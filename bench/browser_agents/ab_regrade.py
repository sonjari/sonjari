"""ab_before_after 결과를 **전체 답**으로 다시 채점한다 (2026-09-26).

ab_0926 앞 판들은 채점기가 잡을 못 찾아 답 앞 180자로 개수를 셌다(`/v1/jobs` 목록에 prompt 가 없었다). 판 기록에
job_id 도 없어서, 백엔드마다 잡을 시간순으로 줄 세워 판과 짝짓고 **걸린 시간이 맞는지로 짝을 검증**한다(0.5초 안).
원본 jsonl 은 그대로 두고 `<label>.regraded.jsonl` 로 쓴다 — 진 판도 지우지 않는다.

    python ab_regrade.py <label> <before_base> <before_token_file> <after_base> <after_token_file>
"""

from __future__ import annotations

import json
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import bench_research_tasks as B  # noqa: E402
from ab_before_after import OUT, TASKS, grade, summarize  # noqa: E402


def jobs_in_order(base: str, token: str) -> list[dict]:
    B.BASE = base
    listed = B._get("/v1/jobs?limit=200", token)
    listed = listed if isinstance(listed, list) else listed.get("jobs") or []
    return sorted(listed, key=lambda job: float(job.get("created_at") or 0))


def main() -> None:
    label = sys.argv[1]
    arms = {"before": (sys.argv[2], pathlib.Path(sys.argv[3]).read_text(encoding="utf-8").strip()),
            "after": (sys.argv[4], pathlib.Path(sys.argv[5]).read_text(encoding="utf-8").strip())}
    rows = [json.loads(line) for line in (OUT / f"{label}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    tasks = {task[0]: task for task in TASKS}
    out: list[dict] = []
    for arm, (base, token) in arms.items():
        mine = [row for row in rows if row.get("arm") == arm]
        jobs = jobs_in_order(base, token)
        # 판 기록의 걸린 시간과 맞는 잡을 뒤에서부터 짝짓는다(벤치 앞의 시범·데모 잡은 남는다).
        details = []
        for job in jobs:
            B.BASE = base
            detail = B._get(f"/v1/jobs/{job['id']}", token)
            began, ended = float(detail.get("started_at") or 0), float(detail.get("finished_at") or 0)
            details.append((round(ended - began, 1) if began and ended else None, detail))
        cursor = len(details)
        for row in reversed(mine):
            match = None
            for index in range(cursor - 1, -1, -1):
                took, detail = details[index]
                if took is not None and abs(took - float(row.get("elapsed_sec") or -1)) <= 0.5:
                    match, cursor = detail, index
                    break
            fixed = dict(row)
            if match is None:
                fixed["regrade"] = "no_match"
            else:
                fixed["job_id"] = match.get("id")
                fixed["answer"] = str((match.get("result") or {}).get("answer") or "")
                fixed.update(grade(tasks[row["task"]], fixed))
                fixed["regrade"] = "full_answer"
            out.append(fixed)
    out.sort(key=lambda row: (row.get("round", 0), [t[0] for t in TASKS].index(row["task"]), row.get("at", "")))
    target = OUT / f"{label}.regraded.jsonl"
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in out), encoding="utf-8")
    for row in out:
        print(f"r{row.get('round')} {row['task']:12} {row['arm']:6} ok={row.get('ok')} items={row.get('items')} "
              f"t={row.get('elapsed_sec')} {row.get('regrade')}")
    summarize(target)


if __name__ == "__main__":
    main()
