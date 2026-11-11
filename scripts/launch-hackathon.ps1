param([string]$Python, [switch]$NoBrowser, [switch]$Live)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hackathon-environment.ps1')
$core = Join-Path $HackathonRoot '.venv/Scripts/python.exe'
function Test-CoreReady {
    if (!(Test-Path -LiteralPath $core -PathType Leaf)) { return $false }
    try {
        & $core -I -B -c 'import sys, fastapi, uvicorn, mitmproxy, exfilscope; sys.exit(sys.version_info[:2] != (3, 13))' 2>$null | Out-Null
    } catch { return $false }
    return $LASTEXITCODE -eq 0
}
if (!(Test-CoreReady)) {
    if (!$Python -and !(Get-Command py.exe -ErrorAction SilentlyContinue)) {
        throw 'Python 3.13 x64 with the Windows Python launcher is required. Install it or pass -Python to scripts/launch-hackathon.ps1.'
    }
    Write-Host 'Setting up or repairing locked core dependencies. Python 3.13 x64 and internet access are required.'
    if ($Python) { & (Join-Path $PSScriptRoot 'setup.ps1') -Python $Python }
    else { & (Join-Path $PSScriptRoot 'setup.ps1') }
    if (!(Test-CoreReady)) { throw 'Core imports failed after setup. Review the setup output before starting a run.' }
}
$model = $null
try {
    if ($Live) {
        $modelScript = Join-Path $PSScriptRoot 'serve-hackathon-model.ps1'
        $stdout = Join-Path $HackathonRoot 'artifacts/local/live-model.log'
        $stderr = Join-Path $HackathonRoot 'artifacts/local/live-model-error.log'
        $client = [Net.Sockets.TcpClient]::new()
        try {
            try { $client.Connect('127.0.0.1', 11435) } catch [Net.Sockets.SocketException] {}
            if ($client.Connected) { throw 'Port 11435 is occupied. Stop the dedicated listener or use the normal launcher.' }
        } finally { $client.Dispose() }
        Write-Host 'Starting isolated Qwen3. Initial asset verification can take a minute.'
        $model = Start-Process -FilePath powershell.exe -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $modelScript + '"')
        ) -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $ready = $false
        for ($attempt = 0; $attempt -lt 150 -and !$model.HasExited; $attempt++) {
            try {
                $null = Invoke-RestMethod 'http://127.0.0.1:11435/api/tags' -TimeoutSec 2
                $ready = $true
                break
            } catch { Start-Sleep -Milliseconds 500 }
        }
        if (!$ready) { throw 'Qwen3 failed to start. Check artifacts/local/live-model-error.log, or use the scripted launcher.' }
    }
    & (Join-Path $PSScriptRoot 'start-exfilscope.ps1') -EnvRoot $HackathonRoot -Port 8700 -NoBrowser:$NoBrowser
    $code = $LASTEXITCODE
} finally {
    if ($model -and !$model.HasExited) { & taskkill.exe /T /F /PID $model.Id 2>$null | Out-Null }
}
exit $code