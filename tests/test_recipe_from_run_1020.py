"""잘 해낸 판 → 레시피 초안 (2026-10-20 · 확장 설계 P1 · `recipe_from_run`).

운영 기록 2,623판에 돌려 보니: 초안 707개 중 693개가 「주소 하나 열기」였고 누르기 · 입력이 든 절차는 14개였다.
거절 까닭은 「누른 요소의 이름이 기록에 없음」(옛 판 159개 — 이제 브라우저가 `selectors` 를 남긴다) ·
「누른 뒤 바뀐 것이 없음」(62개) · 「주소 열기로 시작 안 함」(223개).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.recipe_from_run import DraftRefused, draft_from_run, run_is_a_candidate, strip_tracking
from alture_jarvis.site_recipes import SiteRecipe, read_only_reason


def _open(url: str) -> dict:
    return {"tool": "browser_open", "ok": True, "arguments": {"url": url}, "evidence": {"action": "opened", "url": url}}


def _fill(ref: str, value: str, url: str, *, selectors=None, field: str = "") -> dict:
    evidence = {"action": "filled", "ref": ref, "url": url, **({"selectors": selectors} if selectors else {}), **({"field": field} if field else {})}
    return {"tool": "browser_fill", "ok": True, "arguments": {"ref": ref, "value": value}, "evidence": evidence}


def _press(ref: str, url: str, *, selectors=None) -> dict:
    return {"tool": "browser_press", "ok": True, "arguments": {"ref": ref, "key": "Enter"},
            "evidence": {"action": "pressed", "url": url, **({"selectors": selectors} if selectors else {})}}


def _click(ref: str, url: str, *, label: str = "", selectors=None, expect=None, verified=None) -> dict:
    evidence = {"action": "clicked", "ref": ref, "url": url, **({"label": label} if label else {}),
                **({"selectors": selectors} if selectors else {}), **({"verified": verified} if verified is not None else {})}
    return {"tool": "browser_click", "ok": True, "arguments": {"ref": ref, **({"expect": expect} if expect else {})}, "evidence": evidence}


SEARCH = ['[placeholder="상품 검색"]', 'role=textbox[name="상품 검색"]']


def test_a_search_then_sort_run_becomes_a_procedure_with_a_query_slot() -> None:
    steps = [
        _open("https://www.danawa.com/?utm_source=x"),
        _fill("j3", "닌텐도 스위치 2", "https://www.danawa.com/", selectors=SEARCH),
        _press("j3", "https://search.danawa.com/dsearch.php?query=%EB%8B%8C%ED%85%90%EB%8F%84%20%EC%8A%A4%EC%9C%84%EC%B9%98%202", selectors=SEARCH),
        _click("j40", "https://search.danawa.com/dsearch.php?query=x&sort=priceASC", label="낮은 가격순",
               selectors=['[data-testid="sort-low"]'], expect={"kind": "url_changes"}, verified=True),
        {"tool": "browser_open_result", "ok": True, "arguments": {"rank": 1}, "evidence": {"url": "https://prod.danawa.com/info/?pcode=1"}},
        _open("https://prod.danawa.com/info/?pcode=1"),
    ]
    draft = draft_from_run("다나와에서 닌텐도 스위치 2 최저가", steps, job_id="j-1", at=1.0)
    action = draft["actions"]["from_run"]
    assert [step["do"] for step in action["steps"]] == ["open", "dismiss", "fill", "press", "click"], "결과를 연 뒤부터는 싣지 않는다 · 연 뒤엔 가로막는 창부터"
    assert action["steps"][0]["url"] == "https://www.danawa.com/", "추적 인자는 뗀다"
    assert action["steps"][2]["value"] == "{query}"
    assert draft["_slots"] == {"query": "닌텐도 스위치 2"}
    assert draft["targets"]["fill_1"] == SEARCH
    assert action["steps"][3]["target"] == "fill_1", "같은 칸에서 누른 Enter 는 같은 대상이다"
    assert action["steps"][3]["expect"] == {"kind": "url_changes"}
    assert action["risk"] == "L2" and read_only_reason(draft)
    assert draft["_learned_from"]["job_id"] == "j-1"
    SiteRecipe(Path("danawa.json"), draft)  # 확정본과 같은 규칙을 통과한다


def test_wandering_opens_fold_into_the_last_one_and_the_value_becomes_a_slot() -> None:
    steps = [
        _open("https://www.yes24.com/"),
        _open("https://www.yes24.com/Product/Search?domain=ALL&query=%ED%8C%8C%EC%9D%B4%EC%8D%AC"),
    ]
    draft = draft_from_run("예스24 에서 파이썬 책 찾아 줘", steps)
    action = draft["actions"]["from_run"]
    assert action["steps"] == [{"do": "open", "url": "https://www.yes24.com/Product/Search?domain=ALL&query={query}"}]
    assert draft["_slots"] == {"query": "파이썬"}
    assert action["risk"] == "L1" and not read_only_reason(draft)


def test_a_click_with_no_observed_change_refuses_the_draft() -> None:
    """확인 조건을 만들 수 없는 누르기를 빼고 쓰면 다른 절차가 된다 — 쓰지 않는다(불변식 I2)."""
    steps = [_open("https://www.example-shop.kr/"), _click("j5", "https://www.example-shop.kr/", label="필터")]
    with pytest.raises(DraftRefused, match="바뀐 것"):
        draft_from_run("필터 걸어 줘", steps)


def test_old_runs_without_names_are_refused_with_the_reason() -> None:
    steps = [_open("https://www.coupang.com/"), _click("j18", "https://www.coupang.com/np/campaigns/82")]
    with pytest.raises(DraftRefused, match="이름"):
        draft_from_run("쿠팡 로켓배송", steps)


def test_old_runs_fall_back_to_names_from_the_record() -> None:
    steps = [
        _open("https://www.perplexity.ai/"),
        _fill("j25", "질문 하나", "https://www.perplexity.ai/", field="무엇이든 물어보세요… 안의 div"),
        _press("j25", "https://www.perplexity.ai/search/new/abc"),
        _click("j5", "https://www.perplexity.ai/", label="신규", expect={"kind": "text_appears", "value": "무엇이든"}, verified=True),
        _fill("j48", "질문 둘", "https://www.perplexity.ai/", field="무엇이든 물어보세요… 안의 div"),
    ]
    draft = draft_from_run("퍼플렉시티에 물어봐 줘", steps)
    assert draft["targets"]["fill_1"][0] == '[placeholder^="무엇이든 물어보세요"]'
    assert draft["targets"]["click_2"][0] == 'role=button[name="신규"]'
    assert [step["do"] for step in draft["actions"]["from_run"]["steps"]] == ["open", "dismiss", "fill", "press", "click"], "같은 칸을 두 번째 채우면 한 바퀴 끝"


def test_runs_on_this_pc_and_runs_across_sites_are_refused() -> None:
    with pytest.raises(DraftRefused, match="시험 주소"):
        draft_from_run("x", [_open("http://127.0.0.1:5173/")])
    with pytest.raises(DraftRefused, match="여러 사이트"):
        draft_from_run("x", [_open("https://www.danawa.com/"), _click("j1", "https://www.coupang.com/", label="쿠팡", expect={"kind": "url_changes"}, verified=True)])


def test_only_clean_runs_are_candidates() -> None:
    good = {"completion_state": "complete", "answer": "가격은 1만 원입니다.",
            "agent_trace": {"plan": {"met": 2, "total": 2}, "verification": {"answer_conflict": ""}}}
    assert run_is_a_candidate(good) == ""
    assert run_is_a_candidate({**good, "completion_state": "partial"})
    assert run_is_a_candidate({**good, "agent_trace": {"plan": {"met": 1, "total": 2}}})
    assert run_is_a_candidate({**good, "answer": "⚠ 읽지 않고 적은 것이 있습니다"})


def test_tracking_parameters_are_removed_and_the_rest_kept() -> None:
    assert strip_tracking("https://a.kr/p?id=3&utm_medium=x&fbclid=y&sort=low") == "https://a.kr/p?id=3&sort=low"
