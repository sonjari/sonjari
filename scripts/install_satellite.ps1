#Requires -Version 5.1
<#
.SYNOPSIS
  위성 자비스를 이 PC 에 깐다. 두뇌(젬마)는 본체에서 빌려 쓴다.

.DESCRIPTION
  손과 눈은 이 PC 것이다 — 자기 파일, 자기 창, 자기 크롬. 무거운 것만 본체에서
  빌린다:

      젬마 추론   -> 본체 :11434   (VRAM 이 거기 있다)
      음성 합성   -> 본체 :7788    (WAV 를 받아 이 PC 스피커로 튼다)
      STT        -> ★ 이 PC 의 GPU 로 한다. 본체에서 못 빌리지만(프로세스 안
                    에서 도는 물건이라) GPU 가 있으면 자기 것으로 하면 된다.
                    large-v3-turbo / int8_float16 = 1.5~2GB. 3050 이면 넉넉하다.
                    GPU 가 없으면 CPU 로 내려가고 이유를 /health 에 남긴다

  ★ 본체와 이 PC 가 같은 테일넷에 있어야 한다. 사무실/집이 갈려도 테일스케일이면
    된다 — LAN 을 열지 않아도 되고, 암호화·인증이 붙는다.

.EXAMPLE
  .\install_satellite.ps1 -BrainHost 100.64.0.10 -ControlToken <토큰>

.NOTES
  되돌리기: Remove-Item -Recurse C:\RoboMetaFit\tools\alture-jarvis
            schtasks /Delete /TN "RoboMetaFit-Alture-Jarvis" /F
#>
[CmdletBinding()]
param(
    # 본체의 테일스케일 주소(권장) 또는 LAN 주소.
    [Parameter(Mandatory = $true)][string] $BrainHost,
    # 본체의 data\control.token 내용. 같은 값을 써야 붙는다.
    [Parameter(Mandatory = $true)][string] $ControlToken,
    # 우리 DB(입시·진로) 조회용 NAS 키. 없으면 그 도구들이 0개로 서고,
    # 라우팅이 그 갈래를 아예 안 연다(도구가 없을 때 갈래를 열면 지어낸다).
    [string] $InhouseApiKey = "",
    [string] $Root = "C:\RoboMetaFit\tools\alture-jarvis",
    [switch] $SkipBrowser,
    # 음성(PTT + STT)까지 쓴다. NVIDIA GPU 가 있으면 켜는 것이 맞다.
    # 마이크 녹음·faster-whisper·CUDA 런타임이 같이 깔린다(수백 MB).
    [switch] $WithVoice,
    [switch] $NoTask
)

$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $PSScriptRoot

function Step($n, $what) { Write-Host ("[{0}] {1}" -f $n, $what) -ForegroundColor Cyan }
function Ok($what) { Write-Host ("    OK  {0}" -f $what) -ForegroundColor Green }
function Warn($what) { Write-Host ("    !!  {0}" -f $what) -ForegroundColor Yellow }

# ── 1. 본체에 닿는지부터 본다 ────────────────────────────────────────────────
#
# ★ 이걸 먼저 하는 이유: 30분 설치한 뒤에 "본체를 못 찾습니다"가 뜨면 어디서
#   틀렸는지 알 수가 없다. 닿는 것을 먼저 확인하고 시작한다.
Step 1 "본체에 닿는가 ($BrainHost)"
try {
    $tags = Invoke-RestMethod -Uri "http://${BrainHost}:11434/api/tags" -TimeoutSec 10
    Ok ("젬마 서버 응답 · 모델 {0}종" -f @($tags.models).Count)
    # ★ 본체가 **지금 올려 둔** 모델을 그대로 쓴다 (2026-08-23).
    #
    # 태그가 갈리면 슬롯이 하나뿐이라 서로 축출한다. 그래서 이름을 여기서 짐작하지
    # 않고 본체에 **물어본다** — 두 벌을 두면 갈리고, 갈린 쪽은 조용히 틀린다.
    # 상주 모델이 없으면(아무도 안 쓰는 중) 목록 첫 번째로 떨어진다.
    $BrainModel = $null
    try {
        $ps = Invoke-RestMethod -Uri "http://${BrainHost}:11434/api/ps" -TimeoutSec 10
        if (@($ps.models).Count -gt 0) { $BrainModel = @($ps.models)[0].name }
    } catch { }
    if (-not $BrainModel -and @($tags.models).Count -gt 0) { $BrainModel = @($tags.models)[0].name }
    if (-not $BrainModel) { $BrainModel = "plopfit-gemma4-qat" }
    Ok "본체와 같은 모델을 쓴다: $BrainModel"
} catch {
    throw "본체 :11434 에 못 닿습니다 — $($_.Exception.Message)`n" +
          "  본체에서 확인할 것:`n" +
          "    · OLLAMA_HOST=0.0.0.0 인가`n" +
          "    · 방화벽이 11434 를 막고 있지 않은가 (100.64.0.0/10 허용)`n" +
          "    · tailscale status 에 이 PC 가 보이는가"
}
try {
    Invoke-RestMethod -Uri "http://${BrainHost}:7788/v1/health" -TimeoutSec 10 | Out-Null
    Ok "음성 합성 서버 응답"
} catch {
    Warn "음성 합성(:7788)에 못 닿습니다 — 소리 없이 씁니다(나머지는 정상)"
}

# ── 2. 파이썬 ────────────────────────────────────────────────────────────────
Step 2 "파이썬 확인"
$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue) }
if (-not $py) {
    throw "파이썬이 없습니다. https://www.python.org/downloads/ 에서 3.11 이상을 먼저 설치하세요."
}
$pyVersion = & $py.Source -c "import sys; print('%d.%d' % sys.version_info[:2])"
Ok "python $pyVersion ($($py.Source))"
if ([version]$pyVersion -lt [version]"3.11") { throw "3.11 이상이 필요합니다(지금 $pyVersion)." }

# ── 3. 파일 복사 ─────────────────────────────────────────────────────────────
Step 3 "파일 복사 -> $Root"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
# ★ 2026-08-22: `ui` 가 이 목록에 없어서 **화면 없이 백엔드만 깔렸다.**
#   `/health` 는 ok:true 로 나오니 설치가 된 것처럼 보이는데, 나래님은 볼 창이
#   없었다. 바탕화면 바로가기도 백엔드를 가리키고 있어서 눌러도 아무 일이 없었다.
#   **도는 것과 쓸 수 있는 것은 다르다.**
foreach ($dir in @("src", "scripts", "knowledge", "recipes", "skills", "ui")) {
    $from = Join-Path $Source $dir
    if (-not (Test-Path $from)) { continue }
    $to = Join-Path $Root $dir
    New-Item -ItemType Directory -Force -Path $to | Out-Null
    Copy-Item -Path (Join-Path $from "*") -Destination $to -Recurse -Force
}
foreach ($file in @(
    "pyproject.toml", "requirements.txt", "requirements-hardware.txt",
    "requirements-stt-cuda.txt", "README.ko.md"
)) {
    $from = Join-Path $Source $file
    if (Test-Path $from) { Copy-Item -LiteralPath $from -Destination (Join-Path $Root $file) -Force }
}
Ok "복사 완료"

# ── 4. venv 와 의존성 ────────────────────────────────────────────────────────
Step 4 "venv + 의존성 (몇 분 걸립니다)"
$venv = Join-Path $Root ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $py.Source -m venv $venv
}
$vpy = Join-Path $venv "Scripts\python.exe"
& $vpy -m pip install --quiet --upgrade pip
$req = Join-Path $Root "requirements.txt"
if (Test-Path $req) {
    # ★ **종료코드를 본다** (2026-09-12).
    #
    #   여기가 `--quiet` 로만 돌고 결과를 안 봤다. 노트북에서 휠 빌드가 하나
    #   실패해도 화면에는 아무 말도 안 나오고 다음 줄로 넘어가, 「설치 성공」인데
    #   문서 읽기 라이브러리만 빠진 자비스가 만들어진다. 그러면 나중에
    #   「첨부한 문서를 못 읽어요」로 돌아오고, 원인을 처음부터 다시 판다.
    #
    #   바로 아래 `pip install -e` 는 이미 확인하고 있었다 - 한쪽만 보고 있었다.
    & $vpy -m pip install -r $req
    if ($LASTEXITCODE -ne 0) {
        throw "의존성 설치가 실패했습니다 (pip 종료코드 $LASTEXITCODE) - 위 출력을 보세요. 이대로 두면 문서 첨부와 한글 읽기가 조용히 안 됩니다."
    }
}
Ok "의존성 설치"

# ★ 2026-08-22: 이 줄이 빠져 있었다. `src/` 를 복사만 하고 **패키지를 venv 에
#   등록하지 않아서**, 설치는 전부 OK 로 끝났는데 띄우면 이렇게 죽었다:
#
#       ModuleNotFoundError: No module named 'alture_jarvis'
#
#   본체는 `install.ps1` 이 `pip install -e .` 를 한다. 위성 스크립트를 새로
#   쓰면서 그 줄을 안 옮긴 것이다 — **새로 쓸 때는 원본이 하던 일을 세어라.**
#   (나래님 노트북에서 실제로 걸렸고, 그쪽 Claude 가 로그를 파서 찾아냈다.)
& $vpy -m pip install --quiet -e $Root
& $vpy -c "import alture_jarvis" 2>$null
if ($LASTEXITCODE -ne 0) { throw "alture_jarvis 를 venv 에 등록하지 못했습니다 — pip install -e 가 실패했습니다." }
Ok "alture_jarvis 패키지 등록 (import 확인됨)"

if ($WithVoice) {
    Step "4b" "음성 (마이크 + faster-whisper + CUDA 런타임)"
    foreach ($extra in @("requirements-hardware.txt", "requirements-stt-cuda.txt")) {
        $path = Join-Path $Root $extra
        if (Test-Path $path) {
            & $vpy -m pip install -r $path
            if ($LASTEXITCODE -ne 0) { Write-Warning "$extra 설치 실패 (코드 $LASTEXITCODE) - 음성이 느리거나 안 될 수 있습니다" }
        }
    }
    # ★ 깔았다고 도는 게 아니다. **실제로 GPU 가 잡히는지 지금 확인한다** —
    #   나중에 "음성이 느린데요"로 오면 원인을 처음부터 다시 판다.
    $gpu = & $vpy -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())" 2>$null
    if ($gpu -and [int]$gpu -gt 0) {
        Ok ("CUDA 장치 {0}장 — STT 가 GPU 로 돕니다" -f $gpu)
    } else {
        Warn "CUDA 장치를 못 찾았습니다 — STT 가 CPU 로 돕니다(느림). /health 에 이유가 뜹니다"
    }
}

# ── 5. 브라우저 (자기 크롬) ──────────────────────────────────────────────────
#
# ★ 여기가 이 설계의 요점이다. 브라우저는 **이 PC 것**이라 여기 깔아야 한다.
#   이걸 빼면 위성이 아니라 그냥 창 하나가 된다.
if ($SkipBrowser) {
    Warn "브라우저 건너뜀 (-SkipBrowser) — 조사·자동화가 안 됩니다"
} else {
    Step 5 "Playwright 크로미움 (수백 MB, 오래 걸립니다)"
    & $vpy -m playwright install chromium
    Ok "브라우저 설치"
}

# ── 6. 설정 ──────────────────────────────────────────────────────────────────
Step 6 ".env 생성"
$envPath = Join-Path $Root ".env"
if (Test-Path $envPath) {
    Copy-Item -LiteralPath $envPath -Destination "$envPath.bak-$(Get-Date -Format yyyyMMdd-HHmmss)" -Force
    Warn "기존 .env 를 백업했습니다"
}
$envBody = @"
# 위성 자비스 — 손은 이 PC, 두뇌는 본체
#
# 이 파일이 이 PC 의 설정 자리다. 같은 이름을 사용자 환경변수에도 넣으면
# 그쪽이 이겨서(load_env_file 은 기존 값을 안 덮는다) 여기를 고쳐도 안 먹는다.

JARVIS_ROLE=satellite

# 본체에서 빌리는 것 둘
JARVIS_OLLAMA_BASE_URL=http://${BrainHost}:11434
JARVIS_SUPERTONIC_BASE_URL=http://${BrainHost}:7788

# ★ 본체와 **같은 태그**여야 한다 (2026-08-23).
#
# 이 줄이 없으면 설정 기본값(`plopfit-gemma4:latest`)으로 떨어진다. 그런데 본체
# 자비스는 `plopfit-gemma4-qat` 를 쓰고 `OLLAMA_MAX_LOADED_MODELS=1` 이라,
# **위성이 한 번 말을 걸 때마다 본체 자비스의 모델이 GPU 에서 밀려난다.**
# 다음 대화는 15GB 재적재를 기다리므로 본체 쪽에서는 "자비스가 갑자기 느려졌다"로
# 보이고, 위성 쪽에는 아무 표시도 안 난다.
#
# 실측(2026-08-23): 나래님 노트북에서 위성을 쓰는 동안 본체 벤치가 판마다
# 19GB 재적재에 걸려 과제 하나가 244초씩 걸렸다. 사고 P 의 새 경로다.
JARVIS_OLLAMA_MODEL=$BrainModel

# 본체와 같은 토큰이어야 붙는다
JARVIS_CONTROL_TOKEN=$ControlToken

# 갱신을 받아 올 본체. 비워 두면 위의 OLLAMA_BASE_URL 에서 호스트를 끌어온다 —
# 이미 깔린 위성이 재설치 없이 받을 수 있게 그렇게 만들었다.
JARVIS_BRAIN_HOST=$BrainHost

# 이 PC 는 자기만 듣는다(화면도 이 PC 에서 연다)
JARVIS_HOST=127.0.0.1

# 우리 DB(입시·진로) 조회. 비어 있으면 그 도구들이 안 뜬다.
JARVIS_INHOUSE_API_KEY=$InhouseApiKey

# 음성 입력. GPU 가 없거나 -WithVoice 없이 깔았으면 0 으로 두는 편이 낫다 —
# 켜 두면 뜰 때마다 없는 것을 올리려 든다.
JARVIS_VOICE_ENABLED=$(if ($WithVoice) { "1" } else { "0" })
JARVIS_HOTKEY_ENABLED=$(if ($WithVoice) { "1" } else { "0" })
"@
[System.IO.File]::WriteAllText($envPath, $envBody, (New-Object System.Text.UTF8Encoding($true)))
Ok ".env 작성 (BOM 포함 — 사고 J 재발 방지)"

$tokenDir = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $tokenDir | Out-Null
[System.IO.File]::WriteAllText((Join-Path $tokenDir "control.token"), $ControlToken, (New-Object System.Text.UTF8Encoding($false)))
Ok "control.token 저장"

# ── 7. 확인 ──────────────────────────────────────────────────────────────────
Step 7 "설정이 실제로 읽히는가"
$check = & $vpy -c @"
import os, sys
sys.path.insert(0, r'$Root\src')
os.environ.setdefault('JARVIS_RUNTIME_ROOT', r'$Root')
from alture_jarvis.config import JarvisConfig, load_env_file
load_env_file()
c = JarvisConfig.from_env()
print('role=%s brain=%s voice_in=%s browser=%s' % (c.jarvis_role, c.ollama_base_url, c.voice_enabled, c.browser_enabled))
"@
Ok $check
if ($check -notmatch "role=satellite") { throw "역할이 satellite 로 안 읽힙니다 — .env 를 확인하세요." }

# ── 8. 자동 시작 ─────────────────────────────────────────────────────────────
if ($NoTask) {
    Warn "작업 스케줄러 등록 건너뜀 (-NoTask)"
} else {
    Step 8 "로그인 시 자동 시작 등록"
    $entry = Join-Path $Root "scripts\task_entry.py"
    # ★ 2026-08-22: 처음엔 결과를 `| Out-Null` 로 삼키고 무조건 OK 를 찍었다.
    #   나래님 노트북에서 "ERROR: Access is denied." 가 뜨는데도 화면엔 "OK 등록"
    #   이 나갔고, 그다음 단계가 **없는 작업을 실행하려다** 죽었다.
    #   예외가 없다고 성공이 아니다 — 이 저장소가 여러 번 데인 그 모양이다.
    # ★ 2026-08-24: 이 `2>&1` 이 **바로 아래 폴백을 사문화시키고 있었다.**
    #   PowerShell 5.1 은 네이티브 exe 의 stderr 를 `2>&1` 로 합치면 그 줄을
    #   NativeCommandError 로 감싸고, 이 파일 위쪽의 `$ErrorActionPreference =
    #   "Stop"` 아래서 그것은 **터미네이팅**이다. 즉 schtasks 가 "Access is denied"
    #   를 뱉는 순간 스크립트가 죽어서, `$LASTEXITCODE` 를 볼 기회조차 없었다.
    #   schtasks 가 막힌 PC 를 위해 쓴 시작프로그램 폴백이 **그 PC 에서만** 안 돌았다.
    #   같은 함정이 apply_update.ps1 에서 갱신 전체를 반쯤 바꾼 채로 남겼다.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    schtasks /Create /TN "RoboMetaFit-Alture-Jarvis" /TR "`"$vpy`" `"$entry`"" /SC ONLOGON /RL LIMITED /F 2>&1 | Out-Null
    $taskCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($taskCode -eq 0) {
        Ok "작업 스케줄러 등록"
    } else {
        # 회사 정책이 schtasks 를 막는 경우가 있다(나래님 노트북이 그랬다).
        # 그때는 **시작프로그램 폴더**로 간다 — 관리자 권한이 필요 없고 결과는 같다.
        Warn "schtasks 가 막혔습니다(코드 $taskCode) - 시작프로그램 폴더로 대신합니다"
        try {
            $startup = [Environment]::GetFolderPath("Startup")
            $pyw = Join-Path $venv "Scripts\pythonw.exe"
            if (-not (Test-Path $pyw)) { $pyw = $vpy }
            $lnk = Join-Path $startup "JARVIS.lnk"
            $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
            $sc.TargetPath = $pyw
            $sc.Arguments = "`"$entry`""
            $sc.WorkingDirectory = $Root
            $sc.Save()
            if (Test-Path $lnk) { Ok "시작프로그램 등록 ($lnk)" } else { throw "바로가기 생성 실패" }
        } catch {
            Warn "자동 시작 등록 실패 - 수동으로 띄우세요: `"$vpy`" `"$entry`""
        }
    }
}

# ── 9. 화면 ─────────────────────────────────────────────────────────────────
#
# 시작프로그램의 바로가기는 **백엔드**(task_entry.py)를 띄우는 것이 맞다.
# 바탕화면 바로가기는 **화면**(HUD exe)이어야 한다 — 둘을 헷갈리면 눌러도
# 아무 일이 안 난다(이미 떠 있는 백엔드를 또 띄우려 들 뿐이다).
Step 9 "바탕화면에 화면 바로가기"
$hud = Join-Path $Root "ui\alture-jarvis-hud.exe"
if (Test-Path $hud) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $lnk = Join-Path $desktop "JARVIS.lnk"
        $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
        $sc.TargetPath = $hud
        $sc.WorkingDirectory = (Split-Path -Parent $hud)
        $sc.Save()
        if (Test-Path $lnk) { Ok "바탕화면 JARVIS.lnk (화면)" } else { throw "생성 실패" }
    } catch {
        Warn "바탕화면 바로가기 실패 - 직접 실행하세요: $hud"
    }
} else {
    Warn "화면(alture-jarvis-hud.exe)이 묶음에 없습니다 - 사용자님께 요청하세요"
}

Write-Host ""
Write-Host "설치 끝났습니다." -ForegroundColor Green
Write-Host "  백엔드 : schtasks /Run /TN `"RoboMetaFit-Alture-Jarvis`"  (자동 시작됨)"
Write-Host "  화면   : 바탕화면의 JARVIS 아이콘  <- 실제로 쓰는 것은 이쪽"
Write-Host "  확인   : curl http://127.0.0.1:8091/health"
Write-Host "  되돌리기: schtasks /Delete /TN `"RoboMetaFit-Alture-Jarvis`" /F ; Remove-Item -Recurse `"$Root`""
Write-Host ""
$voiceLine = if ($WithVoice) { "파일·창·크롬·스킬 · 음성 입력(STT)" } else { "파일·창·크롬·스킬" }
Write-Host ("이 PC 에서 도는 것 : {0}" -f $voiceLine) -ForegroundColor Gray
Write-Host "본체에서 빌리는 것 : 젬마 추론 · 음성 합성(소리는 이 PC 에서 납니다)" -ForegroundColor Gray
Write-Host "없는 것            : 카메라 · 격리 상자 · 예약 메일" -ForegroundColor Gray
Write-Host ""
Write-Host "★ 사람마다 따로 해야 하는 것 (설치로는 안 됩니다)" -ForegroundColor Yellow
Write-Host "   구글(Drive/Gmail/Calendar) : 화면에서 '구글 연결' 눌러 본인 계정으로"
Write-Host "   네이버 등 로그인            : 자비스 브라우저에서 한 번 로그인하면 유지됩니다"
if (-not $InhouseApiKey) {
    Write-Host "   우리 DB 조회               : -InhouseApiKey 를 안 줘서 꺼져 있습니다"
}
if (-not $WithVoice) {
    Write-Host ""
    Write-Host "음성까지 쓰려면 -WithVoice 로 다시 실행하세요 (NVIDIA GPU 필요)" -ForegroundColor Yellow
}
