"""작은 창의 빈 자리를 쓴다 — 서버가 알려 준 프롬프트에 자리가 남았으면 예산을 넓히기도 한다 (2026-10-12 밤).

같은 공식 9B · 같은 가격 조사인데 창 49,152 에서는 온전한 줄이 9 · 8 · 7 이고 창 32,768 에서는 고침 넷을 넣고도 3 · 1 · 2 · 1 · 2 였다.
판마다 가장 큰 프롬프트를 나란히 놓으니 창 49,152 는 4만 토큰으로 꽉 찼고, 창 32,768 은 2만 토큰에서 멈춰 있었다 — 쓸 자리
(8,192)를 빼고도 4천 토큰쯤이 비었다. 글자로 센 예산(토큰당 2자)이 조사 판의 실제 글(토큰당 3.8자쯤)보다 훨씬 조심스러웠고,
10-11 의 맞춤은 좁히기만 했다.

이 시험이 **못** 지키는 것: 걸음을 더 보여 주면 작은 모델이 판을 끝까지 가는가. 그건 실제 판으로만 본다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.transcript_policy import (
    _CHAT_OUTPUT_RESERVE_TOKENS, _TRANSCRIPT_BUDGET_CHARS, chat_transcript_budget, window_fitted_budget,
)

_WINDOW = 32_768
_SEEN = 20_145           # 그 판들의 가장 큰 프롬프트(20,115 ~ 20,961)


def test_idle_room_in_a_small_window_widens_the_next_budget() -> None:
    budget, _ = chat_transcript_budget(_WINDOW, "qwen3.5:9b")
    assert budget == 34_406
    room = _WINDOW - _CHAT_OUTPUT_RESERVE_TOKENS - _SEEN        # 4,431토큰이 비었다
    widened = window_fitted_budget(budget, num_ctx=_WINDOW, sent_chars=34_000, prompt_tokens=_SEEN, widen=True)
    assert widened == 34_000 + int(room * 1.5)
    assert widened > budget, "받은 예산을 넘어 넓힌다"
    # 끄면 예전 그대로다 — 받은 예산이 천장.
    assert window_fitted_budget(budget, num_ctx=_WINDOW, sent_chars=34_000, prompt_tokens=_SEEN) == budget


def test_widening_stops_at_the_target_and_turns_back_when_overshot() -> None:
    budget, _ = chat_transcript_budget(_WINDOW, "qwen3.5:9b")
    target = _WINDOW - _CHAT_OUTPUT_RESERVE_TOKENS
    # 과녁에 닿았으면 더 안 넓힌다.
    assert window_fitted_budget(budget, num_ctx=_WINDOW, sent_chars=45_000, prompt_tokens=target, widen=True) == 45_000
    # 촘촘한 글이 들어와 쓸 자리를 먹었으면 넓힌 것을 도로 좁힌다 — 좁히는 셈은 그대로다.
    back = window_fitted_budget(budget, num_ctx=_WINDOW, sent_chars=45_000, prompt_tokens=target + 2_000, widen=True)
    assert back == 45_000 - 3_000
    assert back == window_fitted_budget(60_000, num_ctx=_WINDOW, sent_chars=45_000, prompt_tokens=target + 2_000)


def test_walking_toward_the_target_never_passes_it_at_the_density_we_saw() -> None:
    """토큰당 3.8자인 글로 걸음마다 다시 재면 과녁 밑에서 다가간다 — 1.5자로 셈하므로 한 번에 넘지 않는다."""
    budget, _ = chat_transcript_budget(_WINDOW, "qwen3.5:9b")
    target = _WINDOW - _CHAT_OUTPUT_RESERVE_TOKENS
    fixed_tokens, density = 11_116, 3.8
    sent = budget
    seen = []
    for _ in range(6):
        prompt = fixed_tokens + int(sent / density)
        assert prompt <= target
        seen.append(prompt)
        sent = window_fitted_budget(budget, num_ctx=_WINDOW, sent_chars=sent, prompt_tokens=prompt, widen=True)
    assert seen == sorted(seen) and seen[-1] > seen[0] + 3_000, "걸음에 돌아가는 자리가 3천 토큰 넘게 는다"
    # 가장 촘촘하게 본 글(토큰당 1.7자)이어도 한 번 넓힌 것이 창을 넘지는 않는다 — 쓸 자리 안에서 받는다.
    dense_prompt = fixed_tokens + int(budget / 1.7)
    assert dense_prompt > target, "그런 글이면 받은 예산부터가 과녁을 넘는다"
    assert window_fitted_budget(budget, num_ctx=_WINDOW, sent_chars=budget, prompt_tokens=dense_prompt, widen=True) < budget


def test_a_big_window_has_nothing_to_widen() -> None:
    budget, _ = chat_transcript_budget(131_072, "big-27b")
    widened = window_fitted_budget(budget, num_ctx=131_072, sent_chars=70_000, prompt_tokens=38_000, widen=True)
    assert budget <= widened <= _TRANSCRIPT_BUDGET_CHARS, "큰 창은 전사 전체 상한이 천장이다"
    assert widened - budget < 10_000


def test_without_a_measurement_nothing_changes_either_way() -> None:
    assert window_fitted_budget(34_406, num_ctx=_WINDOW, sent_chars=0, prompt_tokens=0, widen=True) == 34_406
    assert window_fitted_budget(34_406, num_ctx=0, sent_chars=30_000, prompt_tokens=20_000, widen=True) == 34_406


def test_the_agent_widens_for_chat_jobs_and_records_it() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert 'widen=model_role != "code",' in source
    assert '"agent_transcript_widened_to_window"' in source and '"agent_transcript_fitted_to_window"' in source
