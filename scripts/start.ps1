param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8091
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Run scripts\install.ps1 first. Missing: $VenvPython"
}

$env:JARVIS_RUNTIME_ROOT = $ProjectRoot
$env:JARVIS_HOST = $HostAddress
$env:JARVIS_PORT = [string]$Port
# Keep the user's global GPU policy untouched; Jarvis alone needs cuda:1.
$env:CUDA_VISIBLE_DEVICES = "0,1"
$LogDirectory = Join-Path $ProjectRoot "outputs"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Process = Start-Process -FilePath $VenvPython -ArgumentList @("-m", "alture_jarvis") -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $LogDirectory "jarvis.stdout.log") -RedirectStandardError (Join-Path $LogDirectory "jarvis.stderr.log") -WindowStyle Hidden -Wait -PassThru
exit $Process.ExitCode
