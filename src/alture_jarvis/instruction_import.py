"""첫 실행 3단계 — 다른 AI 도구의 지침 **가져오기** (전략안 §43, P4).

사용자가 이미 클로드·코덱스·커서에 적어 둔 「이렇게 일해 줘」 파일을 찾아서, 보여 주고,
비밀을 걷어 내고, 사용자가 확인하면 넣는다. 가져온 지침을 **대답에 쓰는 것은 이번 범위가
아니다** — 넣고, 보이고, 지울 수 있으면 끝이다.

## 흐름

    찾기(stat 만) → 고르기 → 미리보기(읽고 걷음) → 확인 → 넣기(출처·해시·시각) → 바뀜 알림 → 지우기

## 지키는 것

1. **정해진 경로만 본다.** 홈 전체를 훑지 않는다. 후보는 `candidate_paths` 한 곳에서만
   나오고, 미리보기·넣기는 **그 목록의 id** 만 받는다(경로를 받지 않는다).
2. **설정 파일은 열지 않는다.** `~/.codex/config.toml`·Cursor `settings.json` 은 키가
   섞일 수 있고 지침이 아니다. 있다는 사실만 보여 준다.
3. **확인 전에는 아무것도 저장하지 않는다.** 미리보기는 읽기만 한다.
4. **보여 준 것과 넣는 것이 같아야 한다.** 넣기는 파일을 다시 읽고 미리보기 때의 해시와
   비교한다. 그 사이 바뀌었으면 넣지 않는다.
5. **자동 갱신은 없다.** 바뀌면 「바뀌었습니다」만 말한다.
6. 전부 이 PC 안에서 한다. 네트워크로 보내지 않는다.

## 어디에 넣나 — 기존 기억 저장소를 왜 안 썼나

- `memory_documents`: 대화 메시지(`conversation_messages.id`)에 외래 키로 묶여 있어 넣으려면
  가짜 대화를 만들어야 한다. 게다가 `retrieve()` 가 이 표를 훑는다 — 넣는 순간 가져온 지침이
  대화 회상에 섞여 들어가 「쓰기」가 시작된다. 그건 이번 범위도 아니고 검토도 안 됐다.
- `facts`: 한 줄 200자 상한이고, `learned_block` 으로 **매 턴** 시스템 프롬프트에 실린다.
  30KB 짜리 지침 파일이 들어갈 자리가 아니다.
- 그래서 **같은 SQLite 파일에 전용 표**(`imported_instructions`)를 둔다
  (`ExternalActionStore` 가 이미 쓰는 방식). 이 표는 아직 아무 프롬프트에도 안 실린다.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from .secret_scrub import scrub

# 지침 파일 하나의 상한. 넘으면 **자르지 않고 거절한다** — 잘린 지침은 틀린 지침이다.
MAX_BYTES = 256_000
# `.cursor/rules` 에 규칙이 수백 개면 화면이 못 보여 준다. 넘은 사실은 결과에 싣는다.
MAX_RULE_FILES = 60
# Claude Desktop 지침은 계정에 저장돼 PC 에 파일이 없다 — 파일 목록에 자리가 없어 「내 클로드는?」이 됐다(2026-09-16 노트북).
PASTE_TOOLS = {"claude_desktop": "Claude Desktop", "manus": "Manus", "windsurf": "Windsurf", "other": "다른 도구"}
TOOL_NAMES = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor", **PASTE_TOOLS}


@dataclass(frozen=True)
class Candidate:
    id: str
    tool: str
    scope: str  # "global" | "project"
    path: Path
    readable: bool = True
    # 안 읽는 이유 — "settings_file" | "sensitive_location"
    skip_reason: str = ""


#: ★ 이 기능이 **일부러 읽는** 두 파일 (2026-09-20).
#:
#:   같은 날 폴더 권한을 다시 짜면서 `.claude`·`.codex` 를 통째로 비밀 취급했다 — 그 안에는
#:   대화 원문과 토큰이 들어 있어서 맞는 판단이다. 그런데 **지침 가져오기는 바로 그 폴더의
#:   지침 파일 하나를 읽는 기능**이라 같이 막혔다(시험 9건이 그렇게 잡았다).
#:
#:   폴더는 계속 막고, **부모 폴더와 파일 이름이 정확히 이 조합인 것만** 예외로 둔다.
#:   `.claude/settings.json`·`.codex/auth.json` 같은 것은 그대로 막힌다.
_INSTRUCTION_FILES = {(".claude", "claude.md"), (".codex", "agents.md")}


def _is_sensitive(path: Path) -> bool:
    """이미 있는 「읽으면 안 되는 파일」 규칙을 그대로 쓴다 — 두 벌이면 갈린다."""
    from .code_index import SENSITIVE_NAMES
    from .local_computer import LocalComputerTools

    if (path.parent.name.lower(), path.name.lower()) in _INSTRUCTION_FILES:
        return bool(SENSITIVE_NAMES.search(path.name))
    return LocalComputerTools._is_sensitive(path) or bool(SENSITIVE_NAMES.search(path.name))


def candidate_paths(home: Path, appdata: Path | None, project: Path | None) -> list[Candidate]:
    """볼 경로 **전부.** 여기 없는 파일은 어떤 요청으로도 열리지 않는다.

    경로는 2026-09-13 개발 PC 에서 실제로 있던 것만 넣었다. 윈드서프는 설치된 PC 에서
    경로를 확인하기 전까지 넣지 않는다(추측한 경로를 박지 않는다) — 붙여넣기로 받는다.
    """
    out = [
        Candidate("claude:global", "claude", "global", home / ".claude" / "CLAUDE.md"),
        Candidate("codex:global", "codex", "global", home / ".codex" / "AGENTS.md"),
        Candidate("codex:config", "codex", "global", home / ".codex" / "config.toml", False, "settings_file"),
    ]
    if appdata is not None:
        out.append(Candidate("cursor:settings", "cursor", "global",
                             appdata / "Cursor" / "User" / "settings.json", False, "settings_file"))
    if project is not None:
        out += [
            Candidate("claude:project", "claude", "project", project / "CLAUDE.md"),
            Candidate("codex:project", "codex", "project", project / "AGENTS.md"),
            Candidate("cursor:cursorrules", "cursor", "project", project / ".cursorrules"),
        ]
        rules = project / ".cursor" / "rules"
        try:
            # 한 층만. 하위 폴더는 내려가지 않는다.
            names = sorted(p.name for p in rules.iterdir() if p.suffix.lower() == ".mdc" and p.is_file())
        except OSError:
            names = []
        out += [Candidate(f"cursor:rule:{name}", "cursor", "project", rules / name)
                for name in names[:MAX_RULE_FILES]]

    checked: list[Candidate] = []
    for cand in out:
        if cand.readable and _is_sensitive_location(cand, project):
            cand = Candidate(cand.id, cand.tool, cand.scope, cand.path, False, "sensitive_location")
        checked.append(cand)
    return checked


def _is_sensitive_location(cand: Candidate, project: Path | None) -> bool:
    if _is_sensitive(cand.path):
        return True
    try:
        resolved = cand.path.resolve()
    except OSError:
        return False
    if _is_sensitive(resolved):
        return True
    # 프로젝트 파일이 링크로 프로젝트 **밖**을 가리키면 읽지 않는다.
    if cand.scope == "project" and project is not None and cand.path.exists():
        try:
            resolved.relative_to(project.resolve())
        except ValueError:
            return True
    return False


def _decode(raw: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class InstructionImportService:
    """첫 실행 화면이 부르는 곳. 파일 읽기(`read_bytes`)는 주입할 수 있다 — 시험이 무엇을
    열었는지 세려고."""

    def __init__(
        self,
        db_path: Path,
        *,
        read_bytes: Callable[[Path], bytes] | None = None,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._read = read_bytes or (lambda p: p.read_bytes())
        self._publish = publish or (lambda _event, _payload: None)
        self._init_db()

    # ── 저장소 ──────────────────────────────────────────────────────────────
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """★ 닫는다. `with sqlite3.connect() as conn` 은 커밋만 하고 **안 닫는다** — 리허설
        데이터를 뽑다가 임시 폴더를 못 지우는 것으로 드러났다(WinError 32). 자비스는 오래
        떠 있는 프로세스라 열린 연결이 쌓이면 안 된다. `memory.py` 의 `_connection` 과 같은 모양."""
        conn = sqlite3.connect(str(self.path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS imported_instructions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL UNIQUE,
                    tool TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    text TEXT NOT NULL,
                    secrets_json TEXT NOT NULL DEFAULT '{}',
                    contacts_json TEXT NOT NULL DEFAULT '{}',
                    redact_contacts INTEGER NOT NULL DEFAULT 0,
                    imported_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    # ── 경로 ────────────────────────────────────────────────────────────────
    @staticmethod
    def _home() -> Path:
        return Path.home()

    @staticmethod
    def _appdata() -> Path | None:
        value = os.environ.get("APPDATA", "")
        return Path(value) if value else None

    @staticmethod
    def _project(project: str | None) -> tuple[Path | None, str]:
        raw = str(project or "").strip()
        if not raw:
            return None, ""
        path = Path(raw).expanduser()
        if not path.is_absolute() or not path.is_dir():
            return None, "project_not_found"
        return path, ""

    def _candidates(self, project: Path | None) -> dict[str, Candidate]:
        return {c.id: c for c in candidate_paths(self._home(), self._appdata(), project)}

    # ── 1. 찾기 — 내용은 안 읽는다 ─────────────────────────────────────────────
    def scan(self, project: str | None = "") -> dict[str, Any]:
        project_path, project_error = self._project(project)
        imported = {row["source_key"]: row for row in self._rows()}
        items = []
        for cand in self._candidates(project_path).values():
            try:
                stat = cand.path.stat()
                exists = cand.path.is_file()
            except OSError:
                stat, exists = None, False
            entry: dict[str, Any] = {
                "id": cand.id,
                "tool": cand.tool,
                "tool_name": TOOL_NAMES[cand.tool],
                "scope": cand.scope,
                "path": str(cand.path),
                "exists": exists,
                "size": stat.st_size if exists and stat else 0,
                "modified_at": stat.st_mtime if exists and stat else None,
                "readable": cand.readable,
                "skip_reason": cand.skip_reason,
                "too_large": bool(exists and stat and stat.st_size > MAX_BYTES),
            }
            row = imported.get(str(cand.path))
            if row is not None:
                # 이미 넣은 파일만 해시를 다시 잰다(바뀜 알림). 넣지 않은 파일은 안 연다.
                entry["imported"] = {"import_id": int(row["id"]), "status": self._status(row)}
            items.append(entry)
        return {"project": str(project_path) if project_path else "", "project_error": project_error,
                "candidates": items, "max_bytes": MAX_BYTES}

    # ── 2·3. 미리보기 — 읽고 걷는다. 저장하지 않는다 ────────────────────────────────
    def preview(self, project: str | None, ids: list[str], paste: dict[str, Any] | None = None,
                *, redact_contacts: bool = False) -> dict[str, Any]:
        project_path, project_error = self._project(project)
        candidates = self._candidates(project_path)
        items = [self._preview_one(candidates.get(str(i)), str(i), redact_contacts) for i in ids]
        if paste:
            items.append(self._preview_paste(paste, redact_contacts))
        return {"project_error": project_error, "items": items}

    def _load(self, cand: Candidate | None, cid: str) -> tuple[dict[str, Any], bytes | None, str | None]:
        base: dict[str, Any] = {"id": cid}
        if cand is None:
            return {**base, "error": "not_in_list"}, None, None
        base.update(tool=cand.tool, tool_name=TOOL_NAMES[cand.tool], scope=cand.scope, path=str(cand.path))
        if not cand.readable:
            return {**base, "error": cand.skip_reason}, None, None
        try:
            if not cand.path.is_file():
                return {**base, "error": "missing"}, None, None
            if cand.path.stat().st_size > MAX_BYTES:
                return {**base, "error": "too_large"}, None, None
            raw = self._read(cand.path)
        except OSError as exc:
            return {**base, "error": "unreadable", "detail": type(exc).__name__}, None, None
        if len(raw) > MAX_BYTES:
            return {**base, "error": "too_large"}, None, None
        text = _decode(raw)
        if text is None:
            return {**base, "error": "not_text"}, None, None
        return base, raw, text

    def _preview_one(self, cand: Candidate | None, cid: str, redact_contacts: bool) -> dict[str, Any]:
        base, raw, text = self._load(cand, cid)
        if raw is None or text is None:
            return base
        return {**base, "sha256": _sha(raw), "chars": len(text), **_public(scrub(text, redact_contacts=redact_contacts))}

    @staticmethod
    def _paste_text(paste: dict[str, Any]) -> tuple[str, str, str]:
        tool = str(paste.get("tool") or "")
        text = str(paste.get("text") or "")
        if tool not in PASTE_TOOLS:
            return tool, text, "unknown_tool"
        if not text.strip():
            return tool, text, "empty"
        if len(text.encode("utf-8")) > MAX_BYTES:
            return tool, text, "too_large"
        return tool, text, ""

    def _preview_paste(self, paste: dict[str, Any], redact_contacts: bool) -> dict[str, Any]:
        tool, text, error = self._paste_text(paste)
        base = {"id": "paste", "tool": tool, "tool_name": TOOL_NAMES.get(tool, tool), "scope": "paste",
                "path": ""}
        if error:
            return {**base, "error": error}
        return {**base, "sha256": _sha(text.encode("utf-8")), "chars": len(text),
                **_public(scrub(text, redact_contacts=redact_contacts))}

    # ── 4·5. 넣기 — 사람이 눌렀다 ──────────────────────────────────────────────────
    def commit(self, project: str | None, items: list[dict[str, Any]], paste: dict[str, Any] | None = None,
               *, redact_contacts: bool = False) -> dict[str, Any]:
        project_path, _ = self._project(project)
        candidates = self._candidates(project_path)
        saved: list[dict[str, Any]] = []
        refused: list[dict[str, Any]] = []
        for item in items:
            cid = str(item.get("id") or "")
            base, raw, text = self._load(candidates.get(cid), cid)
            if raw is None or text is None:
                refused.append(base)
                continue
            if _sha(raw) != str(item.get("sha256") or ""):
                # 미리보기에서 본 것과 다르다 — 사람이 안 본 것을 넣지 않는다.
                refused.append({**base, "error": "changed_since_preview"})
                continue
            saved.append(self._upsert(str(candidates[cid].path), candidates[cid], raw, text, redact_contacts))
        if paste:
            tool, text, error = self._paste_text(paste)
            sha = _sha(text.encode("utf-8"))
            if error:
                refused.append({"id": "paste", "error": error})
            elif sha != str(paste.get("sha256") or ""):
                refused.append({"id": "paste", "error": "changed_since_preview"})
            else:
                cand = Candidate("paste", tool, "paste", Path(""))
                saved.append(self._upsert(f"paste:{tool}:{sha[:16]}", cand, text.encode("utf-8"), text,
                                          redact_contacts, display=f"붙여넣기 · {PASTE_TOOLS[tool]}"))
        if saved:
            self._publish("instructions_imported", {"count": len(saved)})
        return {"ok": not refused, "saved": saved, "refused": refused}

    def _upsert(self, key: str, cand: Candidate, raw: bytes, text: str, redact_contacts: bool,
                *, display: str | None = None) -> dict[str, Any]:
        result = scrub(text, redact_contacts=redact_contacts)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO imported_instructions
                   (source_key, tool, scope, source_path, sha256, text, secrets_json, contacts_json,
                    redact_contacts, imported_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_key) DO UPDATE SET
                     sha256 = excluded.sha256, text = excluded.text,
                     secrets_json = excluded.secrets_json, contacts_json = excluded.contacts_json,
                     redact_contacts = excluded.redact_contacts, updated_at = excluded.updated_at""",
                (key, cand.tool, cand.scope, display or str(cand.path), _sha(raw), result["text"],
                 json.dumps(result["secrets"], ensure_ascii=False),
                 json.dumps(result["contacts"], ensure_ascii=False), int(redact_contacts), now, now),
            )
            row = conn.execute("SELECT * FROM imported_instructions WHERE source_key = ?", (key,)).fetchone()
        return {"import_id": int(row["id"]), "id": cand.id, "source_path": row["source_path"],
                "secret_total": result["secret_total"]}

    # ── 6·7. 목록 · 바뀜 · 지우기 ──────────────────────────────────────────────────
    def _rows(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM imported_instructions ORDER BY imported_at DESC, id DESC").fetchall()

    def _status(self, row: sqlite3.Row) -> str:
        if row["scope"] == "paste":
            return "same"
        path = Path(row["source_path"])
        try:
            if not path.is_file():
                return "missing"
            # 넣을 때 이미 목록 안의 파일이었다. 그래도 민감 위치로 바뀌었으면 열지 않는다.
            if _is_sensitive(path) or path.stat().st_size > MAX_BYTES:
                return "unreadable"
            return "same" if _sha(self._read(path)) == row["sha256"] else "changed"
        except OSError:
            return "unreadable"

    def list(self) -> dict[str, Any]:
        items = []
        for row in self._rows():
            secrets = json.loads(row["secrets_json"] or "{}")
            items.append({
                "import_id": int(row["id"]),
                "tool": row["tool"],
                "tool_name": TOOL_NAMES.get(row["tool"], row["tool"]),
                "scope": row["scope"],
                "source_path": row["source_path"],
                "imported_at": row["imported_at"],
                "updated_at": row["updated_at"],
                "chars": len(row["text"]),
                "text": row["text"],
                "secrets": secrets,
                "secret_total": sum(int(v) for v in secrets.values()),
                "status": self._status(row),
            })
        return {"count": len(items), "items": items}

    def remove(self, import_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            deleted = conn.execute("DELETE FROM imported_instructions WHERE id = ?", (int(import_id),)).rowcount
        if not deleted:
            return {"ok": False, "error": "not_found"}
        self._publish("instructions_removed", {"import_id": int(import_id)})
        return {"ok": True, "removed": int(import_id)}


def _public(result: dict[str, Any]) -> dict[str, Any]:
    """화면에 줄 것만. 걷은 글(`text`)은 조각에서 다시 만들 수 있어 두 번 싣지 않는다."""
    return {k: result[k] for k in ("segments", "secrets", "secret_total", "contacts", "contact_total")}


__all__ = ["Candidate", "InstructionImportService", "MAX_BYTES", "candidate_paths"]
