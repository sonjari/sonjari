"""「가 줘」라고 했는데 링크만 주고 안 열었으면 도구가 연다 (2026-09-29 대표 실사용 · 잡 9fe5fbd7)."""
from __future__ import annotations

from alture_jarvis.agent import _offered_link_to_open

AWS_ASK = "그러면 AWS로 가줄수는있나 로그인은 내가할게"
AWS_ANSWER = (
    "네, 사용자님. AWS 콘솔로 바로 이동해 드리겠습니다.\n\n"
    "👉 **[AWS EC2 대시보드 열기](https://ap-northeast-2.console.aws.amazon.com/ec2/home?region=ap-northeast-2#)**"
)


def test_the_aws_link_is_opened_when_nothing_was_opened() -> None:
    assert _offered_link_to_open(AWS_ASK, AWS_ANSWER, []) == "https://ap-northeast-2.console.aws.amazon.com/ec2/home?region=ap-northeast-2#"


def test_nothing_happens_once_the_browser_was_used() -> None:
    steps = [{"tool": "browser_open", "ok": True}]
    assert _offered_link_to_open(AWS_ASK, AWS_ANSWER, steps) == ""


def test_a_link_to_somewhere_else_is_not_opened_for_a_named_site() -> None:
    answer = "AWS 는 여기서 보세요: https://example.com/aws-guide"
    assert _offered_link_to_open(AWS_ASK, answer, []) == ""


def test_web_place_words_count_as_a_place() -> None:
    ask = "그 구글 로그인 페이지 열어줘"
    assert _offered_link_to_open(ask, "여기입니다: https://accounts.google.com/", []) == "https://accounts.google.com/"


def test_chat_that_merely_contains_the_verb_is_left_alone() -> None:
    ask = "우리 강아지 어제 산책하다 발을 다쳐서 연고 발랐거든 상태 좀 봐줘"
    assert _offered_link_to_open(ask, "동물병원 안내: https://vet.example/", []) == ""
    assert _offered_link_to_open("링크 하나 알려줘", "https://example.com/", []) == ""


def test_a_given_address_is_opened_before_any_answer_is_accepted() -> None:
    """주소를 주고 열라 했는데 걸음 0 으로 「화면이 열렸습니다」를 지어낸 판(2884740b) — 도구가 먼저 연다."""
    from alture_jarvis.agent import _forced_open_call

    ask = "browser_open 으로 https://github.com/account/organizations/new?plan=free 를 열어라. 로그인 화면이면 멈춰라."
    assert _forced_open_call(ask, []) == ("browser_open", {"url": "https://github.com/account/organizations/new?plan=free"})
    assert _forced_open_call(ask, [{"tool": "browser_open", "ok": False}]) is None, "한 번 시도했으면 다시 밀지 않는다"
    assert _forced_open_call("이 글 https://example.com/a 요약해줘", []) is None, "열라는 말이 없으면 안 연다"
    assert _forced_open_call("https://example.com/a 는 열지 말고 제목만 말해", []) is None
