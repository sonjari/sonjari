from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ApprovalRequired, JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.tool_gateway import ToolGateway


def _stack(tmp_path: Path) -> tuple[LocalComputerTools, ToolGateway]:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed),
        local_computer_enabled=True,
    )
    local = LocalComputerTools(config)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    local.register(gateway)
    return local, gateway


def test_a_relative_write_stays_in_the_job_workspace_and_undo_removes_it(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)

    result = gateway.execute(
        "local_write_file", {"path": "notes/결과.md", "content": "첫 결과"}, job_id="job-1"
    )

    target = local.job_workspace("job-1") / "notes" / "결과.md"
    assert result.ok is True
    assert result.risk_level == "L1"
    assert target.read_text(encoding="utf-8") == "첫 결과"
    assert result.result["proof"]["after"]["sha256"]
    offers = gateway.store.list_undo_offers()
    assert len(offers) == 1

    undone = gateway.undo(offers[0]["undo_id"])

    assert undone["ok"] is True
    assert undone["verified"] is True
    assert not target.exists()


def test_an_edit_and_undo_restore_the_original_bytes_and_encoding(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)
    target = local.job_workspace("job-cp949", create=True) / "기록.txt"
    original = "점수: 80점\r\n".encode("cp949")
    target.write_bytes(original)

    changed = gateway.execute(
        "local_apply_edit",
        {"path": "기록.txt", "old": "80점", "new": "95점"},
        job_id="job-cp949",
    )

    assert changed.ok is True
    assert target.read_bytes().decode("cp949") == "점수: 95점\r\n"
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]
    assert gateway.undo(undo_id)["verified"] is True
    assert target.read_bytes() == original


def test_editing_plain_utf8_does_not_add_a_bom(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)
    target = local.job_workspace("job-utf8", create=True) / "plain.txt"
    target.write_bytes("값: 이전\n".encode("utf-8"))

    result = gateway.execute(
        "local_apply_edit",
        {"path": "plain.txt", "old": "이전", "new": "이후"},
        job_id="job-utf8",
    )

    assert result.ok is True
    assert result.result["encoding"] == "utf-8"
    assert target.read_bytes() == "값: 이후\n".encode("utf-8")
    assert not target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_an_absolute_write_needs_approval_and_rejects_target_drift(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)
    target = local.allowed_roots[0] / "사용자님.txt"
    target.write_text("승인 전", encoding="utf-8")
    arguments = {"path": str(target), "content": "승인한 내용"}

    with pytest.raises(ApprovalRequired) as asked:
        gateway.execute("local_write_file", arguments, job_id="job-2")

    approval = gateway.store.list_approvals(status="pending")[0]
    # 내부 잡 문맥은 모델 인자나 승인 카드로 새지 않는다.
    assert "__job_id" not in approval["arguments"]
    gateway.decide(asked.value.nonce, True)
    target.write_text("승인 뒤 사람이 고침", encoding="utf-8")

    rejected = gateway.execute("local_write_file", arguments, job_id="job-2")

    assert rejected.ok is False
    assert rejected.status == "proof_target_drifted"
    assert target.read_text(encoding="utf-8") == "승인 뒤 사람이 고침"


def test_an_approved_absolute_write_can_be_undone_to_the_exact_original(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)
    target = local.allowed_roots[0] / "기존.txt"
    original = b"before\r\n"
    target.write_bytes(original)
    arguments = {"path": str(target), "content": "after\n"}

    with pytest.raises(ApprovalRequired) as asked:
        gateway.execute("local_write_file", arguments, job_id="job-3")
    gateway.decide(asked.value.nonce, True)
    written = gateway.execute("local_write_file", arguments, job_id="job-3")

    assert written.ok is True
    assert written.risk_level == "L2"
    assert written.result["proof"]["approval"]["consumed"] is True
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]
    assert gateway.undo(undo_id)["verified"] is True
    assert target.read_bytes() == original


def test_delete_is_always_approved_and_undo_restores_the_file(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)
    target = local.job_workspace("job-delete", create=True) / "없앨.txt"
    target.write_bytes(b"keep me")
    arguments = {"path": "없앨.txt"}

    with pytest.raises(ApprovalRequired) as asked:
        gateway.execute("local_delete_file", arguments, job_id="job-delete")
    gateway.decide(asked.value.nonce, True)
    deleted = gateway.execute("local_delete_file", arguments, job_id="job-delete")

    assert deleted.ok is True
    assert deleted.risk_level == "L2"
    assert not target.exists()
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]
    assert gateway.undo(undo_id)["verified"] is True
    assert target.read_bytes() == b"keep me"


def test_workspace_is_allowed_even_when_an_old_env_allowlist_overrides_defaults(tmp_path: Path) -> None:
    local, _ = _stack(tmp_path)

    assert local.workspace_root in local.allowed_roots
    assert str(local.workspace_root) in local.status()["allowed_roots"]


def test_code_workspace_relative_edits_stay_in_selected_project_without_approval(
    tmp_path: Path,
) -> None:
    local, gateway = _stack(tmp_path)
    project = local.allowed_roots[0] / "selected-project"
    project.mkdir()
    target = project / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("VALUE = 1\n", encoding="utf-8")
    local.authorize_code_workspace("code-job", str(project))

    changed = gateway.execute(
        "local_apply_edit",
        {"path": "src/app.py", "old": "VALUE = 1", "new": "VALUE = 2"},
        job_id="code-job",
    )

    assert changed.ok is True
    assert changed.risk_level == "L1"
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert not gateway.store.list_approvals(status="pending")


def test_code_workspace_relative_index_path_can_be_read_without_approval(
    tmp_path: Path,
) -> None:
    local, gateway = _stack(tmp_path)
    project = local.allowed_roots[0] / "selected-project"
    target = project / "docs" / "agent-todo.md"
    target.parent.mkdir(parents=True)
    target.write_text("# 실제 저장소 문서\n", encoding="utf-8")
    local.authorize_code_workspace("code-read", str(project))

    result = gateway.execute(
        "local_read_text_file",
        {"path": "docs/agent-todo.md"},
        job_id="code-read",
    )

    assert result.ok is True
    assert result.risk_level == "L1"
    assert result.result["path"] == str(target)
    assert "실제 저장소 문서" in result.result["content"]
    assert not gateway.store.list_approvals(status="pending")


def test_code_workspace_empty_search_is_limited_to_selected_project(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)
    project = local.allowed_roots[0] / "selected-project"
    project.mkdir()
    inside = project / "wanted.py"
    outside = local.allowed_roots[0] / "wanted-outside.py"
    inside.write_text("VALUE = 1\n", encoding="utf-8")
    outside.write_text("VALUE = 2\n", encoding="utf-8")
    local.authorize_code_workspace("code-search", str(project))

    result = gateway.execute(
        "local_search_files",
        {"query": "wanted"},
        job_id="code-search",
    )

    paths = {row["path"] for row in result.result["items"]}
    assert paths == {str(inside)}


def test_code_workspace_does_not_trust_an_absolute_path_outside_selected_project(
    tmp_path: Path,
) -> None:
    local, gateway = _stack(tmp_path)
    project = local.allowed_roots[0] / "selected-project"
    project.mkdir()
    outside = local.allowed_roots[0] / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    local.authorize_code_workspace("code-job", str(project))

    with pytest.raises(ApprovalRequired):
        gateway.execute(
            "local_write_file",
            {"path": str(outside), "content": "changed"},
            job_id="code-job",
        )

    assert outside.read_text(encoding="utf-8") == "keep"
