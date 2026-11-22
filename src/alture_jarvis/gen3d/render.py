"""3D 렌더 — 스튜디오 컷 한 장 · 한 바퀴(턴테이블) · 회색 형체 (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우` §14-3).

왜: 영상 1편 콘티의 「진짜 3D 컷」을 세션이 매번 블렌더 스크립트로 구웠다. 손님도 같은 사슬(3D → 렌더 → 영상 팩 첫/끝 그림)을 쓰게
도구로 내린다. 블렌더 안 코드는 GPL 폴더의 `render.py` — 여기는 따로 실행하고 PNG · JSON 만 읽는다.

영수증 숫자는 **파일을 직접 열어 잰 것만**(11-14 원칙): 프레임 수 · 해상도 · 모델이 그림에서 차지하는 몫 · 턴테이블 이음새(끝 → 첫 차이를
옆 프레임끼리 차이와 견줌). 색은 손대지 않는다 — 톤 매핑 이름만 적는다.

엔진 기본은 Cycles CPU(11-18 PC 실측 · 로봇 판 768px: Cycles 24샘플 8장 20.6초 · EEVEE 8장 16.7초 · 그림 차이 눈으로 거의 없음 · n=1).
그래픽카드를 안 써서 PC 에서 굽기와 겹쳐도 서로 안 막는다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .beauty import BG, measure
from .blender import find_blender, run_script

MODES = ("still", "turntable")
LOOKS = ("color", "clay")
ENGINES = ("cycles", "eevee")
FRAMES_RANGE = (8, 240)
SIZE_RANGE = (256, 2048)
LENS_RANGE = (18.0, 200.0)
FPS = 24
DEFAULTS = {"still": {"lens": 85.0, "samples": 48, "elevation": 10.0, "azimuth": 30.0},
            "turntable": {"lens": 50.0, "samples": 24, "elevation": 12.0, "azimuth": 0.0}}
#: 블렌더 시간 한도 — 프레임마다 이만큼 + 켜기 몫. 11-18 실측 768px 한 장 2.6초(Cycles 24) → 넉넉히.
SEC_PER_FRAME = 12.0
START_SEC = 60.0


def _hex(color: str) -> tuple[float, float, float]:
    raw = str(color or "").strip().lstrip("#")
    if len(raw) != 6 or any(c not in "0123456789abcdefABCDEF" for c in raw):
        raise ValueError(f"background 는 #RRGGBB — 받은 것: {color}")
    return tuple(int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def check_args(mode: str, look: str, engine: str, frames: int, width: int, height: int, lens: float | None) -> None:
    if mode not in MODES:
        raise ValueError(f"mode 는 {list(MODES)}")
    if look not in LOOKS:
        raise ValueError(f"look 은 {list(LOOKS)}")
    if engine not in ENGINES:
        raise ValueError(f"engine 은 {list(ENGINES)}")
    if mode == "turntable" and not FRAMES_RANGE[0] <= frames <= FRAMES_RANGE[1]:
        raise ValueError(f"frames 는 {FRAMES_RANGE[0]}~{FRAMES_RANGE[1]}")
    for name, value in (("width", width), ("height", height)):
        if not SIZE_RANGE[0] <= value <= SIZE_RANGE[1]:
            raise ValueError(f"{name} 는 {SIZE_RANGE[0]}~{SIZE_RANGE[1]}")
    if lens is not None and not LENS_RANGE[0] <= lens <= LENS_RANGE[1]:
        raise ValueError(f"lens 는 {LENS_RANGE[0]:g}~{LENS_RANGE[1]:g}mm")


#: 이음새 판정 — 끝→첫 차이를 옆 프레임 차이의 범위(최소~최대)에 댄다. 모델 모양 따라 옆 차이가 오르내리므로(11-18 로봇 8장:
#: 0.038~0.067 번갈아) 가운데값 하나에 대면 멀쩡한 판도 걸린다 — 처음 잣대(가운데값 × 2)가 그 판을 1.58 · 상자를 2.34 로 걸었다.
SEAM_JUMP = 1.5   # 최대의 이만큼 배를 넘으면 튐
SEAM_STALL = 0.3  # 최소의 이만큼 배보다 작으면 멈칫(같은 그림 두 번 — 0° 와 360° 를 둘 다 넣은 실수)


def seam(files: list[Path]) -> dict[str, Any] | None:
    """턴테이블 이음새: 끝 → 첫 프레임 차이(평균 절대값)를 옆 프레임끼리 차이의 범위와 견준다."""
    if len(files) < 3:
        return None
    import numpy as np
    from PIL import Image

    def load(p: Path) -> Any:
        return np.asarray(Image.open(p).convert("RGB").resize((128, 128)), dtype=np.float32) / 255.0

    frames = [load(p) for p in files]
    steps = [float(np.abs(frames[i + 1] - frames[i]).mean()) for i in range(len(frames) - 1)]
    wrap = float(np.abs(frames[0] - frames[-1]).mean())
    lo, hi = min(steps), max(steps)
    verdict = "jump" if wrap > hi * SEAM_JUMP else "stall" if wrap < lo * SEAM_STALL else "ok"
    return {"wrap_diff": round(wrap, 4), "step_min": round(lo, 4), "step_max": round(hi, 4), "verdict": verdict}


def to_mp4(folder: Path, out: Path, fps: int = FPS) -> tuple[Path | None, str]:
    ff = shutil.which("ffmpeg")
    if not ff:
        return None, "ffmpeg 를 못 찾아 mp4 는 안 만들었다(PNG 프레임은 있다)"
    cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(folder / "frame_%04d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(out)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001
        return None, f"mp4 실패 — {type(exc).__name__}: {exc}"[:200]
    if proc.returncode != 0 or not out.is_file():
        return None, f"mp4 실패(rc {proc.returncode}): {(proc.stderr or b'').decode('utf-8', 'replace')[-200:]}"
    return out, ""


def render_glb(glb: Path, out_dir: Path, *, mode: str = "still", look: str = "color", engine: str = "cycles",
               frames: int = 48, width: int = 1024, height: int = 1024, lens: float | None = None,
               azimuth: float | None = None, elevation: float | None = None, background: str | None = None,
               transparent: bool = False, samples: int | None = None, mp4: bool = True,
               find: Callable[[], dict[str, Any]] | None = None,
               run: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """{ok, mode, look, files{frames|still, mp4}, measured{…}, done[], not_done[]}. 블렌더가 없으면 ok=False · not_done 에 까닭."""
    check_args(mode, look, engine, frames, width, height, lens)
    base = DEFAULTS[mode]
    bg = _hex(background) if background else BG
    started = time.time()
    found = (find or find_blender)()
    if not found.get("found"):
        return {"ok": False, "mode": mode, "look": look, "files": {}, "measured": {}, "done": [],
                "not_done": [f"렌더 못 함 — {found.get('why') or '블렌더를 못 찾았다'}. 없으면 gen_3d_blender(action=status)로 사람 동의를 받아 받는다 · 이미 깔려 있으면 JARVIS_BLENDER 에 경로"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    job = {"input": str(glb), "out_dir": str(out_dir), "mode": mode, "look": look, "engine": engine,
           "frames": int(frames), "lens": float(lens if lens is not None else base["lens"]),
           "width": int(width), "height": int(height),
           "azimuth": float(azimuth if azimuth is not None else base["azimuth"]),
           "elevation": float(elevation if elevation is not None else base["elevation"]),
           "bg": list(bg), "transparent": bool(transparent), "samples": int(samples or base["samples"]),
           "threads": max(2, (os.cpu_count() or 4) // 2)}
    timeout = int(START_SEC + SEC_PER_FRAME * (frames if mode == "turntable" else 1) * max(1.0, width * height / (768 * 768)))
    try:
        result = (run or run_script)("render.py", job, exe=found.get("exe"), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — 실패도 영수증으로
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    out: dict[str, Any] = {"ok": False, "mode": mode, "look": look, "files": {}, "measured": {}, "done": [], "not_done": [],
                           "settings": {k: job[k] for k in ("engine", "lens", "azimuth", "elevation", "samples", "width", "height", "transparent")}}
    if mode == "turntable":
        pngs = sorted(out_dir.glob("frame_*.png"))
    else:
        pngs = [p for p in [out_dir / "still.png"] if p.is_file()]
    if not result.get("ok") or not pngs:
        out["not_done"].append(f"렌더 실패 — {result.get('error') or '블렌더가 그림을 안 남겼다'}")
        out["measured"]["sec"] = round(time.time() - started, 1)
        return out
    from PIL import Image

    with Image.open(pngs[0]) as im:
        real_size = list(im.size)
    measured: dict[str, Any] = {
        "frames": len(pngs), "size": real_size, "engine": result.get("engine"), "samples": result.get("samples"),
        "view_transform": result.get("view_transform"), "color_graded": False,
        "render_sec": result.get("render_sec"), "sec": round(time.time() - started, 1),
        "sec_per_frame": round(float(result.get("render_sec") or 0) / len(pngs), 2),
    }
    picks = {"첫": pngs[0]} if len(pngs) == 1 else {"첫": pngs[0], "가운데": pngs[len(pngs) // 2]}
    measured["cover"] = {name: measure(p, bg)["cover"] for name, p in picks.items()}
    if real_size != [width, height]:
        out["not_done"].append(f"그림 크기가 요청({width}×{height})과 다르다: {real_size[0]}×{real_size[1]}")
    if mode == "turntable" and len(pngs) != frames:
        out["not_done"].append(f"프레임이 {frames}장이어야 하는데 {len(pngs)}장")
    for name, cover in measured["cover"].items():
        if cover < 0.01:
            out["not_done"].append(f"{name} 프레임에 모델이 거의 안 보인다(그림의 {cover * 100:.1f}%) — 카메라 · 크기를 볼 것")
    files: dict[str, Any] = {}
    if mode == "turntable":
        # 경로를 다 붓지 않는다(48줄이면 클로드 창만 차지) — 폴더 · 첫 · 가운데 · 끝 · 이름 꼴
        files["frames"] = {"count": len(pngs), "folder": str(out_dir), "pattern": "frame_%04d.png", "first": str(pngs[0]),
                           "middle": str(pngs[len(pngs) // 2]), "last": str(pngs[-1])}
        measured["seam"] = seam(pngs)
        cut = measured["seam"] or {}
        if cut.get("verdict") == "jump":
            out["not_done"].append(f"한 바퀴 이음새가 튄다(끝→첫 차이 {cut['wrap_diff']} · 옆 프레임 차이 최대 {cut['step_max']})")
        elif cut.get("verdict") == "stall":
            out["not_done"].append(f"한 바퀴 이음새에서 멈칫한다(끝과 첫이 거의 같은 그림 — 차이 {cut['wrap_diff']} · 옆 최소 {cut['step_min']})")
        if mp4:
            path, why = to_mp4(out_dir, out_dir / "turntable.mp4")
            if path:
                files["mp4"] = str(path)
                measured["mp4_sec"] = round(len(pngs) / FPS, 2)
            else:
                out["not_done"].append(why)
    else:
        files["still"] = str(pngs[0])
    if result.get("look") == "color" and result.get("plain_added"):
        out["not_done"].append("재질 없는 메시가 있어 회색 기본 재질을 줬다(구운 색이 아닌 자리)")
    out["done"].append(f"{'한 바퀴 ' + str(len(pngs)) + '장' if mode == 'turntable' else '한 장'} · {look} · {measured['engine']} · {real_size[0]}×{real_size[1]}")
    out.update(ok=True, files=files, measured=measured)
    return out
