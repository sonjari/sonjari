"""Ollama 버튼 한 번 설치 (W2, 2026-09-15 제품 요청).

## 사실과 제약 (인수인계서 W2, 2026-09-15 확인)

- 공식 `OllamaSetup.exe` 는 무인 설치 플래그가 문서에 없다. 공식 `ollama-windows-amd64.zip` 은
  「다른 앱에 내장하거나 `ollama serve` 로 서비스처럼 돌리는」 용도로 문서화돼 있다.
- 스토어 정책 10.2.3·10.2.4: 기능에 필요한 비통합 의존은 설명 첫머리에 공개하면 허용.
  10.2.2: 원격 코드를 받아 **설명과 다르게** 실행 금지.

## 그래서 이렇게 한다

1. 이미 Ollama 가 돌면(`/api/version` 응답) 그대로 쓴다. 아무것도 받지 않는다.
2. 없으면 사용자가 누른 버튼이 동의다 → GitHub 공식 릴리스의 zip 을 자비스 데이터 폴더에 받는다.
3. **받은 것을 그냥 실행하지 않는다.** 같은 릴리스의 `sha256sum.txt`(그리고 GitHub 가 주는 자산
   digest)와 해시를 대조해 다르면 지우고 멈춘다.
4. 풀어서 자비스가 `ollama serve` 를 직접 켜고 끈다(설치 창·서비스 등록 없음).
5. 모델 위치는 `OLLAMA_MODELS` — 비워 두면 Ollama 기본(사용자 폴더 `.ollama\\models`)이라
   앱을 지워도 받은 모델이 남는다(MSIX 전용 칸 밖).

주소는 `github.com/ollama/ollama` 릴리스로 **고정**한다. 받는 주소가 그 밖으로 가면 거절한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

RELEASE_API = "https://api.github.com/repos/ollama/ollama/releases/latest"
ASSET_NAME = "ollama-windows-amd64.zip"
SUMS_NAME = "sha256sum.txt"
ALLOWED_DOWNLOAD_PREFIXES = (
    "https://github.com/ollama/ollama/releases/download/",
    # GitHub 는 받기 주소를 저장소 CDN 으로 넘긴다(302). 넘어간 뒤 주소는 urllib 가 따라간다.
)
USER_AGENT = "AltureJarvis-OllamaInstaller/1"
CREATE_NO_WINDOW = 0x08000000

Fetch = Callable[[str], bytes]


def _fetch(url: str, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


#: API 를 안 거치는 최신판 페이지. GitHub 가 `…/releases/tag/<판>` 으로 넘겨준다(2026-10-01 실측: v0.35.0).
LATEST_PAGE = "https://github.com/ollama/ollama/releases/latest"


def _latest_page_url(timeout: float = 30.0) -> str:
    """최신판 페이지가 넘겨준 **최종 주소**. 본문은 안 읽는다."""
    request = urllib.request.Request(LATEST_PAGE, headers={"User-Agent": USER_AGENT}, method="HEAD")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return str(response.geturl())


def _system_app_candidates() -> tuple[Path, ...]:
    """공식 설치 파일(OllamaSetup.exe)이 까는 트레이 앱 자리 — 사용자별 설치가 기본, 예전 판은 Program Files."""
    out: list[Path] = []
    for env_name, tail in (("LOCALAPPDATA", ("Programs", "Ollama")), ("ProgramFiles", ("Ollama",))):
        base = os.environ.get(env_name)
        if base:
            out.append(Path(base).joinpath(*tail, "ollama app.exe"))
    return tuple(out)


def parse_sums(text: str, name: str = ASSET_NAME) -> str:
    """`sha256sum.txt` 에서 한 파일의 해시. 없으면 빈 문자열."""
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*").lstrip("./") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return ""


# ── 서버의 대화 보관함 한도 (2026-10-10) ─────────────────────────────────────────────────
#
# 대표: 「뒤죽박죽으로 시간이 오래 걸린다」 → 「이거 들어가자, 주말이라 늦어져도 된다」.
# Ollama 안의 서버(llama-server)는 최근 대화의 상태를 메모리 보관함에 넣어 두고, 하던 대화로 돌아오면 거기서 되살린다.
# 한도는 기본 8,192MiB 다. 큰 대화 하나(약 5만 토큰)가 4.7GB, 작은 호출 하나가 0.6GB 쯤을 차지해서(저장점마다 150~270MiB),
# 작은 호출(기억 정리 · 분류 · 화면 글자 읽기)이 몇 번 끼어들면 **가장 오래된 것 = 하던 큰 대화**가 밀려난다. 밀려난 대화로
# 돌아오면 통째로 다시 읽는다 — 이 PC 의 사흘 기록에서 439번 밀어냈다.
#
# 잰 값(이 PC · 27B · 128K · 큰 대화 5만 토큰 → 작은 호출 N번 → 돌아와서 읽은 시간 · 세 판씩):
#   작은 호출 16번:  8GB 59.5 · 62.0 · 53.8초 —  12GB 59.0 · 59.0 · 58.9초 —  24GB 0.5 · 0.6 · 0.5초
#   작은 호출  8번:  12GB 는 되살렸다(0.5초대) — 8GB 값은 `docs/낱말하네스_전수조사_1008.ko.md` §7-25
# 한도를 올리면 서버가 **실제로 그만큼 메모리를 쓴다**(24GB 일 때 여유 메모리 35GB → 17GB). 그래서 이 PC 의 메모리에 맞춘다.
#
# 넘기는 길: 서버는 `LLAMA_ARG_CACHE_RAM`(MiB)을 읽고, Ollama 는 제 환경을 서버에 그대로 넘긴다(기록의 `limits:` 줄로 확인).
# 그래서 **손자리가 Ollama 를 켜거나 다시 켤 때** 그 환경에만 넣는다. 사용자 환경변수(레지스트리)에는 적지 않는다 — 이 이름은
# Ollama 만의 것이 아니라 llama.cpp 를 쓰는 모든 프로그램이 읽는다. 사람이 이미 정해 둔 값은 덮지 않는다.
# 모자란 점: 사람이 따로 깐 Ollama 가 손자리보다 먼저 켜져 있으면(로그인할 때 뜨는 트레이 앱) 이 값이 안 들어간다.
PROMPT_CACHE_ENV = "LLAMA_ARG_CACHE_RAM"
#: (메모리 GB 이상, 보관함 MiB). 위에서부터 처음 맞는 칸.
#:
#: ★ 2026-10-14: 메모리가 작은 PC 는 **줄인다.** 예전에는 28GB 아래를 손대지 않아 서버 기본값(8,192MiB)이 그대로 걸렸다.
#:   그날 밤 메모리 24GB 노트북(RTX 3050 6GB)에서 실행기가 일반 메모리를 12GB 까지 쓰다 죽었다 — 창 48K 의 대화 상태 한
#:   덩이가 0.7~1.35GB 이고 그것을 8GB 까지 쌓는다(윈도우 기록 「가상 메모리 부족 · llama-server 11.96GB」 · 마지막 줄
#:   `prompt_save … 1303.543 MiB` → `std::bad_alloc`). 16GB 노트북에서는 실행기가 8.6GB 를 쥐고 빈 메모리가 1.8GB 였다.
#:   내주는 것: 보관함이 작으면 다른 물음을 여럿 거친 뒤 본 대화로 돌아올 때 다시 읽는 일이 늘 수 있다(이 칸들에서는 **안 쟀다**).
#:   꺼지는 것보다 느린 쪽을 고른다.
PROMPT_CACHE_BY_RAM: tuple[tuple[float, int], ...] = ((56.0, 24576), (28.0, 12288), (12.0, 4096), (0.1, 2048))


def prompt_cache_mib(ram_gb: float | None) -> int:
    """이 PC 의 메모리로 정하는 보관함 한도(MiB). 0 = 손대지 않는다."""
    if not ram_gb:
        return 0
    for floor, mib in PROMPT_CACHE_BY_RAM:
        if float(ram_gb) >= floor:
            return mib
    return 0


def ollama_launch_env(setting: int = -1, *, ram_gb: float | None = None,
                      environ: dict[str, str] | None = None) -> dict[str, str]:
    """손자리가 Ollama 를 켤 때 줄 환경 — 카드 제한은 그대로 돌려주고(`gpu_policy`), 보관함 한도를 얹는다.

    `setting`: -1 = 메모리에 맞춰 스스로 · 0 = 손대지 않는다 · 양수 = 그 값(MiB).
    """
    from .gpu_policy import child_env_for_ollama

    env = child_env_for_ollama(environ)
    if PROMPT_CACHE_ENV in env or setting == 0:
        return env  # 사람이 정해 둔 값은 덮지 않는다
    if setting > 0:
        mib = int(setting)
    else:
        if ram_gb is None:
            try:
                from .setup_profile import _ram_gb

                ram_gb = _ram_gb()
            except Exception:  # noqa: BLE001 — 못 재면 손대지 않는다
                ram_gb = None
        mib = prompt_cache_mib(ram_gb)
    if mib > 0:
        env[PROMPT_CACHE_ENV] = str(mib)
    return env


class OllamaInstaller:
    def __init__(
        self,
        *,
        install_root: Path,
        base_url: str = "http://127.0.0.1:11434",
        models_dir: str = "",
        legacy_roots: tuple[Path, ...] = (),
        fetch_json: Callable[[str], dict[str, Any]] | None = None,
        fetch_bytes: Fetch | None = None,
        latest_page_url: Callable[[], str] | None = None,
        download: Callable[[str, Path, Callable[[int, int], None]], None] | None = None,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        system_apps: tuple[Path, ...] | None = None,
        prompt_cache_mib: int = -1,
    ) -> None:
        self.install_root = Path(install_root)
        #: 서버 보관함 한도(`ollama_launch_env`). -1 = 메모리에 맞춰 · 0 = 손대지 않음 · 양수 = MiB.
        self.prompt_cache_mib = int(prompt_cache_mib)
        #: 사람이 **공식 설치 파일로** 깐 Ollama 의 트레이 앱 자리. 우리 설치가 없을 때 이것을 켠다.
        self.system_apps = tuple(system_apps) if system_apps is not None else _system_app_candidates()
        #: 예전에 깔던 자리(앱 데이터 안). 거기 멀쩡한 설치가 있으면 **다시 받지 않고 옮겨 온다.**
        self.legacy_roots = tuple(Path(one) for one in legacy_roots)
        self.base_url = base_url.rstrip("/")
        self.models_dir = models_dir
        self._fetch_json = fetch_json or (lambda url: json.loads(_fetch(url).decode("utf-8")))
        self._fetch_bytes = fetch_bytes or _fetch
        self._latest_page_url = latest_page_url or _latest_page_url
        self._download = download or self._download_to
        self.publish = publish
        self.popen = popen
        self._lock = threading.Lock()
        #: 켜기는 한 번에 한 사람만(`serve`). 다시 켜기(`_restart_with_env`)가 안에서 `serve` 를 부르므로 되들어올 수 있게 둔다.
        self._serve_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None
        self._state: dict[str, Any] = {"phase": "idle"}

    # ── 상태 ───────────────────────────────────────────────────────────────
    def running_version(self) -> str:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/version", timeout=2.5) as response:
                return str(json.loads(response.read().decode("utf-8")).get("version") or "")
        except (urllib.error.URLError, OSError, ValueError):
            return ""

    def bundled_exe(self) -> Path | None:
        marker = self.install_root / "current.json"
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        exe = self.install_root / str(data.get("folder") or "") / "ollama.exe"
        return exe if exe.is_file() else None

    #: 모델을 **실제로 돌리는** 실행 파일. `ollama.exe` 는 서버일 뿐이라 이것 없이도 켜지고 목록도 답한다.
    RUNNER_NAME = "llama-server.exe"

    def runner_exe(self) -> Path | None:
        """우리가 깐 Ollama 안의 `llama-server.exe`. 없으면 None.

        ★ 2026-09-18 노트북: 설치가 「성공」이라 했는데 모델을 올릴 때 `llama-server binary not found` 로 터졌다.
          **뿌리는 자리였다** — 앱 데이터 안에 깔았더니 스토어판에서 그 파일들이 앱 전용 칸으로 갔고,
          패키지 밖 실행 파일인 Ollama 는 그 칸을 못 본다. 우리 눈에는 파일 43개가 멀쩡히 보였다.
          자리는 `config.ollama_install_dir` 로 옮겼고(사용자 폴더), 여기서는 **깔고 나서 러너가 있는지**를 확인한다.
        """
        exe = self.bundled_exe()
        if exe is None:
            return None
        root = exe.parent
        for candidate in (root / self.RUNNER_NAME, root / "lib" / "ollama" / self.RUNNER_NAME):
            if candidate.is_file():
                return candidate
        found = next(root.rglob(self.RUNNER_NAME), None)
        return found if found is not None and found.is_file() else None

    def status(self) -> dict[str, Any]:
        version = self.running_version()
        with self._lock:
            state = dict(self._state)
        bundled = self.bundled_exe()
        # ★ 우리가 깐 것이 **반쪽**인가 (2026-09-18 노트북). 러너가 없으면 서버는 켜지고 목록도 답하지만
        #   모델은 하나도 못 올린다. 그런데 「이미 돌고 있다」는 이유로 다시 설치 버튼까지 숨어 있었다 —
        #   사용자가 고칠 방법이 화면에 없었다. 반쪽이면 다시 설치를 열어 준다.
        broken = bool(bundled) and self.runner_exe() is None
        # ★ 새 자리는 비었는데 **옛 자리의 우리 Ollama** 가 돌고 있으면 그것도 고장이다(스토어판에서는 그 서버가
        #   자기 러너를 못 본다 — 2026-09-18 노트북). 프로세스 목록은 비싸서 그 경우에만, 짧게 기억해 둔다.
        if not broken and version and bundled is None and self.legacy_roots:
            broken = self._legacy_server_running()
        busy = state.get("phase") in {"resolving", "downloading", "verifying", "extracting", "starting"}
        return {
            "running": bool(version),
            "version": version,
            "bundled": str(bundled) if bundled else "",
            # 어디에 깔 것인가 — 스토어판에서 이 자리가 앱 데이터 안이면 Ollama 가 자기 파일을 못 본다(2026-09-18).
            # 포장 합격 시험이 **실제 패키지 안에서** 이 값을 확인한다.
            "install_root": str(self.install_root),
            "runner_missing": broken,
            "managed": self._process is not None and self._process.poll() is None,
            "install": state,
            # 이미 돌면 설치 버튼을 안 보인다 — 쓰는 Ollama 를 바꾸지 않는다. 다만 우리 설치가 반쪽이면 고칠 길을 연다.
            "can_install": (not version or broken) and not busy,
            "source": "https://github.com/ollama/ollama/releases",
            "license": "MIT (Ollama) — 고지: packaging/THIRD_PARTY_NOTICES.md",
        }

    def _legacy_server_running(self) -> bool:
        now = time.monotonic()
        cached = getattr(self, "_legacy_seen", None)
        if cached is not None and now - cached[0] < 10.0:
            return cached[1]
        try:
            answer = bool(self.our_running_servers())
        except Exception:  # noqa: BLE001 — 못 재면 「고장 아님」으로 둔다(버튼을 괜히 띄우지 않는다)
            answer = False
        self._legacy_seen = (now, answer)
        return answer

    def _set(self, **fields: Any) -> None:
        with self._lock:
            self._state = {**self._state, **fields, "updated_at": time.time()}
            snapshot = dict(self._state)
        if self.publish is not None:
            self.publish("ollama_install", snapshot)

    # ── 설치 ───────────────────────────────────────────────────────────────
    def adopt_legacy_install(self) -> dict[str, Any]:
        """예전 자리(앱 데이터)에 있는 **멀쩡한 설치를 새 자리로 옮긴다.** 1.4GB 를 다시 받지 않게.

        ★ 2026-09-18. 자리를 사용자 폴더로 옮기면서, 이미 받아 둔 사람은 그대로 쓰게 하려고 넣었다.
          우리 프로세스는 앱 전용 칸이 보이므로 읽을 수 있다 — 못 보는 것은 Ollama 쪽이다.
          러너까지 갖춘 설치만 옮긴다(반쪽을 옮기면 고장을 옮기는 것이다).
        """
        if self.bundled_exe() is not None and self.runner_exe() is not None:
            return {"ok": False, "error": "already_installed"}
        for legacy in self.legacy_roots:
            if legacy.resolve() == self.install_root.resolve():
                continue
            marker = legacy / "current.json"
            try:
                folder = str(json.loads(marker.read_text(encoding="utf-8")).get("folder") or "")
            except (OSError, ValueError):
                continue
            source = legacy / folder
            if not folder or not (source / "ollama.exe").is_file():
                continue
            if next(source.rglob(self.RUNNER_NAME), None) is None:
                continue  # 반쪽이면 옮기지 않는다 — 다시 받는 편이 낫다
            target = self.install_root / folder
            try:
                self.install_root.mkdir(parents=True, exist_ok=True)
                staging = self.install_root / f"{folder}.adopting"
                shutil.rmtree(staging, ignore_errors=True)
                shutil.copytree(source, staging)
                shutil.rmtree(target, ignore_errors=True)
                staging.rename(target)
                shutil.copyfile(marker, self.install_root / "current.json")
            except OSError as exc:
                return {"ok": False, "error": f"copy_failed:{type(exc).__name__}: {exc}"[:200]}
            if self.runner_exe() is None:
                return {"ok": False, "error": "copied_but_runner_missing"}
            self._set(phase="ready", adopted_from=str(source))
            return {"ok": True, "adopted_from": str(source), "folder": folder}
        return {"ok": False, "error": "no_legacy_install"}

    def start_install(self) -> dict[str, Any]:
        # 우리가 깐 것이 반쪽이면(러너 없음) 돌고 있어도 다시 깐다 — 그 상태로는 모델을 하나도 못 올린다.
        if self.running_version() and not (self.bundled_exe() and self.runner_exe() is None):
            return {"ok": False, "error": "already_running"}
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return {"ok": False, "error": "in_progress"}
            self._state = {"phase": "resolving", "started_at": time.time()}
            self._thread = threading.Thread(target=self._install_safely, name="jarvis-ollama-install", daemon=True)
            self._thread.start()
        return {"ok": True, "phase": "resolving"}

    def _install_safely(self) -> None:
        try:
            # 새 자리에 이미 멀쩡한 설치가 있으면 켜기만 한다(고치기를 두 번 눌렀을 때 다시 받지 않게).
            if self.bundled_exe() is not None and self.runner_exe() is not None:
                started = self.serve()
                self._set(phase="ready" if started.get("ok") else "error", error=started.get("error", ""))
                return
            # 예전 자리에 멀쩡한 설치가 있으면 그것을 옮겨 쓴다 — 1.4GB 를 다시 받지 않는다.
            if self.adopt_legacy_install().get("ok"):
                started = self.serve()
                self._set(phase="ready" if started.get("ok") else "error", error=started.get("error", ""))
                return
            self.install()
        except Exception as exc:  # noqa: BLE001 — 화면에 이유가 가야 한다
            self._set(phase="error", error=f"{type(exc).__name__}: {exc}"[:300])

    # ── 고치기 (2026-09-18 노트북) ─────────────────────────────────────────────
    def our_running_servers(self, find: Callable[[], list[dict[str, str]]] | None = None) -> list[dict[str, str]]:
        """**우리가 깐 자리에서** 돌고 있는 `ollama.exe` 만. 사람이 따로 깐 Ollama 는 여기 안 든다.

        스토어판에서는 같은 폴더가 두 경로로 보인다(우리 눈의 앱 데이터 경로 · 밖에서 본 실제 전용 칸 경로).
        둘 다 우리 자리로 센다.
        """
        roots: list[Path] = [self.install_root, *self.legacy_roots]
        try:
            from .msix import external_path

            roots += [external_path(root) for root in list(roots)]
        except Exception:  # noqa: BLE001 — 못 풀면 그대로의 경로로만 센다
            pass
        prefixes = {str(root).lower().rstrip("\\/") + os.sep for root in roots}
        rows = (find or _ollama_processes)()
        return [row for row in rows
                if row.get("name", "").lower() == "ollama.exe"
                and any(str(row.get("path") or "").lower().startswith(prefix) for prefix in prefixes)]

    def repair(self, *, find: Callable[[], list[dict[str, str]]] | None = None,
               kill: Callable[[int], None] | None = None) -> dict[str, Any]:
        """고장난 우리 Ollama 를 **끄고 → 새 자리로 옮기고(없으면 받고) → 새 자리에서 켠다.**

        ★ 2026-09-18 노트북: 「다시 설치」가 `already_running` 으로 거절됐다. 돌고 있는 것은 **옛 자리에서 켜진
          고장난** Ollama 였는데, 검사는 새 자리만 봤다(비어 있으니 「반쪽 아님 + 이미 돈다 → 손대지 않음」).
          「적용하기」도 그 고장난 서버에 물어 같은 오류가 나 화면이 그대로였다 — 사람 눈엔 「아무것도 안 된다」.
        사람이 따로 깐 Ollama 가 돌고 있으면 **건드리지 않는다**(`not_ours`) — 그건 사람의 것이다.
        """
        ours = self.our_running_servers(find)
        if self.running_version() and not ours:
            if self.bundled_exe() is not None and self.runner_exe() is not None:
                return {"ok": True, "phase": "ready", "note": "already_healthy"}
            return {"ok": False, "error": "not_ours"}
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return {"ok": False, "error": "in_progress"}
        self.stop()
        for row in ours:
            try:
                (kill or _kill_pid)(int(row["pid"]))
            except Exception:  # noqa: BLE001 — 이미 끝난 프로세스는 그냥 지나간다
                pass
        gone_by = time.monotonic() + 15
        while self.running_version() and time.monotonic() < gone_by:
            time.sleep(0.3)
        if self.running_version():
            return {"ok": False, "error": "old_server_still_answering", "stopped": len(ours)}
        with self._lock:
            self._state = {"phase": "starting", "started_at": time.time(), "repair": True}
            self._thread = threading.Thread(target=self._install_safely, name="jarvis-ollama-repair", daemon=True)
            self._thread.start()
        return {"ok": True, "phase": "starting", "stopped": len(ours)}

    def resolve(self) -> dict[str, str]:
        """받을 판·주소·해시. GitHub API 가 막히면 **API 없는 길**로 같은 것을 알아낸다.

        ★ 2026-10-01 베타 첫 사용자(회사 PC): 「HTTP Error 403: rate limit exceeded」로 설치가 멈췄다. 로그인 없는
          GitHub API 는 **IP 하나당 시간당 60번**이라, 직원 수천 명이 한 인터넷 주소를 쓰는 회사에서는 남이 다 써 버린다.
          받기 주소(`releases/download/…`)는 이 제한과 상관없다 — 판 이름만 API 없이 알면 된다.
        """
        try:
            return self._resolve_by_api()
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as api_error:
            # **길이 막힌 것만** 다른 길로 간다(403 횟수 제한·프록시·응답 깨짐). 공식 밖 주소·해시 불일치 같은
            #   **안전 거절**은 여기 안 온다 — 그건 다른 길로 우회할 일이 아니라 멈출 일이다.
            try:
                return self._resolve_without_api()
            except Exception as page_error:  # noqa: BLE001 — 그 길도 막히면 둘 다 말한다
                raise RuntimeError(f"{api_error} · 대체 경로도 실패: {page_error}") from page_error

    def _resolve_without_api(self) -> dict[str, str]:
        """`releases/latest` 페이지가 넘겨주는 주소(`…/releases/tag/v0.35.0`)에서 판 이름을 읽는다.

        해시 대조는 그대로다 — 그 판의 `sha256sum.txt` 와 맞지 않으면 받은 것을 실행하지 않는다.
        API 가 주던 자산 digest 는 이 길에 없으니 `sha256sum.txt` 하나와 대조한다(없으면 받지 않는다).
        """
        final = self._latest_page_url()
        match = re.search(r"/releases/tag/([0-9A-Za-z._-]+)/?$", final)
        if not match:
            raise RuntimeError(f"latest_page_unexpected:{final[:120]}")
        tag = match.group(1)
        base = f"{ALLOWED_DOWNLOAD_PREFIXES[0]}{tag}/"
        expected = parse_sums(self._fetch_bytes(base + SUMS_NAME).decode("utf-8", "replace"))
        if not expected:
            raise RuntimeError("no_published_hash")
        return {"version": tag, "url": base + ASSET_NAME, "sha256": expected, "size": ""}

    def _resolve_by_api(self) -> dict[str, str]:
        release = self._fetch_json(RELEASE_API)
        assets = {str(a.get("name") or ""): a for a in release.get("assets") or []}
        asset = assets.get(ASSET_NAME)
        sums = assets.get(SUMS_NAME)
        if not asset:
            raise RuntimeError(f"release_has_no_{ASSET_NAME}")
        url = str(asset.get("browser_download_url") or "")
        if not url.startswith(ALLOWED_DOWNLOAD_PREFIXES):
            raise RuntimeError("download_url_not_official")
        expected = ""
        if sums and str(sums.get("browser_download_url") or "").startswith(ALLOWED_DOWNLOAD_PREFIXES):
            expected = parse_sums(self._fetch_bytes(str(sums["browser_download_url"])).decode("utf-8", "replace"))
        digest = str(asset.get("digest") or "")
        api_digest = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""
        if expected and api_digest and expected != api_digest:
            raise RuntimeError("release_hashes_disagree")
        expected = expected or api_digest
        if not expected:
            # 대조할 해시가 없으면 받지 않는다 — 받은 것을 그냥 실행하지 않는다는 약속.
            raise RuntimeError("no_published_hash")
        return {"version": str(release.get("tag_name") or ""), "url": url, "sha256": expected,
                "size": str(asset.get("size") or "")}

    def install(self) -> dict[str, Any]:
        self._set(phase="resolving")
        release = self.resolve()
        folder = re.sub(r"[^0-9A-Za-z._-]", "_", release["version"] or "unknown")
        self.install_root.mkdir(parents=True, exist_ok=True)
        archive = self.install_root / f"{folder}.zip.partial"
        self._set(phase="downloading", version=release["version"], expected_sha256=release["sha256"],
                  total=int(release["size"] or 0), received=0)
        self._download(release["url"], archive, lambda received, total: self._set(received=received, total=total))
        self._set(phase="verifying")
        actual = _sha256(archive)
        if actual != release["sha256"]:
            archive.unlink(missing_ok=True)
            self._set(phase="error", error="hash_mismatch", actual_sha256=actual)
            return {"ok": False, "error": "hash_mismatch"}
        self._set(phase="extracting", actual_sha256=actual)
        target = self.install_root / folder
        # 지금 쓰는 설치가 「.extracting」 이름으로 살아 있을 수 있다(`_move_into_place` 의 둘째 길). 그 폴더를 풀 자리로
        # 다시 쓰면 돌고 있는 설치를 지운다 — 살아 있는 폴더와 다른 이름을 고른다.
        live = self._live_folder()
        staging = next(self.install_root / name
                       for name in (f"{folder}.extracting", f"{folder}.extracting-2") if name != live)
        shutil.rmtree(staging, ignore_errors=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                destination = (staging / member.filename).resolve()
                if not str(destination).startswith(str(staging.resolve())):
                    raise RuntimeError("zip_path_escape")
            bundle.extractall(staging)
        if not (staging / "ollama.exe").is_file():
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError("zip_has_no_ollama_exe")
        # ★ 서버(`ollama.exe`)만 보고 「설치 끝」이라 하면 안 된다 (2026-09-18 노트북). 러너가 빠지면
        #   서버는 켜지고 목록도 답하지만 모델은 **하나도 못 올린다.** 그 고장이 설치가 아니라
        #   몇 분 뒤 「모델을 올렸지만 글자가 나오지 않았습니다」로 나타나 드라이버를 의심하게 만들었다.
        if next(staging.rglob(self.RUNNER_NAME), None) is None:
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError("zip_has_no_runner")
        # 우리가 켠 서버가 그 폴더를 쥐고 있으면 못 지운다 — 다시 깔기(반쪽 복구) 때 먼저 끈다.
        self.stop()
        shutil.rmtree(target, ignore_errors=True)
        placed = self._move_into_place(staging, target)
        archive.unlink(missing_ok=True)
        (self.install_root / "current.json").write_text(
            json.dumps({"folder": placed.name, "version": release["version"], "sha256": actual,
                        "installed_at": time.time()}, ensure_ascii=False), encoding="utf-8")
        # 앞 설치가 다른 이름의 폴더였으면 이제 안 쓴다(서버는 위에서 껐다). 못 지워도 설치는 끝난 것이다.
        if live and live != placed.name:
            shutil.rmtree(self.install_root / live, ignore_errors=True)
        started = self.serve()
        self._set(phase="ready" if started.get("ok") else "error", error=started.get("error", ""))
        return {"ok": bool(started.get("ok")), "version": release["version"], "sha256": actual}

    #: 푼 폴더를 제자리로 옮기는 것을 몇 초까지 다시 해 보나.
    MOVE_RETRY_SECONDS = 20.0

    def _live_folder(self) -> str:
        """`current.json` 이 가리키는 폴더 이름(없으면 빈 글). 이름 모양이 아니면 안 믿는다 — 그 이름으로 지운다."""
        try:
            data = json.loads((self.install_root / "current.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        name = str(data.get("folder") or "") if isinstance(data, dict) else ""
        return name if re.fullmatch(r"[0-9A-Za-z._-]+", name) and name.strip(".") else ""

    def _move_into_place(self, staging: Path, target: Path) -> Path:
        """푼 폴더를 제자리 이름으로 옮긴다. 끝내 못 옮기면 **푼 자리 그대로** 쓴다 — 돌려주는 것이 설치된 폴더다.

        ★ 2026-10-06 스토어 공개판 첫 설치(회사 PC, 보안 프로그램 PCFILTER 가 깔린 곳): 다 받고 해시도 맞고 다 풀었는데
          마지막 이름 바꾸기 한 번이 `PermissionError [WinError 5]` 로 떨어져 **설치 전체가 실패**했다. 방금 푼 exe·dll 을
          보안 프로그램이 훑는 동안에는 폴더 이름을 못 바꾼다(원인은 그 PC 에서 확인하지 못했다 — 어느 쪽이든 같은 자리다).
          이름 바꾸기는 필수가 아니다. 설치된 자리는 `current.json` 이 가리키는 폴더이므로, 몇 번 다시 해 보고 안 되면
          푼 폴더를 그대로 가리키게 한다.
        """
        deadline = time.monotonic() + self.MOVE_RETRY_SECONDS
        delay = 0.25
        while True:
            try:
                staging.rename(target)
                return target
            except OSError:
                if time.monotonic() >= deadline:
                    return staging
                time.sleep(delay)
                delay = min(delay * 2, 2.0)

    def _download_to(self, url: str, target: Path, progress: Callable[[int, int], None]) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            last = 0.0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if time.monotonic() - last > 0.5:
                    progress(received, total)
                    last = time.monotonic()
            progress(received, total)

    # ── 켜기·끄기 ──────────────────────────────────────────────────────────
    def _list_runners(self) -> list[dict[str, Any]]:
        """모델 실행기(`llama-server.exe`) — pid · 부모 pid · 경로 · 부모 Ollama 가 살아 있나."""
        return _runner_processes()

    @staticmethod
    def _kill(pid: int) -> None:
        _kill_pid(pid)

    def clear_orphan_runners(self) -> list[int]:
        """**우리 엔진 폴더의** 실행기 중 부모 Ollama 가 죽은 것을 끈다. 끈 pid 목록.

        ★ 2026-09-20 노트북: 앱이 꺼질 때(업데이트의 강제 종료 포함) Ollama 는 죽는데 자식 실행기는 고아로 남아
          그래픽 메모리를 쥐었다 — 8GB 카드에 4B 가 두 벌, 읽기 12초·생성 16토큰/초(정리 뒤 0.67초·69토큰/초).
          사람이 따로 깐 Ollama 는 경로가 달라 안 건드린다. 지금 Ollama 의 실행기(지금 모델)도 안 건드린다.
        """
        root = str(self.install_root).lower().rstrip("\\/") + "\\"
        killed: list[int] = []
        try:
            rows = self._list_runners()
        except Exception:  # noqa: BLE001 - 못 보면 안 건드린다
            return killed
        for row in rows:
            path = str(row.get("path") or "").lower().replace("/", "\\")
            if not path.startswith(root) or row.get("parent_alive"):
                continue
            try:
                self._kill(int(row["pid"]))
                killed.append(int(row["pid"]))
            except Exception:  # noqa: BLE001
                continue
        if killed and self.publish:
            self.publish("ollama_orphan_runners_cleared", {"pids": killed})
        return killed

    def serve(self, *, wait_sec: float = 30.0) -> dict[str, Any]:
        """우리 Ollama 를 켠다. **한 번에 한 사람만** (2026-10-05 AWS 영어 윈도우 첫 실행).

        설치가 끝나는 순간 두 곳이 같이 켰다 — 설치 스레드(풀고 나서 켠다)와 지킴이(`OllamaKeeper`, 화면이 `/health` 를
        물을 때 「깔려 있는데 꺼져 있다」를 보고 켠다). 둘 다 「안 돌고 있다」를 확인한 뒤 `ollama serve` 를 띄웠고,
        포트를 못 잡은 쪽은 코드 1로 죽었다. 화면에는 「설치하지 못했습니다 (serve_exited:1)」가 떴다가 곧바로
        「돌고 있습니다 — 그대로 씁니다」로 바뀌었다: 멀쩡히 깔리고 켜졌는데 실패라고 말했고, 진 쪽이 `_process` 를
        덮어써 우리가 켠 것을 남의 것으로 알았다(`managed=False`). 줄을 세우면 둘째는 「이미 돌고 있다」를 본다.
        """
        with self._serve_lock:
            return self._serve_locked(wait_sec=wait_sec)

    def _serve_locked(self, *, wait_sec: float) -> dict[str, Any]:
        # 고아 실행기를 먼저 치운다 — 남아 있으면 새로 올리는 모델이 카드에 온전히 못 올라간다.
        self.clear_orphan_runners()
        if self.running_version():
            return {"ok": True, "already_running": True}
        exe = self.bundled_exe()
        if exe is None:
            app = self.system_app()
            if app is None:
                return {"ok": False, "error": "not_installed"}
            return self._serve_system_app(app, wait_sec=wait_sec)
        # 사용자가 Ollama 를 위해 정해 둔 카드 제한은 **그대로** 돌려준다 — 온텔릭 자신은 그 값을 안 물려받았다(gpu_policy).
        env = ollama_launch_env(self.prompt_cache_mib)
        host = self.base_url.split("://", 1)[-1]
        env["OLLAMA_HOST"] = host
        if needs_gpu_only():
            # 우리가 켜는 Ollama 는 **알아서** NVIDIA 만 보게 한다 — 사람이 환경변수를 만질 일이 없게(2026-09-16).
            env["OLLAMA_VULKAN"] = "0"
        if self.models_dir:
            env["OLLAMA_MODELS"] = self.models_dir
        log = (self.install_root / "serve.log").open("ab")
        process = self.popen(
            [str(exe), "serve"], env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self._process = process
        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            if self.running_version():
                return {"ok": True, "pid": process.pid}
            if process.poll() is not None:
                # 우리가 띄운 것은 죽었는데 **서버가 답한다** = 다른 Ollama 가 그 자리를 잡았다(사람이 방금 켰거나,
                # 이 관리자 밖에서 띄운 것). 실패가 아니다 — 죽은 손잡이를 쥐고 있지도 않는다.
                if self._process is process:
                    self._process = None
                if self._answers_within(self.SERVE_TAKEOVER_GRACE_SEC):
                    return {"ok": True, "already_running": True}
                return {"ok": False, "error": f"serve_exited:{process.returncode}"}
            time.sleep(0.5)
        return {"ok": False, "error": "serve_not_answering"}

    #: 우리가 띄운 서버가 죽었을 때, 다른 서버가 답하는지 기다려 보는 시간(초). 포트를 먼저 잡은 쪽이 듣기 시작할 틈.
    SERVE_TAKEOVER_GRACE_SEC = 3.0

    def _answers_within(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            if self.running_version():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.3)

    def system_app(self) -> Path | None:
        """사람이 공식 설치 파일로 깐 Ollama 트레이 앱. 없으면 None."""
        return next((app for app in self.system_apps if app.is_file()), None)

    def _serve_system_app(self, app: Path, *, wait_sec: float) -> dict[str, Any]:
        """★ 사람이 따로 깐 Ollama 가 꺼져 있으면 **그 프로그램으로** 켠다 (2026-10-01 베타 첫 사용자 · 회사 PC).

        우리 설치가 GitHub 403 에 막혀 테스터가 Ollama 공식 설치 파일로 깔았다. 설치 뒤 계정 화면만 뜨고 서버는 안 떠 있어
        모델 받기가 「[WinError 10061] 연결 거부」였다 — 그때 이 관리자는 **우리가 깐 것만** 켰다. 트레이 앱을 띄우면 서버를
        같이 올린다. 우리 것이 아니므로 `_process` 로 쥐지 않는다(`stop()` 은 사람이 켠 Ollama 를 건드리지 않는다).
        """
        env = ollama_launch_env(self.prompt_cache_mib)
        if needs_gpu_only():
            env["OLLAMA_VULKAN"] = "0"
        flags = (CREATE_NO_WINDOW | 0x00000008) if os.name == "nt" else 0  # DETACHED_PROCESS
        process = self.popen([str(app)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=flags, cwd=str(app.parent))
        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            if self.running_version():
                return {"ok": True, "pid": process.pid, "external": True}
            time.sleep(0.5)
        return {"ok": False, "error": "system_ollama_not_answering"}

    # ── 그래픽카드 고르기 (2026-09-16 노트북 첫 설치에서 제품 요청) ─────────────────
    def fix_gpu_selection(
        self,
        *,
        write_setting: Callable[[], bool] | None = None,
        find_processes: Callable[[], list[dict[str, str]]] | None = None,
        kill: Callable[[int], None] | None = None,
        vulkan_setting: Callable[[], str] | None = None,
        wait_sec: float = 40.0,
    ) -> dict[str, Any]:
        """NVIDIA 카드와 내장 그래픽이 같이 있을 때 Ollama 가 **NVIDIA 만** 쓰게 맞춘다.

        ★ 부팅 직후 Ollama 가 CUDA 대신 내장 그래픽(Vulkan)을 잡아 모델 적재가 통째로 실패한 적이 있다(사고 P).
          예전 마법사는 「OLLAMA_VULKAN=0 을 권합니다」라고 **말만** 했다 — 사람에게 환경변수를 만지라는 건 제품이 아니다.
        하는 일은 셋: ① 사용자 환경변수 `OLLAMA_VULKAN=0`(다음 부팅에도 유지) ② 우리 백엔드 환경에도 반영
        ③ 이미 돌던 Ollama 는 새 설정으로 다시 켠다. 사람이 `OLLAMA_VULKAN` 을 켜 뒀으면 **덮어쓰지 않는다.**
        MSIX 안에서 쓴 HKCU Environment 는 밖에서도 보인다(2026-09-16 실측 — 패키지 신원이 붙은 상태로 확인).
        """
        if vulkan_setting is None:
            from .setup_profile import _vulkan_setting as vulkan_setting
        before = vulkan_setting()
        if before == "on":
            return {"ok": False, "error": "user_set_vulkan_on"}
        written = False
        if before != "off":
            written = (write_setting or _write_user_vulkan_off)()
            if not written:
                return {"ok": False, "error": "setting_not_written"}
        os.environ["OLLAMA_VULKAN"] = "0"
        return self._restart_with_env({"OLLAMA_VULKAN": "0"}, written=written, find_processes=find_processes,
                                      kill=kill, wait_sec=wait_sec)

    # ── 컨텍스트 기본값 (2026-09-23 제품 요청 · 「묻고 넣기」) ───────────────────────
    def set_default_context(
        self,
        num_ctx: int,
        *,
        owned_path: Path,
        current_setting: Callable[[], str] | None = None,
        write_setting: Callable[[int], bool] | None = None,
        find_processes: Callable[[], list[dict[str, str]]] | None = None,
        kill: Callable[[int], None] | None = None,
        wait_sec: float = 40.0,
    ) -> dict[str, Any]:
        """잰 상한을 **Ollama 전체 기본값**(`OLLAMA_CONTEXT_LENGTH`, 사용자 환경변수)으로 둔다.

        ★ 왜: `num_ctx` 를 안 보내는 프로그램(클로드 코드의 Anthropic 호환 요청)은 Ollama 기본값으로 올린다 —
          VRAM 24~48GB 면 32K, 24GB 미만이면 4K. 그게 먼저 올라오면 온텔릭도 그 컨텍스트를 따라가고, 값이 다르면
          서로 러너를 쫓아낸다. 기본값을 상한과 맞추면 누가 먼저 올리든 같은 러너다.
        ★ 사람이 적어 둔 값은 **덮지 않는다**(OLLAMA_VULKAN 과 같은 규칙). 우리가 적었던 값인지는 `owned_path` 에
          남긴 기록으로 가린다 — 우리가 쓴 값이면 새 상한으로 바꿔도 된다.
        """
        num_ctx = int(num_ctx)
        current = (current_setting or _read_user_context_length)()
        ours = _read_owned(owned_path).get("OLLAMA_CONTEXT_LENGTH", "")
        if current and current != ours:
            return {"ok": False, "error": "user_set_context_length", "current": current}
        written = False
        if current != str(num_ctx):
            written = (write_setting or _write_user_context_length)(num_ctx)
            if not written:
                return {"ok": False, "error": "setting_not_written"}
            _write_owned(owned_path, {"OLLAMA_CONTEXT_LENGTH": str(num_ctx)})
        os.environ["OLLAMA_CONTEXT_LENGTH"] = str(num_ctx)
        if not written:
            return {"ok": True, "setting_written": False, "restarted": "unchanged"}
        return self._restart_with_env({"OLLAMA_CONTEXT_LENGTH": str(num_ctx)}, written=written,
                                      find_processes=find_processes, kill=kill, wait_sec=wait_sec)

    def _restart_with_env(
        self,
        env_updates: dict[str, str],
        *,
        written: bool,
        find_processes: Callable[[], list[dict[str, str]]] | None,
        kill: Callable[[int], None] | None,
        wait_sec: float,
    ) -> dict[str, Any]:
        """돌던 Ollama 를 **새 환경으로** 다시 켠다. 우리가 켠 것은 우리 식으로, 사람이 켠 것은 그 프로그램으로."""
        if not self.running_version():
            return {"ok": True, "setting_written": written, "restarted": "not_running"}
        if self._process is not None and self._process.poll() is None:
            self.stop()
            served = self.serve(wait_sec=wait_sec)
            return {**served, "ok": bool(served.get("ok")), "setting_written": written, "restarted": "managed"}
        rows = (find_processes or _ollama_processes)()
        if not rows:
            return {"ok": False, "setting_written": written, "error": "ollama_process_not_found"}
        app = next((r["path"] for r in rows if r.get("name", "").lower() == "ollama app.exe" and r.get("path")), "")
        exe = next((r["path"] for r in rows if r.get("name", "").lower() == "ollama.exe" and r.get("path")), "")
        if not app and not exe:
            return {"ok": False, "setting_written": written, "error": "ollama_path_unknown"}
        for row in rows:
            try:
                (kill or _kill_pid)(int(row["pid"]))
            except Exception:  # noqa: BLE001 — 이미 끝난 프로세스는 그냥 지나간다
                pass
        # 끊긴 것을 확인한 뒤 켠다 — 옛 서버가 아직 답하면 새 설정이 안 먹은 채로 「됐다」가 된다.
        gone_by = time.monotonic() + 10
        while self.running_version() and time.monotonic() < gone_by:
            time.sleep(0.3)
        # ★ 사용자가 Ollama 를 위해 정해 둔 카드 제한을 **돌려준다** (2026-10-01 밤). 여기만 `os.environ` 을 그대로 물려,
        #   손자리 자신의 GPU 설정(`gpu_policy` — 모든 카드)이 Ollama 로 새었다. 컨텍스트를 적용하며 다시 켠 Ollama 가
        #   3090 + 3060(화면 카드) 두 장에 모델을 나눠 올렸고, 적재율을 못 읽어 다음 적용이 거절됐다.
        #   Ollama 를 켜는 다른 두 자리(`serve`·시스템 앱)는 이미 이 함수를 쓴다 — 세 번째 자리만 빠져 있었다.
        env = {**ollama_launch_env(self.prompt_cache_mib), **env_updates}
        flags = (CREATE_NO_WINDOW | 0x00000008) if os.name == "nt" else 0  # DETACHED_PROCESS
        command = [app] if app else [exe, "serve"]
        self.popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            version = self.running_version()
            if version:
                return {"ok": True, "setting_written": written, "restarted": "external", "version": version}
            time.sleep(0.5)
        return {"ok": False, "setting_written": written, "error": "ollama_not_answering_after_restart"}

    def stop(self) -> None:
        """우리가 켠 것만 끈다. 사용자가 따로 켠 Ollama 는 건드리지 않는다."""
        process, self._process = self._process, None
        if process is None or process.poll() is not None:
            return
        # ★ `terminate()` 는 Ollama 만 죽이고 자식 실행기(llama-server)를 고아로 남겼다(2026-09-20). 나무째 끈다.
        try:
            self._kill(process.pid)
        except Exception:  # noqa: BLE001
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


class OllamaKeeper:
    """우리가 깐 Ollama 를 **꺼져 있으면 알아서 켜 둔다** (2026-09-20 사용자 요청 · 노트북 실측).

    예전에는 백엔드가 시작할 때 `serve()` 를 **딱 한 번** 불렀다. 노트북에서 앱 창이 뜬 뒤 Ollama 가
    뜨기까지 14초였고, 그 사이 화면은 「Ollama 에 닿지 않습니다」를 띄웠다. 도중에 Ollama 가 죽거나
    트레이에서 끄면 다시 안 켰다.

    `annotate()` 는 `/health` 의 ollama 칸을 받아 — 꺼져 있으면 켜기를 걸고 `starting` 을 붙인다.
    화면이 몇 초마다 `/health` 를 물으니 따로 감시 스레드가 필요 없다.

    - 켜는 중에 또 물어도 두 번 켜지 않는다(스레드 하나).
    - 방금 시도했으면 `retry_sec` 동안은 다시 걸지 않는다(켜지는 데 걸리는 시간을 준다).
    - **연달아 `give_up_after` 번 실패하면 `starting=False`** — 끝없이 「켜는 중」이라고 하면 거짓말이다.
      실패 이유는 `autostart_error` 에 싣는다. 한 번이라도 뜨면 셈을 0 으로 되돌린다.
    - 우리가 깐 Ollama 가 없으면(`bundled_exe() is None`) 켤 것이 없다 — 첫 실행 안내가 맞다.
    """

    def __init__(
        self,
        installer: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
        retry_sec: float = 20.0,
        give_up_after: int = 3,
        run: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.installer = installer
        self.clock = clock
        self.retry_sec = retry_sec
        self.give_up_after = give_up_after
        self._run = run
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_try = float("-inf")
        self._failures = 0
        self._last_error = ""

    def _serve_once(self) -> None:
        try:
            result = self.installer.serve()
        except Exception as exc:  # noqa: BLE001 — 실패는 셈하고 이유를 남긴다
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        with self._lock:
            if result.get("ok"):
                self._failures = 0
                self._last_error = ""
            else:
                self._failures += 1
                self._last_error = str(result.get("error") or "serve_failed")

    def ensure(self) -> bool:
        """꺼져 있다고 알려졌을 때 부른다. 돌려주는 값 = 지금 「켜는 중」이라고 말해도 되나."""
        try:
            installed = self.installer.bundled_exe() is not None
            if not installed:
                # 사람이 공식 설치 파일로 깐 Ollama 도 켤 수 있다(`OllamaInstaller._serve_system_app`).
                system_app = getattr(self.installer, "system_app", None)
                installed = bool(system_app and system_app() is not None)
        except Exception:  # noqa: BLE001
            installed = False
        if not installed:
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            if self._failures >= self.give_up_after:
                # 포기한 뒤에도 가끔은 다시 본다(사용자가 원인을 치웠을 수 있다) — 그래도 「켜는 중」이라 하지 않는다.
                if self.clock() - self._last_try >= self.retry_sec * 6:
                    self._failures = self.give_up_after - 1
                else:
                    return False
            if self.clock() - self._last_try < self.retry_sec:
                return True
            self._last_try = self.clock()
            if self._run is not None:
                runner = None
            else:
                runner = threading.Thread(target=self._serve_once, name="jarvis-ollama-keeper", daemon=True)
                self._thread = runner
        if runner is None:
            self._run(self._serve_once)  # type: ignore[misc]
            with self._lock:
                return self._failures < self.give_up_after
        runner.start()
        return True

    def annotate(self, status: Any) -> Any:
        """`/health` 의 ollama 칸. 살아 있으면 그대로, 죽어 있으면 켜기를 걸고 `starting` 을 붙인다."""
        if not isinstance(status, dict) or status.get("ok"):
            return status
        starting = self.ensure()
        out = {**status, "starting": starting}
        with self._lock:
            if not starting and self._last_error:
                out["autostart_error"] = self._last_error
        return out

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)


def needs_gpu_only() -> bool:
    """NVIDIA 카드와 다른 그래픽(내장 등)이 같이 있고, 사람이 `OLLAMA_VULKAN` 을 따로 안 적었나."""
    if os.name != "nt":
        return False
    try:
        from .setup_profile import _registry_adapters, _vulkan_setting

        if _vulkan_setting():
            return False
        vendors = [str(card.get("vendor") or "") for card in _registry_adapters()]
    except Exception:  # noqa: BLE001 — 못 재면 손대지 않는다
        return False
    return "nvidia" in vendors and any(vendor != "nvidia" for vendor in vendors)


def _write_user_vulkan_off() -> bool:
    return _write_user_env("OLLAMA_VULKAN", "0")


def _write_user_context_length(num_ctx: int) -> bool:
    return _write_user_env("OLLAMA_CONTEXT_LENGTH", str(int(num_ctx)))


def _read_user_context_length() -> str:
    """사용자·시스템 환경변수에 적힌 `OLLAMA_CONTEXT_LENGTH`. 사용자 칸이 이긴다."""
    if os.name != "nt":
        return str(os.environ.get("OLLAMA_CONTEXT_LENGTH") or "").strip()
    try:
        import winreg

        for root, path in ((winreg.HKEY_CURRENT_USER, "Environment"),
                           (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, path) as key:
                    value, _kind = winreg.QueryValueEx(key, "OLLAMA_CONTEXT_LENGTH")
                    if str(value).strip():
                        return str(value).strip()
            except OSError:
                continue
    except Exception:  # noqa: BLE001 — 못 읽으면 「사람이 안 적었다」가 아니라 모르는 것이다
        return "unknown"
    return ""


def _read_owned(path: Path) -> dict[str, str]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _write_owned(path: Path, values: dict[str, str]) -> None:
    merged = {**_read_owned(path), **values}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")


def _write_user_env(name: str, value: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        # 새로 켜는 프로그램(로그인 때 뜨는 Ollama 포함)이 바뀐 환경을 보게 알린다.
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 2000, ctypes.byref(result))
        return True
    except Exception:  # noqa: BLE001
        return False


_PS_OLLAMA = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
    "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('ollama app.exe','ollama.exe') } | "
    'ForEach-Object { "$($_.ProcessId)|$($_.Name)|$($_.ExecutablePath)" }'
)


def _ollama_processes() -> list[dict[str, str]]:
    """`ollama app.exe`(트레이)와 `ollama.exe`(서버) — pid·이름·경로."""
    if os.name != "nt":
        return []
    done = subprocess.run(["powershell", "-NoProfile", "-Command", _PS_OLLAMA], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30, creationflags=CREATE_NO_WINDOW)
    rows = []
    for line in (done.stdout or "").splitlines():
        parts = line.split("|")
        if len(parts) >= 3 and parts[0].strip().isdigit():
            rows.append({"pid": parts[0].strip(), "name": parts[1].strip(), "path": parts[2].strip()})
    return rows


_PS_RUNNERS = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
    "$alive = @(Get-Process ollama -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }); "
    "Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | "
    'ForEach-Object { "$($_.ProcessId)|$($_.ParentProcessId)|$([int]($alive -contains $_.ParentProcessId))|$($_.ExecutablePath)" }'
)


def _runner_processes() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    done = subprocess.run(["powershell", "-NoProfile", "-Command", _PS_RUNNERS], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30, creationflags=CREATE_NO_WINDOW)
    rows: list[dict[str, Any]] = []
    for line in (done.stdout or "").splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4 and parts[0].strip().isdigit():
            rows.append({"pid": int(parts[0]), "parent": int(parts[1] or 0), "parent_alive": parts[2].strip() == "1",
                         "path": parts[3].strip()})
    return rows


def _kill_pid(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20,
                   creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["ASSET_NAME", "OllamaInstaller", "parse_sums"]
