"""머리에 적힌 모델 이름을 누르면 바꿀 수 있어야 한다 (2026-09-21 제품 요청).

두 가지를 잰다:

    ① **사람이 직접 받아 둔 모델도 목록에 보인다.** 우리 카탈로그에 없다는 이유로
       빼 버리면, 사용자는 자기가 `ollama pull` 한 모델을 온텔릭에서 못 쓰는 줄 안다.
       쓸 수 있다 — 다만 「우리가 능력을 잰 적 없음」이라고 **적어서** 보여 준다.

    ② **Code 탭에서 고른 것은 Code 탭에만 적용된다.** 대화 모델을 같이 바꾸면,
       코드 모델을 고르려다 대화 모델까지 갈아타 버린다.

★ 왜 목록에서 빼지 않고 「이유를 적어서」 보이나 — 막기만 하면 모델도 사람도 같은 벽에
  계속 부딪친다(사고 R 의 반대편 교훈). 도구를 못 부르는 모델은 **보이되 못 누르게** 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SetupService

#: 3090 한 장이 있는 PC. 목록에 있는 모델과 없는 모델이 섞여 있다.
PROFILE = {
    "gpus": [{"name": "NVIDIA GeForce RTX 3090", "vram_total_gb": 24.0, "integrated": False,
              "display_active": False, "vendor": "NVIDIA", "backend": "cuda"}],
    "ollama": {"reachable": True, "version": "0.13", "installed": [
        "qwen3.6:35b-a3b", "qwen3.5:9b",
        # ↓ 우리 카탈로그에 없는 것들 — 사용자가 직접 받은 모델
        "mistral-small3.2:24b", "translategemma:4b", "bge-m3:latest", "my-old-alias:latest",
    ], "vulkan_enabled": False},
}

CAPS = {
    "qwen3.6:35b-a3b": ["completion", "vision", "tools", "thinking"],
    "qwen3.5:9b": ["completion", "tools"],
    "mistral-small3.2:24b": ["completion", "tools"],
    "translategemma:4b": ["completion", "vision"],   # 도구 못 부름
    "bge-m3:latest": ["embedding"],                  # 글을 못 씀
    "my-old-alias:latest": ["completion", "tools"],
}

SIZES = {"qwen3.6:35b-a3b": 21.1, "qwen3.5:9b": 6.1, "mistral-small3.2:24b": 14.0,
         "translategemma:4b": 3.1, "bge-m3:latest": 1.1,
         # ↓ 사용자가 옛날에 지어 둔 별칭 — 실은 `qwen3.5:9b` 와 **같은 파일**이다
         "my-old-alias:latest": 6.1}

DIGESTS = {"qwen3.5:9b": "sha-qwen9b", "my-old-alias:latest": "sha-qwen9b"}


class _Ollama:
    """받아 둔 모델·능력·상주 상태를 모두 아는 가짜 Ollama."""

    def __init__(self) -> None:
        self.unloaded: list[str] = []
        self.current = ""

    def post(self, url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        if url.endswith("/api/show"):
            if body["model"] not in CAPS:
                raise RuntimeError("model not found")
            return {"capabilities": CAPS[body["model"]]}
        if body.get("keep_alive") == 0:
            self.unloaded.append(str(body.get("model") or ""))
            return {}
        self.current = str(body.get("model") or "")
        return {"response": "1, 2, 3", "eval_count": 64, "eval_duration": 1_000_000_000,
                "load_duration": 1_000_000_000}

    def get(self, url: str) -> dict[str, Any]:
        if url.endswith("/api/ps"):
            return {"models": [{"name": self.current, "size": 100, "size_vram": 100}]}
        return {"models": [{"name": name, "size": int(gb * 2**30), "digest": DIGESTS.get(name, name)}
                           for name, gb in SIZES.items()]}


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SetupService:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    config.model_roles = {"chat": "qwen3.5:9b", "vision": "qwen3.5:9b", "code": "qwen3.6:35b-a3b"}
    fake = _Ollama()
    saved: dict[str, Any] = {}
    made = SetupService(config, post=fake.post, get=fake.get,
                        patch_settings=lambda changes: (saved.update(changes), {"ok": True})[1])
    monkeypatch.setattr(made, "profile", lambda **_: PROFILE)
    made.ollama, made.saved = fake, saved  # type: ignore[attr-defined]
    return made


def _by_tag(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["tag"]: row for row in view["models"]}


# ── ① 사람이 직접 받은 모델 ──────────────────────────────────────────────────
def test_a_model_the_user_pulled_themselves_shows_up(service: SetupService) -> None:
    rows = _by_tag(service.picker("chat"))
    assert "mistral-small3.2:24b" in rows, "사용자가 직접 받은 모델이 목록에서 사라졌다"
    assert rows["mistral-small3.2:24b"]["installed"] is True
    assert rows["mistral-small3.2:24b"]["listed"] is False


def test_an_unlisted_model_says_we_never_measured_it(service: SetupService) -> None:
    """「목록에 없다」와 「나쁘다」는 다른 말이다 — 모른다고 적는다."""
    row = _by_tag(service.picker("chat"))["mistral-small3.2:24b"]
    assert row["grade"]["measured"] is False
    assert row["grade"]["label"] == "능력을 잰 적 없음"


def test_a_model_that_cannot_call_tools_is_shown_with_the_reason(service: SetupService) -> None:
    """빼 버리면 사용자는 왜 안 보이는지 모른 채 같은 벽에 계속 부딪친다."""
    rows = _by_tag(service.picker("chat"))
    assert "translategemma:4b" in rows
    assert "도구" in rows["translategemma:4b"]["blocked"]
    assert "임베딩" in rows["bge-m3:latest"]["blocked"]


def test_the_model_in_use_is_marked_per_role(service: SetupService) -> None:
    """대화와 코드는 서로 다른 모델을 쓴다 — ✓ 는 그 역할의 것에만 붙는다."""
    assert _by_tag(service.picker("chat"))["qwen3.5:9b"]["current"] is True
    assert _by_tag(service.picker("chat"))["qwen3.6:35b-a3b"]["current"] is False
    assert _by_tag(service.picker("code"))["qwen3.6:35b-a3b"]["current"] is True
    assert _by_tag(service.picker("code"))["qwen3.5:9b"]["current"] is False


def test_latest_suffix_does_not_split_one_model_into_two_rows(service: SetupService) -> None:
    """Ollama 는 같은 모델을 `x` 와 `x:latest` 두 이름으로 말한다."""
    tags = [row["tag"] for row in service.picker("chat")["models"]]
    assert len(tags) == len(set(t.lower().removesuffix(":latest") for t in tags))


def test_the_same_file_under_a_users_old_alias_is_not_offered_twice(service: SetupService) -> None:
    """★ 이 저장소가 겪은 사고 그대로 — 같은 파일을 두 이름으로 부르면 각자 러너를 띄워
    서로를 GPU 에서 쫓아낸다. 목록에 둘 다 두면 **사용자가 그 사고를 직접 만든다.**"""
    rows = _by_tag(service.picker("chat"))
    assert "qwen3.5:9b" in rows
    assert "my-old-alias:latest" not in rows, "같은 파일이 두 줄로 나왔다 — 태그 갈림의 입구"


def test_a_model_too_big_for_this_pc_says_so(service: SetupService, monkeypatch: pytest.MonkeyPatch) -> None:
    """목록 밖 모델도 **같은 자**로 잰다 — 규칙이 두 벌이면 갈린다."""
    small = {**PROFILE, "gpus": [{**PROFILE["gpus"][0], "vram_total_gb": 8.0}]}
    monkeypatch.setattr(service, "profile", lambda **_: small)
    row = _by_tag(service.picker("chat"))["mistral-small3.2:24b"]
    assert row["fits"] is False and "GB" in row["blocked"]


# ── ② 역할마다 따로 ─────────────────────────────────────────────────────────
def test_choosing_in_code_mode_does_not_change_the_chat_model(service: SetupService) -> None:
    result = service.select("mistral-small3.2:24b", role="code")

    assert result["ok"] is True, result
    assert service.saved == {"model_code": "mistral-small3.2:24b"}  # type: ignore[attr-defined]
    assert service.config.model_for("chat") == "qwen3.5:9b", "코드 모델을 고르려다 대화 모델이 바뀌었다"


def test_a_code_model_is_actually_run_before_it_is_saved(service: SetupService) -> None:
    """200 은 증거가 아니다 — 저장만 하고 못 도는 모델을 박으면 Code 탭이 통째로 죽는다."""
    service.select("mistral-small3.2:24b", role="code")
    assert service.last_bench is not None and service.last_bench["ok"]


def test_a_code_model_without_tools_is_refused(service: SetupService) -> None:
    result = service.select("translategemma:4b", role="code")
    assert result == {"ok": False, "error": "no_tool_calling"}
    assert service.saved == {}  # type: ignore[attr-defined]


def test_switching_the_code_model_unloads_the_old_one_first(service: SetupService) -> None:
    """3090 에 두 모델이 같이 올라가면 안 된다 — Ollama 는 스스로 안 내린다(8/31 재발)."""
    service.select("mistral-small3.2:24b", role="code")
    assert "qwen3.6:35b-a3b" in service.ollama.unloaded  # type: ignore[attr-defined]


def test_a_bad_tag_is_refused_for_every_role(service: SetupService) -> None:
    for bad in ("", "../evil", "a b", "x;rm", "C:\\model"):
        assert service.select(bad, role="code")["error"] == "bad_tag", bad
        assert service.select(bad, role="chat")["error"] == "bad_tag", bad
