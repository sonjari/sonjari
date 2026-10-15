"""할 수 없는 일이면 **시작하기 전에** 말한다.

실측(잡 200건, 2026-08-10): `naver_blog_fill_editor` 8번 호출에 성공 1번.
실패 7건 중 **2건이 로그인 풀림**이었고, 둘 다 편집기까지 5스텝쯤 간 다음에야
터졌다. 사람은 몇 분을 기다렸다가 "로그인이 필요합니다"를 듣는다.

네이버는 '로그인 상태 유지'를 안 켜면 세션 쿠키를 주고 그건 브라우저가 닫히면
죽는다 — 자비스가 일 끝나고 창을 닫게 된 뒤로 더 자주 걸리는 조건이다.

`browser.naver_session_alive()` 는 쿠키만 읽어 공짜다(항해하지 않는다). 값은
`/health` 에 이미 실려 있었는데 **시작 전에 아무도 안 물어봤을 뿐**이다.

여기서 지키는 것 셋:

  1. 로그인 아닌 게 **확인되면** 시작하지 않고 그 자리에서 말한다
  2. **모르면 막지 않는다** — 브라우저가 안 떠 있는 것은 이유가 아니다
  3. 안내에 '로그인 상태 유지'가 들어간다. 그게 재발을 막는 유일한 조작이다
"""

from __future__ import annotations

from typing import Any


class _Browser:
    def __init__(self, session: dict[str, Any] | Exception) -> None:
        self._session = session
        self.calls = 0

    def naver_session_alive(self) -> dict[str, Any]:
        self.calls += 1
        if isinstance(self._session, Exception):
            raise self._session
        return self._session


def _runtime(session: dict[str, Any] | Exception):
    from alture_jarvis.runtime import JarvisRuntime

    runtime = object.__new__(JarvisRuntime)
    runtime.browser = _Browser(session)  # type: ignore[attr-defined]
    return runtime


def test_a_missing_login_stops_before_the_work_starts() -> None:
    note = _runtime({"known": True, "signed_in": False})._blog_session_blocker()
    assert note, "로그인이 없는 게 확인됐는데 그냥 시작한다"
    assert "로그인 상태 유지" in note, "재발을 막는 조작을 안 알려 준다"


def test_being_signed_in_does_not_block() -> None:
    assert _runtime({"known": True, "signed_in": True})._blog_session_blocker() == ""


def test_not_knowing_is_not_a_reason_to_block() -> None:
    """브라우저가 아직 안 떴을 뿐이다 — 띄우면 프로필 쿠키가 그대로 올라온다."""
    note = _runtime({"known": False, "reason": "browser_not_started"})._blog_session_blocker()
    assert note == "", "모른다는 이유로 멀쩡한 요청을 막았다"


def test_a_broken_check_never_blocks_the_user() -> None:
    """확인이 실패했다고 일까지 못 하게 되면 그게 더 나쁘다."""
    assert _runtime(RuntimeError("browser_action_timeout"))._blog_session_blocker() == ""
