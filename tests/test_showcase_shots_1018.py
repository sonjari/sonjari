"""답이 기댄 페이지의 사진(대표사진) — 읽는 순간 한 장 · 판이 끝나면 고르기 (2026-10-18 대표 결정).

여기서 붙드는 것:
1) 답의 숫자 · 이름이 가장 많이 있던 본문의 사진이 앞에 온다(같으면 나중에 읽은 것) · 상한을 지킨다
2) 로그인 · 개인 화면(메일 · 마이페이지 · 사람에게 넘긴 사이트 · 주민번호가 있던 본문 · 사내 주소)은 고르지 않는다
3) 사진 없는 판 · 답과 겹친 것이 없는 판은 빈 목록이다
4) 찍기가 실패해도 걸음은 그대로 적히고 판은 이어간다(`_record_observation`)
5) 밖으로 나가는 사본은 needs 로 밝히지 않은 전화번호 · 메일 주소가 있던 페이지의 사진을 뺀다
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.outbound import outbound_job_view, showcase_for_outside
from alture_jarvis.showcase import (
    SHOT_TOOLS,
    pick_showcase_shots,
    private_reason,
    save_jpeg,
    shot_path_for,
)


def _shot(tmp_path: Path, step: int) -> str:
    path = tmp_path / f"step_{step:03d}.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    return str(path)


def _read(step: int, url: str, shot: str = "", *, tool: str = "browser_extract", ok: bool = True,
          title: str = "") -> dict[str, Any]:
    evidence: dict[str, Any] = {"url": url, "title": title or url}
    if shot:
        evidence.update({"shot_path": shot, "shot_url": url, "shot_title": title or url, "shot_at": 1000.0 + step})
    return {"step": step, "tool": tool, "ok": ok, "status": "completed" if ok else "failed", "error": "", "evidence": evidence}


ANSWER = (
    "| 회사 | 연봉 | 마감 |\n"
    "|---|---|---|\n"
    "| 코드나루 | 4,200만 원 | 10월 31일 |\n"
    "| 한울솔루션 | 3,800만 원 | 11월 7일 |\n\n"
    "**코드나루**가 연봉이 가장 높습니다."
)


def test_most_matched_page_comes_first_and_limit_holds(tmp_path: Path) -> None:
    steps = [
        _read(1, "https://www.saramin.co.kr/job/1", _shot(tmp_path, 1)),
        _read(2, "https://www.saramin.co.kr/job/2", _shot(tmp_path, 2)),
        _read(3, "https://www.saramin.co.kr/job/3", _shot(tmp_path, 3)),
    ]
    bodies = {
        1: "코드나루 백엔드 개발자 모집 연봉 4,200만 원 마감 10월 31일",
        2: "한울솔루션 연봉 3,800만 원",
        3: "관련 없는 페이지 날씨 맑음",
    }

    picked = pick_showcase_shots(steps, ANSWER, bodies, limit=2)

    assert [row["step"] for row in picked] == [1, 2]
    first = picked[0]
    assert set(first) >= {"path", "url", "title", "read_at", "matched"}
    assert first["url"] == "https://www.saramin.co.kr/job/1"
    assert first["read_at"] == 1001.0
    assert first["matched"] > picked[1]["matched"]
    # 답과 하나도 안 겹친 페이지(3)는 증거가 아니다.
    assert all(row["step"] != 3 for row in pick_showcase_shots(steps, ANSWER, bodies, limit=5))


def test_tie_goes_to_the_later_read_and_same_page_is_one_photo(tmp_path: Path) -> None:
    body = "한울솔루션 연봉 3,800만 원"
    steps = [
        _read(1, "https://a.example.com/x", _shot(tmp_path, 1)),
        _read(2, "https://b.example.com/y", _shot(tmp_path, 2)),
        _read(4, "https://b.example.com/y#top", _shot(tmp_path, 4)),
    ]
    picked = pick_showcase_shots(steps, ANSWER, {1: body, 2: body, 4: body}, limit=3)

    assert [row["step"] for row in picked] == [4, 1]


def test_only_body_reads_with_a_photo_on_disk_count(tmp_path: Path) -> None:
    body = "코드나루 연봉 4,200만 원"
    steps = [
        _read(1, "https://x.example.com/a", _shot(tmp_path, 1), tool="browser_open_result"),  # 연 것은 읽은 것이 아니다
        _read(2, "https://x.example.com/b", str(tmp_path / "gone.jpg")),  # 파일이 없다
        _read(3, "https://x.example.com/c", _shot(tmp_path, 3), ok=False),
        _read(4, "https://x.example.com/d"),  # 사진 없음
    ]
    assert pick_showcase_shots(steps, ANSWER, {n: body for n in (1, 2, 3, 4)}) == []
    assert SHOT_TOOLS == frozenset({"browser_extract", "browser_read"})


def test_run_without_photos_or_overlap_is_empty(tmp_path: Path) -> None:
    assert pick_showcase_shots([], ANSWER, {}) == []
    steps = [_read(1, "https://x.example.com/a", _shot(tmp_path, 1))]
    # 본문을 모르면 고를 근거가 없다.
    assert pick_showcase_shots(steps, ANSWER, {}) == []
    # 답에 숫자도 이름도 없으면 고를 것이 없다.
    assert pick_showcase_shots(steps, "네, 알겠습니다.", {1: "코드나루"}) == []


@pytest.mark.parametrize(
    "url, body, reason",
    [
        ("https://mail.google.com/mail/u/0/#inbox", "", "private_site"),
        ("https://www.coupang.com/np/cart", "", "private_page"),
        ("https://www.saramin.co.kr/zf_user/mypage/resume", "", "private_page"),
        ("https://nid.naver.com/nidlogin.login", "", "login_or_payment"),
        ("https://www.kbstar.com/quics?page=C0", "", "private_site"),
        ("http://localhost:3000/dashboard", "", "internal"),
        ("http://192.168.0.10/report", "", "internal"),
        ("http://intranet/notice", "", "internal"),
        ("file:///C:/Users/me/doc.html", "", "not_web"),
        ("https://www.example.com/public", "주민번호 900101-1234567 입니다", "sensitive_value"),
    ],
)
def test_private_and_login_pages_are_named(url: str, body: str, reason: str) -> None:
    assert private_reason(url, body=body) == reason


def test_public_pages_pass_including_sort_queries() -> None:
    assert private_reason("https://www.danawa.com/list/?order=price") == ""
    assert private_reason("https://blog.naver.com/someone/22312") == ""


def test_private_pages_are_never_picked(tmp_path: Path) -> None:
    body = "코드나루 연봉 4,200만 원 마감 10월 31일"
    steps = [
        _read(1, "https://mail.google.com/mail/u/0/#inbox/abc", _shot(tmp_path, 1)),
        _read(2, "https://www.saramin.co.kr/zf_user/mypage/apply", _shot(tmp_path, 2)),
        # 이 사이트는 이 판에서 사람에게 로그인을 넘겼다 — 그 뒤 읽은 화면은 로그인한 화면이다.
        {"step": 3, "tool": "browser_click", "ok": False, "status": "failed", "error": "login_required",
         "evidence": {}, "human_gate": {"code": "login_required", "url": "https://www.jobkorea.co.kr/Login"}},
        _read(4, "https://www.jobkorea.co.kr/Recruit/GI_Read/1", _shot(tmp_path, 4)),
        _read(5, "https://www.example.com/hr-notice", _shot(tmp_path, 5)),
        _read(6, "https://www.wanted.co.kr/wd/1", _shot(tmp_path, 6)),
    ]
    bodies = {1: body, 2: body, 4: body, 5: body + " 카드 4111 1111 1111 1111", 6: body}

    picked = pick_showcase_shots(steps, ANSWER, bodies, limit=5)

    assert [row["url"] for row in picked] == ["https://www.wanted.co.kr/wd/1"]


def test_phone_on_page_is_noted_and_dropped_outside_unless_asked(tmp_path: Path) -> None:
    steps = [_read(1, "https://www.wanted.co.kr/wd/1", _shot(tmp_path, 1))]
    # 2026-10-18 대표 결정 뒤: 회사 대표 번호(02-…)는 사진을 안 빼고, 휴대폰 번호(010-…)가 있으면 뺀다.
    picked = pick_showcase_shots(steps, ANSWER, {1: "코드나루 연봉 4,200만 원 문의 02-123-4567 · 담당 010-1234-5678"})
    assert picked and picked[0]["contains"] == ["전화번호"]

    job = {"payload": {"origin": "mcp", "needs": []}, "result": {"answer": "답", "showcase": picked}}
    assert outbound_job_view(job)["result"]["showcase"] == []
    asked = {"payload": {"origin": "mcp", "needs": ["연락처"]}, "result": {"answer": "답", "showcase": picked}}
    kept = outbound_job_view(asked)["result"]["showcase"]
    assert [row["url"] for row in kept] == ["https://www.wanted.co.kr/wd/1"]
    # 밖으로는 고른 칸만 — 걸음 번호 · contains 는 안 나간다.
    assert set(kept[0]) == {"path", "url", "title", "read_at", "matched"}
    assert showcase_for_outside("아님") == []


def test_save_jpeg_shrinks_wide_shots(tmp_path: Path) -> None:
    Image = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), (200, 30, 30)).save(buffer, format="JPEG", quality=90)
    saved = save_jpeg(buffer.getvalue(), tmp_path / "shots" / "job" / "step_001.jpg")

    assert saved["width"] == 1280 and saved["resized"]
    with Image.open(saved["path"]) as image:
        assert image.size == (1280, 720)

    small = io.BytesIO()
    Image.new("RGB", (800, 600)).save(small, format="JPEG")
    kept = save_jpeg(small.getvalue(), tmp_path / "small.jpg")
    assert not kept["resized"] and Path(kept["path"]).read_bytes() == small.getvalue()


def test_shots_live_beside_the_desk_not_on_it(tmp_path: Path) -> None:
    path = shot_path_for(tmp_path, "job-1", 7)
    assert path == tmp_path / "shots" / "job-1" / "step_007.jpg"
    assert "workspace" not in path.parts


# ── 찍는 길목 ─────────────────────────────────────────────────────────

class _Browser:
    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour
        self.calls: list[Path] = []

    def capture_read_shot(self, destination: Path) -> dict[str, Any]:
        self.calls.append(Path(destination))
        if self.behaviour == "raise":
            raise RuntimeError("browser_busy_stuck")
        if self.behaviour == "fail":
            return {"ok": False, "reason": "capture_window_minimized", "ms": 3}
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"jpeg")
        return {"ok": True, "path": str(destination), "url": "https://www.wanted.co.kr/wd/1", "title": "공고",
                "at": 1234.5, "ms": 42}


def _agent(tmp_path: Path, behaviour: str) -> Any:
    from alture_jarvis.agent import BrowserAgent
    from alture_jarvis.events import EventBus

    agent = object.__new__(BrowserAgent)
    agent.events = EventBus()
    agent.attention = None
    agent.browser = _Browser(behaviour)
    agent.config = SimpleNamespace(output_dir=tmp_path)
    return agent


def _record(agent: Any, name: str = "browser_extract", ok: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    steps: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    agent._record_observation(
        job_id="job-7",
        name=name,
        arguments={},
        step_number=3,
        label="본문 읽기",
        observation={"ok": ok, "status": "completed" if ok else "failed", "error": "" if ok else "x",
                     "result": {"url": "https://www.wanted.co.kr/wd/1", "title": "공고", "text": "코드나루 연봉"}},
        steps=steps,
        messages=messages,
        evidence_urls=[],
        last_action_ids={},
        tool_numbers=set(),
        tool_numbers_body=set(),
    )
    return steps, messages


def test_a_read_takes_one_photo_into_the_step(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "ok")
    steps, messages = _record(agent)

    evidence = steps[0]["evidence"]
    assert evidence["shot_path"] == str(tmp_path / "shots" / "job-7" / "step_003.jpg")
    assert evidence["shot_url"] == "https://www.wanted.co.kr/wd/1"
    assert evidence["shot_title"] == "공고" and evidence["shot_at"] == 1234.5 and evidence["shot_ms"] == 42
    # 모델에게 돌아가는 관찰값에는 사진 칸이 없다(토큰 · 캐시).
    assert all("shot_path" not in str(message.get("content")) for message in messages)


@pytest.mark.parametrize("behaviour", ["raise", "fail"])
def test_failed_photo_does_not_stop_the_run(tmp_path: Path, behaviour: str) -> None:
    agent = _agent(tmp_path, behaviour)
    steps, messages = _record(agent)

    assert len(steps) == 1 and steps[0]["ok"]
    evidence = steps[0]["evidence"]
    assert "shot_path" not in evidence and evidence["shot_error"]
    assert isinstance(evidence["shot_ms"], int)
    assert any(message.get("role") == "tool" for message in messages)


def test_no_photo_for_opening_failing_or_without_a_browser(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "ok")
    _record(agent, name="browser_open_result")
    _record(agent, ok=False)
    assert agent.browser.calls == []

    bare = _agent(tmp_path, "ok")
    bare.browser = object()  # 그 손이 없는 브라우저(옛 일꾼 · 시험)
    steps, _ = _record(bare)
    assert "shot_path" not in steps[0]["evidence"] and "shot_error" not in steps[0]["evidence"]


def test_worker_without_a_browser_says_why() -> None:
    from alture_jarvis.browser import BrowserWorker

    worker = object.__new__(BrowserWorker)
    worker._connected = False
    result = worker.capture_read_shot("unused.jpg")
    assert result["ok"] is False and result["reason"] == "browser_not_started" and "ms" in result


def test_business_numbers_keep_the_photo_but_personal_contacts_drop_it() -> None:
    """2026-10-18 대표 결정: 가게 · 회사 대표 번호와 회사 메일은 공개 정보 — 휴대폰 번호와 개인 메일만 사진을 뺀다."""
    from alture_jarvis.showcase import _personal_contacts

    assert _personal_contacts("거창시장추어탕 055-944-1234 · 예약 1588-0000 · info@shop.co.kr") == []
    assert _personal_contacts("사장님 010-1234-5678") == ["전화번호"]
    assert _personal_contacts("문의 someone@gmail.com") == ["메일 주소"]


def test_the_discord_copy_drops_the_top_band(tmp_path) -> None:
    from PIL import Image

    from alture_jarvis.messaging.bridge import _without_top_band

    source = tmp_path / "step_001.jpg"
    Image.new("RGB", (800, 600), (255, 255, 255)).save(source)
    cropped = _without_top_band(source, band=120)
    with Image.open(cropped) as image:
        assert image.size == (800, 480)
    assert source.exists() and cropped != source
