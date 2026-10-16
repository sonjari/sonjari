"""「네이버에서 뉴스 세 개」의 읽은 수는 언론사 누리집에서 읽은 것도 센다 (2026-10-16).

튜토리얼 후보 측정(185f5208): 네이버 검색으로 기사 12곳을 열어 읽었는데 「3개 이상 직접 열어 읽기 — 1개 읽음」이었다.
지목한 사이트의 주소에서 읽은 것만 세는 규칙(사람인 공고 3개처럼)이 검색 엔진에도 걸렸다. 같은 문장 둘째 판은 기사 둘이
네이버 안 주소에 걸려 통과했다 — 운이 판정을 갈랐다. 양방향:
- 검색 엔진 바탕 주소(`naver.com`)를 지목하면 밖에서 읽은 것도 센다.
- 서비스를 지목하면(`blog.naver.com`) 그 주소만 센다 — 그대로.
- 일반 사이트(사람인)는 그 사이트에서 읽은 것만 센다 — 그대로.
표본의 주소는 지어낸 것이다.
"""

from __future__ import annotations

from alture_jarvis.plan import check, extract


def _read_count(prompt: str, sources: list[str]) -> tuple[bool, str]:
    reqs = extract(prompt)
    steps = [{"tool": "browser_extract", "ok": True, "evidence": {"url": url}} for url in sources]
    for req, ok, saw in check(reqs, sources=sources, steps=steps, answer="1. 가\n2. 나\n3. 다"):
        if req.kind == "count":
            return ok, saw
    raise AssertionError("개수 요구가 서지 않았다: " + ", ".join(r.label for r in reqs))


PRESS = ["https://press-a.example/news/1", "https://press-b.example/view/2", "https://press-c.example/article/3"]


def test_reads_reached_through_naver_search_count() -> None:
    ok, saw = _read_count("네이버에서 오늘 국내 뉴스 세 개를 직접 열어 읽고 제목과 한 줄 요약으로 정리해 줘", PRESS)
    assert ok, saw
    assert "3개" in saw


def test_a_named_naver_service_still_counts_only_its_own_pages() -> None:
    ok, saw = _read_count("네이버 블로그에서 캠핑 후기 글 세 개를 직접 열어 읽고 요약해 줘", PRESS)
    assert not ok, saw


def test_an_ordinary_named_site_still_counts_only_its_own_pages() -> None:
    ok, saw = _read_count("사람인에서 회계 공고 세 개를 직접 열어 읽고 마감일을 알려 줘", PRESS)
    assert not ok, saw
