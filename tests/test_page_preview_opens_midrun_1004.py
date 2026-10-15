"""페이지를 만든 코드 판은 화면 손이 열린다 (2026-10-04 도구 전수조사 2번).

화면 손 묶음은 요청에 「프론트·페이지를 만들…」 같은 낱말이 있어야 열렸다. 「index.html 로 계산기 만들어 줘」·
「build a landing page」는 낱말표에 안 걸린다 — 모델은 페이지를 만들고 띄운 뒤(`local_preview_page` 는 늘 있다)
열 손이 없어 `code_tool_not_in_active_profile` 로 튕겼다(운영 기록 aurora-replay 36baec94: 네 번).

낱말을 더 붙이지 않는다. **걸음 기록**으로 판정한다 — 페이지를 실제로 만들었거나 띄웠으면 연다.
"""
from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis import agent as agent_module
from alture_jarvis.code_runtime import (
    CODE_PREVIEW_TOOL_NAMES,
    PREVIEW_GUIDANCE,
    launched_a_page,
    select_code_tool_profile,
    touched_local_page,
    with_page_preview,
)


def _step(tool: str, ok: bool = True, **arguments: Any) -> dict[str, Any]:
    evidence = {"url": arguments["url"]} if "url" in arguments and tool != "browser_open" else {}
    return {"tool": tool, "ok": ok, "arguments": arguments, "evidence": evidence}


# --- 구멍이 실제로 있었다 -------------------------------------------------------

def test_a_page_request_without_the_keywords_starts_without_screen_hands() -> None:
    """이 시험은 구멍을 **기록**한다 — 낱말표를 넓혀 닫지 않았다는 뜻이다."""
    for prompt in ("index.html 로 계산기 만들어 줘", "build a landing page for my bakery"):
        profile = select_code_tool_profile(prompt)
        assert "browser_open" not in profile.tool_names, prompt
        assert "local_preview_page" in profile.tool_names, prompt  # 띄우는 손은 늘 있다


# --- 여는 조건 -----------------------------------------------------------------

def test_writing_an_html_file_counts_as_launching_a_page() -> None:
    assert launched_a_page([_step("local_write_file", path="C:/work/index.html")])
    assert launched_a_page([_step("local_apply_edit", path="site/About.HTM")])
    assert launched_a_page([_step("local_preview_page", path="C:/work")])


def test_scripts_and_styles_alone_do_not_open_the_screen_hands() -> None:
    """`.js`·`.css` 는 페이지가 아닌 저장소(Node 서버)에서도 쓴다 — 그 판에 화면 손 15개를 얹지 않는다."""
    steps = [
        _step("local_write_file", path="server/routes.js"),
        _step("local_write_file", path="src/theme.css"),
        _step("local_write_file", path="app.py"),
    ]

    assert not launched_a_page(steps)


def test_a_failed_write_or_preview_does_not_count() -> None:
    assert not launched_a_page([_step("local_write_file", ok=False, path="index.html")])
    assert not launched_a_page([_step("local_preview_page", ok=False, path="C:/work")])


# --- 넓힌 프로필 ---------------------------------------------------------------

def test_the_widened_profile_has_the_screen_hands_and_the_same_guidance() -> None:
    core = select_code_tool_profile("index.html 로 계산기 만들어 줘")

    wide = with_page_preview(core)

    assert CODE_PREVIEW_TOOL_NAMES <= wide.tool_names
    assert core.tool_names <= wide.tool_names  # 빼는 것은 없다
    assert wide.name == core.name + "+preview"
    assert PREVIEW_GUIDANCE in wide.guidance
    # 처음부터 열린 판과 같은 손이다 — 판 도중 열렸다고 다른 묶음이 되지 않는다.
    opened_at_start = select_code_tool_profile("프론트 페이지를 만들어 줘")
    assert wide.tool_names == opened_at_start.tool_names


def test_widening_is_idempotent() -> None:
    already = select_code_tool_profile("프론트 페이지를 만들어 줘")

    assert with_page_preview(already) is already
    assert with_page_preview(with_page_preview(select_code_tool_profile("버그 고쳐줘"))).name.count("preview") == 1


# --- 만진 화면 -----------------------------------------------------------------

def test_touching_a_local_page_is_seen_even_without_a_page_file() -> None:
    """플라스크(`app.py`)로 화면을 만들고 자기 서버를 연 판 — 페이지 파일을 쓴 적이 없다."""
    steps = [
        _step("local_write_file", path="app.py"),
        _step("browser_open", url="http://localhost:5000/"),
        _step("browser_click", ref="e3"),
    ]

    assert touched_local_page(steps)


def test_looking_only_or_touching_an_outside_site_is_not_touching_a_local_page() -> None:
    """09-21 「또 보기만」 다섯 판이 되살아나지 않게 — 열기·읽기만 한 판은 아니다."""
    looked = [_step("browser_open", url="http://127.0.0.1:8000/"), _step("browser_read"), _step("browser_snapshot")]
    outside = [_step("browser_open", url="https://example.com/"), _step("browser_click", ref="e1")]
    failed = [_step("browser_open", url="http://localhost:3000/"), _step("browser_click", ok=False, ref="e1")]

    assert not touched_local_page(looked)
    assert not touched_local_page(outside)
    assert not touched_local_page(failed)


# --- 배선 ---------------------------------------------------------------------

def test_the_loop_widens_the_profile_and_keeps_read_hands_for_touched_pages() -> None:
    source = inspect.getsource(agent_module)

    assert "and launched_a_page(steps)" in source
    assert "code_tool_profile = with_page_preview(code_tool_profile)" in source
    assert '"reason": "made_a_page"' in source
    assert "screen_check=_made_a_page(steps) or touched_local_page(steps)," in source
    # 넓히기는 손을 정하기 **전**이다 — 뒤면 이번 턴의 손에 안 들어간다.
    widen = source.index("code_tool_profile = with_page_preview(code_tool_profile)")
    assert widen < source.index("active_code_tools = (\n                code_tools_after_look_pushback(")
    # 멈췄다 다시 도는 판에 같은 안내가 한 벌 더 붙지 않는다.
    assert "if not any(item.get(\"content\") == preview_note for item in messages):" in source
