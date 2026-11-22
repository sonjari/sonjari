
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
