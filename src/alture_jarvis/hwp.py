"""한컴 한글: 열린 문서에 붙어 사본 diff 뒤 승인·적용·복원한다.

COM은 별도 프로세스에서만 부른다. 한글의 모달 대화상자 하나가 JobRunner의 유일한
스레드를 영원히 붙드는 것을 막고, 제한시간이 지나면 그 호출 프로세스를 종료한다.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import environment_for_our_own_child
from .models import RiskLevel
from .proof import ProofSpec, same_fingerprint
from .tool_gateway import InverseSpec, ToolGateway, ToolSpec

_PROG_ID = "HWPFrame.HwpObject"
_SECURITY_KIND = "FilePathCheckDLL"
_MAX_TEXT = 200_000
_MAX_REPLACEMENT = 20_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_restore(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.jarvis-restore-{secrets.token_hex(6)}")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


def _document_rows(hwp: Any, *, instance_id: str = "") -> list[dict[str, Any]]:
    documents = hwp.XHwpDocuments
    rows: list[dict[str, Any]] = []
    for index in range(int(documents.Count)):
        document = documents.Item(index)
        full_name = str(getattr(document, "FullName", "") or "")
        rows.append(
            {
                "index": index,
                "native_document_id": int(document.DocumentID),
                "instance_id": instance_id,
                "path": full_name,
                "name": Path(full_name).name if full_name else "저장하지 않은 한글 문서",
                "format": str(getattr(document, "Format", "") or ""),
                "modified": bool(getattr(document, "Modified", False)),
            }
        )
    return rows


def _find_document(hwp: Any, native_document_id: int, source_path: str = "") -> Any:
    wanted_path = str(Path(source_path).resolve()).lower() if source_path else ""
    for row in _document_rows(hwp):
        if int(row["native_document_id"]) != int(native_document_id):
            continue
        if wanted_path and str(Path(row["path"]).resolve()).lower() != wanted_path:
            raise RuntimeError("hwp_document_identity_changed")
        return hwp.XHwpDocuments.Item(int(row["index"]))
    raise RuntimeError("hwp_document_not_open")


def _active_text(hwp: Any, document: Any) -> str:
    document.SetActive_XHwpDocument()
    return str(hwp.GetTextFile("TEXT", "") or "")[:_MAX_TEXT]


def _replace_active(hwp: Any, old_text: str, new_text: str) -> bool:
    parameters = hwp.HParameterSet.HFindReplace
    hwp.HAction.GetDefault("AllReplace", parameters.HSet)
    parameters.FindString = old_text
    parameters.ReplaceString = new_text
    parameters.IgnoreMessage = 1
    parameters.Direction = hwp.FindDir("AllDoc")
    return bool(hwp.HAction.Execute("AllReplace", parameters.HSet))


# ── 서식 바꾸기 (2026-10-17) ─────────────────────────────────────────────────
# ★ 서식은 메뉴를 눌러 바꾸지 않고 한글 자동화(HAction "CharShape" · "ParagraphShape")로 바꾼다 (2026-10-17).
#   화면 자동화로 「서식 > 글자 모양」 대화 창을 누르면 칸 하나에 몇 걸음씩 들고, 그림으로 그리는 한글 메뉴는 누름 신호를
#   무시하기도 했다(windows_automation 의 메뉴 항목 주석). 글자 바꾸기(hwp_apply_edit)와 같은 안전 모양 — 사본 미리보기 →
#   승인 → 백업 뒤 원본 반영 → 되돌리기 — 에, **반영한 자리의 서식을 다시 읽어** 요청과 맞는지까지 돌려준다.
#
# ★ 한글 API 이름은 아래 작은 함수들에만 둔다. 실제 한글로 재 보지 못한 채 넣었다(측정이 화면을 쓰고 있었다) — 틀리면
#   여기만 고치면 된다. 문서로 확인한 것과 짐작한 것은 각 함수 주석에 나눠 적었다.

_MAX_FORMAT_TARGETS = 300
#: PDF 내보내기 제한시간 바닥(초) — 한글을 새로 띄우고 문서를 다 그려 굽는다. 편집용 30초로는 큰 문서가 잘린다.
_EXPORT_TIMEOUT_SEC = 180
_MAX_FORMAT_TARGET_TEXT = 500
_MAX_FONT_NAME = 64
#: 한글 문단 정렬 번호(HParaShape.AlignType): 0 양쪽 · 1 왼쪽 · 2 오른쪽 · 3 가운데 · 4 배분 · 5 나눔.
_ALIGN_TYPES = {"justify": 0, "left": 1, "right": 2, "center": 3}
_ALIGN_NAMES = {value: name for name, value in _ALIGN_TYPES.items()}
#: 글꼴 종류(FontType*): 1 = 트루타입. 글꼴 이름만 바꾸고 종류를 안 주면 한글이 이름을 무시하는 일이 있다고 알려져 있다.
_FONT_TYPE_TTF = 1
#: 밑줄 종류(UnderlineType): 0 없음 · 1 글자 아래.
_UNDERLINE_BOTTOM = 1
#: 줄 간격 종류(LineSpacingType): 0 = 글자에 따라(%).
_LINE_SPACING_PERCENT = 0
_FORMAT_CHAR_ITEMS = ("FaceNameHangul", "FaceNameLatin", "Height", "Bold", "Italic", "UnderlineType", "TextColor")
_FORMAT_PARA_ITEMS = ("AlignType", "LineSpacingType", "LineSpacing")


def _pt_to_hwpunit(pt: Any) -> int:
    """글자 크기 pt → HWPUNIT(1pt = 100). 한글 글자 크기 범위(1~4096pt) 밖이면 거절한다."""
    if isinstance(pt, bool):
        raise ValueError("hwp_size_pt_must_be_a_number")  # noqa: TRY004 - 도구 인자 오류는 모두 ValueError 로 돌려준다
    try:
        value = float(pt)
    except (TypeError, ValueError) as exc:
        raise ValueError("hwp_size_pt_must_be_a_number") from exc
    if not math.isfinite(value) or not 1 <= value <= 4096:
        raise ValueError("hwp_size_pt_out_of_range")
    return round(value * 100)


def _color_to_colorref(color: Any) -> int:
    """「#RRGGBB」 → 윈도우 COLORREF(0x00BBGGRR). 한글의 RGBColor 가 돌려주는 값과 같은 모양이다."""
    match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(color or "").strip())
    if not match:
        raise ValueError("hwp_color_must_be_hex_rrggbb")
    hexa = match.group(1)
    red, green, blue = int(hexa[0:2], 16), int(hexa[2:4], 16), int(hexa[4:6], 16)
    return red | (green << 8) | (blue << 16)


def _colorref_to_hex(value: Any) -> str:
    number = int(value) & 0xFFFFFF
    return f"#{number & 0xFF:02X}{(number >> 8) & 0xFF:02X}{(number >> 16) & 0xFF:02X}"


def _font_name(value: Any, field: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > _MAX_FONT_NAME or re.search(r"[\x00-\x1f]", name):
        raise ValueError(f"hwp_{field}_invalid")
    return name


def _format_spec(arguments: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """모델이 준 서식 인자 → 한글 파라미터 항목 이름과 값. 아무것도 안 바꾸는 요청은 거절한다."""
    char: dict[str, Any] = {}
    para: dict[str, Any] = {}
    if arguments.get("font_hangul") not in (None, ""):
        char["FaceNameHangul"] = _font_name(arguments["font_hangul"], "font_hangul")
        char["FontTypeHangul"] = _FONT_TYPE_TTF
    if arguments.get("font_latin") not in (None, ""):
        char["FaceNameLatin"] = _font_name(arguments["font_latin"], "font_latin")
        char["FontTypeLatin"] = _FONT_TYPE_TTF
    if arguments.get("size_pt") not in (None, ""):
        char["Height"] = _pt_to_hwpunit(arguments["size_pt"])
    for field, item in (("bold", "Bold"), ("italic", "Italic")):
        if arguments.get(field) is not None:
            if not isinstance(arguments[field], bool):
                raise ValueError(f"hwp_{field}_must_be_boolean")
            char[item] = 1 if arguments[field] else 0
    if arguments.get("underline") is not None:
        if not isinstance(arguments["underline"], bool):
            raise ValueError("hwp_underline_must_be_boolean")
        char["UnderlineType"] = _UNDERLINE_BOTTOM if arguments["underline"] else 0
    if arguments.get("color") not in (None, ""):
        char["TextColor"] = _color_to_colorref(arguments["color"])
    if arguments.get("align") not in (None, ""):
        align = str(arguments["align"]).strip().lower()
        if align not in _ALIGN_TYPES:
            raise ValueError("hwp_align_must_be_left_center_right_or_justify")
        para["AlignType"] = _ALIGN_TYPES[align]
    if arguments.get("line_spacing_percent") not in (None, ""):
        spacing = arguments["line_spacing_percent"]
        if isinstance(spacing, bool):
            raise ValueError("hwp_line_spacing_percent_must_be_a_number")
        try:
            spacing_value = float(spacing)
        except (TypeError, ValueError) as exc:
            raise ValueError("hwp_line_spacing_percent_must_be_a_number") from exc
        if not math.isfinite(spacing_value) or not 50 <= spacing_value <= 500:
            raise ValueError("hwp_line_spacing_percent_out_of_range")
        para["LineSpacingType"] = _LINE_SPACING_PERCENT
        para["LineSpacing"] = round(spacing_value)
    if not char and not para:
        raise ValueError("hwp_format_needs_at_least_one_change")
    return {"char": char, "para": para}


def _shape_mismatches(spec: dict[str, dict[str, Any]], readback: dict[str, Any]) -> list[dict[str, Any]]:
    """요청한 항목마다 다시 읽은 값과 견준다. 못 읽은 값(None — 섞여 있거나 항목이 없음)도 어긋남이다."""
    out: list[dict[str, Any]] = []
    for group in ("char", "para"):
        wanted_items = dict(spec.get(group) or {})
        got_items = dict((readback or {}).get(group) or {})
        for item, wanted in wanted_items.items():
            if item.startswith("FontType"):
                continue  # 종류는 이름을 받게 하려고 같이 넣는 값이다 — 사람이 시킨 것이 아니다.
            got = got_items.get(item)
            if isinstance(wanted, str):
                same = got is not None and str(got).strip() == wanted.strip()
            else:
                try:
                    same = got is not None and int(got) == int(wanted)
                except (TypeError, ValueError):
                    same = False
            if not same:
                out.append({"item": item, "wanted": wanted, "got": got})
    return out


def _friendly_shape(readback: dict[str, Any]) -> dict[str, Any]:
    """다시 읽은 한글 값을 사람이 읽는 칸으로. 못 읽은 칸은 None 그대로 둔다(「없었다」와 섞지 않는다)."""
    char = dict((readback or {}).get("char") or {})
    para = dict((readback or {}).get("para") or {})
    out: dict[str, Any] = {}
    names = {"FaceNameHangul": "font_hangul", "FaceNameLatin": "font_latin"}
    for item, field in names.items():
        if item in char:
            out[field] = None if char[item] is None else str(char[item])
    if "Height" in char:
        out["size_pt"] = None if char["Height"] is None else int(char["Height"]) / 100
    for item, field in (("Bold", "bold"), ("Italic", "italic")):
        if item in char:
            out[field] = None if char[item] is None else bool(int(char[item]))
    if "UnderlineType" in char:
        out["underline"] = None if char["UnderlineType"] is None else int(char["UnderlineType"]) != 0
    if "TextColor" in char:
        out["color"] = None if char["TextColor"] is None else _colorref_to_hex(char["TextColor"])
    if "AlignType" in para:
        value = para["AlignType"]
        out["align"] = None if value is None else _ALIGN_NAMES.get(int(value), f"other:{int(value)}")
    if "LineSpacing" in para:
        out["line_spacing_percent"] = None if para["LineSpacing"] is None else int(para["LineSpacing"])
    return out


def _format_summary(spec: dict[str, dict[str, Any]], target: str) -> str:
    """승인 카드 · 미리보기에 보일 한 줄. 「무엇을 · 어디에」를 사람 말로."""
    parts: list[str] = []
    char = spec.get("char") or {}
    para = spec.get("para") or {}
    if "FaceNameHangul" in char:
        parts.append(f"한글 글꼴 {char['FaceNameHangul']}")
    if "FaceNameLatin" in char:
        parts.append(f"영문 글꼴 {char['FaceNameLatin']}")
    if "Height" in char:
        parts.append(f"{char['Height'] / 100:g}pt")
    if "Bold" in char:
        parts.append("굵게" if char["Bold"] else "굵게 끄기")
    if "Italic" in char:
        parts.append("기울임" if char["Italic"] else "기울임 끄기")
    if "UnderlineType" in char:
        parts.append("밑줄" if char["UnderlineType"] else "밑줄 끄기")
    if "TextColor" in char:
        parts.append(f"글자 색 {_colorref_to_hex(char['TextColor'])}")
    if "AlignType" in para:
        korean = {0: "양쪽", 1: "왼쪽", 2: "오른쪽", 3: "가운데"}
        parts.append(f"{korean.get(int(para['AlignType']), '')} 정렬")
    if "LineSpacing" in para:
        parts.append(f"줄 간격 {para['LineSpacing']}%")
    return f"{target}: " + " · ".join(parts)


def _run_action(hwp: Any, action_id: str) -> bool:
    """HAction.Run — 「Cancel」(선택 풀기) · 「MoveDocBegin」(문서 처음) · 「SelectAll」(모두 선택).

    확인 정도: 세 이름 모두 한글 자동화 문서의 액션 목록에 있는 이름이다(문서 기준 · 실제 한글로는 이번에 못 재 봄).
    """
    return bool(hwp.HAction.Run(action_id))


def _try_set(parameters: Any, name: str, value: Any) -> None:
    try:
        setattr(parameters, name, value)
    except Exception:  # noqa: BLE001, S110 - 판마다 없는 항목이 있을 수 있다. 없으면 기본값으로 둔다.
        pass


def _find_forward(hwp: Any, text: str) -> bool:
    """RepeatFind 로 아래쪽으로 한 번 찾는다. 찾으면 그 글자가 **선택된** 상태가 된다.

    확인 정도: `RepeatFind` + `HFindReplace`(FindString · Direction=FindDir("Forward") · IgnoreMessage · FindType=1)는
    널리 쓰이는 예제 모양이다(인프런 질문 글 · pyhwpx 의 find 설명). 문서 끝에서 False 가 오는지, 처음으로 돌아가는지는
    판마다 다르다는 말이 있어 부르는 쪽이 위치가 되풀이되면 멈춘다. 대소문자 · 정규식 같은 칸은 사용자의 마지막
    찾기 설정이 남아 있을 수 있어 끈다(없는 칸이면 넘어간다).
    """
    parameters = hwp.HParameterSet.HFindReplace
    hwp.HAction.GetDefault("RepeatFind", parameters.HSet)
    parameters.FindString = text
    parameters.IgnoreMessage = 1
    parameters.Direction = hwp.FindDir("Forward")
    _try_set(parameters, "FindType", 1)
    _try_set(parameters, "MatchCase", 1)
    _try_set(parameters, "FindRegExp", 0)
    _try_set(parameters, "UseWildCards", 0)
    _try_set(parameters, "WholeWordOnly", 0)
    _try_set(parameters, "FindJaso", 0)
    return bool(hwp.HAction.Execute("RepeatFind", parameters.HSet))


def _caret(hwp: Any) -> tuple[int, int, int]:
    """GetPos → (목록 · 문단 · 칸). 확인 정도: 문서의 메서드(pywin32 에서는 바깥 값이 튜플로 온다 — 널리 쓰이는 모양)."""
    position = hwp.GetPos()
    return int(position[0]), int(position[1]), int(position[2])


def _occurrence_ends(hwp: Any, text: str, limit: int) -> list[tuple[int, int, int]]:
    """1단계: **고치지 않고** 찾기만 하며 찾은 곳마다 커서 자리를 적는다.

    ★ 찾는 도중에 문서를 고치면 다시 찾기의 시작 자리가 처음으로 돌아가 끝없이 돈다는 보고가 있다(인프런 질문 글).
      그래서 찾기와 고치기를 두 바퀴로 나눈다. 같은 자리가 또 나오면(끝에서 처음으로 돌아온 것) 멈춘다.
    """
    _run_action(hwp, "Cancel")
    _run_action(hwp, "MoveDocBegin")
    ends: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    while len(ends) < limit:
        if not _find_forward(hwp, text):
            break
        position = _caret(hwp)
        if position in seen:
            break
        seen.add(position)
        ends.append(position)
    _run_action(hwp, "Cancel")
    return ends


def _select_occurrence(
    hwp: Any,
    text: str,
    start: tuple[int, int, int] | None,
    expected: tuple[int, int, int],
) -> None:
    """2단계: 앞 대상의 자리(첫 대상은 문서 처음)에서 한 번 더 찾아 **그 대상만** 선택하고, 1단계 자리와 같은지 본다.

    서식은 글자 수를 안 바꾸므로 1단계에서 적은 자리가 그대로 맞아야 한다. 다르면 엉뚱한 곳을 고칠 수 있으니 멈춘다.
    확인 정도: SetPos(목록, 문단, 칸)는 문서의 메서드다. 찾은 뒤 커서가 선택의 끝에 있다는 것은 짐작이다 — 시작에
    있다면 이 확인이 「hwp_format_target_moved」로 멈춰 알려 준다(엉뚱한 곳을 고치지는 않는다).
    """
    _run_action(hwp, "Cancel")
    if start is None:
        _run_action(hwp, "MoveDocBegin")
    else:
        hwp.SetPos(*start)
    if not _find_forward(hwp, text):
        raise RuntimeError("hwp_format_target_not_found_again")
    if _caret(hwp) != tuple(expected):
        raise RuntimeError("hwp_format_target_moved")


def _execute_shape(hwp: Any, action_id: str, set_name: str, items: dict[str, Any]) -> bool:
    """선택한 곳에 글자 모양(CharShape · HCharShape) 또는 문단 모양(ParagraphShape · HParaShape)을 건다.

    확인 정도: 액션 · 파라미터 셋 이름과 항목(FaceNameHangul · FontTypeHangul · Height · Bold · Italic · UnderlineType ·
    TextColor / AlignType · LineSpacingType · LineSpacing)은 한글 자동화 파라미터 셋 문서와 널리 쓰이는 예제 모양 그대로다.
    GetDefault 로 지금 선택의 값을 채운 뒤 바꿀 칸만 덮는다 — 섞여 있는 칸은 비어 있어 안 건드린다.
    """
    parameters = getattr(hwp.HParameterSet, set_name)
    hwp.HAction.GetDefault(action_id, parameters.HSet)
    for name, value in items.items():
        setattr(parameters, name, value)
    return bool(hwp.HAction.Execute(action_id, parameters.HSet))


def _read_items(hwp: Any, action_id: str, names: tuple[str, ...]) -> dict[str, Any]:
    """지금 선택의 모양을 **새 파라미터 셋**으로 읽는다(CreateAction → CreateSet → GetDefault → ItemExist/Item).

    ★ 쓸 때 쓴 셋(HParameterSet.HCharShape)으로 다시 읽으면 방금 넣은 값이 그대로 남아 있어 아무것도 안 바뀌어도
      「맞다」가 나올 수 있다. 그래서 따로 만든 셋으로 읽는다. 선택 안에서 값이 섞여 있으면 그 항목이 없다 → None.
    확인 정도: Action 객체(CreateSet · GetDefault)와 ParameterSet 객체(Item · ItemExist)는 한글 자동화 문서의 메서드다.
    """
    action = hwp.CreateAction(action_id)
    parameters = action.CreateSet()
    action.GetDefault(parameters)
    out: dict[str, Any] = {}
    for name in names:
        try:
            exists = bool(parameters.ItemExist(name))
        except Exception:  # noqa: BLE001
            exists = False
        if not exists:
            out[name] = None
            continue
        value = parameters.Item(name)
        out[name] = str(value) if name.startswith("FaceName") else int(value)
    return out


def _read_shape(hwp: Any, spec: dict[str, dict[str, Any]]) -> dict[str, Any]:
    char_names = tuple(name for name in _FORMAT_CHAR_ITEMS if name in (spec.get("char") or {}))
    para_names = tuple(name for name in _FORMAT_PARA_ITEMS if name in (spec.get("para") or {}))
    return {
        "char": _read_items(hwp, "CharShape", char_names) if char_names else {},
        "para": _read_items(hwp, "ParagraphShape", para_names) if para_names else {},
    }


def _apply_shape(hwp: Any, spec: dict[str, dict[str, Any]], progress: dict[str, int]) -> None:
    if spec.get("char"):
        if not _execute_shape(hwp, "CharShape", "HCharShape", dict(spec["char"])):
            raise RuntimeError("hwp_char_shape_failed")
        progress["steps"] = progress.get("steps", 0) + 1
    if spec.get("para"):
        if not _execute_shape(hwp, "ParagraphShape", "HParaShape", dict(spec["para"])):
            raise RuntimeError("hwp_para_shape_failed")
        progress["steps"] = progress.get("steps", 0) + 1


def _format_active(
    hwp: Any,
    document: Any,
    payload: dict[str, Any],
    progress: dict[str, int],
) -> dict[str, Any]:
    """열린(활성) 문서에 서식을 건다. 대상마다 걸기 전 · 건 뒤 모양을 다시 읽고, 본문 글자가 그대로인지 본다."""
    spec = dict(payload.get("spec") or {})
    target_text = str(payload.get("target_text") or "")
    whole_document = bool(payload.get("whole_document"))
    occurrence = str(payload.get("occurrence") or "")
    before_text = _active_text(hwp, document)
    before_shapes: list[dict[str, Any]] = []
    readbacks: list[dict[str, Any]] = []
    found = 0
    if whole_document:
        _run_action(hwp, "Cancel")
        if not _run_action(hwp, "SelectAll"):
            raise RuntimeError("hwp_select_all_failed")
        found = 1
        before_shapes.append(_read_shape(hwp, spec))
        _apply_shape(hwp, spec, progress)
        readbacks.append(_read_shape(hwp, spec))
    else:
        ends = _occurrence_ends(hwp, target_text, _MAX_FORMAT_TARGETS + 1)
        found = len(ends)
        if not ends:
            raise RuntimeError("hwp_format_target_not_found")
        if len(ends) > _MAX_FORMAT_TARGETS:
            raise RuntimeError("hwp_format_too_many_targets")
        if len(ends) > 1 and occurrence not in {"all", "first"}:
            raise RuntimeError("hwp_format_target_not_unique_set_occurrence")
        chosen = ends[:1] if occurrence == "first" else ends
        previous: tuple[int, int, int] | None = None
        for end in chosen:
            _select_occurrence(hwp, target_text, previous, end)
            before_shapes.append(_read_shape(hwp, spec))
            _apply_shape(hwp, spec, progress)
            readbacks.append(_read_shape(hwp, spec))
            previous = end
    _run_action(hwp, "Cancel")
    after_text = _active_text(hwp, document)
    if after_text != before_text:
        # 서식은 글자를 바꾸지 않는다. 바뀌었으면 찾기 · 선택이 엉뚱하게 움직인 것이다 — 부르는 쪽이 되돌린다.
        raise RuntimeError("hwp_format_changed_the_text")
    return {
        "found": found,
        "targets": len(readbacks),
        "text_occurrences": before_text.count(target_text) if target_text else 0,
        "before_shapes": before_shapes,
        "readbacks": readbacks,
    }


def _undo_steps(document: Any, steps: int) -> None:
    for _ in range(max(0, int(steps))):
        try:
            document.Undo()
        except Exception:  # noqa: BLE001
            break


def _late_bound(dispatch: Any) -> Any:
    """COM 형식 캐시(gen_py)를 **거치지 않고** 묶는다 (2026-10-17 화면 자동화 측정).

    `win32com.client.Dispatch` · `DispatchEx` 는 형식 캐시가 있으면 그것을 쓰는데, 이 PC 의 한글 캐시 폴더는 9월 1일부터
    **비어 있었고**(만들다 끊긴 것으로 보임) 그 뒤로 `hwp_open` 이 매번 「… has no attribute 'CLSIDToClassMap'」로 죽었다.
    사용자 PC 에서도 같은 일이 생길 수 있다. 여기서는 한글 상수를 캐시에서 꺼내 쓰지 않으므로 늦은 묶기로 충분하다.
    """
    import win32com.client.dynamic  # noqa: PLC0415

    return win32com.client.dynamic.Dispatch(dispatch)


def _new_instance(prog_id: str) -> Any:
    """**새** 인스턴스(`DispatchEx` 와 같은 뜻) — 사용자가 띄워 둔 한글에 붙지 않는다. 묶기는 `_late_bound`."""
    import pythoncom  # noqa: PLC0415

    return _late_bound(pythoncom.CoCreateInstance(prog_id, None, pythoncom.CLSCTX_SERVER, pythoncom.IID_IDispatch))


def _running_hwp_objects(module_name: str) -> tuple[list[tuple[str, Any]], Any]:
    if os.name != "nt":
        raise RuntimeError("windows_only")
    import pythoncom

    pythoncom.CoInitialize()
    try:
        table = pythoncom.GetRunningObjectTable()
        enumerator = table.EnumRunning()
        context = pythoncom.CreateBindCtx(0)
        objects: list[tuple[str, Any]] = []
        while True:
            batch = enumerator.Next(1)
            if not batch:
                break
            moniker = batch[0]
            try:
                name = str(moniker.GetDisplayName(context, None) or "")
            except Exception:
                continue
            if not name.startswith("!HwpObject."):
                continue
            raw = table.GetObject(moniker)
            dispatch = raw.QueryInterface(pythoncom.IID_IDispatch)
            hwp = _late_bound(dispatch)
            # 한글 2022는 같은 인스턴스에 두 번째로 부르면 False를 돌려준다.
            # 최초 등록·비대화상자 저장은 설치 스파이크에서 따로 검증하고, 여기서는
            # 호출 자체가 COM 오류 없이 끝났는지만 본다. 실제 열기/저장은 아래
            # 제한시간 프로세스와 사후 파일 검증이 다시 붙든다.
            hwp.RegisterModule(_SECURITY_KIND, module_name)
            objects.append((name, hwp))
        if not objects:
            raise RuntimeError("hwp_no_running_instance")
        return objects, pythoncom
    except Exception:
        pythoncom.CoUninitialize()
        raise


# ── PDF 로 내보내기 (2026-10-17) ──────────────────────────────────────────────
# ★ 한글 → PDF 를 화면으로 하면 46걸음 · 593초가 들었다(windows_automation 메뉴 주석의 측정 7412255c — 메뉴 누름을
#   다섯 번 되풀이). 같은 일을 한글 자동화로 하면 「열기 → 다른 이름으로 저장(PDF) → 닫기」 세 번이다. 사용자가 띄워 둔
#   한글 창에는 손대지 않는다 — 따로 띄운 숨김 인스턴스에서 **사본**을 열어 굽고 그 인스턴스만 끈다.


def _open_format(path: Path) -> str:
    """Open 의 형식 문자열. hwpx 는 「HWPX」, 옛 한글은 「HWP」 (한글 자동화 Open 의 Format 인자)."""
    return "HWPX" if path.suffix.lower() == ".hwpx" else "HWP"


def _save_as_pdf(hwp: Any, pdf_path: Path) -> bool:
    """열린(활성) 문서를 PDF 로 저장한다 — 한글 API 이름은 이 함수에만 있다.

    확인 정도: `SaveAs(경로, "PDF")` 를 **위치 인자로** 부르는 모양은 인프런 답변 글에서 확인했다(키워드로 부르면
    인자 이름 대소문자 때문에 오류가 난다는 말이 같이 있다). 셋째 인자(arg)는 빈 글로 둔다. 실제 한글로는 이번에 못 재 봤다.
    그게 False 거나 파일이 안 생기면 「FileSaveAs_S」 액션 + HFileOpenSave(filename · Format="PDF")로 한 번 더 해 본다 —
    이쪽은 블록 저장(FileSaveBlock_S) 예제에서 미루어 본 **짐작**이다. 어느 쪽이 됐는지는 부르는 쪽이 %PDF 머리로 다시 본다.
    """
    try:
        if bool(hwp.SaveAs(str(pdf_path), "PDF", "")) and pdf_path.is_file():
            return True
    except Exception:  # noqa: BLE001, S110 - 아래 두 번째 길로 넘어간다. 결과는 파일로 판정한다.
        pass
    parameters = hwp.HParameterSet.HFileOpenSave
    hwp.HAction.GetDefault("FileSaveAs_S", parameters.HSet)
    parameters.filename = str(pdf_path)
    parameters.Format = "PDF"
    return bool(hwp.HAction.Execute("FileSaveAs_S", parameters.HSet)) and pdf_path.is_file()


def _pdf_head_ok(path: Path) -> tuple[bool, int]:
    """PDF 인가 — 있고, 0바이트가 아니고, 첫 바이트가 「%PDF」인가. (맞는가, 바이트 수)"""
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            head = stream.read(5)
    except OSError:
        return False, 0
    return size > 0 and head.startswith(b"%PDF"), size


def _pdf_pages(path: Path) -> int | None:
    """쪽수 — 싸게 읽히면. 못 읽으면 None(「0쪽」과 섞지 않는다)."""
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 - 쪽수는 덤이다. 못 읽어도 변환 판정은 %PDF 머리로 한다.
        return None


def _export_pdf_operation(payload: dict[str, Any], module_name: str) -> dict[str, Any]:
    """숨김 인스턴스에서 사본을 열어 PDF 로 저장하고 그 인스턴스만 끈다. 사용자의 한글은 찾지도 붙지도 않는다."""
    if os.name != "nt":
        raise RuntimeError("windows_only")
    import pythoncom

    source = Path(str(payload.get("source_copy") or ""))
    pdf_path = Path(str(payload.get("pdf_path") or ""))
    if not source.is_file():
        raise RuntimeError("hwp_export_source_copy_missing")
    pythoncom.CoInitialize()
    try:
        hidden = _new_instance(_PROG_ID)
        try:
            hidden.RegisterModule(_SECURITY_KIND, module_name)
            if not bool(hidden.Open(str(source), _open_format(source), "lock:false;suspendpassword:true;forceopen:true")):
                raise RuntimeError("hwp_export_open_failed")
            try:
                hidden.XHwpWindows.Item(0).Visible = False
            except Exception:  # noqa: BLE001, S110 - 창 숨기기는 덤이다. 실패해도 변환은 그대로 한다.
                pass
            saved = _save_as_pdf(hidden, pdf_path)
        finally:
            try:
                hidden.Clear(1)  # 1 = 저장 안 하고 버림 — 사본이라 남길 것이 없다(짐작: 없으면 Quit 이 그대로 닫는다).
            except Exception:  # noqa: BLE001, S110
                pass
            try:
                hidden.Quit()
            except Exception:  # noqa: BLE001, S110
                pass
        return {"saved": bool(saved), "pdf_path": str(pdf_path)}
    finally:
        pythoncom.CoUninitialize()


def _worker_operation(payload: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation") or "")
    module_name = str(payload.get("module_name") or "FilePathCheckerModuleExample")
    if operation == "export_pdf":
        # 떠 있는 한글이 없어도 된다 — 아래 `_running_hwp_objects` 는 없으면 실패하니 그보다 앞에서 갈라진다.
        return _export_pdf_operation(payload, module_name)
    objects, pythoncom = _running_hwp_objects(module_name)
    try:
        if operation == "list_open":
            documents: list[dict[str, Any]] = []
            for instance_id, current in objects:
                documents.extend(_document_rows(current, instance_id=instance_id))
            return {"active": True, "documents": documents}

        instance_id = str(payload.get("instance_id") or "")
        hwp = next((current for name, current in objects if name == instance_id), None)
        if hwp is None:
            raise RuntimeError("hwp_instance_changed")
        native_document_id = int(payload.get("native_document_id") or 0)
        source_path = str(payload.get("source_path") or "")
        document = _find_document(hwp, native_document_id, source_path)
        document.SetActive_XHwpDocument()

        if operation == "read":
            text = _active_text(hwp, document)
            return {
                "native_document_id": native_document_id,
                "path": source_path,
                "text": text,
                "char_count": len(text),
                "modified": bool(hwp.IsModified),
            }

        if operation == "preview_edit":
            if bool(hwp.IsModified) or bool(getattr(document, "Modified", False)):
                raise RuntimeError("hwp_document_has_unsaved_edits")
            old_text = str(payload.get("old_text") or "")
            new_text = str(payload.get("new_text") or "")
            replace_all = bool(payload.get("replace_all"))
            before_text = _active_text(hwp, document)
            occurrences = before_text.count(old_text)
            if occurrences == 0:
                raise RuntimeError("hwp_old_text_not_found")
            if occurrences > 1 and not replace_all:
                raise RuntimeError("hwp_old_text_not_unique_set_replace_all")
            preview_path = Path(str(payload.get("preview_path") or ""))
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(source_path), preview_path)
            # HwpObject.Open은 같은 인스턴스에 탭을 더하는 것이 아니라 현재 문서를
            # 새 파일로 **교체**한다(한글 2022 실측). 사용자 원본 인스턴스에서
            # 사본을 열면 원본이 닫혀 apply의 대상까지 사라진다. 사본은 별도 숨김
            # 인스턴스에서만 굽고 그 인스턴스만 종료한다.
            preview_hwp = _new_instance(_PROG_ID)
            preview_document = None
            try:
                preview_hwp.RegisterModule(_SECURITY_KIND, module_name)
                if not bool(
                    preview_hwp.Open(
                        str(preview_path), "HWP", "lock:false;suspendpassword:true;forceopen:true"
                    )
                ):
                    raise RuntimeError("hwp_preview_copy_open_failed")
                preview_document = preview_hwp.XHwpDocuments.Item(0)
                preview_hwp.XHwpWindows.Item(0).Visible = False
                preview_document.SetActive_XHwpDocument()
                if not _replace_active(preview_hwp, old_text, new_text):
                    raise RuntimeError("hwp_replace_failed")
                after_text = _active_text(preview_hwp, preview_document)
                if not bool(preview_document.Save(True)):
                    raise RuntimeError("hwp_preview_save_failed")
            finally:
                try:
                    preview_hwp.Quit()
                except Exception:
                    pass
            return {
                "native_document_id": native_document_id,
                "path": source_path,
                "preview_path": str(preview_path),
                "source_sha256": _sha256(Path(source_path)),
                "preview_sha256": _sha256(preview_path),
                "before_text": before_text,
                "after_text": after_text,
                "occurrences": occurrences,
            }

        if operation == "apply_edit":
            if bool(hwp.IsModified) or bool(getattr(document, "Modified", False)):
                raise RuntimeError("hwp_document_has_unsaved_edits")
            source = Path(source_path)
            expected_sha = str(payload.get("source_sha256") or "")
            if not expected_sha or _sha256(source) != expected_sha:
                raise RuntimeError("hwp_source_drifted_since_preview")
            backup = Path(str(payload.get("backup_path") or ""))
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            before_text = _active_text(hwp, document)
            try:
                if not _replace_active(
                    hwp,
                    str(payload.get("old_text") or ""),
                    str(payload.get("new_text") or ""),
                ):
                    raise RuntimeError("hwp_replace_failed")
                after_text = _active_text(hwp, document)
                if not bool(document.Save(True)):
                    raise RuntimeError("hwp_apply_save_failed")
            except Exception:
                try:
                    document.Undo()
                except Exception:
                    pass
                raise
            after_sha = _sha256(source)
            return {
                "native_document_id": native_document_id,
                "path": str(source),
                "backup_path": str(backup),
                "before_sha256": expected_sha,
                "after_sha256": after_sha,
                "before_text": before_text,
                "after_text": after_text,
                "verified": after_sha != expected_sha,
            }

        if operation == "restore":
            source = Path(source_path)
            backup = Path(str(payload.get("backup_path") or ""))
            before_sha = str(payload.get("before_sha256") or "")
            after_sha = str(payload.get("after_sha256") or "")
            if not backup.is_file() or _sha256(backup) != before_sha:
                raise RuntimeError("hwp_backup_missing_or_drifted")
            if not source.is_file() or _sha256(source) != after_sha:
                raise RuntimeError("hwp_source_drifted_after_apply")
            if bool(hwp.IsModified) or bool(getattr(document, "Modified", False)):
                raise RuntimeError("hwp_document_has_unsaved_edits")
            document.Close(False)
            _atomic_restore(backup, source)
            reopened = bool(
                hwp.Open(str(source), "HWP", "lock:false;suspendpassword:true;forceopen:true")
            )
            restored_sha = _sha256(source)
            return {
                "path": str(source),
                "restored_sha256": restored_sha,
                "reopened": reopened,
                "verified": restored_sha == before_sha,
            }

        if operation == "preview_format":
            # 글자 바꾸기 미리보기와 같은 까닭으로 사본은 따로 띄운 숨김 인스턴스에서만 굽는다(위 preview_edit 주석).
            if bool(hwp.IsModified) or bool(getattr(document, "Modified", False)):
                raise RuntimeError("hwp_document_has_unsaved_edits")
            preview_path = Path(str(payload.get("preview_path") or ""))
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(source_path), preview_path)
            preview_hwp = _new_instance(_PROG_ID)
            try:
                preview_hwp.RegisterModule(_SECURITY_KIND, module_name)
                if not bool(
                    preview_hwp.Open(
                        str(preview_path), "HWP", "lock:false;suspendpassword:true;forceopen:true"
                    )
                ):
                    raise RuntimeError("hwp_preview_copy_open_failed")
                preview_document = preview_hwp.XHwpDocuments.Item(0)
                preview_hwp.XHwpWindows.Item(0).Visible = False
                preview_document.SetActive_XHwpDocument()
                formatted = _format_active(preview_hwp, preview_document, payload, {"steps": 0})
                if not bool(preview_document.Save(True)):
                    raise RuntimeError("hwp_preview_save_failed")
            finally:
                try:
                    preview_hwp.Quit()
                except Exception:
                    pass
            return {
                "native_document_id": native_document_id,
                "path": source_path,
                "preview_path": str(preview_path),
                "source_sha256": _sha256(Path(source_path)),
                "preview_sha256": _sha256(preview_path),
                **formatted,
            }

        if operation == "apply_format":
            if bool(hwp.IsModified) or bool(getattr(document, "Modified", False)):
                raise RuntimeError("hwp_document_has_unsaved_edits")
            source = Path(source_path)
            expected_sha = str(payload.get("source_sha256") or "")
            if not expected_sha or _sha256(source) != expected_sha:
                raise RuntimeError("hwp_source_drifted_since_preview")
            backup = Path(str(payload.get("backup_path") or ""))
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            progress = {"steps": 0}
            try:
                formatted = _format_active(hwp, document, payload, progress)
                if not bool(document.Save(True)):
                    raise RuntimeError("hwp_apply_save_failed")
            except Exception:
                # ★ 서식은 대상마다 한 걸음씩 쌓인다 — 한 번 되돌리기로는 앞 대상들이 남는다. 건 만큼 되돌린다.
                _undo_steps(document, progress["steps"])
                raise
            after_sha = _sha256(source)
            return {
                "native_document_id": native_document_id,
                "path": str(source),
                "backup_path": str(backup),
                "before_sha256": expected_sha,
                "after_sha256": after_sha,
                "file_changed": after_sha != expected_sha,
                **formatted,
            }

        raise ValueError("unknown_hwp_worker_operation")
    finally:
        pythoncom.CoUninitialize()


def _without_type_cache() -> None:
    """이 작업 프로세스에서는 COM 형식 캐시(gen_py)를 **아예 찾지 않는다** — 모든 객체를 늦은 묶기로 받는다.

    ★ 2026-10-17 실제 한글로 서식 도구를 처음 돌렸을 때: 맨 위 묶기는 `_late_bound` 로 캐시를 피했지만, 그렇게 받은
      객체의 메서드가 돌려주는 객체(`XHwpDocuments.Item(i)` 등)는 pywin32 가 결과 형식 번호로 **다시 캐시를 찾아간다**
      (`win32com.client.Dispatch` → `gencache.GetClassForCLSID`). 이 PC 의 한글 캐시는 반쯤 만들다 끊긴 채라 열린 문서
      목록 읽기가 「… has no attribute 'CLSIDToClassMap'」로 죽었다 — 열린 한글을 다루는 도구 전부가 같은 자리를 지난다.
      한글 상수를 캐시에서 꺼내 쓰는 곳이 없으므로 캐시를 안 쓰면 그만이다. 별도 프로세스라 다른 COM 사용에는 번지지 않는다.
    """
    if os.name != "nt":
        return
    try:
        from win32com.client import gencache  # noqa: PLC0415

        gencache.GetClassForCLSID = lambda _clsid: None
    except Exception:  # noqa: BLE001, S110 - pywin32 가 없으면 아래 작업이 제 오류를 낸다.
        pass


def _worker_main() -> int:
    try:
        _without_type_cache()
        payload = json.loads(sys.stdin.read() or "{}")
        result = _worker_operation(payload)
        sys.stdout.write(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - 경계를 건너 오류 종류와 문구를 보존한다.
        sys.stdout.write(
            json.dumps(
                {"ok": False, "error": str(exc)[:1000], "type": type(exc).__name__},
                ensure_ascii=False,
            )
        )
        return 1


@dataclass(slots=True)
class HwpEditPreview:
    preview_id: str
    document_id: int
    instance_id: str
    native_document_id: int
    source_path: str
    source_sha256: str
    old_text: str
    new_text: str
    replace_all: bool
    preview_path: str
    diff: str
    occurrences: int
    created_at: float
    expires_at: float
    used: bool = False


@dataclass(slots=True)
class HwpFormatPreview:
    """서식 미리보기 한 건. 적용은 여기 적힌 대상 · 서식 · 원본 해시 그대로만 한다."""

    preview_id: str
    document_id: int
    instance_id: str
    native_document_id: int
    source_path: str
    source_sha256: str
    spec: dict[str, dict[str, Any]]
    target_text: str
    whole_document: bool
    occurrence: str
    preview_path: str
    summary: str
    targets: int
    found: int
    created_at: float
    expires_at: float
    used: bool = False


class HwpTools:
    """열린 HWP를 사본에서 검토한 뒤 승인받아 원본에 적용한다."""

    def __init__(self, config: Any, local_computer: Any, events: Any = None) -> None:
        self.config = config
        self.local_computer = local_computer
        self.events = events
        self._lock = threading.RLock()
        self._previews: dict[str, HwpEditPreview] = {}
        self._format_previews: dict[str, HwpFormatPreview] = {}
        self._definitions = self._build_definitions()

    @staticmethod
    def _function(
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                },
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "hwp_list_open",
                "현재 한글에서 이미 열려 있는 HWP 문서의 ID·경로·수정 상태를 읽는다. 한글을 새로 열지 않는다.",
                {},
            ),
            self._function(
                "hwp_read",
                "hwp_list_open에서 받은 document_id의 본문을 읽는다. 저장되지 않은 편집 여부도 같이 확인한다.",
                {"document_id": {"type": "integer"}, "max_chars": {"type": "integer", "maximum": _MAX_TEXT}},
                ["document_id"],
            ),
            self._function(
                "hwp_preview_edit",
                "열린 HWP 원본은 건드리지 않고 사본에 정확한 문자열 교체를 적용해 diff를 만든다. "
                "같은 문구가 여러 번이면 replace_all=true가 아니면 거절한다.",
                {
                    "document_id": {"type": "integer"},
                    "old_text": {"type": "string", "maxLength": _MAX_REPLACEMENT},
                    "new_text": {"type": "string", "maxLength": _MAX_REPLACEMENT},
                    "replace_all": {"type": "boolean"},
                },
                ["document_id", "old_text", "new_text"],
            ),
            self._function(
                "hwp_apply_edit",
                "앞서 만든 HWP 사본 diff를 원본에 반영한다. 승인 필수이며, 사람이 편집 중이거나 원본이 달라졌으면 실행하지 않는다.",
                {
                    "preview_id": {"type": "string"},
                    "diff_summary": {"type": "string", "description": "승인 화면에 보여 줄 preview의 diff 요약"},
                    "preview_path": {"type": "string", "description": "preview 결과의 사본 경로"},
                },
                ["preview_id"],
            ),
            self._function(
                "hwp_preview_format",
                "열린 HWP 문서의 서식(한글·영문 글꼴, 글자 크기, 굵게, 기울임, 밑줄, 글자 색, 문단 정렬, 줄 간격)을 "
                "한글 자동화 기능으로 바꾼다. 메뉴나 대화 창을 누르지 않는다. 원본은 건드리지 않고 사본에 먼저 걸어 "
                "몇 곳이 바뀌는지와 다시 읽은 서식을 돌려준다. 대상은 target_text(그 글자가 있는 곳) 또는 "
                "whole_document=true(문서 전체)이고, 같은 글자가 여러 곳이면 occurrence 를 all 이나 first 로 줘야 한다. "
                "정렬·줄 간격은 대상이 든 문단 전체에 걸린다. 원본 반영은 hwp_apply_format.",
                {
                    "document_id": {"type": "integer"},
                    "target_text": {
                        "type": "string",
                        "maxLength": _MAX_FORMAT_TARGET_TEXT,
                        "description": "서식을 바꿀 글자(본문에 있는 그대로)",
                    },
                    "whole_document": {"type": "boolean", "description": "true 면 문서 전체"},
                    "occurrence": {
                        "type": "string",
                        "enum": ["all", "first"],
                        "description": "같은 글자가 여러 곳일 때 all=전부, first=처음 한 곳",
                    },
                    "font_hangul": {"type": "string", "description": "한글 글꼴 이름(예: 맑은 고딕)"},
                    "font_latin": {"type": "string", "description": "영문 글꼴 이름(예: Arial)"},
                    "size_pt": {"type": "number", "minimum": 1, "maximum": 4096, "description": "글자 크기(pt)"},
                    "bold": {"type": "boolean"},
                    "italic": {"type": "boolean"},
                    "underline": {"type": "boolean"},
                    "color": {"type": "string", "description": "글자 색 #RRGGBB"},
                    "align": {"type": "string", "enum": ["left", "center", "right", "justify"], "description": "문단 정렬"},
                    "line_spacing_percent": {
                        "type": "integer",
                        "minimum": 50,
                        "maximum": 500,
                        "description": "줄 간격(%)",
                    },
                },
                ["document_id"],
            ),
            self._function(
                "hwp_apply_format",
                "앞서 만든 HWP 서식 미리보기를 원본에 반영하고, 반영한 자리의 서식을 다시 읽어 요청과 맞는지(matches) 돌려준다. "
                "승인 필수이며, 사람이 편집 중이거나 원본이 달라졌으면 실행하지 않는다.",
                {
                    "preview_id": {"type": "string"},
                    "change_summary": {"type": "string", "description": "승인 화면에 보여 줄 서식 변경 요약"},
                    "preview_path": {"type": "string", "description": "preview 결과의 사본 경로"},
                },
                ["preview_id"],
            ),
            self._function(
                "hwp_export_pdf",
                "이 PC 의 한글 파일(.hwp·.hwpx)을 PDF 로 바꾼다. 한글 파일을 PDF 로 바꿀 때는 한글 창을 열지 말고 이 도구를 쓴다. "
                "화면에 안 보이는 한글을 따로 띄워 사본을 PDF 로 저장하고 그 한글만 끈다 — 열려 있는 한글 창과 원본 파일은 "
                "건드리지 않는다. output_path 를 안 주면 원본과 같은 폴더에 같은 이름의 .pdf 로 만들고, 그 자리에 파일이 "
                "이미 있으면 overwrite=true 가 아니면 거절한다. 저장한 뒤 PDF 가 맞는지(%PDF) 다시 본다.",
                {
                    "path": {"type": "string", "description": "PDF 로 바꿀 한글 파일(.hwp·.hwpx) 경로"},
                    "output_path": {
                        "type": "string",
                        "description": "만들 PDF 경로(생략하면 원본 옆에 같은 이름 .pdf, 이름만 주면 원본과 같은 폴더)",
                    },
                    "overwrite": {"type": "boolean", "description": "같은 자리에 파일이 있어도 덮어쓴다"},
                },
                ["path"],
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def _enabled(self) -> bool:
        if not bool(getattr(self.config, "hwp_enabled", True)) or os.name != "nt":
            return False
        try:
            import win32com.client  # noqa: F401
        except Exception:
            return False
        return True

    def status(self) -> dict[str, Any]:
        active = 0
        with self._lock:
            active = sum(
                1 for row in [*self._previews.values(), *self._format_previews.values()]
                if not row.used and row.expires_at >= time.time()
            )
        return {
            "enabled": self._enabled(),
            "preview_first": True,
            "active_previews": active,
            "security_module": str(
                getattr(self.config, "hwp_security_module_name", "FilePathCheckerModuleExample")
            ),
        }

    def _invoke(self, operation: str, **payload: Any) -> dict[str, Any]:
        # ★ 부르는 쪽이 제한시간 바닥을 올릴 수 있다 (2026-10-17 PDF 내보내기). 한글을 새로 띄우고 문서를 다 그려 굽는
        #   일이라 편집용 30초로는 큰 문서가 중간에 잘린다. 프로세스에는 안 넘긴다.
        floor = int(payload.pop("_timeout_floor_sec", 0) or 0)
        request = {
            "operation": operation,
            "module_name": str(
                getattr(self.config, "hwp_security_module_name", "FilePathCheckerModuleExample")
            ),
            **payload,
        }
        timeout = max(5, floor, int(getattr(self.config, "hwp_com_timeout_sec", 30)))
        try:
            process = subprocess.run(  # noqa: S603 - 고정된 현재 Python 모듈만 실행한다.
                [sys.executable, "-m", "alture_jarvis.hwp", "--worker"],
                input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                check=False,
                env={**environment_for_our_own_child(), "PYTHONUTF8": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("hwp_com_timeout_do_not_retry_automatically") from exc
        try:
            envelope = json.loads(process.stdout.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("hwp_worker_invalid_response") from exc
        if process.returncode != 0 or envelope.get("ok") is not True:
            error = str(envelope.get("error") or process.stderr.decode("utf-8", "replace") or "hwp_worker_failed")
            raise RuntimeError(error[:1000])
        return dict(envelope.get("result") or {})

    def _open_rows(self) -> list[dict[str, Any]]:
        try:
            result = self._invoke("list_open")
        except RuntimeError as exc:
            message = str(exc)
            if (
                "hwp_no_running_instance" in message
                or "작업을 사용할 수 없습니다" in message
                or "Operation unavailable" in message
            ):
                return []
            raise
        rows = []
        for row in result.get("documents") or []:
            if not isinstance(row, dict) or not row.get("path"):
                continue
            try:
                path = self.local_computer.resolve_allowed_path(str(row["path"]))
            except Exception:
                continue
            if path.suffix.lower() not in {".hwp", ".hwpx"}:
                continue
            rows.append({**row, "path": str(path)})
        for document_id, row in enumerate(rows, 1):
            row["document_id"] = document_id
        return rows

    def _row(self, document_id: int) -> dict[str, Any]:
        match = next((row for row in self._open_rows() if int(row["document_id"]) == document_id), None)
        if match is None:
            raise RuntimeError("hwp_document_not_open_or_outside_allowed_roots")
        return match

    @staticmethod
    def _job_id(arguments: dict[str, Any]) -> str:
        job_id = str(arguments.get("__job_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError("job_context_required")
        return job_id

    def list_open(self, _arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = self._open_rows()
        return {"action": "hwp_list_open", "count": len(rows), "documents": rows}

    def read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document_id = int(arguments.get("document_id") or 0)
        row = self._row(document_id)
        result = self._invoke(
            "read",
            instance_id=row["instance_id"],
            native_document_id=row["native_document_id"],
            source_path=row["path"],
        )
        maximum = max(1, min(int(arguments.get("max_chars") or _MAX_TEXT), _MAX_TEXT))
        text = str(result.get("text") or "")
        return {
            "action": "hwp_read",
            "document_id": document_id,
            "path": row["path"],
            "text": text[:maximum],
            "char_count": len(text),
            "truncated": len(text) > maximum,
            "modified": bool(result.get("modified")),
        }

    def preview_edit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document_id = int(arguments.get("document_id") or 0)
        old_text = str(arguments.get("old_text") or "")
        new_text = str(arguments.get("new_text") or "")
        if not old_text:
            raise ValueError("old_text_required")
        if old_text == new_text:
            raise ValueError("replacement_makes_no_change")
        if len(old_text) > _MAX_REPLACEMENT or len(new_text) > _MAX_REPLACEMENT:
            raise ValueError("hwp_replacement_too_large")
        row = self._row(document_id)
        if bool(row.get("modified")):
            raise RuntimeError("hwp_document_has_unsaved_edits")
        job_id = self._job_id(arguments)
        workspace = self.local_computer.job_workspace(job_id, create=True)
        preview_dir = workspace / "hwp-previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        source = Path(str(row["path"]))
        preview_path = preview_dir / f"{source.stem}.preview{source.suffix}"
        result = self._invoke(
            "preview_edit",
            instance_id=row["instance_id"],
            native_document_id=row["native_document_id"],
            source_path=str(source),
            preview_path=str(preview_path),
            old_text=old_text,
            new_text=new_text,
            replace_all=bool(arguments.get("replace_all")),
        )
        before_text = str(result.get("before_text") or "")
        after_text = str(result.get("after_text") or "")
        diff = "\n".join(
            difflib.unified_diff(
                before_text.splitlines(),
                after_text.splitlines(),
                fromfile=source.name,
                tofile=preview_path.name,
                lineterm="",
            )
        )[:12_000]
        now = time.time()
        preview = HwpEditPreview(
            preview_id=secrets.token_urlsafe(18),
            document_id=document_id,
            instance_id=str(row["instance_id"]),
            native_document_id=int(row["native_document_id"]),
            source_path=str(source),
            source_sha256=str(result.get("source_sha256") or ""),
            old_text=old_text,
            new_text=new_text,
            replace_all=bool(arguments.get("replace_all")),
            preview_path=str(preview_path),
            diff=diff,
            occurrences=int(result.get("occurrences") or 0),
            created_at=now,
            expires_at=now + max(30, int(getattr(self.config, "hwp_preview_ttl_sec", 300))),
        )
        with self._lock:
            self._previews[preview.preview_id] = preview
            for preview_id, old in list(self._previews.items()):
                if old.used or old.expires_at < now - 60:
                    self._previews.pop(preview_id, None)
        return {
            "action": "hwp_preview_edit",
            "preview_id": preview.preview_id,
            "expires_at": preview.expires_at,
            "document_id": document_id,
            "path": str(source),
            "output_path": str(preview_path),
            "diff": diff,
            "occurrences": preview.occurrences,
            "requires_approval": True,
        }

    def _preview(self, preview_id: str) -> HwpEditPreview:
        with self._lock:
            preview = self._previews.get(preview_id)
        if preview is None:
            raise ValueError("hwp_preview_not_found")
        if preview.used:
            raise RuntimeError("hwp_preview_already_used")
        if preview.expires_at < time.time():
            raise RuntimeError("hwp_preview_expired")
        return preview

    def apply_edit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        preview = self._preview(str(arguments.get("preview_id") or ""))
        job_id = self._job_id(arguments)
        backup_dir = self.local_computer.job_workspace(job_id, create=True) / "backups"
        backup = backup_dir / f"{Path(preview.source_path).name}.{secrets.token_hex(6)}.bak"
        result = self._invoke(
            "apply_edit",
            instance_id=preview.instance_id,
            native_document_id=preview.native_document_id,
            source_path=preview.source_path,
            source_sha256=preview.source_sha256,
            old_text=preview.old_text,
            new_text=preview.new_text,
            replace_all=preview.replace_all,
            backup_path=str(backup),
        )
        if result.get("verified") is not True:
            raise RuntimeError("hwp_apply_unverified_do_not_retry")
        with self._lock:
            preview.used = True
        if self.events is not None:
            self.events.publish(
                "hwp_edit_applied",
                {"path": preview.source_path, "preview_id": preview.preview_id},
            )
        return {
            "action": "hwp_apply_edit",
            "preview_id": preview.preview_id,
            "path": preview.source_path,
            "backup_path": str(backup),
            "before_sha256": str(result.get("before_sha256") or ""),
            "after_sha256": str(result.get("after_sha256") or ""),
            "occurrences": preview.occurrences,
            "verified": True,
            "what_changed": [
                {"old": preview.old_text[:500], "new": preview.new_text[:500], "count": preview.occurrences}
            ],
        }

    def _capture_apply_proof(self, arguments: dict[str, Any]) -> dict[str, Any]:
        preview = self._preview(str(arguments.get("preview_id") or ""))
        path = Path(preview.source_path)
        current_sha = _sha256(path) if path.is_file() else ""
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "preview_id": preview.preview_id,
                    "document_id": preview.document_id,
                    "instance_id": preview.instance_id,
                    "native_document_id": preview.native_document_id,
                    "path": preview.source_path.lower(),
                    "expected_sha256": preview.source_sha256,
                    "current_sha256": current_sha,
                    "old_text": preview.old_text,
                    "new_text": preview.new_text,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "fingerprint": fingerprint,
            "preview_id": preview.preview_id,
            "document_id": preview.document_id,
            "instance_id": preview.instance_id,
            "native_document_id": preview.native_document_id,
            "path": preview.source_path,
            "sha256": current_sha,
            "diff": preview.diff[:4000],
        }

    @staticmethod
    def _finalize_apply_proof(before: dict[str, Any], result: Any) -> dict[str, Any]:
        out = dict(result) if isinstance(result, dict) else {"value": result}
        out["verified"] = out.get("verified") is True
        out["proof"] = {
            "before": dict(before),
            "after": {
                "path": str(out.get("path") or ""),
                "sha256": str(out.get("after_sha256") or ""),
                "verified": out["verified"],
            },
        }
        return out

    @staticmethod
    def _undo_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        required = ("path", "backup_path", "before_sha256", "after_sha256")
        if not result.get("verified") or any(not result.get(key) for key in required):
            return None
        return {key: result[key] for key in required}

    def _undo_apply(self, handle: dict[str, Any]) -> dict[str, Any]:
        rows = self._open_rows()
        source = str(handle.get("path") or "")
        row = next(
            (item for item in rows if str(Path(item["path"]).resolve()).lower() == str(Path(source).resolve()).lower()),
            None,
        )
        if row is None:
            raise RuntimeError("hwp_document_must_be_open_for_undo")
        result = self._invoke(
            "restore",
            instance_id=row["instance_id"],
            native_document_id=int(row["native_document_id"]),
            source_path=source,
            backup_path=str(handle.get("backup_path") or ""),
            before_sha256=str(handle.get("before_sha256") or ""),
            after_sha256=str(handle.get("after_sha256") or ""),
        )
        if result.get("verified") is not True:
            raise RuntimeError("hwp_undo_unverified")
        return {"action": "hwp_undo_edit", **result}

    # ── 서식 바꾸기 (2026-10-17) ────────────────────────────────────────────
    @staticmethod
    def _format_target(arguments: dict[str, Any]) -> tuple[str, bool, str]:
        """대상은 「그 글자」 또는 「문서 전체」 둘 중 하나만. 둘 다거나 둘 다 없으면 거절한다."""
        target_text = str(arguments.get("target_text") or "")
        whole = arguments.get("whole_document")
        if whole is not None and not isinstance(whole, bool):
            raise ValueError("hwp_whole_document_must_be_boolean")
        whole_document = bool(whole)
        if whole_document and target_text:
            raise ValueError("hwp_format_target_text_or_whole_document_not_both")
        if not whole_document and not target_text.strip():
            raise ValueError("hwp_format_target_text_or_whole_document_required")
        if len(target_text) > _MAX_FORMAT_TARGET_TEXT:
            raise ValueError("hwp_format_target_text_too_long")
        if "\n" in target_text or "\r" in target_text:
            # 한글 찾기는 문단을 넘는 글자를 못 찾는다 — 못 찾았다는 말보다 먼저 까닭을 준다.
            raise ValueError("hwp_format_target_text_must_be_one_line")
        occurrence = str(arguments.get("occurrence") or "").strip().lower()
        if occurrence and occurrence not in {"all", "first"}:
            raise ValueError("hwp_format_occurrence_must_be_all_or_first")
        return target_text, whole_document, occurrence

    def preview_format(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document_id = int(arguments.get("document_id") or 0)
        spec = _format_spec(arguments)
        target_text, whole_document, occurrence = self._format_target(arguments)
        row = self._row(document_id)
        if bool(row.get("modified")):
            raise RuntimeError("hwp_document_has_unsaved_edits")
        job_id = self._job_id(arguments)
        workspace = self.local_computer.job_workspace(job_id, create=True)
        preview_dir = workspace / "hwp-previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        source = Path(str(row["path"]))
        preview_path = preview_dir / f"{source.stem}.format-preview{source.suffix}"
        result = self._invoke(
            "preview_format",
            instance_id=row["instance_id"],
            native_document_id=row["native_document_id"],
            source_path=str(source),
            preview_path=str(preview_path),
            spec=spec,
            target_text=target_text,
            whole_document=whole_document,
            occurrence=occurrence,
        )
        readbacks = [dict(item or {}) for item in result.get("readbacks") or []]
        before_shapes = [dict(item or {}) for item in result.get("before_shapes") or []]
        targets = int(result.get("targets") or len(readbacks))
        found = int(result.get("found") or 0)
        mismatches = [
            {"target": index, **mismatch}
            for index, readback in enumerate(readbacks, 1)
            for mismatch in _shape_mismatches(spec, readback)
        ]
        if targets == 0 or len(readbacks) != targets:
            mismatches.append({"target": 0, "item": "targets", "wanted": targets, "got": len(readbacks)})
        where = "문서 전체" if whole_document else f"「{target_text[:60]}」 {targets}곳"
        summary = _format_summary(spec, where)
        now = time.time()
        preview = HwpFormatPreview(
            preview_id=secrets.token_urlsafe(18),
            document_id=document_id,
            instance_id=str(row["instance_id"]),
            native_document_id=int(row["native_document_id"]),
            source_path=str(source),
            source_sha256=str(result.get("source_sha256") or ""),
            spec=spec,
            target_text=target_text,
            whole_document=whole_document,
            occurrence=occurrence,
            preview_path=str(preview_path),
            summary=summary,
            targets=targets,
            found=found,
            created_at=now,
            expires_at=now + max(30, int(getattr(self.config, "hwp_preview_ttl_sec", 300))),
        )
        with self._lock:
            self._format_previews[preview.preview_id] = preview
            for preview_id, old in list(self._format_previews.items()):
                if old.used or old.expires_at < now - 60:
                    self._format_previews.pop(preview_id, None)
        out: dict[str, Any] = {
            "action": "hwp_preview_format",
            "preview_id": preview.preview_id,
            "expires_at": preview.expires_at,
            "document_id": document_id,
            "path": str(source),
            "output_path": str(preview_path),
            "summary": summary,
            "targets": targets,
            "found": found,
            "text_occurrences": int(result.get("text_occurrences") or 0),
            # ★ 본문 글자로 센 수와 한글 찾기가 찾은 수가 다르면 알린다 — 표 · 글상자 안 글자이거나, 찾기가 처음으로
            #   돌아와 일찍 멈춘 것일 수 있다(실제 한글로 재 보기 전이라 조용히 넘기지 않는다).
            "count_differs": (not whole_document) and found != int(result.get("text_occurrences") or 0),
            "value_before": [_friendly_shape(item) for item in before_shapes[:20]],
            "value_after": [_friendly_shape(item) for item in readbacks[:20]],
            "matches": not mismatches,
            "mismatches": mismatches[:40],
            "requires_approval": True,
        }
        if mismatches:
            # ★ 사본에서도 안 맞으면 원본에서도 안 맞는다. 적용을 막지는 않되(글꼴 이름을 고쳐 다시 미리볼 수 있게) 먼저 알린다.
            out["warning"] = (
                "사본에 걸고 다시 읽은 서식이 요청과 다릅니다. 글꼴 이름이 이 PC 에 있는지, 대상 글자가 맞는지 확인한 뒤 "
                "다시 미리보기를 만드세요. 이대로 적용하면 원본도 같은 모양이 됩니다."
            )
        return out

    def _format_preview(self, preview_id: str) -> HwpFormatPreview:
        with self._lock:
            preview = self._format_previews.get(preview_id)
        if preview is None:
            raise ValueError("hwp_preview_not_found")
        if preview.used:
            raise RuntimeError("hwp_preview_already_used")
        if preview.expires_at < time.time():
            raise RuntimeError("hwp_preview_expired")
        return preview

    def apply_format(self, arguments: dict[str, Any]) -> dict[str, Any]:
        preview = self._format_preview(str(arguments.get("preview_id") or ""))
        job_id = self._job_id(arguments)
        backup_dir = self.local_computer.job_workspace(job_id, create=True) / "backups"
        backup = backup_dir / f"{Path(preview.source_path).name}.{secrets.token_hex(6)}.bak"
        result = self._invoke(
            "apply_format",
            instance_id=preview.instance_id,
            native_document_id=preview.native_document_id,
            source_path=preview.source_path,
            source_sha256=preview.source_sha256,
            spec=preview.spec,
            target_text=preview.target_text,
            whole_document=preview.whole_document,
            occurrence=preview.occurrence,
            backup_path=str(backup),
        )
        # ★ 저장까지 끝났다 — 여기서부터는 결과가 어긋나도 예외로 바꾸지 않는다. 바뀐 파일과 되돌리기 손잡이를
        #   잃으면 사람이 되돌릴 길이 없어진다. 어긋남은 verified=false 와 mismatches 로 그대로 알린다
        #   (windows_execute_preview 의 value_after · value_matches 와 같은 뜻).
        with self._lock:
            preview.used = True
        readbacks = [dict(item or {}) for item in result.get("readbacks") or []]
        targets = int(result.get("targets") or len(readbacks))
        mismatches = [
            {"target": index, **mismatch}
            for index, readback in enumerate(readbacks, 1)
            for mismatch in _shape_mismatches(preview.spec, readback)
        ]
        if targets != preview.targets or len(readbacks) != targets:
            mismatches.append({"target": 0, "item": "targets", "wanted": preview.targets, "got": len(readbacks)})
        matches = not mismatches
        if self.events is not None:
            self.events.publish(
                "hwp_format_applied",
                {"path": preview.source_path, "preview_id": preview.preview_id, "matches": matches},
            )
        return {
            "action": "hwp_apply_format",
            "preview_id": preview.preview_id,
            "path": preview.source_path,
            "backup_path": str(backup),
            "before_sha256": str(result.get("before_sha256") or ""),
            "after_sha256": str(result.get("after_sha256") or ""),
            "file_changed": bool(result.get("file_changed")),
            "summary": preview.summary,
            "targets": targets,
            "value_after": [_friendly_shape(item) for item in readbacks[:20]],
            "matches": matches,
            "mismatches": mismatches[:40],
            "verified": matches,
        }

    def _capture_format_proof(self, arguments: dict[str, Any]) -> dict[str, Any]:
        preview = self._format_preview(str(arguments.get("preview_id") or ""))
        path = Path(preview.source_path)
        current_sha = _sha256(path) if path.is_file() else ""
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "preview_id": preview.preview_id,
                    "document_id": preview.document_id,
                    "instance_id": preview.instance_id,
                    "native_document_id": preview.native_document_id,
                    "path": preview.source_path.lower(),
                    "expected_sha256": preview.source_sha256,
                    "current_sha256": current_sha,
                    "spec": preview.spec,
                    "target_text": preview.target_text,
                    "whole_document": preview.whole_document,
                    "occurrence": preview.occurrence,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "fingerprint": fingerprint,
            "preview_id": preview.preview_id,
            "document_id": preview.document_id,
            "instance_id": preview.instance_id,
            "native_document_id": preview.native_document_id,
            "path": preview.source_path,
            "sha256": current_sha,
            "summary": preview.summary,
        }

    @staticmethod
    def _format_undo_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        """서식 되돌리기 손잡이 — 다시 읽은 값이 어긋났어도 **파일이 바뀌었으면** 단다(어긋난 채 남기지 않게)."""
        required = ("path", "backup_path", "before_sha256", "after_sha256")
        if any(not result.get(key) for key in required) or result["before_sha256"] == result["after_sha256"]:
            return None
        return {key: result[key] for key in required}

    # ── PDF 로 내보내기 (2026-10-17) ────────────────────────────────────────
    def _export_target(self, arguments: dict[str, Any]) -> tuple[Path, Path]:
        """원본(읽기 범위 안 · 있어야 함)과 만들 PDF 자리(쓰기 범위 안). 범위 밖이면 local_computer 가 까닭과 함께 거절한다."""
        raw = str(arguments.get("path") or "").strip()
        if not raw:
            raise ValueError("path_required")
        source = self.local_computer.resolve_allowed_path(raw)
        if source.suffix.lower() not in {".hwp", ".hwpx"}:
            raise ValueError("hwp_export_source_must_be_hwp_or_hwpx")
        if not source.is_file():
            raise ValueError("hwp_export_source_not_a_file")
        raw_output = str(arguments.get("output_path") or "").strip()
        if not raw_output:
            wanted = source.with_suffix(".pdf")
        else:
            wanted = Path(os.path.expandvars(raw_output)).expanduser()
            if not wanted.is_absolute():
                # 이름만 주면 원본 옆이다 — 「보고서.pdf 로 만들어 줘」는 대개 같은 폴더를 뜻한다.
                wanted = source.parent / wanted
            if wanted.suffix.lower() != ".pdf":
                if wanted.suffix:
                    raise ValueError("hwp_export_output_must_be_pdf")
                wanted = wanted.with_name(f"{wanted.name}.pdf")
        # ★ 만드는 자리는 **쓰기 범위**로 잰다 — 읽기 범위(비우면 사용자 폴더 전체)로 재면 아무 데나 쓴다.
        output = self.local_computer._resolve(str(wanted), must_exist=False, write=True)
        return source, output

    @staticmethod
    def _overwrite_flag(arguments: dict[str, Any]) -> bool:
        value = arguments.get("overwrite")
        if value is not None and not isinstance(value, bool):
            raise ValueError("hwp_export_overwrite_must_be_boolean")
        return value is True

    def _export_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """새 파일 만들기와 같은 무게(local_write_document 의 `_mutation_risk`): 작업 폴더 · 결과물 폴더면 L1, 그 밖이나
        덮어쓰기면 L2. 모르는 경로는 승인 앞으로 보낸 뒤 핸들러가 정확한 오류를 말한다."""
        try:
            _source, output = self._export_target(arguments)
        except Exception:  # noqa: BLE001
            return RiskLevel.L2
        if output.exists():
            return RiskLevel.L2
        judge = getattr(self.local_computer, "_mutation_risk", None)
        if judge is None:
            return RiskLevel.L2
        try:
            return RiskLevel.parse(judge({"path": str(output), "__job_id": arguments.get("__job_id")}))
        except Exception:  # noqa: BLE001
            return RiskLevel.L2

    def export_pdf(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source, output = self._export_target(arguments)
        overwrite = self._overwrite_flag(arguments)
        if output.is_dir():
            raise ValueError("hwp_export_output_is_a_folder")
        if output.exists() and not overwrite:
            raise FileExistsError("hwp_export_output_exists_set_overwrite_true")
        job_id = self._job_id(arguments)
        work = self.local_computer.job_workspace(job_id, create=True) / "hwp-export" / secrets.token_hex(6)
        work.mkdir(parents=True, exist_ok=True)
        # 원본은 열지 않는다 — 사용자가 같은 파일을 한글에 띄워 두었어도 잠금 · 자동 저장과 엮이지 않게 사본을 연다.
        source_copy = work / f"source{source.suffix.lower()}"
        shutil.copy2(source, source_copy)
        temporary_pdf = work / f"{output.stem}.pdf"
        result = self._invoke(
            "export_pdf",
            source_copy=str(source_copy),
            pdf_path=str(temporary_pdf),
            _timeout_floor_sec=_EXPORT_TIMEOUT_SEC,
        )
        is_pdf, size = _pdf_head_ok(temporary_pdf)
        if not is_pdf:
            # ★ 한글이 「저장했다」고 해도 파일로 판정한다. 아닌 것을 사람 폴더에 PDF 이름으로 두지 않는다 —
            #   결과 칸에 output_path 를 안 실어 계획 층도 산출물로 세지 않는다.
            return {
                "action": "hwp_export_pdf",
                "source_path": str(source),
                "saved_file": None,
                "candidate_path": str(temporary_pdf) if temporary_pdf.exists() else None,
                "bytes": size,
                "hangul_said_saved": bool(result.get("saved")),
                "reason": "pdf_missing" if not temporary_pdf.exists() else ("pdf_empty" if size == 0 else "not_a_pdf"),
                "verified": False,
            }
        output.parent.mkdir(parents=True, exist_ok=True)
        backup = ""
        if output.exists():
            if not overwrite:
                raise FileExistsError("hwp_export_output_exists_set_overwrite_true")
            backup_path = work / f"{output.name}.before"
            shutil.copy2(output, backup_path)
            backup = str(backup_path)
        _atomic_restore(temporary_pdf, output)
        written_ok, written = _pdf_head_ok(output)
        if self.events is not None:
            self.events.publish("hwp_pdf_exported", {"path": str(output), "source": str(source)})
        return {
            "action": "hwp_export_pdf",
            "source_path": str(source),
            "output_path": str(output),
            "saved_file": str(output),
            "bytes": written,
            "pages": _pdf_pages(output),
            "overwrote": bool(backup),
            "backup_path": backup,
            "after_sha256": _sha256(output),
            "verified": written_ok,
        }

    def _describe_export(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # 늦게 가져온다(모듈 사이 순환을 피한다).
        from .local_computer import describe_write_target

        try:
            source, output = self._export_target(arguments)
        except Exception:  # noqa: BLE001 - 카드는 보기만 한다. 오류는 실행 때 핸들러가 정확히 말한다.
            return {}
        card = describe_write_target({"path": str(output)})
        card["source"] = str(source)
        card["overwrite"] = output.exists()
        return card

    @staticmethod
    def _export_undo_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        if result.get("verified") is not True or not result.get("output_path") or not result.get("after_sha256"):
            return None
        return {
            "output_path": result["output_path"],
            "after_sha256": result["after_sha256"],
            "backup_path": str(result.get("backup_path") or ""),
        }

    def _undo_export(self, handle: dict[str, Any]) -> dict[str, Any]:
        """만든 PDF 를 지운다. 덮어쓴 것이면 덮기 전 파일로 되돌린다. 그 사이 바뀌었으면 손대지 않는다."""
        output = Path(str(handle.get("output_path") or ""))
        if not output.is_file() or _sha256(output) != str(handle.get("after_sha256") or ""):
            raise RuntimeError("hwp_export_pdf_changed_since_export")
        backup = Path(str(handle.get("backup_path") or "")) if handle.get("backup_path") else None
        if backup is not None:
            if not backup.is_file():
                raise RuntimeError("hwp_export_backup_missing")
            _atomic_restore(backup, output)
            verified = output.is_file() and _sha256(output) == _sha256(backup)
        else:
            output.unlink()
            verified = not output.exists()
        return {"action": "hwp_export_pdf_undo", "path": str(output), "restored": backup is not None, "verified": verified}

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "hwp_list_open": self.list_open,
            "hwp_read": self.read,
            "hwp_preview_edit": self.preview_edit,
            "hwp_apply_edit": self.apply_edit,
            "hwp_preview_format": self.preview_format,
            "hwp_apply_format": self.apply_format,
            "hwp_export_pdf": self.export_pdf,
        }
        # ★ 서식도 글자 바꾸기와 같은 무게다 — 미리보기는 사본만 만드니 L1, 원본 반영은 승인 L2 (2026-10-17).
        risks = {
            "hwp_list_open": RiskLevel.L0,
            "hwp_read": RiskLevel.L1,
            "hwp_preview_edit": RiskLevel.L1,
            "hwp_apply_edit": RiskLevel.L2,
            "hwp_preview_format": RiskLevel.L1,
            "hwp_apply_format": RiskLevel.L2,
            # ★ PDF 내보내기는 「새 파일 만들기」다 — local_write_document 처럼 바닥 L1, 자리에 따라 `_export_risk` 가 올린다.
            "hwp_export_pdf": RiskLevel.L1,
        }
        inverses = {
            "hwp_apply_edit": self._undo_handle,
            "hwp_apply_format": self._format_undo_handle,
            "hwp_export_pdf": self._export_undo_handle,
        }
        undos = {"hwp_export_pdf": self._undo_export}
        labels = {"hwp_export_pdf": "만든 PDF 를 지우거나 덮기 전 파일로 되돌리기"}
        # 승인 카드(L2 — 결과물 폴더 밖이거나 덮어쓰기)에 **실제로 만들 자리**를 보인다. 인자는 그대로 둔다.
        gateway.approval_describers["hwp_export_pdf"] = self._describe_export
        proofs = {
            "hwp_apply_edit": self._capture_apply_proof,
            "hwp_apply_format": self._capture_format_proof,
        }
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=risks[name],
                    handler=handlers[name],
                    enabled=self._enabled(),
                    dynamic_risk=self._export_risk if name == "hwp_export_pdf" else None,
                    inverse=(
                        InverseSpec(
                            label=labels.get(name, "한글 문서를 적용 전 백업으로 되돌리기"),
                            handle_from=inverses[name],
                            undo=undos.get(name, self._undo_apply),
                        )
                        if name in inverses else None
                    ),
                    proof=(
                        ProofSpec(
                            capture_before=proofs[name],
                            capture_current=proofs[name],
                            same_target=same_fingerprint,
                            finalize=self._finalize_apply_proof,
                        )
                        if name in proofs else None
                    ),
                    needs_job_context=name in {
                        "hwp_preview_edit", "hwp_apply_edit", "hwp_preview_format", "hwp_apply_format", "hwp_export_pdf",
                    },
                )
            )


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", action="store_true")
    args, _ = parser.parse_known_args()
    return _worker_main() if args.worker else 2


if __name__ == "__main__":
    raise SystemExit(main())
