"""영상 팩 도구 `video_read` — 본체 잇기 시험 (2026-11-02 · 설계서 7-2 시험 계획 그대로).

양방향: 해야 할 것(팩 켜면 보임 · 결과 파일 · 탭 정리 · 바쁘면 다시 넘김) / 하면 안 되는 것(팩 꺼지면 안 보임 ·
일꾼을 오래 붙잡음 · 작업 탭 바꿈 · 실패하고 탭 남김 · ffmpeg 없이 파일을 잰 척).
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.packs import PackRegistry
from alture_jarvis.video_tools import VideoTools

PACKS_DIR = Path(__file__).resolve().parents[1] / "packs"


class _Packs:
    def __init__(self, on: bool) -> None:
        self.on = on

    def is_enabled(self, pack_id: str) -> bool:
        return self.on and pack_id == "video"


class _Config:
    def __init__(self, root: Path) -> None:
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"


# ── 단위: 팩 · 입력 ──────────────────────────────────────────────────────

def test_the_video_pack_loads_with_its_tool(tmp_path: Path) -> None:
    registry = PackRegistry(PACKS_DIR, tmp_path / "data")
    listing = {pack["id"]: pack for pack in registry.listing()["packs"]} if hasattr(registry, "listing") else None
    pack = registry.get("video") if hasattr(registry, "get") else None
    found = pack or (listing or {}).get("video")
    assert found, "영상 팩을 못 읽었다"
    tools = getattr(found, "tools", None) or found.get("tools")
    assert list(tools) == ["video_read"]


def test_a_disabled_pack_hides_and_refuses(tmp_path: Path) -> None:
    tools = VideoTools(_Config(tmp_path), browser=None, packs=_Packs(False))
    assert tools.active_ollama_tools == []
    with pytest.raises(PermissionError, match="pack_disabled"):
        tools.video_read({"url": "https://www.youtube.com/watch?v=x"})
    assert [t["function"]["name"] for t in VideoTools(_Config(tmp_path), None, _Packs(True)).active_ollama_tools] == ["video_read"]


@pytest.mark.parametrize("arguments", [{}, {"url": "https://a/b", "path": "C:/x.mp4"}, {"url": "file:///C:/x.mp4"},
                                       {"url": "javascript:alert(1)"}])
def test_bad_input_is_refused(tmp_path: Path, arguments: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        VideoTools(_Config(tmp_path), None, _Packs(True)).video_read(arguments)


def test_a_file_without_ffmpeg_is_refused_plainly(tmp_path: Path, monkeypatch) -> None:
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr("alture_jarvis.video_tools.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg_missing"):
        VideoTools(_Config(tmp_path), None, _Packs(True)).video_read({"path": str(clip)})
    with pytest.raises(FileNotFoundError):
        VideoTools(_Config(tmp_path), None, _Packs(True)).video_read({"path": str(tmp_path / "none.mp4")})


# ── 통합: 진짜 크로미움 + 가짜 일꾼 ─────────────────────────────────────

playwright_api = pytest.importorskip("playwright.sync_api")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")


class _Worker:
    """BrowserWorker 에서 영상 도구가 쓰는 칸만 — 넘긴 동작이 일꾼을 붙잡은 시간을 잰다."""

    def __init__(self, context: Any, *, busy_first: int = 0) -> None:
        self._context = context
        self._our_pages: list[int] = []
        self._page = context.new_page()  # 다른 일이 쓰던 작업 탭
        self.longest = 0.0
        self.calls = 0
        self.busy_left = busy_first

    def _ensure_started(self) -> None:
        return None

    def _submit(self, function: Any, timeout: float | None = None, *, operation: str = "") -> Any:
        if self.busy_left > 0:
            self.busy_left -= 1
            raise RuntimeError("browser_busy_active(browser_internal) — 앞 동작이 아직")
        self.calls += 1
        started = time.monotonic()
        try:
            return function()
        finally:
            self.longest = max(self.longest, time.monotonic() - started)


def _webm(tmp_path: Path) -> bytes:
    out = tmp_path / "cut.webm"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=3",
                    "-f", "lavfi", "-i", "smptebars=size=320x180:rate=24:duration=3",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-c:v", "libvpx-vp9", "-b:v", "1M",
                    str(out)], check=True)
    return out.read_bytes()


@pytest.fixture(scope="module")
def context():
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        ctx = browser.new_context()
        yield ctx
        browser.close()


def _serve(context: Any, body: bytes) -> None:
    video_page = ("<html><head><title>시험 영상 - YouTube</title></head><body><div class='html5-video-player'>"
                  "<video src='/v.webm' muted playsinline></video></div></body></html>")

    def serve(route) -> None:
        url = route.request.url
        if url.endswith("/v.webm"):
            route.fulfill(status=200, body=body, headers={"Content-Type": "video/webm", "Accept-Ranges": "bytes"})
        elif "/novideo" in url:
            route.fulfill(status=200, body="<html><body>영상 없음</body></html>", headers={"Content-Type": "text/html; charset=utf-8"})
        else:
            route.fulfill(status=200, body=video_page, headers={"Content-Type": "text/html; charset=utf-8"})

    context.route("**/*", serve)


@needs_ffmpeg
def test_reading_a_video_keeps_the_worker_free_and_cleans_up(context, tmp_path: Path) -> None:
    _serve(context, _webm(tmp_path))
    worker = _Worker(context, busy_first=2)
    work_tab = worker._page
    tabs_before = len(context.pages)
    result = VideoTools(_Config(tmp_path), worker, _Packs(True)).video_read({"url": "https://video.test/watch?v=x"})
    assert result["ok"] and result["source"] == "시험 영상"
    assert "컷" in result["table"] and result["ruler_note"]
    assert any(f.endswith("sheet.png") for f in result["files"]) and all(Path(f).is_file() for f in result["files"])
    assert Path(result["folder"]).parent == tmp_path / "docs" / "video_read"
    assert len(context.pages) == tabs_before          # 영상 탭은 닫혔다
    assert worker._page is work_tab and not work_tab.is_closed()  # 작업 탭은 그대로
    assert worker.longest < 5.0, f"일꾼을 {worker.longest:.1f}초 붙잡았다 — 짧게 넘겨야 한다"
    assert worker.calls > 5                             # 쪼개 넘겼다(한 번에 통째로가 아니다)


@needs_ffmpeg
def test_a_page_without_video_fails_plainly_and_closes_its_tab(context, tmp_path: Path) -> None:
    _serve(context, _webm(tmp_path))
    worker = _Worker(context)
    tabs_before = len(context.pages)
    with pytest.raises(Exception):
        VideoTools(_Config(tmp_path), worker, _Packs(True)).video_read({"url": "https://video.test/novideo"})
    assert len(context.pages) == tabs_before


@needs_ffmpeg
def test_the_frame_bundle_does_not_pile_up_in_documents(context, tmp_path: Path) -> None:
    _serve(context, _webm(tmp_path))
    result = VideoTools(_Config(tmp_path), _Worker(context), _Packs(True)).video_read({"url": "https://video.test/watch?v=x"})
    assert not (Path(result["folder"]) / "frames.npz").exists()
    assert list((tmp_path / "out" / "video_read_frames").glob("*.npz"))
