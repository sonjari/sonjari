# -*- coding: utf-8 -*-
"""포즈로 찾기 — 영상 키포즈와 비슷한 동작을 모션 창고에서 찾는다 (2026-11-04).

현업 애니메이터 답(11-04 카톡): 시간 제일 잡아먹는 것 = 필요한 모션 찾기 · 제일 귀찮은 일 = 레퍼런스 영상에서 포즈를 따서 내 작업물에 찍기.
→ 영상 키포즈 하나를 주면 창고 511개 동작 중 그 자세가 나오는 동작 · 프레임을 순서대로 낸다.

같은 눈금: 「팔다리 9마디가 어느 쪽을 향하나」(refpose.CHAIN 과 같은 마디).
- 영상: 3D 관절(RTMW3D, 맥스 좌표로 바꾼 것) → 마디 = 끝 관절 − 시작 관절
- 창고: 기본 바이페드에 .bip 를 입혀 2프레임마다 그 마디 노드의 transform.row1(뼈 길이 방향 — refpose 가 맞추는 축과 같다)
- 몸 크기는 방향만 써서 빠지고, 바라보는 방향(제자리 돌기)은 골반 좌우 선을 +X 로 돌려 뺀다. 위아래(누움 · 섬)는 남긴다.
- 좌우 반전도 같이 비교한다(오른손 내려찍기 = 왼손 내려찍기 거울). 반전으로 맞으면 그렇다고 적는다.

거리 = 마디마다 (1 − 방향 내적) 의 평균. 0 이면 같은 자세, 1 이면 직각, 2 면 정반대.
도구는 판단하지 않는다(현업 애니메이터 11-02) — 후보와 사진을 내놓고 고르는 건 사람이다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

BONES = ("Spine", "L Thigh", "L Calf", "R Thigh", "R Calf", "L UpperArm", "L Forearm", "R UpperArm", "R Forearm")
# 좌우 반전 때 자리 바꿈
_MIRROR = [0, 3, 4, 1, 2, 7, 8, 5, 6]
# 영상(COCO 17점): 마디 = (시작, 끝). 리스트는 가운데.
_JOINT_CHAIN: tuple[tuple[Any, Any], ...] = (
    ([11, 12], [5, 6]), (11, 13), (13, 15), (12, 14), (14, 16), (5, 7), (7, 9), (6, 8), (8, 10),
)
FEATURE_FILE = "pose_rows.json"
STEP = 2  # 창고에서 몇 프레임마다 뽑나


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n < 1e-9, 1.0, n)


def normalize(dirs: np.ndarray, side: np.ndarray) -> np.ndarray:
    """(…, 9, 3) 마디 방향 · (…, 3) 골반 좌→우 선 → 바라보는 방향을 뺀 단위 방향."""
    dirs = _unit(np.asarray(dirs, dtype=float))
    side = np.asarray(side, dtype=float)
    ang = np.arctan2(side[..., 1], side[..., 0])
    c, s = np.cos(-ang)[..., None], np.sin(-ang)[..., None]
    x, y, z = dirs[..., 0], dirs[..., 1], dirs[..., 2]
    return np.stack([c * x - s * y, s * x + c * y, z], axis=-1)


def mirror(feat: np.ndarray) -> np.ndarray:
    """좌우 반전: 왼쪽 · 오른쪽 마디를 바꾸고 좌우 축(X)을 뒤집는다."""
    out = np.asarray(feat)[..., _MIRROR, :].copy()
    out[..., 0] *= -1
    return out


def from_joints(joints: Sequence[Sequence[float]]) -> np.ndarray:
    """영상 3D 관절(맥스 좌표, refpose.to_max 를 거친 것) → (9, 3)."""
    J = np.asarray(joints, dtype=float)

    def pt(k: Any) -> np.ndarray:
        return J[k].mean(axis=0) if isinstance(k, list) else J[k]

    dirs = np.stack([pt(b) - pt(a) for a, b in _JOINT_CHAIN])
    return normalize(dirs, J[12] - J[11])  # 오른 골반 − 왼 골반 = 좌→우


def from_rows(rows: Sequence[Sequence[float]]) -> tuple[np.ndarray, np.ndarray]:
    """맥스가 쓴 줄 [프레임, 9마디 × (x,y,z), 골반 좌→우 (x,y,z)] → (프레임들, (N, 9, 3))."""
    R = np.asarray([r for r in rows if len(r) == 1 + 27 + 3], dtype=float)
    if not len(R):
        return np.zeros(0, int), np.zeros((0, 9, 3))
    return R[:, 0].astype(int), normalize(R[:, 1:28].reshape(-1, 9, 3), R[:, 28:31])


def distance(query: np.ndarray, feats: np.ndarray) -> np.ndarray:
    """query (9,3) 와 feats (N,9,3) 의 거리 (N,)."""
    return 1.0 - np.einsum("bc,nbc->nb", query, feats).mean(axis=1)


def load_features(folder: Path) -> tuple[np.ndarray, np.ndarray] | None:
    p = folder / FEATURE_FILE
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    frames, feats = from_rows(data.get("rows") or [])
    return (frames, feats) if len(frames) else None


def search(entries: Sequence[dict[str, Any]], query: np.ndarray, k: int = 5,
           allow_mirror: bool = True) -> dict[str, Any]:
    """창고 칸들 중 query 자세가 나오는 동작 순위. 동작마다 가장 가까운 프레임 하나."""
    scored: list[tuple[float, dict[str, Any]]] = []
    missing = 0
    mq = mirror(query) if allow_mirror else None
    for e in entries:
        if e.get("kind") == "model":
            continue
        got = load_features(Path(e["bip"]).parent) if e.get("bip") else None
        if got is None:
            missing += 1
            continue
        frames, feats = got
        d = distance(query, feats)
        best, mirrored = int(np.argmin(d)), False
        if mq is not None:
            dm = distance(mq, feats)
            if float(dm.min()) < float(d[best]):
                best, mirrored, d = int(np.argmin(dm)), True, dm
        scored.append((float(d[best]), {
            "id": e["id"], "name": e.get("name", ""), "character": e.get("character", ""),
            "frame": int(frames[best]), "distance": round(float(d[best]), 3), "mirrored": mirrored,
            "shots": e.get("shots", []), "origin_label": e.get("origin_label", ""),
        }))
    scored.sort(key=lambda x: x[0])
    return {"found": [row for _d, row in scored[:max(1, k)]], "compared": len(scored), "no_features": missing}


# ── 맥스: 창고 칸마다 마디 방향 뽑기 ─────────────────────────────────────────

def _q(path: Path | str) -> str:
    return '@"' + str(path).replace('"', "") + '"'


_DIALOG_GUARD = r'''
-- ★ 11-04 일괄 실행이 「Frame Rate Change」 창(동작 파일과 장면의 초당 프레임이 다름)에서 7분 멈췄다 — 누를 사람이 없다.
--   칸마다 장면 프레임을 기록값으로 맞추고(아래), 그래도 뜨면 기본 단추를 누른다.
fn sjDlg = (
  local h = DialogMonitorOPS.GetWindowHandle()
  local t = UIAccessor.GetWindowText h
  if t != undefined and (matchPattern t pattern:"*Frame Rate*") do UIAccessor.PressDefaultButton()
  true
)
DialogMonitorOPS.RegisterNotification sjDlg id:#sjPoseDlg
DialogMonitorOPS.Enabled = true
'''


def features_batch_script(jobs: Sequence[tuple], log: Path) -> str:
    """3dsmaxbatch · 열린 맥스 둘 다 쓴다. 빈 장면에 기본 바이페드 하나를 만들고 칸마다 .bip 를 입혀 2프레임마다 읽는다.

    jobs = (창고 칸 폴더, 시작 프레임, 끝 프레임[, 초당 프레임]). 원본 .max 를 열지 않는다 — 방향만 쓰니 체형이 달라도 된다.
    열린 맥스에서 부를 때는 부르는 쪽이 먼저 장면을 비우거나 보관해야 한다(이 스크립트는 바이페드를 새로 만든다).
    """
    names = "#(" + ", ".join(f'"{b}"' for b in BONES) + ")"
    L = [
        "-- 손자리 애니메이터 팩: 포즈로 찾기 — 창고 칸마다 마디 방향 뽑기",
        "(",
        _DIALOG_GUARD,
        'local log = stringStream ""',
        f"local bones = {names}",
        # 열린 맥스에서도 쓰므로, 만들기 전 장면을 적어 두고 끝나면 새로 생긴 것(임시 바이페드)만 지운다.
        "local before = objects as array",
        "local com = biped.createNew 170 -90 [0,0,0]",
        "local ctrl = com.controller",
        "local pre = com.name",
        "fn sjDir n = (local r = normalize n.transform.row1; (r.x as string) + \",\" + (r.y as string) + \",\" + (r.z as string))",
    ]
    for job in jobs:
        folder, start, end = job[0], int(job[1]), int(job[2])
        fps = int(job[3]) if len(job) > 3 and job[3] else 30
        bip = folder / "motion.bip"
        out = folder / FEATURE_FILE
        L.append(
            f"try (frameRate = {fps}; biped.loadBipFile ctrl {_q(bip)} #matchFileStruct #noRedraw; "
            f"local nodes = for b in bones collect getNodeByName (pre + \" \" + b) exact:true; "
            f"local lt = getNodeByName (pre + \" L Thigh\") exact:true; local rt = getNodeByName (pre + \" R Thigh\") exact:true; "
            f"local ss = stringStream \"\"; format \"{{\\\"start\\\":{start},\\\"end\\\":{end},\\\"rows\\\":[\" to:ss; "
            f"local first = true; "
            f"for f = {start} to {end} by {STEP} do at time f ( "
            f"if not first do format \",\" to:ss; first = false; format \"[%\" f to:ss; "
            f"for n in nodes do (if n == undefined then format \",0,0,0\" to:ss else format \",%\" (sjDir n) to:ss); "
            f"local s = rt.transform.pos - lt.transform.pos; format \",%,%,%]\" s.x s.y s.z to:ss); "
            f"format \"]}}\" to:ss; "
            f"(dotNetClass \"System.IO.File\").WriteAllText {_q(out)} (ss as string); "
            f"format \"ok %\\n\" {_q(folder.name)} to:log) "
            f"catch (format \"error % %\\n\" {_q(folder.name)} (getCurrentException()) to:log)"
        )
    L.append("try (delete (for o in objects where findItem before o == 0 collect o)) catch ()")
    L.append("DialogMonitorOPS.unRegisterNotification id:#sjPoseDlg")
    L.append(f'(dotNetClass "System.IO.File").WriteAllText {_q(log)} (log as string)')
    L.append('"sonjari: pose features done"')
    L.append(")")
    return "\n".join(L) + "\n"
