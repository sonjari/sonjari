"""사고는 **막힌 자리**에서만 쓴다.

★ 2026-09-03 실측. 코워크 판당 사고 **11,712자**, 답 **1,308자** — 답 1글자당
사고 9글자다. 100토큰/초로 치면 판 133초 중 **78초가 사고**다.

느린 원인은 프리필도 도구도 아니었다. 프리필은 204,883토큰을 15초에 끝낸다
(프리픽스 캐시가 이미 잘 듣는다). **생각하는 시간이 절반 이상**이었다.

그런데 걸음의 58%가 `browser_open_result` + `browser_extract` 짝이다 — 열고 읽는
기계적인 동작이다. 도구 결과가 잘 나온 직후에 8초를 더 생각할 이유가 없다.

## ★ 통제 실험 결과 — **가설이 틀렸다** (2026-09-03 저녁)

같은 빌드에서 정책만 바꿔 같은 프롬프트 4개를 두 번 돌렸다.

    시간   A(always) 244초  →  B(adaptive) 249초   **+2%**
    걸음   A  29           →  B  31              **+7%**
    사고   A  12,363자     →  B  5,833자          -53%
    답     A  1,840자      →  B  1,525자          -17%
    품질   동일 — 대조 전부 충족 · 읽음 10 · 열고안읽음 0

**사고를 절반 줄였는데 시간이 안 줄었다.** 오히려 걸음이 늘었다 — 생각을 안 하니
한 걸음 더 헤맨 것으로 보인다.

추정이 왜 틀렸나: 「사고가 판 시간의 절반」은 **전체 판의 중앙값(11,712자)**에서
나온 숫자인데, 실험한 판 넷은 사고가 3,091자짜리 쉬운 판이었다. **다른 모집단을
비교한 것이다** — 이 저장소가 분모에서 여러 번 당한 자리와 같다.

그래서 기본은 `always` 그대로 둔다. 이 코드는 지우지 않는다 — 다음 사람이 같은
가설을 다시 세우지 않도록 **결과를 들고 있는 자리**로 남긴다. 진짜 지렛대는
걸음 수였다(`test_opening_leads_straight_to_reading.py`).
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import _should_think
from alture_jarvis.config import JarvisConfig


def _config(policy: str = "always", *, enabled: bool = True) -> JarvisConfig:
    root = Path(".")
    return JarvisConfig(
        runtime_root=root,
        data_dir=root / "d",
        output_dir=root / "o",
        documents_dir=root / "docs",
        agent_thinking_enabled=enabled,
        agent_thinking_policy=policy,
    )


def _step(tool: str, ok: bool = True) -> dict:
    return {"tool": tool, "ok": ok}


def test_the_default_still_thinks_every_step() -> None:
    """기본을 바꾸지 않는다 — 아직 통제 실험을 안 했다."""
    config = _config()
    assert _should_think(config, [])
    assert _should_think(config, [_step("browser_extract")])


def test_adaptive_thinks_on_the_first_move() -> None:
    """아직 아무것도 안 정했다. 여기서는 생각해야 한다."""
    assert _should_think(_config("adaptive"), []) is True


def test_adaptive_does_not_think_while_chaining_tools() -> None:
    """★ 여기가 78초의 대부분이다. 열고 읽고 다음 것 열고 — 도구 결과가 다음 수를 정한다."""
    config = _config("adaptive")
    chain = [_step("browser_site_search"), _step("browser_open_result")]

    assert _should_think(config, chain) is False
    assert _should_think(config, chain + [_step("browser_extract")]) is False


def test_adaptive_thinks_again_when_something_failed() -> None:
    """막혔으면 따져야 새 수가 나온다."""
    config = _config("adaptive")
    stuck = [_step("browser_open_result"), _step("browser_click", ok=False)]

    assert _should_think(config, stuck) is True


def test_adaptive_thinks_when_the_same_hand_repeats() -> None:
    """같은 손을 또 뻗고 있으면 멈춰서 생각해야 한다."""
    config = _config("adaptive")
    looping = [_step("browser_snapshot"), _step("browser_snapshot")]

    assert _should_think(config, looping) is True


def test_off_means_off() -> None:
    assert _should_think(_config("off"), []) is False
    assert _should_think(_config("always", enabled=False), []) is False


def test_artifact_steps_never_think() -> None:
    """예전부터 껐던 자리 — 산출물 전환은 추론보다 구조화된 인자가 필요하다."""
    for policy in ("always", "adaptive"):
        assert _should_think(_config(policy), [], artifact_focus=True) is False


def test_the_loop_actually_asks_the_policy() -> None:
    """배선이 빠지면 정책이 죽은 코드가 된다."""
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    assert "think=_should_think(" in source
    assert source.count("think=self.config.agent_thinking_enabled and not artifact_focus") == 0
