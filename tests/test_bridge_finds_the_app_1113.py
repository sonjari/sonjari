"""클로드 플러그인용(2026-11-13): 환경변수 없이도 다리가 이 PC 손자리 앱의 토큰 파일을 스스로 찾는다.

플러그인 `.mcp.json` 에는 사람마다 다른 경로를 못 적는다 — 앱과 같은 규칙(`…/Sonjari/data/control.token`)으로 찾는다.
환경변수가 있으면 그것이 이긴다(앱이 써 주는 지금 연결은 그대로).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from alture_jarvis import mcp_server


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("JARVIS_CONTROL_TOKEN", "JARVIS_TOKEN_FILE", "JARVIS_RUNTIME_ROOT", "SONJARI_APP_SUPPORT"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_without_env_the_bridge_reads_the_apps_own_token_file(tmp_path: Path, clean_env) -> None:
    data = tmp_path / "Sonjari" / "data"
    data.mkdir(parents=True)
    (data / "control.token").write_text("tok-from-app\n", encoding="utf-8")
    if sys.platform == "win32":
        clean_env.setenv("LOCALAPPDATA", str(tmp_path))
    else:
        clean_env.setattr(sys, "platform", "darwin")
        clean_env.setenv("SONJARI_APP_SUPPORT", str(tmp_path))
    assert mcp_server.default_token_file() == data / "control.token"
    assert mcp_server.resolve_token() == "tok-from-app"


def test_env_still_wins_over_the_default(tmp_path: Path, clean_env) -> None:
    clean_env.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "nowhere"))
    named = tmp_path / "named.token"
    named.write_text("tok-named", encoding="utf-8")
    clean_env.setenv("JARVIS_TOKEN_FILE", str(named))
    assert mcp_server.resolve_token() == "tok-named"
    clean_env.setenv("JARVIS_CONTROL_TOKEN", "tok-env")
    assert mcp_server.resolve_token() == "tok-env"


def test_no_app_means_empty_token_not_a_crash(tmp_path: Path, clean_env) -> None:
    clean_env.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "no-app-here"))
    assert mcp_server.resolve_token() == ""


def test_the_default_follows_the_apps_runtime_rule(tmp_path: Path, clean_env) -> None:
    """앱(config)과 다리가 같은 자리를 가리켜야 한다 — 두 벌이 갈리면 조용히 401."""
    from alture_jarvis.config import _default_runtime_root

    clean_env.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "rt"))
    assert mcp_server.default_token_file() == _default_runtime_root() / "data" / "control.token"
    clean_env.delenv("JARVIS_RUNTIME_ROOT")
    if sys.platform == "win32":
        clean_env.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    else:
        clean_env.setattr(sys, "platform", "darwin")
        clean_env.setenv("SONJARI_APP_SUPPORT", str(tmp_path / "sup"))
    assert mcp_server.default_token_file() == _default_runtime_root() / "data" / "control.token"
