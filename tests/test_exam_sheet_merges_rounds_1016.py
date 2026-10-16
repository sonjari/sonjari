"""시험지(EXAM.md)는 같은 조건을 여러 번 돌린 판을 한 줄로 묶고, 무엇을 바꿔 쟀는지(조건)를 보인다 (2026-10-16).

공개 전 처음 뽑았을 때 두 가지가 틀렸다.
- 이 PC 의 측정 폴더는 판 번호가 **폴더 이름**에 붙어 있어(`9b_32k_links_off_r1/measure_….json`) 일곱 판이 일곱 줄로 나뉘었다 —
  한 줄마다 「판이 적다」가 붙어 실제보다 근거가 약해 보였다. 공개 묶음은 파일 이름에 붙어 있어(`kit__…_r1__measure_….json`) 묶였다.
- 같은 모델 · 같은 창의 두 줄(링크 켬 · 끔)이 표에서 구별되지 않았다.
표본의 숫자는 지어낸 것이다.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _sheet():
    spec = importlib.util.spec_from_file_location("exam_sheet", ROOT / "scripts" / "exam_sheet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _kit(path: pathlib.Path, score: int, model: str = "qwen3.5:9b") -> None:
    path.write_text(json.dumps({
        "pc": {"cards": [{"name": "NVIDIA GeForce RTX 0000"}], "model": model, "window": 32768,
               "on_card_share": 1.0, "sonjari_build": "abcdef123456"},
        "price_summary": {"per_round": [score], "out_of": 9, "median": score, "causes": {"읽고 잃음": 9 - score}, "sec_median": 100},
    }), encoding="utf-8")


def test_rounds_of_one_condition_become_one_row_with_its_condition(tmp_path) -> None:
    pack = tmp_path / "desktop"
    pack.mkdir()
    for number, score in enumerate([1, 2, 6], start=1):
        _kit(pack / f"kit__night__9b_32k_links_off_r{number}__measure_20261013-20{number}0.json", score)
    _kit(pack / "kit__night__9b_32k_links_on_r1__measure_20261013-2100.json", 5)

    sheet = _sheet().render(_sheet()._rows([pack]), link_prefix="measurements/x/")

    rows = [line for line in sheet.splitlines() if line.startswith("| RTX 0000")]
    assert len(rows) == 2
    off = next(row for row in rows if "links off" in row)
    assert "1, 2, 6 |" in off and "판이 적다" not in off
    assert "(3개 파일)" in off and "](measurements/x/desktop/)" in off
    on = next(row for row in rows if "links on" in row)
    assert "판이 적다" in on  # 한 판뿐인 조건은 그렇다고 적는다


def test_rounds_numbered_in_the_folder_name_are_merged_too(tmp_path) -> None:
    """이 PC 의 측정 폴더 모양 — 판 번호가 폴더 이름에 있다."""
    night = tmp_path / "night"
    for number, score in enumerate([3, 4, 5], start=1):
        folder = night / f"9b_32k_links_off_r{number}"
        folder.mkdir(parents=True)
        _kit(folder / f"measure_20261013-20{number}0.json", score)

    sheet = _sheet().render(_sheet()._rows([night]))

    rows = [line for line in sheet.splitlines() if line.startswith("| RTX 0000")]
    assert len(rows) == 1
    assert "9b 32k links off" in rows[0] and "3, 4, 5 |" in rows[0] and "판이 적다" not in rows[0]


def test_a_downloaded_model_shows_its_file_name(tmp_path) -> None:
    pack = tmp_path / "desktop"
    pack.mkdir()
    _kit(pack / "kit__probe__measure_20261014-1300.json", 9, model="7B-GGUF:Some-Model-27B-IQ3_S.gguf")

    sheet = _sheet().render(_sheet()._rows([pack]))

    assert "`Some-Model-27B-IQ3_S`" in sheet
