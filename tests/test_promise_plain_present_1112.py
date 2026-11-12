"""반말 현재형 예고 (2026-11-12 맥 판 ca3566f3).

대표 「다음 주 HN 어떻게 하기로 했더라」 → 한글 문서를 읽고 최종 답이 「문서 원문을 읽었다. HN 관련 내용을 구체적으로 정리한다.」
33자로 끝나 사람에게 갔다. 존댓말 현재형(「~확인합니다」)은 그물이 있었고 같은 뜻의 반말 꼴만 비어 있었다.

역검증(넣기 전 운영 답 전체): PC 5,721개 · 맥 263개 — 새로 걸린 12개가 전부 진짜 예고, 헛걸림 0.
"""
from __future__ import annotations

import pytest

from alture_jarvis.promise_gate import _only_a_promise

# 운영에서 사람에게 최종 답으로 나간 예고들(역검증에서 새로 걸린 것 그대로).
CAUGHT = (
    "문서 원문을 읽었다. HN 관련 내용을 구체적으로 정리한다.",
    "2번 페이지가 11개 요소만 잡혔다 — 결제장벽 화면일 가능성이 있다. 확인한다.",
    "옥션 상세가 열렸다. 가격과 배송비를 읽는다.",
    "검색 결과 화면이 다시 열렸다. 원익피앤이 공고의 주소를 목록에서 받아 연다.",
    "옥션 목록 30건은 전부 케이스·필름·거치대다. 본체 태블릿을 잡기 위해 카테고리 필터를 걸고 다시 검색한다.",
    "네이버쇼핑은 이번 판에서 열지 못했고, 다나와에서 확인한 값만 있다. 브라우저를 닫고 정리한다.",
)

# 결과 · 사실을 말한 답 — 걸리면 안 된다.
KEPT = (
    "가장 최근 유통 판단은 11월 9일 문서다.",
    "문서 원문을 읽었다.",
    "전문가들은 성장으로 본다.",
    "결론: 맥판에서 먼저 친다.",
    "HN 글은 맥판 베타와 같은 날 올리기로 정리돼 있다.",
)


@pytest.mark.parametrize("answer", CAUGHT)
def test_a_plain_present_next_step_is_a_promise(answer: str) -> None:
    assert _only_a_promise(answer), answer


@pytest.mark.parametrize("answer", KEPT)
def test_a_plain_result_is_not_a_promise(answer: str) -> None:
    assert not _only_a_promise(answer), answer


def test_a_long_plain_answer_is_left_alone() -> None:
    body = "HN 은 맥판 베타와 묶는다. " * 20 + "마지막으로 정리한다."
    assert len(body) > 200
    assert not _only_a_promise(body)


# ★ 2026-11-13 맥 판 14c76267: 단계 규칙에 브라우저가 막힌 뒤 「…서버 목록 화면으로 간다.」로 끝났다.
#   ① 「간다」가 그물에 없었고 ② 첫 문장이 괄호 덧말로 끝나 평서형 검사에서 먼저 떨어졌다.
def test_moving_to_a_screen_is_a_promise_even_after_a_bracketed_aside() -> None:
    real = ("mcp.so 제출 페이지를 읽었다(유료 $39 즉시·무료 심사). sonjari 등록 여부는 목록에서 확인해야 한다 — "
            "서버 목록 화면으로 간다.")
    assert _only_a_promise(real)
    assert _only_a_promise("요약 화면으로 돌아간다.")
    assert _only_a_promise("다음 페이지로 넘어간다.")


def test_moving_words_that_are_not_a_next_step_stay_answers() -> None:
    for text in ("그는 학교로 간다.", "시간이 간다.", "가격을 정리했다(단위 원).", "세 곳을 읽었다. 결과는 표로 정리했다."):
        assert not _only_a_promise(text), text
