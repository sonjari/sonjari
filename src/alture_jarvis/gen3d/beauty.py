"""3D 색 렌더 — 조명 있는 앞 · 3/4 두 장 (2026-11-16 · 대표 지시 · 팩 잇기 시험 낙서 → 3D → 영상).

왜: 3D 판 그림(`preview.py`)은 모양 확인용 실루엣 · 조명 없는 색이라 영상 첫 장면으로 넘길 그림이 없었고, 금속성이 높은 판
(바탕색이 어두움)은 새까맣게 보였다(11-16 로봇 g3_20261116_225705_d55c7a). 여기서는 블렌더(Cycles **CPU**)로 스튜디오 3점 조명 +
환경광 아래에서 찍는다. 그래픽카드는 굽기 · 영상이 쓰므로 건드리지 않는다.

★ 라이선스 경계: 블렌더 안 코드는 `blender_scripts/beauty.py`(GPL) — 여기는 그 스크립트를 따로 실행하고 PNG · JSON 만 읽는다.
블렌더가 없으면(맥 · 손님 PC) 조용히 빠지지 않는다: not_done 에 까닭과 대신 쓸 것을 적는다.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .blender import find_blender, run_script

SIZE = 768
SAMPLES = 48
BG = (0.93, 0.92, 0.90)  # sRGB — 밝은 회백색(영상 모델이 바탕을 물체로 잘못 읽지 않게 단색)
VIEWS = ("front", "three_quarter")
NAMES = {"front": "앞", "three_quarter": "3/4"}
#: 모델 픽셀 평균 밝기(0~1)가 이보다 낮으면 「어둡다」 — 11-16 조명 없는 판에서 금속 로봇이 새까맸던 일을 다시 잡으려고.
DARK = 0.08
#: 조명을 받고도 이보다 어두운 픽셀은 「새까맣다」. 그 몫이 BLACK_SHARE 를 넘으면 텍스처 바탕색이 검정인 판(조명으로 안 풀린다).
BLACK_LUMA = 0.03
BLACK_SHARE = 0.25
INSTEAD = "대신: gen_3d_views source=model(조명 없는 색 6방향 판 · 금속성 높은 판은 어둡게 나온다) · 블렌더 4.5 이상을 깔면 이 렌더가 붙는다"


def _threads() -> int:
    """CPU 절반 — 같은 PC 에서 Strata · 다른 일이 CPU 를 쓴다."""
    return max(2, (os.cpu_count() or 4) // 2)


def measure(path: Path, bg: tuple[float, float, float] = BG) -> dict[str, Any]:
    """모델 픽셀(바탕과 다른 픽셀 · 투명 PNG 면 알파)의 몫과 평균 밝기(0~1)."""
    import numpy as np
    from PIL import Image

    img = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
    rgb, alpha = img[..., :3], img[..., 3]
    if float(alpha.min()) < 0.99:
        mask = alpha > 0.5
    else:
        mask = np.abs(rgb - np.asarray(bg, dtype=np.float32)).max(axis=2) > 0.03
    cover = float(mask.mean())
    luma = rgb @ np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
    mean = float(luma[mask].mean()) if mask.any() else 0.0
    black = float((luma[mask] < BLACK_LUMA).mean()) if mask.any() else 0.0
    return {"cover": round(cover, 4), "mean": round(mean, 4), "black": round(black, 4)}


def render_beauty(glb: Path, out_dir: Path, stem: str, *, size: int = SIZE, samples: int = SAMPLES,
                  transparent: bool = False, bg: tuple[float, float, float] = BG,
                  find: Callable[[], dict[str, Any]] | None = None,
                  run: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """{ok, files[앞, 3/4], measured{앞: {cover, mean}}, sec, not_done[]}. 실패해도 예외를 내지 않는다(굽기는 성공)."""
    started = time.time()
    found = (find or find_blender)()
    if not found.get("found"):
        return {"ok": False, "files": [], "sec": 0.0,
                "not_done": [f"색 렌더(조명 있는 앞 · 3/4)를 못 만들었다 — {found.get('why') or '블렌더를 못 찾았다'}. {INSTEAD}"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_alpha" if transparent else ""
    paths = {v: str(out_dir / f"{stem}_beauty_{v}{suffix}.png") for v in VIEWS}
    job = {"input": str(glb), "views": paths, "size": int(size), "samples": int(samples), "threads": _threads(),
           "transparent": bool(transparent), "bg": list(bg)}
    try:
        result = (run or run_script)("beauty.py", job, exe=found.get("exe"))
    except Exception as exc:  # noqa: BLE001 — 렌더는 덤, 굽기를 막지 않는다
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    files = [paths[v] for v in VIEWS if Path(paths[v]).is_file()]
    out: dict[str, Any] = {"ok": bool(result.get("ok")) and len(files) == len(VIEWS), "files": files,
                           "sec": round(time.time() - started, 1), "not_done": []}
    if not out["ok"]:
        out["not_done"].append(f"색 렌더 실패 — {result.get('error') or '블렌더가 그림을 안 남겼다'}. {INSTEAD}")
        return out
    out["engine"] = result.get("engine")
    out["samples"] = result.get("samples")
    out["view_transform"] = result.get("view_transform")
    out["metallic"] = result.get("metallic")
    measured = {}
    for v in VIEWS:
        m = measure(Path(paths[v]), bg)
        measured[NAMES[v]] = m
        if m["cover"] < 0.01:
            out["not_done"].append(f"색 렌더 {NAMES[v]}: 모델이 거의 안 보인다(그림의 {m['cover'] * 100:.1f}%) — 카메라 · 크기를 볼 것")
        elif m["black"] > BLACK_SHARE:
            out["not_done"].append(f"색 렌더 {NAMES[v]}: 모델의 {m['black'] * 100:.0f}% 가 조명을 받고도 새까맣다 — 텍스처 바탕색이 검정인 자리"
                                   "(금속도가 높게 구워진 자리일 수 있다). 조명으로는 안 풀린다 — 굽기 · 텍스처를 볼 것")
        elif m["mean"] < DARK:
            out["not_done"].append(f"색 렌더 {NAMES[v]}: 모델이 어둡다(평균 밝기 {m['mean']:.2f}) — 재질 · 조명을 볼 것")
    out["measured"] = measured
    return out
