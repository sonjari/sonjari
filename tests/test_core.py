from __future__ import annotations

import time
from pathlib import Path
import types

from alture_jarvis.events import EventBus
from alture_jarvis.config import JarvisConfig
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import JobStatus, RiskLevel
from alture_jarvis.ollama import OllamaClient
from alture_jarvis.profile import OperatorProfile
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec
from alture_jarvis.vision import PresenceTracker, VisionService
from alture_jarvis.voice import HotkeyBridge


def test_event_bus_sequence_and_cursor() -> None:
    bus = EventBus()
    first = bus.publish("one", {"value": 1})
    second = bus.publish("two")
    assert first.seq == 1
    assert [event.event for event in bus.get_since(first.seq)] == ["two"]
    assert second.seq == bus.sequence


def test_job_store_claim_complete_and_recover(tmp_path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    created = store.create_job("chat", "hello", {"prompt": "hi"})
    claimed = store.claim_next()
    assert claimed and claimed["id"] == created["id"]
    assert claimed["status"] == "running"
    assert store.recover_interrupted() == 1
    assert store.get_job(created["id"])["status"] == "queued"


def test_listing_approvals_reconciles_expired_pending_rows(tmp_path) -> None:
    """아무도 버튼을 누르지 않아도 시간은 pending을 expired로 바꾼다."""
    store = JobStore(tmp_path / "jarvis.db")
    store.create_approval(
        nonce="old-nonce",
        job_id="",
        tool_name="site_run",
        arguments={"site": "demo"},
        expires_at=time.time() - 1,
    )
    assert store.get_approval("old-nonce")["status"] == "pending"

    assert store.list_approvals(status="pending") == []
    expired = store.list_approvals(status="expired")

    assert [row["nonce"] for row in expired] == ["old-nonce"]
    assert store.get_approval("old-nonce")["status"] == "expired"


def test_expired_approval_closes_its_waiting_job(tmp_path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    job = store.create_job("chat", "submit", {"prompt": "submit"})
    store.set_status(job["id"], JobStatus.WAITING_APPROVAL)
    store.create_approval(
        nonce="expired-job-nonce",
        job_id=job["id"],
        tool_name="browser_click_confirmed",
        arguments={"ref": "j14"},
        expires_at=time.time() - 1,
    )

    assert store.list_approvals(status="pending") == []
    closed = store.get_job(job["id"])

    assert closed["status"] == "cancelled"
    assert closed["error"] == "approval_expired"


def test_gateway_requires_non_voice_approval_for_l2(tmp_path) -> None:
    store = JobStore(tmp_path / "jarvis.db")
    gateway = ToolGateway(store, EventBus())
    calls: list[str] = []
    gateway.register(
        ToolSpec(
            "dangerous",
            "test",
            RiskLevel.L2,
            lambda args: calls.append(args["value"]) or {"done": True},
        )
    )
    first = gateway.execute("dangerous", {"value": "x"})
    assert first.status == "approval_required"
    assert calls == []
    decision = gateway.decide(first.approval_nonce, True)
    assert decision and decision["status"] == "approved"
    second = gateway.execute("dangerous", {"value": "x"})
    assert second.ok is True
    assert calls == ["x"]
    assert store.get_approval(first.approval_nonce)["status"] == "consumed"


def test_presence_tracker_debounces_entry_and_exit() -> None:
    tracker = PresenceTracker(enter_hits=3, enter_window=5, exit_after_sec=2.0)
    assert tracker.update(True, 1.0) is None
    assert tracker.update(False, 1.1) is None
    assert tracker.update(True, 1.2) is None
    assert tracker.update(True, 1.3) == "entered"
    assert tracker.present is True
    assert tracker.update(False, 2.9) is None
    assert tracker.update(False, 3.31) == "left"
    assert tracker.present is False


def test_latest_jpeg_is_encoded_only_when_requested(monkeypatch) -> None:
    calls: list[tuple[str, object, list[int]]] = []

    class Encoded:
        def tobytes(self) -> bytes:
            return b"\xff\xd8on-demand\xff\xd9"

    def imencode(extension: str, frame: object, options: list[int]):
        calls.append((extension, frame, options))
        return True, Encoded()

    fake_cv2 = types.SimpleNamespace(IMWRITE_JPEG_QUALITY=1, imencode=imencode)
    monkeypatch.setitem(__import__("sys").modules, "cv2", fake_cv2)
    config = type("Config", (), {})()
    service = VisionService(config, EventBus())
    frame = object()
    service._latest_frame = frame

    assert calls == []

    encoded = service.latest_jpeg()

    assert encoded.startswith(b"\xff\xd8")
    assert calls == [(".jpg", frame, [1, 85])]


class _FakeCapture:
    def __init__(self, opened: bool = True) -> None:
        self.opened = opened
        self.properties: dict[int, float] = {}

    def set(self, key: int, value: float) -> None:
        self.properties[key] = value

    def isOpened(self) -> bool:  # noqa: N802 - mirrors the cv2 API
        return self.opened


def _fake_cv2(record: list[tuple[object, int]]):
    def video_capture(source, backend):
        record.append((source, backend))
        return _FakeCapture()

    return types.SimpleNamespace(
        CAP_MSMF=1400,
        CAP_ANY=0,
        CAP_FFMPEG=1900,
        CAP_PROP_BUFFERSIZE=38,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        CAP_PROP_FPS=5,
        VideoCapture=video_capture,
    )


def test_capture_source_defaults_to_the_local_usb_camera() -> None:
    config = JarvisConfig(camera_index=2, camera_backend="msmf")
    service = VisionService(config, EventBus())
    opened: list[tuple[object, int]] = []

    capture = service._open_capture(_fake_cv2(opened))

    assert opened == [(2, 1400)]
    # Frame geometry is ours to demand from a USB device.
    assert capture.properties[3] == config.camera_width
    assert service._source_label() == {"source": "usb", "camera_index": 2}


def test_capture_source_switches_to_a_network_stream_when_a_url_is_set() -> None:
    # This is what makes the wireless Pocket 3 (or any RTSP camera) work
    # without touching the YOLO pipeline downstream.
    url = "rtmp://127.0.0.1:1935/live/pocket3"
    config = JarvisConfig(camera_index=2, camera_stream_url=url)
    service = VisionService(config, EventBus())
    opened: list[tuple[object, int]] = []

    capture = service._open_capture(_fake_cv2(opened))

    assert opened == [(url, 1900)]
    # Only the 1-frame buffer: the sender owns size and rate on a stream, and
    # asking for a geometry it is not sending makes FFmpeg fail the open.
    assert capture.properties == {38: 1}
    assert service._source_label() == {"source": "stream", "stream_url": url}


def test_stream_open_carries_a_protocol_correct_timeout() -> None:
    # Without this the capture thread blocks forever inside FFmpeg whenever the
    # publisher is away, and vision never recovers by itself.
    rtmp = VisionService(
        JarvisConfig(camera_stream_url="rtmp://127.0.0.1:1935/live/pocket3"),
        EventBus(),
    )
    assert rtmp._stream_ffmpeg_options("rtmp://127.0.0.1:1935/live/pocket3") == "rw_timeout;12000000"

    # RTSP needs the demuxer option instead, and TCP so frames survive Wi-Fi loss.
    rtsp = VisionService(
        JarvisConfig(camera_stream_url="rtsp://cam.local/stream", camera_stream_read_timeout_sec=5.0),
        EventBus(),
    )
    assert rtsp._stream_ffmpeg_options("rtsp://cam.local/stream") == "rtsp_transport;tcp|timeout;5000000"

    pinned = VisionService(
        JarvisConfig(camera_stream_url="rtsp://cam.local/stream", camera_stream_ffmpeg_options="custom;1"),
        EventBus(),
    )
    assert pinned._stream_ffmpeg_options("rtsp://cam.local/stream") == "custom;1"


def test_control_token_bom_is_normalized(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    token_path = data_dir / "control.token"
    token_path.write_bytes(b"\xef\xbb\xbftest-token")
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=data_dir,
        output_dir=tmp_path / "outputs",
    )

    config.prepare()

    assert config.control_token == "test-token"
    assert token_path.read_bytes() == b"test-token"


def test_control_token_file_follows_env_token(tmp_path) -> None:
    """`.env` 로 토큰을 준 경우에도 파일이 그 값을 따라가야 한다.

    Tauri 껍데기는 `.env` 를 못 읽고 이 파일만 읽는다. 갈라지면 워크스페이스의 모든
    쓰기가 401 로 막히는데, 화면에는 그냥 실패로만 보인다.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    token_path = data_dir / "control.token"
    token_path.write_text("stale-token", encoding="utf-8")
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=data_dir,
        output_dir=tmp_path / "outputs",
        control_token="env-token",
    )

    config.prepare()

    assert config.control_token == "env-token"
    assert token_path.read_text(encoding="utf-8") == "env-token"


def test_ollama_warmup_uses_empty_generate_and_keep_alive(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeResponse:
        # 진짜 httpx.Response 처럼 상태 코드를 갖는다. `_post_chat` 이 404 를
        # 갈라내려고 이 값을 읽는다 — 가짜가 진짜보다 얇으면 프로덕션이
        # 멀쩡한데도 여기서만 깨진다.
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"load_duration": 2_500_000, "total_duration": 3_000_000}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url: str, json: dict) -> FakeResponse:
            calls.append((url, json))
            return FakeResponse()

    monkeypatch.setattr("alture_jarvis.ollama.httpx.Client", FakeClient)
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        ollama_keep_alive="24h",
    )

    result = OllamaClient(config).warmup()

    assert result["ok"] is True
    assert result["load_ms"] == 2.5
    assert calls == [
        (
            "http://127.0.0.1:11434/api/generate",
            {
                    "model": "gemma4:26b-a4b-it-qat",
                "prompt": "Sonjari warmup.",
                "stream": False,
                "keep_alive": "24h",
                # min_p: 0.01 은 2026-09-23 역할 공통 기본값(간체 섞임 완화) — 예열 호출에도 실린다.
                "options": {"temperature": 0.0, "num_ctx": 131072, "min_p": 0.01, "num_predict": 1},
            },
        )
    ]


def test_ollama_adopts_compatible_resident_context_without_reload(monkeypatch, tmp_path) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        ollama_num_ctx=24576,
        ollama_min_num_ctx=16384,
    )
    client = OllamaClient(config)
    monkeypatch.setattr(client, "_resident_context", lambda _model: 16384)

    assert client._options(0.1, model=config.ollama_model)["num_ctx"] == 16384
    assert client._options(
        0.1, model=config.ollama_model, force_preferred=True
    )["num_ctx"] == 24576


def test_a_resident_runner_below_32k_is_not_adopted_by_default(monkeypatch, tmp_path) -> None:
    """작은 모델은 16K 에서 일을 못 한다(8K 6/12 · 16K 9/12) — 남이 16K 로 올린 러너를 주워 쓰지 않는다."""
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          ollama_num_ctx=32768)
    client = OllamaClient(config)
    monkeypatch.setattr(client, "_resident_context", lambda _model: 16384)
    assert client._options(0.1, model=config.ollama_model)["num_ctx"] == 32768
    # 값이 사는 자리 둘 다(사고 Q) — dataclass 기본값과 환경변수 로더.
    assert config.ollama_min_num_ctx == 32768
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "config.py").read_text(encoding="utf-8")
    assert '_int("JARVIS_OLLAMA_MIN_NUM_CTX", 32768)' in source


def test_ollama_call_can_select_the_code_role_without_mutating_config(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []

    class FakeResponse:
        # 진짜 httpx.Response 처럼 상태 코드를 갖는다. `_post_chat` 이 404 를
        # 갈라내려고 이 값을 읽는다 — 가짜가 진짜보다 얇으면 프로덕션이
        # 멀쩡한데도 여기서만 깨진다.
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"role": "assistant", "content": "ok"}}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, _url: str, json: dict) -> FakeResponse:
            calls.append(json)
            return FakeResponse()

    monkeypatch.setattr("alture_jarvis.ollama.httpx.Client", FakeClient)
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        model_roles={
            "chat": "chat-model:latest",
            "code": "coder-model:latest",
            "vision": "vision-model:latest",
        },
        model_num_ctx={"code": 102400},
        ollama_adopt_resident_context=False,
    )

    message = OllamaClient(config).chat_messages(
        [{"role": "user", "content": "code"}], role="code"
    )

    assert message["content"] == "ok"
    assert calls[0]["model"] == "coder-model:latest"
    assert calls[0]["options"]["num_ctx"] == 102400
    assert config.ollama_model == "chat-model:latest"


def test_model_roles_have_one_env_loader_and_legacy_fallback(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_OLLAMA_MODEL", "legacy-chat:latest")
    monkeypatch.setenv("JARVIS_OLLAMA_CHAT_MODEL", "chat-role:latest")
    monkeypatch.setenv("JARVIS_OLLAMA_CODE_MODEL", "coder-role:latest")
    monkeypatch.delenv("JARVIS_OLLAMA_VISION_MODEL", raising=False)

    config = JarvisConfig.from_env()

    assert config.model_roles == {
        "chat": "chat-role:latest",
        "code": "coder-role:latest",
        "vision": "legacy-chat:latest",
    }

    # ★ 2026-09-15 PC 의존성 정리: 코드 모델을 따로 안 주면 **대화 모델**을 쓰고 컨텍스트도 같다.
    #   예전 기본값(qwen3.8 27B · 102400)은 3090 전용이라 8GB 사용자의 Code 탭이 없는 모델을 불렀다.
    monkeypatch.delenv("JARVIS_OLLAMA_CODE_MODEL")
    monkeypatch.delenv("JARVIS_OLLAMA_CODE_NUM_CTX", raising=False)
    fresh = JarvisConfig.from_env()
    assert fresh.model_for("code") == "chat-role:latest"
    assert fresh.num_ctx_for("code") == fresh.num_ctx_for("chat")


def test_qwen_code_profiles_pin_official_sampling_without_changing_chat() -> None:
    config = JarvisConfig(ollama_adopt_resident_context=False)
    client = OllamaClient(config)
    model = config.model_for("code")

    balanced = client._options(
        0.1, model=model, role="code", inference_profile="balanced"
    )
    fast = client._options(
        0.1, model=model, role="code", inference_profile="fast"
    )
    chat = client._options(0.2, model=config.model_for("chat"), role="chat")

    assert balanced["temperature"] == 1.0
    assert balanced["top_p"] == 0.95
    assert balanced["top_k"] == 20
    # ★ 2026-09-23: 공식 권장(0.0)을 여기만 안 따른다 — 간체 섞임 완화, 아래
    #   `test_min_p_nudges_the_official_tail_without_changing_the_rest` 참고.
    assert balanced["min_p"] == 0.01
    assert balanced["repeat_penalty"] == 1.0
    assert fast["temperature"] == 0.7
    assert fast["top_p"] == 0.8
    assert "top_p" not in chat
    assert config.inference_profile_for("code") == "balanced"


def test_min_p_nudges_the_official_tail_without_changing_the_rest() -> None:
    """★ 2026-09-23 (사장님 실사용 보고 + 조사) — 간체가 드물게 섞이는 버그.

    Qwen 공식 권장 샘플링은 `min_p=0.0`(확률 꼬리를 안 자름)인데, 커뮤니티 보고로는
    `min_p=0.01`이 그 꼬리에서 튀는 낮은 확률의 한자 토큰을 줄인다(정량 실측은 없음 —
    완화 조치이지 증명된 하한이 아니다). 역할 공통 기본값으로 깔고, code 역할의 나머지
    공식 권장값(top_p·top_k·temperature·repeat_penalty·presence_penalty)은 그대로 둔다 —
    presence_penalty 를 올리는 건 Qwen3 공식 문서가 직접 "언어 섞임을 늘릴 수 있다"고
    적어 둔 값이라 건드리지 않는다.
    """
    config = JarvisConfig(ollama_adopt_resident_context=False)
    client = OllamaClient(config)

    chat = client._options(0.2, model=config.model_for("chat"), role="chat")
    code_balanced = client._options(
        0.1, model=config.model_for("code"), role="code", inference_profile="balanced"
    )
    code_fast = client._options(
        0.1, model=config.model_for("code"), role="code", inference_profile="fast"
    )

    assert chat["min_p"] == 0.01
    assert code_balanced["min_p"] == 0.01
    assert code_fast["min_p"] == 0.01
    # presence_penalty 는 안 올렸다 — 그대로 0.0.
    assert code_balanced["presence_penalty"] == 0.0


def test_ollama_treats_an_omitted_latest_tag_as_the_same_model() -> None:
    """게임 모드는 태그를 생략하고 Ollama 상태 API는 :latest를 붙인다."""
    assert OllamaClient._same_model("plopfit-gemma4-qat", "plopfit-gemma4-qat:latest")
    assert OllamaClient._same_model("PLOPFIT-GEMMA4-QAT:latest", "plopfit-gemma4-qat")
    assert not OllamaClient._same_model("plopfit-gemma4", "plopfit-gemma4-qat")


def test_operator_profile_loads_bounded_utf8_markdown(tmp_path) -> None:
    path = tmp_path / "JARVIS_PROFILE.md"
    path.write_text("# 프로필\n\n박가람 대표와 RoboMetaFit " + ("맥락 " * 300), encoding="utf-8")

    profile = OperatorProfile(path, max_chars=500)

    assert profile.content.startswith("# 프로필")
    assert "RoboMetaFit" in profile.content
    assert len(profile.content) == 500
    assert profile.status()["loaded"] is True


def test_hotkey_fallback_fires_once_on_release_and_tracks_state(monkeypatch) -> None:
    registered: dict[str, object] = {}

    def add_hotkey(hotkey, callback, **kwargs):
        registered.update(hotkey=hotkey, callback=callback, **kwargs)
        return "handle"

    fake_keyboard = types.SimpleNamespace(
        add_hotkey=add_hotkey,
        remove_hotkey=lambda handle: registered.update(removed=handle),
    )
    monkeypatch.setitem(__import__("sys").modules, "keyboard", fake_keyboard)
    monkeypatch.setattr(HotkeyBridge, "_native_supported", staticmethod(lambda: False))
    config = JarvisConfig(
        hotkey="ctrl+shift+space",
        hotkey_suppress=True,
        hotkey_trigger_on_release=True,
    )
    # The bridge no longer tracks start-vs-stop itself; it forwards every press
    # to the runtime toggle, which decides from the state machine.
    actions: list[str] = []

    def toggle() -> dict[str, str]:
        action = "stopped" if actions[-1:] == ["started"] else "started"
        actions.append(action)
        return {"action": action}

    bridge = HotkeyBridge(config, toggle)

    started = bridge.start()
    registered["callback"]()
    registered["callback"]()

    assert started["ok"] is True
    assert registered["suppress"] is True
    assert registered["trigger_on_release"] is True
    assert actions == ["started", "stopped"]
    assert bridge.status()["last_action"] == "stopped"
    assert bridge.status()["trigger_count"] == 2


def test_windows_hotkey_parser_reserves_f9_without_repeat() -> None:
    modifiers, virtual_key = HotkeyBridge._parse_windows_hotkey("f9")

    assert modifiers & HotkeyBridge._MOD_NOREPEAT
    assert not modifiers & HotkeyBridge._MOD_CONTROL
    assert not modifiers & HotkeyBridge._MOD_ALT
    assert virtual_key == 0x78


def _pin_config(tmp_path):
    # 코더를 따로 둔 설치(운영 PC 처럼 환경변수로 준다) — 공개 기본값은 코드=대화 모델이라 핀 시험이 무의미하다.
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        model_roles={"chat": "gemma4:26b-a4b-it-qat", "code": "qwen3.8:27b-mtp-q4_K_M",
                     "vision": "gemma4:26b-a4b-it-qat"},
        model_num_ctx={"code": 102400},
    )


def test_code_pin_keeps_every_call_on_the_coder(tmp_path) -> None:
    """Code 잡이 도는 동안 채팅 역할 호출이 코더를 3090에서 쫓아냈다."""
    config = _pin_config(tmp_path)
    client = OllamaClient(config)
    coder = config.model_for("code")
    chatter = config.model_for("chat")
    assert coder != chatter

    assert client._selected_model(role="chat") == chatter
    with client.pin_role("code"):
        assert client._selected_model(role="chat") == coder
        # num_ctx 도 같이 따라와야 한다. 태그가 같아도 창이 갈리면 Ollama가
        # 러너를 새로 띄워 결국 같은 축출이 일어난다.
        assert client._options(
            0.1, model=coder, role="chat", force_preferred=True
        )["num_ctx"] == config.num_ctx_for("code")
    assert client._selected_model(role="chat") == chatter


def test_code_pin_never_steals_vision_or_an_explicit_model(tmp_path) -> None:
    config = _pin_config(tmp_path)
    client = OllamaClient(config)
    with client.pin_role("code"):
        # 이미지는 멀티모달 태그로 가야 한다.
        assert client._selected_model(role="vision") == config.model_for("vision")
        # 호출부가 태그를 명시했으면 그 호출의 창을 뺏지 않는다.
        assert client._selected_model("some-other:tag", role="chat") == "some-other:tag"
        assert client._options(
            0.1, model="some-other:tag", role="chat", force_preferred=True
        )["num_ctx"] == config.num_ctx_for("chat")


def test_code_pin_is_released_even_when_the_job_raises(tmp_path) -> None:
    config = _pin_config(tmp_path)
    client = OllamaClient(config)
    try:
        with client.pin_role("code"):
            with client.pin_role("code"):
                pass
            assert client.pinned_role == "code"
            raise RuntimeError("job blew up")
    except RuntimeError:
        pass
    assert client.pinned_role == ""
    assert client._selected_model(role="chat") == config.model_for("chat")


def test_code_mode_job_runs_inside_the_coder_pin(tmp_path) -> None:
    """배선 확인 — 핀을 만들어 놓고 잡에서 안 걸면 아무 일도 안 일어난다."""
    from alture_jarvis.runtime import JarvisRuntime

    runtime = JarvisRuntime.__new__(JarvisRuntime)
    runtime.ollama = OllamaClient(_pin_config(tmp_path))
    observed: list[str] = []

    def fake_inner(job):
        observed.append(runtime.ollama.pinned_role)
        return {"answer": "ok"}

    runtime._chat_job_inner = fake_inner

    runtime._chat_job({"payload": {"workspace_mode": "code"}})
    runtime._chat_job({"payload": {"workspace_mode": "cowork"}})
    runtime._chat_job({"payload": {}})

    assert observed == ["code", "", ""]
    assert runtime.ollama.pinned_role == ""


def test_code_calls_get_a_much_longer_timeout_than_chat(tmp_path) -> None:
    """★ 코드 판 하나가 `timed out` 으로 통째로 죽었다 (2026-08-28).

    실측: 생성 5,520 토큰이 145초, 3,248 토큰이 89초. 여기에 프리필이 붙으면
    대화용 180초를 넘긴다. 그때 모델은 **이미 고쳐 놓은 상태**였다 — 목표
    테스트 19개가 통과하고 있었는데 잡만 죽었다.
    """
    config = _pin_config(tmp_path)

    assert config.timeout_for("chat") == float(config.ollama_timeout_sec)
    assert config.timeout_for("code") >= 600, "코드 호출이 대화 타임아웃에 걸린다"
    assert config.timeout_for("code") > config.timeout_for("chat")


def test_the_code_pin_also_lengthens_the_timeout(tmp_path) -> None:
    """핀으로 코드 역할에 묶였으면 타임아웃도 코드 것이어야 한다.

    둘이 갈리면 「모델은 코더인데 시계는 대화용」이 되어 긴 생성에서 죽는다.
    """
    config = _pin_config(tmp_path)
    client = OllamaClient(config)

    assert config.timeout_for(client._effective_role("chat")) == config.timeout_for("chat")
    with client.pin_role("code"):
        effective = client._effective_role("chat")
        assert effective == "code"
        assert config.timeout_for(effective) >= 600


def test_only_recent_work_is_picked_up_after_a_restart(tmp_path) -> None:
    """★ 2026-09-16: 다시 켤 때마다 몇 시간 전 일까지 되살아나 크롬이 혼자 열렸다(사용자님 목격·실측 오염 3회)."""
    store = JobStore(tmp_path / "jarvis.db")
    fresh = store.create_job("chat", "방금", {"prompt": "방금 시킨 일"})
    old = store.create_job("chat", "옛날", {"prompt": "몇 시간 전 일"})
    store.claim_next()
    store.claim_next()
    with store._connect() as conn:  # noqa: SLF001 — 시간을 되돌리는 것은 시험만 한다
        conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (time.time() - 4 * 3600, old["id"]))

    assert store.recover_interrupted() == 1

    assert store.get_job(fresh["id"])["status"] == "queued"
    stale = store.get_job(old["id"])
    assert stale["status"] == "cancelled" and stale["error"] == "stale_after_restart"
