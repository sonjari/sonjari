"""훑기 상한이 실제 화면을 덮는가 — 다나와 정렬 미스터리의 결말.

## 무엇이었나 (2026-08-13 실측)

인수인계서 4-2 에는 "다나와 통합검색엔 가격 정렬이 아예 없는 것 같다"는 **가설**이
적혀 있었다. 그렇다면 젬마가 "못 찾았다"고 한 것이 맞는 답이라는 뜻이었다.

열어 보니 가설이 틀렸다. 정렬은 멀쩡히 있다:

    <li class="order_item" data-sort-method="priceASC"><a href="">낮은가격순</a></li>

`search.danawa.com/dsearch.php?query=무선마우스` 실측:

    _INTERACTIVE 에 걸리는 요소       7,157 개
    정렬 바(인기상품순~상품평많은순)   4,255 ~ 4,259 번째
    maxScan  700  → 75 개 수집,  정렬 없음      ← 그날의 "93개 중 정렬 없음"
    maxScan 5000  → 200 개 수집, 정렬 있음      (16ms)
    7,157 개 전수 훑기                          (30ms)

즉 **판단이 모자란 게 아니라 목록에 넣어 주질 않았다.** `[onclick],[tabindex]` 를
더해도 안 나온 이유도 같다 — 선택자를 아무리 넓혀도 4,255 번째까지 가지를 않는다.

오늘 세 번째로 만나는 모양이다: **상한이 여러 군데면 낮은 쪽만 일한다.**
(config dataclass · config 로더 · 그리고 함수 안의 하드 상수)

## 이 시험이 증명하는 것과 못 하는 것

증명한다   상한이 실측한 자리를 덮는다. 두 훑기의 상한이 서로 묶여 있지 않다.
못 한다    지금 이 순간의 다나와가 그대로인지는 모른다(살아 있는 사이트다).
           얼린 화면 위에서 진짜 수집기를 태우는 판은 아직 없다 — `result_list_bench`
           처럼 만들려면 수집기 JS 를 모듈 상수로 빼야 한다. 그게 다음 걸음이다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.browser import _MAX_DEEP_SCAN, _MAX_SCAN

# 실측한 자리. 사이트가 무거워지는 쪽으로 변하므로 여유를 둔다.
MEASURED = {
    # 화면            : (정렬·핵심 조작 요소의 순번, 그 화면의 _INTERACTIVE 총수)
    "danawa_dsearch": (4259, 7157),
}


def test_the_cap_reaches_the_controls_we_measured() -> None:
    for page, (position, total) in MEASURED.items():
        assert _MAX_SCAN > position, (
            f"{page}: 조작 요소가 {position} 번째인데 상한이 {_MAX_SCAN} 이다 — "
            "화면에 보이는 것을 목록에 못 넣는다. 그러면 모델은 '그 화면엔 없다'고 답하고, "
            "그건 사이트가 막은 것과 구별되지 않는다."
        )
        assert total > 0


def test_the_two_scans_have_their_own_caps() -> None:
    """예전에는 두 번째 훑기가 `maxScan * 6` 이었다.

    두 훑기는 비용이 다르다 — 두 번째는 `getComputedStyle(cursor)` 를 부르므로 훨씬
    비싸고 대상도 문서 전체다(다나와 32,954 개). 묶어 두면 첫 번째를 올릴 때 두 번째가
    **조용히 여섯 배**가 된다. 이 시험은 그 연결이 다시 생기는 것을 막는다.
    """
    assert _MAX_DEEP_SCAN != _MAX_SCAN * 6, "두 상한이 다시 묶였다"
    assert _MAX_DEEP_SCAN >= 4200, "두 번째 훑기가 종전보다 좁아졌다"


def test_the_deep_scan_is_not_wired_to_the_first_cap_in_the_script() -> None:
    """상수만 갈라 놓고 스크립트가 옛 식을 쓰고 있으면 아무것도 안 바뀐다."""
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py"
    ).read_text(encoding="utf-8")
    assert "maxScan * 6" not in source, "두 번째 훑기가 아직 첫 상한에 묶여 있다"
    assert "slice(0, maxDeepScan)" in source
