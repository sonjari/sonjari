"""손자리 본체가 Strata 를 지킨다 — 1단계 (2026-11-13 · 설계 docs/설계_Strata_앱이켜고지키기_2026-11-13.ko.md).

계기: 클로드 셸에서 켠 Strata · 다리가 클로드와 같이 죽어 PC · 맥 손자리가 1시간 넘게 생각을 못 했다 · 재부팅 뒤 저절로 안 뜬다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis import strata_runtime as sr
from alture_jarvis.strata_runtime import Probe, StrataService, StrataState, decide

STRATA = {"catalog_key": "strata-flash-next-swift", "chat_model": "strata/qwen3.8-flash-next-swift"}
SWIFT = {"catalog_key": "swift-27b", "chat_model": "swift:27b"}


def test_decide_table() -> None:
    now = 10_000.0
    fresh = StrataState()
    assert decide(False, fresh, Probe(False, False), now) == "none"            # 27B 를 고른 동안(3D 작업 포함) 켜지 않는다
    assert decide(True, fresh, Probe(True, True), now) == "none"
    assert decide(True, fresh, Probe(False, False), now) == "start"            # 재부팅 뒤 · 같이 죽은 뒤
    assert decide(True, fresh, Probe(True, False), now) == "bridge"            # 다리만 죽음 — 68GB 를 다시 읽지 않는다
    loading = StrataState(starts=[now - 60])
    assert decide(True, loading, Probe(False, False), now) == "none"           # 켜는 중(68GB 읽는 중) — 겹쳐 띄우지 않는다
    three = StrataState(starts=[now - 500, now - 400, now - 200])
    assert decide(True, three, Probe(False, False), now) == "give_up"          # 10분 3번 — 램 부족을 끝없이 되풀이하지 않는다
    old = StrataState(starts=[now - 900, now - 800, now - 700])
    assert decide(True, old, Probe(False, False), now) == "start"              # 10분 밖은 안 센다
    assert decide(True, StrataState(gave_up=True), Probe(False, False), now) == "none"


def test_selection_and_detect(tmp_path: Path) -> None:
    assert sr.is_selected(STRATA) and not sr.is_selected(SWIFT) and not sr.is_selected(None)
    cmd = tmp_path / "strata.cmd"
    assert not sr.detect(cmd, tmp_path)                                        # 손님 PC — 화면에 안 보인다
    cmd.write_text("@echo off", encoding="utf-8")
    (tmp_path / "models").mkdir()
    assert sr.detect(cmd, tmp_path)


def test_launch_matches_use_strata_ps1() -> None:
    """값은 scripts/use_strata.ps1 의 launch 줄과 같아야 한다 — 둘이 갈리면 앱으로 켠 Strata 가 다르게 돈다."""
    import pytest

    path = Path(__file__).resolve().parents[1] / "scripts" / "use_strata.ps1"
    if not path.is_file():
        pytest.skip("use_strata.ps1 은 대표 PC 개인용이라 공개 저장소에 없다")
    script = path.read_text(encoding="utf-8-sig")
    argv = sr.launch_command()
    for pair in (("--parallel", "1"), ("--port", "8097"), ("--gpu", "0"), ("--vision", "gpu"), ("--tune", "skip")):
        assert f"{pair[0]} {pair[1]}" in script and argv[argv.index(pair[0]) + 1] == pair[1]
    for setting in ("conversation-cache-mib=4096", "conversation-cache-min-tokens=4000", "conversation-cache-slots=6"):
        assert setting in script and setting in argv
    assert f'[string]$Size = "{sr.STRATA_SIZE}"' in script and f'[string]$Context = "{sr.STRATA_CONTEXT}"' in script
    env = sr.strata_env({})
    assert env["LOCALAPPDATA"] == r"D:\SLA" and env["STRATA_DATA_DIR"] == r"D:\Strata"


def _service(tmp_path: Path, *, selection: dict, up: dict[str, bool], clock: list[float]) -> tuple[StrataService, list]:
    spawned: list = []

    def http_ok(url: str) -> bool:
        return up["strata"] if ":8097/" in url else up["bridge"]

    def spawn(argv: list[str], *, env: dict | None, log: Path | None) -> int:
        spawned.append(argv)
        return 1

    ran: list = []
    svc = StrataService(data_dir=tmp_path, runtime=tmp_path / "rt", selection=lambda: selection, http_ok=http_ok,
                        spawn=spawn, run=lambda argv, **k: ran.append(argv), clock=lambda: clock[0], available=lambda: True)
    svc.ran = ran  # type: ignore[attr-defined]
    return svc, spawned


def test_ensure_starts_both_when_down_and_only_the_bridge_when_strata_lives(tmp_path: Path) -> None:
    clock = [1000.0]
    up = {"strata": False, "bridge": False}
    svc, spawned = _service(tmp_path, selection=STRATA, up=up, clock=clock)
    assert svc.ensure() == "start" and len(spawned) == 2
    assert spawned[0][1] == "launch" and spawned[1][-1].endswith("strata_bridge.py")
    assert "Ollama-Watchdog" in svc.ran[0][-1] and "llama-server" in svc.ran[0][-1]   # 램부터 비운다(재부팅 뒤 Ollama 가 떠 있다)
    clock[0] += 30
    assert svc.ensure() == "none" and len(spawned) == 2                        # 켜는 중
    up["strata"] = True
    assert svc.ensure() == "bridge" and len(spawned) == 3


def test_gives_up_after_three_starts_and_retry_resets(tmp_path: Path) -> None:
    clock = [1000.0]
    svc, spawned = _service(tmp_path, selection=STRATA, up={"strata": False, "bridge": False}, clock=clock)
    for _ in range(3):
        assert svc.ensure() == "start"
        clock[0] += 190                                                        # 켜는 중 시간을 넘김
    assert svc.ensure() == "give_up"
    assert svc.status()["gave_up"] and "램" in svc.status()["last_error"]
    assert svc.ensure() == "none" and len(spawned) == 6
    svc.retry()
    assert not svc.status()["gave_up"] and len(spawned) == 8                   # 다시 켜기 = 바로 한 번 켬


def test_nothing_happens_on_a_customer_pc_or_with_27b_selected(tmp_path: Path) -> None:
    clock = [1000.0]
    svc, spawned = _service(tmp_path, selection=SWIFT, up={"strata": False, "bridge": False}, clock=clock)
    assert svc.ensure() == "none" and spawned == []
    svc.available = lambda: False
    svc.selection = lambda: STRATA
    assert svc.ensure() == "none" and spawned == [] and svc.status()["available"] is False


def test_the_watch_never_runs_under_tests_and_has_an_off_switch() -> None:
    """이 PC 엔 진짜 Strata 가 깔려 있다 — 시험이 본체를 만들 때마다 지킴이가 68GB 를 띄우면 안 된다."""
    assert sr.watch_enabled() is False                                         # pytest 안
    assert sr.start_watch(None) is False  # type: ignore[arg-type]


def test_the_app_serves_strata_status_behind_the_token(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    with TestClient(app) as client:
        assert client.get("/v1/strata/status").status_code == 401                # 토큰 없이는 안 된다
        body = client.get("/v1/strata/status", headers={"X-JARVIS-TOKEN": "test-token"}).json()
    assert set(body) >= {"available", "selected", "strata", "bridge", "gave_up", "last_error"}
    assert body["selected"] is False                                           # 이 시험 집엔 Strata 선택이 없다
