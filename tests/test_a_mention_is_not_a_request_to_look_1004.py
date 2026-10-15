"""「브라우저」를 이야깃거리로 말한 것은 가서 보라는 말이 아니다 (2026-10-04, A6 — 10-03 21:56 2ea375c4).

「우리가 가진 강력한 무기는 너는 브라우저 다루는거라고 생각하나 아니면 머라고 보노」 — 의견을 물은 말이 「브라우저」 낱말 하나로
조사 갈래가 됐고, 답 끝에 「❌ 근거가 되는 대상 실제로 읽기 — 0개 실제로 읽음」이 붙어 일부 완료로 찍혔다.
운영 요청 1,524개 중 이 낱말 하나로만 걸린 것이 30개였다. 20개는 제품 이야기를 나누는 대화였고, 10개는 진짜 과제였다
(「공식 요금 페이지를 직접 열어서 확인해줘」) — 그래서 갈래는 그대로 두고 **「보지 않고는 답하지 못한다」는 요구만** 좁게 뺀다.
"""
from __future__ import annotations

import inspect

import pytest

from alture_jarvis import runtime as runtime_module
from alture_jarvis.runtime import JarvisRuntime


@pytest.mark.parametrize("prompt", [
    "근데 이제 우리가 가진 강력한 무기는 너는 브라우저 다루는거라고생각하나 아니면 머라고보노",
    "그러면 근데 우리는 또 브라우저를 만지는거는 진짜 최고다이가 말도안나올수준으로",
    "그려면 지금 너는 그 브라우저 MCP를 어느정도까지 가능한수준이고",
    "한 문장으로 짧고 친근하게 인사해줘. 브라우저는 사용하지 마.",
    "내가 쓰는 브라우저가 뭐야?",
])
def test_talking_about_the_browser_does_not_demand_a_reading(prompt: str) -> None:
    assert JarvisRuntime._only_mentions_the_tool(prompt) is True


@pytest.mark.parametrize("prompt", [
    "아니 브라우저로 조사해달라니까",                                   # 08-24 의 그 말 — 도구로 쓰라고 했다
    "이미 지금 로그인되어있어 너가 지금 보면돼 브라우저들어가서",
    "너가 브라우저 mcp를 사용해서 직접 이제 ms스토어 들어가서 이제 한번 봐줘",
    "구글 API 도구는 쓰지 말고 크롬 브라우저 화면으로만 해줘: drive.google.com 을 열어 파일 이름을 알려줘",
    "Browser Use 와 Manus 두 곳의 공식 요금 페이지를 직접 열어서 무료 플랜에 브라우저 자동화 실행이 포함되는가 확인해줘",
    "공식 가격 페이지에서 개인용 요금제를 모두 찾아, 에이전트/브라우저 기능 포함 여부를 엑셀로 정리해줘",
    "인터넷에서 오늘 환율 찾아봐",
    "여수 국밥집 세 곳 조사해줘",                                      # 「브라우저」가 아예 없는 조사
])
def test_a_real_request_to_look_keeps_its_demand(prompt: str) -> None:
    assert JarvisRuntime._only_mentions_the_tool(prompt) is False


def test_the_route_itself_is_untouched() -> None:
    """에이전트로 보내 도구를 쥐여 주는 것은 그대로다 — 안 보내면 창작이 나간다(08-24). 빼는 것은 읽기 요구뿐이다."""
    prompt = "근데 이제 우리가 가진 강력한 무기는 너는 브라우저 다루는거라고생각하나 아니면 머라고보노"

    assert JarvisRuntime._requires_web_research(prompt) is True


def test_both_places_that_decide_the_demand_use_it() -> None:
    source = inspect.getsource(runtime_module)

    assert "self._requires_web_research(model_prompt)\n                     and not self._only_mentions_the_tool(model_prompt)" in source
    assert "self._requires_web_research(steer_plan)\n                 and not self._only_mentions_the_tool(steer_plan)" in source
