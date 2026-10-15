"""검증을 되받고도 안 돌린 판은 검증하는 손만 받는다 (2026-09-21 저녁, AURORA 5판).

## 어떻게 찾았나

같은 과제를 여섯 번 돌린 중 한 판이 7걸음에 끝났다:

     1 local_index_codebase   2 local_write_file   3 local_preview_page
     4 browser_open           5 browser_snapshot    6 browser_screenshot   7 browser_read
     (끝)  → coding_verification_missing

파일을 만들고 화면까지 봤는데 ``local_run_project_command`` 는 한 번도 안 불렀다.
프롬프트에 「검증하라」고 적혀 있었다. 마지막 걸음 뒤 13초 만에 끝났으니 모델이 도구 없이
답을 세 번 낸 것(되받기 두 번을 무시)으로 읽힌다 — 다만 **그 증거가 디스크에 없었다.**

처음 의심한 「검증 후 종료 강제」는 성공한 검증 실행이 있어야 참이 되므로 이 판의 원인이 아니다.

## 고친 것

1. 되받기를 한 번 받고도 검증이 없으면 **두 번째 턴부터 검증하는 손만** 보여 준다
   (읽기 루프의 `code_tools_after_look_pushback` 과 같은 결정론 — 안내문은 안 먹는다).
2. 되받기 문구가 「테스트·빌드」만 말해서 **테스트가 없는 정적 페이지**에는 안 들어맞았다.
   검증 스크립트를 만들어 돌리라고 구체적으로 적고, 브라우저로 본 것은 검증이 아니라고 적는다.
3. 그래도 죽으면 되받기 횟수와 **무시한 답**을 잡 결과(`diagnosis`)에 남긴다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from alture_jarvis.agent import (
    BrowserAgent,
    code_tools_after_coding_pushback,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

_TOOLS = frozenset({
    "local_read_text_file", "local_index_codebase", "local_preview_page",
    "local_write_file", "local_apply_edit", "local_delete_file",
    "local_run_project_command", "browser_open", "browser_read",
})


def test_no_pushback_yet_keeps_every_hand() -> None:
    assert code_tools_after_coding_pushback(_TOOLS, 0, verified=False) == _TOOLS


def test_after_a_pushback_without_verification_only_verifying_hands_remain() -> None:
    hands = code_tools_after_coding_pushback(_TOOLS, 1, verified=False)

    assert hands == frozenset({
        "local_run_project_command", "local_write_file", "local_apply_edit", "local_delete_file",
    })
    # 브라우저로 또 보는 길이 남아 있으면 5판이 그대로 산다.
    assert not any(name.startswith("browser_") for name in hands)


def test_a_failed_attempt_reopens_the_hands_so_it_cannot_deadlock() -> None:
    """좁힌 손에서 ``old_text_not_found`` 가 나면 정확한 줄을 다시 읽어야 한다.

    안 그러면 읽기 루프가 이미 겪은 교착(`looks_since_write_attempt`)이 이쪽에서 재현된다.
    성패는 가리지 않는다 — 손을 **뻗었는지**만 본다.
    """
    assert code_tools_after_coding_pushback(
        _TOOLS, 1, verified=False, attempted_since_pushback=True,
    ) == _TOOLS


def test_a_verified_job_is_not_narrowed() -> None:
    """이미 검증이 현재 코드에 성공했으면 손을 묶지 않는다(검토 턴이 이어진다)."""
    assert code_tools_after_coding_pushback(_TOOLS, 2, verified=True) == _TOOLS


def test_it_never_narrows_to_a_set_that_cannot_run_anything() -> None:
    """검증 도구가 이 판의 손에 없으면(읽기 전용 등) 좁히지 않는다 — 교착 방지."""
    without_runner = _TOOLS - {"local_run_project_command"}

    assert code_tools_after_coding_pushback(without_runner, 1, verified=False) == without_runner


def test_the_narrowing_and_the_diagnosis_are_wired_in() -> None:
    """만들어 놓고 부르는 자리가 없으면 아무 일도 안 일어난다(이 저장소가 여섯 번 겪은 모양)."""
    source = inspect.getsource(BrowserAgent.run)

    assert "code_tools_after_coding_pushback(" in source
    assert "coding_pushback_answers" in source, "무시한 답을 안 남긴다"
    assert "attempted_since_pushback=" in source, "손을 뻗은 뒤에도 안 풀면 교착한다"
    # 2026-10-08: 진단은 던지는 예외가 아니라 접은 판의 장부(`code_unverified`)에 실린다.
    assert "code_unverified_stop = {" in source and '"code_unverified": code_unverified_stop' in source

    from alture_jarvis.runtime import JarvisRuntime

    assert '"diagnosis"' in inspect.getsource(JarvisRuntime._attach_failure_trace)


def test_the_pushback_text_covers_pages_without_a_test_suite() -> None:
    source = inspect.getsource(BrowserAgent.run)

    # 2026-09-30 대표 결정: 만든 페이지를 만지고 읽은 확인은 검증이다 — 열어서 보기만 한 것은 여전히 아니다.
    assert "열어서 보기만 한 것은 검증이 아니다" in source
    assert "browser_click" in source and "browser_read" in source
    assert "local_delete_file" in source


# --- 실제 판을 돌려 본다 ---------------------------------------------------

class _Tools:
    names = set(_TOOLS)
    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": name, "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in sorted(_TOOLS)
    ]

    def authorize_code_workspace(self, job_id, root):
        assert job_id and root


class _Gateway:
    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, name, arguments, *, job_id=""):
        assert job_id
        path = str(self.root / "index.html")
        if name == "local_write_file":
            # 계획 대조가 「열 수 있는 산출물」을 디스크에서 확인한다 — 진짜로 만든다.
            (self.root / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
            return ToolResult(True, name, result={
                "action": "local_write_file", "path": path, "verified": True, "created": True,
            })
        if name == "local_run_project_command":
            return ToolResult(True, name, result={
                "action": "local_run_project_command", "command": "python verify.py",
                "exit_code": 0, "stdout": "ok", "verified": True,
            })
        return ToolResult(True, name, result={"action": name, "path": path, "text": "x"})


def _agent(tmp_path: Path, model) -> tuple[BrowserAgent, JobStore, EventBus]:
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()

    class _Browser:
        def status(self):
            return {"started": True}

    return BrowserAgent(config, model, _Gateway(tmp_path), _Browser(), _Tools(), store, events), store, events


def _call(name: str, **arguments):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": name, "arguments": arguments}},
    ]}


def _offered(kwargs) -> set[str]:
    return {item["function"]["name"] for item in (kwargs.get("tools") or [])}


class _StubbornModel:
    """파일을 만들고 화면을 본 뒤 **검증은 안 하고 말로만** 답한다 — 5판의 모양."""

    def __init__(self) -> None:
        self.calls = 0
        self.offered: list[set[str]] = []

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        self.offered.append(_offered(kwargs))
        if self.calls == 1:
            return _call("local_write_file", path="index.html", content="<h1>x</h1>")
        if self.calls == 2:
            return _call("browser_open", url="http://127.0.0.1:1/index.html")
        return {"role": "assistant", "content": "화면에서 확인했습니다. 완료했습니다."}


def test_a_job_that_ignores_both_pushbacks_is_folded_with_a_diagnosis_and_narrowed_hands(
    tmp_path,
) -> None:
    """★ 2026-10-08: 이 판은 예전에 `coding_verification_missing` 으로 **실패**했다 — 파일은 만들어졌는데 답은 버려졌다.
    이제 답을 살려 「일부」로 접는다. 머리말·상태·장부 셋을 코드가 박으므로 「검증 없이 완료」는 여전히 없다."""
    model = _StubbornModel()
    agent, store, _events = _agent(tmp_path, model)
    job = store.create_job("chat", "만들어줘", {"prompt": "index.html 만들고 검증해"})
    store.claim_next()

    result = agent.run(
        "index.html 만들고 검증해", job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True,
    )

    # 첫 답(되받기 전)까지는 전부 보였고, 되받기를 받은 뒤의 턴에서는 좁혀졌다.
    assert {"local_read_text_file", "local_run_project_command"} <= model.offered[0]
    assert model.calls == 5, model.offered  # 쓰기 · 열기 · 답 · 되받은 뒤 답 · 또 되받은 뒤 답
    # ★ 2026-10-04: 이 판은 **페이지(index.html)를 만든 판**이라 화면으로 확인하는 손도 남는다 — 「눌러 본 뒤 읽기」가
    #   검증인데(2026-09-30) 브라우저를 빼면 그 길을 따를 수가 없다(사다리 L1·L2). 읽기·검색은 여전히 빠진다.
    for offered in model.offered[3:]:
        assert {
            "local_run_project_command", "local_write_file", "local_apply_edit", "local_delete_file",
        } <= offered, offered
        assert "local_read_text_file" not in offered and "local_index_codebase" not in offered, offered
        assert {"browser_open", "browser_read", "local_preview_page"} & offered, offered

    diagnosis = result.verification["code_unverified"]
    assert diagnosis["coding_pushbacks"] == 2
    assert diagnosis["verified"] is False
    assert diagnosis["mutated"] is True
    assert len(diagnosis["pushed_back_answers"]) == 2
    assert "완료했습니다" in diagnosis["final_answer"]
    # 답은 살아 있고, 첫 줄은 코드가 박은 사실이다. 상태는 완료가 아니다.
    assert result.answer.startswith("⚠ **고친 코드를 실행해 확인하지 못한 채 끝났습니다.**")
    assert "index.html" in result.answer.split("\n\n")[0]
    assert "완료했습니다" in result.answer
    assert result.verification["completion_state"] == "partial"
    assert result.verification["stop_reason"] == "wrapped_up:coding_verification_missing"


class _ObedientOnceNarrowed:
    """말로는 안 듣지만 손이 좁혀지면 검증을 돌린다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        offered = _offered(kwargs)
        if self.calls == 1:
            return _call("local_write_file", path="index.html", content="<h1>x</h1>")
        # 읽기 도구가 보이는 동안(=안 좁혀졌다)에는 말로만 답한다. 좁혀진 손에만 반응한다.
        if "local_read_text_file" in offered:
            return {"role": "assistant", "content": "화면에서 확인했습니다."}
        if self.calls < 6:
            return _call("local_run_project_command", command="python verify.py")
        return {"role": "assistant", "content": "검증을 돌렸고 통과했습니다."}


def test_narrowed_hands_let_a_job_finish_that_words_alone_could_not(tmp_path) -> None:
    model = _ObedientOnceNarrowed()
    agent, store, _events = _agent(tmp_path, model)
    job = store.create_job("chat", "만들어줘", {"prompt": "index.html 만들고 검증해"})
    store.claim_next()

    result = agent.run(
        "index.html 만들고 검증해", job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True,
    )

    # 예외 없이 끝났고, 말로는 안 하던 검증이 좁혀진 손 덕에 실제로 돌았다.
    tools_used = [step["tool"] for step in result.steps]
    assert "local_run_project_command" in tools_used
    assert result.answer.strip()


# --- 고칠 것이 없는 판은 좁히지 않는다 (2026-09-21 밤, 노트북 사다리 fin1) -------

def test_a_job_that_has_changed_nothing_keeps_its_reading_hands() -> None:
    """아직 아무것도 안 고친 판이 되받기를 맞아도 읽기·검색을 뺏지 않는다.

    노트북 4B 가 「직접 읽어 보겠다」고 말만 하고 끝내려다 되받기를 맞았고, 다음 턴에 읽기가 빠진
    쓰기·실행 손 넷만 남아 고칠 줄을 읽을 길이 없었다(`code_tool_not_in_active_profile`, 0ms).
    """
    assert code_tools_after_coding_pushback(_TOOLS, 1, verified=False, mutated=False) == _TOOLS
    assert code_tools_after_coding_pushback(_TOOLS, 2, verified=False, mutated=False) == _TOOLS


def test_a_job_that_did_change_something_is_still_narrowed() -> None:
    """AURORA 를 위한 원래 동작은 그대로다 — 파일을 만들고도 안 돌린 판은 좁혀진다."""
    assert code_tools_after_coding_pushback(_TOOLS, 1, verified=False, mutated=True) < _TOOLS


def test_the_call_site_passes_whether_anything_was_actually_changed() -> None:
    """함수만 고치고 부르는 자리가 기본값(True)에 기대면 아무것도 안 바뀐다."""
    source = inspect.getsource(BrowserAgent.run)

    assert "mutated=any(" in source
    assert '"local_write_file", "local_apply_edit"' in source


class _TalkFirstModel:
    """읽지도 고치지도 않고 「읽어 보겠다」고 말만 한다 — 노트북 L4·L6 3회차의 모양."""

    def __init__(self) -> None:
        self.calls = 0
        self.offered: list[set[str]] = []

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        self.offered.append(_offered(kwargs))
        if self.calls <= 3:
            return {"role": "assistant", "content": "먼저 관련 파일을 읽어 보겠습니다."}
        return {"role": "assistant", "content": "확인하겠습니다."}


def test_a_talking_job_that_changed_nothing_still_sees_its_reading_tools(tmp_path) -> None:
    model = _TalkFirstModel()
    agent, store, _events = _agent(tmp_path, model)
    job = store.create_job("chat", "고쳐줘", {"prompt": "test 가 실패한다 고쳐줘"})
    store.claim_next()

    # 2026-10-08: 실패로 던지지 않고 접는다 — 아무것도 안 고친 판은 그 사실이 첫 줄에 적힌다.
    result = agent.run(
        "test 가 실패한다 고쳐줘", job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True,
    )
    assert result.verification["code_unverified"]["mutated"] is False
    assert result.answer.startswith("ℹ **이 판에서는 파일을 고치지 않았고 실행 확인도 하지 않았습니다.**")
    assert result.verification["completion_state"] == "partial"

    # 되받기를 맞은 뒤의 턴에서도 읽기 도구가 보인다 — 예전에는 여기서 넷만 남았다.
    assert len(model.offered) >= 2, model.offered
    for offered in model.offered:
        assert "local_read_text_file" in offered, offered


# --- 거절 안내는 지금 보이는 손 기준이어야 한다 (2026-09-21 밤, 노트북 L1 2회차) -------

def test_the_refusal_advice_only_names_hands_that_are_open_right_now() -> None:
    """좁혀진 판에서 「지금 쓸 수 있는 것」에 방금 뺏은 도구를 대면 모델이 그 순서대로 튕긴다.

    노트북 4B 는 검색 → grep → 셸 → 읽기 순으로 네 번을 거절당하고 죽었다. 그 순서는
    `_CODE_FALLBACK_DOORS` 의 순서와 같았다 — 안내가 판 전체 프로필로 만들어지고 있었다.
    """
    from alture_jarvis.code_runtime import CodeToolProfile, refusal_for_tool_outside_profile

    full = CodeToolProfile("coding", _TOOLS | {"local_grep", "local_search_files", "local_run_shell"}, "")
    narrowed = CodeToolProfile("coding", frozenset({
        "local_run_project_command", "local_write_file", "local_apply_edit", "local_delete_file",
    }), "")

    wrong = refusal_for_tool_outside_profile("local_read_text_file", full)["instruction"]
    right = refusal_for_tool_outside_profile("local_read_text_file", narrowed)["instruction"]

    assert "local_grep" in wrong  # 판 전체 프로필로 만들면 뺏은 도구를 권한다 — 이게 버그였다
    advice = right.split("지금 쓸 수 있는 것:")[1]
    assert "local_run_project_command" in advice
    for taken in ("local_grep", "local_search_files", "local_read_text_file", "local_run_shell"):
        assert taken not in advice, right


def test_the_refusal_call_site_builds_the_advice_from_the_narrowed_hands() -> None:
    source = inspect.getsource(BrowserAgent.run)

    assert "tool_names=frozenset(active_code_tools)" in source
    assert "refusal_for_tool_outside_profile(name, code_tool_profile)" not in source


class _ReachForReadingModel:
    """좁혀진 뒤에 읽기를 부른다 — 그때 돌려받는 안내문을 붙잡는다."""

    def __init__(self) -> None:
        self.calls = 0
        self.refusal_seen = ""

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _call("local_write_file", path="index.html", content="<h1>x</h1>")
        if self.calls == 2:
            return {"role": "assistant", "content": "만들었습니다."}          # 되받기 1
        if self.calls == 3:
            return _call("local_read_text_file", path="index.html")           # 좁혀진 손에 없는 도구
        for message in reversed(messages):
            if message.get("role") == "tool":
                self.refusal_seen = str(message.get("content"))
                break
        return {"role": "assistant", "content": "확인했습니다."}


def test_a_refused_read_after_narrowing_is_told_to_verify_not_to_read_elsewhere(tmp_path) -> None:
    model = _ReachForReadingModel()
    agent, store, _events = _agent(tmp_path, model)
    job = store.create_job("chat", "만들어줘", {"prompt": "index.html 만들고 검증해"})
    store.claim_next()

    # 2026-10-08: 실패로 던지지 않고 접는다.
    result = agent.run(
        "index.html 만들고 검증해", job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True,
    )
    assert result.verification["completion_state"] == "partial"
    assert result.verification["code_unverified"]["verified"] is False

    assert "code_tool_not_in_active_profile" in model.refusal_seen, model.refusal_seen
    advice = model.refusal_seen.split("지금 쓸 수 있는 것:")[1]
    assert "local_run_project_command" in advice
    for taken in ("local_grep", "local_search_files", "local_run_shell"):
        assert taken not in advice, model.refusal_seen
