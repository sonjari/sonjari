"""한글 양식 채우기 · 그림 넣기 · 쪽수(hwp_preview_fill → hwp_apply_fill) — 가짜 한글로 잰다 (2026-11-23).

계기: 정부 지원사업 신청서(한글 양식)에 요약서를 넣을 때 손자리 한글 도구로는 가이드 문구 지우기 · 여러 줄 · 그림 ·
쪽수 재기를 못 해서 클로드가 한글 자동화를 직접 몰았다. 그때 넣은 본문이 장평 0 · 크기 0 으로 들어가 글씨가 안 보이고
쪽수가 거짓으로 나왔다. 이 시험은 네 층을 본다.

1. 인자 거르기 — 한글에 닿기 전에 막는다(그림 경로는 읽기 범위 안 · 크기 · 찾을 글 한 줄)
2. 한글 호출 순서(`_fill_active`) — 가이드 문단째 지우기 · 줄마다 BreakPara · 0 인 장평/크기를 7개 언어 다 100 으로 ·
   그림 InsertPicture 인자와 TreatAsChar · 쪽수, 그리고 11-23 함정(다시 꺼낸 빈 셋)을 되살리면 멈추는지
3. 도구 층 — 미리보기(쪽수 · fits · lines_missing) → 승인 적용(사본 그대로 끼우기) → 되돌리기 · 승인 지문
4. 등록 자리 — 쓰기 손 목록 등 열 곳이 넘는다. 한 곳만 빠져도 조용히 틀린다.

★ 가짜가 흉내 내는 한글의 동작은 2026-11-23 한글 2022 숨김 인스턴스로 잰 것이다(hwp.py 주석): 찾기 → Cancel 뒤 캐럿은
  찾은 글의 끝, InsertPicture 는 gso 조종을 주고 폭을 HWPUNIT 로 되읽는다, 캐럿에서는 0 인 장평이 0 으로 읽힌다.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import hwp as hwp_module
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.hwp import HwpTools, _fill_active, _fill_ops, _lines_expected_in_pdf, _picture_aspect, _sha256
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway

_ALL = hwp_module._RATIO_SIZE_ITEMS


def _png(path: Path, width: int, height: int) -> Path:
    """머리(IHDR)만 맞는 PNG — 비율 읽기 시험용. 한글로 열 일은 없다."""
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0d" + b"IHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00" + b"\x00" * 4
    )
    return path


# ── 1. 인자 ─────────────────────────────────────────────────────────────────────
def test_picture_height_follows_the_image_proportions(tmp_path: Path) -> None:
    picture = _png(tmp_path / "그림.png", 800, 400)
    assert _picture_aspect(picture) == 0.5
    ops = _fill_ops({"operations": [{"kind": "picture", "find": "[그림 1]", "path": str(picture), "width_mm": 160}]},
                    lambda raw: Path(raw))
    assert ops == [{"kind": "picture", "find": "[그림 1]", "path": str(picture), "width_mm": 160, "height_mm": 80,
                    "replace_paragraph": False}]


@pytest.mark.parametrize(
    ("operations", "code"),
    [
        ([], "operations_required"),
        ([{"kind": "table", "find": "가"}], "kind_must_be_text_or_picture"),
        ([{"kind": "text", "find": "", "lines": ["가"]}], "find_required"),
        ([{"kind": "text", "find": "가\n나", "lines": ["가"]}], "find_must_be_one_line"),
        ([{"kind": "text", "find": "가", "lines": []}], "lines_must_be_a_list"),
        ([{"kind": "text", "find": "가", "lines": ["가"], "size_pt": 0}], "size_pt_out_of_range"),
        ([{"kind": "text", "find": "가", "lines": ["가"], "replace_paragraph": "yes"}], "replace_paragraph_must_be_boolean"),
        ([{"kind": "picture", "find": "가", "path": "PICTURE", "width_mm": 1}], "width_mm_out_of_range"),
        ([{"kind": "picture", "find": "가", "path": "PICTURE", "width_mm": True}], "width_mm_must_be_a_number"),
        ([{"kind": "picture", "find": "가", "path": "NOT_PNG"}], "must_be_png_jpg_bmp_or_gif"),
        ([{"kind": "picture", "find": "가", "path": "UNKNOWN_HEAD"}], "height_mm_required"),
        ([{"kind": "text", "find": "가", "lines": ["가"]}] * 21, "too_many_operations"),
    ],
)
def test_bad_fill_arguments_are_refused(tmp_path: Path, operations: list[dict[str, Any]], code: str) -> None:
    files = {
        "PICTURE": _png(tmp_path / "a.png", 10, 10),
        "NOT_PNG": tmp_path / "a.txt",
        "UNKNOWN_HEAD": tmp_path / "b.png",
    }
    files["NOT_PNG"].write_text("x", encoding="utf-8")
    files["UNKNOWN_HEAD"].write_bytes(b"not an image")
    ops = [{**op, "path": str(files.get(op.get("path", ""), op.get("path", "")))} if "path" in op else op for op in operations]
    with pytest.raises(ValueError, match=code):
        _fill_ops({"operations": ops}, lambda raw: Path(raw))


def test_lines_replaced_by_a_later_step_are_not_expected_in_the_pdf() -> None:
    """실제 한글 첫 판(11-23)의 헛경고: 「[그림 1] 자리」는 뒤 걸음이 그림으로 바꾼 줄이라 PDF 에 없어야 맞다."""
    ops = [
        {"kind": "text", "find": "* 가이드", "lines": ["첫 줄", "[그림 1] 자리", "끝 줄"], "replace_paragraph": True},
        {"kind": "picture", "find": "[그림 1] 자리", "path": "x.png", "width_mm": 100, "height_mm": 50, "replace_paragraph": True},
    ]
    assert _lines_expected_in_pdf(ops) == ["첫 줄", "끝 줄"]
    ops[1]["replace_paragraph"] = False  # 그 문단 뒤에 넣으면 자리표시 줄은 남는다
    assert _lines_expected_in_pdf(ops) == ["첫 줄", "[그림 1] 자리", "끝 줄"]


# ── 2. 한글 호출 순서 — 가짜 한글 ─────────────────────────────────────────────────
class _Bag:
    def __init__(self) -> None:
        self.HSet = object()

    def values(self) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items() if k != "HSet"}

    def reset(self) -> None:
        for key in list(self.values()):
            delattr(self, key)

    def __getattr__(self, name: str) -> Any:  # 한글 셋처럼 없는 항목은 0 으로 읽힌다
        if name.startswith("__"):
            raise AttributeError(name)
        return 0


class _Reader:
    def __init__(self, items: dict[str, Any]) -> None:
        self.items = items

    def ItemExist(self, name: str) -> bool:  # noqa: N802
        return name in self.items

    def Item(self, name: str) -> Any:  # noqa: N802
        return self.items[name]


class _Props(_Reader):
    def SetItem(self, name: str, value: Any) -> None:  # noqa: N802
        self.items[name] = value


class _Ctrl:
    def __init__(self, width_mm: int, *, keep_floating: bool) -> None:
        self.CtrlID = "gso"
        self.keep_floating = keep_floating
        self._props = {"TreatAsChar": 0, "Width": round(width_mm * 7200 / 25.4)}

    @property
    def Properties(self) -> _Props:  # noqa: N802
        return _Props(dict(self._props))

    @Properties.setter
    def Properties(self, value: _Props) -> None:  # noqa: N802
        items = dict(value.items)
        if self.keep_floating:
            items["TreatAsChar"] = 0  # 한글이 글자처럼을 안 받아 준 판
        self._props = items


#: 양식의 작성 가이드 모양 — 파란 기울임(실제 지원사업 양식을 PDF 로 떠서 본 모양). 넣은 글이 이걸 물려받으면 안 된다.
_FORM_CHAR = {"Height": 1000, "Bold": 0, "Italic": 1, "TextColor": 0xFF0000, **{name: 100 for name in _ALL}}
_FORM_PARA = {"PrevSpacing": 0, "NextSpacing": 0, "LineSpacingType": 0, "LineSpacing": 130}


class _FillHwp:
    """문단 목록 하나짜리 한글. 글자마다 글자 모양을 들고, 캐럿 자리의 「칠 모양」(input)을 따로 든다.

    empty_defaults=True 면 GetDefault 가 셋을 안 채운다(11-23 함정의 빈 셋과 같은 모양 — 항목을 읽으면 0).
    Execute("CharShape") 는 선택이 없으면 칠 모양을 **셋 그대로** 바꾼다 — 셋에 없는 항목은 0 이 된다(캐럿 실측).
    """

    def __init__(self, paras: list[str], *, empty_defaults: bool = False, form_ratio: int = 100,
                 keep_floating: bool = False) -> None:
        self.paras = list(paras)
        self.empty_defaults, self.keep_floating = empty_defaults, keep_floating
        self.char: dict[tuple[int, int], dict[str, Any]] = {}
        self.input = {**_FORM_CHAR, **{name: form_ratio for name in _ALL if name.startswith("Ratio")}}
        self.para_shape = dict(_FORM_PARA)
        self.caret = (0, 0, 0)
        self.sel: tuple[tuple[int, int], tuple[int, int]] | None = None
        self.HParameterSet = SimpleNamespace(
            HFindReplace=_Bag(), HCharShape=_Bag(), HParaShape=_Bag(), HInsertText=_Bag()
        )
        self.HAction = SimpleNamespace(Run=self._run, GetDefault=self._get_default, Execute=self._execute)
        self.pictures: list[tuple[Any, ...]] = []
        self.runs: list[str] = []

    # 읽기
    @property
    def PageCount(self) -> int:  # noqa: N802
        return 1 + sum(len(p) for p in self.paras) // 40 + len(self.pictures)

    @property
    def CharShape(self) -> _Reader:  # noqa: N802
        return _Reader(dict(self.input))

    @property
    def ParaShape(self) -> _Reader:  # noqa: N802
        return _Reader(dict(self.para_shape))

    def CreateAction(self, action_id: str) -> Any:  # noqa: N802
        source = self.input if action_id == "CharShape" else self.para_shape
        reader = _Reader({})
        return SimpleNamespace(CreateSet=lambda: reader, GetDefault=lambda r: setattr(r, "items", dict(source)))

    def FindDir(self, name: str) -> int:  # noqa: N802
        return 0

    def GetPos(self) -> tuple[int, int, int]:  # noqa: N802
        return self.caret

    def SetPos(self, list_id: int, para: int, pos: int) -> bool:  # noqa: N802
        self.sel, self.caret = None, (list_id, para, pos)
        return True

    def GetTextFile(self, _format: str, _option: str) -> str:  # noqa: N802
        return "\r\n".join(self.paras)

    # 움직임
    def _bag(self, hset: Any) -> _Bag:
        return next(bag for bag in vars(self.HParameterSet).values() if bag.HSet is hset)

    def _run(self, action_id: str) -> bool:
        self.runs.append(action_id)
        _l, para, pos = self.caret
        if action_id == "Cancel":
            self.sel = None
        elif action_id == "MoveDocBegin":
            self.sel, self.caret = None, (0, 0, 0)
        elif action_id == "MoveParaBegin":
            self.caret = (0, para, 0)
        elif action_id == "MoveParaEnd":
            self.caret = (0, para, len(self.paras[para]))
        elif action_id == "MoveSelParaEnd":
            self.sel = ((para, pos), (para, len(self.paras[para])))
            self.caret = (0, para, len(self.paras[para]))
        elif action_id == "Delete":
            assert self.sel is not None
            (sp, spos), (_ep, epos) = self.sel
            self.paras[sp] = self.paras[sp][:spos] + self.paras[sp][epos:]
            self.sel, self.caret = None, (0, sp, spos)
        elif action_id == "BreakPara":
            text = self.paras[para]
            self.paras[para:para + 1] = [text[:pos], text[pos:]]
            self.char = {(p + 1 if p > para else p, i): v for (p, i), v in self.char.items()}
            self.caret = (0, para + 1, 0)
        elif action_id == "MoveLeft":
            self.sel, self.caret = None, (0, para, max(0, pos - 1))
        else:
            raise AssertionError(action_id)
        return True

    def _get_default(self, action_id: str, hset: Any) -> None:
        bag = self._bag(hset)
        bag.reset()
        if self.empty_defaults or action_id in {"RepeatFind", "InsertText"}:
            return
        for key, value in (self.input if action_id == "CharShape" else self.para_shape).items():
            setattr(bag, key, value)

    def _execute(self, action_id: str, hset: Any) -> bool:
        bag = self._bag(hset)
        values = bag.values()
        if action_id == "RepeatFind":
            return self._find(str(values["FindString"]))
        if action_id == "CharShape":
            assert self.sel is None, "채우기는 선택 없이 캐럿에서 건다"
            self.input = {key: values.get(key, 0) for key in _FORM_CHAR}
            return True
        if action_id == "ParagraphShape":
            self.para_shape = {key: values.get(key, 0) for key in _FORM_PARA}
            return True
        if action_id == "InsertText":
            _l, para, pos = self.caret
            text = str(values["Text"])
            self.paras[para] = self.paras[para][:pos] + text + self.paras[para][pos:]
            for i in range(len(text)):
                self.char[(para, pos + i)] = dict(self.input)
            self.caret = (0, para, pos + len(text))
            return True
        raise AssertionError(action_id)

    def _find(self, text: str) -> bool:
        para, pos = self.sel[1] if self.sel else self.caret[1:]
        for index in range(para, len(self.paras)):
            start = self.paras[index].find(text, pos if index == para else 0)
            if start >= 0:
                self.sel = ((index, start), (index, start + len(text)))
                self.caret = (0, index, start + len(text))
                return True
        return False

    def InsertPicture(self, *args: Any) -> _Ctrl:  # noqa: N802
        self.pictures.append(args)
        _l, para, pos = self.caret
        self.paras[para] = self.paras[para][:pos] + "▣" + self.paras[para][pos:]
        self.caret = (0, para, pos + 1)
        return _Ctrl(int(args[6]), keep_floating=self.keep_floating)


_FORM = ["요 약 서", "3. 과제 목표", "* 본 사업수행을 통해 달성하고자 하는 목표를 기술", "4. 추진 방법", "* 목표를 달성하기 위한 방법"]


def _text_op(find: str, lines: list[str], **extra: Any) -> dict[str, Any]:
    return _fill_ops({"operations": [{"kind": "text", "find": find, "lines": lines, **extra}]}, lambda raw: Path(raw))[0]


def test_guide_paragraph_is_replaced_by_lines_and_an_empty_set_is_filled_for_all_seven_languages() -> None:
    """빈 셋(GetDefault 가 안 채움)에서도 7개 언어의 장평 · 크기가 100 으로 들어가 글씨가 보인다."""
    hwp = _FillHwp(_FORM, empty_defaults=True)
    result = _fill_active(hwp, [_text_op("* 본 사업수행을 통해", ["□ 목표", "- 첫째", "- 둘째"])])

    assert hwp.paras == ["요 약 서", "3. 과제 목표", "□ 목표", "- 첫째", "- 둘째", "4. 추진 방법", "* 목표를 달성하기 위한 방법"]
    inserted = [hwp.char[(2, 0)], hwp.char[(4, 3)]]
    for shape in inserted:
        assert all(shape[name] == 100 for name in _ALL), shape  # Ratio · Size × 7개 언어
        assert shape["Height"] == 1000
        assert shape["Italic"] == 0 and shape["TextColor"] == 0  # 가이드의 파란 기울임을 안 물려받는다
    done = result["done"][0]
    assert set(_ALL) <= set(done["repaired"]) and "Height" in done["repaired"] and "LineSpacing" in done["repaired"]
    assert hwp.para_shape["LineSpacing"] == 160
    assert done["char_after"]["RatioHangul"] == 100 and done["char_after"]["SizeHangul"] == 100
    assert hwp.runs.count("BreakPara") == 2
    assert ["MoveParaBegin", "MoveSelParaEnd", "Delete"] == hwp.runs[hwp.runs.index("MoveParaBegin"):][:3]


def test_the_forms_own_ratio_is_kept_and_size_and_bold_are_applied() -> None:
    """캐럿 자리에는 섞인 값이 없다 — 양식이 쓰던 장평 95% 는 그대로 이어받는다(0 만 고친다)."""
    hwp = _FillHwp(_FORM, form_ratio=95)
    result = _fill_active(hwp, [_text_op("* 목표를 달성하기 위한", ["굵은 줄"], size_pt=11, bold=True, color="#1A2B3C", italic=True)])
    shape = hwp.char[(4, 0)]
    assert shape["RatioHangul"] == 95 and shape["SizeHangul"] == 100 and shape["Height"] == 1100 and shape["Bold"] == 1
    assert shape["Italic"] == 1 and shape["TextColor"] == 0x3C2B1A  # 시키면 그대로
    assert result["done"][0]["repaired"] == []


def test_the_11_23_trap_is_caught_when_someone_brings_back_the_refetched_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """GetDefault 뒤 셋을 **다시 꺼내** 값 몇 개만 넣는 옛 모양 — 넣은 글이 장평 0 이 되고, 되읽기가 멈춘다."""

    def trap(hwp: Any, op: dict[str, Any]) -> list[str]:
        hwp.HAction.GetDefault("CharShape", hwp.HParameterSet.HCharShape.HSet)
        fresh = _Bag()  # 실제 한글에서 다시 꺼낸 셋은 채워지지 않은 빈 셋이었다
        hwp.HParameterSet.HCharShape = fresh
        fresh.Height = 1000
        hwp.HAction.Execute("CharShape", fresh.HSet)
        return []

    monkeypatch.setattr(hwp_module, "_fill_char_shape", trap)
    with pytest.raises(RuntimeError, match="hwp_fill_text_invisible_zero_shape:RatioHangul,SizeHangul"):
        _fill_active(_FillHwp(_FORM), [_text_op("* 본 사업수행을 통해", ["안 보이는 줄"])])


def test_picture_is_inserted_with_the_verified_arguments_and_treated_as_a_character(tmp_path: Path) -> None:
    picture = _png(tmp_path / "그림.png", 1000, 450)
    hwp = _FillHwp(_FORM)
    ops = _fill_ops(
        {
            "operations": [
                {"kind": "text", "find": "* 본 사업수행을 통해", "lines": ["- 위 줄", "[그림 1] 자리", "- 아래 줄"]},
                {"kind": "picture", "find": "[그림 1] 자리", "path": str(picture), "width_mm": 120, "replace_paragraph": True},
                {"kind": "picture", "find": "4. 추진 방법", "path": str(picture), "width_mm": 60, "height_mm": 30},
            ]
        },
        lambda raw: Path(raw),
    )
    result = _fill_active(hwp, ops)

    assert hwp.pictures == [(str(picture), True, 1, False, False, 0, 120, 54), (str(picture), True, 1, False, False, 0, 60, 30)]
    assert hwp.paras[2:5] == ["- 위 줄", "▣", "- 아래 줄"]  # 자리표시 문단이 그림이 됐다
    assert hwp.paras[5:7] == ["4. 추진 방법", "▣"]  # 기본은 찾은 문단 뒤 새 문단
    pictures = [row for row in result["done"] if row["kind"] == "picture"]
    assert [row["treat_as_char"] for row in pictures] == [True, True]
    assert [row["width_mm"] for row in pictures] == [120.0, 60.0]
    assert result["pages_before"] == 2 and result["pages_after"] == hwp.PageCount == 4  # 그림 두 장이 한 쪽씩


def test_a_picture_hangul_left_floating_stops() -> None:
    hwp = _FillHwp(_FORM, keep_floating=True)
    op = {"kind": "picture", "find": "4. 추진 방법", "path": "x.png", "width_mm": 50, "height_mm": 20, "replace_paragraph": False}
    with pytest.raises(RuntimeError, match="not_treated_as_char"):
        _fill_active(hwp, [op])


def test_find_must_be_unique_and_present() -> None:
    with pytest.raises(RuntimeError, match="not_unique"):
        _fill_active(_FillHwp(_FORM), [_text_op("목표", ["가"])])
    with pytest.raises(RuntimeError, match="not_found"):
        _fill_active(_FillHwp(_FORM), [_text_op("없는 가이드", ["가"])])


# ── 3. 도구 층 ──────────────────────────────────────────────────────────────────
def _stack(tmp_path: Path) -> tuple[HwpTools, ToolGateway, Path, Path]:
    allowed = tmp_path / "allowed"
    allowed.mkdir(parents=True)
    source = allowed / "신청서.hwp"
    source.write_bytes(b"before-hwp")
    picture = _png(allowed / "그림.png", 400, 200)
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed), local_read_roots=str(allowed), hwp_enabled=True,
    )
    tools = HwpTools(config, LocalComputerTools(config), EventBus())
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    tools.register(gateway)
    return tools, gateway, source, picture


def _fake_com(tools: HwpTools, source: Path, *, pages: int = 3) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def invoke(operation: str, **payload: Any) -> dict[str, Any]:
        calls.append((operation, payload))
        if operation == "list_open":
            return {"documents": [{"native_document_id": 7, "instance_id": "!HwpObject.t", "path": str(source),
                                   "name": source.name, "format": "HWP", "modified": False}]}
        if operation == "preview_fill":
            preview = Path(payload["preview_path"])
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_bytes(b"filled-hwp")
            Path(payload["pdf_path"]).write_bytes(b"%PDF-1.7 fake")
            return {"source_sha256": _sha256(source), "preview_sha256": _sha256(preview), "pages_before": 2,
                    "pages_after": pages, "done": [{"kind": "text"}]}
        if operation == "apply_fill":
            assert _sha256(Path(payload["preview_path"])) == payload["preview_sha256"]
            backup = Path(payload["backup_path"])
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            before = _sha256(source)
            shutil.copy2(Path(payload["preview_path"]), source)
            after = _sha256(source)
            return {"backup_path": str(backup), "before_sha256": before, "after_sha256": after, "reopened": True,
                    "verified": after == payload["preview_sha256"]}
        if operation == "restore":
            shutil.copy2(Path(payload["backup_path"]), source)
            return {"path": str(source), "restored_sha256": _sha256(source), "reopened": True, "verified": True}
        raise AssertionError(operation)

    tools._invoke = invoke  # type: ignore[method-assign]
    return calls


def _readback(pages: int, missing: list[str] | None = None, images: int = 1) -> Any:
    return lambda _pdf, lines: {"pages": pages, "images": images, "lines_checked": len(lines), "lines_missing": missing or []}


def test_fill_tools_are_registered_like_the_format_tools(tmp_path: Path) -> None:
    _tools, gateway, _source, _picture = _stack(tmp_path)
    specs = gateway._tools
    assert specs["hwp_preview_fill"].risk_level is RiskLevel.L1
    assert specs["hwp_apply_fill"].risk_level is RiskLevel.L2
    assert specs["hwp_apply_fill"].inverse is not None and specs["hwp_apply_fill"].proof is not None
    assert specs["hwp_preview_fill"].inverse is None and specs["hwp_preview_fill"].proof is None
    assert specs["hwp_preview_fill"].needs_job_context and specs["hwp_apply_fill"].needs_job_context


def test_bad_arguments_and_pictures_outside_the_allowed_folders_never_reach_hangul(tmp_path: Path) -> None:
    tools, _gateway, source, picture = _stack(tmp_path)
    calls = _fake_com(tools, source)
    outside = _png(tmp_path / "밖.png", 10, 10)
    for arguments, error in (
        ({"operations": []}, ValueError),
        ({"operations": [{"kind": "picture", "find": "가", "path": str(outside)}]}, Exception),
        ({"operations": [{"kind": "text", "find": "가", "lines": ["나"]}], "max_pages": 0}, ValueError),
    ):
        with pytest.raises(error):
            tools.preview_fill({"document_id": 1, **arguments, "__job_id": "job-bad"})
    assert all(name != "preview_fill" for name, _payload in calls)
    assert picture.is_file()


def test_preview_reports_pages_fit_and_a_missing_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools, _gateway, source, picture = _stack(tmp_path)
    calls = _fake_com(tools, source, pages=4)
    monkeypatch.setattr(hwp_module, "_pdf_readback", _readback(4, missing=["- 둘째"]))
    before = source.read_bytes()

    result = tools.preview_fill(
        {
            "document_id": 1,
            "operations": [
                {"kind": "text", "find": "* 본 사업수행을 통해", "lines": ["- 첫째", "- 둘째"]},
                {"kind": "picture", "find": "4. 추진 방법", "path": str(picture), "width_mm": 100},
            ],
            "max_pages": 3,
            "__job_id": "job-preview",
        }
    )

    assert source.read_bytes() == before
    assert result["pages"] == 4 and result["pages_hangul"] == 4 and result["pages_pdf"] == 4 and result["pages_before"] == 2
    assert result["fits"] is False and "3쪽을 넘습니다" in result["next"]
    assert result["verified"] is False and "lines_missing" in result["warning"]
    assert result["requires_approval"] is True and Path(result["output_path"]).is_file()
    sent = dict(calls[-1][1])
    assert calls[-1][0] == "preview_fill"
    assert sent["ops"][1] == {"kind": "picture", "find": "4. 추진 방법", "path": str(picture.resolve()), "width_mm": 100,
                              "height_mm": 50, "replace_paragraph": False}


def test_hangul_and_pdf_page_counts_that_differ_are_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools, _gateway, source, _picture = _stack(tmp_path)
    _fake_com(tools, source, pages=3)
    monkeypatch.setattr(hwp_module, "_pdf_readback", _readback(4))
    result = tools.preview_fill({"document_id": 1, "operations": [{"kind": "text", "find": "가", "lines": ["나"]}],
                                 "__job_id": "job-pages"})
    assert result["pages"] == 4 and result["verified"] is False and "쪽수(3)" in result["warning"]


def test_apply_puts_the_reviewed_copy_in_place_and_undo_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools, gateway, source, _picture = _stack(tmp_path)
    _fake_com(tools, source)
    monkeypatch.setattr(hwp_module, "_pdf_readback", _readback(3))
    preview = tools.preview_fill({"document_id": 1, "operations": [{"kind": "text", "find": "가", "lines": ["나"]}],
                                  "max_pages": 3, "__job_id": "job-apply"})
    assert preview["verified"] is True and preview["fits"] is True
    original = source.read_bytes()

    applied = tools.apply_fill({"preview_id": preview["preview_id"], "__job_id": "job-apply"})

    assert applied["verified"] is True and source.read_bytes() == b"filled-hwp" and applied["pages"] == 3
    with pytest.raises(RuntimeError, match="already_used"):
        tools.apply_fill({"preview_id": preview["preview_id"], "__job_id": "job-apply"})
    inverse = gateway._tools["hwp_apply_fill"].inverse
    assert inverse is not None and inverse.undo is not None
    handle = inverse.handle_from(applied)
    assert handle is not None and inverse.undo(handle)["verified"] is True
    assert source.read_bytes() == original


def test_approval_fingerprint_binds_the_source_and_the_reviewed_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools, _gateway, source, _picture = _stack(tmp_path)
    _fake_com(tools, source)
    monkeypatch.setattr(hwp_module, "_pdf_readback", _readback(3))
    preview = tools.preview_fill({"document_id": 1, "operations": [{"kind": "text", "find": "가", "lines": ["나"]}],
                                  "__job_id": "job-proof"})
    arguments = {"preview_id": preview["preview_id"], "__job_id": "job-proof"}
    first = tools._capture_fill_proof(arguments)["fingerprint"]
    Path(preview["output_path"]).write_bytes(b"someone-changed-the-copy")
    assert tools._capture_fill_proof(arguments)["fingerprint"] != first
    Path(preview["output_path"]).write_bytes(b"filled-hwp")
    source.write_bytes(b"human-changed-the-source")
    assert tools._capture_fill_proof(arguments)["fingerprint"] != first


# ── 작업자(apply_fill) — 원본 자리 끼우기 ────────────────────────────────────────
class _Docs:
    """한글의 열린 문서 목록 — 닫으면 빠지고, Open 은 「지금 문서」(맨 끝)를 **교체**한다(2026-11-23 실측)."""

    def __init__(self) -> None:
        self.rows: list[_Doc] = []
        self.added = 0

    @property
    def Count(self) -> int:  # noqa: N802
        return len(self.rows)

    def Item(self, index: int) -> _Doc:  # noqa: N802
        return self.rows[index]

    def Add(self, _visible: bool) -> None:  # noqa: N802
        self.added += 1
        self.rows.append(_Doc(None, self))


class _Doc:
    def __init__(self, path: Path | None, docs: _Docs, *, modified: bool = False, document_id: int = 7) -> None:
        self.DocumentID = document_id
        self.FullName = str(path) if path else ""
        self.Modified = modified
        self.docs = docs
        self.closed = 0

    def SetActive_XHwpDocument(self) -> None:  # noqa: N802
        return None

    def Close(self, _save: bool) -> None:  # noqa: N802
        self.closed += 1
        self.docs.rows.remove(self)
        if not self.docs.rows:
            self.docs.rows.append(_Doc(None, self.docs))  # 혼자였으면 빈 문서 하나가 남는다


def _worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, other: bool = False) -> tuple[Path, Path, _Doc, SimpleNamespace]:
    source = tmp_path / "신청서.hwp"
    source.write_bytes(b"original")
    preview = tmp_path / "신청서.fill-preview.hwp"
    preview.write_bytes(b"reviewed")
    docs = _Docs()
    document = _Doc(source, docs)
    docs.rows.append(document)
    if other:
        docs.rows.append(_Doc(tmp_path / "다른문서.hwp", docs, modified=True, document_id=8))
    opened: list[str] = []

    def open_(path: str, _fmt: str, _arg: str) -> bool:
        opened.append(path)
        docs.rows[-1] = _Doc(Path(path), docs)  # 지금 문서를 교체한다
        return True

    fake = SimpleNamespace(IsModified=False, XHwpDocuments=docs, Open=open_, opened=opened)
    monkeypatch.setattr(
        hwp_module, "_running_hwp_objects",
        lambda _module: ([("!HwpObject.t", fake)], SimpleNamespace(CoUninitialize=lambda: None)),
    )
    return source, preview, document, fake


def _apply_payload(tmp_path: Path, source: Path, preview: Path, **override: Any) -> dict[str, Any]:
    return {
        "operation": "apply_fill", "instance_id": "!HwpObject.t", "native_document_id": 7, "source_path": str(source),
        "source_sha256": _sha256(source), "preview_path": str(preview), "preview_sha256": _sha256(preview),
        "backup_path": str(tmp_path / "backups" / "신청서.hwp.bak"), **override,
    }


def test_worker_swaps_in_exactly_the_reviewed_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, preview, document, fake = _worker(tmp_path, monkeypatch)
    result = hwp_module._worker_operation(_apply_payload(tmp_path, source, preview))
    assert result["verified"] is True and result["reopened"] is True
    assert source.read_bytes() == b"reviewed" and (tmp_path / "backups" / "신청서.hwp.bak").read_bytes() == b"original"
    assert document.closed == 1 and fake.opened == [str(source)]


def test_reopening_does_not_replace_another_open_document_with_unsaved_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """실측: 다른 문서(저장 안 한 고침)가 같이 열려 있으면 다시 열기가 그 문서를 갈아엎었다 — 새 탭을 먼저 연다."""
    source, preview, _document, fake = _worker(tmp_path, monkeypatch, other=True)
    result = hwp_module._worker_operation(_apply_payload(tmp_path, source, preview))
    rows = fake.XHwpDocuments.rows
    assert result["verified"] is True and fake.XHwpDocuments.added == 1
    assert [(Path(r.FullName).name, r.Modified) for r in rows] == [("다른문서.hwp", True), ("신청서.hwp", False)]
    # 되돌리기(restore)도 같은 길을 쓴다
    backup = tmp_path / "backups" / "신청서.hwp.bak"
    restore = {"operation": "restore", "instance_id": "!HwpObject.t", "native_document_id": 7, "source_path": str(source),
               "backup_path": str(backup), "before_sha256": _sha256(backup), "after_sha256": _sha256(source)}
    rows[-1].DocumentID = 7
    assert hwp_module._worker_operation(restore)["verified"] is True
    assert [Path(r.FullName).name for r in fake.XHwpDocuments.rows] == ["다른문서.hwp", "신청서.hwp"]
    assert source.read_bytes() == b"original"


def test_worker_refuses_a_copy_changed_after_review_and_leaves_the_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, preview, document, _fake = _worker(tmp_path, monkeypatch)
    payload = _apply_payload(tmp_path, source, preview)
    preview.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="preview_changed_since_review"):
        hwp_module._worker_operation(payload)
    assert source.read_bytes() == b"original" and document.closed == 0
    with pytest.raises(RuntimeError, match="drifted_since_preview"):
        hwp_module._worker_operation(_apply_payload(tmp_path, source, preview, source_sha256="0" * 64))


# ── 4. 등록 자리 ────────────────────────────────────────────────────────────────
def test_fill_tools_are_offered_wherever_the_format_tools_are() -> None:
    import importlib.util

    from alture_jarvis import (
        agent,
        answer_hygiene,
        code_look_gate,
        contract_slim,
        permissions,
        plan,
        runtime,
        tool_roster,
    )

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_measure_autonomy_fill", root / "scripts" / "measure_autonomy.py")
    assert spec and spec.loader
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)

    for table in (
        permissions.WRITE_TOOL_NAMES,
        code_look_gate._READ_ONLY_FORBIDDEN_TOOLS,
        answer_hygiene._ARTIFACT_PROGRESS_TOOLS,
        agent._COMMIT_TOOLS,
        plan._ARTIFACT_TOOLS,
        plan._ACTION_TOOLS,
        measure.WRITE_TOOLS,
        measure.COMMIT_TOOLS,
    ):
        assert "hwp_apply_fill" in table
    assert "hwp_preview_fill" in code_look_gate._READ_ONLY_FORBIDDEN_TOOLS
    assert "hwp_preview_fill" in answer_hygiene._ARTIFACT_STAGE_SUPPORT
    assert "hwp_preview_fill" in measure.PREPARE_TOOLS
    assert runtime.JarvisRuntime._OUTPUT_TOOLS["hwp_preview_fill"] == ("output_path",)
    assert agent.BrowserAgent._tool_label("hwp_apply_fill", {}) == "승인된 한글 양식 채우기를 원본에 반영하는 중"
    screen = (root / "ui" / "src" / "trajectory.ts").read_text(encoding="utf-8")
    assert '"hwp_apply_fill"' in screen.split("export const WRITE_TOOLS")[1].split("]);")[0]
    assert not tool_roster._compact_family_unrequested("hwp_apply_fill", "한글 문서 칸 채워 줘")
    # 양식 채우기 말은 열린 한글 문서 길로 간다. 「그림」 · 「N쪽」 홀로는 안 간다(운영 요청 6,038건에서 헛걸림 1건이 그것).
    for prompt in ("한글 문서 칸 채워 줘", "한글 문서에 그림 넣어 줘", "한글 파일 3쪽에 맞춰 줘", "HWP 양식 채우기"):
        assert runtime._HWP_EDIT_TARGET.search(prompt) and runtime._HWP_EDIT_ACTION.search(prompt), prompt
    for prompt in ("한글 파일 3쪽 요약해 줘", "한글 파일의 그림 설명해 줘", "awesome 목록 형식 규칙(그림 글자 허용 여부) · 한글 파일 저장"):
        assert not (runtime._HWP_EDIT_TARGET.search(prompt) and runtime._HWP_EDIT_ACTION.search(prompt)), prompt
    line = "hwp_preview_fill → hwp_apply_fill"
    assert line in agent.AGENT_SYSTEM_PROMPT
    assert line in contract_slim.slim_contract(agent.AGENT_SYSTEM_PROMPT, ["hwp_apply_fill", "browser_open"])
    assert line not in contract_slim.slim_contract(agent.AGENT_SYSTEM_PROMPT, ["browser_open"])


def test_english_screen_has_the_fill_descriptions(tmp_path: Path) -> None:
    import re

    from alture_jarvis import ui_i18n

    tools = HwpTools.__new__(HwpTools)
    texts: list[str] = []
    for definition in HwpTools._build_definitions(tools):
        function = definition["function"]
        if function["name"] not in {"hwp_preview_fill", "hwp_apply_fill"}:
            continue
        texts.append(function["description"])
        properties = function["parameters"]["properties"]
        texts.extend(p["description"] for p in properties.values() if "description" in p)
        items = properties.get("operations", {}).get("items", {}).get("properties", {})
        texts.extend(p["description"] for p in items.values() if "description" in p)
    texts += ["한글 양식 사본에 글과 그림을 채워 쪽수를 재는 중", "승인된 한글 양식 채우기를 원본에 반영하는 중"]
    ui_i18n.configure(tmp_path / "lang.json")
    ui_i18n.set_lang("en")
    try:
        left = [text for text in texts if re.search(r"[가-힣]", ui_i18n.translate_text(text))]
    finally:
        ui_i18n.set_lang("ko")
    assert len(texts) >= 12 and left == []
