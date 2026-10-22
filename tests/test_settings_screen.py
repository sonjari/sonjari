"""설정 화면 값이 사는 자리 (W3) — 화면에서 바꾼 값이 다음 기동에도 이긴다.

사고 Q 와 「.env 가 항상 졌다」: 같은 값이 dataclass 기본값 · 환경변수 로더 · `task_entry` 의 `setdefault`
세 자리에 살아서, 한 자리를 고치면 다른 자리가 조용히 이겼다. 여기서는 세 자리를 **전부 채운 채로**
화면 값이 이기는지 본다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig, load_env_file
from alture_jarvis.settings import BY_KEY, SETTINGS, SettingsService, validate, SettingsError

REPO = Path(__file__).resolve().parents[1]


def _write_settings(data: Path, values: dict) -> None:
    data.mkdir(parents=True, exist_ok=True)
    (data / "settings.json").write_text(json.dumps({"version": 1, "values": values}), encoding="utf-8")


def test_the_table_stays_small_and_has_no_secret_door() -> None:
    # 36 = 권한 모드 「권한 무시」의 손잡이(`approval_bypass_enabled`, 2026-09-23). 모드가 설정값을 정하는
    #   구조라(`permissions.MODES`) 표에 있어야 저장·적용된다 — 셸 자동 실행·되돌릴 수 있는 일 자동 승인과 같은 자리.
    # 38 = 서기(2026-10-21) 켜기 · 읽을 폴더. 대화 기록은 사람 것이라 사람이 화면에서 직접 켜야 한다 — MCP 로 켜는 문은 두지 않는다.
    assert 20 <= len(SETTINGS) <= 38
    for item in SETTINGS:
        assert not any(mark in item.key for mark in ("token", "secret", "password", "api_key"))
    with pytest.raises(SettingsError):
        validate("control_token", "x")
    with pytest.raises(SettingsError):
        validate("ollama_base_url", "http://evil")  # 표 밖


def test_screen_value_beats_env_dotenv_and_task_entry_setdefault(tmp_path: Path) -> None:
    """세 자리를 다 채워 두고 새 파이썬 프로세스로 띄운다 — 이 프로세스의 캐시가 섞이지 않게."""
    root = tmp_path / "rt"
    data = root / "data"
    _write_settings(data, {"takeover_enabled": False, "user_label": "화면값", "ollama_max_tool_steps": 9,
                           "model_chat": "screen-model:1"})
    (root / ".env").write_text("JARVIS_TAKEOVER_ENABLED=true\nJARVIS_USER_LABEL=닷엔브값\n", encoding="utf-8")
    script = (
        "import os, json\n"
        "os.environ.setdefault('JARVIS_OLLAMA_MAX_TOOL_STEPS', '30')  # task_entry 가 하는 모양\n"
        "os.environ.setdefault('JARVIS_OLLAMA_CHAT_MODEL', 'env-model:1')\n"
        "from alture_jarvis.config import JarvisConfig, load_env_file\n"
        "load_env_file()\n"
        "c = JarvisConfig.from_env()\n"
        "print(json.dumps({'takeover': c.takeover_enabled, 'label': c.user_label,"
        " 'steps': c.ollama_max_tool_steps, 'chat': c.model_for('chat'), 'applied': list(c.settings_applied)}))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update({"JARVIS_RUNTIME_ROOT": str(root), "PYTHONPATH": str(REPO / "src"), "JARVIS_USER_LABEL": "환경값",
                "USERPROFILE": str(tmp_path / "home"), "HOME": str(tmp_path / "home"), "PYTHONIOENCODING": "utf-8"})
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8", env=env,
                          timeout=120)
    assert done.returncode == 0, done.stderr[-800:]
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert (got["takeover"], got["label"], got["steps"], got["chat"]) == (False, "화면값", 9, "screen-model:1")
    assert set(got["applied"]) == {"takeover_enabled", "user_label", "ollama_max_tool_steps", "model_chat"}


def test_dataclass_without_settings_file_is_untouched(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    assert config.settings_applied == ()
    assert config.takeover_enabled is True


def test_broken_or_foreign_values_are_ignored_not_fatal(tmp_path: Path) -> None:
    data = tmp_path / "data"
    _write_settings(data, {"ollama_max_tool_steps": 9999, "control_token": "leak", "takeover_enabled": "yes"})
    config = JarvisConfig(runtime_root=tmp_path, data_dir=data)
    assert config.settings_applied == ()
    assert config.ollama_max_tool_steps == 12


def test_patch_applies_live_values_and_flags_restart(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    changed: list[list[str]] = []
    service = SettingsService(config, on_live_change=changed.append)

    result = service.patch({"takeover_enabled": False, "voice_enabled": False, "skills_domains": ["office", "research"]})

    assert result["ok"] is True
    assert config.takeover_enabled is False and config.skills_domains == ("office", "research")
    assert config.voice_enabled is True  # 다시 시작해야 적용 — 이 프로세스엔 아직 안 먹었다
    assert result["restart_required"] == ["voice_enabled"]
    rows = {row["key"]: row for row in result["settings"]}
    assert rows["voice_enabled"]["restart_required"] is True and rows["voice_enabled"]["value"] is False
    assert rows["takeover_enabled"]["source"] == "user"
    assert changed == [["takeover_enabled", "skills_domains"]]
    # 다음 기동: 파일에서 다시 읽으면 둘 다 이긴다.
    again = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    assert again.voice_enabled is False and again.takeover_enabled is False


def test_patch_rejects_the_whole_batch_on_one_bad_value(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    service = SettingsService(config)
    result = service.patch({"user_label": "좋음", "approval_ttl_sec": 5})
    assert result == {"ok": False, "error": "too_small:approval_ttl_sec"}
    assert not (tmp_path / "data" / "settings.json").exists()


def test_reset_removes_user_values(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    service = SettingsService(config)
    service.patch({"user_label": "화면값", "fact_learning_enabled": False})
    service.reset(["user_label"])
    values = json.loads((tmp_path / "data" / "settings.json").read_text(encoding="utf-8"))["values"]
    assert values == {"fact_learning_enabled": False}


def test_lists_round_trip_to_the_semicolon_string_the_computer_tools_parse(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    service = SettingsService(config)
    service.patch({"local_file_allowed_roots": ["C:/a", "D:/b"]})
    again = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    assert again.local_file_allowed_roots == "C:/a;D:/b"


def test_backup_toggle_maps_to_the_backup_folder(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("JARVIS_BACKUP_DIR", raising=False)
    data = tmp_path / "data"
    _write_settings(data, {"memory_backup_enabled": True})
    assert JarvisConfig(runtime_root=tmp_path, data_dir=data).memory_backup_dir == tmp_path / "home" / "Sonjari" / "backup"
    _write_settings(data, {"memory_backup_enabled": False})
    assert JarvisConfig(runtime_root=tmp_path, data_dir=data, memory_backup_dir=tmp_path / "x").memory_backup_dir is None


def test_every_setting_targets_a_real_config_attribute(tmp_path: Path) -> None:
    """표에 지어낸 속성 이름이 있으면 조용히 새 속성이 생긴다 — 설정한 척만 하는 칸."""
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    for item in SETTINGS:
        head = item.target.split(".", 1)[0]
        assert hasattr(config, head), item.key
    assert "model_chat" in BY_KEY


def test_diagnostics_bundle_carries_no_prompt_or_token(tmp_path: Path) -> None:
    from alture_jarvis.diagnostics import export_bundle

    class _Store:
        def list_jobs(self, limit=30):
            return [{"kind": "chat", "status": "failed", "error": "TimeoutError: 비밀 내용 sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                     "payload": {"prompt": "개인적인 질문"}, "created_at": 1, "updated_at": 2}]

    class _Backup:
        def status(self):
            return {"enabled": True, "keep": 3, "memory_empty": False, "generations": [{}]}

    class _Runtime:
        config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
        store = _Store()
        backup = _Backup()
        settings = None

        def health(self):
            return {"ok": True, "token_hint": config.control_token if False else "x"}

    made = export_bundle(_Runtime())
    text = Path(made["path"]).read_text(encoding="utf-8")
    assert "개인적인 질문" not in text and "비밀 내용" not in text and "sk-ant" not in text
    assert json.loads(text)["jobs"][0]["error"] == "TimeoutError"


def test_diagnostics_bundle_carries_what_the_laptop_diagnosis_needed(tmp_path: Path) -> None:
    """2026-09-18: 노트북 원인을 찾느라 PowerShell 명령을 여덟 번 주고받았다. 그 내용이 파일 하나에 들어와야 한다 —
    엔진 상태·점검 결과·자리·Ollama 로그 끝. 그리고 로그에 섞인 비밀과 사용자 폴더는 여전히 가려져야 한다."""
    from alture_jarvis.diagnostics import export_bundle

    engine = tmp_path / "engine" / "ollama"
    engine.mkdir(parents=True)
    (engine / "serve.log").write_text(
        "\n".join([f"line {i}" for i in range(200)]
                  + ["error starting llama-server: llama-server binary not found",
                     f"token sk-ant-api03-{'y' * 40} at {Path.home() / 'secret'}"]),
        encoding="utf-8")

    class _Installer:
        install_root = engine
        legacy_roots = ()

        def status(self):
            return {"running": True, "runner_missing": True, "install_root": str(engine)}

    class _Care:
        last_boot = {"down": ["engine"]}

        def boot_check(self, include_model=True):
            return {"down": ["engine"], "healable": ["repair_ollama"]}

    class _Runtime:
        config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
        store = None
        backup = None
        settings = None
        ollama_installer = _Installer()
        self_care = _Care()

        def health(self):
            return {"ok": True}

    made = export_bundle(_Runtime())
    text = Path(made["path"]).read_text(encoding="utf-8")
    bundle = json.loads(text)
    assert bundle["ollama"]["runner_missing"] is True
    assert bundle["self_check_now"]["healable"] == ["repair_ollama"]
    assert "ollama_install_dir" in bundle["places"]
    tail = next(iter(bundle["logs"].values()))
    assert any("llama-server binary not found" in line for line in tail), "원인 문장이 들어 있어야 한다"
    assert len(tail) <= 60 and "line 0" not in tail, "끝만 담는다"
    assert "sk-ant" not in text and str(Path.home()) not in text
