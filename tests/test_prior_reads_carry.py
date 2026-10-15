"""앞 판에서 이미 읽은 것은 다시 시키지 않는다 — 판이 아니라 대화 단위로 센다 (2026-09-24 노트북 실측).

「방금 찾은 사람인 부산 회계 공고 3개를 엑셀 파일로 정리해줘」에 계획 층이 「사람인에서 3개 열어 읽기」를 다시 걸어
앞 판 3개를 버리고 21걸음을 헤맸다(문맥 73.8K → 4B 사고 되풀이). 이어받기는 **문장이 아니라 앞 판이 읽은 주소**로 정한다.
"""

from __future__ import annotations

import time
import types

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.plan import asks_for_new_results, extract

SARAMIN = [
    "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1",
    "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=2",
    "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=3",
]
FOLLOW_UP = "방금 찾은 사람인 부산 회계 공고 3개를 엑셀 파일로 정리해줘"


def _carry(prompt: str, reads: list[str]):
    plan = extract(prompt, has_named_source=True)
    return BrowserAgent._carry_prior_reads(object(), plan, reads)  # type: ignore[arg-type]


def test_reads_from_the_previous_job_satisfy_the_follow_up():
    kept, carried = _carry(FOLLOW_UP, SARAMIN)
    assert {"3개 이상 직접 열어 읽기", "사람인에서 하기"} <= set(carried)
    # 만들 파일은 이번 판의 일이다 — 그대로 남는다.
    assert [item.kind for item in kept] == ["artifact"]


def test_reads_on_another_site_do_not_count():
    kept, carried = _carry(FOLLOW_UP, [u.replace("saramin.co.kr", "jobkorea.co.kr") for u in SARAMIN])
    assert carried == []
    assert {item.kind for item in kept} >= {"count", "site", "artifact"}


def test_too_few_prior_reads_leave_the_whole_research_to_this_job():
    kept, carried = _carry(FOLLOW_UP, SARAMIN[:2])
    # 사이트만 채워졌다고 사이트를 빼면 모자란 1개를 엉뚱한 데서 채운다 — 둘 다 남긴다.
    assert carried == []


def test_asking_for_more_is_not_a_follow_up():
    assert asks_for_new_results("사람인에서 부산 회계 공고 3개 더 찾아줘")
    assert asks_for_new_results("다른 공고 3개 추천해줘")
    assert asks_for_new_results("Find 3 more job posts on Saramin")
    assert not asks_for_new_results(FOLLOW_UP)
    assert not asks_for_new_results("그거 워드로도 만들어줘")


def _runtime_with(jobs):
    from alture_jarvis.runtime import JarvisRuntime

    rt = JarvisRuntime.__new__(JarvisRuntime)
    rt.store = types.SimpleNamespace(list_jobs=lambda limit, status: jobs)
    return rt


def _job(job_id, session, *, age=10.0, reads=SARAMIN, answer="표"):
    return {
        "id": job_id,
        "payload": {"session_id": session},
        "finished_at": time.time() - age,
        "result": {
            "answer": answer,
            "agent_trace": {"evidence": [
                {"ok": True, "type": "body_read", "source_id": u} for u in reads
            ] + [{"ok": True, "type": "page_open", "source_id": "https://www.jobkorea.co.kr/"}]},
        },
    }


def test_runtime_hands_over_only_body_reads_of_the_same_recent_session():
    rt = _runtime_with([_job("other", "s2"), _job("prev", "s1")])
    got = rt._prior_session_reads("s1", "now")
    assert got["prior_reads"] == SARAMIN and got["prior_answer"] == "표"
    assert _runtime_with([_job("prev", "s1", age=4000)])._prior_session_reads("s1", "now") == {}
    assert _runtime_with([_job("prev", "s1", reads=[])])._prior_session_reads("s1", "now") == {}
    assert _runtime_with([_job("prev", "s1")])._prior_session_reads("", "now") == {}
