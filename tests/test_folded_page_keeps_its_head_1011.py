"""읽은 페이지를 접을 때 **첫머리는 남긴다** (2026-10-11).

16GB 조건(창 49,152)에서 가격 조사를 돌린 판(dea4dec2): 다나와 · 11번가 · G마켓의 상품 페이지를 차례로 열어 읽고,
엑셀을 쓸 때는 11번가와 G마켓 줄을 「확인 불가」로 적었다. 값을 지어내지는 않았다 — 창을 넘기지 않으려고 앞서 읽은 페이지가
이렇게 한 줄로 접혀 있었기 때문이다:

    [접음] browser_extract — 결과 14,336자는 창을 비우려고 뺐다. 지금 화면이 필요하면 다시 찍어라.

읽었다는 사실만 남고 읽은 값은 없다. 게다가 긴 결과는 잘린 채 접혀서(닫는 괄호가 없어 풀리지 않는다) 제목 · 주소도 안 남았다.

접힌 페이지에 본문 **첫머리**를 남긴다. 줄↔페이지 대조가 「그 페이지의 주 항목이 있는 자리」로 보는 앞자리
(`answer_claims._ROW_BODY_HEAD_CHARS`)와 같은 크기다 — 상품 이름과 값은 거기 있다.

이 시험이 **못** 지키는 것: 모든 가게에서 값이 첫머리에 있는가. 그것은 실제 판으로만 본다.
"""
from __future__ import annotations

import json
from typing import Any

from alture_jarvis.answer_claims import _ROW_BODY_HEAD_CHARS
from alture_jarvis.transcript import (
    FOLDED_READ_ADDRESS_CHARS, FOLDED_READ_HEAD_CHARS, NAVIGATION_TOOLS, PAGE_READ_TOOLS, bounded, fold,
)
from alture_jarvis.transcript_policy import _PAGE_READ_TOOLS, _bounded_tool_result

_HEAD = "[정품] 무선 마우스 블랙 수신기 포함\n판매가 139,700원\n배송비 무료\n"
_BODY = _HEAD + "상품 상세 설명 " * 4_000


_URL = "https://shop.example/products/1"


def _page(tool: str = "browser_extract", text: str = _BODY, limit: int = 30_000, url: str = _URL,
          main_values: str = "") -> dict[str, Any]:
    """본문을 읽은 도구 결과 — 운영과 같은 길로 만든다(길면 뒤가 잘린다).

    ★ 칸은 **한 겹**이다(`agent` 가 도구가 돌려준 것을 그대로 싣는다 — `observation.get("url")` · `.get("text")`).
      순서는 `browser._evidence`(action · url · title · 나머지), 주 항목 값은 `agent` 가 맨 앞에 붙인다.
      처음 쓴 표본은 `result` 안에 넣은 두 겹이었고, 그래서 잘리지 않은 결과에서 아무것도 안 남는 것을 못 봤다.
    """
    observation = {"ok": True, "action": tool, "url": url, "title": "무선 마우스", "text": text}
    if main_values:
        observation = {"page_main_values": main_values, **observation}
    return {"role": "tool", "tool_name": tool, "content": _bounded_tool_result(json.dumps(observation, ensure_ascii=False), limit)}


def test_the_head_is_paired_with_what_the_row_check_calls_the_head() -> None:
    assert FOLDED_READ_HEAD_CHARS == _ROW_BODY_HEAD_CHARS, "두 자리가 갈리면 접힌 페이지에 남은 값과 대조하는 값이 달라진다"
    assert PAGE_READ_TOOLS == _PAGE_READ_TOOLS, "본문을 읽는 도구의 목록이 두 군데서 갈렸다"
    assert not PAGE_READ_TOOLS & NAVIGATION_TOOLS


def test_a_folded_page_still_shows_the_name_and_the_price() -> None:
    folded = fold(_page())["content"]

    assert folded.startswith("[접음] browser_extract")
    assert "139,700원" in folded and "수신기 포함" in folded and "배송비 무료" in folded
    assert len(folded) < FOLDED_READ_HEAD_CHARS + 400, "첫머리만 남는다 — 본문을 도로 채우지 않는다"
    assert _URL in folded.splitlines()[0], "어느 주소였는지도 남는다 — 표의 주소 칸을 기억으로 짓지 않게"
    assert "다시 읽어라" in folded, "더 필요하면 무엇을 할지 적혀 있다"


def test_a_page_cut_before_folding_still_gives_its_head_and_its_title() -> None:
    """창이 작으면 결과는 접히기 전에 먼저 잘린다(닫는 괄호가 없다) — 그래도 꺼낸다."""
    message = _page()
    message["content"] = message["content"][:14_336]

    folded = fold(message)["content"]

    assert "139,700원" in folded and "수신기 포함" in folded
    assert "무선 마우스" in folded.splitlines()[0], "제목도 첫 줄에 남는다 — 어느 페이지였는지"
    assert _URL in folded.splitlines()[0], "주소도 남는다"


def test_escapes_in_the_text_come_back_as_they_were_read() -> None:
    text = '상품 "프로" 모델\n값\t129,000원\\특가\n' + "설명 " * 3_000
    message = _page(text=text)
    message["content"] = message["content"][:9_000]

    folded = fold(message)["content"]

    assert '상품 "프로" 모델\n값\t129,000원\\특가' in folded


def test_a_long_address_keeps_the_part_that_names_the_product() -> None:
    """검색 추적 값이 붙어 긴 주소 — 뒤에 붙은 값은 떼고, 상품을 가리키는 앞쪽은 그대로 남긴다."""
    long_url = "https://item.shop.example/Item?goodscode=4295691811&utparam-url=" + "%7B%22x%22%3A%22" * 60
    assert len(long_url) > FOLDED_READ_ADDRESS_CHARS
    for message in (_page(url=long_url), {**_page(url=long_url), "content": _page(url=long_url)["content"][:9_000]}):
        first_line = fold(message)["content"].splitlines()[0]

        assert "https://item.shop.example/Item?goodscode=4295691811" in first_line
        assert "utparam-url" not in first_line and "%7B" not in first_line


def test_the_values_the_tool_already_picked_out_stay_in_front() -> None:
    """도구가 그 페이지에서 뽑아 맨 앞에 붙여 둔 주 항목 값 — 접어도 남긴다(잘렸든 아니든)."""
    picked = "판매가 139,700원 · 적립 1,397P (도구가 이 페이지 첫머리에서 읽은 주 항목 값 — 표에는 이 값을 쓴다)"
    whole = _page(text="짧은 본문. 판매가 139,700원.", main_values=picked)
    cut = _page(main_values=picked)
    cut["content"] = cut["content"][:9_000]
    for message in (whole, cut):
        lines = fold(message)["content"].splitlines()

        assert lines[1].startswith("[이 페이지의 주 항목 값] 판매가 139,700원 · 적립 1,397P"), lines[:2]
        assert _URL in lines[0] and "무선 마우스" in lines[0]


def test_a_result_wrapped_one_level_deeper_is_read_the_same_way() -> None:
    """`result` 안에 넣어 돌려주는 도구도 있다 — 두 모양 다 본다."""
    nested = {"ok": True, "result": {"action": "browser_read", "url": _URL, "title": "무선 마우스", "text": _HEAD}}
    message = {"role": "tool", "tool_name": "browser_read", "content": json.dumps(nested, ensure_ascii=False)}

    folded = fold(message)["content"]

    assert "139,700원" in folded and _URL in folded.splitlines()[0]


def test_a_short_page_is_kept_whole_in_the_fold() -> None:
    folded = fold(_page(text="품절입니다. 재입고 알림을 신청하세요."))["content"]

    assert "품절입니다. 재입고 알림을 신청하세요." in folded


# --- 그대로인 것 -----------------------------------------------------------------

def test_a_navigation_result_still_folds_to_one_line() -> None:
    snapshot = {"ok": True, "title": "검색 결과", "url": "https://shop.example/search", "text": "버튼 " * 2_000}
    message = {"role": "tool", "tool_name": "browser_snapshot", "content": json.dumps(snapshot, ensure_ascii=False)}

    folded = fold(message)["content"]

    assert "\n" not in folded and "버튼 버튼" not in folded and "검색 결과" in folded


def test_a_result_without_text_folds_as_before() -> None:
    message = {"role": "tool", "tool_name": "browser_extract", "content": json.dumps({"ok": False, "error": "no_page"})}

    folded = fold(message)["content"]

    assert folded.startswith("[접음] browser_extract") and "\n" not in folded


# --- 접히는 길에서 ---------------------------------------------------------------

def test_three_pages_in_a_small_budget_leave_every_price_in_front_of_the_model() -> None:
    """예산이 페이지 하나만 원문으로 담을 만큼 작아도, 앞의 두 페이지의 값은 남는다."""
    def shop(index: int, price: str) -> list[dict[str, Any]]:
        text = f"가게 {index} 무선 마우스\n판매가 {price}\n배송비 무료\n" + "상품 상세 설명 " * 1_500
        observation = {"ok": True, "action": "browser_extract", "url": f"https://shop{index}.example/p", "title": f"가게 {index}", "text": text}
        return [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_extract", "arguments": {}}}]},
            {"role": "tool", "tool_name": "browser_extract", "content": json.dumps(observation, ensure_ascii=False)},
        ]

    messages = [
        {"role": "system", "content": "일하는 규칙."},
        {"role": "user", "content": "무선 마우스 가격 조사"},
        *shop(1, "128,990원"), *shop(2, "139,300원"), *shop(3, "139,700원"),
    ]

    sent = bounded(messages, max_chars=18_000, tool_result_max=14_000)
    seen = "\n".join(str(item.get("content")) for item in sent)

    assert all(price in seen for price in ("128,990원", "139,300원", "139,700원")), "접힌 페이지의 값이 사라졌다"
    assert sum(len(json.dumps(item, ensure_ascii=False)) for item in sent) <= 18_000 + 200
