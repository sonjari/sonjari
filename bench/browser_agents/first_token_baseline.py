"""첫 글자 대기 — 지금 그대로의 판(옛 판) 기준 재기 (2026-10-22 · `docs/측정계획_첫글자대기_2026-10-21.ko.md`).

1단계 이름표(`model_calls.jsonl` 의 purpose · prefix_kept · cut)가 붙은 판을 바로 쌓아, 2단계 견주기의 「옛 판」 칸으로 쓴다.
과제와 채점은 `ab_before_after.py`(09-26) 것을 그대로 빌린다. 한 번에 한 판, 과제를 돌아가며.
판마다 시작 · 끝 시각을 적는다 — 부르기 기록에는 판 번호가 없어서, 시각으로 판의 부르기를 가른다.

    python first_token_baseline.py <label> <rounds> [과제,과제]

진 판도 지우지 않는다 — results/first_token_wait/<label>.jsonl
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import ab_before_after as AB  # noqa: E402

OUT = HERE / "results" / "first_token_wait"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8091"
TOKEN_FILE = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token")
#: 시킨 개수가 있는 목록 과제 — 마지막 정리 · 다시 부르기가 잘 일어나는 쪽(뒤집기 자리를 보려고).
DEFAULT_TASKS = ("saramin", "kyobo", "danawa", "wishket")


def main() -> None:
    label, rounds = sys.argv[1], int(sys.argv[2])
    wanted = tuple(sys.argv[3].split(",")) if len(sys.argv) > 3 else DEFAULT_TASKS
    tasks = [task for task in AB.TASKS if task[0] in wanted]
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    out = OUT / f"{label}.jsonl"
    for round_no in range(1, rounds + 1):
        for task in tasks:
            started = time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                result = AB.run_arm("now", BASE, token, task)
            except Exception as exc:  # noqa: BLE001 — 한 판 실패가 측정을 죽이면 안 된다
                result = {"arm": "now", "task": task[0], "status": "bench_error", "error": str(exc)[:300], "ok": False}
            result.update(round=round_no, started=started, ended=time.strftime("%Y-%m-%d %H:%M:%S"))
            with out.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"r{round_no} {task[0]:10} ok={result.get('ok')} items={result.get('items')} "
                  f"t={result.get('elapsed_sec')} steps={result.get('steps')} status={result.get('status')}", flush=True)


if __name__ == "__main__":
    main()
