# -*- coding: utf-8 -*-
"""입힌 뒤 뚫림 점검표 — anim_fit_check (2026-11-06 · 애니메이터 팩).

현업 애니메이터 작업 흐름의 ③ 고치기(입히기와 합쳐 약 1시간) 중 「어디를 고칠지 찾기」를 없앤다.
11-05 블렌더 공개 캐릭터 실험(arms_clear · kick_belly)의 판정 부분을 맥스 바이페드로 옮긴 것이다.

나눔(엇박자 도구와 같다): 맥스 스크립트는 **읽기만** 한다 — 뼈 행렬(프레임마다)과 기준 프레임의 몸 메시 점을 파일로 쓴다.
판정 · 계산은 이 파이썬 한 곳(시험 통과)에서 한다. 장면은 바꾸지 않는다.

판정:
- 몸 부피 = 머리 · 가슴 · 배 타원체. 기준 프레임의 메시 점을 가장 가까운 뼈 마디에 나눠 담고, 그 뼈의 자리에서 잰다
  (캐릭터마다 몸 크기가 다르니 숫자를 박지 않고 메시에서 잰다 — 3등신과 8등신이 같은 코드로 된다).
- 팔(팔꿈치 · 아래팔 가운데 · 손목 · 손 · 손끝)이 머리 · 가슴 · 배 안으로 들어간 프레임, 무릎 · 허벅지 가운데가 배 · 가슴 안으로
  들어간 프레임을 센다. 팔 · 다리 굵기만큼 몸 부피를 부풀려 잰다(뼈는 팔 한가운데라서).
- 눈금: **기준 프레임에서는 0 이어야 한다.** 0 이 아니면 몸 크기 재기가 틀린 것 — 점검표를 믿지 말라고 같이 적는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

# 바이페드 이름 꼬리(접두어 뒤). 없는 것은 건너뛴다(바이페드 설정마다 척추 · 목 수가 다르다).
BONES = ["Pelvis", "Spine", "Spine1", "Spine2", "Spine3", "Neck", "Head",
         "L UpperArm", "L Forearm", "L Hand", "R UpperArm", "R Forearm", "R Hand",
         "L Thigh", "L Calf", "L Foot", "R Thigh", "R Calf", "R Foot"]

#: 몸 부피 → (재는 뼈 후보, 그 몸에 속하는 마디의 뼈들)
BODY = {
    "머리": (["Head"], ["Head"]),
    "가슴": (["Spine2", "Spine1", "Spine3"], ["Spine2", "Spine3", "Neck"]),
    "배": (["Spine", "Pelvis"], ["Pelvis", "Spine", "Spine1"]),
}
#: 팔다리 → 이 몸 부피들과 견준다 (11-05 실측: 팔이 몸에 겹침 · 발차기 때 무릎이 배에)
LIMB_VS = {"팔": ("머리", "가슴", "배"), "다리": ("가슴", "배")}
SHRINK = 0.95          # 블렌더 판과 같은 여유(가장자리 스침은 뚫림으로 안 친다)

READ_SCRIPT = r'''-- 손자리 애니메이터 팩: 뚫림 점검용 읽기 (읽기만 한다 — 장면을 바꾸지 않는다)
(
local outPath = @"__OUT__"
local S = __START__
local E = __END__
local R = __REF__
local pre = "__PREFIX__"
local tails = #(__TAILS__)
local nodes = #()
local names = #()
for t in tails do (
  local n = getNodeByName (pre + " " + t)
  if n != undefined do (append nodes n; append names t)
)
fn sjNum v = (formattedPrint (v as float) format:".5f")
fn sjM tm = (
  local r = ""
  for row in #(tm.row1, tm.row2, tm.row3, tm.row4) do r += sjNum row.x + "," + sjNum row.y + "," + sjNum row.z + ","
  substring r 1 (r.count - 1)
)
local fs = createFile outPath encoding:#utf8
if nodes.count < 4 then (
  format "{\"ok\":false,\"error\":\"바이페드를 못 찾음: %\"}" pre to:fs
  close fs
  "손자리 점검 읽기: 바이페드 '" + pre + "' 를 못 찾음"
) else (
  format "{\"ok\":true,\"bones\":[" to:fs
  for i = 1 to names.count do format "\"%\"%" names[i] (if i < names.count then "," else "") to:fs
  -- 고칠 뼈의 키 자리(고칠 때 그 자리에서만 고친다 — 키 수를 늘리지 않는다). "L" · "R" 은 위팔(11-06 판과 같은 이름)
  format "],\"keys\":{" to:fs
  local kn = #("L", "R", "L Thigh", "R Thigh", "Spine")
  local kt = #("L UpperArm", "R UpperArm", "L Thigh", "R Thigh", "Spine")
  for k = 1 to kn.count do (
    local ua = getNodeByName (pre + " " + kt[k])
    local ts = #()
    if ua != undefined do try (for i = 1 to ua.controller.keys.count do (local f = ua.controller.keys[i].time.frame as integer; if f >= S and f <= E do appendIfUnique ts f)) catch ()
    format "\"%\":[" kn[k] to:fs
    for i = 1 to ts.count do format "%%" ts[i] (if i < ts.count then "," else "") to:fs
    format "]%" (if k < kn.count then "," else "") to:fs
  )
  format "},\"start\":%,\"end\":%,\"ref\":%,\"frames\":[" S E R to:fs
  for f = S to E do (
    at time f (
      format "[%" f to:fs
      for n in nodes do format ",[%]" (sjM n.transform) to:fs
      format "]%" (if f < E then "," else "") to:fs
    )
  )
  -- 몸 크기는 피겨 모드(팔 벌린 기본 자세)에서 잰다 — 동작 프레임에선 팔이 몸에 붙어 몸 점과 섞인다(11-06 실측).
  -- 읽은 뒤 원래대로 되돌린다(장면을 바꾸지 않는다).
  local root = nodes[1].controller.rootNode
  local wasFig = false
  try (wasFig = root.controller.figureMode) catch ()
  local figOk = false
  -- 11-10 맥스 실측: 피겨 모드 켜고 끄기가 되돌리기 목록에 쌓이면, 「고침 → 다시 점검 → Ctrl+Z」에서 Ctrl+Z 가 고침 대신
  -- 피겨 모드를 켜 동작이 사라진 것처럼 보였다 → 되돌리기 목록에 안 남긴다.
  with undo off (try (root.controller.figureMode = true; figOk = true) catch ())
  format "],\"fig\":[%" (if figOk then 1 else 0) to:fs
  for n in nodes do format ",[%]" (sjM n.transform) to:fs
  format "],\"verts\":[" to:fs
  local first = true
  local nv = 0
  -- 11-10: 점마다 가장 무거운 스킨 뼈(우리 뼈 꼬리 · 아니면 "x:이름" · 못 읽으면 "") — 머리카락 · 리본 · 장식을 몸 부피에서 가른다.
  -- skinOps 는 수정 패널에서 그 Skin 이 열려 있어야 읽힌다 → 잠깐 고르고, 끝나면 원래 선택 · 패널로 되돌린다(장면은 안 바뀐다).
  local labs = #()
  local vmesh = #()
  local mnames = #()
  local xnames = #()
  local oldSel = selection as array
  local oldMode = getCommandPanelTaskMode()
  fn sjClean s = (substituteString (substituteString s "\\" "/") "\"" "'")
  fn sjLabel nm pre tails = (
    if (findString nm (pre + " ")) == 1 then (
      local t = substring nm (pre.count + 2) -1
      if (findItem tails t) > 0 then t else ("x:" + nm)
    ) else ("x:" + nm)
  )
  with undo off (
    for o in geometry where not (classOf o == Biped_Object) and not o.isHidden do (
      local deformed = false
      local sk = undefined
      for m in o.modifiers where (classOf m == Skin or classOf m == Physique) do (deformed = true; if classOf m == Skin do sk = m)
      if deformed do (
        local msh = snapshotAsMesh o
        local cnt = msh.numverts
        local step = if cnt > 6000 then (cnt / 6000 + 1) else 1
        local useSk = false
        if sk != undefined do try (
          max modify mode
          select o
          modPanel.setCurrentObject sk
          useSk = ((skinOps.GetNumberVertices sk) == cnt)   -- 위에 점 수를 바꾸는 수정자(터보스무스 등)가 있으면 못 맞춘다 → 가까운 뼈로
        ) catch (useSk = false)
        append mnames (sjClean o.name)
        for v = 1 to cnt by step do (
          local p = getVert msh v
          format "%[%,%,%]" (if first then "" else ",") (sjNum p.x) (sjNum p.y) (sjNum p.z) to:fs
          first = false
          nv += 1
          local lab = ""
          if useSk do try (
            local bw = 0.0
            local bid = 0
            for i = 1 to (skinOps.GetVertexWeightCount sk v) do (
              local w = skinOps.GetVertexWeight sk v i
              if w > bw do (bw = w; bid = skinOps.GetVertexWeightBoneID sk v i)
            )
            if bid > 0 do (
              local bn = skinOps.GetBoneName sk bid 0
              lab = sjLabel bn pre tails
              if (substring lab 1 2) == "x:" do appendIfUnique xnames bn
            )
          ) catch (lab = "")
          append labs (sjClean lab)
          append vmesh (mnames.count - 1)
        )
        delete msh
      )
    )
  )
  with undo off (try (root.controller.figureMode = wasFig) catch ())
  with undo off (try (if oldSel.count > 0 then select oldSel else clearSelection()) catch ())
  try (setCommandPanelTaskMode oldMode) catch ()
  format "],\"vbones\":[" to:fs
  for i = 1 to labs.count do format "\"%\"%" labs[i] (if i < labs.count then "," else "") to:fs
  format "],\"vmesh\":[" to:fs
  for i = 1 to vmesh.count do format "%%" vmesh[i] (if i < vmesh.count then "," else "") to:fs
  format "],\"meshes\":[" to:fs
  for i = 1 to mnames.count do format "\"%\"%" mnames[i] (if i < mnames.count then "," else "") to:fs
  -- 우리 뼈가 아닌 뼈 → 가장 가까운 우리 조상 뼈(꼬리). 몸(뱃살 · 가슴 출렁)인지 장식인지는 파이썬이 거리로 가른다
  format "],\"xparent\":{" to:fs
  for i = 1 to xnames.count do (
    local anc = ""
    local nd = getNodeByName xnames[i]
    if nd != undefined do (
      local q = nd.parent
      while q != undefined and anc == "" do (
        local t = sjLabel q.name pre tails
        if (substring t 1 2) != "x:" then anc = t else q = q.parent
      )
    )
    format "\"%\":\"%\"%" (sjClean xnames[i]) anc (if i < xnames.count then "," else "") to:fs
  )
  format "}}" to:fs
  close fs
  "손자리 점검 읽기: 뼈 " + (nodes.count as string) + " · 프레임 " + ((E - S + 1) as string) + " · 몸 점 " + (nv as string)
)
)
'''


def read_script(out: Path, start: int, end: int, ref: int, prefix: str = "Bip001") -> str:
    prefix = prefix.replace('"', "").replace("\\", "").strip() or "Bip001"
    return (READ_SCRIPT.replace("__OUT__", str(out)).replace("__START__", str(int(start)))
            .replace("__END__", str(int(end))).replace("__REF__", str(int(ref))).replace("__PREFIX__", prefix)
            .replace("__TAILS__", ", ".join(f'"{t}"' for t in BONES)))


# ── 계산 ────────────────────────────────────────────────────────────────────

def _mats(flat: list[float]) -> np.ndarray:
    """맥스 행렬 네 줄(row1~3 축 · row4 위치) → 4x4 (점은 행 벡터 · p @ M)."""
    m = np.eye(4)
    m[:4, :3] = np.array(flat, float).reshape(4, 3)
    return m


def _segments(mats: dict[str, np.ndarray]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """뼈마다 (시작, 끝). 끝은 사슬의 다음 뼈 자리 — 사슬 끝(머리 · 손 · 발)은 앞 마디 길이로 늘인다."""
    pos = {k: m[3, :3] for k, m in mats.items()}
    axis = {k: m[0, :3] / (np.linalg.norm(m[0, :3]) or 1.0) for k, m in mats.items()}
    nxt = {"Pelvis": "Spine", "Spine": "Spine1", "Spine1": "Spine2", "Spine2": "Spine3", "Spine3": "Neck", "Neck": "Head"}
    for s in "LR":
        nxt.update({f"{s} UpperArm": f"{s} Forearm", f"{s} Forearm": f"{s} Hand",
                    f"{s} Thigh": f"{s} Calf", f"{s} Calf": f"{s} Foot"})
    seg: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for k in pos:
        n = nxt.get(k)
        while n and n not in pos:                         # Spine3 없는 바이페드면 Neck 으로 건너뛴다
            n = nxt.get(n)
        if n:
            seg[k] = (pos[k], pos[n])
    for k, prev in (("Head", "Neck"), ("L Hand", "L Forearm"), ("R Hand", "R Forearm"), ("L Foot", "L Calf"), ("R Foot", "R Calf")):
        if k in pos:
            ln = np.linalg.norm(seg[prev][1] - seg[prev][0]) if prev in seg else 0.1
            ln = ln * (1.2 if k == "Head" else 0.45)
            seg[k] = (pos[k], pos[k] + axis[k] * ln)
    if "Pelvis" in pos and "Pelvis" not in seg and "Spine" in pos:
        seg["Pelvis"] = (pos["Pelvis"], pos["Spine"])
    return seg


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


#: 우리 뼈가 아닌 뼈 · 다른 메시의 점이 본 몸 메시보다 이 배수 넘게 바깥이면 장식(머리카락 · 리본 · 치마)으로 친다.
#: 11-10 시험 캐릭터 실측: 뱃살 출렁 뼈 1.07배(몸) · 똥머리 1.48배(장식). 표본 둘 — 다른 캐릭터로 다시 볼 것.
DECOR_RATIO = 1.25
_TORSO = [k for _c, members in BODY.values() for k in members]


def _part_of(key: str) -> str:
    return next((p for p, (_c, members) in BODY.items() if key in members), "")


def _assign(dump: dict[str, Any], v: np.ndarray, keys: list[str], d: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """점마다 (주인 뼈, 몸 부피에 쓸지, 보고).

    스킨 가중치(vbones: 점마다 가장 무거운 뼈)가 있으면 그것으로 나눈다 — 11-06 까지는 「가장 가까운 뼈」라
    아래팔 옆 뱃살이 팔로, 머리카락 · 장식이 머리 · 가슴으로 갔다. 가중치가 없거나(피지크 · 위상이 바뀐 메시) 빈 칸이면 예전처럼 가까운 뼈.
    """
    near = np.array(keys, dtype=object)[d.argmin(axis=1)]
    labels = dump.get("vbones")
    if not labels or len(labels) != len(v):
        return near, np.ones(len(v), bool), {"skin_weights": False}
    lab = np.array([str(x) for x in labels], dtype=object)
    vmesh = np.array(dump.get("vmesh") or [0] * len(v))
    meshes = list(dump.get("meshes") or [])
    xparent = dict(dump.get("xparent") or {})
    owner, keep = near.copy(), np.ones(len(v), bool)
    ours = np.isin(lab, keys)
    owner[ours] = lab[ours]
    tcols = [keys.index(k) for k in keys if k in _TORSO]
    dt = d[:, tcols].min(axis=1) if tcols else np.full(len(v), np.inf)
    body = ours & np.isin(owner, _TORSO)
    if not body.any():
        return near, np.ones(len(v), bool), {"skin_weights": False, "why": "몸통 · 머리 뼈에 붙은 점이 없다"}
    main = int(np.bincount(vmesh[body]).argmax())
    ref = {}
    for part, (_c, members) in BODY.items():
        sel = body & (vmesh == main) & np.isin(owner, members)
        if sel.sum() >= 12:
            ref[part] = float(np.median(dt[sel]))
    kept, decor = [], []
    # ① 우리 뼈가 아닌 뼈(뱃살 출렁 · 똥머리 · 포니테일 · 리본 …): 조상이 몸통 · 머리면 거리로 가르고, 팔다리 밑이면 뺀다
    for name in sorted({str(x)[2:] for x in lab if str(x).startswith("x:")}):
        sel = lab == "x:" + name
        anc = str(xparent.get(name) or "")
        part = _part_of(anc)
        far = float(np.median(dt[sel]))
        if part and part in ref and anc in keys and far <= DECOR_RATIO * ref[part]:
            owner[sel] = anc
            kept.append({"bone": name, "as": part, "ratio": round(far / ref[part], 2)})
        else:
            keep[sel] = False
            decor.append({"bone": name, "points": int(sel.sum()),
                          **({"ratio": round(far / ref[part], 2)} if part in ref else {"under": anc or "없음"})})
    # ② 본 몸 메시가 아닌 메시의 몸통 · 머리 점(머리카락 메시를 머리 뼈에 통째로 · 치마를 골반에): 같은 잣대
    for mi in sorted(set(vmesh[body].tolist()) - {main}):
        for part, (_c, members) in BODY.items():
            sel = (vmesh == mi) & ours & np.isin(owner, members)
            if sel.sum() >= 6 and part in ref and float(np.median(dt[sel])) > DECOR_RATIO * ref[part]:
                keep[sel] = False
                decor.append({"mesh": meshes[mi] if mi < len(meshes) else str(mi), "part": part, "points": int(sel.sum()),
                              "ratio": round(float(np.median(dt[sel])) / ref[part], 2)})
    blank = lab == ""
    return owner, keep, {"skin_weights": True, "main_mesh": meshes[main] if main < len(meshes) else main,
                         "kept_extra_bones": kept, "decoration": decor,
                         **({"no_weight_points": int(blank.sum())} if blank.any() else {})}


def body_volumes(dump: dict[str, Any]) -> dict[str, Any]:
    """기준 프레임의 메시 점 → 몸 부피(재는 뼈 자리의 타원체) · 팔 · 다리 굵기."""
    names = dump["bones"]
    ref = int(dump["ref"])
    fig = dump.get("fig")
    row = fig if fig and int(fig[0]) == 1 else next((r for r in dump["frames"] if int(r[0]) == ref), dump["frames"][0])
    mats = {n: _mats(m) for n, m in zip(names, row[1:])}
    seg = _segments(mats)
    v = np.array(dump.get("verts") or [], float).reshape(-1, 3)
    if len(v) < 50:
        raise ValueError("몸 메시 점이 너무 적다(스킨 · 피지크가 걸린 메시를 못 찾음) — 캐릭터 메시가 바이페드에 스킨돼 있는지 확인")
    keys = list(seg)
    d = np.stack([_seg_dist(v, *seg[k]) for k in keys], axis=1)
    owner, keep, how = _assign(dump, v, keys, d)
    vols: dict[str, Any] = {}
    for part, (cands, members) in BODY.items():
        bone = next((c for c in cands if c in mats), None)
        pts = v[keep & np.isin(owner, members)]
        if bone is None or len(pts) < 12:
            continue
        local = (np.c_[pts, np.ones(len(pts))] @ np.linalg.inv(mats[bone]))[:, :3]
        lo, hi = np.percentile(local, 2, axis=0), np.percentile(local, 98, axis=0)
        vols[part] = {"bone": bone, "center": ((lo + hi) / 2).round(5).tolist(), "radii": ((hi - lo) / 2).round(5).tolist(),
                      "points": int(len(pts))}
    thick = {}
    for limb, bones in (("팔", ["L Forearm", "R Forearm"]), ("다리", ["L Thigh", "R Thigh", "L Calf", "R Calf"])):
        ds = [d[keep & (owner == b), keys.index(b)] for b in bones if b in keys and (keep & (owner == b)).sum() >= 6]
        thick[limb] = float(np.median(np.concatenate(ds))) if ds else 0.0
    return {"volumes": vols, "thickness": thick, "body_from": how}


def _probe_points(seg: dict[str, tuple[np.ndarray, np.ndarray]]) -> dict[tuple[str, str], np.ndarray]:
    out = {}
    for s, side in (("L", "왼"), ("R", "오른")):
        fa, hd = seg.get(f"{s} Forearm"), seg.get(f"{s} Hand")
        if fa and hd:
            out[("팔", side)] = np.array([fa[0], (fa[0] + fa[1]) / 2, fa[1], (hd[0] + hd[1]) / 2, hd[1]])
        th, ca = seg.get(f"{s} Thigh"), seg.get(f"{s} Calf")
        if th and ca:
            # 무릎 + 정강이 1/4 · 1/2(11-10). 허벅지 쪽은 원래 골반 옆이라 서 있기만 해도 걸린다(11-06 · 11-10 시험 캐릭터 헛잡음 89~98%).
            # 시험 캐릭터 발차기 콤보 1316프레임 메시 기준(정강이 점이 배 · 가슴 안 145프레임): 무릎만 놓침 81% → 셋 37% · 헛잡음 4%.
            out[("다리", side)] = np.array([ca[0], ca[0] + 0.25 * (ca[1] - ca[0]), ca[0] + 0.5 * (ca[1] - ca[0])])
    return out


def _depth(points: np.ndarray, mat: np.ndarray, vol: dict[str, Any], grow: float) -> float:
    local = (np.c_[points, np.ones(len(points))] @ np.linalg.inv(mat))[:, :3] - np.array(vol["center"])
    r = (np.array(vol["radii"]) + grow) * SHRINK
    return float((1 - np.sqrt(((local / np.maximum(r, 1e-6)) ** 2).sum(axis=1))).max())


def _ranges(frames: list[int]) -> list[str]:
    out, run = [], []
    for f in frames:
        if run and f != run[-1] + 1:
            out.append(f"{run[0]}~{run[-1]}" if len(run) > 1 else str(run[0]))
            run = []
        run.append(f)
    if run:
        out.append(f"{run[0]}~{run[-1]}" if len(run) > 1 else str(run[0]))
    return out


def check(dump: dict[str, Any]) -> dict[str, Any]:
    if not dump.get("ok", True):
        raise ValueError(dump.get("error") or "읽기 실패")
    body = body_volumes(dump)
    vols, thick = body["volumes"], body["thickness"]
    names = dump["bones"]
    hits: dict[str, dict[str, Any]] = {}
    any_hit: set[int] = set()
    calib: dict[str, float] = {}
    ref = int(dump["ref"])
    fig = dump.get("fig")
    rows = list(dump["frames"])
    if fig and int(fig[0]) == 1:
        rows = [["fig"] + fig[1:]] + rows                # 눈금 줄 — 기본 자세에서 0 이어야 한다
    for row in rows:
        if row[0] == "fig":
            mats = {n: _mats(m) for n, m in zip(names, row[1:])}
            for (limb, side), pts in _probe_points(_segments(mats)).items():
                for part in LIMB_VS[limb]:
                    vol = vols.get(part)
                    if vol and vol["bone"] in mats:
                        calib[f"{side} {limb} → {part}"] = round(_depth(pts, mats[vol["bone"]], vol, thick.get(limb, 0.0)), 3)
            continue
        f = int(row[0])
        mats = {n: _mats(m) for n, m in zip(names, row[1:])}
        seg = _segments(mats)
        for (limb, side), pts in _probe_points(seg).items():
            for part in LIMB_VS[limb]:
                vol = vols.get(part)
                if not vol or vol["bone"] not in mats:
                    continue
                d = _depth(pts, mats[vol["bone"]], vol, thick.get(limb, 0.0))
                key = f"{side} {limb} → {part}"
                if f == ref and not (fig and int(fig[0]) == 1):
                    calib[key] = round(d, 3)
                if d > 0:
                    h = hits.setdefault(key, {"frames": [], "worst": 0.0})
                    h["frames"].append(f)
                    h["worst"] = max(h["worst"], d)
                    any_hit.add(f)
    total = len(dump["frames"])
    table = [{"where": k, "frames": len(h["frames"]), "of": total, "ranges": _ranges(h["frames"])[:8],
              "worst_depth": round(h["worst"], 2)} for k, h in sorted(hits.items(), key=lambda kv: -len(kv[1]["frames"]))]
    bad_calib = {k: v for k, v in calib.items() if v > 0}
    out = {"frames": total, "frames_with_any_hit": len(any_hit), "table": table,
           "body_measured": {k: {"bone": v["bone"], "points": v["points"]} for k, v in vols.items()},
           "body_from": body["body_from"],
           "missing_body": [p for p in BODY if p not in vols], "ref_frame": ref,
           "measured_in": "피겨 모드" if fig and int(fig[0]) == 1 else f"{ref} 프레임"}
    if bad_calib:
        out["calibration_failed"] = {"at_ref": bad_calib,
                                     "note": "기본 자세(피겨 모드)에서 이미 겹친다 — 몸 크기 재기가 틀렸을 수 있다. "
                                             "이 점검표는 믿지 말고 사람에게 그렇게 말해라."}
    return out


def check_file(path: Path) -> dict[str, Any]:
    from .maxscript import load_dump

    return check(load_dump(path))


# ── 자동 수정(anim_fit_fix · 11-06) — 팔만 ───────────────────────────────────────
# 블렌더 판(arms_clear r1g)과 같은 생각: 뚫린 프레임에서만, 위팔을 **가장 적게** 돌려 풀리는 축(위팔의 옆 축 두 개 × 앞뒤)을 고르고,
# 축마다 앞뒤 프레임과 부드럽게 이은 뒤 **원래 키 자리에서만** 위팔 방향을 바꾼다(키 수 그대로). 다리 바깥 벌림은 하지 않는다(기형).
FIX_MAX_DEG = 45
FIX_STEP = 3
FIX_SOFT = 4          # 프레임(앞뒤로 이만큼 최댓값을 퍼뜨린 뒤 평균) — 30fps 에서 약 0.13초


def _rot(axis: np.ndarray, deg: float) -> np.ndarray:
    a = axis / (np.linalg.norm(axis) or 1.0)
    t = np.radians(deg)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * k + (1 - np.cos(t)) * (k @ k)


def _soften(v: np.ndarray, k: int = FIX_SOFT) -> np.ndarray:
    mx = np.array([v[max(0, i - k):i + k + 1].max() for i in range(len(v))])
    return np.convolve(np.pad(mx, k, mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")


def plan_fix(dump: dict[str, Any], max_deg: int = FIX_MAX_DEG) -> dict[str, Any]:
    """뚫린 팔을 푸는 위팔 방향(키 자리마다). 장면은 안 바꾼다 — 결과를 write_fix_script 로 넘긴다."""
    body = body_volumes(dump)
    vols, thick = body["volumes"], body["thickness"]
    names = dump["bones"]
    rows = list(dump["frames"])
    frames = [int(r[0]) for r in rows]
    mats_all = [{n: _mats(m) for n, m in zip(names, r[1:])} for r in rows]
    out: dict[str, Any] = {"keys": {}, "frames_hit": {}, "unsolved": {}}
    for s, side in (("L", "왼"), ("R", "오른")):
        ua = f"{s} UpperArm"
        need = np.zeros((4, len(rows)))                 # 축 넷(옆 축 둘 × 앞뒤)마다 필요한 도
        hit, unsolved = 0, []
        for i, m in enumerate(mats_all):
            if ua not in m:
                continue
            pts = _probe_points(_segments(m)).get(("팔", side))
            if pts is None:
                continue
            checks = [(m[vols[p]["bone"]], vols[p]) for p in LIMB_VS["팔"] if p in vols and vols[p]["bone"] in m]

            def worst(q: np.ndarray) -> float:
                return max(_depth(q, mm, vv, thick.get("팔", 0.0)) for mm, vv in checks) if checks else -1.0

            if worst(pts) <= 0:
                continue
            hit += 1
            pivot = m[ua][3, :3]
            axes = [m[ua][1, :3], -m[ua][1, :3], m[ua][2, :3], -m[ua][2, :3]]
            best = None
            for j, ax in enumerate(axes):
                for d in range(FIX_STEP, max_deg + 1, FIX_STEP):
                    if best and d >= best[1]:
                        break
                    if worst(pivot + (pts - pivot) @ _rot(ax, d).T) <= 0:
                        best = (j, d)
                        break
            if best is None:
                unsolved.append(frames[i])
                continue
            need[best[0], i] = best[1]
        soft = np.stack([_soften(row) for row in need])
        keys = [int(f) for f in (dump.get("keys") or {}).get(s, [])] or frames
        plan = []
        for f in keys:
            if f not in frames:
                continue
            i = frames.index(f)
            m = mats_all[i]
            if ua not in m or soft[:, i].max() < 0.5:
                continue
            axes = [m[ua][1, :3], -m[ua][1, :3], m[ua][2, :3], -m[ua][2, :3]]
            d = m[ua][0, :3] / (np.linalg.norm(m[ua][0, :3]) or 1.0)
            for j in range(4):
                if soft[j, i] >= 0.5:
                    d = _rot(axes[j], float(soft[j, i])) @ d
            plan.append([f, [round(float(x), 5) for x in d], round(float(soft[:, i].max()), 1)])
        out["keys"][s] = plan
        out["frames_hit"][side] = hit
        if unsolved:
            out["unsolved"][side] = _ranges(unsolved)[:8]
    return out


# ── 자동 수정 — 다리(무릎 · 정강이 → 배 · 가슴 · 11-10) ──────────────────────────────────────
# 11-05 블렌더 kick_belly 실험의 규칙을 옮겼다: 상체를 뒤로 젖히거나 허벅지를 내린다. **둘 다 몸 좌우 축(골반 왼 → 오른)으로만** 돌려
# 무릎이 앞뒤 · 위아래로만 움직인다 — 다리 바깥 벌림(기형)은 생길 수 없다. 두 발이 바닥이면 젖힘 15도까지 · 허벅지는 안 건드린다
# (11-05: 45도까지 젖혔더니 쪼그린 장면에서 몸이 접혔다 · 디딘 발을 들면 발이 뜬다). 원래 키 자리에서만 · 키가 없는 뼈는 안 고친다.
LEG_MAX_DEG = 30
LEAN_MAX_DEG = 30
LEAN_PLANTED_DEG = 15
LEAN_BONE = "Spine"
_UPPER = {"Spine", "Spine1", "Spine2", "Spine3", "Neck", "Head"}      # 젖힐 때 같이 도는 뼈(배 · 가슴 · 머리 부피가 붙는 뼈)


def _turned(m: np.ndarray, R: np.ndarray, p: np.ndarray) -> np.ndarray:
    out = m.copy()
    out[:3, :3] = m[:3, :3] @ R.T
    out[3, :3] = p + (m[3, :3] - p) @ R.T
    return out


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) or 1.0)


def _planted_fn(mats_all: list[dict[str, np.ndarray]]):
    """발(발목) 높이가 동작 전체에서 가장 낮은 발 + 종아리 길이 20% 안이면 디딘 발."""
    zs = [m[f"{s} Foot"][3, 2] for m in mats_all for s in "LR" if f"{s} Foot" in m]
    calves = [np.linalg.norm(m[f"{s} Calf"][3, :3] - m[f"{s} Foot"][3, :3]) for m in mats_all[:1] for s in "LR"
              if f"{s} Calf" in m and f"{s} Foot" in m]
    if not zs or not calves:
        return lambda m, s: False
    ground, tol = min(zs), 0.2 * float(np.median(calves))
    return lambda m, s: f"{s} Foot" in m and m[f"{s} Foot"][3, 2] - ground <= tol


def _used(base: dict[str, Any] | None, dump: dict[str, Any], bone: str) -> dict[int, float]:
    """원본(base) 대비 이미 돌아간 각도(프레임마다 · 도). 같은 뼈대 · 같은 기본 자세가 아니면 빈 것."""
    if not base or base.get("bones") != dump.get("bones") or base.get("fig") != dump.get("fig") or bone not in dump["bones"]:
        return {}
    k = dump["bones"].index(bone) + 1
    was = {int(r[0]): _unit(_mats(r[k])[0, :3]) for r in base["frames"]}
    out = {}
    for r in dump["frames"]:
        f = int(r[0])
        if f in was:
            out[f] = float(np.degrees(np.arccos(np.clip(was[f] @ _unit(_mats(r[k])[0, :3]), -1, 1))))
    return out


def plan_fix_legs(dump: dict[str, Any], max_lean: int = LEAN_MAX_DEG, max_thigh: int = LEG_MAX_DEG,
                  base: dict[str, Any] | None = None) -> dict[str, Any]:
    """무릎 · 정강이가 배 · 가슴을 뚫은 프레임 → 척추(젖힘) · 허벅지(내림) 방향(키 자리마다). 장면은 안 바꾼다.

    base = 고치기 전 원본 읽기. 주면 상한(젖힘 · 허벅지)을 **원본 대비 누적**으로 건다 — 11-10 시험 캐릭터 발차기에서 세 번 돌리니
    한 번 30도 상한이 매번 새로 걸려 상체 68.8도 · 허벅지 70.9도까지 쌓였다(기형).
    """
    body = body_volumes(dump)
    vols, thick = body["volumes"], body["thickness"]
    names = dump["bones"]
    rows = list(dump["frames"])
    frames = [int(r[0]) for r in rows]
    mats_all = [{n: _mats(m) for n, m in zip(names, r[1:])} for r in rows]
    planted = _planted_fn([{n: _mats(m) for n, m in zip(base["bones"], r[1:])} for r in base["frames"]]
                          if base and base.get("bones") == names else mats_all)
    used = {b: _used(base, dump, b) for b in (LEAN_BONE, "L Thigh", "R Thigh")}
    side_of = {"L": "왼", "R": "오른"}
    n = len(rows)
    lean = np.zeros((2, n))                                    # [+, -] 채널(팔과 같이 채널마다 부드럽게)
    thigh = {s: np.zeros((2, n)) for s in "LR"}
    hit = {"왼": 0, "오른": 0}
    unsolved: list[int] = []
    for i, m in enumerate(mats_all):
        if "L Thigh" not in m or "R Thigh" not in m:
            continue
        probes = _probe_points(_segments(m))
        checks = [vols[p] for p in LIMB_VS["다리"] if p in vols and vols[p]["bone"] in m]
        if not checks:
            continue

        def depth(pts: np.ndarray, mm: dict[str, np.ndarray], checks=checks) -> float:
            return max(_depth(pts, mm[v["bone"]], v, thick.get("다리", 0.0)) for v in checks)

        sides = [s for s in "LR" if ("다리", side_of[s]) in probes and depth(probes[("다리", side_of[s])], m) > 0]
        if not sides:
            continue
        for s in sides:
            hit[side_of[s]] += 1
        ax = _unit(m["R Thigh"][3, :3] - m["L Thigh"][3, :3])
        pivot = m[LEAN_BONE][3, :3] if LEAN_BONE in m else None
        cap_a = 0 if pivot is None else (min(max_lean, LEAN_PLANTED_DEG) if planted(m, "L") and planted(m, "R") else max_lean)
        cap_a = max(0, int(cap_a - used[LEAN_BONE].get(frames[i], 0.0)))
        sgn_a = 1
        if pivot is not None:
            # 젖히는 쪽 = 몸의 뒤쪽(좌우 축 × 척추 위 방향). 11-10 맥스 실측: 「가슴이 무릎에서 멀어지는 쪽」으로 고르면
            # 상체를 숙인 채 무릎을 가슴보다 높이 든 장면에서 네 키 모두 「더 숙임」으로 계획했다 — 젖힘이 아니고 몸이 더 접힌다.
            back = _unit(np.cross(ax, _unit(m[LEAN_BONE][0, :3])))
            top = m["Spine2"][3, :3] if "Spine2" in m else pivot + m[LEAN_BONE][0, :3]
            sgn_a = max((1, -1), key=lambda g: float(((top - pivot) @ _rot(ax, 10 * g).T) @ back))
        sgn_t = {}
        for s in sides:                                        # 허벅지를 내리는 쪽 = 무릎이 내려가는 쪽
            hip, kn = m[f"{s} Thigh"][3, :3], m[f"{s} Calf"][3, :3]
            sgn_t[s] = min((1, -1), key=lambda g: float((hip + (kn - hip) @ _rot(ax, 10 * g).T)[2]))
        best = None
        for a in range(0, cap_a + 1, FIX_STEP):
            if best and a >= best[0]:
                break
            mm = m if a == 0 else {k: (_turned(v, _rot(ax, a * sgn_a), pivot) if k in _UPPER else v) for k, v in m.items()}
            cost, ts = a, {}
            for s in sides:
                pts, hip = probes[("다리", side_of[s])], m[f"{s} Thigh"][3, :3]
                cap_t = 0 if planted(m, s) else max(0, int(max_thigh - used[f"{s} Thigh"].get(frames[i], 0.0)))
                t_ok = next((t for t in range(0, cap_t + 1, FIX_STEP)
                             if depth(pts if t == 0 else hip + (pts - hip) @ _rot(ax, t * sgn_t[s]).T, mm) <= 0), None)
                if t_ok is None:
                    cost = None
                    break
                ts[s] = t_ok
                cost += t_ok
            if cost is not None and (best is None or cost < best[0]):
                best = (cost, a, ts)
        if best is None:
            unsolved.append(frames[i])
            continue
        _c, a, ts = best
        if a:
            lean[0 if sgn_a > 0 else 1, i] = a
        for s, t in ts.items():
            if t:
                thigh[s][0 if sgn_t[s] > 0 else 1, i] = t
    keys = dump.get("keys") or {}
    out: dict[str, Any] = {"legs": {}, "frames_hit": {f"{v} 다리": hit[v] for v in hit}, "unsolved": {}, "no_keys": []}

    def at_keys(bone: str, chan: np.ndarray) -> None:
        soft = np.stack([_soften(r) for r in chan])
        net = soft[0] - soft[1]
        if np.abs(net).max() < 0.5:
            return
        ks = [int(f) for f in keys.get(bone, [])]
        if not ks:                                             # 키가 없는 뼈에 새 키를 만들지 않는다
            out["no_keys"].append(bone)
            return
        plan = []
        for f in ks:
            if f not in frames:
                continue
            i = frames.index(f)
            m = mats_all[i]
            if bone not in m or "L Thigh" not in m or "R Thigh" not in m or abs(net[i]) < 0.5:
                continue
            # 부드럽게 이은 값이 옆 프레임에서 번져 와도 이 프레임의 상한을 넘지 않게(11-05: 45도 젖힘이 번져 쪼그린 몸이 접혔다)
            if bone == LEAN_BONE:
                cap = min(max_lean, LEAN_PLANTED_DEG) if planted(m, "L") and planted(m, "R") else max_lean
            else:
                cap = 0 if planted(m, bone[0]) else max_thigh
            cap = max(0.0, cap - used[bone].get(f, 0.0))
            deg = float(np.clip(net[i], -cap, cap))
            if abs(deg) < 0.5:
                continue
            ax = _unit(m["R Thigh"][3, :3] - m["L Thigh"][3, :3])
            d = _rot(ax, deg) @ _unit(m[bone][0, :3])
            plan.append([f, [round(float(x), 5) for x in d], round(abs(deg), 1)])
        if plan:
            out["legs"][bone] = plan

    at_keys(LEAN_BONE, lean)
    for s in "LR":
        at_keys(f"{s} Thigh", thigh[s])
    if unsolved:
        out["unsolved"]["다리"] = _ranges(unsolved)[:8]
    return out


def fix_items(plan: dict[str, Any]) -> list[list[Any]]:
    """[뼈 꼬리, 프레임, 방향] — 척추 → 허벅지 → 위팔 순(같은 프레임에서 상체를 먼저 젖힌 뒤 팔을 맞춘다)."""
    items = [[b, f, d] for b in (LEAN_BONE, "L Thigh", "R Thigh") for f, d, _deg in (plan.get("legs") or {}).get(b, [])]
    items += [[f"{s} UpperArm", f, d] for s, rows in (plan.get("keys") or {}).items() for f, d, _deg in rows]
    return items


FIX_SCRIPT = r'''-- 손자리 애니메이터 팩: 뚫림 자동 수정 (위팔 · 허벅지 · 척추 키 자리에서만 방향을 바꾼다 · Ctrl+Z 한 번 · 편집 › 가져오기)
(
__ALIGN__
local pre = "__PREFIX__"
local plan = #(__PLAN__)
holdMaxFile()
local n = 0
local worst = 1.0
undo "Sonjari fit fix" on (
  with animate on (
    for p in plan do (
      local node = getNodeByName (pre + " " + p[1])
      if node != undefined do at time p[2] (
        local d = sjAlign node p[3]
        if d < worst do worst = d
        n += 1
      )
    )
  )
)
"손자리 뚫림 고침: 키 " + (n as string) + "곳 · 가장 덜 맞은 방향 " + (worst as string) + " (1 = 꼭 맞음) · 되돌리기: Ctrl+Z 또는 편집 › 가져오기"
)
'''


def write_fix_script(plan: dict[str, Any], prefix: str = "Bip001") -> str:
    from .refpose import _ALIGN_FN

    prefix = prefix.replace('"', "").replace("\\", "").strip() or "Bip001"
    items = [f'#("{b}", {f}, [{d[0]},{d[1]},{d[2]}])' for b, f, d in fix_items(plan)]
    return (FIX_SCRIPT.replace("__ALIGN__", _ALIGN_FN).replace("__PREFIX__", prefix)
            .replace("__PLAN__", ", ".join(items)))

