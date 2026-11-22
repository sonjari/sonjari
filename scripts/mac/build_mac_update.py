"""맥 업데이트 묶음 · 목록 만들기 (2026-11-16 · docs/설계_맥업데이트_2026-11-16.ko.md §2 ①~④).

    python scripts/mac/build_mac_update.py --out dist/mac-update                     # 묶음 + 목록(서명 안 함)
    python scripts/mac/build_mac_update.py --out dist/mac-update --sign              # + 목록 서명(열쇠는 환경 변수)
    python scripts/mac/build_mac_update.py --out … --app-version 0.4.1 --app-sig Sonjari.app.tar.gz.sig --sign

★ 비밀 열쇠는 이 스크립트가 **읽지 않는다.** `--sign` 이면 `tauri signer sign` 을 부르고, 열쇠는 그 도구가
  `TAURI_SIGNING_PRIVATE_KEY_PATH` · `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` 에서 읽는다(타우리 빌드와 같은 자리 · 같은 열쇠).
★ 올리기는 하지 않는다 — 만든 파일을 사람이 GitHub Releases(sonjari/sonjari)에 올린다. 목록 · .sig · 묶음 · latest.json · 꾸러미를
  **한 릴리스에** 같이 올리고, 태그를 `--release-tag` 로 준다(설계 §3).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))

from alture_jarvis import mac_update  # noqa: E402


def source_build(repo: Path) -> str:
    """`updater.staged_build` 와 같은 규칙 — 규칙이 갈리면 받는 쪽이 늘 「판이 다르다」로 거절한다.

    2026-11-23: 규칙을 베끼지 않고 `config.code_digest` 하나를 부른다(줄 끝 무시).
    """
    from alture_jarvis.config import code_digest

    return code_digest(repo / "src" / "alture_jarvis")


def build(args: argparse.Namespace) -> dict:
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    seq = int(args.seq or time.strftime("%Y%m%d%H%M", time.gmtime()))
    build_id = source_build(REPO)
    bundle = mac_update.write_bundle(REPO, out / f"python-{build_id}.zip", seq)
    manifest: dict = {
        "schema": mac_update.SCHEMA,
        "channel": mac_update.CHANNEL,
        "seq": seq,
        "issued_at": int(time.time()),
        "python": {
            "build": build_id,
            "payload_id": bundle["sha256"][:12],
            # 태그를 주면 그 릴리스로 못 박는다(받는 쪽이 「최근」이 바뀌는 사이에 다른 릴리스 묶음을 섞지 않게). 없으면 목록 옆 상대 주소.
            "url": mac_update.release_asset_url(args.release_tag, Path(bundle["path"]).name) if args.release_tag
            else Path(bundle["path"]).name,
            "sha256": bundle["sha256"],
            "bytes": bundle["bytes"],
            "min_app_version": args.min_app_version,
        },
    }
    if args.app_version:
        if not args.app_sig:
            raise SystemExit("--app-version 에는 --app-sig(타우리 빌드가 만든 .sig 파일)가 같이 있어야 합니다")
        if not (args.app_tarball and args.release_tag):
            # 11-22: 타우리 업데이터는 latest.json 의 꾸러미 주소가 절대 주소여야 받는다 — 태그로 못 박은 주소만 쓴다.
            raise SystemExit("--app-version 에는 --app-tarball(앱 꾸러미 .app.tar.gz)과 --release-tag 가 같이 있어야 합니다")
        min_python_seq = int(args.min_python_seq or 0)
        if min_python_seq > seq:
            # 앱이 이 목록의 파이썬보다 새 파이썬을 요구하면 받는 쪽은 영영 못 받는다(설계 §5 순서 규칙).
            raise SystemExit(f"앱이 요구하는 파이썬 seq({min_python_seq})가 이 목록의 seq({seq})보다 큽니다 — 순서가 꼬입니다")
        manifest["app"] = {
            "version": args.app_version,
            "latest_json": mac_update.release_asset_url(args.release_tag, "latest.json") if args.release_tag else "latest.json",
            # latest.json 의 signature 와 **글자까지 같아야** 한다 — 화면 앱이 그 둘을 견준다(mac_update.rs).
            "signature": Path(args.app_sig).read_text(encoding="utf-8").strip(),
            "min_python_seq": min_python_seq,
        }
        # 11-22: 타우리가 받는 latest.json — 판 · 서명(목록과 같은 파일에서 · 두 벌 없음) · 꾸러미 주소(태그로 못 박음).
        latest = mac_update.latest_json(
            args.app_version,
            manifest["app"]["signature"],
            mac_update.release_asset_url(args.release_tag, Path(args.app_tarball).name),
        )
        (out / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    path = out / mac_update.MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    result = {"manifest": str(path), "bundle": bundle, "seq": seq, "build": build_id, "signed": False}
    if args.sign:
        tauri = shutil.which("tauri") or str(REPO / "ui" / "node_modules" / ".bin" / ("tauri.cmd" if sys.platform == "win32" else "tauri"))
        # 11-22: 한글 윈도우에서 text=True 만 쓰면 cp949 로 읽다가 읽기 스레드가 UnicodeDecodeError 로 죽었다(서명은 됨) — utf-8 로.
        done = subprocess.run([tauri, "signer", "sign", str(path)], capture_output=True, text=True,  # noqa: S603
                              encoding="utf-8", errors="replace")
        if done.returncode != 0 or not path.with_name(path.name + ".sig").is_file():
            raise SystemExit(f"서명하지 못했습니다(열쇠 환경 변수를 확인하세요): {done.stderr.strip()[:300]}")
        # 만든 서명을 우리 확인기로 바로 다시 본다 — 박아 둔 공개 열쇠와 다른 열쇠로 서명했으면 여기서 멈춘다.
        from alture_jarvis import update_sign

        update_sign.verify(path.read_bytes(), path.with_name(path.name + ".sig").read_text(encoding="utf-8"),
                           mac_update.pubkey_text())
        result["signed"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="맥 업데이트 묶음 · 목록 만들기")
    parser.add_argument("--out", required=True)
    parser.add_argument("--seq", default="")
    parser.add_argument("--min-app-version", default="0.4.0")
    parser.add_argument("--app-version", default="")
    parser.add_argument("--app-sig", default="")
    parser.add_argument("--app-tarball", default="", help="앱 꾸러미 Sonjari-<판>-mac-arm64.app.tar.gz (릴리스에 같이 올릴 이름)")
    parser.add_argument("--min-python-seq", default="")
    parser.add_argument("--release-tag", default="", help="올릴 GitHub 릴리스 태그(예: mac-202611161530) — 묶음 주소를 그 태그로 못 박는다")
    parser.add_argument("--sign", action="store_true")
    result = build(parser.parse_args(argv))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
