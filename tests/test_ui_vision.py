"""The vision picker: what it must never do.

Every test here is about a way this design fails *quietly* if it is built the
obvious way -- by asking a model where to click. The rule the whole module
exists to enforce is that an uncertain answer stops, because the alternative
(guessing) eventually presses 확인 on a dialog nobody read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ui_vision import UiVision


class FakeWorker:
    """Stands in for the Playwright worker: records what it was asked to do."""

    def __init__(self, candidates: list[dict[str, Any]], shot: Path | None = None) -> None:
        self.candidates = candidates
        self.shot = shot
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, action: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((action, dict(arguments or {})))
        if action == "browser_annotate":
            return {
                "action": "annotated",
                "path": str(self.shot or ""),
                "candidates": self.candidates,
                "candidate_count": len(self.candidates),
            }
        if action == "browser_find":
            # 2026-10-07: 그림에 묻기 전에 페이지 전체에서 이름으로 한 번 찾는다(읽기 전용 조회). 이 가짜 화면에는 맞는 이름이 없다.
            self.calls.pop()
            self.lookups = getattr(self, "lookups", 0) + 1
            return {"action": "found", "matches": [], "match_count": 0}
        if action == "browser_click":
            return {"action": "clicked", "ref": (arguments or {}).get("ref")}
        if action == "browser_screenshot":
            return {"action": "screenshot", "path": str(self.shot or "")}
        if action == "browser_scroll":
            # 2026-08-13: 못 찾으면 **내려서 다시 본다**. 사람은 한 화면 보고
            # "이 페이지엔 없네요"라고 하지 않는다(실측: scroll 을 쓴 잡 6%).
            # 이 가짜 화면은 내려도 그대로다 — 그래서 결국 못 찾고 끝난다.
            return {"action": "scrolled"}
        raise AssertionError(f"unexpected action {action}")


class FakeOllama:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen: dict[str, Any] = {}

    def chat_message(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        self.seen = {"prompt": prompt, **kwargs}
        return {"content": self.reply}


def _candidates() -> list[dict[str, Any]]:
    return [
        {"ref": "j1", "name": "로그인", "role": "button", "frame": "main"},
        {"ref": "j2", "name": "글쓰기", "role": "button", "frame": "mainFrame"},
        {"ref": "j3", "name": "", "role": "textbox", "frame": "mainFrame"},
    ]


def _vision(tmp_path: Path, reply: str, *, candidates: list[dict[str, Any]] | None = None):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"PNG-bytes")
    worker = FakeWorker(_candidates() if candidates is None else candidates, shot)
    client = FakeOllama(reply)
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out"
    )
    return UiVision(config, worker, client), worker, client


def test_a_plain_number_resolves_to_the_matching_ref(tmp_path: Path) -> None:
    vision, _, _ = _vision(tmp_path, "2")

    result = vision.find({"goal": "글쓰기 버튼"})

    assert result["status"] == "found"
    assert result["ref"] == "j2"
    assert result["chosen"]["name"] == "글쓰기"


def test_the_number_is_read_out_of_a_lightly_dressed_up_answer(tmp_path: Path) -> None:
    # Small local models answer "2번" as often as "2". Refusing that would send
    # a correct pick to the failure path.
    vision, _, _ = _vision(tmp_path, "2번")
    assert vision.find({"goal": "글쓰기"})["ref"] == "j2"


def test_zero_means_not_on_this_screen_and_nothing_is_pressed(tmp_path: Path) -> None:
    """The escape hatch has to exist, or the model's only way to answer is to
    name something -- and it will name whatever is closest."""
    vision, worker, _ = _vision(tmp_path, "0")

    result = vision.click({"goal": "결제하기 버튼"})

    assert result["status"] == "not_found"
    # ★ 2026-08-13: 없다고 말하기 전에 **내려서 다시 본다**. 그래도 누르지는 않는다 —
    # 이 시험이 지키는 것은 "아무것도 안 눌렀다"이지 "한 번만 봤다"가 아니다.
    assert "browser_click" not in [call[0] for call in worker.calls]
    assert [call[0] for call in worker.calls].count("browser_scroll") == 2


def test_a_sentence_with_several_numbers_is_treated_as_no_answer(tmp_path: Path) -> None:
    # "1번과 2번 중에서는 2번" -- taking the first number picks 로그인, taking the
    # last picks by luck. Both are guessing on the user's behalf.
    vision, worker, _ = _vision(tmp_path, "1번과 2번이 비슷한데 아마 2번")

    result = vision.click({"goal": "글쓰기"})

    assert result["status"] == "unclear"
    assert [call[0] for call in worker.calls] == ["browser_annotate"]


def test_prose_with_no_number_is_treated_as_no_answer(tmp_path: Path) -> None:
    vision, worker, _ = _vision(tmp_path, "글쓰기 버튼을 누르시면 됩니다")

    result = vision.click({"goal": "글쓰기"})

    assert result["status"] == "unclear"
    assert result["raw"].startswith("글쓰기 버튼을")
    assert len(worker.calls) == 1


def test_a_number_outside_the_list_is_not_resolved_to_the_nearest_one(
    tmp_path: Path,
) -> None:
    """Rounding a misread into a real target is the same guess this design
    exists to remove -- and the click would report success."""
    vision, worker, _ = _vision(tmp_path, "9")

    result = vision.click({"goal": "글쓰기"})

    assert result["status"] == "out_of_range"
    assert len(worker.calls) == 1


def test_a_found_target_is_clicked_through_its_ref_never_a_coordinate(
    tmp_path: Path,
) -> None:
    vision, worker, _ = _vision(tmp_path, "2")

    result = vision.click({"goal": "글쓰기"})

    assert result["status"] == "clicked"
    assert worker.calls[1] == ("browser_click", {"ref": "j2"})


def test_an_empty_screen_says_so_rather_than_blaming_the_model(tmp_path: Path) -> None:
    """빈 화면을 두고 모델에게 "골라 봐"라고 물으면, 못 고른 것이 모델 탓처럼 보인다.

    ★ 2026-08-13: 문구가 바뀌었다. 예전에는 첫 화면이 비면 즉시
    `ui_vision_no_candidates` 였는데, 이제는 **내려서 다시 본 뒤** 실패한다 —
    첫 화면이 비어 있고 아래에 목록이 있는 사이트가 흔하기 때문이다(스크립트가
    나중에 그리는 화면). 지키는 것은 그대로다: **모델에게 묻지 않는다.**
    """
    vision, _, client = _vision(tmp_path, "1", candidates=[])

    with pytest.raises(RuntimeError, match="ui_target_not_found"):
        vision.find({"goal": "아무거나"})

    assert client.seen == {}, "the model must not be asked about an empty screen"


def test_the_screenshot_is_actually_sent_and_thinking_is_off(tmp_path: Path) -> None:
    """gemma4 is a thinking model: without think=False the whole prediction
    budget goes into message.thinking and content comes back empty -- the trap
    recorded in 사고 I's 2026-07-14 재발 note."""
    vision, _, client = _vision(tmp_path, "2")

    vision.find({"goal": "글쓰기"})

    assert client.seen["images"], "no image means this is not vision at all"
    assert client.seen["think"] is False
    assert client.seen["temperature"] == 0.0


def test_the_prompt_lists_candidates_by_the_numbers_drawn_on_screen(
    tmp_path: Path,
) -> None:
    # The picture and the list have to agree, or the model is being asked to
    # match two different worlds.
    vision, _, client = _vision(tmp_path, "2")

    vision.find({"goal": "글쓰기"})

    prompt = client.seen["prompt"]
    assert "1. [button] 로그인" in prompt
    assert "2. [button] 글쓰기 · mainFrame" in prompt
    assert "3. [textbox] (이름 없음)" in prompt


def test_a_goal_is_required(tmp_path: Path) -> None:
    vision, _, _ = _vision(tmp_path, "1")
    with pytest.raises(ValueError, match="goal_required"):
        vision.find({"goal": "   "})


def test_a_reviewed_site_search_blocks_visual_search_box_hunting(tmp_path: Path) -> None:
    """사람인에서 이미 있는 레시피를 두고 ref를 더듬던 10걸음 회귀."""
    vision, worker, _ = _vision(tmp_path, "1")
    worker.reviewed_search_recipe = lambda: 'site_run(site="saramin", action="search_jobs")'

    with pytest.raises(RuntimeError, match="reviewed_site_search_required.*browser_site_search"):
        vision.find({"goal": "검색어 입력창"})

    assert worker.calls == [], "검색창을 그리거나 캡처하기 전에 막아야 걸음을 아낀다"


def test_a_reviewed_search_does_not_block_unrelated_visual_targets(tmp_path: Path) -> None:
    vision, worker, _ = _vision(tmp_path, "2")
    worker.reviewed_search_recipe = lambda: 'site_run(site="saramin", action="search_jobs")'

    assert vision.find({"goal": "글쓰기 버튼"})["ref"] == "j2"
    assert worker.calls[0][0] == "browser_annotate"


# ── 읽기는 모델, 판정은 코드 (2026-08-11) ──────────────────────────────────
#
# 처음엔 모델에게 "이 상태가 맞습니까?"라고 물었다. 화면 전체(441KB)로는 178초에
# 오답이었고, 그 자리만 잘라 줘도(12KB·2.6초) 여전히 틀렸다 — 답이 이렇게 무너졌다:
#   "'파이썬'이 아니라 '파이썬'이라는 글자가 아닌 '파이썬'과 유사한…"
#
# 작은 모델에게 판단은 무겁고, 판단은 지어내기 쉽다. 읽기는 다르다 — 옮겨 적는
# 일은 그림에 답이 있다. 그래서 **모델은 읽고, 코드가 판정한다.**
# 실측 1.5~2.0초 · 있는 것/없는 것 양방향 정확.
def test_the_model_reads_and_the_code_decides(tmp_path: Path) -> None:
    vision, worker, client = _vision(tmp_path, "N 파이썬")

    out = vision.verify({"claim": "검색창 확인", "ref": "j7", "expect": "파이썬"})

    assert out["verdict"] == "yes"
    assert out["saw"] == "N 파이썬", "무엇을 읽었는지가 근거로 남아야 한다"
    assert "옮겨 적는" in client.seen["system"], "모델이 받는 일은 읽기다"
    assert "판단하거나 설명하지 마라" in client.seen["system"], "판정은 코드 몫이다"


def test_what_is_not_there_is_answered_no(tmp_path: Path) -> None:
    vision, _, _ = _vision(tmp_path, "N 파이썬")

    assert vision.verify({"claim": "확인", "ref": "j7", "expect": "자바스크립트"})["verdict"] == "no"


def test_it_crops_to_the_field_when_given_a_ref(tmp_path: Path) -> None:
    """★ 화면 전체를 주면 축소돼 글자를 못 읽는다(441KB 178초 오답).
    그 칸만 자르면 12KB 2초다."""
    vision, worker, _ = _vision(tmp_path, "Ajax")

    vision.verify({"claim": "확인", "ref": "j40", "expect": "Ajax"})

    shots = [args for action, args in worker.calls if action == "browser_screenshot"]
    assert shots and shots[0].get("ref") == "j40", "ref 를 줬으면 그 자리만 찍어야 한다"


def test_without_an_expectation_it_does_not_pretend_to_judge(tmp_path: Path) -> None:
    """무엇을 확인할지 안 주면 판정하지 않는다. 읽은 것만 돌려준다."""
    vision, _, _ = _vision(tmp_path, "아무 글자")

    out = vision.verify({"claim": "확인", "ref": "j7"})
    assert out["verdict"] == "unknown" and out["saw"] == "아무 글자"


def test_the_match_ignores_spacing_but_not_more(tmp_path: Path) -> None:
    """공백·대소문자만 무시한다. 더 느슨하게 하면 없는 것을 있다고 하기 시작한다."""
    from alture_jarvis.ui_vision import _loose_contains

    assert _loose_contains("N 파 이 썬", "파이썬")
    assert _loose_contains("Save Draft", "savedraft")
    assert not _loose_contains("파이", "파이썬")
    assert not _loose_contains("", "파이썬")


def test_looking_is_free_but_clicking_is_not(tmp_path: Path) -> None:
    """보는 도구는 L0, 누르는 것만 L1 이다."""
    from alture_jarvis.events import EventBus
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.models import RiskLevel
    from alture_jarvis.tool_gateway import ToolGateway

    vision, _, _ = _vision(tmp_path, "예\n무언가 보인다")
    gateway = ToolGateway(JobStore(tmp_path / "jobs.db"), EventBus())
    vision.register(gateway)
    levels = {t["name"]: t["risk_level"] for t in gateway.list_tools()}

    assert levels["ui_verify"] == RiskLevel.L0.label()
    assert levels["ui_find_target"] == RiskLevel.L0.label()
    assert levels["ui_click_target"] == RiskLevel.L1.label()
