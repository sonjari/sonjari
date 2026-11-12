"""우리 검사가 돌려보낸 쓰기는 「만들어 봤음」이 아니다 (2026-11-08 맥 53366790 벤치 조사).

표 파일이 숫자 검사에 돌려보내지고(numbers_not_in_what_you_read), 다음 걸음은 꺼진 sandbox_run(tool_disabled)이었다.
둘 다 시도로 세어져 접기 전 파일 차례도 끝 안전망도 안 열렸고, 판은 「원문 값만 써서 파일을 만든다」 한 줄로 끝났다.
"""
from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis.answer_hygiene import _artifact_still_owed, artifact_really_attempted, last_write_refusal

_OWED = [(SimpleNamespace(kind="artifact", label="실제 산출물 파일 만들기"), False, "열 수 있는 산출물 없음")]

# 그 판의 마지막 세 걸음 그대로.
_THAT_RUN = [
    {"tool": "browser_extract", "ok": True},
    {"tool": "browser_open", "ok": False, "error": "not_this_stage"},
    {"tool": "local_write_document", "ok": False, "error": "numbers_not_in_what_you_read", "numbers": ["-1.8", "3.4"]},
    {"tool": "sandbox_run", "ok": False,
     "error": "tool_disabled — sandbox_run 은(는) 이 PC 에서 꺼져 있다. 다시 부르지 말고 다른 도구로 하라."},
]


def test_refused_and_disabled_writes_still_owe_the_file() -> None:
    assert artifact_really_attempted(_THAT_RUN) is False
    assert _artifact_still_owed(_OWED, _THAT_RUN) is True, "파일 차례를 한 번 줘야 한다"


def test_the_refusal_reason_is_handed_back() -> None:
    note = last_write_refusal(_THAT_RUN)
    assert note.startswith("numbers_not_in_what_you_read") and "-1.8" in note
    assert "tool_disabled" not in note, "꺼진 도구는 고칠 까닭이 아니다"


def test_a_real_attempt_still_counts() -> None:
    saved = _THAT_RUN + [{"tool": "local_write_document", "ok": True}]
    assert artifact_really_attempted(saved) is True and _artifact_still_owed(_OWED, saved) is False
    broken = [{"tool": "local_write_document", "ok": False, "error": "PermissionError: disk full"}]
    assert artifact_really_attempted(broken) is True, "도구 쪽 사정으로 실패한 것은 시도다(다시 밀지 않는다)"
