"""「읽지 않고 적은 것」은 **진짜 이름**에만 붙인다 (2026-10-20 전수조사 — 대표: 「진짜 짜증난다」).

경고가 붙은 운영 판 301개의 이름 857개를 갈라 보니 574개가 표 첫 칸이었고, 그 머리 칸은 대부분 이름이 아니었다(「구분」 65 ·
「항목」 · 「요구 항목」 · 「용도」 · 「단계」 · 「축」 · 「페인포인트」 …). 표 밖 목록은 모델이 쓴 문장 · 소제목이 많았다.
「읽은 자료가 하나도 없다」는 가장 나쁜 가정으로 다시 대 봐도 301판 중 147판의 경고가 사라지고, 남는 것은 가게 · 책 · 회사 · 모델 이름이다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent

READ = {"role": "tool", "content": "코드나루 채용 공고 본문 … 미르 채용 공고 본문 … 혼자 공부하는 파이썬 452쪽"}


def _check(answer: str, *, ledger: list[dict] | None = None) -> str:
    return BrowserAgent._listed_entity_grounding_check(answer, [{"role": "user", "content": "조사해 줘"}, READ], ledger)


def test_category_column_is_not_names() -> None:
    answer = "| 구분 | 내용 |\n|---|---|\n| 핵심 가치 | 증거를 남긴다 |\n| 샌드박스 | 로컬 |\n| 포지션 | 클로드 옆 |\n"
    assert _check(answer) == ""


def test_model_made_categories_are_not_names() -> None:
    answer = "| 페인포인트 | 횟수 |\n|---|---|\n| 사용량/토큰 한도 | 5 |\n| 환각 | 3 |\n| 자신 있게 틀린 답 | 2 |\n"
    assert _check(answer) == ""


def test_sentence_like_bold_list_items_are_not_names() -> None:
    answer = "- **12GB는 '경계선'이다**\n- **반복 작업 시 10배 이상 빠름**\n- **결론**\n- **24GB 이상은 '초격차' 영역이다**\n"
    assert _check(answer) == ""


def test_invented_company_in_a_company_column_is_still_caught() -> None:
    answer = "| 회사 | 마감 |\n|---|---|\n| 코드나루 | 10.01 |\n| 도담스페이스 | 10.03 |\n| 바름터 | 10.05 |\n"
    note = _check(answer)
    assert "도담스페이스" in note and "바름터" in note and "코드나루" not in note


def test_invented_book_in_a_title_column_is_still_caught() -> None:
    answer = "| 책 제목 | 쪽수 |\n|---|---|\n| 혼자 공부하는 파이썬 | 452 |\n| 존재하지 않는 파이썬 책 | 300 |\n| 또 없는 책 | 200 |\n"
    note = _check(answer)
    assert "존재하지 않는 파이썬 책" in note and "혼자 공부하는" not in note


def _read(url: str) -> dict:
    return {"type": "body_read", "ok": True, "source_id": url, "effect": "read_web"}


def test_shop_names_of_sites_actually_read_are_not_flagged() -> None:
    answer = "| 가게 | 가격 |\n|---|---|\n| 다나와 | 719,940 |\n| 11번가 | 719,720 |\n| G마켓 | 721,000 |\n"
    ledger = [_read("https://prod.danawa.com/info?pcode=1"), _read("https://www.11st.co.kr/products/9"), _read("https://item.gmarket.co.kr/x")]
    assert _check(answer, ledger=ledger) == ""


def test_shop_name_of_a_site_never_read_is_still_flagged() -> None:
    answer = "| 가게 | 가격 |\n|---|---|\n| 다나와 | 719,940 |\n| 11번가 | 719,720 |\n| G마켓 | 721,000 |\n"
    note = _check(answer, ledger=[_read("https://prod.danawa.com/info?pcode=1")])
    assert "11번가" in note and "G마켓" in note and "다나와" not in note
