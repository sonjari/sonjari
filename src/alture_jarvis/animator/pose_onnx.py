# -*- coding: utf-8 -*-
"""사람 찾기 · 2D 관절 · 3D 관절 — onnxruntime 으로 직접 돌린다 (2026-11-03).

전처리 · 후처리는 rtmlib 0.0.16(Tau-J, Apache License 2.0, https://github.com/Tau-J/rtmlib)의
tools/base.py · object_detection/yolox.py · pose_estimation/{rtmpose,rtmpose3d,pre_processings,post_processings}.py 를
줄여 옮겼다. rtmlib 을 통째로 넣지 않은 까닭: opencv-contrib-python 을 같이 요구해 운영 · 스토어 판의 opencv-python 과 부딪친다.

모델 파일(.onnx)은 손자리에 들어 있지 않다 — parts.py 가 사람이 동의한 뒤에만 받는다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

MEAN = np.array((123.675, 116.28, 103.53))
STD = np.array((58.395, 57.12, 57.375))
Z_RANGE = 2.1744869


def _session(path: Path):
    import onnxruntime as ort

    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def _run(session, img: np.ndarray) -> list[np.ndarray]:
    x = np.ascontiguousarray(img.transpose(2, 0, 1), dtype=np.float32)[None]
    names = [o.name for o in session.get_outputs()]
    return session.run(names, {session.get_inputs()[0].name: x})


class Detector:
    """YOLOX(사람 찾기). OpenMMLab onnx_sdk 판은 겹친 상자 고르기까지 모델 안에서 끝내 [N, 5] 를 준다."""

    def __init__(self, path: Path, size: tuple[int, int] = (640, 640), score: float = 0.3) -> None:
        self.session = _session(path)
        self.size = size
        self.score = score

    def __call__(self, img: np.ndarray) -> np.ndarray:
        import cv2

        h, w = self.size
        ratio = min(h / img.shape[0], w / img.shape[1])
        pad = np.full((h, w, 3), 114, np.uint8)
        resized = cv2.resize(img, (int(img.shape[1] * ratio), int(img.shape[0] * ratio)), interpolation=cv2.INTER_LINEAR)
        pad[:resized.shape[0], :resized.shape[1]] = resized
        out = _run(self.session, pad)[0]
        if out.shape[-1] != 5:
            raise RuntimeError(f"사람 찾기 모델 출력 모양이 예상과 다르다: {out.shape}")
        boxes, scores = out[0, :, :4] / ratio, out[0, :, 4]
        return boxes[scores > self.score]


def _bbox_cs(bbox: np.ndarray, padding: float = 1.25) -> tuple[np.ndarray, np.ndarray]:
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2]), np.array([x2 - x1, y2 - y1]) * padding


def _third(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = a - b
    return b + np.r_[-d[1], d[0]]


def _affine(input_size: tuple[int, int], scale: np.ndarray, center: np.ndarray, img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import cv2

    w, h = input_size
    aspect = w / h
    bw, bh = scale
    scale = np.array([bw, bw / aspect]) if bw > bh * aspect else np.array([bh * aspect, bh])
    src_dir = np.array([0.0, scale[0] * -0.5])
    dst_dir = np.array([0.0, w * -0.5])
    src = np.zeros((3, 2), np.float32)
    dst = np.zeros((3, 2), np.float32)
    src[0], src[1] = center, center + src_dir
    src[2] = _third(src[0], src[1])
    dst[0] = [w * 0.5, h * 0.5]
    dst[1] = dst[0] + dst_dir
    dst[2] = _third(dst[0], dst[1])
    mat = cv2.getAffineTransform(np.float32(src), np.float32(dst))
    return cv2.warpAffine(img, mat, (int(w), int(h)), flags=cv2.INTER_LINEAR), scale


class Pose2D:
    """RTMPose(COCO 17점). 결과: (17, 3) = x, y(원본 픽셀), 믿음 점수."""

    def __init__(self, path: Path, size: tuple[int, int] = (192, 256)) -> None:
        self.session = _session(path)
        self.size = size

    def __call__(self, img: np.ndarray, bbox: np.ndarray) -> np.ndarray:
        center, scale = _bbox_cs(bbox)
        crop, scale = _affine(self.size, scale, center, img)
        sx, sy = _run(self.session, (crop - MEAN) / STD)
        sx, sy = sx.reshape(sx.shape[1], -1), sy.reshape(sy.shape[1], -1)
        locs = np.stack([sx.argmax(1), sy.argmax(1)], -1).astype(np.float32)
        vals = 0.5 * (sx.max(1) + sy.max(1))
        kp = locs / 2.0 / np.array(self.size) * scale + center - scale / 2
        kp[vals <= 0] = np.nan
        return np.concatenate([kp, vals[:, None]], 1)


class Pose3D:
    """RTMW3D(133점, 앞 17점이 COCO 몸). 결과: (17, 4) = x, y, z(같은 눈금 — 자른 칸 픽셀), 믿음 점수.

    11-03 시험: rtmlib 이 첫 값으로 주는 것은 x · y 가 픽셀이고 z 만 정규화라 옆에서 보면 눌린다 → simcc 눈금을 쓴다.
    """

    def __init__(self, path: Path, size: tuple[int, int] = (288, 384)) -> None:
        self.session = _session(path)
        self.size = size

    def __call__(self, img: np.ndarray, bbox: np.ndarray) -> np.ndarray:
        center, scale = _bbox_cs(bbox)
        crop, _ = _affine(self.size, scale, center, img)
        sx, sy, sz = _run(self.session, (crop - MEAN) / STD)
        sx, sy, sz = (a.reshape(a.shape[1], -1) for a in (sx, sy, sz))
        locs = np.stack([sx.argmax(1), sy.argmax(1), sz.argmax(1)], -1).astype(np.float32) / 2.0
        vals = np.minimum(sx.max(1), sy.max(1))
        return np.concatenate([locs, vals[:, None]], 1)[:17]


def biggest(boxes: np.ndarray) -> np.ndarray | None:
    """가장 크게 찍힌 사람 하나(레퍼런스 영상은 주인공이 크게 나온다)."""
    if len(boxes) == 0:
        return None
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return boxes[int(np.argmax(areas))]
