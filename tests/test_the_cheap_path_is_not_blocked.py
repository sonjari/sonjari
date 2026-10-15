"""싸고 확실한 길이 **비싸고 잘 깨지는 길에 막혀 있으면 안 된다.**

## 실측 (2026-08-14, 쿠팡 20걸음 판)

    11 ui_find_target  ERR Page.screenshot: Timeout 20000ms exceeded
    12 ui_find_target  ERR Page.screenshot: Timeout 20000ms exceeded

40초를 통째로 버렸고, 그 판은 찾기를 포기했다. 쿠팡 상세처럼 배너·캐러셀이 계속
도는 페이지에서는 Playwright 가 "화면이 멎기"를 기다리다 시간을 다 쓴다.

그런데 **이 도구의 싼 길은 그림이 필요 없다.** 이름이 딱 하나 맞으면 코드가 바로
고른다(`UiVision._by_name`). 순서가 거꾸로였다 — 그림을 먼저 찍다가 죽으니 이름
찾기까지 가지도 못했다.

## 고친 것 셋

  1. 애니메이션을 얼리고 찍는다(`animations="disabled"`), 타임아웃 8초.
  2. **못 찍어도 목록은 내준다** — `_annotate` 가 예외를 안 올린다.
  3. 그림이 없으면 **비전에 묻지 않는다** — 목록 글자만 보고 번호를 찍는 것은
     판정이 아니라 추측이고, 이 도구가 막으려는 바로 그것이다.
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.browser import _SCREENSHOT_TIMEOUT_MS
from alture_jarvis.ui_vision import UiVision


def _el(ref: str, name: str) -> dict[str, Any]:
    return {"ref": ref, "name": name, "tag": "a"}


class _Client:
    def __init__(self) -> None:
        self.calls = 0

    def chat_message(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {"content": "1"}


class _WorkerNoPicture:
    """그림은 못 찍었지만 목록은 온 상태 — 오늘 실측 그대로."""

    def __init__(self, elements: list[dict[str, Any]]) -> None:
        self.elements = elements
        self.scrolls = 0

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "browser_scroll":
            self.scrolls += 1
            return {"action": "scrolled"}
        return {
            "action": "annotated",
            "path": "",                       # ← 못 찍었다
            "screenshot_failed": "Page.screenshot: Timeout 8000ms exceeded",
            "elements": self.elements,
            "candidates": self.elements,
            "candidate_count": len(self.elements),
        }


def _vision(elements: list[dict[str, Any]]) -> tuple[UiVision, _Client, _WorkerNoPicture]:
    client = _Client()
    worker = _WorkerNoPicture(elements)
    instance = object.__new__(UiVision)
    instance.config = None
    instance.worker = worker
    instance.client = client
    return instance, client, worker


def test_a_name_match_still_works_without_a_picture() -> None:
    """★ 이것이 이 시험의 요점이다.

    그림이 없어도 이름이 하나 맞으면 찾아야 한다. 예전에는 그림을 찍다 죽어서
    여기까지 오지도 못했다.
    """
    vision, client, _ = _vision([_el("j1", "장바구니"), _el("j137", "낮은가격순")])

    result = vision.find({"goal": "낮은가격순"})

    assert result["status"] == "found"
    assert result["ref"] == "j137"
    assert result["method"] == "name_match"
    assert client.calls == 0


def test_without_a_picture_the_model_is_not_asked_to_guess() -> None:
    """목록 글자만 주고 "번호로 답해라"는 판정이 아니라 추측이다."""
    vision, client, worker = _vision([_el("j1", "저장"), _el("j2", "저장")])

    with pytest.raises(RuntimeError, match="ui_target_not_found"):
        vision.find({"goal": "저장"})

    assert client.calls == 0, "그림도 없이 비전에 물었다"
    assert worker.scrolls == 2, "내려 보지도 않고 포기했다"


def test_the_screenshot_budget_is_shorter_than_the_action_budget() -> None:
    """그림은 **거들 뿐**이라, 못 찍어도 계속 갈 수 있어야 한다.

    기본 동작 시간(20초)만큼 붙들면 한 판에서 40초가 그냥 사라진다(실측).
    """
    assert _SCREENSHOT_TIMEOUT_MS <= 10_000


def test_the_capture_freezes_animations() -> None:
    """쿠팡 상세는 배너가 계속 돈다 — 안 얼리면 Playwright 가 끝없이 기다린다."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py"
    ).read_text(encoding="utf-8")
    assert '"animations": "disabled"' in source
