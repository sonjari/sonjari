"""열어 달라고 한 주소가 다른 주소로 넘어가도, 그 주소는 「연 주소」다 (2026-10-07 6차 굽기 전 실기 확인에서 나온 것).

패키지 저장소에서 세 프로젝트의 최신 버전을 엑셀로 정리하는 판. 세 페이지를 전부 열어 읽고 값을 맞게 적었는데, 답 끝에
「이번에 열지 않은 주소가 줄에 붙어 있습니다」가 한 줄 붙었다. 모델은 `…/project/Larkspur/` 를 열어 달라고 했고 사이트는
`…/project/larkspur/` 로 넘겼다 — 걸음 기록에는 도착한 주소만 남아, 줄에 적힌(= 열어 달라고 한) 주소가 안 연 주소로 읽혔다.
운영 기록에서 이 경고가 붙은 주소 23개 가운데 4개가 이 모양이었다.

고침: 열기가 성공한 **인자 주소**를 도착한 페이지에 묶는다. 대소문자를 뭉개지는 않는다(경로의 대소문자가 다른 페이지인 사이트가 있다) —
묶는 근거는 「바로 그 주소를 열어 달라고 했고, 열렸다」 하나다. 묶인 줄의 이름·값 대조는 도착한 페이지와 그대로 한다.

여기 쓴 사이트·프로젝트 이름은 전부 지어낸 것이다.
"""
from __future__ import annotations

from alture_jarvis.agent import BrowserAgent

HOST = "https://packs.example"


def _open(asked: str, landed: str, title: str, *, ok: bool = True) -> list[dict]:
    opened = {"ok": ok, "tool": "browser_open", "arguments": {"url": HOST + asked},
              "evidence": {"url": HOST + landed, "title": title}, "evidence_record": {"type": "page_open"}}
    if not ok:
        opened["error"] = "page_not_found"
        return [opened]
    return [opened, {"ok": True, "tool": "browser_extract", "arguments": {}, "evidence": {"url": HOST + landed, "title": title},
                     "evidence_record": {"type": "body_read"}}]


STEPS = (
    _open("/project/Larkspur/", "/project/larkspur/", "larkspur · Packs")
    + _open("/project/Juniper/", "/project/Juniper/", "Juniper · Packs")
    + _open("/project/Thistle/", "/project/Thistle/", "Thistle · Packs")
)

ANSWER = (
    "| 프레임워크 | 최신 버전 | 릴리스 날짜 | 확인한 주소 |\n|---|---|---|---|\n"
    f"| Larkspur | 0.142.2 | 2026년 9월 30일 | {HOST}/project/Larkspur/ |\n"
    f"| Juniper | 3.1.3 | 2026년 2월 19일 | {HOST}/project/Juniper/ |\n"
    f"| Thistle | 6.1.2 | 2026년 10월 6일 | {HOST}/project/Thistle/ |\n"
)


def test_the_address_the_model_asked_to_open_is_an_opened_address() -> None:
    note = BrowserAgent._row_page_binding_check(ANSWER, STEPS)
    assert "열지 않은 주소" not in note, note


def test_an_address_nobody_asked_for_is_still_flagged() -> None:
    answer = ANSWER + f"| Bramble | 2.0.0 | 2026년 1월 3일 | {HOST}/project/Bramble/ |\n"
    note = BrowserAgent._row_page_binding_check(answer, STEPS)
    assert "이번에 열지 않은 주소" in note and "Bramble" in note


def test_a_different_case_that_was_never_asked_for_is_not_folded_into_an_opened_page() -> None:
    """도착한 주소와 대소문자만 다른 주소라도, 열어 달라고 한 적이 없으면 연 주소가 아니다."""
    answer = ANSWER.replace("/project/Juniper/", "/project/JUNIPER/")
    note = BrowserAgent._row_page_binding_check(answer, STEPS)
    assert "이번에 열지 않은 주소" in note and "JUNIPER" in note


def test_an_open_that_failed_does_not_make_its_address_opened() -> None:
    steps = STEPS + _open("/project/Bramble/", "/project/Bramble/", "", ok=False)
    answer = ANSWER + f"| Bramble | 2.0.0 | 2026년 1월 3일 | {HOST}/project/Bramble/ |\n"
    note = BrowserAgent._row_page_binding_check(answer, steps)
    assert "이번에 열지 않은 주소" in note and "Bramble" in note


def test_an_address_that_was_sent_somewhere_else_is_checked_against_where_it_landed() -> None:
    """엉뚱한 페이지로 넘어간 주소를 「열었다」로만 치고 넘어가지 않는다 — 도착한 페이지의 제목과 줄의 이름을 맞대 본다."""
    steps = (
        _open("/project/Larkspur/", "/project/larkspur/", "larkspur · Packs")
        + _open("/project/Juniper/", "/project/Thistle/", "Thistle · Packs")     # Juniper 를 열어 달라고 했는데 Thistle 로 넘어갔다
    )
    answer = (
        "| 프레임워크 | 최신 버전 | 릴리스 날짜 | 확인한 주소 |\n|---|---|---|---|\n"
        f"| Larkspur | 0.142.2 | 2026년 9월 30일 | {HOST}/project/Larkspur/ |\n"
        f"| Juniper | 3.1.3 | 2026년 2월 19일 | {HOST}/project/Juniper/ |\n"
    )
    note = BrowserAgent._row_page_binding_check(answer, steps)
    assert "열지 않은 주소" not in note, note
    assert "줄과 출처 페이지가 안 맞습니다" in note and "Juniper" in note, note
