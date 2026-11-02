"""모델이 그래픽카드 밖으로 새면 빠른 모델(Qwen 3.6 2비트)로 바로 넘긴다 (2026-10-30 대표 결정 · `model_fallback`).

16GB 흉내(모델 자리 12GB)에서 Swift 27B 작은 판이 카드에 71% · 초당 6토큰 — 「너무 느리면 못 쓴다」. 같은 조건 3.6 2비트는 초당 116토큰.
깔려 있으면 묻지 않고 바꾸고(10-20 「대화로 묻기」의 예외), 없으면 「빠른 모델 받기」를 알린다. 되돌리기는 「원래 모델로」만.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import model_fallback as mf

SWIFT = "hf.co/ukisai/Swift:IQ3_XXS"
FAST_TAG = "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ2_M"


class _Config:
    def __init__(self) -> None:
        self.chat, self.ctx = SWIFT, 65536

    def model_for(self, role: str) -> str:
        return self.chat

    def num_ctx_for(self, role: str) -> int:
        return self.ctx


class _Service:
    def __init__(self, config: _Config) -> None:
        self.config, self.calls = config, []

    def current_eyes(self) -> dict[str, Any]:
        return {"reads_pictures": False}

    def apply(self, key: str, ctx: int, **kw: Any) -> dict[str, Any]:
        self.calls.append(("apply", key, ctx, kw))
        self.config.chat = "sonjari-text-" + key
        return {"ok": True, "chat_model": self.config.chat, "verified": {"tokens_per_sec": 116.0}}

    def apply_tag(self, tag: str, ctx: int, **kw: Any) -> dict[str, Any]:
        self.calls.append(("apply_tag", tag, ctx, kw))
        self.config.chat = tag
        return {"ok": True}

    def start_pull(self, key: str) -> dict[str, Any]:
        self.calls.append(("pull", key))
        return {"ok": True, "status": "pulling"}


def _hands(tmp_path: Path, *, installed: bool = True):
    config = _Config()
    service = _Service(config)
    hands = mf.Fallback(service=service, config=config, data_dir=tmp_path,
                        installed=lambda: {FAST_TAG} if installed else {SWIFT},
                        fast_tag=lambda: FAST_TAG, is_fast=lambda tag: "qwen3.6-35b-iq2m" in tag)
    return hands, service, config


SPILL = {"gpu_share": 0.713, "card_full": False}


def test_a_spill_with_the_fast_model_installed_switches_without_asking(tmp_path: Path) -> None:
    hands, service, config = _hands(tmp_path)
    outcome = hands.on_spill("job-1", SPILL)
    assert outcome["action"] == "switched" and outcome["from"] == SWIFT
    assert service.calls[0][:3] == ("apply", mf.FAST_KEY, mf.FAST_CTX)
    assert service.calls[0][3] == {"eyes": False, "accept_spill": True}, "넘쳐도 받는다(MoE)"
    assert mf.read_state(tmp_path)["from"] == {"tag": SWIFT, "num_ctx": 65536, "eyes": False}


def test_not_installed_means_tell_how_to_get_it_and_keep_going(tmp_path: Path) -> None:
    hands, service, _ = _hands(tmp_path, installed=False)
    assert hands.on_spill("job-1", SPILL) == {"action": "missing"}
    assert service.calls == [], "12GB 받기는 사람이 말해야 한다"
    assert "빠른 모델 받기" in mf.missing_line(False)


def test_once_per_job_and_never_when_already_fast(tmp_path: Path) -> None:
    hands, service, _ = _hands(tmp_path)
    hands.on_spill("job-1", SPILL)
    assert hands.on_spill("job-1", SPILL)["action"] == "none", "판 도중엔 다시 안 본다"
    assert hands.on_spill("job-2", SPILL) == {"action": "none", "why": "already_fast"}
    assert [call[0] for call in service.calls] == ["apply"]


def test_restore_goes_back_to_what_was_there_and_clears_the_note(tmp_path: Path) -> None:
    hands, service, config = _hands(tmp_path)
    hands.on_spill("job-1", SPILL)
    result = hands.restore()
    assert result["ok"] and config.chat == SWIFT and service.calls[-1] == ("apply_tag", SWIFT, 65536, {"eyes": False})
    assert mf.read_state(tmp_path) == {}
    assert hands.restore()["error"] == "nothing_to_restore"


def test_a_second_switch_remembers_the_model_used_just_before(tmp_path: Path) -> None:
    """★ 2026-11-02 바꿈: 되돌릴 곳은 **바로 직전에 쓰던 모델**이다(옛: 처음 모델).

    빠른 모델이 아닌 상태에서 또 넘긴다는 것은 그 사이 사람이 화면에서 다른 모델을 직접 골랐거나(「원래 모델로」는 기록을 지운다)
    지난 기록이 남은 것이다. 11-02 실제로 10-31 16GB 흉내 시험의 기록(작은 27B)이 남아, 3090 의 진짜 27B 에서 넘겼을 때
    「원래 모델로」가 시험용 모델로 돌아갈 뻔했다.
    """
    hands, _, config = _hands(tmp_path)
    hands.on_spill("job-1", SPILL)
    config.chat = "some-other-model"
    hands.on_spill("job-2", SPILL)
    assert mf.read_state(tmp_path)["from"]["tag"] == "some-other-model"


@pytest.mark.parametrize("facts, want", [
    ({"gpu_share": 0.713}, True), ({"card_full": True, "gpu_share": 1.0}, True),
    ({"gpu_share": 1.0, "card_full": False}, False), ({}, False),
])
def test_what_counts_as_a_spill(facts: dict, want: bool) -> None:
    assert mf.spilled(facts, 0.98) is want


@pytest.mark.parametrize("text", ["원래 모델로", "원래 모델로 돌려줘", "원래대로", "go back to the usual model"])
def test_restore_words(text: str) -> None:
    assert mf.restore_command(text)


@pytest.mark.parametrize("text", ["빠른 모델 받기", "빠른 모델 받아줘", "빠른 모델 깔아 줘", "download the fast model"])
def test_pull_words(text: str) -> None:
    assert mf.pull_command(text)


@pytest.mark.parametrize("text", [
    "원래 모델로 이 보고서를 다시 정리해서 엑셀 파일로 만들어 줄 수 있어?",   # 긴 일 부탁 속 낱말은 가로채지 않는다
    "빠른 모델이 뭐야", "모델 받기 페이지 열어 줘",
])
def test_other_sentences_are_not_commands(text: str) -> None:
    assert not mf.restore_command(text) and not mf.pull_command(text)


def test_the_agent_asks_the_hand_at_the_start_of_a_spilled_job() -> None:
    """판 시작 경고 자리가 손을 부르고, 넘겨도 되는 역할인지(`_fallback_covers`)를 먼저 본다 — 구조를 잠근다."""
    import inspect

    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent._warn_if_model_spills)
    assert 'getattr(self, "model_fallback", None)' in source and "self._fallback_covers(model_role)" in source
    assert "switched_line(False)" in source and "missing_line(False)" in source


@pytest.mark.parametrize("roles, role, expected", [
    ({"chat": SWIFT, "code": SWIFT}, "chat", True),
    ({"chat": SWIFT, "code": SWIFT}, "code", True),        # 같은 모델이면 코드 판도 넘긴다(10-30 16GB: 넘친 Swift 코드 0/3)
    ({"chat": SWIFT}, "code", True),                       # 코드 칸이 비면 대화 모델을 쓴다 — 같은 모델이다
    ({"chat": SWIFT, "code": "qwen-coder:30b"}, "code", False),  # 따로 고른 코드 모델은 사람의 선택 — 덮지 않는다
    ({"chat": SWIFT, "code": "qwen-coder:30b"}, "chat", True),
])
def test_which_jobs_may_fall_back(roles: dict, role: str, expected: bool) -> None:
    from types import SimpleNamespace

    from alture_jarvis.agent import BrowserAgent
    from alture_jarvis.config import JarvisConfig

    agent = SimpleNamespace(config=JarvisConfig(model_roles=roles))
    assert BrowserAgent._fallback_covers(agent, role) is expected


# ── 2026-11-02: 큰 카드에서는 넘기지 않는다(판 28168caf — 24GB 3090 이 잠깐 23.62GB 차서 선택이 영구히 바뀜) ──

def test_a_big_card_that_is_briefly_full_keeps_the_chosen_model(tmp_path: Path) -> None:
    hands, service, _ = _hands(tmp_path)
    facts = {"card_full": True, "card_total_gb": 24.0, "card_used_gb": 23.62, "card_free_gb": 0.38, "gpu_share": 1.0}
    assert hands.on_spill("job-1", facts) == {"action": "none", "why": "big_card"}
    assert service.calls == [] and not mf.read_state(tmp_path), "사람의 선택을 덮지 않는다"


@pytest.mark.parametrize("total", [16.0, 12.0, 8.0])
def test_a_small_card_still_falls_back(tmp_path: Path, total: float) -> None:
    hands, _, _ = _hands(tmp_path)
    assert hands.on_spill("job-1", {"card_full": True, "card_total_gb": total})["action"] == "switched"


def test_an_unknown_card_size_falls_back_as_before(tmp_path: Path) -> None:
    hands, _, _ = _hands(tmp_path)
    assert hands.on_spill("job-1", SPILL)["action"] == "switched"
