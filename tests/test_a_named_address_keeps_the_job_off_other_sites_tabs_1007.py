"""요청이 주소를 적어 줬으면, 그 판이 시작하기 전부터 열려 있던 **다른 사이트의 탭**으로 넘어가지 않는다 (2026-10-07 폼 벤치 과제 J).

요청은 「http://…/resume/basic 에서 연락처와 주소를 고치고 저장해줘」였다. 모델은 탭 목록부터 봤고, 사람이 전에 쓰던
실제 사이트의 이력서 수정 탭이 있자 그 탭으로 넘어갔다. 그 화면이 로그인 화면이라 사람 확인 문에서 멈췄다 —
로그인이 살아 있었다면 요청이 가리키지 않은 사이트의 폼을 고칠 뻔했다. 다음 판은 그 탭이 앞에 있어, 탭 목록만 보고도
0걸음에 「사람 확인 대기」로 멈췄다.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import agent as agent_module
from alture_jarvis.browser import BrowserWorker, _site_of_url
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

ASKED = "http://127.0.0.2:8765/resume/basic 에서 비상 연락처의 연락처를 010-0000-0303 으로 고치고 저장을 눌러줘."
MOCK_HOME = "http://127.0.0.2:8765/mypage"
OTHER_SITE = "https://www.jobs.example.co.kr/User/Resume/Edit?no=1"


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return ""


class _Context:
    def __init__(self, pages: list[_Page]) -> None:
        self.pages = pages


def _worker(tmp_path: Path, pages: list[_Page]) -> BrowserWorker:
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    worker._context = _Context(pages)
    worker._page = pages[0]
    worker._maximize_window = lambda page: None  # type: ignore[method-assign]
    worker._bring_to_front = lambda page: None  # type: ignore[method-assign]
    worker._evidence = lambda action, **fields: {"action": action, **fields}  # type: ignore[method-assign]
    return worker


def test_a_tab_of_another_site_that_was_already_open_is_refused(tmp_path: Path) -> None:
    here, other = _Page("about:blank"), _Page(OTHER_SITE)
    worker = _worker(tmp_path, [here, other])
    worker.set_named_addresses(ASKED)

    with pytest.raises(ValueError) as refused:
        worker._switch_tab(None, {"index": 1})

    said = str(refused.value)
    assert said.startswith("tab_is_another_site")
    assert "http://127.0.0.2:8765/resume/basic" in said and "example.co.kr" in said and "browser_open" in said
    assert worker._page is here, "탭은 그대로다"


def test_a_tab_of_the_named_site_is_still_reachable(tmp_path: Path) -> None:
    here, same = _Page("about:blank"), _Page(MOCK_HOME)
    worker = _worker(tmp_path, [here, same])
    worker.set_named_addresses(ASKED)

    assert worker._switch_tab(None, {"index": 1})["action"] == "tab_switched"
    assert worker._page is same


def test_a_tab_this_job_opened_is_reachable_even_on_another_site(tmp_path: Path) -> None:
    """누른 링크가 새 창으로 다른 사이트를 띄우는 것은 이 판이 한 일이다 — 막지 않는다."""
    here = _Page(MOCK_HOME)
    worker = _worker(tmp_path, [here])
    worker.set_named_addresses(ASKED)
    popup = _Page("https://pay.example.com/checkout")
    worker._context.pages.append(popup)

    assert worker._switch_tab(None, {"index": 1})["action"] == "tab_switched"


def test_a_request_without_an_address_changes_nothing(tmp_path: Path) -> None:
    here, other = _Page("about:blank"), _Page(OTHER_SITE)
    worker = _worker(tmp_path, [here, other])
    assert worker.set_named_addresses("지금 열려 있는 이력서 수정 탭에서 연락처를 고쳐줘") == ()

    assert worker._switch_tab(None, {"index": 1})["action"] == "tab_switched"


def test_the_next_job_starts_clean(tmp_path: Path) -> None:
    here, other = _Page("about:blank"), _Page(OTHER_SITE)
    worker = _worker(tmp_path, [here, other])
    worker.set_named_addresses(ASKED)

    worker.forget_results()

    assert worker._switch_tab(None, {"index": 1})["action"] == "tab_switched"


def test_pages_that_are_not_websites_are_never_another_site(tmp_path: Path) -> None:
    here, blank, newtab = _Page(MOCK_HOME), _Page("about:blank"), _Page("chrome://newtab/")
    worker = _worker(tmp_path, [here, blank, newtab])
    worker.set_named_addresses(ASKED)

    assert worker._switch_tab(None, {"index": 1})["action"] == "tab_switched"
    assert worker._switch_tab(None, {"index": 2})["action"] == "tab_switched"


def test_hands_are_refused_on_another_sites_screen_that_was_already_in_front(tmp_path: Path) -> None:
    """탭을 바꾸지 않아도 된다 — 판이 시작할 때 그 화면이 이미 앞에 있으면 곧바로 채우고 누를 수 있었다."""
    front = _Page(OTHER_SITE)
    worker = _worker(tmp_path, [front])
    worker.set_named_addresses(ASKED)

    for hand in ("browser_fill", "browser_click", "browser_fill_form", "browser_press", "browser_file_upload"):
        with pytest.raises(ValueError) as refused:
            worker._refuse_hand_on_another_site(hand, front)
        assert str(refused.value).startswith("screen_is_another_site") and "browser_open" in str(refused.value)
    for reading in ("browser_snapshot", "browser_read", "browser_find", "browser_tabs", "browser_open"):
        worker._refuse_hand_on_another_site(reading, front)        # 읽기와 열기는 그대로다


def test_once_the_job_opens_an_address_in_a_tab_that_tab_is_its_own(tmp_path: Path) -> None:
    """전부터 있던 탭에 요청한 주소를 열었다. 거기서 링크를 타고 다른 사이트로 넘어가는 것은 이 판이 한 일이다."""
    tab = _Page(OTHER_SITE)
    worker = _worker(tmp_path, [tab])
    worker.set_named_addresses(ASKED)

    tab.url = "http://127.0.0.2:8765/resume/basic"
    worker._note_job_navigated("browser_open")
    tab.url = "https://pay.example.com/checkout"

    worker._refuse_hand_on_another_site("browser_click", tab)       # 거절하지 않는다


def test_a_site_the_request_mentions_in_words_is_not_another_site(tmp_path: Path) -> None:
    front = _Page(OTHER_SITE)
    worker = _worker(tmp_path, [front])
    worker.set_named_addresses("https://docs.example.org/prices 의 가격을 지금 열려 있는 jobs.example.co.kr 화면의 메모 칸에 적어줘")

    worker._refuse_hand_on_another_site("browser_fill", front)


def test_the_refusals_do_not_photograph_the_other_sites_screen() -> None:
    from alture_jarvis.browser import _NO_EVIDENCE_ERRORS, _SCREEN_HANDS

    assert "tab_is_another_site" in _NO_EVIDENCE_ERRORS and "screen_is_another_site" in _NO_EVIDENCE_ERRORS
    assert {"browser_fill", "browser_click", "browser_click_confirmed", "browser_fill_form", "browser_select_option",
            "browser_file_upload", "browser_pick_suggestion", "browser_press", "browser_click_at", "browser_type_at"} == set(_SCREEN_HANDS)


def test_the_dispatcher_asks_before_every_hand_and_notes_every_navigation() -> None:
    source = inspect.getsource(BrowserWorker._execute_once)
    asks = source.index("self._refuse_hand_on_another_site(action, page)")
    runs = source.index("result = handler(page, arguments)")
    notes = source.index("self._note_job_navigated(action)")
    assert asks < runs < notes


def test_what_counts_as_the_same_site() -> None:
    assert _site_of_url("https://search.shop.example.co.kr/a") == _site_of_url("https://www.shop.example.co.kr/b") == "example.co.kr"
    assert _site_of_url("http://127.0.0.2:8765/resume/basic") == _site_of_url("http://127.0.0.2:9000/") == "127.0.0.2"
    assert _site_of_url("http://localhost:3000/") == "localhost"
    assert _site_of_url("about:blank") == _site_of_url("chrome://newtab/") == _site_of_url("") == ""


def test_an_address_glued_to_a_korean_particle_is_still_read(tmp_path: Path) -> None:
    worker = _worker(tmp_path, [_Page("about:blank")])

    assert worker.set_named_addresses("http://127.0.0.2:8765/resume/basic에서 고쳐줘. (https://docs.example.com/guide) 도 참고해.") == (
        "http://127.0.0.2:8765/resume/basic", "https://docs.example.com/guide",
    )


class _Tools:
    names = {"browser_search", "browser_read"}
    ollama_tools = [{"type": "function", "function": {"name": "browser_search", "description": "search",
                                                       "parameters": {"type": "object", "properties": {}}}}]


class _Gateway:
    def execute(self, name: str, arguments: dict[str, Any], *, job_id: str = "") -> ToolResult:
        return ToolResult(True, name, result={"url": "https://example.test/result", "title": "결과", "text": "근거"})


class _Browser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def status(self) -> dict[str, Any]:
        return {"started": True}

    def forget_results(self) -> None:
        self.calls.append(("forget_results", ""))

    def set_named_addresses(self, prompt: str) -> tuple[str, ...]:
        self.calls.append(("set_named_addresses", prompt))
        return ()


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {"role": "assistant", "content": "",
                    "tool_calls": [{"function": {"name": "browser_search", "arguments": {"query": "x"}}}]}
        return {"role": "assistant", "content": "확인한 근거를 바탕으로 답변합니다."}


def test_a_new_job_hands_its_request_to_the_browser_after_clearing_the_last_one(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    browser = _Browser()
    runner = agent_module.BrowserAgent(config, _Model(), _Gateway(), browser, _Tools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": ASKED})
    store.claim_next()

    runner.run(ASKED, job_id=job["id"], origin="chat")

    assert browser.calls[:2] == [("forget_results", ""), ("set_named_addresses", ASKED)], "지운 뒤에 적는다 — 순서가 바뀌면 방금 적은 것이 지워진다"


def test_listing_tabs_is_not_treated_as_standing_on_that_screen() -> None:
    """탭 목록만 본 걸음에서, 앞에 떠 있던 다른 사이트의 로그인 화면을 이 판의 문으로 읽지 않는다."""
    source = inspect.getsource(agent_module.BrowserAgent._record_observation)
    assert 'if self.attention is not None and name != "browser_tabs":' in source
