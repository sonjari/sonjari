"""모델 호출 한 번의 벽시계 시간이 판 기록에 남는다 (2026-10-07 코딩 사다리 기준선).

판의 시간을 「모델 서버 · 도구 · 그 밖」으로 가르려는데 「그 밖」(판마다 2~6초)을 더 가를 수가 없었다 —
서버가 잰 시간(`telemetry`)과 「첫 글자까지」만 남고, 호출 전체의 벽시계 시간과 끝난 시각이 없었다.
"""
from __future__ import annotations

import time

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult


class _Tools:
    names = {"browser_search", "browser_read"}
    ollama_tools = [{"type": "function", "function": {"name": "browser_search", "description": "search",
                                                       "parameters": {"type": "object", "properties": {}}}}]


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        return ToolResult(True, name, result={"url": "https://example.test/result", "title": "결과", "text": "근거"})


class _Browser:
    def status(self):
        return {"started": True}


class _SlowModel:
    """서버가 잰 시간을 돌려주고, 호출마다 0.05초를 쓴다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        time.sleep(0.05)
        observation = {"model": "test", "telemetry": {"total_duration": 1_000_000}}
        if self.calls == 1:
            return {"role": "assistant", "content": "", "_inference": observation,
                    "tool_calls": [{"function": {"name": "browser_search", "arguments": {"query": "x"}}}]}
        return {"role": "assistant", "content": "확인한 근거를 바탕으로 답변합니다.", "_inference": observation}


def test_each_model_call_records_its_wall_time_and_when_it_ended(tmp_path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    model = _SlowModel()
    runner = BrowserAgent(config, model, _Gateway(), _Browser(), _Tools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": "검색해줘"})
    store.claim_next()
    before = time.time()

    result = runner.run("검색해줘", job_id=job["id"], origin="chat")

    observations = result.verification["inference_observations"]
    assert len(observations) >= 2
    for item in observations:
        # 윈도우의 sleep(0.05)은 0.047초에 끝나기도 한다 — 문턱은 「모델이 쓴 시간이 들어 있다」만 본다.
        assert item["wall_sec"] >= 0.03, "호출 하나의 벽시계 시간"
        assert before <= item["ended_at"] <= time.time(), "끝난 시각 — 앞 호출과의 사이가 도구·검사에 쓴 시간이다"
        assert item["telemetry"] == {"total_duration": 1_000_000}, "서버가 잰 값은 그대로 둔다"
    assert observations[0]["ended_at"] <= observations[1]["ended_at"]
