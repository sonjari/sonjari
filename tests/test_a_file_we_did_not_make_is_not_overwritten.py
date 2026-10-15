"""이 판에서 만들지 않은 파일은 **덮지 않는다** — 옆 이름으로 만들고 말한다.

★ 2026-09-28 헤르메스 대결 확인 판 O4. `2026-09-28_회의록.docx` — 헤르메스가 방금 만든 파일과 같은 이름 — 을 묻지 않고 덮어썼다
(권한 무시 · 되돌릴 수 있는 일로 분류). 백업으로 되살렸지만 사람은 자기 파일이 바뀐 줄 모른다. 헤르메스는 같은 자리에서 덮기를 거부했다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path, monkeypatch) -> LocalComputerTools:
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None, raising=False)
    return LocalComputerTools(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents", local_computer_enabled=True,
    ))


def _write(tools: LocalComputerTools, job: str, text: str) -> dict:
    return tools.write_document_file(
        {"path": "회의록.docx", "format": "docx", "blocks": [{"type": "paragraph", "text": text}], "__job_id": job}
    )


def test_someone_elses_file_is_kept_and_ours_goes_beside_it(tmp_path: Path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    theirs = tools.documents_root / "회의록.docx"
    theirs.write_bytes(b"their file")

    result = _write(tools, "job-1", "우리 것")

    assert theirs.read_bytes() == b"their file", "남의 파일을 덮었다"
    assert Path(result["path"]).name == "회의록 (2).docx"
    assert "덮지 않고" in result["renamed_because_exists"]


def test_rewriting_our_own_file_in_the_same_run_still_overwrites(tmp_path: Path, monkeypatch) -> None:
    """한 판에서 두세 번 고쳐 쓰는 것은 그대로 덮는다 — 아니면 `(2)`·`(3)` 이 쌓인다."""
    tools = _tools(tmp_path, monkeypatch)

    first = _write(tools, "job-1", "첫 판")
    second = _write(tools, "job-1", "고친 판")

    assert first["path"] == second["path"]
    assert "renamed_because_exists" not in second


def test_a_later_run_does_not_overwrite_an_earlier_runs_file(tmp_path: Path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)

    first = _write(tools, "job-1", "어제 것")
    later = _write(tools, "job-2", "오늘 것")

    assert first["path"] != later["path"]


def test_a_file_made_this_run_is_found_by_its_bare_name(tmp_path: Path, monkeypatch) -> None:
    """T2 재측정 B3: `(4)` 로 만든 워드를 이름만으로 고치려다 작업 폴더에서 찾아 `path_not_found` — 5걸음을 돌았다."""
    tools = _tools(tmp_path, monkeypatch)
    (tools.documents_root / "회의록.docx").write_bytes(b"their file")
    made = Path(_write(tools, "job-1", "우리 것")["path"])

    resolved = tools._resolve_mutation_path({"path": made.name, "__job_id": "job-1"}, must_exist=True)

    assert resolved == made


def test_asking_the_same_name_again_rewrites_the_file_this_run_made(tmp_path: Path, monkeypatch) -> None:
    """T2 재측정 E3: 남의 `회의록.docx` 를 피해 `(10)` 을 만들고, 같은 이름을 또 달라고 하자 `(11)` 을 또 만들었다."""
    tools = _tools(tmp_path, monkeypatch)
    (tools.documents_root / "회의록.docx").write_bytes(b"their file")

    first = _write(tools, "job-1", "첫 판")
    second = _write(tools, "job-1", "고친 판")

    assert first["path"] == second["path"]
    assert Path(second["path"]).name == "회의록 (2).docx"
    assert (tools.documents_root / "회의록.docx").read_bytes() == b"their file"
