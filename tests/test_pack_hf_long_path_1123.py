"""팩 받기 — 긴 데이터 폴더에서는 허깅페이스 라이브러리를 쓰지 않는다(2026-11-23).

계기: 현업 사용자 PC(스토어판)에서 영상 팩 wan5b 가 `hf_hub: FileNotFoundError` 로 멈췄다. 라이브러리의 받는 중 파일이
255자 언저리면 긴 경로 표시를 안 붙이는데 윈도우가 막는다(이 PC 에서 255 실패 · 257 성공으로 재현). 우리가 표시를 붙이면
라이브러리가 한 번 더 붙여 깨진다 → 그 자리면 직접 받기(<파일>.part)로.

양방향: 긴 폴더(윈도우) → 라이브러리를 안 부르고 직접 받아 끝남 · 짧은 폴더 · 맥/리눅스 → 라이브러리 그대로.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from alture_jarvis import pack_models
from alture_jarvis.pack_models import HF_TEMP_LIMIT, HF_TEMP_TAIL, ModelFetcher, _hf_temp_too_long, parse_models

STORE = Path(r"C:\Users\USER\AppData\Local\Packages\RoboMetaFit.Sonjari_qe52nfz6fmh9c\LocalCache\Local\Sonjari\data"
             r"\models\genvideo")


class _Packs:
    def __init__(self, *models):
        self.packs = {"gen3d": type("P", (), {"models": parse_models("gen3d", list(models))})()}


class _R:
    def __init__(self, status, body):
        import io
        self.status, self.headers, self._io = status, {"content-length": str(len(body))}, io.BytesIO(body)

    def read(self, n=-1):
        return self._io.read(n)

    def close(self):
        pass


def test_the_store_path_of_the_failed_model_counts_as_too_long() -> None:
    # 실패한 wan5b(255자) · 받아진 fastwan(257자) 모두 넘는다 — 경계(255/257)에 기대지 않는다
    for d in ("wan5b", "fastwan", "umt5", "wanvae"):
        assert _hf_temp_too_long(STORE / d, windows=True)
    assert len(str(STORE / "wan5b")) + HF_TEMP_TAIL == 255
    # 반례: 짧은 폴더 · 맥/리눅스는 라이브러리를 그대로 쓴다
    assert not _hf_temp_too_long(Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\models\genvideo\wan5b"), windows=True)
    assert not _hf_temp_too_long(STORE / "wan5b", windows=False)
    assert HF_TEMP_LIMIT < 255


def _run(tmp_path, monkeypatch, *, too_long: bool):
    good = b"GGUF" * 10
    tree = [{"type": "file", "path": "m.gguf", "size": len(good), "lfs": {"oid": hashlib.sha256(good).hexdigest()}}]
    routes = {"https://huggingface.co/api/models/a/b/tree/main?recursive=true": json.dumps(tree).encode(),
              "https://huggingface.co/a/b/resolve/main/m.gguf": good}
    calls = []

    def opener(url, headers):
        calls.append(url)
        return _R(200, routes[url])

    used = []

    def snapshot(**kw):
        used.append(kw)
        Path(kw["local_dir"], "m.gguf").write_bytes(good)

    monkeypatch.setattr(pack_models, "_hf_temp_too_long", lambda target, windows=None: too_long)
    w = {"id": "w", "kind": "weights", "source": {"hf": "a/b", "include": ["m.gguf"]}, "size": len(good), "license": "MIT"}
    f = ModelFetcher(_Packs(w), tmp_path / "d", opener=opener, hf_snapshot=snapshot, free_bytes=lambda _p: 10**12)
    f.fetch("gen3d", wait=True)
    return f, used, calls, good


def test_long_folder_downloads_directly_without_the_library(tmp_path, monkeypatch) -> None:
    f, used, calls, good = _run(tmp_path, monkeypatch, too_long=True)
    assert used == [] and f.status("gen3d")["state"] == "done"
    assert any("/resolve/main/m.gguf" in u for u in calls)
    got = list((tmp_path / "d").rglob("m.gguf"))
    assert len(got) == 1 and got[0].read_bytes() == good


def test_short_folder_still_uses_the_library(tmp_path, monkeypatch) -> None:
    f, used, calls, _good = _run(tmp_path, monkeypatch, too_long=False)
    assert len(used) == 1 and f.status("gen3d")["state"] == "done"
    assert not any("/resolve/" in u for u in calls)
