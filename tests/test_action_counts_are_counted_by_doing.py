"""「5개 시켰는데 2개」를 잡는다.

★ 2026-09-01 라이브. 「저 순위대로 5개 스크랩해줘」에 자비스는 2개만 스크랩하고
5개를 목록으로 적어 답했다. 그런데 개수 충족이 「읽은 쪽수 ≥ 5 **또는** 답에
적힌 항목 ≥ 5」였다 — 답이 5줄이었으니 **충족으로 통과했다.**

목록으로 답해서 되는 일(「3개 알려줘」)에는 그 규칙이 맞다. 행위에 붙은 개수는
**한 횟수로만** 세야 한다. 적어 놓는 것으로 대신할 수 없다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import actions_done, check, extract, remaining_note


def _kinds(prompt: str) -> list[str]:
    return [req.kind for req in extract(prompt, has_named_source=True)]


def test_writing_the_list_does_not_count_as_doing_it() -> None:
    wanted = extract("저 순위대로 5개 스크랩해줘", has_named_source=True)
    steps = [{"tool": "browser_submit_form", "ok": True}] * 2

    results = check(
        wanted,
        sources=[f"https://example.com/{n}" for n in range(6)],
        steps=steps,
        answer="1. 가\n2. 나\n3. 다\n4. 라\n5. 마",
    )

    met = {req.kind: ok for req, ok, _ in results}
    assert met["count_action"] is False, "답에 5줄 적은 것으로 통과했다"
    assert "2개 처리함" in dict((r.kind, saw) for r, _, saw in results)["count_action"]


def test_the_shortfall_is_pushed_back_into_the_loop_while_it_can_still_act() -> None:
    """끝나고 「못 했네」는 정직할 뿐 도움이 안 된다. 도는 중에 말해 줘야 한다."""
    wanted = extract("저 순위대로 5개 스크랩해줘", has_named_source=True)
    results = check(wanted, sources=[], steps=[{"tool": "browser_submit_form", "ok": True}], answer="")

    note = remaining_note(results)

    assert "5개 실제로 처리하기" in note
    assert "1개 처리함" in note


def test_a_count_next_to_a_reading_verb_is_still_a_reading_count() -> None:
    """★ 이 갈래가 없으면 **맞는 판을 틀렸다고 말한다.**

    "공고를 4개 읽고 메일 보내줘" 의 4개는 읽기다. 뒤의 「보내」가 걸려 행위
    개수가 되면, 4개를 다 읽고도 「4개 중 1개만 처리했습니다」가 답에 붙는다.
    """
    assert "count" in _kinds("위시켓과 크몽에서 공고를 4개 읽고 메일 보내줘")
    assert "count_action" not in _kinds("위시켓과 크몽에서 공고를 4개 읽고 메일 보내줘")


@pytest.mark.parametrize(
    "prompt",
    ["저 순위대로 5개 스크랩해줘", "마음에 드는 거 스크랩 5개 해줘", "드라이브에 파일 2개 올려줘"],
)
def test_an_action_count_is_recognised_either_side_of_the_number(prompt: str) -> None:
    """사람은 「5개 스크랩해줘」라고도 「스크랩 5개 해줘」라고도 말한다."""
    assert "count_action" in _kinds(prompt)


def test_only_finished_actions_are_counted() -> None:
    """「했는지 모른다」는 「했다」가 아니다 — 이 저장소가 그 둘로 여러 번 속았다."""
    steps = [
        {"tool": "browser_submit_form", "ok": True},
        {"tool": "browser_submit_form", "ok": True, "status": "executed_unverified"},
        {"tool": "browser_submit_form", "ok": True, "evidence": {"verified": False}},
        {"tool": "browser_click", "ok": True},  # 누른 것이 곧 처리된 것은 아니다
        {"tool": "browser_submit_form", "ok": False},
    ]

    assert actions_done(steps) == 1


def test_one_intent_does_not_become_two_requirements() -> None:
    """같은 뜻이 두 줄이면 「시킨 것 1/2」로 부풀어 된 판이 못한 것처럼 보인다."""
    labels = [req.label for req in extract("드라이브에 파일 2개 올려줘", has_named_source=True)]

    assert "드라이브에 올리기" in labels
    assert "발행" not in labels, "블로그 발행 요구로도 잡혔다"
