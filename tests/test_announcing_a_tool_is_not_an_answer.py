"""도구 이름을 부르며 끝난 답은 답이 아니다 (2026-09-26 A/B 벤치).

위시켓 · 바꾼 뒤 판: 공고 4개를 다 읽고 나서 최종 답이 이 한 줄이었다(도구 호출 없이, 25걸음, 205초).

    목록 화면에서 'AI 에이전트' 또는 'Agent'가 포함된 다른 프로젝트를 더 찾기 위해 browser_load_more를 호출하겠습니다.

`PROMISED_ACTION` 은 「호출」을 몰랐고, 이미 일을 한 판이라 예고 되받기도 꺼져 있었다. 말투 대신 **내부 도구 이름**을 본다.
"""

from __future__ import annotations

import inspect

from alture_jarvis.agent import PROMISED_ACTION, BrowserAgent, _announces_a_tool, _only_a_promise

TOOLS = frozenset({"browser_load_more", "browser_open_result", "browser_extract", "site_list"})
SEEN_IN_BENCH = (
    "목록 화면에서 'AI 에이전트' 또는 'Agent'가 포함된 다른 프로젝트를 더 찾기 위해 browser_load_more를 호출하겠습니다."
)


def test_the_answer_that_went_out_is_caught() -> None:
    assert not PROMISED_ACTION.search(SEEN_IN_BENCH), "옛 그물은 이걸 못 잡았다 — 그래서 이 판정이 있다"
    assert _announces_a_tool(SEEN_IN_BENCH, TOOLS) == "browser_load_more"


def test_the_tense_does_not_matter() -> None:
    assert _announces_a_tool("다음으로 browser_open_result 로 2번째 공고를 엽니다.", TOOLS) == "browser_open_result"


def test_a_real_answer_with_a_list_is_left_alone() -> None:
    answer = "위시켓 AI 에이전트 프로젝트 3개입니다.\n1. 챗봇 개발 — 500만 원\n2. RAG 구축 — 800만 원\n3. 상담 봇 — 300만 원"
    assert _announces_a_tool(answer + "\n(browser_extract 로 읽음)", TOOLS) == ""


def test_snake_case_that_is_not_our_tool_is_left_alone() -> None:
    assert _announces_a_tool("변수 이름은 user_name 으로 두면 됩니다.", TOOLS) == ""


def test_a_long_answer_is_left_alone() -> None:
    assert _announces_a_tool("설명 " * 150 + "browser_extract", TOOLS) == ""


def test_it_is_wired_into_the_loop_and_answers_without_tools() -> None:
    """판정만 만들고 부르는 자리가 없으면 아무 일도 안 일어난다(이 저장소가 여러 번 겪은 모양)."""
    source = inspect.getsource(BrowserAgent.run)
    start = source.index("announced = \"\" if pushback_spent else")
    block = source[start : start + 5200]
    assert "continue" in block, "걸음이 남았으면 예고한 일을 하게 되받는다"
    # 도구 없이 글로 답하게 부른다. 2026-09-28 부터는 `_text_only_message` 가 캐시를 지키려고 같은 목록을 보내고,
    # 도구만 부르고 글이 없을 때만 목록 없이 한 번 더 부른다(test_side_calls_keep_the_tool_list).
    assert "_text_only_message(" in block, "걸음 상한에 닿은 판에서도 답을 지을 수 있어야 한다 — 글로만 답하게 부른다"
    # 2026-10-02 밤: 「판당 한 번」 → 「지난 되받기 뒤에 도구를 더 썼으면 다시」(상한 있음, test_promise_pushback_repeats_while_progressing).
    assert block.count("announce_synths += 1") == 2 and "announce_pushback_steps = len(steps)" in block
    assert "len(steps) <= announce_pushback_steps or announce_synths >= _ANNOUNCE_PUSHBACK_MAX" in source


def test_a_short_promise_after_reading_something_is_still_not_an_answer() -> None:
    """대학알리미 · 바꾼 뒤: 블로그 한 편을 읽고 이 한 줄로 끝났다. 읽은 게 있다고 예고가 답이 되지는 않는다."""
    assert _only_a_promise("대학알리미(대학정보공시)에서 취업률 지표를 확인하는 방법을 찾아보겠습니다.")


def test_a_real_answer_that_mentions_a_next_step_is_left_alone() -> None:
    answer = "대학알리미 취업률은 공시정보 › 주요지표에서 봅니다.\n1. 상단 공시정보\n2. 취업률 선택\n더 자세히는 학교별로 확인하겠습니다."
    assert not _only_a_promise(answer)



def test_a_promise_is_caught_by_how_it_ends_not_by_a_word_list() -> None:
    """고친 판 벤치(날씨): 「이동」이 낱말표에 없어 빠져나갔다."""
    assert _only_a_promise("검색창에 '부산'을 입력했으니 이제 검색 버튼을 눌러 부산 날씨 페이지로 이동하겠습니다.")
    assert _only_a_promise("상세 페이지를 열어 가격을 확인해 볼게요.")


def test_short_real_answers_are_not_promises() -> None:
    assert not _only_a_promise("오늘 부산 최고기온은 24도입니다.")
    assert not _only_a_promise("네이버 첫 화면 제목은 NAVER 입니다.")
