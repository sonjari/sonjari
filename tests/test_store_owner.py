"""돌고 있는 설치본의 DB 는 다른 프로세스를 거절한다 — 「없다」가 아니라 「거절한다」를 본다 (2026-10-10).

2026-10-09 의 사고(사본에서 돌린 시험이 돌고 있는 진짜 DB 에 붙었다)에 대한 셋째 문이다. 앞의 둘은 주소를 모르게 하는
쪽이었다. 이것은 주소를 알고 와도 거절하는 쪽이다. 잘못 거절하면 앱이 안 뜨므로, 「지나가야 하는 경우」를 거절만큼 본다.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from alture_jarvis import store_owner
from alture_jarvis.jobs import JobStore

SRC = Path(__file__).resolve().parents[1] / "src"


def _owned_by(path: Path, pid: int, born: float | None) -> None:
    """DB 에 「주인은 저 프로세스」라고 적어 둔다 — 서버가 켜져 있는 상태를 흉내 낸다."""
    conn = sqlite3.connect(str(path))
    try:
        store_owner.claim(conn)
        conn.execute("UPDATE store_owner SET pid = ?, born = ? WHERE id = 1", (pid, born))
        conn.commit()
    finally:
        conn.close()


def _someone_else_alive() -> tuple[int, float]:
    """나 말고 살아 있는 프로세스 하나 — 이 시험을 띄운 부모."""
    pid = os.getppid()
    born = store_owner.born_at(pid)
    assert born, "부모 프로세스의 태어난 시각을 못 구했다 — 이 시험의 전제가 깨졌다"
    return pid, born


def _verdicts(folder: Path) -> list[str]:
    return [line["verdict"] for line in store_owner.recent(folder)]


def test_a_fresh_database_opens_for_anyone(tmp_path: Path) -> None:
    JobStore(tmp_path / "jarvis.db")
    assert store_owner.read(tmp_path / "jarvis.db") is None


def test_the_server_writes_itself_down_as_the_owner(tmp_path: Path) -> None:
    JobStore(tmp_path / "jarvis.db", owner=True)
    owner = store_owner.read(tmp_path / "jarvis.db")
    assert owner is not None
    assert owner["pid"] == os.getpid()
    assert store_owner.is_alive(owner)


def test_another_process_is_refused_while_the_owner_lives(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.db"
    JobStore(path)
    _owned_by(path, *_someone_else_alive())
    with pytest.raises(store_owner.NotTheOwner) as refused:
        JobStore(path)
    assert str(os.getppid()) in str(refused.value)


def test_the_refusal_comes_before_the_file_is_touched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """거절하는 동안 DB 를 **읽기 전용으로만** 열었는가를 직접 본다.

    파일의 바이트를 앞뒤로 견주는 것은 흔들린다 — 앞서 연 연결이 나중에 닫히면서 파일을 정리(WAL 체크포인트)하는 시점이
    그때그때 다르다. 처음엔 그렇게 쟀다가 다른 시험과 같이 돌 때만 떨어졌다.
    """
    path = tmp_path / "jarvis.db"
    JobStore(path)
    _owned_by(path, *_someone_else_alive())
    opened: list[tuple[str, bool]] = []
    real = sqlite3.connect

    def spy(target, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        opened.append((str(target), bool(kwargs.get("uri"))))
        return real(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy)
    with pytest.raises(store_owner.NotTheOwner):
        JobStore(path)
    monkeypatch.undo()
    assert opened, "주인 표시를 읽지도 않고 거절했다"
    assert all("mode=ro" in target and uri for target, uri in opened), opened
    assert store_owner.read(path)["pid"] == os.getppid(), "거절당한 쪽이 주인 표시를 바꿨다"


def test_a_real_second_process_is_refused(tmp_path: Path) -> None:
    """흉내가 아니라 진짜 다른 프로세스. 주인은 이 시험 프로세스다."""
    path = tmp_path / "jarvis.db"
    JobStore(path, owner=True)
    script = (
        "import sys, alture_jarvis\n"
        "from alture_jarvis import store_owner\n"
        "from alture_jarvis.jobs import JobStore\n"
        "print('CODE', alture_jarvis.__file__)\n"
        "try:\n"
        "    JobStore(sys.argv[1])\n"
        "except store_owner.NotTheOwner:\n"
        "    print('REFUSED')\n"
        "else:\n"
        "    print('OPENED')\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONUTF8"] = "1"  # 경로에 한글이 있다 — 자식의 출력을 우리가 읽는 글자로
    done = subprocess.run(
        [sys.executable, "-c", script, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120
    )
    assert "REFUSED" in done.stdout, done.stdout + done.stderr
    # 새 프로세스의 `python -c` 는 깔린 코드를 부를 수 있다 — 지금 고치는 코드를 불렀는지 본다.
    assert str(SRC) in done.stdout, done.stdout
    assert store_owner.read(path)["pid"] == os.getpid(), "거절당한 쪽이 주인 표시를 바꿨다"


def test_a_dead_owner_does_not_lock_the_database(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.db"
    JobStore(path)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait(timeout=60)
    _owned_by(path, gone.pid, 1_000_000_000.0)
    JobStore(path)


def test_a_reused_process_number_is_not_the_owner(tmp_path: Path) -> None:
    """번호는 같은데 태어난 시각이 다르다 — 죽은 주인의 번호를 다른 프로세스가 받은 경우."""
    path = tmp_path / "jarvis.db"
    JobStore(path)
    pid, born = _someone_else_alive()
    _owned_by(path, pid, born - 3600.0)
    JobStore(path)


def test_when_we_cannot_tell_we_do_not_refuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "jarvis.db"
    JobStore(path)
    _owned_by(path, *_someone_else_alive())
    monkeypatch.setattr(store_owner, "born_at", lambda pid: None)
    JobStore(path)


def test_the_server_is_never_refused_and_takes_the_seat(tmp_path: Path) -> None:
    """재시작 경합: 옛 서버가 아직 죽는 중이어도 새 서버는 뜬다."""
    path = tmp_path / "jarvis.db"
    JobStore(path)
    _owned_by(path, *_someone_else_alive())
    JobStore(path, owner=True)
    assert store_owner.read(path)["pid"] == os.getpid()


def test_the_owner_itself_may_open_again(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.db"
    JobStore(path, owner=True)
    JobStore(path)


def test_a_database_in_memory_is_nobodys(tmp_path: Path) -> None:
    store_owner.admit(Path(":memory:"))


def test_every_open_leaves_one_line_and_no_values(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.db"
    JobStore(path)
    JobStore(path, owner=True)
    _owned_by(path, *_someone_else_alive())
    with pytest.raises(store_owner.NotTheOwner):
        JobStore(path)
    assert _verdicts(tmp_path) == ["opened", "claimed", "refused"]
    last = store_owner.recent(tmp_path)[-1]
    assert last["db"] == "jarvis.db"
    assert last["owner_pid"] == os.getppid()
    assert last["pid"] == os.getpid()
    # 적는 것은 자리의 이름뿐이다 — 칸 이름을 못 박아 둔다. 설정값이나 열쇠를 실을 칸이 생기면 여기서 걸린다.
    assert set(last) == {"at", "verdict", "db", "pid", "entry", "code", "owner_pid"}


def test_the_log_does_not_grow_without_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_owner, "_LOG_MAX_BYTES", 2_000)
    path = tmp_path / "jarvis.db"
    for _ in range(60):
        store_owner.admit(path)
    log = tmp_path / store_owner.LOG_NAME
    assert log.stat().st_size < 4_000
    for line in log.read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_the_running_server_is_the_one_that_claims() -> None:
    """배선: 주인 자리를 적는 곳은 서버 하나다. 다른 자리에서 `owner=True` 로 열면 거절이 뜻을 잃는다."""
    package = SRC / "alture_jarvis"
    claimers = [
        file.name
        for file in package.glob("*.py")
        if "owner=True" in file.read_text(encoding="utf-8") and file.name not in {"store_owner.py", "jobs.py"}
    ]
    assert claimers == ["runtime.py"]
