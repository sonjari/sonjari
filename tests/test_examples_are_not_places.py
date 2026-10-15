"""괄호 속 예시는 장소가 아니고, 「로컬 AI」의 로컬은 출처가 아니다 (2026-09-30 손자리 조사 판 e7dd3831).

「…로컬 AI 제품의 초기 마케팅 회고 글 5개를 … 처음 쓴 채널(레딧·해커뉴스·깃허브·트위터 등) …」이
「로컬 자료 5개 읽기 · 깃허브에서 하기」가 됐다. 웹 글을 10개 읽고도 「시킨 곳에서 안 읽었다」로 41걸음을 헤맸고,
그사이 엑셀에 지어낸 숫자가 들어갔다. 운영 요청 1,321개에 옛·새 판정을 돌려 바뀐 것 5개를 전부 눈으로 확인했다.
"""

from __future__ import annotations

from alture_jarvis.plan import extract


def _labels(prompt: str) -> list[str]:
    return [requirement.label for requirement in extract(prompt)]


def test_the_real_research_task() -> None:
    labels = _labels(
        "구글에서 \"how we got our first 1000 users\" 로 검색해, 개발자 도구·오픈소스·로컬 AI 제품의 초기 마케팅 회고 글 5개를 "
        "직접 열어 읽고, 회사·제품 · 처음 쓴 채널(레딧·해커뉴스·깃허브·트위터 등) · 주소를 엑셀(.xlsx)로 정리해 줘."
    )

    assert "깃허브에서 하기" not in labels
    assert not any(label.startswith("로컬 자료") for label in labels)
    assert "5개 이상 직접 열어 읽기" in labels


def test_a_site_in_parentheses_is_a_reference() -> None:
    assert _labels("개발자 포럼에서 스타를 통해 플랫폼 장사를 하는 건데 (깃허브 참고) 어렵나") == []


def test_real_places_stay() -> None:
    assert "깃허브에서 하기" in _labels("깃허브에서 ollama 저장소의 최근 릴리스 3개를 찾아 정리해줘")
    assert {"다나와에서 하기", "쿠팡에서 하기"} <= set(_labels("다나와·쿠팡 등에서 무선 마우스 가격 비교해줘"))
    # 목록 끝 「등등」도 장소다 — 한때 이걸 빼서 사람인이 사라졌다.
    assert "사람인에서 하기" in _labels("브라우저로 사람인, 잡코리아 등등 다양한 이력서 사이트를 조사해서 공고 3개 찾아줘")


def test_local_files_are_still_local() -> None:
    labels = _labels("로컬 문서 3개와 웹 자료 3개를 읽고 비교해줘")

    assert "로컬 자료 3개 이상 직접 열어 읽기" in labels
    assert "웹 자료 3개 이상 직접 열어 읽기" in labels


def test_local_ai_is_a_kind_not_a_source() -> None:
    assert _labels("브라우저에서 요즘 로컬 AI 에이전트 자료 3개를 직접 찾아보고 비교해줘.") == ["3개 이상 직접 열어 읽기"]
