"""이 PC 에서 재 보기(`measure_kit`) — 채점은 쓰던 자와 같고, 결과 파일에는 숫자와 예 · 아니오만 실린다 (2026-10-13).

작은 그래픽카드의 숫자를 큰 카드에서 창만 줄여 재다가 권고를 한 번 거뒀다. 재는 일을 그 PC 의 주인이 명령 한 줄로 할 수 있게
하되, 남의 PC 에서 도는 것이라 지킬 것이 있다: 쓰는 중이면 기다린다 · 결과에 글 · 주소 · 파일 이름을 싣지 않는다.

표본의 가게 주소 · 값 · 글은 지어낸 것이다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis import measure_kit as kit

HEAD = ["가게", "상품 이름", "판매 가격", "배송비", "읽은 페이지 주소", "비고"]
PAGES = [
    {"url": "https://prod.danawa.com/info/?pcode=101", "text": "가상 마우스 X1 최저가 129,000원 무료배송"},
    {"url": "https://www.11st.co.kr/products/202", "text": "가상 마우스 X1 판매가 131,500원"},
    {"url": "https://item.gmarket.co.kr/Item?goodscode=303", "text": "가상 마우스 X1 133000원"},
]


def test_a_row_is_whole_only_when_its_price_is_on_the_page_read_from_that_shop() -> None:
    rows = [HEAD,
            ["다나와", "가상 마우스 X1", "129,000원", "무료", "https://prod.danawa.com/info/?pcode=101", ""],
            ["11 번가", "가상 마우스 X1", "131500", "무료", "https://www.11st.co.kr/products/202", ""],
            ["G마켓", "가상 마우스 X1", "133,000 원", "무료", "https://item.gmarket.co.kr/Item?goodscode=303", ""]]
    assert kit.grade_price_rows(rows, PAGES) == {"다나와": "온전", "11번가": "온전", "G마켓": "온전"}


def test_each_way_a_row_falls_short_has_its_own_word() -> None:
    rows = [HEAD,
            ["다나와", "가상 마우스 X1", "확인 불가", "", "https://prod.danawa.com/info/?pcode=101", ""],           # 값 없음
            ["11번가", "가상 마우스 X1", "131,500원", "", "https://search.11st.co.kr/total?kwd=x1", ""],             # 검색 화면 주소
            ["G마켓", "가상 마우스 X1", "99,000원", "", "https://item.gmarket.co.kr/Item?goodscode=303", ""]]         # 읽은 글에 없는 값
    assert kit.grade_price_rows(rows, PAGES) == {"다나와": "값 없음", "11번가": "주소 틀림", "G마켓": "값이 글에 없음"}
    assert kit.grade_price_rows([HEAD], PAGES) == {shop: "줄 없음" for shop in kit.SHOPS}
    assert kit.grade_price_rows([], []) == {shop: "줄 없음" for shop in kit.SHOPS}


def test_a_price_read_on_another_shop_does_not_count() -> None:
    """다나와에서 읽은 값을 G마켓 줄에 적으면 온전한 줄이 아니다."""
    rows = [HEAD, ["G마켓", "가상 마우스 X1", "129,000원", "", "https://item.gmarket.co.kr/Item?goodscode=303", ""]]
    assert kit.grade_price_rows(rows, PAGES)["G마켓"] == "값이 글에 없음"


def _turn(answer: str = "", *, asked: bool = False, docs: tuple[str, ...] = (), other_ai: bool = False) -> dict:
    return {"answer": answer, "asked": asked, "doc_texts": list(docs), "asked_another_ai": other_ai}


def test_the_chain_verdict_follows_what_went_wrong_that_day() -> None:
    good = kit.grade_chain(("올레",), [
        _turn("제주 올레길은 …"), _turn("올레길 방식과 동네 둘레길의 차이는 …"),
        _turn("파일을 만들었습니다", docs=("제주 올레길 정리\n" + "본문 " * 200,)), _turn("올레길을 따라 하는 방법을 더 적었습니다"),
    ])
    assert good["first_answered"] and all(good["second"].values()) and all(good["fourth"].values())
    assert good["third"]["made_file"] and good["third"]["file_has_text"] and good["third"]["file_kept_topic"]

    bad = kit.grade_chain(("올레",), [
        _turn("제주 올레길은 …"),
        _turn("같은 말을 되풀이합니다. " * 40),                      # 같은 말 반복
        _turn("한글 파일로 정리했습니다", docs=("",)),                 # 흰 화면뿐인 파일
        _turn("무엇을 다시 설명해 드릴까요?", asked=True, other_ai=True),  # 되묻고, 남의 AI 에 물음
    ])
    assert bad["second"]["kept_topic"] is False and bad["second"]["no_loop"] is False
    assert bad["third"] == {"made_file": True, "file_chars": 0, "file_has_text": False, "file_kept_topic": False}
    assert bad["fourth"] == {"did_not_ask_back": False, "did_not_ask_another_ai": False, "kept_topic": False}


def test_what_goes_into_the_result_file_carries_no_words_from_the_job() -> None:
    run = {"status": "completed", "state": "complete", "asked": False, "sec": 212, "steps": 14, "stop_reason": "model_done",
           "pushbacks": 1, "largest_prompt_tokens": 24_800, "refused_steps": 2,
           "answer": "비밀스러운 답 글", "pages": [{"url": "https://prod.danawa.com/info/?pcode=101", "text": "읽은 화면 글"}],
           "sheet_paths": [r"C:\\Users\\someone\\Documents\\가격.xlsx"], "doc_paths": [],
           "tools": [{"tool": "browser_extract", "ok": True, "error": ""}, {"tool": "browser_open", "ok": False, "error": "not_this_stage"}]}
    plain = kit.numbers_only(run, with_steps=False)
    assert set(plain) == {"status", "state", "asked", "sec", "steps", "stop_reason", "pushbacks", "largest_prompt_tokens", "refused_steps"}
    packed = json.dumps(plain, ensure_ascii=False)
    for leak in ("비밀스러운", "읽은 화면", "danawa", "someone", "xlsx"):
        assert leak not in packed
    with_steps = kit.numbers_only(run, with_steps=True)
    assert with_steps["tools"] == [{"tool": "browser_extract", "ok": True, "error": ""}, {"tool": "browser_open", "ok": False, "error": "not_this_stage"}]
    assert "danawa" not in json.dumps(with_steps, ensure_ascii=False)


class _Busy:
    def __init__(self, busy: list[bool]) -> None:
        self._busy = list(busy)

    def busy(self) -> bool:
        return self._busy.pop(0) if len(self._busy) > 1 else self._busy[0]


def test_it_waits_while_the_pc_is_in_use_and_gives_up_politely() -> None:
    said: list[str] = []
    slept: list[float] = []
    # 손자리가 한 번 바빴다가 비고, 사람은 손을 뗀 지 오래다 → 한 번 기다린 뒤 시작.
    assert kit.wait_until_free(_Busy([True, False]), idle_sec=120, patience_sec=600, say=said.append, sleep=slept.append, input_idle=lambda: 900.0)
    assert slept == [30] and "다른 일" in said[0]
    # 사람이 계속 쓰는 중 → 참을 만큼 기다리고 건너뛴다(과제를 밀어붙이지 않는다).
    slept.clear()
    assert not kit.wait_until_free(_Busy([False]), idle_sec=120, patience_sec=90, say=said.append, sleep=slept.append, input_idle=lambda: 3.0)
    assert slept == [30, 30, 30]
    # 입력을 잴 수 없는 PC — 막지 않는다.
    assert kit.wait_until_free(_Busy([False]), idle_sec=120, patience_sec=0, say=said.append, sleep=slept.append, input_idle=lambda: None)


def test_the_screen_share_is_only_claimed_for_a_single_card() -> None:
    one = [{"name": "가상 카드 8GB", "total_mb": 8192, "used_mb": 6900}]
    assert kit.screen_share_mb(one, 4 * 1024 * 1024 * 1024) == 6900 - 4096
    assert kit.screen_share_mb(one + one, 4 * 1024 * 1024 * 1024) is None, "카드가 둘이면 어느 카드의 몫인지 모른다"
    assert kit.screen_share_mb([], 0) is None


def test_the_tasks_stand_alone_without_any_skill_pack() -> None:
    """남의 PC 에는 우리 본보기 스킬팩이 없다 — 가게 셋과 칸을 문장이 다 말한다."""
    for prompt in kit.PRICE_TASKS.values():
        for word in ("다나와", "11번가", "G마켓", "판매 가격", "엑셀"):
            assert word in prompt
    for chain in kit.CHAIN_TASKS.values():
        assert len(chain["turns"]) == 4 and any(name in chain["turns"][0] for name in chain["names"])
        assert not any(name in chain["turns"][1] or name in chain["turns"][3] for name in chain["names"]), "둘째 · 넷째는 이름을 말하지 않는다"


def test_empty_or_missing_documents_read_as_no_text(tmp_path: Path) -> None:
    assert kit.document_text(tmp_path / "없는파일.docx") == ""
    (tmp_path / "빈.txt").write_text("", encoding="utf-8")
    assert kit.document_text(tmp_path / "빈.txt") == ""
    assert kit.sheet_rows(tmp_path / "없는파일.xlsx") == []


def test_a_wrong_token_is_said_before_any_task_runs(tmp_path: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    """첫 실제 실행에서 옛 토큰을 집어 과제 도중에 401 로 죽었다 — 돌리기 전에 알고, 무엇을 하면 되는지 말한다."""
    import urllib.error

    token = tmp_path / "control.token"
    token.write_text("stale", encoding="utf-8")
    ran: list[str] = []
    monkeypatch.setattr(kit.Sonjari, "health", lambda self: {"ok": True})

    def refuse(self):  # noqa: ANN001, ANN202
        raise urllib.error.HTTPError(self.base_url, 401, "Unauthorized", None, None)

    monkeypatch.setattr(kit.Sonjari, "busy", refuse)
    monkeypatch.setattr(kit.Sonjari, "run", lambda self, *a, **k: ran.append("ran"))
    code = kit.main(["--now", "--token-file", str(token), "--base-url", "http://127.0.0.1:9", "--out", str(tmp_path / "out")])
    said = capsys.readouterr().out
    assert code == 2 and not ran, "과제를 하나도 돌리지 않는다"
    assert "토큰이 맞지 않습니다" in said and "--token-file" in said
    assert not (tmp_path / "out").exists(), "결과 폴더도 만들지 않는다"


def test_the_token_file_can_be_named_by_the_environment_like_the_connector_does(tmp_path: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setenv("JARVIS_TOKEN_FILE", str(tmp_path / "없는.token"))
    assert kit.main(["--now", "--out", str(tmp_path / "out")]) == 2
    assert "토큰을 찾지 못했습니다" in capsys.readouterr().out


@pytest.mark.parametrize("cell, shop", [("다나와", "다나와"), ("11 번가", "11번가"), ("G 마켓", "G마켓"), ("지마켓", "G마켓"), ("Gmarket", "G마켓"), ("쿠팡", "")])
def test_shop_names_are_read_the_way_small_models_write_them(cell: str, shop: str) -> None:
    assert kit.shop_of(cell) == shop
