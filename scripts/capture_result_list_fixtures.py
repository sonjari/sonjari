"""결과 목록 판정기의 **고정 표본**을 뜬다 — 살아있는 사이트를 얼려서 시험대에 올린다.

## 왜 필요한가 (2026-08-12 실측)

하루에 되돌린 것이 셋이다. 묶음 상한(당근 12건 → 0건) · 자기 페이지를 앞 두 칸으로
판정(당근 매물 60개 증발) · 카드 대표 링크(사람인은 깨끗해졌는데 교보·다나와가 망가짐).
셋 다 **한 곳만 보고 고쳐서** 딴 데가 깨진 것이다.

"세 사이트를 함께 재라"는 규율은 지켜지지 않는다. 판정 하나 바꿀 때마다 살아있는
브라우저로 살아있는 사이트를 여덟 곳 치려면 십수 분이 걸리고, 그 사이 사이트가 바뀌면
어제와 오늘을 비교할 수도 없다. **그래서 규율이 아니라 도구로 만든다.**

## 어떻게 얼리나

판정기(`_RESULT_LIST_JS`)가 실제로 읽는 것은 넷이다:

    a[href]                 링크와 그 목적지
    innerText               글자 (길이가 주된 신호다)
    getBoundingClientRect   보이는가
    getComputedStyle        보이는가

뒤의 셋은 **CSS 가 있어야** 제 값이 나온다. 그래서 HTML 만 떠서는 안 되고,
스타일시트를 본문 안에 통째로 녹여 넣는다(`<link>` → `<style>`). 스크립트는 지운다 —
재생할 때 어차피 안 돌리고, 페이지 무게의 절반이 그것이다.

주소는 **원래 주소 그대로** 재생한다(재생 쪽에서 route 로 가로챈다). `location.href` 를
쓰는 자기 페이지 판정이 살아 있어야 하기 때문이다.

## 쓰는 법

    python -u scripts/capture_result_list_fixtures.py              # 전부
    python -u scripts/capture_result_list_fixtures.py danawa kyobo # 골라서
    python -u scripts/capture_result_list_fixtures.py --repeat 5 kyobo   # 흔들림 조사용

`--repeat` 는 같은 화면을 여러 번 떠서 **DOM 이 판마다 다른지**를 본다.
교보문고가 판마다 진짜 책 ↔ "바로펀딩" 으로 갈리는데, 원인이 페이지인지 판정기인지
이것으로 갈린다.

캡처는 살아있는 사이트를 친다 — 읽기만 하고 아무것도 제출하지 않는다.
"""

from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import sys
import time
from typing import Any

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "result_lists"

# 인수인계서에 실측으로 적힌 그 화면들. 무작위 사이트를 얼리면 무작위 시험이 된다.
#
# `url` 은 검색 결과 주소를 **직타**하는 길이다. 빠르지만 리퍼러도 쿠키도 없어서
# 첫 요청부터 티가 난다. `host`·`google`·`query` 가 있으면 **사람이 가는 길**로 간다:
#
#     구글 홈 → 검색칸에 사이트 이름을 쳐서 들어가기 → 그 사이트 검색칸에 검색어
#
# 운영 자비스가 실제로 가는 길이 이쪽이라(`search → open_result → browser_site_search`),
# 이 길로 떠야 표본이 운영이 보는 화면과 같아진다. 봇 검사가 센 곳은 이 길뿐이다.
SITES: dict[str, dict[str, str]] = {
    "danawa": {
        "url": "https://search.danawa.com/dsearch.php?query=무선마우스",
        "host": "danawa.com",
        "google": "다나와",
        "query": "무선마우스",
        "why": "카드 하나가 링크를 여럿 낸다 — 부속 링크가 목록을 이겼던 곳",
    },
    "kyobo": {
        "url": "https://search.kyobobook.co.kr/search?keyword=회계",
        "host": "kyobobook.co.kr",
        "google": "교보문고",
        "query": "회계",
        "why": "판마다 1번이 갈린다(진짜 책 ↔ 바로펀딩) — 원인 미상",
    },
    "daangn": {
        "url": "https://www.daangn.com/kr/buy-sell/s/?search=책상",
        "host": "daangn.com",
        "google": "당근마켓",
        "query": "책상",
        "why": "슬러그 주소 + 목록이 세 덩어리로 쪼개짐",
    },
    "coupang": {
        "url": "https://www.coupang.com/np/search?q=무선마우스",
        "host": "coupang.com",
        "google": "쿠팡",
        "query": "무선마우스",
        "why": "직타로는 벽만 온다 — 사람 길로만 열린다",
    },
    "kmong": {
        "url": "https://kmong.com/search?type=gigs&keyword=AI 에이전트",
        "host": "kmong.com",
        "google": "크몽",
        "query": "AI 에이전트",
        "why": "사람만 지나는 문 뒤에 목록이 있던 곳",
    },
    "wishket": {
        "url": "https://www.wishket.com/project/?search=AI 에이전트",
        "host": "wishket.com",
        "google": "위시켓",
        "query": "AI 에이전트",
        "why": "프로젝트 목록 — 카드형",
    },
    "saramin": {
        "url": "https://www.saramin.co.kr/zf_user/search?searchword=여수 회계",
        "host": "saramin.co.kr",
        "google": "사람인",
        "query": "여수 회계",
        "why": "부속 링크(회사명·기업정보)가 섞인다 — 고치려다 되돌린 곳",
    },
    "jobkorea": {
        "url": "https://www.jobkorea.co.kr/Search/?stext=여수 회계",
        "host": "jobkorea.co.kr",
        "google": "잡코리아",
        "query": "여수 회계",
        "why": "처음으로 됐던 곳 — 목록이 마침 앞에 있었을 뿐이다",
    },
    # ── 검색을 안 거치는 목록 화면 (2026-10-05) — 주소로 바로 연다(`--direct`). 검색어가 없다.
    "github_trending": {
        "url": "https://github.com/trending/python",
        "host": "github.com",
        "google": "GitHub trending",
        "query": "",
        "why": "카드마다 짧은 부속 링크 셋(Star·별 수·포크) — 평균 글자수에 걸려 목록이 통째로 빠졌다(0줄)",
    },
    "hackernews": {
        "url": "https://news.ycombinator.com/",
        "host": "ycombinator.com",
        "google": "Hacker News",
        "query": "",
        "why": "표(table) 한 줄이 항목 — 항목은 딴 사이트로 간다",
    },
    "arxiv_list": {
        "url": "https://arxiv.org/list/cs.CL/recent",
        "host": "arxiv.org",
        "google": "arXiv cs.CL recent",
        "query": "",
        "why": "제목은 링크가 아니고(글자뿐) 항목 링크는 「arXiv:번호」 — 저자 링크 묶음이 목록을 이긴다",
    },
}

# `<link rel=stylesheet>` 를 본문에 녹여 넣고, 스크립트를 지운 뒤 문서를 통째로 돌려준다.
# 순서를 지켜야 캐스케이드가 보존된다 — `<style>` 을 `<link>` 자리에 그대로 끼운다.
_FREEZE_JS = r"""
(sheets) => {
  const map = new Map(sheets);
  let inlined = 0, missing = 0;
  for (const link of Array.from(document.querySelectorAll('link[rel~="stylesheet" i][href]'))) {
    const text = map.get(link.href);
    if (text === undefined) { missing += 1; continue; }
    const style = document.createElement('style');
    style.setAttribute('data-jarvis-from', link.href);
    style.textContent = text;
    link.replaceWith(style);
    inlined += 1;
  }
  // 재생할 때 스크립트는 안 돌린다. 여기서 지워 두면 표본이 절반으로 줄고,
  // 혹시 재생 중에 실행돼도 DOM 이 캡처 시점과 달라지는 일이 없다.
  let scripts = 0;
  for (const node of Array.from(document.querySelectorAll('script'))) {
    node.remove();
    scripts += 1;
  }
  return {
    html: '<!doctype html>\n' + document.documentElement.outerHTML,
    inlined, missing, scripts,
    links: document.querySelectorAll('a[href]').length,
  };
}
"""


_WALL_MARKERS = (
    "Access Denied", "Reference #", "unusual traffic", "verify you are human",
    "checking your browser", "captcha", "잠시 후 다시", "비정상적인 트래픽",
    "접근이 제한", "로봇이 아닙니다", "자동입력 방지",
)


def _wall_reason(frozen: dict[str, Any]) -> str:
    """문전박대 화면인가. 벽을 표본으로 얼리면 그 뒤로 영원히 벽을 시험하게 된다."""
    if frozen["links"] < 6:
        # 판정기가 링크 6개 미만이면 아예 None 을 돌려준다 — 시험이 될 수 없다.
        return f"링크 {frozen['links']}개 — 목록이 없는 화면이다"
    if frozen["inlined"] == 0:
        return "스타일시트를 하나도 못 받았다 — 껍데기만 온 화면이다"
    head = frozen["html"][:4000]
    hit = next((m for m in _WALL_MARKERS if m.lower() in head.lower()), "")
    return f"문전박대 표지: {hit}" if hit else ""


def _spawn_and_connect(playwright: Any, port: int, headless: bool) -> tuple[Any, Any, Any, Any]:
    """`chrome.exe` 를 **우리가 직접** CDP 포트로 띄우고 붙는다 — 운영과 같은 길.

    세 가지 길이 있고 셋 다 다른 화면을 본다:

        Playwright 가 띄우기   `--remote-debugging-pipe` = 자동화 모드. 봇에 걸린다.
        떠 있는 크롬에 붙기     제일 안 걸리지만 **운영 워커가 쥐고 있으면** 우리가 연
                              새 탭이 항해를 못 한다(2026-08-13 실측: 구글도 안 열림).
        chrome.exe 직접 띄우기  자동화 모드가 아니고 우리 것이라 안 물린다. ← 여기

    프로필은 운영 것과 따로 쓴다. 남의 로그인 세션을 캡처에 끌어들이지 않는다.
    """
    import subprocess
    import sys as _sys
    import tempfile
    import urllib.request

    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    profile = pathlib.Path(tempfile.gettempdir()) / "jarvis-fixture-capture-profile"
    profile.mkdir(parents=True, exist_ok=True)
    chrome = BrowserWorker(JarvisConfig())._find_chrome()

    arguments = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--headless=new" if headless else "--start-maximized",
    ]
    # ★ `--disable-*` 를 덧대지 않는다. 플래그를 더할수록 다시 자동화 브라우저처럼
    # 보이고, 그러면 이 길을 택한 이유가 통째로 사라진다.
    process = subprocess.Popen(
        arguments,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if _sys.platform == "win32" else 0,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
            break
        except Exception:
            time.sleep(0.5)
    else:
        process.kill()
        raise RuntimeError(f"cdp_port_never_opened:{port}")

    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    context = browser.contexts[0]
    pages = [item for item in context.pages if not item.is_closed()]
    page = pages[-1] if pages else context.new_page()
    print(f"[띄워서 붙음] chrome.exe · CDP {port} · 프로필 {profile.name}", flush=True)
    return process, page, context, browser


def _settle(page: Any, settle: float) -> None:
    for state, budget in (("domcontentloaded", 30_000), ("networkidle", 12_000)):
        try:
            page.wait_for_load_state(state, timeout=budget)
        except Exception:
            pass
    page.wait_for_timeout(int(settle * 1000))


def walk_in(page: Any, spec: dict[str, str], *, settle: float) -> str:
    """**사람이 가는 길**로 검색 화면까지 걸어 들어간다.

    구글 홈에서 사이트 이름을 쳐서 들어가고, 그 사이트의 검색칸에 검색어를 친다.
    직타(`url`)는 리퍼러도 쿠키도 없어서 첫 요청부터 걸린다 — 쿠팡은 직타로는
    붙은 크롬으로도 안 열렸다(2026-08-13, 60초 타임아웃 ×3).

    사이트 검색칸을 찾는 판정기는 운영 것을 **import 해서** 쓴다. 사본을 만들면
    어긋난다.
    """
    from alture_jarvis.browser import BrowserWorker

    page.goto("https://www.google.com", wait_until="commit", timeout=60_000)
    _settle(page, 1.0)
    box = page.locator("textarea[name=q], input[name=q]").first
    box.click(timeout=15_000)
    box.type(spec["google"], delay=90)  # 사람은 붙여넣지 않는다
    page.keyboard.press("Enter")
    _settle(page, 2.0)

    # 결과 중 그 사이트로 가는 첫 링크. 광고(googleadservices 경유)는 건너뛴다.
    host = spec["host"]
    link = page.locator(
        f"a[href*='//{host}'], a[href*='//www.{host}'], a[href*='.{host}/']"
    ).filter(has_not=page.locator("[aria-hidden=true]")).first
    link.click(timeout=20_000)
    _settle(page, settle)

    # 그 사이트 안에서 검색한다. 접혀 있으면 먼저 편다.
    found = page.evaluate(BrowserWorker._SITE_SEARCH_JS)
    if not found:
        opener = page.evaluate(BrowserWorker._OPEN_SEARCH_JS)
        if opener:
            page.locator("[data-jarvis-searchopen='1']").first.click(timeout=8_000)
            page.wait_for_timeout(900)
            found = page.evaluate(BrowserWorker._SITE_SEARCH_JS)
    if not found:
        raise RuntimeError(f"검색칸을 못 찾았다 — 지금 선 곳: {page.url[:90]}")

    field = page.locator("[data-jarvis-sitesearch='1']").first
    field.click(timeout=10_000)
    field.type(spec["query"], delay=110)
    page.keyboard.press("Enter")
    _settle(page, settle)
    return page.url


def capture(
    page: Any, sheets: dict[str, str], spec: dict[str, str], *, settle: float, human: bool
) -> dict[str, Any]:
    # 스타일시트는 걸어 들어오는 **동안 전부** 모은다. 마지막 화면 직전에 비우면,
    # 앞 화면에서 이미 받아 캐시에 있는 것이 다시 안 와서 구멍이 난다.
    sheets.clear()
    if human:
        walk_in(page, spec, settle=settle)
    else:
        # ★ `goto` 로 완료 상태를 기다리면 한 사이트가 안 끝날 때 캡처가 통째로
        # 실패한다(쿠팡 실측: domcontentloaded 가 60초 안에 안 왔다). 문서가 오는
        # 것까지만 기다리고 나머지는 기다리되 실패해도 넘어간다. 무엇이 왔는지는
        # 저장 직전에 따로 판정한다(`_wall_reason`).
        page.goto(spec["url"], wait_until="commit", timeout=60_000)
        _settle(page, settle)
    # 무한스크롤 사이트는 첫 화면만으로는 목록이 얕다. 한 번만 굴려 준다.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
    page.wait_for_timeout(1200)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)

    frozen = page.evaluate(_FREEZE_JS, list(sheets.items()))
    frozen["landed"] = page.url
    frozen["title"] = page.title()
    return frozen


def _write(name: str, url: str, why: str, frozen: dict[str, Any], *, suffix: str = "") -> pathlib.Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{name}{suffix}"
    html_path = FIXTURE_DIR / f"{stem}.html.gz"
    html_path.write_bytes(gzip.compress(frozen["html"].encode("utf-8"), 9))
    meta = {
        "site": name,
        "url": url,
        "landed": frozen["landed"],
        "title": frozen["title"],
        "why": why,
        # 어떤 길로 떴는지는 남겨야 한다 — 직타로 뜬 표본과 사람 길로 뜬 표본은
        # 같은 사이트라도 다른 화면일 수 있다(로그인 유도·간이 목록 등).
        "route": frozen.get("route", "direct"),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "links": frozen["links"],
        "stylesheets_inlined": frozen["inlined"],
        "stylesheets_missing": frozen["missing"],
        "scripts_stripped": frozen["scripts"],
        "bytes_gz": html_path.stat().st_size,
        # 기대 1번은 **사람이 얼린 화면을 직접 보고** 채운다. 캡처가 정하면
        # 지금 틀린 답이 그대로 정답으로 굳는다.
        "expect_top1_contains": None,
        "expect_min_items": None,
    }
    (FIXTURE_DIR / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return html_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sites", nargs="*", help="비우면 전부")
    parser.add_argument("--repeat", type=int, default=1, help="같은 화면을 N번 뜬다(흔들림 조사)")
    parser.add_argument("--settle", type=float, default=3.0, help="문서 로드 뒤 추가 대기(초)")
    # ★ 기본은 **붙기**다. Playwright 가 크롬을 띄우면 `--remote-debugging-pipe`(자동화
    # 모드)로 뜨고, 그건 봇 검사에 걸린다 — 운영이 `chrome.exe` 를 직접 띄우고 CDP 로
    # 붙는 길을 택한 이유가 바로 그것이다. 캡처만 다른 길로 뜨면 표본이 운영과 다른
    # 화면이 된다.
    parser.add_argument(
        "--spawn",
        action="store_true",
        default=True,
        help="chrome.exe 를 직접 CDP 포트로 띄워 붙는다 (기본)",
    )
    parser.add_argument(
        "--attach",
        dest="spawn",
        action="store_false",
        help="이미 떠 있는 크롬에 붙는다 — 운영 워커가 쥐고 있으면 항해가 막힌다",
    )
    parser.add_argument(
        "--launch",
        action="store_true",
        help="Playwright 가 띄운다 — 자동화 모드라 봇 검사에 걸린다. 되도록 쓰지 마라",
    )
    parser.add_argument("--headless", action="store_true", help="--launch 일 때만. 창을 안 띄운다")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="사람 길로 걸어 들어가지 않고 검색 결과 주소를 직타한다 — 빠르지만 걸린다",
    )
    # 띄울 때 9222 를 쓰면 이미 떠 있는 운영 크롬과 부딪힌다 — 길마다 기본이 다르다.
    parser.add_argument("--cdp-port", type=int, default=0, help="0이면 띄우기 9333 · 붙기 9222")
    args = parser.parse_args()

    names = args.sites or list(SITES)
    unknown = [n for n in names if n not in SITES]
    if unknown:
        print(f"모르는 이름: {unknown}. 아는 것: {list(SITES)}")
        return 2

    from playwright.sync_api import sync_playwright

    rows: list[str] = []
    spawned = None
    with sync_playwright() as p:
        if args.launch:
            browser = p.chromium.launch(headless=args.headless, channel="chrome")
            context = browser.new_context(
                locale="ko-KR",
                timezone_id="Asia/Seoul",
                viewport={"width": 1440, "height": 900},
            )
            page = context.new_page()
            print("[Playwright 가 띄움] 자동화 모드다 — 봇 검사가 있는 곳은 벽을 뜨게 된다", flush=True)
        elif args.spawn:
            spawned, page, context, browser = _spawn_and_connect(
                p, args.cdp_port or 9333, args.headless
            )
        else:
            # 평범하게 떠 있는 크롬에 붙는다. 쓰던 탭은 건드리지 않고 **새 탭**만
            # 쓰고 끝나면 닫는다.
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.cdp_port or 9222}")
            context = browser.contexts[0]
            page = context.new_page()
            page.set_viewport_size({"width": 1440, "height": 900})
            print(f"[붙음] CDP {args.cdp_port or 9222} · 새 탭", flush=True)

        sheets: dict[str, str] = {}

        def _on_response(response: Any) -> None:
            kind = (response.request.resource_type or "").lower()
            if kind != "stylesheet":
                return
            try:
                sheets[response.url] = response.text()
            except Exception:
                pass

        page.on("response", _on_response)

        for name in names:
            spec = SITES[name]
            for attempt in range(args.repeat):
                suffix = f".r{attempt + 1}" if args.repeat > 1 else ""
                label = f"{name}{suffix}"
                human = not args.direct and bool(spec.get("host") and spec.get("google"))
                print(f"... {label} ({'사람 길' if human else '직타'})", flush=True)
                try:
                    frozen = capture(page, sheets, spec, settle=args.settle, human=human)
                except Exception as exc:  # 한 곳이 죽어도 나머지는 떠야 한다
                    rows.append(f"{label:<14} 실패  {str(exc)[:90]}")
                    continue
                frozen["route"] = "human" if human else "direct"
                wall = _wall_reason(frozen)
                if wall:
                    # ★ 벽을 표본으로 얼리면 그 뒤로 영원히 벽을 시험하게 된다.
                    # 2026-08-13 쿠팡 실측: 띄운 크롬으로 링크 0개·CSS 0개가 나왔는데,
                    # 그대로 저장되면 "통과"로 보인다.
                    rows.append(f"{label:<14} 거부  {wall}")
                    continue
                path = _write(name, spec["url"], spec["why"], frozen, suffix=suffix)
                rows.append(
                    f"{label:<14} 링크 {frozen['links']:>5} · CSS {frozen['inlined']:>2}"
                    f"(못받음 {frozen['missing']}) · {path.stat().st_size // 1024:>4}KB gz"
                )
        if args.launch:
            context.close()
            browser.close()
        elif spawned is not None:
            # 우리가 띄운 크롬이다. 자식이 여럿이라 부모만 죽이면 창이 남는다.
            import subprocess as _sp

            _sp.run(["taskkill", "/F", "/T", "/PID", str(spawned.pid)], capture_output=True, timeout=20)
        else:
            page.close()  # 붙은 크롬은 우리 것이 아니다 — 우리가 연 탭만 닫는다

    print()
    for row in rows:
        print(row)
    print(f"\n→ {FIXTURE_DIR}")
    print("다음: 얼린 화면을 판정기에 태워 1번이 무엇인지 보고, .json 의 expect_top1_contains 를 채운다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
