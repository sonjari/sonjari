"""숫자는 **자기가 세는 낱말**에 붙는다.

★ 2026-09-03 스모크. 문서 하나를 지목해 놓고

    …WORKSPACE_UX_ARCHITECTURE.ko.md 파일을 직접 읽고 핵심 3개를 정리해줘.

라고 했더니 계획층이 `3개` 를 **읽기 개수**로 가져가 지목한 문서 말고 두 개를 더
읽었다. 원인은 프롬프트 전체에서 대표 숫자 하나를 뽑는 구조였다. `_scoped_count_targets`
는 숫자 뒤 180자 안에 「파일」이 있으면 무엇을 세든 로컬 읽기 개수로 만들었다.

판정은 `alture_jarvis.quantities` **한 곳**에서만 한다. 계획층과 작업계약이 같은
함수를 쓴다 — 두 군데서 세면 반드시 갈린다(이 저장소가 상한·분류표에서 겪은 것).

역할 다섯:

    input_cardinality   가서 읽어야 할 것 — 「공고 3개를 열어 읽어라」
    output_cardinality  만들어 내놓을 것 — 「핵심 3개」·「강점 3개」·「각주 3개」
    action_cardinality  실제 수행 횟수 — 「세 번 시도해줘」
    constraint_value    거르는 값 — 「경력 3년 이상」
    range_endpoint      범위 끝점 — 「1순위부터 3순위까지」
"""

from __future__ import annotations

from alture_jarvis import quantities
from alture_jarvis.plan import extract
from alture_jarvis.task_contract import compile_task_contract

SMOKE = (
    r"C:\work\monorepo\docs\WORKSPACE_UX_ARCHITECTURE.ko.md 파일을 직접 읽고 "
    "핵심 3개를 채팅으로 정리해줘."
)
#: 실측에서 계약이 가장 많이 마주친 모양(35판). 여기 개수를 잃으면 상세를 안 연다.
LISTING = "크몽에서 AI 자동화 관련 서비스 상위 5개의 제목과 가격을 알려줘"


def _roles(prompt: str) -> list[tuple[str, str, int]]:
    return [
        (item.role, item.object_quote, item.value)
        for clause in compile_task_contract(prompt).clauses
        for item in clause.quantities
    ]


def test_the_smoke_no_longer_asks_for_three_documents() -> None:
    """이것이 이번 작업의 재현 조건이다."""
    counts = [r for r in extract(SMOKE, has_named_source=True) if r.kind == "count"]

    assert counts == [], f"지목한 문서 하나인데 읽기 개수가 생겼다: {counts}"
    assert _roles(SMOKE) == [("output_cardinality", "핵심", 3)]


def test_a_listing_request_keeps_its_read_count() -> None:
    """★ 반대 방향. 여기서 개수를 잃으면 상세를 안 열고 목록만 베낀다."""
    counts = [r.target for r in extract(LISTING, has_named_source=True) if r.kind == "count"]

    assert counts == [5]
    assert _roles(LISTING) == [("input_cardinality", "서비스", 5)]


def test_a_product_count_does_not_steal_a_real_read_count() -> None:
    """둘이 한 문장에 같이 와도 각자 주인이 있다."""
    ask = "로컬 문서 3개를 읽고 강점 3개를 뽑아줘"

    assert [r.target for r in extract(ask) if r.kind == "count"] == [3]
    assert _roles(ask) == [
        ("input_cardinality", "문서", 3),
        ("output_cardinality", "강점", 3),
    ]


def test_every_role_is_told_apart() -> None:
    cases = {
        "공고 3개를 각각 상세 페이지까지 직접 열어 읽어라": "input_cardinality",
        "각주를 3개 이상 달아줘": "output_cardinality",
        "세 번 시도해줘": "action_cardinality",
        "경력 3년 이상인 공고를 찾아줘": "constraint_value",
        "사람인에서 1순위부터 3순위까지 찾아줘": "range_endpoint",
    }
    for ask, want in cases.items():
        assert _roles(ask)[0][0] == want, ask


def test_the_counted_word_can_follow_the_number() -> None:
    """한국어는 둘 다 쓴다. 뒤를 안 보면 실측 unknown 의 최대 덩어리가 남는다."""
    assert _roles("상위 5개 서비스를 알려줘")[0][:2] == ("input_cardinality", "서비스")
    assert _roles("서비스 5개를 알려줘")[0][:2] == ("input_cardinality", "서비스")


def test_ownership_needs_a_real_span() -> None:
    """지어낸 소유권은 안 쓴다 — 원문 조각이 실제로 그 자리에 있어야 한다."""
    prompt = "로컬 문서 3개를 읽고 공개 웹 자료 2개도 읽어줘"
    for clause in compile_task_contract(prompt).clauses:
        for item in clause.quantities:
            assert prompt[item.span_start : item.span_end] == item.quote
            if item.object_quote:
                assert (
                    prompt[item.object_span_start : item.object_span_end]
                    == item.object_quote
                )
            else:
                assert item.object_span_start == -1


def test_a_letter_glued_number_is_not_a_quantity() -> None:
    """「P0/P1/P2 개선」이 「2개」로 잡혀 있었다."""
    assert _roles("P0/P1/P2 개선 순서를 정해줘") == []


def test_a_section_minimum_only_counts_what_is_produced() -> None:
    """「경력 3년」이 섹션의 최소 항목 수가 되면 안 된다."""
    made = compile_task_contract("경력 3년 이상인 공고를 비교해서 표로 정리해줘")
    assert all(section.min_items == 0 for section in made.deliverable_sections)

    real = compile_task_contract("강점 3개를 뽑아서 표로 정리해줘")
    assert any(section.min_items == 3 for section in real.deliverable_sections)


def test_only_one_place_decides_what_a_number_counts() -> None:
    """★ 같은 것을 두 군데서 세면 반드시 갈린다."""
    import alture_jarvis.plan as plan_module
    import alture_jarvis.task_contract as contract_module

    assert plan_module.quantity_role is quantities.quantity_role
    assert contract_module._quantity_role is quantities.quantity_role


def test_asking_what_exists_is_answered_by_the_listing() -> None:
    """★ 2026-09-03 라이브. 「docs 폴더에 어떤 문서들이 있는지 알려줘」에

        시킨 것 대조: ❌ 근거가 되는 대상 실제로 읽기 — 0개 실제로 읽음

    가 붙었다. **목록이 곧 답인 요청**인데 본문을 안 읽었다고 미달로 찍었다.
    「무엇이 있는가」는 열거가 답이다.
    """
    from alture_jarvis.plan import wants_a_count  # noqa: PLC0415

    for ask in (
        r"E:\docs 폴더에 어떤 문서들이 있는지 알려줘",
        "사람인에 어떤 공고가 있는지 보여줘",
    ):
        assert wants_a_count(ask) is True, ask
        kinds = {r.kind for r in extract(ask, has_named_source=True, must_observe=True)}
        assert "observe" not in kinds, f"목록이 답인데 읽기를 강제한다: {ask}"


def test_asking_about_properties_still_needs_the_body() -> None:
    """★ 반대 방향. 속성을 물으면 목록 줄로는 답이 안 된다 — 여기서 느슨해지면
    2026-09-02 사고(목록만 보고 마감일을 단정)가 되돌아온다."""
    from alture_jarvis.plan import wants_a_count  # noqa: PLC0415

    for ask in (
        "사람인에서 공고 3개 찾아서 각각 마감일을 알려줘",
        "어떤 공고가 있는지 알려주고 상세 내용도 읽어줘",
    ):
        assert wants_a_count(ask) is False, ask
