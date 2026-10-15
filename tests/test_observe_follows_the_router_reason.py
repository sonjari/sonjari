"""「근거가 되는 대상 실제로 읽기」는 **라우터가 왜 봐야 한다고 했는지**를 따른다 (2026-09-30).

전에는 라우터가 참/거짓 하나만 넘겼고, 계획 층이 읽을 곳을 낱말(「열어서」)로 다시 추측했다. 그래서
로컬 파일을 열어 읽으라는 말에 브라우저 읽기를 요구했다. 지난 요청 1,274개로 재 봤다 — 바뀐 것은
로컬 읽기 17개(browser→local)와 워드클라우드 1개(조사로 오분류)뿐이고, 웹 판정은 나머지 전부 그대로다.
"""

from __future__ import annotations

from alture_jarvis import plan
from alture_jarvis.runtime import JarvisRuntime

WORDCLOUD = (
    "'로컬 AI', '정직', '한국 사이트', '손자리', '검증', '브라우저', '문서', '엑셀' 같은 단어로 "
    "한글 워드클라우드 PNG 이미지를 만들어서 바탕화면에 sonjari_wordcloud.png 로 저장해 줘."
)


def _observe(prompt: str, **kw):
    return [r for r in plan.extract(prompt, **kw) if r.kind == "observe"]


def test_words_to_put_in_quotes_are_not_an_order_to_research() -> None:
    """따옴표 안은 **넣을 내용**이다. 「'브라우저'」라는 낱말을 그리라고 한 것은 브라우저를 쓰라는 말이 아니다."""
    assert not JarvisRuntime._requires_web_research(WORDCLOUD)


def test_the_research_verb_outside_the_quotes_still_counts() -> None:
    """역방향 — 조사하라는 말이 따옴표 **밖**에 있으면 그대로 조사다."""
    assert JarvisRuntime._requires_web_research("'로컬 AI 에이전트' 를 조사해서 워드클라우드로 만들어 줘")
    assert JarvisRuntime._requires_web_research("브라우저로 '손자리' 검색해서 알려줘")


LOCAL_READ = r"C:\work\monorepo\CLAUDE.md 파일을 열어서 첫 번째 제목 줄만 그대로 알려 줘."


def test_a_local_reason_does_not_demand_a_browser_read() -> None:
    """라우터가 **이 PC 때문에** 켠 읽기는 브라우저 읽기가 아니다 — 브라우저로 억지로 읽히는 쪽으로 밀면 안 된다."""
    (req,) = _observe(LOCAL_READ, must_observe=True, observe_from={"local"})
    assert req.target == "local"


def test_a_web_reason_still_demands_a_browser_read() -> None:
    (req,) = _observe("webawesome.com 사이트를 열어서 첫 문단을 그대로 알려줘", has_named_source=True,
                      must_observe=True, observe_from={"web", "named"})
    assert req.target == "browser"


def test_old_callers_without_a_reason_keep_the_old_guess() -> None:
    """이유를 안 넘기는 호출(옛 경로·시험)은 예전 그대로 — 조용히 동작이 바뀌지 않게."""
    (req,) = _observe(LOCAL_READ, must_observe=True)
    assert req.target == "browser"


def test_an_address_to_put_into_the_output_is_not_a_source() -> None:
    """「네이버 링크를 담은 QR」의 네이버는 **넣을 주소**다 — 읽을 출처가 아니다."""
    assert not _observe("네이버 링크를 담은 QR 코드 PNG 를 만들어 줘", has_named_source=True,
                        must_observe=True, observe_from={"named"})


def test_finding_then_embedding_still_has_to_read() -> None:
    """역방향 — 찾아서 넣으라고 했으면 찾는 것(읽기)이 먼저다."""
    assert _observe("yes24.com 에서 클린 코드 책을 찾아서 그 링크를 담은 문서를 만들어 줘", has_named_source=True,
                    must_observe=True, observe_from={"web", "named"})
