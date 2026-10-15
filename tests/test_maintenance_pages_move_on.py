"""**점검 중이면 두드리지 않고 넘어간다.**

## 왜 세 번째 갈래인가

이 저장소는 닫힌 화면을 둘로 갈라 다뤄 왔다:

    봇 검사      「네가 사람인지 보겠다」 → 기다리거나 사람이 넘겨받는다
    문전박대     앞단이 그때그때 되돌려보낸다 → 세 번까지 다시 해 본다
                 (실측에서 같은 주소가 1·2·3번째에 열렸다)

점검 화면은 **모두에게 닫혀 있다.** 1초 뒤에도 2초 뒤에도 같다. 그런데 코드는
이것을 문전박대로 읽어 세 번 두드렸고, 3초와 걸음 셋을 버린 끝에 「막혔다」라는
**틀린 이유**를 말했다. 점검 중인 것과 차단당한 것은 다음에 할 일이 다르다 —
전자는 다른 출처로 가야 하고, 후자는 그 사이트를 다시 시도해 볼 수 있다.

## 넓힐 때는 반대쪽도 붙든다

「점검」 두 글자만 보면 「차량 점검 서비스」를 파는 멀쩡한 페이지가 점검 화면이
된다. 그래서 문전박대와 같은 규율을 쓴다 — **짧은 화면일 때만** 본문 문구를 믿고,
제목에 걸리면 길이를 안 본다.
"""
from __future__ import annotations


class _Page:
    def __init__(self, title: str = "", body: str = "") -> None:
        self._title, self._body = title, body

    def title(self) -> str:
        return self._title

    def locator(self, _selector: str) -> "_Page":
        return self

    def inner_text(self, timeout: int = 0) -> str:
        return self._body


def _seen(title: str = "", body: str = "") -> str:
    from alture_jarvis.browser import BrowserWorker

    return BrowserWorker._under_maintenance(_Page(title, body))


def test_a_korean_maintenance_screen_is_recognised() -> None:
    assert _seen(body="서비스 점검 중입니다. 잠시 후 다시 이용해 주세요.")
    assert _seen(body="시스템 점검 안내\n02:00 ~ 06:00")
    assert _seen(body="일시적인 오류가 발생했습니다.")


def test_an_english_maintenance_screen_is_recognised() -> None:
    assert _seen(body="We'll be back soon. Under maintenance.")
    assert _seen(body="503 Service Unavailable")


def test_the_title_alone_is_enough() -> None:
    """점검 화면은 제목부터 그렇게 적는다 — 본문이 길어도 믿는다."""
    assert _seen(title="서비스 점검 중 - 사람인", body="본문 " * 4000)


def test_a_long_page_that_merely_mentions_inspection_is_not_maintenance() -> None:
    """★ 넓힌 만큼 새는지 반대쪽도 붙든다."""
    body = "자동차 점검 중 알아두면 좋은 것 열 가지. " * 200
    assert not _seen(body=body)


def test_a_normal_page_is_not_maintenance() -> None:
    assert not _seen(title="여수 회계 채용", body="(주)솔바람뜰여수 정규직 모집")
    assert not _seen(body="")


def test_maintenance_is_not_the_same_message_as_blocked() -> None:
    """다음에 할 일이 다르므로 **말이 달라야 한다.**

    막힌 것은 그 사이트를 다시 시도해 볼 수 있고, 점검은 다른 출처로 가야 한다.
    """
    import inspect

    from alture_jarvis.browser import BrowserWorker

    source = inspect.getsource(BrowserWorker._goto_checked)
    assert "site_under_maintenance" in source
    assert "다른 출처로 넘어가세요" in source
    # 점검 판정이 **재시도보다 먼저** 와야 세 번 두드리지 않는다.
    assert source.index("_under_maintenance") < source.index("_edge_blocked")
