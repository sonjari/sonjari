"""서기가 끝난 일을 못 닫던 두 자리 (2026-10-22 · 이 대화 남은 일 12장 중 5장이 이미 끝났거나 바뀐 채 열려 있었다).

1. 한 조각 안에서 남은 일이 생기고 그 뒤에 커밋까지 끝나면 그 카드는 영영 열린 채였다 — 닫기는 이미 열린 카드만 본다.
   새 남은 일보다 뒤에 커밋 줄이 있을 때만 그 뒤 말들로 닫기를 한 번 더 한다(커밋이 없으면 모델 부르기가 늘지 않는다).
2. 「~하는 중이다」 진행 보고가 남은 일 카드가 됐다(지시문에 「적지 마라」가 있었는데 안 먹음) — 코드가 거른다.
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.scribe import Scribe, Turn, _kept_items


def _user(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False) + "\n"


def _commit(message: str) -> str:
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": f'git commit -q -m "{message}"'}}]}}, ensure_ascii=False) + "\n"


def _book(tmp_path: Path, rows: list[str]) -> Scribe:
    log = tmp_path / "proj" / "s1.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("".join(rows), encoding="utf-8")
    book = Scribe(tmp_path / "data", [log.parent])
    book.MIN_NEW = 1
    return book


def test_a_card_made_and_committed_in_the_same_chunk_gets_closed(tmp_path: Path) -> None:
    rows = [_user(f"잡담 {i}") for i in range(3)] + [_user("주제 색인을 만들자"), _commit("feat(scribe): 주제 색인")]
    book = _book(tmp_path, rows)
    systems: list[str] = []

    def ask(system: str, body: str) -> str:
        systems.append(system)
        if "새 카드를 쓰지 않는다" in system:
            assert "[c1]" in body and "주제 색인을 만든다" in body
            return json.dumps({"closes": [{"id": "c1", "status": "done", "line": 4, "quote": "feat(scribe): 주제 색인"}]},
                              ensure_ascii=False)
        return json.dumps({"items": [{"kind": "open", "text": "주제 색인을 만든다", "line": 3, "quote": "주제 색인을 만들자"}]},
                          ensure_ascii=False)

    result = book.run_once(ask)
    assert result["items"] == 1 and result["closed"] == 1 and len(systems) == 2
    assert book.recent(session="s1") == [], "만들고 커밋한 일은 열린 목록에 남지 않는다"
    assert book.closed(session="s1")[0]["card_text"] == "주제 색인을 만든다"


def test_without_a_later_commit_there_is_no_extra_call(tmp_path: Path) -> None:
    book = _book(tmp_path, [_commit("chore: 앞선 커밋"), _user("주제 색인을 만들자"), _user("잡담")])
    calls: list[str] = []

    def ask(system: str, body: str) -> str:
        calls.append(system)
        return json.dumps({"items": [{"kind": "open", "text": "주제 색인을 만든다", "line": 1, "quote": "주제 색인을 만들자"}]},
                          ensure_ascii=False)

    book.run_once(ask)
    assert len(calls) == 1, "커밋이 카드보다 앞에만 있으면 닫기를 더 부르지 않는다"
    assert [card["text"] for card in book.recent(session="s1")] == ["주제 색인을 만든다"]


def test_progress_reports_do_not_become_open_cards() -> None:
    turns = [Turn(5, "클로드", "손자리가 7개 프로젝트를 읽고 문서를 쓰고 있습니다. 나중에 사용자님 확인 필요", "10-22 10:00")]
    items = [
        {"kind": "open", "text": "손자리가 7개 프로젝트를 조사하여 문서를 작성하는 중이다.", "line": 5, "quote": "7개 프로젝트를 읽고"},
        {"kind": "open", "text": "전체 회귀를 돌리고 있다", "line": 5, "quote": "문서를 쓰고 있습니다"},
        {"kind": "open", "text": "결과를 사용자님께 확인받는다", "line": 5, "quote": "사용자님 확인 필요"},
        {"kind": "decided", "text": "조사는 손자리가 하는 중이다", "line": 5, "quote": "7개 프로젝트를"},
    ]
    kept = _kept_items({"items": items}, turns, 12)
    assert [item["text"] for item in kept] == ["결과를 사용자님께 확인받는다", "조사는 손자리가 하는 중이다"], \
        "남은 일 칸의 진행 보고만 거른다(정한 것은 그대로)"
