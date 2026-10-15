"""대화·라우터 호출도 **턴마다 바뀌는 것**(시각·스킬 메모)을 시스템 글이 아니라 요청문 앞에 싣는다 (2026-10-07).

모든 요청이 먼저 지나는 라우터 호출과 바로 답하는 판은 시스템 글의 끝에 시각 줄이 있었다. 운영 모델은 서버가 캐시를
체크포인트 자리(마지막 사용자 메시지가 시작하는 곳)로만 되돌려서, 분이 바뀔 때마다 시스템 글과 도구를 통째로 다시 읽었다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis import runtime as runtime_module
from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.transcript import JOB_CONTEXT_CLOSE, JOB_CONTEXT_OPEN


def _runtime(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


def test_the_system_message_is_the_same_two_minutes_later(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(runtime_module, "now_line_ko", lambda: "현재 한국 시각 (KST)\n- 시각: 18:32")
    before = runtime._system_prompt("지침 하나", now=False)
    monkeypatch.setattr(runtime_module, "now_line_ko", lambda: "현재 한국 시각 (KST)\n- 시각: 18:34")
    after = runtime._system_prompt("지침 하나", now=False)

    assert before == after and "현재 한국 시각" not in before
    assert runtime._system_prompt("지침 하나").endswith("- 시각: 18:34"), "곁가지 호출은 예전처럼 시각을 시스템 글 끝에 둔다"


def test_the_request_carries_this_turns_note_and_time_in_front(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module, "now_line_ko", lambda: "현재 한국 시각 (KST)\n- 시각: 18:32")
    sent: list[tuple[str, dict]] = []

    def chat(prompt: str, **kwargs):
        sent.append((prompt, kwargs))
        return {"role": "assistant", "content": "답"}

    wrapped = JarvisRuntime._with_turn_context(chat, "참고 플레이북: 표로 정리")

    assert wrapped("오늘 무슨 요일이야", system="고정 글", tools=[]) == {"role": "assistant", "content": "답"}
    prompt, kwargs = sent[0]
    assert prompt.startswith(JOB_CONTEXT_OPEN + "\n참고 플레이북: 표로 정리\n\n현재 한국 시각")
    assert prompt.endswith(JOB_CONTEXT_CLOSE + "\n\n오늘 무슨 요일이야")
    assert kwargs == {"system": "고정 글", "tools": []}


def test_a_turn_without_a_skill_note_still_carries_the_time(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module, "now_line_ko", lambda: "현재 한국 시각 (KST)\n- 시각: 18:32")
    sent: list[str] = []
    wrapped = JarvisRuntime._with_turn_context(lambda prompt, **kwargs: sent.append(prompt), "")

    wrapped("안녕")

    assert sent[0] == f"{JOB_CONTEXT_OPEN}\n현재 한국 시각 (KST)\n- 시각: 18:32\n{JOB_CONTEXT_CLOSE}\n\n안녕"


def test_both_answer_paths_use_it() -> None:
    """바로 답하는 판과 라우터 — 둘 다 시각을 시스템 글에서 빼고 요청문 쪽으로 보낸다."""
    for name in ("_contextual_answer",):
        source = inspect.getsource(getattr(JarvisRuntime, name))
        assert "self._with_turn_context(chat, self._skill_instruction(prompt, job_id=job_id))" in source
        assert "now=False" in source
    whole = inspect.getsource(JarvisRuntime)
    assert whole.count("chat = self._with_turn_context(chat, self._skill_instruction(prompt, job_id=job_id))") == 2
    assert whole.count("self._system_prompt(*route_instructions, now=False)") == 1
