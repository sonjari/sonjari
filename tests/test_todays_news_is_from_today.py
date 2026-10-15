"""「오늘 소식」을 물으면 **오늘 것**을 읽는다 — 날짜는 도구가 센다.

★ 2026-09-29 실사용(대표, 새벽 1시): 「오늘자 국내 이슈나ㅓ 뉴스 한번 조사해주라」 → 62초 · 도구 3걸음.
네이버 뉴스 탭을 **관련도순·기간 없이** 검색 → 3위 YTN 대담(`0104_202609171709…`, **09-17 = 12일 전**)을 열어 읽고,
출처·날짜 없이 「오늘의 이슈」로 답했다. 그 기사의 NewsArticle `datePublished` 는 structured_data 로 **이미 모델 앞에**
있었다 — 아무도 날짜를 안 봤다(사고 R — 안내문은 안 먹는다). 같은 판에서 「한번」(말버릇)이 「뉴스 1개」로 세졌다.

실측: 같은 네이버 뉴스 검색의 앞 15건이 기간 없이는 3일~1주 전 기사를 섞었고, `nso=so:r,p:1d` 를 붙이자 전부 18시간 이내였다.
역검증(과거 고유 요청 1,217개): 소식 판정 16개 중 15개가 진짜 「오늘자 뉴스·이슈」 요청 — 대표가 **열다섯 번** 물은 일이다.
"""
from __future__ import annotations

from datetime import date, datetime

from alture_jarvis.agent import BrowserAgent, _stale_for_request, _stale_read_notice
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult
from alture_jarvis.plan import requested_news_recency
from alture_jarvis.structured_data import published_date
from alture_jarvis.task_contract import compile_task_contract

TODAY = date(2026, 9, 29)
PROMPT = "오늘자 국내 이슈나ㅓ 뉴스 한번 조사해주라"


def test_only_news_requests_about_today_are_dated() -> None:
    assert requested_news_recency(PROMPT) == "day"
    assert requested_news_recency("네이버 뉴스에서 오늘 경제 분야 주요 기사 3개를 찾아서") == "day"
    assert requested_news_recency("이번 주 AI 뉴스 정리해줘") == "week"
    # 「오늘」이 「지금 시점」인 말 — 여기에 날짜 경고를 달면 멀쩡한 기술 글을 버리게 만든다(역검증에서 걸러 낸 모양).
    assert requested_news_recency("오늘자 깃허브 최신 기술 설계 트렌드 알아봐주라") == ""
    assert requested_news_recency("오늘자로 지원 가능한 공고 찾아줘") == ""
    assert requested_news_recency("오늘 서울 날씨 알려줘") == ""
    assert requested_news_recency("최근 3년 AI 뉴스") == ""        # 「최근」은 기간이 제각각이라 안 잡는다
    assert requested_news_recency("이번 주 토요일 밀양 숙소") == ""


def test_the_search_url_carries_the_period() -> None:
    naver_news = BrowserWorker._search_url("naver", "국내 주요 뉴스", "news", "day")
    assert "where=news" in naver_news and "nso=so%3Ar%2Cp%3A1d" in naver_news
    assert "p%3A1w" in BrowserWorker._search_url("naver", "q", "news", "week")
    # 네이버는 재 본 뉴스 탭에만 붙인다.
    assert "nso=" not in BrowserWorker._search_url("naver", "q", "all", "day")
    assert BrowserWorker._search_url("google", "q", "all", "day").endswith("&tbs=qdr:d")
    # 기간을 안 주면 예전 주소 그대로.
    assert BrowserWorker._search_url("naver", "q", "news") == (
        "https://search.naver.com/search.naver?query=q&ssc=tab.news.all&where=news&sm=tab_jum"
    )


def test_published_date_is_read_only_from_articles() -> None:
    news = {"items": [{"type": "newsarticle", "fields": [
        "headline: '호르무즈 파병·대미 투자' 한미 현안 결론은?", "datePublished: 2026-09-17T17:09:14+09:00"]}]}
    assert published_date(news) == "2026-09-17"
    assert published_date({"items": [{"type": "blogposting", "fields": ["datePublished: 2026.9.3"]}]}) == "2026-09-03"
    assert published_date({"meta": {"article:published_time": "2026-09-28T22:10:00+09:00"}}) == "2026-09-28"
    # 책의 출간일·채용 공고는 소식의 날짜가 아니다.
    assert published_date({"items": [{"type": "book", "fields": ["datePublished: 2019-06-10"]}]}) == ""
    assert published_date({"items": [{"type": "jobposting", "fields": ["datePublished: 2026-09-01"]}]}) == ""
    assert published_date({}) == ""


def test_a_stale_article_gets_its_date_in_the_result() -> None:
    observation = {"ok": True, "result": {"url": "https://www.ytn.co.kr/_ln/0104_202609171709148846",
                                          "published": "2026-09-17", "instruction": "본문을 읽었다."}}
    marked = _stale_read_notice(observation, "day", TODAY)
    assert marked["result"]["stale_for_request"] == 12
    assert "2026-09-17 게시(12일 전)" in marked["result"]["instruction"]
    assert marked["result"]["instruction"].endswith("본문을 읽었다.")   # 원래 안내는 그대로 뒤에
    # 어제 기사는 「오늘」로 봐준다 — 새벽에는 그게 가장 최신이다.
    assert _stale_for_request("2026-09-28", "day", TODAY) is None
    assert _stale_for_request("2026-09-23", "week", TODAY) is None
    assert _stale_for_request("2026-09-20", "week", TODAY) == 9
    # 날짜를 못 읽은 글은 판정하지 않는다.
    assert _stale_read_notice({"ok": True, "result": {"url": "x"}}, "day", TODAY)["result"] == {"url": "x"}


def test_the_answer_says_the_date_when_what_was_read_is_old() -> None:
    steps = [
        {"ok": True, "tool": "browser_search", "evidence": {"url": "https://search.naver.com/..."}},
        {"ok": True, "tool": "browser_extract", "evidence": {
            "url": "https://www.ytn.co.kr/_ln/0104_202609171709148846", "published": "2026-09-17",
            "title": "'호르무즈 파병·대미 투자' 한미 현안 결론은? [이슈ON] | YTN"}},
    ]
    note = BrowserAgent._stale_read_check(PROMPT, steps, TODAY)
    assert "읽은 글이 전부 오늘 게시가 아닙니다" in note and "2026-09-17 게시(12일 전)" in note
    fresh = steps + [{"ok": True, "tool": "browser_extract",
                      "evidence": {"url": "https://n.news.naver.com/a", "published": "2026-09-29"}}]
    assert "읽은 글 중 일부가" in BrowserAgent._stale_read_check(PROMPT, fresh, TODAY)
    assert BrowserAgent._stale_read_check(PROMPT, steps[:1] + fresh[2:], TODAY) == ""
    # 소식을 안 물었으면 날짜로 말하지 않는다.
    assert BrowserAgent._stale_read_check("호르무즈 파병 쟁점 정리해줘", steps, TODAY) == ""


def test_hanbeon_is_a_habit_not_a_count() -> None:
    def quotes(prompt: str) -> list[str]:
        return [q["quote"] for c in compile_task_contract(prompt).to_dict()["clauses"] for q in c["quantities"]]

    assert quotes(PROMPT) == []
    assert quotes("검색을 한 번 더 해줘") == ["한 번"]
    assert quotes("Submit 버튼을 한 번만 눌러") == ["한 번"]
    assert quotes("승인 뒤 정확히 한 번 실행해") == ["한 번"]   # 역검증에서 빠질 뻔한 유일한 진짜 개수
    assert quotes("기사 3개 읽고 두 번 확인해") == ["3개", "두 번"]


# ---- 판을 통째로 돌려 **배선**을 본다(test_site_first_redirect_is_wired 와 같은 틀) ----

class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names = {"browser_search", "browser_open_result", "browser_extract"}
    ollama_tools = [{"type": "function", "function": {"name": "browser_search", "description": "search",
                                                      "parameters": {"type": "object", "properties": {}}}}]


class _Gateway:
    def __init__(self, published: str) -> None:
        self.published = published
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name, arguments, *, job_id=""):
        self.calls.append((name, dict(arguments)))
        if name == "browser_search":
            return ToolResult(True, name, result={"action": "searched", "url": "https://search.naver.com/x",
                                                   "results": [{"rank": 1, "title": "기사"}], "result_count": 1})
        return ToolResult(True, name, result={"action": "extracted", "url": "https://www.ytn.co.kr/_ln/0104_1",
                                               "title": "대담 기사 | YTN", "text": "본문 " * 200,
                                               "char_count": 1000, "published": self.published})


class _Model:
    """라이브 판이 한 그대로 — 뉴스 탭을 기간 없이 검색하고, 기사 하나를 읽고, 「오늘의 이슈」로 답한다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "browser_search", "arguments": {"query": "오늘 국내 뉴스 주요 이슈", "engine": "naver", "tab": "news"}}}]}
        if self.calls == 2:
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "browser_extract", "arguments": {}}}]}
        return {"role": "assistant", "content": "오늘의 주요 이슈는 호르무즈 파병과 대미 투자입니다."}


def _run(tmp_path, published: str):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _Gateway(published)
    agent = BrowserAgent(config, _Model(), gateway, _Browser(), _Tools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": PROMPT})
    store.claim_next()
    return agent.run(PROMPT, job_id=job["id"], origin="chat"), gateway


def test_the_tool_adds_the_period_and_says_so(tmp_path) -> None:
    result, gateway = _run(tmp_path, "2020-01-01")
    name, arguments = gateway.calls[0]
    assert name == "browser_search" and arguments.get("period") == "day", arguments
    evidence = result.steps[0]["evidence"]
    assert "최근 1일로 좁혔다" in str(evidence.get("instruction") or ""), evidence


def test_an_old_article_is_dated_for_the_model_the_ledger_and_the_reader(tmp_path) -> None:
    result, _ = _run(tmp_path, "2020-01-01")
    read = next(step for step in result.steps if step.get("tool") == "browser_extract")
    assert read["evidence"].get("stale_for_request"), read["evidence"]
    assert "2020-01-01 게시" in str(read["evidence"].get("instruction") or "")
    assert "⚠" in result.answer and "2020-01-01 게시" in result.answer, result.answer


def test_todays_article_is_left_alone(tmp_path) -> None:
    result, _ = _run(tmp_path, datetime.now().date().isoformat())
    read = next(step for step in result.steps if step.get("tool") == "browser_extract")
    assert "stale_for_request" not in read["evidence"]
    assert "게시가 아닙니다" not in result.answer
