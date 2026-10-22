"""「밀기 켬/끔」 스위치 (2026-10-21) — 끄면 판 도중에 계획 요구로 모델을 밀지 않고, 끝 검사는 그대로 한다.

10-20 대표 결정: 「플랜이 모델을 종속시킨다」 → ② 확실한 것만 민다(먼저) → ③ 모델이 읽고 끝 검사만(재서 정함).
이 스위치는 ③을 재기 위한 것이다. 같은 모델 · 같은 요청에서 켬/끔만 바꿔 견준다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import test_forced_commit as base
from alture_jarvis import agent as agent_module
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.jobs import JobStore

PROMPT = "네이버 블로그에 '점검' 이라는 제목으로 세 줄 쓰고 임시저장까지 해줘. 발행은 하지 마."


def _run(tmp_path: Path, **kwargs):
    config = base._Config(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    gateway = base._RecordingGateway()
    runner = BrowserAgent(config, base._StopsAfterPreparing(), gateway, base._FakeBrowser(), base._FakeTools(), store, base._EventBus())
    job = store.create_job("chat", "agent", {"prompt": PROMPT})
    store.claim_next()
    return runner.run(PROMPT, job_id=job["id"], origin="chat", **kwargs), gateway


def test_push_off_stops_pushing_but_the_end_check_still_tells_the_truth(tmp_path: Path) -> None:
    result, gateway = _run(tmp_path, plan_push=False)
    called = [name for name, _ in gateway.calls]
    assert called == ["naver_blog_prepare_post"], f"끄면 하네스가 사슬을 대신 밀지 않는다: {called}"
    assert result.verification["forced_commits"] == 0
    assert result.verification["plan_pushbacks"] == 0
    assert result.verification["plan_push"] is False
    # 끝 검사는 그대로 — 임시저장이 안 나갔으니 다 끝냈다고 적지 않는다.
    assert result.verification["completion_state"] != "complete"


def test_push_on_is_the_default_and_is_recorded(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)
    assert result.verification["plan_push"] is True
    assert result.verification["forced_commits"] == 3


def test_the_switch_reads_the_setting_when_the_request_does_not_say(tmp_path: Path) -> None:
    assert JarvisConfig(data_dir=tmp_path).plan_push_enabled is True
    source = inspect.getsource(agent_module.BrowserAgent.run)
    assert 'getattr(self.config, "plan_push_enabled", True)) if plan_push is None else bool(plan_push)' in source
    # 코드 판은 늘 켠다(끄면 「최종 답만 써라」가 안 걸린다) · 끝 검사 · 사람 확인 문은 원래 계획을 본다.
    assert 'loop_plan = plan if (plan_push_on or model_role == "code") else []' in source
