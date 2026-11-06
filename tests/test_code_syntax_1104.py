"""파이썬이 아닌 코드도 함수 · 클래스 단위로 자른다 (tree-sitter, 2026-11-04).

측정(우리 화면 코드 ui/src · 주석 한 줄로 검색 · 무작위 30개 × 3판):
위 3개 안에 맞는 자리 끔 85/90 · 켬 87/90 — **찾는 비율은 같다.** 맞힌 덩어리 길이 중앙 120줄 → 8~10줄.
이 시험은 「같은 것을 찾되 읽을 양이 준다」와 「부품이 없으면 예전 길」 둘을 지킨다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from alture_jarvis import code_syntax
from alture_jarvis.code_index import CodeIndex

pytestmark = pytest.mark.skipif(
    not code_syntax.available("csharp"), reason="tree-sitter 부품이 없는 환경 — 아래 부품 없음 시험만 의미가 있다"
)

UNITY = """using UnityEngine;

namespace Game.Player
{
    /// <summary>점프와 이동</summary>
    public class PlayerController : MonoBehaviour
    {
        void Update()
        {
            if (Input.GetButtonDown("Jump")) Jump();
        }

        // 땅에 닿아 있을 때만 뛴다
        private void Jump()
        {
            GetComponent<Rigidbody>().AddForce(Vector3.up * 5f);
        }
    }
}
"""

TS = """import { invoke } from "@tauri-apps/api/core";

export async function loadBootstrap(): Promise<void> {
  await invoke("bootstrap");
}

// 바깥 링크는 사용자 브라우저로 연다
export const openExternalUrl = async (url: string) => {
  await invoke("open", { url });
};

export class Store {
  save(): void {}
}
"""


def test_csharp_methods_get_their_own_chunk_with_class_prefix() -> None:
    chunks = code_syntax.chunks(UNITY, "csharp")
    names = {c["symbol"]: (c["start_line"], c["end_line"]) for c in chunks if c["symbol"]}
    assert names["PlayerController.Jump"] == (14, 17)
    assert "PlayerController.Update" in names
    jump = next(c for c in chunks if c["symbol"] == "PlayerController.Jump")
    assert "땅에 닿아" in jump["doc"]  # 바로 위 주석이 설명으로 붙는다 — 한글 검색이 여기 걸린다
    # 예전 정규식은 C# 메서드를 하나도 못 잡았다
    assert not any(s["name"] == "Jump" for s in CodeIndex._generic_facts(UNITY)[0])
    symbols, imports = CodeIndex._generic_facts(UNITY, "csharp")
    assert {s["name"] for s in symbols} >= {"PlayerController", "Update", "Jump"}
    assert "UnityEngine" in imports


def test_typescript_arrow_functions_and_imports_are_both_kept() -> None:
    symbols, imports = CodeIndex._generic_facts(TS, "typescript")
    assert {s["name"] for s in symbols} >= {"loadBootstrap", "openExternalUrl", "Store", "save"}
    # 가져오기는 합친다 — 정규식이 잡던 `from "…"` 을 잃지 않는다
    assert "@tauri-apps/api/core" in imports


def test_without_the_parts_it_falls_back_to_the_old_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code_syntax, "available", lambda language: False)
    assert code_syntax.chunks(UNITY, "csharp") is None
    chunks = CodeIndex._chunks_for(UNITY, "csharp")
    assert [c["kind"] for c in chunks] == ["block"]


def test_a_broken_file_still_gives_what_it_can() -> None:
    broken = UNITY.replace("private void Jump()", "private void Jump(")  # 괄호 하나 빠짐
    chunks = code_syntax.chunks(broken, "csharp")
    assert chunks is not None and any(c["symbol"].endswith("Update") for c in chunks)


def test_an_existing_index_is_rechunked_once_when_the_chunker_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "PlayerController.cs").write_text(UNITY, encoding="utf-8")
    store = tmp_path / "store"
    index = CodeIndex(store)
    index.refresh(repo)
    db_path = index._database_path(repo.resolve())
    # 예전 색인 흉내: 덩어리를 120줄 창으로 되돌리고 판 기록을 지운다
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE chunks SET kind = 'block', symbol = ''")
        db.execute("DELETE FROM index_meta")
    second = index.refresh(repo)
    with sqlite3.connect(db_path) as db:
        symbols = {row[0] for row in db.execute("SELECT symbol FROM chunks")}
    assert "PlayerController.Jump" in symbols
    assert second["updated_files"] == 1
    # 판이 같으면 다시 읽지 않는다
    third = index.refresh(repo)
    assert third["updated_files"] == 0 and third["unchanged_files"] == 1
