"""정리를 **도구와 같이** 써 버리고 짧은 끝말만 남긴 판은 끝내기를 한 번 되돌린다 (2026-10-17).

레딧 r/AI_Agents 글(「에이전트는 일을 했는데 하네스가 답을 버렸다」)에 달린 댓글 둘이 같은 처방을 냈다 — 최종 답은 도구 호출이
없는 따로 된 메시지여야 하고, 아니면 하네스가 그 끝내기를 거절한다. 10-16 고침(`wrap_up_said`)은 탭 닫기와 같이 쓴 글만 건졌다.
다른 도구와 같이 쓰면 여전히 「위에서 정리한 대로…」 한 줄이 답이 됐다.

지키는 약속:
- 도구와 같이 쓴 가장 긴 글이 한 문장(200자)보다 길고 최종 답이 그 절반도 안 되면, 도구 없이 완전한 답을 다시 쓰게 한 번 돌려보낸다.
- 다시 쓴 답이 더 길 때만 바꾼다 — 아니면 원래 답 그대로.
- 도구와 같이 쓴 말이 한 문장뿐이거나 최종 답이 충분히 길면 돌려보내지 않는다.
- 판 기록에 도구와 같이 쓴 가장 긴 글의 길이 · 걸음과 되돌렸는지를 남긴다.
- 지시문에도 「최종 답은 도구 없이 따로」를 적는다.
"""

from __future__ import annotations

from alture_jarvis import narration, plan
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
    "가장 겹치는 쪽은 가상 에이전트 A 입니다. 내 PC 에서 돌고 브라우저를 직접 다룹니다. 다른 점은 행동마다 사람 승인을 거치는지입니다."
)
assert len(SUMMARY) >= 200
REWRITTEN = SUMMARY + "\n\n(다시 쓴 최종 답)"


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
    """검색 → (긴 글 + 검색 하나 더) → 짧은 끝말 → (되돌려 보내면) 다시 쓴 답."""

    def __init__(self, *, said: str, final: str, resend: str) -> None:
        self.calls = 0
        self.turns = [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_search", "arguments": {"query": "가상"}}}]},
            {"role": "assistant", "content": said, "tool_calls": [{"function": {"name": "browser_search", "arguments": {"query": "가상 B"}}}]},
            {"role": "assistant", "content": final},
            {"role": "assistant", "content": resend},
        ]

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        return self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]


def _run(tmp_path, model):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "j.db")
    events = EventBus()
    from test_agent import FakeBrowser

    agent = BrowserAgent(config, model, _Gateway(), FakeBrowser(), _Tools(), store, events)
    job = store.create_job("chat", "agent", {"prompt": "둘 중 어느 쪽이 우리와 더 겹치나 찾아봐"})
    store.claim_next()
    result = agent.run("둘 중 어느 쪽이 우리와 더 겹치나 찾아봐", job_id=job["id"], origin="chat")
    return result, [event.event for event in events.get_since(0)]


def test_a_short_finish_after_a_long_text_with_tools_is_sent_back(tmp_path) -> None:
    result, events = _run(tmp_path, _Model(said=SUMMARY, final="위에서 정리한 대로입니다.", resend=REWRITTEN))

    assert "(다시 쓴 최종 답)" in result.answer
    assert "agent_final_sent_back" in events
    sent = result.verification["final_sent_back"]
    assert sent["reason"] == "shorter_than_said_with_tools" and sent["used"] is True
    assert result.verification["said_with_tools"] == {"chars": len(SUMMARY), "step": 2}


def test_the_original_stays_when_the_rewrite_is_not_longer(tmp_path) -> None:
    result, events = _run(tmp_path, _Model(said=SUMMARY, final="위에서 정리한 대로입니다.", resend="네."))

    assert result.answer.startswith("위에서 정리한 대로입니다.")
    assert "agent_final_sent_back" in events
    assert result.verification["final_sent_back"]["used"] is False


def test_one_sentence_with_tools_does_not_send_the_finish_back(tmp_path) -> None:
    result, events = _run(tmp_path, _Model(said="B 쪽도 찾아보겠습니다.", final="정리: " + "가" * 60, resend=REWRITTEN))

    assert result.answer.startswith("정리: ")
    assert "agent_final_sent_back" not in events
    assert result.verification["final_sent_back"] == {}


def test_a_full_final_answer_is_not_sent_back(tmp_path) -> None:
    result, events = _run(tmp_path, _Model(said=SUMMARY, final=SUMMARY + "\n\n덧붙여 둘 다 2026년 판입니다.", resend=REWRITTEN))

    assert "2026년 판입니다." in result.answer
    assert "(다시 쓴 최종 답)" not in result.answer
    assert "agent_final_sent_back" not in events


def test_the_instruction_says_the_final_answer_goes_alone() -> None:
    assert "최종 답" in narration.NARRATION_INSTRUCTION and "도구를 부르지 말고" in narration.NARRATION_INSTRUCTION
    assert "final answer" in narration.NARRATION_INSTRUCTION_EN and "call no tool" in narration.NARRATION_INSTRUCTION_EN


def test_five_posts_spelled_out_are_five_to_read() -> None:
    """운영 판 9f8645bd — 「다섯 글」을 못 알아보고 「글마다 … 댓글 위쪽 세 개」의 3을 집어, 넷째 글에서 「목표 채움」으로 접혔다."""
    prompt = ("크롬에서 https://www.reddit.com/r/LLMDevs/top/?t=month 를 열고, 목록에서 아래 다섯 글을 찾아 하나씩 열어 읽어 줘. "
              "① 「가상 글 하나」 ② 「가상 글 둘」 ③ 「가상 글 셋」 ④ 「가상 글 넷」 ⑤ 「가상 글 다섯」. "
              "글마다: 제목 · 점수 · 댓글 수 · 본문 첫 세 문장 그대로 · 댓글 위쪽 세 개가 무엇을 말했는지를 정리해 줘.")
    counts = [req.target for req in plan.extract(prompt) if req.kind == "count"]
    assert counts == [5]


def test_hangul_file_and_letters_are_not_counts() -> None:
    """「한글 파일」이 「한(1) 글」로, 「세 글자」가 3으로 읽히면 안 된다(운영 요청 2,167개 대조에서 「한글 파일」 둘이 바뀌어 좁힘)."""
    assert [req for req in plan.extract("한글 파일로 이력서를 정리해 줘") if req.kind == "count"] == []
    assert [req for req in plan.extract("제목을 세 글자로 줄여서 알려 줘") if req.kind == "count"] == []


def test_names_seen_on_screen_are_not_called_unread_anywhere() -> None:
    """운영 판 6570adff — 글쓰기 화면에서 「모든 플레어 보기」를 눌러 본 이름에 「읽은 자료 어디에도 없습니다」가 붙었다.

    경고를 낼지는 그대로(이름 하나뿐인 항목은 구제하지 않는다). 말만 사실대로 — 화면에서 봤고, 따로 열지는 않았다.
    머리는 `⚠ **` 그대로여야 화면이 답 본문 밖(노란 줄)으로 옮긴다.
    """
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    bullets = "- **가상태그가**\n- **가상태그나**\n- **가상태그다**\n"
    messages = [
        {"role": "tool", "tool_name": "browser_extract", "content": "규칙 1 존중 규칙 2 주제"},
        {"role": "tool", "tool_name": "browser_snapshot", "content": "button 가상태그가 button 가상태그나 button 가상태그다"},
    ]
    note = BrowserAgent._listed_entity_grounding_check(bullets, messages)

    assert note.lstrip().startswith("⚠ **화면 목록에서 옮겨 적은 이름이 있습니다")
    assert "어디에도 없습니다" not in note


def test_names_seen_nowhere_still_get_the_strong_warning() -> None:
    """반대 방향 — 화면에도 없는 이름은 예전 그대로 「어디에도 없습니다」."""
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    bullets = "- **가상태그가**\n- **가상태그나**\n- **가상태그다**\n"
    messages = [
        {"role": "tool", "tool_name": "browser_extract", "content": "규칙 1 존중 규칙 2 주제"},
        {"role": "tool", "tool_name": "browser_snapshot", "content": "button 가상태그가 button 다른것"},
    ]
    note = BrowserAgent._listed_entity_grounding_check(bullets, messages)

    assert "읽지 않고 적은 것이 있습니다" in note and "어디에도 없습니다" in note
