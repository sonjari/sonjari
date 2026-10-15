"""네이버 블로그 탭 결과가 **글**인가 — 실사이트로 확인한다.

읽기만 한다. 아무것도 누르지 않고, 제출하지 않고, 로그인하지 않는다.

2026-08-07 에 잰 이전 상태는 이랬다(질의 두 개 모두 동일):

    결과 10건 · 그중 블로그 홈 5건 · rank=1 이 홈

블로그 홈을 열면 그 블로그의 최신 글(질의와 무관한 글)이 뜨므로 그 순위는 통째로
버려진다. 카드가 블로그 이름(홈)과 글 제목(글) 두 링크를 갖는데 파서가 둘을 별개
순위로 세던 것이 원인이었다 — `serp.collect_results` 가 홈을 같은 블로그의 글에
합친다.

묶기 규칙 자체는 `tests/test_serp_results.py` 가 실측 픽스처로 잠가 둔다. 이 스크립트가
따로 있는 이유는 **네이버가 화면을 바꾸면** 픽스처는 그대로 통과하면서 실제 결과만
조용히 망가지기 때문이다.

Run:
    set PYTHONPATH=C:\\work\\monorepo\\tools\\alture-jarvis\\src
    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts\\verify_blog_results.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from _scratch import scratch_root
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

# 하나로는 모자란다 — 한 질의만 보면 그 질의의 카드 배치에만 맞춘 수정이 통과한다.
QUERIES = ("제주도 3박4일 여행 경비 총정리", "부산 서면 맛집 후기")
WANTED = 10


def _is_blog_home(url: str) -> bool:
    """글이 아니라 블로그 홈인가 — 경로에 글 번호가 없으면 홈이다."""
    parsed = urlparse(url)
    if "blog.naver.com" not in parsed.netloc:
        return False
    return len([segment for segment in parsed.path.split("/") if segment]) < 2


def main() -> int:
    with scratch_root("jarvis-blogresults-") as root:
        return _run(root)


def _run(root: Path) -> int:
    worker = BrowserWorker(
        JarvisConfig(
            runtime_root=root,
            data_dir=root / "data",
            output_dir=root / "out",
            browser_headless=True,
            browser_read_only=True,
            browser_profile_dir=root / "profile",
        )
    )
    worker.start()
    failures: list[str] = []
    try:
        for query in QUERIES:
            print(f"\n{'=' * 74}\n{query}\n{'=' * 74}")
            found = worker.execute(
                "browser_search",
                {"query": query, "engine": "naver", "tab": "blog", "limit": WANTED},
            )
            urls = [item["url"] for item in found["results"]]
            homes = [url for url in urls if _is_blog_home(url)]
            for item in found["results"]:
                print(f"  {item['rank']:>2}. {item['title'][:44]:<46} {item['url'][:70]}")
            print(
                f"  → 결과 {found['result_count']}건 · 블로그 홈 {len(homes)}건 · "
                f"중복 {len(urls) - len(set(urls))}건"
            )
            if homes:
                failures.append(f"{query}: 블로그 홈이 순위를 차지한다 {len(homes)}건")
            if len(urls) != len(set(urls)):
                failures.append(f"{query}: 같은 주소가 두 순위에 있다")
            # 홈을 뺀 만큼 더 훑지 않으면 목록이 반토막 난다(browser.py 의 budget).
            if found["result_count"] < WANTED:
                failures.append(
                    f"{query}: {WANTED}건 요청에 {found['result_count']}건 — 훑는 양이 모자라다"
                )
            if not found["results"]:
                continue

            # 순위를 열었을 때 정말 글이 나오는가. 홈이면 본문이 있긴 하되 **다른 글**이라
            # 건수만 봐서는 안 걸린다.
            opened = worker.execute("browser_open_result", {"rank": 1})
            body = worker.execute("browser_extract", {"max_chars": 2000})
            print(f"  rank=1 → {opened['url'][:70]}")
            print(f"  본문 {body['char_count']}자 · {body['text'][:70]}")
            if _is_blog_home(opened["url"]):
                failures.append(f"{query}: rank=1 이 블로그 홈이다")
            if body["char_count"] < 300:
                failures.append(f"{query}: rank=1 본문이 {body['char_count']}자뿐")
    finally:
        worker.stop()

    print(f"\n{'=' * 74}\n판정\n{'=' * 74}")
    if failures:
        for line in failures:
            print(f"  ✗ {line}")
        return 1
    print(f"  ✓ 두 질의 모두 {WANTED}건 전부 글이다 · 중복 없음 · rank=1 이 글로 열린다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
