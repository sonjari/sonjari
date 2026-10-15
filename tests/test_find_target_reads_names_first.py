"""이름이 딱 하나 맞으면 그림을 볼 이유가 없다.

## 무엇이 있었나 (2026-08-13, 다나와 정렬)

화면에 `<a>낮은가격순</a>` 이 멀쩡히 있는데 `ui_find_target("낮은가격순 정렬")` 이
**광고 상품 링크**를 골랐다. 그 전 판에서는 아예 "후보 58 개 중에 없습니다"였다.

왜냐하면 그림에 번호를 그릴 수 있는 개수에 한계가 있어서다(비전이 못 읽는다).
후보는 화면에 든 것 중 **앞에서부터 60 개**인데, 다나와는 머리말·배너·광고가
그 60 개를 다 먹는다. 정렬 바는 스냅샷 136 번째다.

이 저장소가 이미 적어 둔 규칙이 있다 — **비전은 읽게 하고 판정은 코드가.**
이름이 딱 하나 맞는 것은 판정이 아니라 조회다. 둘 이상이면 그때가 판정이고,
그건 그림 몫으로 남긴다.

## 좁게 잡는 이유

수집기는 이름 없는 요소에 둘레 글을 빌려 채운다("Python 줄의 연필"). 그래서 긴
이름에는 낱말이 우연히 들어 있다 — 다나와 광고 카드 이름 예순 자 안에 "가격"이
있다. 그것까지 집으면 이 지름길이 곧 새로운 오답 기계가 된다.
"""

from __future__ import annotations

from alture_jarvis.ui_vision import _NAME_MATCH_MAX_CHARS, UiVision

_find = UiVision._by_name


def _el(ref: str, name: str) -> dict:
    return {"ref": ref, "name": name, "tag": "a"}


# 실제 다나와 검색결과에서 뽑은 모양이다.
DANAWA = [
    _el("j58", "오브룸 물방울 버티컬 마우스 투명 무선 블루투스 OV-WM01 핑크 30,900원 무료 오브룸 스토어 별점 안의 a"),
    _el("j136", "인기상품순"),
    _el("j137", "낮은가격순"),
    _el("j138", "높은가격순"),
    _el("j139", "신상품순"),
]


def test_the_exact_label_wins_without_asking_the_picture() -> None:
    hit = _find("낮은가격순 정렬", DANAWA)
    assert hit is not None and hit["ref"] == "j137"


def test_spacing_does_not_matter() -> None:
    """사람에게 '낮은 가격순'과 '낮은가격순'은 같은 말이다."""
    assert _find("낮은 가격순", DANAWA)["ref"] == "j137"
    assert _find("낮은가격순", DANAWA)["ref"] == "j137"


def test_a_long_borrowed_name_is_not_a_label() -> None:
    """광고 카드 이름 안의 '가격'에 걸리면 지름길이 오답 기계가 된다."""
    assert len(DANAWA[0]["name"]) > _NAME_MATCH_MAX_CHARS
    assert _find("가격", DANAWA) is None


def test_two_matches_go_back_to_the_picture() -> None:
    """어느 것인지 고르는 일은 판정이다. 판정은 코드가 하지 않는다."""
    rows = [_el("j1", "저장"), _el("j2", "저장")]
    assert _find("저장", rows) is None


def test_nothing_matching_falls_through() -> None:
    assert _find("장바구니 담기", DANAWA) is None


def test_a_one_letter_goal_is_too_loose() -> None:
    """한 글자는 어디에나 걸린다 — 그건 조회가 아니라 우연이다."""
    assert _find("순", DANAWA) is None
