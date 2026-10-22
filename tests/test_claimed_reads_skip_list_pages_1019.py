"""「글 N개를 직접 열어 확인했습니다」 대조에서 목록 화면은 「연 곳」이 아니다 (2026-10-19).

긱뉴스 판 1bc39285: 답은 「글 4개를 직접 열어 확인」인데 연 글은 둘이었고, 목록 화면까지 「연 곳」으로 세어 경고가 서지 않았다.
목록만 보고 글은 하나도 안 연 판(1b6df02d 모양)은 「연 곳 0」으로 대조해야 한다 — 예전엔 `not places` 에 걸려 아무 말도 안 했다.
반대로 결과를 골라 연 상세(`browser_open_result`)는 늘 글이다(사람인 7643c135 — 상세가 목록으로 찍혀 셋이 둘로 셀 뻔했다).
"""

from alture_jarvis.agent import claimed_reads_note


def _step(tool, url, n, **extra):
    return {"step": n, "tool": tool, "ok": True, "arguments": {}, "evidence": {"url": url, "title": extra.get("title", url)}}


def _list_pages_then_links():
    steps = []
    n = 0
    for page in range(1, 4):
        url = "https://news.example.test/show" + ("" if page == 1 else f"?page={page}")
        n += 1
        steps.append(_step("browser_open", url, n, title="Show"))
        n += 1
        steps.append(_step("browser_extract", url, n, title="Show"))
    return steps


def test_list_pages_only_against_a_claim_of_ten_opened_posts_warns_with_zero():
    steps = _list_pages_then_links()
    note = claimed_reads_note("글 10개를 직접 열어 확인했습니다.", steps)
    assert "0곳" in note
    assert "목록 화면" in note


def test_posts_opened_from_results_are_counted_even_if_a_rule_calls_them_lists():
    steps = []
    for n, rec in enumerate(("101", "202", "303"), start=1):
        url = f"https://jobs.example.test/view?rec_idx={rec}"
        steps.append(_step("browser_open_result", url, n * 2 - 1, title=f"공고 {rec}"))
        steps.append(_step("browser_extract", url, n * 2, title=f"공고 {rec}"))
    assert claimed_reads_note("공고 3개를 직접 열어 확인했습니다.", steps) == ""


def test_no_page_at_all_still_says_nothing():
    steps = [{"step": 1, "tool": "local_read_file", "ok": True, "arguments": {"path": "C:/x.txt"}, "evidence": {}}]
    assert claimed_reads_note("파일 3개를 직접 열어 확인했습니다.", steps) == ""
