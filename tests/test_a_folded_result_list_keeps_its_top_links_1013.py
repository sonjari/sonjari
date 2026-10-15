"""접힌 **검색 결과**에는 앞쪽 몇 건의 링크가 남는다 (2026-10-13 · 밖에서 받은 가설).

    「검색 결과 페이지가 버려질 때 그 한 줄 요약에 제목과 주소는 있어도 상품 링크가 없으면, 에이전트는 상품으로 돌아갈
      길이 없다.」

코드를 보니 사실이었다. 접힌 길 찾기 결과는 「결과 N자는 창을 비우려고 뺐다. 지금 화면이 필요하면 다시 찍어라」 한 줄이고
받아 둔 목록은 통째로 사라진다. 가게 셋을 **먼저 다 검색하고** 나중에 상품을 여는 판(4B)에서는, 첫 가게의 목록이 접힌 뒤
그 상품으로 가려면 검색부터 다시 해야 한다 — 창 32K 의 틀린 29칸 중 19칸이 「상품 페이지까지 못 감」이었다.

순위는 남기지 않고 **주소**를 남긴다. `browser_open_result` 의 순위는 도구가 마지막으로 받은 목록의 것이라, 그 뒤에 다른
가게를 검색했으면 옛 순위는 엉뚱한 것을 연다.

끌 수 있다(`JARVIS_FOLD_KEEPS_RESULT_LINKS=0`) — 넣기 전후를 같은 밤에 나란히 재려고.
표본의 가게 주소 · 상품 이름은 지어낸 것이다.
"""
from __future__ import annotations

import json

import pytest

from alture_jarvis import transcript


def _results(count: int) -> list[dict[str, object]]:
    return [{"rank": n + 1, "title": f"가상 마우스 X{n + 1} 무선 블루투스", "url": f"https://shop.example/products/{9000 + n}?from=search&track={'t' * 90}",
             "domain": "shop.example", "ref": f"e{n}"} for n in range(count)]


def _searched(count: int = 12, *, tool: str = "browser_site_search") -> dict[str, object]:
    body = {"ok": True, "action": "site_searched", "site": "shop.example", "query": "가상 마우스", "title": "가상 마우스 - 검색",
            "url": "https://shop.example/search?q=x", "results": _results(count), "result_count": count,
            "instruction": "이 사이트가 직접 준 목록이다 " * 30}
    return {"role": "tool", "tool_name": tool, "content": json.dumps(body, ensure_ascii=False)}


def test_a_folded_search_keeps_the_addresses_of_its_first_results() -> None:
    folded = transcript.fold(_searched())["content"]

    assert folded.startswith("[접음] browser_site_search")
    for number in range(transcript.FOLDED_LIST_KEEP):
        assert f"https://shop.example/products/{9000 + number}" in folded, number
    assert f"products/{9000 + transcript.FOLDED_LIST_KEEP}" not in folded, "앞쪽 몇 건만 — 목록을 통째로 남기면 접은 뜻이 없다"
    assert "browser_open" in folded, "그 주소로 여는 길을 말해 준다"
    assert "12건" in folded


def test_the_kept_lines_stay_small() -> None:
    whole = _searched()
    folded = transcript.fold(whole)["content"]

    assert len(folded) < 1_000 < len(str(whole["content"])), f"접힌 줄이 {len(folded)}자"
    assert "track=" not in folded, "주소 뒤에 붙은 추적 값은 뗀다 — 상품을 가리키는 것은 앞쪽이다"


@pytest.mark.parametrize("tool", ["browser_search", "browser_load_more", "browser_open"])
def test_any_step_that_came_back_with_a_list_keeps_it(tool: str) -> None:
    assert "https://shop.example/products/9000" in transcript.fold(_searched(tool=tool))["content"]


def test_a_result_cut_off_by_the_length_limit_still_keeps_what_it_can() -> None:
    """결과는 접히기 전에 길이 한도로 먼저 잘린다 — 작은 창일수록 낮다. 잘린 글은 풀리지 않지만 앞쪽 줄은 꺼낸다."""
    whole = _searched(15)
    cut = dict(whole, content=str(whole["content"])[:900])
    with pytest.raises(ValueError):
        json.loads(str(cut["content"]))

    folded = transcript.fold(cut)["content"]

    assert "https://shop.example/products/9000" in folded and "https://shop.example/products/9001" in folded
    assert "browser_open" in folded and "track=" not in folded


def test_a_cut_off_step_without_a_list_folds_as_before() -> None:
    cut = {"role": "tool", "tool_name": "browser_snapshot", "content": '{"ok": true, "title": "가상 화면", "elements": [{"ref": "e1", "name": "' + "가" * 500}

    assert "다시 찍어라" in transcript.fold(cut)["content"]


def test_a_search_with_no_results_folds_as_before() -> None:
    folded = transcript.fold(_searched(0))["content"]

    assert "products/" not in folded and "다시 찍어라" in folded


def test_a_read_page_still_keeps_its_head_not_a_list() -> None:
    page = {"role": "tool", "tool_name": "browser_extract",
            "content": json.dumps({"ok": True, "title": "가상 마우스 X1", "url": "https://shop.example/products/9000", "text": "판매가 129,000원 " * 200})}

    folded = transcript.fold(page)["content"]

    assert "첫머리" in folded and "판매가 129,000원" in folded


def test_it_can_be_switched_off_to_measure_before_and_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_FOLD_KEEPS_RESULT_LINKS", "0")

    folded = transcript.fold(_searched())["content"]

    assert "products/" not in folded and "다시 찍어라" in folded
