"""스토어 포장에서 팩 숨기기(2026-11-16 대표 「3D 팩은 이번 판에서 숨긴다」 → 11-20 「전부 들어가자」: 숨기는 팩 없음 · 장치는 남김).

진짜 저장소의 packs/ · capabilities/ 를 포장본 Lib 처럼 복사해 `store_exclusions.prune` 을 돌린다.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packaging" / "msix"))

import check_bundle  # noqa: E402
import store_exclusions  # noqa: E402


def _fake_lib(tmp_path: Path) -> Path:
    lib = tmp_path / "Lib"
    shutil.copytree(_ROOT / "packs", lib / "packs", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "vendor"))
    shutil.copytree(_ROOT / "capabilities", lib / "capabilities")
    return lib


def test_no_pack_is_hidden_from_the_store_since_0449():
    """★ 11-20 대표 「권고대로 전부 들어가자」: 0.4.49 부터 3D · 영상 생성 팩도 스토어 판에 싣는다(라이선스 파일 8860b3ae)."""
    flags = {p.parent.name: json.loads(p.read_text(encoding="utf-8")).get("store")
             for p in (_ROOT / "packs").glob("*/pack.json")}
    assert {"animator", "game", "video", "gen3d", "genvideo"} <= set(flags)
    for name, flag in flags.items():
        assert flag is not False, name


def test_store_package_keeps_every_pack_and_card(tmp_path):
    lib = _fake_lib(tmp_path)
    before_cards = {p.relative_to(lib / "capabilities").as_posix() for p in (lib / "capabilities").rglob("*.md")}
    result = store_exclusions.prune(lib)

    assert result == {"packs": [], "cards": []}
    left = sorted(p.parent.name for p in (lib / "packs").glob("*/pack.json"))
    assert {"animator", "game", "video", "gen3d", "genvideo"} <= set(left)
    pattern, least, _ = check_bundle.REQUIRED_DATA["packs"]
    assert len(list((lib / "packs").glob(pattern))) >= least
    after_cards = {p.relative_to(lib / "capabilities").as_posix() for p in (lib / "capabilities").rglob("*.md")}
    assert after_cards == before_cards
    assert "3d/image-to-3d.md" in after_cards
    # 라이선스 파일이 포장본 팩 폴더에 같이 실린다.
    for pack in ("gen3d", "genvideo"):
        assert (lib / "packs" / pack / "LICENSE.md").exists(), pack


def test_mixed_card_stays_and_headless_card_stays(tmp_path):
    lib = tmp_path / "Lib"
    (lib / "packs" / "a").mkdir(parents=True)
    (lib / "packs" / "a" / "pack.json").write_text(json.dumps({"id": "a", "store": False, "tools": ["x1", "x2"]}), encoding="utf-8")
    (lib / "packs" / "b").mkdir(parents=True)
    (lib / "packs" / "b" / "pack.json").write_text(json.dumps({"id": "b", "tools": ["y1"]}), encoding="utf-8")
    cards = lib / "capabilities" / "g"
    cards.mkdir(parents=True)
    (cards / "only_a.md").write_text("---\nid: g/only_a\n도구: [x1, x2]\n---\n본문 도구: [y1]\n", encoding="utf-8")
    (cards / "mixed.md").write_text("---\nid: g/mixed\n도구: [x1, y1]\n---\n", encoding="utf-8")
    (cards / "no_tools.md").write_text("---\nid: g/none\n---\n도구: [x1]\n", encoding="utf-8")
    result = store_exclusions.prune(lib)
    assert result == {"packs": ["a"], "cards": ["g/only_a.md"]}
    assert (cards / "mixed.md").exists() and (cards / "no_tools.md").exists()
    assert (lib / "packs" / "b").exists()


def test_nothing_hidden_means_nothing_removed(tmp_path):
    lib = tmp_path / "Lib"
    (lib / "packs" / "b").mkdir(parents=True)
    (lib / "packs" / "b" / "pack.json").write_text(json.dumps({"id": "b", "tools": ["y1"]}), encoding="utf-8")
    (lib / "capabilities").mkdir()
    (lib / "capabilities" / "README.md").write_text("카드 안내", encoding="utf-8")
    assert store_exclusions.prune(lib) == {"packs": [], "cards": []}
    assert (lib / "capabilities" / "README.md").exists()


def test_only_the_store_path_runs_the_exclusion():
    """MSIX 길은 robocopy 뒤 · 번들 검사 앞에서 돌린다. 맥 설치 · dmg · 운영 동기화는 3D 를 그대로 싣는다."""
    ps1 = (_ROOT / "packaging/msix/build_app_package.ps1").read_text(encoding="utf-8")
    at = ps1.index("store_exclusions.py")
    assert ps1.index('(Join-Path $Root "packs")') < at
    assert ps1.index('(Join-Path $Root "capabilities")') < at
    assert at < ps1.index("check_bundle.py")
    for other in ("scripts/mac/install_mac.sh", "scripts/mac/build_mac_dmg.sh", "scripts/sync_to_runtime.ps1"):
        path = _ROOT / other
        if path.exists():
            assert "store_exclusions" not in path.read_text(encoding="utf-8", errors="replace"), other
