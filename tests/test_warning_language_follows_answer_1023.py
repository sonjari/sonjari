"""경고 언어는 답의 언어를 따른다 · 순위 경고는 무엇과 견줬는지 남긴다 (2026-10-23 레딧 영상 이어받기 판).

영어 화면에서 「Claude Code hit its usage limit… take over」로 이어받기를 했더니, 요청 글이 손자리가 만든 **한국어 인계문**이라
판 언어가 「ko」로 정해졌다. 답은 「화면이 영어면 영어로」(`_voice_for`)를 따라 영어였고, 순위 경고만 한국어로 붙었다.
같은 것을 두 군데서 정하면 갈린다 — 경고는 답의 언어를 따르게 한다.
"""

from __future__ import annotations

import inspect

from alture_jarvis import agent
from alture_jarvis.promise_gate import rank_order_source, rank_order_warning

ENGLISH_ANSWER = (
    "Done.\n\n| # | Repo | Stars |\n| --- | --- | --- |\n"
    "| 1 | alpha/one | 10 |\n| 2 | beta/two | 9 |\n| 3 | gamma/three | 8 |\n\nAll three were read from the page."
)
PAGE_IN_OTHER_ORDER = [{"role": "tool", "tool_name": "browser_read", "content": "gamma/three ... beta/two ... alpha/one"}]


def test_an_english_answer_gets_an_english_rank_warning_even_when_the_brief_is_korean() -> None:
    korean_brief = "Claude Code 가 사용량 한도로 멈춘 작업을 이어서 한다. 상위 3개 저장소."
    token = agent._REPLY_LANGUAGE.set(None)   # 영어 화면 · 한국어 인계문 판은 판 언어를 미리 정하지 않는다
    try:
        note = rank_order_warning(korean_brief, ENGLISH_ANSWER, PAGE_IN_OTHER_ORDER,
                                  english=agent.reply_language(ENGLISH_ANSWER) == "en")
    finally:
        agent._REPLY_LANGUAGE.reset(token)
    assert "The order differs" in note and "순서" not in note


def test_the_run_leaves_the_language_open_on_an_english_screen_with_a_korean_brief() -> None:
    source = inspect.getsource(agent.BrowserAgent.run)
    assert '_REPLY_LANGUAGE.set(None if ui_i18n.lang() == "en" else "ko")' in source


def test_notes_shown_to_the_person_follow_the_answer_language() -> None:
    source = inspect.getsource(agent)
    assert "rank_order_warning(asked, answer, messages, english=reply_language(answer)" in source
    assert "summary_note(final_plan_results, reply_language(answer))" in source
    assert "summary_note(final_plan_results, reply_language(asked))" not in source


def test_the_rank_check_records_what_it_compared_against() -> None:
    found = rank_order_source(ENGLISH_ANSWER, PAGE_IN_OTHER_ORDER)
    assert found["tool_name"] == "browser_read" and found["names"] == ["alpha/one", "beta/two", "gamma/three"]
    assert found["positions"][0] > found["positions"][2]
    assert all(len(text) <= 60 + 40 for text in found["around"])


def test_nothing_is_recorded_when_no_tool_result_holds_all_names() -> None:
    assert rank_order_source(ENGLISH_ANSWER, [{"role": "tool", "content": "alpha/one only"}]) == {}


def test_the_first_word_wait_line_follows_the_screen_when_the_run_language_is_open(monkeypatch) -> None:  # noqa: ANN001
    """「모델의 첫 글자를 기다리는 중 · 5초째」가 영어 화면에 한국어로 떴다(10-23 대표 · 이어받기 점검 판)."""
    from alture_jarvis import ui_i18n

    monkeypatch.setattr(ui_i18n, "lang", lambda: "en")
    token = agent._REPLY_LANGUAGE.set(None)
    try:
        assert agent._shown_in_english() is True
    finally:
        agent._REPLY_LANGUAGE.reset(token)
    token = agent._REPLY_LANGUAGE.set("ko")   # 사람이 한국어로 시킨 판은 화면이 영어여도 한국어
    try:
        assert agent._shown_in_english() is False
    finally:
        agent._REPLY_LANGUAGE.reset(token)
    assert "english=_shown_in_english()" in inspect.getsource(agent)


def test_inserting_the_record_did_not_steal_a_decorator() -> None:
    """10-23 처음 넣을 때 `_commit_reality_check` 위의 @staticmethod 가 새 함수로 붙어, 점검 판이 마지막 검사에서 TypeError 로 넘어졌다."""
    assert isinstance(inspect.getattr_static(agent.BrowserAgent, "_commit_reality_check"), staticmethod)
    assert not isinstance(inspect.getattr_static(agent.BrowserAgent, "_rank_order_note"), staticmethod)


def _open_result(page_text: str, remembered: list[str], *, cut: bool = False) -> dict:
    import json as _json

    body = _json.dumps({"ok": True, "url": "https://github.com/trending/python", "text": page_text,
                        "site_traits": [{"trait": "readable_url", "count": 28, "details": remembered}],
                        "instruction": "이 사이트에서 전에 본 주소: " + ", ".join(remembered)}, ensure_ascii=False)
    return {"role": "tool", "tool_name": "browser_open", "content": body[:-40] if cut else body}


def test_the_site_memory_attached_to_a_result_is_not_the_page_order() -> None:
    """10-23 확인한 헛경고 그대로 — 페이지는 바른 순서, 결과 끝의 사이트 기억(지난 판 방문 주소)만 거꾸로였다."""
    page = "Trending · alpha/one 10 stars · beta/two 9 stars · gamma/three 8 stars"
    remembered = ["/gamma/three/releases", "/gamma/three", "/beta/two", "/alpha/one"]
    for cut in (False, True):
        messages = [_open_result(page, remembered, cut=cut)]
        assert rank_order_warning("top 3 repos", ENGLISH_ANSWER, messages, english=True) == "", cut


def test_a_page_really_in_another_order_still_warns_with_site_memory_present() -> None:
    page = "Trending · gamma/three 8 stars · beta/two 9 stars · alpha/one 10 stars"
    messages = [_open_result(page, ["/alpha/one", "/beta/two", "/gamma/three"])]
    assert "The order differs" in rank_order_warning("top 3 repos", ENGLISH_ANSWER, messages, english=True)


def test_site_memory_nested_one_level_down_is_also_left_out() -> None:
    """실제 촬영 판(10-23 c0fcc75a)에서는 사이트 기억이 결과 한 겹 안쪽에 있어 첫 고침을 빠져나갔다."""
    import json as _json

    page = "Trending · alpha/one 10 stars · beta/two 9 stars · gamma/three 8 stars"
    inner = {"ok": True, "text": page, "site_traits": [{"trait": "readable_url", "details": ["/gamma/three", "/beta/two", "/alpha/one"]}]}
    messages = [{"role": "tool", "tool_name": "browser_open", "content": _json.dumps({"ok": True, "result": inner})}]
    assert rank_order_warning("top 3 repos", ENGLISH_ANSWER, messages, english=True) == ""
