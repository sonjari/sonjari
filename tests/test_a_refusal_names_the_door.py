"""막을 때는 **어디로 가야 하는지 같이 말한다** (2026-09-21 실전).

## 무슨 일이 있었나

Code 모드에서 모델이 파일 둘을 만들고 마지막에 **검증 스크립트를 돌리려다** 죽었다:

    step 16  sandbox_run  ✕  실패했습니다 — code_tool_not_in_active_profile
    (판 끝)             coding_verification_missing

거절문은 이랬다:

    "현재 요청에 허용된 도구 중에서 다시 선택하라."

**어느 도구인지 말하지 않았다.** 그런데 이 판의 프로필(core)에는 `local_run_shell`
과 `local_run_project_command` 가 **이미 들어 있었다.** 문이 있는데 안내가 없어서
모델이 못 찾았고, 거의 다 한 판이 마지막 한 걸음에서 무너졌다.

바로 위 분기(`web_pages_are_read_with_the_browser`)는 제대로 한다 —
「browser_site_search 로 찾고 browser_open_result → browser_extract 로 읽어라」.
이 분기만 빠져 있었다.

## 규칙

이 저장소의 교훈 그대로다 — **막기만 하면 모델은 같은 벽에 계속 부딪친다.**
거절은 세 가지를 담아야 한다: 왜 안 되는지 · **무엇을 쓰면 되는지** · 판은 계속 간다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.code_runtime import (
    CODE_CORE_TOOL_NAMES,
    select_code_tool_profile,
)


# ── ① 실전에서 죽은 그 문들이 실제로 열려 있는가 ────────────────────────────
def test_the_doors_the_model_needed_are_in_the_core_profile() -> None:
    """검증을 돌릴 문이 core 에 없으면 안내를 고쳐도 소용이 없다."""
    assert "local_run_shell" in CODE_CORE_TOOL_NAMES
    assert "local_run_project_command" in CODE_CORE_TOOL_NAMES


def test_a_plain_code_request_still_gets_those_doors() -> None:
    profile = select_code_tool_profile("이 저장소 정리해 줘")
    assert "local_run_shell" in profile.tool_names
    assert "local_run_project_command" in profile.tool_names
    assert "sandbox_run" not in profile.tool_names, "격리 실행은 부를 때만 열린다"


# ── ② 거절문이 갈 곳을 말하는가 ─────────────────────────────────────────────
def test_the_refusal_for_a_missing_tool_names_what_to_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 이것이 실전에서 빠져 있던 것 — 「다시 선택하라」만 하고 어디인지 안 말했다."""
    from alture_jarvis.code_runtime import refusal_for_tool_outside_profile

    profile = select_code_tool_profile("이 저장소 정리해 줘")
    refusal = refusal_for_tool_outside_profile("sandbox_run", profile)

    assert refusal["error"] == "code_tool_not_in_active_profile"
    instruction = refusal["instruction"]
    assert "local_run_shell" in instruction or "local_run_project_command" in instruction, (
        f"갈 곳을 안 말했다: {instruction}"
    )


def test_the_refusal_lists_real_tools_not_invented_ones() -> None:
    """안내가 프로필에 없는 이름을 대면 모델은 그 다음 벽에 부딪친다."""
    from alture_jarvis.code_runtime import refusal_for_tool_outside_profile

    profile = select_code_tool_profile("이 저장소 정리해 줘")
    named = [
        word.strip(" `,.")
        for word in refusal_for_tool_outside_profile("sandbox_run", profile)["instruction"].split()
        if word.strip(" `,.").startswith(("local_", "browser_", "skill_"))
    ]
    assert named, "도구 이름을 하나도 안 댔다"
    for name in named:
        assert name in profile.tool_names, f"프로필에 없는 {name} 을(를) 안내했다"


def test_a_research_tool_outside_the_profile_is_pointed_at_research() -> None:
    """조사 도구를 부르면 「조사를 켜는 말」 쪽으로 보내야 한다 — 셸로 우회시키면 안 된다."""
    from alture_jarvis.code_runtime import refusal_for_tool_outside_profile

    profile = select_code_tool_profile("이 저장소 정리해 줘")
    instruction = refusal_for_tool_outside_profile("browser_search", profile)["instruction"]
    assert "조사" in instruction


def test_the_refusal_still_says_which_profile_is_on() -> None:
    from alture_jarvis.code_runtime import refusal_for_tool_outside_profile

    profile = select_code_tool_profile("이 저장소 정리해 줘")
    assert refusal_for_tool_outside_profile("sandbox_run", profile)["profile"] == profile.name
