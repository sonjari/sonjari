"""「이번 주 손자리가 클로드 대신 읽은 양」 영수증 (2026-10-19).

지키는 것: 바깥 AI 가 MCP 문으로 맡긴 판만 센다 · 판 하나의 하한은 `delegation.host_context_kept_out` 그대로 ·
멈춘 판도 읽었으면 센다(판 수는 나눠 적는다) · 말은 「최소 N 토큰」과 근거뿐(약 · 배 · % · $ 없음).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from alture_jarvis import savings_receipt as sr
from alture_jarvis import ui_i18n
from alture_jarvis.delegation import host_context_kept_out

NOW = 1_800_000_000.0
DAY = 86400.0


def _steps(*chars: int) -> list[dict]:
    return [{"ok": True, "tool": "browser_extract", "evidence_record": {"effect": "read"}, "evidence": {"char_count": n}}
            for n in chars]


def _row(job_id: str, *, origin: str = "mcp", caller: str = "Claude Code", status: str = "completed",
         chars: tuple[int, ...] = (9000,), ago_days: float = 1.0, prompt: str = "과제") -> dict:
    return {
        "id": job_id,
        "status": status,
        "payload": {"origin": origin, "caller": caller, "prompt": prompt},
        "result": {"agent_trace": {"steps": _steps(*chars)}},
        "finished_at": NOW - ago_days * DAY,
    }


def _rows() -> list[dict]:
    return [
        _row("cc-1", chars=(9000,)),                                     # 2000
        _row("cc-2", chars=(4500, 4500), prompt="가" * 80),              # 2000 (읽기 둘)
        _row("codex-1", caller="codex-mcp-client", chars=(45000,)),      # 10000
        _row("cc-stopped", status="cancelled", chars=(900,)),             # 200 — 멈췄어도 읽은 것은 센다
        _row("cc-failed-noread", status="failed", chars=()),              # 0 — 판 수에는 든다
        _row("person", origin="workspace", caller="", chars=(90000,)),    # 사람이 앱에서 — 아예 안 본다
        _row("discord", caller="Discord", chars=(90000,)),               # 사람이 폰으로 — 빠짐(까닭 적음)
        _row("nameless", caller="", chars=(90000,)),                      # MCP 문을 안 지난 판(측정 스크립트) — 빠짐
        _row("bench", caller="bench-om2w", chars=(90000,)),              # 측정 스크립트가 붙인 이름 — 빠짐
        _row("running", status="running", chars=(90000,)),                # 아직 도는 판 — 건수만
        _row("old", chars=(90000,), ago_days=8),                          # 기간 밖
    ]


def test_it_counts_only_tasks_an_outside_ai_handed_off() -> None:
    receipt = sr.summarize(_rows(), days=7, now=NOW)

    assert receipt["tokens_at_least"] == 2000 + 2000 + 10000 + 200
    assert receipt["jobs"] == {"total": 5, "done": 3, "stopped": 2, "with_reads": 4}
    assert receipt["excluded"] == {"no_host_name": 1, "person_via_discord": 1, "measurement": 1}
    assert receipt["in_progress"] == 1
    assert receipt["kind"] == "floor"


def test_each_task_floor_is_the_delegation_function_itself() -> None:
    """복사한 셈이 아니라 `delegation` 의 함수 그대로 — 판 결과의 cost 와 같은 숫자여야 한다."""
    rows = [r for r in _rows() if r["id"] in {"cc-1", "cc-2", "codex-1", "cc-stopped"}]
    expected = sum(host_context_kept_out(r["result"]["agent_trace"]["steps"])["tokens_at_least"] for r in rows)

    assert sr.summarize(rows, days=7, now=NOW)["tokens_at_least"] == expected


def test_hosts_and_top_three() -> None:
    receipt = sr.summarize(_rows(), days=7, now=NOW)

    hosts = {b["host"]: (b["tokens_at_least"], b["jobs"]) for b in receipt["by_host"]}
    assert hosts == {"Claude Code": (4200, 4), "Codex": (10000, 1)}
    # 많이 덜어 준 순 — 같으면 늦게 끝난 판이 먼저, 그것도 같으면 기록 순서 그대로.
    assert [t["job_id"] for t in receipt["top"]] == ["codex-1", "cc-1", "cc-2"]
    long = next(t for t in receipt["top"] if t["job_id"] == "cc-2")
    assert long["prompt"] == "가" * 60 + "…"
    # 코덱스가 섞였으니 「클로드 대신」이라 하지 않는다.
    assert receipt["host_word"] == "outside_ai"


def test_claude_only_week_says_claude() -> None:
    rows = [r for r in _rows() if r["payload"]["caller"] == "Claude Code"]
    assert sr.summarize(rows, days=7, now=NOW)["host_word"] == "claude"
    assert sr.summarize([], days=7, now=NOW)["host_word"] == "outside_ai"


def test_classification_rules() -> None:
    assert sr.counted_reason({"origin": "mcp", "caller": "Claude Code"}) == ""
    assert sr.counted_reason({"origin": "mcp", "caller": "cursor-vscode"}) == ""
    assert sr.counted_reason({"origin": "workspace", "caller": "Claude Code"}) == "not_delegated"
    assert sr.counted_reason({"origin": "mcp", "caller": ""}) == "no_host_name"
    assert sr.counted_reason({"origin": "mcp", "caller": "Discord"}) == "person_via_discord"
    for name in ("bench-om2w", "honesty-bench", "rerun-reddit-1003"):
        assert sr.counted_reason({"origin": "mcp", "caller": name}) == "measurement"
    assert sr.host_label("claude-code") == "Claude Code"
    assert sr.host_label("codex-mcp-client") == "Codex"
    assert sr.host_label("cursor-vscode") == "기타"


def test_discord_caller_matches_the_bridge() -> None:
    bridge = pytest.importorskip("alture_jarvis.messaging.bridge")
    assert sr.DISCORD_CALLER == bridge.CALLER


_INFLATING = re.compile(r"약|배|%|\$|달러|아꼈|절약|시간")
_INFLATING_EN = re.compile(r"\babout\b|\baround\b|\btimes\b|\bx\d|%|\$|dollar|saved time|faster", re.IGNORECASE)


def test_the_words_say_floor_and_nothing_bigger() -> None:
    receipt = sr.summarize(_rows(), days=7, now=NOW)
    line = sr.headline(receipt)

    assert "최소 14,200 토큰" in line
    assert "맡긴 일 5건" in line and "끝난 판 3" in line and "멈춘 판 2" in line
    assert "하한" in receipt["basis"]
    # 눈금 역검증 — 부풀린 말을 넣으면 잡아야 한다.
    assert _INFLATING.search("약 3배 아꼈습니다") and _INFLATING_EN.search("about 3 times, $2 saved")
    for text in (line, receipt["basis"]):
        assert not _INFLATING.search(text), text


def test_the_english_basis_keeps_the_floor_and_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_i18n, "_lang", "en")
    ui_i18n.reload()
    out = ui_i18n.translate_payload(sr.summarize(_rows(), days=7, now=NOW))

    assert not re.search("[가-힣]", out["basis"]), out["basis"]
    assert "lower bound" in out["basis"]
    assert not _INFLATING_EN.search(out["basis"]), out["basis"]
    # 과제 글은 사용자의 글 — 영어 화면에서도 바꾸지 않는다.
    assert any(re.search("[가-힣]", t["prompt"]) for t in out["top"])


def test_days_are_clamped() -> None:
    assert sr.summarize([], days=0, now=NOW)["days"] == 1
    assert sr.summarize([], days=10_000, now=NOW)["days"] == sr.MAX_DAYS
    assert sr.summarize([], days="x", now=NOW)["days"] == sr.DEFAULT_DAYS


def test_collect_reads_a_real_store_read_only(tmp_path: Path) -> None:
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.models import JobStatus

    store = JobStore(tmp_path / "jobs.db")
    mine = store.create_job("chat", "t", {"origin": "mcp", "caller": "Claude Code", "prompt": "레딧 조사"})
    store.set_status(mine["id"], JobStatus.COMPLETED, result={"agent_trace": {"steps": _steps(45000)}})
    person = store.create_job("chat", "t", {"origin": "workspace", "prompt": "사람"})
    store.set_status(person["id"], JobStatus.COMPLETED, result={"agent_trace": {"steps": _steps(45000)}})
    before = (tmp_path / "jobs.db").read_bytes()

    receipt = sr.collect(tmp_path / "jobs.db", days=7)

    assert receipt["tokens_at_least"] == 10000
    assert receipt["jobs"]["total"] == 1
    assert (tmp_path / "jobs.db").read_bytes() == before
    # 읽기 전용 — 없는 DB 를 만들지 않는다.
    with pytest.raises(Exception):
        sr.collect(tmp_path / "nope.db")
    assert not (tmp_path / "nope.db").exists()


def test_api_needs_the_token_and_answers(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False)
    client = TestClient(create_app(config, start_services=False))

    assert client.get("/v1/savings").status_code == 401
    response = client.get("/v1/savings?days=7", headers={"X-JARVIS-TOKEN": "test-token"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "floor" and body["days"] == 7 and body["tokens_at_least"] == 0
