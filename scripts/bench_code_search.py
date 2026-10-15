"""「어디를 고쳐야 하나」를 찾는 능력을 잰다.

    python scripts/bench_code_search.py                 # 지금 색인
    python scripts/bench_code_search.py --with-scout    # 색인 + 3060 정찰기

코드를 고치지 않으므로 초 단위로 돈다. 색인을 바꿀 때마다 개선폭이 바로 숫자로
나오게 하는 것이 목적이다.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from alture_jarvis.code_index import CodeIndex  # noqa: E402
from code_search_bench_cases import CASES, verify_ground_truth  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def rank_of_answer(paths: list[str], answers: tuple[str, ...]) -> int:
    """정답이 몇 번째에 있나. 없으면 0."""
    wanted = {answer.replace("\\", "/") for answer in answers}
    for position, path in enumerate(paths, 1):
        if str(path).replace("\\", "/") in wanted:
            return position
    return 0


def score(ranks: list[int]) -> dict[str, float]:
    found = [rank for rank in ranks if rank]
    total = len(ranks) or 1
    return {
        "recall@1": round(sum(1 for r in ranks if r == 1) / total, 4),
        "recall@5": round(sum(1 for r in ranks if 1 <= r <= 5) / total, 4),
        "recall@10": round(sum(1 for r in ranks if 1 <= r <= 10) / total, 4),
        "mrr": round(sum(1 / r for r in found) / total, 4),
        "median_rank": statistics.median(found) if found else 0,
        "missed": sum(1 for r in ranks if not r),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument("--with-scout", action="store_true")
    parser.add_argument("--json", default="")
    parser.add_argument("--label", default="lexical")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    problems = verify_ground_truth(repo)
    if problems:
        # 낡은 정답으로 낸 점수는 점수가 아니다.
        for line in problems:
            print("  " + line)
        raise SystemExit("정답이 낡았다 — 고치기 전에는 재지 않는다")

    index = CodeIndex(ROOT / "outputs" / "code_search_bench")
    scout = None
    if args.with_scout:
        import os

        from alture_jarvis.code_scout import CodeScout
        from alture_jarvis.config import JarvisConfig, load_env_file

        # 정찰기 설정은 런타임 .env 에 산다. from_env() 만 부르면 프로세스
        # 환경에 없어서 "꺼져 있다"로 읽힌다.
        runtime_env = Path("C:/RoboMetaFit/tools/alture-jarvis/.env")
        for key, value in load_env_file(runtime_env).items():
            os.environ.setdefault(key, value)
        scout = CodeScout(JarvisConfig.from_env())
        if not scout.enabled:
            raise SystemExit("정찰기가 꺼져 있다")

    rows: list[dict[str, object]] = []
    print(f"고정 분모 {len(CASES)}건 · {args.label}")
    for case in CASES:
        started = time.time()
        result = index.query(repo, case.query, max_results=args.max_results)
        matches = (result.get("repo_map") or {}).get("matches") or []
        paths = [str(item.get("path") or "") for item in matches]
        stage = "index"
        if scout is not None:
            try:
                report = scout.analyze(case.query, result)
                ordered = list(report.get("priority_files") or [])
                ordered += [p for p in paths if p not in ordered]
                paths = ordered
                stage = "index+scout"
            except Exception as exc:  # 정찰기 실패는 색인 순위로 폴백
                stage = f"index(scout_failed:{type(exc).__name__})"
        rank = rank_of_answer(paths, case.answers)
        rows.append(
            {
                "key": case.key,
                "tier": case.tier,
                "rank": rank,
                "stage": stage,
                "elapsed_sec": round(time.time() - started, 2),
                "top3": paths[:3],
            }
        )
        mark = "✔" if rank and rank <= 5 else ("~" if rank else "✘")
        print(f"  {mark} {case.key:24s} rank={rank or '-':>3}  {case.tier}")

    overall = score([int(r["rank"]) for r in rows])
    by_tier = {
        tier: score([int(r["rank"]) for r in rows if r["tier"] == tier])
        for tier in sorted({str(r["tier"]) for r in rows})
    }
    print("─" * 68)
    print(
        f"recall@1 {overall['recall@1']:.1%} · @5 {overall['recall@5']:.1%} · "
        f"@10 {overall['recall@10']:.1%} · MRR {overall['mrr']:.3f} · 못 찾음 {overall['missed']}"
    )
    for tier, value in by_tier.items():
        print(f"   {tier:12s} @5 {value['recall@5']:.1%}  MRR {value['mrr']:.3f}  못 찾음 {value['missed']}")

    payload = {
        "label": args.label,
        "measured_at": time.time(),
        "repo": str(repo),
        "total": len(CASES),
        "overall": overall,
        "by_tier": by_tier,
        "rows": rows,
    }
    if args.json:
        target = Path(args.json).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"기록: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
