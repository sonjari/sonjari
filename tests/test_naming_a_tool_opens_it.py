"""도구 **이름을 직접 적으면 그 도구를 연다** (2026-09-21 실전 재측정).

## 무슨 일

코덱스 패치 후 AURORA 재측정(job `36baec94`). 걸음은 66 → 24 로 크게 줄었는데
**실패했다.** 걸음 11·16 이 이랬다:

    11 X browser_click     code_tool_not_in_active_profile
    16 X browser_snapshot  code_tool_not_in_active_profile

그런데 사용자 프롬프트에는 이렇게 적혀 있었다:

    "... browser_open, browser_snapshot, browser_click 으로 화면과 상호작용을 직접 확인해"

**사용자가 이름을 대고 시켰는데 우리가 막았다.** 모델은 시킨 대로 하려다 두 번 튕겼고,
판이 `coding_verification_missing` 으로 죽었다.

## 왜 생겼나

`_PREVIEW_HINTS` 가 「프론트/웹앱/화면을 만들·고치」 같은 **의도 낱말**만 본다.
이 문장은 의도를 안 적고 **도구 이름을 적었다.** 낱말표에 구멍이 난 것이다 —
이 저장소가 가장 여러 번 겪은 병이다.

## 규칙 (이미 정해져 있던 것)

`_RESEARCH_HINTS` 주석에 이미 적혀 있다:

    낱말을 더 붙이는 대신 원칙으로 둔다: 표면을 이름으로 지목하면 그 표면을 연다.
    이것은 의도 추측이 아니라 **명시적 요청**이라 넓혀도 안전하다.

조사 쪽에는 그 원칙이 있는데 **프리뷰 쪽에는 없었다.** 같은 원칙을 여기에도 둔다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.code_runtime import select_code_tool_profile

AURORA = (
    "AURORA라는 한밤의 오로라 항해 관측소를 index.html 단일 파일로 만들어줘. "
    "깊은 밤 색감과 빛나는 오로라를 사용하고, 서로 다른 3개 관측 목적지 카드와 "
    "각 목적지의 관측 확률을 보여줘. 카드와 버튼은 클릭해 반응해야 해. "
    "완성 뒤 local_preview_page로 열고 browser_open, browser_snapshot, browser_click으로 "
    "화면과 상호작용을 직접 확인해. local_run_project_command로 검증하고 "
    "검증용 임시 파일은 삭제해."
)


# ── ★ 실전에서 죽은 자리 ────────────────────────────────────────────────────
def test_the_tools_the_user_named_are_open() -> None:
    """사용자가 이름을 대고 시킨 것을 막으면, 모델은 시킨 일을 못 하고 판이 죽는다."""
    tools = select_code_tool_profile(AURORA).tool_names
    for named in ("browser_open", "browser_snapshot", "browser_click", "local_preview_page"):
        assert named in tools, f"{named} 을(를) 이름으로 시켰는데 막혔다"


@pytest.mark.parametrize("said", [
    "browser_snapshot 으로 확인해 줘",
    "browser_click 해서 눌러 봐",
    "browser_screenshot 찍어 줘",
    "만든 화면을 browser_snapshot 으로 봐",
])
def test_naming_any_preview_tool_opens_the_preview_set(said: str) -> None:
    tools = select_code_tool_profile(said).tool_names
    assert "browser_snapshot" in tools and "browser_click" in tools, said


# ── 안 부른 판까지 열면 안 된다 ─────────────────────────────────────────────
def test_a_plain_repo_task_does_not_get_browser_hands() -> None:
    """도구를 과하게 주면 Qwen 의 선택 정확도가 떨어진다 — 이 파일 위쪽 실측."""
    tools = select_code_tool_profile("이 저장소 정리하고 시험 돌려 줘").tool_names
    assert "browser_click" not in tools
    assert "browser_snapshot" not in tools


def test_the_intent_route_still_works() -> None:
    """이름을 안 대도 프론트 의도면 열려야 한다 — 코덱스가 넣은 길을 안 깨뜨린다."""
    tools = select_code_tool_profile("프론트엔드 페이지 하나 만들고 눌러서 확인해 줘").tool_names
    assert "browser_snapshot" in tools and "browser_click" in tools


def test_mentioning_a_tool_inside_a_filename_is_not_a_request() -> None:
    """`browser_click.md 를 읽어 줘` 는 그 도구를 쓰겠다는 말이 아니다."""
    tools = select_code_tool_profile("docs/browser_click.md 파일을 읽고 요약해 줘").tool_names
    assert "browser_click" not in tools


def test_a_refusal_is_not_what_the_user_asked_for() -> None:
    """★ 이 시험의 요점 — 사용자가 이름을 댄 도구는 거절 대상이 아니다."""
    profile = select_code_tool_profile(AURORA)
    assert "browser_snapshot" in profile.tool_names
    assert "preview" in profile.name, profile.name
