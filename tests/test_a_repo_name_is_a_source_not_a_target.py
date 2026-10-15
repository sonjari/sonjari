"""「llama.cpp 저장소 문서에서 … 워드로 만들어 줘」는 코딩이 아니다.

★ 2026-09-28 MCP 위임 판 8453471b. 워드는 제대로 만들었는데 `llama.cpp` 의 `.cpp` 가 파일 대상에, `만들어` 가 동사에 걸려 코딩 과제가
됐다 — 코드 검증을 두 번 되받은 뒤 `coding_verification_missing` 으로 **실패**. 「파이썬 책」(09-07)·「'클린 코드' 책」(09-14)과 같은
병이다. 운영 DB 과거 요청 2,373건에 옛 판정·새 판정을 같이 돌려 바뀐 것은 이 한 건뿐이었다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import wants_code


@pytest.mark.parametrize("prompt", [
    "GitHub 의 llama.cpp 저장소 문서에서 MoE 모델의 전문가 층을 일부만 CPU 로 보내는 옵션(--override-tensor, --n-cpu-moe 등)을 "
    "찾아 읽고, 옵션 이름·뜻·예시 명령을 표로 정리한 워드 파일로 만들어 줘.",
    "whisper.cpp README 를 읽고 설치 순서를 한글 문서로 만들어 줘",
    "Read the llama.cpp repo README and make a Word file summarizing the MoE offload options.",
])
def test_a_repo_that_is_read_from_is_not_a_coding_target(prompt: str) -> None:
    assert not wants_code(prompt)


@pytest.mark.parametrize("prompt", [
    "llama.cpp 빌드 스크립트 만들어 줘",
    "main.cpp 고쳐 줘",
    "app.py 에 로그인 함수를 만들어 줘",
    "Fix main.cpp so the tests pass",
])
def test_real_coding_requests_stay_coding(prompt: str) -> None:
    assert wants_code(prompt)


def test_a_repo_name_is_not_the_asked_file_type() -> None:
    """같은 판의 두 번째 병: 계획 층이 `.cpp` 를 **시킨 형식**으로 잡아, 워드를 만들었는데 「열 수 있는 산출물 없음」.

    09-28 아침 판 78671832(속말로 끝난 판)도 이것으로 `.cpp`·`.md` 를 요구받아 산출물 되받기·집중 전환을 탔다 — 과거 요청
    2,373건 중 판정이 바뀐 것은 이 두 llama.cpp 판뿐이었다.
    """
    from alture_jarvis.plan import artifact_extensions

    assert artifact_extensions("GitHub 의 llama.cpp 저장소 문서에서 옵션을 읽고 표로 정리한 워드 파일로 만들어 줘") == (".docx",)
    assert artifact_extensions("Read the llama.cpp repo README and make a Word file") == (".docx",)
    assert artifact_extensions("main.cpp 에 함수 추가해 줘") == (".cpp",)
