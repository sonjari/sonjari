"""모델 자리 — 이 맥 / 집 PC (설계_짝짓기_모델자리_2026-11-03 순서 1 · §5 양방향 시험).

대표(11-03 맥미니): 「맥판에서는 설정도 못 하고 모델도 못 바꾼다」. 지키는 것:
- 위성 설치본도 「이 맥」으로 바꾸면 이 기기 모델을 받고 고른다(예전엔 역할만 보고 통째로 막았다).
- 자리를 바꾸면 다시 켜지 않고 살아 있는 설정이 바뀐다(다음 호출부터).
- 집 PC 에서 모델을 고르면 이 기기가 쓸 모델만 바뀌고, 이 기기의 선택 파일 · 집 PC 의 선택은 건드리지 않는다.
- 집 PC 를 모르면 「집 PC」로 못 바꾼다.
"""

from __future__ import annotations

import json

from alture_jarvis import model_place
from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SetupService

HOME = "http://192.0.2.10:11434"
BRAIN_MODEL = "hf.co/ukisai/Swift:IQ3_S"


def satellite(tmp_path, **over) -> JarvisConfig:
    config = JarvisConfig(data_dir=tmp_path, jarvis_role="satellite", ollama_base_url=HOME,
                          model_roles={"chat": BRAIN_MODEL, "code": BRAIN_MODEL, "vision": BRAIN_MODEL},
                          ollama_num_ctx=131072, **over)
    model_place.apply(config)
    return config


def write_selection(tmp_path, tag="hf.co/ornith-ai/Ornith-1.5-9B-GGUF:Q4_K_M", ctx=65536):
    (tmp_path / "model_selection.json").write_text(json.dumps({"chat_model": tag, "num_ctx": ctx}), encoding="utf-8")


def test_installed_satellite_starts_on_home_pc_like_before(tmp_path):
    config = satellite(tmp_path)
    assert model_place.current(config) == "home_pc"
    assert config.ollama_base_url == HOME and config.model_for("chat") == BRAIN_MODEL and config.ollama_num_ctx == 131072


def test_this_mac_uses_this_machines_choice_without_restart(tmp_path):
    config = satellite(tmp_path)
    write_selection(tmp_path)
    done = model_place.set_place(config, "this_pc")
    assert done["ok"] and done["place"] == "this_pc"
    # 같은 설정 객체가 바로 바뀐다 — 다시 켜지 않는다
    assert config.ollama_base_url == model_place.LOCAL_OLLAMA
    assert config.model_for("chat").startswith("hf.co/ornith-ai") and config.ollama_num_ctx == 65536
    # 되돌리면 집 PC 주소 · 모델 · 창이 그대로 돌아온다
    model_place.set_place(config, "home_pc")
    assert (config.ollama_base_url, config.model_for("chat"), config.ollama_num_ctx) == (HOME, BRAIN_MODEL, 131072)


def test_this_mac_without_a_choice_does_not_keep_the_home_model_name(tmp_path):
    """이 맥에 없는 집 PC 모델 이름으로 이 맥 Ollama 를 부르지 않는다 — 비워 두고 화면이 「고르세요」를 말한다."""
    config = satellite(tmp_path)
    model_place.set_place(config, "this_pc")
    assert config.model_for("chat") == "" and config.ollama_base_url == model_place.LOCAL_OLLAMA


def test_choice_survives_restart(tmp_path):
    config = satellite(tmp_path)
    write_selection(tmp_path)
    model_place.set_place(config, "this_pc")
    again = satellite(tmp_path)
    assert model_place.current(again) == "this_pc" and again.ollama_base_url == model_place.LOCAL_OLLAMA


def test_home_model_pick_changes_only_this_device(tmp_path):
    config = satellite(tmp_path)
    write_selection(tmp_path)
    before = (tmp_path / "model_selection.json").read_text(encoding="utf-8")
    done = model_place.set_home_model(config, "qwen3.6:35b-a3b", 65536)
    assert done["ok"] and done["home_model_chosen_here"]
    # 대화와 대화를 따라가던 역할이 같이 바뀐다
    assert config.model_for("chat") == config.model_for("code") == "qwen3.6:35b-a3b" and config.ollama_num_ctx == 65536
    # 이 기기의 선택 파일은 그대로(집 PC 고르기는 그 파일을 쓰지 않는다)
    assert (tmp_path / "model_selection.json").read_text(encoding="utf-8") == before
    # 이 맥으로 갔다 와도 집 PC 에서 고른 것이 남는다
    model_place.set_place(config, "this_pc")
    model_place.set_place(config, "home_pc")
    assert config.model_for("chat") == "qwen3.6:35b-a3b"


def test_home_model_pick_while_on_this_mac_waits_for_home(tmp_path):
    config = satellite(tmp_path)
    write_selection(tmp_path)
    model_place.set_place(config, "this_pc")
    model_place.set_home_model(config, "qwen3.6:35b-a3b")
    assert config.ollama_base_url == model_place.LOCAL_OLLAMA and "ornith" in config.model_for("chat").lower()


def test_without_a_home_pc_there_is_nothing_to_switch_to(tmp_path):
    config = JarvisConfig(data_dir=tmp_path, model_roles={"chat": "qwen3.5:9b"})
    assert model_place.current(config) == "this_pc"
    assert model_place.set_place(config, "home_pc") == {"ok": False, "error": "no_home_pc"}
    assert model_place.set_home_model(config, "x") == {"ok": False, "error": "no_home_pc"}
    assert model_place.set_place(config, "cloud") == {"ok": False, "error": "unknown_place"}
    assert model_place.view(config)["home_known"] is False


def test_model_setup_blocks_local_models_only_while_on_home_pc(tmp_path):
    config = satellite(tmp_path)
    service = SetupService(config, post=lambda *a, **k: {}, get=lambda *a, **k: {})
    assert service.is_satellite is True
    assert service.apply("qwen3.5-9b", 65536)["error"] == "satellite_uses_brain_models"
    model_place.set_place(config, "this_pc")
    assert service.is_satellite is False
    assert service.recommendation().get("mode") != "satellite"


def test_extra_live_holders_follow(tmp_path):
    class Installer:
        base_url = HOME

    config = satellite(tmp_path)
    holder = Installer()
    model_place.set_place(config, "this_pc", extra_live=[holder])
    assert holder.base_url == model_place.LOCAL_OLLAMA


def test_empty_home_pick_follows_the_home_pc_again(tmp_path):
    config = satellite(tmp_path)
    model_place.set_home_model(config, "qwen3.6:35b-a3b", 65536)
    done = model_place.set_home_model(config, "")
    assert done["ok"] and not done["home_model_chosen_here"]
    assert config.model_for("chat") == BRAIN_MODEL and config.ollama_num_ctx == 131072


def test_home_list_keeps_only_chat_models_and_marks_the_home_default():
    """11-04 대표 맥미니 스크린샷: 집 PC 목록에 임베딩 · 그림 읽는 부품(mmproj) · 시험 별칭이 섞였고, 집 PC 기본 모델이 안 보였다."""
    from alture_jarvis import model_place

    swift = "hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF:Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf"
    tags = [
        {"name": "bge-m3:latest", "size": 1.2e9, "details": {"family": "bert", "quantization_level": "F16"}},
        {"name": "hf.co/ukisai/Swift-1.5-Qwen3.8-27B-GGUF:mmproj-Swift-1.5-Qwen3.8-27B-F16.gguf", "size": 1.9e9,
         "details": {"family": "qwen35", "quantization_level": "F16"}},
        {"name": "sonjari-probe-swift-vision:test", "size": 13.1e9, "details": {"family": "qwen35"}},
        {"name": "nomic-embed-text:latest", "size": 0.3e9, "details": {"family": "nomic-bert"}},
        {"name": "qwen3.5:9b", "size": 6.6e9, "details": {"family": "qwen35", "quantization_level": "Q4_K_M"}},
        {"name": swift, "size": 13.0e9, "details": {"family": "qwen35", "quantization_level": "BF16"}},
    ]
    rows = model_place.home_rows(tags, swift)
    assert [r["tag"] for r in rows] == [swift, "qwen3.5:9b"]  # 기본이 맨 위 · 대화 모델만
    assert rows[0]["home_default"] is True and rows[1]["home_default"] is False
    # 반대 방향: 대화 모델은 이름이 낯설어도 빼지 않는다
    assert model_place.is_chat_model("hf.co/empero-ai/Qwen3.8-35B-A3B-Distill-GGUF:IQ4_XS", "qwen35moe")
    assert model_place.is_chat_model("sonjari-text-qwen3.8-27b-swift-iq3xxs:latest", "qwen35")
