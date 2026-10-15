"""「읽지 않고 적은 것」 경고가 헛짚던 두 모양 (2026-10-08).

경고가 붙은 최근 122판을 세어 보니 —
- 14판은 **웹을 한 번도 안 본 판**이었다(이 PC 의 파일만 읽은 코드·문서 판). 이 검사는 「목록 줄에서 옮겨 적었나」를
  묻는데, 그런 판에는 옮겨 적을 목록이 없다. 영어 설명서를 읽고 한국어로 풀어 쓴 「| 요구 | 구현 |」 표에 경고가 붙었다.
- 9판은 짚인 것이 전부 **번호 붙은 제목 아래의 굵은 글머리**였다. 항목마다 `### 1. 이름` 을 달고 그 아래 장점·단점을
  적은 답에서 「완전 무료」·「상세 내용 확인 필요」가 이름으로 뽑혔다.

여기 글은 전부 지어낸 것이다.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent

READ_PAGE = "가람 창업센터 입주 모집 안내. 나래 공유오피스 멘토링 프로그램. 월 이용료와 신청 기간은 공고문 참조."


def tool_messages(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": "창업 공간 지원을 알아봐줘"}, {"role": "tool", "content": text}]


def test_bold_bullets_under_numbered_headings_are_attributes() -> None:
    answer = "\n".join([
        "### 1. **가람 창업센터 입주 모집**",
        "**장점**:",
        "- **완전 무료**",
        "- **네트워킹 + 컨설팅**",
        "### 2. **나래 공유오피스 멘토링**",
        "**단점**:",
        "- **상세 내용 확인 필요**",
        "- **모집 규모 미정**",
    ])
    assert BrowserAgent._listed_entity_grounding_check(answer, tool_messages(READ_PAGE)) == ""


def test_bold_bullets_without_item_headings_are_still_names() -> None:
    answer = "\n".join(["추천하는 곳입니다.", "- **다온 스타트업 캠퍼스**", "- **마루 창업보육센터**"])
    note = BrowserAgent._listed_entity_grounding_check(answer, tool_messages(READ_PAGE))
    assert "다온 스타트업 캠퍼스" in note and "마루 창업보육센터" in note


def test_table_rows_under_numbered_headings_are_still_checked() -> None:
    answer = "\n".join([
        "### 1. 서울권",
        "| 이름 | 지역 |",
        "|---|---|",
        "| 다온 스타트업 캠퍼스 | 서울 |",
        "| 마루 창업보육센터 | 서울 |",
        "### 2. 부산권",
        "- **가람 창업센터 입주 모집**",
    ])
    note = BrowserAgent._listed_entity_grounding_check(answer, tool_messages(READ_PAGE))
    assert "다온 스타트업 캠퍼스" in note


PARAPHRASED_TABLE = "\n".join([
    "| 요구 | 구현 |",
    "|---|---|",
    "| 입력 칸은 값을 바꿀 수 있다 | `InputCell` 의 value 세터 |",
    "| 계산 칸은 다른 칸으로 값을 낸다 | `ComputeCell` 의 함수 |",
])


ENGLISH_SPEC = "An input cell has a settable value. A compute cell computes its value from other cells."


def test_a_requirement_table_is_a_list_of_items_not_names() -> None:
    """「| 요구 | 구현 |」의 첫 칸은 설명서의 요구를 풀어 쓴 말이다 — 영어 설명서를 한국어로 옮겼으니 원문에 글자 그대로 없다."""
    ledger = [{"type": "body_read", "ok": True, "source_id": r"c:\work\cells\instructions.md", "job_id": "j", "step": 1}]
    note = BrowserAgent._listed_entity_grounding_check(
        PARAPHRASED_TABLE, tool_messages(ENGLISH_SPEC), ledger, lambda job_id, step: ENGLISH_SPEC
    )
    assert note == ""


def test_a_local_only_job_is_still_checked() -> None:
    """★ 지키는 쪽 — 웹을 안 본 판이라고 통째로 건너뛰지 않는다. 처음엔 그렇게 넣었다가 되돌렸다:
    코드 판에서 읽지 않은 파일을 표에 적은 줄을 잡는 보호가 같이 지워졌다(기존 시험이 잡아 줬다)."""
    ledger = [{"type": "body_read", "ok": True, "source_id": r"c:\work\cells\instructions.md", "job_id": "j", "step": 1}]
    answer = "\n".join([
        "| 이름 | 하는 일 |",
        "|---|---|",
        "| 다온 스케줄러 | 순서를 정한다 |",
        "| 마루 캐시 | 값을 기억한다 |",
    ])
    note = BrowserAgent._listed_entity_grounding_check(
        answer, tool_messages(ENGLISH_SPEC), ledger, lambda job_id, step: ENGLISH_SPEC
    )
    assert "다온 스케줄러" in note and "마루 캐시" in note
