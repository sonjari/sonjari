"""옛 조각의 FTS 줄을 **줄 번호로** 지운다 (2026-10-22 대표 실사용 · 판 84e3771a).

FTS 의 `path` 는 UNINDEXED 라 `DELETE … WHERE path = ?` 가 파일마다 표 전체를 훑었다. 운영 색인 사본에서 파일당 147ms →
줄 번호로 12ms. 바뀐 파일 267개 따라잡기가 45초 상한을 다 쓴 까닭이었다(새 색인은 초당 125개, 운영은 초당 6개).

지키는 것: 지운 뒤 남는 줄이 예전과 같다(옛 조각이 검색에 다시 안 나온다) · 줄 번호가 어긋난 옛 색인은 예전처럼 path 로 지운다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alture_jarvis.code_index import CodeIndex


def _db(index: CodeIndex, root: Path) -> sqlite3.Connection:
    return sqlite3.connect(index._database_path(root.resolve()))


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "alpha.py").write_text("def alpha_quokka():\n    return 'quokka'\n", encoding="utf-8")
    (repo / "beta.py").write_text("def beta_wombat():\n    return 'wombat'\n", encoding="utf-8")
    return repo


def _fts_rows(index: CodeIndex, repo: Path) -> dict[str, list[tuple[int, int, str]]]:
    with _db(index, repo) as db:
        return {tk: sorted(db.execute(f"SELECT rowid, chunk_id, path FROM chunk_fts_{tk}").fetchall())
                for tk in index.FTS_TOKENIZERS}


def test_new_rows_keep_rowid_equal_to_chunk_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    index = CodeIndex(tmp_path / "index")
    index.refresh(repo)
    for rows in _fts_rows(index, repo).values():
        assert rows and all(rowid == chunk_id for rowid, chunk_id, _ in rows)
    with _db(index, repo) as db:
        assert CodeIndex._fts_rowids_aligned(db)


def test_a_changed_file_leaves_no_stale_fts_rows(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    index = CodeIndex(tmp_path / "index")
    index.refresh(repo)
    (repo / "alpha.py").write_text("def alpha_platypus():\n    return 'platypus'\n", encoding="utf-8")
    import os
    os.utime(repo / "alpha.py", ns=(1, 2_000_000_000_000_000_000))  # 시각을 확실히 바꾼다
    index.refresh(repo)
    with _db(index, repo) as db:
        chunk_ids = {row[0] for row in db.execute("SELECT id FROM chunks")}
        for tk in index.FTS_TOKENIZERS:
            fts = {row[0] for row in db.execute(f"SELECT chunk_id FROM chunk_fts_{tk}")}
            assert fts == chunk_ids, "FTS 줄과 조각이 한 줄도 어긋나면 안 된다"
    assert index.search_chunks(repo, "platypus")
    assert not any("quokka" in str(hit) for hit in index.search_chunks(repo, "quokka")), "옛 조각이 검색에 남으면 안 된다"


def test_a_misaligned_old_index_falls_back_to_deleting_by_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    index = CodeIndex(tmp_path / "index")
    index.refresh(repo)
    with _db(index, repo) as db:
        # 다른 PC 의 옛 색인처럼 줄 번호를 밀어 둔다.
        for tk in index.FTS_TOKENIZERS:
            rows = db.execute(f"SELECT rowid, body, path, chunk_id FROM chunk_fts_{tk}").fetchall()
            db.execute(f"DELETE FROM chunk_fts_{tk}")
            db.executemany(f"INSERT INTO chunk_fts_{tk}(rowid, body, path, chunk_id) VALUES (?, ?, ?, ?)",
                           [(rowid + 1000, body, path, chunk_id) for rowid, body, path, chunk_id in rows])
        db.commit()
        assert not CodeIndex._fts_rowids_aligned(db)
    (repo / "beta.py").write_text("def beta_numbat():\n    return 'numbat'\n", encoding="utf-8")
    import os
    os.utime(repo / "beta.py", ns=(1, 2_000_000_000_000_000_000))
    index.refresh(repo)
    with _db(index, repo) as db:
        chunk_ids = {row[0] for row in db.execute("SELECT id FROM chunks")}
        for tk in index.FTS_TOKENIZERS:
            assert {row[0] for row in db.execute(f"SELECT chunk_id FROM chunk_fts_{tk}")} == chunk_ids
