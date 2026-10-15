"""재는 꾸러미가 **창이 꽉 차 말이 잘린 호출**을 세어 결과 파일에 싣는다 (2026-10-15).

레딧에서 받은 물음: 「표 없이 끝난 판은 마지막 요청의 프롬프트 + 생각이 창을 채워 잘린 것(`done_reason: length`) 아니냐」.
이 PC 기록에서는 10-11 의 맞춤(`window_fitted_budget`) 뒤 0건이었다. 그런데 남의 PC 에서 돌린 결과 파일에는 그 칸이 없어
같은 물음에 답할 수 없었다. 숫자 하나라 결과 파일에 실어도 된다.
"""
from __future__ import annotations

from alture_jarvis import measure_kit as kit


def _kit_answering(result: dict) -> kit.Sonjari:
    sonjari = kit.Sonjari("http://127.0.0.1:1", "가짜")
    sonjari.chrome = lambda *_a, **_k: (_ for _ in ()).throw(OSError("no chrome"))

    def call(path: str, body: dict | None = None, *, timeout: float = 60) -> object:
        if path == "/v1/chat":
            return {"job_id": "j1"}
        if path == "/v1/jobs/j1":
            return {"status": "completed", "result": result}
        raise AssertionError(path)

    sonjari.call = call  # type: ignore[method-assign]
    return sonjari


def test_calls_cut_by_the_window_are_counted_and_kept() -> None:
    cuts = [{"why": "length_limit", "step": 17, "tokens": 1585, "had_tool_call": False},
            {"why": "loop", "step": 3, "kept_chars": 10}]
    run = _kit_answering({"agent_trace": {"steps": [], "verification": {"content_cuts": cuts}}}).run("가상 과제", "s", sleep=lambda _s: None)

    assert run["length_cuts"] == 1
    assert kit.numbers_only(run, with_steps=False)["length_cuts"] == 1


def test_a_job_without_cuts_says_zero() -> None:
    run = _kit_answering({"agent_trace": {"steps": [], "verification": {}}}).run("가상 과제", "s", sleep=lambda _s: None)

    assert run["length_cuts"] == 0
