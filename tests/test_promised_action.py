"""말만 하고 끝나는 것을 막는다.

2026-08-05 사용자님 대화 실측: 마케팅 경쟁사 조사를 부탁했는데 자비스가 세 턴 연속으로
"지금 바로 조사하겠습니다. 잠시만 기다려 주십시오"라고만 답하고 실제 도구 호출은 0회였다.
라우터가 도구 호출 없는 텍스트를 최종 답변으로 확정하기 때문이다.

프롬프트에 "예고하지 마라"를 적는 것만으로는 부족했다 — 그 지시는 이미 있었다.
여기서 잠그는 것은 말이 아니라 **말로 끝나는 것**이다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import PROMISED_ACTION
from alture_jarvis.runtime import JarvisRuntime


@pytest.mark.parametrize(
    "answer",
    [
        "잠시만 기다려 주십시오. 바로 확인해 보겠습니다.",
        "네, 알겠습니다. 지금 바로 조사하겠습니다.",
        "국내 주요 에듀테크 시장을 상세히 조사해 오겠습니다.",
        "조금만 기다려 주세요.",
        "관련 자료를 검색해 보겠습니다.",
        "제가 찾아보겠습니다.",
        "지금 확인해 보겠습니다.",
        "바로 진행하겠습니다.",
        "경쟁사 특징을 분석해 드리겠습니다.",
    ],
)
def test_promises_are_caught(answer: str) -> None:
    assert PROMISED_ACTION.search(answer), answer


@pytest.mark.parametrize(
    "answer",
    [
        "1 더하기 1은 2입니다.",
        "현재 시각은 2026년 8월 5일 04:39입니다.",
        "확인 결과, 서버는 정상입니다.",
        "조사 결과 경쟁사는 세 곳입니다.",
        "필요하시면 말씀해 주세요.",
        "그 파일은 이미 삭제되어 있습니다.",
        "임시저장을 완료했습니다. 저장 개수가 3에서 4로 늘었습니다.",
    ],
)
def test_finished_answers_are_not_treated_as_promises(answer: str) -> None:
    """이미 끝난 일을 보고하는 문장을 예고로 오인하면, 멀쩡한 답변마다 에이전트가
    한 번 더 돌아 느려지고 같은 말을 두 번 하게 된다."""
    assert not PROMISED_ACTION.search(answer), answer


# ── 조사해 달라는 말은 답이 아니라 조사를 원하는 것이다 ──────────────────────────
#
# 예고를 막았더니 이번엔 모델이 도구 없이 2,244자짜리 경쟁사 분석을 자기 기억에서
# 지어냈다(2026-08-05 실측, 출처 0). 예고보다 나쁠 수 있다 — 그럴듯해서 검증을 안 하게 된다.


@pytest.mark.parametrize(
    "prompt",
    [
        "국내 에듀테크 경쟁사 특징 조사해줘",
        "요즘 학원 관리 솔루션 시장 트렌드 좀 알아봐",
        "에듀테크 박람회 참가사 찾아봐",
        "이거 웹에서 찾아봐",
        "구글링 좀 해줘",
        "관련 기사 검색해줘",
        "경쟁 제품 가격 조사해 줘",
    ],
)
def test_explicit_research_goes_to_the_agent(prompt: str) -> None:
    assert JarvisRuntime._requires_web_research(prompt), prompt


@pytest.mark.parametrize(
    "prompt",
    [
        "내 다운로드 폴더에서 계약서 찾아봐",
        "어제 만든 파일 좀 찾아봐",
        "1+1은?",
        "오늘 일정 알려줘",
        "블로그에 글 하나 써줘",
        "카메라 왼쪽으로 돌려봐",
    ],
)
def test_local_or_conversational_requests_are_left_alone(prompt: str) -> None:
    """'내 파일 찾아봐'까지 브라우저로 보내면 엉뚱한 곳을 뒤진다. 대상이 바깥일 때만이다."""
    assert not JarvisRuntime._requires_web_research(prompt), prompt
