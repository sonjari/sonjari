"""`path` 를 빼먹은 코드 도구는 **작업 폴더를 기본값으로** 쓴다 (2026-09-21, 노트북 4B 실측).

## 어떻게 찾았나

8GB 노트북의 Qwen 3.5 4B 로 AURORA 를 돌렸더니 6걸음에 `partial` 로 끝났다:

     1 local_index_codebase   ok
     2 local_write_file       ok    path = "aurora-4b-1/index.html"   ← 17.6KB 진짜 페이지
     3 local_preview_page     FAIL  path_required      ← 인자 `{}`
     4 browser_open           FAIL  browser_url_not_allowed (file:// 로 우회)
     5 local_read_text_file    ok
     6 local_index_codebase   FAIL  path_required      ← 인자 `{}`

**페이지는 만들었다.** 못 본 것은 4B 가 필수 인자를 빼먹어서다. 작업 폴더는 이미 잡에 묶여
있어 물어볼 필요가 없다 — 09-20 에 `local_glob`·`local_grep`·`local_run_project_command`
에 넣은 것과 같은 손질이 이 둘에만 빠져 있었다. **안내문은 안 먹는다**(사고 R) — 도구가 정한다.

작은 모델일수록 인자를 빼먹는다. 무료 티어(8GB·4B)가 제품이므로 이건 그 칸의 문제다.

## 안 고친 것 (기록)

모델이 상대 경로 `aurora-4b-1/index.html` 을 줘서 `aurora-4b-1/aurora-4b-1/index.html` 로
중첩됐다. 「첫 조각이 작업 폴더 이름이면 벗긴다」는 쓰기 동작을 바꾸는 일이고 근거가 n=1 이라
하지 않았다. 같은 모양이 한 번 더 나오면 그때 다룬다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "site"
    work.mkdir()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools, work


def test_preview_without_a_path_opens_index_html(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    (work / "index.html").write_text("<h1>오로라</h1>", encoding="utf-8")
    try:
        served = tools.serve_page({"__job_id": "code-job"})
        assert served["url"].endswith("/index.html")
        assert served["path"] == str((work / "index.html").resolve())
        assert "path" in served.get("note", ""), "어떤 파일을 골랐는지 말해 줘야 다음엔 직접 준다"
    finally:
        tools.stop_serving()


def test_preview_without_a_path_prefers_the_newest_page_when_no_index(tmp_path: Path) -> None:
    import os

    tools, work = _tools(tmp_path)
    old, new = work / "old.html", work / "sub" / "new.html"
    new.parent.mkdir()
    old.write_text("<p>old</p>", encoding="utf-8")
    new.write_text("<p>new</p>", encoding="utf-8")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.utime(new, (1_800_000_000, 1_800_000_000))
    try:
        served = tools.serve_page({"__job_id": "code-job"})
        assert served["url"].endswith("/sub/new.html")
    finally:
        tools.stop_serving()


def test_index_html_wins_over_a_newer_page(tmp_path: Path) -> None:
    """`index.html` 은 사람이 「열어 달라」고 할 때의 기본 문이다."""
    import os

    tools, work = _tools(tmp_path)
    (work / "index.html").write_text("<p>home</p>", encoding="utf-8")
    (work / "other.html").write_text("<p>other</p>", encoding="utf-8")
    os.utime(work / "index.html", (1_700_000_000, 1_700_000_000))
    os.utime(work / "other.html", (1_800_000_000, 1_800_000_000))
    try:
        assert tools.serve_page({"__job_id": "code-job"})["url"].endswith("/index.html")
    finally:
        tools.stop_serving()


def test_preview_without_a_path_and_without_any_page_is_still_refused(tmp_path: Path) -> None:
    """열 것이 없으면 기본값으로 메울 수 없다 — 지어내지 않고 이유를 말한다."""
    tools, work = _tools(tmp_path)
    (work / "notes.txt").write_text("html 이 없다", encoding="utf-8")
    with pytest.raises(ValueError, match="path_required"):
        tools.serve_page({"__job_id": "code-job"})


def test_a_given_path_behaves_exactly_as_before(tmp_path: Path) -> None:
    """★ 좋은 표본 — 경로를 주면 한 글자도 다르지 않다."""
    tools, work = _tools(tmp_path)
    (work / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
    (work / "other.html").write_text("<h1>y</h1>", encoding="utf-8")
    try:
        served = tools.serve_page({"__job_id": "code-job", "path": "other.html"})
        assert served["url"].endswith("/other.html")
        assert "note" not in served
    finally:
        tools.stop_serving()


def test_index_codebase_without_a_path_uses_the_code_workspace(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    (work / "app.py").write_text("def hello():\n    return 1\n", encoding="utf-8")

    out = tools.index_codebase({"__job_id": "code-job", "query": "hello"})

    assert out["action"] == "local_index_codebase"


def test_the_schema_no_longer_calls_path_required() -> None:
    """도구가 받아 주는데 스키마가 「필수」라고 하면 모델은 여전히 채우려다 빼먹는다."""
    tools = LocalComputerTools(JarvisConfig())
    schemas = {item["function"]["name"]: item["function"]["parameters"] for item in tools.ollama_tools}

    for name in ("local_preview_page", "local_index_codebase"):
        assert "path" in schemas[name]["properties"], name
        assert "path" not in (schemas[name].get("required") or []), f"{name}: path 가 아직 필수"


def test_index_codebase_without_a_path_outside_a_code_job_is_still_refused(tmp_path: Path) -> None:
    """코드 작업이 아니면 어디를 색인할지 알 수 없다 — 지금과 같다."""
    tools, _work = _tools(tmp_path)
    with pytest.raises(ValueError, match="path_required"):
        tools.index_codebase({"__job_id": "not-a-code-job", "query": "hello"})
