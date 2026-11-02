"""마무리 답이 생각을 뒤집어 앞 기록 전체를 다시 읽지 않게 (2026-10-30 대표 스크린샷 「약 7.8만 토큰 · 첫 글자 전 45초」).

그 판: 마지막 걸음(생각 끔) 3.9초 → 마무리 답(생각 켬) 57.2초 · 늘어난 것 3,500토큰. 앞 기록이 길면 직전 걸음과 같은 설정.
"""
from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis.agent import _KEEP_THINK_FOR_CACHE_CHARS, BrowserAgent


def _call(last: bool | None, think: bool, chars: int) -> bool:
    seen: dict = {}
    fake = SimpleNamespace(
        _last_think={} if last is None else {"job": last},
        _text_only_message_inner=lambda messages, **kw: (seen.update(kw) or ({}, 0)),
    )
    BrowserAgent._text_only_message(fake, [{"role": "user", "content": "가" * chars}], job_id="job", think=think, purpose="final")
    return seen["think"]


def test_a_long_history_keeps_the_last_steps_setting() -> None:
    assert _call(last=False, think=True, chars=_KEEP_THINK_FOR_CACHE_CHARS + 10) is False


def test_a_short_history_thinks_as_the_policy_says() -> None:
    assert _call(last=False, think=True, chars=1000) is True


def test_nothing_known_or_already_the_same_is_left_alone() -> None:
    assert _call(last=None, think=True, chars=200_000) is True
    assert _call(last=True, think=True, chars=200_000) is True
    assert _call(last=True, think=False, chars=200_000) is True   # 걸음이 생각 중이었으면 마무리도 생각 — 뒤집지 않는다
