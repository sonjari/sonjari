"""준비까지 해 놓고 커밋을 안 부르는 판을 **대신 눌러 준다.**

## 왜 (2026-08-20 실측)

7일치 DB 에서 위임이 걸린 179 판 중 60 판(33.5%)이 `model_stopped_early` 로 끝났고,
그중 행위 요구가 미달인 12 판의 걸음 꼬리가 전부 같았다:

    naver_blog_prepare_post → fill_editor → prepare_save_draft    (끝)
    google_gmail_prepare_send                                      (끝)
    google_calendar_prepare_create                                 (끝)

답은 "승인을 기다리는 대기 상태입니다"였다. **승인 요청이 뜬 적이 없다.** 카드는
도구를 불러야 생기는데 부르지 않았으니 사용자님이 누를 것 자체가 없었다.

프롬프트에는 이미 "commit 도구를 실제로 호출해야만 화면에 승인 요청이 생성된다"가
적혀 있고, 되받기도 두 번까지 걸려 있다. 둘 다 못 뚫었다 — 안내문은 안 먹는다(사고 R).

## 이 검사가 지키는 것

**지어내지 않는다.** 뿌리(제목·본문·수신자를 받는 prepare)는 절대 대신 부르지 않고,
그 뒤의 칸들은 인자가 `action_id` 하나뿐이라 지어낼 것이 없다. 그 사실이 깨지면
(도구에 인자가 하나 늘면) 이 검사가 그 자리에서 깨져야 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.agent import (
    _ACTION_ID_CONSUMER_TO_PRODUCER,
    _ACTION_ID_PRODUCER_TOOLS,
    _COMMIT_CHAINS,
    _COMMIT_TOOLS,
    _forced_commit_call,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.events import EventBus
from alture_jarvis.google_workspace import GoogleWorkspace
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.naver_blog import NaverBlogTools
from alture_jarvis.plan import Requirement


def _step(tool: str, ok: bool = True) -> dict[str, Any]:
    return {"step": 1, "tool": tool, "arguments": {}, "ok": ok, "status": "", "error": "", "evidence": {}}


def _unmet(tool: str) -> list[tuple[Requirement, bool, str]]:
    return [(Requirement("action", "임시저장", tool), False, "실행 안 됨")]


# ── 사슬 자체가 성립하는가 ────────────────────────────────────────────────────

def test_every_chain_ends_at_a_real_commit() -> None:
    for commit, chain in _COMMIT_CHAINS.items():
        assert chain[-1] == commit, f"{commit} 사슬의 끝이 자기 자신이 아니다"
        assert commit in _COMMIT_TOOLS, f"{commit} 는 커밋 도구 목록에 없다"


def test_the_root_is_a_prepare_and_the_rest_are_consumers() -> None:
    """뿌리만 진짜 인자를 받는다. 나머지는 전부 action_id 소비자여야 한다."""
    for chain in _COMMIT_CHAINS.values():
        assert chain[0] in _ACTION_ID_PRODUCER_TOOLS
        for tool in chain[1:]:
            assert tool in _ACTION_ID_CONSUMER_TO_PRODUCER, f"{tool} 가 소비자 표에 없다"


def test_pushed_tools_take_nothing_but_an_action_id(tmp_path: Path) -> None:
    """★ 이 검사가 이 기능의 안전 근거다.

    대신 부르는 칸에 인자가 하나라도 더 생기면 그 순간부터 우리는 **값을 지어내야**
    한다. 그때는 이 검사가 깨져서 사람이 다시 판단하게 만든다.
    """
    config = JarvisConfig(runtime_root=tmp_path)
    schemas: dict[str, dict[str, Any]] = {}

    class _Browser:  # 스키마만 읽는다 — 브라우저는 부르지 않는다
        def __getattr__(self, name: str) -> Any:  # pragma: no cover - 방어용
            raise AssertionError(f"브라우저를 부르면 안 된다: {name}")

    actions = ExternalActionStore(tmp_path / "data" / "jarvis.db")
    collections = [
        NaverBlogTools(config, _Browser(), LocalComputerTools(config), actions),
        GoogleWorkspace(
            config, EventBus(), local_computer=LocalComputerTools(config), actions=actions
        ),
    ]
    for collection in collections:
        for definition in collection.ollama_tools:
            function = definition["function"]
            schemas[function["name"]] = function.get("parameters") or {}

    pushed = {tool for chain in _COMMIT_CHAINS.values() for tool in chain[1:]}
    for tool in sorted(pushed):
        properties = set((schemas[tool].get("properties") or {}).keys())
        assert properties == {"action_id"}, f"{tool} 인자가 action_id 하나가 아니다: {properties}"


# ── 언제 밀고 언제 안 미는가 ──────────────────────────────────────────────────

def test_pushes_the_next_missing_link() -> None:
    """실측 그대로의 판: 준비 셋까지 갔는데 저장을 안 불렀다."""
    steps = [
        _step("naver_blog_prepare_post"),
        _step("naver_blog_fill_editor"),
        _step("naver_blog_prepare_save_draft"),
    ]
    forced = _forced_commit_call(
        _unmet("naver_blog_save_draft"), steps, {"naver_blog_prepare_post": "act-1"}
    )
    assert forced is not None
    name, arguments = forced
    assert name == "naver_blog_save_draft"
    assert set(arguments) == {"action_id"}


def test_fills_the_editor_before_saving() -> None:
    """본문을 안 채우고 저장하면 **빈 글이 저장된다.**

    fill_editor 는 prepare_save_draft 의 형제라, 사슬을 역추적으로 만들면 빠진다.
    그래서 사슬을 손으로 적어 뒀고, 이 검사가 그 이유를 붙들고 있다.
    """
    steps = [_step("naver_blog_prepare_post")]
    forced = _forced_commit_call(
        _unmet("naver_blog_save_draft"), steps, {"naver_blog_prepare_post": "act-1"}
    )
    assert forced is not None and forced[0] == "naver_blog_fill_editor"


def test_never_pushes_the_root_because_it_would_have_to_invent_the_content() -> None:
    """뿌리가 안 돌았으면 내보낼 내용이 없다. 만들지 않는다."""
    assert _forced_commit_call(_unmet("naver_blog_save_draft"), [], {}) is None


def test_does_not_push_what_already_failed() -> None:
    """불렀는데 실패한 칸은 안 민다 — 모델이 안 부른 것이 아니라 도구가 안 된 것이다."""
    steps = [
        _step("naver_blog_prepare_post"),
        _step("naver_blog_fill_editor"),
        _step("naver_blog_prepare_save_draft"),
        _step("naver_blog_save_draft", ok=False),
    ]
    assert (
        _forced_commit_call(
            _unmet("naver_blog_save_draft"), steps, {"naver_blog_prepare_post": "act-1"}
        )
        is None
    )


def test_silent_when_the_user_did_not_ask_for_it() -> None:
    """요구가 채워졌으면 밀 것이 없다. 시키지 않은 것을 하지 않는 자리다."""
    steps = [_step("naver_blog_prepare_post"), _step("naver_blog_fill_editor")]
    met = [(Requirement("action", "임시저장", "naver_blog_save_draft"), True, "완료")]
    assert _forced_commit_call(met, steps, {"naver_blog_prepare_post": "act-1"}) is None


def test_ignores_requirements_that_need_a_screen_reference() -> None:
    """폼 제출은 화면의 ref 가 있어야 한다. ref 를 지어내면 엉뚱한 것을 누른다."""
    steps = [_step("browser_snapshot")]
    unmet = [(Requirement("action", "폼 제출", "browser_click_confirmed"), False, "실행 안 됨")]
    assert _forced_commit_call(unmet, steps, {}) is None


def test_google_chain_is_two_links() -> None:
    steps = [_step("google_calendar_prepare_create")]
    forced = _forced_commit_call(
        [(Requirement("action", "일정 등록", "google_calendar_create"), False, "실행 안 됨")],
        steps,
        {"google_calendar_prepare_create": "act-9"},
    )
    assert forced == ("google_calendar_create", {"action_id": "act-9"})


# ── 배선이 실제로 물려 있는가 ─────────────────────────────────────────────────
#
# ★ 위 검사들은 판정 함수만 본다. 이 저장소는 "도구는 순서에 없으면 안 쓰인다"를
#   여러 번 겪었다 — 함수는 맞는데 아무도 안 부르는 것이 제일 안 보인다.
#   그래서 루프를 통째로 돌려 **실제로 저장까지 나가는지** 본다.

from alture_jarvis.config import JarvisConfig as _Config  # noqa: E402
from alture_jarvis.events import EventBus as _EventBus  # noqa: E402
from alture_jarvis.jobs import JobStore  # noqa: E402
from alture_jarvis.models import ToolResult  # noqa: E402
from alture_jarvis.agent import BrowserAgent, _FORCED_COMMIT_NOTE  # noqa: E402


_BLOG_TOOLS = (
    "naver_blog_prepare_post",
    "naver_blog_fill_editor",
    "naver_blog_prepare_save_draft",
    "naver_blog_save_draft",
)


class _RecordingGateway:
    """부른 것을 적어 둔다. 준비 도구는 진짜처럼 action_id 를 돌려준다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, name: str, arguments: dict[str, Any], *, job_id: str = "") -> ToolResult:
        self.calls.append((name, dict(arguments)))
        payloads = {
            "naver_blog_prepare_post": {"action_id": "post-1", "title": "점검"},
            "naver_blog_fill_editor": {"status": "filled"},
            "naver_blog_prepare_save_draft": {"action_id": "draft-1"},
            "naver_blog_save_draft": {
                "status": "draft_saved",
                "title": "점검",
                "url": "https://blog.naver.com/me/1",
            },
        }
        return ToolResult(True, name, result=payloads.get(name, {"status": "ok"}))


class _StopsAfterPreparing:
    """실측한 모델 그대로 — 준비 하나 부르고, 그 뒤로는 계속 "승인 대기 중"이라 답한다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "naver_blog_prepare_post", "arguments": {}}}
                ],
            }
        return {
            "role": "assistant",
            "content": "임시저장 단계는 승인을 기다리는 대기 상태입니다. 승인해 주시면 실행하겠습니다.",
        }


class _FakeBrowser:
    def status(self) -> dict[str, Any]:
        return {"started": True}


class _FakeTools:
    names = set(_BLOG_TOOLS)
    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {"action_id": {"type": "string"}}},
            },
        }
        for name in _BLOG_TOOLS
    ]


def test_the_loop_actually_pushes_the_draft_out(tmp_path: Path) -> None:
    """"승인 대기 중"이라고만 답하는 모델을 두고도 **임시저장이 나간다.**

    이것이 안 되면 이 기능은 없는 것이다. 실측 판(2026-08-20 쓰기 벤치)이 정확히
    이 모양이었고, 그때는 승인 카드조차 생기지 않아 사용자님이 누를 것이 없었다.
    """
    config = _Config(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _RecordingGateway()
    agent = BrowserAgent(
        config, _StopsAfterPreparing(), gateway, _FakeBrowser(), _FakeTools(), store, _EventBus()
    )
    prompt = "네이버 블로그에 '점검' 이라는 제목으로 세 줄 쓰고 임시저장까지 해줘. 발행은 하지 마."
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()

    result = agent.run(prompt, job_id=job["id"], origin="chat")

    called = [name for name, _ in gateway.calls]
    assert called == list(_BLOG_TOOLS), f"사슬이 끝까지 안 갔다: {called}"
    # 발행은 시키지 않았다("하지 마"). 밀어서도 안 된다.
    assert "naver_blog_publish" not in called
    # action_id 는 각 도구의 **진짜 생산자** 것으로 덮인다(루프의 보정).
    assert dict(gateway.calls)["naver_blog_save_draft"] == {"action_id": "draft-1"}
    assert result.verification["forced_commits"] == 3
    assert result.verification["completion_state"] == "complete"
    assert result.verification["plan_pushbacks"] >= 1


def test_the_model_is_told_we_pushed(tmp_path: Path) -> None:
    """대신 부른 것을 **감추지 않는다.** 모델이 자기가 부르지 않은 결과를 받으면
    그 이유를 알아야 다음 칸을 이어서 부른다."""
    assert "대신 불렀다" in _FORCED_COMMIT_NOTE
    assert _FORCED_COMMIT_NOTE.startswith("★")  # 별도 [시스템] 줄로 올라가는 표시
