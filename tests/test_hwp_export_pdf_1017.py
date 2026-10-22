"""한글 파일 → PDF(hwp_export_pdf) — 실제 한글 없이 가짜로 잰다 (2026-10-17).

화면으로 한글 → PDF 를 하면 46걸음 · 593초였다(windows_automation 메뉴 주석의 측정). 이 도구는 숨김 인스턴스에서
사본을 열어 `SaveAs(경로, "PDF")` 하고 그 인스턴스만 끈다. 이 시험이 보는 것:

1. 자리 검사 — 원본은 읽기 범위, 만들 PDF 는 쓰기 범위, 이미 있으면 overwrite=true 없이는 거절
2. 한글 호출 모양 — 위치 인자 SaveAs(경로, "PDF", ""), 안 되면 FileSaveAs_S, 사용자 한글에는 안 붙음, 끝나면 Quit
3. %PDF 가 아니면 「안 됐다」로 돌려주고 사람 폴더에 안 둔다
4. 산출물로 세어진다(계획 층 · 장부 · 「만든 것」 서랍) — 원본 경로는 산출물로 둔갑하지 않는다

★ SaveAs 의 PDF 형식 문자열은 인프런 답변 글에서 본 모양이고 실제 한글로는 재 보지 못했다(hwp.py `_save_as_pdf` 주석).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import hwp as hwp_module
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.hwp import HwpTools, _save_as_pdf
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway

_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _stack(tmp_path: Path) -> tuple[HwpTools, ToolGateway, dict[str, Path]]:
    places = {
        "write": tmp_path / "write_root",
        "read": tmp_path / "read_only",
        "docs": tmp_path / "docs",
        "outside": tmp_path / "outside",
    }
    for folder in places.values():
        folder.mkdir(parents=True)
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(places["write"]),
        local_read_roots=str(places["read"]),
        documents_dir=places["docs"],
        hwp_enabled=True,
    )
    tools = HwpTools(config, LocalComputerTools(config), EventBus())
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    tools.register(gateway)
    return tools, gateway, places


def _fake_export(tools: HwpTools, *, body: bytes | None = _PDF) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def invoke(operation: str, **payload: Any) -> dict[str, Any]:
        assert operation == "export_pdf"
        calls.append(payload)
        assert Path(payload["source_copy"]).is_file()
        if body is not None:
            Path(payload["pdf_path"]).write_bytes(body)
        return {"saved": body is not None, "pdf_path": payload["pdf_path"]}

    tools._invoke = invoke  # type: ignore[method-assign]
    return calls


def _hwp(folder: Path, name: str = "보고서.hwpx") -> Path:
    source = folder / name
    source.write_bytes(b"PK\x03\x04hwpx-body")
    return source


# ── 1. 자리 검사 ────────────────────────────────────────────────────────────────
def test_default_output_is_next_to_the_source_and_reads_back_as_pdf(tmp_path: Path) -> None:
    tools, _gateway, places = _stack(tmp_path)
    calls = _fake_export(tools)
    source = _hwp(places["write"])
    original = source.read_bytes()

    result = tools.export_pdf({"path": str(source), "__job_id": "job-pdf"})

    output = places["write"] / "보고서.pdf"
    assert result["verified"] is True
    assert result["output_path"] == result["saved_file"] == str(output)
    assert result["bytes"] == len(_PDF) and output.read_bytes() == _PDF
    assert source.read_bytes() == original  # 원본은 열지도 바꾸지도 않는다 — 사본을 연다
    assert Path(calls[0]["source_copy"]) != source and Path(calls[0]["source_copy"]).suffix == ".hwpx"
    assert calls[0]["_timeout_floor_sec"] >= 120
    assert "path" not in result  # 원본은 source_path 로만 — `path` 로 실으면 산출물로 둔갑한다
    assert result["source_path"] == str(source)


def test_source_must_be_inside_read_roots_and_be_hangul(tmp_path: Path) -> None:
    tools, _gateway, places = _stack(tmp_path)
    calls = _fake_export(tools)
    with pytest.raises(PermissionError):
        tools.export_pdf({"path": str(_hwp(places["outside"])), "__job_id": "job-pdf"})
    text = places["write"] / "메모.txt"
    text.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="must_be_hwp_or_hwpx"):
        tools.export_pdf({"path": str(text), "__job_id": "job-pdf"})
    with pytest.raises(ValueError, match="path_required"):
        tools.export_pdf({"__job_id": "job-pdf"})
    assert calls == []


def test_output_must_be_inside_write_roots(tmp_path: Path) -> None:
    """읽기만 허용된 폴더의 한글 파일은 읽을 수 있지만, 그 옆에 PDF 를 만들 수는 없다."""
    tools, _gateway, places = _stack(tmp_path)
    calls = _fake_export(tools)
    source = _hwp(places["read"])
    with pytest.raises(PermissionError):
        tools.export_pdf({"path": str(source), "__job_id": "job-pdf"})
    with pytest.raises(PermissionError):
        tools.export_pdf({"path": str(source), "output_path": str(places["outside"] / "a.pdf"), "__job_id": "job-pdf"})
    with pytest.raises(ValueError, match="output_must_be_pdf"):
        tools.export_pdf({"path": str(source), "output_path": str(places["write"] / "a.docx"), "__job_id": "job-pdf"})
    assert calls == []

    result = tools.export_pdf({"path": str(source), "output_path": str(places["write"] / "결과"), "__job_id": "job-pdf"})
    assert result["output_path"] == str(places["write"] / "결과.pdf") and result["verified"] is True


def test_existing_file_is_refused_unless_overwrite_and_undo_restores_it(tmp_path: Path) -> None:
    tools, gateway, places = _stack(tmp_path)
    calls = _fake_export(tools)
    source = _hwp(places["write"])
    existing = places["write"] / "보고서.pdf"
    existing.write_bytes(b"%PDF-old")

    with pytest.raises(FileExistsError, match="overwrite"):
        tools.export_pdf({"path": str(source), "__job_id": "job-pdf"})
    with pytest.raises(ValueError, match="overwrite_must_be_boolean"):
        tools.export_pdf({"path": str(source), "overwrite": "yes", "__job_id": "job-pdf"})
    assert calls == [] and existing.read_bytes() == b"%PDF-old"

    result = tools.export_pdf({"path": str(source), "overwrite": True, "__job_id": "job-pdf"})
    assert result["overwrote"] is True and existing.read_bytes() == _PDF

    inverse = gateway._tools["hwp_export_pdf"].inverse
    assert inverse is not None and inverse.undo is not None
    handle = inverse.handle_from(result)
    assert handle is not None
    assert inverse.undo(handle)["verified"] is True
    assert existing.read_bytes() == b"%PDF-old"


def test_undo_deletes_a_new_pdf_but_not_one_changed_since(tmp_path: Path) -> None:
    tools, gateway, places = _stack(tmp_path)
    _fake_export(tools)
    source = _hwp(places["write"])
    inverse = gateway._tools["hwp_export_pdf"].inverse

    result = tools.export_pdf({"path": str(source), "__job_id": "job-pdf"})
    output = Path(result["output_path"])
    output.write_bytes(b"%PDF-person-edited")
    with pytest.raises(RuntimeError, match="changed_since_export"):
        inverse.undo(inverse.handle_from(result))
    assert output.exists()

    output.unlink()
    result = tools.export_pdf({"path": str(source), "__job_id": "job-pdf"})
    assert inverse.undo(inverse.handle_from(result))["verified"] is True
    assert not Path(result["output_path"]).exists()


def test_risk_is_like_making_a_new_document(tmp_path: Path) -> None:
    """local_write_document 와 같은 무게 — 결과물 폴더면 L1, 사람의 다른 폴더나 덮어쓰기면 승인(L2)."""
    tools, gateway, places = _stack(tmp_path)
    spec = gateway._tools["hwp_export_pdf"]
    assert spec.risk_level is RiskLevel.L1 and spec.needs_job_context is True
    source = _hwp(places["write"])
    assert spec.effective_risk({"path": str(source), "output_path": str(places["docs"] / "a.pdf")}) is RiskLevel.L1
    assert spec.effective_risk({"path": str(source)}) is RiskLevel.L2
    (places["docs"] / "b.pdf").write_bytes(b"%PDF")
    assert spec.effective_risk({"path": str(source), "output_path": str(places["docs"] / "b.pdf"), "overwrite": True}) \
        is RiskLevel.L2
    card = gateway.approval_describers["hwp_export_pdf"]({"path": str(source)})
    assert card["path"] == str(places["write"] / "보고서.pdf") and card["source"] == str(source)
    del tools


# ── 2. 한글 호출 모양 ────────────────────────────────────────────────────────────
class _Hidden:
    """숨김 인스턴스 흉내. SaveAs 가 되면 PDF 를 쓴다."""

    def __init__(self, *, save_as_works: bool = True) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.save_as_works = save_as_works
        self.window = SimpleNamespace(Visible=True)
        self.XHwpWindows = SimpleNamespace(Item=lambda _index: self.window)
        self.HParameterSet = SimpleNamespace(HFileOpenSave=SimpleNamespace(HSet=object()))
        self.HAction = SimpleNamespace(GetDefault=self._get_default, Execute=self._execute)

    def RegisterModule(self, kind: str, name: str) -> bool:
        self.calls.append(("RegisterModule", kind, name))
        return True

    def Open(self, path: str, fmt: str, option: str) -> bool:
        self.calls.append(("Open", path, fmt, option))
        return True

    def SaveAs(self, *args: Any) -> bool:
        self.calls.append(("SaveAs", *args))
        if self.save_as_works:
            Path(args[0]).write_bytes(_PDF)
        return self.save_as_works

    def _get_default(self, action: str, _hset: Any) -> None:
        self.calls.append(("GetDefault", action))

    def _execute(self, action: str, _hset: Any) -> bool:
        bag = self.HParameterSet.HFileOpenSave
        self.calls.append(("Execute", action, bag.filename, bag.Format))
        Path(bag.filename).write_bytes(_PDF)
        return True

    def Clear(self, option: int) -> None:
        self.calls.append(("Clear", option))

    def Quit(self) -> None:
        self.calls.append(("Quit",))


def test_save_as_is_called_positionally_with_pdf(tmp_path: Path) -> None:
    hidden = _Hidden()
    assert _save_as_pdf(hidden, tmp_path / "a.pdf") is True
    assert hidden.calls == [("SaveAs", str(tmp_path / "a.pdf"), "PDF", "")]


def test_save_as_falls_back_to_the_file_save_action(tmp_path: Path) -> None:
    hidden = _Hidden(save_as_works=False)
    assert _save_as_pdf(hidden, tmp_path / "b.pdf") is True
    assert hidden.calls[-2:] == [("GetDefault", "FileSaveAs_S"), ("Execute", "FileSaveAs_S", str(tmp_path / "b.pdf"), "PDF")]


def test_worker_uses_a_new_hidden_instance_and_never_the_users_hangul(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pythoncom")
    hidden = _Hidden()
    monkeypatch.setattr(hwp_module, "_new_instance", lambda _prog: hidden)

    def users_hangul(_module: str) -> Any:
        raise AssertionError("사용자가 띄운 한글을 찾았다")

    monkeypatch.setattr(hwp_module, "_running_hwp_objects", users_hangul)
    copy = tmp_path / "source.hwpx"
    copy.write_bytes(b"PK")
    result = hwp_module._worker_operation(
        {"operation": "export_pdf", "module_name": "M", "source_copy": str(copy), "pdf_path": str(tmp_path / "o.pdf")}
    )

    assert result["saved"] is True
    names = [call[0] for call in hidden.calls]
    assert names[0] == "RegisterModule" and names[-1] == "Quit"
    assert ("Open", str(copy), "HWPX", "lock:false;suspendpassword:true;forceopen:true") in hidden.calls
    assert hidden.window.Visible is False


def test_invoke_raises_the_timeout_floor_without_sending_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools, _gateway, _places = _stack(tmp_path)
    seen: dict[str, Any] = {}

    def run(_args: Any, **kwargs: Any) -> Any:
        seen["timeout"] = kwargs["timeout"]
        seen["input"] = kwargs["input"].decode("utf-8")
        return SimpleNamespace(returncode=0, stdout=b'{"ok": true, "result": {"saved": true}}', stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    tools._invoke("export_pdf", source_copy="a", pdf_path="b", _timeout_floor_sec=180)
    assert seen["timeout"] == 180 and "_timeout_floor_sec" not in seen["input"]


# ── 3. %PDF 검사 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("body", "reason"), [(None, "pdf_missing"), (b"", "pdf_empty"), (b"<html>error</html>", "not_a_pdf")])
def test_not_a_pdf_is_reported_unverified_and_not_placed(tmp_path: Path, body: bytes | None, reason: str) -> None:
    tools, _gateway, places = _stack(tmp_path)
    _fake_export(tools, body=body)
    source = _hwp(places["write"])

    result = tools.export_pdf({"path": str(source), "__job_id": "job-pdf"})

    assert result["verified"] is False and result["reason"] == reason
    assert result["saved_file"] is None and "output_path" not in result
    assert not (places["write"] / "보고서.pdf").exists()


# ── 4. 산출물로 세어진다 · 등록 자리 ──────────────────────────────────────────────
def test_the_pdf_counts_as_an_artifact_and_the_source_does_not(tmp_path: Path) -> None:
    from alture_jarvis import agent, plan, runtime

    tools, _gateway, places = _stack(tmp_path)
    _fake_export(tools)
    source = _hwp(places["write"])
    result = tools.export_pdf({"path": str(source), "__job_id": "job-pdf"})

    ledger = agent._step_evidence(result)
    assert ledger["output_path"] == result["output_path"]
    step = {"tool": "hwp_export_pdf", "ok": True, "status": "", "evidence": ledger}
    assert plan._step_output_paths(step) == [Path(result["output_path"])]
    assert runtime.JarvisRuntime._OUTPUT_TOOLS["hwp_export_pdf"] == ("output_path",)

    _fake_export(tools, body=b"nope")
    (places["write"] / "보고서.pdf").unlink()
    failed = tools.export_pdf({"path": str(source), "__job_id": "job-pdf"})
    assert plan._step_output_paths({"tool": "hwp_export_pdf", "ok": True, "evidence": agent._step_evidence(failed)}) == []


def test_export_is_offered_and_classified_with_the_other_hwp_tools(tmp_path: Path) -> None:
    import importlib.util
    import re

    from alture_jarvis import (
        answer_hygiene,
        code_look_gate,
        evidence,
        permissions,
        plan,
        runtime,
        tool_roster,
        ui_i18n,
    )

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_measure_autonomy_pdf", root / "scripts" / "measure_autonomy.py")
    assert spec and spec.loader
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)
    for table in (
        permissions.WRITE_TOOL_NAMES, code_look_gate._READ_ONLY_FORBIDDEN_TOOLS, answer_hygiene._ARTIFACT_PROGRESS_TOOLS,
        plan._ARTIFACT_TOOLS, plan._ACTION_TOOLS, measure.WRITE_TOOLS, measure.COMMIT_TOOLS,
    ):
        assert "hwp_export_pdf" in table
    assert evidence.MANIFEST["hwp_export_pdf"].effect == evidence.MANIFEST["local_write_document"].effect
    screen = (root / "ui" / "src" / "trajectory.ts").read_text(encoding="utf-8")
    assert '"hwp_export_pdf"' in screen.split("export const WRITE_TOOLS")[1].split("]);")[0]

    # 「한글」 낱말이 있는 판에 실리고, 그 요청은 열린 한글 문서 길로 간다.
    assert not tool_roster._compact_family_unrequested("hwp_export_pdf", "한글 파일을 PDF로 저장해 줘")
    for prompt in ("한글 파일을 PDF로 저장해 줘", "이 HWP 를 pdf 로"):
        assert runtime._HWP_EDIT_TARGET.search(prompt) and runtime._HWP_EDIT_ACTION.search(prompt), prompt

    tools = HwpTools.__new__(HwpTools)
    definition = next(d["function"] for d in HwpTools._build_definitions(tools) if d["function"]["name"] == "hwp_export_pdf")
    assert "한글 파일을 PDF 로 바꿀 때는 한글 창을 열지 말고 이 도구를 쓴다" in definition["description"]
    texts = [definition["description"], "만든 PDF 를 지우거나 덮기 전 파일로 되돌리기"]
    texts += [p["description"] for p in definition["parameters"]["properties"].values() if "description" in p]
    ui_i18n.configure(tmp_path / "lang.json")
    ui_i18n.set_lang("en")
    try:
        left = [text for text in texts if re.search(r"[가-힣]", ui_i18n.translate_text(text))]
    finally:
        ui_i18n.set_lang("ko")
    assert len(texts) == 5 and left == []


def test_the_hwp_worker_never_looks_up_the_com_type_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """실제 한글로 처음 돌렸을 때(2026-10-17): 메서드가 돌려준 객체(`XHwpDocuments.Item`)를 pywin32 가 형식 캐시로
    다시 묶으려다 반쯤 만들다 끊긴 캐시에서 죽었다. 작업 프로세스는 캐시를 아예 찾지 않는다."""
    gencache = pytest.importorskip("win32com.client.gencache")
    monkeypatch.setattr(gencache, "GetClassForCLSID", lambda _clsid: (_ for _ in ()).throw(AttributeError("CLSIDToClassMap")))
    monkeypatch.setattr(hwp_module.os, "name", "nt")
    hwp_module._without_type_cache()
    assert gencache.GetClassForCLSID("{00000000-0000-0000-0000-000000000000}") is None


def test_a_successful_conversion_counts_as_having_read_the_local_source() -> None:
    """한글→PDF 3판(2026-10-17): 읽기 요구가 「0개 실제로 읽음」으로 남아 모델이 원본을 샌드박스로 뜯어 읽으러 갔다."""
    from alture_jarvis import plan

    req = plan.Requirement("observe", "근거가 되는 대상 실제로 읽기", "local")
    done = {"tool": "hwp_export_pdf", "ok": True, "evidence": {"output_path": "C:/x/a.pdf", "verified": True}}
    ((_, ok, saw),) = plan.check([req], sources=[], steps=[done])
    assert ok and "변환" in saw
    failed = {"tool": "hwp_export_pdf", "ok": True, "evidence": {"verified": False}}
    ((_, ok, _saw),) = plan.check([req], sources=[], steps=[failed])
    assert not ok
    web = plan.Requirement("observe", "근거가 되는 대상 실제로 읽기", "browser")
    ((_, ok, _saw),) = plan.check([web], sources=[], steps=[done])
    assert not ok


def test_reading_an_old_hwp_points_to_the_conversion_tool(tmp_path: Path) -> None:
    tools, _gateway, places = _stack(tmp_path)
    source = places["write"] / "옛문서.hwp"
    source.write_bytes(b"\xd0\xcf\x11\xe0\x00\x00old hangul")
    with pytest.raises(ValueError, match="unsupported_document_format") as caught:
        tools.local_computer.read_document({"path": str(source), "__job_id": "job-pdf"})
    assert "hwp_export_pdf" in str(caught.value)


def test_a_hangul_file_job_is_not_routed_to_the_web_hands() -> None:
    """한글→PDF 3판 0/3(2026-10-17): 읽기 요구 하나로 웹 조사 갈래가 되어 한글 도구 일곱 개가 목록에서 빠졌다."""
    from alture_jarvis import plan
    from alture_jarvis.tool_roster import _is_web_research_job

    prompt = r"「C:\x\앱측정\welcome.hwp」 한글 파일을 같은 폴더에 같은 이름의 PDF 로 저장해 줘."
    steps = plan.extract(prompt, must_observe=True, observe_from=frozenset({"local"}))
    assert not _is_web_research_job(steps, prompt)
    # 웹 주소를 같이 댄 판은 그대로 웹 갈래다.
    web = "https://example.com/a.hwp 를 읽고 요약해 줘"
    assert _is_web_research_job(plan.extract(web, must_observe=True, observe_from=frozenset({"web"})), web)


@pytest.mark.parametrize(
    ("prompt", "wanted"),
    [
        # 한글→PDF 3판(2026-10-17): 원본 .hwp 가 만들 형식이 되어 PDF 를 만든 판마다 「열 수 있는 산출물 없음」이 찍혔다.
        ("「C:/x/welcome_1.hwp」 한글 파일을 같은 폴더에 같은 이름의 PDF 로 저장해 줘.", (".pdf",)),
        ("보고서.docx 를 PDF 로 변환해 줘", (".pdf",)),
        # 만들 파일 이름은 그대로 만들 형식이다.
        ("결과.md 를 만들어서 열어 줘", (".md",)),
        ("매출.xlsx 에 정리해 줘", (".xlsx",)),
    ],
)
def test_the_file_being_converted_is_the_source_not_the_result(prompt: str, wanted: tuple[str, ...]) -> None:
    from alture_jarvis.plan import artifact_extensions

    assert artifact_extensions(prompt) == wanted
