"""줄 범위 모드 편집이 도구 관문(`ToolGateway`)을 지나도 되돌리기 · 증거 · 인코딩이 그대로다 (2026-10-28).

직접 부르는 시험(`test_apply_edit_by_line_range_1028`)은 관문을 안 지난다. 실제 판은 관문을 지나므로 — 되돌리기 제안(undo)이 생기고, 되돌리면 바이트까지
원래대로이며, 결과에 증거(proof)가 붙고, 거절은 파일을 건드리지 않는 것까지 한 번 더 본다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
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


def test_a_line_range_edit_leaves_proof_and_undo_restores_the_original_bytes(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)
    target = local.job_workspace("job-lines", create=True) / "plan.txt"
    original = "첫째 줄\r\n둘째 줄\r\n셋째 줄\r\n".encode("cp949")      # 한글 cp949 + CRLF — 편집은 인코딩 · 줄바꿈을 그대로 둔다
    target.write_bytes(original)

    changed = gateway.execute(
        "local_apply_edit",
        {"path": "plan.txt", "line_start": 2, "first_line": "둘째 줄", "new": "고친 둘째 줄"},
        job_id="job-lines",
    )

    assert changed.ok is True, changed.error
    assert target.read_bytes() == "첫째 줄\r\n고친 둘째 줄\r\n셋째 줄\r\n".encode("cp949")
    assert changed.result["healed"] == "line_range"
    assert changed.result["proof"]["after"]["sha256"]
    offers = gateway.store.list_undo_offers()
    assert len(offers) == 1

    undone = gateway.undo(offers[0]["undo_id"])

    assert undone["ok"] is True and undone["verified"] is True
    assert target.read_bytes() == original


def test_a_refused_line_range_edit_changes_nothing_and_offers_no_undo(tmp_path: Path) -> None:
    local, gateway = _stack(tmp_path)
    target = local.job_workspace("job-refused", create=True) / "a.txt"
    target.write_bytes(b"a = 1\nb = 2\n")

    refused = gateway.execute(
        "local_apply_edit",
        {"path": "a.txt", "line_start": 2, "first_line": "c = 3", "new": "b = 3"},
        job_id="job-refused",
    )

    assert refused.ok is False
    assert "line_text_changed" in str(refused.error)
    assert target.read_bytes() == b"a = 1\nb = 2\n"
    assert gateway.store.list_undo_offers() == []
