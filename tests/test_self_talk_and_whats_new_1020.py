"""손자리가 자기 설정을 대화로 알려 주고 · 묻고 · 바꾸기 · 업데이트 뒤 「바뀐 것」 (2026-10-20 대표).

대표: 「그림 읽기가 꺼져 있으면 손자리가 '켜면 된다, 바꿔 드릴까요?' 하고 — 카드 말고 대화로 — 바꿔 주면 좋겠다 · 설정을 다 보고
있어야 한다 · 업데이트하면 바뀐 것을 알려 줘라, 지금 사용자는 아예 모른다 · 디스코드처럼 되는 게 많은데 한번 알려 줘라」.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import self_talk as talk
from alture_jarvis import whats_new
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime

VERSION = "0.4.27.0"


# ── 「바뀐 것」 글과 상태 ─────────────────────────────────────────────────────

def test_the_release_has_notes_in_both_languages_with_a_tour() -> None:
    for lang in ("ko", "en"):
        notes = whats_new.notes_for(VERSION, lang)
        assert notes and notes["changes"].strip() and notes["tour"].strip()
    assert "디스코드" in whats_new.notes_for(VERSION, "ko")["tour"]
    assert "Discord" in whats_new.notes_for(VERSION, "en")["tour"]
    assert not any("가" <= ch <= "힣" for ch in json.dumps(whats_new.notes_for(VERSION, "en"), ensure_ascii=False))


def test_english_notes_use_the_real_menu_names() -> None:
    from alture_jarvis import ui_i18n

    tour = whats_new.notes_for(VERSION, "en")["tour"]
    for korean in ("이어받기", "예약 작업"):
        assert ui_i18n.translate_text(korean) in tour
    ui_en = json.loads((Path(__file__).resolve().parents[1] / "ui" / "src" / "i18n" / "en.json").read_text(encoding="utf-8"))
    for korean in ("연결", "디스코드로 일 시키기", "나에 대한 지침"):
        assert ui_en[korean] in tour


def test_nothing_shows_outside_a_package() -> None:
    assert whats_new.status("unused", "", setup_done=True) == {"show": False, "version": ""}


def test_a_fresh_install_is_not_told_and_is_marked_seen(tmp_path: Path) -> None:
    got = whats_new.status(tmp_path, VERSION, setup_done=False)
    assert got["show"] is False
    assert whats_new.read_seen(tmp_path) == VERSION


def test_someone_coming_from_an_older_version_sees_it_once(tmp_path: Path) -> None:
    # 기록이 없는데 첫 설정을 마친 사람 = 이 기능이 처음 들어간 판으로 넘어온 사람
    got = whats_new.status(tmp_path, VERSION, setup_done=True)
    assert got["show"] is True and got["version"] == VERSION and got["changes"]
    whats_new.mark_seen(tmp_path, VERSION)
    assert whats_new.status(tmp_path, VERSION, setup_done=True)["show"] is False


def test_the_next_update_shows_again(tmp_path: Path) -> None:
    whats_new.mark_seen(tmp_path, "0.4.25.0")
    assert whats_new.status(tmp_path, VERSION, setup_done=True)["show"] is True


def test_a_version_without_notes_shows_nothing(tmp_path: Path) -> None:
    whats_new.mark_seen(tmp_path, VERSION)
    assert whats_new.status(tmp_path, "9.9.9.0", setup_done=True)["show"] is False
    assert whats_new.notes_for("../secrets") is None


def test_the_chat_answer_names_the_version() -> None:
    answer = whats_new.chat_answer(VERSION)
    assert answer.startswith(f"손자리 {VERSION} 에서 바뀐 것입니다.")
    assert "디스코드" in answer


# ── 말 알아보기 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["응", "응 바꿔줘", "어엉", "네!", "ㅇㅇ", "좋아요", "그렇게 해줘", "켜줘", "yes", "ok"])
def test_short_yes(text: str) -> None:
    assert talk.is_yes(text)


@pytest.mark.parametrize("text", ["응 근데 네이버에서 가격 찾아줘", "네이버", "응? 뭐라고", "그림 읽기는 왜 꺼져 있어"])
def test_not_a_yes(text: str) -> None:
    assert not talk.is_yes(text)


@pytest.mark.parametrize("text", ["뭐가 바뀌었어?", "이번 업데이트 뭐가 바뀌었어", "업데이트 내용 알려줘", "새로운 기능 뭐 있어?",
                                  "손자리 뭐가 새로 생겼어?", "what's new?"])
def test_asks_whats_new(text: str) -> None:
    assert talk.asks_whats_new(text)


@pytest.mark.parametrize("text", ["네이버 뭐가 바뀌었어", "이 사이트 디자인 뭐가 달라졌는지 찾아줘", "윈도우 업데이트 해줘",
                                  "아이폰 새 기능 정리해서 엑셀로 만들어줘"])
def test_does_not_steal_work_requests(text: str) -> None:
    assert not talk.asks_whats_new(text)
    assert not talk.asks_settings(text)
    assert talk.eyes_command(text) is None


@pytest.mark.parametrize("text", ["지금 설정 보여줘", "손자리 설정 알려줘", "무슨 모델 써?", "그림 읽기 켜져 있어?"])
def test_asks_settings(text: str) -> None:
    assert talk.asks_settings(text)


def test_windows_settings_are_not_ours() -> None:
    assert not talk.asks_settings("윈도우 설정 보여줘")
    assert not talk.asks_settings("블루투스 설정 열어줘")


def test_eyes_commands() -> None:
    assert talk.eyes_command("그림 읽기 켜 줘") is True
    assert talk.eyes_command("그림읽기 꺼줘") is False
    assert talk.eyes_command("turn picture reading on") is True
    assert talk.eyes_command("그림 읽기를 켜고 이 사이트 상품 사진에서 가격 읽어서 표로 정리해줘") is None  # 긴 일 부탁은 가로채지 않는다


# ── 대화 흐름 ───────────────────────────────────────────────────────────────

class _Model:
    def __init__(self, reads: bool = False, can_switch: bool = True) -> None:
        self.reads, self.can_switch = reads, can_switch
        self.applied: list[bool] = []

    def ctx(self, lang: str = "ko") -> talk.SelfContext:
        return talk.SelfContext(
            version=lambda: VERSION,
            lang=lambda: lang,
            current_eyes=lambda: {"tag": "m", "reads_pictures": self.reads, "can_switch": self.can_switch,
                                  "source_tag": "m", "saves_gb": 0.9},
            apply_eyes=self.apply,
            summary=lambda: {"version": VERSION, "model": "m", "reads_pictures": self.reads,
                             "can_switch": self.can_switch, "num_ctx": 65536},
        )

    def apply(self, on: bool) -> dict[str, Any]:
        self.applied.append(on)
        self.reads = on
        return {"ok": True, "selection": {"num_ctx": 65536 if on else 131072}}


def test_offer_yes_switches_and_undo_switches_back() -> None:
    model, chat = _Model(), talk.SelfTalk()
    chat.offer_eyes("s1")
    got = chat.intercept("응", "s1", model.ctx())
    assert got and got["kind"] == "eyes_switched" and model.applied == [True]
    assert "되돌리려면" in got["answer"] and "64K" in got["answer"]
    back = chat.intercept("되돌려", "s1", model.ctx())
    assert back and back["kind"] == "eyes_switched" and model.applied == [True, False]


def test_the_offer_lives_for_one_message_only() -> None:
    model, chat = _Model(), talk.SelfTalk()
    chat.offer_eyes("s1")
    assert chat.intercept("네이버에서 노트북 가격 찾아줘", "s1", model.ctx()) is None
    assert chat.intercept("응", "s1", model.ctx()) is None, "다른 말 뒤의 「응」은 제안을 승인하지 않는다"
    assert model.applied == []


def test_the_offer_is_per_conversation() -> None:
    model, chat = _Model(), talk.SelfTalk()
    chat.offer_eyes("s1")
    assert chat.intercept("응", "s2", model.ctx()) is None
    assert model.applied == []


def test_no_keeps_it() -> None:
    model, chat = _Model(), talk.SelfTalk()
    chat.offer_eyes("s1")
    got = chat.intercept("아니", "s1", model.ctx())
    assert got and got["kind"] == "offer_declined" and model.applied == []


def test_an_old_offer_expires() -> None:
    now = [1000.0]
    model, chat = _Model(), talk.SelfTalk(clock=lambda: now[0])
    chat.offer_eyes("s1")
    now[0] += talk.OFFER_TTL_SEC + 1
    assert chat.intercept("응", "s1", model.ctx()) is None


def test_undo_without_a_change_is_not_taken() -> None:
    model, chat = _Model(), talk.SelfTalk()
    assert chat.intercept("되돌려", "s1", model.ctx()) is None


def test_a_direct_command_does_not_need_a_yes() -> None:
    model, chat = _Model(), talk.SelfTalk()
    got = chat.intercept("그림 읽기 켜 줘", "s1", model.ctx())
    assert got and model.applied == [True]


def test_already_on_and_not_switchable_are_said_plainly() -> None:
    chat = talk.SelfTalk()
    on = _Model(reads=True)
    assert chat.intercept("그림 읽기 켜 줘", "s1", on.ctx())["kind"] == "eyes_already" and on.applied == []
    fixed = _Model(can_switch=False)
    got = chat.intercept("그림 읽기 켜 줘", "s1", fixed.ctx())
    assert got["kind"] == "eyes_not_switchable" and fixed.applied == []


def test_a_failed_switch_says_the_old_setting_is_kept() -> None:
    model, chat = _Model(), talk.SelfTalk()
    model.apply = lambda on: {"ok": False, "error": "model_not_fully_on_gpu"}  # type: ignore[method-assign]
    got = chat.intercept("그림 읽기 켜 줘", "s1", model.ctx())
    assert got["kind"] == "eyes_failed" and "원래 설정 그대로" in got["answer"]
    assert chat.intercept("되돌려", "s1", model.ctx()) is None, "바뀐 게 없으면 되돌릴 것도 없다"


def test_settings_and_whats_new_answers() -> None:
    model, chat = _Model(), talk.SelfTalk()
    settings = chat.intercept("지금 설정 보여줘", "s1", model.ctx())
    assert settings["kind"] == "settings" and "그림 읽기: 꺼짐" in settings["answer"] and "64K" in settings["answer"]
    news = chat.intercept("뭐가 바뀌었어?", "s1", model.ctx())
    assert news["kind"] == "whats_new" and VERSION in news["answer"]
    english = chat.intercept("what's new?", "s1", model.ctx("en"))
    assert english["answer"].startswith(f"Here is what changed in Sonjari {VERSION}.")


def test_offer_text_has_the_cost() -> None:
    text = talk.eyes_offer_text(2, 0.9, 131072)
    assert "페이지 2곳" in text and "0.9GB" in text and "128K" in text and "켜 드릴까요?" in text
    assert "Want me to turn picture reading on?" in talk.eyes_offer_text(1, 0.0, 65536, "en")


def test_unread_picture_pages_counts_only_unread_bodies() -> None:
    steps = [
        {"ok": True, "evidence": {"url": "https://a.test/1", "image_body": True}},
        {"ok": True, "evidence": {"url": "https://a.test/1", "image_body": True}},
        {"ok": True, "evidence": {"url": "https://a.test/2", "image_body": True, "images_read": 3}},
        {"ok": True, "evidence": {"url": "https://a.test/3"}},
        {"ok": False, "evidence": {"url": "https://a.test/4", "image_body": True}},
    ]
    assert talk.unread_picture_pages(steps) == 1


# ── 채팅 입구에서 (실제 런타임) ────────────────────────────────────────────────

class _NoModel:
    """모델을 부르면 시험이 떨어진다 — 손자리 자신에 대한 말은 모델 없이 답해야 한다."""

    def reads_pictures(self, role: str = "chat") -> bool:
        return False

    def chat_message(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("모델을 불렀다: " + prompt[:60])

    chat_message_stream = chat_message

    def chat(self, prompt: str, **kwargs: Any) -> str:
        raise AssertionError("모델을 불렀다: " + prompt[:60])


class _Setup:
    def __init__(self) -> None:
        self.reads = False
        self.calls: list[tuple[str, int, Any]] = []

    def current_eyes(self) -> dict[str, Any]:
        return {"tag": "m", "reads_pictures": self.reads, "can_switch": True, "source_tag": "m", "saves_gb": 0.9}

    def apply_tag(self, tag: str, num_ctx: int = 32768, *, remembered_first: bool = False, eyes: Any = None) -> dict[str, Any]:
        self.calls.append((tag, num_ctx, eyes))
        self.reads = bool(eyes)
        return {"ok": True, "selection": {"num_ctx": num_ctx}}


def _runtime(tmp_path: Path) -> JarvisRuntime:
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    runtime = create_app(config, start_services=False).state.jarvis
    runtime.ollama = _NoModel()
    runtime._learn_facts = lambda *args, **kwargs: None
    runtime.setup_service = _Setup()
    return runtime


def test_the_chat_entry_answers_about_itself_without_the_model(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    result = runtime._chat_job_inner({"id": "j-self-1", "payload": {"prompt": "뭐가 바뀌었어?", "session_id": "s-self"}})
    assert "에서 바뀐 것입니다." in str(result.get("answer") or "")


def test_the_chat_entry_switches_pictures_on_a_yes(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.self_talk.offer_eyes("s-self")
    result = runtime._chat_job_inner({"id": "j-self-2", "payload": {"prompt": "응", "session_id": "s-self"}})
    assert "그림 읽기를 켰습니다" in str(result.get("answer") or "")
    assert runtime.setup_service.calls and runtime.setup_service.calls[0][2] is True


def test_a_claude_handed_job_is_not_intercepted(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    payload = {"prompt": "그림 읽기 켜 줘", "session_id": "s-mcp", "origin": "mcp"}
    with pytest.raises(AssertionError, match="모델을 불렀다"):
        runtime._chat_job_inner({"id": "j-self-3", "payload": payload})
    assert runtime.setup_service.calls == []


def test_the_eyes_offer_needs_a_blind_switchable_model(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    steps = [{"ok": True, "evidence": {"url": "https://shop.test/p/1", "image_body": True}}]
    assert "켜 드릴까요?" in runtime._eyes_offer(steps)
    runtime.setup_service.reads = True
    assert runtime._eyes_offer(steps) == ""
    runtime.setup_service.reads = False
    runtime.ollama = type("Sees", (_NoModel,), {"reads_pictures": lambda self, role="chat": True})()
    assert runtime._eyes_offer(steps) == "", "그림 읽기가 켜진 PC 의 「못 읽음」은 다른 까닭이라 묻지 않는다"


def test_the_system_prompt_knows_its_own_settings(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    line = runtime._self_status_line()
    assert line.startswith("손자리 자신의 지금 설정:") and "그림 읽기 꺼짐" in line


def test_the_whats_new_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("JARVIS_FAKE_PACKAGE_FULL_NAME", f"RoboMetaFit.Sonjari_{VERSION}_x64__abc")
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    app = create_app(config, start_services=False)
    client = TestClient(app)
    headers = {"X-Jarvis-Token": "test-token"}
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "setup_state.json").write_text(json.dumps({"completed": True, "steps": []}), encoding="utf-8")
    first = client.get("/v1/whats-new", headers=headers).json()
    assert first["show"] is True and first["version"] == VERSION
    assert client.post("/v1/whats-new/seen", headers=headers, json={"version": VERSION}).json()["ok"] is True
    assert client.get("/v1/whats-new", headers=headers).json()["show"] is False


# ── 패키지 밖(운영 PC)에서도 새 판 글이 한 번 뜬다 (2026-10-27 대표) ──────────────────────────────────────────

def test_outside_a_package_the_newest_notes_show_once_then_again_for_the_next_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import msix

    monkeypatch.setattr(msix, "package_version", lambda: "")
    app = create_app(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    ), start_services=False)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    headers = {"X-Jarvis-Token": "test-token"}
    newest = whats_new.newest_version()
    assert newest
    # 설정을 끝낸 PC 로 만든다(막 깐 사람은 마법사가 먼저라 안 띄운다).
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "setup_state.json").write_text(json.dumps({"completed": True}), encoding="utf-8")
    first = client.get("/v1/whats-new?lang=ko", headers=headers).json()
    # 장(slides)은 판마다 있을 수도 없을 수도 있다(0.4.35 는 쓰는 법 쇼가 따로 있어 목록만) — 여기서 보는 것은 「한 번 뜬다」.
    assert first["show"] is True and first["version"] == newest
    client.post("/v1/whats-new/seen", json={"version": first["version"]}, headers=headers)
    assert client.get("/v1/whats-new?lang=ko", headers=headers).json()["show"] is False
    # 다음 판 글이 들어오면(= 더 높은 번호가 newest 가 되면) 다시 뜬다.
    monkeypatch.setattr(whats_new, "newest_version", lambda: "9.9.9.0")
    monkeypatch.setattr(whats_new, "notes_for", lambda version, lang="ko": {"changes": "새 글", "tour": "", "slides": []})
    again = client.get("/v1/whats-new?lang=ko", headers=headers).json()
    assert again["show"] is True and again["version"] == "9.9.9.0"
