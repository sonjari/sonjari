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
        if stem.startswith("measure_"):
            # 이 PC 의 측정 폴더 모양 — 조건과 판 번호가 **폴더 이름**에 있다(`9b_32k_links_off_r1/measure_….json`).
            folder = row["file"].rsplit("/", 2)[-2] if row["file"].count("/") >= 1 else ""
            stem = "kit__" + re.sub(r"_r\d+$", "", folder)
        key = (row["card"], row["model"], row["window"], row["build"], stem)
        group = groups.setdefault(key, {**row, "per_round": [], "causes": {}, "secs": [], "files": []})
        group["per_round"] += row["per_round"]
        for name, count in row["causes"].items():
            group["causes"][name] = group["causes"].get(name, 0) + count
        if isinstance(row["sec_median"], (int, float)):
            group["secs"].append(row["sec_median"])
        group["files"].append(row["file"])
    out = []
    for (_card, _model, _window, _build, stem), group in groups.items():
        # 조건 = 파일 이름의 마지막 묶음(「9b_32k_links_off」) — 같은 모델 · 창이라도 무엇을 바꿔 쟀는지 보이게.
        condition = stem.removeprefix("kit").strip("_").split("__")[-1] if stem.startswith("kit") else ""
        group["condition"] = condition.replace("_", " ") or "-"
        group["median"] = statistics.median(group["per_round"]) if group["per_round"] else None
        group["sec_median"] = statistics.median(group["secs"]) if group["secs"] else None
        group["file"] = group["files"][0] if len(group["files"]) == 1 else f"{group['files'][0].rsplit('/', 1)[0]}/…({len(group['files'])}개 파일)"
        out.append(group)
    return out


def _model_name(model: str) -> str:
    """허깅페이스에서 받은 모델은 태그 끝의 파일 이름이 이름이다(「…:Swift-…-IQ3_S-mtp.gguf」 → 「Swift-…-IQ3_S-mtp」)."""
    if ".gguf" in model and ":" in model:
        return model.rsplit(":", 1)[-1].removesuffix(".gguf")
    return model


def render(rows: list[dict], *, link_prefix: str = "", suite: str = "") -> str:
    rows = _merged(rows)
    out = ["# 시험지 · Exam sheet (자동 생성 · generated)", "",
           "> 「얼마나 잘했나」를 우리 말이 아니라 기록으로. 진 판도 지우지 않는다.",
           "> How well it did — from the records, not our words. Runs that lost stay in.", "",
           "가격 조사 꾸러미(가게 셋 × 물건 셋 = 한 판 9줄 · 페이지와 칸이 모두 맞아야 한 줄)의 결과를 카드 · 모델 · 창 · 조건마다 옮겼다.",
           "손으로 쓰지 않았다 — `scripts/exam_sheet.py` 가 결과 파일의 `price_summary` 에서 뽑았다. 판이 셋 미만이면 「판이 적다」.", "",
           "*One fixed price-research kit (3 Korean shops × 3 products = 9 rows per round; a row counts only when every cell matches",
           "the page). Copied from each result file's `price_summary` by `scripts/exam_sheet.py` — not written by hand. Fewer than three",
           "rounds is marked 「판이 적다」 (few rounds). Cause labels are explained at the bottom.*", ""]
    if suite:
        out += [f"**회귀 시험 · Regression suite**: {suite}", ""]
    out += ["| 카드 | 모델 | 창 | 조건 | 카드에 올라간 몫 | 판별(9줄 만점) | 가운데 값 | 과제 시간(가운데) | 진 까닭(많은 순) | 판(빌드) | 결과 파일 |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in sorted(rows, key=lambda r: (r["card"], r["model"], r["window"])):
        causes = " · ".join(f"{name} {count}" for name, count in sorted(row["causes"].items(), key=lambda kv: -kv[1])[:3])
        rounds = ", ".join(str(score) for score in row["per_round"])
        few = " (판이 적다)" if len(row["per_round"]) < 3 else ""
        share = f"{float(row['on_card']) * 100:.0f}%" if isinstance(row["on_card"], (int, float)) else "?"
        sec = f"{row['sec_median']:.0f}초" if isinstance(row["sec_median"], (int, float)) else "?"
        target = row["files"][0] if len(row["files"]) == 1 else row["files"][0].rsplit("/", 1)[0] + "/"
        file_cell = f"[`{row['file']}`]({link_prefix}{target})" if link_prefix else f"`{row['file']}`"
        out.append(f"| {row['card']} | `{_model_name(row['model'])}` | {row['window'] // 1024}K | {row['condition']} | {share} | "
                   f"{rounds}{few} | {row['median']:g} | {sec} | {causes or '-'} | {row['build'] or '?'} | {file_cell} |")
    out += ["", "까닭 낱말: 온전 = 맞음 · 안 감 / 목록에서 못 엶 / 가려다 막힘 = 상품 페이지까지 못 감 · 열고 안 읽음 · "
            "읽고 잃음 = 읽고도 표에 못 옮김 · 잘못 읽음 · 표 없이 끝남 · 주소만 틀림.", "",
            "*Causes: 안 감 / 목록에서 못 엶 / 가려다 막힘 = never reached the product page · 열고 안 읽음 = opened but didn't read · "
            "읽고 잃음 = read it, then lost it from the window · 잘못 읽음 = misread · 표 없이 끝남 = ended without writing the sheet · "
            "주소만 틀림 = only the URL was wrong.*"]
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--out", default=str(ROOT / "generated_reports" / "exam_sheet_draft.md"))
    parser.add_argument("--link-prefix", default="", help="결과 파일 칸을 링크로 — 공개 저장소 안의 묶음 자리(예: measurements/2026-10-14/)")
    parser.add_argument("--suite", default="", help="회귀 시험 한 줄(예: 「2026-10-16 · 7,354 통과 · 실패 0」) — 실제로 돌린 결과만")
    args = parser.parse_args()
    rows = _rows([pathlib.Path(folder) for folder in args.folders])
    pathlib.Path(args.out).write_text(render(rows, link_prefix=args.link_prefix, suite=args.suite), encoding="utf-8")
    print(f"{len(rows)}줄 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
