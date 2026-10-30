"""실제 요청 대조 — `plan.py` 를 고치기 전 · 후로 운영 요청 문장에 돌려, **뜻밖에 바뀐 요청**을 표로 낸다.

사용법
    python scripts/plan_request_diff.py                  # 기준 = HEAD 의 plan.py  대  지금 작업 트리의 plan.py
    python scripts/plan_request_diff.py <커밋> --show 80  # 기준 커밋을 고르고 표를 80줄까지
    python scripts/plan_request_diff.py --db <jarvis.db 경로> --limit 500   # 다른 DB · 앞 500개만

이 도구는 **손자리 자기 저장소에서 plan.py(요청 읽기)를 고칠 때** 쓴다. 운영 DB(`jobs.payload_json` 의 `prompt`)에 쌓인 실제 요청이
재료라서 사용자의 저장소에는 그런 기록이 없다 — 그래서 하네스에 붙이지 않았다(`regression_vs_start.py` 는 사용자 저장소의 시험을 쓴다).

하는 일
    - 운영 DB 는 **읽기 전용**으로 연다(`mode=ro`). 서로 다른 요청 문장을 뽑는다.
    - 기준 커밋의 `src` 는 `git archive` 로 임시 폴더에 풀어 돈다 — 작업 트리는 건드리지 않는다(worktree · stash · checkout 을 쓰지 않는다).
    - 두 쪽에서 `plan.artifact_extensions`(만들 파일 형식)와 `plan.extract`(요구의 종류 · 읽을 범위)를 돌려 견주고, 달라진 요청만 낸다.
    - 개인 정보: 출력에는 요청 **전문 대신 앞 60자 + 해시**만 나간다.

2026-10-28 재생 측정 261fbfe2 의 채점기(`probe_corpus.py` · `grade.py` 의 `run_corpus`)를 일반 도구로 옮긴 것이다.
그 측정에서 세 판 중 둘이 운영 요청 2,672개 가운데 7개 · 53개를 뜻밖에 바꿨고, 저장소 시험은 그것을 못 잡았다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

#: 한쪽 코드(PYTHONPATH 의 src)로 요청마다 만들 파일 형식 · 요구의 (종류, 읽을 범위)를 낸다 — `probe_corpus.py` 와 같다. 읽기만 한다.
PROBE = r'''
import hashlib, json, sys
from alture_jarvis import plan
prompts = json.load(open(sys.argv[1], encoding="utf-8"))
out = {}
for p in prompts:
    try:
        ext = list(plan.artifact_extensions(p))
    except Exception as e:
        ext = "ERR:" + repr(e)[:80]
    try:
        reqs = plan.extract(p, own_from=p, has_named_source=True)
        scope = [list(x) for x in sorted({(r.kind, r.source_scope) for r in reqs if r.source_scope})]
        kinds = sorted({r.kind for r in reqs})
    except Exception as e:
        scope = kinds = "ERR:" + repr(e)[:80]
    out[hashlib.sha1(p.encode("utf-8")).hexdigest()[:12]] = {"ext": ext, "scope": scope, "kinds": kinds}
json.dump({"module": plan.__file__, "n": len(out), "rows": out}, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
'''

DEFAULT_DB = Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\jarvis.db")
SHOW_CHARS = 60


def key_of(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]


def short(prompt: str, limit: int = SHOW_CHARS) -> str:
    """출력용 — 줄바꿈을 없애고 앞 `limit` 자만. 전문은 어디에도 찍지 않는다."""
    flat = " ".join(prompt.split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def read_prompts(db: Path, limit: int = 0) -> list[str]:
    """운영 DB 의 서로 다른 요청 문장들. **읽기 전용**으로 연다 — 쓰기 시도는 실패한다."""
    uri = "file:" + Path(db).resolve().as_posix() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        seen: dict[str, None] = {}
        for (raw,) in connection.execute("select payload_json from jobs"):
            try:
                prompt = (json.loads(raw) or {}).get("prompt")
            except (TypeError, ValueError):
                continue
            if isinstance(prompt, str) and prompt.strip():
                seen.setdefault(prompt, None)
    finally:
        connection.close()
    prompts = list(seen)
    return prompts[:limit] if limit > 0 else prompts


def _git(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def archive_src(project: Path, commit: str, dest: Path) -> Path:
    """`commit` 의 `src` 를 `dest` 에 푼다(`git archive`). 작업 폴더는 읽기만 한다. 풀린 `src` 를 돌려준다."""
    archive = dest / "base.zip"
    done = _git(project, "archive", "--format=zip", "-o", str(archive), commit, "src")
    if done.returncode != 0:
        raise SystemExit("git archive 실패 (" + commit + "): " + (done.stderr or b"").decode("utf-8", "replace").strip()[:300])
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(dest)
    archive.unlink()
    return dest / "src"


def probe(src: Path, prompts_file: Path, work: Path, tag: str) -> dict[str, Any]:
    """`src` 를 PYTHONPATH 맨 앞에 두고 요청마다 판정을 돈다. 우리 설정(JARVIS_*)은 넘기지 않는다."""
    script, out = work / f"probe_{tag}.py", work / f"out_{tag}.json"
    script.write_text(PROBE, encoding="utf-8")
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("JARVIS_")}
    environment["PYTHONPATH"] = os.pathsep.join([str(src), environment.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    done = subprocess.run([sys.executable, "-X", "utf8", str(script), str(prompts_file), str(out)], cwd=str(work), env=environment,
                          capture_output=True, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode != 0 or not out.exists():
        raise SystemExit(f"{tag} 쪽 판정 실패: " + (done.stderr or b"").decode("utf-8", "replace")[-500:])
    data = json.loads(out.read_text(encoding="utf-8"))
    inside = str(Path(data["module"]).resolve()).lower().startswith(str(Path(src).resolve()).lower())
    if not inside:
        raise SystemExit(f"{tag} 쪽이 엉뚱한 plan.py 를 불렀다: {data['module']} (기대: {src} 아래)")
    return data


def changed_rows(base: dict[str, Any], now: dict[str, Any], prompts: dict[str, str]) -> list[dict[str, Any]]:
    """두 쪽의 판정이 다른 요청만. 만들 형식 · 요구의 (종류, 범위) · 요구 종류 중 하나라도 다르면 바뀐 것이다."""
    rows = []
    for key, after in now["rows"].items():
        before = base["rows"].get(key)
        if before is None or before == after:
            continue
        rows.append({"key": key, "prompt": prompts.get(key, ""), "before": before, "after": after})
    return rows


def _cell(before: Any, after: Any) -> str:
    return "(같음)" if before == after else f"{before} -> {after}"


def format_table(rows: list[dict[str, Any]], *, total: int, base_label: str, seconds: float, show: int = 50) -> str:
    lines = [
        f"기준 {base_label} 대 지금 작업 트리 · 서로 다른 요청 {total}개 · 바뀐 요청 {len(rows)}개 · 걸린 시간 {seconds:.1f}초",
    ]
    if not rows:
        lines.append("바뀐 요청 없음.")
        return "\n".join(lines)
    lines += ["", "| # | 해시 | 요청(앞 60자) | 만들 형식 | 읽을 범위 | 요구 종류 |", "|---|---|---|---|---|---|"]
    for index, row in enumerate(rows[:show], 1):
        before, after = row["before"], row["after"]
        lines.append(
            f"| {index} | {row['key'][:8]} | {short(row['prompt']).replace('|', '/')} | {_cell(before['ext'], after['ext'])} | "
            f"{_cell(before['scope'], after['scope'])} | {_cell(before['kinds'], after['kinds'])} |"
        )
    if len(rows) > show:
        lines.append(f"\n… 그 밖에 {len(rows) - show}개 더 (--show 로 늘린다)")
    return "\n".join(lines)


def run(project: Path, commit: str, db: Path, *, limit: int = 0, show: int = 50) -> tuple[list[dict[str, Any]], int, str]:
    began = time.time()
    prompts = read_prompts(db, limit)
    by_key = {key_of(p): p for p in prompts}
    resolved = _git(project, "rev-parse", "--short", commit)
    if resolved.returncode != 0:
        raise SystemExit("기준 커밋을 찾을 수 없다: " + commit)
    label = f"{commit}({resolved.stdout.decode().strip()})" if commit != resolved.stdout.decode().strip() else commit
    with tempfile.TemporaryDirectory(prefix="sonjari-plandiff-") as folder:
        work = Path(folder)
        prompts_file = work / "prompts.json"
        prompts_file.write_text(json.dumps(prompts, ensure_ascii=False), encoding="utf-8")
        base_src = archive_src(project, commit, work)
        base = probe(base_src, prompts_file, work, "base")
        now = probe(Path(project) / "src", prompts_file, work, "now")
    rows = changed_rows(base, now, by_key)
    return rows, len(prompts), format_table(rows, total=len(prompts), base_label=label, seconds=time.time() - began, show=show)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="plan.py 를 고치기 전 · 후로 운영 요청에 돌려 뜻밖에 바뀐 요청을 낸다.")
    parser.add_argument("commit", nargs="?", default="HEAD", help="기준 커밋(기본 HEAD)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="운영 jobs DB(읽기 전용으로 연다)")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parent.parent, help="alture-jarvis 폴더(src 가 든 곳)")
    parser.add_argument("--limit", type=int, default=0, help="앞에서 이만큼만(0 = 전부)")
    parser.add_argument("--show", type=int, default=50, help="표에 낼 줄 수")
    parser.add_argument("--strict", action="store_true", help="바뀐 요청이 있으면 종료 값 1")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rows, _total, table = run(args.project, args.commit, args.db, limit=args.limit, show=args.show)
    print(table)
    return 1 if (args.strict and rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
