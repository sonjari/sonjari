"""「테스트 파일은 고치지 마」는 **도구가 막는다** — 말로만 전하지 않는다.

★ 2026-09-28 헤르메스 대결 T7 O3: 코딩 사다리 L6 「테스트 파일은 고치지 마」 판에서 모델이 test_pager.py 의 빈 줄을 지우고,
답에는 「들여쓰기만 수정(pytest 구문 오류 해결)」 — pytest 를 한 번도 안 돌린 채 지어낸 이유였다. 금지는 `clause` 로 **모델에게
말만** 했다(사고 R — 안내문은 안 먹는다). 판을 통째로 묶으면 09-03 SWE 사고가 재발하므로 **그 대상만** 막는다.

같이 잡은 구멍: L7 「test_report.py 와 orders.csv 는 고치지 마」는 금지로 **읽히지조차** 않았다(scope "").
과거 실제 요청 1,215개에 돌려 대상이 잡힌 40개는 전부 진짜 테스트 파일 금지였다(헛잡음 0).
"""
from __future__ import annotations

import sys
from pathlib import Path

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.plan import protected_path_hit, protected_write_targets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench" / "coding"))
import ladder  # noqa: E402


def test_every_ladder_task_protects_exactly_what_it_says() -> None:
    for key, task in ladder.TASKS.items():
        targets = protected_write_targets(task["prompt"].replace("{folder}", "C:/x"))
        hit = sorted(name for name in task["seed"] if protected_path_hit(name, targets))
        assert hit == sorted(task.get("protect") or []), key


def test_implementation_files_stay_writable() -> None:
    targets = protected_write_targets(ladder.TASKS["L6_two_bug_pipeline"]["prompt"])
    assert protected_path_hit("pager.py", targets) == ""
    assert protected_path_hit("src/slicer.py", targets) == ""
    assert protected_path_hit("tests/test_pager.py", targets)
    assert protected_path_hit(r"C:\repo\tests\helpers.py", targets)  # tests/ 폴더 안
    assert protected_path_hit("conftest.py", targets)


def test_no_prohibition_no_targets() -> None:
    assert protected_write_targets("test_textutil.py 에도 테스트를 2개 이상 추가하고 pytest 로 확인해.") == {}
    assert protected_write_targets("교보문고에서 파이썬 책 3권을 엑셀로 정리해 줘") == {}
    # 판 전체 금지는 이미 모든 쓰기 손을 막는다 — 여기서 대상을 따로 만들지 않는다.
    assert protected_write_targets("이 판에서는 파일을 수정하지 마") == {}


def test_the_o3_edit_is_refused_and_a_new_test_file_is_not(tmp_path: Path) -> None:
    (tmp_path / "test_pager.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    targets = protected_write_targets(ladder.TASKS["L6_two_bug_pipeline"]["prompt"])
    root = str(tmp_path)

    # O3 가 실제로 한 것 — 있는 테스트 파일을 고침
    assert BrowserAgent._protected_write_hit("local_apply_edit", {"path": "test_pager.py", "old": "\n\n", "new": "\n"}, targets, root)
    assert BrowserAgent._protected_write_hit("local_write_file", {"path": "test_pager.py", "content": ""}, targets, root)
    assert BrowserAgent._protected_write_hit("local_delete_file", {"path": "test_pager.py"}, targets, root)
    # 새 파일을 만드는 것은 고치는 것이 아니다
    assert BrowserAgent._protected_write_hit("local_write_file", {"path": "test_new.py", "content": ""}, targets, root) == ""
    # 구현 파일
    assert BrowserAgent._protected_write_hit("local_apply_edit", {"path": "pager.py"}, targets, root) == ""


def test_named_files_in_l7_are_protected_and_the_new_test_file_is_allowed(tmp_path: Path) -> None:
    for name in ("test_report.py", "orders.csv", "report.py"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    targets = protected_write_targets(ladder.TASKS["L7_compound_report"]["prompt"].replace("{folder}", str(tmp_path)))
    root = str(tmp_path)
    assert BrowserAgent._protected_write_hit("local_apply_edit", {"path": "orders.csv"}, targets, root)
    assert BrowserAgent._protected_write_hit("local_apply_edit", {"path": "test_report.py"}, targets, root)
    assert BrowserAgent._protected_write_hit("local_apply_edit", {"path": "report.py"}, targets, root) == ""
    assert BrowserAgent._protected_write_hit("local_write_file", {"path": "test_cli.py", "content": ""}, targets, root) == ""


def test_the_guard_sits_in_the_tool_loop() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert '"error": "user_protected_file"' in source
    assert "protected_targets = {} if write_forbidden else plan_protected_write_targets(plan_text)" in source


def test_files_listed_with_middle_dots_are_all_protected() -> None:
    """★ 2026-10-01: 「a · b · c 는 고치지 마」에서 마지막 하나만 지켰다 — 가운뎃점이 구분자 목록에 없었다."""
    targets = protected_write_targets("tidy.py 를 완성해. scenekit.py · API.md · test_tidy.py 는 고치지 마.")
    assert sorted(targets["names"]) == ["API.md", "scenekit.py", "test_tidy.py"]
    assert protected_path_hit("tidy.py", targets) == ""
