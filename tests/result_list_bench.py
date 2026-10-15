"""얼린 화면 위에서 **진짜 판정기**를 돌리는 재생 장치.

시험이 아니다(`test_` 로 시작하지 않는다). `test_result_list_bench.py` 가 쓴다.
직접 돌려서 눈으로 볼 수도 있다:

    python tests/result_list_bench.py            # 사람이 읽는 표
    python tests/result_list_bench.py --json     # 시험이 먹는 JSON

## 무엇이 진짜인가

    판정기   `BrowserWorker._RESULT_LIST_JS` 를 **import 해서** 태운다.
             사본을 만들면 어긋난다 — 2026-08-05 에 이미 데인 자리다.
    엔진     실제 크롬(`channel="chrome"`). 운영이 붙는 것과 같다.
    주소     `page.route` 로 가로채 **원래 주소 그대로** 재생한다.
             `location.href` 를 쓰는 자기 페이지 판정이 살아 있어야 한다.
    그물     문서 하나만 내주고 나머지는 전부 끊는다. 바깥으로 나가는 요청이 없으니
             사이트가 바뀌어도 어제와 오늘이 같은 값을 낸다.

CSS 는 캡처할 때 본문에 녹여 넣었다(`capture_result_list_fixtures.py`). 그래서
`getBoundingClientRect`·`getComputedStyle`·`innerText` 가 살아있는 화면과 같은 값을 낸다.

## ★ 왜 별도 프로세스인가

pytest 안에서 바로 `sync_playwright()` 를 부르면 **전체 시험을 돌릴 때만** 깨진다:

    '_Chromium' object has no attribute 'launch'

앞선 시험들이 이벤트 루프를 돌려 놓아서 sync API 가 제대로 안 잡히는 것이다.
단독으로 돌리면 멀쩡하니 알아채기도 어렵고, 결과는 **조용한 건너뜀 16건**이다 —
초록불인데 아무것도 안 잰 상태(2026-07-28 CI 사고와 같은 모양).

그래서 재생은 **자식 프로세스에서 한 번에 전부** 하고 결과만 JSON 으로 받는다.
프로세스가 깨끗하니 루프 오염이 원리적으로 없고, 크롬도 한 번만 띄운다.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import sys
from typing import Any

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "result_lists"

# pytest 의 `pythonpath = ["src"]` 는 **부모 프로세스에만** 걸린다. 재생은 자식에서 도는데,
# 그 자식은 src 를 못 찾아 `ModuleNotFoundError` 로 죽고 → 시험은 그것을 "크롬을 띄울 수
# 없다"로 읽어 **조용히 건너뛴다.** 표본 8개 × 시험 2개 = 16건이 초록불 뒤에 숨는다
# (2026-08-14 실측. 이 벤치는 만들어진 뒤로 pytest 안에서 한 번도 돈 적이 없었다).
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class Fixture:
    def __init__(self, name: str, meta: dict[str, Any], html: str) -> None:
        self.name = name
        self.meta = meta
        self.html = html

    @property
    def url(self) -> str:
        # 얼릴 때 실제로 닿은 주소로 재생한다. 리다이렉트가 있으면 그쪽이 진짜다.
        return str(self.meta.get("landed") or self.meta["url"])

    @property
    def expect_top1(self) -> str | None:
        value = self.meta.get("expect_top1_contains")
        return str(value) if value else None

    @property
    def expect_min_items(self) -> int:
        return int(self.meta.get("expect_min_items") or 0)

    @property
    def known_failing(self) -> bool:
        """지금은 못 푸는 자리. **빼지 않고** 빨간불로 들고 간다 —
        빼는 순간 "전부 통과"가 구멍을 덮는다."""
        return bool(self.meta.get("known_failing"))


def names() -> list[str]:
    """얼려 둔 표본 전부. 기대값이 비었는지는 시험이 판단한다 —
    여기서 걸러 내면 **기대를 안 채운 표본이 조용히 사라진다.**"""
    if not FIXTURE_DIR.exists():
        return []
    return sorted(
        path.stem for path in FIXTURE_DIR.glob("*.json") if (FIXTURE_DIR / f"{path.stem}.html.gz").exists()
    )


def load(name: str) -> Fixture:
    meta = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    html = gzip.decompress((FIXTURE_DIR / f"{name}.html.gz").read_bytes()).decode("utf-8")
    return Fixture(name, meta, html)


def _rows_from(found: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in found or []:
        if isinstance(item, dict):
            href, name = str(item.get("href") or ""), str(item.get("name") or "")
        else:
            href, name = str(item or ""), ""
        if href:
            rows.append({"name": name, "href": href})
    return rows


def detect_all(only: list[str] | None = None) -> dict[str, Any]:
    """크롬 하나로 표본 전부를 잰다. 이 함수는 **자식 프로세스에서** 돈다."""
    from playwright.sync_api import sync_playwright

    from alture_jarvis.browser import BrowserWorker

    wanted = only or names()
    out: dict[str, Any] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chrome")
        for name in wanted:
            fixture = load(name)
            context = browser.new_context(
                locale="ko-KR", timezone_id="Asia/Seoul", viewport={"width": 1440, "height": 900}
            )
            page = context.new_page()
            try:
                body = fixture.html

                def _route(route: Any, request: Any, body: str = body) -> None:
                    # 문서 하나만 내준다. 나머지(이미지·글꼴·추적·XHR)는 전부 끊는다 —
                    # 표본이 바깥 세상에 의존하는 순간 시험이 아니라 관측이 된다.
                    if request.resource_type == "document" and request.is_navigation_request():
                        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)
                    else:
                        route.abort()

                page.route("**/*", _route)
                # `load` 를 기다리면 안 된다 — 끊어 버린 이미지·글꼴 때문에 영영 안 온다
                # (다나와 실측: 30초 타임아웃). 스크립트는 얼릴 때 지웠고 CSS 는 본문에
                # 녹아 있으니, DOM 이 서면 판정에 필요한 것은 이미 다 있다.
                page.goto(fixture.url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(300)  # 레이아웃이 서야 rect 가 0 이 아니다
                out[name] = _rows_from(page.evaluate(BrowserWorker._RESULT_LIST_JS))
            finally:
                context.close()
        browser.close()
    return out


def main() -> int:
    as_json = "--json" in sys.argv
    picked = [arg for arg in sys.argv[1:] if not arg.startswith("--")] or None
    try:
        found = detect_all(picked)
    except Exception as exc:
        if as_json:
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}"[:400]}, ensure_ascii=False))
            return 3
        raise
    if as_json:
        print(json.dumps(found, ensure_ascii=False))
        return 0
    for name, rows in found.items():
        fixture = load(name)
        mark = "✗" if fixture.expect_top1 and (not rows or fixture.expect_top1 not in rows[0]["name"]) else "○"
        print(f"\n{mark} {name} — {len(rows)}건 (기대 1번: {fixture.expect_top1})")
        for index, row in enumerate(rows[:5], 1):
            print(f"   {index}. {row['name'][:70]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
