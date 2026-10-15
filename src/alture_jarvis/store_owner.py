"""돌고 있는 설치본의 DB 를 다른 프로세스가 열지 못하게 한다 — 주인 표시와 「누가 어느 DB 를 열었나」 기록 (2026-10-10).

2026-10-09 의 사고: 손자리가 저장소 사본에서 돌린 시험이 운영 프로세스의 설정값을 물려받아 **돌고 있는 진짜 DB** 에 붙었고,
거기서 진행 중이던 판을 실패로 적었다. 그날 고친 것은 둘이다 — 설정값을 환경에 두지 않기(`config._PRIVATE`), 시험은 임시
폴더의 DB 만 열기(`tests/conftest.py`). 둘 다 「엉뚱한 손님이 주소를 **모르게**」 하는 쪽이다.

이 모듈은 반대쪽이다: 주소를 알고 와도 **집이 거절한다.** 그 사고를 공개한 글에 달린 조언 그대로다 — 「없다」가 아니라
「거절한다」를 시험하라 · 쓰기 전에 거절되는지 보라 · 어느 DB 가 골라졌는지 기록을 남겨라.

어떻게
    서버는 켜질 때 DB 에 주인(프로세스 번호와 그 프로세스가 태어난 시각)을 적는다 — `claim`.
    그 뒤 누가 그 DB 를 열려 하면 `admit` 이 먼저 본다. 주인이 **살아 있고** 그게 내가 아니면 `NotTheOwner` 를 던진다.
    DB 파일에는 손대지 않는다 — 읽기 전용으로 주인 표시만 읽는다.

★ 잘못 거절하면 아침에 앱이 안 뜬다. 그래서 거절은 좁다.
    - 서버 자신(`owner=True`)은 **절대 거절당하지 않는다.** 늘 주인 자리를 넘겨받는다(재시작 때 옛 프로세스가 아직 죽는 중이어도).
    - 주인이 죽었으면(번호가 없거나, 같은 번호의 다른 프로세스면) 지나간다.
    - 확인하다 무엇이든 틀어지면(표가 없다 · 읽기 실패 · 태어난 시각을 못 구함) 지나간다. 모르면 막지 않는다.
  막는 것은 하나뿐이다: 「살아 있는 주인이 분명히 따로 있다」.

안 하는 것(알고 남겨 둠)
    - 서버가 두 번 뜨는 것은 안 막는다(포트가 막는다) — 여기서 막으면 재시작 경합에서 새 서버가 못 뜬다.
    - 같은 폴더의 다른 저장소(기억 · 예약 등)는 안 본다. 그날 사고가 난 것은 잡 장부였다.
    - 주인이 뜨기 **전에** 열어 둔 연결은 그대로 쓴다. 문은 열 때만 본다.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

#: 태어난 시각을 견줄 때의 여유(초). 같은 프로세스를 두 번 재면 소수점 아래가 조금 다르다.
_SAME_BIRTH_SEC = 2.0
#: 기록 파일이 이 크기를 넘으면 뒤쪽 절반만 남긴다.
_LOG_MAX_BYTES = 512 * 1024
LOG_NAME = "store_opens.jsonl"


class NotTheOwner(RuntimeError):
    """이 DB 는 지금 돌고 있는 다른 프로세스의 것이다."""


def born_at(pid: int) -> float | None:
    """그 번호의 프로세스가 태어난 시각(유닉스 초). 그런 프로세스가 없으면 0.0, 알 수 없으면 None.

    번호만 보면 안 된다 — 죽은 프로세스의 번호는 다른 프로세스가 다시 받는다. 번호와 태어난 시각이 둘 다 같아야 같은 프로세스다.
    """
    if pid <= 0:
        return 0.0
    if sys.platform == "win32":
        return _born_at_windows(pid)
    try:
        import psutil  # noqa: PLC0415 — 없을 수 있다(필수 의존이 아니다)
    except Exception:  # noqa: BLE001
        return None
    try:
        return float(psutil.Process(pid).create_time())
    except psutil.NoSuchProcess:
        return 0.0
    except Exception:  # noqa: BLE001
        return None


def _born_at_windows(pid: int) -> float | None:
    try:
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        query_limited = 0x1000
        handle = kernel32.OpenProcess(query_limited, False, pid)
        if not handle:
            # 87 = 그런 번호가 없다. 5 = 있지만 못 본다(다른 사용자·보호된 프로세스) → 모른다.
            return 0.0 if ctypes.get_last_error() == 87 else None
        try:
            code = wintypes.DWORD()
            still_active = 259
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != still_active:
                return 0.0
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in (created, exited, kernel, user))):
                return None
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return ticks / 10_000_000 - 11_644_473_600  # 1601년 기준 100나노초 → 유닉스 초
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return None


def me() -> dict[str, Any]:
    """나를 가리키는 것 — 번호 · 태어난 시각 · 어느 코드에서 떴나 · 무엇으로 불렸나. 값이 아니라 자리의 이름만."""
    pid = os.getpid()
    return {
        "pid": pid,
        "born": born_at(pid),
        "code": str(Path(__file__).resolve().parent),
        "entry": Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "",
    }


def read(path: Path) -> dict[str, Any] | None:
    """DB 에 적힌 주인. 없거나 못 읽으면 None. **읽기 전용**으로 연다 — 남의 DB 일 수 있다."""
    try:
        if str(path) == ":memory:" or not Path(path).is_file():
            return None
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
        try:
            row = conn.execute("SELECT pid, born, code, entry, claimed_at FROM store_owner WHERE id = 1").fetchone()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — 표가 없다 · 잠겼다 · 깨졌다: 모르면 막지 않는다
        return None
    if not row:
        return None
    return {"pid": int(row[0] or 0), "born": row[1], "code": str(row[2] or ""), "entry": str(row[3] or ""), "claimed_at": row[4]}


def is_alive(owner: dict[str, Any] | None) -> bool:
    """그 주인이 **분명히** 살아 있나. 모르면 False(= 막지 않는다)."""
    if not owner:
        return False
    recorded = owner.get("born")
    now = born_at(int(owner.get("pid") or 0))
    if not recorded or not now:
        return False
    return abs(float(now) - float(recorded)) <= _SAME_BIRTH_SEC


def admit(path: Path, *, owner: bool = False) -> None:
    """이 DB 를 열어도 되는가. 살아 있는 주인이 따로 있으면 `NotTheOwner` — DB 파일을 건드리기 전에.

    `owner=True`(서버)는 늘 지나간다. 열고 난 뒤 `claim` 으로 주인 자리를 적는다.
    """
    if str(path) == ":memory:":
        return
    held_by = None if owner else read(Path(path))
    refused = bool(held_by) and int(held_by.get("pid") or 0) != os.getpid() and is_alive(held_by)
    _log(Path(path), "refused" if refused else ("claimed" if owner else "opened"), held_by)
    if refused:
        raise NotTheOwner(
            f"이 DB 는 지금 돌고 있는 손자리의 것이다(프로세스 {held_by['pid']}): {path} — 다른 프로세스는 열 수 없다. "
            "시험이나 스크립트라면 임시 폴더의 DB 를 써라. "
            f"[This database belongs to a running Sonjari (pid {held_by['pid']}); another process may not open it.]"
        )


def claim(conn: sqlite3.Connection) -> None:
    """이 DB 의 주인은 나다. 서버가 켜질 때 한 번 적는다(앞 주인이 누구였든 덮는다)."""
    mine = me()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS store_owner ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), pid INTEGER NOT NULL, born REAL, code TEXT, entry TEXT, claimed_at REAL)"
    )
    conn.execute(
        "INSERT INTO store_owner (id, pid, born, code, entry, claimed_at) VALUES (1, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET pid = excluded.pid, born = excluded.born, code = excluded.code, "
        "entry = excluded.entry, claimed_at = excluded.claimed_at",
        (mine["pid"], mine["born"], mine["code"], mine["entry"], time.time()),
    )


def _log(path: Path, verdict: str, held_by: dict[str, Any] | None) -> None:
    """DB 옆에 한 줄 — 누가 · 어느 DB 를 · 어떻게 됐나. 설정값도 열쇠도 적지 않는다. 기록은 여는 일을 꺾지 않는다."""
    try:
        folder = path.parent
        if not folder.is_dir():
            return  # 폴더가 아직 없다 = 처음 만드는 DB. 남의 자리에 폴더를 만들지 않는다
        mine = me()
        line = {
            "at": round(time.time(), 3),
            "verdict": verdict,
            "db": path.name,
            "pid": mine["pid"],
            "entry": mine["entry"],
            "code": mine["code"],
            "owner_pid": (held_by or {}).get("pid"),
        }
        target = folder / LOG_NAME
        if target.is_file() and target.stat().st_size > _LOG_MAX_BYTES:
            kept = target.read_bytes()[-_LOG_MAX_BYTES // 2 :]
            target.write_bytes(kept[kept.find(b"\n") + 1 :])
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001, S110 — 기록이 실패해도 여는 일은 간다
        pass


def recent(folder: Path, limit: int = 50) -> list[dict[str, Any]]:
    """기록의 마지막 몇 줄 — 진단 화면과 사람이 볼 것."""
    try:
        lines = (Path(folder) / LOG_NAME).read_text(encoding="utf-8").splitlines()[-max(1, limit) :]
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001, S112
            continue
    return out
