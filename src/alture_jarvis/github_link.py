"""깃허브 연결 — 「설정 › 연결 › 깃허브 연결」 (2026-11-12 · 설계 `docs/설계_깃허브연결_2026-11-12.ko.md`).

순서를 코드에 박는다(모델이 셸로 즉흥하지 않는다 · 사고 R):
gh 찾기 → 없으면 **공식 릴리스 + 체크섬 + 서명**이 맞을 때만 넣기 → `gh auth login --web` 을 뒤에서 띄워 일회용 코드를 카드에
→ 사람이 브라우저에서 승인 → `gh auth status` 로 확인.

지키는 것
- gh 와 그 설정은 **앱 칸 밖**(엔진 폴더 `…/gh`)에 둔다 — 스토어판에서 앱 데이터에 새로 쓴 파일은 밖의 프로그램이 못 본다(9-18 Ollama).
- 사용자의 전역 git 설정 · 사용자가 따로 쓰는 gh 로그인은 건드리지 않는다. 우리 git 에만 자격 증명 도우미를 붙인다(`git_auth`).
- 토큰 값은 어디에도 싣지 않는다(`_scrub`).
"""
from __future__ import annotations

import hashlib
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

__all__ = ["GithubLink", "GH_RELEASE_API", "parse_login_prompt", "pick_asset", "parse_status"]

GH_RELEASE_API = "https://api.github.com/repos/cli/cli/releases/latest"
DEVICE_URL = "https://github.com/login/device"
#: 공식 gh 를 서명한 곳(11-12 실측) — 맥 애플 공증 팀 · 윈도우 Authenticode 주체.
MAC_TEAM_ID = "VEKTX9H2N7"
WINDOWS_SIGNER = "GitHub, Inc."
#: 일회용 코드를 기다리는 한도 · 사람이 승인하기를 기다리는 한도(깃허브 장치 코드는 보통 15분 — 그보다 길게 붙잡지 않는다).
CODE_WAIT_SEC = 12.0
LOGIN_WAIT_SEC = 15 * 60
#: ★ 11-12 이 PC 실측: 한국어 윈도우는 `text=True` 를 cp949 로 읽는다 — gh 의 「✓」(UTF-8)에서 깨져 로그인돼 있어도
#:   「안 됨」으로 나왔다. gh · git 출력은 늘 UTF-8 로 읽는다(모든 실행에 `encoding="utf-8"`).
#: 이보다 오래된 gh 는 「오래된 판」으로만 표시한다(계정 여럿 · `auth status` 모양이 이 뒤로 같다).
MIN_VERSION = (2, 40)

_CODE = re.compile(r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})")
_URL = re.compile(r"https://github\.com/login/device\S*")
_TOKEN = re.compile(r"\bgh[opsur]_[A-Za-z0-9_*]+")
_LOGGED_IN = re.compile(r"Logged in to github\.com (?:account|as) (\S+)(?: \(([^)]*)\))?")
_VERSION = re.compile(r"gh version (\d+)\.(\d+)\.(\d+)")

Run = Callable[..., "subprocess.CompletedProcess[str]"]


def _scrub(text: str) -> str:
    return _TOKEN.sub("<토큰>", str(text or ""))


def parse_login_prompt(text: str) -> tuple[str, str]:
    """`gh auth login --web` 이 표준 오류에 찍은 글에서 (코드, 주소). 못 찾으면 빈 글."""
    code = _CODE.search(text or "")
    url = _URL.search(text or "")
    return (code.group(1) if code else "", url.group(0).rstrip(".") if url else (DEVICE_URL if code else ""))


def parse_status(text: str) -> dict[str, Any]:
    """`gh auth status --hostname github.com` 출력 → {logged_in, user, storage}. storage: keyring / file / ""."""
    match = _LOGGED_IN.search(text or "")
    if not match:
        return {"logged_in": False, "user": "", "storage": ""}
    where = (match.group(2) or "").strip()
    return {"logged_in": True, "user": match.group(1), "storage": "keyring" if where == "keyring" else ("file" if where else "")}


def pick_asset(assets: list[dict[str, Any]], system: str, machine: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """릴리스 파일 목록에서 (이 기계의 zip, 체크섬 파일)."""
    arch = "arm64" if machine.lower() in {"arm64", "aarch64"} else "amd64"
    kind = {"darwin": "macOS", "win32": "windows"}.get(system)
    zip_asset = next((a for a in assets if kind and str(a.get("name", "")).endswith(f"_{kind}_{arch}.zip")), None)
    sums = next((a for a in assets if str(a.get("name", "")).endswith("_checksums.txt")), None)
    return zip_asset, sums


class GithubLink:
    def __init__(self, root: Path, *, run: Run | None = None, popen: Callable[..., Any] | None = None,
                 fetch: Callable[[str], bytes] | None = None, open_url: Callable[[str], Any] | None = None,
                 system: str | None = None, machine: str | None = None, which: Callable[[str], str | None] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.root = Path(root)                      # 엔진 폴더/gh
        self.system = system or sys.platform
        self.machine = machine or platform.machine()
        self._run = run or subprocess.run
        self._popen = popen or subprocess.Popen
        self._fetch = fetch or _http_get
        self._open_url = open_url or _open_default_browser
        self._which = which or shutil.which
        self._clock = clock
        self._login: dict[str, Any] | None = None
        self._lock = threading.Lock()

    # --- 자리 -----------------------------------------------------------------------------------------
    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def our_gh(self) -> Path:
        return self.root / "bin" / ("gh.exe" if self.system == "win32" else "gh")

    def _gh_env(self, ours: bool) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("GH_TOKEN", None)
        env.pop("GITHUB_TOKEN", None)  # 사용자 환경의 토큰이 우리 판정을 덮지 않게
        if ours:
            env["GH_CONFIG_DIR"] = str(self.config_dir)
        env["GH_NO_UPDATE_NOTIFIER"] = "1"
        return env

    def _call(self, gh: str, args: list[str], ours: bool, timeout: float = 30) -> "subprocess.CompletedProcess[str]":
        return self._run([gh, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
                         env=self._gh_env(ours), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _version(self, gh: str) -> tuple[int, int, int] | None:
        try:
            done = self._call(gh, ["--version"], ours=False, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        match = _VERSION.search(done.stdout or "")
        return tuple(int(x) for x in match.groups()) if match else None  # type: ignore[return-value]

    def find_gh(self) -> dict[str, Any] | None:
        """우리 자리 먼저, 그다음 사용자 PATH. {path, version, source}."""
        candidates = []
        if self.our_gh.is_file():
            candidates.append((str(self.our_gh), "ours"))
        system_gh = self._which("gh")
        if system_gh:
            candidates.append((system_gh, "system"))
        for path, source in candidates:
            version = self._version(path)
            if version:
                return {"path": path, "version": ".".join(map(str, version)), "source": source,
                        "old": version[:2] < MIN_VERSION}
        return None

    def find_git(self) -> dict[str, Any] | None:
        git = self._which("git")
        if not git:
            return None
        try:
            done = self._run([git, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            return None
        return {"path": git, "version": (done.stdout or "").strip().replace("git version ", "")}

    # --- 상태 -----------------------------------------------------------------------------------------
    def _login_state(self, gh: dict[str, Any]) -> dict[str, Any]:
        """우리 설정 자리 먼저 · 없으면 사용자의 gh 로그인(그대로 쓰기 후보)."""
        tries = [True, False] if gh["source"] == "ours" or self.config_dir.exists() else [False]
        for ours in tries:
            try:
                done = self._call(gh["path"], ["auth", "status", "--hostname", "github.com"], ours=ours)
            except (OSError, subprocess.TimeoutExpired):
                continue
            state = parse_status(f"{done.stdout}\n{done.stderr}")
            if state["logged_in"]:
                return {**state, "config": "ours" if ours else "user"}
        return {"logged_in": False, "user": "", "storage": "", "config": ""}

    def status(self) -> dict[str, Any]:
        gh = self.find_gh()
        login = self._login_state(gh) if gh else {"logged_in": False, "user": "", "storage": "", "config": ""}
        return {"gh": gh, "git": self.find_git(), "login": login, "pending": self._pending_view(),
                "supported": self.system in {"darwin", "win32"}}

    # --- 받기 -----------------------------------------------------------------------------------------
    def install(self) -> dict[str, Any]:
        """공식 릴리스에서 이 기계의 gh 를 받아 **체크섬 · 서명이 맞을 때만** 우리 자리에 넣는다."""
        import json

        release = json.loads(self._fetch(GH_RELEASE_API).decode("utf-8"))
        zip_asset, sums_asset = pick_asset(release.get("assets") or [], self.system, self.machine)
        if not zip_asset or not sums_asset:
            raise RuntimeError("gh_asset_not_found")
        blob = self._fetch(str(zip_asset["browser_download_url"]))
        sums = self._fetch(str(sums_asset["browser_download_url"])).decode("utf-8", "replace")
        want = next((line.split()[0] for line in sums.splitlines()
                     if line.strip().endswith(str(zip_asset["name"]))), "")
        got = hashlib.sha256(blob).hexdigest()
        if not want or want.lower() != got:
            raise RuntimeError("gh_checksum_mismatch")
        name = "gh.exe" if self.system == "win32" else "gh"
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            member = next((m for m in archive.namelist() if m.replace("\\", "/").endswith(f"bin/{name}")), "")
            if not member:
                raise RuntimeError("gh_binary_not_in_zip")
            data = archive.read(member)
        staging = self.root / "staging" / name
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(data)
        if self.system != "win32":
            staging.chmod(0o755)
        signed = self.check_signature(staging)
        if not signed["trusted"]:
            staging.unlink(missing_ok=True)
            raise RuntimeError(f"gh_not_signed:{signed['reason']}")
        self.our_gh.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, self.our_gh)
        return {"version": str(release.get("tag_name") or "").lstrip("v"), "path": str(self.our_gh),
                "sha256": got, "signer": signed["signer"]}

    def check_signature(self, binary: Path) -> dict[str, Any]:
        if self.system == "win32":
            from .app_install import check_windows

            seen = check_windows(binary, run=self._run)
            ok = seen["trusted"] and seen["signer"] == WINDOWS_SIGNER
            return {"trusted": ok, "signer": seen["signer"],
                    "reason": "" if ok else (seen["reason"] or f"서명한 곳이 {WINDOWS_SIGNER} 가 아니다")}
        verify = self._run(["codesign", "--verify", "--strict", str(binary)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, check=False)
        assess = self._run(["spctl", "-a", "-vv", "-t", "install", str(binary)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, check=False)
        detail = self._run(["codesign", "-dv", str(binary)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
        said = f"{assess.stdout}\n{assess.stderr}"
        team = re.search(r"TeamIdentifier=(\S+)", f"{detail.stdout}\n{detail.stderr}")
        ok = (verify.returncode == 0 and assess.returncode == 0 and "accepted" in said
              and "Notarized Developer ID" in said and bool(team) and team.group(1) == MAC_TEAM_ID)
        return {"trusted": ok, "signer": team.group(1) if team else "",
                "reason": "" if ok else "애플 공증을 받은 공식 gh(팀 VEKTX9H2N7)가 아니다"}

    # --- 로그인 ---------------------------------------------------------------------------------------
    def _pending_view(self) -> dict[str, Any] | None:
        login = self._login
        if not login:
            return None
        left = max(0, int(login["deadline"] - self._clock()))
        return {"code": login["code"], "url": login["url"], "expires_in": left}

    def login_start(self) -> dict[str, Any]:
        """`gh auth login --web` 을 뒤에서 띄우고 일회용 코드를 돌려준다. 이미 진행 중이면 같은 코드."""
        with self._lock:
            if self._login and self._login["proc"].poll() is None and self._clock() < self._login["deadline"]:
                return {"ok": True, **(self._pending_view() or {})}
            gh = self.find_gh()
            if not gh:
                return {"ok": False, "error": "gh_missing"}
            self.config_dir.mkdir(parents=True, exist_ok=True)
            proc = self._popen([gh["path"], "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace",
                               env=self._gh_env(ours=True), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                proc.stdin.write("\n")
                proc.stdin.flush()
            except (OSError, ValueError):
                pass
            seen: list[str] = []
            reader = threading.Thread(target=_drain, args=(proc.stderr, seen), daemon=True)
            reader.start()
            started = self._clock()
            code = url = ""
            while self._clock() - started < CODE_WAIT_SEC:
                code, url = parse_login_prompt("".join(seen))
                if code or proc.poll() is not None:
                    break
                time.sleep(0.1)
            if not code:
                _stop(proc)
                return {"ok": False, "error": "login_code_not_found", "detail": _scrub("".join(seen))[:300]}
            self._login = {"proc": proc, "code": code, "url": url, "deadline": started + LOGIN_WAIT_SEC, "seen": seen}
        try:
            self._open_url(url)
        except Exception:  # noqa: BLE001 — 못 열어도 카드에 주소가 있다
            pass
        return {"ok": True, **(self._pending_view() or {})}

    def login_poll(self) -> dict[str, Any]:
        login = self._login
        if not login:
            return {"state": "idle"}
        proc = login["proc"]
        if proc.poll() is None:
            if self._clock() < login["deadline"]:
                return {"state": "waiting", **(self._pending_view() or {})}
            _stop(proc)
            self._login = None
            return {"state": "expired"}
        self._login = None
        state = self.status()["login"]
        if proc.returncode == 0 and state["logged_in"]:
            return {"state": "done", "user": state["user"], "storage": state["storage"]}
        return {"state": "failed", "detail": _scrub("".join(login["seen"]))[-300:]}

    def logout(self) -> dict[str, Any]:
        """**우리 설정 자리의** 로그인만 끊는다 — 사용자가 따로 쓰는 gh 로그인은 그대로."""
        gh = self.find_gh()
        if not gh or not self.config_dir.exists():
            return {"ok": True, "changed": False}
        seen = self._call(gh["path"], ["auth", "status", "--hostname", "github.com"], ours=True)
        state = parse_status(f"{seen.stdout}\n{seen.stderr}")
        if not state["logged_in"]:
            return {"ok": True, "changed": False}
        done = self._call(gh["path"], ["auth", "logout", "--hostname", "github.com", "--user", state["user"]], ours=True)
        return {"ok": done.returncode == 0, "changed": done.returncode == 0, "detail": _scrub(done.stderr)[:200]}

    # --- 우리 git 에만 붙이는 자격 증명 ------------------------------------------------------------------
    def git_auth(self) -> tuple[list[str], dict[str, str]] | None:
        """우리가 부르는 git 의 앞 인자와 환경. 전역 `~/.gitconfig` 는 안 건드린다(설계 4-4)."""
        gh = self.find_gh()
        if not gh:
            return None
        state = self._login_state(gh)
        if not state["logged_in"]:
            return None
        helper = f"!'{Path(gh['path']).as_posix()}' auth git-credential"
        args = ["-c", "credential.https://github.com.helper=", "-c", f"credential.https://github.com.helper={helper}"]
        return args, self._gh_env(ours=state["config"] == "ours")


def _drain(stream: Any, sink: list[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            sink.append(line)
    except (OSError, ValueError):
        pass


def _stop(proc: Any) -> None:
    try:
        proc.kill()
    except OSError:
        pass


def _http_get(url: str) -> bytes:
    import httpx

    response = httpx.get(url, timeout=60.0, follow_redirects=True,
                         headers={"Accept": "application/vnd.github+json", "User-Agent": "Sonjari"})
    response.raise_for_status()
    return response.content


def _open_default_browser(url: str) -> None:
    import webbrowser

    webbrowser.open(url, new=2)
