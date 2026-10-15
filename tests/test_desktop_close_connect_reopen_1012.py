"""Claude Desktop 을 **닫고 → 잇고 → 다시 켜기**를 한 번에 (2026-10-12).

처음 깐 두 사람이 같은 자리에서 헤맸다 — 첫 설정의 금색 단추만 따라 누르면 「닫으면 잇습니다」를 지나쳐 끝나고,
「클로드를 껐다 켜라」는 글로만 있었다. 창의 X 는 앱을 끄지 않고 작업 표시줄 구석에 남긴다.
사람이 「다시 켤까요?」에 누르면 손자리가 대신 한다. 말없이 하지 않는다 — 이 길은 누른 뒤에만 불린다.

지키는 것:
- 설정을 못 쓸 판이면(깨진 파일 · 설치 안 됨) **앱을 끄지 않는다**
- 앱이 안 꺼지면 설정을 건드리지 않는다(켜진 채 쓰면 앱이 종료하면서 덮어쓴다)
- 터미널의 클로드 코드(`claude.exe`)는 끄지 않는다
- 순서는 끄기 → 쓰기 → 켜기
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from alture_jarvis.mcp_connect import SERVER_NAME, ConnectService

from test_mcp_connect import _Cli, _config, _desktop

DESKTOP = r"C:\Program Files\WindowsApps\Claude_1.0_x64__abc\app\claude.exe"
CLASSIC = r"C:\Users\u\AppData\Local\AnthropicClaude\app-1.2.3\claude.exe"
TERMINAL_CODE = r"C:\Users\u\.local\bin\claude.exe"
APP_CODE = r"C:\Users\u\AppData\Roaming\Claude\claude-code\2.1.0\claude.exe"


class _Pc:
    """켜져 있는 프로세스 · 끄기 · 켜기를 흉내 낸다. 실제 프로세스는 건드리지 않는다."""

    def __init__(self, running: list[str], *, closes: bool = True) -> None:
        self.running = list(running)
        self.closes = closes
        self.events: list[str] = []
        self.stopped: list[str] = []
        self.launched: list[str] = []

    def stop(self, exes: list[str]) -> None:
        self.events.append("stop")
        self.stopped = list(exes)
        if self.closes:
            self.running = [exe for exe in self.running if exe not in exes]

    def launch(self, exes: list[str]) -> bool:
        self.events.append("launch")
        self.launched = list(exes)
        self.running.extend(exes[:1])
        return True


def _service(tmp_path: Path, pc: _Pc) -> ConnectService:
    home = tmp_path / "home"
    service = ConnectService(
        _config(tmp_path), run=_Cli(), which=lambda name: None, processes=lambda: list(pc.running),
        home=home, appdata=home / "AppData" / "Roaming", localappdata=home / "AppData" / "Local",
        clock=time.time, python="C:/py/python.exe", desktop_stop=pc.stop, desktop_launch=pc.launch,
    )
    service.desktop_poll_sec = 0.01
    service.desktop_close_poll_sec = 0.01
    service.desktop_close_wait_sec = 0.3
    service.desktop_settle_sec = 0.0
    return service


def _has_us(path: Path) -> bool:
    return SERVER_NAME in (json.loads(path.read_text(encoding="utf-8")).get("mcpServers") or {})


def test_running_desktop_is_closed_then_connected_then_reopened(tmp_path: Path) -> None:
    paths = _desktop(tmp_path)
    pc = _Pc([DESKTOP, DESKTOP])
    service = _service(tmp_path, pc)
    seen: list[bool] = []
    real_change = service._change

    def change(client_id: str, *, add: bool):
        seen.append(service.desktop_running())      # 쓰는 순간 앱이 꺼져 있어야 한다
        pc.events.append("write")
        return real_change(client_id, add=add)

    service._change = change  # type: ignore[method-assign]

    result = service.restart_desktop()

    assert result["ok"] is True and result["desktop"] == "restarted"
    assert pc.events == ["stop", "write", "launch"]
    assert seen == [False]
    assert all(_has_us(path) for path in paths)
    assert service.scan()["clients"][0]["registered"] is True


def test_when_desktop_is_not_running_it_just_connects(tmp_path: Path) -> None:
    paths = _desktop(tmp_path)
    pc = _Pc([])
    result = _service(tmp_path, pc).restart_desktop()
    assert result["ok"] is True and result["desktop"] == "was_not_running"
    assert pc.events == []                              # 끈 것도 켠 것도 없다
    assert all(_has_us(path) for path in paths)


def test_a_config_we_cannot_write_is_found_before_the_app_is_closed(tmp_path: Path) -> None:
    path = _desktop(tmp_path, store=False)[0]
    path.write_text("{ broken", encoding="utf-8")
    pc = _Pc([CLASSIC])
    result = _service(tmp_path, pc).restart_desktop()
    assert result == {"ok": False, "error": "config_not_json", "path": str(path)}
    assert pc.events == [] and pc.running == [CLASSIC]   # 못 이을 판에 남의 앱만 꺼 놓지 않는다
    assert path.read_text(encoding="utf-8") == "{ broken"


def test_not_installed_closes_nothing(tmp_path: Path) -> None:
    pc = _Pc([DESKTOP])
    result = _service(tmp_path, pc).restart_desktop()
    assert result["ok"] is False and result["error"] == "not_installed"
    assert pc.events == []


def test_if_the_app_does_not_close_the_config_is_left_alone(tmp_path: Path) -> None:
    paths = _desktop(tmp_path)
    before = [path.read_bytes() for path in paths]
    pc = _Pc([DESKTOP], closes=False)
    result = _service(tmp_path, pc).restart_desktop()
    assert result == {"ok": False, "error": "claude_desktop_did_not_close"}
    assert pc.events == ["stop"]                          # 다시 켜지도 않는다 — 아직 켜져 있다
    assert [path.read_bytes() for path in paths] == before


def test_claude_code_in_a_terminal_is_never_closed(tmp_path: Path) -> None:
    _desktop(tmp_path)
    pc = _Pc([CLASSIC, TERMINAL_CODE, APP_CODE])
    result = _service(tmp_path, pc).restart_desktop()
    assert result["ok"] is True
    assert pc.stopped == [CLASSIC]
    assert TERMINAL_CODE in pc.running                    # 터미널에서 돌던 일은 그대로다
    assert pc.launched == [CLASSIC]


def test_the_wait_for_close_watcher_ends_once_we_are_connected(tmp_path: Path) -> None:
    """「닫으면 잇기」로 기다리던 중에 이 길로 이었으면, 기다림도 끝난다 — 다시 켠 앱을 보고 세 시간을 더 기다리지 않는다."""
    _desktop(tmp_path)
    pc = _Pc([DESKTOP])
    service = _service(tmp_path, pc)
    assert service.apply("claude_desktop") == {"ok": True, "pending": "until_claude_desktop_closes"}
    assert service.scan()["clients"][0]["waiting_for_close"] is True

    assert service.restart_desktop()["ok"] is True
    for _ in range(200):
        if not service._desktop_waiting:
            break
        time.sleep(0.01)
    client = service.scan()["clients"][0]
    assert client["waiting_for_close"] is False and client["registered"] is True
    assert not (service._pending_path() or Path("-")).exists()


def test_store_and_classic_installs_reopen_through_different_doors() -> None:
    """스토어판은 실행 파일을 직접 못 띄운다 — 시작 메뉴에 등록된 이름으로 연다. 설치형은 그 파일을 연다.
    둘 다 **앱 밖에서** 띄운다(스토어판 손자리의 자식으로 뜨면 손자리의 전용 칸 안에서 돈다)."""
    from alture_jarvis.mcp_connect import desktop_reopen_script

    store = desktop_reopen_script([DESKTOP])
    assert "Get-StartApps" in store and "shell:AppsFolder" in store and DESKTOP not in store
    classic = desktop_reopen_script([CLASSIC, CLASSIC])
    assert CLASSIC in classic and "shell:AppsFolder" not in classic
    assert desktop_reopen_script([]) == ""
