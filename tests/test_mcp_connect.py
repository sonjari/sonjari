"""P5 — 클로드·코덱스·커서에 한 번에 잇기. 공개 제품 기준으로 시험한다.

- 설정 파일의 **다른 키는 한 글자도** 안 바뀐다
- **토큰이 어느 설정에도 안 들어간다**
- 클로드 데스크톱이 켜져 있으면 안 쓴다(앱이 덮어쓴다)
- 코덱스 TOML 은 다른 표를 안 건드리고, 결과가 유효한 TOML 이다
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.mcp_connect import SERVER_NAME, ConnectService, toml_without_server


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path / "rt", data_dir=tmp_path / "rt" / "data",
                        output_dir=tmp_path / "rt" / "out", control_token="secret-token-should-not-leak")


class _Cli:
    def __init__(self, get_returncode: int = 1) -> None:
        self.calls: list[list[str]] = []
        self.get_returncode = get_returncode

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        joined = " ".join(cmd)
        code = self.get_returncode if " get " in f" {joined} " else 0
        if "add-json" in joined:
            self.get_returncode = 0
        return subprocess.CompletedProcess(cmd, code, stdout="", stderr="")


def _service(tmp_path: Path, *, running=(), which=None, cli=None) -> ConnectService:
    home = tmp_path / "home"
    return ConnectService(
        _config(tmp_path), run=cli or _Cli(), which=which or (lambda name: None),
        processes=lambda: list(running), home=home, appdata=home / "AppData" / "Roaming",
        localappdata=home / "AppData" / "Local", clock=lambda: 1_780_000_000.0, python="C:/py/python.exe",
    )


def _desktop(tmp_path: Path, *, store: bool = True) -> list[Path]:
    home = tmp_path / "home"
    paths = [home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"]
    if store:
        paths.append(home / "AppData" / "Local" / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
                     / "claude_desktop_config.json")
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"preferences": {"theme": "dark"}, "coworkUserFilesPath": "D:/x"}), encoding="utf-8")
    return paths


def test_entry_has_no_secret_and_points_at_the_running_install(tmp_path: Path) -> None:
    entry = _service(tmp_path).entry()
    blob = json.dumps(entry)
    assert "secret-token-should-not-leak" not in blob and "JARVIS_CONTROL_TOKEN" not in blob
    assert entry["env"]["JARVIS_TOKEN_FILE"].endswith("control.token")
    # 「이 PC 의 경로를 박아 두지 않았다」를 본다. 다만 코드 자체가 그 이름이 든 폴더에 놓여 있으면(우리 운영 폴더 밑의 사본 등)
    # 연결 항목의 PYTHONPATH 에 그 이름이 **정당하게** 들어간다 — 그 경우는 박아 둔 것이 아니다 (2026-10-09).
    # 손자리가 작업 자리(사본)에서 전체 시험을 돌리면 이 줄 하나만 떨어졌다. 저장소를 받아 그런 경로에 둔 사람도 똑같이 밟는다.
    import alture_jarvis

    code_lives_here = str(Path(alture_jarvis.__file__).resolve())
    assert "RoboMetaFit" not in blob or "RoboMetaFit" in str(tmp_path) or "RoboMetaFit" in code_lives_here


def test_desktop_both_store_and_classic_paths_get_only_our_key(tmp_path: Path) -> None:
    paths = _desktop(tmp_path)
    service = _service(tmp_path)
    assert service.scan()["clients"][0]["installed"]
    result = service.apply("claude_desktop")
    assert result["ok"] and len(result["backups"]) == 2
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["preferences"] == {"theme": "dark"} and data["coworkUserFilesPath"] == "D:/x"
        assert SERVER_NAME in data["mcpServers"]
    assert service.scan()["clients"][0]["registered"]
    assert service.remove("claude_desktop")["ok"]
    assert all(SERVER_NAME not in json.loads(p.read_text(encoding="utf-8"))["mcpServers"] for p in paths)


def test_desktop_is_not_touched_while_the_app_runs_and_is_connected_once_it_closes(tmp_path: Path) -> None:
    """켜진 채 쓰면 앱이 종료하면서 덮어쓴다 — 그래서 **켜져 있는 동안은 안 쓴다.** 예전엔 여기서 거절하고 끝이라
    Claude Desktop 을 쓰면서 설치하는 사람이 막혔다(2026-09-16 노트북). 이제 닫히는 순간 잇는다."""
    import time as _time

    paths = _desktop(tmp_path)
    before = paths[0].read_bytes()
    running = [r"C:\Program Files\WindowsApps\Claude_1.0_x64__abc\app\claude.exe"]
    service = _service(tmp_path, running=running)
    service.desktop_poll_sec = 0.01

    assert service.apply("claude_desktop") == {"ok": True, "pending": "until_claude_desktop_closes"}
    _time.sleep(0.1)
    assert paths[0].read_bytes() == before, "켜져 있는 동안 썼다"
    assert service.scan()["clients"][0]["waiting_for_close"] is True

    running.clear()  # 사람이 Claude Desktop 을 닫았다
    for _ in range(100):
        if not service._desktop_waiting:
            break
        _time.sleep(0.02)
    assert SERVER_NAME in json.loads(paths[0].read_text(encoding="utf-8"))["mcpServers"]


def test_the_bundled_claude_code_is_not_mistaken_for_the_desktop_app(tmp_path: Path) -> None:
    _desktop(tmp_path)
    service = _service(tmp_path, running=[r"C:\Users\u\AppData\Roaming\Claude\claude-code\2.1.0\claude.exe"])
    assert service.apply("claude_desktop")["ok"]


def test_a_broken_json_config_is_refused_not_overwritten(tmp_path: Path) -> None:
    path = _desktop(tmp_path, store=False)[0]
    path.write_text("{ broken", encoding="utf-8")
    assert _service(tmp_path).apply("claude_desktop")["error"] == "config_not_json"
    assert path.read_text(encoding="utf-8") == "{ broken"


def test_cursor_config_is_created_with_the_documented_shape(tmp_path: Path) -> None:
    (tmp_path / "home" / ".cursor").mkdir(parents=True)
    service = _service(tmp_path)
    assert service.apply("cursor")["ok"]
    data = json.loads((tmp_path / "home" / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"][SERVER_NAME]["args"] == ["-m", "alture_jarvis.mcp_server"]


def test_claude_code_goes_through_the_cli_with_cmd_wrapping(tmp_path: Path) -> None:
    cli = _Cli()
    service = _service(tmp_path, which=lambda n: r"C:\npm\claude.CMD" if n == "claude" else None, cli=cli)
    assert service.apply("claude_code")["ok"]
    add = next(c for c in cli.calls if "add-json" in " ".join(c))
    assert add[:4] == ["cmd.exe", "/d", "/s", "/c"] and "--scope user" in add[4]
    assert "secret-token-should-not-leak" not in " ".join(add)


def test_claude_code_without_cli_offers_a_manual_snippet(tmp_path: Path) -> None:
    result = _service(tmp_path).apply("claude_code")
    assert result["error"] == "cli_missing" and SERVER_NAME in result["manual"]


CODEX = '''model = "gpt-5"
api_key = "keep-me"

[mcp_servers.other]
command = "node"

[mcp_servers.alture-jarvis]
command = "old"

[mcp_servers.alture-jarvis.env]
X = "1"

[profiles.fast]
model = "mini"
'''


def test_codex_toml_replaces_only_our_table_and_stays_valid(tmp_path: Path) -> None:
    path = tmp_path / "home" / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(CODEX, encoding="utf-8")
    service = _service(tmp_path)
    assert service.apply("codex")["ok"]
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["api_key"] == "keep-me" and data["mcp_servers"]["other"]["command"] == "node"
    assert data["profiles"]["fast"]["model"] == "mini"
    assert data["mcp_servers"][SERVER_NAME]["command"] == "C:/py/python.exe"
    assert service.remove("codex")["ok"]
    assert SERVER_NAME not in tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]


def test_toml_strip_keeps_following_tables() -> None:
    assert "[profiles.fast]" in toml_without_server(CODEX) and "old" not in toml_without_server(CODEX)


def test_session_start_hook_is_merged_idempotently_and_removable(tmp_path: Path) -> None:
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"agentPushNotifEnabled": True, "hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": "echo mine"}]}]}}), encoding="utf-8")
    service = _service(tmp_path)
    assert service.set_hook(True)["ok"] and service.set_hook(True)["ok"]
    data = json.loads(settings.read_text(encoding="utf-8"))
    ours = [h for g in data["hooks"]["SessionStart"] for h in g["hooks"] if "takeover_hook.py" in json.dumps(h)]
    assert len(ours) == 1 and data["agentPushNotifEnabled"] is True
    assert "secret-token-should-not-leak" not in settings.read_text(encoding="utf-8")
    assert service.set_hook(False)["ok"]
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["SessionStart"] == [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo mine"}]}]


def test_mcp_server_reads_the_token_file_when_env_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import mcp_server

    token = tmp_path / "control.token"
    token.write_text("tok-from-file\n", encoding="utf-8")
    monkeypatch.delenv("JARVIS_CONTROL_TOKEN", raising=False)
    monkeypatch.setenv("JARVIS_TOKEN_FILE", str(token))
    assert mcp_server.resolve_token() == "tok-from-file"


def test_connecting_also_writes_the_one_line_into_the_global_guidance(tmp_path: Path) -> None:
    """★ 2026-09-16 실측: 설정만 이어 두면 **안 부른다.** Codex 는 온텔릭을 0번 부르고 자기 브라우저로 했다.

    전역 지침(`AGENTS.md`·`CLAUDE.md`)은 스킬과 달리 매번 읽히므로, 잇기 한 번에 둘 다 넣고 풀기에 둘 다 뺀다.
    """
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    agents = home / ".codex" / "AGENTS.md"
    agents.write_text("# 내 지침\n\n- 한국어로 답한다\n", encoding="utf-8")
    (home / ".codex" / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
    service = ConnectService(
        _config(tmp_path), run=_Cli(), which=lambda name: None, processes=list,
        home=home, appdata=home / "AppData" / "Roaming", localappdata=home / "AppData" / "Local",
        clock=lambda: 1_780_000_000.0, python="C:/py/python.exe",
        exported_tools=lambda: [{"name": "sonjari_task", "description": "통째로 맡기기"}],
    )

    applied = service.apply("codex")

    assert applied["ok"], applied
    text = agents.read_text(encoding="utf-8")
    assert "- 한국어로 답한다" in text and "sonjari-guide.md" in text
    assert (home / ".codex" / "sonjari-guide.md").exists()

    removed = service.remove("codex")

    assert removed["ok"]
    left = agents.read_text(encoding="utf-8")
    assert "sonjari" not in left and "- 한국어로 답한다" in left


def test_an_npm_cmd_shim_is_run_directly_not_through_cmd(tmp_path: Path) -> None:
    """2026-09-17 첫 실행 E2E: `cmd.exe /s /c` 로 감싸 연결 JSON 을 넘기니 따옴표가 깨져 claude 가
    `Invalid configuration: : Invalid input` 으로 거절했다. 심이 가리키는 exe 를 직접 띄우면 인자가 그대로 간다."""
    from alture_jarvis import mcp_connect

    npm = tmp_path / "npm"
    exe = npm / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    shim = npm / "claude.cmd"
    shim.write_text("@ECHO off\r\nGOTO start\r\n:start\r\n"
                    + r'"%dp0%\node_modules\@anthropic-ai\claude-code\bin\claude.exe"   %*' + "\r\n",
                    encoding="utf-8")
    seen: list[list[str]] = []

    def run(cmd, **_kwargs):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    payload = json.dumps({"type": "stdio", "command": "C:/py/python.exe", "args": ["-m", "x"]})
    mcp_connect._run_cli(run, str(shim), ["mcp", "add-json", "ontelic", payload, "--scope", "user"])

    assert seen[0][0] == str(exe) and "cmd.exe" not in seen[0]
    assert seen[0][4] == payload, "JSON 인자는 한 글자도 바뀌면 안 된다"


def test_an_unreadable_shim_still_falls_back_to_cmd(tmp_path: Path) -> None:
    from alture_jarvis import mcp_connect

    seen: list[list[str]] = []
    mcp_connect._run_cli(lambda cmd, **_k: seen.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0, "", ""),
                         str(tmp_path / "missing.cmd"), ["--version"])
    assert seen[0][0] == "cmd.exe"



def test_claude_desktop_bundled_claude_code_is_used_when_there_is_no_cli_on_path(tmp_path: Path) -> None:
    """Claude Desktop 만 깐 PC(2026-09-17 노트북): PATH 에 `claude` 가 없어도 Desktop 이 들고 있는 CLI 로 잇는다."""
    home = tmp_path / "home"
    for version in ("2.1.9", "2.1.271"):
        exe = home / "AppData" / "Roaming" / "Claude" / "claude-code" / version / "claude.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")
    cli = _Cli()
    service = _service(tmp_path, cli=cli)  # which() 는 아무것도 못 찾는다

    scan = {c["id"]: c for c in service.scan()["clients"]}["claude_code"]
    assert scan["can_apply"] and scan["cli"].endswith(r"2.1.271\claude.exe"), "버전 문자열 순서가 아니라 숫자 순서로 가장 새것"
    assert service.apply("claude_code")["ok"]
    add = next(c for c in cli.calls if "add-json" in c)
    assert add[0].endswith(r"2.1.271\claude.exe") and "cmd.exe" not in add


def test_a_separately_installed_claude_code_is_found_even_when_path_does_not_have_it(tmp_path: Path) -> None:
    """2026-10-06 스토어판 첫 설치(노트북): 클로드 코드를 따로 깐 PC 인데 「명령을 찾지 못함」이 떴다.

    PATH 는 앱이 켜진 때의 것이다 — 설치 뒤 다시 로그인하지 않았으면 그 자리가 빠져 있다. 자리를 직접 본다.
    """
    home = tmp_path / "home"
    exe = home / ".local" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    cli = _Cli()
    service = _service(tmp_path, cli=cli)  # which() 는 아무것도 못 찾는다

    scan = {c["id"]: c for c in service.scan()["clients"]}["claude_code"]

    assert scan["can_apply"] and scan["reason"] == ""
    assert scan["cli"].endswith(r".local\bin\claude.exe")
    assert service.apply("claude_code")["ok"]


def test_an_npm_installed_claude_code_is_found_by_its_place(tmp_path: Path) -> None:
    home = tmp_path / "home"
    shim = home / "AppData" / "Roaming" / "npm" / "claude.cmd"
    shim.parent.mkdir(parents=True)
    shim.write_text("@echo off\r\n", encoding="utf-8")
    service = _service(tmp_path, cli=_Cli())

    scan = {c["id"]: c for c in service.scan()["clients"]}["claude_code"]

    assert scan["can_apply"] and scan["cli"].endswith(r"npm\claude.cmd")


def test_the_separately_installed_one_wins_over_the_copy_inside_claude_desktop(tmp_path: Path) -> None:
    home = tmp_path / "home"
    own = home / ".local" / "bin" / "claude.exe"
    bundled = home / "AppData" / "Roaming" / "Claude" / "claude-code" / "2.1.271" / "claude.exe"
    for exe in (own, bundled):
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")
    service = _service(tmp_path, cli=_Cli())

    scan = {c["id"]: c for c in service.scan()["clients"]}["claude_code"]

    assert scan["cli"] == str(own)
