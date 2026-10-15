"""명령 출력과 도구 결과에서 아는 비밀 값은 가려진다 · 사본에는 지워질 빈 데이터 자리를 준다 (2026-10-11).

손자리가 돌린 명령은 무엇이든 찍을 수 있다 — 오류 글에 API 키가 섞여 나오면 그 출력은 모델·걸음 장부·답으로 간다.
값을 **아는** 것(넘기는 환경의 비밀 이름 값 · 작업 폴더의 `.env` · 손자리 자신의 토큰)은 글자 그대로 찾아 가리고,
모르는 것은 세기만 한다. 값은 명령에 그대로 전달된다.

표본의 값은 전부 여기서 지어 붙인 글자다.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import local_computer, project_env
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.google_workspace import GoogleWorkspace
from alture_jarvis.jobs import JobStore
from alture_jarvis.known_secrets import KnownSecrets, marker
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec

FAKE_KEY = "zz-" + "Qr7Lm2Xp" * 5
FAKE_PASSWORD = "Tr0ub4dor&3-fixture"


def _stack(tmp_path: Path) -> tuple[Path, LocalComputerTools, ToolGateway, KnownSecrets]:
    project = tmp_path / "project"
    project.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    local = LocalComputerTools(config)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    local.register(gateway)
    known = KnownSecrets()
    local.known_secrets = known
    gateway.known_secrets = known
    return project, local, gateway, known


def _fake_output(monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str = "") -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake(executable, *, cwd, env, timeout_sec, **_kwargs):  # type: ignore[no-untyped-def]
        seen["env"] = dict(env)
        seen["scratch_exists_while_running"] = Path(env["JARVIS_RUNTIME_ROOT"]).is_dir()
        seen["scratch_was_empty"] = not any(Path(env["JARVIS_RUNTIME_ROOT"]).iterdir())
        return 0, stdout.encode("utf-8"), stderr.encode("utf-8"), False

    monkeypatch.setattr(local_computer, "run_captured", fake)
    return seen


# --- 명령 출력 ------------------------------------------------------------------

def test_a_value_the_command_was_given_is_hidden_when_it_prints_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """진짜로 자식을 띄운다 — 값은 자식에게 가고(그래서 찍을 수 있다), 돌아온 글에서만 가려진다."""
    monkeypatch.setenv("FIXTURE_SERVICE_API_KEY", FAKE_KEY)
    project, _, gateway, _ = _stack(tmp_path)

    result = gateway.execute(
        "local_run_project_command",
        {"path": str(project), "timeout_sec": 30,
         "command": ["python", "-c", "import os; v = os.environ['FIXTURE_SERVICE_API_KEY']; print('len', len(v)); print('Error: bad key', v)"]},
        job_id="code-1",
    )

    out = str(result.result.get("stdout"))
    assert result.result["exit_code"] == 0, result.result
    assert f"len {len(FAKE_KEY)}" in out, "명령은 진짜 값을 받았다"
    assert FAKE_KEY not in str(result.result), result.result
    assert marker("FIXTURE_SERVICE_API_KEY") in out
    assert result.result["secrets_hidden"] == 1 and "가렸다" in result.result["secrets_note"]


def test_the_shell_door_hides_it_too_and_dumping_the_environment_shows_names_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIXTURE_DB_PASSWORD", FAKE_PASSWORD)
    _, local, _, _ = _stack(tmp_path)
    _fake_output(monkeypatch, f"FIXTURE_DB_PASSWORD={FAKE_PASSWORD}\nPATH=C:\\Windows\nUSERNAME=someone\n")

    result = local.run_shell({"command": "set", "timeout_sec": 10, "__job_id": "shell-1"})

    assert FAKE_PASSWORD not in str(result)
    assert f"FIXTURE_DB_PASSWORD={marker('FIXTURE_DB_PASSWORD')}" in result["stdout"]
    assert "PATH=C:\\Windows" in result["stdout"] and "USERNAME=someone" in result["stdout"]
    assert result["secrets_hidden"] == 1


def test_the_error_stream_is_covered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIXTURE_TOKEN", FAKE_KEY)
    _, local, _, _ = _stack(tmp_path)
    _fake_output(monkeypatch, "", f"Traceback…\nAuthError: token {FAKE_KEY} rejected\n")

    result = local.run_shell({"command": "python app.py", "timeout_sec": 10, "__job_id": "shell-1"})

    assert FAKE_KEY not in result["stderr"] and marker("FIXTURE_TOKEN") in result["stderr"]


def test_hiding_happens_before_the_output_is_cut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """끝 16,000자만 남길 때, 잘리는 자리에 걸친 값의 꼬리가 남으면 안 된다."""
    monkeypatch.setenv("FIXTURE_TOKEN", FAKE_KEY)
    _, local, _, _ = _stack(tmp_path)
    tail = "y" * (16_000 - 12)
    _fake_output(monkeypatch, "x" * 5_000 + FAKE_KEY + tail)

    result = local.run_shell({"command": "python noisy.py", "timeout_sec": 10, "__job_id": "shell-1"})

    assert len(result["stdout"]) == 16_000
    assert FAKE_KEY[-12:] not in result["stdout"], "값의 뒷부분이 잘린 채 남았다"


def test_a_clean_output_gains_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIXTURE_TOKEN", FAKE_KEY)
    _, local, _, _ = _stack(tmp_path)
    _fake_output(monkeypatch, "3 passed in 0.12s\ncommit 9f2c1e7a4b8d0c3e5f6a7b8c9d0e1f2a3b4c5d6e\n")

    result = local.run_shell({"command": "pytest -q", "timeout_sec": 10, "__job_id": "shell-1"})

    assert result["stdout"].startswith("3 passed")
    assert not {"secrets_hidden", "secrets_note", "secret_looking", "secret_looking_note"} & set(result)


def test_an_unknown_random_looking_string_is_flagged_and_left_as_it_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, local, _, _ = _stack(tmp_path)
    unknown = "Zx9Kq2Lm8Vb4Nc7Xd1Fg6Hj3Pk5Rt0Ws" + "Ay8Bu2"
    _fake_output(monkeypatch, f"generated: {unknown}\n")

    result = local.run_shell({"command": "python make_token.py", "timeout_sec": 10, "__job_id": "shell-1"})

    assert unknown in result["stdout"], "값을 모르는 것은 지우지 않는다"
    assert result["secret_looking"] == 1 and "옮겨 적지" in result["secret_looking_note"]
    assert "secrets_hidden" not in result


def test_without_the_collection_the_door_behaves_as_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIXTURE_TOKEN", FAKE_KEY)
    _, local, _, _ = _stack(tmp_path)
    local.known_secrets = None
    _fake_output(monkeypatch, f"token {FAKE_KEY}\n")

    result = local.run_shell({"command": "python app.py", "timeout_sec": 10, "__job_id": "shell-1"})

    assert FAKE_KEY in result["stdout"] and "secrets_hidden" not in result


# --- 작업 폴더의 .env ------------------------------------------------------------

def test_what_the_project_env_file_holds_is_hidden_in_command_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, local, _, _ = _stack(tmp_path)
    # 셸 명령은 그 일의 작업 폴더에서 돈다 — `.env` 도 거기에 있다.
    workspace = local.job_workspace("shell-1", create=True)
    (workspace / ".env").write_text(f"PAYMENT_SECRET_KEY={FAKE_KEY}\nPORT=3000\n", encoding="utf-8")
    _fake_output(monkeypatch, f"connecting with {FAKE_KEY} on port 3000\n")

    result = local.run_shell({"command": "python app.py", "timeout_sec": 10, "__job_id": "shell-1"})

    assert FAKE_KEY not in result["stdout"]
    assert marker("PAYMENT_SECRET_KEY") in result["stdout"] and "port 3000" in result["stdout"]


def test_reading_the_env_file_shows_names_and_plain_settings_only(tmp_path: Path) -> None:
    project, _, gateway, _ = _stack(tmp_path)
    (project / "service.env").write_text(
        f"PAYMENT_SECRET_KEY={FAKE_KEY}\nDB_PASSWORD={FAKE_PASSWORD}\nPORT=3000\nAPP_NAME=fixture-service\n", encoding="utf-8",
    )

    result = gateway.execute("local_read_text_file", {"path": str(project / "service.env")}, job_id="read-1")

    shown = str(result.result)
    assert result.ok is True, result.error
    assert FAKE_KEY not in shown and FAKE_PASSWORD not in shown
    assert "PAYMENT_SECRET_KEY=" in shown and "PORT=3000" in shown and "APP_NAME=fixture-service" in shown


# --- 도구 관문 -------------------------------------------------------------------

def _echo_tool(gateway: ToolGateway, name: str, handler: Any) -> None:
    gateway.register(ToolSpec(name=name, description="fixture", parameters={"type": "object", "properties": {}},
                              risk_level=RiskLevel.L0, handler=handler))


def test_any_tool_result_passes_the_same_door(tmp_path: Path) -> None:
    _, _, gateway, known = _stack(tmp_path)
    known.learn(FAKE_KEY, "FIXTURE_API_KEY")
    _echo_tool(gateway, "fixture_page", lambda args: {"text": f"your key is {FAKE_KEY}", "rows": [FAKE_KEY, "ok"], "count": 2})

    result = gateway.execute("fixture_page", {}, job_id="any-1")

    assert FAKE_KEY not in str(result.result)
    assert result.result["text"] == f"your key is {marker('FIXTURE_API_KEY')}" and result.result["count"] == 2


def test_a_failure_message_is_covered(tmp_path: Path) -> None:
    _, _, gateway, known = _stack(tmp_path)
    known.learn(FAKE_KEY, "FIXTURE_API_KEY")

    def broken(args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(f"401 for key {FAKE_KEY}")

    _echo_tool(gateway, "fixture_broken", broken)

    result = gateway.execute("fixture_broken", {}, job_id="any-1")

    assert result.ok is False and FAKE_KEY not in str(result.error) and marker("FIXTURE_API_KEY") in str(result.error)


def test_a_clean_result_is_the_very_object_the_tool_returned(tmp_path: Path) -> None:
    _, _, gateway, known = _stack(tmp_path)
    known.learn(FAKE_KEY, "FIXTURE_API_KEY")
    made = {"text": "nothing to hide"}
    _echo_tool(gateway, "fixture_clean", lambda args: made)

    assert gateway.execute("fixture_clean", {}, job_id="any-1").result is made


def test_the_runtime_hangs_the_collection_on_every_door() -> None:
    source = inspect.getsource(JarvisRuntime.__init__)
    for line in ("self.gateway.known_secrets = self.known_secrets", "self.local_computer.known_secrets = self.known_secrets",
                 "self.google.secret_sink = self.known_secrets.learn", "self.known_secrets.learn_environment(dict(os.environ))"):
        assert line in source, line
    for owner in ("run_project_command", "run_shell"):
        assert "_run_for_model(" in inspect.getsource(getattr(LocalComputerTools, owner)), owner


def test_google_tokens_are_told_to_the_collection() -> None:
    google = object.__new__(GoogleWorkspace)
    heard: list[tuple[str, str]] = []
    google.secret_sink = lambda value, label: heard.append((value, label))

    google._tell_secrets({"access_token": "fixture-access-token-0001", "refresh_token": "fixture-refresh-token-0002", "expires_at": 1})

    assert heard[:2] == [("fixture-access-token-0001", "구글 토큰"), ("fixture-refresh-token-0002", "구글 토큰")]


# --- 사본에는 지워질 빈 데이터 자리 -----------------------------------------------

def test_a_command_gets_a_fresh_empty_home_that_is_gone_afterwards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "the-running-app"))
    _, local, _, _ = _stack(tmp_path)
    seen = _fake_output(monkeypatch, "ok\n")

    local.run_shell({"command": "python app.py", "timeout_sec": 10, "__job_id": "shell-1"})
    first = seen["env"]["JARVIS_RUNTIME_ROOT"]
    local.run_shell({"command": "python app.py", "timeout_sec": 10, "__job_id": "shell-1"})

    assert seen["scratch_exists_while_running"] and seen["scratch_was_empty"]
    assert first != str(tmp_path / "the-running-app"), "돌고 있는 앱의 자리는 넘기지 않는다"
    assert seen["env"]["JARVIS_RUNTIME_ROOT"] != first, "명령마다 새 자리다"
    assert not Path(first).exists() and not Path(seen["env"]["JARVIS_RUNTIME_ROOT"]).exists(), "끝나면 지운다"
    assert Path(seen["env"]["JARVIS_BACKUP_DIR"]).parent == Path(seen["env"]["JARVIS_RUNTIME_ROOT"])


def test_the_scratch_home_leaves_the_given_mapping_alone() -> None:
    given = {"PATH": "p"}
    with project_env.scratch_home(given) as child:
        folder = Path(child["JARVIS_RUNTIME_ROOT"])
        assert folder.is_dir() and child["PATH"] == "p"
        (folder / "left-behind.db").write_text("x", encoding="utf-8")
    assert given == {"PATH": "p"} and not folder.exists()
