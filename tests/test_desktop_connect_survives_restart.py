"""Claude Desktop 잇기 — 따로 깐 클로드 코드를 Desktop 으로 착각하지 않고, 「닫히면 잇기」가 재시작을 넘어간다 (2026-10-01).

베타 테스터(회사 PC): 「잇기」를 누르자 「Claude Desktop 을 닫으면 바로 잇습니다」. 재부팅하고 다시 해도 클로드가 손자리를 모른다
(「온텔릭도 해 봤는데 클로드가 그게 뭐임?」). 원인 둘 — 따로 깐 클로드 코드(`%USERPROFILE%\.local\bin\claude.exe`)가 늘 떠 있어
「Desktop 이 켜져 있다」로 봤고, 기다림은 앱 메모리에만 있어 재부팅에 사라졌다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from alture_jarvis.mcp_connect import SERVER_NAME
from test_mcp_connect import _desktop, _service

CLI = r"C:\Users\u\.local\bin\claude.exe"
DESKTOP = r"C:\Program Files\WindowsApps\Claude_2.16_x64__abc\app\claude.exe"


def _wait_done(service) -> None:
    for _ in range(200):
        if not service._desktop_waiting:
            return
        time.sleep(0.02)


def test_a_separately_installed_claude_code_is_not_the_desktop_app(tmp_path: Path) -> None:
    paths = _desktop(tmp_path)
    service = _service(tmp_path, running=[CLI])
    assert service.desktop_running() is False
    assert service.apply("claude_desktop")["ok"]
    assert SERVER_NAME in json.loads(paths[0].read_text(encoding="utf-8"))["mcpServers"]


def test_the_wait_survives_an_app_restart(tmp_path: Path) -> None:
    paths = _desktop(tmp_path)
    first = _service(tmp_path, running=[DESKTOP])
    first.clock = time.monotonic  # 시험 기본 시계는 멈춰 있다 — 기다림이 끝나려면 흘러야 한다
    first.desktop_poll_sec = 0.01
    first.desktop_wait_limit_sec = 0.05  # 첫 앱은 기다리다 끝난다(재부팅으로 죽은 것과 같다)
    assert first.apply("claude_desktop")["pending"] == "until_claude_desktop_closes"
    _wait_done(first)
    assert SERVER_NAME not in (json.loads(paths[0].read_text(encoding="utf-8")).get("mcpServers") or {})

    # 다시 뜬 앱 — 이번엔 Desktop 이 닫혀 있다. 사람이 다시 누르지 않아도 잇는다.
    assert not first._desktop_waiting
    second = _service(tmp_path, running=[])
    second.desktop_poll_sec = 0.01
    assert second.resume_pending()["pending"] == "until_claude_desktop_closes"
    _wait_done(second)
    assert SERVER_NAME in json.loads(paths[0].read_text(encoding="utf-8"))["mcpServers"]
    assert second.resume_pending() == {"ok": True, "pending": ""}, "이어진 뒤엔 표식이 없다"


def test_removing_cancels_the_pending_wait(tmp_path: Path) -> None:
    _desktop(tmp_path)
    service = _service(tmp_path, running=[DESKTOP])
    service.clock = time.monotonic
    service.desktop_poll_sec = 0.01
    service.desktop_wait_limit_sec = 0.05
    service.apply("claude_desktop")
    _wait_done(service)
    service.remove("claude_desktop")
    assert _service(tmp_path, running=[]).resume_pending() == {"ok": True, "pending": ""}
