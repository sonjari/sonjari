"""누가 골랐는지를 결과가 말해야 한다 — 안 그러면 비전 실력을 잘못 잰다.

2026-08-13. `ui_find_target` 이 이름으로 곧장 찾는 지름길을 갖게 됐다
(`UiVision._by_name`). 좋은 일이지만 **눈금에 구멍을 낸다**: 그림을 보지도 않고
맞힌 판이 "비전이 잘 골랐다"로 세어진다.

이 저장소는 같은 병을 여러 번 겪었다 — 만든 것과 도는 것을 구별하지 않는 것.
그래서 결과에 `method` 를 싣고, 재는 자(`scripts/measure_ui_vision.py`)가 갈라서
적는다. 이 시험은 **그 계약**을 지킨다: 두 길 모두 자기가 누구인지 밝힌다.
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.ui_vision import UiVision


class _Worker:
    """`browser_annotate` 와 `browser_scroll` 만 흉내 낸다 — 화면도 크롬도 없다.

    스크롤은 **횟수만 센다.** 이 시험이 지키는 것은 "내려 봤는가"이지 얼마나
    내렸는가가 아니다.
    """

    def __init__(self, elements: list[dict[str, Any]], marked: int) -> None:
        self.elements = elements
        self.marked = marked
        self.scrolls = 0

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "browser_scroll":
            self.scrolls += 1
            return {"action": "scrolled"}
        assert name == "browser_annotate"
        return {
            "path": "",
            "elements": self.elements,
            "candidates": self.elements[: self.marked],
            "candidate_count": self.marked,
        }


class _Client:
    """비전. 불렸는지 기록한다 — 지름길이 도는지 보는 유일한 방법이다."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def chat_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {"content": self.reply}


def _vision(elements: list[dict[str, Any]], marked: int, reply: str = "0") -> tuple[UiVision, _Client]:
    client = _Client(reply)
    instance = object.__new__(UiVision)
    instance.config = None
    instance.worker = _Worker(elements, marked)
    instance.client = client
    # 2026-08-14: 그림이 없으면 비전에 **안 묻는다**(목록 글자만 보고 번호를 찍는 것은
    # 판정이 아니라 추측이라서). 이 시험들은 비전 쪽 길을 재는 것이므로 그림이 있는
    # 셈 친다 — 그림이 없을 때의 동작은 `test_the_cheap_path_is_not_blocked` 가 잰다.
    instance._encode = lambda path: "FAKE_IMAGE_B64"  # type: ignore[method-assign]
    return instance, client


def _el(ref: str, name: str) -> dict[str, Any]:
    return {"ref": ref, "name": name, "tag": "a"}


def test_a_name_hit_says_so_and_never_asks_the_picture() -> None:
    """다나와 정렬이 이 모양이다 — 이름이 정확히 하나 있는데 그림 밖에 있다."""
    elements = [_el(f"j{i}", f"광고 배너 {i}") for i in range(1, 61)]
    elements.append(_el("j137", "낮은가격순"))
    vision, client = _vision(elements, marked=60)

    result = vision.find({"goal": "낮은가격순 정렬"})

    assert result["status"] == "found"
    assert result["ref"] == "j137"
    assert result["method"] == "name_match"
    assert client.calls == 0, "이름으로 찾았는데 비전을 불렀다"


def test_a_picture_pick_is_labelled_as_one() -> None:
    """이름이 안 맞으면 원래대로 그림을 본다. 그때는 method 가 없거나 vision 이다."""
    elements = [_el("j1", "저장"), _el("j2", "저장")]  # 둘이라 이름으로는 못 고른다
    vision, client = _vision(elements, marked=2, reply="2")

    result = vision.find({"goal": "저장"})

    assert result["status"] == "found"
    assert result["ref"] == "j2"
    assert result.get("method", "vision") == "vision"
    assert client.calls == 1


def test_it_scrolls_before_saying_it_is_not_there() -> None:
    """★ 사람은 한 화면 보고 "이 페이지엔 없네요"라고 하지 않는다.

    실측(2026-08-13, 잡 142건): `browser_scroll` 을 쓴 잡이 **9건(6%)**. 프롬프트에
    "스크롤해라"라고 적혀 있는데도 그렇다. 그런데 이 도구의 후보는 **지금 화면에
    든 것**뿐이라, 접힌 아래에 있는 것은 언제나 "없습니다"가 됐다.
    """
    vision, client = _vision([_el("j1", "장바구니")], marked=1, reply="0")

    with pytest.raises(RuntimeError, match="ui_target_not_found"):
        vision.find({"goal": "낮은가격순 정렬"})

    assert vision.worker.scrolls == 2, "내려 보지도 않고 없다고 했다"
    assert client.calls == 3, "내린 뒤에 다시 보지 않았다"


def test_not_found_still_fails_loudly() -> None:
    """지름길이 생겼다고 **못 찾은 것이 성공이 되면 안 된다.**

    2026-08-13 오전에 고친 것이 정확히 이것이다 — `find` 가 조용히 돌려주면
    게이트웨이가 ok=True 로 적어 L2 성공률이 부풀었다(55회 중 53회).
    내려 보는 것이 생겼어도 **끝내 없으면 예외**라는 계약은 그대로다.
    """
    vision, _ = _vision([_el("j1", "장바구니")], marked=1, reply="0")

    with pytest.raises(RuntimeError, match="ui_target_not_found"):
        vision.find({"goal": "낮은가격순 정렬"})


def test_something_below_the_fold_is_found_after_scrolling() -> None:
    """내려서 보이게 된 것은 찾아야 한다 — 그게 스크롤을 넣은 이유다."""

    class _Appearing(_Worker):
        def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if name == "browser_scroll":
                self.scrolls += 1
                # 내리고 나니 정렬 바가 화면에 들어왔다.
                self.elements = [_el("j137", "낮은가격순")]
                self.marked = 1
                return {"action": "scrolled"}
            return super().execute(name, arguments)

    client = _Client("0")
    vision = object.__new__(UiVision)
    vision.config = None
    vision.worker = _Appearing([_el("j1", "장바구니")], marked=1)
    vision.client = client

    result = vision.find({"goal": "낮은가격순 정렬"})

    assert result["status"] == "found"
    assert result["ref"] == "j137"
    assert result["scrolled"] == 1
