"""사람이 같은 크롬 탭을 쓰고 있으면 손자리는 그 화면에서 누르지 않는다 (2026-10-19 · 잡 51f35b07).

대표가 같은 탭에서 깃허브 계정을 더하는 사이에 손자리가 계정 고르기 화면에서 뒤로 가고(→ 이 판이 연 적 없는 로그인 화면),
그다음 사람이 연 `github.com/ollama/ollama` 에서 `j15` 를 눌렀다. 「사람이 만졌다 · 다시 보라」 알림은 붙어 있었다 — 안내문은
안 먹는다. 그래서 문으로 막는다(`BrowserWorker._hold_if_human_on_tab`).

지켜야 할 것(양방향):
- 사람 손이 닿은 뒤 이 판이 연 적 없는 화면이면 누르기 · 쓰기 · 뒤로를 **멈추고** `human_on_tab` 으로 돌려보낸다. 읽기는 알림을 붙여 이어 간다.
- 사람 손이 없으면 바뀐 주소를 받아들인다 — 우리 누르기 뒤 늦게 끝난 이동 · 광고 다리(운영 기록에 100번 넘게 있었다).
- 이 판이 간 로그인 화면에서 사람이 로그인을 마치고 돌아온 화면은 이 판의 화면이다.
- 이 판이 제 주소를 열면(browser_open) 멈춤이 풀린다. 「이어서」(멈춘 판을 잇기)도 푼다.
"""
from __future__ import annotations

import inspect
import re
import time
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import browser as browser_module
from alture_jarvis.browser import (
    _HANDS_ON_THE_PAGE, _LOOKING_HANDS, _OWN_ADDRESS_HANDS, _SCREEN_HANDS, BrowserWorker, _own_key,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.stuck_hands import _stuck_report

GOOGLE_CHOOSER = (
    "https://accounts.google.com/v3/signin/accountchooser?client_id=1078992815106-brpsupgvhheqg35tupphbh0qk9c32nq8"
    ".apps.googleusercontent.com&code_challenge=k3SpV-jjYsCVFZ8UdP1HezCN4zioXs6FDqvR89ZaHLo&nonce=abc123&state=xyz789"
)
GITHUB_LOGIN = "https://github.com/login?add_account=1&return_to=https%3A%2F%2Fgithub.com%2Follama%2Follama"


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url

    def is_closed(self) -> bool:
        return False


def _worker(tmp_path: Path, url: str = "about:blank") -> tuple[BrowserWorker, _Page]:
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    page = _Page(url)
    worker._page = page
    return worker, page


def _step(worker: BrowserWorker, page: _Page, action: str, after: str | None = None, **arguments: Any) -> dict[str, Any]:
    """`_execute_once` 가 손 앞뒤로 하는 일을 그대로 — 문 → (손이 화면을 바꿈) → 이 판이 간 곳 적기 → 알림."""
    worker._hold_if_human_on_tab(action, page)
    started = time.time()
    if after is not None:
        page.url = after
    worker._note_own_page_after(action, arguments, started)
    return worker._with_human_on_tab_note({"ok": True, "url": page.url})


def _person_goes(worker: BrowserWorker, page: _Page, url: str) -> None:
    """사람이 무대에서 크롬을 넘겨받아 다른 화면으로 갔다가 돌려준다."""
    time.sleep(0.002)
    page.url = url
    worker.note_human_hand()
    time.sleep(0.002)


def test_the_incident_stops_at_the_first_hand_on_the_persons_screen(tmp_path: Path) -> None:
    worker, page = _worker(tmp_path)
    _step(worker, page, "browser_open", "https://github.com/sonjari/sonjari", url="https://github.com/sonjari/sonjari")
    _step(worker, page, "browser_find")
    _step(worker, page, "browser_snapshot")
    _step(worker, page, "browser_click", "https://github.com/sonjari/sonjari", ref="j15")

    _person_goes(worker, page, GOOGLE_CHOOSER)  # 대표가 계정을 더하러 감(111.3초)

    looked = _step(worker, page, "browser_snapshot")
    assert "human_on_tab" in looked, "읽기는 이어 가되 사람이 쓰는 화면이라고 알린다"
    assert "code_challenge" not in looked["human_on_tab"], "알림에도 한 번 쓰는 값을 싣지 않는다"

    with pytest.raises(ValueError) as stopped:
        _step(worker, page, "browser_back", GITHUB_LOGIN)
    said = str(stopped.value)
    assert said.startswith("human_on_tab")
    assert "accounts.google.com/v3/signin/accountchooser" in said and "github.com/sonjari/sonjari" in said
    assert "code_challenge" not in said and "nonce" not in said and "state=" not in said
    assert page.url == GOOGLE_CHOOSER, "뒤로 가지 않았다 — 사람의 방문 기록을 따라가지 않는다"

    # 판이 그 자리에서 다른 손을 또 써 봐도 같다 — 사람이 「이어서」를 누르기 전까지.
    for action in ("browser_click", "browser_fill", "browser_press", "browser_site_search", "browser_select_option"):
        with pytest.raises(ValueError, match="^human_on_tab"):
            _step(worker, page, action)


def test_the_second_screen_of_the_incident_is_also_stopped(tmp_path: Path) -> None:
    """같은 사이트(github.com)로 사람이 옮겨도 — 이 판이 마지막으로 간 곳이 로그인 화면이 아니면 사람의 화면이다."""
    worker, page = _worker(tmp_path)
    _step(worker, page, "browser_open", "https://github.com/sonjari/sonjari", url="https://github.com/sonjari/sonjari")
    _person_goes(worker, page, "https://github.com/ollama/ollama")
    with pytest.raises(ValueError, match="^human_on_tab"):
        _step(worker, page, "browser_click", ref="j15")


def test_the_stop_hands_the_job_to_the_person_at_once(tmp_path: Path) -> None:
    worker, page = _worker(tmp_path)
    _step(worker, page, "browser_open", "https://github.com/sonjari/sonjari", url="https://github.com/sonjari/sonjari")
    _person_goes(worker, page, GOOGLE_CHOOSER)
    with pytest.raises(ValueError) as stopped:
        _step(worker, page, "browser_back")
    steps = [
        {"tool": "browser_open", "ok": True, "evidence": {"url": "https://github.com/sonjari/sonjari"}},
        {"tool": "browser_snapshot", "ok": True, "evidence": {"url": GOOGLE_CHOOSER}},
        {"tool": "browser_back", "ok": False, "error": str(stopped.value)},
    ]
    report = _stuck_report(steps)
    assert report is not None and report["kind"] == "human_on_tab", "몇 번 실패를 기다리지 않고 첫 번에 넘긴다"
    assert report["url"] == "https://accounts.google.com/v3/signin/accountchooser"
    assert "이어서" in report["ask"]
    assert "code_challenge" not in str(report)


def test_a_late_redirect_of_our_own_click_is_not_a_person(tmp_path: Path) -> None:
    """운영 기록: 다나와 광고 다리 → 스마트스토어, 네이버 광고 주소 → 11번가. 사람 손이 없으면 우리 이동이다."""
    worker, page = _worker(tmp_path)
    bridge = "https://prod.danawa.com/bridge/loadingBridgePowerShopping.php?minPrice=35900"
    _step(worker, page, "browser_open", bridge, url=bridge)
    page.url = "https://smartstore.naver.com/actto/products/7655009823?n_sads=true"  # 늦게 끝난 이동
    looked = _step(worker, page, "browser_snapshot")
    assert "human_on_tab" not in looked
    _step(worker, page, "browser_click", ref="j3")  # 멈추지 않는다
    page.url = "https://www.wishket.com/project/similar-case-search/?search_keyword="
    _step(worker, page, "browser_fill", ref="j1", value="AI")


def test_a_login_the_job_reached_and_the_person_finished_is_the_jobs_screen(tmp_path: Path) -> None:
    """운영 기록(네이버 서치어드바이저): 이 판이 연 주소가 로그인으로 넘어갔고, 사람이 로그인하자 원래 화면으로 돌아왔다."""
    worker, page = _worker(tmp_path)
    asked = "https://searchadvisor.naver.com/console/board"
    _step(worker, page, "browser_open", "https://nid.naver.com/oauth2.0/authorize?response_type=code&client_id=x&state=y",
          url=asked)
    _person_goes(worker, page, asked)
    _step(worker, page, "browser_fill", ref="j9", value="https://sonjari.com")  # 멈추지 않는다

    worker2, page2 = _worker(tmp_path)
    _step(worker2, page2, "browser_open", "https://manus.im/pricing", url="https://manus.im/pricing")
    _step(worker2, page2, "browser_click", "https://manus.im/login?redirectUrl=https%3A%2F%2Fmanus.im%2Fpricing", ref="j10")
    _person_goes(worker2, page2, "https://manus.im/app")
    _step(worker2, page2, "browser_click", ref="j2")  # 같은 사이트로 로그인을 마쳤다 — 이 판의 화면


def test_opening_our_own_address_ends_the_hold(tmp_path: Path) -> None:
    worker, page = _worker(tmp_path)
    _step(worker, page, "browser_open", "https://huggingface.co/Qwen/Qwen3-14B", url="https://huggingface.co/Qwen/Qwen3-14B")
    _person_goes(worker, page, "https://huggingface.co/models")
    assert "human_on_tab" in _step(worker, page, "browser_extract")
    _step(worker, page, "browser_open", "https://huggingface.co/Qwen/Qwen3.8-27B", url="https://huggingface.co/Qwen/Qwen3.8-27B")
    assert worker._human_on_tab is None
    assert "human_on_tab" not in _step(worker, page, "browser_click", ref="j4")


def test_continuing_hands_the_tab_back(tmp_path: Path) -> None:
    worker, page = _worker(tmp_path)
    _step(worker, page, "browser_open", "https://github.com/sonjari/sonjari", url="https://github.com/sonjari/sonjari")
    _person_goes(worker, page, "https://github.com/ollama/ollama")
    with pytest.raises(ValueError, match="^human_on_tab"):
        _step(worker, page, "browser_click", ref="j15")
    worker.hand_tab_back()  # 사람이 「이어서」
    _step(worker, page, "browser_click", ref="j15")
    assert _own_key("https://github.com/ollama/ollama") in worker._own_page_keys


def test_a_new_job_starts_from_the_screen_it_finds(tmp_path: Path) -> None:
    worker, page = _worker(tmp_path)
    _step(worker, page, "browser_open", "https://github.com/sonjari/sonjari", url="https://github.com/sonjari/sonjari")
    _person_goes(worker, page, "https://github.com/ollama/ollama")
    worker.forget_results()  # 판 경계
    _step(worker, page, "browser_click", ref="j1")  # 맡길 때 떠 있던 화면이 출발점이다


def test_a_screen_the_person_changed_during_our_action_is_not_written_as_ours(tmp_path: Path) -> None:
    worker, page = _worker(tmp_path)
    _step(worker, page, "browser_open", "https://example.com/a", url="https://example.com/a")
    worker._hold_if_human_on_tab("browser_click", page)
    started = time.time()
    time.sleep(0.002)
    page.url = "https://pay.example.org/checkout"
    worker.note_human_hand()  # 우리 누르기가 도는 사이 사람이 만졌다
    worker._note_own_page_after("browser_click", {"ref": "j1"}, started)
    assert _own_key("https://pay.example.org/checkout") not in worker._own_page_keys
    with pytest.raises(ValueError, match="^human_on_tab"):
        _step(worker, page, "browser_click", ref="j2")


def test_every_browser_hand_is_sorted_once() -> None:
    """새 손을 만들면 그날 이 분류에 넣는다 — 분류표에 없는 손이 조용히 빠지면 문이 그 손을 못 본다(사고 S)."""
    source = inspect.getsource(BrowserWorker._execute_once)
    handlers = set(re.findall(r'^\s+"((?:browser|naver_blog)_[a-z_]+)": (?:self\.|lambda)', source, re.MULTILINE))
    assert len(handlers) > 40
    neither = {"browser_close", "browser_switch_tab", "naver_blog_open_editor"}
    assert not (_HANDS_ON_THE_PAGE & _OWN_ADDRESS_HANDS) and not (_HANDS_ON_THE_PAGE & _LOOKING_HANDS)
    assert not (_OWN_ADDRESS_HANDS & _LOOKING_HANDS)
    assert _SCREEN_HANDS <= _HANDS_ON_THE_PAGE
    unsorted = handlers - _HANDS_ON_THE_PAGE - _OWN_ADDRESS_HANDS - _LOOKING_HANDS - neither
    assert not unsorted, f"분류 안 된 손: {sorted(unsorted)}"


def test_the_gate_sits_before_the_hand_and_the_resume_hands_the_tab_back() -> None:
    source = inspect.getsource(BrowserWorker._execute_once)
    assert source.index("self._hold_if_human_on_tab(action, page)") < source.index("result = handler(page, arguments)")
    assert source.index("result = handler(page, arguments)") < source.index("self._note_own_page_after(action, arguments")
    root = Path(browser_module.__file__).resolve().parent
    agent_source = (root / "agent.py").read_text(encoding="utf-8")
    resume = agent_source[agent_source.index("checkpoint = self.store.get_agent_checkpoint(job_id)\n        if checkpoint:"):]
    assert resume.index('"hand_tab_back"') < resume.index("else:"), "멈춘 판을 이을 때 탭을 돌려받는다"
    live_source = (root / "live_view.py").read_text(encoding="utf-8")
    release = live_source[live_source.index("def release_control"):live_source.index("def input(")]
    assert "note_human_hand()" in release
