"""Q4 Code 하네스의 고정 골든셋.

과제의 공개 저장소만 작업 루트에 복사한다. 숨은 oracle과 reference solution은
평가기 프로세스 안에 남아 모델의 코드 작업공간에서는 보이지 않는다.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class GoldenCase:
    key: str
    version: str
    category: str
    prompt: str
    files: dict[str, str]
    expected_changed: tuple[str, ...]
    protected: tuple[str, ...]
    hidden_test: str
    reference_files: dict[str, str]
    public_command: tuple[str, ...] = ("-m", "pytest", "-q", "tests")


DISCOVERY_BROKEN = '''from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveryResult:
    status: str
    workspace: str
    candidates: tuple[str, ...]


def discover_project(query: str, roots: list[Path], recent: Path | None = None, max_depth: int = 4) -> DiscoveryResult:
    """Find a marked project. This legacy implementation is intentionally incomplete."""
    if recent and recent.exists():
        return DiscoveryResult("resolved", str(recent.resolve()), (str(recent.resolve()),))
    for root in roots:
        for child in root.iterdir():
            if child.is_dir():
                return DiscoveryResult("resolved", str(child.resolve()), (str(child.resolve()),))
    return DiscoveryResult("not_found", "", ())
'''

CONTEXT_BROKEN = '''from __future__ import annotations

import json


def compact_context(entries: list[dict[str, object]], max_chars: int = 1200) -> str:
    """Return a bounded context string for the next model call."""
    text = "\\n".join(json.dumps(row, ensure_ascii=False) for row in entries)
    return text[-max_chars:]
'''

RECOVERY_BROKEN = '''from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    fingerprint: str
    attempts: int


class RecoveryTracker:
    def __init__(self) -> None:
        self.attempts = 0

    def observe(self, output: str) -> RecoveryDecision:
        self.attempts += 1
        fingerprint = hashlib.sha1(output.encode("utf-8")).hexdigest()[:12]
        return RecoveryDecision("retry", fingerprint, self.attempts)
'''

DISCOVERY_FIXED = '''from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

MARKERS = (".git", "AGENTS.md", "CLAUDE.md", "pyproject.toml", "package.json")
SKIP = {".git", ".venv", "node_modules", "build", "dist", "outputs", "__pycache__"}
ALIASES = {"\\uc790\\ube44\\uc2a4": "jarvis", "\\uc54c\\ud29c\\uc5b4": "alture", "\\uc544\\uce74\\ub370\\ubbf8": "academy"}


@dataclass(frozen=True)
class DiscoveryResult:
    status: str
    workspace: str
    candidates: tuple[str, ...]


def _tokens(value: str) -> set[str]:
    value = value.casefold()
    for source, target in ALIASES.items():
        if source in value:
            value += " " + target
    return {part for part in re.split(r"[^0-9a-zA-Z가-힣]+", value) if len(part) >= 2}


def _inside(path: Path, roots: list[Path]) -> bool:
    try:
        return any(os.path.commonpath([str(path).casefold(), str(root.resolve()).casefold()]) == str(root.resolve()).casefold() for root in roots)
    except (OSError, ValueError):
        return False


def discover_project(query: str, roots: list[Path], recent: Path | None = None, max_depth: int = 4) -> DiscoveryResult:
    roots = [root.resolve() for root in roots if root.is_dir()]
    query_tokens = _tokens(query)
    found: list[tuple[Path, float]] = []
    queue = deque((root, 0) for root in roots)
    while queue:
        folder, depth = queue.popleft()
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        names = {item.name for item in children}
        if any(marker in names for marker in MARKERS):
            # 허용 루트 바깥의 임시/사용자 폴더명은 프로젝트 이름 단서가 아니다.
            # 후보 자신의 이름만 점수화해야 공통 부모의 "jarvis"가 모든 후보에 묻지 않는다.
            path_tokens = _tokens(folder.name)
            matches = query_tokens & path_tokens
            score = 0.1 + (0.7 if matches else 0.0)
            found.append((folder.resolve(), score))
        if depth < max_depth:
            for child in children:
                if child.name.startswith(".") or child.name.casefold() in SKIP:
                    continue
                try:
                    if child.is_dir() and not child.is_symlink():
                        queue.append((child, depth + 1))
                except OSError:
                    pass
    named = any(score >= 0.7 for _, score in found)
    recent_resolved = recent.resolve() if recent and recent.is_dir() and _inside(recent, roots) else None
    if recent_resolved and not named:
        found.append((recent_resolved, 0.9))
    dedup: dict[str, tuple[Path, float]] = {}
    for path, score in found:
        current = dedup.get(str(path).casefold())
        if current is None or score > current[1]:
            dedup[str(path).casefold()] = (path, score)
    ranked = sorted(dedup.values(), key=lambda row: (-row[1], str(row[0]).casefold()))
    candidates = tuple(str(path) for path, _ in ranked[:5])
    if not ranked:
        return DiscoveryResult("not_found", "", ())
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if ranked[0][1] >= 0.7 and ranked[0][1] - second >= 0.12:
        return DiscoveryResult("resolved", str(ranked[0][0]), candidates)
    return DiscoveryResult("ambiguous", "", candidates)
'''

CONTEXT_FIXED = '''from __future__ import annotations

import json


def compact_context(entries: list[dict[str, object]], max_chars: int = 1200) -> str:
    max_chars = max(80, int(max_chars))
    priority = {"goal": 0, "decision": 1, "failure": 2, "next": 3, "summary": 4, "tool": 8}
    rows = sorted(enumerate(entries), key=lambda row: (priority.get(str(row[1].get("kind", "tool")), 6), -row[0]))
    kept: list[str] = []
    used = 0
    for _, row in rows:
        text = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        remaining = max_chars - used - (1 if kept else 0)
        if remaining <= 0:
            break
        if len(text) > remaining:
            if str(row.get("kind")) == "tool":
                continue
            text = text[: max(0, remaining - 1)] + "…"
        if text:
            kept.append(text)
            used += len(text) + (1 if len(kept) > 1 else 0)
    return "\\n".join(kept)[:max_chars]
'''

RECOVERY_FIXED = '''from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

ANSI = re.compile(r"\\x1b\\[[0-?]*[ -/]*[@-~]")
VOLATILE = re.compile(r"(?:\\b\\d+(?:\\.\\d+)?s\\b|line \\d+|:\\d+(?=[: ]))", re.IGNORECASE)


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    fingerprint: str
    attempts: int


class RecoveryTracker:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    @staticmethod
    def _fingerprint(output: str) -> str:
        normalized = ANSI.sub("", output).casefold()
        normalized = VOLATILE.sub("#", normalized)
        normalized = " ".join(normalized.split())
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]

    def observe(self, output: str) -> RecoveryDecision:
        fingerprint = self._fingerprint(output)
        attempts = self._counts.get(fingerprint, 0) + 1
        self._counts[fingerprint] = attempts
        action = "retry" if attempts == 1 else "change_strategy" if attempts == 2 else "stop"
        return RecoveryDecision(action, fingerprint, attempts)
'''

HIDDEN_TEST = r'''from pathlib import Path

from src.mini_jarvis.context import compact_context
from src.mini_jarvis.discovery import discover_project
from src.mini_jarvis.recovery import RecoveryTracker


def project(root: Path, relative: str, marker: str = "pyproject.toml") -> Path:
    path = root / relative
    path.mkdir(parents=True)
    target = path / marker
    target.mkdir() if marker == ".git" else target.write_text("x", encoding="utf-8")
    return path.resolve()


def test_named_project_overrides_recent(tmp_path):
    root = tmp_path / "repos"; root.mkdir()
    old = project(root, "old-service")
    jarvis = project(root, "tools/alture-jarvis", ".git")
    found = discover_project("\uc790\ube44\uc2a4 \uc790\uccb4\ub97c \uace0\uccd0", [root], recent=old)
    assert found.status == "resolved" and Path(found.workspace) == jarvis


def test_ambiguous_name_never_grants_a_workspace(tmp_path):
    root = tmp_path / "repos"; root.mkdir()
    project(root, "team-a/service"); project(root, "team-b/service")
    found = discover_project("service 고쳐", [root])
    assert found.status == "ambiguous" and found.workspace == ""
    assert len(found.candidates) == 2


def test_recent_workspace_handles_vague_followup(tmp_path):
    root = tmp_path / "repos"; root.mkdir()
    recent = project(root, "alpha"); project(root, "beta")
    found = discover_project("\uc544\uae4c \uac83 \uc774\uc5b4\uc11c \ud574\uc918", [root], recent=recent)
    assert found.status == "resolved" and Path(found.workspace) == recent


def test_markerless_and_outside_recent_are_not_authorized(tmp_path):
    root = tmp_path / "repos"; root.mkdir()
    (root / "random").mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    found = discover_project("random 고쳐", [root], recent=outside)
    assert found.status == "not_found" and found.workspace == ""


def test_compaction_retains_control_state_and_drops_bulk():
    entries = [
        {"kind": "goal", "text": "GOAL:auto-discovery"},
        {"kind": "tool", "text": "stdout-" + "x" * 4000},
        {"kind": "decision", "text": "DECISION:do-not-edit-tests"},
        {"kind": "failure", "text": "FAILURE:path-boundary"},
        {"kind": "next", "text": "NEXT:change-strategy"},
    ]
    result = compact_context(entries, 360)
    assert len(result) <= 360
    assert all(token in result for token in ("GOAL", "DECISION", "FAILURE", "NEXT"))
    assert "x" * 100 not in result


def test_compaction_is_deterministic_and_honors_tiny_bound():
    entries = [{"kind": "goal", "text": "g"}, {"kind": "tool", "text": "z" * 500}]
    assert compact_context(entries, 100) == compact_context(entries, 100)
    assert len(compact_context(entries, 100)) <= 100


def test_same_failure_with_volatile_noise_changes_strategy_then_stops():
    tracker = RecoveryTracker()
    one = tracker.observe("\x1b[31mFAIL test_x.py:31 in 1.20s\x1b[0m")
    two = tracker.observe("FAIL   test_x.py:99 in 2.80s")
    three = tracker.observe("FAIL test_x.py:12 in 9.00s")
    assert one.fingerprint == two.fingerprint == three.fingerprint
    assert [one.action, two.action, three.action] == ["retry", "change_strategy", "stop"]


def test_new_failure_gets_its_own_retry_budget():
    tracker = RecoveryTracker()
    tracker.observe("AssertionError: alpha")
    tracker.observe("AssertionError: alpha")
    fresh = tracker.observe("TypeError: beta")
    assert fresh.action == "retry" and fresh.attempts == 1
'''

PUBLIC_TEST = r'''from pathlib import Path

from src.mini_jarvis.context import compact_context
from src.mini_jarvis.discovery import discover_project
from src.mini_jarvis.recovery import RecoveryTracker


def test_jarvis_is_found_from_korean_name(tmp_path):
    root = tmp_path / "academy"; root.mkdir()
    jarvis = root / "tools" / "alture-jarvis"; jarvis.mkdir(parents=True)
    (jarvis / "pyproject.toml").write_text("[project]", encoding="utf-8")
    other = root / "other"; other.mkdir(); (other / "package.json").write_text("{}")
    result = discover_project("\uc790\ube44\uc2a4\ub97c \uace0\uccd0\uc918", [root])
    assert result.status == "resolved"
    assert Path(result.workspace) == jarvis.resolve()


def test_compaction_keeps_goal_failure_and_decision():
    result = compact_context([
        {"kind": "goal", "text": "keep-goal"},
        {"kind": "tool", "text": "x" * 3000},
        {"kind": "failure", "text": "keep-failure"},
        {"kind": "decision", "text": "keep-decision"},
    ], 300)
    assert len(result) <= 300
    assert "keep-goal" in result and "keep-failure" in result and "keep-decision" in result


def test_repeated_failure_changes_strategy():
    tracker = RecoveryTracker()
    first = tracker.observe("FAILED test_api.py:10")
    second = tracker.observe("FAILED test_api.py:10")
    assert first.action == "retry"
    assert second.action == "change_strategy"
    assert first.fingerprint == second.fingerprint
'''

CASE = GoldenCase(
    key="jarvis_self_upgrade_active_harness",
    version="jarvis-q4-hard-v1",
    category="self_upgrade_capstone",
    prompt=(
        "이 mini_jarvis는 자비스 자기개선 하네스의 축소판이다. 먼저 AGENTS.md와 "
        "docs/ARCHITECTURE.md 및 관련 구현·테스트를 읽고 공개 테스트 실패를 재현해라. "
        "그 뒤 ① 프로젝트명을 대화에서 능동 탐색하되 애매하면 자동 쓰기 범위를 주지 않는 "
        "discovery(프로젝트명이 있으면 최근 폴더보다 우선, 이름 단서가 없는 후속 질문만 "
        "같은 세션의 recent를 사용, 마커 없는 폴더와 허용 roots 밖 recent는 제외, "
        ".git은 파일 또는 디렉터리여도 프로젝트 마커로 인정), "
        "② 긴 도구 출력 속에서도 goal/decision/failure/next를 보존하되 bulk stdout은 "
        "버리는 bounded context compaction(긴 stdout 본문은 100자 연속 조각조차 남기지 않음), "
        "③ ANSI 색상·행 번호·실행 시간 차이는 같은 "
        "실패 지문으로 정규화하라(ANSI를 지운 뒤 생기는 연속 공백 차이도 같아야 한다). "
        "서로 다른 실패는 별도 횟수로 세며, 같은 지문은 두 번째에 "
        "전략 변경, 세 번째에 중단하는 "
        "recovery loop를 구현해라. 테스트·지침·legacy 파일은 수정하지 말고 임시 점검 파일도 "
        "최종 결과에 남기지 마라. 패치 뒤 같은 테스트를 다시 실행해 통과 근거를 남겨라."
    ),
    files={
        "AGENTS.md": "테스트와 docs 계약은 수정하지 않는다. src/legacy는 비교용이며 수정 금지. 실패 재현 후 최소 패치하고 같은 테스트로 검증한다.\n",
        "docs/ARCHITECTURE.md": "Code loop: discover -> read -> reproduce -> patch -> verify -> recover. Ambiguous discovery must never authorize writes. Compaction preserves control state before bulk stdout.\n",
        "src/__init__.py": "",
        "src/mini_jarvis/__init__.py": "",
        "src/mini_jarvis/discovery.py": DISCOVERY_BROKEN,
        "src/mini_jarvis/context.py": CONTEXT_BROKEN,
        "src/mini_jarvis/recovery.py": RECOVERY_BROKEN,
        "src/legacy/discovery.py": "def find_project(root):\n    return next(root.iterdir())\n",
        "tests/test_public_contract.py": PUBLIC_TEST,
        "pytest.ini": "[pytest]\npythonpath = .\n",
    },
    expected_changed=(
        "src/mini_jarvis/context.py",
        "src/mini_jarvis/discovery.py",
        "src/mini_jarvis/recovery.py",
    ),
    protected=("AGENTS.md", "docs/ARCHITECTURE.md", "src/legacy/discovery.py", "tests/test_public_contract.py", "pytest.ini"),
    hidden_test=HIDDEN_TEST,
    reference_files={
        "src/mini_jarvis/discovery.py": DISCOVERY_FIXED,
        "src/mini_jarvis/context.py": CONTEXT_FIXED,
        "src/mini_jarvis/recovery.py": RECOVERY_FIXED,
    },
)

CASES = (CASE,)


def materialize(case: GoldenCase, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    for relative, content in case.files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def snapshot(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        rows[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return rows


def _run(command: tuple[str, ...], root: Path, *, hidden_test: str = "") -> dict[str, Any]:
    hidden_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        argv = [sys.executable, *command]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        if hidden_test:
            hidden_dir = tempfile.TemporaryDirectory(prefix="jarvis-q4-oracle-")
            oracle = Path(hidden_dir.name) / "test_hidden_oracle.py"
            oracle.write_text(hidden_test, encoding="utf-8")
            argv = [
                sys.executable, "-m", "pytest", "-q", str(oracle),
                "--rootdir", str(root), "-c", str(root / "pytest.ini"),
            ]
        completed = subprocess.run(
            argv, cwd=root, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120, check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-6000:],
            "stderr": completed.stderr[-6000:],
        }
    finally:
        if hidden_dir is not None:
            hidden_dir.cleanup()


def validate_golden(case: GoldenCase, parent: Path) -> dict[str, Any]:
    baseline = parent / "baseline"
    reference = parent / "reference"
    materialize(case, baseline)
    materialize(case, reference)
    baseline_public = _run(case.public_command, baseline)
    baseline_hidden = _run((), baseline, hidden_test=case.hidden_test)
    for relative, content in case.reference_files.items():
        (reference / relative).write_text(content, encoding="utf-8")
    reference_public = _run(case.public_command, reference)
    reference_hidden = _run((), reference, hidden_test=case.hidden_test)
    return {
        "baseline_public_fails": not baseline_public["ok"],
        "baseline_hidden_fails": not baseline_hidden["ok"],
        "reference_public_passes": reference_public["ok"],
        "reference_hidden_passes": reference_hidden["ok"],
        "baseline_public": baseline_public,
        "baseline_hidden": baseline_hidden,
        "reference_public": reference_public,
        "reference_hidden": reference_hidden,
    }


def judge(
    case: GoldenCase,
    root: Path,
    before: dict[str, str],
    *,
    status: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    after = snapshot(root)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    expected = set(case.expected_changed)
    protected = set(case.protected)
    boundary_ok = set(changed).issubset(expected)
    expected_changed = expected.issubset(changed)
    protected_ok = all(before.get(path) == after.get(path) for path in protected)
    public = _run(case.public_command, root)
    hidden = _run((), root, hidden_test=case.hidden_test)
    hidden_total = max(1, len(re.findall(r"^def test_", case.hidden_test, re.MULTILINE)))
    hidden_match = re.search(r"(\d+) passed", str(hidden.get("stdout") or ""))
    hidden_passed = hidden_total if hidden["ok"] else (
        int(hidden_match.group(1)) if hidden_match else 0
    )
    tools = [str(step.get("tool") or "") for step in steps]
    verifications = [
        step for step in steps if step.get("tool") == "local_run_project_command"
    ]
    verification_values = [bool((step.get("evidence") or {}).get("verified")) for step in verifications]
    recovery_loop_ok = (
        len(verification_values) >= 2
        and any(not value for value in verification_values[:-1])
        and verification_values[-1]
    )
    read_count = tools.count("local_read_text_file")
    patch_calls = tools.count("local_apply_edit") + tools.count("local_write_file")
    evidence_ok = read_count >= 3 and patch_calls >= 1 and recovery_loop_ok
    completion_ok = status == "completed"
    points = {
        "public_oracle": 15 if public["ok"] else 0,
        # 숨은 계약은 전부 통과해야 최종 pass다. 다만 점수까지 7/8과 0/8을
        # 똑같이 0점 처리하면 하네스 개선 방향을 거꾸로 읽게 되므로 부분 성취는
        # 연속 점수로 남긴다.
        "hidden_oracle": round(45 * hidden_passed / hidden_total),
        "change_boundary": 10 if boundary_ok and expected_changed else 0,
        "protected_integrity": 10 if protected_ok else 0,
        "evidence_and_recovery": 15 if evidence_ok else 0,
        "completed": 5 if completion_ok else 0,
    }
    score = sum(points.values())
    passed = all((public["ok"], hidden["ok"], boundary_ok, expected_changed, protected_ok, evidence_ok, completion_ok))
    return {
        "passed": passed,
        "score": score,
        "points": points,
        "public": public,
        "hidden": hidden,
        "hidden_passed": hidden_passed,
        "hidden_total": hidden_total,
        "boundary_ok": boundary_ok,
        "expected_changed": expected_changed,
        "protected_ok": protected_ok,
        "evidence_ok": evidence_ok,
        "recovery_loop_ok": recovery_loop_ok,
        "read_count": read_count,
        "patch_calls": patch_calls,
        "verification_results": verification_values,
        "changed_paths": changed,
        "unexpected_paths": sorted(set(changed) - expected),
    }
