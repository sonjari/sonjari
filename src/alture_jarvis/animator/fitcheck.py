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
  -- 위팔 키 자리(고칠 때 그 자리에서만 고친다 — 키 수를 늘리지 않는다)
  format "],\"keys\":{" to:fs
  local sides = #("L", "R")
  for k = 1 to 2 do (
    local ua = getNodeByName (pre + " " + sides[k] + " UpperArm")
    local ts = #()
    if ua != undefined do try (for i = 1 to ua.controller.keys.count do (local f = ua.controller.keys[i].time.frame as integer; if f >= S and f <= E do appendIfUnique ts f)) catch ()
    format "\"%\":[" sides[k] to:fs
    for i = 1 to ts.count do format "%%" ts[i] (if i < ts.count then "," else "") to:fs
    format "]%" (if k == 1 then "," else "") to:fs
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
  try (root.controller.figureMode = true; figOk = true) catch ()
  format "],\"fig\":[%" (if figOk then 1 else 0) to:fs
  for n in nodes do format ",[%]" (sjM n.transform) to:fs
  format "],\"verts\":[" to:fs
  local first = true
  local nv = 0
  (
    for o in geometry where not (classOf o == Biped_Object) and not o.isHidden do (
      local deformed = false
      for m in o.modifiers where (classOf m == Skin or classOf m == Physique) do deformed = true
      if deformed do (
        local msh = snapshotAsMesh o
        local cnt = msh.numverts
        local step = if cnt > 6000 then (cnt / 6000 + 1) else 1
        for v = 1 to cnt by step do (
          local p = getVert msh v
          format "%[%,%,%]" (if first then "" else ",") (sjNum p.x) (sjNum p.y) (sjNum p.z) to:fs
          first = false
          nv += 1
        )
        delete msh
      )
    )
  )
  try (root.controller.figureMode = wasFig) catch ()
  format "]}" to:fs
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
    owner = np.array(keys)[d.argmin(axis=1)]
    vols: dict[str, Any] = {}
    for part, (cands, members) in BODY.items():
        bone = next((c for c in cands if c in mats), None)
        pts = v[np.isin(owner, members)]
        if bone is None or len(pts) < 12:
            continue
        local = (np.c_[pts, np.ones(len(pts))] @ np.linalg.inv(mats[bone]))[:, :3]
        lo, hi = np.percentile(local, 2, axis=0), np.percentile(local, 98, axis=0)
        vols[part] = {"bone": bone, "center": ((lo + hi) / 2).round(5).tolist(), "radii": ((hi - lo) / 2).round(5).tolist(),
                      "points": int(len(pts))}
    thick = {}
    for limb, bones in (("팔", ["L Forearm", "R Forearm"]), ("다리", ["L Thigh", "R Thigh", "L Calf", "R Calf"])):
        ds = [d[owner == b, keys.index(b)] for b in bones if b in keys and (owner == b).sum() >= 6]
        thick[limb] = float(np.median(np.concatenate(ds))) if ds else 0.0
    return {"volumes": vols, "thickness": thick}


def _probe_points(seg: dict[str, tuple[np.ndarray, np.ndarray]]) -> dict[tuple[str, str], np.ndarray]:
    out = {}
    for s, side in (("L", "왼"), ("R", "오른")):
        fa, hd = seg.get(f"{s} Forearm"), seg.get(f"{s} Hand")
        if fa and hd:
            out[("팔", side)] = np.array([fa[0], (fa[0] + fa[1]) / 2, fa[1], (hd[0] + hd[1]) / 2, hd[1]])
        th, ca = seg.get(f"{s} Thigh"), seg.get(f"{s} Calf")
        if th and ca:
            out[("다리", side)] = np.array([ca[0]])            # 무릎만 — 허벅지 가운데는 원래 골반 옆이라 늘 걸렸다(11-06)
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


FIX_SCRIPT = r'''-- 손자리 애니메이터 팩: 팔 뚫림 자동 수정 (위팔 키 자리에서만 방향을 바꾼다 · Ctrl+Z 한 번 · 편집 › 가져오기)
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
      local node = getNodeByName (pre + " " + p[1] + " UpperArm")
      if node != undefined do at time p[2] (
        local d = sjAlign node p[3]
        if d < worst do worst = d
        n += 1
      )
    )
  )
)
"손자리 팔 고침: 위팔 키 " + (n as string) + "곳 · 가장 덜 맞은 방향 " + (worst as string) + " (1 = 꼭 맞음) · 되돌리기: Ctrl+Z 또는 편집 › 가져오기"
)
'''


def write_fix_script(plan: dict[str, Any], prefix: str = "Bip001") -> str:
    from .refpose import _ALIGN_FN

    prefix = prefix.replace('"', "").replace("\\", "").strip() or "Bip001"
    items = [f'#("{s}", {f}, [{d[0]},{d[1]},{d[2]}])' for s, rows in plan["keys"].items() for f, d, _deg in rows]
    return (FIX_SCRIPT.replace("__ALIGN__", _ALIGN_FN).replace("__PREFIX__", prefix)
            .replace("__PLAN__", ", ".join(items)))

