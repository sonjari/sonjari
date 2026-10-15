"""하네스 한·영 동등성 — 같은 뜻의 한국어·영어 요청이 **같은 요구·같은 스킬**을 뽑는가 (2026-09-23 밤, 영어판 P1 의 눈금).

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/measure_language_parity.py [--verbose]

재는 것
  plan   `plan.extract(prompt, must_observe=True)` 의 (kind, target) 집합이 같은가
  skill  `skills.match_skills(prompt)` 의 이름 목록이 같은가(한국어 쪽에 붙은 쌍만 분모)

첫 측정(10쌍): plan 2/10 · skill 0/5. 목표: plan ≥ 90% · skill ≥ 90% — **그리고 한국어 결과는 한 개도 안 바뀔 것**
(바꾸기 전후로 실제 요청 1,181개의 `extract` 결과를 비교하라 — 부정문·미리보기 고칠 때 쓴 방법, 인수인계 §10-4).

쌍은 **실제 요청에서** 늘린다(운영 DB `jobs.payload_json` 의 prompt). 지어낸 문장만으로 맞추면 벤치에 과적합한다.
영어 쪽에서 새로 걸리는 것(오탐)도 같이 볼 것 — 영어 낱말표를 넓히면 영어 잡담이 행위 요구로 잡힐 수 있다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from alture_jarvis.plan import extract  # noqa: E402
from alture_jarvis.skills import match_skills  # noqa: E402

from language_pairs import PAIRS  # noqa: E402 — 쌍은 실제 요청에서 고른 것(scripts/language_pairs.py)


def _plan(prompt: str) -> list[tuple[str, str]]:
    return sorted({(r.kind, str(r.target)) for r in extract(prompt, must_observe=True)})


def _route(prompt: str) -> dict[str, bool]:
    """라우터가 이 요청을 어디로 보내는가 — 계획이 같아도 갈래가 다르면 영어 사용자는 다른 도구를 받는다."""
    from alture_jarvis import agent, plan
    from alture_jarvis.runtime import JarvisRuntime as R

    return {
        "web": R._requires_web_research(prompt),
        "named": R._requires_named_source(prompt),
        "local": R._requires_local_inspection(prompt),
        "blog": R._requires_naver_blog(prompt),
        "artifact": plan.wants_an_artifact(prompt),
        "code": plan.wants_code(prompt),
        "sandbox": plan.wants_the_sandbox(prompt),
        "count": plan.wants_a_count(prompt),
        "sourced": bool(agent.named_sources(prompt)),
    }


def _skills(prompt: str) -> list[str]:
    return [name for name, _hits in match_skills(prompt)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    plan_same = skill_same = skill_total = route_same = skill_extra = 0
    for ko, en in PAIRS:
        pk, pe = _plan(ko), _plan(en)
        sk, se = _skills(ko), _skills(en)
        plan_same += pk == pe
        rk, re_ = _route(ko), _route(en)
        route_diff = [key for key in rk if rk[key] != re_[key]]
        route_same += not route_diff
        if sk:
            skill_total += 1
            skill_same += sk == se
        elif se:
            # 한국어엔 안 붙는데 영어에만 붙은 스킬 — 동등성 분모엔 안 들어가지만 오탐이다. 따로 센다.
            skill_extra += 1
            print("EXTRA " + en[:70])
            print("   skill en only:", se[:3])
        if args.verbose or pk != pe or (sk and sk != se) or route_diff:
            print(("SAME " if pk == pe else "DIFF ") + en[:70])
            if pk != pe:
                print("   plan ko:", pk, "\n   plan en:", pe)
            if sk and sk != se:
                print("   skill ko:", sk[:3], "| en:", se[:3])
            if route_diff:
                print("   route:", {key: (rk[key], re_[key]) for key in route_diff})
    print(f"\nplan parity {plan_same}/{len(PAIRS)} · skill parity {skill_same}/{skill_total} · route parity {route_same}/{len(PAIRS)} · English-only skills {skill_extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
