"""`.env` 를 실제로 읽는가 — 값은 보관소(`_PRIVATE`)에 간다, 환경에는 안 간다.

이 파일들은 오래 전부터 있었는데 **읽는 코드가 없었다.** 설정은 전부 `os.getenv` 로만
들어왔고, 실제 값은 `scripts/task_entry.py` 가 손으로 setdefault 하는 것들뿐이었다.
그래서 `.env` 에 무언가를 적어 두면 적용된 것처럼 보이지만 아무 일도 안 일어난다 —
2026-08-06 MCP 토큰을 넣고 재시작했는데 계속 401 이 나서 발견했다.

침묵하는 설정 파일은 잘못된 설정보다 나쁘다. 고쳤다고 믿고 다른 원인을 찾으러 간다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from alture_jarvis import config
from alture_jarvis.config import load_env_file


@pytest.fixture(autouse=True)
def _each_test_starts_with_an_empty_store():
    saved = dict(config._PRIVATE)
    config._PRIVATE.clear()
    yield
    config._PRIVATE.clear()
    config._PRIVATE.update(saved)


def _write(tmp_path: Path, text: str, *, bom: bool = False) -> Path:
    path = tmp_path / ".env"
    encoding = "utf-8-sig" if bom else "utf-8"
    path.write_text(text, encoding=encoding)
    return path


def test_values_reach_the_store_not_the_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_TEST_TOKEN", raising=False)
    path = _write(tmp_path, "JARVIS_TEST_TOKEN=abc123\n")

    loaded = load_env_file(path)

    assert loaded["JARVIS_TEST_TOKEN"] == "abc123"
    assert config.setting("JARVIS_TEST_TOKEN") == "abc123"
    assert "JARVIS_TEST_TOKEN" not in os.environ


def test_the_environment_always_wins(tmp_path: Path, monkeypatch) -> None:
    # task_entry.py 가 켜 두는 스위치를 오래된 .env 한 줄이 뒤집으면 안 된다.
    monkeypatch.setenv("JARVIS_TEST_SWITCH", "false")
    path = _write(tmp_path, "JARVIS_TEST_SWITCH=true\n")

    loaded = load_env_file(path)

    assert loaded == {}, "환경에 이미 있는 이름은 싣지 않는다"
    assert config.setting("JARVIS_TEST_SWITCH") == "false"


def test_a_bom_does_not_swallow_the_first_line(tmp_path: Path, monkeypatch) -> None:
    # BOM 을 안 벗기면 첫 키 이름에 들러붙어 그 줄만 조용히 사라진다(사고 J 와 같은 부류).
    monkeypatch.delenv("JARVIS_TEST_FIRST", raising=False)
    path = _write(tmp_path, "JARVIS_TEST_FIRST=1\nJARVIS_TEST_SECOND=2\n", bom=True)

    loaded = load_env_file(path)

    assert loaded.get("JARVIS_TEST_FIRST") == "1"


def test_comments_and_blank_lines_are_skipped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_TEST_REAL", raising=False)
    path = _write(tmp_path, "# 주석\n\n  \nJARVIS_TEST_REAL=yes\n")

    loaded = load_env_file(path)

    assert loaded == {"JARVIS_TEST_REAL": "yes"}


def test_quotes_are_stripped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_TEST_QUOTED", raising=False)
    path = _write(tmp_path, 'JARVIS_TEST_QUOTED="a b c"\n')

    assert load_env_file(path)["JARVIS_TEST_QUOTED"] == "a b c"


def test_a_value_containing_equals_survives(tmp_path: Path, monkeypatch) -> None:
    # base64 토큰에 = 패딩이 붙는다. 잘라 먹으면 인증이 조용히 실패한다.
    monkeypatch.delenv("JARVIS_TEST_B64", raising=False)
    path = _write(tmp_path, "JARVIS_TEST_B64=abc==\n")

    assert load_env_file(path)["JARVIS_TEST_B64"] == "abc=="


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "nope.env") == {}
