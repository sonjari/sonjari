"""요약은 바깥, 본문은 안쪽 틀 — 둘 다 읽는다 · 쌓인 다음 항목은 읽지 않는다 · 그림 본문은 그림이라고 말한다 (2026-10-04 채용 공고 조사 판 788ef850).

사람인 「이어 보기」는 연 공고 아래에 다음 공고들을 틀째 쌓는다(`iframe_content_0`·`_1`·`_2`). 점수 높은 틀 하나만 고르던 추출은
공고 21개를 열어 **제 공고의 상세 본문을 2개만** 읽었다 — 17개는 바깥 요약만, 2개는 옆 공고(두레기계공업)를 읽었다(두 번, 글자 하나 안 틀리고 같음).
그 21개의 본문을 재 보니 사람인 기본 양식 15 · 회사가 직접 짠 표 템플릿 4(셋은 `<th>` 없음) · 통이미지 1~2 였다.
"""
from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker, single_item_view

SUMMARY = "핵심 정보\n근무형태\n정규직 수습기간 3개월\n급여\n면접 후 결정\n근무지역\n대전 유성구\n" + "회사 소개가 이어집니다. " * 40
OWN_BODY = "모집부문\n정부R&D 사업관리 담당자\n자격요건\nRCMS, IRIS 사용 경험\n우대사항\n연구비 정산 경력\n" + "상세 업무 설명입니다. " * 30
NEXT_BODY = "2026 RECRUIT\n두레기계공업(주)\n각 부문별 신입/경력 채용공고\n" + "공기압축기 제조 사업을 하고 있습니다. " * 60


class _Frame:
    def __init__(self, name: str, url: str, found: dict[str, Any] | None) -> None:
        self.name, self.url, self._found = name, url, found

    def is_detached(self) -> bool:
        return False

    def evaluate(self, _script: str) -> dict[str, Any] | None:
        return self._found


class _Page:
    def __init__(self, url: str, frames: list[_Frame]) -> None:
        self.url, self.frames, self.main_frame = url, frames, frames[0]


def _found(text: str, **extra: Any) -> dict[str, Any]:
    return {"score": len(text), "text": text, "selector": "div", "link_ratio": 0, "big_images": 0, "tall_images": 0, **extra}


def _worker() -> BrowserWorker:
    worker = object.__new__(BrowserWorker)
    worker._last_results = []
    worker._reads_since_search = 0
    worker._visited = []
    worker._sweep_for_lazy_content = lambda page: None  # type: ignore[method-assign]
    worker._deep_text = lambda page, limit: ""  # type: ignore[method-assign]
    worker._visible_rollers = lambda page, text: text  # type: ignore[method-assign]
    worker._evidence = lambda action, **kw: {"action": action, **kw}  # type: ignore[method-assign]
    worker._mark_visited = lambda url: None  # type: ignore[method-assign]
    worker._navigation_never_committed = lambda frame: False  # type: ignore[method-assign]
    return worker


def _extract(frames: list[_Frame], url: str = "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1") -> dict[str, Any]:
    return _worker()._extract(_Page(url, frames), {})


SITE = "https://www.saramin.co.kr/zf_user/jobs/relay/view-detail?rec_idx="


# --- 바깥 글 + 안쪽 본문 틀 -----------------------------------------------------

def test_the_summary_outside_and_the_body_frame_are_both_read() -> None:
    out = _extract([_Frame("", "https://www.saramin.co.kr/x", _found(SUMMARY)), _Frame("iframe_content_0", SITE + "1", _found(OWN_BODY))])

    assert "정규직 수습기간 3개월" in out["text"] and "RCMS, IRIS 사용 경험" in out["text"]
    assert out["text"].index("정규직 수습기간 3개월") < out["text"].index("RCMS, IRIS 사용 경험"), "요약이 앞, 본문이 뒤"
    assert "[이 페이지 안쪽 틀 「iframe_content_0」의 글 — 상세 본문]" in out["text"]
    assert out["merged_frame"] == "iframe_content_0" and out["frame"] == "main + iframe_content_0"


def test_a_body_frame_that_scores_higher_no_longer_hides_the_summary() -> None:
    """그 판의 16·18걸음 — 본문 틀(17,234자)이 이겨 바깥의 근무형태·급여를 잃었다."""
    long_body = OWN_BODY * 20
    out = _extract([_Frame("", "https://www.saramin.co.kr/x", _found(SUMMARY)), _Frame("iframe_content_0", SITE + "1", _found(long_body))])

    assert "정규직 수습기간 3개월" in out["text"] and "RCMS, IRIS 사용 경험" in out["text"]


def test_the_next_items_stacked_below_are_not_this_page() -> None:
    """`iframe_content_1`·`_2` 는 다음 공고다 — 더 길어도 고르지 않는다(그 판의 44·48걸음)."""
    out = _extract([
        _Frame("", "https://www.saramin.co.kr/x", _found(SUMMARY)),
        _Frame("iframe_content_0", SITE + "1", _found(OWN_BODY)),
        _Frame("iframe_content_1", SITE + "2", _found(NEXT_BODY)),
        _Frame("iframe_content_2", SITE + "3", _found(NEXT_BODY * 2)),
    ])

    assert "RCMS, IRIS 사용 경험" in out["text"]
    assert "두레기계공업" not in out["text"]


def test_a_frame_from_another_site_is_not_stitched_in() -> None:
    """광고 틀은 호스트가 다르다 — 본문으로 합치지 않는다."""
    ad = "광고: 지금 가입하면 3개월 무료. " * 20
    out = _extract([_Frame("", "https://www.saramin.co.kr/x", _found(SUMMARY)), _Frame("ad_frame", "https://ads.example.net/slot", _found(ad))])

    assert "merged_frame" not in out
    assert "안쪽 틀" not in out["text"]


def test_a_page_whose_text_all_lives_in_one_frame_reads_as_before() -> None:
    """네이버 블로그처럼 바깥엔 글이 없고 틀 하나에 본문이 있는 페이지 — 예전처럼 그 틀을 읽는다."""
    out = _extract([_Frame("", "https://blog.naver.com/a/1", None), _Frame("mainFrame", "https://blog.naver.com/PostView", _found(OWN_BODY))],
                   url="https://blog.naver.com/a/1")

    assert out["text"].startswith("모집부문") and out["frame"] == "mainFrame" and "merged_frame" not in out


def test_a_long_outer_text_gives_way_to_the_body() -> None:
    outer = SUMMARY + "추천 공고 목록이 길게 이어집니다. " * 1200
    out = _extract([_Frame("", "https://www.saramin.co.kr/x", _found(outer)), _Frame("iframe_content_0", SITE + "1", _found(OWN_BODY))])

    assert "RCMS, IRIS 사용 경험" in out["text"], "바깥 글이 길어도 본문 틀이 잘려 나가면 안 된다"
    assert "바깥 글은 여기까지만" in out["text"]


# --- 그림 본문 -----------------------------------------------------------------

def test_a_body_that_is_one_picture_is_called_a_picture() -> None:
    """글자 0자·그림 1장인 본문 틀 — 「조건이 안 적혀 있다」가 아니라 「못 읽었다」."""
    out = _extract([
        _Frame("", "https://www.saramin.co.kr/x", _found(SUMMARY)),
        _Frame("iframe_content_0", SITE + "1", {"score": -1, "text": "", "big_images": 1, "tall_images": 1}),
    ])

    assert out["image_body"] is True and out["tall_images"] == 1
    assert out["instruction"].startswith("★") and "그림이라 확인 못 함" in out["instruction"]
    assert "정규직 수습기간 3개월" in out["text"], "바깥 요약은 그대로 준다"


def test_almost_no_text_and_big_pictures_says_so() -> None:
    out = _extract([_Frame("", "https://smartstore.naver.com/x/products/1", _found("상품 상세 " * 30, big_images=6))],
                   url="https://smartstore.naver.com/x/products/1")

    assert out["image_body"] is True and "큰 그림이 6장" in out["image_body_note"]


def test_an_article_with_a_few_photos_is_left_alone() -> None:
    out = _extract([_Frame("", "https://example.com/post", _found(OWN_BODY * 3, big_images=3))], url="https://example.com/post")

    assert "image_body" not in out and not out["instruction"].startswith("★")


# --- 사람인: 공고 하나만 나오는 주소로 ---------------------------------------------

def test_a_stacked_view_address_becomes_the_single_item_address() -> None:
    relay = "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=51000001&location=ts&searchword=x#seq=0"

    assert single_item_view(relay) == "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=51000001"


@pytest.mark.parametrize("url", [
    "https://www.saramin.co.kr/zf_user/search/recruit?searchword=회계",          # 목록
    "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=51000001",            # 이미 단독 보기
    "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=",              # 번호 없음
    "https://example.com/zf_user/jobs/relay/view?rec_idx=1",                   # 다른 사이트
    "https://www.jobkorea.co.kr/Recruit/GI_Read/12345",
])
def test_other_addresses_are_untouched(url: str) -> None:
    assert single_item_view(url) == url


def test_reviewed_procedures_keep_their_address() -> None:
    """스크랩·관심기업 절차는 이어 보기 화면에서 셀렉터를 세어 정했다 — 검토된 주소는 바꾸지 않는다."""
    import inspect

    source = inspect.getsource(BrowserWorker._open)

    assert "if not trusted:" in source and "url = single_item_view(url)" in source
    assert "single_item_view(self._validate_url(raw_url))" in inspect.getsource(BrowserWorker._open_result)
