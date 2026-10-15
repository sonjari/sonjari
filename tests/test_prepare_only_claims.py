"""준비만 해놓고 "완료했습니다"라고 답하는 것을 막는다.

2026-08-05 실측(job 3692f293): 블로그에 글을 넣어 달라고 했더니 도구를 딱 하나
`naver_blog_prepare_post` 만 부르고, "블로그 포스팅 준비를 완벽하게 마쳤습니다.
이제 아래 순서대로 진행하면 됩니다" 라며 **자기가 부를 도구 이름 셋을 목록으로**
답했다. 편집기에는 아무것도 안 들어갔다.

기존 장치가 둘 다 비켜 갔다:
- 예고 되받기: 조건이 `not steps` 였다. prepare 가 한 줄 남겨서 꺼졌다.
- 사실 검증(_commit_reality_check): "실패한 commit 도구"를 찾는데, 부르지도 않았으니
  실패한 것이 없어 할 말이 없었다.

prepare 는 action_id 만 만들고 바깥 세상은 하나도 바꾸지 않는다 — 그래서 "한 일"로
쳐 주면 안 된다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent, PROMISED_ACTION, _nothing_done_yet


def _step(tool: str, ok: bool = True, error: str = "") -> dict[str, object]:
    return {"step": 1, "tool": tool, "arguments": {}, "ok": ok, "status": "", "error": error, "evidence": {}}


def test_filling_the_editor_does_not_stand_in_for_saving() -> None:
    """준비마다 자기 소비자가 있다. "글은 채웠다"가 "저장했다"를 대신하지 못한다.

    2026-08-13 실측. 걸음이 prepare_post → fill_editor → prepare_save_draft 로 끝났는데
    답변 첫 문장은 **"임시저장까지 마쳤습니다"** 였다. 같은 답 안의 계획 대조표에는
    "❌ 임시저장 — 실행 안 됨"이라고 정확히 적혀 있었다 — 한 답변이 스스로 모순됐고,
    사람이 먼저 읽는 쪽이 거짓말이었다.

    원인: 준비한 것 **전체**의 소비자를 한 무더기로 모아 놓고 "그중 하나라도 불렸으면
    됐다"고 봤다. `fill_editor` 가 prepare_post 의 소비자라서, 그것 하나로 저장 준비까지
    이어진 것으로 세어졌다.
    """
    steps = [
        _step("naver_blog_prepare_post"),
        _step("naver_blog_fill_editor"),
        _step("naver_blog_prepare_save_draft"),
    ]
    note = BrowserAgent._commit_reality_check("임시저장까지 마쳤습니다.", steps)
    assert "naver_blog_save_draft" in note
    assert "아직 실제로 실행되지 않았습니다" in note


def test_actually_saving_draws_no_warning() -> None:
    steps = [
        _step("naver_blog_prepare_post"),
        _step("naver_blog_fill_editor"),
        _step("naver_blog_prepare_save_draft"),
        _step("naver_blog_save_draft"),
    ]
    assert BrowserAgent._commit_reality_check("임시저장 완료했습니다.", steps) == ""


def test_a_prepare_alone_is_not_something_done() -> None:
    assert _nothing_done_yet([_step("naver_blog_prepare_post")]) is True


def test_a_real_tool_counts_as_done() -> None:
    assert _nothing_done_yet([_step("browser_snapshot")]) is False


def test_a_failed_tool_is_not_done_either() -> None:
    assert _nothing_done_yet([_step("naver_blog_fill_editor", ok=False, error="boom")]) is True


def test_the_promise_that_slipped_through_is_still_a_promise() -> None:
    """실제로 나왔던 문장. 되받기 조건이 이 문장을 잡아야 한다."""
    answer = "이제 아래 순서대로 진행하면 됩니다. 지금 바로 편집기에 글을 채워 넣을까요? 바로 실행하겠습니다!"
    assert PROMISED_ACTION.search(answer)
    assert _nothing_done_yet([_step("naver_blog_prepare_post")])


def test_claiming_done_after_only_preparing_is_corrected() -> None:
    answer = "블로그 포스팅 준비를 완벽하게 마쳤습니다. 임시저장 준비 완료 단계입니다."

    correction = BrowserAgent._commit_reality_check(answer, [_step("naver_blog_prepare_post")])

    assert "아직 실제로 실행되지 않았습니다" in correction
    assert "naver_blog_fill_editor" in correction


def test_no_correction_once_the_next_step_actually_ran() -> None:
    answer = "본문까지 모두 작성 완료했습니다."

    correction = BrowserAgent._commit_reality_check(
        answer, [_step("naver_blog_prepare_post"), _step("naver_blog_fill_editor")]
    )

    assert correction == ""


def test_a_failed_commit_still_wins_the_older_correction() -> None:
    """이미 있던 검사가 죽지 않았는지. 실패한 commit 이 있으면 그쪽을 말해야 한다."""
    answer = "메일을 보냈습니다."
    steps = [
        _step("google_gmail_prepare_send"),
        _step("google_gmail_send", ok=False, error="quota_exceeded"),
    ]

    correction = BrowserAgent._commit_reality_check(answer, steps)

    assert "성공하지 않았습니다" in correction and "quota_exceeded" in correction


def test_an_answer_that_claims_nothing_is_left_alone() -> None:
    answer = "초안을 세 가지 방향으로 정리해 봤습니다. 어느 쪽으로 갈까요?"

    assert BrowserAgent._commit_reality_check(answer, [_step("naver_blog_prepare_post")]) == ""
