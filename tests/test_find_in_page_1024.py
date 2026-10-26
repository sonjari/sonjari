"""찾을 칸 — 본문 읽기가 페이지 전체(옆 칸 포함)에서 그 말이 든 줄을 맨 앞에 모아 준다 (2026-10-24 · 전략안 새 절).

깃허브 저장소 11개 조사(판 e9098192)가 56걸음 중 20걸음 안팎을 라이선스 찾기에 썼다. 라이선스는 깃허브 **옆 칸**에 있는데
본문 고르기는 옆 칸을 뺀다. 같은 판들이 「66.6k」를 66,600 으로 옮겨 적은 것을 숫자 검사가 「읽은 자료에 없는 숫자」로 막아
파일을 못 쓰고 접혔다(밤 측정 깃허브 6판 중 5판).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.browser import BrowserWorker, clean_find_terms, found_block
from alture_jarvis.config import JarvisConfig
from alture_jarvis.evidence import numbers_claimed_in, numbers_in_body, unsupported_numbers


# ── 숫자 검사: 영어 줄임 단위 ─────────────────────────────────────────────────────

def test_a_number_written_out_from_k_or_million_is_grounded() -> None:
    seen = numbers_in_body({"text": "Stars 66.6k · forks 4.1k · 11 million users · 2.5M downloads"})
    claimed = numbers_claimed_in("별 66,600 · 포크 4,100 · 사용자 1,100만 · 다운로드 2,500,000")
    assert unsupported_numbers(claimed, seen) == set()


def test_a_made_up_number_next_to_a_k_value_is_still_caught() -> None:
    seen = numbers_in_body({"text": "Stars 66.6k"})
    assert unsupported_numbers(numbers_claimed_in("별 66,700"), seen) == {"66700"}


def test_letters_that_are_not_a_scale_are_not_expanded() -> None:
    seen = numbers_in_body({"text": "37km away · a 48MB file · 72kg"})
    assert "37000" not in seen and "48000000" not in seen and "72000" not in seen


# ── 찾은 줄 덩어리 ─────────────────────────────────────────────────────────────────

PAGE_TEXT = """remotion-dev/remotion
Make videos programmatically
66.6k stars
4.1k forks
About
Make videos programmatically with React
License
Remotion License
Activity"""


def test_a_short_label_brings_the_value_on_the_next_line() -> None:
    block, meta = found_block(PAGE_TEXT, ["License"])
    assert "License / Remotion License" in block
    assert meta["hits"] == {"License": 2} and meta["missed"] == []


def test_a_term_that_is_not_on_the_page_is_reported_as_not_found() -> None:
    block, meta = found_block(PAGE_TEXT, ["라이선스", "stars"])
    assert meta["missed"] == ["라이선스"] and "못 찾음: 라이선스" in block
    assert "66.6k stars" in block


def test_the_side_column_is_added_only_when_the_body_did_not_already_carry_it() -> None:
    aside = "About\nMake videos programmatically with React\nRemotion License"
    _block, outside = found_block(PAGE_TEXT, ["stars"], aside=aside, body="README only")
    _block, inside = found_block(PAGE_TEXT, ["stars"], aside=aside, body=aside)
    assert outside["aside_chars"] > 0 and inside["aside_chars"] == 0


def test_a_long_block_says_it_was_cut() -> None:
    many = "\n".join(f"price line {i} " + "x" * 150 for i in range(200))
    block, meta = found_block(many, [f"line {i}" for i in range(12)])
    assert meta["truncated"] is True and block.endswith("잘라냈다)")
    assert len(block) <= 2400


def test_terms_are_cleaned_deduplicated_and_capped() -> None:
    assert clean_find_terms(["  License ", "license", "", None, "stars"]) == ["License", "stars"]
    assert len(clean_find_terms([f"t{i}" for i in range(30)])) == 12


# ── 하네스가 바깥 AI 의 needs 를 본문 읽기에 붙인다 ───────────────────────────────────

def _agent_with_terms(job_id: str, terms: tuple[str, ...]) -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.__dict__["_find_terms"] = {job_id: terms}
    return agent


def test_needs_are_added_to_a_page_read_and_the_models_own_words_come_first() -> None:
    agent = _agent_with_terms("job-1", ("라이선스", "별 수"))
    args = agent._with_find_terms("browser_extract", {"max_chars": 9000, "find": ["License"]}, "job-1")
    assert args == {"max_chars": 9000, "find": ["License", "라이선스", "별 수"]}


def test_other_tools_and_other_jobs_are_left_alone() -> None:
    agent = _agent_with_terms("job-1", ("라이선스",))
    assert agent._with_find_terms("browser_open", {"url": "https://github.com"}, "job-1") == {"url": "https://github.com"}
    assert agent._with_find_terms("browser_extract", {}, "job-2") == {}


# ── 진짜 크로미움: 깃허브 모양 페이지에서 옆 칸의 라이선스 ──────────────────────────────

GITHUB_LIKE = """<html><head><title>remotion-dev/remotion</title></head><body>
<header><nav><a href='/'>Home</a> <a href='/explore'>Explore</a></nav></header>
<div class='Layout'>
  <main><h1>remotion-dev/remotion</h1><p>66.6k stars · 4.1k forks</p>
    <article><h2>README</h2>""" + "".join(
    f"<p>Remotion lets you create videos programmatically using React. Paragraph {i} of the long readme.</p>" for i in range(40)
) + """</article></main>
  <aside class='Layout-sidebar'><h2>About</h2><p>Make videos programmatically with React</p>
    <h3>License</h3><p>MIT license</p><p>Activity</p></aside>
</div></body></html>"""


def test_a_page_read_with_find_shows_the_license_from_the_side_column(tmp_path: Path) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_content(GITHUB_LIKE)
            plain = worker._extract_with_data(page, {"max_chars": 20000})
            found = worker._extract_with_data(page, {"max_chars": 20000, "find": ["License"]})
        finally:
            browser.close()
    assert "MIT license" not in plain["text"], "옆 칸을 빼는 본문 고르기 — 이 시험이 보려는 빈칸"
    assert "find" not in plain
    head = found["text"].split("\n\n")[0]
    assert head.startswith("[찾는 칸") and "License / MIT license" in head
    assert found["find"]["hits"]["License"] >= 1
    # 같은 결과 안이라 숫자 장부 · 근거 대조가 그 줄을 읽은 원문으로 센다.
    assert "66600" in numbers_in_body(found)


def test_the_switch_turns_the_needs_off_for_a_before_after_measurement(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("JARVIS_FIND_FROM_NEEDS", "0")
    agent = _agent_with_terms("job-1", ("라이선스",))
    assert agent._with_find_terms("browser_extract", {"max_chars": 9000}, "job-1") == {"max_chars": 9000}
