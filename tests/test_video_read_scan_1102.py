"""영상 읽기 분석기 (2026-11-02) — opencv 없이 numpy 로 확대 · 축소 · 컷을 찾는다.

스토어 판 기본 부품에 opencv 가 없다. 실제 채점(정답 아는 생성 영상 26개 · 옛 opencv 판과 대조)은
docs/설계_영상읽기_도구_2026-11-02.ko.md 7절. 여기는 ffmpeg 없이 도는 작은 시험이다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from alture_jarvis.video_read import scan as S


def _texture(h: int = 108, w: int = 192, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, size=(h // 6 + 1, w // 6 + 1)).astype(np.uint8)
    return np.kron(base, np.ones((6, 6), np.uint8))[:h, :w]


def _zoom_clip(rate_per_frame: float, frames: int = 40) -> np.ndarray:
    img = _texture()
    return np.stack([np.clip(S._scale_about_center(img, rate_per_frame ** k), 0, 255).astype(np.uint8) for k in range(frames)])


def test_the_scanner_does_not_need_opencv() -> None:
    tree = ast.parse(Path(S.__file__).read_text(encoding="utf-8"))
    names = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
             for alias in node.names} | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "cv2" not in names


def test_zoom_in_and_out_are_found() -> None:
    zin = S.scan(_zoom_clip(1.006))["zooms"]
    assert zin and all(z["kind"] == "확대" for z in zin)
    zout = S.scan(_zoom_clip(1 / 1.006))["zooms"]
    assert zout and all(z["kind"] == "축소" for z in zout)


def test_a_still_or_sliding_picture_is_not_a_zoom() -> None:
    still = np.stack([_texture()] * 40)
    assert S.scan(still)["zooms"] == []
    wide = _texture(108, 260)
    slide = np.stack([wide[:, k:k + 192] for k in range(40)])  # 옆으로 밀기(패닝)
    assert S.scan(slide)["zooms"] == []


def test_a_hard_cut_is_found() -> None:
    a, b = _texture(seed=1), _texture(seed=2)
    clip = np.stack([a] * 16 + [b] * 16)
    assert S.scan(clip)["cuts"] == [2.0]
