#!/bin/bash
# 손자리 맥 .dmg 만들기 (2026-11-03 · 설계 D5). 맥에서 돌린다. **만들기만 한다 — 서명 · 공증 · 올리기는 대표가 정한다.**
#
# 담기는 것
#   Sonjari.app                 화면(Tauri). 서명 없음 → 처음 열 때 「확인되지 않은 개발자」(오른쪽 클릭 → 열기)
#   손자리 설치.command          두 번 누르면: 백엔드 설치(install_mac.sh) + Sonjari.app 을 응용 프로그램 폴더로
#   backend/                    파이썬 백엔드 소스(src · pyproject) + 자료(recipes · skills · packs) + install_mac.sh · check_bundle.py
#
# 쓰는 법(맥, 저장소의 tools/alture-jarvis 에서):
#   PATH=$HOME/.local/node/bin:$HOME/.cargo/bin:$PATH bash scripts/mac/build_mac_dmg.sh
# 결과: dist/Sonjari-<판>-mac-arm64.dmg
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
[ "$(uname -s)" = "Darwin" ] || { echo "맥에서만 돌립니다." >&2; exit 2; }

VERSION="$(python3 -c 'import json;print(json.load(open("ui/src-tauri/tauri.conf.json"))["version"])')"
echo "[1/4] 화면 빌드 (판 $VERSION)"
( cd ui && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npx tauri build --bundles app )
APP="ui/src-tauri/target/release/bundle/macos/Sonjari.app"
[ -d "$APP" ] || { echo "Sonjari.app 이 안 만들어졌습니다." >&2; exit 1; }

echo "[2/4] 담을 것 모으기"
STAGE="$(mktemp -d)/Sonjari"
mkdir -p "$STAGE/backend/scripts/mac"
cp -R "$APP" "$STAGE/"
# ★ 11-04: Tauri 가 만든 앱은 실행 파일에만 붙은 서명(linker-signed)뿐이라 엄격 검증에서 「리소스가 봉인되지 않음」으로 떨어졌다.
#   공증(애플 개발자 계정)은 다음 달 — 지금은 앱 전체를 애드혹으로 다시 서명한다(애플 실리콘은 서명이 아예 없으면 안 열린다).
codesign --force --deep --sign - "$STAGE/Sonjari.app"
codesign --verify --deep --strict "$STAGE/Sonjari.app" || { echo "애드혹 서명 검증 실패" >&2; exit 1; }
rsync -a --exclude '__pycache__' src "$STAGE/backend/"
# ★ 2026-11-03: 자료(recipes · skills · packs)도 담는다 — 빠지면 「스킬 0개」 · 팩 없음(check_bundle.py REQUIRED_DATA).
rsync -a --exclude 'drafts' --exclude '__pycache__' recipes skills packs "$STAGE/backend/"
# ★ 2026-11-12: 기능 카드도 담는다 — `capability_cards.py` 는 앱 바로 아래 capabilities/ 를 찾는다. 빠지면 sonjari_guide(query) 가 빈다.
rsync -a capabilities "$STAGE/backend/"
cp pyproject.toml README.ko.md "$STAGE/backend/"
cp scripts/mac/install_mac.sh "$STAGE/backend/scripts/mac/"
# 11-04: 공증 없는 베타 — 처음 한 번 여는 법(그림 셋 · 대표 맥미니 실제 순서: 열지 않음 → 설정 › 개인정보 보호 및 보안 › 그래도 열기 → 설치 끝).
mkdir -p "$STAGE/처음 한 번 여는 법"
cp scripts/mac/first_open/*.png "$STAGE/처음 한 번 여는 법/"
mkdir -p "$STAGE/backend/packaging/msix"
cp packaging/msix/check_bundle.py "$STAGE/backend/packaging/msix/"
cat > "$STAGE/손자리 설치.command" <<'CMD'
#!/bin/bash
# 두 번 누르면 손자리를 이 맥에 깝니다. 터미널 창이 뜨고 끝나면 닫아도 됩니다.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
bash "$HERE/backend/scripts/mac/install_mac.sh" "$@"
DEST="/Applications"
[ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
rm -rf "$DEST/Sonjari.app"
cp -R "$HERE/Sonjari.app" "$DEST/"
# 11-04: 맥의 cp 는 「인터넷에서 받음」 격리 표시도 같이 옮긴다 — 그대로 두면 이 설치를 허락받고도 앱을 처음 열 때 한 번 더 막힌다.
#   사람이 이 설치 파일을 직접 허락해 돌렸으니, 방금 넣은 손자리 앱 하나의 표시만 지운다(공증 전 베타 · 다른 파일은 안 건드림).
xattr -dr com.apple.quarantine "$DEST/Sonjari.app" 2>/dev/null || true
echo ""
echo "설치 끝 · Sonjari 가 열립니다. 이 창은 닫아도 됩니다."
open "$DEST/Sonjari.app" || true
CMD
chmod +x "$STAGE/손자리 설치.command"

echo "[3/4] .dmg 묶기 (hdiutil — 파인더 꾸미기 없음 · 허락 창 없음)"
mkdir -p dist
OUT="dist/Sonjari-$VERSION-mac-arm64.dmg"
rm -f "$OUT"
hdiutil create -volname "Sonjari" -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null

echo "[4/4] 끝: $OUT ($(du -h "$OUT" | cut -f1))"
echo "서명 · 공증은 하지 않았습니다(애플 개발자 계정 필요 — 대표 결정)."
