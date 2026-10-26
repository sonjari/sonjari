"""틀째 장(부품 없는 결)의 「[사진: …]」 칸도 사람이 끌어다 넣는 사진 자리가 된다 (2026-10-25 판 891b5d6a).

지난 장 103장에 대 보니 바뀐 장은 이 판의 두 장(3 · 7번)뿐이었고, 둘 다 모델이 사진 자리로 적은 칸이었다.
"""

from alture_jarvis import slide_parts

TILE = ('<html><head></head><body><div class="grid">'
        '<div class="tile"><b>PC 파일</b><span>내 폴더의 파일을 찾고 읽는다</span></div>'
        '<div class="tile"><b>[ 제품 화면 사진 ]</b><span>사진 자리 — 사용자님이 넣으실 자리</span></div>'
        '</div><ul class="rows"><li><b>[사진: 매장 전경]</b></li><li><b>결 선택</b>결을 고른다</li></ul></body></html>')


def test_bracket_photo_marks_become_slots() -> None:
    out = slide_parts.mark_photo_slots(TILE)
    slots = slide_parts.slots_of(out)
    assert [s["label"] for s in slots] == ["제품 화면 사진", "매장 전경"]
    assert "사용자님이 넣으실 자리" not in out  # 칸 설명 글은 빠진다
    assert "data-sonjari-slot" in out and out.count("data-sonjari-slot") == 1
    assert slide_parts.mark_photo_slots(out) == out  # 두 번 돌려도 같다


def test_photo_goes_into_a_marked_slot() -> None:
    out = slide_parts.mark_photo_slots(TILE)
    filled = slide_parts.put_photo(out, "s1", "data:image/jpeg;base64,AAAA", alt="제품 화면 사진")
    assert [s["filled"] for s in slide_parts.slots_of(filled)] == [True, False]
    assert "has-photo" in filled


def test_plain_brackets_and_body_text_are_left_alone() -> None:
    html = ('<div class="tile"><b>[참고]</b> 화면 구성은 다음과 같다</div>'
            '<div class="tile">결과는 [사진 없음] 상태로 둔다고 적었다</div>')
    assert slide_parts.mark_photo_slots(html) == html


def test_numbering_continues_after_existing_part_slots() -> None:
    html = ('<div class="pz-photo" data-slot="s1" data-label="팀">[사진: 팀]</div>'
            '<div class="tile">[사진: 매장]</div>')
    out = slide_parts.mark_photo_slots(html)
    assert [s["id"] for s in slide_parts.slots_of(out)] == ["s1", "s2"]
