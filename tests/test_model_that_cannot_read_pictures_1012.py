"""지금 모델이 그림을 못 읽을 때 — 헛돌지 않고, 실패로 죽지 않고, 못 봤다고 말한다 (2026-10-12).

그림 부속이 없는 모델(또는 그림 읽기를 끈 설정)에게 그림을 주면 Ollama 가 거절한다(`image input is not supported` · HTTP 500).
지어내지는 않는다. 그런데 손자리는 그 전에 물어보지 않았다:
    페이지 그림 — 그림을 받아 자르고 화면에 「읽는 중」을 비춘 뒤 조각마다 거절을 받았다
    붙인 사진   — 거절이 그대로 판의 실패로 나갔다
    스캔 PDF   — 「글자를 못 찾았다」고 적혔다(못 읽은 것과 없는 것은 다른 말이다)
부르기 전에 모델의 능력을 묻고, 못 읽으면 도구가 그렇다고 말한다.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import ollama as ollama_mod
from alture_jarvis import runtime as runtime_mod
from alture_jarvis import ui_i18n
from alture_jarvis.api import create_app
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama import OllamaClient
from alture_jarvis.runtime import JarvisRuntime, unseen_pictures_note


def _png(width: int = 40, height: int = 30) -> bytes:
    image_module = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image_module.new("RGB", (width, height), (250, 250, 250)).save(buffer, format="PNG")
    return buffer.getvalue()


# ── 1. 모델에게 묻는다 ──────────────────────────────────────────────────────────

class _Show:
    """`/api/show` 만 답하는 가짜 서버. 모델 이름마다 능력을 돌려주고, 몇 번 물었는지 센다."""

    asked: list[str] = []
    answers: dict[str, Any] = {}

    def __init__(self, **_kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_Show":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def post(self, url: str, json: dict[str, Any]) -> Any:  # noqa: A002 — httpx 의 인자 이름
        name = str(json.get("model"))
        type(self).asked.append(name)
        answer = type(self).answers.get(name)
        if isinstance(answer, Exception):
            raise answer

        class _Reply:
            @staticmethod
            def raise_for_status() -> None:
                return None

            @staticmethod
            def json() -> dict[str, Any]:
                return dict(answer or {})

        return _Reply()


def _client(tmp_path: Path, model: str, monkeypatch: pytest.MonkeyPatch) -> OllamaClient:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False)
    config.model_roles = {"chat": model}
    _Show.asked, _Show.answers = [], {}
    monkeypatch.setattr(ollama_mod.httpx, "Client", _Show)
    return OllamaClient(config)


def test_the_model_is_asked_whether_it_reads_pictures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, "with-eyes:1", monkeypatch)
    _Show.answers = {"with-eyes:1": {"capabilities": ["completion", "tools", "vision"]},
                     "text-only:1": {"capabilities": ["completion", "tools"]}}
    assert client.reads_pictures() is True
    client.config.model_roles = {"chat": "text-only:1"}
    assert client.reads_pictures() is False


def test_the_answer_is_remembered_for_a_while_per_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, "text-only:1", monkeypatch)
    _Show.answers = {"text-only:1": {"capabilities": ["completion", "tools"]}}
    for _ in range(5):
        assert client.reads_pictures() is False
    assert _Show.asked == ["text-only:1"], "조각마다 서버에 다시 묻지 않는다"
    clock = [1_000_000.0]
    monkeypatch.setattr(ollama_mod.time, "monotonic", lambda: clock[0])
    client.__dict__.pop("_sight_memory", None)
    assert client.reads_pictures() is False
    clock[0] += OllamaClient._SIGHT_MEMORY_SEC + 1
    _Show.answers = {"text-only:1": {"capabilities": ["completion", "tools", "vision"]}}
    assert client.reads_pictures() is True, "같은 이름에 그림 부속을 붙이면 답이 바뀐다 — 오래 기억하지 않는다"


def test_not_knowing_is_not_the_same_as_cannot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, "unknown:1", monkeypatch)
    _Show.answers = {"unknown:1": RuntimeError("connection refused")}
    assert client.reads_pictures() is None
    _Show.answers = {"unknown:1": {}}
    assert client.reads_pictures() is None, "능력을 안 알리는 옛 서버 — 모른다"
    _Show.answers = {"unknown:1": {"capabilities": []}}
    assert client.reads_pictures() is None
    assert len(_Show.asked) == 3, "모르는 답은 기억하지 않는다 — 다음에 다시 묻는다"


# ── 2. 브라우저는 헛일을 안 한다 ────────────────────────────────────────────────

class _Page:
    url = "https://shop.example/item/1"

    class context:  # noqa: N801 — 페이지가 그림을 받는 길(가짜)
        class request:  # noqa: N801
            @staticmethod
            def get(url: str, timeout: int = 0) -> Any:
                raise AssertionError("그림을 못 읽는 모델인데 그림을 받으러 갔다")


def _worker(readable: Any, reader: Any = None, sink: Any = None) -> BrowserWorker:
    worker = object.__new__(BrowserWorker)
    worker.image_text_reader = reader or (lambda png: "글")
    if sink is not None:
        worker.image_read_sink = sink
    if readable is not ...:
        worker.pictures_readable = readable
    return worker


def test_page_pictures_are_not_fetched_for_a_model_that_cannot_read_them() -> None:
    called: list[bytes] = []
    told: list[dict[str, Any]] = []
    worker = _worker(lambda: False, called.append, told.append)
    assert worker._read_body_images(_Page(), ["https://img.example/detail.png"]) == ("", 0, 0)
    assert called == [] and told == [], "읽는 손도 부르지 않고 화면에 「읽는 중」도 비추지 않는다"


@pytest.mark.parametrize("readable", [lambda: True, lambda: None, ...])
def test_pictures_are_still_read_when_the_model_can_or_we_do_not_know(readable: Any) -> None:
    pytest.importorskip("PIL.Image")
    raw = _png(860, 400)

    class _Reply:
        ok = True

        @staticmethod
        def body() -> bytes:
            return raw

    class _ReadablePage:
        url = "https://shop.example/item/1"

        class context:  # noqa: N801
            class request:  # noqa: N801
                @staticmethod
                def get(url: str, timeout: int = 0) -> Any:
                    return _Reply()

    text, images, tiles = _worker(readable)._read_body_images(_ReadablePage(), ["https://img.example/detail.png"])
    assert text == "글" and images == 1 and tiles >= 1


def test_a_hook_that_breaks_counts_as_not_knowing() -> None:
    def broken() -> bool:
        raise RuntimeError("server went away")

    assert _worker(broken)._cannot_read_pictures() is False
    assert _worker(...)._cannot_read_pictures() is False
    assert _worker(lambda: False)._cannot_read_pictures() is True


def test_the_page_note_says_why_and_does_not_suggest_a_screenshot() -> None:
    blind = _worker(lambda: False)._image_body_note("짧은 글", 2, 0)
    assert "지금 모델은 그림을 읽지 못한다" in blind and "2장" in blind
    assert "browser_screenshot" not in blind, "찍어도 못 본다"
    assert "그림이라 확인 못 함" in blind
    tall = _worker(lambda: False)._image_body_note("긴 글 " * 4000, 0, 3)
    assert "지금 모델은 그림을 읽지 못한다" in tall and "3장" in tall
    assert _worker(lambda: False)._image_body_note("긴 글 " * 4000, 0, 0) == "", "그림이 없는 페이지에는 아무 말도 안 붙는다"
    seeing = _worker(lambda: True)._image_body_note("짧은 글", 2, 0)
    assert "browser_screenshot" in seeing and "읽지 못한다" not in seeing, "그림을 읽는 모델에게는 예전 글 그대로"


def test_a_built_page_is_not_rendered_apart_for_a_model_without_eyes() -> None:
    looked: list[bytes] = []
    worker = _worker(lambda: False)
    worker.page_eye = looked.append
    worker._playwright = object()

    class _Local:
        url = "http://127.0.0.1:5173/index.html"

    assert worker._look_at_local_page(_Local()) == ""
    assert looked == []


# ── 3. 사람에게는 못 봤다고 말한다 ──────────────────────────────────────────────

class _Blind:
    """그림을 못 읽는 모델. 그림이 든 부름이 오면 시험을 떨어뜨린다 — 실제 서버라면 HTTP 500 이다."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def reads_pictures(self, role: str = "chat") -> bool:
        return False

    def chat_message(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        assert not kwargs.get("images"), "그림을 못 읽는 모델에게 그림을 줬다"
        self.calls.append({"prompt": prompt, **kwargs})
        return {"content": "파일 내용으로 답했습니다.", "tool_calls": []}

    chat_message_stream = chat_message

    def chat(self, prompt: str, **kwargs: Any) -> str:
        return str(self.chat_message(prompt, **kwargs)["content"])


def _runtime(tmp_path: Path) -> JarvisRuntime:
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


def _picture(name: str = "shot.png") -> dict[str, Any]:
    return {"name": name, "mime_type": "image/png", "data_base64": base64.b64encode(_png()).decode("ascii")}


def test_the_note_is_plain_and_has_an_english_line() -> None:
    note = unseen_pictures_note(2)
    assert note.startswith("붙여 주신 그림 2장은 보지 못했습니다.")
    assert "그림을 읽는 모델을 고르면" in note
    before = ui_i18n.lang()
    try:
        ui_i18n.set_lang("en")
        for korean in (note, runtime_mod.PICTURES_UNREADABLE_RETRY, runtime_mod.PICTURES_UNREADABLE_CAMERA):
            english = ui_i18n.translate_text(korean)
            assert english != korean and not any("가" <= ch <= "힣" for ch in english), english
        assert "2 picture" in ui_i18n.translate_text(note)
    finally:
        ui_i18n.set_lang(before)


def test_a_picture_only_question_is_answered_without_asking_the_model(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _Blind()
    # 판이 끝난 뒤의 「기억해 둘 사실 뽑기」는 답과 상관없는 부름이다 — 여기서는 답을 만든 부름만 센다.
    runtime._learn_facts = lambda *args, **kwargs: None
    job = {"id": "job-blind-1", "payload": {"prompt": "이 화면에 뭐라고 적혀 있어?", "session_id": "s-blind-1",
                                              "attachments": [_picture()]}}
    result = runtime._chat_job_inner(job)
    answer = str(result.get("answer") or "")
    assert answer.startswith(unseen_pictures_note(1))
    assert runtime_mod.PICTURES_UNREADABLE_RETRY in answer
    assert runtime.ollama.calls == [], "안 본 그림에 대해 모델에게 묻지 않는다"


def test_the_pieces_that_read_pictures_step_aside(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _Blind()
    assert runtime._read_image_text(_png()) == ""
    assert runtime._look_at_page(_png()) == ""
    with pytest.raises(RuntimeError, match="그림을 읽지 못해 스캔본을 판독하지 못했습니다"):
        runtime._ocr_scanned_pdf(b"%PDF-1.4", 3)
    with pytest.raises(RuntimeError, match="model_cannot_read_pictures"):
        runtime._plan_screen_action(tmp_path / "missing.png", {"left": 0, "top": 0, "right": 10, "bottom": 10}, "버튼")
    assert runtime.ollama.calls == []
    assert runtime.browser.pictures_readable is not None
