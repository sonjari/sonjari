"""하네스(요청을 읽는 규칙)가 실제 요청에 내놓는 판정을 통째로 찍어 두고, 바꾼 뒤와 비교한다 (2026-09-23 밤, 영어판 P1).

    python scripts/harness_snapshot.py --save  before.json
    python scripts/harness_snapshot.py --compare before.json [--limit 40]

왜: 영어 낱말을 정규식에 더하면 **한국어 요청의 판정이 조용히 바뀔 수 있다**(부정문·미리보기를 고칠 때 이렇게 쟀다 —
인수인계 새벽2 §10-4). 계획(`plan.extract` 네 가지 조건)·라우터 판정·스킬·세부 판정을 전부 찍어서, 한국어 요청에서
**하나라도** 바뀌면 그 요청과 바뀐 칸을 보여 준다. 영어 요청은 따로 센다(거기서는 바뀌는 게 목적이다).

요청은 운영 DB(`C:\\RoboMetaFit\\tools\\alture-jarvis\\data\\jarvis.db`)의 `jobs.payload_json.prompt` 중 서로 다른 것 전부.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\jarvis.db")


def prompts() -> list[str]:
    con = sqlite3.connect(DB)
    seen: dict[str, None] = {}
    for (payload,) in con.execute("SELECT payload_json FROM jobs ORDER BY created_at DESC"):
        try:
            prompt = json.loads(payload or "{}").get("prompt") or ""
        except Exception:  # noqa: BLE001 — 깨진 행은 건너뛴다
            continue
        prompt = " ".join(str(prompt).split())
        if prompt:
            seen.setdefault(prompt, None)
    return list(seen)


def verdicts(prompt: str) -> dict[str, object]:
    from alture_jarvis import agent, plan, runtime, skills
    from alture_jarvis.task_contract import compile_task_contract

    rt = runtime.JarvisRuntime if hasattr(runtime, "JarvisRuntime") else None

    def reqs(**kwargs: object) -> list[str]:
        return sorted(f"{r.kind}|{r.target}|{r.grounding_required}|{r.source_scope}" for r in plan.extract(prompt, **kwargs))

    out: dict[str, object] = {
        "plan": reqs(),
        "plan_observe": reqs(must_observe=True),
        "plan_named": reqs(has_named_source=True),
        "plan_both": reqs(has_named_source=True, must_observe=True),
        "labels": [r.label for r in plan.extract(prompt, must_observe=True)],
        "artifact": plan.wants_an_artifact(prompt),
        "exts": list(plan.artifact_extensions(prompt)),
        "code": plan.wants_code(prompt),
        "code_action": plan.wants_code_action(prompt),
        "count": plan.wants_a_count(prompt),
        "verify": plan.wants_verification(prompt),
        "compute": plan.wants_a_computation(prompt),
        "sandbox": plan.wants_the_sandbox(prompt),
        "forbids": plan.forbids_writes(prompt),
        "prohibit_scope": plan.write_prohibition_scope(prompt),
        "work": plan.asked_for_work(prompt),
        "continuation": plan.is_continuation(prompt),
        "named": agent.named_sources(prompt),
        "particulars": agent.asks_for_particulars(prompt),
        "inhouse": agent.asks_inhouse_data(prompt),
        "social": runtime._is_social_remark(prompt),
        "sharing": runtime._is_sharing_not_request(prompt),
        "skills": [name for name, _hits in skills.match_skills(prompt)],
    }
    if rt is not None:
        for name in ("_requires_web_research", "_requires_named_source", "_requires_local_inspection",
                     "_requires_naver_blog", "_requires_person_search", "_requires_code_workspace_inspection",
                     "_requires_fresh_camera", "_requires_camera_control"):
            fn = getattr(rt, name, None)
            if fn is not None:
                out[name] = bool(fn(prompt))
    try:
        contract = compile_task_contract(prompt)
        out["contract"] = repr(contract)[:4000]
    except Exception as exc:  # noqa: BLE001 — 계약 컴파일 실패도 판정의 일부다
        out["contract"] = f"error:{type(exc).__name__}"
    return out


def snapshot() -> dict[str, dict[str, object]]:
    return {prompt: verdicts(prompt) for prompt in prompts()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    ap.add_argument("--compare")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()
    now = snapshot()
    if args.save:
        Path(args.save).write_text(json.dumps(now, ensure_ascii=False), encoding="utf-8")
        print(f"saved {len(now)} prompts → {args.save}")
    if args.compare:
        before = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        changed_ko: list[tuple[str, list[str]]] = []
        changed_en = 0
        for prompt, verdict in now.items():
            old = before.get(prompt)
            if old is None:
                continue
            diff = [key for key in sorted(set(verdict) | set(old)) if verdict.get(key) != old.get(key)]
            if not diff:
                continue
            if re.search(r"[가-힣]", prompt):
                changed_ko.append((prompt, diff))
            else:
                changed_en += 1
        print(f"compared {len(now)} prompts · Korean changed {len(changed_ko)} · non-Korean changed {changed_en}")
        for prompt, diff in changed_ko[: args.limit]:
            print(f"\n• {prompt[:120]}")
            for key in diff:
                print(f"    {key}: {str(before[prompt].get(key))[:160]}\n      → {str(now[prompt].get(key))[:160]}")
        return 1 if changed_ko else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
