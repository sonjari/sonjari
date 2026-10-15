"""이어받기 — 클로드·코덱스가 한도에 멈춘 자리를 찾아 자비스가 받는다 (전략안 §44).

## 반자동이다 (2026-09-14 사용자 결정)

자동으로 알림을 밀지 않는다. 사람이 자비스에게 「다 썼어」·「limit 걸림」·「額度用完了」처럼
**어떤 말로든** 말하면, 자비스가 이 PC 에 남은 기록에서 **어느 도구의 어느 대화가 어디서
멈췄는지** 찾아 「이 대화를 이어갈까요?」라고 묻는다.

- 훅이 없는 도구(코덱스·커서)에서도 통하고, 남의 프로그램 설정을 안 고쳐도 첫날부터 된다.
- 틀리게 짚어도 사람이 한 번 확인하므로 사고가 안 난다.

## 판정은 두 겹이다 — 증거 × 의도

낱말표는 안 쓴다. 「보고서 다 썼어」와 「클로드 다 썼어」는 모양이 같고(이 저장소는 낱말표
라우팅으로 창작 78% 를 겪었다), 공개 제품은 모든 언어로 들어온다.

1. **증거 먼저.** 최근에 한도로 멈춘 대화가 기록에 있을 때만 판정을 켠다. 없으면 평소 대화는
   한 글자도 느려지지 않고, 잘못 잡힐 일도 없다.
2. **의도는 모델이.** 증거를 같이 주고 `takeover / not / unclear` 하나만 받는다.

## 멈춤은 **구조 흔적**으로만 판정한다 (2026-09-14 개발 PC 실측)

- 클로드 코드: 한도 줄은 `isApiErrorMessage: true` + `error: "rate_limit"`. 이런 줄이 19개 파일에
  23번, 대화가 그 줄로 **끝난** 것이 13개. 본문 23개 중 22개에 재개 시각 문구.
- 코덱스: `token_count` 의 `rate_limits.primary/secondary.used_percent`(≥100 이 635번)와
  `resets_at`(epoch). 끝난 작업의 `error` 21, 도중 끊김 `turn_aborted` 19.
- 기록 속 「rate limit」 **낱말 개수는 눈금이 못 된다** — 코드·논의 속 낱말이고 이 세션 자체도 걸렸다.
- 커서는 대화가 비공개 DB 키에 있어 형식이 보장되지 않는다 → 1차에서는 안 읽는다(정직하게 밝힌다).

## 「만지던 파일」은 기록이 아니라 git 에서

코덱스 기록의 도구 호출은 거의 전부 `exec`(셸) 하나라 파일을 못 뽑는다. `git status` 는 어느 도구든
똑같이 보이므로 그쪽이 공통 근거다. 기록에서 뽑은 경로는 보조로만 붙인다.

## H2 — 이어 작업은 **사용자 폴더를 안 건드린다**

git 워크트리를 자비스 출력 폴더(`output_dir/workspace/takeover`, 코드 모드가 이미 허용한 자리)에
만들고, 멈춘 순간의 미커밋 변경을 옮겨 시작점으로 삼는다. 끝나면 거기서만 커밋하고 「검토 대기」로
둔다. 버리면 워크트리와 가지를 지운다 — 원래 폴더는 그대로다.
"""

from __future__ import annotations

import copy
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from .secret_scrub import scrub

TOOL_NAMES = {"claude_code": "Claude Code", "codex": "Codex"}
HEAD_BYTES = 400_000
TAIL_BYTES = 2_500_000
# 한 번 훑을 때 볼 최근 파일 수. 사람은 대개 방금 쓰던 대화를 말한다.
SCAN_FILES = 40
# 「최근에 멈췄다」의 창. 넘으면 증거로 안 쓴다 — 어제 멈춘 대화 때문에 오늘 말이 잡히면 안 된다.
STOP_WINDOW_SEC = 3 * 3600
# 한 번 물은 뒤 답을 기다리는 창.
OFFER_WINDOW_SEC = 30 * 60
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
MAX_UNTRACKED_COPY = 400
MAX_UNTRACKED_BYTES = 50_000_000


def _clean(text: str, limit: int) -> str:
    """보여 주거나 저장하는 글은 **전부** 비밀을 걷고 자른다. 자른 사실은 끝에 남긴다."""
    value = scrub(" ".join(str(text or "").split()))["text"]
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _epoch(stamp: Any) -> float:
    if isinstance(stamp, (int, float)):
        return float(stamp)
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _read_lines(path: Path) -> tuple[list[str], int]:
    """머리와 꼬리만 읽는다 — 대화 기록은 수십 MB 가 된다. 돌려주는 두 번째 값은 건너뛴 바이트."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size <= HEAD_BYTES + TAIL_BYTES:
            return fh.read().decode("utf-8", "replace").splitlines(), 0
        head = fh.read(HEAD_BYTES).decode("utf-8", "replace").splitlines()[:-1]
        fh.seek(size - TAIL_BYTES)
        tail = fh.read().decode("utf-8", "replace").splitlines()[1:]
    return head + tail, size - HEAD_BYTES - TAIL_BYTES


@dataclass
class SessionState:
    tool: str
    path: str
    session_id: str = ""
    cwd: str = ""
    title: str = ""
    last_activity: float = 0.0
    stop_kind: str = "none"  # rate_limit | api_error | aborted | none
    stop_message: str = ""
    resets_at: float = 0.0
    first_request: str = ""
    last_request: str = ""
    request_count: int = 0
    last_reply: str = ""
    edited_files: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    open_tasks: list[str] = field(default_factory=list)
    unreadable_lines: int = 0
    skipped_bytes: int = 0

    @property
    def tool_name(self) -> str:
        return TOOL_NAMES.get(self.tool, self.tool)


def _is_human_text(text: str) -> bool:
    """사람이 친 말인가. 도구가 끼워 넣은 `<system-reminder>`·`<command-name>` 같은 봉투는 뺀다."""
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith("<")


def _text_blocks(content: Any, kinds: tuple[str, ...] = ("text",)) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") in kinds
        )
    return ""


# ── 클로드 코드 ───────────────────────────────────────────────────────────────
def read_claude_session(path: Path) -> SessionState | None:
    try:
        lines, skipped = _read_lines(Path(path))
    except OSError:
        return None
    state = SessionState(tool="claude_code", path=str(path), skipped_bytes=skipped)
    tasks: list[str] = []
    task_status: dict[str, str] = {}
    last_turn: dict[str, Any] | None = None
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            state.unreadable_lines += 1
            continue
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type")
        state.session_id = state.session_id or str(obj.get("sessionId") or "")
        if obj.get("cwd"):
            state.cwd = str(obj["cwd"])
        if kind == "custom-title" and obj.get("customTitle"):
            state.title = str(obj["customTitle"])
        stamp = _epoch(obj.get("timestamp"))
        if stamp:
            state.last_activity = max(state.last_activity, stamp)
        if kind not in {"user", "assistant", "system"}:
            continue
        message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        content = message.get("content")
        if kind == "user":
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                last_turn = obj
                continue
            text = _text_blocks(content)
            if _is_human_text(text) and not obj.get("isMeta"):
                state.first_request = state.first_request or text
                state.last_request = text
                state.request_count += 1
                last_turn = obj
            continue
        if kind == "system":
            if obj.get("level") == "error":
                last_turn = obj
            continue
        last_turn = obj
        if obj.get("isApiErrorMessage"):
            continue
        reply = _text_blocks(content)
        if reply.strip():
            state.last_reply = reply
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = str(block.get("name") or "")
            args = block.get("input") if isinstance(block.get("input"), dict) else {}
            if name in EDIT_TOOLS and args.get("file_path"):
                target = str(args["file_path"])
                if target in state.edited_files:
                    state.edited_files.remove(target)
                state.edited_files.append(target)
            elif name in SHELL_TOOLS and args.get("command"):
                state.commands.append(str(args["command"]).splitlines()[0])
            elif name == "TaskCreate" and args.get("subject"):
                tasks.append(str(args["subject"]))
            elif name == "TaskUpdate" and args.get("taskId"):
                task_status[str(args["taskId"])] = str(args.get("status") or "")
            elif name == "TodoWrite" and isinstance(args.get("todos"), list):
                tasks = [str(t.get("content") or "") for t in args["todos"] if isinstance(t, dict)]
                task_status = {
                    str(i + 1): str(t.get("status") or "")
                    for i, t in enumerate(args["todos"])
                    if isinstance(t, dict)
                }
    # 할 일 번호는 만든 순서다(1부터). 기록에 결과 줄까지 매칭하지 않는다 — 근사라서 화면에도 그렇게 적는다.
    state.open_tasks = [
        subject for index, subject in enumerate(tasks)
        if task_status.get(str(index + 1)) not in {"completed", "deleted"}
    ]
    if last_turn is not None:
        if last_turn.get("type") == "assistant" and last_turn.get("isApiErrorMessage"):
            error = str(last_turn.get("error") or "")
            state.stop_kind = "rate_limit" if error == "rate_limit" else "api_error"
            msg = last_turn.get("message") if isinstance(last_turn.get("message"), dict) else {}
            state.stop_message = _text_blocks(msg.get("content"))
        elif last_turn.get("type") == "system" and last_turn.get("level") == "error":
            state.stop_kind = "api_error"
            err = last_turn.get("error") if isinstance(last_turn.get("error"), dict) else {}
            state.stop_message = str(err.get("message") or err.get("formatted") or "")
    return state


# ── 코덱스 ────────────────────────────────────────────────────────────────────
def read_codex_session(path: Path) -> SessionState | None:
    try:
        lines, skipped = _read_lines(Path(path))
    except OSError:
        return None
    state = SessionState(tool="codex", path=str(path), skipped_bytes=skipped)
    last_limits: dict[str, Any] = {}
    last_event = ""
    last_error = ""
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            state.unreadable_lines += 1
            continue
        if not isinstance(obj, dict):
            continue
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        kind = obj.get("type")
        sub = payload.get("type")
        stamp = _epoch(obj.get("timestamp"))
        if stamp:
            state.last_activity = max(state.last_activity, stamp)
        if kind == "session_meta":
            state.session_id = str(payload.get("id") or payload.get("session_id") or "")
            state.cwd = str(payload.get("cwd") or state.cwd)
        elif kind == "turn_context" and payload.get("cwd"):
            state.cwd = str(payload["cwd"])
        elif kind == "response_item" and sub == "message":
            role = payload.get("role")
            text = _text_blocks(payload.get("content"), ("input_text", "output_text", "text"))
            if role == "user" and _is_human_text(text):
                state.first_request = state.first_request or text
                state.last_request = text
                state.request_count += 1
            elif role == "assistant" and text.strip():
                state.last_reply = text
        elif kind == "response_item" and sub in {"custom_tool_call", "function_call"}:
            raw = payload.get("input") if sub == "custom_tool_call" else payload.get("arguments")
            if isinstance(raw, str) and raw.strip():
                state.commands.append(raw.strip().splitlines()[0])
        elif kind == "event_msg" and sub == "token_count" and isinstance(payload.get("rate_limits"), dict):
            last_limits = payload["rate_limits"]
        elif kind == "event_msg" and sub in {"task_started", "task_complete", "turn_aborted"}:
            last_event = str(sub)
            err = payload.get("error")
            last_error = (
                str(err.get("message") or "") if isinstance(err, dict) else str(err or "")
            ) if sub == "task_complete" else ""
    windows = [w for w in (last_limits.get("primary"), last_limits.get("secondary")) if isinstance(w, dict)]
    full = [w for w in windows if float(w.get("used_percent") or 0) >= 100]
    if full or last_limits.get("rate_limit_reached_type"):
        state.stop_kind = "rate_limit"
        state.resets_at = max((float(w.get("resets_at") or 0) for w in (full or windows)), default=0.0)
    elif last_event == "task_complete" and last_error:
        state.stop_kind = "api_error"
        state.stop_message = last_error
    elif last_event == "turn_aborted":
        state.stop_kind = "aborted"
    return state


# ── 찾기 ──────────────────────────────────────────────────────────────────────
def session_files(home: Path) -> list[tuple[str, Path]]:
    """정해진 자리만 본다 — 각 도구의 **공식 기본 기록 위치**. 홈 전체를 훑지 않는다."""
    found: list[tuple[str, Path]] = []
    for tool, pattern in (
        ("claude_code", str(home / ".claude" / "projects" / "*" / "*.jsonl")),
        ("codex", str(home / ".codex" / "sessions" / "*" / "*" / "*" / "rollout-*.jsonl")),
    ):
        found += [(tool, Path(p)) for p in glob.glob(pattern)]
    return found


def recent_sessions(home: Path, *, now: float, window_sec: float, limit: int = SCAN_FILES) -> list[SessionState]:
    files = []
    for tool, path in session_files(home):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if now - mtime <= window_sec:
            files.append((mtime, tool, path))
    files.sort(reverse=True)
    out: list[SessionState] = []
    for _mtime, tool, path in files[:limit]:
        reader = read_claude_session if tool == "claude_code" else read_codex_session
        state = reader(path)
        if state is not None:
            state.last_activity = state.last_activity or _mtime
            out.append(state)
    # 한도로 멈춘 것이 먼저, 그다음 최근 것.
    out.sort(key=lambda s: (s.stop_kind != "rate_limit", s.stop_kind == "none", -s.last_activity))
    return out


def is_substantive(state: SessionState) -> bool:
    """실제로 일을 한 대화인가 — 고친 파일·명령이 있거나 요청이 여러 번 오갔다."""
    return bool(state.edited_files or state.commands) or state.request_count >= 3


def pick_resume_source(stop: SessionState, sessions: list[SessionState]) -> SessionState:
    """멈춘 대화가 **헛시도**면 같은 폴더의 진짜 작업 대화를 찾는다.

    ★ 2026-09-14 개발 PC: 한도로 멈춘 대화 상위 10개가 전부 편집 0·할 일 0 이었다. 한도에 걸린 뒤
      새 대화를 열어 다시 해 볼 때마다 즉시 막힌 흔적이다. 그걸 이어받으면 **빈 대화를 이어받는다.**
      증거(멈췄다)는 헛시도에서, 내용(무엇을 하던 중)은 그 앞의 같은 폴더 작업 대화에서 가져온다.
    """
    if is_substantive(stop) or not stop.cwd:
        return stop
    want = os.path.normcase(os.path.abspath(stop.cwd))
    same = [s for s in sessions
            if s is not stop and s.cwd and os.path.normcase(os.path.abspath(s.cwd)) == want
            and is_substantive(s) and s.last_activity <= stop.last_activity + 60]
    return max(same, key=lambda s: s.last_activity) if same else stop


# ── git ───────────────────────────────────────────────────────────────────────
Runner = Callable[..., subprocess.CompletedProcess]


def _git(run: Runner, cwd: str, *args: str, input_bytes: bytes | None = None, timeout: float = 20) -> subprocess.CompletedProcess:
    return run(
        ["git", "-C", cwd, *args],
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
    )


def git_state(cwd: str, run: Runner = subprocess.run) -> dict[str, Any]:
    """이 폴더가 git 저장소인지와 지금 무엇이 바뀌어 있는지. git 이 없거나 저장소가 아니면 그렇다고 말한다."""
    if not cwd or not Path(cwd).is_dir():
        return {"repo": False, "reason": "folder_missing"}
    if shutil.which("git") is None and run is subprocess.run:
        return {"repo": False, "reason": "git_not_installed"}
    try:
        inside = _git(run, cwd, "rev-parse", "--show-toplevel")
        if inside.returncode != 0:
            return {"repo": False, "reason": "not_a_git_repo"}
        # ★ git 은 윈도우에서도 `C:/Users/...` 처럼 슬래시로 준다. 그대로 사람에게 보이면 낯설고 탐색기에
        #   붙여 넣기도 어색하다(데모 문장을 뽑다 발견). 운영체제 표기로 정리한다.
        top = os.path.normpath(inside.stdout.decode("utf-8", "replace").strip())
        branch = _git(run, cwd, "rev-parse", "--abbrev-ref", "HEAD").stdout.decode("utf-8", "replace").strip()
        head = _git(run, cwd, "rev-parse", "--short", "HEAD").stdout.decode("utf-8", "replace").strip()
        # ★ 추적 중인 파일만 목록으로. 추적 안 한 파일은 **개수만** — 개발 PC 저장소가 8,967개로
        #   나왔다(출력물이 .gitignore 밖). 전 세계 저장소에 흔한 모양이라 목록에 넣으면 잡음이 된다.
        status = _git(run, cwd, "status", "--porcelain", "-uno").stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return {"repo": False, "reason": "git_failed"}
    changed = [line[3:].strip() for line in status.splitlines() if len(line) > 3]

    # ★ **덤 하나가 저장소 사실 전체를 버리면 안 된다** (2026-09-21 실전).
    #
    #   이어받기를 처음 실전에서 굴렸더니 `git_failed` 로 떨어져 간판 기능이
    #   「붙여넣을 쪽지」로 내려앉았다. 멀쩡한 저장소인데.
    #
    #   진짜 원인은 **개수 하나를 세려고 1.18MB 를 훑는 것**이었다:
    #
    #       ls-files --others --exclude-standard              9.7초 · 1,180,368바이트 · 11,880개
    #       ls-files --others --exclude-standard --directory  0.8초 ·     1,568바이트 ·     32개
    #
    #   `--directory` 는 통째로 추적 안 된 폴더를 **한 줄로 접는다.** 우리가 쓰는 것은
    #   개수뿐이니 그걸로 충분하고, 12배 싸다. 그래도 못 세면 **None 으로 두고 말한다** —
    #   0 으로 적으면 「추적 안 한 파일이 없다」가 되고, 그건 다른 사실이다.
    untracked_count: int | None = None
    untracked_note = ""
    try:
        others = _git(run, cwd, "ls-files", "--others", "--exclude-standard", "--directory", "-z",
                      timeout=10).stdout
        untracked_count = len([p for p in others.decode("utf-8", "replace").split("\0") if p])
    except (OSError, subprocess.TimeoutExpired):
        untracked_note = "추적 안 한 파일은 세지 못했습니다(저장소가 커서 시간이 걸립니다)."

    state: dict[str, Any] = {
        "repo": True, "root": top, "branch": branch, "head": head,
        "changed_count": len(changed), "changed": changed[:40],
        "untracked_count": untracked_count,
    }
    if untracked_note:
        state["untracked_note"] = untracked_note
    return state


# ── 카드 ──────────────────────────────────────────────────────────────────────
#: 인계 카드에 싣는 요청 길이. **요청이 곧 계약이다** — 여기가 잘리면 이어 할 모델은 요구를 못 본다.
#
# ★ 2026-09-23 실측: 400 이었다. 이어받기 실험의 요청(466자)이 「…test_textutil.py 에 wor…」에서 잘려
#   「테스트를 2개 이상 추가해」와 「마지막에 pytest 로 확인」이 **통째로 빠졌다.** 온텔릭은 세 판 중 두 판에서
#   그 테스트를 빠뜨렸고, 한 판은 「3가지 모두 완료」라고 답했다 — 못 본 요구를 지킬 수는 없다(사고 Q).
#   화면에 보여 줄 때만 짧게 자른다(`_offer_text`).
REQUEST_LIMIT = 4000


def build_card(state: SessionState, git: dict[str, Any], *, now: float) -> dict[str, Any]:
    """무엇을 하던 중이었는지 — **기록과 git 에 있는 것만.** 모델이 지어낸 줄은 없다."""
    # 대화에서 **실제로 고친 파일이 먼저**(최근 것부터), 그다음 git 이 본 추적 파일 변경.
    files: list[str] = []
    root = str(git.get("root") or "")
    for path in reversed(state.edited_files[-12:]):
        rel = path
        if root and path.replace("\\", "/").lower().startswith(root.replace("\\", "/").lower()):
            rel = path[len(root):].lstrip("\\/")
        rel = rel.replace("\\", "/")
        if rel not in files:
            files.append(rel)
    for rel in git.get("changed") or []:
        if rel not in files:
            files.append(rel)
    return {
        "request_count": state.request_count,
        "tool": state.tool,
        "tool_name": state.tool_name,
        "session_id": state.session_id,
        "session_path": state.path,
        "title": _clean(state.title or state.first_request, 80),
        "cwd": state.cwd,
        "stop_kind": state.stop_kind,
        "stopped_minutes_ago": max(0, int((now - state.last_activity) // 60)) if state.last_activity else None,
        "resets_at": state.resets_at or None,
        "stop_message": _clean(state.stop_message, 200),
        "first_request": _clean(state.first_request, REQUEST_LIMIT),
        "last_request": _clean(state.last_request, REQUEST_LIMIT),
        "last_reply": _clean(state.last_reply[-1200:], 600),
        "files": files[:30],
        "recent_commands": [_clean(c, 160) for c in state.commands[-5:]],
        "open_tasks": [_clean(t, 120) for t in state.open_tasks[:10]],
        "git": git,
        "read_gaps": {"unreadable_lines": state.unreadable_lines, "skipped_bytes": state.skipped_bytes},
    }


# ── 인계 방향 계약 ────────────────────────────────────────────────────────────
# ★ 2026-09-15 E2E. 「남은 일만 정리하기」를 골랐는데 첫 턴이 239.5초·19걸음을 돌고 docx 를 만들었다.
#   계획 층이 **긴 인계문 전체**에서 요구를 뽑았고, 카드 안의 할 일(「부가세 계산 확인」·「검증」)과
#   `resume_prompt` 의 규칙 문장이 계산·산출물 요구로 걸렸다. 사람이 고른 방향은 계약으로 안 실렸다.
#   그래서 방향은 **잡의 필드**로 싣고, 요구는 사람에게 보인 문장 + 아래 한 줄에서만 뽑는다.
#   낱말을 더 막는 대신 **어느 글에서 요구를 뽑는가**를 바꾼다.
HANDOFF_INSTRUCTIONS: dict[str, str] = {
    "continue": "멈춘 자리와 남은 할 일부터 이어간다.",
    "review": "새 작업을 시작하기 전에 지금까지 한 일과 근거를 먼저 검토한다.",
    "tasks": "실행하지 않고 남은 할 일과 검증 순서만 체크리스트로 정리한다.",
}
# 읽기만 하는 방향. 쓰기·실행·산출물 손을 빼고, 완료는 체크리스트·검토 답이다.
READ_ONLY_HANDOFF_DIRECTIONS = frozenset({"review", "tasks"})
HANDOFF_DIRECTIONS = frozenset({*HANDOFF_INSTRUCTIONS, "custom"})


def handoff_instruction(direction: str, custom: str = "") -> str:
    """고른 방향의 한 줄 지시. 모르는 방향이나 빈 직접 입력은 빈 문자열."""
    if direction == "custom":
        return _clean(custom, 800)
    return HANDOFF_INSTRUCTIONS.get(direction, "")


#: 인계문에서 **원래 부탁**만 집어 오는 줄. 카드의 「남은 할 일」은 여기 안 든다.
_ORIGINAL_REQUEST_LINE = re.compile(r"^(?:마지막|처음) 요청:\s*(.+)$", re.MULTILINE)


def original_request(handoff_text: str) -> str:
    """멈춘 대화에서 **사람이 그 도구에게 한 부탁**. 마지막 것을 쓰고, 없으면 처음 것.

    카드의 `open_tasks`(모델이 남긴 할 일)는 **일부러 안 본다** — 그것이 계산·파일 과제로
    둔갑하던 자리다(W0). 이 줄은 사람이 적은 말이다.
    """
    found = _ORIGINAL_REQUEST_LINE.findall(handoff_text or "")
    return _clean(found[-1], 400) if found else ""


def handoff_contract(
    direction: str, display_prompt: str, handoff_text: str = ""
) -> tuple[str, bool] | None:
    """인계 잡의 (요구를 뽑을 문장, 읽기 전용인가). 인계 잡이 아니면 None.

    직접 입력(custom)은 사람이 적은 문장이 이미 보이는 문장에 들어 있으므로 그 문장만 쓴다.

    ## ★ 이어서 하는 판은 **원래 부탁**까지 요구로 센다 (2026-09-16 실측)

    보이는 문장(「멈춘 자리부터 이어서 해줘」)에는 개수도 산출물도 없다. 그래서 계획이
    **0개**로 섰고, 그 판은:

        되받기 0회 (빈 계획은 「아직 남았다」고 말할 것이 없다)
        완료 판정 `unmeasured`
        답 스스로 「엑셀 미완료·남은 작업」이라 적었는데 **잡은 completed**

    로 끝났다. 요구가 없으면 눈금도 되받기도 통째로 죽는다. 그래서 이어서 **하는** 방향에는
    인계문의 「마지막 요청」 한 줄을 붙인다 — 카드의 할 일이 아니라 **사람이 그 도구에게 한 말**이다.
    읽기 전용 방향(정리만·검토만)에는 안 붙인다. 거기서 산출물 요구를 세우면 못 채울
    체크리스트가 되고 되받기가 판을 붙잡는다.
    """
    shown = " ".join((display_prompt or "").split())
    if direction not in HANDOFF_DIRECTIONS or not shown:
        return None
    read_only = direction in READ_ONLY_HANDOFF_DIRECTIONS
    instruction = HANDOFF_INSTRUCTIONS.get(direction, "")
    text = f"{shown}\n{instruction}" if instruction else shown
    asked = "" if read_only else original_request(handoff_text)
    if asked and asked not in text:
        text = f"{text}\n{asked}"
    return text, read_only


# 읽기 전용 방향의 규칙. 기본 규칙(「git diff」·「시험을 돌려」)은 **이어서 고치는** 사람용이다.
# 「남은 일만 정리」를 고른 판에 그 규칙을 주면 모델이 명령부터 돌린다(W0 라이브: 첫 걸음이 git·diff).
# 손은 계약(`read_only`)이 이미 뺐다 — 여기서는 서로 어긋나는 지시를 안 주는 것뿐이다.
_READ_ONLY_RULES = {
    "tasks": [
        "1. 파일을 만들거나 고치지 않고, 계산·명령·시험도 실행하지 않는다.",
        "2. 위 기록에 있는 사실로 남은 일과 검증 순서를 체크리스트로 적는다. 기록만으로 모자라면 작업 폴더를 읽기만 한다.",
        "3. 계산·파일 만들기·시험은 「해야 할 일」 항목으로 적는다 — 직접 하지 않는다.",
        "4. 어디까지 된 것 같은지 판단한 근거(읽은 파일·기록 줄)를 짧게 붙인다.",
    ],
    "review": [
        "1. 파일을 만들거나 고치지 않고, 명령·시험도 실행하지 않는다.",
        "2. 바뀌어 있는 파일과 기록을 읽고 지금까지 한 일이 마지막 요청에 맞는지 검토한다.",
        "3. 확인한 것과 확인하지 못한 것을 나눠 적고, 고칠 곳은 제안으로만 적는다.",
    ],
}


def card_for_worktree(card: dict[str, Any], worktree: str | Path) -> dict[str, Any]:
    """카드의 원래 저장소 경로를 **가지 작업 자리** 경로로 바꾼 사본 (2026-09-23 실측).

    ★ 이어받기 B2·B3 에서 모델이 인계문의 원래 폴더 경로(작업 폴더 줄·파일 목록·클로드의 마지막 답)를
      그대로 따라가 **원래 폴더를 고쳤다.** 가지를 따로 판 뜻이 없어졌다. 경로를 주는 쪽이 맞는 경로를 준다.
    """
    import copy
    import re

    root = str(card.get("git", {}).get("root") or "")
    if not root:
        return card
    target = str(worktree)
    variants = sorted({root, root.replace("\\", "/"), root.replace("/", "\\")}, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(v) for v in variants), re.IGNORECASE)

    def swap(value: Any) -> Any:
        if isinstance(value, str):
            return pattern.sub(lambda _m: target, value)
        if isinstance(value, list):
            return [swap(item) for item in value]
        return value

    moved = copy.deepcopy(card)
    for key in ("cwd", "first_request", "last_request", "last_reply", "stop_message", "recent_commands", "open_tasks"):
        if key in moved:
            moved[key] = swap(moved[key])
    moved["git"] = {**moved.get("git", {}), "root": target}
    moved["original_root"] = root
    return moved


def resume_prompt(card: dict[str, Any], *, direction: str = "continue") -> str:
    """이어 할 모델(자비스든, 한도가 풀린 클로드든)에게 줄 지시문. 카드에 있는 사실만 옮긴다."""
    lines = [
        f"{card['tool_name']} 가 사용량 한도로 멈춘 작업을 이어서 한다.",
        f"작업 폴더: {card['cwd']}",
    ]
    # 한 번만 말한 대화면 처음과 마지막이 같다 — 같은 긴 글을 두 번 싣지 않는다.
    if card["first_request"] == card["last_request"]:
        lines.append(f"요청: {card['first_request']}")
    else:
        lines += [f"처음 요청: {card['first_request']}", f"마지막 요청: {card['last_request']}"]
    if any(str(card.get(key) or "").endswith("…") for key in ("first_request", "last_request")):
        lines.append(f"(요청이 길어 잘렸다 — 원문은 세션 기록 {card.get('session_path') or '(경로 없음)'} 에 있다. "
                     "빠진 요구가 있을 수 있으니 먼저 원문을 읽는다.)")
    if card.get("last_reply"):
        lines.append(f"멈추기 직전 답: {card['last_reply']}")
    if card.get("open_tasks"):
        lines.append("남은 할 일(기록 기준):\n" + "\n".join(f"- {t}" for t in card["open_tasks"]))
    if card.get("files"):
        # ★ 절대 경로로 적는다 (2026-09-16 실측). 상대 경로로 적어 줬더니 모델이 그 이름을 그대로 파일 도구에
        #   넘겼고, 작업 폴더가 아닌 곳으로 풀려 `path_outside_allowed_roots` 로 막혔다 — 이어받기가 첫 걸음에서
        #   죽었다. 경로를 주는 쪽이 온전한 경로를 준다.
        shown = [_absolute_file(card, str(name)) for name in _worth_showing(card.get("files") or [])]
        lines.append("바뀌어 있거나 만지던 파일:\n" + "\n".join(f"- {f}" for f in shown))
    if direction in _READ_ONLY_RULES:
        return "\n".join([*lines, "", "규칙:", *_READ_ONLY_RULES[direction]])
    # ★ 규칙은 **그 일의 모양**을 따라간다 (2026-09-16 실측).
    #   「git diff 로 읽어라 · 저장소의 시험을 돌려라」를 **채용 공고 조사** 판에 그대로 줬다.
    #   저장소가 아닌 폴더였는데도 코드 세션용 규칙이 갔고, 모델은 그 틀에 맞춰 「최종 보고」를
    #   쓰고 6걸음에서 끝냈다. 예산은 12 중 6 이 남아 있었다 — 멈춘 것은 모델이 아니라 우리 문장이다.
    lines += ["", "규칙:"]
    if card.get("original_root"):
        # 가지 작업 자리 — 멈춘 순간의 변경은 이미 **커밋**돼 있어서 `git diff` 가 비어 보인다(2026-09-23 실측).
        #   비어 보이니 모델이 「가지엔 아무것도 없고 원래 폴더에 있다」로 읽고 원래 폴더로 갔다.
        lines += [
            f"0. 원래 폴더({card['original_root']})는 **고치지 않는다.** 읽기·고치기·시험은 전부 작업 폴더에서 한다.",
            "1. 먼저 `git show --stat HEAD` 로 멈춘 순간의 변경(이 커밋에 담겨 있다)을 읽고, 마지막 요청이 어디까지 됐는지 판단한다.",
            "2. 남은 일만 한다. 이미 된 것을 다시 하지 않는다.",
            "3. 고친 뒤 이 저장소의 시험을 돌려 결과를 적는다. 못 돌렸으면 못 돌렸다고 적는다.",
        ]
    elif card.get("git", {}).get("root"):
        lines += [
            "1. 먼저 git diff 로 이미 바뀐 것을 읽고, 마지막 요청이 어디까지 됐는지 판단한다.",
            "2. 남은 일만 한다. 이미 된 것을 다시 하지 않는다.",
            "3. 고친 뒤 이 저장소의 시험을 돌려 결과를 적는다. 못 돌렸으면 못 돌렸다고 적는다.",
        ]
    else:
        lines += [
            "1. 먼저 작업 폴더의 기록(메모·중간 산출물)을 읽고 어디까지 됐는지 판단한다.",
            "2. 남은 일만 한다. 이미 된 것을 다시 하지 않는다.",
            "3. **처음 요청을 끝까지 해낸다.** 중간 보고로 끝내지 않는다 — 산출물(문서·엑셀 등)을 요청했으면 그것까지 만든다.",
        ]
    lines.append("4. 끝나면 무엇을 했고 무엇이 남았는지 짧게 적는다 — 한도가 풀린 원래 도구가 검토한다.")
    return "\n".join(lines)


#: 인계문에 실어도 쓸모가 없는 자리. 백업·캐시·산출물이 목록을 덮으면 진짜 파일이 안 보인다.
_NOISE_PARTS = ("backups", "backup", "__pycache__", "node_modules", "dist", "outputs", ".venv", ".git")


def _worth_showing(files: list[Any], limit: int = 8) -> list[str]:
    """★ 백업 폴더가 목록을 먹었다 (2026-09-16 실측).

    15줄 중 14줄이 `backups/ui_before_handoff_restore_.../` 사본이었고, 정작 이어받을 근거인
    `notes.md` 한 줄만 진짜였다. 사람이 읽어도 못 찾을 목록을 모델에게 준 셈이다.
    """
    clean = [str(f) for f in files
             if not any(part in str(f).replace("\\", "/").split("/") for part in _NOISE_PARTS)]
    return (clean or [str(f) for f in files])[:limit]


def _absolute_file(card: dict[str, Any], name: str) -> str:
    """상대 경로를 **실제로 사는 자리**에 붙인다.

    ★ 두 번 틀린 자리다. 처음엔 상대 경로를 그대로 줘서 `path_outside_allowed_roots` 로 막혔고,
    그래서 `cwd` 에 붙였더니 이번엔 **겹쳤다**:

        cwd = ...\yeosu_jobs ,  name = tools/e2e_takeover/home/Documents/yeosu_jobs/notes.md
        → ...\yeosu_jobs\tools\e2e_takeover\home\Documents\yeosu_jobs\notes.md   (없는 파일)

    git 이 준 목록은 **저장소 뿌리** 기준이고 `cwd` 는 그 아래 폴더였기 때문이다. 그래서
    후보를 순서대로 대 보고 **실제로 있는 것**을 쓴다. 하나도 없으면 가장 그럴듯한 하나를 준다 —
    지어내지 않고, 적어도 상대 경로를 그대로 주지는 않는다.
    """
    path = Path(name)
    if path.is_absolute():
        return str(path)
    bases = [str(card.get("git", {}).get("root") or ""), str(card.get("cwd") or "")]
    candidates = [Path(base) / path for base in bases if base]
    for candidate in candidates:
        try:
            if candidate.exists():
                return str(candidate)
        except OSError:
            continue
    return str(candidates[0]) if candidates else str(path)


# ── 의도 판정 ─────────────────────────────────────────────────────────────────
# ★ v2 (2026-09-14). v1 은 판정 문장에 「방금 한도로 멈춘 대화가 있다」는 증거를 같이 줬다.
#   그러자 모델이 **평범한 작업 요청까지** 그 멈춘 일을 이어 달라는 뜻으로 읽었다 — 과거 자비스
#   사용자 발화 300개 중 64개(21%) 오탐(「진행하자」·「나머지 다해줘」). 증거가 판정을 끌어당겼다.
#   그래서 증거는 **판정을 켤지만** 정하고, 모델은 **말 자체**만 본다. 애매한 말은 증거(멈춘 지
#   얼마나 됐나)로 한 번 더 가른다(`intercept`).
INTENT_SYSTEM = (
    "You classify ONE user message sent to a desktop assistant. Judge ONLY the message itself. "
    'Reply with JSON only: {"intent": "takeover" | "unclear" | "not"}.\n'
    '"takeover" = the message itself says an AI assistant or AI coding tool (Claude, Claude Code, Codex, Cursor, '
    "ChatGPT, Gemini, or 'the AI') hit a usage or rate limit, ran out of quota/tokens/credits, or got cut off because "
    "of that — or asks to take over the work such a tool left unfinished.\n"
    '"unclear" = a very short or vague message that might mean running out of an AI tool\'s usage but does not say so '
    '(for example "all used up", "blocked again", "cut off", "limit").\n'
    '"not" = everything else: ordinary task requests (including "continue", "do the rest", "let\'s proceed" about the '
    "assistant's own work), finishing one's own writing, money, battery, phone data, vacation, questions about how "
    "rate limits work, or writing rate-limit code.\nThe message may be in any language."
)
# 애매한 말을 물어볼 만큼 **최근**에 멈췄나. 넘으면 답 끝에 한 줄만 붙인다.
UNCLEAR_OFFER_WINDOW_SEC = 30 * 60
# 이 PC 에 Claude Code·Codex 기록이 하나도 없는데 이어받자고 했다. 할 수 없는 것을 할 수 있는 척하지 않는다.
NO_RECORDS_ANSWER = (
    "이 PC에서 최근 이틀 안의 Claude Code·Codex 대화 기록을 찾지 못했습니다. 이어받기는 이 PC에 남은 그 기록에서 시작합니다 — "
    "웹이나 휴대폰 채팅의 한도는 기록이 이 PC에 없어 이어받을 수 없습니다. 하던 일을 여기에 적어 주시면 그 일부터 바로 시작하겠습니다."
)
OFFER_SYSTEM = (
    "The assistant just asked the user whether to continue a stopped AI coding session. Classify the user's "
    'reply. JSON only: {"answer": "yes" | "no" | "other"}. Any language.'
)


# ★ 멈춘 기록이 **없을 때** 모델에게 물어볼지 정하는 싼 문 (2026-10-05 밤, 대표 실사용).
#
#   「클로드 한도걸렸어..」·「코덱스 한도걸렸어 이어받자」가 **한 글자도 안 읽히고** 평소 대화로 넘어갔다. 최근 3시간 안에
#   한도로 멈춘 기록이 없었기 때문이다(실제로 안 걸렸다) — 그러면 `intercept` 는 모델을 부르지도 않고 None 을 돌려줬다.
#   기능을 한 번 쳐 보는 사람(새 사용자·심사자)이 정확히 이 길로 들어온다: 대답은 엉뚱한 잡담이었다.
#
#   뜻은 여전히 **모델**이 가른다(`INTENT_SYSTEM`). 이 문은 「물어볼 값어치가 있는 말인가」만 본다 — 평소 대화마다 판정을 한 번씩
#   더 부르면 프롬프트 앞머리가 바뀌어 다음 답이 통째로 느려진다(2026-09-30 도구 목록 교훈). 그래서 한도·이어받기 **이야기**일 때만.
#   재 본 것(운영 모델, 문장마다 3번): 이어받자는 말 7개 21/21 · 아닌 말 6개 중 5개 15/15(「오늘 데이터 한도 다 썼네」 하나가 샌다 —
#   그때도 지어내지 않고 「한도로 멈춘 기록은 없다」고 말한 뒤 묻는다).
_WORTH_ASKING = re.compile(
    r"한도|사용량|토큰|쿼터|크레딧|리밋|이어\s?받|rate.?limit|usage|quota|credits?\b|tokens?\b|\blimit|take\s?over|"
    r"pick(?:s|ed)?\s+up\s+where|left\s+off|"
    r"(?:클로드|코덱스|커서|지피티|제미나이|코파일럿|claude|codex|cursor|chatgpt|gpt|gemini|copilot)"
    r".{0,24}(?:멈|막혔|막힘|끊|죽었|stopp|cut\s?off|blocked|died)",
    re.IGNORECASE,
)
# 멈춘 기록이 없을 때 「가장 최근에 하던 일」을 찾는 창.
NO_STOP_LOOKBACK_SEC = 48 * 3600
_NAMED_TOOL = (("codex", re.compile(r"코덱스|codex", re.IGNORECASE)),
               ("claude_code", re.compile(r"클로드|claude", re.IGNORECASE)))


def worth_asking(message: str) -> bool:
    return bool(_WORTH_ASKING.search(message or ""))


def named_tool(message: str) -> str:
    for tool, pattern in _NAMED_TOOL:
        if pattern.search(message or ""):
            return tool
    return ""


def intent_prompt(message: str) -> str:
    """증거를 **안 넣는다**(v2 주석). 말만 준다."""
    return f"User message:\n{message.strip()[:600]}"


def _stop_phrase(kind: object) -> str:
    """멈춘 이유는 기록된 `stop_kind` 가 말한다. 문구를 고정하면 오류로 멈춘 것도 「한도」가 된다."""
    return {
        "rate_limit": "사용량 한도로 멈췄습니다",
        "api_error": "오류로 멈췄습니다",
        "aborted": "중간에 멈췄습니다",
    }.get(str(kind or ""), "멈췄습니다")


def parse_label(raw: str, key: str, allowed: set[str], default: str) -> str:
    match = re.search(r"\{.*?\}", str(raw or ""), re.S)
    if match:
        try:
            value = str(json.loads(match.group(0)).get(key) or "").strip().lower()
            if value in allowed:
                return value
        except ValueError:
            pass
    # JSON 이 깨져도 낱말 하나는 건진다 — 단, 허용된 값만.
    words = re.findall(r"[a-z]+", str(raw or "").lower())
    for word in words:
        if word in allowed:
            return word
    return default


def evidence_line(state: SessionState, *, now: float) -> str:
    minutes = max(0, int((now - state.last_activity) // 60))
    folder = Path(state.cwd).name if state.cwd else "unknown folder"
    reason = {"rate_limit": "usage limit", "api_error": "an API error", "aborted": "being interrupted"}.get(
        state.stop_kind, "unknown reason")
    return f"{state.tool_name} session in '{folder}' stopped {minutes} min ago because of {reason}."


# ── 저장소 · 서비스 ───────────────────────────────────────────────────────────
class TakeoverService:
    """반자동 이어받기. 파일·git·모델·시계는 주입할 수 있다 — 시험이 가짜를 넣는다."""

    def __init__(
        self,
        config: Any,
        *,
        ask: Callable[[str, str], str] | None = None,
        submit: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        run: Runner = subprocess.run,
        home: Path | None = None,
        clock: Callable[[], float] = time.time,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.db_path = Path(config.database_path)
        self.ask = ask
        self.submit = submit
        self.run = run
        self._home = home
        self.clock = clock
        self.publish = publish or (lambda _e, _p: None)
        self.enabled = bool(getattr(config, "takeover_enabled", True))
        self.branch_enabled = bool(getattr(config, "takeover_branch_enabled", False))
        self.worktree_root = Path(config.output_dir) / "workspace" / "takeover"
        # 창 크기별로 따로 둔다 — 한 칸에 두면 3시간 창이 7일 창의 결과를 돌려준다.
        self._scan_cache: dict[float, tuple[float, list[SessionState]]] = {}
        self._init_db()

    @property
    def home(self) -> Path:
        return self._home or Path.home()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS takeovers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stop_key TEXT NOT NULL UNIQUE,
                    tool TEXT NOT NULL,
                    session_path TEXT NOT NULL,
                    cwd TEXT NOT NULL DEFAULT '',
                    card_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    chat_session TEXT NOT NULL DEFAULT '',
                    branch TEXT NOT NULL DEFAULT '',
                    worktree TEXT NOT NULL DEFAULT '',
                    base_ref TEXT NOT NULL DEFAULT '',
                    job_id TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    # ---- 찾기 ------------------------------------------------------------
    def sessions(self, *, window_sec: float, fresh: bool = False) -> list[SessionState]:
        now = self.clock()
        cached_at, cached = self._scan_cache.get(window_sec, (0.0, []))
        if not fresh and now - cached_at < 20 and cached:
            return cached
        found = recent_sessions(self.home, now=now, window_sec=window_sec)
        self._scan_cache[window_sec] = (now, found)
        return found

    def scan(self, *, hours: float = 12.0) -> dict[str, Any]:
        now = self.clock()
        # ★ 같은 폴더의 git 상태는 **한 번만** 본다 (2026-10-06 포장본 관문 시간 초과).
        #   이 목록이 36초 걸렸고 그중 34.5초가 git 이었다 — 대화 12개 중 10개가 같은 폴더였는데 폴더를 대화마다 다시 봤다
        #   (큰 저장소에서 한 번에 2.9초). 설정 › 이어받기 화면을 여는 사람이 그 시간을 그대로 기다렸다.
        seen: dict[str, dict[str, Any]] = {}

        def git_for(cwd: str) -> dict[str, Any]:
            key = os.path.normcase(os.path.abspath(cwd)) if cwd else ""
            if key not in seen:
                seen[key] = git_state(cwd, self.run)
            return copy.deepcopy(seen[key])  # 카드가 저마다 고쳐도 서로 물들지 않게

        cards = [build_card(s, git_for(s.cwd), now=now)
                 for s in self.sessions(window_sec=hours * 3600, fresh=True)[:12]]
        return {"sessions": cards, "cursor_supported": False,
                "note": "커서는 대화가 공개 형식이 아니라 아직 읽지 않습니다."}

    def _recent_stops(self) -> list[SessionState]:
        return [s for s in self.sessions(window_sec=STOP_WINDOW_SEC)
                if s.stop_kind == "rate_limit" and self.clock() - s.last_activity <= STOP_WINDOW_SEC]

    @staticmethod
    def _stop_key(state: SessionState) -> str:
        return f"{state.path}|{int(state.last_activity)}"

    # ---- 채팅 가로채기 ---------------------------------------------------
    def intercept(self, prompt: str, chat_session: str, *, capsule_visible: bool = False) -> dict[str, Any] | None:
        """이어받기와 관계된 말이면 답을 준다. 아니면 None — 평소 대화는 그대로 간다."""
        if not self.enabled or self.ask is None or not prompt.strip():
            return None
        offered = self._open_offer(chat_session)
        if offered is not None:
            answer = parse_label(self.ask(OFFER_SYSTEM, prompt.strip()[:400]), "answer", {"yes", "no", "other"}, "other")
            if answer == "yes":
                # ★ 채팅의 「응」은 **가지를 파지 않는다** (2026-09-20). 부수효과가 있는 일은
                #   사람이 무엇이 벌어질지 보고 누를 때만 — 그 자리는 화면 캡슐의 단추다.
                return self.accept(int(offered["id"]), via="chat")
            if answer == "no":
                self._set(int(offered["id"]), status="dismissed")
                return {"answer": "알겠습니다. 이 대화는 이어받지 않겠습니다. 필요하면 다시 말씀해 주세요.",
                        "takeover_id": int(offered["id"]), "kind": "declined"}
            # 다른 말이면 제안을 거둔다 — 사람이 딴 얘기로 넘어갔는데 계속 붙잡으면 안 된다.
            self._set(int(offered["id"]), status="expired")
            return None
        stops = [s for s in self._recent_stops() if not self._already_handled(self._stop_key(s))]
        if not stops:
            return self._asked_without_a_recent_stop(prompt, chat_session, capsule_visible=capsule_visible)
        now = self.clock()
        top = stops[0]
        label = parse_label(
            self.ask(INTENT_SYSTEM, intent_prompt(prompt)),
            "intent", {"takeover", "not", "unclear"}, "not",
        )
        recent = now - top.last_activity <= UNCLEAR_OFFER_WINDOW_SEC
        self.publish("takeover_intent", {"label": label, "tool": top.tool, "recent": recent})
        if label == "not":
            return None
        card = self._card_for_stop(top, now)
        takeover_id = self._record(top, card, chat_session, status="offered")
        if label == "unclear" and not recent:
            return {"hint": self._hint(card), "takeover_id": takeover_id, "kind": "hint"}
        # Cowork 화면은 이 사건으로 오른쪽 「자비스의 컴퓨터」 칸을 인계 캡슐로
        # 바꾼다. 답 문자열을 다시 해석하지 않는다 — 화면이 자연어에서 id·경로를
        # 긁어내기 시작하면 문구를 고치는 순간 배선이 끊긴다.
        self.publish("takeover_offered", {
            "takeover_id": takeover_id,
            "card": card,
            "other_count": max(0, len(stops) - 1),
        })
        # ★ 캡슐이 떠 있는 화면(전체화면 Cowork)에서는 채팅 답을 **한 줄**로 줄인다(TODO 7차 결정, 2026-09-15).
        #   폴더·마지막 요청·남은 일을 캡슐과 채팅이 똑같이 두 번 말하면 사람은 어느 쪽을 눌러야 하는지 헷갈린다.
        #   음성·작은 창처럼 캡슐이 없는 입구는 지금처럼 긴 설명을 준다 — 거기선 그게 유일한 화면이다.
        answer = self._offer_line(card) if capsule_visible else self._offer_text(card, others=len(stops) - 1)
        return {"answer": answer, "takeover_id": takeover_id, "kind": "offer", "card": card}

    def _asked_without_a_recent_stop(self, prompt: str, chat_session: str, *, capsule_visible: bool) -> dict[str, Any] | None:
        """최근 3시간 안에 한도로 멈춘 기록이 없는데 사람이 **직접** 이어받자고 했다 — 조용히 넘기지 않는다(`_WORTH_ASKING` 주석).

        있는 것만 말한다: ① 더 오래된 한도 멈춤이 있으면 그것 ② 없으면 「한도로 멈춘 기록은 없다」고 밝히고 가장 최근에 하던 대화
        ③ 기록이 아예 없으면 그렇다고. 평소 대화(문을 못 넘는 말)는 모델을 한 번도 안 부르고 None 이다.
        """
        if not worth_asking(prompt):
            return None
        label = parse_label(self.ask(INTENT_SYSTEM, intent_prompt(prompt)), "intent", {"takeover", "not", "unclear"}, "not")
        self.publish("takeover_intent", {"label": label, "tool": named_tool(prompt), "recent": False, "stop_found": False})
        if label != "takeover":
            return None
        now = self.clock()
        wanted = named_tool(prompt)
        # ★ 창은 **마지막 활동**으로 잰다(파일 고친 시각이 아니라). 실제 기록으로 돌리자 12일 전에 멈춘 대화가 골라졌다 —
        #   파일은 이틀 안에 건드려졌지만 멈춘 것은 18,323분 전이었다(2026-10-06 운영 PC).
        found = [s for s in self.sessions(window_sec=NO_STOP_LOOKBACK_SEC)
                 if now - s.last_activity <= NO_STOP_LOOKBACK_SEC
                 and not (s.stop_kind == "rate_limit" and self._already_handled(self._stop_key(s)))]
        if not found:
            return {"answer": NO_RECORDS_ANSWER, "kind": "no_records"}
        # 말한 도구 → 한도로 멈춘 것 → 실제로 일을 한 대화 → 최근 순.
        found.sort(key=lambda s: (bool(wanted) and s.tool != wanted, s.stop_kind != "rate_limit",
                                  not is_substantive(s), -s.last_activity))
        top = found[0]
        # 「코덱스」라고 했는데 코덱스 기록이 없으면 말없이 다른 도구의 대화를 내밀지 않는다 — 없다고 먼저 말한다.
        missing = (f"최근 이틀 안의 {TOOL_NAMES.get(wanted, wanted)} 대화 기록은 찾지 못했습니다.\n"
                   if wanted and top.tool != wanted else "")
        card = self._card_for_stop(top, now)
        takeover_id = self._record(top, card, chat_session, status="offered")
        self.publish("takeover_offered", {"takeover_id": takeover_id, "card": card, "other_count": max(0, len(found) - 1)})
        if top.stop_kind == "rate_limit":
            answer = self._offer_line(card) if capsule_visible else self._offer_text(card, others=len(found) - 1)
        elif capsule_visible:
            answer = (f"최근 3시간 안에 사용량 한도로 멈춘 기록은 찾지 못했습니다. 가장 최근에 쓰던 {card['tool_name']} 대화는 "
                      f"「{card['title']}」({self._ago(card)})입니다. 이 대화를 이어받으려면 오른쪽에서 방법을 "
                      "고르시거나 「응」이라고 답해 주세요.")
        else:
            answer = self._offer_text(card, others=len(found) - 1, stop_found=False)
        return {"answer": missing + answer, "takeover_id": takeover_id, "kind": "offer", "card": card}

    @staticmethod
    def _ago(card: dict[str, Any]) -> str:
        """오래된 것은 시간으로 — 물어서 찾은 대화는 이틀 전 것일 수 있고, 「2880분 전」은 읽을 수 없다."""
        minutes = int(card.get("stopped_minutes_ago") or 0)
        return f"{minutes}분 전" if minutes < 120 else f"{round(minutes / 60)}시간 전"

    def _offer_line(self, card: dict[str, Any]) -> str:
        return (f"{card['tool_name']} 의 「{card['title']}」 대화가 {self._ago(card)} "
                f"{_stop_phrase(card.get('stop_kind'))}. 오른쪽에서 이어갈 방법을 고르시거나 「응」이라고 답해 주세요.")

    def _card_for_stop(self, stop: SessionState, now: float) -> dict[str, Any]:
        source = pick_resume_source(stop, self.sessions(window_sec=48 * 3600))
        card = build_card(source, git_state(source.cwd, self.run), now=now)
        # 멈춤의 증거는 멈춘 대화에서 — 내용만 앞의 작업 대화에서 왔다.
        card["stop_kind"] = stop.stop_kind
        card["stopped_minutes_ago"] = max(0, int((now - stop.last_activity) // 60))
        card["resets_at"] = stop.resets_at or card.get("resets_at")
        card["stop_message"] = _clean(stop.stop_message, 200)
        card["resumed_from_earlier_session"] = source is not stop
        return card

    def _hint(self, card: dict[str, Any]) -> str:
        return (f"\n\n참고: {card['tool_name']} 의 「{card['title']}」 대화가 "
                f"{self._ago(card)} {_stop_phrase(card.get('stop_kind'))}. 이어받기를 원하시면 "
                "「이어서 해줘」라고 말씀해 주세요.")

    def _offer_text(self, card: dict[str, Any], *, others: int, stop_found: bool = True) -> str:
        where = card["git"].get("root") or card["cwd"]
        lead = (f"{card['tool_name']} 의 「{card['title']}」 대화가 {self._ago(card)} {_stop_phrase(card.get('stop_kind'))}."
                if stop_found else
                f"최근 3시간 안에 사용량 한도로 멈춘 기록은 찾지 못했습니다. 가장 최근에 쓰던 {card['tool_name']} 대화는 "
                f"「{card['title']}」({self._ago(card)})입니다.")
        lines = [
            lead,
            f"- 작업 폴더: {where}",
            f"- 마지막 요청: {_clean(card['last_request'], 200) if card['last_request'] else '(기록에 없음)'}",
        ]
        if card["open_tasks"]:
            lines.append(f"- 남은 할 일(기록 기준): {', '.join(card['open_tasks'][:3])}")
        if card["git"].get("repo"):
            lines.append(f"- 바뀌어 있는 파일: {card['git']['changed_count']}개")
        if others > 0 and stop_found:
            lines.append(f"(최근에 멈춘 대화가 {others}개 더 있습니다. 화면에서 고를 수 있습니다.)")
        # ★ 말로 하는 자리에서는 **가지를 약속하지 않는다** (2026-09-20).
        #
        #   「응」 한 마디에 git 가지와 잡이 생기면 그건 사람이 **보고 고른 것이 아니다.**
        #   진짜 이어 작업은 화면 캡슐의 단추가 연다 — 거기서는 무엇이 벌어질지 보인다.
        lines.append("\n이어갈까요? 원래 대화와 작업 폴더는 건드리지 않고, "
                     "이어서 할 일을 정리한 지시문을 만들어 드리겠습니다.")
        # 화면 캡슐에 「코드로 이어받기」 단추가 따로 있다. 말로 하는 자리에서는 그 말을
        # 꺼내지 않는다 — 여기서 약속할 수 있는 것은 인계문까지다.
        return "\n".join(lines)

    # ---- 받아들이기 · 이어 작업 ------------------------------------------
    def accept(self, takeover_id: int, *, via: str = "screen") -> dict[str, Any]:
        """이어받기를 받아들인다.

        `via="chat"` 이면 **가지를 파지 않고** 인계문만 준다 — 말 한마디로 git 가지와 잡이
        생기면 안 된다. 화면에서 누를 때(`via="screen"`)만 실제로 이어 작업을 시작한다.
        """
        row = self.get(takeover_id)
        if row is None:
            return {"answer": "그 이어받기 기록을 찾지 못했습니다.", "kind": "missing"}
        card = row["card"]
        if via == "chat" or not self.branch_enabled or not card["git"].get("repo") or self.submit is None:
            self._set(takeover_id, status="card_only")
            return {"answer": "이어서 할 일을 정리했습니다. 이 지시문을 한도가 풀린 도구나 다른 도구에 붙여 넣으면 됩니다.\n\n"
                              + resume_prompt(card), "takeover_id": takeover_id, "kind": "card"}
        started = self.continue_on_branch(takeover_id)
        if not started.get("ok"):
            return {"answer": f"가지를 만들지 못해 이어 작업을 시작하지 못했습니다({started.get('error')}). "
                              "대신 이어서 할 일을 정리했습니다.\n\n" + resume_prompt(card),
                    "takeover_id": takeover_id, "kind": "card"}
        return {"answer": (f"가지 `{started['branch']}` 에서 이어 작업을 시작했습니다. 원래 폴더는 그대로입니다.\n"
                           f"작업 자리: {started['worktree']}\n끝나면 검토 대기로 알려 드리겠습니다."),
                "takeover_id": takeover_id, "kind": "started", "job_id": started.get("job_id")}

    def prepare_cowork(
        self,
        takeover_id: int,
        *,
        direction: str = "continue",
        custom: str = "",
        target: str = "cowork",
    ) -> dict[str, Any]:
        """이어받은 작업을 새 판이 읽을 **인계문**으로 바꾼다.

        `target` 이 갈라 준다:

            "cowork"  대화 쪽. 저장소를 안 건드린다 — 코드 수정은 다음 계획으로만 적는다.
            "code"    ★ Code 모드. **고치라고 부른 자리**다 (2026-09-20 사장님 지시).

        ★ 왜 갈라야 하나: 예전에는 한 문장뿐이었고 거기 "코드 파일 수정과 git 가지 실행만
          직접 하지 말고" 가 들어 있었다. 그 인계문이 Code 판에도 그대로 실려서, 이어받기가
          **구조적으로 아무것도 못 고치게** 되어 있었다. 모델은 시키는 대로 따랐을 뿐이다.
          목표는 반대다 — 클로드 한도가 끝나면 온텔릭이 **이어서 진짜로 고쳐야** 한다.
        """
        row = self.get(takeover_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        instruction = handoff_instruction(direction, custom)
        if not instruction:
            return {"ok": False, "error": "invalid_direction"}
        card = row["card"]
        source = str(card.get("tool_name") or card.get("tool") or "다른 도구")
        title = _clean(str(card.get("title") or "멈춘 작업"), 80)
        prompt = (
            f"{source}에서 이어온 작업 · {title}\n\n"
            f"{resume_prompt(card, direction=direction)}\n\n"
            "[사용자가 고른 이어가기 방식]\n"
            f"{instruction}\n\n"
            # ★ 이 꼬리말이 판을 끝냈다 (2026-09-16 실측). 「실제로 수행하지 말고 … 계획까지 정리한다」가
            #   **조사 과제에까지** 걸려, 모델이 6걸음에서 「남은 작업」 목록을 쓰고 멈췄다. 코드에만 걸리는
            #   말이었는데 문장이 그렇게 안 읽혔다 — 먼저 **할 일**을 말하고, 못 하는 것만 뒤에 좁혀 적는다.
            + (
                # Code 모드 — 고치러 온 자리다. 손을 묶는 말을 쓰지 않는다.
                "너는 지금 Code 모드이고, 이 저장소의 **새 가지(worktree)** 에서 일한다. "
                "원래 폴더와 원래 가지는 그대로 있으니, 파일을 고치고 시험을 돌리는 것을 **직접 끝까지 한다** — "
                "다음에 할 일 목록으로 끝내지 않는다. 고친 뒤에는 반드시 시험을 돌려 초록불을 확인하고, "
                "무엇을 왜 고쳤는지 한 줄로 남긴다."
                if target == "code" else
                # 대화 쪽 — 저장소를 안 건드린다는 약속은 그대로 지킨다.
                "지금은 Cowork 선공개 모드다. 원래 대화와 작업 폴더를 바꾸지 말고, "
                "웹 조사·문서·표 만들기처럼 Cowork에서 할 수 있는 일은 **끝까지 해낸다** — 중간 보고로 끝내지 않는다. "
                "**코드 파일 수정과 git 가지 실행만** 직접 하지 말고, 그 자리는 다음 패치와 검증 계획으로 적는다."
            )
        )
        self._set(takeover_id, status="card_only")
        self.publish("takeover_cowork_prepared", {
            "takeover_id": takeover_id, "tool": card.get("tool"), "title": title,
        })
        return {
            "ok": True,
            "takeover_id": takeover_id,
            "tool": str(card.get("tool") or ""),
            "tool_name": source,
            "title": f"{source}에서 이어온 · {title}",
            "prompt": prompt,
            # 화면이 채팅 요청에 그대로 되실어 보낸다. 계획 층은 이 값과 사람에게 보인
            # 문장에서 요구를 뽑고, 위의 긴 인계문은 맥락으로만 읽는다(`handoff_contract`).
            "direction": direction,
        }

    def dismiss(self, takeover_id: int) -> dict[str, Any]:
        """화면에서 「지금은 안 함」을 고른 제안을 다시 붙잡지 않는다."""
        row = self.get(takeover_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        if row.get("status") == "offered":
            self._set(takeover_id, status="dismissed")
        self.publish("takeover_dismissed", {"takeover_id": takeover_id})
        return {"ok": True, "takeover_id": takeover_id}

    def continue_on_branch(self, takeover_id: int) -> dict[str, Any]:
        row = self.get(takeover_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        card = row["card"]
        repo = str(card["git"].get("root") or "")
        if not repo:
            return {"ok": False, "error": "not_a_git_repo"}
        branch = f"jarvis/takeover-{takeover_id}-{int(self.clock())}"
        worktree = self.worktree_root / f"{takeover_id}-{int(self.clock())}"
        worktree.parent.mkdir(parents=True, exist_ok=True)
        added = _git(self.run, repo, "worktree", "add", "-b", branch, str(worktree), "HEAD", timeout=120)
        if added.returncode != 0:
            return {"ok": False, "error": "worktree_add_failed",
                    "detail": _clean(added.stderr.decode("utf-8", "replace"), 200)}
        carried = self._carry_uncommitted(repo, worktree, list(card.get("files") or []))
        base = self._commit(worktree, "이어받기 시작점: 멈춘 순간의 미커밋 변경")
        self._set(takeover_id, status="continuing", branch=branch, worktree=str(worktree), base_ref=base)
        job: dict[str, Any] = {}
        if self.submit is not None:
            # ★ 채팅 API 가 받는 값만 쓴다. `origin` 은 chat·voice·workspace 셋뿐이다 — 처음에 "takeover" 를
            #   넣었다가 실제 시험(`live_h2_test.py`)이 422 로 드러냈다. 제품은 enqueue 로 바로 넣어 검증을
            #   건너뛰므로 조용히 통과했을 것이고, 뒤쪽은 모르는 출처를 음성으로 보거나 작은 HUD 를 띄운다.
            #   뒤에서 도는 일이라 전체화면 출처(workspace)로 둔다. `speak` 는 폐기된 칸이라 안 넣는다.
            job = self.submit({
                "prompt": resume_prompt(card_for_worktree(card, worktree)),
                "session_id": f"takeover-{takeover_id}",
                "origin": "workspace",
                "workspace_mode": "code",
                "code_workspace": str(worktree),
                "open_results": False,
                "takeover_id": takeover_id,
            })
            self._set(takeover_id, job_id=str(job.get("id") or ""))
        self.publish("takeover_started", {"takeover_id": takeover_id, "branch": branch})
        return {"ok": True, "branch": branch, "worktree": str(worktree), "base": base,
                "carried": carried, "job_id": job.get("id")}

    def _carry_uncommitted(self, repo: str, worktree: Path, wanted: list[str]) -> dict[str, int]:
        """추적 파일의 변경은 전부, 추적 안 한 파일은 **대화에서 실제로 만든 것만** 옮긴다.

        ★ 추적 안 한 파일을 통째로 옮기면 출력물·로그 수천 개가 따라온다(개발 PC 8,967개).
        """
        wanted_set = {w.replace("\\", "/").lower() for w in wanted}
        diff = _git(self.run, repo, "diff", "HEAD", "--binary", timeout=60).stdout
        applied = 0
        if diff.strip():
            result = _git(self.run, str(worktree), "apply", "--whitespace=nowarn", "-", input_bytes=diff, timeout=60)
            applied = 1 if result.returncode == 0 else 0
        others = _git(self.run, repo, "ls-files", "--others", "--exclude-standard", "-z").stdout
        copied = 0
        total = 0
        candidates = [p for p in others.decode("utf-8", "replace").split("\0")
                      if p and p.replace("\\", "/").lower() in wanted_set]
        for rel in candidates[:MAX_UNTRACKED_COPY]:
            source = Path(repo) / rel
            try:
                size = source.stat().st_size
            except OSError:
                continue
            if total + size > MAX_UNTRACKED_BYTES:
                break
            target = worktree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
            total += size
        return {"diff_applied": applied, "untracked_copied": copied}

    def _commit(self, worktree: Path, message: str) -> str:
        """가지 안에서만 커밋한다. 사용자의 git 이름이 없어도 되게 이번 커밋에만 자비스 이름을 쓴다."""
        _git(self.run, str(worktree), "add", "-A", timeout=60)
        done = self.run(
            ["git", "-C", str(worktree), "-c", "user.name=Sonjari", "-c", "user.email=ontelic@localhost",
             "commit", "--allow-empty", "-m", message],
            capture_output=True, timeout=120,
        )
        if done.returncode != 0:
            return ""
        return _git(self.run, str(worktree), "rev-parse", "HEAD").stdout.decode("utf-8", "replace").strip()

    def on_job_terminal(self, job: dict[str, Any]) -> None:
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        takeover_id = payload.get("takeover_id")
        if not takeover_id:
            return
        self.finish(int(takeover_id), status=str(job.get("status") or ""),
                    answer=str(((job.get("result") or {}) if isinstance(job.get("result"), dict) else {}).get("answer") or ""))

    def finish(self, takeover_id: int, *, status: str = "", answer: str = "") -> dict[str, Any]:
        row = self.get(takeover_id)
        if row is None or not row["worktree"]:
            return {"ok": False, "error": "not_found"}
        worktree = Path(row["worktree"])
        head = self._commit(worktree, "손자리 이어 작업")
        stat = _git(self.run, str(worktree), "diff", "--stat", row["base_ref"] or "HEAD~1", "HEAD").stdout.decode(
            "utf-8", "replace") if row["base_ref"] else ""
        files = _git(self.run, str(worktree), "diff", "--name-only", row["base_ref"], "HEAD").stdout.decode(
            "utf-8", "replace").split() if row["base_ref"] else []
        result = {"job_status": status, "head": head, "changed_files": files[:60],
                  "diffstat_tail": stat.strip().splitlines()[-1] if stat.strip() else "",
                  "summary": _clean(answer, 1200)}
        self._set(takeover_id, status="review_pending", result=result)
        self.publish("takeover_review_pending", {"takeover_id": takeover_id, "branch": row["branch"]})
        return {"ok": True, **result}

    def discard(self, takeover_id: int) -> dict[str, Any]:
        """가지와 작업 자리를 지운다. 원래 폴더는 건드리지 않는다."""
        row = self.get(takeover_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        repo = str(row["card"]["git"].get("root") or "")
        if row["worktree"] and repo:
            _git(self.run, repo, "worktree", "remove", "--force", row["worktree"], timeout=120)
        if row["branch"] and repo:
            _git(self.run, repo, "branch", "-D", row["branch"])
        self._set(takeover_id, status="discarded")
        return {"ok": True}

    def review_context(self, cwd: str) -> str:
        """클로드 코드가 다시 열렸을 때(SessionStart 훅) 넣어 줄 글. 이 폴더의 검토 대기만."""
        want = os.path.normcase(os.path.abspath(cwd)) if cwd else ""
        rows = [r for r in self.list(status="review_pending")["items"]
                if want and os.path.normcase(os.path.abspath(r["card"]["git"].get("root") or r["cwd"] or "")) == want]
        if not rows:
            return ""
        parts = ["손자리가 사용량 한도 동안 이 저장소의 작업을 이어서 했습니다. 먼저 사용자에게 알리고, "
                 "검토할지 물은 뒤 검토하세요. 자동으로 병합하지 마세요."]
        for r in rows[:3]:
            res = r["result"]
            parts.append(f"- 가지 `{r['branch']}` (작업 자리 {r['worktree']}): 바뀐 파일 {len(res.get('changed_files') or [])}개"
                         f" · {res.get('diffstat_tail') or ''}\n  손자리 요약: {res.get('summary') or '(없음)'}\n"
                         f"  검토: git diff {r['base_ref'][:12]}..{r['branch']}")
        return "\n".join(parts)

    # ---- 도구 등록 ----------------------------------------------------------
    def register(self, gateway: Any) -> None:
        """둘 다 L0 — 기록을 읽을 뿐 아무것도 안 바꾼다. MCP 로도 그대로 나간다(클로드가 자비스에게 물을 수 있다).

        ★ 가지를 만들고 이어 작업을 **시작하는** 것은 도구로 안 준다. 사람이 대화에서 「응」이라고 하거나
          화면 버튼을 눌러야 시작한다 — 반자동의 뜻이 그것이다.
        """
        from .tool_gateway import RiskLevel, ToolSpec

        gateway.register(ToolSpec(
            name="takeover_find",
            description=("클로드 코드·코덱스가 사용량 한도로 멈춘 최근 대화를 이 PC 기록에서 찾는다. "
                         "대화마다 작업 폴더·마지막 요청·남은 할 일·바뀐 파일을 준다."),
            parameters={"type": "object", "properties": {
                "hours": {"type": "number", "description": "몇 시간 안의 대화까지 볼지(기본 12)"}}, "required": []},
            risk_level=RiskLevel.L0,
            handler=lambda arguments=None: {"ok": True, **self.scan(hours=float((arguments or {}).get("hours") or 12))},
            enabled=self.enabled,
        ))
        gateway.register(ToolSpec(
            name="takeover_resume_prompt",
            description="takeover_find 가 준 session_path 의 대화를 이어서 할 지시문을 만든다(기록에 있는 사실만).",
            parameters={"type": "object", "properties": {"session_path": {"type": "string"}},
                        "required": ["session_path"]},
            risk_level=RiskLevel.L0,
            handler=self._tool_resume_prompt,
            enabled=self.enabled,
        ))

    def _tool_resume_prompt(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        wanted = str((arguments or {}).get("session_path") or "")
        now = self.clock()
        for state in self.sessions(window_sec=7 * 24 * 3600, fresh=True):
            if os.path.normcase(state.path) == os.path.normcase(wanted):
                card = build_card(state, git_state(state.cwd, self.run), now=now)
                return {"ok": True, "card": card, "resume_prompt": resume_prompt(card)}
        return {"ok": False, "error": "그 경로의 대화를 최근 7일 기록에서 찾지 못했다. takeover_find 로 경로를 확인할 것."}

    # ---- 기록 --------------------------------------------------------------
    def _already_handled(self, stop_key: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM takeovers WHERE stop_key = ?", (stop_key,)).fetchone() is not None

    def _record(self, state: SessionState, card: dict[str, Any], chat_session: str, *, status: str) -> int:
        now = self.clock()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO takeovers (stop_key, tool, session_path, cwd, card_json, status, chat_session,
                   created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   -- ★ **카드도 새로 쓴다** (2026-09-21 실전).
                   --
                   --   예전엔 status·chat_session·updated_at 만 고쳤다. 그래서 git 조회가
                   --   한 번 실패해 `{"repo": false}` 가 박히자, 원인을 고치고 다시 골라도
                   --   저장된 카드는 그대로였다 — **사람에게 고칠 방법이 없었다.**
                   --
                   --   카드는 「무엇을 하던 중이었나」다. 다시 고른다는 것은 「지금 다시
                   --   보라」는 뜻이므로, 그때 본 것으로 갈아 끼우는 것이 맞다.
                   ON CONFLICT(stop_key) DO UPDATE SET status = excluded.status,
                   card_json = excluded.card_json,
                   chat_session = excluded.chat_session, updated_at = excluded.updated_at""",
                (self._stop_key(state), state.tool, state.path, state.cwd,
                 json.dumps(card, ensure_ascii=False), status, chat_session, now, now),
            )
            row = conn.execute("SELECT id FROM takeovers WHERE stop_key = ?", (self._stop_key(state),)).fetchone()
        return int(row["id"])

    def record_card(self, session_path: str, chat_session: str = "") -> dict[str, Any]:
        """화면·MCP 가 고른 대화로 직접 기록을 만든다(대화 없이 버튼으로 이어받을 때)."""
        now = self.clock()
        for state in self.sessions(window_sec=7 * 24 * 3600, fresh=True):
            if os.path.normcase(state.path) == os.path.normcase(session_path):
                card = build_card(state, git_state(state.cwd, self.run), now=now)
                return {"ok": True, "takeover_id": self._record(state, card, chat_session, status="offered"),
                        "card": card}
        return {"ok": False, "error": "session_not_found"}

    def _open_offer(self, chat_session: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM takeovers WHERE status = 'offered' AND chat_session = ? AND updated_at >= ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (chat_session, self.clock() - OFFER_WINDOW_SEC),
            ).fetchone()
        return dict(row) if row else None

    def _set(self, takeover_id: int, *, result: dict[str, Any] | None = None, **fields: Any) -> None:
        if result is not None:
            fields["result_json"] = json.dumps(result, ensure_ascii=False)
        fields["updated_at"] = self.clock()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._connect() as conn:
            conn.execute(f"UPDATE takeovers SET {cols} WHERE id = ?", (*fields.values(), takeover_id))

    def get(self, takeover_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM takeovers WHERE id = ?", (takeover_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["card"] = json.loads(item.pop("card_json") or "{}")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    def list(self, *, status: str = "") -> dict[str, Any]:
        with self._connect() as conn:
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM takeovers WHERE (? = '' OR status = ?) ORDER BY updated_at DESC LIMIT 100",
                (status, status))]
        items = [self.get(int(i)) for i in ids]
        return {"items": [i for i in items if i]}


__all__ = [
    "SessionState", "TakeoverService", "build_card", "evidence_line", "git_state", "intent_prompt",
    "parse_label", "read_claude_session", "read_codex_session", "recent_sessions", "resume_prompt",
    "INTENT_SYSTEM", "OFFER_SYSTEM",
]
