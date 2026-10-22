"""비전 계획의 숫자를 action-previews 폴더의 visual_plans.jsonl 에 남긴다 (2026-10-19).

`visual_preview` 는 비전이 고른 좌표가 그림 밖이면 숫자를 **오류 문장**에 넣지 않는다
(같은 실패 되풀이를 세는 열쇠가 문장 전체다). 대신 그 숫자를 기록 파일로 남긴다 —
성공이든 실패든 한 번씩.

1. 범위 밖 좌표 → 오류 문장은 예전 그대로(숫자 없음) · jsonl 에 in_bounds=false 와 x · y
2. 범위 안 좌표 → jsonl 에 in_bounds=true
3. 파일을 못 써도(쓰기 실패) 본래 동작은 그대로
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import window_view
from alture_jarvis.config import JarvisConfig
from alture_jarvis.window_view import Monitor, Rect
from alture_jarvis.windows_automation import WindowsAutomationTools

PRIMARY = Monitor(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1032), True)


class _FakeDesk:
    """범위 판정만 필요 — 화면 안 창이라 옮기지 않는다."""

    def __init__(self, rect: Rect) -> None:
        self._rect = rect

    def monitors(self) -> list[Monitor]:
        return [PRIMARY]

    def rect(self, hwnd: int) -> Rect:
        return self._rect

    def is_minimized(self, hwnd: int) -> bool:
        return False

    def is_maximized(self, hwnd: int) -> bool:
        return False

    def restore(self, hwnd: int) -> None:
        return None

    def move(self, hwnd: int, rect: Rect) -> bool:
        return True


def _automation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planner: Any):
    from alture_jarvis import windows_automation

    tools = WindowsAutomationTools(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"),
        visual_planner=planner,
    )
    desk = _FakeDesk(Rect(0, 0, 968, 524))
    monkeypatch.setattr(window_view, "desktop", lambda: desk)
    monkeypatch.setattr(window_view.time, "sleep", lambda _s: None)
    monkeypatch.setattr(windows_automation.time, "sleep", lambda _s: None)
    monkeypatch.setattr(tools.presence, "wait_until_idle", lambda **kw: True)
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"png")
    monkeypatch.setattr(
        tools, "_capture_window",
        lambda window_id, prefix: (shot, {"left": 0, "top": 0, "right": 968, "bottom": 524}),
    )
    return tools


def _plan_lines(tools: WindowsAutomationTools) -> list[dict[str, Any]]:
    path = tools.preview_dir / "visual_plans.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_out_of_bounds_keeps_the_old_message_and_logs_the_numbers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _automation(tmp_path, monkeypatch, planner=lambda *_a: {"x": 2400, "y": 30, "confidence": 0.9})
    with pytest.raises(RuntimeError) as caught:
        tools.visual_preview({"window_id": 48959036, "instruction": "설정 버튼"})
    message = str(caught.value)
    # 오류 문장은 예전 그대로 — 부를 때마다 바뀌는 숫자는 문장에 없다
    assert message.startswith("visual_coordinate_out_of_bounds: 비전이 고른 자리가 창 그림(968x524) 밖입니다")
    assert "2400" not in message and "30" not in message
    # 대신 기록에는 숫자가 남는다
    lines = _plan_lines(tools)
    assert len(lines) == 1
    row = lines[0]
    assert row["in_bounds"] is False
    assert row["x"] == 2400 and row["y"] == 30
    assert row["window_id"] == 48959036
    assert row["width"] == 968 and row["height"] == 524
    assert row["instruction"] == "설정 버튼"
    assert row["screenshot"].endswith("shot.png")
    assert row["at"]  # ISO 시각이 있다


def test_in_bounds_logs_in_bounds_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _automation(tmp_path, monkeypatch, planner=lambda *_a: {"x": 50, "y": 40, "confidence": 0.9})
    result = tools.visual_preview({"window_id": 7, "instruction": "확인"})
    assert result["action"] == "windows_visual_preview"
    lines = _plan_lines(tools)
    assert len(lines) == 1
    row = lines[0]
    assert row["in_bounds"] is True
    assert row["x"] == 50 and row["y"] == 40
    assert row["confidence"] == 0.9


def test_a_plan_that_cannot_be_written_does_not_break_the_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _automation(tmp_path, monkeypatch, planner=lambda *_a: {"x": 50, "y": 40, "confidence": 0.9})
    # 기록 파일 이름 자리에 폴더를 두면 open("a") 이 IsADirectoryError 로 죽는다 — 예외가 삼켜져야
    (tools.preview_dir / "visual_plans.jsonl").mkdir()
    result = tools.visual_preview({"window_id": 7, "instruction": "확인"})
    assert result["action"] == "windows_visual_preview"
    assert result["target"]["relative_x"] == 50
    assert result["requires_approval"] is True
