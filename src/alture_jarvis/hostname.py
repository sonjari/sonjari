"""주소가 어느 사이트인가 — 글자 포함이 아니라 호스트로 가른다 (2026-11-12 CodeQL 경보 정리).

`"naver.com" in url` 은 `https://evil.example/?next=naver.com` 도 네이버로 보고,
`host.endswith("naver.com")` 은 `evilnaver.com` 도 네이버로 본다. 로그인 관문(`human_gate.is_cleared`)이
이 판정으로 「네이버 로그인 끝남」을 내렸다 — 같은 자리를 여러 군데서 따로 짜면 한쪽만 고쳐진다(사고 Q), 그래서 한 곳에 둔다.
"""
from __future__ import annotations

from urllib.parse import urlparse

__all__ = ["host_of", "on_domain", "url_on_domain"]


def host_of(url: str) -> str:
    """주소의 호스트(소문자 · 포트 없음). 스킴이 없으면 붙여 읽는다. 못 읽으면 빈 문자열."""
    text = str(url or "").strip()
    if not text:
        return ""
    if "//" not in text.split("?", 1)[0]:
        text = "//" + text
    try:
        return (urlparse(text).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def on_domain(host: str, domain: str) -> bool:
    """`host` 가 `domain` 그 자체이거나 그 하위 도메인인가(`m.naver.com` → naver.com 예 · `evilnaver.com` → 아니오)."""
    host = str(host or "").lower().rstrip(".").split(":", 1)[0]
    domain = str(domain or "").lower().strip(".")
    return bool(host and domain) and (host == domain or host.endswith("." + domain))


def url_on_domain(url: str, domain: str) -> bool:
    return on_domain(host_of(url), domain)
