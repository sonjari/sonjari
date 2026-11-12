# -*- coding: utf-8 -*-
"""애니메이터 팩 — 블렌더 쪽 다리 (2026-11-06).

★ 까닭. 맥스는 손자리가 직접 부를 수 없어(3dsmax-mcp 가 한 줄을 보낸다) 사람 · 클로드가 사이에 껴야 했다. 블렌더는 무료이고 명령줄로
  창 없이 돈다 — **손자리가 직접 띄워 끝까지 한다.** 클로드는 말 · 표 · 「해」만(완성 기준 2층 「클로드가 짠 코드 0줄」).
  그리고 이 PC 맥스는 교육용이라 영리 목적(제품 개발 · 홍보 화면)이 약관 밖이다(11-06 확인) → 공개 시연 · 개발은 블렌더로.

나눔은 맥스 판과 같다: 블렌더 스크립트는 **읽기(뼈 행렬 · 몸 메시 점 → 파일)** 와 **쓰기(계산된 방향을 키로)** 만 한다.
판정 · 계산은 `fitcheck.py` 한 곳(맥스와 같이 쓴다) — 그래서 두 프로그램 결과가 어긋날 수 없다.

- 원본 .blend 는 덮어쓰지 않는다. 쓰기는 늘 새 파일(`<이름>_sonjari_<무엇>.blend`).
- 뼈 이름은 흔한 꼴 셋(리지파이 게임 뼈대 · 리지파이 DEF- · 믹사모)을 자동으로 맞춘다. 못 맞추면 무엇이 없는지 말한다.
- 바이페드와 축이 다르다: 블렌더 뼈의 길이 방향은 Y. 읽을 때 (Y, X, Z, 머리 자리) 순으로 줄을 놓아 fitcheck 의 「row1 = 길이 방향」을 맞춘다.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
from pathlib import Path
from typing import Any

#: fitcheck 의 이름(바이페드 꼬리) → 블렌더 뼈 후보(앞이 이긴다). {s} 는 L/R, {S} 는 Left/Right.
BONE_MAP: dict[str, list[str]] = {
    "Pelvis": ["spine", "DEF-spine", "mixamorig:Hips", "Hips", "hips", "pelvis"],
    "Spine": ["spine.001", "DEF-spine.001", "mixamorig:Spine", "Spine", "spine_01"],
    "Spine1": ["spine.002", "DEF-spine.002", "mixamorig:Spine1", "Spine1", "spine_02"],
    "Spine2": ["spine.003", "DEF-spine.003", "mixamorig:Spine2", "Spine2", "spine_03", "chest"],
    "Neck": ["spine.004", "DEF-spine.004", "mixamorig:Neck", "Neck", "neck", "neck_01"],
    "Head": ["spine.006", "DEF-spine.006", "mixamorig:Head", "Head", "head"],
    "{s} UpperArm": ["upper_arm.{s}", "DEF-upper_arm.{s}", "mixamorig:{S}Arm", "{S}Arm", "upperarm_{l}"],
    "{s} Forearm": ["forearm.{s}", "DEF-forearm.{s}", "mixamorig:{S}ForeArm", "{S}ForeArm", "lowerarm_{l}"],
    "{s} Hand": ["hand.{s}", "DEF-hand.{s}", "mixamorig:{S}Hand", "{S}Hand", "hand_{l}"],
    "{s} Thigh": ["thigh.{s}", "DEF-thigh.{s}", "mixamorig:{S}UpLeg", "{S}UpLeg", "thigh_{l}"],
    "{s} Calf": ["shin.{s}", "DEF-shin.{s}", "mixamorig:{S}Leg", "{S}Leg", "calf_{l}"],
    "{s} Foot": ["foot.{s}", "DEF-foot.{s}", "mixamorig:{S}Foot", "{S}Foot", "foot_{l}"],
}
REQUIRED = ["Pelvis", "Spine", "Head", "L UpperArm", "L Forearm", "L Hand", "R UpperArm", "R Forearm", "R Hand"]


def bone_candidates() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, cands in BONE_MAP.items():
        if "{s}" in key:
            for s, S, l in (("L", "Left", "l"), ("R", "Right", "r")):
                out[key.format(s=s)] = [c.format(s=s, S=S, l=l) for c in cands]
        else:
            out[key] = cands
    return out


def find_blender() -> str | None:
    """블렌더 실행 파일 — 설정(JARVIS_BLENDER)이 먼저, 그다음 흔한 설치 자리(새 판이 이긴다)."""
    from ..config import setting

    given = setting("JARVIS_BLENDER", "").strip().strip('"')
    if given and Path(given).is_file():
        return given
    pats = [r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender Foundation\Blender*\blender.exe"),
            r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
            r"D:\tools\blender-*\blender.exe"]
    found = [p for pat in pats for p in glob.glob(pat)]

    def ver(p: str) -> tuple[int, ...]:
        import re
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", p)
        return tuple(int(x or 0) for x in m.groups()) if m else (0,)

    return sorted(found, key=ver)[-1] if found else None


# ── 블렌더 안에서 도는 스크립트(읽기 · 쓰기) ────────────────────────────────────────

_COMMON = r'''
import bpy, json, sys
from mathutils import Matrix, Vector
A = json.loads(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8").read())
def pick_rig(name):
    if name:
        o = bpy.data.objects.get(name)
        if o is None or o.type != "ARMATURE":
            raise SystemExit("@@ERR@@ 그런 뼈대가 없다: " + name)
        return o
    rigs = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    # 메시가 armature 수정자로 붙어 있는 뼈대 · 뼈가 많은 것 먼저
    def score(o):
        skinned = sum(1 for m in bpy.data.objects if m.type == "MESH" for md in m.modifiers if md.type == "ARMATURE" and md.object == o)
        return (skinned, len(o.data.bones))
    if not rigs:
        raise SystemExit("@@ERR@@ 장면에 뼈대(armature)가 없다")
    return sorted(rigs, key=score)[-1]
def resolve(rig, cands):
    names = set(b.name for b in rig.data.bones)
    m = {}
    for k, cs in cands.items():
        for c in cs:
            if c in names:
                m[k] = c; break
    return m
def rows(rig, pb):
    M = rig.matrix_world @ pb.matrix
    x, y, z = (M.col[i].to_3d().normalized() for i in range(3))
    h = M.to_translation()
    return [y.x, y.y, y.z, x.x, x.y, x.z, z.x, z.y, z.z, h.x, h.y, h.z]
def bone_keys(rig, bone):
    ad = rig.animation_data
    act = ad.action if ad else None
    if act is None:
        return []
    path = 'pose.bones["%s"].' % bone
    fcs = []
    for l in getattr(act, "layers", []):
        for st in l.strips:
            for cb in getattr(st, "channelbags", []):
                fcs += [fc for fc in cb.fcurves if fc.data_path.startswith(path) and "rotation" in fc.data_path]
    try:
        fcs += [fc for fc in act.fcurves if fc.data_path.startswith(path) and "rotation" in fc.data_path]
    except Exception:
        pass
    return sorted({int(round(kp.co[0])) for fc in fcs for kp in fc.keyframe_points})
'''

READ_PY = _COMMON + r'''
rig = pick_rig(A.get("armature"))
bmap = resolve(rig, A["candidates"])
missing = [k for k in A["required"] if k not in bmap]
if missing:
    print("@@JSON@@" + json.dumps({"ok": False, "error": "뼈 이름을 못 맞춤: " + ", ".join(missing), "armature": rig.name,
          "bones": [b.name for b in rig.data.bones][:80]}, ensure_ascii=False)); raise SystemExit(0)
names = list(bmap)
sc = bpy.context.scene
act = rig.animation_data.action if rig.animation_data else None
S = A.get("start"); E = A.get("end")
if S is None or E is None:
    if act is not None:
        S, E = int(act.frame_range[0]), int(act.frame_range[1])
    else:
        S, E = sc.frame_start, sc.frame_end
constrained = [bmap[k] for k in names if len(rig.pose.bones[bmap[k]].constraints)]
# 기준 자세(쉬는 자세)에서 뼈 · 메시
rig.data.pose_position = "REST"; bpy.context.view_layer.update()
fig = [1] + [rows(rig, rig.pose.bones[bmap[k]]) for k in names]
dg = bpy.context.evaluated_depsgraph_get()
verts = []
# 11-10: 점마다 가장 무거운 스킨 가중치의 뼈(fitcheck 이름 · 우리 뼈가 아니면 "x" · 가중치 없음 "") — 머리카락 · 리본 · 장식을 몸 부피에서 가른다
inv = {}
for k, b in bmap.items():
    inv[b] = k
    inv[b.split("-", 1)[1] if b.startswith(("DEF-", "ORG-")) else b] = k
def vlabel(o, vx):
    best, w = None, 0.0
    for g in vx.groups:
        if g.weight > w and g.group < len(o.vertex_groups):
            best, w = o.vertex_groups[g.group].name, g.weight
    if best is None:
        return ""
    plain = best.split("-", 1)[1] if best.startswith(("DEF-", "ORG-")) else best
    return inv.get(best) or inv.get(plain) or ("x:" + best)
# 우리 뼈가 아닌 뼈(뱃살 출렁 · 머리카락 · 리본 …) → 가장 가까운 우리 조상 뼈. 몸인지 장식인지는 fitcheck 가 거리로 가른다
xparent = {}
for b in rig.data.bones:
    if b.name in inv:
        continue
    p = b.parent
    while p is not None and p.name not in inv:
        p = p.parent
    xparent[b.name] = inv[p.name] if p is not None else ""
vbones, vmesh, meshes = [], [], []
for o in bpy.data.objects:
    if o.type != "MESH" or o.hide_get() or o.hide_render:
        continue
    if not any(md.type == "ARMATURE" and md.object == rig for md in o.modifiers):
        continue
    # 외곽선(Solidify) · 세분화 같은 수정자는 잠깐 끄고 뼈대 변형만 본다(11-10: 시험 캐릭터 외곽선이 점을 두 배로 만들어 껍데기까지 몸으로 쟀다).
    # 저장하지 않으니 파일은 그대로다.
    off = [md for md in o.modifiers if md.type != "ARMATURE" and md.show_viewport]
    for md in off:
        md.show_viewport = False
    if off:
        bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg); me = ev.to_mesh()
    step = max(1, len(me.vertices) // 6000 + (1 if len(me.vertices) > 6000 else 0))
    W = o.matrix_world
    same = len(me.vertices) == len(o.data.vertices)        # 그래도 위상이 다르면 가중치를 못 맞춘다 → 빈 이름(가까운 뼈로)
    for i in range(0, len(me.vertices), step):
        p = W @ me.vertices[i].co
        verts.append([round(p.x, 5), round(p.y, 5), round(p.z, 5)])
        vbones.append(vlabel(o, o.data.vertices[i]) if same else "")
        vmesh.append(len(meshes))
    meshes.append(o.name)
    ev.to_mesh_clear()
    for md in off:
        md.show_viewport = True
    if off:
        bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
rig.data.pose_position = "POSE"; bpy.context.view_layer.update()
frames = []
for f in range(int(S), int(E) + 1):
    sc.frame_set(f)
    frames.append([f] + [rows(rig, rig.pose.bones[bmap[k]]) for k in names])
keys = {"L": [k for k in bone_keys(rig, bmap["L UpperArm"]) if S <= k <= E],
        "R": [k for k in bone_keys(rig, bmap["R UpperArm"]) if S <= k <= E]}
for k in ("L Thigh", "R Thigh", "Spine"):                  # 11-10 다리 자동 수정 — 허벅지 · 척추도 원래 키 자리에서만
    if k in bmap:
        keys[k] = [f for f in bone_keys(rig, bmap[k]) if S <= f <= E]
json.dump({"ok": True, "app": "blender", "armature": rig.name, "map": bmap, "bones": names, "start": int(S), "end": int(E),
           "ref": int(S), "fig": fig, "frames": frames, "verts": verts, "vbones": vbones, "vmesh": vmesh, "meshes": meshes, "xparent": xparent,
           "keys": keys, "constrained": constrained},
          open(A["out"], "w", encoding="utf-8"))
print("@@JSON@@" + json.dumps({"ok": True, "frames": len(frames), "verts": len(verts), "armature": rig.name,
      "constrained": constrained}, ensure_ascii=False))
'''

WRITE_FIX_PY = _COMMON + r'''
rig = pick_rig(A.get("armature"))
bmap = A["map"]
sc = bpy.context.scene
W2A = rig.matrix_world.inverted().to_3x3()
n = 0; worst = 1.0
for bone, f, d in A["items"]:                              # fitcheck.fix_items: 척추 → 허벅지 → 위팔 순
    pb = rig.pose.bones[bmap[bone]]
    sc.frame_set(int(f))
    h = pb.head.copy(); cur = (pb.tail - pb.head).normalized()
    tgt = (W2A @ Vector(d)).normalized()
    R = cur.rotation_difference(tgt).to_matrix().to_4x4()
    pb.matrix = Matrix.Translation(h) @ R @ Matrix.Translation(-h) @ pb.matrix
    bpy.context.view_layer.update()
    worst = min(worst, (pb.tail - pb.head).normalized().dot(tgt))
    prop = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(pb.rotation_mode, "rotation_euler")
    pb.keyframe_insert(prop, frame=int(f)); n += 1
bpy.ops.wm.save_as_mainfile(filepath=A["save"], copy=False)
print("@@JSON@@" + json.dumps({"ok": True, "keys": n, "worst_dot": round(worst, 4), "saved": A["save"]}, ensure_ascii=False))
'''

BLOCK_PY = _COMMON + r'''
rig = pick_rig(A.get("armature"))
bmap = resolve(rig, A["candidates"])
need = ["Pelvis", "Spine", "L Thigh", "L Calf", "R Thigh", "R Calf", "L UpperArm", "L Forearm", "R UpperArm", "R Forearm"]
miss = [k for k in need if k not in bmap]
if miss:
    print("@@JSON@@" + json.dumps({"ok": False, "error": "뼈 이름을 못 맞춤: " + ", ".join(miss)}, ensure_ascii=False)); raise SystemExit(0)
sc = bpy.context.scene
for pb in rig.pose.bones:
    pb.rotation_mode = "QUATERNION"
W2A = rig.matrix_world.inverted().to_3x3()
CHAIN = [("Spine", [11, 12], [5, 6]), ("L Thigh", 11, 13), ("L Calf", 13, 15), ("R Thigh", 12, 14), ("R Calf", 14, 16),
         ("L UpperArm", 5, 7), ("L Forearm", 7, 9), ("R UpperArm", 6, 8), ("R Forearm", 8, 10)]
def pt(J, x):
    return Vector([sum(J[k][c] for k in x) / len(x) for c in range(3)]) if isinstance(x, list) else Vector(J[x])
def align(pb, tgt):
    h = pb.head.copy(); cur = (pb.tail - pb.head).normalized(); tgt = tgt.normalized()
    R = cur.rotation_difference(tgt).to_matrix().to_4x4()
    pb.matrix = Matrix.Translation(h) @ R @ Matrix.Translation(-h) @ pb.matrix
    bpy.context.view_layer.update()
    return round((pb.tail - pb.head).normalized().dot(tgt), 3)
rep = []
for p, f in zip(A["poses"], A["frames"]):
    sc.frame_set(f)
    for pb in rig.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0); pb.location = (0, 0, 0)
    bpy.context.view_layer.update()
    J = p["joints"]
    # 몸통 방향: 골반 좌→우 선(수평)을 영상에 맞춘다(엉덩이 뼈를 수직축으로)
    hv = W2A @ (Vector(J[12]) - Vector(J[11])); hv.z = 0
    hips = rig.pose.bones[bmap["Pelvis"]]
    cur = rig.pose.bones[bmap["R Thigh"]].head - rig.pose.bones[bmap["L Thigh"]].head; cur.z = 0
    if hv.length > 1e-6 and cur.length > 1e-6:
        R = cur.normalized().rotation_difference(hv.normalized()).to_matrix().to_4x4()
        hh = hips.head.copy(); hips.matrix = Matrix.Translation(hh) @ R @ Matrix.Translation(-hh) @ hips.matrix
        bpy.context.view_layer.update()
    row = {"pose": p["no"], "frame": f}
    for k, s, e in CHAIN:
        row[k] = align(rig.pose.bones[bmap[k]], W2A @ (pt(J, e) - pt(J, s)))
    for pb in rig.pose.bones:
        pb.keyframe_insert("rotation_quaternion", frame=f)
    rep.append(row)
sc.frame_start, sc.frame_end = A["frames"][0], A["frames"][-1]
bpy.ops.wm.save_as_mainfile(filepath=A["save"], copy=False)
print("@@JSON@@" + json.dumps({"ok": True, "keys": len(rep), "frames": A["frames"], "fit": rep, "saved": A["save"], "armature": rig.name}, ensure_ascii=False))
'''


def run(blend: Path, script: str, args: dict[str, Any], work: Path, *, timeout: float = 280.0) -> dict[str, Any]:
    """창 없는 블렌더로 스크립트 하나. 인자는 JSON 파일로(한글 경로가 명령줄에서 깨지지 않게)."""
    exe = find_blender()
    if not exe:
        raise FileNotFoundError("블렌더를 못 찾았다 — 설치돼 있으면 설정의 JARVIS_BLENDER 에 blender.exe 경로를 넣어 달라고 사람에게 말해라")
    work.mkdir(parents=True, exist_ok=True)
    sp, ap = work / "_script.py", work / "_args.json"
    sp.write_text(script, encoding="utf-8")
    ap.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
    try:
        proc = subprocess.run([exe, "-b", str(blend), "--factory-startup", "--python-exit-code", "1", "-P", str(sp), "--", str(ap)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"블렌더가 {int(timeout)}초 안에 못 끝냈다 — 구간(start · end)을 줄여라") from exc
    out = proc.stdout or ""
    for line in out.splitlines():
        if "@@ERR@@" in line:
            raise ValueError(line.split("@@ERR@@", 1)[1].strip())
    got = [line.split("@@JSON@@", 1)[1] for line in out.splitlines() if "@@JSON@@" in line]
    if not got:
        raise RuntimeError(f"blender_failed: {(proc.stderr or out)[-500:]}")
    res = json.loads(got[-1])
    if not res.get("ok", True):
        raise ValueError(res.get("error") or "블렌더 쪽 실패")
    return res
