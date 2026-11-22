#!/bin/bash
# 손자리 맥 .dmg 만들기 (2026-11-03 · 설계 D5). 맥에서 돌린다. **만들기만 한다 — 서명 · 공증 · 올리기는 대표가 정한다.**
#
# 담기는 것 (11-17 대표: dmg 에는 앱 하나 · 로고만 누르면 깔리게)
#   Sonjari.app                          화면(Tauri). 처음 켜질 때 본체가 없으면 아래 묶음으로 뒤에서 깔고 응용 프로그램 폴더로 옮긴다(mac_setup.rs)
#     Contents/Resources/backend/        파이썬 본체(src · pyproject) + 자료(recipes · skills · packs · capabilities) + install_mac.sh · check_bundle.py
#     Contents/Helpers/SonjariVoice.app  맥 음성 도우미(마이크 권리와 함께 먼저 서명)
#
# 쓰는 법(맥, 저장소의 tools/alture-jarvis 에서):
#   PATH=$HOME/.local/node/bin:$HOME/.cargo/bin:$PATH bash scripts/mac/build_mac_dmg.sh
# 결과: dist/Sonjari-<판>-mac-arm64.dmg
#
# ★ 2026-11-17 서명 · 공증(대표 맥 터미널에서 — ssh 세션은 키체인이 잠겨 서명이 안 된다):
#   SONJARI_SIGN_IDENTITY="Developer ID Application: YOUR NAME (TEAMID)" SONJARI_NOTARY_PROFILE=sonjari-notary #     PATH=$HOME/.local/node/bin:$HOME/.cargo/bin:$PATH bash scripts/mac/build_mac_dmg.sh
#   두 값이 없으면 예전처럼 애드혹 서명 · 공증 없음(베타).
set -euo pipefail
SIGN_ID="${SONJARI_SIGN_IDENTITY:-}"
NOTARY="${SONJARI_NOTARY_PROFILE:-}"
if [ -n "$NOTARY" ] && [ -z "$SIGN_ID" ]; then echo "공증하려면 SONJARI_SIGN_IDENTITY 도 주세요." >&2; exit 2; fi
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
[ "$(uname -s)" = "Darwin" ] || { echo "맥에서만 돌립니다." >&2; exit 2; }

VERSION="$(python3 -c 'import json;print(json.load(open("ui/src-tauri/tauri.conf.json"))["version"])')"
python3 -c 'import json,sys;u=(json.load(open("ui/src-tauri/tauri.macos.conf.json")).get("plugins") or {}).get("updater");sys.exit(0 if isinstance(u,dict) else 1)' \
  || { echo "ui/src-tauri/tauri.macos.conf.json 에 plugins.updater 가 없습니다 — 앱이 켜자마자 죽습니다(11-17). 굽기 폴더가 저장소와 같은지 보세요." >&2; exit 1; }
echo "[1/4] 화면 빌드 (판 $VERSION)"
( cd ui && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npx tauri build --bundles app )
APP="ui/src-tauri/target/release/bundle/macos/Sonjari.app"
[ -d "$APP" ] || { echo "Sonjari.app 이 안 만들어졌습니다." >&2; exit 1; }

# ★ 2026-11-17: 켜 보기 — 서명 · 공증 전에 앱을 6초 실제로 켠다. 이날 공증까지 통과한 dmg 의 앱이 켜자마자 죽었다
#   (맥 굽기 폴더에 옛 tauri.macos.conf.json 이 남아 plugins.updater 가 null → PluginInitialization panic).
#   다른 손자리가 이미 떠 있으면 한 개만 뜨기 규칙으로 바로 끝날 수 있다 — 그래서 「죽음」은 panic · abort 로만 가른다.
SMOKE_LOG="$(mktemp)"
"$APP/Contents/MacOS/alture-jarvis-hud" > "$SMOKE_LOG" 2>&1 &
SMOKE_PID=$!
sleep 6
if kill -0 "$SMOKE_PID" 2>/dev/null; then
  kill "$SMOKE_PID" 2>/dev/null || true
  wait "$SMOKE_PID" 2>/dev/null || true
  echo "  켜 보기: 6초 동안 살아 있음"
else
  wait "$SMOKE_PID" 2>/dev/null; SMOKE_RC=$?
  if [ "$SMOKE_RC" -ge 128 ] || grep -q "panicked" "$SMOKE_LOG"; then
    echo "앱이 켜자마자 죽습니다(종료 코드 $SMOKE_RC) — 서명 · 공증으로 넘어가지 않습니다:" >&2
    head -20 "$SMOKE_LOG" >&2
    exit 1
  fi
  echo "  켜 보기: 바로 끝남(종료 코드 $SMOKE_RC · panic 없음 — 이미 떠 있는 손자리로 넘긴 것으로 봄)"
fi

echo "[2/4] 담을 것 모으기 — dmg 에는 앱 하나(11-17 대표: 로고만 누르면 깔리게)"
STAGE="$(mktemp -d)/Sonjari"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
# ★ 2026-11-17: 본체 묶음은 앱 안(Contents/Resources/backend)에 싣는다. 앱이 처음 켜질 때 본체가 없으면 그 안의 install_mac.sh 를
#   뒤에서 돌린다(mac_setup.rs). 예전 「손자리 설치.command」 · backend 폴더 · 안내 그림은 dmg 에서 뺐다 — 대표가 새 계정 시험에서
#   로고부터 눌렀다(손님도 그렇다).
PAYLOAD="$STAGE/Sonjari.app/Contents/Resources/backend"
mkdir -p "$PAYLOAD/scripts/mac" "$PAYLOAD/packaging/msix"
rsync -a --exclude '__pycache__' src "$PAYLOAD/"
# ★ 2026-11-03: 자료(recipes · skills · packs)도 담는다 — 빠지면 「스킬 0개」 · 팩 없음(check_bundle.py REQUIRED_DATA).
rsync -a --exclude 'drafts' --exclude '__pycache__' recipes skills packs "$PAYLOAD/"
# ★ 2026-11-12: 기능 카드도 담는다 — `capability_cards.py` 는 앱 바로 아래 capabilities/ 를 찾는다. 빠지면 sonjari_guide(query) 가 빈다.
rsync -a capabilities "$PAYLOAD/"
cp pyproject.toml README.ko.md "$PAYLOAD/"
cp scripts/mac/install_mac.sh "$PAYLOAD/scripts/mac/"
cp packaging/msix/check_bundle.py "$PAYLOAD/packaging/msix/"
# 실행 파일은 Resources 에 두지 않는다(서명 규칙 · 「자료 칸의 코드」) — 앱 안에 Mach-O 가 숨어 있으면 공증이 거절한다.
if find "$PAYLOAD" -type f -exec file {} + 2>/dev/null | grep -q "Mach-O"; then
  echo "본체 묶음(Resources/backend)에 실행 파일이 섞였습니다 — 빼고 다시:" >&2
  find "$PAYLOAD" -type f -exec file {} + | grep "Mach-O" | head -5 >&2
  exit 1
fi
# ★ 2026-11-18: 비밀 검사 — 스토어 굽기 · NAS 올리기와 같은 검사기(packaging/msix/scan_package_secrets.py). 걸리면 굽지 않는다(소스에서 고친다).
"${SONJARI_PYTHON:-python3}" packaging/msix/scan_package_secrets.py "$PAYLOAD" || { echo "본체 묶음에 비밀처럼 보이는 것이 있습니다 — 위 목록을 보고 소스에서 고친 뒤 다시" >&2; exit 1; }
# ★ 2026-11-16: 맥 음성 도우미(받아쓰기 · 녹음) — 손님 맥에는 swiftc 가 없어 여기서 굽는다. 실행 칸(Contents/Helpers)에 두고
#   build.sh 가 권리 목록(마이크)과 함께 먼저 서명한다. 앱 서명은 --deep 을 쓰지 않는다 — 다시 서명하면 그 권리가 지워진다.
bash native/mac/SonjariVoice/build.sh "$STAGE/Sonjari.app/Contents/Helpers" || { echo "맥 음성 도우미 굽기 실패(위 줄이 까닭 · 11-17 출력을 숨기지 않음)" >&2; exit 1; }
# ★ 2026-11-18: 실행 도우미 — 본체 파이썬을 이 서명된 앱의 자식으로 띄워 맥 허락 창이 「python3.12」 대신 「손자리」 이름 ·
#   이유 문장으로 뜨게 한다(native/mac/SonjariEngine/main.swift 머리말). 음성 도우미와 같은 자리 · 같은 서명 순서.
bash native/mac/SonjariEngine/build.sh "$STAGE/Sonjari.app/Contents/Helpers" || { echo "맥 실행 도우미 굽기 실패(위 줄이 까닭)" >&2; exit 1; }
# ★ 2026-11-18: 판 표시 — 앱이 켜질 때 깔린 본체의 판과 다르면 설치를 다시 돌린다(mac_setup.rs). 이미 깐 계정이 새 dmg 를 열어도
#   옛 본체로 돌던 것(11-17 새 계정 시험)을 막는다.
# ★ 11-20: 맥 굽기 폴더엔 git 이 없다 — PC 가 동기화 때 남긴 .build_rev 를 읽는다(11-18 판은 nogit 으로 찍혔음).
echo "$VERSION $(git rev-parse --short=12 HEAD 2>/dev/null || cat .build_rev 2>/dev/null || echo nogit) $(date +%Y%m%d%H%M%S)" > "$PAYLOAD/PAYLOAD_STAMP"
if [ -n "$SIGN_ID" ]; then
  # 11-17: Developer ID + 강화 런타임 + 시각 도장 — 공증의 세 조건.
  codesign --force --options runtime --timestamp --sign "$SIGN_ID" "$STAGE/Sonjari.app"
else
  # ★ 11-04: 애플 실리콘은 서명이 아예 없으면 안 열린다 — 공증 없는 베타는 애드혹으로.
  codesign --force --sign - "$STAGE/Sonjari.app"
fi
codesign --verify --deep --strict "$STAGE/Sonjari.app" || { echo "앱 서명 검증 실패" >&2; exit 1; }

echo "[3/4] .dmg 묶기 (hdiutil — 파인더 꾸미기 없음 · 허락 창 없음)"
mkdir -p dist
OUT="dist/Sonjari-$VERSION-mac-arm64.dmg"
rm -f "$OUT"
hdiutil create -volname "Sonjari" -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null

if [ -n "$SIGN_ID" ]; then
  codesign --force --timestamp --sign "$SIGN_ID" "$OUT"
fi
if [ -n "$NOTARY" ]; then
  echo "[공증] 애플에 제출하고 끝날 때까지 기다립니다(처음 제출은 오래 걸릴 수 있음)"
  xcrun notarytool submit "$OUT" --keychain-profile "$NOTARY" --wait | tee "dist/notary_$VERSION.log"
  grep -q "status: Accepted" "dist/notary_$VERSION.log" || { echo "공증 통과 못 함 — 위 id 로: xcrun notarytool log <id> --keychain-profile $NOTARY" >&2; exit 1; }
  xcrun stapler staple "$OUT"
  spctl -a -t open --context context:primary-signature -v "$OUT"
  # ★ 2026-11-22: 앱 안 업데이트(설계_맥앱안업데이트 §3-1) — 타우리 업데이터가 받는 앱 꾸러미. dmg 공증이 안의 앱도 공증하므로
  #   앱에도 도장을 찍어(인터넷 없이도 열리게) 그대로 묶는다. 서명(.sig)은 여기서 하지 않는다 — 원격 굽기는 비밀 열쇠를 모른다
  #   (대표가 PC 에서 scripts/mac/sign_mac_release.ps1 로 한 번).
  xcrun stapler staple "$STAGE/Sonjari.app" || echo "  경고: 앱 도장 실패(공증은 dmg 로 되어 있음 · 인터넷 확인으로 열림)"
  TARBALL="dist/Sonjari-$VERSION-mac-arm64.app.tar.gz"
  rm -f "$TARBALL"
  COPYFILE_DISABLE=1 tar -C "$STAGE" -czf "$TARBALL" Sonjari.app
  echo "  앱 꾸러미: $TARBALL ($(du -h "$TARBALL" | cut -f1)) — 서명은 PC 에서"
fi
echo "[4/4] 끝: $OUT ($(du -h "$OUT" | cut -f1))"
if [ -z "$SIGN_ID" ]; then echo "서명 · 공증은 하지 않았습니다(애드혹 · 베타)."; fi
