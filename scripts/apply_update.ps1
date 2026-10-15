#Requires -Version 5.1
<#
.SYNOPSIS
  위성 자비스를 새 판으로 갈아치운다. **떼어 낸 채로** 돈다.

.DESCRIPTION
  파이썬이 자기 파일을 자기가 못 바꾼다(도는 중이다). 그래서 자비스는 받아서
  풀고 지시서(plan.json)만 쓰고, 실제 교체는 이 스크립트가 한다.

  순서가 곧 안전이다:

      1  내린다        python + HUD. 안 죽으면 여기서 멈춘다(반쯤 바꾸느니 안 바꾼다)
      2  백업          src · ui\alture-jarvis-hud.exe · 그 밖의 대상
      3  바꾼다        staging -> 설치본
      4  의존성        pyproject/requirements 가 바뀌었을 때만
      5  올린다        작업 스케줄러 · **없으면 직접 띄운다**
      6  ★ 확인       /health 의 build 가 **기대한 값인가**
      7  아니면 되돌림  백업을 되돌리고 다시 올린다. 그리고 크게 남긴다

  ## 왜 6번이 있나

  「배포했다」는 말은 증거가 아니다. `/health` 가 200 을 주는 것도 아니다 —
  안 죽은 옛 프로세스가 답할 수 있다. 이 저장소는 그 구멍으로 두 번 속았고,
  한 번은 스케줄러가 엿새 죽어 있는 것을 아무도 몰랐다. 그래서 **판 지문이
  기대한 값과 같은지**를 본다. 그것만이 새 코드가 도는 증거다.

  ## ★ 2026-08-24 — 첫 실전에서 5~7 이 통째로 안 돌았다

  나래님 노트북의 첫 갱신이 이렇게 끝났다: 파일은 새 판으로 바뀌었고, 자비스는
  **꺼진 채로** 남았고, 화면엔 "되돌렸습니다"가 찍혔는데 **되돌린 적이 없었다.**
  원인 셋이 겹쳐 있었다.

  ① `schtasks ... 2>&1 | Out-Null` 이 5단계에서 스크립트를 죽였다.
     PowerShell 5.1 은 네이티브 exe 의 stderr 를 `2>&1` 로 합치면 그 줄을
     **터미네이팅 에러**로 만든다(종료코드가 0 이어도). `$ErrorActionPreference
     = "Stop"` 아래라 그대로 죽었고, 6단계(확인)도 7단계(되돌림)도 안 돌았다.
     같은 병이 4단계 pip 줄에도 있었다 — 거긴 **교체 직후**라 더 나빴다.
  ② 그 노트북엔 예약 작업이 아예 없다(회사 정책으로 schtasks 가 막혀 있다).
     ①을 고쳐도 5단계는 아무 일도 못 했을 것이다. 그래서 **직접 띄우는 길**을 뒀다.
  ③ 부르는 쪽(bootstrap)이 종료코드만 보고 "되돌렸습니다"라고 찍었다.
     이제 이 스크립트가 `result.json` 에 **무슨 일이 실제로 일어났는지**를 적고,
     부르는 쪽은 그것을 읽는다. 시작할 때 `started` 로 적어 두므로, 스크립트가
     중간에 죽으면 그 흔적이 남는다 — 침묵이 성공으로도, 되돌림으로도 안 읽힌다.

.NOTES
  로그: <data>\update\apply.log — 이 스크립트는 화면이 없다. 로그가 유일한 눈이다.
  결과: <data>\update\result.json — 부르는 쪽이 읽는 유일한 진실.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $Plan,
    # 재기동 뒤 새 판이 뜨기를 기다리는 시간. 콜드 스타트가 느린 노트북을 본다.
    [int] $VerifySeconds = 150
)

$ErrorActionPreference = "Stop"
$planData   = Get-Content -LiteralPath $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
$Root       = $planData.root
$Staging    = $planData.staging
$Expected   = $planData.expected_build
$WorkDir    = Split-Path -Parent $Plan
$LogPath    = Join-Path $WorkDir "apply.log"
$ResultPath = Join-Path $WorkDir "result.json"

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    Write-Host $line
}

# ── 무슨 일이 실제로 일어났나 ────────────────────────────────────────────────
#
# ★ 부르는 쪽이 종료코드로 짐작하지 않게 한다. 짐작하면 "되돌렸습니다"가
#   되돌린 적 없이 찍힌다 — 2026-08-24 에 실제로 그렇게 났다.
function Write-Result([string] $State, [string] $Note = "", [string] $Build = "") {
    $data = [ordered]@{
        result   = $State
        note     = $Note
        build    = $Build
        expected = $Expected
        at       = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    }
    try {
        $data | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    } catch {
        Log "  !! 결과를 못 적었습니다: $_"
    }
}

# 시작하자마자 적는다. 스크립트가 중간에 죽어도 `started` 가 남아, 부르는 쪽이
# 「모른다」고 말할 수 있다. 지난 판의 결과가 남아 오해를 부르지도 않는다.
Write-Result "started" "아직 진행 중"

# ── 네이티브 명령은 여기로만 부른다 ──────────────────────────────────────────
#
# ★ PowerShell 5.1 에서 `exe ... 2>&1` 은 stderr 한 줄을 NativeCommandError 로
#   감싸고, `$ErrorActionPreference = "Stop"` 아래서는 그것이 **터미네이팅**이다.
#   종료코드가 0 이어도 죽는다. 그래서 이 안에서만 잠깐 Continue 로 낮춘다.
function Invoke-Native([string] $Exe, [string[]] $Arguments = @()) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        return [pscustomobject]@{ Code = $LASTEXITCODE; Out = @($lines) }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Test-Task([string] $Name) {
    return ((Invoke-Native "schtasks" @("/Query", "/TN", $Name)).Code -eq 0)
}

Log "──────────────────────────────────────────"
Log "갱신 시작 · 기대 판 $Expected"
Log "설치본 $Root"

# ── 1. 내린다 ────────────────────────────────────────────────────────────────
#
# ★ TTS 서버를 뺀다. 그 서버도 python.exe 이고 명령줄에 alture-jarvis 가 들어
#   있어서, 안 빼면 갱신할 때마다 음성이 죽는다. 이 저장소는 그렇게 다섯 번
#   죽였고 **아무 데도 안 찍혀서** 사용자님이 말할 때까지 몰랐다.
$script:HudWasRunning = $false

function Stop-Jarvis {
    $procs = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -like "python*" -and
         ($_.CommandLine -like "*alture-jarvis*" -or $_.CommandLine -like "*alture_jarvis*") -and
         $_.CommandLine -notlike "*supertonic*") -or
        $_.Name -eq "alture-jarvis-hud.exe"
    }
    foreach ($p in $procs) {
        # 화면은 **돌고 있었을 때만** 되살린다. 안 켜져 있던 화면을 갱신이
        # 제멋대로 띄우면 그건 사람이 시킨 적 없는 일이다.
        if ($p.Name -eq "alture-jarvis-hud.exe") { $script:HudWasRunning = $true }
        Log ("  내림 PID {0} ({1})" -f $p.ProcessId, $p.Name)
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { Log "    !! $_" }
    }
    Start-Sleep -Seconds 3
}

Stop-Jarvis
$still = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -like "python*" -and $_.CommandLine -like "*alture*jarvis*" -and $_.CommandLine -notlike "*supertonic*") -or
    $_.Name -eq "alture-jarvis-hud.exe"
}
if ($still) {
    # 반쯤 바꾸느니 안 바꾼다. 도는 프로세스의 파일을 갈아치우면 그 프로세스는
    # 옛 코드와 새 코드가 섞인 상태로 남고, 그건 진단이 안 된다.
    Log "★ 프로세스가 안 죽었습니다. 아무것도 바꾸지 않고 멈춥니다."
    Write-Result "stopped_no_change" "프로세스가 안 죽어 아무것도 바꾸지 않았습니다"
    exit 2
}
Log "  전부 내려갔습니다"

# ── 2. 백업 ──────────────────────────────────────────────────────────────────
$stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $WorkDir "backup-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null

$targets = @()
foreach ($d in $planData.dirs) { $targets += $d }
foreach ($f in $planData.files) { $targets += $f }
$targets += $planData.hud

foreach ($rel in $targets) {
    $src = Join-Path $Root ($rel -replace '/', '\')
    if (-not (Test-Path -LiteralPath $src)) { continue }
    $dst = Join-Path $backup ($rel -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
}
Log "  백업 -> $backup"

# ── 올리는 방법 ──────────────────────────────────────────────────────────────
#
# ★ 예약 작업이 **없는 PC 가 실재한다.** 나래님 노트북은 회사 정책으로 schtasks
#   가 막혀 있어 설치 때 작업이 안 만들어졌다. 스케줄러만 부르면 이 스크립트는
#   "명령을 넣었습니다"라고 찍고 아무 일도 안 일어난다 — 그리고 6단계가 실패해
#   되돌리는데, 되돌린 뒤에도 못 올려서 **꺼진 채로** 끝난다.
function Start-Jarvis {
    $started = $false
    if (Test-Task "RoboMetaFit-Alture-Jarvis") {
        $run = Invoke-Native "schtasks" @("/Run", "/TN", "RoboMetaFit-Alture-Jarvis")
        if ($run.Code -eq 0) {
            Log "  올림: 작업 스케줄러"
            $started = $true
        } else {
            Log ("  !! schtasks /Run 실패(코드 {0}): {1}" -f $run.Code, ($run.Out -join " "))
        }
    } else {
        Log "  예약 작업이 없습니다 — 직접 띄웁니다"
    }

    if (-not $started) {
        # venv 것을 먼저 본다. 시스템 파이썬으로 띄우면 의존성이 다를 수 있다.
        $py = Join-Path $Root ".venv\Scripts\pythonw.exe"
        if (-not (Test-Path -LiteralPath $py)) {
            $found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
            $py = if ($found) { $found.Source } else { "" }
        }
        $entry = Join-Path $Root "scripts\task_entry.py"
        if ($py -and (Test-Path -LiteralPath $entry)) {
            Start-Process -FilePath $py -ArgumentList @("""$entry""") -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
            Log "  올림: 직접 실행 ($py)"
            $started = $true
        } else {
            Log "  !! 올릴 방법이 없습니다 (pythonw='$py', entry='$entry')"
        }
    }

    if ($script:HudWasRunning) {
        if (Test-Task "RoboMetaFit-Alture-Jarvis-HUD") {
            $null = Invoke-Native "schtasks" @("/Run", "/TN", "RoboMetaFit-Alture-Jarvis-HUD")
            Log "  화면도 다시 띄웠습니다 (작업 스케줄러)"
        } else {
            $hud = Join-Path $Root "ui\alture-jarvis-hud.exe"
            if (Test-Path -LiteralPath $hud) {
                Start-Process -FilePath $hud -WorkingDirectory (Split-Path -Parent $hud) | Out-Null
                Log "  화면도 다시 띄웠습니다 (직접 실행)"
            }
        }
    }
    return $started
}

function Wait-ForBuild([string] $Want, [int] $Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $got = ""
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        try {
            $health = Invoke-RestMethod -Uri $planData.health_url -TimeoutSec 8
            $got = [string]$health.build
            if ($got -eq $Want) { return $got }
        } catch { $got = "" }
    }
    return $got
}

# ── 3~6 은 한 덩어리다 ───────────────────────────────────────────────────────
#
# ★ 여기 어디서 죽어도 **7번(되돌림)으로 간다.** 전에는 try 가 없어서, 5단계에서
#   죽으면 6·7 이 통째로 안 돌고 「새 파일 + 꺼진 자비스」로 남았다.
$applied = $false
try {
    # ── 3. 바꾼다 ────────────────────────────────────────────────────────────
    #
    # staging 에 있는 것만 덮는다. **지우지 않는다** — 위성에만 있는 파일(자기 크롬
    # 프로필 경로 설정 같은 것)을 이 스크립트가 판단할 수 없다.
    $changedDeps = $false
    foreach ($rel in $targets) {
        $from = Join-Path $Staging ($rel -replace '/', '\')
        if (-not (Test-Path -LiteralPath $from)) { continue }
        $to = Join-Path $Root ($rel -replace '/', '\')
        if ($rel -match 'pyproject|requirements') {
            $old = if (Test-Path -LiteralPath $to) { (Get-FileHash -LiteralPath $to).Hash } else { "" }
            $new = (Get-FileHash -LiteralPath $from).Hash
            if ($old -ne $new) { $changedDeps = $true }
        }
        if (Test-Path -LiteralPath $from -PathType Container) {
            New-Item -ItemType Directory -Force -Path $to | Out-Null
            Copy-Item -Path (Join-Path $from "*") -Destination $to -Recurse -Force
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $to) | Out-Null
            Copy-Item -LiteralPath $from -Destination $to -Force
        }
        $applied = $true
    }
    Log "  교체 완료 (의존성 변경: $changedDeps)"

    # ── 4. 의존성 ────────────────────────────────────────────────────────────
    #
    # 바뀌었을 때만 돈다. 매번 돌리면 갱신이 몇 분씩 걸리고, 오프라인이면 실패한다.
    if ($changedDeps) {
        $vpy = Join-Path $Root ".venv\Scripts\python.exe"
        if (Test-Path -LiteralPath $vpy) {
            Log "  의존성 갱신 중..."
            $pip = Invoke-Native $vpy @("-m", "pip", "install", "-e", $Root, "--quiet")
            foreach ($line in $pip.Out) { if ($line) { Log "    $line" } }
            if ($pip.Code -ne 0) { throw "의존성 설치가 실패했습니다 (코드 $($pip.Code))" }
        } else {
            Log "  !! venv 를 못 찾아 의존성을 건너뜁니다: $vpy"
        }
    }

    # ── 5. 올린다 ────────────────────────────────────────────────────────────
    if (-not (Start-Jarvis)) { throw "자비스를 올릴 방법을 못 찾았습니다" }
    Log "  재기동 명령을 넣었습니다"

    # ── 6. 확인 ──────────────────────────────────────────────────────────────
    #
    # ★ 여기가 요점이다. 200 은 증거가 아니다 — **판 지문이 기대한 값**이어야 한다.
    $got = Wait-ForBuild $Expected $VerifySeconds
    if ($got -eq $Expected) {
        Log "[OK] 갱신 성공 · 판 $got"
        Log "   백업은 남겨 둡니다: $backup"
        Write-Result "success" "새 판이 떠 있는 것을 확인했습니다" $got
        exit 0
    }
    throw "확인 실패 (본 값 '$got' != 기대 '$Expected')"

} catch {
    Log "★ $_"
    if (-not $applied) {
        # 아직 아무것도 안 바꿨다. 되돌릴 것도 없다 — 다시 올리기만 한다.
        Log "   바꾸기 전에 멈췄습니다. 되돌릴 것이 없습니다."
        $null = Start-Jarvis
        Write-Result "stopped_no_change" "$_"
        exit 2
    }
}

# ── 7. 되돌린다 ──────────────────────────────────────────────────────────────
Log "   되돌립니다 (백업: $backup)"
Stop-Jarvis
foreach ($rel in $targets) {
    $from = Join-Path $backup ($rel -replace '/', '\')
    if (-not (Test-Path -LiteralPath $from)) { continue }
    $to = Join-Path $Root ($rel -replace '/', '\')
    try {
        if (Test-Path -LiteralPath $from -PathType Container) {
            Copy-Item -Path (Join-Path $from "*") -Destination $to -Recurse -Force
        } else {
            Copy-Item -LiteralPath $from -Destination $to -Force
        }
    } catch {
        Log "   !! 되돌리다 실패: $rel — $_"
    }
}
$null = Start-Jarvis
Log "   옛 판으로 다시 올렸습니다. 떠 있는지 봅니다."

# 되돌린 것도 **확인한다.** 되돌림이 조용히 실패해 엿새를 잃은 적이 있다.
$after   = ""
$answered = $false
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    try {
        $health = Invoke-RestMethod -Uri $planData.health_url -TimeoutSec 8
        $after = [string]$health.build
        $answered = $true
        break
    } catch { }
}
if ($answered) {
    Log "   되돌린 뒤 상태: build '$after'"
    Write-Result "rolled_back" "옛 판으로 되돌렸고, 자비스가 다시 응답합니다" $after
    exit 3
}
Log "   !! 되돌린 뒤에도 응답이 없습니다. 사람이 봐야 합니다: $backup"
Write-Result "half_applied" "되돌렸지만 자비스가 응답하지 않습니다. 백업: $backup"
exit 4
