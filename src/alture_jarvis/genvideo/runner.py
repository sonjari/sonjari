"""콘티 → 컷 × 후보 굽기 · 고른 것만 본판 — `sd-cli` 를 따로 떼어 낸 프로세스로 (2026-11-16 · 설계 §10-3 · §10-12).

3D 팩(`gen3d/runner.py`)과 같은 꼴:
- 한 번에 한 묶음. 대기열은 도는 것 하나 + 기다리는 것 하나까지, 그 위는 거절(그래픽카드 한 장을 둘이 나눠 쓰면 둘 다 느려진다).
- 묶음 안의 컷 × 후보는 **차례로** 하나씩 굽는다. 굽기 직전마다 「사람이 손자리를 쓰는 중인가」(`busy_probes`)를 보고,
  working 이면 끝날 때까지 기다린다 — 기다린 초는 영수증에 남는다(대표 지시 · 11-12 회귀가 대표 질문과 겹쳐 첫 글자가 20초).
- 카드: 못 박은 번호(설정) → 없으면 남은 메모리가 가장 많은 카드(`gen3d.memory.pick_gpu`). nvidia-smi 번호와 CUDA 번호를 맞춘다.
- 글 모델 내리기: **카드가 하나뿐일 때만**(손님 PC — 굽는 카드 = 글 모델 카드). 카드가 둘 이상이면 내리지 않는다(이 PC 27B 보호 · §10-4).
- 끝나면 컷마다 검사 숫자(`inspect.py`) · 장면 사진 판, 묶음엔 고르기 판(컷 × 후보) 한 장.
- 본판(`finish`)은 그린 결과를 다시 쓰지 못한다(실행기에 latent 저장 옵션 없음) — **같은 프롬프트 · 씨앗 · 첫 그림으로 다시 굽는다.**
  엔진이 바뀌면 모양 · 움직임이 시안과 달라진다 — 영수증 not_done 에 늘 적는다.
- 영수증 숫자는 손자리 코드가 잰 것과 실행기 로그에 찍힌 것만. 실패 · 취소도 영수증.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..gen3d.memory import gpu_list, gpu_used_mib
from . import commands
from .progress import VideoTracker, split_lines

_JOB_ID = re.compile(r"^gv_[0-9]{8}_[0-9]{6}_[0-9a-f]{6}$")
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
#: 한 컷 상한(초). 실측 최장 = LTX 아이콘 384초 · Wan 정식 풀기 370초 — 넉넉히 다섯 배.
RUN_TIMEOUT_SEC = 1800
#: 바쁨 기다리기 — 얼마마다 다시 보나 · 최대 얼마나(넘으면 그 컷은 실패로 적고 다음으로 가지 않고 멈춘다).
BUSY_POLL_SEC = 20.0
BUSY_WAIT_MAX_SEC = 2 * 3600
#: 잰 표(초 · 832×480 · 73프레임 · 3060 12GB · n=1~4). 「되나」의 예상 시간은 이것만 쓴다 — 잰 적 없는 조건은 None.
MEASURED_SEC = {
    "fastwan": {"range": [30.6, 57.1], "n": 4, "where": "§10-9 · RTX 3060 12GB · 832×480 · 73프레임"},
    "wan": {"range": [370.0, 370.0], "n": 1, "where": "§10-1 정식 풀기 · RTX 3060 12GB · 832×480 · 73프레임"},
    "ltx": {"range": [285.2, 383.7], "n": 4, "where": "§10-11 · RTX 3060 12GB · --offload-to-cpu · 832×480 · 73프레임"},
}
#: 본판 어긋남 기준(16×9 색 격자 · 같은 상대 시각 넷의 평균 색 차 · 0~1). 11-16 실측(설계 §10-14):
#:   시안 장면을 지킨 본판(처음·끝 고정) 0.056 · 0.073 / 장면이 바뀐 본판 0.168 · 0.262 · 0.268 · 0.300 · 0.329 /
#:   같은 프롬프트 · 다른 씨앗 시안끼리 0.158 · 0.161. 지킴 n=2 라 사이(0.10~0.15)는 「판을 본다」로 둔다.
DRIFT_KEPT_MAX = 0.10
DRIFT_FLAG_MIN = 0.15
#: LTX distilled 단계표 — 11-16 실측에서 장면을 바꾸지 못했다(단계표만 ↔ 기본 0.055 · 0.069 · 시안과는 여전히 0.268 · 0.329).
#:   원본 distilled 흐름의 값이라 켜 둔다(해는 못 봄 · 득도 못 봄 · n=2).
LTX_SIGMAS_ON = True
#: LTX(`--offload-to-cpu`)는 무게를 램에 두고 쓴다 — 본체 · 글 읽기(CPU) · 영상 VAE · 소리 VAE 파일 크기에 이만큼 더 남아 있어야 시작한다.
#: 실측(11-16 13시 로그 `total params memory size`): 램에 올린 무게 38,536MB = 글 읽기 14,273 + 본체 22,539 + VAE 1,725.
#: 파일 크기 합(약 37,800MiB)이 그와 거의 같다 — 여유는 2GB.
RAM_MARGIN_MIB = 2048


class GenVideoError(RuntimeError):
    pass


def valid_job_id(job_id: str) -> bool:
    return bool(_JOB_ID.fullmatch(str(job_id or "")))


def ram_free_mib() -> int | None:
    """남은 램(MiB). 윈도우는 GlobalMemoryStatusEx, 그 밖은 os.sysconf. 못 재면 None."""
    try:
        if sys.platform == "win32":
            # 램 부스트와 같은 재기(공용 windll 대신 `winapi` 를 거친다 — test_winapi_1103).
            from ..ram_boost import ram_free_gb

            free = ram_free_gb()
            return None if free is None else int(free * 1024)
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1048576)
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Task:
    cut: str
    candidate: int
    prompt: str
    seed: int
    frames: int
    first_image: str | None
    out_name: str
    state: str = "queued"
    receipt: dict[str, Any] | None = None
    #: 본판: 고른 시안 파일(절대 경로) — 처음·끝 고정의 재료이자 어긋남 검사의 짝.
    draft_file: str | None = None
    #: 본판: 시안의 첫 · 끝 프레임으로 고정하나(LTX 만).
    anchor: bool = False
    #: 콘티가 준 끝 그림(사람이 고른 실물 사진 등 · LTX 만) — 고정할 때도 시안의 끝 프레임보다 앞선다.
    last_image: str | None = None

    def saved(self) -> dict[str, Any]:
        return {"cut": self.cut, "candidate": self.candidate, "prompt": self.prompt, "seed": self.seed, "frames": self.frames,
                "first_image": self.first_image, "out_name": self.out_name, "state": self.state, "receipt": self.receipt,
                "draft_file": self.draft_file, "anchor": self.anchor, "last_image": self.last_image}


@dataclass
class Job:
    job_id: str
    kind: str
    engine: str
    folder: Path
    width: int
    height: int
    tasks: list[Task]
    title: str = ""
    aspect: str = "16:9"
    board_notes: list[str] = field(default_factory=list)
    skipped_cuts: list[dict[str, Any]] = field(default_factory=list)
    source_job: str | None = None
    state: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    current: int | None = None
    tracker: VideoTracker = field(default_factory=VideoTracker)
    waiting_busy: str | None = None
    receipt: dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False
    process: Any = None
    gpu: int | None = None
    gpu_pick: dict[str, Any] | None = None
    unloaded: list[str] = field(default_factory=list)
    not_unloaded: list[str] = field(default_factory=list)
    #: 굽기 직전 램 판정(11-17 · `pack_ram`) — {free_mib, commit_share, need_mib, unload, why}.
    ram: dict[str, Any] | None = None
    #: 글 모델을 내린 까닭 — "card"(카드 하나를 나눔) · "ram"(램 모자람).
    unload_reason: str = ""

    def public(self) -> dict[str, Any]:
        running = self.state == "running"
        progress = None
        if running and self.current is not None:
            task = self.tasks[self.current]
            progress = {"task": self.current + 1, "tasks": len(self.tasks), "cut": task.cut, "candidate": task.candidate,
                        "stage": None if self.waiting_busy else self.tracker.current(),
                        "waiting_busy": self.waiting_busy}
        return {"job_id": self.job_id, "kind": self.kind, "engine": self.engine, "state": self.state, "progress": progress,
                "done_tasks": sum(1 for t in self.tasks if t.state == "done"), "tasks": len(self.tasks),
                "receipt": self.receipt, "error": self.error}

    def saved(self) -> dict[str, Any]:
        return {**self.public(), "progress": None, "title": self.title, "aspect": self.aspect, "width": self.width,
                "height": self.height, "source_job": self.source_job, "board_notes": self.board_notes,
                "skipped_cuts": self.skipped_cuts, "task_list": [t.saved() for t in self.tasks]}


class VideoRunner:
    def __init__(
        self,
        out_root: Path,
        bin_dirs: list[Path],
        model_roots: list[Path],
        ltx_dir: Path,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        vram_probe: Callable[[int | None], int | None] = gpu_used_mib,
        gpus: Callable[[], list[dict]] = gpu_list,
        ram_probe: Callable[[], int | None] = ram_free_mib,
        memory_probe: Callable[[], dict[str, Any]] | None = None,
        busy_probes: list[Callable[[], str | None]] | None = None,
        text_models: Any = None,
        inspect_fn: Callable[..., dict[str, Any]] | None = None,
        grab_fn: Callable[[Path, Path, Path], tuple[str, str] | None] | None = None,
        drift_fn: Callable[[Path, Path], dict[str, Any]] | None = None,
        gpu_pin: int | None = None,
        poll_sec: float = 1.0,
        busy_poll_sec: float = BUSY_POLL_SEC,
        busy_wait_max_sec: float = BUSY_WAIT_MAX_SEC,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.out_root = Path(out_root)
        self.bin_dirs = [Path(p) for p in bin_dirs]
        self.model_roots = [Path(p) for p in model_roots]
        self.ltx_dir = Path(ltx_dir)
        self._popen = popen
        self._vram = vram_probe
        self._gpus = gpus
        self._ram = ram_probe
        self._memory_probe = memory_probe
        #: 「사람이 손자리를 쓰는 중인가」 — 각자 "working" · "idle" · None(못 봄)을 돌려준다.
        self.busy_probes = list(busy_probes or [])
        self.text_models = text_models
        self._inspect = inspect_fn
        self._grab = grab_fn
        self._drift_fn = drift_fn
        self.gpu_pin = gpu_pin
        self._poll_sec = float(poll_sec)
        self._busy_poll = float(busy_poll_sec)
        self._busy_max = float(busy_wait_max_sec)
        self._sleep = sleep
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._queue: list[str] = []
        self._running: str | None = None
        self.on_change: Callable[[str], None] | None = None

    # ── 무엇이 있나 ─────────────────────────────────────────────────────
    def files(self) -> dict[str, Path]:
        return commands.find_files([*self.model_roots, self.ltx_dir])

    def exe(self) -> Path | None:
        return commands.find_exe(self.bin_dirs)

    def engine_problems(self, engine: str, files: dict[str, Path] | None = None) -> list[str]:
        files = self.files() if files is None else files
        problems = []
        if self.exe() is None:
            problems.append("실행기(sd-cli)가 없다 — 설정 › 팩 › 영상 생성 팩에서 사람이 「받기」를 누르면 받는다(켜기만으로는 안 받는다 · 클로드는 대신 받지 않는다)")
        lack = commands.missing(engine, files)
        if lack:
            if engine == "ltx":
                problems.append(f"LTX 파일이 없다({', '.join(lack)}) — " + commands.LTX_HOW.format(dir=self.ltx_dir))
            else:
                problems.append(f"{engine} 모델 파일이 없다({', '.join(lack)}) — 설정 › 팩 › 영상 생성 팩에서 사람이 「받기」를 누르면 받는다(켜기만으로는 안 받는다 · 클로드는 대신 받지 않는다)")
        if engine == "ltx" and not lack:
            need = self.ltx_ram_need_mib(files)
            free = self._ram()
            if need and free is not None and free < need:
                problems.append(f"램이 모자라다 — 남은 {free:,}MiB, LTX(무게를 램에 두고 씀)는 약 {need:,}MiB 가 남아 있어야 한다. 다른 프로그램을 닫고 다시")
        return problems

    @staticmethod
    def ltx_ram_need_mib(files: dict[str, Path]) -> int | None:
        try:
            roles = ("ltx", "ltx_text", "ltx_vae", "ltx_audio_vae")
            return int(sum(files[role].stat().st_size for role in roles) / 1048576) + RAM_MARGIN_MIB
        except (KeyError, OSError):
            return None

    def busy_now(self) -> list[str]:
        """working 인 탐침 이름(빈 목록이면 아무도 안 쓴다). 탐침이 실패하면 그 탐침은 「못 봄」으로 넘어간다."""
        busy = []
        for index, probe in enumerate(self.busy_probes):
            try:
                state = probe()
            except Exception:  # noqa: BLE001
                state = None
            if state == "working":
                busy.append(getattr(probe, "label", f"probe{index}"))
        return busy

    def check(self) -> dict[str, Any]:
        """이 PC 로 되나 — 엔진마다 준비 · 카드 · 램 · 바쁨 · 잰 시간(잰 조건만)."""
        from ..video_read.scan import ffmpeg_exe

        files = self.files()
        cards = self._gpus()
        engines = {}
        for engine in commands.ENGINES:
            problems = self.engine_problems(engine, files)
            engines[engine] = {"ready": not problems, "problems": problems, "measured_sec_per_cut": MEASURED_SEC.get(engine)}
        pick = self._pick_card(cards)
        notes = []
        if not cards:
            notes.append("엔비디아 카드를 못 찾았다(nvidia-smi 없음) — 이 판은 CUDA 실행기만 있다")
        if len(cards) == 1:
            notes.append("카드가 하나 — 굽기 전에 이 기기 글 모델을 내린다(다음 질문 때 다시 올라온다 · 첫 답이 그만큼 늦다)")
        if pick and pick.get("total_mib", 0) < 12000:
            notes.append(f"고른 카드 메모리 {pick.get('total_mib')}MiB — 잰 적은 12GB(3060)부터다. 더 작은 카드는 안 쟀다")
        if not ffmpeg_exe():
            notes.append("ffmpeg 가 없다 — 검사 숫자 · 장면 사진 판을 못 만든다(굽기는 된다)")
        return {
            "ok": engines["fastwan"]["ready"],
            "engines": engines,
            "draft_engine": commands.DRAFT_ENGINE,
            "gpus": cards, "gpu_pick": pick, "ram_free_mib": self._ram(), "ram": self._ram_check(),
            "busy": self.busy_now(),
            "ffmpeg": bool(ffmpeg_exe()),
            "notes": notes,
        }

    # ── 받기 ────────────────────────────────────────────────────────────
    def _new_job_locked(self, kind: str, engine: str, width: int, height: int, tasks: list[Task], **extra: Any) -> Job:
        waiting = len(self._queue) + (1 if self._running else 0)
        if waiting >= 2:
            raise GenVideoError(f"busy: 영상 굽기는 한 번에 한 묶음 — 지금 {self._running} 이(가) 돌고 하나가 기다린다. 끝난 뒤 다시.")
        job_id = f"gv_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
        folder = self.out_root / job_id
        folder.mkdir(parents=True, exist_ok=False)
        job = Job(job_id, kind, engine, folder, width, height, tasks, **extra)
        self._jobs[job_id] = job
        self._queue.append(job_id)
        self._save(job)
        if self._running is None:
            self._start_next_locked()
        return job

    def submit_batch(self, board: dict[str, Any], *, engine: str = commands.DRAFT_ENGINE) -> str:
        """정리된 콘티(`storyboard.parse`) → 시안 묶음 job_id."""
        if engine not in commands.ENGINES:
            raise ValueError(f"engine 은 {list(commands.ENGINES)} 가운데 하나")
        problems = self.engine_problems(engine)
        if problems:
            raise GenVideoError("not_ready: " + " · ".join(problems))
        tasks: list[Task] = []
        skipped = []
        for cut in board["cuts"]:
            if cut["kind"] != "gen":
                skipped.append({"cut": cut["id"], "kind": cut["kind"], "note": cut.get("note") or ""})
                continue
            base = cut["seed"] if cut["seed"] is not None else secrets.randbelow(2**31 - 64)
            for k in range(cut["candidates"]):
                tasks.append(Task(cut["id"], k + 1, cut["prompt"], base + k, cut["frames"], cut["first_image"],
                                  f"{cut['id']}_{k + 1}_{engine}.webm", last_image=cut.get("last_image")))
        with self._lock:
            job = self._new_job_locked("batch", engine, board["width"], board["height"], tasks, title=board.get("title") or "",
                                       aspect=board["aspect"], board_notes=list(board.get("notes") or []), skipped_cuts=skipped)
        self._notify(job.job_id)
        return job.job_id

    def submit_finish(self, source_job: str, picks: list[dict[str, Any]], *, engine: str = "wan", anchor: bool = True) -> str:
        """고른 후보만 본판 엔진으로 다시 굽는다(같은 프롬프트 · 씨앗). LTX 는 기본으로 고른 시안의 첫 · 끝 프레임에 고정한다."""
        if engine not in commands.FINAL_ENGINES:
            raise ValueError(f"본판 engine 은 {list(commands.FINAL_ENGINES)} 가운데 하나")
        found = self._saved(source_job)
        if not found or found.get("kind") != "batch":
            raise GenVideoError(f"not_found: 시안 묶음 {source_job} 이(가) 없다")
        if not isinstance(picks, list) or not picks or len(picks) > 8:
            raise ValueError("picks 는 1~8개 — [{\"cut\": \"c1\", \"candidate\": 2}, …]")
        done = {(t["cut"], int(t["candidate"])): t for t in found.get("task_list") or [] if t.get("state") == "done"}
        tasks: list[Task] = []
        for pick in picks:
            key = (str((pick or {}).get("cut") or ""), int((pick or {}).get("candidate") or 0))
            if key not in done:
                raise GenVideoError(f"not_found: {key[0]} 후보 {key[1]} — 끝난 시안에 없다")
            if any((t.cut, t.candidate) == key for t in tasks):
                continue
            src = done[key]
            last = src.get("last_image")
            if last and engine != "ltx":
                # 사람이 준 끝 그림을 말없이 버리지 않는다 — Wan 은 끝 그림을 못 받는다(commands.build).
                raise GenVideoError(f"end_image_needs_ltx: {key[0]} 컷에 끝 그림({Path(last).name})이 있다 — "
                                    "끝 그림은 engine ltx 로만 굽는다(Wan 은 첫 그림까지만)")
            draft = self.out_root / source_job / str(src.get("out_name") or "")
            tasks.append(Task(key[0], key[1], src["prompt"], int(src["seed"]), int(src["frames"]), src.get("first_image"),
                              f"{key[0]}_{key[1]}_{engine}.webm", draft_file=str(draft) if draft.is_file() else None,
                              anchor=bool(anchor and engine == "ltx" and draft.is_file()), last_image=last))
        problems = self.engine_problems(engine)
        if problems:
            raise GenVideoError("not_ready: " + " · ".join(problems))
        with self._lock:
            job = self._new_job_locked("finish", engine, int(found["width"]), int(found["height"]), tasks,
                                       title=str(found.get("title") or ""), aspect=str(found.get("aspect") or "16:9"),
                                       source_job=source_job)
        self._notify(job.job_id)
        return job.job_id

    # ── 읽기 · 취소 · 파일 ──────────────────────────────────────────────
    def _saved(self, job_id: str) -> dict[str, Any] | None:
        if not valid_job_id(job_id):
            return None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job.saved()
        path = self.out_root / job_id / "job.json"
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return None

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not valid_job_id(job_id):
            return None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job.public()
        found = self._saved(job_id)
        if found is None:
            return None
        return {key: found.get(key) for key in ("job_id", "kind", "engine", "state", "progress", "done_tasks", "tasks", "receipt", "error")}

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in {"queued", "running"}:
                return False
            job.cancel_requested = True
            if job.state == "queued" and job_id in self._queue:
                self._queue.remove(job_id)
                job.state, job.error = "failed", "cancelled"
                for task in job.tasks:
                    task.state = "cancelled"
                job.receipt = self._job_receipt(job)
                self._save(job)
                return True
            process = job.process
        if process is not None:
            try:
                process.kill()
            except Exception:  # noqa: BLE001, S110
                pass
        return True

    def shutdown(self) -> None:
        with self._lock:
            ids = [self._running, *self._queue]
        for job_id in ids:
            if job_id:
                self.cancel(job_id)

    def file_for(self, job_id: str, name: str) -> Path | None:
        """영수증 files 에 있는 이름만, 그 판 폴더 안에서만(경로 빠져나가기 막기 — 3D 와 같은 규칙)."""
        if not valid_job_id(job_id) or not name or Path(name).name != name or name in {".", ".."}:
            return None
        receipt = (self.get(job_id) or {}).get("receipt") or {}
        listed: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, str) and value:
                listed.add(Path(value).name)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)

        walk(receipt.get("files") or {})
        if name not in listed:
            return None
        home = (self.out_root / job_id).resolve()
        target = (home / name).resolve()
        if not target.is_relative_to(home) or not target.is_file():
            return None
        return target

    # ── 돌리기 ──────────────────────────────────────────────────────────
    def _notify(self, job_id: str) -> None:
        callback = self.on_change
        if callback is not None:
            try:
                callback(job_id)
            except Exception:  # noqa: BLE001, S110
                pass

    def _start_next_locked(self) -> None:
        if not self._queue:
            self._running = None
            return
        job_id = self._queue.pop(0)
        self._running = job_id
        threading.Thread(target=self._run, args=(self._jobs[job_id],), name=f"genvideo-{job_id}", daemon=True).start()

    def _pick_card(self, cards: list[dict] | None = None) -> dict[str, Any] | None:
        cards = self._gpus() if cards is None else cards
        if self.gpu_pin is not None:
            found = next((c for c in cards if int(c["index"]) == int(self.gpu_pin)), None)
            return {**(found or {"index": int(self.gpu_pin)}), "auto": False}
        if not cards:
            return None
        best = max(cards, key=lambda c: c["free_mib"])
        return {**best, "auto": True}

    def _note_slot_wait(self, job: Job, holders: list[str]) -> None:
        """한 줄 잠금을 기다리기 시작할 때 — 상태에 「무엇을 기다리나」를 보인다(잡으면 `_wait_if_busy` 가 지운다)."""
        job.waiting_busy = "한 줄 대기: " + (" · ".join(holders) or "다른 무거운 일")
        self._notify(job.job_id)

    def _wait_if_busy(self, job: Job) -> float:
        """사람이 손자리를 쓰는 중이면 기다린다. 기다린 초를 돌려준다. 최대를 넘기면 GenVideoError."""
        waited = 0.0
        while True:
            busy = self.busy_now()
            if not busy:
                if job.waiting_busy:
                    job.waiting_busy = None
                    self._notify(job.job_id)
                return round(waited, 1)
            if job.cancel_requested:
                return round(waited, 1)
            if waited >= self._busy_max:
                raise GenVideoError(f"busy_too_long: {', '.join(busy)} 이(가) {int(waited)}초 동안 일하는 중이라 굽기를 멈췄다")
            if job.waiting_busy != ", ".join(busy):
                job.waiting_busy = ", ".join(busy)
                self._notify(job.job_id)
            self._sleep(self._busy_poll)
            waited += self._busy_poll

    def _memory(self) -> dict[str, Any]:
        from ..pack_ram import memory_status

        try:
            return dict((self._memory_probe or memory_status)())
        except Exception:  # noqa: BLE001 — 못 재면 모른다
            return {"free_mib": None, "commit_share": None}

    def _ram_check(self) -> dict[str, Any]:
        """「이 PC 로 되나」의 램 칸 — 클로드가 굽기 전에 「언어 모델을 잠시 내린다」를 사람에게 말할 수 있게(11-17)."""
        from ..pack_ram import VIDEO_NEED_MIB, should_unload, unload_disabled

        status = self._memory()
        unload, why = should_unload(VIDEO_NEED_MIB, status, disabled=unload_disabled())
        return {**status, "need_mib": VIDEO_NEED_MIB, "will_unload_text_model": unload, "why": why}

    def _unload_if_single_card(self, job: Job, cards: list[dict]) -> None:
        """굽기 직전 글 모델 내리기 — 카드가 하나(같은 카드를 나눔)이거나 **램이 모자라면**(카드가 둘이어도 · 11-17 `pack_ram`)."""
        if self.text_models is None:
            return
        from ..pack_ram import VIDEO_NEED_MIB, should_unload, unload_disabled

        status = self._memory()
        ram_unload, why = should_unload(VIDEO_NEED_MIB, status, disabled=unload_disabled())
        job.ram = {**status, "need_mib": VIDEO_NEED_MIB, "unload": ram_unload, "why": why}
        if len(cards) != 1 and not ram_unload:
            return
        try:
            names = [row["name"] for row in self.text_models.loaded()]
        except Exception:  # noqa: BLE001
            names = []
        if not names:
            return
        try:
            left = list(self.text_models.unload(names))
        except Exception:  # noqa: BLE001
            left = list(names)
        job.not_unloaded = left
        job.unloaded = [n for n in names if n not in left]
        job.unload_reason = "card" if len(cards) == 1 else "ram"
        if job.unloaded:
            from ..pack_ram import note_unloaded

            note_unloaded()

    def _env(self, job: Job, exe: Path) -> dict[str, str]:
        env = dict(os.environ)
        if job.gpu is not None:
            env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            env["CUDA_VISIBLE_DEVICES"] = str(job.gpu)
        # cudart DLL 묶음은 따로 받은 폴더에 있다 — 실행기 폴더와 같이 PATH 앞에 붙인다.
        extra = [str(exe.parent), *[str(p) for p in self.bin_dirs if p and Path(p).is_dir()]]
        env["PATH"] = os.pathsep.join([*dict.fromkeys(extra), env.get("PATH", "")])
        return env

    def _run(self, job: Job) -> None:
        # 굽는 동안 「무거운 일 중」 — 앞부분 데우기가 내린 언어 모델을 도로 올리지 않게(11-17 · `pack_ram.heavy_work`).
        from ..pack_ram import heavy_work

        with heavy_work():
            self._run_inner(job)

    def _run_inner(self, job: Job) -> None:
        from ..pack_ram import heavy_slot

        job.started_at = time.time()
        with self._lock:
            job.state = "running"
        self._notify(job.job_id)
        try:
            cards = self._gpus()
            pick = self._pick_card(cards)
            if pick is not None:
                job.gpu, job.gpu_pick = int(pick["index"]), pick
            self._unload_if_single_card(job, cards)
            exe = self.exe()
            files = self.files()
            if exe is None:
                raise GenVideoError("not_ready: 실행기(sd-cli)가 없다")
            for index, task in enumerate(job.tasks):
                if job.cancel_requested:
                    break
                job.current = index
                # 한 줄 잠금(11-18 · 설계 `설계_블렌더공통층_워크플로우` §14-2): 맥에서는 3D 굽기 · 블렌더 일과 한 줄. 컷마다 잡고 놓는다.
                with heavy_slot("영상 굽기", wait=True, on_wait=lambda holders: self._note_slot_wait(job, holders)) as slot:
                    self._run_task(job, task, exe, files)
                if task.receipt is not None and slot.get("one_line"):
                    task.receipt["slot_wait_sec"] = slot.get("busy_wait_sec")
                self._save(job)
                if task.state == "failed" and (task.receipt or {}).get("error", "").startswith("busy_too_long"):
                    break
        except Exception as exc:  # noqa: BLE001 — 실패도 영수증으로
            job.error = job.error or f"run_failed: {exc}"
        for task in job.tasks:
            if task.state in {"queued", "running"}:
                task.state = "cancelled" if job.cancel_requested else "skipped"
        job.ended_at = time.time()
        job.current = None
        job.waiting_busy = None
        if job.cancel_requested:
            job.error = "cancelled"
        elif job.error is None and not any(t.state == "done" for t in job.tasks):
            job.error = "all_failed: " + " | ".join(str((t.receipt or {}).get("error") or "") for t in job.tasks)[:600]
        try:
            job.receipt = self._job_receipt(job)
        except Exception as exc:  # noqa: BLE001
            job.error = job.error or f"receipt_failed: {exc}"
        with self._lock:
            job.state = "done" if job.error is None else "failed"
            self._save(job)
            self._start_next_locked()
        self._notify(job.job_id)

    def _run_task(self, job: Job, task: Task, exe: Path, files: dict[str, Path]) -> None:
        task.state = "running"
        job.tracker = VideoTracker()
        out = job.folder / task.out_name
        log_path = job.folder / (Path(task.out_name).stem + ".log")
        receipt: dict[str, Any] = {"cut": task.cut, "candidate": task.candidate, "seed": task.seed, "engine": job.engine,
                                   "frames": task.frames, "size": [job.width, job.height]}
        try:
            receipt["busy_wait_sec"] = self._wait_if_busy(job)
        except GenVideoError as exc:
            task.state, receipt["error"] = "failed", str(exc)
            task.receipt = receipt
            return
        if job.cancel_requested:
            task.state = "cancelled"
            return
        # 끝 그림: 콘티가 준 것(LTX 만 — 시안 FastWan 은 첫 그림까지만 받는다).
        given_end = task.last_image if job.engine == "ltx" else None
        first_image, end_image = task.first_image, given_end
        if given_end:
            receipt["end_image"] = Path(given_end).name
        if task.anchor and task.draft_file:
            # 처음·끝 고정: 고른 시안의 첫 · 끝 프레임을 판 폴더에 뽑아 -i · --end-img 로(못 뽑으면 고정 없이 가고 영수증에 남긴다).
            stem = Path(task.out_name).stem
            grabbed = self._grab_ends(Path(task.draft_file), job.folder / f"{stem}_first.png", job.folder / f"{stem}_last.png")
            if grabbed:
                first_image, end_image = grabbed[0], given_end or grabbed[1]  # 사람이 준 끝 그림이 시안의 끝 프레임보다 앞선다
                receipt["anchor"] = {"first": Path(first_image).name, "last": Path(end_image).name}
            else:
                receipt["anchor"] = {"error": "시안의 첫 · 끝 프레임을 못 뽑아 고정 없이 구웠다"}
        sigmas = commands.LTX_DISTILLED_SIGMAS if (job.engine == "ltx" and LTX_SIGMAS_ON) else None
        if sigmas:
            receipt["sigmas"] = "ltx_distilled"
        cmd = commands.build(job.engine, exe, files, prompt=task.prompt, out=out, width=job.width, height=job.height,
                             frames=task.frames, seed=task.seed, first_image=first_image, end_image=end_image, sigmas=sigmas)
        base = self._vram(job.gpu)
        peak = [base]
        stop = threading.Event()

        def poll() -> None:
            seen: tuple[Any, ...] = ()
            while not stop.wait(self._poll_sec):
                used = self._vram(job.gpu)
                if used is not None and (peak[0] is None or used > peak[0]):
                    peak[0] = used
                current = job.tracker.current() or {}
                mark = (current.get("index"), (current.get("sub") or {}).get("done"))
                if mark != seen:
                    seen = mark
                    self._notify(job.job_id)

        poller = threading.Thread(target=poll, daemon=True)
        poller.start()
        started = time.time()
        rc: int | None = None
        timed_out = threading.Event()
        try:
            with open(log_path, "wb") as log:
                process = self._popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                      cwd=str(exe.parent), env=self._env(job, exe), creationflags=_NO_WINDOW)
                job.process = process
                # 본체의 낮은 순위(메모리 2 · 디스크 1)를 물려받지 않게 — 11-17 시안 400초 → 32초의 뿌리(`pack_ram.lift_to_normal`).
                from ..pack_ram import lift_to_normal

                lifted = lift_to_normal(process)
                if lifted is not None:
                    receipt["priority"] = lifted
                if job.cancel_requested:
                    process.kill()

                def on_timeout() -> None:
                    timed_out.set()
                    try:
                        process.kill()
                    except Exception:  # noqa: BLE001, S110
                        pass

                watchdog = threading.Timer(RUN_TIMEOUT_SEC, on_timeout)
                watchdog.daemon = True
                watchdog.start()
                rest = ""
                try:
                    while True:
                        chunk = process.stdout.read1(4096) if hasattr(process.stdout, "read1") else process.stdout.read(4096)
                        if not chunk:
                            break
                        log.write(chunk)
                        lines, rest = split_lines(rest + chunk.decode("utf-8", "replace"))
                        for line in lines:
                            job.tracker.feed(line)
                            if "loading tensors completed" in line:
                                job.tracker.begin_text()
                    if rest:
                        job.tracker.feed(rest)
                    rc = process.wait(timeout=30)
                finally:
                    watchdog.cancel()
        except Exception as exc:  # noqa: BLE001
            receipt["error"] = f"run_failed: {exc}"
        finally:
            stop.set()
            poller.join(timeout=3)
            job.process = None
            job.tracker.finish()
        receipt.update({"sec": round(time.time() - started, 1), **job.tracker.numbers(), "vram_base_mib": base,
                        "vram_peak_mib": peak[0], "log": log_path.name})
        if job.cancel_requested:
            task.state, receipt["error"] = "cancelled", "cancelled"
        elif timed_out.is_set():
            task.state, receipt["error"] = "failed", f"timeout: {RUN_TIMEOUT_SEC}초를 넘겨 멈췄다"
        elif "error" not in receipt and rc == 0 and out.is_file() and out.stat().st_size > 0:
            task.state = "done"
            receipt["file"] = out.name
            receipt["check"] = self._check_clip(out, job.folder / (Path(task.out_name).stem + "_sheet.png"),
                                                label=f"{task.cut} #{task.candidate}  seed {task.seed}  {job.engine}")
            if task.draft_file:
                receipt["drift"] = self._drift(out, Path(task.draft_file))
        else:
            task.state = "failed"
            last = job.tracker.error_summary() or (job.tracker.tail[-1] if job.tracker.tail else "")
            where = job.tracker.current() or {}
            stage = where.get("name") or "시작 전"
            if (where.get("sub") or {}).get("total"):
                stage += f" {where['sub']['done']}/{where['sub']['total']}"
            if job.tracker.out_of_memory:
                receipt["error"] = receipt.get("error") or (
                    f"gpu_out_of_memory: 그래픽카드 메모리가 모자라 멈췄다 — 멈춘 자리 {stage} · 시작 때 카드 사용 {base}MiB · "
                    f"잰 최대 {peak[0]}MiB(1초마다 재서 순간 최대는 놓칠 수 있다). 같은 카드를 다른 프로그램이 쓰는지 보고 다시")
            else:
                receipt["error"] = receipt.get("error") or f"exit_{rc}: 실행기가 끝까지 못 갔다 — 멈춘 자리 {stage} · 오류: {last[:300]}"
        task.receipt = receipt

    def _grab_ends(self, clip: Path, first: Path, last: Path) -> tuple[str, str] | None:
        grab = self._grab
        if grab is None:
            from .inspect import grab_ends as grab
        try:
            return grab(clip, first, last)
        except Exception:  # noqa: BLE001 — 못 뽑으면 고정 없이 간다
            return None

    def _drift(self, final: Path, draft: Path) -> dict[str, Any]:
        """본판 ↔ 고른 시안 어긋남(같은 상대 시각의 16×9 색 격자 평균 차). 기준은 DRIFT_* 주석."""
        fn = self._drift_fn
        if fn is None:
            from .inspect import drift as fn
        try:
            found = fn(final, draft)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "why": f"어긋남 검사 실패: {exc}"[:200]}
        mean = found.get("mean")
        if mean is None:
            return found
        flag = "drift" if mean >= DRIFT_FLAG_MIN else ("kept" if mean <= DRIFT_KEPT_MAX else "unclear")
        advice = {"drift": "시안과 다른 장면이 됐다 — 다시 굽거나 시안을 그대로 쓴다", "kept": "시안 장면을 지켰다",
                  "unclear": "숫자로 못 가른다 — 장면 판을 본다"}[flag]
        return {**found, "flag": flag, "advice": advice, "kept_max": DRIFT_KEPT_MAX, "flag_min": DRIFT_FLAG_MIN}

    def _check_clip(self, clip: Path, sheet: Path, *, label: str) -> dict[str, Any]:
        inspect_fn = self._inspect
        if inspect_fn is None:
            from .inspect import inspect as inspect_fn
        try:
            found = inspect_fn(clip, sheet, label=label)
        except Exception as exc:  # noqa: BLE001 — 검사는 덤 — 실패해도 영상은 남는다
            return {"ok": False, "why": f"검사 실패: {exc}"[:300]}
        if found.get("sheet"):
            found["sheet"] = Path(found["sheet"]).name
        return found

    # ── 영수증 ──────────────────────────────────────────────────────────
    def _pick_sheet(self, job: Job) -> Path | None:
        """고르기 판: 줄 = 컷 · 칸 = 후보, 칸마다 그 후보의 장면 사진 판을 줄여 넣는다."""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return None
        rows: dict[str, list[Task]] = {}
        for task in job.tasks:
            if task.state == "done" and (task.receipt or {}).get("check", {}).get("sheet"):
                rows.setdefault(task.cut, []).append(task)
        if not rows:
            return None
        cell_w = 384
        images: dict[tuple[str, int], Any] = {}
        cell_h = 0
        for cut, tasks in rows.items():
            for task in tasks:
                with Image.open(job.folder / task.receipt["check"]["sheet"]) as image:
                    ratio = cell_w / image.width
                    small = image.convert("RGB").resize((cell_w, int(image.height * ratio)))
                images[(cut, task.candidate)] = small
                cell_h = max(cell_h, small.height)
        cols = max(len(tasks) for tasks in rows.values())
        pad = 20
        sheet = Image.new("RGB", (cols * cell_w, len(rows) * (cell_h + pad)), (12, 12, 12))
        draw = ImageDraw.Draw(sheet)
        for r, (cut, tasks) in enumerate(rows.items()):
            for c, task in enumerate(tasks):
                x, y = c * cell_w, r * (cell_h + pad)
                # 영문 · 숫자만 — PIL 기본 글꼴에 한글이 없어 「후보」가 네모로 깨졌다(11-16 홍보 초안 판).
                draw.text((x + 6, y + 4), f"{cut} #{task.candidate}  seed {task.seed}", fill=(235, 235, 235))
                sheet.paste(images[(cut, task.candidate)], (x, y + pad))
        out = job.folder / "pick_sheet.png"
        sheet.save(out)
        return out

    def _job_receipt(self, job: Job) -> dict[str, Any]:
        runs = [t.receipt or {"cut": t.cut, "candidate": t.candidate, "seed": t.seed, "state": t.state} for t in job.tasks]
        for task, run in zip(job.tasks, runs):
            run["state"] = task.state
        done = [t for t in job.tasks if t.state == "done"]
        files: dict[str, Any] = {"clips": [t.receipt["file"] for t in done],
                                 "sheets": [t.receipt["check"]["sheet"] for t in done if (t.receipt.get("check") or {}).get("sheet")],
                                 "logs": [r["log"] for r in runs if r.get("log")]}
        if job.kind == "batch" and done:
            made = self._pick_sheet(job)
            if made:
                files["pick_sheet"] = made.name
        peaks = [r.get("vram_peak_mib") for r in runs if r.get("vram_peak_mib") is not None]
        sample = [r.get("sample_sec") for r in runs if r.get("sample_sec") is not None]
        measured = {
            "sec": round((job.ended_at or time.time()) - (job.started_at or time.time()), 1) if job.started_at else 0.0,
            "done": len(done), "failed": sum(1 for t in job.tasks if t.state == "failed"),
            "cancelled_or_skipped": sum(1 for t in job.tasks if t.state in {"cancelled", "skipped"}),
            "sample_sec_sum": round(sum(sample), 1) if sample else None,
            "busy_wait_sec_sum": round(sum(r.get("busy_wait_sec") or 0 for r in runs), 1),
            "vram_peak_mib": max(peaks) if peaks else None,
            "memory_what": f"그래픽카드 전체 사용량(nvidia-smi · 카드 {job.gpu}) — 다른 프로그램 몫 포함",
            "gpu_pick": job.gpu_pick,
            #: 굽기 직전 램 판정 · 내린 글 모델(11-17 · `pack_ram`) — 느렸을 때 램 탓인지 가르는 근거.
            "ram": job.ram,
            "text_models_unloaded": list(job.unloaded),
        }
        not_done = [
            "키우기(RelayVSR)는 하지 않았다 — 12GB 카드에서 안 됨(§10-10)",
            "글자 · 로고 · 앱 화면은 굽지 않는다 — code 컷으로 합성(HyperFrames/리모션)",
        ]
        if job.kind == "batch":
            not_done.append("시안은 빠른 풀기(taew2_2)라 잔결이 조금 뭉갠다 — 본판은 gen_video_finish")
        if job.kind == "finish":
            not_done.append("본판은 같은 프롬프트 · 씨앗 · 첫 그림으로 다시 구웠다(그린 결과 재사용 기능이 실행기에 없음) — 엔진이 달라 시안과 모양 · 움직임이 다를 수 있다. 장면 사진 판으로 다시 본다")
        if job.engine == "ltx":
            not_done.append("소리는 숫자(평균 dB)만 쟀다 — 내용은 사람이 들어 봐야 한다")
            not_done.append("LTX 로 만든 영상은 내보낼 때 「AI 생성」이라고 밝힌다(LTX-2.x 커뮤니티 라이선스 첨부 A-5)")
        if job.skipped_cuts:
            not_done.append("굽지 않은 컷(code · 3d): " + ", ".join(f"{s['cut']}({s['kind']})" for s in job.skipped_cuts))
        if job.unloaded:
            if job.unload_reason == "ram":
                from ..pack_ram import unload_note

                not_done.append(unload_note(job.unloaded, (job.ram or {}).get("why") or "램 부족"))
            else:
                not_done.append(f"카드가 하나라 굽기 전에 글 모델을 내렸다({', '.join(job.unloaded)}) — 다음 질문 때 다시 올라온다")
        elif job.ram and job.ram.get("why") and not job.ram.get("unload"):
            not_done.append(job.ram["why"])
        if job.not_unloaded:
            not_done.append(f"글 모델을 다 내리지 못했다({', '.join(job.not_unloaded)})")
        for run in runs:
            if run.get("error"):
                not_done.append(f"{run['cut']} 후보 {run['candidate']}: {run['error']}"[:400])
        return {
            "did": (f"시안 {len(done)}/{len(job.tasks)}개 · {job.engine}" if job.kind == "batch"
                    else f"본판 {len(done)}/{len(job.tasks)}개 · {job.engine}"),
            "files": files,
            "runs": runs,
            "measured": measured,
            "notes": list(job.board_notes),
            "not_done": not_done,
            "model": commands.model_block(job.engine, self.files()),
            **({"source_job": job.source_job} if job.source_job else {}),
        }

    def _save(self, job: Job) -> None:
        try:
            (job.folder / "job.json").write_text(json.dumps(job.saved(), ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

