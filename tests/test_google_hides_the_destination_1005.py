"""구글이 목적지를 숨긴 링크(`/goto?url=암호화`)로 결과를 줄 때도 결과를 읽는다 (2026-10-05).

갓 만든 크롬 프로필(= 새로 설치한 사람 전원)에서 구글이 결과 링크를 전부 `https://www.google.com/goto?url=CAES…` 로 줬다.
그 주소는 구글 것이라 「화면 장치」로 걸러졌고, 결과가 떠 있는데 `result_count: 0` 이 나갔다(9B 허깅페이스 판에서 다섯 번).
운영 크롬은 구글에 로그인돼 있어 실제 주소가 와서 여태 안 보였다.

아래 줄들은 그 화면의 스냅샷에서 그대로 옮긴 것이다(값은 줄였다).
"""
from __future__ import annotations

from alture_jarvis.serp import collect_results, is_navigation, opaque_outbound, shown_host

GOTO = "https://www.google.com/goto?url=CAESVgHrOzAV8DD0Pwy5Y8CuiIPbOch9uGTZ"
ROWS = [
    {"name": "AI 모드", "href": "https://www.google.com/search?q=huggingface+blog&udm=50", "ref": "j14"},
    {"name": "이미지", "href": "https://www.google.com/search?q=huggingface+blog&udm=2", "ref": "j16"},
    # AI 요약의 출처 칩 — 같은 꼴인데 가는 곳이 안 적혀 있다.
    {"name": "Hugging Face Blog", "href": GOTO + "chipA", "ref": "j23"},
    {"name": "Releasebot", "href": GOTO + "chipB", "ref": "j31"},
    # 정식 결과 — 글자에 가는 곳이 적혀 있다.
    {"name": "Hugging Face – Blog Hugging Face https://huggingface.co › blog", "href": GOTO + "one", "ref": "j45"},
    {"name": "Three Million Models and Counting Hugging Face https://huggingface.co › blog › ivanfioravanti › three-mi...",
     "href": GOTO + "two", "ref": "j47"},
    {"name": "Hugging Face Release Notes - October 2026 Latest Updates Releasebot https://releasebot.io › updates › huggingface",
     "href": GOTO + "three", "ref": "j63"},
    {"name": "Page 2", "href": "https://www.google.com/search?q=huggingface+blog&start=10", "ref": "j73"},
    {"name": "개인정보처리방침", "href": "https://policies.google.com/privacy?hl=ko", "ref": "j87"},
]


def test_results_are_found_when_google_hides_where_they_go():
    results = [item.as_dict() for item in collect_results(ROWS, limit=10)]
    assert [item["rank"] for item in results] == [1, 2, 3]
    assert [item["domain"] for item in results] == ["huggingface.co", "huggingface.co", "releasebot.io"]
    assert results[0]["url"].startswith("https://www.google.com/goto?url="), "여는 주소는 구글이 준 그대로 — 열면 구글이 넘긴다"
    assert results[0]["title"].startswith("Hugging Face – Blog")


def test_a_source_chip_without_a_shown_address_is_not_a_result():
    assert is_navigation("Hugging Face Blog", GOTO + "chipA") is True
    assert is_navigation("Hugging Face – Blog Hugging Face https://huggingface.co › blog", GOTO + "one") is False


def test_the_engines_own_links_are_still_navigation():
    assert opaque_outbound("https://www.google.com/search?q=huggingface+blog") is False
    assert is_navigation("이미지", "https://www.google.com/search?q=huggingface+blog&udm=2") is True
    # 광고 클릭 길(/aclk)은 나가는 길 목록에 없다 — 계속 거른다.
    assert opaque_outbound("https://www.google.com/aclk?sa=l&url=CAESxyz") is False
    assert is_navigation("Sponsored https://ads.example.com", "https://www.google.com/aclk?sa=l&url=CAESxyz") is True
    # 다른 사이트의 /goto 는 이 규칙과 무관하다.
    assert opaque_outbound("https://example.com/goto?url=abc") is False


def test_a_wrapped_link_that_can_be_unwrapped_still_is():
    rows = [{"name": "FastAPI docs https://fastapi.tiangolo.com", "href": "https://www.google.com/url?q=https://fastapi.tiangolo.com/&sa=U", "ref": "j1"},
            {"name": "Requests https://requests.readthedocs.io", "href": "https://requests.readthedocs.io/en/latest/", "ref": "j2"}]
    results = [item.as_dict() for item in collect_results(rows, limit=5)]
    assert [item["domain"] for item in results] == ["fastapi.tiangolo.com", "requests.readthedocs.io"]
    assert results[0]["url"].startswith("https://fastapi.tiangolo.com")


def test_shown_host():
    assert shown_host("Trending Papers Hugging Face https://huggingface.co › papers › trending") == "huggingface.co"
    assert shown_host("Docs https://www.python.org › 3") == "python.org"
    assert shown_host("Hugging Face Blog") == ""


# ── 같은 판의 둘째: 사이트가 거절한 주소(400)를 「열었다」고 했다 ─────────────────────────────────────
#
# 모델이 `huggingface.co/models?sort=trending&direction=desc` 를 지어 열었고 화면은 「400 · Invalid input: expected never,
# received string → at direction」였다. 도구는 OK 와 「이 사이트에는 검색칸이 있다」를 돌려줬고, 모델은 오류 화면인 줄 모르고
# 스크롤·재검색을 열일곱 걸음 했다.
import inspect

from alture_jarvis.browser import BrowserWorker


class _Response:
    def __init__(self, status):
        self.status = status


class _Page:
    def __init__(self, body):
        self._body = body

    def evaluate(self, _script, cap):
        return self._body[:cap]


def _rejected(status, body):
    return BrowserWorker._rejected_address(BrowserWorker, _Page(body), _Response(status))  # type: ignore[arg-type]


def test_a_rejected_address_reports_what_the_page_said():
    status, said = _rejected(400, "400\n\nInvalid input: expected never, received string\n→ at direction")
    assert status == 400
    assert "Invalid input" in said and "at direction" in said


def test_a_long_page_is_left_alone_even_if_the_status_is_400():
    assert _rejected(400, "x" * 5000) is None, "상태만 400 이고 내용이 있는 화면은 건드리지 않는다"


def test_other_statuses_are_not_this_rule():
    for status in (200, 301, 401, 403, 404, 429, 500):
        assert _rejected(status, "Invalid input") is None, status


def test_the_open_door_raises_before_calling_it_opened():
    source = inspect.getsource(BrowserWorker)
    assert "rejected = self._rejected_address(page, response)" in source
    assert "address_rejected:" in source and "화면이 말한 것" in source
    assert source.index("self._not_found_page(page, response)") < source.index("self._rejected_address(page, response)")


# ── 같은 뿌리의 셋째: 1번을 연 뒤 2·3번이 구글의 것이 아니라 들어간 사이트 안의 링크였다 ───────────────
#
# 순위 속 주소가 전부 구글 것(`/goto?url=…`)이라, 도착한 사이트를 「이 순위를 타고 온 상세」로 못 알아봤다.


class _Landed:
    def __init__(self, url):
        self.url = url


def _worker_with_ranks():
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._visited = []
    worker._last_results = [
        {"rank": 1, "title": "Best Local LLMs for 12GB VRAM https://atomic.chat › blog", "url": GOTO + "one"},
        {"rank": 2, "title": "RTX 3080 12GB guide https://www.fitmyllm.com › blog", "url": GOTO + "two"},
    ]
    worker._results_origin_host = "www.google.com"
    return worker


def test_the_landed_address_is_written_into_the_rank():
    worker = _worker_with_ranks()
    match = worker._last_results[0]
    BrowserWorker._remember_where_it_landed(worker, _Landed("https://atomic.chat/blog/guides/best-local-llm-12gb"), match, match["url"])
    assert match["url"] == "https://atomic.chat/blog/guides/best-local-llm-12gb"
    assert match["via"].startswith("https://www.google.com/goto?url=")


def test_after_landing_the_google_ranks_are_still_ours():
    """도착한 화면에 관련 글 목록이 있어도, 지금 주소가 순위 속 주소면 그 순위를 타고 온 상세다."""
    worker = _worker_with_ranks()
    match = worker._last_results[0]
    page = _Landed("https://atomic.chat/blog/guides/best-local-llm-12gb")
    worker._result_list_rows = lambda _page: [{"href": "x"}] * 9  # 상세의 「관련 글」 묶음
    assert BrowserWorker._results_are_someone_elses(worker, page) is True, "적기 전에는 남의 목록으로 본다(고치기 전 모습)"
    BrowserWorker._remember_where_it_landed(worker, page, match, match["url"])
    assert BrowserWorker._results_are_someone_elses(worker, page) is False


def test_an_ordinary_link_is_left_as_it_is():
    worker = _worker_with_ranks()
    match = {"rank": 1, "url": "https://example.com/a"}
    BrowserWorker._remember_where_it_landed(worker, _Landed("https://example.com/b"), match, match["url"])
    assert match == {"rank": 1, "url": "https://example.com/a"}
