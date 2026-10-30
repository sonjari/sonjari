"""끝내기 문 — 「시작점에서 통과하던 시험이 지금 깨진 게 하나도 없다」 (2026-10-28).

## 왜

바깥 AI 가 코드 일을 맡기며 확인 명령을 주면(`declared_check`) 하네스는 그 명령이 통과한 순간 끝을 받는다. 재생 측정(판 261fbfe2 를
같은 시작점 · 같은 문장으로 Swift 27B 가 세 번)에서 세 판 모두 확인 명령(시험 파일 8개)은 통과했는데 **다른 시험을 깬 채** 끝났다.
모델이 저장소 전체 시험을 돌리려 했지만 세 판 모두 일반 명령 상한 300초에 잘려 끝까지 본 적이 없고, `-x` 로 돌리면 첫 실패에서 멈췄다.
게다가 시작점에서 이미 13개가 깨져 있어서(원래 깨진 것) 모델은 「원래 깨진 것」과 「내가 깬 것」을 가르지 못했다.

## 무엇을 하나 (모델에게 「전체 시험을 돌려라」고 말하지 않는다 — 하네스가 직접 돌린다. 사고 R)

1. 판이 시작될 때 시작점(HEAD 커밋)을 **작업 폴더를 건드리지 않고** `git archive` 로 임시 폴더에 풀어, 거기서 전체 시험을
   백그라운드 스레드로 돌려 **실패한 시험 이름의 집합**을 적어 둔다. 모델이 읽고 고치는 동안 돈다.
2. 하네스가 끝을 받아들이려는 자리에서 지금 작업 폴더로 같은 시험을 돌린다. (지금 실패) − (시작점 실패) = 새로 깨진 것.
3. 새로 깨진 것은 **하나씩 혼자 다시 돌려 또 실패한 것만** 센다 — 병렬 중에 브라우저 시험이 멈춘 흔들림이 실측됐다(판 5b05df02).
4. 확정된 새 실패가 있으면 끝을 받지 않고 모델에게 돌려준다(판당 두 번). 두 번 뒤에도 남으면 「일부」로 끝내고 답 끝에 적는다.

## 대조 못 하면 막지 않는다

파이썬 · pytest 가 아닌 저장소 · `tests/` 없음 · pytest 없음 · 시작점 시험이 시간 안에 안 끝남 · 시작점에서 통과한 시험이 하나도 없음 ·
결과 파일이 안 생김 — 전부 「대조 못 함(까닭)」으로 기록하고 판은 평소대로 끝난다. 모르는 것을 근거로 판을 막지 않는다.
수집 오류(`import` 가 깨진 시험 파일)는 `--continue-on-collection-errors` 로 **실패한 시험 하나**로 센다 — 시작점에도 있던 것은 빠지고
모델이 새로 깨뜨린 import 는 새 실패로 잡힌다.

## 한계 (정직하게)

저장소의 시험이 지키는 것만 잡는다. 재생 측정에서 이 장치가 있었어도 세 판 중 잡힌 것은 판3 의 숨은 지킴 19개 가운데 2개였다.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import project_env

#: 전체 시험 한 번(시작점 · 끝)의 시간 상한. 일반 명령의 300초를 넘는다 — 확인 명령과 같다.
SUITE_TIMEOUT_SEC = 900
#: 새로 깬 시험을 혼자 다시 돌려 보는 개수 상한. 그 너머는 다시 돌리지 않고 확정으로 센다(수십 개가 한꺼번에 깨졌으면 흔들림이 아니다).
RECHECK_MAX = 20
#: 다시 돌리기 한 번 · 전체의 시간 상한(초).
RECHECK_EACH_SEC = 120
RECHECK_TOTAL_SEC = 400
#: 모델에게 돌려보내는 횟수 상한 (`_DECLARED_CHECK_RUNS` 와 같은 식).
SEND_BACK_MAX = 2
#: 모델에게 보이는 새 실패 개수 상한.
SHOW_MAX = 10
#: 병렬 일꾼 수 상한 — 이 PC 의 CPU 가 많아도 이 이상은 브라우저 시험이 멈출 위험만 키웠다(재생 측정 12갈래).
WORKERS_MAX = 12
#: 시작점 시험이 끝나기를 기다리는 최대(판 시작부터 잰 초). 시험 상한 + 풀기 · 정리 여유.
BASELINE_DEADLINE_SEC = SUITE_TIMEOUT_SEC + 90


@dataclass
class SuiteResult:
    """전체 시험을 한 번 돈 결과. `status` 가 ok 가 아니면 이 결과로는 견줄 수 없다 — `reason` 이 까닭이다."""

    status: str                     # "ok" | "unavailable"
    reason: str = ""
    ran_sec: float = 0.0
    failed: dict[str, str] = field(default_factory=dict)   # 시험 이름(node id) -> 실패 메시지 첫 줄
    passed: int = 0
    total: int = 0
    stopped: bool = False           # 사람의 요청 · 취소로 끊겼다 (실패도 성공도 아니다)


@dataclass
class Verdict:
    """끝내기 문의 판정 한 번."""

    send_back: bool = False         # 끝을 받지 않고 모델에게 돌려준다
    stopped: bool = False           # 사람의 요청으로 시험이 끊겼다 — 호출한 쪽이 자리를 비켜 준다
    text: str = ""                  # 모델에게 보낼 글 (send_back 일 때)
    leftover: list[str] = field(default_factory=list)   # 돌려보내기를 다 쓰고도 남은 새 실패 (보이는 줄)


# ── 시험 실행기 (진짜) ───────────────────────────────────────────────────────────────

def _first_line(text: str, limit: int = 200) -> str:
    for line in str(text or "").splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ""


def _node_id(case: ET.Element) -> str:
    """junit 의 시험 하나를 pytest 의 node id(`파일::클래스::이름`)로 되돌린다 — 혼자 다시 돌릴 때 그대로 쓴다.

    `junit_family=xunit1` 이어야 `file` 칸이 있다. 수집 오류는 `classname` 이 비고 `file` 이 곧 이름이다.
    """
    file = str(case.get("file") or "").replace("\\", "/")
    name = str(case.get("name") or "")
    classname = str(case.get("classname") or "")
    if not file:
        return f"{classname}::{name}" if classname else name
    if not classname:
        return file
    module = file[:-3].replace("/", ".") if file.endswith(".py") else file.replace("/", ".")
    rest = classname[len(module) + 1:] if classname.startswith(module + ".") else ""
    classes = [part for part in rest.split(".") if part]
    return "::".join([file, *classes, name])


def parse_junit(path: Path) -> tuple[dict[str, str], int, int]:
    """(실패한 시험 {이름: 메시지 첫 줄}, 통과한 시험 수, 건너뛰지 않은 전체). 읽을 수 없으면 예외."""
    root = ET.parse(str(path)).getroot()
    failed: dict[str, str] = {}
    passed = total = 0
    for case in root.iter("testcase"):
        skipped = any(child.tag == "skipped" for child in case)
        if skipped:
            continue
        total += 1
        bad = next((child for child in case if child.tag in ("failure", "error")), None)
        if bad is None:
            passed += 1
            continue
        failed[_node_id(case)] = _first_line(bad.get("message") or bad.text or "") or bad.tag
    return failed, passed, total


class PytestSuite:
    """파이썬 · pytest 저장소의 전체 시험. 다른 언어는 처음 판에서 다루지 않는다 — `prepare` 가 「대조 못 함」을 돌려준다."""

    def __init__(self, *, workers: int | None = None) -> None:
        self.workers = workers if workers is not None else max(1, min(WORKERS_MAX, (os.cpu_count() or 4) - 2))
        self.python = ""
        self.has_xdist = False

    # 어느 파이썬으로 돌리나 — `local_run_project_command` 와 같은 규칙(프로젝트 가상환경이 있으면 그것).
    def python_for(self, root: Path) -> str:
        from .local_computer import LocalComputerTools

        return LocalComputerTools._project_python(Path(root), "pytest")

    def _env(self, root: Path, sources_in: Path) -> dict[str, str]:
        """시험이 도는 환경. `root` 의 가상환경을 쓰고, `sources_in` 의 `src` 를 맨 앞에(풀어 놓은 시작점은 거기 코드를 재야 한다)."""
        from .local_computer import _with_our_python_first

        environment = project_env.with_project_sources_first(
            project_env.with_project_venv_first(_with_our_python_first(project_env.without_our_settings(dict(os.environ))), Path(root)),
            Path(sources_in),
        )
        environment.update({"CI": "1", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                            "GIT_TERMINAL_PROMPT": "0"})
        return environment

    def _run(self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float, should_stop: Callable[[], bool] | None):
        from .local_computer import run_captured, stop_commands_when

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # 사용자의 시험이 만지는 손자리 자리는 이 한 번만 있는 빈 폴더로 — `_run_for_model` 과 같다.
        with project_env.scratch_home(env) as child:
            if should_stop is None:
                return run_captured(argv, cwd=cwd, env=child, timeout_sec=timeout, creationflags=flags), False
            with stop_commands_when(should_stop) as was_stopped:
                done = run_captured(argv, cwd=cwd, env=child, timeout_sec=timeout, creationflags=flags)
            return done, was_stopped()

    def prepare(self, root: Path) -> tuple[bool, str]:
        """이 저장소를 견줄 수 있나 → (예, "") 또는 (아니오, 까닭). 시작 때 한 번 부른다."""
        root = Path(root)
        if not (root / "tests").is_dir():
            return False, "no_tests_dir"
        self.python = self.python_for(root)
        probe = ("import importlib.util as u;"
                 "print(int(bool(u.find_spec('pytest'))), int(bool(u.find_spec('xdist'))))")
        try:
            (code, out, _err, timed_out), _stopped = self._run(
                [self.python, "-c", probe], cwd=root, env=self._env(root, root), timeout=60, should_stop=None
            )
        except OSError as exc:
            return False, f"python_unavailable:{type(exc).__name__}"
        if timed_out or code != 0:
            return False, "python_probe_failed"
        parts = out.decode("utf-8", "replace").split()
        if len(parts) < 2 or parts[0] != "1":
            return False, "no_pytest"
        self.has_xdist = parts[1] == "1"
        return True, ""

    def run(self, cwd: Path, *, real_root: Path, timeout: float = SUITE_TIMEOUT_SEC,
            should_stop: Callable[[], bool] | None = None) -> SuiteResult:
        cwd = Path(cwd)
        folder = Path(tempfile.mkdtemp(prefix="sonjari-junit-"))
        xml_path = folder / "junit.xml"
        argv = [self.python, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors",
                "--tb=line", "-o", "junit_family=xunit1", f"--junitxml={xml_path}"]
        if self.has_xdist and self.workers > 1:
            argv += ["-n", str(self.workers)]
        began = time.monotonic()
        try:
            try:
                (_code, _out, err, timed_out), stopped = self._run(
                    argv, cwd=cwd, env=self._env(real_root, cwd), timeout=timeout, should_stop=should_stop
                )
            except OSError as exc:
                return SuiteResult("unavailable", f"run_failed:{type(exc).__name__}")
            ran = round(time.monotonic() - began, 1)
            if stopped:
                return SuiteResult("unavailable", "stopped", ran_sec=ran, stopped=True)
            if timed_out:
                return SuiteResult("unavailable", f"timeout_{int(timeout)}s", ran_sec=ran)
            if not xml_path.exists():
                return SuiteResult("unavailable", "no_result_file:" + _first_line(err.decode("utf-8", "replace"), 80), ran_sec=ran)
            try:
                failed, passed, total = parse_junit(xml_path)
            except (ET.ParseError, OSError):
                return SuiteResult("unavailable", "result_file_unreadable", ran_sec=ran)
            if total == 0:
                return SuiteResult("unavailable", "no_tests_ran", ran_sec=ran)
            return SuiteResult("ok", "", ran_sec=ran, failed=failed, passed=passed, total=total)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def rerun(self, cwd: Path, node_id: str, *, real_root: Path, should_stop: Callable[[], bool] | None = None) -> str:
        """시험 하나를 혼자 다시 돌린다 → "passed" · "failed" · "unclear"(돌지 못했거나 찾지 못함)."""
        argv = [self.python, "-m", "pytest", node_id, "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors", "--tb=line"]
        try:
            (code, _out, _err, timed_out), stopped = self._run(
                argv, cwd=Path(cwd), env=self._env(real_root, Path(cwd)), timeout=RECHECK_EACH_SEC, should_stop=should_stop
            )
        except OSError:
            return "unclear"
        if stopped or timed_out:
            return "unclear"
        return "passed" if code == 0 else "failed" if code in (1, 2) else "unclear"


# ── 시작점 스냅숏 ────────────────────────────────────────────────────────────────────

def _git(root: Path, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, timeout=timeout, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def head_commit(root: Path) -> str:
    try:
        done = _git(Path(root), "rev-parse", "HEAD", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.decode("utf-8", "replace").strip() if done.returncode == 0 else ""


def archive_snapshot(root: Path, ref: str, dest: Path) -> tuple[bool, str]:
    """`ref` 커밋의 파일을 `dest` 에 푼다 — **작업 폴더는 읽기만** 한다(`git archive`: worktree · stash · checkout 을 쓰지 않는다).

    `root` 가 저장소의 하위 폴더면 그 폴더 안만 풀린다(`git archive` 는 서 있는 자리의 하위 트리를 낸다).
    """
    dest = Path(dest)
    archive = dest.parent / (dest.name + ".zip")
    try:
        done = _git(Path(root), "archive", "--format=zip", "-o", str(archive), ref, timeout=300)
        if done.returncode != 0:
            return False, "git_archive_failed:" + _first_line(done.stderr.decode("utf-8", "replace"), 80)
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(dest)          # zipfile 은 경로를 벗어나는 이름을 스스로 거른다
        return True, ""
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        return False, f"snapshot_failed:{type(exc).__name__}"
    finally:
        try:
            archive.unlink()
        except OSError:
            pass


def tree_mark(root: Path) -> str:
    """작업 폴더의 지금 모양을 한 줄로 — 같으면 마지막으로 잰 뒤 바뀐 것이 없다(시험을 또 돌리지 않는다)."""
    try:
        diff = _git(Path(root), "diff", "HEAD", "--binary", timeout=120).stdout or b""
        others = _git(Path(root), "ls-files", "--others", "--exclude-standard", "-z", timeout=120).stdout or b""
    except (OSError, subprocess.SubprocessError):
        return ""
    digest = hashlib.sha1(diff)
    digest.update(b"\0")
    digest.update(others)
    return digest.hexdigest()


# ── 문 ──────────────────────────────────────────────────────────────────────────────

class RegressionGate:
    """한 판의 「시작점 대비 새로 깬 시험 0」. 판이 시작될 때 `start()`, 끝을 받으려 할 때 `check()`, 판 기록에 `record()`."""

    def __init__(
        self,
        root: Path,
        *,
        suite: Any = None,
        snapshot: Callable[[Path, str, Path], tuple[bool, str]] = archive_snapshot,
        start_ref: Callable[[Path], str] = head_commit,
        mark: Callable[[Path], str] = tree_mark,
        should_cancel: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
        send_back_max: int = SEND_BACK_MAX,
    ) -> None:
        self.root = Path(root)
        self.suite = suite if suite is not None else PytestSuite()
        self._snapshot, self._start_ref, self._mark = snapshot, start_ref, mark
        self._should_cancel, self._clock = should_cancel, clock
        self.send_back_max = send_back_max
        self.sent_back = 0
        self.baseline = SuiteResult("unavailable", "not_started")
        self.final: dict[str, Any] = {"status": "not_run", "reason": "", "ran_sec": 0.0, "newly_failing": 0, "confirmed": 0,
                                      "rechecked": 0, "evaluations": 0}
        self.leftover: list[str] = []
        self.leftover_total = 0
        self._ref = ""
        self._python_at_start = ""
        self._began = 0.0
        self._closed = threading.Event()
        self._baseline_done = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_mark: str | None = None
        self._last_verdict: Verdict | None = None
        self._last_confirmed: dict[str, str] = {}

    # ── 시작 ──
    def start(self) -> bool:
        """시작점 시험을 백그라운드에서 돌리기 시작한다. 견줄 수 없는 저장소면 거기서 끝(까닭을 `baseline` 에 적는다) → False."""
        self._began = self._clock()
        ok, why = self.suite.prepare(self.root)
        if not ok:
            self.baseline = SuiteResult("unavailable", why)
            self._baseline_done.set()
            return False
        self._python_at_start = self.suite.python
        self._ref = self._start_ref(self.root)
        if not self._ref:
            self.baseline = SuiteResult("unavailable", "no_start_commit")
            self._baseline_done.set()
            return False
        self._thread = threading.Thread(target=self._baseline_worker, name="regression-baseline", daemon=True)
        self._thread.start()
        return True

    def _stopped(self) -> bool:
        return self._closed.is_set() or bool(self._should_cancel())

    def _baseline_worker(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="sonjari-base-"))
        try:
            ok, why = self._snapshot(self.root, self._ref, folder / "start")
            if not ok:
                self.baseline = SuiteResult("unavailable", why)
                return
            result = self.suite.run(folder / "start", real_root=self.root, timeout=SUITE_TIMEOUT_SEC, should_stop=self._stopped)
            if result.status == "ok" and result.passed == 0:
                result = SuiteResult("unavailable", "nothing_passed_at_start", ran_sec=result.ran_sec)
            self.baseline = result
        except Exception as exc:  # noqa: BLE001 — 시작점을 못 재도 판은 평소대로 간다
            self.baseline = SuiteResult("unavailable", f"baseline_error:{type(exc).__name__}")
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            self._baseline_done.set()

    def close(self) -> None:
        """판이 끝났다 — 돌고 있는 시작점 시험이 있으면 끊고 임시 폴더는 스스로 치워진다."""
        self._closed.set()

    # ── 끝내기 문 ──
    def _wait_for_baseline(self, should_stop: Callable[[], bool] | None) -> bool:
        """시작점 시험이 끝나기를 기다린다 → 사람이 끊었으면 False."""
        while not self._baseline_done.is_set():
            if should_stop is not None and should_stop():
                return False
            if self._clock() - self._began > BASELINE_DEADLINE_SEC or self._should_cancel():
                self.baseline = SuiteResult("unavailable", "baseline_unfinished")
                return True
            self._baseline_done.wait(timeout=1.0)
        return True

    def check(self, *, should_stop: Callable[[], bool] | None = None, english: bool = False, can_send_back: bool = True) -> Verdict:
        """확인 명령이 통과해 끝을 받으려는 자리에서 부른다. `should_stop` 이 참이 되면 시험을 끊고 `stopped` 를 돌려준다.

        `can_send_back` 이 거짓이면(모델이 더 걸을 자리가 없다) 돌려보내지 않고 남은 새 실패로 적는다.
        """
        mark = self._mark(self.root)
        if self._last_verdict is not None and mark and mark == self._last_mark:
            return self._decide(self._last_confirmed, english, can_send_back)
        if not self._wait_for_baseline(should_stop):
            return Verdict(stopped=True)
        if self.baseline.status != "ok":
            return self._skip("baseline_" + (self.baseline.reason or "unavailable"), mark)
        if self.suite.python_for(self.root) != self._python_at_start:
            return self._skip("python_changed", mark)
        now = self.suite.run(self.root, real_root=self.root, timeout=SUITE_TIMEOUT_SEC, should_stop=should_stop)
        if now.stopped:
            return Verdict(stopped=True)
        self.final["evaluations"] += 1
        self.final["ran_sec"] = now.ran_sec
        if now.status != "ok":
            return self._skip("final_" + (now.reason or "unavailable"), mark)
        newly = sorted(set(now.failed) - set(self.baseline.failed))
        confirmed, rechecked = self._recheck(newly, now.failed, should_stop)
        if confirmed is None:
            return Verdict(stopped=True)
        self.final.update(status="ok", reason="", newly_failing=len(newly), confirmed=len(confirmed), rechecked=rechecked)
        self._last_mark, self._last_confirmed = mark, confirmed
        self._last_verdict = Verdict()
        return self._decide(confirmed, english, can_send_back)

    def _skip(self, reason: str, mark: str) -> Verdict:
        self.final.update(status="unavailable", reason=reason, newly_failing=0, confirmed=0, rechecked=0)
        self._last_mark, self._last_confirmed, self._last_verdict = mark, {}, Verdict()
        self.leftover, self.leftover_total = [], 0
        return Verdict()

    def _recheck(self, newly: list[str], messages: dict[str, str], should_stop: Callable[[], bool] | None):
        """새로 깬 것을 하나씩 혼자 다시 돌려 또 실패한 것만 남긴다 → ({이름: 메시지}, 다시 돌린 수). 사람이 끊으면 (None, n)."""
        confirmed: dict[str, str] = {}
        began = self._clock()
        rechecked = 0
        for node in newly:
            if rechecked >= RECHECK_MAX or self._clock() - began > RECHECK_TOTAL_SEC:
                confirmed[node] = messages.get(node, "")          # 너머는 다시 돌리지 않고 확정으로 센다
                continue
            outcome = self.suite.rerun(self.root, node, real_root=self.root, should_stop=should_stop)
            rechecked += 1
            if should_stop is not None and should_stop():
                return None, rechecked
            if outcome == "failed":
                confirmed[node] = messages.get(node, "")
            # "passed" = 흔들림 · "unclear" = 돌지 못해 확인 못 함 → 센 것으로 치지 않는다(모르는 것으로 막지 않는다)
        return confirmed, rechecked

    def _decide(self, confirmed: dict[str, str], english: bool, can_send_back: bool = True) -> Verdict:
        if not confirmed:
            self.leftover, self.leftover_total = [], 0
            return Verdict()
        lines = [f"{node} — {message}" if message else node for node, message in list(confirmed.items())[:SHOW_MAX]]
        if can_send_back and self.sent_back < self.send_back_max:
            self.sent_back += 1
            self.leftover, self.leftover_total = [], 0
            return Verdict(send_back=True, text=describe(len(confirmed), len(self.baseline.failed), lines, english=english))
        self.leftover, self.leftover_total = lines, len(confirmed)
        return Verdict(leftover=lines)

    # ── 기록 ──
    def record(self) -> dict[str, Any]:
        """판 결과 `verification.regression_vs_start`."""
        baseline = self.baseline
        return {
            "enabled": True,
            "baseline": {"status": baseline.status, "reason": baseline.reason, "ran_sec": baseline.ran_sec,
                         "failed_ids": len(baseline.failed), "passed": baseline.passed},
            "final": dict(self.final),
            "sent_back": self.sent_back,
            "leftover": list(self.leftover),
            "leftover_count": self.leftover_total,
        }


def describe(count: int, already_failing: int, lines: list[str], *, english: bool = False) -> str:
    """모델에게 돌려보내는 글 — 사실만(몇 개 · 어느 시험 · 왜). 「전체 시험을 돌려라」 같은 지시는 없다."""
    shown = "\n".join(f"  - {line}" for line in lines)
    more = count - len(lines)
    if english:
        return (
            f"[system] {count} test(s) that passed at the start of this job are failing now (the {already_failing} that were already "
            f"failing at the start are left out). The harness ran the whole suite itself and re-ran each of these alone; they failed again.\n"
            f"{shown}" + (f"\n  ... and {more} more" if more > 0 else "") +
            "\nFix the code (or, if a test only guarded old behavior you changed on purpose, the test, and say so), then finish. "
            "The harness checks again when you do."
        )
    return (
        f"[시스템] 이 일을 시작할 때 통과하던 시험 {count}개가 지금 깨져 있다(시작할 때부터 깨져 있던 {already_failing}개는 뺐다). "
        f"하네스가 전체 시험을 직접 돌렸고, 아래 시험은 하나씩 혼자 다시 돌려도 또 실패했다.\n"
        f"{shown}" + (f"\n  … 그 밖에 {more}개 더" if more > 0 else "") +
        "\n코드를 고쳐라. 바꾼 동작을 지키던 옛 시험이면 시험을 고쳐도 되지만, 그 까닭을 답에 적어라. 고친 뒤 끝내면 하네스가 다시 확인한다."
    )


def leftover_note(lines: list[str], count: int, *, english: bool = False) -> str:
    """돌려보내기를 다 쓰고도 남은 새 실패 — 답 끝에 코드가 박는 글(모델의 말이 아니다)."""
    shown = "\n".join(f"- {line}" for line in lines)
    if english:
        return (f"\n\nNot clean: {count} test(s) that passed at the start of this job still fail (re-run alone, the harness confirmed them):\n"
                f"{shown}")
    return (f"\n\n※ 깨끗하지 않습니다: 이 일을 시작할 때 통과하던 시험 {count}개가 아직 깨져 있습니다(하네스가 혼자 다시 돌려 확인했습니다).\n"
            f"{shown}")
