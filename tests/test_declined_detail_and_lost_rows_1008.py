"""목록 과제 세 판(2026-10-08 실기)에서 나온 넷.

① 「기사 본문은 열지 말고」의 「본문」을 보고 거꾸로 「상세를 원한다」로 읽어, 열지 말라는 말이 「5개 이상 직접 열어 읽기」가 됐다
   (기사를 네 번 대신 열었다 · 13걸음 · 171초).
② 「5개 저장소」의 「저장」을 행위로 읽어 「5개 실제로 처리하기」가 섰다.
③ 그 헛되받기에 모델이 「이미 답에 담았습니다 … 추가할 것이 없습니다」라고 대꾸하자 그 한 줄이 최종 답이 되어 목록이 사라졌다.
④ 따옴표 모양이 달라(도구 결과는 `\\"` · 화면은 굽은 따옴표) 화면에서 본 제목을 못 알아봤다.

운영 요청 1,809개에 옛·새 계획을 대 보니 달라진 것은 셋 — 측정 과제 둘과, 사람이 「상세 페이지는 열지 않아도 된다」고 적은 요청 하나였다.
"""
from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis import plan
from alture_jarvis.agent import (
    _answer_that_lost_its_rows,
    _nothing_new_since,
    _seen_text,
    list_items_seen_by_tools,
)


def _reqs(prompt: str) -> list[plan.Requirement]:
    return plan.extract(prompt)


# ── ① 거절한 상세는 원하는 것이 아니다 ─────────────────────────────────────────


@pytest.mark.parametrize("prompt", [
    "뉴스 첫 화면의 헤드라인 5개를 번호 목록으로 알려줘. 기사 본문은 열지 말고 목록에 보이는 제목 그대로.",
    "검색 결과 목록에 나오는 서비스 8개를 정리해줘. 상세 페이지는 열지 않아도 된다.",
    "게시판 첫 화면의 글 제목 5개를 알려줘. 글은 하나하나 들어가지 말고.",
])
def test_a_request_that_declines_the_detail_is_a_listing(prompt: str) -> None:
    assert plan.says_list_only(prompt)
    counts = [r for r in _reqs(prompt) if r.kind == "count"]
    # 개수 요구가 서지 않는 문장도 있다 — 서면 「목록으로 담기」여야 하고 읽기 근거를 따로 따지지 않는다.
    assert all(r.list_only and not r.grounding_required for r in counts)
    assert all("직접 열어 읽기" not in r.label for r in counts)


def test_the_headline_request_gets_a_listing_count() -> None:
    counts = [r for r in _reqs("뉴스 첫 화면의 헤드라인 5개를 번호 목록으로 알려줘. 기사 본문은 열지 말고 목록에 보이는 제목 그대로.") if r.kind == "count"]
    assert [(r.target, r.list_only, r.grounding_required) for r in counts] == [(5, True, False)]


@pytest.mark.parametrize("prompt", [
    "공고 3개를 찾아 본문을 열어 자격 요건을 비교해줘",
    "책 2권의 상세 페이지에 들어가서 쪽수를 확인해줘",
    # 하나는 거절하고 다른 것은 보라고 했다 — 보라고 한 것이 남는다.
    "댓글은 읽지 말고 글 3개의 본문을 열어서 요약해줘",
])
def test_a_request_that_wants_the_detail_still_reads(prompt: str) -> None:
    assert not plan.says_list_only(prompt)
    counts = [r for r in _reqs(prompt) if r.kind == "count"]
    assert counts and all(r.grounding_required for r in counts)


# ── ② 「저장소」는 저장이 아니다 ───────────────────────────────────────────────


def test_a_repository_is_not_a_save() -> None:
    kinds = {r.kind for r in _reqs("트렌딩 목록에서 맨 위 5개 저장소의 이름과 별 수를 알려줘")}
    assert "count_action" not in kinds


def test_saving_five_things_is_still_an_action() -> None:
    assert plan._is_action_count("검색 결과에서 5개 저장해줘", 5)
    assert not plan._is_action_count("맨 위 5개 저장소의 이름을 알려줘", 5)


# ── ③ 대꾸 한 줄이 줄 있는 답을 덮지 않는다 ────────────────────────────────────

_LIST = "오늘 트렌딩 상위 3개입니다.\n\n1. **alpha/one** — 1,204\n2. **beta/two** — 980\n3. **gamma/three** — 733\n"
_TALK_BACK = "이미 목록에서 상위 3개를 모두 확인해 답에 담았습니다. 추가할 것이 없습니다."


def _step(tool: str, url: str = "", ok: bool = True) -> dict[str, Any]:
    return {"tool": tool, "ok": ok, "evidence": {"url": url}}


_READ_ONCE = [_step("browser_open", "https://code.example/trending"), _step("browser_extract", "https://code.example/trending")]


def test_talking_back_to_us_does_not_erase_the_list() -> None:
    steps = _READ_ONCE + [_step("browser_extract", "https://code.example/trending"), _step("browser_close")]
    assert _answer_that_lost_its_rows(_TALK_BACK, [_LIST], [2], steps) == _LIST


def test_an_answer_that_drops_the_rows_after_reading_something_new_stands() -> None:
    """새로 읽고 나서 줄을 거뒀다면 그것은 고친 답이다 — 옛 목록을 되살리면 틀린 답으로 돌아간다."""
    steps = _READ_ONCE + [_step("browser_open", "https://code.example/other"), _step("browser_extract", "https://code.example/other")]
    assert _answer_that_lost_its_rows("다시 확인해 보니 조건에 맞는 저장소가 없었습니다.", [_LIST], [2], steps) == ""


def test_a_correction_is_never_overwritten_by_the_old_list() -> None:
    assert _answer_that_lost_its_rows("앞의 목록은 잘못 말씀드렸습니다. 그 화면은 어제 것이었습니다.", [_LIST], [2], _READ_ONCE) == ""


def test_an_answer_that_still_has_rows_is_left_alone() -> None:
    newer = "1. **alpha/one**\n2. **beta/two**\n"
    assert _answer_that_lost_its_rows(newer, [_LIST], [2], _READ_ONCE) == ""


def test_nothing_to_restore_when_no_earlier_answer_had_rows() -> None:
    assert _answer_that_lost_its_rows(_TALK_BACK, ["찾아보겠습니다."], [2], _READ_ONCE) == ""


def test_looking_again_at_the_same_page_is_not_new_ground() -> None:
    steps = _READ_ONCE + [_step("browser_snapshot"), _step("browser_extract", "https://code.example/trending"),
                          _step("browser_open", "https://code.example/x", ok=False)]
    assert _nothing_new_since(steps, 2)
    assert not _nothing_new_since(steps + [_step("browser_click", "https://code.example/trending")], 2)


# ── ④ 따옴표 모양은 값이 아니다 ────────────────────────────────────────────────


def test_quote_shapes_do_not_hide_a_title_that_was_on_the_screen() -> None:
    screen = '{"text": "\\"고객 정보 팔아요\\"…가짜 판매글 등장 ‘새 칩 탑재’ 노트북 선봬"}'
    answer = "1. \"고객 정보 팔아요\"…가짜 판매글 등장\n2. '새 칩 탑재' 노트북 선봬\n"
    assert _seen_text("“새 칩”") == _seen_text("'새 칩'")
    assert list_items_seen_by_tools(answer, [{"role": "tool", "content": screen}]) == 2
