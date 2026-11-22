"""구운 컷 검사 — 숫자와 장면 사진 판 (2026-11-16 · 설계 §10-3 ④).

클로드는 영상을 보지 않고 이것만 읽는다. 숫자는 ffmpeg 로 푼 작은 흑백 화면(초당 8장)에서 잰다 — 모델 없음.

| 칸 | 뜻 | 왜 |
|---|---|---|
| motion_mean | 이웃 장면의 평균 밝기 차(0~255) | 5B 원본은 「거의 안 움직임」이 있었다(§10-9 아이콘) |
| still_share | 거의 안 바뀐 이웃 쌍의 비율(차 < 0.6) | 1.0 이면 정지 그림이다 |
| dark_share | 평균 밝기 < 30 인 장면 비율 | 「너무 어두워 거의 안 보임」(§10-9 직장인 원본) |
| jumps | 앞뒤보다 유난히 큰 차(중앙값의 6배 · 25 넘음) — 깨진 장면 · 번쩍임 · 갑자기 바뀐 화면 | 한 컷 안에서는 0 이어야 한다 |
| audio | 소리 줄 있나 · 평균 dB(ffmpeg volumedetect) | LTX 만 소리 — 무음(-91dB)인지 본다. 내용은 사람이 들어야 안다 |

장면 사진 판: 고르게 4장(첫 · 1/3 · 2/3 · 끝)을 2×2 로, 긴 변 1024 이하. 아래에 초를 적는다.
못 재면 None — 지어내지 않는다.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from ..video_read.scan import ffmpeg_exe

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
SAMPLE_FPS = 8
SMALL = (192, 108)
STILL_DIFF = 0.6
DARK_LEVEL = 30.0
_MEAN_DB = re.compile(r"mean_volume:\s*(-?[\d.]+)\s*dB")
_MAX_DB = re.compile(r"max_volume:\s*(-?[\d.]+)\s*dB")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")
_AUDIO_STREAM = re.compile(r"Stream #\S+.*Audio:")


def _run(cmd: list[str], *, binary: bool = False, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=not binary, timeout=timeout, check=False, creationflags=_NO_WINDOW,
                          **({} if binary else {"encoding": "utf-8", "errors": "replace"}))


def gray_frames(path: Path, exe: str, size: tuple[int, int] = SMALL, fps: int = SAMPLE_FPS) -> np.ndarray:
    width, height = size
    out = _run([exe, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf", f"fps={fps},scale={width}:{height}",
                "-f", "rawvideo", "-pix_fmt", "gray", "-"], binary=True)
    raw = out.stdout or b""
    count = len(raw) // (width * height)
    return np.frombuffer(raw[: count * width * height], dtype=np.uint8).reshape(count, height, width)


def picture_numbers(frames: np.ndarray) -> dict[str, Any]:
    """흑백 장면 묶음 → 숫자(순수 함수 · 시험은 만든 배열을 넣는다)."""
    if len(frames) == 0:
        return {"frames_read": 0, "motion_mean": None, "still_share": None, "dark_share": None, "brightness_mean": None, "jumps": None}
    f = frames.astype(np.float32)
    bright = f.mean(axis=(1, 2))
    out: dict[str, Any] = {"frames_read": len(frames), "brightness_mean": round(float(bright.mean()), 1),
                           "dark_share": round(float((bright < DARK_LEVEL).mean()), 3)}
    if len(frames) < 2:
        out.update({"motion_mean": None, "still_share": None, "jumps": None})
        return out
    diffs = np.abs(f[1:] - f[:-1]).mean(axis=(1, 2))
    median = float(np.median(diffs))
    jumps = int(((diffs > max(25.0, 6.0 * median))).sum())
    out.update({"motion_mean": round(float(diffs.mean()), 2), "still_share": round(float((diffs < STILL_DIFF).mean()), 3),
                "jumps": jumps})
    return out


def audio_numbers(path: Path, exe: str) -> dict[str, Any]:
    probe = _run([exe, "-hide_banner", "-i", str(path)])
    text = probe.stderr or ""
    if not _AUDIO_STREAM.search(text):
        return {"has_audio": False, "mean_db": None, "max_db": None}
    out = _run([exe, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"])
    log = out.stderr or ""
    mean, peak = _MEAN_DB.search(log), _MAX_DB.search(log)
    return {"has_audio": True, "mean_db": float(mean.group(1)) if mean else None, "max_db": float(peak.group(1)) if peak else None}


def duration_sec(path: Path, exe: str) -> float | None:
    found = _DURATION.search(_run([exe, "-hide_banner", "-i", str(path)]).stderr or "")
    if not found:
        return None
    h, m, s = found.groups()
    return round(int(h) * 3600 + int(m) * 60 + float(s), 2)


def scene_sheet(path: Path, out_png: Path, exe: str, *, count: int = 4, label: str = "") -> Path | None:
    """고르게 뽑은 장면 count 장을 2열 판으로. 못 만들면 None."""
    from PIL import Image, ImageDraw

    total = duration_sec(path, exe)
    if not total:
        return None
    times = [round(total * i / (count - 1) * 0.97, 2) if count > 1 else 0.0 for i in range(count)]
    shots = []
    for i, t in enumerate(times):
        one = out_png.with_name(f".{out_png.stem}_{i}.png")
        _run([exe, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", str(one)])
        if one.is_file():
            with Image.open(one) as image:
                shots.append((t, image.convert("RGB").copy()))
            one.unlink(missing_ok=True)
    if not shots:
        return None
    cell_w, cell_h = shots[0][1].size
    scale = min(1.0, 512 / max(cell_w, cell_h))
    cell_w, cell_h = int(cell_w * scale), int(cell_h * scale)
    cols = 2 if len(shots) > 1 else 1
    rows = (len(shots) + cols - 1) // cols
    pad = 22
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + pad) + (pad if label else 0)), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    top = pad if label else 0
    if label:
        draw.text((6, 4), label[:120], fill=(230, 230, 230))
    for i, (t, image) in enumerate(shots):
        x, y = (i % cols) * cell_w, top + (i // cols) * (cell_h + pad)
        sheet.paste(image.resize((cell_w, cell_h)), (x, y))
        draw.text((x + 6, y + cell_h + 4), f"{t:.1f}s", fill=(200, 200, 200))
    sheet.save(out_png)
    return out_png


def inspect(path: Path, sheet_png: Path | None = None, *, label: str = "") -> dict[str, Any]:
    """한 컷 검사. ffmpeg 가 없으면 숫자는 None 이고 그 까닭을 남긴다."""
    exe = ffmpeg_exe()
    if not exe:
        return {"ok": False, "why": "ffmpeg 가 없다 — 검사 숫자 · 장면 사진 판을 못 만들었다"}
    numbers = picture_numbers(gray_frames(path, exe))
    numbers["duration_sec"] = duration_sec(path, exe)
    numbers.update(audio_numbers(path, exe))
    out: dict[str, Any] = {"ok": True, **numbers}
    if sheet_png is not None:
        made = scene_sheet(path, sheet_png, exe, label=label)
        out["sheet"] = str(made) if made else None
    return out


# ── 어긋남(본판 ↔ 시안) ────────────────────────────────────────────────
#: 큰 배치만 보려고 16×9 색 격자로 줄인다(잔결 · 작은 움직임은 지운다).
DRIFT_GRID = (16, 9)
#: 견줄 상대 시각(처음 · 1/3 · 2/3 · 끝).
DRIFT_AT = (0.0, 1 / 3, 2 / 3, 1.0)


def color_frames(path: Path, exe: str, size: tuple[int, int] = DRIFT_GRID, fps: int = SAMPLE_FPS) -> np.ndarray:
    width, height = size
    out = _run([exe, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf", f"fps={fps},scale={width}:{height}:flags=area",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], binary=True)
    raw = out.stdout or b""
    step = width * height * 3
    count = len(raw) // step
    return np.frombuffer(raw[: count * step], dtype=np.uint8).reshape(count, height, width, 3)


def layout_diff(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    """두 영상의 색 격자 묶음(순수 함수) → 같은 상대 시각마다 평균 색 차(0~1)와 그 평균."""
    if len(a) == 0 or len(b) == 0:
        return {"at": list(DRIFT_AT), "diff": None, "mean": None}
    diffs = []
    for at in DRIFT_AT:
        fa = a[min(len(a) - 1, round(at * (len(a) - 1)))].astype(np.float32)
        fb = b[min(len(b) - 1, round(at * (len(b) - 1)))].astype(np.float32)
        diffs.append(round(float(np.abs(fa - fb).mean() / 255.0), 4))
    return {"at": [round(x, 3) for x in DRIFT_AT], "diff": diffs, "mean": round(float(np.mean(diffs)), 4)}


def drift(final: Path, draft: Path) -> dict[str, Any]:
    exe = ffmpeg_exe()
    if not exe:
        return {"ok": False, "why": "ffmpeg 가 없다 — 어긋남을 못 쟀다"}
    return {"ok": True, **layout_diff(color_frames(final, exe), color_frames(draft, exe))}


def grab_ends(clip: Path, first: Path, last: Path) -> tuple[str, str] | None:
    """영상의 첫 · 끝 프레임을 PNG 로(처음·끝 고정 재료). 못 뽑으면 None."""
    exe = ffmpeg_exe()
    if not exe:
        return None
    _run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip), "-frames:v", "1", str(first)])
    _run([exe, "-hide_banner", "-loglevel", "error", "-y", "-sseof", "-0.05", "-i", str(clip), "-update", "1", "-frames:v", "1", str(last)])
    return (str(first), str(last)) if first.is_file() and last.is_file() else None
