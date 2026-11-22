"""사진 손질(gen_3d_prep) — 일부러 깨 보는 시험 (2026-11-15 · 설계 `설계_3D두번굽기_분업` §4-1).

- 칸 이름 ↔ 실제 자리가 맞나(A1 · Z1 · AA1 · 끝 칸) · 격자 밖 · 이상한 이름은 거절
- fill(주변 색으로)이 점을 지우고 둘레 색에 가깝나 · bg(배경으로)는 흰색 · 지운 칸 밖은 안 건드림
- 작은 사진은 긴 변 1024 로 키움 · 잔무늬 펴기가 점무늬를 줄임 · 결과 그림 셋(손질본 · 격자 · 전후) · view 확대 격자
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from alture_jarvis.gen3d.prep import col_name, parse_cell, prep_image


def _photo(tmp_path: Path, w: int = 200, h: int = 240) -> Path:
    a = np.zeros((h, w, 3), dtype=np.uint8)
    a[:] = (40, 40, 40)                      # 어두운 배경
    a[40:220, 40:160] = (150, 90, 50)        # 갈색 몸
    a[60:66, 97:103] = (250, 250, 250)       # 하얀 점(열쇠고리 구멍 흉내)
    a[150:160, 50:60] = (60, 30, 20)         # 어두운 점(지우면 안 되는 것)
    p = tmp_path / "toy.png"
    Image.fromarray(a).save(p)
    return p


def test_cell_names_round_trip() -> None:
    assert [col_name(i) for i in (0, 25, 26, 27, 47)] == ["A", "Z", "AA", "AB", "AV"]
    assert parse_cell("A1", 48, 48) == (0, 0)
    assert parse_cell("aa10", 48, 48) == (26, 9)
    assert parse_cell("AV48", 48, 48) == (47, 47)
    for bad in ("A0", "AW1", "A49", "3C", "", "C3:"):
        with pytest.raises(ValueError):
            parse_cell(bad, 48, 48)


def test_fill_erases_the_spot_and_leaves_other_cells(tmp_path: Path) -> None:
    src = _photo(tmp_path)
    # 200×240 → 긴 변 1024(배수 4.27) · grid 20: 칸 = 원본 10×12 픽셀. 점(97~103, 60~66)은 J6 칸(가로 90~100 · 세로 60~72) 근처
    out = prep_image(src, tmp_path / "o", grid=20, smooth=0, erase=[{"cells": "J6:K6", "mode": "fill"}], margin=0.0)
    img = np.asarray(Image.open(out["image"]).convert("RGB")).astype(int)
    s = 1024 / 240
    spot = img[int(61 * s):int(65 * s), int(98 * s):int(102 * s)]
    assert spot.mean(axis=(0, 1))[0] < 200  # 하얀 점이 사라짐(빨강 성분이 몸 갈색 쪽으로)
    assert np.abs(spot.mean(axis=(0, 1)) - np.array([150, 90, 50])).max() < 40
    dark = img[int(152 * s):int(158 * s), int(52 * s):int(58 * s)]
    assert dark.mean() < 60  # 지우지 않은 칸의 어두운 점은 그대로
    assert out["erased_cells"] == 2


def test_bg_paints_white_and_size_grows(tmp_path: Path) -> None:
    src = _photo(tmp_path)
    out = prep_image(src, tmp_path / "o", grid=10, smooth=0, erase=[{"cells": "A1:B10", "mode": "bg"}], margin=0.0)
    img = np.asarray(Image.open(out["image"]).convert("RGB")).astype(int)
    assert max(img.shape[:2]) == 1024
    left = img[:, : int(img.shape[1] * 0.2) - 2]
    assert left.min() >= 250  # 왼쪽 두 열은 흰 바탕
    assert img[:, int(img.shape[1] * 0.5)].mean() < 200  # 가운데는 그대로


def test_smoothing_reduces_freckles(tmp_path: Path) -> None:
    a = np.full((200, 200, 3), (150, 90, 50), dtype=np.uint8)
    rng = np.random.default_rng(0)
    for _ in range(80):  # 점무늬
        y, x = rng.integers(10, 190, size=2)
        a[y:y + 2, x:x + 2] = (90, 40, 30)
    p = tmp_path / "f.png"
    Image.fromarray(a).save(p)
    plain = np.asarray(Image.open(prep_image(p, tmp_path / "a", smooth=0, margin=0.0)["image"])).astype(float)
    smooth = np.asarray(Image.open(prep_image(p, tmp_path / "b", smooth=2, margin=0.0)["image"])).astype(float)
    # 색마다 따로(세 색을 한꺼번에 재면 점이 없어도 41 — 11-15 시험 버그)
    assert smooth.std(axis=(0, 1)).mean() < 0.5 * plain.std(axis=(0, 1)).mean()


def test_outputs_and_bad_arguments(tmp_path: Path) -> None:
    src = _photo(tmp_path)
    out = prep_image(src, tmp_path / "o", grid=24, view="C3:H8")
    for k in ("image", "grid", "before_after", "zoom"):
        assert Path(out[k]).is_file(), k
    zoom = Image.open(out["zoom"])
    assert zoom.size[0] > 6 * 60 and zoom.size[1] > 6 * 60  # 칸 하나 60px 로 키운 확대 격자
    with pytest.raises(ValueError):
        prep_image(src, tmp_path / "x", grid=100)
    with pytest.raises(ValueError):
        prep_image(src, tmp_path / "x", smooth=9)
    with pytest.raises(ValueError):
        prep_image(src, tmp_path / "x", erase=[{"cells": "A1", "mode": "blur"}])
    with pytest.raises(ValueError):
        prep_image(src, tmp_path / "x", grid=10, erase=[{"cells": "Z99", "mode": "fill"}])
