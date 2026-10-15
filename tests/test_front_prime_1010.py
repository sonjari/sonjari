"""앱을 켠 뒤 한 번, 고정 앞부분(도구 목록 + 첫 시스템 메시지)을 데워 둔다 (2026-10-10).

대표: 「뒤죽박죽으로 시간이 오래 걸린다 — 원인을 정확히 진단해 보자」. Ollama 기록의 호출별 읽기·쓰기를 세어 보니, 모델을 막 올린
뒤의 첫 일은 앞부분 2만 토큰을 처음부터 읽는 데 20초를 쓰고 있었다. 서버는 저장점이 찍힌 자리로만 되돌아가는데, 켠 직후에는
저장점이 하나도 없다. 앞부분만 든 짧은 요청을 미리 읽혀 두면 「앞부분의 끝」에 저장점이 남는다.

잰 값(이 PC · 27B · 128K · 모델을 내렸다 올린 뒤 같은 짧은 일 세 판씩): 일 전체 28.9 · 28.2 · 28.7초 → 11.6초대,
첫 걸음이 읽는 양 19,761토큰(19.7초) → 328토큰(1.1초).

★ **켠 뒤 한 번만이다.** 일이 끝날 때마다 데우게 만들었다가 재 보고 뺐다 — 데우는 요청은 서버에 살아 있는 대화를 앞부분까지
  잘라 낸다. 지난 사흘 기록으로 어림하니 얻는 것(약 1,800초)보다 잃는 것(약 5,800초)이 컸다.

눈금 주의: 이 시험은 **무엇을 보내고 언제 안 보내는가**만 본다. 실제로 빨라지는지는 Ollama 기록의 읽은 토큰 수로 쟀다.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import alture_jarvis.ollama as ollama_module
from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient

MODEL = "some-model:27b"
TOOLS = [{"type": "function", "function": {"name": f"tool_{i}", "description": "d", "parameters": {}}} for i in range(30)]
SYSTEM = {"role": "system", "content": "고정 지침"}


class Server:
    """모델 서버 흉내 — 올라가 있는 모델과 창을 알려 주고, 받은 요청을 적어 둔다."""

    def __init__(self) -> None:
        self.resident = {MODEL: 65536}
        self.posts: list[dict] = []
        self.closed = 0
        self.hold: threading.Event | None = None

    def client(self, *_a, **_kw):
        server = self

        class Http:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return None

            def close(self):
                server.closed += 1
                self.dead = True
                if server.hold is not None:
                    server.hold.set()

            def get(self, url: str):
                body = {"models": [{"name": name, "context_length": ctx} for name, ctx in server.resident.items()]}
                return SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: body, text="")

            def post(self, url: str, json=None):  # noqa: A002 — httpx 의 이름 그대로
                server.posts.append(json)
                if server.hold is not None and (json.get("options") or {}).get("num_predict") == 1:
                    server.hold.wait(5.0)
                    if getattr(self, "dead", False):
                        raise RuntimeError("connection closed")
                reply = {"message": {"role": "assistant", "content": "ok"}, "prompt_eval_count": 19000,
                         "prompt_eval_duration": 21_000_000_000, "load_duration": 0}
                return SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: reply, text="")

        return Http()


@pytest.fixture()
def rig(tmp_path: Path, monkeypatch):
    server = Server()
    monkeypatch.setattr(ollama_module.httpx, "Client", server.client)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out", control_token="t")
    config.model_roles = {"chat": MODEL, "code": MODEL}

    def started() -> OllamaClient:
        """앱을 (다시) 켠 것."""
        client = OllamaClient(config)
        monkeypatch.setattr(client, "_make_room_for", lambda *_a, **_kw: None)
        return client

    return SimpleNamespace(server=server, started=started, config=config)


def _big(extra: list[dict] | None = None, **over) -> dict:
    body = {"model": MODEL, "messages": [SYSTEM, {"role": "user", "content": "뉴스 찾아 줘"}, *(extra or [])], "tools": TOOLS,
            "stream": False, "think": "medium", "options": {"num_ctx": 65536, "temperature": 0.1, "num_predict": 4096}}
    body.update(over)
    return body


def _small() -> dict:
    return {"model": MODEL, "messages": [{"role": "system", "content": "너는 사실만 뽑는 도구다"}, {"role": "user", "content": "x"}],
            "stream": False, "think": False, "options": {"num_ctx": 65536, "temperature": 0}}


def _send(rig, client: OllamaClient, body: dict) -> None:
    with rig.server.client() as http:
        client._post_chat(http, body)


def _quiet(client: OllamaClient) -> None:
    client.__dict__["_last_send_at"] = time.monotonic() - 60


def _used_once(rig) -> None:
    """어제 큰 일을 한 번 한 앱 — 앞부분이 디스크에 남아 있다."""
    _send(rig, rig.started(), _big())


def test_after_a_start_it_primes_exactly_the_front_of_the_last_big_request(rig) -> None:
    _used_once(rig)
    client = rig.started()
    assert client.front_prime_due(), "켠 직후 — 방금 올린 모델은 아무것도 읽은 적이 없다"

    done = client.prime_front("idle")

    assert done["ok"] is True and done["prompt_tokens"] == 19000 and done["read_ms"] == 21000.0
    prime = rig.server.posts[-1]
    assert prime["tools"] == TOOLS and prime["messages"] == [SYSTEM, {"role": "user", "content": "."}]
    assert prime["think"] == "medium", "생각 스위치가 앞부분에 그려지는 모델이 있다 — 실제 요청과 같아야 한다"
    assert prime["options"] == {"num_ctx": 65536, "temperature": 0.1, "num_predict": 1}
    assert prime["keep_alive"] == rig.config.ollama_keep_alive, "짧게 찌르면 데우는 호출이 모델을 내리는 주범이 된다"
    [row] = [json.loads(line) for line in (rig.config.data_dir / "front_primes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert row["ok"] is True and row["tools"] == 30 and row["reason"] == "idle"


def test_it_primes_once_and_never_again_after_jobs_or_small_calls(rig) -> None:
    """일이 끝날 때마다 데우면 서버에 살아 있는 대화를 앞부분까지 잘라 낸다 — 재 보니 얻는 것보다 잃는 것이 컸다(머리말)."""
    _used_once(rig)
    client = rig.started()
    assert client.prime_front()["ok"]
    sent = len(rig.server.posts)

    for body in (_big(), _big([{"role": "assistant", "content": "찾았습니다"}]), _small(), _small()):
        _send(rig, client, body)
        _quiet(client)
        assert not client.front_prime_due()
    assert len(rig.server.posts) == sent + 4, "데우는 요청이 더 나가지 않았다"


def test_a_big_job_that_arrives_first_makes_priming_unnecessary(rig) -> None:
    """큰 일이 제 앞부분을 직접 읽으면 그 대화가 서버에 생긴다 — 그 뒤에 데우면 방금 그 대화를 지운다."""
    _used_once(rig)
    client = rig.started()
    _send(rig, client, _big())
    _quiet(client)
    assert not client.front_prime_due()


def test_small_calls_alone_are_not_remembered(rig) -> None:
    client = rig.started()
    _send(rig, client, _small())
    _quiet(client)
    assert not client.front_prime_due(), "기억한 앞부분이 없다"
    assert not (rig.config.data_dir / "front_prime.json").exists()
    assert rig.started().prime_front()["skipped"] == "no_front"


def test_it_waits_for_a_quiet_moment(rig) -> None:
    _used_once(rig)
    client = rig.started()
    _send(rig, client, _small())
    assert not client.front_prime_due(), "방금 요청이 나갔다 — 곁가지 호출이 끝나기를 기다린다"
    _quiet(client)
    assert client.front_prime_due()


def test_it_never_loads_a_model_or_changes_the_window(rig) -> None:
    _used_once(rig)
    client = rig.started()
    before = len(rig.server.posts)

    rig.server.resident = {}
    assert client.prime_front()["skipped"] == "not_resident"
    rig.server.resident = {"someone-elses-model:9b": 32768}
    assert client.prime_front()["skipped"] == "not_resident", "남의 모델이 올라가 있으면 밀어내지 않는다"
    rig.server.resident = {MODEL: 32768}
    assert client.prime_front()["skipped"] == "window_differs", "다른 창으로 찌르면 러너를 갈아 끼운다"

    assert len(rig.server.posts) == before
    assert not client.front_prime_due(), "못 데운 뒤에는 잠깐 쉬었다 다시 본다(매 3초마다 묻지 않는다)"
    client.__dict__["_front_retry_at"] = 0.0
    assert client.front_prime_due(), "아직 못 데웠으니 차례는 남아 있다"


def test_a_real_request_cuts_the_priming_off(rig) -> None:
    _used_once(rig)
    client = rig.started()
    rig.server.hold = threading.Event()
    result: dict = {}
    worker = threading.Thread(target=lambda: result.update(client.prime_front()))
    worker.start()
    for _ in range(200):
        if client.__dict__.get("_prime_client") is not None:
            break
        time.sleep(0.01)

    _send(rig, client, _small())
    worker.join(5.0)

    assert result["ok"] is False and result["cancelled"] is True
    assert rig.server.closed >= 1
    _quiet(client)
    assert client.front_prime_due(), "끊긴 것은 데운 것이 아니다 — 작은 호출이 지나간 뒤 다시 한다"


def test_the_switch_turns_it_off(rig) -> None:
    _used_once(rig)
    rig.config.front_prime_enabled = False
    assert not rig.started().front_prime_due()


def test_a_changed_front_replaces_the_remembered_one(rig) -> None:
    _used_once(rig)
    other = [*TOOLS, {"type": "function", "function": {"name": "new_tool", "description": "d", "parameters": {}}}]
    _send(rig, rig.started(), _big(tools=other))

    rig.started().prime_front()

    assert len(rig.server.posts[-1]["tools"]) == 31
    assert json.loads((rig.config.data_dir / "front_prime.json").read_text(encoding="utf-8"))["tools"] == other


def test_health_says_how_long_ago_the_model_last_answered(rig) -> None:
    client = rig.started()
    assert client.health()["last_ok_age_sec"] is None
    _send(rig, client, _small())
    age = client.health()["last_ok_age_sec"]
    assert age is not None and 0 <= age < 5
    assert client.health()["front_prime"]["enabled"] is True
