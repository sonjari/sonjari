"""「돌려받을 항목(needs)」 검사가 **답에 다 있는데 0/n** 을 내지 않는다 (2026-10-19).

사고: 같은 날 바깥 AI(클로드 코드)가 needs 를 붙여 맡긴 세 판(022c62a1 · 029fae29 · f74274ef)이 0/4 · 0/5 · 0/3 이었다.
답에는 설정 명령 · 기본값 · 읽은 주소가 다 있었다. 항목 이름은 맡긴 쪽이 자유롭게 지은 말(「how to set num_ctx」 ·
「읽은 FAQ 페이지 URL」)이고 답은 제 말로 적는다(「Setting it with the num_ctx parameter」 · 「읽은 페이지 주소」).
검사는 이름 낱말이 표 머리 · 제목 · 「이름: 값」 줄에 그대로 있는지만 봤고, **못 찾으면 「없다」로 단정했다.**
클로드는 그 0/4 를 보고 사용자에게 「손자리 체크리스트가 0/4 라 믿기 어렵다」고 말했다.

고친 것(낱말표를 늘리지 않고 판정의 모양을 바꿨다):
- met 은 셋이다 — True(이름 붙은 자리에 값) · False(이름 붙은 자리가 **비어 있는 것을 봤다** · 또는 답도 파일도 아예 없다) ·
  None(이름 붙은 자리를 못 찾음 = 확인 못 함).
- 확인 못 한 항목이 있으면 영수증이 분수(「0/3」)를 쓰지 않는다 — 「필요한 것 3개 · 확인 못 함 3」.
- 메모도 둘로 나눈다 — 「비어 있는 항목」과 「확인 못 한 항목(비었다는 뜻이 아님)」.

양방향으로 지킨다: 내용이 있으면 False 가 안 나온다 · 정말 없는 항목은 True 가 안 된다 · 이름과 답의 언어가 달라도 같다.
표본 글 · 값 · 주소 · 도구 이름은 지어낸 것이다(주소는 example.com).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from alture_jarvis.delegation import summarize_job
from alture_jarvis.outbound import check_needs, outbound_record, receipt

FRACTION = re.compile(r"필요한 것 \d+/\d+")

# 022c62a1 모양 — 영어 이름 · 영어 산문 답(굵은 글씨 소제목 · 코드 칸 · 「Source:」 줄).
EN_NEEDS = ["how to set FAKETOOL_WINDOW", "how to set win_size", "default window length value", "source URL"]
EN_ANSWER = """Here's what the FakeTool FAQ says about the window size.

**(1) Default window length**
> "By default, FakeTool uses a window size of **2048 units**."

**(2) Setting it with the `FAKETOOL_WINDOW` environment variable**
```
FAKETOOL_WINDOW=4096 faketool serve
```

**(3) Setting it with the `win_size` parameter**
```
/set parameter win_size 2048
```

Source: https://example.com/faketool/docs/faq
"""

# 029fae29 모양 — 한국어 이름 · 한국어 번호 목록 답 · 표 없는 md 파일을 만들었다.
KO_NEEDS = ["FAKETOOL_WINDOW 설정 방법", "/set parameter win_size 방법", "API 로 win_size 넘기는 방법",
            "기본 창 길이 단위 수", "읽은 FAQ 페이지 URL"]
KO_ANSWER = """산출물 파일까지 완성했습니다.

## 결과

**내용** — FAQ 원문에 적힌 그대로:

1. **기본값**: 2048 단위
2. **환경 변수**: `FAKETOOL_WINDOW=4096 faketool serve`
3. **run 안**: `/set parameter win_size 2048`
4. **API**: `{"options": {"win_size": 2048}}`

**읽은 페이지 주소**: https://example.com/faketool/docs/faq
"""

# f74274ef 모양 — 영어 이름 · 「**Default value:** …」 줄 · 번호 목록.
EN2_NEEDS = ["ways to set the window", "default window length", "source URL"]
EN2_ANSWER = """Done. Here's everything the FAQ lists for setting the window size:

**Default value:** 2048 units

**The three ways to override it:**

1. **Environment variable** — `FAKETOOL_WINDOW=4096 faketool serve`
2. **CLI** — `/set parameter win_size 2048`
3. **API parameter** — `win_size` in the `options` object

**Source:** https://example.com/faketool/faq
"""


def _met(needs: list[str], answer: str, files: list[str] | None = None) -> dict[str, Any]:
    return {item["label"]: item["met"] for item in check_needs(needs, answer, files=files or [])}


def _job(answer: str, needs: list[str], *, files: list[str] | None = None) -> dict[str, Any]:
    steps = [{"tool": "browser_extract", "ok": True, "evidence": {"url": "https://example.com/faketool/docs/faq"},
              "evidence_record": {"effect": "read", "source_id": "https://example.com/faketool/docs/faq"}}]
    for path in files or []:
        steps.append({"tool": "local_write_document", "ok": True,
                      "evidence": {"action": "local_write_document", "output_path": path},
                      "evidence_record": {"effect": "write_local", "source_id": path.lower()}})
    return {"id": "j1019", "status": "completed",
            "payload": {"prompt": "FAQ 를 읽고 알려 줘", "origin": "mcp", "caller": "Claude Code", "needs": needs},
            "result": {"answer": answer, "agent_trace": {"steps": steps,
                                                        "tool_numbers": ["2048", "4096", "1", "2", "3", "4"]}}}


# ── (a) 내용이 있으면 0/n 이 안 나온다 ────────────────────────────────────────────────


def test_english_prose_answer_is_never_judged_empty() -> None:
    met = _met(EN_NEEDS, EN_ANSWER)
    assert False not in met.values(), met


def test_korean_numbered_answer_with_a_tableless_file_is_never_judged_empty(tmp_path: Path) -> None:
    made = tmp_path / "faketool_창_변경_방법.md"
    made.write_text("# 창 바꾸기\n\n- 기본값 2048 단위\n- `FAKETOOL_WINDOW=4096 faketool serve`\n", encoding="utf-8")

    met = _met(KO_NEEDS, KO_ANSWER, [str(made)])
    assert False not in met.values(), met


def test_labelled_bold_lines_answer_is_never_judged_empty() -> None:
    met = _met(EN2_NEEDS, EN2_ANSWER)
    assert False not in met.values(), met


def test_the_summary_receipt_has_no_zero_fraction_for_those_answers() -> None:
    for answer, needs in ((EN_ANSWER, EN_NEEDS), (KO_ANSWER, KO_NEEDS), (EN2_ANSWER, EN2_NEEDS)):
        summary = summarize_job(_job(answer, needs))
        line = summary["receipt"]["line"]
        assert not FRACTION.search(line) or summary["receipt"]["needs_unknown"] == 0, line
        assert "필요한 것 0/" not in line, line
        assert summary["receipt"]["needs_missing"] == 0
        notes = " ".join(summary.get("review_notes") or [])
        assert "비어 있는 항목" not in notes, notes


def test_unchecked_items_get_their_own_note_that_says_they_are_not_empty() -> None:
    summary = summarize_job(_job(EN_ANSWER, EN_NEEDS))
    unchecked = [item["label"] for item in summary["needs"] if item["met"] is None]
    assert unchecked, "이 표본은 이름 낱말로 자리를 못 찾는 항목이 있어야 한다"
    note = next(note for note in summary["review_notes"] if "확인하지 못한 항목" in note)
    assert all(label in note for label in unchecked)
    assert "비어 있다는 뜻이 아닙니다" in note


def test_a_section_split_into_sub_headings_is_not_empty() -> None:
    """728ecaa5 모양 — 「## 네 커뮤니티 …」 바로 아래가 「### r/가상1」 하위 절이었다. 전에는 「제목 아래가 비었다」로 봤다."""
    answer = "## 네 커뮤니티 인기 글\n\n### **r/가상1**\n\n| 순위 | 제목 |\n|---|---|\n| 1 | 가상 글 |\n"
    assert _met(["커뮤니티"], answer) == {"커뮤니티": True}


# ── (b) 정말 없는 항목은 「있음」이 되지 않는다 ─────────────────────────────────────────


def test_an_item_the_answer_never_gives_is_not_met() -> None:
    met = _met(EN2_NEEDS + ["review count"], EN2_ANSWER)
    assert met["review count"] is not True


def test_a_labelled_but_blank_place_is_empty() -> None:
    answer = EN2_ANSWER + "\nReview count: N/A\n"
    assert _met(["review count"], answer) == {"review count": False}
    table = "| shop | price | stock |\n|---|---|---|\n| A | 10 | - |\n| B | 12 |  |\n"
    assert _met(["price", "stock"], table) == {"price": True, "stock": False}
    heading = "### 리뷰 수\n\n### 가격\n- 10\n"
    assert _met(["리뷰 수", "가격"], heading) == {"리뷰 수": False, "가격": True}


def test_nothing_back_at_all_is_empty_for_every_item() -> None:
    assert _met(["가격", "source URL"], "   ") == {"가격": False, "source URL": False}


def test_a_failed_run_does_not_turn_into_met() -> None:
    """0e4a6657 모양 — 브라우저가 못 떠서 아무 값도 못 가져온 답. 확인 못 함은 될 수 있어도 「있음」은 안 된다."""
    answer = ("브라우저가 두 번 연속 내부 오류로 시작에 실패했습니다.\n\n## 지금까지 한 일\n\n| 항목 | 상태 |\n|---|---|\n"
              "| 가상몰 상품 페이지 열기 | ❌ 시작 실패 |\n| 파일 업데이트 | ❌ 값이 없어서 안 함 |\n")
    met = _met(["가상몰 상품 이름", "가상몰 가격", "가상몰 배송비"], answer)
    assert True not in met.values(), met


# ── (c) 이름과 답의 언어가 달라도 ──────────────────────────────────────────────────────


def test_korean_names_with_an_english_answer() -> None:
    met = _met(["기본 창 길이", "읽은 페이지 주소", "리뷰 수"], EN2_ANSWER)
    assert False not in met.values(), met          # 있는 것을 없다고 하지 않는다
    assert met["리뷰 수"] is not True               # 없는 것을 있다고 하지 않는다


def test_english_names_with_a_korean_answer() -> None:
    met = _met(["default window length", "source URL", "review count"], KO_ANSWER)
    assert False not in met.values(), met
    assert met["review count"] is not True


# ── 이름 붙은 자리를 찾는 길은 그대로 일한다 ────────────────────────────────────────────


def test_named_columns_still_count_as_met() -> None:
    answer = "| 가게 | 판매 가격 | 페이지 주소 |\n|---|---|---|\n| 가상몰 | 10,000원 | https://example.com/p/1 |\n"
    assert _met(["판매 가격", "페이지 주소"], answer) == {"판매 가격": True, "페이지 주소": True}


def test_a_made_spreadsheet_still_fills_the_needs(tmp_path: Path) -> None:
    """759ba894 모양(10-16 에 고친 것) — 답은 경로만, 표는 엑셀에만."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["순위", "제목", "점수(업보트)", "댓글 수", "올린 시각"])
    sheet.append([1, "가상 글", 10, 2, "2026-01-01 00:00"])
    made = tmp_path / "가상_인기글.xlsx"
    book.save(made)

    summary = summarize_job(_job(f"엑셀 파일을 만들었습니다: `{made}`", ["제목", "점수", "댓글 수", "올린 시각"],
                                 files=[str(made)]))
    assert [item["met"] for item in summary["needs"]] == [True] * 4
    assert "필요한 것 4/4" in summary["receipt"]["line"]


# ── 영수증 · 화면 기록 · 영어 연결 ─────────────────────────────────────────────────────


def test_receipt_counts_the_three_states_separately() -> None:
    made = receipt([{"label": "a", "met": True}, {"label": "b", "met": False}, {"label": "c", "met": None}], [],
                   host="Claude Code")
    assert (made["needs_total"], made["needs_met"], made["needs_missing"], made["needs_unknown"]) == (3, 1, 1, 1)
    assert made["line"] == "Claude Code 에게 보냄 · 필요한 것 3개 · 채움 1 · 비어 있음 1 · 확인 못 함 1 · 정제 0"
    known = receipt([{"label": "a", "met": True}, {"label": "b", "met": False}], [], host="Claude Code")
    assert known["line"] == "Claude Code 에게 보냄 · 필요한 것 1/2 · 정제 0"


def test_the_screen_record_carries_the_same_three_states() -> None:
    record = outbound_record(EN_ANSWER, {"origin": "mcp", "caller": "claude-code", "needs": EN_NEEDS})
    assert record is not None
    assert record["needs_missing"] == 0
    assert record["needs_met"] + record["needs_unknown"] == len(EN_NEEDS)
    summary = summarize_job(_job(EN_ANSWER, EN_NEEDS))
    assert summary["needs"] == record["needs"]


def test_the_english_connection_translates_the_new_lines() -> None:
    from alture_jarvis.mcp_server import JarvisMcpBridge

    hangul = re.compile("[가-힣]")
    summary = summarize_job(_job(EN_ANSWER, EN_NEEDS))
    out = JarvisMcpBridge(lang="en").say({"receipt": summary["receipt"], "review_notes": summary["review_notes"]})
    assert not hangul.search(out["receipt"]["line"]), out["receipt"]["line"]
    assert "not checked" in out["receipt"]["line"]
    assert all(not hangul.search(note) for note in out["review_notes"]), out["review_notes"]
