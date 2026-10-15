"""2026-09-06 벤치 증거 보관 — 원문 + 해시 + 그 원문이 증명하는 주장.

웹은 움직인다. `class="point"` 가 내일 사라지면 "curl 두 줄로 재현" 이 통째로
무효가 된다. 원문을 날짜와 함께 박고, **그 원문에서 무엇을 셌는지**도 같이 적는다.
파일만 남기면 나중에 무엇을 증명하려 했는지 모른다.
"""
from __future__ import annotations
import hashlib, io, json, pathlib, re, sys, time, urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = pathlib.Path(r"C:\work\monorepo\tools\alture-jarvis\docs\evidence\2026-09-06")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

# (파일명, URL, 이 원문이 증명하는 것, 세는 방법)
TARGETS = [
    ("kyobo_listing.html",
     "https://search.kyobobook.co.kr/search?keyword=%ED%9A%8C%EA%B3%84&target=total",
     "990p 는 적립 포인트지 쪽수가 아니다 — 목록에 '쪽' 은 0회",
     {"class=\"point\"": None, "쪽": None, "990p": None, "2,250": None}),
    ("yes24_119293186.html", "https://www.yes24.com/product/goods/119293186",
     "Do it! 점프 투 파이썬 = 432쪽 / ISBN 9791163034735", {"432": None, "9791163034735": None}),
    ("yes24_116038106.html", "https://www.yes24.com/product/goods/116038106",
     "Do it! 게임 10개 = 376쪽 / 9791163034230", {"376": None, "9791163034230": None}),
    ("yes24_117373102.html", "https://www.yes24.com/product/goods/117373102",
     "나도코딩 파이썬 입문 = 436쪽 / 9791140703302", {"436": None, "9791140703302": None}),
    ("yes24_109625396.html", "https://www.yes24.com/product/goods/109625396",
     "혼자 공부하는 파이썬 = 552쪽 / 9791162245651", {"552": None, "9791162245651": None}),
    ("yes24_116253011.html", "https://www.yes24.com/product/goods/116253011",
     "혼자 공부하는 데이터 분석 = 496쪽 / 9791169210287", {"496": None, "9791169210287": None}),
    ("wishket_154599_closed.html", "https://www.wishket.com/project/154599/",
     "BU(로컬)가 답한 공고 — 모집 마감", {"closed-mark": None, "모집 마감": None}),
    ("wishket_157299_closed.html", "https://www.wishket.com/project/157299/",
     "BU(로컬)가 답한 공고 — 모집 마감", {"closed-mark": None, "모집 마감": None}),
    ("wishket_155967_closed.html", "https://www.wishket.com/project/155967/",
     "BU(로컬)가 답한 공고 — 모집 마감", {"closed-mark": None, "모집 마감": None}),
    ("wishket_158203_open.html", "https://www.wishket.com/project/158203/",
     "자비스·소네트가 답한 공고 — 모집 중", {"recruiting-mark": None, "모집 중": None}),
    ("wishket_158176_open.html", "https://www.wishket.com/project/158176/",
     "자비스·소네트가 답한 공고 — 모집 중", {"recruiting-mark": None, "모집 중": None}),
    ("wishket_158173_open.html", "https://www.wishket.com/project/158173/",
     "자비스·소네트가 답한 공고 — 모집 중", {"recruiting-mark": None, "모집 중": None}),
]

rows = []
for name, url, claim, probes in TARGETS:
    row = {"file": name, "url": url, "claim": claim,
           "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            row["http_status"] = r.status
        (OUT / name).write_bytes(raw)
        text = raw.decode("utf-8", "replace")
        row["bytes"] = len(raw)
        row["sha256"] = hashlib.sha256(raw).hexdigest()
        row["counts"] = {k: text.count(k) for k in probes}
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"[:200]
    rows.append(row)
    print(f"  {name:32} {row.get('bytes', 0):>8,}B  {row.get('counts') or row.get('error')}")

(OUT / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{len(rows)}건 → {OUT}")
