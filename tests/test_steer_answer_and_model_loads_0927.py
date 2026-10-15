"""09-27 밤 실사용에서 잡은 셋.

1. 작업 도중 말을 덧붙인 판이 16걸음을 읽고도 「방향 전환: … 구글과 깃허브에서 직접 찾겠습니다.」 **한 줄**로 끝났다.
2. 대화 기록에 덧붙인 말이 안 남아, 이어진 「찾은 거 정리해줘」가 맥락 없이 「어ㅓㅇ」을 「어쌔인」으로 읽고 엉뚱한 것을 찾았다.
3. 「질문마다 모델이 올라갔다 내려간다」 — 누가 35B 를 내렸는지 아무 기록도 없었다(Ollama 는 로그 없이 떠 있고, 온텔릭은 조용히 내렸다).
"""

from __future__ import annotations

from _harvest import WATCHDOG, needs_monorepo_watchdog
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alture_jarvis.agent import BrowserAgent, _only_a_promise, _steer_notes_block
from alture_jarvis.ollama import OllamaClient

REPO = Path(__file__).resolve().parents[1]
SAID = "방향 전환: kin.naver 정보는 관련 없으니 버리고 **구글과 깃허브**에서 직접 찾겠습니다."


class _Events:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        self.sent.append((kind, payload))


def _agent() -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.events = _Events()
    agent._steer_inbox, agent._steer_applied, agent._steer_lock = {}, {}, threading.Lock()
    return agent


def test_the_real_final_line_is_recognised_as_a_promise() -> None:
    assert _only_a_promise(SAID), "그날 사람에게 간 최종 답 — 다음 걸음 예고다"


def test_the_steer_instruction_no_longer_asks_for_a_standalone_line() -> None:
    agent = _agent()
    agent.steer("job", "kin.naver 말고 구글이랑 깃허브에서 찾아")
    messages: list[dict[str, Any]] = []
    agent._apply_steer("job", messages, 12)
    content = messages[-1]["content"]
    assert "한 줄로 밝혀라" not in content, "그 지시가 「방향 전환」 한 줄을 부르고, 그 줄이 최종 답이 됐다"
    assert "최종 답이 돼 버린다" in content and "함께" in content
    assert _steer_notes_block(messages).endswith("- kin.naver 말고 구글이랑 깃허브에서 찾아")


def test_applied_notes_are_handed_back_once_for_the_conversation_record() -> None:
    agent = _agent()
    agent.steer("job", "구글이랑 깃허브에서")
    agent._apply_steer("job", [], 3)
    agent.steer("job", "표로 정리해")  # 아직 모델에게 안 간 말 — 새 작업으로 가는 몫이다
    assert agent.applied_steer("job") == ["구글이랑 깃허브에서"]
    assert agent.applied_steer("job") == []
    assert agent.take_leftover_steer("job") == ["표로 정리해"]


def test_the_final_answer_gate_rewrites_a_promise_and_the_record_keeps_the_notes() -> None:
    agent_source = (REPO / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    gate = agent_source.index('"agent_final_promise_rewrite"')
    assert agent_source.index("if answer and steps and _only_a_promise(answer)") < gate < agent_source.index(
        'raise RuntimeError("agent_empty_response")', gate), "빈 답 검사 앞, 사람에게 가기 전 마지막 자리"
    assert agent_source.count("_steer_notes_block(messages)") >= 2, "최종 정리와 다시 쓰기 둘 다 덧붙인 말을 싣는다"
    runtime_source = (REPO / "src" / "alture_jarvis" / "runtime.py").read_text(encoding="utf-8")
    assert '"applied_steer"' in runtime_source and "[작업 도중 덧붙인 말]" in runtime_source
    assert '"steer_notes": steer_notes' in runtime_source


def test_the_next_turn_reads_the_notes_from_the_record() -> None:
    from alture_jarvis.memory import _model_content

    record = {"role": "user", "content": "우리 경쟁자 알아봐줘",
              "metadata": {"model_prompt": "우리 경쟁자 알아봐줘\n\n[작업 도중 덧붙인 말]\n- 구글이랑 깃허브에서"}}
    assert "구글이랑 깃허브에서" in _model_content(record)


# ── 모델 내림·재적재 기록 ────────────────────────────────────────────────


def _client(tmp_path: Path) -> OllamaClient:
    client = OllamaClient.__new__(OllamaClient)
    client.config = SimpleNamespace(data_dir=tmp_path, ollama_base_url="http://127.0.0.1:11434")
    return client


def _rows(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "ollama_loads.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_slow_load_is_written_down_with_model_and_context(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = {"model": "qwen3.6:35b-a3b", "options": {"num_ctx": 131072}, "tools": [{}]}
    client._note_reload(body, {"load_duration": 40_000_000})  # 40ms — 상주 모델
    assert _rows(tmp_path) == []
    client._note_reload(body, {"load_duration": 29_100_000_000})  # 29.1초 — 그날 워치독이 본 재적재
    row = _rows(tmp_path)[0]
    assert row["event"] == "reloaded" and row["model"] == "qwen3.6:35b-a3b" and row["num_ctx"] == 131072 and row["load_ms"] == 29100


def test_unloading_another_model_is_written_down(tmp_path: Path, monkeypatch) -> None:
    posted: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def get(self, url: str) -> Any:
            return SimpleNamespace(json=lambda: {"models": [{"name": "qwen3.6:35b-a3b"}]})

        def post(self, url: str, json: dict[str, Any]) -> Any:
            posted.append(json)
            return SimpleNamespace(status_code=200)

    # conftest 가 진짜 Ollama 를 안 건드리려고 `_make_room_for` 를 비워 둔다 — 이 시험만 그걸 풀고 가짜 HTTP 로 본다.
    monkeypatch.undo()
    monkeypatch.setattr("alture_jarvis.ollama.httpx.Client", FakeClient)
    client = _client(tmp_path)
    client._make_room_for("plopfit-gemma4:latest")
    assert posted and posted[0] == {"model": "qwen3.6:35b-a3b", "messages": [], "keep_alive": 0}
    assert _rows(tmp_path)[0] == {**_rows(tmp_path)[0], "event": "unloaded_by_ontelic",
                                  "unloaded": "qwen3.6:35b-a3b", "for": "plopfit-gemma4:latest"}


@needs_monorepo_watchdog
def test_the_watchdog_starts_ollama_with_a_server_log() -> None:
    script = WATCHDOG.read_text(encoding="utf-8-sig")
    assert "-RedirectStandardError $ServerLog" in script
    assert script.count("Start-OllamaServe $exe") == 2, "재기동·첫 기동 둘 다"
    assert '-ArgumentList "serve" -WindowStyle Hidden\n' not in script.replace("`\n", "\n"), "출력 없이 띄우는 길이 남아 있다"
