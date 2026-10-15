<#
게임 모드 — 사용자님이 FC 온라인 할 때 PC를 비켜 준다.

  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\game_mode.ps1 -On
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\game_mode.ps1 -Off

## 왜 이게 필요한가 (2026-08-06 실측)

모니터가 RTX 2070 에 물려 있다. 바탕화면·크롬·카톡·자비스 HUD 가 전부 그 8GB 카드에서
돌고, 24GB 짜리 3090 은 젬마를 15GB 얹은 채 **0%** 로 논다. 게임도 화면이 붙은 GPU 에서
그려지므로 FC 온라인은 이미 반쯤 찬 2070 위에서 시작한다.

그 위에 자비스 HUD 가 얹혀 있었다. 실측:

    HUD 켜짐(18시간째)   2070 = 64%
    HUD 끔               2070 = 37%    <- 27%p 가 오브 하나
    HUD 새로 켬          2070 = 39%    <- 오래 켤수록 나빠진다

오브에 애니메이션은 없다. **투명 + 항상 위 + backdrop-filter: blur()** 조합이라
뒤에 있는 바탕화면을 100Hz 로 계속 다시 합성한다 — 가만히 있어도 GPU 를 간다.

## 이 스크립트가 하는 일

  1. 자비스 HUD 종료          (2070 에서 ~25%p 회수. 백엔드와 F9 는 그대로 살아 있다)
  2. 젬마를 VRAM 에서 내림    (3090 에 15GB 반납 — 게임을 3090 으로 돌릴 때 쓸 수 있게)
  3. QB 풀 스케줄러·수퍼바이저 일시 중지 (게임 중에 생성이 끼어들지 않게)

되돌리는 것까지가 한 쌍이다. `-Off` 는 껐던 것만 정확히 다시 켠다.
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
    [switch]$On,
    [switch]$Off,
    # HUD 종료는 **기본 꺼짐**이다. 2026-08-18 실측에서 위의 27%p 가 재현되지 않았다
    # (HUD 켬 9~10% vs 끔 9~14%). 오브 하나 때문에 게임 중 비서를 통째로 끄지 않는다.
    # 전체화면 독점이 깨져 프레임이 깎이는 별개 경로가 확인되면 이 스위치로 켜라.
    [switch]$StopHud,
    [string]$RepoRoot = "C:\RoboMetaFit",
    [string]$OllamaBase = "http://127.0.0.1:11434",
    [string]$Model = $(if ($env:JARVIS_OLLAMA_MODEL) { $env:JARVIS_OLLAMA_MODEL } else { "plopfit-gemma4-qat" })
)

$ErrorActionPreference = "Continue"
$StateFile = Join-Path $RepoRoot "logs\game_mode_state.json"
$PausedTasks = @("RoboMetaFit-QB-Pool-Scheduler", "RoboMetaFit-QB-Pool-Supervisor", "RoboMetaFit-QB-Pool-QA-Sweep")

function Get-Gpu($index) {
    $raw = & nvidia-smi -i $index --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>$null
    if ($raw) { return ($raw | Select-Object -First 1).ToString().Trim() }
    return "?"
}

function Show-State($label) {
    "{0,-12} 3090: {1,-18} 2070: {2}" -f $label, (Get-Gpu 0), (Get-Gpu 1)
}

if (-not $On -and -not $Off) {
    Show-State "지금"
    Write-Host "`n  -On  으로 게임 모드, -Off 로 복귀합니다."
    exit 0
}

if ($On) {
    Show-State "시작 전"
    $restore = @{ hud = $false; tasks = @() }

    if ($StopHud) {
        $hud = Get-Process "alture-jarvis-hud" -ErrorAction SilentlyContinue
        if ($hud) {
            $hud | Stop-Process -Force
            $restore.hud = $true
            Write-Host "  [1/3] 자비스 HUD 종료 (백엔드와 F9 마이크는 그대로)"
        } else {
            Write-Host "  [1/3] HUD 는 이미 꺼져 있음"
        }
    } else {
        Write-Host "  [1/3] HUD 는 그대로 둔다 (-StopHud 로 끌 수 있음)"
    }

    # 젬마를 VRAM 에서 내린다. 다음에 자비스에게 말을 걸면 알아서 다시 올라온다(20초쯤).
    try {
        $body = @{ model = $Model; keep_alive = 0 } | ConvertTo-Json
        Invoke-RestMethod -Uri "$OllamaBase/api/generate" -Method Post -TimeoutSec 30 `
            -ContentType "application/json" -Body $body | Out-Null
        Write-Host "  [2/3] 젬마를 VRAM 에서 내림 (3090 에 약 15GB 반납)"
    } catch {
        Write-Host "  [2/3] 젬마 내리기 실패(무시 가능): $($_.Exception.Message)"
    }

    foreach ($name in $PausedTasks) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task -and $task.State -ne "Disabled") {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            Disable-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null
            $restore.tasks += $name
        }
    }
    Write-Host "  [3/3] QB 배치 일시 중지: $($restore.tasks.Count)개"

    New-Item -ItemType Directory -Force -Path (Split-Path $StateFile) | Out-Null
    $restore | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
    Start-Sleep -Seconds 3
    Show-State "게임 모드"
    Write-Host "`n  끝나면: game_mode.ps1 -Off"
    exit 0
}

if ($Off) {
    $restore = $null
    if (Test-Path $StateFile) {
        try { $restore = Get-Content $StateFile -Raw | ConvertFrom-Json } catch { $restore = $null }
    }
    # 상태 파일이 없어도 되돌릴 수 있어야 한다 — 없다고 껐던 걸 영영 못 켜면 안 된다.
    $tasks = if ($restore -and $restore.tasks) { @($restore.tasks) } else { $PausedTasks }
    # ★ 되돌림은 **성공을 확인해야 한다.** 예전 이 자리는 SilentlyContinue 로 실패를
    #   삼켰고(권한 없이 Enable-ScheduledTask 를 부르면 Access denied 다), 그 바람에
    #   RoboMetaFit-QB-Pool-Scheduler 가 2026-08-12~08-18 엿새 동안 꺼진 채였다.
    #   아무도 몰랐던 이유는 "재개했다"고 찍고 끝났기 때문이다.
    $failed = @()
    foreach ($name in $tasks) {
        try { Enable-ScheduledTask -TaskName $name -ErrorAction Stop | Out-Null } catch { }
        $state = (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue).State
        if ($state -eq "Disabled" -or $null -eq $state) { $failed += $name }
    }
    if ($failed.Count -gt 0) {
        Write-Host "  ★ QB 배치 재개 실패 $($failed.Count)개: $($failed -join ', ')"
        Write-Host "  ★ 관리자 권한이 필요하다. 그대로 두면 야간 생성이 통째로 멈춘다:"
        Write-Host "      Enable-ScheduledTask -TaskName $($failed -join ',')"
        # 상태 파일을 지우지 않는다 — 다음 기동의 정리 단계가 다시 시도하게 남긴다.
        Write-Host "  복구 못 한 항목이 있어 상태 파일을 남긴다."
    } else {
        Write-Host "  QB 배치 재개: $($tasks.Count)개 (전부 확인됨)"
    }

    if (-not $restore -or $restore.hud) {
        schtasks /Run /TN "RoboMetaFit-Alture-Jarvis-HUD" | Out-Null
        Write-Host "  자비스 HUD 다시 켬"
    }
    if ($failed.Count -eq 0) { Remove-Item $StateFile -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 4
    Show-State "복귀"
    Write-Host "`n  젬마는 다음에 자비스에게 말을 걸 때 다시 올라옵니다(20초쯤)."
    exit 0
}
