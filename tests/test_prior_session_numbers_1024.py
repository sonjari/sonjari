"""같은 대화의 앞 판에서 도구가 준 숫자는 쓰기 전 숫자 문의 근거다 · 소제목 번호는 숫자 주장이 아니다 (2026-10-24).

대표 판(ab760dc8): 「지금까지 조사한 거 전부 MD 로」가 「읽은 자료에 없는 숫자 59개」로 두 번 막혔다. 53개는 같은 대화의 앞 판
도구가 읽어 온 숫자였고 6개는 「### 2.4 …」 같은 소제목 번호였다 — 근거 없는 숫자는 0개였다. 모델은 안내대로 페이지를 다시
열었고 같은 긴 문서를 세 번 썼다(422초 중 약 280초).
"""
from __future__ import annotations

import inspect
import time
import types

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import GROUNDED_WRITE_MIN, ungrounded_write_numbers
from alture_jarvis.evidence import numbers_claimed_in, numbers_in_body


# ── 소제목 번호 ───────────────────────────────────────────────────────────────────

def test_section_numbers_in_headings_are_not_claims() -> None:
    doc = "### 2.4 리뷰엉이 형식 해부\n## 3. 결론\n#### 5.2.1 구조\n본문"
    assert numbers_claimed_in(doc) == set()


def test_values_in_headings_and_dotted_values_in_text_are_still_claims() -> None:
    claimed = numbers_claimed_in("## 37 stars 달성\n### 2.4초 단축\n조회수 2.4 배")
    assert {"37", repr(2.4)} <= claimed


# ── 앞 판 숫자를 모으는 쪽(런타임) ────────────────────────────────────────────────

def _runtime_with(jobs):  # noqa: ANN001
    from alture_jarvis.runtime import JarvisRuntime

    rt = JarvisRuntime.__new__(JarvisRuntime)
    rt.store = types.SimpleNamespace(list_jobs=lambda limit, status: jobs)
    return rt


def _job(job_id, session, *, age=60.0, numbers=(), body=(), answer=""):  # noqa: ANN001
    return {
        "id": job_id, "payload": {"session_id": session}, "finished_at": time.time() - age,
        "result": {"answer": answer, "agent_trace": {"tool_numbers": list(numbers), "tool_numbers_body": list(body)}},
    }


def test_numbers_come_from_every_earlier_job_in_the_conversation_even_past_a_chat_turn() -> None:
    jobs = [
        _job("chat", "s1", age=30, answer="훅 후보: 월 50만 원"),        # 도구 없이 답한 대화 판이 사이에 낀다
        _job("research", "s1", age=600, body=["1060000", "970000"]),
        _job("older", "s1", age=1500, numbers=["1860000"]),
    ]
    got = _runtime_with(jobs)._prior_session_numbers("s1", "now")
    assert got == {"1060000", "970000", "1860000"}
    assert "500000" not in got, "앞 판 **답**의 숫자는 근거가 아니다"


def test_other_conversations_old_jobs_and_this_job_are_left_out() -> None:
    jobs = [
        _job("now", "s1", body=["11"]),
        _job("other", "s2", body=["22"]),
        _job("stale", "s1", age=9000, body=["33"]),
    ]
    assert _runtime_with(jobs)._prior_session_numbers("s1", "now") == frozenset()
    assert _runtime_with(jobs)._prior_session_numbers("", "now") == frozenset()


# ── 판 쪽: 숫자 문이 그 숫자를 근거로 친다 ─────────────────────────────────────────

def test_the_summary_that_was_blocked_twice_now_passes() -> None:
    doc = {"path": "전략.md", "text": "### 2.4 롱폼\n| 인류에게 남은 시간 | 106만 |\n| 복어 독 | 97만 |\n| 매머드 | 103만 |"}
    earlier = set(numbers_in_body({"text": "인류 106만 · 복어 97만 · 매머드 103만"}))   # 앞 판이 페이지에서 걷은 그대로
    assert len(ungrounded_write_numbers(doc, set())) >= GROUNDED_WRITE_MIN, "이 판만 보면 막힌다 — 이 시험이 보려는 빈칸"
    assert ungrounded_write_numbers(doc, earlier) == []


def test_a_made_up_number_is_still_caught_with_earlier_numbers_in_hand() -> None:
    doc = {"text": "| 영상 | 106만 |\n| 영상 | 77만 |\n| 영상 | 88만 |\n| 영상 | 12만 |"}
    assert len(ungrounded_write_numbers(doc, set(numbers_in_body({"text": "106만"})))) >= GROUNDED_WRITE_MIN


def test_the_run_loop_adds_earlier_numbers_at_every_grounding_gate() -> None:
    source = inspect.getsource(agent_module.BrowserAgent.run)
    assert "prior_numbers" in inspect.signature(agent_module.BrowserAgent.run).parameters
    assert source.count("numbers_read_in(messages) | set(prior_numbers or ())") == 4
    from alture_jarvis.runtime import JarvisRuntime

    assert "prior_numbers=self._prior_session_numbers(session_id" in inspect.getsource(JarvisRuntime)


# ── 판단이라고 밝힌 의견 답은 찾으러 보내지 않는다 (대표 판 f7269ce4) ──────────────────────

def test_an_opinion_answer_that_says_it_is_a_judgment_is_kept() -> None:
    from alture_jarvis.runtime import _judgment_answer_kept

    draft = "제 판단으로 답합니다. 1,000 은 최소선, 3,000~5,000 이면 괜찮아 보이고, 10,000 은 1~2년 걸립니다."
    assert _judgment_answer_kept("너가 봤을 때 소규모 팀이 구독자 어느 정도면 괜찮아 보이노", draft)


def test_a_made_up_fact_is_still_sent_to_look() -> None:
    from alture_jarvis.runtime import _judgment_answer_kept

    fact = "업스테이지 최신은 Solar Pro 4 입니다. 512K 창, 입력 $0.30, Solar Open 2 250B."
    assert not _judgment_answer_kept("업스테이지 솔라 최신 모델 이름이 뭐야", fact), "판단이라고 안 밝힌 사실 단정"
    assert not _judgment_answer_kept("솔라 최신 모델 확인해서 알려줘", "제 짐작으로는 Solar Pro 4 · 512K"), "확인을 시킨 질문"


def test_the_router_keeps_the_labelled_draft_only_below_the_known_site_rule() -> None:
    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime)
    assert "needed > 1 and _judgment_answer_kept(prompt, answer)" in source


def test_prior_reads_skip_a_chat_turn_between_research_and_summary() -> None:
    from alture_jarvis.runtime import JarvisRuntime

    def job(job_id, age, reads, answer):  # noqa: ANN001
        return {"id": job_id, "payload": {"session_id": "s1"}, "finished_at": time.time() - age,
                "result": {"answer": answer, "agent_trace": {"evidence": [
                    {"ok": True, "type": "body_read", "source_id": url} for url in reads]}}}

    rt = JarvisRuntime.__new__(JarvisRuntime)
    rt.store = types.SimpleNamespace(list_jobs=lambda limit, status: [
        job("chat", 60, [], "훅 후보"), job("research", 400, ["https://www.youtube.com/@reviewowl"], "리뷰엉이 표"),
    ])
    got = rt._prior_session_reads("s1", "now")
    assert got["prior_reads"] == ["https://www.youtube.com/@reviewowl"] and got["prior_answer"] == "리뷰엉이 표"
