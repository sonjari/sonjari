"""처음 보는 종류의 일에서 「쓸 도구와 지침을 읽는 중」을 서버가 적은 진행률로 보인다 (2026-11-18 대표 결정 · 디자인 검토로 줄인 판)."""
from __future__ import annotations

import time
from pathlib import Path

from alture_jarvis.first_token_wait import FirstTokenWatch, remaining_label, wait_message
from alture_jarvis.prefill_progress import PrefillProgress, is_local_ollama

LINE = "slot print_timing: id  0 | task 7 | prompt processing, n_tokens =   {n}, progress = {p}, t =   8.03 s / 510 tokens per second\n"


def test_it_reads_only_lines_written_after_the_call_started(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_text(LINE.format(n=9000, p="0.95"), encoding="utf-8")       # 앞 부르기의 줄 — 섞으면 안 된다
    probe = PrefillProgress(log)
    assert probe.fraction() is None
    with log.open("a", encoding="utf-8") as handle:
        handle.write("srv  something else\n" + LINE.format(n=3072, p="0.34") + LINE.format(n=4096, p="0.46"))
    assert probe.fraction() == 0.46


def test_no_log_or_a_remote_engine_means_no_fraction(tmp_path: Path) -> None:
    assert PrefillProgress(None).fraction() is None
    assert PrefillProgress(tmp_path / "missing.log").fraction() is None
    assert is_local_ollama("http://127.0.0.1:11434") and not is_local_ollama("http://100.64.0.20:8091")


def test_a_rotated_log_starts_over(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_text("x" * 500, encoding="utf-8")
    probe = PrefillProgress(log)
    log.write_text(LINE.format(n=1024, p="0.12"), encoding="utf-8")      # 줄었다 = 새 파일
    assert probe.fraction() == 0.12


def test_the_words_are_the_ones_decided() -> None:
    assert wait_message(26_000, 41, reason="first", fraction=0.62) == "쓸 도구와 지침을 읽는 중 · 62% · 30초쯤 남음 · 처음 한 번만 걸려요"
    assert wait_message(26_000, 20, reason="first") == "쓸 도구와 지침을 읽는 중 · 20초째 · 처음 한 번만 걸려요"
    assert wait_message(26_000, 20, reason="model").endswith("모델을 다시 켠 뒤라 한 번 더 걸려요")
    assert "토큰" not in wait_message(26_000, 41, reason="first", fraction=0.62), "토큰 수는 화면 글에서 뺀다"


def test_remaining_time_comes_only_from_measured_progress() -> None:
    assert remaining_label(30, None) == ""
    assert remaining_label(2, 0.5) == "", "첫 배치 전에는 셈하지 않는다"
    assert remaining_label(30, 0.25) == "2분쯤 남음"
    assert remaining_label(30, 0.5) == "30초쯤 남음"


def test_the_watch_puts_the_fraction_in_the_line_and_keeps_numbers_for_the_record() -> None:
    sent: list[dict] = []
    state = {"p": None}
    watch = FirstTokenWatch(last={"job_id": "j", "message": "첫 걸음을 고르는 중"}, tokens=26_000, english=False,
                            publish=sent.append, delay=0.05, every=0.05, reason="first", progress=lambda: state["p"])
    time.sleep(0.12)
    state["p"] = 0.4
    time.sleep(0.12)
    watch.seen()
    shown = [p for p in sent if p.get("waiting_first_token")]
    assert shown and "40%" in shown[-1]["message"] and shown[-1]["prefill_fraction"] == 0.4 and shown[-1]["prefill_tokens"] == 26_000
    assert sent[-1]["message"] == "첫 걸음을 고르는 중", "첫 글자가 오면 원래 줄로 되돌린다"
