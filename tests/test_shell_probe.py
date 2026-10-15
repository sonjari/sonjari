"""읽기 전용 셸이 **정말로 읽기 전용인가.**

## 이 파일의 성격

다른 검사 파일이 "되는가"를 보는 것과 달리, 여기는 **"뚫리는가"** 를 본다.
그래서 대부분이 공격 표본이다 — 인터프리터·경로 우회·메타문자·쓰기 하위명령.

## 왜 차단목록이 아니라 허용목록인가

셸에서 "위험한 것만 막자"는 절대 성립하지 않는다:

    powershell -enc <base64>      막을 문자열이 없다
    python -c "import os; ..."    한 줄로 뭐든
    cmd /c "..."                  그 안은 다시 셸이다

그래서 허용목록만 쓰고, **그 목록에 인터프리터를 하나라도 넣으면 그 순간
전부 무의미해진다.** 이 파일이 그 사실을 못으로 박는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.shell_probe import ALLOWED, FORBIDDEN_EVER, ShellProbe


def _probe(tmp_path: Path) -> ShellProbe:
    return ShellProbe(JarvisConfig(runtime_root=tmp_path), EventBus())


# ── ★ 인터프리터는 영원히 안 된다 ───────────────────────────────────────────


def test_no_interpreter_is_ever_allowed() -> None:
    """★ 이 파일에서 가장 중요한 검사.

    허용목록에 셸이나 임의 코드를 여는 것이 하나라도 들어오면, 나머지 방벽이
    전부 무의미해진다. 목록을 늘리는 사람은 여기서 걸린다.
    """
    for name in ALLOWED:
        assert name not in FORBIDDEN_EVER, f"{name} 은 임의 코드를 열 수 있다"


@pytest.mark.parametrize(
    "command",
    ["powershell", "pwsh", "cmd", "python", "python3", "node", "bash", "wsl", "mshta", "rundll32"],
)
def test_interpreters_are_refused(tmp_path: Path, command: str) -> None:
    why = ShellProbe.check(command, ["-c", "print(1)"])
    assert "interpreter_forbidden" in why, f"{command} 이 통과했다"


def test_the_refusal_explains_why_not_just_no(tmp_path: Path) -> None:
    """거절만 하고 이유를 안 말하면 모델이 같은 것을 다시 시도한다."""
    why = ShellProbe.check("powershell", ["-enc", "AAA"])
    assert "허용목록" in why and "다시 말해" in why


# ── 경로로 목록을 우회할 수 없다 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "C:/Windows/System32/cmd.exe",
        "powershell.exe",
        "POWERSHELL",
        '"C:\\Windows\\System32\\cmd.exe"',
    ],
)
def test_a_full_path_does_not_smuggle_an_interpreter(command: str) -> None:
    """★ 이름만 보면 경로로 우회된다. 밑동만 떼서 본다."""
    assert "interpreter_forbidden" in ShellProbe.check(command, [])


def test_an_unknown_program_is_refused_even_if_harmless() -> None:
    """허용목록 방식의 요점 — 모르는 것은 전부 거절이다."""
    why = ShellProbe.check("notepad", [])
    assert "not_allowed" in why


# ── 셸 메타문자 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "arg",
    ["a|b", "a>b", "a&&b", "a;b", "$(whoami)", "`whoami`", "a\nb", 'a"b'],
)
def test_shell_characters_in_arguments_are_refused(arg: str) -> None:
    """`shell=False` 라 이미 안전하지만, 이 줄은 **마지막 방벽**이다.

    나중에 누가 `shell=True` 로 바꾸거나 인자를 문자열로 합치는 순간 여기가
    유일하게 남는 방벽이 된다. 방벽을 하나만 두면 그것이 무너질 때 아무것도 안 남는다.
    """
    assert "argument_has_shell_characters" in ShellProbe.check("tasklist", [arg])


# ── 쓰기 하위명령 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "args",
    [["push"], ["commit", "-m", "x"], ["reset", "--hard"], ["clean", "-fd"], ["checkout", "main"]],
)
def test_git_write_subcommands_are_refused(args: list[str]) -> None:
    """★ `git` 은 허용목록에 있지만 `git push` 는 쓰기다. 하위명령을 따진다."""
    assert "subcommand_not_allowed" in ShellProbe.check("git", args)


@pytest.mark.parametrize("args", [["status"], ["log", "--oneline"], ["rev-parse", "HEAD"], ["diff"]])
def test_git_read_subcommands_pass(args: list[str]) -> None:
    assert ShellProbe.check("git", args) == ""


def test_service_control_only_allows_query() -> None:
    """`sc query` 는 읽기, `sc stop` 은 서비스를 죽인다."""
    assert ShellProbe.check("sc", ["query", "W32Time"]) == ""
    assert "subcommand_not_allowed" in ShellProbe.check("sc", ["stop", "W32Time"])
    assert "subcommand_not_allowed" in ShellProbe.check("sc", ["delete", "W32Time"])


def test_scheduled_tasks_cannot_be_run_or_deleted() -> None:
    """`schtasks /Run` 은 오늘 밤 내가 손으로 쓴 명령이다 — 모델에게는 안 준다."""
    assert ShellProbe.check("schtasks", ["/query"]) == ""
    assert "subcommand_not_allowed" in ShellProbe.check("schtasks", ["/Run", "/TN", "x"])
    assert "subcommand_not_allowed" in ShellProbe.check("schtasks", ["/Delete", "/TN", "x"])


def test_a_subcommand_is_needed_when_the_program_has_write_paths() -> None:
    """하위명령 없이 부르면 통과시키면 안 된다 — 기본 동작이 쓰기일 수 있다."""
    assert "subcommand_not_allowed" in ShellProbe.check("git", [])
    assert "subcommand_not_allowed" in ShellProbe.check("sc", [])


def test_a_read_only_program_needs_no_subcommand() -> None:
    assert ShellProbe.check("tasklist", []) == ""
    assert ShellProbe.check("netstat", ["-ano"]) == ""


# ── 실제로 돌려 본다 ────────────────────────────────────────────────────────


def test_a_refused_command_never_runs(tmp_path: Path) -> None:
    out = _probe(tmp_path).run({"command": "powershell", "args": ["-c", "1"]})
    assert out["ok"] is False
    assert "stdout" not in out, "거절했는데 무언가 돌았다"


def test_a_string_of_args_is_refused_rather_than_split(tmp_path: Path) -> None:
    """★ 문자열을 쪼개는 순간 따옴표 규칙을 우리가 다시 만들게 되고, 그것이 곧 셸이다."""
    out = _probe(tmp_path).run({"command": "tasklist", "args": "/FI \"IMAGENAME eq x\""})
    assert out["ok"] is False
    assert "args_must_be_a_list" in out["error"]


def test_an_allowed_command_actually_runs(tmp_path: Path) -> None:
    out = _probe(tmp_path).run({"command": "where", "args": ["where"]})
    assert out["ok"] is True
    assert out["exit_code"] == 0
    assert "where" in out["stdout"].lower()


def test_shell_characters_are_literal_not_interpreted(tmp_path: Path) -> None:
    """★ `shell=False` 의 증거. 만약 셸을 거쳤다면 리디렉션이 일어나 파일이 생긴다.

    메타문자 검사를 통과할 수 있는 형태로 시험한다 — `^` 는 목록에 없지만
    cmd 에서는 이스케이프 문자다. 셸이 없으면 그냥 글자다.
    """
    target = tmp_path / "should_not_exist.txt"
    out = _probe(tmp_path).run({"command": "where", "args": [f"^{target}"]})
    # 없는 것을 찾으니 실패하는 게 정상이다. 요점은 **파일이 안 생겼다**는 것.
    assert out["ok"] is True
    assert not target.exists(), "셸을 거쳐 리디렉션이 일어났다"


def test_the_tool_schema_only_offers_the_allowlist(tmp_path: Path) -> None:
    """모델이 고를 수 있는 것이 enum 으로 묶여 있는가."""
    spec = _probe(tmp_path).ollama_tools[0]["function"]
    assert sorted(spec["parameters"]["properties"]["command"]["enum"]) == sorted(ALLOWED)


def test_long_output_says_it_was_cut(tmp_path: Path) -> None:
    """잘랐으면 잘랐다고 말한다 — 조용히 자르면 없던 것과 구별이 안 된다."""
    from alture_jarvis.shell_probe import MAX_OUTPUT_CHARS

    text, cut = ShellProbe._clip("x" * (MAX_OUTPUT_CHARS + 10))
    assert cut is True and len(text) == MAX_OUTPUT_CHARS
    assert ShellProbe._clip("짧다")[1] is False
