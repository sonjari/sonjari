"""성장 기록(GROWTH.md) 초안을 시험 파일에서 뽑는다 (2026-10-15 · 전략안 §55-33).

「당신이 알려 준 실패는 손자리가 앞으로 영원히 통과해야 할 시험이 됩니다.」 — 그 말이 참인지 남이 확인할 수 있게,
손으로 쓰지 않고 **시험 파일의 이름 · 첫 줄 설명 · git 이 그 파일을 처음 들인 날**에서 뽑는다.

- 대상: `tests/test_*_MMDD.py` (실패한 날짜를 이름에 단 시험).
- 한 줄: 날짜 · 무엇을 지키나(설명 첫 줄) · 시험 파일 · git 에 들어온 날.
- ★ 역검증(10-15)에서 두 방향 다 어긋났다 — 날짜 단 시험에 새 기능이 섞이고, 실패에서 온 시험이 날짜 없이도 있다.
  그래서 표 머리는 「무엇이 실패했나」가 아니라 「무엇을 지키나」이고, 한계를 초안 맨 위에 적는다.
- ★ 눈금을 먼저 의심한다: 이름의 날짜와 git 에 들어온 날이 사흘 넘게 다르면 「날짜 어긋남」으로 따로 모은다(이름이 거짓말일 수 있다).
- 이름 · 신상은 싣지 않는다 — 설명 첫 줄이 공개본 내보내기(`scripts/export_public.py`)의 금지 목록(FORBIDDEN)에 걸리면
  그 줄을 「(설명에 공개 금지 낱말 — 공개 전 손볼 것)」으로 바꾼다.

    python scripts/growth_ledger.py [--out 경로]
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_DATED = re.compile(r"^test_.+_(\d{2})(\d{2})\.py$")


def _first_line(path: pathlib.Path) -> str:
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    except (SyntaxError, UnicodeDecodeError):
        return ""
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return ""


_ADDED: dict[str, dt.date] | None = None


def _added_on(path: pathlib.Path) -> dt.date | None:
    """git 이 그 시험 파일을 처음 들인 날 — `tests/` 의 추가 기록을 **한 번만** 읽어 둔다(파일마다 부르면 몇 분 걸렸다)."""
    global _ADDED
    if _ADDED is None:
        done = subprocess.run(["git", "log", "--diff-filter=A", "--format=@%as", "--name-only", "--", "tests"],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        _ADDED, day = {}, None
        for line in done.stdout.splitlines():
            line = line.strip()
            if line.startswith("@"):
                day = dt.date.fromisoformat(line[1:])
            elif line and day:
                _ADDED[pathlib.PurePosixPath(line).name] = day  # 기록은 새것부터 — 덮어써서 가장 처음 들인 날이 남는다
    return _ADDED.get(path.name)


def _forbidden() -> list:
    """공개본 내보내기(`scripts/export_public.py`)의 금지 목록 그대로 — 사람 이름 · 신상 · 남의 이름."""
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("export_public", ROOT / "scripts" / "export_public.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return [pattern for _label, pattern in getattr(module, "FORBIDDEN", [])]
    except Exception:  # noqa: BLE001 — 못 읽으면 설명을 싣지 않는 쪽으로 간다
        return [re.compile(r".")]


def build() -> tuple[list[dict], list[dict]]:
    forbidden = _forbidden()
    rows, odd = [], []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        match = _DATED.match(path.name)
        if not match:
            continue
        month, day = int(match.group(1)), int(match.group(2))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        added = _added_on(path)
        year = added.year if added else 2026
        try:
            named = dt.date(year, month, day)
        except ValueError:
            continue
        line = _first_line(path)
        if any(pattern.search(line) for pattern in forbidden):
            line = "(설명에 공개 금지 낱말 — 공개 전 손볼 것)"
        row = {"date": named, "what": line, "test": path.name, "added": added}
        rows.append(row)
        if added and abs((added - named).days) > 3:
            odd.append(row)
    rows.sort(key=lambda row: (row["date"], row["test"]))
    return rows, odd


def render(rows: list[dict], odd: list[dict]) -> str:
    out = ["# 성장 기록 (초안 · 자동 생성)", "",
           "> 어떤 일을 하시든, 당신의 현장이 손자리의 선생입니다.",
           "> 당신이 알려 준 실패는 손자리가 앞으로 영원히 통과해야 할 시험이 됩니다.", "",
           f"날짜를 이름에 단 시험 {len(rows)}개. 손으로 쓰지 않았다 — `scripts/growth_ledger.py` 가 시험 파일에서 뽑았다.", "",
           "**이 표의 한계 (역검증 2026-10-15 · 공개 전에 사람이 볼 것)**",
           "- 날짜를 단 시험이 전부 실패에서 온 것은 아니다 — 새 기능의 시험도 섞여 있다(예: `test_needs_refine_receipt_1015.py`).",
           "- 실패에서 왔는데 날짜를 안 단 시험도 있다(예: `test_failed_site_search_points_at_the_recipe.py` · 2026-08-16 실사용 실패).",
           "- 그래서 「실패에서 온 시험」만 고르는 일은 낱말로 짐작하지 않고 사람이 한다.", "",
           "| 날짜 | 무엇을 지키나 | 시험 | git 에 들어온 날 |", "|---|---|---|---|"]
    for row in reversed(rows):
        what = row["what"].replace("|", "\\|") or "(설명 없음)"
        out.append(f"| {row['date']:%Y-%m-%d} | {what} | `{row['test']}` | {row['added'] or '?'} |")
    if odd:
        out += ["", f"## 날짜 어긋남 {len(odd)}개 — 이름의 날짜와 git 에 들어온 날이 사흘 넘게 다르다(공개 전 확인)", ""]
        out += [f"- `{row['test']}` — 이름 {row['date']} · 들어온 날 {row['added']}" for row in odd]
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "generated_reports" / "growth_ledger_draft.md"))
    args = parser.parse_args()
    rows, odd = build()
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(render(rows, odd), encoding="utf-8")
    print(f"{len(rows)}줄 · 날짜 어긋남 {len(odd)} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
