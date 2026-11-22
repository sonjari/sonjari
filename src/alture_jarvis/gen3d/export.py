"""3D 내보내기 — 유니티용 FBX · GLB (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우` §5-3 · G6 · 게임 팩과 잇기).

블렌더 안 코드는 GPL 폴더의 `export.py` — 여기는 따로 실행하고 결과 JSON 만 읽는다. 스크립트는 내보낸 파일을 **빈 장면에 다시 불러와**
잰 숫자를 돌려준다(말이 아니라 결과). 여기서는 그 숫자를 요청과 대 본다: 긴 변 = size_m · 바닥 = 0 · 가운데 = 원점 · 배율 1 ·
삼각형 ≤ 예산 · 축(FBX 를 블렌더로 다시 읽으면 유니티 Y 위 → 블렌더 Z 위 변환으로 X 90° 가 정상 — GLB 는 0°).

11-18 PC 실측(블렌더 5.2.3 · 로봇 판 145,200면 → 예산 20,000): FBX 3.7초 · GLB 3.3초 · 긴 변 1.0m · 재질 1 · 그림 2(n=1).
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .blender import find_blender, run_script

FORMATS = ("unity_fbx", "glb")
SIZE_RANGE = (0.01, 100.0)
FACES_RANGE = (200, 2_000_000)
TOL_M = 0.002


def safe_name(raw: str) -> str:
    """엔진은 이름으로 메시 · 재질을 잇는다 — 영문 · 숫자 · _ 만(빈 이름이면 Model)."""
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(raw or "")).strip("_")
    return (name[:40] or "Model") if not name[:1].isdigit() else f"M_{name[:38]}"


def check_args(fmt: str, size_m: float | None, max_faces: int | None, origin: str) -> None:
    if fmt not in FORMATS:
        raise ValueError(f"format 은 {list(FORMATS)}")
    if size_m is not None and not SIZE_RANGE[0] <= size_m <= SIZE_RANGE[1]:
        raise ValueError(f"size_m 은 {SIZE_RANGE[0]}~{SIZE_RANGE[1]}(긴 변 미터)")
    if max_faces is not None and not FACES_RANGE[0] <= max_faces <= FACES_RANGE[1]:
        raise ValueError(f"max_faces 는 {FACES_RANGE[0]}~{FACES_RANGE[1]:,}")
    if origin not in {"bottom", "keep"}:
        raise ValueError("origin 은 bottom(바닥 가운데 · 소품) · keep")


def judge(result: dict[str, Any], fmt: str, size_m: float | None, max_faces: int | None, origin: str) -> list[str]:
    """다시 읽은 숫자를 요청과 대 본다 — 어긋남마다 한 줄."""
    after = result.get("after") or {}
    bad: list[str] = []
    dims = after.get("dims_m") or []
    if not after.get("objects"):
        return ["다시 불러오니 메시가 없다"]
    if size_m and dims and abs(max(dims) - size_m) > max(TOL_M, size_m * 0.002):
        bad.append(f"긴 변이 {max(dims)}m — 요청 {size_m}m")
    if origin == "bottom":
        if abs(after.get("min_z", 0.0)) > TOL_M:
            bad.append(f"바닥이 0 이 아니다(min_z {after.get('min_z')})")
        if any(abs(v) > TOL_M for v in after.get("center_xy") or [0, 0]):
            bad.append(f"가운데가 원점이 아니다({after.get('center_xy')})")
    if any(abs(v - 1.0) > 1e-3 for v in after.get("obj_scale") or [1, 1, 1]):
        bad.append(f"물체 배율이 1 이 아니다({after.get('obj_scale')}) — 엔진에서 100배로 보일 수 있다")
    want_rot = [90.0, 0.0, 0.0] if fmt == "unity_fbx" else [0.0, 0.0, 0.0]
    rot = after.get("obj_rot_deg") or want_rot
    if any(abs(((a - b) + 180) % 360 - 180) > 0.5 for a, b in zip(rot, want_rot)):
        bad.append(f"축이 어긋났다(다시 읽은 회전 {rot} · 기대 {want_rot})")
    if max_faces and (after.get("tris") or 0) > max_faces:
        bad.append(f"삼각형 {after.get('tris'):,} — 예산 {max_faces:,} 넘음")
    return bad


def export_glb(glb: Path, out_dir: Path, *, fmt: str = "unity_fbx", name: str = "Model", size_m: float | None = None,
               max_faces: int | None = None, origin: str = "bottom",
               find: Callable[[], dict[str, Any]] | None = None,
               run: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    check_args(fmt, size_m, max_faces, origin)
    started = time.time()
    found = (find or find_blender)()
    if not found.get("found"):
        return {"ok": False, "format": fmt, "files": {}, "measured": {}, "done": [],
                "not_done": [f"내보내기 못 함 — {found.get('why') or '블렌더를 못 찾았다'}. 없으면 gen_3d_blender(action=status)로 사람 동의를 받아 받는다"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(name)
    ext = "fbx" if fmt == "unity_fbx" else "glb"
    target = out_dir / f"{name}.{ext}"
    job = {"input": str(glb), "output": str(target), "format": ext, "name": name, "size_m": size_m,
           "origin": origin, "max_faces": max_faces}
    try:
        result = (run or run_script)("export.py", job, exe=found.get("exe"), timeout=600)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    out: dict[str, Any] = {"ok": False, "format": fmt, "files": {}, "measured": {}, "done": [], "not_done": []}
    if not result.get("ok") or not target.is_file():
        out["not_done"].append(f"내보내기 실패 — {result.get('error') or '파일이 안 생겼다'}")
        return out
    after = result.get("after") or {}
    out["files"] = {ext: str(target), "bytes": target.stat().st_size}
    out["measured"] = {"before": result.get("before"), "after": after, "decimate_ratio": result.get("decimate_ratio"),
                       "scale_factor": result.get("scale_factor"), "blender": result.get("blender"),
                       "sec": round(time.time() - started, 1)}
    out["not_done"] = judge(result, fmt, size_m, max_faces, origin)
    out["ok"] = not out["not_done"]
    dims = after.get("dims_m") or [0, 0, 0]
    out["done"].append(f"{name}.{ext} · 삼각형 {after.get('tris', 0):,} · {dims[0]}×{dims[1]}×{dims[2]}m · 재질 {after.get('materials')} · 그림 {after.get('images')}")
    if fmt == "unity_fbx":
        out["unity"] = ("유니티: Assets 아래로 끌어 넣으면 된다(배율 1 · 회전 0 으로 들어오게 구웠다). 재질은 유니티가 FBX 에서 PBR 을 잘 못 만든다 — "
                        "Materials 탭 Extract 로 꺼내 URP Lit 에 그림을 다시 잇는다. 게임 팩(unity_*)으로 프로젝트에 넣을 수 있다.")
    return out
