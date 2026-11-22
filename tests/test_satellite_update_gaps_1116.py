"""윈도우 위성 갱신의 빈틈 둘 (2026-11-16 · 맥 업데이트 설계 중 지나가다 봄 · 대표 「이어서 고쳐라」).

1. `runtime.update_apply` 가 받은 zip 을 sha256 확인 없이 풀었다 — 검사 함수(`updater.verify_download`)는 있는데 부르는 자리가 없었다.
   이제 본체가 **내준 바로 그 바이트**의 해시를 머리글(`X-Payload-SHA256`)로 주고, 위성은 맞을 때만 푼다. 없으면 안 푼다.
2. `updater.unpack` 의 staging 밖 검사가 글자 앞머리 비교였다 — `staged` 옆 `staged2` 로 쓰는 `../staged2/x` 가 지나갔다.
"""

from __future__ import annotations

import hashlib
import sys
import types
import zipfile
from pathlib import Path

import pytest

from alture_jarvis import runtime, updater


# ── 2. staging 밖으로 ─────────────────────────────────────────────────────────────────────


def test_a_sibling_folder_with_the_same_prefix_is_outside(tmp_path: Path) -> None:
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as bundle:
        bundle.writestr("../staged2/gotcha.txt", "pwned")
    with pytest.raises(ValueError, match="staging 밖"):
        updater.unpack(evil, tmp_path / "staged")
    assert not (tmp_path / "staged2" / "gotcha.txt").exists(), "staging 옆 폴더에 써 버렸다"


def test_an_ordinary_bundle_still_unpacks(tmp_path: Path) -> None:
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as bundle:
        bundle.writestr("src/alture_jarvis/a.py", "A = 1\n")
        bundle.writestr("recipes/r.json", "{}")
    out = updater.unpack(good, tmp_path / "staged")
    assert out["file_count"] == 2 and (tmp_path / "staged" / "recipes" / "r.json").is_file()


# ── 1. 위성이 받은 바이트를 맞춰 본다 ─────────────────────────────────────────────────────


@pytest.fixture()
def satellite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """본체가 내줄 진짜 묶음 하나와, 위성 `update_apply` 를 돌릴 대역."""
    from alture_jarvis import store_update

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(store_update, "package_full_name", lambda: "")
    install = tmp_path / "install"
    (install / "src" / "alture_jarvis").mkdir(parents=True)
    (install / "src" / "alture_jarvis" / "agent.py").write_text("A = 2\n", encoding="utf-8")
    (install / "scripts").mkdir()
    (install / "scripts" / "apply_update.ps1").write_text("# 교체", encoding="utf-8")
    made = updater.write_payload(install, tmp_path / "served.zip")
    served = Path(made["path"]).read_bytes()
    unpack_dir = tmp_path / "x"
    updater.unpack(Path(made["path"]), unpack_dir)
    expected_build = updater.staged_build(unpack_dir)

    popen: list[list[str]] = []
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda args, **kw: popen.append(list(args)))
    monkeypatch.setattr(runtime, "build_id", lambda: "oldbuild0000")
    monkeypatch.setattr(updater, "runtime_root", lambda: tmp_path / "running")

    def make(header: str | None, body: bytes = served):
        def download(path: str, dest: Path) -> str:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            return "" if header is None else header

        stub = types.SimpleNamespace(
            config=types.SimpleNamespace(private_update_enabled=True, data_dir=str(tmp_path / "data"), store_update_dir="x"),
            events=types.SimpleNamespace(publish=lambda *a, **k: None),
            _brain_get=lambda path: {"build": expected_build, "payload_id": ""},
            _brain_download=download,
        )
        return stub

    return types.SimpleNamespace(make=make, served=served, sha=hashlib.sha256(served).hexdigest(), popen=popen,
                                 staging=tmp_path / "data" / "update" / "staged")


def test_matching_bytes_are_applied(satellite) -> None:
    out = runtime.JarvisRuntime.update_apply(satellite.make(satellite.sha))
    assert out["applied"] is True, out
    assert len(satellite.popen) == 1


def test_bytes_broken_on_the_way_are_not_applied(satellite) -> None:
    broken = satellite.served[:-10] + b"\x00" * 10
    out = runtime.JarvisRuntime.update_apply(satellite.make(satellite.sha, broken))
    assert out["applied"] is False and "해시가 다릅니다" in out["reason"]
    assert satellite.popen == [] and not satellite.staging.exists(), "확인 전에 풀었다"


def test_no_hash_from_the_brain_means_no_swap(satellite) -> None:
    """옛 본체는 머리글을 안 준다 — 「모르면 안 받는다」. 본체부터 새 판으로."""
    out = runtime.JarvisRuntime.update_apply(satellite.make(None))
    assert out["applied"] is False and "해시를 안 줬습니다" in out["reason"]
    assert satellite.popen == []


def test_the_brain_sends_the_hash_of_exactly_what_it_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    payload = tmp_path / "payload.zip"
    payload.write_bytes(b"PK fake zip bytes")
    monkeypatch.setattr(runtime.JarvisRuntime, "update_payload_path", lambda self: payload)
    config = JarvisConfig(data_dir=tmp_path / "data", control_token="test-token")
    with TestClient(create_app(config, start_services=False)) as client:
        response = client.get("/v1/update/payload", headers={"X-JARVIS-TOKEN": "test-token"})
    assert response.status_code == 200
    assert response.headers["X-Payload-SHA256"] == hashlib.sha256(response.content).hexdigest()
