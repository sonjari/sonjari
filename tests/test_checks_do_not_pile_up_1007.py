"""화면이 자주 묻는 가벼운 길은, 앞 물음이 띄운 느린 일이 아직 돌면 **겹쳐 돌지 않는다** (2026-10-07).

6GB 노트북 첫 실행에서 「시작하기」가 안 먹었고, 작업 관리자로 모델 실행기를 끄자 풀렸다. 원인은 확인하지 못했다(그 PC 의
기록이 없다). 코드를 훑어 **기록 없이도 틀린 것이 분명한** 두 자리를 고쳤다 — 둘 다 「느린 일을 물을 때마다 새로 시작한다」였다.

1. 켤 때 점검: 모델 검사는 멈춘 실행기 앞에서 180초까지 묶인다. 화면은 15초마다 묻고 결과는 검사가 끝나야 바뀌므로,
   그 사이의 물음이 전부 같은 검사에 다시 들어갔다.
2. 컨텍스트 조회: 감시 루프가 처음 돌기 전(켠 뒤 30분)에는 물을 때마다 `nvidia-smi` 를 두 번 돌렸다. 마법사는 상한을 재는
   동안 이 주소를 1초마다 부른다.
"""
from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.self_care import SelfCare

HEADERS = {"X-JARVIS-TOKEN": "test-token"}


class _Events:
    def publish(self, *_args, **_kwargs) -> None:
        return None


def _care(release: threading.Event, started: threading.Event, probes: list[str]) -> SelfCare:
    care = object.__new__(SelfCare)
    care.last_boot = None
    care.events = _Events()

    def probe(name: str) -> dict:
        probes.append(name)
        started.set()
        release.wait(5)
        return {"organ": name, "state": "ok", "healer": ""}

    care._safe_probe = probe
    return care


def test_a_check_asked_for_while_one_is_running_does_not_start_another() -> None:
    release, started, probes = threading.Event(), threading.Event(), []
    care = _care(release, started, probes)
    first = threading.Thread(target=lambda: care.boot_check(include_model=False))
    first.start()
    assert started.wait(2)
    began = time.monotonic()
    answers = [care.boot_check(include_model=False, wait=False) for _ in range(5)]
    assert time.monotonic() - began < 0.5, "기다리지 않는다"
    assert answers == [{"pending": True}] * 5, "지난 결과가 없으면 「아직」"
    assert probes == ["engine"], "검사는 하나만 돈다"
    release.set()
    first.join(3)
    assert care.last_boot and care.last_boot["healthy"] is True


def test_while_one_is_running_the_last_result_is_what_the_screen_gets() -> None:
    release, started, probes = threading.Event(), threading.Event(), []
    care = _care(release, started, probes)
    care.last_boot = {"down": ["engine"], "healthy": False}
    first = threading.Thread(target=lambda: care.boot_check(include_model=False))
    first.start()
    assert started.wait(2)
    assert care.boot_check(include_model=False, wait=False) == {"down": ["engine"], "healthy": False}
    release.set()
    first.join(3)


def test_once_the_running_check_is_done_the_next_ask_checks_again() -> None:
    release, started, probes = threading.Event(), threading.Event(), []
    release.set()
    care = _care(release, started, probes)
    care.boot_check(include_model=False, wait=False)
    care.boot_check(include_model=False, wait=False)
    assert probes == ["engine", "engine"]


def test_the_boot_time_check_still_waits_for_its_own_result() -> None:
    """켤 때의 한 번과 「고치기」 뒤의 다시 보기는 결과가 필요하다 — 기다렸다가 제 검사를 돈다."""
    release, started, probes = threading.Event(), threading.Event(), []
    care = _care(release, started, probes)
    first = threading.Thread(target=lambda: care.boot_check(include_model=False))
    first.start()
    assert started.wait(2)
    done: list[dict] = []
    second = threading.Thread(target=lambda: done.append(care.boot_check(include_model=False)))
    second.start()
    time.sleep(0.1)
    assert not done, "앞 검사가 끝나기 전에는 돌아오지 않는다"
    release.set()
    first.join(3)
    second.join(3)
    assert done and done[0]["healthy"] is True and probes == ["engine", "engine"]


def test_asking_for_the_context_state_again_does_not_measure_the_card_again(tmp_path, monkeypatch) -> None:
    from alture_jarvis import context_watch

    calls: list[int] = []

    def snapshot(*_args, **_kwargs) -> dict:
        calls.append(1)
        return {"gpus": []}

    # 설정 서비스는 만들어질 때 이 함수를 집어 든다 — 앱을 만들기 전에 바꿔 둔다.
    monkeypatch.setattr(context_watch, "gpu_snapshot", snapshot)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs", control_token="test-token",
                          camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False)
    with TestClient(create_app(config, start_services=False)) as client:
        states = [client.get("/v1/setup/context", headers=HEADERS).json()["watch"] for _ in range(5)]
    assert len(calls) == 1, "첫 물음에서 한 번 재서 두고, 다음 물음은 둔 값을 받는다"
    assert all(state == states[0] for state in states)
