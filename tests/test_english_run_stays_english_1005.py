"""영어로 시킨 판은 생각·중계까지 영어로 남는다 (2026-10-05 AWS 영어 윈도우 · Tesla T4 · qwen3.5:9b).

새 PC 첫 과제 「Tell me the top 3 Python repositories trending on GitHub today and their stars」.
최종 답은 영어였지만(19걸음·2/2), 도구 사이에 화면에 흘린 말 세 줄이 전부 한국어였다:

    Google 검색이 GitHub 트렌딩 리포지토리를 직접 제공하지 않습니다. 대신 GitHub 공식 트렌딩 페이지로 …
    GitHub 트렌딩 Python 페이지가 열렸습니다. 이제 화면에서 상위 3개 리포지토리와 스타 수를 확인하겠습니다.

생각 칸도 첫 걸음은 영어, 둘째 걸음부터 「시스템 메시지 …면, 아직 3개」로 바뀌었다. 영어 지시는 시스템 글 맨 앞·맨 끝
한 줄씩뿐이고, 모델이 걸음마다 마지막으로 읽는 것은 한국어 도구 안내다. 운영 모델(35B)은 버텼고 9B 는 따라갔다.
"""
from __future__ import annotations

import inspect
import re

from alture_jarvis import agent, narration
from alture_jarvis.transcript import REPLY_IN_ENGLISH_LINE, attach_system_notes, pin_reply_language

HANGUL = re.compile(r"[가-힣]")

RUN = [
    {"role": "system", "content": "당신은 손자리의 범용 로컬 Computer Use 계획자다."},
    {"role": "user", "content": "Tell me the top 3 Python repositories trending on GitHub today and their stars"},
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_search", "arguments": {}}}]},
    {"role": "tool", "tool_name": "browser_search", "content": '{"ok": true, "results": []}'},
    {"role": "user", "content": "[시스템] 아직 3개를 직접 열어 읽지 않았다. 결과 주소를 열어라."},
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_open", "arguments": {}}}]},
    {"role": "tool", "tool_name": "browser_open", "content": '{"ok": true, "url": "https://github.com/trending/python"}'},
]


def test_every_tool_result_ends_with_the_language_line() -> None:
    sent = pin_reply_language(attach_system_notes(RUN))

    tools = [item for item in sent if item["role"] == "tool"]
    assert len(tools) == 2
    for item in tools:
        assert item["content"].endswith(REPLY_IN_ENGLISH_LINE)
    # 한국어 `[시스템]` 안내가 도구 결과에 붙어도, 모델이 마지막으로 읽는 줄은 영어다.
    assert "[시스템]" in tools[0]["content"]
    assert tools[0]["content"].index("[시스템]") < tools[0]["content"].index(REPLY_IN_ENGLISH_LINE)


def test_the_line_is_english_and_names_the_three_places() -> None:
    assert not HANGUL.search(REPLY_IN_ENGLISH_LINE)
    for word in ("thinking", "before each tool call", "final answer"):
        assert word in REPLY_IN_ENGLISH_LINE


def test_only_tool_results_change_and_the_original_is_untouched() -> None:
    before = [dict(item) for item in RUN]

    sent = pin_reply_language(RUN)

    assert RUN == before, "모델에 보내는 사본만 바꾼다"
    for original, out in zip(RUN, sent):
        if original["role"] != "tool":
            assert out == original


def test_what_was_sent_last_step_is_a_prefix_of_what_is_sent_now() -> None:
    """마지막 도구 결과에만 붙이면 다음 걸음에 그 줄이 사라져 캐시가 그 자리부터 깨진다 — 전부에 늘 붙인다."""
    earlier = pin_reply_language(attach_system_notes(RUN[:4]))
    now = pin_reply_language(attach_system_notes(RUN))

    assert now[:3] == earlier[:3]
    assert now[3]["content"].startswith(earlier[3]["content"][: -len(REPLY_IN_ENGLISH_LINE)].rstrip())


def test_pinning_twice_adds_the_line_once() -> None:
    once = pin_reply_language(RUN)
    assert pin_reply_language(once) == once


def test_the_english_narration_instruction_is_english_and_keeps_the_tool_call_rule() -> None:
    text = narration.NARRATION_INSTRUCTION_EN
    assert not HANGUL.search(text)
    assert "one English sentence" in text and "tool_calls" in text and "Never speak without calling a tool" in text


def test_the_contract_line_that_says_answer_in_korean_is_swapped_for_english_runs() -> None:
    assert agent._ANSWER_IN_KOREAN in agent.AGENT_SYSTEM_PROMPT, "바꿔 넣을 줄이 계약서에 그대로 있어야 한다"
    swapped = agent.AGENT_SYSTEM_PROMPT.replace(agent._ANSWER_IN_KOREAN, agent._ANSWER_IN_ENGLISH)
    assert "한국어로 결론" not in swapped and "in English" in swapped


def test_the_model_call_pins_the_language_only_for_english_runs() -> None:
    source = inspect.getsource(agent.BrowserAgent._model_message)
    assert 'if _REPLY_LANGUAGE.get() == "en":' in source and "pin_reply_language(bounded)" in source
    assert source.index("attach_system_notes(bounded)") < source.index("pin_reply_language(bounded)")
    run = inspect.getsource(agent.BrowserAgent.run)
    assert "NARRATION_INSTRUCTION_EN if _REPLY_LANGUAGE.get() == \"en\" else NARRATION_INSTRUCTION" in run


# ── 영어 화면의 「Requested」 칸에 남은 한국어 ────────────────────────────────────────────────


def test_checklist_words_the_dictionary_lacks_come_from_the_plan_layer(tmp_path) -> None:
    """둘째 과제(arXiv) 화면: 「사이트 정렬·필터로 보기 — 최신순 정렬 안 걸림」, 첫 과제: 「Do it in GitHub — 1건」."""
    from alture_jarvis import plan, ui_i18n

    ui_i18n.reload()
    ui_i18n.configure(tmp_path / "lang.json")
    try:
        ui_i18n.set_lang("en")
        sent = ui_i18n.translate_payload({"plan": [{"label": "사이트 정렬·필터로 보기", "saw": "최신순 정렬 안 걸림"},
                                                   {"label": "GitHub 에서 하기", "saw": "1건"}],
                                          "prompt": "1건"})
        assert sent["plan"][0] == {"label": "Use the site's own sort / filters", "saw": "newest sort not applied"}
        assert sent["plan"][1]["saw"] == "1"
        assert sent["prompt"] == "1건", "사용자가 쓴 글은 바꾸지 않는다"
        assert ui_i18n.translate_text("이건 사전에도 계획 층에도 없는 말") == "이건 사전에도 계획 층에도 없는 말"
        # 화면으로 가는 말과 바깥 AI 로 가는 말이 같다.
        assert plan.display_saw("최신순 정렬 안 걸림", "en") == ui_i18n.translate_text("최신순 정렬 안 걸림")
    finally:
        ui_i18n.configure(tmp_path / "lang_reset.json")
        ui_i18n.reload()
