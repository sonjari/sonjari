"""부르기 기록 이름표 (2026-10-21 · `docs/측정계획_첫글자대기_2026-10-21.ko.md` 1단계).

20초 넘은 첫 글자 대기 105건 중 생각 켬/끔 뒤집기 15건 · 기록 줄어듦 21건이 **어느 부르기에서** 나왔는지 몰라 짐작만 했다.
- `purpose`: 왜 불렀나(평소 걸음 · 정리 다시 부르기 여덟 자리 · 생각 예산 뒤 · 접기 정리 장)
- `prefix_kept` / `prev_messages`: 지난번에 보낸 대화와 앞에서부터 몇 개가 같은가(캐시는 처음 달라진 곳부터 깨진다)
- `cut`: 우리가 중간에 끊은 부르기도 남긴다(예전엔 기록 줄보다 먼저 빠져나가 안 남았다)
동작은 바꾸지 않는다 — 보내는 메시지는 같다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from alture_jarvis import ollama as ollama_mod
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.ollama import OllamaClient, tagged_call

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"


def test_tags_nest_and_inner_wins() -> None:
    with tagged_call(purpose="step", prefix_kept=4):
        with tagged_call(purpose="budget_second"):
            assert ollama_mod._CALL_TAGS.get() == {"purpose": "budget_second", "prefix_kept": 4}
        assert ollama_mod._CALL_TAGS.get()["purpose"] == "step"
    assert ollama_mod._CALL_TAGS.get() == {}


def _client(tmp_path: Path) -> OllamaClient:
    return OllamaClient(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"))


def _rows(tmp_path: Path) -> list[dict]:
    path = tmp_path / "data" / "model_calls.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_log_line_carries_tags_and_cut(tmp_path) -> None:
    client = _client(tmp_path)
    body = {"model": "m", "messages": [{"role": "system", "content": "s"}], "think": True, "options": {}}
    with tagged_call(purpose="final", prefix_kept=7, prev_messages=9, model="덮으면 안 됨"):
        client._log_call(body, {"prompt_eval_count": 100}, 0.5, 0.6)
    client._log_call(body, {}, 0.1, 30.0, cut="budget", elapsed=142.37)
    first, second = _rows(tmp_path)
    assert first["purpose"] == "final" and first["prefix_kept"] == 7 and first["prev_messages"] == 9
    assert first["model"] == "m", "이름표가 기록 칸을 덮으면 안 된다"
    assert "cut" not in first
    assert second["cut"] == "budget" and second["elapsed_sec"] == 142.37 and "purpose" not in second
    assert "thinking_chars" not in first, "글자 수를 안 준 부르기에 0 을 지어 넣지 않는다"


def test_log_line_splits_thinking_and_answer(tmp_path) -> None:
    """10-22: 분업 판 「글 쓰기 16분」을 생각과 답으로 못 나눴다 — 생성 토큰은 둘을 합친 수다."""
    client = _client(tmp_path)
    body = {"model": "m", "messages": [], "think": "medium", "options": {}}
    client._log_call(body, {"eval_count": 900}, 0.1, 1.0, thinking_chars=2400, content_chars=180)
    (row,) = _rows(tmp_path)
    assert row["thinking_chars"] == 2400 and row["content_chars"] == 180 and row["eval_tokens"] == 900


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names: set[str] = set()
    ollama_tools: list = []


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        raise AssertionError("도구를 실행하지 않는다")


class _Recorder:
    """부르기 순간의 이름표와 받은 메시지를 적는 가짜 모델."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict, list]] = []

    def chat_messages_stream(self, messages, *, tools=None, temperature=0.1, think=False, on_chunk=None, **kwargs):
        self.calls.append((dict(ollama_mod._CALL_TAGS.get()), list(messages)))
        return {"role": "assistant", "content": "답입니다."}


def _agent(tmp_path) -> tuple[BrowserAgent, _Recorder]:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True)
    model = _Recorder()
    agent = BrowserAgent(config, model, _Gateway(), _Browser(), _Tools(), JobStore(tmp_path / "j.db"), EventBus())
    return agent, model


def test_prefix_kept_counts_same_leading_messages(tmp_path) -> None:
    agent, model = _agent(tmp_path)
    first = [{"role": "system", "content": "지시"}, {"role": "user", "content": "일"}]
    agent._model_message(first, job_id="j", tools=None, think=True)
    grown = first + [{"role": "assistant", "content": "a"}, {"role": "user", "content": "b"}]
    agent._model_message(grown, job_id="j", tools=None, think=True)
    changed = [first[0], {"role": "user", "content": "바뀐 일"}, *grown[2:]]
    agent._model_message(changed, job_id="j", tools=None, think=True)

    tags = [call[0] for call in model.calls]
    assert tags[0] == {}, "그 판의 첫 부르기에는 견줄 것이 없다"
    assert tags[1]["prev_messages"] == len(model.calls[0][1])
    assert tags[1]["prefix_kept"] == len(model.calls[0][1]), "앞이 그대로면 지난번 것 전부가 같아야 한다"
    assert tags[2]["prefix_kept"] < tags[1]["prefix_kept"], "중간이 바뀌면 거기서 끊겨야 한다"


def test_text_only_purpose_reaches_the_call(tmp_path) -> None:
    agent, model = _agent(tmp_path)
    agent._text_only_message([{"role": "user", "content": "정리해"}], job_id="j", think=False, purpose="short_redo")
    assert model.calls[-1][0]["purpose"] == "short_redo"


def test_every_wrap_up_site_is_named() -> None:
    """정리 다시 부르기 자리가 이름 없이 남으면 「text_only」로 묶여 또 짐작하게 된다."""
    source = (SRC / "agent.py").read_text(encoding="utf-8")
    calls = [match.start() for match in re.finditer(r"self\._text_only_message\(", source)]
    assert len(calls) >= 8
    for start in calls:
        end = source.index(")\n", start) if ")\n" in source[start:] else len(source)
        window = source[start:start + 2600]
        assert re.search(r'purpose="[a-z_]+"', window.split("self._text_only_message(", 2)[1]), \
            f"이름 없는 정리 다시 부르기: {source.count(chr(10), 0, start) + 1}줄"
