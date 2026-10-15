"""손자리가 켜는 Ollama 에 서버의 대화 보관함 한도를 이 PC 메모리에 맞춰 넘긴다 (2026-10-10).

대표: 「뒤죽박죽으로 시간이 오래 걸린다」 → 「이거 들어가자」. 서버는 최근 대화의 상태를 보관함(기본 8GB)에 넣어 두는데, 작은 호출이
몇 번 끼어들면 하던 큰 대화가 밀려나고, 돌아오면 통째로 다시 읽는다(이 PC 의 사흘 기록에서 439번).

잰 값(27B · 128K · 큰 대화 5만 토큰 → 작은 호출 16번 → 돌아와서 읽은 시간 · 세 판씩):
8GB 59.5 · 62.0 · 53.8초 / 12GB 59.0 · 59.0 · 58.9초 / 24GB 0.5 · 0.6 · 0.5초. 한도를 올리면 서버가 그만큼 메모리를 실제로 쓴다.

눈금 주의: 이 시험은 **무엇을 넘기는가**만 본다. 넘긴 값이 서버에 닿는 것은 Ollama 기록의 `limits:` 줄로 확인했다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis import ollama_install
from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama_install import PROMPT_CACHE_ENV, OllamaInstaller, ollama_launch_env, prompt_cache_mib


def test_the_limit_follows_the_memory_of_this_pc() -> None:
    assert prompt_cache_mib(63.7) == 24576
    assert prompt_cache_mib(31.9) == 12288
    # ★ 2026-10-14: 작은 메모리는 **줄인다.** 예전에는 손대지 않아 서버 기본(8GB)이 걸렸고, 메모리 24GB 노트북에서
    #   실행기가 12GB 까지 쓰다 죽었다(`std::bad_alloc`).
    assert prompt_cache_mib(23.7) == 4096, "24GB 급 — 그날 밤 꺼진 노트북"
    assert prompt_cache_mib(15.6) == 4096, "16GB 급"
    assert prompt_cache_mib(7.8) == 2048, "8GB 급"
    assert prompt_cache_mib(None) == 0 and prompt_cache_mib(0) == 0, "못 재면 손대지 않는다"
    for ram, mib in ((63.7, 24576), (31.9, 12288), (23.7, 4096), (15.6, 4096), (7.8, 2048)):
        assert mib <= ram * 1024 * 0.4, "보관함이 메모리의 4할을 넘지 않는다"


def test_the_launch_environment_carries_it() -> None:
    assert ollama_launch_env(ram_gb=64.0, environ={"PATH": "x"})[PROMPT_CACHE_ENV] == "24576"
    assert ollama_launch_env(ram_gb=32.0, environ={"PATH": "x"})[PROMPT_CACHE_ENV] == "12288"
    assert ollama_launch_env(ram_gb=16.0, environ={"PATH": "x"})[PROMPT_CACHE_ENV] == "4096", "작은 메모리는 줄여서 넘긴다"
    assert PROMPT_CACHE_ENV not in ollama_launch_env(ram_gb=0.0, environ={"PATH": "x"}), "못 잰 PC 는 손대지 않는다"
    assert ollama_launch_env(ram_gb=64.0, environ={"PATH": "x"})["PATH"] == "x"


def test_a_value_the_person_set_is_never_replaced() -> None:
    env = ollama_launch_env(ram_gb=64.0, environ={PROMPT_CACHE_ENV: "4096"})
    assert env[PROMPT_CACHE_ENV] == "4096"
    assert ollama_launch_env(20000, ram_gb=64.0, environ={PROMPT_CACHE_ENV: "0"})[PROMPT_CACHE_ENV] == "0"


def test_the_setting_can_fix_it_or_leave_it_alone() -> None:
    assert ollama_launch_env(16384, ram_gb=16.0, environ={})[PROMPT_CACHE_ENV] == "16384"
    assert PROMPT_CACHE_ENV not in ollama_launch_env(0, ram_gb=64.0, environ={})
    config = JarvisConfig()
    assert config.ollama_prompt_cache_mib == -1, "기본은 메모리에 맞춰 스스로"


def test_the_card_limits_of_the_person_still_go_back_to_ollama() -> None:
    """보관함을 얹느라 `gpu_policy` 가 하던 일(사용자의 카드 제한을 Ollama 에 돌려주기)이 빠지면 안 된다."""
    from alture_jarvis.gpu_policy import INHERITED_KEY, child_env_for_ollama

    environ = {INHERITED_KEY: "1", "CUDA_VISIBLE_DEVICES": "0,1"}
    assert ollama_launch_env(0, environ=dict(environ)) == child_env_for_ollama(dict(environ))
    assert ollama_launch_env(ram_gb=64.0, environ=dict(environ))["CUDA_VISIBLE_DEVICES"] == "1"


def test_every_place_that_starts_ollama_uses_it(tmp_path: Path) -> None:
    """Ollama 를 켜는 자리는 셋이다(우리 것 · 사람이 깐 것 · 다시 켜기). 하나라도 빠지면 그 길로 켠 Ollama 만 한도가 다르다."""
    source = inspect.getsource(OllamaInstaller)
    assert source.count("ollama_launch_env(self.prompt_cache_mib)") == 3
    assert "child_env_for_ollama" not in source, "카드 제한만 넘기던 옛 길이 남아 있다"
    assert OllamaInstaller(install_root=tmp_path).prompt_cache_mib == -1
    assert OllamaInstaller(install_root=tmp_path, prompt_cache_mib=0).prompt_cache_mib == 0


def test_it_is_not_written_into_the_users_environment() -> None:
    """이 이름은 Ollama 만의 것이 아니다 — llama.cpp 를 쓰는 모든 프로그램이 읽는다. 사용자 환경변수(레지스트리)에 적지 않는다."""
    source = inspect.getsource(ollama_install)
    assert "_write_user_env(PROMPT_CACHE_ENV" not in source and '_write_user_env("LLAMA_ARG' not in source
    assert "os.environ[PROMPT_CACHE_ENV]" not in source, "백엔드 자신의 환경에도 두지 않는다 — 사용자의 명령으로 샌다"


def test_the_runtime_hands_the_setting_to_the_installer() -> None:
    from alture_jarvis import runtime

    assert 'prompt_cache_mib=int(getattr(self.config, "ollama_prompt_cache_mib", -1))' in inspect.getsource(runtime)
