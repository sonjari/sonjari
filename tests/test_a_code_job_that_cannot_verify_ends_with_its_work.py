"""검증을 못 하는 자동 코드 작업은 정해진 시간에 그때까지 한 일을 담아 끝난다 (2026-09-22).

## 무엇이 있었나

노트북 4B 의 AURORA 는 파일을 쓰고 검증 스크립트를 다시 쓰기를 되풀이하며 391~1,143초, 한 번은 29분(내가 취소)까지 갔다.
자동 이어가기 리스(`agent_autonomous_lease_sec`)는 진전이 있으면 계속 늘어나서 안 끊는다. 호스트는 그동안 기다린다.

## 왜 이렇게 좁게 만들었나 (데이터로 정했다)

실행된 51판(완료 36 · 실패 15) 에서 **검증 실행 실패 횟수는 성공과 실패가 겹쳤다**(완료도 3 번까지). 그래서 「N 번 실패하면 끊기」는
성공한 작업을 죽인다 — 쓰지 않는다. 완료 36판의 최대 소요는 592초이고 이 저장소가 예전에 적어 둔 통과 최대는 1,202초라,
기본값 1,200초는 어느 쪽도 안 건드린다. 그리고 **검증에 성공한 판은 시간과 상관없이 안 자른다.**

## 지킬 것

1. 검증을 못 한 채 시간을 넘긴 **자동** 코드 작업은 그 자리에서 접고, 한 일을 정리해 답한다.
   ★ 2026-10-04 대표 결정으로 바뀌었다: 전에는 `code_budget_exhausted` **실패**로 끝냈다 — 22분을 일한 판이 답 한 줄 없이
   빨간 오류로 닫혔다. 이제 「덜 채우고 끝」(completion_state=partial)이고, 거짓 완료가 되지 않게 답 맨 위에
   「검증을 통과하지 못했다」를 **코드가** 붙인다(모델의 정리가 뭐라 하든).
2. **검증에 성공한 판은 안 잘린다.**
3. 사람이 지켜보는(자동 이어가기 아닌) 판은 이 상한이 안 걸린다 — 거기엔 「계속할까요?」 카드가 있다.
4. 0 이면 꺼진다.
5. 호스트는 진행 중일 때 경과 시간을 받고, 10분을 넘으면 「기다릴지 이어받을지」 판단하라는 안내를 받는다.
"""

from __future__ import annotations

import inspect
import re
import time
from pathlib import Path

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.delegation import summarize_job
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

_TOOLS = frozenset({
    "local_read_text_file", "local_index_codebase", "local_preview_page",
    "local_write_file", "local_apply_edit", "local_delete_file",
    "local_run_project_command", "browser_open", "browser_read",
})


class _Tools:
    names = set(_TOOLS)
    ollama_tools = [
        {"type": "function", "function": {"name": name, "description": name,
                                          "parameters": {"type": "object", "properties": {}}}}
        for name in sorted(_TOOLS)
    ]

    def authorize_code_workspace(self, job_id, root):
        assert job_id and root


class _Gateway:
    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, name, arguments, *, job_id=""):
        path = str(self.root / "index.html")
        if name == "local_write_file":
            (self.root / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
            return ToolResult(True, name, result={"action": name, "path": path, "verified": True, "created": True})
        if name == "local_run_project_command":
            return ToolResult(True, name, result={
                "action": name, "command": "python verify.py", "exit_code": 0, "stdout": "ok", "verified": True,
            })
        return ToolResult(True, name, result={"action": name, "path": path, "text": "x"})


def _agent(tmp_path: Path, model, *, stall: int) -> tuple[BrowserAgent, JobStore]:
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False, code_job_stall_sec=stall,
    )
    store = JobStore(tmp_path / "jarvis.db")

    class _Browser:
        def status(self):
            return {"started": True}

    return BrowserAgent(config, model, _Gateway(tmp_path), _Browser(), _Tools(), store, EventBus()), store


def _call(name: str, **arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class _NeverVerifies:
    """파일을 쓰고 브라우저만 계속 연다 — 검증을 안 한다. 두 번째 호출에서 시간을 흘려 보낸다."""

    def __init__(self, delay: float) -> None:
        self.calls = 0
        self.delay = delay

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _call("local_write_file", path="index.html", content="<h1>x</h1>")
        if self.calls == 2:
            time.sleep(self.delay)
        if self.calls > 8:
            # 상한이 꺼져 있어도 이 가짜 모델은 영원히 돌지 않는다 — 결국 말로 답한다(그러면 검증 누락으로 끝난다).
            return {"role": "assistant", "content": "만들었습니다."}
        return _call("browser_open", url="http://127.0.0.1:1/index.html")


def _run(agent: BrowserAgent, store: JobStore, tmp_path: Path, *, auto: bool = True):
    job = store.create_job("chat", "만들어줘", {"prompt": "index.html 만들고 검증해"})
    store.claim_next()
    return agent.run(
        "index.html 만들고 검증해", job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=auto,
    )


def test_an_unverified_autonomous_job_ends_with_a_diagnosis_at_the_deadline(tmp_path: Path) -> None:
    agent, store = _agent(tmp_path, _NeverVerifies(delay=1.3), stall=1)

    result = _run(agent, store, tmp_path)  # 실패로 던지지 않는다

    # 답 맨 위에 코드가 붙인 줄 — 이 가짜 모델은 정리를 한 글자도 못 쓰지만(빈 답) 그래도 사람은 사실을 받는다.
    assert result.answer.startswith("⚠")
    assert "검증을 통과하지 못했습니다" in result.answer and "index.html" in result.answer
    assert "이어서 해줘" in result.answer
    # 완료로 세지 않는다.
    assert result.verification["completion_state"] == "partial"
    assert result.verification["stop_reason"] == "wrapped_up:code_budget_exhausted"
    stop = result.verification["code_budget_exhausted"]
    assert stop["budget_sec"] == 1 and stop["elapsed_sec"] >= 1
    assert stop["mutated"] is True  # 파일은 만들었다
    assert stop["verified"] is False


class _VerifiesThenLingers:
    """검증에 성공한 뒤 시간이 상한을 넘겨도 — 성공한 판은 안 자른다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _call("local_write_file", path="index.html", content="<h1>x</h1>")
        if self.calls == 2:
            return _call("local_run_project_command", command="python verify.py")  # 검증 성공
        if self.calls == 3:
            time.sleep(1.3)  # 상한(1초)을 넘긴다
            return _call("local_read_text_file", path="index.html")
        return {"role": "assistant", "content": "검증을 돌렸고 통과했습니다."}


def test_a_verified_job_is_never_cut_however_long_it_runs(tmp_path: Path) -> None:
    agent, store = _agent(tmp_path, _VerifiesThenLingers(), stall=1)

    result = _run(agent, store, tmp_path)  # 예외 없이 끝난다

    assert result.answer.strip()


def test_a_supervised_job_is_not_subject_to_the_cap(tmp_path: Path) -> None:
    """사람이 지켜보는 판에는 「계속할까요?」 카드가 있다 — 이 상한은 자동 판만 잡는다."""
    agent, store = _agent(tmp_path, _VerifiesThenLingers(), stall=1)

    result = _run(agent, store, tmp_path, auto=False)

    assert result.answer.strip()


def test_zero_switches_the_cap_off(tmp_path: Path) -> None:
    agent, store = _agent(tmp_path, _NeverVerifies(delay=1.3), stall=0)

    # 2026-10-08: 검증 누락은 이제 예외가 아니라 접힘이다. 이 시험이 보는 것은 그대로다 — **시간 때문에** 끝나지 않는다.
    result = _run(agent, store, tmp_path)

    assert result.verification["code_budget_exhausted"] is None
    assert result.verification["stop_reason"] != "wrapped_up:code_budget_exhausted"  # 다른 이유(검증 누락 등)로 끝나는 것은 상관없다


def test_the_default_is_20_minutes_and_can_be_overridden(monkeypatch) -> None:
    assert JarvisConfig().code_job_stall_sec == 1200
    monkeypatch.setenv("JARVIS_CODE_JOB_STALL_SEC", "1800")
    assert JarvisConfig.from_env().code_job_stall_sec == 1800


# --- 호스트가 받는 것 -------------------------------------------------------------

def test_the_host_hears_why_it_stopped_and_gets_the_files() -> None:
    job = {
        "id": "j", "status": "failed", "error": "code_budget_exhausted",
        "result": {"failed": True, "error": "code_budget_exhausted",
                   "agent_trace": {"steps": [{"step": 1, "tool": "local_write_file", "ok": True}]},
                   "partial": {"files": ["index.html"], "sources": []},
                   "diagnosis": {"verified": False, "mutated": True, "elapsed_sec": 1210, "budget_sec": 1200}},
    }
    summary = summarize_job(job)

    assert summary["status"] == "failed" and summary["files"] == ["index.html"]
    assert "정해 둔 시간" in summary["message"] and "검증되지 않았습니다" in summary["message"]


def test_a_running_job_reports_how_long_it_has_been_running() -> None:
    summary = summarize_job({"id": "j", "status": "running", "started_at": 1_000.0, "result": None}, now=1_090.0)

    assert summary["status"] == "running" and summary["elapsed_sec"] == 90
    assert "분째" not in summary["message"]  # 짧으면 재촉하지 않는다


def test_a_long_running_job_tells_the_host_to_decide() -> None:
    summary = summarize_job({"id": "j", "status": "running", "started_at": 1_000.0, "result": None}, now=1_000.0 + 780)

    assert summary["elapsed_sec"] == 780
    assert "13분째" in summary["message"] and "이어받을지" in summary["message"]


def test_the_cap_is_wired_into_the_loop() -> None:
    source = inspect.getsource(BrowserAgent.run)

    assert "code_budget_exhausted" in source and "code_job_stall_sec" in source
    # 접는 줄 — 시간으로 접은 판의 이름은 그대로고, 제자리여서 접은 맡긴 판은 다른 이름을 쓴다(2026-10-09).
    fold = 'stop_reason = "wrapped_up:code_not_progressing" if stuck_why else "wrapped_up:code_budget_exhausted"'
    assert 'raise failure' not in source[source.index("code_budget_stop = {"):source.index(fold)]
    # 거짓 완료가 되지 않게 박은 셋: 답 머리말 · partial · 장부.
    assert "_code_budget_head(code_budget_stop" in source
    assert re.search(r"if code_budget_stop is not None:\s+completion_state = \"partial\"", source)
    assert '"code_budget_exhausted": code_budget_stop,' in source
    assert "not code_verification_is_current(steps)" in source, "검증에 성공한 판을 자르면 안 된다"


def test_a_verified_job_carries_no_budget_mark(tmp_path: Path) -> None:
    agent, store = _agent(tmp_path, _VerifiesThenLingers(), stall=1)

    result = _run(agent, store, tmp_path)

    assert result.verification["code_budget_exhausted"] is None
    assert not result.answer.startswith("⚠")


def test_the_head_line_is_built_from_counts_not_from_the_model() -> None:
    from alture_jarvis.agent import _code_budget_head

    head = _code_budget_head({"elapsed_sec": 1320}, ["C:/work/index.html", "C:/work/_check.py"])
    assert "약 22분" in head and "index.html, _check.py" in head and "검증되지 않음" in head
    assert "만든 파일은 없습니다" in _code_budget_head({"elapsed_sec": 30}, [])
    english = _code_budget_head({"elapsed_sec": 1320}, ["C:/work/index.html"], english=True)
    assert "did not pass verification" in english and "index.html" in english
    assert not any("가" <= ch <= "힣" for ch in english)
