"""대화 기록 예산은 **서버가 알려 준 실제 프롬프트 크기**를 따라 좁아진다 (2026-10-11).

16GB 조건(작은 27B 판 · 창 49,152)으로 가격 조사 스킬팩을 세 판 돌렸다:

    91e91957  세 가게를 다 읽고 엑셀을 못 만들고 멈춤 — 마지막 호출이 49,151토큰에서 끊겼다(쓸 자리 1,585토큰)
    f6ba307d  엑셀까지 만듦
    2689e68c  8걸음에서 죽음 — 프롬프트가 창을 넘자 Ollama 가 앞쪽 메시지를 잘라 냈고, 시킨 말이 사라져 대화 틀이 거절(500)

뿌리는 하나다. 예산은 「창의 70% × 토큰당 2자」로 잡는데, 그 판의 고정 앞부분(지침 + 도구 목록)이 **28,201토큰**이었고
(Ollama 기록의 첫 호출) 읽은 글은 토큰당 2자보다 촘촘했다. 글자로 센 예산은 안 넘었는데 토큰으로는 창을 넘었다.

도구 목록이 몇 토큰인지, 이 글이 토큰당 몇 자인지를 미리 맞히지 않는다. 서버가 호출마다 돌려주는 프롬프트 토큰 수
(`prompt_eval_count` — 그날 큰 호출 16번의 합 618,418 이 Ollama 기록의 「대화 전체」 합과 맞았다: 전체 크기다)를 받아
**다음 호출**의 예산을 좁힌다. 창이 넉넉하면 아무것도 안 바뀐다.

이 시험이 **못** 지키는 것: 좁힌 뒤에 답의 질이 어떤가. 접힌 페이지의 값을 모델이 기억하는지는 실제 판으로만 볼 수 있다.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.transcript import transcript_chars
from alture_jarvis.transcript_policy import chat_transcript_budget, window_fitted_budget

_WINDOW = 49_152          # 16GB 조건의 창
_OUTPUT_ROOM = 8_192      # 모델이 쓸 자리(`_CHAT_OUTPUT_RESERVE_TOKENS`)
_SEEN_PROMPT = 47_566     # 91e91957 의 끊긴 호출: 49,151 − 쓴 1,585


# ── 셈 ────────────────────────────────────────────────────────────────────────

def test_without_a_measurement_the_budget_is_untouched() -> None:
    assert window_fitted_budget(57_344, num_ctx=_WINDOW, sent_chars=0, prompt_tokens=0) == 57_344
    assert window_fitted_budget(57_344, num_ctx=_WINDOW, sent_chars=50_000, prompt_tokens=0) == 57_344
    assert window_fitted_budget(57_344, num_ctx=0, sent_chars=50_000, prompt_tokens=40_000) == 57_344


def test_a_prompt_that_ate_the_output_room_shrinks_the_next_budget() -> None:
    fitted = window_fitted_budget(57_344, num_ctx=_WINDOW, sent_chars=50_000, prompt_tokens=_SEEN_PROMPT)

    over = _SEEN_PROMPT - (_WINDOW - _OUTPUT_ROOM)          # 쓸 자리를 6,606토큰 먹었다
    assert fitted < 50_000, "지난번에 보낸 것보다 적게 보내야 한다"
    assert 50_000 - fitted >= over, "넘친 토큰마다 적어도 한 글자는 덜어 낸다(한글 본문은 토큰당 1.7자쯤이다)"
    assert fitted > 30_000, "한 번에 반 토막 내지 않는다 — 넘친 만큼만 던다"


def test_a_roomy_window_changes_nothing() -> None:
    """운영 조건(창 131,072 · 프롬프트 3만 8천 토큰쯤)에서는 예전 그대로다."""
    budget, _ = chat_transcript_budget(131_072, "big-27b")
    assert window_fitted_budget(budget, num_ctx=131_072, sent_chars=70_000, prompt_tokens=38_000) == budget


def test_room_left_lets_the_budget_grow_only_as_far_as_the_window() -> None:
    """자리가 남았으면 남은 만큼만 더 준다 — 원래 예산을 넘지는 않는다."""
    fitted = window_fitted_budget(57_344, num_ctx=_WINDOW, sent_chars=20_000, prompt_tokens=36_000)
    room = _WINDOW - _OUTPUT_ROOM - 36_000                   # 4,960토큰
    assert 20_000 < fitted <= 20_000 + room * 2
    assert window_fitted_budget(57_344, num_ctx=_WINDOW, sent_chars=20_000, prompt_tokens=10_000) == 57_344


def test_the_fitted_budget_is_never_zero_or_negative() -> None:
    assert window_fitted_budget(57_344, num_ctx=_WINDOW, sent_chars=5_000, prompt_tokens=90_000) >= 1


# ── 실제 호출 길 ───────────────────────────────────────────────────────────────

class _Model:
    """부를 때마다 「프롬프트가 이만큼이었다」를 돌려주는 가짜 서버."""

    def __init__(self, prompt_tokens: list[int]) -> None:
        self.sent: list[list[dict]] = []
        self.tools: list[Any] = []
        self._prompt_tokens = list(prompt_tokens)
        self.extra: dict[str, Any] = {}

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.sent.append([dict(item) for item in messages])
        self.tools.append(kwargs.get("tools"))
        tokens = self._prompt_tokens.pop(0) if self._prompt_tokens else 0
        return {"role": "assistant", "content": "다음 걸음", "_metrics": {"prompt_eval_count": tokens}, **self.extra}


_TOOLS = [{"type": "function", "function": {"name": "browser_extract", "description": "지금 페이지의 본문을 읽는다", "parameters": {}}}]


def _agent(tmp_path: Path, prompt_tokens: list[int]) -> tuple[BrowserAgent, _Model, JobStore]:
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
    )
    store = JobStore(tmp_path / "jarvis.db")
    model = _Model(prompt_tokens)
    tools = SimpleNamespace(names=set(), ollama_tools=[])
    agent = BrowserAgent(config, model, SimpleNamespace(), SimpleNamespace(status=lambda: {}), tools, store, EventBus())
    agent._window = lambda role: _WINDOW   # type: ignore[method-assign]
    return agent, model, store


def _page(index: int, chars: int = 8_000) -> list[dict[str, Any]]:
    """상품 페이지 하나를 읽은 걸음 — 부른 메시지와 그 결과."""
    body = json.dumps(
        {"ok": True, "result": {"action": "browser_extract", "url": f"https://shop{index}.example/item", "title": f"가게 {index}",
                                "text": f"가게 {index} 상품 " + "설명 " * (chars // 3)}},
        ensure_ascii=False,
    )
    return [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_extract", "arguments": {}}}]},
        {"role": "tool", "tool_name": "browser_extract", "content": body},
    ]


_TASK = "말한 상품을 가게마다 찾아 가격을 엑셀로 정리해 줘"


def _conversation(pages: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": "일하는 규칙."}, {"role": "user", "content": _TASK}]
    for index in range(pages):
        messages += _page(index)
    return messages


def _call(agent: BrowserAgent, messages: list[dict[str, Any]], job_id: str, tools: Any = _TOOLS) -> None:
    agent._model_message(messages, job_id=job_id, tools=tools, think=False)


def _fitted_records(tmp_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(tmp_path / "jarvis.db") as connection:
        rows = connection.execute(
            "select payload_json from audit_log where event = 'agent_transcript_fitted_to_window'"
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _job(store: JobStore) -> str:
    return store.create_job("chat", "가격 조사", {"prompt": _TASK, "origin": "mcp"})["id"]


def test_the_next_call_sends_less_after_the_server_reports_a_full_window(tmp_path: Path) -> None:
    agent, model, store = _agent(tmp_path, [_SEEN_PROMPT, 39_000])
    job = _job(store)
    messages = _conversation(5)
    default_budget, _ = chat_transcript_budget(_WINDOW, agent.config.model_for("chat"))
    assert transcript_chars(messages) < default_budget, "글자로 센 예산은 안 넘는 대화여야 한다 — 그날의 모양이다"

    _call(agent, messages, job)
    first = transcript_chars(model.sent[-1])
    assert first == transcript_chars(messages), "첫 호출은 재 본 것이 없어 그대로 보낸다"

    messages += _page(5, chars=1_200)
    _call(agent, messages, job)
    second = transcript_chars(model.sent[-1])

    assert second < first - (_SEEN_PROMPT - (_WINDOW - _OUTPUT_ROOM)), "쓸 자리를 먹은 만큼보다 더 덜어 내고 보낸다"
    assert any(item.get("role") == "user" and _TASK in str(item.get("content")) for item in model.sent[-1]), "시킨 말은 남는다"
    assert json.loads(model.sent[-1][-1]["content"])["result"]["url"] == "https://shop5.example/item", "방금 읽은 것은 원문으로 남는다"
    fitted = _fitted_records(tmp_path)
    assert len(fitted) == 1, "좁힌 사실은 기록에 남는다(숫자만)"
    assert fitted[0]["prompt_tokens"] == _SEEN_PROMPT and fitted[0]["window"] == _WINDOW
    assert fitted[0]["fitted_chars"] < fitted[0]["budget_chars"]


def test_a_roomy_report_keeps_sending_everything(tmp_path: Path) -> None:
    agent, model, store = _agent(tmp_path, [24_000, 25_000])
    job = _job(store)
    messages = _conversation(5)

    _call(agent, messages, job)
    first = model.sent[-1]
    messages += _page(5, chars=1_200)
    _call(agent, messages, job)

    assert model.sent[-1][:len(first)] == first, "자리가 남으면 앞쪽을 건드리지 않는다 — 서버가 다시 읽지 않는다"
    assert not _fitted_records(tmp_path)


def test_a_call_with_another_tool_list_does_not_borrow_the_measurement(tmp_path: Path) -> None:
    """도구 목록이 다르면 프롬프트 크기도 다르다 — 그 호출에는 다른 목록으로 잰 값을 대지 않는다."""
    agent, model, store = _agent(tmp_path, [_SEEN_PROMPT, 20_000, 39_000])
    job = _job(store)
    messages = _conversation(5)

    _call(agent, messages, job)                       # 도구 목록과 함께: 창이 찼다
    _call(agent, messages, job, tools=None)           # 도구 없이 부른 곁가지: 그대로 보낸다
    assert transcript_chars(model.sent[-1]) == transcript_chars(messages)

    _call(agent, messages, job)                       # 다시 도구 목록과 함께: 곁가지가 잰 2만 토큰에 속지 않는다
    assert transcript_chars(model.sent[-1]) < transcript_chars(messages)


def test_a_reply_from_a_second_inner_call_is_not_a_measurement(tmp_path: Path) -> None:
    """도구 없이 다시 받은 답(`_slow_content`)이 돌려준 토큰 수는 다른 프롬프트의 것이다 — 예산을 정하는 데 쓰지 않는다."""
    agent, model, store = _agent(tmp_path, [_SEEN_PROMPT, 39_000])
    model.extra = {"_slow_content": {"cut_at_chunks": 10}}
    job = _job(store)
    messages = _conversation(5)

    _call(agent, messages, job)
    _call(agent, messages, job)

    assert transcript_chars(model.sent[-1]) == transcript_chars(messages)


def test_a_new_job_starts_without_the_last_jobs_measurement(tmp_path: Path) -> None:
    agent, model, store = _agent(tmp_path, [_SEEN_PROMPT, 39_000])
    messages = _conversation(5)

    _call(agent, messages, _job(store))
    _call(agent, messages, _job(store))

    assert transcript_chars(model.sent[-1]) == transcript_chars(messages)
