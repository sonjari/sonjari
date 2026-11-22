"""블렌더 받기 · 깔기 — 사람이 동의한 뒤에만, blender.org 공식 자리에서, 지문을 맞춰 보고 (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우` §5-1 · G3).

왜: 3D 마무리 · 렌더 · 애니 블렌더 도구는 블렌더가 없으면 「깔아 주세요」에서 멈춘다. 블렌더를 처음 듣는 사람은 깔아 줘야 쓴다(11-15 대표).
블렌더 실행 파일은 우리 꾸러미에 넣지 않는다(설계 N3 · GPL 실행 파일을 우리가 퍼뜨리지 않는다) — 사람이 동의하면 공식 자리에서 받는다.

- 판: **4.5 LTS 의 가장 새 고침 판**(11-18 기준 4.5.16 · 윈도우 zip 398MB · 맥 dmg 312MB). 우리 블렌더 스크립트가 맥 4.5.9 · PC 5.2.3 에서 돌았다(4.5.16 자체는 아직 안 돌려 봄) — 4.5 는 오래 지원하는 판. 목록을 글자 순서로 보면 4.5.9 가 마지막처럼 보인다(11-18 내가 그렇게 잘못 읽음) — 숫자로 비교한다.
- 지문: 같은 폴더의 `blender-<판>.sha256`(공식 서버가 함께 올림)과 받은 파일을 맞춘다. 같은 서버의 지문이라 전송 중 깨짐 · 덜 받음은 잡지만
  서버 자체가 바뀐 경우까지는 못 막는다(HTTPS 에 기댐) — 안내문에 그대로 적는다.
- 윈도우: 휴대판 zip → `%LOCALAPPDATA%\\Sonjari\\blender\\blender-<판>-windows-x64\\` 에 푼다(관리자 권한 필요 없음 · 찾기가 보는 자리).
- 맥: dmg 를 받아 지문을 맞추고 연다. **응용 프로그램 폴더로 끌어 넣기는 사람이 한다**(대신 끌지 않는다 · 설계 §5-1).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

SERIES = "4.5"
BASE = f"https://download.blender.org/release/Blender{SERIES}/"
#: 풀었을 때 크기 어림(윈도우 4.5 휴대판 zip 약 0.4GB → 풀면 약 1.1GB · 받는 zip 은 끝나면 지운다) — 여유 확인용 넉넉히.
NEED_FREE_GB = 2.0

NOTICE = (
    "블렌더는 손자리에 들어 있지 않습니다. 받기에 동의하면 blender.org 공식 자리(download.blender.org)에서 "
    f"블렌더 {SERIES} LTS(오래 지원하는 판) 최신을 이 PC 로 한 번 내려받습니다(윈도우 약 0.4GB → 풀면 약 1.1GB · 맥 약 0.3GB).\n"
    "- 블렌더는 GNU GPL 자유 소프트웨어입니다(blender.org). 손자리는 블렌더를 창 없이 따로 실행만 하고 파일로만 주고받습니다.\n"
    "- 받은 파일은 같은 서버가 올린 sha256 지문과 맞을 때만 씁니다(전송 중 깨짐은 잡지만, 서버 자체가 바뀐 경우까지는 막지 못합니다).\n"
    "- 윈도우: 손자리 자리(내 계정 AppData\\Local\\Sonjari\\blender)에 풉니다 · 관리자 권한이 필요 없습니다.\n"
    "- 맥: 받은 dmg 를 열어 드립니다. 블렌더 아이콘을 응용 프로그램(Applications) 폴더로 끌어 넣는 것은 직접 해 주세요."
)

_LOCK = threading.Lock()
_JOB: dict[str, Any] = {}


def _get(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Sonjari"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 고정된 https 공식 자리만
        return resp.read()


def latest(fetch: Callable[[str], bytes] = _get) -> str:
    """4.5 폴더 목록에서 가장 큰 고침 판(숫자 비교 · 11-18 기준 4.5.16)."""
    text = fetch(BASE).decode("utf-8", "replace")
    found = [int(m) for m in re.findall(rf"blender-{re.escape(SERIES)}\.(\d+)-", text)]
    if not found:
        raise RuntimeError(f"blender.org 목록에서 {SERIES} 판을 못 찾았다")
    return f"{SERIES}.{max(found)}"


def file_name(version: str, platform: str | None = None) -> str:
    platform = platform or sys.platform
    if platform == "darwin":
        return f"blender-{version}-macos-arm64.dmg"
    if platform == "win32":
        return f"blender-{version}-windows-x64.zip"
    raise RuntimeError("이 운영체제는 손자리가 블렌더를 받아 깔지 않는다 — 배포판 꾸러미로 깔고 JARVIS_BLENDER 에 경로를 넣어 달라")


def expected_sha(version: str, name: str, fetch: Callable[[str], bytes] = _get) -> str:
    text = fetch(f"{BASE}blender-{version}.sha256").decode("utf-8", "replace")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == name and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            return parts[0]
    raise RuntimeError(f"지문 파일에 {name} 줄이 없다")


def install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Sonjari" / "blender"


def download_dir() -> Path:
    return Path.home() / "Downloads"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def status(find: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    from .find import find as find_any

    found = (find or (lambda: find_any(None)))()
    with _LOCK:
        job = dict(_JOB)
    return {"found": bool(found.get("found")), "exe": found.get("exe"), "version": found.get("version"),
            "downloading": job.get("state") == "running", "progress": job.get("progress"), "error": job.get("error"),
            "done": job.get("done"), "next_for_human": job.get("next_for_human")}


def _download(url: str, dst: Path, progress: Callable[[str], None]) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Sonjari"})
    with urllib.request.urlopen(req, timeout=60) as resp, dst.open("wb") as out:  # noqa: S310
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        last = 0.0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if time.time() - last > 1.0:
                last = time.time()
                progress(f"받는 중 {got / 1e6:.0f}MB" + (f" / {total / 1e6:.0f}MB ({got * 100 // total}%)" if total else ""))
    if total and got != total:
        raise RuntimeError(f"덜 받았다({got}/{total}바이트)")


def _install(platform: str, fetch: Callable[[str], bytes], downloader: Callable[..., None], opener: Callable[[Path], None]) -> None:
    def progress(text: str) -> None:
        with _LOCK:
            _JOB["progress"] = text

    try:
        version = latest(fetch)
        name = file_name(version, platform)
        want = expected_sha(version, name, fetch)
        if platform == "win32":
            home = install_dir()
            home.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(home).free / 1e9
            if free < NEED_FREE_GB:
                raise RuntimeError(f"자리가 모자라다(남은 {free:.1f}GB · 약 {NEED_FREE_GB:.0f}GB 필요)")
            archive = home / (name + ".part")
        else:
            home = download_dir()
            home.mkdir(parents=True, exist_ok=True)
            archive = home / (name + ".part")
        downloader(BASE + name, archive, progress)
        progress("지문 맞추는 중")
        got = _sha(archive)
        if got != want:
            archive.unlink(missing_ok=True)
            raise RuntimeError(f"지문이 다르다(받은 {got[:12]}… · 공식 {want[:12]}…) — 지웠다")
        final = archive.with_name(name)
        if final.exists():
            final.unlink()
        archive.rename(final)
        if platform == "win32":
            progress("푸는 중")
            target = home / name[:-len(".zip")]
            tmp = home / (target.name + ".unpack")
            shutil.rmtree(tmp, ignore_errors=True)
            with zipfile.ZipFile(final) as zf:
                for member in zf.namelist():  # 풀 자리 밖으로 나가는 이름(../)은 받지 않는다
                    if not (tmp / member).resolve().is_relative_to(tmp.resolve()):
                        raise RuntimeError(f"zip 안 이상한 경로: {member}")
                zf.extractall(tmp)
            inner = [p for p in tmp.iterdir() if p.is_dir()]
            src = inner[0] if len(inner) == 1 and not (tmp / "blender.exe").exists() else tmp
            if not (src / "blender.exe").is_file():
                raise RuntimeError("풀었는데 blender.exe 가 없다")
            shutil.rmtree(target, ignore_errors=True)
            src.rename(target)
            shutil.rmtree(tmp, ignore_errors=True)
            final.unlink(missing_ok=True)
            with _LOCK:
                _JOB.update(done={"version": version, "exe": str(target / "blender.exe"), "sha256": want}, next_for_human=None)
        else:
            opener(final)
            with _LOCK:
                _JOB.update(done={"version": version, "dmg": str(final), "sha256": want},
                            next_for_human="열린 창에서 블렌더 아이콘을 응용 프로그램(Applications) 폴더로 끌어 넣어 주세요. 끝나면 손자리가 저절로 찾습니다.")
        with _LOCK:
            _JOB.update(state="done", progress="끝")
        record = install_dir() if platform == "win32" else download_dir()
        try:
            (record / "sonjari_blender_install.json").write_text(json.dumps(
                {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "version": version, "file": name, "sha256": want, "notice": NOTICE},
                ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    except Exception as exc:  # noqa: BLE001 — 실패도 상태로
        with _LOCK:
            _JOB.update(state="failed", error=f"{type(exc).__name__}: {exc}"[:300])


def _open_mac(path: Path) -> None:
    subprocess.run(["open", str(path)], check=False, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def install(agree: bool, *, platform: str | None = None, fetch: Callable[[str], bytes] = _get,
            downloader: Callable[..., None] = _download, opener: Callable[[Path], None] = _open_mac,
            background: bool = True) -> dict[str, Any]:
    if not agree:
        return {"ok": False, "notice": NOTICE,
                "next": "이 안내문을 사람에게 그대로 보이고, 사람이 「받아」라고 하면 agree=true 로 다시 불러라. 동의 없이 받지 않는다."}
    platform = platform or sys.platform
    file_name("0", platform)  # 받을 수 없는 운영체제면 여기서 바로 까닭
    with _LOCK:
        if _JOB.get("state") == "running":
            return {"ok": True, "already_running": True, "progress": _JOB.get("progress")}
        _JOB.clear()
        _JOB.update(state="running", progress="시작")
    args = (platform, fetch, downloader, opener)
    if background:
        threading.Thread(target=_install, args=args, name="sonjari-blender-install", daemon=True).start()
    else:
        _install(*args)
    return {"ok": True, "started": True,
            "next": "뒤에서 받는 중이다(보통 1~3분). action=status 로 진행을 보고 found=true 가 되면 블렌더 도구를 다시 부른다. "
                    "맥은 next_for_human(끌어 넣기)을 사람에게 그대로 전한다."}


def tool(arguments: dict[str, Any]) -> dict[str, Any]:
    """3D 팩(`gen_3d_blender`) · 애니 팩(`anim_blender_setup`)이 같이 쓰는 처리 — 팩 켜기 단위가 그대로 살게 이름만 팩마다."""
    if str(arguments.get("action") or "status") == "install":
        return install(bool(arguments.get("agree")))
    st = status()
    if not st["found"] and not st["downloading"]:
        st["notice"] = NOTICE
        st["next"] = "블렌더가 없다. notice 를 사람에게 그대로 보이고, 「받아」라고 하면 action=install, agree=true."
    return {"ok": True, **st}


TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["status", "install"]},
        "agree": {"type": "boolean", "description": "사람이 안내문을 읽고 받기에 동의했을 때만 true"},
    },
    "required": ["action"],
}
TOOL_DESC = (
    "블렌더 상태 보기 · 받기(블렌더 마무리 · 렌더 · 애니 블렌더 도구가 쓰는 블렌더). 블렌더는 손자리에 들어 있지 않다. "
    "action=status 로 찾았는지 · 받는 중인지 보고, 없으면 안내문(notice)을 **사람에게 그대로 보이고** 사람이 「받아」라고 하면 "
    f"action=install, agree=true(blender.org 공식 {SERIES} LTS · 윈도우 약 0.4GB · 지문 확인 · 뒤에서 1~3분). "
    "맥은 dmg 를 열어 주고 끌어 넣기는 사람이 한다(next_for_human 을 그대로 전한다). 사람 동의 없이 agree=true 를 보내지 마라."
)
