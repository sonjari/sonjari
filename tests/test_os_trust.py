"""HTTPS 검사를 윈도우에 맡긴다 — 초기화한 노트북에서 첫 실행 Ollama 받기가 인증서로 죽었다(2026-09-24).

갓 초기화한 윈도우는 루트 인증서를 필요할 때 받아 온다. 파이썬 `ssl` 은 저장소에 **이미 있는 것만** 읽어서
`CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate` 로 떨어졌다. 오래 쓴 개발 PC 에선
브라우저가 루트를 다 받아 둬서 한 번도 안 났다 — 이 시험이 그 자리를 지킨다.
"""

from __future__ import annotations

import ssl
import tomllib
from pathlib import Path

import pytest

truststore = pytest.importorskip("truststore")

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def restore_ssl():
    yield
    truststore.extract_from_ssl()
    import alture_jarvis.os_trust as os_trust

    os_trust._done = False


def test_every_new_https_context_is_verified_by_the_os(restore_ssl):
    from alture_jarvis.os_trust import use_os_trust_store

    assert use_os_trust_store() is True
    # urllib·httpx 가 만드는 기본 문맥이 윈도우 검사 쪽이어야 한다.
    assert isinstance(ssl.create_default_context(), truststore.SSLContext)


def test_backend_entry_switches_before_serving(monkeypatch, restore_ssl):
    import alture_jarvis.__main__ as entry

    seen: list[bool] = []

    def fake_run(*_args, **_kwargs):
        seen.append(isinstance(ssl.create_default_context(), truststore.SSLContext))

    monkeypatch.setattr(entry.uvicorn, "run", fake_run)
    monkeypatch.setattr(entry, "load_env_file", lambda *a, **k: None)
    entry.main()
    assert seen == [True]


def test_a_missing_truststore_does_not_stop_the_app(monkeypatch):
    import builtins

    import alture_jarvis.os_trust as os_trust

    real_import = builtins.__import__

    def no_truststore(name, *args, **kwargs):
        if name == "truststore":
            raise ImportError("gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_truststore)
    monkeypatch.setattr(os_trust, "_done", False)
    assert os_trust.use_os_trust_store() is False


def test_it_ships_in_the_package_and_in_updates():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert any(d.startswith("truststore") for d in deps), "갱신(pip install -e .)으로 깔리려면 pyproject 에 있어야 한다"
    assert "truststore" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert '"truststore"' in (ROOT / "packaging" / "msix" / "check_bundle.py").read_text(encoding="utf-8")
