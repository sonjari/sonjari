"""「첫 낱말로 다시 찾기」는 검색칸의 버릇을 확인한 사이트에서만 켜진다 (2026-10-12).

운영 기록(10-02 ~ 10-12): 모든 사이트에 걸려 있던 동안 24번 켜졌고, 모델이 다시 찾은 결과를 그대로 연 것은 1번이었다.
가게에서는 첫 낱말이 상표라 — 상품 제목에 상표가 안 적혀 있으면 도구가 상표 하나로 다시 찾아 모델 번호를 버렸다
(모델은 세 낱말을 넣었는데 결과에는 한 낱말로 찾은 목록이 왔고, 모델은 곧바로 다시 검색했다).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alture_jarvis import browser as browser_mod
from alture_jarvis import search_boxes

#: 제목에 상표가 안 적힌 가게 목록 — 첫 낱말(상표)이 한 줄에도 없다.
SHOP_ROWS = [{"title": "가나다 프로 16 무선 은색"}, {"title": "가나다 프로 16 무선 검정 정품"}]
QUERY = "상표이름 가나다 프로"


def _worker() -> Any:
    worker = browser_mod.BrowserWorker.__new__(browser_mod.BrowserWorker)
    worker.calls = []

    def site_search(_page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        worker.calls.append(arguments["query"])
        return {"results": [{"title": "상표이름 다른 물건"}]}

    worker._site_search = site_search
    return worker


def test_a_shop_search_is_not_cut_down_to_its_first_word() -> None:
    worker = _worker()
    for host in ("www.shop.example", "search.shop.example", "shopping.portal.example", ""):
        assert worker._retry_with_head_word(None, QUERY, SHOP_ROWS, 15, host=host) is None, host
    assert worker.calls == [], "모르는 사이트에서는 모델이 넣은 검색어를 바꾸지 않는다"
    assert worker._head_retry_note == ""


def test_the_host_is_asked_for_by_default() -> None:
    """사이트를 안 넘기면 안 켜진다 — 넘기는 것을 빠뜨린 호출이 옛 동작으로 돌아가지 않게."""
    worker = _worker()
    assert worker._retry_with_head_word(None, QUERY, SHOP_ROWS, 15) is None
    assert worker.calls == []


def test_the_checked_site_still_gets_the_retry() -> None:
    worker = _worker()
    out = worker._retry_with_head_word(None, QUERY, SHOP_ROWS, 15, host="www.k-startup.go.kr")
    assert out is not None and out[0] == "상표이름"
    assert worker.calls == ["상표이름"]
    assert "하나로 다시 찾았다" in worker._head_retry_note


def test_the_search_tool_hands_its_site_to_the_retry() -> None:
    source = (Path(browser_mod.__file__)).read_text(encoding="utf-8")
    assert "self._retry_with_head_word(page, query, results, limit, host=host)" in source


def test_known_sites_come_from_checked_files(tmp_path: Path) -> None:
    assert search_boxes.needs_every_word("k-startup.go.kr")
    assert search_boxes.needs_every_word("WWW.K-Startup.go.kr")
    assert not search_boxes.needs_every_word("notk-startup.go.kr"), "이름 끝이 같다고 같은 사이트가 아니다"
    assert not search_boxes.needs_every_word("")
    for path in sorted(search_boxes.BOXES_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw.get("hosts") and str(raw.get("why") or "").strip() and str(raw.get("checked") or "").strip(), path.name

    (tmp_path / "good.json").write_text(json.dumps({"hosts": ["Board.Example"], "needs_every_word": True}), encoding="utf-8")
    (tmp_path / "off.json").write_text(json.dumps({"hosts": ["loose.example"], "needs_every_word": False}), encoding="utf-8")
    (tmp_path / "truthy.json").write_text(json.dumps({"hosts": ["truthy.example"], "needs_every_word": "yes"}), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    folder = str(tmp_path)
    assert search_boxes.needs_every_word("sub.board.example", folder)
    assert not search_boxes.needs_every_word("loose.example", folder)
    assert not search_boxes.needs_every_word("truthy.example", folder), "true 라고 적은 것만 켠다"
    assert not search_boxes.needs_every_word("k-startup.go.kr", folder), "그 폴더에 없는 사이트는 모른다"
