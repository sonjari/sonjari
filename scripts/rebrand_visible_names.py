"""사람 눈에 보이는 문자열의 제품 이름만 바꾼다 — 조사까지 (2026-09-15, 자비스 → Ontelic).

    python scripts/rebrand_visible_names.py          # 무엇이 바뀔지 보여만 준다
    python scripts/rebrand_visible_names.py --write  # 실제로 고친다

찾아 바꾸기로는 안 되는 이유: 「자비스」는 받침이 없고 「온텔릭」은 있다. `자비스가` 를 그대로
바꾸면 「온텔릭가」가 된다. 여기서는 조사를 받침에 맞춰 같이 고친다.

- 파이썬: `ast` 로 **문자열 리터럴만**(독스트링·주석 제외) 고친다.
- TS/TSX/Rust/HTML/JSON: 주석 줄을 뺀 줄에서 고친다(코드 식별자 `JarvisClient`·`JARVIS_*` 는 규칙이 안 건드린다).
- 옛 이름을 **알아들어야** 하는 자리(정규식·폴더·연결 이름)는 `brand.py` 에서 손으로 다룬다 —
  이 스크립트는 옛 이름이 든 정규식 리터럴과 정확히 "JARVIS" 인 리터럴(옛 폴더 이름)을 건너뛴다.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NEW_EN = "Ontelic"
NEW_KO = "온텔릭"

# 받침 없는 말 뒤 조사 → 받침 있는 말 뒤 조사. 긴 것부터.
_PARTICLES = [
    ("로부터", "으로부터"), ("로서", "으로서"), ("로써", "으로써"), ("로", "으로"),
    ("라고", "이라고"), ("라는", "이라는"), ("라서", "이라서"), ("라면", "이라면"),
    ("예요", "이에요"), ("였", "이었"), ("랑", "이랑"),
    ("가", "이"), ("는", "은"), ("를", "을"), ("와", "과"), ("다", "이다"), ("야", "아"),
]
_PARTICLE_ALT = "|".join(re.escape(a) for a, _ in _PARTICLES)
_PARTICLE_FIX = dict(_PARTICLES)
_HANGUL = "가-힣"

# 한국어 이름 + 조사(바로 뒤가 한글이 아니거나, 조사 뒤 낱말이 이어져도 조사로 본다)
_KO = re.compile(rf"자비스(?:({_PARTICLE_ALT})(?=[^{_HANGUL}]|$|[{_HANGUL}]))?")
# 영문 이름: 앞뒤가 식별자 글자가 아닐 때만. `ALTURE JARVIS` 를 먼저 본다.
_EN = re.compile(r"(?<![A-Za-z0-9_\-])(?:ALTURE\s+)?JARVIS(?![A-Za-z0-9_\-])")
# 영문 이름 뒤에 띄어 쓴 한 글자 조사(`ALTURE JARVIS 가 …`, `JARVIS 에 연결`)
_EN_SPACED_PARTICLE = re.compile(r"^ (가|는|를|와|로|에|의|에게)(?=[\s,.·)]|$)")
_EN_PARTICLE = re.compile(rf"^({_PARTICLE_ALT}|에게|에서|에|의|도|만|까지|한테)")


def _ko_particle(particle: str | None) -> str:
    return _PARTICLE_FIX.get(particle, particle) if particle else ""


def rebrand(text: str) -> str:
    """한 조각의 사람 문장을 고친다."""
    def ko(match: re.Match[str]) -> str:
        particle = match.group(1)
        # 「자비스다운」 같은 합성은 드물다 — 조사 표에 있는 것만 받침에 맞춘다.
        return NEW_KO + _ko_particle(particle)

    text = _KO.sub(ko, text)

    out: list[str] = []
    pos = 0
    for match in _EN.finditer(text):
        out.append(text[pos:match.start()])
        rest = text[match.end():]
        spaced = _EN_SPACED_PARTICLE.match(rest)
        glued = _EN_PARTICLE.match(rest)
        if glued:
            # `JARVIS에게` · `JARVIS로` — 한국어 문장 속 이름
            particle = glued.group(1)
            out.append(NEW_KO + _ko_particle(particle))
            pos = match.end() + len(particle)
            continue
        if spaced:
            particle = spaced.group(1)
            out.append(NEW_KO + _ko_particle(particle))
            pos = match.end() + len(spaced.group(0))
            continue
        if re.match(rf"^ [{_HANGUL}]", rest) and not match.group(0).startswith("ALTURE"):
            # `JARVIS 작업 완료` · `JARVIS 창을` — 한국어 낱말을 꾸미는 이름
            out.append(NEW_KO)
        else:
            # 창 제목·상표 자리(`ALTURE JARVIS`, `JARVIS · 제목`, 홀로 선 `JARVIS`)
            out.append(NEW_EN)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def describe(where: str, old: str, new: str) -> list[str]:
    """바뀐 자리만 앞뒤 몇 글자와 함께 보여 준다(긴 프롬프트도 한 줄씩)."""
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
    if value.strip().strip("\"'") == "JARVIS":  # 옛 폴더 이름 — brand.product_dir 가 다룬다
        return True
    if re.search(r"자비스\||\|자비스|\(자비스|JARVIS\|", value):  # 옛 이름을 알아듣는 정규식
        return True
    return False


# ── 파이썬 ────────────────────────────────────────────────────────────────
def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Constant, ast.JoinedStr)):
                    ids.add(id(stmt.value))  # 독스트링·떠 있는 문자열은 주석과 같다
    return ids


def python_spans(source: str) -> list[tuple[int, int]]:
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    lines = source.encode("utf-8").splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    spans: list[tuple[int, int]] = []
    inside_fstring: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            inside_fstring.update(id(v) for v in ast.walk(node) if v is not node)
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


# ── 줄 단위(TS/TSX/Rust/HTML/JSON/MD) ─────────────────────────────────────
_COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|\{/\*)")


def convert_lines(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    changes: list[str] = []
    in_block = False
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        stripped = line.lstrip()
        if in_block:
            if "*/" in line:
                in_block = False
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
        if p.suffix in {".ts", ".tsx", ".json"} and ".test." not in p.name:
            found.append((p, "lines"))
    for p in sorted((REPO / "ui" / "src-tauri" / "src").rglob("*.rs")):
        found.append((p, "lines"))
    for rel in ("ui/index.html", "ui/src-tauri/tauri.conf.json", "ui/src-tauri/tauri.msix.conf.json",
                "ui/src-tauri/tauri.pilot.conf.json", "ui/src-tauri/tauri.e2e.conf.json",
                "skills/vendor/alture/document-craft/SKILL.md", "knowledge/JARVIS_PROFILE.md"):
        found.append((REPO / rel, "lines"))
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    total: list[str] = []
    for path, kind in targets():
        new, changes = convert_python(path) if kind == "py" else convert_lines(path)
        if changes:
            total.extend(changes)
            if args.write:
                if b"\r\n" in path.read_bytes():  # 줄끝을 원래대로 — 파일 전체가 diff 로 뜨지 않게
                    new = new.replace("\r\n", "\n").replace("\n", "\r\n")
                path.write_text(new, encoding="utf-8", newline="")
    sys.stdout.buffer.write(("\n".join(total) + f"\n\n{len(total)} changes\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
