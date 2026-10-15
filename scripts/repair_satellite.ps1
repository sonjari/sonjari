#Requires -Version 5.1
<#
.SYNOPSIS
  위성 자비스가 **죽어 있을 때** 한 번 눌러서 되살린다. 진단하고, 고치고, 결과를 본체로 보낸다.

.DESCRIPTION
  ## 왜 「지금 받기」로는 안 되나

  화면의 「지금 받기」는 그 PC 의 자비스 백엔드가 살아 있어야 눌린다 — 버튼이
  `127.0.0.1:8091` 로 부탁하는 것이기 때문이다. 백엔드가 죽으면 버튼도 같이
  죽는다. 그런데 **정작 고쳐야 할 때가 백엔드가 죽은 때**다. 닭과 달걀이다.

  `bootstrap_update.ps1` 이 그 매듭을 푸는 자리인데, 그것도 두 가지를 가정한다:
  ① 그 PC 에 이미 깔려 있고 ② 그것이 낡지 않았다. 나래님 노트북은 그 둘을 다
  못 믿는 상태다(설치본의 스크립트가 한 판 낡을 수 있다).

  그래서 이 스크립트는 **아무것도 가정하지 않는다.** 본체에서 최신 묶음을 받아
  그 안의 `bootstrap_update.ps1` 을 쓴다. 교체·되돌리기의 판단은 여전히
  `apply_update.ps1` 한 곳에만 있다 — 여기서 또 판단하면 두 벌이 되고, 두 벌은
  반드시 갈린다.

  ## 이 스크립트가 실제로 고치는 것

      백엔드가 안 뜬다        패키지 미설치(pip install -e) 를 먼저 잡는다
      껐다 켜면 안 뜬다       예약 작업이 막힌 PC 라 시작프로그램 폴더로 건다
      아이콘을 눌러도 무반응  바탕화면 바로가기가 백엔드를 가리키던 것을 화면으로
      뭐가 문젠지 모르겠다    진단 표를 만들어 **본체로 보낸다**

  ## 결과를 본체로 보내는 이유

  위성은 `127.0.0.1` 에만 귀를 연다(설계가 그렇다). 그래서 본체에서 들여다볼
  방법이 없고, 지금까지는 사람이 화면을 읽어 전해 줘야 했다. 이 스크립트는
  끝나면 진단 표를 테일드롭으로 본체에 던진다 — 「됐어요」라는 말이 아니라
  숫자를 본다.

.EXAMPLE
  # 위성 PC 에서 (관리자 권한 필요 없음)
  powershell -NoProfile -ExecutionPolicy Bypass -File .\repair_satellite.ps1

.NOTES
  로그·리포트 : <Root>\data\update\repair-<시각>.log
  ★ 이 파일은 `$ErrorActionPreference = "Continue"` 로 돈다. 구조 스크립트가
    중간에 죽으면 아무것도 못 고치고 아무 말도 못 남긴다 — 그게 제일 나쁘다.
    실패는 예외로 튀는 게 아니라 표에 적힌다.
#>
[CmdletBinding()]
param(
    [string] $Root = "C:\RoboMetaFit\tools\alture-jarvis",
    [string] $BrainHost = "",
    [string] $ControlToken = "",
    # 진단만 하고 아무것도 안 바꾼다. 「뭐가 문제인지만 봐 주세요」일 때.
    [switch] $DiagnoseOnly,
    # 판이 같아 보여도 그냥 다시 깐다. 반쯤 바뀐 채로 남았을 때 이것이 필요하다.
    [switch] $Force,
    # 결과를 본체로 안 보낸다.
    [switch] $NoReport
)

# ★ Stop 이 아니다. 이유는 위 NOTES.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$Stamp   = Get-Date -Format "yyyyMMdd-HHmmss"
$WorkDir = Join-Path $Root "data\update"
if (-not (Test-Path -LiteralPath $WorkDir)) {
    New-Item -ItemType Directory -Force -Path $WorkDir -ErrorAction SilentlyContinue | Out-Null
}
$LogPath = Join-Path $WorkDir "repair-$Stamp.log"

$script:Facts = [ordered]@{}

function Log([string] $msg, [string] $color = "Gray") {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    try { Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue } catch { }
    Write-Host $line -ForegroundColor $color
}
function Say($m) { Log "   $m" "Cyan" }
function Ok($m)  { Log "OK $m" "Green" }
function Bad($m) { Log "!! $m" "Red" }
function Fact([string] $k, $v) { $script:Facts[$k] = $v }

# 네이티브 exe 는 여기로만 부른다. PS 5.1 은 `exe ... 2>&1` 한 줄을
# NativeCommandError 로 감싸고, Stop 아래서 그것은 터미네이팅이다 — 종료코드가
# 0 이어도 죽는다. 이 저장소는 그 한 줄에 갱신 전체를 잃은 적이 있다.
function Invoke-Native([string] $Exe, [string[]] $Arguments = @()) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        return [pscustomobject]@{ Code = $LASTEXITCODE; Out = @($lines) }
    } catch {
        return [pscustomobject]@{ Code = -1; Out = @("$_") }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Get-LocalBuild {
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:8091/health" -TimeoutSec 8
        return [string]$h.build
    } catch { return "" }
}

Log "══════════════════════════════════════════"
Log "위성 복구 · $Stamp"
Log "설치본 $Root"
Fact "at" (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Fact "computer" $env:COMPUTERNAME
Fact "user" $env:USERNAME
Fact "root" $Root

# ── 1. 진단 ──────────────────────────────────────────────────────────────────
#
# 고치기 전에 **무엇이 어떤 상태였는지**를 먼저 적는다. 고친 뒤에 적으면
# 「원래 그랬는지 내가 고쳐서 그런지」를 영원히 모른다.
Log ""
Log "── 1. 지금 상태 ─────────────────────────" "Yellow"

$hasRoot = Test-Path -LiteralPath $Root
Fact "install_present" $hasRoot
if (-not $hasRoot) {
    Bad "설치본이 없습니다: $Root"
    Bad "이건 복구가 아니라 설치입니다 — install_satellite.ps1 이 필요합니다."
    exit 1
}

$envPath = Join-Path $Root ".env"
$hasEnv = Test-Path -LiteralPath $envPath
Fact "env_present" $hasEnv

# .env 에서 본체 주소·토큰을 읽는다. 새 값을 요구하지 않는다 — 위성은 이미 갖고 있다.
if ($hasEnv) {
    foreach ($line in (Get-Content -LiteralPath $envPath -Encoding UTF8 -ErrorAction SilentlyContinue)) {
        if (-not $BrainHost -and $line -match '^\s*JARVIS_BRAIN_HOST\s*=\s*(\S+)') { $BrainHost = $Matches[1] }
        if (-not $BrainHost -and $line -match '^\s*JARVIS_OLLAMA_BASE_URL\s*=\s*https?://([^:/\s]+)') { $BrainHost = $Matches[1] }
        if (-not $ControlToken -and $line -match '^\s*JARVIS_CONTROL_TOKEN\s*=\s*(\S+)') { $ControlToken = $Matches[1] }
        if ($line -match '^\s*JARVIS_ROLE\s*=\s*(\S+)') { Fact "role" $Matches[1] }
    }
}
Fact "brain_host" $BrainHost
Fact "token_present" ([bool]$ControlToken)

$vpy   = Join-Path $Root ".venv\Scripts\python.exe"
$vpyw  = Join-Path $Root ".venv\Scripts\pythonw.exe"
$entry = Join-Path $Root "scripts\task_entry.py"
$hud   = Join-Path $Root "ui\alture-jarvis-hud.exe"
Fact "venv_python" (Test-Path -LiteralPath $vpy)
Fact "task_entry" (Test-Path -LiteralPath $entry)
Fact "hud_exe" (Test-Path -LiteralPath $hud)

# 패키지가 venv 에 실제로 설치돼 있나. **여기가 첫 설치에서 조용히 샜던 자리다**
# (`pip install -e .` 누락 → ModuleNotFoundError → 백엔드가 영원히 안 뜬다).
$importOk = $false
$importMsg = "venv 없음"
if (Test-Path -LiteralPath $vpy) {
    $imp = Invoke-Native $vpy @("-c", "import alture_jarvis, sys; print(alture_jarvis.__file__)")
    $importOk = ($imp.Code -eq 0)
    $importMsg = ($imp.Out -join " ").Trim()
}
Fact "package_importable" $importOk
Fact "import_detail" $importMsg

$localBuild = Get-LocalBuild
Fact "backend_build_before" $localBuild
if ($localBuild) { Ok "백엔드 응답 · 판 $localBuild" } else { Bad "백엔드가 응답하지 않습니다 (127.0.0.1:8091)" }

$procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -like "python*" -and $_.CommandLine -like "*alture*jarvis*" -and $_.CommandLine -notlike "*supertonic*") -or
    $_.Name -eq "alture-jarvis-hud.exe"
})
Fact "processes" @($procs | ForEach-Object { "$($_.Name)#$($_.ProcessId)" })
Say ("도는 프로세스 {0}개" -f $procs.Count)

$taskQ = Invoke-Native "schtasks" @("/Query", "/TN", "RoboMetaFit-Alture-Jarvis")
$hasTask = ($taskQ.Code -eq 0)
Fact "scheduled_task" $hasTask

$startupLnk = Join-Path ([Environment]::GetFolderPath("Startup")) "JARVIS.lnk"
$desktopLnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "JARVIS.lnk"
Fact "startup_shortcut" (Test-Path -LiteralPath $startupLnk)
Fact "desktop_shortcut" (Test-Path -LiteralPath $desktopLnk)

# 자동 시작이 **하나도** 없으면 껐다 켤 때마다 죽은 채로 남는다. 이번 증상의 1순위.
if (-not $hasTask -and -not (Test-Path -LiteralPath $startupLnk)) {
    Bad "자동 시작이 없습니다 — 껐다 켜면 자비스가 안 뜹니다 (아래에서 겁니다)"
}

# 본체에 닿나. 못 닿으면 갱신은 시작도 못 한다 — 여기서 갈래를 나눈다.
$base = ""
$manifest = $null
if ($BrainHost) {
    $base = if ($BrainHost -match '^https?://') { $BrainHost.TrimEnd('/') } else { "http://${BrainHost}:8091" }
    try {
        $manifest = Invoke-RestMethod -Uri "$base/v1/update/manifest" `
            -Headers @{ "X-JARVIS-TOKEN" = $ControlToken } -TimeoutSec 25
        Ok ("본체 도달 · 판 {0} · {1}개 · {2}MB" -f $manifest.build, $manifest.file_count,
            [math]::Round($manifest.total_bytes / 1MB, 1))
        Fact "brain_reachable" $true
        Fact "brain_build" $manifest.build
        Fact "brain_payload_id" $manifest.payload_id
    } catch {
        Bad "본체에 못 닿습니다: $_"
        Fact "brain_reachable" $false
        Fact "brain_error" "$_"
    }
} else {
    Bad ".env 에서 본체 주소를 못 찾았습니다"
    Fact "brain_reachable" $false
}

if ($DiagnoseOnly) {
    Log ""
    Log "진단만 하고 멈춥니다 (-DiagnoseOnly)." "Yellow"
} else {

# ── 2. 백엔드가 못 뜨는 이유부터 없앤다 ──────────────────────────────────────
#
# 패키지가 안 깔려 있으면 무엇을 갈아치워도 안 뜬다. 그 상태로 갱신을 걸면
# 6단계(확인)가 실패하고 되돌리기가 돌고, 되돌린 것도 안 뜬다 — 「반쯤 바뀜」으로
# 끝난다. 그래서 갱신보다 **먼저** 잡는다.
Log ""
Log "── 2. 밑바닥 (패키지) ───────────────────" "Yellow"
if (-not $importOk -and (Test-Path -LiteralPath $vpy)) {
    Say "alture_jarvis 를 못 불러옵니다 — pip install -e 를 겁니다"
    $pip = Invoke-Native $vpy @("-m", "pip", "install", "-e", $Root, "--quiet")
    foreach ($l in $pip.Out) { if ($l) { Log "     $l" } }
    $imp2 = Invoke-Native $vpy @("-c", "import alture_jarvis; print('ok')")
    $importOk = ($imp2.Code -eq 0)
    Fact "pip_install_ran" $true
    Fact "package_importable_after_pip" $importOk
    if ($importOk) { Ok "이제 불러와집니다" } else { Bad "아직도 안 됩니다: $($imp2.Out -join ' ')" }
} elseif ($importOk) {
    Ok "패키지 정상"
}

# ── 3. 최신 묶음을 받아 그 안의 bootstrap 으로 간다 ──────────────────────────
#
# ★ 설치본의 스크립트를 안 쓴다. 그것이 한 판 낡았을 수 있고, 하필 낡은 자리가
#   교체 스크립트면 그 버그는 **자기 자신을 영원히 못 고친다.** 2026-08-24 에
#   실제로 그렇게 났다.
Log ""
Log "── 3. 본체에서 받아 갈아치우기 ──────────" "Yellow"
$bootstrapUsed = ""
if ($manifest) {
    $fresh = Join-Path $WorkDir "repair-staging"
    if (Test-Path -LiteralPath $fresh) { Remove-Item -Recurse -Force -LiteralPath $fresh -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $fresh -ErrorAction SilentlyContinue | Out-Null
    $zip = Join-Path $WorkDir "repair-incoming.zip"
    try {
        Say "받는 중…"
        Invoke-WebRequest -Uri "$base/v1/update/payload" -Headers @{ "X-JARVIS-TOKEN" = $ControlToken } `
            -OutFile $zip -TimeoutSec 600 -UseBasicParsing
        Ok ("받음 {0}MB" -f [math]::Round((Get-Item $zip).Length / 1MB, 1))
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $fresh)
        $cand = Join-Path $fresh "scripts\bootstrap_update.ps1"
        if (Test-Path -LiteralPath $cand) { $bootstrapUsed = $cand }
    } catch {
        Bad "받기 실패: $_"
        Fact "download_error" "$_"
    }
}
if (-not $bootstrapUsed) {
    $cand = Join-Path $Root "scripts\bootstrap_update.ps1"
    if (Test-Path -LiteralPath $cand) {
        $bootstrapUsed = $cand
        Say "받은 것이 없어 설치본의 스크립트를 씁니다 (낡았을 수 있습니다)"
    }
}
Fact "bootstrap_used" $bootstrapUsed

if ($bootstrapUsed -and $manifest) {
    $bootArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $bootstrapUsed,
              "-Root", $Root, "-BrainHost", $BrainHost, "-ControlToken", $ControlToken)
    if ($Force) { $bootArgs += "-Force" }
    $run = Invoke-Native "powershell" $bootArgs
    foreach ($l in $run.Out) { if ($l) { Log "     $l" } }
    Fact "bootstrap_exit" $run.Code

    # ★ 종료코드로 짐작하지 않는다. 교체 스크립트가 남긴 result.json 만 읽는다.
    $resultPath = Join-Path $WorkDir "result.json"
    if (Test-Path -LiteralPath $resultPath) {
        try {
            $res = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
            Fact "apply_result" $res.result
            Fact "apply_note" $res.note
            Fact "apply_build" $res.build
            Log ("   교체 결과: {0} — {1}" -f $res.result, $res.note)
        } catch { Fact "apply_result" "read_failed" }
    } else {
        Fact "apply_result" "no_result_file"
    }
} else {
    Bad "갱신을 못 걸었습니다 (본체 미도달이거나 스크립트 없음)"
}

# ── 4. 그래도 안 떠 있으면 직접 띄운다 ───────────────────────────────────────
#
# 갱신이 「할 일 없음」으로 끝났는데 백엔드는 여전히 죽어 있는 경우가 있다 —
# 그때 아무도 안 띄우면 이 스크립트는 "성공"을 찍고 사람은 여전히 못 쓴다.
Log ""
Log "── 4. 띄우기 ────────────────────────────" "Yellow"
if (-not (Get-LocalBuild)) {
    $started = $false
    if ($hasTask) {
        $r = Invoke-Native "schtasks" @("/Run", "/TN", "RoboMetaFit-Alture-Jarvis")
        if ($r.Code -eq 0) { Say "작업 스케줄러로 올렸습니다"; $started = $true }
        else { Say "schtasks /Run 실패(코드 $($r.Code))" }
    }
    if (-not $started) {
        $py = if (Test-Path -LiteralPath $vpyw) { $vpyw } elseif (Test-Path -LiteralPath $vpy) { $vpy } else { "" }
        if ($py -and (Test-Path -LiteralPath $entry)) {
            Start-Process -FilePath $py -ArgumentList @("""$entry""") -WorkingDirectory $Root -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
            Say "직접 띄웠습니다 ($py)"
            $started = $true
        } else {
            Bad "올릴 방법이 없습니다 (pythonw='$py', entry='$entry')"
        }
    }
    Fact "manual_start" $started
    # 콜드 스타트가 느린 노트북을 본다.
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if (Get-LocalBuild) { break }
    }
}

# ── 5. 껐다 켜도 뜨게 ────────────────────────────────────────────────────────
#
# 이 노트북은 회사 정책으로 schtasks 가 막혀 있다. 그래서 **시작프로그램 폴더**로
# 건다 — 관리자 권한이 필요 없고 결과는 같다.
Log ""
Log "── 5. 자동 시작 ─────────────────────────" "Yellow"
if (-not $hasTask) {
    try {
        $py = if (Test-Path -LiteralPath $vpyw) { $vpyw } else { $vpy }
        $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($startupLnk)
        $sc.TargetPath = $py
        $sc.Arguments = """$entry"""
        $sc.WorkingDirectory = $Root
        $sc.Save()
        if (Test-Path -LiteralPath $startupLnk) { Ok "시작프로그램 등록 ($startupLnk)" }
        else { Bad "시작프로그램 바로가기를 못 만들었습니다" }
    } catch { Bad "시작프로그램 등록 실패: $_" }
} else {
    Ok "예약 작업이 있습니다"
}
Fact "startup_shortcut_after" (Test-Path -LiteralPath $startupLnk)

# 바탕화면 아이콘은 **화면(HUD)** 을 가리켜야 한다. 백엔드를 가리키면 눌러도
# 아무 일이 안 난다 — 이미 떠 있는 것을 또 띄우려 들 뿐이다.
if (Test-Path -LiteralPath $hud) {
    try {
        $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($desktopLnk)
        $sc.TargetPath = $hud
        $sc.WorkingDirectory = (Split-Path -Parent $hud)
        $sc.Save()
        Ok "바탕화면 JARVIS 아이콘 (화면)"
    } catch { Bad "바탕화면 바로가기 실패: $_" }
} else {
    Bad "화면(alture-jarvis-hud.exe)이 설치본에 없습니다"
}
Fact "desktop_shortcut_after" (Test-Path -LiteralPath $desktopLnk)

}  # /DiagnoseOnly

# ── 6. 최종 판정 ─────────────────────────────────────────────────────────────
#
# 「고쳤습니다」는 말이 아니라 **판 지문**으로 말한다. 200 은 증거가 아니다.
Log ""
Log "── 6. 결과 ──────────────────────────────" "Yellow"
$after = Get-LocalBuild
Fact "backend_build_after" $after
$want = if ($manifest) { [string]$manifest.build } else { "" }

if ($after -and $want -and $after -eq $want) {
    Fact "verdict" "ok_latest"
    Ok "자비스가 최신 판으로 떠 있습니다 ($after)"
} elseif ($after -and $want) {
    Fact "verdict" "ok_but_stale"
    Bad "자비스는 떴는데 판이 다릅니다 (이 PC $after / 본체 $want)"
} elseif ($after) {
    Fact "verdict" "ok_unknown_target"
    Ok "자비스가 떠 있습니다 ($after) — 본체 판은 확인 못 했습니다"
} else {
    Fact "verdict" "down"
    Bad "자비스가 아직도 응답하지 않습니다. 로그를 보세요: $LogPath"
}

# ── 7. 본체로 보낸다 ─────────────────────────────────────────────────────────
#
# 위성은 127.0.0.1 에만 귀를 연다 — 본체에서 들여다볼 방법이 없다. 그래서 결과를
# 밀어 준다. 「됐어요/안 돼요」가 아니라 표를 본다.
$reportPath = Join-Path $WorkDir "repair-report-$Stamp.json"
try {
    # ★ [string] 로 바꿔서 담는다. Get-Content 가 주는 것은 PSPath·PSDrive 가
    #   달린 살찐 객체라, 그대로 ConvertTo-Json 하면 드라이브 그래프까지 따라와
    #   리포트가 **5.6MB** 가 된다(실측). 보내려던 것은 40줄이었다.
    $script:Facts["log_tail"] = @(Get-Content -LiteralPath $LogPath -Tail 40 -Encoding UTF8 -ErrorAction SilentlyContinue |
        ForEach-Object { [string]$_ })
    $script:Facts | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Log ""
    Log "리포트: $reportPath"
} catch { Bad "리포트를 못 적었습니다: $_" }

if (-not $NoReport -and (Test-Path -LiteralPath $reportPath)) {
    $ts = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path -LiteralPath $ts) {
        $cp = Invoke-Native $ts @("file", "cp", $reportPath, "node:")
        if ($cp.Code -eq 0) { Ok "결과를 본체로 보냈습니다" }
        else { Say "본체로 못 보냈습니다(코드 $($cp.Code)) — 이 파일을 사용자님께 주세요: $reportPath" }
    } else {
        Say "테일스케일을 못 찾아 못 보냈습니다 — 이 파일을 사용자님께 주세요: $reportPath"
    }
}

Log ""
Log "끝났습니다. 바탕화면의 JARVIS 아이콘을 눌러 보세요." "Green"
