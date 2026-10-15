from __future__ import annotations

from pathlib import Path

from alture_jarvis.code_index import CodeIndex


def test_code_index_extracts_symbols_imports_and_respects_gitignore(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "generated").mkdir()
    (repo / ".gitignore").write_text("generated/\n*.secret.py\n", encoding="utf-8")
    (repo / "src" / "service.py").write_text(
        "import json\nfrom pathlib import Path\n\nclass BillingService:\n    def run(self):\n        return Path('.')\n",
        encoding="utf-8",
    )
    (repo / "generated" / "bundle.py").write_text("class Decoy: pass\n", encoding="utf-8")
    (repo / "token.secret.py").write_text("SECRET = 'x'\n", encoding="utf-8")
    index = CodeIndex(tmp_path / "indexes")

    result = index.query(repo, "BillingService")

    matches = result["repo_map"]["matches"]
    assert [row["path"] for row in matches] == ["src/service.py"]
    assert {symbol["name"] for symbol in matches[0]["symbols"]} >= {"BillingService", "run"}
    assert set(matches[0]["imports"]) >= {"json", "pathlib"}
    assert result["index"]["total_files"] == 1


def test_code_index_updates_only_changed_files_and_removes_stale_rows(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    first = repo / "first.py"
    second = repo / "second.py"
    first.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    second.write_text("def beta():\n    return 2\n", encoding="utf-8")
    index = CodeIndex(tmp_path / "indexes")

    initial = index.refresh(repo)
    unchanged = index.refresh(repo)
    second.unlink()
    first.write_text("def gamma():\n    return 3\n", encoding="utf-8")
    changed = index.refresh(repo)

    assert initial["updated_files"] == 2
    assert unchanged["updated_files"] == 0
    assert unchanged["unchanged_files"] == 2
    assert changed["updated_files"] == 1
    assert changed["removed_files"] == 1
    assert index.query(repo, "gamma")["repo_map"]["matches"][0]["path"] == "first.py"


def test_code_index_never_indexes_env_or_private_key_material(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (repo / "id_rsa").write_text("secret\n", encoding="utf-8")
    (repo / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    index = CodeIndex(tmp_path / "indexes")

    result = index.query(repo)

    assert [row["path"] for row in result["repo_map"]["matches"]] == ["main.py"]


def test_natural_language_query_ranks_symbol_and_related_test(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "billing_service.py").write_text(
        "class BillingService:\n    def calculate_total(self):\n        return 1\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_billing_service.py").write_text(
        "from src.billing_service import BillingService\n\ndef test_total():\n    assert BillingService().calculate_total() == 1\n",
        encoding="utf-8",
    )
    (repo / "src" / "unrelated.py").write_text("def nope(): return 0\n", encoding="utf-8")
    index = CodeIndex(tmp_path / "indexes")

    result = index.query(repo, "BillingService 계산 로직을 고쳐줘", max_chars=8_000)
    paths = [row["path"] for row in result["repo_map"]["matches"]]

    assert paths[0] == "src/billing_service.py"
    assert "tests/test_billing_service.py" in paths
    assert result["repo_map_chars"] <= 8_000
    assert result["repo_map"]["query_terms"]


def test_korean_only_query_still_returns_bounded_semantic_scout_candidates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "workspace_paths.py").write_text(
        "def resolve_workspace_path(value: str) -> str:\n    return value\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_workspace_paths.py").write_text(
        "def test_relative_path():\n    assert True\n", encoding="utf-8"
    )
    index = CodeIndex(tmp_path / "indexes")

    result = index.query(repo, "선택한 저장소의 상대경로 오류를 찾아줘")
    matches = result["repo_map"]["matches"]

    assert matches
    assert matches[0]["path"] == "src/workspace_paths.py"
    assert matches[0]["why"] == ["semantic_fallback"]
    assert len(matches) <= 30


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "obscure_name.py").write_text(
        '"""사람이 화면을 봐야 하는 순간을 알린다 — 조용히 실패하지 않게."""\n'
        "\n\ndef notify_when_a_human_must_look():\n    return True\n",
        encoding="utf-8",
    )
    (root / "src" / "decoy.py").write_text(
        '"""전혀 상관없는 모듈."""\n\n\ndef unrelated():\n    return 0\n',
        encoding="utf-8",
    )
    return root


def test_content_is_indexed_so_a_korean_symptom_finds_an_english_filename(
    tmp_path: Path,
) -> None:
    """이름만 색인하던 시절엔 한글 질의가 영문 파일명과 한 조각도 안 겹쳤다.

    2026-08-27 실측: 24개 질의 중 19개를 아예 못 찾았고 recall@5 가 0.0% 였다.
    """
    root = _repo(tmp_path)
    index = CodeIndex(tmp_path / "store")
    index.refresh(root)

    hits = index.search_chunks(root, "사람이 화면을 봐야 하는 순간을 알려 주는 곳")

    assert hits, "본문이 색인되지 않았다"
    assert hits[0]["path"] == "src/obscure_name.py"


def test_search_uses_the_same_database_as_refresh(tmp_path: Path) -> None:
    """root 를 정규화 안 하면 조용히 **빈 다른 DB** 를 연다."""
    root = _repo(tmp_path)
    index = CodeIndex(tmp_path / "store")
    index.refresh(root)

    absolute = index.search_chunks(root.resolve(), "화면을 봐야 하는 순간")
    relative = index.search_chunks(Path(str(root)), "화면을 봐야 하는 순간")

    assert absolute and relative
    assert [row["path"] for row in absolute] == [row["path"] for row in relative]


def test_an_older_index_gets_its_missing_chunks_backfilled(tmp_path: Path) -> None:
    """이미 있는 색인은 파일이 「변경 없음」이라 본문이 영원히 안 들어갔다."""
    import sqlite3

    root = _repo(tmp_path)
    index = CodeIndex(tmp_path / "store")
    index.refresh(root)
    database = index._database_path(root.resolve())
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM chunks")
        for tokenizer in CodeIndex.FTS_TOKENIZERS:
            db.execute(f"DELETE FROM chunk_fts_{tokenizer}")
        db.commit()

    stats = index.refresh(root)

    assert stats["backfilled_chunks"] > 0
    assert stats["total_chunks"] > 0
    assert index.search_chunks(root, "화면을 봐야 하는 순간")


def test_semantic_search_degrades_quietly_when_the_embedder_is_down(
    tmp_path: Path, monkeypatch
) -> None:
    """임베더가 죽어도 검색 자체는 살아 있어야 한다 — 렉시컬로 계속 간다."""
    root = _repo(tmp_path)
    index = CodeIndex(tmp_path / "store")
    index.refresh(root)

    def _dead(_texts):
        raise RuntimeError("embedder is down")

    monkeypatch.setattr(CodeIndex, "_embed", staticmethod(_dead))

    assert index.semantic_search(root, "화면을 봐야 하는 순간") == []
    result = index.query(root, "사람이 화면을 봐야 하는 순간을 알려 주는 곳")
    paths = [row["path"] for row in result["repo_map"]["matches"]]
    assert "src/obscure_name.py" in paths


def test_what_we_already_know_about_a_path_comes_back_with_the_index(
    tmp_path: Path,
) -> None:
    """「이 폴더는 자동 생성물이라 고치면 사라진다」는 그 폴더를 열 때 나와야 한다."""
    from alture_jarvis.local_computer import LocalComputerTools

    root = _repo(tmp_path)

    class _Memory:
        def code_notes_for(self, paths, *, limit=8):
            assert "src/obscure_name.py" in paths
            return [{"path": "src", "note": "이 폴더는 자동 생성물이다", "fact_id": 1}]

    tools = LocalComputerTools.__new__(LocalComputerTools)
    tools.memory = _Memory()
    index = CodeIndex(tmp_path / "store")
    result = tools._attach_code_notes(
        index.query(root, "사람이 화면을 봐야 하는 순간을 알려 주는 곳")
    )

    notes = result["repo_map"]["known_notes"]
    assert notes and notes[0]["note"] == "이 폴더는 자동 생성물이다"
    assert "known_notes" in result["instruction"]


def test_a_broken_memory_never_breaks_the_index(tmp_path: Path) -> None:
    from alture_jarvis.local_computer import LocalComputerTools

    root = _repo(tmp_path)

    class _Broken:
        def code_notes_for(self, paths, *, limit=8):
            raise RuntimeError("drawer is on fire")

    tools = LocalComputerTools.__new__(LocalComputerTools)
    tools.memory = _Broken()
    index = CodeIndex(tmp_path / "store")

    result = tools._attach_code_notes(index.query(root, "화면을 봐야 하는 순간"))

    assert result["repo_map"]["matches"]
    assert "known_notes" not in result["repo_map"]


def test_a_repo_wide_note_is_found_from_any_path(tmp_path: Path) -> None:
    """저장 자리와 조회 자리가 갈리면 한 건도 안 맞는다 — 조용한 고장이다."""
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.memory import ConversationMemory
    from alture_jarvis.runtime import JarvisRuntime

    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out"
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    memory = ConversationMemory(config.database_path)
    session = "jarvis-real"
    message_id = memory.add_message(session, "user", "이 저장소 구조 알려줘")

    scope = JarvisRuntime._code_note_scope(r"C:\work\monorepo\tools\alture-jarvis")
    memory.add_code_note(
        path=scope,
        note="gemma_bundle 은 자동 생성물이라 직접 고치면 다음 sync 때 사라진다",
        source_message_id=message_id,
        session_id=session,
    )

    found = memory.code_notes_for(["src/alture_jarvis/agent.py"])

    assert found, "저장 자리와 조회 자리가 안 맞는다"
    assert "gemma_bundle" in found[0]["note"]


def test_the_whole_chain_works_with_real_parts(tmp_path: Path) -> None:
    """가짜로 갈아끼운 자리는 검사가 안 지나는 이음매다 — 진짜로 한 번 통과시킨다."""
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools
    from alture_jarvis.memory import ConversationMemory
    from alture_jarvis.runtime import JarvisRuntime

    root = _repo(tmp_path)
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out"
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    memory = ConversationMemory(config.database_path)
    message_id = memory.add_message("jarvis-real", "user", "이 저장소 좀 봐줘")
    memory.add_code_note(
        path=JarvisRuntime._code_note_scope(str(root)),
        note="이 저장소의 알림 진입점은 obscure_name.py 다",
        source_message_id=message_id,
        session_id="jarvis-real",
    )

    tools = LocalComputerTools.__new__(LocalComputerTools)
    tools.memory = memory
    index = CodeIndex(tmp_path / "store")
    result = tools._attach_code_notes(
        index.query(root, "사람이 화면을 봐야 하는 순간을 알려 주는 곳")
    )

    notes = result["repo_map"].get("known_notes") or []
    assert notes, "실제 부품으로 이으면 한 건도 안 나온다"
    assert "obscure_name.py" in notes[0]["note"]


def test_changing_a_file_leaves_no_old_rows_in_either_search_table(tmp_path: Path) -> None:
    """바뀐 파일의 옛 조각은 검색 표 둘에서 **같이** 사라진다 (2026-10-06).

    옛 조각을 하나씩 `chunk_id` 로 지우던 것을 파일당 한 번 `path` 로 지우게 바꿨다 — `chunk_id` 는 색인이 없는
    칸이라 조각 하나마다 표 전체를 훑었다(운영 색인 사본: `browser.py` 하나에 41초 → 0.2초). 지워지는 줄은 같아야 한다.
    """
    import sqlite3

    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "pricing.py"
    other = repo / "shipping.py"
    target.write_text("def old_discount_rule():\n    return 'aardvark_marker'\n", encoding="utf-8")
    other.write_text("def shipping_fee():\n    return 'zebra_marker'\n", encoding="utf-8")
    index = CodeIndex(tmp_path / "store")
    index.refresh(repo)

    target.write_text("def new_discount_rule():\n    return 'walrus_marker'\n", encoding="utf-8")
    index.refresh(repo)

    with sqlite3.connect(index._database_path(repo.resolve())) as db:
        chunk_ids = {row[0] for row in db.execute("SELECT id FROM chunks")}
        for tokenizer in CodeIndex.FTS_TOKENIZERS:
            rows = db.execute(f"SELECT chunk_id, path, body FROM chunk_fts_{tokenizer}").fetchall()
            assert {row[0] for row in rows} == chunk_ids, tokenizer
            bodies = " ".join(row[2] for row in rows)
            assert "aardvark_marker" not in bodies and "old_discount_rule" not in bodies, tokenizer
            assert "walrus_marker" in bodies, tokenizer
            assert "zebra_marker" in bodies, "안 바뀐 파일의 줄은 그대로다"
