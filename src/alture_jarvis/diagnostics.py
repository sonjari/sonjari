"""진단 묶음 내보내기 (W3 설정 > 데스크톱 앱).

사용자가 「진단 내보내기」를 누르면 **이 PC 에 파일 하나**를 만든다. 어디로도 보내지 않는다 — 보낼지는 사람이 정한다.

담는 것: 판(build)·패키지 여부·상태 점검(`/health` 와 같은 값)·설정 화면 값·백업 상태·최근 잡의 **상태와 오류 이름**.
담지 않는 것: 대화·파일·브라우저 본문, 잡의 프롬프트와 답, 토큰. 그리고 전체를 `secret_scrub` 로 한 번 더 걷고
사용자 폴더 이름을 `~` 로 바꾼다(경로에 사람 이름이 들어간다).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .secret_scrub import scrub


def _home_masked(text: str) -> str:
    home = str(Path.home())
    if not home:
        return text
    pattern = re.compile(re.escape(home).replace(r"\\", r"[\\/]{1,2}"), re.I)
    return pattern.sub("~", text)


def build_bundle(runtime: Any, *, job_limit: int = 30) -> dict[str, Any]:
    from . import msix

    health: dict[str, Any] = {}
    try:
        health = runtime.health()
    except Exception as exc:  # noqa: BLE001 — 고장 난 PC 의 진단이 고장으로 멈추면 안 된다
        health = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    jobs = []
    try:
        for row in runtime.store.list_jobs(limit=job_limit):
            jobs.append({
                "kind": row.get("kind"), "status": row.get("status"),
                # 오류는 **이름**만. 메시지 본문에 사용자 내용이 섞일 수 있다.
                "error": str(row.get("error") or "").split(":", 1)[0][:80],
                "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
            })
    except Exception:  # noqa: BLE001
        jobs = []
    settings_view: dict[str, Any] = {}
    service = getattr(runtime, "settings", None)
    if service is not None:
        try:
            settings_view = {row["key"]: {"value": row["value"], "source": row["source"]}
                             for row in service.view()["settings"]}
        except Exception:  # noqa: BLE001
            settings_view = {}
    backup: dict[str, Any] = {}
    try:
        status = runtime.backup.status()
        backup = {k: status.get(k) for k in ("enabled", "keep", "memory_empty")}
        backup["generations"] = len(status.get("generations") or [])
    except Exception:  # noqa: BLE001
        backup = {}
    return {
        "made_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "package": {k: v for k, v in msix.runtime_summary().items() if k != "executable"},
        "os": os.name,
        "health": health,
        "settings": settings_view,
        "backup": backup,
        "jobs": jobs,
        **_engine_section(runtime),
        "note": "대화·파일·프롬프트·답·토큰은 담지 않았다. 사용자 폴더는 ~ 로 바꿨다.",
    }


#: 로그는 끝만 본다 — 원인은 대개 마지막 몇십 줄에 있고, 통째로 넣으면 사람이 못 읽는다.
LOG_TAIL_LINES = 60


def _tail(path: Path, lines: int = LOG_TAIL_LINES) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 200_000))
            data = handle.read().decode("utf-8", "replace")
    except OSError as exc:
        return [f"(못 읽음: {type(exc).__name__})"]
    return data.splitlines()[-lines:]


def _engine_section(runtime: Any) -> dict[str, Any]:
    """엔진(Ollama)·자리·로그 — 2026-09-18 노트북 진단에 필요했던 것들.

    그날 원인을 찾느라 PowerShell 명령을 여덟 번 주고받았다(버전·Ollama 목록·직접 생성·폴더 목록·백신 기록·파일 수·로그).
    전부 기계가 모을 수 있는 것이었고, 다른 사람 PC 에서는 그 여덟 번을 부탁할 수도 없다.
    로그에는 사용자 내용이 섞일 수 있어 끝 몇십 줄만, 그리고 전체가 한 번 더 비밀 걷기를 지난다(export_bundle).
    """
    section: dict[str, Any] = {}
    care = getattr(runtime, "self_care", None)
    if care is not None:
        try:
            section["self_check_now"] = care.boot_check(include_model=True)
        except Exception as exc:  # noqa: BLE001
            section["self_check_now"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        section["self_check_at_boot"] = getattr(care, "last_boot", None)
    installer = getattr(runtime, "ollama_installer", None)
    logs: dict[str, list[str]] = {}
    if installer is not None:
        try:
            section["ollama"] = installer.status()
        except Exception as exc:  # noqa: BLE001
            section["ollama"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        for root in (installer.install_root, *getattr(installer, "legacy_roots", ())):
            log = Path(root) / "serve.log"
            if log.exists():
                logs[f"ollama serve.log ({root})"] = _tail(log)
    config = runtime.config
    section["places"] = {
        name: str(getattr(config, name, ""))
        for name in ("data_dir", "output_dir", "ollama_install_dir", "browser_profile_dir",
                     "sandbox_output_dir", "face_model_dir", "documents_dir", "browser_download_dir")
    }
    log = Path(config.output_dir) / "jarvis.stderr.log"
    if log.exists():
        logs["jarvis.stderr.log"] = _tail(log)
    section["logs"] = logs
    return section


def export_bundle(runtime: Any) -> dict[str, Any]:
    from .msix import external_path
    bundle = build_bundle(runtime)
    text = json.dumps(bundle, ensure_ascii=False, indent=2, default=str)
    cleaned = scrub(_home_masked(text))
    folder = Path(runtime.config.output_dir) / "diagnostics"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"jarvis-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(cleaned["text"], encoding="utf-8")
    return {"ok": True, "path": str(external_path(path)), "bytes": path.stat().st_size, "secrets_removed": cleaned["secrets"]}


__all__ = ["build_bundle", "export_bundle"]
