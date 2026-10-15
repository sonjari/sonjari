"""시킨 것을 다 채웠으면 더 안 간다 — 그리고 기다리는 사람에게 상황을 말한다.

자율을 늘린 대가로 한 번 답하는 데 11.7분이 걸렸다(2026-08-10 실측). 그 시간을
그냥 깎으면 자율을 늘려 얻은 깊이도 같이 깎인다 — 실제로 그 판에서 처음으로 크몽
공고 본문을 읽었다. 그래서 **더 가도 나아지지 않는 구간만** 잘라낸다.

그 구간이 어디였나. 계속 갈지 정하는 자리(`_autonomous_extension`)가 보는 것은
"되돌릴 수 있는가"와 "진전이 있는가" 둘뿐이었다. 그런데 진전은 **새 출처**로 재기
때문에, 시킨 것을 다 채운 뒤에도 아무 페이지나 하나 더 열면 진전으로 읽혀서 상한까지
간다. 답은 더 좋아지지 않는데 시간만 쓴다.

7단계(`plan.py`)가 "무엇을 시켰나"를 이미 세어 두고 있었다. 남은 것을 짚어 주는 말은
있었는데(`remaining_note`) **다 됐다고 말해 주는 말이 없었다.** 그 빈자리가 꼬리였다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.plan import all_met, check, extract, satisfied_note
from alture_jarvis.tool_gateway import ToolGateway


def _agent() -> BrowserAgent:
    root = Path(tempfile.mkdtemp())
    config = JarvisConfig(
        runtime_root=root, data_dir=root / "data", output_dir=root / "outputs"
    )
    store = JobStore(root / "jobs.db")
    return BrowserAgent(
        config, object(), ToolGateway(store, EventBus()), object(), object(), store, EventBus()
    )


def _read(url: str) -> dict[str, Any]:
    return {
        "step": 1, "tool": "browser_extract", "arguments": {}, "ok": True,
        "status": "", "error": "", "evidence": {"url": url},
    }


_TWO_SITES = "위시켓과 크몽에서 공고를 2개 이상 직접 열어 읽고 정리해줘"


def _results(prompt: str, urls: list[str]) -> list[Any]:
    steps = [_read(u) for u in urls]
    return check(extract(prompt), sources=[u for u in urls], steps=steps)


# ── 다 채웠는지 판단 ─────────────────────────────────────────────────────────
def test_meeting_every_requirement_counts_as_met() -> None:
    results = _results(
        _TWO_SITES, ["https://www.wishket.com/project/1/", "https://kmong.com/gig/2"]
    )
    assert all_met(results)


def test_a_missing_site_is_not_met() -> None:
    """개수만 세면 '아무거나 두 개'로 통과한다 — 사이트 요구가 그래서 있다."""
    results = _results(
        _TWO_SITES, ["https://www.wishket.com/project/1/", "https://www.wishket.com/p/2"]
    )
    assert not all_met(results)


def test_no_requirements_is_not_the_same_as_finished() -> None:
    """아무것도 못 뽑았다는 것은 '다 했다'가 아니라 '모른다'다.

    이걸 다 됐다고 읽으면, 문체·구성처럼 애초에 안 뽑는 요구가 걸린 요청이
    첫 걸음에 끝나 버린다.
    """
    assert not all_met([])
    assert not all_met(_results("자비스 뭐하고 있어?", []))


# ── 다 채웠으면 연장하지 않는다 ──────────────────────────────────────────────
def test_it_does_not_extend_once_everything_is_done() -> None:
    agent = _agent()
    steps = [_read("https://www.wishket.com/project/1/"), _read("https://kmong.com/gig/2")]
    results = _results(
        _TWO_SITES, ["https://www.wishket.com/project/1/", "https://kmong.com/gig/2"]
    )

    extra, why = agent._autonomous_extension(
        steps=steps, elapsed=120.0, plan_results=results
    )

    assert extra == 0.0
    assert why == "goal_met"


def test_it_keeps_going_while_something_is_missing() -> None:
    agent = _agent()
    urls = ["https://www.wishket.com/project/1/", "https://www.wishket.com/p/2"]
    steps = [_read(u) for u in urls]

    extra, why = agent._autonomous_extension(
        steps=steps, elapsed=120.0, plan_results=_results(_TWO_SITES, urls)
    )

    assert extra > 0, "크몽을 아직 못 읽었는데 멈추면 시킨 일을 안 한 것이다"
    assert why == "reversible_and_progressing"


def test_a_prompt_with_no_requirements_behaves_as_before() -> None:
    """요구를 못 뽑는 요청이 대부분이다. 그쪽 동작이 바뀌면 안 된다."""
    agent = _agent()
    steps = [_read("https://example.com/a")]
    extra, why = agent._autonomous_extension(steps=steps, elapsed=120.0, plan_results=[])
    assert extra > 0 and why == "reversible_and_progressing"


def test_the_model_is_told_it_is_done() -> None:
    """연장을 안 하는 것만으로는 부족하다 — 모델에게도 그만 찾으라고 말해야 한다."""
    results = _results(
        _TWO_SITES, ["https://www.wishket.com/project/1/", "https://kmong.com/gig/2"]
    )
    note = satisfied_note(results)
    assert "다 채웠다" in note
    assert "더 찾지 말고" in note


def test_nothing_is_said_while_work_remains() -> None:
    results = _results(_TWO_SITES, ["https://www.wishket.com/project/1/"])
    assert satisfied_note(results) == ""


# ── 기다리는 사람에게 상황을 말한다 ──────────────────────────────────────────
#
# 예전 문구는 "되돌릴 수 있는 작업이라 계속 진행합니다" 하나였다. 왜 계속하는지는
# 알려 주지만, 무엇을 가졌고 얼마나 남았는지는 알려 주지 않는다. 11분을 기다리는
# 사람에게 필요한 건 뒤쪽이다 — 기다릴지 멈출지 정할 수 있어야 한다.


def test_the_interim_report_says_what_it_has_and_how_long_is_left() -> None:
    urls = ["https://www.wishket.com/project/1/", "https://kmong.com/gig/2"]
    report = BrowserAgent._interim_report(
        steps=[_read(u) for u in urls],
        plan_results=_results(_TWO_SITES, urls[:1]),
        remaining_sec=310.0,
    )
    assert "2곳에서 읽음" in report
    assert "wishket.com" in report and "kmong.com" in report
    assert "5분 남음" in report
    assert "남은 것" in report, "아직 못 채운 게 있으면 그것도 말해야 한다"


def test_the_interim_report_is_honest_when_nothing_was_read() -> None:
    report = BrowserAgent._interim_report(
        steps=[], plan_results=[], remaining_sec=60.0
    )
    assert "아직 읽은 본문 없음" in report
    assert "남은 것" not in report


def test_the_interim_report_costs_no_model_call() -> None:
    """중간 요약을 새로 생성하면 그게 20~30초다 — 긴 걸 길게 만들어 푸는 꼴이 된다.

    `_interim_report` 가 classmethod 이고 인자만으로 문자열을 만든다는 사실이
    그 보장이다(모델 클라이언트에 손이 닿지 않는다).
    """
    report = BrowserAgent._interim_report(
        steps=[_read("https://kmong.com/gig/2")], plan_results=[], remaining_sec=5.0
    )
    assert "1분 미만 남음" in report
