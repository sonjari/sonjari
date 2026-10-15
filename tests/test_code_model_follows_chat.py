"""대화 모델을 바꾸면 **대화를 따라가던** 코드 모델도 같이 바뀐다 (2026-09-30 이 PC 실측).

대화·코드 둘 다 3.6 이던 PC 에서 대화만 3.8 로 바꾸자 코드가 3.6 에 남았다. Ollama 는 모델을 하나만 올려
(OLLAMA_MAX_LOADED_MODELS=1) 한 과제 안에서 대화 걸음과 코드 걸음이 서로를 밀어냈고(적재 70초·40초),
3.6 은 잰 적 없는 코드 창 102400 으로 올라가 GPU 94% — CPU 로 샜다.

양방향: 코드를 **따로 골라 둔** 사람의 선택은 그대로 둔다(`adopt_model_selection` 의 원래 약속).

★ 2026-10-10: 「따라간다」를 **사본으로 적지 않는다.** 예전에는 대화 모델 이름을 `settings.json` 의 `model_code` 에 베껴
  적었다. 대화 모델은 `model_selection.json` 에 있으니 두 파일이 어긋날 수 있다 — 이 PC 에서 작은 양자화로 재 본 뒤 대화 쪽만
  되돌리자 사본이 작은 양자화에 남았고, 하루 종일 두 모델이 서로를 밀어냈다(사용자의 다음 말이 17~27초 적재를 기다림).
  이제 선택 파일의 한 줄(`code_follows_chat`)이 사실이고, 코드 역할은 켤 때마다 대화 모델에 맞춘다.
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SELECTION_NAME, SetupService, read_selection
from alture_jarvis.settings import SettingsService, read_user_values

from test_a_spilling_context_steps_down import Rig

OLD = "qwen3.8:27b-mtp-q4_K_M"
NEW = "qwen3.6:35b-a3b"  # the rig only has this one installed
STALE = "stale-code:9b"
OWN = "own-code:latest"


def _service(tmp_path: Path, roles: dict[str, str]) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.model_roles = dict(roles)
    rig = Rig({32768: 1.0})
    return SetupService(config, post=rig.post, get=rig.get, stream=rig.stream)


def _restart(tmp_path: Path, roles: dict[str, str]) -> JarvisConfig:
    """앱을 다시 켠 것 — `roles` 는 환경변수·.env 가 말하는 값이다(선택·화면 설정이 그 위에 얹힌다)."""
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out", model_roles=dict(roles))


def test_a_code_role_that_followed_chat_moves_with_it(tmp_path: Path) -> None:
    setup = _service(tmp_path, {"chat": OLD, "code": OLD})

    assert setup.apply_tag(NEW, 32768)["ok"]

    assert setup.config.model_for("code") == NEW
    assert read_selection(setup.config.data_dir)["code_follows_chat"] is True
    assert "model_code" not in read_user_values(setup.config.data_dir), "사본을 적지 않는다 — 사본은 원본과 어긋난다"


def test_a_code_model_chosen_on_purpose_is_kept(tmp_path: Path) -> None:
    setup = _service(tmp_path, {"chat": OLD, "code": OWN})

    assert setup.apply_tag(NEW, 32768)["ok"]

    assert setup.config.model_for("code") == OWN
    assert "model_code" not in read_user_values(setup.config.data_dir)
    assert read_selection(setup.config.data_dir)["code_follows_chat"] is False
    assert _restart(tmp_path, {"chat": OLD, "code": OWN}).model_for("code") == OWN, "따로 고른 것은 다시 켜도 그대로다"


def test_following_survives_a_restart_and_beats_a_stale_environment_value(tmp_path: Path) -> None:
    """사본이 없으니 다시 켰을 때 환경변수에 남은 옛 코드 모델이 이기면 안 된다(이 PC 의 사용자 환경변수에 실제로 남아 있다)."""
    setup = _service(tmp_path, {"chat": OLD, "code": OLD})
    assert setup.apply_tag(NEW, 32768)["ok"]

    again = _restart(tmp_path, {"chat": OLD, "code": STALE})

    assert again.model_for("chat") == NEW
    assert again.model_for("code") == NEW


def test_putting_back_only_the_chat_choice_brings_the_code_role_with_it(tmp_path: Path) -> None:
    """이번 사고 그대로: 다른 모델로 바꿔 재 본 뒤 **선택 파일만** 예전 것으로 되돌렸다. 코드 역할이 재 본 모델에 남으면 안 된다."""
    setup = _service(tmp_path, {"chat": OLD, "code": OLD})
    before = json.dumps({"chat_model": OLD, "num_ctx": 32768, "code_follows_chat": True})
    assert setup.apply_tag(NEW, 32768)["ok"]
    assert setup.config.model_for("code") == NEW

    (setup.config.data_dir / SELECTION_NAME).write_text(before, encoding="utf-8")
    again = _restart(tmp_path, {"chat": OLD, "code": OLD})

    assert again.model_for("chat") == OLD
    assert again.model_for("code") == OLD, "대화만 되돌아오고 코드가 남으면 두 모델이 서로를 밀어낸다"


def test_a_code_model_picked_on_the_settings_screen_wins_over_following(tmp_path: Path) -> None:
    setup = _service(tmp_path, {"chat": OLD, "code": OLD})
    assert setup.apply_tag(NEW, 32768)["ok"]
    assert SettingsService(setup.config).patch({"model_code": OWN})["ok"]

    assert setup.config.model_for("code") == OWN
    assert _restart(tmp_path, {"chat": OLD, "code": OLD}).model_for("code") == OWN


def test_changing_only_the_chat_model_on_the_settings_screen_takes_the_code_role_along(tmp_path: Path) -> None:
    setup = _service(tmp_path, {"chat": OLD, "code": OLD})
    assert setup.apply_tag(NEW, 32768)["ok"]

    assert SettingsService(setup.config).patch({"model_chat": "typed-chat:latest"})["ok"]

    assert setup.config.model_for("code") == "typed-chat:latest"
    assert _restart(tmp_path, {"chat": OLD, "code": STALE}).model_for("code") == "typed-chat:latest"


def test_a_code_model_picked_this_session_is_not_dragged_along(tmp_path: Path) -> None:
    """켤 때 읽은 목록만 보면, 방금 화면에서 고른 코드 모델이 「따로 고른 것」으로 안 보인다."""
    setup = _service(tmp_path, {"chat": OLD, "code": OLD})
    assert setup.apply_tag(NEW, 32768)["ok"]
    service = SettingsService(setup.config)
    assert service.patch({"model_code": OWN})["ok"]

    assert service.patch({"model_chat": "typed-chat:latest"})["ok"]
    assert setup.config.model_for("code") == OWN

    assert service.reset(["model_code"])["ok"]
    assert service.patch({"model_chat": "typed-again:latest"})["ok"]
    assert setup.config.model_for("code") == "typed-again:latest", "따로 고른 것을 지우면 다시 따라간다"


def test_an_old_selection_file_without_the_line_is_left_alone(tmp_path: Path) -> None:
    """옛 파일(그 줄이 없다)과 관리 설치(환경변수로 코드 모델을 정함)는 손대지 않는다 — 모르는 것을 따라간다고 치지 않는다."""
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / SELECTION_NAME).write_text(json.dumps({"chat_model": NEW, "num_ctx": 32768}), encoding="utf-8")

    again = _restart(tmp_path, {"chat": OLD, "code": OWN})

    assert again.model_for("chat") == NEW
    assert again.model_for("code") == OWN
