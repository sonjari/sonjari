"""스토어 패키지 로고는 바탕화면 아이콘과 **같은 그림**으로 보여야 한다 (2026-09-29).

노트북 베타에서 로고가 「이상한 것」으로 보였다. 패키지에 44px 한 장만 넣어서, 작업 표시줄·시작 메뉴가
그 한 장을 늘리거나 강조색 판 위에 작게 얹었다. 크기별·판 없는(unplated) 그림과 그것을 묶는 resources.pri 가 필요하다.
"""

import importlib.util
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / "packaging" / "msix" / "build_app_package.ps1").read_text(encoding="utf-8")


def _icons():
    spec = importlib.util.spec_from_file_location("make_brand_icons", ROOT / "scripts" / "make_brand_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_taskbar_gets_its_own_unplated_art_at_every_size(tmp_path):
    icons = _icons()
    written = set(icons.write_msix_assets(tmp_path))
    for size in (16, 24, 32, 48, 256):
        for suffix in ("", "_altform-unplated", "_altform-lightunplated"):
            name = f"Square44x44Logo.targetsize-{size}{suffix}.png"
            assert name in written, f"작업 표시줄이 찾는 {name} 이 없다 — 윈도우가 판 위에 얹는다"
            assert Image.open(tmp_path / name).size == (size, size), "크기마다 따로 그려야 흐리지 않다"
    for scale in (100, 150, 200):
        assert Image.open(tmp_path / f"Square150x150Logo.scale-{scale}.png").size == (150 * scale // 100,) * 2


def test_the_unplated_art_is_the_desktop_tile_not_a_bare_mark(tmp_path):
    """대표 판정: 바탕화면에 있는 **정확히 그 로고**(흑연 사각형+보라 마크). 모서리 안쪽이 불투명해야 한다."""
    icons = _icons()
    icons.write_msix_assets(tmp_path)
    art = Image.open(tmp_path / "Square44x44Logo.targetsize-48_altform-unplated.png").convert("RGBA")
    assert art.getpixel((24, 6))[3] == 255, "배경 사각형이 빠진 맨 마크다"
    assert list(art.getdata()) == list(icons.tile(48).convert("RGBA").getdata())


def test_the_build_indexes_the_set_into_one_pri():
    assert "makepri" in BUILD and "resources.pri" in BUILD
    assert 'SelectSingleNode("//packaging")' in BUILD, (
        "기본 설정은 배율별 그림을 리소스 팩으로 뺀다 — 단일 msix 에선 그 팩이 안 깔려 고해상도에서 흐린 그림을 쓴다")
    assert 'icons\msix' in BUILD


def test_the_start_menu_name_is_the_new_name():
    assert '$Display = "Sonjari" }' in BUILD
    assert '$Display = "Sonjari Beta" }' in BUILD
    assert '$Display = "Ontelic' not in BUILD
