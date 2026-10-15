"""상자가 내보낸 파일도 「이 판이 만든 것」이다 — 다시 만들면 덮어쓴다 (2026-10-04 레딧 기준선 판 b79871c7).

엑셀을 상자에서 만들고 계산이 틀려 다시 만들자, 방금 자기가 만든 파일을 남의 것으로 보고 새 이름 둘
(`1889…_이름.xlsx` · `이름 (2).xlsx`)이 생겼다. 요청한 이름에는 틀린 판이 남았다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.sandbox import _fetch_target, _made_by


def test_a_file_this_job_made_is_overwritten_not_sidestepped(tmp_path: Path) -> None:
    first = _fetch_target(tmp_path, "기준선.xlsx", "run1", keep_name=True, made=set())
    assert first.name == "기준선.xlsx"
    first.write_bytes(b"wrong")
    made = {str(first)}

    again = _fetch_target(tmp_path, "기준선.xlsx", "run2", keep_name=True, made=made)

    assert again == first  # 같은 이름 — 고친 판이 틀린 판을 덮는다


def test_someone_elses_file_with_the_same_name_is_left_alone(tmp_path: Path) -> None:
    theirs = tmp_path / "기준선.xlsx"
    theirs.write_bytes(b"the person's own file")

    for made in (set(), None):
        target = _fetch_target(tmp_path, "기준선.xlsx", "run9", keep_name=True, made=made)
        assert target.name == "run9_기준선.xlsx"
    assert theirs.read_bytes() == b"the person's own file"


def test_the_registry_is_the_same_one_the_document_writer_uses(tmp_path: Path) -> None:
    """상자가 만든 파일을 문서 쓰기 손으로 다시 써도 「(2)」가 안 생긴다 — 같은 명부를 보기 때문이다."""
    local = LocalComputerTools(JarvisConfig(local_file_allowed_roots=str(tmp_path)))

    made = _made_by(local, "job-1")
    assert made is not None
    made.add(str(tmp_path / "기준선.xlsx"))

    assert str(tmp_path / "기준선.xlsx") in local._made_by_job["job-1"]
    assert _made_by(local, "") is None and _made_by(None, "job-1") is None
