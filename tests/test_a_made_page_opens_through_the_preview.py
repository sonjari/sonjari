"""만든 페이지를 `file://`·`localhost` 로 열려 하면 **미리보기 주소로 바꿔 열어 준다** (2026-09-21, 노트북 4B AURORA).

## 어떻게 찾았나

4B 로 AURORA(단일 html 페이지 + 미리보기로 열어 눌러 보기)를 세 번 돌렸다. 잡 상태는 `completed` 0/3 이었다.
페이지는 만들었는데 화면 확인 단계에서 이랬다:

    browser_open  browser_url_not_allowed      ← file:///C:/…/index.html
    browser_open  browser_url_not_allowed      ← 같은 것을 4번
    browser_open  Page.goto: ERR_CONNECTION_REFUSED at http://localhost:8080/index.html   ← 서버를 지어냄
    (local_preview_page 는 한 번도 안 불렀다 — 프롬프트에 이름까지 적혀 있었는데)

`file://` 를 그대로 열면 `.ssh` 키도 열려서 브라우저가 막는 게 맞다. 그런데 **막기만 하고 갈 곳을 안 말한다.** 안내문은 안 먹는다
(사고 R) — 4B 는 같은 벽에 네 번 부딪쳤다. 그래서 도구가 대신 한다: 작업 폴더 **안**의 페이지를 가리키는 `file://`·`localhost`
주소는 `local_preview_page` 로 서빙한 주소로 바꿔 열고, 바꿨다는 사실을 결과에 적는다(`site_first_note` 와 같은 규율).

## 안 여는 것

작업 폴더 **밖**의 파일은 바꾸지 않는다 — 그대로 거절된다. 우회로가 되면 안 된다.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from alture_jarvis.agent import BrowserAgent


class _Gateway:
    def __init__(self, url: str = "http://127.0.0.1:54321/index.html", ok: bool = True) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.url = url
        self.ok = ok

    def execute(self, name, arguments, *, job_id=""):
        self.calls.append((name, dict(arguments)))
        return SimpleNamespace(ok=self.ok, result={"url": self.url, "path": arguments.get("path")})


def _agent(gateway: _Gateway) -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)  # 이 판단만 시험한다 — 전체 에이전트는 모델이 있어야 뜬다
    agent.gateway = gateway
    return agent


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "page.html").write_text("<h1>y</h1>", encoding="utf-8")
    return root


def test_a_file_url_inside_the_workspace_becomes_the_preview_address(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    gateway = _Gateway()

    out = _agent(gateway)._localize_local_open({"url": (root / "index.html").as_uri()}, str(root), "job-1")

    assert out is not None
    arguments, note = out
    assert arguments["url"] == "http://127.0.0.1:54321/index.html"
    assert "미리보기" in note and "바꿔" in note, "바꿨다는 사실을 감추지 않는다"
    assert gateway.calls == [("local_preview_page", {"path": str((root / "index.html").resolve())})]


def test_a_localhost_address_the_model_invented_is_pointed_at_the_real_server(tmp_path: Path) -> None:
    """서버를 안 띄우고 `http://localhost:8080/index.html` 을 여는 판이 실제로 있었다."""
    root = _workspace(tmp_path)

    out = _agent(_Gateway())._localize_local_open({"url": "http://localhost:8080/sub/page.html"}, str(root), "job-1")

    assert out is not None and out[0]["url"] == "http://127.0.0.1:54321/index.html"


def test_a_bare_windows_path_is_accepted_too(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    out = _agent(_Gateway())._localize_local_open({"url": str(root / "index.html")}, str(root), "job-1")

    assert out is not None


def test_a_file_outside_the_workspace_is_never_opened_this_way(tmp_path: Path) -> None:
    """★ 우회로가 되면 안 된다 — 밖은 그대로 거절된다."""
    root = _workspace(tmp_path)
    secret = tmp_path / "secret.html"
    secret.write_text("x", encoding="utf-8")
    gateway = _Gateway()

    assert _agent(gateway)._localize_local_open({"url": secret.as_uri()}, str(root), "job-1") is None
    assert gateway.calls == []


def test_a_relative_escape_does_not_leave_the_workspace(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (tmp_path / "outside.html").write_text("x", encoding="utf-8")

    out = _agent(_Gateway())._localize_local_open({"url": "http://localhost:1/../outside.html"}, str(root), "job-1")

    assert out is None


def test_real_web_addresses_are_untouched(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    for url in ("https://example.com/", "http://192.168.0.5/index.html", "https://localhost.evil.com/x"):
        assert _agent(_Gateway())._localize_local_open({"url": url}, str(root), "job-1") is None, url


def test_a_missing_page_is_left_to_fail_honestly(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    assert _agent(_Gateway())._localize_local_open({"url": (root / "nope.html").as_uri()}, str(root), "job-1") is None


def test_when_the_preview_itself_fails_nothing_is_swapped(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    assert _agent(_Gateway(ok=False))._localize_local_open(
        {"url": (root / "index.html").as_uri()}, str(root), "job-1") is None


def test_it_is_wired_into_the_tool_loop_for_code_jobs_only() -> None:
    """만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다."""
    source = inspect.getsource(BrowserAgent.run)
    assert "_localize_local_open(" in source
    assert 'name == "browser_open"' in source and 'model_role == "code"' in source


def test_the_swap_is_told_to_the_model_in_the_result() -> None:
    source = inspect.getsource(BrowserAgent.run)
    assert "localize_note" in source
