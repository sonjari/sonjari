"""짧은 토막이 연달아 네 번이면 답 글을 그 자리에서 끊는다 (2026-10-12).

작은 카드로 쓰는 사람의 말: 「고장 난 브라운관 TV 처럼 같은 말을 계속 반복했다」. 답 글의 되풀이를 끊는 장치(10-04)는
1,200자를 넘고 200자짜리 토막이 네 번 나와야 끊는다 — 짧은 문장 하나를 되풀이하면 열 번 넘게 쏟아진 뒤다.

운영의 지난 답 3,285개에 대 봤다: 새 판정에 걸리는 것 3개, 셋 다 진짜 맴도는 답(49,312 · 35,252 · 18,491자)이었고
멀쩡한 답은 0개였다. 표본의 글은 지어낸 것이다.
"""
from __future__ import annotations

from alture_jarvis import ollama

HEAD = "두 전략의 차이를 정리하겠습니다.\n\n"
LINE = "첫째로 대상 고객을 좁혀서 시작한다는 점이 다릅니다. "


def test_one_short_sentence_said_four_times_in_a_row_is_a_stutter() -> None:
    assert not ollama.content_is_stuttering(HEAD + LINE * 3)
    assert ollama.content_is_stuttering(HEAD + LINE * 4)
    # 이 길이에서는 예전 판정이 아직 못 본다 — 그래서 열 번 넘게 쏟아졌다.
    assert not ollama.content_is_looping(HEAD + LINE * 4)
    # 줄바꿈으로 끊어 되풀이해도 같다.
    assert ollama.content_is_stuttering(HEAD + (LINE.strip() + "\n") * 5)


def test_the_cut_point_does_not_have_to_land_on_a_sentence_edge() -> None:
    """글은 80자마다 본다 — 토막의 한가운데서 봐도 되풀이는 되풀이다."""
    looping = HEAD + LINE * 12
    hits = [end for end in range(len(HEAD) + 40, len(looping), 80) if ollama.content_is_stuttering(looping[:end])]
    assert hits and hits[0] < len(HEAD) + len(LINE) * 6, "여섯 번을 넘기기 전에 잡는다"


def test_ordinary_answers_are_left_alone() -> None:
    table = HEAD + "| 가게 | 값 | 배송비 |\n| --- | --- | --- |\n" + "".join(
        f"| 가게{n} | {n}9,000원 | 무료 |\n" for n in range(1, 9))
    assert not ollama.content_is_stuttering(table)
    listing = HEAD + "".join(f"{n}. 가상 상품 {n}번은 값이 {n}만 원이고 배송은 무료입니다.\n" for n in range(1, 12))
    assert not ollama.content_is_stuttering(listing)
    # 같은 말이 떨어져서 여러 번 나오는 것은 되풀이가 아니다(맺음말 · 후렴).
    refrain = HEAD + "".join(f"{LINE}다만 경우 {n}에서는 사정이 조금 다릅니다. " for n in range(1, 6))
    assert not ollama.content_is_stuttering(refrain)
    # 글자 종류가 적은 줄(빈 표 · 구분선)은 판정하지 않는다.
    assert not ollama.content_is_stuttering(HEAD + "| | | | | | | | | | |\n" * 30)
    assert not ollama.content_is_stuttering(HEAD + "--------------------\n" * 30)
    assert not ollama.content_is_stuttering("") and not ollama.content_is_stuttering("짧은 답")


def test_a_very_long_answer_is_checked_at_its_end_only() -> None:
    long_good = HEAD + "".join(f"문단 {n}: 서로 다른 내용을 적습니다. " for n in range(1, 4000))
    assert not ollama.content_is_stuttering(long_good)
    assert ollama.content_is_stuttering(long_good + LINE * 4)


def test_the_stream_asks_both_judges() -> None:
    import inspect

    source = inspect.getsource(ollama)
    assert "content_loop = content_is_looping(so_far) or content_is_stuttering(so_far)" in source
