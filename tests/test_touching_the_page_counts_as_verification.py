"""만든 페이지를 **만지고 읽은** 확인은 코드 판의 검증이다 (2026-09-30 대표 결정).

## 왜

질문 카드 라이브 판(잡 feb76ebb): 메모 앱 `index.html` 을 만들고 브라우저로 칸을 채우고 버튼을 누르고 결과까지
읽었다. 그런데 「브라우저로 본 것은 검증이 아니다」 규칙 때문에 `coding_verification_missing` 으로 죽었다 —
규칙이 시키는 프로젝트 명령 대신 작업 폴더를 못 보는 `sandbox_run` 을 네 번 돌리다가.

## 선

- 인정: 이 PC 안 페이지(file·localhost)에서 **누르기·채우기 뒤에 읽기**.
- 여전히 아님: 열어서 보기만 · 바깥 사이트 · 확인한 뒤 코드를 또 고친 것 · 실패한 걸음.
"""

from __future__ import annotations

from alture_jarvis.code_runtime import browser_verification_indices, code_verification_is_current
from alture_jarvis.plan import _execution_verified

PAGE = "file:///C:/Users/me/Documents/memo/index.html"


def _write(path: str = "index.html") -> dict:
    return {"tool": "local_write_file", "ok": True, "arguments": {"path": path}, "evidence": {"verified": True}}


def _step(tool: str, url: str = "", ok: bool = True) -> dict:
    return {"tool": tool, "ok": ok, "arguments": {"url": url} if tool == "browser_open" else {},
            "evidence": {"url": url} if url else {}}


def test_filling_clicking_then_reading_the_local_page_is_verification() -> None:
    steps = [_write(), _step("browser_open", PAGE), _step("browser_fill"), _step("browser_click"), _step("browser_read")]

    assert browser_verification_indices(steps) == [4]
    assert code_verification_is_current(steps) is True
    assert _execution_verified(steps)[0] is True


def test_the_same_page_on_localhost_counts_too() -> None:
    steps = [_write(), _step("browser_open", "http://127.0.0.1:5173/"), _step("browser_click"),
             _step("browser_snapshot", "http://127.0.0.1:5173/#done")]

    assert code_verification_is_current(steps) is True


def test_only_looking_is_still_not_verification() -> None:
    steps = [_write(), _step("browser_open", PAGE), _step("browser_read"), _step("browser_snapshot")]

    assert browser_verification_indices(steps) == []
    assert code_verification_is_current(steps) is False


def test_touching_an_outside_site_is_not_verifying_your_code() -> None:
    steps = [_write(), _step("browser_open", "https://example.com/"), _step("browser_click"), _step("browser_read")]

    assert code_verification_is_current(steps) is False


def test_changing_the_code_after_the_check_needs_a_new_check() -> None:
    steps = [_write(), _step("browser_open", PAGE), _step("browser_click"), _step("browser_read"), _write("app.js")]

    assert code_verification_is_current(steps) is False


def test_a_failed_click_does_not_count() -> None:
    steps = [_write(), _step("browser_open", PAGE), _step("browser_click", ok=False), _step("browser_read")]

    assert code_verification_is_current(steps) is False


def test_the_project_command_still_works_as_before() -> None:
    steps = [_write(), {"tool": "local_run_project_command", "ok": True, "evidence": {"verified": True, "exit_code": 0}}]

    assert code_verification_is_current(steps) is True
