"""PPTX 에 앱 글꼴 심기 (2026-10-26).

장표 결은 앱에 든 오픈 글꼴(프리텐다드 등 · `slide_themes/fonts`)로 그린다. 그런데 PPTX 의 글 상자는 받는 사람 PC 의 글꼴로
그려져서, 그 PC 에 없는 글꼴 이름을 적으면 PowerPoint 가 다른 글꼴로 바꿔 그린다. 그래서 장에 **쓴 글자만** 담은 글꼴을
PPTX 안에 심는다 — PowerPoint 가 「글꼴 포함」으로 저장할 때와 같은 자리(`ppt/fonts/*.fntdata` + `p:embeddedFontLst`).

- 꼴: EOT(Embedded OpenType) 2.2 머리 + 압축 안 한 TrueType. PowerPoint 는 자기가 저장할 때 압축(MTX)을 쓰지만,
  압축 안 한 것도 읽는다 — 프리텐다드를 설치하지 않은 이 PC 의 PowerPoint 창에서 그 모양으로 그려지는 것을 눈으로 확인(10-26).
  ★ COM 의 `Slide.Export` 그림은 심은 글꼴을 안 쓴다(PowerPoint 가 직접 심은 파일도 같음) — 확인은 그림이 아니라 창으로.
- 머리의 검사합 · 이름 · OS/2 값은 **실제로 싣는 줄인 글꼴에서** 읽는다(원본 글꼴 값을 쓰면 데이터와 어긋난다).
- 라이선스: 전부 SIL OFL 1.1. OFL FAQ 1.12 「문서에 통째로든 일부만이든 심어도 된다 · 고침 · 재배포 제한은 적용되지 않는다」.
  심는 글꼴의 심기 허용 값(fsType)은 0 으로 둔다 — SUIT 는 4(보기 · 인쇄만)라 받는 사람이 고칠 수 없게 열릴 수 있는데,
  OFL 은 고칠 권리를 주고 FAQ 4.2.2 가 라이선스와 어긋나는 fsType 을 바로잡을 것으로 본다.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path
from typing import Any

FONT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"
FONT_TYPE = "application/x-fontdata"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
#: p:presentation 안에서 embeddedFontLst 보다 **뒤에** 와야 하는 것들(스키마 순서) — 이 중 첫 것 앞에 넣는다.
_AFTER_FONTS = ("custShowLst", "photoAlbum", "custDataLst", "kinsoku", "defaultTextStyle", "modifyVerifier", "extLst")


def unavailable() -> str:
    """심을 수 없는 까닭(빈 글이면 심을 수 있다). woff2 를 풀려면 brotli 가 있어야 한다."""
    try:
        import brotli  # noqa: F401
        import fontTools.subset  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"[:200]
    return ""


def face_file(family: str, bold: bool) -> tuple[Path | None, bool]:
    """앱 글꼴 묶음에서 그 굵기 파일. (파일, 진짜 굵은 꼴인가) — 굵은 꼴이 없으면 보통 꼴(PowerPoint 가 굵게 흉내 낸다)."""
    from .slides_style import FONT_DIR, bundled_fonts

    for fam in bundled_fonts():
        if str(fam["family"]).lower() != family.lower():
            continue
        faces = list(fam.get("faces") or [])
        want = 700 if bold else 400
        exact = next((f for f in faces if int(f["weight"]) == want), None)
        pick = exact or next((f for f in faces if int(f["weight"]) == 400), faces[0] if faces else None)
        if pick is None:
            return None, False
        return FONT_DIR / str(pick["file"]), exact is not None and bold
    return None, False


def subset_font(path: Path, text: str) -> bytes:
    """쓴 글자만 남긴 TrueType(꼴 풀기 · 줄이기 · fsType 0)."""
    from fontTools import subset
    from fontTools.ttLib import TTFont

    font = TTFont(str(path))
    font.flavor = None
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.drop_tables = ["DSIG"]
    sub = subset.Subsetter(options)
    sub.populate(text=text + " ")
    sub.subset(font)
    if "OS/2" in font:
        font["OS/2"].fsType = 0
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def _name(font: Any, name_id: int) -> str:
    table = font["name"]
    record = table.getName(name_id, 3, 1, 0x409) or table.getName(name_id, 3, 1) or table.getName(name_id, 1, 0, 0)
    return str(record) if record else ""


def eot(data: bytes, charset: int = 1) -> bytes:
    """TrueType → EOT 2.2(압축 없음 · 줄인 글꼴 표시). 머리 값은 이 데이터에서 다시 읽는다."""
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(data))
    os2 = font["OS/2"]
    panose = os2.panose
    body = bytes(int(getattr(panose, key)) for key in (
        "bFamilyType", "bSerifStyle", "bWeight", "bProportion", "bContrast",
        "bStrokeVariation", "bArmStyle", "bLetterForm", "bMidline", "bXHeight"))
    body += struct.pack("<BBIHH", charset, 1 if os2.fsSelection & 1 else 0, int(os2.usWeightClass), int(os2.fsType), 0x504C)
    body += struct.pack("<4I", os2.ulUnicodeRange1, os2.ulUnicodeRange2, os2.ulUnicodeRange3, os2.ulUnicodeRange4)
    body += struct.pack("<2I", getattr(os2, "ulCodePageRange1", 0), getattr(os2, "ulCodePageRange2", 0))
    body += struct.pack("<I", font["head"].checkSumAdjustment) + b"\0" * 16

    def text(value: str) -> bytes:
        raw = value.encode("utf-16-le")
        return struct.pack("<H", len(raw)) + raw

    for name_id in (1, 2, 5, 4):  # 가족 · 꼴 · 판 · 전체 이름 — 앞에 빈 2바이트씩
        body += b"\0\0" + text(_name(font, name_id))
    # 뿌리 글(없음) · 그 검사합(빈 글이면 0x50475342) · EUDC 코드페이지 · 서명 없음 · EUDC 없음
    body += b"\0\0" + struct.pack("<H", 0) + struct.pack("<I", 0x50475342) + struct.pack("<I", 0)
    body += b"\0\0" + struct.pack("<H", 0) + struct.pack("<II", 0, 0)
    flags = 0x1  # TTEMBED_SUBSET — 쓴 글자만
    return struct.pack("<IIII", 16 + len(body) + len(data), len(data), 0x00020002, flags) + body + data


def embed(deck: Any, used: dict[str, dict[bool, str]]) -> dict[str, Any]:
    """python-pptx 덱에 글꼴을 심는다. used = {가족: {굵게?: 쓴 글자}}. → {embedded: [...], bytes, errors}.

    가족 하나가 실패해도 다른 가족은 심는다 — 실패한 가족은 errors 에(그 가족 글은 받는 PC 글꼴로 보인다).
    """
    from lxml import etree
    from pptx.opc.package import Part
    from pptx.opc.packuri import PackURI

    root = deck.part._element
    entries: list[tuple[str, dict[str, str]]] = []
    report: dict[str, Any] = {"embedded": [], "bytes": 0, "errors": []}
    index = 0
    for family, by_weight in sorted(used.items()):
        rel_ids: dict[str, str] = {}
        # 꼴별로 글자를 모은다 — 굵은 꼴이 없는 가족(고운돋움)은 굵은 글자도 보통 꼴에 담는다(PowerPoint 가 굵게 흉내 낸다).
        slots: dict[str, tuple[Path, str]] = {}
        for bold, chars in sorted(by_weight.items()):
            path, real_bold = face_file(family, bold)
            if path is None or not path.exists():
                report["errors"].append(f"{family}: font_file_missing")
                continue
            slot = "bold" if real_bold else "regular"
            slots[slot] = (path, slots.get(slot, (path, ""))[1] + chars)
        for slot, (path, chars) in sorted(slots.items(), key=lambda kv: kv[0] != "regular"):
            try:
                blob = eot(subset_font(path, chars))
            except Exception as exc:  # noqa: BLE001 — 글꼴 하나 때문에 PPTX 를 못 굽지 않게
                report["errors"].append(f"{family}/{slot}: {type(exc).__name__}: {exc}"[:200])
                continue
            index += 1
            part = Part(PackURI(f"/ppt/fonts/font{index}.fntdata"), FONT_TYPE, deck.part.package, blob)
            rel_ids[slot] = deck.part.relate_to(part, FONT_REL)
            report["bytes"] += len(blob)
            report["embedded"].append(f"{family}/{slot}")
        if rel_ids:
            entries.append((family, rel_ids))
    if not entries:
        return report
    old = root.find(f"{{{_P}}}embeddedFontLst")
    if old is not None:
        root.remove(old)
    font_list = etree.Element(f"{{{_P}}}embeddedFontLst")
    for family, rel_ids in entries:
        node = etree.SubElement(font_list, f"{{{_P}}}embeddedFont")
        etree.SubElement(node, f"{{{_P}}}font").set("typeface", family)
        for slot in ("regular", "bold"):  # 스키마 순서: regular → bold → italic → boldItalic
            if slot in rel_ids:
                etree.SubElement(node, f"{{{_P}}}{slot}").set(f"{{{_R}}}id", rel_ids[slot])
    anchor = next((root.find(f"{{{_P}}}{tag}") for tag in _AFTER_FONTS if root.find(f"{{{_P}}}{tag}") is not None), None)
    if anchor is not None:
        anchor.addprevious(font_list)
    else:
        root.append(font_list)
    root.set("embedTrueTypeFonts", "1")
    root.set("saveSubsetFonts", "1")
    return report
