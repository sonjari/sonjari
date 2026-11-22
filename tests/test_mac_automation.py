"""`mac_automation.py` — 11-16 맥미니 Peekaboo 실측 기록을 맞대어 PC 에서 돈다(설계 §8-2).

자료: `fixtures/peekaboo_4_9_8/out1~3` 는 맥 `~/sonjari_peekaboo_test/` 에서 읽기만 해서 가져온 **실제 출력**이다(run1~3.sh 가 만든 것).
손으로 만든 json 은 실측에 없는 모양(`app list` · 허락 오류)과, 실측 출력에서 한 칸만 바꾼 반례(창 이름 · 값)뿐이고 그 자리에 적었다.
"""

from __future__ import annotations

import copy
import json
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.mac_automation import (
    MacAutomationTools,
    PeekabooRunner,
    PermissionNeeded,
    _window_rows,
    normalize_key_combo,
)
from alture_jarvis.tool_gateway import tool_runs_here

FIX = Path(__file__).parent / "fixtures" / "peekaboo_4_9_8"
TYPED = "손자리 시험입니다 hello 123"
#: 1판 실측에서 지정 없이 찍었을 때 잡힌 대표의 기존 문서 창 이름(`out1/te_see1.out`).
OTHER_DOC = "버그막이_설계.md"


def _raw(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _see1() -> dict[str, Any]:
    return json.loads(_raw("out3/see1.json"))


def _see_with(*, title: str | None = None, value: str | None = None, window_id: int | None = None) -> str:
    """실측 `see1.json` 에서 한 칸만 바꾼 반례. title 은 실측처럼 **NFD** 로 넣는다."""
    data = _see1()
    if title is not None:
        data["data"]["window_title"] = unicodedata.normalize("NFD", title)
    if value is not None:
        for row in data["data"]["ui_elements"]:
            if row["id"] == "elem_2":
                row["value"] = unicodedata.normalize("NFD", value)
    if window_id is not None:
        data["target_receipt"]["window_id"] = window_id
    return json.dumps(data, ensure_ascii=False)


def _perms(screen: bool, control: bool) -> str:
    """`permissions --json` — ★ 실측 기록 없음. v4.9.8 `PermissionHelpers.PermissionStatusResponse` 모양으로 만든 것."""
    return json.dumps({"success": True, "data": {"source": "local", "permissions": [
        {"name": "Screen Recording", "isRequired": True, "isGranted": screen, "grantInstructions": "System Settings > Privacy & Security > Screen Recording"},
        {"name": "Accessibility", "isRequired": True, "isGranted": control, "grantInstructions": "System Settings > Privacy & Security > Accessibility"},
        {"name": "Event Synthesizing", "isRequired": False, "isGranted": False, "grantInstructions": "x"},
    ]}})


PERMS_OK = _perms(True, True)

#: `app list --json` — ★ 실측 기록 없음(설계 §8-3). 소스 v4.9.8 `ServiceApplicationInfo` 칸 이름으로 만든 것.
APP_LIST = json.dumps({"success": True, "data": {"applications": [
    {"name": unicodedata.normalize("NFD", "텍스트 편집기"), "bundleIdentifier": "com.apple.TextEdit", "processIdentifier": 5259,
     "isHidden": False, "windowCount": 4},
    {"name": "Hidden", "bundleIdentifier": "x.hidden", "processIdentifier": 1, "isHidden": True, "windowCount": 1},
]}}, ensure_ascii=False)


class FakePeekaboo:
    """argv 를 받아 실측 출력을 돌려주는 가짜. `see` 는 차례대로 꺼낸다(없으면 마지막 것을 되풀이)."""

    def __init__(self, sees: list[str], *, action_rc: int = 1, action_out: str | None = None) -> None:
        self.sees = list(sees)
        self.argvs: list[list[str]] = []
        self.action_rc = action_rc
        self.action_out = _raw("out3/type.out") if action_out is None else action_out
        self.permissions_out = PERMS_OK

    @staticmethod
    def command(argv: list[str]) -> list[str]:
        """Peekaboo 명령 부분 — direct 는 `[실행 파일, 명령…]`, app 은 `open … --args 명령…`."""
        return argv[argv.index("--args") + 1:] if argv[0] == "/usr/bin/open" else argv[1:]

    def _answer(self, command: list[str]) -> tuple[int, str]:
        sub = command[0]
        if sub == "see":
            out = self.sees.pop(0) if len(self.sees) > 1 else self.sees[0]
            return (0 if '"success" : true' in out or '"success": true' in out else 1), out
        if sub == "app":
            return 0, APP_LIST
        if sub == "window" and command[1] == "list":
            return 0, _raw("out3/wins.json")
        if sub == "permissions":
            return 0, self.permissions_out
        # 동작 명령: 실측 3판처럼 「보냈지만 확인 안 됨」 rc=1 이 기본.
        return self.action_rc, self.action_out

    def __call__(self, argv: list[str], **_: Any) -> subprocess.CompletedProcess:
        self.argvs.append(list(argv))
        rc, out = self._answer(self.command(argv))
        if argv[0] == "/usr/bin/open":  # app 길: 출력은 --stdout 파일로 간다(실측 주력 세션 11-16)
            Path(argv[argv.index("--stdout") + 1]).write_text(out, encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, rc, out, "")

    def actions(self) -> list[list[str]]:
        commands = [self.command(argv) for argv in self.argvs]
        return [["peekaboo", *command] for command in commands if command[0] not in {"see", "app", "window", "permissions"}]


APP = "/Applications/Sonjari.app/Contents/Helpers/손자리 화면 도우미.app"


def _tools(tmp_path: Path, fake: FakePeekaboo, *, transport: str = "direct", **kwargs: Any) -> MacAutomationTools:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    runner = PeekabooRunner("/opt/peekaboo", transport=transport, app_bundle=APP, io_dir=tmp_path / "io", run=fake)
    return MacAutomationTools(config, runner=runner, wait_for_hands=lambda what: None, settle_sec=0, **kwargs)


def _type_flow(tmp_path: Path, sees: list[str], **fake_kw: Any) -> tuple[MacAutomationTools, FakePeekaboo, dict[str, Any]]:
    fake = FakePeekaboo(sees, **fake_kw)
    tools = _tools(tmp_path, fake)
    tools.ax_snapshot({"window_id": 3785})
    preview = tools.ax_preview({"window_id": 3785, "ref": "elem_2", "action": "set_value", "value": TYPED})
    return tools, fake, preview


# ── 함정 ① NFD ──────────────────────────────────────────────────────
def test_fixture_really_is_nfd() -> None:
    """시험이 뜻이 있으려면 자료가 정말 NFD 여야 한다 — 실측 「무제 2」는 길이 6."""
    titles = [row["window_title"] for row in json.loads(_raw("out3/wins.json"))["data"]["windows"]]
    assert "무제 2" not in titles and any(len(title) == 6 and unicodedata.normalize("NFC", title) == "무제 2" for title in titles)


def test_nfd_window_title_found_by_nfc_query() -> None:
    rows = _window_rows(json.loads(_raw("out3/wins.json"))["data"])
    titles = [row["title"] for row in rows]
    assert "무제 2" in titles and "무제 3" in titles
    assert all(unicodedata.is_normalized("NFC", title) for title in titles)
    assert [row["window_id"] for row in rows] == [3785, 3774, 3768]  # 제목 없는 픽셀 전용 창(3767)은 뺀다


def test_list_open_windows_all_names_nfc(tmp_path: Path) -> None:
    out = _tools(tmp_path, FakePeekaboo([_raw("out3/see1.json")])).list_open_windows({})
    assert out["count"] == 3
    assert {row["app"] for row in out["windows"]} == {"텍스트 편집기"}
    assert all(unicodedata.is_normalized("NFC", json.dumps(row, ensure_ascii=False)) for row in out["windows"])


def test_snapshot_elements_are_nfc_and_actionable_first(tmp_path: Path) -> None:
    out = _tools(tmp_path, FakePeekaboo([_raw("out3/see1.json")])).ax_snapshot({"window_id": 3785})
    assert out["title"] == "무제 3" and out["app"] == "텍스트 편집기"
    assert unicodedata.is_normalized("NFC", json.dumps(out, ensure_ascii=False))
    text = next(row for row in out["elements"] if row["ref"] == "elem_2")
    assert text["role"] == "textField" and text.get("settable")
    first_plain = next(i for i, row in enumerate(out["elements"]) if not (row.get("actionable") or row.get("settable")))
    assert all(not (row.get("actionable") or row.get("settable")) for row in out["elements"][first_plain:])


def test_nfd_value_from_model_is_stored_nfc(tmp_path: Path) -> None:
    fake = FakePeekaboo([_raw("out3/see1.json")])
    tools = _tools(tmp_path, fake)
    tools.ax_snapshot({"window_id": 3785})
    preview = tools.ax_preview({"window_id": 3785, "ref": "elem_2", "action": "set_value", "value": unicodedata.normalize("NFD", TYPED)})
    assert preview["value_preview"] == TYPED


# ── 함정 ② 창 지정 ─────────────────────────────────────────────────
def test_preview_requires_window_id_and_snapshot(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakePeekaboo([_raw("out3/see1.json")]))
    with pytest.raises(ValueError, match="window_id_required"):
        tools.ax_preview({"ref": "elem_2", "action": "click"})
    with pytest.raises(ValueError, match="ax_snapshot_required"):
        tools.ax_preview({"window_id": 3785, "ref": "elem_2", "action": "click"})


def test_preview_sends_no_action(tmp_path: Path) -> None:
    _, fake, preview = _type_flow(tmp_path, [_raw("out3/see1.json")])
    assert preview["requires_approval"] and preview["window_title"] == "무제 3"
    assert fake.actions() == []


def test_other_document_window_refused_before_sending(tmp_path: Path) -> None:
    """반례(실측 1판): 실행 직전 그 자리에 대표의 기존 문서 창이 있으면 보내지 않는다."""
    tools, fake, preview = _type_flow(tmp_path, [_raw("out3/see1.json"), _raw("out3/see1.json"), _see_with(title=OTHER_DOC)])
    out = tools.execute_preview({"preview_id": preview["preview_id"]})
    assert out["verdict"] == "window_changed" and out["sent"] is False and OTHER_DOC in out["why"]
    assert fake.actions() == []


def test_same_title_but_other_window_refused_before_sending(tmp_path: Path) -> None:
    """반례: 이름은 같은 「무제 3」인데 실제로 찍힌 창 번호(target_receipt)가 다르면 보내지 않는다."""
    tools, fake, preview = _type_flow(tmp_path, [_raw("out3/see1.json"), _raw("out3/see1.json"), _see_with(window_id=3774)])
    out = tools.execute_preview({"preview_id": preview["preview_id"]})
    assert out["verdict"] == "window_changed" and fake.actions() == []


def test_window_changed_between_snapshot_and_preview(tmp_path: Path) -> None:
    fake = FakePeekaboo([_raw("out3/see1.json"), _see_with(title=OTHER_DOC)])
    tools = _tools(tmp_path, fake)
    tools.ax_snapshot({"window_id": 3785})
    with pytest.raises(RuntimeError, match="window_changed"):
        tools.ax_preview({"window_id": 3785, "ref": "elem_2", "action": "click"})


def test_window_gone_before_execute_is_window_changed(tmp_path: Path) -> None:
    """`out1/te_see1.out` 은 실측 WINDOW_NOT_FOUND(후보에 그 기존 문서 창이 보인다)."""
    assert OTHER_DOC in unicodedata.normalize("NFC", _raw("out1/te_see1.out"))
    tools, fake, preview = _type_flow(tmp_path, [_raw("out3/see1.json"), _raw("out3/see1.json"), _raw("out1/te_see1.out")])
    out = tools.execute_preview({"preview_id": preview["preview_id"]})
    assert out["verdict"] == "window_changed" and fake.actions() == []


# ── 함정 ③ 다시 읽기 판정 ──────────────────────────────────────────
def test_rc1_but_text_landed_is_verified(tmp_path: Path) -> None:
    """실측 3판: 타자 rc=1(「확인 안 됨」)인데 다시 읽으니 글자가 있었다 → verified. rc 는 참고로만 싣는다."""
    assert TYPED in _raw("out3/after.txt") and "not verified" in _raw("out3/type.out")
    tools, fake, preview = _type_flow(tmp_path, [_raw("out3/see1.json"), _raw("out3/see1.json"), _raw("out3/see1.json"),
                                                 _see_with(value=TYPED)])
    out = tools.execute_preview({"preview_id": preview["preview_id"]})
    assert out["verdict"] == "verified" and out["verified"] is True and out["peekaboo_rc"] == 1
    sent = fake.actions()
    assert len(sent) == 1 and sent[0][1] == "set-value" and "--window-id" in sent[0] and "3785" in sent[0]


def test_rc0_but_nothing_changed_is_not_verified(tmp_path: Path) -> None:
    """헛성공 막기: rc=0 이어도 다시 읽은 칸에 글이 없으면 not_verified."""
    tools, _, preview = _type_flow(tmp_path, [_raw("out3/see1.json")], action_rc=0, action_out='{"success": true}')
    out = tools.execute_preview({"preview_id": preview["preview_id"]})
    assert out["verdict"] == "not_verified" and out["verified"] is False


def test_after_read_lands_on_other_window_is_window_changed(tmp_path: Path) -> None:
    tools, _, preview = _type_flow(tmp_path, [_raw("out3/see1.json"), _raw("out3/see1.json"), _raw("out3/see1.json"),
                                              _see_with(value=TYPED, window_id=48)])
    assert tools.execute_preview({"preview_id": preview["preview_id"]})["verdict"] == "window_changed"


def test_after_read_window_gone_is_window_changed(tmp_path: Path) -> None:
    tools, _, preview = _type_flow(tmp_path, [_raw("out3/see1.json"), _raw("out3/see1.json"), _raw("out3/see1.json"),
                                              _raw("out1/te_see1.out")])
    assert tools.execute_preview({"preview_id": preview["preview_id"]})["verdict"] == "window_changed"


def test_key_press_verified_only_by_visible_change(tmp_path: Path) -> None:
    fake = FakePeekaboo([_raw("out3/see1.json")])
    tools = _tools(tmp_path, fake)
    tools.ax_snapshot({"window_id": 3785})
    preview = tools.ax_preview({"window_id": 3785, "action": "key", "value": "Cmd+S"})
    assert preview["key_combo"] == "cmd+s"
    out = tools.execute_preview({"preview_id": preview["preview_id"]})
    assert out["verdict"] == "not_verified"  # 창이 그대로면 「먹었다」고 하지 않는다
    assert fake.actions()[0][1:3] == ["press", "cmd+s"]


def test_preview_is_single_use(tmp_path: Path) -> None:
    tools, _, preview = _type_flow(tmp_path, [_raw("out3/see1.json")])
    tools.execute_preview({"preview_id": preview["preview_id"]})
    with pytest.raises(RuntimeError, match="preview_already_used"):
        tools.execute_preview({"preview_id": preview["preview_id"]})
    with pytest.raises(ValueError, match="preview_not_found"):
        tools.execute_preview({"preview_id": "nope"})


# ── 키 ─────────────────────────────────────────────────────────────
def test_key_combo_comma_refused_like_run1() -> None:
    assert "cmd,n" in _raw("out1/te_new.out")
    with pytest.raises(ValueError, match="key_combo_invalid"):
        normalize_key_combo("cmd,n")
    assert normalize_key_combo("cmd+shift+a") == "cmd+shift+a"
    for bad in ("cmd", "cmd++s", "", "cmd+ s+"):
        with pytest.raises(ValueError):
            normalize_key_combo(bad)


# ── 밖으로 안 보냄 · 부르는 길 ─────────────────────────────────────
@pytest.mark.parametrize("args", [("see", "--analyze", "x"), ("agent", "do"), ("mcp", "serve"), ("learn",),
                                  ("see", "--no-remote"), ("see", "--bridge-socket", "/tmp/evil"),
                                  ("permissions", "grant"), ("permissions", "request", "event-synthesizing")])
def test_forbidden_calls_refused(args: tuple[str, ...]) -> None:
    runner = PeekabooRunner("/opt/peekaboo", transport="direct", run=FakePeekaboo([_raw("out3/see1.json")]))
    with pytest.raises(PermissionError):
        runner.argv(*args)


def test_paste_text_with_word_agent_is_allowed() -> None:
    argv = PeekabooRunner("/opt/peekaboo", transport="direct").argv("paste", "--text", "agent mcp 이야기", "--window-id", "1")
    assert argv[-1] == "--no-remote"


@pytest.mark.parametrize("transport", ["direct", "app"])
def test_every_call_in_full_flow_is_local_only(tmp_path: Path, transport: str) -> None:
    """두 길 모두: 모든 부름이 `--json --no-remote` 로 끝나고, AI 분석 · 다리 소켓 · agent/mcp 가 없다. app 길은 늘 같은 꾸러미를
    `open -W -n -g` 로, 출력 파일은 부르기마다 다르다(겹쳐 불러도 섞이지 않게) · 읽은 뒤 지운다."""
    fake = FakePeekaboo([_raw("out3/see1.json"), _raw("out3/see1.json"), _raw("out3/see1.json"), _see_with(value=TYPED)])
    tools = _tools(tmp_path, fake, transport=transport)
    tools.list_open_windows({})
    tools.ax_snapshot({"window_id": 3785})
    preview = tools.ax_preview({"window_id": 3785, "ref": "elem_2", "action": "set_value", "value": TYPED})
    assert tools.execute_preview({"preview_id": preview["preview_id"]})["verdict"] == "verified"
    assert len(fake.argvs) >= 7
    outs = []
    for argv in fake.argvs:
        command = FakePeekaboo.command(argv)
        assert command[-2:] == ["--json", "--no-remote"] and command.count("--no-remote") == 1
        assert "--bridge-socket" not in argv and not any(arg.startswith("--analyze") for arg in argv)
        assert command[0] not in {"agent", "mcp"}
        if transport == "app":
            assert argv[:4] == ["/usr/bin/open", "-W", "-n", "-g"] and argv[argv.index("-a") + 1] == APP
            outs.append(argv[argv.index("--stdout") + 1])
        else:
            assert argv[0] == "/opt/peekaboo"
    if transport == "app":
        assert len(set(outs)) == len(outs)
        assert list((tmp_path / "io").glob("*")) == []


def test_transport_checks() -> None:
    with pytest.raises(ValueError, match="app_missing"):
        PeekabooRunner(transport="app")
    with pytest.raises(ValueError, match="binary_missing"):
        PeekabooRunner(transport="direct")
    with pytest.raises(ValueError, match="transport_unknown"):
        PeekabooRunner("/opt/peekaboo", transport="bridge")


# ── 허락 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("code", ["PERMISSION_ERROR_SCREEN_RECORDING", "PERMISSION_ERROR_ACCESSIBILITY", "PERMISSION_DENIED"])
def test_permission_error_becomes_permission_needed(tmp_path: Path, code: str) -> None:
    """★ 손으로 만든 오류 json — 코드 이름은 v4.9.8 `JSONOutput.swift` ErrorCode 그대로."""
    denied = json.dumps({"success": False, "data": None, "error": {"code": code, "message": "denied"}})
    tools = _tools(tmp_path, FakePeekaboo([denied]))
    with pytest.raises(PermissionNeeded, match="permission_needed"):
        tools.ax_snapshot({"window_id": 3785})


def test_real_outputs_are_not_permission_errors() -> None:
    """헛걸림 0: 실측 출력 전부가 허락 오류로 잘못 걸리지 않는다."""
    for path in sorted(FIX.glob("out*/*")):
        PeekabooRunner.parse(1, path.read_text(encoding="utf-8"))


def test_not_ready_without_helper(tmp_path: Path) -> None:
    for extra in ({"mac_peekaboo_app": str(tmp_path / "missing.app")},
                  {"mac_peekaboo_transport": "direct", "mac_peekaboo_bin": str(tmp_path / "missing")}):
        config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out", **extra)
        tools = MacAutomationTools(config)
        with pytest.raises(RuntimeError, match="not_ready"):
            tools.ax_snapshot({"window_id": 1})
        assert tools.permission_status()["state"] == "not_ready" and tools.status()["ready"] is False


def test_default_transport_is_app() -> None:
    assert JarvisConfig().mac_peekaboo_transport == "app" and JarvisConfig().mac_control_enabled is False


# ── 열기 ───────────────────────────────────────────────────────────
def test_open_path_uses_resolver_and_no_shell(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_open(argv: list[str], **_: Any) -> subprocess.CompletedProcess:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def resolve(raw: str) -> Path:
        if "outside" in raw:
            raise PermissionError("path_outside_allowed_roots")
        return tmp_path / raw

    tools = _tools(tmp_path, FakePeekaboo([_raw("out3/see1.json")]), resolve_path=resolve, open_run=fake_open)
    assert tools.open_path({"path": "텍스트 편집기"})["bundle_id"] == "com.apple.TextEdit"
    tools.open_path({"path": "a.txt", "app": "텍스트 편집기"})
    with pytest.raises(PermissionError, match="path_outside"):
        tools.open_path({"path": "/outside/x"})
    with pytest.raises(PermissionError, match="app_not_allowed"):
        tools.open_path({"path": "a.txt", "app": "Terminal"})
    assert calls[0] == ["/usr/bin/open", "-b", "com.apple.TextEdit"]
    assert calls[1][:3] == ["/usr/bin/open", "-b", "com.apple.TextEdit"] and calls[1][3] == "--"


# ── 복사해 읽기 ────────────────────────────────────────────────────
def test_copy_reads_element_values_without_keys(tmp_path: Path) -> None:
    fake = FakePeekaboo([_see_with(value=TYPED)])
    out = _tools(tmp_path, fake).copy_from_window({"window_id": 3785})
    assert TYPED in out["text"] and out["read_by"] == "element_values" and fake.actions() == []


# ── OS 문 · 등급 ───────────────────────────────────────────────────
def test_platform_gate() -> None:
    assert not tool_runs_here("mac_execute_preview", "win32") and tool_runs_here("mac_execute_preview", "darwin")
    assert not tool_runs_here("windows_execute_preview", "darwin") and tool_runs_here("windows_execute_preview", "win32")


def test_hidden_from_model_while_disabled(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakePeekaboo([_raw("out3/see1.json")]))
    assert tools.config.mac_control_enabled is False and tools.active_ollama_tools == []
    tools.config.mac_control_enabled = True
    assert {t["function"]["name"] for t in tools.active_ollama_tools} == tools.names


def test_risk_levels(tmp_path: Path) -> None:
    from alture_jarvis.models import RiskLevel

    registered: dict[str, Any] = {}

    class Gateway:
        def register(self, spec: Any) -> None:
            registered[spec.name] = spec

    _tools(tmp_path, FakePeekaboo([_raw("out3/see1.json")])).register(Gateway())  # type: ignore[arg-type]
    levels = {name: spec.risk_level for name, spec in registered.items()}
    assert levels["mac_execute_preview"] == levels["mac_open_path"] == RiskLevel.L2
    assert levels["mac_list_open_windows"] == levels["mac_ax_snapshot"] == RiskLevel.L0
    assert all(not spec.enabled for spec in registered.values())  # 기본 꺼짐


def test_fixture_untouched_by_tests() -> None:
    """반례는 사본에서만 만든다 — 실측 파일은 그대로."""
    data = _see1()
    before = copy.deepcopy(data)
    _see_with(title=OTHER_DOC, value=TYPED)
    assert _see1() == before


def _empty_text_see() -> str:
    """실측 see1 에서 글 칸 값을 비우고 창 이름과 같은 글만 남긴 것 — 요소 값으로는 읽을 글이 없다."""
    data = _see1()
    data["data"]["ui_elements"] = [row for row in data["data"]["ui_elements"] if row.get("role") != "textField"
                                   and unicodedata.normalize("NFC", str(row.get("value") or "")) in {"", "무제 3"}]
    return json.dumps(data, ensure_ascii=False)


def test_copy_fallback_restores_clipboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import macos

    board = ["사람이 복사해 둔 것"]
    reads = iter(["사람이 복사해 둔 것", "복사된 본문"])
    monkeypatch.setattr(macos, "clipboard_read", lambda *a, **k: next(reads))
    monkeypatch.setattr(macos, "clipboard_write", lambda text, *a, **k: board.append(text) or True)
    fake = FakePeekaboo([_empty_text_see()])
    out = _tools(tmp_path, fake).copy_from_window({"window_id": 3785})
    assert out["read_by"] == "select_all_copy" and out["text"] == "복사된 본문"
    assert board[-1] == "사람이 복사해 둔 것"
    assert [argv[1:3] for argv in fake.actions()] == [["press", "cmd+a"], ["press", "cmd+c"]]


def test_copy_fallback_refused_when_clipboard_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import macos

    monkeypatch.setattr(macos, "clipboard_read", lambda *a, **k: None)
    fake = FakePeekaboo([_empty_text_see()])
    with pytest.raises(RuntimeError, match="clipboard_unreadable"):
        _tools(tmp_path, fake).copy_from_window({"window_id": 3785})
    assert fake.actions() == []



# ── 허락 켜기 돕기(주력 세션 11-16 요청) ──────────────────────────
@pytest.mark.parametrize("screen,control,state,missing", [
    (True, True, "ready", []),
    (False, True, "permission_needed", ["화면 및 시스템 오디오 녹음"]),
    (True, False, "permission_needed", ["기기 제어 및 데이터 접근"]),
])
def test_permission_status(tmp_path: Path, screen: bool, control: bool, state: str, missing: list[str]) -> None:
    fake = FakePeekaboo([_raw("out3/see1.json")])
    fake.permissions_out = _perms(screen, control)
    out = _tools(tmp_path, fake, transport="app").permission_status()
    assert out["state"] == state and out["missing"] == missing
    assert FakePeekaboo.command(fake.argvs[-1]) == ["permissions", "status", "--json", "--no-remote"]


def test_permission_status_unknown_shape_is_not_guessed(tmp_path: Path) -> None:
    fake = FakePeekaboo([_raw("out3/see1.json")])
    fake.permissions_out = json.dumps({"success": True, "data": {"something": "else"}})
    assert _tools(tmp_path, fake).permission_status()["state"] == "unknown"


def test_permission_needed_note_uses_macos27_names(tmp_path: Path) -> None:
    denied = json.dumps({"success": False, "data": None, "error": {"code": "PERMISSION_ERROR_ACCESSIBILITY", "message": "x"}})
    with pytest.raises(PermissionNeeded, match="기기 제어 및 데이터 접근"):
        _tools(tmp_path, FakePeekaboo([denied])).ax_snapshot({"window_id": 3785})
    denied = json.dumps({"success": False, "data": None, "error": {"code": "PERMISSION_ERROR_SCREEN_RECORDING", "message": "x"}})
    with pytest.raises(PermissionNeeded, match="화면 및 시스템 오디오 녹음"):
        _tools(tmp_path, FakePeekaboo([denied])).ax_snapshot({"window_id": 3785})


def test_permission_setup_steps(tmp_path: Path) -> None:
    opened: list[list[str]] = []

    def fake_open(argv: list[str], **_: Any) -> subprocess.CompletedProcess:
        opened.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    fake = FakePeekaboo([_raw("out3/see1.json")])
    fake.permissions_out = json.dumps({"success": True, "data": {"action": "request-screen-recording", "granted": False}})
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out", mac_peekaboo_app=APP)
    runner = PeekabooRunner(transport="app", app_bundle=APP, io_dir=tmp_path / "io", run=fake)
    tools = MacAutomationTools(config, runner=runner, open_run=fake_open, wait_for_hands=lambda what: None)
    asked = tools.permission_setup("request")
    assert set(asked["asked"]) == {"screen-recording", "accessibility"}
    assert [FakePeekaboo.command(argv)[:3] for argv in fake.argvs] == [["permissions", "request", "screen-recording"],
                                                                        ["permissions", "request", "accessibility"]]
    tools.permission_setup("open_settings")
    assert [argv[1] for argv in opened] == [
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"]
    tools.permission_setup("reveal")
    assert opened[-1] == ["/usr/bin/open", "-R", APP]
    with pytest.raises(ValueError, match="step_unknown"):
        tools.permission_setup("grant_everything")


def test_health_mac_control_only_on_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    from alture_jarvis import runtime as runtime_module

    calls = []
    fake_self = types.SimpleNamespace(
        config=types.SimpleNamespace(mac_control_enabled=True),
        mac_automation=types.SimpleNamespace(permission_status=lambda: calls.append(1) or {"state": "permission_needed"}),
    )
    health = runtime_module.JarvisRuntime._mac_control_health
    monkeypatch.setattr(runtime_module.sys, "platform", "win32")
    assert health(fake_self) == {}  # 윈도우 /health 는 그대로
    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
    assert health(fake_self) == {"mac_control": "permission_needed"}
    assert health(fake_self) == {"mac_control": "permission_needed"} and len(calls) == 1  # 30초 안은 앞 답
    fake_self.config.mac_control_enabled = False
    assert health(fake_self) == {"mac_control": "off"}
