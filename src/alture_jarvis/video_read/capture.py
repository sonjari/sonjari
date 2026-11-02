# -*- coding: utf-8 -*-
"""영상 읽기 수집 — **이미 열린 브라우저 탭**에서 영상을 소리 끄고 빠르게 틀며 작은 흑백 화면만 숫자로 모은다 (2026-11-02).

11-01 MVP 는 빈 프로필 크로미움을 따로 띄웠다 → 유튜브 `player_error` · 화면 1,236칸 빔(부산항, n=1).
손자리에서는 사용자 크롬(로그인 있음)의 새 탭을 받아 돈다. 브라우저를 띄우거나 닫는 일은 부르는 쪽(BrowserWorker)이 한다.

영상 · 소리를 **내려받지 않는다**(유튜브 약관) — 남는 것은 작은 흑백 화면 숫자와 대표 장면 사진 몇 장뿐.
수집은 페이지 안에서 출발만 시키고 1초마다 진행을 물어본다 — 진행 표시(「영상 보는 중 1:20 / 3:05」)가 화면에 보이게.
"""
from __future__ import annotations

import base64
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .report import THUMB_H, THUMB_W, choose_windows, finish, heatmap_from_html
from .scan import FPS, frame_size, frames_from_file

#: 페이지 안 수집기 — 출발만 시키고 바로 돌아온다. 진행은 `window.__vs` 에 쌓인다.
START_JS = r"""
({FPS, rate, sizes, windows}) => {
  const v = document.querySelector('video');
  if (!v) return {error: 'no_video'};
  const player = document.querySelector('.html5-video-player');
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const adShowing = () => !!(player && player.classList.contains('ad-showing'));
  window.__vs = {state: 'starting', frames: null, dur: 0, slots: 0, adWaits: 0, W: 0, H: 0, at: 0, error: null};
  (async () => {
    try {
      await new Promise(r => v.readyState >= 1 ? r() : v.addEventListener('loadedmetadata', r, {once: true}));
      const vertical = v.videoHeight > v.videoWidth;
      const [W, H] = vertical ? sizes.vertical : sizes.horizontal;
      v.muted = true;
      // 광고: 끝나길 기다리고, 건너뛰기 단추가 있으면 누른다. 광고 화면은 모으지 않는다.
      window.__vs.state = 'ad';
      for (let k = 0; k < 240 && adShowing(); k++) {
        const skip = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button-modern, .ytp-ad-skip-button');
        if (skip) skip.click();
        await sleep(500);
      }
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const g = c.getContext('2d', {willReadFrequently: true});
      const dur = v.duration;
      const slots = Math.floor(dur * FPS);
      Object.assign(window.__vs, {frames: new Array(slots).fill(null), dur, slots, W, H, state: 'playing'});
      v.playbackRate = rate;
      const take = (mediaTime) => {
        if (adShowing()) { window.__vs.adWaits++; return; }
        const t = (mediaTime ?? v.currentTime); const s = Math.round(t * FPS);
        window.__vs.at = t;
        if (s < 0 || s >= slots || window.__vs.frames[s]) return;
        g.drawImage(v, 0, 0, W, H);
        const d = g.getImageData(0, 0, W, H).data; const out = new Uint8Array(W * H);
        for (let i = 0; i < W * H; i++) out[i] = (d[i*4] * 0.299 + d[i*4+1] * 0.587 + d[i*4+2] * 0.114) | 0;
        window.__vs.frames[s] = out;
      };
      for (const [a, b] of windows) {
        if (window.__vs.error) break;
        await new Promise(r => { v.addEventListener('seeked', r, {once: true}); v.currentTime = a; setTimeout(r, 6000); });
        await v.play().catch(() => {});
        await new Promise(resolve => {
          let done = false, watch = null;
          const finish = () => { if (!done) { done = true; if (watch) clearInterval(watch); resolve(); } };
          v.addEventListener('ended', finish, {once: true});
          // 「새로고침」 오류 화면 · 15초 멈춤이면 기다리지 않는다(11-01 셋 다 멈춤).
          let lastT = -1, stillSince = Date.now();
          watch = setInterval(() => {
            const err = document.querySelector('.ytp-error, .ytp-error-content');
            if (err && err.offsetParent !== null) { window.__vs.error = 'player_error: ' + (err.innerText || '').slice(0, 120); finish(); return; }
            if (adShowing()) { stillSince = Date.now(); return; }
            if (v.currentTime !== lastT) { lastT = v.currentTime; stillSince = Date.now(); }
            else if (Date.now() - stillSince > 15000) { window.__vs.error = 'stalled at ' + v.currentTime.toFixed(1); finish(); return; }
            // 화면 콜백이 줄어든 탭(뒤에 숨은 탭)에서도 칸이 비지 않게 — 시간표로도 한 장씩 찍는다.
            take(v.currentTime);
            if (v.currentTime >= b - 0.05) finish();
            else if (v.paused) v.play().catch(() => {});
          }, 100);
          const tick = (_now, meta) => {
            if (done) return;
            take(meta ? meta.mediaTime : undefined);
            if ('requestVideoFrameCallback' in v) v.requestVideoFrameCallback(tick); else setTimeout(tick, 30);
          };
          tick();
          setTimeout(finish, ((b - a) / rate + 60) * 1000);
        });
        v.pause();
      }
      window.__vs.state = 'done';
    } catch (e) {
      window.__vs.error = String(e).slice(0, 200); window.__vs.state = 'done';
    }
  })();
  return {started: true};
}
"""

POLL_JS = r"""
() => { const s = window.__vs; if (!s) return null;
  return {state: s.state, at: s.at, dur: s.dur, slots: s.slots, W: s.W, H: s.H, adWaits: s.adWaits, error: s.error,
          filled: s.frames ? s.frames.filter(Boolean).length : 0}; }
"""

PULL_JS = r"""
({from, count, W, H}) => {
  const fr = window.__vs.frames; const out = new Uint8Array(count * W * H); const missing = [];
  let last = null;
  for (let k = 0; k < count; k++) {
    let f = fr[from + k];
    if (!f) { missing.push(from + k); f = last || new Uint8Array(W * H); }
    out.set(f, k * W * H); last = f;
  }
  let s = ''; for (let i = 0; i < out.length; i += 0x8000) s += String.fromCharCode.apply(null, out.subarray(i, i + 0x8000));
  return {b64: btoa(s), missing};
}
"""

THUMB_JS = r"""
async ({t, w, h}) => {
  const v = document.querySelector('video');
  await new Promise(r => { v.addEventListener('seeked', r, {once: true}); v.currentTime = t; setTimeout(r, 4000); });
  await new Promise(r => setTimeout(r, 150));
  const ar = (v.videoWidth || 16) / (v.videoHeight || 9);
  const cw = ar >= 1 ? w : Math.round(h * ar), ch = ar >= 1 ? Math.round(w / ar) : h;
  const c = document.createElement('canvas'); c.width = cw; c.height = ch; c.getContext('2d').drawImage(v, 0, 0, cw, ch);
  return c.toDataURL('image/jpeg', 0.85);
}
"""

DURATION_JS = r"""
() => new Promise(r => {
  const v = document.querySelector('video');
  if (!v) return r(0);
  if (v.readyState >= 1) r(v.duration); else v.addEventListener('loadedmetadata', () => r(v.duration), {once: true});
})
"""

Progress = Callable[[dict[str, Any]], None]
#: 브라우저 동작 하나를 실행해 주는 함수. 손자리에서는 브라우저 일꾼 스레드에 **짧게** 넘긴다 — 영상 보는 2분 내내
#: 일꾼을 붙잡으면 그동안 오는 다른 브라우저 호출이 전부 「앞 동작에 물려 있다」로 거절된다(08-16 설계). 기본은 그냥 부른다.
Runner = Callable[[Callable[[], Any]], Any]


def _direct(function: Callable[[], Any]) -> Any:
    return function()


def _sizes() -> dict[str, list[int]]:
    return {"vertical": list(frame_size(True)), "horizontal": list(frame_size(False))}


def _open_at(page: Any, url: str, t: float | None, run: Runner = _direct) -> None:
    sep = "&" if "?" in url else "?"
    target = url if t is None else f"{url}{sep}t={int(t)}s"
    run(lambda: page.goto(target, wait_until="domcontentloaded", timeout=60000))
    run(lambda: page.wait_for_selector("video", timeout=30000))
    time.sleep(1.5)


def _play_window(page: Any, a: float, b: float, rate: float, total_seen: float, total_want: float,
                 on_progress: Progress | None, run: Runner = _direct) -> dict[str, Any]:
    args = {"FPS": FPS, "rate": rate, "windows": [[a, b]], "sizes": _sizes()}
    run(lambda: page.evaluate(START_JS, args))
    deadline = time.monotonic() + (b - a) / rate + 120
    state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = run(lambda: page.evaluate(POLL_JS)) or {}
        if on_progress:
            at = float(state.get("at") or a)
            on_progress({"phase": state.get("state") or "starting", "at": round(at, 1), "duration": round(float(state.get("dur") or 0), 1),
                         "seen": round(total_seen + max(0.0, min(at, b) - a), 1), "want": round(total_want, 1)})
        if state.get("state") == "done":
            break
        time.sleep(1.0)  # 일꾼을 붙잡지 않고 기다린다
    return state


#: 한 번 읽기의 전체 마감(초). MCP 도구 호출 상한이 300초라 60초를 남긴다(설계서 7-2).
DEADLINE_SEC = 240.0


def capture_page(page: Any, url: str, workdir: Path, *, rate: float = 2.0, limit: float = 600.0,
                 on_progress: Progress | None = None, run: Runner | None = None,
                 deadline_sec: float = DEADLINE_SEC) -> dict[str, Any]:
    """`page` (이미 열린 탭)에서 `url` 을 보고 결과 폴더를 만든다. 반환: report.json 의 내용.

    `run` 을 주면 브라우저 동작마다 그 함수로 넘긴다(손자리 브라우저 일꾼). 기다림은 넘기지 않는다.
    """
    run = run or _direct
    started = time.monotonic()
    left = lambda: deadline_sec - (time.monotonic() - started)  # noqa: E731
    _open_at(page, url, None, run)
    html = run(lambda: page.content())
    title = run(lambda: page.title()).removesuffix(" - YouTube") or url
    dur = float(run(lambda: page.evaluate(DURATION_JS)) or 0)
    if dur <= 0:
        raise RuntimeError("video_not_playable: 페이지에 재생할 수 있는 영상이 없다")
    heat = heatmap_from_html(html)
    windows = choose_windows(min(dur, limit), heat)
    total_want = sum(b - a for a, b in windows)
    segments: list[tuple[float, np.ndarray]] = []
    missing = 0
    failed: list[list[float]] = []
    errors: list[str] = []
    ad_waits = 0
    seen = 0.0
    for k, (a, b) in enumerate(windows):
        if left() < (b - a) / rate + 15:
            # ★ 마감 안에 못 볼 구간은 틀지 않는다 — 300초를 넘기면 결과 전체를 잃는다. 「일부만 봤다」로 남긴다.
            failed.append([a, b])
            errors.append(f"{a:.0f}~{b:.0f}초: 시간 상한({deadline_sec:.0f}초)으로 안 봄")
            continue
        ok = False
        info: dict[str, Any] = {}
        for attempt in range(2):
            if k > 0 or attempt > 0:
                # 건너뛰면 유튜브가 「새로고침」 오류를 낸 일이 있다(11-01) — 구간마다 &t= 주소로 새로 연다.
                _open_at(page, url, a, run)
            info = _play_window(page, a, b, rate, seen, total_want, on_progress, run)
            want = int((b - a) * FPS)
            if not info.get("error") or int(info.get("filled") or 0) >= want * 0.9:
                ok = True
                break
            errors.append(f"{a:.0f}~{b:.0f}초: {str(info.get('error'))[:120]}")
        if not ok or not info.get("W"):
            failed.append([a, b])
            continue
        W, H = int(info["W"]), int(info["H"])
        lo, hi = int(round(a * FPS)), min(int(info["slots"]), int(b * FPS))
        parts = []
        for start in range(lo, hi, 64):
            count = min(64, hi - start)
            pull = {"from": start, "count": count, "W": W, "H": H}
            got = run(lambda: page.evaluate(PULL_JS, pull))
            parts.append(np.frombuffer(base64.b64decode(got["b64"]), np.uint8).reshape(count, H, W))
            missing += len(got["missing"])
        if parts:
            segments.append((lo / FPS, np.concatenate(parts)))
        ad_waits += int(info.get("adWaits") or 0)
        seen += b - a
    if not segments:
        raise RuntimeError("video_capture_failed: 모든 구간 재생 실패 · " + " / ".join(errors)[:300])

    def thumb(t: float, path: Path) -> None:
        if left() < 8:
            raise TimeoutError("시간 상한 — 사진은 여기까지")
        if on_progress:
            on_progress({"phase": "thumbs", "at": round(t, 1), "duration": round(dur, 1), "seen": round(seen, 1), "want": round(total_want, 1)})
        args = {"t": t, "w": THUMB_W, "h": THUMB_H}
        try:
            data = run(lambda: page.evaluate(THUMB_JS, args))
        except Exception:  # noqa: BLE001 — 건너뛰기가 막히면 &t= 로 새로 열어 찍는다
            _open_at(page, url, t, run)
            data = run(lambda: page.evaluate(THUMB_JS, args))
        path.write_bytes(base64.b64decode(str(data).split(",", 1)[1]))

    cap = {"segments": segments, "windows": [w for w in windows if w not in failed], "failed_windows": failed,
           "title": title, "url": url, "duration": dur, "missing_slots": missing, "ad_waits": ad_waits,
           "heatmap": heat, "errors": errors}
    return finish(cap, workdir, thumb)


def capture_file(path: str, workdir: Path) -> dict[str, Any]:
    """이 PC 의 영상 파일 — 같은 눈금으로(우리 결과물 재기)."""
    frames = frames_from_file(path)
    dur = len(frames) / FPS

    def thumb(t: float, out: Path) -> None:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                        "-vf", f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=decrease", str(out)], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    cap = {"segments": [(0.0, frames)], "title": Path(path).stem, "url": "", "duration": dur, "missing_slots": 0,
           "ad_waits": 0, "heatmap": []}
    return finish(cap, workdir, thumb)
