"""2026-09-02 코워크 병목: 빈 계획·목록 베끼기·동일 실패 반복."""

from __future__ import annotations

from alture_jarvis.agent import (
    BrowserAgent,
    _can_wrap_at_human_gate,
    _detailed_count_can_force_read,
    _focused_tool_definitions,
    _forced_read_call,
    _plan_focus_stage,
    _read_only_tool_definitions,
    _redirect_redundant_extract,
    _repeat_notice,
)
from alture_jarvis.plan import Requirement, check, extract


def _step(tool: str, *, url: str = "", ok: bool = True) -> dict[str, object]:
    return {
        "tool": tool,
        "ok": ok,
        "arguments": {},
        "evidence": {"url": url} if url else {},
        "status": "",
        "error": "",
    }


def test_a_routed_research_task_can_no_longer_have_an_empty_plan() -> None:
    prompt = "내 철학이 시장에서 틀린지 외부조사랑 같이해서 분석해줘"

    plan = extract(prompt, must_observe=True)

    assert [item.kind for item in plan] == ["observe"]
    assert check(plan, sources=[], steps=[])[0][1] is False
    assert check(
        plan,
        sources=["https://example.com/report"],
        steps=[_step("browser_extract", url="https://example.com/report")],
    )[0][1] is True


def test_list_visible_fields_still_do_not_force_detail_pages() -> None:
    prompt = "무신사에서 상위 3개 제품명과 가격만 알려줘"
    plan = extract(prompt, has_named_source=True, must_observe=True)
    count = next(item for item in plan if item.kind == "count")
    answer = "1. A 10원\n2. B 20원\n3. C 30원"

    result = check([count], sources=[], steps=[], answer=answer)

    assert result[0][1] is True
    assert not [item for item in plan if item.kind == "observe"]


def test_detail_count_requires_read_answer_and_entity_pairing() -> None:
    prompt = "사람인에서 정규직 공고 3개를 조사해서 추천해줘"
    requirement = next(
        item
        for item in extract(prompt, has_named_source=True, must_observe=True)
        if item.kind == "count"
    )
    assert requirement.grounding_required is True
    sources = [f"https://saramin.test/job/{n}" for n in (1, 2, 3)]
    answer = "1. **미르**\n2. **도담스페이스**\n3. **바름터**"

    mismatched = check(
        [requirement],
        sources=sources,
        steps=[],
        answer=answer,
        listed_entities_grounded=False,
    )
    matched = check(
        [requirement],
        sources=sources,
        steps=[],
        answer=answer,
        listed_entities_grounded=True,
    )

    assert mismatched[0][1] is False
    assert "없는 이름" in mismatched[0][2]
    assert matched[0][1] is True


def test_entity_grounding_does_not_count_names_seen_only_in_a_search_list() -> None:
    answer = "1. **미르**\n2. **도담스페이스**\n3. **바름터**"
    messages = [
        {
            "role": "tool",
            "tool_name": "browser_site_search",
            "content": "미르 도담스페이스 바름터 검색 결과",
        },
        {
            "role": "tool",
            "tool_name": "browser_extract",
            "content": "미르 상세 본문",
        },
    ]

    note = BrowserAgent._listed_entity_grounding_check(answer, messages)

    assert "도담스페이스" in note and "바름터" in note
    assert "미르" not in note.split("있습니다:")[1].split(".")[0]


def test_entity_grounding_ignores_explanatory_bullet_labels() -> None:
    """일반 조사 답의 굵은 소제목은 회사·공고 실명 목록이 아니다."""
    answer = """- **워크플로우 자동화:** 계획과 실행 루프를 돌린다.
- **파일 시스템 기반 메모리:** 필요한 기록을 다시 읽는다.
- **ACE (Agentic Context Engineering):** 컨텍스트를 구조화한다."""
    messages = [
        {
            "role": "tool",
            "tool_name": "browser_extract",
            "content": "Harness engineering article body",
        }
    ]

    assert BrowserAgent._listed_entity_grounding_check(answer, messages) == ""


def test_entity_grounding_keeps_companies_but_ignores_work_summary_labels() -> None:
    answer = """**분석한 공고**
- **한뜻회계법인**: 연구비 정산 경력직
- **주식회사 물빛핀**: 연구비 관리 직원
- **한울대학교산학협력단**: 사업관리 채용

**작업 요약**
- **이력서 원문 반영**: Drive 원문 기반
- **공고 맞춤형 제안**: 각주 3개
- **파일 형식**: HWPX"""
    messages = [
        {
            "role": "tool",
            "tool_name": "browser_extract",
            "content": "한뜻회계법인 주식회사 물빛핀 한울대학교산학협력단 상세 본문",
        }
    ]

    assert BrowserAgent._listed_entity_grounding_check(answer, messages) == ""


def test_grounded_count_uses_the_existing_deterministic_read_path() -> None:
    requirement = next(
        item
        for item in extract(
            "사람인에서 공고 3개를 조사해줘",
            has_named_source=True,
            must_observe=True,
        )
        if item.kind == "count"
    )
    results = [(requirement, False, "0개 읽음 · 답에 0개")]

    assert _forced_read_call(results, []) == ("browser_open_result", {"rank": 1})
    assert _detailed_count_can_force_read(results) is True


def test_artifact_stage_gets_its_own_narrow_tool_surface() -> None:
    plan = [
        (Requirement("count", "3개 읽기", 3), True, "3개 읽음"),
        (Requirement("artifact", "문서 만들기", (".hwpx",)), False, "없음"),
    ]
    tools = [
        {"function": {"name": "browser_open_result"}},
        {"function": {"name": "local_write_document"}},
        {"function": {"name": "sandbox_run"}},
    ]

    assert _plan_focus_stage(plan) == "artifact"
    # ★ 2026-10-04: 계획 층은 `sandbox_run` 을 산출물 손으로 친다(그래프·QR 을 파일로) — 차례 문만 안 받아 갈려 있었다
    #   (도구 전수조사 2-E). 이 시험의 뜻은 그대로다: **브라우저로 더 찾으러 가는 손**은 산출물 차례에 없다.
    assert [
        item["function"]["name"]
        for item in _focused_tool_definitions(tools, "artifact")
    ] == ["local_write_document", "sandbox_run"]


def test_read_only_tool_surface_hides_file_and_external_writes() -> None:
    tools = [
        {"function": {"name": "local_read_text_file"}},
        {"function": {"name": "browser_extract"}},
        {"function": {"name": "local_write_document"}},
        {"function": {"name": "artifact_from_observations"}},
        {"function": {"name": "google_gmail_send"}},
    ]

    assert [
        item["function"]["name"] for item in _read_only_tool_definitions(tools)
    ] == ["local_read_text_file", "browser_extract"]


def test_met_web_count_wraps_instead_of_waiting_on_an_optional_bot_wall() -> None:
    requirement = Requirement("count", "웹 본문 3개", 3, grounding_required=True)
    results = [(requirement, True, "3개 읽음")]
    steps = [
        _step("browser_extract", url=f"https://source{n}.test/body")
        for n in (1, 2, 3)
    ]

    assert _can_wrap_at_human_gate(results, steps) is True
    assert _can_wrap_at_human_gate(results, steps[:2]) is False


def test_repeated_extract_moves_to_the_next_unread_result() -> None:
    requirement = Requirement(
        "count", "웹 자료 3개", 3, grounding_required=True, source_scope="web"
    )
    results = [(requirement, False, "1개 읽음")]
    steps = [
        _step("browser_open_result", url="https://source.test/one"),
        _step("browser_extract", url="https://source.test/one"),
    ]
    steps[0]["arguments"] = {"rank": 1}

    assert _redirect_redundant_extract("browser_extract", {}, results, steps) == (
        "browser_open_result",
        {"rank": 2},
    )


def test_final_answer_cannot_cite_a_page_that_was_only_opened() -> None:
    steps = [
        _step("browser_open_result", url="https://datanorth.ai/guide"),
        _step("browser_open_result", url="https://endorlabs.com/guide"),
        _step("browser_extract", url="https://endorlabs.com/guide"),
    ]

    conflict = BrowserAgent._unread_source_attribution_conflict(
        "외부 분석 대상: DataNorth AI의 하네스 가이드", steps
    )

    assert "datanorth" in conflict
    assert BrowserAgent._unread_source_attribution_conflict(
        "DataNorth AI는 열기만 했고 본문은 못 읽었습니다.", steps
    ) == ""


def test_repeat_notice_preserves_the_real_result_instead_of_blocking_it() -> None:
    observation = {"ok": False, "error": "timeout", "result": {"url": "https://x"}}

    noticed = _repeat_notice(
        observation,
        tool="browser_extract",
        repeat_count=3,
        same_failure_count=3,
    )

    assert noticed["ok"] is False
    assert noticed["error"] == "timeout"
    assert noticed["result"]["url"] == "https://x"
    assert noticed["result"]["repeat_notice"] is True
    assert "다른 도구" in noticed["result"]["instruction"]


def test_repeat_notice_is_silent_before_the_third_identical_call() -> None:
    observation = {"ok": True, "result": {"text": "new evidence"}}

    assert _repeat_notice(
        observation,
        tool="local_read_text_file",
        repeat_count=2,
        same_failure_count=0,
    ) is observation
