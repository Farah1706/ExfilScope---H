# Dot-source in a fresh PowerShell process from an ExfilScope Hackathon distribution.
$HackathonRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Get-ChildItem Env:EXFILSCOPE_* | Remove-Item
foreach ($name in @('artifacts', 'artifacts/local', 'artifacts/local/tmp', 'artifacts/local/pip')) {
    $path = Join-Path $HackathonRoot $name
    if (!(Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Path $path | Out-Null }
    if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "A local output directory is redirected: $path"
    }
}
foreach ($name in @('.venv', '.venv-agent', 'models', 'artifacts/platform-runs')) {
    $path = Join-Path $HackathonRoot $name
    if ((Test-Path -LiteralPath $path) -and
        ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "A project resource is redirected: $path"
    }
}
$env:TEMP = $env:TMP = Join-Path $HackathonRoot 'artifacts/local/tmp'
$env:PIP_CACHE_DIR = Join-Path $HackathonRoot 'artifacts/local/pip'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'