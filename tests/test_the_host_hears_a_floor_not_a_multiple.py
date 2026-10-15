"""호스트에게는 「N배 절감」이 아니라 **센 값에서 나온 하한**을 준다 (2026-09-22, 사장님 지시).

## 무엇이 문제였나

위임 결과의 `cost` 는 호스트가 직접 했을 때의 실측 두 건(60만·97만 토큰)을 쪽수로 나눠 곱한 **범위 추정**이었다. 사용자에게 전하는
말로는 좋지만 「그 숫자가 어디서 나왔나」에 약하고, 그 실측 자체가 캐싱을 끄고 잰 값이라 반박당할 자리가 있다.

## 하한은 어디서 나오나

    로컬에서 읽은 본문 글자 수   ← 걸음 기록의 `char_count`. **센 값**이다.
    ÷ 4.5                        ← 실측: 한글 본문 토큰당 1.66~1.72자 · 영어 4.43자. 가장 큰 쪽보다 크게 나눠 하한으로 만든다.

한글 본문이면 실제 토큰은 이보다 2.6배쯤 더 많다. 하한이라 일부러 낮게 잡았다.

## 지킬 것

1. 성공한 **읽기**만 센다 — 실패한 걸음·쓰기·`char_count` 없는 걸음은 안 센다(부풀리지 않는다).
2. 「N배」는 만들지 않는다. 기존 범위 추정은 **추정이라는 이름으로 따로** 남는다 — 하한과 섞지 않는다.
3. 읽은 게 없으면 칸 자체가 없다(0 을 자랑하지 않는다).
4. 호스트 안내문은 하한을 「최소」로 전하고, **시간을 아꼈다고 말하지 말라**고 한다(로컬은 더 느릴 수 있다).
"""

from __future__ import annotations

from alture_jarvis.delegation import STATUS_TOOL, host_context_kept_out, summarize_job


def _read(step: int, chars, *, ok: bool = True, effect: str = "read_web", tool: str = "browser_extract") -> dict:
    return {
        "step": step, "tool": tool, "ok": ok,
        "evidence": {"char_count": chars, "url": f"https://example.com/{step}"},
        "evidence_record": {"effect": effect, "source_id": f"https://example.com/{step}"},
    }


def test_the_floor_is_the_characters_read_divided_by_the_largest_measured_ratio() -> None:
    kept = host_context_kept_out([_read(1, 16_920), _read(2, 14_027), _read(3, 3_426)])

    assert kept is not None
    assert kept["kind"] == "floor"
    assert kept["text_chars"] == 34_373 and kept["reads"] == 3
    assert kept["tokens_at_least"] == int(34_373 / 4.5) == 7_638
    # 한글 본문(토큰당 ~1.7자)이면 실제 토큰은 이보다 훨씬 많다 — 하한이 실제를 넘으면 안 된다
    assert kept["tokens_at_least"] < 34_373 / 1.66


def test_a_failed_read_a_write_and_a_step_without_a_count_add_nothing() -> None:
    kept = host_context_kept_out([
        _read(1, 5_000),
        _read(2, 99_999, ok=False),                                   # 실패한 읽기
        _read(3, 88_888, effect="write_local", tool="local_write_file"),  # 쓰기는 읽은 게 아니다
        _read(4, None),                                               # 크기를 모르는 걸음
        _read(5, "abc"),
        _read(6, 0),
    ])

    assert kept is not None and kept["text_chars"] == 5_000 and kept["reads"] == 1


def test_a_count_that_arrives_as_text_is_still_counted() -> None:
    """저장을 거치면 숫자가 글자로 돌아오는 경우가 있다."""
    kept = host_context_kept_out([_read(1, "12000")])

    assert kept is not None and kept["text_chars"] == 12_000


def test_nothing_read_means_no_claim_at_all() -> None:
    assert host_context_kept_out([]) is None
    assert host_context_kept_out([_read(1, 100, ok=False)]) is None


def test_the_basis_says_it_is_a_floor_and_what_it_leaves_out() -> None:
    basis = host_context_kept_out([_read(1, 9_000)])["basis"]  # type: ignore[index]

    assert "하한" in basis and "4.5" in basis
    assert "세지 않았습니다" in basis  # 안 센 것을 말한다


# --- 호스트가 받는 요약 -------------------------------------------------------------

def _job() -> dict:
    return {"id": "j", "status": "completed", "result": {
        "answer": "정리했습니다.", "completion_state": "complete",
        "agent_trace": {"steps": [_read(1, 16_920), _read(2, 14_027)], "tool_numbers": [], "tool_numbers_body": [],
                        "verification": {"elapsed_sec": 90}},
    }}


def test_the_completed_summary_carries_only_the_floor() -> None:
    """★ 2026-09-23: 9/7 숫자로 곱한 범위 추정은 뺐다(폐기된 숫자가 로그인 화면 한 장에 「20만 토큰 절감」을 만들었다)."""
    cost = summarize_job(_job())["cost"]

    assert cost["host_context_kept_out"]["tokens_at_least"] == int((16_920 + 14_027) / 4.5)
    assert cost["pages_read_by_host"] == 0
    assert "host_input_tokens_avoided_estimate" not in cost
    assert cost["host_context_kept_out"]["kind"] == "floor"


def test_no_multiplier_is_ever_produced() -> None:
    """「N배」는 캐싱을 끄고 잰 값이라 반박당한다 — 어느 칸에도 배수가 없어야 한다."""
    import json

    text = json.dumps(summarize_job(_job())["cost"], ensure_ascii=False)

    assert "배" not in text, "어느 칸에도 「N배」 표현이 없어야 한다"
    assert "multiplier" not in text and "times" not in text


def test_a_job_that_read_nothing_gets_no_floor_field() -> None:
    job = {"id": "j", "status": "completed", "result": {
        "answer": "네.", "completion_state": "complete",
        "agent_trace": {"steps": [], "tool_numbers": [], "tool_numbers_body": []},
    }}

    assert "host_context_kept_out" not in summarize_job(job)["cost"]


# --- 호스트 안내문 -------------------------------------------------------------------

def test_the_host_is_told_to_say_at_least_and_not_to_claim_time_saved() -> None:
    description = STATUS_TOOL["description"]

    assert "tokens_at_least" in description and "하한" in description and "최소" in description
    assert "시간을 아꼈다는 말은 하지 마세요" in description  # 로컬은 더 느릴 수 있다 — 시간 절감은 근거가 없다
