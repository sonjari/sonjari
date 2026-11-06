# -*- coding: utf-8 -*-
"""판 안에서는 창 크기를 한 번만 잰다(2026-11-06) — 걸음마다 물었더니 한 걸음만 「작은 창」 조사 묶음(29개)이 되어 3~4만 토큰을 다시 읽었다."""
from __future__ import annotations

import inspect

from alture_jarvis import agent as agent_module


class _Cfg:
    tool_surface_compact_max_ctx = 32768

    def num_ctx_for(self, role):
        return 131072


class _Probe:
    def __init__(self, values):
        self.values = list(values)

    def effective_num_ctx(self, role):
        return self.values.pop(0) if self.values else 131072


def _agent(values):
    a = agent_module.BrowserAgent.__new__(agent_module.BrowserAgent)
    a.config = _Cfg()
    a.ollama = _Probe(values)
    return a


def test_a_momentary_small_reading_does_not_flip_the_job_to_the_small_window_list() -> None:
    a = _agent([131072, 16384, 131072])        # 둘째 걸음에 서버가 잠깐 16K 를 답한 셈
    first = a._job_window("job-1", "chat")
    second = a._job_window("job-1", "chat")
    assert first == second == 131072
    assert a._compact_tool_surface("chat", window=second) is False


def test_a_new_job_measures_again_and_old_jobs_are_forgotten() -> None:
    a = _agent([131072, 16384])
    assert a._job_window("job-1", "chat") == 131072
    assert a._job_window("job-2", "chat") == 16384
    assert ("job-1", "chat") not in a._job_windows


def test_the_loop_and_the_transcript_budget_use_the_job_window() -> None:
    src = inspect.getsource(agent_module.BrowserAgent)
    assert "window_for_job = self._job_window(job_id, model_role)" in src
    assert "window = self._job_window(job_id, model_role) if job_id else self._window(model_role)" in src
