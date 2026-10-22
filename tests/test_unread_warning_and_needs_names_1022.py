"""잡 7832a9a6(10-22 · 코딩 에이전트들의 저장소 색인 조사)에서 보인 버그 둘.

1. 「| Hermes Agent | 못 찾음 | 못 찾음 | … |」처럼 **못 찾았다고 정직하게 적은 줄**에 「읽지 않고 적은 것」 경고가 붙었다.
   이름 말고 모든 칸이 「못 찾음」이면 그 줄은 아무것도 주장하지 않는다. 값이 하나라도 있으면 그대로 본다.
2. 「필요한 것」 다섯 중 넷이 「확인 못 함」 — 이름이 채점에만 쓰이고 일하는 모델에게는 간 적이 없었다. 이제 과제 글에 싣는다.
"""

from __future__ import annotations

import asyncio
from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.mcp_server import JarvisMcpBridge

PROMPT = "코딩 AI 에이전트들(Claude Code, Aider, Cursor, OpenAI Codex CLI, Hermes Agent, OpenHands)이 저장소를 어떻게 다루는지 표로"
READ = "Aider repo map uses tree-sitter ... Claude Code reads files fresh on each tool call ..."
MESSAGES = [{"role": "user", "content": PROMPT}, {"role": "tool", "content": READ}]

HEAD = "| 에이전트 | ① 미리 만드는지 | ② 색인 시점 | ③ 제외 | ④ 측정 |\n|---|---|---|---|---|\n"


def test_rows_that_only_say_not_found_get_no_warning() -> None:
    answer = (HEAD
              + "| **Aider** | 미리 만듦 | 증분 | git 추적 파일 | PageRank |\n"
              + "| **Claude Code** | 색인 없음 | 해당 없음 | .gitignore | 토큰 비용 |\n"
              + "| **OpenAI Codex CLI** | 못 찾음 | 못 찾음 | 못 찾음 | 못 찾음 |\n"
              + "| **Hermes Agent (Nous Research)** | 못 찾음 | 못 찾음 | 못 찾음 | 못 찾음 |\n"
              + "| **OpenHands** | 못 찾음 | — | 확인 못 함 | N/A |\n")
    assert BrowserAgent._listed_entity_grounding_check(answer, MESSAGES) == ""


def test_a_row_with_a_value_is_still_checked_even_if_other_cells_say_not_found() -> None:
    answer = (HEAD
              + "| **Hermes Agent** | 시작할 때 색인 | 못 찾음 | 못 찾음 | 못 찾음 |\n"
              + "| **OpenHands** | 미리 만듦 | 뒤에서 | 못 찾음 | 못 찾음 |\n")
    warning = BrowserAgent._listed_entity_grounding_check(answer, MESSAGES)
    assert "Hermes Agent" in warning and "OpenHands" in warning


def test_a_value_like_none_is_still_a_claim() -> None:
    """「없음」은 「못 찾음」이 아니다 — 「할인 없음」은 값이다."""
    answer = (HEAD
              + "| **Hermes Agent** | 없음 | 없음 | 없음 | 없음 |\n"
              + "| **OpenHands** | 없음 | 없음 | 없음 | 없음 |\n")
    warning = BrowserAgent._listed_entity_grounding_check(answer, MESSAGES)
    assert "Hermes Agent" in warning and "OpenHands" in warning


class _Resp:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> Any:
        return self._payload


class _Capture:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        return _Resp([])

    async def post(self, url: str, json: dict[str, Any] | None = None, **kwargs: Any) -> Any:  # noqa: A002
        self.bodies.append(dict(json or {}))
        return _Resp({"job_id": "j1", "status": "queued"})


def test_needs_names_reach_the_working_model_in_the_task_text() -> None:
    client = _Capture()
    bridge = JarvisMcpBridge(client=client, lang="ko")
    asyncio.run(bridge.call("sonjari_task", {"task": "에이전트 조사", "needs": ["미리 색인 여부", "출처"]}))
    body = client.bodies[-1]
    assert body["needs"] == ["미리 색인 여부", "출처"]
    assert body["prompt"].startswith("에이전트 조사")
    assert "미리 색인 여부" in body["prompt"] and "출처" in body["prompt"]
    assert "바깥 AI 가 맡긴 일 · 에이전트 조사" == body["display_prompt"], "화면에 보이는 제목은 사람이 쓴 그대로"


def test_without_needs_the_task_text_is_unchanged() -> None:
    client = _Capture()
    asyncio.run(JarvisMcpBridge(client=client, lang="ko").call("sonjari_task", {"task": "에이전트 조사"}))
    assert client.bodies[-1]["prompt"] == "에이전트 조사"


def test_english_connection_names_the_items_in_english() -> None:
    client = _Capture()
    asyncio.run(JarvisMcpBridge(client=client, lang="en").call("sonjari_task", {"task": "survey", "needs": ["source"]}))
    assert "exact names" in client.bodies[-1]["prompt"] and "source" in client.bodies[-1]["prompt"]
