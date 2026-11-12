"""11-10: 질문 카드에서 닫힌 판이 「걸음 0」으로 찍혀 「한 걸음도 안 갔다」로 잘못 읽었다 — 걸음 목록에서 센다(양방향)."""
from __future__ import annotations

from alture_jarvis import measure_kit as mk


class _Fake(mk.Sonjari):
    def __init__(self, rows):
        super().__init__("http://x", "t")
        self.rows = rows

    def call(self, path, body=None, *, timeout=60):
        if path == "/v1/chat":
            return {"job_id": "J"}
        if path == "/v1/jobs/J":
            return {"status": "waiting_approval"}          # 기록(trace) 없이 질문 카드에서 섬
        if path == "/v1/jobs/J/steps":
            return {"items": self.rows}
        if path.startswith("/v1/jobs/J/steps/"):
            return {"payload": {"url": "https://11st.co.kr/products/1", "text": "가격 99,000원"}}
        return {}


def test_a_run_closed_at_a_question_card_still_counts_its_steps() -> None:
    rows = [{"step": 1, "tool": "browser_search", "ok": True}, {"step": 2, "tool": "browser_read", "ok": True},
            {"step": 3, "tool": "browser_click", "ok": False, "error": "not_found"}]
    run = _Fake(rows).run("x", "s", sleep=lambda _s: None)
    assert run["asked"] is True
    assert run["steps"] == 3
    assert run["refused_steps"] == 1
    assert run["pages"] and run["pages"][0]["url"].startswith("https://11st.co.kr")


def test_a_run_that_really_did_nothing_stays_at_zero() -> None:
    run = _Fake([]).run("x", "s", sleep=lambda _s: None)
    assert run["steps"] == 0 and run["pages"] == []
