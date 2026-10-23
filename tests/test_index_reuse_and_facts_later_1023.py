"""코드 판 첫 글자 줄이기 둘 (2026-10-23 대표 — 「질문마다 색인 · 사실 뽑기가 붙잡는다」).

1. 색인: 끝까지 훑은 지 1분 안이고 손자리가 그 뒤 아무것도 안 바꿨으면 다시 훑지 않는다. 손자리의 쓰기 · 지우기 · 명령 도구는
   시작할 때 `CodeIndex.note_write()` 를 불러 다음 질의가 다시 훑게 한다. 지도(`repo_card`)도 같은 규칙을 탄다.
2. 사실 뽑기: 판을 끝내기 **전에** 그 자리에서 기다리며 돌던 것을 판이 끝난 뒤 조용할 때로 옮긴다. 사람 일이 오면 끊기고(`None`)
   다시 한다. 앱이 실제로 시작되지 않은 런타임(시험)은 예전처럼 그 자리에서 한다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis import local_computer, runtime
from alture_jarvis.code_index import CodeIndex


def test_every_tool_that_can_change_the_repo_tells_the_index() -> None:
    for name in ("write_file", "apply_edit", "delete_file", "run_project_command", "run_shell"):
        source = inspect.getsource(getattr(local_computer.LocalComputerTools, name))
        assert "CodeIndex.note_write()" in source, name
    # 읽기 도구는 알리지 않는다 — 알리면 건너뛰기가 한 번도 안 산다.
    for name in ("read_text_file", "grep_files", "index_codebase"):
        assert "note_write" not in inspect.getsource(getattr(local_computer.LocalComputerTools, name)), name


def test_the_repo_card_reuses_a_fresh_refresh_too() -> None:
    source = inspect.getsource(local_computer.LocalComputerTools.repo_card)
    assert "_reused_backlog(resolved) is None" in source


def test_a_write_during_the_scan_is_not_lost(tmp_path: Path) -> None:
    """훑는 도중에 쓴 파일은 놓쳤을 수 있다 — 기록하는 쓰기 횟수는 **시작할 때** 값이라 다음 질의가 다시 훑는다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    index = CodeIndex(tmp_path / "index")
    original_walk = __import__("os").walk

    def walk_and_write(*args, **kwargs):  # noqa: ANN002, ANN003
        CodeIndex.note_write()  # 훑는 사이에 손자리가 파일을 썼다
        yield from original_walk(*args, **kwargs)

    import alture_jarvis.code_index as module

    module.os.walk, saved = walk_and_write, module.os.walk
    try:
        index.refresh(repo.resolve())
    finally:
        module.os.walk = saved
    assert index._reused_backlog(repo.resolve()) is None


class _State:
    def __init__(self, state: str) -> None:
        self.state = state


def _fake_runtime(calls: list[str], *, started: bool) -> runtime.JarvisRuntime:
    fake = runtime.JarvisRuntime.__new__(runtime.JarvisRuntime)
    fake.__dict__["_started_for_real"] = started

    def learn(*args, **kwargs):  # noqa: ANN002, ANN003
        calls.append("ask" if kwargs.get("ask") else "now")
        return None

    fake._learn_facts = learn  # type: ignore[method-assign]
    return fake


def test_in_tests_facts_are_still_learned_on_the_spot() -> None:
    calls: list[str] = []
    fake = _fake_runtime(calls, started=False)
    runtime.JarvisRuntime._learn_facts_soon(fake, "s1", "질문", "답", 1, 2)
    assert calls == ["now"]


def test_a_cancelled_extraction_says_so_instead_of_failing(tmp_path: Path) -> None:
    """뒤로 미룬 부름이 사람 일에 끊기면(`None`) 「cancelled」 — 실패도 아니고 저장도 안 한다(부르는 쪽이 다시 한다)."""
    fake = runtime.JarvisRuntime.__new__(runtime.JarvisRuntime)
    fake.config = type("C", (), {"fact_learning_enabled": True})()
    published: list[tuple[str, dict]] = []
    fake.events = type("E", (), {"publish": lambda self, name, payload: published.append((name, payload))})()
    result = runtime.JarvisRuntime._learn_facts(
        fake, "s1", "나는 여수에 산다. 앞으로 답은 짧게 해 줘.", "알겠습니다.", 1, 2, ask=lambda system, user: None,
    )
    assert result == "cancelled"


def test_the_job_path_no_longer_waits_for_fact_extraction() -> None:
    source = inspect.getsource(runtime.JarvisRuntime)
    assert "self._learn_facts_soon(" in source
    # 판을 끝내는 길에서 그 자리 부름(`self._learn_facts(` 바로 부르기)은 `_learn_facts_soon` 안에만 남는다.
    outside = source.replace(inspect.getsource(runtime.JarvisRuntime._learn_facts_soon), "")
    assert "self._learn_facts(\n" not in outside and "self._learn_facts(session_id" not in outside


def test_the_late_extraction_uses_the_same_model_and_options_as_before_and_does_not_rewarm() -> None:
    """다른 모델 · 다른 창 크기로 부르면 모델을 다시 올린다 — 일반 부르기가 고르는 그대로(`_selected_model` · `_options`)."""
    source = inspect.getsource(runtime.JarvisRuntime._learn_facts_soon)
    assert '_selected_model(None, role="chat")' in source and '_options(0.0, model=model, role="chat")' in source
    assert "rewarm=False" in source
    from alture_jarvis.ollama import OllamaClient

    assert "rewarm: bool = True" in inspect.getsource(OllamaClient.background_chat)
