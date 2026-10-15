"""셈을 시키면 **「직접 계산해 보기」가 요구로 잡히는가.**

## 왜 이게 필요했나

라우터에 계산 갈래를 열었더니(`_requires_sandbox`) 도구를 **쥐어주기만** 하고
부르라고는 안 했다. 그래서 모델이 상자를 손에 든 채 암산했다.

2026-08-23 실측 — 낱말표를 넓힌 **뒤**의 퀀3.8:

    P2 수강료   266,475원  ✅ 맞음   그런데 audit_log 에 sandbox_run 0건
    P3 내신     2.62      ✅ 맞음   같음
    P4 일률     4         ✅ 맞음   같음

셋 다 맞았는데 **아무것도 계산하지 않았다.** 자비스 자신이 답에 경고를 달았다 —
"이 숫자는 이번에 열어 본 자료 어디에도 안 나옵니다". 맞았지만 근거가 없었다.

## 어떻게 고쳤나 — 새 장치를 만들지 않는다

`plan.extract` 가 `Requirement("action", "직접 계산해 보기", "sandbox_run")` 을
내놓는다. 그러면 **기존 기계가 그대로 일한다**:

    check          `sandbox_run` 이 실제로 실행됐는지 본다(done_tools)
    remaining_note "아직 계산을 안 했다"를 루프에 흘려 넣는다
    all_met        거짓이라 답하고 끝내지 않는다
    summary_note   끝내 안 하면 대조표에 ❌ 로 남는다

강제 호출(`_forced_commit_call`)을 못 쓰는 이유는 분명하다 — 그 패턴이 안전한 것은
**인자가 `action_id` 하나뿐이라 지어낼 것이 없기** 때문인데, `sandbox_run` 은
코드를 써야 한다. 그건 모델의 몫이다. 그래서 「부르라고 시키는」 대신
**「부를 때까지 끝내지 않는다」**로 만들었다.
"""

from __future__ import annotations

from alture_jarvis.plan import (
    Requirement,
    all_met,
    check,
    extract,
    remaining_note,
    summary_note,
    wants_a_computation,
)

COMPUTE = (
    "수강료가 30만원이었다. 3월에 10% 올렸고, 9월에 15% 할인 행사를 했고, "
    "거기에 형제 할인 5%를 추가로 적용했다. 할인은 순차 적용된다. "
    "최종 수강료는 얼마인가? 숫자만 답해라."
)


def test_a_computation_request_becomes_a_requirement() -> None:
    reqs = extract(COMPUTE)
    targets = [r.target for r in reqs if r.kind == "action"]
    assert "sandbox_run" in targets, f"셈을 시켰는데 요구가 안 잡힌다: {reqs}"


def test_the_requirement_is_unmet_until_the_box_actually_runs() -> None:
    reqs = [Requirement("action", "직접 계산해 보기", "sandbox_run")]

    # 아무것도 안 돌린 상태 — 미달이어야 하고, 남은 것을 말해 줘야 한다.
    before = check(reqs, sources=[], steps=[])
    assert not all_met(before)
    assert "직접 계산해 보기" in remaining_note(before)
    assert "❌" in summary_note(before)

    # 상자가 실제로 돌았다 — 그때야 충족이다.
    after = check(reqs, sources=[], steps=[{"tool": "sandbox_run", "ok": True}])
    assert all_met(after)


def test_answering_without_running_the_box_does_not_satisfy_it() -> None:
    """★ 오늘의 고장 그대로: 답은 맞았지만 도구를 안 썼다."""
    reqs = [Requirement("action", "직접 계산해 보기", "sandbox_run")]
    # 브라우저를 아무리 써도 셈을 한 것은 아니다.
    results = check(
        reqs,
        sources=["https://example.com"],
        steps=[{"tool": "browser_extract", "ok": True}, {"tool": "browser_open", "ok": True}],
    )
    assert not all_met(results)


def test_a_failed_box_run_does_not_count() -> None:
    """실패한 실행은 「했다」가 아니다 — `check` 의 done_tools 규칙을 지킨다."""
    reqs = [Requirement("action", "직접 계산해 보기", "sandbox_run")]
    results = check(reqs, sources=[], steps=[{"tool": "sandbox_run", "ok": False}])
    assert not all_met(results)


def test_non_computational_requests_get_no_such_requirement() -> None:
    """웹 조사·자사 DB·일상 대화에는 이 요구가 붙으면 안 된다.

    붙으면 그 판은 상자를 돌릴 때까지 안 끝난다 — 오탐의 값이 크다.
    """
    for prompt in (
        "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘",
        "중앙대 소프트웨어학부 최근 경쟁률이 어떻게 되나요?",
        "오늘 기분이 어때",
        "나래이한테 메일 보내줘",
        "소수가 뭐야",  # 설명 요청 — 동사가 없다
    ):
        assert not wants_a_computation(prompt), f"오탐: {prompt}"
        assert "sandbox_run" not in [r.target for r in extract(prompt)]


def test_the_router_and_the_plan_agree() -> None:
    """★ 판정이 **한 벌**인지. 두 벌이 되면 갈리고, 갈린 쪽이 조용히 틀린다."""
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime._requires_sandbox)
    assert "plan_wants_the_sandbox" in source, (
        "라우터가 자기 낱말표를 다시 갖고 있다 — plan.wants_the_sandbox 를 써야 한다"
    )


def test_a_table_request_is_not_a_computation() -> None:
    """★ "표로 정리해줘"는 셈이 아니다 — 웹 조사 결과를 표 모양으로 쓰라는 말이다.

    한 표에 섞어 뒀더니 기존 검사(`test_plan.py` 의 위시켓 문장)가 그 자리에서
    걸렸다. 그 판까지 상자를 돌려야 끝나게 만들면 조사가 영영 안 끝난다.
    """
    from alture_jarvis.plan import wants_the_sandbox

    table = "위시켓과 크몽에서 AI 챗봇 외주 공고를 찾아서 최소 4개는 직접 열어 읽고 표로 정리해줘"
    assert not wants_a_computation(table), "표 정리를 셈으로 보면 안 된다"
    assert "sandbox_run" not in [r.target for r in extract(table)]
    # 다만 라우터는 예전처럼 상자를 쥐어줘도 된다(목적지가 같은 에이전트다).
    assert wants_the_sandbox(table)


def test_an_artifact_request_still_reaches_the_router() -> None:
    from alture_jarvis.plan import wants_the_sandbox

    for prompt in ("엑셀 파일로 만들어줘", "csv 로 정리해줘", "이 데이터로 차트 그려서 저장해줘"):
        assert wants_the_sandbox(prompt), prompt
