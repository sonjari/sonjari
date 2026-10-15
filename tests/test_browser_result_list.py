"""결과 목록을 **구조로** 찾는다 — 배너가 1번을 차지하지 못하게.

2026-08-12 실측. 한 번도 안 건드린 사이트 네 곳에 같은 고리를 태웠더니 문은 다
열리는데(사이트 진입·팝업 정리·검색칸 채우기) **1번이 전부 엉뚱했다**:

    다나와 "무선마우스"  → 1번이 경쟁사(에누리) 광고
    교보문고 "회계"      → 1번이 "오늘의 미션"
    당근마켓 "책상"      → 1번이 "당근 알바"

`collect_results` 는 검색엔진 SERP 용이라 "본문 링크를 DOM 순서로"가 전부다.
쇼핑몰·서점은 본문 앞머리가 배너·기획전이라 그게 1번이 된다. 잡코리아가 잘 됐던 건
목록이 마침 앞에 있어서였다 — 운이었다.

목록은 어디서나 같은 모양이다: **비슷한 형제가 여러 개 반복되고 각각이 링크를 품는다.**

여기서 지키는 것 넷:

  1. 목록 안의 것만 순위에 넣는다
  2. 목록을 못 찾으면 **예전대로** 간다 — 새 판정이 조용히 결과를 지우면 안 된다
  3. 셋 미만은 목록이라 부르지 않는다 (배너 두 개짜리를 목록으로 오인하지 않기)
  4. 사이트 이름은 한 줄도 안 쓴다
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _rows_of(urls: list[str] | None) -> list[dict[str, Any]]:
    return [{"name": f"항목 {i}", "href": url, "ref": ""} for i, url in enumerate(urls or [], 1)]


def _worker(tmp_path: Path, listed: list[str] | None) -> BrowserWorker:
    worker = BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            browser_evidence_dir=tmp_path / "evidence",
        )
    )
    worker._frames_of = lambda page: ["f0"]  # type: ignore[method-assign]
    worker._chrome_links = lambda page: set()  # type: ignore[method-assign]
    worker._result_list_rows = lambda page: _rows_of(listed)  # type: ignore[method-assign]
    return worker


_BANNER = {"name": "여름 대특가 기획전", "href": "https://shop.example.com/event/summer", "ref": "j1"}
_ADVERT = {"name": "최저가로 산다! 에누리", "href": "https://www.enuri.com/", "ref": "j2"}
_ITEMS = [
    {"name": "로지텍 M170 무선마우스", "href": "https://shop.example.com/goods/1", "ref": "j3"},
    {"name": "앱코 무선마우스", "href": "https://shop.example.com/goods/2", "ref": "j4"},
    {"name": "삼성 무선마우스", "href": "https://shop.example.com/goods/3", "ref": "j5"},
]


def _rows() -> list[dict[str, Any]]:
    return [_BANNER, _ADVERT, *_ITEMS]


def test_the_banner_no_longer_takes_rank_one(tmp_path: Path) -> None:
    worker = _worker(tmp_path, [item["href"] for item in _ITEMS])
    worker._frame_elements = lambda frame, **kwargs: _rows()  # type: ignore[method-assign]

    results = worker._collect_results(object(), limit=10)

    assert results, "결과가 통째로 사라졌다"
    assert results[0]["url"] == "https://shop.example.com/goods/1"
    assert all("enuri" not in item["url"] for item in results), "광고가 남아 있다"


def test_without_a_detected_list_nothing_changes(tmp_path: Path) -> None:
    """새 판정이 조용히 결과를 지우는 일은 없어야 한다."""
    worker = _worker(tmp_path, None)
    worker._frame_elements = lambda frame, **kwargs: _rows()  # type: ignore[method-assign]

    results = worker._collect_results(object(), limit=10)

    assert len(results) == 5
    assert results[0]["url"] == "https://shop.example.com/event/summer"


def test_a_two_item_group_is_not_treated_as_a_list(tmp_path: Path) -> None:
    """배너 두 개짜리를 목록으로 오인하면 진짜 목록이 통째로 날아간다."""
    worker = _worker(tmp_path, [_BANNER["href"], _ADVERT["href"]])
    worker._frame_elements = lambda frame, **kwargs: _rows()  # type: ignore[method-assign]

    results = worker._collect_results(object(), limit=10)

    assert len(results) == 5, "둘뿐인 묶음을 목록으로 보고 나머지를 버렸다"


def test_the_detector_is_site_agnostic() -> None:
    """사이트 이름이 코드에 들어가는 순간 그 목록은 영원히 안 끝난다."""
    source = BrowserWorker._RESULT_LIST_JS.lower()

    for name in ("danawa", "kyobo", "daangn", "jobkorea", "saramin", "coupang", "naver"):
        assert name not in source


def test_navigation_is_excluded_and_length_beats_count() -> None:
    """2026-08-12 실측(당근마켓): 카테고리 메뉴가 진짜 목록을 이겼다.

        [11점] 네비 <nav>  링크10 평균 6자   ← 이김
        [ 9점] 본문 <div>  링크4  평균 51자  ← 진짜 목록

    개수로 재면 메뉴가 이긴다. 목록 항목에는 제목·가격·지역이 붙어 길고,
    메뉴는 낱말 하나라 짧다 — 그 차이가 판정의 근거다.
    """
    source = BrowserWorker._RESULT_LIST_JS

    assert "closest(CHROME)" in source, "네비게이션을 빼지 않으면 메뉴가 목록을 이긴다"
    assert "nav" in source and "footer" in source
    assert "average < 12" in source, "짧은 낱말 묶음(메뉴)을 걸러내지 않는다"
    assert "links.length * Math.min(average" in source, "개수만으로 재면 안 된다"


def test_link_destinations_must_be_homogeneous() -> None:
    """2026-08-12 실측(다나와): 개수와 길이만으로도 진짜 목록이 진다.

        n=241 평균12자 prod_info      "브랜드로그 | 의견194"   <- 이겼다
        n=76  평균15자 prod_main_info "ATK VXE R1 SE+ 유무선"  <- 진짜 목록

    상품 카드 하나가 링크를 여러 개 낸다(제목·브랜드로고·의견수·쇼핑몰). 부속 링크는
    목적지가 제각각이고, 진짜 항목은 **같은 모양의 상세 페이지**로 모인다.
    """
    source = BrowserWorker._RESULT_LIST_JS

    assert "shapeOf" in source, "목적지 모양을 안 본다"
    assert "homogeneity" in source
    # 앞 두 칸만 본다. 숫자만 지우면 슬러그 주소(/kr/buy-sell/원목-책상-xy)가
    # 항목마다 달라져 동질성이 2%로 떨어진다(당근마켓 실측).
    assert "slice(0, 2)" in source, "경로를 앞 두 칸으로 줄이지 않는다"
    assert "/\\d/.test(part)" in source, "숫자가 든 칸을 정규화하지 않는다"


def test_the_list_items_do_not_depend_on_the_scan_budget(tmp_path: Path) -> None:
    """2026-08-12 다나와 실측. 링크 1,561개 · 수집 예산 144개인데 앞에 스펙 필터가
    링크 724개를 깔고 있어 예산이 거기서 다 소진됐다. 판정기가 상품 묶음(75개)을
    정확히 골라 놨는데도 그 주소들이 rows 에 아예 없어 좁히기가 무의미했다.

    묶음 상한으로 막아 보려다 더 나빠졌다 — 우리가 원하는 것이 바로 그 큰 묶음이라
    잘라 내면 결과가 사라진다(당근마켓 12건 → 0건).

    판정기는 이미 브라우저 안에서 모든 링크를 한 번에 훑는다. 항목을 직접 받아 오면
    예산 문제 자체가 없어진다.
    """
    worker = _worker(tmp_path, [item["href"] for item in _ITEMS])
    # 예산이 바닥나 아무것도 못 훑은 상황.
    worker._frame_elements = lambda frame, **kwargs: []  # type: ignore[method-assign]

    results = worker._collect_results(object(), limit=12)

    assert len(results) == 3, "훑기 예산과 무관하게 목록 항목을 받아 와야 한다"
    assert results[0]["url"] == "https://shop.example.com/goods/1"


def test_links_back_to_this_very_page_are_not_items() -> None:
    """광고를 걷어내니 이번엔 **검색 페이지 자체**가 1번이 됐다(다나와·교보문고).

    목록 안에는 쪽번호·정렬·필터처럼 같은 주소로 되돌아가는 링크가 섞여 있고,
    경로가 같아 동질성 점수까지 끌어올린다. 항목은 **다른 곳으로** 간다.
    """
    source = BrowserWorker._RESULT_LIST_JS

    assert "const here = pathOf(location.href)" in source
    assert "pathOf(a.href) === here) continue" in source, "자기 페이지 링크를 안 뺀다"


def test_self_detection_is_exact_while_homogeneity_is_coarse() -> None:
    """두 판정은 목적이 다르다 — 잣대를 하나로 합쳤다가 매물 60개를 통째로 잃었다.

    2026-08-12 당근마켓 실측:
        현재  /kr/buy-sell/s/?search=책상   -> 앞 두 칸 kr/buy-sell
        매물  /kr/buy-sell/원목-책상-xxx/    -> 앞 두 칸 kr/buy-sell   (같아져 버림)

    보이는 링크 167개 중 네비 104 · 묶음없음 3 · **자기페이지 60** → 후보 0개.

    동질성은 거칠게(앞 두 칸) 묶어야 슬러그 주소가 한 덩어리가 되고,
    자기 페이지는 경로 전체로 봐야 항목을 안 버린다.
    """
    source = BrowserWorker._RESULT_LIST_JS

    assert "const pathOf" in source and "const shapeOf" in source, "판정이 둘로 갈라져 있어야 한다"
    # 자기 페이지 쪽은 경로를 자르지 않는다.
    assert "u.host + u.pathname.replace(/\\/+$/, '')" in source


def test_card_sublinks_are_left_alone_on_purpose() -> None:
    """카드마다 대표 하나만 남기는 규칙을 넣어 봤다가 **되돌렸다** (2026-08-12).

    사람인은 깨끗해졌다(80개 → 38개, 전부 진짜 공고). 그런데 같은 규칙에
    교보문고와 다나와가 함께 망가졌다 — 그 카드들에서는 제일 긴 글자가 제목이 아니라
    브랜드·기획전이라, 1번이 "바로펀딩"·"Bravotec 브랜드로그"로 바뀌었다.

    섞이는 것은 성가신 정도지만(1번은 여전히 진짜 항목이다) 1번이 엉뚱해지는 것은
    답을 통째로 틀리게 만든다. **고칠 값보다 깨뜨릴 값이 크면 안 고친다** —
    오늘 같은 종류의 되돌리기가 세 번째다(묶음 상한·앞 두 칸·카드 대표).

    이 시험은 그 판단을 기록으로 남긴다. 다시 넣고 싶으면 세 사이트를 함께 재라.
    """
    source = BrowserWorker._RESULT_LIST_JS

    assert "CARD_LINKS" not in source
    assert "되돌렸다" in source, "왜 안 고쳤는지가 코드에 남아 있어야 한다"


def test_same_looking_groups_are_merged() -> None:
    """목록이 4개씩 세 덩어리로 쪼개진 사이트가 있다(당근마켓). 하나만 고르면 4건뿐이다."""
    assert "signature" in BrowserWorker._RESULT_LIST_JS
