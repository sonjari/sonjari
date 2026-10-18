"""한글 서식 바꾸기(hwp_preview_format → hwp_apply_format) — 실제 한글 없이 가짜로 잰다 (2026-10-17).

서식은 메뉴를 누르지 않고 한글 자동화(CharShape · ParagraphShape)로 바꾼다. 안전 모양은 글자 바꾸기(hwp_apply_edit)와 같고,
반영한 자리의 서식을 **다시 읽어** 요청과 맞는지(matches)를 돌려준다. 이 시험은 세 층을 본다.

1. 인자 · 단위(pt → HWPUNIT · #RRGGBB → COLORREF)
2. 도구 층의 미리보기 → 승인 적용 → 되돌리기, 다시 읽은 값이 어긋나면 그대로 알리기, 허용 폴더 밖 거절, 등록 자리
3. 한글 호출 순서(`_format_active`) — 가짜 한글 객체로 찾기 두 바퀴 · 끝에서 처음으로 돌아오기 · 엉뚱한 자리 멈춤 · 글자 바뀜 되돌리기

★ 가짜가 흉내 내는 한글의 동작(찾은 뒤 커서가 선택의 끝에 있다 등)은 실제 한글로 재 본 것이 아니다. 실제와 다르면
  hwp.py 의 작은 함수들(_find_forward · _select_occurrence · _execute_shape · _read_items)만 고치면 된다.
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
from alture_jarvis.hwp import (
    HwpTools,
    _color_to_colorref,
    _colorref_to_hex,
    _format_active,
    _format_spec,
    _pt_to_hwpunit,
    _sha256,
    _shape_mismatches,
)
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway


# ── 1. 인자 · 단위 ─────────────────────────────────────────────────────────────
def test_points_become_hwpunits_and_colors_become_colorref() -> None:
    assert _pt_to_hwpunit(12) == 1200
    assert _pt_to_hwpunit(10.5) == 1050
    assert _pt_to_hwpunit("16") == 1600
    # COLORREF 는 0x00BBGGRR — 빨강이 맨 아래 바이트다.
    assert _color_to_colorref("#FF0000") == 0x0000FF
    assert _color_to_colorref("0000ff") == 0xFF0000
    assert _color_to_colorref("#123456") == 0x563412
    assert _colorref_to_hex(_color_to_colorref("#1A2B3C")) == "#1A2B3C"


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({}, "hwp_format_needs_at_least_one_change"),
        ({"size_pt": 0.5}, "hwp_size_pt_out_of_range"),
        ({"size_pt": 5000}, "hwp_size_pt_out_of_range"),
        ({"size_pt": True}, "hwp_size_pt_must_be_a_number"),
        ({"size_pt": "크게"}, "hwp_size_pt_must_be_a_number"),
        ({"color": "red"}, "hwp_color_must_be_hex_rrggbb"),
        ({"align": "middle"}, "hwp_align_must_be_left_center_right_or_justify"),
        ({"line_spacing_percent": 20}, "hwp_line_spacing_percent_out_of_range"),
        ({"bold": "yes"}, "hwp_bold_must_be_boolean"),
        ({"font_hangul": "x" * 65}, "hwp_font_hangul_invalid"),
    ],
)
def test_bad_format_arguments_are_refused(arguments: dict[str, Any], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        _format_spec(arguments)


def test_format_spec_maps_to_hangul_items() -> None:
    spec = _format_spec(
        {
            "font_hangul": "맑은 고딕",
            "font_latin": "Arial",
            "size_pt": 14,
            "bold": True,
            "italic": False,
            "underline": True,
            "color": "#FF0000",
            "align": "center",
            "line_spacing_percent": 180,
        }
    )
    assert spec["char"] == {
        "FaceNameHangul": "맑은 고딕",
        "FontTypeHangul": 1,
        "FaceNameLatin": "Arial",
        "FontTypeLatin": 1,
        "Height": 1400,
        "Bold": 1,
        "Italic": 0,
        "UnderlineType": 1,
        "TextColor": 0x0000FF,
    }
    assert spec["para"] == {"AlignType": 3, "LineSpacingType": 0, "LineSpacing": 180}


def test_mismatch_compares_only_what_was_asked_and_mixed_counts_as_mismatch() -> None:
    spec = _format_spec({"font_hangul": "맑은 고딕", "bold": True})
    assert _shape_mismatches(spec, {"char": {"FaceNameHangul": "맑은 고딕", "Bold": 1}}) == []
    got = _shape_mismatches(spec, {"char": {"FaceNameHangul": None, "Bold": 0}})
    assert {row["item"] for row in got} == {"FaceNameHangul", "Bold"}  # 글꼴 종류(FontType)는 견주지 않는다


# ── 2. 도구 층 ──────────────────────────────────────────────────────────────────
def _stack(tmp_path: Path, *, outside: bool = False) -> tuple[HwpTools, ToolGateway, Path]:
    allowed = tmp_path / "allowed"
    allowed.mkdir(parents=True)
    folder = tmp_path / "elsewhere" if outside else allowed
    folder.mkdir(exist_ok=True)
    source = folder / "보고서.hwp"
    source.write_bytes(b"before-hwp")
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed),
        # ★ 열린 한글 문서는 **읽기 범위**로 거른다(`_open_rows` → resolve_allowed_path). 비우면 사용자 폴더 전체라
        #   임시 폴더도 통과한다 — 허용 밖 거절을 재려면 읽기 범위도 좁혀야 한다.
        local_read_roots=str(allowed),
        hwp_enabled=True,
    )
    local = LocalComputerTools(config)
    tools = HwpTools(config, local, EventBus())
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    tools.register(gateway)
    return tools, gateway, source


def _fake_com(
    tools: HwpTools,
    source: Path,
    *,
    found: int = 2,
    apply_readback: dict[str, Any] | None = None,
    modified: bool = False,
) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def readback(spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "char": {k: v for k, v in spec["char"].items() if not k.startswith("FontType")},
            "para": dict(spec["para"]),
        }

    def invoke(operation: str, **payload: Any) -> dict[str, Any]:
        calls.append((operation, payload))
        if operation == "list_open":
            return {
                "documents": [
                    {
                        "native_document_id": 7,
                        "instance_id": "!HwpObject.test.1",
                        "path": str(source),
                        "name": source.name,
                        "format": "HWP",
                        "modified": modified,
                    }
                ]
            }
        if operation == "preview_format":
            preview = Path(payload["preview_path"])
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_bytes(b"preview-hwp")
            targets = 1 if payload["whole_document"] or payload["occurrence"] == "first" else found
            return {
                "source_sha256": _sha256(source),
                "preview_sha256": "preview",
                "found": 1 if payload["whole_document"] else found,
                "targets": targets,
                "text_occurrences": found,
                "before_shapes": [{"char": {"Bold": 0}, "para": {}}] * targets,
                "readbacks": [readback(payload["spec"])] * targets,
            }
        if operation == "apply_format":
            backup = Path(payload["backup_path"])
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            before = _sha256(source)
            source.write_bytes(b"after-hwp")
            targets = 1 if payload["whole_document"] or payload["occurrence"] == "first" else found
            shape = apply_readback if apply_readback is not None else readback(payload["spec"])
            return {
                "before_sha256": before,
                "after_sha256": _sha256(source),
                "file_changed": True,
                "found": found,
                "targets": targets,
                "readbacks": [shape] * targets,
            }
        if operation == "restore":
            shutil.copy2(Path(payload["backup_path"]), source)
            return {"path": str(source), "restored_sha256": _sha256(source), "reopened": True, "verified": True}
        raise AssertionError(operation)

    tools._invoke = invoke  # type: ignore[method-assign]
    return calls


def test_format_tools_are_registered_like_the_edit_tools(tmp_path: Path) -> None:
    _tools, gateway, _source = _stack(tmp_path)
    specs = gateway._tools
    assert specs["hwp_preview_format"].risk_level is RiskLevel.L1
    assert specs["hwp_apply_format"].risk_level is RiskLevel.L2
    assert specs["hwp_apply_edit"].risk_level is RiskLevel.L2
    assert specs["hwp_apply_format"].inverse is not None and specs["hwp_apply_format"].inverse.undo is not None
    assert specs["hwp_apply_format"].proof is not None
    assert specs["hwp_preview_format"].inverse is None and specs["hwp_preview_format"].proof is None
    assert specs["hwp_preview_format"].needs_job_context is True
    assert specs["hwp_apply_format"].needs_job_context is True


def test_bad_arguments_never_reach_hangul(tmp_path: Path) -> None:
    tools, _gateway, source = _stack(tmp_path)
    calls = _fake_com(tools, source)
    for arguments, code in (
        ({"document_id": 1, "bold": True}, "target_text_or_whole_document_required"),
        ({"document_id": 1, "bold": True, "target_text": "제목", "whole_document": True}, "not_both"),
        ({"document_id": 1, "bold": True, "target_text": "첫 줄\n둘째 줄"}, "one_line"),
        ({"document_id": 1, "bold": True, "target_text": "제목", "occurrence": "last"}, "all_or_first"),
        ({"document_id": 1, "target_text": "제목"}, "needs_at_least_one_change"),
    ):
        with pytest.raises(ValueError, match=code):
            tools.preview_format({**arguments, "__job_id": "job-bad"})
    assert calls == []


def test_preview_formats_a_copy_and_says_what_will_change(tmp_path: Path) -> None:
    tools, _gateway, source = _stack(tmp_path)
    calls = _fake_com(tools, source, found=3)
    before = source.read_bytes()

    result = tools.preview_format(
        {
            "document_id": 1,
            "target_text": "제목",
            "occurrence": "all",
            "size_pt": 16,
            "bold": True,
            "align": "center",
            "__job_id": "job-preview",
        }
    )

    assert source.read_bytes() == before
    assert Path(result["output_path"]).is_file()
    assert result["requires_approval"] is True
    assert result["targets"] == 3
    assert result["matches"] is True and result["mismatches"] == []
    assert result["value_after"][0] == {"size_pt": 16.0, "bold": True, "align": "center"}
    assert "「제목」 3곳" in result["summary"] and "16pt" in result["summary"] and "가운데 정렬" in result["summary"]
    sent = dict(calls[-1][1])
    assert calls[-1][0] == "preview_format"
    assert sent["spec"]["char"] == {"Height": 1600, "Bold": 1}
    assert sent["spec"]["para"] == {"AlignType": 3}


def test_apply_reads_back_and_undo_restores_the_backup(tmp_path: Path) -> None:
    tools, gateway, source = _stack(tmp_path)
    _fake_com(tools, source, found=1)
    preview = tools.preview_format(
        {"document_id": 1, "whole_document": True, "font_hangul": "맑은 고딕", "color": "#0000FF", "__job_id": "job-apply"}
    )
    original = source.read_bytes()

    applied = tools.apply_format({"preview_id": preview["preview_id"], "__job_id": "job-apply"})

    assert applied["verified"] is True and applied["matches"] is True
    assert applied["value_after"] == [{"font_hangul": "맑은 고딕", "color": "#0000FF"}]
    assert source.read_bytes() == b"after-hwp"
    with pytest.raises(RuntimeError, match="already_used"):
        tools.apply_format({"preview_id": preview["preview_id"], "__job_id": "job-apply"})

    inverse = gateway._tools["hwp_apply_format"].inverse
    assert inverse is not None and inverse.undo is not None
    handle = inverse.handle_from(applied)
    assert handle is not None
    assert inverse.undo(handle)["verified"] is True
    assert source.read_bytes() == original


def test_a_readback_mismatch_is_reported_not_hidden_and_undo_stays(tmp_path: Path) -> None:
    """한글이 굵게를 안 받아 줬다 — 「바꿨다」고 하면 안 된다. 그래도 파일은 바뀌었으니 되돌릴 손잡이는 남는다."""
    tools, gateway, source = _stack(tmp_path)
    _fake_com(tools, source, found=1, apply_readback={"char": {"Bold": 0, "Height": 1200}, "para": {}})
    preview = tools.preview_format(
        {"document_id": 1, "target_text": "제목", "bold": True, "size_pt": 12, "__job_id": "job-mismatch"}
    )

    applied = tools.apply_format({"preview_id": preview["preview_id"], "__job_id": "job-mismatch"})

    assert applied["verified"] is False and applied["matches"] is False
    assert applied["mismatches"] == [{"target": 1, "item": "Bold", "wanted": 1, "got": 0}]
    assert applied["value_after"] == [{"size_pt": 12.0, "bold": False}]
    assert gateway._tools["hwp_apply_format"].inverse.handle_from(applied) is not None


def test_ambiguous_or_unsaved_or_outside_documents_are_refused(tmp_path: Path) -> None:
    tools, _gateway, source = _stack(tmp_path, outside=True)
    _fake_com(tools, source)
    with pytest.raises(RuntimeError, match="outside_allowed_roots"):
        tools.preview_format({"document_id": 1, "target_text": "제목", "bold": True, "__job_id": "job-outside"})

    tools, _gateway, source = _stack(tmp_path / "dirty")
    _fake_com(tools, source, modified=True)
    with pytest.raises(RuntimeError, match="unsaved"):
        tools.preview_format({"document_id": 1, "target_text": "제목", "bold": True, "__job_id": "job-dirty"})


def test_approval_fingerprint_binds_the_format_and_the_file(tmp_path: Path) -> None:
    tools, _gateway, source = _stack(tmp_path)
    _fake_com(tools, source, found=1)
    preview = tools.preview_format({"document_id": 1, "target_text": "제목", "bold": True, "__job_id": "job-proof"})
    arguments = {"preview_id": preview["preview_id"], "__job_id": "job-proof"}
    before = tools._capture_format_proof(arguments)
    source.write_bytes(b"human-changed-the-source")
    assert tools._capture_format_proof(arguments)["fingerprint"] != before["fingerprint"]


def test_format_tools_are_offered_wherever_the_edit_tools_are() -> None:
    """등록 자리는 열 곳이 넘는다 — 한 곳만 빠져도 조용히 틀린다(plan.py 주석). 글자 바꾸기가 있는 자리에 서식도 있어야 한다."""
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
    spec = importlib.util.spec_from_file_location("_measure_autonomy_fmt", root / "scripts" / "measure_autonomy.py")
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
        assert "hwp_apply_edit" in table and "hwp_apply_format" in table
    assert "hwp_preview_format" in code_look_gate._READ_ONLY_FORBIDDEN_TOOLS
    assert {"hwp_preview_edit", "hwp_preview_format"} <= answer_hygiene._ARTIFACT_STAGE_SUPPORT
    assert {"hwp_preview_edit", "hwp_preview_format"} <= measure.PREPARE_TOOLS
    assert runtime.JarvisRuntime._OUTPUT_TOOLS["hwp_preview_format"] == ("output_path",)
    assert agent.BrowserAgent._tool_label("hwp_apply_format", {}) == "승인된 한글 서식을 원본에 반영하는 중"
    # 화면의 쓰기 손 목록 — 없으면 서식만 바꾼 판이 「읽기만 함」으로 보인다(trajectory.ts 주석).
    screen = (root / "ui" / "src" / "trajectory.ts").read_text(encoding="utf-8")
    screen_writes = screen.split("export const WRITE_TOOLS")[1].split("]);")[0]
    assert '"hwp_apply_edit"' in screen_writes and '"hwp_apply_format"' in screen_writes

    # 작은 창에서 한글 가족은 「한글」이라는 말이 있을 때만 실린다 — 서식 도구도 같은 가족이다.
    assert not tool_roster._compact_family_unrequested("hwp_apply_format", "한글 문서 제목을 굵게 해 줘")
    assert tool_roster._compact_family_unrequested("hwp_apply_format", "오늘 날씨 알려 줘")
    # 서식 말만 있는 요청도 열린 한글 문서 길로 간다(고치라는 낱말이 없다).
    for prompt in ("한글 문서 제목을 굵게 해 줘", "열린 문서 전체 글꼴을 맑은 고딕으로", "HWP 본문 가운데 정렬해 줘", "한글 파일 줄 간격 160%로"):
        assert runtime._HWP_EDIT_TARGET.search(prompt) and runtime._HWP_EDIT_ACTION.search(prompt), prompt
    # 지침의 한글 대목에 서식 길이 들어 있고, 한글 손이 없는 판에서는 그 대목과 같이 빠진다.
    line = "hwp_preview_format → hwp_apply_format"
    assert line in agent.AGENT_SYSTEM_PROMPT
    assert line in contract_slim.slim_contract(agent.AGENT_SYSTEM_PROMPT, ["hwp_apply_format", "browser_open"])
    assert line not in contract_slim.slim_contract(agent.AGENT_SYSTEM_PROMPT, ["browser_open"])


def test_english_screen_has_the_new_descriptions(tmp_path: Path) -> None:
    import re

    from alture_jarvis import ui_i18n

    tools = HwpTools.__new__(HwpTools)
    texts: list[str] = []
    for definition in HwpTools._build_definitions(tools):
        function = definition["function"]
        if function["name"] not in {"hwp_preview_format", "hwp_apply_format"}:
            continue
        texts.append(function["description"])
        texts.extend(p["description"] for p in function["parameters"]["properties"].values() if "description" in p)
    texts += ["한글 문서 사본에 서식을 걸어 보는 중", "승인된 한글 서식을 원본에 반영하는 중"]
    ui_i18n.configure(tmp_path / "lang.json")
    ui_i18n.set_lang("en")
    try:
        left = [text for text in texts if re.search(r"[가-힣]", ui_i18n.translate_text(text))]
    finally:
        ui_i18n.set_lang("ko")
    assert len(texts) >= 12 and left == []


# ── 3. 한글 호출 순서 — 가짜 한글 ─────────────────────────────────────────────────
_DEFAULT_CHAR = {
    "FaceNameHangul": "함초롬바탕", "FaceNameLatin": "함초롬바탕", "Height": 1000,
    "Bold": 0, "Italic": 0, "UnderlineType": 0, "TextColor": 0,
}
_DEFAULT_PARA = {"AlignType": 0, "LineSpacingType": 0, "LineSpacing": 160}


class _Bag:
    """HParameterSet.HCharShape 같은 셋 — 속성을 받아 두었다가 Execute 때 쓴다."""

    def __init__(self) -> None:
        self.HSet = object()

    def values(self) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items() if k != "HSet"}

    def reset(self) -> None:
        for key in list(self.values()):
            delattr(self, key)


class _ReadSet:
    def __init__(self) -> None:
        self.items: dict[str, Any] = {}

    def ItemExist(self, name: str) -> bool:
        return name in self.items

    def Item(self, name: str) -> Any:
        return self.items[name]


class _ReadAction:
    def __init__(self, hwp: _FakeHwp, action_id: str) -> None:
        self.hwp, self.action_id = hwp, action_id

    def CreateSet(self) -> _ReadSet:
        return _ReadSet()

    def GetDefault(self, parameters: _ReadSet) -> None:
        parameters.items = self.hwp.uniform(self.action_id)


class _Actions:
    def __init__(self, hwp: _FakeHwp) -> None:
        self.hwp = hwp

    def Run(self, action_id: str) -> bool:
        hwp = self.hwp
        if action_id == "Cancel":
            hwp.sel = None
        elif action_id == "MoveDocBegin":
            hwp.sel, hwp.caret = None, (0, 0, 0)
        elif action_id == "SelectAll":
            last = len(hwp.paras) - 1
            hwp.sel = ((0, 0), (last, len(hwp.paras[last])))
        else:
            raise AssertionError(action_id)
        return True

    def GetDefault(self, action_id: str, hset: Any) -> None:
        self.hwp.bag_for(hset).reset()

    def Execute(self, action_id: str, hset: Any) -> bool:
        bag = self.hwp.bag_for(hset)
        if action_id == "RepeatFind":
            return self.hwp.find(str(bag.FindString))
        if action_id in {"CharShape", "ParagraphShape"}:
            return self.hwp.shape(action_id, bag.values())
        raise AssertionError(action_id)


class _FakeDocument:
    def __init__(self) -> None:
        self.undone = 0
        self.saved = 0

    def SetActive_XHwpDocument(self) -> None:
        return None

    def Undo(self) -> None:
        self.undone += 1

    def Save(self, _flag: bool) -> bool:
        self.saved += 1
        return True


class _FakeHwp:
    """문단 목록 하나짜리 한글. 찾으면 그 글자가 선택되고 커서는 선택의 끝(caret_at_start 면 시작)에 선다.

    wrap=True 면 문서 끝에서 처음으로 돌아가 다시 찾는다(IgnoreMessage 판에 따라 그렇다는 보고가 있다).
    ignore 에 든 항목은 Execute 가 조용히 안 바꾼다(한글이 값을 안 받아 준 경우).
    """

    def __init__(self, paras: list[str], *, wrap: bool = False, caret_at_start: bool = False,
                 ignore: tuple[str, ...] = (), eat_a_char: bool = False) -> None:
        self.paras = list(paras)
        self.wrap, self.caret_at_start, self.ignore, self.eat_a_char = wrap, caret_at_start, ignore, eat_a_char
        self.char: dict[tuple[int, int], dict[str, Any]] = {}
        self.para_shape: dict[int, dict[str, Any]] = {}
        self.caret = (0, 0, 0)
        self.sel: tuple[tuple[int, int], tuple[int, int]] | None = None
        self.HParameterSet = SimpleNamespace(HFindReplace=_Bag(), HCharShape=_Bag(), HParaShape=_Bag())
        self.HAction = _Actions(self)
        self.shape_calls = 0

    def bag_for(self, hset: Any) -> _Bag:
        return next(bag for bag in vars(self.HParameterSet).values() if bag.HSet is hset)

    def FindDir(self, name: str) -> int:
        return {"Forward": 0, "Backward": 1, "AllDoc": 2}[name]

    def GetTextFile(self, _format: str, _option: str) -> str:
        return "\r\n".join(self.paras)

    def GetPos(self) -> tuple[int, int, int]:
        return self.caret

    def SetPos(self, list_id: int, para: int, pos: int) -> bool:
        self.sel, self.caret = None, (list_id, para, pos)
        return True

    def CreateAction(self, action_id: str) -> _ReadAction:
        return _ReadAction(self, action_id)

    def _search(self, text: str, para: int, pos: int) -> tuple[int, int] | None:
        for index in range(para, len(self.paras)):
            start = self.paras[index].find(text, pos if index == para else 0)
            if start >= 0:
                return index, start
        return None

    def find(self, text: str) -> bool:
        # 선택이 있으면 그 끝에서부터(화면의 「다시 찾기」처럼), 없으면 커서에서부터.
        para, pos = self.sel[1] if self.sel else self.caret[1:]
        hit = self._search(text, para, pos)
        if hit is None and self.wrap:
            hit = self._search(text, 0, 0)
        if hit is None:
            return False
        start, end = hit, (hit[0], hit[1] + len(text))
        self.sel = (start, end)
        self.caret = (0, *(start if self.caret_at_start else end))
        return True

    def _selected_chars(self) -> list[tuple[int, int]]:
        assert self.sel is not None, "선택 없이 서식을 걸었다"
        (sp, spos), (ep, epos) = self.sel
        out = []
        for para in range(sp, ep + 1):
            first = spos if para == sp else 0
            last = epos if para == ep else len(self.paras[para])
            out.extend((para, i) for i in range(first, last))
        return out

    def shape(self, action_id: str, values: dict[str, Any]) -> bool:
        self.shape_calls += 1
        values = {k: v for k, v in values.items() if k not in self.ignore}
        if action_id == "CharShape":
            for key in self._selected_chars():
                self.char.setdefault(key, dict(_DEFAULT_CHAR)).update(values)
            if self.eat_a_char:
                self.paras[0] = self.paras[0][1:]
        else:
            (sp, _), (ep, _) = self.sel  # type: ignore[misc]
            for para in range(sp, ep + 1):
                self.para_shape.setdefault(para, dict(_DEFAULT_PARA)).update(values)
        return True

    def uniform(self, action_id: str) -> dict[str, Any]:
        if action_id == "CharShape":
            rows = [self.char.get(key, _DEFAULT_CHAR) for key in self._selected_chars()]
        else:
            (sp, _), (ep, _) = self.sel  # type: ignore[misc]
            rows = [self.para_shape.get(p, _DEFAULT_PARA) for p in range(sp, ep + 1)]
        return {name: rows[0][name] for name in rows[0] if all(row[name] == rows[0][name] for row in rows)}


_PARAS = ["제목 하나", "본문 제목 둘 그리고 제목 셋", "끝"]


def test_every_occurrence_is_formatted_and_read_back() -> None:
    hwp = _FakeHwp(_PARAS)
    spec = _format_spec({"bold": True, "size_pt": 14, "align": "center"})

    result = _format_active(hwp, _FakeDocument(), {"spec": spec, "target_text": "제목", "occurrence": "all"}, {"steps": 0})

    assert result["found"] == 3 and result["targets"] == 3 and result["text_occurrences"] == 3
    assert all(_shape_mismatches(spec, row) == [] for row in result["readbacks"])
    assert result["before_shapes"][0]["char"] == {"Height": 1000, "Bold": 0}
    bold = sorted(key for key, shape in hwp.char.items() if shape["Bold"] == 1)
    assert bold == [(0, 0), (0, 1), (1, 3), (1, 4), (1, 12), (1, 13)]  # 「제목」 글자만, 다른 글자는 그대로
    assert hwp.para_shape[0]["AlignType"] == 3 and hwp.para_shape[1]["AlignType"] == 3 and 2 not in hwp.para_shape


def test_wrapping_search_stops_instead_of_looping() -> None:
    hwp = _FakeHwp(_PARAS, wrap=True)
    spec = _format_spec({"italic": True})
    result = _format_active(hwp, _FakeDocument(), {"spec": spec, "target_text": "제목", "occurrence": "all"}, {"steps": 0})
    assert result["found"] == 3 and result["targets"] == 3


def test_first_only_and_not_unique_without_occurrence() -> None:
    spec = _format_spec({"bold": True})
    hwp = _FakeHwp(_PARAS)
    result = _format_active(hwp, _FakeDocument(), {"spec": spec, "target_text": "제목", "occurrence": "first"}, {"steps": 0})
    assert result["found"] == 3 and result["targets"] == 1
    assert sorted(hwp.char) == [(0, 0), (0, 1)]

    with pytest.raises(RuntimeError, match="not_unique"):
        _format_active(_FakeHwp(_PARAS), _FakeDocument(), {"spec": spec, "target_text": "제목"}, {"steps": 0})
    with pytest.raises(RuntimeError, match="target_not_found"):
        _format_active(_FakeHwp(_PARAS), _FakeDocument(), {"spec": spec, "target_text": "없는 글"}, {"steps": 0})


def test_whole_document_selects_all_once() -> None:
    hwp = _FakeHwp(_PARAS)
    spec = _format_spec({"font_hangul": "맑은 고딕", "line_spacing_percent": 200})
    result = _format_active(hwp, _FakeDocument(), {"spec": spec, "whole_document": True}, {"steps": 0})
    assert result["targets"] == 1 and _shape_mismatches(spec, result["readbacks"][0]) == []
    assert all(shape["FaceNameHangul"] == "맑은 고딕" for shape in hwp.char.values())
    assert len(hwp.char) == sum(len(p) for p in _PARAS)


def test_readback_catches_a_value_hangul_did_not_take() -> None:
    hwp = _FakeHwp(_PARAS, ignore=("Bold",))
    spec = _format_spec({"bold": True, "size_pt": 20})
    result = _format_active(hwp, _FakeDocument(), {"spec": spec, "target_text": "끝"}, {"steps": 0})
    assert _shape_mismatches(spec, result["readbacks"][0]) == [{"item": "Bold", "wanted": 1, "got": 0}]


def test_a_caret_left_at_the_selection_start_stops_rather_than_formatting_the_wrong_place() -> None:
    """찾은 뒤 커서가 선택의 시작에 서는 판이면 2단계가 같은 곳을 또 잡는다 — 엉뚱한 곳을 고치기 전에 멈춘다."""
    hwp = _FakeHwp(_PARAS, caret_at_start=True)
    progress = {"steps": 0}
    with pytest.raises(RuntimeError, match="target_moved"):
        _format_active(hwp, _FakeDocument(), {"spec": _format_spec({"bold": True}), "target_text": "제목",
                                             "occurrence": "all"}, progress)
    assert progress["steps"] == 1  # 첫 대상만 걸렸다 — 부르는 쪽이 그만큼 되돌린다


def test_apply_worker_undoes_every_step_when_the_text_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "문서.hwp"
    source.write_bytes(b"original")
    document = _FakeDocument()
    document.DocumentID = 7  # type: ignore[attr-defined]
    document.FullName = str(source)  # type: ignore[attr-defined]
    fake = _FakeHwp(_PARAS, eat_a_char=True)
    fake.IsModified = False  # type: ignore[attr-defined]
    fake.XHwpDocuments = SimpleNamespace(Count=1, Item=lambda _index: document)  # type: ignore[attr-defined]
    pythoncom = SimpleNamespace(CoUninitialize=lambda: None)
    monkeypatch.setattr(hwp_module, "_running_hwp_objects", lambda _module: ([("!HwpObject.t", fake)], pythoncom))

    payload = {
        "operation": "apply_format",
        "instance_id": "!HwpObject.t",
        "native_document_id": 7,
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "backup_path": str(tmp_path / "backups" / "문서.hwp.bak"),
        "spec": _format_spec({"bold": True, "align": "right"}),
        "target_text": "제목",
        "occurrence": "first",
    }
    with pytest.raises(RuntimeError, match="changed_the_text"):
        hwp_module._worker_operation(payload)
    assert document.undone == 2 and document.saved == 0  # 글자 모양 + 문단 모양 두 걸음
    assert (tmp_path / "backups" / "문서.hwp.bak").read_bytes() == b"original"


def test_apply_worker_refuses_a_file_changed_since_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "문서.hwp"
    source.write_bytes(b"original")
    document = _FakeDocument()
    document.DocumentID = 7  # type: ignore[attr-defined]
    document.FullName = str(source)  # type: ignore[attr-defined]
    fake = _FakeHwp(_PARAS)
    fake.IsModified = False  # type: ignore[attr-defined]
    fake.XHwpDocuments = SimpleNamespace(Count=1, Item=lambda _index: document)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        hwp_module, "_running_hwp_objects",
        lambda _module: ([("!HwpObject.t", fake)], SimpleNamespace(CoUninitialize=lambda: None)),
    )
    with pytest.raises(RuntimeError, match="drifted_since_preview"):
        hwp_module._worker_operation(
            {
                "operation": "apply_format",
                "instance_id": "!HwpObject.t",
                "native_document_id": 7,
                "source_path": str(source),
                "source_sha256": "0" * 64,
                "backup_path": str(tmp_path / "b.bak"),
                "spec": _format_spec({"bold": True}),
                "target_text": "끝",
            }
        )
    assert fake.shape_calls == 0
