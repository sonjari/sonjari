"""문서를 쓴 직후 「다시 읽어 견주기」를 **그림자로** 남긴다 (2026-10-15).

`readback.readback_gaps` 는 저장한 파일에서 쓰려던 문장 · 칸이 빠지거나 바뀐 곳을 찾는다. 그런데 문서 쓰기는 받은 것을 일부러
바꾸기도 한다(「확인 불가」 칸 비우기 · 모델의 생각 조각 버리기 · 마크다운 정리) — 그대로 판정에 쓰면 헛경고가 난다. 또 결과에
덧붙인 글은 모델에게 되돌아가 판을 흔든다(10-05 「덧붙인 경고가 맥락을 잃게 함」).

그래서 지금은:
- 도구 결과에는 **아무것도 싣지 않는다**(모델이 못 본다). 「확인됨(verified)」도 바꾸지 않는다.
- 데이터 폴더의 `readback_shadow.jsonl` 에 한 줄을 남긴다 — 파일 · 형식 · 견준 단위 수 · 빠진 것(앞 열 개).
- 일부러 비운 「확인 불가」 칸은 빠진 것으로 세지 않는다.
- 다시 읽기가 실패해도 쓰기는 그대로 성공한다.
실제 판에서 헛경고가 얼마나 나는지 잰 뒤에 판정에 쓸지 정한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path, monkeypatch) -> LocalComputerTools:
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None, raising=False)
    return LocalComputerTools(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents", local_computer_enabled=True,
    ))


def _shadow(tmp_path: Path) -> list[dict]:
    path = tmp_path / "data" / "readback_shadow.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_clean_write_leaves_a_shadow_line_and_nothing_in_the_result(tmp_path: Path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    result = tools.write_document_file({
        "path": "가격.xlsx", "format": "xlsx", "__job_id": "j1",
        "rows": [["가게", "가격"], ["다나와", "129,000원"]],
    })
    assert result["verified"] is True
    assert not any("readback" in key for key in result), "결과에 실으면 모델에게 되돌아간다"
    lines = _shadow(tmp_path)
    assert len(lines) == 1
    assert lines[0]["format"] == "xlsx" and lines[0]["gaps"] == [] and lines[0]["units"] == 4
    assert lines[0]["job"] == "j1"


def test_cells_blanked_on_purpose_are_not_counted_as_missing(tmp_path: Path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    tools.write_document_file({
        "path": "표.md", "format": "md", "__job_id": "j2",
        "blocks": [{"type": "table", "rows": [["가게", "가격"], ["다나와", "확인 불가"]]}],
    })
    assert _shadow(tmp_path)[0]["gaps"] == []


def test_a_format_it_cannot_read_back_is_recorded_as_unchecked(tmp_path: Path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    tools.write_document_file({
        "path": "보고서.hwpx", "format": "hwpx", "__job_id": "j3",
        "blocks": [{"type": "paragraph", "text": "본문입니다."}],
    })
    line = _shadow(tmp_path)[0]
    assert line["gaps"] is None and line["checked"] is False
