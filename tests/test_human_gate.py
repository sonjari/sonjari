"""사람만 열 수 있는 문 — 넘기고, 지켜보고, 열리면 이어받는다.

자비스는 비밀번호를 다루지 않고 캡차를 풀지 않는다. 한계가 아니라 **결정**이다
(사용자님이 네이버 계정 저장을 거절하신 것과 같은 선). 그러면 그 앞에서 무엇을 하나.

지금까지는 실패를 관찰값으로 돌려주고 모델이 계속 두드리게 뒀다 — 실측에서 그 결과는
검색으로 되돌아가 헛도는 것이었다.

★ 여기서 자비스만 할 수 있는 것이 있다. 마누스는 클라우드 VM 안, GPT 는 내부
브라우저 안이라 **막혔을 때 사람이 손을 뻗어 넣을 수가 없다.** 자비스는 사용자님 눈앞의
진짜 크롬에서 돈다.

  막히면 → 무엇을 해주셔야 하는지 정확히 말하고 → **워커를 놓고**
  → 싸게 지켜보다가 → 열리면 스스로 이어간다

워커를 놓는 것이 핵심이다. 잡은 직렬로 돌기 때문에(JobRunner 스레드 하나) 기다리는
잡이 워커를 쥐면 그동안 다른 요청이 전부 멈춘다.
"""

from __future__ import annotations

import time
from typing import Any

from alture_jarvis.gate_watcher import HumanGateWatcher
from alture_jarvis.human_gate import describe, gate_evidence, is_cleared, is_human_gate
from alture_jarvis.models import JobStatus


# ── 어떤 것이 사람 몫인가 ────────────────────────────────────────────────────
def test_only_the_doors_a_person_must_open_count() -> None:
    assert is_human_gate("login_required") is True
    assert is_human_gate("bot_check") is True
    # 이건 자비스가 스스로 회복한다. 사람을 부르면 잦아져서 진짜일 때 무시된다.
    assert is_human_gate("browser_stuck") is False
    assert is_human_gate("change_not_verified") is False


# ── 무엇을·어디서·어디까지 ──────────────────────────────────────────────────
def test_the_ask_says_what_where_and_how_far_we_got() -> None:
    """예전 문구는 "확인해 주세요"가 전부였다. 그러면 사람은 창을 찾다 포기한다."""
    note = describe("login_required", "https://www.wishket.com/login", 3, 7)
    assert "로그인" in note
    assert "wishket.com/login" in note          # 어디를 봐야 하는지
    assert "3/7" in note                        # 지금 어디까지 했는지
    assert "이어서" in note                      # 하고 나면 어떻게 되는지
    assert "로그인 상태 유지" in note             # 재발을 막는 조작


# ── 문이 열렸는지 ────────────────────────────────────────────────────────────
def test_a_naver_login_is_cleared_by_the_cookie() -> None:
    gate = {"code": "login_required", "url": "https://nid.naver.com/login"}
    assert is_cleared(gate, {"known": True, "naver_signed_in": True, "url": "x"}) is True
    assert is_cleared(gate, {"known": True, "naver_signed_in": False, "url": "x"}) is False


def test_leaving_the_blocked_page_counts_as_cleared() -> None:
    """로그인에 성공하면 사이트가 다른 곳으로 보낸다. 그게 신호다."""
    gate = {"code": "login_required", "url": "https://www.wishket.com/login"}
    assert is_cleared(gate, {"known": True, "url": "https://www.wishket.com/project/"}) is True


def test_still_sitting_on_a_login_page_is_not_cleared() -> None:
    gate = {"code": "login_required", "url": "https://www.wishket.com/login"}
    for still in ("https://www.wishket.com/login", "https://www.wishket.com/accounts/signin"):
        assert is_cleared(gate, {"known": True, "url": still}) is False, still


def test_not_knowing_is_never_treated_as_cleared() -> None:
    """잘못 열렸다고 판단해 재개하면 막힌 화면에서 다시 헛돈다 — 기다리는 것보다 나쁘다."""
    gate = {"code": "bot_check", "url": "https://www.google.com/sorry/index"}
    assert is_cleared(gate, {"known": False}) is False


def test_a_captcha_page_is_not_cleared_by_moving_to_another_captcha() -> None:
    gate = {"code": "bot_check", "url": "https://www.google.com/sorry/index"}
    assert is_cleared(gate, {"known": True, "url": "https://www.google.com/sorry/other"}) is False


def test_an_unrelated_clean_site_cannot_clear_another_sites_gate() -> None:
    """여러 작업을 지켜볼 때 현재 탭 하나로 모든 문을 열었다고 하면 안 된다."""
    evidence = gate_evidence(
        "login_required",
        "https://www.wishket.com/login",
        {
            "known": True,
            "url": "https://www.wishket.com/login",
            "wall_url": "https://accounts.google.com/signin",
            "password_fields": 1,
            "captcha": False,
        },
    )
    gate = {"code": "login_required", "url": "https://www.wishket.com/login", **evidence}

    assert not is_cleared(
        gate,
        {
            "known": True,
            "url": "https://www.saramin.co.kr/zf_user/",
            "password_fields": 0,
            "captcha": False,
        },
    )
    assert is_cleared(
        gate,
        {
            "known": True,
            "url": "https://www.wishket.com/project/",
            "password_fields": 0,
            "captcha": False,
        },
    )


# ── 지켜보다 이어 붙이기 ─────────────────────────────────────────────────────
class _Store:
    def __init__(self, checkpoint: dict[str, Any] | None) -> None:
        self._checkpoint = checkpoint

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        del limit
        return [{"id": "job-1", "status": JobStatus.WAITING_CONTINUATION.value, "updated_at": 0}]

    def get_agent_checkpoint(self, job_id: str) -> dict[str, Any] | None:
        del job_id
        return self._checkpoint


class _Agent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def continue_job(self, job_id: str, action: str, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append((job_id, action))
        return {"ok": True}


class _Browser:
    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state
        self.gates: list[dict[str, Any]] = []

    def gate_state(self, gate: dict[str, Any] | None = None) -> dict[str, Any]:
        self.gates.append(dict(gate or {}))
        return self._state


class _Events:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def publish(self, name: str, payload: dict[str, Any]) -> None:
        self.sent.append((name, payload))


def _watcher(checkpoint: dict[str, Any] | None, state: dict[str, Any], **kwargs: Any):
    agent = _Agent()
    watcher = HumanGateWatcher(
        _Store(checkpoint), _Browser(state), agent, _Events(), **kwargs
    )
    return watcher, agent


def _gate_now() -> dict[str, Any]:
    """방금 막힌 문. `gate_since` 는 실제 시각이라야 포기 타이머가 정상 동작한다 —
    처음에 1970년 값을 넣었더니 첫 tick 에서 바로 포기해 버렸다."""
    return {
        "gate_code": "login_required",
        "gate_url": "https://www.wishket.com/login",
        "gate_since": time.time(),
    }


def test_opening_the_door_resumes_the_job_with_no_one_asking() -> None:
    watcher, agent = _watcher(_gate_now(), {"known": True, "url": "https://www.wishket.com/project/"})
    assert watcher.tick() == 1
    assert agent.calls == [("job-1", "continue_task")]


def test_the_watcher_reopens_the_tab_named_by_the_checkpoint() -> None:
    checkpoint = {
        **_gate_now(),
        "gate_evidence": {
            "hosts": ["wishket.com"],
            "wall_url": "https://accounts.google.com/signin",
        },
    }
    watcher, _agent = _watcher(
        checkpoint,
        {"known": True, "url": "https://www.wishket.com/project/"},
    )

    watcher.tick()

    assert watcher.browser.gates[0]["url"] == "https://www.wishket.com/login"
    assert watcher.browser.gates[0]["hosts"] == ["wishket.com"]


def test_the_same_gate_is_claimed_for_resume_only_once() -> None:
    watcher, agent = _watcher(
        _gate_now(), {"known": True, "url": "https://www.wishket.com/project/"}
    )

    assert watcher.tick() == 1
    assert watcher.tick() == 0
    assert agent.calls == [("job-1", "continue_task")]


def test_a_door_still_shut_leaves_the_job_alone() -> None:
    watcher, agent = _watcher(_gate_now(), {"known": True, "url": "https://www.wishket.com/login"})
    assert watcher.tick() == 0
    assert agent.calls == []


def test_waiting_forever_is_worse_than_a_partial_answer() -> None:
    """사용자님이 자리를 비우셨을 수도 있다. 영영 매달려 있는 작업이 제일 나쁘다."""
    watcher, agent = _watcher(
        _gate_now(), {"known": True, "url": "https://www.wishket.com/login"}, give_up_sec=0.0
    )
    watcher.tick()
    assert agent.calls == [("job-1", "finish")]


def test_jobs_waiting_for_something_else_are_not_touched() -> None:
    """시간 예산으로 멈춘 잡까지 이 감시자가 건드리면 안 된다."""
    watcher, agent = _watcher({"lease_sec": 180}, {"known": True, "url": "https://x.com"})
    assert watcher.tick() == 0
    assert agent.calls == []


# ── 어디가 아픈지 세고, 반복되면 그 자리에서 레시피를 제안한다 ────────────────
#
# 레시피는 **자율이 저절로 늘어나는 유일한 축**이다 — 사람이 한 번 뚫으면 다음부터
# 안 막힌다. 그런데 recipes/ 에는 naver_blog 하나뿐이다. 무엇을 쓸지 모르기 때문이고,
# 모르는 이유는 어디서 아픈지 아무도 안 세고 있었기 때문이다.
#
# ★ 제안 시점이 핵심이다. 나중에 목록 보고 고르라고 하면 아무도 안 본다. 막힌 그
# 순간에 말해야 한다 — 사용자님이 그 화면 앞에 계시고, 방금 직접 뚫으셨을 때가
# 셀렉터를 확인하기에 가장 좋은 순간이다.

from alture_jarvis.human_gate import RECIPE_SUGGEST_AFTER, host_of, suggest_recipe


def test_the_host_is_pulled_from_the_blocked_url() -> None:
    assert host_of("https://www.wishket.com/login?next=/project/") == "www.wishket.com"
    assert host_of("") == ""


def test_one_block_is_an_accident_and_says_nothing() -> None:
    assert suggest_recipe("www.wishket.com", 1) == ""
    assert suggest_recipe("www.wishket.com", RECIPE_SUGGEST_AFTER - 1) == ""


def test_the_third_block_asks_to_write_a_recipe() -> None:
    """한 번은 사고, 두 번은 우연, 세 번이면 앞으로도 계속 막는다."""
    note = suggest_recipe("kmong.com", RECIPE_SUGGEST_AFTER)
    assert "kmong.com" in note
    assert "3번째" in note
    assert "레시피" in note
    assert "지금 화면이 열려 있을 때" in note, "짐작으로 만들라고 하면 안 된다"
    # 예전에는 "레시피 만들자고 말씀해 주세요"였다. 그때 자비스에게는 만들 손이
    # 없었다(도구가 보기·실행 둘뿐). 시켜도 못 하는 것을 시켜 달라고 한 셈이다.
    # 이제 site_draft_recipe 로 초안까지는 자기가 쓴다 — 부탁이 아니라 제안이어야 한다.
    assert "초안" in note


def test_the_ledger_counts_per_site_and_reason() -> None:
    import tempfile
    from pathlib import Path

    from alture_jarvis.jobs import JobStore

    store = JobStore(Path(tempfile.mkdtemp()) / "jobs.db")
    assert store.note_site_friction(host="kmong.com", code="login_required") == 1
    assert store.note_site_friction(host="kmong.com", code="login_required") == 2
    # 같은 사이트라도 막힌 이유가 다르면 따로 센다 — 처방이 다르기 때문이다.
    assert store.note_site_friction(host="kmong.com", code="bot_check") == 1
    assert store.note_site_friction(host="wishket.com", code="login_required") == 1

    rows = store.site_friction()
    assert rows[0]["host"] == "kmong.com" and rows[0]["hits"] == 2, "아픈 순서대로 와야 한다"
    assert len(rows) == 3


def test_the_ask_points_at_the_window_we_bring_forward_in_plain_words() -> None:
    """2026-09-18: 크롬은 평소 뒤에 떠 있고 넘길 때도 앞으로 안 올린다 — 작업 표시줄 아이콘을 가리키고, 못 찾으면 누를 버튼을 알려 드린다."""
    bot = describe("bot_check", "https://www.coupang.com/", 2, 5)
    assert "사람인지 확인하는 화면" in bot and "작업 표시줄" in bot and "앞으로" not in bot
    assert "크롬 창 보기" in bot and "봇" not in bot, "익숙하지 않은 분이 읽는 말이다"
    login = describe("login_required", "https://nid.naver.com/login", 1, 3)
    assert "작업 표시줄" in login and "크롬 창 보기" in login


def test_handing_over_brings_the_browser_forward(monkeypatch) -> None:
    from alture_jarvis import agent as agent_module

    source = open(agent_module.__file__, encoding="utf-8").read().replace("\r\n", "\n")
    start = source.index("    def _checkpoint_human_gate(")
    body = source[start:source.index("\n    @staticmethod", start)]
    assert "present_for_human" in body, "사람 문에서 크롬 창을 찾기 쉽게 해 둬야 한다"
    assert "activate=False" in body, "온텔릭 스스로 멈출 때는 크롬을 앞으로 올리면 안 된다 — 사람의 작업 흐름이 끊긴다"


def test_only_the_show_button_brings_chrome_forward() -> None:
    from alture_jarvis import api as api_module

    source = open(api_module.__file__, encoding="utf-8").read()
    assert "present_for_human(activate=True)" in source, "사람이 「크롬 창 보기」를 눌렀을 때만 앞으로"


def test_in_stage_mode_the_ask_points_at_the_stage_not_the_taskbar() -> None:
    """2026-09-26 브라우저 무대: 크롬은 화면 밖이다 — 할 곳은 온텔릭 창 안의 브라우저 화면."""
    for code in ("login_required", "bot_check", "payment_required"):
        note = describe(code, "https://nid.naver.com/login", 1, 3, stage=True)
        assert "Sonjari 창의 브라우저 화면" in note and "작업 표시줄" not in note, code
        assert "크롬 창 보기" in note and "이어서" in note, code


def test_a_cleared_gate_hands_the_stage_back_before_resuming() -> None:
    """로그인을 끝낸 사람이 「돌려주기」를 따로 안 눌러도 이어 붙인 잡이 바로 움직인다."""
    from types import SimpleNamespace

    from alture_jarvis.gate_watcher import HumanGateWatcher

    order: list[str] = []
    view = SimpleNamespace(human_in_control=lambda: True,
                           release_control=lambda reason: order.append(f"release:{reason}"))
    watcher = HumanGateWatcher.__new__(HumanGateWatcher)
    watcher.browser = SimpleNamespace(live_view=view)
    watcher.agent = SimpleNamespace(continue_job=lambda job_id, action, reason: order.append(f"continue:{reason}"))
    watcher.events = SimpleNamespace(publish=lambda *_a, **_k: None)
    assert watcher._resume({"job_id": "j", "code": "login_required"}, "gate_cleared", "continue_task")
    assert order == ["release:gate_cleared", "continue:gate_cleared"]
    order.clear()
    watcher._resume({"job_id": "j", "code": "login_required"}, "gate_timeout", "finish")
    assert order == ["continue:gate_timeout"], "기다리다 포기할 때는 사람 손을 빼앗지 않는다"
