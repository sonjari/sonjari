"""화면 언어 — 백엔드 글을 나가는 순간 바꾼다 (2026-10-02 영어판 2단계, ui_i18n.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alture_jarvis import ui_i18n
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

#: 실제 사전 — 아래 자동 고정물이 시험용 사전으로 바꾸기 전에 잡아 둔다.
REAL_DICT = ui_i18n._DICT_PATH

DICT = {
    "저장했습니다": "Saved",
    "{0}개 남았습니다": "{0} left",
    "ℹ 도구 기록: 손자리가 본 목록 범위는 {0}입니다.": "ℹ Tool record: the list Sonjari saw was {0}.",
    "검색 「{0}」 {1}건": "search “{0}” {1} results",
}


@pytest.fixture(autouse=True)
def _dictionary(tmp_path, monkeypatch):
    path = tmp_path / "ui_i18n_en.json"
    path.write_text(json.dumps(DICT, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ui_i18n, "_DICT_PATH", path)
    ui_i18n.reload()
    ui_i18n.configure(tmp_path / "lang_state.json")
    yield
    ui_i18n.configure(tmp_path / "lang_state_reset.json")  # 다음 시험은 한국어로
    ui_i18n.reload()


def test_korean_screen_changes_nothing() -> None:
    assert ui_i18n.lang() == "ko"
    payload = {"message": "저장했습니다", "items": ["3개 남았습니다"]}
    assert ui_i18n.translate_payload(payload) == payload


def test_english_screen_translates_fixed_templated_and_multiline_text(tmp_path: Path) -> None:
    ui_i18n.set_lang("en")
    assert ui_i18n.translate_text("저장했습니다") == "Saved"
    assert ui_i18n.translate_text("12개 남았습니다") == "12 left"
    # 모델의 영어 답 + 손자리의 한국어 안내 줄 — 줄마다 바꾸고, 안내 속 자리(검색 범위)도 사전으로 바꾼다.
    answer = "Here are the posts.\n\nℹ 도구 기록: 손자리가 본 목록 범위는 검색 「AI」 9건입니다."
    assert ui_i18n.translate_text(answer) == "Here are the posts.\n\nℹ Tool record: the list Sonjari saw was search “AI” 9 results."
    # 사전에 없는 문장은 그대로 — 빠진 번역이 화면을 깨지 않는다.
    assert ui_i18n.translate_text("사전에 없는 문장") == "사전에 없는 문장"
    # 사용자가 쓴 글은 사전 문장과 같아도 바꾸지 않는다.
    assert ui_i18n.translate_payload({"prompt": "저장했습니다", "status_text": "저장했습니다"}) == {
        "prompt": "저장했습니다", "status_text": "Saved"}


def test_the_choice_survives_a_restart(tmp_path: Path) -> None:
    ui_i18n.set_lang("en")
    ui_i18n.configure(tmp_path / "lang_state.json")
    assert ui_i18n.lang() == "en"
    with pytest.raises(ValueError):
        ui_i18n.set_lang("fr")


def test_api_responses_are_translated_on_the_way_out(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)

    @app.get("/probe")
    def probe() -> dict[str, str]:
        return {"message": "저장했습니다", "prompt": "저장했습니다"}

    headers = {"X-JARVIS-TOKEN": "test-token"}
    with TestClient(app) as client:
        assert client.get("/probe").json()["message"] == "저장했습니다"
        assert client.post("/v1/ui-language", json={"lang": "en"}, headers=headers).json() == {"lang": "en"}
        assert client.get("/v1/ui-language", headers=headers).json() == {"lang": "en"}
        assert client.get("/probe").json() == {"message": "Saved", "prompt": "저장했습니다"}
        assert client.post("/v1/ui-language", json={"lang": "xx"}, headers=headers).status_code == 400
        client.post("/v1/ui-language", json={"lang": "ko"}, headers=headers)
        assert client.get("/probe").json()["message"] == "저장했습니다"


def test_the_model_thinks_and_answers_in_the_screen_language() -> None:
    """프롬프트에 「생각도 한국어로 한다」가 박혀 있어 영어 화면에서도 한국어로 생각·답했다."""
    from alture_jarvis import agent

    assert agent._THINK_IN_KOREAN in agent._VOICE_AND_MANNER, "바꿀 문장이 프롬프트에서 사라지면 영어판이 조용히 한국어로 돌아간다"
    assert agent._voice_and_manner() == agent._VOICE_AND_MANNER
    ui_i18n.set_lang("en")
    english = agent._voice_and_manner()
    assert agent._THINK_IN_KOREAN not in english and "Think and answer in English" in english


def test_what_leaked_in_the_first_english_run_is_covered(monkeypatch, tmp_path: Path) -> None:
    """영어 실제 판(107f2da1)에서 샌 셋 — 빈칸 둘이 띄어쓰기로만 나뉜 틀 · 이어 붙인 문장 · 사용자 칸 앞의 우리 말머리."""
    monkeypatch.setattr(ui_i18n, "_DICT_PATH", tmp_path / "missing.json")
    ui_i18n.reload()
    ui_i18n.set_lang("en")
    assert ui_i18n.translate_text("웹 자료 3개 이상 직접 열어 읽기") == "Open and read at least 3 web sources directly"
    assert ui_i18n.translate_text("3개 읽음 · 답에 3개") == "3 read · 3 in the answer"
    assert ui_i18n.translate_payload({"display_prompt": "바깥 AI 가 맡긴 일 · Open HN"}) == {
        "display_prompt": "Handed off by another AI · Open HN"}
    assert ui_i18n.translate_payload({"display_prompt": "내가 쓴 글 · 그대로"}) == {"display_prompt": "내가 쓴 글 · 그대로"}


def test_an_english_request_gets_an_english_answer_even_on_a_korean_screen() -> None:
    """★ 10-03 영어 벤치: 한국어 판이 쌓인 대화방에서 영어로 시킨 arXiv 판이 답·파일 제목까지 한국어로 썼다."""
    from alture_jarvis import agent

    assert ui_i18n.lang() == "ko"
    english = agent._voice_and_manner("Open arxiv.org/list/cs.CL/new and save a markdown table of the first 3 papers.")
    assert agent._THINK_IN_KOREAN not in english and "This request is in English" in english
    assert agent._voice_and_manner("아카이브에서 논문 3편 찾아 표로 정리해줘") == agent._VOICE_AND_MANNER


def test_a_sentence_joined_with_plus_is_in_the_real_dictionary(monkeypatch) -> None:
    """★ 2026-10-03: 마법사 추천 칸 첫 줄이 영어 화면에서 한국어로 남았다. 「…약 {n}GB」 + 「 (화면 출력이…)」 로
    이어 붙인 문장이라 추출기가 조각만 뽑았다. 이은 전체가 실제 사전에 있어야 한다."""
    monkeypatch.setattr(ui_i18n, "_DICT_PATH", REAL_DICT)
    ui_i18n.reload()
    ui_i18n.set_lang("en")
    line = "NVIDIA GeForce RTX 4060 · 쓸 수 있는 메모리 약 7GB (화면 출력이 같은 카드라 1GB 를 비워 둡니다)"
    out = ui_i18n.translate_text(line)
    assert out.startswith("NVIDIA GeForce RTX 4060 · ") and "7GB" in out
    assert not any("가" <= ch <= "힣" for ch in out), out
