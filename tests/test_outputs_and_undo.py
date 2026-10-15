"""끝나면 손에 쥐어 준다 (R4).

두 가지가 코드에는 있는데 화면에는 없었다.

  · `outputs/` 에 파일이 쌓이는데 **목록 경로가 없었다.** 자비스가 무언가를 만들어도
    사람은 답변에 적힌 경로를 보고 탐색기를 직접 열어야 했다.
  · `undo_list`·`undo_action` 도구는 **이미 있었다.** 모델만 부를 수 있었고 화면에는
    버튼이 없어서, 사람은 "방금 거 취소해줘"라고 말로 해야 했다.

여기서 못 박는 것은 **무엇을 산출물로 세는가**다. 디렉터리를 훑어 시각으로 짐작하면
남의 작업 파일이 섞인다 — 그 작업의 장부가 만들었다고 적은 것만 센다.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import JobStatus


def _config(tmp_path) -> JarvisConfig:
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


AUTH = {"X-JARVIS-TOKEN": "test-token"}


def _job_with_steps(runtime, steps: list[dict]) -> str:
    job = runtime.store.create_job("chat", "조사해줘", {"prompt": "조사해줘"})
    job_id = str(job["id"])
    runtime.store.set_status(
        job_id, JobStatus.COMPLETED, result={"answer": "…", "agent_trace": {"steps": steps}}
    )
    return job_id


def test_only_what_the_ledger_says_it_made(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    shots = tmp_path / "outputs" / "browser-evidence"
    shots.mkdir(parents=True)
    made = shots / "20260819_150000_shot.png"
    made.write_bytes(b"\x89PNG-x")
    # 같은 폴더에 있지만 **이 작업이 만든 것이 아닌** 파일. 디렉터리를 훑으면 섞인다.
    (shots / "somebody_elses.png").write_bytes(b"\x89PNG-y")

    job_id = _job_with_steps(runtime, [
        {"step": 1, "tool": "browser_open", "ok": True, "evidence": {"url": "https://x"}},
        # 읽은 파일은 산출물이 아니다 — path 가 있다고 다 만든 것이 아니다.
        {"step": 2, "tool": "local_read_document", "ok": True, "evidence": {"path": str(tmp_path / "읽은것.pdf")}},
        {"step": 3, "tool": "browser_screenshot", "ok": True, "evidence": {"path": str(made)}},
    ])

    with TestClient(app) as client:
        body = client.get(f"/v1/outputs?job_id={job_id}", headers=AUTH).json()

    assert body["count"] == 1
    item = body["items"][0]
    assert item["name"] == "20260819_150000_shot.png"
    assert item["kind"] == "image"
    assert item["bytes"] == 6
    assert item["exists"] is True
    assert item["viewable"] is True


def test_a_file_the_ledger_claims_but_is_gone_still_shows(tmp_path) -> None:
    """조용히 빼면 "안 만들었다"와 "만들었는데 지워졌다"를 구별할 수 없다."""
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    job_id = _job_with_steps(runtime, [
        {"step": 1, "tool": "browser_screenshot", "ok": True,
         "evidence": {"path": str(tmp_path / "outputs" / "사라진것.png")}},
    ])

    with TestClient(app) as client:
        item = client.get(f"/v1/outputs?job_id={job_id}", headers=AUTH).json()["items"][0]

    assert item["exists"] is False
    assert item["viewable"] is False
    assert item["bytes"] == 0


def test_a_file_outside_the_outputs_folder_is_not_served(tmp_path) -> None:
    """경로를 인자로 받는 경로는 **장부**와 **폴더**를 둘 다 본다. 하나만 보면 뚫린다."""
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    secret = tmp_path / "data" / "control.token"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("s3cret", encoding="utf-8")
    # 장부에는 있다 — 도구가 산출물 폴더 밖에 쓴 척한 경우다.
    job_id = _job_with_steps(runtime, [
        {"step": 1, "tool": "browser_screenshot", "ok": True, "evidence": {"path": str(secret)}},
    ])

    with TestClient(app) as client:
        listed = client.get(f"/v1/outputs?job_id={job_id}", headers=AUTH).json()["items"][0]
        response = client.get(
            "/v1/outputs/file", params={"job_id": job_id, "path": str(secret)}, headers=AUTH
        )

    assert listed["viewable"] is False
    assert response.status_code == 404
    # 장부에 아예 없는 경로도 마찬가지다.
    with TestClient(app) as client:
        assert client.get(
            "/v1/outputs/file",
            params={"job_id": job_id, "path": str(tmp_path / "outputs" / "무관.png")},
            headers=AUTH,
        ).status_code == 404


def test_a_ledgered_file_can_actually_be_opened(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    shots = tmp_path / "outputs" / "browser-evidence"
    shots.mkdir(parents=True)
    made = shots / "shot.png"
    made.write_bytes(b"\x89PNG\r\n\x1a\n")
    job_id = _job_with_steps(runtime, [
        {"step": 1, "tool": "browser_screenshot", "ok": True, "evidence": {"path": str(made)}},
    ])

    with TestClient(app) as client:
        response = client.get(
            "/v1/outputs/file", params={"job_id": job_id, "path": str(made)}, headers=AUTH
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"\x89PNG\r\n\x1a\n"


def test_local_and_observation_artifacts_follow_the_existing_file_card_wiring(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    workspace = tmp_path / "outputs" / "workspace" / "job-files"
    workspace.mkdir(parents=True)
    written = workspace / "메모.md"
    baked = workspace / "조사표.xlsx"
    written.write_text("결과", encoding="utf-8")
    baked.write_bytes(b"xlsx")
    job_id = _job_with_steps(runtime, [
        {"step": 1, "tool": "local_write_file", "ok": True,
         "evidence": {"output_path": str(written)}},
        {"step": 2, "tool": "artifact_from_observations", "ok": True,
         "evidence": {"output_path": str(baked)}},
    ])

    with TestClient(app) as client:
        body = client.get(f"/v1/outputs?job_id={job_id}", headers=AUTH).json()

    assert [item["name"] for item in body["items"]] == ["메모.md", "조사표.xlsx"]
    assert all(item["viewable"] for item in body["items"])


def test_a_followup_pronoun_is_bound_to_the_latest_real_output_in_that_session(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    workspace = tmp_path / "outputs" / "workspace" / "previous-job"
    workspace.mkdir(parents=True)
    text = workspace / "메모.txt"
    excel = workspace / "성적.xlsx"
    text.write_text("기존", encoding="utf-8")
    excel.write_bytes(b"xlsx")
    runtime.memory.add_exchange(
        "same-session",
        "파일 만들어줘",
        "두 파일을 만들었습니다.",
        assistant_metadata={"created_outputs": [str(text), str(excel)]},
    )

    found = runtime._followup_output_path(
        "same-session", "거기 3행 점수를 고쳐서 xlsx로 저장해줘"
    )

    assert found == str(excel)
    assert runtime._followup_output_path("same-session", "그거 내용 알려줘") == ""
    assert runtime._followup_output_path("other-session", "거기 3행 고쳐줘") == ""


def test_undo_is_reachable_without_speaking_to_the_model(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    offer = runtime.store.add_undo_offer(
        tool="naver_blog_save_draft",
        job_id="job-1",
        label="블로그 임시저장을 지웁니다",
        handle={"title": "여수 사무실 이전 점검"},
        manual_hint="",
        automatic=True,
        expires_at=time.time() + 1800,
    )

    with TestClient(app) as client:
        assert client.get("/v1/undo").status_code == 401
        body = client.get("/v1/undo", headers=AUTH).json()

    assert body["count"] == 1
    row = body["items"][0]
    assert row["undo_id"] == offer["undo_id"]
    assert row["label"] == "블로그 임시저장을 지웁니다"
    # 무엇을 되돌리는지 사람이 알아볼 수 있어야 한다 — 제목 같은 것이 여기 있다.
    assert row["what"] == {"title": "여수 사무실 이전 점검"}
    assert row["automatic"] is True


def test_running_an_unknown_undo_says_so_instead_of_pretending(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        body = client.post("/v1/undo/nope", headers=AUTH).json()
    assert body["ok"] is False
    assert body["error"] == "undo_not_found_or_expired"


def test_deleted_probe_is_removed_from_the_final_created_file_list(tmp_path) -> None:
    from alture_jarvis.runtime import _strip_deleted_output_claims

    probe = tmp_path / "verify.py"
    answer = f"완료했습니다.\n\n만든 파일:\n- `{probe}`"
    steps = [{
        "tool": "local_delete_file", "ok": True,
        "arguments": {"path": str(probe)},
        "evidence": {"output_path": str(probe), "verified": True},
    }]

    cleaned = _strip_deleted_output_claims(answer, steps)
    assert str(probe) not in cleaned
    assert "만든 파일:" not in cleaned
    assert cleaned == "완료했습니다."
