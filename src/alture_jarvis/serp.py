"""검색 결과 화면(SERP)을 결과 목록으로 바꾼다 — 브라우저 없이.

## 왜 있나

`browser_search` 는 오랫동안 결과를 **하나도** 돌려주지 않았다. 무엇을 검색했고
차단됐는지만 알려 주고, 결과는 모델이 `browser_snapshot` 으로 직접 뒤지게 했다.
그 스냅샷이 어떤 모양인지 2026-08-06 에 실측했다(질의: "크몽 AI 챗봇 개발 견적 사례
블로그"):

```
네이버   요소 114개 · 첫 외부 결과가 j21 · j1~j20 이 전부 탭·로그인·사전·더보기
         나무위키 하나가 ref 15개를 먹는다 (목차 s-1~s-10 이 전부 별개 <a>)
빙       요소 40개 · 첫 외부 결과 없음 · http 링크 26개가 **전부** bing.com/ck/a 래퍼
         한 결과가 ref 2개 (도메인 줄 + 제목 줄) 인데 href 는 같다
```

두 가지가 동시에 무너진다:

1. **한 결과가 ref 여러 개로 흩어진다.** 그래서 "세 번째 블로그 결과"를 셀 수 없다.
2. **빙은 목적지가 아예 안 보인다.** 26개 링크의 도메인이 전부 `www.bing.com` 이라
   모델은 어디로 가는지 모른 채 골라야 한다.

세 번째가 2026-08-07 에 드러났다(질의: "제주도 3박4일 여행 경비 총정리", 네이버
블로그 탭). 결과 10건 중 1·3·5·7·9 위가 **글이 아니라 블로그 홈**이었다:

```
 1. memory and goodtime      blog.naver.com/negelowha              <- 홈
 2. 제주도 여행 3박 4일 2인용 코스   blog.naver.com/negelowha/224368785692  <- 같은 카드의 글
 3. 나의하루.                 blog.naver.com/new_yyoung             <- 홈
 4. 제주도 동쪽 3박4일 …         blog.naver.com/new_yyoung/224361780207
```

네이버 블로그 카드는 링크를 두 종류 갖는다 — 블로그 이름(홈)과 글 제목(글). 주소가
다르니 묶기 규칙에 걸리지 않고 **별개 순위**로 앉는다. 홈을 열면 그 블로그의 최신
글(질의와 무관한 글)이 뜨므로 그 순위는 통째로 버려진다. 실측에서 순위의 절반이
그렇게 날아갔고, 7위는 이미 읽은 글의 홈이라 중복이기까지 했다.

여기 있는 함수들이 그 셋을 고친다. Playwright 를 import 하지 않는 것은 일부러다 —
파싱은 브라우저 없이 검증할 수 있어야 하고, 실제로 위 실측 자료가 그대로 테스트
픽스처로 들어가 있다.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlparse

__all__ = [
    "SearchResult",
    "unwrap_redirect",
    "canonical_url",
    "is_navigation",
    "naver_blog_ref",
    "collect_results",
    "SEARCH_HOSTS",
]


# 검색엔진 자신의 화면 장치(탭·로그인·정책)로 가는 링크. 결과가 아니다.
#
# ★ `naver.com` 을 통째로 거르면 안 된다. `blog.naver.com`·`cafe.naver.com` 은
# 검색엔진이 아니라 **우리가 찾는 바로 그 내용**이다 — 실측 질의가 "블로그 사례"
# 였고 blog.naver.com 링크가 36개 잡혔다. 도메인 단위로 쓸면 그게 전부 사라지면서
# "네이버 검색은 결과가 없다"는 거짓 결론이 나온다.
#
# 그래서 호스트를 **하나씩** 적는다. 늘어나는 목록이 성가셔 보여도, 잘못 거른 결과는
# 조용히 사라져서 아무도 눈치 못 챈다.
SEARCH_HOSTS = (
    "naver.com",
    "search.naver.com",
    "nid.naver.com",
    "dict.naver.com",
    "policy.naver.com",
    "mkt.naver.com",
    "help.naver.com",
    "search.shopping.naver.com",
    "bing.com",
    "google.com",
    "duckduckgo.com",
    # 광고 중계. 결과처럼 생겼지만 내용이 없고, 열면 대개 그냥 실패한다.
    #
    # 2026-08-09 실측: 외주 공고를 찾는데 3위 결과가 `ader.naver.com/v1/...` 이었고
    # `browser_open_result(rank=3)` 이 ERR_HTTP_RESPONSE_CODE_FAILURE 로 죽었다.
    # 실패 자체보다 나쁜 것은 그 다음이다 — 모델은 "이 방향은 막혔다"로 읽고
    # 사이트 진입을 포기한 뒤 검색으로 되돌아갔다. 광고 한 줄이 조사 전체를 틀었다.
    "ader.naver.com",
    "adcr.naver.com",
    # 2026-10-12: 네이버 검색 1번 결과가 「네이버 광고주센터: 검색광고 소개」(ads.naver.com/sa)였다 — 광고 묶음 옆의
    #   「광고 안내」 링크다. 4B 판이 그것을 열어 읽고 「1번이 광고 페이지였다」로 멈췄다. 같은 날 11번가 · G마켓에 이어
    #   우리 도구가 광고를 순위에 넣은 세 번째다.
    "ads.naver.com",
    "adcreative.naver.com",
    "googleadservices.com",
    "doubleclick.net",
)

# 이쪽은 **도메인 전체**를 걸러도 되는 곳 — 내용이 실리지 않는 검색엔진 인프라다.
# 네이버가 여기 없는 것이 요점이다(블로그·카페·뉴스가 전부 하위 도메인이라서).
_CHROME_DOMAINS = ("bing.com", "google.com", "duckduckgo.com", "msn.com")

# 검색 결과를 감싸는 껍데기를 벗기는 규칙. 값은 "이 파라미터에 진짜 주소가 있다".
#
# 빙은 base64 인데 앞에 두 글자(`a1`)를 덧붙인다 — 그대로 디코드하면 깨진다.
# 이걸 모르고 보면 "빙은 원본 URL 을 안 준다"는 잘못된 결론이 나온다.
_REDIRECT_PARAMS = ("u", "q", "url", "target", "link")

_NAV_WORDS = frozenset(
    {
        "통합", "블로그", "카페", "클립", "이미지", "지식in", "지식iN", "동영상",
        "쇼핑", "뉴스", "어학사전", "사전", "지도", "더보기", "더 보기", "공유",
        "로그인", "로그아웃", "검색", "전체", "옵션 메뉴 열기", "한글 입력기",
        "메뉴 영역으로 바로가기", "본문 영역으로 바로가기", "콘텐츠로 건너뛰기",
        "접근성 피드백", "서비스 더보기", "이전", "다음", "다음 페이지", "이전 페이지",
        "개인 정보 보호", "사용 약관", "고객센터", "설정", "도움말",
        "next", "previous", "sign in", "settings", "help", "privacy", "terms",
        "skip to content", "images", "videos", "maps", "news", "shopping", "all",
    }
)

# "1페이지" "2페이지" "Page 3" 같은 쪽 번호.
_PAGER = re.compile(r"^\s*(?:page\s*)?\d+\s*(?:페이지|쪽)?\s*$", re.IGNORECASE)

# 네이버가 링크 이름 끝에 붙이는 접근성 문구. 남겨 두면 제목마다 따라다닌다.
_A11Y_SUFFIX = re.compile(r"\s*(새 창 열림|새창열림|opens in a new (?:tab|window))\s*$", re.IGNORECASE)

# 제목이 아니라 출처를 표시하는 줄. 두 가지 꼴이 있고 **둘 다** 잡아야 한다:
#
#   kmong.com                 빙 — 도메인만
#   크몽 kmong.com›gig         네이버 — 브랜드명 + 도메인 + 경로 (도메인이 가운데 온다)
#
# 앞을 `^` 로 묶으면 네이버 꼴을 통째로 놓쳐 브레드크럼이 제목 자리에 앉는다.
# `›`(U+203A)는 네이버의 경로 구분자라 진짜 제목에는 거의 안 나온다.
_SOURCE_LINE = re.compile(r"(?:^|\s)[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:\s*›|\s*$)", re.IGNORECASE)

# 네이버 블로그 카드에서 "블로그 홈"과 "글"을 가르는 데 쓰는 것들.
#
# `blog.me` 같은 옛 별칭은 넣지 않았다 — 실제로는 blog.naver.com 으로 리다이렉트되고,
# 확인 못 한 모양을 넣으면 글을 홈으로 잘못 읽어 결과가 사라질 수 있다.
_NAVER_BLOG_HOSTS = ("blog.naver.com", "m.blog.naver.com")
# 아이디에는 점이 없다. 그래서 `PostView.naver` 같은 엔드포인트가 아이디로 오인되지 않는다.
_BLOG_ID = re.compile(r"^[A-Za-z0-9_-]{2,40}$")
_LOG_NO = re.compile(r"^\d{6,}$")
_POST_ENDPOINTS = ("postview.naver", "postview.nhn")
_HOME_ENDPOINTS = (
    "postlist.naver",
    "postlist.nhn",
    "prologuelist.naver",
    "prologuelist.nhn",
    "blogmain.naver",
)

# 추적용 파라미터. 같은 글이 다른 주소로 보이게 만들어 중복 제거를 무력화한다.
_TRACKING = re.compile(
    r"^(?:utm_|fbclid|gclid|igshid|spm|ref_?src|from|sm|ssc|dtm_|trk|"
    r"nso|where|query|sort|photo|api|_?src)",
    re.IGNORECASE,
)


def _is_source_line(text: str) -> bool:
    """제목이 아니라 출처를 가리키는 줄인가.

    `.match()` 가 아니라 `.search()` 여야 한다 — `크몽 kmong.com›gig` 은 도메인이
    **가운데** 오므로 처음에 붙는 검사로는 영원히 안 잡힌다. 그 상태에서는
    브레드크럼이 제목 자리에 그대로 앉는다.
    """
    return bool(_SOURCE_LINE.search(text or ""))


@dataclass
class SearchResult:
    """검색 결과 한 건 — 흩어진 ref 여러 개를 하나로 묶은 것."""

    rank: int
    title: str
    url: str
    domain: str
    snippet: str = ""
    ref: str = ""
    section: str = ""
    refs: list[str] = field(default_factory=list)
    visited: bool = False

    def as_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "rank": self.rank,
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "ref": self.ref,
        }
        if self.snippet:
            item["snippet"] = self.snippet
        if self.section:
            item["section"] = self.section
        # 한 결과가 ref 몇 개로 흩어져 있었는지. 묶기가 제대로 됐는지 확인하는 증거이자,
        # 대표 ref 를 눌렀는데 엉뚱한 데로 가면 다른 것을 시도할 근거가 된다.
        if len(self.refs) > 1:
            item["refs"] = self.refs
        if self.visited:
            item["visited"] = True
        return item


def _b64_decode(value: str) -> str:
    """빙의 `u=` 값을 푼다. 앞 두 글자는 버전 표식이라 벗겨야 한다."""
    raw = value
    # `a1`, `a2` … 형태의 접두. 이걸 그대로 두면 4바이트 정렬이 깨져 전부 실패한다.
    if len(raw) > 2 and raw[0] == "a" and raw[1].isdigit():
        raw = raw[2:]
    raw = raw.replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(raw).decode("utf-8", "ignore")
    except (binascii.Error, ValueError):
        return ""
    return decoded if decoded.startswith(("http://", "https://")) else ""


def unwrap_redirect(url: str, *, depth: int = 3) -> str:
    """리다이렉트 껍데기를 벗겨 진짜 목적지를 돌려준다.

    빙은 **모든** 결과를 `bing.com/ck/a?…&u=a1<base64>` 로 감싼다. 실측에서 http
    링크 26개의 도메인이 전부 `www.bing.com` 이었던 이유가 이것이다. 벗기지 않으면
    모델은 어느 사이트로 가는지 모르는 채 순위만 보고 골라야 한다.

    껍데기가 겹칠 수 있어 `depth` 만큼 되풀이한다. 못 벗기면 원래 주소를 그대로 준다
    (조용히 빈 값을 주면 결과가 통째로 사라진다).
    """
    current = (url or "").strip()
    for _ in range(max(1, depth)):
        parsed = urlparse(current)
        if parsed.scheme not in {"http", "https"}:
            return current
        params = parse_qs(parsed.query)
        target = ""
        for key in _REDIRECT_PARAMS:
            values = params.get(key)
            if not values:
                continue
            candidate = values[0]
            if candidate.startswith(("http://", "https://")):
                target = candidate
                break
            unquoted = unquote(candidate)
            if unquoted.startswith(("http://", "https://")):
                target = unquoted
                break
            decoded = _b64_decode(candidate)
            if decoded:
                target = decoded
                break
        if not target or target == current:
            return current
        current = target
    return current


def canonical_url(url: str) -> str:
    """같은 글을 같은 주소로 만든다 — 묶기의 기준.

    조각(`#s-3`)을 버리는 것이 핵심이다. 실측에서 나무위키 하나가 ref 15개를 먹은
    것은 목차 링크가 전부 `#s-1` … `#s-10` 으로 **다른 주소**였기 때문이다. 조각만
    떼면 15개가 한 결과로 합쳐진다.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    query = "&".join(
        part
        for part in sorted(parsed.query.split("&"))
        if part and not _TRACKING.match(part.split("=", 1)[0])
    )
    path = parsed.path.rstrip("/") or "/"
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{parsed.scheme}://{host}{path}" + (f"?{query}" if query else "")


def _host_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


#: 검색엔진이 결과를 감싸 내보내는 길. 벗길 수 있는 것은 `unwrap_redirect` 가 벗긴다 — 여기 남는 것은 **못 벗기는** 것이다.
_OUTBOUND_PATHS = frozenset({"/goto", "/url"})
#: 링크의 글자에 적힌 「가는 곳」 — 구글 결과 한 줄은 「제목 사이트이름 https://huggingface.co › blog」 꼴이다.
_SHOWN_ADDRESS = re.compile(r"https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def opaque_outbound(url: str) -> bool:
    """검색엔진이 **목적지를 숨긴 채** 내보내는 링크인가.

    ★ 2026-10-05 가짜 홈(갓 만든 크롬 프로필) 실측: 구글이 로그인 안 된 프로필에는 결과 링크를 전부
      `https://www.google.com/goto?url=CAES…`(암호화된 값)로 준다 — 화면에 직접 링크가 **0개**였다. 이 주소는 구글 것이라
      「화면 장치」로 걸러졌고, 결과가 떠 있는데 `result_count: 0` 이 다섯 번 나갔다(9B 허깅페이스 판 ef1e8e25). 운영 크롬은
      구글에 로그인돼 있어 실제 주소가 그대로 와서 안 보였다 — **새로 설치한 사람은 전원 이 조건이다.**
      열어 보면 구글이 실제 페이지로 바로 넘긴다(세 개 0.7~2.1초).
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or (parsed.path.rstrip("/") or "/") not in _OUTBOUND_PATHS:
        return False
    host = _host_of(url)
    if not any(host == item or host.endswith("." + item) for item in _CHROME_DOMAINS):
        return False
    params = parse_qs(parsed.query)
    return any(params.get(key) for key in ("url", "q"))


def shown_host(name: str) -> str:
    """링크의 글자에 적힌 가는 곳의 호스트. 없으면 빈 글자."""
    found = _SHOWN_ADDRESS.search(name or "")
    if not found:
        return ""
    host = found.group(1).lower()
    return host[4:] if host.startswith("www.") else host


def is_navigation(name: str, url: str, *, engine_hosts: Iterable[str] = SEARCH_HOSTS) -> bool:
    """결과가 아니라 화면 장치인가.

    실측에서 네이버 스냅샷의 앞 20개(j1~j20)가 전부 여기 걸린다 — 탭 10개, 로그인,
    사전, 더보기, 바로가기. 모델은 그걸 다 읽고 나서야 첫 결과에 닿았다.
    """
    label = _A11Y_SUFFIX.sub("", (name or "").strip())
    if not url or url.startswith(("#", "javascript:", "mailto:", "tel:")):
        return True
    if not url.startswith(("http://", "https://")):
        # 상대 주소로 남은 것은 검색엔진 자신의 탭 전환이다(`?ssc=tab.blog.all` 등).
        return True
    if _PAGER.match(label):
        return True
    if label.lower() in _NAV_WORDS or label in _NAV_WORDS:
        return True
    if opaque_outbound(url):
        # 목적지를 숨긴 나가는 링크 — **어디로 가는지 글자로 보여 주는 것**만 결과다. AI 요약의 출처 칩(「Hugging Face」)도 같은
        # 꼴인데 가는 곳이 안 적혀 있고, 같은 글이 아래 정식 결과에 주소와 함께 다시 나온다.
        return not shown_host(label)
    host = _host_of(url)
    # 정확히 일치하는 것만 — 하위 도메인까지 쓸면 blog.naver.com 이 같이 날아간다.
    if host in set(engine_hosts):
        return True
    # 내용이 실리지 않는 검색 인프라만 도메인 전체로 거른다.
    return any(host == item or host.endswith("." + item) for item in _CHROME_DOMAINS)


def naver_blog_ref(url: str) -> tuple[str, str]:
    """네이버 블로그 주소를 `(블로그ID, 'post'|'home')` 으로 가른다.

    네이버 블로그가 아니면 `("", "")` — 그 경우 아무 규칙도 적용되지 않는다.

    가르는 기준은 **경로 모양 하나뿐**이고 일부러 좁게 잡았다:

        blog.naver.com/negelowha/224368785692     글  (아이디 + 숫자 logNo)
        blog.naver.com/PostView.naver?…&logNo=…   글  (구형 주소)
        blog.naver.com/negelowha                  홈  (아이디 하나뿐)
        blog.naver.com/PostList.naver?blogId=…    홈

    모르는 모양은 `("", "")` 로 돌려보내 **평소대로 결과로 남긴다.** 이 파일 첫머리에
    적힌 이유 그대로다 — 잘못 거른 결과는 조용히 사라져 아무도 눈치 못 챈다. 글을
    홈으로 잘못 읽으면 진짜 결과가 병합돼 없어지므로, 애매하면 손대지 않는 쪽이 맞다.
    """
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _NAVER_BLOG_HOSTS:
        return "", ""
    params = parse_qs(parsed.query)
    query_id = (params.get("blogId") or [""])[0].strip()
    segments = [segment for segment in parsed.path.split("/") if segment]
    endpoint = segments[-1].lower() if segments else ""

    if endpoint in _POST_ENDPOINTS:
        # logNo 가 없는 PostView 는 어느 글인지 모르는 주소다 — 건드리지 않는다.
        return (query_id, "post") if query_id and params.get("logNo") else ("", "")
    if endpoint in _HOME_ENDPOINTS:
        return (query_id, "home") if query_id else ("", "")
    if len(segments) >= 2 and _BLOG_ID.match(segments[0]) and _LOG_NO.match(segments[1]):
        return segments[0], "post"
    if len(segments) == 1 and _BLOG_ID.match(segments[0]):
        return segments[0], "home"
    return "", ""


def _merge_naver_blog_homes(
    seen: dict[str, "SearchResult"],
    order: list[str],
    kinds: dict[str, tuple[str, str]],
) -> list[str]:
    """같은 블로그의 글이 목록에 있으면, 그 블로그 홈은 글에 합치고 순위에서 뺀다.

    홈은 화면에서 글보다 **먼저** 나오므로(카드가 블로그 이름을 위에 그린다) 홈을
    빼면 글이 그 자리를 물려받는다 — 카드 순서는 그대로 유지된다.

    ★ 반드시 `limit` 으로 자르기 **전에** 해야 한다. 자른 뒤에 합치면 10건을 달라고
    했을 때 실제로는 5건만 남는다 — 낭비가 사라지는 게 아니라 목록이 짧아진다.

    글이 없는 홈은 남긴다. 검색이 정말로 블로그 자체를 결과로 준 경우이고, 그것까지
    지우면 "결과가 없다"는 거짓 결론으로 이어진다.
    """
    first_post: dict[str, str] = {}
    for key in order:
        blog_id, kind = kinds.get(key, ("", ""))
        if kind == "post" and blog_id and blog_id not in first_post:
            first_post[blog_id] = key

    kept: list[str] = []
    for key in order:
        blog_id, kind = kinds.get(key, ("", ""))
        target = first_post.get(blog_id, "") if kind == "home" else ""
        if not target or target == key:
            kept.append(key)
            continue
        post = seen[target]
        # 홈 링크의 ref 도 글 쪽에 남긴다 — 대표 ref 가 안 먹힐 때 눌러 볼 자리다.
        for ref in seen[key].refs:
            if ref not in post.refs:
                post.refs.append(ref)
        del seen[key]
    return kept


def _better_title(current: str, candidate: str) -> bool:
    """어느 쪽이 제목다운가.

    출처 줄("kmong.com", "namu.wiki›크몽")은 문장에 진다. 둘 다 문장이면 **먼저 나온
    쪽**이 제목이다 — 길이로 고르면 안 된다. 실측에서 크몽 결과는 이 순서였다:

        j36  크몽 kmong.com›gig                              <- 출처
        j38  쓰던 웹 앱 서비스에 GPT AI 기능 연동 개발          <- 제목
        j39  두번째 요청이었는데, 이번에도 요청사항에 딱 맞게…    <- 발췌(더 길다)

    긴 쪽을 제목으로 삼으면 리뷰 발췌가 제목 자리에 온다. 검색 화면은 제목을 먼저,
    발췌를 나중에 그리므로 순서가 길이보다 믿을 만하다.
    """
    if not current:
        return True
    # 이미 문장을 잡았으면 바꾸지 않는다 — 뒤에 오는 것은 발췌다.
    if not _is_source_line(current):
        return False
    return not _is_source_line(candidate)


def collect_results(
    rows: Iterable[dict[str, Any]],
    *,
    limit: int = 20,
    visited: Iterable[str] = (),
) -> list[SearchResult]:
    """스냅샷 행들을 결과 목록으로. 흩어진 ref 를 묶고, 껍데기를 벗기고, 장치를 뺀다.

    `rows` 는 `_frame_elements` 가 내는 모양 그대로다: `name`·`href`·`ref`.
    순서가 화면 순서이므로 그대로 순위가 된다 — 정렬하지 않는다.
    """
    seen: dict[str, SearchResult] = {}
    order: list[str] = []
    kinds: dict[str, tuple[str, str]] = {}
    visited_keys = {canonical_url(item) for item in visited}

    for row in rows:
        name = _A11Y_SUFFIX.sub("", str(row.get("name") or "").strip())
        # ★ 반드시 **벗긴 뒤에** 판정한다. 빙은 결과도 탭도 전부 `bing.com/ck/a` 라,
        # 벗기기 전에 호스트로 거르면 **결과가 하나도 안 남는다**(실측에서 0개였다).
        # 벗기고 나면 탭은 bing.com/images 로, 결과는 kmong.com 으로 갈린다.
        url = unwrap_redirect(str(row.get("href") or ""))
        if is_navigation(name, url):
            continue
        key = canonical_url(url)
        if not key:
            continue

        existing = seen.get(key)
        if existing is None:
            result = SearchResult(
                rank=0,
                title=name,
                url=url,
                # 목적지를 숨긴 링크는 주소가 검색엔진 것이다 — 사람에게 보이는 「가는 곳」을 적는다.
                domain=(shown_host(name) if opaque_outbound(url) else "") or _host_of(url),
                ref=str(row.get("ref") or ""),
                section=str(row.get("section") or ""),
                refs=[str(row.get("ref"))] if row.get("ref") else [],
                visited=key in visited_keys,
            )
            seen[key] = result
            order.append(key)
            kinds[key] = naver_blog_ref(url)
            continue

        ref = str(row.get("ref") or "")
        if ref and ref not in existing.refs:
            existing.refs.append(ref)
        if not name:
            continue
        if _better_title(existing.title, name):
            # 밀려난 제목은 버리지 않는다 — 그게 대개 발췌문이다.
            if existing.title and not _is_source_line(existing.title):
                if len(existing.title) > len(existing.snippet):
                    existing.snippet = existing.title
            existing.title = name
        elif len(name) > len(existing.snippet) and not _is_source_line(name):
            existing.snippet = name

    results: list[SearchResult] = []
    for key in _merge_naver_blog_homes(seen, order, kinds):
        item = seen[key]
        # 제목이 출처 줄뿐이면 그 자리에 도메인을 남긴다. 빈 제목보다는 낫다.
        if not item.title:
            item.title = item.domain
        item.rank = len(results) + 1
        results.append(item)
        if len(results) >= max(1, limit):
            break
    return results
