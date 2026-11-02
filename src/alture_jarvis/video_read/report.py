# -*- coding: utf-8 -*-
"""영상 읽기 결과 만들기 — 볼 구간 고르기 · 구간별 분석 합치기 · 대표 장면 고르기 · 사진 한 장 · 표 (2026-11-02).

11-01 MVP(`generated_reports/video_pack_mvp_1101/code/vidscope.py`)에서 옮겼다. 모델을 쓰지 않는다 — 전부 정해진 코드.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .scan import FPS, scan

THUMB_W, THUMB_H = 480, 270
RULER_NOTE = ("눈금(11-02 · 정답 아는 시험 영상 26개): 컷 66/69 · 헛컷 0 · 겹침 22/33 · 헛것 0 · 확대·축소 58/58 · 헛것 0 — "
              "「찾았다」는 믿고, 「없다」는 「못 찾았을 수 있다」(어두운 비슷한 화면 사이 컷 · 겹침 셋 중 하나를 놓친다).")


def heatmap_from_html(html: str) -> list[tuple[float, float]]:
    pts = re.findall(r'"startMillis":"(\d+)","durationMillis":"(\d+)","intensityScoreNormalized":([\d.e-]+)', html)
    seen, out = set(), []
    for s, _d, v in pts:
        if s in seen:
            continue
        seen.add(s)
        out.append((int(s) / 1000, round(float(v), 3)))
    return sorted(out)


def choose_windows(dur: float, heat: list[tuple[float, float]], full_under: float = 90.0) -> list[list[float]]:
    """긴 영상은 나눠 본다: 앞 60초(훅) · 다시 본 구간 높은 곳 3군데 ±15초 · 나머지 고르게 20초 3군데. 겹치면 합친다."""
    if dur <= full_under:
        return [[0.0, round(dur, 2)]]
    wins = [[0.0, 60.0]]
    body = sorted([h for h in heat if h[0] > 60.0], key=lambda x: -x[1])
    for t, _v in body[:3]:
        wins.append([max(0.0, t - 15.0), min(dur, t + 15.0)])
    for k in range(3):
        mid = 60.0 + (dur - 60.0) * (k + 0.5) / 3
        wins.append([max(0.0, mid - 10.0), min(dur, mid + 10.0)])
    wins.sort()
    merged = [wins[0]]
    for a, b in wins[1:]:
        if a <= merged[-1][1] + 2.0:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [[round(a, 2), round(b, 2)] for a, b in merged]


def scan_segments(segments: list[tuple[float, np.ndarray]], dur: float) -> dict:
    """구간마다 따로 재고 시각을 옮겨 합친다. 컷 길이는 양끝이 다 보인 것만(구간 가장자리 조각은 잘린 길이라 뺀다)."""
    out: dict = {"cuts": [], "fades": [], "zooms": [], "shot_lengths": [], "band_events": {}}
    for off, fr in segments:
        r = scan(fr)
        out["cuts"] += [round(c + off, 2) for c in r["cuts"]]
        out["fades"] += [{**f, "from": round(f["from"] + off, 2), "to": round(f["to"] + off, 2)} for f in r["fades"]]
        out["zooms"] += [{**z, "from": round(z["from"] + off, 2), "to": round(z["to"] + off, 2)} for z in r["zooms"]]
        inner = r["shot_lengths"]
        keep_first = off <= 0.01
        keep_last = off + len(fr) / FPS >= dur - 0.2
        out["shot_lengths"] += inner[(0 if keep_first else 1):(len(inner) if keep_last else len(inner) - 1)]
        for k, v in r.get("band_events", {}).items():
            out["band_events"].setdefault(k, []).extend(round(x + off, 2) for x in v)
    return out


def pick_moments(res: dict, heat: list[tuple[float, float]], dur: float, limit: int = 12) -> list[tuple[float, str]]:
    """사진으로 보낼 순간을 프로그램이 고른다(모델 안 씀)."""
    picks: list[tuple[float, str]] = [(0.3, "시작"), (min(2.0, dur * 0.5), "2초")]
    if heat:
        body = [h for h in heat if h[0] > 3.0]  # 첫 몇 초는 늘 높다
        for t, v in sorted(body, key=lambda x: -x[1])[:4]:
            picks.append((t + 0.5, f"다시 봄 {v:.2f}"))
    for f in res["fades"]:
        picks.append(((f["from"] + f["to"]) / 2, "겹침"))
    for z in res["zooms"]:
        picks.append(((z["from"] + z["to"]) / 2, z["kind"]))
    shots = [0.0] + res["cuts"] + [dur]
    mids = [((a + b) / 2, "컷 뒤") for a, b in zip(shots, shots[1:]) if b - a > 0.3]
    room = max(0, limit - len(picks))
    if mids and room:
        step = max(1, len(mids) // room)
        picks += mids[::step][:room]
    caps = res.get("band_events", {})
    busiest = max(caps, key=lambda k: len(caps[k])) if caps else None
    if busiest and caps[busiest]:
        for tt in caps[busiest][:: max(1, len(caps[busiest]) // 3)][:3]:
            picks.append((tt + 0.2, f"{busiest} 글자 바뀜"))
    while len(picks) < 8:  # 사건이 적은 영상(한 번에 찍은 쇼츠)도 고르게 8장은 본다
        k = len(picks)
        picks.append((dur * (k + 0.5) / 9, "고르게"))
    picks = sorted({round(t, 1): (round(t, 1), lab) for t, lab in picks if 0 <= t < dur}.values())
    merged: list[tuple[float, str]] = []
    for t, lab in picks:  # 0.6초 안에 겹친 것은 하나로
        if merged and t - merged[-1][0] < 0.6:
            merged[-1] = (merged[-1][0], merged[-1][1] + " · " + lab)
        else:
            merged.append((t, lab))
    return merged[:limit]


def contact_sheet(items: list[tuple[Path, str]], out: Path, cols: int = 4) -> None:
    """대표 장면을 한 장으로. 세로 영상이면 칸을 세로로 · 한 줄에 6칸."""
    first = Image.open(items[0][0]) if items else None
    vertical = bool(first and first.height > first.width)
    cell_w, cell_h = (220, 392) if vertical else (THUMB_W, THUMB_H)
    cols = 6 if vertical else cols
    rows = max(1, (len(items) + cols - 1) // cols)
    pad = 6
    sheet = Image.new("RGB", (cols * cell_w + (cols + 1) * pad, rows * cell_h + (rows + 1) * pad), (18, 18, 18))
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 18 if vertical else 22)
    except OSError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(sheet)
    for i, (path, label) in enumerate(items):
        x, y = pad + (i % cols) * (cell_w + pad), pad + (i // cols) * (cell_h + pad)
        im = Image.open(path).convert("RGB")
        im.thumbnail((cell_w, cell_h))
        sheet.paste(im, (x + (cell_w - im.width) // 2, y + (cell_h - im.height) // 2))
        box = draw.textbbox((x + 8, y + 4), label, font=font)
        draw.rectangle([box[0] - 6, box[1] - 4, box[2] + 6, box[3] + 4], fill=(0, 0, 0))
        draw.text((x + 8, y + 4), label, font=font, fill=(255, 255, 255))
    sheet.save(out)


def _gap(beats: list[float]) -> float | None:
    gaps = [b - a for a, b in zip(beats, beats[1:]) if b - a < 20.0]
    return round(float(np.mean(gaps)), 2) if gaps else None


def finish(cap: dict[str, Any], workdir: Path, thumb: Callable[[float, Path], None]) -> dict[str, Any]:
    """화면 묶음 → report.json · table.md · sheet.png · thumbs/. `thumb(t, 경로)` 는 그 시각의 컬러 사진을 찍는다."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "thumbs").mkdir(exist_ok=True)
    dur = float(cap["duration"])
    segments = cap["segments"]
    np.savez_compressed(workdir / "frames.npz", **{f"seg_{off:.2f}": fr for off, fr in segments})  # 다시 잴 때 영상을 또 틀지 않게
    seen = sum(len(fr) for _o, fr in segments) / FPS
    res = scan_segments(segments, dur)
    moments = pick_moments(res, cap.get("heatmap") or [], dur)
    items = []
    for k, (t, lab) in enumerate(moments):
        p = workdir / "thumbs" / f"{k:02d}_{t:.1f}.jpg"
        try:
            thumb(t, p)
        except Exception:  # noqa: BLE001 — 사진 한 장 실패로 결과를 버리지 않는다
            continue
        if p.is_file():
            items.append((p, f"{t:.1f}초 · {lab}"))
    if items:
        contact_sheet(items, workdir / "sheet.png")
    lens = res["shot_lengths"]
    missing = int(cap.get("missing_slots") or 0)
    report = {
        "source": cap.get("title") or "", "url": cap.get("url") or "", "duration": round(dur, 2), "cuts": res["cuts"],
        "shot_lengths": lens,
        "avg_shot": round(float(np.mean(lens)), 2) if lens else None,
        "median_shot": round(float(np.median(lens)), 2) if lens else None,
        "cuts_in_first_3s": sum(1 for c in res["cuts"] if c <= 3.0),
        "windows": cap.get("windows") or [[0.0, round(dur, 2)]], "failed_windows": cap.get("failed_windows") or [],
        "seen_seconds": round(seen, 1),
        "cuts_per_min_seen": round(len(res["cuts"]) * 60 / max(1.0, seen), 1), "fades": res["fades"], "zooms": res["zooms"],
        "caption_beats": {k: len(v) for k, v in res.get("band_events", {}).items()},
        "caption_beat_avg_gap": {k: _gap(v) for k, v in res.get("band_events", {}).items()},
        "heatmap_peaks": [h for h in sorted(cap.get("heatmap") or [], key=lambda x: -x[1]) if h[0] > 3.0][:5],
        "heatmap_present": bool(cap.get("heatmap")), "missing_slots": missing, "ad_waits": int(cap.get("ad_waits") or 0),
        # 빈 칸을 앞 화면으로 채우면 가짜 컷이 생긴다(11-01 부산항: 빈 칸 1,236 → 2.0초 · 0.38초가 기계처럼 반복) — 5% 넘으면 믿지 않는다.
        "missing_ratio": round(missing / max(1, seen * FPS), 3),
        "reliable": missing / max(1, seen * FPS) <= 0.05,
        "moments": [{"t": t, "label": lab} for t, lab in moments],
        "ruler_note": RULER_NOTE,
        "errors": cap.get("errors") or [],
    }
    (workdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (workdir / "table.md").write_text(table_md(report), encoding="utf-8")
    return report


def table_md(r: dict) -> str:
    lines = [f"# {r['source']}", ""] + ([] if r.get("reliable", True) else [
             f"> ⚠ 믿을 수 없음: 못 읽은 칸이 {r['missing_ratio']:.0%} — 아래 컷 숫자는 쓰지 말 것(다시 잴 것).", ""]) + [
             f"- 길이 {r['duration']}초 · 컷 {len(r['cuts'])}개 · 컷 길이 평균 {r['avg_shot']}초 · 가운데값 {r['median_shot']}초 · 첫 3초 컷 {r['cuts_in_first_3s']}개",
             f"- 겹침 {len(r['fades'])}개 · 확대/축소 {len(r['zooms'])}개 · 다시 본 구간 그래프 {'있음' if r['heatmap_present'] else '없음'}",
             "- 자막 박자(글자가 튀는 줄): " + (" · ".join(f"{k} {n}번(평균 {r['caption_beat_avg_gap'][k]}초 간격)" for k, n in r["caption_beats"].items()) or "못 찾음"),
             f"- 본 구간 {r['seen_seconds']}초 / 전체 {r['duration']}초: " + ", ".join(f"{a:.0f}~{b:.0f}초" for a, b in r["windows"]),
             f"- 본 구간 안 컷 {r['cuts_per_min_seen']}개/분 · 빈 칸(못 읽은 1/8초) {r['missing_slots']}개", "",
             "컷 길이(양끝이 다 보인 것만, 초): " + ", ".join(f"{x:.2f}" for x in r["shot_lengths"][:80])]
    if r["fades"]:
        lines += ["", "겹침: " + ", ".join(f"{f['from']}~{f['to']}초" for f in r["fades"])]
    if r["zooms"]:
        lines += ["", "확대/축소: " + ", ".join(f"{z['from']}~{z['to']}초 {z['kind']} ×{z['total']}" for z in r["zooms"])]
    if r.get("errors"):
        lines += ["", "못 본 곳 · 문제: " + " / ".join(r["errors"][:6])]
    if r["heatmap_peaks"]:
        lines += ["", "다시 본 구간 높은 곳: " + ", ".join(f"{t:.0f}초({v})" for t, v in r["heatmap_peaks"])]
    lines += ["", r.get("ruler_note") or RULER_NOTE]
    return "\n".join(lines) + "\n"
