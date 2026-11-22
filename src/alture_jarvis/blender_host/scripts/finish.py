# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sonjari contributors
"""손자리 3D 마무리 — 블렌더 안에서 도는 스크립트 (2026-11-15).

이 폴더(`blender_scripts/`)만 GPL-3.0-or-later 다(같은 폴더 LICENSE). 블렌더 파이썬 API(bpy)를 쓰는 스크립트는 배포하면 GPL 호환이어야
한다(blender.org 라이선스 안내). 그래서 손자리 본체 · 팩 코드는 이 파일을 **블렌더에 넘겨 따로 실행**만 하고, 파일(GLB · JSON)로만 주고받는다.
★ 이 파일은 손자리 코드를 import 하지 않는다 — 판단 · 계산(어디를 고칠지)은 밖에서 하고, 여기는 받은 대로 고치기만 한다.

부르는 법: blender -b --factory-startup --python finish.py -- <job.json>
job.json = {"input": GLB, "output": GLB, "result": JSON, "ops": [ … ]}
좌표는 glTF(y 위 · 앞 +z)로 받는다 — 블렌더(z 위)로는 여기서 바꾼다: (x, y, z)_glTF → (x, -z, y)_blender.

ops:
- {"op": "erase_fill", "box": {center, axes[3], half[3]}, "rounds": 20}  상자 안 면을 지우고 구멍을 메운 뒤 메운 곳만 편다
- {"op": "erase_part", "box": {…}, "min_inside": 0.5}  상자 안에 절반 넘게 든 따로 떨어진 조각을 통째로 지운다(띠 · 고리 · 막대 조각)
- {"op": "drop_loose", "max_share": 0.01}  가장 큰 덩이 말고, 꼭짓점 몫이 이보다 작은 덩이를 지운다
- {"op": "symmetrize", "keep": "+x" | "-x"}  좌우 한쪽을 거울로 반대쪽에 덮는다(가운데는 모델 폭의 가운데)
- {"op": "smooth", "box": {…}, "rounds": 10}  상자 안 꼭짓점만 편다(잔물결 — 얇은 막에는 쓰지 말 것)
- {"op": "smooth_surface", "rounds": 8, "box": {…} (선택 · 없으면 전체), "size_mm": 80}  모양을 지키며 겉면을 편다(11-15 · 아래)

smooth_surface (2026-11-16): 같은 자리 꼭짓점을 합친 뒤(0.0001) Corrective Smooth(LENGTH_WEIGHTED · rest ORCO · use_only_smooth)를
rounds 번 건다. 11-15 테디 · 개구리 그림 대조: 30번은 계단 줄무늬를 다 지우지만 입선 · 눈 새김 · 털결까지 지웠고, 8번이 줄무늬는 대부분
지우고 입선 · 눈은 남겼다(그림으로만 판단 · n=2). 결과에 꼭짓점 이동량(긴 변을 size_mm 로 놓은 mm)과 부피 변화를 남긴다.
"""
import json
import sys

import bmesh
import bpy
from mathutils import Vector


def g2b(v):
    return Vector((v[0], -v[2], v[1]))


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.import_scene.gltf(filepath=path, merge_vertices=True)
    except TypeError:  # 옛 판에는 merge_vertices 가 없다
        bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("GLB 에 메시가 없다")
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def in_box(co, box):
    c = g2b(box["center"])
    axes = [g2b(a) for a in box["axes"]]
    d = co - c
    return all(abs(d.dot(a)) <= h for a, h in zip(axes, box["half"]))


def parts_of(bm):
    seen, parts = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, comp = [v], []
        seen.add(v.index)
        while stack:
            x = stack.pop()
            comp.append(x)
            for e in x.link_edges:
                y = e.other_vert(x)
                if y.index not in seen:
                    seen.add(y.index)
                    stack.append(y)
        parts.append(comp)
    return parts


def relax(bm, verts, rounds, fixed=()):
    fixed = set(fixed)
    movable = [v for v in verts if v not in fixed and v.is_valid]
    for _ in range(int(rounds)):
        new = {}
        for v in movable:
            nb = [e.other_vert(v).co for e in v.link_edges]
            if nb:
                avg = sum(nb, Vector()) / len(nb)
                new[v] = v.co.lerp(avg, 0.6)
        for v, co in new.items():
            v.co = co


def op_erase_fill(bm, op):
    bm.verts.ensure_lookup_table()
    hit = [v for v in bm.verts if in_box(v.co, op["box"])]
    if not hit:
        return {"op": "erase_fill", "erased_verts": 0, "note": "상자 안에 꼭짓점이 없다"}
    hit_set = set(hit)
    ring = {e.other_vert(v) for v in hit for e in v.link_edges} - hit_set
    faces = list({f for v in hit for f in v.link_faces})
    n_faces = len(faces)
    bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")
    loose = [v for v in hit if v.is_valid and not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    edges = [e for e in bm.edges if e.is_boundary and any(v in ring for v in e.verts)]
    filled = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
    new_faces = filled.get("faces", [])
    if new_faces:
        tri = bmesh.ops.triangulate(bm, faces=new_faces)
        new_faces = tri.get("faces", new_faces)
        # 납작한 막을 잘게 나눠 둘레에서 이어지게 편다(둘레 꼭짓점은 고정)
        inner_edges = list({e for f in new_faces for e in f.edges})
        sub = bmesh.ops.subdivide_edges(bm, edges=inner_edges, cuts=2, use_grid_fill=True)
        patch = {v for f in new_faces if f.is_valid for v in f.verts}
        patch |= {g for g in sub.get("geom_inner", []) if isinstance(g, bmesh.types.BMVert)}
        relax(bm, list(patch), op.get("rounds", 20), fixed=ring)
    return {"op": "erase_fill", "erased_verts": len(hit), "erased_faces": n_faces, "filled_faces": len(new_faces),
            "open_edges_left": sum(1 for e in bm.edges if e.is_boundary)}


def op_drop_loose(bm, op):
    parts = parts_of(bm)
    if len(parts) <= 1:
        return {"op": "drop_loose", "dropped_parts": 0, "parts": len(parts)}
    total = sum(len(p) for p in parts)
    parts.sort(key=len, reverse=True)
    drop = [p for p in parts[1:] if len(p) / total < float(op.get("max_share", 0.01))]
    bmesh.ops.delete(bm, geom=[v for p in drop for v in p], context="VERTS")
    return {"op": "drop_loose", "dropped_parts": len(drop), "dropped_verts": sum(len(p) for p in drop), "parts_before": len(parts)}


def op_erase_part(bm, op):
    """상자 안에 꼭짓점이 절반 넘게 든 **따로 떨어진 조각**을 통째로 지운다(가장 큰 덩이는 절대 안 지움).
    11-15 리락쿠마: 뒷목 띠는 몸과 떨어진 얇은 고리 조각(꼭짓점 976)이었다 — 겉을 지우고 메우면 머리 겉만 지워졌다."""
    parts = parts_of(bm)
    parts.sort(key=len, reverse=True)
    min_inside = float(op.get("min_inside", 0.5))
    gone = []
    for p in parts[1:]:
        inside = sum(1 for v in p if in_box(v.co, op["box"]))
        if inside / len(p) >= min_inside:
            xs = [v.co for v in p]
            lo = [round(min(c[i] for c in xs), 4) for i in range(3)]
            hi = [round(max(c[i] for c in xs), 4) for i in range(3)]
            gone.append({"verts": len(p), "inside_share": round(inside / len(p), 2), "bbox_blender": [lo, hi]})
            bmesh.ops.delete(bm, geom=list(p), context="VERTS")
    return {"op": "erase_part", "erased_parts": len(gone), "parts": gone, "parts_before": len(parts)}


def op_smooth(bm, op):
    verts = [v for v in bm.verts if in_box(v.co, op["box"])]
    relax(bm, verts, op.get("rounds", 10))
    return {"op": "smooth", "verts": len(verts)}


def _pct(sorted_values, q):
    if not sorted_values:
        return 0.0
    return sorted_values[min(len(sorted_values) - 1, int(round(q * (len(sorted_values) - 1))))]


def op_smooth_surface(obj, op):
    """모양을 지키며 겉면 펴기 — 계단 줄무늬(뒷단계 다시 뜨기 · 면 줄이기 자국)를 지운다. 상자를 주면 그 안만."""
    rounds = max(1, min(60, int(op.get("rounds", 8))))
    size_mm = float(op.get("size_mm", 80.0))
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    n0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=float(op.get("merge_dist", 0.0001)))
    merged = n0 - len(bm.verts)
    vol0 = abs(bm.calc_volume(signed=True))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    before = [v.co.copy() for v in obj.data.vertices]
    group = None
    if op.get("box"):
        idx = [v.index for v in obj.data.vertices if in_box(v.co, op["box"])]
        if not idx:
            return {"op": "smooth_surface", "rounds": rounds, "verts": 0, "merged_verts": merged, "note": "상자 안에 꼭짓점이 없다"}
        group = obj.vertex_groups.new(name="sonjari_smooth")
        group.add(idx, 1.0, "REPLACE")
    mod = obj.modifiers.new("sonjari_smooth_surface", "CORRECTIVE_SMOOTH")
    mod.iterations = rounds
    mod.smooth_type = "LENGTH_WEIGHTED"
    mod.rest_source = "ORCO"
    mod.use_only_smooth = True
    if group is not None:
        mod.vertex_group = group.name
    bpy.ops.object.modifier_apply(modifier=mod.name)
    if group is not None:
        obj.vertex_groups.remove(group)
    moves = sorted((v.co - before[i]).length for i, v in enumerate(obj.data.vertices))
    lo = [min(c[i] for c in before) for i in range(3)]
    hi = [max(c[i] for c in before) for i in range(3)]
    long_side = max(hi[i] - lo[i] for i in range(3)) or 1.0
    mm = size_mm / long_side
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    vol1 = abs(bm.calc_volume(signed=True))
    closed = not any(e.is_boundary for e in bm.edges)
    bm.free()
    return {
        "op": "smooth_surface", "rounds": rounds, "verts": sum(1 for d in moves if d > 0) if group is not None else len(moves),
        "merged_verts": merged,
        "move_mm": {"median": round(_pct(moves, 0.5) * mm, 4), "p95": round(_pct(moves, 0.95) * mm, 4),
                    "max": round(moves[-1] * mm if moves else 0.0, 4), "long_side_mm": size_mm},
        "volume_change_pct": round((vol1 - vol0) / vol0 * 100, 3) if vol0 > 0 else None,
        "volume_closed": closed,
    }


def op_symmetrize(obj, op):
    keep = op.get("keep", "+x")
    xs = [v.co.x for v in obj.data.vertices]
    mid = (min(xs) + max(xs)) / 2
    for v in obj.data.vertices:
        v.co.x -= mid
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.symmetrize(direction="POSITIVE_X" if keep == "+x" else "NEGATIVE_X")
    bpy.ops.object.mode_set(mode="OBJECT")
    for v in obj.data.vertices:
        v.co.x += mid
    return {"op": "symmetrize", "keep": keep, "mid_x": round(mid, 5)}


def main():
    job = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    obj = load(job["input"])
    done = []
    before = {"verts": len(obj.data.vertices), "faces": len(obj.data.polygons)}
    for op in job.get("ops", []):
        if op["op"] == "symmetrize":
            done.append(op_symmetrize(obj, op))
            continue
        if op["op"] == "smooth_surface":
            done.append(op_smooth_surface(obj, op))
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        if op["op"] == "erase_fill":
            done.append(op_erase_fill(bm, op))
        elif op["op"] == "erase_part":
            done.append(op_erase_part(bm, op))
        elif op["op"] == "drop_loose":
            done.append(op_drop_loose(bm, op))
        elif op["op"] == "smooth":
            done.append(op_smooth(bm, op))
        else:
            raise RuntimeError(f"모르는 작업: {op['op']}")
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    after = {"verts": len(bm.verts), "faces": len(bm.faces), "parts": len(parts_of(bm)),
             "open_edges": sum(1 for e in bm.edges if e.is_boundary)}
    bm.free()
    bpy.ops.export_scene.gltf(filepath=job["output"], export_format="GLB")
    json.dump({"ok": True, "before": before, "after": after, "ops": done, "blender": bpy.app.version_string},
              open(job["result"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 결과 파일에 까닭을 남기고 끝낸다
        try:
            job = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
            json.dump({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, open(job["result"], "w", encoding="utf-8"), ensure_ascii=False)
        finally:
            sys.exit(1)
