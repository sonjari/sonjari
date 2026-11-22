
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
