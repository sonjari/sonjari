"""위성 자비스를 **본체에서 갱신한다** (2026-08-24).

## 왜 통짜인가

타우리에 업데이터가 있고 그걸 붙이면 exe 는 알아서 갱신된다. 그런데 그날
바뀐 양을 세어 보면 이렇다:

    파이썬(백엔드)   2,059줄
    화면(UI)         1,057줄

exe 만 갱신하면 다른 사용자 노트북은 **새 창을 받고도 어제처럼 행동한다.** 그게
제일 나쁜 결말이다 — 겉이 바뀌었으니 갱신된 줄 안다. 그래서 갱신 경로를
하나로 둔다. 둘로 나누면 「exe 만 새것」 같은 어긋남이 반드시 생긴다.

## 무엇을 근거로 「받을 게 있다」고 하나

`config.build_id()` — 패키지 모든 `.py` 의 **내용 해시**다. mtime 이 아니라
내용이라 복사만으로는 안 바뀌고, git sha 가 아니라 실제로 도는 코드를 가리킨다
(C: 런타임은 git 저장소가 아니고, 커밋 안 한 수정으로 도는 일이 잦다).

이미 있는 값인데 밖에서 볼 수가 없었다. `/health` 에 얹었다.

## 위협 모델 — 왜 minisign 을 안 쓰나

본체와 위성은 **같은 테일넷**이고, 위성은 이미 본체의 control token 을 쥐고
있다. 그 토큰이면 위성에서 본체 도구를 부를 수 있다. 즉 **본체가 털리면
위성은 이미 끝난 것**이고, 서명은 그 위에 아무것도 안 얹는다.

그래서 여기서 지키는 것은 둘이다:

    토큰      모르는 놈이 못 받아 간다 (그리고 못 보낸다)
    sha256    받는 중에 깨진 것을 못 쓴다

배포처가 테일넷 밖으로 나가면(예: 인터넷 호스팅) **그때는 서명이 필요하다.**
그 경계를 넘을 때 이 주석을 다시 읽어라.

## 되돌리기

`되돌림은 성공을 확인한다` — 이 저장소가 엿새짜리 침묵으로 배운 것이다.
갱신 뒤 `/health` 의 `build` 가 **기대한 값인지** 확인하고, 아니면 되돌린다.
「배포했다」는 말도, 200 응답도 증거가 아니다(안 죽은 옛 프로세스가 답할 수 있다).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

from .config import build_id

# ── 무엇을 보내나 ────────────────────────────────────────────────────────────
#
# 설치된 런타임 디렉터리에서 뜬다. **저장소가 아니다** — 저장소의 `ui/`
# 에는 node_modules 와 rust target 이 있어 기가 단위다. 런타임에는 구워진 exe
# 하나만 있다.
PAYLOAD_DIRS: tuple[str, ...] = (
    "src", "recipes", "skills", "knowledge", "resources", "scripts"
)
PAYLOAD_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-hardware.txt",
    "requirements-stt-cuda.txt",
)
HUD_EXE = "ui/alture-jarvis-hud.exe"

# ★ 이 목록이 낡으면 **남의 것이 실려 간다.** data/ 가 실리면 다른 사용자 노트북의
#   대화가 본체 것으로 덮인다. .env 가 실리면 본체 토큰·키가 통째로 간다.
#   그래서 「보낼 것」은 위에 적고, 「절대 안 보낼 것」을 여기 또 적는다.
EXCLUDE_NAMES = frozenset({
    "__pycache__", ".venv", "venv", "data", "outputs", "node_modules",
    "target", ".git", ".pytest_cache", ".mypy_cache", "browser-profile",
})
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".db", ".db-wal", ".db-shm")


def _skip(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES:
        return True
    if any(part in EXCLUDE_NAMES for part in path.parts):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    # `alture-jarvis-hud.exe.bak-20260819` 류. 런타임 ui/ 에 9개가 쌓여 있었다.
    return ".bak-" in path.name or path.name.endswith(".bak")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_files(root: Path) -> list[tuple[str, Path]]:
    """보낼 파일 목록. `(relpath, 실제경로)` 를 **정렬해서** 준다.

    정렬이 중요하다 — 순서가 흔들리면 같은 내용인데 zip 해시가 달라지고,
    「받을 게 있다」가 매번 참이 된다.
    """
    found: list[tuple[str, Path]] = []
    for name in PAYLOAD_DIRS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_dir() or _skip(path):
                continue
            found.append((path.relative_to(root).as_posix(), path))
    for name in PAYLOAD_FILES:
        path = root / name
        if path.is_file():
            found.append((name, path))
    hud = root / HUD_EXE
    if hud.is_file():
        found.append((HUD_EXE, hud))
    return sorted(found, key=lambda item: item[0])


def payload_id(root: Path) -> str:
    """**실려 가는 것 전체**의 지문 (2026-08-24).

    `build_id()` 는 `src/alture_jarvis/*.py` 만 센다. 그것이 옳은 자리도 있다 —
    실적을 남길 때 "어느 코드가 이 일을 했나"를 가리키는 값이라, 화면이나
    스크립트가 바뀌었다고 실적 표가 갈리면 안 된다.

    그런데 **받을 게 있나**를 그 값으로 물으면 구멍이 난다. 실측(2026-08-24):
    `apply_update.ps1` 의 치명적인 버그를 고쳤는데 `build` 가 그대로라, 위성은
    「이미 같은 판입니다」라고 답했다. 고친 것이 위성에 **영원히 안 닿는다.**
    화면(exe)만 바꾼 날도 같은 일이 일어났을 것이다.

    그래서 「받을 게 있나」는 이 값으로 묻는다 — 보낼 목록 그대로, 이름과 내용을
    함께 센다. 이름을 같이 세는 이유는 파일이 옮겨지거나 이름만 바뀐 것도
    바뀐 것이기 때문이다.
    """
    digest = hashlib.sha256()
    for rel, path in payload_files(root):
        digest.update(rel.encode("utf-8"))
        digest.update(_sha256(path).encode("ascii"))
    return digest.hexdigest()[:12]


def manifest(root: Path) -> dict[str, Any]:
    """본체가 「나는 이 판이다」라고 말하는 표.

    `build` 는 위성이 자기 것과 견주는 값이고, `payload_sha256` 은 받은 것이
    깨졌는지 보는 값이다. 둘은 하는 일이 다르므로 둘 다 있어야 한다.
    """
    files = payload_files(root)
    total = sum(path.stat().st_size for _rel, path in files)
    hud = root / HUD_EXE
    return {
        "build": build_id(),
        # ★ 「받을 게 있나」는 이걸로 묻는다. `build` 로 물으면 .ps1·화면 수정이
        #   통째로 안 보인다 — payload_id 의 주석 참고.
        "payload_id": payload_id(root),
        "file_count": len(files),
        "total_bytes": total,
        "hud_present": hud.is_file(),
        "hud_sha256": _sha256(hud) if hud.is_file() else "",
        "hud_bytes": hud.stat().st_size if hud.is_file() else 0,
        "created_at": time.time(),
    }


def write_payload(root: Path, dest: Path) -> dict[str, Any]:
    """보낼 것을 zip 하나로. 돌려주는 값에 sha256 이 들어 있다.

    ★ 압축 시각을 고정한다. 안 그러면 같은 내용인데 zip 해시가 매번 달라져서
      위성이 「받을 게 있다」를 영원히 참으로 본다. 오늘 `build_id` 가 mtime 이
      아니라 내용을 해시하는 것과 같은 이유다.
    """
    files = payload_files(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fixed = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for rel, path in files:
            info = zipfile.ZipInfo(rel, date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes())
    return {
        "path": str(dest),
        "sha256": _sha256(dest),
        "bytes": dest.stat().st_size,
        "file_count": len(files),
    }


def needs_update(mine: str, theirs: str) -> bool:
    """받을 게 있는가.

    **모르면 안 받는다.** 빈 값이 「같다」와 「모른다」 둘 다를 뜻하면 조용히
    고장 난다 — 이 저장소가 이미 겪은 모양이라, 여기서는 둘을 가른다.
    """
    if not mine or not theirs:
        return False
    return mine != theirs


def verify_download(path: Path, expected_sha256: str) -> tuple[bool, str]:
    """받은 것이 온전한가. 아니면 **왜 아닌지**를 같이 준다."""
    if not path.is_file():
        return False, "받은 파일이 없습니다"
    if not expected_sha256:
        return False, "본체가 해시를 안 줬습니다 — 검증 없이 갈아치우지 않습니다"
    actual = _sha256(path)
    if actual != expected_sha256:
        return False, f"해시가 다릅니다(받은 것 {actual[:12]} ≠ 기대 {expected_sha256[:12]})"
    return True, ""


def unpack(archive: Path, staging: Path) -> dict[str, Any]:
    """받은 zip 을 **staging 안에만** 푼다.

    zip 안의 경로가 `..` 로 밖을 가리키면 거기서 멈춘다. 본체를 믿더라도
    푸는 코드는 믿지 않는다 — 값이 싼 방어다.
    """
    staging.mkdir(parents=True, exist_ok=True)
    root = staging.resolve()
    written = 0
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            target = (root / name).resolve()
            if not str(target).startswith(str(root)):
                raise ValueError(f"zip 이 staging 밖을 가리킵니다: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(name))
            written += 1
    return {"staging": str(root), "file_count": written}


def staged_build(staging: Path) -> str:
    """푼 것의 판 지문. **갈아치우기 전에** 본체가 말한 값과 맞는지 본다.

    `config.build_id` 와 같은 규칙으로 센다 — 규칙이 갈리면 늘 「다르다」가 되고,
    그러면 되돌리기가 매번 돈다.
    """
    package = staging / "src" / "alture_jarvis"
    if not package.is_dir():
        return ""
    digest = hashlib.sha256()
    for path in sorted(package.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def plan(root: Path, staging: Path, expected_build: str) -> dict[str, Any]:
    """갈아치우는 스크립트가 읽을 지시서.

    파이썬이 자기 파일을 자기가 못 바꾼다(도는 중이다). 그래서 **떼어 낸**
    PowerShell 이 프로세스를 내리고 바꾼 뒤 다시 올린다. 무엇을 바꿀지는
    여기서 정해 두고, 스크립트는 시키는 것만 한다 — 두 곳이 판단하면 갈린다.
    """
    return {
        "root": str(root),
        "staging": str(staging),
        "expected_build": expected_build,
        "dirs": list(PAYLOAD_DIRS),
        "files": list(PAYLOAD_FILES),
        "hud": HUD_EXE,
        "health_url": "http://127.0.0.1:8091/health",
        "created_at": time.time(),
    }


def write_plan(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def runtime_root() -> Path:
    """지금 도는 설치본의 뿌리. `src/alture_jarvis/updater.py` 에서 두 칸 위다."""
    return Path(__file__).resolve().parents[2]
