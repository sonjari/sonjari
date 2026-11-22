"""3D 로 보낼 그림 살피기(`gen_3d_check` · ADR-3D-1) — 양방향 표본.

걸려야 할 것: 선만 있는 낙서(11-14 배 낙서 실물 · 집 선화) · 두 물체 · 잘린 물체 · 사진 바탕 · 너무 작은 그림.
걸리면 안 되는 것: 클로드가 그린 색칠 배(11-14 실물 · 3D 가 잘 나온 그림) · 외곽선 있는 색칠 만화 · 투명 바탕 물체 하나.
배 낙서는 돛대 선이 끊겨 「물체 2개」로 헛걸렸다 → 이어 붙인 뒤 센다(이 시험이 그 헛걸림을 잡는다).
문턱을 정한 표본 13장(공식 예제 · 오늘 판 포함)의 값은 `generated_reports/img2_3d_1114/실험기록.md` 「입력 검사 표본」 절.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from alture_jarvis.gen3d.check import check_image
from alture_jarvis.gen3d_tools import Gen3DTools
from test_gen3d_1114 import _Config, _Packs

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gen3d"


def _kinds(result: dict) -> set[str]:
    return {note.split(":")[0] for note in result["notes"]}


def _save(image: Image.Image, tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    image.save(path)
    return path


def _two_objects(tmp_path: Path) -> Path:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 250, 330, 520), fill=(200, 60, 60), outline="black", width=4)
    draw.ellipse((470, 250, 740, 520), fill=(60, 90, 200), outline="black", width=4)
    return _save(image, tmp_path, "two.png")


def _cut_box(tmp_path: Path) -> Path:
    image = Image.new("RGB", (800, 800), "white")
    ImageDraw.Draw(image).rectangle((300, 200, 800, 600), fill=(90, 160, 90))
    return _save(image, tmp_path, "cut.png")


def _photo_bg(tmp_path: Path) -> Path:
    yy, xx = np.mgrid[0:800, 0:800]
    pixels = np.stack([xx / 800 * 200, yy / 800 * 180, np.full_like(xx, 120.0)], axis=-1)
    pixels = pixels + np.random.default_rng(1).normal(0, 25, pixels.shape)
    image = Image.fromarray(np.clip(pixels, 0, 255).astype("uint8"))
    ImageDraw.Draw(image).ellipse((250, 250, 550, 550), fill=(230, 200, 40))
    return _save(image, tmp_path, "photo.png")


def _cartoon(tmp_path: Path) -> Path:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((200, 300, 600, 600), 40, fill=(240, 170, 80), outline="black", width=6)
    draw.ellipse((300, 120, 500, 320), fill=(250, 210, 170), outline="black", width=6)
    draw.line((330, 600, 330, 720), fill="black", width=6)
    draw.line((470, 600, 470, 720), fill="black", width=6)
    return _save(image, tmp_path, "cartoon.png")


def _house_lines(tmp_path: Path) -> Path:
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    for seg in [((200, 400), (400, 200)), ((400, 200), (600, 400)), ((200, 400), (200, 650)), ((600, 400), (600, 650)),
                ((200, 650), (600, 650)), ((350, 650), (350, 500)), ((450, 500), (450, 650)), ((350, 500), (450, 500))]:
        draw.line(seg, fill="black", width=5)
    return _save(image, tmp_path, "house.png")


def _transparent_object(tmp_path: Path) -> Path:
    image = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((150, 150, 450, 450), fill=(120, 80, 200, 255))
    return _save(image, tmp_path, "alpha.png")


# ── 걸려야 할 것 ──
def test_the_real_doodle_from_11_14_is_a_line_drawing_and_one_object() -> None:
    result = check_image(FIXTURES / "ship_doodle.png")
    assert "line_drawing" in _kinds(result)
    assert result["objects"] == 1, "돛대 선이 끊긴 것을 물체 둘로 세면 안 된다(11-14 헛걸림)"


@pytest.mark.parametrize(("make", "kind"), [
    (_house_lines, "line_drawing"),
    (_two_objects, "several_objects"),
    (_cut_box, "cut_off"),
    (_photo_bg, "busy_background"),
])
def test_what_should_be_flagged_is_flagged(tmp_path: Path, make, kind: str) -> None:
    assert kind in _kinds(check_image(make(tmp_path)))


def test_a_tiny_picture_is_blocked(tmp_path: Path) -> None:
    result = check_image(_save(Image.new("RGB", (200, 180), "white"), tmp_path, "tiny.png"))
    assert result["blocked"] and result["blocked"][0].startswith("too_small")


# ── 걸리면 안 되는 것 ──
@pytest.mark.parametrize("make", [_cartoon, _transparent_object])
def test_clean_one_object_pictures_pass_without_notes(tmp_path: Path, make) -> None:
    result = check_image(make(tmp_path))
    assert result["notes"] == [] and result["blocked"] == [] and result["objects"] == 1


def test_claudes_coloured_ship_that_made_a_good_3d_passes() -> None:
    result = check_image(FIXTURES / "ship_color.png")
    assert result["notes"] == [] and result["objects"] == 1
    assert result["line_like"] < 0.1


def test_a_busy_photo_does_not_also_claim_a_cut(tmp_path: Path) -> None:
    """가림막을 믿기 어려운 사진 바탕에서 「잘림」까지 말하면 거짓 근거가 하나 더 붙는다."""
    assert "cut_off" not in _kinds(check_image(_photo_bg(tmp_path)))


# ── 도구 문 ──
def test_the_tool_goes_through_the_file_check_and_the_pack_switch(tmp_path: Path) -> None:
    def refuse(raw: str) -> Path:
        raise PermissionError("path_outside_allowed_roots")

    with pytest.raises(PermissionError, match="outside_allowed"):
        Gen3DTools(_Config(tmp_path), resolve=refuse, packs=_Packs(True)).gen_3d_check({"image_path": "C:/x.png"})
    with pytest.raises(PermissionError, match="pack_disabled"):
        Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(False)).gen_3d_check({"image_path": "x.png"})
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    out = tools.gen_3d_check({"image_path": str(FIXTURES / "ship_doodle.png")})
    assert out["ok"] and "line_drawing" in _kinds(out)
