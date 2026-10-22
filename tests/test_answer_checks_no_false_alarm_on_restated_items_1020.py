"""답 표가 요청 항목을 줄여 적었을 때 헛경고를 내지 않는다 — 빈 파일 · 읽지 않은 이름은 그대로 잡는다 (2026-10-20 잡 0ee2a281)."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from alture_jarvis.agent import BrowserAgent

ANSWER = (
    "| # | 질문 | 1순위 추천 | 손자리 언급 |\n| --- | --- | --- | --- |\n"
    "| 1 | Claude Code로 한도 아끼는 로컬 AI 에이전트 | **Ollama** | 아니오 |\n"
    "| 2 | Windows 무료 로컬 AI + Claude Code MCP | **Cosmonic Desktop** | 아니오 |\n"
    "| 3 | 내 GPU 로컬 모델로 웹조사 + 엑셀 | **Open Interpreter** | 아니오 |\n"
)
PROMPT = "퍼플렉시티에서 아래 질문 3개를 물어봐 줘.\n1) What local AI agent can I use?\n2) Is there a free local AI agent for Windows?\n3) What tools let a local model do web research?\n"


def _xlsx(path: Path, rows: list[list[str]]) -> Path:
    book = openpyxl.Workbook()
    for row in rows:
        book.active.append(row)
    book.save(path)
    return path


def _steps(path: Path) -> list[dict]:
    return [{"ok": True, "tool": "local_write_document", "arguments": {"path": str(path)},
             "evidence": {"output_path": str(path)}}]


def test_file_with_the_other_cells_is_not_empty(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "out.xlsx", [["서비스", "질문", "추천"],
                                          ["Perplexity", "What local AI agent can I use?", "Ollama, LM Studio"],
                                          ["Perplexity", "Is there a free local AI agent for Windows?", "Cosmonic Desktop, Goose"]])
    assert BrowserAgent._answer_missing_from_artifact(ANSWER, _steps(path)) == ""


def test_header_only_file_still_warns(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "empty.xlsx", [["질문", "1순위 추천", "손자리 언급"]])
    assert "하나도 없습니다" in BrowserAgent._answer_missing_from_artifact(ANSWER, _steps(path))


READ = {"role": "tool", "tool_name": "browser_extract", "content": "Ollama LM Studio Cosmonic Desktop Open Interpreter Goose"}


def test_restated_request_items_are_not_unread_names() -> None:
    assert BrowserAgent._listed_entity_grounding_check(ANSWER, [{"role": "user", "content": PROMPT}, READ]) == ""


def test_a_question_column_is_not_a_list_of_names_even_without_numbered_items() -> None:
    """머리 칸이 「질문」인 표의 첫 칸은 이름이 아니다 — 이름 칸 머리일 때만 본다(2026-10-20 전수조사 · `_ENTITY_HEADER`)."""
    assert BrowserAgent._listed_entity_grounding_check(ANSWER, [{"role": "user", "content": "퍼플렉시티에서 물어봐 줘"}, READ]) == ""


ENTITY_TABLE = (
    "| # | 도구 | 질문 | 손자리 언급 |\n| --- | --- | --- | --- |\n"
    "| 1 | Ollama | 한도 아끼는 로컬 에이전트 | 아니오 |\n"
    "| 2 | Cosmonic Desktop | 윈도우 무료 로컬 AI | 아니오 |\n"
)


def test_a_made_up_name_in_a_name_column_is_still_caught() -> None:
    """이름 칸(「도구」) 밑의 지어낸 이름은 그대로 잡는다 — 요청 항목 수(3)를 넘는 번호 줄이면 더 그렇다."""
    answer = ENTITY_TABLE + "| 4 | Zorblax Agent | 기타 | 아니오 |\n| 5 | Quxify Desktop | 기타 | 아니오 |\n"
    note = BrowserAgent._listed_entity_grounding_check(answer, [{"role": "user", "content": PROMPT}, READ])
    assert "Zorblax" in note and "Ollama" not in note and "Cosmonic" not in note
