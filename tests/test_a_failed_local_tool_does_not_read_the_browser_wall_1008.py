"""브라우저를 쓰지 않은 판은 브라우저에 떠 있는 로그인 화면 때문에 멈추지 않는다 (2026-10-08).

코드 과제(폴더 보기 · 파일 읽기 넷 · 파일 고치기)에서 「파일 고치기」가 글자를 못 맞춰 한 번 실패했다. 그 순간 판이
`human_gate:login_required` 로 멈추고 화면에 로그인 카드가 떴다 — 브라우저에는 그 전 대화가 열어 둔 뉴스 기사 탭이 있었고
거기 비밀번호 칸이 하나 있었다. 이 판은 브라우저를 한 번도 부르지 않았다.

길목의 조건이 「**어떤 도구든** 실패하면 지금 화면의 구조를 본다」였다(바로 위 주석은 「비브라우저 도구까지 현재 탭에 묶지는
않는다」고 적고 있었다). 화면의 문은 **이 판이 그 화면에 들어간 적이 있을 때만** 이 판의 문이다.
"""
from __future__ import annotations

from test_agent import _agent

LOGIN_WALL = {
    "known": True,
    "url": "https://news.example/article/1",
    "wall_url": "https://news.example/article/1",
    "password_fields": 1,
    "password_gate": True,
    "captcha": False,
    "windows": 2,
}


class _QuietAttention:
    def check(self, **_kwargs):
        return None


def _record(agent, steps, *, name, ok, arguments=None, error=""):
    observation = {"ok": ok, "result": {}}
    if error:
        observation["error"] = error
    return agent._record_observation(
        job_id="wall-ownership",
        name=name,
        arguments=arguments or {},
        step_number=len(steps) + 1,
        label=name,
        observation=observation,
        steps=steps,
        messages=[],
        evidence_urls=[],
        last_action_ids={},
        tool_numbers=set(),
        tool_numbers_body=set(),
    )


def _agent_with_a_login_tab(tmp_path):
    agent, _, _, _ = _agent(tmp_path)
    agent.attention = _QuietAttention()
    agent.browser.blocking_wall = lambda: dict(LOGIN_WALL)
    return agent


def test_a_failed_edit_in_a_job_that_never_used_the_browser_is_not_a_login_gate(tmp_path) -> None:
    agent = _agent_with_a_login_tab(tmp_path)
    steps: list[dict] = []
    for name in ("local_list_directory", "local_read_text_file", "local_read_text_file"):
        assert _record(agent, steps, name=name, ok=True, arguments={"path": "C:/work/tidy.py"}) is None

    gate = _record(agent, steps, name="local_apply_edit", ok=False, arguments={"path": "C:/work/tidy.py"},
                   error="old_text_not_found")

    assert gate is None, "브라우저를 안 쓴 판이 브라우저 탭의 로그인 화면 때문에 멈췄다"


def test_only_listing_tabs_does_not_make_the_screen_this_jobs_door(tmp_path) -> None:
    """탭 목록을 본 것은 그 화면에 들어간 것이 아니다(10-07 과제 J 의 규칙과 같다)."""
    agent = _agent_with_a_login_tab(tmp_path)
    steps: list[dict] = []
    assert _record(agent, steps, name="browser_tabs", ok=True) is None

    assert _record(agent, steps, name="local_write_file", ok=False, error="permission_denied") is None


def test_a_failed_local_tool_after_the_job_used_the_browser_still_checks_the_screen(tmp_path) -> None:
    """★ 좋은 표본 — 이 판이 그 화면에 들어갔다면, 뒤따른 다른 도구의 실패에서도 문을 본다(예전 동작 그대로)."""
    agent, _, _, _ = _agent(tmp_path)
    agent.attention = _QuietAttention()
    wall = {"known": True, "url": "", "wall_url": "", "password_fields": 0, "password_gate": False, "captcha": False}
    agent.browser.blocking_wall = lambda: dict(wall)
    steps: list[dict] = []
    assert _record(agent, steps, name="browser_open", ok=True, arguments={"url": "https://news.example/article/1"}) is None

    wall.update(LOGIN_WALL)  # 그 뒤 화면이 로그인으로 바뀌었다
    gate = _record(agent, steps, name="local_write_file", ok=False, error="write_failed")

    assert gate is not None and gate["code"] == "login_required"


def test_a_browser_step_on_a_login_screen_is_still_a_gate(tmp_path) -> None:
    """★ 좋은 표본 — 브라우저 걸음은 성공해도 실패해도 화면의 구조를 본다."""
    for ok in (True, False):
        agent = _agent_with_a_login_tab(tmp_path)
        gate = _record(agent, [], name="browser_snapshot", ok=ok, error="" if ok else "blocked")
        assert gate is not None and gate["code"] == "login_required", ok
