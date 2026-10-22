"""모델 별명 표 · 판 하나만 다른 모델 · 디스코드 「@별명」 · `/모델` (2026-10-18). 진짜 Ollama · 디스코드 없이.

붙드는 것:
- 별명 규칙(공백 없는 1~12자, 한글 · 영문 · 숫자) · 처음 표 채우기(똑똑한 = 운영 대화 모델, 빠른 = 더 작은 가장 작은 대화 모델,
  글→숫자 모델은 빼고, 없으면 안 만듦) · 사람이 비운 표를 다시 채우지 않음
- `pin_model`: 대화 모델 자리만 그 판 동안 바뀌고, 따로 정한 역할 모델 · 찍어 부른 태그는 그대로, 나가면 흔적 없음
- `/v1/chat` 은 **별명**만 받아 본체가 태그를 푼다 — 모르는 별명은 400, 태그를 직접 넣을 칸은 없다
- 디스코드: 「@빠른 할 일」은 그 판만 · 표에 없는 `@무엇` 은 그대로 일로 · `/모델` 은 그 대화에 계속 · 「PC 와 같음」 ·
  안 올라간 모델이면 진행 메시지에 「올리는 중」
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from alture_jarvis import ui_i18n
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.messaging.base import PC_SAME, SessionMap, say
from alture_jarvis.messaging.bridge import TaskRunner
from alture_jarvis.messaging.credentials import MemoryCredentialStore
from alture_jarvis.messaging.discord_config import SETTINGS_FILE, DiscordSettings
from alture_jarvis.messaging.service import MESSAGES, DiscordService
from alture_jarvis.model_aliases import ALIASES_FILE, ModelAliasBook, clean_items, split_prefix
from alture_jarvis.ollama import OllamaClient
from test_messaging_discord_1017 import FakeAdapter, FakeBackend, _event, _no_sleep

CHAT = "swift-27b:q4"
SMALL = "qwen3.5:4b"
GB = 1_000_000_000
INSTALLED = [
    {"name": CHAT, "size": 17 * GB, "details": {"family": "qwen3"}},
    {"name": "qwen3.5:9b", "size": 6 * GB, "details": {"family": "qwen3"}},
    {"name": SMALL, "size": 3 * GB, "details": {"family": "qwen3"}},
    {"name": "nomic-embed-text:latest", "size": GB // 3, "details": {"family": "nomic-bert"}},
]


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                        control_token="test-token", camera_enabled=False, vision_enabled=False,
                        voice_enabled=False, tts_enabled=False,
                        model_roles={"chat": CHAT, "code": "coder:30b", "vision": "eyes:4b", "router": CHAT})


def _book(tmp_path: Path, installed: Any = INSTALLED, resident: list[str] | None = None) -> ModelAliasBook:
    return ModelAliasBook(_config(tmp_path), installed=lambda: installed, resident=lambda: resident or [],
                          lang=lambda: "ko")


# ── 별명 표 ────────────────────────────────────────────────────────────────────

def test_alias_rules() -> None:
    ok = clean_items([{"alias": "빠른", "tag": SMALL}, {"alias": "Fast2", "tag": CHAT, "note": " 줄\n바꿈 "}])
    assert [item["alias"] for item in ok] == ["빠른", "Fast2"] and ok[1]["note"] == "줄 바꿈"
    for bad in ([{"alias": "빠 른", "tag": SMALL}], [{"alias": "가" * 13, "tag": SMALL}], [{"alias": "fast!", "tag": SMALL}],
                [{"alias": "빠른", "tag": ""}], [{"alias": "빠른", "tag": "a b"}],
                [{"alias": "Fast", "tag": SMALL}, {"alias": "fast", "tag": CHAT}]):
        with pytest.raises(ValueError):
            clean_items(bad)


def test_the_first_table_is_seeded_from_installed_models_once(tmp_path: Path) -> None:
    book = _book(tmp_path)
    items = book.items()
    assert [(i["alias"], i["tag"]) for i in items] == [("똑똑한", CHAT), ("빠른", SMALL)]   # 글→숫자 모델은 후보가 아니다
    assert json.loads((tmp_path / "data" / ALIASES_FILE).read_text(encoding="utf-8"))["seeded"] is True
    book.replace([])
    assert book.items() == []   # 사람이 비운 표를 다시 채우지 않는다


def test_no_smaller_chat_model_means_no_fast_alias(tmp_path: Path) -> None:
    assert [i["alias"] for i in _book(tmp_path, installed=INSTALLED[:1]).items()] == ["똑똑한"]


def test_an_unreachable_ollama_does_not_mark_the_table_seeded(tmp_path: Path) -> None:
    assert [i["alias"] for i in _book(tmp_path, installed=None).items()] == ["똑똑한"]
    assert not (tmp_path / "data" / ALIASES_FILE).exists()


def test_the_view_says_which_alias_is_loaded(tmp_path: Path) -> None:
    view = _book(tmp_path, resident=[f"{CHAT}"]).view()
    assert view["pc_model"] == CHAT
    assert {row["alias"]: row["loaded"] for row in view["aliases"]} == {"똑똑한": True, "빠른": False}


def test_prefix_parsing() -> None:
    names = ["빠른", "똑똑한"]
    assert split_prefix("@빠른 오늘 서울 날씨", names) == ("빠른", "오늘 서울 날씨")
    assert split_prefix("  @빠른\n표로 정리해 줘", names) == ("빠른", "표로 정리해 줘")
    assert split_prefix("@빠른", names) == ("빠른", "")
    assert split_prefix("@누구 이거 해 줘", names) == ("", "@누구 이거 해 줘")      # 표에 없으면 건드리지 않는다
    assert split_prefix("메일 a@빠른 보내", names) == ("", "메일 a@빠른 보내")
    assert split_prefix("@빠른이 뭐야", names) == ("", "@빠른이 뭐야")


# ── 판 하나만 다른 모델 ─────────────────────────────────────────────────────────

def test_pin_model_swaps_only_the_chat_model_and_leaves_no_trace(tmp_path: Path) -> None:
    client = OllamaClient(_config(tmp_path))
    with client.pin_model(SMALL):
        assert client._selected_model(None, role="chat") == SMALL
        assert client._selected_model(None, role="router") == SMALL      # 대화 모델과 같은 태그를 쓰는 역할
        assert client._selected_model(None, role="code") == "coder:30b"  # 따로 정한 역할 모델은 그대로
        assert client._selected_model(None, role="vision") == "eyes:4b"
        assert client._selected_model("other:1b", role="chat") == "other:1b"   # 찍어 부른 태그는 그대로
    assert client._selected_model(None, role="chat") == CHAT and client.pinned_model == ""


def test_a_job_with_a_model_override_runs_pinned_and_the_next_job_does_not(tmp_path: Path) -> None:
    runtime = create_app(_config(tmp_path), start_services=False).state.jarvis
    seen: list[str] = []
    runtime._chat_job_inner = lambda job: seen.append(runtime.ollama.pinned_model) or {}
    runtime._chat_job({"payload": {"prompt": "x", "model_override": SMALL}})
    runtime._chat_job({"payload": {"prompt": "x"}})
    assert seen == [SMALL, ""]


def test_chat_takes_an_alias_not_a_tag(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    runtime.model_aliases = _book(tmp_path)
    headers = {"X-JARVIS-TOKEN": "test-token"}
    with TestClient(app) as client:
        refused = client.post("/v1/chat", headers=headers, json={"prompt": "날씨", "model_alias": "없는것"})
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "unknown_model_alias"
        taken = client.post("/v1/chat", headers=headers, json={"prompt": "날씨", "model_alias": "빠른"})
        assert taken.status_code == 200
        assert runtime.store.get_job(taken.json()["id"])["payload"]["model_override"] == SMALL
        # 태그를 직접 실어 보내도 칸이 없어 버려진다.
        sneaky = client.post("/v1/chat", headers=headers, json={"prompt": "날씨", "model_override": "evil:70b"})
        assert "model_override" not in runtime.store.get_job(sneaky.json()["id"])["payload"]


def test_alias_doors_and_the_discord_default_model(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    runtime.model_aliases = _book(tmp_path)
    runtime.discord = DiscordService(runtime.config, store=MemoryCredentialStore(), installed=lambda: True,
                                     aliases=runtime.model_aliases, lang=lambda: "ko")
    headers = {"X-JARVIS-TOKEN": "test-token"}
    with TestClient(app) as client:
        assert client.get("/v1/models/aliases").status_code == 401
        view = client.get("/v1/models/aliases", headers=headers).json()
        assert [row["alias"] for row in view["aliases"]] == ["똑똑한", "빠른"] and "loaded" in view["aliases"][0]
        bad = client.put("/v1/models/aliases", headers=headers, json={"aliases": [{"alias": "띄 어", "tag": SMALL}]})
        assert bad.status_code == 400 and bad.json()["detail"]["code"] == "invalid_alias"
        put = client.put("/v1/models/aliases", headers=headers,
                         json={"aliases": [{"alias": "빠른", "tag": SMALL, "note": "작은 것"}, {"alias": "big", "tag": CHAT}]})
        assert put.status_code == 200 and [row["alias"] for row in put.json()["aliases"]] == ["빠른", "big"]

        status = client.get("/v1/discord/status", headers=headers).json()
        assert status["default_model_alias"] == "" and [row["alias"] for row in status["aliases"]] == ["빠른", "big"]
        unknown = client.put("/v1/discord/settings", headers=headers, json={"default_model_alias": "없는것"}).json()
        assert unknown["ok"] is False and unknown["error"] == "unknown_model_alias"
        chosen = client.put("/v1/discord/settings", headers=headers, json={"default_model_alias": "BIG"}).json()
        assert chosen["ok"] is True and chosen["default_model_alias"] == "big"
        assert DiscordSettings.load(tmp_path / "data" / SETTINGS_FILE).default_model_alias == "big"
        cleared = client.put("/v1/discord/settings", headers=headers, json={"default_model_alias": ""}).json()
        assert cleared["default_model_alias"] == ""


# ── 디스코드 다리 ───────────────────────────────────────────────────────────────

class AliasBackend(FakeBackend):
    def __init__(self, *args: Any, loaded: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.loaded = loaded

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/models/aliases":
            self.requests.append(request)
            return httpx.Response(200, json={"pc_model": CHAT, "aliases": [
                {"alias": "똑똑한", "tag": CHAT, "note": "", "loaded": True},
                {"alias": "빠른", "tag": SMALL, "note": "", "loaded": self.loaded}]})
        return super().handler(request)

    def chat_bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == "/v1/chat"]


def _runner(adapter: FakeAdapter, fake: FakeBackend, tmp_path: Path, default: str = "") -> TaskRunner:
    return TaskRunner(adapter, fake.backend(), SessionMap(tmp_path / "state.json"), poll_sec=0, typing_every=0,
                      sleep=_no_sleep, default_model=lambda: default)


def test_an_at_alias_runs_that_task_only_and_says_the_model_is_loading(tmp_path: Path) -> None:
    fake, adapter = AliasBackend(["queued", "running", "completed"], loaded=False), FakeAdapter()
    runner = _runner(adapter, fake, tmp_path)
    asyncio.run(runner.run_task(_event("@빠른 오늘 서울 날씨 찾아 줘")))
    asyncio.run(runner.run_task(_event("내일 날씨도")))
    first, second = fake.chat_bodies()
    assert first["model_alias"] == "빠른" and first["prompt"] == "오늘 서울 날씨 찾아 줘"
    assert "model_alias" not in second   # 다음 판에 새지 않는다
    assert adapter.sent[0][1] == "⏳ " + say("model_loading", "ko", alias="빠른")


def test_an_unknown_at_word_is_left_in_the_task(tmp_path: Path) -> None:
    fake = AliasBackend(["completed"])
    asyncio.run(_runner(FakeAdapter(), fake, tmp_path).run_task(_event("@누구 에게 보낼 메일 초안 써 줘")))
    body = fake.chat_bodies()[0]
    assert body["prompt"] == "@누구 에게 보낼 메일 초안 써 줘" and "model_alias" not in body


def test_the_model_command_sticks_to_the_conversation_and_pc_same_beats_the_default(tmp_path: Path) -> None:
    fake, adapter = AliasBackend(["completed"], loaded=True), FakeAdapter()
    runner = _runner(adapter, fake, tmp_path, default="똑똑한")
    event = _event("날씨")
    assert "빠른" in asyncio.run(runner.model_command("빠른", event))
    asyncio.run(runner.run_task(_event("날씨")))
    assert asyncio.run(runner.model_command(PC_SAME, event)) == say("model_pc", "ko")
    asyncio.run(runner.run_task(_event("날씨")))
    assert "없는것" in asyncio.run(runner.model_command("없는것", event))
    bodies = fake.chat_bodies()
    assert bodies[0]["model_alias"] == "빠른" and "model_alias" not in bodies[1]
    assert not any("올리는 중" in content for _c, content, _r in adapter.sent)   # 이미 올라가 있으면 알리지 않는다


def test_the_discord_default_model_and_a_stale_alias(tmp_path: Path) -> None:
    fake = AliasBackend(["completed"], loaded=True)
    asyncio.run(_runner(FakeAdapter(), fake, tmp_path, default="똑똑한").run_task(_event("날씨")))
    asyncio.run(_runner(FakeAdapter(), fake, tmp_path / "b", default="지운별명").run_task(_event("날씨")))
    first, second = fake.chat_bodies()
    assert first["model_alias"] == "똑똑한" and "model_alias" not in second   # 표에서 지운 별명은 PC 모델로


def test_a_thread_follows_the_model_chosen_in_its_channel(tmp_path: Path) -> None:
    fake = AliasBackend(["completed"], loaded=True)
    runner = _runner(FakeAdapter(), fake, tmp_path)
    asyncio.run(runner.model_command("빠른", _event("x", session_key="700", chat_id="700")))
    asyncio.run(runner.run_task(_event("날씨", session_key="900", chat_id="900", origin_chat_id="700", chat_type="thread")))
    assert fake.chat_bodies()[0]["model_alias"] == "빠른"


def test_model_choices_start_with_same_as_pc_and_filter() -> None:
    runner = TaskRunner(FakeAdapter(), None, SessionMap(None))   # type: ignore[arg-type]
    rows = [{"alias": "똑똑한", "tag": CHAT, "note": ""}, {"alias": "빠른", "tag": SMALL, "note": "작은 것"}]
    choices = runner.model_choices("", rows)
    assert choices[0] == (say("model_pc_choice", "ko"), PC_SAME) and len(choices) == 3
    assert runner.model_choices("빠", rows) == [(f"빠른 · {SMALL} — 작은 것", "빠른")]


def test_the_model_slash_command_is_registered_with_autocomplete() -> None:
    pytest.importorskip("discord")
    from alture_jarvis.messaging.base import AccessPolicy
    from alture_jarvis.messaging.discord_adapter import MODEL_COMMANDS, DiscordAdapter

    async def build() -> dict[str, Any]:
        adapter = DiscordAdapter("x" * 30, policy=AccessPolicy(["1"]), sessions=SessionMap(None))
        client = adapter._build_client()
        try:
            tree = client._connection._command_tree
            return {c.name: c for c in tree.get_commands()}
        finally:
            await client.close()

    commands = asyncio.run(build())
    for name in MODEL_COMMANDS:
        assert [p.name for p in commands[name].parameters] == ["name"]
        assert commands[name].parameters[0].autocomplete is not None


# ── 영어 화면 ──────────────────────────────────────────────────────────────────

def test_every_discord_screen_sentence_has_an_english_translation(tmp_path: Path) -> None:
    ui_i18n.configure(tmp_path / "lang.json")
    ui_i18n.set_lang("en")
    try:
        texts = [*MESSAGES.values(), "PC 에서 쓰는 대화 모델", "깔린 것 중 가장 작은 모델 — 빠르지만 덜 꼼꼼합니다"]
        missing = [text for text in texts if any("가" <= ch <= "힣" for ch in ui_i18n.translate_text(text.format(3)))]
    finally:
        ui_i18n.set_lang("ko")
    assert missing == []


def test_fast_skips_projector_files_and_tiny_models() -> None:
    """2026-10-18 첫 운영: 그림 부속(mmproj)이 「빠른」이 됐다. 부속을 빼고, 7B 이상에서 가장 작은 것을 고른다."""
    from alture_jarvis.model_aliases import _smallest_chat_model

    def m(name: str, gib: float, params: str, family: str = "qwen35") -> dict:
        return {"name": name, "size": int(gib * 2**30), "details": {"parameter_size": params, "family": family}}

    installed = [
        m("bge-m3:latest", 1.1, "566.70M", "bert"),
        m("hf.co/x/Swift-GGUF:mmproj-Swift-F16.gguf", 1.7, "27.3B"),
        m("qwen3.5:4b", 3.2, "4.7B"),
        m("sonjari-text-qwen3.5-9b-q3:latest", 4.4, "9.0B"),
        m("qwen3.5:9b", 6.1, "9.7B"),
        m("swift-27b:iq3s", 12.2, "27.3B"),
    ]
    assert _smallest_chat_model(installed, "swift-27b:iq3s") == "sonjari-text-qwen3.5-9b-q3:latest"
    only_small = [m("qwen3.5:4b", 3.2, "4.7B"), m("swift-27b:iq3s", 12.2, "27.3B")]
    assert _smallest_chat_model(only_small, "swift-27b:iq3s") == "qwen3.5:4b"
