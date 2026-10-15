"""시킨 것을 하나씩 세어 두고 대조한다 — 개수만 세면 "아무거나 네 개"로 통과한다.

에이전트에는 "무엇이 남았는가"를 담는 자리가 없었다. 반응형 도구 루프라 매 걸음
그때그때 정할 뿐이다. 실측(2026-08-10): 26스텝 방황, 17~30번째가 거의 전부 검색.
이미 가진 것과 아직 없는 것을 구별하지 못하니 가장 싼 행동을 되풀이했다.

★ 그래도 **LLM 에게 계획을 세우게 하지는 않는다.** 오늘 하루 잡은 병이 "안 한 일을
했다고, 안 본 것을 봤다고" 하는 것인데, 계획을 지어내게 하면 그 병이 계획 층에서
다시 나고 **계획은 아무도 대조하지 않으므로 더 조용하다.** 대신 프롬프트에서
결정론적으로 뽑을 수 있는 요구만 뽑고, 못 뽑는 것은 아예 안 다룬다.

이 파일이 지키는 것:

  1. 사이트 요구를 잡는다 — 어제 개수 검사(4개)는 통과했는데 그 넷 중 크몽은
     하나도 없었다. 개수만 세면 "아무거나 네 개"로 통과한다.
  2. 남은 것을 **작업 중에** 알려 준다 — 끝나고 "못 했네" 하는 것은 정직할 뿐
     도움이 안 된다
  3. 없는 요구를 지어내지 않는다 — 반쯤 아는 체하는 체크리스트는 없느니만 못하다
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.plan import (
    check,
    extract,
    forbids_writes,
    remaining_note,
    summary_note,
    wants_an_artifact,
)

_WISHKET = "위시켓과 크몽에서 AI 챗봇 외주 공고를 찾아서 최소 4개는 직접 열어 읽고 표로 정리해줘"

# 어제 실제로 통과했던 상태: 출처 4개인데 크몽은 0건, 위시켓 공고도 하나뿐.
_YESTERDAY = [
    "https://www.kpc.or.kr/x",
    "https://www.kmooc.kr/y",
    "https://www.wishket.com/project/",
    "https://www.wishket.com/project/132082/",
]


def _step(tool: str, ok: bool = True) -> dict[str, Any]:
    return {"tool": tool, "ok": ok}


def test_it_pulls_count_and_sites_out_of_the_ask() -> None:
    kinds = {(r.kind, r.label) for r in extract(_WISHKET)}
    assert ("count", "4개 이상 직접 열어 읽기") in kinds
    assert ("site", "위시켓에서 하기") in kinds
    assert ("site", "크몽에서 하기") in kinds


def test_read_only_analysis_does_not_turn_a_later_evidence_table_into_a_file() -> None:
    prompt = (
        "파일을 수정하거나 외부 서비스에 쓰지 말고 조사·분석만 해라. "
        "확인한 사실과 추론을 분리하고 근거표를 만들어라."
    )

    assert forbids_writes(prompt) is True
    assert wants_an_artifact(prompt) is False
    assert "artifact" not in {item.kind for item in extract(prompt, must_observe=True)}


def test_an_explicit_file_request_is_still_an_artifact() -> None:
    prompt = "조사 결과를 워드 파일로 만들어줘"

    assert forbids_writes(prompt) is False
    assert wants_an_artifact(prompt) is True


def test_local_documents_and_web_sources_are_counted_separately() -> None:
    prompt = (
        "로컬 문서 3개를 직접 읽고, 공개 웹에서 서로 다른 자료 3개를 "
        "본문까지 직접 열어 읽어라."
    )
    requirements = [item for item in extract(prompt, must_observe=True) if item.kind == "count"]

    assert [(item.source_scope, item.target) for item in requirements] == [
        ("local", 3),
        ("web", 3),
    ]
    results = check(
        requirements,
        sources=[
            r"E:\docs\one.md",
            r"E:\docs\two.md",
            r"E:\docs\three.md",
            "https://source.test/only-one",
        ],
        steps=[],
        answer="- 하나\n- 둘\n- 셋",
        listed_entities_grounded=True,
    )
    by_scope = {item.source_scope: ok for item, ok, _saw in results}
    assert by_scope == {"local": True, "web": False}


def test_counting_four_of_anything_no_longer_passes() -> None:
    """★ 어제 이 상태가 통과했다. 넷을 셌지만 크몽은 하나도 없었다."""
    results = check(extract(_WISHKET), sources=_YESTERDAY, steps=[])
    by_label = {r.label: (ok, saw) for r, ok, saw in results}
    assert by_label["4개 이상 직접 열어 읽기"] == (False, "2개 읽음")
    assert by_label["크몽에서 하기"] == (False, "거기서 아무것도 안 함")


def test_what_is_left_is_said_while_there_is_still_time() -> None:
    note = remaining_note(check(extract(_WISHKET), sources=_YESTERDAY, steps=[]))
    assert "크몽" in note
    assert "검색을 되풀이하지 말고" in note
    assert "위시켓" not in note, "이미 된 것까지 다시 시키면 잔소리가 된다"


def test_meeting_everything_says_nothing() -> None:
    sources = _YESTERDAY + [
        "https://kmong.com/gig/1",
        "https://kmong.com/gig/2",
    ]
    results = check(extract(_WISHKET), sources=sources, steps=[])
    assert remaining_note(results) == ""
    assert summary_note(results) == ""


def test_a_drive_input_does_not_count_as_a_named_sites_result() -> None:
    """복합 작업: 이력서 1건 + 공고 2건을 공고 3건으로 세면 안 된다."""
    reqs = extract("Google Drive 이력서를 읽고 사람인 공고 3개를 직접 열어 읽어줘")
    sources = [
        "https://docs.google.com/document/d/resume/edit",
        "https://www.saramin.co.kr/jobs/1",
        "https://www.saramin.co.kr/jobs/2",
    ]

    result = next(
        row for row in check(reqs, sources=sources, steps=[]) if row[0].kind == "count"
    )

    assert result[1:] == (False, "2개 읽음")


def test_the_checklist_shows_both_sides() -> None:
    note = summary_note(check(extract(_WISHKET), sources=_YESTERDAY, steps=[]))
    assert "✅" in note and "❌" in note
    assert "크몽" in note


# ── 행위 요구 ────────────────────────────────────────────────────────────────
def test_saving_a_draft_is_checked_against_the_tool_that_did_it() -> None:
    reqs = extract("이 내용으로 블로그에 임시저장까지 해줘")
    assert [r.label for r in reqs] == ["임시저장"]

    failed = check(reqs, sources=[], steps=[_step("naver_blog_save_draft", ok=False)])
    assert failed[0][1] is False and failed[0][2] == "실행 안 됨"

    done = check(reqs, sources=[], steps=[_step("naver_blog_save_draft")])
    assert done[0][1] is True


def test_explicit_form_submit_is_kept_in_the_plan_until_confirmed_click_runs() -> None:
    reqs = extract("입력값을 확인한 뒤 Submit을 정확히 한 번만 실행해")
    assert [r.label for r in reqs] == ["폼 제출"]

    ordinary = check(reqs, sources=[], steps=[_step("browser_click")])
    assert ordinary[0][1] is False

    submitted = check(reqs, sources=[], steps=[_step("browser_click_confirmed")])
    assert submitted[0][1] is True


def test_do_not_submit_does_not_invent_a_submit_requirement() -> None:
    assert extract("폼은 채우되 제출하지 말고 멈춰") == []


# ── 없는 요구를 지어내지 않는다 ──────────────────────────────────────────────
def test_plain_talk_yields_no_checklist() -> None:
    for prompt in ("오늘 기분 어때?", "학원 마케팅 전략 얘기해줘", "고마워"):
        assert extract(prompt) == [], prompt


def test_artifact_and_verification_are_deterministic_requirements(tmp_path) -> None:
    requirements = extract("파이썬 결과를 파일로 만들고 pytest 테스트를 통과시켜줘")
    assert [item.kind for item in requirements] == ["artifact", "verify"]

    output = tmp_path / "result.py"
    output.write_text("print('ok')\n", encoding="utf-8")
    steps = [
        {
            "tool": "local_write_file",
            "ok": True,
            "evidence": {
                "action": "local_write_file",
                "output_path": str(output),
                "verified": True,
            },
        },
        {
            "tool": "sandbox_run",
            "ok": True,
            "evidence": {"action": "sandbox_run", "exit_code": 0, "verified": True},
        },
    ]

    checked = check(requirements, sources=[], steps=steps)
    assert [(item.kind, ok) for item, ok, _ in checked] == [
        ("artifact", True),
        ("verify", True),
    ]


def test_selected_project_command_counts_as_real_verification(tmp_path) -> None:
    requirements = extract("버그를 고치고 pytest 테스트를 통과시켜줘")
    output = tmp_path / "fixed.py"
    output.write_text("VALUE = 2\n", encoding="utf-8")
    checked = check(
        requirements,
        sources=[],
        steps=[
            {
                "tool": "local_write_file",
                "ok": True,
                "evidence": {"output_path": str(output), "verified": True},
            },
            {
                "tool": "local_run_project_command",
                "ok": True,
                "evidence": {"exit_code": 0, "verified": True},
            },
        ],
    )

    # 2026-09-23 밤: 「고치고」가 이제 코드 요청으로 잡혀(「고쳐줘」와 같게) 산출물 요구도 선다 — 이 검사가 보는 것은 검증 칸이다.
    assert [(item.kind, ok, saw) for item, ok, saw in checked if item.kind == "verify"] == [
        ("verify", True, "프로젝트 검증 종료코드 0"),
    ]


def test_code_action_uses_the_selected_workspace_as_the_implicit_target() -> None:
    from alture_jarvis.plan import wants_code_action

    assert wants_code_action("이 버그 고쳐줘") is True
    assert wants_code_action("테스트해") is True
    assert wants_code_action("구조를 설명해줘") is False
    assert wants_code_action("하이하이") is False


def test_a_claimed_artifact_that_cannot_be_opened_is_not_complete(tmp_path) -> None:
    requirements = extract("결과를 엑셀 파일로 만들어줘")
    missing = tmp_path / "missing.xlsx"
    checked = check(
        requirements,
        sources=[],
        steps=[
            {
                "tool": "local_write_file",
                "ok": True,
                "evidence": {"output_path": str(missing), "verified": True},
            }
        ],
    )

    assert [(item.kind, ok, saw) for item, ok, saw in checked] == [
        ("artifact", False, "열 수 있는 산출물 없음")
    ]


def test_claude_changed_files_and_completed_tests_fill_both_requirements(tmp_path) -> None:
    changed = tmp_path / "alpha.py"
    changed.write_text("def multiply(a, b): return a * b\n", encoding="utf-8")
    requirements = extract("여러 파일을 수정하고 pytest 테스트를 통과시켜줘")
    checked = check(
        requirements,
        sources=[],
        steps=[
            {
                "tool": "claude_code_delegate",
                "ok": True,
                "evidence": {
                    "status": "completed",
                    "verified": True,
                    "git_changed": True,
                    "changed_paths": [str(changed)],
                },
            }
        ],
    )

    assert [(item.kind, ok) for item, ok, _ in checked] == [
        ("artifact", True),
        ("verify", True),
    ]


def test_research_prompts_do_not_gain_artifact_or_verify_requirements() -> None:
    prompts = (
        "위시켓에서 AI 에이전트 프로젝트 3개의 제목과 예산을 알려줘",
        "중앙대 소프트웨어학부 최근 경쟁률이 어떻게 되나요?",
        "오늘의집에서 조명 인기 상품 3개의 제품명과 가격을 알려줘",
    )
    for prompt in prompts:
        assert not ({"artifact", "verify"} & {item.kind for item in extract(prompt)}), prompt


def test_numbers_that_are_not_a_reading_quota_are_ignored() -> None:
    """'3박4일'·'4개월'·'500만 원'이 요구로 잡히면 안 된다."""
    for prompt in ("제주도 3박4일 여행 경비", "4개월치 매출 정리", "예산 500만 원짜리"):
        assert [r for r in extract(prompt) if r.kind == "count"] == [], prompt


def test_a_site_only_counts_when_it_was_actually_named() -> None:
    reqs = extract("공고 3개만 읽어줘")
    assert [r.kind for r in reqs] == ["count"], "안 시킨 사이트를 요구로 만들면 안 된다"


def test_count_requirement_survives_a_number_that_describes_a_condition() -> None:
    """조건을 서술하는 숫자가 앞에 있어도 **진짜 요구**를 찾아야 한다.

    2026-08-18 라이브(크몽 조사): "크몽에 처음 들어가는 **리뷰 0개** 신규 판매자가 …
    최소 6개를 뽑아줘" 를 던졌더니 앞의 `0개` 가 먼저 잡혔다. 0 은 범위 밖이라 버려지고,
    그 자리에서 탐색이 끝나 **개수 요구가 통째로 사라졌다.** 요구가 없으면 미달 판정도
    시작되지 않으므로, 6개 중 1개만 준 판이 `complete` 로 기록됐다.
    """
    reqs = extract("리뷰 0개 신규 판매자 기준으로 공고를 최소 6개 열어 읽어라")
    counts = [r for r in reqs if r.kind == "count"]
    assert [r.target for r in counts] == [6]

    # 수식어가 없으면 예전처럼 첫 값을 쓴다.
    plain = [r for r in extract("공고 4개를 열어 읽어라") if r.kind == "count"]
    assert [r.target for r in plain] == [4]

    # 단위가 아닌 숫자(5점)에 끌려가지 않는다.
    mixed = [r for r in extract("평점 5점 이상인 곳 중에서 3개를 직접 열어 확인해줘") if r.kind == "count"]
    assert [r.target for r in mixed] == [3]

    # 요구가 정말 없으면 만들어내지 않는다.
    assert [r for r in extract("리뷰 0개인 판매자를 찾아줘") if r.kind == "count"] == []


def test_making_an_event_counts_as_asking_for_one() -> None:
    """"일정 만들어줘"가 요구로 안 잡혔다 (2026-08-20).

    쓰기 벤치의 캘린더 과제가 바로 이 문장이라, **자기가 시킨 일을 계획 층이 못 봤다.**
    걸음 넷이 전부 실패했는데도 "대조할 요구를 못 뽑음"으로 끝나 위임 성공 쪽에 섰다.

    낱말을 넓히기 전에 재 봤다 — 30일 438개 프롬프트에서 새로 걸리는 것 1건,
    놓치는 것 0건.
    """
    from alture_jarvis.plan import extract, mutating_google_tools

    prompt = "내일 오후 3시에 '자비스 실행 점검' 일정을 30분짜리로 만들어줘."
    targets = [item.target for item in extract(prompt) if item.kind == "action"]
    assert "google_calendar_create" in targets
    # 라우터도 같은 목록을 본다 — 한 줄을 더하면 계획 대조와 갈래가 같이 좋아진다.
    assert "google_calendar_create" in mutating_google_tools(prompt)


def test_looking_at_events_still_is_not_making_one() -> None:
    """넓힌 만큼 조회가 새어 들어오지 않는지 같이 붙든다."""
    from alture_jarvis.plan import mutating_google_tools

    assert mutating_google_tools("오늘 일정 정리해서 보여줘") == []
    assert mutating_google_tools("내일 일정 뭐 있는지 알려줘") == []


def test_a_document_asked_for_by_format_is_an_artifact() -> None:
    """「경쟁 분석 **문서로** 정리해줘」가 산출물 요구로 안 잡혔다 (2026-09-10).

    사슬 벤치(조사→쓰기)에서 이 한 줄이 **2판 중 2판** 실패했다. 조사는 다 하고
    표까지 짜 놓고 파일을 안 만들었는데, 계획 층이 산출물 요구를 안 뽑아서
    **되묻는 사람이 없었다.** 모델이 게으른 게 아니라 우리가 안 시킨 것이다.

    같은 벤치의 「문서로 정리해줘」(사람인)는 통과했는데, 그건 규칙이 맞아서가
    아니라 뒷문장의 「표로 넣어줘」가 대신 걸려 준 **운**이었다.

    넓히기 전에 재 봤다 — 실제 프롬프트 833개에서 판정이 바뀐 것은 **이 한 줄뿐**,
    새로 걸린 오탐 0건.
    """
    from alture_jarvis.plan import extract, wants_an_artifact

    prompt = (
        "위시켓에서 AI 에이전트 개발 프로젝트 3개를 조사해서 "
        "경쟁 분석 문서로 정리해줘. 어떤 기술 스택이 자주 요구되는지 정리해줘."
    )
    assert wants_an_artifact(prompt) is True
    assert "artifact" in {item.kind for item in extract(prompt)}


def test_tidying_a_document_is_still_not_making_one() -> None:
    """넓힌 만큼 새는지 반대쪽도 같이 붙든다.

    「문서**를** 정리해줘」는 읽고 요약해 달라는 말이지 파일을 만들라는 말이 아니다.
    그래서 `_REAL_FILE_TARGET` 에 「문서」를 넣지 않고 **조사 「로」를 필수로** 잡았다.
    """
    from alture_jarvis.plan import wants_an_artifact

    assert wants_an_artifact("이 문서를 정리해줘") is False
    assert wants_an_artifact("문서 정리해줘") is False
    assert wants_an_artifact("보고서 읽고 핵심만 정리해줘") is False
    assert wants_an_artifact("노션 문서들 훑고 정리해줘") is False


def test_frontend_card_counts_and_displayed_probabilities_are_not_research_or_math() -> None:
    """UI 수량·표시값이 자료 읽기와 계산 요구로 오염되면 완료 후 루프가 돈다."""
    from alture_jarvis.plan import extract, wants_a_computation

    prompt = (
        "index.html로 오로라 페이지를 만들어줘. 아이슬란드·트롬쇠·옐로나이프 "
        "3개 목적지 카드를 만들고 카드마다 오로라 확률과 기온을 표시해. "
        "browser_open으로 화면을 확인하고 테스트도 실행해."
    )
    requirements = extract(prompt, must_observe=True)
    assert [item for item in requirements if item.kind == "count"] == []
    assert [item for item in requirements if item.kind == "action" and item.target == "sandbox_run"] == []
    assert wants_a_computation(prompt) is False
    assert wants_a_computation("세 목적지의 오로라 확률 평균을 계산해줘") is True


def test_full_frontend_job_keeps_ui_counts_out_of_the_research_plan() -> None:
    """긴 실사용 문장에서도 뒤쪽의 파일·검증 표현이 UI 수량을 오염시키지 않는다."""
    from alture_jarvis.plan import extract

    prompt = (
        "AURORA라는 한밤의 오로라 항해 관측소를 index.html 단일 파일로 만들어줘. "
        "깊은 밤 색감과 빛나는 오로라를 사용하고, 서로 다른 3개 관측 목적지 카드와 "
        "각 목적지의 관측 확률을 보여줘. 카드와 버튼은 클릭해 반응해야 해. "
        "완성 뒤 local_preview_page로 열고 browser_open, browser_snapshot, browser_click으로 "
        "화면과 상호작용을 직접 확인해. local_run_project_command로 검증하고 "
        "검증용 임시 파일은 삭제해."
    )
    requirements = extract(prompt, must_observe=True)

    assert [item for item in requirements if item.kind == "count"] == []
    assert [item for item in requirements if item.kind == "action" and item.target == "sandbox_run"] == []
    assert [item.kind for item in requirements].count("artifact") == 1
