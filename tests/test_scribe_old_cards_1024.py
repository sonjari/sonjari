"""서기 4차 (2026-10-24 새벽) — 닫기 창 밖으로 밀려난 카드는 영영 닫힐 기회가 없었다.

세션 794912da 사본: 열린 남은 일 45장 중 15장 · 정한 것 97장 중 82장이 닫기 창(남은 일 최근 30 + 정한 것 최근 15) 밖이었다.
그중 끝난 일이 대화에 그대로 있는 카드도 있었다(PR #21 합침 · HN 세기 결과 · 바로잡기 댓글). 압축 훅은 최근 40장만 받아 남은 일
27장이 말없이 빠졌다. 고침:
1. 노는 시간에 창 밖 카드를 몇 장씩 돌아가며 그 뒤 말 가운데 가장 겹치는 말과 대 본다(닫는 규칙은 그대로 — 글자 그대로 인용).
2. 압축 직후 넘기는 글은 최근에 나온 카드부터 예산 안에서 · 오래되고 다시 안 나온 카드는 「(접음)」 한 줄로(닫지 않는다).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from alture_jarvis import claude_hooks
from alture_jarvis.scribe import CLOSE_VERSION, HANDOFF_CHARS, Scribe, card_id, render_handoff


def _line(kind: str, text: str) -> str:
    return json.dumps({"type": kind, "message": {"role": kind, "content": text}, "timestamp": "2026-10-24T01:00:00Z"},
                      ensure_ascii=False) + "\n"


FILLER = ["점심은 김치찌개로 하자", "네 알겠습니다 바로 보겠습니다", "날씨가 꽤 춥네", "창문 닫았습니다",
          "오늘 회의는 세 시", "회의 자료 열어 두겠습니다"]
OLD_TEXT = "README 정확도 표를 17~23 으로 고치는 PR 을 합친다"
EVIDENCE = "README 정확도 표 17~23 으로 고친 PR 을 합쳤습니다(59dca580)"


def _setup(tmp_path: Path, *, evidence_turn: str, extra_lines: int = 0) -> tuple[Scribe, Path]:
    """기록 하나 · 열린 남은 일 31장(가장 오래된 1장이 창 밖) · 서기는 끝까지 읽어 둔 상태."""
    folder = tmp_path / "proj"
    folder.mkdir()
    log = folder / "s1.jsonl"
    lines = [_line("user", "README 숫자부터 바로잡자")]                  # 줄 0
    lines += [_line("assistant", FILLER[i % len(FILLER)] + f" {i}") for i in range(1, 140)]
    lines.append(_line("assistant", evidence_turn))                      # 줄 140 — 덩어리(40말) 몇 개 뒤
    lines += [_line("user", FILLER[i % len(FILLER)] + f" 뒤 {i}") for i in range(extra_lines)]
    log.write_text("".join(lines), encoding="utf-8")
    cards = [{"kind": "open", "text": OLD_TEXT, "line": 1, "quote": "README", "session": "s1", "topics": ["README"]}]
    cards += [{"kind": "open", "text": f"{n}번째 측정 판을 돌리고 표를 만든다", "line": 10 + n, "quote": "측정",
               "session": "s1", "topics": ["측정"]} for n in range(30)]
    for card in cards:
        card["id"] = card_id(card)
    root = tmp_path / "data" / "scribe"
    root.mkdir(parents=True)
    (root / "cards.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
    size, count = log.stat().st_size, len(lines)
    (root / "state.json").write_text(json.dumps({str(log): {"offset": size, "line": count, "rc_offset": size, "rc_line": count,
                                                            "rc_ver": CLOSE_VERSION}}), encoding="utf-8")
    return Scribe(tmp_path / "data", [folder]), log


def _closing_model(calls: list[str]):
    """보인 글에 근거 말이 **실제로 있을 때만** 창 밖 카드를 닫는 가짜 모델."""

    def ask(system: str, user: str) -> str:
        calls.append(user)
        tag = re.search(r"\[(c\d+)\] \(남은 일 · 약속 · 줄 1\)", user)
        # 말 하나 = 「[줄] 누구: 」부터 다음 「\n[줄] 」 앞까지(긴 말의 발췌는 여러 줄이다).
        said = re.search(r"\[(\d+)\] 클로드: (?:(?!\n\[\d+\] ).)*?" + re.escape("README 정확도 표 17~23"), user, re.S)
        if not (tag and said):
            return '{"closes": [], "mentions": []}'
        return json.dumps({"closes": [{"id": tag.group(1), "status": "done", "line": int(said.group(1)),
                                       "quote": "README 정확도 표 17~23 으로 고친 PR 을 합쳤습니다"}]}, ensure_ascii=False)

    return ask


def test_a_card_pushed_out_of_the_close_window_is_still_closed_by_later_words(tmp_path: Path) -> None:
    scribe, _ = _setup(tmp_path, evidence_turn=EVIDENCE)
    assert OLD_TEXT not in [c["text"] for c in scribe.active("s1")], "전제: 가장 오래된 카드는 닫기 창(최근 30) 밖"
    calls: list[str] = []
    result = scribe.run_once(_closing_model(calls))
    assert result["done"] and result["swept"] == 1 and result["closed"] == 1
    assert len(calls) == 1 and "측정 판을 돌리고" not in calls[0], "창 안의 카드는 덩어리마다 이미 본다 — 대 보기에는 창 밖 카드만"
    opened, closes = scribe._split("s1")
    assert OLD_TEXT not in [c["text"] for c in opened]
    assert [(c["card_text"], c["line"], c["status"]) for c in closes] == [(OLD_TEXT, 140, "done")]


def test_the_matching_paragraph_of_a_long_report_is_shown_not_just_its_first_700_chars(tmp_path: Path) -> None:
    # 실제로 「PR #21 합침」은 긴 보고의 셋째 칸에 있었다 — 앞 700자만 보이면 모델이 못 본다.
    report = "\n".join([f"- 올릴 파일 설명 {i}: 크기 333MB, 판 번호 확인, 지문 확인, 비밀값 검사 0건" for i in range(40)] + [f"- {EVIDENCE}"])
    assert report.index(EVIDENCE) > 1500
    scribe, _ = _setup(tmp_path, evidence_turn=report)
    calls: list[str] = []
    assert scribe.run_once(_closing_model(calls))["closed"] == 1


def test_an_invented_quote_still_cannot_close_an_old_card(tmp_path: Path) -> None:
    scribe, _ = _setup(tmp_path, evidence_turn=EVIDENCE)

    def liar(system: str, user: str) -> str:
        tag = re.search(r"\[(c\d+)\] \(남은 일", user).group(1)
        return json.dumps({"closes": [{"id": tag, "status": "done", "line": 140, "quote": "PR 을 이미 다 끝냈습니다"},
                                      {"id": tag, "status": "done", "line": 0, "quote": "README 숫자부터 바로잡자"}]},
                          ensure_ascii=False)

    assert scribe.run_once(liar)["closed"] == 0, "지어낸 인용 · 카드보다 앞선 말로는 못 닫는다(지금 규칙 그대로)"
    assert OLD_TEXT in [c["text"] for c in scribe._split("s1")[0]]


def test_a_swept_card_waits_for_new_lines_before_it_is_looked_at_again(tmp_path: Path) -> None:
    scribe, log = _setup(tmp_path, evidence_turn="다른 이야기를 합니다")
    scribe.SWEEP_AGAIN_LINES = 50
    calls: list[str] = []
    first = scribe.run_once(_closing_model(calls))
    assert first["swept"] == 1 and first["turns"] == 0 and calls == [], "겹치는 뒤 말이 없으면 모델을 부르지 않고 대 본 것만 적는다"
    again = scribe.run_once(_closing_model(calls))
    assert again == {"done": False, "why": "읽을 새 말이 없음"} and calls == [], "새 줄이 없으면 같은 카드를 맴돌지 않는다"
    # 새 줄이 쌓이고(서기가 읽어 둔 자리도 옮겨 감) 끝낸 말이 나오면 다시 대 보고 닫는다.
    with log.open("a", encoding="utf-8") as handle:
        handle.write("".join(_line("user", f"잡담 {i}") for i in range(60)) + _line("assistant", EVIDENCE))
    state = json.loads((scribe.root / "state.json").read_text(encoding="utf-8"))
    total = sum(1 for _ in log.open(encoding="utf-8"))
    state[str(log)].update(offset=log.stat().st_size, line=total, rc_offset=log.stat().st_size, rc_line=total)
    (scribe.root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert scribe.run_once(_closing_model(calls))["closed"] == 1


# ── 압축 직후 넘기는 글 ─────────────────────────────────────────────────────────────────────


def _card(kind: str, line: int, text: str = "", **extra) -> dict:
    return {"kind": kind, "line": line, "text": text or f"{kind} 카드 {line}", "quote": "q", "at": "10-24 01:00", **extra}


def test_old_cards_that_never_came_up_again_are_folded_into_one_line_not_closed() -> None:
    cards = [_card("open", n) for n in range(100, 135)]                       # 35장 — 상한 30
    cards.append(_card("open", 5, "아주 오래됐지만 방금 다시 나온 일", check_line=999))
    text, counts = render_handoff(cards, [])
    assert counts["shown"]["open"] == 30 and counts["folded"]["open"] == 6
    fold = next(line for line in text.splitlines() if line.startswith("(접음)"))
    assert "6장" in fold and "닫힌 것이 아니다" in fold and "줄 105 · 104 · 103 · 102 · 101 · 100" in fold
    assert "방금 다시 나온 일" in text, "오래된 카드라도 그 뒤 다시 나왔으면(확인 표시) 접지 않는다"
    assert "open 카드 134" in text and "open 카드 100  " not in text


def test_the_handoff_keeps_to_its_budget_by_folding_the_least_recent_first() -> None:
    cards = [_card("decided", n, f"정한 것 {n}: " + "긴 설명 " * 30) for n in range(200)]
    cards += [_card("open", 300 + n, f"남은 일 {n}: " + "긴 설명 " * 30) for n in range(40)]
    cards += [_card("corrected", 10, "한국어로만 쓴다")]
    text, counts = render_handoff(cards, [], budget=HANDOFF_CHARS)
    assert len(text) <= HANDOFF_CHARS
    assert "남은 일 39:" in text and "한국어로만 쓴다" in text, "가장 최근 남은 일 · 고쳐 준 것은 남는다"
    assert counts["folded"]["decided"] > 185 and counts["folded"]["open"] >= 10


def test_the_hook_uses_the_handoff_and_says_how_many_were_folded(monkeypatch) -> None:
    handoff = ("## 남은 일 · 약속\n(접음) 오래되고 그 뒤 다시 나오지 않은 남은 일 · 약속 15장 — 닫힌 것이 아니다 · 줄 295667\n"
               "- 옛 일  (10-23 13:00 · 줄 315000)\n- 새 일  (10-24 00:22 · 줄 323553)")
    story = {"count": 40, "card": "## 남은 일 · 약속\n- 최근 40장 글  (줄 1 · 「q」)", "handoff": handoff, "index": ""}
    monkeypatch.setattr(claude_hooks, "_story", lambda *a, **k: story)
    out = claude_hooks.after_compact({"session_id": "s1", "source": "compact"}, {"token-file": "x"})
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "최근 40장 글" not in context and context.index("새 일") < context.index("옛 일"), "넘길 글을 쓰고 최신이 위"
    assert "(접음)" in context and "남은 일 2(접음 15)" in out["systemMessage"]
    # 옛 손자리(넘길 글 칸이 없음)면 예전처럼 최근 카드 글.
    monkeypatch.setattr(claude_hooks, "_story", lambda *a, **k: {k2: v for k2, v in story.items() if k2 != "handoff"})
    out = claude_hooks.after_compact({"session_id": "s1", "source": "compact"}, {"token-file": "x"})
    assert "최근 40장 글" in out["hookSpecificOutput"]["additionalContext"]


def test_scribe_handoff_reads_every_open_card_of_the_session_not_only_the_last_40(tmp_path: Path) -> None:
    scribe, _ = _setup(tmp_path, evidence_turn=EVIDENCE)
    with (scribe.root / "cards.jsonl").open("a", encoding="utf-8") as handle:
        for n in range(45):
            handle.write(json.dumps({"kind": "decided", "text": f"정한 것 {n}", "line": 50 + n, "quote": "q", "session": "s1",
                                     "id": f"d{n}"}, ensure_ascii=False) + "\n")
    assert sum(1 for c in scribe.recent(40, "s1") if c["kind"] == "open") == 0, "전제: 최근 40장(모든 칸)에는 남은 일이 없다"
    text, counts = scribe.handoff("s1")
    assert counts == {"shown": {"decided": 15, "dropped": 0, "open": 30, "corrected": 0},
                      "folded": {"decided": 30, "dropped": 0, "open": 1, "corrected": 0}}
    fold = next(line for line in text.splitlines() if line.startswith("(접음)") and "남은 일" in line)
    assert fold.endswith("줄 1") and OLD_TEXT not in text, "가장 오래된 남은 일은 접히고(줄 번호만) 닫히지 않는다"
    assert OLD_TEXT in [c["text"] for c in scribe._split("s1")[0]]
