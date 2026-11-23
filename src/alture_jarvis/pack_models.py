"""팩을 켤 때 그 자리에서 모델 · 실행기를 받는 장치 (2026-11-14 · 설계 §3-10).

## 왜

3D 생성 팩은 실행기(14~700MB)와 모델(약 10GB)이 있어야 일한다. 본체에 싣지 않고, 사람이 팩을 켠 **그 자리에서** 받는다.
누른 것이 동의다(Ollama 설치 단추와 같은 규칙) — 그러려면 켜기 전에 「무엇을 · 얼마나 · 어느 라이선스로 · 디스크가 되나」를 보여 줘야 한다.

## 팩이 적어 오는 것 (`pack.json` 의 `models` 칸)

    {"id": "trellis-cpp-cuda-win", "kind": "binary", "platform": "win-x64-cuda", "dir": "trellis-cpp",
     "source": {"github_release": "pwilkin/trellis.cpp", "tag": "v0.8.1", "asset": "….zip"},
     "sha256": "…", "size": 715040905, "license": "MIT", "license_url": "https://…", "unpack": true, "required": true}
    {"id": "trellis2-q8", "kind": "weights", "source": {"hf": "ilintar/trellis2-gguf", "include": ["q8/*"]}, "size": …, …}

## 받는 자리

    <data_dir>/tools/<팩id>/<dir>/     kind=binary (실행기)       — `dir` 을 안 적으면 모델 id
    <data_dir>/models/<팩id>/<dir>/    kind=weights (가중치)

## 지키는 것

- **거울 먼저**: 설정 `JARVIS_MODEL_MIRROR`(로컬에 마운트된 폴더)에 같은 이름이 있으면 거기서 복사하고 **인터넷에 안 나간다**
  (우리 집은 NAS 창고 · 손님은 인터넷). binary 는 `<거울>/<asset 이름>` 또는 풀린 `<거울>/<id>/`, weights 는 `<거울>/<id>/`.
- 받은 것을 **그냥 쓰지 않는다**: 해시(`sha256`)가 적혀 있으면 틀릴 때 지우고 멈춘다(파일 안 남김). Hugging Face 는 파일마다 LFS 해시를 대조한다.
- 이어 받기(`Range`) · 취소해도 받은 부분은 남긴다(다음에 이어 감) · 시작 전 디스크 빈 공간 확인 · 라이선스 사본(`LICENSE.txt`).
- 받는 주소는 **정해진 곳**뿐이다: `github.com/<저장소>/releases/download/…`, `huggingface.co/<저장소>/resolve/…`.
- zip 은 풀 때 밖으로 나가는 경로(zip-slip)를 거절한다. 다 받고 풀고 나서야 「준비됨」 표(`.ready.json`)를 남긴다.

## 이 기계용만 받는다 (2026-11-14 맥)

- `platform` 칸(`win-x64-cuda` · `macos-arm64-metal` 꼴 — 앞 두 마디가 운영체제 · 칩)이 **이 기계와 안 맞으면 받지 않는다.**
  상태에는 `not_for_this_machine` 으로 보이고, 「다 받았나」 · 받을 양 · 디스크 셈에서 빠진다. 가중치처럼 비어 있으면 늘 받는다.
  ★ 계기: 대표가 맥에서 받기를 누르자 윈도우 실행기 826MB 가 맥에 받아졌다(칸을 저장만 하고 거르지 않았다).
- 안 맞는 항목의 자리에 이미 무엇이 있으면 `leftovers` 로 보이고(크기 · 경로), 사람이 누를 때만 `remove_leftovers` 가 지운다.
- 배포처가 아직 없는 실행기(`source.build` — 맥 Metal 판)는 **거울**(`JARVIS_MODEL_MIRROR`)이나 **손으로 넣은 자리**
  (`<data_dir>/tools/<팩id>/<dir>/` 에 빌드한 것을 둔다)에서만 들인다. 인터넷에는 안 나간다.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import platform as _platform
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

USER_AGENT = "AltureJarvis-PackModels/1"
READY_FILE = ".ready.json"
LICENSE_FILE = "LICENSE.txt"
DOWNLOAD_DIR = ".dl"
CHUNK = 1024 * 1024
#: 디스크에 여유를 조금 더 둔다(압축 푸는 임시 공간 · 다른 일).
DISK_MARGIN = 1.05
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_KINDS = frozenset({"binary", "weights"})
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PATH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_PLATFORM = re.compile(r"^[a-z0-9]+-[a-z0-9_]+(-[a-z0-9_]+)*$")
#: 상태 이름 — 이 기계용이 아니라 받지 않는 줄.
NOT_FOR_THIS_MACHINE = "not_for_this_machine"


def this_platform(system: str | None = None, machine: str | None = None) -> tuple[str, str]:
    """(운영체제, 칩) — `platform` 칸의 앞 두 마디와 견준다. 시험은 값을 넣어 부른다."""
    system = (system or sys.platform).lower()
    os_name = "win" if system.startswith("win") else "macos" if system == "darwin" else "linux" if system.startswith("linux") else system
    arch = (machine or _platform.machine() or "").lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(arch, arch)
    return os_name, arch


def platform_fits(tag: str, here: tuple[str, str] | None = None) -> bool:
    """이 항목이 이 기계용인가. 칸이 비면(가중치 등) 어디서나 맞다. 뒤 마디(cuda · metal)는 보지 않는다 — 받을 판만 가른다."""
    tag = str(tag or "").strip().lower()
    if not tag:
        return True
    os_name, arch = here or this_platform()
    parts = tag.split("-")
    return len(parts) >= 2 and parts[0] == os_name and parts[1] == arch


class ModelError(ValueError):
    """모델 칸이 틀렸거나 받기가 못 이어질 때. 까닭이 글로 남는다."""


class _Cancelled(Exception):
    pass


# ── pack.json 의 models 칸 읽기 ────────────────────────────────────────────


def parse_models(pack_id: str, raw: Any) -> tuple[dict[str, Any], ...]:
    """`models` 칸을 검증한다. 틀리면 `ModelError` — 받을 곳이 틀린 팩은 켜게 두지 않는다."""
    if raw in (None, []):
        return ()
    if not isinstance(raw, list):
        raise ModelError(f"{pack_id}: models 는 목록이어야 한다")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    dirs: set[tuple[str, str]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ModelError(f"{pack_id}: models[{index}] 는 객체여야 한다")
        model_id = str(item.get("id") or "")
        where = f"{pack_id}: models[{model_id or index}]"
        if not _ID.fullmatch(model_id):
            raise ModelError(f"{where} — id 는 소문자·숫자·붙임표·점이어야 한다")
        if model_id in seen:
            raise ModelError(f"{where} — id 가 겹친다")
        seen.add(model_id)
        kind = str(item.get("kind") or "")
        if kind not in _KINDS:
            raise ModelError(f"{where} — kind 는 binary 또는 weights")
        folder = str(item.get("dir") or model_id)
        if not _DIR.fullmatch(folder) or folder in {".", ".."}:
            raise ModelError(f"{where} — dir 이름이 올바르지 않다")
        if (kind, folder) in dirs:
            raise ModelError(f"{where} — 같은 자리(dir)를 둘이 쓴다")
        dirs.add((kind, folder))
        source = item.get("source")
        if not isinstance(source, dict):
            raise ModelError(f"{where} — source 가 없다")
        clean_source = _parse_source(where, source)
        sha = item.get("sha256")
        if sha not in (None, ""):
            sha = str(sha).lower()
            if not _SHA.fullmatch(sha):
                raise ModelError(f"{where} — sha256 은 64자리 16진수여야 한다")
        else:
            sha = ""
        size = item.get("size", 0)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ModelError(f"{where} — size 는 0 이상의 정수(바이트)")
        license_name = str(item.get("license") or "").strip()
        if not license_name:
            raise ModelError(f"{where} — license 를 적지 않은 모델은 받지 않는다")
        license_url = str(item.get("license_url") or "").strip()
        if license_url and not license_url.startswith("https://"):
            raise ModelError(f"{where} — license_url 은 https 주소여야 한다")
        unpack = bool(item.get("unpack", False))
        if unpack and kind != "binary":
            raise ModelError(f"{where} — unpack 은 binary 에만 쓴다")
        if unpack and "asset" not in clean_source:
            raise ModelError(f"{where} — unpack 은 github_release · build 압축 파일에만 쓴다")
        if "github_file" in clean_source and not sha:
            raise ModelError(f"{where} — github_file 은 sha256 을 꼭 적는다")
        if "github_file" in clean_source and unpack:
            raise ModelError(f"{where} — github_file 은 풀지 않는다(파일 하나)")
        if "build" in clean_source and kind != "binary":
            raise ModelError(f"{where} — build(직접 빌드해 넣는 것)는 binary 에만 쓴다")
        platform_tag = str(item.get("platform") or "").strip().lower()
        if platform_tag and not _PLATFORM.fullmatch(platform_tag):
            raise ModelError(f"{where} — platform 은 「운영체제-칩[-뒤]」 꼴(예: win-x64-cuda · macos-arm64-metal)")
        out.append({
            "id": model_id, "kind": kind, "dir": folder, "platform": platform_tag,
            "source": clean_source, "sha256": sha, "size": size, "license": license_name,
            "license_url": license_url, "unpack": unpack, "required": bool(item.get("required", True)),
        })
    return tuple(out)


def _parse_source(where: str, source: dict[str, Any]) -> dict[str, Any]:
    kinds = [key for key in ("github_release", "hf", "build", "github_file") if source.get(key)]
    if len(kinds) != 1:
        raise ModelError(f"{where} — source 는 github_release · hf · build · github_file 중 하나")
    if kinds[0] == "github_file":
        # 저장소 안 파일 하나(릴리스 · 허깅페이스에 없는 작은 가중치 · 2026-11-16 taew2_2). 커밋을 못 박고(40자리) 해시가 필수다 —
        # 가지 이름(main)은 받지 않는다: 같은 주소가 날마다 다른 파일을 줄 수 있다.
        repo, commit, path = (str(source.get(k) or "") for k in ("github_file", "commit", "path"))
        if not _REPO.fullmatch(repo) or not _COMMIT.fullmatch(commit):
            raise ModelError(f"{where} — github_file 은 「저장소(소유자/이름)」와 40자리 커밋이어야 한다")
        if not path or ".." in path.split("/") or path.startswith("/") or "\\" in path or not _PATH.fullmatch(path):
            raise ModelError(f"{where} — github_file 의 path 는 저장소 안 상대 경로")
        return {"github_file": repo, "commit": commit, "path": path, "asset": Path(path).name}
    if kinds[0] == "build":
        # 배포처가 아직 없는 판(맥 Metal). 저장소 · tag 는 「어느 소스로 빌드했나」 기록이고, 받는 곳은 거울 · 손으로 넣은 자리뿐이다.
        repo, tag, asset = (str(source.get(k) or "") for k in ("build", "tag", "asset"))
        if not _REPO.fullmatch(repo) or not _TAG.fullmatch(tag) or not _ASSET.fullmatch(asset):
            raise ModelError(f"{where} — build 는 「저장소(소유자/이름)」 · tag · asset(거울에 둘 압축 이름)이 모두 올바라야 한다")
        how = str(source.get("how") or "").strip()
        return {"build": repo, "tag": tag, "asset": asset, **({"how": how} if how else {})}
    if kinds[0] == "github_release":
        repo, tag, asset = (str(source.get(k) or "") for k in ("github_release", "tag", "asset"))
        if not _REPO.fullmatch(repo) or not _TAG.fullmatch(tag) or not _ASSET.fullmatch(asset):
            raise ModelError(f"{where} — github_release 는 「저장소(소유자/이름)」 · tag · asset 이 모두 올바라야 한다")
        return {"github_release": repo, "tag": tag, "asset": asset}
    repo = str(source.get("hf") or "")
    if not _REPO.fullmatch(repo):
        raise ModelError(f"{where} — hf 는 「소유자/이름」")
    include = source.get("include") or []
    if not isinstance(include, list) or not all(isinstance(p, str) and p and ".." not in p and not p.startswith("/") for p in include):
        raise ModelError(f"{where} — include 는 상대 경로 무늬의 목록")
    revision = str(source.get("revision") or "main")
    if not _TAG.fullmatch(revision):
        raise ModelError(f"{where} — revision 이름이 올바르지 않다")
    return {"hf": repo, "include": [str(p) for p in include], "revision": revision}


def public_model(model: dict[str, Any]) -> dict[str, Any]:
    """화면에 보여 줄 만큼만(주소 · 해시는 상태에 따로 있다)."""
    return {key: model[key] for key in ("id", "kind", "platform", "size", "license", "license_url", "required")}


def _hand_built(model: dict[str, Any]) -> bool:
    return "build" in model["source"]


# ── 받기 ──────────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, status: int, headers: dict[str, str], stream: Any) -> None:
        self.status = status
        self.headers = {str(k).lower(): str(v) for k, v in headers.items()}
        self._stream = stream

    def read(self, n: int = -1) -> bytes:
        return self._stream.read(n) if self._stream is not None else b""

    def close(self) -> None:
        if self._stream is not None and hasattr(self._stream, "close"):
            self._stream.close()


def _open(url: str, headers: dict[str, str]) -> _Resp:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        response = urllib.request.urlopen(request, timeout=60)  # noqa: S310 — 주소는 호출 쪽이 정해진 곳으로만 만든다
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return _Resp(416, dict(exc.headers or {}), None)
        raise ModelError(f"http_{exc.code}: {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ModelError(f"network: {exc}") from exc
    return _Resp(getattr(response, "status", 200), dict(response.headers), response)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    if path.is_dir():
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    pass
    return total


def _raw_license_url(url: str) -> str:
    match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/blob/(.+)", url)
    return f"https://raw.githubusercontent.com/{match.group(1)}/{match.group(2)}" if match else url


def _fingerprint(model: dict[str, Any]) -> str:
    blob = json.dumps([model["source"], model["sha256"], model["unpack"]], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class ModelFetcher:
    """팩 하나가 적은 모델을 받는다. 팩마다 한 번에 하나씩, 백그라운드 스레드에서."""

    def __init__(
        self,
        packs: Any,
        data_dir: Path,
        *,
        mirror_dir: str | Path | None = None,
        opener: Callable[[str, dict[str, str]], Any] = _open,
        hf_snapshot: Any = "auto",
        free_bytes: Callable[[Path], int] | None = None,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
        platform: tuple[str, str] | None = None,
        root: str | Path | None = None,
        configured: Callable[[str, dict[str, Any]], Path | None] | None = None,
    ) -> None:
        #: (운영체제, 칩) — 비면 이 기계. 시험은 윈도우 · 맥을 넣어 본다.
        self.platform = platform or this_platform()
        self.packs = packs
        self.data_dir = Path(data_dir)
        #: 받는 자리(2026-11-16 · 「팩 파일 자리」 설정). 비면 데이터 폴더. 옛 자리(데이터 폴더)에 이미 받은 것은 그대로 쓴다.
        self.root = Path(root) if root else self.data_dir
        self.mirror_dir = Path(mirror_dir) if mirror_dir else None
        #: 사람이 설정한 자리(`.env` 의 `JARVIS_GEN3D_*_DIR` 등)에 이미 있나 — `pack_places.configured_finder`.
        #: 있으면 그 모델은 「설정한 자리에 있음」 · 받지 않는다(11-16 · 같은 10.6GB 를 또 받을 뻔했다).
        self._configured = configured
        self._open = opener
        self._hf_snapshot = hf_snapshot
        self._free = free_bytes or _free_bytes
        self.publish = publish
        self._lock = threading.Lock()
        self._runs: dict[str, dict[str, Any]] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}

    # ── 자리 ──
    def target_dir(self, pack_id: str, model: dict[str, Any]) -> Path:
        """받는 자리. 새 자리(`root`)에 없고 옛 자리(데이터 폴더)에 다 받아 둔 것이 있으면 옛 자리 — 자리를 바꿔도 다시 받지 않는다."""
        base = "tools" if model["kind"] == "binary" else "models"
        new = self.root / base / pack_id / model["dir"]
        if self.root != self.data_dir and not (new / READY_FILE).exists():
            old = self.data_dir / base / pack_id / model["dir"]
            if (old / READY_FILE).exists():
                return old
        return new

    def _download_part(self, pack_id: str, model: dict[str, Any]) -> Path:
        return self.root / "tools" / pack_id / DOWNLOAD_DIR / (model["source"].get("asset", model["id"]) + ".part")

    def _models_of(self, pack_id: str) -> tuple[dict[str, Any], ...]:
        pack = self.packs.packs.get(pack_id)
        if pack is None:
            raise ModelError(f"unknown_pack: {pack_id}")
        return tuple(getattr(pack, "models", ()) or ())

    def fits(self, model: dict[str, Any]) -> bool:
        """이 기계용인가(`platform` 칸). 안 맞으면 받지도 · 셈하지도 않는다."""
        return platform_fits(model.get("platform", ""), self.platform)

    def leftovers(self, pack_id: str) -> list[dict[str, Any]]:
        """이 기계용이 아닌 항목의 자리에 이미 무엇이 있으면(예: 맥에 받아진 윈도우 실행기) — 경로 · 크기. 지우지는 않는다."""
        found = []
        for model in self._models_of(pack_id):
            if self.fits(model):
                continue
            target = self.target_dir(pack_id, model)
            if target.exists():
                found.append({"id": model["id"], "platform": model["platform"], "path": str(target), "bytes": _tree_size(target)})
        return found

    def remove_leftovers(self, pack_id: str) -> dict[str, Any]:
        """사람이 누를 때만 — 이 기계용이 아닌 항목의 자리만 지운다(그 팩의 tools · models 아래 정해진 dir 뿐)."""
        with self._lock:
            if (self._runs.get(pack_id) or {}).get("state") == "running":
                return {**self.status(pack_id), "ok": False, "error": "busy: 받는 중에는 지우지 않는다"}
            removed = []
            for row in self.leftovers(pack_id):
                target = Path(row["path"])
                allowed = {(home / base / pack_id).resolve() for home in {self.root, self.data_dir} for base in ("tools", "models")}
                if target.resolve().parent not in allowed or target.is_symlink():
                    continue  # 정해진 자리 밖이면 손대지 않는다
                shutil.rmtree(target, ignore_errors=True)
                if not target.exists():
                    removed.append(row)
        return {**self.status(pack_id), "ok": True, "removed": removed}

    # ── 상태 ──
    def configured_at(self, pack_id: str, model: dict[str, Any]) -> Path | None:
        """설정한 자리에 이 모델이 쓸 수 있는 꼴로 있으면 그 자리. 판정이 터지면 없다고 본다(받기 쪽 · 조용히 「있음」이 되지 않게)."""
        if self._configured is None or not self.fits(model):
            return None
        try:
            found = self._configured(pack_id, model)
        except Exception:  # noqa: BLE001
            return None
        return Path(found) if found else None

    def _is_ready(self, pack_id: str, model: dict[str, Any]) -> bool:
        try:
            data = json.loads((self.target_dir(pack_id, model) / READY_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(data, dict) and data.get("fingerprint") == _fingerprint(model)

    def _received(self, pack_id: str, model: dict[str, Any]) -> int:
        target = self.target_dir(pack_id, model)
        if self._is_ready(pack_id, model):
            return max(model["size"], _tree_size(target))
        part = self._download_part(pack_id, model) if model["source"].get("asset") else None
        size = _tree_size(target)
        if part is not None and part.is_file():
            size = max(size, part.stat().st_size)
        return size

    def status(self, pack_id: str) -> dict[str, Any]:
        models = self._models_of(pack_id)
        run = dict(self._runs.get(pack_id) or {})
        items: list[dict[str, Any]] = []
        need = 0
        for model in models:
            if not self.fits(model):
                # 이 기계용이 아니다 — 받을 것도 · 셈할 것도 아니다. 자리에 남은 것은 `leftovers` 가 따로 말한다.
                items.append({
                    **public_model(model), "state": NOT_FOR_THIS_MACHINE, "received": 0,
                    "path": str(self.target_dir(pack_id, model)), "sha256_checked": False, "via_mirror": False,
                    "hand_built": _hand_built(model), "error": "",
                })
                continue
            configured = self.configured_at(pack_id, model)
            if configured is not None:
                # 사람이 설정한 자리에 있다 — 받을 것도 · 디스크 셈도 아니다. 화면은 「설정한 자리에 있음」.
                items.append({
                    **public_model(model), "state": "ready", "received": model["size"], "path": str(configured),
                    "configured": True, "sha256_checked": False, "via_mirror": False,
                    "hand_built": _hand_built(model), "error": "",
                })
                continue
            ready = self._is_ready(pack_id, model)
            received = self._received(pack_id, model)
            if ready:
                state = "ready"
            elif run.get("state") == "running" and run.get("current") == model["id"]:
                state = "downloading"
            elif run.get("failed") == model["id"]:
                state = "failed"
            elif received:
                state = "partial"
            else:
                state = "missing"
            if not ready:
                need += max(model["size"] * (2 if model["unpack"] else 1) - received, 0) if model["size"] else 0
            items.append({
                **public_model(model), "state": state, "received": received,
                "path": str(self.target_dir(pack_id, model)), "configured": False,
                "sha256_checked": bool(model["sha256"]) or model["kind"] == "weights",
                "via_mirror": self._mirror_has(model),
                "hand_built": _hand_built(model),
                **({"how": model["source"]["how"]} if model["source"].get("how") else {}),
                "error": run.get("error", "") if run.get("failed") == model["id"] else "",
            })
        free = self._free_for(self.root)
        mine = [i for i in items if i["state"] != NOT_FOR_THIS_MACHINE]
        todo = [i for i in mine if i["state"] != "ready"]
        return {
            "pack": pack_id,
            "models": items,
            "state": run.get("state", "idle"),
            "current": run.get("current", ""),
            "error": run.get("error", ""),
            "all_ready": all(i["state"] == "ready" for i in mine if i["required"]),
            #: 「켜고 받기」의 기준 — 이 기계용 · 꼭 있어야 하는 것 가운데 아직 없는 것이 있나(설정한 자리에 있으면 있는 것).
            "needs_fetch": any(i["state"] != "ready" for i in mine if i["required"]),
            #: 받는 자리(「팩 파일 자리」 설정 · 비면 데이터 폴더) — 카드 · 설정 화면이 「어디에 받나」로 보인다.
            "root": str(self.root),
            # 직접 빌드할 판은 인터넷에서 받는 양이 아니다(거울 · 손으로 넣은 자리에서만 들인다).
            "to_download_bytes": sum(max(i["size"] - i["received"], 0) for i in todo if not i["via_mirror"] and not i["hand_built"]),
            "platform": "-".join(self.platform),
            "leftovers": self.leftovers(pack_id),
            "disk_needed_bytes": need,
            "disk_free_bytes": free,
            "disk_ok": free >= need * DISK_MARGIN,
            "mirror": str(self.mirror_dir) if self.mirror_dir else "",
        }

    def _free_for(self, path: Path) -> int:
        probe = path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            return int(self._free(probe))
        except OSError:
            return 0

    # ── 시작 · 취소 ──
    def fetch(self, pack_id: str, *, wait: bool = False) -> dict[str, Any]:
        """받기를 시작한다. 이미 돌고 있으면 그대로. 디스크가 모자라면 시작하지 않는다."""
        models = self._models_of(pack_id)
        with self._lock:
            run = self._runs.get(pack_id)
            if run and run.get("state") == "running":
                return {**self.status(pack_id), "ok": True, "started": False}
            if not models:
                return {**self.status(pack_id), "ok": True, "started": False, "reason": "nothing_to_fetch"}
            snapshot = self.status(pack_id)
            if not snapshot["disk_ok"]:
                self._runs[pack_id] = {"state": "failed", "error": "not_enough_disk"}
                return {**snapshot, "ok": False, "started": False, "error": "not_enough_disk"}
            cancel = threading.Event()
            self._cancel[pack_id] = cancel
            self._runs[pack_id] = {"state": "running", "current": "", "error": ""}
            thread = threading.Thread(target=self._run, args=(pack_id, models, cancel), name=f"pack-models-{pack_id}", daemon=True)
            self._threads[pack_id] = thread
            thread.start()
        if wait:
            thread.join()
        return {**self.status(pack_id), "ok": True, "started": True}

    def cancel(self, pack_id: str) -> dict[str, Any]:
        event = self._cancel.get(pack_id)
        running = bool(self._runs.get(pack_id, {}).get("state") == "running")
        if event is not None and running:
            event.set()
        return {**self.status(pack_id), "ok": True, "cancelling": running}

    def join(self, pack_id: str, timeout: float | None = None) -> None:
        thread = self._threads.get(pack_id)
        if thread is not None:
            thread.join(timeout)

    def _set(self, pack_id: str, **fields: Any) -> None:
        self._runs.setdefault(pack_id, {}).update(fields)
        if self.publish:
            try:
                self.publish("pack_models", {"pack": pack_id, **{k: v for k, v in fields.items() if k != "error"}})
            except Exception:  # noqa: BLE001 — 알림이 실패해도 받기는 계속된다
                pass

    def _run(self, pack_id: str, models: tuple[dict[str, Any], ...], cancel: threading.Event) -> None:
        try:
            for model in models:
                if not self.fits(model) or self._is_ready(pack_id, model) or self.configured_at(pack_id, model) is not None:
                    continue  # 이 기계용이 아니면 받지 않는다(11-14 맥에 윈도우 실행기 826MB 가 받아졌다)
                self._set(pack_id, current=model["id"])
                try:
                    self._fetch_one(pack_id, model, cancel)
                except _Cancelled:
                    self._set(pack_id, state="cancelled", current="", error="")
                    return
                except (ModelError, OSError, zipfile.BadZipFile) as exc:
                    if model["required"]:
                        self._set(pack_id, state="failed", failed=model["id"], current="", error=str(exc) or exc.__class__.__name__)
                        return
            self._set(pack_id, state="done", current="", error="")
        except Exception as exc:  # noqa: BLE001 — 스레드가 조용히 죽으면 화면이 영원히 「받는 중」이다
            self._set(pack_id, state="failed", current="", error=f"unexpected: {exc.__class__.__name__}: {exc}")

    # ── 한 모델 ──
    def _fetch_one(self, pack_id: str, model: dict[str, Any], cancel: threading.Event) -> None:
        target = self.target_dir(pack_id, model)
        need = model["size"] * (2 if model["unpack"] else 1)
        if need:
            have = self._received(pack_id, model)
            if self._free_for(self.root) < max(need - have, 0) * DISK_MARGIN:
                raise ModelError("not_enough_disk")
        used_mirror = self._from_mirror(pack_id, model, target, cancel)
        if not used_mirror:
            if _hand_built(model):
                # 배포처가 없다 — 사람이 빌드해 그 자리에 넣어 두었으면 그것을 쓰고, 아니면 무엇을 하면 되는지 말하고 멈춘다.
                if not (target.is_dir() and any(p.is_file() for p in target.iterdir())):
                    raise ModelError(
                        f"no_prebuilt: {model['id']} 는 받을 곳이 아직 없다 — 빌드한 것을 {target} 에 넣거나, "
                        f"거울(JARVIS_MODEL_MIRROR)에 {model['source']['asset']} 를 두고 다시 누른다"
                        + (f" · 빌드 법: {model['source']['how']}" if model["source"].get("how") else ""))
                self._write_license(model, target, from_mirror=False)
                (target / READY_FILE).write_text(json.dumps({
                    "id": model["id"], "fingerprint": _fingerprint(model), "sha256": "", "mirror": False,
                    "by_hand": True, "at": time.time(),
                }, ensure_ascii=False), encoding="utf-8")
                return
            if "github_release" in model["source"]:
                self._from_github(pack_id, model, target, cancel)
            elif "github_file" in model["source"]:
                self._from_github_file(pack_id, model, target, cancel)
            else:
                self._from_hf(pack_id, model, target, cancel)
        self._write_license(model, target, from_mirror=used_mirror)
        target.mkdir(parents=True, exist_ok=True)
        (target / READY_FILE).write_text(json.dumps({
            "id": model["id"], "fingerprint": _fingerprint(model), "sha256": model["sha256"],
            "mirror": used_mirror, "at": time.time(),
        }, ensure_ascii=False), encoding="utf-8")

    # 거울
    def _mirror_has(self, model: dict[str, Any]) -> bool:
        return self._mirror_source(model) is not None

    def _mirror_source(self, model: dict[str, Any]) -> Path | None:
        if self.mirror_dir is None or not self.mirror_dir.is_dir():
            return None
        folder = self.mirror_dir / model["id"]
        if folder.is_dir() and any(folder.iterdir()):
            return folder
        asset = model["source"].get("asset")
        if asset and (self.mirror_dir / asset).is_file():
            return self.mirror_dir / asset
        return None

    def _from_mirror(self, pack_id: str, model: dict[str, Any], target: Path, cancel: threading.Event) -> bool:
        source = self._mirror_source(model)
        if source is None:
            return False
        staging = target.with_name(target.name + ".copying")
        shutil.rmtree(staging, ignore_errors=True)
        try:
            if source.is_dir():
                self._copy_tree(source, staging, cancel)
            else:
                # 압축 파일: 해시를 먼저 보고(적혀 있으면) 풀거나 그대로 둔다.
                if model["sha256"] and _sha256(source) != model["sha256"]:
                    raise ModelError(f"sha256_mismatch: 거울의 {source.name}")
                if model["unpack"]:
                    self._unzip(source, staging)
                else:
                    staging.mkdir(parents=True)
                    shutil.copyfile(source, staging / source.name)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self._swap_in(staging, target)
        return True

    def _copy_tree(self, source: Path, dest: Path, cancel: threading.Event) -> None:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if path.is_dir():
                (dest / relative).mkdir(parents=True, exist_ok=True)
                continue
            if cancel.is_set():
                raise _Cancelled()
            (dest / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest / relative)
        dest.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _swap_in(staging: Path, target: Path) -> None:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(target)

    # 깃허브
    def _from_github(self, pack_id: str, model: dict[str, Any], target: Path, cancel: threading.Event) -> None:
        source = model["source"]
        base = f"https://github.com/{source['github_release']}/releases/download/"
        url = f"{base}{source['tag']}/{source['asset']}"
        part = self._download_part(pack_id, model)
        part.parent.mkdir(parents=True, exist_ok=True)
        self._download_file(url, part, cancel, allowed_prefixes=("https://",))
        if model["sha256"]:
            actual = _sha256(part)
            if actual != model["sha256"]:
                part.unlink(missing_ok=True)
                raise ModelError(f"sha256_mismatch: {source['asset']} (받은 것 {actual[:12]}…) — 지웠다")
        staging = target.with_name(target.name + ".unpacking")
        shutil.rmtree(staging, ignore_errors=True)
        try:
            if model["unpack"]:
                self._unzip(part, staging)
            else:
                staging.mkdir(parents=True)
                shutil.copyfile(part, staging / source["asset"])
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self._swap_in(staging, target)
        part.unlink(missing_ok=True)

    def _from_github_file(self, pack_id: str, model: dict[str, Any], target: Path, cancel: threading.Event) -> None:
        """저장소 안 파일 하나 — 못 박은 커밋의 raw 주소만, 해시가 틀리면 지우고 멈춘다."""
        source = model["source"]
        url = f"https://raw.githubusercontent.com/{source['github_file']}/{source['commit']}/{source['path']}"
        part = self._download_part(pack_id, model)
        part.parent.mkdir(parents=True, exist_ok=True)
        self._download_file(url, part, cancel, allowed_prefixes=("https://raw.githubusercontent.com/",))
        actual = _sha256(part)
        if actual != model["sha256"]:
            part.unlink(missing_ok=True)
            raise ModelError(f"sha256_mismatch: {source['asset']} (받은 것 {actual[:12]}…) — 지웠다")
        staging = target.with_name(target.name + ".unpacking")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        shutil.copyfile(part, staging / source["asset"])
        self._swap_in(staging, target)
        part.unlink(missing_ok=True)

    @staticmethod
    def _unzip(archive: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                out = (dest / info.filename).resolve()
                if out != root and root not in out.parents:
                    raise ModelError(f"unsafe_zip_path: {info.filename}")
            zf.extractall(dest)
            # 파이썬 zip 풀기는 유닉스 권한을 버린다 → 맥에서 받은 실행기가 「권한 없음」으로 안 돈다(11-14 릴리스 전 검토에서 찾음).
            # zip 에 적힌 권한(external_attr 의 위 16비트)을 되살린다. 윈도우는 실행 권한이 없어 영향 없다.
            for info in zf.infolist():
                mode = (info.external_attr >> 16) & 0o777
                if mode and not info.is_dir():
                    try:
                        os.chmod(dest / info.filename, mode)
                    except OSError:
                        pass

    # 허깅페이스
    def _from_hf(self, pack_id: str, model: dict[str, Any], target: Path, cancel: threading.Event) -> None:
        source = model["source"]
        snapshot = self._hf_snapshot
        if snapshot == "auto":
            try:
                from huggingface_hub import snapshot_download as snapshot  # type: ignore[import-not-found]
            except ImportError:
                snapshot = None
        if snapshot and _hf_temp_too_long(target):
            # ★ 2026-11-23 현업 사용자 PC(스토어판): 영상 팩 wan5b 가 `hf_hub: FileNotFoundError` 로 멈췄다. 허깅페이스 라이브러리의
            #   받는 중 파일(`<폴더>\.cache\huggingface\download\<28자>.<64자>.incomplete`)이 255자 언저리면 긴 경로 표시(\\?\)를
            #   안 붙이는데(라이브러리는 255 초과일 때만 붙임) 윈도우가 막는다 — 이 PC 에서 255자 실패 · 257자 성공으로 재현.
            #   스토어판 데이터 폴더(…\Packages\<패키지>\LocalCache\Local\Sonjari\data)가 길어 거기 걸렸다. 우리가 \\?\ 를 붙이면
            #   라이브러리가 한 번 더 붙여 깨진다(WinError 123) → 이 자리면 라이브러리를 쓰지 않고 아래 직접 받기(<파일>.part · 짧다)로.
            snapshot = None
        if snapshot:
            target.mkdir(parents=True, exist_ok=True)
            try:
                snapshot(repo_id=source["hf"], revision=source["revision"], local_dir=str(target),
                         allow_patterns=source["include"] or None)
            except Exception as exc:  # noqa: BLE001 — 허브 라이브러리의 갖가지 오류를 한 말로
                raise ModelError(f"hf_hub: {exc.__class__.__name__}: {exc}") from exc
            if cancel.is_set():
                raise _Cancelled()
            return
        repo, revision = source["hf"], source["revision"]
        listing = self._open(f"https://huggingface.co/api/models/{repo}/tree/{revision}?recursive=true", {})
        try:
            rows = json.loads(listing.read().decode("utf-8"))
        finally:
            listing.close()
        files = [r for r in rows if isinstance(r, dict) and r.get("type") == "file"
                 and (not source["include"] or any(fnmatch.fnmatch(str(r.get("path")), pat) for pat in source["include"]))]
        if not files:
            raise ModelError("hf_empty: include 에 맞는 파일이 없다")
        root = target.resolve()
        for row in files:
            relative = str(row["path"])
            out = (target / relative).resolve()
            if root not in out.parents:
                raise ModelError(f"unsafe_path: {relative}")
            expected = str(((row.get("lfs") or {}).get("oid")) or "").lower()
            if out.is_file() and (not expected or _sha256(out) == expected):
                continue  # 이미 받은 파일
            part = out.with_name(out.name + ".part")
            part.parent.mkdir(parents=True, exist_ok=True)
            self._download_file(f"https://huggingface.co/{repo}/resolve/{revision}/{relative}", part, cancel,
                                allowed_prefixes=("https://",))
            if expected and _sha256(part) != expected:
                part.unlink(missing_ok=True)
                raise ModelError(f"sha256_mismatch: {relative} — 지웠다")
            part.replace(out)

    # 한 파일 이어 받기
    def _download_file(self, url: str, part: Path, cancel: threading.Event, *, allowed_prefixes: tuple[str, ...]) -> None:
        if not url.startswith(allowed_prefixes):
            raise ModelError(f"blocked_url: {url}")
        start = part.stat().st_size if part.is_file() else 0
        headers = {"Range": f"bytes={start}-"} if start else {}
        response = self._open(url, headers)
        try:
            if response.status == 416:
                return  # 이미 다 받았다 — 해시가 맞는지는 부른 쪽이 본다
            if start and response.status != 206:
                start = 0  # 서버가 이어 받기를 안 받는다 — 처음부터
            length = int(response.headers.get("content-length") or 0)
            expected_total = start + length if length else 0
            with part.open("ab" if start else "wb") as handle:
                received = start
                while True:
                    if cancel.is_set():
                        raise _Cancelled()
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
            if expected_total and received != expected_total:
                raise ModelError(f"incomplete: {received}/{expected_total} 바이트에서 끊겼다 — 다시 누르면 이어 받는다")
        finally:
            response.close()

    # 라이선스
    def _write_license(self, model: dict[str, Any], target: Path, *, from_mirror: bool) -> None:
        target.mkdir(parents=True, exist_ok=True)
        text = ""
        if from_mirror and self.mirror_dir is not None:
            for candidate in (self.mirror_dir / f"{model['id']}.LICENSE.txt", self.mirror_dir / model["id"] / LICENSE_FILE):
                if candidate.is_file():
                    text = candidate.read_text(encoding="utf-8", errors="replace")
                    break
        elif model["license_url"]:
            try:
                response = self._open(_raw_license_url(model["license_url"]), {})
                try:
                    text = response.read().decode("utf-8", "replace")
                finally:
                    response.close()
            except (ModelError, OSError):
                text = ""
        if not text.strip():
            text = (f"{model['id']} — 라이선스: {model['license']}\n원문 주소: {model['license_url'] or '(없음)'}\n"
                    "(원문을 이 자리에서 받지 못해 이름과 주소만 적는다.)\n")
        (target / LICENSE_FILE).write_text(text, encoding="utf-8")


#: 허깅페이스 라이브러리가 받는 폴더 아래에 붙이는 받는 중 파일 몫:
#: `\.cache\huggingface\download\` (29) + 줄인 이름 28 + `.` + 지문 64 + `.incomplete` (11) = 133자.
HF_TEMP_TAIL = 133
#: 이 길이를 넘으면 라이브러리를 쓰지 않는다. 255 실패 · 257 성공(긴 경로 표시)이 재현돼 경계가 애매하다 — 넉넉히 240.
HF_TEMP_LIMIT = 240


def _hf_temp_too_long(target: Path, *, windows: bool | None = None) -> bool:
    if not (os.name == "nt" if windows is None else windows):
        return False  # 맥 · 리눅스는 경로 한도가 길다
    return len(os.path.abspath(str(target))) + HF_TEMP_TAIL >= HF_TEMP_LIMIT


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


__all__ = ["ModelError", "ModelFetcher", "parse_models", "public_model"]
