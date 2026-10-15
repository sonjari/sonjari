"""열었으면 **같은 걸음에서** 읽는다.

★ 2026-09-03 실측 (코워크 90판). 걸음의 58%가 이 짝이었다.

    browser_open_result   355회  30.6%
    browser_extract       317회  27.3%

열기 355번 중 317번(89%)이 추출로 이어진다. 그런데 그 사이에 모델을 한 번 더
부른다 — **그 턴이 정하는 것은 아무것도 없다.** 열었으면 읽는 것 말고 할 일이 없다.

붙이면 그 짝마다 **모델 호출이 하나씩 사라진다**(과거 판에서 308쌍). 덤으로
「열어 놓고 본문을 안 읽은」 32회가 구조적으로 사라진다 — Step C 원장이 세던
바로 그 수치다.

## 통제 실험 — **켰다** (2026-09-03 저녁)

같은 빌드에서 켬/끔만 바꿔 같은 프롬프트 4개를 두 번 돌렸다.

    시간   끔 371초  ->  켬 285초   **-23%**
    걸음      34     ->     32      -6%
    사고   18,187자  ->  15,036자   -17%
    품질   동일 - 대조 전부 충족 · 읽음 10 · 열고안읽음 0

브라우저 판 셋 개별로도 -22% · -25% · -25% 로 **방향과 크기가 일관**됐다.
같은 날 사고 정책 실험이 +2% 로 기각된 것과 대조된다 - 그쪽은 비율 추정이었고
이쪽은 **실제 짝 308쌍을 센 것**이었다.

⚠ 줄어드는 것은 걸음이 아니라 **모델 호출**이다. 추출은 그대로 걸음으로 남는다.
  처음에 「걸음 12 -> 7」이라고 적었던 것은 틀렸다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import _EXTRACT_TOOL, _OPEN_RESULT_TOOL, _fused_read_call

TOOLS = {_OPEN_RESULT_TOOL, _EXTRACT_TOOL}


def _call(name: str) -> dict:
    return {"function": {"name": name, "arguments": {}}}


def _name_of(call: dict) -> str:
    return str((call.get("function") or {}).get("name") or "")


def _ask(name, observation, calls, current, *, enabled=True, available=TOOLS):
    return _fused_read_call(
        name, observation, calls, current,
        enabled=enabled, available=available, next_name=_name_of,
    )


def test_a_successful_open_pulls_the_read_in() -> None:
    """이 한 줄이 판 시간을 23% 줄인다 — 사이의 모델 턴이 사라진다."""
    opened = _call(_OPEN_RESULT_TOOL)

    assert _ask(_OPEN_RESULT_TOOL, {"ok": True}, [opened], opened) is True


def test_a_failed_open_reads_nothing() -> None:
    """★ 실패한 열기 뒤에 읽으면 **빈 화면을 읽는다.** 그건 근거가 아니다."""
    opened = _call(_OPEN_RESULT_TOOL)

    assert _ask(_OPEN_RESULT_TOOL, {"ok": False}, [opened], opened) is False


def test_it_does_not_double_up_when_the_model_already_asked() -> None:
    """모델이 이미 추출을 이어 붙였으면 또 붙이지 않는다 — 같은 곳을 두 번 읽는다."""
    opened, extract = _call(_OPEN_RESULT_TOOL), _call(_EXTRACT_TOOL)

    assert _ask(_OPEN_RESULT_TOOL, {"ok": True}, [opened, extract], opened) is False


def test_a_later_extract_does_not_count_as_already() -> None:
    """다음 것이 아니라 **바로 다음**만 본다. 사이에 다른 손이 끼면 붙여야 한다."""
    opened, other, extract = _call(_OPEN_RESULT_TOOL), _call("browser_snapshot"), _call(_EXTRACT_TOOL)

    assert _ask(_OPEN_RESULT_TOOL, {"ok": True}, [opened, other, extract], opened) is True


def test_other_tools_are_left_alone() -> None:
    other = _call("browser_snapshot")

    assert _ask("browser_snapshot", {"ok": True}, [other], other) is False


def test_it_stays_off_until_switched_on() -> None:
    opened = _call(_OPEN_RESULT_TOOL)

    assert _ask(_OPEN_RESULT_TOOL, {"ok": True}, [opened], opened, enabled=False) is False


def test_it_does_nothing_when_the_reading_hand_is_missing() -> None:
    """추출 도구가 이 판의 프로필에 없으면 부를 수 없다."""
    opened = _call(_OPEN_RESULT_TOOL)

    assert _ask(_OPEN_RESULT_TOOL, {"ok": True}, [opened], opened, available={_OPEN_RESULT_TOOL}) is False


def test_appending_while_iterating_actually_runs_the_extra_call() -> None:
    """★ 루프가 **도는 중에 붙인 호출**을 실제로 실행하는가.

    파이썬 리스트는 순회 중 append 를 이어서 돈다. 이 성질에 기대고 있으므로
    여기서 못 박아 둔다 — 나중에 `calls` 를 튜플이나 사본으로 바꾸면 융합이
    조용히 죽는다.
    """
    calls = [_call(_OPEN_RESULT_TOOL)]
    ran: list[str] = []
    for call in calls:
        name = _name_of(call)
        ran.append(name)
        if _ask(name, {"ok": True}, calls, call):
            calls.append(_call(_EXTRACT_TOOL))

    assert ran == [_OPEN_RESULT_TOOL, _EXTRACT_TOOL]


def test_it_does_not_run_away() -> None:
    """추출 뒤에 또 붙이지 않는다 — 붙였다 또 붙이면 판이 끝나지 않는다."""
    calls = [_call(_OPEN_RESULT_TOOL)]
    ran: list[str] = []
    for call in calls:
        if len(ran) > 6:
            break
        name = _name_of(call)
        ran.append(name)
        if _ask(name, {"ok": True}, calls, call):
            calls.append(_call(_EXTRACT_TOOL))

    assert ran == [_OPEN_RESULT_TOOL, _EXTRACT_TOOL], ran


def test_it_is_on_because_it_was_measured() -> None:
    """재고 켰다 - 시간 -23%, 품질 동일.

    사고 정책은 재고 **안 켰다**(+2%). 둘을 나란히 두는 이유는, 다음 사람이
    「둘 다 최적화니까 둘 다 켜자」로 뭉뚱그리지 않게 하기 위해서다.
    """
    from alture_jarvis.config import JarvisConfig  # noqa: PLC0415

    root = Path(".")
    config = JarvisConfig(
        runtime_root=root, data_dir=root / "d", output_dir=root / "o",
        documents_dir=root / "docs",
    )
    assert config.agent_fuse_open_and_read is True
    assert config.agent_thinking_policy == "always"


def test_the_fused_read_takes_no_arguments() -> None:
    """★ `browser_extract` 는 인자가 없다 — 지금 화면의 본문을 읽을 뿐이다.

    인자를 지어 넣으면 되풀이 차단의 지문이 갈려 세 번째부터 판이 통째로 막힌다
    (2026-08 실측: 133판 재현 42→9).
    """
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    assert '{"function": {"name": _EXTRACT_TOOL, "arguments": {}}}' in source
    assert '"agent_fused_read"' in source


def test_a_fused_read_does_not_steal_the_model_s_turn() -> None:
    """★ 도와주려다 판을 일찍 끊으면 안 된다.

    걸음 예산은 「모델이 몇 번 결정하나」를 재는 자다. 융합한 읽기는 **모델의
    결정이 아니므로** 예산도 같이 올려야 한다. 안 올렸더니 실제로
    `test_forced_read.py` 가 `agent_continuation_required` 로 깨졌다 —
    붙여 준 만큼 모델의 차례를 빼앗은 것이다.
    """
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    fused = source.index('{"function": {"name": _EXTRACT_TOOL, "arguments": {}}},')
    nearby = source[fused : fused + 700]
    assert "step_limit += 1" in nearby, "융합한 읽기가 걸음 예산을 잡아먹는다"
