"""문전박대 화면을 **알아보고**, 한 번만 다시 해 보고, 그래도 막히면 막혔다고 한다.

2026-08-11 실측. 쿠팡 상품검색이 Akamai 의 `Access Denied` 를 돌려줬는데 자비스에는
이 화면을 알아보는 코드가 없었다 — 봇 검사 문구 목록(`_SEARCH_BLOCK_MARKERS`)은
검색엔진용이라 여기 문구가 하나도 없다. 그래서 차단 화면을 **본문으로 읽고** 그 위에
"쿠팡에서 구매 가능한…"으로 시작하는 표를 지어냈다.

같은 날 또 하나 실측: 크롬을 새로 띄우면 **첫 이동만** 되돌아오고 곧바로 다시 열면
통과한다(두 판 연속). 사람이 새로고침을 누르는 것과 같아서 한 번은 다시 해 본다.

여기서 지키는 것 넷:

  1. 차단 화면을 본문으로 읽지 않는다
  2. 상태 코드로 판정하지 않는다 — 실측에서 Akamai 는 **200 으로** 그 화면을 줬다
  3. 다시 해 보는 것은 **한 번뿐**이다. 계속 두드리는 것은 우회다
  4. 그 낱말이 들어간 멀쩡한 글을 차단으로 읽지 않는다
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

_DENIED = (
    "Access Denied You don't have permission to access "
    '"http://www.coupang.com/np/search?" on this server. Reference #18.6dda2317'
)


class _Body:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self, timeout: Any = None) -> str:
        del timeout
        return self._text


class _Page:
    """`pages` 만큼 이동할 때마다 다음 화면을 보여 주는 페이지."""

    def __init__(self, screens: list[tuple[str, str]]) -> None:
        self.screens = screens
        self.index = -1
        self.gotos: list[str] = []
        self.url = "about:blank"

    def goto(self, url: str, **kwargs: Any) -> None:
        del kwargs
        self.gotos.append(url)
        self.url = url
        self.index = min(self.index + 1, len(self.screens) - 1)

    def title(self) -> str:
        return self.screens[self.index][0]

    def locator(self, selector: str) -> _Body:
        del selector
        return _Body(self.screens[self.index][1])

    def is_closed(self) -> bool:
        return False


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            browser_evidence_dir=tmp_path / "evidence",
        )
    )


def test_the_block_screen_is_recognised(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page([("Access Denied", _DENIED)])
    page.goto("https://www.coupang.com/np/search?q=x")

    assert worker._edge_blocked(page) == "access denied"


def test_a_normal_page_is_not_called_blocked(tmp_path: Path) -> None:
    """차단이라고 잘못 말하면 멀쩡한 자료를 통째로 못 읽는다."""
    worker = _worker(tmp_path)
    long_article = "권한 없음 access denied 라는 오류를 다루는 글입니다. " * 60
    page = _Page([("에러 해결 방법 정리", long_article)])
    page.goto("https://blog.example.com/post")

    assert worker._edge_blocked(page) == ""


def test_a_bounce_is_retried_and_then_passes(tmp_path: Path) -> None:
    """실측에서 열리기까지 1·2·3번으로 갈렸다. 한 번에 포기하면 못 들어간다."""
    worker = _worker(tmp_path)
    page = _Page(
        [
            ("Access Denied", _DENIED),
            ("Access Denied", _DENIED),
            ("쿠팡이 추천하는 무선마우스 관련 혜택과 특가", "상품 목록입니다"),
        ]
    )

    worker._goto_checked(page, "https://www.coupang.com/np/search?q=x")

    assert len(page.gotos) == 3, "막혔는데 그대로 포기했다"
    assert page.title().startswith("쿠팡이")


def test_an_open_page_is_not_reloaded(tmp_path: Path) -> None:
    """멀쩡히 열렸으면 다시 열지 않는다 — 재시도는 막혔을 때만이다."""
    worker = _worker(tmp_path)
    page = _Page([("쿠팡이 추천하는 무선마우스 관련 혜택과 특가", "상품 목록입니다")])

    worker._goto_checked(page, "https://www.coupang.com/np/search?q=x")

    assert len(page.gotos) == 1


def test_a_wall_that_stays_up_is_reported_not_read(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    page = _Page([("Access Denied", _DENIED)])

    try:
        worker._goto_checked(page, "https://www.coupang.com/np/search?q=x")
    except RuntimeError as error:
        message = str(error)
        assert "site_blocked:www.coupang.com" in message
        assert "짐작해서" in message, "무엇을 하지 말아야 하는지 안 알려 준다"
    else:  # pragma: no cover - 실패했을 때만 도달한다
        raise AssertionError("막혔는데 열린 것처럼 넘어갔다")

    assert len(page.gotos) == 3, "열릴 때까지 두드렸거나, 한 번도 다시 안 해 봤다"
