"""되돌릴 수 있으면 혼자 더 간다 — 사람을 부르는 것은 정말 못 갈 때뿐이다.

예전에는 12스텝·180초에서 **무조건** 멈추고 사람을 불렀다. 안전 장치처럼 보였지만
아니었다: 되돌릴 수 없는 일은 어차피 L2 승인에서 따로 멈춘다. 그 12/180 은 안전이
아니라 자원 한도였고, 그 값이 자비스를 L3 에 묶어 두고 있었다(실측 200건: 스텝
중앙값 2, 제일 긴 조사가 18에서 끊김).

바뀐 규칙은 하나다: **되돌릴 수 없는 일을 아직 안 했고 진전이 있으면 혼자 더 간다.**

  - "되돌릴 수 없는가"는 목록을 따로 적지 않고 게이트웨이에 등록된 역동작
    (ToolSpec.inverse)을 그대로 본다. 목록을 두 벌 두면 갈라지고, 갈라진 쪽은
    조용히 틀린다.
  - "진전이 있는가"는 낱말이 아니라 행동으로 본다 — 연달아 실패하거나 같은 도구만
    되풀이하면 더 가 봐야 같은 자리다.
  - 그래도 끝은 있다(30스텝 / 15분). 무한히 도는 것을 막는 값이지 사람을 부르는
    값이 아니다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from alture_jarvis.agent import BrowserAgent, _next_plan_step_hint
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.plan import Requirement
from alture_jarvis.tool_gateway import InverseSpec, ToolGateway, ToolSpec


def _agent(**overrides: Any) -> BrowserAgent:
    root = Path(tempfile.mkdtemp())
    config = JarvisConfig(
        runtime_root=root, data_dir=root / "data", output_dir=root / "outputs", **overrides
    )
    store = JobStore(root / "jobs.db")
    gateway = ToolGateway(store, EventBus())
    # 되돌릴 수 있는 커밋과 없는 커밋을 하나씩.
    gateway.register(
        ToolSpec(
            name="naver_blog_save_draft",
            description="임시저장",
            risk_level=RiskLevel.L1,
            handler=lambda a: {},
            inverse=InverseSpec(label="지우기", handle_from=lambda r: {"x": 1}),
        )
    )
    gateway.register(
        ToolSpec(
            name="google_gmail_send",
            description="메일 발송",
            risk_level=RiskLevel.L2,
            handler=lambda a: {},
        )
    )
    return BrowserAgent(
        config, object(), gateway, object(), object(), store, EventBus()
    )


def _step(tool: str, ok: bool = True) -> dict[str, Any]:
    return {"step": 1, "tool": tool, "arguments": {}, "ok": ok, "status": "", "error": "", "evidence": {}}


# ── 되돌릴 수 있으면 계속 ────────────────────────────────────────────────────
def test_reading_and_searching_never_stops_to_ask() -> None:
    agent = _agent()
    steps = [_step("browser_search"), _step("browser_extract"), _step("browser_open_result")]
    extra, why = agent._autonomous_extension(steps=steps, elapsed=200.0)
    assert extra > 0
    assert why == "reversible_and_progressing"


def test_a_reversible_commit_does_not_stop_it_either() -> None:
    """임시저장은 되돌릴 수 있다(역동작 등록됨). 계속 가도 무를 수 있다."""
    agent = _agent()
    steps = [_step("browser_search"), _step("naver_blog_save_draft")]
    extra, _ = agent._autonomous_extension(steps=steps, elapsed=100.0)
    assert extra > 0


# ── 되돌릴 수 없는 일을 했으면 멈춘다 ────────────────────────────────────────
def test_after_something_irreversible_it_reports_instead_of_going_on() -> None:
    """발행하고 나서 혼자 열 걸음 더 가는 것보다, 발행했다고 말하고 멈추는 편이 낫다."""
    agent = _agent()
    steps = [_step("browser_search"), _step("google_gmail_send")]
    extra, why = agent._autonomous_extension(steps=steps, elapsed=100.0)
    assert extra == 0
    assert why == "irreversible:google_gmail_send"


def test_a_failed_irreversible_step_does_not_count() -> None:
    """보내려다 실패한 것은 보낸 것이 아니다."""
    agent = _agent()
    steps = [_step("google_gmail_send", ok=False)]
    extra, _ = agent._autonomous_extension(steps=steps, elapsed=10.0)
    assert extra > 0


# ── 헛돌면 멈춘다 ────────────────────────────────────────────────────────────
def test_three_failures_in_a_row_is_not_progress() -> None:
    agent = _agent()
    steps = [_step("browser_search"), _step("browser_click", ok=False),
             _step("browser_click", ok=False), _step("browser_click", ok=False)]
    extra, why = agent._autonomous_extension(steps=steps, elapsed=10.0)
    assert extra == 0
    assert why == "no_progress"


def test_hammering_one_tool_with_nothing_to_show_is_not_progress() -> None:
    """검색 10번·본문 0건이 실제로 있었던 모양이다."""
    agent = _agent()
    steps = [_step("browser_search", ok=False) for _ in range(4)]
    extra, why = agent._autonomous_extension(steps=steps, elapsed=10.0)
    assert extra == 0
    assert why == "no_progress"


# ── 그래도 끝은 있다 ─────────────────────────────────────────────────────────
def test_there_is_still_a_ceiling_on_steps() -> None:
    agent = _agent(agent_autonomous_max_steps=5)
    steps = [_step("browser_search") for _ in range(5)]
    extra, why = agent._autonomous_extension(steps=steps, elapsed=10.0)
    assert extra == 0
    assert why == "autonomous_step_cap"


def test_there_is_still_a_ceiling_on_time() -> None:
    agent = _agent(agent_autonomous_lease_sec=120)
    extra, why = agent._autonomous_extension(steps=[_step("browser_search")], elapsed=121.0)
    assert extra == 0
    assert why == "autonomous_time_cap"


def test_an_unregistered_commit_tool_is_treated_as_irreversible() -> None:
    """모르는 것은 되돌릴 수 있다고 치지 않는다 — 모를 때는 사람을 부른다."""
    agent = _agent()
    steps = [_step("google_calendar_delete")]
    extra, why = agent._autonomous_extension(steps=steps, elapsed=10.0)
    assert extra == 0
    assert why.startswith("irreversible:")


# ── 진전은 "성공"이 아니라 "새 출처"로 잰다 ──────────────────────────────────
#
# ★ 처음에는 실패만 셌는데 그게 구멍이었다(2026-08-10 실측). 30스텝짜리 조사에서
# 17~30 스텝이 거의 전부 검색이었고 **전부 ok=True** 라 헛돎에 안 걸렸다. 결과 없는
# 검색은 실패가 아니라 성공으로 기록된다 — 검색은 늘 성공하기 때문이다.
#
# 그래서 11분을 쓰고 답 없이 "계속할까요?"가 나왔다. 그 전(180초 상한)에는 부분
# 답이라도 나왔으니, 자율을 늘리면서 만든 회귀였다.
#
# 저장소가 같은 결론에 이미 두 번 도달했다(browser._searches_without_read,
# local_computer._listings_since_read): 낱말이 아니라 행동을 봐야 한다.


def _read_step(url: str) -> dict[str, Any]:
    return {"tool": "browser_extract", "ok": True, "arguments": {}, "evidence": {"url": url}}


def _search_step(n: int) -> dict[str, Any]:
    return {
        "tool": "browser_search", "ok": True, "arguments": {},
        "evidence": {"url": f"https://search.naver.com/search.naver?query=q{n}"},
    }


def test_six_successful_searches_with_nothing_new_is_stuck() -> None:
    """실제로 있었던 꼬리 모양이다 — 전부 성공인데 아무것도 안 읽었다."""
    steps = [_read_step("https://a.com/1")] + [_search_step(i) for i in range(6)]
    assert BrowserAgent._is_stuck(steps) is True


def test_reading_new_sources_is_not_stuck() -> None:
    steps = [_search_step(0)] * 3 + [_read_step(f"https://a.com/{i}") for i in range(3)]
    assert BrowserAgent._is_stuck(steps) is False


def test_successful_form_state_changes_are_progress_without_new_sources() -> None:
    """폼은 URL을 더 읽지 않아도 입력·선택·검증으로 목표에 가까워진다."""
    steps = [
        _step("browser_fill_form"),
        _step("browser_select_option"),
        _step("browser_click", ok=False),
        _step("browser_click"),
        _step("browser_click"),
        {
            **_step("ui_verify"),
            "evidence": {"verdict": "yes", "claim": "Textarea contains expected value"},
        },
    ]

    assert BrowserAgent._is_stuck(steps) is False

    agent = _agent()
    extra, why = agent._autonomous_extension(steps=steps, elapsed=100.0)
    assert extra > 0
    assert why == "reversible_and_progressing"


def test_a_reversible_file_write_emits_continued_alone_before_verification(
    tmp_path, monkeypatch
) -> None:
    """산출물만 만들고 예산이 닿아도, 테스트가 남았으면 혼자 이어간다.

    ★ 예산을 **여기서 못 박는다** (2026-09-02). 이 검사가 보는 것은 「경계에서
      혼자 이어가는가」이지 경계가 몇인가가 아니다. 그런데 걸음 예산이 산출물
      요구에도 자리를 주도록 바뀌자(`_step_budget`: 2 → 5) 경계에 안 닿아
      검사가 헛돌았다. 계산 규칙에 매달아 두면 규칙이 옳게 바뀔 때마다 깨진다.
    """
    # `code=` 는 2026-09-20 에 생겼다(Code 모드만 예산이 따로다). 가짜도 같이 받아야 한다.
    monkeypatch.setattr(BrowserAgent, "_step_budget", lambda self, plan, *, code=False: 2)
    output = tmp_path / "outputs" / "workspace" / "job" / "result.py"

    class Tools:
        names = {"local_write_file", "sandbox_run"}
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

    class Browser:
        def forget_results(self) -> None:
            return None

    class Model:
        def __init__(self) -> None:
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
                                "name": "local_write_file",
                                "arguments": {"path": str(output), "content": "print('ok')\n"},
                            }
                        }
                    ],
                }
            if self.calls == 2:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "sandbox_run", "arguments": {"code": "pytest -q"}}}
                    ],
                }
            return {"role": "assistant", "content": "파일을 만들고 테스트를 통과했습니다."}

    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        ollama_max_tool_steps=2,
        agent_autonomous_max_steps=8,
        # Code 모드는 예산 칸이 따로다 (2026-09-20).
        code_max_tool_steps=2,
        code_autonomous_max_steps=8,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jobs.db")
    events = EventBus()
    gateway = ToolGateway(store, events)

    def write(arguments):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(str(arguments.get("content") or ""), encoding="utf-8")
        return {
            "action": "local_write_file",
            "path": str(output),
            "verified": output.is_file(),
            "undo_handle": {"path": str(output)},
        }

    gateway.register(
        ToolSpec(
            name="local_write_file",
            description="write",
            risk_level=RiskLevel.L1,
            handler=write,
            inverse=InverseSpec(
                label="delete",
                handle_from=lambda result: result.get("undo_handle"),
                undo=lambda handle: output.unlink(missing_ok=True),
            ),
        )
    )
    gateway.register(
        ToolSpec(
            name="sandbox_run",
            description="run",
            risk_level=RiskLevel.L1,
            handler=lambda arguments: {
                "action": "sandbox_run",
                "exit_code": 0,
                "verified": True,
            },
        )
    )
    agent = BrowserAgent(config, Model(), gateway, Browser(), Tools(), store, events)
    job = store.create_job("chat", "artifact", {"prompt": "result.py 파일을 만들고 pytest 테스트를 통과시켜줘"})
    store.claim_next()

    result = agent.run(
        "result.py 파일을 만들고 pytest 테스트를 통과시켜줘",
        job_id=job["id"],
    )

    continued = [event for event in events.get_since(0) if event.event == "agent_continued_alone"]
    assert continued and continued[0].payload["reason"] == "reversible_and_progressing"
    assert result.verification["completion_state"] == "complete"


def test_a_search_loop_stops_the_autonomy() -> None:
    agent = _agent()
    steps = [_read_step("https://a.com/1")] + [_search_step(i) for i in range(6)]
    extra, why = agent._autonomous_extension(steps=steps, elapsed=100.0)
    assert extra == 0
    assert why == "no_progress"


def _artifact_plan(*, told: bool = True):
    return [
        (Requirement("count", "3개 읽기", 3), True, "3개 읽음"),
        (Requirement("artifact", "문서 만들기", (".hwpx",)), False, "산출물 없음"),
        (Requirement("footnote", "각주 3개", 3), False, "각주 없음"),
    ], told


def test_new_pages_are_not_progress_when_only_the_artifact_is_left() -> None:
    """새벽 재현: 문서·각주만 남았는데 공고를 12건 더 읽어 15분을 썼다."""
    agent = _agent()
    plan, told = _artifact_plan()
    steps = [_read_step(f"https://saramin.test/job/{i}") for i in range(8)]

    extra, why = agent._autonomous_extension(
        steps=steps,
        elapsed=300.0,
        plan_results=plan,
        plan_told=told,
    )

    assert extra == 0
    assert why == "no_progress_for_remaining_goal"


def test_an_unmet_artifact_gets_one_transition_segment_before_closing() -> None:
    """목표 전환 안내를 듣기도 전에 닫아 버리는 반대쪽 병목은 만들지 않는다."""
    agent = _agent()
    plan, _ = _artifact_plan()
    steps = [_read_step(f"https://saramin.test/job/{i}") for i in range(8)]

    extra, why = agent._autonomous_extension(
        steps=steps,
        elapsed=300.0,
        plan_results=plan,
        plan_told=False,
    )

    assert extra > 0
    assert why == "remaining_goal_first_notice"


def test_the_pushback_hint_matches_the_remaining_stage() -> None:
    artifact_plan, _ = _artifact_plan()
    read_plan = [(Requirement("count", "3개 읽기", 3), False, "1개 읽음")]

    assert "산출물 단계" in _next_plan_step_hint(artifact_plan)
    assert "본문을 열어라" not in _next_plan_step_hint(artifact_plan)
    assert "본문을 열어라" in _next_plan_step_hint(read_plan)


def test_a_missing_file_read_does_not_get_the_browser_nudge() -> None:
    """★ 2026-09-23: 파일 쪽 읽기만 남았는데 `browser_open_result → browser_extract` 재촉이 갔고, 모델이 시킨 일 대신
    그 재촉에 답했다. 대상이 브라우저가 아니면 파일을 읽으라고 — 읽을 게 없으면 한 일을 그대로 답하라고 준다."""
    file_plan = [(Requirement("observe", "근거가 되는 대상 실제로 읽기", "any"), False, "0개 실제로 읽음")]
    hint = _next_plan_step_hint(file_plan)
    assert "browser_open_result" not in hint and "본문을 열어라" not in hint
    assert "한 일" in hint

    web_plan = [(Requirement("observe", "근거가 되는 대상 실제로 읽기", "browser"), False, "0개 실제로 읽음")]
    assert "본문을 열어라" in _next_plan_step_hint(web_plan), "★ 좋은 표본 — 웹 읽기가 남았으면 예전 재촉 그대로"
