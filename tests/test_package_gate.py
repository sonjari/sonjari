"""올리기 전 관문 — 진짜 패키지 안 합격 시험이 떨어지면 채널에 안 올린다 (2026-09-18).

오늘 채널에 네 번 올렸는데 앞의 두 번은 고장난 Ollama 설치를 노트북에 보냈다. 합격 시험은 있었지만
사람이 기억해야 돌았고, 무엇이 실패해도 종료 코드가 0 이라 관문이 될 수 없었다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _publish_script(encoding: str = "ascii") -> str:
    """채널에 올리는 스크립트의 글. 공개본에는 이 스크립트를 싣지 않는다(우리 운영 도구) — 거기서만 건너뛴다.

    모노레포에서 파일이 없으면 건너뛰지 않고 그대로 실패한다. 조용히 건너뛰는 시험은 관문이 아니다.
    """
    path = ROOT / "packaging" / "msix" / "publish_update_channel.ps1"
    if not path.is_file() and (ROOT / ".sonjari-public-export").is_file():
        pytest.skip("채널에 올리는 스크립트는 공개본에 없다")
    return path.read_text(encoding=encoding)


def _harness():
    spec = importlib.util.spec_from_file_location("run_app_package_test", ROOT / "packaging" / "msix" / "run_app_package_test.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


GOOD = {
    "health": {"ok": True}, "token_in_private_cache": True,
    "ollama_install_root_outside_app_private_store": {"ok": True, "install_root": r"C:\Users\u\Ontelic\engine\ollama"},
    "chat": {"status": "completed"}, "mcp_tools_via_alias": 44, "web_research_passed": True,
    "private_cache_after_remove": False, "backend_after_remove": "gone",
}


def test_a_clean_run_passes() -> None:
    assert _harness().verdict(dict(GOOD), web=True) == []


def test_todays_bug_fails_the_gate() -> None:
    """오늘 노트북에 나간 그 상태 — Ollama 가 앱 전용 칸 안에 깔린다."""
    bad = {**GOOD, "ollama_install_root_outside_app_private_store": {"ok": False}}
    assert _harness().verdict(bad, web=True) == ["ollama_install_root_outside_app_private_store"]


def test_a_missing_step_is_a_failure_not_a_pass() -> None:
    """빈 값 하나가 두 사실을 뜻하면 조용히 고장난다 — 「안 쟀다」를 「통과」로 읽지 않는다."""
    partial = {k: v for k, v in GOOD.items() if k != "mcp_tools_via_alias"}
    assert "mcp_tools_via_alias" in _harness().verdict(partial, web=False)
    assert "mcp_tools_via_alias" in _harness().verdict({**GOOD, "mcp_tools_via_alias": "error: ModuleNotFoundError"}, web=False)


def test_the_publish_script_runs_the_gate_before_signing_and_uploading() -> None:
    source = _publish_script()
    gate = source.index("run_app_package_test.py")
    assert gate < source.index("# 4) sign"), "서명·업로드 전에 돌아야 한다"
    assert "package gate failed" in source and "throw" in source[gate:gate + 900]


def test_the_channel_name_and_the_channel_token_are_different_variables() -> None:
    """★ PowerShell 변수는 대소문자를 안 가린다 — 매개변수 `$Channel`(stable/beta 만 허용)에 채널 주소 값을 넣으려다
    검증에 걸려 올리기가 통째로 멈췄다(2026-09-18). 주소 값은 다른 이름이어야 한다."""
    import re

    source = _publish_script()
    body = source[source.index('$ErrorActionPreference = "Stop"'):]  # 매개변수 기본값 선언은 빼고 본문만
    assert not re.search(r"(?i)\$channel\s*=", body), "매개변수 $Channel 에 값을 다시 넣으면 ValidateSet 이 거절한다"
    assert "$channelToken" in source
