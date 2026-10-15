"""상세는 **열기만 하면 끝이 아니다** — 훑어 내리고, 남았으면 남았다고 말한다.

## 사용자님이 짚으신 것 (2026-08-13)

    "지금 상세페이지 들어가는 것에만 보상이 있고 스크롤에는 아예 관심도 없다.
     상세페이지는 무조건 스크롤이 없을 수가 없을 건데."

측정해 보니 정확했다(그날 잡 260건):

    상세를 연 횟수(open_result)          165
    그중 그 페이지에서 스크롤한 것        **1 (0.6%)**
    browser_extract 성공                 128
    그중 8,000자 상한에 딱 걸린 것        **29 (23%)**

## 왜 이런 모양이 됐나 — 보상의 생김새

계획 층이 세는 것은 "몇 개를 **열었나**"다(`_sources_read`). 열기만 하면 요구가
채워지고, 다 읽었는지는 아무도 안 본다. **첫 화면만 보고 나오는 것이 이득이었다.**

거기에 두 가지가 겹친다:

  1. 지연 로딩 — 쿠팡 상세정보·다나와 스펙표는 **내려가야 DOM 에 생긴다.**
     안 내리고 읽으면 "그 페이지에 그런 정보가 없다"가 되는데 사실은 안 그려진 것이다.
  2. 조용한 절단 — 8,000자에서 끊고는 `char_count: 8000` 만 준다. 모델은 그게
     전부인 줄 알고 "그 페이지에는 없습니다"라고 답한다.

## 고친 방향

프롬프트에 "스크롤해라"는 이미 있었다(그리고 0.6%였다). 그래서 **도구가 한다** —
읽기 전에 끝까지 훑어 내렸다 돌아오고, 남은 글이 있으면 결과에 적는다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.browser import (
    _LAZY_SWEEP_MIN_RATIO,
    _LAZY_SWEEP_PAUSE_MS,
    _LAZY_SWEEP_STEPS,
    BrowserWorker,
)


class _Page:
    """훑기 스크립트를 실제로 돌리지 않고 **불렀는지만** 본다."""

    def __init__(self, *, raises: bool = False) -> None:
        self.evaluated: list[Any] = []
        self.raises = raises

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if self.raises:
            raise RuntimeError("evaluate blocked")
        self.evaluated.append(arg)
        return {"swept": True, "before": 4000, "after": 9000}


def test_it_sweeps_before_reading() -> None:
    page = _Page()
    swept = BrowserWorker._sweep_for_lazy_content(BrowserWorker.__new__(BrowserWorker), page)

    assert swept["swept"] is True
    assert page.evaluated == [
        {"steps": _LAZY_SWEEP_STEPS, "pause": _LAZY_SWEEP_PAUSE_MS, "minRatio": _LAZY_SWEEP_MIN_RATIO}
    ]


def test_a_blocked_sweep_does_not_break_reading() -> None:
    """훑기는 읽기를 **거들려고** 있는 것이지 읽기의 조건이 아니다.

    CSP 로 evaluate 가 막히는 페이지가 있다. 거기서 예외가 올라가면 본문을 통째로
    못 읽게 되는데, 그건 안 훑는 것보다 훨씬 나쁘다.
    """
    page = _Page(raises=True)
    assert BrowserWorker._sweep_for_lazy_content(BrowserWorker.__new__(BrowserWorker), page) == {}


def test_the_sweep_is_bounded() -> None:
    """상세 한 장에 쓰는 시간이다. 무제한이면 읽기가 느려진다."""
    assert _LAZY_SWEEP_STEPS * _LAZY_SWEEP_PAUSE_MS <= 2000
    assert _LAZY_SWEEP_MIN_RATIO > 1, "한 화면짜리 페이지까지 훑으면 순수한 낭비다"


# ── 잘렸으면 잘렸다고 말한다 ────────────────────────────────────────────────


class _ExtractWorker:
    """`_extract` 의 뒷부분만 태운다 — 프레임도 크롬도 없다."""

    def __init__(self, body: str) -> None:
        self.body = body
        self._last_results: list[dict[str, Any]] = []
        self._reads_since_search = 1

    _sweep_for_lazy_content = staticmethod(lambda page: {})
    _mark_visited = staticmethod(lambda url: None)
    _frame_label = staticmethod(lambda frame, index: "main")
    _evidence = staticmethod(lambda action, **kw: {"action": action, **kw})
    _site_search_offer = staticmethod(lambda page: "")
    # 섀도 DOM 이 없는 페이지 — 섀도 글자 읽기는 빈 값이다(2026-09-17).
    _deep_text = staticmethod(lambda page, max_chars: "")
    # 그림 본문 알림(2026-10-04)은 진짜 것을 그대로 쓴다 — 이 재료엔 그림이 없으니 빈 글이 나온다.
    _IMAGE_BODY_MAX_CHARS = BrowserWorker._IMAGE_BODY_MAX_CHARS
    _image_body_note = BrowserWorker._image_body_note
    # 그 알림은 지금 모델이 그림을 읽는지 묻는다(2026-10-12) — 물어볼 손이 없으면 「모른다」로 예전 글이 나온다.
    _cannot_read_pictures = BrowserWorker._cannot_read_pictures
    _read_selectors_for = BrowserWorker._read_selectors_for

    def _frames_of(self, page: Any) -> list[Any]:
        body = self.body

        class _Frame:
            @staticmethod
            def evaluate(script: str) -> dict[str, Any]:
                return {"text": body, "score": 900, "selector": "article", "link_ratio": 2}

        return [_Frame()]


def _extract(body: str, **arguments: Any) -> dict[str, Any]:
    return BrowserWorker._extract(_ExtractWorker(body), page=None, arguments=arguments)


def test_a_short_page_says_nothing_about_truncation() -> None:
    result = _extract("짧은 본문입니다.")
    assert "truncated" not in result


def test_a_long_page_says_how_much_is_left() -> None:
    """실측 23%가 이 자리였다 — 상한에 딱 걸리고도 아무 말이 없었다."""
    result = _extract("가" * 40000)

    assert result["char_count"] == 20000, "기본 상한이 20,000 이어야 한다"
    assert result["truncated"] is True
    assert "max_chars" in result["truncated_note"], "다음 수를 안 알려 준다"
    assert "없는 것이 아니라" in result["truncated_note"]


def test_asking_for_more_actually_gets_more() -> None:
    """안내가 거짓이면 안내가 아니다 — 시키는 대로 하면 실제로 더 와야 한다."""
    result = _extract("가" * 25000, max_chars=30000)

    assert result["char_count"] == 25000
    assert "truncated" not in result


def test_the_two_caps_move_together() -> None:
    """추출 상한과 전사의 도구결과 상한은 **쌍**이다.

    저쪽이 30,000 을 돌려줘도 이쪽이 20,000 이면 10,000 이 조용히 날아간다.
    오늘만 세 번째로 만난 "상한이 여러 군데면 낮은 쪽만 일한다" 자리다.
    """
    from alture_jarvis.agent import _TOOL_RESULT_MAX_CHARS

    biggest = _extract("가" * 60000, max_chars=99999)["char_count"]
    assert biggest <= _TOOL_RESULT_MAX_CHARS, (
        f"추출이 {biggest}자를 돌려주는데 전사는 {_TOOL_RESULT_MAX_CHARS}자에서 자른다 — "
        "그 차이는 조용히 사라진다"
    )
