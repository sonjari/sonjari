"""파일을 쓴 뒤에 새로 읽은 페이지가 있으면, 끝내기 전에 한 번만 다시 쓰게 돌려보낸다 (2026-10-14).

골라내기(`reads_after_last_write`)는 손자리가 짰다(`test_reads_after_last_write_1014.py`). 여기서는 붙이는 쪽을 지킨다.

운영 기록 대조(완료된 판 3,133 · 파일을 쓴 판 1,024): 처음 기준으로는 49판이 걸렸고, 그중 웹페이지 · 코드를 만드는 판이
「쓰고 → 자기 페이지를 미리보기(localhost)로 열어 읽기」라 걸렸다. 미리보기 주소를 빼고 문서 도구로 쓴 파일만 보니
31판 — 남은 것은 전부 조사 · 문서 판이었다(교보문고 책 3권 · 가격 비교 · 레딧 기록 — 쓴 뒤에 하나를 더 읽고 다시 안 씀).
"""

from __future__ import annotations

import inspect

from alture_jarvis import agent
from alture_jarvis.write_order import reads_after_last_write, rewrite_note


def _read(url: str) -> dict:
    return {"tool": "browser_extract", "ok": True, "arguments": {}, "evidence": {"url": url}}


def _write(path: str) -> dict:
    return {"tool": "local_write_document", "ok": True, "arguments": {"path": path}, "evidence": {}}


def test_reading_my_own_preview_page_is_not_a_new_source() -> None:
    for url in ("http://127.0.0.1:5173/", "http://localhost:8000/index.html", "http://app.localhost:3000/p"):
        assert reads_after_last_write([_write("index.html"), _read(url)]) is None
    got = reads_after_last_write([_write("a.xlsx"), _read("http://127.0.0.1:5173/"), _read("https://shop.example.test/p/3")])
    assert got is not None and got["new_reads"] == ["https://shop.example.test/p/3"]


def test_the_note_names_the_file_and_the_pages_and_allows_finishing() -> None:
    found = {"path": r"C:\out\캣타워.xlsx", "write_index": 4, "new_reads": ["https://shop.example.test/p/3"]}
    ko = rewrite_note(found, "ko")
    assert "캣타워.xlsx" in ko and "https://shop.example.test/p/3" in ko
    assert "local_write_document" in ko and "그대로 끝내도 된다" in ko
    en = rewrite_note(found, "en")
    assert "캣타워.xlsx" in en and "local_write_document" in en and "finish as is" in en
    assert not any("가" <= ch <= "힣" for ch in en.replace("캣타워", ""))


def test_the_note_lists_at_most_five_pages() -> None:
    found = {"path": "a.xlsx", "write_index": 0, "new_reads": [f"https://shop.example.test/p/{i}" for i in range(9)]}
    note = rewrite_note(found)
    assert "/p/4" in note and "/p/5" not in note


def test_the_loop_sends_it_back_once_after_the_plan_pushback_and_before_forced_calls() -> None:
    source = inspect.getsource(agent)
    plan_pushback = source.index('"agent_plan_pushback",')
    block_start = source.index("stale_write = None if write_order_pushed else reads_after_last_write(steps)")
    forced = source.index("forced_self = _forced_self_check_call(")
    assert plan_pushback < block_start < forced
    block = source[block_start:forced]
    assert 'get("tool") == "local_write_file"' in block, "코드 파일 쓰기는 돌려보내지 않는다"
    assert "write_order_pushed = True" in block, "한 판에 한 번뿐"
    assert "and len(steps) + 2 <= step_limit" in block and "time.monotonic() < deadline" in block
    assert "rewrite_note(stale_write, reply_language(asked))" in block
    assert "continue" in block
    assert "write_order_pushed = False" in source
