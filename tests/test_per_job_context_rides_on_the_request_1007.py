"""판마다 바뀌는 것은 시스템 메시지가 아니라 **요청 메시지 앞**에 싣는다 (2026-10-07 코딩 사다리 L6 기준선).

세 판 모두 첫 모델 호출이 프롬프트 전체(17,121토큰)를 6.3~6.5초 동안 다시 읽었다. 앞 14,146토큰은 앞 판과 글자까지
같았는데, 시각·목표가 시스템 글의 **끝**에 있었다. 운영 모델은 서버가 캐시를 「체크포인트」 자리로만 되돌리고, 서버는
그 자리를 마지막 사용자 메시지가 시작하는 곳과 프롬프트 끝 근처에만 만든다 — 갈라진 자리보다 앞에는 하나도 없었다.

같은 서버에 직접 잰 값: 시각 줄을 요청 메시지 앞으로 옮기면 새 판이 83토큰·0.12초만 다시 읽는다.
"""
from __future__ import annotations

import copy

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

SECTIONS = [
    ("voice", "말투 글", False),
    ("contract", "계약 글", False),
    ("user_context", "사용자 맥락:\n지난번에 표로 달라고 했다", True),
    ("skill_note", "스킬 메모: 표 만들기", False),
    ("thinking_card", "사고 도구 목록", True),
    ("repo_card", "저장소 지도: pipeline.py", True),
    ("now", "현재 한국 시각 (KST)\n- 시각: 18:32", False),
]
PER_JOB = frozenset({"user_context", "skill_note", "repo_card", "now"})


def test_the_stable_part_holds_nothing_that_changes_between_jobs() -> None:
    from alture_jarvis.transcript import fit_system_split

    stable, job, dropped = fit_system_split(SECTIONS, budget=10_000, per_job=PER_JOB)

    assert stable == "말투 글\n\n계약 글\n\n사고 도구 목록"
    assert job.split("\n\n") == [
        "사용자 맥락:\n지난번에 표로 달라고 했다", "스킬 메모: 표 만들기", "저장소 지도: pipeline.py",
        "현재 한국 시각 (KST)\n- 시각: 18:32",
    ]
    assert dropped == []


def test_what_gets_dropped_is_chosen_exactly_as_before() -> None:
    """어느 메시지에 실리는지만 바뀐다 — 자리가 모자랄 때 무엇을 버리는지는 목록 순서 그대로다."""
    from alture_jarvis.transcript import fit_system, fit_system_split

    fixed = sum(len(text) + 2 for _, text, droppable in SECTIONS if not droppable)
    budget = fixed + len(SECTIONS[2][1]) + 2 + len(SECTIONS[4][1]) + 2      # 사용자 맥락·사고 도구까지만 들어간다

    whole, dropped_before = fit_system(SECTIONS, budget=budget)
    stable, job, dropped = fit_system_split(SECTIONS, budget=budget, per_job=PER_JOB)

    assert dropped == dropped_before == ["repo_card"]
    assert "저장소 지도" not in stable + job
    assert "자리가 모자라 뺀 것: repo_card" in job, "빠졌다는 알림은 판마다 달라질 수 있어 이번 판 글에 싣는다"
    assert "자리가 모자라" not in stable
    assert sorted((stable + "\n\n" + job).split("\n\n")) == sorted(whole.split("\n\n"))


def test_the_request_message_carries_the_context_first_and_the_request_last() -> None:
    from alture_jarvis.transcript import JOB_CONTEXT_CLOSE, JOB_CONTEXT_OPEN, with_job_context

    content = with_job_context("현재 한국 시각 (KST)\n- 시각: 18:32", "현재 사용자 목표:\n실패하는 시험을 고쳐줘")

    assert content.startswith(JOB_CONTEXT_OPEN + "\n현재 한국 시각")
    assert content.endswith(JOB_CONTEXT_CLOSE + "\n\n현재 사용자 목표:\n실패하는 시험을 고쳐줘")
    assert with_job_context("  ", "요청") == "요청"


def test_a_late_note_for_this_job_lands_inside_the_context_not_in_the_system_message() -> None:
    from alture_jarvis.transcript import JOB_CONTEXT_CLOSE, add_job_context, with_job_context

    messages = [
        {"role": "system", "content": "고정 글"},
        {"role": "user", "content": "지난 요청"},
        {"role": "assistant", "content": "지난 답"},
        {"role": "user", "content": with_job_context("시각 줄", "현재 사용자 목표:\n엑셀로 정리해줘")},
    ]

    assert add_job_context(messages, "[이 대화에서 이미 한 조사] 3곳을 읽었다") is True

    assert messages[0]["content"] == "고정 글"
    head, _, tail = messages[3]["content"].partition(JOB_CONTEXT_CLOSE)
    assert head.rstrip().endswith("[이 대화에서 이미 한 조사] 3곳을 읽었다")
    assert tail == "\n\n현재 사용자 목표:\n엑셀로 정리해줘"
    assert add_job_context([{"role": "system", "content": "고정 글"}, {"role": "user", "content": "맥락 없는 요청"}], "x") is False


def test_a_long_context_does_not_eat_the_end_of_the_request() -> None:
    from alture_jarvis.transcript import bounded, with_job_context

    request = "현재 사용자 목표:\n" + "가" * 5_000 + " 끝말"
    messages = [
        {"role": "system", "content": "고정 글"},
        {"role": "user", "content": with_job_context("지" * 4_000, request)},
    ]

    sent = bounded(messages, max_chars=100_000, tool_result_max=5_100)

    assert sent[1]["content"].endswith(" 끝말"), "요청의 상한은 요청 글에만 건다"


def test_the_request_survives_a_full_window_even_when_older_turns_come_first() -> None:
    """앞에 지난 대화가 있으면 이번 요청은 첫 사용자 메시지가 아니다. 목표가 거기에만 있으니 밀려나면 안 된다."""
    from alture_jarvis.transcript import bounded, with_job_context

    job = with_job_context("시각 줄", "현재 사용자 목표:\n이번 요청")
    messages = [
        {"role": "system", "content": "고정 글"},
        {"role": "user", "content": "지난 요청"},
        {"role": "assistant", "content": "지난 답"},
        {"role": "user", "content": job},
    ]
    for step in range(12):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_extract", "arguments": {}}}]})
        messages.append({"role": "tool", "tool_name": "browser_extract", "content": f"{step} " + "본문 " * 400})

    sent = bounded(messages, max_chars=6_000, tool_result_max=2_000)

    # ★ 2026-10-12: 밀려난 것(바로 앞 판의 답 · 읽은 화면)의 줄임이 이 요청의 맥락 안에 실린다 — 글자 그대로는 아니다.
    #   요청의 말과 원래 맥락은 그대로이고, 요청은 제자리에 하나만 있다.
    here = [i for i, item in enumerate(sent)
            if item.get("role") == "user" and str(item.get("content")).endswith("현재 사용자 목표:\n이번 요청")]
    assert len(here) == 1
    request = str(sent[here[0]]["content"])
    assert request.startswith("<이번-판-맥락>\n시각 줄")
    assert "[앞 답] 지난 답" in request, "바로 앞 판의 답은 밀려나도 요청 앞에 남는다"
    assert sent[0]["role"] == "system"
    last_tool = max(i for i, item in enumerate(sent) if item.get("role") == "tool")
    assert here[0] < last_tool, "요청은 제 순서(도구 걸음들 앞)에 남는다"
    assert len(sent) < len(messages), "창이 모자라 오래된 것이 빠진 판이어야 이 시험이 뜻이 있다"


class _Tools:
    names = {"browser_search", "browser_read"}
    ollama_tools = [{"type": "function", "function": {"name": "browser_search", "description": "search",
                                                       "parameters": {"type": "object", "properties": {}}}}]


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        return ToolResult(True, name, result={"url": "https://example.test/result", "title": "결과", "text": "근거"})


class _Browser:
    def status(self):
        return {"started": True}


class _Model:
    def __init__(self) -> None:
        self.first_calls: list[list[dict]] = []
        self._calls = 0

    def chat_messages(self, messages, **kwargs):
        self._calls += 1
        if self._calls % 2 == 1:
            self.first_calls.append(copy.deepcopy(list(messages)))
            return {"role": "assistant", "content": "",
                    "tool_calls": [{"function": {"name": "browser_search", "arguments": {"query": "x"}}}]}
        return {"role": "assistant", "content": "확인한 근거를 바탕으로 답변합니다."}


def test_two_jobs_minutes_apart_send_the_same_system_message(tmp_path, monkeypatch) -> None:
    from alture_jarvis import agent as agent_module

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    model = _Model()
    runner = agent_module.BrowserAgent(config, model, _Gateway(), _Browser(), _Tools(), store, EventBus())

    for minute, prompt in (("18:32", "로컬 모델 소식을 검색해줘"), ("18:34", "오늘 날씨를 검색해줘")):
        monkeypatch.setattr(agent_module, "now_line_ko", lambda minute=minute: f"현재 한국 시각 (KST)\n- 시각: {minute}")
        job = store.create_job("chat", "agent", {"prompt": prompt})
        store.claim_next()
        runner.run(prompt, job_id=job["id"], origin="chat", system_context="표는 세로로 길게 달라고 했다")

    first, second = model.first_calls
    assert first[0]["role"] == second[0]["role"] == "system"
    assert first[0]["content"] == second[0]["content"], "같은 모드의 판끼리 시스템 글은 글자까지 같아야 앞머리 캐시가 산다"
    from alture_jarvis.transcript import JOB_CONTEXT_OPEN

    for sent, minute, prompt in ((first, "18:32", "로컬 모델 소식을 검색해줘"), (second, "18:34", "오늘 날씨를 검색해줘")):
        assert "현재 한국 시각" not in sent[0]["content"] and prompt not in sent[0]["content"]
        assert "표는 세로로 길게 달라고 했다" in sent[0]["content"], "프로필은 판이 바뀌어도 같은 글이다 — 시스템 쪽에 남는다"
        request = next(item["content"] for item in sent if item["role"] == "user")
        assert request.startswith(JOB_CONTEXT_OPEN)
        assert "표는 세로로 길게 달라고 했다" not in request
        assert f"- 시각: {minute}" in request
        assert request.endswith("현재 사용자 목표:\n" + prompt)


def test_the_sections_that_move_are_named_in_one_place() -> None:
    from alture_jarvis import agent as agent_module

    assert agent_module._PER_JOB_SECTIONS == frozenset({"skill_note", "repo_card", "now"})
