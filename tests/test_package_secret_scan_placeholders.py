"""게시 전 비밀 검사 — 문서 예시의 자리 표시 키는 건너뛰고, 진짜 키 모양은 계속 막는다 (2026-09-26 npm 문서)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging" / "msix"))

from scan_package_secrets import scan  # noqa: E402


def _write(root: Path, name: str, text: bytes) -> None:
    target = root / "backend" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text)


def test_npm_documentation_placeholder_is_not_a_secret(tmp_path: Path) -> None:
    _write(tmp_path, "config.html", b'key="-----BEGIN PRIVATE KEY-----\nXXXX\nXXXX\n-----END PRIVATE KEY-----"')
    assert scan(tmp_path) == []


def test_a_real_looking_key_still_stops_publishing(tmp_path: Path) -> None:
    # 조각으로 적는다 — 이 소스 자체가 공개판 비밀 검사에 「진짜 키」로 걸리지 않게(실행 때는 온전한 모양이 된다).
    body = b"MIIEvQIBADANBgkq" + b"hkiG9w0BAQEFAASC"
    _write(tmp_path, "leak.json", b"-----BEGIN PRIVATE KEY-----\n" + body + b"\n-----END PRIVATE KEY-----")
    hits = scan(tmp_path)
    assert hits and "private key block" in hits[0]


def test_our_own_prefixes_are_not_written_in_the_source_but_still_caught(tmp_path, monkeypatch) -> None:
    """운영 키 앞자리를 소스에 적으면 공개 저장소에 그 자체가 샌다(2026-09-29) — 환경변수·로컬 파일에서 읽는다."""
    import importlib.util
    from pathlib import Path as _P

    source = _P(__file__).resolve().parents[1] / "packaging" / "msix" / "scan_package_secrets.py"
    assert "pEwo" + "YkLDQh6w" not in source.read_text(encoding="utf-8")
    monkeypatch.setenv("JARVIS_SCAN_EXTRA_PREFIXES", "fake key=ZZfakePrefix123")
    spec = importlib.util.spec_from_file_location("scan_fresh", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "leak.json").write_text('{"k": "ZZfakePrefix123abc"}', encoding="utf-8")
    assert any("fake key" in hit for hit in module.scan(tmp_path))
