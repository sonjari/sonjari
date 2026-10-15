"""영어로 시켜도 **같은 요구·같은 갈래·같은 스킬**이 선다 (2026-09-23 밤, 영어판 P1).

처음 잰 값: 계획 10/85 · 스킬 0/42. 영어 요청은 요구를 못 뽑아 되받기·미달 판정·구글 갈래가 안 돌았다 — 한국어에서 「라우팅
낱말표 → 78% 창작」으로 겪은 모양이 영어 사용자에게 그대로 간다. 영어 층(`english.py`)은 **영어가 주된 요청에만** 걸어서
한국어 판정을 구조로 지킨다. 쌍은 실제 요청에서 골랐다(`scripts/language_pairs.py`).

한국어 쪽에서 드러난 구멍도 같이 고쳤다(아래 「한국어」 절) — 짝을 맞추다 보니 한국어가 틀린 자리가 보였다.
바꾼 뒤 실제 요청 1,181개의 판정을 전후로 비교했다(`scripts/harness_snapshot.py`): 바뀐 33개를 하나씩 봤고 전부 고친 쪽이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from alture_jarvis import agent, english, plan, skills
from alture_jarvis.runtime import JarvisRuntime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from language_pairs import PAIRS  # noqa: E402


def _plan(prompt: str) -> list[tuple[str, str]]:
    return sorted({(r.kind, str(r.target)) for r in plan.extract(prompt, must_observe=True)})


def _skills(prompt: str) -> list[str]:
    return [name for name, _hits in skills.match_skills(prompt)]


# ── 동등성 눈금 ────────────────────────────────────────────────────────────────


def test_plan_parity_stays_above_ninety_five_percent() -> None:
    same = sum(_plan(ko) == _plan(en) for ko, en in PAIRS)
    assert len(PAIRS) >= 80
    assert same / len(PAIRS) >= 0.95, f"계획 동등성 {same}/{len(PAIRS)}"


def test_skill_parity_stays_above_ninety_five_percent() -> None:
    judged = [(ko, en) for ko, en in PAIRS if _skills(ko)]
    same = sum(_skills(ko) == _skills(en) for ko, en in judged)
    assert same / len(judged) >= 0.95, f"스킬 동등성 {same}/{len(judged)}"


# ── 언어 판정 ─────────────────────────────────────────────────────────────────


def test_a_korean_instruction_with_a_pasted_english_log_stays_korean() -> None:
    """★ 좋은 표본 — 지시는 한국어, 붙여넣은 오류가 영어. 비율만 보면 영어로 잡혀 한국어 판정을 잃었다."""
    prompt = ("이 저장소에서 다음 테스트가 실패한다: tests/test_facts_drawer.py 실패 출력: E AttributeError: "
              "'ConversationMemory' object has no attribute 'facts' while importing the module under test")
    assert not english.english_dominant(prompt)


def test_an_english_sentence_with_a_korean_site_name_is_english() -> None:
    assert english.english_dominant("Find 3 accounting job posts on 사람인 and put them in Excel")


# ── 영어 ───────────────────────────────────────────────────────────────────────


def test_negation_comes_before_the_verb_in_english() -> None:
    requirements = _plan("Write a blog post and only save it as a draft. Don't publish it.")
    assert ("action", "naver_blog_save_draft") in requirements
    assert ("action", "naver_blog_publish") not in requirements


@pytest.mark.parametrize("prompt", [
    "Add a team meeting to my calendar tomorrow at 3pm",      # 3pm 은 시각
    "It went up 10% in March",                                # 10% 는 비율
    "Compute it to two decimal places",                       # 자릿수
    "Search the web but don't open more than 2 pages",        # 상한
    "Please read report.pdf and tell me the three main risks",  # 내놓을 것
])
def test_numbers_that_are_not_read_counts(prompt: str) -> None:
    """★ 좋은 표본 — 영어는 단위가 없어 수 뒤 명사로 가른다. 시각·비율·상한·내놓을 것은 읽을 개수가 아니다."""
    assert not any(kind == "count" for kind, _ in _plan(prompt))


def test_a_count_of_things_to_read_is_a_read_requirement() -> None:
    assert ("count", "3") in _plan("Find 3 accounting job posts in Yeosu on Saramin and list the companies")
    assert ("count", "3") in _plan("Search Kyobo for 'Python' books and tell me the titles and prices of the top 3.")


def test_english_site_names_resolve_to_the_same_hosts() -> None:
    assert ("site", "('saramin.co.kr',)") in _plan("Tell me the titles of 3 accounting job posts on Saramin")
    assert ("site", "('wishket.com',)") in _plan("Tell me the budgets of 3 AI agent projects on Wishket")


@pytest.mark.parametrize("prompt, tool", [
    ("Delete the meeting on Friday", "google_calendar_delete"),
    ("Reschedule my dentist appointment to next Monday at 10am", "google_calendar_update"),
    ("Upload this report to my Google Drive", "google_drive_write"),
    ("Send an email to test@example.com with the subject 'hi'", "google_gmail_send"),
    ("Calculate the average of 12, 15 and 20", "sandbox_run"),
])
def test_english_actions_open_the_same_tools(prompt: str, tool: str) -> None:
    assert ("action", tool) in _plan(prompt)


def test_quoted_content_is_not_an_instruction() -> None:
    """★ 「write 'scope check'」의 check 는 적을 내용이다 — 읽으라는 말로 보면 읽을 대상 없는 영원한 미달이 된다."""
    requirements = _plan("Create a memo.txt file in C:\\work and write 'scope check' in it")
    assert ("artifact", "('.txt',)") in requirements or any(kind == "artifact" for kind, _ in requirements)
    assert not any(kind == "observe" for kind, _ in requirements)


def test_a_negated_make_is_not_an_artifact_request() -> None:
    assert not plan.wants_an_artifact("Search the YES24 site for the book. No need to make a file, just answer.")
    assert not plan.wants_code("Suppose this test fails: tests/test_x.py. Don't fix anything, only judge.")


def test_an_output_format_file_is_not_the_inside_of_this_computer() -> None:
    """「an Excel file」은 내놓을 형식이다 — 「내 컴퓨터 안」으로 보면 조사 갈래가 닫힌다."""
    assert JarvisRuntime._requires_web_research(
        "Find 3 accounting job posts in Yeosu on Saramin and put company names in an Excel file")


def test_a_blog_is_where_we_write_not_a_source() -> None:
    assert agent.named_sources("Write a short post titled 'Tips' on the Robometafit blog and save it as a draft") == []


def test_english_skill_triggers_use_word_boundaries() -> None:
    assert "document-craft" in _skills("Research 3 AI agent projects on Wishket and put them in an Excel file")
    assert "launch" not in _skills("Search the web for the latest Claude release notes")


# ── 한국어 — 짝을 맞추다 드러난 구멍 ───────────────────────────────────────────


def test_google_is_not_a_read_intent() -> None:
    """「구글」의 「글」이 읽기 요구(`observe browser`)를 달았다."""
    assert ("observe", "any") in _plan("내 구글 캘린더에 내일 오후 3시 일정 하나 등록해줘")


def test_applicants_are_not_an_action_count() -> None:
    """「지원자 수」의 「지원」이 행위라 「3개 실제로 처리하기」가 됐다."""
    requirements = _plan("위시켓에서 AI 에이전트 관련 프로젝트 3개의 예상 기간과 지원자 수를 알려줘")
    assert ("count", "3") in requirements and ("count_action", "3") not in requirements


def test_word_is_a_file_target_in_korean_too() -> None:
    assert plan.wants_an_artifact("이력서 초안을 워드로 써줘")
    assert plan.artifact_extensions("이력서 초안을 워드로 써줘") == (".docx",)


def test_a_sentence_final_period_is_not_part_of_the_extension() -> None:
    assert ".py" in plan.artifact_extensions("Read INSTRUCTIONS.md and implement beer_song.py. Don't modify the test file.")


@pytest.mark.parametrize("prompt, not_skill", [
    ("크몽에서 'AI 자동화' 키워드로 검색했을 때 상위 5개 서비스의 제목과 가격을 알려줘.", "document-craft"),
    ("YES24에서 책 2권의 쪽수를 확인해줘. 파일로 만들 필요는 없고 결과만 답해줘.", "document-craft"),
    ("네이버 뉴스에서 기사 3개를 찾아서 제목·언론사·한 줄 요약을 표로 정리한 워드 문서로 만들어줘", "public-relations"),
])
def test_korean_skill_false_positives_are_gone(prompt: str, not_skill: str) -> None:
    assert not_skill not in _skills(prompt)
