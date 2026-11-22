"""중간 소식 — 일하는 동안 **한 항목을 실제로 읽어 확인할 때마다** 짧은 한 줄을 쌓는다 (2026-11-14).

## 왜

대표(11-14): 「저장소 10개 다 돌린 뒤에 말하는 것보다 중간에 한 번만 알려줘도 사용자는 기다릴 맛이 난다」.
`sonjari_task_status` 의 진행(`progress`)에는 「지금 하는 일 · 시킨 것 n/m」만 있고 **찾은 내용이 없었다.**

## 지킬 것 (설계: `docs/설계_중간소식_2026-11-14.ko.md`)

- **모델이 쓴 글을 싣지 않는다.** 한 줄은 이 코드가 도구 결과(제목 · 읽은 본문)에서 결정론으로 만든다.
  값은 이미 검증된 자리에서만 꺼낸다 — 가게 값 레시피(`page_values`) · 두 번 맞은 값 칸(`value_cells.trusted`) ·
  깃허브 저장소 첫 화면의 별 · 라이선스.
- 그래도 **같은 그물을 한 번 더 친다**: 줄의 숫자가 그 걸음에서 읽은 본문 숫자(`numbers_in_body`)에 없으면
  (`unsupported_numbers` — 답의 숫자 대조와 같은 눈금) 그 값 조각을 뺀다. 이름 쪽에 걸리면 줄을 통째로 버린다.
- 「확인된 항목」 = 본문을 읽는 도구(`browser_extract` · `browser_read`)가 **성공**했고, http 주소이며, 검색 결과 · 로그인 ·
  오류 화면이 아니고, 본문이 짧지 않은 걸음. 같은 주소는 한 판에 한 줄.
- 어떤 이유로도 판을 막지 않는다 — 실패하면 None.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .evidence import numbers_claimed_in, numbers_in, numbers_in_body, unsupported_numbers
from .url_privacy import is_sign_in_url, safe_url

#: 본문을 실제로 읽는 도구 — 목록 · 검색 · 화면 훑기는 「한 항목을 읽어 확인」이 아니다.
READ_TOOLS = frozenset({"browser_extract", "browser_read"})
#: 이보다 짧은 본문은 빈 화면 · 막힌 화면이다.
MIN_BODY_CHARS = 300
NAME_MAX = 40
FACT_MAX = 24
FACTS_MAX = 3
LINE_MAX = 90
URL_MAX = 160

#: 검색 결과 화면 — 여러 항목의 목록이지 한 항목이 아니다.
_SEARCH_URL = re.compile(
    r"(?:google\.[a-z.]+/search|bing\.com/search|search\.naver\.com|duckduckgo\.com/|search\.daum\.net"
    r"|github\.com/search|/search(?:\?|/|$)|^https?://search\.)",
    # ★ 「?searchword=」 같은 질의 칸은 안 본다 — 재생(11-14)에서 사람인 **공고 상세**(rec_idx=…)가 검색어를 달고 와 다 빠졌다.
    re.IGNORECASE,
)
#: 오류 · 막힘 화면의 제목.
_ERROR_TITLE = re.compile(
    r"^(?:404|403|500|page not found|not found|access denied|just a moment|attention required|error)\b"
    r"|페이지를 찾을 수 없|로그인|접근이 거부|보안 문자|captcha"
    # ★ 운영 기록 재생(11-14): G마켓 봇 확인 화면 「잠시만 기다리십시오…」가 소식으로 나왔다.
    r"|잠시만 기다리|please wait|checking your browser|verify you are human",
    re.IGNORECASE,
)
#: 깃허브의 **목록** 화면(PR · 이슈 · 릴리스 · 커밋 목록) — 한 항목이 아니다(재생에서 「Pull requests · rust-lang/rust」).
_GITHUB_LIST = re.compile(r"^https?://github\.com/[^/]+/[^/]+/(?:pulls|issues|releases|commits|tags|branches)/?(?:[?#].*)?$",
                          re.IGNORECASE)
#: 제목 끝의 사이트 이름(「… - 예스24」 · 「… | 사람인」 · 「… · GitHub」).
_TITLE_TAIL = re.compile(r"\s+[-|·—–:]\s+[^-|·—–:]{1,24}$")
#: 깃허브 저장소 제목 — 「GitHub - owner/repo: 설명」 · 「owner/repo: 설명」.
_GITHUB_TITLE = re.compile(r"^(?:GitHub\s*-\s*)?([\w.-]+/[\w.-]+)(?::\s.*)?$")
_GITHUB_STARS = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{1,3})?\s?[kK]?|\d+)\s*stars?\b")
_GITHUB_LICENSE = re.compile(
    r"\b(MIT|Apache[- ]2\.0|GPL-?[23]\.0|AGPL-?3\.0|LGPL-?[23]\.\d|BSD-[23]-Clause|MPL-2\.0|Unlicense|ISC)\s+license\b",
    re.IGNORECASE,
)


_GITHUB_LICENSES = re.compile(r"\b([\w.-]{2,20}) and (\d{1,2}) other licenses? found\b", re.IGNORECASE)


def _is_github_repo(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    segments = [seg for seg in parts.path.split("/") if seg]
    return host == "github.com" and len(segments) == 2 and segments[0] not in {"topics", "orgs", "search", "trending"}


def _name(title: str, url: str) -> str:
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    if "github.com" in url:
        github = _GITHUB_TITLE.match(text)
        if github:
            return github.group(1)[:NAME_MAX]
        # 「Release 15.1.0 · BurntSushi/ripgrep」 꼴은 사이트 이름이 아니라 저장소가 꼬리다 — 그대로 둔다.
        return (text[: NAME_MAX - 1] + "…") if len(text) > NAME_MAX else text
    # 사이트 이름이 **앞에** 붙는 가게(「G마켓 - 닌텐도 스위치2 …」) — 아는 사이트 이름일 때만 뗀다.
    lead = _TITLE_LEAD.match(text)
    if lead and _SITE_NAME.search(lead.group(1)) and len(text) - lead.end() >= 2:
        text = text[lead.end():]
    for _ in range(2):
        tail = _TITLE_TAIL.search(text)
        if not tail:
            break
        head = text[: tail.start()]
        # 꼬리가 머리보다 짧거나 아는 사이트 이름일 때만 뗀다 — 「G마켓 - 긴 상품 이름」의 상품 이름을 꼬리로 떼지 않게(재생 11-14).
        if len(head) < 2 or not (len(tail.group(0)) < len(head) or _SITE_NAME.search(tail.group(0))):
            break
        text = head
    return (text[: NAME_MAX - 1] + "…") if len(text) > NAME_MAX else text


_TITLE_LEAD = re.compile(r"^([^-|·—–:]{1,12})\s+[-|·—–:]\s+")
_SITE_NAME = re.compile(
    r"위키백과|wikipedia|github|네이버|naver|예스24|yes24|교보문고|사람인|잡코리아|11번가|다나와|옥션|g마켓|gmarket|쿠팡|"
    r"알라딘|google|youtube|reddit|npm|pypi|stack overflow|나무위키|hacker news",
    re.IGNORECASE,
)


def _facts(url: str, body: str, cells: list[dict[str, Any]] | None) -> list[str]:
    facts: list[str] = []
    try:
        from . import page_values

        found = page_values.extract(url, body)
        if found:
            facts += [part.strip() for part in page_values.describe(found).split("·") if part.strip()]
    except Exception:  # noqa: BLE001 — 값 레시피 하나 때문에 줄을 못 쓰면 안 된다
        pass
    if cells:
        try:
            from .value_cells import apply, trusted

            for field, value in apply(trusted(cells), body).items():
                facts.append(f"{field} {value}")
        except Exception:  # noqa: BLE001
            pass
    if _is_github_repo(url):
        head = body[:6000]
        stars = _GITHUB_STARS.search(head)
        if stars:
            facts.append("별 " + stars.group(1).replace(" ", ""))
        # 라이선스가 여럿이면 깃허브가 「Apache-2.0 and 2 other licenses found」로 쓴다 — 하나만 적으면 반만 맞는 말이다
        # (실물 대조 11-14: rust-lang/rust 가 「MIT」로만 나왔다).
        several = _GITHUB_LICENSES.search(body[:20000])
        license_ = _GITHUB_LICENSE.search(body[:20000])
        if several:
            facts.append(f"{several.group(1)} 외 {several.group(2)}")
        elif license_:
            facts.append(license_.group(1))
    out: list[str] = []
    for fact in facts:
        fact = re.sub(r"\s+", " ", fact).strip()
        if fact and len(fact) <= FACT_MAX and fact not in out:
            out.append(fact)
        if len(out) >= FACTS_MAX:
            break
    return out


def news_line(
    tool: str, observation: dict[str, Any], *, step: int = 0, cells: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """이 걸음이 한 항목을 읽어 확인했으면 `{"text", "url", "step"}`, 아니면 None. 절대 예외를 던지지 않는다."""
    try:
        if tool not in READ_TOOLS or not observation.get("ok"):
            return None
        result = observation.get("result") if isinstance(observation.get("result"), dict) else observation
        url = str(result.get("url") or observation.get("url") or "")
        body = str(result.get("text") or observation.get("text") or "")
        title = str(result.get("title") or "")
        if not url.lower().startswith(("http://", "https://")) or _SEARCH_URL.search(url) or _GITHUB_LIST.match(url) or is_sign_in_url(url):
            return None
        chars = int(result.get("value_cells_from_chars") or result.get("char_count") or len(body) or 0)
        if chars < MIN_BODY_CHARS or not title.strip() or _ERROR_TITLE.search(title.strip()):
            return None
        name = _name(title, url)
        if len(name) < 2:
            return None
        facts = _facts(url, body, cells)
        # ★ 같은 그물(답의 숫자 대조와 같은 눈금) — 이 걸음에서 읽은 본문 · 제목 · 도구 필드에 없는 숫자는 싣지 않는다.
        seen = numbers_in_body({"title": title, "text": body}) | numbers_in(result)
        if unsupported_numbers(numbers_claimed_in(name), seen):
            return None
        facts = [fact for fact in facts if not unsupported_numbers(numbers_claimed_in(fact), seen)]
        text = name + (" — " + " · ".join(facts) if facts else "")
        if len(text) > LINE_MAX:
            text = text[: LINE_MAX - 1] + "…"
        return {"text": text, "url": safe_url(url)[:URL_MAX], "step": int(step or 0), "facts": len(facts)}
    except Exception:  # noqa: BLE001 — 중간 소식 때문에 판을 죽이지 않는다
        return None
