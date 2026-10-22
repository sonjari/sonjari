"""답 끝 경고의 헛경고 둘 (2026-10-22 손자리 홍보 조사 판 f0bc931c · 대표 「진짜 보기 싫다」).

1. 「읽은 자료에 없는 금액: $0.07, $0.63」 — 답은 README 의 `$0.074` · `$0.635` 를 그대로 옮겼는데, 금액 정규식이 소수점 아래를
   두 자리까지만 읽어 잘린 값을 원문에서 찾았다.
2. 「읽지 않고 적은 것: Reddit r/LLMDevs」 — 그 레딧 글을 직접 열어 읽었다. 「낱말이 한자리에 모였나」 구제에 띄어쓰기를 지운
   이름(`Redditr/LLMDevs`)이 넘어가 늘 「아니다」였다.
안 읽은 것은 여전히 잡혀야 한다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent

README = "| arm | rows | cost/row |\n| Sonjari | 23/27 | $0.074 |\n| Playwright MCP | 11/27 | $0.635 |"


def _tool(text: str) -> list[dict]:
    return [{"role": "tool", "tool_name": "browser_extract", "content": text}]


def test_sub_cent_amounts_copied_from_the_page_are_not_flagged() -> None:
    answer = "Free local agent: 23/27 at $0.074/row, vs Playwright MCP 11/27 at $0.635/row."
    assert BrowserAgent._money_grounding_check("홍보 전략", answer, _tool(README)) == ""


def test_a_sub_cent_amount_that_was_not_read_is_still_flagged_whole() -> None:
    warning = BrowserAgent._money_grounding_check("홍보 전략", "It costs $0.081 per row.", _tool(README))
    assert "$0.081" in warning, "잘린 값($0.08)이 아니라 답에 쓴 값 그대로 보여야 한다"


def test_two_decimal_amounts_still_compare_exactly() -> None:
    assert BrowserAgent._money_grounding_check("", "It is $24.99.", _tool("price $24.90")) != ""
    assert BrowserAgent._money_grounding_check("", "It is $24.99.", _tool("price $24.99")) == ""


TABLE = """| 채널 | 상태 |
|---|---|
| **GitHub** | 3스타 |
| **Reddit r/LLMDevs** | 4,300회 조회 |
| **Reddit r/ClaudeWorkflows** | 1댓글 |
"""


def test_a_platform_and_subforum_read_together_is_not_unread() -> None:
    page = "Reddit - The heart of the internet. r/LLMDevs Posted by u/someone. Sonjari ... GitHub stars 3"
    warning = BrowserAgent._listed_entity_grounding_check(TABLE, _tool(page))
    assert "r/LLMDevs" not in warning
    assert "Reddit r/ClaudeWorkflows" in warning, "열지 않은 게시판은 그대로 잡혀야 한다"


def test_words_scattered_far_apart_do_not_rescue_a_name() -> None:
    page = "Reddit " + ("x " * 200) + "r/LLMDevs GitHub"
    warning = BrowserAgent._listed_entity_grounding_check(TABLE, _tool(page))
    assert "Reddit r/LLMDevs" in warning
