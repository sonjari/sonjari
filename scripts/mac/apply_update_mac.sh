#!/bin/sh
# 손자리 맥 파이썬 묶음 교체 (2026-11-16 · docs/설계_맥업데이트_2026-11-16.ko.md §7)
#
# 백엔드(runtime._mac_update_apply)가 서명 · sha256 · 판 확인을 **다 마친 뒤** 새 세션으로 떼어 내 부른다.
# 이 스크립트는 판단하지 않는다 — 지시서(plan_mac.json, mac_update.plan)가 시키는 것만 한다.
#
#   1. 바꿀 것을 옮겨 둔다(backup/<시각>/)
#   2. 받은 것으로 바꾼다
#   3. pyproject.toml 이 바뀌었으면 부품을 다시 깐다(install_mac.sh 와 같은 uv)
#   4. launchctl kickstart -k 로 백엔드를 다시 켠다
#   5. /health 의 build 가 기대한 값인지 본다 — 「켜졌다」 · 200 은 증거가 아니다(updater.py 머리말)
#   6. 아니면 옮겨 둔 것으로 되돌리고 다시 켠다
#   결과는 last_result.json 하나에 — /health 의 mac_update.last_result 로 보인다.
#
# ★ 지시서는 plutil 로 읽는다(맥에 늘 있다). 파이썬으로 읽으면 갈아치우는 도중의 파이썬에 기대게 된다.
set -u

# 시험만을 위한 갈아 끼울 자리(tests/test_mac_update_1116.py). 운영에선 늘 맥 기본 경로.
PLUTIL="${SONJARI_PLUTIL:-/usr/bin/plutil}"
CURL="${SONJARI_CURL:-/usr/bin/curl}"
LAUNCHCTL="${SONJARI_LAUNCHCTL:-launchctl}"

PLAN="${1:-}"
[ -f "$PLAN" ] || { echo "지시서가 없습니다: $PLAN" >&2; exit 2; }
get() { "$PLUTIL" -extract "$1" raw -o - "$PLAN" 2>/dev/null; }

APP="$(get app_root)"
STAGING="$(get staging)"
EXPECT="$(get expected_build)"
RESULT="$(get result)"
BACKUP_ROOT="$(get backup)"
LABEL="$(get launchd_label)"
HEALTH="$(get health_url)"
WAIT="$(get health_wait_sec)"
SEQ="$(get seq)"
WORK="$(dirname "$RESULT")"
LOG="$WORK/apply_mac.log"
DOMAIN="gui/$(id -u)"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
write_result() {  # $1 true/false · $2 까닭 · $3 실제 build
  printf '{"ok": %s, "reason": "%s", "expected": "%s", "got": "%s", "seq": %s, "at": %s}\n' \
    "$1" "$2" "$EXPECT" "$3" "${SEQ:-0}" "$(date +%s)" > "$RESULT.tmp" && mv "$RESULT.tmp" "$RESULT"
}

if [ -z "$APP" ] || [ -z "$EXPECT" ] || [ ! -d "$STAGING" ] || [ ! -d "$APP" ]; then
  write_result false "지시서를 읽지 못했거나 자리가 없습니다" ""
  exit 1
fi

# 바꿀 것 목록 — 지시서의 dirs · files 를 순서대로.
ITEMS=""
for key in dirs files; do
  i=0
  while item="$(get "$key.$i")" && [ -n "$item" ]; do
    ITEMS="$ITEMS
$item"
    i=$((i + 1))
  done
done

sleep 1  # 부른 쪽의 응답이 먼저 나가게
BACKUP="$BACKUP_ROOT/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP"
log "시작: 기대 $EXPECT · seq $SEQ · 옮겨 둘 자리 $BACKUP"

MOVED=""
restore() {
  log "되돌림: $1"
  printf '%s\n' "$MOVED" | while IFS= read -r item; do
    [ -n "$item" ] || continue
    rm -rf "$APP/$item"
    if [ -e "$BACKUP/$item" ]; then
      mkdir -p "$(dirname "$APP/$item")"
      mv "$BACKUP/$item" "$APP/$item"
    fi
  done
}

health_build() {
  "$CURL" -s -m 3 "$HEALTH" 2>/dev/null | "$PLUTIL" -extract build raw -o - - 2>/dev/null
}

wait_for_build() {  # $1 기대값(빈 글이면 아무 판이든 답하면)
  waited=0
  while [ "$waited" -lt "${WAIT:-90}" ]; do
    got="$(health_build)"
    if [ -n "$got" ] && { [ -z "$1" ] || [ "$got" = "$1" ]; }; then
      echo "$got"
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  echo "$(health_build)"
  return 1
}

# 1 · 2 — 옮겨 두고 바꾼다
NL='
'
OLDIFS="$IFS"; IFS="$NL"
for item in $ITEMS; do
  [ -n "$item" ] || continue
  [ -e "$STAGING/$item" ] || continue
  if [ -e "$APP/$item" ]; then
    mkdir -p "$(dirname "$BACKUP/$item")"
    mv "$APP/$item" "$BACKUP/$item" || { IFS="$OLDIFS"; restore "옮겨 두기 실패($item)"; write_result false "옮겨 두기 실패" ""; exit 1; }
  fi
  MOVED="$MOVED$NL$item"
  mkdir -p "$(dirname "$APP/$item")"
  mv "$STAGING/$item" "$APP/$item" || { IFS="$OLDIFS"; restore "바꾸기 실패($item)"; write_result false "바꾸기 실패" ""; exit 1; }
done
IFS="$OLDIFS"
log "바꿈:$(printf '%s' "$MOVED" | tr '\n' ' ')"

# 3 — 부품이 바뀌었으면 다시 깐다
if [ -f "$BACKUP/pyproject.toml" ] && ! cmp -s "$BACKUP/pyproject.toml" "$APP/pyproject.toml"; then
  UV="$(command -v uv || true)"
  [ -n "$UV" ] || UV="$HOME/.local/bin/uv"
  if [ ! -x "$UV" ] || ! VIRTUAL_ENV="$APP/.venv" "$UV" pip install -q -e "$APP" >> "$LOG" 2>&1; then
    restore "부품 설치 실패"
    "$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" >> "$LOG" 2>&1
    write_result false "부품을 깔지 못해 되돌렸습니다" ""
    exit 1
  fi
fi

# 4 · 5 — 다시 켜고 판을 본다
"$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" >> "$LOG" 2>&1
if got="$(wait_for_build "$EXPECT")"; then
  log "성공: $got"
  write_result true "" "$got"
  # 옮겨 둔 것은 최근 둘만 남긴다(옮겨 둔 자리 안에서만 지운다).
  ls -1t "$BACKUP_ROOT" 2>/dev/null | tail -n +3 | while IFS= read -r old; do
    [ -n "$old" ] && rm -rf "${BACKUP_ROOT:?}/$old"
  done
  exit 0
fi

# 6 — 되돌린다
restore "새 판이 안 떴습니다(본 값: ${got:-없음})"
"$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" >> "$LOG" 2>&1
back="$(wait_for_build "")"
write_result false "새 판이 /health 에 안 떠서 되돌렸습니다" "$back"
exit 1
