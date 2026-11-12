"""맥에서 손자리가 만든 .md 를 누르면 Xcode 가 뒤에서 한참 뜨던 것 (2026-11-08 대표 맥)."""
from __future__ import annotations

import subprocess

from alture_jarvis import file_open


def _run_with(handler: str, calls: list):
    def run(args, **_k):
        calls.append(list(args))
        if args[0] == "osascript":
            return subprocess.CompletedProcess(args, 0, stdout=handler + "\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    return run


def test_text_file_owned_by_xcode_opens_in_textedit(tmp_path) -> None:
    calls: list = []
    popped: list = []
    target = tmp_path / "보고.md"
    target.write_text("# t", encoding="utf-8")
    how = file_open._open_on_mac(str(target), popen=lambda a, **k: popped.append(a), run=_run_with("/Applications/Xcode.app", calls))
    assert how == "notepad" and popped == [["open", "-e", str(target)]]
    assert not any(c[0] == "open" for c in calls), "Xcode 로 여는 `open` 은 부르지 않는다"


def test_text_file_with_light_default_opens_normally(tmp_path) -> None:
    calls: list = []
    target = tmp_path / "보고.md"
    target.write_text("# t", encoding="utf-8")
    how = file_open._open_on_mac(str(target), popen=lambda a, **k: None, run=_run_with("/Applications/Typora.app", calls))
    assert how == "app" and calls[-1] == ["open", str(target)]


def test_non_text_file_does_not_ask(tmp_path) -> None:
    calls: list = []
    target = tmp_path / "표.xlsx"
    target.write_bytes(b"x")
    file_open._open_on_mac(str(target), popen=lambda a, **k: None, run=_run_with("/Applications/Xcode.app", calls))
    assert [c[0] for c in calls] == ["open"]
