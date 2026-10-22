"""예고를 다시 쓰게 할 때 「파일은 못 만드니 표를 답에 직접 써라」고 말한다 (2026-10-22 잡 238d2dfa).

「표로 정리해 파일로」 요구에 페이지 9개를 읽고, 보안 문자 대기 뒤 끝내기에서 「마크다운 파일로 만들겠습니다」로 끝났다.
다시 쓰기 관문도 도구가 없는 자리라 또 예고였다. 답에 쓴 표는 끝에서 손자리가 파일로 옮겨 저장한다(`closing`) —
그러니 다시 쓰기는 표를 답에 쓰라고 알려야 하고, 그 저장은 다시 쓰기 **뒤에** 돌아야 한다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis import agent as agent_mod

SOURCE = Path(agent_mod.__file__).read_text(encoding="utf-8")


def test_the_rewrite_tells_the_model_to_put_the_table_in_the_answer() -> None:
    rewrite = SOURCE.index('purpose="rewrite_announce"')
    prompt_start = SOURCE.rindex("방금 말은 다음 걸음 예고", 0, rewrite)
    prompt = SOURCE[prompt_start:rewrite]
    assert "이 답에 직접" in prompt and "만들겠습니다" in prompt


def test_the_table_to_file_save_runs_after_the_rewrite() -> None:
    rewrite = SOURCE.index('purpose="rewrite_announce"')
    closing_save = SOURCE.index("답의 표를 파일로 옮겨 저장했습니다")
    assert rewrite < closing_save
