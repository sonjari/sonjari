"""조용히 띄운 크롬이 **페이지 이동에 답을 안 하는가** — 제품 코드 그대로 A/B (2026-09-16 밤).

이어받기 5·6·7판이 사람인 검색 결과에서 `busy_stuck` 으로 멈췄다. 7판에서 멈춘 순간 스택을 떠 보니
파이썬은 크롬 응답을 기다리고 있었다(`browser_open`, 붙어 쓰는 크롬). 오늘 크롬에 닿는 변경은
「사람이 지켜보는 중이면 **최소화·비활성으로 띄우고, 뜨면 바로 내린다**」뿐이다.

    A (quiet)  : 운영 기본값 — browser_allow_foreground=False, browser_sink_windows=True
    B (loud)   : browser_allow_foreground=True, browser_sink_windows=False

같은 순서(사람인 검색 → 상세 1·2·3 열기 → 본문 읽기)를 판마다 새 프로필로 돌리고 걸음별 시간을 적는다.
사용자 프로필은 건드리지 않는다(임시 프로필 · 다른 CDP 포트).

    python ab_quiet_start_stall.py quiet 3
    python ab_quiet_start_stall.py loud 3
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, r"C:\RoboMetaFit\tools\alture-jarvis\src")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from alture_jarvis.browser import BrowserWorker  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402
from alture_jarvis.user_presence import UserPresence  # noqa: E402

SEARCH = "https://www.saramin.co.kr/zf_user/search/recruit?searchword=%EC%97%AC%EC%88%98%20%ED%9A%8C%EA%B3%84"
STEP_LIMIT_SEC = 60
POLL = "--poll" in sys.argv


def one_round(mode: str, port: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix=f"ab-{mode}-"))
    config = JarvisConfig(
        runtime_root=root, data_dir=root / "data", yield_to_user_enabled=True, browser_headless=False,
        browser_attach_mode="auto", browser_profile_dir=root / "profile", browser_cdp_port=port,
        browser_task_timeout_sec=STEP_LIMIT_SEC,
        browser_allow_foreground=(mode == "loud"), browser_sink_windows=(mode == "quiet"),
    )
    worker = BrowserWorker(config)
    worker.presence = UserPresence(config, idle=lambda: 9999.0)  # 지켜보는 사람
    steps: list[dict] = []
    # 작업 화면이 열려 있으면 「온텔릭의 컴퓨터」가 1.5초마다 실시간 화면을 당겨 간다(e2e 조건).
    import threading

    stop = threading.Event()
    frames = {"ok": 0, "empty": 0, "slow": 0}

    def poll() -> None:
        while not stop.is_set():
            started = time.time()
            frame = worker.live_frame()
            frames["ok" if frame.get("jpeg") else "empty"] += 1
            if not frame.get("jpeg"):
                reasons = frames.setdefault("reasons", {})
                key = str(frame.get("reason") or "?")[:60]
                reasons[key] = reasons.get(key, 0) + 1
            if time.time() - started > 3:
                frames["slow"] += 1
            time.sleep(1.5)

    if POLL:
        threading.Thread(target=poll, daemon=True).start()

    def run(name: str, args: dict) -> bool:
        started = time.time()
        try:
            worker.execute_trusted(name, args)
            steps.append({"tool": name, "sec": round(time.time() - started, 1), "ok": True})
            return True
        except Exception as exc:  # noqa: BLE001
            steps.append({"tool": name, "sec": round(time.time() - started, 1), "ok": False,
                          "error": str(exc)[:90]})
            return False

    run("browser_open", {"url": SEARCH})
    for rank in (1, 2, 3):
        if run("browser_open_result", {"rank": rank}):
            run("browser_extract", {})
            run("browser_back", {})
    stop.set()
    out = {"mode": mode, "poll": POLL, "frames": frames, "connect_mode": getattr(worker, "_connect_mode", "?"),
           "ok": sum(s["ok"] for s in steps), "total": len(steps),
           "stalled": [s for s in steps if not s["ok"]][:3],
           "slowest_sec": max((s["sec"] for s in steps), default=0), "steps": steps}
    try:
        worker.stop()
    except Exception:  # noqa: BLE001
        pass
    return out


if __name__ == "__main__":
    mode = sys.argv[1]
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    for index in range(rounds):
        result = one_round(mode, 9360 + index)
        print(json.dumps({k: result[k] for k in ("mode", "poll", "frames", "connect_mode", "ok", "total", "slowest_sec", "stalled")},
                         ensure_ascii=False), flush=True)
