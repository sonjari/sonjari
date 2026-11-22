# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sonjari contributors
"""손자리 3D 렌더 — 스튜디오 컷 한 장 · 한 바퀴(턴테이블) · 회색 형체 (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우` §14-3).

이 폴더만 GPL-3.0-or-later 다(같은 폴더 LICENSE). 손자리 코드는 이 파일을 블렌더에 넘겨 **따로 실행**만 하고 파일로만 주고받는다.
★ 이 파일은 손자리 코드를 import 하지 않는다. 조명 · 환경 · 크기 맞추기는 같은 폴더 `beauty.py` 의 함수를 그대로 쓴다(같은 빛).

왜: 영상 1편 콘티의 「진짜 3D 컷」을 세션이 매번 스크립트로 구웠다 — 손님도 같은 사슬(3D → 렌더 → 영상)을 쓰게 도구로 내린다.
색은 손대지 않는다(톤 매핑 이름만 결과에 적는다). clay 는 재질을 회색으로 바꾼 「모양만」 판이다.

부르는 법: blender -b --factory-startup --python render.py -- <job.json>
job.json = {"input": GLB, "result": JSON, "out_dir": 폴더, "mode": "still"|"turntable", "look": "color"|"clay",
            "engine": "cycles"|"eevee", "frames": 48, "lens": 85, "width": 1024, "height": 1024,
            "azimuth": 30, "elevation": 12, "bg": [r,g,b](sRGB 0~1), "transparent": false, "samples": 48, "threads": 8}
"""
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beauty as studio  # noqa: E402 — 같은 GPL 폴더의 조명 · 환경 함수

CLAY = (0.32, 0.32, 0.31, 1.0)  # 선형 값 — 0.62 는 기본 밝은 바탕과 거의 같아 경계가 흐렸다(11-18 로봇 판)


def _clay(objs: list) -> int:
    mat = bpy.data.materials.new("sonjari_clay")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = CLAY
    bsdf.inputs["Roughness"].default_value = 0.55
    sock = bsdf.inputs.get("Metallic")
    if sock is not None:
        sock.default_value = 0.0
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(mat)
    return len(objs)


def _engine(want: str) -> str:
    """엔진 이름은 판마다 다르다(BLENDER_EEVEE_NEXT · BLENDER_EEVEE) — 목록에서 읽어 고른다."""
    items = [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    if want == "eevee":
        for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            if name in items:
                return name
    return "CYCLES"


def _settings(job: dict) -> dict:
    scene = bpy.context.scene
    engine = _engine(str(job.get("engine") or "cycles"))
    scene.render.engine = engine
    samples = int(job.get("samples") or 48)
    if engine == "CYCLES":
        scene.cycles.device = "CPU"  # 그래픽카드는 굽기 · 영상 몫
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        scene.cycles.max_bounces = 8
    else:
        ee = scene.eevee
        for name in ("taa_render_samples",):
            if hasattr(ee, name):
                setattr(ee, name, samples)
    threads = int(job.get("threads") or 0)
    if threads > 0:
        scene.render.threads_mode = "FIXED"
        scene.render.threads = threads
    scene.render.resolution_x = int(job.get("width") or 1024)
    scene.render.resolution_y = int(job.get("height") or 1024)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = bool(job.get("transparent"))
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA" if job.get("transparent") else "RGB"
    used = ""
    for vt in ("Khronos PBR Neutral", "Standard"):
        try:
            scene.view_settings.view_transform = vt
            used = vt
            break
        except TypeError:
            continue
    return {"engine": engine, "samples": samples, "view_transform": used}


def _camera(lens: float, az: float, el: float, radius: float, width: int, height: int):
    data = bpy.data.cameras.new("sonjari_cam")
    data.lens = float(lens)
    data.sensor_width = 36.0
    data.sensor_fit = "AUTO"
    data.clip_start = radius * 0.01
    data.clip_end = radius * 100.0
    # AUTO 면 센서 폭이 긴 변에 붙는다 — 짧은 변 화각으로 경계 구가 들어오게
    wide = 2 * math.atan(data.sensor_width / 2 / data.lens)
    narrow = 2 * math.atan(math.tan(wide / 2) * min(width, height) / max(width, height))
    dist = radius / math.sin(narrow / 2) * 1.06
    cam = bpy.data.objects.new("sonjari_cam", data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = studio._place(az, el, dist)
    studio._aim(cam, Vector((0, 0, 0)))
    bpy.context.scene.camera = cam
    return cam


def _spin(frames: int) -> None:
    """모델(뿌리)을 Z 축으로 한 바퀴 — 조명 · 카메라는 그대로(스튜디오 회전대). 마지막 프레임 다음이 첫 프레임이 되게 360·(n-1)/n 까지."""
    root = bpy.data.objects.get("sonjari_root")
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frames
    root.rotation_euler = (0.0, 0.0, 0.0)
    root.keyframe_insert("rotation_euler", index=2, frame=1)
    root.rotation_euler = (0.0, 0.0, 2 * math.pi * (frames - 1) / frames)
    root.keyframe_insert("rotation_euler", index=2, frame=frames)
    act = root.animation_data.action if root.animation_data else None
    curves = []
    if act is not None:
        curves = list(getattr(act, "fcurves", []) or [])
        if not curves:  # 5.x 칸 나뉜 액션
            for layer in getattr(act, "layers", []) or []:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        curves.extend(bag.fcurves)
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"


def main() -> None:
    with open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8") as fh:
        job = json.load(fh)
    started = time.time()
    out: dict = {"ok": False}
    try:
        studio._clear()
        bpy.ops.import_scene.gltf(filepath=job["input"])
        objs = studio._meshes()
        if not objs:
            raise RuntimeError("GLB 에 메시가 없다")
        radius = studio._normalize(objs)
        look = str(job.get("look") or "color")
        mats = studio._materials(objs) if look == "color" else {"clay_objects": _clay(objs)}
        info = _settings(job)
        studio._world(job.get("bg") or [0.93, 0.92, 0.90])
        studio._lights(radius)
        width, height = int(job.get("width") or 1024), int(job.get("height") or 1024)
        def num(key: str, default: float) -> float:  # 0 을 「없음」으로 읽지 않게
            value = job.get(key)
            return default if value is None else float(value)

        _camera(num("lens", 85.0), num("azimuth", 0.0), num("elevation", 10.0), radius, width, height)
        out_dir = job["out_dir"]
        os.makedirs(out_dir, exist_ok=True)
        mode = str(job.get("mode") or "still")
        t = time.time()
        if mode == "turntable":
            frames = max(2, int(job.get("frames") or 48))
            _spin(frames)
            bpy.context.scene.render.filepath = os.path.join(out_dir, "frame_")
            bpy.ops.render.render(animation=True)
            files = sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("frame_") and f.endswith(".png"))
        else:
            path = os.path.join(out_dir, "still.png")
            bpy.context.scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            files = [path] if os.path.isfile(path) else []
        out = {"ok": bool(files), "files": files, "mode": mode, "look": look, "render_sec": round(time.time() - t, 1),
               "threads": bpy.context.scene.render.threads, "objects": len(objs), "radius": round(radius, 4),
               "width": width, "height": height, **info, **mats}
        if not files:
            out["error"] = "블렌더가 그림을 안 남겼다"
    except Exception as exc:  # noqa: BLE001 — 실패도 결과 파일로
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
    out["sec"] = round(time.time() - started, 1)
    with open(job["result"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
