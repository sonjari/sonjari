"""「켜고 받기」 · 설정한 자리 판정 (2026-11-16 저녁 · 팩 잇기 시험 구멍 · ADR-PACK-1 덧붙임 절).

지키는 것:
1. 사람이 설정한 자리(`JARVIS_GEN3D_*_DIR` · `JARVIS_GENVIDEO_*_DIR`)에 그 팩 도구가 쓰는 꼴로 있으면 팩 모델 상태가
   「있음(configured)」 — 받을 것 0 · 받기가 그 모델을 건너뛴다(같은 10.6GB 를 또 받지 않는다).
2. 「받을 것이 남았나」는 한 자리(`status.needs_fetch`) — 카드 · 맡김 · 설정 켜기 단추가 같은 판정을 쓴다.
3. 맡김이 켜져 있어도 받을 것이 남은 팩은 카드(받기는 맡기지 않는다) · 다 있는 팩만 맡김으로 바로.
4. 카드에 크기 · 받는 자리 · 남은 자리 · 「켜고 받기」. 누르면 켜면서 받기를 시작한다. 자리가 모자라면 켜지 않는다.
5. 설정 › 팩 켜기(`POST /v1/packs/{id}/enable?fetch=true`)도 같은 규칙.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.pack_models import ModelFetcher
from alture_jarvis.pack_places import configured_finder
from alture_jarvis.pack_request import TOOL_NAME, PackRequestTools
from alture_jarvis.packs import PackRegistry
from alture_jarvis.tool_gateway import ToolGateway

REPO = Path(__file__).resolve().parents[1]
WIN = ("win", "x64")
GEN3D_FILES = ["birefnet.gguf", "dinov3.gguf", "ss_flow.gguf", "ss_dec.gguf", "shape_dec.gguf", "tex_dec.gguf"]
ARGS = {"pack": "gen3d", "why": "사진 한 장으로 3D 피규어를 만들려고"}
BIG = 10 ** 13  # 넉넉한 디스크


def _no_network(url: str, headers: dict[str, str]) -> Any:
    raise AssertionError(f"설정한 자리에 있는데 인터넷에 나갔다: {url}")


def _gen3d_places(tmp_path: Path, *, bins: bool = True, models: bool = True, nested: bool = True) -> SimpleNamespace:
    bin_dir = tmp_path / "trellis.cpp" / "cuda"
    model_dir = tmp_path / "trellis2-gguf"
    if bins:
        bin_dir.mkdir(parents=True)
        (bin_dir / "trellis-cli.exe").write_bytes(b"MZ")
    if models:
        where = model_dir / "q8" if nested else model_dir
        where.mkdir(parents=True)
        for name in GEN3D_FILES:
            (where / name).write_bytes(b"gguf")
    return SimpleNamespace(gen3d_bin_dir=str(bin_dir), gen3d_models_dir=str(model_dir),
                           genvideo_bin_dir="", genvideo_models_dir="")


def _fetcher(tmp_path: Path, config: Any = None, *, free: int = BIG, opener: Any = _no_network) -> tuple[PackRegistry, ModelFetcher]:
    registry = PackRegistry(REPO / "packs", tmp_path / "data")
    fetcher = ModelFetcher(registry, tmp_path / "data", platform=WIN, free_bytes=lambda _p: free, opener=opener,
                           hf_snapshot=None, root=tmp_path / "packfiles",
                           configured=configured_finder(config, platform="win32") if config is not None else None)
    return registry, fetcher


# ── 1. 설정한 자리 ──────────────────────────────────────────────────────────

def test_configured_places_count_as_present(tmp_path: Path) -> None:
    """11-16: 이 PC 는 .env 자리로 3D 가 잘 도는데 팩 화면은 「missing · 받기 10.6GB」였다."""
    _registry, fetcher = _fetcher(tmp_path, _gen3d_places(tmp_path))
    status = fetcher.status("gen3d")
    mine = [row for row in status["models"] if row["state"] != "not_for_this_machine"]
    assert {row["id"] for row in mine} == {"trellis-cpp-cuda-win", "trellis2-q8"}
    assert all(row["state"] == "ready" and row["configured"] for row in mine), mine
    assert status["all_ready"] and not status["needs_fetch"]
    assert status["to_download_bytes"] == 0 and status["disk_needed_bytes"] == 0
    weights = next(row for row in mine if row["id"] == "trellis2-q8")
    assert weights["path"].endswith("q8"), "모델이 q8/ 아래에 있으면 그 자리를 가리킨다(gen3d_dirs 와 같게)"


def test_without_settings_it_is_still_missing(tmp_path: Path) -> None:
    """반례: 설정이 비면 예전 그대로 받을 것이 남는다(고침이 「다 있음」으로 새지 않는다)."""
    blank = SimpleNamespace(gen3d_bin_dir="", gen3d_models_dir="", genvideo_bin_dir="", genvideo_models_dir="")
    for config in (None, blank):
        _registry, fetcher = _fetcher(tmp_path, config)
        status = fetcher.status("gen3d")
        assert status["needs_fetch"] and status["to_download_bytes"] > 9_000_000_000


def test_half_configured_only_skips_what_is_there(tmp_path: Path) -> None:
    """실행기만 설정 자리에 있으면 실행기만 「있음」 · 모델은 받는다. 빈 자리를 설정해 둔 것은 있음이 아니다."""
    _registry, fetcher = _fetcher(tmp_path, _gen3d_places(tmp_path, models=False))
    status = fetcher.status("gen3d")
    rows = {row["id"]: row for row in status["models"]}
    assert rows["trellis-cpp-cuda-win"]["configured"] and rows["trellis-cpp-cuda-win"]["state"] == "ready"
    assert rows["trellis2-q8"]["state"] == "missing" and not rows["trellis2-q8"]["configured"]
    assert status["needs_fetch"] and status["to_download_bytes"] == rows["trellis2-q8"]["size"]


def test_missing_one_model_file_is_not_present(tmp_path: Path) -> None:
    """반례: 설정 자리에 모델 파일 여섯 가운데 하나가 빠지면 있음이 아니다(그 팩 도구가 쓰는 판정 `models_ready` 그대로)."""
    config = _gen3d_places(tmp_path, nested=False)
    (Path(config.gen3d_models_dir) / "tex_dec.gguf").unlink()
    _registry, fetcher = _fetcher(tmp_path, config)
    rows = {row["id"]: row for row in fetcher.status("gen3d")["models"]}
    assert rows["trellis2-q8"]["state"] == "missing"


def test_fetch_skips_configured_models_and_goes_nowhere(tmp_path: Path) -> None:
    registry, fetcher = _fetcher(tmp_path, _gen3d_places(tmp_path))
    registry.set_enabled("gen3d", True)
    out = fetcher.fetch("gen3d", wait=True)
    assert out["ok"] and fetcher.status("gen3d")["state"] == "done"
    assert not (tmp_path / "packfiles" / "models" / "gen3d").exists(), "설정 자리에 있는데 팩 자리에 또 받았다"


def test_a_broken_place_check_means_not_present(tmp_path: Path) -> None:
    """판정이 터지면 「있음」이 아니라 받기 쪽으로(조용히 다 있다고 하지 않는다)."""
    registry = PackRegistry(REPO / "packs", tmp_path / "data")

    def boom(_pack: str, _model: dict[str, Any]) -> Path:
        raise OSError("드라이브 없음")

    fetcher = ModelFetcher(registry, tmp_path / "data", platform=WIN, free_bytes=lambda _p: BIG, configured=boom)
    assert fetcher.status("gen3d")["needs_fetch"]


def test_genvideo_configured_places(tmp_path: Path) -> None:
    bins, models = tmp_path / "sd", tmp_path / "wan"
    bins.mkdir()
    models.mkdir()
    (bins / "sd-cli.exe").write_bytes(b"MZ")
    (bins / "cudart64_12.dll").write_bytes(b"MZ")
    for name in ("FastWan2.2-TI2V-5B-Q8_0.gguf", "Wan2.2-TI2V-5B-Q8_0.gguf", "umt5-xxl-encoder-Q8_0.gguf",
                 "wan2.2_vae.safetensors", "taew2_2.safetensors"):
        (models / name).write_bytes(b"x")
    config = SimpleNamespace(gen3d_bin_dir="", gen3d_models_dir="", genvideo_bin_dir=str(bins), genvideo_models_dir=str(models))
    _registry, fetcher = _fetcher(tmp_path, config)
    status = fetcher.status("genvideo")
    assert status["all_ready"] and not status["needs_fetch"] and status["to_download_bytes"] == 0
    # 반례: cudart 가 없으면 그 묶음만 받는다
    (bins / "cudart64_12.dll").unlink()
    rows = {row["id"]: row for row in fetcher.status("genvideo")["models"]}
    assert rows["sdcpp-cudart-win"]["state"] == "missing" and rows["sdcpp-cuda-win"]["state"] == "ready"


# ── 2 · 3 · 4. 청하기 · 맡김 · 카드 ──────────────────────────────────────────

def _request_setup(tmp_path: Path, config: Any = None, *, free: int = BIG, delegate: bool = False, **gate: Any):
    registry, fetcher = _fetcher(tmp_path, config, free=free)
    store = JobStore(tmp_path / "jobs.db")
    gateway = ToolGateway(store, EventBus(), **gate)
    if delegate:
        registry.set_claude_may_enable(True)
    fetched: list[str] = []

    def fetch(pack_id: str) -> dict[str, Any]:
        fetched.append(pack_id)
        return {"ok": True, "started": True, "state": "running"}

    tools = PackRequestTools(registry, store, models_status=fetcher.status, models_fetch=fetch)
    tools.register(gateway)
    return gateway, registry, store, fetched


@pytest.mark.parametrize("mode", [{}, {"auto_approve_all": True}], ids=["수동", "권한무시"])
def test_delegated_but_files_left_still_shows_the_card(tmp_path: Path, mode: dict[str, Any]) -> None:
    """ADR-PACK-1 결정 3: 받기는 맡기지 않는다 — 맡김 켬 + 받을 것 남음 → 카드."""
    gateway, registry, store, fetched = _request_setup(tmp_path, delegate=True, **mode)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.status == "approval_required" and not registry.is_enabled("gen3d")
    assert len(store.list_approvals(10, "pending")) == 1 and not fetched


def test_delegated_and_nothing_to_fetch_turns_on_directly(tmp_path: Path) -> None:
    gateway, registry, store, fetched = _request_setup(tmp_path, _gen3d_places(tmp_path), delegate=True)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.ok and registry.is_enabled("gen3d") and out.result["by"] == "delegated"
    assert store.list_approvals(10, "pending") == [] and not fetched, "받을 것이 없는데 받기를 시작했다"


def test_card_shows_size_place_and_room(tmp_path: Path) -> None:
    gateway, _registry, store, _fetched = _request_setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    target = gateway.describe_approval(store.list_approvals(1, "pending")[0])["target"]
    assert target["fetch_on_enable"] is True and target["disk_ok"] is True
    assert target["download_bytes"] > 9_000_000_000
    assert target["place"] == str(tmp_path / "packfiles")
    line = target["download"]
    assert "켜면 필요한 파일" in line and "GB" in line and "받는 자리" in line and "남은 자리" in line, line


def test_card_says_nothing_to_fetch_when_configured(tmp_path: Path) -> None:
    gateway, _registry, store, _fetched = _request_setup(tmp_path, _gen3d_places(tmp_path))
    gateway.execute(TOOL_NAME, dict(ARGS))
    target = gateway.describe_approval(store.list_approvals(1, "pending")[0])["target"]
    assert target["fetch_on_enable"] is False and target["download_bytes"] == 0
    assert "이미 있습니다" in target["download"]


def test_pressing_the_card_turns_on_and_starts_fetching(tmp_path: Path) -> None:
    gateway, registry, store, fetched = _request_setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    assert not fetched, "누르기 전에 받기를 시작했다"
    gateway.decide(store.list_approvals(1, "pending")[0]["nonce"], True)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.ok and registry.is_enabled("gen3d")
    assert fetched == ["gen3d"] and out.result["models"]["fetching"] is True
    assert "받기를 시작했습니다" in out.result["message"]


def test_declining_fetches_nothing(tmp_path: Path) -> None:
    gateway, registry, store, fetched = _request_setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    gateway.decide(store.list_approvals(1, "pending")[0]["nonce"], False)
    assert not registry.is_enabled("gen3d") and not fetched


def test_not_enough_room_does_not_turn_on(tmp_path: Path) -> None:
    gateway, registry, store, fetched = _request_setup(tmp_path, free=1_000_000_000)
    gateway.execute(TOOL_NAME, dict(ARGS))
    target = gateway.describe_approval(store.list_approvals(1, "pending")[0])["target"]
    assert target["disk_ok"] is False and "설정 › 일반 › 팩 파일 자리" in target["download"]
    gateway.decide(store.list_approvals(1, "pending")[0]["nonce"], True)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert not out.ok and "not_enough_disk" in out.error
    assert not registry.is_enabled("gen3d") and not fetched


def test_pack_without_models_has_no_fetch(tmp_path: Path) -> None:
    gateway, registry, store, fetched = _request_setup(tmp_path, delegate=True)
    out = gateway.execute(TOOL_NAME, {"pack": "animator", "why": "블렌더 동작 고치려고"})
    assert out.ok and registry.is_enabled("animator") and not fetched and "models" not in out.result


def test_unreadable_status_counts_as_files_left(tmp_path: Path) -> None:
    """상태를 못 읽으면 받을 것이 남은 것으로 본다 — 맡김으로 새지 않는다."""
    registry = PackRegistry(REPO / "packs", tmp_path / "data")
    registry.set_claude_may_enable(True)
    store = JobStore(tmp_path / "jobs.db")
    gateway = ToolGateway(store, EventBus())

    def broken(_pack: str) -> dict[str, Any]:
        raise RuntimeError("상태 고장")

    PackRequestTools(registry, store, models_status=broken).register(gateway)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.status == "approval_required" and not registry.is_enabled("gen3d")


# ── 5. 설정 › 팩 켜기 단추(API) ─────────────────────────────────────────────

def _api(tmp_path: Path):
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=tmp_path / "docs", control_token="test-token", camera_enabled=False,
                          vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis
    runtime.pack_models.platform = WIN
    runtime.pack_models._configured = None
    calls: list[str] = []
    runtime.pack_models.fetch = lambda pack_id, wait=False: calls.append(pack_id) or {"ok": True, "started": True}
    return TestClient(app), runtime, calls


HEAD = {"X-JARVIS-TOKEN": "test-token"}


def test_settings_enable_with_fetch_turns_on_and_fetches(tmp_path: Path) -> None:
    client, runtime, calls = _api(tmp_path)
    runtime.pack_models._free = lambda _p: BIG
    out = client.post("/v1/packs/gen3d/enable?fetch=true", headers=HEAD)
    assert out.status_code == 200 and runtime.packs.is_enabled("gen3d") and calls == ["gen3d"]


def test_settings_enable_without_fetch_does_not_fetch(tmp_path: Path) -> None:
    client, runtime, calls = _api(tmp_path)
    runtime.pack_models._free = lambda _p: BIG
    out = client.post("/v1/packs/gen3d/enable", headers=HEAD)
    assert out.status_code == 200 and runtime.packs.is_enabled("gen3d") and calls == []
    assert out.json()["models_status"]["needs_fetch"] is True


def test_settings_enable_with_fetch_and_no_room_stays_off(tmp_path: Path) -> None:
    client, runtime, calls = _api(tmp_path)
    runtime.pack_models._free = lambda _p: 1_000_000
    out = client.post("/v1/packs/gen3d/enable?fetch=true", headers=HEAD)
    assert out.status_code == 507 and out.json()["detail"]["error"] == "not_enough_disk"
    assert not runtime.packs.is_enabled("gen3d") and calls == []


def test_runtime_wires_the_configured_places(tmp_path: Path) -> None:
    """운영 runtime 이 설정 자리 판정을 꽂는다 — 빠지면 이 PC 화면이 다시 「받기 10.6GB」가 된다."""
    from fastapi.testclient import TestClient  # noqa: F401 — create_app 이 쓰는 것과 같은 길

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    places = _gen3d_places(tmp_path)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=tmp_path / "docs", control_token="test-token", camera_enabled=False,
                          vision_enabled=False, voice_enabled=False, tts_enabled=False,
                          gen3d_bin_dir=places.gen3d_bin_dir, gen3d_models_dir=places.gen3d_models_dir)
    runtime = create_app(config, start_services=False).state.jarvis
    if runtime.pack_models.platform != WIN:
        pytest.skip("윈도우 실행기 이름으로 만든 자리 — 윈도우에서만")
    status = runtime.pack_models.status("gen3d")
    assert status["all_ready"] and not status["needs_fetch"]
    assert runtime.pack_request.models_fetch is not None, "카드에서 누른 뒤 받기를 시작할 자리가 안 꽂혔다"
