"""막혔을 때 갈 **정직한 공개 출처** — 피드·사이트맵·공식 링크, 그리고 robots.txt (2026-09-18).

## 왜

봇 검사·로그인 벽에서 같은 곳을 다시 두드리면 차단이 길어지고, 우회(지문 위장·프록시)는 정직한 제품이 할 일이 아니다.
대신 사이트가 **기계에게 읽으라고 공개한 것**으로 간다:

- 페이지가 스스로 선언한 RSS·Atom 피드 (`<link rel="alternate">`)
- robots.txt 가 알려 주는 사이트맵 — 그리고 **지금 경로가 자동 수집 금지인지.** 금지면 긁지 말라고 알린다.
- 공식 링크: 「공식 홈페이지」·「개발사 웹사이트」·「게시자 웹 사이트」(MS 스토어 상세에 있다)

답에는 어디서 가져왔는지 밝힌다.
"""

from __future__ import annotations

from . import brand as _brand

import re
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

#: 페이지에서 한 번에 거둔다(요청 없음).
SOURCES_JS = """() => {
  const feeds = [];
  for (const l of __deepAll('link[rel~="alternate"]')) {
    const type = (l.getAttribute('type') || '').toLowerCase();
    if (/rss|atom|feed|json/.test(type) && l.href) feeds.push({ href: l.href, title: (l.getAttribute('title') || '').slice(0, 80), type });
  }
  const official = [];
  const words = /(공식|개발사|게시자|제조사|판매자\\s*홈|회사\\s*홈|홈페이지|official|developer|publisher|website|웹\\s*사이트)/i;
  for (const a of __deepAll('a[href]')) {
    const label = ((a.getAttribute('aria-label') || '') + ' ' + (a.innerText || '') + ' ' + (a.title || '')).replace(/\\s+/g, ' ').trim();
    if (!a.href.startsWith('http') || !words.test(label)) continue;
    official.push({ href: a.href, text: label.slice(0, 80) });
    if (official.length >= 12) break;
  }
  return { feeds: feeds.slice(0, 10), official };
}"""

_AGENT = _brand.NAME


def robots_verdict(robots_text: str, page_url: str) -> dict[str, Any]:
    """robots.txt 를 읽어 **이 경로를 자동으로 읽어도 되는지**와 사이트맵을 돌려준다."""
    parser = RobotFileParser()
    parser.parse((robots_text or "").splitlines())
    sitemaps = [m.strip() for m in re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", robots_text or "")][:10]
    allowed_ours = parser.can_fetch(_AGENT, page_url)
    allowed_any = parser.can_fetch("*", page_url)
    return {"path_allowed": bool(allowed_ours and allowed_any), "sitemaps": sitemaps}


def robots_url(page_url: str) -> str:
    parsed = urlparse(page_url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")


def note_for(result: dict[str, Any]) -> str:
    parts = []
    if result.get("path_allowed") is False:
        parts.append("★ 이 경로는 사이트가 robots.txt 로 **자동 수집을 막았다** — 이 페이지를 더 긁지 말고, 공개 출처나 사람에게 넘겨라.")
    if result.get("feeds") or result.get("sitemaps") or result.get("official"):
        parts.append("막히거나 값이 안 보이면 같은 곳을 다시 두드리지 말고 feeds·sitemaps·official 의 **공개 출처**로 가라. 답에는 어디서 가져왔는지 밝혀라.")
    else:
        parts.append("이 사이트는 공개 피드·사이트맵·공식 링크를 알려 주지 않는다. 막혔으면 사람에게 넘기거나 다른 공식 사이트를 검색해라.")
    return "[도구가 보낸 안내] " + " ".join(parts)
