from __future__ import annotations

import json
import time

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.media import MediaSessionController
from alture_jarvis.memory import ConversationMemory, normalize_session_id
from alture_jarvis.runtime import JarvisRuntime


def test_conversation_memory_bounds_context_and_prepares_compaction(tmp_path) -> None:
    memory = ConversationMemory(
        tmp_path / "jarvis.db",
        recent_messages=4,
        compact_batch=2,
        max_chars=2000,
    )
    for index in range(8):
        memory.add_message("office-main", "user" if index % 2 == 0 else "assistant", f"message-{index}")

    context = memory.context_messages("office-main")
    assert [item["content"] for item in context] == [
        "message-4",
        "message-5",
        "message-6",
        "message-7",
    ]
    candidate = memory.compaction_candidate("office-main")
    assert candidate is not None
    assert [item["content"] for item in candidate["messages"]] == [
        "message-0",
        "message-1",
        "message-2",
        "message-3",
    ]
    memory.save_summary("office-main", "결정 사항 요약", candidate["through_message_id"])
    compacted = memory.context_messages("office-main")
    assert compacted[0]["role"] == "system"
    assert "결정 사항 요약" in compacted[0]["content"]


def test_history_and_session_list_are_independent_from_context_compaction(tmp_path) -> None:
    memory = ConversationMemory(tmp_path / "jarvis.db", recent_messages=2, compact_batch=2)
    memory.add_exchange("session-a", "프로젝트 계획", "계획 답변")
    memory.add_exchange("session-a", "후속 질문", "후속 답변")
    memory.save_summary("session-a", "프로젝트 누적 요약", 2)

    assert len(memory.context_messages("session-a")) == 3
    assert len(memory.history("session-a")) == 4
    session = memory.list_sessions()[0]
    assert session["title"] == "프로젝트 계획"
    assert session["message_count"] == 4
    assert session["has_summary"] is True


def test_retrieval_recalls_relevant_older_turn_across_sessions(tmp_path) -> None:
    memory = ConversationMemory(tmp_path / "jarvis.db", recent_messages=2)
    memory.add_exchange(
        "project-old",
        "로보메타핏 문제은행 골든셋 기준은 무엇이었지?",
        "수학 문항의 정답 일치와 풀이 근거 보존을 핵심 기준으로 정했습니다.",
    )
    memory.add_exchange("noise", "오늘 점심 뭐 먹지?", "가볍게 국수를 추천합니다.")

    recalled = memory.retrieve("문제은행 골든셋 기준 다시 알려줘", "new-chat")

    assert recalled
    assert recalled[0]["session_id"] == "project-old"
    assert "골든셋" in recalled[0]["content"]
    context = memory.context_messages("new-chat", query="문제은행 골든셋 기준 다시 알려줘")
    assert context[0]["role"] == "system"
    assert "로컬 대화 기록에서 검색한 과거 기억" in context[0]["content"]
    assert "골든셋" in context[0]["content"]


def test_retrieval_does_not_duplicate_current_recent_messages(tmp_path) -> None:
    memory = ConversationMemory(tmp_path / "jarvis.db", recent_messages=4)
    memory.add_exchange("same", "브라우저 승인 정책", "제출 직전에 승인합니다.")

    context = memory.context_messages("same", query="브라우저 승인 정책")

    assert sum("브라우저 승인 정책" in item["content"] for item in context) == 1


def test_long_attachment_selects_bounded_relevant_sections() -> None:
    text = ("도입 설명 " * 500) + ("핵심매출 성장률 42퍼센트 " * 400) + ("부록 " * 1000)
    selected, was_selected = JarvisRuntime._select_attachment_text(
        text, "핵심매출 성장률을 찾아줘", 9000
    )

    assert was_selected is True
    assert len(selected) <= 9000
    assert "핵심매출" in selected


def test_visual_memory_stores_text_metadata_not_image(tmp_path) -> None:
    memory = ConversationMemory(tmp_path / "jarvis.db")
    memory.add_visual(
        "office-main",
        focus="책상 위 물건",
        summary="검은색 리모컨이 보인다.",
        frame_id=42,
        captured_at=1234.5,
    )
    visual = memory.latest_visual("office-main", max_age_sec=10**12)
    assert visual is not None
    assert visual["frame_id"] == 42
    assert set(visual).isdisjoint({"image", "jpeg", "base64"})


def test_session_id_is_bounded_and_safe() -> None:
    assert normalize_session_id("../office main!@#") == "..officemain"
    assert len(normalize_session_id("a" * 200)) == 80


class FakeMediaBackend:
    def __init__(self) -> None:
        self.pause_calls: list[tuple[str, ...]] = []
        self.resume_calls: list[list[str]] = []

    def pause_playing(self, excluded_apps: tuple[str, ...]) -> list[str]:
        self.pause_calls.append(excluded_apps)
        return ["Chrome", "Spotify", "Chrome"]

    def resume(self, source_ids: list[str]) -> list[str]:
        self.resume_calls.append(source_ids)
        return list(source_ids)


def test_media_controller_resumes_only_sessions_it_paused(tmp_path) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        media_pause_enabled=True,
        media_resume_delay_sec=0,
    )
    backend = FakeMediaBackend()
    controller = MediaSessionController(config, EventBus(), backend=backend)

    paused = controller.pause_for_interaction()
    resumed = controller.resume_after_interaction()

    assert paused["paused"] == ["Chrome", "Spotify"]
    assert backend.resume_calls == [["Chrome", "Spotify"]]
    assert resumed["resumed"] == ["Chrome", "Spotify"]
    assert controller.resume_after_interaction()["resumed"] == []


def test_camera_tool_call_parser_accepts_dict_and_rejects_other_tools() -> None:
    message = {
        "tool_calls": [
            {"function": {"name": "look_at_camera", "arguments": {"focus": "모니터"}}}
        ]
    }
    assert JarvisRuntime._camera_tool_call(message) == {"focus": "모니터"}
    assert JarvisRuntime._camera_tool_call(
        {"tool_calls": [{"function": {"name": "search", "arguments": {}}}]}
    ) is None


def test_current_face_question_forces_camera_without_previous_observation() -> None:
    assert JarvisRuntime._requires_fresh_camera("내 지금 얼굴 상태 많이 안 좋아 보이나?")
    assert JarvisRuntime._requires_fresh_camera("내 표정 어때?")
    assert not JarvisRuntime._requires_fresh_camera("얼굴 인식 AI의 원리를 설명해줘")
    assert not JarvisRuntime._requires_fresh_camera(
        "내 지금 얼굴 상태를 말하지 마", camera_denied=True
    )


def test_moving_the_camera_is_not_a_question_about_what_it_sees() -> None:
    # "왼쪽으로 돌려서 저쪽 좀 봐줘" is an instruction, not a question. Taking
    # the vision shortcut answers the wrong one -- and used to fail outright as
    # camera_frame_unavailable whenever no video source was attached, which
    # reads as a broken camera rather than a misrouted request.
    assert not JarvisRuntime._requires_fresh_camera("카메라 왼쪽으로 돌려서 저쪽 좀 봐줘")
    assert not JarvisRuntime._requires_fresh_camera("짐벌 정면으로 되돌려줘")
    assert not JarvisRuntime._requires_fresh_camera("카메라 아래로 움직여줘")
    # Genuine "what do you see" questions must still reach the camera.
    assert JarvisRuntime._requires_fresh_camera("내 표정 어때?")


def test_explicit_camera_commands_are_routed_deterministically() -> None:
    # Left to its own judgement the model answers "카메라를 다시 정면으로
    # 돌려놓았습니다" without calling anything -- measured, the preview did not
    # move. A confident report of an action that never happened is worse than
    # an error, because nothing downstream contradicts it.
    assert JarvisRuntime._requires_camera_control("짐벌 정면으로 되돌려줘")
    assert JarvisRuntime._requires_camera_control("카메라 오른쪽으로 조금만 움직여줘")
    assert JarvisRuntime._requires_camera_control("카메라 왼쪽으로 돌려줘")
    assert JarvisRuntime._requires_camera_control("라이브 송출 다시 켜줘")


def test_camera_control_needs_both_a_verb_and_a_subject() -> None:
    # "고개를 왼쪽으로 돌려봐" is about the person, not the camera; moving the
    # office camera because someone said 돌려 would be its own kind of wrong.
    assert not JarvisRuntime._requires_camera_control("고개를 왼쪽으로 돌려봐")
    assert not JarvisRuntime._requires_camera_control("카메라 잘 나오고 있어?")
    assert not JarvisRuntime._requires_camera_control(
        "카메라 왼쪽으로 돌려줘", camera_denied=True
    )


def test_contextual_answer_bypasses_tool_router_for_explicit_visual_question(
    monkeypatch, tmp_path
) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )
    runtime = JarvisRuntime(config)
    called: dict = {}

    def fake_vision_answer(**kwargs):
        called.update(kwargs)
        return "실제 카메라 답변", {"frame_id": 7}

    monkeypatch.setattr(runtime, "_vision_answer", fake_vision_answer)
    monkeypatch.setattr(
        runtime.ollama,
        "chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("router must be bypassed")),
    )

    answer, observation = runtime._contextual_answer(
        "내 지금 얼굴 상태 많이 안 좋아 보이나?", "office-main"
    )

    assert answer == "실제 카메라 답변"
    assert observation == {"frame_id": 7}
    assert "현재 얼굴" in called["focus"]


def test_vision_answer_includes_real_frame_metadata_and_stores_text_only(
    monkeypatch, tmp_path
) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )
    runtime = JarvisRuntime(config)
    captured_at = time.time()
    monkeypatch.setattr(
        runtime.vision,
        "latest_base64_with_metadata",
        lambda: {"image": "encoded-frame", "frame_id": 123, "captured_at": captured_at},
    )
    monkeypatch.setattr(runtime.ollama, "chat", lambda *_args, **_kwargs: "눈에 보이는 상태입니다.")

    answer, observation = runtime._vision_answer(
        prompt="내 얼굴 어때?",
        focus="현재 얼굴",
        session_id="office-main",
        history=[],
    )

    assert "카메라 실시간 확인" in answer
    assert "프레임 #123" in answer
    assert observation["frame_id"] == 123
    assert observation["captured_at_iso"]
    visual = runtime.memory.latest_visual("office-main")
    assert visual is not None
    assert visual["summary"] == "눈에 보이는 상태입니다."


def _blank_runtime(tmp_path) -> JarvisRuntime:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
    )
    return JarvisRuntime(config)


def test_a_missing_frame_answers_instead_of_killing_the_job(monkeypatch, tmp_path) -> None:
    # This used to `raise RuntimeError("camera_frame_unavailable")` with
    # nothing downstream catching it: the job died with status "failed" and no
    # reply ever reached the user, on a request as ordinary as "지금 뭐가
    # 보여?" landing here while the tablet was offline.
    runtime = _blank_runtime(tmp_path)
    monkeypatch.setattr(runtime.vision, "latest_base64_with_metadata", lambda: {"image": ""})
    monkeypatch.setattr(runtime.vision, "status", lambda: {"source": "usb"})
    monkeypatch.setattr(
        runtime.ollama,
        "chat",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no frame to ask the model about")),
    )

    answer, observation = runtime._vision_answer(
        prompt="지금 뭐가 보여?", focus="현재 장면", session_id="office-main", history=[]
    )

    assert "영상이 없어서" in answer
    assert observation == {"no_frame": True}


def test_a_missing_tablet_frame_names_the_tablet(monkeypatch, tmp_path) -> None:
    # A generic "카메라를 확인할 수 없습니다" sends nobody anywhere useful.
    # When the source is the tablet screen capture, the message should point
    # at the actual thing worth checking.
    runtime = _blank_runtime(tmp_path)
    monkeypatch.setattr(runtime.vision, "latest_base64_with_metadata", lambda: {"image": ""})
    monkeypatch.setattr(runtime.vision, "status", lambda: {"source": "tablet_screen"})

    answer, _ = runtime._vision_answer(
        prompt="지금 뭐가 보여?", focus="현재 장면", session_id="office-main", history=[]
    )

    assert "태블릿" in answer


def test_a_missing_frame_does_not_record_a_fake_observation(monkeypatch, tmp_path) -> None:
    # Nothing was actually seen, so nothing should be written into visual
    # memory as if it had been -- a later "아까 뭐 보였어?" would answer from a
    # sighting that never happened.
    runtime = _blank_runtime(tmp_path)
    monkeypatch.setattr(runtime.vision, "latest_base64_with_metadata", lambda: {"image": ""})
    monkeypatch.setattr(runtime.vision, "status", lambda: {"source": "usb"})

    runtime._vision_answer(
        prompt="지금 뭐가 보여?", focus="현재 장면", session_id="office-main", history=[]
    )

    assert runtime.memory.latest_visual("office-main") is None


def test_an_attached_image_never_goes_to_the_camera_shortcut(monkeypatch, tmp_path) -> None:
    """2026-09-17 라이브: 스크린샷을 붙이고 「이 이미지에 뭐가 보여?」 → 「지금 카메라 영상이 없어서…」."""
    runtime = _blank_runtime(tmp_path)
    monkeypatch.setattr(runtime, "_vision_answer", lambda **_kw: (_ for _ in ()).throw(AssertionError("camera must not be used")))
    seen: dict = {}

    def fake_chat(prompt, **kwargs):
        seen.update(kwargs)
        return {"content": "스크린샷에는 설정 화면이 보입니다.", "tool_calls": []}

    monkeypatch.setattr(runtime.ollama, "chat_message", fake_chat)
    answer, observation = runtime._contextual_answer("지금 이 이미지에 뭐가 보여?", "s", images=["aW1n"])
    assert answer.startswith("스크린샷에는") and observation is None
    assert seen["images"] == ["aW1n"] and seen["tools"] == []


def test_a_camera_call_with_an_attached_image_is_asked_again_without_the_camera(monkeypatch, tmp_path) -> None:
    """도구를 안 줬는데도 모델이 look_at_camera 를 부를 때가 있다 — 첨부가 있으면 카메라 대신 한 번 다시 묻는다."""
    runtime = _blank_runtime(tmp_path)
    monkeypatch.setattr(runtime, "_vision_answer", lambda **_kw: (_ for _ in ()).throw(AssertionError("camera must not be used")))
    calls: list = []

    def fake_chat(prompt, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"content": "", "tool_calls": [{"function": {"name": "look_at_camera", "arguments": {"focus": "화면"}}}]}
        return {"content": "첨부 이미지를 보니 버튼이 잘려 있습니다.", "tool_calls": []}

    monkeypatch.setattr(runtime.ollama, "chat_message", fake_chat)
    answer, _obs = runtime._contextual_answer("UI 괜찮아 보이는지 평가해줘", "s", images=["aW1n"])
    assert "버튼이 잘려" in answer
    assert len(calls) == 2 and "첨부된 이미지·문서를 직접 보고" in calls[1]["system"]


def test_without_an_image_the_camera_shortcut_still_works(monkeypatch, tmp_path) -> None:
    runtime = _blank_runtime(tmp_path)
    monkeypatch.setattr(runtime, "_vision_answer", lambda **_kw: ("카메라 답", {"frame_id": 1}))
    monkeypatch.setattr(runtime.ollama, "chat_message", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("shortcut expected")))
    assert runtime._contextual_answer("내 지금 얼굴 상태 어때 보여?", "s")[0] == "카메라 답"


def _png_b64() -> str:
    import base64 as _b64
    return _b64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 64).decode()


def test_the_same_pasted_image_twice_reaches_the_model_once(tmp_path) -> None:
    """2026-09-17: 캡처 한 장이 붙여넣기 두 통로로 같은 바이트 두 개가 됐다 — 모델엔 한 번만."""
    runtime = _blank_runtime(tmp_path)
    same = {"name": "image.png", "mime_type": "image/png", "data_base64": _png_b64()}
    _context, images, metadata = runtime._attachments({"attachments": [same, dict(same)]}, "q")
    assert len(images) == 1 and len(metadata) == 1


def test_an_image_preview_is_kept_for_the_message_but_only_as_an_image_data_url(tmp_path) -> None:
    runtime = _blank_runtime(tmp_path)
    good = {"name": "shot.png", "mime_type": "image/png", "data_base64": _png_b64(),
            "thumbnail": "data:image/jpeg;base64,/9j/4AAQ", "width": 1920, "height": 1080}
    _c, _i, metadata = runtime._attachments({"attachments": [good]}, "q")
    assert metadata[0]["thumbnail"].startswith("data:image/jpeg") and metadata[0]["width"] == 1920
    assert metadata[0]["size"] > 0

    evil = dict(good, data_base64=_png_b64() + "AAAA", thumbnail="javascript:alert(1)")
    _c, _i, metadata = runtime._attachments({"attachments": [evil]}, "q")
    assert "thumbnail" not in metadata[0] and "width" not in metadata[0]


def test_the_preview_never_reaches_the_model_context(tmp_path) -> None:
    runtime = _blank_runtime(tmp_path)
    runtime.memory.add_exchange("s", "이거 봐줘", "봤습니다",
                                user_metadata={"attachments": [{"name": "a.png", "mime_type": "image/png",
                                                                "thumbnail": "data:image/jpeg;base64,SECRETPIXELS"}]})
    context = runtime._memory_context("s", "다음 질문")
    assert "SECRETPIXELS" not in json.dumps(context, ensure_ascii=False)
