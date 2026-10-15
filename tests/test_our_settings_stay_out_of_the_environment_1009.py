"""우리 설정은 프로세스 환경에 **두지 않는다** — 맡기기 전에 합격 시험으로 썼고(2026-10-09), 손자리가 통과시킨 뒤 여기로 옮겼다.

왜: 손자리가 프로그램을 켜는 자리는 33곳이고, 그 가운데 우리 설정(`JARVIS_*`)을 빼고 넘기는 자리는 3곳뿐이었다.
나머지 30곳은 열쇠와 데이터 위치를 그대로 물려준다. 켜는 자리마다 빼는 방식은 새 자리가 생길 때마다 또 잊는다.
레딧에서 네 사람 가운데 셋이 같은 말을 했다: 「빼지 말고, 애초에 거기 넣지 마라」.

설계(정해 둔 것):
  · `config.py` 에 안쪽 보관소 `_PRIVATE: dict[str, str]` 를 둔다. 프로세스 환경(os.environ)이 아니다 — 자식에게 안 넘어간다.
  · 읽기: `config.setting(name, default="")`. 환경에 값이 있으면(비어 있지 않으면) 그것, 없으면 보관소, 없으면 default.
    `config._env` 도 같은 규칙으로 읽는다(JarvisConfig.from_env 가 그것을 쓴다).
  · `load_env_file(path)` 는 `.env` 의 값을 **보관소에** 싣는다. 환경이나 보관소에 이미 있는 이름은 덮지 않는다. 돌려주는 것은 지금처럼 실은 것들.
  · `absorb_environment()` — 환경에 있는 `JARVIS_*` 를 보관소로 옮기고 환경에서 지운다(보관소의 같은 이름을 덮는다). 옮긴 이름 목록을 돌려준다.
  · `keep_private(name, value, *, override=False)` — 값 하나를 보관소에. override 가 아니면 환경·보관소에 이미 있는 이름은 건드리지 않는다.
  · `environment_for_our_own_child()` — 우리가 **우리 자신의 부속**(음성 서버 등)을 켤 때만 쓰는 환경: os.environ 사본 + 보관소.
  · 시작하는 쪽(`scripts/task_entry.py` · `__main__.py`)은 환경에 우리 것을 쓰지 않고, 물려받은 것은 absorb 한다.
  · `config.py` 밖에서 환경의 `JARVIS_*` 를 직접 읽지 않는다(`mcp_server.py` 는 따로 도는 프로세스라 예외).

"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import alture_jarvis
from alture_jarvis import config
from alture_jarvis.config import JarvisConfig

_PACKAGE = Path(alture_jarvis.__file__).parent
_SCRIPTS = _PACKAGE.parents[1] / "scripts"


@pytest.fixture(autouse=True)
def _each_test_starts_with_an_empty_store():  # noqa: ANN201
    saved = dict(config._PRIVATE)
    config._PRIVATE.clear()
    yield
    config._PRIVATE.clear()
    config._PRIVATE.update(saved)


def _env_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


# ── 읽기 · 싣기 ────────────────────────────────────────────────────────────────


def test_a_value_from_the_env_file_is_readable_but_not_in_the_environment(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("JARVIS_T_TOKEN", raising=False)
    loaded = config.load_env_file(_env_file(tmp_path, "JARVIS_T_TOKEN=abc123\n# 설명 줄\nJARVIS_T_QUOTED=\"a b c\"\n"))
    assert loaded == {"JARVIS_T_TOKEN": "abc123", "JARVIS_T_QUOTED": "a b c"}
    assert config.setting("JARVIS_T_TOKEN") == "abc123"
    assert config._env("JARVIS_T_TOKEN") == "abc123"
    assert "JARVIS_T_TOKEN" not in os.environ and "JARVIS_T_QUOTED" not in os.environ


def test_the_environment_still_wins_over_the_file(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("JARVIS_T_SWITCH", "false")
    loaded = config.load_env_file(_env_file(tmp_path, "JARVIS_T_SWITCH=true\n"))
    assert loaded == {}, "환경에 이미 있는 이름은 싣지 않는다"
    assert config.setting("JARVIS_T_SWITCH") == "false"


def test_an_empty_environment_value_does_not_hide_the_stored_one(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    config.keep_private("JARVIS_T_NAME", "stored")
    monkeypatch.setenv("JARVIS_T_NAME", "")
    assert config.setting("JARVIS_T_NAME") == "stored"
    assert config.setting("JARVIS_T_MISSING", "fallback") == "fallback"
    assert config.setting("JARVIS_T_MISSING") == ""


def test_the_config_loader_sees_what_the_file_gave(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("JARVIS_INTENT_SHADOW_ENABLED", raising=False)
    assert JarvisConfig.from_env().intent_shadow_enabled is False
    config.load_env_file(_env_file(tmp_path, "JARVIS_INTENT_SHADOW_ENABLED=1\n"))
    assert JarvisConfig.from_env().intent_shadow_enabled is True
    assert "JARVIS_INTENT_SHADOW_ENABLED" not in os.environ


def test_keep_private_does_not_override_unless_asked(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("JARVIS_T_HOST", raising=False)
    config.keep_private("JARVIS_T_HOST", "127.0.0.1")
    config.keep_private("JARVIS_T_HOST", "0.0.0.0")
    assert config.setting("JARVIS_T_HOST") == "127.0.0.1", "먼저 정해진 값이 남는다"
    config.keep_private("JARVIS_T_HOST", "0.0.0.0", override=True)
    assert config.setting("JARVIS_T_HOST") == "0.0.0.0"
    monkeypatch.setenv("JARVIS_T_PORT", "9000")
    config.keep_private("JARVIS_T_PORT", "8091")
    assert config.setting("JARVIS_T_PORT") == "9000", "환경에 있는 이름의 기본값은 넣지 않는다"
    assert "JARVIS_T_HOST" not in os.environ


# ── 물려받은 것은 안으로 옮긴다 ─────────────────────────────────────────────────────


def test_what_we_inherited_is_moved_inside_and_removed_from_the_environment(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("JARVIS_T_ROOT", "C:/somewhere")
    monkeypatch.setenv("jarvis_t_lower", "also-ours")
    monkeypatch.setenv("NOT_OURS_T", "stays")
    moved = config.absorb_environment()
    assert "JARVIS_T_ROOT" in moved
    assert "JARVIS_T_ROOT" not in os.environ
    assert not [key for key in os.environ if key.upper().startswith("JARVIS_T_")], "대소문자가 달라도 우리 것이다(윈도우)"
    assert os.environ.get("NOT_OURS_T") == "stays", "남의 것은 건드리지 않는다"
    assert config.setting("JARVIS_T_ROOT") == "C:/somewhere"


def test_what_the_user_set_in_the_environment_beats_the_file_even_after_it_moved_inside(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("JARVIS_T_MODEL", "from-environment")
    config.absorb_environment()
    loaded = config.load_env_file(_env_file(tmp_path, "JARVIS_T_MODEL=from-file\nJARVIS_T_OTHER=x\n"))
    assert loaded == {"JARVIS_T_OTHER": "x"}
    assert config.setting("JARVIS_T_MODEL") == "from-environment"


def test_the_runtime_root_is_found_without_the_environment(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("JARVIS_RUNTIME_ROOT", raising=False)
    config.keep_private("JARVIS_RUNTIME_ROOT", str(tmp_path), override=True)
    assert Path(config._default_runtime_root()) == tmp_path
    assert "JARVIS_RUNTIME_ROOT" not in os.environ


# ── 자식에게 가는 것 ───────────────────────────────────────────────────────────────


def test_a_program_we_start_inherits_nothing_of_ours(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """이것이 이 일의 목적이다 — 켜는 자리에서 아무것도 안 해도(env 를 안 줘도) 새지 않는다."""
    monkeypatch.setenv("JARVIS_T_INHERITED", "secret-from-parent")
    config.absorb_environment()
    config.load_env_file(_env_file(tmp_path, "JARVIS_T_TOKEN=abc123\n"))
    config.keep_private("JARVIS_RUNTIME_ROOT", str(tmp_path), override=True)
    done = subprocess.run(
        [sys.executable, "-c", "import os; print(sorted(k for k in os.environ if k.upper().startswith('JARVIS_')))"],
        capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr[-300:]
    assert done.stdout.strip() == "[]", f"자식이 우리 설정을 물려받았다: {done.stdout.strip()[:200]}"


def test_our_own_parts_get_our_settings_only_when_we_hand_them_over(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("JARVIS_T_TOKEN", raising=False)
    config.load_env_file(_env_file(tmp_path, "JARVIS_T_TOKEN=abc123\n"))
    handed = config.environment_for_our_own_child()
    assert handed["JARVIS_T_TOKEN"] == "abc123"
    assert "PATH" in {key.upper() for key in handed}, "보통의 환경도 같이 간다"
    assert "JARVIS_T_TOKEN" not in os.environ, "건네줄 것을 만들었다고 우리 환경이 바뀌지 않는다"
    handed["JARVIS_T_TOKEN"] = "changed"
    assert config.setting("JARVIS_T_TOKEN") == "abc123", "돌려준 것은 사본이다"


# ── 배선 ─────────────────────────────────────────────────────────────────────

_DIRECT_READ = re.compile(r"""os\.(?:environ\.get|getenv)\(\s*["']JARVIS_|os\.environ\[\s*["']JARVIS_|os\.environ\.setdefault\(\s*["']JARVIS_""")
#: 환경을 직접 읽어도 되는 파일. `config.py` 는 읽는 한 곳이고, `mcp_server.py` 는 바깥 AI 가 따로 켜는 프로세스라 제 환경을 읽는다.
_MAY_READ_DIRECTLY = {"config.py", "mcp_server.py"}


def test_no_other_module_reads_our_settings_straight_from_the_environment() -> None:
    found = []
    for path in sorted(_PACKAGE.glob("*.py")):
        if path.name in _MAY_READ_DIRECTLY:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _DIRECT_READ.search(line) and not line.lstrip().startswith("#"):
                found.append(f"{path.name}:{number}")
    assert not found, f"환경에서 우리 설정을 직접 읽는 자리가 남았다(config.setting 을 써라): {found}"


def test_the_entry_points_write_nothing_of_ours_into_the_environment() -> None:
    entry = (_SCRIPTS / "task_entry.py").read_text(encoding="utf-8")
    assert not _DIRECT_READ.search(entry), "시작 스크립트가 환경에 우리 설정을 쓰거나 직접 읽는다"
    assert "absorb_environment(" in entry and "keep_private(" in entry
    main = (_PACKAGE / "__main__.py").read_text(encoding="utf-8")
    assert "absorb_environment(" in main


def test_our_own_parts_are_started_with_our_settings_handed_over() -> None:
    for name in ("tts_server.py", "hwp.py"):
        source = (_PACKAGE / name).read_text(encoding="utf-8")
        assert "environment_for_our_own_child(" in source, f"{name} — 우리 부속을 켤 때는 설정을 건네줘야 한다(환경에 없으니 물려받지 못한다)"
