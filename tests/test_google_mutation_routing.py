"""계정의 무언가를 **바꾸라**는 요청은 모델 판단에 맡기지 않는다.

2026-08-13 L3 시험. "방금 등록한 'JARVIS L3 테스트 일정'을 내일 오후 5시로 옮겨줘"에
라우터가 **도구를 하나도 안 부르고** 이렇게 답했다:

    내일(2026-08-14) 오후 5시부터 6시로 일정을 변경할 준비를 마쳤습니다.
    아래 내용을 확인해 주시고, **승인**해 주시면 일정이 최종 수정됩니다.
    [변경 내용 미리보기] 기존 시간: 15:00~16:00 / 변경 시간: 17:00~18:00

미리보기 표까지 그럴듯하게 그렸는데 아무 일도 없었다. 정직성 검사 셋이 다 비켜 갔다:
출처를 인용한 게 아니고("본 척"이 아니다), 예고형도 아니었다("~하겠습니다"가 아니라
"~마쳤습니다"). **갈래가 없으면 검사로는 못 막는다**는 것을 다시 확인한 셈이다.

라우터에는 카메라 조작·사람 찾기·웹 조사·블로그 작성·로컬 점검·출처 지목 갈래가 있는데
**구글 워크스페이스만 없었다.** 캘린더·메일은 `use_google_workspace` 를 도구 메뉴에
올려놓고 모델이 고르기를 기다리고 있었다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.plan import mutating_google_tools


@pytest.mark.parametrize(
    ("prompt", "tool"),
    [
        ("내 구글 캘린더에 내일 오후 3시에 회의 일정 등록해줘", "google_calendar_create"),
        ("일정 하나 추가해줘 내일 2시", "google_calendar_create"),
        ("방금 등록한 일정을 오후 5시로 옮겨줘", "google_calendar_update"),
        ("내일 일정 시간 좀 변경해줘", "google_calendar_update"),
        ("내일 그 일정 삭제해줘", "google_calendar_delete"),
        ("가람한테 메일 보내줘", "google_gmail_send"),
    ],
)
def test_asking_to_change_something_names_the_tool(prompt: str, tool: str) -> None:
    assert tool in mutating_google_tools(prompt), prompt


@pytest.mark.parametrize(
    "prompt",
    [
        "내일 일정 뭐 있는지 알려줘",
        "메일 온 거 있나 확인해줘",
        "오늘 일정 정리해서 보여줘",
        "이번 주 계획 3가지만 세워줘",
    ],
)
def test_just_looking_is_not_changing(prompt: str) -> None:
    """읽기는 갈래를 안 탄다 — 타면 조회까지 전부 에이전트로 가서 느려진다."""
    assert mutating_google_tools(prompt) == [], prompt


def test_finishing_words_count_as_a_completion_claim() -> None:
    """"변경할 준비를 **마쳤습니다**"가 완료 주장 목록 어디에도 없었다.

    ★ 이 낱말을 넣는 것으로 그날 사고가 막히지는 **않는다.** `_commit_reality_check`
    는 `prepare` 는 됐는데 커밋이 없는 경우를 잡는 것이라, 도구를 하나도 안 부른
    라우터 직답에는 구조적으로 안 걸린다. 그 사고는 갈래(위 시험들)로 막는다.
    여기서 얻는 것은 **에이전트 경로**에서 준비만 하고 "마쳤다"고 할 때다.
    """
    prepared = [{"tool": "google_calendar_prepare_create", "ok": True, "status": "", "error": ""}]
    assert BrowserAgent._commit_reality_check("일정 등록을 마쳤습니다.", prepared)


def test_a_plain_conversation_is_not_accused_of_faking() -> None:
    answer = "학원 상담 기록은 세 가지 이유로 남겨야 합니다. 첫째, 분쟁이 생겼을 때 근거가 됩니다."
    assert BrowserAgent._commit_reality_check(answer, []) == ""


def test_counting_kinds_is_not_a_request_to_go_read_things() -> None:
    """오늘 내가 낸 회귀. `_COUNT_REQUEST` 에 '가지'를 넣었더니 이게 걸렸다:

        "'학원 데이터 관리 3가지 원칙'이라는 제목으로 글 써서 임시저장해줘"
        → ⚠ 3개를 열어 보라고 하셨는데 본문까지 연 것은 하나도 없습니다.

    가지·종은 **읽을 물건이 아니라 종류**를 센다.
    """
    prompt = "'학원 데이터 관리 3가지 원칙'이라는 제목으로 짧은 글을 써서 임시저장까지 해줘"
    assert BrowserAgent._goal_shortfall_check(prompt, []) == ""
