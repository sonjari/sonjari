"""「나에 대한 지침」 (2026-10-18) — 사용자 지침을 파일 하나(`JARVIS_PROFILE.md`)로 모으고 그 위에 쉬운 화면을 얹는다.

지키는 것을 하나씩 잰다:

    - 읽기 · 저장 · 상한(넘으면 거절하고 파일은 그대로)
    - 저장하면 **다시 켜지 않아도 다음 턴**부터 시스템 글에 실린다(메모장으로 고쳐도)
    - 길이 자(창의 N%)는 실제로 실리는 블록을 우리 글자/토큰 상수로 잰다
    - 3분 카드: 답 → 줄은 결정론, 카드 칸만 바뀌고 손으로 쓴 줄은 남는다, 부르는 이름은 설정 그대로
    - 가져온 지침: 고른 줄만 더한다 · 비밀이 걷힌 줄은 못 더한다 · 원본 파일을 다시 열지 않는다

★ 가짜 비밀은 실행 중에 조립한다(`test_secret_scrub.py` 와 같은 이유 — 저장소 비밀 검사가 시험 파일을 막지 않게).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alture_jarvis.about_me import (
    CARD_END,
    CARD_START,
    WARN_SHARE,
    AboutMe,
    card_lines,
    merge_card,
    normalize_answers,
)
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.instruction_import import InstructionImportService
from alture_jarvis.profile import OperatorProfile, profile_block
from alture_jarvis.transcript import CHARS_PER_TOKEN

FAKE_KEY = "sk-" + "ant-api03-" + "Q7fK2mZp9Lx4Rt8Vb3Nc6Hy1Wd5Js0Ge" + "Aa11Bb22"
AUTH = {"X-JARVIS-TOKEN": "test-token"}


class _Config:
    """`num_ctx_for` 만 쓰는 가벼운 설정."""

    def __init__(self, num_ctx: int = 32768, user_label: str = "") -> None:
        self.num_ctx = num_ctx
        self.user_label = user_label

    def num_ctx_for(self, role: str = "chat") -> int:
        return self.num_ctx


class _Settings:
    def __init__(self, config: _Config) -> None:
        self.config = config
        self.calls: list[dict] = []

    def patch(self, changes: dict) -> dict:
        self.calls.append(changes)
        if len(changes.get("user_label", "")) > 20:
            return {"ok": False, "error": "too_long:user_label"}
        self.config.user_label = changes["user_label"]
        return {"ok": True}


def _service(tmp_path: Path, *, max_chars: int = 6000, num_ctx: int = 32768, imports=None):
    config = _Config(num_ctx)
    profile = OperatorProfile(tmp_path / "data" / "JARVIS_PROFILE.md", max_chars=max_chars)
    settings = _Settings(config)
    return AboutMe(config, profile, settings=settings, imports=imports, clock=lambda: 1_760_745_600.0), config, settings


# ── 읽기 · 저장 · 상한 ─────────────────────────────────────────────────────────
def test_empty_profile_reads_as_zero(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path)
    view = about.view()
    assert view["exists"] is False
    assert view["content_raw"] == ""
    assert view["tokens"] == 0 and view["share_pct"] == 0
    assert view["path"].endswith("JARVIS_PROFILE.md")


def test_save_writes_the_file_and_the_next_turn_sees_it(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path)
    result = about.save("- 답은 짧게.\n")
    assert result["ok"] and result["saved"]
    assert about.path.read_bytes() == "- 답은 짧게.\n".encode("utf-8")
    assert about.profile.content == "- 답은 짧게."


def test_over_cap_is_refused_and_the_file_is_untouched(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path, max_chars=500)
    about.save("- 원래 줄\n")
    result = about.save("가" * 501)
    assert result["ok"] is False and result["error"] == "too_long"
    assert result["chars"] == 501 and result["max_chars"] == 500
    assert "500자" in result["message"]
    assert about.path.read_text(encoding="utf-8") == "- 원래 줄\n"


def test_exactly_at_cap_is_accepted(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path, max_chars=500)
    assert about.save("가" * 500)["ok"]


def test_hand_edit_is_picked_up_without_restart(tmp_path: Path) -> None:
    """메모장으로 고친 것도 다음 턴부터 — 기동 때 한 번만 읽던 예전 동작을 바꿨다."""
    path = tmp_path / "JARVIS_PROFILE.md"
    path.write_bytes("첫 판".encode("utf-8"))
    profile = OperatorProfile(path)
    assert profile.content == "첫 판"
    path.write_bytes("고친 판 — 길이도 다르다".encode("utf-8"))
    assert profile.content == "고친 판 — 길이도 다르다"
    path.unlink()
    assert profile.content == ""


def test_comments_never_reach_the_model(tmp_path: Path) -> None:
    path = tmp_path / "JARVIS_PROFILE.md"
    path.write_bytes("<!-- 메모: 모델은 못 본다 -->\n- 한국어로 답한다.\n".encode("utf-8"))
    assert OperatorProfile(path).content == "- 한국어로 답한다."


def test_oversized_hand_edit_says_it_was_cut(tmp_path: Path) -> None:
    path = tmp_path / "JARVIS_PROFILE.md"
    path.write_bytes(("가" * 700).encode("utf-8"))
    profile = OperatorProfile(path, max_chars=500)
    assert profile.truncated is True and profile.status()["truncated"] is True
    assert len(profile.content) == 500


def test_runtime_system_prompt_uses_the_saved_text_on_the_next_turn(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis
    with TestClient(app) as client:
        assert "<jarvis-profile>" not in runtime._system_prompt()
        saved = client.put("/v1/about-me", headers=AUTH, json={"content": "- 나는 학원을 운영한다.\n"}).json()
        assert saved["ok"]
        prompt = runtime._system_prompt()
        assert profile_block("- 나는 학원을 운영한다.") in prompt


# ── 길이 자 ────────────────────────────────────────────────────────────────────
def test_meter_measures_the_block_actually_sent(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path, num_ctx=32768)
    text = "- " + "가" * 998
    about.save(text)
    view = about.view()
    expected = math.ceil(len(profile_block(text)) / CHARS_PER_TOKEN)
    assert view["tokens"] == expected
    assert view["num_ctx"] == 32768
    assert view["share"] == round(expected / 32768, 4)
    assert view["chars_per_token"] == CHARS_PER_TOKEN


def test_meter_warns_above_ten_percent_of_the_window(tmp_path: Path) -> None:
    about, config, _ = _service(tmp_path, num_ctx=8192)
    about.save("가" * 1500)  # ≈ 800 토큰 / 8192 ≈ 9.8%
    assert about.view()["warn"] is False
    about.save("가" * 1800)  # ≈ 950 토큰 ≈ 11.6%
    view = about.view()
    assert view["warn"] is True and view["share"] > WARN_SHARE


def test_meter_ignores_comments_like_the_loader(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path)
    about.save("<!-- " + "메모 " * 300 + "-->\n- 짧은 줄\n")
    assert about.view()["sent_chars"] == len("- 짧은 줄")


# ── 3분 카드 ───────────────────────────────────────────────────────────────────
ANSWERS = {"user_label": "가람", "work_text": "학원 운영", "length": "short", "tone": "polite",
           "sites": "네이버, 사람인, 네이버", "avoid_text": "영어로 답하지 말 것"}


def test_card_lines_are_deterministic_and_in_fixed_order() -> None:
    answers = normalize_answers(ANSWERS)
    lines = card_lines(answers)
    assert lines == [
        "- 하는 일: 학원 운영",
        "- 답은 짧게, 핵심부터.",
        "- 말투는 정중하게, 존댓말로.",
        "- 자주 쓰는 사이트: 네이버, 사람인",
        "- 하지 말 것: 영어로 답하지 말 것",
    ]
    assert card_lines(normalize_answers(ANSWERS)) == lines  # 같은 답 → 같은 줄
    assert card_lines(answers, "en")[1] == "- Keep answers short; lead with the point."


def test_normal_length_and_blank_answers_add_no_lines() -> None:
    assert card_lines(normalize_answers({"length": "normal"})) == []
    assert card_lines(normalize_answers({})) == []


def test_bad_choices_and_long_answers_are_refused() -> None:
    from alture_jarvis.about_me import AboutMeError

    with pytest.raises(AboutMeError):
        normalize_answers({"length": "very_long"})
    with pytest.raises(AboutMeError):
        normalize_answers({"work_text": "가" * 121})


def test_answers_cannot_break_the_card_block() -> None:
    answers = normalize_answers({"avoid_text": "<!-- 몰래 --> 숨기기"})
    assert "<!--" not in card_lines(answers)[0] and "-->" not in card_lines(answers)[0]


def test_preview_does_not_write(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path)
    preview = about.preview_card(ANSWERS)
    assert preview["ok"] and preview["card_lines"][0] == "- 하는 일: 학원 운영"
    assert CARD_START in preview["content_raw"]
    assert not about.path.exists() and not about.answers_path.exists()


def test_save_card_keeps_hand_written_lines_and_replaces_only_the_card(tmp_path: Path) -> None:
    about, config, settings = _service(tmp_path)
    about.save("- 개발자가 손으로 쓴 줄\n")
    first = about.save_card(ANSWERS)
    assert first["ok"]
    text = about.path.read_text(encoding="utf-8")
    assert text.startswith(CARD_START) and CARD_END in text
    assert "- 개발자가 손으로 쓴 줄" in text
    # 카드를 다시 저장하면 카드 칸만 바뀐다.
    about.save_card({**ANSWERS, "length": "long"})
    text = about.path.read_text(encoding="utf-8")
    assert "- 답은 자세히, 까닭과 예를 들어." in text and "- 답은 짧게, 핵심부터." not in text
    assert text.count(CARD_START) == 1
    assert "- 개발자가 손으로 쓴 줄" in text
    # 모델에게는 경계 표시 없이 줄만 간다.
    assert "sonjari:card" not in about.profile.content
    assert about.profile.content.startswith("- 하는 일: 학원 운영")


def test_card_answers_are_stored_beside_the_file_and_reopen_prefilled(tmp_path: Path) -> None:
    about, config, settings = _service(tmp_path)
    about.save_card(ANSWERS)
    stored = json.loads(about.answers_path.read_text(encoding="utf-8"))
    assert stored["answers"]["work_text"] == "학원 운영"
    assert "user_label" not in stored["answers"]  # 이름은 설정에만 산다
    view = about.view()
    assert view["answers"]["sites"] == ["네이버", "사람인"]
    assert view["answers"]["user_label"] == "가람"


def test_card_name_goes_to_the_existing_setting_not_the_file(tmp_path: Path) -> None:
    about, config, settings = _service(tmp_path)
    about.save_card(ANSWERS)
    assert settings.calls == [{"user_label": "가람"}]
    assert config.user_label == "가람"
    assert "가람" not in about.path.read_text(encoding="utf-8")
    # 이름이 그대로면 설정을 다시 안 고친다.
    about.save_card(ANSWERS)
    assert len(settings.calls) == 1


def test_emptying_the_card_removes_its_block(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path)
    about.save("- 남는 줄\n")
    about.save_card(ANSWERS)
    about.save_card({"user_label": "가람"})
    assert about.path.read_text(encoding="utf-8") == "- 남는 줄\n"


def test_card_that_would_overflow_is_refused(tmp_path: Path) -> None:
    about, *_ = _service(tmp_path, max_chars=500)
    about.save("가" * 480)
    result = about.save_card(ANSWERS)
    assert result["ok"] is False and result["error"] == "too_long"
    assert about.path.read_text(encoding="utf-8") == "가" * 480 + "\n"


def test_merge_card_on_empty_file() -> None:
    assert merge_card("", "") == ""
    merged = merge_card("", f"{CARD_START}\n- 줄\n{CARD_END}\n")
    assert merged.endswith(f"{CARD_END}\n")


# ── 가져온 지침에서 골라 올리기 ─────────────────────────────────────────────────
@pytest.fixture
def imported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    path = home / ".claude" / "CLAUDE.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        f"# 전역 지침\n한국어로 답한다.\n\n검증 키: {FAKE_KEY}\nAPI_TOKEN={FAKE_KEY}\n결론부터 말한다.\n".encode("utf-8"))
    monkeypatch.setattr(InstructionImportService, "_home", staticmethod(lambda: home))
    monkeypatch.setattr(InstructionImportService, "_appdata", staticmethod(lambda: None))
    opened: list[Path] = []

    def reader(p: Path) -> bytes:
        opened.append(Path(p))
        return Path(p).read_bytes()

    service = InstructionImportService(tmp_path / "data" / "jarvis.db", read_bytes=reader)
    preview = service.preview("", ["claude:global"])["items"][0]
    saved = service.commit("", [{"id": "claude:global", "sha256": preview["sha256"]}])["saved"][0]
    opened.clear()
    return service, saved["import_id"], opened


def test_import_lines_flag_secret_and_blank_lines(tmp_path: Path, imported) -> None:
    service, import_id, opened = imported
    about, *_ = _service(tmp_path, imports=service)
    result = about.import_lines(import_id)
    by_text = {line["raw"]: line for line in result["lines"]}
    assert by_text["한국어로 답한다."]["allowed"] is True
    assert by_text[""]["reason"] == "blank"
    secret_lines = [line for line in result["lines"] if line["reason"] == "secret"]
    assert len(secret_lines) == 2
    assert FAKE_KEY not in json.dumps(result, ensure_ascii=False)
    assert opened == []  # 원본 파일은 다시 열지 않는다 — 걷은 사본에서 읽는다


def test_append_adds_only_picked_lines_and_refuses_secrets(tmp_path: Path, imported) -> None:
    service, import_id, _ = imported
    about, *_ = _service(tmp_path, imports=service)
    lines = about.import_lines(import_id)["lines"]
    index = {line["raw"]: line["index"] for line in lines}
    secret = next(line["index"] for line in lines if line["reason"] == "secret")
    result = about.append_import(import_id, [index["결론부터 말한다."], secret])
    assert result["ok"] and result["added"] == 1
    assert result["refused"] == [{"index": secret, "reason": "secret"}]
    text = about.path.read_text(encoding="utf-8")
    assert "결론부터 말한다." in text
    assert "한국어로 답한다." not in text  # 안 고른 줄은 안 들어간다
    assert "비밀 걷어 냄" not in text and FAKE_KEY not in text
    assert "<!-- 가져옴: Claude Code · CLAUDE.md · " in text
    # 모델에게는 출처 주석 없이 줄만.
    assert about.profile.content == "결론부터 말한다."
    # 같은 줄은 두 번 못 더한다.
    again = about.import_lines(import_id)["lines"]
    assert next(line for line in again if line["raw"] == "결론부터 말한다.")["reason"] == "already"


def test_append_with_only_refused_lines_writes_nothing(tmp_path: Path, imported) -> None:
    service, import_id, _ = imported
    about, *_ = _service(tmp_path, imports=service)
    secret = next(line["index"] for line in about.import_lines(import_id)["lines"] if line["reason"] == "secret")
    result = about.append_import(import_id, [secret, 999])
    assert result["ok"] is False and result["error"] == "nothing_to_add"
    assert {r["reason"] for r in result["refused"]} == {"secret", "not_in_import"}
    assert not about.path.exists()


def test_unknown_import_is_not_found(tmp_path: Path, imported) -> None:
    service, _, _ = imported
    about, *_ = _service(tmp_path, imports=service)
    assert about.import_lines(424242)["error"] == "not_found"
    assert about.append_import(424242, [0])["error"] == "not_found"


# ── HTTP ──────────────────────────────────────────────────────────────────────
def test_routes_need_the_token_and_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import alture_jarvis.file_open as file_open

    opened: list = []
    monkeypatch.setattr(file_open, "open_file", lambda *args, **kwargs: opened.append(args))
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md",
                          profile_max_chars=800)
    app = create_app(config, start_services=False)
    with TestClient(app) as client:
        assert client.get("/v1/about-me").status_code == 401
        assert client.put("/v1/about-me", json={"content": "x"}).status_code == 401
        assert client.post("/v1/about-me/card", json={"answers": {}}).status_code == 401
        view = client.get("/v1/about-me", headers=AUTH).json()
        assert view["max_chars"] == 800 and view["num_ctx"] == config.num_ctx_for("chat")
        too_long = client.put("/v1/about-me", headers=AUTH, json={"content": "가" * 801}).json()
        assert too_long["ok"] is False and too_long["error"] == "too_long"
        preview = client.post("/v1/about-me/card/preview", headers=AUTH,
                              json={"answers": ANSWERS}).json()
        assert preview["card_lines"][1] == "- 답은 짧게, 핵심부터."
        saved = client.post("/v1/about-me/card", headers=AUTH, json={"answers": ANSWERS}).json()
        assert saved["ok"] and saved["answers"]["user_label"] == "가람"
        # 부르는 이름은 설정 화면과 같은 값이다.
        settings = client.get("/v1/settings", headers=AUTH).json()
        assert next(row for row in settings["settings"] if row["key"] == "user_label")["value"] == "가람"
        # 원문 편집기가 받은 그대로 다시 저장해도 카드 칸이 남는다.
        again = client.put("/v1/about-me", headers=AUTH, json={"content": saved["content_raw"]}).json()
        assert again["has_card"] is True
        # 「파일 열기」는 설정의 파일 하나만 연다(경로를 받지 않는다). 실제로 띄우는 함수는 바꿔 끼워 세기만 한다.
        result = client.post("/v1/about-me/open", headers=AUTH, json={"path": "C:/Windows/win.ini"})
        if result.status_code == 200 and result.json().get("ok"):
            assert [Path(str(args[0])).name for args in opened] == ["JARVIS_PROFILE.md"]
        else:  # 루프백이 아니라고 보는 환경이면 아무것도 안 띄운다
            assert opened == []
        assert client.get("/v1/about-me/import-lines", params={"import_id": 1}, headers=AUTH).json()["error"] == "not_found"


def test_english_screen_does_not_rewrite_the_users_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """영어 화면이면 응답의 한국어를 사전으로 바꾼다 — 사용자 글이 우연히 사전 문장과 같아도 그대로 와야 한다.

    그대로 안 오면 화면이 바뀐 글(영어)을 그대로 다시 저장해 사용자의 지침이 몰래 바뀐다.
    """
    from alture_jarvis import ui_i18n

    phrase = "학원 운영"
    dictionary = tmp_path / "ui_i18n_en.json"
    dictionary.write_text(json.dumps({phrase: "Running an academy"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ui_i18n, "_DICT_PATH", dictionary)
    ui_i18n.reload()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    app = create_app(config, start_services=False)
    try:
        ui_i18n.configure(tmp_path / "lang_state.json")
        ui_i18n.set_lang("en")
        assert ui_i18n.translate_payload({"message": phrase}) == {"message": "Running an academy"}  # 사전이 실제로 먹는다
        with TestClient(app) as client:
            client.put("/v1/about-me", headers=AUTH, json={"content": phrase})
            client.post("/v1/about-me/card", headers=AUTH,
                        json={"answers": {"work_text": phrase, "avoid_text": phrase, "sites": [phrase]}})
            view = client.get("/v1/about-me", headers=AUTH).json()
        assert phrase in view["content_raw"]
        assert view["answers"]["work_text"] == phrase and view["answers"]["avoid_text"] == phrase
        assert view["answers"]["sites"] == [phrase]
    finally:
        ui_i18n.configure(tmp_path / "lang_state_reset.json")
        monkeypatch.undo()
        ui_i18n.reload()
