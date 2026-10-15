"""아무것도 못 읽은 판의 답은 문서로 옮기지 않는다 (2026-09-29 밤, AWS 첫 실행).

크롬 없는 PC 에서 「YES24에서 파이썬 입문서 3권의 쪽수와 가격을 비교해서 문서로 만들어줘」. 브라우저가 한 번도
안 떠서 읽은 곳이 0 이었는데, 실패를 설명하는 답(제목 + 표)이 산출물 안전망(`_forced_artifact_decision`)을
통과해 워드가 됐다 — `브라우저를_재시작했지만_Playwright_브라우저가_아직_설치되지.docx`, 대조표는 「산출물 ✅」.
"""
from __future__ import annotations

from alture_jarvis.agent import _forced_artifact_decision
from alture_jarvis.plan import check as check_plan, extract as extract_plan

PROMPT = "YES24에서 파이썬 입문서 3권의 쪽수와 가격을 비교해서 문서로 만들어줘"

FAILURE_ANSWER = """## 브라우저를 재시작했지만 Playwright 브라우저가 아직 설치되지 않았습니다

브라우저가 실행되지 않아서 YES24 로 직접 접속할 수 없습니다.

| 항목 | 상태 |
| --- | --- |
| YES24 접속 | 실패 (브라우저 없음) |
| 도서 정보 | 확인 못 함 |

## 📝 대안: 수동 정보 입력으로 문서 제작

YES24 에서 직접 확인한 3권의 파이썬 입문서 정보를 주시면 바로 문서를 만들어 드립니다.
"""

REAL_ANSWER = """## YES24 파이썬 입문서 3권 비교

YES24 상세 페이지 세 곳을 직접 열어 쪽수와 판매가를 확인했습니다. 가격은 정가가 아니라 오늘 기준 판매가입니다.

| 도서명 | 쪽수 | 가격 |
| --- | --- | --- |
| 혼자 공부하는 파이썬 | 552쪽 | 22,000원 |
| Do it! 점프 투 파이썬 | 432쪽 | 22,000원 |
| 파이썬 코딩 도장 | 668쪽 | 27,000원 |
"""

FAILED_STEPS = [
    {"tool": "browser_open", "ok": False, "error": "browser_start_failed"},
    {"tool": "browser_site_search", "ok": False, "error": "browser_start_failed"},
    {"tool": "sandbox_run", "ok": False, "error": "tool_disabled"},
]

READ_STEPS = [
    {"tool": "browser_extract", "ok": True, "evidence": {"url": f"https://www.yes24.com/product/goods/{n}"}}
    for n in (1, 2, 3)
]


def _decide(answer: str, steps: list[dict]):
    plan = extract_plan(PROMPT, has_named_source=True)
    sources = [str((s.get("evidence") or {}).get("url") or "") for s in steps]
    results = check_plan(plan, sources=[u for u in sources if u], steps=steps)
    return _forced_artifact_decision(results, steps, answer, PROMPT)


def test_nothing_read_means_no_document() -> None:
    call, reason = _decide(FAILURE_ANSWER, FAILED_STEPS)
    assert call is None
    assert reason == "nothing_was_read"


def test_a_run_that_read_pages_still_gets_its_document() -> None:
    call, reason = _decide(REAL_ANSWER, READ_STEPS)
    assert call is not None, reason
