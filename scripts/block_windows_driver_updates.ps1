<#
윈도우 업데이트가 그래픽 드라이버를 멋대로 갈아끼우지 못하게 막는다.

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\block_windows_driver_updates.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\block_windows_driver_updates.ps1 -Revert

관리자 권한이 필요해서 실행하면 **한 번 「허용」을 눌러 달라고 뜬다.** 그 창이 뜨는 것이
정상이다 — 레지스트리의 시스템 영역을 건드리기 때문이다.

## 왜 만들었나 (2026-08-20 실측)

  20:54  자비스 화면 배포 정상 완료
  22:13  윈도우 업데이트가 「NVIDIA - Display - 32.0.15.6094」 설치
         그 드라이버는 **2024-08-14 자**였고 새로 꽂은 3060 에만 붙었다
         3090 은 32.0.16.1088 을 물고 있다가 결합이 깨져 **Error 31** 로 떨어졌다
  결과   젬마 14GB 가 갈 곳을 잃고 CPU 로 내려감

         정상   130 tok/s
         고장   2.3 tok/s      ← 55배. 자비스를 못 쓰는 상태였다

재부팅으로는 안 돌아왔고 NVIDIA 드라이버를 깨끗한 설치로 다시 깔아야 했다.
카드는 처음부터 멀쩡했다(PCI 버스에 계속 보였다) — 순전히 드라이버 사고다.

## 무엇을 바꾸나 — 세 값뿐이다

  SearchOrderConfig                 1 → 0   윈도우가 드라이버를 자동으로 찾지 않는다
                                            (sysdm.cpl → 하드웨어 → 장치 설치 설정 → 「아니요」)
  PreventDeviceMetadataFromNetwork  0 → 1   장치 아이콘·이름을 인터넷에서 안 받는다
  ExcludeWUDriversInQualityUpdate   - → 1   품질 업데이트에 드라이버를 끼워 넣지 않는다
                                            ★ 이번 사고를 실제로 막는 값이 이것이다

## 대가 (알고 쓰셔야 한다)

새 장치를 꽂았을 때 윈도우가 드라이버를 자동으로 안 깔아 준다. 프린터·웹캠 같은 것을
새로 연결하면 제조사에서 직접 받아야 할 수 있다. 그때는 `-Revert` 로 잠깐 풀고
설치한 뒤 다시 걸면 된다.

## 되돌리기

바꾸기 **전** 값을 파일에 적어 둔다. `-Revert` 는 그 파일을 읽어 원래대로 돌린다 —
"0 으로 되돌린다"가 아니라 **원래 있던 값 그대로**다(원래 없던 값은 다시 지운다).

    C:\ProgramData\RoboMetaFit\driver_update_policy_backup.json
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

# ── 바꿀 자리 세 곳 ───────────────────────────────────────────────────────────
$Targets = @(
    @{
        Path  = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching"
        Name  = "SearchOrderConfig"
        Block = 0
        What  = "드라이버 자동 검색"
    },
    @{
        Path  = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Device Metadata"
        Name  = "PreventDeviceMetadataFromNetwork"
        Block = 1
        What  = "장치 메타데이터 내려받기"
    },
    @{
        Path  = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
        Name  = "ExcludeWUDriversInQualityUpdate"
        Block = 1
        What  = "품질 업데이트에 드라이버 포함"
    }
)

$BackupDir  = Join-Path $env:ProgramData "RoboMetaFit"
$BackupFile = Join-Path $BackupDir "driver_update_policy_backup.json"

function Read-Value($path, $name) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $item = Get-ItemProperty -LiteralPath $path -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    return $item.$name
}

function Show-State($label) {
    Write-Host ""
    Write-Host "  $label" -ForegroundColor Cyan
    foreach ($t in $Targets) {
        $v = Read-Value $t.Path $t.Name
        if ($null -eq $v) { $shown = "(없음)" } else { $shown = "$v" }
        Write-Host ("    {0,-34} {1,-8} {2}" -f $t.Name, $shown, $t.What)
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
    foreach ($t in $Targets) {
        $before = $saved.($t.Name)
        if ($null -eq $before -or "$before" -eq "") {
            # 원래 없던 값이다. 0 으로 만들지 않고 **지운다** — 없는 것과 0 은 다르다.
            Remove-ItemProperty -LiteralPath $t.Path -Name $t.Name -ErrorAction SilentlyContinue
        } else {
            if (-not (Test-Path -LiteralPath $t.Path)) { New-Item -Path $t.Path -Force | Out-Null }
            New-ItemProperty -LiteralPath $t.Path -Name $t.Name -Value ([int]$before) -PropertyType DWord -Force | Out-Null
        }
    }
    Show-State "되돌린 뒤"
    Write-Host ""
    Write-Host "  원래대로 돌렸습니다. 윈도우 업데이트가 다시 드라이버를 깔 수 있습니다." -ForegroundColor Yellow
    Read-Host "`n  엔터를 누르면 닫힙니다"
    exit 0
}

# ── 막기 ─────────────────────────────────────────────────────────────────────
Show-State "바꾸기 전"

# 바꾸기 **전에** 지금 값을 적어 둔다. 이걸 먼저 안 하면 되돌릴 방법이 없다.
if (-not (Test-Path -LiteralPath $BackupDir)) { New-Item -Path $BackupDir -ItemType Directory -Force | Out-Null }
if (-not (Test-Path -LiteralPath $BackupFile)) {
    $snapshot = @{}
    foreach ($t in $Targets) {
        $v = Read-Value $t.Path $t.Name
        if ($null -eq $v) { $snapshot[$t.Name] = "" } else { $snapshot[$t.Name] = [int]$v }
    }
    $snapshot["saved_at"] = (Get-Date).ToString("s")
    $snapshot | ConvertTo-Json | Out-File -LiteralPath $BackupFile -Encoding utf8
    Write-Host ""
    Write-Host "  되돌릴 값을 적어 뒀습니다: $BackupFile" -ForegroundColor DarkGray
} else {
    # 두 번째 실행이다. 첫 기록을 **덮어쓰지 않는다** — 덮으면 이미 막힌 값이
    # "원래 값"으로 기록돼 되돌리기가 아무 일도 안 하게 된다.
    Write-Host ""
    Write-Host "  이미 기록이 있어 그대로 둡니다: $BackupFile" -ForegroundColor DarkGray
}

foreach ($t in $Targets) {
    if (-not (Test-Path -LiteralPath $t.Path)) { New-Item -Path $t.Path -Force | Out-Null }
    New-ItemProperty -LiteralPath $t.Path -Name $t.Name -Value $t.Block -PropertyType DWord -Force | Out-Null
}

Show-State "바꾼 뒤"

# 바꿨다는 말은 증거가 아니다. 다시 읽어서 확인한다.
$bad = @()
foreach ($t in $Targets) {
    $v = Read-Value $t.Path $t.Name
    if ("$v" -ne "$($t.Block)") { $bad += $t.Name }
}

Write-Host ""
if ($bad.Count -gt 0) {
    Write-Host "  ★ 안 먹은 값이 있습니다: $($bad -join ', ')" -ForegroundColor Red
    Write-Host "    회사 정책(그룹 정책)이 덮어쓰고 있을 수 있습니다."
} else {
    Write-Host "  막았습니다. 윈도우 업데이트가 그래픽 드라이버를 갈아끼우지 않습니다." -ForegroundColor Green
    Write-Host "  드라이버는 이제 NVIDIA 사이트에서 직접 받아 까시면 됩니다."
    Write-Host ""
    Write-Host "  되돌리려면 같은 파일에 -Revert 를 붙여 실행하세요." -ForegroundColor DarkGray
}

Read-Host "`n  엔터를 누르면 닫힙니다"
