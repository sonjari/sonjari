"""긴 목록 하나가 화면 전체를 먹지 못하게 한다 — 다만 접었으면 접었다고 말한다.

스냅샷은 DOM 순서로 자른다. 그래서 드롭다운이 열려 있으면 그 카탈로그가 앞에서
예산을 통째로 쓰고, 뒤에 있는 저장 버튼·다음 입력칸은 **화면에 뻔히 보이는데도**
목록에 안 들어온다(위시켓 기술 카탈로그에서 실제로 그랬다).

목록에서 빠진 것과 화면에 없는 것은 자비스 눈에 똑같이 보인다. 그래서 접는 것보다
**접었다고 말하는 것**이 중요하다.

여기서 지키는 것 셋:

  1. 사람·모델에게 내주는 목록(`_snapshot`)은 칸마다 상한을 건다
  2. 접었으면 몇 개를 접었는지, 그럼 무엇을 써야 하는지 같이 준다
  3. `browser_pick_suggestion` 이 속으로 훑을 때는 **접지 않는다** —
     접으면 57번째 항목을 영영 못 고른다
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Page:
    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "보유 기술"

    @property
    def url(self) -> str:
        return "https://www.wishket.com/profile/"


def _worker(tmp_path: Path, **overrides: Any) -> BrowserWorker:
    worker = BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            browser_evidence_dir=tmp_path / "evidence",
            **overrides,
        )
    )
    worker._wait_until_operable = lambda page: {"count": 1, "ms": 1, "polls": 1}  # type: ignore[method-assign]
    worker._frames_of = lambda page: ["frame0"]  # type: ignore[method-assign]
    return worker


def _capture(worker: BrowserWorker, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`_frame_elements` 가 어떤 인자로 불렸는지 받아 적는다."""
    calls: list[dict[str, Any]] = []

    def _elements(frame: Any, **kwargs: Any) -> list[dict[str, Any]]:
        del frame
        calls.append(kwargs)
        return items

    worker._frame_elements = _elements  # type: ignore[method-assign]
    return calls


def test_the_list_the_model_sees_is_capped(tmp_path: Path) -> None:
    worker = _worker(tmp_path, browser_snapshot_group_cap=15)
    calls = _capture(worker, [{"ref": "j1", "name": "Python", "tag": "li"}])

    worker._snapshot(_Page(), {})

    assert calls[0]["group_cap"] == 15


def test_folding_is_reported_with_what_to_do_next(tmp_path: Path) -> None:
    worker = _worker(tmp_path, browser_snapshot_group_cap=15)
    _capture(
        worker,
        [
            {"ref": "j1", "name": "기술명", "tag": "input"},
            {"ref": "j2", "name": "Redis", "tag": "li", "group_more": 188},
            {"ref": "j3", "name": "저장", "tag": "button"},
        ],
    )

    result = worker._snapshot(_Page(), {})

    assert result["list_more"] == 188, "접어 놓고 말하지 않았다"
    assert "browser_pick_suggestion" in result["instruction"], (
        "접힌 목록에서 무엇을 써야 하는지 안 알려 준다"
    )
    names = [item["name"] for item in result["elements"]]
    assert "저장" in names, "목록이 먹어 버려서 뒤의 버튼이 밀려났다"


def test_nothing_is_said_when_nothing_was_folded(tmp_path: Path) -> None:
    """접지 않았는데 접었다고 하면 모델이 없는 항목을 찾으러 간다."""
    worker = _worker(tmp_path)
    _capture(worker, [{"ref": "j1", "name": "저장", "tag": "button"}])

    result = worker._snapshot(_Page(), {})

    assert "list_more" not in result
    assert "instruction" not in result


def test_picking_scans_the_whole_list(tmp_path: Path) -> None:
    """고르려면 다 봐야 한다 — 접으면 57번째를 영영 못 고른다."""
    worker = _worker(tmp_path)
    calls = _capture(worker, [{"ref": "j1", "name": "Redis", "tag": "li"}])

    worker._scan_elements(_Page(), stamp_refs=False)

    assert calls[0]["group_cap"] == 0
