"""짝짓기 — 6자리 코드 · 기기 토큰 · 같은 네트워크엔 짝짓기 길만 (설계_짝짓기_모델자리_2026-11-03 §4-1 · §5 양방향).

해야 할 것: 코드가 맞으면 기기 전용 토큰 · 그 토큰으로만 모델을 빌림 · 끊으면 그 기기만 무효 · 짝지은 맥은 집 PC 자리로.
하면 안 되는 것: 코드 없이 토큰 · 틀린 코드 세 번 뒤 계속 시도 · 코드를 청한 쪽에 돌려줌 · 같은 네트워크에 제어 API 가 열림 ·
파일에 토큰 평문.
"""

from __future__ import annotations

import json

from alture_jarvis import model_place, pairing, peer_guard
from alture_jarvis.config import JarvisConfig


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def host(tmp_path, events=None):
    clock = Clock()
    seen = events if events is not None else []
    return pairing.PairingHost(tmp_path, publish=lambda e, p: seen.append((e, p)), clock=clock,
                               info=lambda: {"name": "DONGJU-PC", "gpu": "RTX 3090 24GB", "version": "x"}), clock, seen


def test_code_goes_to_the_home_screen_not_to_the_asker(tmp_path):
    h, _clock, events = host(tmp_path)
    asked = h.request("mac-mini", "dev-1", peer="192.168.0.20")
    assert asked["ok"] and "code" not in asked
    shown = [p for e, p in events if e == "pair_request"]
    # 사건(열쇠 없이 읽히는 /v1/events)에는 코드가 없고, 집 PC 띠가 읽는 열쇠 있는 길에만 있다(11-04 보안 점검)
    assert len(shown) == 1 and "code" not in shown[0]
    code = h.pending()[0]["code"]
    assert len(code) == 6 and code.isdigit()


def test_right_code_gives_a_device_token_kept_only_as_a_hash(tmp_path):
    h, _clock, events = host(tmp_path)
    rid = h.request("mac-mini", "dev-1")["request_id"]
    code = h.pending()[0]["code"]
    done = h.confirm(rid, code)
    assert done["ok"] and len(done["token"]) >= 40 and done["home_name"] == "DONGJU-PC"
    stored = (tmp_path / pairing.DEVICES_FILE).read_text(encoding="utf-8")
    assert done["token"] not in stored and pairing._hash(done["token"]) in stored
    assert h.verify(done["token"])["device_id"] == "dev-1"
    assert h.verify("wrong") is None and h.verify("") is None
    # 한 번 쓴 요청은 닫힌다
    assert h.confirm(rid, code)["error"] == "no_request"


def test_three_wrong_codes_close_the_request(tmp_path):
    h, _clock, events = host(tmp_path)
    rid = h.request("mac-mini", "dev-1")["request_id"]
    code = h.pending()[0]["code"]
    wrong = "000000" if code != "000000" else "111111"
    assert h.confirm(rid, wrong) == {"ok": False, "error": "wrong_code", "tries_left": 2}
    assert h.confirm(rid, wrong)["tries_left"] == 1
    assert h.confirm(rid, wrong)["error"] == "closed"
    assert h.confirm(rid, code)["error"] == "no_request"  # 맞는 코드라도 이미 닫힘
    assert not (tmp_path / pairing.DEVICES_FILE).exists()


def test_codes_expire_after_five_minutes(tmp_path):
    h, clock, events = host(tmp_path)
    rid = h.request("mac-mini", "dev-1")["request_id"]
    code = h.pending()[0]["code"]
    clock.now += pairing.CODE_TTL_SEC + 1
    assert h.confirm(rid, code)["error"] == "no_request"
    assert h.pending() == []


def test_requests_are_rate_limited(tmp_path):
    h, clock, _events = host(tmp_path)
    assert h.request("a", "1")["ok"]
    assert h.request("b", "2") == {"ok": False, "error": "too_fast"}
    for i in range(pairing.MAX_OPEN_REQUESTS - 1):
        clock.now += pairing.REQUEST_GAP_SEC + 0.1
        assert h.request(f"x{i}", str(i))["ok"]
    clock.now += pairing.REQUEST_GAP_SEC + 0.1
    assert h.request("y", "y") == {"ok": False, "error": "too_many"}


def test_revoke_cuts_only_that_device(tmp_path):
    h, clock, events = host(tmp_path)
    tokens = {}
    for name in ("mac-a", "mac-b"):
        clock.now += pairing.REQUEST_GAP_SEC + 0.1
        rid = h.request(name, name)["request_id"]
        code = h.pending()[-1]["code"]
        tokens[name] = h.confirm(rid, code)["token"]
    assert h.revoke("mac-a") is True
    assert h.verify(tokens["mac-a"]) is None
    assert h.verify(tokens["mac-b"])["device_id"] == "mac-b"
    assert [d["device_id"] for d in h.devices()] == ["mac-b"]
    assert h.revoke("mac-a") is False


def test_the_lan_only_reaches_the_pairing_doors():
    lan = "192.168.0.20"
    for path in ("/v1/pair/hello", "/v1/pair/request", "/v1/pair/confirm", "/v1/llm/api/chat"):
        assert peer_guard.is_allowed_for(lan, path)
    for path in ("/v1/chat", "/v1/pair/pending", "/v1/pair/devices", "/v1/pair/revoke", "/v1/config", "/v1/home-llm/api/chat", "/v1/pair"):
        assert not peer_guard.is_allowed_for(lan, path), path
    # 사설이 아닌 주소는 짝짓기 길도 안 된다
    assert not peer_guard.is_allowed_for("8.8.8.8", "/v1/pair/hello")
    # 루프백 · 테일넷은 예전 그대로 전부
    assert peer_guard.is_allowed_for("127.0.0.1", "/v1/chat") and peer_guard.is_allowed_for("100.100.1.2", "/v1/chat")
    assert peer_guard.is_loopback("127.0.0.1") and not peer_guard.is_loopback("100.100.1.2") and not peer_guard.is_loopback(lan)


def test_subnet_scan_stays_inside_a_private_slash24():
    hosts = pairing.subnet_hosts("192.168.0.27")
    assert len(hosts) == 253 and "192.168.0.27" not in hosts and "192.168.0.91" in hosts
    assert pairing.subnet_hosts("8.8.8.8") == []


def test_paired_mac_uses_the_relay_and_the_home_model(tmp_path):
    pairing.save_home(tmp_path, {"address": "192.0.2.10:8091", "name": "DONGJU-PC", "home_model": "swift:27b", "home_ctx": 131072})
    config = JarvisConfig(data_dir=tmp_path, model_roles={"chat": "local-model"}, ollama_num_ctx=32768)
    model_place.forget_cache(config)
    assert model_place.home_url(config) == "http://127.0.0.1:8091/v1/home-llm"
    done = model_place.set_place(config, "home_pc")
    assert done["ok"] and config.ollama_base_url.endswith("/v1/home-llm") and config.model_for("chat") == "swift:27b"
    assert config.ollama_num_ctx == 131072
    # 토큰은 모델 주소에 없다
    assert "token" not in config.ollama_base_url
    # 끊으면 옛 값(이 기기는 위성이 아니었다) — 집 PC 를 모른다
    (tmp_path / pairing.HOME_FILE).unlink()
    model_place.forget_cache(config)
    assert model_place.home_url(config) == ""


def test_a_paired_device_becomes_a_child_on_next_start(tmp_path, monkeypatch):
    pairing.save_home(tmp_path, {"address": "192.0.2.10:8091", "name": "DONGJU-PC", "home_model": "swift:27b"})
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    config = JarvisConfig.from_env()
    assert str(config.data_dir) == str(tmp_path)
    assert config.jarvis_role == "satellite" and config.brain_host == "192.0.2.10"
    assert config.ollama_base_url.endswith("/v1/home-llm") and config.model_for("chat") == "swift:27b"


def test_device_id_is_stable(tmp_path):
    first = pairing.device_id(tmp_path)
    assert pairing.device_id(tmp_path) == first and len(first) == 32


def test_saved_home_has_no_token(tmp_path):
    pairing.save_home(tmp_path, {"address": "192.0.2.10:8091", "name": "PC"})
    assert "token" not in json.loads((tmp_path / pairing.HOME_FILE).read_text(encoding="utf-8"))


def test_guessing_codes_across_new_requests_locks_pairing_for_a_day(tmp_path):
    """11-04 보안 점검: 요청마다 3번만 세면 2초마다 새 요청으로 시간당 ~5,400번 맞혀 볼 수 있었다 — 이 PC 전체로 하루 10번이면 잠근다."""
    h, clock, events = host(tmp_path)
    wrong = 0
    while not h.locked():
        asked = h.request("guest", "")
        assert asked["ok"], asked
        code = h.pending()[-1]["code"]
        bad = "000000" if code != "000000" else "111111"
        for _ in range(pairing.MAX_TRIES):
            done = h.confirm(asked["request_id"], bad)
            wrong += 1
            if done["error"] in {"closed", "locked"}:
                break
        clock.now += pairing.REQUEST_GAP_SEC
        assert wrong <= pairing.MAX_WRONG_PER_DAY
    assert wrong == pairing.MAX_WRONG_PER_DAY
    assert h.pending() == []                                   # 열린 요청(도배된 띠)도 닫힌다
    assert h.request("guest", "")["error"] == "locked"
    assert h.hello()["accepting"] is False
    assert ("pair_locked", {"wrong_in_day": pairing.MAX_WRONG_PER_DAY}) in events
    clock.now += 86_400                                         # 하루 뒤 풀린다
    assert h.request("mac", "")["ok"] and h.hello()["accepting"] is True


def test_a_locked_pc_refuses_even_the_right_code(tmp_path):
    h, clock, _events = host(tmp_path)
    legit = h.request("mac", "dev-1")
    right = h.pending()[0]["code"]
    clock.now += pairing.REQUEST_GAP_SEC
    for _ in range(pairing.MAX_WRONG_PER_DAY):                  # 다른 요청으로 틀려 잠근다
        asked = h.request("guest", "")
        if not asked.get("ok"):
            break
        code = h.pending()[-1]["code"]
        for _ in range(pairing.MAX_TRIES):
            if h.confirm(asked["request_id"], "000000" if code != "000000" else "111111")["error"] in {"closed", "locked"}:
                break
        clock.now += pairing.REQUEST_GAP_SEC
    assert h.locked()
    assert h.confirm(legit["request_id"], right)["error"] == "locked"
    assert h.devices() == []


def test_new_requests_are_capped_per_hour(tmp_path):
    h, clock, _events = host(tmp_path)
    made = 0
    for _ in range(pairing.MAX_REQUESTS_PER_HOUR + 5):
        asked = h.request("guest", "")
        if asked.get("ok"):
            made += 1
            h.reject(asked["request_id"])                      # 열린 요청 5개 한도에 안 걸리게 바로 거절
        clock.now += pairing.REQUEST_GAP_SEC
    assert made == pairing.MAX_REQUESTS_PER_HOUR
    clock.now += 3_600
    assert h.request("guest", "")["ok"]
