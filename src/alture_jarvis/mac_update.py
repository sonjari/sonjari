"""맥 자동 업데이트 — 서명된 목록 하나로 파이썬 묶음 · 앱 꾸러미를 같이 다룬다 (2026-11-16).

설계: `docs/설계_맥업데이트_2026-11-16.ko.md`. 여기 있는 것은 **판단**뿐이다 — 받기(네트워크) · 바꾸기(떼어 낸 sh)는
부르는 쪽(`runtime.py`) · `scripts/mac/apply_update_mac.sh` 가 한다. 판단을 한 곳에 두는 까닭은 `updater.plan` 주석과 같다:
두 곳이 판단하면 갈린다.

## 순서 (설계 §7)

    서명 확인  →  모양(schema · channel)  →  seq 되먹임  →  받을 것이 있나(build)  →  판 맞춤(앱 ↔ 파이썬)

서명 확인 앞에서는 목록 내용을 **한 글자도** 쓰지 않는다. 확인을 지난 목록만 `mac_seen.json` 에 seq 를 남긴다.

## 기존 위성 갱신(`updater.py`)과 무엇을 같이 쓰나

`unpack`(staging 밖으로 못 나감) · `staged_build`(도는 판과 같은 규칙) · `verify_download`(sha256) · `_skip`(남의 것 안 싣기)을
그대로 부른다. 같은 일을 두 벌로 짜면 한쪽만 고쳐진다.
"""

from __future__ import annotations

import hashlib
import json
import plistlib
import re
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from . import update_sign, updater

SCHEMA = 1
CHANNEL = "mac-stable"
MANIFEST_NAME = "sonjari-mac.json"
#: 배포처(대표 결정 11-16): GitHub Releases. 서명이 믿음의 근거라 배포처를 믿지 않는다(설계 §6).
GITHUB_REPO = "sonjari/sonjari"
#: 받는 쪽이 늘 묻는 자리 — **가장 최근 릴리스**의 목록. 목록 안의 묶음 · latest.json 주소는 빌드가 **그 릴리스 태그로 못 박는다**
#: (`release_asset_url`) — 「최근」이 목록과 묶음 사이에 바뀌어도 다른 릴리스의 묶음을 섞어 받지 않게.
DEFAULT_MANIFEST_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/{MANIFEST_NAME}"


def release_asset_url(tag: str, name: str) -> str:
    """태그로 못 박은 릴리스 파일 주소."""
    return f"https://github.com/{GITHUB_REPO}/releases/download/{urllib.parse.quote(tag)}/{urllib.parse.quote(name)}"


def screen_labels(decision: dict[str, Any]) -> dict[str, Any]:
    """화면 막대가 쓸 두 칸 — `mine`(지금 판) · `theirs`(받을 판) · `road`("app" | "python" | "").

    2026-11-22: 화면(UpdateBar)은 스토어 · 위성 갈래의 `mine/theirs` 만 읽었다. 맥 응답엔 그 칸이 없어 새 판이 생기면
    「undefined → undefined」 자리였다. 갈래마다 다른 칸을 화면이 뒤지지 않게 여기서 한 번 정한다.
    앱 꾸러미가 있으면 앱 판으로(사람이 아는 번호), 파이썬만 있으면 build 앞 8자로.
    """
    app = decision.get("app") if isinstance(decision.get("app"), dict) else {}
    python = decision.get("python") if isinstance(decision.get("python"), dict) else {}
    mine_app = str(decision.get("app_version") or "")
    if app.get("available"):
        return {"mine": mine_app, "theirs": str(app.get("version") or ""), "road": "app"}
    if python.get("available"):
        return {"mine": str(decision.get("mine_build") or "")[:8], "theirs": str(python.get("build") or "")[:8],
                "road": "python"}
    return {"mine": mine_app or str(decision.get("mine_build") or "")[:8], "theirs": "", "road": ""}


#: 타우리 업데이터가 맥(애플 실리콘) 꾸러미를 찾는 칸 이름.
LATEST_PLATFORM = "darwin-aarch64"


def latest_json(version: str, signature: str, url: str, *, notes: str = "", pub_date: str = "") -> dict[str, Any]:
    """타우리 업데이터가 읽는 latest.json(정적 형식) — 2026-11-22 · 설계_맥앱안업데이트 §3-2.

    ★ `signature` 는 서명된 목록(`app.signature`)과 **글자까지 같아야** 한다 — 화면 앱이 둘을 견주고(mac_update.rs
      `bound_to_manifest`), 다르면 받지 않는다. 그래서 같은 .sig 파일에서 한 번 읽은 값을 둘 다에 넣는다.
    ★ `url` 은 절대 https 주소(태그로 못 박은 릴리스 파일)여야 한다.
    """
    version, signature, url = str(version).strip(), str(signature).strip(), str(url).strip()
    if not version or not signature:
        raise ValueError("latest.json 에는 판과 서명이 있어야 합니다")
    if not url.startswith("https://"):
        raise ValueError(f"꾸러미 주소는 https 절대 주소여야 합니다: {url!r}")
    return {
        "version": version,
        "notes": notes,
        "pub_date": pub_date or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platforms": {LATEST_PLATFORM: {"signature": signature, "url": url}},
    }
#: 목록 · 서명 파일 크기 상한 — 배포처가 털려도 큰 응답으로 메모리를 못 채우게.
MAX_MANIFEST_BYTES = 1 << 20

#: 묶음 안에 박는 공개 열쇠 · 자기 seq. 둘 다 **서명된 묶음으로만** 바뀐다.
PUBKEY_FILE = Path(__file__).with_name("update_pubkey.txt")
SEQ_FILE = Path(__file__).with_name("update_seq.txt")

# ── 무엇을 싣나 — 맥 설치(`install_mac.sh` 1단계)와 같은 목록 ──────────────────────────────
#
# 윈도우 위성 목록(`updater.PAYLOAD_DIRS`)과 다르다: 맥엔 knowledge · resources 가 없고, 화면 exe 는 꾸러미 갈래가 맡는다.
# `scripts/mac/apply_update_mac.sh` 는 **받은 묶음 안의 것**을 돌려야 하므로(교체 스크립트의 버그가 스스로를 고치게 —
# runtime.update_apply 의 2026-08-24 주석) 그 하나만 싣는다.
MAC_PAYLOAD_DIRS: tuple[str, ...] = ("src", "recipes", "skills", "packs")
MAC_PAYLOAD_FILES: tuple[str, ...] = ("pyproject.toml", "README.ko.md", "scripts/mac/apply_update_mac.sh")
#: 묶음을 만들 때 저장소 것을 거르는 규칙에 더해 — install_mac.sh 의 `--exclude 'drafts'`.
_MAC_EXCLUDE_DIRS = frozenset({"drafts"})


class UpdateRefused(ValueError):
    """이 목록 · 묶음으로는 갈아치우지 않는다. 메시지는 사람이 읽는 한국어."""


# ── 박아 둔 값 ──────────────────────────────────────────────────────────────────────────


def pubkey_text(path: Path = PUBKEY_FILE) -> str:
    """박아 둔 공개 열쇠. 없거나 비었으면 빈 글 — 그러면 맥 업데이트는 꺼진다(대표 결정 전)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return "\n".join(lines).strip()


def baked_seq(path: Path = SEQ_FILE) -> int:
    """이 묶음이 만들어질 때 받은 seq. 저장소에서 바로 깐 것(install_mac.sh)은 0 — 그땐 본 seq 만으로 막는다."""
    try:
        return int(path.read_text(encoding="ascii").strip() or 0)
    except (OSError, ValueError):
        return 0


def read_seen(path: Path) -> int:
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("seq") or 0)
    except (OSError, ValueError, AttributeError):
        return 0


def write_seen(path: Path, seq: int) -> None:
    """확인을 지난 목록의 seq 만 적는다. **내려가지 않는다** — 더 작은 값이 오면 그대로 둔다."""
    if seq <= read_seen(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"seq": seq, "at": time.time()}), encoding="utf-8")
    tmp.replace(path)


def installed_app_version(app_path: str | Path) -> str:
    """화면 앱 꾸러미의 판(`CFBundleShortVersionString`). 못 읽으면 빈 글 — 「모름」은 「맞다」가 아니다."""
    plist = Path(app_path) / "Contents" / "Info.plist"
    try:
        with plist.open("rb") as handle:
            return str(plistlib.load(handle).get("CFBundleShortVersionString") or "")
    except (OSError, plistlib.InvalidFileException, ValueError):
        return ""


def _version_tuple(text: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", str(text or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def version_at_least(have: str, need: str) -> bool | None:
    """have ≥ need 인가. 둘 중 하나라도 못 읽으면 None(모름)."""
    a, b = _version_tuple(have), _version_tuple(need)
    if a is None or b is None:
        return None
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) >= b + (0,) * (width - len(b))


def resolve_url(base: str, ref: str, *, allow_http: bool = False) -> str:
    """목록 안의 주소(상대도 됨)를 목록 자리 기준으로 푼다. https 만 — 시험용 http 는 `allow_http`."""
    url = urllib.parse.urljoin(base, str(ref or "").strip())
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme == "https" or (allow_http and scheme == "http"):
        return url
    raise UpdateRefused(f"주소가 https 가 아닙니다: {url[:120]}")


# ── 목록 확인 ────────────────────────────────────────────────────────────────────────────


def verify_manifest(raw: bytes, signature_text: str, pubkey: str) -> tuple[dict[str, Any], update_sign.Verified]:
    """서명 → 모양. 서명이 맞기 전에는 JSON 을 풀지도 않는다."""
    if len(raw) > MAX_MANIFEST_BYTES:
        raise UpdateRefused("목록 파일이 너무 큽니다")
    try:
        verified = update_sign.verify(raw, signature_text, pubkey)
    except update_sign.SignatureError as exc:
        raise UpdateRefused(f"목록 서명 확인 실패: {exc}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateRefused("서명은 맞는데 목록이 JSON 이 아닙니다") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise UpdateRefused(f"모르는 목록 형식입니다(schema={manifest.get('schema') if isinstance(manifest, dict) else '?'})")
    if manifest.get("channel") != CHANNEL:
        raise UpdateRefused(f"다른 채널의 목록입니다({manifest.get('channel')!r})")
    if not isinstance(manifest.get("seq"), int) or manifest["seq"] <= 0:
        raise UpdateRefused("목록에 seq 가 없습니다")
    return manifest, verified


def evaluate(
    manifest: dict[str, Any],
    *,
    mine_build: str,
    mine_seq: int,
    seen_seq: int,
    app_version: str,
    app_enabled: bool = False,
) -> dict[str, Any]:
    """서명 확인을 지난 목록으로 판단한다. 바꾸지 않는다.

    `mine_seq` 는 지금 도는 묶음의 seq(구운 값), `seen_seq` 는 마지막으로 받아들인 목록의 seq.
    """
    seq = int(manifest["seq"])
    floor = max(int(mine_seq or 0), int(seen_seq or 0))
    if seq < floor:
        # ★ 되먹임(옛 진짜 목록 다시 주기)을 막는 자리. 같은 seq 는 「같은 목록」이라 받아들인다.
        raise UpdateRefused(f"옛 목록입니다(seq {seq} < 이미 본 {floor}) — 옛 판으로 되돌리지 않습니다")

    out: dict[str, Any] = {"seq": seq, "mine_build": mine_build, "mine_seq": mine_seq, "app_version": app_version}

    python = manifest.get("python")
    if isinstance(python, dict) and python.get("build"):
        build = str(python["build"])
        available = updater.needs_update(mine_build, build)
        part: dict[str, Any] = {
            "available": available,
            "build": build,
            "payload_id": str(python.get("payload_id") or ""),
            "sha256": str(python.get("sha256") or ""),
            "bytes": int(python.get("bytes") or 0),
            "url": str(python.get("url") or ""),
            "ready": available,
            "reason": "" if available else "이미 같은 판입니다",
        }
        if available and not part["sha256"]:
            part.update(ready=False, reason="목록에 묶음 sha256 이 없습니다 — 검증 없이 갈아치우지 않습니다")
        need_app = str(python.get("min_app_version") or "")
        if available and part["ready"] and need_app:
            ok = version_at_least(app_version, need_app)
            if ok is not True:
                part.update(
                    ready=False,
                    reason=(f"화면 앱을 먼저 업데이트해야 합니다(지금 {app_version or '모름'} · 필요 {need_app})"),
                )
        out["python"] = part
    else:
        out["python"] = {"available": False, "ready": False, "reason": "목록에 파이썬 묶음이 없습니다"}

    app = manifest.get("app")
    if isinstance(app, dict) and app.get("version"):
        version = str(app["version"])
        newer = version_at_least(version, app_version) is True and version_at_least(app_version, version) is False
        part = {
            "available": newer,
            "version": version,
            "signature": str(app.get("signature") or ""),
            "latest_json": str(app.get("latest_json") or ""),
            "ready": newer,
            "reason": "" if newer else "이미 같거나 더 새 판입니다",
        }
        if not _version_tuple(app_version):
            part["reason"] = "깔린 화면 앱의 판을 읽지 못했습니다 — 모르는 판 위에 덮어쓰지 않습니다"
        need_seq = int(app.get("min_python_seq") or 0)
        if newer and need_seq and int(mine_seq or 0) < need_seq:
            # 파이썬이 먼저 간다(설계 §5) — 지금 도는 파이썬이 이 앱이 기대하는 판보다 낮으면 앱은 기다린다.
            part.update(ready=False, reason=f"파이썬 묶음을 먼저 업데이트해야 합니다(지금 seq {mine_seq} · 필요 {need_seq})")
        if newer and (not part["signature"] or not part["latest_json"]):
            part.update(ready=False, reason="목록에 앱 서명 · latest.json 자리가 없습니다")
        if newer and not app_enabled:
            # 대표 결정(11-16): 앱 꾸러미 갈래는 Developer ID 서명 · 공증 뒤에 켠다. 그전엔 있다는 것만 알리고 안 받는다.
            part.update(ready=False, reason="앱 꾸러미 갱신은 아직 꺼져 있습니다(Developer ID 서명 · 공증 뒤에 켭니다)")
        out["app"] = part
    else:
        out["app"] = {"available": False, "ready": False, "reason": "목록에 앱 꾸러미가 없습니다"}

    out["available"] = bool(out["python"]["available"] or out["app"]["available"])
    return out


# ── 묶음 ────────────────────────────────────────────────────────────────────────────────


def payload_files(repo: Path) -> list[tuple[str, Path]]:
    """저장소(또는 맥 app/)에서 실을 것. 정렬 — 순서가 흔들리면 같은 내용인데 해시가 달라진다(updater.payload_files 와 같은 까닭)."""
    found: list[tuple[str, Path]] = []
    for name in MAC_PAYLOAD_DIRS:
        base = repo / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(repo)
            if path.is_dir() or updater._skip(rel) or any(part in _MAC_EXCLUDE_DIRS for part in rel.parts):
                continue
            # 박는 seq 는 빌드가 따로 넣는다 — 저장소에 남은 낡은 값이 실리면 seq 가 거짓말을 한다.
            if rel.as_posix() == "src/alture_jarvis/update_seq.txt":
                continue
            found.append((rel.as_posix(), path))
    for name in MAC_PAYLOAD_FILES:
        path = repo / name
        if path.is_file():
            found.append((name, path))
    return sorted(found, key=lambda item: item[0])


def write_bundle(repo: Path, dest: Path, seq: int) -> dict[str, Any]:
    """맥 파이썬 묶음 zip. 압축 시각 고정(결정론) + `update_seq.txt` 를 zip 안에만 넣는다."""
    files = payload_files(repo)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fixed = (1980, 1, 1, 0, 0, 0)
    entries = [(rel, path.read_bytes()) for rel, path in files]
    entries.append(("src/alture_jarvis/update_seq.txt", f"{seq}\n".encode("ascii")))
    entries.sort(key=lambda item: item[0])
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for rel, data in entries:
            info = zipfile.ZipInfo(rel, date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if rel.endswith(".sh") else 0o644
            info.external_attr = mode << 16
            bundle.writestr(info, data)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    return {"path": str(dest), "sha256": digest, "bytes": dest.stat().st_size, "file_count": len(entries)}


def plan(app_root: Path, staging: Path, expected_build: str, seq: int, work: Path) -> dict[str, Any]:
    """`apply_update_mac.sh` 가 읽을 지시서. 무엇을 바꿀지는 여기서 정하고 스크립트는 시키는 것만 한다."""
    return {
        "app_root": str(app_root),
        "staging": str(staging),
        "expected_build": expected_build,
        "seq": seq,
        "dirs": list(MAC_PAYLOAD_DIRS),
        "files": ["pyproject.toml", "README.ko.md"],
        "health_url": "http://127.0.0.1:8091/health",
        "launchd_label": "com.sonjari.backend",
        "result": str(work / "last_result.json"),
        "backup": str(work / "backup"),
        "health_wait_sec": 90,
        "created_at": time.time(),
    }
