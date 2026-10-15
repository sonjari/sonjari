from __future__ import annotations

import time

import pytest

from alture_jarvis.agent import (
    BrowserAgent,
    _code_text_tool_call,
    _completion_state,
    _model_answer_stop_reason,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ApprovalRequired, ContinuationRequired, JobStore
from alture_jarvis.models import JobStatus, RiskLevel, ToolResult
from alture_jarvis.plan import Requirement
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec


class FakeBrowser:
    def status(self):
        return {"started": True}


class FakeTools:
    names = {"browser_search", "browser_read"}
    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": "browser_search",
                "description": "search",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


class FakeGateway:
    def execute(self, name, arguments, *, job_id=""):
        assert job_id
        return ToolResult(
            True,
            name,
            result={"url": "https://example.test/result", "title": "검증 결과", "text": "근거"},
        )


class FakeOllama:
    def __init__(self):
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "browser_search",
                            "arguments": {"query": "로컬 JARVIS"},
                        }
                    }
                ],
            }
        assert any(item.get("role") == "tool" for item in messages)
        return {"role": "assistant", "content": "확인한 근거를 바탕으로 답변합니다."}


def _agent(tmp_path):
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    ollama = FakeOllama()
    agent = BrowserAgent(
        config,
        ollama,
        FakeGateway(),
        FakeBrowser(),
        FakeTools(),
        store,
        events,
    )
    return agent, store, events, ollama


def test_browser_intent_and_followup_are_detected(tmp_path) -> None:
    agent, _, _, _ = _agent(tmp_path)

    assert agent.should_handle("브라우저에서 로컬 AI를 찾아봐") is True
    assert agent.should_handle("그중 두 번째 결과를 더 읽어줘") is True
    assert agent.should_handle("안녕 자비스") is False


def test_agent_runs_tool_then_verifies_result(tmp_path) -> None:
    agent, store, events, ollama = _agent(tmp_path)
    job = store.create_job("chat", "agent", {"prompt": "검색해줘"})
    store.claim_next()

    result = agent.run("검색해줘", job_id=job["id"], origin="chat")

    assert result.answer.startswith("확인한 근거")
    assert result.verification["verified"] is True
    assert result.verification["urls"] == ["https://example.test/result"]
    assert result.verification["stop_reason"] == "model_answered"
    # ★ 2026-08-21: 이 판의 프롬프트는 "검색해줘"다 — **일을 시킨 것**인데 대조할
    #   요구(개수·사이트·행위)를 하나도 못 뽑았다. 예전에는 그것을 `answered` 로
    #   묶어 성공으로 셌는데, 이제 「원래 요구가 없는 대화」와 갈라 `unmeasured`
    #   (성공도 실패도 아닌 **모름**)로 둔다.
    assert result.verification["completion_state"] == "unmeasured"
    assert ollama.calls == 2
    event_names = [event.event for event in events.get_since(0)]
    assert event_names[0] == "agent_started"
    assert "agent_progress" in event_names
    assert event_names[-1] == "agent_finished"


def test_coding_role_refuses_an_answer_until_sandbox_run_succeeds(tmp_path) -> None:
    class CodingTools:
        names = {"sandbox_run"}
        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": "sandbox_run",
                    "description": "run code",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_open",
                    "description": "unrelated browser tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    class CodingGateway:
        def execute(self, name, arguments, *, job_id=""):
            assert name == "sandbox_run" and job_id
            output = tmp_path / "prime_count.py"
            output.write_text("print(168)\n", encoding="utf-8")
            return ToolResult(
                True,
                name,
                result={
                    "action": "sandbox_run",
                    "stdout": "168",
                    "exit_code": 0,
                    "output_path": str(output),
                    "verified": True,
                },
            )

    class CodingOllama:
        def __init__(self) -> None:
            self.calls = 0
            self.roles: list[str] = []
            self.thinking: list[bool] = []
            self.inference_profiles: list[str] = []
            self.tool_names: list[set[str]] = []

        def chat_messages(self, messages, **kwargs):
            self.calls += 1
            self.roles.append(str(kwargs.get("role") or "chat"))
            self.thinking.append(bool(kwargs.get("think")))
            self.inference_profiles.append(str(kwargs.get("inference_profile") or ""))
            self.tool_names.append(
                {
                    str((tool.get("function") or {}).get("name") or "")
                    for tool in kwargs.get("tools") or []
                }
            )
            if self.calls == 1:
                return {"role": "assistant", "content": "코드는 다음과 같습니다."}
            if self.calls == 2:
                assert any("sandbox_run" in str(item.get("content")) for item in messages)
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "sandbox_run",
                                "arguments": {"code": "print(168)"},
                            }
                        }
                    ],
                }
            return {"role": "assistant", "content": "실행 결과 168을 확인했습니다."}

    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        agent_stream_enabled=False,
    )
    store = JobStore(tmp_path / "jarvis.db")
    model = CodingOllama()
    agent = BrowserAgent(
        config,
        model,
        CodingGateway(),
        FakeBrowser(),
        CodingTools(),
        store,
        EventBus(),
    )
    job = store.create_job("chat", "agent", {"prompt": "소수 계산 코드를 짜줘"})
    store.claim_next()

    result = agent.run(
        "소수 계산 코드를 짜줘",
        job_id=job["id"],
        origin="chat",
        model_role="code",
        require_sandbox=True,
    )

    assert result.answer == "실행 결과 168을 확인했습니다."
    assert [step["tool"] for step in result.steps] == ["sandbox_run"]
    assert model.roles == ["code", "code", "code"]
    assert model.thinking == [True, True, True]
    assert model.inference_profiles == ["medium", "medium", "medium"]
    assert model.tool_names == [{"sandbox_run"}] * 3


def test_code_pushback_survives_a_model_call_that_crosses_the_time_lease(tmp_path) -> None:
    class CodingTools:
        names = {"sandbox_run"}
        ollama_tools = [{
            "type": "function",
            "function": {
                "name": "sandbox_run", "description": "run code",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

    class CodingGateway:
        def execute(self, name, arguments, *, job_id=""):
            return ToolResult(True, name, result={
                "action": "sandbox_run", "stdout": "ok", "exit_code": 0,
                "output_path": str(tmp_path / "fix.py"), "verified": True,
            })

    class SlowFirstAnswer:
        def __init__(self) -> None:
            self.calls = 0

        def chat_messages(self, messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                time.sleep(1.05)
                return {"role": "assistant", "content": "Here is an explanation only."}
            if self.calls == 2:
                assert any("local_run_project_command" in str(row.get("content")) for row in messages)
                return {"role": "assistant", "content": "", "tool_calls": [{
                    "function": {"name": "sandbox_run", "arguments": {"code": "print('ok')"}},
                }]}
            return {"role": "assistant", "content": "Implemented and verified."}

    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
        agent_autonomous_lease_sec=1, ollama_max_tool_steps=2,
    )
    store = JobStore(tmp_path / "jarvis.db")
    model = SlowFirstAnswer()
    agent = BrowserAgent(
        config, model, CodingGateway(), FakeBrowser(), CodingTools(), store, EventBus(),
    )
    job = store.create_job("chat", "code", {"prompt": "implement it"})
    store.claim_next()

    result = agent.run(
        "implement it", job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, auto_continue_budget=True,
    )

    assert result.answer == "Implemented and verified."
    assert [step["tool"] for step in result.steps] == ["sandbox_run"]
    assert model.calls == 3


def test_repository_code_gets_one_adversarial_review_after_public_verification(tmp_path) -> None:
    class RepositoryTools:
        names = {
            "local_apply_edit", "local_index_codebase", "local_list_directory",
            "local_read_text_file", "local_write_file", "local_run_project_command",
        }
        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": name,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in names
        ]

        def authorize_code_workspace(self, job_id, root):
            assert job_id and root == str(tmp_path)

    class RepositoryGateway:
        def execute(self, name, arguments, *, job_id=""):
            assert job_id
            if name == "local_index_codebase":
                return ToolResult(True, name, result={
                    "path": str(tmp_path), "files": [], "query": "implement the fix",
                })
            if name == "local_list_directory":
                return ToolResult(True, name, result={"path": str(tmp_path), "entries": []})
            if name == "local_read_text_file":
                return ToolResult(True, name, result={
                    "action": "local_read_text_file", "path": str(tmp_path / "fix.py"),
                    "text": "fixed = False\n", "verified": True,
                })
            if name == "local_write_file":
                return ToolResult(True, name, result={
                    "action": "local_write_file",
                    "path": str(tmp_path / "fix.py"), "verified": True,
                })
            if name == "local_apply_edit":
                return ToolResult(True, name, result={
                    "action": "local_apply_edit",
                    "path": str(tmp_path / "fix.py"), "verified": True,
                })
            assert name == "local_run_project_command"
            return ToolResult(True, name, result={
                "action": "local_run_project_command",
                "command": "pytest -q", "exit_code": 0, "stdout": "3 passed",
                "verified": True,
            })

    class RepositoryModel:
        def __init__(self) -> None:
            self.calls = 0
            self.review_seen = False

        def chat_messages(self, messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"role": "assistant", "content": "", "tool_calls": [{
                    "function": {
                        "name": "local_read_text_file", "arguments": {"path": "fix.py"},
                    },
                }]}
            if self.calls == 2:
                return {"role": "assistant", "content": "", "tool_calls": [{
                    "function": {
                        "name": "local_write_file",
                        "arguments": {"path": "fix.py", "content": "fixed = True\n"},
                    },
                }]}
            if self.calls == 3:
                return {"role": "assistant", "content": "", "tool_calls": [{
                    "function": {
                        "name": "local_run_project_command",
                        "arguments": {"command": "pytest -q"},
                    },
                }]}
            if self.calls == 4:
                return {"role": "assistant", "content": "Implemented and verified."}
            self.review_seen = any(
                "adversarial" in str(item.get("content") or "").lower()
                or "적대적으로" in str(item.get("content") or "")
                for item in messages
            )
            if self.calls == 5:
                return {"role": "assistant", "content": "", "tool_calls": [{
                    "function": {
                        "name": "local_apply_edit",
                        "arguments": {"path": "fix.py", "old": "True", "new": "1"},
                    },
                }]}
            if self.calls == 6:
                return {"role": "assistant", "content": "", "tool_calls": [{
                    "function": {
                        "name": "local_run_project_command",
                        "arguments": {"command": "pytest -q"},
                    },
                }]}
            return {"role": "assistant", "content": "Reviewed boundaries; implementation is complete."}

    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    model = RepositoryModel()
    agent = BrowserAgent(
        config, model, RepositoryGateway(), FakeBrowser(), RepositoryTools(), store, events,
    )
    job = store.create_job("chat", "repo code", {"prompt": "implement the fix"})
    store.claim_next()

    result = agent.run(
        "implement the fix", job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True,
    )

    assert result.answer == "Reviewed boundaries; implementation is complete."
    assert model.calls == 7
    assert model.review_seen is True
    review_events = [
        event for event in events.get_since(0, limit=100)
        if event.event == "agent_code_review_requested"
    ]
    assert len(review_events) == 1
    assert [step["tool"] for step in result.steps].count("local_run_project_command") == 2


def test_code_role_recovers_only_an_exposed_json_tool_call() -> None:
    allowed = {"local_write_file", "sandbox_run"}
    recovered = _code_text_tool_call(
        {
            "content": (
                '{"name":"local_write_file","arguments":'
                '{"path":"check.py","content":"print(42)"}}'
            )
        },
        allowed,
    )
    assert recovered == {
        "function": {
            "name": "local_write_file",
            "arguments": {"path": "check.py", "content": "print(42)"},
        }
    }
    assert _code_text_tool_call(
        {"content": '{"name":"browser_open","arguments":{"url":"https://x"}}'},
        allowed,
    ) is None
    assert _code_text_tool_call(
        {"content": "설명 뒤에 JSON을 붙인 산문"}, allowed
    ) is None


def test_completion_status_distinguishes_unknown_plan_from_confirmed_shortfall() -> None:
    done = [(object(), True, "3개 읽음")]
    short = [(object(), False, "2개 읽음")]

    assert _model_answer_stop_reason([]) == "model_answered"
    assert _completion_state("model_answered", []) == "answered"
    assert _model_answer_stop_reason(done) == "model_done"
    assert _completion_state("model_done", done) == "complete"
    assert _completion_state("claude_code_completed", []) == "complete"
    assert _model_answer_stop_reason(short) == "model_stopped_early"
    assert _completion_state("model_stopped_early", short) == "partial"
    assert _completion_state("wrapped_up:no_progress", []) == "partial"


def _three_successful_reads() -> list[dict]:
    return [
        {
            "step": index,
            "tool": "browser_extract",
            "ok": True,
            "status": "",
            "error": "",
            "arguments": {},
            "evidence": {
                "url": f"https://www.saramin.co.kr/jobs/{index}",
                "title": f"공고 {index}",
                "char_count": 15000 + index,
            },
        }
        for index in range(1, 4)
    ]


def _three_read_plan() -> list[tuple[Requirement, bool, str]]:
    # 실제 요청(「사람인 공고 3개를 찾아줘」)에서 뽑히는 모양 그대로 — 읽어야 채워지는 개수다(`grounding_required`).
    # 2026-10-10 까지 이 본보기는 그 표시 없이 만들어져 있었다. 판정이 그 표시를 보게 되면서 맞췄다.
    return [(Requirement("count", "3개 이상 직접 열어 읽기", 3, grounding_required=True), True, "3개 읽음")]


def test_a_successful_third_read_cannot_be_reported_as_an_extraction_failure() -> None:
    conflict = BrowserAgent._answer_trace_conflict(
        "사람인 공고 3개를 찾아줘",
        "2개를 확인했습니다. 3번째 상세 정보 추출에 실패했습니다.",
        _three_successful_reads(),
        _three_read_plan(),
    )

    # 문구가 바뀌었다 — 이제 **몇 곳에서 받아 왔는지**를 같이 말한다(2026-09-09).
    # 사람이 읽을 때 「그래서 몇 개를 읽었다는 건데」가 바로 답이 되도록.
    assert "실제로 받아 왔는데" in conflict
    assert "3곳" in conflict


def test_an_unmet_plan_does_not_disable_the_contradiction_check() -> None:
    """★ 순환이었다 (2026-09-09 라이브).

    위시켓 판이 상세 4개를 정상으로 읽고도 "결과 목록이 나타나지 않는다"고 쓰고
    사용자에게 클릭을 부탁했다. 파일은 안 만들었다. 그래서:

        모델이 잘못 믿는다 -> 파일을 안 만든다 -> 계획 미충족 ->
        `plan_all_met` 이 False -> **그 잘못된 믿음을 잡을 검사가 꺼진다**

    판정에 필요한 것은 「본문을 실제로 받아 왔는가」 하나뿐이다. 계획이 덜 찼든
    다른 걸음이 실패했든 상관없다.

    ★ 2026-10-10 — 위 마지막 두 줄은 반만 남는다. 「받아 왔는가 하나뿐」으로 두었더니 운영 판에서 정직한 보고
      (「나머지는 못 읽었다」 · 「가격: 확인 불가」)가 129판 걸려 답을 다시 쓰게 했다. 이제 **읽기 요구**가 채워졌는지를
      본다 — 산출물 요구는 여전히 안 본다. 그래서 이 순환은 그대로 끊겨 있다: 파일을 안 만들어 계획이 덜 찼어도,
      읽으라는 개수를 다 읽었으면 판정은 선다. 이 시험의 계획을 그 판의 실제 계획(읽기 채움 · 파일 없음)으로 바꿨다.
    """
    steps = _three_successful_reads()
    plan = [
        (Requirement("count", "3개 이상 직접 열어 읽기", 3, grounding_required=True), True, "4개 읽음"),
        (Requirement("artifact", "실제 산출물 파일 만들기", ()), False, "열 수 있는 산출물 없음"),
    ]

    conflict = BrowserAgent._answer_trace_conflict(
        "위시켓에서 3개 조사해서 엑셀로",
        "결과 목록이 나타나지 않고 화면이 변화하지 않는 상태입니다. 직접 클릭해 주세요.",
        steps,
        plan,
    )

    assert "실제로 받아 왔는데" in conflict


def test_a_failed_read_step_means_the_claim_may_be_true() -> None:
    """읽으러 간 걸음이 실패한 판에서는 「못 읽었다」가 참말일 수 있다 — 거짓이라 하지 않는다.

    ★ 뒤집힌 시험이다. 2026-09-09 에는 이름이 `…does_not_excuse_a_false_claim` 이었고 반대를 지켰다:
      「무관한 걸음 하나가 실패했다고 거짓 주장을 봐줄 이유가 없다」. 그 판(e7b6d39f)에서는 맞는 말이었다 — 넷을 읽고도
      「결과 목록이 나타나지 않는다」고 썼고, 실패한 걸음은 없는 순위(37)를 연 것 하나였다.
      2026-10-10 에 운영 판 전체에 대 보니 반대쪽이 더 많았다: 읽기 요구를 다 채우고도 더 열려다 실패한 판들은
      「#4~#8 은 상세를 열지 못해 제외」처럼 **그 실패를 정직하게 적고 있었다.** 낱말로는 어느 쪽인지 가를 수 없다.
      잘못 걸면 정직한 답을 다시 쓰게 한다 — 그쪽이 더 비싸다고 봤다. 그래서 09-09 의 그 판은 이제 이 판정에 안 걸린다
      (계획 대조표의 「4개 읽음」은 그대로 답 아래 붙는다). 진 쪽을 지우지 않고 여기 적어 둔다.
    """
    steps = _three_successful_reads() + [
        {"tool": "browser_open_result", "ok": False, "error": "result_rank_not_found:37"}
    ]

    conflict = BrowserAgent._answer_trace_conflict(
        "사람인 공고 3개",
        "상세 정보 추출에 실패했습니다.",
        steps,
        _three_read_plan(),
    )

    assert "실제로 받아 왔는데" not in conflict


def test_nothing_read_means_no_accusation() -> None:
    """정말로 못 읽었으면 걸리지 않는다 — 오탐이 없는 이유다."""
    steps = [{"tool": "browser_open", "ok": True, "evidence": {"url": "https://x.test/"}}]

    conflict = BrowserAgent._answer_trace_conflict(
        "사람인 공고 3개", "상세 정보 추출에 실패했습니다.", steps, _three_read_plan())

    assert "실제로 받아 왔는데" not in conflict


def test_a_condition_shortfall_is_partial_not_a_fake_read_failure() -> None:
    steps = _three_successful_reads()
    plan = _three_read_plan()
    answer = "정규직 조건에 맞는 공고 2개만 확인했습니다."

    assert BrowserAgent._answer_trace_conflict("정규직 공고 3개", answer, steps, plan) == ""
    assert BrowserAgent._answer_reports_shortfall(answer, plan) is True


def test_shortfall_is_caught_when_the_count_trails_the_verb() -> None:
    """서술어가 숫자보다 **앞에** 오는 자백도 잡아야 한다.

    2026-08-18 라이브(크몽 조사): 6개를 시켰는데 실제로 검증한 것은 1건이었고, 답에도
    "…검증한 것은 위 1건입니다" 라고 분명히 적혀 있었다. 그런데 그 판은 `complete` 로
    기록됐다 — 당시 정규식이 (1) 단위를 `개` 만 받고 `건` 을 안 받았으며 (2) 숫자→서술어
    한 방향만 봤기 때문이다. 같은 날 다른 판이 잡힌 것은 우연히 "3개만 … 읽었습니다" 라고
    썼기 때문이지 탐지가 좋아서가 아니었다.
    """
    plan = _three_read_plan()

    # 서술어가 앞, 숫자가 뒤 + 단위가 '건'
    assert BrowserAgent._answer_reports_shortfall(
        "현재까지 완벽히 검증한 것은 위 1건입니다.", plan
    ) is True
    # 단위만 바꿔도 그대로 잡혀야 한다
    for unit in ("개", "건", "곳", "가지"):
        assert BrowserAgent._answer_reports_shortfall(
            f"확인한 것은 {1}{unit}뿐이고 나머지는 못 했습니다.", plan
        ) is True

    # 반대로 **다 끝낸 답**은 부족으로 읽으면 안 된다.
    assert BrowserAgent._answer_reports_shortfall(
        "요청하신 3개를 모두 확인했습니다.", plan
    ) is False
    assert BrowserAgent._answer_reports_shortfall(
        "검증한 결과 3건 모두 조건에 맞았습니다.", plan
    ) is False


def test_a_condition_conflict_requests_reconciliation() -> None:
    conflict = BrowserAgent._answer_trace_conflict(
        "정규직 공고 3개",
        "계약직 공고를 포함해 3개를 정리했습니다.",
        _three_successful_reads(),
        _three_read_plan(),
    )

    assert "정규직≠계약직" in conflict


def test_a_contradictory_final_draft_is_reconciled_before_it_is_painted(tmp_path) -> None:
    class _ReadTools:
        names = {"browser_read"}
        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": "browser_read",
                    "description": "read",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                    },
                },
            }
        ]

    class _ReadGateway:
        def execute(self, name, arguments, *, job_id=""):
            index = int(str(arguments["url"]).rsplit("/", 1)[-1])
            return ToolResult(
                True,
                name,
                result={
                    "action": "read",
                    "url": f"https://www.saramin.co.kr/jobs/{index}",
                    "title": f"정규직 공고 {index}",
                    "char_count": 12000 + index,
                    "text": f"정규직 공고 {index} 본문",
                },
            )

    class _DraftThenReconcile:
        def __init__(self) -> None:
            self.calls = 0

        def chat_messages(self, messages, **_kwargs):
            self.calls += 1
            if self.calls <= 3:
                index = self.calls
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "browser_read",
                                "arguments": {
                                    "url": f"https://www.saramin.co.kr/jobs/{index}"
                                },
                            }
                        }
                    ],
                }
            if self.calls == 4:
                return {
                    "role": "assistant",
                    "content": "2개를 확인했습니다. 세 번째 상세 정보 추출에 실패했습니다.",
                }
            assert "성공한 읽기" in str(messages[-1]["content"])
            return {
                "role": "assistant",
                "content": "정규직 공고 1, 정규직 공고 2, 정규직 공고 3을 모두 확인했습니다.",
            }

    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    model = _DraftThenReconcile()
    agent = BrowserAgent(
        config,
        model,
        _ReadGateway(),
        FakeBrowser(),
        _ReadTools(),
        store,
        events,
    )
    job = store.create_job("chat", "agent", {"prompt": "사람인 정규직 공고 3개를 찾아줘"})
    store.claim_next()

    result = agent.run("사람인 정규직 공고 3개를 찾아줘", job_id=job["id"], origin="chat")

    assert "공고 3" in result.answer
    assert "추출에 실패" not in result.answer
    assert result.verification["answer_reconciled"] is True
    assert result.verification["answer_conflict"] == ""
    assert result.verification["completion_state"] == "complete"
    event_names = [event.event for event in events.get_since(0)]
    assert event_names.count("agent_answer_reconciliation") == 1
    assert event_names.count("agent_answer_reset") == 1, "틀린 초안을 먼저 칠하면 답이 두 번 보인다"


def test_a_successful_browser_snapshot_still_parks_on_a_structural_captcha(tmp_path) -> None:
    """Google reCAPTCHA 데모는 snapshot 자체는 성공한다.

    성공을 '문 없음'으로 읽으면 모델이 답에 체크포인트라는 글자만 쓰고 실제 잡은
    completed가 된다. 구조적 문은 도구 성공 여부와 별개다.
    """
    agent, _, _, _ = _agent(tmp_path)

    class _QuietAttention:
        def check(self, **_kwargs):
            return None

    agent.attention = _QuietAttention()
    agent.browser.blocking_wall = lambda: {
        "known": True,
        "url": "https://www.google.com/recaptcha/api2/demo",
        "wall_url": "https://www.google.com/recaptcha/api2/demo",
        "password_fields": 0,
        "captcha": True,
    }
    steps: list[dict] = []
    messages: list[dict] = []

    gate = agent._record_observation(
        job_id="captcha-live-shape",
        name="browser_snapshot",
        arguments={"include_box": True},
        step_number=1,
        label="페이지 요소 확인",
        observation={
            "ok": True,
            "result": {
                "url": "https://www.google.com/recaptcha/api2/demo",
                "element_count": 7,
            },
        },
        steps=steps,
        messages=messages,
        evidence_urls=[],
        last_action_ids={},
        tool_numbers=set(),
            tool_numbers_body=set(),
    )

    assert gate == {
        "code": "bot_check",
        "url": "https://www.google.com/recaptcha/api2/demo",
    }


class GmailToolNames:
    names = {"google_gmail_prepare_send", "google_gmail_send"}
    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": "google_gmail_prepare_send",
                "description": "prepare",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "google_gmail_send",
                "description": "send",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


class RecordingGmailGateway:
    """Mirrors the real google_gmail_prepare_send/google_gmail_send contract
    closely enough to prove the agent loop corrects a bad action_id: prepare
    returns a real action_id in its result, send only "succeeds" (in this
    fake) so we can assert on what action_id it actually received."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name, arguments, *, job_id=""):
        assert job_id
        self.calls.append((name, dict(arguments)))
        if name == "google_gmail_prepare_send":
            return ToolResult(True, name, result={"action_id": "real-action-id-abc123", "preview": {}})
        if name == "google_gmail_send":
            return ToolResult(True, name, result={"message_id": "msg-1"})
        return ToolResult(True, name, result={})


class HallucinatingActionIdOllama:
    """Reproduces the observed real-world failure: the model calls prepare,
    receives the real action_id in the tool result, then fabricates a
    plausible-looking placeholder instead of copying it verbatim when
    calling the commit tool."""

    def __init__(self):
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "google_gmail_prepare_send",
                            "arguments": {"to": ["a@example.com"], "subject": "hi", "body_text": "hi"},
                        }
                    }
                ],
            }
        if self.calls == 2:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "google_gmail_send", "arguments": {"action_id": "prepare_gmail_test_12345"}}}
                ],
            }
        return {"role": "assistant", "content": "메일을 보냈습니다."}


def test_agent_corrects_hallucinated_action_id_before_commit(tmp_path) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    gateway = RecordingGmailGateway()
    agent = BrowserAgent(
        config,
        HallucinatingActionIdOllama(),
        gateway,
        FakeBrowser(),
        GmailToolNames(),
        store,
        events,
    )
    job = store.create_job("chat", "agent", {"prompt": "메일 보내줘"})
    store.claim_next()

    result = agent.run("메일 보내줘", job_id=job["id"], origin="chat")

    assert result.answer == "메일을 보냈습니다."
    send_call = next(args for name, args in gateway.calls if name == "google_gmail_send")
    assert send_call["action_id"] == "real-action-id-abc123"


class RealGmailHandlers:
    """Backs a real ToolGateway with handlers that mimic the actual
    action_id contract: prepare mints a fresh id, send only accepts that
    exact id."""

    def __init__(self):
        self.prepare_calls = 0
        self.send_calls = 0

    def prepare(self, arguments):
        self.prepare_calls += 1
        return {"action_id": "real-action-id-xyz", "preview": {}}

    def send(self, arguments):
        self.send_calls += 1
        assert arguments["action_id"] == "real-action-id-xyz"
        return {"message_id": "msg-1"}


def test_agent_approval_resume_replays_exact_call_without_replanning(tmp_path) -> None:
    """Reproduces the real-world bug: approving the popup must actually take
    effect. Before this fix, ApprovalRequired carried no checkpoint, so
    resuming re-ran the whole plan from scratch, calling prepare again and
    minting a brand-new action_id that could never match the nonce the user
    just approved -- every click just produced another dead approval popup."""

    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    gateway = ToolGateway(store, events)
    handlers = RealGmailHandlers()
    gateway.register(
        ToolSpec(
            name="google_gmail_prepare_send",
            description="",
            risk_level=RiskLevel.L1,
            handler=handlers.prepare,
        )
    )
    gateway.register(
        ToolSpec(
            name="google_gmail_send",
            description="",
            risk_level=RiskLevel.L2,
            handler=handlers.send,
        )
    )

    class ScriptedOllama:
        def __init__(self):
            self.calls = 0

        def chat_messages(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "google_gmail_prepare_send", "arguments": {"to": ["a@example.com"]}}}
                    ],
                }
            if self.calls == 2:
                # A fabricated id here should still be corrected by the
                # self-healing fix -- proving the two fixes compose.
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "google_gmail_send", "arguments": {"action_id": "fabricated-placeholder"}}}
                    ],
                }
            return {"role": "assistant", "content": "메일을 보냈습니다."}

    ollama = ScriptedOllama()
    agent = BrowserAgent(config, ollama, gateway, FakeBrowser(), GmailToolNames(), store, events)
    job = store.create_job("chat", "agent", {"prompt": "메일 보내줘"})
    store.claim_next()

    with pytest.raises(ApprovalRequired) as approval:
        agent.run("메일 보내줘", job_id=job["id"], origin="chat")

    assert handlers.prepare_calls == 1
    assert handlers.send_calls == 0
    checkpoint = store.get_agent_checkpoint(job["id"])
    assert checkpoint is not None
    assert checkpoint["pending_tool_call"]["name"] == "google_gmail_send"
    assert checkpoint["pending_tool_call"]["arguments"]["action_id"] == "real-action-id-xyz"

    store.set_status(job["id"], JobStatus.WAITING_APPROVAL)
    decision = gateway.decide(approval.value.nonce, True)
    assert decision["status"] == "approved"
    assert store.get_job(job["id"])["status"] == "queued"

    result = agent.run("메일 보내줘", job_id=job["id"], origin="chat")

    assert handlers.prepare_calls == 1, "resume must not re-run prepare and mint a second action_id"
    assert handlers.send_calls == 1
    assert result.answer == "메일을 보냈습니다."


def test_time_budget_wraps_up_instead_of_asking(tmp_path) -> None:
    """자율 예산까지 다 써도 **사람을 부르지 않고** 한 것까지로 정리한다 (2026-09-29).

    예전엔 읽은 것이 없으면 「기본 작업 시간을 다 썼습니다 — 3분 더?」 카드를 띄웠다.
    대표 판정: 브라우저는 원래 오래 걸리는데 그걸 묻는 것은 짜증이다. 더 갈 이유가 있으면
    자율 연장이 이미 늘려 줬으니, 여기 닿았다는 것은 정리할 때라는 뜻이다.
    `agent_autonomous_lease_sec=1` 로 자율 한도를 즉시 소진시켜 그 자리를 만든다.
    """

    class SlowOllama(FakeOllama):
        last_messages: list = []

        def chat_messages(self, messages, **kwargs):
            self.calls += 1
            self.last_messages = list(messages)
            if self.calls == 1:
                time.sleep(1.05)
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "browser_search", "arguments": {"query": "긴 조사"}}}
                    ],
                }
            return {"role": "assistant", "content": "현재까지 확인한 근거를 정리했습니다."}

    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=1,
        ollama_max_tool_steps=4,
        # 자율 한도를 즉시 소진시켜 "정말 못 가는" 자리를 만든다.
        agent_autonomous_lease_sec=1,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    agent = BrowserAgent(
        config,
        SlowOllama(),
        FakeGateway(),
        FakeBrowser(),
        FakeTools(),
        store,
        events,
    )
    job = store.create_job("chat", "long", {"prompt": "긴 조사"})
    store.claim_next()

    result = agent.run("긴 조사", job_id=job["id"], origin="chat")

    assert result.answer == "현재까지 확인한 근거를 정리했습니다."
    assert result.verification["stop_reason"].startswith("wrapped_up:time_budget:")
    assert store.get_agent_checkpoint(job["id"]) is None, "사람을 부르는 체크포인트가 남으면 안 된다"
    # 스스로 접은 판에 「사용자가 골랐다」고 적으면 그 말이 답에 샌다.
    assert not any("사용자가 여기까지 정리를 선택했다" in str(m.get("content")) for m in agent.ollama.last_messages), \
        "스스로 접은 판을 사용자가 고른 것처럼 적었다"


def test_code_budget_auto_continue_does_not_request_a_continuation_card(tmp_path) -> None:
    """Code mode renews time/step leases internally instead of pausing for a card."""

    class SlowOllama(FakeOllama):
        def chat_messages(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                time.sleep(1.05)
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "browser_search",
                                "arguments": {"query": f"코드 조사 {index}"},
                            }
                        }
                        for index in range(3)
                    ],
                }
            return {"role": "assistant", "content": "저장소 분석을 마쳤습니다."}

    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=1,
        ollama_max_tool_steps=2,
        # ★ 2026-09-20: Code 모드는 예산 칸이 따로다(`code_max_tool_steps`). 여기를 안 좁히면
        #   이 시험이 재려던 「부드러운 경계」가 아예 안 걸린다.
        code_max_tool_steps=2,
        code_autonomous_max_steps=8,
        agent_autonomous_lease_sec=1,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()
    agent = BrowserAgent(
        config,
        SlowOllama(),
        FakeGateway(),
        FakeBrowser(),
        FakeTools(),
        store,
        events,
    )
    job = store.create_job("chat", "code", {"prompt": "코드 조사"})
    store.claim_next()

    result = agent.run(
        "코드 조사",
        job_id=job["id"],
        origin="chat",
        model_role="code",
        auto_continue_budget=True,
    )

    assert result.answer == "저장소 분석을 마쳤습니다."
    assert len(result.steps) == 2, "tool execution stops exactly on the soft step boundary"
    assert store.get_agent_checkpoint(job["id"]) is None
    assert not [
        event for event in events.get_since(0, limit=100)
        if event.event == "agent_continuation_requested"
    ]
    continued = [
        event for event in events.get_since(0, limit=100)
        if event.event == "agent_continued_alone"
    ]
    assert continued
    assert continued[-1].payload["reason"].startswith("code_mode_uninterrupted:")


def test_a_cleared_human_gate_must_reobserve_before_answering(tmp_path) -> None:
    """재개됐는데 통과 전 화면을 되풀이하며 끝내는 라이브 회귀."""

    class ResumeOllama:
        def __init__(self) -> None:
            self.calls = 0

        def chat_messages(self, messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                assert any("HUMAN GATE CLEARED" in str(m.get("content")) for m in messages)
                return {"role": "assistant", "content": "아직 CAPTCHA 앞입니다. 다시 명령해 주세요."}
            if self.calls == 2:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "browser_read", "arguments": {}}}
                    ],
                }
            return {"role": "assistant", "content": "인증 성공 화면을 다시 확인했습니다."}

    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    ollama = ResumeOllama()
    agent = BrowserAgent(
        config,
        ollama,
        FakeGateway(),
        FakeBrowser(),
        FakeTools(),
        store,
        EventBus(),
    )
    prompt = "CAPTCHA 뒤 현재 화면을 다시 확인해"
    job = store.create_job("chat", "gate resume", {"prompt": prompt})
    store.claim_next()
    agent._save_checkpoint_state(
        job_id=job["id"],
        prompt=prompt,
        origin="chat",
        messages=[{"role": "system", "content": "system"}],
        steps=[
            {
                "step": 1,
                "tool": "browser_search",
                "arguments": {},
                "ok": True,
                "status": "",
                "error": "",
                "evidence": {"url": "https://example.test/captcha"},
            }
        ],
        fingerprints={},
        evidence_urls=["https://example.test/captcha"],
        elapsed_sec=3.0,
        thinking_chars=0,
        continuation_count=0,
        last_action_ids={},
    )
    store.set_status(job["id"], JobStatus.WAITING_CONTINUATION)

    agent.continue_job(job["id"], "continue_task", reason="gate_cleared")
    result = agent.run(prompt, job_id=job["id"], origin="chat")

    assert result.answer == "인증 성공 화면을 다시 확인했습니다."
    assert ollama.calls == 3
    assert result.verification["successful_steps"] == 2


def _step(tool: str, *, ok: bool, error: str = "") -> dict:
    return {"step": 1, "tool": tool, "arguments": {}, "ok": ok, "status": "", "error": error, "evidence": {}}


def test_success_claim_is_corrected_when_the_commit_tool_failed(tmp_path) -> None:
    """2026-08-03: naver_blog_save_draft failed on a click the SmartEditor popup
    had swallowed, and the answer still read "본문 입력 완료. 임시 저장 완료."
    The prompt already forbids this (handoff 5.2) and the prompt is not enough,
    so the claim is checked against the recorded step outcome."""
    agent, _, _, _ = _agent(tmp_path)
    steps = [
        _step("naver_blog_fill_editor", ok=True),
        _step("naver_blog_save_draft", ok=False, error="naver_blog_draft_save_unverified:count -1->-1"),
    ]

    correction = agent._commit_reality_check("본문 입력 완료. 임시 저장 완료.", steps)

    assert "성공하지 않았습니다" in correction
    assert "naver_blog_save_draft" in correction
    assert "draft_save_unverified" in correction


def test_no_correction_when_the_commit_finally_succeeded(tmp_path) -> None:
    agent, _, _, _ = _agent(tmp_path)
    steps = [
        _step("naver_blog_save_draft", ok=False, error="naver_blog_popup_blocking:이전에 작성 중이던 글"),
        _step("naver_blog_save_draft", ok=True),
    ]
    assert agent._commit_reality_check("임시 저장 완료했습니다.", steps) == ""


def test_no_correction_when_the_answer_claims_nothing(tmp_path) -> None:
    agent, _, _, _ = _agent(tmp_path)
    steps = [_step("naver_blog_save_draft", ok=False, error="naver_blog_draft_save_unverified:")]
    answer = "임시저장이 실패했습니다. 화면에서 직접 확인해 주세요."
    assert agent._commit_reality_check(answer, steps) == ""


def test_read_only_step_failures_never_trigger_a_correction(tmp_path) -> None:
    agent, _, _, _ = _agent(tmp_path)
    steps = [_step("browser_read", ok=False, error="stale_element_ref")]
    assert agent._commit_reality_check("조사를 완료했습니다.", steps) == ""
