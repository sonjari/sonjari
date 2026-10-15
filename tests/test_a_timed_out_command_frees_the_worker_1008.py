"""시간 제한에 걸린 명령은 **그 아래 프로세스까지** 끝내고, 일꾼을 붙잡지 않는다 (2026-10-08).

바깥 과제(27B) 한 판: 모델이 경우의 수를 전부 따지는 확인용 스크립트를 `local_run_shell` 로 돌렸다. 시간 제한이 다 되자
`subprocess.run` 은 **직접 띄운 PowerShell 만** 죽였고, 그 아래 파이썬(가상환경의 파이썬은 진짜 파이썬을 자식으로 띄운다)은
살아남아 출력 통로를 쥐었다. 윈도우의 `subprocess.run` 은 죽인 뒤 **시간 제한 없이** 출력을 마저 읽으려 하므로 일꾼 스레드가
영원히 멈췄다 — 판을 취소해도 안 풀리고, 뒤의 요청이 전부 줄만 섰다(다음 판은 10분 동안 시작도 못 했다). 살아남은 스크립트는
16분 동안 CPU 를 태웠다. 그 스크립트를 끄자 일꾼이 바로 풀렸다.

같은 방식으로 돌던 `local_run_project_command` 도 같다 — 모델이 쓴 코드에 무한 반복이 있으면 시험이 안 끝난다.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools

pytestmark = pytest.mark.skipif(os.name != "nt", reason="윈도우의 프로세스 나무·통로 상속에서 나는 걸림이다")

#: 손자를 띄워 놓고 둘 다 오래 잔다. 손자는 자기 번호를 파일에 적는다(끝났는지 보려고).
SLEEPER = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', "
    "\"import os, time; open('grandchild.pid', 'w').write(str(os.getpid())); time.sleep(90)\"])\n"
    "time.sleep(90)\n"
)


def _local(tmp_path: Path) -> tuple[Path, LocalComputerTools]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "sleeper.py").write_text(SLEEPER, encoding="utf-8")
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    local = LocalComputerTools(config)
    local.authorize_code_workspace("job-timeout", str(project))  # 명령줄 도구는 판에 묶인 작업 자리에서 돈다
    return project, local


def _alive(pid: int) -> bool:
    done = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=20)
    return str(pid) in (done.stdout or "")


def _grandchild(project: Path) -> int:
    marker = project / "grandchild.pid"
    for _ in range(40):
        if marker.exists() and marker.read_text(encoding="utf-8").strip().isdigit():
            return int(marker.read_text(encoding="utf-8").strip())
        time.sleep(0.25)
    return 0


@pytest.mark.parametrize("tool", ["shell", "project_command"])
def test_a_timeout_returns_on_time_and_leaves_nothing_running(tmp_path: Path, tool: str) -> None:
    project, local = _local(tmp_path)
    started = time.monotonic()

    if tool == "shell":
        result = local.run_shell({"path": str(project), "command": "python sleeper.py", "timeout_sec": 5, "__job_id": "job-timeout"})
    else:
        result = local.run_project_command({"path": str(project), "command": "python sleeper.py", "timeout_sec": 5, "__job_id": "job-timeout"})
    elapsed = time.monotonic() - started

    assert result.get("timed_out") is True, result
    assert elapsed < 40, f"시간 제한 5초인 명령이 {elapsed:.0f}초 만에 돌아왔다 — 살아남은 손자를 기다렸다"
    pid = _grandchild(project)
    assert pid, "손자가 뜨지 않았다 — 시험이 재려던 상황이 안 만들어졌다"
    time.sleep(1.0)
    assert not _alive(pid), "시간 제한에 걸린 명령의 손자 프로세스가 살아 있다"


def test_a_command_that_finishes_in_time_is_untouched(tmp_path: Path) -> None:
    """★ 좋은 표본 — 제때 끝나는 명령은 예전 그대로 출력과 종료 값을 준다."""
    project, local = _local(tmp_path)

    result = local.run_shell({"path": str(project), "command": "python -c \"print('ok-123')\"", "timeout_sec": 30, "__job_id": "job-timeout"})

    assert result.get("timed_out") is False and result.get("exit_code") == 0
    assert "ok-123" in str(result.get("stdout"))
