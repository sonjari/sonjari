"""영상 읽기 수집 (2026-11-02) — 이미 열린 탭에서 영상을 틀며 화면을 모아 표 · 사진 한 장을 만든다(진짜 크로미움).

ffmpeg 로 그 자리에서 정답을 아는 영상(색 두 장면 사이 컷 하나)을 만들어 가짜 영상 페이지에 넣는다.
이 PC 의 정답 아는 생성 영상 6개를 진짜 크롬으로 잰 결과(컷 19/19 · 겹침 3/6 · 확대 15/16 · 헛것 0)는 설계서 7-1.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from alture_jarvis.video_read.capture import capture_page  # noqa: E402
from alture_jarvis.video_read.report import choose_windows, pick_moments  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")


def _clip(tmp_path: Path) -> Path:
    out = tmp_path / "cut.webm"
    # 3초 무늬 A → 3초 무늬 B(색이 다른 시험 화면) — 3.0초에 딱 끊는 컷 하나.
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=3",
                    "-f", "lavfi", "-i", "smptebars=size=320x180:rate=24:duration=3",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-c:v", "libvpx-vp9", "-b:v", "1M",
                    str(out)], check=True)
    return out


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield launched
        launched.close()


def test_a_page_video_becomes_a_table_and_one_picture(browser, tmp_path: Path) -> None:
    body = _clip(tmp_path).read_bytes()
    html = ("<html><head><title>시험 영상 - YouTube</title></head><body><div class='html5-video-player'>"
            "<video src='/v.webm' muted playsinline></video></div></body></html>")
    page = browser.new_page()

    def serve(route) -> None:
        if route.request.url.endswith("/v.webm"):
            route.fulfill(status=200, body=body, headers={"Content-Type": "video/webm", "Accept-Ranges": "bytes"})
        else:
            route.fulfill(status=200, body=html, headers={"Content-Type": "text/html; charset=utf-8"})

    page.route("**/*", serve)
    seen: list[dict] = []
    out = tmp_path / "out"
    report = capture_page(page, "https://video.test/watch?v=x", out, rate=2.0, on_progress=seen.append)
    page.close()
    assert report["source"] == "시험 영상"          # 「 - YouTube」를 뗀 제목
    assert any(abs(c - 3.0) <= 0.3 for c in report["cuts"]), report["cuts"]
    assert report["missing_slots"] == 0 and report["reliable"]
    assert (out / "sheet.png").is_file() and (out / "table.md").is_file()
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["ruler_note"]
    assert any(p["phase"] == "playing" for p in seen)  # 진행 표시가 재생 중에 들어왔다


def test_long_videos_are_watched_in_windows() -> None:
    assert choose_windows(60.0, []) == [[0.0, 60.0]]                     # 90초 이하는 통째로
    wins = choose_windows(600.0, [(300.0, 1.0), (450.0, 0.9)])
    assert wins[0][0] == 0.0 and sum(b - a for a, b in wins) < 300    # 긴 영상은 앞 60초 + 몇 군데만
    assert any(a <= 300.0 <= b for a, b in wins)                        # 다시 본 구간 높은 곳은 꼭 본다


def test_moments_pick_at_least_eight_and_at_most_twelve() -> None:
    res = {"cuts": [float(k) for k in range(1, 30)], "fades": [], "zooms": [], "band_events": {}}
    picks = pick_moments(res, [], 30.0)
    assert 8 <= len(picks) <= 12
    assert pick_moments({"cuts": [], "fades": [], "zooms": [], "band_events": {}}, [], 20.0)  # 사건 없는 영상도 고르게
