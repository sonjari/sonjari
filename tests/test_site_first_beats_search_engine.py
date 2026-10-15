"""지목받은 사이트가 있으면 **검색엔진보다 그 사이트가 먼저**다.

## 왜 이 시험이 생겼나 (2026-08-14)

프롬프트에는 이 규칙이 일곱 줄로 적혀 있었다 — "갈 곳을 알면 검색엔진을 거치지
마라", 광고 브리지 실측까지 붙여서. 그런데 같은 과제 다섯 판 중 셋이 그 안내를
받고도 `browser_search` 로 시작했다. 첫 도구로 갈라 재면 이렇다:

    browser_open 직행      103 · 137 · 188 초     전부 깨끗
    browser_search 경유    142 · 147 · 180 · 224 초   셋이 **틀린 답**

경유가 느리기만 한 게 아니다. 네이버 결과의 다나와 링크가 다나와의 **광고
브리지**라 열자마자 스마트스토어로 넘어가고, 거기 가격을 "다나와 상위 3개"로
답한다. 실패할 때마다 **매번 같은 광고 상품**이 나왔다 — 고정된 함정이다.

그래서 안내를 코드로 옮겼다(사고 R: 결정론으로 박을 수 있으면 코드로).

## 무엇을 지켜야 하나

돌리는 것만큼 **안 돌리는 것**이 중요하다. 막기만 하면 길이 끊긴다 —
사고 R 의 두 번째 교훈이 그거다(막았더니 사람이 검토한 레시피까지 걸렸다).
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import site_first_target
from alture_jarvis.site_atlas import SiteAtlas


def _atlas(tmp_path: Path) -> SiteAtlas:
    """다나와를 아는 아틀라스. 배우는 조건(서로 다른 2 장·단일 도메인)을 실제로 태운다."""
    atlas = SiteAtlas(tmp_path / "atlas.json")
    atlas.learn("다나와", "https://prod.danawa.com/info/?pcode=1", "다나와 (가격비교)")
    atlas.learn("다나와", "https://search.danawa.com/dsearch.php?query=x", "다나와 (가격비교)")
    return atlas


def _step(url: str) -> dict:
    return {"tool": "browser_open", "ok": True, "evidence": {"url": url}}


def test_named_site_beats_the_search_engine(tmp_path: Path) -> None:
    atlas = _atlas(tmp_path)
    assert site_first_target("다나와에서 무선마우스 상위 3개 알려줘", [], atlas) == (
        "다나와",
        "danawa.com",
    )


def test_it_lets_go_once_we_have_been_there(tmp_path: Path) -> None:
    """거기 갔는데 없어서 웹으로 넓히는 것은 **정상적인 판단**이다.

    이 조건이 무한 루프도 같이 막는다 — 돌려보낸 browser_open 이 호스트를
    기록하므로 다음 browser_search 는 그냥 나간다.
    """
    atlas = _atlas(tmp_path)
    steps = [_step("https://www.danawa.com/")]
    assert site_first_target("다나와에서 무선마우스 상위 3개 알려줘", steps, atlas) is None


def test_a_subdomain_counts_as_having_been_there(tmp_path: Path) -> None:
    """`search.danawa.com` 은 다나와다. 이걸 못 알아보면 갔는데도 계속 돌린다."""
    atlas = _atlas(tmp_path)
    steps = [_step("https://search.danawa.com/dsearch.php?query=%EB%A7%88%EC%9A%B0%EC%8A%A4")]
    assert site_first_target("다나와에서 마우스 알려줘", steps, atlas) is None


def test_an_unknown_name_is_left_alone(tmp_path: Path) -> None:
    """모르는 이름은 아무것도 안 한다. 추측해서 엉뚱한 곳으로 보내면 그게 더 나쁘다."""
    atlas = _atlas(tmp_path)
    assert site_first_target("골리에서 무선마우스 알려줘", [], atlas) is None


def test_an_ambiguous_word_is_left_alone(tmp_path: Path) -> None:
    """"광양"처럼 두 도메인에 걸리는 낱말은 이름이 아니다.

    `atlas.host_for` 가 이미 빈 문자열을 주지만, **라우팅에서 이게 뚫리면
    자비스가 엉뚱한 사이트로 간다** — 판정이 틀리는 것보다 나쁘다. 그래서 여기서
    한 번 더 못 박는다.
    """
    atlas = _atlas(tmp_path)
    atlas.learn("광양", "https://job.gwangyang.go.kr/view.do?no=1", "광양 일자리")
    atlas.learn("광양", "https://job.gwangyang.go.kr/view.do?no=2", "광양 일자리")
    atlas.learn("광양", "https://www.jobkorea.co.kr/Search/?stext=광양", "광양 채용 | 잡코리아")
    atlas.learn("광양", "https://www.jobkorea.co.kr/Recruit/1", "광양 채용 | 잡코리아")
    assert site_first_target("광양에서 회계 채용 알려줘", [], atlas) is None


def test_asking_for_the_search_engine_itself_is_not_redirected(tmp_path: Path) -> None:
    """"네이버에서 찾아줘"는 검색엔진으로 가라는 뜻이다. 돌릴 곳이 없다."""
    atlas = _atlas(tmp_path)
    atlas.learn("네이버", "https://blog.naver.com/a/1", "네이버 블로그")
    atlas.learn("네이버", "https://blog.naver.com/b/2", "네이버 블로그")
    assert site_first_target("네이버에서 무선마우스 후기 찾아줘", [], atlas) is None
