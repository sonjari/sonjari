"""2026-11-12 공개 저장소에 CodeQL 을 켜자 경보 112건 — 그중 **진짜**를 고친 시험.

진짜로 판정한 것(나머지는 열쇠 뒤 · 이 PC 안 · 시험 코드 · 오탐 — 판정 목록은 커밋 글):
1. 남이 만든 글에 도는 정규식이 지수로 멈췄다(실측): 내려받은 파일 앞머리 판별 27초 · 표 한 줄 22초 · 금지 말 6초 · 지침 주석 11초.
2. 「naver.com 이 주소 어딘가에 있으면 네이버」 — 로그인 관문이 `evil.example/?next=naver.com` 도 「네이버 로그인 끝남」으로 넘겼다.
3. 장표 스크립트 거름이 `</script foo>` 로 닫힌 스크립트를 못 걸렀다.
"""
from __future__ import annotations

import time

import pytest

from alture_jarvis import browser, documents, human_gate, plan, profile, slides
from alture_jarvis.hostname import on_domain, url_on_domain

_HTML_HEAD = next(v for v in vars(browser).values() if isinstance(v, type) and hasattr(v, "_HTML_HEAD"))._HTML_HEAD


def _fast(fn, text, limit: float = 1.0) -> None:
    started = time.perf_counter()
    fn(text)
    assert time.perf_counter() - started < limit, "남이 만든 글 하나로 멈추면 안 된다"


@pytest.mark.parametrize("fn, attack", [
    (_HTML_HEAD.match, b"<!--" + b"--><!--" * 60),          # 옛 식: 28번에 27초
    (documents._FLAT_ROW.search, "[" + "0" * 60),            # 옛 식: 28자에 22초
    (plan._WRITE_PROHIBITION.search, "\t검토" * 60),         # 옛 식: 25번에 6초
    (plan._JOB_WIDE_PROHIBITION.search, "\t검토" * 60),
    (profile.strip_comments, "<!--" * 30000),               # 옛 식: 12만 자에 11초
], ids=["html_head", "flat_row", "write_prohibition", "job_wide_prohibition", "profile_comments"])
def test_hostile_text_does_not_hang_the_regexes(fn, attack) -> None:
    _fast(fn, attack)


def test_the_regexes_still_catch_what_they_caught() -> None:
    assert _HTML_HEAD.match(b"<!-- a --> <!-- b ---> \n<!DOCTYPE html><html>")
    assert not _HTML_HEAD.match(b"<!-- x --> hello")
    for good in ['[1, 2, 3]', '["a,b", "c]d", 1.5, true, null]', '[ ]', '[1,2,]']:
        assert documents._FLAT_ROW.fullmatch(good), good
    for said in ["조사·분석만 해", "조사와 분석만 해주세요", "조사 및 검토만 하라", "검토만 해"]:
        assert plan._WRITE_PROHIBITION.search(said) and plan._JOB_WIDE_PROHIBITION.search(said), said
    assert profile.strip_comments("a<!-- x -->b<!-- y") == "ab<!-- y", "닫히지 않은 주석은 사람이 쓴 글 — 그대로"


def test_a_site_is_its_host_not_a_substring() -> None:
    assert url_on_domain("https://nid.naver.com/login", "naver.com")
    assert url_on_domain("nid.naver.com/nidlogin.login", "naver.com")
    assert not url_on_domain("https://evil.example/?next=naver.com", "naver.com")
    assert not url_on_domain("https://evilnaver.com/", "naver.com")
    assert not url_on_domain("https://naver.com.evil.example/", "naver.com")
    assert on_domain("m.youtube.com", "youtube.com") and not on_domain("notyoutube.com", "youtube.com")


def test_the_login_gate_is_not_cleared_by_naver_in_the_query() -> None:
    real = {"code": "login_required", "url": "https://nid.naver.com/nidlogin.login"}
    fake = {"code": "login_required", "url": "https://evil.example/login?next=naver.com"}
    # 사람이 아직 그 로그인 벽 앞에 서 있다(주소 그대로) · 네이버에는 로그인돼 있다.
    assert human_gate.is_cleared(real, {"known": True, "naver_signed_in": True, "url": real["url"]})
    assert not human_gate.is_cleared(fake, {"known": True, "naver_signed_in": True, "url": fake["url"]}),         "네이버 로그인이 남의 사이트 로그인 벽을 풀어 주면 안 된다"


@pytest.mark.parametrize("html", [
    "<p>a</p><script>alert(1)</script foo><p>b</p>",
    "<p>a</p><script>alert(1)</script\t\n bar><p>b</p>",
    "<p>a</p><script>alert(1)",
])
def test_slide_scripts_are_stripped_however_they_close(html: str) -> None:
    assert "alert" not in slides._SCRIPT.sub("", html)
