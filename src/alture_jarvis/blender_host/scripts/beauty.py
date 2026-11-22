# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sonjari contributors
"""손자리 3D 색 렌더 — 블렌더 안에서 도는 스크립트 (2026-11-16).

이 폴더(`blender_scripts/`)만 GPL-3.0-or-later 다(같은 폴더 LICENSE). 손자리 코드는 이 파일을 블렌더에 넘겨 **따로 실행**만 하고
파일(GLB · PNG · JSON)로만 주고받는다. ★ 이 파일은 손자리 코드를 import 하지 않는다.

왜(11-16 밤 팩 잇기 시험 · 낙서 → 3D → 영상): 3D 판 그림이 전부 실루엣 · 조명 없는 색이라 영상 첫 장면으로 넘길 그림이 없었고,
금속성이 높은 판(바탕색이 어두움)은 새까맣게 보였다. 여기서는 스튜디오 3점 조명 + 환경광(금속이 비칠 위아래 밝기 차)으로
앞 · 3/4 두 장을 찍는다. 그래픽카드는 굽기 · 영상이 쓰므로 **Cycles CPU**(스레드는 받은 수만큼)로만 그린다.

부르는 법: blender -b --factory-startup --python beauty.py -- <job.json>
job.json = {"input": GLB, "result": JSON, "views": {"front": PNG, "three_quarter": PNG},
            "size": 768, "samples": 48, "threads": 8, "transparent": false, "bg": [0.93, 0.92, 0.90]}
bg 는 sRGB 0~1. 좌표: glTF 앞(+z)은 블렌더로 읽으면 -y 쪽 — 앞 카메라는 -y 에서 본다.
"""
import json
import math
import sys
import time

import bpy
from mathutils import Vector


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _meshes() -> list:
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _bbox(objs: list) -> tuple[Vector, Vector]:
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def _normalize(objs: list) -> float:
    """가운데를 원점에 · 가장 긴 변을 2 로. 돌려주는 값 = 경계 구의 반지름."""
    lo, hi = _bbox(objs)
    size = max(hi - lo) or 1.0
    s = 2.0 / size
    center = (lo + hi) / 2
    root = bpy.data.objects.new("sonjari_root", None)
    bpy.context.scene.collection.objects.link(root)
    for o in list(bpy.context.scene.objects):
        if o is not root and o.parent is None:
            o.parent = root
    root.scale = (s, s, s)
    root.location = -center * s
    bpy.context.view_layer.update()
    lo, hi = _bbox(objs)
    return (hi - lo).length / 2


def _materials(objs: list) -> dict:
    """재질이 없는 메시에는 회색 기본 재질을 준다. 금속성 값(연결 안 된 것만)을 모아 돌려준다."""
    plain = None
    metallic: list[float] = []
    base_texture = 0
    for o in objs:
        if not o.data.materials or all(m is None for m in o.data.materials):
            if plain is None:
                plain = bpy.data.materials.new("sonjari_plain")
                plain.use_nodes = True
                bsdf = next(n for n in plain.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
                bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1.0)
                bsdf.inputs["Roughness"].default_value = 0.5
            o.data.materials.clear()
            o.data.materials.append(plain)
    for m in bpy.data.materials:
        if not m.use_nodes or m.node_tree is None:
            continue
        for n in m.node_tree.nodes:
            if n.type != "BSDF_PRINCIPLED":
                continue
            sock = n.inputs.get("Metallic")
            if sock is not None and not sock.is_linked:
                metallic.append(round(float(sock.default_value), 3))
            base = n.inputs.get("Base Color")
            if base is not None and base.is_linked:
                base_texture += 1
    return {"materials": len(bpy.data.materials), "metallic": metallic, "base_color_textures": base_texture,
            "plain_added": plain is not None}


def _world(bg_srgb: list) -> None:
    """환경광: 아래 어둡고 위 밝은 띠(금속이 비칠 거리) · 카메라 광선만 단색 바탕."""
    world = bpy.data.worlds.new("sonjari_world")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    remap = nt.nodes.new("ShaderNodeMapRange")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    env = nt.nodes.new("ShaderNodeBackground")
    solid = nt.nodes.new("ShaderNodeBackground")
    path = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(coord.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], remap.inputs["Value"])
    remap.inputs["From Min"].default_value = -1.0
    remap.inputs["From Max"].default_value = 1.0
    nt.links.new(remap.outputs["Result"], ramp.inputs["Fac"])
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.35, (0.05, 0.045, 0.04, 1.0)
    els[1].position, els[1].color = 0.75, (1.0, 1.0, 1.0, 1.0)
    mid = els.new(0.52)
    mid.color = (0.35, 0.35, 0.36, 1.0)
    nt.links.new(ramp.outputs["Color"], env.inputs["Color"])
    env.inputs["Strength"].default_value = 0.7
    solid.inputs["Color"].default_value = (*[_linear(float(c)) for c in bg_srgb[:3]], 1.0)
    solid.inputs["Strength"].default_value = 1.0
    nt.links.new(path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(env.outputs["Background"], mix.inputs[1])
    nt.links.new(solid.outputs["Background"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])


def _aim(obj, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def _place(azimuth_deg: float, elevation_deg: float, dist: float) -> Vector:
    a = math.radians(azimuth_deg)
    e = math.radians(elevation_deg)
    # 방위 0 = 앞(-y) · 양수 = 모델의 왼쪽(+x)으로 돈다
    return Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * dist


def _lights(radius: float) -> None:
    """스튜디오 3점: 열쇠(앞 왼쪽 위) · 채움(앞 오른쪽 · 약하게) · 테두리(뒤 위)."""
    dist = radius * 4.0
    for name, az, el, power, size in (("key", -40.0, 35.0, 260.0, 2.5), ("fill", 55.0, 12.0, 90.0, 3.0),
                                      ("rim", 165.0, 45.0, 170.0, 2.0)):
        data = bpy.data.lights.new(f"sonjari_{name}", type="AREA")
        data.energy = power * (dist / 4.8) ** 2  # 거리가 달라도 모델에 닿는 밝기는 같게(반지름 1.2 · 거리 4.8 에서 맞춤)
        data.size = size * radius / 1.2
        light = bpy.data.objects.new(f"sonjari_{name}", data)
        bpy.context.scene.collection.objects.link(light)
        light.location = _place(az, el, dist)
        _aim(light, Vector((0, 0, 0)))


def _camera(name: str, az: float, el: float, radius: float):
    data = bpy.data.cameras.new(name)
    data.lens = 50.0
    data.sensor_width = 36.0
    data.clip_start = radius * 0.01
    data.clip_end = radius * 100.0
    fov = 2 * math.atan(data.sensor_width / 2 / data.lens)
    dist = radius / math.sin(fov / 2) * 1.04
    cam = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = _place(az, el, dist)
    _aim(cam, Vector((0, 0, 0)))
    return cam


def _settings(job: dict) -> str:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"  # 그래픽카드는 굽기 · 영상 몫 — 여기는 CPU 만
    scene.cycles.samples = int(job.get("samples") or 48)
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 8
    threads = int(job.get("threads") or 0)
    if threads > 0:
        scene.render.threads_mode = "FIXED"
        scene.render.threads = threads
    side = int(job.get("size") or 768)
    scene.render.resolution_x = side
    scene.render.resolution_y = side
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = bool(job.get("transparent"))
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA" if job.get("transparent") else "RGB"
    used = ""
    for vt in ("Khronos PBR Neutral", "Standard"):  # 바탕색을 덜 바래게(AgX 는 색을 눌러 제품 색이 흐려진다)
        try:
            scene.view_settings.view_transform = vt
            used = vt
            break
        except TypeError:
            continue
    return used


def main() -> None:
    with open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8") as fh:
        job = json.load(fh)
    started = time.time()
    out: dict = {"ok": False}
    try:
        _clear()
        bpy.ops.import_scene.gltf(filepath=job["input"])
        objs = _meshes()
        if not objs:
            raise RuntimeError("GLB 에 메시가 없다")
        radius = _normalize(objs)
        mats = _materials(objs)
        view_transform = _settings(job)
        _world(job.get("bg") or [0.93, 0.92, 0.90])
        _lights(radius)
        views = job["views"]
        angles = {"front": (0.0, 8.0), "three_quarter": (35.0, 20.0)}
        secs = {}
        for name, path in views.items():
            az, el = angles[name]
            bpy.context.scene.camera = _camera(f"sonjari_cam_{name}", az, el, radius)
            bpy.context.scene.render.filepath = path
            t = time.time()
            bpy.ops.render.render(write_still=True)
            secs[name] = round(time.time() - t, 1)
        out = {"ok": True, "files": views, "render_sec": secs, "engine": "CYCLES/CPU",
               "samples": bpy.context.scene.cycles.samples, "threads": bpy.context.scene.render.threads,
               "view_transform": view_transform, "objects": len(objs), **mats}
    except Exception as exc:  # noqa: BLE001 — 실패도 결과 파일로
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
    out["sec"] = round(time.time() - started, 1)
    with open(job["result"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)


if __name__ == "__main__":  # 블렌더 --python 으로 돌 때만 — render.py 가 조명 함수를 가져다 쓸 때는 안 돈다
    main()
