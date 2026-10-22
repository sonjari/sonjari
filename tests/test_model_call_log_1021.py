"""부르기마다 첫 글자까지 · 앞부분 읽기 시간을 남긴다 (2026-10-21 대표: 「처음 생각 토큰이 나오기까지 너무 오래 걸린다」).

같은 엑셀 판이 10-16 엔 앞부분 읽기 5.9초, 10-20 엔 32.3초였다. 판 합계만 남아 어느 부르기에서 캐시가 깨졌는지 몰랐다.
글 · 도구 내용은 남기지 않고 지문만 남긴다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from alture_jarvis.ollama import OllamaClient


def _client(tmp_path: Path) -> OllamaClient:
    client = OllamaClient.__new__(OllamaClient)
    client.config = SimpleNamespace(data_dir=tmp_path)
    return client


def test_a_call_leaves_one_line_with_times_and_fingerprints_only(tmp_path: Path) -> None:
    body = {"model": "m", "messages": [{"role": "system", "content": "비밀 지시문 본문"}, {"role": "user", "content": "내 주소는 서울"}],
            "tools": [{"function": {"name": "browser_open"}}, {"function": {"name": "local_write_document"}}],
            "options": {"temperature": 0.1}, "think": True}
    payload = {"prompt_eval_count": 31000, "prompt_eval_duration": 16_200_000_000, "eval_count": 500, "load_duration": 20_000_000}
    _client(tmp_path)._log_call(body, payload, 16.4, 16.9)
    row = json.loads((tmp_path / "model_calls.jsonl").read_text(encoding="utf-8").strip())
    assert row["first_token_sec"] == 16.9 and row["prefill_sec"] == 16.2 and row["prompt_tokens"] == 31000
    assert row["tools"] == 2 and len(row["tools_sig"]) == 10 and len(row["system_head_sig"]) == 10
    text = json.dumps(row, ensure_ascii=False)
    assert "비밀 지시문" not in text and "서울" not in text and "browser_open" not in text


def test_the_log_keeps_only_recent_lines_when_it_grows(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.CALL_LOG_MAX_BYTES = 2000
    for _ in range(60):
        client._log_call({"model": "m", "messages": []}, {}, 0.1, 0.2)
    assert (tmp_path / "model_calls.jsonl").stat().st_size < 4000
