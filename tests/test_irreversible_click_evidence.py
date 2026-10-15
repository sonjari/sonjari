"""되돌릴 수 없는 클릭은 승인만 받는 게 아니라 **증거도** 받아야 한다.

레시피 안에서는 변경 스텝에 `expect` 가 없으면 로드 시점에 거부된다. 그런데 범용
`browser_click_confirmed` 는 `expect` 없이 불러도 아무 검증 없이 `clicked` 를
돌려줬다 — 사람 승인은 받는데 증거는 안 받는 자리였다.

기록된 사고가 거의 전부 이 모양이다:
  · 빈 공간에 세 번 클릭하고 세 번 다 성공 보고 (2026-08-05, 다이얼로그는 그대로)
  · 도구가 예외를 안 던졌다는 이유로 성공, any(step.ok) 집계도 무의미

무동작을 잡는 데는 셀렉터도 예측도 필요 없다. 화면이 하나도 안 바뀌었다는 사실만으로
충분하고, 그건 `_page_signals` 가 이미 잰다.

★ 그리고 정직하게: 화면이 바뀌었다고 **의도한 일이 일어난 건 아니다.** 오류
페이지로 넘어가도 화면은 바뀐다. 이 계층이 잡는 것은 조용한 **무동작**이지 잘못된
동작이 아니다 — 그래서 바뀌었을 때 `verified: True` 를 주지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from test_browser_generic_control import El, Frame, Page, _worker

_BEFORE = "저장 전 화면입니다. 여기에 글이 있습니다."
_AFTER = "저장되었습니다. 초안이 갱신되었고 목록이 늘었습니다."


def _screen(button: str, *, reacts: bool) -> tuple[Page, El]:
    """누르면 본문이 바뀌는(또는 안 바뀌는) 화면.

    ref 는 스냅샷이 찍어 준다 — 지어내면 stale_element_ref 로 막힌다. 그게 맞다.
    """
    frame = Frame(elements=[], body=_BEFORE)

    def on_click() -> None:
        if reacts:
            frame.body = _AFTER

    element = El(tag="button", text=button, on_click=on_click)
    frame.elements = [element]
    return Page([frame]), element


# ---- 무동작 검출 ------------------------------------------------------------

def test_a_dead_click_is_not_reported_as_success(tmp_path: Path) -> None:
    """승인까지 받은 클릭이 화면을 하나도 안 건드렸으면 그건 실패다."""
    page, target = _screen("삭제", reacts=False)
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click_confirmed(page, {"ref": target.ref, "verify_timeout_ms": 600})

    assert result["verified"] is False, (
        "아무 일도 안 일어났는데 성공으로 돌려주면, 빈 공간을 세 번 누르고도 "
        "세 번 다 됐다고 말하던 그 고장 그대로다"
    )
    assert result["what_changed"] == []
    assert "다시 누르지 마라" in result["instruction"], (
        "되돌릴 수 없는 동작을 두 번 하는 것이 최악이다 — 재시도를 막아야 한다"
    )


def test_a_click_that_moves_the_screen_is_not_called_verified(tmp_path: Path) -> None:
    """바뀌었다고 '검증됐다'고 하면 안 된다 — 오류 페이지로 가도 화면은 바뀐다."""
    page, target = _screen("삭제", reacts=True)
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click_confirmed(page, {"ref": target.ref, "verify_timeout_ms": 600})

    assert result["what_changed"], "바뀐 것을 못 잡으면 무동작 검출 자체가 무의미하다"
    assert result.get("verified") is not True, (
        "'무언가 바뀌었다'와 '의도한 일이 일어났다'는 다르다 — 이걸 뭉개면 "
        "과장된 확신을 주고, 그게 이 저장소가 반복해서 데인 방식이다"
    )
    assert "의도한 일이" in result["instruction"]


def test_the_absence_of_a_prediction_is_recorded(tmp_path: Path) -> None:
    page, target = _screen("삭제", reacts=True)
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click_confirmed(
        page, {"ref": target.ref, "verify_timeout_ms": 600}
    )

    assert result["predicted"] is False, "예측 없이 누른 사실 자체가 보여야 한다"


def test_an_ordinary_click_pays_nothing(tmp_path: Path) -> None:
    """되돌릴 수 있는 평범한 클릭은 지문을 안 뜬다 — 모든 클릭에 걸면 너무 비싸다."""
    page, target = _screen("다음 페이지", reacts=False)
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click(page, {"ref": target.ref})

    assert "predicted" not in result and "what_changed" not in result


# ---- 승인 우회 구멍 ---------------------------------------------------------

def test_a_caller_cannot_grant_itself_approval(tmp_path: Path) -> None:
    """`_approved` 를 인자로 얹어서 L2 승인을 건너뛸 수 없어야 한다.

    예전에는 승인이 `arguments["_approved"]` 였고, `_execute` 도 `ToolGateway` 도
    인자를 스키마로 거르지 않는다. 그래서 L1 인 browser_click 에 `_approved: true`
    한 줄이면 결제·삭제·발행의 화면 승인이 통째로 우회됐다.
    """
    page, target = _screen("결제하기", reacts=True)
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    with pytest.raises(RuntimeError, match="irreversible_click_needs_approval"):
        worker._click(page, {"ref": target.ref, "_approved": True})


def test_private_arguments_never_reach_a_handler(tmp_path: Path) -> None:
    """밑줄로 시작하는 인자는 바깥에서 오면 안 되는 값이다 — 문 앞에서 떨어낸다."""
    seen: dict[str, Any] = {}
    worker = _worker(tmp_path)
    worker._current_page = lambda: None  # type: ignore[assignment]
    worker._show_visual = lambda *a, **k: None  # type: ignore[assignment]

    def _fake_wait(page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        seen.update(arguments)
        return {"ok": True}

    worker._wait = _fake_wait  # type: ignore[assignment]
    worker._execute("browser_wait", {"milliseconds": 10, "_approved": True, "_recipe": True})

    assert "_approved" not in seen and "_recipe" not in seen
    assert seen["milliseconds"] == 10, "멀쩡한 인자까지 떨어내면 안 된다"


def test_the_approved_door_still_opens(tmp_path: Path) -> None:
    # 구멍을 막느라 정상 경로를 막으면 안 된다.
    page, target = _screen("결제하기", reacts=True)
    worker = _worker(tmp_path)
    worker._snapshot(page, {})

    result = worker._click_confirmed(
        page, {"ref": target.ref, "verify_timeout_ms": 600}
    )

    assert result["action"] == "clicked"
