"""검색 결과에 섞인 **첨부파일 링크** 하나가 일을 통째로 끝내지 못하게 한다.

2026-08-12 실측. "여수·순천·광양 공고를 4개는 직접 열어 읽어라"를 시켰더니 공고를
한 건도 못 열고 끝났다. 마지막 스텝의 에러는 이것이었다:

    Page.goto: Download is starting
      navigating to "https://www.moel.go.kr/local/yeosu/common/downloadFile.do?..."

검색 결과 11번이 고용노동부 여수지청의 **첨부파일(hwp)** 링크였다. 페이지가 아니니
못 여는 게 맞다. 문제는 이 문구가 회복 힌트 어디에도 안 걸려서 **모델이 다음 수를
못 들었다**는 것이다. 예산은 30스텝인데 7스텝에서 스스로 멈췄다.

실패는 대부분 "이 방향이 막혔다"가 아니라 "이 **한 걸음**이 막혔다"이다. 그 구별을
모델이 스스로 못 하니 실패마다 다음 수를 같이 준다 — 이 파일이 지키는 규칙이다.
"""

from __future__ import annotations

from alture_jarvis.agent import _RECOVERY_HINTS

_DOWNLOAD_ERROR = (
    'Page.goto: Download is starting\nCall log:\n  - navigating to '
    '"https://www.moel.go.kr/local/yeosu/common/downloadFile.do?file_seq=20260300513", '
    'waiting until "domcontentloaded"'
)


def _hint_for(error: str) -> str:
    for pattern, hint in _RECOVERY_HINTS:
        if pattern.search(error):
            return hint
    return ""


def test_a_file_link_gets_a_next_move() -> None:
    hint = _hint_for(_DOWNLOAD_ERROR)

    assert hint, "이 실패에는 다음 수가 없다 — 모델은 여기서 멈춘다"
    assert "다른 rank" in hint, "다음 결과로 넘어가라고 말하지 않는다"


def test_it_does_not_send_the_model_back_to_searching() -> None:
    """막히면 검색으로 되돌아가는 것이 이 모델의 기본 습관이다(검색은 늘 성공하니까).

    그런데 그건 답에서 **멀어지는** 방향이다 — 결과 순위는 그대로 살아 있다.
    """
    hint = _hint_for(_DOWNLOAD_ERROR)

    assert "검색을 다시 하지" in hint


def test_it_says_to_keep_going_until_the_asked_count(fixture: None = None) -> None:
    del fixture
    hint = _hint_for(_DOWNLOAD_ERROR)

    assert "개수를 채울 때까지" in hint, "한 번 더 열고 또 멈출 수 있다"


def test_a_normal_page_error_is_still_handled() -> None:
    """새 규칙이 기존 규칙을 가로채지 않는지."""
    hint = _hint_for("net::ERR_CONNECTION_REFUSED")

    assert "다른 rank" in hint
