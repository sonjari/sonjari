"""사람 눈에 보이는 제품 이름만 바꾼다 — 조사까지 (2026-09-29, Ontelic → 손자리 / Sonjari · 전략안 §55-9).

    python scripts/rebrand_to_sonjari.py          # 무엇이 바뀔지 보여만 준다
    python scripts/rebrand_to_sonjari.py --write  # 실제로 고친다

09-15 의 `rebrand_visible_names.py`(자비스 → 온텔릭)와 같은 틀, 조사 방향만 반대다: 「온텔릭」은 받침이 있고 「손자리」는 없다.
`온텔릭이` → `손자리가`, `온텔릭은` → `손자리는`, `온텔릭으로` → `손자리로`. 옛 개명이 남긴 틀린 조사(`온텔릭는`·`온텔릭가`)는
받침 없는 쪽 조사라 그대로 두면 맞게 된다.

**1단계만**(보이는 이름). 이미 깔린 곳이 깨지는 식별자는 건드리지 않는다 — 패키지 `RoboMetaFit.Ontelic`·실행 파일 `Ontelic.exe`·
데이터 폴더 `%LOCALAPPDATA%\\Ontelic`·MCP 이름 `ontelic`(소문자는 이 스크립트가 아예 안 본다). 그 옮기기는 공개 직전 2단계.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NEW_EN = "Sonjari"
NEW_KO = "손자리"

# 받침 있는 말 뒤 조사 → 받침 없는 말 뒤 조사. 긴 것부터(「이다」가 「이」보다 먼저).
_PARTICLES = [
    ("으로부터", "로부터"), ("으로서", "로서"), ("으로써", "로써"), ("으로", "로"),
    ("이라고", "라고"), ("이라는", "라는"), ("이라서", "라서"), ("이라면", "라면"), ("이라", "라"),
    ("이에요", "예요"), ("이었", "였"), ("이랑", "랑"), ("이야", "야"), ("이지", "지"), ("이면", "면"),
    ("이나", "나"), ("이든", "든"), ("이다", "다"),
    ("이", "가"), ("은", "는"), ("을", "를"), ("과", "와"), ("아", "야"),
]
_PARTICLE_ALT = "|".join(re.escape(a) for a, _ in _PARTICLES)
_PARTICLE_FIX = dict(_PARTICLES)

_KO = re.compile(rf"온텔릭(?:({_PARTICLE_ALT}))?")
# 영문 이름: 식별자·경로·패키지 이름 속은 안 건드린다(`RoboMetaFit.Ontelic`·`Ontelic.exe`·`\\Ontelic\\`·`OntelicMsixTest`).
_EN = re.compile(r"(?<![A-Za-z0-9_\-.\\/])Ontelic(?![A-Za-z0-9_\-\\/])(?!\.[A-Za-z])")
# 영문 이름 바로 뒤에 붙은 한국어 조사(`Ontelic이`·`Ontelic 이` 는 한국어 문장 속 이름)
_EN_GLUED = re.compile(rf"^ ?({_PARTICLE_ALT})(?![가-힣])")


def _fix(particle: str | None) -> str:
    return _PARTICLE_FIX.get(particle, particle) if particle else ""


def rebrand(text: str) -> str:
    text = _KO.sub(lambda m: NEW_KO + _fix(m.group(1)), text)
    out: list[str] = []
    pos = 0
    for match in _EN.finditer(text):
        out.append(text[pos:match.start()])
        rest = text[match.end():]
        glued = _EN_GLUED.match(rest)
        if glued:
            out.append(NEW_KO + _fix(glued.group(1)))
            pos = match.end() + len(glued.group(0))
            continue
        out.append(NEW_EN)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def describe(where: str, old: str, new: str) -> list[str]:
    import difflib

    lines = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        before = old[max(0, i1 - 18):i1].replace("\n", "⏎")
        after = old[i2:i2 + 18].replace("\n", "⏎")
        lines.append(f"{where}: …{before}[{old[i1:i2]}→{new[j1:j2]}]{after}…")
    return lines


def _skip_literal(value: str) -> bool:
    # 옛 이름을 알아듣는 정규식(`온텔릭|자비스`)과 옛 이름 그 자체(폴더·패키지 이름)는 brand.py 가 다룬다.
    if value.strip().strip("\"'") in {"Ontelic", "온텔릭"}:
        return True
    return bool(re.search(r"온텔릭\||\|온텔릭|\(온텔릭|Ontelic\||\|Ontelic", value))


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Constant, ast.JoinedStr)):
                    ids.add(id(stmt.value))
    return ids


def python_spans(source: str) -> list[tuple[int, int]]:
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    lines = source.encode("utf-8").splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    inside_fstring: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            inside_fstring.update(id(v) for v in ast.walk(node) if v is not node)
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if id(node) in skip or id(node) in inside_fstring:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) or isinstance(node, ast.JoinedStr):
            start = starts[node.lineno - 1] + node.col_offset
            end = starts[node.end_lineno - 1] + node.end_col_offset
            spans.append((start, end))
    return spans


def convert_python(path: Path) -> tuple[str, list[str]]:
    source = path.read_text(encoding="utf-8")
    raw = source.encode("utf-8")
    changes: list[str] = []
    for start, end in sorted(python_spans(source), reverse=True):
        piece = raw[start:end].decode("utf-8")
        if _skip_literal(piece):
            continue
        new = rebrand(piece)
        if new != piece:
            line = raw[:start].count(b"\n") + 1
            changes.extend(describe(f"{path.relative_to(REPO).as_posix()}:{line}", piece, new))
            raw = raw[:start] + new.encode("utf-8") + raw[end:]
    return raw.decode("utf-8"), changes


_COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|\{/\*)")
_IDENTIFIER_LINE = re.compile(r"RUNTIME_DIR_NAME|STARTUP_TASK_ID|\"identifier\"|mainBinaryName|productName")


def convert_lines(path: Path, *, prose: bool = False) -> tuple[str, list[str]]:
    """코드 파일은 주석 줄을 건너뛴다. 사람이 읽는 문서(`prose`)는 전부 고친다."""
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    changes: list[str] = []
    in_block = False
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        if _IDENTIFIER_LINE.search(line):
            out.append(line)  # 설치 이름(데이터 폴더·자동 시작·식별자) — 2단계에서 옮긴다
            continue
        if not prose:
            stripped = line.lstrip()
            if in_block:
                in_block = "*/" not in line
                out.append(line)
                continue
            if stripped.startswith("/*") and "*/" not in line:
                in_block = True
                out.append(line)
                continue
            if _COMMENT_LINE.match(line):
                out.append(line)
                continue
            code, sep, comment = line.partition(" // ")
            new = rebrand(code) + sep + comment
        else:
            new = rebrand(line)
        if new != line:
            changes.extend(describe(f"{path.relative_to(REPO).as_posix()}:{n}", line, new))
        out.append(new)
    return "".join(out), changes


def targets() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for p in sorted((REPO / "src" / "alture_jarvis").rglob("*.py")):
        if p.name != "brand.py":
            found.append((p, "py"))
    for p in sorted((REPO / "ui" / "src").rglob("*")):
        if p.suffix in {".ts", ".tsx", ".json", ".css"} and ".test." not in p.name:
            found.append((p, "lines"))
    for p in sorted((REPO / "ui" / "src-tauri" / "src").rglob("*.rs")):
        found.append((p, "lines"))
    for rel in ("ui/index.html",):
        found.append((REPO / rel, "lines"))
    # 사람이 읽는 스킬·안내 문서(모델에게 가는 글도 사람 글이다)
    for base in ("skills", "packs", "recipes", "knowledge"):
        for p in sorted((REPO / base).rglob("*")):
            if p.suffix in {".md", ".json"} and p.is_file():
                found.append((p, "prose"))
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    total: list[str] = []
    for path, kind in targets():
        if kind == "py":
            new, changes = convert_python(path)
        else:
            new, changes = convert_lines(path, prose=(kind == "prose"))
        if changes:
            total.extend(changes)
            if args.write:
                if b"\r\n" in path.read_bytes():
                    new = new.replace("\r\n", "\n").replace("\n", "\r\n")
                path.write_text(new, encoding="utf-8", newline="")
    sys.stdout.buffer.write(("\n".join(total) + f"\n\n{len(total)} changes\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
