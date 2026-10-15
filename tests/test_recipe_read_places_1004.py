"""레시피가 적어 둔 **읽을 자리**를 읽는다 — 회사 템플릿의 `<main>` 만 읽지 않는다 (2026-10-04 실전 판 e055235f).

사람인 공고 편집기의 템플릿은 본문을 `<main class="job-posting">` 으로 감싼다. 회사가 쓴 영역 **안**의 main 이다.
본문 고르기는 「<main> 이 있으면 그대로 믿는다」 — 그래서 그 안만 읽고, 사람인이 채운 「핵심 정보」(근무형태·급여)와
접수기간을 통째로 버렸다(그 판이 연 공고 11개 중 8개: 451자 · 701자 · 797자 …).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.browser import _EXTRACT_MAIN_JS, BrowserWorker, _clean_lines
from alture_jarvis.config import JarvisConfig
from alture_jarvis.site_recipes import SiteRecipeTools, load_recipes

RECIPES = Path(__file__).resolve().parents[1] / "recipes"
PLACES = [".wrap_jv_header", ".jv_cont.jv_summary", ".jv_cont.jv_detail", ".jv_cont.jv_location", ".jv_cont.jv_howto"]

# 사람인 단독 보기처럼: 사이트가 채운 칸들 사이에, 회사가 쓴 영역 안의 <main>.
SARAMIN_LIKE = """
<html><body><div id="content"><div class="wrap_jview"><section class="jview"><div class="wrap_jv_cont">
<div class="wrap_jv_header"><a href="/c">온새이엔지(주)</a><h1>정부/국책/연구과제 담당 인력 채용</h1></div>
<div class="jv_cont jv_summary"><h2>핵심 정보</h2>
  <dl><dt>근무형태</dt><dd>계약직 12개월</dd></dl><dl><dt>급여</dt><dd>면접 후 결정</dd></dl>
  <dl><dt>근무지역</dt><dd>대전 유성구</dd></dl></div>
<div class="jv_cont jv_detail"><div class="cont"><div class="user_content">
  <main class="job-posting job-posting--table"><h2>모집분야</h2>
  <p>""" + "국책과제 운영 관리와 연구비 집행 및 정산 대응을 맡습니다. " * 8 + """</p></main>
</div></div></div>
<div class="jv_cont jv_location"><h2>근무지위치</h2><p>대전 유성구 테크노2로 14-9</p></div>
<div class="jv_cont jv_howto"><h2>접수기간 및 방법</h2><dl><dt>마감일</dt><dd>2026.10.21 23:59</dd></dl></div>
<div class="jv_cont jv_recommend">""" + "".join(f'<a href="/j{i}">추천 공고 {i} — 다른 회사 연구비 정산 담당 정규직</a> ' for i in range(30)) + """</div>
</div></section></div></div></body></html>
"""


def _evaluate(html: str, places: list[str] | None) -> dict[str, Any]:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_content(html)
            found = page.evaluate(_EXTRACT_MAIN_JS, places) if places else page.evaluate(_EXTRACT_MAIN_JS)
            found["text"] = _clean_lines(found["text"], 10_000)
            return found
        finally:
            browser.close()


# --- 페이지 안 ------------------------------------------------------------------

def test_without_places_the_template_main_hides_the_summary() -> None:
    """고치기 전의 모습 — 이 시험이 통과하지 않게 되면 범용 고르기가 바뀐 것이니 아래 시험의 전제를 다시 볼 것."""
    found = _evaluate(SARAMIN_LIKE, None)

    assert found["selector"].startswith("main.job-posting")
    assert "국책과제 운영 관리" in found["text"]
    assert "계약직 12개월" not in found["text"] and "2026.10.21" not in found["text"]


def test_with_places_the_summary_the_body_and_the_deadline_are_all_read() -> None:
    found = _evaluate(SARAMIN_LIKE, PLACES)
    text = found["text"]

    assert found["selector"].startswith("recipe: ") and found["read_places"] == 5
    assert "근무형태" in text and "계약직 12개월" in text and "면접 후 결정" in text
    assert "국책과제 운영 관리" in text
    assert "대전 유성구 테크노2로 14-9" in text and "2026.10.21 23:59" in text
    assert "추천 공고" not in text, "읽을 자리 밖의 옆 공고는 싣지 않는다"
    assert text.index("계약직 12개월") < text.index("국책과제 운영 관리") < text.index("2026.10.21"), "화면 순서 그대로"


def test_when_the_places_are_gone_it_falls_back_to_the_old_choice() -> None:
    """사이트가 화면을 바꿔 자리가 없어지면 — 빈 글이 아니라 예전 고르기다."""
    found = _evaluate(SARAMIN_LIKE, [".no_such_place", ".another_missing"])

    assert found["selector"].startswith("main.job-posting") and "국책과제 운영 관리" in found["text"]


def test_one_place_alone_is_not_enough() -> None:
    found = _evaluate(SARAMIN_LIKE, [".jv_cont.jv_location", ".no_such_place"])

    assert found["selector"].startswith("main.job-posting")


# --- 어느 화면에 주나 ------------------------------------------------------------

def _worker(places: dict[str, list[tuple[str, list[str]]]]) -> BrowserWorker:
    worker = object.__new__(BrowserWorker)
    worker._recipe_read_selectors = places
    return worker


def test_places_are_given_only_on_the_recipes_site_and_path() -> None:
    worker = _worker({"saramin.co.kr": [("/zf_user/jobs/view", PLACES)]})

    assert worker._read_selectors_for("https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=51000005") == PLACES
    assert worker._read_selectors_for("https://m.saramin.co.kr/zf_user/jobs/view?rec_idx=1") == PLACES
    assert worker._read_selectors_for("https://www.saramin.co.kr/zf_user/search/recruit?searchword=a") == []
    assert worker._read_selectors_for("https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1") == []
    assert worker._read_selectors_for("https://example.com/zf_user/jobs/view?rec_idx=1") == []
    assert worker._read_selectors_for("") == []


def test_a_worker_that_was_never_told_reads_as_before() -> None:
    assert object.__new__(BrowserWorker)._read_selectors_for("https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1") == []


# --- 레시피 → 브라우저 -----------------------------------------------------------

class _Worker:
    def __init__(self) -> None:
        self._recipe_search: dict[str, str] = {}
        self._recipe_result_markers: dict[str, list[str]] = {}
        self._recipe_read_selectors: dict[str, list[tuple[str, list[str]]]] = {}
        self._site_search_delegate: Any = None


def test_the_saramin_recipe_names_the_places() -> None:
    saramin = load_recipes(RECIPES)["saramin"]

    assert saramin.read_selectors == {"/zf_user/jobs/view": PLACES}


def test_the_recipes_tell_the_browser(tmp_path: Path) -> None:
    worker = _Worker()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o", site_recipe_dir=RECIPES)
    tools = SiteRecipeTools(config, worker)
    tools._tell_browser_about_search_recipes()

    assert worker._recipe_read_selectors.get("saramin.co.kr") == [("/zf_user/jobs/view", PLACES)]
