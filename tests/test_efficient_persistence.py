"""끈기는 **다시 볼 수 있어야** 생기고, **다음 수를 알아야** 효율이 된다.

## 사용자님이 쓰면서 잡은 것 (2026-08-15)

    "자비스 끈기가 없고 되돌리기가 잘 안 되노. 결국은 잘하는데 답답한 부분이 있어."

기록을 뒤지니 포기한 것이 아니었다. 사람인 공고 찾기 16걸음의 **마지막 다섯 걸음이
전부 차단**이었다:

      7 browser_snapshot     ok
    ✗ 8 browser_snapshot     duplicate_action_blocked
     10 browser_click        ok            <- 화면이 진짜로 바뀌었는데도
    ✗12 browser_snapshot     duplicate_action_blocked
    ✗13 ui_find_target       duplicate_action_blocked
    ✗14 browser_snapshot     duplicate_action_blocked
    ✗16 browser_snapshot     duplicate_action_blocked

**눈을 가린 채로 계속 하라고 시킨 것이다.** 그리고 그 앞에는 같은 실패를 두 번 한
자리가 있었다 — `browser_fill` 이 "Element is not an <input>" 을 두 번 냈다.
플레이라이트 원문은 사람에게는 정확하지만 모델에게는 **다음 수가 없다.**

그래서 셋을 건다: 다시 볼 수 있게 · 다음 수를 알려주게 · 채운 것은 되돌릴 수 있게.
"""

from __future__ import annotations

from alture_jarvis.agent import BrowserAgent, _world_version


def _step(tool: str, **evidence) -> dict:
    return {"tool": tool, "ok": True, "evidence": {"url": "https://x.test/form", **evidence}}


def _print(steps, tool, arguments=None):
    return BrowserAgent._fingerprint(tool, arguments or {}, steps)


# ── ① 보는 것은 되풀이가 아니다 ──────────────────────────────────────────────


def test_looking_again_after_a_click_is_a_new_action() -> None:
    """★ 이 시험이 '끈기' 의 전부다.

    누르면 화면이 바뀐다. 바뀐 화면을 다시 보는 것은 **일 그 자체**이지
    되풀이가 아니다. 폼 작업은 보기→채우기→보기→누르기→보기 로 돌아간다.
    """
    before = [_step("browser_open"), _step("browser_snapshot")]
    after = before + [_step("browser_click")]

    assert _print(before, "browser_snapshot") != _print(after, "browser_snapshot")


def test_looking_twice_with_nothing_in_between_is_still_repetition() -> None:
    """막자는 취지는 그대로다 — 아무것도 안 하고 또 보는 것은 진짜 되풀이다."""
    once = [_step("browser_open"), _step("browser_snapshot")]
    twice = once + [_step("browser_snapshot")]

    assert _print(once, "browser_snapshot") == _print(twice, "browser_snapshot")


def test_scrolling_counts_as_changing_what_can_be_seen() -> None:
    """스크롤하면 보이는 것이 달라진다. 다시 보는 것이 맞다."""
    before = [_step("browser_open")]
    after = before + [_step("browser_scroll")]

    assert _print(before, "browser_snapshot") != _print(after, "browser_snapshot")


def test_the_world_counter_ignores_pure_looking() -> None:
    steps = [
        _step("browser_open"),        # 1
        _step("browser_snapshot"),    # (보기)
        _step("ui_find_target"),      # (보기)
        _step("browser_click"),       # 2
        _step("browser_read"),        # (보기)
    ]
    assert _world_version(steps) == 2


def test_acting_tools_are_still_judged_the_old_way() -> None:
    """누르기·채우기까지 풀어 주면 진짜 되풀이가 통과한다.

    같은 화면에서 같은 ref 를 또 누르는 것은 막아야 한다 — 두 번 제출이 된다.
    """
    once = [_step("browser_open"), _step("browser_click")]
    twice = once + [_step("browser_snapshot")]  # 사이에 보기가 끼어도

    assert _print(once, "browser_click", {"ref": "j9"}) == _print(twice, "browser_click", {"ref": "j9"})


# ── ② 실패는 다음 수를 알려 준다 ────────────────────────────────────────────


class _NotAnInput:
    def evaluate(self, _script):
        return "DIV"


def test_a_div_pretending_to_be_a_field_says_what_to_do_instead() -> None:
    from alture_jarvis.browser import BrowserWorker

    message = BrowserWorker._fill_failure_hint(
        _NotAnInput(), Exception("Locator.fill: Error: Element is not an <input>, <textarea>")
    )
    assert "fill_target_is_not_an_input" in message
    assert "browser_click" in message and "browser_pick_suggestion" in message
    # ★ 같은 수를 다시 두지 말라고 명시한다. 실측에서 그걸 두 번 했다.
    assert "다시 부르지 마라" in message


def test_a_hidden_field_is_told_to_scroll_not_to_retry() -> None:
    from alture_jarvis.browser import BrowserWorker

    message = BrowserWorker._fill_failure_hint(
        _NotAnInput(), Exception("Element is not visible")
    )
    assert "fill_target_not_visible" in message
    assert "browser_scroll" in message


# ── ③ 채운 것은 되돌릴 수 있다 ──────────────────────────────────────────────


def test_filling_leaves_a_way_back_to_the_old_value() -> None:
    from alture_jarvis.browser import BrowserTools

    handle = BrowserTools._fill_handle(
        {"action": "filled", "undo_ref": "j12", "previous_value": "예전 값",
         "url": "https://x.test/form"}
    )
    assert handle == {"ref": "j12", "previous_value": "예전 값", "url": "https://x.test/form"}


def test_no_way_back_when_the_old_value_could_not_be_read() -> None:
    """무엇으로 되돌릴지 모르면 안 내준다 — 눌렀는데 아무 일도 안 하는 버튼이 제일 나쁘다."""
    from alture_jarvis.browser import BrowserTools

    assert BrowserTools._fill_handle({"action": "filled", "undo_ref": "j12"}) is None
    assert BrowserTools._fill_handle({"action": "filled", "previous_value": "x"}) is None


def test_only_what_we_can_actually_undo_gets_an_automatic_inverse() -> None:
    """누르기는 무엇이 일어나는지 **일반적으로는** 알 수 없다.

    토글이면 한 번 더 누르면 되지만 제출이면 **두 번 낸다.** 모르면서 되돌리는
    척하는 것이 제일 나쁘다.

    ★ 그런데 **표준이 알려 주는 경우가 있다**(2026-08-16). `aria-pressed`·
    `aria-checked` 는 "누르면 두 상태를 오가는 버튼"이라는 뜻이 정해져 있어서,
    그것이 뒤집혔다면 같은 것을 다시 누르는 것이 역동작이라고 말할 근거가 있다.
    그래서 `browser_click` 에도 자동 되돌리기가 붙었다 — 다만 **그 경우에만**
    손잡이가 나온다(`_toggle_state` 가 표준 속성만 본다).

    되돌릴 수 없는 제출(`browser_click_confirmed`)은 여전히 **수동**이다.
    거기 붙은 것은 되돌리기가 아니라 **찾아갈 길**이다(13-3) — 되돌리려면 먼저
    찾을 수 있어야 한다는 뜻이지, 자비스가 되돌린다는 뜻이 아니다. 둘을 섞으면 안 된다.
    """
    from alture_jarvis.browser import BrowserTools

    class _Tools:
        worker = None

    inverses = BrowserTools._inverses(_Tools())
    automatic = {name for name, spec in inverses.items() if spec.undo is not None}
    assert automatic == {"browser_fill", "browser_click"}
    assert inverses["browser_click_confirmed"].undo is None


# ── ④ 뒤로 가기가 판을 죽이지 않는다 ─────────────────────────────────────────


class _SlowBack:
    """뒤로 가기가 안 끝나는 사이트. 실측에서 30초를 다 쓰고 판이 끝났다."""

    url = "https://x.test/item"

    def go_back(self, **kwargs):
        raise TimeoutError("Timeout 8000ms exceeded")


def test_a_slow_back_does_not_kill_the_run(tmp_path) -> None:
    """뒤로 가기는 **되돌아오는 길이지 목적이 아니다.**

    오래 걸리면 그만두고 다른 길을 알려 주면 된다. 예외로 던지면 rank 로
    다음 자료를 여는 길까지 같이 닫힌다 — `_last_results` 는 아직 살아 있는데.
    """
    from alture_jarvis.browser import BrowserWorker

    worker = BrowserWorker.__new__(BrowserWorker)
    worker._last_results = [{"rank": 1, "visited": True}, {"rank": 2}, {"rank": 3}]
    worker._page = None          # `_evidence` 가 화면을 못 읽어도 돌아야 한다
    worker._last_dialog = None

    out = BrowserWorker._back(worker, _SlowBack(), {})

    assert out["action"] == "back_timed_out", out
    assert "browser_open_result" in str(out.get("instruction") or "")
    # 남은 순위를 그대로 알려 준다 — 이게 다음 수다.
    assert out.get("remaining") == [2, 3]


# ── ⑤ 같은 답을 또 받으면 "이제 써라" 고 말한다 ──────────────────────────────


def _vision():
    from alture_jarvis.ui_vision import UiVision

    tools = UiVision.__new__(UiVision)
    tools._recent_finds = {}
    # 되묻기 판정은 **방금 그린 화면의 주소**로 한다(따로 물으면 왕복이 는다).
    tools._last_seen_url = "https://x.test/form"
    return tools


def test_the_first_answer_is_given_plainly() -> None:
    tools = _vision()
    out = tools._note_if_asked_again("검색창", {"ref": "j6"})
    assert "asked_before" not in out


def test_asking_the_same_thing_again_is_told_to_act_instead(monkeypatch) -> None:
    """★ 되묻기를 잡는 자리.

    실측: 여섯 가지 표현으로 물어 여섯 번 같은 ref 를 받고 **한 번도 안 채웠다.**
    되풀이 차단은 이걸 못 잡는다 — goal 이 매번 달라 지문이 갈린다.
    """
    tools = _vision()
    tools._note_if_asked_again("검색창", {"ref": "j6"})
    out = tools._note_if_asked_again("검색어 입력란", {"ref": "j6"})

    assert out["asked_before"] == 2
    note = out["instruction"]
    assert "답은 매번 j6 로 같다" in note
    # 다음 수를 **이름까지 대서** 준다. "다시 찾지 마라"만 하면 무엇을 할지 모른다.
    assert "browser_fill(ref=j6)" in note and "browser_click(ref=j6)" in note


def test_a_different_element_is_not_a_repeat() -> None:
    """다른 것을 찾은 것은 되묻기가 아니다 — 화면이 바뀌면 답도 바뀐다."""
    tools = _vision()
    tools._note_if_asked_again("검색창", {"ref": "j6"})
    out = tools._note_if_asked_again("검색 버튼", {"ref": "j30"})
    assert "asked_before" not in out


def test_a_miss_is_left_alone() -> None:
    """못 찾은 것은 되묻기와 다른 얘기다. 그때는 다른 말로 찾아보는 게 맞다."""
    tools = _vision()
    tools._note_if_asked_again("검색창", {"found": False})
    out = tools._note_if_asked_again("검색창", {"found": False})
    assert "asked_before" not in out
