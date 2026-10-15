"""「모델 이름 직접 입력」은 허깅페이스 주소도 받는다 (2026-10-01 헤르메스 비교 중 발견).

Ollama 는 `hf.co/작성자/저장소:양자화` 로 허깅페이스 GGUF 를 바로 받는다. 이름 검사가 슬래시 둘·대문자를 거절해
그 길이 막혀 있었다 — 목록 밖 모델을 쓰고 싶은 사람에게 「되긴 된다」고 말할 수 없는 상태였다.
"""

from alture_jarvis.model_setup import OLLAMA_TAG


def test_ollama_library_tags_still_pass():
    for tag in ("qwen3.5:9b", "gemma4:12b-it-qat", "huihui_ai/qwen3.5-abliterated:9b", "llama3"):
        assert OLLAMA_TAG.fullmatch(tag), tag


def test_hugging_face_gguf_tags_pass():
    for tag in (
        "hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M",
        "hf.co/bartowski/Qwen_Qwen3.5-9B-GGUF",
        "huggingface.co/lmstudio-community/Qwen3.5-9B-GGUF:Q6_K",
    ):
        assert OLLAMA_TAG.fullmatch(tag), tag


def test_shell_and_path_tricks_are_still_refused():
    for tag in (
        "qwen3.5:9b; rm -rf /",
        "../../etc/passwd",
        "hf.co/../secrets",
        "hf.co/a/b/c",
        "https://evil.example/model",
        "Qwen3.5:9b",  # 대문자 라이브러리 이름은 Ollama 도 안 받는다
        "",
    ):
        assert not OLLAMA_TAG.fullmatch(tag), tag
