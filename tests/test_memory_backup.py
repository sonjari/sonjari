"""기억 복제 폴더 (W1-3) — 앱을 지워도 대화·배운 사실이 남는가."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alture_jarvis.backup import DELETE_CONFIRMATION, KEEP_GENERATIONS, DailyBackup, MemoryBackup
from alture_jarvis.config import JarvisConfig
from alture_jarvis.memory import ConversationMemory


class _Clock:
    def __init__(self) -> None:
        self.now = 1_780_000_000.0

    def __call__(self) -> float:
        return self.now


def _seed(data: Path) -> Path:
    data.mkdir(parents=True, exist_ok=True)
    db = data / "jarvis.db"
    memory = ConversationMemory(db)
    memory.add_exchange("s-1", "부가세 신고 준비 도와줘", "네, 매출·매입부터 보겠습니다.")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, payload TEXT)")
    conn.execute("INSERT INTO jobs VALUES ('j1', 'secret-ish operational row')")
    conn.commit()
    conn.close()
    (data / "JARVIS_PROFILE.md").write_text("# 사용자\n호칭: 사용자님\n", encoding="utf-8")
    (data / "control.token").write_text("do-not-copy", encoding="utf-8")
    return db


def test_backup_keeps_memory_tables_and_files_but_not_token_or_jobs(tmp_path: Path) -> None:
    data = tmp_path / "data"
    db = _seed(data)
    backup = MemoryBackup(data_dir=data, database_path=db, root=tmp_path / "home" / "RoboMetaFit" / "JARVIS" / "backup")

    made = backup.create("manual")

    assert made["ok"] is True
    folder = Path(made["path"])
    assert (folder / "JARVIS_PROFILE.md").exists()
    assert not (folder / "control.token").exists()
    conn = sqlite3.connect(folder / "memory.db")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "conversation_messages" in tables and "jobs" not in tables
    assert made["tables"]["conversation_messages"] == 2
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["reason"] == "manual" and "JARVIS_PROFILE.md" in manifest["files"]


def test_only_three_generations_are_kept(tmp_path: Path) -> None:
    data = tmp_path / "data"
    db = _seed(data)
    clock = _Clock()
    backup = MemoryBackup(data_dir=data, database_path=db, root=tmp_path / "bk", clock=clock)
    for _ in range(KEEP_GENERATIONS + 2):
        backup.create("daily")
        clock.now += 60
    assert len(backup.generations()) == KEEP_GENERATIONS


def test_a_partial_generation_is_never_the_latest(tmp_path: Path) -> None:
    data = tmp_path / "data"
    db = _seed(data)
    root = tmp_path / "bk"
    backup = MemoryBackup(data_dir=data, database_path=db, root=root)
    backup.create("manual")
    (root / "29990101-000000.partial").mkdir()
    (root / "29990101-000000.partial" / "manifest.json").write_text('{"created_at": 9e12}', encoding="utf-8")
    assert backup.status()["latest"]["reason"] == "manual"


def test_restore_after_reinstall_brings_back_the_conversation(tmp_path: Path) -> None:
    old = tmp_path / "old"
    backup_root = tmp_path / "home" / "RoboMetaFit" / "JARVIS" / "backup"
    MemoryBackup(data_dir=old, database_path=_seed(old), root=backup_root).create("shutdown")

    # 앱을 지우고 다시 깔았다 — 새 데이터 폴더, 기억 표는 비어 있다.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    ConversationMemory(fresh / "jarvis.db")
    again = MemoryBackup(data_dir=fresh, database_path=fresh / "jarvis.db", root=backup_root)
    assert again.status()["memory_empty"] is True

    restored = again.restore()

    assert restored["ok"] is True and restored["tables"]["conversation_messages"] == 2
    assert (fresh / "JARVIS_PROFILE.md").read_text(encoding="utf-8").startswith("# 사용자")
    texts = [m["content"] for m in ConversationMemory(fresh / "jarvis.db").history("s-1")]
    assert "부가세 신고 준비 도와줘" in texts
    # 이미 기억이 생긴 뒤에는 섞지 않는다.
    assert again.restore()["error"] == "memory_not_empty"


def test_delete_needs_the_confirmation_and_only_removes_our_generations(tmp_path: Path) -> None:
    data = tmp_path / "data"
    root = tmp_path / "bk"
    backup = MemoryBackup(data_dir=data, database_path=_seed(data), root=root)
    backup.create("manual")
    (root / "사용자가_둔_폴더").mkdir()
    assert backup.delete_all("yes")["error"] == "confirmation_required"
    assert len(backup.generations()) == 1
    assert backup.delete_all(DELETE_CONFIRMATION)["ok"] is True
    assert backup.generations() == []
    assert (root / "사용자가_둔_폴더").exists()


def test_daily_tick_only_when_a_day_passed(tmp_path: Path) -> None:
    data = tmp_path / "data"
    clock = _Clock()
    backup = MemoryBackup(data_dir=data, database_path=_seed(data), root=tmp_path / "bk", clock=clock)
    daily = DailyBackup(backup)
    assert daily.tick()["ok"] is True
    clock.now += 3600
    assert daily.tick() is None
    clock.now += 24 * 3600
    assert daily.tick()["ok"] is True


def test_disabled_by_default_in_the_dataclass_and_on_in_the_loader(tmp_path: Path, monkeypatch) -> None:
    """사고 Q — 값이 사는 자리가 둘이다. 시험용 dataclass 는 꺼짐, 실제 로더는 사용자 폴더."""
    assert JarvisConfig(runtime_root=tmp_path).memory_backup_dir is None
    monkeypatch.setenv("JARVIS_RUNTIME_ROOT", str(tmp_path / "rt"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("JARVIS_BACKUP_DIR", raising=False)
    monkeypatch.delenv("JARVIS_MEMORY_BACKUP_ENABLED", raising=False)
    loaded = JarvisConfig.from_env()
    assert loaded.memory_backup_dir == tmp_path / "home" / "Sonjari" / "backup"
    monkeypatch.setenv("JARVIS_MEMORY_BACKUP_ENABLED", "0")
    assert JarvisConfig.from_env().memory_backup_dir is None
    assert MemoryBackup(data_dir=tmp_path, database_path=tmp_path / "x.db", root=None).create()["error"] == "disabled"
