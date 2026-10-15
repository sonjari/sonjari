"""버릴 초안은 **화면에 뜬 적조차 없어야 한다.**

★ 2026-08-06 사용자님 지적: "답변을 하고 이제 또 에이전트가 돌아서 또 답변하고".
그때는 버리기로 정한 순간에 `agent_answer_reset` 을 보내는 것으로 고쳤다.

★ 2026-08-10 같은 지적이 다시 왔다: "답변을 하고 그다음에 작업을 하니까 짱나."
반쪽이었던 것이다 — **지우는 시점**이 문제였다. 젬마는 도구 호출을 메시지 끝에
붙이므로, 버릴지 판단하려면 그 글이 이미 다 흘러나온 뒤다. 그래서 실제 순서가

    답이 다 타이핑됨 → 사라짐 → 그제서야 브라우저가 뜸 → 전혀 다른 답

이었다. 앞뒤가 바뀐 것처럼 보인 게 아니라 바뀌어 있었다.

더 빨리 지울 방법은 없다(끝까지 안 보면 도구를 부를지 모른다). 그래서 **애초에
내보내지 않는다**(`_held_stream_callback`). 진행 표시는 그대로 나가고, 쥐고 있던
글은 최종 답으로 확정될 때만 한 번에 풀린다.

아래 시험은 그 규칙 하나를 지킨다: **확정되기 전에는 화면에 글자가 한 자도 안 간다.**
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig


def _runtime(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
        camera_control_enabled=False,
        google_enabled=False,
        naver_blog_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


class _StreamingModel:
    """판단하면서 글을 흘린 뒤 그 글을 message 로 돌려주는 모델."""

    def __init__(self, content: str, tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []

    def chat_message_stream(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        del prompt
        on_chunk = kwargs.get("on_chunk")
        if on_chunk:
            for piece in (self.content[:6], self.content[6:]):
                if piece:
                    on_chunk({"content": piece})
        return {"content": self.content, "tool_calls": self.tool_calls}


def _events(runtime) -> list[str]:
    return [event.to_dict()["event"] for event in runtime.events.get_since(0, 200)]


def test_a_promise_never_reaches_the_screen(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.ollama = _StreamingModel("지금 바로 조사하겠습니다. 잠시만 기다려 주십시오.")

    # 조사·검색 같은 말이 들어가면 모델을 부르기 전에 에이전트로 가 버려서
    # 스트리밍 자체가 안 일어난다. 여기서 보려는 건 "흘렸다가 버리는" 옛 경로다.
    route, answer, _ = runtime._general_route("메일 초안 하나 써줘", "s1", job_id="job-1")

    assert route == "agent" and answer == ""
    assert _events(runtime).count("agent_answer_delta") == 0, "예고가 화면에 갔다"
    assert _events(runtime).count("agent_answer_reset") == 0, "뜬 적이 없으면 지울 것도 없다"


def test_a_real_answer_is_not_cleared(tmp_path: Path) -> None:
    """지우는 것이 공짜가 아니다 — 멀쩡한 답까지 지우면 화면이 빈다."""
    runtime = _runtime(tmp_path)
    runtime.ollama = _StreamingModel("1 더하기 1은 2입니다.")

    route, answer, _ = runtime._general_route("1+1은?", "s1", job_id="job-1")

    assert route == "answer" and "2입니다" in answer
    events = _events(runtime)
    assert events.count("agent_answer_reset") == 1
    assert events.count("agent_answer_delta") >= 1


def test_a_thank_you_does_not_resume_an_unfinished_browser_mission(tmp_path: Path) -> None:
    """현재 말이 감사로 완결됐으면 직전의 미완료 임무보다 우선한다.

    라이브 사고는 바로 이 모양이었다: 공고를 더 찾겠다는 긴 답 뒤의
    ``어어 고맙다``가 21걸음·580초 브라우저 작업이 됐다.
    """
    runtime = _runtime(tmp_path)
    runtime.memory.add_exchange(
        "s1",
        "사람인 공고 다섯 개 찾아줘",
        "두 개를 확인했습니다. 나머지 세 개는 이어서 찾아보겠습니다.",
    )

    class _MustNotRun:
        def chat_message_stream(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError(f"감사 한마디에 라우터 모델을 부르면 안 된다: {prompt} {kwargs}")

    runtime.ollama = _MustNotRun()
    route, answer, _ = runtime._general_route("어어 고맙다", "s1", job_id="job-1")

    assert route == "answer"
    assert "별말씀" in answer
    selected = [
        event.to_dict()["payload"]
        for event in runtime.events.get_since(0, 100)
        if event.to_dict()["event"] == "agent_route_selected"
    ]
    assert selected[-1]["reason"] == "standalone_social_ack"


def test_common_thank_you_spellings_take_the_same_cheap_route(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    class _MustNotRun:
        def chat_message_stream(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError(f"감사 표현에 모델을 부르면 안 된다: {prompt} {kwargs}")

    runtime.ollama = _MustNotRun()
    for prompt in ("고마워", "고마워요!", "감사합니다", "오케이, 고맙습니다"):
        route, answer, _ = runtime._general_route(prompt, "s1", job_id="job-1")
        assert route == "answer" and "별말씀" in answer, prompt


def test_thanks_plus_a_new_action_is_not_swallowed(tmp_path: Path) -> None:
    """감사 뒤에 실제 요청이 붙으면 평소 라우터가 판단해야 한다."""
    runtime = _runtime(tmp_path)
    runtime.ollama = _StreamingModel(
        "",
        tool_calls=[{"function": {"name": "use_browser", "arguments": {}}}],
    )

    route, _answer, _ = runtime._general_route(
        "고마워, 그럼 남은 공고도 찾아줘", "s1", job_id="job-1"
    )

    assert route == "agent"


def test_a_tool_handoff_shows_nothing_either(tmp_path: Path) -> None:
    """도구를 부르기 전에 몇 글자 흘리는 모델이 있다. 그 글자도 답이 아니다."""
    runtime = _runtime(tmp_path)
    runtime.ollama = _StreamingModel(
        "브라우저를 열어",
        tool_calls=[{"function": {"name": "use_browser", "arguments": {}}}],
    )

    route, _answer, _ = runtime._general_route("사이트 하나 열어줘", "s1", job_id="job-1")

    assert route == "agent"
    assert _events(runtime).count("agent_answer_delta") == 0
    assert _events(runtime).count("agent_answer_reset") == 0


def test_nothing_streamed_means_nothing_to_clear(tmp_path: Path) -> None:
    """빈 reset 은 화면에 아무 의미가 없고 로그만 지저분해진다."""
    runtime = _runtime(tmp_path)
    runtime.ollama = _StreamingModel("", tool_calls=[{"function": {"name": "use_browser", "arguments": {}}}])

    runtime._general_route("사이트 열어줘", "s1", job_id="job-1")

    assert _events(runtime).count("agent_answer_reset") == 0


def test_progress_still_shows_while_it_holds(tmp_path: Path) -> None:
    """조용한 것과 엉뚱한 답이 떠 있는 것은 다르다.

    글을 안 내보내는 대신 **생각 중이라는 표시는 계속 나가야 한다** — 안 그러면
    도구를 타는 동안 화면이 죽은 것처럼 보인다. 고치면서 이걸 같이 껐다가는
    "답이 두 번"을 "아무 반응 없음"으로 바꾸는 것뿐이다.
    """

    class _ThinkingModel(_StreamingModel):
        def chat_message_stream(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            on_chunk = kwargs.get("on_chunk")
            if on_chunk:
                on_chunk({"thinking": "무엇을 부를지 고르는 중"})
                on_chunk({"content": self.content})
            return {"content": self.content, "tool_calls": self.tool_calls}

    runtime = _runtime(tmp_path)
    runtime.ollama = _ThinkingModel(
        "브라우저를 열어",
        tool_calls=[{"function": {"name": "use_browser", "arguments": {}}}],
    )

    runtime._general_route("사이트 하나 열어줘", "s1", job_id="job-1")

    events = _events(runtime)
    assert events.count("agent_thinking") >= 1, "쥐고 있는 동안 화면이 죽어 보인다"
    assert events.count("agent_answer_delta") == 0


def test_the_held_answer_is_painted_not_dumped(tmp_path: Path) -> None:
    """★ 통째로 한 번에 보내는 것이 그 자체로 버그였다(2026-08-10 사용자님 지적).

    글이 스르륵 나오지 않고 한 덩어리로 튀어나오고, **화면이 따라 내려가는 것도
    같이 죽는다** — 따라가기는 delta 가 올 때마다 도는 것이라 delta 가 하나면
    한 번만 돈다. 순서를 고치면서 흐르는 느낌을 죽이면 안 된다.

    글은 이미 다 만들어져 있으니 다시 만들지 않는다. 칠하기만 나눈다.
    """
    runtime = _runtime(tmp_path)
    answer = "안녕하세요. " * 40
    runtime.ollama = _StreamingModel(answer)

    route, _answer, _ = runtime._general_route("인사 좀 길게 해줘", "s1", job_id="job-1")

    assert route == "answer"
    deltas = [
        event.to_dict()["payload"]["delta"]
        for event in runtime.events.get_since(0, 400)
        if event.to_dict()["event"] == "agent_answer_delta"
    ]
    assert len(deltas) > 1, "한 덩어리로 나가면 스르륵도 따라가기도 죽는다"
    assert "".join(deltas) == answer, "나눠 보내다 글자를 흘리면 답이 깨진다"


def test_painting_a_long_answer_does_not_drag_on(tmp_path: Path) -> None:
    """칠하는 시간은 **글자 수에 비례해 늘어나지 않는다.**

    ★ 2026-08-23. 예전에는 "3초 안"이라는 **값**을 지켰다. 그런데 그 값의 뿌리가
    `PAINT_MS = 700`(답 전체를 0.7초에 칠함)이었고, 사용자님이 그걸 두고 "읽기 전에
    지나간다"고 하셨다. 긴 답일수록 한 칸에 실리는 글자가 늘어 뭉텅뭉텅 튀어나왔다
    (1,400자면 칸당 50자).

    그래서 총 시간이 아니라 **글자 속도**로 바꿨다(초당 90자, 상한 6초). 값은
    바뀌었지만 **지키려던 것은 그대로다** — 글이 길어져도 칠하기가 하염없이
    늘어지지 않는 것. 그래서 이 검사도 값이 아니라 그 불변식을 본다.
    """
    import time as _time

    def _paint_ms(chars: int) -> float:
        runtime = _runtime(tmp_path)
        runtime.ollama = _StreamingModel("가" * chars)
        started = _time.monotonic()
        runtime._general_route("긴 글 하나 써줘", "s1", job_id="job-1")
        return (_time.monotonic() - started) * 1000

    short = _paint_ms(6_000)
    long = _paint_ms(24_000)

    # 글자가 네 배가 돼도 시간은 안 는다 — 상한에 묶여 있기 때문이다.
    assert long < short * 1.5, f"6천자 {short:.0f}ms → 2만4천자 {long:.0f}ms (비례해 늘어난다)"
    # 그래도 하염없이 늘어지지는 않는다.
    assert long < 9_000, f"2만4천자를 칠하는 데 {long:.0f}ms 썼다"
