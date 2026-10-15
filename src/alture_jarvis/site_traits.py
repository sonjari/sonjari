"""사이트의 **성질**을 기억한다 — 두 번째부터는 첫 걸음부터 맞는 길로 (2026-09-18).

## 왜

`site_atlas` 는 이름→주소, `search_atlas` 는 검색 주소 틀을 배운다. 그런데 헤매는 걸음은 주소를 몰라서가 아니라
**그 사이트가 어떻게 생겼는지 몰라서** 나왔다:

    MS 스토어   누를 것·글자가 전부 섀도 DOM 안 → 스냅샷 0개를 16걸음 동안 다른 낱말로 다시 찾았다
    쿠팡·여기어때  헤드리스·자동화 표시에 봇 검사 → 같은 걸 다시 두드린다
    다나와·YES24  상세 값이 구조화 데이터에 깔끔히 있는데 본문을 훑었다

이런 것은 한 번 보면 **코드가 안다**(모델이 알아챌 필요가 없다). 그래서 도구가 본 사실을 사이트별로 세어 두고,
그 사이트를 다시 열 때 결과에 한 줄로 알려 준다.

## 규칙

- **본 것만** 적는다. 짐작으로 성질을 붙이지 않는다. 몇 번 봤는지·마지막으로 언제 봤는지를 같이 적는다.
- 오래된 것은 흐려진다: 90일 넘게 안 본 성질은 알려 주지 않는다(사이트는 바뀐다).
- 사람이 고칠 수 있게 `data/site_traits.json` 에 그냥 쌓는다(`site_atlas` 와 같은 이유).
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


#: 성질 → 다시 왔을 때 모델에게 할 말. `{n}` 은 본 횟수, `{detail}` 은 곁들인 값.
_ADVICE: dict[str, str] = {
    "shadow_dom": "화면이 웹 컴포넌트(섀도 DOM)다({n}번) — browser_extract·browser_snapshot 이 섀도 안까지 읽는다. 스냅샷이 비면 낱말을 바꾸지 말고 좌표로",
    "needs_coordinates": "목록이 못 읽는 칸이 있었다({n}번) — unreadable_structure 가 오면 targets 좌표로 browser_click_at",
    "structured_data": "상세 값이 structured_data 에 있다({detail}) — 가격·별점·ISBN·마감일은 그것부터 봐라",
    "bot_wall": "봇 검사가 떴다({n}번) — 뜨면 다시 두드리거나 우회하지 말고 사람에게 넘겨라",
    "login_wall": "로그인해야 보이는 화면이 있었다({n}번) — 로그인은 사람이 한다",
    "login_popup_closed": "로그인 팝업이 떴지만 닫기(X)로 닫혔다({n}번) — 로그인이 필요 없는 일이면 그대로 계속 가라. 같은 자리에서 또 뜨면 그 일엔 로그인이 필요한 것이라 사람에게 넘어간다",
    "site_search_ok": "사이트 검색칸이 됐다({n}번) — 검색 주소를 짓지 말고 browser_site_search 부터",
    "site_search_fails": "사이트 검색칸을 못 찾았다({n}번) — 같은 시도를 되풀이하지 말고 결과 목록·메뉴로 가라",
    # ★ **통한 길도 적는다** (2026-10-02 대표 운영 판). 실패만 적었더니 K-Startup 두 번째 판이 1시간 전에 본문을 읽어 낸
    #   상세 주소(`bizpbanc-ongoing.do?schM=view&pbancSn=N`)를 잊고 다른 모양(`bizpbanc-view.do?id=N`, 빈 껍데기)을 짐작해
    #   열 걸음을 헛돌았다. Perplexity 도 `/hub/pricing` 을 찾아 놓고 다음 판에서 `/pricing` 404 를 또 헤맸다.
    # ★ 2026-10-04 새벽: 예전 문장은 「이 모양에 **번호만 바꿔 열어라**」였다. 번호를 아는 판(K-Startup 목록에서 pbancSn 을
    #   받은 판)에는 맞는 말인데, 번호를 **모르는** 판에는 「번호를 지어내라」가 됐다 — 레딧 글 주소가 모양으로 쌓여 있었고,
    #   모델은 「진짜 제목 + 지어낸 글 번호」로 열어 다른 게시판의 글(성인 게시판)로 갔다(열기 1,859번 중 7번, 네 판).
    #   statista `/study/104511/…` 도 같은 뿌리로 보인다. 모양은 알려 주되, 번호는 받은 것만 넣으라고 말한다.
    "readable_url": (
        "본문이 제대로 읽혔던 주소 모양: {detail} — 같은 종류 페이지는 이런 모양이다. 번호 자리에는 목록·링크에서 **실제로 받은 번호만** 넣어라"
        "(번호를 짐작해 주소를 만들면 다른 글이 열린다). 번호를 모르면 목록에서 browser_links 로 주소를 받아라"
    ),
    "empty_url": "본문이 비어 오거나 없는 페이지였던 주소 모양: {detail} — 이 모양으로 짐작해 열지 마라",
    "js_link_route": "목록 링크가 javascript: 함수였다 — 함수→실제 주소 모양: {detail}. 상세는 그 모양에 번호만 바꿔 열어라",
}
#: 주소 모양을 담는 성질은 40자로 자르면 쓸모가 없다(`bizpbanc-ongoing.do?schM=view&pbancSn={n}` 가 41자).
_LONG_DETAIL = {"readable_url": 160, "empty_url": 160, "js_link_route": 200}
#: 서로 반대인 성질 — 최근에 더 많이 본 쪽만 말한다.
_OPPOSITES = {"site_search_ok": "site_search_fails", "site_search_fails": "site_search_ok"}
STALE_AFTER_SEC = 90 * 86400


def site_key(url: str) -> str:
    """호스트 단위(www 만 뗀다). `apps.microsoft.com` 과 `www.microsoft.com` 은 생김새가 전혀 다른 사이트다."""
    host = urlparse(url or "").netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


#: **글 하나의 주소**: 글자가 섞인 번호(레딧 `1ual8at`) 뒤에 제목 꼬리(낱말 셋 이상)가 붙었거나,
#: 숫자 번호 자리 뒤에 긴 제목 꼬리(낱말 넷 이상)가 붙은 것.
_ONE_ITEM_ADDRESS = re.compile(
    r"/(?:"
    r"(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{5,14}/[^/?]*?[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+){2,}"
    r"|\{n\}/[^/?]*?[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+){3,}"
    r")/?(?:\?|$)"
)


def is_one_item_address(pattern: str) -> bool:
    """이 주소 모양이 **글 하나의 주소**인가 — 그러면 「같은 종류 페이지의 모양」으로 기억하지도, 알려 주지도 않는다.

    ★ 2026-10-04 새벽: 레딧 글 주소(`/r/LocalLLaMA/comments/1ual8at/how_i_got_a_24x_…/`)가 「읽히는 주소 모양」으로 쌓여
      있었다. 다시 쓸 모양이 아니라 그 글 하나의 주소다. 모델은 이걸 틀로 삼아 「진짜 제목 + 지어낸 번호」를 열었고,
      모양 속의 `{n}`(네 자리 넘는 숫자를 가린 자리)까지 글자 그대로 주소에 써서 엑셀에 옮겼다.
      번호만 바꾸면 되는 진짜 모양(`…?pbancSn={n}` · `/experiences/{n}` · `/pid/{n}`)은 건드리지 않는다.
    """
    return bool(_ONE_ITEM_ADDRESS.search(str(pattern or "")))


#: **검색·목록 화면의 주소** — 경로에 search 가 있거나 검색어 인자가 있다.
_SEARCH_ADDRESS = re.compile(r"(?i)/search(?:[/?.]|$)|[?&](?:searchword|query|q|keyword|kwd|search_query|searchType)=")


def is_search_address(pattern: str) -> bool:
    """이 주소 모양이 **검색·목록 화면**인가 — 그러면 「같은 종류 페이지의 모양」으로 기억하지도, 알려 주지도 않는다.

    ★ 2026-10-04 실전 판(574826ac): 사람인에 `…/zf_user/search?searchType=search&loc_mcd={n}&…` 가 「본문이 제대로 읽혔던 주소 모양」으로
      쌓여 있었다(지역을 화면에서 고른 판이 그 목록을 읽어서). `{n}` 은 **지역 번호**다 — 모델은 그 자리에 번호를 짐작해 넣어
      (41,42,44 · 85,86,51 · 47,55,46) 세 번 열었고, 사이트가 돌려준 엉뚱한 목록을 「0건」의 근거로 삼았다. 실제로는 16건이 있었다.
      상세 주소의 번호는 목록에서 받을 수 있지만, 검색 주소의 번호는 받을 곳이 없다 — 걸러 쓰는 값은 레시피의 표가 댄다.
    """
    return bool(_SEARCH_ADDRESS.search(str(pattern or "")))


class SiteTraits:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        if path and path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                self._data = loaded if isinstance(loaded, dict) else {}
            except Exception:
                self._data = {}

    def record(self, url: str, trait: str, detail: str = "", *, now: float | None = None) -> None:
        key = site_key(url)
        if not key or trait not in _ADVICE:
            return
        if trait == "readable_url" and (is_one_item_address(detail) or is_search_address(detail)):
            return
        stamp = float(now if now is not None else time.time())
        with self._lock:
            entry = self._data.setdefault(key, {}).setdefault(trait, {"count": 0, "details": []})
            entry["count"] = int(entry.get("count") or 0) + 1
            entry["last"] = stamp
            details = [d for d in entry.get("details") or [] if d != detail]
            if detail:
                details.insert(0, detail[: _LONG_DETAIL.get(trait, 40)])
            entry["details"] = details[:5]
            self._save()

    def traits_for(self, url: str, *, now: float | None = None) -> list[dict[str, Any]]:
        key = site_key(url)
        stamp = float(now if now is not None else time.time())
        with self._lock:
            entries = dict(self._data.get(key) or {})
        fresh = {t: e for t, e in entries.items() if stamp - float(e.get("last") or 0) <= STALE_AFTER_SEC}
        out = []
        for trait, entry in fresh.items():
            opposite = _OPPOSITES.get(trait)
            if opposite in fresh and float(fresh[opposite].get("last") or 0) > float(entry.get("last") or 0):
                continue
            out.append({"trait": trait, "count": int(entry.get("count") or 0), "details": list(entry.get("details") or []),
                        "last_seen": time.strftime("%Y-%m-%d", time.localtime(float(entry.get("last") or 0)))})
        out.sort(key=lambda item: -item["count"])
        return out

    def note_for(self, url: str, *, now: float | None = None) -> str:
        traits = self.traits_for(url, now=now)
        # 같은 모양이 읽힌 적도 있으면 「비어 왔던 모양」에서 뺀다 — 한 번 늦게 그려진 것을 막힌 길로 적지 않는다.
        readable = {d for t in traits if t["trait"] == "readable_url" for d in t["details"]}
        for t in traits:
            if t["trait"] == "empty_url":
                t["details"] = [d for d in t["details"] if d not in readable]
        # 이미 쌓인 「글 하나의 주소」는 지우지 않고 **알려 주지만 않는다**(파일은 사람이 볼 수 있게 그대로 둔다).
        for t in traits:
            if t["trait"] == "readable_url":
                t["details"] = [d for d in t["details"] if not is_one_item_address(d) and not is_search_address(d)]
        traits = [t for t in traits if not (t["trait"] in {"empty_url", "readable_url"} and not t["details"])]
        if not traits:
            return ""
        parts = [
            _ADVICE[t["trait"]].format(n=t["count"], detail=", ".join(t["details"][:3]) or "?")
            for t in traits
        ]
        return f"[도구가 보낸 안내] 전에 {site_key(url)} 에서 본 것: " + " · ".join(parts)

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass
