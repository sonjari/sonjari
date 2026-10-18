"""순서를 물은 요청에서 답의 순서가 읽은 목록의 순서와 다르면 알린다 (2026-10-18 r/LLMDevs 지적 · 공개 약속).

「깃허브 트렌딩 상위 3개」 데모에 「표의 순위가 페이지에서 온 것인지 확인하라」는 지적을 받았다. 그 판은 맞았지만 마지막 검사는
값이 읽은 글에 있는지만 봤다 — 순서만 섞인 표도 통과했다. 시험은 그날 아침 남겨 둔 트렌딩 페이지 사본으로 한다.
"""

from __future__ import annotations

import gzip
import html
import re
from pathlib import Path

import pytest

from alture_jarvis.promise_gate import rank_order_warning

FIXTURE = Path(__file__).parent / "fixtures" / "result_lists" / "github_trending.html.gz"
# 캡처 원본(.html.gz)은 공개본으로 내보내지 않는다(`result_list_bench.py` 와 같은 규칙) — 없으면 건너뛴다.
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="캡처 원본(.html.gz)이 없는 공개본")
ASKED = "github.com/trending/python 을 열어서 상위 3개 저장소를 읽고 이름 · 별 · 설명을 엑셀 표로 저장해 줘"


def _page_text() -> str:
    raw = gzip.open(FIXTURE).read().decode("utf-8", "replace")
    raw = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def _messages() -> list[dict]:
    return [{"role": "tool", "content": _page_text()}]


def _table(*names: str) -> str:
    rows = "\n".join(f"| {i} | {name} | 1.0k |" for i, name in enumerate(names, 1))
    return "| 순위 | 저장소 | 별 |\n|---|---|---|\n" + rows


def test_the_demo_order_matches_the_page() -> None:
    answer = _table("earthtojake / text-to-cad", "Panniantong / Agent-Reach", "getsentry / sentry")
    assert rank_order_warning(ASKED, answer, _messages()) == ""


def test_a_reshuffled_table_of_real_repos_is_flagged() -> None:
    answer = _table("getsentry / sentry", "earthtojake / text-to-cad", "Panniantong / Agent-Reach")
    note = rank_order_warning(ASKED, answer, _messages())
    assert "순서가 읽은 목록의 순서와 다릅니다" in note
    assert note.index("text-to-cad") < note.index("Agent-Reach") < note.index("sentry")
    en = rank_order_warning(ASKED, answer, _messages(), english=True)
    assert "order differs" in en and not any("가" <= ch <= "힣" for ch in en)


def test_a_resort_request_or_an_unordered_request_is_not_checked() -> None:
    answer = _table("getsentry / sentry", "earthtojake / text-to-cad", "Panniantong / Agent-Reach")
    assert rank_order_warning(ASKED + " 별 많은 순으로 정렬해서", answer, _messages()) == ""
    assert rank_order_warning("트렌딩에서 재미있는 저장소 몇 개 골라 줘 이유도", answer, _messages()) == ""  # 순서를 안 물었다


def test_names_not_all_on_one_read_page_are_not_compared() -> None:
    answer = _table("getsentry / sentry", "earthtojake / text-to-cad", "someone / not-on-the-page")
    assert rank_order_warning(ASKED, answer, _messages()) == ""


def test_a_numbered_list_answer_is_checked_too() -> None:
    answer = "1. **getsentry / sentry** — 오류 추적\n2. **earthtojake / text-to-cad** — 글로 CAD\n"
    assert "다릅니다" in rank_order_warning(ASKED, answer, _messages())
