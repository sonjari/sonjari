"""화면을 만들라고 하면 **디자인 지침이 같이 가야 한다** (2026-09-20 사장님 지시).

> "프론트 한번 시켜보면 딱 답 나오거든 — 클로드 아티팩트 스킬 써서 리액트 단일 페이지 데모
>  잘 만드는지 한번 봐줘. 이것도 중요하데이."

## 재 보니 안 닿고 있었다 (실측)

`frontend-design` 의 트리거가 **「디자인」이라는 낱말을 요구**했다:

    리액트로 단일 페이지 데모 하나 만들어줘      -> ['react']            ← 디자인 지침 없음
    프론트엔드 디자인 해서 리액트 페이지 만들어줘  -> ['frontend-design', 'react']

사람은 "데모 페이지 만들어줘"라고 하지 "프론트엔드 디자인 해줘"라고 하지 않는다. 그래서
**아티팩트 같은 화면을 만들라는 지침이 모델에 한 번도 안 갔다.** 「스킬 85개가 일에 닿지
않았다(11/11,043회)」와 같은 자리이고, 고치는 방법도 같다 — **트리거는 캐서 쓴다.**

★ 그렇다고 「리액트」 한 낱말로 붙이지는 않는다. 그러면 컴포넌트 한 줄 고치는 판에도
  디자인 플레이북이 실려 시스템 메시지 자리를 도구 규율과 다툰다(이 저장소가 아는 함정).
  **무언가를 「화면/페이지로 만들어 달라」**는 모양일 때만 붙인다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.skills import match_skills


def _names(prompt: str) -> list[str]:
    return [name for name, _hits in match_skills(prompt) or []]


@pytest.mark.parametrize("prompt", [
    "리액트로 단일 페이지 데모 하나 만들어줘",
    "리액트 단일 페이지 데모 만들어줘. 보기 좋게.",
    "학원 대시보드 랜딩 페이지를 리액트로 만들어줘",
    "예약 현황 보여 주는 화면 하나 만들어줘",
    "소개 페이지 만들어줘",
])
def test_asking_for_a_screen_brings_the_design_playbook(prompt: str) -> None:
    assert "frontend-design" in _names(prompt), f"디자인 지침이 안 붙는다: {prompt}"


@pytest.mark.parametrize("prompt", [
    "리액트 컴포넌트에서 상태 갱신이 안 되는 버그 고쳐줘",
    "이 저장소 테스트 깨진 것 고쳐줘",
    "예약 겹침 검사 로직 수정해줘",
])
def test_plain_code_work_does_not_drag_the_design_playbook(prompt: str) -> None:
    """★ 넓히면 반대쪽으로 넘어간다. 고치는 판에는 붙으면 안 된다."""
    assert "frontend-design" not in _names(prompt), f"쓸데없이 붙었다: {prompt}"


def test_the_old_wording_still_works() -> None:
    """예전 낱말을 지우지 않는다 — 쓰던 사람이 있다."""
    assert "frontend-design" in _names("웹 화면 디자인해서 리액트로 만들어줘")
