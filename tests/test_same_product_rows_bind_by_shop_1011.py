"""같은 상품을 가게마다 찾은 표 — 줄은 **주소가 가리키는 가게**로 제 페이지와 묶인다 (2026-10-11).

표의 값을 도구가 고쳐 쓰는 장치(`_fill_values_from_pages`)는 줄과 페이지를 **상품 이름**으로 묶고, 한 페이지에만 맞을 때만
고친다. 책 세 권의 표에서는 그것으로 충분했다. 가격 비교 표는 세 줄의 상품 이름이 같아서 이름이 세 페이지에 다 맞고,
그래서 한 줄도 못 고치고 지나갔다. 그 사이에:

  - 작은 모델이 다나와 줄의 주소를 지어 적었다(`prod.danawa.com/info/111111111` — 같은 날 네 번).
  - 11번가 줄에 할인 전 값을 적거나(작은 모델), 할인가를 적고 「첫머리에는 ○○원」 경고를 받았다(큰 모델 · 다섯 번).

이름이 여러 페이지에 맞으면 **그 줄 주소의 가게(호스트)**로 가른다. 이름도 맞고 가게도 하나뿐일 때만 묶는다 — 주소만 맞는 줄은
여전히 안 믿는다(2026-09-28 T1 O8: 주소를 옆 줄 것으로 옮긴 판). 묶이면 값과 주소를 그 페이지 것으로 바로잡는다.

값 대조(`_row_value_mismatch`)의 「그 페이지의 주 항목 자리」도 가게별 값 규칙이 뽑은 값을 안다.

표본의 상품 이름 · 값은 지어낸 것이다. 페이지 글의 구조는 `tests/test_page_value_recipes_shops_1011.py` 와 같다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.documents import write_document

from test_page_value_recipes_shops_1011 import DANAWA, DANAWA_BODY, ELEVEN, ELEVEN_DISCOUNT, GMARKET, GMARKET_COUPON

NAME = "가상 무선 마우스 M3"
TITLES = {
    DANAWA: f"{NAME} (정품) (블랙) : 다나와 가격비교",
    ELEVEN: f"[정품] {NAME} 블랙 수신기 포함",
    GMARKET: f"G마켓 - {NAME} 정품 블랙",
}
BODIES = {DANAWA: DANAWA_BODY, ELEVEN: ELEVEN_DISCOUNT, GMARKET: GMARKET_COUPON}
HEADER = ["가게", "상품 이름", "판매 가격", "배송비", "읽은 페이지 주소", "비고"]
ELEVEN_SHORT = "https://www.11st.co.kr/products/1000000001"
GMARKET_SHORT = "https://item.gmarket.co.kr/Item?goodscode=1000000001"
MADE_UP = "https://prod.danawa.com/info/111111111"


class _Store:
    def __init__(self) -> None:
        self.by_step: dict[int, str] = {}

    def get(self, job_id: str, step: int) -> dict[str, Any] | None:
        text = self.by_step.get(step)
        return {"payload": {"text": text}} if text else None


def _agent(pages: dict[str, str] | None = None) -> tuple[BrowserAgent, list[dict[str, Any]]]:
    agent = object.__new__(BrowserAgent)
    store = _Store()
    agent.observations = store
    steps: list[dict[str, Any]] = []
    for number, url in enumerate(pages or BODIES, start=1):
        store.by_step[number] = (pages or BODIES)[url]
        steps.append({
            "step": number, "tool": "browser_extract", "ok": True,
            "evidence": {"url": url, "title": TITLES.get(url, f"{NAME} 다른 판매자")},
            "evidence_record": {"type": "body_read", "ok": True, "source_id": url, "step": number, "job_id": "j"},
        })
    return agent, steps


def _write(agent: BrowserAgent, steps: list[dict[str, Any]], target: Path, rows: list[list[Any]]) -> str:
    arguments = {"format": "xlsx", "path": target.name, "sheets": {"가격 비교": [HEADER, *rows]}}
    write_document(target, "xlsx", dict(arguments))
    steps.append({"step": len(steps) + 1, "tool": "local_write_document", "ok": True, "arguments": arguments,
                  "evidence": {"action": "local_write_document", "format": "xlsx", "output_path": str(target), "verified": True}})
    return agent._fill_values_from_pages("local_write_document", {"ok": True}, steps, "j")


def _rows(target: Path) -> dict[str, list[Any]]:
    grid = [[cell.value for cell in row] for row in openpyxl.load_workbook(target).active.iter_rows()]
    return {str(row[0]): row for row in grid[1:]}


def _table(danawa_price: str = "139,300원", danawa_url: str = MADE_UP, eleven_price: str = "279,290원") -> list[list[Any]]:
    return [
        ["다나와", NAME, danawa_price, "무료", danawa_url, ""],
        ["11번가", NAME, eleven_price, "무료", ELEVEN_SHORT, ""],
        ["G마켓", NAME, "249,470원", "무료", GMARKET_SHORT, "쿠폰 제외"],
    ]


# --- 묶인다 ----------------------------------------------------------------------

def test_each_row_gets_the_price_of_the_shop_its_address_points_at(tmp_path: Path) -> None:
    agent, steps = _agent()
    target = tmp_path / "가격조사.xlsx"

    note = _write(agent, steps, target, _table())
    rows = _rows(target)

    assert rows["다나와"][2] == "128,970원", "다나와의 최저가 — 옆 가게 값(139,300원)이 적혀 있었다"
    assert rows["11번가"][2] == "229,020원", "할인된 값 — 할인 전 값(279,290원)이 적혀 있었다"
    assert note.startswith("★") and "128,970원" in note and "229,020원" in note, "고친 것은 전부 말한다"


def test_a_made_up_address_becomes_the_address_that_was_opened(tmp_path: Path) -> None:
    agent, steps = _agent()
    target = tmp_path / "가격조사.xlsx"

    note = _write(agent, steps, target, _table())

    assert _rows(target)["다나와"][4] == DANAWA
    assert MADE_UP in note


def test_an_address_that_is_the_opened_one_minus_tracking_is_left_as_written(tmp_path: Path) -> None:
    """모델이 추적 값을 떼고 적은 주소는 같은 페이지다 — 900자짜리 주소로 바꿔 쓰지 않는다."""
    agent, steps = _agent()
    target = tmp_path / "가격조사.xlsx"

    _write(agent, steps, target, _table())
    rows = _rows(target)

    assert rows["11번가"][4] == ELEVEN_SHORT
    assert rows["G마켓"][4] == GMARKET_SHORT


def test_the_shop_whose_everyone_price_is_not_on_the_page_keeps_what_the_model_wrote(tmp_path: Path) -> None:
    """G마켓의 값 규칙은 판매가를 주지 않는다(쿠폰을 뺀 값이 페이지에 없다) — 도구가 그 칸을 고치지 않는다."""
    agent, steps = _agent()
    target = tmp_path / "가격조사.xlsx"

    _write(agent, steps, target, _table())

    assert _rows(target)["G마켓"][2] == "249,470원"


def test_right_rows_are_not_rewritten(tmp_path: Path) -> None:
    agent, steps = _agent()
    target = tmp_path / "가격조사.xlsx"

    note = _write(agent, steps, target, _table(danawa_price="128,970원", danawa_url=DANAWA, eleven_price="229,020원"))

    assert note == ""


# --- 묶이지 않는다 -----------------------------------------------------------------

def test_a_row_without_an_address_is_not_guessed(tmp_path: Path) -> None:
    agent, steps = _agent()
    target = tmp_path / "가격조사.xlsx"
    rows = _table()
    for row in rows:
        row[4] = ""

    assert _write(agent, steps, target, rows) == ""
    assert _rows(target)["다나와"][2] == "139,300원"


def test_an_address_at_a_shop_that_was_not_opened_binds_nothing(tmp_path: Path) -> None:
    agent, steps = _agent()
    target = tmp_path / "가격조사.xlsx"
    rows = _table()
    rows[0][4] = "https://shop.example/products/9"

    _write(agent, steps, target, rows)

    assert _rows(target)["다나와"][2] == "139,300원" and _rows(target)["다나와"][4] == "https://shop.example/products/9"


def test_two_opened_pages_at_the_same_shop_are_not_told_apart_by_the_shop(tmp_path: Path) -> None:
    """같은 가게에서 같은 이름의 페이지를 둘 열었으면 가게로는 못 가른다 — 고치지 않는다."""
    other = "https://www.11st.co.kr/products/2000000002"
    agent, steps = _agent({**BODIES, other: ELEVEN_DISCOUNT.replace("229,020", "231,000")})
    target = tmp_path / "가격조사.xlsx"

    _write(agent, steps, target, _table())

    assert _rows(target)["11번가"][2] == "279,290원"


# --- 값 대조가 규칙의 값을 안다 -----------------------------------------------------

def _key(url: str) -> str:
    return BrowserAgent._url_key(url)


def test_the_discounted_price_is_not_called_a_mismatch_any_more() -> None:
    cells = ["11번가", NAME, "229,020원", "무료"]
    old_head = ELEVEN_DISCOUNT[:900]
    assert "229,020" not in old_head and "279,290" in old_head, "표본이 그날의 모양이어야 한다 — 첫머리에는 할인 전 값만 있다"
    assert BrowserAgent._row_value_mismatch(cells, NAME, old_head) is not None, "예전 기준으로는 헛경고가 났다"

    assert BrowserAgent._row_value_mismatch(cells, NAME, BrowserAgent._value_head(_key(ELEVEN), ELEVEN_DISCOUNT)) is None


def test_the_card_price_is_still_a_mismatch_and_the_warning_shows_the_right_one() -> None:
    wrong = BrowserAgent._row_value_mismatch(
        ["11번가", NAME, "226,730원", "무료"], NAME, BrowserAgent._value_head(_key(ELEVEN), ELEVEN_DISCOUNT),
    )

    assert wrong is not None and wrong[0] == "226,730원"
    assert wrong[1].startswith("229,020원"), "그 페이지의 값으로 가장 먼저 보이는 것이 할인된 판매가다"


def test_a_shop_whose_price_sits_past_the_menu_is_checked_at_last() -> None:
    """다나와는 첫머리가 메뉴라 예전에는 판정을 못 했다(값이 없는 자리는 판정하지 않는다)."""
    cells = ["다나와", NAME, "139,300원", "무료"]
    assert BrowserAgent._row_value_mismatch(cells, NAME, DANAWA_BODY[:900]) is None

    wrong = BrowserAgent._row_value_mismatch(cells, NAME, BrowserAgent._value_head(_key(DANAWA), DANAWA_BODY))

    assert wrong == ("139,300원", "128,970원")


def test_a_page_without_a_rule_is_checked_as_before() -> None:
    body = "어느 가게 상품\n판매가 15,000원\n" + "설명 " * 500

    assert BrowserAgent._value_head("shop.example/products/1", body) == body[:900]
