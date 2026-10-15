"""분야 팩 0판 (2026-09-27 · 전략안 §50) — 형식·기본 꺼짐·켜고 끄기·꺼지면 사라지는가·유니티 마법사."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.code_runtime import select_code_tool_profile
from alture_jarvis.config import JarvisConfig
from alture_jarvis.packs import PackError, PackRegistry, load_packs
from alture_jarvis.skills import SkillLibrary
from alture_jarvis.unity_editor import EDITOR_TOOL_NAMES
from alture_jarvis.unity_tools import UNITY_TOOL_NAMES, UnityTools

REPO = Path(__file__).resolve().parents[1]


def _pack(root: Path, pack_id: str, **overrides) -> Path:
    folder = root / pack_id
    folder.mkdir(parents=True)
    data = {
        "id": pack_id, "name": "시험 팩", "version": "0.1.0", "kind": "content", "summary": "한 줄",
        "tools": [], "skills": [], "domains": [],
        "permissions": {"reads": [], "writes": [], "runs": [], "network": "쓰지 않는다"},
    }
    data.update(overrides)
    (folder / "pack.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return folder


def test_the_game_pack_ships_and_declares_what_it_touches() -> None:
    packs, problems = load_packs(REPO / "packs")
    assert problems == []
    game = packs["game"]
    assert game.kind == "code" and set(game.tools) == set(UNITY_TOOL_NAMES) | {"unity_try_script"} | set(EDITOR_TOOL_NAMES)
    assert game.skills == ("game-unity",) and "game" in game.domains
    for key in ("reads", "writes", "runs", "network"):
        assert game.permissions[key], f"켜는 사람이 {key} 를 보고 동의해야 한다"
    assert (REPO / game.bench).is_dir(), "측정된 팩 — 벤치 과제가 같이 있어야 한다"


def test_a_pack_that_does_not_say_what_it_touches_is_refused(tmp_path: Path) -> None:
    folder = _pack(tmp_path, "sneaky")
    data = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    del data["permissions"]["network"]
    (folder / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    packs, problems = load_packs(tmp_path)
    assert "sneaky" not in packs and any("network" in problem for problem in problems), "조용히 빠지지 않고 이유를 남긴다"


def test_a_content_pack_cannot_carry_tools(tmp_path: Path) -> None:
    _pack(tmp_path, "recipes-only", tools=["local_run_shell"])
    packs, problems = load_packs(tmp_path)
    assert "recipes-only" not in packs and any("content" in problem for problem in problems)


def test_the_id_must_match_the_folder(tmp_path: Path) -> None:
    _pack(tmp_path, "alpha", id="beta")
    with pytest.raises(PackError):
        from alture_jarvis.packs import _load_manifest

        _load_manifest(tmp_path / "alpha")


def test_packs_start_off_and_remember_being_turned_on(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path)
    assert not registry.is_enabled("game"), "분야 팩은 기본으로 꺼져 있다"
    assert registry.tool_enabled("unity_run_recipe") is False
    assert registry.tool_enabled("local_read_text_file") is True, "팩과 무관한 도구는 늘 켜져 있다"
    called: list[bool] = []
    registry.on_change(lambda: called.append(True))
    assert registry.set_enabled("game", True)["enabled"] is True and called
    assert PackRegistry(REPO / "packs", tmp_path).is_enabled("game"), "다시 켜도 남는다"
    assert registry.skill_dirs() == [REPO / "packs" / "game" / "skills"]
    registry.set_enabled("game", False)
    assert registry.skill_dirs() == []
    with pytest.raises(PackError):
        registry.set_enabled("nope", True)


def test_turning_the_pack_off_removes_tools_skills_and_the_code_branch(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    tools = UnityTools(config, object(), packs=registry)
    library = SkillLibrary(JarvisConfig(runtime_root=REPO, skills_dir=REPO / "skills"), extra_dirs=registry.skill_dirs)
    registry.on_change(library.reload)

    assert tools.active_ollama_tools == []
    assert "game-unity" not in library.skills
    names_off = {"local_read_text_file"}
    assert not (UNITY_TOOL_NAMES & select_code_tool_profile("유니티 프리팹 점검해줘", available=names_off).tool_names)

    registry.set_enabled("game", True)
    assert {tool["function"]["name"] for tool in tools.active_ollama_tools} == set(UNITY_TOOL_NAMES) | set(EDITOR_TOOL_NAMES),         "초안 문(unity_try_script)은 바깥 AI 전용 — 온텔릭 자신의 모델에게는 안 보인다"
    assert "game-unity" in library.skills
    names_on = names_off | set(UNITY_TOOL_NAMES)
    assert UNITY_TOOL_NAMES <= select_code_tool_profile("유니티 프리팹 점검해줘", available=names_on).tool_names


def test_a_disabled_pack_tool_says_how_to_turn_it_on(tmp_path: Path) -> None:
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.tool_gateway import ToolGateway

    registry = PackRegistry(REPO / "packs", tmp_path)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    tools = UnityTools(config, object(), packs=registry)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    tools.register(gateway)
    out = gateway.execute("unity_list_recipes", {}, job_id="j")
    assert not out.ok and "pack_disabled" in str(out.error) and "설정" in str(out.error)


def test_the_agent_drops_pack_requirements_it_cannot_meet() -> None:
    source = (REPO / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert "str(item.target) in (UNITY_TOOL_NAMES | EDITOR_TOOL_NAMES)" in source and "str(item.target) not in self.tools.names" in source
    assert source.count("available=self.tools.names") >= 2, "처음 판과 이어 가는 판 둘 다"


def test_the_api_exposes_packs_and_the_wizard() -> None:
    source = (REPO / "src" / "alture_jarvis" / "api.py").read_text(encoding="utf-8")
    for route in ('"/v1/packs"', '"/v1/packs/{pack_id}/{action}"', '"/v1/packs/game/unity"',
                  '"/v1/packs/game/unity/project"', '"/v1/packs/game/unity/hub"'):
        assert route in source, route
    assert "grant_path_by_person" in source, "고른 프로젝트는 설정 › 권한과 같은 장부로, 사람의 허락으로 연다"


# ── 유니티 마법사 ─────────────────────────────────────────────────────────────


class _Local:
    def __init__(self, allowed: Path | None) -> None:
        self.allowed = allowed

    def resolve_export_path(self, raw: str) -> Path:
        if self.allowed is None or not str(Path(raw).resolve()).lower().startswith(str(self.allowed.resolve()).lower()):
            raise PermissionError("no")
        return Path(raw)


def _wizard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, hub: bool, editor: str, license: bool,
            project: str, allowed: bool) -> dict:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    editors = tmp_path / "Editors"
    if editor:
        (editors / editor / "Editor").mkdir(parents=True)
        (editors / editor / "Editor" / "Unity.exe").write_bytes(b"")
    config.unity_editor_roots = str(editors)
    projects = tmp_path / "work"
    if project:
        root = projects / "Game"
        (root / "ProjectSettings").mkdir(parents=True)
        (root / "Assets").mkdir()
        (root / "ProjectSettings" / "ProjectVersion.txt").write_text(f"m_EditorVersion: {project}\n", encoding="utf-8")
    tools = UnityTools(config, _Local(projects if allowed else None))
    monkeypatch.setattr(UnityTools, "hub_path", lambda self: "C:/Hub/Unity Hub.exe" if hub else "")
    monkeypatch.setattr(UnityTools, "license_present", lambda self: license)
    monkeypatch.setattr(UnityTools, "_PROJECT_ROOTS", (str(projects),))
    monkeypatch.setattr(UnityTools, "_DRIVE_ROOTS", ())
    monkeypatch.setattr("alture_jarvis.unity_tools._hub_install_roots", lambda: [])
    return tools.setup_status()


@pytest.mark.parametrize(("case", "expected"), [
    (dict(hub=False, editor="", license=False, project="", allowed=False), "install_hub"),
    (dict(hub=True, editor="", license=False, project="", allowed=False), "open_hub"),
    (dict(hub=True, editor="6000.6.3f1", license=False, project="", allowed=False), "open_hub"),
    (dict(hub=True, editor="6000.6.3f1", license=True, project="", allowed=False), "pick_project"),
    (dict(hub=True, editor="6000.6.3f1", license=True, project="6000.6.3f1", allowed=False), "allow_project"),
    (dict(hub=True, editor="6000.6.3f1", license=True, project="2022.3.40f1", allowed=True), "open_hub"),
    (dict(hub=True, editor="6000.6.3f1", license=True, project="6000.6.3f1", allowed=True), "ready"),
])
def test_the_wizard_names_the_first_blocked_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case, expected) -> None:
    status = _wizard(tmp_path, monkeypatch, **case)
    assert status["next"]["kind"] == expected, status["next"]
    assert status["next"]["text"], "무엇을 하면 되는지 한 줄"


def test_the_wizard_says_which_version_a_project_needs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status = _wizard(tmp_path, monkeypatch, hub=True, editor="6000.6.3f1", license=True, project="2022.3.40f1", allowed=True)
    assert "2022.3.40f1" in status["next"]["text"]
    assert status["projects"][0]["editor_installed"] is False


def test_the_wizard_never_reads_the_license_contents(tmp_path: Path) -> None:
    source = (REPO / "src" / "alture_jarvis" / "unity_tools.py").read_text(encoding="utf-8")
    block = source[source.index("def license_present"):source.index("def _project_state_path")]
    assert "is_file()" in block and "read_text" not in block and "open(" not in block
