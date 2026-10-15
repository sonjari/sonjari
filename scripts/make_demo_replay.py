"""첫 실행 화면의 되감기 기록(`ui/src/setup/demoReplay.json`)을 **실제 판의 장부에서** 뽑는다.

    python scripts/make_demo_replay.py <job_id 앞자리>

## 규칙 (2026-09-14)

- 지어내지 않는다. 걸음·시각·파일·표는 전부 그 판의 장부와 그 판이 만든 파일에서 온다.
- 기사 **본문은 담지 않는다**(저작권). 제목·언론사·주소의 호스트만.
- 「확인」 줄은 벤치 양식·근거 검사기(`doc_form`)가 그 파일을 장부와 대조한 결과다.
  못 맞춘 값이 있으면 있다고 적는다 — 데모라고 좋은 말만 하지 않는다.
- 화면(스냅샷) 걸음은 뺀다. 사람이 볼 것은 찾기·열기·읽기·만들기다. 뺐다는 사실은 남긴다.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench" / "browser_agents"))

import doc_form  # noqa: E402
from alture_jarvis.evidence import numbers_claimed_in  # noqa: E402

DB = Path("C:/RoboMetaFit/tools/alture-jarvis/data/jarvis.db")
OUT = ROOT / "ui" / "src" / "setup" / "demoReplay.json"

_KIND = {
    "browser_search": "search", "browser_site_search": "search",
    "browser_open": "open", "browser_open_result": "open",
    "browser_extract": "read", "browser_read": "read",
    "local_write_document": "write",
}
_LABEL = {
    "search": "뉴스를 찾습니다",
    "open": "페이지를 엽니다",
    "read": "기사를 읽습니다",
    "write": "워드 문서를 만듭니다",
}


def _short(text: str, limit: int = 46) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main(prefix: str) -> None:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    row = conn.execute(
        "select id, payload_json, result_json, started_at, finished_at from jobs where id like ?",
        (prefix + "%",),
    ).fetchone()
    if not row:
        raise SystemExit("그 잡이 없다")
    job_id, payload, result, started, finished = row
    prompt = json.loads(payload).get("prompt", "")
    trace = json.loads(result)["agent_trace"]
    evidence = {int(e.get("step") or 0): float(e.get("created_at") or 0) for e in trace.get("evidence") or []}

    beats = []
    written: Path | None = None
    skipped = 0
    for index, step in enumerate(trace["steps"], start=1):
        kind = _KIND.get(str(step.get("tool") or ""))
        if not kind or not step.get("ok"):
            skipped += 1
            continue
        ev = step.get("evidence") or {}
        at = round(max(0.0, (evidence.get(index) or started) - started), 1)
        if kind == "write":
            written = Path(str(ev.get("output_path") or ev.get("path") or ""))
            detail = written.name
        elif kind == "search":
            detail = _short(str((step.get("arguments") or {}).get("query") or ""))
        else:
            host = (urlsplit(str(ev.get("url") or "")).hostname or "").removeprefix("www.")
            detail = _short(str(ev.get("title") or "")) or host
        beats.append({"at": at, "kind": kind, "label": _LABEL[kind], "detail": detail})

    if not written or not written.exists():
        raise SystemExit("이 판은 파일을 만들지 않았다 — 되감기로 쓰지 않는다")

    table = doc_form.read(written)["table"]
    head = [c.lower() for c in table[0]]

    def col(*words: str) -> int:
        return next((i for i, h in enumerate(head) if any(w in h for w in words)), -1)

    ti, pi = col("제목", "기사"), col("언론", "매체", "출처")
    rows = [
        {"title": _short(r[ti]) if ti >= 0 else "", "press": r[pi] if pi >= 0 else "", "host": ""}
        for r in table[1:4]
    ]

    form = doc_form.check(written, want_ext=(".docx",), table_task=True, url_wanted=True, trace=trace)
    text = doc_form.read(written)["text"]
    values = len(numbers_claimed_in(text)) + len(doc_form._URL.findall(text))
    missing = len(form["unsupported"])
    check = (
        f"문서 속 숫자·주소 {values}개가 전부 실제로 읽은 페이지에 있었습니다"
        if not missing
        else f"문서 속 숫자·주소 {values}개 중 {missing}개는 읽은 페이지에서 못 찾았습니다"
    )
    beats.append({"at": round(finished - started, 1), "kind": "check", "label": "만든 문서를 읽은 기사와 대조합니다", "detail": ""})

    OUT.write_text(json.dumps({
        "job": job_id[:8],
        "recorded_on": __import__("time").strftime("%Y년 %m월 %d일", __import__("time").localtime(started)),
        "prompt": prompt,
        "real_seconds": round(finished - started, 1),
        "skipped_steps": skipped,
        "beats": beats,
        "result": {"file": written.name, "rows": rows, "check": check},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(OUT, "| 걸음", len(beats), "| 뺀 걸음", skipped, "|", check)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
