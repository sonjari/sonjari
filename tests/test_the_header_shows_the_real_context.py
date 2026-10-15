"""머리에 적힌 컨텍스트는 **실제로 올라간 값**이어야 한다 (2026-09-21 사장님 지적).

> 아직 코드모드에서 100k로 뜨는거 이거는 잡아주라잉 실제 실측(올라마에 올라가있는 걸로 가야돼)

## 무슨 일

`num_ctx_for()` 를 고쳐 실효값은 131072 가 됐는데 **화면은 여전히 100K** 였다.

    /v1/config  model_num_ctx = {"code": 102400}   ← 화면이 읽는 것 (덮어쓰기 **원본**)
    /health     by_role       = {"code": 131072}   ← 실효값
    /api/ps     context_length = 131072            ← 진짜 올라간 값

`public_dict()` 가 dataclass 를 통째로 내보내서, 고치기 전의 **원본 덮어쓰기 값**이
그대로 화면에 갔다. 값이 사는 자리가 또 갈린 것이다 — 이번엔 **계산한 값과 원본**.

## 규칙

밖으로 나가는 것은 **쓰이는 값**이다. 원본은 안에서만 쓴다.
그리고 올라마가 실제 `context_length` 를 주므로, 화면은 그것을 첫 번째 진실로 쓴다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig


def _config(tmp_path: Path) -> JarvisConfig:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    config.model_roles = {"chat": "qwen3.6:35b-a3b", "code": "qwen3.6:35b-a3b", "vision": "qwen3.6:35b-a3b"}
    config.ollama_num_ctx = 131072
    # OS 환경변수에서 온 옛값 — 같은 모델이라 실효값은 131072 여야 한다.
    config.model_num_ctx = {"code": 102400}
    return config


def test_the_public_config_reports_the_context_that_is_actually_used(tmp_path: Path) -> None:
    """★ 화면이 100K 로 뜨던 자리 — 원본이 아니라 **쓰이는 값**을 내보낸다."""
    public = _config(tmp_path).public_dict()
    assert public["model_num_ctx"]["code"] == 131072, public["model_num_ctx"]


def test_every_role_is_listed_so_the_screen_never_guesses(tmp_path: Path) -> None:
    """화면에 없는 역할이 있으면 화면이 제 나름의 기본값을 쓴다 — 그게 하드 상수 102400 이었다."""
    public = _config(tmp_path).public_dict()
    assert set(public["model_num_ctx"]) == {"chat", "code", "vision"}
    assert all(v == 131072 for v in public["model_num_ctx"].values())


def test_a_genuinely_different_model_still_shows_its_own_context(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.model_roles["code"] = "qwen3.8:27b-mtp-q4_K_M"
    assert config.public_dict()["model_num_ctx"]["code"] == 102400


def test_the_raw_override_is_still_what_the_code_reads(tmp_path: Path) -> None:
    """밖으로 내보내는 모양을 바꿨다고 **안에서 쓰는 값**까지 흔들리면 안 된다."""
    config = _config(tmp_path)
    config.public_dict()
    assert config.model_num_ctx == {"code": 102400}, "내보내면서 원본을 망가뜨렸다"
    assert config.num_ctx_for("code") == 131072
