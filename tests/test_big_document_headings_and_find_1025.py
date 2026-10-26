"""큰 문서: 목차에서 `##` 절을 버리지 않는다 · 파일 안에서 낱말로 찾는다 (2026-10-25 대표 판 0064b1b3).

「전략안 뒷단 쫙 읽고 유입 전략」 판이 기록 11만 토큰까지 쌓였다. 전략안은 `##` 제목이 257개라 80개를 넘었고, 예전 규칙은
그때 `#` 제목만 남겨 최근 절(§55-6 · §55-25 같은 유입 이야기)이 목차에서 통째로 사라졌다. 모델은 갈 곳을 몰라 앞에서부터
4만 자씩 읽었다.
"""
from __future__ import annotations

import pathlib
import tempfile

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools, markdown_headings


def _strategy_like(root: pathlib.Path, sections: int = 260) -> pathlib.Path:
    lines = ["# 전략안", ""]
    for n in range(1, sections + 1):
        topic = "유입 채널 다시 보기" if n in (6, 25) else f"측정 이야기 {n}"
        lines.append(f"## §55-{n} 2026-10-{(n % 28) + 1:02d} 새벽 — {topic}: 순서와 조건 (대표 결정)")
        lines.extend(f"{n}절 본문 {k} — 레딧 · 깃허브 · 스토어 숫자." for k in range(6))
        if n == 25:
            lines.append("받는 그릇: 깃허브 토론 게시판이 첫 그릇이 될 수 있다.")
        lines.append("")
    path = root / "전략안.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _tools(root: pathlib.Path) -> LocalComputerTools:
    return LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(root)))


def test_second_level_sections_stay_in_the_outline_when_there_are_many() -> None:
    root = pathlib.Path(tempfile.mkdtemp())
    path = _strategy_like(root)
    first = _tools(root).read_text_file({"path": str(path)})
    headings = first["headings"]
    assert any("§55-25" in item and "유입 채널" in item for item in headings), "최근 `##` 절이 목차에 있어야 한다"
    assert len(headings) > 200 and any("§55-260" in item for item in headings), "글자 상한 안에서 최근 절부터 남긴다"
    assert not any("2026-10-" in item for item in headings), "날짜는 떼서 짧게"
    assert "find" in first["instruction"]


def test_the_outline_is_capped_by_characters_and_keeps_the_newest_sections() -> None:
    lines = ["# 맨 위"] + [f"## §{n} " + "아주 긴 제목 " * 6 for n in range(1, 1001)]
    kept = markdown_headings(lines, budget=3_000)
    assert sum(len(item) + 2 for item in kept) <= 3_000
    assert kept[0].startswith("# 맨 위")
    assert any(item.startswith("## §1000 ") for item in kept), "가장 최근 절이 남는다"
    assert not any(item.startswith("## §1 ") for item in kept)


def test_find_returns_matching_lines_with_their_section_not_the_body() -> None:
    root = pathlib.Path(tempfile.mkdtemp())
    path = _strategy_like(root)
    found = _tools(root).read_text_file({"path": str(path), "find": ["받는 그릇", "유입", "없는말"]})
    text = found["content"]
    assert "받는 그릇" in text and "§55-25" in text, text[:400]
    assert found["find"]["hits"]["유입"] == 2 and found["find"]["missed"] == ["없는말"]
    assert "본문 0 —" not in text, "본문은 싣지 않는다"
    assert len(text) < 6_200


def test_a_line_range_still_reads_that_range() -> None:
    root = pathlib.Path(tempfile.mkdtemp())
    path = _strategy_like(root)
    part = _tools(root).read_text_file({"path": str(path), "line_start": 3, "line_end": 6})
    assert part["line_start"] == 3 and part["line_end"] == 6 and "1절 본문" in part["content"]


def test_the_tool_schema_offers_find() -> None:
    tools = LocalComputerTools(JarvisConfig())
    spec = next(tool for tool in tools.ollama_tools if tool["function"]["name"] == "local_read_text_file")
    assert "find" in spec["function"]["parameters"]["properties"]
