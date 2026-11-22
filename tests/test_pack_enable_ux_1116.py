"""팩 켜기 UX (2026-11-16 · 설계 `docs/설계_팩켜기UX_2026-11-16.ko.md` §8 시험 계획).

지키는 것:
1. 권하기 판정(§4-1 표) — 윈도우 · 맥 가짜 신호로 칸마다. 못 읽은 메모리는 「맞음」이 아니다.
2. 권하기는 켜지 않는다 · 이 PC 밖으로 아무것도 안 보낸다 · 「무시」는 남고 켜고 끌 때 지워지지 않는다.
3. `sonjari_pack_request` — **어느 권한 모드에서도** 사람이 누르기 전엔 안 켜진다. 거절 · 만료면 같은 일에서 다시 조르지 않는다.
4. 바깥 클로드가 청한 것은 사람이 누르는 순간 켜진다(두 번 켜지 않음).
5. MCP — 위험 상한(L1) 아래 목록에도 이 문은 늘 있고, 고정 문으로도 불린다.
6. `pack.json next` — 켰거나 무시한 팩은 빼고, 끝난 결과에만 한 줄.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.pack_hints import PackHints, Signals, judge, read_signals
from alture_jarvis.pack_request import PACK_REQUEST_TOOL, TOOL_NAME, PackRequestTools, attach_next_line, model_bytes
from alture_jarvis.packs import PackError, PackRegistry, _read_next
from alture_jarvis.permissions import ALWAYS_ASK, NEVER_BYPASS
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec

REPO = Path(__file__).resolve().parents[1]


def _row(rows: list[dict[str, Any]], pack: str) -> dict[str, Any]:
    return next(row for row in rows if row["pack"] == pack)


# ── 1. 판정 표 ─────────────────────────────────────────────────────────────

CASES = [
    # (이름, 신호, 맞아야 할 팩들)
    ("아무것도 없음 · 윈도우", Signals(os="win", gpu_gb=None), set()),
    ("3ds Max 만", Signals(os="win", apps={"3ds Max": "설치 목록"}, gpu_gb=None), {"animator"}),
    ("블렌더 · 카드 6GB", Signals(os="win", apps={"Blender": "5.2"}, gpu_gb=6.0), {"animator"}),
    ("블렌더 · 카드 8GB", Signals(os="win", apps={"Blender": "5.2"}, gpu_gb=8.0), {"animator", "gen3d"}),
    ("유니티만", Signals(os="win", apps={"Unity": "6000.6.3f1"}, gpu_gb=4.0), {"game"}),
    ("뱀부 · 카드 못 읽음", Signals(os="win", apps={"Bambu Studio": "x"}, gpu_gb=None), set()),
    # 11-16 바로잡음: 12GB 기준은 영상 생성(genvideo) 것 · 영상 읽기(video)는 그래픽카드 기준 없음(신호도 없어 권하지 않음).
    ("카드 12GB 만", Signals(os="win", gpu_gb=12.0), {"gen3d", "genvideo"}),
    ("카드 11.9GB", Signals(os="win", gpu_gb=11.9), {"gen3d"}),
    ("카드 24GB · 3ds Max · 유니티", Signals(os="win", apps={"3ds Max": "a", "Unity": "b"}, gpu_gb=24.0),
     {"animator", "game", "gen3d", "genvideo"}),
    ("맥 16GB", Signals(os="mac", gpu_gb=16.0), {"gen3d"}),
    ("맥 64GB", Signals(os="mac", gpu_gb=64.0), {"gen3d"}),
    ("다른 OS · 카드 24GB", Signals(os="other", gpu_gb=24.0), {"gen3d"}),
    ("맥 8GB · 블렌더", Signals(os="mac", apps={"Blender": "5.2"}, gpu_gb=8.0), {"animator"}),
    ("맥 메모리 못 읽음", Signals(os="mac", gpu_gb=None), set()),
]


@pytest.mark.parametrize("name,signals,fits", CASES, ids=[c[0] for c in CASES])
def test_the_table(name: str, signals: Signals, fits: set[str]) -> None:
    rows = judge(signals)
    assert {row["pack"] for row in rows if row["fits"]} == fits, name
    for row in rows:
        assert set(row) == {"pack", "fits", "reasons", "blockers", "enabled", "dismissed"}
        if row["fits"]:
            assert row["reasons"] and not row["blockers"], "맞으면 까닭이 있고 막힘이 없다"


def test_blockers_say_why() -> None:
    rows = judge(Signals(os="win", apps={"Bambu Studio": "x"}, gpu_gb=6.0))
    gen3d = _row(rows, "gen3d")
    assert not gen3d["fits"] and gen3d["reasons"], "뱀부는 맞는 신호지만 카드가 막는다"
    assert "6GB" in gen3d["blockers"][0] and "8GB" in gen3d["blockers"][0]
    mac = _row(judge(Signals(os="mac", gpu_gb=8.0)), "gen3d")
    assert "통합 메모리" in mac["blockers"][0] and "16GB" in mac["blockers"][0]
    unknown = _row(judge(Signals(os="win", gpu_gb=None)), "genvideo")
    assert "못 읽음" in unknown["blockers"][0]
    small = _row(judge(Signals(os="win", gpu_gb=8.0)), "genvideo")
    assert "8GB" in small["blockers"][0] and "12GB" in small["blockers"][0] and "엔비디아" in small["blockers"][0]
    mac = _row(judge(Signals(os="mac", gpu_gb=64.0)), "genvideo")
    assert not mac["fits"] and "CUDA" in mac["blockers"][0] and "윈도우" in mac["blockers"][0], "맥은 메모리가 커도 실행기가 없어 막는다"
    assert "라데온" in mac["blockers"][0] and "라데온" in unknown["blockers"][0], "엔비디아가 아닌 카드는 nvidia-smi 로 못 읽어 「못 읽음」으로 온다"
    assert _row(judge(Signals(os="win", gpu_gb=12.0)), "genvideo")["fits"], "12GB 는 맞음(3060 실측 카드 최대 11,764MiB)"
    for signals in (Signals(os="win", gpu_gb=None), Signals(os="win", gpu_gb=2.0), Signals(os="mac", gpu_gb=8.0)):
        video = _row(judge(signals), "video")
        assert video["blockers"] == [] and video["reasons"] == [], "영상 읽기는 그래픽카드로 막지도 권하지도 않는다"


def test_enabled_and_dismissed_are_marked_not_hidden() -> None:
    rows = judge(Signals(os="win", apps={"3ds Max": "a"}, gpu_gb=24.0), enabled={"gen3d"}, dismissed={"animator"})
    assert _row(rows, "gen3d")["enabled"] and _row(rows, "gen3d")["fits"]
    assert _row(rows, "animator")["dismissed"] and _row(rows, "animator")["fits"]


def test_max_is_looked_for_only_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import pack_hints

    monkeypatch.setattr(pack_hints, "_find_max", lambda: "설치 목록")
    quiet = {"Blender": lambda: "", "Bambu Studio": lambda: ""}
    assert "3ds Max" in read_signals(finders=dict(quiet), gpu=lambda _os: None, os_name="win").apps
    assert "3ds Max" not in read_signals(finders=dict(quiet), gpu=lambda _os: None, os_name="mac").apps


def test_a_finder_that_breaks_does_not_break_the_rest() -> None:
    def boom() -> str:
        raise RuntimeError("레지스트리 막힘")

    signals = read_signals(finders={"3ds Max": boom, "Blender": lambda: "5.2", "Bambu Studio": lambda: ""},
                           gpu=lambda _os: 12.0, os_name="win")
    assert signals.apps == {"Blender": "5.2"} and signals.gpu_gb == 12.0
    assert any("3ds Max" in err for err in signals.errors)


# ── 2. 몰래 켜지 않음 · 밖으로 안 보냄 · 무시 · 캐시 ─────────────────────────────

def test_dismiss_survives_reload_and_toggling(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path)
    registry.dismiss_hint("animator")
    registry.set_enabled("gen3d", True)
    registry.set_enabled("gen3d", False)  # ★ 켜고 끌 때 「무시」를 덮어 지우면 안 된다
    again = PackRegistry(REPO / "packs", tmp_path)
    assert again.hint_dismissed() == {"animator"}
    data = json.loads((tmp_path / "packs.json").read_text(encoding="utf-8"))
    assert data["hint_dismissed"] == ["animator"] and data["enabled"] == []
    with pytest.raises(PackError):
        registry.dismiss_hint("nope")


def test_old_state_file_without_dismissed_still_reads(tmp_path: Path) -> None:
    (tmp_path / "packs.json").write_text(json.dumps({"enabled": ["game"]}), encoding="utf-8")
    registry = PackRegistry(REPO / "packs", tmp_path)
    assert registry.is_enabled("game") and registry.hint_dismissed() == set()


class _SpyRegistry(PackRegistry):
    def set_enabled(self, pack_id: str, on: bool) -> dict[str, Any]:  # pragma: no cover — 불리면 시험이 떨어진다
        raise AssertionError("권하기가 팩을 켰다")


def test_hints_never_enable_and_cache_for_a_day(tmp_path: Path) -> None:
    registry = _SpyRegistry(REPO / "packs", tmp_path)
    reads: list[int] = []
    now = [1000.0]

    def reader() -> Signals:
        reads.append(1)
        return Signals(os="win", apps={"3ds Max": "a"}, gpu_gb=24.0)

    hints = PackHints(registry, reader=reader, clock=lambda: now[0])
    first = hints.hints()
    assert set(first["suggest"]) == {"animator", "gen3d", "genvideo"}  # 11-16: 12GB+ 는 영상 생성(genvideo) · 영상 읽기는 기준 없음
    registry.dismiss_hint("genvideo")
    second = hints.hints()
    assert "genvideo" not in second["suggest"] and len(reads) == 1, "무시는 바로 반영 · 찾기는 다시 안 함"
    now[0] += 23 * 3600
    hints.hints()
    assert len(reads) == 1
    now[0] += 2 * 3600
    hints.hints()
    assert len(reads) == 2, "하루가 지나면 다시 잰다"
    hints.hints(fresh=True)
    assert len(reads) == 3
    assert {row["pack"] for row in first["hints"]} == {"animator", "game", "gen3d", "video", "genvideo"}
    assert all(row.get("name") for row in first["hints"])


def test_reading_this_pc_sends_nothing_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """진짜 찾기 함수로 한 판 — 그동안 연결 시도가 0 이어야 한다.

    ★ 11-16 저녁 전체 회귀(-n 4): 같은 일꾼 안 다른 시험의 뒤쪽 스레드가 건 `127.0.0.1:9222`(크롬 디버그) 연결이 전역 가로채기에
    잡혀 떨어졌다(혼자 돌리면 통과). 찾기를 부른 **이 스레드**의 연결만 센다 — 남의 스레드 연결은 원래대로 보낸다.
    """
    import threading

    tried: list[Any] = []
    me = threading.get_ident()
    real_connect, real_connect_ex, real_create = socket.socket.connect, socket.socket.connect_ex, socket.create_connection

    def record(self: socket.socket, address: Any) -> Any:
        if threading.get_ident() != me:
            return real_connect(self, address)
        tried.append(address)
        raise OSError("시험: 밖으로 보내지 않는다")

    def record_ex(self: socket.socket, address: Any) -> int:
        if threading.get_ident() != me:
            return real_connect_ex(self, address)
        tried.append(address)
        return 1

    def record_create(*args: Any, **kwargs: Any) -> Any:
        if threading.get_ident() != me:
            return real_create(*args, **kwargs)
        tried.append(args)
        raise OSError("시험: 밖으로 보내지 않는다")

    monkeypatch.setattr(socket.socket, "connect", record)
    monkeypatch.setattr(socket.socket, "connect_ex", record_ex)
    monkeypatch.setattr(socket, "create_connection", record_create)
    signals = read_signals(unity_editors=lambda: {})
    assert tried == [], f"찾기가 연결을 시도했다: {tried}"
    assert isinstance(signals.apps, dict)


# ── 3. 켜 달라고 청하기 — 게이트 · 저장소는 진짜 ──────────────────────────────────

def _setup(tmp_path: Path, **gate: Any) -> tuple[ToolGateway, PackRegistry, PackRequestTools, JobStore]:
    store = JobStore(tmp_path / "jobs.db")
    gateway = ToolGateway(store, EventBus(), **gate)
    registry = PackRegistry(REPO / "packs", tmp_path / "data")
    tools = PackRequestTools(registry, store)
    tools.register(gateway)
    return gateway, registry, tools, store


ARGS = {"pack": "animator", "why": "이 모션을 블렌더 뼈대에 입히려고"}


def test_name_is_in_both_closed_lists() -> None:
    assert TOOL_NAME in ALWAYS_ASK and TOOL_NAME in NEVER_BYPASS


@pytest.mark.parametrize("mode", [
    {}, {"auto_approve_reversible": True}, {"auto_approve_shell": True}, {"auto_approve_all": True},
    {"auto_approve_all": True, "auto_approve_reversible": True, "auto_approve_shell": True},
], ids=["수동", "편집자동", "셸자동", "권한무시", "전부"])
def test_every_mode_asks_a_person(tmp_path: Path, mode: dict[str, Any]) -> None:
    gateway, registry, _tools, store = _setup(tmp_path, **mode)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.status == "approval_required", f"{mode}: 카드 없이 지나갔다"
    assert not registry.is_enabled("animator"), "사람이 누르기 전에 켜졌다"
    pending = store.list_approvals(10, "pending")
    assert len(pending) == 1 and pending[0]["tool_name"] == TOOL_NAME


def test_card_carries_pack_json_and_size(tmp_path: Path) -> None:
    gateway, _registry, tools, store = _setup(tmp_path)
    gateway.execute(TOOL_NAME, {"pack": "gen3d", "why": "그림 한 장을 3D 로"})
    target = gateway.describe_approval(store.list_approvals(1, "pending")[0])["target"]
    pack = json.loads((REPO / "packs" / "gen3d" / "pack.json").read_text(encoding="utf-8"))
    assert target["summary"] == pack["summary"] and target["why"] == "그림 한 장을 3D 로"
    # 11-16 ADR-PACK-1: 권한 글은 이 기계 꼴로 푼다(`{docs}` 자리 표시).
    from alture_jarvis.packs import localize_permissions
    assert target["permissions"] == localize_permissions({key: pack["permissions"][key] for key in ("reads", "writes", "runs", "network")})
    assert target["download_bytes"] > 9_000_000_000 and "GB" in target["download"]
    registry = tools.registry
    win = model_bytes(registry.packs["gen3d"], ("win", "x64"))
    mac = model_bytes(registry.packs["gen3d"], ("macos", "arm64"))
    assert win - mac == 715040905 - 1788647, "이 기계용 실행기만 센다"
    assert model_bytes(registry.packs["animator"]) == 0


def test_approve_then_enabled_with_counts(tmp_path: Path) -> None:
    gateway, registry, _tools, store = _setup(tmp_path)
    gateway.execute(TOOL_NAME, {"pack": "gen3d", "why": "그림을 3D 로"})
    nonce = store.list_approvals(1, "pending")[0]["nonce"]
    gateway.decide(nonce, True)
    out = gateway.execute(TOOL_NAME, {"pack": "gen3d", "why": "그림을 3D 로"})
    assert out.ok and registry.is_enabled("gen3d")
    result = out.result
    assert result["tool_count"] == len(registry.packs["gen3d"].tools) > 0
    assert "받기" in result["models"]["note"] and result["models"]["download_bytes"] > 0
    assert [row["pack"] for row in result["next"]] == ["animator", "video", "genvideo"]


def test_denied_is_not_asked_again_in_the_same_work(tmp_path: Path) -> None:
    gateway, registry, _tools, store = _setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    gateway.decide(store.list_approvals(1, "pending")[0]["nonce"], False)
    again = gateway.execute(TOOL_NAME, dict(ARGS))
    assert not again.ok and "pack_request_declined" in again.error and "거절" in again.error
    assert len(store.list_approvals(50)) == 1, "카드를 새로 만들었다(조르기)"
    assert not registry.is_enabled("animator")


def test_a_pending_card_is_not_doubled(tmp_path: Path) -> None:
    gateway, _registry, _tools, store = _setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    second = gateway.execute(TOOL_NAME, dict(ARGS))
    assert not second.ok and "pack_request_pending" in second.error
    assert len(store.list_approvals(50)) == 1


def test_expired_counts_as_not_turned_on_and_window_ends(tmp_path: Path) -> None:
    gateway, _registry, tools, store = _setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    created = time.time()
    tools.clock = lambda: created + 3600  # 카드 수명(30분)이 지났다
    expired = gateway.execute(TOOL_NAME, dict(ARGS))
    assert not expired.ok and "만료" in expired.error
    tools.clock = lambda: created + 3 * 3600  # 바깥 부름의 「같은 일」 창(2시간) 밖
    assert gateway.execute(TOOL_NAME, dict(ARGS)).status == "approval_required"


def test_another_job_may_ask_again(tmp_path: Path) -> None:
    gateway, _registry, tools, store = _setup(tmp_path)
    store_rows: list[dict[str, Any]] = [
        {"tool_name": TOOL_NAME, "job_id": "job-a", "arguments": dict(ARGS), "status": "denied",
         "created_at": time.time(), "expires_at": time.time() + 100}]
    tools.store = type("S", (), {"list_approvals": staticmethod(lambda limit=50, status="": store_rows)})()
    with pytest.raises(ValueError, match="pack_request_declined"):
        tools.check(dict(ARGS), "job-a")
    tools.check(dict(ARGS), "job-b")  # 다른 일은 막지 않는다


@pytest.mark.parametrize("args,needle", [
    ({"pack": "nope", "why": "x"}, "unknown_pack"),
    ({"pack": "animator", "why": "  "}, "why"),
    ({"pack": "animator", "why": "가" * 300}, "200"),
])
def test_bad_requests_get_no_card(tmp_path: Path, args: dict[str, Any], needle: str) -> None:
    gateway, _registry, _tools, store = _setup(tmp_path)
    out = gateway.execute(TOOL_NAME, args)
    assert not out.ok and needle in out.error and store.list_approvals(10) == []


def test_already_on_gets_no_card(tmp_path: Path) -> None:
    gateway, registry, _tools, store = _setup(tmp_path)
    registry.set_enabled("animator", True)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert not out.ok and out.error.startswith("already_enabled") and store.list_approvals(10) == []


def test_inside_a_job_the_card_pauses_the_job(tmp_path: Path) -> None:
    from alture_jarvis.jobs import ApprovalRequired

    gateway, registry, _tools, _store = _setup(tmp_path, auto_approve_all=True)
    with pytest.raises(ApprovalRequired):
        gateway.execute(TOOL_NAME, dict(ARGS), job_id="job-1")
    assert not registry.is_enabled("animator")


def test_model_sees_it_only_while_some_pack_is_off(tmp_path: Path) -> None:
    _gateway, registry, tools, _store = _setup(tmp_path)
    assert tools.active_ollama_tools == [PACK_REQUEST_TOOL]
    for pack_id in registry.packs:
        registry.set_enabled(pack_id, True)
    assert tools.active_ollama_tools == []


# ── 4. 바깥 클로드가 청한 것은 누르는 순간 켠다 ─────────────────────────────────

class _FakeRuntime:
    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway
        self.events = EventBus()
        self.published: list[tuple[str, Any]] = []
        self.events.publish = lambda name, payload: self.published.append((name, payload))  # type: ignore[method-assign]


def test_outside_request_turns_on_when_pressed(tmp_path: Path) -> None:
    from alture_jarvis.runtime import JarvisRuntime

    gateway, registry, _tools, store = _setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    nonce = store.list_approvals(1, "pending")[0]["nonce"]
    fake = _FakeRuntime(gateway)
    decision = gateway.decide(nonce, True)
    JarvisRuntime._enable_requested_pack(fake, decision, True)  # type: ignore[arg-type]
    assert registry.is_enabled("animator")
    assert fake.published and fake.published[-1][0] == "pack_enabled_by_request" and fake.published[-1][1]["ok"]
    assert store.get_approval(nonce)["status"] == "consumed"
    # 바깥 클로드가 같은 인자로 다시 불러도 두 번 켜지 않는다 — 「이미 켜짐」
    again = gateway.execute(TOOL_NAME, dict(ARGS))
    assert again.error.startswith("already_enabled")


def test_pressing_through_decide_approval_turns_it_on(tmp_path: Path) -> None:
    """화면의 승인 문(`/v1/approvals/{nonce}` → `runtime.decide_approval`) 길 그대로 — 연결이 빠지면 여기서 떨어진다."""
    import types

    from alture_jarvis.runtime import JarvisRuntime

    gateway, registry, _tools, store = _setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    nonce = store.list_approvals(1, "pending")[0]["nonce"]
    fake = _FakeRuntime(gateway)
    fake._move = lambda *a, **k: None  # type: ignore[attr-defined]
    fake._enable_requested_pack = types.MethodType(JarvisRuntime._enable_requested_pack, fake)  # type: ignore[attr-defined]
    JarvisRuntime.decide_approval(fake, nonce, True)  # type: ignore[arg-type]
    assert registry.is_enabled("animator")


def test_denied_or_job_requests_are_not_turned_on_by_the_hook(tmp_path: Path) -> None:
    from alture_jarvis.runtime import JarvisRuntime

    gateway, registry, _tools, store = _setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    nonce = store.list_approvals(1, "pending")[0]["nonce"]
    fake = _FakeRuntime(gateway)
    JarvisRuntime._enable_requested_pack(fake, gateway.decide(nonce, False), False)  # type: ignore[arg-type]
    assert not registry.is_enabled("animator")
    # 손자리 안 일의 카드는 일이 다시 돌며 켠다 — 여기서 켜지 않는다
    job_decision = {"tool_name": TOOL_NAME, "job_id": "job-1", "status": "approved", "arguments": dict(ARGS)}
    JarvisRuntime._enable_requested_pack(fake, job_decision, True)  # type: ignore[arg-type]
    assert not registry.is_enabled("animator") and fake.published == []


# ── 5. MCP ────────────────────────────────────────────────────────────────

def _mcp_body(execute: dict[str, Any] | None = None):
    # tests/ 에 __init__.py 가 없어 「tests.」 이름 가져오기는 돌리는 방식(-n · 순서)에 따라 깨진다 — 경로로 직접 불러온다.
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("_fixed_door_1115", Path(__file__).with_name("test_mcp_fixed_door_1115.py"))
    door = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(door)  # type: ignore[union-attr]
    _Body, _tool = door._Body, door._tool

    request = {**_tool(TOOL_NAME, risk="L2", schema=dict(PACK_REQUEST_TOOL["function"]["parameters"]))}
    packs = [{"id": "animator", "name": "애니메이터 팩", "enabled": False, "tools": ["anim_habit"]}]
    return _Body([request, _tool("anim_habit"), _tool("local_read_file")], packs=packs, execute=execute)


def test_mcp_lists_it_under_the_l1_cap_and_the_door_calls_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis.mcp_server import JarvisMcpBridge, ToolFilter

    monkeypatch.delenv("JARVIS_MCP_TOOLSET", raising=False)
    body = _mcp_body({"ok": False, "status": "approval_required", "approval_nonce": "n"})
    bridge = JarvisMcpBridge(token="t", client=body, tool_filter=ToolFilter(max_risk="L1"))
    names = [tool["name"] for tool in asyncio.run(bridge.list_tools())]
    assert TOOL_NAME in names and names.count(TOOL_NAME) == 1
    assert "anim_habit" not in names, "꺼진 팩 도구는 여전히 안 보인다"
    text, failed = asyncio.run(bridge.call("sonjari_tool", {"name": TOOL_NAME, "arguments": dict(ARGS)}))
    assert not failed and "팩 켜기" in text and "직접 누릅니다" in text
    assert body.posts[-1]["json"] == {"name": TOOL_NAME, "arguments": dict(ARGS)}
    direct, failed = asyncio.run(bridge.call(TOOL_NAME, dict(ARGS)))
    assert not failed and "팩 켜기" in direct


def test_mcp_exclude_still_wins() -> None:
    from alture_jarvis.mcp_server import JarvisMcpBridge, ToolFilter

    bridge = JarvisMcpBridge(token="t", client=_mcp_body(), tool_filter=ToolFilter(exclude=[TOOL_NAME]))
    assert TOOL_NAME not in [tool["name"] for tool in asyncio.run(bridge.list_tools())]


def test_mcp_already_on_is_not_an_error() -> None:
    from alture_jarvis.mcp_server import JarvisMcpBridge

    body = _mcp_body({"ok": False, "status": "failed", "error": "already_enabled: 애니메이터 팩은 이미 켜져 있다"})
    text, failed = asyncio.run(JarvisMcpBridge(token="t", client=body).call(TOOL_NAME, dict(ARGS)))
    assert not failed and text.startswith("already_enabled")


def test_mcp_door_refusal_points_at_the_request() -> None:
    from alture_jarvis.mcp_server import JarvisMcpBridge

    bridge = JarvisMcpBridge(token="t", client=_mcp_body())
    text, failed = asyncio.run(bridge.call("sonjari_tool", {"name": "anim_habit", "arguments": {}}))
    assert failed and TOOL_NAME in text and 'pack="animator"' in text and "대신 켜지 마세요" in text


# ── 안내 문구 ────────────────────────────────────────────────────────────────

def test_capability_card_points_at_the_request_with_the_real_pack_id() -> None:
    """카드 분류(`3d`)와 팩 id(`gen3d`)가 다르다 — 켜 달라는 문에는 **실린 팩 id** 가 가야 하고, 켜져 있으면 꺼짐 표시가 없다."""
    from alture_jarvis.capability_cards import _pack_groups, load_cards, pack_of_group, render_search

    pool = load_cards()
    shipped = set(PackRegistry(REPO / "packs", Path("__unused__")).packs)
    groups = _pack_groups(pool)
    assert groups and all(pack_of_group(group) in shipped for group in groups), "카드 분류마다 실린 팩이 있어야 한다"
    off = render_search("3d/image-to-3d", enabled_packs=set(), cards=pool)
    assert 'sonjari_pack_request`(pack="gen3d"' in off and "대신 켜지 마세요" in off
    on = render_search("3d/image-to-3d", enabled_packs={"gen3d"}, cards=pool)
    assert "꺼져 있습니다" not in on, "3D 팩을 켰는데 카드가 꺼짐이라고 말한다(11-16 이전 버그)"
    game = render_search("유니티 참조", enabled_packs=set(), cards=pool, lang="en")
    assert 'sonjari_pack_request` (pack="game"' in game


@pytest.mark.parametrize("module,pack", [("animator_tools", "animator"), ("gen3d_tools", "gen3d"),
                                         ("unity_tools", "game"), ("video_tools", "video")])
def test_pack_disabled_points_at_the_request(module: str, pack: str) -> None:
    source = (REPO / "src" / "alture_jarvis" / f"{module}.py").read_text(encoding="utf-8")
    line = next(line for line in source.splitlines() if "pack_disabled:" in line)
    assert f'sonjari_pack_request(pack=\\"{pack}\\"' in line and "대신 켜지 마라" in line


def test_animator_refusal_message_at_runtime(tmp_path: Path) -> None:
    from alture_jarvis.animator_tools import AnimatorTools
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    tools = AnimatorTools(config, packs=PackRegistry(REPO / "packs", tmp_path / "d"))
    with pytest.raises(PermissionError) as caught:
        tools._check()
    assert "pack_disabled" in str(caught.value) and TOOL_NAME in str(caught.value)


# ── 6. 다음 팩 ────────────────────────────────────────────────────────────────

def test_shipped_next() -> None:
    registry = PackRegistry(REPO / "packs", Path("__unused__"))
    assert [item["pack"] for item in registry.packs["gen3d"].next] == ["animator", "video", "genvideo"]
    assert [item["pack"] for item in registry.packs["animator"].next] == ["game"]
    assert registry.problems == []


@pytest.mark.parametrize("raw,needle", [
    ({"pack": "game"}, "꼴"),
    ([{"pack": "gen3d", "when": "x"}], "다른 팩"),
    ([{"pack": "Bad!", "when": "x"}], "다른 팩"),
    ([{"pack": "game", "when": ""}], "when"),
    ([{"pack": "game", "when": "가" * 81}], "when"),
    ([{"pack": "game", "when": "x", "go": 1}], "pack · when"),
])
def test_next_is_validated(raw: Any, needle: str) -> None:
    with pytest.raises(PackError, match=needle):
        _read_next("gen3d", raw)


def test_next_skips_enabled_and_dismissed(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path)
    assert [row["pack"] for row in registry.next_for("gen3d")] == ["animator", "video", "genvideo"]
    registry.set_enabled("animator", True)
    registry.dismiss_hint("video")
    registry.set_enabled("genvideo", True)
    assert registry.next_for("gen3d") == []


def test_next_line_only_on_finished_results(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path)
    note = attach_next_line(registry)
    done = note("gen_3d_status", {"ok": True, "state": "done", "receipt": {"faces": 1}})
    assert "애니메이터" in done["next_pack"] and "sonjari_pack_request" in done["next_pack"]
    assert "next_pack" not in note("gen_3d_status", {"ok": True, "state": "running"}), "상태 묻기마다 붙이지 않는다"
    assert "next_pack" not in note("gen_3d_status", {"ok": False, "receipt": {"x": 1}})
    assert "next_pack" not in note("local_read_file", {"ok": True, "files": ["a"]}), "팩 도구가 아니다"
    assert "next_pack" not in note("video_read", {"ok": True, "files": ["a"]}), "영상 팩은 next 가 없다"
    registry.set_enabled("animator", True)
    registry.set_enabled("video", True)
    registry.set_enabled("genvideo", True)
    assert "next_pack" not in note("gen_3d_status", {"ok": True, "receipt": {"x": 1}}), "다 켰으면 안 붙는다"


def test_gateway_result_note_is_applied_and_cannot_break_a_tool(tmp_path: Path) -> None:
    gateway = ToolGateway(JobStore(tmp_path / "j.db"), EventBus())
    gateway.register(ToolSpec(name="t", description="t", parameters={"type": "object", "properties": {}},
                              handler=lambda _a: {"ok": True, "files": ["x"]}, risk_level=RiskLevel.L0))
    gateway.result_note = lambda name, result: {**result, "next_pack": "다음"}
    assert gateway.execute("t", {}).result["next_pack"] == "다음"

    def boom(name: str, result: Any) -> Any:
        raise RuntimeError("x")

    gateway.result_note = boom
    out = gateway.execute("t", {})
    assert out.ok and "next_pack" not in out.result


# ── API ─────────────────────────────────────────────────────────────────────

def test_api_hints_and_dismiss(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=tmp_path / "docs", control_token="test-token", camera_enabled=False,
                          vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis
    runtime.pack_hints.reader = lambda: Signals(os="win", apps={"3ds Max": "설치 목록"}, gpu_gb=8.0)
    client = TestClient(app)
    head = {"X-JARVIS-TOKEN": "test-token"}
    assert client.get("/v1/packs/hints").status_code == 401
    body = client.get("/v1/packs/hints", headers=head).json()
    assert set(body["suggest"]) == {"animator", "gen3d"}
    animator = _row(body["hints"], "animator")
    assert {"pack", "fits", "reasons", "blockers", "enabled", "dismissed"} <= set(animator)
    assert client.post("/v1/packs/animator/dismiss_hint", headers=head).json() == {"pack": "animator", "dismissed": True}
    assert client.post("/v1/packs/nope/dismiss_hint", headers=head).status_code == 404
    assert client.get("/v1/packs/hints", headers=head).json()["suggest"] == ["gen3d"]
    assert not runtime.packs.is_enabled("animator"), "권하기 · 무시가 팩을 켜면 안 된다"
    enabled = client.post("/v1/packs/gen3d/enable", headers=head).json()
    assert [row["pack"] for row in enabled["next_packs"]] == ["video", "genvideo"], "무시한 animator 는 다음 팩에서도 빠진다"
    # 런타임에 도구가 등록돼 있고 L2 다
    tool = next(t for t in client.get("/v1/tools").json() if t["name"] == TOOL_NAME)
    assert tool["risk_level"] == "L2"
