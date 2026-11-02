"""2026-11-01 — 코드 판 스킬 고르기 · 브라우저를 닫으며 쓴 답으로 마무리 · 접기 천장을 잰 토큰으로.

까닭은 각 코드의 주석에 있다(runtime `_CODE_SKILL_DROP` · agent `_finishes_at_wrap_up` · transcript_policy `window_fitted_budget`).
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis import agent as agent_mod
from alture_jarvis import runtime as runtime_mod
from alture_jarvis.skills import load_skills, match_skills
from alture_jarvis.transcript_policy import transcript_cap_chars, window_fitted_budget

ROOT = Path(__file__).resolve().parents[1]


# ── 코드 판 스킬 ──────────────────────────────────────────────

def test_code_jobs_do_not_spend_the_slot_on_verification_prose() -> None:
    available = {"verification-before-completion", "systematic-debugging", "diagnosing-bugs", "codebase-design"}
    swapped = runtime_mod._swap_code_skills(
        [("verification-before-completion", 2), ("systematic-debugging", 1)], available,
    )
    assert swapped == [("diagnosing-bugs", 1)]


def test_debugging_swaps_to_the_stronger_playbook_only_when_it_is_there() -> None:
    assert runtime_mod._swap_code_skills([("systematic-debugging", 2)], {"systematic-debugging"}) == [
        ("systematic-debugging", 2)
    ]
    # 둘 다 걸려도 하나만 남는다(같은 일을 두 번 싣지 않는다).
    both = runtime_mod._swap_code_skills(
        [("systematic-debugging", 2), ("diagnosing-bugs", 1)], {"systematic-debugging", "diagnosing-bugs"},
    )
    assert both == [("diagnosing-bugs", 2)]


def test_the_new_skills_are_on_disk_with_their_licence() -> None:
    skills = load_skills(ROOT / "skills")
    for name in ("diagnosing-bugs", "codebase-design", "unity-physics", "unity-animation", "unity-csharp-scripting"):
        assert name in skills, name
    assert (ROOT / "skills" / "vendor" / "mattpocock" / "LICENSE").exists()
    assert (ROOT / "skills" / "vendor" / "gamedev-unity" / "LICENSE").exists()


def test_unity_topic_words_reach_their_skill() -> None:
    names = [name for name, _ in match_skills("유니티에서 리지드바디 콜라이더가 서로 안 부딪혀 고쳐줘")]
    assert "unity-physics" in names
    names = [name for name, _ in match_skills("애니메이터 블렌드 트리 설정 좀 봐줘")]
    assert "unity-animation" in names
    # 일을 시키는 말이 없으면 붙이지 않는다 — 기존 규칙 그대로(`match_skills`).
    assert match_skills("유니티에서 리지드바디 콜라이더가 서로 안 부딪혀") == []


def test_structure_words_reach_codebase_design() -> None:
    names = [name for name, _ in match_skills("이 모듈 구조 개선하고 인터페이스 설계 다시 해줘")]
    assert "codebase-design" in names


# ── 브라우저를 닫으며 쓴 답으로 마무리 ─────────────────────────

def test_a_research_job_finishes_on_the_answer_written_with_the_close() -> None:
    assert agent_mod._finishes_at_wrap_up(
        "알라딘에서 '파이썬'을 검색해 상위 3권의 제목 · 저자 · 판매가", model_role="chat", require_sandbox=False,
    )


def test_a_job_that_asks_for_a_file_keeps_its_next_turn() -> None:
    for prompt in ("상위 3권을 엑셀로 정리해", "보고서로 만들어 줘", "csv 로 저장", "save it as a spreadsheet"):
        assert not agent_mod._finishes_at_wrap_up(prompt, model_role="chat", require_sandbox=False), prompt


def test_code_jobs_keep_their_next_turn() -> None:
    assert not agent_mod._finishes_at_wrap_up("버그 고쳐줘", model_role="code", require_sandbox=False)
    assert not agent_mod._finishes_at_wrap_up("버그 고쳐줘", model_role="chat", require_sandbox=True)


def test_the_loop_uses_the_held_answer_instead_of_calling_the_model() -> None:
    source = (ROOT / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert "message, used_thinking = finishing_turn or self._model_turn_that_may_step_aside(" in source
    assert "wrap_up_finish = said_in_full" in source


# ── 접기 천장 ─────────────────────────────────────────────────

def test_the_ceiling_follows_measured_tokens_not_a_char_guess() -> None:
    # 10-31 22:03 판: 창 196,608 · 보낸 248,618자 = 101,468토큰에서 27만 자 천장에 걸려 접혔다.
    widened = window_fitted_budget(263_782, num_ctx=196_608, sent_chars=248_618, prompt_tokens=101_468, widen=True)
    assert widened > transcript_cap_chars(196_608)
    # 그래도 창의 85% 를 넘게 넓히지 않는다(남은 자리 × 1.5자).
    share_room = int(196_608 * 0.85) - 8_192 - 101_468
    assert widened <= 248_618 + int(share_room * 1.5)


def test_narrowing_is_unchanged() -> None:
    assert window_fitted_budget(100_000, num_ctx=32_768, sent_chars=90_000, prompt_tokens=30_000) < 100_000


# ── 목록에 보이는 칸만 달라고 한 요청 ─────────────────────────

def test_titles_authors_and_prices_from_a_result_list_need_no_opening() -> None:
    from alture_jarvis.plan import says_list_only

    assert says_list_only("알라딘에서 '파이썬'을 검색해 결과 상위 3권의 제목 · 저자 · 판매가를 표로 정리해 줘.")
    assert says_list_only("크몽에서 AI 자동화 관련 서비스 상위 3개의 제목과 가격을 알려줘")
    # 상세에만 있는 값은 그대로 연다.
    assert not says_list_only("YES24 에서 파이썬 책 2권의 쪽수 · ISBN 을 알려줘")
    assert not says_list_only("사람인에서 공고 3개의 회사명 · 연봉 · 자격 요건을 비교표로")
