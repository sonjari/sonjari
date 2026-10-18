"""답이 기댄 페이지의 사진을 화면에 내주는 좁은 문 (2026-10-18 대표 결정).

`GET /v1/jobs/{job_id}/showcase/{index}` — 그 판 result.showcase 의 index 번째 사진만, 그 판의 사진 자리
(`outputs/shots/<job>/`) 안의 jpg 만 준다. 경로를 인자로 받지 않는다. 기록에 엉뚱한 경로가 들어 있어도 밖은 안 나간다.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import JobStatus
from alture_jarvis.showcase import shot_path_for

AUTH = {"X-JARVIS-TOKEN": "test-token"}
JPEG = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )


def _job(runtime, showcase: list[dict]) -> str:
    job = runtime.store.create_job("chat", "조사해줘", {"prompt": "조사해줘"})
    job_id = str(job["id"])
    runtime.store.set_status(job_id, JobStatus.COMPLETED, result={"answer": "…", "showcase": showcase})
    return job_id


def _shot(tmp_path: Path, job_id: str, step: int) -> Path:
    path = shot_path_for(tmp_path / "outputs", job_id, step)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(JPEG)
    return path


def test_the_picked_shot_comes_back_as_jpeg(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    job_id = _job(runtime, [])
    first = _shot(tmp_path, job_id, 3)
    second = _shot(tmp_path, job_id, 7)
    runtime.store.set_status(job_id, JobStatus.COMPLETED, result={"answer": "…", "showcase": [
        {"path": str(second), "url": "https://a.example/x", "title": "A", "read_at": 1.0, "matched": 3, "step": 7},
        {"path": str(first), "url": "https://b.example/y", "title": "B", "read_at": 2.0, "matched": 1, "step": 3},
    ]})
    with TestClient(app) as client:
        got = client.get(f"/v1/jobs/{job_id}/showcase/1", headers=AUTH)
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/jpeg"
    assert got.content == JPEG


def test_the_door_wants_the_token(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    job_id = _job(runtime, [])
    shot = _shot(tmp_path, job_id, 1)
    runtime.store.set_status(job_id, JobStatus.COMPLETED, result={"answer": "…", "showcase": [{"path": str(shot)}]})
    with TestClient(app) as client:
        assert client.get(f"/v1/jobs/{job_id}/showcase/0").status_code == 401
        assert client.get(f"/v1/jobs/{job_id}/showcase/0", headers={"X-JARVIS-TOKEN": "wrong"}).status_code == 401


def test_an_index_outside_the_list_or_an_unknown_job_is_404(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    job_id = _job(runtime, [])
    with TestClient(app) as client:
        assert client.get(f"/v1/jobs/{job_id}/showcase/0", headers=AUTH).json()["detail"] == "showcase_not_found"
        assert client.get(f"/v1/jobs/{job_id}/showcase/-1", headers=AUTH).status_code == 404
        assert client.get("/v1/jobs/no-such-job/showcase/0", headers=AUTH).json()["detail"] == "job_not_found"


def test_a_path_outside_this_jobs_shot_folder_never_leaves(tmp_path: Path) -> None:
    """기록의 path 가 판의 사진 자리 밖(다른 판 · 상위 폴더 · 다른 형식)을 가리키면 안 준다."""
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    job_id = _job(runtime, [])
    other_job = _job(runtime, [])
    someone_elses = _shot(tmp_path, other_job, 1)
    secret = tmp_path / "data" / "control.token"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("test-token", encoding="utf-8")
    own_folder = shot_path_for(tmp_path / "outputs", job_id, 1).parent
    own_folder.mkdir(parents=True, exist_ok=True)
    not_a_photo = own_folder / "notes.txt"
    not_a_photo.write_text("x", encoding="utf-8")
    runtime.store.set_status(job_id, JobStatus.COMPLETED, result={"answer": "…", "showcase": [
        {"path": str(someone_elses)},
        {"path": str(own_folder / ".." / ".." / ".." / "data" / "control.token")},
        {"path": str(not_a_photo)},
        {"path": ""},
    ]})
    with TestClient(app) as client:
        for index in range(4):
            got = client.get(f"/v1/jobs/{job_id}/showcase/{index}", headers=AUTH)
            assert got.status_code == 404, index
            assert got.json()["detail"] == "showcase_outside_shots", index


def test_a_deleted_shot_says_missing(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    job_id = _job(runtime, [])
    gone = shot_path_for(tmp_path / "outputs", job_id, 4)
    runtime.store.set_status(job_id, JobStatus.COMPLETED, result={"answer": "…", "showcase": [{"path": str(gone)}]})
    with TestClient(app) as client:
        got = client.get(f"/v1/jobs/{job_id}/showcase/0", headers=AUTH)
    assert got.status_code == 404
    assert got.json()["detail"] == "showcase_missing"
