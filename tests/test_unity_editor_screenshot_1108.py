"""게임 팩 「에디터 보기」 화면 찍기 (2026-11-08 밤 · 설계 generated_reports/bug_guard_game/설계_유니티_화면보기.md).

유니티가 스스로 그려 Temp/SonjariShots 에 저장 → 본체의 그림 보기 곁 호출이 같은 걸음 안에서 보고 답한다. 맥 · 윈도우 같다.
해야 하는 것 · 하면 안 되는 것 양쪽을 본다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from alture_jarvis.unity_editor import UnityBridgeError, UnityEditorBridge

REPO = Path(__file__).resolve().parents[1]


def _bridge(tmp_path: Path, monkeypatch, *, write_to: str | None = "Temp/SonjariShots") -> tuple[UnityEditorBridge, list, Path]:
    project = tmp_path / "Game"
    project.mkdir()
    bridge = UnityEditorBridge(SimpleNamespace(data_dir=tmp_path / "data", packs_dir=REPO / "packs"), None,
                               status_dir=tmp_path / "status")
    sent: list[tuple[str, dict[str, Any]]] = []

    def ask(editor: dict[str, Any], command: str, params: dict[str, Any]) -> Any:
        sent.append((command, dict(params)))
        if write_to is None:
            return {"success": True, "data": {"path": "x.png", "fullPath": str(tmp_path / "elsewhere.png")}}
        folder = project / write_to
        folder.mkdir(parents=True, exist_ok=True)
        shot = folder / params["fileName"]
        Image.new("RGB", (64, 48), (200, 30, 30)).save(shot)
        return {"success": True, "data": {"path": f"{write_to}/{shot.name}", "fullPath": str(shot).replace("\\", "/")}}

    monkeypatch.setattr(bridge, "_ask", ask)
    monkeypatch.setattr(bridge, "_editor_for", lambda arguments: {"project": str(project), "port": 1})
    return bridge, sent, project


def test_screenshot_saves_outside_assets_and_the_model_looks_at_it(tmp_path, monkeypatch) -> None:
    bridge, sent, project = _bridge(tmp_path, monkeypatch)
    seen: list[tuple[int, str]] = []
    bridge.viewer = lambda jpeg, prompt: seen.append((len(jpeg), prompt)) or "빨간 화면이 보인다"
    bridge.cannot_see = lambda: False
    out = bridge.look({"what": "screenshot", "question": "포탑이 보이나"})
    command, params = sent[-1]
    assert command == "manage_scene" and params["action"] == "screenshot" and params["captureSource"] == "game_view"
    assert params["outputFolder"] == "Temp/SonjariShots" and params["includeImage"] is False, "Assets 밖 · 그림은 파일로"
    assert out["answer"] == "빨간 화면이 보인다" and seen and seen[0][0] > 0 and "포탑이 보이나" in seen[0][1]
    assert Path(out["image_path"]).is_file() and "imageBase64" not in str(out)
    assert not (project / "Assets").exists(), "에셋 폴더에 아무것도 안 만든다"


def test_a_model_that_cannot_read_pictures_only_gets_the_path(tmp_path, monkeypatch) -> None:
    bridge, _sent, _project = _bridge(tmp_path, monkeypatch)
    bridge.viewer = lambda jpeg, prompt: pytest.fail("그림을 못 읽는 모델에게 보이면 안 된다")
    bridge.cannot_see = lambda: True
    out = bridge.look({"what": "screenshot"})
    assert "answer" not in out and "image_path" in out and "못 읽는다" in out["note"]


def test_a_path_outside_the_shot_folder_is_never_opened(tmp_path, monkeypatch) -> None:
    bridge, _sent, _project = _bridge(tmp_path, monkeypatch, write_to=None)
    bridge.viewer = lambda jpeg, prompt: pytest.fail("찍기 폴더 밖 파일을 열면 안 된다")
    with pytest.raises(UnityBridgeError, match="unity_screenshot_missing"):
        bridge.look({"what": "screenshot"})


def test_scene_view_and_bad_source(tmp_path, monkeypatch) -> None:
    bridge, sent, _project = _bridge(tmp_path, monkeypatch)
    bridge.look({"what": "screenshot", "source": "scene_view", "camera": "Main Camera"})
    assert sent[-1][1]["captureSource"] == "scene_view" and "camera" not in sent[-1][1], "씬 화면은 카메라 고르기를 안 받는다"
    with pytest.raises(ValueError, match="source"):
        bridge.look({"what": "screenshot", "source": "desktop"})


def test_only_the_latest_twenty_shots_are_kept(tmp_path, monkeypatch) -> None:
    bridge, _sent, project = _bridge(tmp_path, monkeypatch)
    folder = project / "Temp" / "SonjariShots"
    folder.mkdir(parents=True)
    for index in range(25):
        old = folder / f"sonjari-old{index:02d}.png"
        old.write_bytes(b"x")
    bridge.look({"what": "screenshot"})
    assert len(list(folder.glob("sonjari-*.png"))) == UnityEditorBridge.SHOT_KEEP


def test_the_tool_offers_screenshot_and_stays_read_only() -> None:
    bridge = UnityEditorBridge(SimpleNamespace(data_dir=Path("."), packs_dir=REPO / "packs"), None)
    tool = next(t for t in bridge.ollama_tools if t["function"]["name"] == "unity_editor_look")
    props = tool["function"]["parameters"]["properties"]
    assert "screenshot" in props["what"]["enum"] and "question" in props and "source" in props
    source = (REPO / "src" / "alture_jarvis" / "unity_editor.py").read_text(encoding="utf-8")
    assert '"unity_editor_look": (self.look, RiskLevel.L0)' in source
    runtime = (REPO / "src" / "alture_jarvis" / "runtime.py").read_text(encoding="utf-8")
    assert "self.unity_tools.editor.viewer = self._look_at_file" in runtime


def test_game_view_written_late_is_waited_for(tmp_path, monkeypatch) -> None:
    """11-08 밤 실기기: 게임 화면은 isAsync — 요청 성공 뒤 파일이 늦게 생겨 두 번 다 「못 찾았다」였다."""
    import threading

    project = tmp_path / "Game"
    project.mkdir()
    bridge = UnityEditorBridge(SimpleNamespace(data_dir=tmp_path / "data", packs_dir=REPO / "packs"), None,
                               status_dir=tmp_path / "status")
    bridge.SHOT_ASYNC_WAIT_SEC = 3.0

    def ask(editor, command, params):
        shot = project / "Temp" / "SonjariShots" / params["fileName"]
        shot.parent.mkdir(parents=True, exist_ok=True)
        threading.Timer(0.6, lambda: Image.new("RGB", (32, 32)).save(shot)).start()
        return {"success": True, "data": {"fullPath": str(shot), "isAsync": True}}

    monkeypatch.setattr(bridge, "_ask", ask)
    monkeypatch.setattr(bridge, "_editor_for", lambda arguments: {"project": str(project), "port": 1})
    bridge.viewer = lambda jpeg, prompt: "보임"
    bridge.cannot_see = lambda: False
    assert bridge.look({"what": "screenshot"})["answer"] == "보임"
