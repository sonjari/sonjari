"""이름 하나로 **정의·참조·줄 범위**까지 탄다 (2026-09-21 사장님 요청).

> 관련 파일에서 관련 코드 줄까지 이제 지가 딱 타고 인덱싱을 하면은 제일 좋을거같고

없던 것은 **관계**였다. 모델은 「이 함수 누가 부르나」를 몰라서 이름을 grep 하고
파일을 통째로 읽어 확인했다 — 그게 전사를 먹었다.

★ `jedi` 로 먼저 해 봤다(0.11초에 정의는 정확히 찾음). 그런데 프로젝트 전체 참조는
  `scope='project'` 를 줘도 **2건만** 찾았다(실제 18건). 그래서 정의는 `ast` 로,
  참조는 낱말 훑기로 간다 — 둘 다 표준 라이브러리라 사용자 PC 에 반드시 있다.
  (ripgrep·ast-grep 은 이 PC 에도 없었다. 「깔려 있으면 된다」는 대부분에게 없는 기능이다.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.symbol_index import find_symbol

SOURCE = '''
import json


BILL_RATE = 3


class Ledger:
    """장부."""

    def total(self, items):
        return sum(items)

    def report(self):
        return self.total([1, 2])


@staticmethod
def monthly_fee(base, months):
    """월 수강료."""
    return base * months
'''

CALLER = '''
from .fees import monthly_fee


def invoice(base):
    # monthly_fee 를 여기서 부른다
    return monthly_fee(base, 3)


def twice(base):
    return monthly_fee(base, 1) + monthly_fee(base, 1)
'''


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "fees.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "pkg" / "billing.py").write_text(CALLER, encoding="utf-8")
    # 건너뛰어야 하는 자리 — 여기 것이 답에 섞이면 사람이 산출물 사본을 고치게 된다.
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "fees.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "fees.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def test_it_finds_where_the_function_is_defined(repo: Path) -> None:
    result = find_symbol(repo, "monthly_fee")
    assert result["ok"] is True
    assert result["definition_count"] == 1
    found = result["definitions"][0]
    assert found["file"] == "pkg/fees.py"
    assert found["kind"] == "function"


def test_the_definition_carries_a_line_range_you_can_read(repo: Path) -> None:
    """줄 범위가 없으면 모델은 파일을 통째로 읽는다 — 그게 전사를 먹는 자리다."""
    found = find_symbol(repo, "monthly_fee")["definitions"][0]
    assert found["line"] < found["end_line"]
    body = (repo / "pkg" / "fees.py").read_text(encoding="utf-8").splitlines()
    assert "def monthly_fee" in body[found["line"] - 1]


def test_a_decorator_is_included_in_what_to_read(repo: Path) -> None:
    """`@staticmethod` 위부터 읽어야 뜻이 통한다 — def 줄부터 읽으면 그게 빠진다."""
    found = find_symbol(repo, "monthly_fee")["definitions"][0]
    assert found["read_from"] < found["line"]
    body = (repo / "pkg" / "fees.py").read_text(encoding="utf-8").splitlines()
    assert body[found["read_from"] - 1].strip().startswith("@")


def test_it_finds_who_calls_it(repo: Path) -> None:
    result = find_symbol(repo, "monthly_fee")
    assert "pkg/billing.py" in result["used_in_files"]
    calls = [r for r in result["references"] if r["file"] == "pkg/billing.py"]
    assert len(calls) >= 3, calls  # import · invoice · twice 두 번


def test_the_definition_line_is_not_counted_as_a_reference(repo: Path) -> None:
    """정의를 참조로도 세면 「N 곳에서 쓴다」가 부풀어 판단을 흐린다."""
    result = find_symbol(repo, "monthly_fee")
    assert not [r for r in result["references"]
                if r["file"] == "pkg/fees.py" and r["line"] == result["definitions"][0]["line"]]


def test_a_comment_mention_is_marked_not_deleted(repo: Path) -> None:
    """지우면 진짜 단서를 잃는다 — 표시만 하고 「부르는 파일」에서는 뺀다."""
    result = find_symbol(repo, "monthly_fee")
    comments = [r for r in result["references"] if r["in_comment"]]
    assert comments, "주석 언급을 통째로 버렸다"


def test_classes_and_methods_are_found_too(repo: Path) -> None:
    assert find_symbol(repo, "Ledger")["definitions"][0]["kind"] == "class"
    method = find_symbol(repo, "total")["definitions"][0]
    assert method["kind"] == "method" and method["holder"] == "Ledger"


def test_a_module_level_constant_is_found(repo: Path) -> None:
    assert find_symbol(repo, "BILL_RATE")["definitions"][0]["kind"] == "variable"


def test_build_folders_are_not_searched(repo: Path) -> None:
    """★ 사본을 집으면 사람이 산출물을 고치게 된다."""
    files = {d["file"] for d in find_symbol(repo, "monthly_fee")["definitions"]}
    assert not any(f.startswith(("__pycache__", ".venv")) for f in files), files


def test_a_name_inside_a_longer_word_is_not_a_match(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("monthly_fee_total = 1\n", encoding="utf-8")
    assert find_symbol(tmp_path, "monthly_fee")["reference_count"] == 0


def test_a_missing_symbol_says_so_instead_of_guessing(repo: Path) -> None:
    result = find_symbol(repo, "no_such_thing")
    assert result["ok"] is True
    assert result["definition_count"] == 0 and result["reference_count"] == 0


@pytest.mark.parametrize("bad", ["", "a.b", "a b", "2things", "x;rm"])
def test_it_refuses_things_that_are_not_names(repo: Path, bad: str) -> None:
    assert find_symbol(repo, bad)["error"] == "bad_symbol_name"


def test_a_broken_file_does_not_stop_the_search(repo: Path) -> None:
    """문법이 깨진 파일 하나 때문에 저장소 전체 검색을 포기하면 안 된다."""
    (repo / "pkg" / "broken.py").write_text("def monthly_fee(  # 안 닫힘\n", encoding="utf-8")
    result = find_symbol(repo, "monthly_fee")
    assert result["ok"] and result["definition_count"] == 1
    assert "pkg/broken.py" in {r["file"] for r in result["references"]}


def test_it_hands_back_ready_to_use_reads(repo: Path) -> None:
    """★ 「그 줄만 읽어라」라고 적어 두는 대신 **답을 쥐여 준다** — 안내문은 안 먹는다."""
    call = find_symbol(repo, "monthly_fee")["next_reads"][0]
    assert call["tool"] == "local_read_text_file"
    assert call["arguments"]["path"] == "pkg/fees.py"
    assert call["arguments"]["line_start"] <= call["arguments"]["line_end"]


def test_too_many_references_say_they_were_cut(repo: Path) -> None:
    """조용히 자르면 「그게 전부」로 읽힌다."""
    (repo / "pkg" / "many.py").write_text(
        "\n".join(f"x{i} = monthly_fee" for i in range(200)), encoding="utf-8"
    )
    result = find_symbol(repo, "monthly_fee", max_references=10)
    assert result["references_truncated"] is True
    assert len(result["references"]) == 10
    assert result["reference_count"] > 10, "자른 뒤의 수만 알려 주면 전체를 알 수 없다"
