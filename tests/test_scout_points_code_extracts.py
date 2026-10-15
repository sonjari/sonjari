"""정찰기는 **짚고**, 원문은 **코드가 꺼낸다.**

## 왜 이 파일이 있는가 (2026-09-05)

`local_apply_edit` 이 최근 2,500 판에서 195 번 중 108 번 실패했다(55%). 그중
107 건이 `old_text_not_found` 이고, **39% 는 끝내 못 고쳤다.** 고친 것도 주 모델
왕복을 중앙 2 회(≈20 초) 더 썼다.

결정론 사다리(줄바꿈·줄끝 공백)는 이 중 10% 만 건진다 — 그래서 4칸을 놓았다.

## ★ 라이브가 설계를 한 번 뒤집었다

처음엔 정찰기에게 **원문을 그대로 옮겨 적게** 했다. 라이브 3 건이 전부 실패했다:

    받아쓰기  0/3 통과   ·  느린 것은 23.4초  ← 9B 가 들여쓰기·공백을 정규화한다
    줄 번호   3/3 정상   ·  1.7~1.9초

작은 모델에게 받아쓰기는 어렵고 **짚기는 쉽다.** 원문을 꺼내는 일은 코드가 하면
되고, 그러면 받아쓰기 오류라는 실패 원인이 아예 사라진다. 이 저장소의 규율과도
더 맞는다 — 정찰기는 읽고, **판정과 추출은 코드가 한다.**

## 이 파일이 지키는 불변식

정찰기가 무슨 번호를 답하든, 코드가 꺼낸 조각이 **파일에 글자 그대로 있고 딱 한
번 나올 때만** 쓴다. 그래서 정찰기는 편집을 **살릴 수만 있고 망칠 수는 없다.**
"""

from __future__ import annotations

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.grounding_scout import (
    _anchor_windows,
    _span_of,
    drain_calls,
    find_anchor,
    record_call,
    reset_breaker,
    summarize_calls,
)

FILE = (
    "import os\n"
    "\n"
    "def alpha(value):\n"
    "    total = value + 1\n"
    "    return total\n"
    "\n"
    "def beta(value):\n"
    "    total = value + 2\n"
    "    return total\n"
)
LINES = FILE.split("\n")


# ─────────────────────────────────────────────────────────────────────────────
# 코드가 꺼내는 부분 — 정찰기 없이도 지켜져야 하는 것
# ─────────────────────────────────────────────────────────────────────────────


def test_짚어_준_줄을_원문_그대로_꺼낸다():
    span = _span_of(LINES, 3, 5, "def alpha(value):\n    total\n    return total")
    assert span == "def alpha(value):\n    total = value + 1\n    return total"
    assert span in FILE


@pytest.mark.parametrize(
    "start,end,why",
    [
        (0, 5, "0은 줄 번호가 아니다"),
        (5, 3, "범위가 뒤집혔다"),
        (99, 120, "파일 밖이다"),
        (-2, 4, "음수다"),
    ],
)
def test_말이_안_되는_범위는_안_쓴다(start, end, why):
    assert _span_of(LINES, start, end, "def alpha(value):") == "", why


def test_터무니없이_넓게_잡으면_안_쓴다():
    """넓게 잡아 바꾸면 편집이 아니라 삭제가 된다."""
    assert _span_of(LINES, 1, 9, "return total") == ""


def test_후보_창에는_줄_번호가_붙는다():
    """정찰기가 답할 것이 이 번호다. 번호가 없으면 짚을 수가 없다."""
    windows = _anchor_windows(LINES, "def beta(value):\n    total = value + 2")
    assert windows
    assert any(line.startswith("7: def beta(value):") for line in windows[0].split("\n"))


def test_파일_전체를_주지_않는다():
    """정찰기에게는 후보 top-K 만 준다 — 토큰도 시간도 그만큼만 쓴다."""
    big = "\n".join(f"line {n}" for n in range(1, 400))
    windows = _anchor_windows(big.split("\n"), "line 200\nline 201")
    assert 1 <= len(windows) <= 3
    assert sum(len(w.split("\n")) for w in windows) < 60


# ─────────────────────────────────────────────────────────────────────────────
# 정찰기가 무슨 말을 하든 — 살릴 수만 있고 망칠 수는 없다
# ─────────────────────────────────────────────────────────────────────────────


class _FakeScout:
    """정찰기 대신 정해진 번호를 답한다. 실제 모델을 안 띄운다."""

    def __init__(self, start: int, end: int) -> None:
        self.payload = {"start_line": start, "end_line": end}
        self.calls = 0

    def post(self, url, json=None):  # noqa: A002 — httpx 흉내
        import json as _json

        self.calls += 1
        body = _json.dumps(self.payload)
        return _Response({"message": {"content": body}})

    def close(self) -> None:
        pass


class _Response:
    def __init__(self, data): self._data = data
    def raise_for_status(self): return None
    def json(self): return self._data


def _config() -> JarvisConfig:
    return JarvisConfig(code_scout_enabled=True)


def test_맞게_짚으면_원문을_돌려준다():
    reset_breaker(); drain_calls()
    got = find_anchor(FILE, "def alpha(value):\n  total\n  return total",
                      config=_config(), client=_FakeScout(3, 5))
    assert got and got in FILE and FILE.count(got) == 1
    rows = drain_calls()
    assert rows[0]["accepted"] == 1


def test_엉뚱하게_짚으면_버린다():
    """★ 이 파일에서 제일 중요한 검사. 라이브가 잡아 준 진짜 고장이다.

    처음 이 검사는 이렇게 물렁했다:

        assert got == "" or got in FILE      ← 통과해 버린다

    「파일에 있나」만 보면 정찰기가 **아무 함수나 짚어도 통과한다.** 라이브에서
    없는 함수(`gamma`)를 고치라고 했더니 정찰기가 `alpha` 를 짚었고, 그 조각은
    파일에 진짜로 있으니 통과해서 **alpha 가 지워졌다.** 못 고치는 것보다 훨씬
    나쁘다 — 조용히 딴 곳을 고친 것이다.
    """
    reset_breaker(); drain_calls()
    # 7~9 는 beta 다. alpha 를 찾는데 beta 를 짚었으면 **버려야 한다.**
    got = find_anchor(FILE, "def alpha(value):\n    total = value + 1\n    return total",
                      config=_config(), client=_FakeScout(7, 9))
    assert got == "", "찾던 것이 아닌데 통과했다 — 딴 곳을 고치게 된다"
    assert drain_calls()[0]["rejected"] == 1


def test_없는_것을_고치라고_하면_아무_데도_안_짚는다():
    """라이브에서 실제로 난 그 판. `gamma` 는 파일에 없다."""
    reset_breaker(); drain_calls()
    got = find_anchor(FILE, "def gamma(value):\n    return value * 3",
                      config=_config(), client=_FakeScout(3, 5))
    assert got == "", "없는 함수를 고치랬는데 다른 함수를 내줬다"


@pytest.mark.parametrize(
    "wanted,span,expected",
    [
        # 정상 — 이름이 그대로 있다
        ("def alpha(value):\n  total = value + 1\n  return total",
         "def alpha(value):\n    total = value + 1\n    return total", True),
        ("def alpha(value):\n    total = value + 1",
         "def alpha(value):\n    total = value + 1\n    return total", True),
        # 오짚음 — 이름이 통째로 빠진다
        ("def gamma(value):\n    return value * 3",
         "def alpha(value):\n    total = value + 1\n    return total", False),
        ("def alpha(value):\n    total = value + 1\n    return total",
         "def beta(value):\n    total = value + 2\n    return total", False),
        ("import json\nx = 1",
         "def alpha(value):\n    total = value + 1\n    return total", False),
    ],
)
def test_낱말_포함률이_맞는지_가른다(wanted, span, expected):
    """★ 유사도로는 못 가른다 — 재 보고 고른 신호다.

    difflib 로 재면 **오짚음(alpha↔beta) 0.905 가 정상(줄 일부만) 0.843 보다
    높다.** 문턱을 어디 둬도 안 갈린다. 낱말 포함률은 갈린다 — 이름이 다르면
    그 낱말이 통째로 빠지기 때문이다(정상 최저 0.875 · 오짚음 최고 0.750).
    """
    from alture_jarvis.grounding_scout import _ANCHOR_TOKEN_COVERAGE, _token_coverage

    assert (_token_coverage(wanted, span) >= _ANCHOR_TOKEN_COVERAGE) is expected


def test_해당_없음으로_답하면_아무것도_안_한다():
    reset_breaker(); drain_calls()
    assert find_anchor(FILE, "def gamma():", config=_config(), client=_FakeScout(0, 0)) == ""
    assert drain_calls()[0]["rejected"] == 1


def test_꺼져_있으면_부르지도_않는다():
    reset_breaker(); drain_calls()
    scout = _FakeScout(3, 5)
    assert find_anchor(FILE, "def alpha", config=JarvisConfig(code_scout_enabled=False), client=scout) == ""
    assert scout.calls == 0, "꺼져 있는데 불렀다 — 시간을 그냥 버린다"
    assert drain_calls()[0]["outcome"] == "disabled"


# ─────────────────────────────────────────────────────────────────────────────
# 성적표 — 늘리기 전에 재는 자부터
# ─────────────────────────────────────────────────────────────────────────────


def test_안_불렀다가_여러_뜻이다():
    """★ 빈 값 하나가 두 사실을 뜻하면 조용히 고장난다.

    「정찰기 0 번」이 꺼져 있어서인지, 죽어서인지, 물을 게 없어서인지 갈려야 한다.
    """
    drain_calls()
    record_call("grounding", outcome="disabled")
    record_call("grounding", outcome="breaker")
    record_call("edit_anchor", asked=1, accepted=1, took_ms=1800)
    summary = summarize_calls(drain_calls())
    assert summary["calls"] == 3
    assert summary["ran"] == 1
    assert summary["outcomes"] == {"breaker": 1, "disabled": 1, "ok": 1}
    assert summary["purposes"] == {"edit_anchor": 1, "grounding": 2}


def test_버린_개수를_따로_센다():
    """이 숫자가 크면 정찰기가 지어내고 있다는 뜻이다 — 성적표에서만 보인다."""
    drain_calls()
    record_call("grounding", asked=5, accepted=1, rejected=4, took_ms=2000)
    assert summarize_calls(drain_calls())["rejected"] == 4


def test_꺼내면_비워진다():
    """판마다 비운다. 안 비우면 다음 판 성적에 앞 판이 섞인다."""
    drain_calls()
    record_call("grounding", asked=1)
    assert len(drain_calls()) == 1
    assert drain_calls() == []


def test_아무것도_없으면_빈_성적표():
    """도구를 안 쓴 판에 빈 표를 달지 않는다 — 분모가 지저분해진다."""
    assert summarize_calls([]) == {}
