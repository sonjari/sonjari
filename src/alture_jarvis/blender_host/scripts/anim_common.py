
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
