<#
.SYNOPSIS
Creates the ExfilScope Python environments from the hash-pinned lock files.

.DESCRIPTION
Always builds the core environment (.venv). -Agent adds .venv-agent,
and -EmbeddingCache downloads Chroma's all-MiniLM-L6-v2 archive and
checks it against the pinned SHA-256. Existing environments are reused and re-checked.
The Ollama model is not installed by this script; see docs/SETUP.md.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Agent -EmbeddingCache
#>
param(
    [switch]$Agent,
    [switch]$EmbeddingCache,
    # Python 3.13 interpreter to create environments with; defaults to "py -3.13".
    [string]$Python
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$EmbeddingSha256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"

function Invoke-Checked([string]$Description, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE) { throw "$Description failed (exit code $LASTEXITCODE)." }
}

function Install-Environment([string]$Name, [string]$Lock, [string[]]$PipOptions) {
    if (-not (Test-Path -LiteralPath (Join-Path $Name "Scripts/python.exe") -PathType Leaf)) {
        Write-Host "Creating $Name"
        if ($Python) { Invoke-Checked "Creating $Name" { & $Python -m venv $Name } }
        else { Invoke-Checked "Creating $Name" { & py -3.13 -m venv $Name } }
    }
    $exe = Join-Path $Name "Scripts\python.exe"
    Invoke-Checked "Python 3.13 check in $Name" {
        & $exe -c "import sys; sys.exit(sys.version_info[:2] != (3, 13))"
    }
    Write-Host "Installing $Lock into $Name"
    Invoke-Checked "Installing $Lock" {
        & $exe -m pip install --disable-pip-version-check --require-hashes @PipOptions -r $Lock
    }
    Invoke-Checked "Dependency check in $Name" { & $exe -m pip check }
}

# Local evidence (ledgers, keys, logs) is written under artifacts/, which Git ignores.
New-Item -ItemType Directory -Force artifacts | Out-Null

Install-Environment ".venv" "requirements.lock" @()
Invoke-Checked "Installing the exfilscope package" {
    & .venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-build-isolation --no-deps -e .
}

if ($Agent -or $EmbeddingCache) {
    Install-Environment ".venv-agent" "requirements-phase2.lock" @("--only-binary", ":all:")
}
if ($EmbeddingCache) {
    $cache = if ($env:EXFILSCOPE_EMBEDDING_CACHE) { $env:EXFILSCOPE_EMBEDDING_CACHE }
             else { "models\all-MiniLM-L6-v2" }
    Write-Host "Preparing the embedding cache in $cache"
    $code = "import sys; from pathlib import Path; " +
            "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2 as E; " +
            "E.DOWNLOAD_PATH = Path(sys.argv[1]); " +
            "E(preferred_providers=['CPUExecutionProvider'])(['warm-up'])"
    Invoke-Checked "Embedding download" { & .venv-agent\Scripts\python.exe -c $code $cache }
    $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $cache "onnx.tar.gz")).Hash.ToLower()
    if ($actual -ne $EmbeddingSha256) {
        throw "Embedding archive checksum mismatch ($actual). Delete $cache and retry."
    }
    Write-Host "Embedding archive verified."
}

Write-Host "Setup complete. Run the test suites listed in docs/SETUP.md."
