from __future__ import annotations

import time

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.agent import AgentRunResult
from alture_jarvis.config import JarvisConfig
from alture_jarvis.models import JobStatus


def _config(tmp_path) -> JarvisConfig:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )
    return config


def test_granted_paths_can_be_listed_and_revoked_by_mode(tmp_path) -> None:
    config = _config(tmp_path)
    config.model_roles = {"chat": "qwen3.5:9b"}
    app = create_app(config, start_services=False)
    tools = app.state.jarvis.local_computer
    folder = tmp_path / "shared"
    folder.mkdir()
    tools.request_path_access({"path": str(folder), "mode": "read", "reason": "자료"})
    tools.request_path_access({"path": str(folder), "mode": "write", "reason": "결과물"})
    headers = {"X-JARVIS-TOKEN": "test-token"}
    with TestClient(app) as client:
        assert client.get("/v1/settings/granted-paths").status_code == 401
        assert client.post("/v1/settings/granted-paths/revoke", json={"path": str(folder), "mode": "read"}).status_code == 401
        listed = client.get("/v1/settings/granted-paths", headers=headers)
        assert listed.status_code == 200
        assert str(folder) in listed.json()["read"]
        assert client.post("/v1/settings/granted-paths/revoke", json={"path": str(folder)}, headers=headers).status_code == 400
        revoked = client.post("/v1/settings/granted-paths/revoke", json={"path": str(folder), "mode": "read"}, headers=headers)
        assert revoked.status_code == 200 and revoked.json()["ok"]
        assert revoked.json()["granted_paths"]["read"] == []
        assert str(folder) in revoked.json()["granted_paths"]["write"]


def test_mutations_require_control_token(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        assert client.post("/v1/chat", json={"prompt": "hello"}).status_code == 401
        response = client.post(
            "/v1/chat",
            json={"prompt": "hello", "speak": False, "session_id": "office-main"},
            headers={"X-JARVIS-TOKEN": "test-token"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"


def test_workspace_origin_rides_on_the_first_job_event(tmp_path) -> None:
    # The small HUD and the full-screen workspace share one broadcast socket, so
    # the HUD needs the origin from the earliest event of a job -- agent_progress
    # and agent_answer_delta never carry one of their own.
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            json={
                "prompt": "안녕",
                "session_id": "jarvis-workspace",
                "delivery": "screen",
                "origin": "workspace",
            },
            headers={"X-JARVIS-TOKEN": "test-token"},
        )
        assert response.status_code == 200
        job_id = response.json()["id"]

    queued = [
        event
        for event in runtime.events.get_since(0, limit=500)
        if event.event == "job_queued" and event.payload.get("job_id") == job_id
    ]
    assert queued, "job_queued was not published for the workspace chat"
    assert queued[0].payload["origin"] == "workspace"


def test_chat_carries_an_explicit_skill_to_the_job(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            json={"prompt": "검토해줘", "skill": "copy-editing"},
            headers={"X-JARVIS-TOKEN": "test-token"},
        )

    assert response.status_code == 200
    job = app.state.jarvis.store.get_job(response.json()["id"])
    assert job["payload"]["skill"] == "copy-editing"


def test_code_mode_discovers_or_normalizes_an_allowed_project_directory(tmp_path) -> None:
    config = _config(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    config.local_file_allowed_roots = str(tmp_path)
    app = create_app(config, start_services=False)
    headers = {"X-JARVIS-TOKEN": "test-token"}

    with TestClient(app) as client:
        unresolved = client.post(
            "/v1/chat", json={"prompt": "읽어줘", "workspace_mode": "code"}, headers=headers,
        )
        accepted = client.post(
            "/v1/chat",
            json={
                "prompt": "읽어줘",
                "workspace_mode": "code",
                "code_workspace": str(project / "."),
            },
            headers=headers,
        )

    assert unresolved.status_code == 409
    assert unresolved.json()["detail"]["code"] == "code_workspace_ambiguous"
    assert accepted.status_code == 200
    job = app.state.jarvis.store.get_job(accepted.json()["id"])
    assert job["payload"]["workspace_mode"] == "code"
    assert job["payload"]["code_workspace"] == str(project.resolve())
    assert job["payload"]["workspace_discovery"]["source"] == "explicit"


def test_code_mode_reuses_recent_workspace_without_picker(tmp_path) -> None:
    config = _config(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    config.local_file_allowed_roots = str(tmp_path)
    app = create_app(config, start_services=False)
    headers = {"X-JARVIS-TOKEN": "test-token"}

    with TestClient(app) as client:
        first = client.post(
            "/v1/chat",
            json={
                "prompt": "읽어줘", "workspace_mode": "code",
                "code_workspace": str(project), "session_id": "code-recent",
            },
            headers=headers,
        )
        second = client.post(
            "/v1/chat",
            json={
                "prompt": "이어서 버그를 고쳐줘", "workspace_mode": "code",
                "session_id": "code-recent",
            },
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    job = app.state.jarvis.store.get_job(second.json()["id"])
    assert job["payload"]["code_workspace"] == str(project.resolve())
    assert job["payload"]["workspace_discovery"]["source"] == "recent"


def test_code_mode_bypasses_chat_routing_and_selects_the_code_role(tmp_path) -> None:
    config = _config(tmp_path)
    config.sandbox_enabled = True
    config.local_file_allowed_roots = str(tmp_path)
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis
    captured: dict = {}

    def fake_run(prompt: str, **kwargs):
        captured.update(kwargs)
        return AgentRunResult(
            answer="저장소를 읽었습니다.", steps=[{"tool": "local_list_directory", "ok": True}],
            verification={"completion_state": "complete"}, plan={},
            contract={"version": "task-contract-shadow-v1", "clauses": []},
        )

    runtime.agent.run = fake_run
    runtime._learn_facts = lambda *_args, **_kwargs: None
    project = tmp_path / "repo"
    project.mkdir()
    job = runtime.enqueue(
        "chat", "코드 읽기",
        {
            "prompt": "구조를 설명해줘", "session_id": "code-session",
            "workspace_mode": "code", "code_workspace": str(project),
            "origin": "workspace", "delivery": "screen", "agent_mode": "auto",
        },
    )

    result = runtime._chat_job(runtime.store.get_job(job["id"]))

    assert result["answer"] == "저장소를 읽었습니다."
    assert captured["model_role"] == "code"
    assert captured["required_local_root"] == str(project)
    assert captured["must_observe"] is True
    assert captured["require_sandbox"] is False
    assert captured["auto_continue_budget"] is True
    assert result["agent_trace"]["contract"]["version"] == "task-contract-shadow-v1"


def test_code_mode_plain_chat_uses_qwen_without_indexing_or_verification(tmp_path) -> None:
    config = _config(tmp_path)
    config.sandbox_enabled = True
    config.local_file_allowed_roots = str(tmp_path)
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis
    captured: dict = {}

    def fake_run(prompt: str, **kwargs):
        captured.update(kwargs)
        return AgentRunResult(
            answer="반갑습니다.", steps=[],
            verification={"completion_state": "complete"}, plan={},
        )

    runtime.agent.run = fake_run
    runtime._learn_facts = lambda *_args, **_kwargs: None
    project = tmp_path / "repo"
    project.mkdir()
    job = runtime.enqueue(
        "chat", "하이하이",
        {
            "prompt": "하이하이", "session_id": "code-greeting",
            "workspace_mode": "code", "code_workspace": str(project),
            "origin": "workspace", "delivery": "screen", "agent_mode": "auto",
        },
    )

    result = runtime._chat_job(runtime.store.get_job(job["id"]))

    assert result["answer"] == "반갑습니다."
    assert captured["model_role"] == "code"
    assert captured["required_local_root"] == ""
    assert captured["must_observe"] is False
    assert captured["require_sandbox"] is False
    assert captured["auto_continue_budget"] is True


def test_code_mode_change_without_saying_code_still_requires_verification(tmp_path) -> None:
    config = _config(tmp_path)
    config.sandbox_enabled = True
    config.local_file_allowed_roots = str(tmp_path)
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis
    captured: dict = {}

    def fake_run(prompt: str, **kwargs):
        captured.update(kwargs)
        return AgentRunResult(
            answer="수정했습니다.", steps=[{"tool": "sandbox_run", "ok": True}],
            verification={"completion_state": "complete"}, plan={},
        )

    runtime.agent.run = fake_run
    runtime._learn_facts = lambda *_args, **_kwargs: None
    project = tmp_path / "repo"
    project.mkdir()
    job = runtime.enqueue(
        "chat", "버그 수정",
        {
            "prompt": "이 버그 고쳐줘", "session_id": "code-fix",
            "workspace_mode": "code", "code_workspace": str(project),
            "origin": "workspace", "delivery": "screen", "agent_mode": "auto",
        },
    )

    runtime._chat_job(runtime.store.get_job(job["id"]))

    assert captured["model_role"] == "code"
    assert captured["required_local_root"] == str(project)
    assert captured["must_observe"] is True
    assert captured["require_sandbox"] is True
    assert captured["auto_continue_budget"] is True


def test_public_state_and_redacted_config(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        assert client.get("/v1/state").json()["state"] == "idle"
        config = client.get("/v1/config").json()
        assert "control_token" not in config
        assert "pc_mcp_token" not in config
        policy = client.get("/v1/presentation/policy").json()
        assert policy["default"] == "auto"
        assert policy["modes"] == ["voice", "hybrid", "screen"]
        assert client.get("/v1/memory/office-main").status_code == 401
        memory = client.get(
            "/v1/memory/office-main", headers={"X-JARVIS-TOKEN": "test-token"}
        )
        assert memory.status_code == 200
        assert memory.json()["message_count"] == 0
        browser = client.get("/v1/browser/status")
        assert browser.status_code == 200
        assert browser.json()["read_only"] is True


def test_workspace_conversation_history_keeps_compacted_messages(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    runtime.memory.add_exchange("jarvis-one", "첫 질문", "첫 답변")
    runtime.memory.add_exchange("jarvis-one", "두 번째 질문", "두 번째 답변")
    runtime.memory.save_summary("jarvis-one", "누적 요약", 2)
    headers = {"X-JARVIS-TOKEN": "test-token"}

    with TestClient(app) as client:
        sessions = client.get("/v1/conversations", headers=headers)
        history = client.get(
            "/v1/conversations/jarvis-one/messages", headers=headers
        )

    assert sessions.status_code == 200
    assert sessions.json()[0]["title"] == "첫 질문"
    assert sessions.json()[0]["has_summary"] is True
    assert history.status_code == 200
    assert history.json()["summary"] == "누적 요약"
    assert history.json()["context_window"] == 131072
    assert history.json()["retrieval_enabled"] is True
    assert [row["content"] for row in history.json()["messages"]] == [
        "첫 질문", "첫 답변", "두 번째 질문", "두 번째 답변"
    ]


def test_websocket_requires_token_and_connects(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/v1/ws", subprotocols=["jarvis", "test-token"]
        ) as websocket:
            message = websocket.receive_json()
            assert message["event"] == "connected"
            assert message["sequence"] == 0


def test_websocket_replays_a_pending_approval_after_hud_reconnect(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    app.state.jarvis.store.create_approval(
        nonce="pending-nonce",
        job_id="job-1",
        tool_name="browser_click_confirmed",
        arguments={"ref": "j14"},
        proof={"url": "https://example.test/form"},
        expires_at=time.time() + 300,
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            "/v1/ws", subprotocols=["jarvis", "test-token"]
        ) as websocket:
            assert websocket.receive_json()["event"] == "connected"
            replay = websocket.receive_json()

    assert replay["event"] == "approval_requested"
    assert replay["replayed"] is True
    assert replay["payload"]["nonce"] == "pending-nonce"
    assert replay["payload"]["arguments"] == {"ref": "j14"}


def test_tauri_hud_cors_preflight_allows_authenticated_chat(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        response = client.options(
            "/v1/chat",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-jarvis-token",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"
        assert "x-jarvis-token" in response.headers["access-control-allow-headers"].lower()


def test_every_route_method_passes_the_packaged_app_preflight(tmp_path) -> None:
    """포장 앱은 화면과 백엔드의 출처가 달라, POST 가 아닌 메서드는 사전 확인을 먼저 받는다.

    ★ 2026-09-18 노트북: 설정 저장이 전부 「Failed to fetch」였다. `PATCH /v1/settings` 가
      CORS 허용 목록(GET·POST)에 없어 브라우저가 요청을 아예 안 보냈다 — 서버 로그에도 안 남았다.
      `DELETE /v1/people/{name}` 도 같이 죽어 있었다. 위 시험은 `/v1/chat` 의 POST 하나만 찔렀다.
      그래서 **라우트가 쓰는 메서드 전부**를 실제 사전 확인으로 찌른다 — 새 메서드를 만들면 여기서 걸린다.
    """
    app = create_app(_config(tmp_path), start_services=False)
    wanted: set[tuple[str, str]] = set()
    for route in app.routes:
        for method in getattr(route, "methods", None) or ():
            if method not in {"HEAD", "OPTIONS"} and str(getattr(route, "path", "")).startswith("/v1/"):
                wanted.add((method, route.path))
    assert {method for method, _ in wanted} >= {"GET", "POST", "PATCH", "DELETE"}, "표본이 메서드를 다 담아야 시험이 뜻이 있다"

    refused = []
    with TestClient(app) as client:
        for method, path in sorted(wanted):
            response = client.options(
                path.replace("{", "x").replace("}", ""),
                headers={
                    "Origin": "http://tauri.localhost",
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type,x-jarvis-token",
                },
            )
            allowed = response.headers.get("access-control-allow-methods", "")
            if response.status_code != 200 or method not in allowed:
                refused.append(f"{method} {path} → {response.status_code} ({allowed or '허용 헤더 없음'})")
    assert not refused, "포장 앱에서 막히는 문:\n" + "\n".join(refused)


def test_untrusted_web_origin_is_not_cors_allowed(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    with TestClient(app) as client:
        response = client.options(
            "/v1/chat",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-jarvis-token",
            },
        )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


def test_external_action_preview_endpoint(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    headers = {"X-JARVIS-TOKEN": "test-token"}

    with TestClient(app) as client:
        assert client.get("/v1/external-actions/does-not-exist", headers=headers).status_code == 404
        assert client.get("/v1/external-actions/does-not-exist").status_code == 401

        action = runtime.external_actions.create_prepared_action(
            kind="gmail_send",
            payload={"to": ["a@example.com"], "subject": "secret-payload"},
            preview={"to": ["a@example.com"], "subject": "제목"},
            ttl_sec=300,
        )
        response = client.get(f"/v1/external-actions/{action['action_id']}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "gmail_send"
    assert body["preview"] == {"to": ["a@example.com"], "subject": "제목"}
    assert "payload" not in body
    assert "payload_hash" not in body


def test_agent_continuation_endpoint_requeues_checkpoint(tmp_path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    job = runtime.enqueue("chat", "long task", {"prompt": "continue"})
    runtime.store.save_agent_checkpoint(
        job["id"],
        {
            "messages": [],
            "steps": [],
            "lease_sec": 180,
            "finish_now": False,
        },
    )
    runtime.store.set_status(job["id"], JobStatus.WAITING_CONTINUATION)

    with TestClient(app) as client:
        response = client.post(
            f"/v1/agents/{job['id']}/continue",
            json={"action": "extend_3m"},
            headers={"X-JARVIS-TOKEN": "test-token"},
        )

    assert response.status_code == 200
    assert runtime.store.get_job(job["id"])["status"] == "queued"
    checkpoint = runtime.store.get_agent_checkpoint(job["id"])
    assert checkpoint["lease_sec"] == runtime.config.agent_continue_short_sec
