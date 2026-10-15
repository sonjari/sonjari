from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.hwp import HwpTools, _sha256
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway


def _stack(tmp_path: Path) -> tuple[HwpTools, ToolGateway, Path]:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "사용자님.hwp"
    source.write_bytes(b"before-hwp")
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed),
        hwp_enabled=True,
    )
    local = LocalComputerTools(config)
    tools = HwpTools(config, local, EventBus())
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    tools.register(gateway)
    return tools, gateway, source


def _fake_com(tools: HwpTools, source: Path, *, modified: bool = False) -> None:
    def invoke(operation: str, **payload: Any) -> dict[str, Any]:
        if operation == "list_open":
            return {
                "documents": [
                    {
                        "native_document_id": 7,
                        "instance_id": "!HwpObject.test.1",
                        "path": str(source),
                        "name": source.name,
                        "format": "HWP",
                        "modified": modified,
                    }
                ]
            }
        if operation == "read":
            return {"text": "제목\n기존 문구", "modified": modified}
        if operation == "preview_edit":
            preview = Path(payload["preview_path"])
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_bytes(b"preview-hwp")
            return {
                "source_sha256": _sha256(source),
                "preview_sha256": "preview",
                "before_text": "제목\n기존 문구",
                "after_text": "제목\n새 문구",
                "occurrences": 1,
            }
        if operation == "apply_edit":
            backup = Path(payload["backup_path"])
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            before = _sha256(source)
            source.write_bytes(b"after-hwp")
            return {
                "before_sha256": before,
                "after_sha256": _sha256(source),
                "verified": True,
            }
        if operation == "restore":
            shutil.copy2(Path(payload["backup_path"]), source)
            return {
                "path": str(source),
                "restored_sha256": _sha256(source),
                "reopened": True,
                "verified": True,
            }
        raise AssertionError(operation)

    tools._invoke = invoke  # type: ignore[method-assign]


def test_hwp_tools_use_preview_then_l2_apply_with_real_inverse(tmp_path: Path) -> None:
    tools, gateway, _source = _stack(tmp_path)
    specs = gateway._tools

    assert specs["hwp_list_open"].risk_level is RiskLevel.L0
    assert specs["hwp_read"].risk_level is RiskLevel.L1
    assert specs["hwp_preview_edit"].risk_level is RiskLevel.L1
    assert specs["hwp_apply_edit"].risk_level is RiskLevel.L2
    assert specs["hwp_apply_edit"].inverse is not None
    assert specs["hwp_apply_edit"].inverse.undo is not None
    assert specs["hwp_apply_edit"].proof is not None
    assert specs["hwp_preview_edit"].needs_job_context is True
    assert specs["hwp_apply_edit"].needs_job_context is True


def test_list_open_returns_empty_when_hwp_is_not_running(tmp_path: Path) -> None:
    tools, _gateway, _source = _stack(tmp_path)

    def no_instance(_operation: str, **_payload: Any) -> dict[str, Any]:
        raise RuntimeError("hwp_no_running_instance")

    tools._invoke = no_instance  # type: ignore[method-assign]

    assert tools.list_open() == {"action": "hwp_list_open", "count": 0, "documents": []}


def test_preview_edits_a_copy_and_returns_a_diff_without_touching_source(tmp_path: Path) -> None:
    tools, _gateway, source = _stack(tmp_path)
    _fake_com(tools, source)
    before = source.read_bytes()

    result = tools.preview_edit(
        {
            "document_id": 1,
            "old_text": "기존 문구",
            "new_text": "새 문구",
            "__job_id": "job-preview",
        }
    )

    assert source.read_bytes() == before
    assert Path(result["output_path"]).is_file()
    assert "-기존 문구" in result["diff"]
    assert "+새 문구" in result["diff"]
    assert result["requires_approval"] is True
    assert result["preview_id"]


def test_preview_refuses_to_copy_over_unsaved_human_edits(tmp_path: Path) -> None:
    tools, _gateway, source = _stack(tmp_path)
    _fake_com(tools, source, modified=True)

    with pytest.raises(RuntimeError, match="unsaved"):
        tools.preview_edit(
            {
                "document_id": 1,
                "old_text": "기존 문구",
                "new_text": "새 문구",
                "__job_id": "job-dirty",
            }
        )


def test_apply_is_single_use_and_inverse_restores_the_backup(tmp_path: Path) -> None:
    tools, gateway, source = _stack(tmp_path)
    _fake_com(tools, source)
    preview = tools.preview_edit(
        {
            "document_id": 1,
            "old_text": "기존 문구",
            "new_text": "새 문구",
            "__job_id": "job-apply",
        }
    )
    original = source.read_bytes()

    applied = tools.apply_edit({"preview_id": preview["preview_id"], "__job_id": "job-apply"})

    assert applied["verified"] is True
    assert source.read_bytes() == b"after-hwp"
    with pytest.raises(RuntimeError, match="already_used"):
        tools.apply_edit({"preview_id": preview["preview_id"], "__job_id": "job-apply"})

    inverse = gateway._tools["hwp_apply_edit"].inverse
    assert inverse is not None and inverse.undo is not None
    handle = inverse.handle_from(applied)
    assert handle is not None
    undone = inverse.undo(handle)

    assert undone["verified"] is True
    assert source.read_bytes() == original


def test_approval_fingerprint_changes_when_the_source_file_drifts(tmp_path: Path) -> None:
    tools, _gateway, source = _stack(tmp_path)
    _fake_com(tools, source)
    preview = tools.preview_edit(
        {
            "document_id": 1,
            "old_text": "기존 문구",
            "new_text": "새 문구",
            "__job_id": "job-proof",
        }
    )
    arguments = {"preview_id": preview["preview_id"], "__job_id": "job-proof"}
    before = tools._capture_apply_proof(arguments)

    source.write_bytes(b"human-changed-the-source")
    current = tools._capture_apply_proof(arguments)

    assert before["fingerprint"] != current["fingerprint"]
