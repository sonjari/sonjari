"""다른 대화에서 찾아 붙인 기억은 「이번에 본 값」의 근거가 아니다 (2026-10-30 판 58761894).

「Continue: open StayFab, … stop at Confirm and pay.」에 도구 0번 · 16초로 「Done — reached the Confirm and pay page ·
₩456,581」을 냈다. 그 금액은 20분 앞 **다른 대화**(MCP 로 맡긴 판)에서 **다른 숙소**의 값이었다. 대화 기억의
「관련 기록 찾아 붙이기」가 그 글을 이번 판에 붙였고, 근거 없는 숫자 검사가 그 글까지 「알려진 값」으로 쳐서
근거 없는 숫자를 3개(문턱 4 미만)로 셌다. 같은 대화의 앞 판 답 · 배운 사실은 지금처럼 근거로 친다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.memory import RECALLED_MEMORY_HEADER
from alture_jarvis.runtime import _grounding_texts

ASK = (
    "Find me an Airbnb near Shibuya Station for Nov 14-16, 2 adults, entire home, rated 4.8+. Compare the top 3 "
    "by their latest reviews, pick the best, and take it to the Confirm and pay page. Don't log in or pay."
)
COMPARED = (
    "## Top 3 by rating\n\n| # | Listing | Rating | Price |\n|---|---|---|---|\n"
    "| 1 | **StayFab** | **4.94** (281) | from $349 |\n| 2 | **Triphome East Shinjuku 2** | **4.89** (439) | from $345 |\n\n"
    "## What I could not complete\nI was **not able to take it to the Confirm and pay page.** StayFab is a multi-apartment "
    "listing, so it shows a **Choose apartment** step before Reserve."
)
OTHER_ROOM = (
    "Here are the results of the Airbnb search near Shibuya Station: **listing name:** Triphome East Shinjuku 2 "
    "**price per night:** ₩228,291 (₩456,581 ÷ 2 nights) **total price:** ₩456,581 — I reserved and stopped at "
    "Confirm and pay, choose apartment, StayFab compared."
)
CONTINUE = "Continue: open StayFab, choose an apartment, click Reserve and stop at Confirm and pay."
INVENTED = (
    "I've completed the task.\n\n## Done — reached the Confirm and pay page\n\n"
    "1. Opened StayFab and chose **1LDK, 36 m²** (₩456,581 total).\n2. Clicked **Reserve**, then **Continue**.\n\n"
    "- Total: **₩456,581**\n- ₩228,291 × 2 nights + ₩17,943 service fee + ₩110,347 cleaning fee"
)


def _runtime(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


class _Model:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat_message(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return {"content": self.content, "tool_calls": []}

    chat_message_stream = chat_message

    def chat(self, *args: Any, **kwargs: Any) -> str:
        return self.content


def _stayfab(runtime) -> None:
    runtime.memory.add_message("mcp-other", "user", "Airbnb Shibuya Station Nov 14-16 Confirm and pay StayFab")
    runtime.memory.add_message("mcp-other", "assistant", OTHER_ROOM)
    runtime.memory.add_message("s1", "user", ASK)
    runtime.memory.add_message("s1", "assistant", COMPARED)


def test_the_recalled_block_really_reaches_the_router(tmp_path: Path) -> None:
    """전제 — 다른 대화의 그 글이 이번 판의 기억에 붙는다(붙지 않으면 아래 시험은 아무것도 재지 않는다)."""
    runtime = _runtime(tmp_path)
    _stayfab(runtime)
    history = runtime._memory_context("s1", CONTINUE)
    recalled = [m for m in history if str(m.get("content") or "").startswith(RECALLED_MEMORY_HEADER)]
    assert recalled and "456,581" in recalled[0]["content"]


def test_a_continue_that_invents_a_finished_checkout_goes_to_hands(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _stayfab(runtime)
    runtime.ollama = _Model(INVENTED)

    route, answer, observation = runtime._general_route(CONTINUE, "s1", job_id="job-1")

    assert route == "agent" and answer == ""
    assert (observation or {}).get("route_reason") == "unsourced_particulars"
    assert {"456581", "228291"} <= set((observation or {}).get("numbers") or [])


def test_values_from_this_conversation_still_answer_directly(tmp_path: Path) -> None:
    """역방향 — 같은 대화의 앞 판에 있던 값을 다시 정리한 답은 그대로 나간다."""
    runtime = _runtime(tmp_path)
    _stayfab(runtime)
    runtime.ollama = _Model(
        "Triphome East Shinjuku 2 had more reviews: 439, against 281 for StayFab. StayFab rates higher, 4.94 against "
        "4.89, and starts from $349 against $345."
    )

    route, answer, _ = runtime._general_route("Which of those had more reviews?", "s1", job_id="job-2")

    assert route == "answer" and answer.startswith("Triphome East Shinjuku 2 had more reviews")


def test_only_the_recalled_block_is_dropped() -> None:
    history = [
        {"role": "system", "content": "현재 질문과 관련해 **이전에 배운 사실**이다.\n- 사용자 PC: RAM 64GB"},
        {"role": "system", "content": RECALLED_MEMORY_HEADER + "현재 질문과 충돌하면…\n[2026-10-29 · assistant · 세션 mcp-x] ₩456,581"},
        {"role": "user", "content": ASK},
        {"role": "assistant", "content": COMPARED},
        "plain text turn",
    ]
    kept = _grounding_texts(history)
    assert len(kept) == 4
    assert not any("456,581" in text for text in kept)
    assert any("64GB" in text for text in kept) and COMPARED in kept and "plain text turn" in kept
