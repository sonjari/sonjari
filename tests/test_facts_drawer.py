"""사실 서랍 — 세션을 나가도 사용자님을 아는 장치 (2026-08-24, P1·P3).

## 왜 생겼나

회상은 **대화 조각**을 돌려준다. 조각 넷을 붙여도 "내 이름은 박가람"라는
문장이 어디에도 없으면 모델은 답을 못 한다. 실측:

    '박가람' 가 들어간 메시지  : 18건        ← 사실은 대화 안에 있다
    「내 이름이 뭐야」의 검색어 : ['이름이','뭐야']
    → 겹치는 낱말이 하나도 없다. 있는데 못 찾는다.

기억 눈금(`scripts/bench_memory_recall.py`) 기준선 20문항 중 10개(50%).
남은 실패는 전부 같은 모양이다 — **정답 낱말이 질문에 없다.**

그래서 대화를 회상하는 대신 **사실을 적는다.**
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.memory import ConversationMemory


@pytest.fixture()
def memory(tmp_path: Path) -> ConversationMemory:
    return ConversationMemory(tmp_path / "m.db")


def _seed(memory: ConversationMemory) -> int:
    return memory.add_message("s1", "user", "내 이름은 박가람다")


# ── 출처 없는 사실은 안 받는다 ────────────────────────────────────────────────

def test_a_fact_without_a_source_is_refused(memory: ConversationMemory) -> None:
    """★ 이 저장소는 「AI가 생성했다」 라벨이 실은 정적 템플릿이었던 것을 **두 번**
    겪었다(사고 I, 그리고 과학 4과목 재발). 그때 배운 것은 provenance 가 주장이
    아니라 **검증 대상**이라는 것이고, 검증하려면 되짚을 자리가 있어야 한다.
    """
    with pytest.raises(ValueError, match="출처 없는 사실"):
        memory.add_fact(kind="person", subject="사용자님", fact="이름은 박가람", source_message_id=0)


def test_a_hand_written_fact_may_skip_the_source(memory: ConversationMemory) -> None:
    """사람이 직접 넣은 것은 사람이 출처다."""
    assert memory.add_fact(
        kind="person", subject="사용자님", fact="이름은 박가람",
        source_message_id=0, origin="manual",
    )


def test_the_kind_list_is_closed(memory: ConversationMemory) -> None:
    """아무 갈래나 받으면 서랍이 잡동사니가 되고, 「항상 붙이는 층」이 무엇을
    골라야 할지 판단할 수 없게 된다."""
    with pytest.raises(ValueError, match="모르는 갈래"):
        memory.add_fact(kind="아무거나", subject="a", fact="b", source_message_id=_seed(memory))


def test_a_long_fact_is_refused_not_trimmed(memory: ConversationMemory) -> None:
    """★ 조용히 자르면 **틀린 사실**이 된다.

    "사용자님은 여수로 사무실을 옮겼고 그 전에는" 에서 끊기면 뜻이 바뀐다.
    긴 것은 사실이 아니라 요약이고, 요약은 이미 다른 자리가 맡고 있다.
    """
    with pytest.raises(ValueError, match="너무 깁니다"):
        memory.add_fact(
            kind="person", subject="사용자님", fact="가" * 300,
            source_message_id=_seed(memory),
        )


def test_the_same_fact_is_stored_once(memory: ConversationMemory) -> None:
    """대화가 같은 말을 여러 번 해도 서랍은 한 줄이어야 한다."""
    mid = _seed(memory)
    first = memory.add_fact(kind="person", subject="사용자님", fact="이름은 박가람", source_message_id=mid)
    again = memory.add_fact(kind="person", subject="사용자님", fact="이름은 박가람", source_message_id=mid)
    assert first == again
    assert len(memory.live_facts()) == 1


# ── 틀린 것은 지우지 않고 덮는다 ──────────────────────────────────────────────

def test_a_wrong_fact_is_covered_not_deleted(memory: ConversationMemory) -> None:
    """지우면 왜 바뀌었는지가 사라지고, 같은 오해가 다시 들어온다."""
    mid = _seed(memory)
    old = memory.add_fact(kind="product", subject="사무실", fact="부산에 있다", source_message_id=mid)
    new = memory.add_fact(kind="product", subject="사무실", fact="여수에 있다", source_message_id=mid)
    memory.supersede_fact(old, new)

    live = [row["fact"] for row in memory.live_facts()]
    assert "여수에 있다" in live
    assert "부산에 있다" not in live, "덮인 사실이 아직 살아 있다"


def test_covering_without_a_replacement_still_marks_it(memory: ConversationMemory) -> None:
    """빈 값이 「안 덮였다」와 「그냥 틀렸다」 둘 다를 뜻하면 조용히 고장 난다."""
    mid = _seed(memory)
    one = memory.add_fact(kind="person", subject="x", fact="y", source_message_id=mid)
    memory.supersede_fact(one)
    assert memory.live_facts() == []


# ── 항상 붙는 층 ──────────────────────────────────────────────────────────────

def _fill(memory: ConversationMemory, count: int) -> None:
    mid = _seed(memory)
    for at in range(count):
        memory.add_fact(
            kind="person", subject=f"사람{at}", fact="가" * 60, source_message_id=mid
        )


def test_the_always_on_block_respects_one_single_cap(memory: ConversationMemory) -> None:
    """★ 상한은 **한 자리**에만 있어야 한다.

    2026-08-24 하루에 상한이 세 군데 흩어져 낮은 쪽만 일한 것을 네 번 겪었다
    (dataclass 기본값 · 환경변수 로더 · 함수 안 하드 상수). 그래서 값은
    `LEARNED_MAX_CHARS` 하나이고, 이 검사가 그 자리를 지킨다.
    """
    _fill(memory, 60)
    block = memory.learned_block()
    assert block
    # 안내 문구를 뺀 본문이 상한 안이어야 한다.
    body = block[block.index("<jarvis-learned>"):]
    assert len(body) <= memory.LEARNED_MAX_CHARS + 300, len(body)


def test_it_says_when_it_could_not_fit_everything(memory: ConversationMemory) -> None:
    """★ 침묵으로 오는 잘림이 제일 나쁘다 — 사고 Q 에서 본문의 23%가 그렇게
    사라졌고 아무도 몰랐다."""
    _fill(memory, 60)
    assert "안 실었다" in memory.learned_block()


def test_an_empty_drawer_attaches_nothing(memory: ConversationMemory) -> None:
    """서랍이 비었는데 빈 블록을 붙이면 모델이 「배운 게 없다」를 사실로 읽는다."""
    assert memory.learned_block() == ""


def test_learned_facts_are_marked_as_fallible(memory: ConversationMemory) -> None:
    """프로필(사람이 관리·권위)과 같은 무게로 믿으면, 잘못 배운 한 줄이 사람이
    적어 둔 사실을 이긴다."""
    memory.add_fact(
        kind="person", subject="사용자님", fact="이름은 박가람",
        source_message_id=_seed(memory),
    )
    block = memory.learned_block()
    assert "틀릴 수 있" in block
    assert "<jarvis-learned>" in block


def test_the_block_sits_after_the_profile_for_cache_reasons() -> None:
    """★ 앞에 두면 사실이 하나 늘 때마다 프로필까지 프리필 캐시가 무효가 된다.

    시각 줄을 맨 뒤로 옮겨 중앙값 0.630초 → 0.396초가 됐던 것과 같은 이유다.
    """
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime._system_prompt)
    assert source.index("jarvis-profile") < source.index("learned_block"), (
        "배운 것 블록이 프로필보다 앞에 있다 — 캐시가 매번 깨진다"
    )
    assert source.index("learned_block") < source.index("now_line_ko"), (
        "시각 줄보다 뒤에 있다 — 그 앞은 전부 캐시에 안 걸린다"
    )


# ── 사실 검색 ─────────────────────────────────────────────────────────────────

def test_a_fact_is_found_by_the_words_of_the_question(memory: ConversationMemory) -> None:
    """★ 이게 서랍의 존재 이유다.

    대화 조각에서는 「내 이름이 뭐야」가 '박가람'를 못 찾는다 — 겹치는 낱말이
    없기 때문이다. 사실 한 줄은 짧고 subject 가 질문의 말과 겹쳐서 걸린다.
    """
    memory.add_fact(
        kind="person", subject="사용자님 이름", fact="박가람",
        source_message_id=_seed(memory),
    )
    found = memory.search_facts("내 이름이 뭐야")
    assert found, "질문의 낱말로 사실을 못 찾았다"
    assert found[0]["fact"] == "박가람"


def test_searching_facts_for_something_unsaid_finds_nothing(memory: ConversationMemory) -> None:
    memory.add_fact(
        kind="person", subject="사용자님", fact="이름은 박가람",
        source_message_id=_seed(memory),
    )
    assert memory.search_facts("티라노사우루스 발톱 손질") == []


# ── P5 · 사람이 보고 고친다 (2026-08-24) ──────────────────────────────────────
#
# ★ **사람이 볼 수 없는 기억은 고칠 수도 없다.**
#
# 자동 추출이 도는 순간부터 틀린 사실이 쌓이고, 그건 매 턴 시스템 프롬프트에
# 실려 모든 답을 조금씩 물들인다. 그래서 목록·지우기가 추출과 **같은 날**이어야
# 한다. 나중에 만들자고 미루면 그 사이에 들어온 것은 아무도 모르게 산다.

def test_a_fact_comes_back_with_the_words_it_came_from(memory: ConversationMemory) -> None:
    """출처를 안 주면 사람이 지울지 말지 못 정한다.

    `source_message_id` 를 저장할 때 필수로 만든 규율이 여기서 값을 한다.
    """
    mid = memory.add_message("s1", "user", "우리 사무실 이번에 여수로 옮겼어")
    memory.add_fact(kind="product", subject="사무실", fact="여수", source_message_id=mid)

    rows = memory.facts_with_sources()
    assert len(rows) == 1
    assert rows[0]["source"], "근거가 안 왔다 — 이러면 사람이 판단할 수 없다"
    assert "여수로 옮겼어" in rows[0]["source"]["excerpt"]


def test_a_fact_whose_source_vanished_is_still_shown(memory: ConversationMemory) -> None:
    """★ 근거를 못 찾는 것을 **숨기지 않는다.**

    근거 없는 사실이 서랍에 있다는 것 자체가 사람이 알아야 할 정보다.
    조용히 빼면 그 사실은 영원히 안 보이면서 매 턴 실려 간다.
    """
    memory.add_fact(
        kind="person", subject="누군가", fact="무언가",
        source_message_id=999999,  # 없는 메시지
    )
    rows = memory.facts_with_sources()
    assert len(rows) == 1, "근거를 못 찾았다고 목록에서 빠졌다"
    assert rows[0]["source"] is None


def test_where_a_fact_came_from_is_kept(memory: ConversationMemory) -> None:
    """`seed`(사람이 쓴 문장)와 `extracted`(인용을 대조한 것)는 **근거의 세기가
    다르다.** 같은 것으로 보이면 사람이 그 차이를 못 본다.

    이걸 잘못 적었다가 한 번 걸렸다 — `seed_facts.py` 가 손으로 쓴 12줄을
    `extracted` 로 적고 있었다. 내가 막으려던 그 거짓말이었다(사고 I).
    """
    mid = memory.add_message("s1", "user", "여수로 옮겼어")
    memory.add_fact(kind="product", subject="a", fact="b", source_message_id=mid, origin="seed")
    memory.add_fact(kind="product", subject="c", fact="d", source_message_id=mid, origin="extracted")
    origins = {row["origin"] for row in memory.facts_with_sources()}
    assert origins == {"seed", "extracted"}


def test_the_screen_can_actually_reach_it() -> None:
    """★ 판정을 만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다.

    이 저장소가 여섯 번 겪은 모양이다(도구를 만들어도 갈래가 없으면 안 쓰인다).
    """
    import inspect

    from alture_jarvis.api import create_app

    source = inspect.getsource(create_app)
    assert "/v1/memory/facts" in source, "목록 경로가 없다"
    assert "/v1/memory/facts/forget" in source, "지우는 경로가 없다"


def test_forgetting_is_covering_not_deleting() -> None:
    """지우면 왜 바뀌었는지가 사라지고 같은 오해가 다시 들어온다."""
    import inspect

    from alture_jarvis.api import create_app

    source = inspect.getsource(create_app)
    start = source.index("/v1/memory/facts/forget")
    block = source[start : start + 600]
    assert "supersede_fact" in block, "덮는 게 아니라 지우고 있다"
