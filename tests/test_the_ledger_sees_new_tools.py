"""장부가 **새 도구의 증거를 못 보면**, 일한 것이 안 한 것으로 기록된다.

## 실측 (2026-08-14, 쿠팡 카테고리 판)

그날 만든 `browser_hover` 가 실제로 일했다 — 답변에 쿠팡 가전디지털 하위 분류가
17개(모니터·세탁기/건조기·냉장고·TV/영상가전 …) 정확히 나왔다.

그런데 장부에는 이렇게 남았다:

    3 browser_hover  ok=True  나타남=0  before=None  after=None

벤치는 그걸 읽고 **"호버가 아무것도 못 했다"**고 적었다. 도구를 의심할 뻔했다.

원인은 걸음 증거가 **하드코딩 목록**이었던 것이다:

    for key in ("action", "url", "title", "char_count", "element_count")

`appeared`·`visible_before`·`visible_after` 는 그 다섯에 없으니 통째로 버려졌다.

## 목록이 아니라 규칙으로

도구를 만들 때마다 사람이 목록에 이름을 더해야 하면 **언젠가 반드시 잊는다.**
오늘만 세 번째다 — 눈금 분모 구멍, 새 도구가 분류표에 없음, 그리고 여기.

그래서 **뺄 것만 정하고 나머지는 싣는다.**
"""

from __future__ import annotations

from alture_jarvis.agent import (
    _EVIDENCE_LIST_MAX,
    _EVIDENCE_VALUE_MAX,
    _step_evidence,
)


def test_a_brand_new_tools_evidence_survives() -> None:
    """이것이 이 시험의 요점이다 — 아무도 목록에 안 넣어도 남아야 한다."""
    kept = _step_evidence(
        {
            "action": "hovered",
            "url": "https://www.coupang.com/",
            "visible_before": 121,
            "visible_after": 138,
            "appeared": ["모니터", "냉장고", "TV/영상가전"],
        }
    )
    assert kept["visible_before"] == 121
    assert kept["visible_after"] == 138
    assert kept["appeared"] == ["모니터", "냉장고", "TV/영상가전"]


def test_the_big_things_stay_out() -> None:
    """본문·그림까지 실으면 장부가 전사를 먹는다."""
    kept = _step_evidence(
        {"action": "extracted", "char_count": 20000, "text": "가" * 20000, "path": "C:/shot.png"}
    )
    assert kept == {"action": "extracted", "char_count": 20000}


def test_long_values_are_cut_not_dropped() -> None:
    """빼 버리면 '없었다'와 구별이 안 된다. 잘린 값은 있었다는 사실을 남긴다."""
    kept = _step_evidence({"action": "clicked", "note": "가" * 900})
    assert len(kept["note"]) == _EVIDENCE_VALUE_MAX


def test_long_lists_say_how_many_were_cut() -> None:
    kept = _step_evidence({"action": "hovered", "appeared": [f"항목{i}" for i in range(50)]})
    assert len(kept["appeared"]) == _EVIDENCE_LIST_MAX + 1
    assert "외" in kept["appeared"][-1], "몇 개가 잘렸는지 안 적혀 있다"


def test_empty_values_are_skipped() -> None:
    """빈 칸이 늘어서면 장부가 안 읽힌다."""
    kept = _step_evidence({"action": "opened", "url": "", "title": None, "appeared": []})
    assert kept == {"action": "opened"}


def test_zero_is_not_treated_as_empty() -> None:
    """★ '0개 나타났다'는 **정보**다 — 호버가 안 먹혔다는 뜻이니까.

    `value in (None, "", [], {})` 는 파이썬에서 `0 == False` 때문에 자칫 0 과 False 를
    같이 떨어뜨린다. 그 둘은 이 장부에서 제일 중요한 값이다.
    """
    kept = _step_evidence({"action": "hovered", "visible_after": 0, "verified": False})
    assert kept["visible_after"] == 0
    assert kept["verified"] is False
