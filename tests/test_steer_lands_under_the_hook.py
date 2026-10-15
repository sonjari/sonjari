"""일하는 도중 덧붙인 말은 손자리가 그때까지 한 말 **아래**에 붙는다 (2026-10-01, 대표: 「훅 밑에 들어가야 되는데 위에 들어가노」).

전에는 덧붙인 말을 위쪽 대화 목록에 붙여서, 맨 아래 「일하는 중」 블록의 손자리 말보다 늘 위에 보였다 — 무엇에 대한 말인지
순서가 뒤집혔다. 판이 끝난 뒤에는 서버가 질문 기록에 남긴 `steer_notes` 를 말풍선이 그린다(전엔 안 그려 기록에서 사라졌다).
"""

from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui" / "src"


def test_a_steer_goes_into_the_working_block_not_the_history() -> None:
    source = (UI / "WorkspaceApp.tsx").read_text(encoding="utf-8")
    steer = source.index("await client.steerJob(steerTarget, prompt);")
    echo = source.index("const localId = -Date.now();")

    assert steer < echo, "덧붙이기를 위쪽 목록에 붙인 뒤에 보내면 손자리 말보다 위에 보인다"
    assert "you: true" in source[:steer]
    assert "workspace-narration is-you" in source


def test_finished_messages_show_their_steer_notes() -> None:
    assert "steer_notes" in (UI / "workspace" / "MessageView.tsx").read_text(encoding="utf-8")
