"""답을 대신 파일로 옮길 때, 사람이 댄 파일 이름 · 자리를 쓴다 (2026-10-14 레딧 홍보 규칙 조사).

「…파일 이름은 레딧_홍보규칙_조사.xlsx 로 문서 폴더에 저장해」였는데 모델이 파일을 안 만들고 표로만 답했고, 대신 저장
(`_forced_artifact_decision`)이 답의 첫 문장으로 이름을 지어 `JARVIS\\9개까지_확인했고_나머지_15개(….xlsx` 가 나왔다.
사람은 자기가 댄 이름으로 파일을 찾는다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import _forced_artifact_decision
from alture_jarvis.plan import check as check_plan, extract as extract_plan

ANSWER = """9개까지 확인했고, 나머지 15개는 이번 판에서 열지 못했습니다.

| 게시판 | 구독자 수 | 셀프 홍보 |
| --- | --- | --- |
| LocalLLaMA | 848,875 | 제한 허용 |
| LocalLLM | 243,901 | 제한 허용 |
| ollama | 140,531 | 규칙에 언급 없음 |

LocalLLaMA 와 LocalLLM 은 셀프 홍보를 전체 글의 10% 이하로 묶고, 소속을 밝히라고 적어 두었습니다. ollama 는 규칙 페이지에
규칙 항목이 없었습니다. 나머지 게시판은 이번 판에서 열지 못했습니다.
"""

STEPS = [
    {"tool": "browser_extract", "ok": True, "evidence": {"url": f"https://old.reddit.com/r/{name}/about/rules"}}
    for name in ("LocalLLaMA", "LocalLLM", "ollama")
]


def _call(prompt: str) -> dict:
    plan = extract_plan(prompt, has_named_source=True)
    sources = [str((s.get("evidence") or {}).get("url") or "") for s in STEPS]
    results = check_plan(plan, sources=sources, steps=STEPS)
    call, reason = _forced_artifact_decision(results, STEPS, ANSWER, prompt)
    assert call is not None, reason
    return call[1]


def test_a_named_file_in_a_named_folder_goes_there_with_that_name() -> None:
    args = _call("레딧 게시판 3곳의 규칙을 읽어 엑셀로 정리해 줘. 파일 이름은 레딧_홍보규칙_조사.xlsx 로 문서 폴더에 저장해.")
    assert Path(args["path"]) == Path.home() / "Documents" / "레딧_홍보규칙_조사.xlsx"


def test_a_full_path_keeps_the_name() -> None:
    args = _call(r"레딧 게시판 3곳의 규칙을 읽어 엑셀로 정리해 줘. 파일은 C:\Users\someone\Documents\레딧_홍보규칙_조사_2.xlsx 로 저장해.")
    assert Path(args["path"]).name == "레딧_홍보규칙_조사_2.xlsx"


def test_no_named_file_keeps_the_old_title_rule() -> None:
    args = _call("레딧 게시판 3곳의 규칙을 읽어 엑셀로 정리해 줘.")
    assert args["path"].endswith(".xlsx") and "/" not in args["path"] and "\\" not in args["path"]
    assert args["path"].startswith("9개까지")


def test_a_name_with_another_format_keeps_its_stem_only() -> None:
    args = _call("레딧 게시판 3곳의 규칙을 읽어 엑셀로 정리해 줘. 이름은 홍보규칙.csv 로.")
    assert Path(args["path"]).name in {"홍보규칙.xlsx", "홍보규칙.csv"}
