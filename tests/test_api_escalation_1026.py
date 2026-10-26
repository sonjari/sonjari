"""막히면 내 API 키로 클로드에게 한 번 묻기 — 가짜 클라이언트로만 잰다(진짜 호출 없음) (2026-10-26).

설계: `docs/설계_혼합_로컬API승급_2026-10-26.ko.md`. 지키는 것: 실패 신호에서만 · 기본 꺼짐 · 측정 판 꺼짐 · 판마다 1번 ·
달 상한 · 영수증 셋 · 키 값은 어디에도 안 찍힘 · 넘기기(`claude_code.py`)와 섞지 않음.
"""
from __future__ import annotations

import inspect
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import agent, api_escalation as esc
from alture_jarvis.settings import unavailable_reason

FAKE_KEY = "sk-ant-api03-" + "x" * 40 + "WXYZ"


class _Messages:
    def __init__(self, owner: "_Client", beta: bool) -> None:
        self.owner, self.beta = owner, beta

    def create(self, **kwargs: Any) -> Any:
        self.owner.calls.append(("beta" if self.beta else "plain", kwargs))
        if self.owner.raise_on and (self.beta or self.owner.raise_on == "any"):
            raise self.owner.raise_with
        return self.owner.response


class _Client:
    def __init__(self, response: Any = None, raise_on: str = "", raise_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.response = response or SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="쿠팡 상세 페이지를 열어 가격 칸을 읽어라.")],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=0),
            stop_reason="end_turn",
            model="claude-opus-5-5",
        )
        self.raise_on, self.raise_with = raise_on, raise_with or RuntimeError("boom")
        self.messages = _Messages(self, beta=False)
        self.beta = SimpleNamespace(messages=_Messages(self, beta=True))


def _config(tmp_path: Path, **over: Any) -> SimpleNamespace:
    values = {"data_dir": tmp_path, "api_escalation_enabled": True, "api_escalation_model": "claude-opus-5-5",
              "api_escalation_monthly_usd": 3}
    values.update(over)
    return SimpleNamespace(**values)


def _helper(tmp_path: Path, client: _Client, *, key: bool = True, sdk: bool = True, **over: Any) -> esc.ApiEscalation:
    config = _config(tmp_path, **over)
    if key:
        esc.save_key(config, FAKE_KEY)
    seen_keys: list[str] = []

    def factory(api_key: str) -> _Client:
        seen_keys.append(api_key)
        return client

    helper = esc.ApiEscalation(config, client_factory=factory, sdk_check=lambda: sdk, clock=lambda: time.time())
    helper.seen_keys = seen_keys  # type: ignore[attr-defined]
    return helper


def _ledger(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / esc.LEDGER_NAME
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


# ── 부르기 · 돈 · 영수증 ────────────────────────────────────────────────

def test_opus_call_uses_default_fallbacks_low_effort_and_counts_money(tmp_path: Path) -> None:
    client = _Client()
    helper = _helper(tmp_path, client)
    entry = helper.ask("job1", "pushback_stalled", "막힌 자리 요약")
    assert entry.called and entry.ok and "쿠팡" in entry.advice
    kind, request = client.calls[0]
    assert kind == "beta"
    assert request["model"] == "claude-opus-5-5" and request["max_tokens"] == esc.MAX_OUTPUT_TOKENS
    assert request["betas"] == ["server-side-fallback-2026-07-01"] and request["fallbacks"] == "default"
    assert request["output_config"] == {"effort": "low"}
    # 2026-10-21 부터 400 인 값 · Opus 5.5 에서 400 인 생각 끄기는 보내지 않는다.
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(request)
    # 1,000 입력 × $4 + 200 출력 × $20 (100만 토큰당) = $0.008
    assert entry.usd == pytest.approx(0.008)
    assert helper.seen_keys == [FAKE_KEY]  # type: ignore[attr-defined]
    row = _ledger(tmp_path)[-1]
    assert row["called"] and row["usd"] == pytest.approx(0.008) and row["input_tokens"] == 1000
    sent = Path(row["sent_file"]).read_text(encoding="utf-8")
    assert "막힌 자리 요약" in sent
    # 키 값은 장부 · 보낸 글 파일 어디에도 없다.
    assert FAKE_KEY not in (tmp_path / esc.LEDGER_NAME).read_text(encoding="utf-8") and FAKE_KEY not in sent
    line = esc.receipt_line(helper.entries("job1"))
    assert esc.RECEIPT_MARK in line and "Claude Opus 5.5" in line and "$0.008" in line and "보낸 것은" in line
    answer = esc.with_receipt("답입니다", helper.entries("job1"))
    assert answer.endswith(line) and esc.with_receipt(answer, helper.entries("job1")) == answer


def test_haiku_gets_no_fallbacks(tmp_path: Path) -> None:
    client = _Client()
    helper = _helper(tmp_path, client, api_escalation_model="claude-haiku-5-5")
    helper.ask("job1", "pushback_stalled", "요약")
    kind, request = client.calls[0]
    assert kind == "plain" and "fallbacks" not in request and "betas" not in request


def test_old_sdk_without_fallbacks_argument_retries_plain(tmp_path: Path) -> None:
    client = _Client(raise_on="beta", raise_with=TypeError("unexpected keyword 'fallbacks'"))
    helper = _helper(tmp_path, client)
    entry = helper.ask("job1", "pushback_stalled", "요약")
    assert [k for k, _ in client.calls] == ["beta", "plain"] and entry.ok
    assert entry.extra.get("fallbacks") == "sdk_unsupported"


def test_refusal_and_errors_do_not_inject_advice_or_crash(tmp_path: Path) -> None:
    refused = _Client(response=SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=900, output_tokens=0),
                                               stop_reason="refusal", model="claude-opus-5-5"))
    entry = _helper(tmp_path / "a", refused).ask("job1", "pushback_stalled", "요약")
    assert entry.called and not entry.ok and entry.error == "refusal" and entry.advice == ""
    broken = _Client(raise_on="any", raise_with=ConnectionError("down"))
    entry = _helper(tmp_path / "b", broken).ask("job1", "pushback_stalled", "요약")
    assert entry.called and not entry.ok and entry.error == "ConnectionError"
    assert "답을 못 받았습니다(ConnectionError)" in esc.receipt_line([entry])


# ── 부르지 않는 까닭 ────────────────────────────────────────────────────

def test_switched_off_never_calls_and_leaves_no_ledger_line(tmp_path: Path) -> None:
    client = _Client()
    helper = _helper(tmp_path, client, api_escalation_enabled=False)
    entry = helper.ask("job1", "pushback_stalled", "요약")
    assert not entry.called and entry.skip == "switched_off" and client.calls == []
    assert _ledger(tmp_path) == [] and esc.receipt_line(helper.entries("job1")) == ""


@pytest.mark.parametrize("over, key, sdk, expected", [
    ({}, False, True, "no_key"),
    ({}, True, False, "no_sdk"),
])
def test_missing_key_or_sdk_blocks(tmp_path: Path, over: dict[str, Any], key: bool, sdk: bool, expected: str) -> None:
    client = _Client()
    entry = _helper(tmp_path, client, key=key, sdk=sdk, **over).ask("job1", "pushback_stalled", "요약")
    assert entry.skip == expected and client.calls == []
    assert _ledger(tmp_path)[-1]["skip"] == expected  # 부르지 **않은** 까닭도 장부에 남는다


def test_one_call_per_job(tmp_path: Path) -> None:
    client = _Client()
    helper = _helper(tmp_path, client)
    assert helper.ask("job1", "pushback_stalled", "요약").called
    second = helper.ask("job1", "pushback_stalled", "요약")
    assert not second.called and second.skip == "per_job_limit" and len(client.calls) == 1
    assert helper.ask("job2", "pushback_stalled", "요약").called  # 다른 판은 따로 센다


def test_monthly_cap_stops_before_spending(tmp_path: Path) -> None:
    month = time.strftime("%Y-%m")
    (tmp_path / esc.LEDGER_NAME).write_text(
        json.dumps({"month": month, "called": True, "usd": 2.98}) + "\n"
        + json.dumps({"month": "1999-01", "called": True, "usd": 100}) + "\n",  # 지난달은 세지 않는다
        encoding="utf-8",
    )
    client = _Client()
    entry = _helper(tmp_path, client).ask("job1", "pushback_stalled", "요약 " * 2000)
    assert entry.skip == "monthly_cap" and client.calls == []
    assert esc.month_spent(tmp_path, time.time()) == pytest.approx(2.98)


def test_measurement_and_claude_delegated_jobs_are_held(tmp_path: Path) -> None:
    assert esc.hold_reason({"measurement": True}) == "measurement_flag"
    assert esc.hold_reason({"caller": "bench-om2w"}) == "measurement_caller"
    assert esc.hold_reason({}, "code-repo-bench-3") == "measurement_session"
    assert esc.hold_reason({"origin": "mcp", "caller": "claude-code"}) == "delegated_by_claude_code"
    assert esc.hold_reason({"origin": "console"}) == ""
    # 재는 스크립트만 따로 푼다 — 클로드가 맡긴 판은 풀지 않는다.
    assert esc.hold_reason({"measurement": True, "api_escalation_measure": True}) == ""
    assert esc.hold_reason({"origin": "mcp", "caller": "claude-code", "api_escalation_measure": True}) == "delegated_by_claude_code"
    client = _Client()
    helper = _helper(tmp_path, client)
    helper.hold_for_job("job1", "measurement_flag")
    entry = helper.ask("job1", "pushback_stalled", "요약")
    assert not entry.called and entry.skip == "measurement_flag" and client.calls == []


# ── 보낼 글 ────────────────────────────────────────────────────────────

def test_brief_is_capped_and_redacted() -> None:
    steps = [{"tool": "browser_read", "arguments": {"url": f"https://shop.example/{i}"}, "observation": "가격 " * 400}
             for i in range(40)]
    prompt = (r"C:\Users\user\문서\견적.xlsx 를 열어 garam@example.com 010-1234-5678 로 정리 "
              + FAKE_KEY + " " + "요청 " * 3000)
    brief = esc.build_brief(prompt, ["가격 3개", "파일 만들기"], steps, "초안 " * 2000)
    assert len(brief) <= esc.MAX_SEND_CHARS
    assert "user" not in brief and "garam@example.com" not in brief and "010-1234-5678" not in brief and FAKE_KEY not in brief
    assert "견적.xlsx" in brief  # 파일 이름은 남기고 사용자 폴더만 가린다
    assert "## 아직 못 채운 요구" in brief and "- 가격 3개" in brief
    assert "전체 40걸음 중 마지막" in brief


def test_worst_case_is_never_below_a_plausible_real_bill() -> None:
    # 20,000자 → 최악 어림 입력 ~8K 토큰 + 출력 2,000 = Opus 기준 약 $0.07
    worst = esc.worst_case_usd("claude-opus-5-5", 20_000)
    assert 0.06 < worst < 0.09
    assert esc.worst_case_usd("claude-haiku-5-5", 20_000) < 0.01


# ── 키 ─────────────────────────────────────────────────────────────────

class _Clip:
    def __init__(self, text: str) -> None:
        self.text, self.cleared = text, False

    def read(self) -> str:
        return self.text

    def clear(self) -> None:
        self.text, self.cleared = "", True


def test_key_comes_only_from_clipboard_and_is_never_echoed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    wrong = _Clip("hunter2 my password")
    result = esc.key_from_clipboard(config, wrong)
    assert result == {"ok": False, "error": "not_an_api_key"} and not esc.has_key(config) and not wrong.cleared
    assert esc.key_from_clipboard(config, _Clip("sk-ant-admin01-" + "y" * 40))["error"] == "not_an_api_key"
    clip = _Clip(FAKE_KEY)
    result = esc.key_from_clipboard(config, clip)
    assert result["ok"] and result["masked"] == "…WXYZ" and clip.cleared and FAKE_KEY not in json.dumps(result)
    assert esc.has_key(config) and esc.load_key(config) == FAKE_KEY
    raw = (tmp_path / esc.KEY_FILE).read_bytes()
    if __import__("os").name == "nt":
        assert FAKE_KEY.encode() not in raw  # DPAPI 로 감쌌다
    status = esc.key_status(config)
    assert status["has_key"] and FAKE_KEY not in json.dumps(status) and "WXYZ" not in json.dumps(status)
    assert esc.clear_key(config) and not esc.has_key(config)


def test_environment_key_is_not_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """다른 프로그램용으로 깔아 둔 환경변수 키로 몰래 돈이 나가면 안 된다 — 손자리에 넣은 키만."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-" + "e" * 40)
    client = _Client()
    entry = _helper(tmp_path, client, key=False).ask("job1", "pushback_stalled", "요약")
    assert entry.skip == "no_key" and client.calls == []
    assert "api_key=api_key" in inspect.getsource(esc._default_client)


def test_settings_cannot_switch_on_without_sdk_or_key(tmp_path: Path) -> None:
    config = _config(tmp_path)
    reason = unavailable_reason("api_escalation_enabled", config)
    assert reason in {"no_sdk", "no_key"}  # 이 PC 의 venv 에는 아직 anthropic 이 없다 — 어느 쪽이든 켤 수 없다


# ── 루프 연결 · 넘기기와 분리 ──────────────────────────────────────────

def test_loop_asks_only_at_the_stalled_pushback() -> None:
    source = inspect.getsource(agent)
    assert source.count("self._api_escalation_advice(") == 1, "실패 신호 한 자리에서만 — 예측 갈래 없음"
    block = source[source.index('"agent_plan_pushback_stalled",'):]
    block = block[: block.index("if (\n")]
    assert "advice = self._api_escalation_advice(job_id, prompt, [u[0] for u in unmet_now], steps, answer)" in block
    assert "messages.append({\"role\": \"user\", \"content\": advice_message(advice)})" in block
    assert "step_limit = max(step_limit, len(steps) + 3)" in block and "continue" in block


def test_agent_helper_returns_advice_only_when_ok() -> None:
    calls: list[tuple[str, str]] = []

    class Stub:
        def __init__(self, entry: Any, on: bool = True) -> None:
            self.entry, self.on = entry, on

        def switched_on(self) -> bool:
            return self.on

        def ask(self, job_id: str, reason: str, brief: str) -> Any:
            calls.append((job_id, reason))
            return self.entry

    bare = agent.BrowserAgent.__new__(agent.BrowserAgent)
    bare.api_escalation = None
    assert bare._api_escalation_advice("j", "p", [], [], "") == ""
    bare.api_escalation = Stub(SimpleNamespace(ok=True, advice="이렇게 해라"), on=False)
    assert bare._api_escalation_advice("j", "p", [], [], "") == "" and calls == []
    bare.api_escalation = Stub(SimpleNamespace(ok=True, advice="이렇게 해라"))
    assert bare._api_escalation_advice("j", "p", ["가격"], [{"tool": "x"}], "초안") == "이렇게 해라"
    bare.api_escalation = Stub(SimpleNamespace(ok=False, advice=""))
    assert bare._api_escalation_advice("j", "p", [], [], "") == ""
    assert calls == [("j", "pushback_stalled"), ("j", "pushback_stalled")]


def test_advice_is_not_evidence() -> None:
    message = esc.advice_message("상세 페이지를 열어라")
    assert "근거가 아니다" in message and "도구를 불러 직접 확인" in message


def test_api_path_is_separate_from_subscription_handoff() -> None:
    from alture_jarvis import claude_code

    handoff = inspect.getsource(claude_code)
    assert "import anthropic" not in handoff and "api_escalation" not in handoff
    assert "claude_code_enabled" not in inspect.getsource(esc)
