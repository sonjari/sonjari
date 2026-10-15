"""그림·글꼴로 숨긴 값 — 잘라서 읽고, 판정은 코드가 (2026-09-18)."""

from __future__ import annotations

from typing import Any

from alture_jarvis.ui_vision import UiVision, compare_seen_and_dom, numbers_of


def test_numbers_and_verdicts() -> None:
    assert numbers_of("판매가 25,900원 (정가 32,000)") == ["25900", "32000"]
    assert compare_seen_and_dom("25,900원", "")["verdict"] == "only_in_picture"
    assert compare_seen_and_dom("25,900원", "₩ ◇◆,◇◆◆")["verdict"] == "only_in_picture"
    assert compare_seen_and_dom("25,900원", "판매가 52,600원")["verdict"] == "differs"
    assert compare_seen_and_dom("25,900원", "판매가 25900원")["verdict"] == "same"
    assert compare_seen_and_dom("(없음)", "25900")["verdict"] == "no_numbers_seen"


class _Worker:
    def __init__(self, dom: str) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.dom = dom

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "browser_screenshot":
            return {"path": __file__}  # 아무 파일이나 — 인코딩만 되면 된다
        if name == "browser_read":
            return {"text": self.dom}
        raise AssertionError(name)


class _Client:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.kwargs: dict = {}

    def chat_message(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        self.kwargs = kwargs
        return {"content": self.reply}


def _vision(dom: str, reply: str) -> tuple[UiVision, _Worker, _Client]:
    vision = object.__new__(UiVision)
    worker, client = _Worker(dom), _Client(reply)
    vision.worker, vision.client = worker, client
    return vision, worker, client


def test_a_price_drawn_as_a_picture_is_reported_as_only_in_the_picture() -> None:
    vision, worker, client = _vision(dom="판매가 ₩", reply="판매가 25,900원")
    out = vision.read_value({"ref": "j12", "what": "판매가"})
    assert out["verdict"] == "only_in_picture" and out["numbers_seen"] == ["25900"]
    assert worker.calls[0] == ("browser_screenshot", {"ref": "j12", "pad": 6}), "그 칸만 잘라 본다"
    assert client.kwargs["images"] and client.kwargs["num_predict"] <= 80, "옮겨 적기만, 짧게"
    assert "그림에서 읽었다고 밝혀라" in out["instruction"]


def test_a_box_without_ref_is_cropped_and_no_dom_text_is_invented() -> None:
    vision, worker, _ = _vision(dom="무시", reply="32,000")
    out = vision.read_value({"box": {"x": 10, "y": 20, "width": 80, "height": 30}})
    assert worker.calls[0][1] == {"box": {"x": 10, "y": 20, "width": 80, "height": 30}, "pad": 6}
    assert out["dom_text"] == "" and out["verdict"] == "only_in_picture"
    assert not any(name == "browser_read" for name, _ in worker.calls), "ref 가 없으면 DOM 글자를 지어 읽지 않는다"
