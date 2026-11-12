"""11-11 측정 스위치 JARVIS_AGENT_PAGE_VIEW — 번호 붙인 지금 화면을 일회용으로 붙인다. 양방향."""
from __future__ import annotations

import base64

from alture_jarvis.page_view import build_page_view, last_browser_tool


def test_only_after_a_browser_step() -> None:
    assert last_browser_tool([{"role": "tool", "tool_name": "browser_read", "content": "x"}]) == "browser_read"
    assert last_browser_tool([{"role": "tool", "tool_name": "local_write_document", "content": "x"}]) == ""
    assert last_browser_tool([{"role": "user", "content": "x"}]) == ""
    assert last_browser_tool([]) == ""
    # 끝에 하네스 안내가 붙어도 브라우저 걸음으로 본다 · 모델 말 뒤에 도구가 없으면 아니다
    assert last_browser_tool([{"role": "tool", "tool_name": "browser_open", "content": "x"}, {"role": "user", "content": "[시스템] …"}]) == "browser_open"
    assert last_browser_tool([{"role": "tool", "tool_name": "browser_open", "content": "x"}, {"role": "assistant", "content": "y"}, {"role": "user", "content": "z"}]) == ""


def test_builds_image_and_numbered_list(tmp_path) -> None:
    shot = tmp_path / "a.png"
    shot.write_bytes(b"\x89PNG fake")
    view = build_page_view({"path": str(shot), "candidates": [
        {"ref": "j12", "role": "link", "name": "  갤럭시   버즈3 "}, {"ref": "j7", "role": "button", "name": "검색"}]})
    assert view is not None and view["role"] == "user"
    assert base64.b64decode(view["images"][0]) == b"\x89PNG fake"
    assert "12 = j12 · link · 갤럭시 버즈3" in view["content"] and "7 = j7 · button · 검색" in view["content"]
    # 11-11: 안내 글이 실제 번호표 꼴을 가르친다(예전 「e12」 는 누르기 도구가 받지 않는 꼴이었다) · 순위와 헷갈리지 않게.
    assert "j12" in view["content"].splitlines()[0] and "e12" not in view["content"] and "rank" in view["content"]
    assert "사용자가 한 말 아님" in view["content"]


def test_no_picture_no_message(tmp_path) -> None:
    assert build_page_view({"path": "", "candidates": [{"ref": "e1"}]}) is None
    assert build_page_view({"path": str(tmp_path / "missing.png")}) is None


def test_switch_is_off_by_default(monkeypatch) -> None:
    from alture_jarvis import config as cfg

    assert cfg.JarvisConfig().agent_page_view is False
    monkeypatch.setattr(cfg, "_env", lambda name, default="": "1" if name == "JARVIS_AGENT_PAGE_VIEW" else default)
    assert cfg.JarvisConfig.from_env().agent_page_view is True


def test_agent_attaches_only_when_model_reads_pictures(tmp_path) -> None:
    from types import SimpleNamespace

    from alture_jarvis.agent import BrowserAgent

    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    calls: list[str] = []

    class Browser:
        def execute(self, name, arguments=None):
            calls.append(name)
            return {"path": str(shot), "candidates": [{"ref": "e3", "role": "link", "name": "상품"}]}

    sees = {"value": True}
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.browser = Browser()
    agent.ollama = SimpleNamespace(reads_pictures=lambda role: sees["value"])
    agent.store = SimpleNamespace(add_audit=lambda *a, **k: None)
    after_browser = [{"role": "tool", "tool_name": "browser_open", "content": "{}"}]

    view = agent._page_view(after_browser, job_id="j", model_role="chat")
    assert view is not None and view["images"] and "_image_bytes" not in view and calls == ["browser_annotate"]

    sees["value"] = False  # 글 전용 모델에는 안 붙이고 찍지도 않는다
    assert agent._page_view(after_browser, job_id="j", model_role="chat") is None and calls == ["browser_annotate"]

    sees["value"] = True  # 브라우저 걸음이 아니면 안 찍는다
    assert agent._page_view([{"role": "tool", "tool_name": "local_read_file", "content": "{}"}], job_id="j", model_role="chat") is None
    assert calls == ["browser_annotate"]


# ── 11-11 오후: 그림 켬 판 9개 중 5개가 창을 넘어 죽었다. 사진 base64(약 10만 자)를 「보낸 글자」로 세서 예산이
#    3.7만 자 → 14만~19만 자로 넓어진 탓(노트북 판 5dc29c5e: 보낸 글자 16,945 → 123,999 · 토큰 11,272 → 13,600).


def test_picture_is_not_counted_as_text() -> None:
    from alture_jarvis.transcript import transcript_chars

    plain = [{"role": "user", "content": "가격 표"}]
    with_picture = [{"role": "user", "content": "가격 표", "images": ["A" * 100_000]}]
    assert transcript_chars(with_picture) == transcript_chars(plain)
    # 하면 안 되는 것: 글 칸까지 빼면 안 된다
    assert transcript_chars([{"role": "user", "content": "가" * 500}]) > transcript_chars(plain)


def test_budget_meter_leaves_page_view_out_of_chars() -> None:
    from types import SimpleNamespace

    from alture_jarvis.agent import BrowserAgent
    from alture_jarvis.transcript import transcript_chars

    talk = [{"role": "user", "content": "버즈 값 찾아"}, {"role": "tool", "tool_name": "browser_open", "content": "본문" * 300}]
    view = {"role": "user", "content": "[지금 화면]\n12 = e12 · link · 상품" * 20, "images": ["B" * 90_000], "_page_view": True}
    holder = SimpleNamespace()
    key = ("job", "chat", 0)
    BrowserAgent._note_prompt_size(holder, key, [*talk, view], {"_metrics": {"prompt_eval_count": 13_600}})
    chars, tokens = holder._prompt_meter[key]
    assert chars == transcript_chars(talk) and tokens == 13_600
    # 화면이 없는 판은 예전 그대로
    BrowserAgent._note_prompt_size(holder, key, talk, {"_metrics": {"prompt_eval_count": 11_272}})
    assert holder._prompt_meter[key] == (transcript_chars(talk), 11_272)


def test_real_numbers_no_longer_widen_past_the_window() -> None:
    """노트북 판 숫자 그대로: 고치기 전 셈은 14만 자를 줬고, 고친 셈은 받은 예산 근처에 머문다."""
    from alture_jarvis.transcript_policy import window_fitted_budget

    before = window_fitted_budget(36_864, num_ctx=32_768, sent_chars=123_999, prompt_tokens=13_600, widen=True)
    after = window_fitted_budget(36_864, num_ctx=32_768, sent_chars=16_945 + 1_500, prompt_tokens=13_600, widen=True)
    assert before > 120_000
    assert after < 40_000


def test_loose_refs_become_the_element_ref_the_click_tool_takes() -> None:
    """11-11 노트북 그림 켬: 그림 속 「12」 · 안내 글의 「e12」 꼴로 누르면 다섯 번 다 invalid_element_ref 였다."""
    from alture_jarvis.browser import _coerce_ref

    for loose in ("12", "e12", "E12", " j12 ", "#12", "ref12", 12):
        assert _coerce_ref({"ref": loose})["ref"] == "j12", loose
    # 하면 안 되는 것: 엉터리는 그대로 두어 원래 검사가 막게 한다 · 다른 칸은 안 건드린다 · 참거짓은 숫자가 아니다
    for bad in ("x12", "j", "12; drop", "j1234567", "123456", True):
        assert _coerce_ref({"ref": bad})["ref"] == bad
    assert _coerce_ref({"rank": "12"}) == {"rank": "12"}


def test_a_failed_step_is_carried_to_the_top_of_the_picture(tmp_path) -> None:
    """11-11 노트북: 멈춘 4칸 모두 같은 실패를 5번 — 그림이 맨 끝에 붙어 오류를 덮었다. 실패 뒤 그림은 오류를 윗줄에 둔다."""
    import json as _json

    from alture_jarvis.page_view import last_browser_failure

    failed = {"role": "tool", "tool_name": "browser_click", "content": _json.dumps({"ok": False, "error": "invalid_element_ref"})}
    assert last_browser_failure([failed]) == ("browser_click", "invalid_element_ref")
    assert last_browser_failure([failed, {"role": "user", "content": "[시스템] …"}]) == ("browser_click", "invalid_element_ref")
    cut = {"role": "tool", "tool_name": "browser_open", "content": '{"ok": false, "error": "page_not_found:search.daum.net/x — 그런' + "가" * 3000}
    assert last_browser_failure([cut])[0] == "browser_open", "길어서 잘린 결과도 머리로 읽는다"
    # 하면 안 되는 것: 성공 · 브라우저 아닌 걸음 · 모델이 그 뒤에 말한 것
    assert last_browser_failure([{"role": "tool", "tool_name": "browser_click", "content": '{"ok": true}'}]) == ("", "")
    assert last_browser_failure([{"role": "tool", "tool_name": "local_read_file", "content": '{"ok": false, "error": "x"}'}]) == ("", "")
    assert last_browser_failure([failed, {"role": "assistant", "content": "다시"}]) == ("", "")

    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNG fake")
    observed = {"path": str(shot), "candidates": [{"ref": "j3", "role": "link", "name": "상품"}]}
    view = build_page_view(observed, failure=("browser_click", "invalid_element_ref"))
    first = view["content"].splitlines()[0]
    assert "browser_click" in first and "invalid_element_ref" in first and "다시 하지 말고" in first
    assert "실패" not in build_page_view(observed)["content"], "성공 뒤 그림에는 안 붙는다"
