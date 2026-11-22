"""스토어 · 맥 굽기도 비밀 검사를 거친다 (2026-11-18).

비밀 검사기(`packaging/msix/scan_package_secrets.py`)는 NAS 업데이트 올리기에서만 불렸다. 스토어 0.4.48 은 사람이 손으로 훑었고
(그때 우리 코드 폴더를 빼고 훑는 실수까지 했다) 맥 dmg 는 아예 안 봤다. 두 굽기 모두 사람 이름 검사 바로 뒤에서 부른다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "packaging" / "msix" / "build_app_package.ps1"
DMG = ROOT / "scripts" / "mac" / "build_mac_dmg.sh"


def _scanner():
    spec = importlib.util.spec_from_file_location("scan_package_secrets", ROOT / "packaging" / "msix" / "scan_package_secrets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_the_store_build_runs_the_secret_scan_and_stops_on_a_hit() -> None:
    text = PS1.read_text(encoding="utf-8")
    people, secrets, manifest = text.index("scan_package_people.py"), text.index("scan_package_secrets.py"), text.index("# 3) manifest")
    assert people < secrets < manifest  # 포장(makeappx) 전에
    after = text[secrets:manifest]
    assert "$LASTEXITCODE -ne 0" in after and "throw" in after


def test_the_mac_build_runs_the_secret_scan_before_the_dmg() -> None:
    text = DMG.read_text(encoding="utf-8")
    scan, dmg = text.index("scan_package_secrets.py \"$PAYLOAD\""), text.index("hdiutil create")
    assert scan < dmg and "exit 1" in text[scan:scan + 300]


def test_a_real_looking_key_in_our_code_is_caught_and_a_clean_folder_passes(tmp_path: Path) -> None:
    scanner = _scanner()
    ours = tmp_path / "src" / "alture_jarvis"
    ours.mkdir(parents=True)
    (ours / "ok.py").write_text("X = 1\n", encoding="utf-8")
    assert scanner.scan(tmp_path) == []
    (ours / "leak.py").write_text('KEY = "sk-ant-api03-' + "Ab3dE7gH1jK9mN2pQ5rS8tU4vW6xY0z" + '"\n', encoding="utf-8")
    hits = scanner.scan(tmp_path)
    assert len(hits) == 1 and "leak.py:1" in hits[0] and "sk-a..." in hits[0]  # 값은 앞 4자만
