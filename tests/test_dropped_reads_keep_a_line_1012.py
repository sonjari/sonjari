"""작은 창의 기억 — 버리기 전에 한 줄 (2026-10-12).

가격 조사 세 판(공식 9B · 창 32,768 · 광고 카드 규칙을 넣은 뒤)이 다나와와 11번가를 왔다 갔다 하다 끝났고 G마켓에는
가 보지도 못했다. 한 판은 11번가 상품 화면을 읽고도 「11번가에서도 검색할 수 있지만」이라고 답했다. 그 판의 걸음을
다시 쌓아 마지막 호출을 재생하니 걸음 1~17 이 통째로 없었다 — 읽은 화면 넷이 그 안에 있었다.

    접기는 「버리는 대신 접는다」였는데, 접어도 안 들어가면 그보다 오래된 것은 통째로 버렸다.

한 건에 주는 자리(8,600자)도 같이 줄였다가 되돌렸다 — 맨 아래 시험에 까닭이 있다.

표본의 도구 결과는 실제 모양이다(칸이 한 겹 · 도구가 뽑은 값이 맨 앞 — `agent` 가 그렇게 싣는다). 값과 이름은 지어낸 것이다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from alture_jarvis import transcript
from alture_jarvis.transcript_policy import chat_transcript_budget

_NOTE = " (도구가 이 페이지 첫머리에서 읽은 주 항목 값 — 표에는 이 값을 쓴다)"


def _call(tool: str, **arguments) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": tool, "arguments": arguments}}]}


def _read(shop: str, number: int, price: str, *, ok: bool = True, values: bool = True) -> dict:
    body = {"ok": ok, "url": f"https://{shop}.example.test/item/{number}?from=search&keyword=%EA%B0%80", "title": f"가상 상품 {number} : {shop}",
            "text": "메뉴 바로가기 " + ("본문 " * 4000)}
    if values and ok:
        body = {"page_main_values": f"판매가 {price}원{_NOTE}", **body}
    return {"role": "tool", "tool_name": "browser_extract", "content": json.dumps(body, ensure_ascii=False)}


def _nav(tool: str, text: str = "목록") -> dict:
    return {"role": "tool", "tool_name": tool, "content": json.dumps({"ok": True, "url": "https://shop.example.test/search", "results": text * 40}, ensure_ascii=False)}


def _conversation(reads: list[dict], *, request: str = "가상 상품 가격 조사") -> list[dict]:
    messages = [{"role": "system", "content": "지침 " * 2000}, {"role": "user", "content": request}]
    for index, read in enumerate(reads, 1):
        messages += [_call("browser_site_search", query="가상 상품"), _nav("browser_site_search"),
                     _call("browser_open_result", rank=1), _nav("browser_open_result", "열림"),
                     _call("browser_extract"), read]
    return messages


def _request(kept: list[dict]) -> str:
    return next(str(item["content"]) for item in kept if item["role"] == "user")


def _ledger_rows(kept: list[dict]) -> list[str]:
    text = _request(kept)
    if transcript.READ_LEDGER_OPEN not in text:
        return []
    block = text[text.index(transcript.READ_LEDGER_OPEN):text.index(transcript.READ_LEDGER_CLOSE)]
    return [row for row in block.splitlines() if row.startswith("- ")]


def test_a_read_that_no_longer_fits_leaves_one_line_with_its_value() -> None:
    reads = [_read("danawa", 1, "128,950"), _read("11st", 2, "139,700"), _read("gmarket", 3, "131,000"),
             _read("danawa", 4, "99,000"), _read("11st", 5, "88,000")]
    messages = _conversation(reads)
    kept = transcript.bounded(messages, max_chars=20_000, tool_result_max=4_000)
    rows = _ledger_rows(kept)
    # 남은 화면의 글은 한 건의 자리(4,000자)에서 잘려 있다 — 주소만 꺼낸다.
    survivors = {match.group(1) for item in kept if item["role"] == "tool"
                 for match in [re.search(r'"url": "([^"]+)"', item["content"])] if match}
    assert rows, "버려진 읽은 화면이 한 줄도 안 남았다"
    # 첫 가게는 대화에서 사라졌지만 값 · 주소 · 제목이 한 줄에 있다.
    first = rows[0]
    assert "가상 상품 1 : danawa" in first and "danawa.example.test/item/1" in first and "값: 판매가 128,950원" in first
    assert "도구가 이 페이지" not in first, "값 뒤의 풀이는 줄마다 되풀이하지 않는다"
    # 오래된 것부터 · 대화에 아직 있는 화면은 묶음에 다시 적지 않는다.
    order = [int(row.split("가상 상품 ")[1].split(" ")[0]) for row in rows]
    assert order == sorted(order)
    assert not any(url and any(url.split("?")[0] in row for row in rows) for url in survivors)
    # 길 찾기 걸음은 한 줄로 남기지 않는다.
    assert all("example.test/search" not in row for row in rows)
    # 시킨 말은 그대로 뒤에 있다.
    assert _request(kept).endswith("가상 상품 가격 조사")


def test_the_lines_ride_inside_the_job_context_and_fit_the_budget() -> None:
    reads = [_read("danawa", n, f"{n}0,000") for n in range(1, 9)]
    request = transcript.with_job_context("스킬 안내: 가게 셋의 값을 표로.", "가상 상품 가격 조사")
    messages = _conversation(reads, request=request)
    budget = 22_000
    kept = transcript.bounded(messages, max_chars=budget, tool_result_max=4_000)
    text = _request(kept)
    assert text.index(transcript.READ_LEDGER_OPEN) < text.index(transcript.JOB_CONTEXT_CLOSE), "묶음은 이번 판 맥락 안에 싣는다"
    assert text.count(transcript.JOB_CONTEXT_OPEN) == 1 and "스킬 안내: 가게 셋의 값을 표로." in text
    assert sum(len(json.dumps(item, ensure_ascii=False)) for item in kept) <= budget + 800, "묶음만큼 걸음에 줄 자리를 먼저 뺀다"
    assert len(text[text.index(transcript.READ_LEDGER_OPEN):text.index(transcript.READ_LEDGER_CLOSE)]) <= transcript.READ_LEDGER_MAX_CHARS + 200


def test_the_same_page_read_twice_is_one_line_and_a_failed_read_is_none() -> None:
    reads = [_read("danawa", 1, "128,950"), _read("11st", 2, "139,700", ok=False), _read("danawa", 1, "127,000"),
             _read("gmarket", 3, "131,000"), _read("gmarket", 4, "132,000"), _read("gmarket", 5, "133,000")]
    kept = transcript.bounded(_conversation(reads), max_chars=19_000, tool_result_max=4_000)
    rows = _ledger_rows(kept)
    assert sum("item/1" in row for row in rows) <= 1
    twice = [row for row in rows if "item/1" in row]
    if twice:
        assert "127,000" in twice[0], "같은 화면은 마지막에 읽은 값으로"
    assert all("item/2" not in row for row in rows), "못 읽은 걸음은 「이미 읽은 화면」이 아니다"


def test_nothing_dropped_means_no_block_and_the_request_is_untouched() -> None:
    messages = _conversation([_read("danawa", 1, "128,950")])
    kept = transcript.bounded(messages, max_chars=180_000, tool_result_max=30_000)
    assert _request(kept) == "가상 상품 가격 조사"
    assert transcript.READ_LEDGER_OPEN not in json.dumps(kept, ensure_ascii=False)


def test_a_page_without_tool_values_keeps_its_title_address_and_first_words() -> None:
    reads = [_read("blog", 1, "", values=False)] + [_read("danawa", n, f"{n}0,000") for n in range(2, 8)]
    rows = _ledger_rows(transcript.bounded(_conversation(reads), max_chars=19_000, tool_result_max=4_000))
    first = next(row for row in rows if "blog.example.test" in row)
    assert "첫머리: 메뉴 바로가기" in first and "값:" not in first


def test_a_line_from_a_result_that_was_cut_before_it_could_be_parsed() -> None:
    whole = _read("danawa", 1, "128,950")["content"]
    line, key = transcript.read_line({"role": "tool", "tool_name": "browser_extract", "content": whole[:900]})
    assert "가상 상품 1 : danawa" in line and "값: 판매가 128,950원" in line and key.startswith("https://danawa.example.test/item/1")
    # 계단식 접기가 대화에 남긴 접힌 줄에서도 꺼낸다.
    folded = transcript.fold({"role": "tool", "tool_name": "browser_extract", "content": whole})
    line, _ = transcript.read_line(folded)
    assert "가상 상품 1 : danawa" in line and "값: 판매가 128,950원" in line


def test_the_room_for_one_result_was_tried_smaller_and_put_back() -> None:
    """「시스템 글을 뺀 나머지의 1/4」(창 32K 에서 4,000자)로 줄였다가 되돌렸다 — 검색 결과 목록까지 잘려 판이 2걸음 만에 끝났다.

    읽은 화면이 밀려나는 것은 위의 한 줄 묶음이 맡는다. 이 셈을 다시 손댈 사람이 까닭을 읽게 시험으로도 붙잡아 둔다.
    """
    budget, page = chat_transcript_budget(32_768, "qwen3.5:9b")
    assert page == budget // 4 > 8_000
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "transcript_policy.py").read_text(encoding="utf-8")
    assert "해 보고 되돌렸다" in source and "검색 결과 목록" in source


# ── 작은 창에서는 늘 보인다 (같은 날 밤) ──────────────────────────────────────────────
#
# 방을 넓힌 뒤 읽은 화면이 밀려나지 않았는데도 공식 9B · 창 32K 세 판 중 둘이 첫 가게로 되돌아갔다 — 한 판은 다섯 걸음 전에
# 읽은 가게를 두고 「아직 못 봤습니다」라고 했다. 화면 글이 눈앞에 있어도 「어디까지 했나」를 스스로 추리지 못했다.


def test_pinned_the_list_shows_every_read_even_the_ones_still_in_view() -> None:
    reads = [_read("danawa", 1, "128,950"), _read("11st", 2, "139,700")]
    messages = _conversation(reads)
    plain = transcript.bounded([dict(m) for m in messages], max_chars=180_000, tool_result_max=30_000)
    assert _ledger_rows(plain) == [], "넉넉한 판에서 밀려난 것이 없으면 예전대로 아무것도 안 붙는다"
    pinned = transcript.bounded([dict(m) for m in messages], max_chars=180_000, tool_result_max=30_000, pin_reads=True)
    rows = _ledger_rows(pinned)
    assert len(rows) == 2
    assert "가상 상품 1 : danawa" in rows[0] and "값: 판매가 128,950원" in rows[0]
    assert "가상 상품 2 : 11st" in rows[1] and "값: 판매가 139,700원" in rows[1]
    request = _request(pinned)
    assert transcript.READ_LEDGER_PINNED_LEAD in request and transcript.READ_LEDGER_LEAD not in request
    assert "아직 여기 없는 곳으로 가고" in request, "남은 곳으로 가라는 말이 같이 있다"
    assert request.endswith("가상 상품 가격 조사")


def test_pinned_nothing_read_yet_means_nothing_added() -> None:
    messages = [{"role": "system", "content": "지침"}, {"role": "user", "content": "가상 상품 가격 조사"},
                _call("browser_site_search", query="가상 상품"), _nav("browser_site_search")]
    kept = transcript.bounded(messages, max_chars=180_000, tool_result_max=30_000, pin_reads=True)
    assert _request(kept) == "가상 상품 가격 조사"


def test_pinned_the_list_still_fits_the_budget_and_keeps_one_line_per_page() -> None:
    reads = [_read("danawa", 1, "128,950"), _read("11st", 2, "139,700"), _read("danawa", 1, "127,000"), _read("gmarket", 3, "131,000")]
    budget = 20_000
    kept = transcript.bounded(_conversation(reads), max_chars=budget, tool_result_max=4_000, pin_reads=True)
    rows = _ledger_rows(kept)
    assert [row.split("가상 상품 ")[1].split(" ")[0] for row in rows] == ["2", "1", "3"], "같은 화면은 마지막에 읽은 자리 · 값으로"
    assert "127,000" in rows[1]
    assert sum(len(json.dumps(item, ensure_ascii=False)) for item in kept) <= budget + 800


def test_the_agent_pins_them_only_for_small_windows() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert 'pin_reads=model_role != "code" and self._compact_tool_surface(model_role),' in source
