"""사람이 준 분류 이름은 「읽지 않고 적은 이름」이 아니다 (2026-09-28 레딧 판).

클로드가 「댓글을 『철학 공감 / 써 보고 싶다·다운로드 문의 / 하드웨어·사양 언급 / 반론·의심 / 질문』 중
하나로 나눠 줘」라고 맡겼고, 온텔릭은 제대로 읽고 표를 냈다. 그런데 거짓말 검사가 표 첫 칸의 **분류 이름**을
「이번에 연 페이지 어디에도 없다」고 잡아 맞는 답 끝에 경고를 붙였다. 경고가 틀리면 아무도 경고를 안 읽는다.
"""

from alture_jarvis.agent import BrowserAgent

PROMPT = (
    "레딧에서 우리 글을 찾아 댓글을 「철학 공감 / 써 보고 싶다·다운로드 문의 / 하드웨어·사양 언급 / "
    "반론·의심 / 질문」 중 하나로 나누고 작성자와 함께 정리해 줘."
)
PAGE = "Tiny-Paper-Boat: Had the same experience, the install worked fine on my machine ... Maker-Account0000: Thank you"


def _answer(first_header: str) -> str:
    return (
        f"| {first_header} | 작성자 | 원문 요지 |\n|---|---|---|\n"
        "| **하드웨어·사양 언급** | Tiny-Paper-Boat | 8K 6/12, 16K 9/12 |\n"
        "| **철학 공감** | Tiny-Paper-Boat | 설치판이 두 배 걸림 |\n"
        "| **써 보고 싶다·다운로드 문의** | Maker-Account0000 | 감사 |\n"
    )


def test_category_column_is_not_checked_as_names():
    messages = [{"role": "user", "content": PROMPT}, {"role": "tool", "content": PAGE}]
    assert BrowserAgent._listed_entity_grounding_check(_answer("카테고리"), messages) == ""


def test_labels_the_user_listed_are_not_names_even_under_an_unknown_header():
    # 머리글 낱말표는 언젠가 샌다 — 사람이 준 선택지는 머리글과 상관없이 뺀다.
    messages = [{"role": "user", "content": PROMPT}, {"role": "tool", "content": PAGE}]
    assert BrowserAgent._listed_entity_grounding_check(_answer("반응 성격"), messages) == ""


def test_names_the_user_asked_about_are_still_checked():
    # 쉼표로 부른 회사 이름은 선택지가 아니다 — 안 읽고 적었으면 여전히 잡는다.
    messages = [
        {"role": "user", "content": "사람인에서 도담스페이스, 바름터 공고를 찾아 정리해 줘"},
        {"role": "tool", "content": "코드나루 채용 공고 본문 ... 미르 채용 공고 본문"},
    ]
    answer = "| 회사 | 마감 |\n|---|---|\n| 도담스페이스 | 10.01 |\n| 바름터 | 10.03 |"
    warning = BrowserAgent._listed_entity_grounding_check(answer, messages)
    assert "도담스페이스" in warning and "바름터" in warning


def test_invented_names_next_to_user_labels_are_still_caught():
    messages = [{"role": "user", "content": PROMPT}, {"role": "tool", "content": PAGE}]
    answer_rows = "| 작성자 | 분류 |\n|---|---|\n| Ghost-Commenter-1 | 철학 공감 |\n| Ghost-Commenter-2 | 질문 |"
    warning = BrowserAgent._listed_entity_grounding_check(answer_rows, messages)
    assert "Ghost-Commenter-1" in warning and "Ghost-Commenter-2" in warning
    assert "철학" not in warning
