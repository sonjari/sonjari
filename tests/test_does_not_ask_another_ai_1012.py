"""다른 AI 대화 사이트에 대신 묻지 않는다 — 사용자가 시켰을 때만 (2026-10-12).

작은 카드로 쓰는 사람이 「그 회사의 홍보 전략부터 다시 잡아 보자」고 하자, 손자리가 그 회사의 AI 대화 사이트에 들어가
입력칸에 그 질문을 쳤다. 같은 날 아침 4B 도 가격 조사가 벅차자 같은 쪽으로 흘렀다. 일을 시켰는데 남에게 물으러 간 것이다.

걸음의 모양은 실제 기록 그대로다(도구 · 성공 여부 · 인자 · `evidence.url`). 요청 글은 그 순서를 본떠 지은 것이다.
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from alture_jarvis import agent
from alture_jarvis.ai_chat_sites import AI_CHAT_HOSTS, TYPING_TOOLS, asked_to_use_one, asks_another_ai, is_ai_chat_site, refusal_note

ABOUT = "GPT의 홍보 전략부터 다시 잡아보자"
TOLD = "이 문장을 챗GPT한테 물어봐서 뭐라고 하는지 알려줘"


def _step(tool: str, landed: str = "", /, *, ok: bool = True, **arguments: Any) -> dict[str, Any]:
    return {"tool": tool, "ok": ok, "arguments": arguments, "evidence": {"url": landed} if landed and ok else {}}


ON_THE_CHAT_SITE = [_step("browser_search", "https://www.google.com/search?q=x", query="GPT 홍보 전략"),
                    _step("browser_open", "https://chatgpt.com/", url="https://chatgpt.com")]


def test_typing_into_an_ai_chat_site_is_turned_back_when_nobody_asked_for_it() -> None:
    for hand in sorted(TYPING_TOOLS):
        assert asks_another_ai(hand, {"text": "홍보 전략을 알려줘"}, ON_THE_CHAT_SITE, ABOUT) == "chatgpt.com", hand
    note = refusal_note("chatgpt.com")
    assert "chatgpt.com" in note and "직접 조사" in note and "모른다고 답해라" in note


def test_naming_the_service_is_not_the_same_as_telling_us_to_ask_it() -> None:
    assert not asked_to_use_one(ABOUT)
    assert not asked_to_use_one("GPT가 어떻게 그렇게 자리를 잡았는지 마케팅 전략을 깊이 알려줘")
    assert not asked_to_use_one("제미나이랑 클로드 요금제 비교해 줘")
    for told in (TOLD, "제미나이에 이거 입력해 줘", "클로드에게 같은 질문을 물어보고 답을 비교해 줘", "Ask ChatGPT what it thinks of this"):
        assert asked_to_use_one(told), told
        assert asks_another_ai("browser_fill", {"text": "x"}, ON_THE_CHAT_SITE, told) == ""


def test_reading_the_site_and_working_elsewhere_are_untouched() -> None:
    for hand in ("browser_extract", "browser_read", "browser_snapshot", "browser_open_result", "browser_click", "local_write_document"):
        assert asks_another_ai(hand, {}, ON_THE_CHAT_SITE, ABOUT) == "", hand
    elsewhere = [_step("browser_open", "https://www.danawa.com/", url="https://www.danawa.com")]
    for hand in sorted(TYPING_TOOLS):
        assert asks_another_ai(hand, {"query": "가상 상품"}, elsewhere, "다나와에서 가상 상품 찾아줘") == "", hand
    # 그 사이트를 떠났으면 다시 글을 넣을 수 있다 — 지금 있는 자리로 본다.
    left = ON_THE_CHAT_SITE + [_step("browser_open", "https://www.danawa.com/", url="https://www.danawa.com")]
    assert asks_another_ai("browser_site_search", {"query": "가상 상품"}, left, ABOUT) == ""
    # 실패한 열기는 자리를 옮기지 않는다.
    not_there = [_step("browser_open", "https://www.danawa.com/", url="https://www.danawa.com"),
                 _step("browser_open", "https://chatgpt.com/", ok=False, url="https://chatgpt.com")]
    assert asks_another_ai("browser_fill", {"text": "x"}, not_there, ABOUT) == ""


def test_opening_one_with_the_question_in_the_address_is_the_same_thing() -> None:
    assert asks_another_ai("browser_open", {"url": "https://chatgpt.com/?prompt=%ED%99%8D%EB%B3%B4"}, [], ABOUT) == "chatgpt.com"
    assert asks_another_ai("browser_open", {"url": "https://www.perplexity.ai/search?q=marketing"}, [], ABOUT) == "www.perplexity.ai"
    # 그냥 여는 것 · 질문을 실었어도 시킨 것 · 검색엔진은 아니다.
    assert asks_another_ai("browser_open", {"url": "https://chatgpt.com/"}, [], ABOUT) == ""
    assert asks_another_ai("browser_open", {"url": "https://chatgpt.com/?prompt=x"}, [], TOLD) == ""
    assert asks_another_ai("browser_open", {"url": "https://www.google.com/search?q=x"}, [], ABOUT) == ""
    assert asks_another_ai("browser_open", None, [], ABOUT) == ""


@pytest.mark.parametrize("url", ["https://chatgpt.com/c/abc", "https://gemini.google.com/app", "https://claude.ai/new", "https://www.perplexity.ai/"])
def test_the_chat_sites(url: str) -> None:
    assert is_ai_chat_site(url)


def test_their_other_pages_and_ordinary_sites_are_not_chat_sites() -> None:
    for url in ("https://openai.com/blog", "https://www.google.com/search?q=gemini", "https://www.anthropic.com/news",
                "https://blog.naver.com/x", "https://notchatgpt.com/", ""):
        assert not is_ai_chat_site(url), url
    assert all("." in host for host in AI_CHAT_HOSTS)


def test_the_agent_turns_it_back_before_running_the_tool() -> None:
    source = inspect.getsource(agent)
    assert "elif (other_ai := asks_another_ai(name, arguments, steps, plan_text)):" in source
    hook = source[source.index("elif (other_ai := asks_another_ai("):]
    hook = hook[:hook.index('and name == "sandbox_run"')]
    assert '"error": f"asks_another_ai:{other_ai}"' in hook and "ai_chat_refusal_note(other_ai)" in hook
