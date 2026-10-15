"""샌드박스가 없는 기기에서도 **저장소 코드 작업은 검증 게이트를 탄다** (2026-09-21, 노트북 4B 기준선).

## 어떻게 찾았나

8GB 노트북(스토어 빌드 — 샌드박스 없음)에서 Qwen 3.5 4B 에게 「테스트가 실패한다, 고쳐라」를 시켰다:

    4  local_apply_edit           `+ 1` 제거          ← 정답
    5  local_run_project_command  3 passed
    6  local_apply_edit           `+ 1` 을 **되돌려 넣음**   ← 통과한 코드를 스스로 깨뜨림
    9  local_run_project_command  failed
       답: 「+1 을 제거하고 다시 돌렸더니 3개 모두 통과했다」  ← 거짓
       completion_state = complete                             ← 그대로 통과

## 왜 게이트가 안 걸렸나

검증 게이트(`require_sandbox`)의 스위치 `_requires_coding` 이 **`sandbox_enabled` 가 켜져 있어야만** 참이었다.
샌드박스가 없는 기기에서는 항상 꺼져서 「검증을 안 돌리고 답하면 되받기」·「검증이 최신이 아니면 못 끝냄」·
`coding_verification_missing` 이 **전부 빠졌다.** 그런데 「통과 뒤 적대적 검토 턴」은 그 스위치와 무관하게 돌았다 —
검토만 있고 검증 게이트는 없는 기형이다.

저장소 작업의 검증은 상자가 아니라 `local_run_project_command` 가 한다. 상자 유무가 스위치일 이유가 없다.
그리고 **샌드박스 없는 기기가 곧 무료 티어**다(전략안 §10.1) — 제품의 가장 얇은 칸이 게이트 없이 돌고 있었다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime


class _Runtime:
    _requires_coding = JarvisRuntime._requires_coding

    def __init__(self, *, sandbox: bool) -> None:
        self.config = JarvisConfig()
        self.config.sandbox_enabled = sandbox
        self.sandbox = object() if sandbox else None


_FIX = "test_calc.py 가 실패한다. 원인을 찾아 calc.py 를 고치고 python -m pytest -q 로 통과를 확인해."


@pytest.mark.parametrize("sandbox", [True, False])
def test_a_repo_fix_is_coding_with_or_without_a_sandbox(sandbox: bool) -> None:
    assert _Runtime(sandbox=sandbox)._requires_coding(_FIX, code_workspace_selected=True) is True


def test_without_a_selected_folder_and_without_a_sandbox_it_is_still_not_coding() -> None:
    """폴더도 상자도 없으면 돌릴 곳이 없다 — 예전과 같다."""
    assert _Runtime(sandbox=False)._requires_coding(_FIX, code_workspace_selected=False) is False


def test_explaining_code_in_a_selected_folder_is_not_coding() -> None:
    """폴더를 골랐다고 모든 말이 코딩은 아니다 — 설명·질문은 게이트를 안 건다."""
    for prompt in ("이 프로젝트 구조가 어떻게 돼 있는지 설명해줘", "calc.py 가 무슨 일을 하는지 알려줘"):
        assert _Runtime(sandbox=False)._requires_coding(prompt, code_workspace_selected=True) is False, prompt


def test_the_sandbox_path_is_unchanged() -> None:
    """상자가 있을 때의 판정은 한 글자도 안 바뀐다."""
    runtime = _Runtime(sandbox=True)
    assert runtime._requires_coding("이 함수 코드를 짜줘") is True
    assert runtime._requires_coding("이 파이썬 코드가 무슨 뜻이야") is False


# ── 낱말표 구멍 (같은 날, 같은 사다리) ─────────────────────────────────────────
#
# `wants_code_action` 의 동사 목록이 「고쳐·수정해·만들어」 같은 몇 활용형만 알아서, 폴더를 고른 Code 모드에서도
# 「고치고」·「추가해」·「바꿔」 가 코딩으로 인식되지 않았다 — **샌드박스가 있는 이 PC 에서도** 검증 게이트가 꺼져 있었다.
# 사다리 여섯 중 셋(L3·L4·L5)이 그랬다. 이 저장소가 여러 번 겪은 「낱말표 구멍」이다.

@pytest.mark.parametrize(
    "prompt",
    [
        "test_calc.py 가 실패한다. 원인을 찾아 calc.py 를 고치고 pytest 로 확인해.",       # 고치고
        "textutil.py 에 word_count 함수를 추가해. 경계값도 처리해.",                      # 추가해
        "함수 get_user 의 이름을 fetch_user 로 바꿔. 테스트도 같이.",                     # 바꿔
        "이 버그를 고치자",
        "로그인 실패 처리를 넣어줘",
        "쓰지 않는 함수를 삭제해줘",
        "중복 코드를 제거해줘",
        "테스트가 통과하게 만들어줘",
    ],
)
def test_ordinary_korean_change_requests_are_code_actions(prompt: str) -> None:
    from alture_jarvis.plan import wants_code_action

    assert wants_code_action(prompt) is True, prompt


@pytest.mark.parametrize(
    "prompt",
    [
        "구조를 설명해줘",
        "하이하이",
        "이 프로젝트가 무슨 일을 하는지 알려줘",
        "이 함수를 어떻게 고치는지 설명해줘",       # 「고치」가 있어도 설명이다
        "왜 추가했는지 알려줘",
        "calc.py 가 뭐야",
        "이 코드 좀 분석해줘",
    ],
)
def test_explanations_and_questions_are_not_code_actions(prompt: str) -> None:
    """넓힌 만큼 오탐도 는다 — 설명 요청에 검증 게이트를 걸면 `coding_verification_missing` 으로 죽는다."""
    from alture_jarvis.plan import wants_code_action

    assert wants_code_action(prompt) is False, prompt


def test_the_old_forms_keep_working() -> None:
    from alture_jarvis.plan import wants_code_action

    assert wants_code_action("이 버그 고쳐줘") is True
    assert wants_code_action("테스트해") is True


def test_the_ladder_prompts_are_all_recognized() -> None:
    """사다리 여섯 과제가 전부 코딩으로 잡혀야 한다 — 하나라도 빠지면 그 과제는 게이트 없이 돈다."""
    import sys
    from pathlib import Path

    from alture_jarvis.plan import wants_code_action

    sys.path.insert(0, str(Path(__file__).parent.parent / "bench" / "coding"))
    import ladder  # noqa: PLC0415

    missed = [name for name, spec in ladder.TASKS.items() if not wants_code_action(spec["prompt"])]
    assert not missed, missed
