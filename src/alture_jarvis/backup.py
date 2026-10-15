"""기억 복제 폴더 — 앱을 지워도 대화·배운 사실은 남긴다 (W1-3, 2026-09-15 제품 결정).

## 왜 필요한가

스토어 MSIX 로 깔리면 우리가 AppData 에 새로 만든 데이터(`jarvis.db` 등)는 앱 전용 칸에 들어가고,
**앱을 지우면 같이 지워진다**(실측). 사용자 폴더 아래는 가상화되지 않으므로 거기에 복제본을 둔다.

    %USERPROFILE%\\RoboMetaFit\\JARVIS\\backup\\<세대>\\
        memory.db        대화·요약·검색 기억·배운 사실·가져온 지침 (그 표만 남긴 SQLite)
        JARVIS_PROFILE.md · settings.json · model_selection.json (있는 것만)
        manifest.json    언제·왜·무엇을 담았나 — 이 파일이 있는 폴더만 우리 세대로 본다

## 지키는 것

- DB 는 **SQLite backup API** 로 뜬다. 파일 복사는 WAL·잠금 때문에 반쪽 파일을 만든다.
- 세대는 `.partial` 폴더에 다 쓴 뒤 이름을 바꾼다. 도중에 꺼져도 반쪽 세대가 「최신」이 되지 않는다.
- 담지 않는 것: 제어 토큰, Google 토큰(DPAPI 라 기기에 묶임), 브라우저 프로필, 캐시, 모델, 잡 기록.
- 세대는 3개만 둔다. 지우는 것은 `manifest.json` 이 있는 **우리 세대 폴더**뿐이다.
- 되살리기는 기억 표가 **비어 있을 때만** 한다(첫 실행). 이미 쌓인 대화에 섞으면 id 가 겹쳐
  검색 기억이 엉뚱한 메시지를 가리킨다.
- 「백업까지 지우기」(스토어 10.2.7 깨끗한 제거)는 사용자가 확인 문구를 보내야만 돈다.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

FORMAT_VERSION = 1
KEEP_GENERATIONS = 3
DAILY_SEC = 24 * 3600
MANIFEST = "manifest.json"
DB_NAME = "memory.db"
# 기억이라 부를 수 있는 표만. 잡·승인·감사 기록은 이 PC 의 운영 기록이라 안 옮긴다.
MEMORY_TABLES = (
    "conversation_messages",
    "conversation_summaries",
    "memory_documents",
    "facts",
    "imported_instructions",
)
DATA_FILES = ("JARVIS_PROFILE.md", "settings.json", "model_selection.json")
DELETE_CONFIRMATION = "delete-backups"


class MemoryBackup:
    def __init__(
        self,
        *,
        data_dir: Path,
        database_path: Path,
        root: Path | None,
        clock: Callable[[], float] = time.time,
        build: str = "",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.database_path = Path(database_path)
        # None 이면 꺼져 있다 — 시험·임시 런타임이 사용자 홈에 복제본을 흘리지 않게.
        self.root = Path(root) if root else None
        self.clock = clock
        self.build = build
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.root is not None

    # ── 만들기 ─────────────────────────────────────────────────────────────
    def create(self, reason: str = "manual") -> dict[str, Any]:
        if self.root is None:
            return {"ok": False, "error": "disabled"}
        with self._lock:
            return self._create(reason)

    def _create(self, reason: str) -> dict[str, Any]:
        assert self.root is not None
        now = self.clock()
        name = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        final = self.root / name
        suffix = 1
        while final.exists():
            final = self.root / f"{name}-{suffix}"
            suffix += 1
        partial = final.with_name(final.name + ".partial")
        if partial.exists():
            shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        counts: dict[str, int] = {}
        if self.database_path.exists():
            counts = self._copy_memory_tables(partial / DB_NAME)
        files = []
        for file_name in DATA_FILES:
            source = self.data_dir / file_name
            if source.is_file():
                shutil.copy2(source, partial / file_name)
                files.append(file_name)
        manifest = {
            "format": FORMAT_VERSION,
            "created_at": now,
            "reason": reason,
            "build": self.build,
            "tables": counts,
            "files": files,
        }
        (partial / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        partial.rename(final)
        pruned = self._prune()
        return {"ok": True, "generation": final.name, "path": str(final), "tables": counts,
                "files": files, "pruned": pruned}

    def _copy_memory_tables(self, target: Path) -> dict[str, int]:
        source = sqlite3.connect(str(self.database_path), timeout=30.0)
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            source.close()
        try:
            rows = destination.execute(
                "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'view', 'trigger') "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for kind, name in rows:
                if kind == "table" and name in MEMORY_TABLES:
                    continue
                # 표에 딸린 트리거·인덱스는 표와 같이 사라진다. 뷰·트리거는 이름으로 지운다.
                if kind == "table" and _still_exists(destination, "table", name):
                    destination.execute(f'DROP TABLE "{name}"')
                elif kind in {"view", "trigger"} and _still_exists(destination, kind, name):
                    destination.execute(f'DROP {kind.upper()} "{name}"')
            destination.commit()
            counts = {
                name: int(destination.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
                for (name,) in destination.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            destination.execute("VACUUM")
        finally:
            destination.close()
        return counts

    # ── 보기 ───────────────────────────────────────────────────────────────
    def generations(self) -> list[dict[str, Any]]:
        if self.root is None or not self.root.is_dir():
            return []
        out = []
        for folder in self.root.iterdir():
            manifest = folder / MANIFEST
            if not folder.is_dir() or folder.name.endswith(".partial") or not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append({"generation": folder.name, "path": str(folder), **data})
        out.sort(key=lambda row: float(row.get("created_at") or 0), reverse=True)
        return out

    def status(self) -> dict[str, Any]:
        rows = self.generations()
        return {
            "enabled": self.enabled,
            "root": str(self.root) if self.root else "",
            "keep": KEEP_GENERATIONS,
            "generations": rows,
            "latest": rows[0] if rows else None,
            "memory_empty": self.memory_empty(),
            "delete_confirmation": DELETE_CONFIRMATION,
        }

    def due(self) -> bool:
        latest = next(iter(self.generations()), None)
        return latest is None or self.clock() - float(latest.get("created_at") or 0) >= DAILY_SEC

    def memory_empty(self) -> bool:
        if not self.database_path.exists():
            return True
        conn = sqlite3.connect(str(self.database_path), timeout=30.0)
        try:
            for table in ("conversation_messages", "facts"):
                if _still_exists(conn, "table", table) and conn.execute(
                    f'SELECT 1 FROM "{table}" LIMIT 1'
                ).fetchone():
                    return False
        finally:
            conn.close()
        return True

    # ── 되살리기 ────────────────────────────────────────────────────────────
    def restore(self, generation: str = "") -> dict[str, Any]:
        if self.root is None:
            return {"ok": False, "error": "disabled"}
        rows = self.generations()
        chosen = next((row for row in rows if row["generation"] == generation), None) if generation else (
            rows[0] if rows else None)
        if chosen is None:
            return {"ok": False, "error": "not_found"}
        if not self.memory_empty():
            return {"ok": False, "error": "memory_not_empty"}
        folder = Path(chosen["path"])
        restored: dict[str, int] = {}
        with self._lock:
            backup_db = folder / DB_NAME
            if backup_db.is_file():
                restored = self._restore_tables(backup_db)
            files = []
            for file_name in DATA_FILES:
                source = folder / file_name
                if not source.is_file():
                    continue
                target = self.data_dir / file_name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    # 첫 실행이 만든 기본 파일일 수 있어도 지우지 않고 옆에 둔다.
                    shutil.copy2(target, target.with_name(target.name + ".before-restore"))
                shutil.copy2(source, target)
                files.append(file_name)
        return {"ok": True, "generation": chosen["generation"], "tables": restored, "files": files}

    def _restore_tables(self, backup_db: Path) -> dict[str, int]:
        conn = sqlite3.connect(str(self.database_path), timeout=30.0)
        restored: dict[str, int] = {}
        try:
            conn.execute("ATTACH DATABASE ? AS bk", (str(backup_db),))
            for table in MEMORY_TABLES:
                if not _still_exists(conn, "table", table, schema="bk") or not _still_exists(conn, "table", table):
                    continue
                # 판이 바뀌어 칸이 늘거나 줄었을 수 있다 — 양쪽에 다 있는 칸만 옮긴다.
                mine = {row[1] for row in conn.execute(f'PRAGMA main.table_info("{table}")')}
                theirs = [row[1] for row in conn.execute(f'PRAGMA bk.table_info("{table}")')]
                columns = [name for name in theirs if name in mine]
                if not columns:
                    continue
                joined = ", ".join(f'"{name}"' for name in columns)
                cursor = conn.execute(
                    f'INSERT OR IGNORE INTO main."{table}" ({joined}) SELECT {joined} FROM bk."{table}"'
                )
                restored[table] = int(cursor.rowcount or 0)
            conn.commit()
            conn.execute("DETACH DATABASE bk")
        finally:
            conn.close()
        return restored

    # ── 지우기 ─────────────────────────────────────────────────────────────
    def delete_all(self, confirmation: str) -> dict[str, Any]:
        if self.root is None:
            return {"ok": False, "error": "disabled"}
        if confirmation != DELETE_CONFIRMATION:
            return {"ok": False, "error": "confirmation_required"}
        removed = []
        with self._lock:
            for row in self.generations():
                shutil.rmtree(row["path"], ignore_errors=True)
                removed.append(row["generation"])
            if self.root.is_dir():
                for folder in self.root.iterdir():
                    if folder.is_dir() and folder.name.endswith(".partial") and (folder / MANIFEST).exists():
                        shutil.rmtree(folder, ignore_errors=True)
        return {"ok": True, "removed": removed}

    def _prune(self) -> list[str]:
        removed = []
        for row in self.generations()[KEEP_GENERATIONS:]:
            shutil.rmtree(row["path"], ignore_errors=True)
            removed.append(row["generation"])
        return removed


def _still_exists(conn: sqlite3.Connection, kind: str, name: str, *, schema: str = "main") -> bool:
    return conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type = ? AND name = ?", (kind, name)
    ).fetchone() is not None


class DailyBackup:
    """하루 한 번. 한 시간마다 「하루 지났나」만 본다 — 켤 때마다 뜨면 재시작 잦은 날 세대가 금방 밀린다."""

    def __init__(self, backup: MemoryBackup, *, interval_sec: float = 3600.0,
                 publish: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.backup = backup
        self.interval_sec = interval_sec
        self.publish = publish
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.backup.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="jarvis-memory-backup", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_sec):
            self.tick()

    def tick(self) -> dict[str, Any] | None:
        try:
            if not self.backup.due():
                return None
            result = self.backup.create("daily")
        except Exception as exc:  # noqa: BLE001 — 백업이 넘어져도 앱은 계속 간다
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        if self.publish is not None:
            self.publish("memory_backup", {k: v for k, v in result.items() if k != "path"})
        return result

    def stop(self) -> None:
        self._stop.set()


__all__ = ["DELETE_CONFIRMATION", "DailyBackup", "MemoryBackup"]
