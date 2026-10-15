from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.observations import ObservationStore
from alture_jarvis.sandbox import SandboxBox
from alture_jarvis.tool_gateway import ToolGateway


def test_the_artifact_is_built_from_full_observations_and_can_be_undone(
    tmp_path: Path, monkeypatch
) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(tmp_path / "allowed"),
        local_computer_enabled=True,
        sandbox_enabled=True,
    )
    local = LocalComputerTools(config)
    observations = ObservationStore()
    observations.record(
        job_id="job-artifact",
        step=4,
        tool="browser_extract",
        arguments={"selector": "table"},
        observation={
            "ok": True,
            "result": {
                "items": [
                    {"이름": "긴 원문 상품", "가격": "12,345원", "설명": "가" * 500}
                ]
            },
        },
    )
    box = SandboxBox(config, local_computer=local, observations=observations)
    captured: dict = {}

    def fake_run(arguments: dict) -> dict:
        captured.update(arguments)
        compile(arguments["code"], "artifact_from_observations.py", "exec")
        source = Path(arguments["files"][0])
        payload = json.loads(source.read_text(encoding="utf-8"))
        assert payload[0]["step"] == 4
        assert "가" * 300 in json.dumps(payload, ensure_ascii=False)
        delivered = tmp_path / "outputs" / "sandbox" / "baked.xlsx"
        delivered.parent.mkdir(parents=True, exist_ok=True)
        delivered.write_bytes(b"deterministic-xlsx-bytes")
        return {
            "ok": True,
            "action": "sandbox_run",
            "run_id": "run-1",
            "saved_to": [{"path": str(delivered), "bytes": delivered.stat().st_size}],
        }

    monkeypatch.setattr(box, "run", fake_run)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    box.register(gateway)

    result = gateway.execute(
        "artifact_from_observations",
        {"step_ids": [4], "path": "조사표", "format": "xlsx"},
        job_id="job-artifact",
    )

    target = local.job_workspace("job-artifact") / "조사표.xlsx"
    assert result.ok is True
    assert result.risk_level == "L1"
    assert target.read_bytes() == b"deterministic-xlsx-bytes"
    assert "openpyxl" in captured["code"]
    assert result.result["source_steps"] == [4]
    assert result.result["verified"] is True
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]
    assert gateway.undo(undo_id)["verified"] is True
    assert not target.exists()


def test_artifact_path_extension_must_match_the_chosen_format(tmp_path: Path) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_computer_enabled=True,
        sandbox_enabled=True,
    )
    local = LocalComputerTools(config)
    box = SandboxBox(config, local_computer=local, observations=ObservationStore())
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    box.register(gateway)

    result = gateway.execute(
        "artifact_from_observations",
        {"step_ids": [1], "path": "보고서.csv", "format": "docx"},
        job_id="job-mismatch",
    )

    assert result.ok is False
    assert result.status == "proof_capture_failed"
    assert result.error == "path_extension_mismatch:.docx"


def _box_available() -> bool:
    if not shutil.which("wsl.exe"):
        return False
    try:
        return subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "--user", "root", "--", "true"],
            capture_output=True,
            timeout=30,
            check=False,
        ).returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _box_available(), reason="상자(WSL Ubuntu)가 없다")
def test_live_observation_rows_become_a_real_xlsx_and_undo_removes_it(tmp_path: Path) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_computer_enabled=True,
        sandbox_enabled=True,
    )
    local = LocalComputerTools(config)
    observations = ObservationStore()
    observations.record(
        job_id="job-live-artifact",
        step=2,
        tool="browser_extract",
        arguments={},
        observation={
            "ok": True,
            "result": {
                "items": [
                    {"제품": "마우스 A", "가격": "10,000원"},
                    {"제품": "마우스 B", "가격": "20,000원"},
                ]
            },
        },
    )
    box = SandboxBox(config, local_computer=local, observations=observations)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    box.register(gateway)

    result = gateway.execute(
        "artifact_from_observations",
        {"step_ids": [2], "path": "제품표.xlsx", "format": "xlsx"},
        job_id="job-live-artifact",
    )

    assert result.ok is True, result.error
    target = local.job_workspace("job-live-artifact") / "제품표.xlsx"
    with zipfile.ZipFile(target) as archive:
        cells: list[str] = []
        for name in archive.namelist():
            if name.endswith(".xml"):
                cells.extend(ET.fromstring(archive.read(name)).itertext())
    text = "\n".join(cells)
    assert "제품" in text and "가격" in text
    assert "마우스 A" in text and "마우스 B" in text
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]
    assert gateway.undo(undo_id)["verified"] is True
    assert not target.exists()
