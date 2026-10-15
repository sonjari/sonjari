"""게임 팩을 처음 켠 사람의 화면 (2026-10-12).

스토어판으로 게임 팩을 처음 써 본 사람의 화면에서 나왔다(1명). 설정 화면이 보여 준 것은 `missing_references ·
scene_stats · texture_audit · unused_assets` 라는 파일 이름 넷이었고, 무엇을 해 주는지도 뭐라고 말하면 되는지도
없었다. 점검마다 제목 · 사람이 읽는 한 줄 · 그대로 말하면 되는 문장을 싣는다.

그 문장을 화면에 적기 전에 재 보니 넷 중 하나(「안 쓰는 에셋 찾아 줘」)가 유니티 점검 요구로 서지 않았다 — 점검이
규칙보다 뒤에 들어왔다. **화면에 적은 문장은 계획 층이 알아보는 문장이어야 한다** — 아래 시험이 팩의 점검 전부에
대해 지킨다(새 점검을 넣으면서 문장을 빼먹거나 규칙이 못 알아보면 여기서 걸린다).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.plan import extract
from alture_jarvis.unity_tools import UnityTools


class _Local:
    _code_workspaces: dict = {}

    def resolve_export_path(self, raw: str) -> Path:
        return Path(raw)

    def resolve_allowed_path(self, raw: str, must_exist: bool = True) -> Path:
        return Path(raw)


def _actions(prompt: str) -> list[str]:
    return [str(item.target) for item in extract(prompt) if item.kind == "action"]


def test_every_shipped_check_says_what_it_does_and_what_to_say() -> None:
    cards = [card for card in UnityTools(JarvisConfig(), _Local()).recipe_cards() if card["origin"] == "pack"]
    assert {card["name"] for card in cards} >= {"missing_references", "scene_stats", "texture_audit", "unused_assets"}
    for card in cards:
        assert card["title"] and card["title"] != card["name"], card
        assert card["description"], card
        assert card["ask"], f"{card['name']}: 화면에 적을 예시 문장(ask)이 없다"
        assert _actions(card["ask"]) == ["unity_run_recipe"], f"{card['name']}: 적어 둔 문장을 계획 층이 유니티 점검으로 못 알아본다"


def test_the_line_people_read_is_not_the_line_the_model_reads() -> None:
    tools = UnityTools(JarvisConfig(), _Local())
    recipes = tools.recipes()
    for card in tools.recipe_cards():
        if card["origin"] != "pack":
            continue
        assert card["description"] == recipes[card["name"]]["plain"]
        assert card["description"].endswith("습니다."), "사람에게 하는 말투로"
    # 모델이 읽는 목록은 그대로다 — 쉬운 한 줄이 모델의 설명을 덮어쓰지 않는다.
    listing = {row["recipe"]: row for row in tools.list_recipes()["recipes"]}
    assert "Missing Script" in listing["missing_references"]["description"]
    assert "ask" not in listing["missing_references"]


def test_a_registered_recipe_without_an_example_still_shows(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    tools = UnityTools(config, _Local())
    tools.user_recipe_dir.mkdir(parents=True)
    (tools.user_recipe_dir / "big_meshes.json").write_text(json.dumps(
        {"name": "big_meshes", "title": "큰 메시 찾기", "description": "삼각형이 많은 메시를 찾는다.",
         "method": "Sonjari.Recipes.BigMeshes.Run", "risk": "L1"}, ensure_ascii=False), encoding="utf-8")
    (tools.user_recipe_dir / "big_meshes.cs").write_text("//", encoding="utf-8")
    card = next(card for card in tools.recipe_cards() if card["name"] == "big_meshes")
    assert card == {"name": "big_meshes", "title": "큰 메시 찾기", "description": "삼각형이 많은 메시를 찾는다.",
                    "ask": "", "origin": "registered"}


@pytest.mark.parametrize(("prompt", "wanted"), [
    ("유니티 프로젝트에서 안 쓰는 에셋 찾아줘", ["unity_run_recipe"]),
    ("유니티 프로젝트에서 쓰지 않는 에셋 찾아 줘", ["unity_run_recipe"]),
    # 「에셋」 한 낱말로 넓히지 않았다 — 가게에서 찾는 일에 점검을 요구하면 채울 길이 없다.
    ("유니티 에셋 스토어에서 무료 캐릭터 에셋 찾아줘", []),
    ("유니티 에셋 스토어 세일 확인해줘", []),
])
def test_unused_assets_is_a_check_but_the_asset_store_is_not(prompt: str, wanted: list[str]) -> None:
    assert _actions(prompt) == wanted


def test_the_next_step_is_written_for_someone_new() -> None:
    source =(Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "unity_tools.py").read_text(encoding="utf-8")
    start = source.index("def setup_status")
    block = source[start:source.index("\n    def ", start + 10)]
    # 처음 보는 사람이 뜻을 모르는 말은 그 자리에서 풀어 준다 · 우리끼리 쓰는 말은 적지 않는다.
    assert "「LTS」(오래 고쳐 주는 안정판)" in block
    assert "배치 모드" not in block and "레시피 점검" not in block
