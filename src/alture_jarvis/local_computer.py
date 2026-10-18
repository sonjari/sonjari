from __future__ import annotations

import contextlib
import ctypes
import fnmatch
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
from collections import deque
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable, Iterator

from .brand import documents_product_dir
from .config import JarvisConfig
from .grounding_scout import find_anchor as scout_find_anchor
from .code_index import CodeIndex
from .document_reader import DocumentReader, PLAIN_TEXT_EXTENSIONS, SUPPORTED_EXTENSIONS
from .documents import _UNVERIFIED_CELL, WRITABLE, edit_document, edit_spreadsheet, write_document
from .readback import readback_report
from . import project_env
from .known_secrets import count_secret_looking
from .models import RiskLevel
from .proof import ProofSpec, same_fingerprint
from .tool_gateway import InverseSpec, ToolGateway, ToolSpec


# 코드·텍스트를 훑을 때 한 파일에서 가져오는 기본 분량.
#
# 컨텍스트가 24,576 토큰이라는 사실에서 나온 숫자다. 여기가 40,000자였을 때는
# 한 파일이 창을 통째로 먹어서 두 번째 파일을 읽을 수가 없었고, 그래서 모델은
# 아예 안 읽고 파일 이름으로 추측했다. 6,000자면 대여섯 개를 견줄 수 있다.
# 모자라면 `truncated: true` 를 보고 max_chars 를 키워 다시 부르면 된다.
SURVEY_READ_CHARS = 15_000

# 되짚기에 실어 보내는 줄 수 상한. 한 화면에서 눈으로 좇을 수 있는 만큼이면 된다.
EDIT_PREVIEW_LINES = 40

# 목록 한 번에 돌려주는 항목 수의 기본값.
#
# ★ 이 숫자는 컨텍스트 예산이다. 100개였을 때 큰 작업 폴더 목록 하나가
# 직렬화 15,936자였고(24,576 토큰 창의 절반 이상), 파일 두 개를 읽자 창이 넘쳐
# **답변이 11자에서 잘려 나왔다.** 읽기를 싸게 만들었더니 목록이 병목이 된 것이다.
# 40개면 3천자 남짓이라 목록 두 번 + 파일 서너 개가 함께 들어간다.
# 더 필요하면 max_items 를 키우거나 pattern 으로 좁히면 된다 — 잘린 사실은
# 결과에 실어 보낸다.
LISTING_DEFAULT_ITEMS = 80

SKIP_DIRECTORIES = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "browser-profile",
}
SENSITIVE_PARTS = {
    ".ssh",
    ".gnupg",
    "credentials",
    "secrets",
    # ★ 2026-09-20: 읽기를 사용자 폴더 전체로 넓히면서 **같이 넓힌다.** 다른 AI 도구의 기록과 브라우저
    #   프로필에는 대화 원문·쿠키·토큰이 그대로 들어 있다. 여기 걸리는 자리는 **승인으로도 못 연다**
    #   (`local_request_path_access` 가 먼저 거절한다) — 사람이 실수로 눌러도 토큰은 안 나간다.
    ".claude",
    ".codex",
    ".aws",
    ".azure",
    ".kube",
    ".docker",
    "browser-profile",
    "user data",
}
SENSITIVE_NAME_FRAGMENTS = (
    "client_secret",
    "login data",
    "cookies.sqlite",
    "secret",
    "credential",
    "_token",
    "token_",
    "control.token",
    "token.dpapi",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".p12",
    ".pfx",
)

# Code 모드의 검증기는 셸이 아니다. 프로젝트 안의 테스트 코드는 실행되므로 완전한
# 격리는 아니지만, 모델이 명령 연결자나 설치/배포/Git 변경 명령을 조립하는 길은
# 스키마와 이 이중 allowlist에서 닫는다. 실제 프로젝트 코드를 전혀 실행하지 않는
# sandbox_run만으로는 저장소 패치의 성공을 증명할 수 없었다(2026-08-26 P5).
_PROJECT_COMMANDS = frozenset({"python", "py", "node", "pytest", "npm", "pnpm", "yarn", "cargo", "git"})
#: 코드 모드 도구 설명 표(`code_runtime._QWEN_DESCRIPTIONS`)의 분류 이름 — 명령 앞에 베껴 오면 뗀다.
_DESCRIPTION_LABELS = frozenset({"tests", "test", "lint", "types", "security", "dead", "complexity", "deps", "script", "js"})
#: 이름표 **하나만** 명령으로 온 것 — 그 줄의 명령으로 돌린다 (2026-10-08, 9B · 64K 코드 사다리 6판 중 5판).
#:   설명 표가 「tests    python -m pytest -q」라고 이름을 붙였고, 9B 는 왼쪽 칸을 명령으로 읽어 `command="tests"` 를 보냈다.
#:   거절문은 「셸로 돌려라」였고 셸 실행은 검증으로 안 쳐서, 통과한 판이 `coding_verification_missing` 으로 닫혔다.
#:   설명이 붙인 이름은 그 명령이다. 풀어 준 뒤에도 아래 관문(허용 프로그램·인자 검사)은 그대로 지난다.
#:   ★ `code_runtime._QWEN_DESCRIPTIONS` 의 표와 짝이다 — 한쪽만 고치면 같은 버그가 돌아온다(시험이 짝을 본다).
PROJECT_COMMAND_LABELS: dict[str, tuple[str, ...]] = {
    "tests": ("python", "-m", "pytest", "-q"),
    "test": ("python", "-m", "pytest", "-q"),
    "lint": ("python", "-m", "ruff", "check", "."),
    "types": ("python", "-m", "mypy", "."),
    "security": ("python", "-m", "bandit", "-r", "."),
    "dead": ("python", "-m", "vulture", "."),
    "deps": ("python", "-m", "pip_audit"),
}


def run_captured(
    executable: list[str], *, cwd: Any, env: dict[str, str], timeout_sec: float, creationflags: int = 0,
) -> tuple[int, bytes, bytes, bool]:
    """명령 하나를 돌려 (종료 값, 표준 출력, 오류 출력, 시간 제한에 걸렸나)를 준다 — **걸려도 일꾼을 붙잡지 않는다.**

    ★ 2026-10-08: `subprocess.run(timeout=…)` 은 시간 제한이 다 되면 **직접 띄운 프로세스만** 죽이고, 윈도우에서는 그 뒤
      시간 제한 없이 출력을 마저 읽는다. 가상환경의 `python.exe` 는 진짜 파이썬을 자식으로 띄우는 실행기라(PowerShell 로
      돌리면 한 겹 더), 죽지 않은 손자가 출력 통로를 쥐고 있으면 그 읽기가 영원히 안 끝난다. 실제로 모델이 돌린 무거운
      확인용 스크립트 하나에 일꾼 스레드가 14분 넘게 멈췄고(취소해도 안 풀림), 뒤의 판은 시작도 못 했다.
      시간 제한에 걸리면 **프로세스 나무 전체**를 끝내고, 남은 출력은 5초만 기다린다.

    ★ 2026-10-17 (앱 묶음 · VS Code 72b9e9c6): **명령 자체는 끝났는데 그것이 띄운 창 프로그램이 통로를 쥔 경우**도 같은 병이다.
      `code "파일"` 이 띄운 편집기(이 PC 에서는 Cursor)가 통로를 쥔 채 떠 있어 판이 15분을 매달렸다. 끝까지 다 읽어야 출력을
      주던 `communicate` 대신 **조금씩 받아 두고**, 직접 띄운 프로세스가 끝나면 3초만 더 기다린 뒤 받아 둔 만큼 돌려준다.
      통로는 억지로 닫지 않는다(윈도우에서는 다른 스레드가 읽는 통로를 닫는 일 자체가 그 읽기가 끝날 때까지 기다린다).
      띄운 프로그램은 끄지 않는다 — 사람이 쓸 창이다.
    """
    process = subprocess.Popen(
        executable, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, creationflags=creationflags,
    )
    sinks: dict[str, list[bytes]] = {"out": [], "err": []}

    def pump(pipe: Any, sink: list[bytes]) -> None:
        try:
            while True:
                chunk = pipe.read1(65536) if hasattr(pipe, "read1") else pipe.read(65536)
                if not chunk:
                    return
                sink.append(chunk)
        except (OSError, ValueError):
            return

    pumps = [threading.Thread(target=pump, args=(pipe, sink), daemon=True)
             for pipe, sink in ((process.stdout, sinks["out"]), (process.stderr, sinks["err"])) if pipe is not None]
    for thread in pumps:
        thread.start()

    def collected(wait: float) -> tuple[bytes, bytes]:
        until = time.monotonic() + max(0.0, wait)
        for thread in pumps:
            thread.join(max(0.0, until - time.monotonic()))
        return b"".join(sinks["out"]), b"".join(sinks["err"])

    # ★ 2026-10-10: 도는 중에도 「그만」을 듣는다(`stop_commands_when`). 맡긴 판이 3분짜리 시험을 돌리는 동안 사람의 요청이
    #   206초를 기다렸다 — 걸음 사이와 모델이 생각하는 도중에는 비켰지만 명령이 도는 중에는 들을 귀가 없었다.
    #   끊으면 그 명령은 버린다(다시 돌려야 한다). 그래서 귀는 비켜 줄 판에만 달린다 — 평소에는 아무도 안 묻는다.
    should_stop = getattr(_STOP, "check", None)
    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while True:
        remaining = deadline - time.monotonic()
        try:
            process.wait(timeout=max(0.05, min(remaining, _STOP_POLL_SEC)))
        except subprocess.TimeoutExpired:
            if deadline - time.monotonic() <= 0:
                kill_process_tree(process)
                stdout, stderr = collected(5)
                return 124, stdout, stderr, True
            if should_stop is not None and _asked_to_stop(should_stop):
                getattr(_STOP, "seen", {})["stopped"] = True
                kill_process_tree(process)
                stdout, stderr = collected(5)
                return STOPPED_EXIT_CODE, stdout, stderr, False
            continue
        # 직접 띄운 프로세스가 끝났다. 남은 출력은 통로가 닫히는 대로 — 손자가 쥐고 있으면 3초만 기다린다.
        stdout, stderr = collected(3)
        return int(process.returncode), stdout, stderr, False


#: 도는 명령에게 「그만」을 물어볼 것 — 스레드마다 따로 든다(판을 도는 스레드에만 달린다. 다른 요청의 명령은 안 끊긴다).
_STOP = threading.local()
#: 그만둘지 물어보는 간격(초).
_STOP_POLL_SEC = 2.0
#: 끊긴 명령의 종료 값 — 사람이 Ctrl+C 로 끊은 것과 같은 값이다.
STOPPED_EXIT_CODE = 130


@contextlib.contextmanager
def stop_commands_when(check: Callable[[], bool]) -> Iterator[Callable[[], bool]]:
    """이 안에서 도는 명령은 `check()` 가 참이 되면 끊긴다. 끊겼는지는 돌려준 함수로 묻는다.

        with stop_commands_when(store.person_is_waiting) as was_stopped:
            result = gateway.execute(...)
        if was_stopped(): ...   # 그 결과는 버린다 — 끝까지 돈 것이 아니다

    결과가 아니라 여기로 알리는 까닭: 도구 관문이 예외를 삼키고, 명령 도구마다 결과 모양이 다르다.
    """
    before = (getattr(_STOP, "check", None), getattr(_STOP, "seen", None))
    seen: dict[str, bool] = {}  # 이 블록의 것 — 블록을 나온 뒤에도 물을 수 있어야 한다
    _STOP.check, _STOP.seen = check, seen
    try:
        yield lambda: bool(seen.get("stopped"))
    finally:
        _STOP.check, _STOP.seen = before


def _asked_to_stop(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:  # noqa: BLE001 — 묻다가 틀어지면 끊지 않는다(명령은 끝까지 간다)
        return False


def kill_process_tree(process: "subprocess.Popen[bytes]") -> None:
    """띄운 프로세스와 **그 아래 전부**를 끝낸다. 윈도우는 뿌리가 살아 있을 때 나무를 훑어야 자식을 찾는다."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def project_command_label(raw: Any) -> str:
    """명령이 설명 표의 이름표 하나뿐이면 그 이름표(소문자), 아니면 빈 글자."""
    if isinstance(raw, list) and len(raw) == 1:
        raw = raw[0]
    if not isinstance(raw, str):
        return ""
    word = raw.strip().strip("[]'\"` ").lower()
    return word if word in PROJECT_COMMAND_LABELS else ""
#: Code 모드가 `python -m …` 으로 부를 수 있는 연장 (2026-09-20 확장).
#:
#: ★ 여기 적은 것은 **실제로 깔려 있어야 한다.** 오래 `ruff`·`mypy` 가 허용돼 있었는데
#:   설치가 안 돼 있었고(사장님 지적으로 발견), 모델이 부르면 `No module named ruff` 였다.
#:   갈래는 있는데 그 끝에 아무것도 없는 상태 — 막는 것보다 나쁘다.
#:   `tests/test_the_code_toolchain_is_actually_installed.py` 가 이제 그 갈림을 붙든다.
#:
#:     ruff         린트 + 포맷 (black·isort·flake8 을 대체하므로 그것들은 안 넣는다)
#:     mypy         타입 검사
#:     pyflakes     빠른 문법·미사용 검사 (ruff 가 느릴 만큼 큰 저장소용)
#:     pycodestyle  PEP8 스타일
#:     bandit       보안 린트 (하드코딩된 비밀·위험한 호출)
#:     vulture      죽은 코드
#:     radon        복잡도 — 「이 함수가 너무 크다」를 숫자로
#:     pip_audit    의존성의 알려진 취약점 (★ 바깥 DB 를 조회한다)
#:     pytest·unittest·compileall·py_compile  돌려 보는 쪽
def _with_our_python_first(environment: dict[str, str]) -> dict[str, str]:
    """PATH 맨 앞에 **온텔릭 파이썬**을 둔다 — 셸의 `python`·`pip`·도구 이름이 우리 것을 가리키게.

    ★ 2026-09-26 노트북: 셸의 `python` 이 윈도우 스토어 가짜(App Execution Alias)로 가서 「Python」 한 줄에 종료 코드 1 이었다.
      초기화한 PC 에는 파이썬이 없는 게 보통이다 — 우리 포장본에 든 파이썬을 먼저 찾게 한다.
    """
    here = Path(sys.executable).resolve().parent
    first = [str(here), str(here / "Scripts")]
    rest = environment.get("PATH") or environment.get("Path") or ""
    environment.pop("Path", None)
    environment["PATH"] = os.pathsep.join([*first, rest]) if rest else os.pathsep.join(first)
    return environment


_PYTHON_MODULES = frozenset({
    "pytest", "unittest", "compileall", "py_compile",
    "ruff", "mypy", "pyflakes", "pycodestyle",
    # ★ 타입 검사기 둘 (2026-09-21). `ruff` 는 문법·스타일이고 타입은 못 본다 —
    #   실측: `fee("10", 3)` 을 ruff 는 통과시키고 pyright 는 잡았다.
    #   mypy 와 같이 둔다: 저장소마다 설정이 있는 쪽을 쓰면 된다.
    "pyright",
    "bandit", "vulture", "radon", "pip_audit",
})
_NPM_COMMANDS = frozenset({"test", "run", "ci", "install"})
_SAFE_PACKAGE_SCRIPT = re.compile(
    r"^(?:test(?::[A-Za-z0-9_-]+)?|build(?::[A-Za-z0-9_-]+)?|lint|check|"
    r"typecheck|type-check|verify|format:check)$",
    re.IGNORECASE,
)
_CARGO_COMMANDS = frozenset({"test", "check", "clippy", "build", "fmt"})
#: 읽기 전용 git. ★ 2026-09-20 실전에서 `git remote -v` 가 막혀 한 걸음을 버렸다 —
#: 어느 저장소에서 일하는지 확인하는 것은 **읽기**이고, 깃허브 연동에도 그 값이 필요하다.
#: `blame`·`shortlog`·`describe` 도 같은 이유로 연다. `branch` 는 여기 넣지 않는다 — 이미 쓰기 쪽에
#: 있고 인자 검사를 받는다. `remote` 는 **인자에 따라 쓰기가 되므로**(`remote add`) 아래에서 따로 막는다.
_GIT_COMMANDS = frozenset({
    "status", "diff", "show", "log", "rev-parse", "ls-files",
    "remote", "blame", "shortlog", "describe",
})

#: 남길 수 있게 열어 준 것 (2026-09-01, 사용자 승인).
#:
#: 지금까지는 읽기 전용이라 **고칠 수는 있어도 남길 수가 없었다** — 바톤터치의
#: 핵심이 여기 막혀 있었다. 다만 넓게 열지 않는다: 되돌리기가 **브랜치 하나 삭제**로
#: 끝나는 범위까지만이다.
#:
#: 여기 없는 것은 전부 막힌다 — push · reset · clean · rebase · merge · cherry-pick
#: · revert · tag · remote · config · stash. 그중 하나라도 열면 되돌리기가
#: "브랜치 지우기"보다 어려워진다.
_GIT_WRITE_COMMANDS = frozenset({"add", "commit", "branch", "switch", "checkout", "worktree"})

#: 이 이름 위에서는 커밋하지 않는다. `run_project_command` 가 실행 직전에 확인한다.
_GIT_PROTECTED_BRANCHES = frozenset({"main", "master", "develop", "release"})
#: 이름으로 찾을 때 들어가지 않을 자리. 산출물·의존성에는 같은 이름의 사본이
#: 수십 개씩 있어, 안 거르면 "같은 이름이 여기 있다"가 소음이 된다.
_NAME_SEARCH_SKIP_DIRS = frozenset({
    "node_modules", ".git", ".venv", "__pycache__", "target", "dist", "build",
    "outputs", "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})

_SHELL_META = re.compile(r"[\r\n\x00]|(?:&&|\|\||[|<>])")



# 되짚어 보여 줄 재료. **되짚기지 생중계가 아니다.**
#
# 사용자 제안: "쓰는 건 토큰이 있으니 커서처럼 보여줄 수 있지 않나". 확인해 보니
# 아니었다 — Ollama 는 tool_calls 를 통째로 한 번에 준다(ollama._stream 의
# on_chunk 는 {thinking, content, tool_calls} 를 흘리는데, 파일 내용은 도구 **인자**
# 안에 있다). 그러니 지금 커서를 붙이면 실제로 안 일어나는 일을 일어나는 척하는
# 연출이 된다.
#
# 그래서 흘러오는 척하지 않고, **끝난 뒤 무엇이 바뀌었는지 되짚는다.** 그러려면
# 화면이 바뀐 자리를 알아야 하는데 지금까지 그걸 안 실어 보냈다 — 결과에는 바이트
# 수와 해시만 있었다. 사람이 볼 것이 하나도 없는 증거였다.
def _heal_old_text(text: str, old: str) -> tuple[str, str]:
    """완전일치가 안 될 때 **한 칸씩 내려가** 실제 원문 조각을 찾는다.

    돌려주는 것은 `(파일에 글자 그대로 있는 조각, 어느 칸에서 찾았나)`.
    못 찾으면 `("", "")` — 그러면 부르는 쪽이 예전처럼 실패한다.

    ## 왜 이만큼만 하나 (2026-09-05 실측)

    `local_apply_edit` 은 최근 2,500 판에서 **195 번 중 108 번 실패**했고, 그중
    107 건이 `old_text_not_found` 였다. 실패 직후 패턴 1 위는 「다시 읽고 · 또
    고치고 · 또 고치고」다 — 눈 감고 되풀이하는 것이다.

    그래서 치유 사다리를 재 봤다. 실패한 107 건을 지금 파일과 맞춰 보니:

        지금은 완전일치 (그때 파일에 없었던 것)   33 (58%)   ← 매칭 문제가 아니다
        줄끝 공백·들여쓰기만 다름                  1
        90% 이상 비슷                              5
        진짜로 없음                               15

    **퍼지 치유는 10% 밖에 못 건진다.** 그래서 자동으로 고치는 칸은 **되돌릴
    걱정이 없는 것만** 둔다 — 줄바꿈 방식과 줄 끝 공백. 이 둘은 들여쓰기를 안
    건드리므로 `new` 를 그대로 끼워 넣어도 안전하다.

    들여쓰기가 다르거나 어렴풋이 비슷한 것은 **고치지 않고 알려만 준다**
    (`_old_text_not_found_message`). 들여쓰기를 짐작해서 고치면 파이썬에서는
    그게 곧 다른 코드다 — 이 저장소가 여러 번 배운 「모르면 안전쪽」이다.

    각 칸은 **후보가 정확히 하나일 때만** 성립한다. 둘이면 어느 쪽인지 모르는
    것이고, 모르는 채로 고치는 것이 못 고치는 것보다 나쁘다.
    """
    if not old or not text:
        return "", ""
    # ① 줄바꿈 방식만 다르다. 파일이 CRLF 인데 모델이 LF 로 적어 온 경우가 흔하다.
    for newline in ("\r\n", "\r"):
        if newline in text:
            candidate = old.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
            if text.count(candidate) == 1:
                return candidate, "line_endings"
    # ② 줄 끝 공백만 다르다. 줄 수가 같은 창을 훑어 **하나뿐일 때만** 받아들인다.
    lines = text.split("\n")
    old_lines = [line.rstrip() for line in old.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    span = len(old_lines)
    if span > len(lines):
        return "", ""
    hits = [
        index
        for index in range(len(lines) - span + 1)
        if [line.rstrip() for line in lines[index : index + span]] == old_lines
    ]
    if len(hits) == 1:
        exact = "\n".join(lines[hits[0] : hits[0] + span])
        if text.count(exact) == 1:
            return exact, "trailing_whitespace"
    return "", ""


def _unescape_quotes(value: str) -> str:
    """`\\"` → `"` , `\\'` → `'` (백슬래시 하나짜리만)."""
    return value.replace('\\"', '"').replace("\\'", "'")


def _match_ignoring_indentation(text: str, old: str) -> str:
    """들여쓰기·줄 끝 공백·**빈 줄 수**를 무시하고 `old` 와 같은 줄 묶음을 찾아, 파일에 글자 그대로 있는 조각을 돌려준다.

    후보가 **정확히 하나일 때만** 돌려준다. 못 찾거나 둘 이상이면 빈 글자.
    """
    want = [line.strip() for line in old.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if not want:
        return ""
    lines = text.split("\n")
    have = [(index, line.strip()) for index, line in enumerate(lines) if line.strip()]
    hits: list[tuple[int, int]] = []
    for start in range(len(have) - len(want) + 1):
        if [stripped for _index, stripped in have[start : start + len(want)]] == want:
            hits.append((have[start][0], have[start + len(want) - 1][0]))
    if len(hits) != 1:
        return ""
    first, last = hits[0]
    starts: list[int] = []
    position = 0
    for line in lines:
        starts.append(position)
        position += len(line) + 1
    # 조각은 **첫 줄의 첫 글자**에서 시작한다 — 첫 줄의 들여쓰기는 항상 파일의 것이 남는다.
    # 끝은 마지막 줄의 `\r` 앞이다(CRLF 파일에서 줄바꿈 반쪽을 안 먹게).
    begin = starts[first] + (len(lines[first]) - len(lines[first].lstrip()))
    end = starts[last] + len(lines[last].rstrip("\r"))
    span = text[begin:end]
    return span if span and text.count(span) == 1 else ""


def _indentation_is_plausible(span: str, new: str) -> bool:
    """파일 조각은 들여쓰기가 있는데 `new` 는 **여러 줄이 전부 들여쓰기 없이** 왔으면 파이썬이 깨질 모양이다 — 구제하지 않는다."""

    def indented(lines: list[str]) -> bool:
        return any(line[:1] in (" ", "\t") for line in lines if line.strip())

    new_lines = [line for line in new.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if len(new_lines) >= 2 and indented(span.split("\n")) and not indented(new_lines):
        return False
    return True


def _leading_whitespace(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _reindent_flat_with_added_lines(
    file_lines: list[str], old_lines: list[str], new_lines: list[str], new_at: list[int]
) -> "str | None":
    """`old`·`new` 를 **똑같이 평평하게**(들여쓰기 전부 뺌) 보냈는데 `new` 에 줄이 **더 있거나 적을 때.**

    ★ 2026-09-28 헤르메스 대결 T7 O2·O3: `new` 앞에 `import math` 와 빈 줄을 더 넣었다. 줄 수가 달라 위 구제가 포기했고,
    도구는 「100% 비슷」이라 말하고도 거절 → 모델 왕복 한 번 더(O1~O3 세 판 모두 첫 편집이 실패했다).

    짐작하지 않는 칸만 받는다:
      · 짝이 있는 줄(같거나 1:1 로 바뀐 줄) — 파일의 들여쓰기 그대로.
      · 끼운 줄 — 첫 짝 줄 **앞**이면 그 짝 줄의 들여쓰기, `:` 로 여는 줄 **바로 뒤**면 다음 짝 줄의 들여쓰기,
        앞뒤 짝 줄의 들여쓰기가 **같으면** 그 들여쓰기. 끼운 줄이 `:` 로 블록을 열거나, 마지막 짝 줄 뒤거나,
        앞뒤가 다르면 **포기**(속 깊이를 모른다 — 틀리면 문법은 맞는 다른 코드가 된다).
    """
    import difflib

    flat = {_leading_whitespace(line) for line in old_lines} | {_leading_whitespace(new_lines[i]) for i in new_at}
    if len(flat) != 1:
        return None  # 모델이 들여쓰기를 일부라도 줬다 — 뜻이 있다
    if all(_leading_whitespace(f) == next(iter(flat)) for f in file_lines):
        return None  # 고칠 게 없다
    old_keys = [line.strip() for line in old_lines]
    new_keys = [new_lines[i].strip() for i in new_at]
    indent: dict[int, str] = {}          # new_at 순번 → 들여쓰기
    for tag, o1, o2, n1, n2 in difflib.SequenceMatcher(a=old_keys, b=new_keys, autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "replace" and o2 - o1 == n2 - n1):
            for step in range(n2 - n1):
                indent[n1 + step] = _leading_whitespace(file_lines[o1 + step])
    if not indent:
        return None
    mapped = sorted(indent)
    for order in range(len(new_keys)):
        if order in indent:
            continue
        if new_keys[order].endswith(":"):
            return None
        before = [m for m in mapped if m < order]
        after = [m for m in mapped if m > order]
        if not after:
            return None
        if not before:
            indent[order] = indent[after[0]]
        elif new_keys[before[-1]].endswith(":") or indent[before[-1]] == indent[after[0]]:
            indent[order] = indent[after[0]]
        else:
            return None
    fixed = list(new_lines)
    for order, index in enumerate(new_at):
        fixed[index] = indent[order] + new_lines[index].lstrip(" \t")
    # 조각의 첫 줄 앞 공백은 파일에 이미 있다 — **첫 짝 줄 앞에 끼운 줄**이 있으면 그 줄들도 같은 자리에서 시작한다.
    first = new_at[0]
    fixed[first] = fixed[first].lstrip(" \t")
    return "\n".join(fixed)


def _reindent_like_file(text: str, span: str, old: str, new: str) -> "str | None":
    """`old` 와 `new` 가 **똑같이** 들여쓰기를 잃었으면, 파일에 실제로 있는 들여쓰기로 `new` 를 되살린다.

    ## 왜 (2026-09-22, 노트북 4B `fin3` 실측)

    이름만 바꾸는 편집에서 4B 는 `old` 와 `new` 둘 다 둘째 줄부터 들여쓰기를 뺐다
    (`def get_user(user_id):` 다음 줄 `return USERS.get(user_id)` 의 앞 공백이 없다). 도구는 「유사도 100%」라고 말하고도
    거절했다. 안전장치(`_indentation_is_plausible`)가 「`new` 가 전부 들여쓰기 없이 왔으니 파이썬이 깨진다」고 본 것이라
    설계대로지만, 이 모양은 **더 안전하게** 구제할 수 있다 — 모델이 들여쓰기를 바꾸려던 것이 아니기 때문이다.

    ## 짐작이 아닌 이유

    다음이 **모두** 참일 때만 한다:
      · 줄 수가 셋 다 같다(파일 조각 · `old` · `new` — 비어 있지 않은 줄 기준). 구조를 바꾸는 편집은 안 건드린다.
      · 줄마다 `new` 의 들여쓰기가 `old` 의 것과 **같다** — 모델 스스로 들여쓰기를 바꿀 뜻이 없었다는 증거다.
      · 파일의 들여쓰기가 `old` 와 **다르다** — 고칠 것이 있다.
    그러면 각 줄의 들여쓰기는 **파일의 것**을 그대로 쓴다. 우리가 만드는 값이 없다. 아니면 `None` (예전 경로로 간다).
    """
    start = text.find(span)
    if start < 0:
        return None
    line_start = text.rfind("\n", 0, start) + 1
    file_lines = [line.rstrip("\r") for line in text[line_start : start + len(span)].split("\n") if line.strip()]
    old_lines = [
        line.rstrip("\r") for line in old.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()
    ]
    new_lines = new.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    new_at = [index for index, line in enumerate(new_lines) if line.strip()]
    if len(file_lines) != len(old_lines):
        return None
    if len(old_lines) != len(new_at):
        return _reindent_flat_with_added_lines(file_lines, old_lines, new_lines, new_at)
    if any(_leading_whitespace(o) != _leading_whitespace(new_lines[i]) for o, i in zip(old_lines, new_at)):
        return None  # 모델이 들여쓰기를 바꾸려던 것이다 — 우리가 짐작하지 않는다
    if all(_leading_whitespace(o) == _leading_whitespace(f) for o, f in zip(old_lines, file_lines)):
        return None  # 고칠 게 없다
    fixed = list(new_lines)
    for order, index in enumerate(new_at):
        fixed[index] = _leading_whitespace(file_lines[order]) + new_lines[index].lstrip(" \t")
    # 조각이 첫 글자에서 시작하니 첫 줄의 앞 공백은 뗀다 — 파일의 원래 들여쓰기가 이미 조각 앞에 있다.
    fixed[new_at[0]] = fixed[new_at[0]].lstrip(" \t")
    return "\n".join(fixed)


def _rescue_edit(text: str, old: str, new: str) -> tuple[str, str, str]:
    """`_heal_old_text` 가 못 고친 **작은 모델의 흔한 글자 어긋남 둘**을 구제한다. `(파일 조각, 넣을 new, 이름)`.

    ## 왜 (2026-09-22, 노트북 4B 사다리 `fin2` 실측)

    편집 56 번 중 12 번(21%)이 `old_text_not_found` 였고, 그것 때문에 진 작업이 둘이었다(L5 1회차·L4 3회차).
    어긋난 모양을 보니 둘이다 — 유사도 95% 이상 4 번이 이것이다:

        · **들여쓰기를 빼먹었다**  (`def f():\\nreturn 1` — 둘째 줄 들여쓰기가 없다. 도구는 「100% 비슷」이라고 말하고도 거절했다)
        · **따옴표를 이중으로 이스케이프했다**  (`\\"\\"\\"` — 인자를 만들 때 백슬래시가 한 겹 더 붙었다)

    ## 왜 이전 결정(들여쓰기는 안 고친다)과 안 부딪히나

    앞 결정의 이유는 「들여쓰기를 **짐작해서** 고치면 파이썬에서는 그게 곧 다른 코드」였다. 여기서는 짐작하지 않는다:
    바꾸는 자리를 **`old` 로 찾는 기준만** 느슨하게 하고, 후보가 **정확히 하나일 때만** 받아들이며,
    **`new` 는 모델이 쓴 그대로** 넣는다(들여쓰기를 우리가 만들지 않는다). `new` 가 여러 줄인데 전부 들여쓰기가 없으면
    (파이썬이 깨질 모양) 구제하지 않는다. 그 밖에 72~90% 비슷한 것(모델이 파일 내용을 실제로 잘못 기억한 것)은 그대로 실패한다.
    """
    if not old.strip() or not text:
        return "", "", ""
    unescaped_old = _unescape_quotes(old)
    escaped = unescaped_old != old
    attempts: list[tuple[str, str, str, bool]] = []
    if escaped:
        # 이스케이프만 다른 경우 — 풀었더니 글자 그대로 한 곳에 있다. new 도 같은 방식으로 푼다.
        attempts.append((unescaped_old, _unescape_quotes(new), "escaped_quotes", True))
    attempts.append((unescaped_old if escaped else old, _unescape_quotes(new) if escaped else new, "indentation", False))
    def in_file_newlines(value: str) -> str:
        # 파일이 CRLF 면 넣을 글자도 CRLF 로 — 한 파일에 줄바꿈 방식이 섞이지 않게(윈도우에서 흔하다).
        return value.replace("\r\n", "\n").replace("\n", "\r\n") if "\r\n" in text else value

    for candidate_old, candidate_new, kind, literal in attempts:
        if literal:
            # 풀었더니 글자 그대로(줄바꿈 방식·줄 끝 공백 차이까지 앞 단계와 같은 규칙으로) 한 곳에 있다.
            if text.count(candidate_old) == 1:
                return candidate_old, in_file_newlines(candidate_new), kind
            healed, _how = _heal_old_text(text, candidate_old)
            if healed and text.count(healed) == 1:
                return healed, in_file_newlines(candidate_new), kind
            continue
        span = _match_ignoring_indentation(text, candidate_old)
        if span:
            reindented = _reindent_like_file(text, span, candidate_old, candidate_new)
            if reindented is not None:
                return span, in_file_newlines(reindented), "indentation_from_file"
        if span and _indentation_is_plausible(span, candidate_new):
            # 조각이 첫 글자에서 시작하니, `new` 첫 줄의 앞 공백은 뗀다 — 파일의 원래 들여쓰기가 이미 앞에 있다.
            first_line_fixed = candidate_new.lstrip(" \t")
            return span, in_file_newlines(first_line_fixed), ("escaped_quotes+indentation" if escaped else kind)
    return "", "", ""


#: 못 찾았을 때 **어디가 가까운지** 알려 줄 때의 최소 닮음. 이보다 멀면 말해도 헷갈린다.
_NEAR_MISS_RATIO = 0.6


def _old_text_not_found_message(text: str, old: str) -> str:
    """「없다」로 끝내지 않고 **가장 가까운 자리**를 짚어 준다.

    예전 문구는 `old_text_not_found` 여섯 글자였다. 실측에서 모델은 그걸 받고
    다시 읽고 또 같은 편집을 시도하기를 되풀이했다(실패 직후 3 걸음 패턴 1 위).
    어디가 어긋났는지 모르니 눈 감고 되풀이할 수밖에 없다.

    고치지는 않는다 — 짐작으로 고치면 안 되는 자리다. **보여만 준다.**
    """
    import difflib

    base = "old_text_not_found"
    normalized = old.replace("\r\n", "\n").replace("\r", "\n")
    old_lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not old_lines:
        return base
    lines = text.split("\n")
    stripped = [line.strip() for line in lines]
    span = max(1, len(old_lines))
    target = "\n".join(old_lines)
    best_ratio, best_at = 0.0, -1
    for index in range(max(1, len(lines) - span + 1)):
        window = "\n".join(part for part in stripped[index : index + span] if part)
        if not window:
            continue
        ratio = difflib.SequenceMatcher(None, target, window).ratio()
        if ratio > best_ratio:
            best_ratio, best_at = ratio, index
    if best_at < 0 or best_ratio < _NEAR_MISS_RATIO:
        return (
            f"{base} — 그 글자가 파일에 없다. 비슷한 자리도 못 찾았다. "
            "local_read_text_file 로 **고칠 곳을 다시 읽고** 원문을 그대로 복사해 와라. "
            "기억이나 짐작으로 old 를 적지 마라."
        )
    where = best_at + 1
    sample = "\n".join(lines[best_at : best_at + min(span, 6)])
    return (
        f"{base} — 그 글자는 없지만 **{where}번째 줄쯤이 {int(best_ratio * 100)}% 비슷하다.** "
        f"거기 실제 원문은 이렇다:\n{sample[:600]}\n"
        "이 원문을 **그대로 복사해서** old 에 넣어라(들여쓰기·공백까지). "
        "다시 읽을 필요 없이 위 글자를 쓰면 된다."
    )


#: 지워도 다시 생기는 캐시 폴더 — 원래 있던 것이어도 잃을 것이 없다. `node_modules`·`.venv`·`dist` 는 넣지 않는다
#: (다시 받는 데 시간이 들거나, 사람이 넣어 둔 산출물일 수 있다 — 그런 것은 이 판이 만들었을 때만 지운다).
_REGENERATED_FOLDERS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})

#: 판 시작 때 폴더를 훑을 때 **안으로 안 들어가는** 폴더(있다는 것만 적는다). 수만 개라 훑는 값이 없다.
_HEAVY_FOLDERS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "target", "Library"})
_HEAVY_FOLDERS_FOLDED = frozenset(name.casefold() for name in _HEAVY_FOLDERS)
_FOLDER_SCAN_CAP = 20_000


def _folders_under(root: Path) -> "frozenset[str] | None":
    """`root` 아래 지금 있는 폴더들(루트 기준, 소문자, `/` 구분). 너무 많아 다 못 훑으면 None — 그러면 「없던 폴더」를 증명할 수 없다."""
    found: set[str] = set()
    try:
        for folder, dirs, _files in os.walk(root):
            base = Path(folder)
            for name in list(dirs):
                found.add((base / name).relative_to(root).as_posix().casefold())
                if name in _HEAVY_FOLDERS:
                    dirs.remove(name)  # 있다는 것만 적고 안은 안 본다 — 그 안의 폴더는 「그 밑」으로 가려진다
            if len(found) > _FOLDER_SCAN_CAP:
                return None
    except OSError:
        return None
    return frozenset(found)


def _is_link(path: Path) -> bool:
    """심볼릭 링크나 윈도우 연결 폴더(junction)인가 — 지우면 가리키는 쪽이 다칠 수 있다."""
    try:
        if os.path.islink(path):
            return True
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True  # 모르면 안 지우는 쪽


def _retry_writable(function: Any, target: str, _error: Any) -> None:
    """읽기 전용 파일(윈도우의 패키지 캐시)을 풀고 한 번 더."""
    os.chmod(target, 0o700)
    function(target)


def start_preview_server(root: Path):
    """작업 폴더를 `127.0.0.1` 에만 띄운다 — **연결마다 스레드 하나** (2026-09-29).

    ★ 대표 목격: 제품 화면 칸이 흰 화면, 새로고침해도 한참 그대로. 손자리 걸음엔 「스크린샷이 타임아웃 됐습니다」.
      서버가 `socketserver.TCPServer`(한 번에 연결 하나)였다 — `daemon_threads` 는 스레드 방식이 아니면 아무 일도 안 한다.
      이 서버를 **손자리의 크롬과 앱의 제품 화면 칸이 같이** 쓰는데, 브라우저는 요청 없이 미리 열어 두는 연결을 만든다.
      서버가 그 빈 연결의 첫 줄을 기다리는 동안 다른 요청은 전부 줄을 섰다.
    - 캐시 금지: 손자리가 파일을 고친 뒤 새로고침하면 **고친 판**이 보여야 한다.
    - 요청 기록 안 남김: 포장판(pythonw)엔 stderr 가 없어 기록 한 줄이 응답을 끊을 수 있다.
    """
    import functools
    import http.server
    import threading

    base = os.path.realpath(str(root))

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path: str) -> str:
            """작업 폴더 **실제 경로** 밖이면 없는 파일로 돌린다 — 심볼릭 링크·정션을 따라 밖을 읽지 못하게.

            `../` 는 표준 처리가 막지만, 폴더 안의 링크가 밖을 가리키면 그대로 읽혔다(2026-09-29 코덱스 교차 검사 재현:
            `/linked.txt` → 200 · 본문 OUTSIDE). 링크를 풀어 본 실제 경로로 판단한다.
            """
            target = super().translate_path(path)
            real = os.path.realpath(target)
            if real != base and not real.startswith(base + os.sep):
                return os.path.join(base, ".sonjari-outside-denied")  # 없는 이름 → 404
            return target

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — 상위 서명 그대로
            return

    # ★ 127.0.0.1 만. 0.0.0.0 으로 열면 같은 망의 다른 기기가 이 폴더를 본다.
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(root))
    )
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="sonjari-preview").start()
    return server


def _edit_preview(before: str, old: str, new: str) -> dict[str, Any]:
    """바뀐 자리와 그 앞뒤. 화면이 되짚기에 쓴다."""
    at = before.find(old)
    start_line = before.count('\n', 0, at) + 1 if at >= 0 else 1
    removed = old.split('\n')
    added = new.split('\n')
    clipped = len(removed) > EDIT_PREVIEW_LINES or len(added) > EDIT_PREVIEW_LINES
    return {
        "start_line": start_line,
        "removed": removed[:EDIT_PREVIEW_LINES],
        "added": added[:EDIT_PREVIEW_LINES],
        # 잘렸으면 그렇다고 말한다 — 되짚기가 전부를 보여 준 척하면 안 된다.
        "truncated": clipped,
        "removed_count": len(removed),
        "added_count": len(added),
    }


def _looks_like_symbol(query: str) -> bool:
    """찾던 것이 파일 이름이 아니라 코드 심볼처럼 생겼는가.

    파일명 검색(`report.md`, `2026`)과 심볼 검색(`chat_messages_stream`)을 가른다.
    확장자가 붙어 있으면 파일을 찾는 것이고, 밑줄이나 대소문자 섞임이 있으면
    코드 안을 찾는 것이다. 애매하면 **참견하지 않는다** — 틀린 안내는 없는 것보다 나쁘다.
    """
    text = query.strip()
    if not text or len(text) < 4 or " " in text or "." in text or "*" in text:
        return False
    return ("_" in text and text.replace("_", "").isalnum()) or (
        text.isalnum() and not text.isdigit() and text.lower() != text
    )


def _check_git_write_args(args: list[str]) -> None:
    """쓰기 git 의 **인자**까지 본다. 이름만 보고 열면 `checkout .` 이 통과한다.

    막는 이유가 전부 같다 — **되돌리기가 브랜치 삭제보다 어려워지는 것**은 안 연다.

    - ``--force``/``-f`` : 어디에 붙든 되돌리기를 어렵게 만든다
    - ``commit --amend`` : 이미 남긴 것을 고쳐 쓴다
    - ``branch -d/-D``   : 남의 브랜치를 지운다
    - 맨 ``checkout``/``switch`` : 작업 중인 변경을 덮어쓰거나 딴 가지로 옮긴다.
      **새 가지를 만드는 것(-b / -c)만** 연다.
    """
    head, rest = args[0], args[1:]
    if any(a in {"-f", "--force"} or a.startswith("--force") for a in rest):
        raise PermissionError("git_force_not_allowed")
    if head == "commit":
        if "--amend" in rest:
            raise PermissionError("git_amend_not_allowed")
        if not any(a == "-m" or a.startswith("--message") for a in rest):
            # 메시지가 없으면 편집기가 열리고 그대로 멈춘다.
            raise PermissionError("git_commit_needs_message")
    elif head == "branch":
        if any(a in {"-d", "-D", "--delete", "-m", "-M", "--move"} for a in rest):
            raise PermissionError("git_branch_delete_or_move_not_allowed")
    elif head in {"checkout", "switch"}:
        creating = any(a in {"-b", "-c", "-B", "-C", "--create"} for a in rest)
        if not creating:
            raise PermissionError("git_switch_must_create_branch")
    elif head == "worktree":
        # ★ **컨테이너 없는 격리** (2026-09-21). 이어받기가 사람이 보던 작업 폴더를
        #   발밑에서 고치면 안 된다 — `worktree add ../옆자리 -b 가지` 하나로
        #   같은 저장소의 딴 폴더에서 딴 가지로 일할 수 있다. 이 PC 에 도커도 없다.
        #
        #   여는 것은 **만드는 것과 보는 것뿐**이다. 되돌리기가 브랜치 삭제보다
        #   어려워지는 것은 안 연다 — 이 함수의 규칙 그대로.
        sub = rest[0] if rest else ""
        if sub in {"remove", "prune", "move", "unlock"}:
            raise PermissionError(f"git_worktree_{sub}_not_allowed")
        if sub not in {"add", "list"}:
            raise PermissionError("git_worktree_only_add_or_list")
        if sub == "add" and not any(a in {"-b", "-B", "--create-branch"} for a in rest):
            # 기존 가지에 붙이면 그 가지에서 남이 일하고 있을 수 있다.
            # `switch` 를 「새 가지만」으로 막아 둔 것과 같은 이유다.
            raise PermissionError("git_worktree_add_must_create_branch")


def _unused_sibling(path: Path) -> Path:
    """`이름 (N).확장자` 중 **아직 없는 것.** 있는 이름은 절대 다시 고르지 않는다.

    ★ 2026-09-13 벤치에서 이렇게 죽었다:

        Permission denied: 여수_회계_지원_이력서_초안 (9).docx

    잠긴 파일을 비켜 가려고 `(2)`~`(9)` 를 찾는데, **상한이 9 로 박혀 있었다.**
    여덟 개가 다 차면 반복문이 끝난 자리의 `(9)` — 이미 있고, 앞 판이 워드로 띄워
    열려 있는 그 파일 — 에 그대로 썼다. 비켜 가려던 곳이 잠긴 곳이었다.
    (이 저장소 사고 Q 와 같은 모양이다: 함수 안에 박힌 상한이 제일 안 보인다.)

    그 여덟 개는 벤치가 판마다 워드를 띄워서 쌓인 것이다. 창을 안 띄우게 한 것과
    이것은 같은 고장의 두 끝이다.
    """
    for attempt in range(2, 1000):
        spare = path.with_name(f"{path.stem} ({attempt}){path.suffix}")
        if not spare.exists():
            return spare
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.stem} ({stamp}){path.suffix}")



def _decode_output(raw: "bytes | str | None") -> str:
    """자식 프로그램의 출력을 **읽을 수 있는 글자로** 돌린다 (2026-09-20 실측).

    윈도우에서 한국어 출력이 `????` 로 오는 일이 있었다. 두 코드페이지가 섞이기 때문이다:

        파이썬 자식   `PYTHONIOENCODING=utf-8` 을 주면 UTF-8 로 찍는다
        git·npm·cargo  여전히 **시스템 코드페이지(cp949)** 로 찍는다

    그래서 UTF-8 로 먼저 읽어 보고, 깨진 글자가 나오면 cp949 로 다시 읽는다. 둘 다 아니면
    UTF-8 로 읽되 깨진 자리를 표시로 남긴다 — **조용히 버리지 않는다**(잘림은 에러가 아니라
    침묵으로 오고, 그게 제일 나쁘다는 것을 이 저장소는 여러 번 배웠다).
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if text and "�" not in text:
        return text
    import locale

    for name in (locale.getpreferredencoding(False), "cp949", "cp1252"):
        if not name:
            continue
        try:
            candidate = raw.decode(name)
        except (UnicodeDecodeError, LookupError):
            continue
        if "�" not in candidate:
            return candidate
    return raw.decode("utf-8", errors="replace")

# ── 진짜 셸 (2026-09-20) ─────────────────────────────────────────────────────
#
# 커서·윈드서프·클로드 코드 셋 다 진짜 셸을 준다. 온텔릭만 허용 목록 8개로 묶여 있었고,
# 실전에서 `flake8` 을 시도하다 `project_command_not_allowed` 로 막혔다.
#
# 그들의 안전 모델은 **허용 목록이 아니라 승인**이다. 우리도 거기로 간다 — 다만 「무엇을
# 하는 명령인가」로 가른다. 보는 것은 막힘없이, 바꾸는 것은 사람 앞에서.

#: 보기만 하는 명령. 여기 있으면 승인 없이 돈다.
_SHELL_READ_ONLY = frozenset({
    "dir", "ls", "type", "cat", "tree", "where", "which", "findstr", "find",
    "get-childitem", "gci", "get-content", "gc", "select-string", "sls",
    "get-location", "pwd", "get-item", "gi", "test-path", "measure-object",
    "get-date", "hostname", "whoami", "echo", "write-output", "write-host",
    "get-command", "get-help", "get-member", "resolve-path", "split-path",
    "join-path", "compare-object", "sort-object", "select-object", "format-table",
    "get-process", "get-service", "systeminfo", "ver", "python", "py", "node",
    "npm", "pnpm", "yarn", "cargo", "git", "pytest", "ruff", "mypy",
})

#: 폴더만 옮기는 명령 — 이어 붙인 명령에서 이 조각은 판정에서 뺀다(아무것도 안 바꾼다).
_SHELL_NAVIGATION = frozenset({"cd", "chdir", "set-location", "sl", "pushd", "popd"})

#: 이 명령들은 이름만으로 **바꾸는 일**이다 — 위 목록에 있어도 인자로 갈린다.
_SHELL_MUTATING_ARGS = re.compile(
    r"(?:^|\s)(?:-o|--output|>|>>|\|\s*out-file)|"
    r"\b(?:install|uninstall|publish|push|deploy|rm|del|erase|move|mv|copy|cp|"
    r"remove-item|new-item|set-content|add-content|out-file|rename-item|"
    r"stop-process|start-process|invoke-webrequest|invoke-restmethod|curl|wget|"
    r"reset|clean|rebase|merge|revert|checkout\s+--)\b",
    re.IGNORECASE,
)

#: ★ **승인으로도, 자동 실행을 켜도 안 연다.** 전역 규칙: 보안 설정·인증서는 사람이 직접 한다.
#: PowerShell 에게 **읽을 때도 쓸 때도** UTF-8 을 쓰라고 먼저 말해 둔다 (2026-09-20 실측).
#:
#: 세 가지가 따로 논다 — 출력 인코딩(`[Console]::OutputEncoding`), 파이프 인코딩
#: (`$OutputEncoding`), 그리고 **cmdlet 이 파일을 읽을 때 쓰는 기본값**. 앞의 둘만 고치면
#: `Get-Content 메모.txt` 가 여전히 `?쒓? ?댁슜` 로 온다. 한국어 PC 에서 실제로 그랬다.
_PS_UTF8_PRELUDE = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    "$OutputEncoding=[Text.Encoding]::UTF8; "
    "$PSDefaultParameterValues['*:Encoding']='utf8'; "
)

_SHELL_NEVER = re.compile(
    r"\b(?:set-mppreference|add-mppreference|remove-mppreference|"             # Windows Defender
    r"netsh\s+advfirewall|new-netfirewallrule|set-netfirewallprofile|"         # 방화벽
    r"certutil|import-certificate|import-pfxcertificate|"                      # 인증서
    r"sc\.exe|set-service|new-service|"                                        # 서비스
    r"reg\s+(?:add|delete|import)|set-itemproperty\s+hklm|new-itemproperty\s+hklm|"  # 레지스트리
    r"bcdedit|diskpart|vssadmin|cipher\s+/w|takeown|icacls|"                   # 디스크·권한
    r"set-executionpolicy|disable-windowsoptionalfeature|"                     # 정책
    r"net\s+user|net\s+localgroup|add-localgroupmember)\b"                    # 계정
    # ★ 디스크 포맷은 **드라이브를 지목한 명령**으로만 잡는다 (2026-10-09 새벽 · 판 hw5).
    #   낱말 `format` 을 통째로 막아 `Format-Table` · `Format-List` · `Get-Date -Format` 이 전부 「보안 설정 변경」으로
    #   거절됐다 — PowerShell 에서 가장 흔한 출력 명령이다. 운영 셸 명령 75개에 대 보니 옛 규칙이 막은 3개가 전부
    #   `Format-Table` 이었다. `format C:` · `format.com d:` 는 그대로 막는다.
    r"|\bformat(?:\.com)?\s+[a-z]:",
    re.IGNORECASE,
)

#: 손대면 안 되는 자리. **경로로 쓰인 것**만 잡는다 — 「windows」라는 낱말만으로 막으면
#: `Get-Content windows_notes.md` 같은 멀쩡한 파일까지 걸려 조사가 또 막힌다.
_SHELL_FORBIDDEN_PATHS = re.compile(
    r"windows[\\/](?:system32|syswow64)|[\\/]windows[\\/]|"
    r"program\s*files|programdata|\$env:systemroot|\$env:windir",
    re.IGNORECASE,
)



#: 모델이 **이미 아는 다른 이름**. 같은 것을 다르게 부르는 것뿐이라 받아 준다 (2026-09-21).
#
# ★ AURORA 3판에서 `local_apply_edit` 가 두 번 튕겼다. 거절문을 친절하게 고친 **뒤에도**
#   또 튕겼고, 무엇을 보냈는지 보니 `{"new_string": ...}` — **클로드 코드의 인자 이름**이었다.
#   모델은 그 이름을 이미 알고 있고, 세상에서 그게 더 흔하다. 안내문으로 이름을 가르치는
#   것보다 **받아 주는 것**이 싸고 확실하다(사고 R: 결정론으로 박을 수 있으면 코드로).
#
#   어젯밤 같은 자리를 겪었다 — 도구 설명을 표로 바꾸자 모델이 `command` 를 문자열로
#   보냈고, 막는 대신 문자열을 받아 주도록 고쳤다.
#
# ⚠ 우리 이름이 같이 오면 **우리 것이 이긴다.** 둘 다 왔을 때 조용히 고르면 안 된다.
_ARGUMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "old": ("old_string", "oldText", "search"),
    "new": ("new_string", "newText", "replace"),
    "content": ("file_text", "text", "body"),
}


#: 상대 경로 첫 칸에 오는 **사람의 폴더 이름** → 홈 아래 실제 폴더 (`_resolve_mutation_path`).
#: 사용자 폴더의 사람 이름 — 승인 카드의 「바탕화면에 쓰기」.
_USER_FOLDER_LABELS: dict[str, str] = {"Desktop": "바탕화면", "Documents": "문서", "Downloads": "다운로드"}


def _require_path(arguments: dict[str, Any]) -> None:
    """쓰기 도구의 승인 전 검사 — 어디에 쓸지 없으면 카드를 만들지 않고 모델에게 고칠 말을 돌려준다."""
    if not str(arguments.get("path") or "").strip():
        raise ValueError(
            "path_required — 어디에 쓸지(path)가 없다. 파일 이름을 path 로 넣어 다시 불러라(예: 교보문고_파이썬_도서.xlsx). "
            "이름만 주면 사람이 찾기 쉬운 결과물 폴더(문서\\Sonjari)에 저장된다."
        )


def describe_write_target(arguments: dict[str, Any]) -> dict[str, Any]:
    """승인 카드에 보여 줄 **실제 경로와 자리**. 파일을 만들거나 지우지 않는다(보기만).

    ★ 2026-09-23 스토어 촬영: 카드에 `"path": "바탕화면/회의 메모.txt"` 가 날것으로 떴다. 사람은 그게 진짜 바탕화면인지,
      작업 폴더 안의 「바탕화면」이라는 폴더인지 알 수 없다 — 승인은 판단할 수 있어야 의미가 있다.
      `_resolve_mutation_path` 와 같은 규칙으로 푼다(첫 칸이 사용자 폴더 이름이면 사람의 그 폴더).
    """
    raw = str(arguments.get("path") or "").strip()
    if not raw:
        return {}
    expanded = Path(os.path.expandvars(raw)).expanduser()
    if expanded.is_absolute():
        home = Path.home()
        place = ""
        for folder, label in _USER_FOLDER_LABELS.items():
            try:
                expanded.relative_to(home / folder)
                place = label
                break
            except ValueError:
                continue
        return {"path": str(expanded), "place": place or str(expanded.parent), "label": f"{place or '이 위치'}에 쓰기"}
    parts = expanded.parts
    folder = _USER_FOLDER_ALIASES.get(parts[0].casefold()) if len(parts) > 1 else None
    if folder:
        real = Path.home() / folder / Path(*parts[1:])
        label = _USER_FOLDER_LABELS.get(folder, folder)
        return {"path": str(real), "place": label, "label": f"{label}에 쓰기"}
    return {"path": raw, "place": "작업 폴더", "label": "작업 폴더에 쓰기"}


_USER_FOLDER_ALIASES: dict[str, str] = {
    "바탕화면": "Desktop", "바탕 화면": "Desktop", "데스크톱": "Desktop", "데스크탑": "Desktop", "desktop": "Desktop",
    "문서": "Documents", "내 문서": "Documents", "documents": "Documents",
    "다운로드": "Downloads", "downloads": "Downloads",
}


def _with_aliases(arguments: dict[str, Any]) -> dict[str, Any]:
    """흔한 다른 이름을 우리 이름으로 옮긴 사본. 원본은 안 바꾼다."""
    out = dict(arguments)
    for ours, others in _ARGUMENT_ALIASES.items():
        if str(out.get(ours) or ""):
            continue  # 우리 이름이 이미 있으면 그것이 이긴다
        for other in others:
            if str(out.get(other) or ""):
                out[ours] = out[other]
                break
    return out


#: 붙어 버린 두 폴더 이름 사이에 들어갔던 것 — 빈칸·밑줄·붙임표·아무것도 없음.
_GLUE_SEPARATORS = (" ", "_", "-", "")


def repair_doubled_folder(path: Path, *, allow_missing_leaf: bool = False) -> Path | None:
    """같은 폴더 이름이 **두 번 겹친** 경로(`…\\forth\\forth\\파일`)에서 하나를 걷어 낸다. 딱 하나로 정해질 때만, 아니면 None.

    ★ 2026-10-08 바깥 코드 과제(9B): 작업 폴더가 `…\\forth` 인데 모델이 그 안의 파일을 `…\\forth\\forth\\INSTRUCTIONS.md` 로
      불렀다 — 폴더 이름을 한 번 더 붙인 것. 「경로 없음」과 근처 안내를 다섯 번 받고도 같은 경로를 되풀이해 판이 10초 만에
      0걸음으로 멈췄다(열두 과제 중 둘). 안내는 안 먹었다 — 디스크에 실제로 있는 쪽으로만 바로잡는다(지어낼 자리가 없다).
      겹친 이름의 폴더가 정말 있으면(`a\\a\\파일`) 원래 경로가 있으니 여기 오지 않는다.
    """
    parts = path.parts
    hits: list[Path] = []
    for index in range(1, len(parts) - 1):
        if parts[index].lower() != parts[index + 1].lower():
            continue
        candidate = Path(*parts[: index + 1], *parts[index + 2 :])
        if candidate.exists() or (allow_missing_leaf and candidate.parent.is_dir()):
            hits.append(candidate)
    hits = list(dict.fromkeys(hits))
    return hits[0] if len(hits) == 1 else None


def repair_glued_path(path: Path, *, allow_missing_leaf: bool = False) -> Path | None:
    """구분자(역슬래시)가 빠져 두 폴더 이름이 붙은 경로를 **실제 폴더로** 나눈다. 딱 하나로 정해질 때만, 아니면 None.

    ★ 2026-10-02 Ornith 35B 코딩 사다리: 작업 폴더 `C:\\RoboMetaFit\\tools\\ladder_ornith\\…` 를 모델이
      `tools ladder_ornith` · `toolsladder_ornith` · `tools_ladder_ornith` 로 썼다 — 언제나 `tools` 와 `ladder` 사이 한 곳,
      판의 첫 직접 호출부터. 같은 모델에게 단발 호출·같은 대화 모양·생각 켜기로 각 4번씩 재 보니 전부 맞게 썼다
      (단독으로는 재현 안 됨 — 원인 판별은 실패한 판의 실제 요청을 붙잡아야 끝난다). 원인과 무관하게, 디스크에 있는
      이름으로만 나누므로 지어낼 자리가 없다. L4 판은 이 경로로 13번, L6 판은 9번 「경로 없음」을 받았다.
    """
    parts = path.parts
    if len(parts) < 2:
        return None
    current = Path(parts[0])
    changed = False
    for index, segment in enumerate(parts[1:], 1):
        nxt = current / segment
        last = index == len(parts) - 1
        if nxt.exists() or (last and allow_missing_leaf and current.is_dir()):
            current = nxt
            continue
        try:
            children = [entry.name for entry in os.scandir(current) if entry.is_dir()][:2000]
        except OSError:
            return None
        hits: list[Path] = []
        for name in children:
            for separator in _GLUE_SEPARATORS:
                head = name + separator
                if len(segment) <= len(head) or not segment.lower().startswith(head.lower()):
                    continue
                candidate = current / name / segment[len(head):]
                if candidate.exists() or (last and allow_missing_leaf):
                    hits.append(candidate)
        hits = list(dict.fromkeys(hits))
        if len(hits) != 1:
            return None
        current, changed = hits[0], True
    return current if changed else None


#: 이름으로 켜도 되는 윈도우 기본 프로그램 — (부르는 이름들, System32 안의 실행 파일). 목록 밖은 예전대로 막는다(2026-10-17).
_SYSTEM_APPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("notepad", "메모장"), "notepad.exe"),
    (("calc", "calculator", "계산기"), "calc.exe"),
    (("mspaint", "paint", "그림판"), "mspaint.exe"),
    (("taskmgr", "task manager", "작업 관리자", "작업관리자"), "Taskmgr.exe"),
    (("explorer", "file explorer", "windows explorer", "파일 탐색기", "탐색기"), "explorer.exe"),
    # ★ 2026-10-18 「모르는 앱」 측정: 「시스템 정보(msinfo32)를 열어서」가 System32 라 허용 폴더 밖으로 막혀 3판 모두 창을 못 열고
    #   셸 명령(systeminfo)으로 돌아갔다. 읽기만 하는 정보 창이라 이름으로 연다.
    (("msinfo32", "system information", "시스템 정보"), "msinfo32.exe"),
)
#: 윈도우 설정 화면 — 실행 파일이 아니라 `ms-settings:` 주소로 연다. 이름 → 주소(정해 둔 것만, 모델 글의 주소는 받지 않는다).
_SETTINGS_PAGES: dict[str, str] = {
    "설정": "ms-settings:", "윈도우 설정": "ms-settings:", "windows settings": "ms-settings:", "settings": "ms-settings:",
    "설정 정보": "ms-settings:about", "시스템 정보 설정": "ms-settings:about", "about": "ms-settings:about",
    "설정 > 시스템 > 정보": "ms-settings:about", "시스템 → 정보": "ms-settings:about", "시스템 > 정보": "ms-settings:about",
    "디스플레이 설정": "ms-settings:display", "소리 설정": "ms-settings:sound", "저장소 설정": "ms-settings:storagesense",
}


def settings_page(requested: str) -> str | None:
    """「설정」 · 「시스템 → 정보」처럼 정해 둔 설정 화면 이름이면 그 `ms-settings:` 주소, 아니면 None(2026-10-18)."""
    text = " ".join(str(requested or "").strip().strip('"').split()).casefold()
    if text.startswith("ms-settings:"):
        return text if text in {value.casefold() for value in _SETTINGS_PAGES.values()} else None
    return _SETTINGS_PAGES.get(text) or next((v for k, v in _SETTINGS_PAGES.items() if k.casefold() == text), None)
#: 따로 깔리는 프로그램 — 윈도우가 「App Paths」에 적어 둔 자리에서만 찾는다(경로를 모델 글에서 받지 않는다).
# ★ 2026-10-17 앱 묶음 측정 준비: 엑셀 · 워드 · 파워포인트 · VS Code 를 이름으로 못 열었다(목록에 없음). 넷 다 이 PC 의
#   「App Paths」에 자리가 적혀 있다. 윈11 그림판은 스토어 앱이라 System32 에 없고 App Paths 에 있다(아래 `launchable_app`).
_REGISTERED_APPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("hwp", "한글", "한컴오피스 한글", "hancom hwp"), "Hwp.exe"),
    (("excel", "엑셀", "microsoft excel", "ms excel"), "excel.exe"),
    (("word", "워드", "winword", "microsoft word", "ms word"), "winword.exe"),
    (("powerpoint", "파워포인트", "powerpnt", "ppt", "microsoft powerpoint"), "powerpnt.exe"),
    (("code", "vscode", "vs code", "visual studio code", "비주얼 스튜디오 코드"), "Code.exe"),
)


def _app_paths_lookup(exe: str) -> str:
    """윈도우 「App Paths」에 등록된 실행 파일 자리. 없으면 빈 글."""
    try:
        import winreg  # noqa: PLC0415 — 윈도우에서만
    except ImportError:
        return ""
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for root in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
                     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"):
            try:
                with winreg.OpenKey(hive, rf"{root}\{exe}") as key:
                    value = str(winreg.QueryValue(key, None) or "").strip().strip('"')
            except OSError:
                continue
            if value and Path(value).is_file():
                return value
    # 한컴 오피스는 「App Paths」에 안 적는 판이 있다(이 PC 의 한글 2022). 설치 폴더 안에서만 찾는다.
    if exe.casefold() == "hwp.exe":
        for base in (os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)", os.environ.get("ProgramFiles") or r"C:\Program Files"):
            for vendor in ("HNC", "Hnc", "Hancom"):
                hits = sorted(Path(base, vendor).glob("Office */HOffice*/Bin/Hwp.exe"), reverse=True)
                if hits:
                    return str(hits[0])
    return ""


def _visible_windows() -> dict[int, str]:
    """지금 화면에 보이는 맨 위 창들 — {창 번호: 제목}. 윈도우가 아니면 빈 것."""
    if os.name != "nt":
        return {}
    found: dict[int, str] = {}
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(hwnd: Any, _param: Any) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                found[int(hwnd)] = buffer.value
        return True

    user32.EnumWindows(callback_type(collect), 0)
    return found


def _wait_for_new_window(before: dict[int, str], *, timeout: float = 12.0) -> dict[str, Any]:
    """연 뒤 **새로 뜬 창**을 기다려 그 번호 · 제목을 돌려준다 (2026-10-17 한글 → PDF 측정).

    한글이 뜨는 몇 초 동안 모델이 창 목록 보기와 `tasklist` 를 여섯 번 되풀이했다. 여기서 기다려 주면 한 걸음이다.
    시간 안에 안 뜨면(이미 떠 있던 프로그램이 새 창 없이 앞으로 왔을 수도 있다) 빈 것을 돌려준다 — 그때는 창 목록으로 본다.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        time.sleep(0.5)
        now = _visible_windows()
        fresh = {hwnd: title for hwnd, title in now.items() if hwnd not in before and title.strip()}
        if fresh:
            hwnd, title = next(iter(fresh.items()))
            return {"window_id": hwnd, "window_title": title[:300]}
    return {}


def launchable_app(requested: str) -> str | None:
    """「메모장」 · `notepad.exe` · `C:\\Windows\\System32\\notepad.exe` 처럼 정해 둔 프로그램을 부른 것이면 그 실행 파일 자리, 아니면 None.

    전체 경로로 부른 것은 **그 자리가 실제 자리와 같을 때만** 받는다 — 다른 폴더의 같은 이름 실행 파일은 받지 않는다.
    """
    text = str(requested or "").strip().strip('"').strip()
    if not text:
        return None
    lowered = text.casefold()
    name = Path(text).name.casefold()
    stem = name[:-4] if name.endswith(".exe") else name
    system = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32"
    for names, exe in _SYSTEM_APPS:
        if lowered in names or stem in names or name == exe.casefold():
            # System32 → 윈도우 폴더(explorer.exe) → 실행 별칭 · App Paths(윈11 그림판처럼 스토어 앱이 된 것) 순서로 찾는다.
            aliases = Path(os.environ.get("LOCALAPPDATA") or "") / "Microsoft" / "WindowsApps"
            candidates = [system / exe, system.parent / exe, aliases / exe]  # 스토어 앱은 실행 별칭으로 띄운다
            registered = _app_paths_lookup(exe)
            if registered:
                candidates.append(Path(registered))
            target = next((path for path in candidates if path.is_file()), None)
            if target is None:
                return None
            if ("\\" in text or "/" in text) and Path(text).resolve() != target.resolve():
                return None
            return str(target)
    for names, exe in _REGISTERED_APPS:
        if lowered in names or stem in names or name == exe.casefold():
            found = _app_paths_lookup(exe)
            if not found:
                return None
            if ("\\" in text or "/" in text) and Path(text).resolve() != Path(found).resolve():
                return None
            return found
    return None


class LocalComputerTools:
    def __init__(
        self,
        config: JarvisConfig,
        *,
        reader: DocumentReader | None = None,
        memory: Any | None = None,
    ) -> None:
        self.config = config
        self.reader = reader or DocumentReader()
        # 색인이 어떤 경로를 올릴 때, 그 자리에 대해 **이미 아는 것**을 같이
        # 올리려고 쥔다. 없으면 색인은 예전과 똑같이 동작한다.
        self.memory = memory
        self.code_index = CodeIndex(config.output_dir / "code_index")
        #: 아는 비밀 값의 모음 — 런타임이 건다. 명령 출력에서 그 값을 가린다(`_run_for_model`).
        self.known_secrets: Any = None
        self.allowed_roots = self._parse_roots(config.local_file_allowed_roots)
        self.workspace_root = (config.output_dir / "workspace").resolve(strict=False)
        self.backup_root = (config.output_dir / "backups").resolve(strict=False)
        if self.workspace_root not in self.allowed_roots:
            # env가 예전 허용목록을 들고 있어도 자기가 만든 파일은 다시 읽을 수
            # 있어야 한다. 이 루트는 자비스 자신의 output_dir 아래로 고정돼 있다.
            self.allowed_roots.append(self.workspace_root)
        # ★ 결과물 폴더도 같은 이유로 **반드시** 들어간다 (2026-09-01).
        #
        #   기본값(`내 문서\\JARVIS`)은 허용 목록의 `내 문서` 아래라 우연히 통과하고
        #   있었다. 그런데 `documents_dir` 를 설정으로 빼면서 다른 자리를 가리키면
        #   자비스가 **자기 결과물 폴더에 못 쓴다** — 검사가 그렇게 걸렸다.
        #   자리를 옮길 수 있게 만들었으면 따라와야 할 것도 같이 옮겨야 한다.
        documents_root = Path(
            getattr(config, "documents_dir", None) or documents_product_dir(Path.home() / "Documents")
        ).resolve(strict=False)
        if documents_root not in self.allowed_roots:
            self.allowed_roots.append(documents_root)
        # ── 읽기는 넓게, 쓰기는 좁게 (2026-09-20) ──────────────────────────────
        #
        #   `allowed_roots` 는 이제 **쓰기** 범위다. 읽기는 여기에 `read_roots` 를 더해서 본다.
        #   비면 사용자 폴더 전체 — 코워크가 이 PC 를 보고 답하려면 읽을 수 있어야 한다.
        self.read_roots = self._parse_roots(getattr(config, "local_read_roots", "") or "")
        if not self.read_roots:
            self.read_roots = [Path.home().resolve(strict=False)]
        #: 사람이 승인 카드로 열어 준 자리. `{"read": [...], "write": [...]}`.
        self._granted: dict[str, list[Path]] = {"read": [], "write": []}
        self._load_grants()
        self._definitions = self._build_definitions()
        # Code 모드에서 사람이 폴더 선택기로 고른 루트만 잡별 작업공간으로 승격한다.
        # 일반 대화의 상대경로는 계속 outputs/workspace/<job>에 격리된다.
        self._code_workspaces: dict[str, Path] = {}
        #: 판이 시작될 때 작업 폴더에 **이미 있던** 폴더(루트 기준 상대 경로). 「이 판이 만든 폴더」를 가리는 근거다.
        self._folders_at_start: dict[str, frozenset[str] | None] = {}
        #: 판이 끝나면 띄울 파일(잡별 하나). `remember_to_open` / `open_pending`.
        self._pending_opens: dict[str, Path] = {}
        #: 사람이 자리와 이름까지 댄 산출물(잡별 하나) — 「바탕화면에 x.png 로 저장」. `expect_delivery`.
        self._deliveries: dict[str, Path] = {}
        #: 잡마다 **이 판이 만든** 결과물 경로(대조는 소문자로). 여기 없는 이미 있는 파일은 덮지 않는다(`write_document_file`).
        self._made_by_job: dict[str, set[str]] = {}
        #: 잡마다 「달라고 한 이름(소문자) → 남의 파일을 피해 대신 만든 경로」.
        self._detoured_by_job: dict[str, dict[str, str]] = {}
        # 마지막으로 파일을 연 뒤 목록을 몇 번 봤는가. 낱말이 아니라 **행동**을
        # 본다 — 브라우저 쪽에서 `_searches_without_read` 로 검증된 방법이다.
        # 1 이면 방금 처음 본 것이고, 2 부터가 "안 읽고 또 봤다"다.
        self._listings_since_read = 0

    @staticmethod
    def _parse_roots(raw: str) -> list[Path]:
        roots: list[Path] = []
        for value in raw.split(";"):
            value = value.strip()
            if not value:
                continue
            resolved = Path(os.path.expandvars(value)).expanduser().resolve(strict=False)
            if resolved not in roots:
                roots.append(resolved)
        return roots

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
                "local_list_directory",
                "허용된 로컬 PC 폴더의 파일과 하위 폴더 목록을 확인한다. 숨김·비밀 파일은 제외한다.",
                {
                    "path": {"type": "string"},
                    "pattern": {"type": "string", "description": "선택적인 파일명 패턴(예: *.md)"},
                    "max_items": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                ["path"],
            ),
            self._function(
                "local_search_files",
                "허용된 로컬 PC 폴더에서 파일명으로 파일과 폴더를 검색한다.",
                {
                    "query": {"type": "string"},
                    "root": {"type": "string", "description": "비우면 모든 허용 루트"},
                    "extension": {"type": "string", "description": "선택적 확장자(예: .docx)"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                ["query"],
            ),
            self._function(
                "local_write_document",
                "자기가 정리한 내용으로 **엑셀·워드·PPT·한글(hwpx)·CSV 파일을 만든다.** "
                # ★ 대결 T2(2026-09-28): 이 줄이 rows 를 먼저 대서 모델이 워드에도 rows(표 한 장) → sheets → blocks 로 **세 번** 썼다.
                "**워드·한글·PPT·md 는 blocks 하나로** 제목·문단·표 여러 개를 한 번에 준다(아래 blocks 예). "
                "rows 는 표 한 장짜리(엑셀·CSV), sheets 는 엑셀 여러 시트다. "
                "읽은 자료를 표나 문서로 남길 때 쓴다 — 텍스트로만 답하지 마라.",
                {
                    "path": {"type": "string", "description": "예: 정리.xlsx (상대 경로 권장)"},
                    "format": {"type": "string", "description": "xlsx·docx·pptx·**hwpx(한글)**·csv·md·txt (생략하면 확장자)"},
                    "rows": {"type": "array", "items": {}, "description": "표 한 장"},
                    "sheets": {"type": "object", "description": "{시트이름: 표} — 여러 장일 때"},
                    "blocks": {
                        "type": "array",
                        "items": {},
                        "description": (
                            # ★ **기본 모양부터 보여 준다** (2026-09-11).
                            #
                            #   전에는 각주 설명만 길게 있고 제목·표를 어떻게 주는지가
                            #   없었다. 그래서 모델이 전부 `paragraph` 로 보냈고, 라이브
                            #   문서의 큰 제목이 `Normal` 스타일로 나왔다 — 워드에서
                            #   개요도 목차도 안 잡힌다. 코드에 `heading` 이 있는데
                            #   **쓰는 법을 안 알려 준 것**이다.
                            "문서의 뼈대. **제목은 heading 으로, 표는 table 로 줘라** — "
                            "전부 paragraph 로 보내면 제목이 본문과 같은 크기로 나온다. "
                            '예: [{"type":"heading","level":1,"text":"조사 결과"},'
                            '{"type":"paragraph","text":"사람인에서 3건을 직접 열어 확인했다."},'
                            '{"type":"table","rows":[["회사명","마감일"],["가나","2026.10.09"]]}]. '
                            "쓸 수 있는 type: heading(level 1~3)·paragraph·table·bullet"
                            "·code·quote. 서식(글꼴·여백·머리줄 굵기)은 손자리가 알아서 "
                            "입히니 신경 쓰지 마라. "
                            "각주는 hwpx 에서만 되고 "
                            '{"type":"paragraph","text":"본문","footnote":"수정 제안"} 로 준다. '
                            "★ 한 문단에 **여러 개**를 달 수 있다 — 회사별로 다른 제안이면 "
                            'footnote 를 목록으로 줘라: "footnote":[{"label":"A사","text":"…"},'
                            '{"label":"B사","text":"…"}]. 한 칸에 이어 붙이면 각주 **1개**로 '
                            "세어져 미달이 된다. 본문에 [수정 제안: …] 처럼 써 넣는 것은 각주가 아니다."
                        ),
                    },
                    "text": {"type": "string"},
                    "open": {"type": "boolean", "description": "만든 뒤 바로 띄운다(기본 참)"},
                },
                ["path"],
            ),
            self._function(
                "local_edit_spreadsheet",
                "이미 있는 엑셀의 **셀만** 고친다. 서식·수식·다른 시트는 그대로 둔다. "
                "사람이 쓰던 파일에 값을 채워 넣을 때 쓴다.",
                {
                    "path": {"type": "string"},
                    "edits": {"type": "array", "items": {}, "description": '[{"cell":"B3","value":"..."}]'},
                    "sheet": {"type": "string", "description": "고칠 시트 이름. 시트가 하나면 비워도 되고, 여러 개면 꼭 넣는다"},
                },
                ["path", "edits"],
            ),
            self._function(
                "local_edit_document",
                "이미 있는 **워드(docx)·한글(hwpx)·발표자료(pptx)** 를 제자리에서 고친다. 통째로 다시 쓰지 "
                "않으므로 서식·표·머리말·글꼴·레이아웃이 그대로 남는다. 받은 파일을 손보라는 말에는 "
                "local_write_document 로 새로 만들지 말고 **이걸** 써라 — 새로 쓰면 원래 서식이 전부 날아간다. "
                "문단·슬라이드 번호는 0부터이고 local_read_document 가 보여 준 순서와 같다.",
                {
                    "path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "items": {},
                        "description": (
                            '워드·한글: {"find":"옛 글","replace":"새 글"} · '
                            '{"paragraph":3,"text":"새 내용"} · {"after":3,"insert":"끼울 문단"} · '
                            '{"delete":7} · {"paragraph":3,"footnote":"수정 제안"} — 마지막이 '
                            '**진짜 각주**이고 hwpx 에서만 된다(본문에 [수정 제안: …] 을 써 넣는 것은 '
                            '각주가 아니다). '
                            'PPT: {"slide":2,"title":"새 제목"} · {"slide":2,"bullets":["가","나"]} · '
                            '{"after":2,"insert":{"title":"...","bullets":["..."]}} · {"delete":3}'
                        ),
                    },
                },
                ["path", "edits"],
            ),
            self._function(
                "local_grep",
                "파일 **내용**에서 정규식으로 찾는다. 파일:줄번호와 앞뒤 맥락이 함께 온다. "
                "「이 값이 어디서 정해지나」·「이 함수를 누가 부르나」는 이 도구로 답한다 — "
                "파일을 열어 눈으로 훑지 마라.",
                {
                    "pattern": {"type": "string", "description": "정규식(파이썬 문법)"},
                    "path": {"type": "string", "description": "찾을 뿌리 폴더"},
                    "extension": {"type": "string", "description": "예: .py — 좁힐수록 빠르다"},
                    "context": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 5,
                        "description": "매칭 줄 앞뒤로 함께 볼 줄 수",
                    },
                    "ignore_case": {"type": "boolean"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                ["pattern"],
            ),
            self._function(
                "local_glob",
                "이름 패턴으로 **트리 전체**에서 파일을 찾는다(예: **/*.test.ts). "
                "한 폴더만 보는 local_list_directory 와 다르다.",
                {
                    "pattern": {"type": "string", "description": "예: **/*.py"},
                    "path": {"type": "string", "description": "찾을 뿌리 폴더"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 400},
                },
                ["pattern"],
            ),
            self._function(
                "local_read_text_file",
                "허용된 경로의 텍스트·코드 파일을 읽는다. 큰 파일은 잘리고 outline(함수와 줄 범위)이 함께 온다 — "
                "그 다음엔 line_start/line_end 로 필요한 구간만 다시 읽어라. 비밀 파일은 차단한다.",
                {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 40000},
                    "line_start": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "이 줄부터 읽는다(1부터). outline 의 범위를 그대로 넣으면 된다.",
                    },
                    "line_end": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "이 줄까지 읽는다(포함).",
                    },
                },
                ["path"],
            ),
            self._function(
                "local_read_document",
                "허용된 경로의 PDF·DOCX·XLSX·PPTX·HWPX·ODT·EPUB·텍스트 문서를 구조와 인코딩을 보존해 읽는다.",
                {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 80000},
                },
                ["path"],
            ),
            self._function(
                "local_index_codebase",
                "선택한 코드 저장소를 .gitignore·생성물·비밀 경로를 제외해 증분 색인하고 "
                "파일·심볼·import 후보 지도를 반환한다. 내용 확인은 별도 파일 읽기가 필요하다.",
                {
                    "path": {"type": "string", "description": "코드 저장소 절대 폴더. 비우면 이 작업의 폴더."},
                    "query": {"type": "string", "description": "선택적 파일·심볼·import 검색어"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 80},
                    "max_chars": {"type": "integer", "minimum": 4000, "maximum": 16000},
                },
                [],
            ),
            self._function(
                "local_find_symbol",
                "함수·클래스·상수 이름 하나로 **정의가 어디고 누가 부르는지** 찾는다(파이썬). "
                "정의는 문법으로 정확히 찾고 줄 범위를 같이 준다 — 그 줄만 읽으면 된다. "
                "고치기 전에 이것부터 불러라: 무엇이 깨질지 먼저 보인다. "
                "이름을 모르고 뭉뚱그려 찾을 때는 local_index_codebase, 글자 그대로 찾을 때는 local_grep.",
                {
                    "path": {"type": "string", "description": "코드 저장소 절대 폴더"},
                    "symbol": {"type": "string", "description": "이름만. 예: monthly_fee (a.b 는 안 됨)"},
                    "max_references": {"type": "integer", "minimum": 5, "maximum": 200},
                },
                ["path", "symbol"],
            ),
            self._function(
                "local_write_file",
                "텍스트 파일을 새로 쓰거나 전체 내용을 바꾼다. 상대 경로는 이 작업의 전용 폴더에 저장된다. "
                "사용자 파일처럼 작업 폴더 밖의 경로는 화면 승인이 필요하다.",
                {
                    "path": {"type": "string", "description": "상대 경로면 현재 작업폴더 기준"},
                    "content": {"type": "string", "description": "UTF-8로 저장할 전체 내용"},
                },
                ["path", "content"],
            ),
            self._function(
                "local_apply_edit",
                "텍스트 파일에서 정확히 한 번 나오는 old를 new로 바꾼다. 상대 경로는 현재 작업폴더 기준이다. "
                "old가 없거나 두 번 이상이면 추측해서 고치지 않고 멈춘다.",
                {
                    "path": {"type": "string", "description": "상대 경로면 현재 작업폴더 기준"},
                    "old": {"type": "string", "description": "파일에 정확히 한 번 있는 원문"},
                    "new": {"type": "string", "description": "바꿀 새 원문"},
                },
                ["path", "old", "new"],
            ),
            self._function(
                "local_delete_file",
                "허용된 로컬 파일 하나를 삭제한다. 백업해 두므로 되돌릴 수 있다. 권한 모드와 자리에 따라 화면 승인을 한 번 물을 수 있다. 폴더는 코드 작업 폴더 안에서 **이 작업이 만든 폴더**(예: 방금 생긴 node_modules)와 캐시 폴더(__pycache__ 등)만 지운다 — 폴더 삭제는 되돌릴 수 없어서, 원래 있던 폴더는 지우지 않는다.",
                {"path": {"type": "string", "description": "상대 경로면 현재 작업폴더 기준"}},
                ["path"],
            ),
            self._function(
                "local_run_project_command",
                "선택한 프로젝트 폴더에서 테스트·빌드·정적검사·Git 명령(status·diff·log 와 add·commit·branch·switch)을 실행하고 "
                "종료 코드와 출력을 검증 근거로 남긴다. 패키지 설치는 프로젝트 가상환경에만 한다(pip install). 그 밖의 셸 명령은 받지 않는다.",
                {
                    "path": {
                        "type": "string",
                        "description": "실행할 프로젝트의 절대 폴더 경로. 비우면 이 작업의 폴더에서 돈다.",
                    },
                    # ★ 문자열도 받는다 (2026-09-20). 설명이 `python -m pytest -q` 처럼 보이니
                    #   모델은 그 모양대로 보낸다 — 배열만 받던 때 한 판에서 일곱 번 막혔다.
                    "command": {
                        "type": ["array", "string"],
                        "items": {"type": "string"},
                        "maxItems": 30,
                        "description": "\"python -m pytest -q\" 처럼 한 줄로 주거나 "
                                       "[\"python\", \"-m\", \"pytest\", \"-q\"] 처럼 나눠서 줘도 된다.",
                    },
                    "timeout_sec": {
                        "type": "integer",
                        "minimum": 5,
                        "maximum": 300,
                    },
                },
                ["path", "command"],
            ),
            self._function(
                "windows_list_open_windows",
                "현재 Windows PC에서 화면에 열린 앱 창의 제목과 창 ID를 확인한다.",
                {"max_results": {"type": "integer", "minimum": 1, "maximum": 100}},
            ),
            self._function(
                "windows_focus_window",
                "사용자가 요청한 열린 앱 창을 앞으로 가져온다. 창 ID는 windows_list_open_windows 결과를 사용한다.",
                {"window_id": {"type": "integer"}},
                ["window_id"],
            ),
            self._function(
                "windows_open_path",
                "허용된 로컬 폴더 또는 파일을 Windows 기본 앱으로 연다. 메모장 · 계산기 · 그림판 · 작업 관리자 · 파일 탐색기 · 시스템 정보 · 한글(HWP) · 엑셀 · 워드 · 파워포인트 · VS Code 는 path 에 이름만 적으면 새로 켠다(예: \"엑셀\", \"taskmgr\"). 윈도우 설정 화면은 path 에 \"설정\" 또는 \"시스템 → 정보\"처럼 적으면 연다. 파일을 기본 앱이 아닌 그 앱들 가운데 하나로 열려면 app 에 앱 이름을 같이 적는다(예: path 에 그림 파일, app 에 \"그림판\"). 실제 프로그램 실행이므로 화면 승인이 필요하다.",
                {"path": {"type": "string"}, "app": {"type": "string"}},
                ["path"],
            ),
            self._function(
                "local_request_path_access",
                "허용 범위 밖의 폴더가 필요할 때 사용자에게 그 폴더를 열어 달라고 요청한다. "
                "path_outside_allowed_roots 로 막혔으면 같은 경로를 다시 시도하지 말고 이 도구로 한 번 요청한다. "
                "화면에 승인 카드가 뜨고 사용자가 승인해야만 열린다. mode 는 읽기만 필요하면 read, "
                "파일을 만들거나 고쳐야 하면 write 이며, reason 에는 왜 그 폴더가 필요한지 한 문장으로 적는다.",
                {
                    "path": {"type": "string", "description": "열어 달라고 요청할 폴더의 절대 경로"},
                    "mode": {"type": "string", "enum": ["read", "write"]},
                    "reason": {"type": "string", "description": "이 폴더가 필요한 이유 한 문장"},
                },
                ["path", "mode", "reason"],
            ),
            self._function(
                "local_run_shell",
                "작업 폴더에서 PowerShell 명령 한 줄을 돌린다(창은 뜨지 않는다). "
                "둘러보기에 쓴다: dir, Get-ChildItem, Select-String, Get-Content, git log, --version. "
                "보기만 하는 명령은 바로 돌고, 만들기·지우기·설치·네트워크는 사용자 승인 카드가 뜬다. "
                "보안 설정·시스템 폴더는 어떤 경우에도 거부된다. "
                "시험·린트처럼 정해진 것은 local_run_project_command 가 더 낫다.",
                {
                    "command": {
                        "type": "string",
                        "description": "PowerShell 한 줄. 예: Get-ChildItem -Recurse -Filter *.py",
                    },
                    "timeout_sec": {"type": "integer", "minimum": 5, "maximum": 600},
                },
                ["command"],
            ),
            self._function(
                "local_preview_page",
                "작업 폴더에 만든 웹 페이지(html)를 이 PC 안에서만 보이는 주소로 띄운다. "
                "돌려받은 url 을 browser_open 으로 열면 화면을 직접 확인할 수 있고, 사용자도 같은 화면을 본다.",
                {"path": {"type": "string", "description": "작업 폴더 기준 상대 경로 (예: index.html). 비우면 index.html 을 연다."}},
                [],
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "local_list_directory": self.list_directory,
            "local_search_files": self.search_files,
            "local_read_text_file": self.read_text_file,
            "local_index_codebase": self.index_codebase,
            "local_find_symbol": self.find_symbol,
            "local_grep": self.grep_files,
            "local_write_document": self.write_document_file,
            "local_edit_spreadsheet": self.edit_spreadsheet_file,
            "local_edit_document": self.edit_document_file,
            "local_glob": self.glob_files,
            "local_read_document": self.read_document,
            "local_write_file": self.write_file,
            "local_apply_edit": self.apply_edit,
            "local_delete_file": self.delete_file,
            "local_run_project_command": self.run_project_command,
            "windows_list_open_windows": self.list_open_windows,
            "windows_focus_window": self.focus_window,
            "windows_open_path": self.open_path,
            "local_request_path_access": self.request_path_access,
            "local_preview_page": self.serve_page,
            "local_run_shell": self.run_shell,
        }
        risks = {
            "local_list_directory": RiskLevel.L0,
            "local_search_files": RiskLevel.L1,
            "local_read_text_file": RiskLevel.L1,
            "local_index_codebase": RiskLevel.L1,
            "local_find_symbol": RiskLevel.L1,
            "local_grep": RiskLevel.L1,
            "local_write_document": RiskLevel.L1,
            "local_edit_spreadsheet": RiskLevel.L1,
            "local_edit_document": RiskLevel.L1,
            "local_glob": RiskLevel.L1,
            "local_read_document": RiskLevel.L1,
            "local_write_file": RiskLevel.L1,
            "local_apply_edit": RiskLevel.L1,
            # 선택한 Code 저장소 안에서는 백업 가능한 L1 정리다. 그 밖의
            # 경로는 _mutation_risk가 L2로 올려 기존 승인 경계를 유지한다.
            "local_delete_file": RiskLevel.L1,
            "local_run_project_command": RiskLevel.L1,
            "windows_list_open_windows": RiskLevel.L0,
            "windows_focus_window": RiskLevel.L1,
            "windows_open_path": RiskLevel.L2,
            # ★ 반드시 L2 다. L1 이면 모델이 **혼자 폴더를 열 수 있다** — 그러면 허용 목록이 장식이 된다.
            "local_request_path_access": RiskLevel.L2,
            # 루프백에만 띄우고 작업 폴더 밖은 못 연다 — 되돌릴 것이 없다.
            "local_preview_page": RiskLevel.L1,
            # 바닥은 L2 — 보는 명령이면 `_shell_risk` 가 L1 으로 내린다(등급은 **올리기만** 하는
            # 규칙이라 바닥을 L2 로 두면 안 된다). 아래 dynamic_risk 가 실제 등급을 정한다.
            "local_run_shell": RiskLevel.L2,
        }
        # 승인 카드에 실제 경로·자리를 붙인다 — 인자는 그대로(재실행되는 값이다).
        for writer in ("local_write_file", "local_apply_edit", "local_write_document", "local_edit_spreadsheet",
                       "local_edit_document", "local_delete_file"):
            gateway.approval_describers[writer] = describe_write_target
            # ★ 경로 없는 쓰기는 **카드를 만들기 전에** 돌려보낸다 (2026-09-30 촬영 판). 모르는 경로라 승인으로 올라갔고,
            #   사람이 누르면 쓰기는 `path_required` 로 반드시 실패했다 — 실패가 정해진 일을 사람에게 묻고 있었다.
            gateway.pre_approval_checks[writer] = _require_path
        gateway.pre_approval_checks["local_delete_file"] = self._delete_pre_check
        # 문서 쓰기는 파일 이름만 받으면 `문서\\Sonjari` 에 쓴다 — 카드도 그 실제 자리를 보인다.
        gateway.approval_describers["local_write_document"] = self.describe_document_target
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=risks[name],
                    handler=handlers[name],
                    enabled=self.config.local_computer_enabled,
                    dynamic_risk=(
                        self._delete_risk
                        if name == "local_delete_file"
                        else self._document_risk
                        if name == "local_write_document"
                        else self._mutation_risk
                        if name in {"local_write_file", "local_apply_edit", "local_edit_spreadsheet", "local_edit_document"}
                        else self._shell_risk
                        if name == "local_run_shell"
                        else self._install_risk
                        if name == "local_run_project_command"
                        else None
                    ),
                    inverse=(
                        InverseSpec(
                            label="로컬 파일을 쓰기 전 상태로 되돌리기",
                            handle_from=self._undo_handle,
                            undo=self._undo_mutation,
                        )
                        if name in {"local_write_file", "local_apply_edit", "local_delete_file", "local_write_document", "local_edit_spreadsheet", "local_edit_document"}
                        else None
                    ),
                    proof=(
                        ProofSpec(
                            capture_before=self._capture_file_proof,
                            capture_current=self._capture_file_proof,
                            capture_after=lambda args, result: self._capture_file_proof(args),
                            same_target=same_fingerprint,
                            finalize=self._finalize_file_proof,
                        )
                        if name in {"local_write_file", "local_apply_edit", "local_delete_file"}
                        else None
                    ),
                    needs_job_context=name.startswith("local_") and name in {
                        "local_list_directory",
                        "local_search_files",
                        "local_read_text_file",
                        "local_read_document",
                        "local_index_codebase",
                        "local_find_symbol",
                        "local_write_file",
                        "local_apply_edit",
                        "local_delete_file",
                        "local_run_project_command",
                        # ★ 새 도구는 **여기도** 넣어야 한다 (2026-09-01 라이브 실패).
                        #
                        #   `__job_id` 는 이 목록에 있는 도구에만 주입된다. 안 넣으면
                        #   상대 경로를 풀 작업폴더가 없어 `job_context_required` 로
                        #   죽는다 — 라이브에서 문서 생성이 그렇게 실패했다.
                        #   등록 자리가 아홉 곳이고, 이게 제일 안 보이는 자리다.
                        "local_grep",
                        "local_glob",
                        "local_write_document",
                        "local_edit_spreadsheet",
                        "local_edit_document",
                        "local_preview_page",
                        "local_run_shell",
                    },
                )
            )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.local_computer_enabled,
            "allowed_roots": [str(root) for root in self.allowed_roots],
            "windows_control": self.config.windows_control_enabled and os.name == "nt",
            "mode": "allowlist",
        }

    @staticmethod
    def _is_sensitive(path: Path) -> bool:
        lowered_parts = {part.lower() for part in path.parts}
        lowered_name = path.name.lower()
        if lowered_parts & SENSITIVE_PARTS:
            return True
        if lowered_name == ".env" or lowered_name.startswith(".env."):
            return True
        return any(fragment in lowered_name for fragment in SENSITIVE_NAME_FRAGMENTS)

    def _sensitive_path(self, path: Path) -> bool:
        # 데이터 폴더의 DB·승인 원장 등은 파일명에 `token` 이 없어도 사적이다.
        data_dir = Path(self.config.data_dir).resolve(strict=False)
        return self._is_sensitive(path) or self._inside(path, data_dir)

    # ── 사람이 열어 준 자리 ────────────────────────────────────────────────────
    #
    # 막기만 하면 모델은 같은 호출을 되풀이한다(2026-09-16 실측). **넓히는 길**을 같이 둔다:
    # 모델이 `local_request_path_access` 를 부르면 L2 승인 카드가 뜨고, 사장님이 누른 자리만 열린다.
    # 열린 자리는 파일로 남아 앱을 다시 켜도 유지되고, 설정 › 권한·안전에서 지울 수 있다.

    @property
    def _grants_path(self) -> Path:
        return Path(self.config.data_dir) / "granted_paths.json"

    def _load_grants(self) -> None:
        try:
            raw = json.loads(self._grants_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for mode in ("read", "write"):
            rows = raw.get(mode) or []
            self._granted[mode] = [
                Path(str(row)).resolve(strict=False) for row in rows if str(row).strip()
            ]

    def _save_grants(self) -> None:
        self._grants_path.parent.mkdir(parents=True, exist_ok=True)
        self._grants_path.write_text(
            json.dumps(
                {mode: [str(path) for path in paths] for mode, paths in self._granted.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_scope(self) -> list[Path]:
        return [*self.allowed_roots, *self._granted["write"]]

    def _read_scope(self) -> list[Path]:
        # 쓸 수 있는 자리는 당연히 읽을 수 있다. 읽기 승인은 읽기까지만.
        return [*self._write_scope(), *self.read_roots, *self._granted["read"]]

    def granted_paths(self) -> dict[str, list[str]]:
        """설정 화면이 보여 줄 목록. 사람이 지울 수 있어야 하므로 그대로 내보낸다."""
        return {mode: [str(path) for path in paths] for mode, paths in self._granted.items()}

    def revoke_path_access(self, raw: str, mode: str = "") -> bool:
        target = Path(os.path.expandvars(str(raw))).expanduser().resolve(strict=False)
        removed = False
        for key in (mode,) if mode in ("read", "write") else ("read", "write"):
            kept = [path for path in self._granted[key] if path != target]
            removed = removed or len(kept) != len(self._granted[key])
            self._granted[key] = kept
        if removed:
            self._save_grants()
        return removed

    def request_path_access(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """이 폴더를 열어 달라고 **사람에게** 묻는다. L2 라서 승인 없이는 여기까지 오지 않는다."""
        raw = str(arguments.get("path") or "").strip()
        if not raw:
            raise ValueError("path_required")
        mode = str(arguments.get("mode") or "read").strip().lower()
        if mode not in ("read", "write"):
            raise ValueError("mode_must_be_read_or_write")
        reason = str(arguments.get("reason") or "").strip()
        expanded = Path(os.path.expandvars(raw)).expanduser()
        if not expanded.is_absolute():
            raise ValueError("path_must_be_absolute")
        path = expanded.resolve(strict=False)
        # ★ 승인으로도 비밀은 못 연다. 사람이 실수로 눌러도 토큰·키·다른 AI 도구의 기록은 안 나간다.
        if self._sensitive_path(path):
            raise PermissionError(
                "sensitive_path_blocked: 비밀이 든 자리(키·토큰·자격증명·다른 도구의 기록)는 승인으로도 열지 않습니다."
            )
        too_broad = self._too_broad_for_workspace(path)
        if too_broad:
            raise PermissionError(f"path_too_broad: {path} — {too_broad}")
        if mode == "write":
            grade = self._model_grade()
            if not grade["measured"]:
                # ★ 사장님 지시(2026-09-20): 능력을 잰 적 없는 모델이 **스스로 쓰기 자리를 넓히는 것**은 막는다.
                #   경고만으로는 4B 가 승인 카드를 띄우고 사람이 무심코 누르는 일을 막지 못한다. 읽기는 그대로 열린다.
                raise PermissionError(
                    f"model_not_benchmarked: 지금 모델({grade['model']})은 손자리가 능력을 잰 적이 없습니다. "
                    "쓰기 폴더는 모델이 스스로 넓힐 수 없습니다 — 설정 › 권한·안전에서 사람이 직접 추가해 주세요."
                )
        if path not in self._granted[mode]:
            self._granted[mode].append(path)
            self._save_grants()
        return {
            "ok": True,
            "path": str(path),
            "mode": mode,
            "reason": reason,
            "detail": f"{path} 을(를) {'읽고 쓸' if mode == 'write' else '읽을'} 수 있게 열었습니다.",
        }

    def grant_path_by_person(self, raw: str, mode: str = "write") -> Path:
        """**사람이 화면에서 직접** 고르거나 누른 폴더를 허락한다(설정 › 팩의 프로젝트 허락 등, 2026-09-27).

        `request_path_access` 는 **모델이** 넓혀 달라고 할 때의 문이라 「능력을 안 잰 모델은 쓰기를 못 넓힌다」가 걸린다.
        사람이 누른 것은 그 검사가 맞지 않는다 — 대신 비밀 자리·너무 넓은 자리는 똑같이 막는다.
        """
        if mode not in ("read", "write"):
            raise ValueError("mode_must_be_read_or_write")
        expanded = Path(os.path.expandvars(str(raw or "").strip())).expanduser()
        if not str(raw or "").strip() or not expanded.is_absolute():
            raise ValueError("path_must_be_absolute")
        path = expanded.resolve(strict=False)
        if not path.is_dir():
            raise FileNotFoundError(f"folder_not_found: {path}")
        if self._sensitive_path(path):
            raise PermissionError("sensitive_path_blocked: 비밀이 든 자리는 열지 않습니다.")
        too_broad = self._too_broad_for_workspace(path)
        if too_broad:
            raise PermissionError(f"path_too_broad: {path} — {too_broad}")
        if path not in self._granted[mode]:
            self._granted[mode].append(path)
            self._save_grants()
        return path

    def _model_grade(self) -> dict[str, Any]:
        """지금 대화 모델의 **능력 실측** 상태. 메모리 실측(`verified`)과는 다른 칸이다."""
        from .model_catalog import agent_grade

        return agent_grade(self.config.model_for("chat"))

    def _resolve(self, raw: str, *, must_exist: bool = True, write: bool = False) -> Path:
        if not raw.strip():
            raise ValueError("path_required")
        path = Path(os.path.expandvars(raw)).expanduser().resolve(strict=False)
        if not path.exists():
            # ★ 구분자가 빠져 두 폴더 이름이 붙은 경로를 실제 폴더로 나눠 본다(`repair_glued_path`). 허용 범위 검사는 아래에서 그대로.
            repaired = repair_glued_path(path, allow_missing_leaf=not must_exist)
            if repaired is not None:
                path = repaired
            elif must_exist or not path.parent.exists():
                # 같은 폴더 이름이 두 번 겹친 경로 — 실제로 있는 쪽으로(`repair_doubled_folder`). 허용 범위 검사는 아래에서 그대로.
                undoubled = repair_doubled_folder(path, allow_missing_leaf=not must_exist)
                if undoubled is not None:
                    path = undoubled
        scope = self._write_scope() if write else self._read_scope()
        allowed = False
        for root in scope:
            try:
                if os.path.commonpath([str(path).lower(), str(root).lower()]) == str(root).lower():
                    allowed = True
                    break
            except ValueError:
                continue
        if not allowed:
            # ★ 이유만 말하면 모델은 같은 상대 경로를 또 넣는다 (2026-09-16 이어받기 실측).
            #   무엇으로 풀렸는지와 쓸 수 있는 자리를 같이 준다 — 도구가 그 자리에서 말한다.
            roots = " · ".join(str(root) for root in list(scope)[:4])
            # ★ 절대 경로에 「상대 경로는…」을 말하면 틀린 안내다 (2026-09-16 밤 스크린샷:
            #   다른 드라이브의 저장소 절대 경로를 넣었는데 「절대 경로를 주세요」라고 답했다). 상대일 때만 그 말을 한다.
            relative = not Path(os.path.expandvars(raw)).expanduser().is_absolute()
            hint = (
                "상대 경로는 이 프로세스 자리 기준이라 대개 밖으로 나갑니다 — **절대 경로**를 주세요. "
                if relative
                else "이 자리는 허용 목록 밖입니다. "
            )
            # ★ 막기만 하면 모델은 같은 호출을 되풀이한다. **넓히는 길**을 같이 준다 (2026-09-20).
            door = (
                f"여기에 쓰려면 `local_request_path_access`(path='{path.parent}', mode='write') 로 "
                "사장님께 여쭤 보세요 — 승인 카드가 뜹니다."
                if write
                else f"여기를 읽으려면 `local_request_path_access`(path='{path.parent}', mode='read') 로 "
                "사장님께 여쭤 보세요 — 승인 카드가 뜹니다."
            )
            raise PermissionError(
                f"path_outside_allowed_roots: 「{raw}」은 {path} 로 풀렸습니다. "
                f"{hint}{'쓸' if write else '볼'} 수 있는 자리: {roots} | {door}"
            )
        if self._sensitive_path(path):
            raise PermissionError("sensitive_path_blocked")
        if must_exist and not path.exists():
            raise FileNotFoundError(self._not_found_hint(path))
        return path

    #: 못 찾았을 때 같이 실어 보낼 정보의 상한. 도구 오류는 `str(exc)[:500]` 로
    #: 잘려 모델에게 간다(`tool_gateway`). 넘치면 조용히 반쪽만 간다.
    _NOT_FOUND_HINT_CHARS = 430
    _NOT_FOUND_SIBLINGS = 20
    _NOT_FOUND_SEARCH_DEPTH = 3

    def _not_found_hint(self, path: Path) -> str:
        """없는 경로면 **근처에 무엇이 있는지** 같이 준다.

        2026-08-29 라이브: `tools/alture-jarvis/evals` 를 찍었는데 실제 `evals` 는
        저장소 루트에 있었다. 도구는 `path_not_found` 다섯 글자와 `{}` 만 돌려줬고,
        모델은 고칠 근거가 없어 계속 찍었다. **판정은 맞았는데 말을 안 해 준 것이다.**

        경로를 더 열어 주는 것은 답이 아니다 — 없는 경로는 넓혀도 없다. 필요한 것은
        「여기엔 없고 저기 있다」는 사실이고, 그건 우리가 결정론으로 줄 수 있다.
        """
        parts = [f"path_not_found: {path}"]

        # ★ 답이 되는 것을 **앞에** 둔다. 뒤에 뒀더니 500자 상한에서 잘려 나갔다.
        found = self._find_by_name(path.name)
        if found:
            parts.append("같은 이름이 여기 있다: " + ", ".join(found))

        ancestor = path.parent
        while not ancestor.exists() and ancestor.parent != ancestor:
            ancestor = ancestor.parent
        if ancestor.exists() and ancestor.is_dir():
            try:
                entries = [e for e in os.scandir(ancestor) if not e.name.startswith(".")]
            except OSError:
                entries = []
            # 없는 경로를 고칠 때 필요한 것은 대개 **폴더**다. 이름을 잘못 쓴
            # 파일까지 볼 수 있게 파일도 뒤에 붙이되, 폴더를 먼저 채운다.
            dirs = sorted(e.name for e in entries if e.is_dir())
            files = sorted(e.name for e in entries if not e.is_dir())
            names = (dirs + files)[: self._NOT_FOUND_SIBLINGS]
            if names:
                more = len(dirs) + len(files) - len(names)
                tail = f" 외 {more}개" if more > 0 else ""
                parts.append(f"'{ancestor}' 안에는: {', '.join(names)}{tail}")

        return " | ".join(parts)[: self._NOT_FOUND_HINT_CHARS]

    def _find_by_name(self, leaf: str, limit: int = 3) -> list[str]:
        """허용 루트 안에서 같은 이름을 얕게(깊이 3) 찾는다. 못 찾으면 빈 목록."""
        if not leaf:
            return []
        hits: list[str] = []
        for root in self.allowed_roots:
            if not root.is_dir():
                continue
            stack = [(root, 0)]
            while stack and len(hits) < limit:
                current, depth = stack.pop()
                if depth > self._NOT_FOUND_SEARCH_DEPTH:
                    continue
                try:
                    entries = list(os.scandir(current))
                except OSError:
                    continue
                for entry in entries:
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                    # 훑는 값이 없는 자리는 아예 안 들어간다. 산출물·의존성은
                    # 사본이 많아 「같은 이름」이 수십 개로 나온다.
                    if entry.name in _NAME_SEARCH_SKIP_DIRS:
                        continue
                    if entry.name == leaf:
                        hits.append(str(Path(entry.path)))
                        if len(hits) >= limit:
                            break
                    stack.append((Path(entry.path), depth + 1))
        return hits

    def resolve_allowed_path(self, raw: str, *, must_exist: bool = True) -> Path:
        """Public wrapper so other tool collections (Gmail attachments, Naver
        Blog images) can reuse the allowed-root + sensitive-file guard
        without reaching into the private _resolve()."""
        return self._resolve(raw, must_exist=must_exist)

    def resolve_export_path(self, raw: str) -> Path:
        """외부 서비스로 보낼 파일은 넓어진 읽기 범위만으로 선택하지 않는다.

        메일 첨부·Drive 업로드·블로그 이미지는 단순 열람이 아니다. 작업 폴더나
        사람이 쓰기까지 허용한 폴더의 파일만 외부 전송 준비에 쓸 수 있다.
        """
        return self._resolve(raw, must_exist=True, write=True)

    @staticmethod
    def _job_id(arguments: dict[str, Any]) -> str:
        job_id = str(arguments.get("__job_id") or "").strip()
        if job_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError("invalid_job_id")
        return job_id

    def job_workspace(self, job_id: str, *, create: bool = False) -> Path:
        if not job_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError("job_context_required")
        path = (self.workspace_root / job_id).resolve(strict=False)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def admit_code_workspace(self, raw: str) -> Path:
        """사람이 코드 탭에서 **직접 고른** 폴더를 작업 자리로 받는다.

        ## 왜 (2026-09-16 밤, 사용자 스크린샷)

        코드 탭은 「찾아보기」로 아무 폴더나 고르게 해 놓고, 보내는 순간 그 폴더가 허용 목록
        (바탕화면·문서·다운로드) 밖이라며 **요청 전체를 400 으로 거절**했다. 실제 사람 PC 의
        저장소는 대개 `D:/dev`·`E:/...` 에 있다 — 코드 모드가 사실상 안 되는 판이었다.

        고른 것은 사람의 명시적 동작이므로 그 폴더 안은 허락으로 본다. 대신 **너무 넓은 자리**
        (드라이브 통째·홈 통째·시스템·AppData·온텔릭 자기 데이터가 든 자리)는 여전히 막는다 —
        「폴더 하나 골랐더니 PC 전체가 열렸다」가 되면 안 된다. 파일 하나하나의 민감 검사
        (`.env`·키·토큰)는 그대로 걸린다.
        """
        if not str(raw or "").strip():
            raise ValueError("path_required")
        expanded = Path(os.path.expandvars(raw)).expanduser()
        if not expanded.is_absolute():
            raise ValueError("code_workspace_must_be_absolute")
        path = expanded.resolve(strict=False)
        if not path.is_dir():
            raise FileNotFoundError(f"code_workspace_not_found: {path}")
        reason = self._too_broad_for_workspace(path)
        if reason:
            raise PermissionError(f"code_workspace_too_broad: {path} — {reason}")
        if self._sensitive_path(path):
            raise PermissionError("sensitive_path_blocked")
        if not any(self._inside(path, root) for root in self.allowed_roots):
            self.allowed_roots.append(path)
        return path

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            return os.path.commonpath([str(path).lower(), str(root).lower()]) == str(root).lower()
        except ValueError:
            return False

    def _too_broad_for_workspace(self, path: Path) -> str:
        """작업 자리로 받기엔 너무 넓은가. 넓으면 이유를, 아니면 빈 문자열."""
        if path.parent == path:
            return "드라이브 전체는 작업 자리로 받지 않습니다. 저장소 폴더를 골라 주세요."
        home = Path.home().resolve(strict=False)
        if self._inside(home, path):
            return "홈 폴더 전체(또는 그 위)는 받지 않습니다. 저장소 폴더를 골라 주세요."
        system = [os.environ.get(name, "") for name in
                  ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
        for raw in system:
            if raw and self._inside(path, Path(raw).resolve(strict=False)):
                return "시스템·프로그램 폴더는 작업 자리로 받지 않습니다."
        # AppData 는 **그 자체와 바로 아래**(Local·Roaming·LocalLow)만 막는다. 통째로 막으면
        # 그 밑 깊은 곳의 작업 폴더(임시 폴더 등)까지 못 고른다 — 넓은 문만 닫는다.
        appdata = (home / "AppData").resolve(strict=False)
        if path == appdata or path.parent == appdata:
            return "AppData 는 앱들의 설정·토큰이 모인 자리라 통째로 받지 않습니다."
        data_dir = getattr(self.config, "data_dir", None)
        if data_dir is not None and self._inside(Path(data_dir).resolve(strict=False), path):
            return "손자리 자기 데이터(대화·토큰)가 든 폴더는 받지 않습니다."
        return ""

    def authorize_code_workspace(self, job_id: str, raw_root: str) -> Path:
        """API가 검증해 넘긴 선택 폴더를 이 잡의 유일한 무승인 쓰기 루트로 묶는다."""
        if not job_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError("job_context_required")
        # ★ 이 자리는 잡의 **무승인 쓰기 루트**가 된다. 읽기 범위로 풀면 모델이 사용자 폴더 아무 데나
        #   작업 자리로 묶어 쓰기를 얻는다 — 반드시 좁은 쪽으로 (2026-09-20).
        root = self._resolve(raw_root, must_exist=True, write=True)
        if not root.is_dir():
            raise NotADirectoryError("directory_required")
        self._code_workspaces[job_id] = root
        # 멈췄다 다시 도는 판은 이 자리를 또 지난다 — 처음 한 번만 적는다(다시 적으면 그새 만든 폴더가 「원래 있던 것」이 된다).
        if job_id not in self._folders_at_start:
            self._folders_at_start[job_id] = _folders_under(root)
        return root

    def code_workspace(self, job_id: str) -> Path | None:
        """이 잡에 API가 검증해 묶어 준 Code 저장소. 없으면 None."""
        if not job_id:
            return None
        return self._code_workspaces.get(job_id)

    def _mutation_workspace(self, arguments: dict[str, Any], *, create: bool) -> Path:
        job_id = self._job_id(arguments)
        code_root = self._code_workspaces.get(job_id)
        return code_root if code_root is not None else self.job_workspace(job_id, create=create)

    def _resolve_mutation_path(
        self, arguments: dict[str, Any], *, must_exist: bool, allow_folder: bool = False
    ) -> Path:
        raw = str(arguments.get("path") or "").strip()
        if not raw:
            raise ValueError("path_required")
        expanded = Path(os.path.expandvars(raw)).expanduser()
        # ★ **이 판에서 방금 만든 파일**을 이름만으로 부르면 그 파일이다 (2026-09-28 T2 재측정 B3). 워드를 `(4)` 로 만든 뒤
        #   `회의록_20260928 (4).docx` 를 고치라고 불렀는데 작업 폴더에서 찾아 `path_not_found` — 5걸음을 돌아 `_최종` 을 또 만들었다.
        if not expanded.is_absolute() and len(expanded.parts) == 1:
            for made in self._made_by_job.get(self._job_id(arguments), ()):
                if Path(made).name.lower() == expanded.name.lower():
                    expanded = Path(made)
                    break
        if not expanded.is_absolute():
            workspace = self._mutation_workspace(arguments, create=True)
            # ★ 상대 경로가 **작업 폴더 자기 이름으로 시작하면** 그 이름을 뗀다 (2026-09-22, 노트북 4B `fin2`).
            #   `L1_hello_page-r2/index.html` 처럼 쓰면 작업 폴더 안에 같은 이름의 하위 폴더가 생겨 파일이 엉뚱한 곳에 간다
            #   (그 판은 `index.html 없음`으로 졌다). 같은 이름의 폴더가 **이미 있으면** 진짜 하위 폴더이니 건드리지 않는다.
            parts = expanded.parts
            if len(parts) > 1 and parts[0] == workspace.name and not (workspace / parts[0]).exists():
                expanded = Path(*parts[1:])
            # ★ 「바탕화면/회의 메모.txt」의 바탕화면은 **사람의 바탕화면**이다 (2026-09-23 스토어 촬영).
            #   예전엔 작업 폴더 안에 「바탕화면」이라는 새 폴더를 만들고 거기 썼다 — 승인도 안 거쳤고, 사람은
            #   「바탕화면에 만들었습니다」를 듣고도 바탕화면에서 파일을 못 찾는다. 첫 칸이 사용자 폴더 이름이고
            #   작업 폴더에 그런 하위 폴더가 **없을 때만** 실제 폴더로 푼다 — 그러면 작업 폴더 밖이라 아래
            #   `_resolve(write=True)` 가 승인 자리로 보낸다(몰래 넓히지 않는다).
            user_folder = _USER_FOLDER_ALIASES.get(parts[0].casefold()) if len(parts) > 1 else None
            if user_folder and not (workspace / parts[0]).exists():
                expanded = Path.home() / user_folder / Path(*parts[1:])
            else:
                expanded = workspace / expanded
        # ★ 쓰기는 **좁은 쪽**으로 푼다 (2026-09-20). 읽기 범위가 사용자 폴더 전체로 넓어졌어도
        #   고치고 지우는 것은 작업 폴더와 사람이 승인한 자리 안에서만.
        path = self._resolve(str(expanded), must_exist=must_exist, write=True)
        if path.exists() and not path.is_file() and not (allow_folder and path.is_dir()):
            raise IsADirectoryError("file_required")
        return path

    def _resolve_workspace_path(
        self,
        arguments: dict[str, Any],
        *,
        key: str = "path",
        must_exist: bool = True,
        write: bool = False,
    ) -> Path:
        """선택 저장소의 상대경로를 읽기·목록·검증에서도 같은 기준으로 푼다.

        코드 인덱스는 의도적으로 ``src/app.py`` 같은 짧은 상대경로를 돌려준다.
        예전 읽기 도구는 그 값을 프로세스 CWD 기준으로 해석해, 올바른 인덱스
        결과가 ``path_outside_allowed_roots`` 로 막혔다. 쓰기만 알고 있던 job별
        저장소 루트를 모든 로컬 코드 작업이 공유해야 읽기→패치 폐루프가 닫힌다.
        """
        raw = str(arguments.get(key) or "").strip()
        if not raw:
            raise ValueError("path_required")
        expanded = Path(os.path.expandvars(raw)).expanduser()
        if not expanded.is_absolute():
            job_id = self._job_id(arguments)
            code_root = self._code_workspaces.get(job_id)
            if code_root is not None:
                expanded = code_root / expanded
            elif job_id:
                # ★ 2026-09-30 QR 판: 고른 저장소가 없는 판에서 `create_qr.py` 를 읽자 **백엔드 폴더**
                #   (백엔드 설치 폴더\create_qr.py)로 풀려 「없다」가 났다. 쓰기는 이미 잡 책상 기준인데
                #   읽기만 프로세스 자리 기준이었다 — 사용자에게 뜻 없는 자리다. 이 판이 만든 같은 이름이 있으면 그것,
                #   아니면 잡 책상 기준으로 푼다(쓰기 `_resolve_mutation_path` 와 같은 규칙).
                made = next((Path(p) for p in self._made_by_job.get(job_id, ())
                             if len(expanded.parts) == 1 and Path(p).name.lower() == expanded.name.lower()), None)
                expanded = made if made is not None else self.job_workspace(job_id) / expanded
        return self._resolve(str(expanded), must_exist=must_exist, write=write)

    #: 판이 끝나면 띄울 것. 잡 하나에 하나만 — 창 폭탄을 만들지 않는다.
    #
    # 왜 여기 모아 두나: 문서를 만드는 **도중에** 띄우면 한글·엑셀이 그 파일을
    # 붙잡아 다음 걸음이 Access Denied 로 죽는다(2026-09-01 라이브). 만드는 동안은
    # 아무도 안 붙잡고 있어야 자비스가 자기 결과물을 고칠 수 있다.
    def remember_to_open(self, job_id: str, path: Path) -> None:
        key = str(job_id or "")
        if not key:
            # ★ 잡이 없으면 **안 띄운다** (2026-09-01 저녁, 두 번째 교정).
            #
            #   처음엔 "미룰 자리가 없으니 바로 띄운다"로 뒀다. 그랬더니 라이브
            #   상자 **검사**가 `성적표.csv` 를 만들자마자 엑셀을 띄웠고 회귀가
            #   통째로 멎었다. 검사가 사람 화면에 창을 띄우면 그건 검사가 아니다.
            #
            #   잡이 없다는 것은 띄워 줄 사람도 없다는 뜻이다(검사·MCP 직접 호출).
            #   경로는 결과에 이미 들어 있으니 부른 쪽이 알아서 연다.
            return
        self._pending_opens[key] = path

    def open_pending(self, job_id: str) -> str:
        """판이 끝났다. **마지막으로 만든 것 하나**를 띄운다.

        돌려주는 값은 무슨 일이 있었는지다 — `opened` / `open_failed:…` / `""`.
        못 열어도 파일은 남았다. **실패를 만들기 실패로 바꾸지 않는다.**
        """
        path = self._pending_opens.pop(str(job_id or ""), None)
        if path is None:
            return ""
        return self._open_now(path)

    def discard_pending(self, job_id: str) -> None:
        """띄우지 않고 **적어 둔 것만 비운다.** 부른 쪽이 창을 원하지 않는다."""
        self._pending_opens.pop(str(job_id or ""), None)

    # ★ **달라고 한 자리로 보낸다** (2026-09-30 워드클라우드 판).
    #
    #   「바탕화면에 sonjari_wordcloud.png 로 저장해 줘」에 상자가 PNG 를 제대로 만들고, 파일은 잡 작업 폴더
    #   (`outputs/workspace/<잡>/`)에 떨어졌다. 모델은 「바탕화면에 두고 싶으시면 복사해서 붙여넣으세요」로
    #   **일을 사람에게 되돌렸다.** 상자는 격리가 핵심이라 자리를 스스로 못 고르고, 이미지를 옮길 도구도 없다.
    #   안내문은 안 먹는다(사고 R) — 사람이 자리와 이름을 **둘 다** 댄 경우에만, 같은 이름이 나오면 코드가 보낸다.
    #   쓰기 범위는 넓히지 않는다(`_resolve(write=True)`). 있던 파일은 덮지 않는다 — 되돌리기가 만든 것만 지운다.
    def expect_delivery(self, job_id: str, path: Path) -> None:
        if job_id:
            self._deliveries[str(job_id)] = Path(path)

    def forget_delivery(self, job_id: str) -> None:
        self._deliveries.pop(str(job_id or ""), None)

    def delivery_for(self, job_id: str, name: str) -> Path | None:
        """이 잡이 이 이름의 파일을 **어디로** 보내야 하나. 이름이 다르면 None — 추측하지 않는다."""
        wanted = self._deliveries.get(str(job_id or ""))
        if wanted is None or Path(name).name.casefold() != wanted.name.casefold():
            return None
        return wanted

    def deliver_bytes(self, job_id: str, path: Path, raw: bytes) -> dict[str, Any]:
        """달라고 한 자리에 쓴다. **이 판이 안 만든** 같은 이름이 있으면 덮지 않고 옆 이름으로(`write_document_file` 과 같은 규칙)."""
        target = self._resolve(str(path), must_exist=False, write=True)
        job = str(job_id or "")
        made = self._made_by_job.setdefault(job, set())
        kept_theirs = ""
        if target.exists() and str(target).lower() not in made and target.read_bytes() != raw:
            spare = _unused_sibling(target)
            kept_theirs = f"「{target.name}」이 이미 있어서 덮지 않고 「{spare.name}」로 새로 만들었습니다(원래 파일은 그대로입니다)."
            target = spare
        target.parent.mkdir(parents=True, exist_ok=True)
        result = self._commit_bytes(target, raw, job_id=job, action="deliver")
        made.add(str(target).lower())
        if kept_theirs:
            result["renamed_because_exists"] = kept_theirs
        return result

    def _open_now(self, path: Path) -> str:
        try:
            # 여는 것은 탐색기·워드 같은 **밖의 앱**이다. 스토어판에서 우리가 보는 앱 데이터 경로는
            # 가상화된 보기라, 그대로 넘기면 밖의 앱은 그 자리에서 아무것도 못 찾는다(2026-09-18).
            from .file_open import open_file
            from .msix import external_path

            # 여는 프로그램이 없는 PC(새 윈도우의 `.md`)에서 오류 창이 뜨지 않게 한 곳에서 연다(`file_open`).
            open_file(external_path(path))
            return "opened"
        except Exception as exc:
            return f"open_failed:{type(exc).__name__}"

    @property
    def documents_root(self) -> Path:
        """사람이 **찾을 수 있는** 곳. 잡별 UUID 폴더가 아니다.

        ★ 2026-09-01 라이브. HWPX 를 11,410바이트로 제대로 만들어 놓고 답에는
        파일명만 적었다. 실제 파일은

            outputs/workspace/764b7920-2d0f-4ab2-afdf-a77fd7793d8c/다른 사용자_이력서.hwpx

        안에 있었다. **만든 것을 사람이 못 찾으면 안 만든 것과 같다.**

        잡별 폴더는 중간 산출물에는 맞다 — 판이 끝나면 치울 것들이니까. 그런데
        사람이 달라고 한 문서는 **결과물**이라 자리가 달라야 한다. 「내 문서\\JARVIS」
        는 탐색기에서 바로 보이고, 이미 읽기 허용 루트 안이라 다음 턴에 다시 읽을
        수도 있다.
        """
        root = Path(getattr(self.config, "documents_dir", None) or documents_product_dir(Path.home() / "Documents"))
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _inside_documents_root(self, path: Path) -> bool:
        try:
            root = str(self.documents_root).lower()
            return os.path.commonpath([str(path).lower(), root]) == root
        except (ValueError, OSError):
            return False

    def _inside_current_workspace(self, path: Path, arguments: dict[str, Any]) -> bool:
        try:
            root = self._mutation_workspace(arguments, create=False)
            return os.path.commonpath([str(path).lower(), str(root).lower()]) == str(root).lower()
        except (ValueError, OSError):
            return False

    def _mutation_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        try:
            path = self._resolve_mutation_path(arguments, must_exist=False)
        except Exception:
            # 모르는 경로는 승인 앞으로 보낸 뒤 핸들러가 정확한 오류를 말한다.
            return RiskLevel.L2
        if self._inside_current_workspace(path, arguments) or self._inside_documents_root(path):
            # 「내 문서\\JARVIS」 는 자비스가 결과물을 두는 자기 폴더다. 사람의 다른
            # 문서를 건드리는 것과 같은 무게로 승인을 받게 하면, 문서 한 장 만들
            # 때마다 사람을 부른다. 되돌리기(백업)는 그대로 붙는다.
            return RiskLevel.L1
        return RiskLevel.L2

    #: 저장소가 **이미 선언한 것**을 재현하는 설치. 승인 없이 돈다.
    _DECLARED_INSTALL = frozenset({"-r", "--requirement", "ci"})

    def _install_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """설치는 **인자로** 갈린다 (2026-09-01).

        폴더 경계로는 못 막는 일이다 — 설치는 네트워크에서 코드를 끌어와 그 설치
        스크립트까지 돌린다. 그래서 「어디서 도느냐」가 아니라 **무엇을 가져오느냐**로
        가른다:

            pip install -r requirements.txt / npm ci
                저장소에 이미 적혀 있는 것을 재현한다 → L1, 승인 없음
            pip install requests / npm install lodash
                새로 끌어온다 → L2, 사람이 본다

        설치가 아닌 명령(테스트·빌드·조회)은 원래대로 L1 이다.
        """
        # ★ 글자 한 줄도 **목록과 똑같이** 본다 (2026-09-26). 09-20 에 글자 명령을 받아 주면서 여기는 목록만 봤다 —
        #   `"python -m pip install requests"` 가 L1 로 떨어져 **승인 없이** 새 패키지를 끌어올 수 있었다.
        try:
            parts = self._split_command(arguments.get("command"))
        except ValueError:
            return RiskLevel.L2
        if not parts:
            return RiskLevel.L1
        program = Path(parts[0]).name.lower().removesuffix(".exe").removesuffix(".cmd")
        rest = parts[1:]
        npm_installing = program in {"npm", "pnpm", "yarn"} and bool(rest) and rest[0] in {"install", "ci"}
        pip_installing = program in {"python", "py"} and rest[:3] == ["-m", "pip", "install"]
        if not (npm_installing or pip_installing):
            return RiskLevel.L1
        if npm_installing:
            # `npm install` 을 인자 없이 부르면 package.json 그대로다 — 그것도 선언된 것.
            if rest[0] == "ci" or len(rest) == 1:
                return RiskLevel.L1
            return RiskLevel.L2
        try:
            root: Path | None = Path(
                self._resolve_workspace_path(arguments, write=True) if str(arguments.get("path") or "").strip()
                else self._mutation_workspace(arguments, create=False)
            )
        except Exception:
            root = None          # 자리를 모르면 선언 목록을 못 본다 → 이름을 댄 설치는 사람이 본다
        install = project_env.PipInstall(rest[3:], root or Path.cwd())
        if install.forbidden:
            return RiskLevel.L2          # 어차피 실행에서 막힌다 — 판정이 먼저 느슨해지지 않게
        if install.names and (root is None or install.undeclared(project_env.declared_packages(root))):
            # 프로젝트가 적어 둔 적 없는 이름 → 사람이 본다
            return RiskLevel.L2
        if install.names or install.requirement_files or install.local_self:
            return RiskLevel.L1
        return RiskLevel.L2

    @staticmethod
    def _split_command(raw: Any) -> list[str]:
        """글자 한 줄이든 목록이든 **같은 조각**으로. 판정과 실행이 다른 모양을 보면 안 된다."""
        if isinstance(raw, str):
            import shlex

            return shlex.split(raw, posix=True)
        if isinstance(raw, list):
            return [str(part) for part in raw]
        return []

    def _delete_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """Only a selected Code repository gets autonomous cleanup.

        Ordinary workspace/file deletion keeps the historical L2 approval.
        Code mode has an explicit, API-validated root and deletion is backed up,
        which lets an agent remove its temporary probes without interrupting the
        patch loop.
        """
        job_id = self._job_id(arguments)
        code_root = self._code_workspaces.get(job_id)
        if code_root is None:
            return RiskLevel.L2
        try:
            # 폴더도 같은 잣대다 — 무엇을 지워도 되는지는 `_folder_deletable` 이 가른다(이 작업이 만든 것·캐시만).
            path = self._resolve_mutation_path(arguments, must_exist=False, allow_folder=True)
            inside = os.path.commonpath(
                [str(path).lower(), str(code_root).lower()]
            ) == str(code_root).lower()
        except (OSError, ValueError):
            return RiskLevel.L2
        return RiskLevel.L1 if inside else RiskLevel.L2

    @staticmethod
    def _sha256_bytes(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _sha256_file(cls, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _file_state(self, path: Path) -> dict[str, Any]:
        exists = path.is_file()
        return {
            "path": str(path),
            "exists": exists,
            "bytes": path.stat().st_size if exists else 0,
            "sha256": self._sha256_file(path) if exists else "",
        }

    def _capture_file_proof(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_mutation_path(arguments, must_exist=False, allow_folder=True)
        state = self._file_state(path)
        state["fingerprint"] = hashlib.sha256(
            json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return state

    @staticmethod
    def _finalize_file_proof(before: dict[str, Any], result: Any) -> dict[str, Any]:
        out = dict(result) if isinstance(result, dict) else {"value": result}
        out["verified"] = out.get("verified") is True
        out["proof"] = {
            "before": dict(before),
            "after": {
                "path": str(out.get("path") or ""),
                "exists": out.get("exists"),
                "bytes": out.get("bytes"),
                "sha256": str(out.get("sha256") or ""),
                "verified": out["verified"],
            },
        }
        return out

    def _backup(self, path: Path, job_id: str) -> tuple[bool, Path | None, str]:
        existed = path.is_file()
        if not existed:
            return False, None, ""
        raw = path.read_bytes()
        backup_dir = self.backup_root / (job_id or "manual")
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{secrets.token_hex(8)}-{path.name}.bak"
        backup.write_bytes(raw)
        return True, backup, self._sha256_bytes(raw)

    @staticmethod
    def _atomic_write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.jarvis-{secrets.token_hex(6)}.tmp")
        try:
            temporary.write_bytes(raw)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _commit_bytes(
        self, path: Path, raw: bytes, *, job_id: str, action: str
    ) -> dict[str, Any]:
        if len(raw) > self.config.local_file_max_bytes:
            raise ValueError("file_too_large")
        before = path.read_bytes() if path.is_file() else None
        if before == raw:
            state = self._file_state(path)
            return {
                "action": action, **state, "exists": True, "changed": False,
                "duplicate_commit": True, "verified": True,
            }
        existed, backup, before_sha = self._backup(path, job_id)
        self._atomic_write(path, raw)
        state = self._file_state(path)
        expected_sha = self._sha256_bytes(raw)
        verified = state["exists"] and state["sha256"] == expected_sha
        return {
            "action": action,
            **state,
            "changed": True,
            "created": not existed,
            "verified": verified,
            "undo_handle": {
                "path": str(path),
                "existed": existed,
                "backup_path": str(backup) if backup else "",
                "before_sha256": before_sha,
                "after_exists": True,
                "after_sha256": state["sha256"],
            },
        }

    @staticmethod
    def _decode_edit_text(raw: bytes) -> tuple[str, str]:
        # utf-8-sig 는 BOM이 없는 UTF-8도 읽는다. 그걸 먼저 시도한 뒤 같은
        # 이름으로 다시 인코딩하면 없던 BOM이 생긴다 — 내용은 같아 보여도 원본
        # 바이트와 빌드 도구 동작이 달라진다. BOM은 실제로 있을 때만 보존한다.
        encodings = (
            ("utf-8-sig", "utf-8", "cp949", "euc-kr")
            if raw.startswith(b"\xef\xbb\xbf")
            else ("utf-8", "cp949", "euc-kr")
        )
        for encoding in encodings:
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise UnicodeError("text_encoding_not_supported")

    def write_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        arguments = _with_aliases(arguments)
        path = self._resolve_mutation_path(arguments, must_exist=False)
        content = str(arguments.get("content") or "")
        return self._commit_bytes(
            path, content.encode("utf-8"), job_id=self._job_id(arguments), action="local_write_file"
        )

    def apply_edit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        arguments = _with_aliases(arguments)
        path = self._resolve_mutation_path(arguments, must_exist=True)
        raw = path.read_bytes()
        text, encoding = self._decode_edit_text(raw)
        old = str(arguments.get("old") or "")
        new = str(arguments.get("new") or "")
        if not old:
            # ★ 거절은 **갈 곳을 같이 댄다** (2026-09-21 재측정: 이걸로 두 걸음을 버렸다).
            #   인자 이름만 던지면 모델은 같은 자리에서 다시 튕긴다 — 오늘 세 번째 자리다.
            raise ValueError(
                "old_required — `old` 에 **파일에 지금 있는 글자 그대로**를 넣고 `new` 에 바꿀 글자를 넣어라. "
                '예: {"path": "index.html", "old": "<h1>옛 제목</h1>", "new": "<h1>새 제목</h1>"} · '
                "고칠 자리를 모르면 local_read_text_file 로 그 줄을 먼저 읽어라. "
                "파일을 통째로 새로 쓰는 것이면 local_write_file 을 써라."
            )
        occurrences = text.count(old)
        healed_by = ""
        if occurrences == 0:
            # ★ 완전일치가 안 되면 **한 칸씩 내려가 본다** (2026-09-05).
            #   내려가도 못 찾으면, 최소한 **어디가 가까운지는 말해 준다.**
            wanted = old
            old, healed_by = _heal_old_text(text, old)
            occurrences = text.count(old) if old else 0
            if occurrences == 0:
                # 들여쓰기·빈 줄 수·따옴표 이스케이프만 어긋난 것 — 작은 모델이 흔히 낸다(`_rescue_edit`).
                # 정찰기(모델 호출) 앞에 둔다: 결정론이고 공짜다.
                rescued_old, rescued_new, rescued_by = _rescue_edit(text, wanted, new)
                if rescued_old and text.count(rescued_old) == 1:
                    old, new, healed_by = rescued_old, rescued_new, rescued_by
                    occurrences = 1
            if occurrences == 0:
                # 4칸 — 정찰기. 공짜 칸이 다 실패했을 때만 온다.
                #
                # 실측: 이 실패 107 건 중 39% 는 **끝내 못 고쳤고**, 고친 것도 주
                # 모델 왕복 중앙 2 회(≈20초)를 더 썼다. 정찰기는 1~2 초다.
                # 틀리면 아래에서 글자로 걸러져 예전 실패로 떨어지므로 **느려질
                # 수 있는 최악이 1~2 초**다.
                healed = scout_find_anchor(text, wanted, config=self.config)
                if healed and text.count(healed) == 1:
                    old, healed_by = healed, "scout"
                    occurrences = 1
                else:
                    old = wanted
        if occurrences == 0:
            raise ValueError(_old_text_not_found_message(text, str(arguments.get("old") or "")))
        if occurrences > 1:
            raise ValueError(f"old_text_not_unique:{occurrences}")
        edited = text.replace(old, new, 1).encode(encoding)
        result = self._commit_bytes(
            path, edited, job_id=self._job_id(arguments), action="local_apply_edit"
        )
        result["replacements"] = 1
        result["encoding"] = encoding
        # 치유해서 고쳤으면 **그렇다고 적는다.** 조용히 고치면 모델은 자기가 준
        # 글자가 맞았다고 배우고, 다음에도 같은 모양으로 어긋난 것을 보내온다.
        if healed_by:
            result["healed"] = healed_by
        result["edit_preview"] = _edit_preview(text, old, new)
        return result

    def delete_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_mutation_path(arguments, must_exist=True, allow_folder=True)
        if path.is_dir():
            return self._delete_folder(path, arguments)
        existed, backup, before_sha = self._backup(path, self._job_id(arguments))
        if not existed or backup is None:
            raise FileNotFoundError("path_not_found")
        path.unlink()
        verified = not path.exists()
        return {
            "action": "local_delete_file",
            "path": str(path),
            "exists": False,
            "bytes": 0,
            "sha256": "",
            "deleted": True,
            "verified": verified,
            "undo_handle": {
                "path": str(path),
                "existed": True,
                "backup_path": str(backup),
                "before_sha256": before_sha,
                "after_exists": False,
                "after_sha256": "",
            },
        }

    def _delete_folder(self, path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
        """폴더 지우기 — **이 판이 만든 폴더**와 다시 생기는 캐시 폴더만. 되돌릴 수 없어서 좁다.

        ## 왜 (2026-10-04 대표 결정)

        코드 판의 검토가 `npm install` 을 돌려 `node_modules` 가 생겼다. 모델은 치우려 했지만 손이 없었다(파일 지우기는
        폴더를 안 받고, 셸의 `rm -rf` 는 막혀 있다). 사용자 저장소에 판이 만든 군더더기가 남았다.

        ## 왜 좁은가

        파일 지우기는 백업을 떠서 되돌릴 수 있다. 폴더(수만 개 파일)는 그렇게 못 한다 — **되돌릴 수 없는 삭제**다.
        그래서 잃을 것이 없는 것만 받는다:

        - 고른 코드 작업 폴더 **안**(그 폴더 자체는 아니다).
        - 판이 시작될 때 **없던** 폴더(이 판이 만들었다), 또는 다시 생기는 캐시(`__pycache__` 등).
        - `.git` 이거나 `.git` 을 품은 폴더, 링크(다른 곳을 가리키는 폴더)는 안 지운다.

        원래 있던 폴더(전부터 있던 `node_modules` 포함)는 거절하고 사람에게 묻게 한다.
        """
        target, why = self._folder_deletable(path, arguments)
        files = size = 0
        for folder, _dirs, names in os.walk(target):
            for name in names:
                files += 1
                try:
                    size += os.path.getsize(os.path.join(folder, name))
                except OSError:
                    pass
        shutil.rmtree(target, onerror=_retry_writable)
        verified = not target.exists()
        return {
            "action": "local_delete_file",
            "path": str(target),
            "folder": True,
            "exists": target.exists(),
            "deleted": verified,
            "verified": verified,
            "files_removed": files,
            "bytes_removed": size,
            "why_allowed": why,
            "note": "폴더를 지웠다. 폴더 삭제는 되돌릴 수 없다(백업 없음).",
        }

    def _folder_deletable(self, path: Path, arguments: dict[str, Any]) -> tuple[Path, str]:
        """이 폴더를 지워도 되는가. 되면 (실제 경로, 까닭), 안 되면 까닭을 적어 거절한다. **아무것도 지우지 않는다.**"""
        job_id = self._job_id(arguments)
        root = self._code_workspaces.get(job_id)
        if root is None:
            raise PermissionError(
                "folder_delete_only_in_code_workspace — 폴더는 코드 작업 폴더 안에서만, 이 작업이 만든 것만 지운다. "
                "파일 하나를 지우려면 그 파일의 경로를 주어라."
            )
        root = root.resolve(strict=False)
        target = path.resolve(strict=False)
        if target == root or not self._inside(target, root):
            raise PermissionError("folder_delete_outside_workspace — 작업 폴더 자체나 그 밖의 폴더는 지우지 않는다.")
        if _is_link(path):
            raise PermissionError("folder_is_a_link — 다른 곳을 가리키는 폴더(링크)는 지우지 않는다.")
        relative = target.relative_to(root).as_posix()
        if ".git" in target.relative_to(root).parts or (target / ".git").exists():
            raise PermissionError("folder_holds_git_history — .git 이거나 .git 을 품은 폴더는 지우지 않는다.")
        existed = self._folders_at_start.get(job_id)
        key = relative.casefold()
        parts = key.split("/")
        # 훑지 않은 폴더(원래 있던 node_modules 등)의 **안쪽**은 적어 둔 것이 없다 — 「없던 폴더」라고 할 수 없다.
        under_unscanned = any(
            parts[index - 1] in _HEAVY_FOLDERS_FOLDED and "/".join(parts[:index]) in existed
            for index in range(1, len(parts))
        ) if existed is not None else True
        made_here = existed is not None and key not in existed and not under_unscanned
        cache = target.name in _REGENERATED_FOLDERS
        if not (made_here or cache):
            raise PermissionError(
                f"folder_existed_before_this_job:{relative} — 이 작업이 만든 폴더가 아니다. 폴더는 되돌릴 수 없어서 "
                "원래 있던 것은 지우지 않는다. 꼭 지워야 하면 ask_user 로 사람에게 물어라."
            )
        return target, ("made_by_this_job" if made_here else "regenerated_cache")

    def _delete_pre_check(self, arguments: dict[str, Any]) -> None:
        """지우기의 승인 전 검사 — 안 될 폴더면 **카드를 띄우기 전에** 거절한다(실패가 정해진 일을 사람에게 묻지 않는다)."""
        _require_path(arguments)
        try:
            path = self._resolve_mutation_path(arguments, must_exist=False, allow_folder=True)
        except Exception:  # noqa: BLE001 — 경로를 못 풀면 여기서 판단하지 않는다(실행 때 그 까닭이 나온다)
            return
        if path.is_dir():
            self._folder_deletable(path, arguments)

    @staticmethod
    def _undo_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        handle = result.get("undo_handle")
        return dict(handle) if isinstance(handle, dict) and result.get("verified") is True else None

    def _undo_mutation(self, handle: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(str(handle.get("path") or ""), must_exist=False)
        current = self._file_state(path)
        expected_exists = bool(handle.get("after_exists"))
        expected_sha = str(handle.get("after_sha256") or "")
        if current["exists"] != expected_exists:
            raise RuntimeError("undo_target_drifted")
        if expected_exists and current["sha256"] != expected_sha:
            raise RuntimeError("undo_target_drifted")
        if bool(handle.get("existed")):
            backup = Path(str(handle.get("backup_path") or ""))
            if not backup.is_file():
                raise FileNotFoundError("undo_backup_missing")
            self._atomic_write(path, backup.read_bytes())
            restored = self._file_state(path)
            if restored["sha256"] != str(handle.get("before_sha256") or ""):
                raise RuntimeError("undo_restore_unverified")
        else:
            path.unlink(missing_ok=True)
            restored = self._file_state(path)
            if restored["exists"]:
                raise RuntimeError("undo_delete_unverified")
        return {"path": str(path), "verified": True, **restored}

    @staticmethod
    def _validated_project_command(
        raw: Any, *, root: "Path | None" = None
    ) -> tuple[list[str], list[str]]:
        # ★ 글자 하나로 줘도 받는다 (2026-09-20). 도구 설명이 `python -m ruff check .` 처럼
        #   보이니 모델은 그 모양 그대로 보낸다 — 한 판에서 `command_array_required` 에
        #   **일곱 번** 부딪쳐 걸음을 버렸다. 안내문으로 고칠 일이 아니라 받아 줄 일이다(사고 R).
        #
        #   ★ 받아 준다고 느슨해지지 않는다. 쪼갠 뒤 **아래 관문을 똑같이** 지난다 —
        #   프로그램 허용 목록·인자 검사·셸 메타문자 차단. 쪼개는 일을 우리가 할 뿐이다.
        # ★ 대괄호로 두른 글자 하나도 목록으로 푼다 (2026-10-01 밤 Ornith 1.5 35B 코딩 사다리 L3). 배열을 글자로 바꿔
        #   `"[python -m pytest -q]"`·`"[python, -m, pytest]"` 처럼 보냈고, 첫 낱말이 `[python` 이 되어 세 번 거절된 뒤
        #   모델이 웹으로 방법을 찾으러 나갔다(코드는 이미 맞게 고친 판이 「확인 안 함」으로 실패). 모델마다 인자 모양이 다르다.
        if isinstance(raw, str) and raw.strip().startswith("[") and raw.strip().endswith("]"):
            inner = raw.strip()
            try:
                decoded = json.loads(inner)
            except ValueError:
                decoded = None
            if isinstance(decoded, list):
                raw = decoded
            elif "," in inner:
                raw = [part.strip().strip("'\"") for part in inner[1:-1].split(",") if part.strip().strip("'\"")]
            else:
                raw = inner[1:-1]
        # ★ 명령 전체를 **목록 한 칸에** 넣어 보낸 것도 푼다 (2026-10-04 사다리 L6 기준선, Ornith 1.5 35B).
        #   `["python -m pytest -q"]` — 첫 낱말이 `python -m pytest -q` 가 되어 「정해진 명령이 아니다 · 셸로 돌려라」로 네 번
        #   거절됐다. 모델은 시킨 대로 셸로 pytest 를 돌려 통과시켰는데, 셸 실행은 검증으로 안 쳐서 **맞게 고친 판이
        #   `coding_verification_missing` 실패(125초)** 로 끝났다. 위의 대괄호 글자와 같은 가족이다 — 쪼갠 뒤 아래 관문은 그대로 지난다.
        #   진짜 파일 경로(빈칸 든 폴더)는 건드리지 않는다.
        if (
            isinstance(raw, list)
            and len(raw) == 1
            and isinstance(raw[0], str)
            and re.search(r"\s", raw[0].strip())
            and not Path(raw[0].strip().strip("'\"")).exists()
        ):
            raw = raw[0].strip()
        if isinstance(raw, str):
            import shlex

            try:
                raw = shlex.split(raw, posix=True)
            except ValueError as exc:                      # 닫히지 않은 따옴표
                raise ValueError(f"command_quotes_unbalanced: {exc}") from exc
        if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
            raise ValueError("command_array_required")
        command = [str(part) for part in raw]
        # ★ 도구 설명 표의 **분류 이름을 명령에 베껴 온 것**은 떼고 받는다 (2026-09-30 코드 벤치 — `['js', 'node', 'test.js']`·
        #   `script python …` 로 두 번 막혔다). 설명이 「tests python -m pytest」처럼 이름표를 앞에 두니 모델이 그 줄을 통째로 보낸다.
        #   막지 말고 받아 준다(사고 R) — 뗀 뒤에도 아래 관문을 똑같이 지난다. 진짜 프로그램 이름(git 등)은 이름표가 아니다.
        if len(command) >= 2 and command[0].lower() in _DESCRIPTION_LABELS:
            command = command[1:]
        bad = next((part for part in command if not part or len(part) > 500 or _SHELL_META.search(part)), None)
        if bad is not None:
            # ★ 코드만 던지면 작은 모델은 **무엇이 걸렸는지·다음에 무엇을 할지** 모른다(4B AURORA: 같은 오류 네 번).
            #   이유를 대고, 갈 곳(파일로 만들어 실행)을 같이 준다. 검사는 그대로다 — 안내만 는다.
            raise ValueError(
                "command_argument_blocked — 인자 `" + (bad[:60] or "(빈 인자)") + "` 에 셸 문자(| & ; < > ` $ ^ 등)가 있거나 "
                "너무 길다. 명령은 한 줄로 주고, 여러 줄 코드나 파이프가 필요하면 `local_write_file` 로 스크립트를 만들어 "
                "`python 스크립트.py` 로 실행해라."
            )

        program = Path(command[0]).name.lower()
        if program.endswith(".exe") or program.endswith(".cmd"):
            program = Path(program).stem.lower()
        # 허용 도구 이름(`ruff`·`mypy` …)도 입구에서 받는다 — 아래에서 우리 파이썬의 `-m` 으로 돌린다. 입구가 따로 막고 있어서
        # 그 분기를 넣고도 노트북에서 `ruff check .` 가 또 `project_command_not_allowed` 였다(2026-09-26, 같은 것을 자르는 두 자리).
        if program not in _PROJECT_COMMANDS and program not in _PYTHON_MODULES:
            # ★ 거절은 갈 곳을 같이 댄다(2026-09-28, 코드 모드 316판 중 이 벽 8번). 이 문은 **정해진 검증 명령**의
            #   문이고, 그 밖의 명령은 `local_run_shell` 이 권한 모드대로(묻거나 바로) 돌린다 — 막힌 게 아니라 문이 다르다.
            raise PermissionError(
                f"project_command_not_allowed — `{program}` 은(는) 시험·빌드용 정해진 명령이 아니다. "
                "다른 명령은 `local_run_shell` 로 돌려라(권한 모드에 따라 바로 돌거나 한 번 묻는다)."
            )

        args = command[1:]
        executable: list[str]
        if program in {"python", "py"}:
            # ★ `-c` 도 연다 (2026-09-01).
            #
            # 위험도가 새로 늘지 않는다 — 바로 아래 `pytest` 가 **이미 임의 코드를
            # 실행한다.** 테스트 파일 하나 쓰고 돌리면 되는 일을, 한 줄로 하는 것만
            # 막고 있었다. 그래서 자비스는 자기 장부(sqlite)도 조회를 못 했고,
            # JSON·수치 분석을 전부 「읽어서 눈으로」 했다.
            #
            # ★ 파일을 지정해 돌리는 것(`python foo.py`)을 **작업 폴더 안에서만** 연다
            #   (2026-09-20). 원래 막은 이유는 「작업 폴더 **밖**의 스크립트를 부를 통로」였고,
            #   그 이유는 경로를 검사하면 그대로 지켜진다. 막혀 있는 동안 어려운 코딩 판은
            #   **재현 스크립트를 짜 놓고 돌릴 수가 없었다** — 그게 제일 큰 막힘이었다.
            #   (`pytest` 가 이미 저장소의 임의 코드를 돌리므로 위험이 새로 늘지 않는다.)
            if args and args[0] == "-c":
                if len(args) < 2:
                    raise PermissionError("python_c_needs_source")
            elif args and not args[0].startswith("-"):
                if root is None:
                    raise PermissionError("python_script_needs_workspace")
                script = Path(os.path.expandvars(args[0])).expanduser()
                if not script.is_absolute():
                    script = root / script
                script = script.resolve(strict=False)
                if not LocalComputerTools._inside(script, Path(root).resolve(strict=False)):
                    raise PermissionError(
                        f"python_script_outside_workspace: {script} — 작업 폴더 안의 스크립트만 돌립니다."
                    )
                if LocalComputerTools._is_sensitive(script):
                    raise PermissionError("sensitive_path_blocked")
                if not script.is_file():
                    raise FileNotFoundError(f"python_script_not_found: {script}")
                args = [str(script), *args[1:]]
            elif len(args) >= 2 and args[0] == "-m" and args[1] == "pip":
                # ★ 설치를 연다 (2026-09-01). 위험도는 **인자로 갈린다** —
                #   `-r requirements.txt` 는 저장소가 이미 선언한 것을 재현하는 일이고,
                #   이름을 직접 대는 것은 인터넷에서 새로 끌어오는 일이다.
                #   그 구분은 `_install_risk` 가 하고, 여기서는 통로만 연다.
                if len(args) < 3 or args[2] not in {"install", "list", "show", "freeze", "check"}:
                    raise PermissionError("pip_subcommand_not_allowed")
                if args[2] == "install":
                    if root is None:
                        raise PermissionError("pip_install_needs_workspace")
                    install = project_env.PipInstall(args[3:], Path(root))
                    if install.forbidden:
                        raise PermissionError(
                            "pip_option_not_allowed: " + ", ".join(install.forbidden)
                            + " — 받는 곳을 바꾸거나 프로젝트 밖에 까는 옵션은 열지 않습니다. 프로젝트 .venv 에만 깝니다."
                        )
                    if install.outside_files:
                        raise PermissionError(
                            "pip_requirement_outside_workspace: " + ", ".join(install.outside_files)
                            + " — 작업 폴더 안의 requirements 파일만 씁니다."
                        )
                    if project_env.venv_dir(Path(root)) is None:
                        # 실행 앞에서 `run_project_command` 가 만든다. 여기 오면 만들기가 실패한 것이다.
                        raise RuntimeError("project_venv_missing — 설치할 프로젝트 가상환경(.venv)을 만들지 못했습니다.")
            elif len(args) < 2 or args[0] != "-m" or args[1] not in _PYTHON_MODULES:
                raise PermissionError(
                    "python_module_not_allowed — 이 문은 시험·린트 모듈(`python -m pytest` 등)만 돈다. "
                    "작업 폴더의 스크립트는 `python 스크립트.py`, 그 밖의 명령은 `local_run_shell` 로 돌려라."
                )
            executable = [LocalComputerTools._project_python(root, None), *args]
        elif program == "pytest" or program in _PYTHON_MODULES:
            # ★ 2026-09-26 노트북 코드 모드 E2E: 모델이 `ruff check .` 처럼 **도구 이름으로** 불렀는데 이 문은 `python -m …` 과
            #   pytest 만 받아 `project_command_not_allowed` 로 막혔다 → 모델이 셸로 돌아가 `python -m ruff` 를 쳤더니 셸의
            #   `python` 이 윈도우 스토어 가짜라 「Python」만 찍고 끝났다. 허용된 도구 이름은 우리 파이썬의 `-m` 으로 돌린다.
            executable = [LocalComputerTools._project_python(root, program), "-m", program, *args]
        elif program == "node":
            # ★ node 도 python 과 같은 문이다 (2026-09-30 코드 벤치). 「node 로 돌리는 test.js 를 만들어 통과시켜」 과제에서
            #   이 문이 node 를 안 받고 상자는 파이썬·bash 뿐이라 **돌릴 길이 아예 없었다** — 모델은 상자 안에서 node 를
            #   찾아 네 걸음을 헤맸다. python 이 이미 임의 코드를 돌리므로 위험이 새로 늘지 않는다. 같은 규칙: 작업 폴더
            #   안의 스크립트만, 버전 확인(`--version`)은 그대로. `-e`(한 줄 코드)는 python `-c` 처럼 연다.
            if args and args[0] in {"-e", "--eval"}:
                if len(args) < 2:
                    raise PermissionError("node_eval_needs_source")
            elif args and args[0] in {"--version", "-v"}:
                pass
            elif args and not args[0].startswith("-"):
                if root is None:
                    raise PermissionError("node_script_needs_workspace")
                script = Path(os.path.expandvars(args[0])).expanduser()
                if not script.is_absolute():
                    script = root / script
                script = script.resolve(strict=False)
                if not LocalComputerTools._inside(script, Path(root).resolve(strict=False)):
                    raise PermissionError(f"node_script_outside_workspace: {script} — 작업 폴더 안의 스크립트만 돌립니다.")
                if LocalComputerTools._is_sensitive(script):
                    raise PermissionError("sensitive_path_blocked")
                if not script.is_file():
                    raise FileNotFoundError(f"node_script_not_found: {script}")
                args = [str(script), *args[1:]]
            else:
                raise PermissionError("node_option_not_allowed — `node 스크립트.js` · `node -e \"코드\"` · `node --version` 만 받는다.")
            resolved = shutil.which("node")
            if not resolved:
                raise FileNotFoundError(
                    "command_not_found:node — 이 PC 에 Node.js 가 없습니다. 사용자에게 설치를 부탁하거나, 계산 검증은 python 으로 하세요."
                )
            executable = [resolved, *args]
        elif program in {"npm", "pnpm", "yarn"}:
            if not args or args[0] not in _NPM_COMMANDS:
                raise PermissionError("package_command_not_allowed")
            if args[0] == "run" and (
                len(args) < 2
                or not re.fullmatch(r"[A-Za-z0-9:_-]{1,80}", args[1])
                or not _SAFE_PACKAGE_SCRIPT.fullmatch(args[1])
            ):
                raise PermissionError("package_script_not_allowed")
            resolved = shutil.which(program)
            if not resolved:
                raise FileNotFoundError(f"command_not_found:{program}")
            executable = [resolved, *args]
        elif program == "cargo":
            if not args or args[0] not in _CARGO_COMMANDS:
                raise PermissionError("cargo_command_not_allowed")
            if args[0] == "fmt" and "--check" not in args:
                raise PermissionError("cargo_fmt_must_be_check_only")
            resolved = shutil.which("cargo")
            if not resolved:
                raise FileNotFoundError("command_not_found:cargo")
            executable = [resolved, *args]
        else:
            if not args:
                raise PermissionError("git_command_not_read_only")
            if args[0] not in _GIT_COMMANDS:
                if args[0] not in _GIT_WRITE_COMMANDS:
                    raise PermissionError("git_command_not_allowed")
                _check_git_write_args(args)
            elif args[0] == "remote" and not all(
                # `git remote` · `git remote -v` · `git remote show <이름>` 만 읽기다.
                # `add`·`remove`·`set-url`·`rename` 은 저장소가 **어디를 가리키는지**를 바꾼다.
                part in {"-v", "--verbose", "show", "get-url"} or re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", part)
                for part in args[1:]
            ) or (args[0] == "remote" and any(
                part in {"add", "remove", "rm", "set-url", "rename", "prune", "set-head", "update"}
                for part in args[1:]
            )):
                raise PermissionError("git_remote_write_not_allowed")
            resolved = shutil.which("git")
            if not resolved:
                raise FileNotFoundError("command_not_found:git")
            executable = [resolved, *args]
        return command, executable

    @staticmethod
    def _project_python(root: "Path | None", module: "str | None") -> str:
        """이 프로젝트에서 쓸 파이썬. 프로젝트 `.venv` 가 있으면 그것 — 프로젝트 의존성이 거기 있다 (2026-09-26).

        도구 모듈(ruff·mypy…)은 그 가상환경이 **실제로 볼 수 있을 때만** 그리로 보낸다: 자기 칸에 깔렸거나,
        우리가 만든 것처럼 시스템 칸(온텔릭 파이썬)을 같이 보는 경우. 아니면 우리 파이썬으로 — 예전과 같다.
        """
        if root is None:
            return sys.executable
        venv = project_env.venv_dir(Path(root))
        python = project_env.venv_python(venv) if venv is not None else None
        if venv is None or python is None:
            return sys.executable
        if module is None or project_env.venv_has_module(venv, module):
            return str(python)
        try:
            config = (venv / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            config = ""
        if re.search(r"include-system-site-packages\s*=\s*true", config):
            return str(python)
        return sys.executable

    def _ensure_project_venv(self, root: Path, command: Any) -> dict[str, Any] | None:
        """`pip install` 인데 프로젝트 가상환경이 없으면 **먼저 만든다**. 설치는 온텔릭 자기 파이썬에 하지 않는다."""
        try:
            parts = self._split_command(command)
        except ValueError:
            return None
        program = Path(parts[0]).name.lower().removesuffix(".exe") if parts else ""
        if program not in {"python", "py"} or parts[1:4] != ["-m", "pip", "install"]:
            return None
        if project_env.venv_dir(root) is not None:
            return None
        done = subprocess.run(
            project_env.create_venv_command(root), cwd=root, capture_output=True,
            timeout=180, shell=False, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {
            "created": str(root / project_env.VENV_DIRNAMES[0]),
            "exit_code": int(done.returncode),
            "stderr": _decode_output(done.stderr)[-2_000:],
        }

    @staticmethod
    def _current_branch(root: Path) -> str:
        """지금 어느 가지에 서 있나. 못 알아내면 **빈 문자열이 아니라 보호로 친다.**

        모르는 것을 「안전하다」로 읽으면 그게 사고다 — detached HEAD 나 git 이
        없는 폴더에서 커밋이 통과해 버린다.
        """
        try:
            done = subprocess.run(
                [shutil.which("git") or "git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            return "main"
        name = (done.stdout or "").strip()
        return name or "main"

    def check_project_command(self, command: Any, *, root: Path) -> list[str]:
        """이 명령을 프로젝트 명령으로 **돌릴 수 있는가** — 돌리지 않고 문만 지난다. 못 돌리면 그 이유로 예외를 낸다.

        바깥 AI 가 맡기며 준 확인 명령을 **받는 순간** 검사하려고 있다. 가지를 만들고 20분 일한 뒤에 「그 명령은 못 돌린다」가
        나오면 늦다. 모델이 직접 부를 때와 같은 문(`_validated_project_command` · `names_our_own_install`)이다.
        """
        label = project_command_label(command)
        if label:
            command = list(PROJECT_COMMAND_LABELS[label])
        display, _executable = self._validated_project_command(command, root=root)
        own = self.names_our_own_install(" ".join(str(part) for part in display))
        if own:
            raise PermissionError(f"own_install_blocked: {own}")
        return list(display)

    def run_project_command(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # ★ `path` 를 안 줘도 **잡에 묶인 작업 폴더**에서 돈다 (2026-09-20). 안 주면
        #   `path_required` 로 막혔는데, 작업 자리는 이미 잡에 묶여 있어 물어볼 필요가 없다.
        #   같은 날 아침 `local_glob`·`local_grep` 에 넣은 것과 같은 손질이다.
        if not str(arguments.get("path") or "").strip():
            arguments = {**arguments, "path": str(self._mutation_workspace(arguments, create=True))}
        # ★ 명령을 돌리는 것은 읽기가 아니다. 읽기 범위가 넓어져도 **실행은 작업 자리 안에서만** (2026-09-20).
        root = self._resolve_workspace_path(arguments, write=True)
        # ★ 폴더 자리에 **파일**을 주면 그 파일이 든 폴더에서 돌린다 (2026-10-08 사다리 L6 · 64K 창).
        #   모델이 시험 파일 경로를 `path` 에 넣어 `directory_required` 로 세 번 튕겼고, 일반 명령줄로 돌아서 통과시킨 판을
        #   하네스가 「검증 명령을 돌린 적 없다」로 실패 처리했다. 뜻은 분명하다 — 범위 검사는 위에서 그 파일로 이미 지났고
        #   부모 폴더는 그 안쪽이다. 어디서 돌렸는지는 결과에 적는다.
        given_file = root if root.is_file() else None
        if given_file is not None:
            # 부모 폴더도 같은 문(쓰기 범위)을 다시 지난다 — 파일 하나만 허락된 자리에서 폴더로 넓어지지 않게.
            root = self._resolve_workspace_path({**arguments, "path": str(given_file.parent)}, write=True)
        if not root.is_dir():
            raise NotADirectoryError("directory_required")
        # 설명 표의 이름표 하나(`tests`·`lint`…)로 불렀으면 그 줄의 명령으로 푼다 — 표는 `PROJECT_COMMAND_LABELS`.
        label = project_command_label(arguments.get("command"))
        if label:
            arguments = {**arguments, "command": list(PROJECT_COMMAND_LABELS[label])}
        created_venv = self._ensure_project_venv(root, arguments.get("command"))
        display, executable = self._validated_project_command(arguments.get("command"), root=root)
        # ★ 손자리 자신이 깔린 폴더를 가리키는 명령은 돌리지 않는다(`names_our_own_install`). 프로젝트 명령은 파이썬 한 줄처럼
        #   무엇을 하는지 글로 가를 수 없어서, 가리키기만 해도 막는다 — 그 폴더를 **읽는** 일은 읽기 도구로 한다.
        own = self.names_our_own_install(" ".join(str(part) for part in display))
        if own:
            raise PermissionError(
                f"own_install_blocked: {own} 은(는) 손자리 자신이 깔린 폴더라 이 명령으로 건드리지 않습니다. "
                "이 판의 작업 폴더 안의 것을 쓰세요(읽기만 필요하면 읽기 도구로)."
            )
        # ★ main 위에서는 커밋하지 않는다 (2026-09-01).
        #
        # 인자 검사는 "무엇을 하는 명령인가"만 본다. **어디에 커밋하는가**는 그때의
        # HEAD 에 달려 있어서 인자로는 알 수 없다. 그래서 실행 직전에 한 번 더 본다.
        #
        # 이 한 줄이 git 을 열 수 있게 만든 근거다 — 브랜치에만 남기면 잘못돼도
        # **브랜치 하나 지우면 끝**이다. 보호 가지에 직접 커밋하면 그게 무너진다.
        if len(display) >= 2 and display[0] == "git" and display[1] == "commit":
            branch = self._current_branch(root)
            if branch in _GIT_PROTECTED_BRANCHES:
                raise PermissionError(f"git_commit_on_protected_branch:{branch}")
        # 맡긴 쪽이 정한 확인 명령(하네스가 직접 돌린다)은 더 오래 돌 수 있다 — 저장소 전체 시험은 300초를 넘기도 한다.
        timeout_sec = max(5, min(int(arguments.get("timeout_sec") or 120), 900 if arguments.get("__declared_check") else 300))
        # 사용자의 명령에는 손자리 자신의 설정(`JARVIS_*`)을 넘기지 않는다 — `project_env.without_our_settings` 의 설명.
        environment = project_env.with_project_sources_first(
            project_env.with_project_venv_first(
                _with_our_python_first(project_env.without_our_settings(dict(os.environ))), root
            ),
            root,
        )
        environment.update(
            {
                "CI": "1",
                "NO_COLOR": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                # ★ 한글이 깨져서 돌아왔다 (2026-09-20 실측). 윈도우의 파이썬 자식은
                #   stdout 을 **콘솔 코드페이지(cp949)** 로 찍는데 우리는 UTF-8 로 읽었다.
                #   그래서 한국어 시험의 실패 메시지가 통째로 `????` 로 와서, 모델은
                #   무엇이 틀렸는지 읽을 수가 없었다. 자식에게 UTF-8 로 찍으라고 말한다.
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "npm_config_yes": "false",
            }
        )
        started = time.monotonic()
        # ★ 글자로 바로 받지 않고 **바이트로 받아 우리가 읽는다** (2026-09-20).
        #   `PYTHONIOENCODING` 은 파이썬 자식만 고친다 — git·npm·cargo 는 여전히
        #   시스템 코드페이지로 찍는다. 둘 다 읽으려면 여기서 갈라야 한다.
        # ★ 시간 제한에 걸리면 그 아래 프로세스까지 끝내고 돌아온다 (2026-10-08) — 모델이 쓴 코드의 무한 반복 하나에
        #   일꾼이 통째로 멈추지 않게. `run_captured` 의 설명.
        exit_code, stdout, stderr, timed_out, secret_notes = self._run_for_model(
            executable, root=root, environment=environment, timeout_sec=timeout_sec,
        )
        combined = "\n".join(value for value in (stderr, stdout) if value)
        failure_kind = ""
        self_reported_failure = bool(re.search(
            r"(?im)^\s*(?:\[FAIL(?:ED)?\]|FAIL(?:ED)?\s*:|검증\s*실패\b|일부\s*항목\s*실패\b)",
            combined,
        ))
        if exit_code != 0 or timed_out or self_reported_failure:
            lowered = combined.casefold()
            if timed_out:
                failure_kind = "timeout"
            elif self_reported_failure:
                failure_kind = "self_reported_failure"
            elif any(value in lowered for value in ("syntaxerror", "parse error", "ts1005")):
                failure_kind = "syntax"
            elif any(value in lowered for value in ("modulenotfounderror", "importerror", "cannot find module", "collection error")):
                failure_kind = "collection_import"
            elif any(value in lowered for value in ("assertionerror", " failed", "failure", "expected:")):
                failure_kind = "test_assertion"
            elif any(value in lowered for value in ("type error", "typeerror", "mypy", "ts2322", "ts2339")):
                failure_kind = "typecheck"
            elif any(value in lowered for value in ("lint", "ruff", "eslint", "flake8")):
                failure_kind = "lint"
            elif any(value in lowered for value in ("build failed", "compilation failed", "error: could not compile")):
                failure_kind = "build"
            else:
                failure_kind = "unknown"
        normalized = re.sub(r"[A-Za-z]:\\[^\n:]+|/[^\s:]+", "<path>", combined[-8_000:])
        normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "#", normalized)
        failure_fingerprint = (
            hashlib.sha256(f"{failure_kind}\n{normalized}".encode("utf-8")).hexdigest()[:16]
            if failure_kind else ""
        )
        failed_targets: list[str] = []
        for pattern in (
            r"(?:FAILED|ERROR)\s+([^\s:]+(?:::[^\s]+)?)",
            r"File \"([^\"]+)\"",
            r"([^\s]+\.(?:py|ts|tsx|js|jsx|rs|go))(?::\d+)?",
        ):
            for match in re.findall(pattern, combined):
                value = str(match).strip()
                if value and value not in failed_targets:
                    failed_targets.append(value)
                if len(failed_targets) >= 12:
                    break
            if len(failed_targets) >= 12:
                break
        return {
            "action": "local_run_project_command",
            "path": str(root),
            "command": display,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": timed_out,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "verified": exit_code == 0 and not timed_out and not self_reported_failure,
            "failure_kind": failure_kind,
            "failure_fingerprint": failure_fingerprint,
            "failed_targets": failed_targets,
            **secret_notes,
            **({"project_venv_created": created_venv} if created_venv else {}),
            **({"install_hint": hint} if failure_kind and (hint := project_env.missing_module_hint(combined, root)) else {}),
            # ★ 시간 제한에 걸린 것은 **멈춘 것이 아니다** (2026-10-09 새벽 · 판 hw5).
            #   한 줄짜리 애매한 숙제에서 모델이 첫 걸음에 전체 시험을 돌렸고 300초 제한에 걸렸다. 결과에는 `timed_out` 과
            #   끊기기 전의 출력(진행률 36%)만 있었고, 모델은 그것을 「36% 자리의 시험이 멈춘다」로 읽어 멈춤 진단 플러그인까지
            #   만들며 300초를 두 번 더 기다렸다(22분 중 15분). 무슨 일이 있었는지를 결과가 말한다.
            **({"timeout_note": (
                f"{timeout_sec}초 시간 제한에 걸려 **우리가 끊었다** — 명령이 멈췄다는 뜻이 아니다. 위 출력은 끊긴 순간까지의 것이고, "
                "마지막에 보이는 진행률·파일은 그때 돌던 자리일 뿐 고장 난 자리가 아니다. 같은 명령을 그대로 다시 돌리지 말고 "
                "범위를 좁혀라(시험이면 파일이나 이름으로 일부만)."
            )} if timed_out else {}),
            **({"note": " ".join(note for note in (
                f"path 가 파일({given_file.name})이라 그 파일이 든 폴더에서 돌렸다. 다음부터는 폴더를 줘라." if given_file is not None else "",
                f"`{label}` 는 이름표라 `{' '.join(PROJECT_COMMAND_LABELS[label])}` 로 돌렸다." if label else "",
            ) if note)} if given_file is not None or label else {}),
        }

    def list_directory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        roots = self._roots_when_path_missing(arguments)
        if roots is not None and len(roots) != 1:
            # 경로 없이 불렀다 — 볼 수 있는 자리들을 보여 준다(2026-09-20, 거절 대신).
            return {
                "action": "local_list_directory",
                "count": len(roots),
                "items": [{"name": root.name, "path": str(root.resolve()), "type": "directory", "size": None}
                          for root in roots],
                "note": "path 를 안 줘서 볼 수 있는 자리를 보여 준다. 그중 한 곳을 path 로 주면 안을 본다.",
            }
        if roots is not None:
            arguments = {**arguments, "path": str(roots[0])}
        path = self._resolve_workspace_path(arguments)
        if not path.is_dir():
            raise NotADirectoryError("directory_required")
        pattern = str(arguments.get("pattern") or "").strip()
        maximum = max(1, min(int(arguments.get("max_items") or LISTING_DEFAULT_ITEMS), 200))
        rows = []
        for item in sorted(path.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
            if item.name.startswith(".") or self._is_sensitive(item):
                continue
            if pattern and not fnmatch.fnmatch(item.name.lower(), pattern.lower()):
                continue
            stat = item.stat()
            # 항목 하나를 최대한 짧게. `extension`·`modified_at` 은 이름에서 알 수
            # 있거나 거의 안 쓰이는데, 100줄이 모이면 그것만으로 수천 자가 된다.
            rows.append(
                {
                    "name": item.name,
                    "path": str(item),
                    "type": "directory" if item.is_dir() else "file",
                    "size": None if item.is_dir() else stat.st_size,
                }
            )
            if len(rows) >= maximum:
                break
        self._listings_since_read += 1
        readable = [row for row in rows if row["type"] == "file"]
        clipped = len(rows) >= maximum
        return {
            "action": "local_list_directory",
            # ★ 목록은 답이 아니다 — 그리고 이 말을 **맨 앞**에 싣는다.
            #
            # 2026-08-09: 이 도구 하나만 부르고 파일 이름에서 구조·역할·기술 수준을
            # 추론해 "코드를 분석한 결과"라고 답했다. 이름 아홉 개는 실재했지만
            # 그 해석은 전부 추측이었다. 검색 결과 목록에서 겪은 것과 같은 고장이라
            # (browser._search_instruction) 같은 방법으로 막는다.
            #
            # 자리가 맨 앞인 이유: 도구 결과는 16,000자에서 잘려 모델에게 간다
            # (agent._record_observation). 이 폴더의 목록은 직렬화하면 15,936자였다 —
            # 상한까지 **64자** 남았다. 파일 하나만 더 생겼어도 맨 뒤에 있던 지시가
            # 통째로 잘려 나갔을 것이고, 아무도 그 사실을 몰랐을 것이다.
            "instruction": self._listing_instruction(readable, clipped=clipped),
            "path": str(path),
            "count": len(rows),
            "truncated": len(rows) >= maximum,
            "items": rows,
        }

    def _listing_instruction(self, readable: list[dict[str, Any]], *, clipped: bool = False) -> str:
        if not readable:
            return "이 폴더에는 읽을 파일이 없다. 하위 폴더를 열어 보거나 다른 경로를 확인해라."
        names = ", ".join(row["name"] for row in readable[:5])
        # ★ 로 시작시키는 것은 뜻이 있다 — 에이전트가 이 표시를 보고 지시를 **별도
        # 메시지로** 세운다(agent._record_observation). 결과 JSON 안에만 두면 큰
        # 목록에 묻혀 안 읽힌다는 것이 실측으로 드러났다. 읽을 파일이 있을 때만
        # 붙이므로, 폴더만 있는 목록에서는 울리지 않는다.
        base = (
            "★ 이건 **목록일 뿐이다 — 파일 이름은 내용의 근거가 아니다.** 무엇이 들어 "
            f"있는지 말하려면 local_read_text_file 로 실제로 열어라(예: {names}). "
            "이름과 폴더 구성만 보고 구조·역량·수준을 판단하지 마라."
        )
        if clipped:
            # 잘렸다는 사실을 안 알리면 "이 폴더에는 이것뿐"이라고 단정한다.
            base += (
                " 이 목록은 위쪽 일부만이다 — 전부 봐야 하면 max_items 를 키우거나 "
                "pattern 으로 좁혀라."
            )
        if self._listings_since_read >= 3:
            return (
                f"★ 파일은 하나도 안 열고 목록만 {self._listings_since_read}번째다. "
                "폴더를 더 뒤져도 내용은 알 수 없다. 지금은 읽어라. " + base
            )
        if self._listings_since_read == 2:
            return "★ 직전 목록에서 아무 파일도 안 열고 또 목록을 봤다. " + base
        return base

    #: 훑어 둔 이름을 다시 쓰는 시간(초). 같은 판 안에서 같은 뿌리를 다시 찾으면 디스크를 다시 안 긁는다.
    _NAME_SCAN_TTL_SEC = 600.0
    #: 하나라도 찾은 뒤 더 훑는 시간(초). 얕은 곳의 것이 먼저 나오니, 찾고 나서 예산을 끝까지 채우며 기다리게 하지 않는다.
    _NAME_SCAN_GRACE_SEC = 3.0
    #: 같이 들고 있는 뿌리 수. 넘으면 가장 오래된 것을 버린다.
    _NAME_SCAN_KEEP = 4

    def _name_scan(self, job_id: str, root: Path) -> dict[str, Any]:
        """이 판·이 뿌리의 **훑기 상태** — 아직 안 본 폴더 줄(queue)과 본 폴더의 이름들(folders).

        ★ 2026-10-05 실사용 판 568ca034: 「E 폴더에서 자비스 전략안 파일을 찾아」에 파일 찾기를 다섯 번 불렀고, 한 번에 18~49초씩
          **매번 처음부터** 같은 2만 개를 긁어 다섯 번 0건이었다(259초 중 약 166초). 한 번 본 이름은 다시 안 본다 — 다음 찾기는
          쌓인 이름부터 보고, 모자라면 멈춘 자리에서 **이어서** 훑는다.
        """
        scans: dict[tuple[str, str], dict[str, Any]] = self.__dict__.setdefault("_name_scans", {})
        key = (job_id, os.path.normcase(str(root)))
        now = time.monotonic()
        scan = scans.get(key)
        if scan is None or now - scan["started"] > self._NAME_SCAN_TTL_SEC:
            scan = {"started": now, "queue": deque([str(root)]), "folders": [], "count": 0}
            scans[key] = scan
            for stale in sorted(scans, key=lambda item: scans[item]["started"])[: max(0, len(scans) - self._NAME_SCAN_KEEP)]:
                scans.pop(stale, None)
        return scan

    #: 훑는 동안 화면에 「어디까지 봤나」를 알리는 간격(초).
    _NAME_SCAN_NOTE_SEC = 2.0

    def _note_progress(self, job_id: str, message: str) -> None:
        """오래 걸리는 도구가 **일하는 중**임을 화면에 알린다. 통로(`progress_sink`)는 런타임이 건다 — 없으면 아무 일도 안 한다.

        ★ 2026-10-05 대표: 「사용자는 멈췄나 한다」. 파일 찾기가 18~49초 동안 「이 PC에서 파일을 찾는 중」 한 줄만 보여 줬다.
          저장소 지도(`_index_progress`)가 이미 쓰는 것과 같은 길로 「몇 개 훑음 · 지금 어느 폴더」를 흘린다.
        """
        sink = getattr(self, "progress_sink", None)
        if sink is None or not job_id:
            return
        try:
            sink(job_id, message)
        except Exception:  # noqa: BLE001 — 알림이 실패해도 찾기는 계속한다
            pass

    def search_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """파일·폴더를 **이름으로** 찾는다. 얕은 폴더부터 보고, 찾으면 멈추고, 시간 예산 안에서만 긁는다.

        ★ 왜 넓이 우선인가 (2026-10-05, E: 실측 28만 2천 개 · 전부 훑으면 90~122초). 찾던 파일은 깊이 5에 있었는데, 깊이 우선은
          앞쪽 폴더들의 깊은 속에서 상한 2만 개를 다 썼다. 넓이 우선으로는 같은 파일이 22,566번째 · 5~8초였다. 같은 드라이브에서
          ripgrep `rg --files` 는 전부 훑는 데 49.9초 — 전체 훑기는 2배 빠르지만 디스크가 병목이라 「파일 하나 찾기」를 빠르게 하는 것은
          엔진이 아니라 **얕은 곳부터 · 찾으면 멈춤 · 본 것을 다시 안 봄**이었다.
        """
        query = str(arguments.get("query") or "").strip().lower()
        if not query:
            raise ValueError("query_required")
        root_raw = str(arguments.get("root") or "").strip()
        job_id = self._job_id(arguments)
        if root_raw:
            roots = [self._resolve_workspace_path({**arguments, "path": root_raw})]
        else:
            code_root = self._code_workspaces.get(job_id)
            roots = [code_root] if code_root is not None else list(self.allowed_roots)
        extension = str(arguments.get("extension") or "").strip().lower()
        if extension and not extension.startswith("."):
            extension = "." + extension
        maximum = max(1, min(int(arguments.get("max_results") or 30), 50))
        results: list[dict[str, Any]] = []
        scan_limit = max(1000, int(self.config.local_file_scan_limit))
        deadline = time.monotonic() + max(1.0, float(getattr(self.config, "local_file_scan_seconds", 20.0) or 20.0))
        scanned = 0
        walked_now = 0
        unscanned = 0
        found_at = 0.0
        noted_at = time.monotonic()

        def take(folder: str, names: list[tuple[str, bool]]) -> None:
            for name, is_dir in names:
                if len(results) >= maximum:
                    return
                if query not in name.lower():
                    continue
                # 건너뛰는 폴더(.git·node_modules …)와 숨은 폴더는 속을 안 보는 것처럼 이름도 결과로 내지 않는다(예전과 같다).
                if is_dir and (name.lower() in SKIP_DIRECTORIES or name.startswith(".")):
                    continue
                item = Path(folder) / name
                if self._is_sensitive(item):
                    continue
                suffix = "" if is_dir else item.suffix.lower()
                if extension and (is_dir or suffix != extension):
                    continue
                results.append({"name": name, "path": str(item), "type": "directory" if is_dir else "file", "extension": suffix})

        for root in roots:
            if not root.exists():
                continue
            scan = self._name_scan(job_id, root)
            # 1) 이미 훑어 둔 이름부터 — 디스크를 안 긁는다.
            for folder, names in scan["folders"]:
                if len(results) >= maximum:
                    break
                take(folder, names)
            # 2) 모자라면 멈춘 자리에서 이어서 훑는다(얕은 폴더부터).
            queue = scan["queue"]
            while queue and len(results) < maximum and scan["count"] < scan_limit and time.monotonic() < deadline:
                if results:
                    # 찾았으면 조금만 더 보고 멈춘다 — 나머지는 다시 부르면 이어서 본다.
                    deadline = min(deadline, found_at + self._NAME_SCAN_GRACE_SEC) if found_at else deadline
                    if not found_at:
                        found_at = time.monotonic()
                        continue
                folder = queue.popleft()
                names: list[tuple[str, bool]] = []
                try:
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            name = entry.name
                            try:
                                is_dir = entry.is_dir(follow_symlinks=False)
                            except OSError:
                                is_dir = False
                            names.append((name, is_dir))
                            if (
                                is_dir
                                and name.lower() not in SKIP_DIRECTORIES
                                and not name.startswith(".")
                                and not self._is_sensitive(Path(folder) / name)
                            ):
                                queue.append(os.path.join(folder, name))
                except OSError:
                    continue
                scan["folders"].append((folder, names))
                scan["count"] += len(names)
                walked_now += len(names)
                take(folder, names)
                if time.monotonic() - noted_at >= self._NAME_SCAN_NOTE_SEC:
                    noted_at = time.monotonic()
                    self._note_progress(job_id, f"파일을 찾는 중 — {scan['count']:,}개 훑음 · 지금 「{folder[-48:]}」")
            scanned += scan["count"]
            unscanned += len(queue)
            if len(results) >= maximum:
                break
        complete = unscanned == 0 and len(results) < maximum
        payload: dict[str, Any] = {
            "action": "local_search_files",
            "query": query,
            "count": len(results),
            "scanned": scanned,
            # 「끝까지 봤는가」를 따로 말한다. 예전에는 상한에 걸린 0건과 진짜 0건이 같은 모양이었다.
            "complete": complete,
            "truncated": not complete,
            "items": results,
        }
        if unscanned:
            payload["unscanned_folders"] = unscanned
        if not walked_now and scanned:
            payload["from_memory"] = True
        if unscanned and len(results) < maximum:
            # ★ 로 시작시킨다 — 에이전트가 이 표시를 보고 지시를 별도 메시지로 세운다(`_listing_instruction` 과 같은 약속).
            payload["instruction"] = (
                f"★ 이 자리를 **끝까지 못 봤다** — {scanned:,}개까지 훑었고 아직 안 본 폴더가 {unscanned:,}개 남았다. "
                # ★ 찾았으면 **더 부르라고 하지 않는다** (2026-10-05 판 b4b71589). 첫 걸음에 파일을 찾고도 「한 번 더 부르면
                #   이어서 훑는다」는 말에 같은 찾기를 네 번 더 불렀다(같은 한 건, 12초). 이어 찾기는 못 찾았을 때의 길이다.
                + (
                    "0건은 「없다」가 아니다. 같은 검색을 한 번 더 부르면 **멈춘 자리에서 이어서** 훑는다"
                    "(이미 본 곳은 다시 안 본다). 어느 폴더쯤인지 알면 root 로 좁히면 더 빠르다."
                    if not results else
                    "찾던 것이 위 목록에 있으면 **여기서 멈추고 그것으로 일해라** — 다시 부르지 마라. 같은 이름의 다른 파일까지 "
                    "전부 찾아야 하는 일일 때만 한 번 더 부르면 이어서 훑는다. 답에는 「끝까지 훑은 것은 아니다」라고 밝혀라."
                )
            )
        # ★ 헛걸음에 길을 알려 준다 (2026-08-31).
        #
        # 이 도구는 **파일 이름만** 본다(`query not in name.lower()`). grep 이 아니라
        # find 다. 설명에도 그렇게 적혀 있지만, 심볼을 찾으려고 부르면 수천 개를
        # 훑고 조용히 0건이 온다 — 실측으로 `chat_messages_stream` 을 12,075개
        # 훑고 0건을 받았다. 0건은 **「없다」가 아니라 「여기서는 못 찾는다」**인데
        # 그 둘이 구별이 안 됐다.
        #
        # 막지 않는다. 파일 이름을 찾는 정당한 호출도 0건일 수 있다. 다만 찾던 것이
        # 심볼처럼 생겼으면 **어느 문으로 가야 하는지 결과에 실어 보낸다.**
        if not results and _looks_like_symbol(query):
            payload["hint"] = (
                "이 도구는 파일 **이름**만 본다. 코드 안의 심볼·문자열을 찾으려면 "
                "local_index_codebase(query=...) 를 써라 — 심볼과 줄 범위, "
                "그리고 그대로 부를 수 있는 next_reads 가 함께 온다."
            )
        return payload

    #: 훑을 파일 수 상한. 넘으면 잘랐다고 말한다 — 조용히 멈추지 않는다.
    _GREP_MAX_FILES = 4_000
    #: 한 파일에서 이 크기를 넘으면 건너뛴다(생성물·덤프가 시간을 다 먹는다).
    _GREP_MAX_BYTES = 2_000_000

    def write_document_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """자기가 쓴 내용으로 XLSX·DOCX·PPTX·CSV 를 만든다.

        ★ 이 칸이 비어 있었다 (2026-09-01). 라이브러리는 런타임에 이미 있었는데
        통로가 없었다 — `artifact_from_observations` 는 **관측한 step_id** 로만 만들고,
        `sandbox_run` 은 로컬 파일을 못 본다. 그래서 「받은 엑셀을 읽고 정리해서
        다시 엑셀로」가 통째로 안 됐다.
        """
        if not str(arguments.get("path") or "").strip():
            raise ValueError("path_required")
        arguments = self._document_arguments(arguments)
        path = self._resolve_mutation_path(arguments, must_exist=False)
        fmt = str(arguments.get("format") or path.suffix or "").lower().lstrip(".")
        return self._write_document_at(arguments, path, fmt)

    def _document_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """문서 쓰기의 경로를 **실제로 쓸 자리**로 푼 인자 사본. 쓰기·위험도·승인 카드가 이 하나를 쓴다 (2026-09-30).

        ★ 셋이 따로 풀었다. 쓰기는 파일 이름만 받으면 `문서\\Sonjari` 앞에 붙이는데, 위험도는 날것 이름으로 재고
          승인 카드는 「작업 폴더에 쓰기」라고 적었다 — 사람은 어디에 무슨 파일이 생기는지 모르고 눌렀다.
        """
        raw = str(arguments.get("path") or "").strip()
        if not raw:
            return arguments
        # 결과물은 사람이 찾을 수 있는 곳에 둔다. 절대 경로를 주면 그대로 따른다.
        # ★ 첫 칸이 「내 문서」·「바탕화면」 같은 사용자 폴더 이름이면 **그 폴더**다 (2026-09-28 헤르메스 대결 O_T2).
        #   「내 문서 폴더에 회의록을 만들어 줘」에 모델은 `내 문서/…docx` 를 넣었는데, 여기서 우리 결과물 폴더를 먼저
        #   앞에 붙여 `Documents\JARVIS\내 문서\` 라는 하위 폴더가 생겼다 — 사람은 문서 폴더에서 못 찾는다.
        #   그런 이름은 붙이지 않고 넘겨 `_resolve_mutation_path` 가 실제 폴더로 풀게 한다(작업 폴더 밖이라 승인 자리로 간다).
        relative = Path(os.path.expandvars(raw)).expanduser()
        names_a_user_folder = len(relative.parts) > 1 and relative.parts[0].casefold() in _USER_FOLDER_ALIASES
        if not relative.is_absolute() and not names_a_user_folder:
            # ★ 결과물 폴더 **자기 이름으로 시작하면** 그 이름을 뗀다 (2026-09-28 T2 재시험). 앞 답에 적힌 `Documents\JARVIS\…` 를
            #   보고 모델이 `JARVIS/회의록.docx` 를 넣어 `JARVIS\JARVIS\` 가 생겼다. 같은 이름 폴더를 제 안에 두는 일은 없다.
            if len(relative.parts) > 1 and relative.parts[0].casefold() == self.documents_root.name.casefold():
                raw = str(Path(*relative.parts[1:]))
            arguments = {**arguments, "path": str(self.documents_root / raw)}
        return arguments

    def _document_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """문서 쓰기의 위험도 — **실제로 쓸 자리**로 잰다(쓰기와 같은 `_document_arguments`)."""
        return self._mutation_risk(self._document_arguments(arguments))

    def describe_document_target(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """문서 쓰기 승인 카드의 자리 — 파일 이름만 받아도 실제 경로(`문서\\Sonjari\\…`)를 보인다."""
        return describe_write_target(self._document_arguments(arguments))

    def _write_document_at(self, arguments: dict[str, Any], path: Path, fmt: str) -> dict[str, Any]:
        # ★ 이름의 확장자와 실제 형식을 맞춘다 (2026-09-15 모델 실측).
        #
        #   4B 모델이 이력서를 `path=…초안.hwp, format=hwpx` 로 불렀다. 우리는 hwpx(zip) 를 만들고
        #   이름은 `.hwp` 그대로 뒀다 — 한글은 옛 형식으로 열려다 실패하고, 읽는 쪽도 0자를 냈다(3판).
        #   옛 한글(.hwp, 이진 형식)은 쓸 수 없으니 hwpx 로 만들고, 이름도 그 형식으로 바꾼 뒤 **말한다.**
        if fmt == "hwp":
            fmt = "hwpx"
        extension_fixed = ""
        # ★ **글 형식(txt·md)으로 쓰는데 이름이 다른 글 파일이면 이름을 그대로 둔다** (2026-10-04 코드 판 04ec9c42).
        #   `path=calc.py, format=txt` 가 `calc.txt` 로 저장됐다 — 시킨 것은 `calc.py` 였고, 모델은 다른 손으로 다시 쓴 뒤
        #   잘못 생긴 `calc.txt` 를 지우느라 걸음을 썼다. 이진 형식(hwpx·docx·xlsx)은 이름과 속이 다르면 못 열리니 고쳐야 하지만,
        #   글은 속이 같다 — 확장자는 그 글이 **무엇인지**(파이썬·JSON·HTML)를 말하는 사람의 뜻이다. 문서 형식 이름(.docx 등)이면 예전대로 고친다.
        named = path.suffix.lower().lstrip(".")
        keeps_its_name = fmt in {"txt", "md"} and bool(named) and named not in WRITABLE and named != "hwp"
        if fmt in WRITABLE and named != fmt and not keeps_its_name:
            fixed = path.with_suffix(f".{fmt}")
            extension_fixed = f"「{path.name}」은 {fmt} 형식으로 만들어져 「{fixed.name}」로 저장했습니다."
            path = fixed
        # ★ 사람이 그 파일을 열어 두었으면 **옆에 만든다** (2026-09-01 저녁).
        #
        #   한글·엑셀은 연 파일을 붙잡는다. 그러면 쓰기가 Access Denied 로 죽고,
        #   자비스는 「한글을 닫고 다시 말씀해 주세요」라고 답한다 — 사람은
        #   결과물을 못 받는다. 잠긴 것은 못 이기지만, **빈손으로 끝낼 이유는
        #   없다.** 이름을 하나 비켜서 만들고 그 사실을 결과에 적는다.
        #   (조용히 이름을 바꾸지는 않는다 — 조용한 것이 제일 나쁘다.)
        renamed = ""
        kept_theirs = ""
        # ★ **이 판에서 만들지 않은 파일은 덮지 않는다** (2026-09-28 헤르메스 대결 확인 판 O4).
        #   `2026-09-28_회의록.docx` — 헤르메스가 방금 만든 파일과 같은 이름 — 를 묻지 않고 덮어썼다. 백업이 있어 되살렸지만
        #   사람은 자기 파일이 바뀐 줄 모른다. 헤르메스는 같은 자리에서 「Refusing to overwrite」로 거부했다. 우리는 막지 않고
        #   **옆 이름으로** 만들고 말한다. 같은 판에서 자기가 만든 것을 고쳐 쓰는 것(한 판 두세 번 쓰기)은 그대로 덮는다.
        job = self._job_id(arguments)
        made = self._made_by_job.setdefault(job, set())
        # 같은 판에서 같은 이름을 또 달라고 하면 **이 판이 그 이름 대신 만든 파일**을 고쳐 쓴다(2026-09-28 E3: `(10)` 을 두고 `(11)` 을 또 만들었다).
        detoured = self._detoured_by_job.setdefault(job, {})
        if str(path).lower() in detoured:
            path = Path(detoured[str(path).lower()])
        elif path.exists() and str(path).lower() not in {item.lower() for item in made}:
            spare = _unused_sibling(path)
            kept_theirs = f"「{path.name}」이 이미 있어서 덮지 않고 「{spare.name}」로 새로 만들었습니다(원래 파일은 그대로입니다)."
            detoured[str(path).lower()] = str(spare)
            path = spare
        existed, backup, before_sha = self._backup(path, job)
        try:
            shape = write_document(path, fmt, dict(arguments))
        except PermissionError:
            spare = _unused_sibling(path)
            shape = write_document(spare, fmt, dict(arguments))
            renamed = (
                f"「{path.name}」이 다른 프로그램에서 열려 있어 "
                f"「{spare.name}」로 저장했습니다."
            )
            path, existed, backup, before_sha = spare, False, None, ""
        made.add(str(path))
        state = self._file_state(path)
        self._shadow_readback(path, fmt, arguments, job)
        # ★ 만들었으면 띄워 주되, **판이 끝난 뒤에** 띄운다 (2026-09-01 저녁).
        #
        #   아침에는 여기서 바로 `os.startfile` 을 불렀다. 그랬더니 라이브에서
        #   이렇게 됐다:
        #
        #       3걸음  hwpx 만듦 → 한글이 뜸 → **한글이 그 파일을 붙잡음**
        #       6걸음  같은 파일에 다시 쓰기 → Access Denied
        #       8걸음  또 시도 → Access Denied
        #
        #   자비스가 자기가 만든 파일을 못 고치게 됐다. 게다가 계획 대조의
        #   `_open_artifacts` 는 파일 핸들을 **실제로 열어 보는데**, 잠긴 파일은
        #   그 검사도 통과 못 해서 「열 수 있는 산출물 없음」이 됐다 — 파일 셋을
        #   제대로 만든 판이 스스로 0/1 이라고 보고했다.
        #
        #   보여 주려던 것이 못 고치게 만드는 것이 됐다. 그래서 자리를 옮긴다:
        #   여기서는 **적어만 두고**, 판이 끝날 때 런타임이 연다
        #   (`open_pending`). 중간에 창이 튀지 않는 것은 덤이다.
        opened = ""
        if arguments.get("open", True):
            self.remember_to_open(self._job_id(arguments), path)
            opened = "deferred"
        return {
            "action": "local_write_document",
            "path": str(path),
            "opened": opened,
            # 비켜서 저장했으면 **말한다.** 답에도 이 문장이 실려야 한다.
            **({"renamed_because_locked": renamed} if renamed else {}),
            **({"renamed_because_exists": kept_theirs} if kept_theirs else {}),
            **({"extension_fixed": extension_fixed} if extension_fixed else {}),
            # 블록을 못 읽고 버렸으면 「확인됨」이 아니다 — 파일은 있어도 시킨 것이 빠졌다(2026-09-28 B1).
            "verified": state["exists"] and state["bytes"] > 0 and not shape.get("unreadable_blocks"),
            **shape,
            "undo_handle": {
                "path": str(path),
                "existed": existed,
                "backup_path": str(backup) if backup else "",
                "before_sha256": before_sha,
                "after_exists": True,
                "after_sha256": state.get("sha256", ""),
            },
        }

    def _shadow_readback(self, path: Path, fmt: str, arguments: dict[str, Any], job: str) -> None:
        """쓴 직후 다시 읽어 견준 것을 **그림자로만** 남긴다 (2026-10-15 · `readback.py`).

        결과에는 싣지 않는다 — 덧붙인 글은 모델에게 되돌아가 판을 흔든다(10-05). 「확인됨」도 바꾸지 않는다 — 문서 쓰기는
        받은 것을 일부러 바꾸기도 해서(「확인 불가」 칸 비우기 · 생각 조각 버리기) 헛경고가 얼마나 나는지부터 잰다.
        기록: 데이터 폴더의 `readback_shadow.jsonl`. 무엇이 실패해도 쓰기는 그대로 성공한다.
        """
        try:
            report = readback_report(path, fmt, dict(arguments), skip=lambda unit: bool(_UNVERIFIED_CELL.match(str(unit))))
            gaps = report["gaps"]
            line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "job": job, "path": str(path), "format": fmt,
                    "checked": report["checked"], "units": report["units"],
                    "gaps": gaps[:10] if isinstance(gaps, list) else None,
                    "gap_count": len(gaps) if isinstance(gaps, list) else None}
            target = Path(self.config.data_dir) / "readback_shadow.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — 그림자 기록은 덤이다
            return

    def edit_spreadsheet_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """기존 엑셀의 **셀만** 고친다 — 서식·수식·다른 시트를 안 건드린다."""
        path = self._resolve_mutation_path(arguments, must_exist=True)
        existed, backup, before_sha = self._backup(path, self._job_id(arguments))
        result = edit_spreadsheet(path, arguments.get("edits"), str(arguments.get("sheet") or ""))
        state = self._file_state(path)
        return {
            "action": "local_edit_spreadsheet",
            "path": str(path),
            "verified": result["changed"] > 0,
            **result,
            "undo_handle": {
                "path": str(path),
                "existed": existed,
                "backup_path": str(backup) if backup else "",
                "before_sha256": before_sha,
                "after_exists": True,
                "after_sha256": state.get("sha256", ""),
            },
        }

    def edit_document_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """워드·한글을 **제자리에서** 고친다 — 서식·표·머리말을 안 건드린다."""
        path = self._resolve_mutation_path(arguments, must_exist=True)
        existed, backup, before_sha = self._backup(path, self._job_id(arguments))
        result = edit_document(path, arguments.get("edits"))
        state = self._file_state(path)
        # 고친 것도 판 끝에 띄운다. 도중에 띄우면 다음 걸음이 그 파일을 못 연다.
        opened = ""
        if arguments.get("open", True):
            self.remember_to_open(self._job_id(arguments), path)
            opened = "deferred"
        return {
            "action": "local_edit_document",
            "path": str(path),
            "opened": opened,
            "verified": result["changed"] > 0,
            **result,
            "undo_handle": {
                "path": str(path),
                "existed": existed,
                "backup_path": str(backup) if backup else "",
                "before_sha256": before_sha,
                "after_exists": True,
                "after_sha256": state.get("sha256", ""),
            },
        }

    def grep_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """내용에서 **정규식**으로 찾는다. 파일:줄번호 + 앞뒤 맥락.

        ★ 이게 없어서 자비스는 「읽기로 때우고」 있었다 (2026-09-01).

        `local_search_files` 는 파일 **이름**만 본다(find). `local_index_codebase`
        는 심볼 단위 색인이라 "이 문자열이 어디 나오나"에는 못 답한다. 그래서
        「이 설정이 어디서 바뀌나」를 알려면 **파일을 열어 눈으로 훑는 수밖에** 없었고,
        그게 전사를 부풀리고 예산을 먹었다 — 벤치 실패 판의 공통 모양이
        「읽기 8~11회 · 쓰기 0회」였다.

        찾기가 정확해지면 **읽을 필요 자체가 준다.**
        """
        roots = self._roots_when_path_missing(arguments)
        if roots is not None:
            if not str(arguments.get("pattern") or "").strip():
                raise ValueError('pattern_required — `pattern` 에 찾을 글자를 넣어라. 예: {"pattern": "monthly_fee"} · 정규식도 된다. 이름으로 함수를 찾는 것이면 local_find_symbol 이 정의·참조까지 준다.')
            return self._over_roots("local_grep", self.grep_files, arguments, roots)
        root = self._resolve_workspace_path(arguments)
        pattern = str(arguments.get("pattern") or "").strip()
        if not pattern:
            raise ValueError('pattern_required — `pattern` 에 찾을 글자를 넣어라. 예: {"pattern": "monthly_fee"} · 정규식도 된다. 이름으로 함수를 찾는 것이면 local_find_symbol 이 정의·참조까지 준다.')
        flags = re.IGNORECASE if arguments.get("ignore_case") else 0
        try:
            needle = re.compile(pattern, flags)
        except re.error as exc:
            # 정규식이 틀렸다는 것과 못 찾았다는 것은 다른 사실이다.
            raise ValueError(f"bad_pattern:{exc}") from exc
        extension = str(arguments.get("extension") or "").strip().lower()
        if extension and not extension.startswith("."):
            extension = "." + extension
        context = max(0, min(int(arguments.get("context") or 0), 5))
        maximum = max(1, min(int(arguments.get("max_results") or 40), 200))

        hits: list[dict[str, Any]] = []
        scanned = files = 0
        truncated = False
        # ★ `path` 가 **파일 하나**면 그 파일만 본다 (2026-10-04 사다리 L2 — 「grep 이 0건으로 나왔네요」).
        #   폴더처럼 훑으면 아무것도 안 나와 0건·「훑은 파일 안에는 없다」가 됐다 — 있는 것을 없다고 한 셈이다.
        #   모델은 방금 쓴 `index.html` 안에서 찾으려던 것이었고, 두 걸음을 버린 뒤 파일을 통째로 읽었다.
        single_file = Path(root).is_file()
        walker: Any = [(str(Path(root).parent), [], [Path(root).name])] if single_file else os.walk(root)
        if single_file:
            extension = ""
        for current, directories, names in walker:
            current_path = Path(current)
            directories[:] = [
                name for name in directories
                if name.lower() not in SKIP_DIRECTORIES
                and not name.startswith(".")
                and not self._is_sensitive(current_path / name)
            ]
            for name in names:
                item = current_path / name
                if extension and item.suffix.lower() != extension:
                    continue
                if self._is_sensitive(item):
                    continue
                files += 1
                if files > self._GREP_MAX_FILES:
                    truncated = True
                    break
                try:
                    if item.stat().st_size > self._GREP_MAX_BYTES:
                        continue
                    lines = item.read_text(encoding="utf-8", errors="replace").splitlines()
                except (OSError, ValueError):
                    continue
                scanned += 1
                for index, line in enumerate(lines):
                    if not needle.search(line):
                        continue
                    low, high = max(0, index - context), min(len(lines), index + context + 1)
                    hits.append(
                        {
                            "path": str(item),
                            "line": index + 1,
                            "text": line[:400],
                            "context": [l[:400] for l in lines[low:high]] if context else [],
                        }
                    )
                    if len(hits) >= maximum:
                        truncated = True
                        break
                if len(hits) >= maximum:
                    break
            if truncated or len(hits) >= maximum:
                break
        payload: dict[str, Any] = {
            "action": "local_grep",
            "pattern": pattern,
            "count": len(hits),
            "files_scanned": scanned,
            "truncated": truncated,
            "items": hits,
        }
        if not hits:
            # 0건은 「없다」와 「덜 봤다」가 다르다. 그 둘을 구별해서 말해 준다.
            payload["hint"] = (
                "훑은 파일 안에는 없다. 다른 폴더/확장자일 수 있으니 path·extension 을 넓혀 보라"
                if not truncated
                else "상한에 걸려 다 못 봤다. path 를 좁히거나 extension 을 지정하라"
            )
        return payload

    def _roots_when_path_missing(self, arguments: dict[str, Any]) -> list[Path] | None:
        """경로를 안 줬을 때 찾을 자리. 경로를 줬으면 None(평소대로).

        ★ 2026-09-20 이 PC: 코워크 진단 한 판에서 `local_glob: path_required` 가 9번 — 모델은 패턴만 바꿔 경로 없이
          또 불렀다. 거절 한 단어는 걸음만 먹는다. 코드 작업이면 그 저장소, 아니면 **허용된 자리 전부**를 기본값으로 쓴다.
        """
        if str(arguments.get("path") or "").strip():
            return None
        code_root = self._code_workspaces.get(self._job_id(arguments))
        if code_root is not None:
            return [Path(code_root)]
        return [Path(root) for root in self.allowed_roots if Path(root).is_dir()]

    def _over_roots(self, action: str, run: Callable[[dict[str, Any]], dict[str, Any]],
                    arguments: dict[str, Any], roots: list[Path]) -> dict[str, Any]:
        """같은 찾기를 자리마다 돌려 합친다. 결과에 **어디를 찾았는지** 적는다 — 다음엔 좁혀 부르게."""
        maximum = max(1, int(arguments.get("max_results") or 100))
        merged: list[dict[str, Any]] = []
        truncated = False
        for root in roots:
            out = run({**arguments, "path": str(root)})
            merged.extend(out.get("items") or [])
            truncated = truncated or bool(out.get("truncated"))
            if len(merged) >= maximum:
                merged, truncated = merged[:maximum], True
                break
        searched = [str(root.resolve()) for root in roots]
        return {
            "action": action,
            "pattern": str(arguments.get("pattern") or ""),
            "count": len(merged),
            "truncated": truncated,
            "items": merged,
            "searched_roots": searched,
            "note": "path 를 안 줘서 허용된 자리 전부를 찾았다: " + " · ".join(searched)
                    + ". 다음엔 path 에 그중 한 곳(절대 경로)을 주면 더 빠르다.",
        }

    def glob_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """`**/*.py` 처럼 **트리 전체**에서 이름 패턴으로 찾는다.

        `local_list_directory` 의 pattern 은 한 폴더만 본다. 저장소 작업은
        "테스트 파일 전부"·"이 이름 붙은 것 전부"를 물을 일이 많다.
        """
        # ★ 경로에 패턴이 섞여 오면 **나눠서 받는다**(2026-09-27 게임 팩 벤치). 모델이 `path` 에
        #   `E:\...\Assets\**\*.psd` 를 통째로 넣어 `path_not_found` 가 5번 연속 나고 판이 멈췄다.
        #   와일드카드가 처음 나오는 조각 앞까지가 폴더, 나머지가 패턴이다 — 사고 R: 막지 말고 받아 줄 일.
        raw_path = str(arguments.get("path") or "")
        if any(mark in raw_path for mark in "*?["):
            parts = re.split(r"[\\/]", raw_path)
            cut = next(index for index, part in enumerate(parts) if any(mark in part for mark in "*?["))
            folder = "\\".join(parts[:cut]) or "."
            tail = "/".join(parts[cut:])
            given = str(arguments.get("pattern") or "").strip()
            arguments = {**arguments, "path": folder, "pattern": f"{tail}/{given}" if given and given != tail else tail}
        roots = self._roots_when_path_missing(arguments)
        if roots is not None:
            if not str(arguments.get("pattern") or "").strip():
                raise ValueError('pattern_required — `pattern` 에 파일 이름 모양을 넣어라. 예: {"pattern": "**/*.html"} · 내용을 찾는 것이면 local_grep 을 써라.')
            return self._over_roots("local_glob", self.glob_files, arguments, roots)
        root = self._resolve_workspace_path(arguments)
        pattern = str(arguments.get("pattern") or "").strip()
        if not pattern:
            raise ValueError('pattern_required — `pattern` 에 파일 이름 모양을 넣어라. 예: {"pattern": "**/*.html"} · 내용을 찾는 것이면 local_grep 을 써라.')
        maximum = max(1, min(int(arguments.get("max_results") or 100), 400))
        found: list[dict[str, Any]] = []
        truncated = False
        for item in root.glob(pattern):
            if any(part.lower() in SKIP_DIRECTORIES or part.startswith(".") for part in item.parts):
                continue
            if self._is_sensitive(item) or not item.is_file():
                continue
            try:
                size = item.stat().st_size
            except OSError:
                continue
            found.append({"path": str(item), "bytes": size})
            if len(found) >= maximum:
                truncated = True
                break
        # 최근에 손댄 것이 대개 찾는 것이다.
        found.sort(key=lambda row: row["path"])
        return {
            "action": "local_glob",
            # ★ 어디서 찾았나를 싣는다(2026-09-27). 없어서 원장이 패턴 글자를 온텔릭 작업 폴더에 붙여
            #   「E:\...\alture-jarvis\**\*.png」 를 읽은 것으로 적었다 — 실제로는 유니티 프로젝트를 뒤졌다.
            "path": str(root),
            "pattern": pattern,
            "count": len(found),
            "truncated": truncated,
            "items": found,
        }

    def find_symbol(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """이름 하나로 정의·참조·줄 범위. 「고치면 어디가 깨지나」에 답하는 자리다."""
        from .symbol_index import find_symbol as _find

        root = self._resolve_workspace_path(arguments)
        # ★ 파일을 줬으면 **그 파일이 든 작업 폴더**에서 찾는다 (2026-10-09 새벽 · 판 hw3 — `directory_required` 로 두 번 튕겼다).
        #   「이 파일의 이 이름」을 찾는 것은 자연스러운 부름이다. 명령 실행 손은 같은 경우를 이미 받아 준다(`run_project_command`).
        given_file = root if root.is_file() else None
        if given_file is not None:
            code_root = self._code_workspaces.get(self._job_id(arguments))
            root = Path(code_root) if code_root is not None and Path(code_root) in given_file.parents else given_file.parent
        if not root.is_dir():
            raise NotADirectoryError("directory_required")
        found = _find(
            root,
            str(arguments.get("symbol") or ""),
            max_references=max(5, min(int(arguments.get("max_references") or 60), 200)),
        )
        if given_file is not None and isinstance(found, dict):
            found = {**found, "note": f"path 가 파일({given_file.name})이라 그 파일이 든 폴더({root})에서 찾았다. 다음부터는 폴더를 줘라."}
        return found

    def index_codebase(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # ★ `path` 를 안 줘도 **잡에 묶인 코드 작업 폴더**를 색인한다 (2026-09-21, 노트북 4B).
        #   작은 모델이 `{}` 로 불러 `path_required` 를 받았다. 작업 폴더는 이미 정해져 있어
        #   물어볼 이유가 없다. 코드 작업이 아니면 어디인지 모르므로 예전처럼 거절한다.
        if not str(arguments.get("path") or "").strip():
            code_root = self._code_workspaces.get(self._job_id(arguments))
            if code_root is not None:
                arguments = {**arguments, "path": str(code_root)}
        root = self._resolve_workspace_path(arguments)
        if not root.is_dir():
            raise NotADirectoryError("directory_required")
        query = str(arguments.get("query") or "")
        maximum = max(1, min(int(arguments.get("max_results") or 30), 80))
        max_chars = max(4_000, min(int(arguments.get("max_chars") or 16_000), 16_000))
        result = self.code_index.query(
            root, query, max_results=maximum, max_chars=max_chars
        )
        # 색인이 시간 상한에서 멈췄으면 **그 사실을 결과에 말한다** — 아직 안 읽힌 파일을 「없다」로 읽지 않게.
        last = getattr(self.code_index, "last_refresh", None) or {}
        if last.get("stopped") == "time":
            result = {
                **result,
                "index_incomplete": True,
                "index_note": (
                    f"색인을 다 따라잡지 못했다 — {last.get('seconds')}초 동안 파일 {last.get('updated_files')}개를 새로 읽고 멈췄다. "
                    "아직 안 읽힌 파일이 있다. 여기서 못 찾았다고 「없다」고 하지 말고 local_grep 이나 local_search_files 로 "
                    "직접 찾아라. 다음 색인 때 이어서 읽는다."
                ),
            }
        return self._attach_next_reads(self._attach_code_notes(result), root)

    #: 색인이 쥐여 줄 「다음 읽기」 개수. 너무 많으면 그것대로 전사를 먹는다.
    _NEXT_READ_LIMIT = 6

    def _attach_next_reads(self, result: dict[str, Any], root: Path) -> dict[str, Any]:
        """찾은 심볼의 **줄 범위를 그대로 다음 호출로 만들어** 붙인다.

        ★ 2026-08-31. 조각은 다 있는데 이어져 있지 않았다.

        `repo_map.matches[].chunks[]` 는 이미 ``lines: [407, 530]`` 을 준다. 그리고
        `local_read_text_file` 은 ``line_start``/``line_end`` 를 받는다. **그런데 그
        둘을 이으라고 말해 주는 자리가 없었다** — Qwen 에게 가는 스키마는 인자
        설명을 통째로 지우고(`qwen_code_tools`), 도구 설명에도 줄 범위 얘기가 없다.

        그래서 모델은 파일을 통째로 읽는다. 기본이 15,000자라 열 번이면 15만 자고,
        그게 어젯밤 67,744토큰 프롬프트와 호출당 1~4분의 정체다.

        「그 줄만 읽어라」라고 **적어 두는 대신 답을 손에 쥐여 준다.** 이 저장소가
        여러 번 확인한 것 — 안내문은 안 먹고, 결정론으로 박을 수 있으면 코드로 옮긴다.
        """
        repo_map = result.get("repo_map")
        if not isinstance(repo_map, dict):
            return result
        picks: list[dict[str, Any]] = []
        for row in repo_map.get("matches") or []:
            if not isinstance(row, dict):
                continue
            relative = str(row.get("path") or "")
            for chunk in row.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                lines = chunk.get("lines") or []
                if not (isinstance(lines, (list, tuple)) and len(lines) == 2):
                    continue
                start, end = lines
                if not (isinstance(start, int) and isinstance(end, int) and end >= start):
                    continue
                picks.append(
                    {
                        "symbol": str(chunk.get("symbol") or ""),
                        "tool": "local_read_text_file",
                        "arguments": {
                            "path": str(root / relative) if relative else str(root),
                            "line_start": start,
                            "line_end": end,
                        },
                    }
                )
                if len(picks) >= self._NEXT_READ_LIMIT:
                    break
            if len(picks) >= self._NEXT_READ_LIMIT:
                break
        if not picks:
            return result
        result["next_reads"] = picks
        result["instruction"] = (
            str(result.get("instruction") or "")
            + " next_reads 는 **그대로 호출하면 되는 인자**다. 파일을 통째로 읽지 말고"
            " 이 줄 범위부터 읽어라 — 필요하면 그다음에 넓히면 된다."
        )
        return result

    def repo_card(self, root: str, query: str = "", on_progress: Any = None) -> str:
        """이 저장소가 무엇으로 이루어져 있는지 한 줄씩. 시스템 메시지용."""
        try:
            resolved = self._resolve(str(root), must_exist=True)
        except Exception:
            return ""
        if not resolved.is_dir():
            return ""
        try:
            self.code_index.refresh(resolved, on_progress=on_progress,
                                    budget_sec=self.code_index.REFRESH_BUDGET_SEC)
            return self.code_index.repo_card(resolved, query)
        except Exception:
            # 지도가 없어도 판은 돌아야 한다.
            return ""

    def _attach_code_notes(self, result: dict[str, Any]) -> dict[str, Any]:
        """후보 경로에 대해 아는 것을 지도에 붙인다.

        「gemma_bundle 은 자동 생성물이라 직접 고치면 다음 sync 때 사라진다」
        같은 지식은 그 폴더를 열 때 나와야 쓸모가 있다. 전역 선호로 넣어 두면
        엉뚱한 판에서 튀어나오고 정작 필요한 자리에선 조용하다.
        """
        memory = getattr(self, "memory", None)
        if memory is None:
            return result
        repo_map = result.get("repo_map")
        if not isinstance(repo_map, dict):
            return result
        paths = [
            str(row.get("path") or "")
            for row in (repo_map.get("matches") or [])
            if isinstance(row, dict)
        ]
        try:
            notes = memory.code_notes_for(paths)
        except Exception:
            # 기억이 고장 나도 색인은 계속 돌아야 한다.
            return result
        if notes:
            repo_map["known_notes"] = notes
            result["instruction"] = (
                str(result.get("instruction") or "")
                + " 이 저장소에 대해 이미 아는 것(known_notes)이 붙어 있으면 먼저 읽어라."
            )
        return result

    def _run_for_model(
        self, executable: list[str], *, root: Any, environment: dict[str, str], timeout_sec: float, creationflags: int = 0,
    ) -> tuple[int, str, str, bool, dict[str, Any]]:
        """사용자의 명령을 돌려 **모델에게 보일 출력**으로 만든다 → (종료 값, 출력, 오류 출력, 시간 제한에 걸렸나, 덧붙일 칸).

        명령 두 길(`run_project_command` · `run_shell`)이 같이 지나는 자리다. 여기서 셋을 한다 (2026-10-11):
          1. 넘기는 환경에서 이름이 비밀인 값과 작업 폴더의 `.env` 류 파일을 **배우고**, 출력에 그 값이 찍혔으면 가린다.
             값은 명령에 그대로 간다 — 모델이 보는 글에서만 가린다. 자르기(끝 16,000자) **앞에서** 가린다: 잘린 자리에 걸친
             값의 꼬리가 남지 않게.
          2. 값을 모르는데 비밀처럼 보이는 긴 글자는 **세기만** 한다(지우지 않는다 — 모양으로 지우다 멀쩡한 글 74곳을 지운 적이 있다).
          3. 명령이 도는 동안만 있는 빈 데이터 자리를 넘긴다(`project_env.scratch_home`).
        """
        known = getattr(self, "known_secrets", None)
        if known is not None:
            try:
                known.learn_environment(environment)
                known.learn_near(root)
            except Exception:  # noqa: BLE001 — 배우다 틀어져도 명령은 돈다
                pass
        with project_env.scratch_home(environment) as child_environment:
            exit_code, raw_out, raw_err, timed_out = run_captured(
                executable, cwd=root, env=child_environment, timeout_sec=timeout_sec, creationflags=creationflags,
            )
        stdout, stderr = _decode_output(raw_out)[-200_000:], _decode_output(raw_err)[-200_000:]
        hidden = 0
        if known is not None:
            try:
                stdout, in_out = known.hide(stdout)
                stderr, in_err = known.hide(stderr)
                hidden = in_out + in_err
            except Exception:  # noqa: BLE001
                hidden = 0
        stdout, stderr = stdout[-16_000:], stderr[-16_000:]
        notes: dict[str, Any] = {}
        if hidden:
            notes["secrets_hidden"] = hidden
            notes["secrets_note"] = (
                f"출력에서 아는 비밀 값 {hidden}곳을 가렸다(`[비밀 가림: 이름]`). 값은 명령에 그대로 전달됐고 여기서만 안 보인다 — "
                "값을 보려고 다시 찍지 말고, 필요하면 그 이름으로 가리켜라."
            )
        looking = count_secret_looking(stdout) + count_secret_looking(stderr)
        if looking:
            notes["secret_looking"] = looking
            notes["secret_looking_note"] = (
                f"출력에 비밀일 수 있는 긴 무작위 글자가 {looking}개 있다(가리지 않았다). 답·파일·검색어에 그대로 옮겨 적지 마라."
            )
        return exit_code, stdout, stderr, timed_out, notes

    def read_text_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """코드·텍스트를 **훑어보는** 쪽. 기본을 작게 준다.

        ★ 이게 "파일을 안 읽는다"의 진짜 원인이었다(2026-08-09).
        컨텍스트는 24,576 토큰인데 이 도구의 기본 max_chars 가 40,000자였다 —
        한 파일을 읽으면 대화창이 통째로 찬다. 여러 파일을 견줘 봐야 하는 코드
        분석에서는 사실상 **쓸 수 없는 도구**였고, 그래서 모델은 목록만 보고
        파일 이름에서 추측했다. 게으른 것이 아니라 예산이 없던 것이다.

        작게 주면 대여섯 개를 견줄 수 있다. 더 필요하면 `truncated: true` 를 보고
        max_chars 를 키워 다시 부르면 된다 — 그 신호는 이미 결과에 실려 나간다.

        문서를 통째로 달라는 쪽(`local_read_document`)은 그대로 크게 둔다. 그건
        사용자가 "이 PDF 읽어줘"라고 지목한 경우라 잘라 내면 안 된다.
        """
        arguments = dict(arguments)
        arguments.setdefault("max_chars", SURVEY_READ_CHARS)
        # 줄 범위를 지목했으면 **그 구간만** 준다. outline 을 보고 콕 집어 오는
        # 경로다 — 4,689줄짜리 파일에서 함수 하나만 읽으면 전사가 수십 배 싸다.
        wanted_start = arguments.pop("line_start", None)
        wanted_end = arguments.pop("line_end", None)
        result = self.read_document(arguments, action="local_read_text_file")
        result = self._keep_source_layout(result, arguments)
        content = str(result.get("content") or "")
        if wanted_start or wanted_end:
            return self._slice_lines(result, wanted_start, wanted_end)
        result["line_start"] = 1
        result["line_end"] = content.count("\n") + (1 if content else 0)
        return self._attach_outline(result)

    #: 문서 읽기의 결과를 그대로 두는 글자 형식 — 바꿔서 보여 주는 것(RTF · JSON 은 펴서)과
    #: 조사 쪽에서도 읽는 문서성 글(txt·md·csv·log). 여기 없는 글자 형식(코드·설정·HTML)만 원본 배치를 지킨다.
    #: ★ HTML 은 **원본**을 준다 (2026-10-04 사다리 L1). 문서 읽기는 HTML 에서 보이는 글만 뽑는다 — 방금 만든 `index.html` 을
    #:   세 번 읽어 세 번 다 14글자(「별 관측 관측 시작」)만 받았다. 코드를 보려던 모델에게는 빈 파일이다. 보이는 글만 필요하면
    #:   `local_read_document` 가 그대로 그렇게 준다 — 이 도구(`local_read_text_file`)는 코드·글자를 훑어보는 쪽이다.
    _CONVERTED_TEXT_FORMATS = frozenset({
        ".rtf", ".json", ".jsonl", ".txt", ".md", ".csv", ".tsv", ".log",
    })

    def _keep_source_layout(self, result: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        """코드·글자 파일은 **들여쓰기를 지우지 않고** 준다 (2026-10-04 헤르메스 전수조사).

        문서 읽기(`DocumentReader`)는 줄마다 앞뒤 공백을 지우고 이어진 공백을 한 칸으로 줄인다 — PDF·워드에는 맞지만
        파이썬에는 **들여쓰기가 통째로 사라진다.** 모델은 들여쓰기 없는 본문을 보고 편집을 보내고(32K 판 첫 편집 실패 3/3),
        편집 도구의 구제 사다리가 그걸 메워 왔다. 줄 범위 읽기(`_slice_lines`)는 이미 원본을 준다 — 통째 읽기만 달랐다.

        바꾸는 것은 글자 파일뿐이다. 워드·PDF·한글과 HTML(보이는 글만 뽑음)·RTF 는 그대로 둔다.
        """
        path = Path(str(result.get("path") or ""))
        suffix = path.suffix.lower()
        if suffix not in PLAIN_TEXT_EXTENSIONS or suffix in self._CONVERTED_TEXT_FORMATS:
            return result
        maximum = max(1_000, min(int(arguments.get("max_chars") or 40_000), 80_000))
        try:
            raw = path.read_bytes()
        except OSError:
            return result
        # `decode_text` 는 풀면서 공백까지 정리한다 — 여기서는 글자만 푼다. 순서는 그쪽과 같다(BOM → utf-8 → cp949).
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            candidates: tuple[str, ...] = ("utf-16",)
        else:
            candidates = ("utf-8-sig", "cp949")
        text = ""
        for encoding in candidates:
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        truncated = len(text) > maximum
        result["content"] = text[:maximum]
        result["truncated"] = truncated
        if truncated:
            result["instruction"] = (
                f"이 파일은 {maximum}자에서 잘렸다. 뒷부분이 필요하면 max_chars 를 "
                "키워 다시 읽어라 — 지금 본 것만으로 파일 전체를 단정하지 마라."
            )
        else:
            result.pop("instruction", None)
        return result

    def _slice_lines(
        self, result: dict[str, Any], start: Any, end: Any
    ) -> dict[str, Any]:
        path = str(result.get("path") or "")
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            result["error"] = str(exc)[:200]
            return result
        total = len(lines)
        first = max(1, int(start or 1))
        last = min(total, int(end or total))
        if last < first:
            first, last = last, first
        body = chr(10).join(lines[first - 1 : last])
        result["content"] = body[:40_000]
        result["line_start"] = first
        result["line_end"] = last
        result["total_lines"] = total
        result["truncated"] = len(body) > 40_000
        result["instruction"] = (
            "지목한 줄 범위만 읽었다. 더 필요하면 범위를 옮겨 다시 불러라."
        )
        return result

    def _attach_outline(self, result: dict[str, Any]) -> dict[str, Any]:
        """잘린 파일에는 **무엇이 더 있는지** 목차를 같이 준다.

        `agent.py` 는 4,689줄이다. 앞 8,000자만 주면 모델은 나머지에 무엇이 있는지
        모른 채 목록을 다시 훑거나 엉뚱한 데를 판다. 함수 목록과 줄 범위는
        본문보다 수십 배 싸고, 그것만 있으면 **필요한 구간만 콕 집어** 다시 부를
        수 있다 — 앤트로픽 스킬의 「본문은 필요할 때만」과 같은 층이다.
        """
        if not result.get("truncated"):
            return result
        path = str(result.get("path") or "")
        if not path.lower().endswith(".py"):
            return self._attach_continuation(result, path)
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            chunks = self.code_index._python_chunks(text)
        except Exception:
            return result
        outline = [
            f"{chunk['symbol']} ({chunk['start_line']}-{chunk['end_line']})"
            for chunk in chunks
            if chunk.get("symbol")
        ]
        if not outline:
            return result
        result["outline"] = outline[:200]
        result["total_lines"] = text.count("\n") + 1
        result["instruction"] = (
            str(result.get("instruction") or "")
            + " 잘렸다. outline 에 이 파일의 함수와 줄 범위가 있으니, "
            "필요한 구간을 line_start/line_end 로 지목해 다시 읽어라."
        ).strip()
        return result

    @staticmethod
    def _attach_continuation(result: dict[str, Any], path: str) -> dict[str, Any]:
        """잘린 **글** 파일에 「어디서 이어 읽을지」를 준다. 마크다운이면 제목 목차도.

        ★ 2026-09-29 밤 코워크: 20만 자 전략안을 같은 경로로 세 번 불러 세 번 다 앞 15,000자만 받았다.
          `.py` 에는 목차와 「line_start 로 다시 읽어라」가 붙는데 `.md` 에는 `truncated` 하나뿐이라
          **다음에 어디를 부르라는 말이 없었다** — 답에 「§42~끝 읽지 못함」이 남았다.
        """
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return result
        total = len(lines)
        # 잘린 끝줄은 반쪽일 수 있다 — 그 줄부터 다시 준다(한 줄 겹쳐도 빠지는 것보다 낫다).
        next_start = max(1, min(total, int(result.get("line_end") or 1)))
        result["total_lines"] = total
        result["next_line_start"] = next_start
        note = f"잘렸다 — 앞 {next_start}줄(전체 {total}줄)만 왔다. 뒤를 읽으려면 line_start={next_start} 로 다시 불러라."
        if path.lower().endswith((".md", ".markdown")):
            # 큰 절(#·##)만 — 전략안 전체 제목은 300개·1만 자라 본문만큼 컸다. 목차가 창을 채우면 거꾸로다.
            #   80개를 넘으면 가장 큰 절(#)만 — 앞에서 80개로 자르면 **최근 절(뒤쪽)이 통째로 빠진다**(전략안 §24~§55).
            def _heads(pattern: str) -> list[str]:
                return [f"{line.strip()[:50]} ({index})" for index, line in enumerate(lines, 1)
                        if re.match(pattern, line.lstrip())]

            headings = _heads(r"#{1,2}\s+\S")
            if len(headings) > 80:
                headings = _heads(r"#\s+\S")
            if headings:
                result["headings"] = headings[:80] if len(headings) <= 80 else headings[:40] + headings[-40:]
                note += " headings 에 큰 절의 줄 번호가 있으니 필요한 절을 line_start/line_end 로 콕 집어 읽어도 된다."
        # 앞 단계의 「max_chars 를 키워 다시 읽어라」는 여기선 틀린 안내다 — 상한(40,000)을 넘는 파일은 키워도 잘린다.
        result["instruction"] = note + " 지금 본 것만으로 파일 전체를 단정하지 마라."
        return result

    @staticmethod
    def _read_plain_text(path: Path, maximum: int) -> str:
        """확장자를 모르는 파일을 **글자면** 읽는다. 아니면 거절한다.

        판정은 이름이 아니라 **내용**이다: NUL 바이트가 있으면 실행파일·그림이고,
        UTF-8 로 안 풀리면 시스템 코드페이지로 한 번 더 본다(한국어 PC 의 옛 파일).
        """
        raw = path.read_bytes()[: max(maximum * 4, 4096)]
        if b"\x00" in raw:
            raise ValueError("unsupported_document_format")
        text = _decode_output(raw)
        # 깨진 글자가 많으면 글자 파일이 아니다. 1% 를 넘으면 안 읽는다.
        if text.count("�") > max(4, len(text) // 100):
            raise ValueError("unsupported_document_format")
        return text[:maximum]


    # ── 만든 페이지를 **스스로 보기** (2026-09-20) ────────────────────────────
    #
    #   프론트 과제가 파일을 만들고도 「볼 방법이 없어」 다섯 번 막히고 실패로 끝났다.
    #   `file://` 를 브라우저에 열어 주면 `.ssh` 까지 열리므로, **작업 폴더만** 로컬
    #   주소로 띄우고 브라우저에는 평소대로 `http://127.0.0.1:...` 를 준다.
    #
    #   덤: Code 모드의 컴퓨터 칸이 브라우저 화면을 보여 주므로, 만든 페이지가 거기
    #   그대로 렌더된다 — 모델도 보고 사람도 본다.

    def serve_page(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """작업 폴더를 **루프백에만** 띄우고, 지목한 파일의 주소를 돌려준다."""

        # ★ `path` 를 안 줘도 작업 폴더의 페이지를 연다 (2026-09-21, 노트북 4B 가 `{}` 로 불러
        #   `path_required` → 화면을 못 보고 `partial`). 만든 페이지가 바로 거기 있다 —
        #   `index.html` 을 먼저, 없으면 가장 최근에 바뀐 `.html` 을. 없으면 지어내지 않고 거절한다.
        picked_note = ""
        if not str(arguments.get("path") or "").strip():
            picked = self._default_preview_page(arguments)
            if picked is None:
                raise ValueError(
                    "path_required — 작업 폴더에 열 수 있는 .html 이 아직 없다. "
                    "페이지를 먼저 local_write_file 로 만든 뒤 path 를 주어 불러라."
                )
            arguments = {**arguments, "path": str(picked)}
            picked_note = (
                f"path 를 안 줘서 {picked.name} 을 골랐다. 다른 파일이면 path 에 그 파일을 주어 다시 불러라."
            )
        path = self._resolve_mutation_path(arguments, must_exist=True)
        root = self._mutation_workspace(arguments, create=False).resolve(strict=False)
        if not self._inside(path, root):
            raise PermissionError(f"preview_outside_workspace: {path}")
        if getattr(self, "_preview", None) is None or self._preview_root != root:
            self.stop_serving()
            self._preview = start_preview_server(root)
            self._preview_root = root
        port = self._preview.server_address[1]
        relative = path.relative_to(root).as_posix()
        served = {
            "action": "local_preview_page",
            "path": str(path),
            "url": f"http://127.0.0.1:{port}/{relative}",
            "instruction": (
                "이 주소를 browser_open 으로 열면 화면을 볼 수 있다. "
                "사람도 오른쪽 컴퓨터 칸에서 같은 화면을 본다."
            ),
        }
        if picked_note:
            served["note"] = picked_note
        return served

    #: 미리보기 기본값을 찾을 때 안 들어가는 폴더. 만든 페이지가 아니라 도구가 만든 것들이다.
    _PREVIEW_SKIP_DIRS = frozenset({"node_modules", ".git", "__pycache__", ".venv", "venv", "dist-info"})

    def _default_preview_page(self, arguments: dict[str, Any]) -> Path | None:
        """`path` 없이 불린 미리보기가 열 페이지. `index.html` 우선, 없으면 가장 최근 `.html`."""
        root = self._mutation_workspace(arguments, create=False).resolve(strict=False)
        if not root.is_dir():
            return None
        index = root / "index.html"
        if index.is_file():
            return index
        newest: tuple[float, Path] | None = None
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in self._PREVIEW_SKIP_DIRS]
            for name in files:
                if not name.lower().endswith((".html", ".htm")):
                    continue
                candidate = Path(current) / name
                try:
                    stamp = candidate.stat().st_mtime
                except OSError:
                    continue
                if newest is None or stamp > newest[0]:
                    newest = (stamp, candidate)
        return newest[1] if newest else None

    def stop_serving(self) -> None:
        server = getattr(self, "_preview", None)
        if server is None:
            return
        try:
            server.shutdown()
            server.server_close()
        except Exception:  # noqa: BLE001 — 못 닫아도 판을 죽이지 않는다
            pass
        self._preview = None
        self._preview_root = None


    # ── 진짜 셸 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _shell_head(command: str) -> str:
        """맨 앞 프로그램 이름(소문자, 확장자 뺀 것)."""
        text = str(command or "").strip().lstrip("&").strip()
        if not text:
            return ""
        first = text.split()[0].strip("'\"")
        return Path(first).stem.lower()

    def _shell_looks_read_only(self, command: str) -> bool:
        """이 셸 명령은 **보기만** 하는가.

        ★ 이어 붙인 명령은 **조각마다** 본다 (2026-09-23 이어받기 실측).
          `cd <가지> && git status` 가 맨 앞 이름(`cd`)만 보고 「모르는 명령」→ 승인 카드가 됐다.
          폴더 이동은 아무것도 안 바꾸니 건너뛰고, 남은 조각이 **전부** 보기만 할 때만 참.
          조각 하나라도 바꾸는 명령이면 거짓이다 — 느슨해지지 않는다.
        """
        pieces = [piece.strip() for piece in re.split(r"&&|\|\||;|\|", command) if piece.strip()]
        heads = [self._shell_head(piece) for piece in pieces]
        working = [head for head in heads if head not in _SHELL_NAVIGATION]
        return (
            bool(pieces)
            and all(head in _SHELL_READ_ONLY for head in working)
            and not _SHELL_MUTATING_ARGS.search(command)
        )

    def names_our_own_install(self, command: str) -> str:
        """이 명령 글이 **손자리 자신이 깔린 폴더**를 가리키면 그 경로(앞부분)를, 아니면 빈 글을 돌려준다.

        ★ 2026-10-09 — 대표가 권한 화면을 보다 짚은 것. 「고치고 만들 수 있는 폴더」 목록은 손자리의 **파일 도구**에만 걸린다.
          손자리가 **실행하는 명령**(셸 · 프로젝트 명령)이 무엇을 쓰는지는 그 목록이 막지 못하고, 「셸 명령 자동 실행」이 켜져
          있으면 승인도 없다(막는 것은 윈도우 시스템 폴더뿐이었다). 그날 새벽 한 줄짜리 숙제를 맡긴 판은 사본을 고친 뒤
          **돌고 있는 손자리의 설치 폴더**를 고치려 했다 — 파일 도구로 시도해 허용 범위 문에 막혔지만, 셸로 했으면 됐을 것이다.
          손자리가 자기 자신을 바꾸는 길은 어떤 설정으로도 열지 않는다. 무엇을 「자기 자신」으로 보는지는 `_own_install_folders`.

        명령 글에 적힌 경로를 보는 것이라 **상자가 아니다** — 변수로 조립한 경로나 `..` 로 거슬러 오는 길까지는 못 본다.
        실제로 본 모양(설치 경로를 그대로 적은 명령)을 막는 문이다.
        """
        flat = re.sub(r"[\/]+", r"\\", str(command or "")).casefold()
        for folder in self._own_install_folders():
            start = 0
            while True:
                at = flat.find(folder, start)
                if at < 0:
                    break
                tail = re.match(r"[^\s\"'`;|&<>)]*", flat[at:]).group(0)
                # 같은 글자로 시작하는 **다른 폴더**(…\data-backup)는 그 폴더가 아니다.
                if tail[len(folder):len(folder) + 1] in ("", "\\"):
                    return tail[:160]
                start = at + len(folder)
        return ""

    def _own_install_folders(self) -> tuple[str, ...]:
        """돌고 있는 손자리를 **이루는 것**: 지금 도는 코드 · 데이터(DB·토큰) · 기동 스크립트. 소문자 · 역슬래시로 맞춘 경로.

        실행 환경(파이썬이 든 폴더)은 넣지 않는다 — 그 파이썬을 **부르는** 명령은 정상이다(확인 명령이 그렇게 적혀 온다).
        산출물·작업 자리는 손자리가 일하는 곳이라 넣지 않는다.
        """
        found: list[str] = []
        for raw in (Path(__file__).parent, getattr(self.config, "data_dir", ""), Path(str(getattr(self.config, "runtime_root", "") or ".")) / "scripts"):
            try:
                folder = str(Path(raw).resolve(strict=False)).replace("/", "\\").rstrip("\\").casefold()
            except (OSError, TypeError, ValueError):
                continue
            if len(folder) >= 8 and folder not in found:
                found.append(folder)
        return tuple(found)

    def _shell_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """**무엇을 하는 명령인가**로 등급을 정한다 (2026-09-20).

        보는 것은 L1 — 조사는 멈추지 않는다. 그게 셸을 주는 이유다.
        바꾸는 것은 L2 — 승인 카드. 설정에서 「셸 명령 자동 실행」을 켜면 L1 로 내려간다
        (커서의 Run Mode 와 같은 자리, 사장님 요청).
        """
        command = str(arguments.get("command") or "")
        if self._shell_looks_read_only(command):
            return RiskLevel.L1
        if getattr(self.config, "shell_autorun_enabled", False):
            return RiskLevel.L1
        return RiskLevel.L2

    def run_shell(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """작업 폴더에서 PowerShell 한 줄. **검은 창은 절대 안 뜬다.**"""
        command = str(arguments.get("command") or "").strip()
        if not command:
            raise ValueError("command_required")
        if len(command) > 2000:
            raise ValueError("command_too_long")
        # ★ 승인으로도, 자동 실행을 켜도 **안 연다.** 보안 설정·인증서는 사람이 직접 한다.
        if _SHELL_NEVER.search(command):
            raise PermissionError(
                "security_setting_change_blocked: 보안 설정·인증서·서비스·계정은 손자리가 바꾸지 않습니다. "
                "필요하면 사람이 직접 해 주세요."
            )
        if _SHELL_FORBIDDEN_PATHS.search(command):
            raise PermissionError("system_folder_blocked: 시스템 폴더는 건드리지 않습니다.")
        # ★ 자동 실행을 켜도 **안 연다** — 손자리가 자기 자신을 바꾸는 명령(`names_our_own_install`). 보기만 하는 명령은 둔다.
        own = "" if self._shell_looks_read_only(command) else self.names_our_own_install(command)
        if own:
            raise PermissionError(
                f"own_install_blocked: {own} 은(는) 손자리 자신이 깔린 폴더라 손자리가 바꾸지 않습니다. "
                "이 판의 작업 폴더 안에서 일하세요. 설치된 손자리를 고쳐야 하면 사람이 직접 합니다."
            )

        root = self._mutation_workspace(arguments, create=True)
        timeout_sec = max(5, min(int(arguments.get("timeout_sec") or 120), 600))
        environment = project_env.with_project_venv_first(_with_our_python_first({
            **project_env.without_our_settings(dict(os.environ)),
            "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }), Path(root))
        environment = project_env.with_project_sources_first(environment, Path(root))
        # ★ 창을 숨긴다 (사장님이 못 박은 조건). CREATE_NO_WINDOW 가 없으면 PowerShell 이
        #   검은 창을 띄운다 — 사람이 일하는 화면 위로 튀어 오른다.
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # ★ PowerShell 은 출력을 **콘솔 코드페이지**로 찍는다. 한국어 PC 에서는 cp949 라
        #   한글이 통째로 깨져서 돌아온다(실측). 먼저 UTF-8 로 찍으라고 말해 둔다 —
        #   같은 날 아침 파이썬 자식에게 `PYTHONIOENCODING` 을 준 것과 같은 자리다.
        executable = [
            "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-Command",
            _PS_UTF8_PRELUDE + command,
        ] if os.name == "nt" else ["/bin/sh", "-c", command]
        started = time.monotonic()
        # 시간 제한에 걸리면 그 아래 프로세스까지 끝내고 돌아온다 — `run_captured` 의 설명.
        exit_code, stdout, stderr, timed_out, secret_notes = self._run_for_model(
            executable, root=root, environment=environment, timeout_sec=timeout_sec, creationflags=creation,
        )
        return {
            **secret_notes,
            "action": "local_run_shell",
            "command": command,
            "path": str(root),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "verified": exit_code == 0 and not timed_out,
            "took_ms": round((time.monotonic() - started) * 1000),
        }

    def read_document(
        self, arguments: dict[str, Any], *, action: str = "local_read_document"
    ) -> dict[str, Any]:
        path = self._resolve_workspace_path(arguments)
        if not path.is_file():
            raise IsADirectoryError("file_required")
        if path.stat().st_size > self.config.local_file_max_bytes:
            raise ValueError("file_too_large")
        maximum = max(1_000, min(int(arguments.get("max_chars") or 40_000), 80_000))
        if path.suffix.lower() == ".hwp":
            # ★ 옛 한글(.hwp)은 이 도구가 못 읽는다 — 거절할 때 **갈 길을 같이 준다** (2026-10-17 한글→PDF 3판).
            #   「한글 파일을 PDF 로 저장해 줘」 판이 이 도구로 원본을 열다 거절당하자 샌드박스에서 pyhwp · olefile 로 파일을
            #   뜯어 읽으려고 8~11번 돌았고, 3판 중 2판이 PDF 를 엉뚱한 폴더에 두거나 못 만들었다. `hwp_export_pdf` 는 등록돼
            #   있었는데 한 번도 안 불렸다. 글자 판정(`_read_plain_text`)으로 넘기면 NUL 때문에 같은 거절이 이름 없이 나간다.
            raise ValueError(
                "unsupported_document_format:.hwp — 옛 한글(.hwp)은 이 도구로 못 읽는다. "
                "PDF 로 바꾸려면 hwp_export_pdf(path) 한 번이면 된다. 한글에 열린 문서를 읽으려면 hwp_list_open → hwp_read."
            )
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            # ★ 확장자가 없거나 모르는 이름이어도 **글자면 읽는다** (2026-09-20 실전에서 드러남).
            #
            #   코딩 과제 31걸음 중 하나가 `.git/config` 에서 `unsupported_document_format` 으로
            #   죽었다. 재 보니 `Dockerfile`·`Makefile`·`.gitignore`·`LICENSE`·`Procfile`·
            #   `.python-version` 이 **전부** 안 읽혔다. 저장소에서 흔한 파일들이고, 코드 에이전트가
            #   Dockerfile 을 못 읽으면 배포 관련 일은 시작도 못 한다.
            #
            #   그렇다고 아무거나 열지는 않는다 — **내용을 보고** 정한다. 그림·실행파일을 글자로
            #   읽으면 전사가 쓰레기로 찬다.
            return {
                "action": action,
                "path": str(path),
                "format": path.suffix.lstrip(".").lower() or "text",
                "content": self._read_plain_text(path, maximum),
            }
        document = self.reader.read_path(path, max_chars=maximum)
        self._listings_since_read = 0
        return {
            "action": action,
            "path": str(path),
            **document.public_metadata(),
            "content": document.text,
            # 잘렸으면 그 사실을 눈에 띄게 알린다. 안 그러면 앞 6,000자만 보고
            # "이 파일은 이런 파일이다"라고 단정한다.
            **(
                {
                    "instruction": (
                        f"이 파일은 {maximum}자에서 잘렸다. 뒷부분이 필요하면 max_chars 를 "
                        "키워 다시 읽어라 — 지금 본 것만으로 파일 전체를 단정하지 마라."
                    )
                }
                if document.truncated
                else {}
            ),
        }

    def list_open_windows(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if os.name != "nt" or not self.config.windows_control_enabled:
            raise RuntimeError("windows_control_unavailable")
        maximum = max(1, min(int(arguments.get("max_results") or 50), 100))
        user32 = ctypes.windll.user32
        windows: list[dict[str, Any]] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def collect(hwnd: int, _: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if not title:
                return True
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            windows.append(
                {
                    "window_id": int(hwnd),
                    "title": title[:500],
                    "process_id": int(process_id.value),
                    "minimized": bool(user32.IsIconic(hwnd)),
                }
            )
            return len(windows) < maximum

        callback = callback_type(collect)
        user32.EnumWindows(callback, 0)
        return {"action": "windows_list_open_windows", "count": len(windows), "windows": windows}

    def focus_window(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if os.name != "nt" or not self.config.windows_control_enabled:
            raise RuntimeError("windows_control_unavailable")
        window_id = int(arguments.get("window_id") or 0)
        user32 = ctypes.windll.user32
        if not window_id or not user32.IsWindow(window_id):
            raise ValueError("window_not_found")
        length = int(user32.GetWindowTextLengthW(window_id))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(window_id, buffer, length + 1)
        # 사람이 치는 중이면 창을 앞으로 끌어오지 않는다 — 기다렸다가, 끝내 안 멈추면 미룬다(인수인계 H2-A).
        from .user_presence import UserPresence

        if not UserPresence(self.config).wait_until_idle(quiet_sec=2.0, timeout_sec=45.0):
            raise RuntimeError(
                "user_active_try_later: 사용자가 키보드·마우스를 쓰는 중이라 창을 앞으로 가져오지 않았습니다. "
                "잠시 뒤 다시 시도하세요."
            )
        if user32.IsIconic(window_id):
            user32.ShowWindow(window_id, 9)  # SW_RESTORE
        if not user32.SetForegroundWindow(window_id):
            raise RuntimeError("window_focus_failed")
        return {"action": "windows_focus_window", "window_id": window_id, "title": buffer.value[:500]}

    def open_path(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if os.name != "nt" or not self.config.windows_control_enabled:
            raise RuntimeError("windows_control_unavailable")
        # ★ **정해 둔 윈도우 프로그램은 이름으로 연다** (2026-10-17 메모장 판 d4c7eb06). 「메모장을 열어」에 모델은
        #   `C:\Windows\System32\notepad.exe` 를 열려 했고, 시스템 폴더라 막히자 System32 를 작업 자리로 달라고 했다가 또 막혀
        #   두 걸음을 버렸다(결국 셸 명령으로 열었다 — 셸은 사람 승인이 드는 더 넓은 문이다). 시스템 폴더를 여는 대신 실행 파일
        #   **이름 몇 개만** 받는다. 인자는 넘기지 않는다 — 프로그램을 켜는 것뿐이고, 무엇을 할지는 그다음 창 조작이 한다.
        # ★ **이 파일을 이 앱으로 연다** (2026-10-17 앱 묶음 · 그림판 18306ebe). 「PNG 를 그림판으로 열어」에 파일만 열면 기본 앱(사진)이
        #   떠서, 모델은 셸 명령(`Start-Process mspaint …`)으로 그림판을 띄웠다. 앱은 정해 둔 목록에서만, 파일은 여는 길과 같은 허용
        #   자리에서만 받고, 셸 없이 그 실행 파일에 파일 하나를 넘긴다.
        requested_app = str(arguments.get("app") or "").strip()
        if requested_app:
            exe = launchable_app(requested_app)
            if exe is None:
                raise PermissionError("app_not_allowed: 이름으로 여는 앱(메모장 · 계산기 · 그림판 · 작업 관리자 · 파일 탐색기 · 시스템 정보 · 한글 · "
                                      "엑셀 · 워드 · 파워포인트 · VS Code)만 고를 수 있습니다.")
            target = self._resolve(str(arguments.get("path") or ""), write=True)
            from .msix import external_path

            before = _visible_windows()
            subprocess.Popen([exe, str(external_path(target))], close_fds=True)  # noqa: S603 — 목록의 실행 파일 + 허용 자리의 파일 하나
            return {"action": "windows_open_path", "path": str(target), "type": "directory" if target.is_dir() else "file",
                    "opened_with": Path(exe).name, **_wait_for_new_window(before)}
        page = settings_page(str(arguments.get("path") or ""))
        if page is not None:
            # 윈도우 설정은 실행 파일이 아니라 주소로 연다 — 정해 둔 화면 이름만(`_SETTINGS_PAGES`). 여는 것뿐, 바꾸는 것은 없다.
            before = _visible_windows()
            os.startfile(page)  # noqa: S606 — 정해 둔 ms-settings: 주소만
            return {"action": "windows_open_path", "path": page, "type": "settings", "opened_with": "SystemSettings",
                    **_wait_for_new_window(before)}
        app = launchable_app(str(arguments.get("path") or ""))
        if app is not None:
            before = _visible_windows()
            os.startfile(app)  # noqa: S606 — 목록에 있는 실행 파일만(`launchable_app`)
            return {"action": "windows_open_path", "path": app, "type": "app", "opened_with": Path(app).name,
                    **_wait_for_new_window(before)}
        # ★ 파일을 여는 것은 그 파일의 앱을 **실행**하는 것이다. 좁은 쪽으로 푼다 (2026-09-20).
        path = self._resolve(str(arguments.get("path") or ""), write=True)
        from .file_open import open_file
        from .msix import external_path

        before = _visible_windows()
        opened_with = open_file(external_path(path))
        return {"action": "windows_open_path", "path": str(path), "type": "directory" if path.is_dir() else "file",
                "opened_with": opened_with, **_wait_for_new_window(before)}
