"""아무도 준 적 없는 배수 · 퍼센트를 단정한 답은 **그대로 내보내지 않는다** (2026-10-18 대표 디스코드 실사용).

대표가 폰으로 「손자리가 일자리를 줄이지 않을까」를 묻자 도구 0걸음으로 「생산성 10배 · 3년 뒤 인력 50% 감축 · 2~3배 증가」를
단정했다. 금액 검사(원 · 포인트)도 라우터의 숫자 검사(세 자리 이상)도 이 꼴을 안 본다. 지우게 하지 않고 「상식이면 상식, 예측이면
짐작」으로 밝히게 한다 — 「계약금은 보통 10%」 같은 상식도 섞이기 때문이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.plan_nudges import _invented_ratios

# 표본은 그 판 답의 모양만 따왔다(회사 · 사람 이름은 뺐다).
DRAFT = (
    "AI가 인력을 줄이는 게 아니라, AI를 못 쓰는 조직이 인력을 줄입니다.\n\n"
    "| 시점 | 대체 조직 | 증강 조직 |\n|---|---|---|\n| 1년 | 시키는 중 | 이미 쓰는 중 |\n"
    "| 3년 | 인력 50% 감축 | 인력 2~3배 증가 |\n\n도구로 쓰면 생산성 10배입니다."
)
ASKED = "우리가 만든 도구가 사람 일자리를 줄이지 않을까 고민이 돼"


def _runtime(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


class _Model:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat_message(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return {"content": self.content, "tool_calls": []}

    chat_message_stream = chat_message


def test_the_draft_has_ratios_nobody_gave() -> None:
    assert _invented_ratios(DRAFT, ASKED) == ["50%", "2~3배", "10배"]


def test_ratios_the_person_gave_are_not_invented() -> None:
    """역방향 — 질문에 있던 수치를 되풀이한 것은 지어낸 것이 아니다."""
    given = "인력이 50% 줄고 2~3배 늘고 생산성이 10배라는 기사를 봤는데 정리해 줘"
    assert _invented_ratios(DRAFT, given) == []


def test_one_common_figure_alone_does_not_count_as_two() -> None:
    assert len(_invented_ratios("전세 계약금은 보통 10% 를 냅니다.", "계약금 얼마 내야 하나")) == 1


def test_the_router_does_not_send_such_a_draft_out(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _Model(DRAFT)
    route, answer, observation = runtime._general_route(ASKED, "s1", job_id="job-ratios")
    assert route == "agent" and answer == ""
    assert (observation or {}).get("route_reason") == "invented_ratios"


def test_a_plain_opinion_without_figures_is_still_answered_directly(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    plain = "도구를 쓰는 사람이 일을 더 잘하게 되는 쪽이 많습니다. 다만 어떤 일은 실제로 줄어들 수 있어 걱정은 자연스럽습니다."
    runtime.ollama = _Model(plain)
    route, answer, _ = runtime._general_route(ASKED, "s1", job_id="job-plain")
    assert route == "answer" and answer == plain


def test_the_loop_asks_for_one_rewrite_only_when_no_tool_was_used() -> None:
    import inspect

    from alture_jarvis import agent

    source = inspect.getsource(agent)
    plan_pushback = source.index('"agent_plan_pushback",')
    start = source.index("invented = [] if steps or ratios_rewritten or not answer else _invented_ratios(")
    kept = source.index("answer = _keep_answer_over_reply(")
    assert plan_pushback < start < kept
    block = source[start:kept]
    assert "ratios_rewritten = True" in block, "한 판에 한 번뿐"
    assert "len(invented) >= 2" in block and "time.monotonic() < deadline" in block
    assert 'reply_language(asked) == "en"' in block, "영어 사용자에게는 영어로 말한다"
    assert "continue" in block
    assert "ratios_rewritten = False" in source
