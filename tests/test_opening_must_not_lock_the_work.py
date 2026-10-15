"""띄워 주는 것이 **못 고치게 만들면** 안 된다.

★ 2026-09-01 라이브. 아침에 「만들면 바로 띄운다」를 넣었다. 저녁에 이렇게 됐다:

    3걸음  hwpx 만듦 → 한글이 뜸 → 한글이 그 파일을 붙잡음
    6걸음  같은 파일에 다시 쓰기 → Access Denied
    8걸음  또 시도 → Access Denied
    끝     "한글 창을 닫고 다시 말씀해 주세요"

게다가 계획 대조의 `_open_artifacts` 는 파일 핸들을 **실제로 열어 본다.** 잠긴
파일은 그 검사도 통과 못 해서 「열 수 있는 산출물 없음」이 됐다 — 파일 셋을
제대로 만든 판이 스스로 `시킨 것 0/1` 이라고 보고했다.

보여 주려던 것이 일을 막았다. 그래서 띄우는 자리를 **판 끝으로** 옮겼다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> LocalComputerTools:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents",
        local_computer_enabled=True,
    )
    return LocalComputerTools(config)


def _write(tools: LocalComputerTools, name: str, text: str, job: str = "job-1") -> dict:
    return tools.write_document_file(
        {"path": name, "format": "docx", "blocks": [{"type": "paragraph", "text": text}], "__job_id": job}
    )


def test_making_a_document_does_not_open_it_yet(tmp_path: Path, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: opened.append(p))
    tools = _tools(tmp_path)

    result = _write(tools, "보고서.docx", "첫 판")

    assert result["opened"] == "deferred"
    assert opened == [], "만드는 도중에 띄웠다 — 다음 걸음이 그 파일을 못 고친다"


def test_the_same_file_can_be_rewritten_during_the_run(tmp_path: Path, monkeypatch) -> None:
    """이게 라이브에서 죽은 자리다. 세 번 고쳐 쓸 수 있어야 한다."""
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None)
    tools = _tools(tmp_path)

    for round_number in range(3):
        result = _write(tools, "보고서.docx", f"{round_number}번째 판")
        assert result["verified"] is True

    from alture_jarvis.documents import edit_document  # noqa: F401  (형식 확인용)
    from alture_jarvis.document_reader import preview_of_file

    assert "2번째 판" in preview_of_file(tools.documents_root / "보고서.docx")


def test_it_opens_once_when_the_run_is_over(tmp_path: Path, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: opened.append(p))
    tools = _tools(tmp_path)
    _write(tools, "가.docx", "가")
    _write(tools, "나.docx", "나")

    assert tools.open_pending("job-1") == "opened"

    # 창 폭탄을 만들지 않는다 — 마지막 것 하나다.
    assert opened == [str(tools.documents_root / "나.docx")]
    # 두 번 불러도 다시 안 뜬다.
    assert tools.open_pending("job-1") == ""
    assert len(opened) == 1


def test_a_failure_to_open_is_not_a_failure_to_make(tmp_path: Path, monkeypatch) -> None:
    def boom(path: str) -> None:
        raise OSError("no handler")

    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", boom)
    tools = _tools(tmp_path)
    result = _write(tools, "보고서.docx", "본문")

    assert result["verified"] is True
    assert tools.open_pending("job-1").startswith("open_failed:")


def test_a_locked_file_is_written_beside_it_and_said_so(tmp_path: Path, monkeypatch) -> None:
    """사람이 그 파일을 열어 두었을 때 **빈손으로 끝내지 않는다.**"""
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None)
    tools = _tools(tmp_path)
    _write(tools, "이력서.docx", "첫 판")

    calls = {"n": 0}
    real = __import__("alture_jarvis.documents", fromlist=["write_document"]).write_document

    def locked_once(target, fmt, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("한글이 붙잡고 있다")
        return real(target, fmt, payload)

    monkeypatch.setattr("alture_jarvis.local_computer.write_document", locked_once)
    result = _write(tools, "이력서.docx", "둘째 판")

    assert result["verified"] is True
    assert Path(result["path"]).name == "이력서 (2).docx"
    # 조용히 이름을 바꾸지 않는다.
    assert "열려 있어" in result["renamed_because_locked"]


def test_a_tool_called_outside_a_job_opens_nothing(tmp_path: Path, monkeypatch) -> None:
    """★ 잡이 없으면 **안 띄운다** (2026-09-01 저녁, 두 번째 교정).

    처음엔 "미룰 자리가 없으니 바로 띄운다"로 뒀다. 그랬더니 라이브 상자 **검사**가
    `성적표.csv` 를 만들자마자 엑셀을 띄웠고 회귀가 69% 에서 통째로 멎었다
    (py-spy 로 `sandbox.run` 에 걸려 있는 것을 확인했다).

    검사가 사람 화면에 창을 띄우면 그건 검사가 아니다. 그리고 잡이 없다는 것은
    띄워 줄 사람도 없다는 뜻이다 — 경로는 결과에 이미 들어 있다.
    """
    opened: list[str] = []
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: opened.append(p))
    tools = _tools(tmp_path)

    tools.remember_to_open("", tmp_path / "직접.docx")

    assert opened == []
