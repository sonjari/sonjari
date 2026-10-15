"""할 수 있는 일을 진열한다 (R5).

도구 102개(L0 35 · L1 53 · L2 14)와 사이트 레시피와 자비스가 이름으로 아는 사이트가
전부 코드 안에만 있었다. **쓸 수 있다는 걸 모르면 없는 기능과 같다.**

셋을 한 경로로 주는 이유: 화면이 세 번 왕복할 이유가 없고, 셋은 같은 질문
("자비스는 무엇을 할 수 있나")의 세 면이라 따로 낡으면 안 된다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.site_atlas import SEED, SiteAtlas


def _config(tmp_path) -> JarvisConfig:
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )


def test_capabilities_answer_the_whole_question(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        body = client.get("/v1/capabilities").json()

    assert body["tool_count"] == len(body["tools"])
    assert body["tool_count"] > 50, "도구가 이만큼도 안 나오면 게이트웨이를 잘못 읽고 있다"
    # 등급 합이 전체와 같아야 한다. 여기가 어긋나면 어떤 도구가 **분모에서 빠진** 것이고,
    # 그게 눈금이 조용히 틀리는 자리다(사고 S).
    assert sum(body["by_risk"].values()) == body["tool_count"]
    assert set(body["by_risk"]) <= {"L0", "L1", "L2", "L3", "L4"}
    # 셋이 한 번에 온다.
    assert isinstance(body["recipes"], list)
    assert isinstance(body["sites"], list)


def test_every_tool_carries_what_it_needs_to_be_shown(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        tools = client.get("/v1/capabilities").json()["tools"]

    for tool in tools:
        assert tool["name"], tool
        # 설명이 없으면 목록은 이름 나열일 뿐이고, 그건 "할 수 있는 일"이 아니다.
        assert tool["description"], tool["name"]
        assert tool["risk_level"].startswith("L"), tool["name"]
        assert isinstance(tool["enabled"], bool), tool["name"]


def test_recipes_show_which_actions_cannot_be_undone(tmp_path) -> None:
    """레시피는 사람이 한 번 뚫으면 다음부터 안 막히는, 자율이 저절로 늘어나는 축이다.

    그런데 절차마다 위험 등급이 다르다(사람인 검색은 L0, 블로그 발행은 L2).
    등급이 안 보이면 목록이 "이거 눌러도 되나"를 못 답한다.
    """
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        recipes = client.get("/v1/capabilities").json()["recipes"]

    assert recipes, "recipes/ 에 파일이 있는데 목록이 비었다"
    for recipe in recipes:
        assert recipe["site"] and recipe["hosts"]
        for action in recipe["actions"]:
            assert action["risk"] in {"L0", "L1", "L2"}, action


def test_the_atlas_does_not_pretend_to_know(tmp_path) -> None:
    """애매한 이름은 목록에서 뺀다 — 아는 척한 이름이 그대로 오답의 출발점이 된다."""
    atlas = SiteAtlas(tmp_path / "atlas.json")
    # 한 이름이 **확정된 두 도메인**에 걸리면 `host_for` 는 빈 문자열을 준다("모른다").
    # 확정에는 서로 다른 페이지 두 개가 필요하다(MIN_PAGES) — 한 장은 우연히 섞인
    # 낱말도 통과시키기 때문이다.
    for index in range(2):
        atlas.learn("광양", f"https://gwangyang.example.com/a{index}", "광양 소식")
        atlas.learn("광양", f"https://gwangyang.other.co.kr/b{index}", "광양 안내")

    names = {row["name"] for row in atlas.known()}
    assert "광양" not in names
    # 씨앗은 언제나 있고, 사람이 심은 것과 배운 것이 구별된다.
    assert {row["name"] for row in atlas.known() if row["seeded"]} == set(SEED)


def test_the_atlas_lists_what_it_learned(tmp_path) -> None:
    atlas = SiteAtlas(tmp_path / "atlas.json")
    atlas.learn("골리", "https://www.goli.example/info/?pcode=1", "무선마우스 - 골리")
    atlas.learn("골리", "https://www.goli.example/info/?pcode=2", "키보드 - 골리")

    learned = [row for row in atlas.known() if not row["seeded"]]
    assert learned == [{"name": "골리", "host": "goli.example", "seeded": False}]
