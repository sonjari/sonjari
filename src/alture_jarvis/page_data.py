"""페이지가 **이미 받아 온** 데이터(JSON 응답)를 읽는다 (2026-09-18).

## 왜

화면을 그리려고 사이트가 받아 온 JSON 에는 목록·가격·마감일이 깔끔한 칸으로 들어 있다. 화면 글자는 난독화·캔버스·가상
스크롤·번역에 흔들리지만 이 응답은 안 흔들린다.

## 선 — 코드로 박는다

- **이미 받은 것만.** 페이지가 스스로 보낸 XHR/fetch 의 응답을 모아 둘 뿐, **우리가 새 요청을 보내는 코드는 없다.**
  API 를 따로 두드리는 것은 약관 위반·차단으로 이어진다.
- **같은 사이트만.** 광고·분석·다른 도메인의 응답은 버린다.
- **민감한 칸은 가린다.** 토큰·비밀번호·세션·쿠키·인증 칸과 JWT 모양 값은 「[숨김]」 — 모델에게 넘기지 않는다.
- 로그인 정보를 다른 데 쓰지 않는다(요청 헤더·쿠키는 아예 읽지 않는다).
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from .site_atlas import registrable

_SECRET_KEY = re.compile(
    r"(pass(word|wd)?|token|secret|session|cookie|auth|jwt|credential|api[_-]?key|access[_-]?key|signature|csrf|xsrf|"
    r"ssn|주민|비밀번호)",
    re.IGNORECASE,
)
_JWT = re.compile(r"^eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")
MAX_BODY_BYTES = 3 * 1024 * 1024
MAX_HITS = 25
MAX_OUT_CHARS = 6000


def same_site(page_url: str, response_url: str) -> bool:
    page_host = urlparse(page_url or "").netloc.lower().split(":")[0]
    resp_host = urlparse(response_url or "").netloc.lower().split(":")[0]
    if not page_host or not resp_host:
        return False
    return registrable(page_host) == registrable(resp_host)


def redact(node: Any, depth: int = 0) -> Any:
    if depth > 30:
        return None
    if isinstance(node, dict):
        return {k: ("[숨김]" if _SECRET_KEY.search(str(k)) else redact(v, depth + 1)) for k, v in node.items()}
    if isinstance(node, list):
        return [redact(item, depth + 1) for item in node]
    if isinstance(node, str) and _JWT.match(node):
        return "[숨김]"
    return node


def shape(node: Any, depth: int = 0) -> Any:
    """값 없이 **모양**만 — 칸 이름·목록 길이·첫 항목의 칸."""
    if depth > 3:
        return "…"
    if isinstance(node, dict):
        return {k: shape(v, depth + 1) for k, v in list(node.items())[:25]}
    if isinstance(node, list):
        return {"list": len(node), "first": shape(node[0], depth + 1)} if node else {"list": 0}
    return type(node).__name__


def _compact(obj: Any, limit: int = 20) -> Any:
    if isinstance(obj, dict):
        out = {}
        for key, value in list(obj.items())[:limit]:
            if isinstance(value, (dict, list)):
                out[key] = f"<{type(value).__name__} {len(value)}>"
            else:
                text = str(value)
                out[key] = value if len(text) <= 200 else text[:200] + "…"
        return out
    return obj


def find_hits(node: Any, terms: list[str]) -> list[dict[str, Any]]:
    """찾는 낱말이 든 **값**의 경로와, 그 값을 품은 묶음(한 칸 위)을 돌려준다."""
    wanted = [t.lower() for t in terms if t]
    hits: list[dict[str, Any]] = []

    def walk(value: Any, path: str, parent: Any) -> None:
        if len(hits) >= MAX_HITS:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key), value)
        elif isinstance(value, list):
            for index, child in enumerate(value[:500]):
                walk(child, f"{path}[{index}]", value)
        elif value is not None and any(term in str(value).lower() for term in wanted):
            hits.append({"path": path, "value": str(value)[:200], "record": _compact(parent)})

    walk(node, "", node)
    return hits


def summarize_responses(page_url: str, captured: list[dict[str, Any]], query: str = "") -> dict[str, Any]:
    """모아 둔 응답(각 항목: url·status·json)을 모델이 읽을 크기로."""
    terms = [t for t in re.split(r"[\s,]+", query or "") if len(t) >= 2][:6]
    rows: list[dict[str, Any]] = []
    used = 0
    for item in captured:
        url = str(item.get("url") or "")
        if not same_site(page_url, url):
            continue
        data = redact(item.get("json"))
        entry: dict[str, Any] = {"url": urlparse(url).path[:160], "status": item.get("status")}
        if terms:
            found = find_hits(data, terms)
            if not found:
                continue
            entry["hits"] = found
        else:
            entry["shape"] = shape(data)
        size = len(json.dumps(entry, ensure_ascii=False))
        if used + size > MAX_OUT_CHARS and rows:
            break
        rows.append(entry)
        used += size
    return {"responses": rows, "searched": terms, "considered": len(captured)}
