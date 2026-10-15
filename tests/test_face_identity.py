from __future__ import annotations

import json

import numpy as np
import pytest

from alture_jarvis.face_identity import SFACE_COSINE_THRESHOLD, FaceIdentity


def _identity(tmp_path, **kwargs) -> FaceIdentity:
    return FaceIdentity(
        model_dir=tmp_path / "models",
        registry_path=tmp_path / "registry.json",
        **kwargs,
    )


def test_missing_models_are_named_not_just_reported_as_broken(tmp_path) -> None:
    # "얼굴 인식 불가" alone sends the next person looking in the wrong place.
    report = _identity(tmp_path).available()
    assert report["ok"] is False
    assert report["models_present"] is False
    assert set(report["missing_models"]) == {"detector", "recognizer"}


def test_models_present_but_nobody_registered_is_not_ok(tmp_path) -> None:
    # Both files on disk and an empty registry still cannot answer "가람 어디
    # 있어?", so it must not advertise itself as ready.
    identity = _identity(tmp_path)
    identity.model_dir.mkdir(parents=True)
    for kind in ("detector", "recognizer"):
        identity.model_path(kind).write_bytes(b"not a real model")
    report = identity.available()
    assert report["models_present"] is True
    assert report["ok"] is False
    assert report["registered"] == []


def test_the_threshold_is_sfaces_published_figure(tmp_path) -> None:
    # A number tuned until a demo passed would drift; this one is published.
    assert _identity(tmp_path).threshold == SFACE_COSINE_THRESHOLD == 0.363


def test_a_corrupt_registry_does_not_take_vision_down(tmp_path) -> None:
    identity = _identity(tmp_path)
    identity.registry_path.write_text("{ this is not json", encoding="utf-8")
    assert identity.load_registry() == {}


def test_registry_round_trips(tmp_path) -> None:
    identity = _identity(tmp_path)
    identity._save_registry({"가람": [[0.1, 0.2, 0.3]]})
    reloaded = _identity(tmp_path)
    assert reloaded.load_registry() == {"가람": [[0.1, 0.2, 0.3]]}


def test_the_registry_file_says_not_to_copy_it(tmp_path) -> None:
    # These are photographs of colleagues. Anyone who opens the file should be
    # told what it is without having to read the source.
    identity = _identity(tmp_path)
    identity._save_registry({"가람": [[0.1]]})
    payload = json.loads(identity.registry_path.read_text(encoding="utf-8"))
    assert "Do not copy off this PC" in payload["note"]


def test_forgetting_someone_removes_only_them(tmp_path) -> None:
    identity = _identity(tmp_path)
    identity._save_registry({"가람": [[0.1]], "나래": [[0.2]]})
    result = identity.forget("가람")
    assert result["ok"] is True
    assert result["remaining"] == ["나래"]


def test_forgetting_an_unknown_name_is_not_an_error_but_says_so(tmp_path) -> None:
    identity = _identity(tmp_path)
    identity._save_registry({"나래": [[0.2]]})
    assert identity.forget("없는사람")["ok"] is False


def test_registering_without_a_name_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="empty_name"):
        _identity(tmp_path).register("   ", [np.zeros((100, 100, 3), dtype=np.uint8)])


def test_identify_without_models_says_which_file_is_missing(tmp_path) -> None:
    identity = _identity(tmp_path)
    with pytest.raises(RuntimeError, match="face_model_missing"):
        identity.identify(np.zeros((100, 100, 3), dtype=np.uint8))
