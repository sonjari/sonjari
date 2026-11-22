#!/bin/bash
# 손자리 실행 도우미(SonjariEngine.app) 굽기 — 맥에서, Xcode 명령줄 도구(swiftc)가 있을 때 (2026-11-18).
#   bash build.sh <나올 폴더>            # 예: build_mac_dmg.sh 가 "$STAGE/Sonjari.app/Contents/Helpers" 로 부른다
# 하는 일: 본체 파이썬을 자식으로 띄워 맥 허락 창이 「python3.12」 대신 「손자리」 이름 · 이유 문장으로 뜨게 한다(main.swift 머리말).
# 권리 목록(entitlements.plist)에는 주석 · 한글 · CRLF 를 넣지 않는다 — codesign 이 「syntax error near line 1」로 거절한다(11-17).
# 서명: 기본은 애드혹(-). SONJARI_SIGN_IDENTITY 에 Developer ID 이름을 주면 강화 런타임으로 서명한다(공증은 따로).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:?나올 폴더를 주세요}"
APP="$OUT/SonjariEngine.app"
command -v swiftc >/dev/null || { echo "swiftc 가 없습니다(xcode-select --install)." >&2; exit 2; }
WORK="$(mktemp -d)"
swiftc -O -o "$WORK/SonjariEngine" "$HERE/main.swift" 2>"$WORK/build.log" || { cat "$WORK/build.log" >&2; exit 1; }
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$HERE/Info.plist" "$APP/Contents/Info.plist"
cp "$WORK/SonjariEngine" "$APP/Contents/MacOS/SonjariEngine"
if [ -n "${SONJARI_SIGN_IDENTITY:-}" ]; then
  codesign --force --options runtime --timestamp --entitlements "$HERE/entitlements.plist" --sign "$SONJARI_SIGN_IDENTITY" "$APP"
else
  codesign --force --sign - --identifier com.sonjari.engine "$APP"
fi
codesign --verify --strict "$APP"
echo "$APP"
