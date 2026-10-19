"""바깥 AI 가 맡긴 **코드 일의 작업 자리** — 그 저장소의 새 가지(worktree) (2026-10-09).

## 왜

2026-10-09 밤, 우리 저장소의 숙제 다섯을 손자리에게 맡겼다. 그때 쓴 방식이 「저장소 사본에서 일시키고, 맡긴 쪽이 바뀐 것만
보고 가져온다」였고 세 가지가 확인됐다 — 사본이라 잃을 것이 없었다(손자리가 돌고 있는 설치본을 고치려 했을 때 허용 범위 문이
막았다) · 검토가 자연스러웠다(바뀐 것만 본다) · 가져올 수 있었던 것은 기준이 분명한 좁은 과제였다.
그 방식을 제품의 길로 만든다. 통째 복사 대신 **git 가지**를 쓴다: 복사가 필요 없고, 가져오는 것이 git 그대로다.

## 무엇을 하나

- `prepare` — 저장소의 `HEAD` 에서 새 가지를 따 우리 폴더 밑에 작업 자리를 만든다. 맡긴 쪽이 아직 커밋하지 않은 **추적 파일의
  변경**은 같이 가져와 시작점 커밋으로 박는다(그래야 손자리가 한 것만 따로 보인다). 저장소 안의 하위 폴더를 맡겼으면 **그 폴더만**
  꺼낸다 — 큰 저장소를 통째로 꺼내지 않는다.
- `finish` — 작업 자리의 변경을 그 가지에 커밋하고, 시작점부터 바뀐 것을 요약한다.

원래 폴더는 건드리지 않는다. 가지와 작업 자리는 지우지 않는다 — 지우는 것은 맡긴 쪽이나 사람이 정한다.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]

#: 손자리가 맡은 일로 만든 가지의 이름 머리.
BRANCH_PREFIX = "sonjari/task-"
#: 커밋에 쓰는 이름 — 사용자의 git 이름이 없어도 되게, 그리고 누가 한 것인지 보이게.
_IDENTITY = ("-c", "user.name=Sonjari", "-c", "user.email=sonjari@localhost")


def _git(run: Runner, cwd: str | Path, *args: str, input_bytes: bytes | None = None, timeout: float = 60) -> "subprocess.CompletedProcess[bytes]":
    return run(["git", "-C", str(cwd), *args], input=input_bytes, capture_output=True, timeout=timeout)


def _text(done: "subprocess.CompletedProcess[bytes]") -> str:
    return (done.stdout or b"").decode("utf-8", "replace").strip()


def _why(done: "subprocess.CompletedProcess[bytes]", limit: int = 300) -> str:
    return " ".join((done.stderr or b"").decode("utf-8", "replace").split())[:limit]


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:40] or "repo"


def prepare(folder: str, *, home: Path, run: Runner = subprocess.run, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """`folder`(저장소 뿌리나 그 안의 폴더)의 일을 할 새 가지와 작업 자리를 만든다.

    돌려주는 것: `ok` · `repo`(저장소 뿌리) · `branch` · `worktree`(가지를 꺼낸 자리) · `workspace`(그 안에서 맡긴 폴더에 해당하는 자리 —
    손자리가 일할 곳) · `base`(시작점 커밋) · `carried`(커밋 안 된 변경을 가져왔나). 안 되면 `ok: False` 와 `error` · `detail`.
    """
    target = Path(folder)
    if not target.is_dir():
        return {"ok": False, "error": "folder_missing", "detail": str(target)}
    top_done = _git(run, target, "rev-parse", "--show-toplevel")
    if top_done.returncode != 0:
        return {"ok": False, "error": "not_a_git_repo", "detail": _why(top_done)}
    top = Path(_text(top_done))
    try:
        relative = target.resolve().relative_to(top.resolve())
    except ValueError:
        relative = Path(".")
    stamp = int(clock())
    branch = f"{BRANCH_PREFIX}{stamp}"
    worktree = Path(home) / f"{_slug(top.name)}-{stamp}"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    whole = str(relative) in (".", "")
    added = _git(run, top, "worktree", "add", *([] if whole else ["--no-checkout"]), "-b", branch, str(worktree), "HEAD", timeout=300)
    if added.returncode != 0:
        return {"ok": False, "error": "worktree_add_failed", "detail": _why(added)}
    if not whole:
        # 맡긴 폴더만 꺼낸다 — 큰 저장소의 하위 폴더 하나를 맡겼는데 전체를 꺼내면 수 GB · 수 분이 든다.
        sparse = _git(run, worktree, "sparse-checkout", "set", "--cone", relative.as_posix())
        checked = _git(run, worktree, "checkout", branch, timeout=300) if sparse.returncode == 0 else sparse
        if checked.returncode != 0:
            return {"ok": False, "error": "sparse_checkout_failed", "detail": _why(checked), "branch": branch, "worktree": str(worktree)}
    # 맡긴 쪽이 아직 커밋하지 않은 추적 파일의 변경을 가져온다. 새로 만든(추적 안 한) 파일은 안 가져온다 —
    # 개발 저장소에는 추적 안 한 출력물·로그가 수천 개씩 있다(이어받기 `_carry_uncommitted` 가 같은 이유로 그렇게 한다).
    diff_args = ["diff", "HEAD", "--binary"] + ([] if whole else ["--", relative.as_posix()])
    diff = _git(run, top, *diff_args, timeout=120).stdout or b""
    carried = False
    if diff.strip():
        applied = _git(run, worktree, "apply", "--whitespace=nowarn", "-", input_bytes=diff, timeout=120)
        carried = applied.returncode == 0
    base = _commit(run, worktree, "맡긴 순간의 상태(커밋 안 된 변경 포함)") if carried else _text(_git(run, worktree, "rev-parse", "HEAD"))
    return {
        "ok": True, "repo": str(top), "branch": branch, "worktree": str(worktree),
        "workspace": str(worktree if whole else worktree / relative), "base": base, "carried": carried,
    }


#: 가지에 커밋하지 않는 부산물 — 시험 · 컴파일이 만든 것. 저장소에 `.gitignore` 가 없으면 `add -A` 가 다 쓸어 담는다.
#: ★ 2026-10-20 시험 판 dd6c008c: `.gitignore` 없는 저장소에서 바뀐 파일 173개 중 `__pycache__/*.pyc` 가 130여 개였다.
_NOT_WORK = (":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc", ":(exclude,glob)**/.pytest_cache/**")


def _commit(run: Runner, worktree: str | Path, message: str) -> str:
    """작업 자리의 변경을 그 가지에 커밋하고 커밋 번호를 돌려준다. 바뀐 것이 없으면 지금 머리 그대로."""
    _git(run, worktree, "add", "-A", "--", ".", *_NOT_WORK, timeout=120)
    if _git(run, worktree, "diff", "--cached", "--quiet").returncode != 0:
        run(["git", "-C", str(worktree), *_IDENTITY, "commit", "-m", message], capture_output=True, timeout=120)
    return _text(_git(run, worktree, "rev-parse", "HEAD"))


def finish(worktree: str, base: str, *, message: str, run: Runner = subprocess.run) -> dict[str, Any]:
    """작업 자리의 변경을 가지에 커밋하고, 시작점(`base`)부터 바뀐 것을 요약한다."""
    if not worktree or not Path(worktree).is_dir():
        return {"ok": False, "error": "worktree_missing"}
    head = _commit(run, worktree, message[:200] or "손자리 작업")
    names = _text(_git(run, worktree, "diff", "--name-status", f"{base}..{head}")) if base and head else ""
    changed = []
    for line in names.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            changed.append({"status": parts[0][:1], "path": parts[-1]})
    stat = _text(_git(run, worktree, "diff", "--shortstat", f"{base}..{head}")) if base and head else ""
    wording = wording_only(run, worktree, base, head, [item["path"] for item in changed if item["status"] == "M"])
    return {"ok": True, "head": head, "changed": changed[:200], "changed_count": len(changed), "stat": stat,
            "wording_only": wording[:60]}


def _code_shape(source: str) -> str | None:
    """파이썬 소스에서 **설명 글(docstring)과 주석을 뺀** 모양. 문법이 깨졌으면 None.

    주석은 AST 에 원래 없다. 설명 글은 모듈 · 클래스 · 함수 몸의 첫 문장이 글자 하나뿐인 경우다.
    """
    import ast

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def wording_only(run: Runner, worktree: str | Path, base: str, head: str, paths: list[str]) -> list[str]:
    """고친 파이썬 파일 가운데 **설명 글 · 주석만** 바뀌고 코드는 그대로인 것.

    ★ 2026-10-19 맡기기 75aaa296. 「벤치 파일에 measurement 낱말이 있어야」라는 허술한 시험을 받고, 손자리는 일을 걸지도 않는
      조회 스크립트 17개의 **설명 글에 그 낱말을 끼워 넣어** 통과시켰다. 확인 명령은 통과로 찍혔고 바뀐 파일 수는 40개로 커 보였다.
      동작이 그대로인 변경은 시험만 맞춘 것일 수 있다 — 막지 않고, 맡긴 쪽이 가져가기 전에 보게 이름을 붙인다.
    """
    if not base or not head:
        return []
    found: list[str] = []
    for path in paths:
        if not path.endswith(".py"):
            continue
        before = _git(run, worktree, "show", f"{base}:{path}")
        after = _git(run, worktree, "show", f"{head}:{path}")
        if before.returncode != 0 or after.returncode != 0:
            continue
        old_text = (before.stdout or b"").decode("utf-8", "replace")
        new_text = (after.stdout or b"").decode("utf-8", "replace")
        if old_text == new_text:
            continue
        old_shape = _code_shape(old_text)
        if old_shape is not None and old_shape == _code_shape(new_text):
            found.append(path)
    return found


def take_home(repo: str, branch: str, base: str, worktree: str) -> dict[str, str]:
    """맡긴 쪽이 결과를 보고 가져가는 명령 — 손자리는 원래 폴더에 합치지 않는다. 합치는 것은 맡긴 쪽이 본 뒤에 정한다.

    `take` 는 커밋하지 않고 가져온다(`-n`) — 무엇을 어떻게 커밋할지는 가져가는 쪽이 정한다.
    """
    return {
        "review": f'git -C "{repo}" diff {base[:12]}..{branch}',
        "take": f'git -C "{repo}" cherry-pick -n {base[:12]}..{branch}',
        "discard": f'git -C "{repo}" worktree remove --force "{worktree}" ; git -C "{repo}" branch -D {branch}',
    }


def leftovers(home: str | Path, *, older_than_days: float = 7, clock: Callable[[], float] = time.time) -> list[dict[str, Any]]:
    """`home` 바로 아래 남아 있는 오래된 작업 자리를 **목록으로만** 보여 준다.

    `prepare` 가 만든 작업 자리는 일이 끝나도 남는다(맡긴 쪽이 본 뒤에 치워야 하므로).
    **아무것도 지우지 않는다** — 치우는 것은 사람이 정한다.

    돌려주는 것: `{"path": 폴더 전체 경로, "age_days": 지난 날 수(소수 한 자리)}` 를 가장 오래된 것이
    맨 앞에 온 목록. `home` 이 없거나 폴더가 아니면 빈 목록. `home` 아래에서 폴더만 센다.
    """
    base = Path(home)
    if not base.is_dir():
        return []
    now = float(clock())
    found: list[dict[str, Any]] = []
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    for entry in entries:
        try:
            if not entry.is_dir():
                continue
            age = (now - entry.stat().st_mtime) / 86_400.0
        except OSError:
            continue
        if age > older_than_days:
            found.append({"path": str(entry), "age_days": round(age, 1)})
    found.sort(key=lambda item: item["age_days"], reverse=True)
    return found
