"""11-11: PC 상태 물음이 1~27초 — 66% 가 작업 본문 풀기, 30% 가 음성 연결의 인증서 읽기(py-spy). 양방향으로 본다."""
from __future__ import annotations

import time
from pathlib import Path

from alture_jarvis.jobs import JobStore


def test_recent_activity_gives_the_same_newest_time_as_the_full_list(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    for i in range(30):
        store.create_job("chat", f"일 {i}", {"blob": "x" * 50_000})
    full = store.list_jobs(limit=20)
    light = store.recent_activity(limit=20)
    newest = lambda rows: max(max(float(r.get("created_at") or 0), float(r.get("updated_at") or 0)) for r in rows)
    assert newest(full) == newest(light)
    assert [r["kind"] for r in full] == [r["kind"] for r in light]
    assert set(light[0]) == {"kind", "created_at", "updated_at"}  # 본문을 싣지 않는다


def test_the_jobs_table_has_a_created_at_index(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    with store._connect() as conn:  # noqa: SLF001
        plan = " ".join(str(tuple(row)) for row in conn.execute(
            "EXPLAIN QUERY PLAN SELECT kind, created_at, updated_at FROM jobs ORDER BY created_at DESC LIMIT 20"))
    assert "idx_jobs_created" in plan and "TEMP B-TREE" not in plan


def test_tts_health_skips_certificates_for_a_plain_http_server(monkeypatch) -> None:
    from alture_jarvis import tts

    seen = {}

    class _Client:
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            class R:
                status_code = 200

                def raise_for_status(self):
                    return None
            return R()

    monkeypatch.setattr(tts.httpx, "Client", _Client)

    class Cfg:
        tts_enabled = True
        supertonic_voice = "F1"
        supertonic_base_url = "http://127.0.0.1:7788"
        tts_steps = 5
        tts_speed = 1.0
        output_dir = Path(".")

    assert tts.SupertonicTTS(Cfg()).health()["ok"] is True
    assert seen.get("verify") is False
    Cfg.supertonic_base_url = "https://voice.example"
    tts.SupertonicTTS(Cfg()).health()
    assert seen.get("verify") is True  # https 면 그대로 검사한다
