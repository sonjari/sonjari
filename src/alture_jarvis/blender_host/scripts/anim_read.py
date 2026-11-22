
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
