"""「만든 것」 링크는 이 PC 의 기본 앱으로 연다 (2026-09-17).

데스크톱 앱 안에서 `window.open(blob)` 새 창이 막혀 docx 링크가 아무 반응이 없었다. 백엔드가 같은 PC 에 있으니
`os.startfile` 로 연다 — 단, 그 작업 장부에 있는 파일만, 이 PC 에서 온 요청만.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alture_jarvis import runtime as runtime_module
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                        camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False)


def test_a_file_in_the_job_ledger_opens_with_the_default_app(monkeypatch, tmp_path: Path) -> None:
    runtime = JarvisRuntime(_config(tmp_path))
    made = tmp_path / "outputs" / "Hermes_vs_Ontelic.docx"
    made.parent.mkdir(parents=True, exist_ok=True)
    made.write_bytes(b"PK")
    monkeypatch.setattr(runtime, "job_output_file", lambda job_id, path: made)
    opened: list[str] = []
    monkeypatch.setattr(runtime_module.os, "name", "nt")
    monkeypatch.setattr(runtime_module.os, "startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr("alture_jarvis.msix.external_path", lambda p: p)

    result = runtime.open_job_output("job-1", str(made))
    assert result["ok"] is True and opened == [str(made)]


def test_reveal_points_explorer_at_the_file(monkeypatch, tmp_path: Path) -> None:
    runtime = JarvisRuntime(_config(tmp_path))
    made = tmp_path / "outputs" / "표.xlsx"
    made.parent.mkdir(parents=True, exist_ok=True)
    made.write_bytes(b"PK")
    monkeypatch.setattr(runtime, "job_output_file", lambda job_id, path: made)
    launched: list[list[str]] = []
    monkeypatch.setattr(runtime_module.os, "name", "nt")
    monkeypatch.setattr(runtime_module.subprocess, "Popen", lambda args, **_k: launched.append(args))
    monkeypatch.setattr("alture_jarvis.msix.external_path", lambda p: p)

    runtime.open_job_output("job-1", str(made), reveal=True)
    assert launched == [["explorer.exe", f"/select,{made}"]]


def test_a_path_outside_the_job_ledger_is_refused(tmp_path: Path) -> None:
    runtime = JarvisRuntime(_config(tmp_path))
    with pytest.raises(ValueError):
        runtime.open_job_output("no-such-job", str(tmp_path / "anything.docx"))


def test_a_deleted_output_says_so_instead_of_opening_nothing(monkeypatch, tmp_path: Path) -> None:
    runtime = JarvisRuntime(_config(tmp_path))
    monkeypatch.setattr(runtime, "job_output_file", lambda job_id, path: tmp_path / "gone.docx")
    with pytest.raises(ValueError, match="output_missing"):
        runtime.open_job_output("job-1", "gone.docx")


def test_the_endpoint_only_opens_for_this_pc(tmp_path: Path) -> None:
    """TestClient 의 주소는 `testclient` — 이 PC(루프백)가 아닌 요청으로 취급돼야 한다."""
    app = create_app(_config(tmp_path), start_services=False)
    token = app.state.runtime.config.control_token if hasattr(app.state, "runtime") else ""
    client = TestClient(app)
    response = client.post("/v1/outputs/open", json={"job_id": "x", "path": "y"}, headers={"X-Jarvis-Token": token})
    assert response.status_code in (200, 401, 403)
    if response.status_code == 200:
        assert response.json() == {"ok": False, "error": "not_this_pc"}
