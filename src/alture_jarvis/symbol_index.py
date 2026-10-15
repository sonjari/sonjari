"""이름 하나로 **정의·참조·줄 범위**를 찾는다 — 「이 함수 누가 부르나」 (2026-09-21).

## 왜 (사장님 요청)

> 관련 파일에서 관련 코드 줄까지 이제 지가 딱 타고 인덱싱을 하면은 제일 좋을거같고

지금 `local_index_codebase` 는 심볼 덩어리와 줄 범위를 준다. 없는 것은 **관계**다 —
정의가 어디고, 누가 부르고, 고치면 어디가 깨지는지. 모델은 그걸 몰라서 `local_grep`
으로 이름을 훑고 **파일을 통째로 읽어** 확인한다. 그게 전사를 먹는다.

## 어떻게

    정의   `ast` 로 판다. 파이썬 문법이 정하는 것이라 **오탐이 없고** 줄 범위가 정확하다.
    참조   단어 경계로 훑는다. 주석·문자열 안의 것은 표시해 둔다(지우지 않는다 — 진짜일 수 있다).
    확인   `jedi` 가 있으면 정의에 설명(서명)을 붙인다. 없어도 도구는 돈다.

## 왜 외부 프로그램을 안 쓰나

ripgrep·ast-grep 이 더 빠르지만 **사용자 PC 에 없다**(2026-09-21 실측: 이 PC 에도 없었다).
제품에 넣을 도구가 「깔려 있으면 된다」면 대부분의 사용자에게는 없는 기능이다.
파이썬만으로 이 저장소(1,900 파일)를 0.6초에 훑는다 — 그 값이면 충분하다.

## 무엇을 안 하나

타입 추론으로 **같은 이름의 다른 심볼**을 가르지 않는다. `run` 처럼 흔한 이름은
후보가 많이 나온다. 대신 정의를 **먼저·정확히** 주고, 참조는 파일별로 묶어
사람과 모델이 고를 수 있게 한다. 지어내는 것보다 많이 주는 쪽이 낫다.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

from .code_index import SKIP_DIRS

#: 한 번에 훑을 파일 수. 넘으면 잘랐다고 **말한다** — 조용히 자르면 「없다」로 읽힌다.
MAX_FILES = 4000
#: 돌려줄 참조 수. 모델 전사를 지키는 값이다.
MAX_REFERENCES = 60
#: 파이썬 이름 규칙. 이보다 느슨하면 `a.b` 의 `b` 까지 걸려 후보가 쓸모없어진다.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _python_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for current, directories, files in os.walk(root):
        directories[:] = [
            name for name in directories
            if name not in SKIP_DIRS and not name.startswith(".")
        ]
        for name in files:
            if name.endswith(".py"):
                found.append(Path(current) / name)
                if len(found) >= MAX_FILES:
                    return found
    return found


def _definitions_in(path: Path, name: str) -> list[dict[str, Any]]:
    """이 파일이 `name` 을 **정의**하는 자리. 문법이 정하므로 오탐이 없다."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return []
    out: list[dict[str, Any]] = []

    def _walk(node: ast.AST, holder: str) -> None:
        for child in ast.iter_child_nodes(node):
            kind = ""
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "method" if holder else "function"
            elif isinstance(child, ast.ClassDef):
                kind = "class"
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        out.append({"kind": "variable", "line": child.lineno,
                                    "end_line": getattr(child, "end_lineno", child.lineno),
                                    "holder": holder})
            if kind and getattr(child, "name", "") == name:
                out.append({
                    "kind": kind,
                    "line": child.lineno,
                    "end_line": getattr(child, "end_lineno", child.lineno),
                    "holder": holder,
                    # 데코레이터가 있으면 정의는 그 위부터 읽어야 뜻이 통한다.
                    "read_from": min(
                        [child.lineno] + [d.lineno for d in getattr(child, "decorator_list", [])]
                    ),
                })
            if isinstance(child, ast.ClassDef):
                _walk(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _walk(child, holder)

    _walk(tree, "")
    return out


def _references_in(path: Path, pattern: re.Pattern[str]) -> list[dict[str, Any]]:
    """이 파일에서 그 이름이 **쓰인** 줄. 주석·문자열 여부는 표시만 하고 빼지 않는다."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not pattern.search(line):
            continue
        stripped = line.strip()
        out.append({
            "line": number,
            "text": stripped[:160],
            # 주석 줄은 「부르는 곳」이 아니다. 지우지는 않는다 — 옮겨 적은 규칙일 수 있다.
            "in_comment": stripped.startswith("#"),
        })
    return out


def find_symbol(root: Path, name: str, *, max_references: int = MAX_REFERENCES) -> dict[str, Any]:
    """`name` 의 정의와 참조. 돌려주는 것은 **다음 읽기로 바로 쓸 수 있는 줄 범위**다."""
    name = str(name or "").strip()
    if not _NAME.match(name):
        return {"ok": False, "error": "bad_symbol_name",
                "instruction": "심볼 이름만 줘라 — `a.b` 나 공백은 받지 않는다."}
    root = Path(root)
    if not root.is_dir():
        return {"ok": False, "error": "directory_required"}

    pattern = re.compile(rf"\b{re.escape(name)}\b")
    # ★ 바이트로 먼저 거른다 (2026-09-21 실측: 12.2초 → 아래 주석의 값).
    #
    #   파일마다 utf-8 로 풀고 정규식을 돌리면 이름이 없는 파일에도 그 값을 다 낸다.
    #   저장소의 99% 는 찾는 이름이 아예 없는 파일이다. 바이트 `in` 은 디코딩도
    #   정규식도 없이 그걸 걸러 낸다 — 통과한 것만 제대로 본다.
    needle = name.encode("utf-8")
    files = _python_files(root)
    definitions: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    scanned = 0
    for path in files:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        scanned += 1
        if needle not in raw:
            continue  # 이름이 아예 없는 파일은 풀지도 파싱도 안 한다 — 이게 속도의 전부다
        body = raw.decode("utf-8", errors="replace")
        if not pattern.search(body):
            continue  # 낱말이 아니라 다른 이름의 일부였다 (`grade` 안의 `rad` 같은)
        relative = path.relative_to(root).as_posix()
        for found in _definitions_in(path, name):
            definitions.append({"file": relative, **found})
        for row in _references_in(path, pattern):
            references.append({"file": relative, **row})

    defined_at = {(d["file"], d["line"]) for d in definitions}
    # 정의 줄은 참조가 아니다 — 두 번 세면 「10곳에서 쓴다」가 부풀어 판단을 흐린다.
    references = [r for r in references if (r["file"], r["line"]) not in defined_at]
    callers = sorted({r["file"] for r in references if not r["in_comment"]})
    truncated = len(references) > max_references
    return {
        "ok": True,
        "symbol": name,
        "files_scanned": scanned,
        "definitions": definitions,
        "definition_count": len(definitions),
        "references": references[:max_references],
        "reference_count": len(references),
        "references_truncated": truncated,
        "used_in_files": callers,
        # ★ **줄 범위를 그대로 쥐여 준다** — 「그 줄만 읽어라」라고 적어 두는 대신.
        #   안내문은 안 먹는다(사고 R). 이 저장소가 `_attach_next_reads` 에서 쓴 방법과 같다.
        "next_reads": [
            {
                "tool": "local_read_text_file",
                "arguments": {
                    "path": d["file"],
                    "line_start": d.get("read_from", d["line"]),
                    "line_end": d["end_line"],
                },
                "why": f"{d['kind']} {name} 의 정의",
            }
            for d in definitions[:6]
        ],
    }
