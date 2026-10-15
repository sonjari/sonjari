<#
게임이 뜨면 비켜 주고, 끄면 되돌아온다 — 사용자님이 아무것도 안 눌러도.

  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\game_watchdog.ps1
  powershell ... -Once            (한 번만 확인하고 끝. 로그인 직후 정리용)
  powershell ... -Games fczf,다른게임

## 왜 감시 방식인가

FC 온라인은 넥슨 런처(fclauncher) 가 본체(fczf) 를 따로 띄운다. 그래서 "런처를 눌렀나"가
아니라 **본체 프로세스가 떠 있나**를 본다. 5초마다 한 번 `Get-Process` 하는 비용은
사실상 0이고, 게임 시작을 놓치지 않을 만큼은 촘촘하다.

## 안 되면 안 되는 것

**감시기가 죽었을 때 게임 모드에 갇히는 것.** HUD 가 꺼진 채로, QB 배치가 멈춘 채로
남으면 사용자님은 이유도 모른 채 자비스가 고장 났다고 생각하게 된다. 그래서 시작할 때
**항상 먼저 정리한다** — 게임 모드 표시는 있는데 게임이 없으면 즉시 되돌린다.
로그인 트리거가 이 정리를 매번 태워 준다.
## 은퇴 (2026-08-18) — 세 근거가 전부 사라졌다

이 스크립트는 더 이상 자동 실행되지 않는다(`RoboMetaFit-Game-Watchdog` 비활성화).
남겨 두는 것은 아래 실측 기록 때문이지, 다시 쓰라는 뜻이 아니다.

셋 다 전제가 깨졌다:

1. **HUD 종료** — 위의 "27%p" 는 2070 이 **전력 케이블 불량으로 300MHz 에 묶여 있을 때**
   잰 값이었다. 8핀을 다시 꽂아 1875MHz 를 되찾은 뒤 다시 재니 HUD 켬 9~10%,
   끔 9~14% 로 **차이가 없다.** 1/6 속도 카드에서 64% 를 먹던 일이 제 속도에서는
   반올림 오차다.
2. **젬마 VRAM 내리기** — 모니터 2대를 2070 한 장에 몰아서 3090 은 화면이 없다.
   게임은 화면 붙은 2070 에서 그려지므로 3090 을 비울 이유가 없다. 3090 은 상시 자비스.
3. **QB 배치 중지** — QB 생성도 3090 의 올라마(같은 태그)를 쓴다. 게임 카드와 안 겹친다.

그리고 이 스크립트는 실제로 사고를 냈다: `-Off` 의 `Enable-ScheduledTask` 가 권한
부족으로 **조용히 실패**해(`-ErrorAction SilentlyContinue`) `RoboMetaFit-QB-Pool-Scheduler`
가 2026-08-06 부터 12일간 Disabled 로 갇혀 있었다. 되돌리기를 실패해도 아무도 모르는
구조였다 — 되돌림은 성공을 확인해야 한다.

## 복귀 (2026-08-18 밤) — 화면이 3090 으로 오면서 전제가 되살아났다

위 은퇴 판정은 **모니터가 2070 에 있던 동안** 맞는 말이었다. 그날 밤 2070 이 부하에서
클럭이 널뛰는 하드웨어 고장(전원부 의심)으로 판명돼 화면을 전부 3090 으로 옮겼고,
그 순간 세 단계 중 둘이 다시 근거를 얻었다.

    3090 = 화면 2장 + 게임 + 젬마 15.3GB      여유 6.7GB / 24GB

- **젬마 내리기** — 되살렸다. 15.3GB 를 비우면 게임이 카드를 통째로 쓴다.
- **QB 배치 중지** — 되살렸다. QB 생성도 3090 의 올라마를 쓰므로 이제 게임과 같은 카드다.
- **HUD 종료** — 되살리지 **않았다**. `-StopHud` 를 줘야만 끈다. 27%p 는 2026-08-18
  실측에서 재현되지 않았다(켬 9~10% vs 끔 9~14%). 오브 하나 때문에 게임 중 비서를
  통째로 끄지 않는다. 전체화면 독점이 깨져 프레임이 깎이는 별개 경로가 확인되면 그때 켠다.

그리고 **되돌리기가 조용히 실패하던 버그를 고쳤다**(엿새를 날린 그 버그). `-Off` 는 이제
Enable 후 실제 State 를 다시 읽어 확인하고, 실패하면 크게 찍고 상태 파일을 남긴다.
감시기 작업은 관리자 권한으로 등록해야 한다 — 그래야 Enable-ScheduledTask 가 먹는다.

#>

param(
    [string]$RepoRoot = "C:\RoboMetaFit",
    [string[]]$Games = @("fczf"),
    [int]$IntervalSec = 5,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
$GameMode = Join-Path $RepoRoot "tools\alture-jarvis\scripts\game_mode.ps1"
$StateFile = Join-Path $RepoRoot "logs\game_mode_state.json"
$LogFile = Join-Path $RepoRoot "logs\game_watchdog.log"
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null

# 게임 이름을 파일로도 받는다 — 게임이 하나 늘 때마다 스크립트를 고치게 하지 않는다.
$ConfigFile = Join-Path $RepoRoot "logs\game_watchdog_games.txt"
if (Test-Path $ConfigFile) {
    $fromFile = Get-Content $ConfigFile | Where-Object { $_.Trim() -and -not $_.StartsWith("#") } | ForEach-Object { $_.Trim() }
    if ($fromFile) { $Games = $fromFile }
}

function Write-GameLog([string]$message) {
    Add-Content -Path $LogFile -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message) -Encoding UTF8
}

function Test-GameRunning {
    foreach ($name in $Games) {
        if (Get-Process -Name $name -ErrorAction SilentlyContinue) { return $name }
    }
    return $null
}

function Set-GameMode([string]$switch_) {
    # ★ 새 powershell 을 띄우지 않는다. 띄우면 게임을 켜고 끌 때마다 검은 창이
    #   화면 앞으로 튀어나온다 — 게임 중에 그것만큼 짜증나는 게 없다(2026-08-06 실측).
    #   같은 프로세스 안에서 부르면 창도 없고 빠르다. 스크립트 안의 `exit` 는 그
    #   스크립트만 끝내므로 감시기는 계속 산다.
    try {
        $output = if ($switch_ -eq "-On") { & $GameMode -On } else { & $GameMode -Off }
        foreach ($line in @($output)) { Write-GameLog "  $line" }
    } catch {
        Write-GameLog "  게임 모드 전환 실패: $($_.Exception.Message)"
    }
}

# ── 시작할 때 항상 정리한다 ────────────────────────────────────────────────
# 감시기가 죽은 채로 게임이 끝났으면 지금이 되돌릴 유일한 기회다.
$running = Test-GameRunning
$modeOn = Test-Path $StateFile
if ($modeOn -and -not $running) {
    Write-GameLog "정리: 게임 모드가 켜져 있는데 게임이 없다 -> 일반 모드로 되돌린다"
    Set-GameMode "-Off"
    $modeOn = $false
} elseif (-not $modeOn -and $running) {
    Write-GameLog "정리: 게임($running)이 이미 떠 있다 -> 게임 모드로"
    Set-GameMode "-On"
    $modeOn = $true
}

if ($Once) { exit 0 }

# 두 벌이 동시에 돌면 켜고 끄기를 서로 뒤집는다.
$mutex = New-Object System.Threading.Mutex($false, "Global\RoboMetaFit-Game-Watchdog")
if (-not $mutex.WaitOne(0)) {
    Write-GameLog "다른 감시기가 이미 돌고 있어 종료"
    exit 0
}

Write-GameLog "감시 시작: $($Games -join ', ') / ${IntervalSec}초 간격"
try {
    while ($true) {
        Start-Sleep -Seconds $IntervalSec
        $running = Test-GameRunning
        if ($running -and -not $modeOn) {
            Write-GameLog "게임 시작 감지: $running -> 게임 모드"
            Set-GameMode "-On"
            $modeOn = $true
        } elseif (-not $running -and $modeOn) {
            Write-GameLog "게임 종료 감지 -> 일반 모드"
            Set-GameMode "-Off"
            $modeOn = $false
        } elseif ($modeOn -and -not (Test-Path $StateFile)) {
            # 사용자님이 손으로 -Off 를 돌렸다. 감시기가 그걸 뒤집으면 안 된다.
            Write-GameLog "게임 모드가 밖에서 해제됨 - 그대로 따른다"
            $modeOn = $false
        }
    }
} finally {
    $mutex.ReleaseMutex()
}
