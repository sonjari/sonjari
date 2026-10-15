"""지킬 수 없는 지시는 요청에 적힌 대안으로 넘어가게 한다 (2026-10-02 협업 1차 판 33a2437f).

Claude 가 준 기준 「달러는 미국 영어 가격 페이지 기준이다(claude.com/pricing …). 원화만 보이면 원화 그대로 적고 환율로 바꾸지
않는다」. 사이트는 한국 IP 를 보고 `/ko/pricing` 으로 돌려보냈고, 손자리는 같은 주소를 다섯 번 열고 `/en_US/pricing`(404)을
지어내다 20걸음 상한에 걸렸다. 대안 문장은 요청 안에 있었다.
"""

from __future__ import annotations

from alture_jarvis.agent import _fallback_clauses, _unkeepable_notice
from alture_jarvis.browser import LOCALE_REDIRECT_NOTE, locale_redirect

PROMPT = (
    "Claude, ChatGPT, Perplexity, Manus, Genspark의 공식 가격 페이지에서 개인용 요금제를 모두 찾아 엑셀로 정리해줘.\n\n"
    "[조사 기준 — 이대로 따를 것]\n"
    "1. 월 요금은 '월간 결제' 금액만 적는다.\n"
    "2. 달러는 미국 영어 가격 페이지 기준이다(예: claude.com/pricing, chatgpt.com/pricing, 주소에 /ko 없이). "
    "원화만 보이면 원화 그대로 적고 환율로 바꾸지 않는다.\n"
    "3. 가격 숫자가 글자로 안 읽히면 화면을 캡처해서 그림으로 읽는다. 그래도 안 되면 그 회사 공식 도움말 문서에서 찾는다.\n"
)


def test_a_locale_redirect_is_seen() -> None:
    assert locale_redirect("https://claude.com/pricing", "https://claude.com/ko/pricing") == {
        "asked": "https://claude.com/pricing", "landed": "https://claude.com/ko/pricing"}
    assert locale_redirect("https://chatgpt.com/pricing", "https://chatgpt.com/ko-KR/pricing/")


def test_ordinary_moves_are_not_locale_redirects() -> None:
    assert locale_redirect("https://claude.com/ko/pricing", "https://claude.com/ko/pricing") is None
    assert locale_redirect("https://www.saramin.co.kr/zf_user/jobs", "https://www.saramin.co.kr/zf_user/jobs/list") is None
    assert locale_redirect("https://claude.com/pricing", "https://login.claude.com/ko/") is None, "다른 호스트는 지역 이동이 아니다"


def test_the_fallback_sentences_come_from_the_request() -> None:
    clauses = _fallback_clauses(PROMPT)
    assert "원화만 보이면 원화 그대로 적고 환율로 바꾸지 않는다." in clauses
    assert any("그래도 안 되면" in clause for clause in clauses)
    assert _fallback_clauses("사람인에서 여수 회계 공고 3개 찾아 엑셀로 정리해줘") == []


def test_the_open_result_carries_the_fallback() -> None:
    moved = locale_redirect("https://claude.com/pricing", "https://claude.com/ko/pricing")
    observation = {"ok": True, "result": {"url": "https://claude.com/ko/pricing", "locale_redirect": moved,
                                          "instruction": LOCALE_REDIRECT_NOTE.format(**moved)}}
    out = _unkeepable_notice(observation, PROMPT)["result"]
    assert "지킬 수 없다" in out["instruction"]
    assert "「원화만 보이면 원화 그대로 적고 환율로 바꾸지 않는다.」" in out["instruction"]
    assert "답(과 파일)에 적어라" in out["instruction"]


def test_nothing_is_added_without_a_redirect_or_without_a_fallback() -> None:
    plain = {"ok": True, "result": {"url": "https://claude.com/ko/pricing"}}
    assert _unkeepable_notice(plain, PROMPT) is plain
    moved = {"ok": True, "result": {"locale_redirect": {"asked": "a", "landed": "b"}, "instruction": "x"}}
    assert _unkeepable_notice(moved, "가격표 만들어줘")["result"]["instruction"] == "x", "대안을 지어내지 않는다"
