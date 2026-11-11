param([string]$SourceModels = (Join-Path $env:USERPROFILE '.ollama/models'))
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hackathon-environment.ps1')
$relative = 'manifests/registry.ollama.ai/library/qwen3/4b-instruct-2507-q4_K_M'
$pin = '6214d088d3846e16c9fe00adcbabdbfddc61ce4a70daacc46cb2310c38603054'
$store = Join-Path $HackathonRoot 'models/ollama'
$manifest = Join-Path $store $relative
$source = Join-Path $SourceModels $relative
if (!(Test-Path -LiteralPath $manifest) -and !(Test-Path -LiteralPath $source)) {
    throw 'Pinned Qwen3 model is missing. See docs/DEPLOYMENT.md for model preparation.'
}
function Get-ModelSha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}
$reference = if (Test-Path -LiteralPath $manifest) { $manifest } else { $source }
if ((Get-ModelSha256 $reference) -ne $pin) { throw 'Unexpected Qwen3 manifest digest.' }
$client = [Net.Sockets.TcpClient]::new()
try {
    try { $client.Connect('127.0.0.1', 11435) } catch [Net.Sockets.SocketException] {}
    if ($client.Connected) { throw 'Loopback port 11435 is already occupied.' }
} finally { $client.Dispose() }

$null = New-Item -ItemType Directory -Force (Join-Path $store 'blobs'), (Split-Path $manifest)
$metadata = Get-Content -LiteralPath $reference -Raw | ConvertFrom-Json
foreach ($layer in @($metadata.config) + @($metadata.layers)) {
    if ($layer.digest -notmatch '^sha256:([0-9a-f]{64})$') { throw 'Invalid Qwen3 layer digest.' }
    $digest = $Matches[1]
    $name = "blobs/sha256-$digest"
    $target = Join-Path $store $name
    if (!(Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath (Join-Path $SourceModels $name) -Destination $target
    }
    if ((Get-Item -LiteralPath $target).Length -ne $layer.size -or
        (Get-ModelSha256 $target) -ne $digest) { throw "Invalid model layer $digest." }
}
if (!(Test-Path -LiteralPath $manifest)) { Copy-Item -LiteralPath $source -Destination $manifest }
$env:OLLAMA_MODELS = $store
$env:OLLAMA_HOST = '127.0.0.1:11435'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_KEEP_ALIVE = '0'
$env:USERPROFILE = $env:HOME = (New-Item -ItemType Directory -Force (Join-Path $HackathonRoot 'artifacts/local/ollama-home')).FullName
$env:APPDATA = (New-Item -ItemType Directory -Force (Join-Path $env:HOME 'AppData/Roaming')).FullName
$env:LOCALAPPDATA = (New-Item -ItemType Directory -Force (Join-Path $env:HOME 'AppData/Local')).FullName
Write-Host 'Hackathon Qwen3 listener on 127.0.0.1:11435. Press Ctrl+C to stop.'
& (Get-Command ollama.exe -ErrorAction Stop).Source serve
exit $LASTEXITCODE