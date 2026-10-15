"""구운 패키지 안에 사람 이름·신상·내부 주소가 실리지 않았는지 본다 (2026-10-07).

    python packaging/msix/scan_package_people.py <펼친 패키지 폴더>

왜 있나. 깃허브 공개본은 뽑을 때 이름을 바꾸고 남은 것을 검사한다(`scripts/export_public.py`). 그런데 스토어 패키지는
`src/alture_jarvis` · `recipes` · `skills` · `packs` 를 저장소에서 **그대로 복사**한다 — 그 치환도 검사도 거치지 않는다.
그래서 소스 주석에 적힌 이름과 신상이 패키지에 실려 나갔다. 공개본과 **같은 목록**으로 패키지도 본다.

목록(`FORBIDDEN`)은 `scripts/export_public.py` 에만 있다 — 막을 낱말이 곧 지킬 정보라 공개본에는 싣지 않는다.
그 파일이 없는 곳(공개본을 받아 직접 굽는 사람)에서는 볼 목록이 없으니 건너뛴다.

걸리면 종료 코드 1 — 그 패키지는 올리지 않는다. 소스에서 고친다(패키지를 고치지 않는다).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPORTER = HERE.parents[1] / "scripts" / "export_public.py"

#: 패키지 안에서 **우리가 쓴 것**이 들어가는 폴더 이름. 남이 만든 라이브러리(site-packages 의 나머지)는 보지 않는다.
OUR_FOLDERS = ("alture_jarvis", "recipes", "skills", "packs")
_BINARY = {".pyc", ".pyd", ".dll", ".exe", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".gz", ".zip", ".onnx", ".bin", ".woff", ".woff2"}


def forbidden_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """공개본 가드와 같은 목록. 그 파일이 없으면 빈 목록."""
    if not EXPORTER.is_file():
        return []
    spec = importlib.util.spec_from_file_location("export_public", EXPORTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return list(module.FORBIDDEN)


def our_folders(app: Path) -> list[Path]:
    """펼친 패키지에서 우리 폴더들. 깊이가 판마다 달라서 이름으로 찾는다(가장 얕은 것 하나씩)."""
    found: list[Path] = []
    for name in OUR_FOLDERS:
        hits = sorted((p for p in app.rglob(name) if p.is_dir()), key=lambda p: len(p.parts))
        # `skills` 안의 `skills`(팩 안쪽)처럼 이미 잡은 폴더의 아래는 다시 세지 않는다.
        for hit in hits:
            if not any(parent in hit.parents for parent in found) and hit not in found:
                found.append(hit)
                break
    return found


def scan(app: Path, patterns: list[tuple[str, re.Pattern[str]]] | None = None) -> list[str]:
    """`경로:줄: 종류` 목록. 빈 목록이어야 올릴 수 있다."""
    patterns = forbidden_patterns() if patterns is None else patterns
    hits: list[str] = []
    if not patterns:
        return hits
    for folder in our_folders(app):
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix.lower() in _BINARY:
                continue
            data = path.read_bytes()
            if b"\0" in data[:8192]:
                continue
            text = data.decode("utf-8", errors="ignore")
            for label, pattern in patterns:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    hits.append(f"{path.relative_to(app).as_posix()}:{line}: {label}")
    return hits


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: scan_package_people.py <unpacked package folder>")
        return 2
    app = Path(args[0])
    if not app.is_dir():
        print(f"not a folder: {app}")
        return 2
    patterns = forbidden_patterns()
    if not patterns:
        print("people check: skipped (no list here - scripts/export_public.py is monorepo-only)")
        return 0
    folders = our_folders(app)
    if not folders:
        print("people check: FAILED - none of our folders were found in the package (nothing was checked)")
        return 1
    hits = scan(app, patterns)
    if hits:
        print(f"people check: FAILED - {len(hits)} hit(s). Fix the source, not the package:")
        for hit in hits[:100]:
            print("  " + hit)
        return 1
    print(f"people check: clean ({len(folders)} folders)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
