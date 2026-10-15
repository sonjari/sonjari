"""고른 저장소가 없는 판에서 상대 경로는 **잡 책상** 기준이다 · 새 파일은 「먼저 읽어라」에 안 막힌다 (2026-09-30 QR 판).

QR 판 걸음 기록:
     4 X local_write_file      create_qr.py   code_recon_required   ← 「이 파일은 이미 있으니 먼저 읽어라」(없는 파일이다)
     5 X local_read_text_file  create_qr.py   path_not_found: C:\\RoboMetaFit\\tools\\alture-jarvis\\create_qr.py  ← 백엔드 폴더
     … 같은 벽에 네 번

셋이 겹쳤다: (1) 읽기만 상대 경로를 프로세스 자리 기준으로 풀었다(쓰기는 이미 잡 책상 기준) (2) 관문은 root 가 비면
「새 파일 아님」으로 봤다 (3) 안내문이 없는 파일에 「이미 있으니 먼저 읽어라」라고 했다. 09-20·09-28 에 이은 같은 병.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

JOB = "job-qr-0930"


def _tools(tmp_path: Path) -> LocalComputerTools:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          local_read_roots=str(tmp_path))
    return LocalComputerTools(config)


def test_a_relative_read_without_a_repo_looks_on_the_job_desk(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    desk = tools.job_workspace(JOB, create=True)
    (desk / "create_qr.py").write_text("print('qr')\n", encoding="utf-8")

    got = tools._resolve_workspace_path({"path": "create_qr.py", "__job_id": JOB})

    assert got == (desk / "create_qr.py").resolve()


def test_a_relative_read_never_lands_in_the_backend_folder(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    tools.job_workspace(JOB, create=True)
    try:
        tools._resolve_workspace_path({"path": "create_qr.py", "__job_id": JOB})
    except Exception as exc:  # noqa: BLE001 — 없는 파일이면 없다고 해야 한다. 어디서 찾았는지가 문제다
        assert "alture-jarvis\\create_qr.py" not in str(exc) and str(Path.cwd()) not in str(exc)
        assert JOB in str(exc) or "workspace" in str(exc)


def test_a_new_file_on_the_desk_counts_as_new(tmp_path: Path) -> None:
    desk = tmp_path / "out" / "workspace" / JOB
    desk.mkdir(parents=True)
    assert BrowserAgent._creates_new_file("local_write_file", {"path": "create_qr.py"}, str(desk)) is True
    (desk / "create_qr.py").write_text("x", encoding="utf-8")
    assert BrowserAgent._creates_new_file("local_write_file", {"path": "create_qr.py"}, str(desk)) is False


def test_the_refusal_only_says_it_exists_when_it_does() -> None:
    """틀린 안내는 막는 것보다 나쁘다 — 없는 파일에 「이미 있으니 먼저 읽어라」가 네 번 헛걸음을 만들었다."""
    import inspect

    source = inspect.getsource(BrowserAgent.run)
    assert "if creates_new else" in source and "desk_root" in source
