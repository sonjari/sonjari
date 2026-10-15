"""「문제 보내기」 — 보여 주고, 동의받고, **보여 준 그대로** 보낸다 (2026-09-29, 베타 전 필수)."""

from __future__ import annotations

from pathlib import Path

import httpx

from alture_jarvis.problem_report import ProblemReporter, build_report, scrub

HOME = Path(r"C:\Users\parkgaram")


class _Response:
    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.status_code = status
        self._body = body or {"ok": True, "id": "r1"}

    def json(self) -> dict:
        return self._body


def _jobs() -> list[dict]:
    return [
        {"id": "ok1", "status": "completed", "title": "잘 끝난 일", "result": {"status": "done"}},
        {"id": "bad1", "status": "failed", "title": r"C:\Users\parkgaram\Documents 에서 보고서", "error": "boom",
         "result": {"agent_trace": {"steps": [
             {"tool": "browser_open", "ok": True},
             {"tool": "browser_screenshot", "ok": False, "error": "timeout 15000ms"},
         ]}}},
        {"id": "part1", "status": "completed", "title": "덜 채운 일", "result": {"status": "partial"}},
    ]


def test_scrub_hides_paths_mail_phone_and_tokens() -> None:
    text = r"C:\Users\parkgaram\a.txt garam@example.com 010-1234-5678 key=AbCdEfGhIjKlMnOpQrStUvWxYz0123"
    out = scrub(text, HOME)
    assert "parkgaram" not in out and "~" in out
    assert "<메일>" in out and "example.com" not in out
    assert "<전화>" in out and "1234" not in out
    assert "<숨김>" in out and "AbCdEf" not in out


def test_only_problem_jobs_go_in_and_they_are_scrubbed() -> None:
    report = build_report(health={"build": "abc", "ollama": {"model": "qwen", "context_length": 65536}},
                          jobs=_jobs(), gpu={"gpus": [{"used_gb": 20, "total_gb": 24, "apps": ["게임.exe"]}]},
                          home=HOME, app_version="0.4.0")
    titles = [job["title"] for job in report["jobs"]]
    assert "잘 끝난 일" not in titles and "덜 채운 일" in titles
    assert not any("parkgaram" in title for title in titles)
    failed = next(job for job in report["jobs"] if job["status"] == "failed")
    assert failed["steps"][1] == {"tool": "browser_screenshot", "ok": False, "error": "timeout 15000ms"}
    assert report["gpu"] == [{"used_gb": 20, "total_gb": 24}], "켜 둔 프로그램 이름을 실었다"
    assert report["model"]["context"] == 65536 and report["app_version"] == "0.4.0"


def test_no_consent_nothing_leaves() -> None:
    sent: list = []
    reporter = ProblemReporter(post=lambda url, payload: sent.append(payload) or _Response())
    preview = reporter.preview({"schema": 1, "jobs": []})
    assert reporter.send(preview["id"], consent=False)["error"] == "consent_required"
    assert sent == []


def test_what_was_shown_is_exactly_what_is_sent() -> None:
    sent: list = []
    reporter = ProblemReporter(post=lambda url, payload: sent.append((url, payload)) or _Response())
    shown = {"schema": 1, "jobs": [{"title": "보여 준 것"}]}
    preview = reporter.preview(shown)
    assert '"보여 준 것"' in preview["text"]
    result = reporter.send(preview["id"], consent=True, note="흰 화면 garam@example.com", home=HOME)
    assert result == {"ok": True, "id": "r1"}
    [(url, payload)] = sent
    assert url == "https://api.robometafit.com/sonjari/reports"
    assert {k: v for k, v in payload.items() if k not in {"consent", "note"}} == shown
    assert payload["consent"] is True and payload["note"] == "흰 화면 <메일>"
    assert reporter.send(preview["id"], consent=True)["error"] == "preview_expired", "한 번 보낸 것을 또 보냈다"


def test_an_old_preview_cannot_be_sent() -> None:
    now = [1000.0]
    reporter = ProblemReporter(post=lambda url, payload: _Response(), clock=lambda: now[0])
    preview = reporter.preview({"schema": 1})
    now[0] += 31 * 60
    assert reporter.send(preview["id"], consent=True)["error"] == "preview_expired"


def test_a_failed_send_can_be_retried() -> None:
    calls = {"n": 0}

    def post(url, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("down")
        return _Response()

    reporter = ProblemReporter(post=post)
    preview = reporter.preview({"schema": 1})
    assert not reporter.send(preview["id"], consent=True)["ok"]
    assert reporter.send(preview["id"], consent=True)["ok"], "한 번 실패하면 다시 못 보냈다"


def test_the_server_refusing_is_reported_not_swallowed() -> None:
    reporter = ProblemReporter(post=lambda url, payload: _Response(status=429))
    preview = reporter.preview({"schema": 1})
    assert reporter.send(preview["id"], consent=True) == {"ok": False, "error": "http_429"}


def test_the_url_lives_in_both_the_dataclass_and_the_loader() -> None:
    """사고 Q: 값이 사는 자리가 여럿이면 낮은 쪽이 이긴다 — 둘 다 같은 주소여야 한다."""
    from alture_jarvis.config import JarvisConfig

    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "config.py").read_text(encoding="utf-8")
    assert JarvisConfig().problem_report_url == "https://api.robometafit.com/sonjari/reports"
    assert '_env("JARVIS_PROBLEM_REPORT_URL", "https://api.robometafit.com/sonjari/reports")' in source


def test_the_gaps_the_cross_check_found_are_closed() -> None:
    """코덱스 교차 검사(09-29)가 그대로 나가는 것을 재현한 네 가지."""
    cases = {
        r"C:/Users\sampleuser/private.txt": "sampleuser",
        "+82-10-1234-5678": "1234",
        "010 (1234) 5678": "1234",
        "username=sampleuser password=ShortPass123!": "ShortPass123",
    }
    for text, leak in cases.items():
        out = scrub(text, Path(r"C:\Users\other"))
        assert leak not in out, (text, out)
    assert scrub("username=sampleuser password=x1", None) == "username=<숨김> password=<숨김>"
    assert scrub("비밀번호: abc123 아이디=hong", None) == "비밀번호: <숨김> 아이디=<숨김>"


def test_ordinary_numbers_survive() -> None:
    """시각·크기·걸음 수는 진단에 필요하다 — 전화번호로 먹지 않는다."""
    text = "elapsed 1790665751 steps 12 size 21152755874 build 15fe11f9b11c 2026-09-29"
    assert scrub(text, None) == text
