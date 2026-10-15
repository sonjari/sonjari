param(
    # ★ 2026-08-22: 기본값이 127.0.0.1 이라 **위성 자비스가 못 닿았다.**
    #   젬마(OLLAMA_HOST)는 0.0.0.0 으로 열어 뒀는데 이쪽만 안 열어서, 나래님
    #   노트북에서 "음성 합성(:7788)에 못 닿습니다" 가 떴다.
    #   같은 일을 두 곳에서 해야 하면 한 곳은 잊는다 — 그 자리다.
    #
    #   방화벽은 테일스케일이 자기 인터페이스를 이미 전부 허용하고 있어서
    #   (Tailscale-In: port=Any) 여는 것은 이 한 줄이면 된다.
    #   JARVIS_SUPERTONIC_HOST 로 되돌릴 수 있다.
    [string]$HostAddress = $(if ($env:JARVIS_SUPERTONIC_HOST) { $env:JARVIS_SUPERTONIC_HOST } else { "0.0.0.0" }),
    [int]$Port = 7788
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Supertonic = Join-Path $ProjectRoot ".venv\Scripts\supertonic.exe"

if (-not (Test-Path -LiteralPath $Supertonic)) {
    throw "Run scripts\install.ps1 -TTS first. Missing: $Supertonic"
}

$LogDirectory = Join-Path $ProjectRoot "outputs"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Process = Start-Process -FilePath $Supertonic -ArgumentList @("serve", "--host", $HostAddress, "--port", [string]$Port) -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $LogDirectory "supertonic.stdout.log") -RedirectStandardError (Join-Path $LogDirectory "supertonic.stderr.log") -WindowStyle Hidden -Wait -PassThru
exit $Process.ExitCode
