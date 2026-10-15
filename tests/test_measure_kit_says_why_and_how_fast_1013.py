"""재는 꾸러미가 **왜 틀렸는지 · 얼마나 빨랐는지**를 적고, 과제가 끝나면 **자기가 연 탭을 닫는다** (2026-10-13).

밖에서 받은 지적 셋이 한 자리에 모였다.
  - 「줄이 틀렸다」를 까닭별로 — 페이지를 못 찾았나 · 잘못 읽었나 · 읽고 잃었나. 고침이 다르다.
  - 실제 카드에서 넘쳤을 때 얼마나 느려지나 — 한 사람은 30%, 다른 사람은 2~5배라고 했다. 큰 카드로는 답할 수 없다.
  - 2와 9가 같이 나오면 평균보다 **가운데 값과 범위**가 낫다.

그리고 같은 날 저녁, 화면 밖 크롬에 판이 남긴 탭이 소리를 내 PC 주인이 놀랐다. 남의 노트북에서 밤새 도는 도구가 그러면 안 된다.

결과 파일에는 여전히 숫자와 **정해진 낱말**만 실린다. 걸음의 주소 · 인자 글은 까닭을 가르는 데만 쓰고 버린다.
표본의 가게 주소 · 값 · 글은 지어낸 것이다.
"""
from __future__ import annotations

import json

from alture_jarvis import measure_kit as kit

HEAD = ["가게", "상품 이름", "판매 가격", "배송비", "읽은 페이지 주소"]
DANAWA = "https://prod.danawa.com/info/?pcode=101"
ELEVEN = "https://www.11st.co.kr/products/202"
GMARKET = "https://item.gmarket.co.kr/Item?goodscode=303"
PAGES = [
    {"url": DANAWA, "text": "가상 마우스 X1 최저가 129,000원 무료배송"},
    {"url": ELEVEN, "text": "가상 마우스 X1 판매가 131,500원"},
    {"url": GMARKET, "text": "가상 마우스 X1 133000원"},
]
ROWS = [HEAD,
        ["다나와", "가상 마우스 X1", "129,000원", "무료", DANAWA],
        ["11번가", "가상 마우스 X1", "131,500원", "무료", ELEVEN],
        ["G마켓", "가상 마우스 X1", "133,000원", "무료", GMARKET]]


def _step(tool: str, url: str = "", *, ok: bool = True, error: str = "", aim: str = "") -> dict[str, object]:
    return {"tool": tool, "ok": ok, "error": error, "url": url, "aim": aim}


def _visit(search: str, product: str, *, read: bool = True) -> list[dict[str, object]]:
    steps = [_step("browser_site_search", search), _step("browser_open_result", product)]
    return steps + ([_step("browser_extract", product)] if read else [])


ALL_READ = (_visit("https://search.danawa.com/dsearch.php?query=x1", DANAWA)
            + _visit("https://search.11st.co.kr/pc/total-search?kwd=x1", ELEVEN)
            + _visit("https://www.gmarket.co.kr/n/search?keyword=x1", GMARKET))


# --- 까닭 ---------------------------------------------------------------------------

def test_three_whole_rows_have_no_cause_to_name() -> None:
    assert kit.price_causes(ROWS, PAGES, ALL_READ) == {"다나와": "온전", "11번가": "온전", "G마켓": "온전"}


def test_how_far_it_got_towards_a_shop_is_told_apart() -> None:
    steps = (_visit("https://search.danawa.com/dsearch.php?query=x1", DANAWA)                    # 읽음
             + [_step("browser_site_search", "https://search.11st.co.kr/pc/total-search?kwd=x1")]   # 검색까지만
             + [_step("browser_open", "", ok=False, error="page_not_found", aim='{"url": "https://www.gmarket.co.kr/search/x1"}')])
    rows = [HEAD, ROWS[1]]

    causes = kit.price_causes(rows, PAGES[:1], steps)

    assert causes == {"다나와": "온전", "11번가": "목록에서 못 엶", "G마켓": "가려다 막힘"}


def test_a_shop_never_aimed_at_and_one_opened_but_not_read() -> None:
    steps = _visit("https://search.11st.co.kr/pc/total-search?kwd=x1", ELEVEN, read=False)

    causes = kit.price_causes([HEAD], [], steps)

    assert causes["다나와"] == "안 감" and causes["G마켓"] == "안 감"
    assert causes["11번가"] == "열고 안 읽음"


def test_a_search_engine_query_naming_the_shop_is_not_a_visit() -> None:
    """검색 엔진에 가게 이름을 넣어 찾은 것은 그 가게에 들어간 것이 아니다."""
    steps = [_step("browser_search", "https://search.naver.com/search.naver?query=x1", aim='{"query": "가상 마우스 다나와"}')]

    assert kit.price_causes([HEAD], [], steps)["다나와"] == "가려다 막힘"


def test_what_went_wrong_after_reading_is_told_apart() -> None:
    rows = [HEAD,
            ["다나와", "가상 마우스 X1", "99,000원", "무료", DANAWA],                               # 읽은 글에 없는 값
            ["11번가", "가상 마우스 X1", "131,500원", "무료", "https://search.11st.co.kr/pc/total-search?kwd=x1"]]  # 값은 맞고 주소가 검색 화면

    causes = kit.price_causes(rows, PAGES, ALL_READ)

    assert causes == {"다나와": "잘못 읽음", "11번가": "주소만 틀림", "G마켓": "읽고 잃음"}
    assert kit.price_causes([], PAGES, ALL_READ) == {shop: "표 없이 끝남" for shop in kit.SHOPS}


def test_a_document_step_that_mentions_a_shop_is_not_a_visit() -> None:
    """문서를 쓰는 걸음의 내용에 가게 이름이 있다고 그 가게에 간 것이 아니다(이 눈금을 처음 만들 때 그렇게 셌다가 고쳤다)."""
    steps = [_step("local_write_document", "", aim='{"rows": [["11번가", "131,500원"]]}')]

    assert kit.price_causes([HEAD], [], steps)["11번가"] == "안 감"


# --- 요약: 까닭 · 가운데 값 · 속도 ---------------------------------------------------

def _run(round_no: int, task: str, causes: dict[str, str], **more: object) -> dict[str, object]:
    return {"task": task, "round": round_no, "shops": {shop: ("온전" if cause == "온전" else "줄 없음") for shop, cause in causes.items()},
            "causes": causes, "whole_rows": sum(1 for cause in causes.values() if cause == "온전"), **more}


def test_the_summary_counts_causes_and_gives_the_middle_and_the_range() -> None:
    whole = {"다나와": "온전", "11번가": "온전", "G마켓": "온전"}
    lost = {"다나와": "온전", "11번가": "안 감", "G마켓": "목록에서 못 엶"}
    runs = [_run(n, "mouse", whole if n in (1, 4) else lost, sec=300 + 10 * n, gen_tokens_per_sec=20.0 + n) for n in (1, 2, 3, 4, 5)]

    summary = kit.price_summary(runs)

    assert summary["causes"] == {"안 감": 3, "목록에서 못 엶": 3}
    assert summary["cause_groups"] == {"못 찾음": 6}, "「못 찾음」은 안 감 · 가려다 막힘 · 목록에서 못 엶 · 열고 안 읽음을 묶은 것"
    assert (summary["median"], summary["low"], summary["high"]) == (1, 1, 3)
    assert summary["sec_median"] == 330 and summary["gen_tokens_per_sec_median"] == 23.0
    said = "\n".join(kit.summary_lines(summary))
    assert "가운데 값 1" in said and "1~3" in said and "못 찾음 6" in said and "23.0" in said


def test_speed_comes_from_the_model_time_the_job_recorded() -> None:
    assert kit.speed_of({"generate_sec": 8.0, "generated_tokens": 360, "prefill_sec": 0.5, "prompt_tokens": 27000}) == {
        "gen_tokens_per_sec": 45.0, "prefill_tokens_per_sec": 54000.0}
    assert kit.speed_of({}) == {} and kit.speed_of({"generate_sec": 0, "generated_tokens": 10}) == {}


def test_what_goes_into_the_result_file_is_still_only_numbers_and_fixed_words() -> None:
    run = {"status": "completed", "state": "complete", "asked": False, "sec": 301, "steps": 12, "stop_reason": "model_done", "pushbacks": 0,
           "largest_prompt_tokens": 21000, "refused_steps": 1, "gen_tokens_per_sec": 31.2, "prefill_tokens_per_sec": 900.0, "closed_tabs": 2,
           "answer": "가상 답", "pages": PAGES, "sheet_paths": ["x.xlsx"], "doc_paths": [],
           "steps_for_grading": ALL_READ, "tools": [{"tool": "browser_open", "ok": True, "error": ""}]}

    kept = json.dumps(kit.numbers_only(run, with_steps=True), ensure_ascii=False)

    assert "gen_tokens_per_sec" in kept and "closed_tabs" in kept
    for leak in ("danawa", "11st", "gmarket", "가상 답", "x.xlsx", "http"):
        assert leak not in kept, leak
    assert set(kit.price_causes(ROWS, PAGES, ALL_READ).values()) <= set(kit.CAUSES)


# --- 과제가 끝나면 자기가 연 탭을 닫는다 ----------------------------------------------

class _Chrome:
    def __init__(self, tabs: list[dict[str, str]]) -> None:
        self.tabs = [dict(tab, type="page") for tab in tabs]
        self.calls: list[str] = []

    def __call__(self, path: str, method: str = "GET") -> object:
        self.calls.append(f"{method} {path}")
        if path == "/json/list":
            return [dict(tab) for tab in self.tabs]
        if path.startswith("/json/new"):
            self.tabs.append({"id": "blank", "url": "about:blank", "type": "page"})
            return self.tabs[-1]
        if path.startswith("/json/close/"):
            self.tabs = [tab for tab in self.tabs if tab["id"] != path.rsplit("/", 1)[1]]
            return "Target is closing"
        raise AssertionError(path)


def test_only_tabs_the_task_opened_or_changed_are_closed() -> None:
    chrome = _Chrome([{"id": "mine", "url": "https://mail.example/inbox"}, {"id": "idle", "url": "about:blank"}])
    before = kit.tabs_now(chrome)
    chrome.tabs[1]["url"] = GMARKET                                    # 과제가 쓰던 탭
    chrome.tabs.append({"id": "new", "url": DANAWA, "type": "page"})   # 과제가 새로 연 탭

    closed = kit.close_tabs_the_task_left(chrome, before)

    assert closed == 2
    assert [tab["id"] for tab in chrome.tabs] == ["mine"], "사람이 열어 둔 탭은 그대로"


def test_the_window_is_not_closed_along_with_its_last_tab() -> None:
    chrome = _Chrome([{"id": "only", "url": "about:blank"}])
    before = kit.tabs_now(chrome)
    chrome.tabs[0]["url"] = ELEVEN

    assert kit.close_tabs_the_task_left(chrome, before) == 1
    assert [tab["url"] for tab in chrome.tabs] == ["about:blank"], "마지막 탭을 닫기 전에 빈 탭을 먼저 만든다"
    assert chrome.calls.index("PUT /json/new?about:blank") < chrome.calls.index("GET /json/close/only")


def test_a_browser_that_does_not_answer_is_left_alone() -> None:
    def dead(path: str, method: str = "GET") -> object:
        raise OSError("connection refused")

    assert kit.tabs_now(dead) is None
    assert kit.close_tabs_the_task_left(dead, None) == 0
    assert kit.close_tabs_the_task_left(dead, {"a": "about:blank"}) == 0
