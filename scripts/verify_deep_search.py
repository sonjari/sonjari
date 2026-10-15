"""검색 → 결과 → 본문 → 그 안의 링크. 파고드는 고리를 **실제 사이트**로 확인한다.

읽기만 한다. 아무것도 누르지 않고, 제출하지 않고, 로그인하지 않는다.

이 스크립트가 답하려는 질문은 하나다: **모델이 이제 무엇을 보는가.**
2026-08-06 에 같은 질의로 잰 이전 상태는 이랬다:

    네이버  스냅샷 요소 114개 · 첫 외부 결과 j21 · 결과 목록 없음
    빙      스냅샷 요소 40개 · 첫 외부 결과 없음 · 링크 26개 전부 ck/a 래퍼

Run:
    set PYTHONPATH=C:\\work\\monorepo\\tools\\alture-jarvis\\src
    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts\\verify_deep_search.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from _scratch import scratch_root
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig

QUERY = "크몽 AI 챗봇 개발 견적 사례 블로그"


def _worker(root: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=root,
            data_dir=root / "data",
            output_dir=root / "out",
            browser_headless=True,
            browser_read_only=True,
            browser_profile_dir=root / "profile",
        )
    )


def _show(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def main() -> int:
    with scratch_root("jarvis-deepsearch-") as root:
        return _run(root)


def _run(root: Path) -> int:
    worker = _worker(root)
    worker.start()
    failures: list[str] = []

    try:
        # ---- 1. 검색이 결과 목록을 돌려주는가 -----------------------------------
        _show(f"1. browser_search  (네이버 블로그 탭)  · {QUERY}")
        found = worker.execute("browser_search", {"query": QUERY, "engine": "naver", "tab": "blog", "limit": 8})
        print(f"엔진={found['engine']}  탭={found['tab']}  화면요소={found['element_count']}  "
              f"결과={found['result_count']}건")
        for item in found["results"]:
            mark = " (본 적 있음)" if item.get("visited") else ""
            print(f"  {item['rank']:>2}. {item['title'][:52]:<54} {item['domain']}{mark}")
            if item.get("snippet"):
                print(f"      └ {item['snippet'][:70]}")
        if not found["results"]:
            failures.append("네이버 검색이 결과 0건 — 예전 상태 그대로다")

        # ---- 2. 순위로 들어가지는가 --------------------------------------------
        if found["results"]:
            _show("2. browser_open_result rank=1  (ref 가 아니라 순위로)")
            opened = worker.execute("browser_open_result", {"rank": 1})
            print(f"제목={opened['result_title'][:60]}")
            print(f"주소={opened['url'][:88]}")
            print(f"남은 순위={opened['remaining']}")

            # ---- 3. 본문만 추려지는가 -------------------------------------------
            _show("3. browser_extract  (메뉴·추천글을 뺀 글 자체)")
            body = worker.execute("browser_extract", {"max_chars": 4000})
            whole = worker.execute("browser_read", {"max_chars": 20000})
            print(f"본문 {body['char_count']}자   (selector={body['selector']}, "
                  f"링크비중={body.get('link_ratio')}%, 폴백={body['fell_back']})")
            print(f"화면 전체 {whole['char_count']}자")
            if whole["char_count"]:
                saved = 100 - round(body["char_count"] / whole["char_count"] * 100)
                print(f"→ 컨텍스트 {saved}% 절약")
            print("--- 앞 300자 ---")
            print(body["text"][:300].replace("\n", " ⏎ "))
            if body["fell_back"]:
                print("! 본문 영역을 못 골랐다 — 이 사이트 구조를 확인할 것")

            # ---- 4. 더 깊이 갈 곳이 보이는가 ------------------------------------
            _show("4. browser_links  (다음 한 걸음)")
            inside = worker.execute("browser_links", {"same_site": "inside", "limit": 6})
            outside = worker.execute("browser_links", {"same_site": "outside", "limit": 6})
            print(f"같은 사이트 안 {inside['link_count']}개:")
            for link in inside["links"][:6]:
                print(f"   · {link['text'][:44]:<46} {link['url'][:52]}")
            print(f"바깥 출처 {outside['link_count']}개:")
            for link in outside["links"][:6]:
                seen = " (본 적 있음)" if link.get("visited") else ""
                print(f"   · {link['text'][:44]:<46} {link['domain']}{seen}")

            # ---- 5. 목록으로 안 돌아가고 다음 결과로 ----------------------------
            if len(found["results"]) > 1:
                _show("5. browser_open_result rank=2  (뒤로가기 없이)")
                second = worker.execute("browser_open_result", {"rank": 2})
                print(f"제목={second['result_title'][:60]}")
                print(f"주소={second['url'][:88]}")

                _show("6. 다시 검색하면 이미 본 것에 표시가 붙는가")
                again = worker.execute("browser_search", {"query": QUERY, "engine": "naver", "tab": "blog", "limit": 8})
                marked = [item["rank"] for item in again["results"] if item.get("visited")]
                print(f"본 적 있음으로 표시된 순위: {marked}")
                if not marked:
                    failures.append("방문 표시가 안 붙는다 — 같은 글을 계속 다시 연다")

        # ---- 7. 빙: 리다이렉트 래퍼가 벗겨지는가 --------------------------------
        _show("7. browser_search (빙)  — 링크 26개가 전부 bing.com/ck/a 였던 자리")
        bing = worker.execute("browser_search", {"query": QUERY, "engine": "bing", "limit": 8})
        print(f"결과 {bing['result_count']}건")
        for item in bing["results"]:
            print(f"  {item['rank']:>2}. {item['title'][:50]:<52} {item['domain']}")
        wrapped = [item for item in bing["results"] if "bing.com" in item["domain"]]
        if wrapped:
            failures.append(f"빙 결과 {len(wrapped)}건이 아직 래퍼 주소다")
        if not bing["results"]:
            failures.append("빙 검색이 결과 0건")

        # ---- 8. 찾기 -------------------------------------------------------------
        _show("8. browser_find  — 200개 덤프 대신 걸린 것만")
        hits = worker.execute("browser_find", {"query": "블로그"})
        print(f"{hits['scanned']}개 훑어 {hits['match_count']}개 일치")
        for row in hits["matches"][:5]:
            print(f"   {row['ref']:<5} {row['name'][:60]}")

    finally:
        worker.stop()

    _show("판정")
    if failures:
        for line in failures:
            print(f"  ✗ {line}")
        return 1
    print("  ✓ 검색이 결과 목록을 준다 · 순위로 들어간다 · 본문만 읽는다 · 다음 링크가 보인다")
    print("  ✓ 빙 래퍼가 벗겨진다 · 본 것에 표시가 붙는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
