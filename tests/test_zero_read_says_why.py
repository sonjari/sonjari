"""「0개 읽음」이면 **왜 0인지 같이 말한다** (2026-09-21 실전).

## 무슨 일이 있었나

「깃허브 오픈소스 10개 찾아서 문서로」 판에서 모델이 8쪽을 열어 읽었다 —
huggingface.co 4곳, mastra.ai, is4.ai, youtube.com 2곳. 그런데 체크리스트는 이랬다:

    10개 이상 직접 열어 읽기        0개 읽음
    깃허브에서 하기                거기서 아무것도 안 함

**숫자는 맞다.** 「깃허브에서 하기」가 있으면 읽기는 github.com 것만 센다. 하지만
모델도 사람도 「0개 읽음」만 보면 *아무것도 안 읽은 줄* 안다. 모델은 실제로 8번
읽었으므로 「더 읽어야 하나?」로 읽고 같은 짓을 반복한다 — 필요한 말은
**「깃허브로 가라」**였다.

이 저장소의 교훈 그대로다 — 빈 값 하나가 두 사실을 뜻하면 조용히 고장 난다
(`empty_means_two_things`). 「봤는데 0건」과 「엉뚱한 데서 봤다」는 다른 말이다.
"""

from __future__ import annotations

from alture_jarvis.plan import Requirement, check


def _rows(requirements, sources, answer=""):
    return {req.label: (ok, saw)
            for req, ok, saw in check(requirements, sources=sources, steps=[], answer=answer)}


def _github_plan() -> list[Requirement]:
    return [
        Requirement("count", "10개 이상 직접 열어 읽기", 10, grounding_required=True),
        Requirement("site", "깃허브에서 하기", ["github.com"]),
    ]


ELSEWHERE = [
    "https://huggingface.co/blog/state-of-open-models-summer-2026",
    "https://huggingface.co/blog/huggingface/state-of-os-hf-spring-2026",
    "https://huggingface.co/blog/daya-shankar/open-source-llms",
    "https://mastra.ai/articles/open-source-llm",
    "https://is4.ai/blog/our-blog-1/transformers-ai-library-160868-stars-2026-445",
    "https://www.youtube.com/watch?v=8p1xuROT4n4",
    "https://www.youtube.com/watch?v=Rv_N34aiMtY",
]


def test_zero_reads_elsewhere_says_where_they_went() -> None:
    """★ 실전에서 빠져 있던 것 — 「0개 읽음」만 있고 8쪽을 어디서 읽었는지 말이 없었다."""
    saw = _rows(_github_plan(), ELSEWHERE)["10개 이상 직접 열어 읽기"][1]

    assert "0개 읽음" in saw
    assert "7" in saw, f"딴 데서 읽은 수를 안 말했다: {saw}"
    assert "github.com" in saw, f"어디로 가야 하는지 안 말했다: {saw}"


def test_it_is_still_not_satisfied() -> None:
    """말을 더 한다고 통과시키면 안 된다 — 시킨 곳에서 안 읽은 것은 그대로다."""
    assert _rows(_github_plan(), ELSEWHERE)["10개 이상 직접 열어 읽기"][0] is False


def test_reading_nothing_at_all_does_not_claim_elsewhere() -> None:
    """진짜로 0쪽을 읽었으면 「딴 데서 읽었다」는 말이 붙으면 안 된다."""
    saw = _rows(_github_plan(), [])["10개 이상 직접 열어 읽기"][1]
    assert "0개 읽음" in saw
    assert "밖" not in saw and "github.com" not in saw, saw


def test_reading_at_the_named_site_counts_normally() -> None:
    inside = [f"https://github.com/owner/repo{index}" for index in range(10)]
    ok, saw = _rows(_github_plan(), inside)["10개 이상 직접 열어 읽기"]
    assert ok is True
    assert "10개 읽음" in saw
    assert "밖" not in saw


def test_a_plan_without_a_named_site_is_untouched() -> None:
    """출처를 안 시킨 판은 예전 그대로 — 여기서 말을 보태면 멀쩡한 판이 시끄러워진다."""
    plain = [Requirement("count", "3개 이상 직접 열어 읽기", 3, grounding_required=True)]
    ok, saw = _rows(plain, ELSEWHERE[:3])["3개 이상 직접 열어 읽기"]
    assert ok is True
    assert saw.startswith("3개 읽음")
    assert "밖" not in saw
