"""중간 소식 — 일하는 동안 한 항목을 실제로 읽어 확인할 때마다 한 줄이 진행에 쌓이고, 호스트는 최근 몇 줄만 받는다 (2026-11-14).

대표(11-14): 「저장소 10개 다 돌린 뒤에 말하는 것보다 중간에 한 번만 알려줘도 사용자는 기다릴 맛이 난다」.
설계: `docs/설계_중간소식_2026-11-14.ko.md`.

## 지킬 것
1. 줄의 숫자는 **그 걸음에서 실제로 읽은 본문에 있는 것만** — 없으면 그 조각을 뺀다(답의 숫자 대조와 같은 눈금).
2. 「한 항목을 읽어 확인」한 걸음만 — 검색 결과 · 로그인 · 실패 · 빈 화면 · 목록 도구는 소식이 아니다.
3. 진행 중일 때만 실린다. 끝난 판은 최종 답이 우선이다(진행 칸 자체가 없다).
4. 길이 상한 — 최근 3줄, 줄 90자, 주소 160자.
"""

from __future__ import annotations

import inspect
from typing import Any

from alture_jarvis import interim_news
from alture_jarvis.delegation import STATUS_TOOL, _progress_block, localized_tool, summarize_job
from alture_jarvis.interim_news import news_line
from alture_jarvis.live_progress import LiveProgress
from alture_jarvis.models import EventRecord

_GITHUB_BODY = (
    "Skip to content\nNavigation Menu\nahujasid\n/\nblender-mcp\nPublic\nNotifications\nFork 1.6k\nStar 14.2k\n"
    "Code Issues 92 Pull requests 40\nmain\nbranches tags\nGo to file\n"
    "About\nBlender MCP — connect Claude to Blender\n14.2k stars\n96 watching\n1.6k forks\nMIT license\n"
    + "README.md\nBlenderMCP connects Blender to Claude AI through the Model Context Protocol. " * 8
)


def _read(url: str, title: str, text: str, *, tool: str = "browser_extract", ok: bool = True) -> dict[str, Any]:
    return {"ok": ok, "tool": tool, "result": {"action": "extracted", "url": url, "title": title, "text": text,
                                                "char_count": len(text)}}


# --- 1. 숫자는 읽은 본문에 있는 것만 ---------------------------------------------------

def test_a_github_repo_read_becomes_a_line_with_its_real_numbers() -> None:
    line = news_line("browser_extract", _read("https://github.com/ahujasid/blender-mcp",
                                              "GitHub - ahujasid/blender-mcp: Blender MCP", _GITHUB_BODY), step=7)

    assert line == {"text": "ahujasid/blender-mcp — 별 14.2k · MIT", "url": "https://github.com/ahujasid/blender-mcp",
                    "step": 7, "facts": 2}


def test_a_value_not_in_the_body_is_dropped_but_the_rest_stays(monkeypatch) -> None:
    """반례: 값 조각이 본문에 없는 숫자를 들고 오면(레시피가 틀렸거나 다른 페이지 값) 그 조각만 빠진다."""
    monkeypatch.setattr(interim_news, "_facts", lambda url, body, cells: ["별 99.9k", "별 14.2k", "MIT"])

    line = news_line("browser_extract", _read("https://github.com/ahujasid/blender-mcp",
                                              "GitHub - ahujasid/blender-mcp: Blender MCP", _GITHUB_BODY))

    assert line["text"] == "ahujasid/blender-mcp — 별 14.2k · MIT"
    assert "99.9" not in line["text"]


def test_a_made_up_price_never_reaches_the_line(monkeypatch) -> None:
    body = "상품 상세\n" + "이 책은 파이썬 입문서입니다. 판매가 16,200원 정가 18,000원. " * 10
    monkeypatch.setattr(interim_news, "_facts", lambda url, body, cells: ["판매가 15,900원", "정가 18,000원"])

    line = news_line("browser_read", _read("https://product.kyobobook.co.kr/detail/S000001", "혼자 공부하는 파이썬 | 교보문고", body))

    assert line["text"] == "혼자 공부하는 파이썬 — 정가 18,000원"


def test_a_name_with_a_number_nobody_read_drops_the_whole_line(monkeypatch) -> None:
    monkeypatch.setattr(interim_news, "_name", lambda title, url: "리포 2731")

    assert news_line("browser_extract", _read("https://github.com/a/b", "GitHub - a/b: x", _GITHUB_BODY)) is None


def test_several_licenses_are_not_cut_to_one() -> None:
    """실물 대조(11-14): rust-lang/rust 는 「Apache-2.0 and 2 other licenses found」인데 「MIT」 하나로 나왔다 — 반만 맞는 말."""
    body = "Readme\nApache-2.0 and 2 other licenses found\n121.9k stars\nCode\nApache-2.0 license\nMIT license\n" + "x " * 300
    line = news_line("browser_extract", _read("https://github.com/rust-lang/rust", "GitHub - rust-lang/rust: Empowering everyone", body))

    assert line["text"] == "rust-lang/rust — 별 121.9k · Apache-2.0 외 2"


def test_stars_are_only_read_on_a_repo_page_not_on_a_list() -> None:
    """목록(토픽 · 검색) 화면의 「12.5k stars」는 어느 저장소 것인지 모른다 — 붙이지 않는다."""
    line = news_line("browser_extract", _read("https://github.com/topics/mcp", "mcp · GitHub Topics · GitHub", _GITHUB_BODY))

    assert line is not None and "별" not in line["text"]


# --- 2. 한 항목을 읽어 확인한 걸음만 ---------------------------------------------------

def test_only_a_successful_read_of_one_item_is_news() -> None:
    page = ("https://github.com/ahujasid/blender-mcp", "GitHub - ahujasid/blender-mcp: x", _GITHUB_BODY)
    assert news_line("browser_open", _read(*page, tool="browser_open")) is None
    assert news_line("browser_extract", _read(*page, ok=False)) is None
    assert news_line("browser_extract", _read("https://www.google.com/search?q=blender+mcp", "blender mcp - Google 검색", _GITHUB_BODY)) is None
    assert news_line("browser_extract", _read("https://github.com/search?q=mcp&type=repositories", "Repository search results", _GITHUB_BODY)) is None
    assert news_line("browser_extract", _read("https://nid.naver.com/nidlogin.login", "네이버 : 로그인", _GITHUB_BODY)) is None
    assert news_line("browser_extract", _read("https://example.com/a", "404 Not Found", _GITHUB_BODY)) is None
    assert news_line("browser_extract", _read("https://example.com/a", "짧은 화면", "로딩 중")) is None
    assert news_line("browser_extract", _read("file:///C:/a.txt", "a.txt", _GITHUB_BODY)) is None


def test_the_site_name_is_cut_from_an_ordinary_title() -> None:
    line = news_line("browser_extract", _read("https://www.yes24.com/product/goods/119293186",
                                              "Do it! 점프 투 파이썬 | 박응용 | 이지스퍼블리싱 - 예스24", "책 소개 " * 100))

    assert line["text"] == "Do it! 점프 투 파이썬 | 박응용"


def test_a_broken_observation_never_raises() -> None:
    assert news_line("browser_extract", {"ok": True, "result": None}) is None
    assert news_line("browser_extract", {"ok": True, "result": {"url": 3, "title": object(), "char_count": "x"}}) is None


# --- 3. 진행 저장소 · 호스트 요약 -------------------------------------------------------

def _news(job: str, n: int, url: str = "") -> EventRecord:
    return EventRecord(seq=n, event="agent_interim_news", timestamp=1_000.0 + n,
                       payload={"job_id": job, "text": f"항목 {n} — 별 1{n}.5k", "url": url or f"https://github.com/o/r{n}", "step": n})


def test_the_live_store_keeps_news_once_per_url_and_bounded() -> None:
    live = LiveProgress()
    for n in range(20):
        live.on_event(_news("j", n))
    live.on_event(_news("j", 99, url="https://github.com/o/r19"))  # 같은 주소를 다시 읽음 — 소식 아님

    snap = live.snapshot("j")

    assert len(snap["news"]) == 12 and snap["news_count"] == 20
    assert snap["news"][-1]["url"] == "https://github.com/o/r19"


def test_the_host_gets_only_the_latest_three_short_lines() -> None:
    live = {"doing": "읽는 중", "news_count": 7, "news": [
        {"text": "가" * 300, "url": "https://example.com/" + "a" * 400, "step": 1},
        *[{"text": f"항목 {n}", "url": f"https://example.com/{n}", "step": n} for n in range(2, 8)],
    ]}

    block = _progress_block(live)

    assert [item["text"] for item in block["news"]] == ["항목 5", "항목 6", "항목 7"]
    assert block["news_count"] == 7
    long = _progress_block({"news": [{"text": "가" * 300, "url": "https://example.com/" + "a" * 400}]})["news"][0]
    assert len(long["text"]) <= 90 and len(long["url"]) <= 160


def test_news_rides_only_while_running_and_the_final_answer_wins() -> None:
    live = {"doing": "읽는 중", "step": 5, "news": [{"text": "ahujasid/blender-mcp — 별 14.2k · MIT", "url": "https://github.com/ahujasid/blender-mcp"}]}

    running = summarize_job({"id": "j", "status": "running", "result": None}, live=live)
    queued = summarize_job({"id": "j", "status": "queued", "result": None}, live=live)
    done = summarize_job({"id": "j", "status": "completed", "result": {
        "answer": "최종 답", "completion_state": "complete",
        "agent_trace": {"steps": [], "tool_numbers": [], "tool_numbers_body": []}}}, live=live)

    assert running["progress"]["news"][0]["text"].startswith("ahujasid/blender-mcp")
    assert "progress" not in queued
    assert "progress" not in done and "news" not in str(done)
    assert done["answer"] == "최종 답"


# --- 4. 배선 · 안내 ------------------------------------------------------------------

def test_the_agent_publishes_news_from_every_recorded_read() -> None:
    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent._record_observation)
    assert "self._publish_interim_news(job_id, name, read_as_is, step_number)" in source

    published: list[tuple[str, dict[str, Any]]] = []

    class _Events:
        def publish(self, event: str, payload: dict[str, Any]) -> None:
            published.append((event, payload))

    agent = object.__new__(BrowserAgent)
    agent.events = _Events()
    agent._publish_interim_news("j", "browser_extract", _read("https://github.com/ahujasid/blender-mcp",
                                                               "GitHub - ahujasid/blender-mcp: x", _GITHUB_BODY), 4)
    agent._publish_interim_news("j", "browser_open", _read("https://github.com/a/b", "GitHub - a/b: x", _GITHUB_BODY), 5)

    assert published == [("agent_interim_news", {"job_id": "j", "text": "ahujasid/blender-mcp — 별 14.2k · MIT",
                                                  "url": "https://github.com/ahujasid/blender-mcp", "step": 4, "facts": 2})]


def test_the_host_is_told_to_relay_it_once_and_say_it_is_interim() -> None:
    ko = STATUS_TOOL["description"]
    en = localized_tool(STATUS_TOOL, "en")["description"]

    assert "progress.news" in ko and "한 번만" in ko and "최종 답과 다를 수 있다" in ko
    assert "progress.news" in en and "once" in en and "final answer may differ" in en


def test_what_the_replay_of_real_runs_caught_stays_out() -> None:
    """운영 기록 재생(11-14)에서 사람 눈으로 걸린 셋 — 봇 확인 화면 · 깃허브 목록 화면 · 같은 이름 두 번."""
    body = "본문 " * 200
    assert news_line("browser_extract", _read("https://item.gmarket.co.kr/Item?goodscode=1", "잠시만 기다리십시오…", body)) is None
    assert news_line("browser_extract", _read("https://github.com/rust-lang/rust/pulls", "Pull requests · rust-lang/rust", body)) is None
    assert news_line("browser_extract", _read("https://github.com/BurntSushi/ripgrep/releases", "Releases · BurntSushi/ripgrep", body)) is None
    assert news_line("browser_extract", _read("https://github.com/BurntSushi/ripgrep/releases/tag/15.1.0",
                                              "Release 15.1.0 · BurntSushi/ripgrep", "15.1.0 " + body)) is not None
    assert news_line("browser_extract", _read("https://ko.wikipedia.org/wiki/x", "올림픽 - 위키백과, 우리 모두의 백과사전", body))["text"] == "올림픽"
    gmarket = news_line("browser_extract", _read("https://item.gmarket.co.kr/Item?goodscode=4", "G마켓 - 닌텐도 스위치2 게임기 본체 단품", body))
    assert gmarket["text"] == "닌텐도 스위치2 게임기 본체 단품"
    # 상세 페이지가 검색어 칸을 달고 와도 한 항목이다(재생: 사람인 공고 다섯이 전부 빠졌다).
    assert news_line("browser_extract", _read("https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=51000000&searchword=x",
                                              "[동아출판] 인턴 사원 모집 | 사람인", body)) is not None

    live = LiveProgress()
    for n, url in enumerate(("https://a.example/1", "https://a.example/2")):
        live.on_event(EventRecord(seq=n, event="agent_interim_news", timestamp=1.0,
                                  payload={"job_id": "j", "text": "같은 상품", "url": url, "step": n}))
    assert len(live.snapshot("j")["news"]) == 1
