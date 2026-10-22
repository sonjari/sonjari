"""값 칸 배우기 — 손자리가 스스로 배우고 스스로 검증한다 (2026-10-21 · 대표: 「레시피 확장은 손자리가 해야 — 킬러 기능」).

예스24 상세 본문 20,000자를 읽은 다음 부르기가 첫 글자까지 17초였다. 답의 값은 「쪽수, 무게, 크기 / 552쪽 | …」 같은 칸 몇 개였다.
첫 시험에서 출판사가 「혼공 체크표」, 저자가 「[ 개정판 ]」(그 책에만 있는 줄)에 우연히 붙었다 — 그런 칸은 받지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from alture_jarvis import value_cells as V


def _page(pages: int, date: str, price: str, extra: str = "") -> str:
    return (
        "메뉴\n로그인\n" + extra + "혼공 체크표\n한빛미디어\n[ 개정판 ]\n윤인성 저\n|\n한빛미디어\n품목정보\n발행일\n"
        f"{date}\n쪽수, 무게, 크기\n{pages}쪽 | 1,160g | 188*257*30mm\n상품 가격정보\n정가\n22,000원\n판매가\n{price} (10% 할인)\n"
        + "함께 본 책 · 추천 도서 · 이 책의 다른 판 · 리뷰 한 줄\n" * 600  # 실제 상세 본문처럼 길게(약 2만 자)
    )


ANSWER_A = "- **쪽수:** 552쪽\n- **출판사:** 한빛미디어\n- **저자:** 윤인성\n- **발행일:** 2022년 6월 1일\n- **판매가:** 19,800원 (정가 22,000원)\n\n출처: https://x"
BODY_A = _page(552, "2022년 06월 01일", "19,800원")
ANSWER_B = "- 쪽수: 304쪽\n- 발행일: 2024년 3월 15일\n- 판매가: 27,000원"
BODY_B = _page(304, "2024년 03월 15일", "27,000원")
ANSWER_C = "| 항목 | 값 |\n|---|---|\n| 쪽수 | 640쪽 |\n| 판매가 | 31,500원 |"
BODY_C = _page(640, "2025년 01월 02일", "31,500원")


def test_learns_only_cells_whose_label_matches_and_rereads_the_same_value() -> None:
    cells = V.learn(ANSWER_A, BODY_A)
    assert {(cell["field"], cell["anchor"]) for cell in cells} == {
        ("쪽수", "쪽수, 무게, 크기"), ("발행일", "발행일"), ("판매가", "판매가")}, "출판사 · 저자는 우연히 붙은 줄이라 안 받는다"
    assert V.apply(cells, BODY_A) == {"쪽수": "552쪽", "발행일": "2022년 06월 01일", "판매가": "19,800원 (10% 할인)"}


def test_trust_comes_only_after_two_other_pages_agree() -> None:
    cells = V.learn(ANSWER_A, BODY_A)
    assert V.trusted(cells) == [], "배운 판은 검증이 아니다"
    cells = V.verify(cells, ANSWER_B, BODY_B)
    assert V.trusted(cells) == []
    cells = V.verify(cells, ANSWER_C, BODY_C)
    assert {cell["field"] for cell in V.trusted(cells)} == {"쪽수", "판매가"}, "발행일은 C 답에 없어 한 번만 맞았다"


def test_one_disagreement_drops_the_cell() -> None:
    cells = V.learn(ANSWER_A, BODY_A)
    wrong = "- 쪽수: 999쪽\n- 판매가: 27,000원"
    kept = V.verify(cells, wrong, BODY_B)
    assert "쪽수" not in {cell["field"] for cell in kept} and "판매가" in {cell["field"] for cell in kept}


def test_a_short_page_is_not_compacted() -> None:
    cells = V.verify(V.verify(V.learn(ANSWER_A, BODY_A), ANSWER_B, BODY_B), ANSWER_C, BODY_C)
    short = "쪽수, 무게, 크기\n200쪽\n판매가\n9,000원\n"
    assert V.compact_text(cells, short, "쪽수와 가격") == ("", []), "줄여서 얻는 것이 없으면 원문 그대로"


def test_compacts_only_when_every_asked_attribute_is_trusted() -> None:
    cells = V.verify(V.verify(V.learn(ANSWER_A, BODY_A), ANSWER_B, BODY_B), ANSWER_C, BODY_C)
    body = _page(416, "2023년 05월 05일", "24,300원")
    text, used = V.compact_text(cells, body, "예스24에서 파이썬 책 쪽수와 가격 알려줘")
    assert used == ["쪽수", "판매가"] and "쪽수: 416쪽" in text and "판매가: 24,300원 (10% 할인)" in text
    assert len(text) < len(body) and "browser_extract 를 한 번 더" in text
    assert V.compact_text(cells, body, "쪽수와 출판사 알려줘") == ("", []), "출판사는 믿는 칸이 없다 — 본문 그대로"
    assert V.compact_text(cells, body, "이 책 어때?") == ("", []), "속성을 묻지 않았으면 줄이지 않는다"


def test_the_book_learns_then_verifies_across_runs(tmp_path: Path) -> None:
    book = V.ValueCellBook(tmp_path)
    first = book.observe("https://www.yes24.com/product/goods/1", ANSWER_A, BODY_A)
    assert first["learned"] == 3 and first["trusted"] == 0
    book.observe("https://www.yes24.com/product/goods/2", ANSWER_B, BODY_B)
    third = book.observe("https://www.yes24.com/product/goods/3", ANSWER_C, BODY_C)
    assert third["newly_trusted"] == 2 and (tmp_path / "www.yes24.com.json").exists()


class _Agent:
    from alture_jarvis.agent import BrowserAgent

    _with_learned_value_cells = BrowserAgent._with_learned_value_cells

    def __init__(self, documents: Path) -> None:
        self.config = SimpleNamespace(user_recipes_dir=documents)


def _trusted_book(tmp_path: Path) -> None:
    book = V.ValueCellBook(tmp_path / "value_cells")
    book.observe("https://www.yes24.com/p/1", ANSWER_A, BODY_A)
    book.observe("https://www.yes24.com/p/2", ANSWER_B, BODY_B)
    book.observe("https://www.yes24.com/p/3", ANSWER_C, BODY_C)


def test_the_agent_gives_the_model_values_first_and_the_full_body_on_a_second_read(tmp_path: Path) -> None:
    _trusted_book(tmp_path)
    agent = _Agent(tmp_path)
    body = _page(416, "2023년 05월 05일", "24,300원")
    observation = {"ok": True, "result": {"url": "https://www.yes24.com/p/9", "text": body, "char_count": len(body)}}
    messages = [{"role": "system", "content": "x"}, {"role": "user", "content": "쪽수랑 가격 알려줘"}]
    first = agent._with_learned_value_cells("job", "browser_extract", observation, messages)
    assert first["result"]["value_cells_used"] == ["쪽수", "판매가"] and len(first["result"]["text"]) < len(body)
    again = agent._with_learned_value_cells("job", "browser_extract", observation, messages)
    assert again["result"]["text"] == body, "같은 판에서 다시 부르면 본문 전체 — 탈출구"
    other_site = {"ok": True, "result": {"url": "https://www.kyobobook.co.kr/p/1", "text": body}}
    assert agent._with_learned_value_cells("job", "browser_extract", other_site, messages) == other_site


def test_the_runtime_learns_from_a_single_page_run_and_says_one_quiet_line(tmp_path: Path) -> None:
    from alture_jarvis.runtime import JarvisRuntime

    class _Store:
        """진짜 보관소(`ObservationStore.get`)와 같은 꼴 — 화면용 사전의 `payload.text`. 처음엔 다른 꼴의 가짜로 시험해 놓쳤다."""

        def get(self, job_id, step):
            return {"step": step, "tool": "browser_extract", "payload": {"url": "https://www.yes24.com/p/1", "text": BODY_A}}

    runtime = SimpleNamespace(config=SimpleNamespace(user_recipes_dir=tmp_path), observations=_Store())
    trace = {"steps": [{"step": 4, "tool": "browser_extract", "ok": True, "evidence": {"url": "https://www.yes24.com/p/1"}}],
             "plan": {"met": 1, "total": 1}, "verification": {"completion_state": "complete", "answer_conflict": ""}}
    line = JarvisRuntime._learn_value_cells(runtime, "job", ANSWER_A, trace)
    assert line == "\n\n— www.yes24.com 값 칸 3개를 배웠습니다(확인 0/2)"
    two_pages = {**trace, "steps": trace["steps"] + [{"step": 6, "tool": "browser_extract", "ok": True, "evidence": {"url": "https://www.yes24.com/p/2"}}]}
    assert JarvisRuntime._learn_value_cells(runtime, "job2", ANSWER_A, two_pages) == "", "두 페이지를 읽은 판은 배우지 않는다"
    used = {"steps": [{"tool": "browser_extract", "ok": True, "evidence": {"value_cells_used": ["쪽수", "판매가"], "value_cells_from_chars": 20000, "char_count": 1700}}]}
    assert JarvisRuntime._learn_value_cells(runtime, "job3", ANSWER_A, used) == "\n\n— 배운 값 칸(쪽수 · 판매가)으로 읽었습니다 · 본문 20,000자 → 1,700자"
