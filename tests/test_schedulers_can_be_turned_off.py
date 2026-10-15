"""스스로 일감을 만드는 둘은 **끌 수 있어야 한다.**

## 왜 (2026-09-05 실측)

예약(scheduler)과 관찰 초소(watches)는 사람이 안 시켜도 잡을 큐에 넣는다. 그게
이 둘의 존재 이유인데, 대신 **아무도 안 볼 때도 GPU 가 돈다.**

    관찰 셋(크몽 2 · 위시켓 1, 6시간 주기)이 도는 동안
      3060  84°C · 94% · 170W 상한에 붙음
      3090  66°C · 186W
      => 두 카드 합쳐 350W

    끄고 60초 뒤
      3090  49°C · 26W   ·   3060  55°C · 17W   => 43W

## 왜 「목록 비우기」로는 부족한가

`watch_cancel` 로 초소를 다 지워도 **서비스는 계속 돈다.** 그러면 다음에 누가
(자비스 자신이든 다음 세션이든) 하나 세우는 순간 조용히 다시 돌기 시작한다.
꺼진 것이 꺼진 채로 남으려면 **스위치**가 있어야 한다.

## 왜 「세우는 것」까지 막는가

끄기만 하고 세우는 길을 열어 두면, 「관찰 세워 줘」에 「세웠습니다」라고 답해
놓고 영영 안 도는 초소가 생긴다. 이 저장소가 여러 번 물린 **조용한 무동작**이다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.config import JarvisConfig


def test_기본값은_켜짐이다():
    """끄는 것은 이 PC 의 선택이지 이 코드의 기본이 아니다."""
    config = JarvisConfig()
    assert config.scheduler_enabled is True
    assert config.watches_enabled is True


@pytest.mark.parametrize(
    "env,field",
    [
        ("JARVIS_SCHEDULER_ENABLED", "scheduler_enabled"),
        ("JARVIS_WATCHES_ENABLED", "watches_enabled"),
    ],
)
def test_env_로_꺼진다(monkeypatch, env, field):
    """★ dataclass 기본값만 고치면 헛돈다 — 값이 사는 자리가 셋이다(사고 Q).

    로더에 안 적으면 `.env` 를 고쳐도 아무 일이 안 일어난다.
    """
    monkeypatch.setenv(env, "false")
    assert getattr(JarvisConfig.from_env(), field) is False
    monkeypatch.setenv(env, "true")
    assert getattr(JarvisConfig.from_env(), field) is True


def test_runtime_이_스위치를_실제로_본다():
    """켜고 끄는 값을 만들어 놓고 `start()` 가 안 보면 아무 소용이 없다."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "runtime.py"
    ).read_text(encoding="utf-8")
    assert "if self.config.scheduler_enabled:" in source
    assert "if self.config.watches_enabled:" in source
    # 잡 워커는 **조건 없이** 돌아야 한다 — 사람이 물어본 것을 처리하는 자리다.
    assert "self.runner.start()" in source
    before = source.split("self.runner.start()")[0]
    assert "if self.config" not in before[-200:], "잡 워커가 스위치 뒤로 들어가면 안 된다"


def test_꺼진_초소는_세우는_것부터_거절한다():
    """조용한 무동작 방지. 「세웠습니다」라고 답하고 안 도는 것이 제일 나쁘다."""
    from alture_jarvis.watch_service import WatchService

    service = WatchService.__new__(WatchService)
    service.enabled = False
    with pytest.raises(RuntimeError) as caught:
        WatchService.tool_create(service, {"name": "크몽", "prompt": "x"})
    assert "watches_disabled" in str(caught.value)
    assert "JARVIS_WATCHES_ENABLED" in str(caught.value), "켜는 방법을 알려 줘야 한다"


def test_꺼진_예약은_만드는_것부터_거절한다():
    from alture_jarvis.scheduler import TaskScheduler

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler.config = JarvisConfig(scheduler_enabled=False)
    with pytest.raises(RuntimeError) as caught:
        TaskScheduler.create(scheduler, {"title": "t", "prompt": "x", "delay_minutes": 10})
    assert "scheduler_disabled" in str(caught.value)
    assert "JARVIS_SCHEDULER_ENABLED" in str(caught.value)


def test_켜져_있으면_예전대로_만든다():
    """끄는 장치가 켜진 상태를 망가뜨리면 안 된다."""
    from alture_jarvis.scheduler import TaskScheduler

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler.config = JarvisConfig(scheduler_enabled=True)
    # 꺼짐 관문을 지나 **그 다음 검사**(prompt 없음)에서 걸려야 한다.
    with pytest.raises(ValueError) as caught:
        TaskScheduler.create(scheduler, {"title": "t", "prompt": ""})
    assert "prompt_required" in str(caught.value)
