"""전사 예산은 **실제로 쓸** 컨텍스트로 잡는다 — 다른 앱의 32K 러너에 맞췄으면 32K.

★ 2026-09-28 헤르메스 대결 T1 온텔릭 1판: 32K 러너를 받아 쓰면서 예산은 설정값 128K(17만 자)로 잡았다. 창이 넘쳐 Ollama 가 두 번
잘랐고(`truncated = 1`), 읽은 상세 본문이 밀려나 모델이 「파이썬 완전 정복 42,000원」처럼 **열어 본 적 없는 책과 가격**을 지어냈다.
"""

from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis.agent import BrowserAgent, chat_transcript_budget


def _agent(effective: int | None, configured: int = 131072) -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.config = SimpleNamespace(num_ctx_for=lambda role: configured, tool_surface_compact_max_ctx=40_000)
    agent.ollama = SimpleNamespace(effective_num_ctx=lambda role: effective) if effective else SimpleNamespace()
    return agent


def test_the_window_is_the_runner_we_actually_use() -> None:
    assert _agent(32768)._window("chat") == 32768
    assert _agent(None)._window("chat") == 131072, "못 물어보면 설정값"


def test_a_shared_small_runner_shrinks_the_budget_and_the_tool_surface() -> None:
    agent = _agent(32768)

    assert chat_transcript_budget(agent._window("chat"))[0] < chat_transcript_budget(131072)[0] // 4
    assert agent._compact_tool_surface("chat"), "32K 에서 도구 설명을 안 줄이면 첫 걸음부터 창의 절반을 쓴다"
