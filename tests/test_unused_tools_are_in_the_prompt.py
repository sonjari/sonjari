"""등록만 돼 있고 **한 번도 안 불린** 도구들.

2026-08-13 L3 시험에서 드러났다. `audit_log` 를 세어 보니 `tool_executed` 0 회인
쓰기 도구가 절반이었고, 그중 둘은 시험에서 **그 자리에 필요한데도** 안 불렸다:

    "다나와 정렬을 낮은가격순으로 바꿔서 상위 3개"
      → 11걸음 쓰고 "정렬을 바꾸지 못했다". `browser_select_option` 호출 0회.

    "아까 저장한 블로그 임시저장 되돌려줘"
      → 블로그 홈으로 가서 화면을 훑다가 "블로그 주소를 알려 주세요". `undo_action` 0회.

둘 다 도구는 멀쩡했다. **프롬프트에 없었을 뿐이다.** 오늘만 세 번째로 확인한 모양이다
(드라이브 읽기 없음 → 사이트 검색 없음 → 있어도 순서에 없음). 프롬프트에 있는 도구
(`browser_load_more`·`browser_pick_suggestion`·`browser_scroll`)는 실제로 불린다.

★ 이 시험의 한계를 알고 쓸 것. 문자열이 프롬프트에 있는지만 본다 — **모델이 그래도 안
따르면 이 시험은 통과하면서 기능은 죽어 있다.** 그래서 라이브로도 확인해야 한다.
결정론으로 못 박을 수 있는 것(라우팅)은 프롬프트가 아니라 코드로 박는 게 맞다
(`test_named_source_routing.py`). 도구 **발견**은 프롬프트가 유일한 통로라 여기 남는다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import AGENT_SYSTEM_PROMPT


@pytest.mark.parametrize(
    "tool",
    [
        "browser_select_option",
        "undo_list",
        "undo_action",
        # 이미 있던 것들 — 빠지면 같은 사고가 난다.
        "browser_load_more",
        "browser_pick_suggestion",
        "browser_scroll",
        "browser_site_search",
        "browser_dismiss_dialog",
    ],
)
def test_the_tool_is_findable_in_the_prompt(tool: str) -> None:
    assert tool in AGENT_SYSTEM_PROMPT, f"{tool} 은 순서에 없으면 안 불린다"


def test_sorting_and_filter_dropdowns_point_at_select_option() -> None:
    """"정렬"이라는 말이 나오면 어느 도구인지 프롬프트가 답해야 한다."""
    assert "정렬을 바꾸라거나" in AGENT_SYSTEM_PROMPT
    assert "`browser_select_option` 이다" in AGENT_SYSTEM_PROMPT


def test_it_knows_select_option_only_works_on_real_selects() -> None:
    """커스텀 드롭다운에 쓰면 `not_a_select:<태그>` 로 답한다 — 그때 클릭으로 가야 한다."""
    assert "not_a_select" in AGENT_SYSTEM_PROMPT
    assert "네이티브 `<select>` 전용" in AGENT_SYSTEM_PROMPT


def test_undoing_is_a_tool_not_a_browser_errand() -> None:
    assert "`undo_list` → `undo_action`" in AGENT_SYSTEM_PROMPT
    assert "손으로 지우려 하지 마라" in AGENT_SYSTEM_PROMPT


def test_it_knows_undo_id_can_be_left_empty() -> None:
    """"방금 거"가 사람이 쓰는 말이다. 비워서 부르면 최근 것이 되돌려진다."""
    assert "비워서 부르면 가장 최근 것" in AGENT_SYSTEM_PROMPT


def test_it_knows_some_things_it_cannot_undo() -> None:
    """`automatic=false` 는 사람이 손으로 해야 한다 — 자비스가 억지로 하면 안 된다."""
    assert "automatic=false" in AGENT_SYSTEM_PROMPT
    assert "manual_hint" in AGENT_SYSTEM_PROMPT
