"""코워크의 프로젝트 폴더 (2026-10-30 대표 「클로드 코워크처럼 폴더를 정해 두고 오가자」).

- 사람이 화면에서 **직접 고른** 폴더만 허락으로 받는다. 바깥 AI(MCP)가 넘긴 경로는 받지 않는다.
- 그 판에서 이름만 준 새 파일은 결과물 폴더(문서\\Sonjari) 대신 그 폴더에 생긴다 — 안내문이 아니라 도구가 정한다.
- 폴더를 안 고르면 예전 그대로 결과물 폴더.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

from test_api import _config


def _tools(tmp_path: Path, monkeypatch) -> LocalComputerTools:  # noqa: ANN001
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None, raising=False)
    return LocalComputerTools(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents", local_computer_enabled=True,
        local_file_allowed_roots=str(tmp_path),
    ))


def test_a_bare_file_name_lands_in_the_project_folder(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    tools = _tools(tmp_path, monkeypatch)
    project = tmp_path / "unity_project"
    project.mkdir()
    tools.set_project_folder("job-a", str(project))

    picked = tools._document_arguments({"path": "텍스처_점검.xlsx", "__job_id": "job-a"})
    assert Path(picked["path"]) == project.resolve() / "텍스처_점검.xlsx"
    assert tools._mutation_workspace({"__job_id": "job-a"}, create=False) == project.resolve()


def test_without_a_project_folder_it_goes_to_the_results_folder_as_before(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    tools = _tools(tmp_path, monkeypatch)
    tools.set_project_folder("job-a", str(tmp_path))
    picked = tools._document_arguments({"path": "보고서.docx", "__job_id": "job-b"})   # 다른 판
    assert Path(picked["path"]).parent == tools.documents_root


def test_an_absolute_path_is_still_followed(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    tools = _tools(tmp_path, monkeypatch)
    project = tmp_path / "p"
    project.mkdir()
    tools.set_project_folder("job-a", str(project))
    elsewhere = tmp_path / "else" / "a.txt"
    picked = tools._document_arguments({"path": str(elsewhere), "__job_id": "job-a"})
    assert Path(picked["path"]) == elsewhere


def test_the_api_takes_a_folder_a_person_picked_in_cowork(tmp_path: Path) -> None:
    config = _config(tmp_path)
    project = tmp_path / "max_scenes"
    project.mkdir()
    config.local_file_allowed_roots = str(tmp_path / "nowhere")   # 허용 목록 밖 — 사람이 골라서 받는다
    app = create_app(config, start_services=False)
    headers = {"X-JARVIS-TOKEN": "test-token"}

    with TestClient(app) as client:
        person = client.post("/v1/chat", json={
            "prompt": "정리해 줘", "workspace_mode": "cowork", "code_workspace": str(project), "origin": "workspace",
        }, headers=headers)
        outside = client.post("/v1/chat", json={
            "prompt": "정리해 줘", "workspace_mode": "cowork", "code_workspace": str(tmp_path / "other"), "origin": "mcp",
        }, headers=headers)
        plain = client.post("/v1/chat", json={"prompt": "안녕", "workspace_mode": "cowork"}, headers=headers)

    assert person.status_code == 200
    job = app.state.jarvis.store.get_job(person.json()["id"])
    assert job["payload"]["project_folder"] == str(project.resolve())
    assert "code_workspace" not in job["payload"] or not job["payload"]["code_workspace"]

    assert outside.status_code == 200, "바깥 AI 가 넘긴 경로는 거절하지 않고 무시한다(예전 그대로 결과물 폴더)"
    mcp_job = app.state.jarvis.store.get_job(outside.json()["id"])
    assert "project_folder" not in mcp_job["payload"]

    plain_job = app.state.jarvis.store.get_job(plain.json()["id"])
    assert "project_folder" not in plain_job["payload"]


def test_a_whole_drive_is_refused(tmp_path: Path) -> None:
    config = _config(tmp_path)
    app = create_app(config, start_services=False)
    with TestClient(app) as client:
        refused = client.post("/v1/chat", json={
            "prompt": "정리해 줘", "workspace_mode": "cowork", "code_workspace": "C:\\", "origin": "workspace",
        }, headers={"X-JARVIS-TOKEN": "test-token"})
    assert refused.status_code == 400


def test_find_and_list_look_inside_the_project_folder_only(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """10-30 대표 스크린샷: 프로젝트 폴더를 골랐는데 「파일 찾기」가 허용된 자리 전부(41만 개)를 훑었다."""
    tools = _tools(tmp_path, monkeypatch)
    project = tmp_path / "academy"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "JARVIS_전략안.md").write_text("x", encoding="utf-8")
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "다른_전략안.md").write_text("x", encoding="utf-8")
    tools.set_project_folder("job-a", str(project))

    found = tools.search_files({"query": "전략안", "__job_id": "job-a"})
    paths = [str(item.get("path") or "") for item in (found.get("results") or found.get("items") or [])]
    assert paths and all(str(project.resolve()) in p for p in paths), paths
    assert tools._roots_when_path_missing({"__job_id": "job-a"}) == [project.resolve()]
    assert tools._resolve_workspace_path({"path": "docs/JARVIS_전략안.md", "__job_id": "job-a"}) == \
        (project / "docs" / "JARVIS_전략안.md").resolve()


def test_deleting_inside_the_project_folder_still_asks(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from alture_jarvis.models import RiskLevel

    tools = _tools(tmp_path, monkeypatch)
    tools.set_project_folder("job-a", str(tmp_path))
    assert tools._delete_risk({"path": str(tmp_path / "a.txt"), "__job_id": "job-a"}) == RiskLevel.L2
