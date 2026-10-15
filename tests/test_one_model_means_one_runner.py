"""같은 모델이면 **컨텍스트도 같아야 한다** (2026-09-21 실측).

## 무슨 일이 있었나

사장님 PC 실측:

    /health  context.by_role = {"chat": 131072, "code": 102400, "vision": 131072}
    model_roles             = {"chat": qwen3.6, "code": qwen3.6, "vision": qwen3.6}

**같은 모델인데 컨텍스트가 갈려 있었다.** 원인은 OS 사용자 환경변수에 남은 옛값:

    JARVIS_OLLAMA_CODE_MODEL   = qwen3.8:27b-mtp-q4_K_M   ← 설정(qwen3.6)이 이김
    JARVIS_OLLAMA_CODE_NUM_CTX = 102400                   ← 이건 아무도 안 덮음

Qwen 3.8 을 쓰던 시절 3090 실측으로 정한 값이 모델이 바뀐 뒤에도 남았다.

## 왜 나쁜가

이 저장소가 아는 사고다 — **num_ctx 가 다르면 Ollama 는 러너를 새로 띄운다.**
`OLLAMA_MAX_LOADED_MODELS=1` 이라 새 러너가 옛 러너를 쫓아낸다. 즉 **Cowork 탭과
Code 탭을 오가는 것만으로** 23GB 재적재가 걸린다. 모델 이름은 같은데.

`config.py` 의 주석이 이미 그렇게 적고 있었다 —
「비우면 대화 모델과 같은 컨텍스트 — 다르면 러너를 새로 띄워 축출한다」.
비우지 **못한** 경우를 아무도 안 막고 있었을 뿐이다.

## 규칙

역할의 모델이 대화 모델과 **같은 태그**면, 그 역할의 컨텍스트는 대화 것을 따른다.
모델이 정말 다를 때만 따로 간다 — 그때는 어차피 러너가 둘이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig


def _config(tmp_path: Path, *, chat: str, code: str, chat_ctx: int, code_ctx: int) -> JarvisConfig:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    config.model_roles = {"chat": chat, "code": code, "vision": chat}
    config.ollama_num_ctx = chat_ctx
    config.model_num_ctx = {"code": code_ctx}
    return config


def test_the_same_model_gets_the_same_context(tmp_path: Path) -> None:
    """★ 실전에서 갈려 있던 것 — 같은 qwen3.6 인데 131072 / 102400."""
    config = _config(tmp_path, chat="qwen3.6:35b-a3b", code="qwen3.6:35b-a3b",
                     chat_ctx=131072, code_ctx=102400)
    assert config.num_ctx_for("code") == config.num_ctx_for("chat") == 131072


def test_latest_suffix_does_not_count_as_a_different_model(tmp_path: Path) -> None:
    config = _config(tmp_path, chat="qwen3.6:35b-a3b", code="qwen3.6:35b-a3b:latest",
                     chat_ctx=131072, code_ctx=102400)
    assert config.num_ctx_for("code") == 131072


def test_an_empty_code_model_follows_chat_as_before(tmp_path: Path) -> None:
    config = _config(tmp_path, chat="qwen3.6:35b-a3b", code="", chat_ctx=131072, code_ctx=102400)
    assert config.num_ctx_for("code") == 131072


def test_a_genuinely_different_model_keeps_its_own_context(tmp_path: Path) -> None:
    """모델이 다르면 러너가 어차피 둘이다 — 그때는 그 모델에 맞는 값을 쓴다."""
    config = _config(tmp_path, chat="qwen3.6:35b-a3b", code="qwen3.8:27b-mtp-q4_K_M",
                     chat_ctx=131072, code_ctx=102400)
    assert config.num_ctx_for("code") == 102400


def test_chat_itself_is_untouched(tmp_path: Path) -> None:
    config = _config(tmp_path, chat="qwen3.6:35b-a3b", code="qwen3.6:35b-a3b",
                     chat_ctx=131072, code_ctx=102400)
    assert config.num_ctx_for("chat") == 131072
    assert config.num_ctx_for("vision") == 131072


@pytest.mark.parametrize("code_ctx", [0, None])
def test_no_code_context_at_all_still_follows_chat(tmp_path: Path, code_ctx) -> None:
    config = _config(tmp_path, chat="qwen3.6:35b-a3b", code="qwen3.6:35b-a3b",
                     chat_ctx=131072, code_ctx=0)
    config.model_num_ctx = {"code": code_ctx} if code_ctx is not None else {}
    assert config.num_ctx_for("code") == 131072


def test_the_floor_still_applies(tmp_path: Path) -> None:
    """너무 작은 값은 예전처럼 바닥에서 걸린다 — 이 고침이 바닥을 없애면 안 된다."""
    config = _config(tmp_path, chat="qwen3.6:35b-a3b", code="other-model:7b",
                     chat_ctx=131072, code_ctx=1024)
    assert config.num_ctx_for("code") == 4096
