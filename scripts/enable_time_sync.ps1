<#
윈도우 시간 동기화를 켠다 (W32Time).

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\enable_time_sync.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\enable_time_sync.ps1 -Revert

관리자 권한이 필요해서 실행하면 **한 번 「허용」을 눌러 달라고 뜬다.**

## 왜 (2026-08-21 실측)

`W32Time` 서비스가 **Stopped · StartType=Manual** 이었다. 인터넷 시각과 맞추는
일을 아무도 안 하고 있었다는 뜻이다.

다만 **시계 자체는 그때 정확했다.** 바깥 세 곳과 대조한 값:

    google.com      -0.5초
    cloudflare.com  -0.1초
    naver.com       +0.1초

그래서 이 스크립트는 「고장을 고치는 것」이 아니라 **앞으로 밀리지 않게 하는 것**이다.
메인보드 시계는 하루 몇 초씩 밀리므로 몇 달 두면 분 단위로 어긋난다.

## 무엇을 바꾸나 — 하나뿐이다

    W32Time StartType   Manual → Automatic   그리고 시작
    그 뒤 `w32tm /resync` 로 즉시 한 번 맞춘다

**NTP 서버와 주기는 안 건드린다.** 이미 정상이다(`time.windows.com,0x9` ·
4.5시간마다). 고칠 이유가 없는 것을 같이 바꾸면 되돌릴 것만 늘어난다.
(한국 서버로 바꾸고 싶으면 `w32tm /config /manualpeerlist:"kr.pool.ntp.org,0x9" /update`
를 따로 하면 된다 — 이 스크립트는 안 한다.)

## 자비스와의 관계

자비스는 이미 날짜·시각을 **정확히 안다.** 시스템 프롬프트에 `clock.now_line_ko`
가 들어가고, 2026-08-21 00:35 에 물었을 때 "2026년 8월 21일 금요일 00:35" 로
정확히 답했다.

★ 그러니 **자비스가 「최신 GPT 모델」 같은 것을 틀리게 답하는 것은 시계 문제가
아니다.** 그건 학습 데이터가 끊긴 시점 이후를 모르는 것이고, 답은 시계가 아니라
**가서 보게 하는 것**이다. 시계는 「오늘이 며칠인가」를 답하게 해 줄 뿐,
「오늘 세상에 뭐가 나왔나」를 답하게 해 주지 않는다.

## 되돌리기

바꾸기 **전** StartType 을 적어 두고 `-Revert` 가 그대로 돌린다.
`C:\ProgramData\RoboMetaFit\time_sync_backup.json`
#>

param(
    [switch]$Revert
)

$ErrorActionPreference = "Stop"

# ── 관리자 권한이 아니면 스스로 올린다 (여기서 「허용」 창이 뜬다) ──────────────
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host ""
    Write-Host "  관리자 권한이 필요합니다. 「허용」을 눌러 주세요." -ForegroundColor Yellow
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($Revert) { $arguments += "-Revert" }
    try {
        Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arguments
    } catch {
        Write-Host "  「허용」을 누르지 않아 아무것도 바꾸지 않았습니다." -ForegroundColor Red
    }
    exit 0
}

$BackupDir  = Join-Path $env:ProgramData "RoboMetaFit"
$BackupFile = Join-Path $BackupDir "time_sync_backup.json"

function Show-State($label) {
    $svc = Get-Service W32Time
    $ntp = (Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Parameters" -Name NtpServer -ErrorAction SilentlyContinue).NtpServer
    Write-Host ""
    Write-Host "  $label" -ForegroundColor Cyan
    Write-Host ("    {0,-22} {1}" -f "서비스 상태", $svc.Status)
    Write-Host ("    {0,-22} {1}" -f "시작 유형", $svc.StartType)
    Write-Host ("    {0,-22} {1}" -f "NTP 서버", $ntp)
}

# 바깥 시각과 대조한다. **동기화를 켰다는 말은 시계가 맞다는 증거가 아니다.**
function Show-Drift {
    Write-Host ""
    Write-Host "  바깥 시각과 대조" -ForegroundColor Cyan
    foreach ($url in @("https://www.naver.com", "https://www.cloudflare.com")) {
        try {
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $resp = Invoke-WebRequest -Uri $url -Method Head -TimeoutSec 10 -UseBasicParsing
            $sw.Stop()
            $server = [DateTime]::Parse($resp.Headers["Date"]).ToUniversalTime()
            $drift = ([DateTime]::UtcNow - $server).TotalSeconds - ($sw.Elapsed.TotalSeconds / 2)
            $host_name = ([Uri]$url).Host
            Write-Host ("    {0,-22} {1,+7:0.0}초" -f $host_name, $drift)
        } catch {
            Write-Host ("    {0,-22} 조회 실패" -f ([Uri]$url).Host)
        }
    }
}

# ── 되돌리기 ─────────────────────────────────────────────────────────────────
if ($Revert) {
    if (-not (Test-Path -LiteralPath $BackupFile)) {
        Write-Host ""
        Write-Host "  되돌릴 기록이 없습니다: $BackupFile" -ForegroundColor Red
        Write-Host "  이 스크립트로 바꾼 적이 없다는 뜻입니다. 아무것도 안 건드렸습니다."
        Read-Host "`n  엔터를 누르면 닫힙니다"
        exit 1
    }
    Show-State "되돌리기 전"
    $saved = Get-Content -LiteralPath $BackupFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ("$($saved.Status)" -ne "Running") {
        Stop-Service W32Time -Force -ErrorAction SilentlyContinue
    }
    Set-Service -Name W32Time -StartupType $saved.StartType
    Show-State "되돌린 뒤"
    Write-Host ""
    Write-Host "  원래대로 돌렸습니다. 시계가 다시 인터넷과 안 맞춰집니다." -ForegroundColor Yellow
    Read-Host "`n  엔터를 누르면 닫힙니다"
    exit 0
}

# ── 켜기 ─────────────────────────────────────────────────────────────────────
Show-State "바꾸기 전"
Show-Drift

$svc = Get-Service W32Time
if (-not (Test-Path -LiteralPath $BackupDir)) { New-Item -Path $BackupDir -ItemType Directory -Force | Out-Null }
if (-not (Test-Path -LiteralPath $BackupFile)) {
    # 바꾸기 **전에** 적는다. 이걸 먼저 안 하면 되돌릴 방법이 없다.
    @{
        StartType = "$($svc.StartType)"
        Status    = "$($svc.Status)"
        saved_at  = (Get-Date).ToString("s")
    } | ConvertTo-Json | Out-File -LiteralPath $BackupFile -Encoding utf8
    Write-Host ""
    Write-Host "  되돌릴 값을 적어 뒀습니다: $BackupFile" -ForegroundColor DarkGray
} else {
    # 두 번째 실행이다. 첫 기록을 덮지 않는다 — 덮으면 이미 켠 상태가 "원래"로
    # 기록돼 되돌리기가 아무 일도 안 하게 된다.
    Write-Host ""
    Write-Host "  이미 기록이 있어 그대로 둡니다: $BackupFile" -ForegroundColor DarkGray
}

Set-Service -Name W32Time -StartupType Automatic
Start-Service W32Time
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "  인터넷 시각과 맞추는 중..." -ForegroundColor DarkGray
# ★ PS 5.1 은 네이티브 stderr 를 `2>&1` 로 합치면 `Stop` 아래서 터미네이팅으로
#   만든다. w32tm 은 시각이 안 맞을 때 stderr 로 말하는데, 그때 죽으면 아래의
#   「정말 도는가」 확인이 통째로 안 돈다 — 확인하려고 만든 스크립트가 확인 직전에
#   죽는 셈이다.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& w32tm /resync /force 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
$ErrorActionPreference = $prevEap

Show-State "바꾼 뒤"
Show-Drift

# 켰다는 말은 증거가 아니다. 서비스가 정말 도는지 다시 읽는다.
$after = Get-Service W32Time
Write-Host ""
if ($after.Status -eq "Running" -and "$($after.StartType)" -eq "Automatic") {
    Write-Host "  켰습니다. 이제 부팅할 때마다 시계를 인터넷과 맞춥니다." -ForegroundColor Green
    Write-Host ""
    Write-Host "  되돌리려면 같은 파일에 -Revert 를 붙여 실행하세요." -ForegroundColor DarkGray
} else {
    Write-Host "  ★ 안 켜졌습니다 (상태 $($after.Status) · 시작 $($after.StartType))" -ForegroundColor Red
    Write-Host "    회사 정책(그룹 정책)이 막고 있을 수 있습니다."
}

Read-Host "`n  엔터를 누르면 닫힙니다"
