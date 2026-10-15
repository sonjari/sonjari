"""산출물을 만들라고 해도 **출처를 댔으면 읽기 수량은 살아 있다** (2026-09-21).

## 두 문장이 갈려야 한다

    AURORA … index.html 로 만들어줘 … 3개 관측 목적지 카드    ← 카드는 **우리가 만드는 것**
    YES24에서 파이썬 책 3권을 조사해서 마크다운 문서로 만들어줘  ← 책은 **밖에 있는 것**

둘 다 「만들어줘」로 끝나고 둘 다 숫자가 있다. 그런데 앞엣것의 3 은 산출물의 모양이고,
뒤엣것의 3 은 **읽어야 할 개수**다.

## 무슨 일이 있었나

AURORA 판이 「3개 카드」를 「자료 3개를 직접 열어 읽기」로 바꿔 계획을 오염시켰다.
그걸 막으려고 **산출물 요청이면 수량을 버리게** 했는데, 그 규칙이 YES24 같은
**출처를 댄 조사**까지 같이 버렸다(기존 시험 다섯 개가 깨졌다).

## 가르는 선

**출처를 댔는가.** 「YES24에서」·「사람인에서」처럼 밖의 이름을 대면 그 숫자는
밖에 있는 것을 세는 것이다. AURORA 에는 댈 출처가 없다 — 우리가 만든다.

낱말(권·개·건)로 가르려 하면 또 구멍이 난다. 이 저장소가 여러 번 겪은 자리다.
"""

from __future__ import annotations

from alture_jarvis.plan import extract as extract_plan

AURORA = (
    "AURORA라는 한밤의 오로라 항해 관측소를 index.html 단일 파일로 만들어줘. "
    "서로 다른 3개 관측 목적지 카드와 각 목적지의 관측 확률을 보여줘. "
    "완성 뒤 local_preview_page로 열고 확인해."
)
YES24 = "YES24에서 파이썬 책 3권의 쪽수와 ISBN 을 조사해서 마크다운 문서로 만들어줘."


def _kinds(prompt: str, **kwargs) -> list[str]:
    return [req.kind for req in extract_plan(prompt, **kwargs)]


def test_a_named_source_keeps_the_read_count() -> None:
    """★ 코덱스 패치가 여기까지 버렸다 — 기존 시험 다섯 개가 깨진 자리."""
    assert "count" in _kinds(YES24, has_named_source=True), (
        "출처를 대고 조사하라고 했는데 읽기 수량이 사라졌다"
    )


def test_the_ui_quantity_is_still_not_a_read_count() -> None:
    """코덱스가 고친 것을 도로 깨뜨리면 안 된다 — 카드는 우리가 만드는 것이다."""
    assert "count" not in _kinds(AURORA), "「3개 카드」가 다시 읽기 요구가 됐다"


def test_the_count_is_the_number_that_was_said() -> None:
    plan = extract_plan(YES24, has_named_source=True)
    counts = [req for req in plan if req.kind == "count"]
    assert counts and int(counts[0].target) == 3


def test_a_plain_research_request_is_unchanged() -> None:
    """출처도 대고 산출물도 안 시킨 평범한 조사 — 예전 그대로."""
    assert "count" in _kinds("사람인에서 여수 회계 공고 3건 찾아 줘", has_named_source=True)
