"""손자리 본체가 Strata(대표 PC 개인용 로컬 모델)를 켜고 지킨다 — 1단계 (2026-11-13).

설계 docs/설계_Strata_앱이켜고지키기_2026-11-13.ko.md (engineering:system-design).

계기(같은 날): 클로드 셸에서 `use_strata.ps1 -On` 을 돌려 Strata · 다리가 클로드의 자식이 됐고, 대표가 클로드를 끄자 같이 죽어
PC · 맥 손자리가 1시간 넘게 생각을 못 했다. 재부팅 뒤에도 Strata 는 저절로 안 뜬다.

1단계: 깔렸나(detect) · 상태(status) · 지킴이(ensure — 본체가 켜질 때와 60초마다) · 포기 뒤 다시 켜기(retry).
2단계(다음): Strata 로 바꾸기 · 되돌리기 · 3D 작업 때 27B 로(선택 · .env · 본체 재시작) — 지금은 `scripts/use_strata.ps1` 이 한다.

★ Strata · 다리는 **떼어 낸 프로세스**로 띄운다 — 본체를 반영 때마다 재시작해도, 클로드를 껐다 켜도 산다.
  (본체의 자식이면 재시작 때마다 68GB 를 다시 읽는다 · 약 90초 · 맥 손자리 끊김.)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import setting

# ── 값은 여기 한 곳(scripts/use_strata.ps1 과 같은 값 · 바꾸면 둘 다) ─────────────────────────────
STRATA_CMD = Path(setting("JARVIS_STRATA_CMD",r"D:\Strata\terminal\current\bin\strata.cmd"))
STRATA_DATA = Path(setting("JARVIS_STRATA_DATA", r"D:\Strata"))
STRATA_LOCALAPPDATA = setting("JARVIS_STRATA_LOCALAPPDATA", r"D:\SLA")  # 포장 앱 경로 260자 회피(11-07)
STRATA_PORT = 8097
BRIDGE_PORT = 11436  # 11435 는 3060 정찰기 자리(launch_jarvis.ps1:51 · 11-08 바로잡음)
STRATA_MODEL = "strata/qwen3.8-flash-next-swift"
STRATA_SIZE = "iq2_xs"   # 11-08 대표: 2비트 — 일반 메모리 여유
STRATA_CONTEXT = "128k"

#: 켜는 중으로 보는 시간 — 68GB 를 읽는 동안(실측 약 90초) 겹쳐 띄우지 않는다.
STARTING_GRACE_SEC = 180
#: 이 시간 안에 이만큼 켰는데도 또 죽으면 포기 — 램이 모자라 죽으면 끝없이 68GB 를 읽어 PC 를 붙잡는다.
GIVE_UP_WINDOW_SEC = 600
GIVE_UP_STARTS = 3

# 떼어 낸 프로세스 — 본체 · 클로드의 작업 묶음(job)에서 빠져나와 따로 산다.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NO_WINDOW = 0x08000000


def detect(cmd: Path = STRATA_CMD, data: Path = STRATA_DATA) -> bool:
    """Strata 가 깔린 PC 인가 — 실행기와 모델 폴더가 둘 다 있어야. 손님 PC 에서는 False(화면에 안 보인다 · 11-07 결정)."""
    return cmd.is_file() and (data / "models").is_dir()


def is_selected(selection: dict[str, Any] | None) -> bool:
    """지금 고른 모델이 Strata 인가(use_strata.ps1 -On 이 쓰는 값과 같게)."""
    if not selection:
        return False
    return (str(selection.get("catalog_key") or "").startswith("strata")
            or str(selection.get("chat_model") or "").startswith("strata/"))


def launch_command(cmd: Path = STRATA_CMD, size: str = STRATA_SIZE, context: str = STRATA_CONTEXT) -> list[str]:
    """use_strata.ps1 -On 의 launch 줄과 같은 인자."""
    return [str(cmd), "launch", "--model", size, "--family", "swift", "--data-dir", str(STRATA_DATA / "models"),
            "--context", context, "--parallel", "1", "--vision", "gpu", "--tune", "skip", "--access", "local",
            "--port", str(STRATA_PORT), "--gpu", "0",
            "--set", "conversation-cache-mib=4096", "--set", "conversation-cache-min-tokens=4000",
            "--set", "conversation-cache-slots=6", "--yes", "--no-tui"]


def stop_command(cmd: Path = STRATA_CMD) -> list[str]:
    return [str(cmd), "launch", "--stop"]


def free_ram_command() -> list[str]:
    """Strata 를 켜기 전에 Ollama 감시 작업을 끄고 Ollama · llama-server 를 내린다(use_strata.ps1 -On 의 102~127줄과 같은 일).
    감시를 안 끄면 감시가 Strata 모델 이름으로 Ollama 에 묻다 실패해 Ollama 를 계속 다시 띄운다."""
    script = ("Disable-ScheduledTask -TaskName 'RoboMetaFit-Ollama-Watchdog' -ErrorAction SilentlyContinue | Out-Null; "
              "Get-Process 'ollama app','ollama','llama-server' -ErrorAction SilentlyContinue | "
              "Stop-Process -Force -ErrorAction SilentlyContinue")
    return ["powershell", "-NoProfile", "-Command", script]


def strata_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env["LOCALAPPDATA"] = STRATA_LOCALAPPDATA
    env["STRATA_DATA_DIR"] = str(STRATA_DATA)
    return env


def bridge_command(runtime: Path) -> list[str]:
    python = runtime / ".venv" / "Scripts" / "python.exe"
    return [str(python), str(runtime / "scripts" / "strata_bridge.py")]


@dataclass
class Probe:
    strata: bool
    bridge: bool


@dataclass
class StrataState:
    starts: list[float] = field(default_factory=list)   # 지킴이가 켠 시각(초)
    last_error: str = ""
    gave_up: bool = False

    @classmethod
    def load(cls, path: Path) -> "StrataState":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(starts=[float(x) for x in raw.get("starts") or []], last_error=str(raw.get("last_error") or ""),
                   gave_up=bool(raw.get("gave_up")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


def decide(selected: bool, state: StrataState, probe: Probe, now: float) -> str:
    """지킴이 한 바퀴의 판단 — "none" · "start" · "bridge" · "give_up". 순수 함수(시험 표 · 설계 3.3)."""
    if not selected or state.gave_up:
        return "none"
    if probe.strata and probe.bridge:
        return "none"
    if probe.strata and not probe.bridge:
        return "bridge"                      # 다리만 죽음 — 1초짜리
    recent = [t for t in state.starts if now - t < GIVE_UP_WINDOW_SEC]
    if recent and now - max(recent) < STARTING_GRACE_SEC:
        return "none"                        # 켜는 중(68GB 읽는 중) — 겹쳐 띄우지 않는다
    if len(recent) >= GIVE_UP_STARTS:
        return "give_up"
    return "start"


def _spawn_detached(argv: list[str], *, env: dict[str, str] | None, log: Path | None) -> int:
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB | CREATE_NO_WINDOW \
        if sys.platform == "win32" else 0
    out = open(log, "ab") if log else subprocess.DEVNULL  # noqa: SIM115 — 떼어 낸 프로세스가 쥔다
    try:
        proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,  # noqa: S603
                                creationflags=flags, close_fds=True)
    except OSError:
        # 작업 묶음이 「빠져나가기」를 막아 둔 경우(일부 실행 환경) — 떼어 냄 플래그만 빼고 다시.
        flags &= ~CREATE_BREAKAWAY_FROM_JOB
        proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,  # noqa: S603
                                creationflags=flags, close_fds=True)
    return proc.pid


class StrataService:
    """본체 안에서 Strata · 다리를 지킨다. HTTP 확인 · 프로세스 띄우기는 주입해 시험한다."""

    def __init__(self, *, data_dir: Path, runtime: Path, selection: Callable[[], dict[str, Any] | None],
                 http_ok: Callable[[str], bool] | None = None, spawn: Callable[..., int] | None = None,
                 run: Callable[..., Any] | None = None, clock: Callable[[], float] = time.time,
                 available: Callable[[], bool] = detect) -> None:
        self.state_path = data_dir / "strata_state.json"
        self.runtime = runtime
        self.selection = selection
        self.http_ok = http_ok or _http_ok
        self.spawn = spawn or _spawn_detached
        self.run = run or subprocess.run
        self.clock = clock
        self.available = available
        self.log_dir = data_dir / "logs"

    # ── 보기 ──
    def probe(self) -> Probe:
        return Probe(strata=self.http_ok(f"http://127.0.0.1:{STRATA_PORT}/health"),
                     bridge=self.http_ok(f"http://127.0.0.1:{BRIDGE_PORT}/api/ps"))

    def status(self) -> dict[str, Any]:
        available = self.available()
        state = StrataState.load(self.state_path)
        probe = self.probe() if available else Probe(False, False)
        return {"available": available, "selected": is_selected(self.selection()), "strata": probe.strata, "bridge": probe.bridge,
                "gave_up": state.gave_up, "last_error": state.last_error, "model": STRATA_MODEL,
                "context": STRATA_CONTEXT}

    # ── 지킴이 ──
    def ensure(self) -> str:
        if not self.available():
            return "none"
        state = StrataState.load(self.state_path)
        now = self.clock()
        action = decide(is_selected(self.selection()), state, self.probe(), now)
        if action == "start":
            state.starts = [t for t in state.starts if now - t < GIVE_UP_WINDOW_SEC] + [now]
            state.last_error = ""
            state.save(self.state_path)
            self._start_strata()
            self._start_bridge()
        elif action == "bridge":
            self._start_bridge()
        elif action == "give_up":
            state.gave_up = True
            state.last_error = (f"Strata 가 {GIVE_UP_WINDOW_SEC // 60}분 안에 {GIVE_UP_STARTS}번 꺼졌습니다 — 램이 모자란지 "
                                "(맥스 · 다른 큰 프로그램) 보고 「다시 켜기」를 누르세요")
            state.save(self.state_path)
        return action

    def _start_strata(self) -> None:
        # 재부팅하면 Ollama 도 로그인 때 뜬다(RoboMetaFit-Ollama-AtLogon · 11-13 아침 12:50 모델이 올라와 있었다).
        # Ollama 가 램을 쥔 채 Strata 를 켜면 Strata 가 디스크에서 읽어 5~7 tok/s(11-07) — use_strata.ps1 처럼 먼저 내린다.
        self.run(free_ram_command(), capture_output=True, timeout=60, check=False)
        self.spawn(launch_command(), env=strata_env(), log=self.log_dir / "strata_launch.log")

    def _start_bridge(self) -> None:
        self.spawn(bridge_command(self.runtime), env=None, log=self.log_dir / "strata_bridge.log")

    # ── 다시 켜기 — 지킴이가 포기(10분 3번)한 뒤 사람이 램을 비우고 누른다 ──
    #   3D 작업용 「잠시 끄기」는 대표 결정(11-13 「3D 할 땐 묶자」)대로 2단계의 27B 바꾸기로 간다 — 여기엔 없다.
    def retry(self) -> dict[str, Any]:
        state = StrataState.load(self.state_path)
        state.gave_up, state.starts, state.last_error = False, [], ""
        state.save(self.state_path)
        self.ensure()
        return self.status()

    def _stop_bridge(self) -> None:
        if sys.platform != "win32":
            return
        # 다리는 이 파일 이름으로 찾는다(use_strata.ps1 Stop-StrataAndBridge 와 같은 방법).
        script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*strata_bridge.py*' } | "
                  "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        self.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=30, check=False)


def watch_enabled(env: dict[str, str] | None = None) -> bool:
    """지킴이를 돌릴지. 시험 중에는 절대 안 돈다 — 이 PC 엔 진짜 Strata 가 깔려 있어 시험이 본체를 만들 때마다 68GB 를 띄우면 안 된다.
    끄는 문: JARVIS_STRATA_WATCH=0."""
    if "pytest" in sys.modules:
        return False
    value = setting("JARVIS_STRATA_WATCH", "1") if env is None else env.get("JARVIS_STRATA_WATCH", "1")
    return value.strip() not in {"0", "false", "no", "off"}


def start_watch(service: StrataService, *, interval: float = 60.0, first_delay: float = 20.0) -> bool:
    """본체가 켜질 때 부른다 — first_delay 뒤 한 번(재부팅 대응), 그 뒤 interval 마다. 예외는 삼킨다(본체를 죽이지 않는다)."""
    if not watch_enabled():
        return False
    import threading

    def loop() -> None:
        time.sleep(first_delay)
        while True:
            try:
                service.ensure()
            except Exception:  # noqa: BLE001 — 다음 바퀴에 다시 본다
                pass
            time.sleep(interval)

    threading.Thread(target=loop, name="strata-watch", daemon=True).start()
    return True


def _http_ok(url: str) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 — 127.0.0.1 고정
            return 200 <= response.status < 300
    except Exception:  # noqa: BLE001
        return False
