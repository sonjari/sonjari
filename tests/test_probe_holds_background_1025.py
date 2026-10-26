"""상한 재기 동안 노는 시간 일(서기 · 앞부분 데우기)을 멈춘다 · 올리지 못한 것을 「안 들어감」으로 말하지 않는다 (2026-10-25).

이 PC 실측(02:09~02:12): 재기가 모델을 내리고 16K 로 올리려는 3분 동안 서기가 옛 대화를 30초마다 정리하며
대화 창(128K)으로 같은 모델을 불렀다. 재기 요청은 차례를 못 받아 3분 만에 끊겼고, 화면은
「가장 작은 칸도 그래픽카드에 안 들어감 — 더 작은 모델을 권함」이라고 했다.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SetupService
from alture_jarvis.ollama import OllamaClient


def _client() -> OllamaClient:
    client = OllamaClient.__new__(OllamaClient)
    client.config = SimpleNamespace(front_prime_enabled=True, ollama_base_url="http://127.0.0.1:1",
                                    ollama_keep_alive="30m", data_dir=Path("."))
    return client


def test_background_calls_wait_while_held() -> None:
    client = _client()
    closed = []
    client.__dict__["_background_client"] = SimpleNamespace(close=lambda: closed.append("bg"))
    client.__dict__["_prime_client"] = SimpleNamespace(close=lambda: closed.append("prime"))
    with client.hold_background():
        # 들어가는 순간 나가 있던 서기 · 데우기 부르기를 끊는다.
        assert closed == ["bg", "prime"]
        assert client.background_held()
        client.__dict__["_prime_client"] = None
        # 모델 서버로 아무것도 보내지 않고 None — 주소가 닫힌 포트라 보냈다면 오래 걸리거나 예외 흔적이 남는다.
        started = time.monotonic()
        assert client.background_chat("s", "u", model="m", options={"num_ctx": 131072}) is None
        assert time.monotonic() - started < 0.5
        client.__dict__["_front_dirty"] = True
        client.__dict__["_last_send_at"] = 0.0
        assert client.front_prime_due() is False
    assert not client.background_held()


def test_hold_nests_and_releases_on_error() -> None:
    client = _client()
    try:
        with client.hold_background():
            with client.hold_background():
                pass
            assert client.background_held()
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert not client.background_held()


def test_the_scribe_skips_while_the_model_is_measured(tmp_path: Path) -> None:
    from alture_jarvis.models import JarvisState
    from alture_jarvis.runtime import JarvisRuntime

    asked = []
    ollama = _client()
    ollama.background_chat = lambda s, u, **k: asked.append(u)
    fake = SimpleNamespace(
        config=SimpleNamespace(data_dir=tmp_path / "data", scribe_enabled=True, scribe_folders=str(tmp_path),
                               model_for=lambda role: "m", num_ctx_for=lambda role: 8192),
        state=SimpleNamespace(snapshot=lambda: SimpleNamespace(state=JarvisState.IDLE)),
        ollama=ollama,
        SCRIBE_QUIET_SEC=JarvisRuntime.SCRIBE_QUIET_SEC,
    )
    fake._scribe_folders = lambda: JarvisRuntime._scribe_folders(fake)
    with ollama.hold_background():
        assert JarvisRuntime._scribe_tick(fake) == {"skipped": "모델 재는 중"}
    assert asked == []


class _SlowCard:
    """첫 칸부터 올리다 시간이 다 된다 — 카드가 작아서가 아니라 차례를 못 받아서."""

    def post(self, url, body, timeout):
        if url.endswith("/api/show"):
            return {"model_info": {"qwen35moe.context_length": 262144}, "capabilities": ["tools"]}
        if body.get("keep_alive") == 0:
            return {}
        raise TimeoutError("timed out")

    def get(self, url):
        return {"models": []}


def _service(tmp_path: Path, card) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.model_roles = {"chat": "qwen3.6:35b-a3b"}
    service = SetupService(config, post=card.post, get=card.get)
    service.gpu_snapshot = lambda: {"gpus": []}
    return service


def test_a_first_rung_that_never_loaded_is_not_called_too_big(tmp_path: Path) -> None:
    result = _service(tmp_path, _SlowCard()).measure_context_ceiling()
    assert not result["ok"]
    assert result["stopped"] == "model_load_timeout", result
    assert result["error"] == "first_rung_failed", result


class _SpillCard:
    """첫 칸을 올리면 절반이 CPU 로 샌다 — 이건 정말 카드가 작은 것이다."""

    def __init__(self) -> None:
        self.loaded = 0

    def post(self, url, body, timeout):
        if url.endswith("/api/show"):
            return {"model_info": {"qwen35moe.context_length": 262144}, "capabilities": ["tools"]}
        if body.get("keep_alive") == 0:
            self.loaded = 0
            return {}
        self.loaded = int(body["options"]["num_ctx"])
        return {"response": "1, 2, 3", "eval_count": 64, "eval_duration": 4_000_000_000, "load_duration": 1}

    def get(self, url):
        if url.endswith("/api/ps") and self.loaded:
            return {"models": [{"name": "qwen3.6:35b-a3b", "size": 20 * 2**30, "size_vram": 10 * 2**30,
                                "context_length": self.loaded}]}
        return {"models": []}


def test_a_first_rung_that_spilled_to_cpu_is_still_too_big(tmp_path: Path) -> None:
    result = _service(tmp_path, _SpillCard()).measure_context_ceiling()
    assert not result["ok"] and result["stopped"] == "not_fully_on_gpu", result
    assert result["error"] == "no_context_fits"


def test_the_router_note_keeps_why_the_draft_was_dropped() -> None:
    """02:03 판처럼 초안을 다 쓰고 버리면 까닭 · 초 · 글자 수가 판 기록에 남는다."""
    from alture_jarvis.events import EventBus
    from alture_jarvis.runtime import JarvisRuntime

    fake = SimpleNamespace(events=EventBus())
    fake.events.publish("agent_route_selected", {"route": "agent", "reason": "old_job"})
    since = fake.events.sequence
    fake.events.publish("agent_route_draft_discarded", {"job_id": "j1", "chars": 1573})
    fake.events.publish("agent_route_selected", {"route": "agent", "reason": "answer_had_unsourced_particulars",
                                                 "numbers": ["1,011", "26"], "prompt": "긴 질문"})
    JarvisRuntime._remember_router_note(fake, "j1", since, 7.68)
    note = fake.__dict__["_router_notes"]["j1"]
    assert note == {"seconds": 7.68, "discarded_chars": 1573, "route": "agent",
                    "reason": "answer_had_unsourced_particulars", "numbers": ["1,011", "26"]}


def test_a_worktree_room_sees_the_main_folders_last_talk(tmp_path: Path, monkeypatch) -> None:
    """클로드 앱이 별도 작업 공간으로 연 방(마케팅 방 · 10-25)도 원래 저장소의 바로 앞 대화 색인을 받는다."""
    from alture_jarvis import claude_hooks

    projects = tmp_path / "projects"
    main = projects / "E----------"
    room = projects / "E------------claude-worktrees-zen-driscoll-f4c94d"
    main.mkdir(parents=True)
    room.mkdir()
    (main / "mainsession.jsonl").write_text("{}\n", encoding="utf-8")
    (room / "newroom.jsonl").write_text("{}\n", encoding="utf-8")
    asked = []

    def story(base, token, session):
        asked.append(session)
        return {"index": "- 레딧 답글 (10-24) 줄 1"}

    monkeypatch.setattr(claude_hooks, "_story", story)
    out = claude_hooks._new_session({"transcript_path": str(room / "newroom.jsonl"), "session_id": "newroom"}, "b", "t")
    assert asked == ["mainsession"]
    assert out and "레딧 답글" in out["hookSpecificOutput"]["additionalContext"]


class _GapCard:
    """KV 가 1K 당 `kv` GB · 카드 `vram` GB — 그 사이 어딘가가 진짜 상한이다."""

    def __init__(self, vram: float = 20.0, weights: float = 12.0, kv: float = 0.04) -> None:
        self.vram, self.weights, self.kv, self.loaded, self.loads = vram, weights, kv, 0, []

    def post(self, url, body, timeout):
        if url.endswith("/api/show"):
            return {"model_info": {"qwen35moe.context_length": 262144}, "capabilities": ["tools"]}
        if body.get("keep_alive") == 0:
            self.loaded = 0
            return {}
        self.loaded = int(body["options"]["num_ctx"])
        self.loads.append(self.loaded)
        share = min(1.0, self.vram / (self.weights + self.kv * self.loaded / 1024))
        tps = 100.0 if share >= 1.0 else 15.0
        return {"response": "1, 2, 3", "eval_count": 64, "eval_duration": int(64 / tps * 1e9), "load_duration": 1}

    def get(self, url):
        if url.endswith("/api/ps") and self.loaded:
            size = self.weights + self.kv * self.loaded / 1024
            return {"models": [{"name": "qwen3.6:35b-a3b", "size": int(size * 2**30),
                                "size_vram": int(min(size, self.vram) * 2**30), "context_length": self.loaded}]}
        return {"models": []}


def test_squeeze_tries_two_sizes_in_the_gap_and_keeps_the_applied_size(tmp_path: Path) -> None:
    from alture_jarvis.model_setup import read_ceilings, squeeze_gap

    card = _GapCard()  # 12 + 0.04·K ≤ 20 → 200K 까지 들어간다
    service = _service(tmp_path, card)
    service.config.ollama_num_ctx = 131072
    first = service.measure_context_ceiling()
    assert first["ceiling"] == 131072 and squeeze_gap(first) == (131072, 262144)
    card.loads.clear()
    out = service.squeeze_context_ceiling()
    # 196608(합격) → 229376(불합격) 두 번만 올리고, 끝에는 적용된 128K 로 다시 올려 둔다.
    assert card.loads == [196608, 229376, 131072], card.loads
    assert out["ok"] and out["ceiling"] == 196608 and out["squeezed"]["to"] == 196608
    saved = read_ceilings(tmp_path / "data")["qwen3.6:35b-a3b"]
    assert saved["ceiling"] == 196608 and len(saved["steps"]) == 7


def test_nothing_to_squeeze_when_the_top_rung_passed_or_the_gap_is_small(tmp_path: Path) -> None:
    from alture_jarvis.model_setup import squeeze_gap

    assert squeeze_gap({"ceiling": 262144, "steps": [{"num_ctx": 262144, "passed": True}]}) is None
    assert squeeze_gap({"ceiling": 16384, "steps": [{"num_ctx": 24576, "passed": False, "why": "not_fully_on_gpu"}]}) is None
    # 올리지도 못한 칸(시간 초과)은 「안 들어간다」의 증거가 아니라 좁힐 사이로 치지 않는다.
    assert squeeze_gap({"ceiling": 32768, "steps": [{"num_ctx": 65536, "passed": False, "why": "model_load_timeout"}]}) is None
    service = _service(tmp_path, _GapCard())
    assert service.squeeze_context_ceiling()["error"] == "not_measured"
