"""이 PC 개발 주소의 시험 계정 — 사람에게 넘기지 않는다 (2026-10-02 분업 실험).

클로드 코드가 할 일 앱을 만들고 「localhost:3000 에서 아이디 "demo_user", 비밀번호 "demo1234" 로 가입해 확인해라」를
맡겼는데, 손자리가 비밀번호 칸을 보고 「로그인이 필요해요」 카드로 사람에게 넘겼다.
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis import browser as browser_mod
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.human_gate import (
    LOCAL_TEST_LOGIN_NOTE,
    allows_local_test_secret,
    is_local_dev_url,
    local_test_login_gate,
    local_test_login_prompt,
)

PROMPT = (
    '내 컴퓨터의 http://localhost:3000 에 떠 있는 할 일 앱을 크롬으로 열어 확인해줘. 순서: '
    '1) 첫 화면에서 회원가입을 눌러 아이디 "demo_user", 비밀번호 "demo1234" 로 회원가입한다.'
)


def test_only_this_pcs_dev_addresses_count() -> None:
    for url in ("http://localhost:3000/", "http://127.0.0.1:5173/login", "http://[::1]:8000/", "http://app.localhost/",
                "https://shop.test/signin"):
        assert is_local_dev_url(url), url
    for url in ("https://www.naver.com/login", "http://localhost.evil.com/", "file:///C:/a.html", ""):
        assert not is_local_dev_url(url), url


def test_the_secret_must_be_written_in_the_task_verbatim() -> None:
    assert allows_local_test_secret("http://localhost:3000/", PROMPT, "demo1234")
    assert not allows_local_test_secret("http://localhost:3000/", PROMPT, "hunter22"), "맡긴 글에 없는 값"
    assert not allows_local_test_secret("https://nid.naver.com/login", PROMPT, "demo1234"), "밖의 사이트"
    assert not allows_local_test_secret("http://localhost:3000/", PROMPT, "dem"), "너무 짧은 값은 우연히 겹친다"
    no_password_word = "localhost:3000 앱에 demo1234 를 검색해 봐"
    assert not allows_local_test_secret("http://localhost:3000/", no_password_word, "demo1234")
    no_local_mention = '네이버에 아이디 "demo_user", 비밀번호 "demo1234" 로 로그인해'
    assert local_test_login_prompt(no_local_mention) == ""


def test_only_the_login_gate_is_passed_payment_and_captcha_still_go_to_a_person() -> None:
    assert local_test_login_gate("login_required", "http://localhost:3000/", PROMPT)
    assert not local_test_login_gate("bot_check", "http://localhost:3000/", PROMPT)
    assert not local_test_login_gate("payment_required", "http://localhost:3000/", PROMPT)
    assert not local_test_login_gate("login_required", "https://www.coupang.com/login", PROMPT)
    assert not local_test_login_gate("login_required", "http://localhost:3000/", "할 일 앱을 열어 확인해줘")


class _Events:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    def publish(self, name: str, payload: dict[str, Any]) -> None:
        self.published.append((name, payload))


def test_the_agent_tells_the_model_once_and_logs_it() -> None:
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.events = _Events()
    agent._local_test_prompt = local_test_login_prompt(PROMPT)
    messages: list[dict[str, Any]] = []
    assert agent._pass_local_test_login("j1", "login_required", "http://localhost:3000/", messages)
    assert agent._pass_local_test_login("j1", "login_required", "http://localhost:3000/", messages)
    assert [m["content"] for m in messages] == [LOCAL_TEST_LOGIN_NOTE]
    assert agent.events.published == [("agent_local_test_login", {"job_id": "j1", "url": "http://localhost:3000/"})]
    assert not agent._pass_local_test_login("j1", "login_required", "https://www.naver.com/login", messages)
    agent._local_test_prompt = ""
    assert not agent._pass_local_test_login("j2", "login_required", "http://localhost:3000/", messages)


class _Locator:
    def __init__(self, field_type: str) -> None:
        self.field_type = field_type
        self.filled: list[str] = []

    def get_attribute(self, name: str) -> str:
        return self.field_type if name == "type" else ""

    def is_disabled(self, timeout: int = 0) -> bool:
        return False

    def input_value(self, timeout: int = 0) -> str:
        return ""

    def fill(self, value: str) -> None:
        self.filled.append(value)


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url

    def wait_for_timeout(self, ms: int) -> None:
        return None


def _worker(locator: _Locator, prompt: str) -> Any:
    worker = browser_mod.BrowserWorker.__new__(browser_mod.BrowserWorker)
    worker.local_test_prompt = local_test_login_prompt(prompt)
    worker._ref_locator = lambda page, ref: locator
    worker._show_visual = lambda *a, **k: None
    worker._evidence = lambda action, **extra: {"action": action, "url": "http://localhost:3000/", **extra}
    worker.remembered: list[str] = []
    worker._remember_typed = worker.remembered.append
    worker._remember_filled = lambda *a, **k: None
    return worker


def test_the_password_field_takes_the_given_test_value_on_localhost_only() -> None:
    locator = _Locator("password")
    worker = _worker(locator, PROMPT)
    out = worker._fill(_Page("http://localhost:3000/"), {"ref": "e7", "value": "demo1234"})
    assert locator.filled == ["demo1234"]
    assert out["local_test_credential"] is True and out["value_length"] == 8
    assert "previous_value" not in out and "demo1234" not in str(out)
    assert worker.remembered == [], "비밀번호를 검색어 기억에 남기지 않는다"

    with pytest.raises(RuntimeError, match="sensitive_field_blocked"):
        worker._fill(_Page("http://localhost:3000/"), {"ref": "e7", "value": "other999"})
    with pytest.raises(RuntimeError, match="sensitive_field_blocked"):
        worker._fill(_Page("https://www.naver.com/login"), {"ref": "e7", "value": "demo1234"})
    with pytest.raises(RuntimeError, match="sensitive_field_blocked"):
        _worker(_Locator("password"), "할 일 앱 확인해줘")._fill(
            _Page("http://localhost:3000/"), {"ref": "e7", "value": "demo1234"}
        )


def test_file_fields_stay_blocked_even_on_localhost() -> None:
    worker = _worker(_Locator("file"), PROMPT)
    with pytest.raises(RuntimeError, match="sensitive_field_blocked"):
        worker._fill(_Page("http://localhost:3000/"), {"ref": "e7", "value": "demo1234"})
