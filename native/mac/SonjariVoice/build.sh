#!/bin/bash
# 손자리 음성 도우미(SonjariVoice.app) 굽기 — 맥에서, Xcode 명령줄 도구(swiftc)가 있을 때.
#   bash build.sh <나올 폴더>            # 예: bash build.sh "$HOME/Library/Application Support/Sonjari/app/voice"
# 권리 목록(entitlements.plist)에는 주석 · 한글 · CRLF 를 넣지 않는다 — codesign 의 AMFI 해석기가 「syntax error near line 1」로 거절한다(11-17 · plutil 은 통과했음).
# 마이크 권리는 강화 런타임(공증)으로 서명할 때만 쓰인다.
# 서명: 기본은 애드혹(-). SONJARI_SIGN_IDENTITY 에 Developer ID 이름을 주면 강화 런타임 + 마이크 권리로 서명한다(공증은 따로).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:?나올 폴더를 주세요}"
APP="$OUT/SonjariVoice.app"
command -v swiftc >/dev/null || { echo "swiftc 가 없습니다(xcode-select --install)." >&2; exit 2; }
WORK="$(mktemp -d)"
swiftc -O -o "$WORK/SonjariVoice" "$HERE/main.swift" 2>"$WORK/build.log" || { cat "$WORK/build.log" >&2; exit 1; }
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$HERE/Info.plist" "$APP/Contents/Info.plist"
cp "$WORK/SonjariVoice" "$APP/Contents/MacOS/SonjariVoice"
if [ -n "${SONJARI_SIGN_IDENTITY:-}" ]; then
  codesign --force --options runtime --timestamp --entitlements "$HERE/entitlements.plist" --sign "$SONJARI_SIGN_IDENTITY" "$APP"  # 공증은 시각 도장(--timestamp) 없으면 거절(11-17)
else
  codesign --force --sign - --identifier com.sonjari.voice "$APP"
fi
codesign --verify --strict "$APP"
echo "$APP"
