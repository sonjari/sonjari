"""산출물 안전망 — **걸리는 자리와 물러나는 자리를 둘 다 센다.**

2026-09-11 사슬 벤치에서 yes24 판이 이렇게 끝났다: 상세 5곳을 읽고, 답에 3권의
쪽수·ISBN·주소를 완성한 표를 쓰고, **파일만 안 만들었다.** 걸음 17 / 예산 20,
시간도 남아 있었다. 안전망(`_forced_artifact_call`)은 바로 이 자리를 위해 전날
넣은 것인데 안 걸렸고, 왜 물러났는지 장부에 한 줄도 없었다.

이 파일이 없던 것도 원인이다 — 어제 넣은 장치에 시험이 **한 개도 없었다.**
"""

from __future__ import annotations

from alture_jarvis.agent import _forced_artifact_decision
from alture_jarvis.plan import check as check_plan, extract as extract_plan

YES24_PROMPT = (
    "YES24에서 파이썬 책 3권의 쪽수와 ISBN 을 조사해서 마크다운 문서로 만들어줘. "
    "상세페이지 URL 도 같이 넣어줘."
)

# 실제로 그 판이 낸 답이다(옮겨 적지 않고 장부에서 그대로 떠 왔다).
YES24_ANSWER = """YES24에서 조사한 파이썬 도서 3권의 정보입니다.

# YES24 파이썬 도서 조사 결과

한 줄 요약: YES24에서 파이썬 관련 도서 3권의 상세 정보를 확인했다. 2026-09-11 기준.

| 도서명 | 쪽수 | ISBN13 | 상세페이지 URL |
| :--- | :--- | :--- | :--- |
| Do it! 점프 투 파이썬 | 432쪽 | 9791163034735 | https://www.yes24.com/product/goods/119293186 |
| 혼자 공부하는 파이썬 | 552쪽 | 9791162245651 | https://www.yes24.com/product/goods/109625396 |
| 파워 유저를 위한 파이썬 EXPRESS | 732쪽 | 9791194630500 | https://www.yes24.com/product/goods/171542281 |

출처
* YES24 상품 상세 페이지 각 항목 (ISBN, 쪽수 정보)
"""


def _read_steps(count: int = 5) -> list[dict[str, object]]:
    """상세를 열어 읽은 걸음들. 쓰기 도구는 한 번도 안 불렀다."""
    return [
        {
            "tool": "browser_extract",
            "ok": True,
            "evidence": {"url": f"https://www.yes24.com/product/goods/{100 + index}"},
        }
        for index in range(count)
    ]


def _plan_results(steps: list[dict[str, object]]):
    plan = extract_plan(YES24_PROMPT, has_named_source=True)
    sources = [str((step.get("evidence") or {}).get("url") or "") for step in steps]
    return check_plan(plan, sources=[url for url in sources if url], steps=steps)


def test_table_in_the_answer_but_no_file_gets_written_for_us() -> None:
    """표까지 써 놓고 파일을 안 만들었으면 **대신 저장한다.**"""
    steps = _read_steps()
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, YES24_ANSWER, YES24_PROMPT
    )
    assert reason == ""
    assert call is not None
    tool, args = call
    assert tool == "local_write_document"
    # 시킨 형식을 따라간다. 마크다운으로 만들라고 했으면 .md 다.
    assert str(args["path"]).endswith(".md")
    blocks = args["blocks"]
    table = next(block for block in blocks if block.get("type") == "table")
    # 내용을 짓지 않는다 — 답에 있던 세 줄이 머리줄과 함께 그대로 온다.
    assert len(table["rows"]) == 4
    assert table["rows"][1][2] == "9791163034735"


def test_it_says_why_it_backed_off_when_the_answer_is_too_short() -> None:
    """빈 문서를 만드는 것이 제일 나쁘다 — 물러나되 **이유를 남긴다.**"""
    steps = _read_steps()
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, "조사를 마쳤습니다.", YES24_PROMPT
    )
    assert call is None
    assert reason.startswith("answer_too_short:")


def test_prose_without_a_table_or_heading_is_not_an_artifact_answer() -> None:
    steps = _read_steps()
    prose = "파이썬 책을 살펴봤습니다. " * 30
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, prose, YES24_PROMPT
    )
    assert call is None
    assert reason.startswith("no_table_or_heading:")


def test_a_failed_write_is_not_pushed_again() -> None:
    """도구가 안 된 것이지 모델이 안 부른 것이 아니다. 같은 것을 다시 누르지 않는다."""
    steps = _read_steps() + [{"tool": "local_write_document", "ok": False, "evidence": {}}]
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, YES24_ANSWER, YES24_PROMPT
    )
    assert call is None
    assert reason == "already_attempted"


def test_no_artifact_asked_means_no_reason_to_record() -> None:
    """산출물을 안 시킨 판은 물러난 것이 아니다 — 장부를 어지럽히지 않는다."""
    prompt = "YES24에서 파이썬 책 3권의 쪽수를 알려줘."
    steps = _read_steps()
    plan = extract_plan(prompt, has_named_source=True)
    sources = [str((step.get("evidence") or {}).get("url") or "") for step in steps]
    results = check_plan(plan, sources=sources, steps=steps)
    call, reason = _forced_artifact_decision(results, steps, YES24_ANSWER, prompt)
    assert call is None
    assert reason == ""


def test_an_empty_reply_after_a_pushback_does_not_lose_the_table() -> None:
    """되받기 뒤 **빈 답**이 와도 직전 턴의 표를 파일로 옮긴다.

    2026-09-12 실측으로 잡은 진짜 원인이다. 계획층이 「산출물이 없다」고 되받으면
    모델은 할 말을 이미 다 했으므로 빈 메시지로 답한다. 그 순간 안전망이
    이번 턴의 길이(0자)를 재고 물러났다 — 표는 직전 턴에 멀쩡히 있었는데도.

    판 장부에 `answer_too_short:0/200` 이 찍혀서야 보였다.
    """
    steps = _read_steps()
    results = _plan_results(steps)

    # 되받기 전: 표가 있는 답 → 걸린다
    fired, reason = _forced_artifact_decision(results, steps, YES24_ANSWER, YES24_PROMPT)
    assert fired is not None and reason == ""

    # 되받은 다음 턴: 모델이 빈 메시지를 준다
    current_turn = ""
    # 고치기 전에는 이 자리에서 물러났다
    lost, lost_reason = _forced_artifact_decision(
        results, steps, current_turn, YES24_PROMPT
    )
    assert lost is None
    assert lost_reason == "answer_too_short:0/200"

    # 고친 뒤: 계획 대조를 통과했던 직전 답으로 떨어진다
    kept, kept_reason = _forced_artifact_decision(
        results, steps, current_turn or YES24_ANSWER, YES24_PROMPT
    )
    assert kept_reason == ""
    assert kept is not None
    assert kept[1]["blocks"] == fired[1]["blocks"]
