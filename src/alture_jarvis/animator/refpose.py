# -*- coding: utf-8 -*-
"""레퍼런스 포즈 시트 · 영상 → 바이페드 블로킹 (2026-11-03 · bench/animator_real 의 ref_sheet · max_guides · fit_biped 를 옮김).

1) 포즈 시트: 영상 파일(mp4 …) 또는 찍어 둔 프레임 폴더 → 프레임마다 2D 관절 → 「몸이 멈춘 순간」 N 장 + 뼈대 + 속도 곡선
   - 카메라 이동 빼기: 골반 가운데를 원점, 어깨~골반 길이로 나눈 좌표에서 속도를 잰다
   - 고르기: 속도 골짜기 중 깊은 순서로, 서로 10프레임 이상 떨어지고 자세가 비슷하면 하나만(11-03 첫 시트에서 같은 자세 두 장)
   - 관절을 한 장 잘못 잡으면 곡선이 튄다 → 상위 5% 위는 깎는다
   - 정확도는 아직 주장하지 않는다(회사 캐릭터 공격 3개 정답 대조 F1 0.73 / 0.36 / 0.17, n=3)
2) 영상 → 바이페드: 시트가 고른 장면마다 3D 관절(RTMW3D) → 뼈마다 방향을 맞추는 맥스 스크립트
   - 부모부터 한 마디씩 돌리고, 돌린 뒤 실제 방향을 다시 읽어 일치(내적)를 재고, 나쁘면 반대로(회전 부호를 믿지 않는다)
   - 11-03 회사 캐릭터 시험: 72뼈 중 70이 0.95 이상
   - 「영상 변환 초안」이다 — 블로킹 초안이지 완성 동작이 아니다
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import pose_onnx

BODY = list(range(5, 17))
EDGES = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MAX_FRAMES = 450          # 30fps 로 15초. 11-03 이 PC CPU 로 421장 156초 — 도구 한 번 300초 안에 들게. 넘으면 구간을 좁히거나 stride


def _imread(path: Path) -> np.ndarray | None:
    import cv2

    data = np.fromfile(str(path), dtype=np.uint8)          # 한글 경로
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def _imwrite(path: Path, img: np.ndarray, quality: int = 90) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError(f"사진을 쓰지 못했다: {path}")
    buf.tofile(str(path))


def iter_frames(source: Path, start_sec: float = 0.0, end_sec: float | None = None, stride: int = 1):
    """(프레임 번호, 초, 그림) 을 낸다. 영상 파일이면 cv2 로 읽고, 폴더면 이름 순 사진(30fps 로 친다)."""
    import cv2

    if source.is_dir():
        files = sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_EXT and not p.name.startswith("_"))  # _chart.png 같은 부산물 빼기
        for i, f in enumerate(files[::stride]):
            sec = start_sec + i * stride / 30.0
            if end_sec is not None and sec > end_sec:
                break
            img = _imread(f)
            if img is not None:
                yield i * stride, sec, img
        return
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise FileNotFoundError(f"영상을 열지 못했다: {source}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000.0)
    i = 0
    try:
        while True:
            ok, img = cap.read()
            if not ok:
                break
            sec = start_sec + i / fps
            if end_sec is not None and sec > end_sec:
                break
            if i % stride == 0:
                yield i, sec, img
            i += 1
    finally:
        cap.release()


def body_speed(kp: np.ndarray, conf_min: float = 0.35) -> np.ndarray:
    xy = kp[:, :, :2].copy()
    ok = kp[:, :, 2] > conf_min
    xy[~ok] = np.nan
    import warnings

    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        hip = np.nanmean(xy[:, [11, 12]], axis=1)
        sh = np.nanmean(xy[:, [5, 6]], axis=1)
        scale = np.linalg.norm(sh - hip, axis=1)
        rel = (xy - hip[:, None, :]) / scale[:, None, None]
        v = np.linalg.norm(np.diff(rel[:, BODY], axis=0), axis=2)
        speed = np.nanmean(v, axis=1)
    valid = np.isfinite(speed) & (np.sum(ok[1:, BODY], axis=1) >= 8)
    speed = np.where(valid, speed, np.nan)
    if np.isfinite(speed).any():
        cap = np.nanpercentile(speed, 95)
        speed = np.where(speed > cap, cap, speed)
    return speed


def smooth(x: np.ndarray, k: int = 5) -> np.ndarray:
    y = x.copy()
    good = np.isfinite(y)
    if not good.any():
        return y
    y[~good] = np.nanmedian(y)
    pad = np.pad(y, (k // 2, k // 2), mode="edge")
    out = np.convolve(pad, np.ones(k) / k, mode="valid")
    out[~good] = np.nan
    return out


def pose_vec(kp: np.ndarray) -> np.ndarray:
    xy = kp[:, :2]
    hip = xy[[11, 12]].mean(axis=0)
    sh = xy[[5, 6]].mean(axis=0)
    return ((xy[BODY] - hip) / (np.linalg.norm(sh - hip) + 1e-6)).ravel()


def pick(speed: np.ndarray, n: int, kp: np.ndarray | None = None, w: int = 8, gap: int = 10, same: float = 0.35) -> list[int]:
    """speed[t] 는 프레임 t → t+1 사이 속도. 돌려주는 값은 speed 의 자리 t(사진은 t+1)."""
    cand = []
    for t in range(1, len(speed) - 1):
        a, b, c = speed[t - 1], speed[t], speed[t + 1]
        if not (np.isfinite(a) and np.isfinite(b) and np.isfinite(c)) or not (b <= a and b <= c):
            continue
        with np.errstate(all="ignore"):
            left = np.nanmax(speed[max(0, t - w):t])
            right = np.nanmax(speed[t + 1:t + 1 + w])
        cand.append((min(left, right) - b, t))
    picks: list[int] = []
    for _d, t in sorted(cand, reverse=True):
        if not all(abs(t - p) >= gap for p in picks):
            continue
        if kp is not None and any(np.nanmean(np.abs(pose_vec(kp[t + 1]) - pose_vec(kp[p + 1]))) < same for p in picks):
            continue
        picks.append(t)
        if len(picks) >= n:
            break
    return sorted(picks)


def _draw(img: np.ndarray, kp: np.ndarray, label: str) -> np.ndarray:
    import cv2

    im = img.copy()
    for a, b in EDGES:
        if kp[a, 2] > 0.35 and kp[b, 2] > 0.35:
            cv2.line(im, tuple(int(v) for v in kp[a, :2]), tuple(int(v) for v in kp[b, :2]), (40, 230, 255), 4, cv2.LINE_AA)
    for j in BODY:
        if kp[j, 2] > 0.35:
            cv2.circle(im, tuple(int(v) for v in kp[j, :2]), 6, (255, 80, 200), -1, cv2.LINE_AA)
    cv2.rectangle(im, (0, 0), (im.shape[1], 54), (20, 20, 20), -1)
    cv2.putText(im, label, (14, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
    return im


def _chart(s: np.ndarray, picks: list[int], width: int, height: int = 200) -> np.ndarray:
    import cv2

    img = np.full((height, width, 3), 250, np.uint8)
    good = np.isfinite(s)
    if good.sum() < 2:
        return img
    lo, hi = float(np.nanmin(s)), float(np.nanmax(s))
    span = hi - lo or 1.0
    xs = np.linspace(20, width - 20, len(s))
    ys = height - 20 - (np.nan_to_num(s, nan=lo) - lo) / span * (height - 50)
    pts = np.stack([xs, ys], 1).astype(np.int32)
    cv2.polylines(img, [pts], False, (80, 80, 80), 2, cv2.LINE_AA)
    for i, t in enumerate(picks):
        x = int(xs[t])
        cv2.line(img, (x, 10), (x, height - 10), (160, 64, 224), 2)
        cv2.putText(img, str(i + 1), (x + 4, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (160, 64, 224), 2, cv2.LINE_AA)
    return img


def pose_sheet(source: Path, out: Path, parts: dict[str, Path], *, n: int = 8, start_sec: float = 0.0,
               end_sec: float | None = None, stride: int = 1, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """첫 훑기: 관절만 적는다(그림은 들고 있지 않는다 — 900장이면 2GB 넘는다). 둘째 훑기: 고른 장면만 꺼낸다."""
    import cv2

    det, p2 = pose_onnx.Detector(parts["det"]), pose_onnx.Pose2D(parts["pose2d"])
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    frames: list[tuple[int, float]] = []
    kps = []
    for count, (i, sec, img) in enumerate(iter_frames(source, start_sec, end_sec, stride)):
        if count >= MAX_FRAMES:
            raise ValueError(f"too_long: 프레임이 {MAX_FRAMES} 장을 넘는다 — start_sec · end_sec 로 동작 한 번 구간만 자르거나 stride=2(한 장 건너 읽기)로")
        box = pose_onnx.biggest(det(img))
        kps.append(np.full((17, 3), np.nan) if box is None else p2(img, box))
        frames.append((i, sec))
        if progress and count % 30 == 0:
            progress(f"관절 읽는 중 {count}장")
    if len(frames) < 12:
        raise ValueError("프레임이 너무 적다(12장 미만) — 구간을 넓히거나 영상을 확인해 달라")
    kp = np.array(kps)
    s = smooth(body_speed(kp), 5)
    picks = pick(s, n, kp=kp)
    want = {frames[t + 1][0]: k for k, t in enumerate(picks)}
    grabbed: dict[int, np.ndarray] = {}
    for i, _sec, img in iter_frames(source, start_sec, end_sec, stride):
        if i in want:
            grabbed[want[i]] = img
            if len(grabbed) == len(want):
                break
    tiles, picked = [], []
    for k, t in enumerate(picks):
        f = t + 1
        img = grabbed.get(k)
        if img is None:
            continue
        sec = frames[f][1]
        frame_path = out / f"pick_{k + 1}.jpg"
        _imwrite(frame_path, img, 95)                      # 3D 단계가 다시 읽는다 — 원본 크기 그대로
        ratio = max(1.0, img.shape[0] / 720)
        small = img if ratio == 1.0 else cv2.resize(img, (int(img.shape[1] / ratio), int(img.shape[0] / ratio)))
        kp_s = kp[f].copy()
        kp_s[:, :2] /= ratio
        tiles.append(_draw(small, kp_s, f"{k + 1}. {int(sec // 60)}:{sec % 60:05.2f}"))
        picked.append({"no": k + 1, "frame": frames[f][0], "sec": round(sec, 3), "image": str(frame_path)})
    sheet_path = out / "pose_sheet.jpg"
    if tiles:
        cols = min(4, len(tiles))
        h, w = tiles[0].shape[:2]
        tiles = [t if t.shape[:2] == (h, w) else cv2.resize(t, (w, h)) for t in tiles]
        rows = (len(tiles) + cols - 1) // cols
        board = np.full((rows * h, cols * w, 3), 25, np.uint8)
        for k, im in enumerate(tiles):
            board[(k // cols) * h:(k // cols + 1) * h, (k % cols) * w:(k % cols + 1) * w] = im
        _imwrite(sheet_path, np.vstack([board, _chart(s, picks, board.shape[1])]))
    info = {"source": str(source), "frames": len(frames), "found_person": int(np.isfinite(kp[:, 11, 0]).sum()),
            "picks": picked, "sheet": str(sheet_path) if tiles else None, "seconds": round(time.time() - t0, 1)}
    (out / "pose_sheet.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


# ── 영상 → 바이페드 ─────────────────────────────────────────────────────────

# (바이페드 마디 이름 꼬리, 가이드 시작 관절, 가이드 끝 관절) — COCO 17점. 리스트면 그 점들의 가운데
CHAIN = [
    ("Spine", [11, 12], [5, 6]),
    ("L Thigh", 11, 13), ("L Calf", 13, 15),
    ("R Thigh", 12, 14), ("R Calf", 14, 16),
    ("L UpperArm", 5, 7), ("L Forearm", 7, 9),
    ("R UpperArm", 6, 8), ("R Forearm", 8, 10),
]


def to_max(k: np.ndarray) -> np.ndarray:
    """RTMW3D simcc 눈금(x 오른쪽 · y 아래 · z 깊이) → 맥스(X 오른쪽 · Y 깊이 · Z 위). 방향만 쓰므로 크기는 맞추지 않는다."""
    return np.c_[k[:, 0], k[:, 2], -k[:, 1]]


def lift(sheet: dict[str, Any], parts: dict[str, Path], use: list[int] | None = None) -> list[dict[str, Any]]:
    det, p3 = pose_onnx.Detector(parts["det"]), pose_onnx.Pose3D(parts["pose3d"])
    poses = []
    for p in sheet["picks"]:
        if use and p["no"] not in use:
            continue
        img = _imread(Path(p["image"]))
        box = pose_onnx.biggest(det(img)) if img is not None else None
        if box is None:
            poses.append({"no": p["no"], "missing": True})
            continue
        k = p3(img, box)
        poses.append({"no": p["no"], "joints": to_max(k[:, :3]).round(3).tolist(), "score": k[:, 3].round(3).tolist()})
    return poses


_ALIGN_FN = r'''
fn sjAlign n target = (
  local cur = normalize n.transform.row1
  local t = normalize target
  local d0 = dot cur t
  local ax = cross cur t
  if (length ax) < 0.00001 do return d0
  ax = normalize ax
  local ang = acos (amax -1.0 (amin 1.0 d0))
  local base = n.transform
  local best = d0
  local bestRot = base.rotation
  for sgn in #(1, -1) do (
    local r = (angleaxis (ang * sgn) ax) as matrix3
    local tm = copy base
    tm.row1 = base.row1 * r; tm.row2 = base.row2 * r; tm.row3 = base.row3 * r
    biped.setTransform n #rotation tm.rotation true
    local d = dot (normalize n.transform.row1) t
    -- 11-10 맥스 실측: 문턱이 0.99(약 8도)면 4도보다 작은 고침은 반대로 돌고도 통과했다(2도 → 목표와 4도 어긋남).
    if d > 0.99999 do return d
    if d > best do (best = d; bestRot = tm.rotation)
  )
  biped.setTransform n #rotation bestRot true      -- 둘 다 덜 맞으면 가장 나았던 쪽(처음보다 나쁘면 처음 그대로)
  best
)
'''


_ELBOW_FN = r'''
fn sjElbow ua fa target = (
  -- 위팔 방향은 그대로 두고 제 축(row1)으로 비틀어 가며 아래팔을 맞춰 보고, 가장 잘 맞은 비틀기로 둔다
  if ua == undefined do return (sjAlign fa target)
  local base = ua.transform
  local ax = normalize base.row1
  local best = -2.0
  local bestA = 0
  for a = 0 to 345 by 15 do (
    local r = (angleaxis a ax) as matrix3
    local tm = copy base
    tm.row1 = base.row1 * r; tm.row2 = base.row2 * r; tm.row3 = base.row3 * r
    biped.setTransform ua #rotation tm.rotation true
    local d = sjAlign fa target
    if d > best do (best = d; bestA = a)
  )
  local r = (angleaxis bestA ax) as matrix3
  local tm = copy base
  tm.row1 = base.row1 * r; tm.row2 = base.row2 * r; tm.row3 = base.row3 * r
  biped.setTransform ua #rotation tm.rotation true
  sjAlign fa target
)
'''

_FACING_FN = r'''
fn sjFacing com lt rt target = (
  -- 11-05: 몸통이 어느 쪽을 보나(수직축 회전)를 영상 골반 좌우 선에 맞춘다. 돌린 뒤 실제로 가까워졌는지 재고 아니면 반대로.
  if com == undefined or lt == undefined or rt == undefined do return -1.0
  local t = normalize [target.x, target.y, 0]
  fn hip lt rt = (local v = rt.transform.pos - lt.transform.pos; normalize [v.x, v.y, 0])
  local d0 = dot (hip lt rt) t
  local ang = acos (amax -1.0 (amin 1.0 d0))
  if ang < 0.5 do return d0
  local base = com.transform
  local best = d0
  local bestRot = base.rotation
  for sgn in #(1, -1) do (
    local tm = copy base
    tm = tm * (inverse (transMatrix base.pos)) * ((angleaxis (ang * sgn) [0,0,1]) as matrix3) * (transMatrix base.pos)
    biped.setTransform com #rotation tm.rotation true
    local d = dot (hip lt rt) t
    if d > 0.99999 do return d          -- 11-10: 0.99 면 4도 아래는 반대로 돌고도 통과했다(sjAlign 과 같은 뿌리)
    if d > best do (best = d; bestRot = tm.rotation)
  )
  biped.setTransform com #rotation bestRot true
  dot (hip lt rt) t
)
'''

_DEG2D_FN = r'''
fn sjDeg2D n target = (
  -- 영상 화면 평면(맥스 X 오른쪽 · Z 위 = to_max 가 옮긴 영상 x · -y)에서 뼈 방향과 영상 관절 방향의 각도 차이(도)
  local a = [n.transform.row1.x, 0, n.transform.row1.z]
  local b = [target.x, 0, target.z]
  if (length a) < 0.00001 or (length b) < 0.00001 then -1.0 else (
    acos (amax -1.0 (amin 1.0 (dot (normalize a) (normalize b))))
  )
)
'''


#: 어깨 화면 폭 ÷ 화면 몸통 길이가 이보다 작으면 옆모습 — 앞 · 뒤를 숫자로 못 가른다(11-05 맥스 6번 0.01).
FACING_SIDE = 0.1
#: 어깨 · 골반 관절 확신도 가장 낮은 것이 이보다 작으면 좌우 이름표를 못 믿는다(11-10 · 블렌더 시험 캐릭터 2번 장면).
#: 11-05 밤 시험 캐릭터 블로킹 6장면: 뒤집힌 2번 0.34 · 나머지 0.42~0.59. 2번은 옆모습 규칙(0.91)으로는 못 잡았다. 표본 6 — 다시 볼 것.
FACING_SCORE = 0.4


def facing_doubt(pose: dict[str, Any]) -> dict[str, Any]:
    """몸이 보는 방향(골반 좌우 선)을 믿어도 되나. 블로킹은 골반 좌 → 우 선으로 몸통을 돌리므로, 이 선이 틀리면 장면이 통째로 좌우 · 앞뒤가 뒤집힌다.

    11-10 시험 캐릭터 2번: 숫자로 바로잡을 단서(코 · 귀 · 무릎 굽는 쪽 · 몸 기울기)가 장면마다 어긋나 고치지는 못했다 — 대신 사람에게 짚어 준다.
    """
    J = pose["joints"]
    sc = [(J[5][c] + J[6][c]) / 2 for c in range(3)]
    hc = [(J[11][c] + J[12][c]) / 2 for c in range(3)]
    torso = ((sc[0] - hc[0]) ** 2 + (sc[2] - hc[2]) ** 2) ** 0.5
    side = abs(J[6][0] - J[5][0]) / torso if torso > 1e-6 else 0.0
    score = pose.get("score")
    low = min(float(score[k]) for k in (5, 6, 11, 12)) if score and len(score) > 12 else None
    why = []
    if side < FACING_SIDE:
        why.append("옆모습(어깨가 화면에서 겹침)")
    if low is not None and low < FACING_SCORE:
        why.append(f"어깨 · 골반 관절을 흐리게 잡음(확신 {low:.2f})")
    return {"sure": round(side, 2), "torso_score": None if low is None else round(low, 2), "unsure": bool(why), "why": why}


def facing_report(poses: list[dict[str, Any]]) -> dict[str, Any] | None:
    bad = [{"pose": p["no"], "why": " · ".join(fd["why"])} for p in poses if not p.get("missing")
           for fd in [facing_doubt(p)] if fd["unsure"]]
    if not bad:
        return None
    return {"poses": [b["pose"] for b in bad], "detail": bad,
            "note": "이 장면은 몸이 보는 방향(앞 · 뒤 · 좌우)이 뒤집혔을 수 있다 — 영상과 나란히 놓고 사람이 확인하게 해라. "
                    "뒤집혔으면 그 키에서 몸통(COM · 골반)만 수직축으로 돌리면 된다."}


def key_frames(poses: list[dict[str, Any]], start: int, spacing: int, fps: float = 30.0,
               timing: str = "video") -> list[int]:
    """키 자리. 11-05: 0 · 10 · 20 … 똑같은 간격은 영상의 예비 · 타격 · 회복 리듬을 지웠다 →
    기본은 영상 속 시각(sec)을 이 장면 fps 로 옮긴 자리. 시각이 없거나 timing="even" 이면 예전처럼 똑같은 간격."""
    good = [p for p in poses if not p.get("missing")]
    secs = [p.get("sec") for p in good]
    if timing != "even" and good and all(isinstance(s, (int, float)) for s in secs):
        out, last = [], None
        for s in secs:
            f = start + int(round((s - secs[0]) * fps))
            if last is not None and f <= last:
                f = last + 1                       # 같은 자리에 두 키가 겹치지 않게
            out.append(f)
            last = f
        return out
    return [start + i * spacing for i in range(len(good))]


def biped_fit_script(poses: list[dict[str, Any]], prefix: str, start: int, spacing: int, report: Path,
                     frames: list[int] | None = None) -> str:
    """자세 i 를 frames[i](없으면 start + i*spacing) 프레임에 바이페드 키로. holdMaxFile + undo 한 묶음.

    보고에는 뼈마다 3D 맞춤(dot)과 함께 **영상 화면 평면에서의 각도 차이(deg2d)** 를 남긴다 — 레퍼런스를 보는 사람 눈과 같은 면.
    """
    L = ["-- 손자리 애니메이터 팩: 영상 → 바이페드 블로킹 초안(입히기 전 장면을 보관(Hold)하고, Ctrl+Z 한 묶음)", "(",
         _ALIGN_FN, _ELBOW_FN, _FACING_FN, _DEG2D_FN, 'local rep = stringStream ""', 'format "[" to:rep', "holdMaxFile()",
         'undo "Sonjari video blocking" on (']
    placed = 0
    for i, p in enumerate(q for q in poses if not q.get("missing")):
        f = frames[i] if frames and i < len(frames) else start + i * spacing
        J = p["joints"]
        L.append(f"sliderTime = {f}f")
        L.append("with animate on (")
        hv = [J[12][c] - J[11][c] for c in range(3)]  # 왼쪽 엉덩이 → 오른쪽 엉덩이(COCO 11 · 12)
        # 11-05 6번 장면: 양 어깨가 화면에서 거의 겹친 옆모습(왼 184.5 · 오른 184.0)에서 앞 · 뒤가 거꾸로 읽혔다.
        # 화면 가로 어깨 폭 ÷ 화면 몸통 길이(골반 가운데→어깨 가운데)가 0.1 아래면 앞뒤를 숫자로 못 가른다 → 「방향 애매」로 보고.
        # (처음엔 3D 어깨 길이로 나눴는데 깊이 축 눈금이 화면과 달라 6번은 놓치고 맞게 나온 1번을 잡았다 — 화면 것끼리만 견준다.)
        # 문턱 0.1 은 장면 8개로 정했다: 6번 0.01 · 나머지 0.14~1.17(맞게 나온 1번이 0.14 로 가깝다 — 표본을 늘려 다시 볼 것)
        # 11-10: 어깨 · 골반 관절 확신도도 같이 남긴다(옆모습 규칙만으로는 블렌더 시험 캐릭터 2번을 못 잡았다) — facing_doubt
        fdb = facing_doubt(p)
        ts = "null" if fdb["torso_score"] is None else f'{fdb["torso_score"]:.2f}'
        L.append(f'(local fd = sjFacing (getNodeByName "{prefix}" exact:true) (getNodeByName "{prefix} L Thigh" exact:true) '
                 f'(getNodeByName "{prefix} R Thigh" exact:true) [{hv[0]:.4f},{hv[1]:.4f},{hv[2]:.4f}]; '
                 f'format "{{\\"pose\\":{p["no"]},\\"frame\\":{f},\\"facing\\":%,\\"facing_sure\\":{fdb["sure"]:.2f},'
                 f'\\"torso_score\\":{ts}}}," fd to:rep)')
        for tail, a, b in CHAIN:
            def pt(x):
                if isinstance(x, list):
                    return [sum(J[k][c] for k in x) / len(x) for c in range(3)]
                return J[x]
            A, B = pt(a), pt(b)
            v = [B[c] - A[c] for c in range(3)]
            name = f"{prefix} {tail}"
            tv = f"[{v[0]:.4f},{v[1]:.4f},{v[2]:.4f}]"
            # 11-05 쿠키 실측: 화면에서 15도 넘게 어긋난 9곳 중 8곳이 아래팔 — 바이페드 팔꿈치는 한 방향 경첩이라
            # 아무 방향으로나 돌리면 막힌다 → 위팔을 제 축으로 비틀어 접히는 면을 맞춘 뒤 접는다(sjElbow)
            # 무릎도 한 방향 경첩 — 몸통 방향을 맞춘 뒤 종아리 하나가 거꾸로(178도) 꺾였다 → 허벅지 비틀기로 같은 방법
            parent = {"Forearm": "UpperArm", "Calf": "Thigh"}.get(tail.split()[-1])
            fit_call = (f"sjElbow (getNodeByName \"{prefix} {tail.split()[0]} {parent}\" exact:true) n {tv}"
                        if parent else f"sjAlign n {tv}")
            L.append(f'(local n = getNodeByName "{name}" exact:true; if n != undefined then (local dd = {fit_call}; '
                     f'format "{{\\"pose\\":{p["no"]},\\"frame\\":{f},\\"bone\\":\\"{name}\\",\\"dot\\":%,\\"deg2d\\":%}}," dd (sjDeg2D n {tv}) to:rep) '
                     f'else format "{{\\"pose\\":{p["no"]},\\"bone\\":\\"{name}\\",\\"missing\\":true}}," to:rep)')
        L.append(")")
        placed += 1
    L += [")", 'format "{}]" to:rep',
          f'(dotNetClass "System.IO.File").WriteAllText @"{report}" (rep as string)',
          f'"sonjari: blocked {placed} poses from frame {start} every {spacing} · 되돌리기: Ctrl+Z 또는 편집 › 가져오기(Fetch)"', ")"]
    return "\n".join(L) + "\n"


def read_fit_report(path: Path) -> dict[str, Any]:
    from .maxscript import load_dump

    rows = [r for r in load_dump(path) if r]
    fitted = [r for r in rows if "dot" in r]
    weak = [r for r in fitted if float(r["dot"]) < 0.95]
    out = {"bones": len(fitted), "weak": len(weak), "missing": sorted({r["bone"] for r in rows if r.get("missing")}),
           "weak_list": weak[:12]}
    unsure = sorted({int(r["pose"]) for r in rows if "facing_sure" in r and (
        float(r["facing_sure"]) < FACING_SIDE or (r.get("torso_score") is not None and float(r["torso_score"]) < FACING_SCORE))})
    if unsure:
        out["facing_unsure"] = {"poses": unsure,
                                "note": "옆모습이거나 어깨 · 골반 관절을 흐리게 잡은 장면이라 앞 · 뒤 · 좌우가 뒤집혔을 수 있다 — "
                                        "이 장면은 몸 방향을 사람이 확인"}
    degs = [float(r["deg2d"]) for r in fitted if float(r.get("deg2d", -1)) >= 0]
    if degs:
        degs.sort()
        out["screen_angle_deg"] = {"median": round(degs[len(degs) // 2], 1), "max": round(degs[-1], 1),
                                   "over_15": sum(d > 15 for d in degs), "of": len(degs)}
    return out


# ── 따로 된 프로세스에서 돌리기 ───────────────────────────────────────────────
# 11-06 실측: 같은 106장이 직접 돌리면 40초, 본체(8091) 안에서 돌리면 188초(4.6배 · 211장 88 → 376초).
# 본체 안에서는 일하는 스레드가 5초 중 0.3초만 CPU 를 받았고, 그동안 /health 도 5.2초 걸렸다(본체가 같이 막힘).
# 우선순위(보통 80초 · 낮음 86초) · torch/ctranslate2 를 먼저 올려 둔 것(40~41초)으로는 재현되지 않았다 — 본체 안 스레드끼리의
# 다툼으로 짐작(py-spy 없이 정확한 스레드는 못 집음). 그래서 무거운 계산은 장표 맞춤(slides.fit_in_subprocess)처럼 따로 돌린다.

ISOLATED_TIMEOUT = 280.0     # 클로드 쪽 MCP 시간 제한이 300초 — 그 안에 답을 돌려줘야 「멈췄다」로 안 보인다


def run_isolated(cmd: str, payload: dict[str, Any], *, timeout: float = ISOLATED_TIMEOUT) -> dict[str, Any]:
    import subprocess
    import sys

    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "alture_jarvis.animator.refpose", cmd],
            input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=str(Path(__file__).resolve().parents[2]),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"too_slow: {int(timeout)}초 안에 못 끝냈다 — start_sec · end_sec 로 구간을 줄이거나 stride=2") from exc
    lines = [line for line in (proc.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        raise RuntimeError(f"pose_worker_failed: {(proc.stderr or proc.stdout or '')[-400:]}")
    out = json.loads(lines[-1])
    if not out.get("ok"):
        kind = {"ValueError": ValueError, "FileNotFoundError": FileNotFoundError}.get(out.get("kind"), RuntimeError)
        raise kind(out.get("error") or "pose_worker_failed")
    return out["result"]


def _worker(cmd: str) -> None:
    import sys

    try:
        p = json.loads(sys.stdin.read())
        need = {k: Path(v) for k, v in p["parts"].items()}
        if cmd == "sheet":
            res: Any = pose_sheet(Path(p["source"]), Path(p["out"]), need, n=int(p.get("n", 8)),
                                  start_sec=float(p.get("start_sec") or 0.0), end_sec=p.get("end_sec"),
                                  stride=int(p.get("stride") or 1))
        elif cmd == "lift":
            sheet = json.loads(Path(p["sheet"]).read_text(encoding="utf-8"))
            res = lift(sheet, need, p.get("use"))
        else:
            raise ValueError(f"unknown: {cmd}")
        print(json.dumps({"ok": True, "result": res}, ensure_ascii=False))
    except Exception as exc:  # 부모가 같은 종류로 다시 던진다
        print(json.dumps({"ok": False, "kind": type(exc).__name__, "error": str(exc)}, ensure_ascii=False))


if __name__ == "__main__":
    import sys as _sys

    _worker(_sys.argv[1] if len(_sys.argv) > 1 else "")
