"""시험지(EXAM.md) 초안을 측정 기록에서 뽑는다 (2026-10-15 · 전략안 §55-33).

「얼마나 잘했나」를 우리 말이 아니라 기록으로 — 재는 꾸러미(`measure_kit`) 결과 파일(`kit__*.json` · `measure_*.json`)에서
카드 · 모델 · 창마다 판별 점수(9줄 만점)와 가운데 값 · 진 까닭을 그대로 옮긴다. **진 판도 지우지 않는다**(§12).

- 손으로 쓰지 않는다. 숫자는 결과 파일의 `price_summary` 그대로다.
- 결과 파일에 없는 숫자(「약」 · 「대략」)를 만들지 않는다. 판이 셋 미만이면 「판이 적다」고 같이 적는다.
- 사람 이름 · 경로 · 읽은 글은 결과 파일에 애초에 없다(꾸러미가 숫자와 예/아니오만 남긴다).

    python scripts/exam_sheet.py <측정 묶음 폴더 …> [--out 경로]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rows(folders: list[pathlib.Path]) -> list[dict]:
    rows = []
    for folder in folders:
        for path in sorted(folder.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            summary = data.get("price_summary") if isinstance(data, dict) else None
            if not isinstance(summary, dict) or not summary.get("per_round"):
                continue
            pc = data.get("pc") if isinstance(data.get("pc"), dict) else {}
            card = ((pc.get("cards") or [{}])[0] or {}).get("name", "")
            rows.append({
                "file": path.relative_to(folder.parent).as_posix(),
                "card": str(card).replace("NVIDIA GeForce ", ""),
                "model": str(pc.get("model") or "").replace(":latest", ""),
                "window": int(pc.get("window") or 0),
                "on_card": pc.get("on_card_share"),
                "per_round": list(summary.get("per_round") or []),
                "out_of": int(summary.get("out_of") or 9),
                "median": summary.get("median"),
                "causes": dict(summary.get("causes") or {}),
                "sec_median": summary.get("sec_median"),
                "build": str(pc.get("sonjari_build") or "")[:8],
            })
    return rows


def _merged(rows: list[dict]) -> list[dict]:
    """한 판씩 따로 쓴 파일(`…_r1__measure…` · `…_r2__…`)은 같은 조건이면 한 줄로 묶는다 — 판이 적어 보이지 않게."""
    groups: dict[tuple, dict] = {}
    for row in rows:
        stem = re.sub(r"_r\d+(?=__measure)", "", row["file"].rsplit("/", 1)[-1])
        stem = re.sub(r"__measure_\d{8}-\d{4}\.json$", "", stem)
        key = (row["card"], row["model"], row["window"], row["build"], stem)
        group = groups.setdefault(key, {**row, "per_round": [], "causes": {}, "secs": [], "files": []})
        group["per_round"] += row["per_round"]
        for name, count in row["causes"].items():
            group["causes"][name] = group["causes"].get(name, 0) + count
        if isinstance(row["sec_median"], (int, float)):
            group["secs"].append(row["sec_median"])
        group["files"].append(row["file"])
    out = []
    for group in groups.values():
        group["median"] = statistics.median(group["per_round"]) if group["per_round"] else None
        group["sec_median"] = statistics.median(group["secs"]) if group["secs"] else None
        group["file"] = group["files"][0] if len(group["files"]) == 1 else f"{group['files'][0].rsplit('/', 1)[0]}/…({len(group['files'])}개 파일)"
        out.append(group)
    return out


def render(rows: list[dict]) -> str:
    rows = _merged(rows)
    out = ["# 시험지 (초안 · 자동 생성)", "",
           "가격 조사 꾸러미(가게 셋 × 물건 셋 = 한 판 9줄 · 페이지와 칸이 모두 맞아야 한 줄)의 결과를 카드 · 모델 · 창마다 옮겼다.",
           "손으로 쓰지 않았다 — `scripts/exam_sheet.py` 가 결과 파일의 `price_summary` 에서 뽑았다. 진 판도 그대로다.", "",
           "| 카드 | 모델 | 창 | 카드에 올라간 몫 | 판별(9줄 만점) | 가운데 값 | 과제 시간(가운데) | 진 까닭(많은 순) | 판(빌드) | 결과 파일 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for row in sorted(rows, key=lambda r: (r["card"], r["model"], r["window"])):
        causes = " · ".join(f"{name} {count}" for name, count in sorted(row["causes"].items(), key=lambda kv: -kv[1])[:3])
        rounds = ", ".join(str(score) for score in row["per_round"])
        few = " (판이 적다)" if len(row["per_round"]) < 3 else ""
        share = f"{float(row['on_card']) * 100:.0f}%" if isinstance(row["on_card"], (int, float)) else "?"
        sec = f"{row['sec_median']:.0f}초" if isinstance(row["sec_median"], (int, float)) else "?"
        out.append(f"| {row['card']} | `{row['model']}` | {row['window'] // 1024}K | {share} | {rounds}{few} | {row['median']:g} | "
                   f"{sec} | {causes or '-'} | {row['build'] or '?'} | `{row['file']}` |")
    out += ["", "까닭 낱말: 온전 = 맞음 · 안 감 / 목록에서 못 엶 / 가려다 막힘 = 상품 페이지까지 못 감 · 열고 안 읽음 · "
            "읽고 잃음 = 읽고도 표에 못 옮김 · 잘못 읽음 · 표 없이 끝남 · 주소만 틀림."]
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--out", default=str(ROOT / "generated_reports" / "exam_sheet_draft.md"))
    args = parser.parse_args()
    rows = _rows([pathlib.Path(folder) for folder in args.folders])
    pathlib.Path(args.out).write_text(render(rows), encoding="utf-8")
    print(f"{len(rows)}줄 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
