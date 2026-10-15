"""그림으로 된 본문을 읽는 동안, 지금 읽는 조각을 화면에 비춘다 (2026-10-10).

대표 화면: 상품 상세가 통이미지인 페이지에서 「본문 읽기」 한 줄만 30초 가까이 떠 있어 멈춘 것처럼 보였다. 그동안 손자리는
그림을 조각으로 잘라 하나씩 읽고 있었다(조각 하나에 3~4초 · 많으면 여덟 번). 무엇을 읽는지 조각 그림과 「몇 번째 조각」을
화면에 내보낸다.

지키는 것
- 알림은 **읽기 직전**에 나간다(읽은 뒤가 아니라) · 조각마다 한 번 · 다 읽으면 거두는 알림 하나.
- 알림이 실패해도 읽은 글은 같다. 통로가 없으면 예전과 한 글자도 다르지 않다.
- 그림은 모델에게 가지 않는 길(`agent_looking`)로만 나간다 — 걸음 장부·맡긴 쪽 진행 한 줄에는 실리지 않는다.
"""
from __future__ import annotations

import base64
import io
from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.events import EventBus
from alture_jarvis.runtime import JarvisRuntime


def _png(width: int, height: int) -> bytes:
    image_module = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image_module.new("RGB", (width, height), (250, 250, 250)).save(buffer, format="PNG")
    return buffer.getvalue()


class _Response:
    def __init__(self, raw: bytes) -> None:
        self._raw, self.ok = raw, bool(raw)

    def body(self) -> bytes:
        return self._raw


class _Request:
    def __init__(self, by_url: dict[str, bytes]) -> None:
        self.by_url = by_url

    def get(self, url: str, timeout: int = 0) -> _Response:
        return _Response(self.by_url.get(url, b""))


class _Context:
    def __init__(self, by_url: dict[str, bytes]) -> None:
        self.request = _Request(by_url)


class _Page:
    url = "https://shop.example/item/1"

    def __init__(self, by_url: dict[str, bytes]) -> None:
        self.context = _Context(by_url)


def _worker(reader: Any, sink: Any = None) -> BrowserWorker:
    worker = object.__new__(BrowserWorker)
    worker.image_text_reader = reader
    if sink is not None:
        worker.image_read_sink = sink
    return worker


def test_each_piece_is_shown_just_before_it_is_read() -> None:
    order: list[str] = []
    told: list[dict[str, Any]] = []

    def sink(info: dict[str, Any]) -> None:
        told.append(info)
        order.append("done" if info.get("done") else f"show{info['tile']}")

    def reader(png: bytes) -> str:
        order.append("read")
        return f"줄 {len(order)}"

    page = _Page({"https://img.example/detail.png": _png(860, 4000)})
    _text, images, tiles = _worker(reader, sink)._read_body_images(page, ["https://img.example/detail.png"])

    assert images == 1 and tiles == 3
    assert order == ["show1", "read", "show2", "read", "show3", "read", "done"], "읽기 직전에 비추고, 다 읽으면 거둔다"
    shown = [row for row in told if not row.get("done")]
    assert [(row["image"], row["images"], row["tile"], row["tiles"]) for row in shown] == [(1, 1, 1, 3), (1, 1, 2, 3), (1, 1, 3, 3)]


def test_the_picture_is_a_small_jpeg_of_that_piece() -> None:
    image_module = pytest.importorskip("PIL.Image")
    told: list[dict[str, Any]] = []
    page = _Page({"https://img.example/detail.png": _png(1400, 1500)})

    _worker(lambda png: "글", told.append)._read_body_images(page, ["https://img.example/detail.png"])

    first = told[0]
    assert first["picture"].startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(first["picture"].split(",", 1)[1])
    small = image_module.open(io.BytesIO(raw))
    assert small.size == (first["width"], first["height"])
    assert small.size[0] <= 240, "화면에 비출 만큼만 — 원본 조각을 그대로 실어 보내지 않는다"
    assert len(first["picture"]) < 40_000


def test_the_count_says_which_image_when_there_are_two() -> None:
    told: list[dict[str, Any]] = []
    page = _Page({"https://img.example/a.png": _png(800, 1200), "https://img.example/b.png": _png(800, 1200)})

    _worker(lambda png: "글", told.append)._read_body_images(
        page, ["https://img.example/a.png", "https://img.example/b.png", "https://img.example/a.png"],
    )

    shown = [(row["image"], row["images"], row["tile"], row["tiles"]) for row in told if not row.get("done")]
    assert shown == [(1, 2, 1, 1), (2, 2, 1, 1)], "같은 주소를 두 번 세지 않는다"


def test_the_piece_count_never_promises_more_than_the_cap() -> None:
    told: list[dict[str, Any]] = []
    page = _Page({"https://img.example/long.png": _png(765, 30_000)})

    _text, _images, tiles = _worker(lambda png: "글", told.append)._read_body_images(page, ["https://img.example/long.png"])

    shown = [row for row in told if not row.get("done")]
    assert tiles == BrowserWorker._IMAGE_READ_MAX_TILES == len(shown)
    assert {row["tiles"] for row in shown} == {BrowserWorker._IMAGE_READ_MAX_TILES}, "한도까지만 읽으니 그만큼만 말한다"
    assert [row["tile"] for row in shown] == list(range(1, tiles + 1))


def test_a_broken_sink_changes_nothing_that_was_read() -> None:
    def broken(info: dict[str, Any]) -> None:
        raise RuntimeError("화면이 닫혔다")

    def reader_factory() -> Any:
        count = {"n": 0}

        def reader(png: bytes) -> str:
            count["n"] += 1
            return f"줄 {count['n']}"

        return reader

    sources = ["https://img.example/detail.png"]
    plain = _worker(reader_factory())._read_body_images(_Page({sources[0]: _png(860, 4000)}), sources)
    with_broken = _worker(reader_factory(), broken)._read_body_images(_Page({sources[0]: _png(860, 4000)}), sources)

    assert plain == with_broken and plain[2] == 3


def test_nothing_is_shown_when_nothing_could_be_opened() -> None:
    told: list[dict[str, Any]] = []

    assert _worker(lambda png: "글", told.append)._read_body_images(_Page({}), ["https://img.example/gone.png"]) == ("", 0, 0)
    assert told == [], "읽은 조각이 없으면 거두는 알림도 없다"


# --- 런타임: 지금 손에 든 일에만, 따로 둔 이름으로 --------------------------------------

def _runtime() -> JarvisRuntime:
    runtime = object.__new__(JarvisRuntime)
    runtime.events = EventBus()
    return runtime


def test_the_piece_goes_out_under_its_own_event_for_the_job_in_hand() -> None:
    runtime = _runtime()
    runtime._job_in_hand = "job-7"

    runtime._note_image_read({"image": 1, "images": 1, "tile": 2, "tiles": 5, "picture": "data:image/jpeg;base64,AAAA"})

    records = runtime.events.snapshot() if hasattr(runtime.events, "snapshot") else list(runtime.events._events)
    names = [record.event for record in records]
    assert names == ["agent_looking"], "걸음 장부와 맡긴 쪽 진행 한 줄이 읽는 agent_progress 에는 그림을 싣지 않는다"
    assert records[0].payload["job_id"] == "job-7" and records[0].payload["tile"] == 2


def test_nothing_goes_out_when_no_job_is_in_hand() -> None:
    runtime = _runtime()

    runtime._note_image_read({"image": 1, "images": 1, "tile": 1, "tiles": 1, "picture": "x"})

    assert list(runtime.events._events) == []
