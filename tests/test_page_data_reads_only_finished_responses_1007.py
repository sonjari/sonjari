"""페이지 데이터 도구는 **다 받은 응답만** 읽는다 (2026-10-07 폼 벤치 과제 F 의 한 판).

응답은 머리줄만 온 때 장부에 적힌다 — 본문은 아직 오는 중일 수 있다. 끝나지 않는 응답(실시간 알림 · 긴 폴링)의 본문을
읽으려 하자 도구가 매달렸고, 브라우저가 60초 넘게 묶여 뒤의 누르기까지 전부 「앞 동작에 물려 있다」로 돌아왔다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Request:
    resource_type = "fetch"


class _Response:
    def __init__(self, url: str, payload: dict[str, Any] | None) -> None:
        self.url = url
        self.status = 200
        self.headers = {"content-type": "application/json"}
        self.request = _Request()
        self._payload = payload
        self.read = 0

    def body(self) -> bytes:
        self.read += 1
        if self._payload is None:
            raise AssertionError("아직 오는 중인 응답의 본문을 읽으려 했다 — 진짜 브라우저에서는 여기서 매달린다")
        return json.dumps(self._payload).encode("utf-8")


class _Page:
    url = "https://shop.example/list"

    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))


def test_a_response_that_is_still_arriving_is_not_read(tmp_path: Path) -> None:
    worker, page = _worker(tmp_path), _Page()
    worker._watch_network(page)
    finished = _Response("https://shop.example/api/items", {"items": [{"name": "가온 텀블러", "price": 12000}]})
    streaming = _Response("https://shop.example/api/live", None)
    page.handlers["response"](finished)
    page.handlers["response"](streaming)
    page.handlers["requestfinished"](finished.request)        # 다 받은 것은 하나뿐이다

    result = worker._page_data(page, {})

    assert streaming.read == 0
    assert finished.read == 1
    assert [row["url"] for row in result["responses"]] == ["/api/items"]


def test_nothing_is_read_before_any_response_has_finished(tmp_path: Path) -> None:
    worker, page = _worker(tmp_path), _Page()
    worker._watch_network(page)
    early = _Response("https://shop.example/api/items", {"items": []})
    page.handlers["response"](early)

    result = worker._page_data(page, {})

    assert early.read == 0
    assert not result.get("responses")
