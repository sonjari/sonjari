"""확장자 없는 글자 파일도 읽는다 (2026-09-20, 실전 코딩 과제에서 드러남).

## 어떻게 찾았나

온텔릭에게 별도 저장소의 버그 둘을 고치라고 시켰더니 31걸음 만에 제대로 고쳤는데,
걸음 30 이 이렇게 실패해 있었다:

    30 X local_read_text_file  .git/config   →  unsupported_document_format

`read_text_file` 이 **확장자로 형식을 고르는데**, 확장자가 없으면 「모르는 문서」로 떨어진다.
저장소에서 확장자 없는 글자 파일은 드물지 않다:

    Dockerfile · Makefile · .gitignore · LICENSE · .python-version · config · Procfile

전부 못 읽었다(실측). 코드 에이전트가 `Dockerfile` 을 못 읽으면 배포 관련 일은 시작도 못 한다.

★ 그래도 **아무거나 열지는 않는다.** 진짜 글자인지 내용을 보고 정한다 — 그림·실행파일을
  글자로 읽으면 전사(transcript)가 쓰레기로 찬다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "repo"
    work.mkdir()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    return LocalComputerTools(config), work


@pytest.mark.parametrize("name,body", [
    ("Dockerfile", "FROM python:3.11\nRUN pip install -r requirements.txt\n"),
    ("Makefile", "all:\n\techo hi\n"),
    (".gitignore", "*.pyc\n.venv/\n"),
    ("LICENSE", "MIT License\n"),
    ("Procfile", "web: uvicorn app:app\n"),
    (".python-version", "3.11.9\n"),
])
def test_a_text_file_without_an_extension_is_read(tmp_path: Path, name: str, body: str) -> None:
    tools, work = _tools(tmp_path)
    (work / name).write_text(body, encoding="utf-8")

    out = tools.read_text_file({"path": str(work / name)})

    text = str(out.get("text") or out.get("content") or "")
    assert body.splitlines()[0] in text, f"{name} 을 못 읽었다"


def test_a_binary_file_without_an_extension_is_still_refused(tmp_path: Path) -> None:
    """★ 넓히면 반대쪽으로 넘어간다. 그림·실행파일을 글자로 읽으면 전사가 쓰레기로 찬다."""
    tools, work = _tools(tmp_path)
    (work / "blob").write_bytes(bytes(range(256)) * 40)

    with pytest.raises((ValueError, UnicodeDecodeError)):
        tools.read_text_file({"path": str(work / "blob")})
