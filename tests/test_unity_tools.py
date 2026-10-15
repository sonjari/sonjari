"""게임 팩 — 유니티 실행 문 (2026-09-27).

유니티가 없어도 도는 시험이 대부분이다: 값 검사·자리 허락·버전 고르기·흔적 치우기·프로필·스킬.
실제 유니티로 도는 시험은 `JARVIS_UNITY_LIVE_PROJECT` 가 있을 때만 돈다(집 PC 실측: 텍스처 115개 중 1개,
프리팹 173·씬 5에서 빠진 참조 2건 — 둘 다 원본 YAML 로 진짜임을 확인, 빈 칸은 안 셈).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from alture_jarvis.code_runtime import select_code_tool_profile
from alture_jarvis.config import JarvisConfig
from alture_jarvis.unity_tools import (
    UNITY_TOOL_NAMES,
    UnityRecipeError,
    UnityTools,
    editor_is_open,
    project_version,
)

_REPO = Path(__file__).resolve().parents[1]


class _Local:
    def __init__(self, workspaces: dict[str, Path] | None = None, allowed: Path | None = None) -> None:
        self._code_workspaces = workspaces or {}
        self.allowed = allowed

    def _check(self, raw: str) -> Path:
        path = Path(raw).resolve()
        if self.allowed is None or not str(path).lower().startswith(str(self.allowed.resolve()).lower()):
            raise PermissionError("path_not_allowed")
        return path

    def resolve_allowed_path(self, raw: str, must_exist: bool = True) -> Path:
        return self._check(raw)

    def resolve_export_path(self, raw: str) -> Path:
        return self._check(raw)


def _project(root: Path, version: str = "6000.6.3f1") -> Path:
    project = root / "Game"
    (project / "ProjectSettings").mkdir(parents=True)
    (project / "Assets" / "Art").mkdir(parents=True)
    (project / "Packages").mkdir()
    (project / "ProjectSettings" / "ProjectVersion.txt").write_text(
        f"m_EditorVersion: {version}\nm_EditorVersionWithRevision: {version} (abc)\n", encoding="utf-8"
    )
    (project / "Packages" / "manifest.json").write_text(
        json.dumps({"dependencies": {"com.unity.render-pipelines.universal": "17.0.0"}}), encoding="utf-8"
    )
    (project / "Assets" / "Art" / "hero.png").write_bytes(b"x" * 2048)
    (project / "Assets" / "Art" / "hero.png.meta").write_text("guid: 1", encoding="utf-8")
    (project / "Assets" / "Main.unity").write_text("scene", encoding="utf-8")
    return project


def _tools(tmp_path: Path, local: _Local, editors: Path | None = None) -> UnityTools:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.unity_editor_roots = str(editors or tmp_path / "no_editors")
    return UnityTools(config, local)


def test_the_shipped_recipes_load_with_their_code() -> None:
    config = JarvisConfig()
    tools = UnityTools(config, _Local())
    assert tools.recipe_dir == _REPO / "packs" / "game" / "recipes" / "unity"
    assert {"texture_audit", "missing_references"} <= set(tools.recipes())
    assert (tools.recipe_dir / "_SonjariRecipeIO.cs").is_file(), "레시피가 같이 쓰는 입출력 도우미"
    for name, data in tools.recipes().items():
        assert str(data["risk"]).upper() in {"L0", "L1"}, f"{name}: 첫 레시피들은 읽기만 한다"


def test_values_only_in_the_declared_shape(tmp_path: Path) -> None:
    tools = UnityTools(JarvisConfig(), _Local())
    recipe = tools.recipes()["texture_audit"]
    assert tools._params(recipe, {}) == {"folder": "Assets", "max_size": 2048, "limit": 200}
    assert tools._params(recipe, {"folder": "Assets\\FPS\\Art", "max_size": "1024"})["folder"] == "Assets/FPS/Art"
    for bad in ({"folder": "C:/Windows"}, {"folder": "Assets/../../etc"}, {"max_size": 10},
                {"max_size": "big"}, {"surprise": 1}, {"limit": True}):
        with pytest.raises(UnityRecipeError):
            tools._params(recipe, bad)


def test_the_project_must_be_allowed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    denied = _tools(tmp_path, _Local())
    with pytest.raises(PermissionError, match="unity_project_not_allowed"):
        denied.project_info({"project": str(project)})
    via_workspace = _tools(tmp_path, _Local({"job": project}))
    assert via_workspace.project_info({"__job_id": "job"})["editor_version"] == "6000.6.3f1"
    via_allowed = _tools(tmp_path, _Local(allowed=tmp_path))
    assert via_allowed.project_info({"project": str(project)})["render_pipeline"] == "URP"
    with pytest.raises(ValueError, match="not_a_unity_project"):
        via_allowed.project_info({"project": str(tmp_path)})


def test_project_info_reads_files_without_starting_unity(tmp_path: Path) -> None:
    project = _project(tmp_path)
    info = _tools(tmp_path, _Local({"job": project})).project_info({"__job_id": "job"})
    assert info["asset_counts"] == {"scenes": 1, "textures": 1}, ".meta 는 세지 않는다"
    assert info["scenes"] == ["Assets/Main.unity"]
    assert info["editor_installed"] is False and info["editor_open"] is False


def test_only_the_same_editor_version_is_used(tmp_path: Path) -> None:
    project = _project(tmp_path)
    editors = tmp_path / "Editors"
    (editors / "2022.3.40f1" / "Editor").mkdir(parents=True)
    (editors / "2022.3.40f1" / "Editor" / "Unity.exe").write_bytes(b"")
    tools = _tools(tmp_path, _Local({"job": project}), editors)
    with pytest.raises(FileNotFoundError, match="unity_editor_missing") as caught:
        tools.editor_for(project_version(project))
    assert "업그레이드" in str(caught.value), "다른 버전으로 열면 프로젝트가 바뀐다는 이유를 말한다"
    (editors / "6000.6.3f1" / "Editor").mkdir(parents=True)
    (editors / "6000.6.3f1" / "Editor" / "Unity.exe").write_bytes(b"")
    assert tools.editor_for("6000.6.3f1").parent.parent.name == "6000.6.3f1"


def test_a_stale_lockfile_is_not_an_open_editor(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "Temp").mkdir()
    (project / "Temp" / "UnityLockfile").write_bytes(b"")
    assert editor_is_open(project) is False, "죽은 에디터가 남긴 잠금 파일은 아무도 안 쥐고 있다"


def test_unstage_removes_only_what_we_created(tmp_path: Path) -> None:
    """★ 첫 실측에서 원래 없던 `Assets/Editor` 와 Editor.meta 가 남았다."""
    project = _project(tmp_path)
    stage = project / "Assets" / "Editor" / "SonjariRecipes"
    created = [project / "Assets" / "Editor", stage]
    stage.mkdir(parents=True)
    staged = [stage / "_SonjariRecipeIO.cs", stage / "texture_audit.cs"]
    for path in staged:
        path.write_text("//", encoding="utf-8")
        path.with_name(path.name + ".meta").write_text("m", encoding="utf-8")
    (project / "Assets" / "Editor.meta").write_text("m", encoding="utf-8")
    (project / "Assets" / "Editor" / "SonjariRecipes.meta").write_text("m", encoding="utf-8")
    assert UnityTools._unstage(staged, created) == []
    assert not (project / "Assets" / "Editor").exists() and not (project / "Assets" / "Editor.meta").exists()

    # ★ 반대 표본: 원래 있던 Editor 폴더(사람의 스크립트가 든)는 그대로 둔다.
    mine = project / "Assets" / "Editor"
    mine.mkdir()
    (mine / "MyTool.cs").write_text("//", encoding="utf-8")
    stage.mkdir()
    staged[1].write_text("//", encoding="utf-8")
    assert UnityTools._unstage([staged[1]], [stage]) == []
    assert (mine / "MyTool.cs").is_file() and not stage.exists()


def test_run_refuses_an_unknown_recipe_before_touching_the_project(tmp_path: Path) -> None:
    project = _project(tmp_path)
    tools = _tools(tmp_path, _Local({"job": project}))
    with pytest.raises(UnityRecipeError, match="unknown_recipe"):
        tools.run_recipe({"__job_id": "job", "recipe": "rm_everything"})
    assert not (project / "Assets" / "Editor").exists()


def test_code_mode_opens_unity_tools_when_unity_is_named() -> None:
    assert UNITY_TOOL_NAMES <= select_code_tool_profile("유니티 프로젝트 텍스처 설정 점검해줘").tool_names
    assert UNITY_TOOL_NAMES <= select_code_tool_profile("find missing scripts in my prefabs").tool_names
    assert not (UNITY_TOOL_NAMES & select_code_tool_profile("calc.py 의 add 함수 고쳐줘").tool_names)


def test_the_game_pack_skill_is_served_and_matched() -> None:
    from alture_jarvis.skills import SKILL_TRIGGERS_EN, SKILL_TRIGGERS_KO, match_skills
    from alture_jarvis.skill_domains import DOMAINS

    assert "game-unity" in SKILL_TRIGGERS_KO and "game-unity" in SKILL_TRIGGERS_EN
    assert (_REPO / "packs" / "game" / "skills" / "vendor" / "game" / "game-unity" / "SKILL.md").is_file()
    assert any(domain.id == "game" and "game-unity" in domain.skills for domain in DOMAINS)
    assert match_skills("유니티 프로젝트 프리팹 정리해줘")[0][0] == "game-unity"


def test_the_runtime_registers_and_lists_the_tools() -> None:
    source = (_REPO / "src" / "alture_jarvis" / "runtime.py").read_text(encoding="utf-8")
    assert "self.unity_tools.register(self.gateway)" in source
    catalog = source[source.index("self.agent_tools = AgentToolCatalog("):]
    assert "self.unity_tools," in catalog[:600], "게이트웨이에만 넣고 카탈로그에 안 넣으면 모델이 못 부른다"


@pytest.mark.skipif(not os.environ.get("JARVIS_UNITY_LIVE_PROJECT"), reason="실제 유니티 프로젝트가 있을 때만")
def test_live_texture_audit(tmp_path: Path) -> None:
    project = Path(os.environ["JARVIS_UNITY_LIVE_PROJECT"])
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    tools = UnityTools(config, _Local({"job": project}))
    before = sorted(p.name for p in (project / "Assets").iterdir())
    out = tools.run_recipe({"__job_id": "job", "recipe": "texture_audit", "params": {"limit": 5}})
    assert out["verified"] is True, out
    assert out["result"]["textures_checked"] > 0
    # ★ 2026-10-01: 경로 순서로 앞의 limit 개만 담아 제일 무거운 텍스처가 잘렸다 — 큰 순서로 담는다.
    sizes = [row["kb"] for row in out["result"]["flagged"]]
    assert out["result"]["sorted_by"] == "file_size_desc" and sizes == sorted(sizes, reverse=True)
    assert out["left_in_project"] == []
    assert sorted(p.name for p in (project / "Assets").iterdir()) == before, "프로젝트에 흔적이 남으면 안 된다"


def test_the_gateway_hands_the_job_to_unity_tools(tmp_path: Path) -> None:
    """★ 첫 벤치: 코드 모드 작업 폴더를 줬는데 「project 를 줘라」로 두 번 헛걸었다 — 게이트웨이가 잡 번호를 안 넘겼다.
    함수를 직접 부르는 시험은 이걸 못 잡는다. **게이트웨이를 거쳐** 부른다."""
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.tool_gateway import ToolGateway

    project = _project(tmp_path)
    tools = _tools(tmp_path, _Local({"job-1": project}))
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    tools.register(gateway)
    out = gateway.execute("unity_project_info", {}, job_id="job-1")
    assert out.ok, out.error
    assert out.result["editor_version"] == "6000.6.3f1"


def test_values_sent_outside_params_and_a_renamed_project_are_accepted(tmp_path: Path) -> None:
    """★ 첫 벤치: 모델이 `folder`·`max_size` 를 params 밖에, 프로젝트를 `project_path` 로 보냈다."""
    project = _project(tmp_path)
    tools = _tools(tmp_path, _Local(allowed=tmp_path))
    assert tools._project({"project_path": str(project)}, write=False) == project.resolve()
    recipe = tools.recipes()["texture_audit"]
    flat = {"recipe": "texture_audit", "folder": "Assets/Art", "max_size": "1024", "limit": "5", "project_path": "x"}
    schema = set(recipe["params"])
    assert tools._params(recipe, {k: v for k, v in flat.items() if k in schema}) == {
        "folder": "Assets/Art", "max_size": 1024, "limit": 5,
    }


def test_the_ledger_knows_the_unity_tools() -> None:
    """★ 첫 벤치: 레시피를 10번 돌린 판의 원장에 유니티가 한 줄도 없었다 — 표에 안 넣었다."""
    from alture_jarvis.evidence import MANIFEST, TYPE_BODY_READ, record_for

    assert MANIFEST["unity_run_recipe"].type == TYPE_BODY_READ
    # 프로젝트 정보의 큰 파일 상위 10개는 실제로 잰 값이다 — 목록으로 두면 거기서 옮긴 이름에 헛경고(2026-10-01).
    assert MANIFEST["unity_project_info"].type == TYPE_BODY_READ
    record = record_for(
        "unity_run_recipe",
        {"project": r"E:\UnityProjects\Game", "verified": True, "content_sha256": "ab" * 32},
        ok=True, step=3, job_id="j", arguments={"recipe": "texture_audit"},
    )
    assert record is not None and record.type == TYPE_BODY_READ and record.content_hash == "ab" * 8


def test_the_same_verified_run_is_not_repeated_in_one_job(tmp_path: Path) -> None:
    """★ 첫 벤치: 35B 가 같은 레시피를 같은 값으로 10번 돌렸다. 두 번째부터는 유니티를 안 띄우고 앞 결과를 준다."""
    project = _project(tmp_path)
    tools = _tools(tmp_path, _Local({"job": project, "other-job": project}))
    key = tools.recipes()["texture_audit"]
    params = tools._params(key, {})
    import json as _json

    cache_key = _json.dumps(["job", "texture_audit", params, str(project.resolve()).lower()], sort_keys=True, ensure_ascii=False)
    tools._recent[cache_key] = {"action": "unity_run_recipe", "verified": True, "result": {"ok": True, "textures_checked": 3}}
    again = tools.run_recipe({"__job_id": "job", "recipe": "texture_audit"})
    assert again["reused_previous_run"] is True and again["result"]["textures_checked"] == 3
    assert "다시 돌려도 같은 답" in again["instruction"]
    # 다른 판·다른 값이면 다시 돈다(여기서는 에디터가 없어 거절로 확인한다).
    with pytest.raises(FileNotFoundError):
        tools.run_recipe({"__job_id": "other-job", "recipe": "texture_audit"})
    with pytest.raises(FileNotFoundError):
        tools.run_recipe({"__job_id": "job", "recipe": "texture_audit", "params": {"max_size": 1024}})


def test_a_project_named_instead_of_pathed_is_found(tmp_path: Path) -> None:
    """★ 2026-10-01 테스터 시험: 모델이 `project: "OntelicPlayground"`(이름)를 보냈고, 앱 폴더 기준 상대 경로로 풀려 531초를 헛돌았다."""
    project = _project(tmp_path)
    tools = _tools(tmp_path, _Local(allowed=tmp_path))
    tools.remember_project(project.resolve())
    assert tools._project({"project": "Game"}, write=False) == project.resolve()
    assert tools._project({"project": "game"}, write=False) == project.resolve(), "대소문자는 가리지 않는다"


def test_two_projects_with_the_same_name_are_not_guessed(tmp_path: Path) -> None:
    first = _project(tmp_path / "a")
    second = _project(tmp_path / "b")
    tools = _tools(tmp_path, _Local(allowed=tmp_path))
    tools.remember_project(first.resolve())
    tools.remember_project(second.resolve())
    with pytest.raises(ValueError, match="unity_project_ambiguous"):
        tools._project({"project": "Game"}, write=False)


def test_the_refusal_points_to_the_game_pack_and_lists_what_is_allowed(tmp_path: Path) -> None:
    allowed_project = _project(tmp_path / "ok")
    tools = _tools(tmp_path, _Local(allowed=tmp_path / "ok"))
    tools.remember_project(allowed_project.resolve())
    with pytest.raises(PermissionError) as caught:
        tools._project({"project": str(tmp_path / "elsewhere" / "Game")}, write=False)
    message = str(caught.value)
    assert "설정 › 팩 › 게임 팩" in message
    assert str(allowed_project.resolve()) in message


def test_a_call_without_a_project_uses_the_only_allowed_one(tmp_path: Path) -> None:
    """★ 2026-10-01 테스터 시험 2판: `unity_project_info` 를 `{}` 로 불러 실패하고 사람에게 「어디 있나요?」를 물었다 — 허락된 것은 하나였다."""
    project = _project(tmp_path / "ok")
    tools = _tools(tmp_path, _Local(allowed=tmp_path / "ok"))
    tools.remember_project(project.resolve())
    assert tools._project({}, write=False) == project.resolve()


def test_a_call_without_a_project_does_not_guess_among_many(tmp_path: Path) -> None:
    first = _project(tmp_path / "a")
    second = _project(tmp_path / "b")
    tools = _tools(tmp_path, _Local(allowed=tmp_path))
    tools.remember_project(first.resolve())
    tools.remember_project(second.resolve())
    with pytest.raises(ValueError, match="unity_project_required") as caught:
        tools._project({}, write=False)
    assert str(first.resolve()) in str(caught.value) and str(second.resolve()) in str(caught.value)
