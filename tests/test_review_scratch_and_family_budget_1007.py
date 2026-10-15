"""어려운 코딩 과제에서 나온 둘 (2026-10-07 사다리 L7·L8, 3판씩).

1. 검토 턴이 사용자 폴더에 만든 확인용 파일이 남는다 — 요청문에 「지워라」가 있는데 만든 6판 중 2판만 지웠다.
   검토가 시작된 뒤 새로 만든 파일은 판이 끝날 때 하네스가 치운다.
2. 운영 모델의 생각 예산이 표에 없어 Gemma 기준 8,000자로 돌았다 — 한 턴이 예산까지 생각하고 끊겨 17~26초씩 버렸다.
   표의 이름 맞추기는 `hf.co/<올린 사람>/<모델>` 같은 이름에 가족 이름이 안 맞았다.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import _review_scratch_files
from alture_jarvis.config import DEFAULT_THINKING_BUDGETS, JarvisConfig
from alture_jarvis.ollama import OllamaClient


def _write(path: Path, *, created: bool) -> dict:
    return {"tool": "local_write_file", "ok": True, "evidence": {"output_path": str(path), "created": created}}


def _edit(path: Path) -> dict:
    return {"tool": "local_apply_edit", "ok": True, "evidence": {"path": str(path)}}


def _delete(path: Path) -> dict:
    return {"tool": "local_delete_file", "ok": True, "evidence": {"path": str(path)}}


def _run(command: str) -> dict:
    return {"tool": "local_run_project_command", "ok": True, "evidence": {"stdout": command}}


def test_a_check_file_made_during_review_is_scratch(tmp_path: Path) -> None:
    report, tests, probe = tmp_path / "report.py", tmp_path / "test_cli.py", tmp_path / "_verify.py"
    for item in (report, tests, probe):
        item.write_text("x = 1\n", encoding="utf-8")
    steps = [_write(report, created=False), _write(tests, created=True), _run("pytest"),      # 여기까지가 시킨 일
             _write(probe, created=True), _run("python _verify.py")]                           # 검토

    assert _review_scratch_files(steps, since=3, request_text="report.py 를 고쳐서 통과시켜") == [str(probe)]


def test_files_made_before_the_review_are_the_work_itself(tmp_path: Path) -> None:
    tests = tmp_path / "test_cli.py"
    tests.write_text("x = 1\n", encoding="utf-8")
    steps = [_write(tests, created=True), _run("pytest")]

    assert _review_scratch_files(steps, since=2, request_text="고쳐줘") == []
    assert _review_scratch_files(steps, since=-1, request_text="고쳐줘") == [], "검토가 없던 판은 건드리지 않는다"


def test_what_the_job_already_removed_or_only_edited_is_left_alone(tmp_path: Path) -> None:
    gone, existing = tmp_path / "_probe.py", tmp_path / "report.py"
    existing.write_text("x = 1\n", encoding="utf-8")
    steps = [_run("pytest"), _write(gone, created=True), _delete(gone), _write(existing, created=False)]

    assert _review_scratch_files(steps, since=1, request_text="고쳐줘") == []


def test_a_file_the_user_asked_for_by_name_is_kept(tmp_path: Path) -> None:
    demo = tmp_path / "demo.py"
    demo.write_text("print(1)\n", encoding="utf-8")
    steps = [_run("pytest"), _write(demo, created=True), _run("python demo.py")]

    assert _review_scratch_files(steps, since=1, request_text="고친 뒤 demo.py 도 만들어서 돌려봐") == []


def test_a_new_module_the_review_fix_depends_on_is_kept(tmp_path: Path) -> None:
    """검토가 구현을 고치면서 새 모듈을 만들었다 — 고친 파일이 그 이름을 쓰면 확인용 파일이 아니다."""
    report, helper, probe = tmp_path / "report.py", tmp_path / "amounts.py", tmp_path / "_edge_probe.py"
    report.write_text("from amounts import parse_amount\n", encoding="utf-8")
    helper.write_text("def parse_amount(text):\n    return 0\n", encoding="utf-8")
    probe.write_text("print(1)\n", encoding="utf-8")
    steps = [_run("pytest"), _write(helper, created=True), _edit(report), _write(probe, created=True), _run("python _edge_probe.py")]

    assert _review_scratch_files(steps, since=1, request_text="report.py 를 고쳐줘") == [str(probe)]


def test_the_run_loop_removes_them_through_the_delete_tool_and_says_so() -> None:
    source = inspect.getsource(agent_module.BrowserAgent.run)
    clean = source.index("for scratch_path in _review_scratch_files(steps, code_review_requested_step, asked):")
    paint = source.index('if origin == "workspace":\n            paint_answer_apart(self.events, job_id, answer)')
    assert clean < paint, "답을 내놓기 전에 치우고, 치웠다는 말이 그 답에 실린다"
    block = source[clean: clean + 1100]
    assert 'self.gateway.execute("local_delete_file", {"path": scratch_path}, job_id=job_id)' in block, "도구로 지운다 — 백업이 남는다"
    assert "되돌릴 수 있습니다" in block and "can be undone" in block


def _client(**budgets: int) -> OllamaClient:
    client = OllamaClient.__new__(OllamaClient)
    client.config = SimpleNamespace(ollama_thinking_char_budget=8000, agent_thinking_policy="always",
                                    ollama_thinking_budget_by_model=budgets or dict(DEFAULT_THINKING_BUDGETS))
    return client


def test_the_operating_model_family_has_a_measured_budget() -> None:
    assert DEFAULT_THINKING_BUDGETS["ornith"] == 3000
    assert JarvisConfig().ollama_thinking_budget_by_model["ornith"] == 3000


def test_a_family_name_matches_a_model_pulled_from_a_hub() -> None:
    client = _client()

    assert client._thinking_budget_for("hf.co/someone/Ornith-1.5-35B-A3B-GGUF:IQ4_XS") == 3000
    assert client._thinking_budget_for("hf.co/someone/Qwen3.6-35B-A3B-GGUF:Q4_K_M") == 3000
    assert client._thinking_budget_for("qwen3.6:35b-a3b") == 3000, "레지스트리 이름은 예전 그대로 맞는다"
    assert client._thinking_budget_for("hf.co/someone/Some-Other-Model-GGUF") == 8000, "표에 없는 가족은 기본값이다"
    assert client._thinking_budget_for("hf.co/ornith-fans/Gemma-4-12B-GGUF") == 8000, "올린 사람 이름에 든 낱말로는 안 맞는다"
