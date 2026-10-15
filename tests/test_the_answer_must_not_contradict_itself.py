"""답이 **자기 두 줄 사이에서 모순되면** 잡는다 (2026-09-21 AURORA 2차).

## 무슨 일

판은 합격했는데(19걸음·complete·verified) 답이 이랬다:

    ...
    - `verify_aurora.py` 는 검증 완료 후 `local_delete_file` 로 **삭제했습니다**.

    만든 파일:
    - ...\\index.html
    - ...\\verify_aurora.py          ← 두 줄 아래

걸음을 보면 둘 다 사실이다 — 17걸음에서 지웠고, 18걸음에서 **다시 만들었다.**
그래서 「삭제했습니다」는 그때는 참이었고 지금은 거짓이다. 파일은 디스크에 남아 있다.

## 왜 이걸 잡아야 하나

사람이 읽는 것은 **답**이다. 「지웠습니다」를 읽고 안 지운 파일이 남으면, 그건
이 저장소가 여러 번 겪은 「안 한 일을 했다고 한다」와 같은 자리다. 다만 이번 것은
더 잡기 쉽다 — **답이 스스로 증거를 옆에 적어 놨다.**

## 무엇을 하고 무엇을 안 하나

지우지 **않는다.** 답을 고치지도 않는다. 원장에 **모순을 적는다** — 사람과 다음 판이
볼 수 있게. 조용히 고치면 다음에 또 모르고, 조용히 넘어가면 사람이 속는다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.answer_audit import contradictions

DELETED_BUT_LISTED = """작업을 마쳤습니다.

## 3. 남은 제한
- `verify_aurora.py` 는 검증 완료 후 `local_delete_file` 로 삭제했습니다.

만든 파일:
- C:\\Users\\user\\Documents\\aurora\\index.html
- C:\\Users\\user\\Documents\\aurora\\verify_aurora.py
"""

CLEAN = """작업을 마쳤습니다.

- `verify_aurora.py` 는 검증 완료 후 삭제했습니다.

만든 파일:
- C:\\Users\\user\\Documents\\aurora\\index.html
"""


def test_saying_it_deleted_a_file_it_also_lists_is_caught() -> None:
    """★ 실전에서 나온 그 모양 — 같은 답의 두 줄이 서로를 부정한다."""
    found = contradictions(DELETED_BUT_LISTED)
    assert found, "「삭제했습니다」와 만든 파일 목록이 부딪치는데 아무도 안 잡았다"
    assert "verify_aurora.py" in found[0]["detail"]


def test_a_consistent_answer_is_not_flagged() -> None:
    """멀쩡한 답에 경고를 붙이면 아무도 경고를 안 읽는다."""
    assert contradictions(CLEAN) == []


def test_an_answer_with_no_file_list_is_not_flagged() -> None:
    assert contradictions("조사만 했고 파일은 안 만들었습니다.") == []


def test_only_the_named_file_is_flagged() -> None:
    """다른 파일까지 싸잡아 잡으면 진짜를 가린다."""
    found = contradictions(DELETED_BUT_LISTED)
    assert len(found) == 1
    assert "index.html" not in found[0]["detail"]


@pytest.mark.parametrize("said", [
    "`probe.py` 를 삭제했습니다.",
    "probe.py 는 지웠습니다.",
    "검증 파일(probe.py)을 제거했습니다.",
])
def test_the_common_ways_of_saying_deleted_are_all_caught(said: str) -> None:
    answer = f"{said}\n\n만든 파일:\n- C:\\x\\probe.py\n"
    assert contradictions(answer), said


def test_a_file_only_mentioned_in_prose_is_not_a_contradiction() -> None:
    """만든 파일 목록에 없으면 모순이 아니다 — 지웠다는 말만 있는 것은 정상이다."""
    assert contradictions("probe.py 를 삭제했습니다. 끝났습니다.") == []
