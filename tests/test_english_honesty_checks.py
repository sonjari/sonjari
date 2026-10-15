"""영어 답에서도 정직 검사가 돈다 — 양방향 표본 (2026-10-01, 영어판 ③-1).

처음 쟀을 때(28칸) **10칸이 틀렸다**: 영어 답에 「$129.99」·「Based on my review of the code」·「on Amazon」·
「I've opened it on your screen」을 지어내도 8개 검사 중 6개가 조용했다. 영어 사양 표(「| Feature | Value |」)에는
헛경고가 붙었다. 한국어 표본은 전부 경고가 떠서 재는 도구 자체는 믿을 만했다.

표본은 `bench/english_honesty/measure_checks.py` 한 곳에 둔다(재는 도구와 이 시험이 같은 표본을 본다).

    *_fab  지어낸 답 — 경고(⚠)가 떠야 한다
    *_ok   맞는 답·권유·화제 — 조용해야 한다(「(열려 있는 주소: …)」 같은 안내는 경고가 아니다)
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import pytest

_HARNESS = Path(__file__).resolve().parents[1] / "bench" / "english_honesty" / "measure_checks.py"
_spec = importlib.util.spec_from_file_location("english_honesty_measure", _HARNESS)
harness = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(harness)

_TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
_AGENT = harness._agent(Path(_TMP.name))
CASES = harness.cases(_AGENT)


@pytest.mark.parametrize("check,kind,run", CASES, ids=[f"{c}-{k}" for c, k, _ in CASES])
def test_each_sample_lands_on_the_right_side(check: str, kind: str, run) -> None:
    note = run() or ""
    warned = "⚠" in note
    if kind.startswith(harness.EXPECT_WARN):
        assert warned, f"{check}/{kind}: 지어낸 답인데 경고가 안 떴다"
    else:
        assert not warned, f"{check}/{kind}: 맞는 답에 헛경고 — {note.strip()[:120]}"


def test_both_languages_are_covered_for_every_check() -> None:
    # 검사마다 한국어 지어낸 답(눈금 역검증) · 영어 지어낸 답 · 영어 맞는 답이 다 있어야 「양방향」이다.
    by_check: dict[str, set[str]] = {}
    for check, kind, _ in CASES:
        by_check.setdefault(check, set()).add(kind.split("_")[0] + "_" + kind.split("_")[1])
    for check, kinds in by_check.items():
        assert {"ko_fab", "en_fab"} <= kinds, check
        if check != "left_open" and check != "comparison":
            assert "en_ok" in kinds, check


# ── 경고를 사람의 언어로 (2026-10-01 영어판 ③-1 · P2 의 경고 몫) ─────────────────────────
# 지어낸 영어 답을 잡아도 경고가 **한국어**로 붙었다 — 영어 사용자는 못 읽는다.

import re as _re

from alture_jarvis import agent as _agent_module
from alture_jarvis.plan import Requirement, summary_note

_HANGUL = _re.compile(r"[가-힣]")


@pytest.mark.parametrize("check,kind,run", [c for c in CASES if c[1].startswith("en_fab")],
                         ids=[f"{c}-{k}" for c, k, _ in CASES if k.startswith("en_fab")])
def test_an_english_run_warns_in_english(check: str, kind: str, run) -> None:
    token = _agent_module._REPLY_LANGUAGE.set("en")
    try:
        note = run() or ""
    finally:
        _agent_module._REPLY_LANGUAGE.reset(token)
    assert "⚠" in note
    assert not _HANGUL.search(note), f"{check}/{kind}: 영어 판 경고에 한글 — {note.strip()[:160]}"


@pytest.mark.parametrize("check,kind,run", [c for c in CASES if c[1] == "ko_fab"],
                         ids=[c for c, k, _ in CASES if k == "ko_fab"])
def test_a_korean_run_still_warns_in_korean(check: str, kind: str, run) -> None:
    token = _agent_module._REPLY_LANGUAGE.set("ko")
    try:
        note = run() or ""
    finally:
        _agent_module._REPLY_LANGUAGE.reset(token)
    assert "⚠" in note and _HANGUL.search(note), check


def test_the_checklist_reads_in_english() -> None:
    results = [
        (Requirement("count", "3개 이상 직접 열어 읽기", 3), False, "1개 읽음 · 답에 3개"),
        (Requirement("site", "Amazon에서 하기", ("amazon.com",)), True, "2건"),
        (Requirement("artifact", "실제 산출물 파일 만들기", (".xlsx",)), False, "실행 안 됨"),
    ]
    english = summary_note(results, "en")
    assert english.startswith("\n\n**Checklist**")
    assert not _HANGUL.search(english), english
    assert "Open and read at least 3 yourself — 1 read · 3 in the answer" in english
    assert "Do it on Amazon" in english
    korean = summary_note(results, "ko")
    assert "**시킨 것 대조**" in korean and "3개 이상 직접 열어 읽기" in korean


def test_an_english_checklist_stays_out_of_the_file() -> None:
    # 우리가 답 끝에 붙인 대조표는 산출물 본문이 아니다(09-16: 엑셀에 「❌ 3개 이상 직접 열어 읽기」가 들어갔다).
    body = "| Title | Price |\n| --- | --- |\n| A | $10 |\n\n**Checklist**\n- ❌ Open and read at least 3 yourself — 1 read"
    assert _agent_module._OUR_APPENDED_NOTES.split(body, maxsplit=1)[0].rstrip().endswith("| A | $10 |")
