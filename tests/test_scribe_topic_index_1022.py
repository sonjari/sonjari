"""서기 주제 색인 (2026-10-22 대표 설계) — 주제 → 날짜 · 줄 번호. 압축 · 새 세션 때 펼쳐 주고 필요한 줄만 연다.

대표 걱정: 「키워드는 두더지 잡기를 자처하는 것 — 표본이 너무 많아지지 않게 완충을」. 그래서 코드가 막는 넷을 지킨다:
① 지금 있는 주제를 모델에게 보여 준다 ② 카드 두 장 이상에 붙은 주제만 색인에 ③ 띄어쓰기 · 대소문자 · 기호만 다른 주제는 하나
④ 총량 상한 — 넘치면 오래 안 나온 주제부터 뺀다.
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.scribe import (INDEX_CHARS, NO_TOPIC, TOPIC_MAX, Scribe, Turn, _body, clean_topics, draft_and_close,
                                  topic_index)


def _card(line: int, topics: list[str], at: str = "10-22 10:00", kind: str = "decided") -> dict:
    return {"kind": kind, "text": f"카드 {line}", "line": line, "quote": "q", "at": at, "topics": topics, "session": "s1"}


def test_clean_topics_bounds_count_length_and_duplicates() -> None:
    raw = ["색인 속도", "색인속도", "x", "아주아주아주아주아주아주아주긴주제이름입니다", "레딧 답글", "원격 연결", "넷째"]
    assert clean_topics(raw) == ["색인 속도", "레딧 답글", "원격 연결"]
    assert len(clean_topics(["a1", "b2", "c3", "d4"])) == TOPIC_MAX
    assert clean_topics("문자열") == []


def test_a_topic_on_one_card_does_not_reach_the_index() -> None:
    text, dropped = topic_index([_card(10, ["색인 속도"]), _card(20, ["색인 속도"]), _card(30, ["한 번 스친 말"])])
    assert "색인 속도" in text and "한 번 스친 말" not in text and dropped == 0


def test_spacing_and_case_variants_merge_into_one_topic() -> None:
    text, _ = topic_index([_card(10, ["Code Index"]), _card(20, ["code-index"]), _card(30, ["CODE INDEX"])])
    assert text.count("\n") == 0 and "줄 30 · 20 · 10" in text


def test_newest_topics_first_and_the_cap_drops_the_oldest() -> None:
    cards = []
    for n in range(80):
        cards += [_card(1000 + n * 10, [f"주제{n:02d}"]), _card(1001 + n * 10, [f"주제{n:02d}"])]
    text, dropped = topic_index(cards)
    assert len(text) <= INDEX_CHARS and dropped > 0
    lines = text.splitlines()
    assert lines[0].startswith("- 주제79"), "가장 최근에 나온 주제가 맨 위"
    assert "주제00" not in text, "상한에 걸리면 오래 안 나온 주제가 빠진다"


def test_no_topic_marker_never_shows() -> None:
    text, _ = topic_index([_card(1, [NO_TOPIC]), _card(2, [NO_TOPIC]), _card(3, ["진짜"]), _card(4, ["진짜"])])
    assert NO_TOPIC not in text and "진짜" in text


def test_date_span_and_recent_lines() -> None:
    text, _ = topic_index([_card(5, ["원격"], at="10-21 18:00"), _card(9, ["원격"], at="10-22 09:00"),
                           _card(7, ["원격"], at="10-21 20:00"), _card(1, ["원격"], at="10-20 08:00")])
    assert text == "- 원격 (10-20~10-22) 줄 9 · 7 · 5"


def test_the_model_sees_existing_topics_and_cards_keep_theirs() -> None:
    turns = [Turn(10, "사람", "색인 따라잡기 고치자", "10-22 17:40")]
    body, _ = _body(turns, [], ["색인 속도", "레딧 답글"])
    assert "=== 지금 있는 주제 ===" in body and "색인 속도 · 레딧 답글" in body
    seen: dict = {}

    def ask(system: str, text: str) -> str:
        seen["body"] = text
        return json.dumps({"items": [{"kind": "decided", "text": "색인을 고친다", "line": 10, "quote": "색인 따라잡기 고치자",
                                      "topics": ["색인 속도", "색인속도", "성능"]}]}, ensure_ascii=False)

    items, _ = draft_and_close(turns, ask, [], topics=["색인 속도"])
    assert "색인 속도" in seen["body"]
    assert items[0]["topics"] == ["색인 속도", "성능"]


def test_old_cards_get_tagged_in_idle_time_and_untagged_ones_are_marked(tmp_path: Path) -> None:
    scribe = Scribe(tmp_path / "data", [])
    old = [{"kind": "decided", "text": f"옛 카드 {n}", "line": n, "quote": "q", "session": "s1", "folder": "f"} for n in (1, 2, 3)]
    for row in old:
        row["id"] = __import__("alture_jarvis.scribe", fromlist=["card_id"]).card_id(row)
    scribe._append(old)

    def ask(system: str, text: str) -> str:
        assert "[t1]" in text and "[t3]" in text
        return json.dumps({"tags": [{"id": "t1", "topics": ["원격 연결"]}, {"id": "t2", "topics": ["원격연결"]}]},
                          ensure_ascii=False)

    result = scribe._tag_once(ask)
    assert result["done"] and result["tagged"] == 3
    cards = {card["line"]: card for card in scribe.all_cards("s1")}
    assert cards[1]["topics"] == ["원격 연결"] and cards[3]["topics"] == [NO_TOPIC]
    assert scribe._tag_once(lambda s, t: "{}")["done"] is False, "다 붙였으면 같은 카드를 다시 잡지 않는다"
    assert "원격 연결" in scribe.index("s1")["text"]
    assert scribe.topics("s1") == ["원격 연결"], "주제 없음 표시는 목록에 안 나온다"
    opened, _ = scribe._split("s1")
    assert all("topics" in card for card in opened)
