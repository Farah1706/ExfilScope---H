<#
.SYNOPSIS
  Starts the ExfilScope platform on 127.0.0.1, opens it in the browser and stops it again.

.DESCRIPTION
  Uses the existing project environments (created by scripts\setup.ps1). It checks the core
  environment and Python version, reports whether the agent environment, embedding cache and
  Ollama model are available (Live Agent mode is disabled without them), finds a free local
  port, starts the control service with a fresh session token and opens the browser.
  Press Enter (or close the window) to stop. Only processes this script started are stopped.
  It changes no global configuration and no certificate trust.

.PARAMETER Port      First local port to try (default 8600; the next 20 are tried if busy).
.PARAMETER EnvRoot   Folder holding .venv, .venv-agent and models (default: repository root).
.PARAMETER NoBrowser Start the service without opening a browser; the link is printed.
#>
param([int]$Port = 8600, [string]$EnvRoot = "", [switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $EnvRoot) { $EnvRoot = $Root }
$EnvRoot = (Resolve-Path $EnvRoot).Path
$Python = Join-Path $EnvRoot ".venv\Scripts\python.exe"

function Say([string]$Text, [string]$Color = "Gray") { Write-Host $Text -ForegroundColor $Color }

Say ""
Say "ExfilScope - local forensic platform" "White"
Say "Repository: $Root"

if (-not (Test-Path $Python)) {
  Say "The core environment (.venv) was not found in $EnvRoot." "Red"
  Say "Create it once with: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Agent -EmbeddingCache" "Yellow"
  exit 1
}
$Version = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($Version -ne "3.13") { Say "The core environment uses Python $Version; ExfilScope requires 3.13." "Red"; exit 1 }
Say "[ok]   Core environment, Python $Version" "Green"

$Agent = Join-Path $EnvRoot ".venv-agent\Scripts\python.exe"
$Cache = Join-Path $EnvRoot "models\all-MiniLM-L6-v2\onnx.tar.gz"
if (Test-Path $Agent) { Say "[ok]   Agent environment" "Green" } else { Say "[--]   Agent environment missing: agent modes will be disabled" "Yellow" }
if (Test-Path $Cache) { Say "[ok]   Embedding cache present (hash verified by the service)" "Green" } else { Say "[--]   Embedding cache missing: agent modes will be disabled" "Yellow" }
try {
  $Tags = Invoke-RestMethod -Uri "http://127.0.0.1:11435/api/tags" -TimeoutSec 3
  if ($Tags.models.name -contains "qwen3:4b-instruct-2507-q4_K_M") { Say "[ok]   Ollama running with qwen3:4b-instruct-2507-q4_K_M" "Green" }
  else { Say "[--]   Ollama is running but the Qwen3 model is not pulled: Live Agent mode will be disabled" "Yellow" }
} catch { Say "[--]   Ollama is not answering: Live Agent mode will be disabled; everything else works" "Yellow" }

function Test-PortFree([int]$Candidate) {
  $listener = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Loopback), $Candidate
  try { $listener.Start(); $listener.Stop(); return $true } catch { return $false }
}
$Chosen = $null
foreach ($Candidate in $Port..($Port + 20)) { if (Test-PortFree $Candidate) { $Chosen = $Candidate; break } }
if (-not $Chosen) { Say "No free local port between $Port and $($Port + 20)." "Red"; exit 1 }
Say "[ok]   Local port $Chosen on 127.0.0.1" "Green"

$Bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($Bytes)
$Token = [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")

$Logs = Join-Path $Root "artifacts\platform-service"
New-Item -ItemType Directory -Force $Logs | Out-Null
$Stamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$OutLog = Join-Path $Logs "service-$Stamp.log"
$ErrLog = Join-Path $Logs "service-$Stamp.err.log"

# Environment for the child only; restored below so this console is left unchanged.
$Saved = @{}
$Child = @{ EXFILSCOPE_UI_TOKEN = $Token; PYTHONUTF8 = "1"; PYTHONPATH = "$Root;$Root\src";
            EXFILSCOPE_ENV_ROOT = $EnvRoot; EXFILSCOPE_AGENT_PYTHON = $Agent;
            EXFILSCOPE_EMBEDDING_CACHE = (Join-Path $EnvRoot "models\all-MiniLM-L6-v2") }
foreach ($Name in $Child.Keys) { $Saved[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process"); [Environment]::SetEnvironmentVariable($Name, $Child[$Name], "Process") }
try {
  $Service = Start-Process -FilePath $Python -ArgumentList @("-B", "-m", "webapp.server", "--port", "$Chosen") `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog
} finally {
  foreach ($Name in $Child.Keys) { [Environment]::SetEnvironmentVariable($Name, $Saved[$Name], "Process") }
}

function Stop-Owned {
  if ($Service -and -not $Service.HasExited) {
    Say "Stopping ExfilScope (process $($Service.Id) and its children)..." "Gray"
    & taskkill.exe /T /F /PID $Service.Id 2>$null | Out-Null
  }
}

try {
  $Url = "http://127.0.0.1:$Chosen"
  $Ready = $false
  $Health = $null
  foreach ($Attempt in 1..60) {
    if ($Service.HasExited) { break }
    try { $Health = Invoke-RestMethod -Uri "$Url/healthz" -TimeoutSec 2; if ($Health.ok) { $Ready = $true; break } } catch { Start-Sleep -Milliseconds 500 }
  }
  if (-not $Ready) {
    Say "The service did not start. Last lines of its error log:" "Red"
    if (Test-Path $ErrLog) { Get-Content $ErrLog -Tail 15 | ForEach-Object { Say "  $_" "Red" } }
    exit 1
  }
  Say "[ok]   Service ready" "Green"
  if (-not $Health.run_owner) {
    Say "[--]   Another ExfilScope service already owns this repository's run folder." "Yellow"
    Say "       This window shows evidence only; start runs from the other window, or close it first." "Yellow"
  }
  $Link = "$Url/#t=$Token"
  if ($NoBrowser) { Say "Open: $Link" "White" } else { Start-Process $Link; Say "Opened ExfilScope in your browser." "White" }
  Say "Keep this window open during the demonstration. Press Enter here to stop ExfilScope." "White"
  [void][Console]::ReadLine()
} finally {
  Stop-Owned
  Say "ExfilScope stopped." "Gray"
}
