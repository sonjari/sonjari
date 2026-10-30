"""생각 깊이 「자동」 — 설정의 선택지이자 기본값, 그리고 깊게로 올라간 순간의 기록 (2026-10-28).

10-27 측정(24판 전부 통과): 보통이 깊게보다 코드 과제에서 크게 빨랐고 나머지는 엇갈렸다. 대표 결정: 자동(보통으로 시작해 막히면 깊게)을
어디서나 기본으로 한다. 칩이 있는 길은 칩이 이기고, 칩이 없는 길(클로드 연결 · 디스코드 · 예약)은 설정을 따른다.

여기서 지키는 것
  · 설정 `auto` + 빈 칩 = 칩 「자동」과 똑같다 (처음 보통 → 되받기 한 번 또는 실패 걸음 둘이면 끝까지 깊게)
  · 칩이 설정을 이긴다 · 옛 값(off · adaptive · always)은 그대로다
  · 설정 값을 풀지 않고 그대로 부르는 길(`_should_think(config, steps)`)이 `auto` 를 `always` 로 잘못 읽지 않는다
  · 기본값이 사는 자리(dataclass · 환경 읽기 · 설정 화면 선택지 · 사용자 저장 파일)가 서로 어긋나지 않는다
  · 올라간 순간을 판 기록 `reasoning_escalated` 에 한 번 남기고 진행 줄을 한 번 낸다 — 안 올라갔거나 자동이 아니면 아무것도 안 한다
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import test_forced_commit as base
from alture_jarvis import settings as settings_module
from alture_jarvis.agent import (
    BrowserAgent,
    _final_answer_thinks,
    _job_thinking_policy,
    _reasoning_escalated,
    _should_think,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult
from alture_jarvis.settings import SettingsService, read_user_values, validate, SettingsError

GOOD = [{"tool": "browser_open", "ok": True}, {"tool": "browser_extract", "ok": True}]
TWO_FAILED = [{"tool": "a", "ok": False}, {"tool": "b", "ok": True}, {"tool": "c", "ok": False}]


def _config(policy: str, *, enabled: bool = True) -> Any:
    return SimpleNamespace(agent_thinking_enabled=enabled, agent_thinking_policy=policy)


# ── 정책을 푸는 함수 ────────────────────────────────────────────────────────────

def test_config_auto_with_an_empty_chip_starts_at_adaptive() -> None:
    config = _config("auto")
    assert _job_thinking_policy(config, "", escalated=False) == "adaptive"
    # 걸음이 매끄러우면 중간 걸음에서는 생각하지 않는다 — 칩 「자동」과 같다.
    assert _should_think(config, GOOD, policy=_job_thinking_policy(config, "", escalated=False)) is False
    # 첫 걸음은 생각한다(보통의 규칙).
    assert _should_think(config, [], policy=_job_thinking_policy(config, "", escalated=False)) is True


def test_config_auto_climbs_to_always_after_a_pushback() -> None:
    config = _config("auto")
    escalated = _reasoning_escalated(GOOD, 1)
    assert escalated is True
    policy = _job_thinking_policy(config, "", escalated=escalated)
    assert policy == "always"
    assert _should_think(config, GOOD, policy=policy) is True


def test_config_auto_climbs_to_always_after_two_failed_steps() -> None:
    config = _config("auto")
    escalated = _reasoning_escalated(TWO_FAILED, 0)
    assert escalated is True
    assert _job_thinking_policy(config, "", escalated=escalated) == "always"
    # 실패 한 번으로는 안 올라간다.
    assert _reasoning_escalated(TWO_FAILED[:2], 0) is False


def test_an_empty_or_missing_config_value_means_auto() -> None:
    assert _job_thinking_policy(_config(""), "", escalated=False) == "adaptive"
    assert _job_thinking_policy(SimpleNamespace(agent_thinking_enabled=True), "", escalated=True) == "always"


def test_an_explicit_chip_still_beats_the_config() -> None:
    config = _config("auto")
    assert _job_thinking_policy(config, "fast", escalated=True) == "off"
    assert _job_thinking_policy(config, "normal", escalated=True) == "adaptive"
    assert _job_thinking_policy(config, "deep", escalated=False) == "always"
    # 반대쪽도: 설정이 깊게여도 칩 「자동」은 보통으로 시작한다.
    assert _job_thinking_policy(_config("always"), "auto", escalated=False) == "adaptive"
    assert _job_thinking_policy(_config("off"), "deep", escalated=False) == "always"


def test_the_old_config_values_are_unchanged() -> None:
    for old, expected in (("off", "off"), ("adaptive", "adaptive"), ("always", "always")):
        config = _config(old)
        assert _job_thinking_policy(config, "", escalated=False) == expected
        # 올라가도 옛 값은 그대로다 — 「보통」을 골랐으면 막혀도 보통이다.
        assert _job_thinking_policy(config, "", escalated=True) == expected


def test_a_raw_auto_config_is_not_read_as_always_by_accident() -> None:
    """정책을 풀지 않고 설정 값 그대로 부르는 길 — `policy != adaptive → 늘 생각` 으로 새면 자동이 깊게가 된다."""
    config = _config("auto")
    assert _should_think(config, []) is True
    assert _should_think(config, GOOD) is False, "자동 · 매끄러운 중간 걸음은 생각하지 않는다"
    assert _should_think(config, TWO_FAILED) is True, "실패가 둘 쌓였으면 깊게"
    assert _should_think(config, GOOD, artifact_focus=True) is False
    assert _should_think(_config("auto", enabled=False), []) is False


def test_the_final_answer_thinks_unless_fast() -> None:
    assert _final_answer_thinks(_config("auto")) is True
    assert _final_answer_thinks(_config("off")) is False
    assert _final_answer_thinks(_config("auto"), "off") is False
    assert _final_answer_thinks(_config("auto", enabled=False)) is False


# ── 기본값이 사는 자리 ─────────────────────────────────────────────────────────────

def test_every_place_that_holds_the_default_says_auto(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("JARVIS_AGENT_THINKING_POLICY", raising=False)
    assert JarvisConfig(runtime_root=tmp_path).agent_thinking_policy == "auto"
    assert JarvisConfig.from_env().agent_thinking_policy == "auto"
    monkeypatch.setenv("JARVIS_AGENT_THINKING_POLICY", "always")
    assert JarvisConfig.from_env().agent_thinking_policy == "always", "관리 설치의 환경 값은 그대로 이긴다"
    # 읽는 쪽 기본값(설정 객체에 칸이 없을 때)도 자동이다.
    assert _job_thinking_policy(SimpleNamespace(), "", escalated=False) == "adaptive"
    assert _final_answer_thinks(SimpleNamespace(agent_thinking_enabled=True)) is True


def test_the_settings_screen_offers_auto_and_the_backend_accepts_it() -> None:
    row = settings_module.BY_KEY["agent_thinking_policy"]
    assert row.choices[0] == "auto"
    assert set(row.choices) == {"auto", "off", "adaptive", "always"}
    assert validate("agent_thinking_policy", "auto") == "auto"
    for old in ("off", "adaptive", "always"):
        assert validate("agent_thinking_policy", old) == old
    try:
        validate("agent_thinking_policy", "whenever")
    except SettingsError:
        pass
    else:  # pragma: no cover
        raise AssertionError("모르는 값을 받으면 안 된다")


def test_settings_file_keeps_only_what_the_user_changed(tmp_path: Path) -> None:
    """새 기본값(자동)은 고른 적 없는 사람에게 그대로 가고, 직접 고른 값은 덮이지 않는다."""
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    service = SettingsService(config)
    service.patch({"user_label": "시험"})
    assert "agent_thinking_policy" not in read_user_values(tmp_path / "data"), "건드리지 않은 칸은 파일에 안 남는다"
    assert config.agent_thinking_policy == "auto"

    service.patch({"agent_thinking_policy": "always"})
    assert read_user_values(tmp_path / "data")["agent_thinking_policy"] == "always"

    # 옛 사용자: 이미 「깊게」를 골라 둔 파일을 새 판이 켜도 그대로 이긴다.
    fresh = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    settings_module.apply_user_settings(fresh)
    assert fresh.agent_thinking_policy == "always"

    # 기본값으로 되돌리면 자동으로 간다.
    service.reset(["agent_thinking_policy"])
    assert config.agent_thinking_policy == "auto"
    row = next(item for item in service.view()["settings"] if item["key"] == "agent_thinking_policy")
    assert row["value"] == "auto" and row["source"] == "default"


# ── 깊게로 올라간 순간의 기록 · 진행 줄 ─────────────────────────────────────────────

class _Bus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.progress: list[str] = []

    def publish(self, event: str, payload: dict[str, Any] | None = None):  # type: ignore[override]
        if event == "agent_progress":
            self.progress.append(str((payload or {}).get("message") or ""))
        return super().publish(event, payload)


class _ThinkLog(base._StopsAfterPreparing):
    """부를 때마다 `think` 를 적는다 — 걸음마다 실제로 생각을 켜고 껐는지."""

    def __init__(self) -> None:
        super().__init__()
        self.think: list[Any] = []

    def chat_messages(self, messages, **kwargs):  # type: ignore[override]
        self.think.append(kwargs.get("think"))
        return super().chat_messages(messages, **kwargs)


class _AnswersAtOnce:
    def __init__(self) -> None:
        self.think: list[Any] = []

    def chat_messages(self, messages, **kwargs):
        self.think.append(kwargs.get("think"))
        return {"role": "assistant", "content": "네, 알겠습니다."}


class _FailsTwice:
    """모르는 도구를 두 번 부르고 실패를 받는다 — 되받기와 상관없이 실패 걸음 둘이 쌓이는 모양."""

    def __init__(self) -> None:
        self.calls = 0
        self.think: list[Any] = []

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        self.think.append(kwargs.get("think"))
        if self.calls <= 3:
            return {"role": "assistant", "content": "",
                    "tool_calls": [{"function": {"name": f"naver_blog_prepare_post", "arguments": {"n": self.calls}}}]}
        return {"role": "assistant", "content": "막혀서 여기까지 했습니다."}


class _FailingGateway(base._RecordingGateway):
    def execute(self, name, arguments, *, job_id: str = ""):  # type: ignore[override]
        self.calls.append((name, dict(arguments)))
        return ToolResult(False, name, error="일부러 실패")


def _run(tmp_path: Path, model: Any, *, prompt: str, reasoning: str = "", policy: str = "auto",
         gateway: Any = None, **kwargs: Any):
    config = base._Config(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, browser_task_timeout_sec=60, agent_thinking_policy=policy,
    )
    store = JobStore(tmp_path / "jarvis.db")
    bus = _Bus()
    runner = BrowserAgent(config, model, gateway or base._RecordingGateway(), base._FakeBrowser(), base._FakeTools(), store, bus)
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()
    result = runner.run(prompt, job_id=job["id"], origin="chat", reasoning=reasoning, **kwargs)
    return result, bus


BLOG = base.__dict__["PROMPT"] if "PROMPT" in base.__dict__ else "네이버 블로그에 '점검' 이라는 제목으로 세 줄 쓰고 임시저장까지 해줘. 발행은 하지 마."
LINE = "막혀서 지금부터 깊게 생각합니다"


def test_a_pushback_under_config_auto_is_recorded_once_with_its_reason(tmp_path: Path) -> None:
    model = _ThinkLog()
    result, bus = _run(tmp_path, model, prompt=BLOG)
    assert result.verification["plan_pushbacks"] >= 1
    escalated = result.verification["reasoning_escalated"]
    assert escalated is not None and escalated["reason"] == "pushback"
    assert isinstance(escalated["step"], int) and escalated["step"] >= 1
    assert bus.progress.count(LINE) == 1, f"진행 줄은 한 번만: {bus.progress}"
    # 보통으로 시작했다 — 첫 걸음은 생각하고 매끄러운 다음 걸음은 생각하지 않았다.
    assert model.think[0] is True and model.think[1] is False, model.think


def test_the_chip_auto_escalates_the_same_way_even_when_the_config_says_off(tmp_path: Path) -> None:
    result, bus = _run(tmp_path, _ThinkLog(), prompt=BLOG, reasoning="auto", policy="off")
    assert result.verification["reasoning_escalated"]["reason"] == "pushback"
    assert bus.progress.count(LINE) == 1


def test_failed_steps_alone_also_escalate_with_the_failures_reason(tmp_path: Path) -> None:
    model = _FailsTwice()
    result, bus = _run(tmp_path, model, prompt="블로그 초안 좀 준비해 줘.", gateway=_FailingGateway())
    escalated = result.verification["reasoning_escalated"]
    assert escalated is not None, "실패 걸음이 둘 쌓였는데 기록이 없다"
    assert escalated["reason"] == "failures" and escalated["step"] == 2
    assert result.verification["plan_pushbacks"] == 0, "되받기 없이 실패만으로 올라간 판이어야 한다"
    assert bus.progress.count(LINE) == 1


def test_a_smooth_job_records_nothing_and_says_nothing(tmp_path: Path) -> None:
    model = _AnswersAtOnce()
    result, bus = _run(tmp_path, model, prompt="고마워, 수고했어.")
    assert result.verification["reasoning_escalated"] is None
    assert LINE not in bus.progress


def test_non_auto_policies_never_record_an_escalation(tmp_path: Path) -> None:
    for policy, chip in (("always", ""), ("adaptive", ""), ("off", ""), ("auto", "deep"), ("auto", "normal"), ("auto", "fast")):
        sub = tmp_path / f"{policy}-{chip or 'none'}"
        sub.mkdir()
        result, bus = _run(sub, _ThinkLog(), prompt=BLOG, reasoning=chip, policy=policy)
        assert result.verification["plan_pushbacks"] >= 1, "되받기가 나야 이 시험이 뜻이 있다"
        assert result.verification["reasoning_escalated"] is None, (policy, chip)
        assert LINE not in bus.progress, (policy, chip)


def test_thinking_turned_off_in_settings_leaves_no_false_promise(tmp_path: Path) -> None:
    config_kwargs = dict(agent_thinking_enabled=False)
    config = base._Config(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, browser_task_timeout_sec=60, agent_thinking_policy="auto", **config_kwargs,
    )
    store = JobStore(tmp_path / "jarvis.db")
    bus = _Bus()
    runner = BrowserAgent(config, _ThinkLog(), base._RecordingGateway(), base._FakeBrowser(), base._FakeTools(), store, bus)
    job = store.create_job("chat", "agent", {"prompt": BLOG})
    store.claim_next()
    result = runner.run(BLOG, job_id=job["id"], origin="chat")
    assert result.verification["reasoning_escalated"] is None
    assert LINE not in bus.progress


def test_the_english_line_exists() -> None:
    path = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "ui_i18n_en.json"
    table = json.loads(path.read_text(encoding="utf-8"))
    assert table[LINE] == "Got stuck — thinking more carefully from here"
