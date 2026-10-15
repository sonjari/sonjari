"""접기 전 산출물 차례는 **말이 아니라 손으로** — 파일 쓰기 손만 받는다 (2026-10-02 밤 레딧 기록 판 9d6942f2).

차례를 주며 「새로 열지 말고 지금 파일을 만들어라」고 말만 했더니, 35B 가 업보트를 찾아 페이지를 더 열다 걸음을 다 써
글 6개를 읽고도 엑셀을 못 썼다(사고 R — 안내문은 안 먹는다). 차례 동안 다른 손은 되돌려 보낸다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

from test_agent import FakeBrowser


def _fn(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": name,
                                             "parameters": {"type": "object", "properties": {}}}}


class _Tools:
    names = {"browser_read", "local_write_document"}
    ollama_tools = [_fn("browser_read"), _fn("local_write_document")]


class _Gateway:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.calls: list[str] = []

    def execute(self, name, arguments, *, job_id=""):
        self.calls.append(name)
        if name == "local_write_document":
            self.out.parent.mkdir(parents=True, exist_ok=True)
            self.out.write_text("| 글 | 조회 |\n|---|---|\n| a | 1 |\n", encoding="utf-8")
            return ToolResult(True, name, result={"action": "written", "path": str(self.out), "output_path": str(self.out)})
        url = str(arguments.get("url") or f"https://www.reddit.com/p/{len(self.calls)}")
        return ToolResult(True, name, result={"action": "read", "url": url, "title": url,
                                              "char_count": 3000, "text": f"{url} 본문 " * 40})


class _Stubborn:
    """읽기만 한다 — 「파일을 만들어라」는 말은 무시하고, 도구가 「차례 규칙」으로 되돌려 보낼 때만 파일을 쓴다."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.n = 0

    def chat_messages(self, messages, **kwargs) -> dict[str, Any]:
        self.n += 1
        last = " ".join(str(m.get("content") or "") for m in messages[-2:])
        if "차례 규칙" in last:
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "local_write_document", "arguments": {"path": str(self.out), "content": "표"}}}]}
        if any("written" in str(m.get("content") or "") for m in messages[-3:]):
            return {"role": "assistant", "content": f"기록했습니다: {self.out}"}
        return {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": "browser_read", "arguments": {"url": f"https://www.reddit.com/p/{self.n}"}}}]}


def test_the_deliver_turn_refuses_other_hands_until_the_file_is_written(tmp_path) -> None:
    out = tmp_path / "out" / "reddit_log.md"
    prompt = f"레딧 글을 열어 읽고 그 내용을 {out.as_posix()} 에 기록해줘"
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60, agent_autonomous_max_steps=30)
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _Gateway(out)
    agent = BrowserAgent(config, _Stubborn(out), gateway, FakeBrowser(), _Tools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()
    agent.run(prompt, job_id=job["id"], origin="chat", must_observe=True, observe_reasons=frozenset({"web"}))
    assert "local_write_document" in gateway.calls, gateway.calls
    assert out.exists()


class _IgnoresTwice(_Stubborn):
    """레딧 판(f2bd80e7)의 35B 처럼 「차례 규칙」 거절을 두 번은 무시하고 또 열려다가, 세 번째에야 쓴다."""

    def chat_messages(self, messages, **kwargs) -> dict[str, Any]:
        refusals = sum(str(m.get("content") or "").count("차례 규칙") for m in messages)
        if 0 < refusals < 2:
            self.n += 1
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "browser_read", "arguments": {"url": f"https://www.reddit.com/again/{self.n}"}}}]}
        return super().chat_messages(messages, **kwargs)


def test_refused_steps_do_not_eat_the_deliver_turn(tmp_path) -> None:
    out = tmp_path / "out" / "reddit_log.md"
    prompt = f"레딧 글을 열어 읽고 그 내용을 {out.as_posix()} 에 기록해줘"
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60, agent_autonomous_max_steps=30)
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _Gateway(out)
    agent = BrowserAgent(config, _IgnoresTwice(out), gateway, FakeBrowser(), _Tools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()
    agent.run(prompt, job_id=job["id"], origin="chat", must_observe=True, observe_reasons=frozenset({"web"}))
    assert out.exists(), gateway.calls


def test_the_deliver_turn_allows_appending_to_a_spreadsheet() -> None:
    """레딧 기록 판(98220347): 「기존 행 아래 덧붙여」에 필요한 엑셀 덧붙이기가 차례에서 거절됐다."""
    from alture_jarvis.agent import _ARTIFACT_PROGRESS_TOOLS, _focused_tool_definitions

    tools = [_fn(name) for name in ("browser_open", "local_write_document", "local_edit_spreadsheet", "hwp_apply_edit")]
    names = {t["function"]["name"] for t in _focused_tool_definitions(tools, "artifact")}
    assert names == {"local_write_document", "local_edit_spreadsheet", "hwp_apply_edit"}
    assert "local_edit_spreadsheet" in _ARTIFACT_PROGRESS_TOOLS
