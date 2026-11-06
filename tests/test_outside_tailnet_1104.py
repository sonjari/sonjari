"""밖에서도 쓰기 — 테일스케일 체크 목록 (설계_밖에서도쓰기_테일스케일_2026-11-04 §2-2 · §2-3 · §4 · §8).

지키는 것(양방향 표본):
- 단계 판정은 `status --json` 꾸민 표본으로: 설치 없음 · 꺼짐 · NeedsLogin · Running · 계정 다름 · 문 안 열림 · 다 됨.
  같은 계정이면 다음으로 가고, 다르면 멈춘다(한 방향만 보지 않는다).
- 밖에서 「PC not found」 까닭: 맥 테일스케일 꺼짐 · 로그인 만료 · 집 PC 잠듦 · 집 PC 는 켜졌는데 손자리가 답 없음.
- 집 PC 문은 8092 에만 serve 하고(Funnel · 8091 아님) 이미 걸려 있으면 다시 걸지 않는다.
- 맥 중계는 집 와이파이 길 먼저, 안 닿으면 테일넷 길 — 구슬 끝 알림은 한 번만.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from alture_jarvis import pairing, tailnet
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig

AUTH = {"X-JARVIS-TOKEN": "test-token"}


def raw_status(state="Running", tailnet_id="T-ONE", dns="home-pc.example.ts.net.", peers=None, auth_url=""):
    return {"BackendState": state, "AuthURL": auth_url,
            "CurrentTailnet": {"StableID": tailnet_id, "Name": "someone@example.com", "MagicDNSSuffix": "example.ts.net"} if tailnet_id else None,
            "Self": {"DNSName": dns, "Online": True, "OS": "windows", "KeyExpiry": "2027-05-01T00:00:00Z"},
            "Peer": {f"k{i}": p for i, p in enumerate(peers or [])}}


def runner(outputs: dict[str, tuple[int, str]], calls: list[list[str]] | None = None):
    def run(args, _timeout):  # type: ignore[no-untyped-def]
        if calls is not None:
            calls.append(list(args))
        return outputs.get(" ".join(args[:2]), outputs.get(args[0], (0, "")))
    return run


# ── 상태 읽기 ───────────────────────────────────────────────────────────────────────────────────────

def test_status_reads_only_the_fields_we_judge_by():
    peer = {"HostName": "Mac mini", "DNSName": "mac-mini.example.ts.net.", "Online": True, "OS": "macOS",
            "TailscaleIPs": ["100.64.0.2"], "PublicKey": "nodekey:secret"}
    got = tailnet.status(runner({"status --json": (0, json.dumps(raw_status(peers=[peer])))}))
    assert got["installed"] and got["state"] == "Running" and got["tailnet_id"] == "T-ONE"
    assert got["dns_name"] == "home-pc.example.ts.net"          # 끝 점은 뗀다
    assert got["peers"] == [{"name": "Mac mini", "dns_name": "mac-mini.example.ts.net", "online": True, "os": "macOS"}]
    assert "nodekey" not in json.dumps(got) and "100.64" not in json.dumps(got)   # 열쇠 · 주소는 화면에 안 보낸다


def test_status_when_not_installed_and_when_stopped():
    assert tailnet.status(runner({"status --json": (127, "")}))["installed"] is False
    # 꺼져 있으면 종료 코드가 0 이 아니어도 JSON 이 나온다 — 출력으로 판정
    stopped = tailnet.status(runner({"status --json": (1, json.dumps(raw_status(state="Stopped")))}))
    assert stopped["installed"] and stopped["state"] == "Stopped"
    broken = tailnet.status(runner({"status --json": (1, "failed to connect to local tailscaled")}))
    assert broken["installed"] and broken["state"] == "NoState"


# ── 단계 판정(§2-2 ①~⑤) ──────────────────────────────────────────────────────────────────────────────

def side(state="Running", tid="T-ONE", installed=True, dns="x.example.ts.net"):
    return {"installed": installed, "state": state, "tailnet_id": tid, "dns_name": dns}


@pytest.mark.parametrize("mac, pc, door, reached, stage, reason", [
    (side(installed=False, state="NotInstalled"), side(), False, False, "install", "not_installed_mac"),
    (side(), side(installed=False, state="NotInstalled"), False, False, "install", "not_installed_pc"),
    (side(state="NeedsLogin", tid=""), side(), False, False, "login", "sign_in_mac"),
    (side(), side(state="NeedsLogin", tid=""), False, False, "login", "sign_in_pc"),
    (side(state="Stopped"), side(), False, False, "login", "turn_on_mac"),
    (side(), side(tid="T-TWO"), False, False, "same_account", "different_account"),
    (side(), side(), False, False, "door", ""),
    (side(), side(), True, False, "reach", ""),
    (side(), side(), True, True, "done", ""),
])
def test_plan_walks_the_steps_in_order(mac, pc, door, reached, stage, reason):
    got = tailnet.plan(mac, pc, door_open=door, reached=reached)
    assert (got["stage"], got["reason"]) == (stage, reason)


def test_plan_without_the_pc_answer_does_not_pretend():
    assert tailnet.plan(side(), None, door_open=True, reached=True)["stage"] == "install"
    assert tailnet.plan(side(), None, door_open=True, reached=True)["reason"] == "pc_unknown"


def test_plan_says_serve_failed_only_when_it_failed():
    assert tailnet.plan(side(), {**side(), "serve_error": "serve_failed"}, door_open=False, reached=False)["reason"] == "serve_failed"


@pytest.mark.parametrize("me, why", [
    ({"installed": True, "state": "Stopped", "peers": []}, "tailscale_off"),
    ({"installed": True, "state": "NeedsLogin", "peers": []}, "sign_in_again"),
    ({"installed": True, "state": "Running", "peers": [{"dns_name": "home-pc.example.ts.net", "online": False}]}, "pc_asleep"),
    ({"installed": True, "state": "Running", "peers": [{"dns_name": "home-pc.example.ts.net", "online": True}]}, "pc_not_answering"),
    ({"installed": True, "state": "Running", "peers": []}, "pc_asleep"),
])
def test_why_the_pc_is_not_found_outside(me, why):
    assert tailnet.why_not_found(me, "home-pc.example.ts.net:8092") == why


def test_no_reason_without_a_tailnet_path():
    assert tailnet.why_not_found({"installed": True, "state": "Stopped"}, "") == ""


# ── 집 PC 문(8092)을 테일넷에만 ────────────────────────────────────────────────────────────────────────

def test_serve_door_uses_the_pair_door_port_over_tcp_and_never_funnel():
    calls: list[list[str]] = []
    served = {"value": False}

    def run(args, _timeout):  # type: ignore[no-untyped-def]
        calls.append(list(args))
        if args[:2] == ["serve", "status"]:
            body = {"TCP": {"8092": {"TCPForward": "127.0.0.1:8092"}}} if served["value"] else {}
            return 0, json.dumps(body)
        if args[:2] == ["serve", "--bg"]:
            served["value"] = True
            return 0, "Serve started"
        return 1, ""

    assert tailnet.serve_door(run) == {"ok": True}
    opened = [c for c in calls if c[:2] == ["serve", "--bg"]]
    assert opened == [["serve", "--bg", "--tcp", "8092", "tcp://127.0.0.1:8092"]]
    assert not any("funnel" in " ".join(c) or "8091" in " ".join(c) for c in calls)
    # 이미 걸려 있으면 다시 걸지 않는다
    calls.clear()
    assert tailnet.serve_door(run) == {"ok": True, "already": True}
    assert not any(c[:2] == ["serve", "--bg"] for c in calls)


def test_serve_door_reports_failure():
    run = runner({"serve status": (0, "{}"), "serve --bg": (1, "access denied")})
    got = tailnet.serve_door(run)
    assert got["ok"] is False and got["error"] == "serve_failed"


# ── 로그인 — 주소만 돌려주고 여는 것은 화면 ─────────────────────────────────────────────────────────────

def test_login_returns_the_auth_url_from_status_without_starting_anything():
    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("login 명령을 띄우면 안 된다")
    run = runner({"status --json": (0, json.dumps(raw_status(state="NeedsLogin", tailnet_id="",
                                                             auth_url="https://login.tailscale.com/a/abc")))})
    assert tailnet.login(run, popen=boom) == {"ok": True, "url": "https://login.tailscale.com/a/abc"}


def test_login_reads_the_url_the_cli_prints(monkeypatch):
    class Proc:
        def __init__(self) -> None:
            self.stdout = iter_lines(["To authenticate, visit:\n", "\n", "\thttps://login.tailscale.com/a/xyz\n"])

    run = runner({"status --json": (0, json.dumps(raw_status(state="NeedsLogin", tailnet_id="")))})
    got = tailnet.login(run, popen=lambda *a, **k: Proc(), sleep=lambda _s: None, wait=2.0)
    assert got == {"ok": True, "url": "https://login.tailscale.com/a/xyz"}


def test_login_when_already_signed_in_and_when_switching_account():
    run = runner({"status --json": (0, json.dumps(raw_status()))})
    assert tailnet.login(run, popen=lambda *a, **k: (_ for _ in ()).throw(AssertionError())) == {"ok": True, "url": ""}

    class Proc:
        def __init__(self) -> None:
            self.stdout = iter_lines(["\thttps://login.tailscale.com/a/switch\n"])

    assert tailnet.login(run, popen=lambda *a, **k: Proc(), force=True, sleep=lambda _s: None, wait=2.0)["url"].endswith("/switch")


class iter_lines:  # noqa: N801 — readline 만 흉내 낸다
    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)

    def readline(self) -> str:
        return self.lines.pop(0) if self.lines else ""


# ── 맥 중계: 집 와이파이 먼저, 안 되면 테일넷 ─────────────────────────────────────────────────────────────

def test_home_routes_order_and_dedup():
    assert pairing.home_routes({"address": "192.0.2.10:8092", "tailnet_address": "home-pc.example.ts.net:8092"}) == [
        ("lan", "192.0.2.10:8092"), ("tailnet", "home-pc.example.ts.net:8092")]
    assert pairing.home_routes({"address": "192.0.2.10:8092", "tailnet_address": "192.0.2.10:8092"}) == [("lan", "192.0.2.10:8092")]
    assert pairing.home_routes({"address": "192.0.2.10:8092"}) == [("lan", "192.0.2.10:8092")]


def _mac(tmp_path: Path, monkeypatch, handler):
    from alture_jarvis.messaging import credentials

    real = httpx.AsyncClient

    def mocked(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    class Store:
        def read(self, target):  # type: ignore[no-untyped-def]
            return "device-token"

    monkeypatch.setattr(httpx, "AsyncClient", mocked)
    monkeypatch.setattr(credentials, "default_store", lambda: Store())
    data = tmp_path / "data"
    data.mkdir()
    pairing.save_home(data, {"name": "HOME-PC", "address": "192.0.2.10:8092", "tailnet_address": "home-pc.example.ts.net:8092"})
    config = JarvisConfig(runtime_root=tmp_path, data_dir=data, output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=data / "JARVIS_PROFILE.md")
    return create_app(config, start_services=False)


def test_relay_falls_back_to_the_tailnet_path_when_home_wifi_is_away(tmp_path: Path, monkeypatch):
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "192.0.2.10":
            raise httpx.ConnectError("no route", request=request)
        assert request.headers["x-sonjari-device"] == "device-token"
        return httpx.Response(200, json={"done": True})

    app = _mac(tmp_path, monkeypatch, handler)
    events = app.state.jarvis.events
    with TestClient(app) as here:
        assert here.post("/v1/home-llm/api/chat", json={"model": "m", "messages": []}).status_code == 200
        assert hosts == ["192.0.2.10", "home-pc.example.ts.net"]
        # 1분 동안은 와이파이 길을 맨 뒤로 — 카페에서 매번 기다리지 않는다
        hosts.clear()
        assert here.post("/v1/home-llm/api/chat", json={"model": "m", "messages": []}).status_code == 200
        assert hosts == ["home-pc.example.ts.net"]
    calls = [e.payload for e in list(events._events) if e.event == "home_llm_call"]
    assert calls == [{"phase": "start"}, {"phase": "end", "ok": True}] * 2   # 끝 알림은 부르기마다 한 번


def test_relay_prefers_home_wifi_and_says_which_path(tmp_path: Path, monkeypatch):
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, json={"models": []})

    app = _mac(tmp_path, monkeypatch, handler)
    with TestClient(app) as here:
        assert here.get("/v1/home-llm/api/tags").status_code == 200
    assert hosts == ["192.0.2.10"]


def test_relay_with_both_paths_down_is_one_failure(tmp_path: Path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    app = _mac(tmp_path, monkeypatch, handler)
    events = app.state.jarvis.events
    with TestClient(app) as here:
        assert here.post("/v1/home-llm/api/chat", json={"model": "m", "messages": []}).status_code == 502
    calls = [e.payload for e in list(events._events) if e.event == "home_llm_call"]
    assert calls == [{"phase": "start"}, {"phase": "end", "ok": False}]


# ── 단계 문 ─────────────────────────────────────────────────────────────────────────────────────────

def test_mac_status_reports_to_the_pc_and_remembers_the_tailnet_path(tmp_path: Path, monkeypatch):
    from alture_jarvis.messaging import credentials

    class Store:
        def read(self, target):  # type: ignore[no-untyped-def]
            return "device-token"

    monkeypatch.setattr(credentials, "default_store", lambda: Store())
    monkeypatch.setattr(tailnet, "status", lambda run=None: {"installed": True, "state": "Running", "tailnet_id": "T-ONE",
                                                             "dns_name": "mac.example.ts.net", "peers": []})
    posted: list[dict] = []

    def fake_post(url, **kwargs):  # type: ignore[no-untyped-def]
        posted.append({"url": url, **kwargs})
        return httpx.Response(200, json={"pc": {"installed": True, "state": "Running", "tailnet_id": "T-ONE",
                                                "dns_name": "home-pc.example.ts.net"}, "door_open": True, "serve_error": ""},
                              request=httpx.Request("POST", url))

    got_urls: list[str] = []

    def fake_get(url, **kwargs):  # type: ignore[no-untyped-def]
        got_urls.append(url)
        assert kwargs["headers"]["X-Sonjari-Device"] == "device-token"
        return httpx.Response(200, json={"version": "0.40"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)
    data = tmp_path / "data"
    data.mkdir()
    pairing.save_home(data, {"name": "HOME-PC", "address": "192.0.2.10:8092"})
    config = JarvisConfig(runtime_root=tmp_path, data_dir=data, output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=data / "JARVIS_PROFILE.md")
    app = create_app(config, start_services=False)
    with TestClient(app) as here:
        assert here.get("/v1/outside/status").status_code == 401        # 화면 열쇠가 있어야
        first = here.get("/v1/outside/status", headers=AUTH).json()
        assert first["role"] == "mac" and first["stage"] == "done" and first["offer"] is False
    assert posted[0]["url"] == "http://192.0.2.10:8092/v1/pair/outside"
    assert posted[0]["json"]["me"] == {"installed": True, "state": "Running", "tailnet_id": "T-ONE", "dns_name": "mac.example.ts.net"}
    assert got_urls == ["http://home-pc.example.ts.net:8092/v1/llm/api/version"]
    assert pairing.read_home(data)["tailnet_address"] == "home-pc.example.ts.net:8092"


def test_pc_answers_the_outside_check_only_to_a_paired_device(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tailnet, "status", lambda run=None: {"installed": True, "state": "Running", "tailnet_id": "T-ONE",
                                                             "dns_name": "home-pc.example.ts.net", "peers": []})
    monkeypatch.setattr(tailnet, "door_served", lambda run=None, port=8092: True)
    monkeypatch.setattr("alture_jarvis.pair_door.should_open", lambda config: True)   # 윈도우 집 PC 흉내(맥에서 돌 때도)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    app = create_app(config, start_services=False)
    host = app.state.jarvis.pair_host
    asked = host.request("mac-mini", "dev-1")
    code = host.pending()[0]["code"]
    token = host.confirm(asked["request_id"], code)["token"]
    with TestClient(app) as pc:
        assert pc.get("/v1/outside/status", headers=AUTH).json()["stage"] == "idle"   # 아무도 시작 안 함
        mac_side = {"installed": True, "state": "Running", "tailnet_id": "T-ONE", "dns_name": "mac.example.ts.net"}
        answer = pc.post("/v1/pair/outside", headers={"X-Sonjari-Device": token}, json={"me": mac_side, "reached": True}).json()
        assert answer["pc"]["tailnet_id"] == "T-ONE" and answer["door_open"] is True
        shown = pc.get("/v1/outside/status", headers=AUTH).json()
        assert shown["role"] == "pc" and shown["stage"] == "done" and shown["other_name"] == "mac-mini"


def test_steps_give_pages_but_never_open_or_install_themselves(tmp_path: Path, monkeypatch):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, profile_path=tmp_path / "data" / "JARVIS_PROFILE.md")
    app = create_app(config, start_services=False)
    with TestClient(app) as here:
        page = here.post("/v1/outside/step/install", headers=AUTH).json()
        assert page["ok"] and page["url"].startswith("https://tailscale.com/download")
        assert here.post("/v1/outside/step/nope", headers=AUTH).json()["error"] == "unknown_step"
        assert here.post("/v1/outside/step/install").status_code == 401
