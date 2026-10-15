"""A2 「분야 끔」 이력서 과제 3판 다시 재기 — 09-15 이름표 결과 덮어쓰기로 유실된 몫.

curation_bench 의 절차를 그대로 쓰되 요약 파일(curation_2026-09-15.json)의 M4 칸은 건드리지 않는다.
"""

from __future__ import annotations

import json

import curation_bench as cb


def main() -> None:
    state = cb.save_state()
    try:
        cb.api("PATCH", "/v1/settings", {"values": {"skills_domains": [], "skills_route_enabled": True}})
        cb.run_bench("a2_domains_off", 3, "resume_skill")
    finally:
        cb.api("POST", "/v1/skills/domains", {"domains": state["domains"]})
        cb.restore_state(state)
    out = cb.RESULTS / "curation_2026-09-15.json"
    summary = json.loads(out.read_text(encoding="utf-8"))
    summary["runs"]["a2_domains_off"] = cb.summarize(cb.RESULTS / "multiturn_a2_domains_off.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    cb.log(f"a2_domains_off resume_skill rerun done -> {summary['runs']['a2_domains_off']}")


if __name__ == "__main__":
    main()
