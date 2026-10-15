from __future__ import annotations

from pathlib import Path

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.plopfit import PlopfitTools


# ── 엔진 고르기 (2026-08-12 전제가 뒤집혀 갱신) ─────────────────────────────
#
# 예전 지식은 "빙·구글은 상시 차단"이라 국내는 네이버, 해외는 빙이었다. 그런데 그
# 차단은 **Playwright 가 띄운 크롬**(자동화 모드)에서 잰 것이었다. 진짜 크롬에 붙기
# 시작하자 같은 질의로:
#
#     구글    ok · 결과 8건 · 폴백 없음   (langchain.com 등 영어권 원문)
#     빙      여전히 막힘 → 네이버 폴백
#     네이버  ok
#
# 쿠팡과 정확히 같은 이야기다 — 사이트가 아니라 우리가 문제였다.


def test_browser_auto_routes_korean_to_naver() -> None:
    assert BrowserWorker._search_engines("여수 지역 AI 지원사업", "auto") == ["naver", "google"]


def test_browser_auto_routes_technical_queries_to_google() -> None:
    """예전에는 빙으로 보냈다. 빙은 아직 막히고 구글은 이제 열린다."""
    assert BrowserWorker._search_engines("Playwright 공식 문서", "auto") == ["google", "naver"]


def test_google_search_has_a_non_google_fallback() -> None:
    assert BrowserWorker._search_engines("테스트", "google") == ["google", "naver"]


def test_bing_is_never_chosen_on_its_own() -> None:
    """막히는 엔진을 기본으로 두면 매번 한 번씩 헛걸음한다."""
    for query in ("여수 채용 공고", "Playwright docs", "AI agent framework"):
        assert BrowserWorker._search_engines(query, "auto")[0] != "bing"


# ── 프롬프트가 도구와 어긋나 있으면 도구는 있어도 안 불린다 ───────────────────
#
# 2026-08-06 실측: 블로그 후기 3개를 읽어 달라고 했더니 browser_search 8번,
# browser_extract 1번. 그리고 답은 후기가 아니라 시장 단가 가이드로 대체됐다.
#
# 도구는 멀쩡했다. 시스템 프롬프트가 "한국어·국내 웹 자료는 먼저 naver_web" 이라고
# 말하고 있었고, 그건 browser_search 가 결과를 하나도 안 주던 시절의 지침이었다.
# 전제가 거짓이 된 문서가 남아 사고를 만든 것은 이번이 처음이 아니다(사고 P).
#
# 프롬프트에 새 고리가 적혀 있는지를 여기서 지킨다.

from alture_jarvis.agent import AGENT_SYSTEM_PROMPT


def test_the_prompt_routes_korean_blog_research_to_the_browser_not_the_api() -> None:
    assert 'tab="blog"' in AGENT_SYSTEM_PROMPT
    # API 를 "먼저" 쓰라고 남아 있으면 브라우저 경로가 통째로 우회된다.
    assert "먼저 naver_web" not in AGENT_SYSTEM_PROMPT
    assert "폴백이다" in AGENT_SYSTEM_PROMPT


def test_the_prompt_names_the_whole_drill_in_loop() -> None:
    for tool in ("browser_open_result", "browser_extract", "browser_links"):
        assert tool in AGENT_SYSTEM_PROMPT, f"{tool} 이 프롬프트에 없으면 모델은 그 도구를 짐작해야 한다"


def test_the_prompt_forbids_the_site_operator() -> None:
    # 네이버는 site: 를 모른다. 실측에서 모델이 두 번 썼고 두 번 다 빈손이었다.
    assert "site: 연산자를 쓰지 마라" in AGENT_SYSTEM_PROMPT


def test_the_prompt_says_to_read_more_than_one_source() -> None:
    assert "browser_open_result를 N번" in AGENT_SYSTEM_PROMPT
    assert "다시 검색하지 마라" in AGENT_SYSTEM_PROMPT


def test_the_prompt_forbids_answering_a_different_question() -> None:
    # 실제 후기를 요청받고 시장 단가 가이드를 대신 내놓은 것이 이번 실패의 마무리였다.
    assert "다른 주제로 바꿔 답하지 마라" in AGENT_SYSTEM_PROMPT


def test_plopfit_agent_catalog_reuses_naver_and_github_without_tavily(tmp_path: Path) -> None:
    tools = PlopfitTools(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            plopfit_enabled=True,
        )
    )
    assert {"naver_web", "naver_news", "github_search"} <= tools.names
    assert "tavily_search" not in tools.names


# ── Naver blog: routed deterministically, not left to the model ──────────────
# The incident: asked to post to the blog, the model chose the general browser
# agent and spent the session hunting a 글쓰기 button on the blog home page,
# reporting "버튼이 안 보이네요" while the button was plainly on screen. It never
# needed the button -- naver_blog_fill_editor opens GoBlogWrite.naver directly.
import pytest

from alture_jarvis.runtime import JarvisRuntime


@pytest.mark.parametrize(
    "prompt",
    [
        "블로그에 로보메타핏 관련 글 직접 브라우저에서 폼넣고 작성해주라",
        "네이버 블로그에 이 내용 올려줘",
        "블로그 초안 임시저장까지 해줘",
        "포스팅 하나 써줘 블로그에",
        "블로그에 발행해줘",
    ],
)
def test_blog_authoring_is_routed_to_the_blog_tools(prompt) -> None:
    assert JarvisRuntime._requires_naver_blog(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "블로그 글은 보통 어떻게 쓰는 게 좋아?",   # a question about blogs
        "블로그 방문자 수 알려줘",                  # reading, not authoring
        "이 내용 정리해줘",                         # no platform named
        "메일 하나 써줘",                           # authoring, but not a blog
    ],
)
def test_talking_about_blogs_does_not_open_an_editor(prompt) -> None:
    # A verb alone, or a platform alone, must not drag the browser open --
    # the same trap the camera router had with "고개를 왼쪽으로 돌려봐".
    assert JarvisRuntime._requires_naver_blog(prompt) is False


# ── person search: routed deterministically, not left to the model ──────────
# The incident: "가람 좀 찾아봐" with the tablet fully offline reached
# _general_route's coarse tool menu (look_at_camera / use_camera_control only
# -- no "sweep the room for someone" option exists there), the model picked
# look_at_camera, that asked for a single frame that did not exist, and the
# resulting camera_frame_unavailable propagated all the way to a dead job with
# no reply at all. camera_find_person only exists inside the full agent
# toolset, so this has to be routed there directly.
@pytest.mark.parametrize(
    "prompt",
    [
        "가람 좀 찾아봐",
        "가람 좀 봐봐",
        "나래이 어디 있나 찾아줘",
        "누구 있나 둘러봐",
        "사무실에 사람 있나 둘러봐줘",
    ],
)
def test_person_search_is_routed_to_the_agent(prompt) -> None:
    assert JarvisRuntime._requires_person_search(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "인터넷에서 로보메타핏 관련 뉴스 찾아봐",   # 찾아봐 alone means web search
        "이 파일 좀 찾아줘",                         # local file search
        "블로그에서 그 글 찾아줘",                    # blog domain, not the camera
        "메일함에서 아까 그거 찾아줘",                 # mail domain, not the camera
        "가람가 누군지 설명해줘",                      # no search verb at all
    ],
)
def test_web_and_file_search_do_not_trigger_a_camera_sweep(prompt) -> None:
    # "찾아봐" is heavily overloaded -- BrowserAgent's own fallback treats it as
    # "search the web". The exclusion list is what keeps this from hijacking
    # every unrelated "find X" request into a room sweep.
    assert JarvisRuntime._requires_person_search(prompt) is False
