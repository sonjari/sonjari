"""11-11 램 부스트 — 그래픽카드가 모자라면 MoE 의 전문가를 남는 램으로. 양방향(할 때 · 하면 안 될 때)."""
from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis import ram_boost
from alture_jarvis.model_fallback import FAST_KEY, Fallback


def test_plan_needs_moe_and_enough_ram() -> None:
    card = {"used_gb": 6.0, "total_gb": 16.0}
    ok = ram_boost.plan(FAST_KEY, card=card, ram_free=40.0, ours_gb=0.0)
    assert ok["ok"] and ok["env"] == {"LLAMA_ARG_FIT_TARGET": str(6 * 1024 + 1024 + 512)}
    # 하면 안 되는 것: 램이 모자람 · 밀집 모델 · 램을 모름
    short = ram_boost.plan(FAST_KEY, card=card, ram_free=10.0)
    assert not short["ok"] and short["why"] == "ram_short"
    assert ram_boost.plan("qwen3.8-27b-swift-iq3xxs", card=card, ram_free=60.0)["why"] == "not_moe"
    assert ram_boost.plan(FAST_KEY, card=card, ram_free=None)["why"] == "ram_unknown"


def test_need_is_experts_plus_four_gb() -> None:
    need = ram_boost.need_ram_gb(FAST_KEY)
    assert need == round(11.52 * ram_boost.EXPERT_SHARE_GUESS + 4.0, 1)
    assert 13.0 < need < 15.0  # 대표 11-11 「약 14GB」


def test_others_share_excludes_our_model() -> None:
    # 카드 12GB 사용 중 우리 모델 몫 8GB → 남의 몫 4GB 만 비워 둔다
    assert ram_boost.fit_target_mib({"used_gb": 12.0}, ours_gb=8.0) == 4 * 1024 + 1024 + 512
    # 우리 몫이 사용량보다 크게 나와도 음수가 되지 않는다
    assert ram_boost.fit_target_mib({"used_gb": 2.0}, ours_gb=8.0) == 1024 + 512
    assert ram_boost.fit_target_mib(None) == 1024 + 512


def test_cache_shrinks_but_not_below_two_gb() -> None:
    assert ram_boost.lower_cache_ram(24576) == 12288
    assert ram_boost.lower_cache_ram(2048) == 2048
    assert ram_boost.lower_cache_ram(0) == 0


class _Installer:
    def __init__(self, ok: bool = True) -> None:
        self.boost_env: dict[str, str] = {}
        self.calls: list[dict[str, str] | None] = []
        self.ok = ok

    def set_boost(self, env, *, wait_sec: float = 40.0):
        self.calls.append(env)
        self.boost_env = dict(env or {})
        return {"ok": self.ok, "restarted": "managed"}


class _Service:
    def __init__(self) -> None:
        self.applied: list[tuple] = []

    def apply(self, key, ctx, *, eyes=None, accept_spill=False, remembered_first=False):
        self.applied.append((key, ctx, eyes, accept_spill))
        return {"ok": True, "chat_model": "qwen3.6-fast", "verified": {"tokens_per_sec": 40.0}}

    def current_eyes(self):
        return {}


def _booster(tmp_path, ram: float | None = 40.0, ok: bool = True):
    audits: list[str] = []
    installer, service = _Installer(ok), _Service()
    booster = ram_boost.Booster(installer=installer, service=service, data_dir=tmp_path,
                                ram=lambda: ram, audit=lambda event, payload: audits.append(event))
    return booster, installer, service, audits


def test_engage_restarts_then_applies_and_remembers(tmp_path) -> None:
    booster, installer, service, audits = _booster(tmp_path)
    out = booster.engage(FAST_KEY, 65536, {"card_used_gb": 7.0, "card_total_gb": 16.0, "model_gb": 1.0}, job_id="j")
    assert out["action"] == "boosted" and out["fit_target_mib"] == 6 * 1024 + 1536
    assert installer.calls == [{"LLAMA_ARG_FIT_TARGET": str(6 * 1024 + 1536)}]
    assert service.applied == [(FAST_KEY, 65536, False, True)]
    assert ram_boost.read_state(tmp_path)["env"] == installer.boost_env
    assert audits == ["ram_boost_plan", "ram_boost_on"]
    # 손자리를 다시 켜면 같은 환경을 쥔다
    fresh = _Installer()
    assert ram_boost.Booster(installer=fresh, service=service, data_dir=tmp_path).resume()
    assert fresh.boost_env == installer.boost_env
    # 끄면 환경 · 기록 둘 다 비운다
    assert booster.release()["released"] and installer.boost_env == {} and not ram_boost.read_state(tmp_path)


def test_engage_does_nothing_when_ram_is_short(tmp_path) -> None:
    booster, installer, service, _ = _booster(tmp_path, ram=8.0)
    out = booster.engage(FAST_KEY, 65536, {"card_used_gb": 7.0, "card_total_gb": 16.0})
    assert out["action"] == "none" and out["why"] == "ram_short"
    assert installer.calls == [] and service.applied == [] and not ram_boost.read_state(tmp_path)


def test_failed_restart_leaves_no_boost(tmp_path) -> None:
    booster, installer, service, _ = _booster(tmp_path, ok=False)
    out = booster.engage(FAST_KEY, 65536, {"card_used_gb": 7.0, "card_total_gb": 16.0})
    assert out["action"] == "failed" and installer.boost_env == {} and service.applied == []


def _fallback(tmp_path, booster, current: str = "qwen3.6-fast"):
    config = SimpleNamespace(model_for=lambda role: current, num_ctx_for=lambda role: 65536)
    return Fallback(service=_Service(), config=config, data_dir=tmp_path, installed=lambda: {"qwen3.6-fast"},
                    fast_tag=lambda: "qwen3.6-fast", is_fast=lambda tag: tag == "qwen3.6-fast", booster=booster)


def test_already_fast_but_card_busy_boosts(tmp_path) -> None:
    """사용자 경우: 이미 3.6 인데 맥스가 카드를 쥐어 넘쳤다 → 예전엔 「already_fast」로 아무것도 안 했다."""
    booster, installer, _, _ = _booster(tmp_path)
    out = _fallback(tmp_path, booster).on_spill("j1", {"card_full": True, "card_used_gb": 15.8, "card_total_gb": 16.0})
    assert out["action"] == "boosted" and installer.calls


def test_already_fast_with_free_card_does_not_boost(tmp_path) -> None:
    booster, installer, _, _ = _booster(tmp_path)
    out = _fallback(tmp_path, booster).on_spill("j1", {"gpu_share": 1.0, "card_used_gb": 12.0, "card_total_gb": 16.0})
    assert out == {"action": "none", "why": "already_fast"} and installer.calls == []


def test_no_booster_behaves_as_before(tmp_path) -> None:
    out = _fallback(tmp_path, None).on_spill("j1", {"card_full": True, "card_total_gb": 16.0})
    assert out == {"action": "none", "why": "already_fast"}


def test_restore_releases_boost_even_without_model_switch(tmp_path) -> None:
    booster, installer, _, _ = _booster(tmp_path)
    fallback = _fallback(tmp_path, booster)
    fallback.on_spill("j1", {"card_full": True, "card_used_gb": 15.8, "card_total_gb": 16.0})
    assert installer.boost_env
    assert fallback.restore() == {"ok": True, "boost_released": True}
    assert installer.boost_env == {}


def test_installer_launch_env_carries_boost_and_halves_cache(tmp_path, monkeypatch) -> None:
    from alture_jarvis import ollama_install

    monkeypatch.delenv("LLAMA_ARG_CACHE_RAM", raising=False)
    installer = ollama_install.OllamaInstaller(install_root=tmp_path, prompt_cache_mib=24576)
    plain = installer._launch_env()
    assert plain.get("LLAMA_ARG_CACHE_RAM") == "24576" and "LLAMA_ARG_FIT_TARGET" not in plain
    installer.boost_env = {"LLAMA_ARG_FIT_TARGET": "7680"}
    boosted = installer._launch_env()
    assert boosted["LLAMA_ARG_FIT_TARGET"] == "7680" and boosted["LLAMA_ARG_CACHE_RAM"] == "12288"


# ── 마법사 · 설정 (램 부스트 카드) ───────────────────────────────────────

def _pc(vram_gb: float, ram_free: float | None) -> dict:
    return {
        "gpus": [{"index": 0, "name": "RTX 3050 Laptop", "vram_total_gb": vram_gb, "vram_used_gb": 0.3,
                  "driver": "580.00", "display_active": False}],
        "gpu_error": "", "ram_gb": 24.0, "ram_free_gb": ram_free, "disk_free_gb": 200.0,
        "ollama": {"reachable": True, "installed": [], "vulkan_enabled": False}, "heavy_apps": [],
    }


def test_wizard_offers_ram_boost_on_small_card_with_spare_ram() -> None:
    from alture_jarvis import setup_profile as sp

    rec = sp.recommend(_pc(6.0, 18.0))
    boost = next((p for p in rec["picks"] if p["kind"] == "ram_boost"), None)
    assert boost is not None and boost["model_key"] == FAST_KEY and boost["num_ctx"] == sp.RAM_BOOST_SMALL_CARD_CTX
    assert boost["confidence"] == "measured_once" and any(r.startswith("램 부스트:") for r in rec["reasons"])
    row = next(m for m in sp.catalog_view(_pc(6.0, 18.0)) if m["key"] == FAST_KEY)
    assert row["fits"] and row["ram_boost"]["ctx"] == sp.RAM_BOOST_SMALL_CARD_CTX


def test_wizard_hides_ram_boost_when_ram_short_or_card_big_enough() -> None:
    from alture_jarvis import setup_profile as sp

    for profile in (_pc(6.0, 9.0), _pc(6.0, None), _pc(24.0, 40.0), _pc(4.0, 40.0)):
        rec = sp.recommend(profile)
        assert not any(p["kind"] == "ram_boost" for p in rec["picks"]), profile
        row = next(m for m in sp.catalog_view(profile) if m["key"] == FAST_KEY)
        assert "ram_boost" not in row


def test_new_lines_have_english() -> None:
    from alture_jarvis import setup_profile as sp, ui_i18n

    ui_i18n.reload()
    reason = next(r for r in sp.recommend(_pc(8.0, 30.0))["reasons"] if r.startswith("램 부스트:"))
    assert ui_i18n.translate_text(reason).startswith("RAM Boost:")
    assert ui_i18n.translate_text(ram_boost.boosted_line(False)).startswith("The graphics card is short")


def test_card_reading_follows_the_card_ollama_is_pinned_to() -> None:
    """11-11: 그래픽카드가 둘(3090 24GB + 3060 12GB)이면 「가장 큰 카드」가 아니라 Ollama 가 쓰는 카드를 본다."""
    from types import SimpleNamespace as NS

    from alture_jarvis import gpu_pressure

    csv = ("0, NVIDIA GeForce RTX 3090, 24576, 2000, 580.00, Enabled\n"
           "1, NVIDIA GeForce RTX 3060, 12288, 9000, 580.00, Enabled\n")

    def run(args, **kwargs):
        return NS(returncode=0, stdout=csv, stderr="")

    import os

    from alture_jarvis.gpu_policy import INHERITED_KEY as _KEY

    old = os.environ.get("CUDA_VISIBLE_DEVICES")
    old_inherited = os.environ.pop(_KEY, None)  # 다른 시험이 본체 정책을 이 프로세스에 걸어 두었을 수 있다
    try:
        os.environ["CUDA_VISIBLE_DEVICES"] = "1"
        card = gpu_pressure.read_card(run)
        assert card["index"] in (1, "1") and round(card["total_gb"]) == 12
        for loose in ("", "0,1", "GPU-0000abcd"):  # 여럿 · 비어 있음 · UUID 면 예전처럼 가장 큰 카드
            os.environ["CUDA_VISIBLE_DEVICES"] = loose
            assert round(gpu_pressure.read_card(run)["total_gb"]) == 24, loose
    finally:
        if old is None:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = old
        if old_inherited is not None:
            os.environ[_KEY] = old_inherited
    assert gpu_pressure.ollama_card_index({"CUDA_VISIBLE_DEVICES": " 2 "}) == "2"
    # 본체는 물려받은 값을 지우고 옮겨 둔다 — 옮겨 둔 값이 Ollama 가 쓰는 카드다(지운 뒤의 빈칸을 믿지 않는다)
    from alture_jarvis.gpu_policy import INHERITED_KEY, apply_process_gpu_policy

    env = {"CUDA_VISIBLE_DEVICES": "1"}
    apply_process_gpu_policy(env)
    assert "CUDA_VISIBLE_DEVICES" not in env and gpu_pressure.ollama_card_index(env) == "1"
    assert gpu_pressure.ollama_card_index({INHERITED_KEY: ""}) is None
    assert gpu_pressure.ollama_card_index({}) is None


# ── 11-11 밤: 램 기준 비트 사다리 · 그래픽카드 쓰는 법(사람이 고름) ─────────────────────────────

def test_ladder_matches_between_wizard_and_boost() -> None:
    from alture_jarvis import setup_profile as sp

    assert set(ram_boost.BOOST_LADDER) == set(sp._BOOST_KEYS) and ram_boost.BOOST_LADDER[0] == "qwen3.6-35b-a3b"
    assert ram_boost.need_ram_gb("qwen3.6-35b-a3b") > ram_boost.need_ram_gb(FAST_KEY)


def test_keep_free_leaves_a_floor_even_when_nobody_holds_the_card() -> None:
    card = {"used_gb": 0.0, "total_gb": 16.0}
    assert ram_boost.plan(FAST_KEY, card=card, ram_free=40.0)["fit_target_mib"] == 1536
    assert ram_boost.plan(FAST_KEY, card=card, ram_free=40.0, min_fit_mib=6144)["fit_target_mib"] == 6144
    # 남이 더 쥐었으면 그쪽이 이긴다
    busy = {"used_gb": 9.0, "total_gb": 16.0}
    assert ram_boost.plan(FAST_KEY, card=busy, ram_free=40.0, min_fit_mib=6144)["fit_target_mib"] == 9 * 1024 + 1536


def _ladder_fallback(tmp_path, booster, installed: set[str], mode: str = "auto", current: str = "qwen3.6-fast"):
    tags = {"qwen3.6-35b-a3b": "qwen3.6:35b-a3b", FAST_KEY: "qwen3.6-fast"}
    config = SimpleNamespace(model_for=lambda role: current, num_ctx_for=lambda role: 65536)
    return Fallback(service=_Service(), config=config, data_dir=tmp_path, installed=lambda: installed,
                    fast_tag=lambda: "qwen3.6-fast", is_fast=lambda tag: tag in tags.values(), booster=booster,
                    tag_of=lambda key: tags.get(key, ""), gpu_mode=lambda: mode)


ROOMY_CARD = {"card_total_gb": 16.0, "card_used_gb": 0.0}


def test_boost_picks_four_bit_when_installed_ram_allows_and_card_has_room(tmp_path) -> None:
    booster, _, _, _ = _booster(tmp_path, ram=40.0)
    both = {"qwen3.6:35b-a3b", "qwen3.6-fast"}
    assert _ladder_fallback(tmp_path, booster, both)._boost_key(ROOMY_CARD) == "qwen3.6-35b-a3b"
    # 하면 안 되는 것: 4비트가 안 깔렸거나 · 램이 4비트에 모자라면 2비트
    assert _ladder_fallback(tmp_path, booster, {"qwen3.6-fast"})._boost_key(ROOMY_CARD) == FAST_KEY
    short, _, _, _ = _booster(tmp_path, ram=18.0)
    assert _ladder_fallback(tmp_path, short, both)._boost_key(ROOMY_CARD) == FAST_KEY


def test_boost_takes_two_bit_when_four_bit_would_mostly_sit_off_the_card(tmp_path) -> None:
    """11-12 출시 문 시험 그대로: 12GB 카드 11.77GB 사용(우리 모델 7.25GB) → 4비트는 카드에 약 27% → 2비트."""
    booster, _, _, _ = _booster(tmp_path, ram=40.0)
    both = {"qwen3.6:35b-a3b", "qwen3.6-fast"}
    gate = {"card_total_gb": 12.0, "card_used_gb": 11.77, "model_gb": 7.25}
    assert ram_boost.card_share("qwen3.6-35b-a3b", {"used_gb": 11.77, "total_gb": 12.0}, 7.25) < ram_boost.CARD_SHARE_MIN
    assert _ladder_fallback(tmp_path, booster, both)._boost_key(gate) == FAST_KEY
    # 카드를 모르면 2비트(맨 아래 칸은 카드 몫을 안 본다)
    assert _ladder_fallback(tmp_path, booster, both)._boost_key() == FAST_KEY
    assert _ladder_fallback(tmp_path, booster, both)._boost_key({}) == FAST_KEY
    # 「비워 두기」 6GB 를 걸면 16GB 빈 카드도 4비트가 절반 아래 → 2비트
    assert _ladder_fallback(tmp_path, booster, both)._boost_key(ROOMY_CARD, 6144) == FAST_KEY


def test_card_share_is_none_without_a_card_and_capped_at_one() -> None:
    assert ram_boost.card_share("qwen3.6-35b-a3b", None) is None
    assert ram_boost.card_share("nope", {"used_gb": 0, "total_gb": 24}) is None
    assert ram_boost.card_share("qwen3.6-35b-iq2m", {"used_gb": 0, "total_gb": 48}) == 1.0


def test_speed_mode_never_switches(tmp_path) -> None:
    booster, installer, _, _ = _booster(tmp_path)
    fallback = _ladder_fallback(tmp_path, booster, {"qwen3.6-fast"}, mode="speed")
    out = fallback.on_spill("j1", {"card_full": True, "card_used_gb": 15.8, "card_total_gb": 16.0})
    assert out == {"action": "none", "why": "speed_mode"} and installer.calls == []


def test_keep_free_boosts_before_any_spill_once_per_job(tmp_path) -> None:
    booster, installer, service, _ = _booster(tmp_path, ram=40.0)
    fallback = _ladder_fallback(tmp_path, booster, {"qwen3.6:35b-a3b", "qwen3.6-fast"}, mode="keep_free",
                                current="sonjari-27b")
    out = fallback.keep_free("j1", {"card_used_gb": 1.0, "card_total_gb": 16.0, "gpu_share": 1.0})
    assert out["action"] == "boosted"
    assert int(installer.boost_env["LLAMA_ARG_FIT_TARGET"]) >= 6144, "넘치지 않았어도 6GB 를 비워 둔다"
    # ★ 11-12: 6GB 를 비워 두면 16GB 카드에 4비트는 46% 만 올라간다 → 2비트(`CARD_SHARE_MIN`).
    assert service.applied[0][0] == FAST_KEY, "비워 두기는 카드가 좁다 — 2비트"
    assert ram_boost.read_state(tmp_path)["model"] == FAST_KEY
    from alture_jarvis.model_fallback import read_state as fallback_state

    assert fallback_state(tmp_path)["from"]["tag"] == "sonjari-27b", "「원래 모델로」가 돌아갈 자리를 적는다"
    assert fallback.keep_free("j1", {})["action"] == "none", "같은 판에 두 번 안 건다"


def test_keep_free_does_nothing_in_other_modes_or_when_ram_is_short(tmp_path) -> None:
    booster, installer, _, _ = _booster(tmp_path, ram=40.0)
    assert _ladder_fallback(tmp_path, booster, {"qwen3.6-fast"}, mode="auto").keep_free("j1", {})["action"] == "none"
    short, short_installer, _, _ = _booster(tmp_path, ram=8.0)
    out = _ladder_fallback(tmp_path, short, {"qwen3.6-fast"}, mode="keep_free").keep_free("j2", {})
    assert out == {"action": "none", "why": "ram_short"} and short_installer.calls == [] and installer.calls == []


def test_gpu_mode_is_stored_and_validated(tmp_path) -> None:
    import pytest

    from alture_jarvis import gpu_mode

    assert gpu_mode.read_mode(tmp_path) == "auto"
    gpu_mode.write_mode(tmp_path, "keep_free")
    assert gpu_mode.read_mode(tmp_path) == "keep_free"
    with pytest.raises(ValueError):
        gpu_mode.write_mode(tmp_path, "turbo")
    view = gpu_mode.view(tmp_path, None)
    assert view["mode"] == "keep_free" and view["available"] is False and view["modes"] == ["speed", "auto", "keep_free"]


def test_wizard_offers_four_bit_boost_when_ram_is_plenty() -> None:
    from alture_jarvis import setup_profile as sp

    boost = next(p for p in sp.recommend(_pc(16.0, 40.0))["picks"] if p["kind"] == "ram_boost")
    assert boost["model_key"] == "qwen3.6-35b-a3b"
    small = next(p for p in sp.recommend(_pc(8.0, 18.0))["picks"] if p["kind"] == "ram_boost")
    assert small["model_key"] == FAST_KEY, "램이 4비트에 모자라면 2비트"
    # 16GB 카드에 램이 4비트에 모자라면: 2비트가 카드에 통째로 들어가니 램 부스트 카드는 없다
    assert not any(p["kind"] == "ram_boost" for p in sp.recommend(_pc(16.0, 18.0))["picks"])


def test_kept_free_line_has_english() -> None:
    from alture_jarvis import gpu_mode, ui_i18n

    ui_i18n.reload()
    assert ui_i18n.translate_text(gpu_mode.kept_free_line(False)).startswith("Keeping the graphics card free")
