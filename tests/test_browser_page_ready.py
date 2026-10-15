"""문서가 내려온 것과 화면이 그려진 것은 다르다.

2026-08-05 사이트 8곳 점검에서 대학어디가·학교알리미·한국교육과정평가원이 **조작
가능한 요소 0개**로 나왔다. 잠시 뒤 다시 재면 111개·72개·177개다. 서버가 뼈대만
내려주고 나머지를 스크립트가 그리는 사이트에서는 전부 이렇게 된다.

요소 0개는 "빈 페이지"와 구별되지 않는다 — 그걸 본 모델은 클릭 계획을 못 세우고
다른 길로 새거나 없는 셀렉터를 지어낸다. 네이버 편집기에서 하루를 보낸 것과 같은
고장(따뜻한 날엔 되고 식은 날엔 안 된다)이 범용 경로에도 있었다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Locator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class _Frame:
    """몇 번째로 물어보는지에 따라 다르게 답하는 프레임 — 그려지는 중인 화면."""

    def __init__(self, counts: list[int]) -> None:
        self.counts = counts
        self.asked = 0
        self.url = "https://example.test/"

    def locator(self, selector: str) -> _Locator:
        del selector
        value = self.counts[min(self.asked, len(self.counts) - 1)]
        self.asked += 1
        return _Locator(value)


class _Page:
    def __init__(self, frame: _Frame) -> None:
        self.frames = [frame]
        self.url = "https://example.test/"
        self.goto_calls: list[str] = []

    def goto(self, url: str, wait_until: str = "") -> None:
        del wait_until
        self.goto_calls.append(url)

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "예시"


def _worker(tmp_path: Path, **overrides: Any) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            **overrides,
        )
    )


def test_it_waits_for_the_page_to_draw_itself(tmp_path: Path) -> None:
    # 첫 두 번은 아무것도 없고 그 다음에 그려진다 — 실제 사이트가 이 모양이다.
    page = _Page(_Frame([0, 0, 42]))

    ready = _worker(tmp_path)._wait_until_operable(page, timeout_ms=3000)

    assert ready["count"] == 42


def test_it_does_not_wait_when_the_page_is_already_there(tmp_path: Path) -> None:
    page = _Page(_Frame([17]))

    ready = _worker(tmp_path)._wait_until_operable(page, timeout_ms=3000)

    assert ready["count"] == 17
    assert ready["ms"] < 200, "이미 그려진 화면에서 기다리면 모든 이동이 그만큼 느려진다"


def test_invisible_elements_in_front_do_not_hide_the_ones_behind(tmp_path: Path) -> None:
    """안 보이는 것이 앞을 채우고 있어도 뒤에 있는 것을 찾아낸다.

    2026-08-06 실측(네이버 블로그 탭): 조작 가능한 요소 377개 중 **보이는 것은 39개**
    였고 **첫 결과가 240번째**였다. 훑는 범위가 `budget * 3` 이던 시절에는 192번째에서
    끊겨 결과를 하나도 못 봤고, 겉으로는 "이 검색은 결과가 0건"으로 보였다 —
    봇 차단이나 파서 버그와 구별되지 않는 모양이다.
    """

    class _Element:
        def __init__(self, index: int) -> None:
            self.index = index

        # 앞의 240개는 DOM 에 있지만 화면에 없다.
        def is_visible(self) -> bool:
            return self.index >= 240

        def is_disabled(self) -> bool:
            return False

        def evaluate(self, script: str, *args: Any) -> Any:
            return "a" if "tagName" in script else None

        def get_attribute(self, name: str) -> str | None:
            return "https://blog.naver.com/post" if name == "href" else None

        def inner_text(self, timeout: int = 0) -> str:
            del timeout
            return f"결과 {self.index}"

    class _WideLocator:
        def count(self) -> int:
            return 377

        def nth(self, index: int) -> _Element:
            return _Element(index)

    class _WideFrame:
        name = ""
        url = "https://search.naver.com/"

        def locator(self, selector: str) -> _WideLocator:
            del selector
            return _WideLocator()

    found = _worker(tmp_path)._frame_elements(
        _WideFrame(), frame_label="main", frame_index=0, budget=12, start=0, include_box=False
    )

    assert len(found) == 12, "훑는 범위를 budget 배수로 끊으면 뒤에 있는 결과를 못 본다"


def test_a_genuinely_empty_page_gives_up_and_says_so(tmp_path: Path) -> None:
    # 오류 화면·차단 화면은 정말로 누를 것이 없다. 영원히 기다리면 안 되고,
    # 0이라는 사실이 증거에 남아야 사람이 알아본다.
    page = _Page(_Frame([0]))

    ready = _worker(tmp_path)._wait_until_operable(page, timeout_ms=400)

    assert ready["count"] == 0
    assert ready["ms"] >= 300


def test_open_reports_how_much_it_found(tmp_path: Path) -> None:
    page = _Page(_Frame([0, 9]))

    result = _worker(tmp_path)._open(page, {"url": "https://example.test/"})

    assert page.goto_calls == ["https://example.test/"]
    assert result["element_count"] == 9
