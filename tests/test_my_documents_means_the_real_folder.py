"""「내 문서 폴더에 만들어 줘」의 내 문서는 **사람의 문서 폴더**다.

★ 2026-09-28 헤르메스 대결 O_T2. 워드는 30초에 잘 만들었는데 자리가 틀렸다 — 모델은 `내 문서/20260928_회의록_양식.docx`
를 넣었고, 문서 도구가 우리 결과물 폴더(`Documents\\JARVIS`)를 먼저 앞에 붙여 `Documents\\JARVIS\\내 문서\\` 라는
하위 폴더를 새로 만들었다. 사람은 문서 폴더를 열고 파일을 못 찾는다 — 만든 것을 못 찾으면 안 만든 것과 같다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path, monkeypatch) -> tuple[LocalComputerTools, Path]:
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None, raising=False)
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        documents_dir=home / "Documents" / "Ontelic",
        local_computer_enabled=True,
        local_file_allowed_roots=str(home / "Documents"),
    )
    return LocalComputerTools(config), home


def _write(tools: LocalComputerTools, path: str) -> dict:
    return tools.write_document_file(
        {"path": path, "format": "docx", "blocks": [{"type": "paragraph", "text": "회의록"}], "__job_id": "job-1"}
    )


def test_my_documents_is_the_documents_folder_not_a_subfolder(tmp_path: Path, monkeypatch) -> None:
    tools, home = _tools(tmp_path, monkeypatch)

    _write(tools, "내 문서/20260928_회의록_양식.docx")

    assert (home / "Documents" / "20260928_회의록_양식.docx").is_file()
    assert not (home / "Documents" / "Ontelic" / "내 문서").exists(), "결과물 폴더 안에 「내 문서」 하위 폴더를 만들었다"


def test_a_plain_name_still_goes_to_our_results_folder(tmp_path: Path, monkeypatch) -> None:
    """사용자 폴더를 말하지 않았으면 예전처럼 사람이 찾을 수 있는 결과물 폴더로 간다."""
    tools, home = _tools(tmp_path, monkeypatch)

    _write(tools, "보고서.docx")

    assert (home / "Documents" / "Ontelic" / "보고서.docx").is_file()


def test_a_bare_file_name_goes_to_the_folder_the_request_named() -> None:
    """같은 요청에 모델이 한 번은 `내 문서/…`, 한 번은 파일 이름만 줬다(2026-09-28 T2 재시험). 요청이 댄 폴더로 맞춘다."""
    from alture_jarvis.agent import _into_asked_folder

    prompt = "내 문서 폴더에 오늘 날짜 회의록 양식을 워드로 만들어 줘"
    moved = _into_asked_folder("local_write_document", {"path": "회의록.docx"}, prompt)
    assert moved["path"] == "내 문서/회의록.docx"

    assert _into_asked_folder("local_write_document", {"path": "C:/x/회의록.docx"}, prompt)["path"] == "C:/x/회의록.docx"
    assert _into_asked_folder("local_write_document", {"path": "내 문서/회의록.docx"}, prompt)["path"] == "내 문서/회의록.docx"
    assert _into_asked_folder("local_write_file", {"path": "a.txt"}, prompt)["path"] == "a.txt"


def test_a_folder_named_as_a_source_is_not_a_destination() -> None:
    from alture_jarvis.agent import _asked_destination_folder

    assert _asked_destination_folder("이 PC 문서 폴더(내 문서)에 워드 문서로 정리해줘") == "내 문서"
    assert _asked_destination_folder("바탕화면에 저장해 줘") == "바탕화면"
    assert _asked_destination_folder("바탕화면에 있는 계약서를 읽고 요약을 워드로") == ""
    assert _asked_destination_folder("다운로드 폴더의 설계서를 읽고 정리해 줘") == ""
    assert _asked_destination_folder("표 형식 문서로 정리해 줘") == ""


def test_our_folder_name_is_not_nested_inside_itself(tmp_path: Path, monkeypatch) -> None:
    """앞 답의 `Documents/JARVIS/…` 를 보고 모델이 `JARVIS/회의록.docx` 를 넣어 `JARVIS/JARVIS/` 가 생겼다(2026-09-28)."""
    tools, home = _tools(tmp_path, monkeypatch)

    _write(tools, "Ontelic/회의록.docx")

    assert (home / "Documents" / "Ontelic" / "회의록.docx").is_file()
    assert not (home / "Documents" / "Ontelic" / "Ontelic").exists()


def test_a_subfolder_under_the_asked_folder_stays_under_it() -> None:
    """T2 재측정 B1: 「내 문서 폴더에」인데 `회의록/양식.docx` 를 줘서 `Documents/JARVIS/회의록/` 에 저장됐다."""
    from alture_jarvis.agent import _USER_FOLDER_KEYS, _into_asked_folder
    from alture_jarvis.local_computer import _USER_FOLDER_ALIASES

    prompt = "내 문서 폴더에 회의록 양식을 워드로 만들어 줘"
    assert _into_asked_folder("local_write_document", {"path": "회의록/양식.docx"}, prompt)["path"] == "내 문서/회의록/양식.docx"
    assert _into_asked_folder("local_write_document", {"path": "JARVIS/양식.docx"}, prompt)["path"] == "JARVIS/양식.docx"
    assert _USER_FOLDER_KEYS == frozenset(_USER_FOLDER_ALIASES), "두 곳에 적은 폴더 이름이 갈렸다"
