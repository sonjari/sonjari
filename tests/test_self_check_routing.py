"""「네 상태 점검해봐」가 **자기 진단으로 가는가.**

## 왜 (2026-08-21 실측)

`self_check` 를 만들어 등록까지 하고 라이브에서 잘 도는 것까지 확인한 날 밤,
사용자님이 이렇게 물었다:

    "지금 네 상태 점검해보고, 이상한 데 있으면 파고들어서 원인까지 알려줘"

    결과: 걸음 0 · agent_trace 없음
    답  : "지금 카메라 영상이 없어서 확인할 수 없습니다. 사무실 태블릿이
           꺼져 있거나 배터리가 다 됐거나…"

**에이전트 루프에 들어가지도 못했다.** 도구는 멀쩡히 있었는데 **갈래가 없어서
한 번도 후보가 되지 못했고**, 모델이 카메라 얘기를 지어냈다.

이 저장소가 이미 아는 병이다 — **도구는 순서에 없으면 안 쓰인다.**
(같은 구멍으로 눈금이 두 번, 라우팅이 세 번 샜다.)

## 이 파일이 지키는 것

**① 그날 실패한 그 문장이 이제 간다.**
**② 오탐이 안 난다** — 게이트는 좋은 표본으로도 역검증해야 한다(하루 두 번 데었다).
**③ 도구가 없으면 갈래를 안 연다** — 갈래만 만들고 도구를 안 주면 지어낸다.
"""

from __future__ import annotations

import re

import pytest

from alture_jarvis.runtime import _HEALTH_SIGN, _SELF_REFERENCE


def _matches(prompt: str) -> bool:
    """`_requires_self_check` 의 판정 부분만 — 런타임을 통째로 안 띄운다."""
    compact = " ".join(prompt.split())
    return bool(_SELF_REFERENCE.search(compact) and _HEALTH_SIGN.search(compact))


# ── ① 그날 실패한 문장 ──────────────────────────────────────────────────────


def test_the_exact_prompt_that_failed_now_routes() -> None:
    """★ 이 검사가 이 파일의 존재 이유다."""
    assert _matches("지금 네 상태 점검해보고, 이상한 데 있으면 파고들어서 원인까지 알려줘")


@pytest.mark.parametrize(
    "prompt",
    [
        "자비스 너 상태 어때?",
        "너 지금 어디 고장 났어?",
        "시스템 점검 좀 해줘",
        "왜 이렇게 느려? 너 문제 있어?",
        "자비스 자가 진단 해봐",
        "너 지금 멀쩡한거 맞나",
        "스스로 점검해보고 이상 있으면 알려줘",
        "너 어디 막혀 있는지 봐줘",
        "자비스 상태 진단해줘",
        "니 상태 좀 보자",
    ],
)
def test_asking_about_its_own_health_routes(prompt: str) -> None:
    assert _matches(prompt), f"자기 진단으로 안 갔다: {prompt}"


# ── ② 오탐 — 게이트는 좋은 표본으로도 역검증한다 ────────────────────────────


@pytest.mark.parametrize(
    "prompt",
    [
        "나래이 이력서 상태 좀 봐줘",
        "쿠팡에서 무선마우스 상위 3개 알려줘",
        "크몽 공고 상태가 어떤지 확인해줘",
        "이 문서 상태가 좀 이상한데 정리해줘",
        "우리 회사 마스코트 누룽지 사진 좀 찾아줘",
        "3개 이상 직접 열어서 읽어줘",
        "네이버 블로그에 글 하나 써줘",
        "너무 길게 쓰지 말고 요약해줘",
        "다나와 가격 비교표 만들어줘",
        "내일 오후 3시에 일정 하나 잡아줘",
    ],
)
def test_ordinary_requests_do_not_route_to_self_check(prompt: str) -> None:
    assert not _matches(prompt), f"엉뚱하게 자기 진단으로 갔다: {prompt}"


def test_comparing_jarvis_state_management_is_not_a_health_check() -> None:
    prompt = "현재 자비스와 외부 흐름을 장기 맥락·도구 선택·상태 관리 축으로 비교해줘"

    assert not _matches(prompt)


def test_neo_the_word_naver_is_not_a_self_reference() -> None:
    """★ `네` 만 보면 **네이버**가 걸린다."""
    assert not _SELF_REFERENCE.search("네이버에서 검색해줘")


def test_the_word_too_much_is_not_a_self_reference() -> None:
    """★ `너` 만 보면 **너무**가 걸린다."""
    assert not _SELF_REFERENCE.search("너무 느리게 하지 마")


def test_a_bare_count_is_not_a_health_sign() -> None:
    """★ 「이상」을 홀로 두면 **3개 이상**이 걸린다."""
    assert not _HEALTH_SIGN.search("3개 이상 찾아줘")
    assert not _HEALTH_SIGN.search("5개 이상 열어서 읽어")
    # 진짜 신호는 뒤에 오는 말로 묶여 있다.
    assert _HEALTH_SIGN.search("이상 있으면 알려줘")
    assert _HEALTH_SIGN.search("이상한 데 없나")


def test_either_half_alone_is_not_enough() -> None:
    """둘 다 있어야 간다 — 하나만으로 열면 오탐이 쏟아진다."""
    assert _SELF_REFERENCE.search("자비스 블로그 글 써줘")
    assert not _matches("자비스 블로그 글 써줘")

    assert _HEALTH_SIGN.search("이 파일 상태 어때")
    assert not _matches("이 파일 상태 어때")


# ── ③ 도구가 없으면 갈래를 안 연다 ──────────────────────────────────────────


def test_the_route_is_closed_when_the_tools_are_missing() -> None:
    """★ `_requires_inhouse_data` 가 배운 것 그대로 — 갈래만 만들고 도구를 안 주면
    에이전트가 빈손으로 받아 결국 지어낸다.

    런타임을 안 띄우고 그 규칙만 본다: `self_care` 가 없거나 도구가 0개면 False.
    """
    # 산문이 아니라 **행동**을 잰다. 독스트링에 규칙이 적혀 있는지 검사하면
    # 그건 문서를 재는 것이지 코드를 재는 것이 아니다.
    from alture_jarvis.runtime import JarvisRuntime

    class _NoTools:
        names: set[str] = set()

    class _Fake:
        self_care = _NoTools()
        _requires_self_check = JarvisRuntime._requires_self_check

    assert _Fake()._requires_self_check("자비스 너 상태 점검해줘") is False


def test_the_route_opens_when_the_tools_are_there() -> None:
    from alture_jarvis.runtime import JarvisRuntime

    class _HasTools:
        names = {"self_check", "self_heal"}

    class _Fake:
        self_care = _HasTools()
        _requires_self_check = JarvisRuntime._requires_self_check

    assert _Fake()._requires_self_check("자비스 너 상태 점검해줘") is True
    assert _Fake()._requires_self_check("쿠팡에서 마우스 찾아줘") is False


# ── 갈래가 카메라보다 앞에 있는가 ───────────────────────────────────────────


def test_self_check_is_decided_before_the_camera_branch() -> None:
    """★ 순서가 곧 정책이다. 「네 상태 어때」가 카메라 갈래로 흘러가면 태블릿
    얘기를 하게 된다 — 2026-08-21 에 실제로 그랬다."""
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime._general_route)
    self_at = source.find("_requires_self_check")
    camera_at = source.find("_requires_camera_control")
    assert self_at != -1, "자기 진단 갈래가 없다"
    assert camera_at != -1
    assert self_at < camera_at, "자기 진단이 카메라보다 뒤에 있다"


# ── 라우팅만으로는 안 됐다 — 걸음 0 으로 지어냈다 ────────────────────────────
#
# ★ 2026-08-21. 라우팅을 고쳐 에이전트 루프까지 들어왔는데 **걸음 0** 으로 끝났다:
#
#     "논리 엔진 [정상] · 도구 가용성 [정상] · 데이터 무결성 [주의]"
#
# 아무것도 안 보고 지어냈다. 카메라 얘기보다 **나쁘다** — 그럴듯해서 안 믿을
# 이유가 없다. 오늘 같은 자리를 셋째로 만난다(커밋 · 상세 읽기 · 이것).


def test_a_self_check_request_that_saw_nothing_is_pushed() -> None:
    from alture_jarvis.agent import _forced_self_check_call

    pushed = _forced_self_check_call([], asked_for_self_check=True)
    assert pushed == ("self_check", {})


def test_nothing_is_pushed_when_it_was_not_a_self_check_request() -> None:
    """평범한 조사 판에 자기 진단이 끼어들면 걸음만 태운다."""
    from alture_jarvis.agent import _forced_self_check_call

    assert _forced_self_check_call([], asked_for_self_check=False) is None


def test_nothing_is_pushed_once_it_has_already_looked() -> None:
    from alture_jarvis.agent import _forced_self_check_call

    steps = [{"tool": "self_check", "ok": True, "arguments": {}}]
    assert _forced_self_check_call(steps, asked_for_self_check=True) is None


def test_a_failed_check_is_not_retried() -> None:
    """이미 불렀으면 실패했더라도 다시 밀지 않는다 — 같은 실패가 반복될 뿐이다."""
    from alture_jarvis.agent import _forced_self_check_call

    steps = [{"tool": "self_check", "ok": False, "arguments": {}}]
    assert _forced_self_check_call(steps, asked_for_self_check=True) is None


def test_the_pushed_tool_takes_nothing_a_model_could_invent() -> None:
    """★ 강제로 부를 수 있는 근거. `self_check` 는 인자가 **없어도 되는** 도구다."""
    from pathlib import Path

    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.events import EventBus
    from alture_jarvis.self_care import SelfCare

    care = SelfCare(JarvisConfig(runtime_root=Path(".")), EventBus())
    spec = next(
        item["function"] for item in care.ollama_tools if item["function"]["name"] == "self_check"
    )
    assert not (spec["parameters"].get("required") or []), "self_check 에 필수 인자가 생겼다"


def test_the_runtime_hands_the_signal_to_the_agent() -> None:
    """★ 판정을 라우터가 하고 루프가 또 추측하면 둘이 갈린다. 그대로 넘기는가."""
    import inspect

    from alture_jarvis.agent import BrowserAgent
    from alture_jarvis.runtime import JarvisRuntime

    assert "asked_for_self_check" in inspect.signature(BrowserAgent.run).parameters
    source = inspect.getsource(JarvisRuntime)
    assert "asked_for_self_check=asked_for_self_check" in source, "신호를 안 넘긴다"


# ── ★ 게이트웨이 등록과 에이전트 카탈로그는 다른 일이다 ─────────────────────
#
# 2026-08-21. 라우팅을 고치고 강제 호출까지 만들었는데 그 호출이 `unknown_tool`
# 로 죽었다. `self_check` 를 게이트웨이에 등록해 두고 **에이전트 카탈로그에는
# 안 넣었기** 때문이다. 도구는 있었지만 에이전트 눈에는 없었다.
#
# 이 저장소가 같은 구멍으로 네 번째 샌 자리다 — 눈금 분류표 두 번, 라우팅 한 번,
# 그리고 여기. **도구는 순서에 없으면 안 쓰인다.**


def test_every_tool_the_agent_is_forced_to_call_is_in_its_catalogue() -> None:
    """★ 강제로 부르는 도구가 카탈로그에 없으면 그 기능은 통째로 없는 것이다."""
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime)
    catalogue = source[source.find("AgentToolCatalog(") :]
    catalogue = catalogue[: catalogue.find("\n        )")]

    # 코드가 대신 부르는 도구들의 주인이 전부 여기 있어야 한다.
    for owner in ("self.self_care", "self.shell_probe", "self.google", "self.naver_blog"):
        assert owner in catalogue, f"{owner} 가 에이전트 카탈로그에 없다"


def test_the_forced_self_check_tool_belongs_to_a_catalogued_owner() -> None:
    """강제 호출이 가리키는 이름이 실제로 그 주인의 도구인가."""
    from pathlib import Path

    from alture_jarvis.agent import _SELF_CHECK_TOOL
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.events import EventBus
    from alture_jarvis.self_care import SelfCare

    care = SelfCare(JarvisConfig(runtime_root=Path(".")), EventBus())
    assert _SELF_CHECK_TOOL in care.names, "강제로 부르는 이름이 그 도구 목록에 없다"
