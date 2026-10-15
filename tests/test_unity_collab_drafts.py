"""클로드·코덱스와 같이 쓰기 — 초안 돌려 보기 → 사람 등록 → 온텔릭 혼자 (2026-09-27, 전략안 §50).

집 PC 실측(유니티 6000.6.3f1 · FPS Microgame): 세미콜론 빠진 초안은 「28,153 CS1002」로 돌아왔고, 고친 초안은 메시 75개 중
3,000 삼각형 넘는 2개를 찾았다. 등록 뒤 unity_run_recipe 로 같은 결과. 에셋 이름을 바꾸는 줄이 든 초안은 실행 전에 승인 대기.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.unity_tools import UNITY_EXTERNAL_TOOLS, UnityRecipeError, UnityTools

GOOD = """
namespace Ontelic.Recipes
{
    public static class CountThings
    {
        public static void Run()
        {
            var guids = UnityEditor.AssetDatabase.FindAssets("t:Mesh");
            RecipeIO.Write(new System.Collections.Generic.Dictionary<string, object> { { "ok", true }, { "n", guids.Length } });
        }
    }
}
"""


class _Local:
    _code_workspaces: dict = {}

    def resolve_export_path(self, raw: str) -> Path:
        return Path(raw)

    def resolve_allowed_path(self, raw: str, must_exist: bool = True) -> Path:
        return Path(raw)


def _setup(tmp_path: Path, verified: bool = True) -> tuple[UnityTools, Path, list]:
    project = tmp_path / "Game"
    (project / "ProjectSettings").mkdir(parents=True)
    (project / "Assets").mkdir()
    (project / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n", encoding="utf-8")
    tools = UnityTools(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out"), _Local())
    calls: list = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        return {"action": kwargs["action"], "recipe": kwargs["name"], "verified": verified,
                "result": {"ok": True, "n": 3} if verified else {}, **({} if verified else {"failure": "compile_error",
                "compile_errors": ["x.cs(3,1): error CS1002: ; expected"]})}

    tools._execute = fake_execute  # type: ignore[method-assign]
    return tools, project, calls


def test_reading_code_is_l1_and_changing_code_is_l2_with_the_lines() -> None:
    assert UnityTools.screen_draft(GOOD) == []
    risky = GOOD.replace("var guids", "UnityEditor.AssetDatabase.DeleteAsset(\"Assets/x.png\");\n            var guids")
    found = UnityTools.screen_draft(risky)
    assert found and found[0]["what"] == "에셋 바꾸기·저장" and "DeleteAsset" in found[0]["code"]
    for sneaky in ("System.IO.File.WriteAllText(p, t);", "new System.Net.Http.HttpClient();", "System.Diagnostics.Process.Start(\"cmd\");",
                   "var t = System.Reflection.Assembly.Load(b);", "EditorSceneManager.SaveScene(s);", "importer.SaveAndReimport();"):
        assert UnityTools.screen_draft(sneaky), sneaky
    assert UnityTools.screen_draft("// File.Delete(p) 는 주석이라 괜찮다") == []
    tools = UnityTools(JarvisConfig(), object())
    assert tools._draft_risk({"csharp": GOOD}).name == "L1"
    assert tools._draft_risk({"csharp": risky}).name == "L2"


def test_a_draft_runs_is_kept_and_only_a_person_can_promote_a_verified_one(tmp_path: Path) -> None:
    tools, project, calls = _setup(tmp_path)
    out = tools.try_script({"name": "count_things", "csharp": GOOD, "project": str(project), "author": "Claude"})
    assert out["verified"] and out["draft"] == "count_things" and calls[0]["method"] == "Ontelic.Recipes.CountThings.Run"
    assert "등록" in out["next"]
    assert "count_things" not in tools.recipes(), "초안은 레시피가 아니다"
    [draft] = tools.drafts()
    assert draft["verified"] and draft["author"] == "Claude" and draft["risk"] == "L1"
    assert tools.promote_draft("count_things")["recipe"] == "count_things"
    recipes = tools.recipes()
    assert recipes["count_things"]["_origin"] == "registered" and tools.drafts() == []


def test_a_failed_draft_says_how_to_fix_and_cannot_be_promoted(tmp_path: Path) -> None:
    tools, project, _calls = _setup(tmp_path, verified=False)
    out = tools.try_script({"name": "count_things", "csharp": GOOD, "project": str(project)})
    assert out["failure"] == "compile_error" and "고쳐" in out["next"]
    with pytest.raises(UnityRecipeError, match="draft_not_verified"):
        tools.promote_draft("count_things")
    assert tools.discard_draft("count_things")["ok"] and tools.drafts() == []


@pytest.mark.parametrize(("args", "code"), [
    ({"name": "Bad Name"}, "draft_name"),
    ({"name": "texture_audit"}, "draft_name_taken"),
    ({"name": "fine", "csharp": "class X { void Run() {} }"}, "draft_shape"),
])
def test_bad_drafts_are_refused_before_anything_runs(tmp_path: Path, args: dict, code: str) -> None:
    tools, project, calls = _setup(tmp_path)
    with pytest.raises(UnityRecipeError, match=code):
        tools.try_script({"csharp": GOOD, "project": str(project), **args})
    assert calls == []


def test_a_registered_recipe_cannot_shadow_a_pack_recipe(tmp_path: Path) -> None:
    tools, _project, _calls = _setup(tmp_path)
    tools.user_recipe_dir.mkdir(parents=True)
    (tools.user_recipe_dir / "texture_audit.json").write_text(json.dumps(
        {"name": "texture_audit", "method": "Ontelic.Recipes.Evil.Run", "risk": "L1"}), encoding="utf-8")
    (tools.user_recipe_dir / "texture_audit.cs").write_text("//", encoding="utf-8")
    assert tools.recipes()["texture_audit"]["_origin"] == "pack"


def test_the_draft_door_is_for_outside_ai_only() -> None:
    tools = UnityTools(JarvisConfig(), object())
    assert "unity_try_script" in {tool["function"]["name"] for tool in tools.ollama_tools}
    assert not (UNITY_EXTERNAL_TOOLS & {tool["function"]["name"] for tool in tools.active_ollama_tools})


def test_no_fitting_recipe_hands_off_instead_of_forcing() -> None:
    listing = UnityTools(JarvisConfig(), object()).list_recipes()
    assert {"texture_audit", "missing_references", "unused_assets", "scene_stats"} <= {r["recipe"] for r in listing["recipes"]}
    assert "클로드 코드나 코덱스" in listing["no_fitting_recipe"] and "억지로" in listing["no_fitting_recipe"]


def test_the_mcp_bridge_lists_enabled_pack_doors() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "mcp_server.py").read_text(encoding="utf-8")
    assert "_enabled_pack_tools" in source and 'if str(tool.get("name")) in pack_tools' in source
