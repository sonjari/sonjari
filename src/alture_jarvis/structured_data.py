"""페이지에 **사이트가 직접 박아 둔 구조화 데이터**를 읽는다 (2026-09-18).

## 왜

화면 글자는 번역·난독화·섀도 DOM·지연 로딩에 흔들린다. 그런데 쇼핑·도서·채용·앱 상세 페이지 대부분은 검색엔진에
보이려고 **JSON-LD(schema.org)** 로 같은 값을 깔끔하게 넣어 둔다 — 검색 노출이 걸려 있어 사이트가 오히려 정확하게 유지한다.

2026-09-18 실측(헤드리스, 우리가 30일간 제일 많이 연 상세 페이지):

    YES24      Book            isbn · numberOfPages · datePublished
    교보문고    Book            isbn · aggregateRating · author · publisher
    알라딘      Book            aggregateRating · offers · author · publisher (+ og:price · og:barcode)
    잡코리아    JobPosting      title · validThrough · hiringOrganization · jobLocation
    위시켓      JobPosting      validThrough · baseSalary · employmentType
    무신사      Product         offers · aggregateRating · brand
    MS 스토어   SoftwareApplication  aggregateRating · author · offers
    다나와      ld+json 이 **문법이 깨져** JSON.parse 실패 → 너그럽게 다시 읽는다
    크몽        Organization·FAQ 뿐(쓸 값 없음) · 사람인·쿠팡·여기어때는 헤드리스를 막음

같은 날 MS 스토어 판에서 크롬 자동 번역이 화면의 「OpenAI」를 「오픈아이」로 바꿔 읽혔다 — 구조화 데이터는 번역되지 않는다.

## 규칙

- **읽기만 한다.** 페이지가 이미 가진 `<script type="application/ld+json">`·`<meta>` 뿐이다. 요청을 새로 보내지 않는다.
- 값을 **고치지 않는다.** 줄이기만 한다(이미지·로고·긴 설명). 줄였으면 줄였다고 적는다.
- 쓸모없는 유형(사이트·회사 소개·경로 표시)은 버린다 — 모델의 주의를 먹는다.
"""

from __future__ import annotations

import re
from typing import Any

#: 페이지 안에서 한 번에 거둔다. ld+json 은 대개 일반 DOM(head)에 있지만 섀도 루트 안에 둔 사이트도 있어 깊게 본다.
STRUCTURED_DATA_JS = """() => {
  const blocks = [];
  const lenient = (raw) => {
    try { return JSON.parse(raw); } catch (e) {}
    // 흔한 고장 둘: 문자열 안의 날것 줄바꿈·탭, 끝에 남은 쉼표.
    const repaired = raw.replace(/[\\u0000-\\u001F]+/g, ' ').replace(/,\\s*([}\\]])/g, '$1');
    try { return JSON.parse(repaired); } catch (e) { return { __unparsed: raw.slice(0, 200) }; }
  };
  for (const s of __deepAll('script[type="application/ld+json"]')) {
    const raw = (s.textContent || '').trim();
    if (raw) blocks.push(lenient(raw));
  }
  const meta = {};
  for (const m of __deepAll('meta[property], meta[name]')) {
    const key = (m.getAttribute('property') || m.getAttribute('name') || '').toLowerCase();
    if (/^(og:(title|type|price|barcode|site_name)|product:|twitter:data|book:|article:published_time)/.test(key) && m.content) meta[key] = m.content.slice(0, 200);
  }
  return { blocks: blocks.slice(0, 20), meta };
}"""

_KEEP_TYPES = frozenset({
    "product", "productgroup", "book", "softwareapplication", "mobileapplication", "webapplication", "videogame",
    "jobposting", "event", "course", "recipe", "offer", "aggregateoffer", "hotel", "lodgingbusiness",
    "localbusiness", "restaurant", "store", "movie", "tvseries", "musicalbum", "vehicle", "car", "service",
    "itemlist", "review", "place", "touristattraction", "apartment", "house", "realestatelisting",
    "newsarticle", "article", "blogposting", "dataset", "creativework",
})
_DROP_KEYS = frozenset({
    "@context", "@id", "image", "logo", "screenshot", "thumbnail", "thumbnailurl", "sameas", "potentialaction",
    "mainentityofpage", "breadcrumb", "photo", "video", "contentreferencetime", "publishingprinciples",
})
_MAX_LINES = 60
_MAX_TEXT = 300


def _types_of(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(value).lower().rsplit("/", 1)[-1] for value in values if value}


def _nodes(block: Any) -> list[dict[str, Any]]:
    if isinstance(block, list):
        return [node for item in block for node in _nodes(item)]
    if not isinstance(block, dict):
        return []
    if isinstance(block.get("@graph"), list):
        return [node for item in block["@graph"] for node in _nodes(item)]
    return [block]


def _scalar(value: Any) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "…"


def _flatten(node: Any, prefix: str, lines: list[str], depth: int) -> None:
    if len(lines) >= _MAX_LINES:
        return
    if isinstance(node, dict):
        types = _types_of(node)
        if prefix and types and not (types & _KEEP_TYPES) and "name" in node:
            # 곁가지 사물(Organization·Person·Brand 따위)은 **이름만** — 게시자·저자·브랜드가 그것이다.
            lines.append(f"{prefix}: {_scalar(node['name'])}")
            return
        for key, value in node.items():
            if key.lower() in _DROP_KEYS or (key.startswith("@") and key != "@type"):
                continue
            if key == "@type" and prefix:
                continue
            _flatten(value, f"{prefix}.{key}" if prefix else key, lines, depth + 1)
        return
    if isinstance(node, list):
        if all(not isinstance(item, (dict, list)) for item in node):
            if node:
                lines.append(f"{prefix}: {_scalar(', '.join(str(item) for item in node[:10]))}")
            return
        for index, item in enumerate(node[:5]):
            _flatten(item, f"{prefix}[{index}]", lines, depth + 1)
        if len(node) > 5:
            lines.append(f"{prefix}: …외 {len(node) - 5}개")
        return
    if node is None or node == "":
        return
    if depth > 6:
        return
    lines.append(f"{prefix}: {_scalar(node)}")


def summarize(raw: dict[str, Any] | None) -> dict[str, Any]:
    """페이지에서 거둔 것을 모델이 읽을 크기로. 쓸 것이 없으면 빈 dict."""
    if not isinstance(raw, dict):
        return {}
    items: list[dict[str, Any]] = []
    unparsed = 0
    for block in raw.get("blocks") or []:
        if isinstance(block, dict) and "__unparsed" in block:
            unparsed += 1
            continue
        for node in _nodes(block):
            types = _types_of(node)
            if not (types & _KEEP_TYPES):
                continue
            lines: list[str] = []
            _flatten(node, "", lines, 0)
            if lines:
                items.append({"type": "/".join(sorted(types)), "fields": lines})
    meta = {str(k): _scalar(v) for k, v in (raw.get("meta") or {}).items() if str(v).strip()}
    if not items and not meta:
        return {"unparsed_blocks": unparsed} if unparsed else {}
    out: dict[str, Any] = {}
    if items:
        out["items"] = items[:6]
    if meta:
        out["meta"] = meta
    if unparsed:
        out["unparsed_blocks"] = unparsed
    return out


_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
#: 사이트마다 날짜 모양이 다르다 — `2026-09-17T17:09:14+09:00` · `2026-09-17 17:09` · `2026.09.17`.
_ANY_DATE = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")


def published_date(summary: dict[str, Any]) -> str:
    """기사·글의 **게시일**(`YYYY-MM-DD`). 없으면 빈 문자열.

    ★ 2026-09-29 실사용: 「오늘자 국내 이슈나 뉴스 한번 조사해주라」에 12일 전(09-17) YTN 대담 기사 하나를 읽고 「오늘의 이슈」로
      답했다. 그 기사의 NewsArticle 에 `datePublished` 가 **이미 모델 앞에 있었는데** 아무도 날짜를 안 봤다 — 값을 한 칸으로
      뽑아 두어야 도구가 날짜를 셀 수 있다.

    기사형만 본다. 책(Book)·상품의 `datePublished` 는 출간일이지 소식의 날짜가 아니다.
    """
    for item in summary.get("items") or []:
        kind = str(item.get("type") or "")
        # 채용 공고(JobPosting)는 「posting」이지만 소식이 아니다 — 기사·블로그 글만.
        if "article" not in kind and "blogposting" not in kind and "socialmediaposting" not in kind:
            continue
        for line in item.get("fields") or []:
            key, _, value = str(line).partition(": ")
            if key == "datePublished":
                match = _ANY_DATE.search(value)
                if match:
                    year, month, day = match.groups()
                    return f"{year}-{int(month):02d}-{int(day):02d}"
    meta = (summary.get("meta") or {}).get("article:published_time") or ""
    match = _ANY_DATE.search(str(meta))
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return ""


def note_for(summary: dict[str, Any]) -> str:
    """결과에 붙일 한 줄. 구조화 데이터가 있을 때만."""
    if not summary.get("items") and not summary.get("meta"):
        return ""
    return (
        "★ structured_data 는 사이트가 검색엔진용으로 **직접 넣은 값**이다(번역·화면 꾸밈에 안 흔들린다). "
        "가격·별점·ISBN·쪽수·마감일·게시자 같은 값은 이것을 우선 근거로 쓰고, 화면 글과 다르면 둘 다 말하라."
    )
