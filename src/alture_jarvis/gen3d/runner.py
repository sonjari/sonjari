"""그림 한 장 → 3D 초안. trellis.cpp(`trellis-cli.exe`)를 따로 떼어 낸 프로세스로 부른다 (2026-11-14 · 설계 §3-1 · §3-9).

- 한 번에 한 일. 대기열은 하나 — 도는 것 하나 + 기다리는 것 하나까지, 그 위는 거절(그래픽카드 한 장을 둘이 나눠 쓰면 둘 다 느려진다).
- 진행은 로그의 `[n/7]` 줄(분모는 믿지 않음 · `progress.py`)로 실시간 갱신, 단계 안 비율(5/12)도 싣는다. 실행기의 「남은 시간」은 안 싣는다.
- 그래픽카드 메모리는 `nvidia-smi` 를 1초마다 — 카드 전체 사용량이라 시작 값(`vram_base_mib`)을 같이 남긴다(다른 프로그램 몫).
- **맥(2026-11-14):** 실행기는 Metal 판(`trellis-cli` · 직접 빌드), `gpu` 는 무시(카드 하나 · 메모리 하나). 메모리는 통합 메모리
  전체 사용량 + 실행기 자신의 최대 실메모리(`memory.py`). 굽기 전에 남은 메모리를 재서 모자라면 `not_ready` 로 거절하고,
  이 기기 Ollama 에 올라간 글 모델은 내린 뒤 굽는다(`swap.py` · 화면 「모델 갈아타기」 알림 unload → load → ready).
- 끝나면 GLB 를 직접 열어 면 수 · 크기 · 닫힌 메시를 재고, 미리보기 webp 둘(앞 · 옆), 요청하면 STL · 3MF.
- 영수증 숫자는 손자리 코드가 잰 것만(설계 §3-1). 실패도 영수증 — 어느 단계에서 멈췄나 · 로그 끝 몇 줄.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .memory import gpu_used_mib, memory_what, pick_gpu, proc_peak_mib, unified_free_mib, unified_total_mib, unified_used_mib
from .progress import StageTracker, split_lines

MODELS = {"trellis": "trellis2", "pixal3d": "pixal3d"}
RESOLUTIONS = (512, 1024)
EXPORTS = ("glb", "stl", "3mf")
#: 프린트 크기(긴 변 mm). 기본 100mm — 실험 기록의 첫 시험 계획(배 10cm)과 같다.
DEFAULT_SIZE_MM = 100.0
DETAILS = ("auto", "fine", "fast")


def check_print_options(printer: str | None, detail: str | None, orientation: str | None) -> None:
    """프린트 설정 검사(만들기 · 다시 준비가 같이 쓴다). 모르는 값은 지어 넣지 않고 거절한다."""
    from .print_plan import ORIENTATIONS
    from .slicer import SUPPORTED_PRINTERS

    if printer and printer not in SUPPORTED_PRINTERS:
        raise ValueError(f"printer 는 {list(SUPPORTED_PRINTERS)} 가운데 하나")
    if detail and detail not in DETAILS:
        raise ValueError(f"detail 은 {list(DETAILS)} 가운데 하나")
    if orientation and orientation not in ORIENTATIONS:
        raise ValueError(f"orientation 은 {list(ORIENTATIONS)} 가운데 하나")
SIZE_MM_RANGE = (5.0, 400.0)
#: 한 판의 상한(초). 실측 최장은 1024 · 3060 762초(실험 기록 w2) — 넉넉히 두 배 반.
RUN_TIMEOUT_SEC = 1800
#: 색 대조 검사로 다시 굽는 최대 횟수(11-16 밤) — 판 하나 약 2분이라 두 번까지.
COLOR_RETRIES = 2


def _logged_seed(log_path: Path) -> int | None:
    """실행기 기록 첫 줄의 씨앗(「seed 539808391 (auto)」) — 못 읽으면 None."""
    import re

    try:
        head = log_path.read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        return None
    found = re.search(r"seed (\d+)", head)
    return int(found.group(1)) if found else None
_JOB_ID = re.compile(r"^g3_[0-9]{8}_[0-9]{6}_[0-9a-f]{6}$")
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

#: 맥(통합 메모리)에서 한 판이 쓰는 메모리 어림(MiB) — 굽기 전에 이만큼 남아 있어야 시작한다.
#: 512: 11-14 맥 미니 M4 16GB 실측 두 판의 실행기 최대 실메모리(ri_lifetime_max_phys_footprint) 중 큰 값 — 배 3,980 ·
#:      캐릭터 5,384(배경 지우기가 돎) — 에 여유 1.5GB. n=2 라 판이 쌓이면 다시 본다.
#: 1024: 맥에서 아직 안 쟀다 — 16GB 기계에서는 막고(`MAC_1024_MIN_TOTAL_MIB` 미만), 더 큰 기계는 512 의 두 배로 어림.
#:      (윈도우 3060 실측: 1024 가 512 의 약 1.6배 카드 메모리 · 6,616MiB.)
MAC_512_PEAK_MIB = 5384
MAC_NEED_MIB = {512: MAC_512_PEAK_MIB + 1536, 1024: MAC_512_PEAK_MIB * 2 + 1536}
MAC_1024_MIN_TOTAL_MIB = 24 * 1024
#: 화면 「모델 갈아타기」의 3D 쪽 이름.
SWAP_TO = "TRELLIS.2"


def _floor(value: Any) -> float | None:
    """바닥 자르기 mm(0~30) — 비우면 None(내 프린터 설정을 따름)."""
    if value in (None, ""):
        return None
    v = float(value)
    if not 0.0 <= v <= 30.0:
        raise ValueError("floor_cut_mm 은 0~30")
    return v


def _read_stl(path: Path) -> tuple[Any, Any]:
    """우리가 쓴 이진 STL(write_stl) 읽기 — 삼각형마다 꼭짓점 셋(이어 붙이지 않음)."""
    import numpy as np

    raw = path.read_bytes()
    n = int.from_bytes(raw[80:84], "little")
    tri = np.frombuffer(raw[84:84 + n * 50], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))["v"]
    pos = tri.reshape(-1, 3).astype(np.float64)
    return pos, np.arange(len(pos), dtype=np.int64).reshape(-1, 3)


#: 블렌더 마무리 작업과 받는 칸(`blender_scripts/finish.py` 와 같아야 한다 — 시험이 맞춰 본다).
FINISH_OPS: dict[str, set[str]] = {
    "smooth_surface": {"rounds", "box"},
    "erase_fill": {"box", "rounds"},
    "erase_part": {"box", "min_inside"},
    "drop_loose": {"max_share"},
    "symmetrize": {"keep"},
    "smooth": {"box", "rounds"},
}
#: 겉면 펴기 기본 횟수 — 11-15 테디 · 개구리 그림 대조(30번은 입선 · 눈 · 털결까지 지움 · 8번이 절충 · n=2 · 그림으로만).
SMOOTH_SURFACE_ROUNDS = 8


def _valid_box(box: Any) -> bool:
    try:
        return (len(box["center"]) == 3 and len(box["axes"]) == 3 and all(len(a) == 3 for a in box["axes"])
                and len(box["half"]) == 3 and all(float(h) > 0 for h in box["half"]))
    except (KeyError, TypeError, ValueError):
        return False


def _finish_line(item: dict[str, Any]) -> str:
    """블렌더 결과 한 칸 → 한국어 한 줄(숫자는 결과에 있는 것만)."""
    op = item.get("op")
    if op == "smooth_surface":
        if item.get("note"):
            return f"겉면 펴기 {item.get('rounds')}번 — {item['note']}"
        move = item.get("move_mm") or {}
        vol = item.get("volume_change_pct")
        return (f"겉면 펴기 {item.get('rounds')}번(꼭짓점 {item.get('verts')}개) — 꼭짓점 이동 중앙값 {move.get('median')}mm · "
                f"95% {move.get('p95')}mm · 최대 {move.get('max')}mm(긴 변 {move.get('long_side_mm')}mm 로 놓고) · "
                f"부피 {'잴 수 없음' if vol is None else f'{vol:+}%'}")
    if op == "erase_fill":
        return f"상자 안 지우고 메움 — 꼭짓점 {item.get('erased_verts')}개 지움 · 메운 면 {item.get('filled_faces')}"
    if op == "erase_part":
        return f"떨어진 조각 지움 — {item.get('erased_parts')}개"
    if op == "drop_loose":
        return f"작은 덩이 지움 — {item.get('dropped_parts')}개"
    if op == "symmetrize":
        return f"좌우 맞춤 — {item.get('keep')} 쪽을 반대로 덮음"
    if op == "smooth":
        return f"상자 안 잔물결 펴기 — 꼭짓점 {item.get('verts')}개"
    return str(op)


def _finish_not_done(items: list[dict[str, Any]]) -> list[str]:
    notes = []
    if any(item.get("op") == "smooth_surface" for item in items):
        notes.append("줄무늬가 얼마나 줄었는지는 숫자로 재지 않았다(맞는 잣대가 아직 없다) — before_after 판을 눈으로 본다")
        notes.append("입선 · 눈 새김 · 털결 같은 작은 새김이 남았는지도 판으로만 안다")
        if any(item.get("op") == "smooth_surface" and item.get("volume_closed") is False for item in items):
            notes.append("열린 메시(구멍 있음)라 부피 변화는 어림값이다")
    return notes


class Gen3DError(RuntimeError):
    pass


def valid_job_id(job_id: str) -> bool:
    return bool(_JOB_ID.fullmatch(str(job_id or "")))


def find_exe(bin_dir: Path, platform: str | None = None) -> Path | None:
    """실행기 자리. 풀어 둔 zip 이 하위 폴더(`cuda/` 등)를 하나 더 가질 수 있어 한 칸 아래까지 본다.

    이름은 플랫폼마다(윈도우 `trellis-cli.exe` · 맥 `trellis-cli`). 맥에 받아진 윈도우 판(.exe)은 실행기로 치지 않는다.
    """
    name = "trellis-cli.exe" if (platform or sys.platform) == "win32" else "trellis-cli"
    for candidate in (bin_dir / name, *sorted(bin_dir.glob(f"*/{name}"))):
        if candidate.is_file():
            return candidate
    return None


def models_ready(models_dir: Path) -> list[str]:
    """빠진 모델 파일(실측 q8 폴더의 512 판에 꼭 있는 것들). 빈 목록이면 됐다."""
    need = ["birefnet.gguf", "dinov3.gguf", "ss_flow.gguf", "ss_dec.gguf", "shape_dec.gguf", "tex_dec.gguf"]
    return [name for name in need if not (models_dir / name).is_file()]


def _precision(models_dir: Path) -> str:
    name = models_dir.name.lower()
    for tag in ("q8", "q4", "f16", "bf16"):
        if tag in name:
            return tag
    return "알 수 없음"


def vram_used_mib(gpu: int | None) -> int | None:
    """이 기계의 메모리 재기 — 윈도우는 그 카드(nvidia-smi), 맥은 통합 메모리 전체(카드 번호 무시)."""
    return unified_used_mib(gpu) if sys.platform == "darwin" else gpu_used_mib(gpu)


@dataclass
class Job:
    job_id: str
    folder: Path
    image: Path
    res: int
    model: str
    seed: int | None
    gpu: int | None
    export: list[str]
    size_mm: float
    state: str = "queued"
    #: 프린트 설정(11-14 폐루프) — 비우면 「내 프린터」(환경 설정) · 기본 세밀도 · 지금 방향.
    printer: str | None = None
    detail: str = "auto"
    orientation: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    tracker: StageTracker = field(default_factory=StageTracker)
    receipt: dict[str, Any] | None = None
    error: str | None = None
    vram_base: int | None = None
    vram_peak: int | None = None
    vram_now: int | None = None
    #: 무대가 띄울 넣은 그림(판 폴더 안 사본 이름 · 11-14 무대).
    input_name: str = ""
    #: 화면 「모델 갈아타기」 — {"from", "to", "phase": unload|load|ready, "from_mib", "expected_mib"}.
    swap: dict[str, Any] | None = None
    #: 맥: 굽기 직전 남은 메모리 · 실행기 자신의 최대 실메모리 · 내린 글 모델.
    free_before: int | None = None
    proc_peak: int | None = None
    unloaded: list[str] = field(default_factory=list)
    not_unloaded: list[str] = field(default_factory=list)
    cancel_requested: bool = False
    process: Any = None
    #: 카드를 손자리가 골랐을 때 {index, name, free_mib, total_mib, auto}(11-15).
    gpu_pick: dict[str, Any] | None = None
    floor_cut_mm: float | None = None
    #: 프린트 준비 안쪽 단계(11-15) — {name, sec, info, phase, steps}
    print_step: dict[str, Any] | None = None
    #: 색 대조 검사로 다시 구운 횟수 · 앞 판들(11-16 밤 · `color_check`) — [{try, seed, glb, color}].
    color_try: int = 0
    color_tries: list[dict[str, Any]] = field(default_factory=list)
    #: 한 줄 잠금(`pack_ram.heavy_slot`)을 기다린 초 — 굽는 시간과 따로 센다(사고 S).
    slot_wait_sec: float = 0.0
    #: 굽기 직전 램 판정(11-17 · 윈도우 · `pack_ram`) — {free_mib, commit_share, need_mib, unload, why}.
    ram: dict[str, Any] | None = None
    #: 실행기를 「보통」 순위로 올린 뒤 순위(11-17 · `pack_ram.lift_to_normal`) — {cpu_class, memory, io}.
    priority: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        stage = self.tracker.current() if self.state == "running" else None
        return {
            "job_id": self.job_id, "state": self.state, "stage": stage,
            "stages": list(self.tracker.stages), "receipt": self.receipt, "error": self.error,
            "res": self.res, "image": self.input_name or None, "vram_mib": self.vram_now, "swap": self.swap,
            "print_step": self.print_step if self.state == "running" else None,
        }


class Gen3DRunner:
    def __init__(
        self,
        out_root: Path,
        bin_dir: Path,
        models_dir: Path,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
        vram_probe: Callable[[int | None], int | None] = vram_used_mib,
        poll_sec: float = 1.0,
        platform: str | None = None,
        free_probe: Callable[[], int | None] = unified_free_mib,
        total_probe: Callable[[], int | None] = unified_total_mib,
        proc_probe: Callable[[int | None], int | None] = proc_peak_mib,
        text_models: Any = None,
        gpu_picker: Callable[[], dict | None] | None = None,
        memory_probe: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._memory_probe = memory_probe
        #: `sys.platform` 꼴. 시험은 "darwin" · "win32" 를 넣어 두 갈래를 다 본다.
        self.platform = platform or sys.platform
        self._free = free_probe
        self._total = total_probe
        self._proc = proc_probe
        #: 이 기기의 글 모델(`swap.LocalTextModels`) — 맥에서만 꽂는다. 없으면 내릴 것이 없다(윈도우 · 위성).
        self.text_models = text_models
        self._poll_sec = float(poll_sec)
        self.out_root = Path(out_root)
        self.bin_dir = Path(bin_dir)
        self.models_dir = Path(models_dir)
        self._popen = popen
        self._vram = vram_probe
        #: 카드 고르기 — 시험은 가짜를 꽂는다. 기본은 nvidia-smi(남은 메모리가 가장 많은 카드).
        self._pick_gpu = gpu_picker or pick_gpu
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._print_lock = threading.Lock()
        #: 굽기 · 블렌더 마무리가 같이 잡는 한 줄 잠금(설계 `설계_3D작업대_블렌더마무리` §5 — 맥 16GB 에서 모델과 블렌더가 겹치지 않게).
        #: 마무리는 굽기가 돌거나 기다리면 바로 「busy」로 거절하고, 마무리 중에 들어온 굽기는 마무리가 끝날 때까지 기다렸다 돈다.
        self._heavy = threading.Lock()
        #: 블렌더 찾기 · 실행 — 시험은 가짜를 꽂는다(`blender.py` 의 두 함수와 같은 꼴).
        self._find_blender: Callable[[], dict[str, Any]] | None = None
        self._run_finish: Callable[..., dict[str, Any]] | None = None
        #: 색 렌더(`beauty.render_beauty` 꼴) — 시험은 가짜를 꽂는다.
        self._render_beauty: Callable[..., dict[str, Any]] | None = None
        #: 렌더 실행(`blender.run_script` 꼴) — 시험은 가짜를 꽂는다.
        self._run_render: Callable[..., dict[str, Any]] | None = None
        #: 내보내기 실행(같은 꼴) — 시험은 가짜를 꽂는다.
        self._run_export: Callable[..., dict[str, Any]] | None = None
        #: 상태가 바뀔 때마다 부른다(판 번호) — 화면 무대 알림(`gen3d_stage`)용. 실패해도 일은 계속한다.
        self.on_change: Callable[[str], None] | None = None
        self._queue: list[str] = []
        self._running: str | None = None

    # ── 받기 ────────────────────────────────────────────────────────────
    @property
    def mac(self) -> bool:
        return self.platform == "darwin"

    def ready(self) -> list[str]:
        """돌릴 준비가 안 된 까닭(빈 목록이면 됐다)."""
        problems = []
        if find_exe(self.bin_dir, self.platform) is None:
            problems.append(("이 맥용 실행기(trellis-cli · Metal 판)가 없다 — " if self.mac else "실행기(trellis-cli)가 없다 — ")
                            + str(self.bin_dir))
        missing = models_ready(self.models_dir)
        if missing:
            problems.append(f"모델 파일이 없다({', '.join(missing)}) — {self.models_dir}")
        return problems

    def submit(self, image: Path, *, res: int = 512, model: str = "trellis", seed: int | None = None,
               gpu: int | None = None, export: list[str] | None = None, size_mm: float | None = None,
               printer: str | None = None, detail: str = "auto", orientation: str | None = None, floor_cut_mm: float | None = None) -> str:
        if res not in RESOLUTIONS:
            raise ValueError(f"res 는 {RESOLUTIONS} 가운데 하나")
        if model not in MODELS:
            raise ValueError(f"model 은 {sorted(MODELS)} 가운데 하나")
        wanted = [str(item).lower() for item in (export or ["glb"])]
        bad = [item for item in wanted if item not in EXPORTS]
        if bad:
            raise ValueError(f"export 는 {list(EXPORTS)} 가운데서 — 모르는 것: {bad}")
        size = float(size_mm) if size_mm else DEFAULT_SIZE_MM
        if not SIZE_MM_RANGE[0] <= size <= SIZE_MM_RANGE[1]:
            raise ValueError(f"size_mm 은 {SIZE_MM_RANGE[0]:g}~{SIZE_MM_RANGE[1]:g}")
        if gpu is not None and not 0 <= int(gpu) <= 15:
            raise ValueError("gpu 는 0~15")
        check_print_options(printer, detail, orientation)
        problems = self.ready() + self.memory_problems(int(res))
        if problems:
            raise Gen3DError("not_ready: " + " · ".join(problems))
        with self._lock:
            waiting = len(self._queue) + (1 if self._running else 0)
            if waiting >= 2:
                raise Gen3DError(f"busy: 3D 만들기는 한 번에 하나 — 지금 {self._running} 이(가) 돌고 하나가 기다린다. 끝난 뒤 다시.")
            job_id = f"g3_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
            folder = self.out_root / job_id
            folder.mkdir(parents=True, exist_ok=False)
            job = Job(job_id, folder, Path(image), int(res), model, seed if seed is None else int(seed),
                      gpu if gpu is None else int(gpu), sorted(set(wanted) | {"glb"}), size,
                      printer=printer or None, detail=detail or "auto", orientation=orientation or None)
            job.floor_cut_mm = _floor(floor_cut_mm)
            # 넣은 그림 사본 — 무대가 판 폴더 안의 것만 받아 가게(원본 경로를 화면에 내주지 않는다).
            try:
                copy = folder / f"input{Path(image).suffix.lower()}"
                shutil.copyfile(image, copy)
                job.input_name = copy.name
            except OSError:
                job.input_name = ""
            self._jobs[job_id] = job
            self._queue.append(job_id)
            self._save(job)
            if self._running is None:
                self._start_next_locked()
        self._notify(job_id)
        return job_id

    def need_mib(self, res: int) -> int | None:
        """맥에서 한 판에 남아 있어야 하는 메모리(MiB). 윈도우는 카드 메모리를 실행기가 알아서 쓰므로 None."""
        return MAC_NEED_MIB.get(int(res)) if self.mac else None

    def memory_problems(self, res: int, *, after_unload: bool = False, free: int | None = None) -> list[str]:
        """맥: 남은 메모리가 모자라면 그 까닭(빈 목록이면 됐다). 글 모델이 올라와 있으면 내려서 생길 몫을 더해 본다."""
        if not self.mac:
            return []
        total = self._total()
        if res == 1024 and total is not None and total < MAC_1024_MIN_TOTAL_MIB:
            return [f"1024 는 이 맥(통합 메모리 {round(total / 1024)}GB)에서 막아 둔다 — 512 한 판이 실행기 혼자 약 {MAC_512_PEAK_MIB:,}MiB 를 "
                    "쓰고(11-14 실측) 1024 는 더 크다. 512 로 맡겨라"]
        need = self.need_mib(res)
        free = self._free() if free is None else free  # 영수증에 남긴 값과 판정에 쓴 값이 같게 — 한 번 잰 것을 넘겨받는다
        if need is None or free is None:
            return []  # 못 재면 막지 않는다(지어낸 숫자로 거절하지 않는다) — 영수증에 못 쟀다고 남는다
        reclaim = 0 if after_unload or self.text_models is None else sum(row["mib"] for row in self.text_models.loaded())
        if free + reclaim >= need:
            return []
        extra = f" + 글 모델을 내리면 {reclaim:,}MiB" if reclaim else ""
        return [f"메모리가 모자라다 — 남은 {free:,}MiB{extra}, {res} 한 판에 약 {need:,}MiB 가 남아 있어야 한다"
                " (맥은 그래픽 메모리가 일반 메모리와 같다 — 다른 프로그램을 닫고 다시)"]

    def _notify(self, job_id: str) -> None:
        callback = self.on_change
        if callback is None:
            return
        try:
            callback(job_id)
        except Exception:  # noqa: BLE001, S110 — 화면 알림이 실패해도 3D 만들기는 계속한다
            pass

    def get(self, job_id: str) -> dict[str, Any] | None:
        if not valid_job_id(job_id):
            return None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job.public()
        saved = self.out_root / job_id / "job.json"
        if saved.is_file():  # 본체를 다시 켠 뒤에도 끝난 판의 영수증은 남는다
            try:
                return json.loads(saved.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in {"queued", "running"}:
                return False
            job.cancel_requested = True
            if job.state == "queued" and job_id not in self._queue:
                # 대기열에서 막 빠져 시작하는 중(카드 고르기 · 갈아타기) — 표시만 하면 띄우자마자 끈다(11-15: 이 틈에 오류가 났다)
                return True
            if job.state == "queued":
                self._queue.remove(job_id)
                job.state, job.error = "failed", "cancelled"
                job.receipt = self._failure_receipt(job, "취소함 — 시작 전")
                self._save(job)
                return True
            process = job.process
        if process is not None:
            try:
                process.kill()
            except Exception:  # noqa: BLE001, S110 — 이미 끝난 프로세스면 죽일 것이 없다
                pass
        return True

    def shutdown(self) -> None:
        with self._lock:
            ids = [self._running, *self._queue]
        for job_id in ids:
            if job_id:
                self.cancel(job_id)

    def reprint(self, job_id: str, *, size_mm: float | None = None, printer: str | None = None, detail: str = "auto",
                orientation: str | None = None, export: list[str] | None = None,
                floor_cut_mm: float | None = None) -> dict[str, Any]:
        """이미 구운 3D 로 프린트 파일만 다시 준비한다(그래픽카드 안 씀 · 1분 안팎) — 영수증을 보고 크기 · 프린터 · 방향을
        바꿔 다시 해 보는 폐루프의 싼 한 바퀴(11-14). 판 폴더 안 `print_v<n>/` 에 새로 쓰고 앞 판은 지우지 않는다."""
        from .glb import read_glb
        from .printing import prepare_print

        found = self.get(job_id) if valid_job_id(job_id) else None
        if not found:
            raise ValueError(f"job_not_found: {job_id}")
        if found.get("state") != "done":
            raise Gen3DError(f"not_done: 그 판은 아직 {found.get('state')} — 끝난 판만 다시 준비할 수 있다")
        glb_name = Path(str(((found.get("receipt") or {}).get("files") or {}).get("glb") or "")).name
        home = (self.out_root / job_id).resolve()
        glb = (home / glb_name).resolve() if glb_name else None
        if glb is None or not glb.is_relative_to(home) or not glb.is_file():
            raise Gen3DError("no_glb: 그 판의 GLB 가 없다")
        # 설계 `설계_3D작업대_블렌더마무리` §4-④: 블렌더 마무리 판이 있으면 마지막 것을 뽑는다(원본은 그대로 남아 있다).
        finished = self.finish_versions(home)
        source = finished[-1].parent.name if finished else "구운 원본"
        if finished:
            glb = finished[-1]
        size = float(size_mm) if size_mm else DEFAULT_SIZE_MM
        if not SIZE_MM_RANGE[0] <= size <= SIZE_MM_RANGE[1]:
            raise ValueError(f"size_mm 은 {SIZE_MM_RANGE[0]:g}~{SIZE_MM_RANGE[1]:g}")
        check_print_options(printer, detail, orientation)
        wanted = sorted({str(item).lower() for item in (export or ["stl", "3mf"])} - {"glb"})
        bad = [item for item in wanted if item not in EXPORTS]
        if bad or not wanted:
            raise ValueError(f"export 는 stl · 3mf 가운데서 — 받은 것: {export}")
        if not self._print_lock.acquire(blocking=False):
            raise Gen3DError("busy: 프린트 준비는 한 번에 하나 — 앞 것이 끝난 뒤 다시")
        try:
            n = 1
            while (home / f"print_v{n}").exists():
                n += 1
            folder = home / f"print_v{n}"
            folder.mkdir()
            started = time.time()
            printed = prepare_print(read_glb(glb), folder, glb.stem, wanted, size, printer=printer or None, floor_cut_mm=_floor(floor_cut_mm),
                                    detail=detail or "auto", orientation=orientation or None)
            out = {"job_id": job_id, "version": f"print_v{n}", "from": source, "size_mm": size, "printer": printer,
                   "detail": detail or "auto", "orientation": orientation or "지금 그대로",
                   "sec": round(time.time() - started, 1), "files": printed["files"],
                   "printable": printed["printable"], "print": printed["report"]}
            (folder / "print.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            return out
        finally:
            self._print_lock.release()

    # ── 조립 부품으로 나눠 뽑기 (설계 `설계_조립부품나누기`) ──────────────────────
    def _done_glb(self, job_id: str) -> tuple[Path, Path]:
        found = self.get(job_id) if valid_job_id(job_id) else None
        if not found:
            raise ValueError(f"job_not_found: {job_id}")
        if found.get("state") != "done":
            raise Gen3DError(f"not_done: 그 판은 아직 {found.get('state')} — 끝난 판만 나눌 수 있다")
        glb_name = Path(str(((found.get("receipt") or {}).get("files") or {}).get("glb") or "")).name
        home = (self.out_root / job_id).resolve()
        glb = (home / glb_name).resolve() if glb_name else None
        if glb is None or not glb.is_relative_to(home) or not glb.is_file():
            raise Gen3DError("no_glb: 그 판의 GLB 가 없다")
        return home, glb

    @staticmethod
    @contextmanager
    def _blender_slot(who: str) -> Iterator[dict[str, Any]]:
        """사람이 기다리는 블렌더 일 — 한 줄 잠금이 잡혀 있으면 기다리지 않고 busy(교착 막기 · §14-2)."""
        from ..pack_ram import HeavyBusy, heavy_slot

        with ExitStack() as stack:
            try:
                info = stack.enter_context(heavy_slot(who, wait=False))
            except HeavyBusy as exc:
                raise Gen3DError(str(exc)) from exc
            yield info

    @staticmethod
    def _next_dir(home: Path, prefix: str) -> Path:
        n = 1
        while (home / f"{prefix}{n}").exists():
            n += 1
        folder = home / f"{prefix}{n}"
        folder.mkdir(parents=True)
        return folder

    def split_plan(self, job_id: str, *, size_mm: float | None = None, orientation: str | None = None) -> dict[str, Any]:
        """나눌 자리 후보 + 그림. 판 폴더 안 `split_plan_v<n>/`."""
        from .assembly import plan_split
        from .glb import read_glb

        home, glb = self._done_glb(job_id)
        size = float(size_mm) if size_mm else DEFAULT_SIZE_MM
        if not SIZE_MM_RANGE[0] <= size <= SIZE_MM_RANGE[1]:
            raise ValueError(f"size_mm 은 {SIZE_MM_RANGE[0]:g}~{SIZE_MM_RANGE[1]:g}")
        check_print_options(None, "auto", orientation)
        if not self._print_lock.acquire(blocking=False):
            raise Gen3DError("busy: 프린트 준비는 한 번에 하나 — 앞 것이 끝난 뒤 다시")
        try:
            folder = self._next_dir(home, "split_plan_v")
            started = time.time()
            out = plan_split(read_glb(glb), folder, glb.stem, size, orientation=orientation or None)
            out = {"job_id": job_id, "version": folder.name, "sec": round(time.time() - started, 1), **out}
            (folder / "plan.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            return out
        finally:
            self._print_lock.release()

    def split(self, job_id: str, cuts: list[dict[str, Any]], *, size_mm: float | None = None, printer: str | None = None,
              detail: str = "auto", orientation: str | None = None, pin_d: float | None = None,
              floor_cut_mm: float | None = None, attach: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """나눠 뽑기: 자르기(후보 번호 또는 점 · 방향) → (따로 구운 부품 앉히기 · 설계 §8-6) → 부품 · 핀 · 판 · 썰기.
        판 폴더 안 `split_v<n>/`. 붙일 판은 읽기만 한다(새 파일은 바탕 판의 split_v<n>/ 에만)."""
        from .assembly import Cut, load_fit, prepare_assembly
        from .attach import Attach
        from .glb import read_glb
        from .printing import print_space, printer_prefs

        home, glb = self._done_glb(job_id)
        size = float(size_mm) if size_mm else DEFAULT_SIZE_MM
        if not SIZE_MM_RANGE[0] <= size <= SIZE_MM_RANGE[1]:
            raise ValueError(f"size_mm 은 {SIZE_MM_RANGE[0]:g}~{SIZE_MM_RANGE[1]:g}")
        check_print_options(printer, detail, orientation)
        cuts = list(cuts or [])
        attach = list(attach or [])
        if not isinstance(cuts, list) or (not cuts and not attach):
            raise ValueError("cuts 는 하나 이상 — {candidate: 번호} 또는 {point:[x,y,z], normal:[x,y,z]} (attach 만 쓸 땐 비워도 된다)")
        if len(attach) > 4:
            raise ValueError("attach 는 한 번에 넷까지")
        attached: list[Any] = []
        for i, raw in enumerate(attach):
            spec = Attach.check(raw, i)
            other = str((raw or {}).get("job_id") or "").strip()
            if not other or other == job_id:
                raise ValueError(f"attach[{i}].job_id 는 따로 구운 다른 판(done)")
            if (raw or {}).get("size_mm") in (None, ""):
                raise ValueError(f"attach[{i}].size_mm 이 비었다 — 붙일 부품의 긴 변 mm(예: 햄버거 39)")
            a_size = float(raw["size_mm"])
            if not 5.0 <= a_size <= size:
                raise ValueError(f"attach[{i}].size_mm 은 5~{size:g}(바탕보다 클 수 없다)")
            _, a_glb = self._done_glb(other)
            a_pos, a_faces = print_space(read_glb(a_glb), a_size)
            attached.append(Attach(pos=a_pos, faces=a_faces, source=other, size_mm=a_size, **spec))
        plan: dict[str, Any] | None = None
        parsed: list[Cut] = []
        for i, raw in enumerate(cuts):
            if not isinstance(raw, dict):
                raise ValueError(f"cuts[{i}] 는 객체")
            if raw.get("candidate") not in (None, ""):
                if plan is None:
                    plans = sorted(home.glob("split_plan_v*/plan.json"), key=lambda p: int(p.parent.name.rsplit("v", 1)[1]))
                    if not plans:
                        raise ValueError("candidate 를 쓰려면 먼저 gen_3d_split_plan 으로 후보를 받아야 한다")
                    plan = json.loads(plans[-1].read_text(encoding="utf-8"))
                    if float(plan.get("size_mm") or 0) != size or (plan.get("orientation") or "지금 그대로") != (orientation or "지금 그대로"):
                        raise ValueError("마지막 후보는 다른 크기 · 방향으로 찾은 것 — 같은 size_mm · orientation 으로 gen_3d_split_plan 을 다시 불러라")
                found = [c for c in plan.get("candidates") or [] if int(c.get("id", -1)) == int(raw["candidate"])]
                if not found:
                    raise ValueError(f"후보 {raw['candidate']} 가 없다")
                parsed.append(Cut.parse({**found[0], "name": raw.get("name") or f"후보{raw['candidate']}"}, i))
            else:
                parsed.append(Cut.parse(raw, i))
        prefs = printer_prefs(printer)
        fit = load_fit(self.out_root)
        clearance, source = None, "기본값 0.2mm(우리 프린터에서 안 잼 — gen_3d_fit_test 로 재면 바뀐다)"
        if fit:
            clearance = float(fit["clearance_mm"])
            source = f"끼움 시험으로 정함({fit.get('printer')} · {fit.get('filament')} · {fit.get('saved_at')})"
            if fit.get("printer") != prefs["printer"]:
                source += f" — 지금 프린터 {prefs['printer']} 와 다르다"
        if not self._print_lock.acquire(blocking=False):
            raise Gen3DError("busy: 프린트 준비는 한 번에 하나 — 앞 것이 끝난 뒤 다시")
        try:
            folder = self._next_dir(home, "split_v")
            started = time.time()
            out = prepare_assembly(read_glb(glb), folder, glb.stem, size, parsed, printer=printer or None,
                                   detail=detail or "auto", orientation=orientation or None, clearance=clearance,
                                   clearance_source=source, pin_d=float(pin_d) if pin_d else None,
                                   floor_cut_mm=_floor(floor_cut_mm), attach=attached or None)
            out = {"job_id": job_id, "version": folder.name, "size_mm": size, "sec": round(time.time() - started, 1), **out}
            (folder / "split.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            return out
        finally:
            self._print_lock.release()

    def prep(self, image: Path, *, size: int = 1024, grid: int = 16, crop: str | None = None,
             erase: list[dict[str, Any]] | None = None, smooth: int = 0, view: str | None = None) -> dict[str, Any]:
        """사진 손질(설계 `설계_3D두번굽기_분업` §4-1) — `<3D 폴더>/prep/<이름>_v<n>/` 에 새로 쓴다(원본은 그대로)."""
        from .prep import prep_image

        stem = re.sub(r"[^0-9A-Za-z가-힣_-]", "_", image.stem)[:40] or "image"
        folder = self._next_dir(self.out_root / "prep", f"{stem}_v")
        out = prep_image(image, folder, size=int(size), grid=int(grid), crop=crop, erase=erase, smooth=int(smooth), view=view)
        (folder / "prep.json").write_text(json.dumps({"source": str(image), "erase": erase or [], "crop": crop, **out},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
        return {"version": folder.name, **out}

    def views(self, job_id: str, *, source: str = "model", zoom: str | None = None, grid: int = 0) -> dict[str, Any]:
        """6방향 판(또는 한 방향 크게). source: model(구운 GLB · 색) · shape(구운 GLB · 회색 모양만) ·
        print(마지막 print_v 의 STL · 다시 뜬 프린트 모양)."""
        import numpy as np

        from .glb import Mesh, read_glb
        from .preview import SHAPE_GRAY, view_one, view_sheet

        home, glb = self._done_glb(job_id)
        if source == "beauty":
            return self._beauty_view(job_id, home, glb)
        gray = False
        if source == "model":
            mesh, tag = read_glb(glb), "model"
        elif source == "shape":
            mesh, tag, gray = read_glb(glb), "shape", True
        elif source == "print":
            stls = sorted(home.glob("print_v*/*.stl"), key=lambda p: int(p.parent.name.rsplit("v", 1)[1]))
            stls = stls or sorted(home.glob("*.stl"))
            if not stls:
                raise ValueError("프린트 파일(STL)이 없다 — gen_3d_print 로 먼저 만든다")
            pos, faces = _read_stl(stls[-1])
            # 프린트 자리(z 위) → 그림 자리(y 위 · 앞 +z): 프린트 자리의 -y 가 앞
            mesh, tag = Mesh(np.stack([pos[:, 0], pos[:, 2], -pos[:, 1]], axis=1), faces), stls[-1].parent.name
        else:
            raise ValueError("source 는 model · shape · print · beauty 가운데 하나")
        grid = int(grid or 0)
        if grid and not 6 <= grid <= 32:
            raise ValueError("grid 는 6~32(칸 수) — 비우면 격자 없음")
        out = home / "views"
        out.mkdir(exist_ok=True)
        suffix = f"_g{grid}" if grid else ""
        if zoom:
            colors = np.full((len(mesh.faces), 3), SHAPE_GRAY) if gray else None
            path = view_one(mesh, zoom, out / f"{tag}_{zoom}{suffix}.png", colors, grid=grid)
        else:
            path = view_sheet(mesh, out / f"{tag}_views{suffix}.png", shape=gray, grid=grid)
        return {"job_id": job_id, "source": tag, "file": path,
                "how": "앞 · 뒤 · 왼쪽 · 오른쪽 · 위 · 아래 — 원본 사진과 대조해 흠(점 · 고리 · 무늬)·안 보이던 쪽(엉덩이 · 바닥)·딸려 온 배경을 찾는다. "
                       "작아서 안 보이면 zoom 으로 그 방향만 크게."}

    # ── 색 렌더 (11-16 · `beauty.py`) ──────────────────────────────────────
    def _beauty(self, glb: Path, folder: Path, stem: str) -> dict[str, Any]:
        """조명 있는 앞 · 3/4 두 장. 블렌더가 없거나 꺼 두면 조용히 빠지지 않고 not_done 에 까닭 · 대신 쓸 것을 적는다."""
        from .beauty import INSTEAD, render_beauty

        if os.environ.get("JARVIS_GEN3D_BEAUTY", "1").strip() == "0":
            return {"ok": False, "files": [], "not_done": [f"색 렌더를 꺼 두었다(JARVIS_GEN3D_BEAUTY=0). {INSTEAD}"]}
        try:
            return (self._render_beauty or render_beauty)(glb, folder, stem, find=self._find_blender)
        except Exception as exc:  # noqa: BLE001 — 렌더는 덤
            return {"ok": False, "files": [], "not_done": [f"색 렌더 실패 — {type(exc).__name__}: {exc}"[:300]]}

    # ── 블렌더 마무리 (설계 `설계_3D작업대_블렌더마무리` §4-③) ─────────────────────
    def _beauty_view(self, job_id: str, home: Path, glb: Path) -> dict[str, Any]:
        """굽기 때 만든 색 렌더가 있으면 그것을, 없으면(옛 판 · 그때 블렌더 없음) 지금 찍는다."""
        found = self.get(job_id) or {}
        had = [p for p in (((found.get("receipt") or {}).get("files") or {}).get("beauty") or []) if Path(p).is_file()]
        how = ("조명 있는 앞 · 3/4 색 렌더(Cycles CPU) — 영상 첫 장면 · 사람에게 보일 그림. 모양 판단은 shape 로 "
               "(조명이 흠을 가린다). not_done 의 「새까맣다」는 텍스처 바탕색이 검정인 판이다(조명으로 안 풀린다).")
        if len(had) == 2:
            return {"job_id": job_id, "source": "beauty", "file": had[0], "files": had, "cached": True, "not_done": [], "how": how}
        if not self._heavy.acquire(blocking=False):
            raise Gen3DError("busy: 굽기 · 블렌더 마무리가 도는 중이다 — 끝난 뒤 다시 부른다")
        try:
            with self._blender_slot("3D 색 렌더"):
                out = self._beauty(glb, home / "views", "beauty")
        finally:
            self._heavy.release()
        if not out.get("ok"):
            raise Gen3DError(" · ".join(out.get("not_done") or ["색 렌더를 못 만들었다"]))
        return {"job_id": job_id, "source": "beauty", "file": out["files"][0], "files": out["files"], "cached": False,
                "measured": out.get("measured"), "not_done": out.get("not_done") or [], "how": how}

    # ── 렌더 (11-18 · 설계 `설계_블렌더공통층_워크플로우` §14-3) ─────────────────────
    def render(self, job_id: str | None = None, *, glb_path: str | None = None, base: str = "last",
               **options: Any) -> dict[str, Any]:
        """스튜디오 컷 · 한 바퀴 · 회색 형체를 판 폴더 안 `render_v<n>/` 에 새로 쓴다(덮어쓰지 않음).
        CPU 렌더라 3D 실행기 안 잠금(`_heavy`)은 잡지 않는다 — 공통 한 줄 잠금만(맥에서 굽기가 돌면 busy · §14-2)."""
        from .render import render_glb

        src, folder = self._pick_source(job_id, glb_path, base, "render")
        try:
            with self._blender_slot("3D 렌더"):
                out = render_glb(src, folder, find=self._find_blender, run=self._run_render, **options)
        except Exception:
            try:
                folder.rmdir()  # 비었으면 지운다(시작도 못 한 칸을 남기지 않게)
            except OSError:
                pass
            raise
        out = {"job_id": job_id, "source": src.name, "folder": str(folder), **out}
        try:
            (folder / "render.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        out["how"] = ("still 은 영상 팩 gen_video_* 의 첫 · 끝 그림으로 그대로 쓴다 · 한 바퀴 mp4 는 「진짜 3D 컷」. "
                      "숫자(프레임 · 크기 · 모델 몫 · 이음새)는 파일을 직접 열어 잰 값 — 그림은 열어 보고 모양이 맞는지 확인한다. 색은 손대지 않았다.")
        return out

    def _pick_source(self, job_id: str | None, glb_path: str | None, base: str, prefix: str) -> tuple[Path, Path]:
        """(원본 GLB, 새 칸) — 렌더 · 내보내기가 같이 쓴다. 판이면 마지막 마무리 판(base) · 아니면 GLB 옆에 새 칸."""
        if job_id:
            home, glb = self._done_glb(job_id)
            done = self.finish_versions(home)
            if base == "last":
                src = done[-1] if done else glb
            elif base == "original":
                src = glb
            else:
                match = [g for g in done if g.parent.name == base]
                if not match:
                    raise ValueError(f"base 는 last · original · 끝까지 간 마무리 판 이름({[g.parent.name for g in done]}) 가운데 — 받은 것: {base}")
                src = match[0]
            return src, self._next_dir(home, f"{prefix}_v")
        if glb_path:
            src = Path(glb_path).expanduser().resolve()
            if src.suffix.lower() != ".glb" or not src.is_file():
                raise ValueError(f"glb_path 는 있는 .glb 파일이어야 한다: {glb_path}")
            return src, self._next_dir(src.parent, f"{src.stem[:40]}_{prefix}_v")
        raise ValueError("job_id 또는 glb_path 가 필요하다")

    # ── 내보내기 (11-18 · 설계 §5-3 · 유니티 FBX · GLB) ─────────────────────────
    def export(self, job_id: str | None = None, *, glb_path: str | None = None, base: str = "last",
               **options: Any) -> dict[str, Any]:
        """판 폴더 안 `export_v<n>/` 에 유니티 FBX · GLB 를 새로 쓴다. 숫자는 블렌더가 다시 불러와 잰 것 · 요청과 대 본 어긋남은 not_done."""
        from .export import export_glb, safe_name

        src, folder = self._pick_source(job_id, glb_path, base, "export")
        options.setdefault("name", safe_name(src.stem))
        try:
            with self._blender_slot("3D 내보내기"):
                out = export_glb(src, folder, find=self._find_blender, run=self._run_export, **options)
        except Exception:
            try:
                folder.rmdir()
            except OSError:
                pass
            raise
        out = {"job_id": job_id, "source": src.name, "folder": str(folder), **out}
        try:
            (folder / "export.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        return out

    def finish_versions(self, home: Path) -> list[Path]:
        """끝까지 간(ok) 마무리 판의 GLB, 오래된 것부터."""
        found = []
        for folder in home.glob("finish_v*"):
            tail = folder.name[len("finish_v"):]
            receipt = folder / "finish.json"
            if not tail.isdigit() or not receipt.is_file():
                continue
            try:
                data = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            glb = folder / Path(str((data.get("files") or {}).get("glb") or "")).name
            if data.get("ok") and glb.is_file():
                found.append((int(tail), glb))
        return [glb for _, glb in sorted(found)]

    def finish(self, job_id: str, ops: list[dict[str, Any]], *, size_mm: float | None = None, base: str | None = None,
               zoom: str | None = None) -> dict[str, Any]:
        """구운 GLB(또는 앞 마무리 판)를 블렌더에서 ops 대로 고쳐 `finish_v<n>/` 에 새로 쓴다 — 원본은 덮어쓰지 않는다.
        전후 회색 모양 판 한 장 · 영수증(한 일 · 숫자 · 파일 · 못 한 것)을 같이 남긴다."""
        from .blender import find_blender
        from .preview import SIX_VIEWS

        home, glb = self._done_glb(job_id)
        ops = self._check_finish_ops(ops)
        size = float(size_mm) if size_mm else DEFAULT_SIZE_MM
        if not SIZE_MM_RANGE[0] <= size <= SIZE_MM_RANGE[1]:
            raise ValueError(f"size_mm 은 {SIZE_MM_RANGE[0]:g}~{SIZE_MM_RANGE[1]:g}")
        if zoom and zoom not in dict(SIX_VIEWS):
            raise ValueError(f"zoom 은 {[name for name, _ in SIX_VIEWS]} 가운데 하나")
        done = self.finish_versions(home)
        base = (base or "last").strip()
        if base == "last":
            src = done[-1] if done else glb
        elif base == "original":
            src = glb
        else:
            match = [g for g in done if g.parent.name == base]
            if not match:
                raise ValueError(f"base 는 last · original · 끝까지 간 마무리 판 이름({[g.parent.name for g in done]}) 가운데 — 받은 것: {base}")
            src = match[0]
        found = (self._find_blender or find_blender)()
        if not found.get("found"):
            raise Gen3DError(f"no_blender: {found.get('why') or '블렌더를 못 찾았다'} — 마무리만 못 한다(굽기 · 프린트 준비 · 나누기는 그대로 된다). "
                             "없으면 gen_3d_blender(action=status)로 사람 동의를 받아 받는다 · 이미 깔려 있으면 JARVIS_BLENDER 에 blender 실행 파일 경로를 넣는다.")
        with self._lock:
            if self._running or self._queue:
                raise Gen3DError(f"busy: 지금 굽기({self._running or self._queue[0]})가 돌거나 기다린다 — 굽기와 마무리는 한 줄로 돈다. 끝난 뒤 다시.")
        if not self._print_lock.acquire(blocking=False):
            raise Gen3DError("busy: 프린트 준비 · 마무리는 한 번에 하나 — 앞 것이 끝난 뒤 다시")
        try:
            if not self._heavy.acquire(blocking=False):
                raise Gen3DError("busy: 굽기 · 마무리는 한 줄로 돈다 — 앞 것이 끝난 뒤 다시")
            try:
                with self._blender_slot("3D 마무리"):
                    return self._finish_locked(job_id, home, glb, src, ops, size, zoom, found)
            finally:
                self._heavy.release()
        finally:
            self._print_lock.release()

    def _finish_locked(self, job_id: str, home: Path, glb: Path, src: Path, ops: list[dict[str, Any]], size: float,
                       zoom: str | None, found: dict[str, Any]) -> dict[str, Any]:
        from .blender import run_finish
        from .glb import read_glb
        from .preview import compare_sheet

        folder = self._next_dir(home, "finish_v")
        out_glb = folder / f"{glb.stem}.glb"
        sent = [{**op, "size_mm": size} if op["op"] == "smooth_surface" else op for op in ops]
        started = time.time()
        try:
            result = (self._run_finish or run_finish)(src, out_glb, sent, exe=found.get("exe"))
        except Exception as exc:  # noqa: BLE001 — 시간 넘김 · 실행 실패도 영수증으로
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        receipt: dict[str, Any] = {
            "ok": bool(result.get("ok")) and out_glb.is_file(), "job_id": job_id, "version": folder.name,
            "from": src.parent.name if src != glb else "구운 원본", "ops": ops, "size_mm": size,
            "sec": round(time.time() - started, 1), "blender": result.get("blender") or found.get("version"),
        }
        if not receipt["ok"]:
            receipt["error"] = result.get("error") or "블렌더가 GLB 를 안 남겼다"
            receipt["not_done"] = ["마무리가 끝까지 못 갔다 — 원본 · 앞 판은 그대로다"]
        else:
            before, after = read_glb(src), read_glb(out_glb)
            files = {"glb": str(out_glb), "before_after": compare_sheet(before, after, folder / "before_after.png")}
            if zoom:
                files["before_after_zoom"] = compare_sheet(before, after, folder / f"before_after_{zoom}.png", only=zoom)
            items = result.get("ops") or []
            receipt.update({
                "files": files, "before": result.get("before"), "after": result.get("after"),
                "did": [_finish_line(item) for item in items], "numbers": items, "not_done": _finish_not_done(items),
                "how": "before_after 판(칸마다 왼쪽 전 · 오른쪽 후 · 회색 모양)을 열어 줄무늬가 줄었는지, 입선 · 눈 새김 · 털결처럼 "
                       "살려야 할 것이 지워지지 않았는지 본다. 지워졌으면 rounds 를 줄여 base=\"original\" 로 다시. "
                       "gen_3d_print 는 이제 마지막 마무리 판을 입력으로 쓴다.",
            })
        (folder / "finish.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return receipt

    @staticmethod
    def _check_finish_ops(ops: Any) -> list[dict[str, Any]]:
        if isinstance(ops, dict):
            ops = [ops]
        if not isinstance(ops, list) or not ops:
            raise ValueError("ops 는 하나 이상 — 예: [{\"op\": \"smooth_surface\"}]")
        if len(ops) > 8:
            raise ValueError("ops 는 한 번에 8개까지")
        out = []
        for i, raw in enumerate(ops):
            if not isinstance(raw, dict) or raw.get("op") not in FINISH_OPS:
                raise ValueError(f"ops[{i}] 의 op 는 {list(FINISH_OPS)} 가운데 하나")
            op = {key: value for key, value in raw.items() if key in FINISH_OPS[raw["op"]] | {"op"}}
            if "rounds" in op:
                rounds = int(op["rounds"])
                if not 1 <= rounds <= 60:
                    raise ValueError(f"ops[{i}].rounds 는 1~60")
                op["rounds"] = rounds
            if raw["op"] == "smooth_surface":
                op.setdefault("rounds", SMOOTH_SURFACE_ROUNDS)
            if "box" in op and not _valid_box(op["box"]):
                raise ValueError(f"ops[{i}].box 는 {{center:[x,y,z], axes:[[..]×3], half:[a,b,c]}}")
            if raw["op"] in {"erase_fill", "erase_part", "smooth"} and "box" not in op:
                raise ValueError(f"ops[{i}]({raw['op']}) 는 box 가 있어야 한다")
            if raw["op"] == "symmetrize" and op.get("keep", "+x") not in {"+x", "-x"}:
                raise ValueError(f"ops[{i}].keep 은 +x · -x")
            out.append(op)
        return out

    def fit_test(self, *, printer: str | None = None, pin_d: float | None = None) -> dict[str, Any]:
        """끼움 시험 조각(구멍 다섯 · 핀 하나). `<3D 폴더>/fit_test/v<n>/`."""
        from .assembly import fit_test

        d = float(pin_d) if pin_d else 5.0
        if not 3.0 <= d <= 10.0:
            raise ValueError("pin_d 는 3~10mm")
        if not self._print_lock.acquire(blocking=False):
            raise Gen3DError("busy: 프린트 준비는 한 번에 하나 — 앞 것이 끝난 뒤 다시")
        try:
            folder = self._next_dir(self.out_root / "fit_test", "v")
            out = {"version": folder.name, **fit_test(folder, printer=printer or None, pin_d=d)}
            (folder / "fit_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            return out
        finally:
            self._print_lock.release()

    def fit_set(self, clearance_mm: float, *, printer: str | None = None, note: str = "") -> dict[str, Any]:
        """사람이 끼워 보고 고른 틈을 저장한다 — 그 뒤 나눠 뽑기의 핀 구멍이 이 값을 쓴다."""
        from .assembly import save_fit
        from .printing import printer_prefs

        prefs = printer_prefs(printer)
        return save_fit(self.out_root, float(clearance_mm), prefs["printer"], prefs["filament"], note)

    def file_for(self, job_id: str, name: str) -> Path | None:
        """파일 내주기. **영수증 files 에 있는 이름만**, 그것도 그 판 폴더 안에서만(경로 빠져나가기 막기 · 11-12 CodeQL 규칙)."""
        if not valid_job_id(job_id) or not name or Path(name).name != name or name in {".", ".."}:
            return None
        found = self.get(job_id)
        receipt = (found or {}).get("receipt") or {}
        listed: set[str] = set()
        for value in (receipt.get("files") or {}).values():
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str) and item:
                    listed.add(Path(item).name)
        job = self._jobs.get(job_id)
        input_name = (job.input_name if job else "") or str((found or {}).get("image") or "")
        if input_name:
            listed.add(Path(input_name).name)
        if name not in listed:
            return None
        home = (self.out_root / job_id).resolve()
        target = (home / name).resolve()
        if not target.is_relative_to(home) or not target.is_file():
            return None
        return target

    # ── 돌리기 ──────────────────────────────────────────────────────────
    def _start_next_locked(self) -> None:
        if not self._queue:
            self._running = None
            return
        job_id = self._queue.pop(0)
        self._running = job_id
        threading.Thread(target=self._run, args=(self._jobs[job_id],), name=f"gen3d-{job_id}", daemon=True).start()

    def _swap_in(self, job: Job) -> None:
        """굽기 직전: (맥) 이 기기에 올라간 글 모델을 내리고 → 3D 모델을 올린다고 알린다. 윈도우는 알림(load)만.

        실패해도 판은 계속 간다 — 남은 것은 영수증 not_done 에 이름으로 남는다. 다 내린 뒤 남은 메모리를 다시 잰다.
        """
        need = self.need_mib(job.res)
        # 윈도우: 3D 는 다른 카드에서 돌아도 **램은 글 모델과 같이 쓴다** — 모자라면 내린다(11-17 · `pack_ram`). 맥은 예전처럼 늘 내린다.
        ram_unload = False
        if not self.mac and self.text_models is not None:
            from ..pack_ram import GEN3D_NEED_MIB, memory_status, should_unload, unload_disabled

            try:
                status = dict((self._memory_probe or memory_status)())
            except Exception:  # noqa: BLE001 — 못 재면 모른다
                status = {}
            ram_unload, why = should_unload(GEN3D_NEED_MIB, status, disabled=unload_disabled())
            job.ram = {**status, "need_mib": GEN3D_NEED_MIB, "unload": ram_unload, "why": why}
        loaded = self.text_models.loaded() if ((self.mac or ram_unload) and self.text_models is not None) else []
        names = [row["name"] for row in loaded]
        base: dict[str, Any] = {"from": " · ".join(names) or None, "to": f"{SWAP_TO} · {_precision(self.models_dir)}"}
        if need:
            base["expected_mib"] = need
        if names:
            job.swap = {**base, "phase": "unload", "from_mib": sum(row["mib"] for row in loaded)}
            self._notify(job.job_id)
            try:
                job.not_unloaded = list(self.text_models.unload(names))
            except Exception:  # noqa: BLE001 — 못 내렸으면 그대로 간다(아래 남은 메모리 확인이 막아 준다)
                job.not_unloaded = list(names)
            job.unloaded = [name for name in names if name not in job.not_unloaded]
            if job.unloaded and not self.mac:
                from ..pack_ram import note_unloaded

                note_unloaded()
        job.swap = {**base, "phase": "load"}
        self._notify(job.job_id)
        if self.mac:
            job.free_before = self._free()
            problems = self.memory_problems(job.res, after_unload=True, free=job.free_before)
            if problems:
                job.error = "not_enough_memory: " + " · ".join(problems)

    def _command(self, job: Job, exe: Path, out_glb: Path) -> list[str]:
        cmd = [str(exe), "-i", str(job.image), "-o", str(out_glb), "-m", str(self.models_dir),
               "--res", str(job.res), "--model", job.model]
        if job.seed is not None:
            cmd += ["--seed", str(job.seed)]
        return cmd

    def _run(self, job: Job) -> None:
        # 블렌더 마무리가 돌고 있으면 끝날 때까지 기다린다(그동안 판은 queued 로 보인다).
        # 굽는 동안 「무거운 일 중」 — 앞부분 데우기가 내린 언어 모델을 도로 올리지 않게(11-17 · `pack_ram.heavy_work`).
        from ..pack_ram import heavy_slot, heavy_work

        # 한 줄 잠금(11-18 §14-2): 맥에서는 영상 굽기 · 애니 블렌더와도 한 줄. 잡는 순서는 늘 `_heavy` → 공통 잠금(교착 막기).
        with self._heavy, heavy_slot("3D 굽기", wait=True) as slot, heavy_work():
            job.slot_wait_sec = float(slot.get("busy_wait_sec") or 0.0)
            self._run_locked(job)

    def _run_locked(self, job: Job) -> None:
        exe = find_exe(self.bin_dir, self.platform)
        # 색이 이상해 다시 굽는 판은 새 이름(앞 판 파일을 지우지 않는다 · 11-16 밤 색 대조 검사).
        suffix = f"_try{job.color_try + 1}" if job.color_try else ""
        out_glb = job.folder / f"{job.image.stem[:40] or 'model'}{suffix}.glb"
        env = dict(os.environ)
        if job.gpu is None and not self.mac:
            # 카드 고르기(설계 `설계_3D두번굽기_분업` §4-5): 남은 메모리가 가장 많은 카드. 영수증에 무엇을 왜 골랐는지.
            card = self._pick_gpu()
            if card is not None:
                job.gpu = int(card["index"])
                job.gpu_pick = {**card, "auto": True}
        if job.gpu is not None and not self.mac:  # 맥은 카드가 하나 — gpu 인자를 무시한다
            # nvidia-smi 번호와 CUDA 번호를 맞춘다 — 기본(빠른 카드 먼저)이면 3090 · 3060 순서가 뒤바뀔 수 있다.
            env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            env["CUDA_VISIBLE_DEVICES"] = str(job.gpu)
        job.tracker = StageTracker()
        job.started_at = time.time()
        with self._lock:
            job.state = "running"
        try:
            self._swap_in(job)
        except Exception as exc:  # noqa: BLE001 — 알림 · 내리기가 틀어져도 굽기는 간다
            job.not_unloaded = job.not_unloaded or [f"갈아타기 오류: {exc}"]
        job.vram_base = self._vram(job.gpu)
        job.vram_peak = job.vram_base
        stop = threading.Event()

        def poll() -> None:
            seen: tuple[Any, ...] = ()
            while not stop.wait(self._poll_sec):
                used = self._vram(job.gpu)
                job.vram_now = used
                if self.mac and job.process is not None:
                    peak = self._proc(getattr(job.process, "pid", None))
                    if peak is not None and (job.proc_peak is None or peak > job.proc_peak):
                        job.proc_peak = peak
                if used is not None and (job.vram_peak is None or used > job.vram_peak):
                    job.vram_peak = used
                current = job.tracker.current() or {}
                mark = (current.get("index"), (current.get("sub") or {}).get("done"), (used or 0) // 128)
                if mark != seen:
                    seen = mark
                    self._notify(job.job_id)

        poller = threading.Thread(target=poll, daemon=True)
        poller.start()
        rc: int | None = None
        log_path = job.folder / (f"run_try{job.color_try + 1}.log" if job.color_try else "run.log")
        try:
            if job.error is not None:  # 굽기 전 확인(메모리)에서 멈췄다 — 실행기를 띄우지 않는다
                raise Gen3DError(job.error)
            with open(log_path, "wb") as log:
                process = self._popen(
                    self._command(job, exe, out_glb), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, cwd=str(exe.parent), env=env, creationflags=_NO_WINDOW,
                )
                job.process = process
                # 본체의 낮은 순위(메모리 2 · 디스크 1)를 물려받지 않게 — 영상 실행기에서 확인한 뿌리(11-17 · `pack_ram.lift_to_normal`).
                from ..pack_ram import lift_to_normal

                job.priority = lift_to_normal(process)
                if job.cancel_requested:
                    process.kill()
                timed_out = threading.Event()

                def on_timeout() -> None:
                    # 로그가 멎은 채 걸려도 읽기가 영영 안 끝나지 않게 — 시계가 따로 죽인다.
                    timed_out.set()
                    try:
                        process.kill()
                    except Exception:  # noqa: BLE001, S110 — 이미 끝난 프로세스면 죽일 것이 없다
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
                        if job.swap and job.swap.get("phase") == "load" and job.tracker.stage_index:
                            # 첫 단계가 돌기 시작했다 = 3D 모델이 올라와 일한다.
                            job.swap = {**job.swap, "phase": "ready"}
                            self._notify(job.job_id)
                    if rest:
                        job.tracker.feed(rest)
                    rc = process.wait(timeout=30)
                finally:
                    watchdog.cancel()
                if timed_out.is_set():
                    job.error = f"timeout: {RUN_TIMEOUT_SEC}초를 넘겨 멈췄다"
        except Exception as exc:  # noqa: BLE001 — 실패도 영수증으로
            job.error = job.error or f"run_failed: {exc}"
        finally:
            stop.set()
            poller.join(timeout=3)
            job.tracker.finish()
            job.ended_at = time.time()
            job.process = None
        try:
            if job.cancel_requested:
                job.error = "cancelled"
                job.receipt = self._failure_receipt(job, "취소함")
            elif job.error and job.error.startswith("not_enough_memory"):
                job.receipt = self._failure_receipt(job, "메모리가 모자라 시작하지 않았다")
            elif job.error is None and rc == 0 and out_glb.is_file():
                job.receipt = self._receipt(job, out_glb)
            else:
                job.error = job.error or f"exit_{rc}: 실행기가 실패했다 — 로그 끝: {' | '.join(job.tracker.tail[-3:])[:400]}"
                job.receipt = self._failure_receipt(job, "실행기가 끝까지 못 갔다")
        except Exception as exc:  # noqa: BLE001
            job.error = f"measure_failed: {exc}"
            job.receipt = self._failure_receipt(job, "GLB 는 만들었지만 재기에 실패했다")
        if self._color_retry(job, out_glb, log_path):
            self._run_locked(job)  # 같은 판 번호로 새 씨앗 한 번 더(색 대조 검사 · 최대 COLOR_RETRIES)
            return
        self._pick_best_color(job, log_path)
        with self._lock:
            job.state = "done" if job.error is None else "failed"
            self._save(job)
            self._start_next_locked()
        self._notify(job.job_id)

    # ── 색 대조 검사로 다시 굽기(11-16 밤) ───────────────────────────────────
    def _color_retry(self, job: Job, out_glb: Path, log_path: Path) -> bool:
        """색이 이상하고 · 씨앗을 사람이 정하지 않았고 · 아직 횟수가 남았으면 이 판을 기록하고 True(한 번 더 굽는다).

        사람이 씨앗을 정한 판은 그 씨앗의 결과를 원한 것이라 다시 굽지 않는다(영수증에 이상만 적는다).
        """
        if job.error is not None or job.cancel_requested or not job.receipt:
            return False
        color = ((job.receipt.get("measured") or {}).get("color") or {})
        if color.get("ok") is not False or job.seed is not None or job.color_try >= COLOR_RETRIES:
            return False
        job.color_tries.append({"try": job.color_try + 1, "seed": _logged_seed(log_path), "glb": str(out_glb),
                                "color": color, "receipt": job.receipt})
        job.color_try += 1
        job.receipt = None
        job.tracker = StageTracker()
        self._notify(job.job_id)
        return True

    def _pick_best_color(self, job: Job, log_path: Path | None = None) -> None:
        """다시 구웠으면 판들 중 색이 가장 나은 판을 결과로 — 나머지는 tries 에 남긴다(파일도 그대로)."""
        if not job.color_tries or not job.receipt:
            return
        from .color_check import score

        # 마지막 판 씨앗도 그 판 기록에서 읽는다(11-17 g3_20261117_000353_ab7129: 마지막 칸만 null 이었다)
        last_seed = _logged_seed(log_path) if log_path is not None else None
        last = {"try": job.color_try + 1, "seed": last_seed, "glb": (job.receipt.get("files") or {}).get("glb"),
                "color": (job.receipt.get("measured") or {}).get("color") or {}, "receipt": job.receipt}
        rows = [*job.color_tries, last]
        best = max(rows, key=lambda row: score(row["color"]))
        receipt = dict(best["receipt"])
        measured = dict(receipt.get("measured") or {})
        measured["color_tries"] = [{"try": row["try"], "seed": row["seed"], "glb": row["glb"],
                                    "ok": row["color"].get("ok"), "dark_share": row["color"].get("dark_share"),
                                    "ratio": row["color"].get("ratio")} for row in rows]
        receipt["measured"] = measured
        not_done = list(receipt.get("not_done") or [])
        if best["color"].get("ok") is False:
            not_done.append(f"색이 넣은 그림과 크게 다르다 — 씨앗을 바꿔 {len(rows)}번 구워도 못 맞췄다(가장 나은 판을 남김). "
                            "평평한 아이콘풍 그림이면 명암 · 질감을 넣은 그림으로 다시 해 보라")
        else:
            not_done.append(f"첫 판의 색이 이상해 씨앗을 바꿔 다시 구웠다({len(rows)}판 중 {best['try']}번째를 남김)")
        receipt["not_done"] = not_done
        job.receipt = receipt

    # ── 영수증 ──────────────────────────────────────────────────────────
    def _model_block(self, job: Job) -> dict[str, Any]:
        return {"name": MODELS[job.model], "precision": _precision(self.models_dir), "res": job.res,
                "license": "MIT(원본 TRELLIS.2 · DINOv3 · BiRefNet 각자 라이선스)", "runner": "trellis.cpp"}

    def _receipt(self, job: Job, glb: Path) -> dict[str, Any]:
        from .glb import read_glb
        from .preview import write_previews
        from .printing import check_printable, prepare_print

        mesh = read_glb(glb)
        lo, hi = mesh.bbox
        check = check_printable(mesh)
        stem = glb.stem
        files: dict[str, Any] = {"glb": str(glb)}
        files["preview"] = write_previews(mesh, job.folder, stem)
        try:
            # 6방향 판(설계 `설계_3D두번굽기_분업` §4-2): 클로드가 앞 · 뒤 · 좌 · 우 · 위 · 아래를 한 장으로 원본과 대조한다.
            from .preview import view_sheet

            files["views"] = view_sheet(mesh, job.folder / f"{stem}_views.png")
            # 모양 판(11-15): 색을 버린 회색 — 판단은 이걸로(색 판에선 햄버거가 좋아 보였는데 모양은 매끈한 통이었다).
            files["shape_views"] = view_sheet(mesh, job.folder / f"{stem}_shape_views.png", shape=True)
        except Exception:  # 그림은 덤 — 실패해도 영수증은 나간다
            pass
        # 색 렌더(11-16 · 팩 잇기): 조명 있는 앞 · 3/4 — 영상 첫 장면 · 사람에게 보일 그림. 실패해도 굽기는 성공이다.
        beauty = self._beauty(glb, job.folder, stem)
        if beauty.get("files"):
            files["beauty"] = beauty["files"]
        texture = glb.with_name(f"{stem}_base.png")
        color: dict[str, Any] | None = None
        if texture.is_file():
            files["texture"] = str(texture)
            # 색 대조 검사(11-16 밤): 모양은 멀쩡한데 색 그림이 검게 나오는 판을 사람이 판을 열기 전에 잡는다.
            from .color_check import measure as measure_color

            color = measure_color(job.image, texture)
        printed = None
        if {"stl", "3mf"} & set(job.export):
            # 프린트 갈래(11-14 · 설계 `설계_3D프린트갈래`): 다시 떠 닫힌 메시로 → 재서 설정 → 뱀부가 있으면 썬다.
            def _step(info: dict[str, Any]) -> None:
                job.print_step = info
                self._notify(job.job_id)

            printed = prepare_print(mesh, job.folder, stem, job.export, job.size_mm, printer=job.printer, floor_cut_mm=job.floor_cut_mm, on_stage=_step,
                                    detail=job.detail, orientation=job.orientation)
            files.update(printed["files"])
        tracker = job.tracker
        measured = {
            "faces": len(mesh.faces),
            "holes_filled": tracker.holes_filled,
            "floaters_dropped": tracker.floaters_dropped,
            "bbox_m": [round(float(v), 4) for v in (hi - lo)],
            "vram_peak_mib": job.vram_peak,
            "vram_base_mib": job.vram_base,
            **self._memory_block(job),
            "sec": round((job.ended_at or time.time()) - (job.started_at or time.time()), 1),
            "exe_sec": tracker.exe_sec,
            "busy_wait_sec": job.slot_wait_sec,
            "watertight": check["watertight"],
            "boundary_edges": check["boundary_edges"],
            "non_manifold_edges": check["non_manifold_edges"],
            "flipped_edges": check["flipped_edges"],
            "parts": check["parts"],
        }
        try:
            # 흠집 숫자(11-15 · 설계 `설계_3D작업대_블렌더마무리` §4-②): 찢김 · 떨어진 덩어리만 숫자로 — 나머지는 모양 판을 본다.
            from .defects import measure as measure_defects

            measured["defects"] = measure_defects(mesh)
        except Exception as exc:  # 재기는 덤 — 실패해도 영수증은 나간다
            measured["defects"] = {"error": str(exc)[:200]}
        backing_flag = None
        try:
            # 뒤에 붙은 판(11-17 · 평면 아이콘 → 판에 붙은 부조 · TRELLIS.2#45): 숫자로 잡아 not_done 에 정직하게 남긴다.
            from .defects import flat_backing

            measured["backing"] = flat_backing(mesh)
            backing_flag = measured["backing"].get("flag")
        except Exception as exc:  # noqa: BLE001 — 재기는 덤
            measured["backing"] = {"error": str(exc)[:200]}
        if color is not None:
            measured["color"] = color
        not_done = ["UV 펼침 · 면 정리(리토폴로지)는 실행기가 한 그대로 — 게임용 다듬기는 블렌더 쪽 일",
                    "색 나누기(여러 색 프린트)는 아직 없다 — 3MF 는 한 색"]
        if job.vram_peak is None:
            not_done.append("통합 메모리를 못 쟀다(sysctl 실패)" if self.mac else "그래픽카드 메모리를 못 쟀다(nvidia-smi 없음)")
        if backing_flag:
            not_done.append(backing_flag)
        not_done.extend(self._swap_notes(job))
        not_done.extend(beauty.get("not_done") or [])
        printable = {**check["printable"], "size_mm": job.size_mm}
        receipt_extra: dict[str, Any] = {}
        if beauty.get("ok"):
            receipt_extra["beauty"] = {k: beauty.get(k) for k in ("sec", "engine", "samples", "measured")}
        if printed is not None:
            # 판정은 다시 뜬 메시 기준 — 실행기 메시의 판정(before)도 같이 남긴다(고친 효과를 숫자로 보이게).
            printable = {**printed["printable"], "before": check["printable"]}
            receipt_extra["print"] = printed["report"]
            if not printed["printable"]["ok"]:
                not_done.append("다시 떴는데도 프린트 판정을 못 넘었다 — why 를 볼 것")
            not_done.append("다시 뜨기에서 색(텍스처)은 버렸다 · 칸보다 가는 디테일은 둥글어졌다")
        return {
            "did": f"3D 초안 1개 · {job.res}",
            "files": files,
            "measured": measured,
            "printable": printable,
            "not_done": not_done,
            "model": self._model_block(job),
            **receipt_extra,
        }

    def _failure_receipt(self, job: Job, did: str) -> dict[str, Any]:
        tracker = job.tracker
        where = f"{tracker.stage_index}/{7} {tracker.stage_name}" if tracker.stage_index else "시작 전"
        sec = round((job.ended_at or time.time()) - job.started_at, 1) if job.started_at else 0.0
        return {
            "did": did,
            "files": {},
            "measured": {"sec": sec, "vram_peak_mib": job.vram_peak, "vram_base_mib": job.vram_base,
                         **self._memory_block(job), "stopped_at": where},
            "printable": {"ok": False, "why": ["결과가 없다"]},
            "not_done": [f"멈춘 자리: {where}", *([f"로그 끝: {tracker.tail[-1][:200]}"] if tracker.tail else []),
                         *([job.error] if job.error and job.error.startswith("not_enough_memory") else []),
                         *self._swap_notes(job)],
            "model": self._model_block(job),
        }

    def _memory_block(self, job: Job) -> dict[str, Any]:
        """무엇을 쟀는지를 칸에 적는다(계약 칸 이름 `vram_*_mib` 는 그대로 · 맥은 통합 메모리)."""
        block: dict[str, Any] = {"memory_what": memory_what(self.platform, job.gpu)}
        if job.gpu_pick:
            block["gpu_pick"] = job.gpu_pick  # 손자리가 고른 카드와 그때 남은 메모리
        if self.mac:
            block.update({"unified_memory": True, "proc_peak_mib": job.proc_peak, "free_before_mib": job.free_before,
                          "need_mib": self.need_mib(job.res), "text_models_unloaded": list(job.unloaded)})
        elif job.ram is not None:
            # 윈도우: 굽기 직전 램 판정 · 내린 글 모델(11-17 · `pack_ram`) — 느렸을 때 램 탓인지 가르는 근거.
            block.update({"ram": job.ram, "text_models_unloaded": list(job.unloaded)})
        if job.priority:
            block["priority"] = job.priority
        return block

    @staticmethod
    def _swap_notes(job: Job) -> list[str]:
        notes = []
        if job.unloaded and job.ram and job.ram.get("unload"):
            from ..pack_ram import unload_note

            notes.append(unload_note(job.unloaded, job.ram.get("why") or "램 부족"))
        elif job.unloaded:
            notes.append(f"굽기 전에 이 기기 글 모델을 내렸다({', '.join(job.unloaded)}) — 다음 질문 때 Ollama 가 저절로 다시 올린다(첫 답이 그만큼 늦다)")
        elif job.ram and job.ram.get("why") and not job.ram.get("unload"):
            notes.append(job.ram["why"])
        if job.not_unloaded:
            notes.append(f"글 모델을 다 내리지 못했다({', '.join(job.not_unloaded)}) — 메모리를 나눠 써서 느렸을 수 있다")
        return notes

    def _save(self, job: Job) -> None:
        try:
            payload = job.public()
            payload["stage"] = None
            (job.folder / "job.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
