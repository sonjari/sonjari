# -*- coding: utf-8 -*-
"""영상 짜임 분석기 — 작은 흑백 화면 묶음(초당 FPS장)에서 컷 · 겹쳐 넘기기 · 확대/축소 · 자막 박자를 숫자로.

11-01 MVP(`generated_reports/video_pack_mvp_1101/code/scan.py`)를 옮겨 왔다. 화면 묶음은 어디서 와도 된다:
파일이면 ffmpeg, 유튜브면 손자리 크롬 탭의 canvas.

★ 2026-11-02: opencv 를 뺐다 — 스토어 판 기본 부품이 아니다(선택 부품 vision). 확대 찾기(화면 흐름)와 경계선(Sobel)을
  numpy 로 다시 짰다. 같은 시험 영상 6개로 옛(opencv) · 새를 대 봤다 — 결과는 설계서 7절 기록.

    python -m alture_jarvis.video_read.scan 영상.mp4 [--truth truth.json]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

W, H, FPS = 192, 108, 8


def frame_size(vertical: bool) -> tuple[int, int]:
    """(가로, 세로). 세로 영상을 가로 크기로 눌러 담으면 자막 글자가 너무 작아져 바뀜을 못 셌다(쇼츠 6번)."""
    return (H, W) if vertical else (W, H)


def frames_from_file(path: str) -> np.ndarray:
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", path], capture_output=True, text=True, check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().split(",")
    fw, fh = frame_size(int(probe[1]) > int(probe[0]))
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-vf", f"fps={FPS},scale={fw}:{fh}",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return np.frombuffer(out, np.uint8).reshape(-1, fh, fw)


def mad(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16))[4:-4, 4:-4].mean())


def blend_residual(a, mid, b) -> float:
    """mid 가 a 와 b 를 섞은 화면이면 남는 차이가 작다(겹쳐 넘기기). 섞음 비율은 최소제곱으로."""
    a, mid, b = (x.astype(np.float32).ravel() for x in (a, mid, b))
    d = a - b
    denom = float(d @ d) or 1.0
    alpha = float(np.clip(((mid - b) @ d) / denom, 0, 1))
    return float(np.abs(mid - (alpha * a + (1 - alpha) * b)).mean()), alpha


def _gradient(a: np.ndarray) -> np.ndarray:
    """경계선 세기(Sobel 3x3 과 같은 꼴, numpy)."""
    f = np.pad(a.astype(np.float32), 1, mode="edge")
    gx = (f[:-2, 2:] + 2 * f[1:-1, 2:] + f[2:, 2:]) - (f[:-2, :-2] + 2 * f[1:-1, :-2] + f[2:, :-2])
    gy = (f[2:, :-2] + 2 * f[2:, 1:-1] + f[2:, 2:]) - (f[:-2, :-2] + 2 * f[:-2, 1:-1] + f[:-2, 2:])
    return np.hypot(gx, gy)


def _scale_about_center(a: np.ndarray, s: float) -> np.ndarray:
    """가운데를 축으로 s배 키운 화면(쌍선형, numpy). s>1 이면 확대."""
    h, w = a.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    sy = (ys - (h - 1) / 2) / s + (h - 1) / 2
    sx = (xs - (w - 1) / 2) / s + (w - 1) / 2
    y0 = np.clip(np.floor(sy).astype(np.int32), 0, h - 2)
    x0 = np.clip(np.floor(sx).astype(np.int32), 0, w - 2)
    fy = np.clip(sy - y0, 0, 1)
    fx = np.clip(sx - x0, 0, 1)
    f = a.astype(np.float32)
    top = f[y0, x0] * (1 - fx) + f[y0, x0 + 1] * fx
    bot = f[y0 + 1, x0] * (1 - fx) + f[y0 + 1, x0 + 1] * fx
    return top * (1 - fy) + bot * fy


def _phase_peak(a: np.ndarray, b: np.ndarray, window: np.ndarray) -> float:
    """옆으로 밀림을 빼고 두 화면이 얼마나 겹치나 — 위상 상관 꼭짓점 높이."""
    fa = np.fft.rfft2((a - a.mean()) * window)
    fb = np.fft.rfft2((b - b.mean()) * window)
    cross = fa * np.conj(fb)
    cross /= np.abs(cross) + 1e-6
    return float(np.fft.irfft2(cross, s=a.shape).max())


def zoom_rate(a, b) -> float:
    """두 화면 사이의 확대 비율(1보다 크면 확대).

    앞 화면을 가운데 축으로 여러 배율로 키워 보고, 옆 밀림을 뺀 뒤(위상 상관) 뒤 화면과 가장 잘 겹치는 배율을 고른다.
    옛 판은 opencv 의 촘촘한 화면 흐름에서 바깥으로 퍼지는 몫의 가운데값을 썼다 — 같은 시험 영상으로 옛 · 새를 대 봤다.
    무늬 없는 넓은 면만 있으면(경계선이 적으면) 1.0 — 옛 판의 「경계선 있는 자리만 본다」와 같은 뜻.
    """
    h, w = a.shape
    grad = _gradient(a)
    if int((grad > max(20.0, float(np.percentile(grad, 70)))).sum()) < 50:
        return 1.0
    window = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    bf = b.astype(np.float32)
    best_s, best_p = 1.0, _phase_peak(a.astype(np.float32), bf, window)
    for step, span in ((0.01, 0.06), (0.002, 0.01)):
        center = best_s
        for s in np.arange(center - span, center + span + 1e-9, step):
            if abs(s - 1.0) < 1e-9 or s <= 0.5:
                continue
            p = _phase_peak(_scale_about_center(a, float(s)), bf, window)
            if p > best_p + 1e-4:
                best_s, best_p = float(s), p
    # ★ 배율을 바꿔 겹침이 **확실히** 좋아질 때만 확대로 친다. 시험 영상 6개(holdout)에서 진짜 확대 · 축소는 1.55~3.50배,
    #   화면 속 움직임이 만든 헛것은 1.02~1.25배였다(문턱 없이 헛것 3). 이 문턱은 그 6개를 보고 정했으니 새로 만든 영상으로 다시 쟀다.
    if best_s != 1.0 and best_p < ZOOM_GAIN_MIN * max(_phase_peak(a.astype(np.float32), bf, window), 1e-6):
        return 1.0
    return best_s


ZOOM_GAIN_MIN = 1.35


def scan(frames: np.ndarray, fps: int = FPS) -> dict:
    n = len(frames)
    t = lambda i: round(i / fps, 2)  # noqa: E731
    diffs = [mad(frames[i - 1], frames[i]) for i in range(1, n)]
    cuts, fades = [], []
    # 컷 = 양옆보다 확 튄 한 칸. 겹침 = 높은 값이 여러 칸 이어짐(어두운→밝은 겹침은 한 칸에 40 넘게 나와 「한 칸 40」 규칙이 컷 다섯으로 읽었다 · gen_02).
    def is_cut(i: int) -> bool:
        d = diffs[i]
        left = diffs[i - 1] if i > 0 else 0.0
        right = diffs[i + 1] if i + 1 < len(diffs) else 0.0
        return d >= 25 and d >= 2.5 * max(left, right, 4.0)
    i = 0
    while i < len(diffs):
        if is_cut(i):
            cuts.append(t(i + 1)); i += 1; continue
        if diffs[i] >= 6:
            j = i
            while j < len(diffs) and diffs[j] >= 6 and not is_cut(j):
                j += 1
            if j - i >= 2:  # 여러 칸에 걸쳐 바뀜 → 섞인 화면인지 본다
                a, b = frames[i], frames[min(j, n - 1)]
                mids = [blend_residual(a, frames[k], b) for k in range(i + 1, j)]
                res = float(np.mean([m[0] for m in mids]))
                alphas = [round(m[1], 2) for m in mids]
                monotone = all(x >= y - 0.05 for x, y in zip(alphas, alphas[1:]))
                spread = (max(alphas) - min(alphas)) if alphas else 0
                if res < 8 and monotone and spread >= 0.4 and mad(a, b) >= 25:
                    fades.append({"from": t(i), "to": t(j), "residual": round(res, 1)})
            i = max(j, i + 1); continue
        i += 1
    # 붙어 있는 컷 둘(한 칸 차이)은 하나 — 화면을 읽은 시각이 칸과 어긋나면 한 번의 컷이 두 칸에 나뉜다(브라우저 수집 5.0 · 5.25).
    merged_cuts = []
    for c in cuts:
        if merged_cuts and c - merged_cuts[-1] <= 1.5 / fps:
            continue
        merged_cuts.append(c)
    cuts = merged_cuts
    # 컷에 붙은 짧은 「겹침」은 컷 앞뒤 잔상이다(시험 영상에서 헛것 둘) — 뺀다.
    near = lambda x: any(abs(x - c) <= 1.5 / fps for c in cuts)  # noqa: E731
    fades = [f for f in fades if not (near(f["from"]) or near(f["to"]))]
    # 확대: 반 초 간격 흐름. 컷 · 겹침 구간은 뺀다.
    step = max(1, fps // 2)
    zooms_raw = []
    _blocked: list[bool] = []  # 컷 · 겹침에 걸쳐 재지 않은 칸
    # 컷 앞뒤 0.5초를 통째로 빼면 짧은 컷이 많은 영상에서 확대 구간이 몽땅 빠졌다(편집 결과물 2초 확대 0) —
    # 그 쌍 사이에 컷이 끼었거나 겹침 안에 걸친 쌍만 뺀다.
    cut_slots_z = [int(round(c * fps)) for c in cuts]
    fade_spans = [(int(f["from"] * fps), int(f["to"] * fps)) for f in fades]
    for k in range(0, n - step, step):
        straddles = any(k < cs <= k + step for cs in cut_slots_z)
        in_fade = any(not (k + step < a or k > b) for a, b in fade_spans)
        if straddles or in_fade:
            zooms_raw.append((t(k), 1.0)); _blocked.append(True); continue
        zooms_raw.append((t(k), zoom_rate(frames[k], frames[k + step]))); _blocked.append(False)
    # ★ 2026-11-02: numpy 판 배율 찾기는 진짜 축소 한가운데 반 초 한 칸을 반대 방향(1.03 · 1.06)으로 읽어 구간을 둘로 끊었다
    #   (처음 보는 시험 영상 gen_00 · gen_08). 이웃 세 칸의 가운데값으로 한 칸짜리 튐을 누른다 — 컷 · 겹침에 걸친 칸(1.0)은 그대로 둔다.
    vals = [z for _, z in zooms_raw]
    smooth = []
    for k, z in enumerate(vals):
        if z == 1.0 and k < len(zooms_raw) and zooms_raw[k][1] == 1.0 and _blocked[k]:
            smooth.append(1.0)
            continue
        window = [v for j, v in enumerate(vals[max(0, k - 1):k + 2], start=max(0, k - 1)) if not _blocked[j]]
        smooth.append(float(np.median(window)) if window else z)
    zooms_raw = [(tk, z) for (tk, _), z in zip(zooms_raw, smooth)]
    zooms, run = [], []
    for tk, z in zooms_raw + [(None, 1.0)]:
        if z >= 1.006 or z <= 0.994:
            if run and (z > 1) != (run[-1][1] > 1):
                run = [] if len(run) < 2 else (zooms.append(_zoom_span(run, step, fps)) or [])
            run.append((tk, z))
        else:
            if len(run) >= 2:
                zooms.append(_zoom_span(run, step, fps))
            run = []
    # 자막 박자: 미리 정한 위 · 가운데 · 아래 띠는 사람 손 움직임과 섞여 자막 바뀜이 묻혔다(쇼츠 38초에 8번).
    # 가는 가로 줄을 훑어 「한 칸에 튀는 바뀜」이 가장 많은 줄을 자막 자리로 삼는다. 움직임은 부드럽게 오르내리고 글자는 튄다.
    h = frames.shape[1]
    strip, stepy = max(6, h // 12), max(3, h // 24)
    cut_slots = {int(round(c * fps)) for c in cuts}
    fr16 = frames.astype(np.int16)
    candidates = []
    for y0 in range(0, h - strip + 1, stepy):
        series = np.abs(np.diff(fr16[:, y0:y0 + strip], axis=0)).mean(axis=(1, 2))
        ev = []
        for k in range(len(series)):
            if any(abs((k + 1) - cs) <= 1 for cs in cut_slots) or diffs[k] >= 25:
                continue
            lo, hi = max(0, k - 4), min(len(series), k + 5)
            local = np.median(np.concatenate([series[lo:k], series[k + 1:hi]])) if hi - lo > 1 else 0.0
            if series[k] >= 12 and series[k] >= 3.0 * max(local, 2.0):
                if not ev or t(k + 1) - ev[-1] > 2.5 / fps:
                    ev.append(t(k + 1))
        candidates.append((len(ev), y0, ev))
    candidates.sort(key=lambda c: -c[0])
    text_rows = []
    for count, y0, ev in candidates:
        if count < 3 or any(abs(y0 - r["y"]) < strip * 2 for r in text_rows):
            continue
        text_rows.append({"y": y0, "where": round((y0 + strip / 2) / h, 2), "beats": ev})
        if len(text_rows) == 2:
            break
    band_events = {f"{int(r['where'] * 100)}% 높이": r["beats"] for r in text_rows}
    shots = [0.0] + cuts + [t(n)]
    lengths = [round(b - a, 2) for a, b in zip(shots, shots[1:])]
    return {"duration": t(n), "cuts": cuts, "fades": fades, "zooms": zooms, "shot_lengths": lengths, "band_events": band_events,
            "zoom_samples": [(a, round(b, 4)) for a, b in zooms_raw]}


def _zoom_span(run, step, fps):
    rate = float(np.prod([z for _, z in run]))
    return {"from": run[0][0], "to": round(run[-1][0] + step / fps, 2), "kind": "확대" if rate > 1 else "축소",
            "total": round(rate, 3)}


def grade(found: dict, truth: dict, tol: float = 0.3) -> dict:
    hit = lambda xs, x: any(abs(x - y) <= tol for y in xs)  # noqa: E731
    cut_hit = sum(hit(found["cuts"], c) for c in truth["hard_cuts"])
    cut_false = sum(not hit(truth["hard_cuts"], c) for c in found["cuts"])
    ov = lambda a, b: min(a[1], b[1]) - max(a[0], b[0]) > 0  # noqa: E731
    fade_hit = sum(any(ov((f["from"], f["to"]), s) for f in found["fades"]) for s in truth["dissolve"])
    fade_false = sum(not any(ov((f["from"], f["to"]), s) for s in truth["dissolve"]) for f in found["fades"])
    zin, zout = truth.get("zoom", []), truth.get("zoom_out", [])
    zoom_hit = sum(any(ov((z["from"], z["to"]), s) and z["kind"] == "확대" for z in found["zooms"]) for s in zin)
    zoom_hit += sum(any(ov((z["from"], z["to"]), s) and z["kind"] == "축소" for z in found["zooms"]) for s in zout)
    zoom_false = sum(not any(ov((z["from"], z["to"]), s) for s in (zin if z["kind"] == "확대" else zout)) for z in found["zooms"])
    return {"컷": f"{cut_hit}/{len(truth['hard_cuts'])} · 헛것 {cut_false}",
            "겹침": f"{fade_hit}/{len(truth['dissolve'])} · 헛것 {fade_false}",
            "확대축소": f"{zoom_hit}/{len(zin) + len(zout)} · 헛것 {zoom_false}",
            "_n": [cut_hit, len(truth["hard_cuts"]), cut_false, len(found["cuts"]), fade_hit, len(truth["dissolve"]), fade_false,
                   zoom_hit, len(zin) + len(zout), zoom_false]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    path = sys.argv[1]
    res = scan(frames_from_file(path))
    out = {k: v for k, v in res.items() if k != "zoom_samples"}
    if "--truth" in sys.argv:
        truth = json.loads(Path(sys.argv[sys.argv.index("--truth") + 1]).read_text(encoding="utf-8"))
        out["채점"] = grade(res, truth)
    if "--samples" in sys.argv:
        out["zoom_samples"] = res["zoom_samples"]
    print(json.dumps(out, ensure_ascii=False))
