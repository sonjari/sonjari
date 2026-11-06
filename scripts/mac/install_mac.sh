#!/bin/bash
# 손자리 맥 설치 (2026-11-03 · 설계 docs/설계_맥판_1103.md D5)
#
# 하는 일
#   1. 코드를 ~/Library/Application Support/Sonjari/app 에 놓는다(다시 돌리면 코드만 바꾸고 데이터는 그대로 — 업데이트 겸용).
#   2. uv 로 파이썬 3.12 가상환경을 만들고 손자리를 깐다(uv 가 없으면 astral.sh 공식 설치기로 깐다).
#   3. 데이터 자리의 .env 를 처음 한 번만 만든다(있으면 안 건드림).
#   4. 로그인할 때 백엔드를 켜는 LaunchAgent(com.sonjari.backend)를 화면 세션(gui/$UID)에 등록한다.
#      ★ SSH 세션에서 직접 띄운 프로세스는 화면에 창을 못 띄운다(11-03 겪음) — 크롬 · 알림을 위해 반드시 화면 세션으로.
#   5. http://127.0.0.1:8091/health 가 답할 때까지 기다린다.
#
# 쓰는 법
#   bash install_mac.sh                         # 이 맥의 Ollama 를 쓴다(로컬)
#   bash install_mac.sh --brain 192.168.0.91     # 집 PC 의 Ollama 를 빌린다(위성)
#   bash install_mac.sh --uninstall             # 자동 시작만 끈다(데이터는 남김)
set -euo pipefail

BRAIN=""
UNINSTALL=0
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
while [ $# -gt 0 ]; do
  case "$1" in
    --brain) BRAIN="$2"; shift 2 ;;
    --source) SRC="$2"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    *) echo "모르는 옵션: $1" >&2; exit 2 ;;
  esac
done

[ "$(uname -s)" = "Darwin" ] || { echo "맥에서만 돌립니다." >&2; exit 2; }

ROOT="$HOME/Library/Application Support/Sonjari"
APP="$ROOT/app"
LOGS="$ROOT/logs"
LABEL="com.sonjari.backend"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [ "$UNINSTALL" = 1 ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "자동 시작을 껐습니다. 데이터는 $ROOT 에 그대로 있습니다."
  exit 0
fi

mkdir -p "$APP" "$LOGS" "$HOME/Library/LaunchAgents"
# ★ 11-04 대표 첫 설치 시험: 손님 터미널에 「mac: skip Windows-only modules: av, comtypes …」 같은 영어 · 개발 줄이 그대로 보였다.
#   화면에는 단계마다 한국어 한 줄만 · 자세한 줄(경로 · 부품 점검 · 내려받기)은 기록 파일로. 실패하면 그 기록 자리를 알려 준다.
INSTALL_LOG="$LOGS/install.log"
echo "── $(date '+%Y-%m-%d %H:%M:%S') 설치 시작 ($SRC → $APP)" >> "$INSTALL_LOG"

# 1. 코드 + 자료 — src · pyproject, 그리고 recipes · skills · packs. .venv · 데이터는 건드리지 않는다.
#   ★ 2026-11-03 맥미니 마법사 「쓰임」에 분야마다 「스킬 0개」: 여기서 src 만 옮겼다(9-16 윈도우 포장본과 같은 꼴).
#   config.py 가 보는 자리(<alture_jarvis>/../../ = $APP)에 둔다. 폴더 목록 · 뺄 것은 check_bundle.py 의
#   REQUIRED_DATA · DATA_EXCLUDES 와 같다(tests/test_bundle_requirements.py 가 붙잡는다). drafts 는 이 맥에서 앱이 쓴 것이라
#   옮기지도 지우지도 않는다(--exclude 는 --delete 에서도 지켜진다).
echo "[1/5] 손자리 파일을 놓는 중"
rsync -a --delete --exclude '__pycache__' "$SRC/src/" "$APP/src/"
for DATA in recipes skills packs; do
  rsync -a --delete --exclude 'drafts' --exclude '__pycache__' "$SRC/$DATA/" "$APP/$DATA/"
done
cp "$SRC/pyproject.toml" "$SRC/README.ko.md" "$APP/"

# 2. 파이썬
echo "[2/5] 필요한 부품을 까는 중 (처음엔 몇 분 걸립니다)"
UV="$(command -v uv || true)"
[ -n "$UV" ] || UV="$HOME/.local/bin/uv"
if [ ! -x "$UV" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >> "$INSTALL_LOG" 2>&1
  UV="$HOME/.local/bin/uv"
fi
[ -x "$APP/.venv/bin/python" ] || "$UV" venv -q --python 3.12 "$APP/.venv" >> "$INSTALL_LOG" 2>&1
VIRTUAL_ENV="$APP/.venv" "$UV" pip install -q -e "$APP" >> "$INSTALL_LOG" 2>&1 || { echo "부품을 깔지 못했습니다. 인터넷 연결을 확인한 뒤 다시 눌러 주세요. (기록: $INSTALL_LOG)" >&2; exit 1; }
# 다 들어갔는가 — 윈도우 포장과 같은 검사기(모듈 + 자료 폴더 알맹이 수). 빠졌으면 자동 시작을 걸기 전에 멈춘다.
CHECK="$SRC/packaging/msix/check_bundle.py"
if [ -f "$CHECK" ]; then
  ( cd "$APP" && "$APP/.venv/bin/python" "$CHECK" ) >> "$INSTALL_LOG" 2>&1 || { echo "설치한 손자리에 빠진 것이 있습니다. (기록: $INSTALL_LOG)" >&2; exit 1; }
else
  echo "검사기($CHECK)가 없어 다 들어갔는지 못 봤습니다." >&2; exit 1
fi

# 3. .env — 처음 한 번만.
ENV_FILE="$ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "[3/5] 처음 설정을 만드는 중"
  {
    echo "# 손자리 맥 설정 — install_mac.sh 가 처음 한 번 만들었다. 고친 뒤 백엔드를 다시 켜면 먹는다."
    echo "JARVIS_HOST=127.0.0.1"
    if [ -n "$BRAIN" ]; then
      echo "JARVIS_ROLE=satellite"
      echo "JARVIS_BRAIN_HOST=$BRAIN"
      echo "JARVIS_OLLAMA_BASE_URL=http://$BRAIN:11434"
      echo "JARVIS_SUPERTONIC_BASE_URL=http://$BRAIN:7788"
    fi
    echo "JARVIS_VOICE_ENABLED=0"
    echo "JARVIS_HOTKEY_ENABLED=0"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
else
  echo "[3/5] 전에 쓰던 설정을 그대로 씁니다"
fi

# 4. LaunchAgent
echo "[4/5] 맥을 켜면 손자리도 같이 켜지게 하는 중"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP/.venv/bin/python</string>
    <string>-m</string>
    <string>alture_jarvis</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>LANG</key><string>ko_KR.UTF-8</string>
    <key>PYTHONUTF8</key><string>1</string>
    <key>PATH</key><string>$APP/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOGS/backend.out.log</string>
  <key>StandardErrorPath</key><string>$LOGS/backend.err.log</string>
</dict>
</plist>
PLIST
# ★ 2026-11-03 맥미니(dmg 로 다시 설치): bootout 은 비동기라 바로 bootstrap 하면 「5: Input/output error」로 실패했다
#   (백엔드가 SIGTERMed 상태로 남아 있었다). 완전히 내려갈 때까지 기다리고, 그래도 안 되면 몇 번 더 해 본다.
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
for _ in $(seq 1 50); do launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break; sleep 0.2; done
for attempt in 1 2 3; do
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then break; fi
  [ "$attempt" = 3 ] && { echo "자동 시작 등록에 실패했습니다: launchctl bootstrap $DOMAIN $PLIST" >&2; exit 1; }
  sleep 1
done

# 5. 답할 때까지
echo "[5/5] 손자리가 켜지기를 기다리는 중"
for _ in $(seq 1 60); do
  if curl -s -m 2 http://127.0.0.1:8091/health >/dev/null; then
    echo "손자리가 켜졌습니다."
    echo "── 켜짐 · 데이터 $ROOT · 로그 $LOGS" >> "$INSTALL_LOG"
    exit 0
  fi
  sleep 1
done
echo "손자리가 60초 안에 켜지지 않았습니다. 맥을 다시 켠 뒤 한 번 더 눌러 주세요. (기록: $LOGS/backend.err.log)" >&2
exit 1
