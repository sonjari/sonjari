"""메신저가 못 그리는 마크다운을 읽히는 모양으로 바꾼다 (2026-10-18).

★ 대표 첫 시험(거창 놀러 갈 곳 · 가성비 밥집): 디스코드는 마크다운 **표**를 그리지 못해 `| 장소 | 포인트 |` · `|---|---|` 가
  글자 그대로 나왔다. 텔레그램 · 카카오톡도 표가 없다. 그래서 메신저로 나가기 직전에 표를 **줄마다 한 항목인 목록**으로 바꾼다.
  답 본문(PC 앱 · 기록)은 그대로다 — 바꾸는 것은 메신저로 나가는 사본뿐이다.

모양:
- 칸이 둘이면  `• **첫 칸** — 둘째 칸`
- 칸이 셋 이상이면  `• **첫 칸** — 머리2: 값2 · 머리3: 값3`  (빈 칸 · 「—」 · 「-」 은 뺀다)
코드 칸(```) 안의 표는 건드리지 않는다.
"""

from __future__ import annotations

import re

_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_SEPARATOR_CELL = re.compile(r"^\s*:?-{2,}:?\s*$")
_EMPTY_CELL = {"", "-", "—", "–", "N/A", "n/a"}
_BOLD = re.compile(r"^\*\*(.+)\*\*$")


def _cells(line: str) -> list[str] | None:
    match = _ROW.match(line)
    if not match:
        return None
    return [cell.strip() for cell in match.group(1).split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_CELL.match(cell) for cell in cells)


def _title(cell: str) -> str:
    bare = _BOLD.match(cell)
    inner = bare.group(1) if bare else cell
    return f"**{inner}**" if inner else ""


def _render(header: list[str], rows: list[list[str]]) -> list[str]:
    out: list[str] = []
    for row in rows:
        cells = row + [""] * (len(header) - len(row))
        title = _title(cells[0])
        rest = [(header[index] if index < len(header) else "", cell) for index, cell in enumerate(cells[1:], 1)]
        rest = [(name, value) for name, value in rest if value not in _EMPTY_CELL]
        if len(header) <= 2:
            body = " · ".join(value for _name, value in rest)
        else:
            body = " · ".join(f"{name}: {value}" if name else value for name, value in rest)
        line = "• " + (title or "")
        if body:
            line += (" — " if title else "") + body
        out.append(line.rstrip())
    return out


def tables_to_lists(text: str) -> str:
    """마크다운 표(머리줄 + 구분줄 + 줄들)를 목록으로. 표가 없으면 글을 그대로 돌려준다."""
    lines = str(text or "").split("\n")
    out: list[str] = []
    in_code = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append(line)
            index += 1
            continue
        header = None if in_code else _cells(line)
        separator = _cells(lines[index + 1]) if header is not None and index + 1 < len(lines) else None
        if header is None or separator is None or not _is_separator(separator):
            out.append(line)
            index += 1
            continue
        rows: list[list[str]] = []
        index += 2
        while index < len(lines):
            cells = _cells(lines[index])
            if cells is None:
                break
            if not _is_separator(cells):
                rows.append(cells)
            index += 1
        out.extend(_render(header, rows))
    return "\n".join(out)
