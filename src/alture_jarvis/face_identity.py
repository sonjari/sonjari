"""Tell the office's few faces apart, locally.

YOLO only ever says "a person is there". Answering "사용자 좀 봐봐" needs "which
person", and with a closed set of two or three people that is a face embedding
plus a cosine similarity -- no training, no cloud call.

Runs on OpenCV's own YuNet detector and SFace recogniser, which ship inside
cv2 5.0; only the two ONNX weight files come from outside. That was chosen over
InsightFace deliberately: no new pip dependency, ~38MB instead of ~300MB, and
this machine's onnxruntime has only a CPU provider so the heavier model would
not have run faster anyway.

**Everything here stays on this PC.** These are photographs of colleagues, so
the registry is a local file and nothing is uploaded, ever.

The one rule that matters when using this: `identify()` returns similarity
numbers, and the caller must decide with them. A model asked "did you find
사용자?" will happily say yes -- that has already happened in this project with
the gimbal (see the handoff, 5.2). The number is the evidence; the sentence is
not.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# SFace's own recommended cosine threshold. Above this, two crops are the same
# person. Kept as a named constant because it is a real published figure, not a
# knob someone tuned until a demo passed.
SFACE_COSINE_THRESHOLD = 0.363

# opencv_zoo pins model files per release; these are the current stable pair.
MODEL_SOURCES = {
    "detector": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "recognizer": (
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
}

# A face smaller than this is too few pixels to embed reliably. Detection can
# still find them; matching them produces confident nonsense.
MIN_FACE_PX = 48


@dataclass(frozen=True, slots=True)
class Match:
    name: str
    similarity: float
    box: tuple[int, int, int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "similarity": round(self.similarity, 4),
            "box": list(self.box),
        }


class FaceIdentity:
    def __init__(
        self,
        *,
        model_dir: Path,
        registry_path: Path,
        threshold: float = SFACE_COSINE_THRESHOLD,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.registry_path = Path(registry_path)
        self.threshold = threshold
        self._detector: Any = None
        self._recognizer: Any = None
        self._registry: dict[str, list[list[float]]] | None = None

    # ── model files ──────────────────────────────────────────────────────────
    def model_path(self, kind: str) -> Path:
        return self.model_dir / MODEL_SOURCES[kind][0]

    def available(self) -> dict[str, Any]:
        """Can this run at all, and if not, which piece is missing?

        Named separately for each file so the answer is actionable. "얼굴 인식
        불가" alone sends the next person looking in the wrong place.
        """
        missing = [kind for kind in MODEL_SOURCES if not self.model_path(kind).exists()]
        registry = self.load_registry()
        return {
            "ok": not missing and bool(registry),
            "models_present": not missing,
            "missing_models": missing,
            "model_dir": str(self.model_dir),
            "registered": sorted(registry),
            "threshold": self.threshold,
        }

    def _load_models(self) -> None:
        if self._detector is not None and self._recognizer is not None:
            return
        # Weights first, then the library. A machine with neither should hear
        # about the missing download it can act on, not about an import.
        for kind in MODEL_SOURCES:
            if not self.model_path(kind).exists():
                raise RuntimeError(f"face_model_missing:{self.model_path(kind).name}")
        import cv2

        # Input size is set per frame in detect(); 320x320 is a placeholder.
        self._detector = cv2.FaceDetectorYN.create(
            str(self.model_path("detector")), "", (320, 320), 0.7, 0.3, 5000
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(self.model_path("recognizer")), "")

    # ── registry ─────────────────────────────────────────────────────────────
    def load_registry(self) -> dict[str, list[list[float]]]:
        if self._registry is not None:
            return self._registry
        if not self.registry_path.exists():
            self._registry = {}
            return self._registry
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            self._registry = {
                str(name): [list(map(float, vector)) for vector in vectors]
                for name, vectors in raw.get("people", {}).items()
            }
        except (ValueError, OSError, TypeError):
            # A corrupt registry must not take vision down with it.
            self._registry = {}
        return self._registry

    def _save_registry(self, registry: dict[str, list[list[float]]]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "note": "Local face embeddings for office recognition. Do not copy off this PC.",
            "updated_at": time.time(),
            "threshold": self.threshold,
            "people": registry,
        }
        self.registry_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._registry = registry

    def forget(self, name: str) -> dict[str, Any]:
        registry = dict(self.load_registry())
        removed = registry.pop(name, None)
        self._save_registry(registry)
        return {"ok": removed is not None, "name": name, "remaining": sorted(registry)}

    # ── embedding ────────────────────────────────────────────────────────────
    def _detect(self, image: Any) -> Any:
        self._load_models()
        height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(image)
        return faces

    def _embed(self, image: Any, face_row: Any) -> Any:
        aligned = self._recognizer.alignCrop(image, face_row)
        return self._recognizer.feature(aligned)

    def register(self, name: str, images: list[Any]) -> dict[str, Any]:
        """Add one person from a handful of photographs.

        Several embeddings per person rather than one: a single frame pins the
        person to one pose and one lighting, and the office camera will see
        neither again.
        """
        name = name.strip()
        if not name:
            raise ValueError("empty_name")
        import numpy as np

        vectors: list[list[float]] = []
        skipped: list[str] = []
        for index, image in enumerate(images):
            faces = self._detect(image)
            if faces is None or len(faces) == 0:
                skipped.append(f"image_{index}:no_face")
                continue
            if len(faces) > 1:
                # Ambiguous: registering the wrong face poisons every later
                # answer, and silently picking the biggest is how that happens.
                skipped.append(f"image_{index}:multiple_faces({len(faces)})")
                continue
            row = faces[0]
            if min(float(row[2]), float(row[3])) < MIN_FACE_PX:
                skipped.append(f"image_{index}:face_too_small")
                continue
            vectors.append(np.asarray(self._embed(image, row)).flatten().astype(float).tolist())

        if not vectors:
            raise ValueError(f"no_usable_face_in_images ({'; '.join(skipped) or 'none supplied'})")

        registry = dict(self.load_registry())
        registry[name] = registry.get(name, []) + vectors
        self._save_registry(registry)
        return {
            "ok": True,
            "name": name,
            "added": len(vectors),
            "total": len(registry[name]),
            "skipped": skipped,
        }

    # ── recognition ──────────────────────────────────────────────────────────
    def identify(self, image: Any) -> list[Match]:
        """Every face in the frame, with its best match and that match's score.

        Returns the score even when nothing clears the threshold: "사용자 아님"
        with 0.35 against a 0.363 bar is a different situation from 0.02, and
        the caller cannot tell them apart from a boolean.
        """
        import numpy as np

        registry = self.load_registry()
        faces = self._detect(image)
        if faces is None or len(faces) == 0:
            return []

        matches: list[Match] = []
        for row in faces:
            left, top, width, height = (int(round(float(value))) for value in row[:4])
            box = (left, top, left + width, top + height)
            if min(width, height) < MIN_FACE_PX:
                matches.append(Match("(too_small)", 0.0, box))
                continue
            vector = np.asarray(self._embed(image, row)).flatten().astype(float)
            norm = float(np.linalg.norm(vector)) or 1.0
            best_name, best_score = "(unknown)", 0.0
            for name, known in registry.items():
                for candidate in known:
                    other = np.asarray(candidate, dtype=float)
                    score = float(vector @ other / (norm * (float(np.linalg.norm(other)) or 1.0)))
                    if score > best_score:
                        best_name, best_score = name, score
            matches.append(Match(best_name if best_score >= self.threshold else "(unknown)", best_score, box))
        return matches

    def find(self, image: Any, target: str) -> Match | None:
        """The best match for one named person, or None if nobody clears the bar."""
        best: Match | None = None
        for match in self.identify(image):
            if match.name != target:
                continue
            if best is None or match.similarity > best.similarity:
                best = match
        return best
