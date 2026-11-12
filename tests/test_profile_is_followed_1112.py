"""「나에 대한 지침」의 말투 지시가 지시로 실린다 (2026-11-12 맥 판 ca3566f3).

대표가 「친절하게 말해줘 반말하지 말고」를 넣었는데 답은 그대로 「~다」체였다. 뿌리 둘:
① 지침 머리말이 전부를 「관련될 때만 활용하는 프로필」로 소개했다 ② 일하는 모드는 「사용자 맥락:」 머리로만 실었다.
모델이 실제로 따르는지는 시험이 아니라 운영 판으로 잰다 — 여기서는 **지시로 읽히게 실리는지**만 막는다.
"""
from __future__ import annotations

from alture_jarvis import agent as agent_module
from alture_jarvis.profile import PROFILE_INTRO, profile_block


def test_the_intro_says_manner_instructions_are_always_followed() -> None:
    assert "모든 답" in PROFILE_INTRO and "말투" in PROFILE_INTRO
    # 사실(하는 일 등)은 여전히 관련될 때만 — 매 답에 끼워 넣지 않는다.
    assert "관련될 때만" in PROFILE_INTRO


def test_the_work_mode_uses_the_same_block_as_chat() -> None:
    source = open(agent_module.__file__, encoding="utf-8").read()
    assert 'f"사용자 맥락:\n{system_context}"' not in source
    assert "profile_block(system_context)" in source
    block = profile_block("- 하지 말 것: 반말하지 말고")
    assert block.startswith(PROFILE_INTRO) and "<jarvis-profile>" in block


def test_the_manner_section_points_at_the_profile() -> None:
    manner = agent_module._VOICE_AND_MANNER
    assert "<jarvis-profile>" in manner and "따른다" in manner
