"""문서가 아직 없는 하위 프레임에는 손대지 않는다 (2026-09-23 스토어 촬영에서 발견).

다나와 목록의 광고 iframe 네 개가 **새 크롬 프로필**에서 주소가 빈 문자열(`''`)인 채 광고 서버 이동이 끝나지 않았다.
그 프레임에 `frame.evaluate` 를 하면 Playwright 가 실행 환경을 끝없이 기다린다 — browser_extract 가 매번 180초
시간 초과(추적: 주소 빈 프레임 하나에서 125초·424초). 평소 프로필은 광고가 달라 2.2초였다. `_frames_of` 가 그런
프레임을 빼자 같은 페이지가 약 2초·11,152자.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Element:
    def __init__(self, src: str | None) -> None:
        self.src = src

    def get_attribute(self, name: str) -> str | None:
        return self.src if name == "src" else None


class _Frame:
    def __init__(self, url, *, detached: bool = False, src: str | None = None) -> None:
        self.url = url
        self._detached = detached
        self._src = src

    def is_detached(self) -> bool:
        return self._detached

    def frame_element(self) -> _Element:
        return _Element(self._src)


class _Page:
    def __init__(self, frames: list[_Frame]) -> None:
        self.frames = frames
        self.main_frame = frames[0]


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d"))


def test_a_frame_whose_navigation_never_committed_is_skipped(tmp_path: Path) -> None:
    main = _Frame("https://prod.danawa.com/list/?cate=11310719")
    ad = _Frame("https://ad.danawa.com/RealMedia/ads/adstream_sx.ads/www.danawa.com/cate_CPU@x35")
    pending = [_Frame("", src="//ad.danawa.com/RealMedia/ads/adstream_sx.ads/www.danawa.com/cate_MUS@x2" + str(i))
               for i in range(4)]
    kept = _worker(tmp_path)._frames_of(_Page([main, ad, *pending]))
    assert kept == [main, ad], "주소 빈 프레임에 evaluate 하면 끝없이 멈춘다"


def test_a_detached_frame_is_skipped(tmp_path: Path) -> None:
    main = _Frame("https://example.com/")
    gone = _Frame("https://example.com/ad", detached=True)
    assert _worker(tmp_path)._frames_of(_Page([main, gone])) == [main]


def test_a_settled_about_blank_frame_and_the_main_frame_stay(tmp_path: Path) -> None:
    """★ 좋은 표본 — `about:blank` 로 자리 잡은 프레임(편집기 등)은 읽을 수 있다. 빈 문자열만 뺀다.
    주 프레임은 무엇이든 남는다."""
    main = _Frame("about:blank")
    editor = _Frame("about:blank")
    blog = _Frame("https://blog.naver.com/PostView.naver?blogId=x")
    kept = _worker(tmp_path)._frames_of(_Page([main, editor, blog]))
    assert kept == [main, editor, blog]


def test_fake_frames_without_url_are_kept(tmp_path: Path) -> None:
    """오프라인 시험이 넘기는 대역 프레임(url 속성 없음)은 예전처럼 전부 남는다."""

    class _Bare:
        pass

    frames = [_Bare(), _Bare()]

    class _P:
        pass

    page = _P()
    page.frames = frames  # type: ignore[attr-defined]
    assert _worker(tmp_path)._frames_of(page) == frames


def test_an_srcless_iframe_filled_by_script_is_kept(tmp_path: Path) -> None:
    """★ 좋은 표본 — 편집기·위젯처럼 `src` 없이 스크립트가 채운 iframe 은 주소가 비어도 읽을 수 있다.
    처음 고침이 이것까지 빼서 iframe 안을 누르고 읽는 시험 53개가 깨졌다."""
    main = _Frame("https://blog.example.com/write")
    editor = _Frame("", src=None)
    about = _Frame("", src="about:blank")
    assert _worker(tmp_path)._frames_of(_Page([main, editor, about])) == [main, editor, about]
