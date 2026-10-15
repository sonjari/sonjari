"""도구가 준 숫자를 판 기록에 남긴다 — **게이트를 만들기 전에 잴 수 있게.**

## 왜 (2026-09-06)

자사 데이터 판에서 이런 일이 났다:

    도구가 준 값   명지대·성신여대·숭실대  전부 probability=0.0 · band=위험
    답의 표        75.2%  ·  92.9%  ·  66.9%

전부 지어낸 숫자다. 그리고 그 창작한 값 12 개를 `sandbox_run` 에 넣어
「평균 73.69% · 표준편차 24.72%」까지 계산했다 — 창작에 통계의 옷을 입혔다.

**이 판은 모든 검사를 통과한다.** 근거 대조는 이름만 보고, 원장은 「읽었나」까지만
알고, 정찰기는 부를 일이 안 생긴다. 셋 다 숫자에는 눈이 없다.

## 왜 게이트를 안 만들었나

막으려고 표본을 만들어 봤더니 **잴 수가 없었다.**

    도구 쓴 판 1,002 · 답에 숫자가 있는 판 565
    도구 결과에 없는 숫자가 있는 판 319 (56%)

이 56% 는 못 믿는다. 답의 숫자는 대개 `browser_extract` **본문**에서 오는데
본문은 `agent_trace` 에 안 들어간다(관측 보관소에 있고 그건 메모리라 재기동에
사라진다). 크몽의 「1,500,000원」이 그 예다 — 페이지에 진짜로 있는 값인데 내
검사에는 「없음」으로 보였다.

확증된 사례는 **1 건**이다. n=1 로 게이트를 만드는 것은 이 저장소가 하지 말라고
적어 둔 그것이다(「게이트는 좋은 표본으로 역검증 필수」).

## 그래서 이 파일이 지키는 것

게이트 대신 **재는 재료**를 남긴다. 도구가 **필드로 준 숫자**만 걷으므로 의미가
분명하다 — 본문에서 온 값과 섞이지 않는다. 이것이 판마다 쌓이면 그때
「도구는 0.0 을 줬는데 답은 75.2 를 말했다」를 표본으로 셀 수 있다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.evidence import numbers_in

# 실측한 그 도구 결과.
REAL = {
    "ok": True,
    "target_label": "명지대학교 컴퓨터공학과",
    "probability": 0.0,
    "band": "위험",
    "q50": 858.964,
    "q70": 843.8,
    "metric": "conversion_score",
    "student_value": 2.4,
    "evidence": [{"year": 2024, "metric": "conversion_score", "q70": 1035.9}],
}


def test_도구가_준_숫자를_걷는다():
    found = numbers_in(REAL)
    assert "0" in found, "probability=0.0 이 빠지면 창작을 못 잡는다"
    assert "843.8" in found and "858.964" in found
    assert "2.4" in found
    assert "1035.9" in found, "중첩된 목록 안의 값도 봐야 한다"


def test_답이_지어낸_숫자는_당연히_없다():
    """★ 이 대조가 가능해지는 것이 이 층의 전부다."""
    found = numbers_in(REAL)
    for made_up in ("75.2", "92.9", "66.9", "73.69"):
        assert made_up not in found


@pytest.mark.parametrize(
    "key", ["step", "rank", "index", "took_ms", "element_count", "char_count", "ready_ms"]
)
def test_순번_소요시간은_안_센다(key):
    """답이 주장하는 값이 아니다. 섞으면 대조가 뜻을 잃는다."""
    assert numbers_in({key: 12345}) == set()


def test_참거짓은_숫자가_아니다():
    """파이썬에서 `True` 는 1 이다. 그대로 두면 온 판에 「1」이 낀다."""
    assert numbers_in({"ok": True, "verified": False}) == set()


def test_정수와_소수를_가른다():
    """`1` 과 `1.0` 을 뭉개면 대조가 샌다."""
    found = numbers_in({"a": 1, "b": 1.5})
    assert "1" in found and "1.5" in found


def test_본문_글자는_안_본다():
    """본문에서 온 숫자를 섞으면 「도구가 준 값」이라는 뜻이 사라진다."""
    found = numbers_in({"text": "가격은 1,500,000원입니다", "count_shown": 3})
    assert "1500000" not in found and "1,500,000" not in found


def test_아무리_커도_상한을_지킨다():
    """장부가 커지면 아무도 안 읽는다."""
    from alture_jarvis.evidence import _NUMBERS_MAX

    huge = {"rows": [{"v": float(i) + 0.5} for i in range(5000)]}
    assert len(numbers_in(huge)) <= _NUMBERS_MAX


def test_깊이_상한도_지킨다():
    deep: dict = {"v": 1.5}
    for _ in range(12):
        deep = {"nest": deep}
    assert numbers_in(deep) == set()


def test_빈_것에도_안_죽는다():
    assert numbers_in({}) == set()
    assert numbers_in(None) == set()  # type: ignore[arg-type]


def test_판_기록까지_흘러간다():
    """값을 걷어 놓고 판 기록에 안 넣으면 사후에 셀 수가 없다 —
    `agent_grounding_scout` 이벤트가 SSE 로만 흘러 아무도 못 세던 것과 같다."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"
    agent = (root / "agent.py").read_text(encoding="utf-8")
    runtime = (root / "runtime.py").read_text(encoding="utf-8")
    assert "tool_numbers.update(evidence_numbers_in(evidence))" in agent, "걷는 자리"
    assert "tool_numbers=sorted(tool_numbers)" in agent, "결과에 싣는 자리"
    assert '"tool_numbers": agent_result.tool_numbers' in runtime, "판 기록에 넣는 자리"


def test_걷는_자리가_잘리기_전이다():
    """`_step_evidence` 는 dict 를 통째로 버리고 문자열을 자른다.

    거기 뒤에서 걷으면 중첩된 값(위 `evidence[].q70`)이 통째로 사라진다.
    """
    from pathlib import Path

    agent = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")
    body = agent.split("def _record_observation(")[1].split("\n    def ")[0]
    assert body.index("tool_numbers.update(") < body.index("_step_evidence(evidence)")
