"""팩 켜기 맡김 (2026-11-16 · `docs/ADR_팩켜기맡김_2026-11-16.ko.md` 시험 계획).

지키는 것:
1. 맡김이 켜졌고 **바깥 클로드**(일 번호 없음)가 부른 팩 켜기만 카드 없이 켜진다 — 기록 이유 `delegated_by_person`.
2. 맡김 꺼짐 · 손자리 안 일(일 번호 있음) · 다른 L2 도구는 어느 모드에서도 그대로 카드.
3. 맡김은 packs.json 에 남고 팩 켜고 끌 때 안 지워진다. 켜는 길은 사람 쪽 API 뿐이고, 도구 목록에 그 일을 하는 도구가 없다.
4. 도구 설명은 목록을 줄 때마다 「꺼진 팩 · 하는 일 · 맞는 까닭 · 먼저 묻기」를 싣는다. L2 일괄 경고(「되돌릴 수 없는」)는 이 도구에 안 붙는다.
5. 기능 안내가 맞는 카드를 못 찾으면 꺼진 팩 목록을 같이 준다.
6. pack.json 경로는 `{docs}` 자리 표시로 적고 기계마다 푼다 · 모든 pack.json 글에 제어 문자 0 · 도구 수는 이 기계에서 쓰는 것.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.pack_request import TOOL_NAME, PackRequestTools
from alture_jarvis.packs import PackRegistry, localize, localize_permissions, tools_here
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec

REPO = Path(__file__).resolve().parents[1]


def _audits(db_path: Path, event: str) -> list[dict[str, Any]]:
    import sqlite3

    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT payload_json FROM audit_log WHERE event = ? ORDER BY rowid DESC", (event,)).fetchall()
    return [json.loads(row[0] or "{}") for row in rows]
ARGS = {"pack": "animator", "why": "블렌더 동작의 팔 뚫림을 고치려고"}


def _setup(tmp_path: Path, *, delegate: bool = False, hints: Any = None, **gate: Any):
    store = JobStore(tmp_path / "jobs.db")
    gateway = ToolGateway(store, EventBus(), **gate)
    registry = PackRegistry(REPO / "packs", tmp_path / "data")
    if delegate:
        registry.set_claude_may_enable(True)
    seen: list[dict[str, Any]] = []
    tools = PackRequestTools(registry, store, hints=hints, on_delegated=seen.append)
    tools.register(gateway)
    return gateway, registry, store, seen


# ── 1 · 2. 게이트 ────────────────────────────────────────────────────────────

MODES = [{}, {"auto_approve_reversible": True}, {"auto_approve_shell": True}, {"auto_approve_all": True}]
MODE_IDS = ["수동", "편집자동", "셸자동", "권한무시"]


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
def test_delegated_outside_call_turns_on_without_a_card(tmp_path: Path, mode: dict[str, Any]) -> None:
    gateway, registry, store, seen = _setup(tmp_path, delegate=True, **mode)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.ok and registry.is_enabled("animator"), f"{mode}: 맡겼는데 안 켜졌다 — {out.status} {out.error}"
    assert store.list_approvals(10, "pending") == [], "맡겼는데 카드가 떴다"
    assert out.result["by"] == "delegated"
    assert seen and seen[0]["pack"] == "animator", "맡김으로 켰는데 화면 알림 자리가 안 불렸다"
    audits = _audits(tmp_path / "jobs.db", "approval_auto_approved")
    assert audits and audits[0]["reason"] == "delegated_by_person"


@pytest.mark.parametrize("mode", MODES, ids=MODE_IDS)
def test_not_delegated_still_asks_in_every_mode(tmp_path: Path, mode: dict[str, Any]) -> None:
    gateway, registry, store, seen = _setup(tmp_path, delegate=False, **mode)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.status == "approval_required" and not registry.is_enabled("animator")
    assert len(store.list_approvals(10, "pending")) == 1 and not seen


def test_inside_a_job_is_never_delegated(tmp_path: Path) -> None:
    """손자리 안 모델의 청(일 번호 있음)은 맡기지 않는다 — 웹 · 문서를 읽던 로컬 모델이 글에 끌릴 수 있다."""
    from alture_jarvis.tool_gateway import ApprovalRequired

    gateway, registry, store, seen = _setup(tmp_path, delegate=True, auto_approve_all=True)
    job = store.create_job("chat", "팩 켜기 시험", {})
    with pytest.raises(ApprovalRequired):
        gateway.execute(TOOL_NAME, dict(ARGS), job_id=job["id"])
    assert not registry.is_enabled("animator") and not seen


@pytest.mark.parametrize("tool", ["google_gmail_send", "payment_confirm", "local_install_app", "local_delete_file"])
def test_delegation_opens_no_other_door(tmp_path: Path, tool: str) -> None:
    gateway, _registry, store, _seen = _setup(tmp_path, delegate=True)
    gateway.register(ToolSpec(name=tool, description=tool, parameters={"type": "object", "properties": {}},
                              risk_level=RiskLevel.L2, handler=lambda _args: {"ok": True}))
    out = gateway.execute(tool, {})
    assert out.status == "approval_required", f"맡김이 {tool} 까지 열었다"


def test_a_broken_delegation_check_falls_back_to_the_card(tmp_path: Path) -> None:
    gateway, registry, store, _seen = _setup(tmp_path, delegate=True)

    def boom(_args: dict[str, Any], _job: str) -> bool:
        raise RuntimeError("판정 고장")

    gateway.delegated_approvals[TOOL_NAME] = boom
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.status == "approval_required" and not registry.is_enabled("animator")


def test_declined_in_the_last_two_hours_still_blocks_even_when_delegated(tmp_path: Path) -> None:
    """맡기기 전에 같은 팩 카드를 거절했으면 그 일에서는 다시 청하지 않는다(조르기 막기가 맡김보다 먼저)."""
    gateway, registry, store, _seen = _setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    gateway.decide(store.list_approvals(1, "pending")[0]["nonce"], False)
    registry.set_claude_may_enable(True)
    again = gateway.execute(TOOL_NAME, dict(ARGS))
    assert not again.ok and "pack_request_declined" in again.error and not registry.is_enabled("animator")


def test_person_pressed_card_is_marked_person(tmp_path: Path) -> None:
    gateway, registry, store, seen = _setup(tmp_path)
    gateway.execute(TOOL_NAME, dict(ARGS))
    gateway.decide(store.list_approvals(1, "pending")[0]["nonce"], True)
    out = gateway.execute(TOOL_NAME, dict(ARGS))
    assert out.ok and out.result["by"] == "person" and not seen


# ── 3. 저장 · 사람 쪽 문 ─────────────────────────────────────────────────────

def test_delegation_is_saved_and_survives_toggling(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path / "data")
    assert registry.claude_may_enable() is False, "기본은 꺼짐이어야 한다"
    registry.set_claude_may_enable(True)
    registry.set_enabled("gen3d", True)
    registry.set_enabled("gen3d", False)
    registry.dismiss_hint("video")
    again = PackRegistry(REPO / "packs", tmp_path / "data")
    assert again.claude_may_enable() is True and again.hint_dismissed() == {"video"}
    assert again.listing()["claude_may_enable"] is True


def test_no_tool_can_switch_delegation_on(tmp_path: Path) -> None:
    """맡김을 켜는 도구가 목록에 있으면 클로드가 스스로 맡길 수 있다 — 이름 · 설명 어디에도 없어야 한다."""
    gateway, _registry, _store, _seen = _setup(tmp_path)
    for tool in gateway.list_tools():
        params = json.dumps(tool.get("parameters") or {}, ensure_ascii=False)
        assert "claude_may_enable" not in tool["name"] and "claude_may_enable" not in params
        assert "delegate" not in tool["name"]


def test_delegate_api_needs_the_token_and_takes_only_booleans(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=tmp_path / "docs", control_token="test-token", camera_enabled=False,
                          vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    runtime = app.state.jarvis
    client = TestClient(app)
    head = {"X-JARVIS-TOKEN": "test-token"}
    assert client.post("/v1/packs/delegate", json={"on": True}).status_code == 401
    assert client.post("/v1/packs/delegate", json={"on": "yes"}, headers=head).status_code == 400
    assert not runtime.packs.claude_may_enable()
    ok = client.post("/v1/packs/delegate", json={"on": True}, headers=head)
    assert ok.status_code == 200 and ok.json() == {"claude_may_enable": True} and runtime.packs.claude_may_enable()
    assert client.get("/v1/packs", headers=head).json()["claude_may_enable"] is True
    # 「delegate」를 팩 이름으로 읽는 길(`/v1/packs/{pack_id}/{action}`)과 엉키지 않는다
    assert client.post("/v1/packs/delegate/enable", headers=head).status_code == 404


# ── 4. 설명 ──────────────────────────────────────────────────────────────────

def _fake_hints() -> dict[str, Any]:
    return {"hints": [{"pack": "animator", "fits": True, "reasons": ["블렌더가 깔려 있음(4.5 · /Applications/Blender.app)"]},
                      {"pack": "video", "fits": False, "reasons": []}]}


def test_description_lists_off_packs_with_why_and_asks_first(tmp_path: Path) -> None:
    gateway, registry, _store, _seen = _setup(tmp_path, hints=_fake_hints)
    registry.set_enabled("gen3d", True)
    text = next(tool["description"] for tool in gateway.list_tools() if tool["name"] == TOOL_NAME)
    assert "- animator(" in text and "- video(" in text and "- gen3d(" not in text, "켜진 팩이 목록에 있거나 꺼진 팩이 빠졌다"
    assert "이 PC 에 맞음: 블렌더가 깔려 있음" in text
    assert "/Applications" not in text, "열쇠 없이 읽히는 목록에 설치 경로가 새면 안 된다"
    assert "먼저 묻고" in text and "카드" in text


def test_description_says_it_turns_on_directly_when_delegated(tmp_path: Path) -> None:
    gateway, _registry, _store, _seen = _setup(tmp_path, delegate=True)
    text = next(tool["description"] for tool in gateway.list_tools() if tool["name"] == TOOL_NAME)
    assert "카드 없이 바로 켜진다" in text and "먼저 물어라" in text


def test_mcp_does_not_add_the_irreversible_warning_to_the_pack_request() -> None:
    from alture_jarvis.mcp_server import describe

    assert "되돌릴 수 없는" not in describe({"name": TOOL_NAME, "risk_level": "L2", "description": "청한다"})
    assert "되돌릴 수 없는" in describe({"name": "google_gmail_send", "risk_level": "L2", "description": "보낸다"})


# ── 5. 기능 안내 ──────────────────────────────────────────────────────────────

def test_guide_with_no_card_points_at_off_packs() -> None:
    from alture_jarvis.capability_cards import render_search

    off = [{"id": "animator", "name": "애니메이터 팩", "summary": "3ds Max 게임 애니메이션을 클로드와 같이 한다. 더 긴 글."}]
    text = render_search("블렌더 모션", off_packs=off, cards=[])
    # 카드가 하나도 없는 판이면 예전 글 — 카드가 있는 판에서 보자.
    from alture_jarvis.capability_cards import load_cards

    text = render_search("zzz-없는-낱말-블렌더", off_packs=off, cards=load_cards())
    assert "sonjari_pack_request" in text and "- animator(애니메이터 팩): 3ds Max 게임 애니메이션을 클로드와 같이 한다" in text
    assert "더 긴 글" not in text
    plain = render_search("zzz-없는-낱말-블렌더", off_packs=[], cards=load_cards())
    assert "꺼진 팩" not in plain


# ── 6. pack.json 글 ───────────────────────────────────────────────────────────

def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


@pytest.mark.parametrize("path", sorted((REPO / "packs").glob("*/pack.json")), ids=lambda p: p.parent.name)
def test_pack_json_has_no_control_chars_or_raw_windows_docs_path(path: Path) -> None:
    """11-16: `내 문서\\Sonjari\\animator` 의 `\\a` 가 벨 문자로 읽혀 「Sonjari□nimator」가 됐다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for text in _strings(data):
        assert not any(ord(ch) < 32 and ch not in "\n\t" for ch in text), f"제어 문자: {text[:80]!r}"
        assert "내 문서\\" not in text, f"윈도우 경로를 그대로 적음 — {{docs}}/… 로: {text[:80]}"


def test_docs_placeholder_is_localized_per_machine() -> None:
    assert localize("{docs}/Sonjari/animator 아래", "darwin") == "~/Documents/Sonjari/animator 아래"
    assert localize("{docs}/Sonjari/animator 아래", "win32") == "내 문서\\Sonjari\\animator 아래"
    assert localize("({docs}/Sonjari/gen3d)", "win32") == "(내 문서\\Sonjari\\gen3d)"
    perms = localize_permissions({"reads": ["{docs}/Sonjari/x"], "network": "없음"}, "darwin")
    assert perms == {"reads": ["~/Documents/Sonjari/x"], "network": "없음"}


def test_tool_count_is_what_this_machine_has(tmp_path: Path) -> None:
    registry = PackRegistry(REPO / "packs", tmp_path / "data")
    animator = registry.packs["animator"]
    assert len(tools_here(animator, "win32")) == len(animator.tools) == 18  # 11-18 anim_blender_setup · 11-19 균형 점검 · 키 정렬
    assert len(tools_here(animator, "darwin")) == 16, "맥에 없는 영상 자세 도구 둘을 빼야 한다"


# ── 7. 창을 다시 열어도 팩 카드 그대로(11-16 맥 실측) ───────────────────────────

def test_reconnect_replay_keeps_the_card_target(tmp_path: Path) -> None:
    """다시 붙을 때 재생하는 승인에도 `target` 이 붙어야 한다 — 빠지면 팩 카드가 「미리보기 없음」 일반 카드로 떨어진다."""
    import time

    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=tmp_path / "docs", control_token="test-token", camera_enabled=False,
                          vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    app.state.jarvis.store.create_approval(nonce="pack-nonce", job_id="", tool_name=TOOL_NAME, arguments=dict(ARGS),
                                           proof={}, expires_at=time.time() + 300)
    with TestClient(app) as client:
        with client.websocket_connect("/v1/ws", subprotocols=["jarvis", "test-token"]) as websocket:
            assert websocket.receive_json()["event"] == "connected"
            replay = websocket.receive_json()
    assert replay["replayed"] is True and replay["payload"]["nonce"] == "pack-nonce"
    target = replay["payload"].get("target") or {}
    assert target.get("kind") == "pack_enable" and target.get("pack") == "animator", "재생한 카드에 팩 설명이 빠졌다"
