"""Phase 1 작업 계약은 실행을 바꾸지 않고 원문 소유 관계를 보존한다."""

from __future__ import annotations

import json

from alture_jarvis.plan import Requirement
from alture_jarvis.task_contract import compile_task_contract


COMPLEX_PROMPT = """복합 분석 실전 점검이다. 파일을 수정하거나 외부 서비스에 쓰지 말고 조사·분석만 해라.
1) 아래 로컬 문서 3개를 각각 직접 읽어라.
2) 공개 웹 자료 3개의 서로 다른 본문을 직접 읽어라.
3) 현재 자비스를 계획, 컨텍스트, 도구 선택, 진행, 검증, 정지의 6개 축으로 비교해라.
4) 사실과 추론을 분리하고 근거표를 만들어라.
5) 강점 3개, 병목 3개, P0/P1/P2 우선순위와 각각의 재현 과제를 제시해라."""


def test_every_clause_is_an_exact_slice_of_the_original_prompt() -> None:
    contract = compile_task_contract(COMPLEX_PROMPT)

    assert len(contract.clauses) >= 7
    for clause in contract.clauses:
        assert COMPLEX_PROMPT[clause.span_start : clause.span_end] == clause.quote
    # 저장 장부에 그대로 들어갈 수 있어야 한다.
    json.dumps(contract.to_dict(), ensure_ascii=False)


def test_numbers_belong_to_their_own_clauses_instead_of_one_global_target() -> None:
    contract = compile_task_contract(COMPLEX_PROMPT)
    local = next(clause for clause in contract.clauses if clause.source_scope == "local")
    web = next(clause for clause in contract.clauses if clause.source_scope == "web")
    comparison = next(clause for clause in contract.clauses if "compare" in clause.operations)

    assert [(item.value, item.unit) for item in local.quantities] == [(3, "개")]
    assert [(item.value, item.unit) for item in web.quantities] == [(3, "개")]
    assert (6, "개") in [(item.value, item.unit) for item in comparison.quantities]
    assert local.id != web.id != comparison.id


def test_read_only_is_a_task_policy_and_a_negated_mutation_is_not_work() -> None:
    contract = compile_task_contract(COMPLEX_PROMPT)
    prohibition = next(clause for clause in contract.clauses if "수정하거나" in clause.quote)

    assert contract.side_effect_policy == "read_only"
    assert "mutate_or_create" not in prohibition.operations


def test_contract_reuses_the_operational_write_prohibition_ssot() -> None:
    contract = compile_task_contract(
        "파일을 읽고 핵심 3개를 정리해줘. 파일 수정이나 외부 서비스 쓰기는 하지 마."
    )

    assert contract.side_effect_policy == "read_only"
    assert "mutate_or_create" not in contract.clauses[-1].operations


def test_self_check_terms_in_different_clauses_do_not_merge() -> None:
    contract = compile_task_contract(COMPLEX_PROMPT)

    assert all("self_diagnose" not in clause.operations for clause in contract.clauses)


def test_a_real_self_diagnosis_stays_in_one_clause() -> None:
    contract = compile_task_contract("자비스 네 시스템 상태를 점검하고 병목 원인을 알려줘.")

    assert "self_diagnose" in contract.clauses[0].operations


def test_legacy_local_and_web_counts_bind_to_different_source_clauses() -> None:
    requirements = [
        Requirement(
            "count", "로컬 자료 3개 이상 직접 열어 읽기", 3,
            grounding_required=True, source_scope="local",
        ),
        Requirement(
            "count", "웹 자료 3개 이상 직접 열어 읽기", 3,
            grounding_required=True, source_scope="web",
        ),
    ]
    contract = compile_task_contract(COMPLEX_PROMPT, legacy_requirements=requirements)

    assert len(contract.legacy_bindings) == 2
    assert all(binding.clause_id for binding in contract.legacy_bindings)
    assert contract.legacy_bindings[0].clause_id != contract.legacy_bindings[1].clause_id


def test_read_nodes_precede_analysis_and_output_nodes() -> None:
    contract = compile_task_contract(COMPLEX_PROMPT)
    read_ids = {
        clause.id for clause in contract.clauses if "read_body" in clause.operations
    }
    comparison = next(clause.id for clause in contract.clauses if "compare" in clause.operations)

    assert read_ids
    assert all((read_id, comparison) in contract.dependencies for read_id in read_ids)
    assert contract.deliverable_sections


def test_the_contract_hears_the_most_common_ask_shape() -> None:
    """★ 2026-09-03. 이 모양에서 계약이 **아무것도 못 읽고 있었다.**

    과거 187판 중 46판이 침묵했는데 그중 35판이 아래 두 문장이었다 — 하필
    **자비스를 재는 벤치 프롬프트**다. 「읽어라」만 조회로 보고 「알려줘」·「상위 N」을
    몰라서, 재는 자가 재는 대상 앞에서 입을 다물었다.
    """
    for ask in (
        "크몽에서 AI 자동화 관련 서비스 상위 5개의 제목과 가격을 알려줘",
        "위시켓에서 AI 에이전트·자동화 관련 프로젝트 상위 5개의 제목과 예산을 알려줘",
        "사람인에서 공고 5개 스크랩해줘",
        "저 목록 좀 보여줘",
    ):
        clause = compile_task_contract(ask).clauses[0]
        assert "read_body" in clause.operations, ask


def test_you_hides_inside_ordinary_words() -> None:
    """「너」는 음절이라 `너무`·`건너편` 안에 숨는다 — 남의 사이트가 자기 진단이 됐다."""
    for ask in (
        "이 사이트 너무 느려 점검해줘",
        "건너편 가게도 점검해줘 오류 있나",
        "배송이 너무 느려 문제 있나 봐줘",
    ):
        clause = compile_task_contract(ask).clauses[0]
        assert "self_diagnose" not in clause.operations, ask

    for ask in ("너 지금 상태 점검해줘", "너의 병목이 뭔지 진단해줘"):
        assert "self_diagnose" in compile_task_contract(ask).clauses[0].operations, ask


def test_a_line_break_ends_a_clause() -> None:
    """한국어 요청은 마침표 없이 줄로 나열된다. 뭉치면 수량의 주인이 사라진다."""
    contract = compile_task_contract(
        "로컬 문서 3개를 읽어줘\n공개 웹 자료 2개도 본문까지 읽어줘\n둘을 비교해줘"
    )

    assert len(contract.clauses) == 3
    for clause in contract.clauses:
        assert "\n" not in clause.quote
    local = next(c for c in contract.clauses if c.source_scope == "local")
    web = next(c for c in contract.clauses if c.source_scope == "web")
    assert [q.value for q in local.quantities] == [3]
    assert [q.value for q in web.quantities] == [2]


def test_an_unbound_requirement_says_which_kind_of_unbound() -> None:
    """★ 빈 값 하나가 두 사실을 뜻하면 조용히 고장 난다.

    「후보가 없다」와 「후보가 여럿이라 포기했다」는 고치는 법이 정반대다. 실측에서
    못 묶은 118건 중 `no_clause` 는 **0건**이었고 105건이 「동작」 규칙까지만 걸린
    뒤 후보 2~5개로 남았다 — 절을 더 쪼갤 문제가 아니라 목적어 소유권이 없는 것이다.
    """
    requirements = [
        Requirement("count", "로컬 자료 3개 이상 직접 열어 읽기", 3,
                    grounding_required=True, source_scope="local"),
        Requirement("count", "웹 자료 3개 이상 직접 열어 읽기", 3,
                    grounding_required=True, source_scope="web"),
    ]
    bound = compile_task_contract(COMPLEX_PROMPT, legacy_requirements=requirements)
    assert all(item.reason == "" for item in bound.legacy_bindings)

    # 절이 하나뿐이면 어느 요구든 그 절로 묶인다. 여러 절이 같은 조건을 만족하면
    # 포기하되, **왜** 포기했는지를 남긴다.
    ambiguous = compile_task_contract(
        "자료를 읽어줘\n다른 자료도 읽어줘",
        legacy_requirements=[Requirement("count", "자료 2개 읽기", 2)],
    )
    unbound = ambiguous.legacy_bindings[0]
    assert unbound.clause_id == ""
    assert unbound.reason.startswith("ambiguous:2")
    assert "rules=" in unbound.reason
    assert ambiguous.summary()["legacy_unbound_reasons"] == ["ambiguous"]
    assert "legacy_unbound:ambiguous" in ambiguous.warnings


def test_a_site_requirement_finds_the_clause_that_names_it() -> None:
    """★ `site` 는 지금까지 **아무 규칙도 안 걸렸다** — 실측 9건 전부 rules=없음."""
    contract = compile_task_contract(
        "사람인에서 공고를 찾아줘\n찾은 것을 표로 정리해줘",
        legacy_requirements=[Requirement("site", "사람인에서 하기", 0)],
    )
    binding = contract.legacy_bindings[0]

    assert binding.clause_id, "사이트 이름이 적힌 절로 묶여야 한다"
    named = next(c for c in contract.clauses if c.id == binding.clause_id)
    assert "사람인" in named.quote


def test_narrowing_to_a_few_is_not_the_same_as_knowing_nothing() -> None:
    """하나로 못 좁혔다고 아무것도 모르는 것은 아니다.

    「실행해 통과를 확인해줘」처럼 요구가 정말 두 절에 걸쳐 있을 수 있다. 후보를
    버리면 다음 사람이 그 사실까지 잃는다 — 실측에서 못 묶은 110건 중 83건은
    3개 이하까지 좁혀져 있었다.
    """
    contract = compile_task_contract(
        "자료를 읽어줘\n다른 자료도 읽어줘",
        legacy_requirements=[Requirement("count", "자료 2개 읽기", 2)],
    )
    binding = contract.legacy_bindings[0]

    assert binding.clause_id == ""
    assert len(binding.clause_ids) == 2
    assert set(binding.clause_ids) <= {c.id for c in contract.clauses}
    assert contract.summary()["legacy_requirements_narrowed"] == 1


def test_a_hopeless_spread_keeps_no_candidates() -> None:
    """넷 이상이면 아는 게 없는 것과 같다 — 장부에 무의미한 줄을 쌓지 않는다."""
    contract = compile_task_contract(
        "읽어줘\n읽어줘\n읽어줘\n읽어줘\n읽어줘",
        legacy_requirements=[Requirement("count", "자료 2개 읽기", 2)],
    )
    assert contract.legacy_bindings[0].clause_ids == ()
