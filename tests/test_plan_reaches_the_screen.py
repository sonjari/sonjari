"""시킨 것 대조가 **사람에게도 간다** (R3).

`plan.py` 는 처음부터 요구를 뽑고(`extract`) 채워졌는지 검사하고(`check`) 남은 것을
문장으로 만들었다(`remaining_note`). 그런데 그 셋은 전부 **모델에게만** 갔다 —
루프에 되먹이는 말이었다. 사람은 143초 동안 점만 보고 있었다.

여기서 못 박는 것:

  1. 대조표가 이벤트로 나간다 — 화면이 받을 수 있어야 체크리스트를 그린다
  2. **바뀐 것이 있을 때만** 나간다 — 걸음마다 같은 값을 쏘면 화면이 매번 다시 그린다
  3. 끝난 뒤에도 남는다(`verification.plan`) — 이벤트는 흘러가 버려서, 화면을 새로
     열면 끝난 판의 체크리스트를 볼 방법이 없었다
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent, named_sources
from alture_jarvis.plan import check, extract

PROMPT = "위시켓과 크몽에서 AI 챗봇 외주 공고를 최소 4개는 직접 열어 읽고 정리해줘"


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, name: str, payload: dict[str, Any]) -> None:
        self.events.append((name, payload))


class _Agent:
    """`_publish_plan` 만 빌려 쓴다 — 판 전체를 돌리지 않고 그 규칙만 본다."""

    _plan_payload = staticmethod(BrowserAgent._plan_payload)
    _publish_plan = BrowserAgent._publish_plan

    def __init__(self) -> None:
        self.events = _Recorder()


def _plan():
    return extract(PROMPT, has_named_source=bool(named_sources(PROMPT)))


def _read(urls: list[str]) -> list[dict[str, Any]]:
    return [{"tool": "browser_extract", "ok": True, "evidence": {"url": url}} for url in urls]


def test_the_checklist_leaves_the_backend() -> None:
    agent = _Agent()
    plan = _plan()
    assert plan, "이 요청에서는 대조 가능한 요구가 뽑혀야 한다"

    agent._publish_plan("job-1", check(plan, sources=[], steps=[]), "")

    assert len(agent.events.events) == 1
    name, payload = agent.events.events[0]
    assert name == "agent_plan"
    assert payload["job_id"] == "job-1"
    assert payload["total"] == len(plan)
    assert payload["met"] == 0
    # 사람이 읽을 말과, 지금까지 어땠는지가 같이 나간다. 라벨만 보내면 화면은
    # "안 됨"이라고만 말할 수 있고 **얼마나 왔는지**는 못 말한다.
    first = payload["items"][0]
    # 2026-10-24: 확실성 등급과 그 요구가 선 자리도 같이 실린다(§55-41 · 측정이 읽는다).
    assert set(first) == {"kind", "label", "met", "saw", "grade", "origin"}
    assert first["label"]
    assert first["saw"]


def test_it_only_speaks_when_something_changed() -> None:
    agent = _Agent()
    plan = _plan()
    nothing = check(plan, sources=[], steps=[])

    signature = agent._publish_plan("job-1", nothing, "")
    same = agent._publish_plan("job-1", nothing, signature)

    assert same == signature
    assert len(agent.events.events) == 1, "안 바뀐 대조표를 다시 쏘았다"

    progressed = check(
        plan,
        sources=["https://www.kmong.com/gig/1", "https://www.wishket.com/project/2/"],
        steps=_read(["https://www.kmong.com/gig/1", "https://www.wishket.com/project/2/"]),
    )
    agent._publish_plan("job-1", progressed, same)

    assert len(agent.events.events) == 2
    _, payload = agent.events.events[1]
    # 사이트 둘은 채워졌고 개수(4개)는 아직 아니다 — 절반만 찬 상태가 그대로 보인다.
    assert payload["met"] == 2
    assert payload["total"] == 3
    labels = {item["label"]: item["met"] for item in payload["items"]}
    assert labels["크몽에서 하기"] is True
    assert labels["4개 이상 직접 열어 읽기"] is False


def test_nothing_is_published_when_nothing_could_be_extracted() -> None:
    """못 뽑은 요구를 "안 됐다"고 그리면 반쯤 아는 체하는 체크리스트가 된다.

    문체·구성 같은 요구는 애초에 안 뽑는다(`plan.py` 첫머리). 그런 요청에서
    빈 체크리스트가 뜨면 사람은 자비스가 아무것도 안 했다고 읽는다.
    """
    plan = extract("고마워", has_named_source=False)
    assert plan == []

    agent = _Agent()
    agent._publish_plan("job-1", check(plan, sources=[], steps=[]), "")
    # 부르는 쪽이 `if plan:` 으로 막지만, 빈 대조표가 새 나가도 total 0 이라
    # 화면이 그릴 것이 없다는 사실은 여기서도 확인해 둔다.
    _, payload = agent.events.events[0]
    assert payload["total"] == 0
    assert payload["items"] == []
