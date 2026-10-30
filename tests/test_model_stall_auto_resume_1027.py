"""모델이 제한 시간 동안 아무것도 안 내면 **자동으로 한 번** 이어 가고, 막히면 까닭을 사람 말로 한다 (2026-10-27 그룹장 실사용).

## 무엇이 있었나

외부 회사 그룹장(16GB 카드 · Swift 27B · 3ds Max/유니티)의 코드 모드: 저장소 지도 한 걸음 뒤 첫 글자가 300초 안에 안 와 판이
「모델이 제한 시간 안에 답하지 못해」로 끝났다. 그 시간이 무엇인지·왜 걸렸는지·어떻게 하면 되는지 말이 없어 「끄는 법」을 물었고,
「이어서 해줘」를 매번 보내야 했다.

## 여기서 지키는 것 (가짜 모델 · 가짜 nvidia-smi — 이 시험은 그래픽카드도 Ollama 도 안 쓴다)

1. 첫 호출이 타임아웃이면 같은 대화 그대로 **딱 한 번** 다시 부르고, 되면 판은 이어서 끝난다. 진행 줄 · 판 기록에 남는다.
2. 두 번째도 막히면 한 번만 다시 불렀고(호출 2번) 지금처럼 끝난다 — 예외에 까닭(몇 초 · 자동 재개 여부 · 카드 사정)이 달려 있다.
3. 타임아웃이 아닌 멈춤(사람 승인 대기)은 재개에 안 걸린다. 판 전체 시간 상한이 모자라면 재개하지 않는다.
4. 끝맺음 문장에 초 · 까닭 · 할 수 있는 것이 들어간다(영어판도). 「이어서 해줘」는 자동 재개를 한 뒤에는 「위를 해 본 뒤」로 바뀐다.
5. 카드 사정은 `/api/ps` 만 믿지 않는다 — 올라간 비율이 100% 여도 `nvidia-smi` 로 본 카드 전체가 가득이면 경고한다.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from alture_jarvis import agent as agent_module
from alture_jarvis import gpu_pressure
from alture_jarvis import ui_i18n
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.delegation import timeout_detail, unfinished_turn_note
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ApprovalRequired, JobStore
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


def _agent(tmp_path: Path, model: Any, **config: Any) -> tuple[BrowserAgent, JobStore]:
    base = dict(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
    )
    store = JobStore(tmp_path / "jarvis.db")

    class _Browser:
        def status(self):
            return {"started": True}

    return BrowserAgent(JarvisConfig(**{**base, **config}), model, _Gateway(tmp_path), _Browser(), _Tools(), store, EventBus()), store


def _call(name: str, **arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def _stall(phase: str = "no_first_token") -> httpx.ReadTimeout:
    exc = httpx.ReadTimeout("timed out")
    exc.jarvis_wait = {"phase": phase, "limit_sec": 300.0, "waited_sec": 300.0}
    return exc


class _TimesOutFirst:
    """앞의 `timeouts` 번은 타임아웃, 그 뒤로는 쓰기 → 검증 → 마무리."""

    def __init__(self, timeouts: int) -> None:
        self.calls = 0
        self.timeouts = timeouts

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.timeouts:
            raise _stall()
        step = self.calls - self.timeouts
        if step == 1:
            return _call("local_write_file", path="index.html", content="<h1>x</h1>")
        if step == 2:
            return _call("local_run_project_command", command="python verify.py")
        return {"role": "assistant", "content": "만들었고 검증했습니다."}


def _run(agent: BrowserAgent, store: JobStore, tmp_path: Path):
    job = store.create_job("chat", "만들어줘", {"prompt": "index.html 만들고 검증해"})
    store.claim_next()
    return job["id"], lambda: agent.run(
        "index.html 만들고 검증해", job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True,
    )


def _progress_lines(agent: BrowserAgent) -> list[str]:
    return [str(e.payload.get("message") or "") for e in agent.events.get_since(0, 500) if e.event == "agent_progress"]


# --- ① 자동으로 한 번 이어 가기 ---------------------------------------------------

def test_one_stall_is_resumed_once_and_the_job_finishes(tmp_path: Path) -> None:
    model = _TimesOutFirst(timeouts=1)
    agent, store = _agent(tmp_path, model)
    job_id, run = _run(agent, store, tmp_path)

    result = run()  # 예외 없이 끝난다

    assert result.answer.strip()
    assert model.calls >= 4  # 막힌 1번 + 다시 1번 + 쓰기 + 검증(+ 마무리 검토) — 타임아웃은 앞의 1번뿐
    assert any("300초 동안 답이 없어 한 번 다시 이어 갑니다" in line for line in _progress_lines(agent))
    assert result.verification["stall_resume"]["phase"] == "no_first_token"  # 판 기록에 남는다
    assert any(e.event == "agent_model_stall_resumed" for e in agent.events.get_since(0, 500))


def test_a_second_stall_ends_the_job_after_exactly_one_retry(tmp_path: Path) -> None:
    model = _TimesOutFirst(timeouts=5)
    agent, store = _agent(tmp_path, model)
    _job_id, run = _run(agent, store, tmp_path)

    with pytest.raises(httpx.ReadTimeout) as caught:
        run()

    assert model.calls == 2  # 무한 반복 없음: 처음 + 딱 한 번
    wait = caught.value.jarvis_wait
    assert wait["auto_resumed"] is True and wait["phase"] == "no_first_token" and wait["limit_sec"] == 300.0
    assert caught.value.diagnosis["model_wait"]["auto_resumed"] is True  # 판 실패 기록(`_attach_failure_trace`)이 읽는다


def test_a_person_wait_is_not_a_stall(tmp_path: Path) -> None:
    class _AsksForApproval:
        calls = 0

        def chat_messages(self, messages, **kwargs):
            _AsksForApproval.calls += 1
            raise ApprovalRequired("nonce-1")

    agent, store = _agent(tmp_path, _AsksForApproval())
    _job_id, run = _run(agent, store, tmp_path)

    with pytest.raises(ApprovalRequired):
        run()

    assert _AsksForApproval.calls == 1  # 다시 부르지 않았다
    assert not agent.__dict__.get("_stall_resumes")


def test_no_resume_when_it_would_pass_the_whole_job_time_cap(tmp_path: Path) -> None:
    """다시 부르면 최악에 300초 더 기다린다 — 판 전체 시간 상한(`agent_autonomous_lease_sec`)을 넘기면 하지 않는다."""
    model = _TimesOutFirst(timeouts=1)
    agent, store = _agent(tmp_path, model, agent_autonomous_lease_sec=120)
    _job_id, run = _run(agent, store, tmp_path)

    with pytest.raises(httpx.ReadTimeout) as caught:
        run()

    assert model.calls == 1
    assert caught.value.jarvis_wait["auto_resumed"] is False


def test_a_cancelled_job_is_not_resumed(tmp_path: Path) -> None:
    model = _TimesOutFirst(timeouts=1)
    agent, store = _agent(tmp_path, model)
    job_id, _run_job = _run(agent, store, tmp_path)
    agent._cancelled = lambda _job_id: True  # type: ignore[method-assign]

    assert agent._may_resume_after_stall(job_id, None, 300.0) is False


def test_only_one_resume_per_job(tmp_path: Path) -> None:
    agent, _store = _agent(tmp_path, _TimesOutFirst(timeouts=0))
    assert agent._may_resume_after_stall("job-a", time.monotonic(), 300.0) is True
    agent.__dict__["_stall_resumes"] = {"job-a": {"phase": "x"}}
    assert agent._may_resume_after_stall("job-a", time.monotonic(), 300.0) is False
    assert agent._may_resume_after_stall("job-b", time.monotonic(), 300.0) is True  # 다른 판은 새로 한 번


# --- 카드가 가득이면 다시 부르지 않는다 (2026-10-27 · 그룹장 PC) ----------------------------

def _with_card(agent: BrowserAgent, **facts: Any) -> None:
    """멈춘 그때 본 카드 사정을 못 박는다(진짜 nvidia-smi 는 안 부른다)."""
    agent._gpu_facts = lambda model_role="chat": dict(facts)  # type: ignore[method-assign]


def test_a_full_card_means_no_retry_and_the_reason_is_recorded(tmp_path: Path) -> None:
    model = _TimesOutFirst(timeouts=5)
    agent, store = _agent(tmp_path, model)
    _with_card(agent, gpu_share=1.0, card_full=True, card_used_gb=15.9, card_total_gb=15.92)
    job_id, run = _run(agent, store, tmp_path)

    with pytest.raises(httpx.ReadTimeout) as caught:
        run()

    assert model.calls == 1  # 다시 부르지 않았다 — 또 300초를 기다리지 않는다
    wait = caught.value.jarvis_wait
    assert wait["auto_resumed"] is False and wait["resume_skipped"] == "card_full"
    assert caught.value.diagnosis["model_wait"]["resume_skipped"] == "card_full"  # 판 실패 기록에 「재시도 안 한 까닭」
    assert not agent.__dict__.get("_stall_resumes")
    assert agent.__dict__["_stall_resume_skipped"][job_id]["reason"] == "card_full"
    assert any(e.event == "agent_model_stall_not_resumed" for e in agent.events.get_since(0, 500))
    assert not any("한 번 다시 이어 갑니다" in line for line in _progress_lines(agent))


def test_the_end_note_tells_what_to_do_first_when_the_card_was_full() -> None:
    wait = {"phase": "no_first_token", "limit_sec": 300.0, "auto_resumed": False, "resume_skipped": "card_full",
            "card_full": True, "card_used_gb": 15.9, "card_total_gb": 15.92}
    note = unfinished_turn_note("timed out", cancelled=False, files=[], sources=[], wait=wait)

    assert "그래픽카드가 가득 차 있어 다시 불러도 같은 자리에서 멈출 가능성이 큽니다" in note
    assert "다른 프로그램(3ds Max · 유니티 등)을 먼저 닫은 뒤 「이어서 해줘」" in note
    assert note.index("가득 차 있어 다시 불러도") < note.index("끌 수 없습니다") < note.index("15.9/15.92GB")  # 할 일이 먼저
    assert "자동으로 한 번 다시 이어 갔지만" not in note  # 안 이어 갔다
    assert note.rstrip(")").endswith("위를 해 본 뒤 「이어서 해줘」라고 보내면 여기서 이어갑니다.")
    english = unfinished_turn_note("timed out", cancelled=False, files=[], sources=[], english=True, wait=wait)
    assert not any("가" <= ch <= "힣" for ch in english), english
    assert "would likely stall at the same place" in english and "I did not retry automatically" in english


@pytest.mark.parametrize("card_full", [False, None])
def test_a_roomy_or_unreadable_card_still_gets_exactly_one_retry(tmp_path: Path, card_full) -> None:
    model = _TimesOutFirst(timeouts=1)
    agent, store = _agent(tmp_path, model)
    facts = {"gpu_share": 1.0}
    if card_full is False:
        facts.update(card_full=False, card_used_gb=9.1, card_total_gb=15.92)  # None 이면 키 자체가 없다(nvidia-smi 실패)
    _with_card(agent, **facts)
    _job_id, run = _run(agent, store, tmp_path)

    result = run()

    assert result.answer.strip() and model.calls >= 4  # 지금처럼 한 번 다시 불러 끝까지 갔다
    assert result.verification["stall_resume"]["phase"] == "no_first_token"
    assert not agent.__dict__.get("_stall_resume_skipped")


def test_may_resume_after_stall_respects_card_full_directly(tmp_path: Path) -> None:
    agent, _store = _agent(tmp_path, _TimesOutFirst(timeouts=0))
    assert agent._may_resume_after_stall("j", time.monotonic(), 300.0, True) is False
    assert agent._may_resume_after_stall("j", time.monotonic(), 300.0, False) is True
    assert agent._may_resume_after_stall("j", time.monotonic(), 300.0, None) is True
    assert agent._may_resume_after_stall("j", time.monotonic(), 300.0) is True  # 옛 호출 모양도 그대로


# --- ② 막힌 까닭을 사람 말로 -------------------------------------------------------

def test_the_end_note_says_what_how_long_why_and_what_to_do() -> None:
    wait = {"phase": "no_first_token", "limit_sec": 300.0, "auto_resumed": True,
            "gpu_share": 1.0, "card_full": True, "card_used_gb": 15.9, "card_total_gb": 15.92}
    note = unfinished_turn_note("timed out", cancelled=False, files=[], sources=[], wait=wait)

    assert "제한 시간" in note
    assert "첫 글자를 300초 동안" in note                      # 무엇이 몇 초 안 왔나
    assert "끌 수 없습니다" in note                            # 「끄기」 요청에 정직한 답
    assert "자동으로 한 번 다시 이어 갔지만" in note
    assert "15.9/15.92GB" in note and "조용히 밀어" in note     # 카드 사정(/api/ps 는 100% 라도)
    assert "3ds Max" in note and "상한 재기" in note and "더 작은 모델" in note  # 할 수 있는 것
    assert "손자리는 다른 프로그램을 끄지 않습니다" in note
    assert note.rstrip(")").endswith("위를 해 본 뒤 「이어서 해줘」라고 보내면 여기서 이어갑니다.")  # 이어서 안내는 맨 마지막


def test_the_note_without_an_auto_resume_keeps_the_plain_continue_line() -> None:
    wait = {"phase": "mid_stream", "limit_sec": 300.0, "auto_resumed": False}
    note = unfinished_turn_note("timed out", cancelled=False, files=[], sources=[], wait=wait)

    assert "답을 쓰던 도중 300초 동안 새 글자가 오지 않았습니다" in note
    assert note.rstrip(")").endswith("「이어서 해줘」라고 보내면 여기서 이어갑니다.")
    assert "위를 해 본 뒤" not in note
    assert "안 들어갔거나" in note and "있을 수 있습니다" in note  # 카드 사정을 모를 때는 「~일 수 있습니다」


def test_an_unknown_wait_keeps_the_old_one_liner() -> None:
    """예외에 아무것도 안 달린 옛 길(비 에이전트 대화 등)은 예전 문장 그대로다."""
    note = unfinished_turn_note("timed out", cancelled=False, files=[], sources=[])

    assert "제한 시간" in note and "해 볼 것" not in note and "이어서 해줘" in note


def test_the_cpu_spill_and_a_roomy_card_are_told_apart() -> None:
    spill = timeout_detail({"phase": "no_first_token", "limit_sec": 300.0, "gpu_share": 0.62})
    roomy = timeout_detail({"phase": "no_first_token", "limit_sec": 300.0, "gpu_share": 1.0,
                            "card_full": False, "card_used_gb": 9.1, "card_total_gb": 15.92})

    assert "약 38%가 그래픽카드 밖(CPU)" in spill
    assert "여유가 있었습니다(사용 9.1/15.92GB)" in roomy and "가득" not in roomy


def test_a_connect_timeout_points_at_ollama_not_the_graphics_card() -> None:
    text = timeout_detail({"phase": "connect", "limit_sec": 10.0})

    assert "Ollama" in text and "그래픽카드" not in text and "끌 수 없습니다" not in text


def test_the_english_note_is_english_only() -> None:
    wait = {"phase": "no_first_token", "limit_sec": 300.0, "auto_resumed": True, "card_full": True,
            "card_used_gb": 15.9, "card_total_gb": 15.92}
    note = unfinished_turn_note("timed out", cancelled=False, files=[], sources=[], english=True, wait=wait)

    assert not any("가" <= ch <= "힣" for ch in note), note
    assert "no first character for 300 seconds" in note and "Measure limit" in note and "I do not close them" in note
    assert 'After trying the above, send "continue"' in note


def test_the_host_summary_gets_the_same_words() -> None:
    from alture_jarvis.delegation import summarize_job

    job = {"id": "j", "status": "failed", "error": "timed out",
           "result": {"failed": True, "error": "timed out", "agent_trace": {"steps": []},
                      "diagnosis": {"model_wait": {"phase": "no_first_token", "limit_sec": 300.0, "auto_resumed": True}}}}
    message = summarize_job(job)["message"]

    assert "첫 글자를 300초 동안" in message and "자동으로 한 번 다시 이어 갔지만" in message


# --- 카드 사정: /api/ps 만 믿지 않는다 ----------------------------------------------

def _smi(used_mib: int, total_mib: int = 16303):
    def run(args, **kwargs):
        assert args[0] == "nvidia-smi" and kwargs["timeout"] <= 4  # 카드가 바빠도 첫 걸음을 오래 붙잡지 않는다
        return SimpleNamespace(returncode=0, stdout=f"0, NVIDIA GeForce RTX 5080, {total_mib}, {used_mib}, 560.94, Enabled\n", stderr="")
    return run


class _PsSaysAllLoaded:
    """Ollama 는 다 올렸다고 보고한다(윈도우는 남이 쥔 몫을 못 본다)."""

    def __init__(self, size_gb: float = 14.0, vram_gb: float = 14.0) -> None:
        self.size, self.vram = int(size_gb * 2**30), int(vram_gb * 2**30)

    def health(self, *, role: str = "chat", **_):
        return {"ok": True, "size": self.size, "size_vram": self.vram}


def _gpu_agent(tmp_path: Path, monkeypatch, model: Any, smi: Any) -> BrowserAgent:
    monkeypatch.setattr(agent_module, "read_card", gpu_pressure.read_card)  # conftest 가 막아 둔 것을 이 시험에서만 되돌린다
    agent, _store = _agent(tmp_path, model)
    agent._nvidia_run = smi
    return agent


def test_a_full_card_warns_even_when_ps_says_everything_is_loaded(tmp_path: Path, monkeypatch) -> None:
    agent = _gpu_agent(tmp_path, monkeypatch, _PsSaysAllLoaded(), _smi(used_mib=16200))  # 남은 0.1GiB

    agent._warn_if_model_spills("job-1", "code")

    line = next(line for line in _progress_lines(agent) if "그래픽카드 메모리가 거의 가득" in line)
    assert "(15.82/15.92GB)" in line and "3ds Max" in line and "손자리는 다른 프로그램을 끄지 않습니다" in line
    facts = agent.__dict__["_model_spill"]["job-1"]
    assert facts["gpu_share"] == 1.0 and facts["card_full"] is True  # /api/ps 는 100% 인데 카드는 가득
    assert any(e.event == "agent_model_spill" for e in agent.events.get_since(0, 100))


def test_a_card_with_room_says_nothing(tmp_path: Path, monkeypatch) -> None:
    agent = _gpu_agent(tmp_path, monkeypatch, _PsSaysAllLoaded(), _smi(used_mib=13000))  # 남은 3.2GiB

    agent._warn_if_model_spills("job-1", "code")

    assert not [line for line in _progress_lines(agent) if "그래픽카드" in line]
    assert agent.__dict__["_model_spill"]["job-1"]["card_full"] is False


def test_part_of_the_model_outside_the_card_warns_from_ps(tmp_path: Path, monkeypatch) -> None:
    agent = _gpu_agent(tmp_path, monkeypatch, _PsSaysAllLoaded(size_gb=20.0, vram_gb=12.0), _smi(used_mib=13000))

    agent._warn_if_model_spills("job-1", "code")

    assert any("모델 일부(40%)가 그래픽카드에 안 들어가" in line for line in _progress_lines(agent))


def test_a_full_card_warns_before_the_model_is_even_loaded(tmp_path: Path, monkeypatch) -> None:
    class _NothingLoaded:
        def health(self, *, role="chat", **_):
            return {"ok": True, "size": 0, "size_vram": 0}

    agent = _gpu_agent(tmp_path, monkeypatch, _NothingLoaded(), _smi(used_mib=16000))

    agent._warn_if_model_spills("job-1", "code")

    assert any("그래픽카드 메모리가 거의 가득" in line for line in _progress_lines(agent))


def test_no_nvidia_smi_and_no_ps_means_silence_not_a_guess(tmp_path: Path, monkeypatch) -> None:
    class _Dead:
        def health(self, **_):
            raise RuntimeError("down")

    def missing(args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    agent = _gpu_agent(tmp_path, monkeypatch, _Dead(), missing)

    agent._warn_if_model_spills("job-1", "code")  # 예외 없이

    assert not [line for line in _progress_lines(agent) if "그래픽카드" in line]


def test_the_late_hint_blames_the_card_only_when_the_card_is_full_or_unreadable(tmp_path: Path, monkeypatch) -> None:
    full = _gpu_agent(tmp_path, monkeypatch, _PsSaysAllLoaded(), _smi(used_mib=16200))
    assert "그래픽카드 메모리가 모자라 느려진 것 같습니다" in full._late_gpu_hint("j", "code")
    assert "손자리는 다른 프로그램을 끄지 않습니다" in full._late_gpu_hint("j", "code")  # 같은 판은 한 번 묻고 그 글을 쓴다

    roomy = _gpu_agent(tmp_path, monkeypatch, _PsSaysAllLoaded(), _smi(used_mib=9000))
    assert roomy._late_gpu_hint("j", "code") == ""  # 카드에 여유가 있으면 카드 탓이 아니다

    def missing(args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    blind = _gpu_agent(tmp_path, monkeypatch, _PsSaysAllLoaded(), missing)
    hedged = blind._late_gpu_hint("j", "code")
    assert "평소보다 많이 늦습니다" in hedged and "모자랐을 수 있습니다" in hedged  # 결과만 보고 「~일 수 있습니다」


def test_the_progress_lines_have_english(tmp_path: Path) -> None:
    ui_i18n.configure(tmp_path / "lang.json")
    ui_i18n.set_lang("en")
    try:
        lines = [
            "모델이 300초 동안 답이 없어 한 번 다시 이어 갑니다",
            "모델이 제한 시간 동안 답이 없어 한 번 다시 이어 갑니다",
            "모델 일부(40%)가 그래픽카드에 안 들어가 느릴 수 있습니다 — 그래픽카드를 쓰는 다른 프로그램을 닫거나, "
            "모델 이름 버튼의 「상한 재기」 · 더 작은 모델을 써 보세요. 손자리는 다른 프로그램을 끄지 않습니다",
            "그래픽카드 메모리가 거의 가득 찼습니다(15.82/15.92GB) — 모델이 아주 느려질 수 있습니다. 다른 프로그램(3ds Max · 유니티 등)을 "
            "닫거나 모델 이름 버튼에서 더 작은 모델을 써 보세요. 손자리는 다른 프로그램을 끄지 않습니다",
        ]
        shown = [ui_i18n.translate_text(line) for line in lines]
    finally:
        ui_i18n.set_lang("ko")
    assert not [text for text in shown if any("가" <= ch <= "힣" for ch in text)], shown
    assert "300 seconds" in shown[0] and "(40%)" in shown[2] and "15.82/15.92GB" in shown[3]


# --- 늦음 기준 ------------------------------------------------------------------

def test_late_after_uses_this_pcs_usual_speed_or_falls_back_to_a_minute(tmp_path: Path) -> None:
    import json

    path = tmp_path / "model_calls.jsonl"
    rows = [{"model": "swift-27b", "prompt_tokens": 20_000, "prefill_sec": 10.0, "load_sec": 0.0} for _ in range(6)]
    rows.append({"model": "swift-27b", "prompt_tokens": 20_000, "prefill_sec": 0.6, "load_sec": 12.0})  # 모델을 올린 부르기는 뺀다
    rows.append({"model": "other-model", "prompt_tokens": 20_000, "prefill_sec": 100.0, "load_sec": 0.0})
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    rate = gpu_pressure.usual_prefill_rate(tmp_path, "swift-27b")
    assert rate == pytest.approx(2000.0)
    assert gpu_pressure.late_after_sec(20_000, rate) == pytest.approx(30.0)   # 어림 10초의 3배 = 30초 (바닥 30초)
    assert gpu_pressure.late_after_sec(100_000, rate) == pytest.approx(150.0)  # 어림 50초의 3배
    assert gpu_pressure.usual_prefill_rate(tmp_path, "never-seen") is None    # 기록이 모자라면 모른다
    assert gpu_pressure.late_after_sec(20_000, None) == gpu_pressure.UNKNOWN_LATE_SEC


# --- 대화에 남는 글까지 이어졌나 (runtime 의 실패 기록 자리) --------------------------------

def test_the_conversation_keeps_the_new_sentence(tmp_path: Path) -> None:
    from alture_jarvis.memory import ConversationMemory
    from alture_jarvis.runtime import JarvisRuntime

    class _Store:
        def get_job(self, job_id):
            return {"id": job_id, "result": {}}

    class _Fake:
        pass

    memory = ConversationMemory(tmp_path / "m.db")
    fake = _Fake()
    fake.memory, fake.store = memory, _Store()
    fake._session_id = lambda payload: "s1"
    exc = _stall()
    exc.jarvis_wait = {**exc.jarvis_wait, "auto_resumed": True, "card_full": True, "card_used_gb": 15.9, "card_total_gb": 15.92}
    job = {"id": "job-1", "kind": "chat", "payload": {"prompt": "제한 시간 안에 못 끝낸 거 어떻게 꺼?", "session_id": "s1"}}

    JarvisRuntime._record_unfinished_turn(fake, job, exc)

    answer = memory.recent("s1")[1]["content"]
    assert "첫 글자를 300초 동안" in answer and "15.9/15.92GB" in answer and "상한 재기" in answer
    assert answer.rstrip(")").endswith("「이어서 해줘」라고 보내면 여기서 이어갑니다.")
