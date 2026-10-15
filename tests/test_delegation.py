"""Claude 가 온텔릭에게 일을 통째로 맡기는 문 (인수인계 H1-a·H1-c).

지켜야 할 것:
- 연결하면 Claude 가 온텔릭이 무엇인지 안다(안내문이 비어 있지 않고, 옛 이름이 없다).
- 위임 결과의 **근거 없는 숫자**는 반드시 드러난다 — 위임 3판 중 2판이 창작했던 자리.
- 근거가 있는 숫자로는 거짓 고발을 하지 않는다(양방향).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from alture_jarvis.brand import LEGACY_NAMES
from alture_jarvis.delegation import summarize_job
from alture_jarvis.mcp_server import INSTRUCTIONS, JarvisMcpBridge, build_server


def _job(answer: str, tool_numbers: list[str], *, write_text: str = "", completion: str = "complete") -> dict[str, Any]:
    steps = [
        {"tool": "browser_extract", "ok": True, "evidence": {},
         "evidence_record": {"effect": "read_web", "source_id": "https://www.saramin.co.kr/a"}},
    ]
    if write_text:
        steps.append({"tool": "local_write_document", "ok": True,
                      "arguments": {"blocks": [{"type": "paragraph", "text": write_text}]},
                      "evidence": {"output_path": "C:/Users/u/Documents/Ontelic/a.docx"},
                      "evidence_record": {"effect": "write_local", "source_id": "c:/users/u/documents/ontelic/a.docx"}})
    return {"id": "j1", "status": "completed",
            "result": {"answer": answer, "completion_state": completion,
                       "agent_trace": {"steps": steps, "tool_numbers": tool_numbers, "tool_numbers_body": []}}}


def test_instructions_say_what_ontelic_is_without_the_old_name() -> None:
    assert "Sonjari" in INSTRUCTIONS and "sonjari_task" in INSTRUCTIONS
    assert len(INSTRUCTIONS) <= 1500
    for legacy in LEGACY_NAMES:
        assert legacy not in INSTRUCTIONS


def test_the_server_hands_the_instructions_to_the_client() -> None:
    server = build_server(JarvisMcpBridge(token="t"))
    options = server.create_initialization_options()
    assert options.instructions == INSTRUCTIONS


def test_a_number_no_tool_gave_marks_the_result_for_review() -> None:
    summary = summarize_job(_job("연봉은 4200만원입니다.", tool_numbers=["3500"]))
    assert summary["status"] == "needs_review"
    assert summary["unsupported_numbers"] == ["4200"]
    assert summary["review_notes"]


def test_numbers_written_into_the_file_are_checked_too() -> None:
    summary = summarize_job(_job("파일로 만들었습니다.", tool_numbers=["3500"], write_text="월급 9900만원"))
    assert summary["unsupported_numbers"] == ["9900"]
    assert summary["files"] == ["C:/Users/u/Documents/Ontelic/a.docx"]


def test_grounded_numbers_are_not_accused() -> None:
    summary = summarize_job(_job("연봉 3,500만원 공고 2개", tool_numbers=["3500"], write_text="3500"))
    assert summary["status"] == "done"
    assert summary["unsupported_numbers"] == []
    assert summary["sources"] == ["https://www.saramin.co.kr/a"]


def test_partial_is_a_note_not_a_review_flag() -> None:
    summary = summarize_job(_job("끝", tool_numbers=[], completion="partial"))
    assert summary["status"] == "done" and summary["review_notes"]


def test_waiting_for_approval_is_said_out_loud() -> None:
    summary = summarize_job({"id": "j2", "status": "waiting_approval", "result": {}})
    assert summary["status"] == "needs_approval" and "승인" in summary["message"]


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        assert self.status_code < 400


class _JobClient:
    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        self.jobs = jobs
        self.posts: list[dict[str, Any]] = []

    async def get(self, url: str) -> Any:
        if url.endswith("/v1/tools"):
            return _Response([{"name": "browser_search", "risk_level": "L0", "enabled": True}])
        return _Response(self.jobs.pop(0) if len(self.jobs) > 1 else self.jobs[0])

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:  # noqa: A002
        self.posts.append({"url": url, "json": json})
        return _Response({"id": "job-9", "status": "queued"})

    async def aclose(self) -> None:
        return None


def test_delegation_tools_lead_the_list_and_start_a_quiet_job(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    client = _JobClient([_job("끝", [])])
    bridge = JarvisMcpBridge(token="t", client=client)
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert names[:2] == ["sonjari_task", "sonjari_task_status"] and "browser_search" in names

    text, failed = asyncio.run(bridge.call("sonjari_task", {"task": "사람인 여수 회계 공고 정리"}))
    assert not failed and json.loads(text)["job_id"] == "job-9"
    sent = client.posts[0]
    assert sent["url"].endswith("/v1/chat") and sent["json"]["open_results"] is False


def test_status_returns_the_summary_when_done() -> None:
    bridge = JarvisMcpBridge(token="t", client=_JobClient([_job("연봉 4200만원", ["3500"])]))
    text, failed = asyncio.run(bridge.call("sonjari_task_status", {"job_id": "j1", "wait_sec": 0}))
    assert not failed and json.loads(text)["status"] == "needs_review"


def test_delegation_can_be_turned_off_for_the_head_to_head_measurement(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_DELEGATION", "0")
    bridge = JarvisMcpBridge(token="t", client=_JobClient([_job("끝", [])]))
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert "sonjari_task" not in names and "browser_search" in names
    text, failed = asyncio.run(bridge.call("sonjari_task", {"task": "x"}))
    assert failed


def test_a_waiting_job_says_why_it_is_not_moving() -> None:
    """★ 「일하는 중 · 걸음 0」만 주면 Claude 가 20분을 헛기다린다(2026-09-16 실측)."""
    queued = summarize_job({"id": "j3", "status": "queued", "result": {}}, ahead=2)
    assert queued["status"] == "queued" and queued["jobs_ahead"] == 2 and "앞에 2개" in queued["message"]

    waiting = summarize_job({"id": "j4", "status": "waiting_approval", "result": {}})
    assert waiting["status"] == "needs_approval" and "승인" in waiting["message"]

    asked = summarize_job({"id": "j5", "status": "waiting_continuation", "result": {}})
    assert asked["status"] == "needs_decision"


# ── resume · cost (2026-09-16 밤 인수인계 §4 ①②) ─────────────────────────────────


def _partial_job(*, unmet: bool, failed: bool) -> dict[str, Any]:
    job = _job("표는 만들었지만 파일은 못 만들었습니다.", [], completion="partial")
    trace = job["result"]["agent_trace"]
    if failed:
        trace["steps"].append({"tool": "browser_open_result", "ok": False, "error": "browser_stuck"})
    trace["verification"] = {
        "elapsed_sec": 88.5,
        "plan": {"items": [
            {"kind": "count", "label": "2개 이상 직접 열어 읽기", "met": True, "saw": "2개 읽음"},
            {"kind": "artifact", "label": "실제 산출물 파일 만들기", "met": not unmet, "saw": "파일 0개"},
        ]},
    }
    return job


def test_resume_carries_what_was_done_and_only_the_unmet_requirements() -> None:
    summary = summarize_job(_partial_job(unmet=True, failed=True))
    resume = summary["resume"]
    assert resume["evidence"] == ["https://www.saramin.co.kr/a"]  # 다시 안 열어도 되는 근거
    assert resume["next"] == ["실제 산출물 파일 만들기 (지금: 파일 0개)"]  # 계획 층 판정 그대로 — 지어내지 않는다
    assert "browser_extract ×1" in resume["did"]
    assert resume["blocked"].startswith("browser_open_result: browser_stuck")


def test_no_resume_when_everything_was_met_and_nothing_failed() -> None:
    job = _partial_job(unmet=False, failed=False)
    job["result"]["completion_state"] = "complete"
    assert "resume" not in summarize_job(job)


def test_a_partial_from_answer_review_still_says_why_and_what_was_read() -> None:
    """2026-09-16 밤 붙임새 S1 2판: 요구는 다 채웠는데 답 검토에 걸려 partial. 예전엔 resume 이 비어
    호스트가 「덜 끝났다」만 받았다. 검토 문구는 **그대로** 옮긴다 — 지어내지 않는다."""
    job = _partial_job(unmet=False, failed=False)
    conflict = "본문을 읽지 않은 출처를 분석 근거로 적었습니다(saramin)."
    job["result"]["agent_trace"]["verification"]["answer_conflict"] = conflict

    resume = summarize_job(job)["resume"]

    assert resume["why_partial"] == [conflict]
    assert resume["evidence"] == ["https://www.saramin.co.kr/a"]
    assert resume["next"] == []  # 계획 층이 못 채웠다고 한 요구는 없다 — 칸을 지어내지 않는다


def test_a_partial_without_any_stated_reason_does_not_invent_one() -> None:
    assert "resume" not in summarize_job(_partial_job(unmet=False, failed=False))


def test_cost_is_numbers_with_a_basis_never_a_bare_multiplier() -> None:
    cost = summarize_job(_partial_job(unmet=False, failed=False))["cost"]
    assert cost["sec"] == 88.5
    assert cost["pages_read_locally"] == 1 and cost["pages_read_by_host"] == 0
    # ★ 2026-09-23: 폐기된 9/7 숫자(캐싱 끔·n=1)로 곱한 범위 추정은 더 이상 나가지 않는다 — 하한만.
    assert "host_input_tokens_avoided_estimate" not in cost
    assert "608,086" not in str(cost) and "971,241" not in str(cost)


def test_no_token_estimate_when_nothing_was_read() -> None:
    job = _partial_job(unmet=False, failed=False)
    job["result"]["agent_trace"]["steps"] = []
    assert "host_input_tokens_avoided_estimate" not in summarize_job(job)["cost"]


def test_a_shortfall_flag_is_said_in_words_not_as_true() -> None:
    job = _partial_job(unmet=False, failed=False)
    job["result"]["agent_trace"]["verification"]["reported_shortfall"] = True

    why = summarize_job(job)["resume"]["why_partial"]

    assert why and all(item not in ("True", "False") for item in why)


def test_the_reason_says_what_fell_short_not_always_the_count() -> None:
    """★ 2026-10-04 통이미지 공고 판(93c18011): 공고 둘을 다 읽고 그림이라 못 읽은 두 칸을 「확인 못 함」으로 냈는데
    「요구한 **개수**에 못 미쳤다고 말했습니다」가 붙었다 — 개수는 2/2 였다. 일부 판정은 맞고 이유만 틀렸다."""
    job = _partial_job(unmet=False, failed=False)
    job["result"]["agent_trace"]["verification"]["reported_shortfall"] = True
    job["result"]["agent_trace"]["verification"]["reported_shortfall_kind"] = "not_done"
    not_done = summarize_job(job)["resume"]["why_partial"]
    job["result"]["agent_trace"]["verification"]["reported_shortfall_kind"] = "count"
    count = summarize_job(job)["resume"]["why_partial"]

    assert any("확인 못 함" in item for item in not_done) and not any("개수" in item for item in not_done)
    assert any("개수" in item for item in count)



def test_the_guide_travels_with_the_connection_for_claude_desktop() -> None:
    """Claude Desktop 은 스킬을 앱이 못 넣고 채팅은 PC 폴더를 못 읽는다(2026-09-17) — 연결이 가이드를 들고 간다."""
    from alture_jarvis.guide_skill import render_skill

    assert "sonjari_guide" in INSTRUCTIONS and len(INSTRUCTIONS) <= 1500
    bridge = JarvisMcpBridge(token="t", client=_JobClient([_job("끝", [])]))
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert names[:3] == ["sonjari_task", "sonjari_task_status", "sonjari_guide"]

    text, failed = asyncio.run(bridge.call("sonjari_guide", {}))

    assert not failed and "sonjari_task" in text
    # Claude Code 에 넣는 SKILL.md 와 같은 본문이어야 한다 — 두 벌이면 갈린다.
    assert text == render_skill(asyncio.run(bridge.list_tools()))


def test_the_guide_is_offered_even_when_delegation_is_off(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_MCP_DELEGATION", "0")
    bridge = JarvisMcpBridge(token="t", client=_JobClient([_job("끝", [])]))
    assert "sonjari_guide" in [tool["name"] for tool in asyncio.run(bridge.list_tools())]


def test_the_lean_toolset_shows_only_the_delegation_doors(monkeypatch) -> None:
    """★ 2026-09-23 비용 실험: 낮은 도구 100여 개의 설명서가 호스트 입력을 약 7만 6천 토큰 늘렸다.
    `JARVIS_MCP_TOOLSET=delegate` 면 맡기기 문과 가이드만 보이고, 낮은 도구는 불러도 막힌다."""
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "delegate")
    bridge = JarvisMcpBridge(token="t", client=_JobClient([_job("끝", [])]))
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert set(names) == {"sonjari_task", "sonjari_task_status", "sonjari_guide"}
    text, failed = asyncio.run(bridge.call("browser_search", {"query": "x"}))
    assert failed


def test_the_delegation_doors_are_never_deferred(monkeypatch) -> None:
    """★ 2026-09-23 오후: 클로드 코드는 MCP 도구를 지연 적재한다. 그 조건에서 클로드가 `sonjari_task` 를 못 찾고
    자기 WebFetch 를 골랐다(맡기기 전용 3판 중 2판). 맡기기 문 셋만 `anthropic/alwaysLoad` 로 처음부터 보이고,
    낮은 도구는 계속 지연된다(표시가 붙으면 100개가 전부 실려 비용이 두 배가 된다 — 본실험의 그 병)."""
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    server = build_server(JarvisMcpBridge(token="t", client=_JobClient([_job("끝", [])])))
    listed = asyncio.run(server._request_handlers["tools/list"].handler(None, None))
    meta = {tool.name: (tool.model_dump(by_alias=True, exclude_none=True).get("_meta") or {}) for tool in listed.tools}
    loud = {name for name, m in meta.items() if m.get("anthropic/alwaysLoad") is True}
    assert loud == {"sonjari_task", "sonjari_task_status", "sonjari_guide"}
    assert "browser_search" in meta and "browser_search" not in loud


def test_the_default_toolset_is_the_delegation_doors(monkeypatch) -> None:
    """★ 2026-09-23 사용자님 결정(재측정 뒤): 설정이 없으면 맡기기 문과 가이드만 — 합계 −25%, 정답 동률(11/12)."""
    monkeypatch.delenv("JARVIS_MCP_TOOLSET", raising=False)
    monkeypatch.delenv("JARVIS_MCP_DELEGATION", raising=False)
    bridge = JarvisMcpBridge(token="t", client=_JobClient([_job("끝", [])]))
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert set(names) == {"sonjari_task", "sonjari_task_status", "sonjari_guide"}


def test_full_toolset_is_still_one_setting_away(monkeypatch) -> None:
    """낮은 도구를 직접 쓰고 싶은 사람은 `JARVIS_MCP_TOOLSET=full` 한 줄 — 되돌리는 길이다."""
    monkeypatch.setenv("JARVIS_MCP_TOOLSET", "full")
    bridge = JarvisMcpBridge(token="t", client=_JobClient([_job("끝", [])]))
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert "sonjari_task" in names and "browser_search" in names


def test_turning_delegation_off_brings_the_low_tools_back(monkeypatch) -> None:
    """맡기기를 끈 실측에서는 낮은 도구가 유일한 손이다 — 기본값이 맡기기 전용이어도 전부 낸다."""
    monkeypatch.delenv("JARVIS_MCP_TOOLSET", raising=False)
    monkeypatch.setenv("JARVIS_MCP_DELEGATION", "0")
    bridge = JarvisMcpBridge(token="t", client=_JobClient([_job("끝", [])]))
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert "browser_search" in names and "sonjari_task" not in names


def test_an_answer_with_zero_steps_is_marked_unchecked() -> None:
    """★ 2026-09-23 파트너 센터: 이어 맡긴 과제에 걸음 0·출처 0 으로 「목록에 없음」 — 앞 판 기억으로 화면을 단정했다."""
    job = {"id": "j0", "status": "completed",
           "result": {"answer": "앱 및 게임 목록에 Ontelic 제품이 존재하지 않음", "completion_state": "answered",
                      "agent_trace": {"steps": [], "tool_numbers": [], "tool_numbers_body": []}}}
    summary = summarize_job(job)
    assert summary["status"] == "needs_review"
    assert any("도구를 하나도 쓰지 않고" in note for note in summary["review_notes"])


def test_an_answer_that_looked_is_not_accused() -> None:
    """★ 좋은 표본 — 한 걸음이라도 읽었으면 걸음 0 표시는 안 붙는다."""
    summary = summarize_job(_job("끝", []))
    assert summary["status"] == "done"
    assert not any("도구를 하나도" in note for note in summary.get("review_notes") or [])


def test_a_stuck_job_tells_the_host_what_the_person_must_do() -> None:
    """★ 헛돌다 멈춘 판(2026-09-23)은 「계속할지 묻는다」가 아니라 **사람이 할 일**을 바깥 AI 에게 넘긴다."""
    job = {"id": "j-stuck", "status": "waiting_continuation", "result": {"continuation": {
        "reason": "stuck",
        "report": {"done": "장바구니를 열었습니다", "blocked": "결제 단추가 넘어가지 않습니다",
                   "ask": "결제 수단을 등록해 주세요", "url": "https://shop.example/cart"},
    }}}
    summary = summarize_job(job)
    assert summary["status"] == "needs_decision"
    assert summary["stuck"]["ask"] == "결제 수단을 등록해 주세요"
    assert "결제 수단을 등록해 주세요" in summary["message"] and "이어서" in summary["message"]


def test_a_budget_stop_keeps_the_plain_question() -> None:
    """★ 좋은 표본 — 예산으로 멈춘 판에 「막혔다」를 붙이지 않는다."""
    job = {"id": "j-budget", "status": "waiting_continuation", "result": {"continuation": {"reason": "time_budget"}}}
    summary = summarize_job(job)
    assert "stuck" not in summary and "계속할지" in summary["message"]


def test_a_human_gate_stop_says_what_the_person_must_open() -> None:
    """★ 사람 문(2026-09-29)에서 멈춘 판은 「계속할지 묻는다」가 아니라 **무슨 문을 열어야 하는지**를 넘긴다.

    운영 58건 중 39건이 사람 문이었는데, 화면·바깥 AI 둘 다 「시간 다 씀 / 계속할지」로 전했다.
    """
    job = {"id": "j-gate", "status": "waiting_continuation", "result": {"continuation": {
        "reason": "human_gate:bot_check", "gate_url": "https://github.com/account/organizations/new",
    }}}
    summary = summarize_job(job)
    assert summary["status"] == "needs_decision"
    assert "보안 문자 확인" in summary["message"] and "이어서" in summary["message"]
    assert "github.com/account/organizations/new" in summary["message"]
    assert "계속할지" not in summary["message"]


def test_numbers_the_person_wrote_in_the_task_are_not_unsupported() -> None:
    """★ 2026-09-30: 「17 곱하기 23은?」의 답에 17·23 이 「도구가 준 적 없는 숫자」로 찍혔다. 과제 문장의 숫자는 근거다.
    계산 결과 391 은 도구가 안 줬으니 그대로 잡혀야 한다(양방향)."""
    job = _job("17 곱하기 23은 391입니다.", tool_numbers=[])
    job["payload"] = {"prompt": "17 곱하기 23은 얼마야?"}

    summary = summarize_job(job)

    assert summary["unsupported_numbers"] == ["391"]


def test_box_outputs_are_listed_by_their_real_path_not_the_run_id() -> None:
    """★ 2026-09-30 QR 판: files 에 상자 실행 번호(`...\48cdbd03a6a7`)가 경로처럼 찍혔다. 실제 경로는 saved_to 에 있다."""
    job = _job("만들었습니다.", tool_numbers=[])
    job["result"]["agent_trace"]["steps"] = [{
        "ok": True, "tool": "sandbox_run",
        "evidence": {"saved_to": [{"name": "qr.png", "path": "C:/out/job/qr.png", "bytes": 548}]},
        "evidence_record": {"effect": "write_local", "source_id": "48cdbd03a6a7"},
    }]

    files = summarize_job(job)["files"]

    assert files == ["C:/out/job/qr.png"]


def test_box_outputs_in_the_ledgers_real_shape() -> None:
    """★ 2026-09-30 워드클라우드 v2: 위 시험은 `saved_to` 를 사전으로 넣었는데 **실제 장부는 글자로 뭉개 둔다.**
    그래서 고친 줄 알았던 것이 운영에서 또 실행 번호를 찍었다. 아래 걸음은 실제 잡(f1756d1b)의 장부 모양 그대로다."""
    job = _job("완성했습니다.", tool_numbers=[])
    job["result"]["agent_trace"]["steps"] = [{
        "ok": True, "tool": "sandbox_run",
        "evidence": {
            "saved_to": ["{'name': 'sonjari_wordcloud_v2.png', 'path': 'C:\\\\Users\\\\user\\\\Desktop\\\\sonjari"],
            "output_paths": ["C:\\Users\\user\\Desktop\\sonjari_wordcloud_v2.png"],
        },
        "evidence_record": {"effect": "write_local", "source_id": "c:\\robometafit\\tools\\alture-jarvis\\dd1e25288c56"},
    }]

    files = summarize_job(job)["files"]

    assert files == ["C:\\Users\\user\\Desktop\\sonjari_wordcloud_v2.png"]


def test_a_human_gate_tells_the_host_to_keep_polling() -> None:
    """★ 10-02 밤 나래 실사용: 클로드가 「이어서 누르고 말해 달라」고 사람을 기다리는 동안 손자리는 이미 답을 썼다.

    사람이 문을 열면 손자리가 스스로 잇는다(gate_watcher) — 바깥 AI 에게는 「계속 물어라」가 다음 수다.
    """
    job = {"id": "j-gate2", "status": "waiting_continuation", "result": {"continuation": {
        "reason": "human_gate:bot_check", "gate_url": "https://www.v2ex.com/signin",
    }}}
    summary = summarize_job(job)
    assert summary["resumes_on_its_own"] is True and summary["waiting_for_person"] == "보안 문자 확인"
    assert "스스로 이어갑니다" in summary["message"] and "sonjari_task_status 를 계속" in summary["message"]
    assert "누르지 않아도" in summary["message"]
