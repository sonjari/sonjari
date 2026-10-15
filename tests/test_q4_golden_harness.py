from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from q4_golden_cases import CASE, judge, materialize, snapshot, validate_golden  # noqa: E402


def test_goldens_are_initially_failing_but_reference_is_fully_solvable() -> None:
    with tempfile.TemporaryDirectory(prefix="q4-golden-unit-") as folder:
        result = validate_golden(CASE, Path(folder))
    assert result["baseline_public_fails"]
    assert result["baseline_hidden_fails"]
    assert result["reference_public_passes"], result["reference_public"]
    assert result["reference_hidden_passes"], result["reference_hidden"]


def test_judge_rejects_test_tampering_even_when_reference_code_passes(tmp_path: Path) -> None:
    root = tmp_path / "case"
    materialize(CASE, root)
    before = snapshot(root)
    for relative, content in CASE.reference_files.items():
        (root / relative).write_text(content, encoding="utf-8")
    (root / "tests/test_public_contract.py").write_text("def test_cheat(): assert True\n", encoding="utf-8")
    steps = [
        {"tool": "local_read_text_file", "evidence": {}},
        {"tool": "local_read_text_file", "evidence": {}},
        {"tool": "local_read_text_file", "evidence": {}},
        {"tool": "local_run_project_command", "evidence": {"verified": False}},
        {"tool": "local_apply_edit", "evidence": {"ok": True}},
        {"tool": "local_run_project_command", "evidence": {"verified": True}},
    ]
    result = judge(CASE, root, before, status="completed", steps=steps)
    assert not result["passed"]
    assert not result["protected_ok"]
    assert "tests/test_public_contract.py" in result["unexpected_paths"]


def test_judge_requires_observed_failure_then_success(tmp_path: Path) -> None:
    root = tmp_path / "case"
    materialize(CASE, root)
    before = snapshot(root)
    for relative, content in CASE.reference_files.items():
        (root / relative).write_text(content, encoding="utf-8")
    steps = [
        *({"tool": "local_read_text_file", "evidence": {}} for _ in range(3)),
        {"tool": "local_apply_edit", "evidence": {}},
        {"tool": "local_run_project_command", "evidence": {"verified": True}},
    ]
    result = judge(CASE, root, before, status="completed", steps=steps)
    assert result["public"]["ok"] and result["hidden"]["ok"]
    assert not result["evidence_ok"]
    assert not result["passed"]
