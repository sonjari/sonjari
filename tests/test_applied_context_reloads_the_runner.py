"""컨텍스트를 적용하면 **그 크기로 다시 올린다** — 머리 칩 「32K」 · 패널 「104K」 (2026-09-30 대표 스크린샷).

칩이 맞았다. 올라가 있던 32K 러너가 설정보다 작으면 그 크기를 그대로 쓰는 규칙(`OllamaClient._options`, 09-28 남의 앱
러너를 안 뺏으려고)이 사람이 방금 고른 104K 까지 눌렀다. 패널은 「다음 요청에서 다시 올립니다」라고 약속했는데 영원히
32K 였다. 도는 일이 없으면 적용하는 자리에서 새 크기로 다시 올린다. 도는 일이 있으면 그 일을 끊지 않는다(양방향).
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.model_setup import SetupService

from test_api import _config

HEADERS = {"X-JARVIS-TOKEN": "test-token"}


def _app(tmp_path, monkeypatch, reloaded: list[str]):
    monkeypatch.setattr(SetupService, "apply_context_ceiling",
                        lambda self, tag=None, num_ctx=None: {"ok": True, "model": "qwen3.8:27b-mtp-q4_K_M", "num_ctx": 106496})
    monkeypatch.setattr(SetupService, "_rewarm", lambda self, tag: reloaded.append(tag))
    config = _config(tmp_path)
    config.model_roles = {"chat": "qwen3.8:27b-mtp-q4_K_M"}
    return create_app(config, start_services=False)


def test_applying_a_context_reloads_the_model_at_that_size(tmp_path, monkeypatch) -> None:
    reloaded: list[str] = []
    with TestClient(_app(tmp_path, monkeypatch, reloaded)) as client:
        got = client.post("/v1/setup/context/apply", json={"num_ctx": 106496}, headers=HEADERS).json()
    for _ in range(50):
        if reloaded:
            break
        time.sleep(0.02)
    assert got.get("reloading") is True and reloaded == ["qwen3.8:27b-mtp-q4_K_M"]


def test_a_running_job_is_not_interrupted(tmp_path, monkeypatch) -> None:
    reloaded: list[str] = []
    app = _app(tmp_path, monkeypatch, reloaded)
    from alture_jarvis.tool_gateway import RiskLevel
    app.state.jarvis.store.create_job("chat", "도는 일", {"prompt": "x"}, RiskLevel.L0)  # 줄 서 있는 일
    with TestClient(app) as client:
        got = client.post("/v1/setup/context/apply", json={"num_ctx": 106496}, headers=HEADERS).json()
    time.sleep(0.1)
    assert got.get("ok") is True and "reloading" not in got and reloaded == []
