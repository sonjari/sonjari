param(
    [switch]$Hardware,
    [switch]$TTS
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    python -m venv (Join-Path $ProjectRoot ".venv")
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -e "$ProjectRoot[test]"

if ($Hardware) {
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-torch-cuda.txt")
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-stt-cuda.txt")
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-hardware.txt")
}

if ($TTS) {
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-tts.txt")
}

Write-Host "ALTURE JARVIS dependencies installed: $VenvPython"
