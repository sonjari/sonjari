"""여러 사이트에서 브라우저 계층이 실제로 무엇을 할 수 있는지 재는 점검.

블로그 하나가 된다고 범용이 된 것은 아니다. 2026-08-05 인수인계 6장의 교훈이
그것이다 — 편집기가 iframe 안에 있으면 스냅샷이 "0개"로 읽히고, 그게 "빈 페이지"와
구별되지 않는다. 그래서 사이트마다 **네 가지를 따로 잰다**:

  열림      browser_open 이 실제로 그 주소에 닿았는가 (리다이렉트 포함)
  프레임    본문이 몇 번째 프레임에 있는가 (top 이 아니면 하드코딩은 다 깨진다)
  요소      snapshot 이 조작 가능한 요소를 찾았는가 (0이면 클릭 계획을 못 세운다)
  본문      read 가 사람이 읽을 글을 가져왔는가 (봇 검사 화면이면 여기가 짧다)

읽기만 한다. 아무것도 제출하지 않고, 로그인도 하지 않는다.

  python scripts/survey_sites.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8091"
TOKEN_PATH = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\control.token")

# 사용자님 사업이 실제로 다뤄야 하는 곳들. 무작위 사이트를 재면 무작위 결과가 나온다.
SITES = [
    ("대학어디가", "https://www.adiga.kr", "입시 — 전형/모집요강 원천"),
    ("대학알리미", "https://www.academyinfo.go.kr", "입시 — 취업률·중도탈락률 지표"),
    ("커리어넷", "https://www.career.go.kr", "진로 — 직업/학과 정보"),
    ("학교알리미", "https://www.schoolinfo.go.kr", "운영 — 학교 공시"),
    ("한국교육과정평가원", "https://www.kice.re.kr", "학습 — 수능/모평 공지"),
    ("EBSi", "https://www.ebsi.co.kr", "학습 — 기출/해설"),
    ("네이버 뉴스", "https://news.naver.com", "일반 — 국내 기사"),
    ("GitHub", "https://github.com/anthropics", "개발 — 저장소 탐색"),
]

_BOT_MARKERS = (
    "로봇이 아닙니다", "비정상적인 트래픽", "자동입력 방지", "접근이 제한",
    "마지막 한 단계", "과제 해결", "사람인지 확인", "보안문자",
    "unusual traffic", "verify you are human", "captcha", "checking your browser",
)


def call(name: str, arguments: dict) -> dict:
    body = json.dumps({"name": name, "arguments": arguments}).encode()
    request = urllib.request.Request(
        f"{BASE}/v1/tools/execute",
        data=body,
        headers={"X-JARVIS-TOKEN": TOKEN_PATH.read_text().strip(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def survey(url: str) -> dict:
    row: dict = {}
    started = time.monotonic()
    opened = call("browser_open", {"url": url})
    row["opened"] = bool(opened.get("ok"))
    row["open_sec"] = round(time.monotonic() - started, 1)
    row["error"] = str(opened.get("error") or "")[:120]
    result = opened.get("result") or {}
    row["landed"] = str(result.get("url") or "")[:70]
    if not row["opened"]:
        return row

    snapshot = (call("browser_snapshot", {"limit": 200}).get("result") or {})
    row["elements"] = int(snapshot.get("element_count") or 0)
    row["frames"] = int(snapshot.get("frame_count") or 0)
    # 조작 대상이 top 문서 밖에 있는가. 있으면 프레임을 못 박은 코드는 그 사이트에서 깨진다.
    row["outside_top"] = sum(
        1 for element in (snapshot.get("elements") or []) if str(element.get("frame") or "main") != "main"
    )

    read = (call("browser_read", {"max_chars": 6000}).get("result") or {})
    text = str(read.get("text") or "")
    row["chars"] = len(text)
    row["blocked"] = next((m for m in _BOT_MARKERS if m in text), "")
    return row


def main() -> int:
    rows = []
    for name, url, why in SITES:
        print(f"... {name}", flush=True)
        try:
            row = survey(url)
        except Exception as exc:  # 한 사이트가 죽어도 나머지는 재야 한다
            row = {"opened": False, "error": str(exc)[:120]}
        row.update(name=name, url=url, why=why)
        rows.append(row)

    print()
    header = f"{'사이트':<12} {'열림':<5} {'초':>5} {'프레임':>6} {'요소':>5} {'top밖':>6} {'본문자':>7}  비고"
    print(header)
    print("-" * len(header))
    for row in rows:
        note = row.get("blocked") and f"차단: {row['blocked']}" or row.get("error", "")
        if not note and row.get("elements", 0) == 0 and row.get("opened"):
            note = "조작 가능한 요소 0"
        print(
            f"{row['name']:<12} {'O' if row.get('opened') else 'X':<5} "
            f"{row.get('open_sec', 0):>5} {row.get('frames', 0):>6} {row.get('elements', 0):>5} "
            f"{row.get('outside_top', 0):>6} {row.get('chars', 0):>7}  {note}"
        )
    pathlib.Path("site_survey.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
