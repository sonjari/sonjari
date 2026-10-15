from __future__ import annotations

import base64
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.sandbox import SandboxBox
from alture_jarvis.tool_gateway import ToolGateway


def _parts(tmp_path: Path) -> tuple[LocalComputerTools, SandboxBox]:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        # 검사가 진짜 「내 문서」에 쓰면 그건 검사가 아니다 — 실제로 한 번 그랬다.
        documents_dir=tmp_path / "documents",
        local_computer_enabled=True,
        sandbox_enabled=True,
    )
    local = LocalComputerTools(config)
    return local, SandboxBox(config, local_computer=local)


def test_fetch_puts_a_job_output_on_that_jobs_workspace(tmp_path: Path, monkeypatch) -> None:
    """중간 산출물은 그 잡의 작업폴더에 남는다.

    ★ 2026-09-01 에 규칙이 갈렸다. **사람에게 줄 문서**(xlsx·docx·hwpx…)는
    「내 문서\\JARVIS」로 가고, 여기서 세는 것은 그 나머지다. 예전엔 이 검사가
    `성적.xlsx` 를 썼는데, 그건 이제 결과물이라 자리가 다르다 —
    `test_sandbox_deliverables.py` 가 그쪽을 지킨다.
    """
    local, box = _parts(tmp_path)
    blob = b"scratch-bytes"
    monkeypatch.setattr(
        box,
        "_exec",
        lambda script, timeout: (0, base64.b64encode(blob).decode("ascii"), ""),
    )

    result = box.fetch({"run_id": "abc123", "name": "중간_성적.json", "__job_id": "job-xlsx"})

    target = local.job_workspace("job-xlsx") / "중간_성적.json"
    assert result["ok"] is True
    assert Path(result["path"]) == target
    assert target.read_bytes() == blob


def test_gateway_gives_sandbox_run_its_job_context_and_undo_removes_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    local, box = _parts(tmp_path)

    def fake_run(arguments: dict) -> dict:
        assert arguments["__job_id"] == "job-run"
        target = local.job_workspace("job-run", create=True) / "계산.csv"
        target.write_bytes(b"a,b\n1,2\n")
        return {
            "ok": True,
            "action": "sandbox_run",
            "saved_to": [{"name": target.name, "path": str(target), "bytes": target.stat().st_size}],
        }

    monkeypatch.setattr(box, "run", fake_run)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    box.register(gateway)

    result = gateway.execute("sandbox_run", {"code": "print(1)"}, job_id="job-run")

    assert result.ok is True
    target = local.job_workspace("job-run") / "계산.csv"
    assert target.exists()
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]
    undone = gateway.undo(undo_id)
    assert undone["verified"] is True
    assert not target.exists()
