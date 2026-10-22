"""첫 글자 전 기다림 표시 (2026-10-21 · `first_token_wait` 의 설명).

22시 예약 판이 첫 글자까지 51 · 33 · 88초를 말없이 기다렸다. 그동안 마지막 걸음 줄을 「앞의 기록을 읽는 중 · N초째」로
바꾸고, 첫 조각이 오면 원래 글로 되돌린다. 빨리 오면 아무것도 안 한다.
"""

from __future__ import annotations

import time

from alture_jarvis import first_token_wait
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.first_token_wait import FirstTokenWatch, estimate_tokens, tokens_label, wait_message
from alture_jarvis.jobs import JobStore


def test_tokens_label_reads_like_a_person() -> None:
    assert tokens_label(70_580) == "약 7.1만 토큰"
    assert tokens_label(100_000) == "약 10만 토큰"
    assert tokens_label(24_808) == "약 2.5만 토큰"
    assert tokens_label(30_010) == "약 3만 토큰"
    assert tokens_label(8_000) == "약 8천 토큰"
    assert tokens_label(70_580, english=True) == "~71k tokens"


def test_estimate_only_from_a_measured_call() -> None:
    assert estimate_tokens(30_000, None) == 0, "잰 값이 없으면 수를 지어내지 않는다"
    assert estimate_tokens(3_000, (1_000, 500)) == 1_500


def test_short_record_does_not_claim_reading() -> None:
    assert "앞의 기록" not in wait_message(3_000, 12)
    assert wait_message(70_580, 15.7) == "모델이 앞의 기록(약 7.1만 토큰)을 읽는 중 · 첫 글자 전 15초째"


def test_quick_first_word_changes_nothing() -> None:
    sent: list[dict] = []
    watch = FirstTokenWatch(last={"job_id": "j", "message": "결과를 읽었습니다", "step": 3},
                            tokens=70_000, english=False, publish=sent.append, delay=0.2, every=0.2)
    watch.seen()
    time.sleep(0.3)
    assert sent == []


def test_slow_first_word_shows_then_restores_the_same_line() -> None:
    sent: list[dict] = []
    last = {"job_id": "j", "phase": "tool", "message": "결과 목록 24개를 읽었습니다", "step": 3,
            "tool": "browser_result_list", "status": "completed"}
    watch = FirstTokenWatch(last=last, tokens=70_000, english=False, publish=sent.append, delay=0.05, every=0.05)
    time.sleep(0.2)
    watch.seen()
    count = len(sent)
    time.sleep(0.15)
    assert len(sent) == count, "되돌린 뒤에는 더 내보내지 않는다"
    waits, restored = sent[:-1], sent[-1]
    assert waits and all("앞의 기록(약 7만 토큰)을 읽는 중" in row["message"] for row in waits)
    # 새 줄을 만들지 않는다 — 같은 걸음 · 같은 도구 줄의 글만 바뀐다.
    assert all((row["step"], row["tool"], row["phase"]) == (3, "browser_result_list", "tool") for row in sent)
    assert restored == last


def test_no_line_to_change_means_no_thread() -> None:
    sent: list[dict] = []
    watch = FirstTokenWatch(last=None, tokens=70_000, english=False, publish=sent.append, delay=0.01, every=0.01)
    time.sleep(0.05)
    watch.close()
    assert sent == []


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names: set[str] = set()
    ollama_tools: list = []


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        raise AssertionError("도구를 실행하지 않는다")


class _SlowFirstWord:
    def chat_messages_stream(self, messages, *, tools=None, temperature=0.1, think=False, on_chunk=None, **kwargs):
        time.sleep(0.25)
        on_chunk({"thinking": "생각 ", "content": ""})
        return {"role": "assistant", "content": "다 했습니다."}


def test_agent_shows_the_wait_on_the_last_step_line(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(first_token_wait, "DELAY_SEC", 0.05)
    monkeypatch.setattr(first_token_wait, "EVERY_SEC", 0.05)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True)
    events = EventBus()
    agent = BrowserAgent(config, _SlowFirstWord(), _Gateway(), _Browser(), _Tools(), JobStore(tmp_path / "j.db"), events)
    agent._progress("job-w", "tool", "결과 목록 24개를 읽었습니다", step=3, tool="browser_result_list", status="completed")

    agent._model_message([], job_id="job-w", tools=None, think=True)

    rows = [e.payload for e in events.get_since(0) if e.event == "agent_progress"]
    assert any(row.get("waiting_first_token") for row in rows), "첫 글자 전 기다림이 안 보였다"
    assert rows[-1]["message"] == "결과 목록 24개를 읽었습니다", "첫 조각 뒤 원래 글로 안 돌아왔다"
