"""토큰 **수를 재는** 코드 · 기록은 읽을 수 있고, 비밀을 품을 수 있는 이름은 그대로 막힌다 (2026-10-20 · 운영 dd6c008c · 75aaa296).

클로드가 맡긴 코드 일에서 `bench/browser_agents/token_showdown.py` 를 읽지도 고치지도 못했다 — `token_` 조각이 이름만 보고 막았다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.local_computer import LocalComputerTools


@pytest.mark.parametrize("name", [
    "token_showdown.py", "token_showdown_A.json", "count_tool_tokens.py", "cursor_task_11_token_optimization.md",
])
def test_token_metric_code_is_readable(name: str) -> None:
    assert not LocalComputerTools._is_sensitive(Path("C:/work") / name)


@pytest.mark.parametrize("name", [
    "connector_token_store.py", "google_drive_obtain_refresh_token.py", "setup_github_cf_service_token.ps1",
    "add_token.py", "add_worker_token_to_nas.sh", "_major_tokens_snip.txt", "api_tokens.json", "access_token.txt",
    "control.token", "token.dpapi", "secret_scrub.py", "bot_token_count.py", "client_secret.json", ".env",
])
def test_secret_looking_names_stay_blocked(name: str) -> None:
    assert LocalComputerTools._is_sensitive(Path("C:/work") / name)


def test_a_secret_folder_still_blocks_a_metric_name() -> None:
    assert LocalComputerTools._is_sensitive(Path("C:/Users/me/.ssh") / "token_showdown.py")
