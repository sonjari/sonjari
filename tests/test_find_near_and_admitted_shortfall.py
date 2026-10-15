"""AWS 할당량 판(2026-09-29, fb04fdfd)에서 나온 둘.

1. 「새 할당량」으로 찾아 0건 → 모델이 「입력란을 찾을 수 없다」로 끝냈다. 칸 이름은 다른 말이었다.
   이제 찾기가 0건이면 이름이 겹치는 후보를 같이 준다(입력 칸을 찾는 말이면 입력 요소를 앞에).
2. 답이 스스로 「찾을 수 없습니다」라고 했는데 completion_state 가 complete 였다.
"""
from __future__ import annotations

from alture_jarvis.agent import _ADMITS_NOT_DONE
from alture_jarvis.browser import _near_find_candidates

ROWS = [
    {"ref": "j10", "name": "할당량 세부 정보", "tag": "a"},
    {"ref": "j32", "name": "계정 수준에서 증가 요청", "tag": "button"},
    {"ref": "j41", "name": "할당량 값 늘리기", "tag": "input"},
    {"ref": "j50", "name": "요청", "tag": "button"},
]


def test_a_field_with_a_different_name_is_offered() -> None:
    near = _near_find_candidates("새 할당량 입력칸", ROWS)
    assert near and near[0]["ref"] == "j41", near


def test_plain_words_rank_by_overlap() -> None:
    near = _near_find_candidates("증가 요청 버튼", ROWS)
    assert near[0]["ref"] == "j32"


def test_nothing_shared_gives_nothing() -> None:
    assert _near_find_candidates("결제 수단", ROWS) == []
    assert _near_find_candidates("새", ROWS) == [], "한 글자 낱말로는 후보를 만들지 않는다"


def test_answers_that_admit_not_doing_it() -> None:
    for text in (
        "새 할당량 입력란을 화면에서 찾을 수 없습니다",
        "상세 화면까지는 열지 못했습니다.",
        "쪽수와 ISBN 정보는 본문에서 찾지 못했습니다.",
        "나머지는 확인하지 못했으니",
    ):
        assert _ADMITS_NOT_DONE.search(text), text


def test_conditionals_and_success_are_not_admissions() -> None:
    for text in (
        "찾을 수 없으면 검색창에 다시 입력해 보세요.",
        "세 곳을 모두 열어 확인했습니다.",
        "입력칸에 8 을 넣었습니다.",
    ):
        assert not _ADMITS_NOT_DONE.search(text), text


def test_ontelic_browser_and_a_request_status_is_not_a_self_check() -> None:
    from alture_jarvis.runtime import _asks_about_own_health

    aws = ("온텔릭 브라우저에 AWS 콘솔이 로그인돼 있다. browser_open 으로 https://ap-northeast-2.console.aws.amazon.com/"
           "servicequotas/home/requests 를 열어 요청한 값·상태(대기/승인/거부 등)·요청 날짜를 읽어라.")
    assert not _asks_about_own_health(aws)
    assert not _asks_about_own_health("내일 오후 3시에 '[벤치] 자비스 실행 점검' 일정을 30분짜리로 만들어줘.")
    for asked in ("지금 네 상태 점검해보고, 이상한 데 있으면 원인까지 알려줘", "자비스 지금 너 상태 어떄", "온텔릭 요즘 왜 이렇게 느려"):
        assert _asks_about_own_health(asked), asked
