"""예고는 진척이 아니다 — 그리고 원장에 없는 도구는 존재하지 않는 것과 같다.

2026-09-04 밀양 야놀자 판에서 한 병이 세 턴 연속으로 나왔다.

    턴1  browser_snapshot 한 장 → "바로 상세 가격 확인 들어갑니다!"
    턴2  browser_snapshot 한 장 → "날짜 바꾸고 바로 찾아오겠습니다!"
    턴3  「어엉 좀해줘」 → 0 걸음 · **가격표를 지어냄**

턴1·2 는 `_nothing_done_yet` 이 「성공한 걸음이 하나 있다」고 봐서 예고 되받기가
꺼졌다. 화면을 보는 것은 답할 재료가 아니다. 턴3 은 라우터 직답이라 원장 자체가
없었다 — 앞 턴의 예고를 아무도 안 보고 있었다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import (
    PROMISED_ACTION,
    _ANSWERABLE_EVIDENCE,
    _nothing_done_yet,
    _nothing_to_answer_from,
)
from alture_jarvis.browser import _IRREVERSIBLE_ACTION, _read_only_submit
from alture_jarvis.evidence import (
    MANIFEST,
    TYPE_ARTIFACT,
    TYPE_BODY_READ,
    TYPE_MUTATION,
    record_for,
)


def _step(tool: str, evidence: dict, *, ok: bool = True, arguments: dict | None = None) -> dict:
    minted = record_for(tool, evidence, ok=ok, step=1, job_id="j", arguments=arguments or {})
    step = {"step": 1, "tool": tool, "ok": ok, "evidence": evidence, "arguments": arguments or {}}
    if minted is not None:
        step["evidence_record"] = minted.to_dict()
    return step


# ── 화면을 본 것은 답할 재료가 아니다 ────────────────────────────────────


def test_a_snapshot_is_not_something_to_answer_from() -> None:
    """이 판이 세 턴을 망친 자리다."""
    steps = [_step("browser_snapshot", {"url": "https://nol.yanolja.com/"})]
    assert not _nothing_done_yet(steps), "성공한 걸음은 있다 — 옛 조건은 못 잡는다"
    assert _nothing_to_answer_from(steps), "그런데 답할 재료는 없다"


def test_reading_a_body_is_something_to_answer_from() -> None:
    steps = [_step("browser_extract", {"url": "https://example.com/a", "text": "본문"})]
    assert not _nothing_to_answer_from(steps)


def test_a_listing_alone_is_not_enough() -> None:
    steps = [
        _step("browser_site_search", {"url": "https://kmong.com/search?q=x"}),
        _step("browser_open_result", {"url": "https://kmong.com/gig/1"}),
    ]
    assert _nothing_to_answer_from(steps), "목록과 여는 것만으로는 답을 못 짓는다"


def test_a_failed_read_does_not_count() -> None:
    steps = [_step("browser_extract", {"url": "https://example.com/a", "text": "x"}, ok=False)]
    assert _nothing_to_answer_from(steps)


def test_the_yanolja_answers_were_promises() -> None:
    """실제로 나간 두 답. 되받기 조건의 나머지 반쪽이 이것이다."""
    for answer in (
        "잠시만 기다려 주십시오. 바로 상세 가격 확인 들어갑니다!",
        "날짜 바꾸고 모텔로 필터링해서 바로 찾아오겠습니다!",
    ):
        assert PROMISED_ACTION.search(answer), answer


# ── 원장에 없으면 「안 했다」로 찍힌다 ────────────────────────────────────


def test_reading_a_local_file_is_recorded_even_though_the_result_omits_the_path() -> None:
    """890 건의 읽기가 여기서 통째로 사라지고 있었다.

    `local_read_text_file` 의 결과에는 `path` 가 없다 — 무엇을 읽었는지는 **인자**에
    있다. 출처가 안 잡히면 `record_for` 는 아무것도 안 만들고, 코드 판의
    「0 개 실제로 읽음」은 거짓말이 된다.
    """
    minted = record_for(
        "local_read_text_file",
        {"action": "local_read_text_file", "char_count": 6000},
        ok=True,
        step=3,
        job_id="j",
        arguments={"path": "E:/repo/src/main.py"},
    )
    assert minted is not None
    assert minted.type == TYPE_BODY_READ


def test_a_source_in_the_result_still_wins_over_the_argument() -> None:
    """리디렉션된 주소가 진실이다 — 결과를 먼저 본다."""
    minted = record_for(
        "browser_extract",
        {"url": "https://final.example.com/a", "text": "본문"},
        ok=True,
        step=1,
        job_id="j",
        arguments={"url": "https://asked.example.com/a"},
    )
    assert minted is not None
    assert "final.example.com" in minted.source_id


def test_no_source_anywhere_still_mints_nothing() -> None:
    assert (
        record_for("local_read_text_file", {"char_count": 1}, ok=True, step=1, job_id="j")
        is None
    ), "지어내는 것보다 없는 편이 낫다"


@pytest.mark.parametrize(
    "tool",
    [
        "local_delete_file",
        "google_gmail_send",
        "google_calendar_create",
        "naver_blog_save_draft",
        "google_drive_write",
    ],
)
def test_things_that_leave_a_mark_are_registered(tool: str) -> None:
    """이게 빠져 있으면 「읽기 전용 위반 0 건」이 거짓이 된다."""
    assert tool in MANIFEST, f"{tool} 이 원장에 없다"
    assert MANIFEST[tool].type == TYPE_MUTATION


def test_a_sandbox_run_that_saved_a_file_is_an_artifact() -> None:
    made = record_for(
        "sandbox_run",
        {"run_id": "67087c43fff8", "saved_to": ["{'name': 'a.xlsx'}"]},
        ok=True,
        step=1,
        job_id="j",
    )
    assert made is not None and made.type == TYPE_ARTIFACT
    ran = record_for("sandbox_run", {"run_id": "20a63553e5dc", "stdout": "42\n"},
                     ok=True, step=1, job_id="j")
    assert ran is not None and ran.type not in _ANSWERABLE_EVIDENCE


# ── 찾아보는 것은 승인받을 일이 아니다 ──────────────────────────────────


@pytest.mark.parametrize("label", ["검색", "숙소 검색", "검색하기", "Search", "필터", "정렬"])
def test_a_search_button_opens_without_asking_a_human(label: str) -> None:
    """야놀자 판이 여기서 걸음 셋을 버리고 승인 창까지 띄웠다 — 찾아보는 일에."""
    assert _read_only_submit(label)
    assert not _IRREVERSIBLE_ACTION.search(label)


@pytest.mark.parametrize(
    "label", ["", "로그인", "신청하기", "예약하기", "저장", "등록", "회원가입", "결제하기"]
)
def test_things_that_leave_a_mark_still_need_approval(label: str) -> None:
    gated = bool(_IRREVERSIBLE_ACTION.search(label)) or not _read_only_submit(label)
    assert gated, f"{label!r} 이 승인 없이 눌린다"


def test_a_search_label_cannot_smuggle_a_payment() -> None:
    label = "검색 후 결제"
    assert _read_only_submit(label), "안전 낱말은 들어 있다"
    assert _IRREVERSIBLE_ACTION.search(label), "그래도 앞 검사에서 걸려야 한다"


def test_a_long_label_is_not_a_label() -> None:
    """이름이 아니라 문단을 긁어 왔으면 판정 재료로 못 쓴다 — 안전한 쪽으로."""
    assert not _read_only_submit("이 상품을 검색하고 장바구니에 담은 뒤 결제까지 진행합니다")
