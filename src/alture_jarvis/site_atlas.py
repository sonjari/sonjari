"""사람이 부르는 이름 → 실제 주소. **자비스가 스스로 채운다.**

왜 따로 만들었나. 이 지식은 원래 `plan.SITE_ALIASES` 에 여덟 줄로 박혀 있었고,
그 옆 주석은 "레시피가 쌓이면 거기서 읽어 오자"고 적혀 있었다. 그 묶음이 문제였다.

**주소를 아는 것**과 **그 사이트를 조작하는 법을 아는 것**은 다른 지식이다.
뒤의 것(레시피)은 사람이 써야 하지만, 앞의 것은 한 번 가 보면 저절로 알 수 있다.
둘을 한 곳에 묶어 두면 레시피를 안 쓴 사이트는 **주소조차 모르게 된다** — 그래서
2026-08-13 에 다나와가 아무 검사에도 안 걸렸다. 목록에 없었으니까.

목록에 없으면 안 걸린다는 것은, 목록에 있는 여덟 곳 말고는 **범용이 아니라는 뜻**이다.

## 어떻게 배우나 — 브랜드는 **반복되고, 하나만 가리킨다**

간 곳의 창 제목에 그 이름이 있으면 후보로 적어 둔다.

    "행복쇼핑의 시작 ! 다나와 (가격비교) - Danawa.com"  @ prod.danawa.com  → 다나와
    "쿠팡이 추천하는 무선마우스 관련 혜택과 특가"        @ www.coupang.com  → 쿠팡
    "회계 검색결과 | 교보문고"                          @ search.kyobobook.co.kr → 교보문고

제목 한 번으로는 **확정하지 않는다.** 실측(130 판)에서 그렇게 했더니 이런 게 섞였다:

    "블로그" → naver.com      (제목에 '블로그'가 들어간 페이지 한 장)
    "상담"  → naver.com      (같은 부류)
    "광양"  → jasoseol.com   (광양 채용공고 한 장)

그래서 조건 둘을 건다.

  1. **서로 다른 페이지 2 장 이상**에서 같은 도메인으로 나와야 한다.
     브랜드는 모든 페이지 제목에 박혀 있고, 우연히 섞인 낱말은 한 장에만 있다.
  2. **도메인 하나만 가리켜야 한다.** "광양"은 `gwangyang.go.kr` 과 `jobkorea.co.kr`
     양쪽에서 2 장 넘게 나왔다 — 지명이라 그렇다. 두 곳을 가리키면 그건 이름이
     아니라 **낱말**이므로, 배우지 않고 판정도 하지 않는다.

조건 2 는 나중에 뒤집힐 수 있고, 그래도 된다. 증거가 쌓여 두 번째 도메인이 2 장을
넘기면 그 이름은 조용히 '모르는 것'으로 돌아간다 — 아는 척하다 틀리는 것보다 낫다.

검색엔진 결과 화면은 제외한다. 질의어가 제목에 그대로 들어가서
("다나와 무선마우스 : 네이버 검색") 그 사이트인 척한다.

## 배운 것을 어디에 쓰나

`agent._offsite_read_check` 가 "지목한 사이트에서 읽은 게 맞나"를 볼 때 쓴다.
**모르는 이름은 판정하지 않는다.** 이게 중요하다 — 처음엔 제목으로 직접 판정하게
만들었더니 130 판 중 21 판이 걸렸고 절반이 오탐이었다. "깃허브"는 영어 제목이라
github.com 을 못 알아봤고, "광양에서"·"드라이브에서"·"이런데에서"까지 사이트로 셌다.
아는 것만 판정하면 그 오탐이 전부 사라진다. 모르면 침묵하는 쪽이 맞다 —
[[gate-must-be-backtested]] 의 교훈이다.

## 사람이 고칠 수 있다

`data/site_atlas.json` 에 그냥 쌓인다. `site_recipes` 가 사이트 지식을 파이썬이
아니라 읽을 수 있는 파일에 두기로 한 것과 같은 이유다.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# 처음부터 아는 곳. 한글 이름과 영문 주소가 안 겹쳐서 제목만으로는 영원히 못 배우는
# 곳들이라(깃허브·노션), 씨앗이 필요하다.
SEED: dict[str, str] = {
    "위시켓": "wishket.com",
    "크몽": "kmong.com",
    "프리모아": "freemoa.net",
    "사람인": "saramin.co.kr",
    "잡코리아": "jobkorea.co.kr",
    "네이버 블로그": "blog.naver.com",
    # 2026-10-08: naver.com 아래는 제목이 「NAVER」·「네이버쇼핑」처럼 붙어 있어 조여진 규칙(`_title_names_it`)으로는 배우기 어렵다.
    #   개발 PC 잡 기록에서 naver.com 아래를 실제로 연 판이 수백이다. 영어 짝은 `english.SITE_NAMES` 의 「Naver」.
    "네이버": "naver.com",
    "깃허브": "github.com",
    "노션": "notion.so",
    # ★ 2026-09-14 새 과제 검사에서 드러났다 — **YES24 가 아는 사이트 목록에 없었다.**
    #   배운 표(site_atlas.json)에 이벤트 페이지 주소 하나로만 적혀 「확실히 안다」 문턱을
    #   못 넘었다. 그래서 「YES24에서 …」 판이 전부 사이트 요구 없이 돌았다. 우리 판에서
    #   yes24.com 상세를 55판 넘게 실제로 열었다(트레이스로 확인).
    "YES24": "yes24.com",
    "예스24": "yes24.com",
    # ★ 우리 트레이스로 확인한 것만 넣는다 (2026-09-04).
    #   2026-09-03 판에서 `www.yanolja.com` → `nol.yanolja.com` 으로 실제 열렸고
    #   제목이 「NOL(야놀자) | 전세계 숙소, 항공, 레저, 공연 특가」였다.
    #   씨앗이 없어 모델이 `yyj.co.kr` 을 지어냈고 판이 통째로 헛돌았다.
    "야놀자": "yanolja.com",
    # ★ 2026-09-24 초기화한 노트북: 「다나와에서 무선키보드」를 **네이버 쇼핑**에서 찾았다. 개발 PC 는 이 가게들을 **경험으로 배워**
    #   알고 있었고(site_atlas.json), 새로 깐 PC 는 처음이라 몰랐다 — 지목한 사이트로 돌리는 장치가 이름을 몰라 작동하지 않았다.
    #   개발 PC 잡 기록에서 실제로 연 판: danawa.com 41 · coupang.com 43 · kyobobook.co.kr 35 · musinsa.com 8.
    # ★ 2026-10-03: 대표 레딧 활동 기록·반응 정리 판이 매일 돈다(22시 예약). 「레딧」을 몰라 지목 사이트 판정이 안 섰다.
    "레딧": "reddit.com",
    "다나와": "danawa.com",
    "쿠팡": "coupang.com",
    # ★ 2026-10-12 이어지는 질문을 재다 나왔다(공식 9B · 창 32K). 「그거 11번가에서는 얼마야?」에 「11번가에서 하기」가 서지 않아
    #   웹 검색 결과(쿠팡 · 제조사 · 블로그)만 읽다 「11번가 값은 못 찾았다」로 끝났고(fb 판), 「아까 그거 11번가 값도 알려줘」는
    #   계획이 비어 **찾지 않고 5초 만에** 낮에 다른 판에서 읽은 값을 기억에서 꺼내 답했다. 같은 문장의 「다나와」 · 「쿠팡」은
    #   가게로 알아봤다. 개발 PC 는 「G마켓」을 써 보며 배워 알고 있었고(site_atlas.json), 「11번가」는 그날 수십 번 들어가고도
    #   못 배웠다(그 가게 화면 제목에 가게 이름이 잘 안 나온다). 새로 깐 PC 는 둘 다 모른다 — 09-24 의 다나와와 같은 병이다.
    #   주소는 그날 가격 조사 판들이 실제로 연 것이다(www.11st.co.kr/products/… · item.gmarket.co.kr/Item?…).
    "11번가": "11st.co.kr",
    "G마켓": "gmarket.co.kr",
    "지마켓": "gmarket.co.kr",
    "교보문고": "kyobobook.co.kr",
    "무신사": "musinsa.com",
    # ★ 같은 병이 옆 가게에서 또 났다 (2026-09-05, 잡 `70fca2c4`).
    #
    #   「여기어때에 직접 들어가서 …」로 시켰더니 모델이 **`yeogiotte.com` 을
    #   지어냈다.** 진짜는 `yeogi.com` 이다 — 한글 이름과 주소가 안 겹치는,
    #   이 표가 존재하는 바로 그 이유다. 그 뒤가 더 나빴다:
    #
    #       10걸음 · 323초 · 검색엔진 3회 · **유튜브 영상을 열어 읽음**
    #       → 홈 화면에 겨우 닿고 예산 끝. 숙소는 한 곳도 못 봄.
    #
    #   씨앗은 우리 트레이스로 확인한 것만 넣는다. 이 판 8걸음에서
    #   `www.yeogi.com` 이 실제로 열렸고 제목이 「여기어때 | 해외여행, 호텔,
    #   리조트, 캠핑, 펜션, 모텔, 풀빌라, 패키지여행, 항공권 예약」이었다.
    "여기어때": "yeogi.com",
    # ★ 2026-09-26 A/B 벤치: 「대학알리미에서 취업률 지표…」 6판 중 3판이 사이트에 **아예 안 갔다** — 블로그를 읽거나
    #   `danawon.com`·`danuri.go.kr`·`alimi.go.kr` 을 지어냈다(같은 병). 이름을 몰라 지목한 사이트로 돌리는 장치가 잠들어 있었다.
    #   같은 벤치에서 실제로 연 판(r1·r2 · 전/후)의 주소가 `www.academyinfo.go.kr` 이었다.
    "대학알리미": "academyinfo.go.kr",
    # ★ 2026-10-08: 경험으로 배워 알고 있던 한글 이름 여섯.
    #   오늘(조여진 `_title_names_it`) 규칙으로는 배우기 어려우니, 진짜 사이트 이름이므로 씨앗으로 올린다.
    "알라딘": "aladin.co.kr",
    "에누리": "enuri.com",
    "오늘의집": "ohou.se",
    "올리브영": "oliveyoung.co.kr",
    "위키백과": "wikipedia.org",
    "커리어넷": "career.go.kr",
}

# 검색엔진. 여기 제목은 질의어를 되읊으므로 배움의 근거가 될 수 없다.
SEARCH_ENGINE_HOSTS = (
    "search.naver.com",
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "search.daum.net",
)

# `co.kr` 처럼 두 칸을 쓰는 꼬리. 이걸 모르면 `kyobobook.co.kr` 이 `co.kr` 이 된다.
_TWO_LABEL_TLDS = frozenset({"co", "go", "or", "ne", "pe", "re", "ac", "hs", "ms", "es"})


def registrable(host: str) -> str:
    """`search.kyobobook.co.kr` → `kyobobook.co.kr`, `prod.danawa.com` → `danawa.com`."""
    labels = [part for part in (host or "").casefold().split(".") if part]
    if len(labels) < 2:
        return ""
    if len(labels) >= 3 and labels[-1] == "kr" and labels[-2] in _TWO_LABEL_TLDS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


#: 제목을 조각으로 가르는 자리 — 「글 제목 | 사이트」·「사이트: 글」·「글 - 사이트, 설명」. 붙임표는 띄어 쓴 것만(「K-Startup」을 안 쪼갠다).
_TITLE_SEPARATORS = re.compile(r"[|·•,()\[\]<>]|\s[-–—]\s|:\s")


def _title_names_it(name: str, title: str) -> bool:
    """제목이 그 이름으로 **사이트를 부르는가.** 제목에 그 낱말이 들어 있는 것만으로는 아니다.

    ★ 2026-10-08 대표 운영 판. 「네이버 항공권에서 …」 한 판이 끝나자 **「항공권」이 사이트 이름으로 확정됐다**(→ naver.com) —
      제목 「네이버 항공권」에 그 낱말이 들어 있고 두 쪽을 봤다는 이유였다. 다음 판부터 계획에 「항공권에서 하기」가 섰다.
      그 PC 의 배운 표를 보니 확정된 20개 중 8개가 이런 것이었다: 항공권 · 카페(「네이버 카페」) · GB · Finance ·
      Seattle · Detroit · Corning · Kansas(검색 조건의 도시 이름이 목록 쪽 제목에 그대로 실린다).
      한번 배우면 그 낱말이 든 **모든 요청**에 「○○에서 하기」가 붙는다.

    사이트 이름은 제목의 **한 조각 전체**이거나 조각의 **머리**다(「알라딘: …」 · 「… | 오늘의집」 · 「올리브영 온라인몰」).
    다른 이름 뒤에 붙은 꼬리(「네이버 **항공권**」 · 「네이버 **카페**」)나 문장 속 낱말은 그 사이트의 이름이 아니다.
    """
    want = name.replace(" ", "").casefold()
    if not want:
        return False
    for segment in _TITLE_SEPARATORS.split(title or ""):
        words = segment.split()
        for take in range(1, len(words) + 1):
            head = "".join(words[:take]).casefold()
            if head == want:
                return True
            if len(head) >= len(want):
                break
    return False


def _host_carries_the_name(name: str, domain: str) -> bool:
    """영문·숫자 이름은 **주소에 그 이름이 있어야** 그 사이트의 이름이다(Amtrak → amtrak.com · GitHub → github.com).

    영어 요청의 「in Seattle」·「16GB」 같은 낱말은 제목에 흔히 실리지만 주소에는 없다 — 제목만으로는 못 가른다(「Kansas Land
    for Sale | LandWatch」는 조각의 머리다). 한글 이름은 주소와 견줄 수 없어 이 문을 지나지 않는다.
    주소에 이름이 없는 사이트(이름과 도메인이 다른 곳)는 못 배운다 — 그런 곳은 씨앗(`SEED`)으로 넣는다. 모르면 모른다고 한다.
    """
    key = re.sub(r"[^0-9a-z]", "", name.casefold())
    label = re.sub(r"[^0-9a-z]", "", (domain or "").casefold().split(".")[0])
    if not key or not label:
        return False
    # 두 글자 이하는 **같을 때만** — 「go」가 google 에, 「x」가 다른 이름 속에 우연히 들어 있는 것을 이름으로 치지 않는다.
    return key == label or (len(key) >= 3 and key in label) or (len(label) >= 3 and label in key)


# 확정에 필요한 서로 다른 페이지 수. 1 이면 우연히 섞인 낱말이 통과한다(실측).
MIN_PAGES = 2

# 이름·도메인 한 쌍에 대해 보관할 주소 개수. 세는 데 필요한 만큼만 남긴다.
_KEEP_URLS = 4

# 배우는 규칙의 판 번호. 2 = 제목의 한 조각 전체이거나 머리일 때만(2026-10-08). 표 파일에 같이 적는다.
_RULE = 2


class SiteAtlas:
    """이름↔주소를 기억한다. 없으면 **모른다고 답한다**(추측하지 않는다)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        # 이름 -> 도메인 -> 그 도메인에서 본 서로 다른 주소들
        self._seen: dict[str, dict[str, list[str]]] = {}
        if path and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                # ★ 예전 규칙(제목에 낱말이 들어 있기만 하면 됨)으로 배운 **한글 이름은 버린다** (2026-10-08). 표에는 주소만 남아
                #   있고 제목이 없어, 「항공권 → naver.com」·「카페 → naver.com」 같은 것을 다시 가려낼 근거가 없다. 진짜 이름은
                #   그 사이트를 다시 두 쪽 보면 새 규칙으로 도로 배운다. 영문 이름은 주소와 견줄 수
                #   있어 남긴다(`host_for` 가 읽을 때 가른다). 새 규칙으로 적은 표는 `rule` 로 알아본다.
                strict = int(raw.get("rule") or 1) >= _RULE
                for name, domains in (raw.get("seen") or {}).items():
                    if not strict and not str(name).isascii():
                        continue
                    self._seen[str(name)] = {
                        str(d): [str(u) for u in urls][:_KEEP_URLS]
                        for d, urls in (domains or {}).items()
                    }
            except (ValueError, OSError, AttributeError):
                # 표가 깨졌다고 자비스가 멈추면 안 된다. 씨앗만으로 계속 간다.
                self._seen = {}

    def host_for(self, name: str) -> str:
        """그 이름의 주소. **모르거나 애매하면 빈 문자열.**

        애매한 것을 빈 문자열로 돌려주는 게 핵심이다. "광양"처럼 두 도메인에 걸리는
        낱말을 하나로 찍으면, 그 뒤의 모든 판정이 그 오답 위에 선다.
        """
        key = name.strip()
        if not key:
            return ""
        seeded = SEED.get(key, "")
        if seeded:
            return seeded
        domains = self._seen.get(key) or {}
        # ★ 도메인이 둘 이상 보이면 **한 장짜리라도** 애매한 것으로 친다.
        #
        # 처음엔 "2 장 넘긴 도메인이 하나뿐이면 확정"으로 뒀는데, 130 판 재현에서
        # "광양"이 `gwangyang.go.kr` 하나만 보이던 시점에 확정돼 버렸고 그 뒤 판정
        # 셋이 그 위에서 틀렸다. 나중에 `jobkorea` 가 쌓여 애매해졌지만 **틀린 판정은
        # 이미 나간 뒤였다.** 증거가 갈릴 낌새가 보이면 그때부터 입을 다무는 게 맞다.
        if len(domains) != 1:
            return ""
        domain, urls = next(iter(domains.items()))
        # 이미 배워 둔 표에도 같은 문을 건다 — 예전 규칙으로 확정된 「Seattle → petfinder.com」 같은 것이 읽는 순간 풀린다.
        if key.isascii() and not _host_carries_the_name(key, domain):
            return ""
        return domain if len(urls) >= MIN_PAGES else ""

    def knows(self, name: str) -> bool:
        return bool(self.host_for(name))

    def known(self) -> list[dict[str, Any]]:
        """자비스가 **이름으로 아는** 사이트 전부. 씨앗과 배운 것을 함께 준다 (R5).

        이 표는 마누스에 없는 우리 자산인데 코드 안에만 있었다 — 자비스가 어디를
        아는지 사람이 볼 방법이 없었다.

        애매한 이름(두 도메인에 걸린 것)은 **뺀다.** `host_for` 가 빈 문자열을 주는
        것이 곧 "모른다"이고, 목록에서 아는 척하면 그게 그대로 오답의 출발점이 된다.
        """
        rows = [{"name": name, "host": host, "seeded": True} for name, host in SEED.items()]
        with self._lock:
            learned = sorted(self._seen)
        for name in learned:
            if name in SEED:
                continue
            host = self.host_for(name)
            if host:
                rows.append({"name": name, "host": host, "seeded": False})
        return rows

    def is_on(self, name: str, url: str) -> bool:
        """이 주소가 그 사이트인가. 모르는 이름에는 **False 가 아니라** 판정 자체를
        하면 안 되므로, 부르는 쪽에서 `knows()` 를 먼저 볼 것."""
        domain = self.host_for(name)
        if not domain:
            return False
        host = (urlparse(url).hostname or "").casefold()
        return host == domain or host.endswith("." + domain)

    def learn(self, name: str, url: str, title: str) -> str:
        """제목이 이름을 대면 **후보로** 적는다. 이번에 확정됐으면 도메인을 돌려준다.

        씨앗은 건드리지 않는다. 사람이 적어 둔 것을 지나가는 페이지가 덮으면,
        고치는 자가 스스로 망가진다.
        """
        key = name.strip()
        if not key or key in SEED:
            return ""
        host = (urlparse(url).hostname or "").casefold()
        if not host or any(engine in host for engine in SEARCH_ENGINE_HOSTS):
            return ""
        if not _title_names_it(key, title):
            return ""
        domain = registrable(host)
        if not domain:
            return ""
        if key.isascii() and not _host_carries_the_name(key, domain):
            return ""
        with self._lock:
            before = self.host_for(key)
            urls = self._seen.setdefault(key, {}).setdefault(domain, [])
            if url in urls:
                return ""
            if len(urls) < _KEEP_URLS:
                urls.append(url)
            self._save()
            after = self.host_for(key)
        # 방금 확정됐을 때만 알린다. 애매해져서 풀린 경우(after 가 빈 문자열)는
        # 알릴 것이 없다 — 조용히 '모르는 것'으로 돌아가는 게 이 표의 규칙이다.
        return after if after and after != before else ""

    def observe(self, names: list[str], steps: list[dict[str, Any]]) -> list[tuple[str, str]]:
        """한 판이 끝난 뒤 배울 것을 배운다. 배운 (이름, 주소) 목록을 돌려준다.

        **읽기만이 아니라 이동도 근거로 쓴다.** 주소를 아는 데는 본문이 필요 없고,
        다나와가 정확히 그런 경우였다 — 다나와 페이지는 열기만 했고 읽기는 딴 데서
        했다. 읽기만 봤다면 다나와 주소를 영영 못 배웠을 것이다.
        """
        learned: list[tuple[str, str]] = []
        for step in steps:
            if not step.get("ok"):
                continue
            evidence = step.get("evidence") or {}
            url = str(evidence.get("url") or "")
            title = str(evidence.get("title") or "")
            if not url or not title:
                continue
            for name in names:
                domain = self.learn(name, url, title)
                if domain:
                    learned.append((name, domain))
        return learned

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"rule": _RULE, "seen": self._seen}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # 못 적어도 이번 판은 계속 간다. 다음에 또 배우면 된다.
            pass
