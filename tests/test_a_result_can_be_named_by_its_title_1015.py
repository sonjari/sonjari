"""결과를 **제목으로** 지목하면 순위를 잘못 세도 그 글이 열린다 (2026-10-15).

10-15 02:41 레딧 판(3dc56fb1): 검색 결과에서 「Why run LLMs locally?」를 찾아 놓고 `browser_open_result(rank=1)` 을 불렀다.
1번은 다른 글(DGX 하드웨어 글)이었고, 손자리는 그 글의 댓글 80개를 읽은 뒤 답에 「실수로 다른 글을 열었다」고 적었다. 뒤로 돌아와
그 제목의 링크를 찾았지만, 레딧 검색 목록은 내려가며 그려져 줄이 화면에 없었다.

순위는 모델이 세는 값이라 틀린다. 모델이 **본 그대로의 제목**을 줄 수 있게 한다:
- `title` 을 주면 지금 목록에서 그 제목이 들어간 결과를 연다 — `rank` 와 어긋나면 제목이 이긴다(모델이 본 것이 제목이다).
- 그 제목인 결과가 없으면 추측해서 열지 않고, 목록에 있는 제목들을 알려 준다.
- `title` 이 없으면 지금처럼 `rank` 로 연다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.browser import BrowserWorker

RANKS = [
    {"rank": 1, "url": "https://www.reddit.com/r/LocalLLaMA/comments/a1/from_1x3090_to_20_dgx_sparks/",
     "title": "From 1x3090 to 20 DGX Sparks: my house"},
    {"rank": 2, "url": "https://www.reddit.com/r/LocalLLaMA/comments/a2/why_run_llms_locally/",
     "title": "Why run LLMs locally?"},
]


def _worker() -> BrowserWorker:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._last_results = [dict(item) for item in RANKS]
    return worker


def test_the_title_wins_over_a_miscounted_rank() -> None:
    assert _worker()._pick_result(1, "Why run LLMs locally")["rank"] == 2


def test_the_title_match_ignores_case_and_spacing() -> None:
    assert _worker()._pick_result(0, "  why RUN llms   locally? ")["rank"] == 2


def test_a_title_not_in_the_list_is_not_guessed() -> None:
    with pytest.raises(ValueError) as refused:
        _worker()._pick_result(1, "What's your reason for running local?")
    said = str(refused.value)
    assert said.startswith("result_title_not_found")
    assert "Why run LLMs locally?" in said, "있는 제목을 알려 준다"


def test_without_a_title_the_rank_opens_as_before() -> None:
    assert _worker()._pick_result(1, "")["rank"] == 1
    with pytest.raises(ValueError):
        _worker()._pick_result(9, "")


def test_the_tool_offers_a_title() -> None:
    from alture_jarvis.browser import BrowserTools

    tools = BrowserTools.__new__(BrowserTools)
    spec = next(tool for tool in BrowserTools._build_definitions(tools) if tool["function"]["name"] == "browser_open_result")
    assert "title" in spec["function"]["parameters"]["properties"]
