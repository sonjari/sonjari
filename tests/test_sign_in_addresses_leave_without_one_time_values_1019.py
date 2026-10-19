"""로그인 · 계정 화면 주소의 한 번 쓰는 값은 바깥 AI 에게 나가지 않는다 (2026-10-19 · 잡 51f35b07).

그 판의 sources 에 `accounts.google.com/v3/signin/accountchooser?client_id=…&code_challenge=…&nonce=…&state=…` 가 그대로
실려 클로드에게 갔다. 출처는 「그 화면을 봤다」면 충분하다 — `scheme://host/path` 로 줄인다(`url_privacy.safe_url`).

양방향: 평범한 출처의 `?code=005930`(증권) · `?state=TX`(매물) · `?q=` · `?sid=105`(뉴스 분류) 는 그대로 둔다.
운영 기록 17,114개 출처 중 바뀐 것은 23개, 전부 로그인 화면이었다(2026-10-19 되짚기).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from alture_jarvis.delegation import summarize_job
from alture_jarvis.outbound import outbound_job_view, refine
from alture_jarvis.url_privacy import has_one_time_values, is_sign_in_url, safe_url, scrub_urls

GOOGLE_CHOOSER = (
    "https://accounts.google.com/v3/signin/accountchooser?client_id=1078992815106-brpsupgvhheqg35tupphbh0qk9c32nq8"
    ".apps.googleusercontent.com&code_challenge=k3SpV-jjYsCVFZ8UdP1HezCN4zioXs6FDqvR89ZaHLo&code_challenge_method=S256"
    "&nonce=n0nce123&state=st4te456&continue=https%3A%2F%2Fexample.com"
)


@pytest.mark.parametrize("url, shortened", [
    (GOOGLE_CHOOSER, "https://accounts.google.com/v3/signin/accountchooser"),
    ("https://github.com/login?add_account=1&return_to=https%3A%2F%2Fgithub.com%2Follama%2Follama", "https://github.com/login"),
    ("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=a&nonce=b&state=c",
     "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"),
    ("https://nid.naver.com/oauth2.0/authorize?response_type=code&client_id=x&state=y", "https://nid.naver.com/oauth2.0/authorize"),
    ("https://searchadvisor.naver.com/auth/callback?code=P793uGb3bNxlMiHy4a&state=9665962872abea",
     "https://searchadvisor.naver.com/auth/callback"),
    ("https://app.example.com/done#access_token=eyJhbGciOi.abc.def&token_type=bearer", "https://app.example.com/done"),
    ("https://files.example.com/a.pdf?X-Amz-Signature=abcdef0123&X-Amz-Credential=AKIA", "https://files.example.com/a.pdf"),
    ("https://api.example.com/cb?client_id=abc&code=4/0AbCdEf", "https://api.example.com/cb"),
    ("https://user:hunter2@example.com/page?q=1", "https://example.com/page?q=1"),
])
def test_sign_in_and_one_time_values_are_shortened(url: str, shortened: str) -> None:
    assert safe_url(url) == shortened


@pytest.mark.parametrize("url", [
    "https://finance.naver.com/item/main.naver?code=005930",
    "https://www.landwatch.com/texas-land-for-sale?state=TX",
    "https://doctor.webmd.com/results?q=Audiologist&city=New+York&state=36",
    "https://www.google.com/search?q=sonjari+github",
    "https://n.news.naver.com/mnews/article/047/0002525644?sid=100",
    "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=54445382&search_uuid=abc",
    "https://www.ekn.kr/web/view.php?key=20261006029482500",
    "https://www.selenium.dev/selenium/web/submitted-form.html?my-text=a&my-password=&my-select=2",
    "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure",
    "https://m.danawa.com/product/product.html?code=73432709&cateCode=12237349",
])
def test_ordinary_sources_are_kept_as_they_are(url: str) -> None:
    assert safe_url(url) == url
    assert not has_one_time_values(url)


def test_the_sign_in_test_is_about_the_screen_not_the_word() -> None:
    assert is_sign_in_url("https://accounts.google.com/anything")
    assert is_sign_in_url("https://login.genspark.ai/x/b2c_1_new_login/oauth2/v2.0/authorize")
    assert is_sign_in_url("https://www.jobkorea.co.kr/Login/Login_Tot.asp?re_url=x")
    assert not is_sign_in_url("https://nextjs.org/docs/app/building-your-application/authentication")
    assert not is_sign_in_url("https://blog.example.com/how-to-login-faster-guide")


def _job(steps: list[dict[str, Any]], *, answer: str = "끝") -> dict[str, Any]:
    return {"id": "j1", "status": "completed", "payload": {"origin": "mcp", "prompt": "x"},
            "result": {"answer": answer, "completion_state": "complete",
                       "agent_trace": {"steps": steps, "tool_numbers": [], "tool_numbers_body": []}}}


def _read(url: str) -> dict[str, Any]:
    return {"tool": "browser_snapshot", "ok": True, "evidence": {"url": url},
            "evidence_record": {"effect": "read_web", "source_id": url}}


def test_the_incident_sources_leave_without_the_one_time_values() -> None:
    steps = [_read("https://github.com/sonjari/sonjari"), _read(GOOGLE_CHOOSER),
             _read("https://github.com/login?add_account=1&return_to=https%3A%2F%2Fgithub.com%2Follama%2Follama"),
             _read("https://github.com/ollama/ollama")]
    summary = summarize_job(_job(steps))
    assert summary["sources"] == [
        "https://github.com/sonjari/sonjari",
        "https://accounts.google.com/v3/signin/accountchooser",
        "https://github.com/login",
        "https://github.com/ollama/ollama",
    ], "화면을 봤다는 사실은 남긴다 — 지우지 않고 줄인다"
    sent = json.dumps(summary, ensure_ascii=False)
    for value in ("code_challenge", "k3SpV-jjYs", "n0nce123", "st4te456", "client_id"):
        assert value not in sent


def test_a_failed_job_report_is_shortened_too() -> None:
    job = {"id": "j2", "status": "failed", "error": "boom", "payload": {"origin": "mcp"},
           "result": {"partial": {"sources": [GOOGLE_CHOOSER, "https://www.google.com/search?q=a"], "files": []},
                      "agent_trace": {"steps": []}}}
    summary = summarize_job(job)
    assert summary["sources"] == ["https://accounts.google.com/v3/signin/accountchooser", "https://www.google.com/search?q=a"]


def test_the_answer_and_the_whole_outbound_copy_are_shortened() -> None:
    answer = f"계정 고르기 화면({GOOGLE_CHOOSER})에서 멈췄습니다. 검색은 https://www.google.com/search?q=a 에서 했습니다."
    cleaned, refined = refine(answer)
    assert "code_challenge" not in cleaned and "https://accounts.google.com/v3/signin/accountchooser)" in cleaned
    assert "https://www.google.com/search?q=a" in cleaned
    assert {"kind": "로그인 주소", "count": 1} in refined

    job = _job([_read(GOOGLE_CHOOSER)], answer=answer)
    job["result"]["grounding"] = {"sources": [GOOGLE_CHOOSER]}
    shaped = outbound_job_view(job)
    sent = json.dumps(shaped, ensure_ascii=False)
    assert "code_challenge" not in sent and "n0nce123" not in sent
    assert "code_challenge" in json.dumps(job, ensure_ascii=False), "이 PC 의 원본 기록은 건드리지 않는다"


def test_scrub_keeps_sentence_punctuation_outside_the_address() -> None:
    text, n = scrub_urls(f"주소: {GOOGLE_CHOOSER}. 끝")
    assert n == 1 and text == "주소: https://accounts.google.com/v3/signin/accountchooser. 끝"
