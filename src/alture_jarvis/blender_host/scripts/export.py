# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sonjari contributors
"""손자리 3D 내보내기 — 유니티용 FBX · GLB (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우` §5-3 · G6).

이 폴더만 GPL-3.0-or-later 다(같은 폴더 LICENSE). 손자리 코드는 이 파일을 블렌더에 넘겨 따로 실행만 한다.
★ 이 파일은 손자리 코드를 import 하지 않는다. 판단(크기 · 면 수 예산)은 밖에서 정해 넘기고, 여기는 받은 대로 하고 잰다.

유니티 FBX(정적 메시): 단위 FBX All · 앞 -Z · 위 Y · Apply Transform(뿌리의 -90° X 회전 · 100 배 크기를 없앰 — 정적 메시만) ·
매끈함 Face · 삼각형(탄젠트가 엔진과 맞게) · 끝 뼈 없음 · 텍스처는 FBX 안에 넣음(파일 하나로 옮김).
내보낸 뒤 **빈 장면에 다시 불러와** 크기 · 회전 · 배율 · 삼각형 수 · 재질 · 그림 수를 잰다(재는 것은 다시 읽은 파일 — 말이 아니라 결과).

부르는 법: blender -b --factory-startup --python export.py -- <job.json>
job.json = {"input": GLB, "output": FBX|GLB 경로, "result": JSON, "format": "fbx"|"glb", "name": "Robot",
            "size_m": 1.0 | null, "origin": "bottom"|"keep", "max_faces": 20000 | null}
"""
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector


def _meshes() -> list:
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _bbox(objs: list) -> tuple:
    lo = Vector((1e18, 1e18, 1e18))
    hi = Vector((-1e18, -1e18, -1e18))
    for o in objs:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def _faces(objs: list) -> int:
    return sum(len(o.data.polygons) for o in objs)


def _tris(objs: list) -> int:
    return sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)


def _select_only(objs: list) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def _one_object(name: str) -> object:
    """가져온 메시를 하나로 합치고(유니티 소품 = 물체 하나) 변환을 적용한다. 빈 부모는 지운다."""
    objs = _meshes()
    _select_only(objs)
    # 부모(빈 노드)의 변환을 메시에 굽고 부모를 뗀다
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    if len(objs) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.context.scene.objects):
        if o is not obj and o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
    obj.name = name
    obj.data.name = name
    return obj


def _decimate(obj, max_faces: int) -> float | None:
    faces = len(obj.data.polygons)
    if not max_faces or faces <= max_faces:
        return None
    ratio = max_faces / faces
    mod = obj.modifiers.new("sonjari_decimate", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    _select_only([obj])
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return round(ratio, 4)


def _place(obj, size_m: float | None, origin: str) -> float:
    lo, hi = _bbox([obj])
    longest = max(hi - lo) or 1.0
    factor = (float(size_m) / longest) if size_m else 1.0
    if factor != 1.0:
        obj.scale = (factor, factor, factor)
        _select_only([obj])
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if origin == "bottom":
        lo, hi = _bbox([obj])
        shift = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        obj.data.transform(Matrix.Translation(-shift))
        obj.location = (0.0, 0.0, 0.0)
    return factor


def _export(fmt: str, path: str) -> None:
    if fmt == "fbx":
        bpy.ops.export_scene.fbx(
            filepath=path, use_selection=True, object_types={"MESH"}, apply_unit_scale=True,
            apply_scale_options="FBX_SCALE_ALL", bake_space_transform=True, axis_forward="-Z", axis_up="Y",
            use_mesh_modifiers=True, mesh_smooth_type="FACE", use_triangles=True, use_tspace=True,
            add_leaf_bones=False, use_custom_props=False, bake_anim=False, path_mode="COPY", embed_textures=True)
    else:
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True,
                                  export_yup=True, export_texcoords=True, export_normals=True, export_materials="EXPORT",
                                  export_animations=False)


def _verify(fmt: str, path: str) -> dict:
    """빈 장면에 다시 불러와 잰다."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if fmt == "fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    objs = _meshes()
    if not objs:
        return {"objects": 0}
    lo, hi = _bbox(objs)
    images = {i.name for i in bpy.data.images if i.size[0] > 0}
    return {"objects": len(objs), "tris": _tris(objs), "dims_m": [round(v, 4) for v in (hi - lo)],
            "min_z": round(lo.z, 4), "center_xy": [round((lo.x + hi.x) / 2, 4), round((lo.y + hi.y) / 2, 4)],
            "obj_scale": [round(v, 4) for v in objs[0].scale], "obj_rot_deg": [round(math.degrees(v), 2) for v in objs[0].rotation_euler],
            "materials": len({m.name for o in objs for m in o.data.materials if m}), "images": len(images)}


def main() -> None:
    with open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8") as fh:
        job = json.load(fh)
    started = time.time()
    out: dict = {"ok": False}
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=job["input"])
        objs = _meshes()
        if not objs:
            raise RuntimeError("GLB 에 메시가 없다")
        lo, hi = _bbox(objs)
        before = {"objects": len(objs), "faces": _faces(objs), "tris": _tris(objs), "dims": [round(v, 4) for v in (hi - lo)]}
        obj = _one_object(str(job.get("name") or "Model"))
        ratio = _decimate(obj, int(job.get("max_faces") or 0))
        factor = _place(obj, job.get("size_m"), str(job.get("origin") or "bottom"))
        _select_only([obj])
        fmt = str(job.get("format") or "fbx")
        os.makedirs(os.path.dirname(job["output"]), exist_ok=True)
        _export(fmt, job["output"])
        if not os.path.isfile(job["output"]):
            raise RuntimeError("내보낸 파일이 없다")
        out = {"ok": True, "format": fmt, "file": job["output"], "bytes": os.path.getsize(job["output"]),
               "before": before, "decimate_ratio": ratio, "scale_factor": round(factor, 6),
               "after": _verify(fmt, job["output"]), "blender": bpy.app.version_string}
    except Exception as exc:  # noqa: BLE001 — 실패도 결과 파일로
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
    out["sec"] = round(time.time() - started, 1)
    with open(job["result"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
