#Requires -Version 5.1
<#
.SYNOPSIS
  위성에서 **한 줄로** 본체의 최신 판을 받아 깐다. 갱신 기능이 아직 없는 위성용.

.DESCRIPTION
  닭과 달걀을 푸는 자리다. 위성이 스스로 갱신하려면 갱신하는 코드가 먼저 그
  위성에 있어야 하는데, 이미 깔린 위성(나래님 노트북)에는 그게 없다.

  이 스크립트는 자비스를 거치지 않고 **직접** 본체에서 받아 깐다. 한 번만 쓰면
  그다음부터는 화면의 「지금 받기」로 된다.

  받는 것·거르는 것·확인하는 것은 전부 `updater.py` 와 `apply_update.ps1` 이
  하던 것과 같다 — 다른 규칙을 쓰면 이 경로로만 이상해진다.

.EXAMPLE
  # 위성 PC 에서 (설정은 .env 에서 읽는다)
  .\bootstrap_update.ps1

.EXAMPLE
  # 주소·토큰을 직접 줄 때
  .\bootstrap_update.ps1 -BrainHost 100.64.0.10 -ControlToken <토큰>

.NOTES
  이 스크립트는 **되돌리기를 갖고 있다** — apply_update.ps1 에 넘기기 때문이다.
  새 판이 안 뜨면 옛 판으로 돌아간다.
#>
[CmdletBinding()]
param(
    [string] $BrainHost = "",
    [string] $ControlToken = "",
    [string] $Root = "C:\RoboMetaFit\tools\alture-jarvis",
    # 판이 같아 보여도 그냥 다시 깐다.
    #
    # ★ 아래 2번의 견줌은 `build` 하나로만 한다 — 그 값은 `src/alture_jarvis/*.py`
    #   만 센다. 그래서 **파일은 새 판인데 자비스가 꺼져 있는** 반쯤 바뀐 PC 에서
    #   이 스크립트는 "할 일이 없습니다"라고 답하고 나간다. 그때 필요한 것이 이것이다.
    #   `repair_satellite.ps1` 이 이 갈래로 들어온다.
    [switch] $Force
)

$ErrorActionPreference = "Stop"

function Say($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Ok($msg)  { Write-Host "  OK  $msg" -ForegroundColor Green }
function Die($msg) { Write-Host "  !!  $msg" -ForegroundColor Red; exit 1 }

# ── 설정 읽기 ────────────────────────────────────────────────────────────────
#
# 새 값을 요구하지 않는다. 위성은 본체 주소와 토큰을 **이미** 갖고 있다 —
# 하나 더 물어보면 그만큼 틀릴 자리가 는다.
$envPath = Join-Path $Root ".env"
if ((-not $BrainHost -or -not $ControlToken) -and (Test-Path -LiteralPath $envPath)) {
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^\s*JARVIS_OLLAMA_BASE_URL\s*=\s*https?://([^:/\s]+)' -and -not $BrainHost) {
            $BrainHost = $Matches[1]
        }
        if ($line -match '^\s*JARVIS_BRAIN_HOST\s*=\s*(\S+)' -and -not $BrainHost) {
            $BrainHost = $Matches[1]
        }
        if ($line -match '^\s*JARVIS_CONTROL_TOKEN\s*=\s*(\S+)' -and -not $ControlToken) {
            $ControlToken = $Matches[1]
        }
    }
}
if (-not $BrainHost)    { Die ".env 에서 본체 주소를 못 찾았습니다. -BrainHost 로 주세요." }
if (-not $ControlToken) { Die ".env 에서 토큰을 못 찾았습니다. -ControlToken 으로 주세요." }
if (-not (Test-Path -LiteralPath $Root)) { Die "설치본이 없습니다: $Root" }

# 주소를 그대로 받는다. 테일스케일 Serve 를 쓰면 `https://node.xxx.ts.net` 처럼
# 전체 URL 이 오고, 직접 여는 방식이면 `100.64.0.10` 처럼 호스트만 온다.
# 두 방식을 오갈 때 이 스크립트를 고치지 않아도 되게 여기서 갈래를 둔다.
$base = if ($BrainHost -match '^https?://') { $BrainHost.TrimEnd('/') } else { "http://${BrainHost}:8091" }
$headers = @{ "X-JARVIS-TOKEN" = $ControlToken }
Say "본체 $base"

# ── 1. 본체에 닿는지부터 ─────────────────────────────────────────────────────
#
# ★ 이걸 먼저 하는 이유는 install_satellite.ps1 과 같다: 다 받아 놓고 "본체를
#   못 찾습니다"가 뜨면 어디서 틀렸는지 알 수가 없다.
try {
    $manifest = Invoke-RestMethod -Uri "$base/v1/update/manifest" -Headers $headers -TimeoutSec 25
} catch {
    Die "본체에 못 닿습니다: $_`n     테일스케일이 켜져 있는지, 토큰이 같은지 보세요."
}
Ok ("본체 판 {0} · {1}개 · {2}MB" -f $manifest.build, $manifest.file_count, [math]::Round($manifest.total_bytes / 1MB, 1))

# ── 2. 내 판과 견주기 ────────────────────────────────────────────────────────
$mine = ""
$minePayload = ""
try {
    $mine = [string](Invoke-RestMethod -Uri "http://127.0.0.1:8091/health" -TimeoutSec 8).build
} catch {
    Say "이 PC 자비스가 응답을 안 합니다(꺼져 있거나 옛 판). 그대로 진행합니다."
}
# ★ **`build` 로만 견주면 안 된다** (2026-09-11).
#
#   `build` 는 src/alture_jarvis/*.py 만 센다. 그래서 exe(화면)와 scripts 만
#   바뀐 판에서는 값이 그대로다. 실제로 오늘 그 상태를 만들었다:
#
#       build       396baf3dc65a -> 396baf3dc65a   (안 바뀜)
#       payload_id  3a78fb4310c5 -> 0a264fa1c6ec   (바뀜)
#
#   이 상태에서 아래 검사가 "이미 같은 판입니다"로 빠져나가면 **새 화면이 영영
#   안 닿는다.** runtime.update_check() 는 이 구멍을 이미 payload_id 로 고쳐
#   놨는데 이 스크립트만 안 고쳐져 있었다 — 한 벌만 고치고 고쳤다고 믿은 것이다.
#
#   내 payload_id 는 이 PC 자비스의 manifest 에서 받는다. PowerShell 에서 다시
#   구현하면 두 벌이 되고, 두 벌은 반드시 갈린다.
try {
    $local = Invoke-RestMethod -Uri "http://127.0.0.1:8091/v1/update/manifest" -Headers $headers -TimeoutSec 8
    $minePayload = [string]$local.payload_id
} catch {
    Say "이 PC 의 payload_id 를 못 읽었습니다. 같은 판인지 확신할 수 없으니 그냥 받습니다."
}
$remotePayload = [string]$manifest.payload_id
# ★ **모르면 받는다.** 잘못 「같다」고 하면 갱신이 통째로 사라지고, 잘못 받으면
#   몇 MB 와 재기동 한 번이다. 확신이 없으면 받는 쪽으로 기운다.
$sameBuild   = ($mine -and $mine -eq $manifest.build)
$samePayload = ($remotePayload -and $minePayload -and $minePayload -eq $remotePayload)
if ($remotePayload) { $nothingToDo = ($sameBuild -and $samePayload) } else { $nothingToDo = $sameBuild }
if ($nothingToDo -and -not $Force) {
    Ok "이미 같은 판입니다 ($mine / $minePayload). 할 일이 없습니다."
    exit 0
}
if ($Force -and $nothingToDo) { Say "판은 같지만 -Force 라 그대로 다시 깝니다." }
if ($mine) { Say "이 PC $mine  ->  본체 $($manifest.build)" }
if ($remotePayload -and $sameBuild -and -not $samePayload) {
    Say "파이썬은 같지만 화면·스크립트가 다릅니다 ($minePayload -> $remotePayload)."
}

# ── 3. 받기 ──────────────────────────────────────────────────────────────────
$work = Join-Path $Root "data\update"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$zip = Join-Path $work "incoming.zip"
Say "받는 중…"
Invoke-WebRequest -Uri "$base/v1/update/payload" -Headers $headers -OutFile $zip -TimeoutSec 600 -UseBasicParsing
Ok ("받음 {0}MB" -f [math]::Round((Get-Item $zip).Length / 1MB, 1))

# ── 4. 풀고 **확인** ─────────────────────────────────────────────────────────
#
# 확인 전에는 설치본을 하나도 안 건드린다.
$staging = Join-Path $work "staged"
if (Test-Path -LiteralPath $staging) { Remove-Item -Recurse -Force -LiteralPath $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $staging)

# 푼 것의 판 지문을 config.build_id 와 **같은 규칙**으로 센다.
$pkg = Join-Path $staging "src\alture_jarvis"
if (-not (Test-Path -LiteralPath $pkg)) { Die "받은 것에 src\alture_jarvis 가 없습니다." }
$sha = [System.Security.Cryptography.SHA256]::Create()
$buffer = New-Object System.IO.MemoryStream
foreach ($f in (Get-ChildItem -LiteralPath $pkg -Filter *.py | Sort-Object Name)) {
    $nameBytes = [System.Text.Encoding]::UTF8.GetBytes($f.Name)
    $buffer.Write($nameBytes, 0, $nameBytes.Length)
    $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
    $buffer.Write($bytes, 0, $bytes.Length)
}
$staged = ([BitConverter]::ToString($sha.ComputeHash($buffer.ToArray())) -replace '-', '').ToLower().Substring(0, 12)
if ($staged -ne $manifest.build) {
    Die "받은 것의 판이 다릅니다 ($staged != $($manifest.build)). 갈아치우지 않습니다."
}
Ok "확인 완료 · 판 $staged"

# ── 5. 교체는 apply_update.ps1 에 맡긴다 ─────────────────────────────────────
#
# 되돌리기·확인이 거기 있다. 여기서 또 쓰면 두 벌이 되고, 두 벌은 반드시 갈린다.
$plan = @{
    root           = $Root
    staging        = $staging
    expected_build = $manifest.build
    dirs           = @("src", "recipes", "skills", "knowledge", "scripts")
    files          = @("pyproject.toml", "requirements.txt", "requirements-hardware.txt", "requirements-stt-cuda.txt")
    hud            = "ui/alture-jarvis-hud.exe"
    health_url     = "http://127.0.0.1:8091/health"
}
$planPath = Join-Path $work "plan.json"
$plan | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $planPath -Encoding UTF8

# ★ 받은 것 안의 스크립트를 쓴다. 설치본 것은 낡았을 수 있다(그래서 지금 받는 것이다).
$script = Join-Path $staging "scripts\apply_update.ps1"
if (-not (Test-Path -LiteralPath $script)) {
    $script = Join-Path $Root "scripts\apply_update.ps1"
}
if (-not (Test-Path -LiteralPath $script)) { Die "교체 스크립트를 못 찾았습니다." }

Say "갈아치웁니다 (로그: $work\apply.log)"

# ★ 여기서 죽으면 안 된다 (2026-08-24).
#
#   PowerShell 5.1 은 네이티브 명령이 stderr 로 뭘 쓰면 `Stop` 아래서 그걸
#   터미네이팅 에러로 만든다. 이 줄이 죽으면 아래의 「무슨 일이 일어났나」를
#   못 읽고, 그러면 이 스크립트가 아무 말도 못 하게 된다.
$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& powershell -NoProfile -ExecutionPolicy Bypass -File $script -Plan $planPath
$code = $LASTEXITCODE
$ErrorActionPreference = $previous

# ── 무슨 일이 실제로 일어났나 ────────────────────────────────────────────────
#
# ★ 종료코드로 짐작하지 않는다. 2026-08-24 에 이 자리가 「갱신 실패 — 되돌렸습니다」
#   라고 찍었는데, 그때 되돌리기는 **한 번도 돈 적이 없었다**(교체 스크립트가
#   5단계에서 죽어 6·7 이 통째로 안 돌았다). 파일은 새 판이고 자비스는 꺼져
#   있는데 화면은 "되돌렸다"고 말한 것 — 이 저장소에서 제일 나쁜 종류의 거짓이다.
#
#   이제 교체 스크립트가 result.json 에 적고, 여기서는 그것만 읽는다.
$resultPath = Join-Path $work "result.json"
$result = $null
if (Test-Path -LiteralPath $resultPath) {
    try { $result = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}

function Show-Tail {
    $log = Join-Path $work "apply.log"
    if (Test-Path -LiteralPath $log) {
        Write-Host "  --- apply.log 마지막 12줄 ---" -ForegroundColor DarkGray
        Get-Content -LiteralPath $log -Tail 12 -Encoding UTF8 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    }
}

if (-not $result) {
    Show-Tail
    Die ("결과를 못 읽었습니다 (종료코드 $code). **무슨 일이 일어났는지 모릅니다** - " +
         "반쯤 바뀌었을 수 있습니다. 자비스가 떠 있는지 직접 보세요: $work")
}

switch ($result.result) {
    "success" {
        Ok "갱신 성공 · 판 $($result.build)"
    }
    "stopped_no_change" {
        Show-Tail
        Die "아무것도 바꾸지 않고 멈췄습니다: $($result.note)"
    }
    "rolled_back" {
        Show-Tail
        Die "갱신 실패 - 되돌렸고, 자비스가 다시 응답합니다(판 $($result.build)). 로그: $work\apply.log"
    }
    "half_applied" {
        Show-Tail
        Die ("★ 반쯤 바뀐 채로 남았습니다. 되돌렸지만 자비스가 응답하지 않습니다. " +
             "사람이 봐야 합니다: $work")
    }
    "started" {
        Show-Tail
        Die ("★ 교체 스크립트가 중간에 멈췄습니다(종료코드 $code). **되돌렸는지 알 수 없습니다.** " +
             "백업은 $work 안에 있습니다. 자비스가 떠 있는지 먼저 보세요.")
    }
    default {
        Show-Tail
        Die "알 수 없는 결과 '$($result.result)' (종료코드 $code). 로그: $work\apply.log"
    }
}
