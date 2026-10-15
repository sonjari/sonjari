"""백엔드에서 화면으로 나갈 수 있는 한국어 문장을 뽑는다 (2026-10-02 영어판 2단계).

ui_i18n 은 나가는 순간 사전으로 바꾼다. 이 스크립트는 그 사전의 열쇠를 만든다:
고정 문장은 그대로, f-string 은 ``{0}`` 틀로. 모델에게 하는 말·정규식·낱말 묶음·비교·딕셔너리 키는 뺀다 —
그것들은 화면에 안 나가고, 번역 비용만 든다.

    python scripts/i18n_backend_extract.py            → 개수
    python scripts/i18n_backend_extract.py --write    → scripts/i18n_backend_keys.json
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "alture_jarvis"
HANGUL = re.compile("[\uac00-\ud7a3]")
MODEL_FACING = ("[시스템]", "[도구가 보낸 안내]", "[도구 안내]", "[계획]", "[재개]")
REGEX_LIKE = re.compile(r"\\[dswbDSWB]|\(\?[:=!<P]|\[\^|\|\(|\)\||\(\?i\)")
REGEX_CALLS = {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"}
MAX_LEN = 600


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    out: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


def _docstrings(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, (ast.Constant, ast.JoinedStr)):
                ids.add(id(first.value))
    return ids


def _skip(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    child, parent = node, parents.get(id(node))
    while isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Mod):  # "…%s" % x
        child, parent = parent, parents.get(id(parent))
    if parent is None:
        return False
    if isinstance(parent, (ast.Set, ast.Compare, ast.Subscript, ast.MatchValue)):
        return True
    if isinstance(parent, ast.Dict) and any(key is child for key in parent.keys):
        return True
    if isinstance(parent, ast.Call):
        func = parent.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name in REGEX_CALLS or name in {"frozenset", "set", "startswith", "endswith", "count", "find", "index", "get"}:
            return True
    # 짧은 낱말 묶음 — ("엑셀", "표", "시트") 같은 판정 목록.
    if isinstance(parent, (ast.Tuple, ast.List)):
        items = [item for item in parent.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        if len(items) >= 3 and all(len(item.value) <= 12 for item in items):
            return True
    return False


def _template(node: ast.JoinedStr) -> str | None:
    parts: list[str] = []
    hole = 0
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value.replace("{", "{{").replace("}", "}}") if False else value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append("{" + str(hole) + "}")
            hole += 1
        else:
            return None
    return "".join(parts)


def extract() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        parents = _parents(tree)
        docs = _docstrings(tree)
        inside_fstring = {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values}
        for node in ast.walk(tree):
            if id(node) in docs or id(node) in inside_fstring:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            elif isinstance(node, ast.JoinedStr):
                text = _template(node) or ""
            else:
                continue
            if len(HANGUL.findall(text)) < 2 or len(text) > MAX_LEN:
                continue
            if text.lstrip().startswith(MODEL_FACING) or REGEX_LIKE.search(text):
                continue
            if _skip(node, parents):
                continue
            found.setdefault(text, []).append(f"{path.name}:{getattr(node, 'lineno', 0)}")
    return found


#: 이어 붙인 문장 속 「자리」 표시 — 글자 아닌 것(이름·호출·숫자)이 들어갈 곳.
HOLE = chr(0)


def _concat_parts(node: ast.AST) -> list[list[str]] | None:
    """「…」 + 「…」 로 이은 문장을 조각 목록으로 — 조건부 조각(a if c else b)은 후보 둘. 자리는 HOLE."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _concat_parts(node.left), _concat_parts(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [[node.value]]
    if isinstance(node, ast.JoinedStr):
        return [["".join(v.value if isinstance(v, ast.Constant) else HOLE for v in node.values)]]
    if isinstance(node, ast.IfExp):
        body, orelse = _concat_parts(node.body), _concat_parts(node.orelse)
        if body and orelse and len(body) == 1 and len(orelse) == 1:
            return [body[0] + orelse[0]]
    return [[HOLE]]


def extract_concatenations() -> set[str]:
    """★ 2026-10-03: 「{카드} · 쓸 수 있는 메모리 약 {n}GB」 + 「(화면 출력이…)」 처럼 + 로 이은 문장은 조각만 뽑혀
    이어진 전체가 사전에 없었다(영어 화면에 그대로 한국어). 이은 전체를 조건 조합마다 하나씩 틀로 뽑는다."""
    import itertools

    newline = chr(10)
    keys: set[str] = set()
    for path in sorted(SRC.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)):
                continue
            parts = _concat_parts(node)
            if not parts or len(parts) < 2:
                continue
            for combo in itertools.product(*parts):
                text = "".join(combo).strip(newline)
                if len(HANGUL.findall(text)) < 2 or len(text) > MAX_LEN or text.lstrip().startswith(MODEL_FACING):
                    continue
                pieces = text.split(HOLE)
                key = "".join(piece + ("{" + str(i) + "}" if i < len(pieces) - 1 else "") for i, piece in enumerate(pieces))
                keys.add(key)
    return keys


if __name__ == "__main__":
    keys = extract()
    for key in extract_concatenations():
        keys.setdefault(key, ["(이은 문장)"])
    files: dict[str, int] = {}
    for where in keys.values():
        name = where[0].split(":")[0]
        files[name] = files.get(name, 0) + 1
    templated = sum(1 for key in keys if re.search(r"\{\d+\}", key))
    print(f"열쇠 {len(keys)}개 (틀 {templated}) · 글자 {sum(len(k) for k in keys):,}")
    for name, count in sorted(files.items(), key=lambda kv: -kv[1])[:25]:
        print(f"{count:5} {name}")
    if "--write" in sys.argv:
        out = ROOT / "scripts" / "i18n_backend_keys.json"
        out.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=1), encoding="utf-8")
        print("썼음:", out)
