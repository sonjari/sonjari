"""Code 탭의 과제 문장은 **만들 물건의 사양서**다 — 읽기 개수·셈 요구를 낱말로 뽑지 않는다 (2026-09-30).

코드 벤치: 「⑤ 폭 360px 모바일에서도 안 깨지는」의 「모바일에서」가 출처로 읽혀, 만들 앱의 예시인 「참가자 3명」이
「3개 이상 직접 열어 읽기」가 됐고, 되받기가 다 만든 판을 붙잡아 자기 파일을 다섯 걸음 다시 읽게 했다.
운영 코드 판 196개로 재 봤다: 헛걸린 것은 읽기 개수와 「직접 계산해 보기」뿐. 역검증(요청 1,306개): 코드 탭 3건만
바뀌고(전부 오독) 코워크 판은 0건 — 「마이크로소프트 스토어에서 메모 앱 3개」 같은 진짜 조사는 그대로다.
"""

from __future__ import annotations

from alture_jarvis import plan

TRAVEL = ("이 폴더에 「여행 경비 정산」 웹앱을 만들어줘. index.html · style.css · app.js 세 파일로. "
          "⑤ 폭 360px 모바일에서도 안 깨지는 반응형과 다크 모드. node 로 돌리는 test.js 를 만들어 통과시켜. "
          "끝나면 브라우저로 index.html 을 열어 참가자 3명·지출 2건을 실제로 넣고 정산 결과가 맞는지 확인해.")


def _kinds(prompt: str, **kw) -> set[str]:
    return {r.kind for r in plan.extract(" ".join(prompt.split()), **kw)}


def test_the_spec_numbers_do_not_become_reading_counts_in_the_code_tab() -> None:
    kinds = _kinds(TRAVEL, has_named_source=True, must_observe=True, observe_from={"workspace"}, code_workspace=True)
    assert "count" not in kinds
    assert "artifact" in kinds, "만든 파일은 그대로 본다"


def test_a_computation_is_left_to_the_tests_in_the_code_tab() -> None:
    reqs = plan.extract("12, 15, 20 의 평균을 계산하는 함수를 만들고 pytest 로 확인해", code_workspace=True)
    assert not any(r.kind == "action" and r.target == "sandbox_run" for r in reqs)


def test_naming_a_readable_place_keeps_the_count_in_the_code_tab() -> None:
    """코드 모드에서도 진짜 조사(「github.com 에서 라이브러리 3개 비교」)는 개수를 지킨다."""
    kinds = _kinds("github.com 에서 날짜 라이브러리 3개를 찾아 읽고 비교표를 README.md 로 만들어줘",
                   has_named_source=True, must_observe=True, code_workspace=True)
    assert "count" in kinds


def test_outside_the_code_tab_nothing_changes() -> None:
    """역방향 — 아는 사이트 목록 밖의 진짜 출처(마이크로소프트 스토어)는 코워크에서 여전히 3개를 읽는다."""
    kinds = _kinds("마이크로소프트 스토어에서 메모 앱 3개를 찾아 이름·가격·평점을 엑셀로 정리해 줘", has_named_source=True)
    assert "count" in kinds
