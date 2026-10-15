"""편집이 빗나갔을 때 **어디가 가까운지** 말해 준다.

## 왜 (2026-09-05 실측, 최근 2,500 판)

    local_apply_edit   195 번 중 108 번 실패   (55%)
    그중 old_text_not_found                    107 건

실패 직후 3 걸음 패턴 1 위가 이랬다:

    local_read_text_file → local_apply_edit → local_apply_edit

**눈 감고 되풀이한다.** 오류 문구가 `old_text_not_found` 여섯 글자뿐이라 어디가
어긋났는지 알 길이 없기 때문이다.

## 왜 「전부 고쳐 주기」가 아닌가

앞 문서가 셀렉터 치유 사다리를 권했다. 그래서 이 자리에도 되는지 **재 봤다** —
실패한 107 건을 지금 파일과 맞춰 보니:

    지금은 완전일치 (그때 파일에 없었던 것)   33 (58%)   ← 매칭 문제가 아니다
    줄끝 공백·들여쓰기만 다름                  1
    90% 이상 비슷                              5
    진짜로 없음                               15
    (파일을 못 찾은 50 건 제외)

**퍼지 치유는 10% 를 건진다.** 그래서 자동으로 고치는 것은 되돌릴 걱정이 없는
둘(줄바꿈 방식·줄 끝 공백)로 묶고, 나머지는 **고치지 않고 보여만 준다.**
들여쓰기를 짐작해서 고치면 파이썬에서는 그게 곧 다른 코드다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.local_computer import _heal_old_text, _old_text_not_found_message


# ─────────────────────────────────────────────────────────────────────────────
# 자동으로 고치는 칸 — 되돌릴 걱정이 없는 것만
# ─────────────────────────────────────────────────────────────────────────────


def test_줄바꿈_방식만_다르면_고친다():
    """파일은 CRLF 인데 모델이 LF 로 적어 오는 일이 흔하다."""
    text = "def a():\r\n    return 1\r\n\r\ndef b():\r\n    return 2\r\n"
    healed, how = _heal_old_text(text, "def a():\n    return 1\n")
    assert how == "line_endings"
    assert healed and healed in text


def test_줄끝_공백만_다르면_고친다():
    text = "def a():   \n    return 1  \n\ndef b():\n    return 2\n"
    healed, how = _heal_old_text(text, "def a():\n    return 1\n")
    assert how == "trailing_whitespace"
    assert healed in text
    # ★ 파일에 **글자 그대로** 있는 조각을 돌려줘야 한다. 안 그러면 replace 가 안 먹는다.
    assert healed == "def a():   \n    return 1  \n"


def test_후보가_둘이면_안_고친다():
    """어느 쪽인지 모르는 것이고, 모르는 채 고치는 것이 못 고치는 것보다 나쁘다."""
    text = "x = 1  \ny = 2\n\nx = 1  \ny = 2\n"
    healed, how = _heal_old_text(text, "x = 1\ny = 2")
    assert (healed, how) == ("", "")


def test_들여쓰기가_다르면_안_고친다():
    """파이썬에서 들여쓰기를 짐작해 고치면 그건 다른 코드다 — 알려만 준다."""
    text = "def a():\n        return 1\n"
    healed, how = _heal_old_text(text, "def a():\n    return 1\n")
    assert (healed, how) == ("", "")


def test_진짜_없으면_안_고친다():
    text = "완전히 다른 내용이다\n"
    assert _heal_old_text(text, "def a():\n    return 1\n") == ("", "")


@pytest.mark.parametrize("old,text", [("", "abc"), ("abc", "")])
def test_비어_있으면_아무것도_안_한다(old, text):
    assert _heal_old_text(text, old) == ("", "")


# ─────────────────────────────────────────────────────────────────────────────
# 못 고칠 때 — 어디가 가까운지 짚어 준다
# ─────────────────────────────────────────────────────────────────────────────


def test_가까운_자리를_원문째_보여_준다():
    """★ 이게 이 파일의 핵심. 여섯 글자로 끝내면 모델은 눈 감고 되풀이한다."""
    text = "\n".join(
        ["import os", "", "def compaction_candidate(self, limit):", "        return found[:limit]", ""]
    )
    message = _old_text_not_found_message(text, "    def compaction_candidate(self, limit):\n        return found[:limit]")
    assert "old_text_not_found" in message
    assert "compaction_candidate" in message, "실제 원문을 보여 줘야 복사할 수 있다"
    assert "%" in message and "번째 줄" in message, "어디가 얼마나 가까운지 짚어야 한다"


def test_비슷한_데가_없으면_다시_읽으라고_한다():
    text = "전혀 상관 없는 문서입니다\n두 번째 줄\n"
    message = _old_text_not_found_message(text, "def zzz():\n    raise SystemExit(1)")
    assert "비슷한 자리도 못 찾았다" in message
    assert "local_read_text_file" in message


def test_짐작으로_적지_말라고_한다():
    """실측에서 「지금은 완전일치」가 58% 였다 — 그때 파일에 없던 것을 적어 온 것이다.

    매칭을 느슨하게 해서 될 일이 아니라, **다시 읽어야** 하는 일이다.
    """
    text = "전혀 상관 없는 문서입니다\n"
    assert "짐작으로 old 를 적지 마라" in _old_text_not_found_message(text, "def zzz():\n    pass")


def test_옛_문구를_그대로_품는다():
    """`old_text_not_found` 로 갈라 보는 자리가 여럿 있다(관문·되풀이 판정).

    문구를 길게 만들면서 그 앞머리를 잃으면 그 검사들이 조용히 눈이 먼다.
    """
    for text, old in (("a\n", "b\n"), ("def a():\n    return 1\n", "def a():\n    return 2\n")):
        assert _old_text_not_found_message(text, old).startswith("old_text_not_found")
