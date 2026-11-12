"""유니티 에디터 띄우기 (2026-11-11 · 대표 맥 게임 판) — 양방향(해야 할 때 · 하면 안 될 때).

맥 판 12개 중 4개가 「이어진 에디터 없음」에서 멈췄다. 새 프로젝트에 다리 패키지가 빠졌고, 설정의 「에디터 잇기」 목록에
그 프로젝트가 없었고, 모델은 「사람에게 물어라」만 따랐다. 마지막 판은 셸로 `open -a Unity` 를 불러 에디터가 맨 앞으로 튀었다.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import unity_editor
from alture_jarvis.models import RiskLevel
from alture_jarvis.unity_editor import EDITOR_TOOL_NAMES, PACKAGE_NAME, UnityBridgeError, UnityEditorBridge

REPO = Path(__file__).resolve().parents[1]


class Hello:
    """인사만 하는 유니티 다리(이어졌나 보기는 인사 한 줄로 가른다)."""

    def __init__(self) -> None:
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.sendall(b"WELCOME UNITY-MCP 1 FRAMING=1\n")
                except OSError:
                    pass

    def close(self) -> None:
        self.server.close()


def _project(root: Path, name: str = "SurvivalWave", version: str = "6000.6.3f1") -> Path:
    project = root / name
    (project / "Assets").mkdir(parents=True)
    (project / "ProjectSettings").mkdir()
    (project / "ProjectSettings" / "ProjectVersion.txt").write_text(f"m_EditorVersion: {version}\n", encoding="utf-8")
    (project / "Packages").mkdir()
    (project / "Packages" / "manifest.json").write_text(json.dumps({"dependencies": {"com.unity.ugui": "2.6.0"}}), encoding="utf-8")
    return project


class FakeTools:
    def __init__(self, project: Path, editors: dict[str, Path]) -> None:
        self.project = project
        self.editors = editors
        self.remembered: list[Path] = []

    def _project(self, arguments: dict[str, Any], *, write: bool) -> Path:
        assert write, "다리를 적으니 쓰기 허락을 본다"
        return self.project

    def editor_for(self, version: str) -> Path:
        if version not in self.editors:
            raise FileNotFoundError(f"unity_editor_missing: {version}")
        return self.editors[version]

    def remember_project(self, path: Path) -> None:
        self.remembered.append(path)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _bridge(tmp_path: Path, tools: FakeTools, status: Path, spawn, clock: Clock) -> UnityEditorBridge:
    config = SimpleNamespace(data_dir=tmp_path / "data", packs_dir=REPO / "packs")
    bridge = UnityEditorBridge(config, tools, status_dir=status, spawn=spawn, sleep=clock.sleep)
    bridge._monotonic = clock  # noqa: SLF001
    return bridge


def _status_file(status: Path, project: Path, port: int) -> None:
    status.mkdir(exist_ok=True)
    (status / "unity-mcp-status-b004d4ae.json").write_text(json.dumps({
        "unity_port": port, "reloading": False, "reason": "ready",
        "project_path": str(project).replace("\\", "/") + "/Assets", "project_name": project.name, "unity_version": "6000.6.3f1",
    }), encoding="utf-8")


@pytest.fixture()
def hello():
    server = Hello()
    yield server
    server.close()


def test_launch_adds_the_bridge_starts_in_background_and_waits_for_connection(tmp_path: Path, hello: Hello) -> None:
    project = _project(tmp_path)
    exe = tmp_path / "Editor" / "Unity.exe"
    tools = FakeTools(project.resolve(), {"6000.6.3f1": exe})
    status = tmp_path / "status"
    clock = Clock()
    spawned: list[tuple[Path, Path]] = []

    def spawn(editor: Path, proj: Path) -> None:
        spawned.append((editor, proj))
        _status_file(status, proj, hello.port)  # 에디터가 떠서 다리가 상태 파일을 적은 것처럼

    out = _bridge(tmp_path, tools, status, spawn, clock).launch({"project": str(project)})
    assert out["connected"] is True and out["verified"] is True and out["launched"] is True
    assert out["bridge_added"] is True and Path(out["manifest_backup"]).is_file()
    deps = json.loads((project / "Packages" / "manifest.json").read_text(encoding="utf-8"))["dependencies"]
    assert deps[PACKAGE_NAME].startswith("file:") and deps["com.unity.ugui"] == "2.6.0", "다리 한 줄만 더한다"
    assert spawned == [(exe, project.resolve())], "한 번만 띄운다"
    assert tools.remembered == [project.resolve()], "설정의 「에디터 잇기」 목록에도 올라간다"


def test_already_connected_does_nothing(tmp_path: Path, hello: Hello) -> None:
    project = _project(tmp_path)
    status = tmp_path / "status"
    _status_file(status, project.resolve(), hello.port)
    spawned: list[Any] = []
    tools = FakeTools(project.resolve(), {"6000.6.3f1": tmp_path / "x"})
    out = _bridge(tmp_path, tools, status, lambda *a: spawned.append(a), Clock()).launch({})
    assert out["connected"] is True and out["launched"] is False and out["bridge_added"] is False
    assert spawned == []
    assert PACKAGE_NAME not in (project / "Packages" / "manifest.json").read_text(encoding="utf-8"), "이어진 판은 manifest 를 안 건드린다"


def test_an_editor_already_open_is_never_restarted(tmp_path: Path, monkeypatch) -> None:
    """사람이 쓰던 에디터를 끄고 다시 열면 저장 안 한 씬이 날아간다 — 띄우지 않고 창을 한 번 눌러 달라고 한다."""
    import alture_jarvis.unity_tools as unity_tools_module

    project = _project(tmp_path)
    monkeypatch.setattr(unity_tools_module, "editor_is_open", lambda path: True)
    spawned: list[Any] = []
    clock = Clock()
    out = _bridge(tmp_path, FakeTools(project.resolve(), {}), tmp_path / "status", lambda *a: spawned.append(a), clock).launch({})
    assert out["connected"] is False and out["editor_was_open"] is True and out["bridge_added"] is True
    assert spawned == [] and "끄고 다시 열지 마라" in out["note"] and "창을 한 번" in out["note"]
    assert clock.now <= 32, "열린 에디터는 길게 안 기다린다"


def test_no_connection_in_time_says_so_and_does_not_launch_twice(tmp_path: Path) -> None:
    project = _project(tmp_path)
    spawned: list[Any] = []
    clock = Clock()
    tools = FakeTools(project.resolve(), {"6000.6.3f1": tmp_path / "Unity.exe"})
    out = _bridge(tmp_path, tools, tmp_path / "status", lambda *a: spawned.append(a), clock).launch({"wait_sec": 20})
    assert out["connected"] is False and out["launched"] is True and "verified" not in out
    assert len(spawned) == 1 and "다시 띄우지 말고" in out["note"]
    assert 20 <= clock.now <= 23


def test_missing_editor_version_is_not_opened_with_another(tmp_path: Path) -> None:
    project = _project(tmp_path, version="6000.6.3f1")
    spawned: list[Any] = []
    tools = FakeTools(project.resolve(), {"2022.3.1f1": tmp_path / "old.exe"})
    with pytest.raises(FileNotFoundError, match="unity_editor_missing"):
        _bridge(tmp_path, tools, tmp_path / "status", lambda *a: spawned.append(a), Clock()).launch({})
    assert spawned == [], "다른 판으로 열면 프로젝트가 업그레이드된다"


def test_not_a_unity_project_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "NotUnity"
    folder.mkdir()
    with pytest.raises(ValueError, match="unity_project_invalid"):
        _bridge(tmp_path, FakeTools(folder, {}), tmp_path / "status", lambda *a: None, Clock()).launch({})


def test_not_connected_error_points_at_the_launch_tool_not_the_person(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, None, tmp_path / "nowhere", lambda *a: None, Clock())  # type: ignore[arg-type]
    with pytest.raises(UnityBridgeError) as error:
        bridge.look({"what": "hierarchy"})
    text = str(error.value)
    assert "unity_editor_launch" in text and "open -a" not in text and "manifest.json 을 손으로" in text


def test_mac_launch_stays_in_the_background(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(unity_editor.sys, "platform", "darwin")
    monkeypatch.setattr(unity_editor.subprocess, "run", lambda command, **kw: calls.append(command))
    exe = Path("/Applications/Unity/Hub/Editor/6000.6.3f1-arm64/Unity.app/Contents/MacOS/Unity")
    unity_editor._spawn_editor(exe, Path("/Users/me/Documents/Sonjari/game/SurvivalWave"))
    command = calls[0]
    assert command[:5] == ["open", "-g", "-n", "-a", str(Path("/Applications/Unity/Hub/Editor/6000.6.3f1-arm64/Unity.app"))]
    assert command[-2:] == ["-projectPath", str(Path("/Users/me/Documents/Sonjari/game/SurvivalWave"))]


@pytest.mark.skipif(os.name != "nt", reason="윈도우 창 띄우기 옵션")
def test_windows_launch_asks_for_minimized_without_focus(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(unity_editor.subprocess, "Popen", lambda command, **kw: seen.update(command=command, **kw))
    unity_editor._spawn_editor(tmp_path / "Unity.exe", tmp_path / "Game")
    assert seen["command"] == [str(tmp_path / "Unity.exe"), "-projectPath", str(tmp_path / "Game")]
    assert seen["startupinfo"].wShowWindow == 7, "SW_SHOWMINNOACTIVE — 포커스를 안 뺏는다"
    assert seen["creationflags"] & unity_editor.subprocess.DETACHED_PROCESS


def test_launch_is_registered_as_a_local_l1_tool(tmp_path: Path) -> None:
    assert "unity_editor_launch" in EDITOR_TOOL_NAMES
    specs: dict[str, Any] = {}
    gateway = SimpleNamespace(register=lambda spec: specs.__setitem__(spec.name, spec))
    _bridge(tmp_path, FakeTools(tmp_path, {}), tmp_path / "s", lambda *a: None, Clock()).register(gateway)  # type: ignore[arg-type]
    spec = specs["unity_editor_launch"]
    assert spec.risk_level == RiskLevel.L1 and spec.needs_job_context


def test_settings_list_shows_an_allowed_project_nobody_remembered(tmp_path: Path) -> None:
    """손자리가 셸로 만든 프로젝트도 「에디터 잇기」 목록에 뜬다(맥에는 기억 목록 파일조차 없었다)."""
    from alture_jarvis.unity_tools import UnityTools

    found = _project(tmp_path, "SurvivalWave")
    hidden = _project(tmp_path, "NotAllowed")
    tools = UnityTools.__new__(UnityTools)
    tools.editor = _bridge(tmp_path, FakeTools(found, {}), tmp_path / "s", lambda *a: None, Clock())
    tools.remembered_projects = lambda: []  # type: ignore[method-assign]
    tools.find_projects = lambda: [found, hidden]  # type: ignore[method-assign]
    tools._allowed = lambda path: path == found  # type: ignore[method-assign]
    names = [row["name"] for row in tools.editor_view()["projects"]]
    assert names == ["SurvivalWave"], "허락 안 된 프로젝트는 안 보인다"


# ── 맥: 유니티가 스스로 앞으로 나오면 원래 앱으로 (11-11 맥 미니 실측: -g 로도 -j 로도 유니티가 맨 앞으로 나왔다) ──────────

def _keeper(sequence: list[str], **kwargs: Any) -> tuple[int, list[str]]:
    activated: list[str] = []
    clock = Clock()
    frames = iter(sequence)
    restores = unity_editor.keep_front_away_from_unity(
        front=lambda: next(frames, sequence[-1]), activate=activated.append, sleep=clock.sleep, clock=clock, **kwargs)
    return restores, activated


def test_unity_jumping_to_the_front_is_sent_back_behind_the_previous_app() -> None:
    unity = unity_editor.UNITY_BUNDLE_ID
    restores, activated = _keeper(["com.google.Chrome", "com.google.Chrome", unity, "com.google.Chrome", "com.google.Chrome"], seconds=3)
    assert restores == 1 and activated == ["com.google.Chrome"]


def test_a_person_who_keeps_choosing_unity_is_left_alone_after_three_tries() -> None:
    unity = unity_editor.UNITY_BUNDLE_ID
    restores, activated = _keeper(["com.apple.Finder", *([unity] * 200)], seconds=60)
    assert restores == 3 and activated == ["com.apple.Finder"] * 3


def test_it_follows_the_app_the_person_moved_to() -> None:
    unity = unity_editor.UNITY_BUNDLE_ID
    restores, activated = _keeper(["com.google.Chrome", "com.apple.Terminal", unity, "com.apple.Terminal"], seconds=2)
    assert activated == ["com.apple.Terminal"], "사람이 옮겨 간 앱으로 돌려놓는다"


def test_nothing_to_return_to_when_unity_was_already_in_front() -> None:
    unity = unity_editor.UNITY_BUNDLE_ID
    restores, activated = _keeper([unity] * 20, seconds=5)
    assert restores == 0 and activated == []


def test_launch_remembers_the_front_app_before_starting_the_editor(tmp_path: Path, hello: Hello) -> None:
    project = _project(tmp_path)
    status = tmp_path / "status"
    order: list[str] = []
    tools = FakeTools(project.resolve(), {"6000.6.3f1": tmp_path / "Unity"})

    def spawn(editor: Path, proj: Path) -> None:
        order.append("spawn")
        _status_file(status, proj, hello.port)

    config = SimpleNamespace(data_dir=tmp_path / "data", packs_dir=REPO / "packs")
    clock = Clock()
    bridge = UnityEditorBridge(config, tools, status_dir=status, spawn=spawn, sleep=clock.sleep,
                               keep_front=lambda: order.append("keep_front"))
    bridge._monotonic = clock  # noqa: SLF001
    assert bridge.launch({})["connected"] is True
    assert order == ["keep_front", "spawn"]
