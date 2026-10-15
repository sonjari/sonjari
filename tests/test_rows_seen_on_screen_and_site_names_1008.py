"""화면에서 본 줄에는 「근거가 약하다」고 하지 않는다 · 제목 속 낱말을 사이트 이름으로 배우지 않는다 (2026-10-08).

운영 판 하나(조회 폼 → 정렬 · 거르개 → 결과 목록의 위 다섯 줄을 표로)에서 둘이 같이 나왔다.

① 맞는 답 끝에 「5개를 열어 보라고 하셨는데 본문까지 연 것은 하나도 없습니다 … 근거가 약합니다」가 붙었다. 값은 전부 화면에서
   본 것이었다. 「연 쪽수」는 근거의 대리 눈금이다 — 답의 줄이 도구가 돌려준 글에 그대로 있으면 그 경고는 틀린 말이다.
   요청의 낱말(「정렬해서 N개」)로 가르지 않는다: 운영 요청 1,796개에 대 보니 달라진 둘이 다 틀린 방향이었다.
② 그 판이 끝나자 요청 속 「○○ △△에서」의 **△△** 가 사이트 이름으로 확정됐다(제목 「○○ △△」에 그 낱말이 들어 있다는 이유).
   다음 판부터 계획에 「△△에서 하기」가 섰다. 그 PC 의 배운 표 20개 중 8개가 이런 것이었다.
"""
from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.agent import BrowserAgent, table_rows_seen_by_tools
from alture_jarvis.site_atlas import SiteAtlas, _host_carries_the_name, _title_names_it

ASK = "가람몰에서 무선 이어폰을 가격 낮은 순으로 5개만 이름·가격과 함께 표로 정리해줘"
LISTING = "\n".join(f"상품 이어폰{n}호 0{n}시간 재생 {n}2,900원~ 무료배송" for n in range(1, 7))
TABLE = "| 순위 | 이름 | 재생 | 가격 |\n| :--: | --- | --- | ---: |\n" + "\n".join(
    f"| {n} | 이어폰{n}호 | {n}시간 | {n}2,900원 |" for n in range(1, 6))
SAW_THE_LIST = [{"role": "user", "content": ASK}, {"role": "tool", "content": LISTING}]
LOOKED = [{"step": 1, "tool": "browser_snapshot", "arguments": {}, "ok": True, "status": "", "error": "",
           "evidence": {"url": "https://shop.example/list?sort=price"}}]


# ── ① 화면에서 본 줄 ─────────────────────────────────────────────────────────────────────────────────────────
def test_rows_whose_every_cell_was_on_screen_are_counted() -> None:
    assert table_rows_seen_by_tools(TABLE, SAW_THE_LIST) == 5, "머리 줄 · 구분 줄 · 순위 칸은 값이 아니다"


def test_number_formatting_does_not_hide_a_match() -> None:
    """화면의 「01시간」·「12,900원~」과 답의 「1시간」·「12,900원」은 같은 값이다."""
    assert table_rows_seen_by_tools("| 이어폰1호 | 1시간 | 12900원 |", SAW_THE_LIST) == 1


def test_two_values_joined_in_one_cell_are_matched_piece_by_piece() -> None:
    """모델이 두 칸을 「이름 → 가격」·「1시간 / 12,900원」으로 묶어 써도 판정이 흔들리지 않는다."""
    joined = "\n".join(f"| {n} | 이어폰{n}호 | {n}시간 → {n}2,900원 |" for n in range(1, 6))
    assert table_rows_seen_by_tools(joined, SAW_THE_LIST) == 5
    half_invented = "| 1 | 이어폰1호 | 1시간 → 99,999원 |"
    assert table_rows_seen_by_tools(half_invented, SAW_THE_LIST) == 0, "조각 하나라도 본 글에 없으면 그 칸은 안 본 것"


def test_a_row_with_one_cell_nobody_saw_is_not_counted() -> None:
    """열어야 나오는 값을 목록만 보고 채운 줄 — 경고를 받아야 하는 바로 그 줄이다."""
    invented = TABLE.replace("| 3 | 이어폰3호 | 3시간 |", "| 3 | 이어폰3호 | 방수 IPX7 |")
    assert table_rows_seen_by_tools(invented, SAW_THE_LIST) == 4


def test_nothing_is_counted_when_no_tool_returned_text() -> None:
    assert table_rows_seen_by_tools(TABLE, [{"role": "user", "content": LISTING}]) == 0
    assert table_rows_seen_by_tools(TABLE, None) == 0


def test_the_weak_sourcing_warning_is_not_added_to_rows_read_off_the_screen() -> None:
    assert "근거가 약합니다" in BrowserAgent._goal_shortfall_check(ASK, LOOKED), "답과 본 글을 안 주면 예전 그대로"
    assert BrowserAgent._goal_shortfall_check(ASK, LOOKED, TABLE, SAW_THE_LIST) == ""


def test_the_warning_stays_when_the_rows_were_not_on_screen() -> None:
    memory_only = [{"role": "user", "content": ASK}, {"role": "tool", "content": "검색 결과가 없습니다"}]
    assert "근거가 약합니다" in BrowserAgent._goal_shortfall_check(ASK, LOOKED, TABLE, memory_only)
    too_few = "\n".join(TABLE.splitlines()[:5])  # 머리 · 구분 · 세 줄
    assert BrowserAgent._goal_shortfall_check(ASK, LOOKED, too_few, SAW_THE_LIST) != "", "다섯을 시켰는데 본 줄은 셋"


def test_an_answer_whose_rows_were_on_screen_is_not_bounced_back() -> None:
    """답을 낸 순간의 대조는 답을 받지 않아 「0개」였다 — 맞는 표를 낸 판마다 한 번씩 되받혀 다시 열러 갔다."""
    from alture_jarvis.agent import count_met_by_rows_on_screen, named_sources
    from alture_jarvis.plan import check as check_plan, extract as extract_plan

    plan = extract_plan(ASK, has_named_source=bool(named_sources(ASK)))
    before = check_plan(plan, sources=[], steps=LOOKED)
    counts = [(req, ok) for req, ok, _saw in before if req.kind == "count"]
    assert counts and not counts[0][1], "답을 안 보면 개수 요구는 미달이다(되받기가 나가던 까닭)"
    assert not counts[0][0].grounding_required, "「표로 정리」 — 판정은 답에 N줄이면 충족"

    after = count_met_by_rows_on_screen(before, table_rows_seen_by_tools(TABLE, SAW_THE_LIST))
    assert all(ok for req, ok, _saw in after if req.kind == "count")
    assert "본 화면에 있음" in next(saw for req, _ok, saw in after if req.kind == "count")

    too_few = count_met_by_rows_on_screen(before, 3)
    assert not any(ok for req, ok, _saw in too_few if req.kind == "count"), "다섯을 시켰는데 본 줄이 셋이면 그대로 미달"
    assert count_met_by_rows_on_screen(before, 0) is before


def _far_apart_listing() -> list[dict[str, str]]:
    """줄 사이에 긴 안내 글이 끼어 있는 목록 — 화면의 줄들이 서로 멀리 떨어져 있다."""
    filler = " 배송 안내와 카드 혜택 설명이 길게 이어집니다." * 20
    body = "".join(f"상품 이어폰{n}호 0{n}시간 재생 {n}2,900원~ 무료배송{filler}\n" for n in range(1, 7))
    return [{"role": "tool", "tool_name": "browser_snapshot", "content": body}]


def test_values_borrowed_from_another_row_do_not_make_a_seen_row() -> None:
    """칸마다 화면 어딘가에 있는 것으로는 모자라다 — 이름만 옮기고 값은 다른 줄에서 끌어온 줄은 본 줄이 아니다."""
    seen = _far_apart_listing()
    assert table_rows_seen_by_tools("| 이어폰1호 | 1시간 | 12,900원 |", seen) == 1
    assert table_rows_seen_by_tools("| 이어폰1호 | 5시간 | 52,900원 |", seen) == 0, "5시간·52,900원은 다섯째 줄의 값이다"


def test_a_name_whose_whole_row_was_on_screen_is_not_called_unread() -> None:
    """화면 보기로 읽은 목록의 줄을 옮긴 답 — 본문 읽기 도구를 안 썼다고 「읽지 않고 적은 것」이 붙었다."""
    seen = _far_apart_listing() + [{"role": "tool", "tool_name": "browser_extract", "content": "장바구니 안내: 오늘 주문하면 내일 도착합니다."}]
    answer = "| 이름 | 재생 | 가격 |\n| --- | --- | --- |\n| 이어폰1호 | 1시간 | 12,900원 |\n| 이어폰2호 | 2시간 | 22,900원 |"

    assert BrowserAgent._listed_entity_grounding_check(answer, seen) == ""

    borrowed = answer.replace("| 이어폰2호 | 2시간 | 22,900원 |", "| 이어폰2호 | 방수 IPX7 | 22,900원 |")
    warned = BrowserAgent._listed_entity_grounding_check(borrowed, seen)
    assert "이어폰2호" in warned and "이어폰1호" not in warned, "세부를 지어낸 줄의 이름만 남는다"


def test_a_requirement_that_needs_pages_read_is_never_met_by_rows_alone() -> None:
    from alture_jarvis.agent import count_met_by_rows_on_screen
    from alture_jarvis.plan import Requirement

    must_read = Requirement("count", "3개 이상 직접 열어 읽기", 3, grounding_required=True)
    assert count_met_by_rows_on_screen([(must_read, False, "0개 읽음")], 5) == [(must_read, False, "0개 읽음")]


# ── ② 사이트 이름 배우기 ─────────────────────────────────────────────────────────────────────────────────────
def test_a_site_name_is_a_whole_title_piece_or_its_head() -> None:
    assert _title_names_it("가람몰", "가람몰: 무선 이어폰")
    assert _title_names_it("가람몰", "무선 이어폰 | 가람몰")
    assert _title_names_it("가람몰", "가람몰 온라인 매장")
    assert _title_names_it("가람 몰", "이어폰 - 가람몰, 모두의 가게")
    assert _title_names_it("K-Garam", "K-Garam 지원 포털"), "붙임표가 든 이름은 쪼개지 않는다"


def test_the_tail_of_another_name_or_a_word_in_a_sentence_is_not_a_site_name() -> None:
    assert not _title_names_it("이어폰", "가람몰 이어폰"), "다른 이름 뒤에 붙은 꼬리"
    assert not _title_names_it("이어폰", "무선 이어폰 추천 모음 | 가람몰")
    assert not _title_names_it("Springfield", "Homes for rent in Springfield, IL | Rentals")


def test_an_english_name_must_be_in_the_address() -> None:
    assert _host_carries_the_name("Garam", "garam.com") and _host_carries_the_name("K-Garam", "k-garam.go.kr")
    assert not _host_carries_the_name("Springfield", "rentals.com"), "조각의 머리에 온 도시 이름도 주소에는 없다"
    assert not _host_carries_the_name("GB", "forum.example")
    assert not _host_carries_the_name("Go", "google.com"), "두 글자 이하는 같을 때만"


def test_a_word_from_a_compound_title_is_not_learned(tmp_path: Path) -> None:
    atlas = SiteAtlas(tmp_path / "site_atlas.json")
    for page in ("https://shop.garam.example/a", "https://shop.garam.example/b", "https://shop.garam.example/c"):
        atlas.learn("이어폰", page, "가람몰 이어폰")
        atlas.learn("가람몰", page, "가람몰 이어폰")
    assert not atlas.knows("이어폰")
    assert atlas.host_for("가람몰") == "garam.example"


def test_names_learned_under_the_old_rule_are_dropped_on_load(tmp_path: Path) -> None:
    """옛 표에는 주소만 있고 제목이 없다 — 한글 이름은 버리고(다시 보면 새 규칙으로 배운다), 영문 이름은 주소로 가른다."""
    path = tmp_path / "site_atlas.json"
    two = ["https://a.example/1", "https://a.example/2"]
    path.write_text(json.dumps({"seen": {
        "이어폰": {"garam.example": two}, "가람몰": {"garam.example": two},
        "Garam": {"garam.example": two}, "Springfield": {"rentals.example": two},
    }}, ensure_ascii=False), encoding="utf-8")

    atlas = SiteAtlas(path)

    assert not atlas.knows("이어폰") and not atlas.knows("가람몰")
    assert atlas.host_for("Garam") == "garam.example"
    assert not atlas.knows("Springfield")


def test_a_table_written_under_the_new_rule_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "site_atlas.json"
    atlas = SiteAtlas(path)
    atlas.learn("가람몰", "https://garam.example/a", "가람몰")
    atlas.learn("가람몰", "https://garam.example/b", "이어폰 | 가람몰")

    again = SiteAtlas(path)

    assert json.loads(path.read_text(encoding="utf-8"))["rule"] == 2
    assert again.host_for("가람몰") == "garam.example"
