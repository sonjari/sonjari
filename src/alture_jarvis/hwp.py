"""한컴 한글: 열린 문서에 붙어 사본 diff 뒤 승인·적용·복원한다.

COM은 별도 프로세스에서만 부른다. 한글의 모달 대화상자 하나가 JobRunner의 유일한
스레드를 영원히 붙드는 것을 막고, 제한시간이 지나면 그 호출 프로세스를 종료한다.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
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


def _running_hwp_objects(module_name: str) -> tuple[list[tuple[str, Any]], Any]:
    if os.name != "nt":
        raise RuntimeError("windows_only")
    import pythoncom
    import win32com.client

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
            hwp = win32com.client.Dispatch(dispatch)
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


def _worker_operation(payload: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation") or "")
    module_name = str(payload.get("module_name") or "FilePathCheckerModuleExample")
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
            import win32com.client

            preview_hwp = win32com.client.DispatchEx(_PROG_ID)
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

        raise ValueError("unknown_hwp_worker_operation")
    finally:
        pythoncom.CoUninitialize()


def _worker_main() -> int:
    try:
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


class HwpTools:
    """열린 HWP를 사본에서 검토한 뒤 승인받아 원본에 적용한다."""

    def __init__(self, config: Any, local_computer: Any, events: Any = None) -> None:
        self.config = config
        self.local_computer = local_computer
        self.events = events
        self._lock = threading.RLock()
        self._previews: dict[str, HwpEditPreview] = {}
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
                1 for row in self._previews.values()
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
        request = {
            "operation": operation,
            "module_name": str(
                getattr(self.config, "hwp_security_module_name", "FilePathCheckerModuleExample")
            ),
            **payload,
        }
        timeout = max(5, int(getattr(self.config, "hwp_com_timeout_sec", 30)))
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

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "hwp_list_open": self.list_open,
            "hwp_read": self.read,
            "hwp_preview_edit": self.preview_edit,
            "hwp_apply_edit": self.apply_edit,
        }
        risks = {
            "hwp_list_open": RiskLevel.L0,
            "hwp_read": RiskLevel.L1,
            "hwp_preview_edit": RiskLevel.L1,
            "hwp_apply_edit": RiskLevel.L2,
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
                    inverse=(
                        InverseSpec(
                            label="한글 문서를 적용 전 백업으로 되돌리기",
                            handle_from=self._undo_handle,
                            undo=self._undo_apply,
                        )
                        if name == "hwp_apply_edit" else None
                    ),
                    proof=(
                        ProofSpec(
                            capture_before=self._capture_apply_proof,
                            capture_current=self._capture_apply_proof,
                            same_target=same_fingerprint,
                            finalize=self._finalize_apply_proof,
                        )
                        if name == "hwp_apply_edit" else None
                    ),
                    needs_job_context=name in {"hwp_preview_edit", "hwp_apply_edit"},
                )
            )


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", action="store_true")
    args, _ = parser.parse_known_args()
    return _worker_main() if args.worker else 2


if __name__ == "__main__":
    raise SystemExit(main())
