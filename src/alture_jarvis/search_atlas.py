"""사이트가 **검색 결과를 준 주소**를 배워 두고, 다음엔 그리로 바로 간다.

## 왜 (2026-09-06 실측)

자비스는 사이트 안에서 찾을 때 `browser_site_search` 로 **검색칸을 찾아 타이핑**한다.
그게 안 될 때가 있다:

    검색칸을 못 찾음            31 건 · 5 종   (위시켓 22 건 — 걸음 2 위 사이트다)
    모델이 손으로 주소 조립     57 건 · 11 종  (이 층이 그대로 대체한다)
    ───────────────────────────────────────
    합계                        88 건 · 12 종

손으로 조립하면 오타가 난다. 이 저장소가 실측한 예: 다나와에서 퍼센트 인코딩을
한 글자 틀려 「무섧마우스」로 검색했고, **404 가 아니라 빈 목록**으로 조용히 왔다.

## 무엇을 배우나 — 「API」가 아니라 「답을 준 주소」다

klura 같은 프로젝트는 **네트워크를 통째로 캡처해 토큰까지 재생**한다. 우리는 안
그런다. 이유가 셋이고 전부 실측이다:

    ① 우리 상위 사이트는 **서버 렌더**다. 크몽 검색은 요청 58 건이 전부 JS 청크고
       데이터 API 호출이 **0 건**이었다. 때릴 API 자체가 없다 — 주소가 곧 응답이다.
    ② 토큰을 저장하면 사용자 실계정 세션이 디스크에 남는다. 안 한다.
    ③ 브라우저 없이 직접 쏘면 봇 검사에 **더** 걸린다. 여기어때에서 Cloudflare
       챌린지를 봤고, 반복 접근에 본문이 140 자 빈 껍데기로 왔다.

그래서 배우는 것은 **그 진짜 크롬이 실제로 열어서 결과가 나온 주소** 하나다.
재생도 같은 크롬으로 한다. 봇 검사를 그대로 통과하고, 토큰을 안 만진다.

## 안전 쪽 원칙

- **검색어가 주소에 있을 때만** 배운다. 없으면 그 주소는 검색을 안 담고 있다.
- 검색엔진은 안 배운다 — 거기 주소는 그 사이트의 것이 아니다.
- 추적·인증 인자는 버린다(`utm_*`·토큰·세션).
- 재생해서 **결과가 안 나오면 원래 길로 돌아간다.** 이 층은 거들 뿐이다.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

#: 검색어를 담는 인자 이름. 여기 없는 이름이어도 **값이 검색어와 같으면** 배운다.
_QUERY_KEYS = (
    "q", "query", "keyword", "kw", "stext", "searchword", "search_word",
    "term", "k1", "searchKeyword", "search",
)

#: 배우면 안 되는 인자. 추적·인증·세션.
_DROP = re.compile(
    r"^(utm_|_ga|gclid|fbclid|ref$|referer|referrer|token|access|auth|sid$|session|"
    r"csrf|nonce|sig$|signature|timestamp|_rsc|trk|from$)",
    re.IGNORECASE,
)

#: 검색엔진. 여기 주소는 그 사이트의 검색이 아니다.
_ENGINES = (
    "search.naver.com", "google.com", "bing.com", "duckduckgo.com",
    "search.daum.net", "search.yahoo.com",
)

#: 한 사이트에서 이만큼 봐야 믿는다. 한 번은 우연일 수 있다.
CONFIRM_AT = 2
#: 배운 주소가 이만큼 결과를 줘야 성공으로 친다.
MIN_ROWS = 3
#: 표가 무한정 자라지 않게.
_MAX_HOSTS = 300


def _host_of(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_search_engine(url: str) -> bool:
    host = _host_of(url)
    return bool(host) and any(engine in host for engine in _ENGINES)


def template_from(url: str, query: str) -> str:
    """이 주소가 **그 검색어로 만든 것**이면 `{query}` 자리를 뚫은 틀. 아니면 빈 문자열.

    검색어가 주소에 실제로 들어 있어야 한다 — 그래야 다음 검색어로 바꿔 쓸 수 있다.
    """
    query = (query or "").strip()
    if not url or not query or is_search_engine(url):
        return ""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http") or not parsed.query:
        return ""
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not pairs:
        return ""
    kept: list[tuple[str, str]] = []
    hit = False
    for name, value in pairs:
        if _DROP.search(name):
            continue
        if value.strip() == query:
            # 이름이 무엇이든 **값이 검색어면** 그 자리가 검색어 자리다.
            kept.append((name, "\x00QUERY\x00"))
            hit = True
            continue
        kept.append((name, value))
    if not hit:
        return ""
    rebuilt = urlunparse(parsed._replace(query=urlencode(kept, doseq=False), fragment=""))
    # `urlencode` 가 자리표시자를 인코딩하므로 되돌린다.
    return rebuilt.replace(quote("\x00QUERY\x00", safe=""), "{query}").replace(
        "%00QUERY%00", "{query}"
    )


def fill(template: str, query: str) -> str:
    """틀에 검색어를 넣는다. 인코딩은 여기서 한 번만 한다 — 손으로 쓰면 틀린다."""
    if not template or "{query}" not in template:
        return ""
    return template.replace("{query}", quote(str(query or "").strip(), safe=""))


class SearchAtlas:
    """호스트 → 검색 주소 틀. 파일 하나로 산다.

    `data/` 에 두는 이유: `recipes/` 는 편집본(E:)에서 실행본(C:)으로 **덮어써진다**
    (`sync_to_runtime.ps1` 는 data·outputs·.venv 만 지킨다). 배운 것을 거기 두면
    배포 한 번에 사라진다.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        rows = raw.get("hosts") if isinstance(raw, dict) else None
        if isinstance(rows, dict):
            self._rows = {str(k): v for k, v in rows.items() if isinstance(v, dict)}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"hosts": self._rows}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            # 못 적어도 판은 계속 간다. 다음 판에서 다시 배우면 된다.
            pass

    # ── 배우기 ──────────────────────────────────────────────────────────
    def learn(self, url: str, query: str, rows: int) -> str:
        """결과가 나온 주소를 기록한다. 배운 틀(또는 빈 문자열)을 돌려준다.

        같은 틀을 다시 보면 `seen` 이 오른다. **다른 틀이 오면 새것으로 갈아탄다** —
        사이트가 주소 모양을 바꾼 것이므로 옛것을 붙들 이유가 없다.
        """
        if rows < MIN_ROWS:
            return ""
        template = template_from(url, query)
        if not template:
            return ""
        host = _host_of(url)
        if not host:
            return ""
        with self._lock:
            row = self._rows.get(host)
            if row and row.get("template") == template:
                row["seen"] = int(row.get("seen") or 1) + 1
                row["rows"] = int(rows)
                row["at"] = int(time.time())
            else:
                self._rows[host] = {
                    "template": template,
                    "seen": 1,
                    "rows": int(rows),
                    "at": int(time.time()),
                }
            if len(self._rows) > _MAX_HOSTS:
                oldest = sorted(self._rows.items(), key=lambda kv: kv[1].get("at") or 0)
                for key, _ in oldest[: len(self._rows) - _MAX_HOSTS]:
                    self._rows.pop(key, None)
            self._save()
        return template

    # ── 쓰기 ────────────────────────────────────────────────────────────
    def url_for(self, page_url: str, query: str, *, confirmed_only: bool = True) -> str:
        """이 사이트에서 이 검색어로 갈 주소. 모르면 빈 문자열."""
        host = _host_of(page_url)
        if not host or not str(query or "").strip():
            return ""
        with self._lock:
            row = self._rows.get(host)
        if not row:
            return ""
        if confirmed_only and int(row.get("seen") or 0) < CONFIRM_AT:
            return ""
        return fill(str(row.get("template") or ""), query)

    def remember_search_page(self, page_url: str) -> None:
        """검색칸이 **실제로 있던 페이지 주소**를 호스트별로 기억한다.

        ## 왜 틀(template)과 따로 두나 (2026-09-09)

        위시켓은 **홈에 검색칸이 없고 `/project/` 에만 있다.** 실측:

            https://www.wishket.com/          -> site_search_box_not_found
            https://www.wishket.com/project/  -> 성공

        자비스는 사이트 이름만 알고 들어가면 홈으로 간다. 그래서 위시켓 4 판이
        **4 판 다** 검색에서 한 번 실패하고 손으로 더듬어 회복했다 — 그 회복이
        시간 편차(66~276초)의 제일 큰 상수였다.

        `template` 은 **주소로 검색이 되는 사이트**(교보·쿠팡·YES24)를 위한 것이고,
        여기는 **칸에 쳐 넣어야 하는 사이트**를 위한 것이다. 둘은 다른 사실이라
        한 칸에 섞으면 한쪽이 다른 쪽을 지운다.
        """
        host = _host_of(page_url)
        url = str(page_url or "").strip()
        if not host or not url:
            return
        with self._lock:
            row = self._rows.setdefault(host, {})
            if row.get("search_page") == url:
                return
            row["search_page"] = url
            self._save()

    def search_page_for(self, page_url: str) -> str:
        """이 사이트에서 **검색칸이 있던** 주소. 모르면 빈 문자열."""
        with self._lock:
            row = self._rows.get(_host_of(page_url)) or {}
        return str(row.get("search_page") or "")

    def forget(self, page_url: str) -> bool:
        """배운 것이 안 먹으면 지운다. 다음 판에서 다시 배운다."""
        host = _host_of(page_url)
        with self._lock:
            gone = self._rows.pop(host, None) is not None
            if gone:
                self._save()
        return gone

    def known(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._rows.items()}
