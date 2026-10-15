"""지켜보는 것이 **자비스를 막으면 안 된다.**

## 왜 (2026-08-20 실측)

브라우저 일꾼은 하나뿐이라, 라이브 화면 캡처와 에이전트 걸음이 같은 자리를 놓고
다툰다. 캡처는 `background=True` 로 표시돼 있고 전면 작업은 배경 일에게 잠깐
양보하게 돼 있었다 — **그 양보가 0.75초 고정이었다.**

그런데 캡처의 자기 예산은 6초다(`_FRAME_TIMEOUT_SEC`, 스크린샷 자체가 4초).
숫자가 둘로 갈리자 낮은 쪽만 일했다:

    2026-08-20 03시 — 에이전트 걸음 27건이 라이브 캡처에 막혔다
    막힌 것: browser_open 6 · browser_extract 6 · site_run 5 · snapshot 5 …
    그 판(사람인)은 그대로 죽었다

저장소에 「★지켜보는 사람이 이긴다」고 적어 둔 것과 **정반대**였다.

## 이 검사가 지키는 것

양보 시간을 **배경 일이 스스로 적어 둔 마감에서 끌어온다.** 지킬 숫자가 하나로
줄어서, 배경 일의 예산이 바뀌어도 양보가 따라간다. 고정 천장은 그 마감이
터무니없을 때만 쓰는 안전장치다.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from alture_jarvis.browser import _BACKGROUND_YIELD_CAP_SEC, BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path: Path) -> BrowserWorker:
    worker = BrowserWorker(
        JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    )
    worker._connected = True
    return worker


# ── 숫자가 하나여야 한다 ─────────────────────────────────────────────────────


def test_the_yield_ceiling_covers_every_background_budget(tmp_path: Path) -> None:
    """★ 이것이 이 파일의 핵심이다.

    천장이 배경 일의 예산보다 낮으면 **낮은 쪽이 조용히 이긴다** — 그게 27건을
    막은 구조다. 배경 일이 새로 생겨 예산이 커지면 여기서 깨져야 한다.
    """
    assert _BACKGROUND_YIELD_CAP_SEC >= BrowserWorker._FRAME_TIMEOUT_SEC, (
        "라이브 캡처가 자기 예산을 다 쓰면 전면 작업이 튕긴다 — 27건을 막은 그 구조다"
    )


def test_a_foreground_call_waits_for_a_slow_background_capture(tmp_path: Path) -> None:
    """캡처가 0.75초보다 오래 걸려도 에이전트 걸음이 튕기지 않아야 한다.

    예전 고정 양보(0.75초)에서는 여기서 `browser_busy_active` 가 났다.
    """
    worker = _worker(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_background() -> str:
        started.set()
        release.wait(timeout=5)
        return "captured"

    background = threading.Thread(
        target=lambda: worker._submit(
            slow_background, 6.0, operation="browser_live_frame", background=True
        ),
        daemon=True,
    )
    background.start()
    assert started.wait(timeout=5)

    # 캡처가 0.75초를 훌쩍 넘겨 도는 동안 전면 호출이 들어온다.
    time.sleep(1.2)
    outcome: list[object] = []

    def foreground() -> None:
        try:
            outcome.append(worker._submit(lambda: "agent step", 5.0, operation="browser_extract"))
        except Exception as exc:  # noqa: BLE001
            outcome.append(exc)

    caller = threading.Thread(target=foreground, daemon=True)
    caller.start()
    time.sleep(0.3)
    release.set()
    caller.join(timeout=8)
    background.join(timeout=8)

    assert outcome, "전면 호출이 끝나지 않았다"
    assert not isinstance(outcome[0], Exception), f"에이전트 걸음이 튕겼다: {outcome[0]}"
    assert outcome[0] == "agent step"


def test_a_foreground_call_still_refuses_to_queue_behind_a_foreground_one(tmp_path: Path) -> None:
    """★ 양보는 **배경 일에게만** 준다.

    전면 작업 뒤에 줄을 서면 호출마다 3분씩 멈춘 것처럼 보인다 — 그 규칙을
    이번 수정이 무너뜨리면 안 된다(2026-08-16 사람인 사고).
    """
    worker = _worker(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_foreground() -> str:
        started.set()
        release.wait(timeout=5)
        return "long nav"

    first = threading.Thread(
        target=lambda: worker._submit(slow_foreground, 10.0, operation="browser_open"),
        daemon=True,
    )
    first.start()
    assert started.wait(timeout=5)

    began = time.monotonic()
    try:
        worker._submit(lambda: "second", 5.0, operation="browser_extract")
        raise AssertionError("전면 작업 뒤에 줄을 섰다")
    except RuntimeError as exc:
        assert "browser_busy_active" in str(exc)
    # 기다리지 않고 **바로** 돌아와야 한다.
    assert time.monotonic() - began < 1.0
    release.set()
    first.join(timeout=8)


def test_the_yield_ends_when_the_background_deadline_passes(tmp_path: Path) -> None:
    """배경 일이 자기 마감을 넘겨 물려 있으면 더는 기다리지 않는다.

    무한정 기다리면 라이브 화면 하나가 자비스를 통째로 세울 수 있다.
    """
    worker = _worker(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def stuck_background() -> str:
        started.set()
        release.wait(timeout=10)
        return "never"

    def run_stuck() -> None:
        # 이 배경 일은 **일부러** 자기 예산을 넘긴다. 그때 나는 timeout 예외는
        # 이 검사가 만들려는 상황 자체라, 스레드 밖으로 새어 나가지 않게 삼킨다.
        try:
            worker._submit(
                stuck_background, 0.3, operation="browser_live_frame", background=True
            )
        except RuntimeError:
            pass

    background = threading.Thread(target=run_stuck, daemon=True)
    background.start()
    assert started.wait(timeout=5)
    time.sleep(0.6)  # 배경 일의 마감(0.3초)이 지났다

    began = time.monotonic()
    try:
        worker._submit(lambda: "agent step", 5.0, operation="browser_extract")
        raise AssertionError("마감이 지난 배경 일을 계속 기다렸다")
    except RuntimeError as exc:
        # `busy_active` 든 `busy_stuck` 이든 상관없다 — 자기 예산을 넘긴 배경 일은
        # 물린 것으로 따로 잡히기도 한다. 여기서 지키는 것은 **기다리지 않는다**는
        # 사실 하나다.
        assert "browser_busy" in str(exc), str(exc)
    assert time.monotonic() - began < 1.0, "마감이 지났는데도 양보를 계속했다"
    release.set()
    background.join(timeout=10)
