"""맥의 유니티 무대 — 다리로 찾고 에디터 안에서 찍는다 (2026-11-08 밤 대표: 「에디터가 있는데도 안 뜬다」).

무대는 윈도우 창 목록(EnumWindows)으로 Unity.exe 를 찾아서 맥에서는 늘 no_editor 였다. 맥은 창 녹화에 「화면 기록」 권한이
필요해서 쓰지 않고, 유니티가 스스로 그리는 찍기(다리 `stage_shot`)로 비춘다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.unity_stage import bridge_stage


class _Bridge:
    def __init__(self, editors: list[dict]) -> None:
        self.editors = editors
        self.shots = 0

    def live_editors(self) -> list[dict]:
        return self.editors

    def stage_shot(self, source: str = "scene_view") -> tuple[bytes, int, int]:
        assert source == "scene_view"
        self.shots += 1
        return f"jpeg-{self.shots}".encode(), 640, 360


def test_an_open_editor_known_to_the_bridge_is_shown() -> None:
    bridge = _Bridge([{"project": "/Users/d/Documents/Sonjari/BugGuard", "project_name": "BugGuard", "alive": True}])
    stage = bridge_stage(bridge, interval=0.0)
    assert stage.status()["status"] == "ready" and "BugGuard" in stage.status()["title"]
    frame = stage.frame(after=0, wait=0)
    assert frame and frame["jpeg"] == b"jpeg-1" and stage.problem == ""


def test_no_live_editor_is_still_no_editor() -> None:
    stage = bridge_stage(_Bridge([{"project": "/x", "alive": False}]), interval=0.0)
    assert stage.status()["status"] == "no_editor"
    assert stage.frame(after=0, wait=0) is None and stage.problem == "no_editor"


def test_mac_shots_are_spaced_out() -> None:
    bridge = _Bridge([{"project": "/x", "project_name": "X", "alive": True}])
    stage = bridge_stage(bridge, interval=60.0)
    stage.frame(after=0, wait=0)
    stage.frame(after=1, wait=0)
    assert bridge.shots == 1, "에디터 안 찍기는 무겁다 — 간격 안에서는 다시 찍지 않는다"


def test_runtime_picks_the_bridge_stage_off_windows() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "runtime.py").read_text(encoding="utf-8")
    assert 'UnityStage() if os.name == "nt" else bridge_stage(self.unity_tools.editor)' in source
