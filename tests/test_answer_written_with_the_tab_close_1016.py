"""모델이 **답을 탭 닫기와 같이 써 버린** 판에서 그 답을 잃지 않는다 (2026-10-16).

대표 화면(4d808ace): 「헤르메스와 오픈클로 중 어느 쪽이 우리와 가장 겹치나」 — 검색 둘 · 두 페이지를 읽은 뒤 모델이 정리를 쓰며
같은 응답에서 `browser_close` 를 불렀다. 도구를 부르며 한 말은 400자로 잘려 「하는 말」로만 화면에 나가고 답에는 안 들어가서,
마지막 답은 「브라우저 닫았습니다. 위에서 정리한 대로, OpenClaw 가 가장 비슷…」 한 줄이었다(대표: 「답변이 너무 대충」).
10-09 b5df5e5d 도 같았다 — 「브라우저 닫았어요. 오늘 뉴스 정리 끝!」. 9월부터 탭 닫기로 끝난 판 121개 중 2개.

지키는 약속:
- 부른 도구가 마무리 도구(탭 닫기)뿐이고 같이 쓴 글이 한 문장보다 길면, 그 글을 답 후보로 쥔다. 마지막 답이 그보다 짧으면
  후보를 답으로 낸다.
- 읽기 · 검색과 같이 쓴 말은 여전히 답이 아니다(그 말은 그 도구의 결과를 보기 **전에** 쓴 것이다).
- 마지막 답이 더 길면 마지막 답 그대로.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

SUMMARY = (
    "두 페이지를 읽고 정리했습니다.\n\n"
    "| 항목 | 가상 에이전트 A | 가상 에이전트 B |\n|---|---|---|\n"
    "| 도는 곳 | 내 PC | 서버 |\n| 브라우저 | 직접 다룸 | 없음 |\n"
    "| 문서 · 파일 | 엑셀 · 워드 | 없음 |\n| 승인 | 없음 | 없음 |\n\n"
    "가장 겹치는 쪽은 가상 에이전트 A 입니다 — 내 PC 에서 돌고 브라우저를 직접 다룹니다. 다른 점은 행동마다 사람 승인을 거치는지입니다."
)
assert len(SUMMARY) >= 200  # 「하는 말」 한 문장보다 긴 정리


class _Tools:
    names = {"browser_search", "browser_close"}
    ollama_tools = [
        {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}
        for name in ("browser_search", "browser_close")
    ]


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        if name == "browser_close":
            return ToolResult(True, name, result={"browser_closed": True})
        return ToolResult(True, name, result={"url": "https://example.test/a", "title": "가상 문서", "text": "가상 에이전트 A 는 내 PC 에서 돈다"})


class _Model:
    """검색 → (정리 글 + 탭 닫기) → 짧은 마무리 한 줄."""

    def __init__(self, *, with_close: str, final: str, close_tool: str = "browser_close") -> None:
        self.turns = [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_search", "arguments": {"query": "가상"}}}]},
            {"role": "assistant", "content": with_close, "tool_calls": [{"function": {"name": close_tool, "arguments": {}}}]},
            {"role": "assistant", "content": final},
        ]

    def chat_messages(self, messages, **kwargs):
        return self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]


def _run(tmp_path, model) -> tuple[str, list[str]]:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "j.db")
    events = EventBus()
    from test_agent import FakeBrowser

    agent = BrowserAgent(config, model, _Gateway(), FakeBrowser(), _Tools(), store, events)
    job = store.create_job("chat", "agent", {"prompt": "둘 중 어느 쪽이 우리와 더 겹치나 찾아봐"})
    store.claim_next()
    result = agent.run("둘 중 어느 쪽이 우리와 더 겹치나 찾아봐", job_id=job["id"], origin="chat")
    return result.answer, [event.event for event in events.get_since(0)]


def test_the_summary_written_with_the_tab_close_becomes_the_answer(tmp_path) -> None:
    answer, events = _run(tmp_path, _Model(with_close=SUMMARY, final="브라우저 닫았습니다. 위에서 정리한 대로입니다."))

    assert "가장 겹치는 쪽은 가상 에이전트 A" in answer
    assert "| 도는 곳 |" in answer
    assert "agent_answer_from_wrap_up" in events


def test_a_one_sentence_remark_with_the_close_is_not_an_answer(tmp_path) -> None:
    answer, events = _run(tmp_path, _Model(with_close="다 읽었으니 탭을 닫겠습니다.", final="정리: " + "가" * 60))

    assert answer.startswith("정리: ")
    assert "agent_answer_from_wrap_up" not in events


def test_a_longer_final_answer_wins(tmp_path) -> None:
    final = SUMMARY + "\n\n덧붙여, 두 문서 모두 2026년 판입니다."
    answer, events = _run(tmp_path, _Model(with_close=SUMMARY, final=final))

    assert answer.rstrip().endswith("2026년 판입니다.") or "2026년 판입니다." in answer
    assert "agent_answer_from_wrap_up" not in events


def test_words_said_with_a_reading_tool_are_still_not_the_answer(tmp_path) -> None:
    answer, events = _run(tmp_path, _Model(with_close=SUMMARY, final="짧은 마무리.", close_tool="browser_search"))

    assert "가장 겹치는 쪽은" not in answer
    assert "agent_answer_from_wrap_up" not in events
