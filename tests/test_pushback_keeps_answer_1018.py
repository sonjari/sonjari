"""되받기에 말로만 짧게 답해도 앞 답이 사라지지 않는다 · 「깃허브에 관한 규칙」의 깃허브는 갈 곳이 아니다 (2026-10-18 c9910364)."""

from __future__ import annotations

from alture_jarvis import plan
from alture_jarvis.plan_nudges import _keep_answer_over_reply

RULES = "규칙 1 ... 규칙 6 원문 " * 20


def test_a_short_reply_with_no_new_steps_keeps_the_answer_before_the_pushback() -> None:
    reply = "깃허브에서 할 일은 없었습니다 — 위 답변에 그대로 실려 있습니다."
    merged = _keep_answer_over_reply(RULES, reply, new_steps=0)
    assert merged.startswith(RULES.strip()) and merged.endswith(reply)


def test_new_steps_or_a_full_rewrite_replace_the_old_answer() -> None:
    assert _keep_answer_over_reply(RULES, "새로 읽고 고친 짧은 답", new_steps=2) == "새로 읽고 고친 짧은 답"
    longer = RULES + " 보탠 말"
    assert _keep_answer_over_reply(RULES, longer, new_steps=0) == longer
    assert _keep_answer_over_reply("", "답", new_steps=0) == "답"
    assert _keep_answer_over_reply(RULES, "", new_steps=0) == RULES


def test_a_site_named_only_as_the_topic_is_not_a_place_to_go() -> None:
    topic = "레딧 r/LocalLLM 규칙을 옮겨 줘. 특히 링크 · 깃허브에 관한 규칙은 빠짐없이."
    labels = [r.label for r in plan.extract(topic, must_observe=True, observe_from=frozenset({"web"})) if r.kind == "site"]
    assert "깃허브에서 하기" not in labels
    place = "깃허브에서 트렌딩 파이썬 저장소 3개 찾아 줘"
    assert [r.label for r in plan.extract(place) if r.kind == "site"] == ["깃허브에서 하기"]


def test_a_quoted_phrase_is_content_not_a_computation() -> None:
    """한글 서식 측정(2026-10-18): 따옴표 안 「몇 가지」와 밖의 「저장해」가 짝지어 헛 「직접 계산해 보기」가 섰다."""
    quoted = r"「C:\x\a.hwp」 한글 파일을 열어서 「간편한 작업을 위한 몇 가지 팁」 줄을 16pt · 기울임 · 빨간색으로 바꾸고 저장해 줘."
    assert not plan.wants_a_computation(quoted)
    assert plan.wants_a_computation("이 숫자들의 평균을 계산해 줘")


def test_a_sum_is_a_computation_but_words_with_hap_are_not() -> None:
    """「1부터 100까지 합을 계산해 줘」가 셈으로 안 잡혔다(2026-10-18). 「합」 한 글자는 합격 · 합의에 걸려 꼴로만 받는다."""
    for asked in ("1부터 100까지 합을 계산해 줘", "이 열의 합을 구해 줘", "매출 총합을 계산해 줘"):
        assert plan.wants_a_computation(asked), asked
    for asked in ("합격 발표 언제야", "두 회사 합의 내용 정리해 줘"):
        assert not plan.wants_a_computation(asked), asked
