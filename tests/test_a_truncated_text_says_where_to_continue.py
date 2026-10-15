"""잘린 글 파일은 **어디서 이어 읽을지**를 같이 준다 (2026-09-29 밤, 코워크 전략안 판).

## 무슨 일이 있었나

대표가 코워크에 전략안(`JARVIS_전략안_20260907.md`, 20만 자)을 읽고 외부 조사까지 해 달라고 했다.
걸음 기록(잡 25a4a17b): `local_read_text_file` 을 **같은 경로로 세 번** 불렀고 세 번 다 앞 15,000자만
받았다(`truncated: true`). 답에는 「전략안 뒷부분(§42~끝) 읽지 못함(15,000자 제한으로 잘림)」.

잘린 `.py` 에는 함수 목차와 줄 범위가 붙어 「line_start 로 필요한 구간을 다시 읽어라」가 나가는데,
`.md` 에는 `truncated` 하나뿐이었다 — **다음에 어디를 부르라는 말이 없었다.**

## 고친 것

잘린 글 파일이면 전체 줄 수와 **이어 읽을 줄 번호**를 준다. 마크다운이면 제목 목차(제목 → 줄 번호)도 준다.
"""
from __future__ import annotations

import pathlib
import tempfile

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _big_markdown(root: pathlib.Path) -> pathlib.Path:
    lines = ["# 전략안", ""]
    for section in range(1, 61):
        lines.append(f"## §{section} 절 제목 {section}")
        lines.extend(f"{section}절 본문 줄 {n} — 온텔릭 손자리 측정 공개 앱." for n in range(12))
        lines.append("")
    path = root / "strategy.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_a_truncated_markdown_says_where_to_continue_and_gives_headings() -> None:
    root = pathlib.Path(tempfile.mkdtemp())
    path = _big_markdown(root)
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(root)))
    first = tools.read_text_file({"path": str(path)})
    assert first["truncated"] is True
    total = len(path.read_text(encoding="utf-8").splitlines())
    assert first["total_lines"] == total
    assert first["next_line_start"] >= first["line_end"] > 1
    assert f"line_start={first['next_line_start']}" in first["instruction"]
    headings = first["headings"]
    assert any(item.startswith("## §60 ") for item in headings), headings[-3:]
    assert all(" (" in item and item.endswith(")") for item in headings)

    # 안내대로 부르면 **뒤쪽**이 온다.
    second = tools.read_text_file({"path": str(path), "line_start": first["next_line_start"]})
    assert "60절 본문" in second["content"] or second["line_end"] < total


def test_a_short_file_is_not_decorated() -> None:
    root = pathlib.Path(tempfile.mkdtemp())
    path = root / "short.md"
    path.write_text("# 제목\n\n짧은 글\n", encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(root)))
    result = tools.read_text_file({"path": str(path)})
    assert not result.get("truncated")
    assert "headings" not in result and "next_line_start" not in result


def test_a_truncated_plain_text_still_says_where_to_continue() -> None:
    root = pathlib.Path(tempfile.mkdtemp())
    path = root / "log.txt"
    path.write_text("\n".join(f"{n} 번째 줄 내용이 여기 있습니다" for n in range(3000)), encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(root)))
    result = tools.read_text_file({"path": str(path)})
    assert result["truncated"] is True
    assert f"line_start={result['next_line_start']}" in result["instruction"]
