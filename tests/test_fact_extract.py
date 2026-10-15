"""대화에서 사실 뽑기 — **지어낸 것을 막는 자리** (2026-08-24, P2).

## 이 파일이 지키는 것 하나

모델이 「이 사실은 대화에서 나왔다」고 말하는 것은 **주장**이다. 이 저장소는 그
주장을 두 번 믿었고 두 번 다 정적 템플릿이었다(사고 I, 그리고 과학 4과목 재발).
그때 배운 것: **provenance 는 검증 대상이다.**

그래서 모델이 준 인용을 실제 대화와 대조한다. 없으면 안 넣는다.
"""

from __future__ import annotations

import pytest

from alture_jarvis import fact_extract as fx

KINDS = ("person", "product", "preference", "ongoing", "reference")


# ── 태우기 전에 거른다 ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    ["고마워", "어어", "응", "ㅋㅋㅋ", "알겠어", "오케이", "잘했어 고마워"],
)
def test_small_talk_never_reaches_the_model(text: str) -> None:
    """매 턴 모델을 태우면 대화가 그만큼 느려진다. 뽑을 게 없는 말은 안 태운다."""
    assert not fx.worth_extracting(text)


@pytest.mark.parametrize(
    "text",
    [
        "우리 사무실 여수로 옮겼거든",
        "내가 쓰는 그래픽카드는 3090이야",
        "나는 추측보다 실측을 원해",
        "우리 회사 제품은 학원용 AI 플랫폼이야",
    ],
)
def test_things_worth_remembering_do_reach_the_model(text: str) -> None:
    assert fx.worth_extracting(text)


# ── 못 읽어도 안 터진다 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["", "   ", "죄송합니다 못 하겠습니다", "{망가진 json", "[]"])
def test_unreadable_output_gives_an_empty_list_not_a_crash(raw: str) -> None:
    """추출이 실패했다고 대화가 안 되면 그게 더 나쁘다."""
    assert fx.parse(raw) == []


def test_it_finds_json_even_with_chatter_around_it() -> None:
    """모델이 앞뒤로 말을 붙이는 일이 흔하다."""
    raw = '알겠습니다.\n{"facts": [{"kind":"person","subject":"사용자님","fact":"이름은 박가람","quote":"내 이름은 박가람야"}]}\n이상입니다.'
    rows = fx.parse(raw)
    assert len(rows) == 1
    assert rows[0]["fact"] == "이름은 박가람"


# ── ★ 지어낸 것은 안 들어간다 ─────────────────────────────────────────────────

def test_a_fact_whose_quote_is_not_in_the_conversation_is_dropped() -> None:
    """★ 이 검사가 사고 I 의 재발 방지다.

    모델이 그럴듯한 사실을 만들어 내고 인용까지 지어내는 일이 실제로 있다.
    인용을 대화와 대조하면 거기서 걸린다.
    """
    rows = [{
        "kind": "person", "subject": "사용자님",
        "fact": "서울에 산다",
        "quote": "나는 서울에 살아",          # ← 대화에 없는 말
    }]
    keep, dropped = fx.usable(rows, ("우리 사무실 여수로 옮겼어",), KINDS)
    assert keep == []
    assert dropped and "근거가 없다" in dropped[0][1]


def test_a_real_quote_survives_small_wording_changes() -> None:
    """모델이 인용을 옮기며 띄어쓰기를 바꾸는 일이 흔하다.

    그걸 「지어냈다」로 판정하면 멀쩡한 사실이 전부 버려진다 — 게이트는
    양방향으로 역검증해야 한다는 것을 이 저장소는 하루에 두 번 배웠다.
    """
    rows = [{
        "kind": "product", "subject": "사무실 위치", "fact": "여수",
        "quote": "우리 사무실여수로 옮겼어",     # 띄어쓰기가 다르다
    }]
    keep, _dropped = fx.usable(rows, ("우리 사무실 여수로 옮겼어.",), KINDS)
    assert len(keep) == 1


def test_a_quote_too_short_to_mean_anything_is_refused() -> None:
    """낱말 하나짜리 인용은 아무 데나 걸린다 — 대조가 뜻을 잃는다."""
    rows = [{"kind": "person", "subject": "a", "fact": "b", "quote": "나"}]
    keep, dropped = fx.usable(rows, ("나는 오늘 밥을 먹었다",), KINDS)
    assert keep == []
    assert dropped


def test_an_unknown_kind_is_dropped_with_a_reason() -> None:
    rows = [{"kind": "잡동사니", "subject": "a", "fact": "b", "quote": "우리 사무실 여수로 옮겼어"}]
    keep, dropped = fx.usable(rows, ("우리 사무실 여수로 옮겼어",), KINDS)
    assert keep == []
    assert "모르는 갈래" in dropped[0][1]


def test_dropped_rows_always_say_why() -> None:
    """★ 이유를 안 남기면 「추출이 안 된다」와 「뽑을 게 없었다」를 못 가린다.

    빈 값이 두 가지를 뜻하면 조용히 고장 난다 — 이 저장소가 여러 번 겪은 모양이다.
    """
    rows = [
        {"kind": "없는갈래", "subject": "a", "fact": "b", "quote": "우리 사무실 여수로 옮겼어"},
        {"kind": "person", "subject": "", "fact": "b", "quote": "우리 사무실 여수로 옮겼어"},
        {"kind": "person", "subject": "a", "fact": "b", "quote": "지어낸 인용입니다"},
    ]
    keep, dropped = fx.usable(rows, ("우리 사무실 여수로 옮겼어",), KINDS)
    assert keep == []
    assert len(dropped) == 3
    assert all(why for _row, why in dropped)


# ── 프롬프트가 지켜야 할 것 ───────────────────────────────────────────────────

def test_the_prompt_asks_for_a_quote() -> None:
    """인용을 안 받으면 대조할 것이 없고, 그러면 위 검사들이 전부 무의미해진다."""
    prompt = fx.build_prompt("사용자 말", "자비스 답")
    assert "quote" in prompt
    assert "지어내지 마라" in prompt


def test_the_prompt_carries_both_sides_of_the_conversation() -> None:
    prompt = fx.build_prompt("우리 사무실 여수", "여수로 이전하셨군요")
    assert "우리 사무실 여수" in prompt
    assert "여수로 이전하셨군요" in prompt


def test_the_caller_must_pass_think_false() -> None:
    """★ 젬마는 thinking 모델이다. `think=False` 를 안 넣으면 num_predict 예산이
    내부 추론에 다 쓰이고 `content` 가 **빈 문자열**로 온다.

    이 저장소는 그 함정에 한 번 걸렸다(KG 오개념 재생성, 2026-07-14).
    """
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime._learn_facts)
    assert "think=False" in source



def test_a_person_fact_found_only_in_the_assistants_own_answer_is_not_learned() -> None:
    """2026-09-17: 온텔릭 답 속 「박가람 대표는 비전공자…」가 사실로 저장됐다 — 자기 말이 사실이 되는 고리."""
    user = "너가 나에 대해 아는 거 뭐야?"
    answer = "상시 프로필: 박가람 대표는 비전공자이며 AI 에이전트 설계 역량을 보유하고 있습니다."
    row = {"kind": "person", "subject": "박가람", "fact": "박가람 대표는 비전공자이며 AI 에이전트 설계 역량을 보유",
           "quote": "박가람 대표는 비전공자이며 AI 에이전트 설계 역량을 보유하고"}
    keep, dropped = fx.usable([row], (user, answer), KINDS, speaker_text=user)
    assert keep == [] and "자기 말뿐" in dropped[0][1]


def test_a_person_fact_the_user_said_is_still_learned() -> None:
    user = "나는 비전공자인데 에이전트를 만들고 있어"
    row = {"kind": "person", "subject": "사용자", "fact": "사용자는 비전공자이다", "quote": "나는 비전공자인데"}
    keep, _dropped = fx.usable([row], (user, "그렇군요"), KINDS, speaker_text=user)
    assert keep == [row]


def test_what_the_assistant_read_can_still_be_a_product_fact() -> None:
    """도구로 읽고 답에 적은 것(제품·참고)은 사람에 관한 말이 아니다 — 막지 않는다."""
    answer = "사람인 공고 마감일은 2026.09.25 입니다."
    row = {"kind": "product", "subject": "사람인 공고", "fact": "마감일은 2026.09.25", "quote": "마감일은 2026.09.25"}
    keep, _dropped = fx.usable([row], ("공고 마감일 알려줘", answer), KINDS, speaker_text="공고 마감일 알려줘")
    assert keep == [row]
