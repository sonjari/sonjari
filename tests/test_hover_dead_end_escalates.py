"""막다른 호버에서 **나가는 문**을 알려 주는가.

## 무엇이 고장이었나

호버가 헛손질이면 안내가 "browser_click 으로 눌러 봐라"까지만 나갔다. 그런데
클릭도 안 먹으면 **그다음 할 말이 없었다.** 그래서 자비스는 이미 죽은 자리로
계속 돌아왔다.

2026-08-23 실측(쿠팡 가전디지털 카테고리):

     5. hover(j10) → 아무것도 안 나타남
     6. click(j10) → 눌렀는데 URL 그대로
     8. hover(j19) → 같은 실패      9. click(j19) → 같은 실패
    15. hover(j10) → ★ 아까 죽은 그 자리를 다시

퀀3.8 은 16걸음·173초를 쓰고 출처 2개로 끝냈다. 두 모델 다 이 판에서 막혔다 —
**모델이 아니라 안내가 끊긴 것**이다.

## 손은 이미 다 있었다

같은 날 도구 사용 분포를 세어 봤다:

    젬마4-26B   총 106걸음 · 키보드 9 (8%)  · 마우스 39 (36%)
    퀀3.8-27B   총  52걸음 · 키보드 5 (9%)  · 마우스 12 (23%)

그리고 `browser_press`·`browser_fill`·`browser_select_option` 은 **0회**였다.
있는데 안 쓰는 것이지 없는 게 아니다. 그래서 도구를 새로 만들지 않고,
막다른 자리에서 **그 손들을 이름으로 짚어 준다.**
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from alture_jarvis.browser import BrowserTools, BrowserWorker


class _Box:
    """`_hover` 의 안내 분기만 떼어 시험한다 — 실제 브라우저는 안 띄운다."""

    def __init__(self) -> None:
        self._dead_hovers: dict[tuple[str, str], int] = {}

    def note(self, url: str, name: str) -> str:
        result: dict[str, object] = {}
        page = SimpleNamespace(url=url)
        fingerprint = (str(getattr(page, "url", "") or "")[:120], name)
        self._dead_hovers[fingerprint] = self._dead_hovers.get(fingerprint, 0) + 1
        if self._dead_hovers[fingerprint] < 2:
            result["instruction"] = (
                "올려놨는데 새로 나타난 것이 없다. 호버로 열리는 메뉴가 아니다 — "
                "browser_click 으로 눌러 봐라."
            )
        else:
            result["instruction"] = (
                f"★ 이 자리는 {self._dead_hovers[fingerprint]}번째 헛손질이다. "
                "browser_site_search browser_find browser_open browser_fill browser_press"
            )
        return str(result["instruction"])


def test_the_first_dead_hover_still_suggests_clicking() -> None:
    box = _Box()
    note = box.note("https://www.coupang.com/", "전체")
    assert "browser_click" in note
    assert "헛손질" not in note, "첫 번째는 클릭을 권하는 게 맞다"


def test_the_second_dead_hover_points_at_other_hands() -> None:
    """★ 같은 자리 두 번째부터는 **다른 손**을 이름으로 짚어야 한다."""
    box = _Box()
    box.note("https://www.coupang.com/", "전체")
    note = box.note("https://www.coupang.com/", "전체")
    assert "헛손질" in note
    for hand in ("browser_site_search", "browser_find", "browser_fill", "browser_press"):
        assert hand in note, f"{hand} 를 안 알려 준다"


def test_a_different_element_starts_its_own_count() -> None:
    """다른 자리는 따로 센다 — 한 번 실패했다고 온 화면을 포기하면 안 된다."""
    box = _Box()
    box.note("https://www.coupang.com/", "전체")
    note = box.note("https://www.coupang.com/", "가전디지털 바로가기")
    assert "browser_click" in note and "헛손질" not in note


def test_the_same_name_on_another_page_starts_over() -> None:
    box = _Box()
    box.note("https://www.coupang.com/", "전체")
    note = box.note("https://www.danawa.com/", "전체")
    assert "헛손질" not in note


def test_the_real_hover_keeps_the_escalation_branch() -> None:
    """★ 진짜 불변식: 위 흉내가 아니라 **실제 코드**에 그 분기가 있는가."""
    import inspect

    source = inspect.getsource(BrowserWorker._hover)
    assert "_dead_hovers" in source, "되풀이를 세지 않으면 막다른 자리를 못 알아본다"
    for hand in ("browser_site_search", "browser_fill", "browser_press"):
        assert hand in source, f"막다른 안내에 {hand} 가 없다"


@pytest.mark.parametrize("hand", ["browser_press", "browser_fill", "browser_select_option"])
def test_the_keyboard_tools_actually_exist(hand: str) -> None:
    """알려 주기 전에 **그 손이 실재하는지** 확인한다.

    없는 도구를 권하면 모델이 이름을 지어내기 시작한다 — 이 저장소가 이미 아는
    함정이다("도구를 만들어도 갈래가 없으면 지어낸다"의 반대 방향).
    """
    import inspect

    source = inspect.getsource(BrowserTools)
    assert f'"{hand}"' in source, f"{hand} 가 실제로 없다"
