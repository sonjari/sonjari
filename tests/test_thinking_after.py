"""그래픽카드 한 장 PC 의 생각 번역 (인수인계 H3) — 판이 끝난 뒤, 주 모델로, 실패해도 원문은 남는다."""

from __future__ import annotations

from alture_jarvis.thinking_ko import split_for_translation, translate_after


def test_long_thinking_is_cut_on_paragraphs_and_nothing_is_lost() -> None:
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(12))
    chunks = split_for_translation(text, limit=1500)
    assert len(chunks) > 1 and all(len(c) <= 1500 for c in chunks)
    assert "".join(c.replace("\n\n", "") for c in chunks).replace(" ", "") == text.replace("\n\n", "").replace(" ", "")


def test_a_failed_chunk_keeps_the_original() -> None:
    calls: list[str] = []

    def ask(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 2:
            raise TimeoutError("model busy")
        return "번역됨"

    text = "First part. " * 200 + "\n\n" + "Second part. " * 200 + "\n\n" + "Third."
    out = translate_after(text, ask)
    assert out.startswith("번역됨") and "Second part." in out
