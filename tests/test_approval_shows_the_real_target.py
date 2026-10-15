"""승인 카드는 **실제 경로와 어디에 쓰는지**를 보여 준다 (2026-09-24).

스토어 촬영에서 카드에 `"path": "바탕화면/회의 메모.txt"` 가 날것으로 떴다 — 진짜 바탕화면인지 작업 폴더 안의 「바탕화면」
폴더인지 사람이 알 수 없었다. 판단할 수 없는 승인은 승인이 아니다. 인자는 그대로 둔다(승인 뒤 그대로 재실행되는 값이다).
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.local_computer import describe_write_target
from alture_jarvis.tool_gateway import ToolGateway


def test_a_user_folder_alias_is_shown_as_the_real_folder() -> None:
    target = describe_write_target({"path": "바탕화면/회의 메모.txt"})
    assert target["path"] == str(Path.home() / "Desktop" / "회의 메모.txt")
    assert target["label"] == "바탕화면에 쓰기"


def test_a_plain_relative_path_is_the_work_folder() -> None:
    assert describe_write_target({"path": "notes/a.md"})["label"] == "작업 폴더에 쓰기"


def test_an_absolute_path_under_documents_is_named() -> None:
    target = describe_write_target({"path": str(Path.home() / "Documents" / "r.docx")})
    assert target["place"] == "문서" and target["label"] == "문서에 쓰기"


def test_the_gateway_adds_a_target_without_touching_the_arguments() -> None:
    gateway = ToolGateway.__new__(ToolGateway)
    gateway.approval_describers = {"local_write_file": describe_write_target}
    approval = {"tool_name": "local_write_file", "arguments": {"path": "바탕화면/a.txt", "content": "x"}}
    shown = gateway.describe_approval(approval)
    assert shown["arguments"] == approval["arguments"]
    assert shown["target"]["label"] == "바탕화면에 쓰기"
    # ★ 좋은 표본 — 설명 함수가 없는 도구는 그대로.
    other = {"tool_name": "google_gmail_send", "arguments": {"action_id": "a1"}}
    assert gateway.describe_approval(other) == other
