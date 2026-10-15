"""끝난 판에 덧붙인 말은 앞 판의 질문을 이어받는다 (2026-10-02 협업 판 6cc1590c → 52017231).

앞 판: 「Claude, ChatGPT, Perplexity, Manus, Genspark 의 공식 가격 페이지에서 … 엑셀로 정리해줘」.
판이 막 끝난 뒤 「2번 기준 취소. 미국 페이지는 한국에서 안 열리니 한국어 가격 페이지 그대로 써…」를 덧붙였다. 화면은 그 말을
새 판으로 보냈고, 새 판의 계획 층은 그 말만 보고 요구 1개를 세웠다 — 예고 한 줄로 끝난 답이 `complete` 가 됐다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.plan import extract
from alture_jarvis.runtime import JarvisRuntime

FIRST = (
    "「Claude, ChatGPT, Perplexity, Manus, Genspark의 공식 가격 페이지에서 개인용 요금제를 모두 찾아, 요금제 이름·월 요금(달러)·"
    "에이전트/브라우저 기능 포함 여부·사용 한도 문구·확인한 주소를 엑셀로 정리해줘. 페이지에 없는 값은 '페이지에 없음'으로 쓰고 추측하지 마.」"
)
NOTE = (
    "2번 기준 취소. 미국 페이지는 한국에서 안 열리니 한국어 가격 페이지 그대로 써. 화면에 보이는 통화 그대로 적고, "
    "'부가세 포함' 같은 표시가 있으면 그 칸에 같이 적어. 환율로 바꾸지 마."
)


class _Events:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        self.sent.append((kind, payload))


class _Store:
    def __init__(self, job: dict[str, Any]) -> None:
        self.job = job

    def get_job(self, _job_id: str) -> dict[str, Any]:
        return self.job


class _Agent:
    def __init__(self, leftover: list[str] | None = None) -> None:
        self.leftover = leftover or []

    def take_leftover_steer(self, _job_id: str) -> list[str]:
        out, self.leftover = self.leftover, []
        return out


def _runtime(job: dict[str, Any], leftover: list[str] | None = None) -> JarvisRuntime:
    runtime = JarvisRuntime.__new__(JarvisRuntime)
    runtime.store = _Store(job)
    runtime.agent = _Agent(leftover)
    runtime.events = _Events()
    return runtime


def _finished() -> dict[str, Any]:
    return {"id": "6cc1590c", "kind": "chat", "status": "completed",
            "payload": {"prompt": FIRST, "session_id": "jarvis-muppho0l"}}


def test_the_note_alone_loses_what_was_asked() -> None:
    kinds_alone = {item.kind for item in extract(NOTE)}
    kinds_joined = {item.kind for item in extract(f"{FIRST} {NOTE}")}
    assert "artifact" not in kinds_alone
    assert "artifact" in kinds_joined, "앞 판 요청을 붙이면 엑셀 산출물 요구가 살아난다"


def test_a_note_to_a_finished_job_is_remembered_for_the_next_job() -> None:
    runtime = _runtime(_finished())
    assert runtime.steer_job("6cc1590c", NOTE)["ok"] is False, "끝난 판은 여전히 말을 받지 않는다 — 화면이 새 판으로 보낸다"
    assert runtime._late_steer_base("jarvis-muppho0l", f"  {NOTE} ") == FIRST
    assert runtime._late_steer_base("jarvis-muppho0l", NOTE) == "", "한 번 쓰면 지운다"


def test_a_leftover_note_is_remembered_too() -> None:
    runtime = _runtime(_finished(), leftover=["한국어 페이지로", "환율 금지"])
    runtime._publish_leftover_steer(_finished())
    assert ("agent_steer_leftover", {"job_id": "6cc1590c", "texts": ["한국어 페이지로", "환율 금지"]}) in runtime.events.sent
    # 화면은 남은 말을 줄바꿈으로 이어 새 판 하나로 보낸다.
    assert runtime._late_steer_base("jarvis-muppho0l", "한국어 페이지로\n환율 금지") == FIRST


def test_another_conversation_or_another_sentence_does_not_inherit() -> None:
    runtime = _runtime(_finished())
    runtime.steer_job("6cc1590c", NOTE)
    assert runtime._late_steer_base("다른-대화", NOTE) == ""
    assert runtime._late_steer_base("jarvis-muppho0l", "날씨 알려줘") == ""


def test_an_old_note_expires() -> None:
    runtime = _runtime(_finished())
    runtime.steer_job("6cc1590c", NOTE)
    runtime._late_steers["jarvis-muppho0l"] = [(0.0, " ".join(NOTE.split()), FIRST)]
    assert runtime._late_steer_base("jarvis-muppho0l", NOTE) == ""


def test_a_chain_of_notes_keeps_the_first_question() -> None:
    runtime = _runtime(_finished())
    runtime.__dict__.setdefault("_late_steer_bases", {})["52017231"] = f"{FIRST} {NOTE}"
    second = {"id": "52017231", "kind": "chat", "status": "completed",
              "payload": {"prompt": NOTE, "session_id": "jarvis-muppho0l"}}
    runtime.store = _Store(second)
    runtime.steer_job("52017231", "Manus 도 꼭 넣어")
    assert runtime._late_steer_base("jarvis-muppho0l", "Manus 도 꼭 넣어") == f"{FIRST} {NOTE}"


def test_the_chat_handler_plans_from_the_joined_request() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "runtime.py").read_text(encoding="utf-8")
    assert 'plan_prompt=handoff[0] if handoff else steer_plan,' in source
    assert "or bool(steer_plan)" in source, "덧붙인 말 판은 라우터가 대화로 빼지 않는다"
