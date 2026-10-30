"""끝내기 문 「시작점 대비 새로 깨진 시험 0」 (2026-10-28 · `regression_vs_start.py`).

재생 측정 261fbfe2: 세 판 모두 확인 명령만 통과시키고 끝났고, 저장소 전체 시험은 300초 상한에 잘려 끝까지 본 적이 없었으며,
시작점에서 이미 13개가 깨져 있어 「원래 깨진 것」과 「내가 깬 것」을 가르지 못했다. 아래는 그 문의 동작을 가짜 실행기로 하나씩,
그리고 작은 임시 git 저장소에서 진짜 pytest 로 한 번 확인한다.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import agent as agent_module
from alture_jarvis import regression_vs_start as rvs
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult


# ── 가짜 실행기 ────────────────────────────────────────────────────────────────────


class FakeSuite:
    """`PytestSuite` 와 같은 얼굴. 시작점(풀어 놓은 폴더)에서는 `baseline`, 작업 폴더에서는 다음 `finals` 를 낸다."""

    python = "fake-python"

    def __init__(self, root: Path, baseline: rvs.SuiteResult, finals: list[rvs.SuiteResult], rerun: dict[str, str] | None = None) -> None:
        self.root = Path(root)
        self.baseline, self.finals = baseline, list(finals)
        self.rerun_outcomes = rerun or {}
        self.final_runs = 0
        self.reruns: list[str] = []
        self.prepared: tuple[bool, str] = (True, "")
        self.python_now = self.python

    def prepare(self, root):  # noqa: ANN001, ANN201
        return self.prepared

    def python_for(self, root):  # noqa: ANN001, ANN201
        return self.python_now

    def run(self, cwd, *, real_root, timeout=900, should_stop=None):  # noqa: ANN001, ANN201
        if Path(cwd) != self.root:
            return self.baseline
        self.final_runs += 1
        return self.finals[min(self.final_runs - 1, len(self.finals) - 1)]

    def rerun(self, cwd, node_id, *, real_root, should_stop=None):  # noqa: ANN001, ANN201
        self.reruns.append(node_id)
        return self.rerun_outcomes.get(node_id, "failed")


def _ok(failed: dict[str, str] | None = None, *, passed: int = 50, ran: float = 12.0) -> rvs.SuiteResult:
    failed = failed or {}
    return rvs.SuiteResult("ok", ran_sec=ran, failed=failed, passed=passed, total=passed + len(failed))


def _gate(tmp_path: Path, suite: FakeSuite, **kwargs: Any) -> rvs.RegressionGate:
    counter = iter(range(1000))
    gate = rvs.RegressionGate(
        tmp_path, suite=suite, snapshot=lambda root, ref, dest: (True, ""), start_ref=lambda root: "abc123",
        mark=kwargs.pop("mark", lambda root: f"tree-{next(counter)}"), **kwargs,
    )
    assert gate.start() is True
    return gate


# ── 집합 차 · 흔들림 · 상한 ───────────────────────────────────────────────────────


def test_only_what_was_passing_at_the_start_and_fails_now_is_counted(tmp_path: Path) -> None:
    suite = FakeSuite(
        tmp_path,
        baseline=_ok({"tests/test_old.py::test_a": "원래 깨짐", "tests/test_old.py::test_b": "원래 깨짐"}),
        finals=[_ok({"tests/test_old.py::test_a": "원래 깨짐", "tests/test_old.py::test_b": "원래 깨짐",
                     "tests/test_new.py::test_c": "AssertionError: 내가 깸"})],
    )
    gate = _gate(tmp_path, suite)
    verdict = gate.check()

    assert verdict.send_back is True
    assert suite.reruns == ["tests/test_new.py::test_c"], "원래 깨져 있던 둘은 다시 돌릴 까닭도 없다"
    assert "tests/test_new.py::test_c — AssertionError: 내가 깸" in verdict.text
    assert "test_old.py" not in verdict.text, "원래 깨져 있던 시험을 모델에게 들이밀지 않는다"
    assert "시험 1개" in verdict.text and "깨져 있던 2개는 뺐다" in verdict.text
    report = gate.record()
    assert report["baseline"] == {"status": "ok", "reason": "", "ran_sec": 12.0, "failed_ids": 2, "passed": 50}
    assert report["final"]["newly_failing"] == 1 and report["final"]["confirmed"] == 1 and report["final"]["rechecked"] == 1
    assert report["sent_back"] == 1 and report["enabled"] is True


def test_a_test_that_passes_when_run_alone_is_a_wobble_not_a_regression(tmp_path: Path) -> None:
    """병렬 중 브라우저 시험이 멈춘 흔들림(판 5b05df02)은 세지 않는다."""
    suite = FakeSuite(
        tmp_path, baseline=_ok(),
        finals=[_ok({"tests/test_browser.py::test_hang": "timeout", "tests/test_real.py::test_x": "assert 1 == 2"})],
        rerun={"tests/test_browser.py::test_hang": "passed", "tests/test_real.py::test_x": "failed"},
    )
    gate = _gate(tmp_path, suite)
    verdict = gate.check()

    assert verdict.send_back and "test_real.py::test_x" in verdict.text and "test_hang" not in verdict.text
    final = gate.record()["final"]
    assert (final["newly_failing"], final["confirmed"], final["rechecked"]) == (2, 1, 2)


def test_a_wobble_alone_does_not_stop_the_job(tmp_path: Path) -> None:
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok({"tests/t.py::test_w": "x"})], rerun={"tests/t.py::test_w": "passed"})
    gate = _gate(tmp_path, suite)
    verdict = gate.check()
    assert not verdict.send_back and not verdict.leftover
    assert gate.record()["final"]["confirmed"] == 0 and gate.record()["sent_back"] == 0


def test_a_rerun_that_could_not_tell_is_not_counted(tmp_path: Path) -> None:
    """다시 돌리지 못했거나 시험을 못 찾았으면 「모른다」다 — 모르는 것으로 판을 막지 않는다."""
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok({"tests/t.py::test_u": "x"})], rerun={"tests/t.py::test_u": "unclear"})
    gate = _gate(tmp_path, suite)
    assert not gate.check().send_back


def test_at_most_twenty_are_rerun_and_the_rest_count_as_confirmed(tmp_path: Path) -> None:
    broken = {f"tests/test_mass.py::test_{index:03d}": "ImportError" for index in range(25)}
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok(broken)])
    gate = _gate(tmp_path, suite)
    verdict = gate.check()

    assert len(suite.reruns) == rvs.RECHECK_MAX == 20
    final = gate.record()["final"]
    assert (final["newly_failing"], final["confirmed"], final["rechecked"]) == (25, 25, 20)
    assert verdict.send_back and "25개" in verdict.text
    assert verdict.text.count("test_mass.py::test_") == rvs.SHOW_MAX, "모델에게는 열 개까지만 보인다"
    assert "그 밖에 15개 더" in verdict.text


# ── 대조 못 하면 막지 않는다 ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "baseline,why",
    [
        (rvs.SuiteResult("unavailable", "timeout_900s"), "baseline_timeout_900s"),
        (rvs.SuiteResult("unavailable", "nothing_passed_at_start"), "baseline_nothing_passed_at_start"),
        (rvs.SuiteResult("unavailable", "no_result_file:boom"), "baseline_no_result_file:boom"),
    ],
)
def test_when_the_start_could_not_be_measured_nothing_is_blocked(tmp_path: Path, baseline: rvs.SuiteResult, why: str) -> None:
    suite = FakeSuite(tmp_path, baseline=baseline, finals=[_ok({"tests/t.py::test_z": "깨짐"})])
    gate = _gate(tmp_path, suite)
    verdict = gate.check()

    assert not verdict.send_back and not verdict.leftover and not verdict.stopped
    assert suite.final_runs == 0, "견줄 수 없는데 끝에서 시험을 또 돌리지 않는다"
    report = gate.record()
    assert report["baseline"]["status"] == "unavailable" and report["final"]["status"] == "unavailable"
    assert report["final"]["reason"] == why


def test_a_repo_that_cannot_be_compared_says_why_at_the_start(tmp_path: Path) -> None:
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok()])
    suite.prepared = (False, "no_tests_dir")
    gate = rvs.RegressionGate(tmp_path, suite=suite)
    assert gate.start() is False
    verdict = gate.check()
    assert not verdict.send_back
    assert gate.record()["baseline"]["reason"] == "no_tests_dir"


def test_a_final_run_that_could_not_finish_does_not_block(tmp_path: Path) -> None:
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[rvs.SuiteResult("unavailable", "timeout_900s", ran_sec=900.0)])
    gate = _gate(tmp_path, suite)
    assert not gate.check().send_back
    assert gate.record()["final"]["reason"] == "final_timeout_900s"


def test_a_python_that_changed_since_the_start_is_not_compared(tmp_path: Path) -> None:
    """시작점은 한 파이썬으로, 끝은 다른 파이썬으로 재면 환경 차이가 새 실패로 보인다."""
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok({"tests/t.py::test_q": "ModuleNotFoundError"})])
    gate = _gate(tmp_path, suite)
    suite.python_now = "another-python"
    assert not gate.check().send_back
    assert gate.record()["final"]["reason"] == "python_changed"


# ── 되돌림 두 번 상한 · 같은 모양이면 다시 안 잰다 ──────────────────────────────────


def test_it_sends_back_twice_then_ends_as_leftover(tmp_path: Path) -> None:
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok({"tests/t.py::test_k": "still broken"})])
    gate = _gate(tmp_path, suite)
    first, second, third = gate.check(), gate.check(), gate.check()

    assert (first.send_back, second.send_back, third.send_back) == (True, True, False)
    assert third.leftover == ["tests/t.py::test_k — still broken"]
    report = gate.record()
    assert report["sent_back"] == rvs.SEND_BACK_MAX == 2
    assert report["leftover"] == third.leftover and report["leftover_count"] == 1
    note = rvs.leftover_note(report["leftover"], report["leftover_count"])
    assert "깨끗하지 않습니다" in note and "test_k" in note


def test_a_fix_in_between_clears_the_leftover(tmp_path: Path) -> None:
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok({"tests/t.py::test_k": "broken"}), _ok()])
    gate = _gate(tmp_path, suite)
    assert gate.check().send_back
    assert not gate.check().send_back
    report = gate.record()
    assert report["leftover"] == [] and report["final"]["confirmed"] == 0 and report["sent_back"] == 1


def test_an_unchanged_tree_is_not_measured_again(tmp_path: Path) -> None:
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok()])
    gate = _gate(tmp_path, suite, mark=lambda root: "same-tree")
    gate.check()
    gate.check()
    assert suite.final_runs == 1, "마지막으로 잰 뒤 작업 폴더가 그대로면 시험을 또 돌리지 않는다"


def test_no_room_for_another_step_means_leftover_not_send_back(tmp_path: Path) -> None:
    suite = FakeSuite(tmp_path, baseline=_ok(), finals=[_ok({"tests/t.py::test_k": "broken"})])
    gate = _gate(tmp_path, suite)
    verdict = gate.check(can_send_back=False)
    assert not verdict.send_back and verdict.leftover and gate.record()["sent_back"] == 0


def test_a_person_waiting_cuts_the_run_and_the_job_steps_aside(tmp_path: Path) -> None:
    class Cut(FakeSuite):
        def run(self, cwd, *, real_root, timeout=900, should_stop=None):  # noqa: ANN001, ANN201
            if Path(cwd) != self.root:
                return self.baseline
            return rvs.SuiteResult("unavailable", "stopped", stopped=True)

    gate = _gate(tmp_path, Cut(tmp_path, baseline=_ok(), finals=[_ok()]))
    assert gate.check(should_stop=lambda: True).stopped is True


# ── 진짜 실행: 작은 임시 git 저장소 + 진짜 pytest ───────────────────────────────────


def _git(folder: Path, *args: str) -> None:
    done = subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t", *args], capture_output=True)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pkgz1028").mkdir()
    (repo / "pkgz1028" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_good.py").write_text("def test_good():\n    assert True\n", encoding="utf-8")
    (repo / "tests" / "test_old_failure.py").write_text("def test_old():\n    assert False, '시작점부터 깨져 있다'\n", encoding="utf-8")
    (repo / "tests" / "test_guards_value.py").write_text(
        "import pkgz1028\n\n\ndef test_value_is_one():\n    assert pkgz1028.VALUE == 1\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    return repo


def test_real_pytest_in_a_small_git_repo_separates_old_failures_from_new_ones(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    gate = rvs.RegressionGate(repo, suite=rvs.PytestSuite(workers=1))
    assert gate.start() is True
    # 모델이 고치는 동안 — 작업 폴더의 코드를 바꿔 시작점에서 통과하던 시험 하나를 깬다(커밋하지 않는다).
    (repo / "pkgz1028" / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
    before = (repo / "pkgz1028" / "__init__.py").read_bytes()

    verdict = gate.check()

    assert verdict.send_back, gate.record()
    assert "tests/test_guards_value.py::test_value_is_one" in verdict.text
    assert "test_old_failure" not in verdict.text, "시작점부터 깨져 있던 시험은 뺀다"
    report = gate.record()
    assert report["baseline"]["status"] == "ok" and report["baseline"]["failed_ids"] == 1 and report["baseline"]["passed"] == 2
    assert report["final"]["status"] == "ok" and report["final"]["newly_failing"] == 1 and report["final"]["confirmed"] == 1
    assert report["final"]["rechecked"] == 1
    assert (repo / "pkgz1028" / "__init__.py").read_bytes() == before, "작업 폴더를 건드리지 않는다"
    assert not list(repo.glob("**/junit*.xml")) and not (repo / ".pytest_cache").exists()

    # 고치고 다시 끝내려 하면 통과한다.
    (repo / "pkgz1028" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert not gate.check().send_back
    assert gate.record()["final"]["confirmed"] == 0


def test_real_start_snapshot_comes_from_the_commit_not_from_the_working_tree(tmp_path: Path) -> None:
    """작업 폴더를 먼저 바꿔 놓고 시작해도(커밋 안 한 변경) 시작점은 커밋의 모습이다 — 그래서 `base` 가 커밋으로 박힌 판에서만 뜻이 있다."""
    repo = _repo(tmp_path)
    dest = tmp_path / "snap"
    (repo / "pkgz1028" / "__init__.py").write_text("VALUE = 99\n", encoding="utf-8")
    ok, why = rvs.archive_snapshot(repo, rvs.head_commit(repo), dest)
    assert ok, why
    assert (dest / "pkgz1028" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (dest / ".git").exists()


def test_a_repo_without_a_tests_folder_is_not_compared(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    ok, why = rvs.PytestSuite().prepare(repo)
    assert (ok, why) == (False, "no_tests_dir")


def test_junit_ids_come_back_as_pytest_node_ids(tmp_path: Path) -> None:
    folder = tmp_path / "j"
    (folder / "tests").mkdir(parents=True)
    (folder / "tests" / "test_n.py").write_text(
        textwrap.dedent(
            """
            import pytest

            class TestBox:
                def test_inside(self):
                    assert 0

            @pytest.mark.parametrize("x", [1, "a b"])
            def test_param(x):
                assert x != "a b"
            """
        ),
        encoding="utf-8",
    )
    (folder / "tests" / "test_broken_import.py").write_text("import module_that_is_not_there_1028\n", encoding="utf-8")
    suite = rvs.PytestSuite(workers=1)
    suite.python = sys.executable
    result = suite.run(folder, real_root=folder)
    assert result.status == "ok"
    assert set(result.failed) == {
        "tests/test_n.py::TestBox::test_inside", "tests/test_n.py::test_param[a b]", "tests/test_broken_import.py",
    }, result.failed
    # 그 이름 그대로 혼자 다시 돌릴 수 있다.
    assert suite.rerun(folder, "tests/test_n.py::TestBox::test_inside", real_root=folder) == "failed"
    assert suite.rerun(folder, "tests/test_n.py::test_param[1]", real_root=folder) == "passed"
    assert suite.rerun(folder, "tests/test_n.py::test_not_there", real_root=folder) == "unclear"


# ── 한 판 안에서: 문의 자리 ─────────────────────────────────────────────────────────

_CHECK = "python -m pytest -q tests/test_value.py"
_TOOL_NAMES = {"local_read_text_file", "local_grep", "local_write_file", "local_apply_edit", "local_delete_file", "local_run_project_command"}


class _Tools:
    names = set(_TOOL_NAMES)
    ollama_tools = [
        {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}
        for name in sorted(_TOOL_NAMES)
    ]

    def authorize_code_workspace(self, job_id, root):  # noqa: ANN001, ANN201
        assert job_id and root


class _Gateway:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.checks: list[dict] = []

    def execute(self, name, arguments, *, job_id=""):  # noqa: ANN001, ANN201
        target = self.root / "value.py"
        if name == "local_write_file":
            target.write_text(str(arguments.get("content") or ""), encoding="utf-8")
            return ToolResult(True, name, result={"action": name, "path": str(target), "verified": True, "created": True})
        if name == "local_run_project_command":
            self.checks.append(dict(arguments))
            passed = target.is_file() and "fixed" in target.read_text(encoding="utf-8")
            return ToolResult(True, name, result={
                "action": name, "command": arguments.get("command"), "exit_code": 0 if passed else 1,
                "stdout": "1 passed" if passed else "1 failed", "verified": passed,
            })
        return ToolResult(True, name, result={"action": name, "text": "x"})


def _agent(tmp_path: Path, model: Any, **config: Any) -> tuple[BrowserAgent, JobStore, _Gateway]:
    cfg = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False, **config,
    )
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _Gateway(tmp_path)
    browser = SimpleNamespace(status=lambda: {"started": True})
    return BrowserAgent(cfg, model, gateway, browser, _Tools(), store, EventBus()), store, gateway


def _call(name: str, **arguments: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def _say(text: str) -> dict:
    return {"role": "assistant", "content": text}


def _run(agent: BrowserAgent, store: JobStore, tmp_path: Path, prompt: str, **extra: Any):  # noqa: ANN201
    job = store.create_job("chat", "맡긴 일", {"prompt": prompt})
    store.claim_next()
    return agent.run(
        prompt, job_id=job["id"], origin="mcp", model_role="code", code_mode=True,
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True, **extra,
    )


class FakeGate:
    """문의 얼굴만 흉내 — 판이 이 문을 어디서 어떻게 부르는지만 본다. 판정은 위의 시험이 이미 봤다."""

    made: list["FakeGate"] = []
    script: list[rvs.Verdict] = []

    def __init__(self, root, **kwargs):  # noqa: ANN001, ANN003
        self.root = root
        self.sent_back = 0
        self.leftover: list[str] = []
        self.leftover_total = 0
        self.closed = False
        self.calls: list[dict] = []
        FakeGate.made.append(self)

    def start(self) -> bool:
        return True

    def check(self, *, should_stop=None, english=False, can_send_back=True):  # noqa: ANN001, ANN201
        self.calls.append({"listening": should_stop is not None, "can_send_back": can_send_back})
        verdict = FakeGate.script.pop(0) if FakeGate.script else rvs.Verdict()
        if verdict.send_back:
            self.sent_back += 1
        if verdict.leftover:
            self.leftover, self.leftover_total = list(verdict.leftover), len(verdict.leftover)
        return verdict

    def close(self) -> None:
        self.closed = True

    def record(self) -> dict:
        return {"enabled": True, "baseline": {"status": "ok"}, "final": {"status": "ok"}, "sent_back": self.sent_back,
                "leftover": list(self.leftover), "leftover_count": self.leftover_total}


@pytest.fixture()
def fake_gate(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    FakeGate.made, FakeGate.script = [], []
    monkeypatch.setattr(agent_module._regression, "RegressionGate", FakeGate)
    return FakeGate


_BACK = "[시스템] 이 일을 시작할 때 통과하던 시험 1개가 지금 깨져 있다.\n  - tests/test_other.py::test_x — assert 1 == 2"


class _HarnessRunsTheCheck:
    """고쳤다고 보고 → (하네스가 확인 명령을 돌림) → 되돌림을 받으면 한 번 더 고치고 보고."""

    def __init__(self) -> None:
        self.calls = 0
        self.saw_back = False

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        self.saw_back = self.saw_back or any("test_other.py::test_x" in str(m.get("content") or "") for m in messages)
        if self.calls == 1:
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
        if self.calls == 2:
            return _say("첫 보고")
        if self.calls == 3:
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed again'\n")
        return _say("둘째 보고")


def test_a_confirmed_new_failure_after_the_check_passes_sends_the_job_back(tmp_path: Path, fake_gate) -> None:  # noqa: ANN001
    fake_gate.script = [rvs.Verdict(send_back=True, text=_BACK), rvs.Verdict()]
    model = _HarnessRunsTheCheck()
    agent, store, gateway = _agent(tmp_path, model)

    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)

    assert model.saw_back, "모델이 새로 깨진 시험을 받았다"
    assert len(gateway.checks) == 2 and all(c.get("__declared_check") for c in gateway.checks), "되돌아온 뒤 고치면 확인 명령도 다시 돈다"
    assert "둘째 보고" in result.answer and "첫 보고" not in result.answer
    assert result.verification["completion_state"] == "complete"
    record = result.verification["regression_vs_start"]
    assert record["sent_back"] == 1 and record["leftover"] == []
    assert len(fake_gate.made[0].calls) == 2 and fake_gate.made[0].calls[0]["listening"] is True
    assert fake_gate.made[0].closed is True


def test_leftover_after_the_last_send_back_makes_the_job_partial_and_says_so(tmp_path: Path, fake_gate) -> None:  # noqa: ANN001
    fake_gate.script = [rvs.Verdict(send_back=True, text=_BACK), rvs.Verdict(leftover=["tests/test_other.py::test_x — assert 1 == 2"])]
    agent, store, _ = _agent(tmp_path, _HarnessRunsTheCheck())

    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)

    assert result.verification["declared_check"]["passed"] is True, "확인 명령은 통과했다"
    assert result.verification["completion_state"] == "partial", "그래도 시작점에서 통과하던 시험을 깬 채라 완료가 아니다"
    assert "깨끗하지 않습니다" in result.answer and "tests/test_other.py::test_x" in result.answer
    assert result.verification["regression_vs_start"]["leftover_count"] == 1


class _RunsTheCheckItself:
    """확인 명령을 스스로 돌려 통과시키고 답한다 — 하네스가 대신 돌릴 일이 없는 판."""

    def __init__(self) -> None:
        self.calls = 0
        self.saw_back = False

    def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        self.saw_back = self.saw_back or any("test_other.py::test_x" in str(m.get("content") or "") for m in messages)
        if self.calls == 1:
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
        if self.calls in (2, 5):
            return _call("local_run_project_command", path=".", command=_CHECK)
        if self.calls == 3:
            return _say("첫 보고")
        if self.calls == 4:
            return _call("local_write_file", path="value.py", content="VALUE = 'fixed again'\n")
        return _say("둘째 보고")


def test_a_job_that_passed_the_check_by_itself_goes_through_the_same_door(tmp_path: Path, fake_gate) -> None:  # noqa: ANN001
    fake_gate.script = [rvs.Verdict(send_back=True, text=_BACK), rvs.Verdict()]
    model = _RunsTheCheckItself()
    agent, store, gateway = _agent(tmp_path, model)

    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)

    assert model.saw_back
    assert all(not c.get("__declared_check") for c in gateway.checks), "하네스는 확인 명령을 대신 돌리지 않았다"
    assert "둘째 보고" in result.answer
    assert result.verification["regression_vs_start"]["sent_back"] == 1
    assert result.verification["completion_state"] == "complete"


def test_a_job_without_a_declared_check_never_builds_the_door(tmp_path: Path, fake_gate) -> None:  # noqa: ANN001
    class Never(_HarnessRunsTheCheck):
        pass

    agent, store, gateway = _agent(tmp_path, Never())
    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘")
    assert fake_gate.made == [], "위임(확인 명령이 있는 판)이 아니면 문을 만들지도 않는다"
    assert result.verification["regression_vs_start"] is None
    assert result.verification["declared_check"] is None and gateway.checks == []


def test_the_door_can_be_switched_off_by_a_setting(tmp_path: Path, fake_gate) -> None:  # noqa: ANN001
    agent, store, _ = _agent(tmp_path, _HarnessRunsTheCheck(), agent_regression_vs_start=False)
    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)
    assert fake_gate.made == []
    assert result.verification["regression_vs_start"] == {"enabled": False, "reason": "config_off"}
    assert result.verification["completion_state"] == "complete"


def test_the_setting_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_AGENT_REGRESSION_VS_START", raising=False)
    assert JarvisConfig.from_env().agent_regression_vs_start is True
    monkeypatch.setenv("JARVIS_AGENT_REGRESSION_VS_START", "0")
    assert JarvisConfig.from_env().agent_regression_vs_start is False


def test_a_door_that_fails_to_start_does_not_stop_the_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def __init__(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("boom")

    monkeypatch.setattr(agent_module._regression, "RegressionGate", Broken)
    agent, store, _ = _agent(tmp_path, _HarnessRunsTheCheck())
    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)
    assert result.verification["regression_vs_start"] == {"enabled": False, "reason": "start_failed:RuntimeError"}
    assert result.verification["declared_check"]["passed"] is True


def test_the_job_without_any_tests_folder_ends_exactly_as_before(tmp_path: Path) -> None:
    """진짜 문(가짜 아님) — 시험 폴더가 없는 작업 폴더는 대조 못 함으로 적고 아무것도 막지 않는다."""

    class Once:
        def __init__(self) -> None:
            self.calls = 0

        def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
            self.calls += 1
            if self.calls == 1:
                return _call("local_write_file", path="value.py", content="VALUE = 'fixed'\n")
            return _say("고쳤습니다.")

    agent, store, _ = _agent(tmp_path, Once())
    result = _run(agent, store, tmp_path, "value.py 의 값을 고쳐줘", declared_check=_CHECK)
    record = result.verification["regression_vs_start"]
    assert record["enabled"] is True and record["baseline"] == {
        "status": "unavailable", "reason": "no_tests_dir", "ran_sec": 0.0, "failed_ids": 0, "passed": 0}
    assert record["sent_back"] == 0 and result.verification["completion_state"] == "complete"
