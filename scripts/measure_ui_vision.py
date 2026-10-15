"""Does the local model actually pick the right thing? Measure before building on it.

The 2026-08-05 handoff (3.4-3) makes this the gate: if `plopfit-gemma4-qat`
cannot choose from a numbered candidate list, the "model is the eyes, code is
the hands" design does not stand and the next session must find out here rather
than three sites later.

Fixtures are served locally on purpose. Real sites move, and the point of this
harness is a number the next session can re-run and compare against. Each page
reproduces one way targeting fails in practice:

  * an element list alone is enough          -- the sanity case
  * the target lives inside an iframe        -- what read as "0 elements" for two days
  * candidates have no accessible name       -- only the picture can tell them apart
  * two candidates share a name              -- text cannot decide, position can
  * the target is simply not on the screen   -- the fail-closed case, and the one
                                                that matters most: a picker that
                                                will not say "없음" is a picker
                                                that presses something wrong

Run:  .venv\\Scripts\\python.exe scripts\\measure_ui_vision.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _scratch import scratch_root
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient
from alture_jarvis.ui_vision import UiVision


_STYLE = """<style>
 body{font:15px/1.5 'Malgun Gothic',sans-serif;margin:0;color:#111}
 header{display:flex;gap:8px;align-items:center;padding:10px 16px;border-bottom:1px solid #ddd;background:#fafafa}
 button,a.btn{padding:7px 14px;border:1px solid #bbb;border-radius:5px;background:#fff;cursor:pointer}
 .icons button{width:40px;height:36px;font-size:17px}
 main{padding:24px}
 .toolbar{display:flex;gap:6px;padding:8px 16px;background:#f1f5f9;border-bottom:1px solid #ddd}
 footer{padding:14px 16px;border-top:1px solid #ddd;background:#fafafa}
 iframe{width:100%;height:340px;border:1px solid #ccc}
 input,textarea{padding:7px;border:1px solid #bbb;border-radius:5px;width:60%}
</style>"""


PAGES: dict[str, str] = {
    # 1. Plain: the list alone is enough. If this one misses, nothing else matters.
    "/plain": f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>블로그 홈</title>{_STYLE}</head>
<body><header><button>알림</button><button>내 블로그</button><button>글쓰기</button><button>로그아웃</button></header>
<main><h1>이웃 새 글</h1><p>오늘의 소식입니다.</p></main></body></html>""",
    # 2. The target is inside an iframe -- the blind spot that read as "0 elements".
    "/editor": f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>편집기</title>{_STYLE}</head>
<body><header><button>내 블로그</button><button>알림</button></header>
<iframe name="mainFrame" src="/editor-inner"></iframe></body></html>""",
    "/editor-inner": f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>편집기 내부</title>{_STYLE}</head>
<body><div class=toolbar><button>굵게</button><button>기울임</button><button>사진</button></div>
<main><input placeholder="제목"><br><br><textarea placeholder="본문을 입력하세요" rows=6></textarea></main></body></html>""",
    # 3. Icon-only buttons: no name to read, so only the picture can decide.
    "/icons": f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>도구 모음</title>{_STYLE}</head>
<body><header class=icons><button>&#128269;</button><button>&#128465;</button><button>&#128190;</button><button>&#9881;</button></header>
<main><h1>문서</h1><p>아이콘만 있는 버튼들입니다.</p></main></body></html>""",
    # 4. Two buttons share a name. Text cannot choose; where they sit can.
    "/twosaves": f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>설정</title>{_STYLE}</head>
<body><div class=toolbar><button>저장</button><button>미리보기</button></div>
<main><h1>프로필 설정</h1><p>아래 저장은 프로필 양식용입니다.</p><input value="박가람"></main>
<footer><button>저장</button></footer></body></html>""",
    # 5. Nothing here matches the goal. The right answer is 0.
    "/absent": f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>공지</title>{_STYLE}</head>
<body><header><button>목록</button><button>인쇄</button></header>
<main><h1>서비스 점검 안내</h1><p>오늘 새벽 점검이 있었습니다.</p></main></body></html>""",
}


# `expect` is None for "must answer 0", a string matched against the chosen
# element's name, or a predicate when a name cannot decide the case. `hint`
# explains what the case was actually testing, printed only when it fails.
def _lower_of_two(chosen: dict) -> bool:
    """The *footer* 저장, not the toolbar one.

    Matching on the name here would pass whichever of the two was picked --
    which is the failure mode this case exists to catch, and it was doing
    exactly that until the geometry check replaced it.
    """
    box = chosen.get("box") or {}
    return chosen.get("name") == "저장" and float(box.get("y", 0)) > 200


def _upper_of_two(chosen: dict) -> bool:
    box = chosen.get("box") or {}
    return chosen.get("name") == "저장" and float(box.get("y", 9999)) < 200


CASES = [
    ("/plain", "글쓰기 버튼", "글쓰기", "목록만으로 충분한 기본 사례"),
    ("/plain", "로그아웃 버튼", "로그아웃", "비슷한 버튼들 사이의 구분"),
    ("/editor", "글 제목을 입력하는 칸", "제목", "iframe 안쪽 요소"),
    ("/editor", "본문을 입력하는 칸", "본문을 입력하세요", "iframe 안쪽, 제목과 혼동되기 쉬움"),
    ("/editor", "사진 넣기 버튼", "사진", "iframe 툴바"),
    ("/icons", "검색 버튼", "🔍", "이름이 없어 그림으로만 판단 가능"),
    ("/icons", "삭제 버튼", "🗑", "이름이 없어 그림으로만 판단 가능"),
    ("/icons", "설정 버튼", "⚙", "이름이 없어 그림으로만 판단 가능"),
    ("/twosaves", "맨 아래 양식의 저장 버튼", _lower_of_two, "이름이 같은 두 후보 — 아래쪽"),
    ("/twosaves", "맨 위 도구 모음의 저장 버튼", _upper_of_two, "이름이 같은 두 후보 — 위쪽"),
    ("/absent", "결제하기 버튼", None, "★없는 것을 없다고 말하는가 (fail-closed)"),
    ("/absent", "글쓰기 버튼", None, "★없는 것을 없다고 말하는가 (fail-closed)"),
]


def _label(expected) -> str:
    """How the expectation is printed. Predicates carry no readable name of
    their own, so the function name stands in."""
    if expected is None:
        return "(없음=0)"
    if callable(expected):
        return getattr(expected, "__name__", "predicate")
    return str(expected)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        body = PAGES.get(self.path, "<h1>404</h1>")
        encoded = body.encode("utf-8")
        self.send_response(200 if self.path in PAGES else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args) -> None:
        return


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "plopfit-gemma4-qat:latest"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    with scratch_root("jarvis-uivision-") as root:
        config = JarvisConfig(
            runtime_root=root,
            data_dir=root / "data",
            output_dir=root / "outputs",
            browser_enabled=True,
            # Headless so this never steals the screen, and so it can run while
            # JARVIS itself has the real profile open.
            browser_headless=True,
            browser_read_only=True,
            browser_visual_overlay=False,
            browser_profile_dir=root / "profile",
            browser_download_dir=root / "downloads",
            browser_evidence_dir=root / "evidence",
            ollama_model=model,
        )
        config.prepare()
        worker = BrowserWorker(config)
        vision = UiVision(config, worker, OllamaClient(config))

        rows = []
        try:
            for path, goal, expected, hint in CASES:
                worker.execute("browser_open", {"url": base + path})
                worker.execute("browser_wait", {"milliseconds": 400})
                started = time.time()
                try:
                    result = vision.find({"goal": goal})
                except Exception as exc:  # a raised error is a failed case, not a crash
                    rows.append(
                        {
                            "page": path, "goal": goal, "expected": expected,
                            "got": f"error:{exc}", "ok": False, "sec": 0.0, "hint": hint,
                        }
                    )
                    continue
                elapsed = round(time.time() - started, 1)
                chosen = (result.get("chosen") or {}).get("name") if result.get("chosen") else None
                if expected is None:
                    ok = result["status"] == "not_found"
                elif callable(expected):
                    ok = bool(result.get("chosen")) and expected(result["chosen"])
                else:
                    ok = bool(chosen) and expected in str(chosen)
                label = _label(expected)
                rows.append(
                    {
                        "page": path,
                        "goal": goal,
                        "expected": label,
                        "got": chosen or result["status"],
                        "raw": result.get("raw", ""),
                        "ok": ok,
                        "sec": elapsed,
                        "hint": hint,
                        # ★ 누가 골랐는가 (2026-08-13).
                        #
                        # 이제 `find` 는 이름이 딱 하나 맞으면 **비전을 안 부르고**
                        # 돌려준다(`method="name_match"`). 그 판을 섞어서 세면 이 표는
                        # 젬마 실력을 실제보다 좋게 말한다 — 정작 그림은 보지도 않았는데.
                        # 이 저장소가 "만든 것과 도는 것을 구별한다"고 정한 것과 같은 규율이다.
                        "method": str(result.get("method") or "vision"),
                    }
                )
        finally:
            worker.stop()
            server.shutdown()

    passed = sum(1 for row in rows if row["ok"])
    print(f"\n{'':2} {'페이지':<14}{'목표':<26}{'기대':<20}{'응답':<20}{'초':>5}  {'고른이'}")
    for row in rows:
        mark = "OK" if row["ok"] else "XX"
        print(
            f"{mark:2} {row['page']:<14}{row['goal']:<26}"
            f"{str(row['expected']):<20}{str(row['got']):<20}{row['sec']:>5}"
            f"  {row.get('method', 'vision')}"
        )
        if not row["ok"]:
            print(f"     └ {row['hint']} | 모델 원문: {str(row.get('raw'))[:80]}")

    # ★ 갈라서 적는다. 합쳐 놓으면 이 표가 젬마 실력을 말하는 척하면서 실은
    # 코드가 찾은 것까지 세게 된다(2026-08-13, `_by_name` 지름길이 생긴 뒤).
    by_vision = [r for r in rows if r.get("method", "vision") == "vision"]
    by_name = [r for r in rows if r.get("method") == "name_match"]
    print(f"\n전체 정확도: {passed}/{len(rows)}  ({round(100 * passed / max(1, len(rows)))}%)  model={model}")
    if by_vision:
        hit = sum(1 for r in by_vision if r["ok"])
        print(f"  그림을 보고 고른 판 : {hit}/{len(by_vision)}  ← 이것이 비전 실력이다")
    else:
        print("  그림을 보고 고른 판 : 0건 — 이 표는 비전에 대해 아무 말도 하지 않는다")
    if by_name:
        hit = sum(1 for r in by_name if r["ok"])
        print(f"  이름으로 찾은 판    : {hit}/{len(by_name)}  (비전 안 부름)")

    summary = {
        "model": model,
        "passed": passed,
        "total": len(rows),
        "vision_passed": sum(1 for r in by_vision if r["ok"]),
        "vision_total": len(by_vision),
        "name_match_passed": sum(1 for r in by_name if r["ok"]),
        "name_match_total": len(by_name),
        "rows": rows,
    }
    out = Path(__file__).resolve().parent.parent / "docs" / "ui_vision_measurement.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"기록: {out}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
