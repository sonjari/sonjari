"""2026-10-03 영어 벤치 셋(GitHub 트렌딩 · arXiv · python 3.13)에서 나온 것."""

from __future__ import annotations

import inspect

from alture_jarvis import agent, plan, ui_i18n

GITHUB = ("Open github.com/trending/python?since=daily in Chrome, read the top 3 trending Python repositories, "
          "and save a markdown file named gh_trending_top3.md with a table of repository name, stars today, "
          "total stars, and the one-line description for each.")

WROTE_TABLE = {
    "tool": "local_write_document", "ok": True,
    "arguments": {"path": "gh.md", "blocks": [
        {"type": "heading", "level": 1, "text": "GitHub Trending"},
        {"type": "table", "rows": [["Repository", "Stars Today"], ["a/b", "696"], ["c/d", "39"], ["e/f", "16"]]},
    ]},
}


def test_a_list_task_counts_the_rows_it_wrote_into_the_file() -> None:
    """목록이 답인 판은 파일 표에 세 줄을 썼으면 충족이다 — 답에 「저장했다」만 적었어도."""
    reqs = plan.extract(GITHUB)
    count = next(req for req in reqs if req.kind == "count")
    assert not count.grounding_required  # 「with a table」 — 목록이 답
    results = plan.check(reqs, sources=["https://github.com/trending/python"], steps=[WROTE_TABLE],
                         answer="The file is saved.")
    ok, saw = next((ok, saw) for req, ok, saw in results if req.kind == "count")
    assert ok, saw
    assert saw == "1개 읽음 · 파일 표에 3줄"
    assert plan.display_saw(saw, "en") == "1 read · 3 rows in the file"


def test_a_grounded_count_is_not_satisfied_by_rows_in_a_file() -> None:
    """상세를 읽어야 하는 요구는 파일 표로 대신할 수 없다 — 읽은 수가 조건이다."""
    req = plan.Requirement("count", "3개 이상 직접 열어 읽기", 3, grounding_required=True)
    (_, ok, saw), = plan.check([req], sources=["https://a.example/1"], steps=[WROTE_TABLE], answer="")
    assert not ok and "파일 표" not in saw


def test_a_failed_write_does_not_count() -> None:
    assert plan._rows_written([{**WROTE_TABLE, "ok": False}]) == 0
    assert plan._rows_written([{"tool": "local_write_document", "ok": True,
                                "arguments": {"path": "a.xlsx", "sheets": {"s": [["h"], [1], [2]]}}}]) == 2


def test_the_checklist_saw_column_is_english_for_an_english_request() -> None:
    """MCP 결과는 화면 번역을 안 거친다 — 「1개 존재·열기 확인」이 바깥 AI 에게 그대로 갔다."""
    assert plan.display_saw("1개 존재·열기 확인", "en") == "1 confirmed to exist and open"
    assert plan.display_saw("1개 존재·열기 확인", "ko") == "1개 존재·열기 확인"


def test_a_specific_template_beats_one_with_more_blanks(tmp_path) -> None:
    """빈칸 둘짜리 「{0} {1}개 이상 직접 열어 읽기」가 「웹 자료 {0}개 …」를 앞질러 「자료 3 웹」이 됐다."""
    ui_i18n.reload()
    ui_i18n.configure(tmp_path / "lang.json")
    try:
        ui_i18n.set_lang("en")
        assert ui_i18n.translate_text("웹 자료 3개 이상 직접 열어 읽기") == "Open and read at least 3 web sources directly"
    finally:
        ui_i18n.configure(tmp_path / "lang_reset.json")
        ui_i18n.reload()


def test_an_english_request_asks_for_an_english_reply_at_the_end_too() -> None:
    """맨 앞 한 줄만으로는 파일은 영어·채팅 답은 한국어였다(python 3.13 판). 맨 끝 목표 칸에도 적는다."""
    source = inspect.getsource(agent)
    assert "write the final reply to the user in English" in source
    assert '"현재 사용자 목표:\\n"' in source


def _grounding(answer: str, read_urls: list[str]) -> str:
    cls = next(c for c in vars(agent).values() if isinstance(c, type) and hasattr(c, "_listed_entity_grounding_check"))
    ledger = [{"type": "body_read", "ok": True, "source_id": url} for url in read_urls]
    body = "Pi 1.0 released today. Shimano Bicycle Museum Review. Several vulnerabilities in the Linux kernel."
    messages = [{"role": "user", "content": "top 3 stories"}, {"role": "tool", "tool_name": "browser_extract", "content": body}]
    return cls._listed_entity_grounding_check(answer, messages, ledger=ledger)


# 실제 답(107f2da1)과 같은 모양 — 숫자 칸 뒤의 주소 칸이 「이름」으로 뽑혔다(`| 34 | https://inrng.com |`).
HN_TABLE = ("| # | Title | Points | Comments | URL |\n| --- | --- | --- | --- | --- |\n"
            "| 1 | Pi 1.0 | 1457 | 479 | https://earendil.com |\n"
            "| 2 | Shimano Bicycle Museum Review | 180 | 34 | https://inrng.com |\n"
            "| 3 | Several vulnerabilities in the Linux kernel | 397 | 288 | https://lwn.net |\n")


def test_a_domain_only_cell_counts_as_read_when_that_site_was_read() -> None:
    """해커뉴스 판: 기사 주소를 읽고 표에는 도메인만 적었다 — 헛경고였다."""
    read = ["https://earendil.com/posts/pi-1-0", "https://inrng.com/2026/10/shimano-bicycle-museum",
            "https://lwn.net/Articles/1"]
    assert _grounding(HN_TABLE, read) == ""


def test_a_domain_cell_for_a_site_never_read_still_warns() -> None:
    """반대쪽: 그 사이트를 안 읽었으면 도메인 칸도 여전히 경고 대상이다."""
    warning = _grounding(HN_TABLE.replace("https://inrng.com", "https://never-read.example"),
                         ["https://earendil.com/posts/pi-1-0", "https://lwn.net/Articles/1"])
    assert "never-read.example" in warning


def test_signing_up_to_try_an_app_does_not_pull_in_the_conversion_skill() -> None:
    """10-02 밤: 「회원가입하고 로그인 되는지 확인」에 가입 전환 최적화(signup) 스킬이 붙었다."""
    from alture_jarvis import skills

    picked = [name for name, _ in skills.match_skills("localhost:5173 앱에서 회원가입하고 로그인 되는지 확인해줘")]
    assert "signup" not in picked
    picked = [name for name, _ in skills.match_skills("우리 서비스 회원가입 전환율을 높이게 가입 전환 흐름을 분석해서 개선안 만들어줘")]
    assert "signup" in picked


# ── 10-03 「드라이브에 새 시트 만들어 내 레딧 글들 반응 정리」 판(155bd3e1) ─────────────────────────


def test_my_posts_plural_means_all_of_them() -> None:
    assert plan.asks_for_everything("구글 드라이브에 새 스프레드시트 하나 만들어서, 내 레딧 글들 추천 수랑 댓글 수를 표로 정리해줘")
    assert plan.asks_for_everything("summarize my reddit posts")
    for not_all in ("내 글 하나만 읽어줘", "이 글들 요약해줘", "내일 글들 써줘", "open my post"):
        assert not plan.asks_for_everything(not_all), not_all


def test_the_artifact_stage_keeps_the_hand_for_an_action_still_owed() -> None:
    """파일만 받던 차례가 「드라이브에 올리기」 손을 안 줘서 한 번도 못 올렸다."""
    tools = [{"function": {"name": n}} for n in ("browser_open", "local_write_document", "google_drive_write")]
    upload = plan.Requirement("action", "드라이브에 올리기", "google_drive_write")
    owed = agent._unmet_action_tools([(upload, False, "실행 안 됨")])
    # 2026-10-04: 끝 도구만 넣으면 그 앞 걸음(준비)이 차례 문에 막힌다 — 사슬을 통째로 넣는다.
    assert owed == {"google_drive_prepare_write", "google_drive_write"}
    names = [t["function"]["name"] for t in agent._focused_tool_definitions(tools, "artifact", also=owed)]
    assert names == ["local_write_document", "google_drive_write"]
    assert agent._unmet_action_tools([(upload, True, "완료")]) == frozenset()


def test_a_fresh_page_is_still_readable_in_the_artifact_stage_of_an_everything_run() -> None:
    """첫 글 .json 을 되읽어 차례에 들어간 뒤, 아직 안 연 둘째 글을 네 번 거절당했다. 되열기는 그대로 막는다."""
    first = "https://www.reddit.com/r/ollama/comments/1/a.json"
    second = "https://www.reddit.com/r/AI_Agents/comments/2/b.json"
    steps = [{"tool": "browser_open", "ok": True, "arguments": {"url": first}},
             {"tool": "browser_read", "ok": True, "arguments": {}}]
    assert agent._fresh_read_for_everything("browser_open", {"url": second}, steps)
    assert not agent._fresh_read_for_everything("browser_open", {"url": first + "/"}, steps)
    assert not agent._fresh_read_for_everything("browser_read", {}, steps)  # 되읽기
    opened = steps + [{"tool": "browser_open", "ok": True, "arguments": {"url": second}}]
    assert agent._fresh_read_for_everything("browser_read", {}, opened)  # 방금 처음 연 쪽 읽기 한 번


def test_the_wrap_up_order_is_marked_as_ours_not_the_users() -> None:
    """「파일이 아니라 채팅으로 완결해라」를 사용자 말로 읽고 「채팅으로 완결하라고 하셨으므로 업로드 안 함」."""
    source = inspect.getsource(agent)
    assert '"[시스템] 더 진행하지 않고 여기서 정리한다. "' in source
    assert "이 정리 지시는 손자리 내부 규칙이지 사용자의 말이 아니다" in source


def test_reddit_post_stats_come_from_the_json_the_tool_reads_itself() -> None:
    """레딧 투표 숫자는 화면 추출에 안 잡혀 모델이 다섯 걸음을 헤맸다 — 도구가 같은 세션으로 .json 을 읽어 붙인다."""
    from alture_jarvis.browser import BrowserWorker, reddit_post_json_url, reddit_post_stats

    post = "https://www.reddit.com/r/ollama/comments/1wskysi/i_went_back_through_15_runs_from_my_local_agent/"
    assert reddit_post_json_url(post) == "https://www.reddit.com/r/ollama/comments/1wskysi.json"
    # 10-03 밤: `.json` 을 직접 연 판도 같은 요약을 받는다(22시 예약 판 5fa9b74c 는 이 규칙 때문에 원문 2만 자에서 잘렸다).
    assert reddit_post_json_url(post.rstrip("/") + ".json") == "https://www.reddit.com/r/ollama/comments/1wskysi.json"
    assert reddit_post_json_url("https://www.reddit.com/r/ollama/comments/1wskysi.json") == "https://www.reddit.com/r/ollama/comments/1wskysi.json"
    assert reddit_post_json_url("https://www.reddit.com/user/someone/submitted/") == ""
    assert reddit_post_json_url("https://example.com/r/x/comments/abc/") == ""
    payload = [{"data": {"children": [{"data": {"score": 4, "num_comments": 2, "upvote_ratio": 1.0}}]}}]
    assert reddit_post_stats(payload) == {"score": 4, "num_comments": 2, "upvote_ratio": 1.0}
    assert reddit_post_stats({"error": 403}) == {}

    class Response:
        ok = True

        def json(self):
            return payload

    class Page:
        url = post

        class context:
            class request:
                @staticmethod
                def get(url, **_):
                    assert url.endswith(".json")
                    return Response()

    attach = BrowserWorker._attach_post_stats
    out = attach(None, Page(), {"ok": True, "url": post, "text": "본문"})
    assert out["text"].startswith("[레딧 글 수치] 점수(추천) 4 · 댓글 2")
    assert out["post_stats"]["num_comments"] == 2
    untouched = {"ok": True, "url": "https://example.com/a", "text": "본문"}
    assert attach(None, Page(), untouched) is untouched


def test_a_short_date_in_a_table_cell_is_a_date_not_a_decimal() -> None:
    """K-Startup 5차: 원문 「2026.10.06」, 답의 표 칸 「10.06」 — 마감일 다섯이 「근거 없는 숫자」로 찍혔다."""
    from alture_jarvis import evidence

    seen = evidence.numbers_claimed_in("접수기간 2026.10.06 18:00 까지 · 지원금 최대 1억")
    claimed = evidence.numbers_claimed_in("| 공공데이터 활용 | 최대 1억 | 10.06 |")
    assert not evidence.unsupported_numbers(claimed, seen)
    # 가격·비율은 날짜가 아니다 — 지어낸 값이면 그대로 잡힌다.
    assert "10.25" in evidence.unsupported_numbers(evidence.numbers_claimed_in("가격 $10.25"), seen)
    assert evidence.unsupported_numbers(evidence.numbers_claimed_in("평점 4.75점"), seen)


def test_distances_durations_and_party_sizes_are_conditions_not_read_counts() -> None:
    """Online-Mind2Web 영어 과제 300개 중 개수 요구 21개가 거의 다 이런 오독이었다(TED 판이 「12개 읽기」로 5배 걸리고 틀림)."""
    for task in (
        "Find the most viewed TED talk on the topic of robots that lasts between 12 and 18 minutes.",
        "Find roofing contractors within 5 miles of zip code 10002.",
        "Find the cheapest 2 bed and 3+ bath apartment listing for rent in New York.",
        "Check permit availability for a group of 4 in Brooks Camp, Katmai National Park for next Saturday.",
        "Find the top-rated hotel in Manhattan, NY, suitable for 4 guests.",
        'Find the lowest 27"-32" Samsung or LG computer monitors nearby which have 4k, IPS display.',
        "Look for the largest hunting land for auction posted in the last seven days.",
        "Find the most frequent word that rhymes with \"thought\" and has three syllables.",
    ):
        assert not [r for r in plan.extract(task) if r.kind == "count"], task
    # 진짜 읽을 개수는 그대로다(오늘 실제로 돌린 영어 판 문장).
    for task, n in (
        ("Open news.ycombinator.com in Chrome, read the top 3 stories on the front page, and save a markdown file.", 3),
        ("Open arxiv.org/list/cs.CL/new in Chrome, read the first 3 papers in the new submissions list.", 3),
        ("Find three open-source local AI agents on GitHub with at least 5,000 stars.", 3),
    ):
        assert [int(r.target) for r in plan.extract(task) if r.kind == "count"] == [n], task


# ── 10-03 「사이트 정렬·필터로 보기」 칸 (TED 판 · Browser Use 「필터 먼저」를 결정론으로) ──────────────


def test_superlative_and_range_asks_need_the_site_filter() -> None:
    for task in (
        "Find the most viewed TED talk on the topic of robots that lasts between 12 and 18 minutes.",
        "Find discussions of the community and open one with the most replies on Flightaware.",
        "Browse used Audi cars made before 2015 and sort by lowest price on KBB.",
        "다나와에서 무선마우스를 낮은가격순으로 정렬해서 상위 3개 제품명과 가격을 알려줘",
    ):
        assert any(r.kind == "filter" for r in plan.extract(task)), task
    # 모은 것끼리의 비교·상품의 값 칸은 사이트 정렬이 아니다(운영 판 역검증에서 헛걸었던 말).
    for task in (
        "YES24와 교보문고에서 파이썬 도서 3권씩 조사해서 가장 비싼 책을 알려줘",
        "에누리에서 무선마우스 2개의 상품명과 최저가를 알려줘",
        "Read the top 3 stories on Hacker News",
        "이 폴더에서 가장 많이 본 문서가 뭐야",  # 브라우저를 안 쓰면 채움(아래)
    )[:3]:
        assert not any(r.kind == "filter" for r in plan.extract(task)), task


def test_the_filter_box_fills_only_from_a_sorted_page_or_a_sort_click() -> None:
    req = plan.Requirement("filter", "사이트 정렬·필터로 보기", "")

    def judge(steps):
        (_, ok, saw), = plan.check([req], sources=[], steps=steps, answer="")
        return ok, saw

    search = {"tool": "browser_open", "ok": True, "arguments": {}, "evidence": {"url": "https://www.ted.com/search?q=robots&types=talks"}}
    sorted_page = {"tool": "browser_open", "ok": True, "arguments": {},
                   "evidence": {"url": "https://www.ted.com/talks?sort=popular&topics%5B0%5D=robots&duration=12-18"}}
    sort_click = {"tool": "browser_click", "ok": True, "arguments": {"ref": "j4", "expect": {"value": "낮은가격순"}}, "evidence": {}}
    assert judge([search]) == (False, "주소·누른 칸에 정렬·필터 흔적 없음")
    assert judge([search, sorted_page])[0]
    assert judge([search, sort_click])[0]
    assert judge([{"tool": "local_read_document", "ok": True}]) == (True, "브라우저 안 씀")
    assert plan.filtered_url("https://discussions.flightaware.com/top")
    assert not plan.filtered_url("https://www.ted.com/search?q=robots&page=2")
    assert plan.display_saw("주소·누른 칸에 정렬·필터 흔적 없음", "en") == "no sort/filter found in the pages opened or the buttons pressed"


def test_when_the_filter_is_owed_the_next_step_says_so() -> None:
    req = plan.Requirement("filter", "사이트 정렬·필터로 보기", "")
    assert agent._next_plan_step_hint([(req, False, "정렬·필터 안 씀")]) == agent._APPLY_SITE_FILTERS_HINT


def test_the_filter_hint_rides_on_the_first_search_results_not_on_a_late_pushback() -> None:
    """TED 재측정(c2eae406): 칸은 있었는데 28걸음 동안 되받기가 안 걸려 안내가 한 번도 안 갔다 — 방법 칸은 처음에 건다."""
    host = type("Host", (), {})()
    host._filter_owed, host._filter_hints = True, 0
    attach = agent.BrowserAgent._with_filter_first.__get__(host)
    host._FILTER_FIRST_TOOLS = agent.BrowserAgent._FILTER_FIRST_TOOLS
    host._FILTER_FIRST_MAX = agent.BrowserAgent._FILTER_FIRST_MAX
    search = {"ok": True, "url": "https://www.ted.com/search?q=robots"}
    first = attach("browser_open", search, search["url"])
    assert list(first)[0] == "filter_first" and "검색어 결과는 전체가 아니다" in first["filter_first"]
    assert "filter_first" in attach("browser_open_result", dict(search), search["url"])
    assert "filter_first" not in attach("browser_open_result", dict(search), search["url"])  # 두 번까지
    host._filter_hints = 0
    sorted_page = "https://www.ted.com/talks?sort=popular&duration=12-18"
    assert "filter_first" not in attach("browser_open", {"ok": True}, sorted_page)  # 걸었으면 끝
    assert host._filter_owed is False
    assert "filter_first" not in attach("browser_open", dict(search), search["url"])
    host._filter_owed, host._filter_hints = True, 0
    assert "filter_first" not in attach("browser_extract", dict(search), search["url"])  # 읽기 결과엔 안 붙인다


def test_the_filter_box_needs_every_kind_the_request_asked_for() -> None:
    """TED 2차(c2eae406): 「주제=로봇」만 걸고 ✅ — 요청은 「많이 본 순」 정렬과 「12~18분」 범위 둘 다였다."""
    ted = "Find the most viewed TED talk on the topic of robots that lasts between 12 and 18 minutes."
    assert plan.site_filter_needs(ted) == ("sort:popular", "range")
    req = next(r for r in plan.extract(ted) if r.kind == "filter")

    def judge(*urls):
        steps = [{"tool": "browser_open", "ok": True, "arguments": {}, "evidence": {"url": u}} for u in urls]
        (_, ok, saw), = plan.check([req], sources=[], steps=steps, answer="")
        return ok, saw

    assert judge("https://www.ted.com/talks?topics%5B0%5D=robots") == (False, "범위 필터 안 걸림 · 많이 본 순 정렬 안 걸림")
    assert judge("https://www.ted.com/talks?sort=newest&topics%5B0%5D=robots")[0] is False  # 최신순·주제는 많이 본 순·12~18분이 아니다
    assert judge("https://www.ted.com/talks?sort=popular&topics%5B0%5D=robots&duration=12-18") == (True, "범위 필터 걸림 · 많이 본 순 정렬 걸림")
    assert plan.display_saw("정렬 안 걸림", "ko") == "정렬 안 걸림"
    # 정렬만 필요한 요청은 정렬만 걸면 된다(FlightAware 「most replies」 · 다나와 「낮은가격순」).
    fa = next(r for r in plan.extract("Find discussions and open one with the most replies on Flightaware.") if r.kind == "filter")
    assert fa.target == ("sort:popular",)
    (_, ok, _), = plan.check([fa], sources=[], steps=[{"tool": "browser_open", "ok": True, "arguments": {},
                                                       "evidence": {"url": "https://discussions.flightaware.com/top"}}], answer="")
    assert ok


# ── 10-03 Online-Mind2Web A 판(15개)에서 나온 것 ───────────────────────────────────────────────


def test_an_english_promise_is_not_a_finished_answer() -> None:
    """#7 「Redfin is also blocked. Let me try one more source — rent.com — …」·#11 「… Let me try Expedia's direct URL …」가 complete 로 나갔다."""
    for text in (
        "Redfin is also blocked (Human Verification). Let me try one more source — rent.com — to find any Corning-specific listings.",
        "The form fields aren't persisting my selections. Let me try Expedia's direct package search URL with all parameters instead.",
        "I'll check the official page next.",
    ):
        assert agent._only_a_promise(text), text
    for text in ("Done. I opened Hacker News and saved the file.", "Let me know if you want more.",
                 "I'll be happy to help with anything else.", "If you'd like, I can lock in the stricter answer — just say which."):
        assert not agent._only_a_promise(text), text


def test_filters_applied_by_clicks_and_unknown_query_names_count() -> None:
    """#3 apartments.com 「Rent (low to high)」 클릭·`so=4`, #5 Petfinder `age=young`·`daysOnPetfinder=1 day` — 걸었는데 「안 씀」."""
    cheap = next(r for r in plan.extract("Search for the cheapest apartment in Detroit for a student.") if r.kind == "filter")
    steps = [{"tool": "browser_click", "ok": True, "arguments": {"expect": {"value": "Rent (low to high)"}, "ref": "j15"}, "evidence": {}}]
    assert plan.check([cheap], sources=[], steps=steps, answer="")[0][1]
    cats = next(r for r in plan.extract("Find young cats in Seattle and show off the newest additions.") if r.kind == "filter")
    url = "https://www.petfinder.com/search/cats-for-adoption/us/wa/seattle/?age=young&daysOnPetfinder=1%20day"
    assert plan.check([cats], sources=[], steps=[{"tool": "browser_open", "ok": True, "arguments": {}, "evidence": {"url": url}}], answer="")[0][1]
    # 검색어·쪽·추적값은 필터가 아니다.
    assert plan.url_filter_kinds("https://example.com/search?q=robots&page=2&utm_source=x") == set()
    # 「View details」 같은 클릭은 정렬이 아니다(클릭 기록의 다른 낱말로 방향을 읽지 않는다).
    view = [{"tool": "browser_click", "ok": True, "arguments": {"expect": {"value": "View details"}, "ref": "j3"}, "evidence": {}}]
    ted = next(r for r in plan.extract("Find the most viewed TED talk on robots.") if r.kind == "filter")
    assert not plan.check([ted], sources=[], steps=view, answer="")[0][1]


def test_a_most_recent_listing_question_goes_to_the_agent_not_to_chat() -> None:
    """#12 「Can you play the recap from the most recent NBA game?」을 대화로 보내 「영상은 못 튼다」(도구 0번)."""
    from alture_jarvis import runtime

    source = inspect.getsource(runtime)
    assert 'routed_observation = {"route_reason": "site_listing"}' in source
    assert plan.asks_for_site_filter("Can you play the recap from the most recent NBA game?")


# ── 10-03 Online-Mind2Web B 판(공식 조건 15개)에서 나온 것 ─────────────────────────────────────


def test_an_english_admission_of_failure_is_not_complete() -> None:
    """AdoptAPet·NVIDIA·Apple 판이 「I was unable to complete the task」라고 쓰고도 complete 로 나갔다."""
    for text in ("I have to stop here — I couldn't get into AdoptAPet.", "I was unable to complete the task. Here's what I found",
                 "I've hit a wall on the exact source.", "I could not locate a Statista report titled X."):
        assert agent._ADMITS_NOT_DONE_EN.search(text), text
    for text in ("If you can't find it, try the official page.", "Here are the specs I found on apple.com.",
                 "Users who are unable to log in should reset the password."):
        assert not agent._ADMITS_NOT_DONE_EN.search(text), text
    # 2026-10-08: 자백은 모델의 글(`own_words`)로만 읽는다 — 우리가 붙인 경고는 읽지 않는다.
    assert "_ADMITS_NOT_DONE_EN.search(own_words)" in inspect.getsource(agent)


def test_the_promise_note_follows_the_request_language() -> None:
    assert "continue" in agent._PROMISE_ONLY_NOTE_EN and "Sonjari" in agent._PROMISE_ONLY_NOTE_EN
    assert "_PROMISE_ONLY_NOTE_EN if _english.english_dominant" in inspect.getsource(agent)


def test_sorts_and_filters_in_the_fragment_path_and_click_label_count() -> None:
    """us-appliance `#…sort_method=pageviews…&filter_width.filter=36` · Rotten Tomatoes `/sort:popular` · RE/MAX 클릭 칸 이름."""
    assert plan.url_filter_kinds("https://www.us-appliance.com/refrigeration.html#query=c130&filter_width.filter=36"
                                 "&sort_method=pageviews.filter/desc&page=1") >= {"sort:popular", "range"}
    assert plan.url_filter_kinds("https://www.rottentomatoes.com/browse/tv_series_browse/sort:popular") == {"sort:popular"}
    assert plan.url_filter_kinds("https://example.com/docs#section-2") == set()
    assert agent._step_evidence({"action": "clicked", "element": {"name": "Experience (High to Low)", "tag": "button"}})["label"] \
        == "Experience (High to Low)"
    agent_req = next(r for r in plan.extract("Find the most experienced real estate agent in St Augustine, FL.") if r.kind == "filter")
    click = {"tool": "browser_click", "ok": True, "arguments": {"ref": "j9"}, "evidence": {"label": "Experience (High to Low)"}}
    assert plan.check([agent_req], sources=[], steps=[click], answer="")[0][1]


def test_the_wrap_up_tells_the_model_not_to_talk_about_the_system() -> None:
    """LandWatch 판 답이 「The system is asking me to stop, but …」로 시작했다."""
    assert "\\\"the system\\\"" in inspect.getsource(agent) or '"the system"' in inspect.getsource(agent)


# ── 10-03 B 판 2차(고친 뒤 같은 15개)에서 나온 것 ─────────────────────────────────────────────


def test_english_promises_and_failures_are_caught_by_shape_not_by_a_verb_list() -> None:
    """「Let me type …」·「Let me snapshot …」·「I couldn't expand …」가 동사 목록 밖이라 complete 로 나갔다."""
    for text in ('The location field is j7. Let me type "New York, NY" and pick the suggestion.',
                 "The Age filter opened. Let me snapshot to find the Kitten option.",
                 "Sorted by experience, the top agent is Thomas Dorazil. Let me open his profile page."):
        assert agent._only_a_promise(text), text
    assert not agent._only_a_promise("Here is the list. Let me know if you want more.")
    assert agent._ADMITS_NOT_DONE_EN.search("the dropdowns are custom comboboxes I couldn't expand to confirm the build")
    assert not agent._ADMITS_NOT_DONE_EN.search("Here are the specs from apple.com.")


def test_manipulation_runs_get_a_longer_closing_round() -> None:
    """WebMD 판이 필터 하나·1개 읽음으로 목표 달성이 켜져 위치 입력 도중 3걸음 만에 닫혔다."""
    assert agent._GOAL_MET_CLOSING_STEPS == 3 and agent._GOAL_MET_CLOSING_STEPS_MANIPULATION > 3
    source = inspect.getsource(agent)
    assert 'str(getattr(req, "kind", "")) == "filter" for req in plan or []) else _GOAL_MET_CLOSING_STEPS' in source
    assert "도구를 최대 {closing_steps}번 더" in source


# ── 10-03 A 판 공식 조건(시작 사이트 줌)에서 나온 것 ─────────────────────────────────────────


def test_a_longer_english_promise_is_still_a_promise() -> None:
    """「… so let me verify the sort actually worked by re-checking the Sort button's current state.」(225자)가 complete."""
    text = ("The sort applied (URL ?so=4), and the top listing is Riverfront Towers at $1,316+. But that seems too high for "
            "\"cheapest in Detroit,\" so let me verify the sort actually worked by re-checking the Sort button's current state.")
    assert len(text) > 200 and agent._only_a_promise(text)
    long_answer = "Here is what I found. " * 30 + "Let me know if you want more."
    assert not agent._only_a_promise(long_answer)


def test_a_price_condition_in_the_url_path_is_a_range_filter() -> None:
    """apartments.com `/corning-ca/under-1500/` 를 못 읽어 「필터 흔적 없음」 → 모델이 대조표와 말다툼했다."""
    assert plan.url_filter_kinds("https://www.apartments.com/corning-ca/under-1500/") == {"range"}
    assert plan.url_filter_kinds("https://www.apartments.com/detroit-mi/2-bedrooms/") == {"range"}
    assert plan.url_filter_kinds("https://www.apartments.com/14299-fordham-st-detroit-mi-48205/") == set()


def test_an_english_request_answered_in_korean_is_rewritten_once_in_english() -> None:
    """B 판 3차 IGN: 같은 과제가 2차엔 영어, 3차엔 「찾았습니다. IGN에서 …」 — 안내문만으론 흔들려 결정론으로 한 번 다시 쓴다."""
    source = inspect.getsource(agent)
    assert '"agent_final_language_rewrite"' in source
    # 2026-10-20: 문턱은 `english.needs_english_rewrite` 하나로 모았다(짧은 한국어 답도 잡는다 — 바로 답하는 길과 같은 판정).
    assert "_english.needs_english_rewrite(prompt, answer)" in source
    assert "if english_final and _english.english_dominant" in source  # 다시 쓴 답이 영어일 때만 바꾼다
    korean = "찾았습니다. IGN에서 젤다 워크스루를 확인했습니다. 결과 페이지 주소와 내용은 아래와 같습니다."
    assert len(agent._HANGUL_RE.findall(korean)) >= 20
    assert agent._english.needs_english_rewrite("Find a Zelda walkthrough on IGN", korean)
