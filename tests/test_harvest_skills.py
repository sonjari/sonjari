"""스킬 들여오기 규칙 (W4) — 라이선스·실행 코드·설명·이름 겹침·출처 기록. 네트워크 없이 가짜 저장소로."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("harvest_skills", REPO / "scripts" / "harvest_skills.py")
harvest = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(harvest)

MIT = "MIT License\n\nCopyright (c) 2026 Someone\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"
GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007"


def _skill(root: Path, name: str, *, description: str = "Use when writing lesson notices.", extra: dict | None = None) -> None:
    folder = root / "skills" / name
    folder.mkdir(parents=True)
    front = f"---\nname: {name}\ndescription: {description}\n---\n" if description else f"---\nname: {name}\n---\n"
    (folder / "SKILL.md").write_text(front + "# Body\nIf the user agrees, proceed without asking.\n", encoding="utf-8")
    for rel, text in (extra or {}).items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_mit_repo_brings_only_text_and_records_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text(MIT, encoding="utf-8")
    _skill(repo, "lesson-notice", extra={"scripts/run.py": "print(1)", "reference/guide.md": "# guide"})
    _skill(repo, "no-desc", description="")
    _skill(repo, "copywriting")  # 기존 이름과 겹침
    skills_root = tmp_path / "skills"
    (skills_root / "vendor" / "marketing" / "copywriting").mkdir(parents=True)
    (skills_root / "vendor" / "marketing" / "copywriting" / "SKILL.md").write_text(
        "---\nname: copywriting\ndescription: x\n---\nbody", encoding="utf-8")
    existing = {"copywriting"}

    report = harvest.plan(repo, existing)
    rows = {row["name"]: row for row in report["skills"]}
    assert report["license"] == "MIT"
    assert rows["lesson-notice"]["refused"] == "" and rows["lesson-notice"]["dropped_count"] == 1
    assert rows["lesson-notice"]["hygiene_sentences"] == 1
    assert rows["no-desc"]["refused"] == "no_description"
    assert rows["copywriting"]["refused"] == "name_exists"

    added = harvest.apply(repo, report, repo="someone/skills", commit="a" * 40, collection="education",
                          skills_root=skills_root)
    assert added == ["lesson-notice"]
    target = skills_root / "vendor" / "education"
    assert (target / "lesson-notice" / "SKILL.md").exists()
    assert (target / "lesson-notice" / "reference" / "guide.md").exists()
    assert not (target / "lesson-notice" / "scripts").exists()
    assert (target / "LICENSE").exists()
    source = json.loads((target / "SOURCE.json").read_text(encoding="utf-8"))
    assert source["repo"] == "https://github.com/someone/skills" and source["commit"] == "a" * 40
    assert source["license"] == "MIT" and source["dropped_executable_files"] == {"lesson-notice": 1}


def test_unknown_or_copyleft_license_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text(GPL, encoding="utf-8")
    _skill(repo, "anything")
    report = harvest.plan(repo, set())
    assert report["skills"][0]["refused"] == "license_not_allowed:unknown"
    bare = tmp_path / "bare"
    bare.mkdir()
    _skill(bare, "no-license")
    assert harvest.plan(bare, set())["skills"][0]["refused"].startswith("license_not_allowed")


def test_duplicate_names_inside_one_repo_are_all_refused(tmp_path: Path) -> None:
    """같은 폴더 이름이 저장소 안에 여럿이면 들일 때 서로 덮는다(2026-09-15 실측: 595개 중 수십 개)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text(MIT, encoding="utf-8")
    for group in ("react", "vue"):
        folder = repo / group / "best-practices"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: best-practices\ndescription: x\n---\nbody", encoding="utf-8")
    _skill(repo, "unique-one")
    rows = harvest.plan(repo, set())["skills"]
    assert [r["refused"] for r in rows if r["name"] == "best-practices"] == ["name_duplicate_in_source"] * 2
    assert [r["refused"] for r in rows if r["name"] == "unique-one"] == [""]


def test_script_dependent_skills_can_be_held_back(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text(MIT, encoding="utf-8")
    _skill(repo, "needs-scripts", extra={"scripts/a.py": "1", "scripts/b.sh": "2"})
    _skill(repo, "text-only")
    rows = {r["name"]: r for r in harvest.plan(repo, set(), max_dropped=0)["skills"]}
    assert rows["needs-scripts"]["refused"] == "depends_on_dropped_files:2"
    assert rows["text-only"]["refused"] == ""


def test_fetch_only_takes_pinned_commits() -> None:
    import pytest

    with pytest.raises(SystemExit):
        harvest.fetch("owner/name", "main", Path("."))
    with pytest.raises(SystemExit):
        harvest.fetch("https://evil/x", "a" * 40, Path("."))
