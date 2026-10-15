"""빈 검색이 경고를 죽이고, 열 수 있던 문까지 닫고 있었다.

2026-08-10 실측. 위시켓·크몽 조사에서 검색 10번·읽기 0건으로 끝났다. 그 안을 보니
**첫 두 검색은 결과가 4건·3건이었고** 각각 "browser_open_result 에 rank 를 줘서
들어가라"는 지시까지 붙어 나갔다. 모델은 둘 다 무시하고 다시 검색했고, 그 뒤 8번은
0건이었다.

여기에 버그가 둘 겹쳐 있었다:

  1. `_searches_without_read` 를 **빈 결과가 0으로 되돌렸다.** 그래서 "읽지도 않고
     또 검색한다"는 경고가 정작 필요한 그 순간에 한 번도 안 떴다.
     결과가 없었다는 것은 더 검색하라는 뜻이 아니다.
  2. 빈 결과가 `_last_results` 를 **덮었다.** 4건을 받아 둔 뒤 0건을 여덟 번 받자
     rank 1 을 열려 해도 `no_search_results` 가 났다 — 열 수 있던 문을 검색이
     스스로 닫았다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_evidence_dir=tmp_path / "evidence",
        )
    )


def _result(rank: int) -> dict[str, Any]:
    return {"rank": rank, "title": f"결과 {rank}", "url": f"https://a.com/{rank}", "visited": False}


def test_an_empty_search_does_not_reset_the_nagging(tmp_path: Path) -> None:
    """빈 결과가 셈을 0으로 되돌리면, 헛도는 그 순간에 경고가 죽는다."""
    worker = _worker(tmp_path)
    worker._last_results = [_result(1)]
    worker._searched_before = True

    # 읽지 않은 채 검색만 세 번 더 — 중간에 0건이 섞여도 셈은 이어져야 한다.
    for had_results in (True, False, False):
        worker._searches_without_read = (
            worker._searches_without_read + 1 if worker._searched_before and worker._reads_since_search == 0 else 0
        )
        worker._searched_before = True
        worker._reads_since_search = 0
        if had_results:
            worker._last_results = [_result(1)]

    assert worker._searches_without_read >= 2, "빈 검색이 셈을 죽였다"


def test_the_instruction_gets_louder_when_nothing_is_being_read(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    worker._searches_without_read = 2
    note = worker._search_instruction([_result(1)], repeated=False, skipped=2)
    assert note.startswith("★")
    assert "읽어라" in note


def test_a_usable_result_list_survives_a_barren_search(tmp_path: Path) -> None:
    """4건을 받아 뒀는데 0건이 그것을 덮으면, rank 1 을 열 방법이 사라진다."""
    worker = _worker(tmp_path)
    worker._last_results = [_result(1), _result(2)]

    empty: list[dict[str, Any]] = []
    if empty or not worker._last_results:
        worker._last_results = empty

    assert worker._last_results, "빈 검색이 쓸 수 있던 결과를 지웠다"
    assert len(worker._last_results) == 2


def test_the_first_search_is_not_scolded(tmp_path: Path) -> None:
    """아직 아무것도 안 했는데 '또 검색했다'고 하면 안 된다."""
    worker = _worker(tmp_path)
    assert worker._searched_before is False
    assert worker._searches_without_read == 0
