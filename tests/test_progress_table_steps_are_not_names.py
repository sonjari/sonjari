"""「| 단계 | 결과 |」 진행 표의 첫 칸은 단계 이름이다 (2026-10-01 네이버 서치어드바이저 판).

손자리가 소유확인을 누르다 캡차에서 멈추고, 끝에 이런 정리 표를 냈다:

    | 단계 | 결과 |
    | HTML 태그 방식 선택 | ✅ 완료 |
    | 소유확인 버튼 클릭 | ✅ 눌렀으나 캡차 발생 |
    | **캡차 통과** | ❌ 사용자 직접 입력 필요 |

검사가 첫 칸을 이름으로 잡아 「읽지 않고 적은 것: HTML태그방식선택, 소유확인버튼클릭, 캡차통과…」를 붙였다.
읽은 페이지에 「HTML 태그 방식 선택」이라는 글이 있을 리 없다 — 손자리가 **한 일**의 이름이다.
"""

from alture_jarvis.agent import BrowserAgent

PAGE = "사이트 소유확인 HTML 태그 <meta name=\"naver-site-verification\" content=\"b37e...\" /> 소유확인"
MESSAGES = [
    {"role": "user", "content": "네이버 서치어드바이저에 sonjari.com 소유확인하고 사이트맵 제출해 줘"},
    {"role": "tool", "content": PAGE},
]


def _answer(first_header: str) -> str:
    return (
        f"| {first_header} | 결과 |\n| --- | --- |\n"
        "| HTML 태그 방식 선택 | ✅ 완료 |\n"
        "| 메타 태그 값 복사 | ✅ 저장 |\n"
        "| 소유확인 버튼 클릭 | ✅ 눌렀으나 캡차 발생 |\n"
        "| **캡차 통과** | ❌ 사용자 직접 입력 필요 |\n"
        "| 사이트맵 제출 | ⏳ 소유확인 완료 후 진행 |\n"
    )


def test_the_live_progress_table_gets_no_false_warning():
    assert BrowserAgent._listed_entity_grounding_check(_answer("단계"), MESSAGES) == ""


def test_other_step_headers_too():
    for header in ("절차", "진행 단계", "Step", "stage", "phase"):
        assert BrowserAgent._listed_entity_grounding_check(_answer(header), MESSAGES) == "", header


def test_a_name_column_is_still_checked():
    answer = "| 회사 | 결과 |\n| --- | --- |\n| 도담스페이스 | ✅ |\n| 바름터 | ✅ |\n"
    warning = BrowserAgent._listed_entity_grounding_check(answer, MESSAGES)
    assert "도담스페이스" in warning and "바름터" in warning
