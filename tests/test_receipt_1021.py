"""영수증 (2026-10-21) — 이번 주 손자리가 클로드 대신 읽은 양. 센 값만, 측정 판은 빼고, 디스코드는 사람이 직접 시킨 일로."""

from __future__ import annotations

import time
from pathlib import Path

from alture_jarvis.jobs import JobStore
from alture_jarvis.models import JobStatus
from alture_jarvis.receipt import is_measurement, one_line, weekly


def _read_step(chars: int) -> dict:
    return {"ok": True, "tool": "browser_extract", "evidence": {"char_count": chars, "url": "https://example.com/p"},
            "evidence_record": {"effect": "read_page"}}


def _job(store: JobStore, payload: dict, steps: list[dict], *, answer: str = "끝", status: str = "completed") -> None:
    job = store.create_job("chat", "agent", payload)
    store.claim_next()
    store.set_status(job["id"], JobStatus.COMPLETED if status == "completed" else JobStatus.FAILED,
                     result={"answer": answer, "agent_trace": {"steps": steps, "verification": {}}})


def test_counts_only_what_an_outside_ai_handed_over(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "j.db")
    _job(store, {"prompt": "a", "origin": "mcp", "caller": "Claude Code", "session_id": "s1"}, [_read_step(4500), _read_step(9000)])
    _job(store, {"prompt": "b", "origin": "mcp", "caller": "Discord", "session_id": "d1"}, [_read_step(4500)])
    _job(store, {"prompt": "c", "origin": "workspace", "session_id": "w1"}, [_read_step(900)])
    _job(store, {"prompt": "d", "origin": "mcp", "caller": "Claude Code", "session_id": "measure-price-1"}, [_read_step(99999)])
    _job(store, {"prompt": "e", "origin": "mcp", "measurement": True, "session_id": "x"}, [_read_step(99999)])
    receipt = weekly(store, days=7)
    assert receipt["delegated"]["jobs"] == 1
    assert receipt["delegated"]["pages"] == 2
    assert receipt["delegated"]["tokens_at_least"] == 3000, "센 글자 13,500 ÷ 4.5 의 하한"
    assert receipt["direct"] == {"jobs": 2, "pages": 2}, "디스코드는 폰에서 사람이 직접 시킨 일"
    assert receipt["measurement_jobs_skipped"] == 2
    assert receipt["callers"] == {"Claude Code": 1}


def test_a_number_no_tool_gave_is_counted_like_claude_saw_it(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "j.db")
    _job(store, {"prompt": "가격", "origin": "mcp", "caller": "Claude Code", "session_id": "s"}, [_read_step(4500)],
         answer="가장 싼 곳은 38,000원입니다.")
    assert weekly(store)["delegated"]["flagged_numbers_jobs"] == 1


def test_old_jobs_are_outside_the_week_and_the_line_is_empty_without_handoffs(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "j.db")
    _job(store, {"prompt": "a", "origin": "mcp", "caller": "Claude Code", "session_id": "s"}, [_read_step(4500)])
    later = time.time() + 8 * 86400
    receipt = weekly(store, days=7, now=later)
    assert receipt["delegated"]["jobs"] == 0 and one_line(receipt) == ""


def test_measurement_marks() -> None:
    assert is_measurement({"measurement": True})
    assert is_measurement({"session_id": "bench-x"}) and is_measurement({"session_id": "Measure-push-1"})
    assert not is_measurement({"session_id": "office-main"})


def test_the_english_line_has_the_same_numbers_and_no_korean() -> None:
    import re

    receipt = {"days": 7, "delegated": {"jobs": 3, "pages": 12, "tokens_at_least": 45678, "flagged_numbers_jobs": 1}}
    en = one_line(receipt, "en")
    assert "3 jobs" in en and "12 pages" in en and "45,678 tokens" in en and "1 jobs flagged" in en
    assert not re.search(r"[\uac00-\ud7a3]", en)


def test_save_image_writes_only_png_into_the_fixed_folder(tmp_path: Path) -> None:
    from alture_jarvis.receipt import IMAGE_MAX_BYTES, save_image

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    docs = tmp_path / "Sonjari"
    first = save_image(docs, png, now=time.mktime((2026, 10, 21, 12, 0, 0, 0, 0, -1)))
    assert first["ok"] and first["name"] == "sonjari-receipt-2026-10-21.png"
    assert first["short"] == r"Sonjari\receipts\sonjari-receipt-2026-10-21.png","집 경로(사람 이름)는 짧은 표시에 안 들어간다"
    assert Path(first["path"]).read_bytes() == png
    second = save_image(docs, png, now=time.mktime((2026, 10, 21, 13, 0, 0, 0, 0, -1)))
    assert second["name"] == "sonjari-receipt-2026-10-21-2.png", "같은 날 다시 저장해도 덮어쓰지 않는다"
    assert save_image(docs, b"GIF89a....")["error"] == "not_png"
    assert save_image(docs, png + b"\x00" * IMAGE_MAX_BYTES)["error"] == "too_large"
    assert sorted(p.name for p in (docs / "receipts").iterdir()) == ["sonjari-receipt-2026-10-21-2.png", "sonjari-receipt-2026-10-21.png"]


def test_receipt_image_endpoint_needs_token_and_writes_to_documents(tmp_path: Path) -> None:
    import base64

    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          documents_dir=tmp_path / "Sonjari", control_token="test-token", camera_enabled=False,
                          vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    body = {"png_base64": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()}
    with TestClient(app) as client:
        assert client.post("/v1/receipt/image", json=body).status_code == 401
        saved = client.post("/v1/receipt/image", json=body, headers={"X-JARVIS-TOKEN": "test-token"}).json()
        assert saved["ok"] and Path(saved["path"]).parent == tmp_path / "Sonjari" / "receipts"
        bad = client.post("/v1/receipt/image", json={"png_base64": "@@@"}, headers={"X-JARVIS-TOKEN": "test-token"}).json()
        assert bad == {"ok": False, "error": "bad_base64"}
