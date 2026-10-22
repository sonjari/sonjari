"""서기를 켜면 클로드 코드 설정(`~/.claude/settings.json`)에 훅 셋을 넣고, 끄면 우리 것만 뺀다 (2026-10-22 · 간판 3번).

넣는 훅(`claude_hooks.py`):
    SessionStart · compact   압축 직후 — 주제 색인 · 서기 카드(· 고른 작업방식 파일)를 다시 넣는다
    SessionStart · startup   새 세션 — 바로 앞 대화의 주제 색인을 펼쳐 준다
    PostCompact              압축 요약과 그 순간의 카드를 손자리 데이터 폴더에 남긴다(효과를 셀 재료)

지키는 것:
- **바뀐 게 있을 때만 쓴다**(앱을 켤 때마다 맞춰 보는데, 같으면 손대지 않아 백업이 쌓이지 않는다). 쓸 때는 먼저 백업한다.
- **우리 것만** 뺀다 — 명령에 `claude_hooks` 가 든 훅. 사용자가 직접 단 훅은 그대로 둔다.
- 스토어 판은 업데이트마다 설치 경로가 바뀐다 — 앱을 켤 때 맞춰 두지 않으면 훅이 옛 경로를 가리킨다.
- 스토어 판은 앱 안 파이썬을 밖에서 못 띄운다 → 실행 별칭 `-m alture_jarvis.claude_hooks`(`mcp_connect.server_entry` 와 같은 길).
  개발 판은 이 폴더의 파일을 직접. `pythonw.exe` 는 출력이 없어 훅이 아무것도 못 넣는다 → 옆의 `python.exe`.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import msix
from .mcp_connect import _atomic_write, _backup, _load_json, msix_alias_path, server_entry

MARK = "claude_hooks"


def _python() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return exe.with_name("python.exe")
    return exe


def _q(path: Any) -> str:
    return '"' + Path(str(path)).as_posix() + '"'


def hook_commands(config: Any) -> list[tuple[str, str | None, str]]:
    """(이벤트, matcher, 명령) 셋. 명령은 클로드 코드가 셸로 돌리는 한 줄."""
    env = server_entry(config)["env"]
    packaged = msix.is_packaged()
    prefix = (f"{_q(msix_alias_path())} -m alture_jarvis.claude_hooks" if packaged
              else f"{_q(_python())} {_q(Path(__file__).with_name('claude_hooks.py'))}")
    common = f"--base-url {env['JARVIS_BASE_URL']} --token-file {_q(env['JARVIS_TOKEN_FILE'])}"
    if packaged:
        common += f" --alias {_q(msix_alias_path())}"
    style = str(getattr(config, "scribe_style_file", "") or "").strip()
    after = f"{prefix} after-compact {common}" + (f" --style-file {_q(style)}" if style else "")
    log_dir = msix.external_path(Path(config.data_dir) / "scribe" / "compact_log")
    save = f"{prefix} save-compact {common} --log-dir {_q(log_dir)}"
    return [("SessionStart", "compact", after), ("SessionStart", "startup", after), ("PostCompact", None, save)]


def _is_ours(hook: Any) -> bool:
    return isinstance(hook, dict) and MARK in str(hook.get("command") or "")


def _without_ours(hooks: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            kept = [hook for hook in (group.get("hooks") or []) if not _is_ours(hook)]
            if kept:
                kept_groups.append({**group, "hooks": kept})
        if kept_groups:
            out[event] = kept_groups
    return out


def desired(data: dict[str, Any], config: Any, enabled: bool) -> dict[str, Any]:
    """설정 글(dict)에 우리 훅을 맞춘 결과 — 원본은 안 바꾼다."""
    hooks = _without_ours(dict(data.get("hooks") or {}))
    if enabled:
        for event, matcher, command in hook_commands(config):
            group: dict[str, Any] = {"hooks": [{"type": "command", "command": command, "timeout": 15}]}
            if matcher:
                group = {"matcher": matcher, **group}
            hooks.setdefault(event, []).append(group)
    out = {key: value for key, value in data.items() if key != "hooks"}
    if hooks:
        out["hooks"] = hooks
    return out


def settings_path(home: Path | None = None) -> Path:
    return Path(home or Path.home()) / ".claude" / "settings.json"


def apply(config: Any, enabled: bool, *, home: Path | None = None,
          clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """클로드 코드 설정을 맞춘다. 바뀐 게 없으면 쓰지 않는다. 설정 파일이 JSON 이 아니면 손대지 않는다."""
    path = settings_path(home)
    data = _load_json(path)
    if data is None:
        return {"ok": False, "error": "config_not_json", "path": str(path)}
    target = desired(data, config, enabled)
    if target == data:
        return {"ok": True, "changed": False, "path": str(path)}
    backup = str(_backup(path, clock)) if path.exists() else ""
    _atomic_write(path, json.dumps(target, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "changed": True, "path": str(path), "backup": backup, "installed": enabled}


def status(home: Path | None = None) -> dict[str, Any]:
    data = _load_json(settings_path(home)) or {}
    found = sorted({event for event, groups in (data.get("hooks") or {}).items() if isinstance(groups, list)
                    for group in groups if isinstance(group, dict) for hook in (group.get("hooks") or []) if _is_ours(hook)})
    return {"installed": bool(found), "events": found}


__all__ = ["apply", "desired", "hook_commands", "settings_path", "status"]
