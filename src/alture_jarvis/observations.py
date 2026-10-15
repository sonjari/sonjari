"""도구가 **실제로 본 것**을 붙들어 둔다 — 화면이 열어 볼 수 있게.

## 왜 이 파일이 생겼나 (2026-08-19)

오른쪽 칸에 파일 내용을 띄우려고 화면부터 만들려다 알았다. **내용이 화면까지
오지를 않는다.**

    agent.py  _EVIDENCE_TOO_BIG = {"text","results","candidates","elements","path","screenshot"}
    agent.py  _EVIDENCE_VALUE_MAX = 200      # 문자열은 200자에서 자른다
    agent.py  # dict 는 안 싣는다

`_step_evidence` 는 **장부**를 만드는 함수다. 장부는 짧아야 하고, 그 판단은 옳다 —
걸음마다 8,000자를 이벤트로 쏘면 웹소켓이 그것만 나른다. 하지만 그 결과로 화면은
`local_read_document` 가 성공했다는 것만 알고 **어느 파일을 열었는지조차 모른다**
(`path` 가 제외 목록에 있다). 원문은 모델 대화에만 잠깐 실렸다가(30,000자 상한)
사라진다.

그래서 **길을 두 갈래로 낸다.**

    이벤트(agent_progress)  →  짧은 장부      →  걸음이 흐르는 것을 본다
    이 보관소(HTTP)         →  원문 그대로    →  누르면 그때 것을 펼쳐 본다

밀어 주지 않고 **물어볼 때만 준다.** 화면이 걸음을 누르는 순간에만 그 한 걸음이
오간다 — 그래야 8,000자가 웹소켓을 막지 않는다.

## 무엇을 보관하는가

원문 그대로가 아니라 **종류가 붙은 모양**으로 둔다(`shape`). 도구는 102개고 앞으로
더 는다. 도구마다 화면을 만들면 새 도구는 영원히 안 보인다 — 종류만 맞으면 그날부터
보이게 한다.

## 잘림은 숨기지 않는다

세 군데서 잘린다: 도구 자신(`max_chars`) · 이 보관소(`_STORE_CHARS`) · 모델 대화
(30,000자). 그래서 셋을 각각 적는다. **잘렸는데 안 적으면 「없던 내용」과 구별이 안
된다** — 사고 Q 에서 본문 23%가 그렇게 조용히 사라졌다.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# 한 걸음에 보관하는 글자 수. 도구가 80,000자까지 돌려줄 수 있으니(local_read_document
# 의 max_chars 상한) 그보다 넉넉하게 잡되, 잡 하나가 메모리를 다 먹지 않을 만큼만.
_STORE_CHARS = 120_000

# 모델 대화에 실리는 상한. `agent.py` 가 도구 결과를 json 으로 덤프하며 쓰는 값과
# 같아야 한다 — 여기 숫자가 저기와 갈리면 화면이 "모델은 이만큼 봤다"고 거짓말한다.
MODEL_TRANSCRIPT_CHARS = 30_000

_MAX_JOBS = 24          # 잡 몇 개분을 들고 있는가
_MAX_STEPS = 200        # 잡 하나에 몇 걸음까지
_TTL_SEC = 6 * 3600     # 이보다 오래된 잡은 버린다

# 코드로 볼 확장자 → 색칠에 쓸 이름. 없으면 문서로 본다.
_CODE_LANGUAGES = {
    ".py": "python", ".ts": "typescript", ".tsx": "tsx", ".js": "javascript",
    ".jsx": "jsx", ".rs": "rust", ".go": "go", ".java": "java", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".sql": "sql", ".sh": "bash", ".ps1": "powershell", ".css": "css",
    ".html": "html", ".json": "json", ".yml": "yaml", ".yaml": "yaml",
    ".toml": "toml", ".ini": "ini", ".xml": "xml", ".md": "markdown",
}

# 초안을 만드는 도구. 이것들은 `action_id` 만 돌려주고 내용은 따로 있다
# (`/v1/external-actions/{id}`) — 화면이 그 자리에서 승인할 수 있게 종류를 붙인다.
_DRAFT_TOOLS = frozenset({
    "google_gmail_prepare_send",
    "google_calendar_prepare_create",
    "google_calendar_prepare_update",
    "google_calendar_prepare_delete",
    "naver_blog_prepare_post",
    "naver_blog_prepare_publish",
    "naver_blog_prepare_save_draft",
})


@dataclass(slots=True)
class Observation:
    """걸음 하나가 실제로 본 것."""

    job_id: str
    step: int
    tool: str
    ok: bool
    status: str
    error: str
    arguments: dict[str, Any]
    kind: str
    title: str
    payload: dict[str, Any]
    # 화면용 shape는 표 셀을 400자로 줄인다. 산출물은 그 요약이 아니라 도구가
    # 돌려준 원 결과를 써야 하므로 JSON 원문을 보관소 상한까지 별도로 붙든다.
    raw_result_json: str
    at: float
    took_ms: int = 0
    # 어디서 얼마나 잘렸는가. 셋 다 적는다(도구·보관소·모델).
    truncation: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        """목록 한 줄. **본문을 싣지 않는다** — 목록이 무거우면 아무도 안 부른다."""
        return {
            "step": self.step,
            "tool": self.tool,
            "ok": self.ok,
            "status": self.status,
            "error": self.error,
            "kind": self.kind,
            "title": self.title,
            "at": self.at,
            "took_ms": self.took_ms,
            "truncated": bool(self.truncation.get("tool") or self.truncation.get("store")),
        }

    def full(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "arguments": self.arguments,
            "payload": self.payload,
            "truncation": self.truncation,
            **self.row(),
        }


def _text_of(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _clip(text: str, limit: int = _STORE_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _suffix(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def _tail(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or path


def _rows_from_dicts(items: list[Any]) -> dict[str, Any] | None:
    """dict 목록이면 표로. 열은 **먼저 나온 순서**를 지킨다(정렬하면 사람이 아는
    순서가 깨진다). 값이 또 dict/list 면 표에 못 넣으므로 그 목록은 포기한다."""
    rows = [item for item in items if isinstance(item, dict)]
    if not rows or len(rows) != len(items):
        return None
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns or len(columns) > 40:
        return None
    body: list[list[str]] = []
    for row in rows[:500]:
        line: list[str] = []
        for key in columns:
            value = row.get(key)
            if isinstance(value, (dict, list, tuple)):
                return None
            line.append("" if value is None else str(value)[:400])
        body.append(line)
    return {"columns": columns, "rows": body, "row_count": len(rows)}


def _sheets_from_tsv(text: str) -> dict[str, Any] | None:
    """xlsx 는 `[시트: 이름]` 다음에 탭으로 구분된 행으로 온다
    (`document_reader.py::_xlsx`). 그 모양이면 표로 세운다 — 백엔드에 손댈 것 없이
    화면이 표를 그릴 수 있다."""
    if "[시트:" not in text:
        return None
    sheets: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("[시트:"):
            current = {"name": line[4:].rstrip("]").strip(), "rows": []}
            sheets.append(current)
            continue
        if current is None or not line.strip():
            continue
        if len(current["rows"]) < 500:
            current["rows"].append([cell[:400] for cell in line.split("\t")])
    if not sheets:
        return None
    for sheet in sheets:
        rows = sheet["rows"]
        sheet["columns"] = rows[0] if rows else []
        sheet["rows"] = rows[1:]
        sheet["row_count"] = max(0, len(rows) - 1)
    return {"sheets": sheets}


def shape(
    tool: str, arguments: dict[str, Any], result: dict[str, Any]
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """도구 결과 → `(종류, 제목, 내용, 잘림)`.

    판정은 **결정론**이다. 모델에게 물어보지 않는다 — 그러면 같은 도구가 판마다
    다른 칸에 뜬다. 순서가 곧 우선순위다: 확실한 것부터 걸러 낸다.

    어느 것에도 안 걸리면 `note` 로 떨어진다. **버리지 않는다** — 새 도구가 조용히
    사라지는 것이 제일 나쁜 결말이고, 우리는 그 구멍으로 눈금이 두 번 샜다.
    """
    result = result if isinstance(result, dict) else {}
    truncation: dict[str, Any] = {}

    # 도구 자신이 잘랐다고 말했으면 그대로 옮긴다.
    if result.get("truncated"):
        truncation["tool"] = True
    if isinstance(result.get("char_count"), int):
        truncation["char_count"] = result["char_count"]

    path = _text_of(result.get("path")) or _text_of(arguments.get("path"))
    content = _text_of(result.get("content")) or _text_of(result.get("text"))

    # ── 초안 ── 내용은 external_actions 에 있고 여기엔 표만 온다.
    if tool in _DRAFT_TOOLS or (
        result.get("action_id") and tool.endswith(("_prepare_send", "_prepare_post"))
    ):
        return "draft", str(result.get("summary") or "보낼 것을 준비했습니다"), {
            "action_id": str(result.get("action_id") or ""),
            "kind": str(result.get("kind") or tool),
            "fields": {k: v for k, v in result.items() if isinstance(v, (str, int, float, bool))},
        }, truncation

    # ── 목록 ── 폴더·검색 결과.
    for key in ("entries", "files", "matches", "items"):
        raw = result.get(key)
        if isinstance(raw, list) and raw and tool.startswith(("local_", "site_", "schedule_", "undo_")):
            table = _rows_from_dicts(raw)
            if table:
                return "files", f"{_tail(path) or tool} · {table['row_count']}개", {
                    "root": path, **table,
                }, truncation

    # ── 코드 · 문서 ── 파일을 읽은 것.
    if content and (path or tool.startswith(("local_read", "google_drive_read", "google_docs"))):
        stored, cut = _clip(content)
        if cut:
            truncation["store"] = True
            truncation.setdefault("char_count", len(content))
        language = _CODE_LANGUAGES.get(_suffix(path), "")
        sheets = _sheets_from_tsv(stored)
        if sheets:
            return "table", f"{_tail(path)} · 시트 {len(sheets['sheets'])}개", {
                "path": path, "source": "xlsx", **sheets,
            }, truncation
        if language and language != "markdown":
            return "code", _tail(path) or "파일", {
                "path": path,
                "language": language,
                "text": stored,
                "line_count": stored.count("\n") + 1,
            }, truncation
        return "document", _tail(path) or _text_of(result.get("title")) or "문서", {
            "path": path,
            "format": str(result.get("format") or _suffix(path).lstrip(".") or "text"),
            "text": stored,
            "pages": result.get("pages"),
            "sheets": result.get("sheets"),
        }, truncation

    # ── 웹 화면 ── 주소가 있으면 브라우저 쪽이다.
    url = _text_of(result.get("url"))
    if url or tool.startswith("browser_"):
        text = _text_of(result.get("text"))
        stored, cut = _clip(text)
        if cut:
            truncation["store"] = True
            truncation.setdefault("char_count", len(text))
        elements = result.get("elements") if isinstance(result.get("elements"), list) else []
        title = _text_of(result.get("title")) or url or tool
        payload: dict[str, Any] = {
            "url": url,
            "title": _text_of(result.get("title")),
            "text": stored,
            "action": _text_of(result.get("action")),
        }
        if elements:
            table = _rows_from_dicts(elements[:200])
            if table:
                payload["elements"] = table
        return "page", title, payload, truncation

    # ── 표 ── 행 목록을 돌려주는 것은 전부 표다.
    #
    # ★ 키 이름 목록으로 고르지 않는다. 처음엔 ("rows","results","candidates",…) 로
    #   적어 뒀는데, 라이브에서 `windows_list_open_windows` 가 `windows` 키를 쓴다는
    #   이유만으로 표가 아니라 날 JSON 으로 떨어졌다(2026-08-19 실측). 도구는 102개고
    #   각자 제 이름으로 목록을 담는다 — 목록을 손으로 관리하면 반드시 새 것이 빠진다.
    #   그래서 **모양으로** 고른다: dict 들의 list 면 표다.
    #
    #   아는 이름을 먼저 보는 이유는 결정론이다. 한 결과에 목록이 둘이면(예: `items`
    #   와 `debug`) 판마다 다른 것이 표로 뜨면 안 된다.
    known = ("rows", "results", "candidates", "records", "items")
    for key in (*known, *(k for k in result if k not in known)):
        raw = result.get(key)
        if isinstance(raw, list) and raw:
            table = _rows_from_dicts(raw)
            if table:
                return "table", f"{tool} · {table['row_count']}행", {"source": tool, "field": key, **table}, truncation

    # ── 그 밖에 ── 통째로 보여 준다. 안 보여 주는 것보다 낫다.
    body = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    stored, cut = _clip(body)
    if cut:
        truncation["store"] = True
        truncation.setdefault("char_count", len(body))
    return "note", tool, {"text": stored, "language": "json"}, truncation


class ObservationStore:
    """잡별 걸음 보관소. 여러 스레드가 같이 쓴다(에이전트는 워커, API 는 별도).

    상한이 셋이다 — 잡 수 · 잡당 걸음 수 · 걸음당 글자 수. 셋 중 하나만 낮아도
    나머지는 일하지 않는다(사고 Q). 그래서 셋을 여기 **한자리에** 둔다.
    """

    def __init__(
        self,
        *,
        max_jobs: int = _MAX_JOBS,
        max_steps: int = _MAX_STEPS,
        ttl_sec: int = _TTL_SEC,
    ) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[int, Observation]] = {}
        self._touched: dict[str, float] = {}
        self.max_jobs = max_jobs
        self.max_steps = max_steps
        self.ttl_sec = ttl_sec

    def record(
        self,
        *,
        job_id: str,
        step: int,
        tool: str,
        arguments: dict[str, Any],
        observation: dict[str, Any],
        took_ms: int = 0,
    ) -> Observation:
        result = observation.get("result")
        result = result if isinstance(result, dict) else {}
        kind, title, payload, truncation = shape(tool, arguments or {}, result)
        raw_body = json.dumps(result, ensure_ascii=False, default=str)
        raw_result_json, raw_cut = _clip(raw_body)
        if raw_cut:
            truncation["store"] = True
            truncation.setdefault("char_count", len(raw_body))

        # 모델은 얼마나 봤는가. 화면이 "모델이 본 것"과 "실제로 있던 것"을 나란히
        # 보여 줄 수 있어야 「봤다고 말한 것」을 대조할 수 있다.
        try:
            wire = len(json.dumps(observation, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            wire = 0
        truncation["to_model"] = min(wire, MODEL_TRANSCRIPT_CHARS)
        if wire > MODEL_TRANSCRIPT_CHARS:
            truncation["model_cut"] = True

        item = Observation(
            job_id=job_id,
            step=step,
            tool=tool,
            ok=bool(observation.get("ok")),
            status=str(observation.get("status") or ""),
            error=str(observation.get("error") or "")[:500],
            # 실패한 걸음은 인자를 길게 남긴다 — 300자에서 잘려 「무엇을 보냈길래 5번 실패했나」를 못 봤다(2026-10-01 AWS 엑셀).
            arguments={
                k: str(v)[: (300 if observation.get("ok") else 4000)] for k, v in (arguments or {}).items()
            },
            kind=kind,
            title=title[:200],
            payload=payload,
            raw_result_json=raw_result_json,
            at=time.time(),
            took_ms=max(0, int(took_ms)),
            truncation=truncation,
        )
        with self._lock:
            steps = self._jobs.setdefault(job_id, {})
            steps[step] = item
            if len(steps) > self.max_steps:
                for old in sorted(steps)[: len(steps) - self.max_steps]:
                    steps.pop(old, None)
            self._touched[job_id] = item.at
            self._evict_locked()
        return item

    def list_steps(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            steps = self._jobs.get(job_id) or {}
            return [steps[key].row() for key in sorted(steps)]

    def get(self, job_id: str, step: int) -> dict[str, Any] | None:
        with self._lock:
            found = (self._jobs.get(job_id) or {}).get(step)
            return found.full() if found else None

    def get_for_artifact(self, job_id: str, step: int) -> dict[str, Any] | None:
        """산출물 배선만 원 결과를 받는다. 화면용 HTTP 본문은 두 배로 키우지 않는다."""
        with self._lock:
            found = (self._jobs.get(job_id) or {}).get(step)
            if found is None:
                return None
            return {**found.full(), "raw_result_json": found.raw_result_json}

    def forget(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
            self._touched.pop(job_id, None)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"jobs": len(self._jobs), "steps": sum(len(v) for v in self._jobs.values())}

    def _evict_locked(self) -> None:
        now = time.time()
        for job_id, at in list(self._touched.items()):
            if now - at > self.ttl_sec:
                self._jobs.pop(job_id, None)
                self._touched.pop(job_id, None)
        while len(self._jobs) > self.max_jobs:
            oldest = min(self._touched, key=lambda key: self._touched[key])
            self._jobs.pop(oldest, None)
            self._touched.pop(oldest, None)
