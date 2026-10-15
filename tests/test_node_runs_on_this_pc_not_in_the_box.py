"""자바스크립트는 **이 PC 에서** 돈다 — 상자에서 헤매지 않게 (2026-09-30 코드 벤치).

「node 로 돌리는 test.js 를 만들어 통과시켜」 과제: 이 PC 의 명령 문은 node 를 안 받았고(python·npm 은 받음), 상자는
파이썬·bash 뿐이라 돌릴 길이 아예 없었다. 모델은 상자 안에서 `cd "C:\\Users\\…" && node test.js` 를 돌렸고, 상자는
리눅스 오류만 돌려줘 네 걸음을 헤맸다. 고친 것: ① 명령 문이 node 를 받는다(python 과 같은 규칙) ② 상자가 못 하는 일이면
오류 대신 갈 곳을 댄다(윈도우 경로·없는 실행 파일 — 사실로 가른다).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.sandbox import _box_mismatch_hint


def test_node_runs_a_script_inside_the_workspace(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "test.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setattr("alture_jarvis.local_computer.shutil.which", lambda name: f"C:/node/{name}.exe")

    display, executable = LocalComputerTools._validated_project_command("node test.js", root=tmp_path)

    assert display[0] == "node"
    assert executable == ["C:/node/node.exe", str((tmp_path / "test.js").resolve())]


def test_node_scripts_outside_the_workspace_are_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("alture_jarvis.local_computer.shutil.which", lambda name: f"C:/node/{name}.exe")
    outside = tmp_path.parent / "elsewhere.js"
    with pytest.raises(PermissionError, match="node_script_outside_workspace"):
        LocalComputerTools._validated_project_command(["node", str(outside)], root=tmp_path)


def test_a_missing_node_says_so_in_plain_words(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "test.js").write_text("", encoding="utf-8")
    monkeypatch.setattr("alture_jarvis.local_computer.shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="Node.js 가 없습니다"):
        LocalComputerTools._validated_project_command("node test.js", root=tmp_path)


def test_the_box_points_away_from_windows_paths() -> None:
    hint = _box_mismatch_hint(r'cd "C:\Users\user\Documents\bench\travel_split" && node test.js',
                              "main.sh: line 1: cd: C:\\Users\\user: No such file or directory\n")
    assert "local_run_project_command" in hint and "못 본다" in hint


def test_the_box_points_away_from_programs_it_does_not_have() -> None:
    hint = _box_mismatch_hint("node test.js", "/work/abc/main.sh: line 1: node: command not found\n")
    assert "`node` 이 없다" in hint and "local_run_project_command" in hint


def test_an_ordinary_error_gets_no_detour() -> None:
    """역방향 — 파이썬 코드의 평범한 오류(0 나누기)에는 다른 도구로 가라고 하지 않는다."""
    assert _box_mismatch_hint("print(1/0)", "ZeroDivisionError: division by zero\n") == ""
    # 문자열 속 URL 의 `https:/` 는 드라이브 경로가 아니다.
    assert _box_mismatch_hint("url = 'https://example.com'", "ValueError: bad\n") == ""


def test_a_label_copied_from_the_tool_description_is_dropped(tmp_path: Path, monkeypatch) -> None:
    """코드 벤치 2차: 설명 표의 이름표를 베껴 `['js','node','test.js']`·`script python …` 로 보내 두 번 막혔다 — 떼고 받는다."""
    (tmp_path / "test.js").write_text("", encoding="utf-8")
    monkeypatch.setattr("alture_jarvis.local_computer.shutil.which", lambda name: f"C:/node/{name}.exe")
    display, _ = LocalComputerTools._validated_project_command(["js", "node", "test.js"], root=tmp_path)
    assert display[0] == "node"
    # 진짜 프로그램 이름은 이름표가 아니다 — 그대로 둔다.
    display, _ = LocalComputerTools._validated_project_command(["git", "status"], root=tmp_path)
    assert display[:2] == ["git", "status"]


def test_clicks_on_a_page_inside_this_pc_need_no_approval() -> None:
    """자기가 만든 앱의 「추가」(폼 submit)가 「되돌릴 수 없는 동작 — 승인」으로 막혔다. 이 PC 안의 페이지는 아무 데도 안 간다."""
    from types import SimpleNamespace

    from alture_jarvis.browser import _is_local_page

    for url in ("file:///C:/Users/me/app/index.html", "http://127.0.0.1:5173/", "http://localhost:3000/x", "http://app.localhost/"):
        assert _is_local_page(SimpleNamespace(url=url)), url
    for url in ("https://www.coupang.com/checkout", "http://192.168.0.10/", "https://localhost.evil.com/"):
        assert not _is_local_page(SimpleNamespace(url=url)), url
