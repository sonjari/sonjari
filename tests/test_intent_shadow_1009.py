"""「그림자 기록」의 시험 — 맡기기 **전에** 합격 시험으로 썼고(2026-10-09), 손자리가 통과시킨 뒤 여기로 옮겼다.

무엇: 사람이 한 요청에서 「무엇을 시켰나」 일곱 칸을, 지금처럼 낱말 규칙(plan.py)으로 뽑은 것과 **모델에게 읽힌 것**을 나란히
그 판의 결과에 남긴다. 나중에 둘이 어긋난 판만 모아 본다. 판의 동작은 하나도 바꾸지 않는다 — 기록만 한다.

근거: bench/intent_reading_1009 (74문장 · 27B 70 · 낱말 규칙 57 · 9B 53 · 4B 41). 칸 이름·지시문·낱말 규칙 쪽 읽는 법이 거기 있다.

정해 둔 것(설계):
  · 새 모듈 `alture_jarvis.intent_shadow` — FIELDS · SYSTEM · read_by_rules · read_by_model · differing · record · attach
  · 설정 `intent_shadow_enabled`(기본 꺼짐) · 환경변수 `JARVIS_INTENT_SHADOW_ENABLED`
  · 런타임: `_chat_job_inner` 가 **판이 끝난 뒤에** `intent_shadow.attach(…)` 를 한 번 부른다. 판 도중에는 모델을 따로 부르지 않는다
    (서버의 대화 캐시가 깨져 판이 느려진다 — 2026-10-09 새벽에 잰 것).
  · 모델 호출은 `JarvisRuntime._intent_shadow_ask(system, user) -> str` 하나로 모은다.

"""
from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from alture_jarvis import intent_shadow
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime

FIELDS = ("count", "open", "file", "scope", "act", "code", "leans")
GOOD = {"count": 3, "open": "yes", "file": True, "scope": "none", "act": "none", "code": False, "leans": False}


def _never(system: str, user: str) -> str:
    raise AssertionError("모델을 부르면 안 되는 자리다")


# ── 일곱 칸 · 낱말 규칙 쪽 ─────────────────────────────────────────────────────────


def test_the_seven_fields_are_the_ones_the_experiment_used() -> None:
    assert tuple(intent_shadow.FIELDS) == FIELDS
    for name in FIELDS:
        assert name in intent_shadow.SYSTEM, f"모델에게 주는 지시문이 {name} 칸을 설명해야 한다"


@pytest.mark.parametrize(("prompt", "want"), [
    ("채용 사이트에서 서울 마케팅 공고 3개를 직접 열어 읽고 엑셀로 정리해줘",
     {"count": 3, "open": "yes", "file": True, "scope": "none", "act": "none", "code": False, "leans": False}),
    ("조사만 해줘. 파일은 아무것도 만들지 마",
     {"count": 0, "open": "-", "file": False, "scope": "all", "act": "none", "code": False, "leans": False}),
    ("이 함수의 버그를 고쳐줘",
     {"count": 0, "open": "-", "file": False, "scope": "none", "act": "none", "code": True, "leans": False}),
    ("이어서 해줘",
     {"count": 0, "open": "-", "file": False, "scope": "none", "act": "none", "code": False, "leans": True}),
    ("설정 파일은 건드리지 말고 나머지 코드만 고쳐줘",
     {"count": 0, "open": "-", "file": False, "scope": "target", "act": "none", "code": True, "leans": False}),
])
def test_the_rules_side_reads_what_the_harness_reads(prompt: str, want: dict[str, Any]) -> None:
    """낱말 규칙 쪽은 실험의 `by_regex`(bench/intent_reading_1009/intent_compare.py)와 같은 값을 낸다 — 그 함수를 옮긴 것이다."""
    assert intent_shadow.read_by_rules(prompt) == want


def test_the_rules_side_never_raises_on_odd_input() -> None:
    for prompt in ("", "   ", "?", "a" * 5000):
        got = intent_shadow.read_by_rules(prompt)
        assert set(got) == set(FIELDS)


# ── 모델 쪽 ───────────────────────────────────────────────────────────────────


def test_the_model_is_asked_once_with_the_instruction_and_the_request_as_it_is() -> None:
    asked: list[tuple[str, str]] = []

    def ask(system: str, user: str) -> str:
        asked.append((system, user))
        return json.dumps(GOOD)

    assert intent_shadow.read_by_model("공고 3개 열어서 엑셀로", ask) == GOOD
    assert asked == [(intent_shadow.SYSTEM, "공고 3개 열어서 엑셀로")]


def test_a_reply_with_words_around_the_json_is_still_read() -> None:
    wrapped = "칸을 채웠습니다.\n```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```\n"
    assert intent_shadow.read_by_model("x", lambda system, user: wrapped) == GOOD


@pytest.mark.parametrize("reply", [
    "모르겠습니다",
    "",
    "{",
    json.dumps({key: value for key, value in GOOD.items() if key != "leans"}),   # 칸이 모자람
    json.dumps({**GOOD, "open": "maybe"}),                                        # 정해진 값이 아님
    json.dumps({**GOOD, "scope": "everything"}),
    json.dumps({**GOOD, "act": "tweet"}),
    json.dumps({**GOOD, "count": "세 개"}),
    json.dumps({**GOOD, "count": -1}),
    json.dumps({**GOOD, "file": "yes"}),
    json.dumps([GOOD]),
])
def test_a_reply_that_does_not_fit_the_seven_fields_is_no_reading(reply: str) -> None:
    assert intent_shadow.read_by_model("x", lambda system, user: reply) is None


def test_a_failing_or_slow_model_is_no_reading_and_never_an_error() -> None:
    def broken(system: str, user: str) -> str:
        raise TimeoutError("모델이 늦다")

    assert intent_shadow.read_by_model("x", broken) is None


def test_extra_fields_in_the_reply_are_dropped() -> None:
    got = intent_shadow.read_by_model("x", lambda system, user: json.dumps({**GOOD, "note": "덤"}))
    assert got == GOOD


# ── 어긋난 칸 ─────────────────────────────────────────────────────────────────


def test_differing_names_the_fields_in_order() -> None:
    assert intent_shadow.differing(GOOD, dict(GOOD)) == []
    assert intent_shadow.differing(GOOD, {**GOOD, "leans": True, "count": 5}) == ["count", "leans"]


def test_a_count_of_zero_and_one_are_the_same_reading() -> None:
    """하네스는 1 이하를 개수 요구로 치지 않는다 — 실험의 채점도 그렇게 고쳤다."""
    assert intent_shadow.differing({**GOOD, "count": 0}, {**GOOD, "count": 1}) == []
    assert intent_shadow.differing({**GOOD, "count": 1}, {**GOOD, "count": 2}) == ["count"]


# ── 한 판의 기록 ───────────────────────────────────────────────────────────────


def test_a_record_holds_both_readings_and_where_they_differ() -> None:
    record = intent_shadow.record("이어서 해줘", lambda system, user: json.dumps(GOOD))
    assert set(record) == {"rules", "model", "differs", "sec", "error"}
    assert record["rules"] == intent_shadow.read_by_rules("이어서 해줘")
    assert record["model"] == GOOD
    assert record["differs"] == intent_shadow.differing(record["rules"], GOOD) and "leans" in record["differs"]
    assert isinstance(record["sec"], float) and record["sec"] >= 0 and record["error"] == ""


def test_a_record_survives_a_broken_model() -> None:
    def broken(system: str, user: str) -> str:
        raise ConnectionError("서버가 없다")

    record = intent_shadow.record("이 함수의 버그를 고쳐줘", broken)
    assert record["model"] is None and record["differs"] == []
    assert record["rules"]["code"] is True
    assert record["error"], "왜 못 읽었는지 한 줄은 남긴다"
    assert len(record["error"]) <= 200


# ── 결과에 붙이기 ──────────────────────────────────────────────────────────────


def test_off_by_default_nothing_is_added_and_the_model_is_not_called() -> None:
    result = {"answer": "끝", "completion_state": "complete"}
    intent_shadow.attach(result, "공고 3개 열어서 엑셀로", enabled=False, origin="workspace", ask=_never)
    assert result == {"answer": "끝", "completion_state": "complete"}


def test_on_it_adds_one_key_and_touches_nothing_else() -> None:
    result = {"answer": "끝", "completion_state": "complete", "agent_trace": {"steps": [1, 2]}}
    intent_shadow.attach(result, "공고 3개 열어서 엑셀로", enabled=True, origin="workspace", ask=lambda s, u: json.dumps(GOOD))
    assert set(result) == {"answer", "completion_state", "agent_trace", "intent_shadow"}
    assert result["answer"] == "끝" and result["completion_state"] == "complete" and result["agent_trace"] == {"steps": [1, 2]}
    assert result["intent_shadow"]["model"] == GOOD


def test_a_job_another_ai_delegated_is_not_shadowed() -> None:
    """맡긴 일의 글은 AI 가 쓴 것이다 — 사람의 요청을 읽는 법을 보려는 기록에 섞지 않는다."""
    result = {"answer": "끝"}
    intent_shadow.attach(result, "함수를 고쳐줘", enabled=True, origin="mcp", ask=_never)
    assert result == {"answer": "끝"}


def test_a_request_a_person_spoke_is_shadowed_like_one_they_typed() -> None:
    """가져올 때 고친 것 — 처음 구현은 창에서 온 요청만 적었다. 빼는 것은 맡긴 일 하나다."""
    for origin in ("voice", "workspace", "hud", ""):
        result = {"answer": "끝"}
        intent_shadow.attach(result, "공고 3개 열어서 엑셀로", enabled=True, origin=origin, ask=lambda s, u: json.dumps(GOOD))
        assert result["intent_shadow"]["model"] == GOOD, origin


def test_an_empty_request_is_not_shadowed() -> None:
    result = {"answer": "끝"}
    intent_shadow.attach(result, "   ", enabled=True, origin="workspace", ask=_never)
    assert result == {"answer": "끝"}


def test_attaching_never_breaks_the_job() -> None:
    def broken(system: str, user: str) -> str:
        raise RuntimeError("무엇이든")

    result = {"answer": "끝"}
    intent_shadow.attach(result, "공고 3개", enabled=True, origin="workspace", ask=broken)
    assert result["answer"] == "끝" and result["intent_shadow"]["model"] is None
    intent_shadow.attach(None, "공고 3개", enabled=True, origin="workspace", ask=broken)   # 결과가 없어도 조용히 지나간다


# ── 설정 ─────────────────────────────────────────────────────────────────────


def test_the_switch_is_off_unless_the_environment_turns_it_on(tmp_path, monkeypatch) -> None:
    assert JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o").intent_shadow_enabled is False
    monkeypatch.delenv("JARVIS_INTENT_SHADOW_ENABLED", raising=False)
    assert JarvisConfig.from_env().intent_shadow_enabled is False
    monkeypatch.setenv("JARVIS_INTENT_SHADOW_ENABLED", "1")
    assert JarvisConfig.from_env().intent_shadow_enabled is True


# ── 런타임 배선 ────────────────────────────────────────────────────────────────


def test_the_runtime_attaches_after_the_job_has_run_and_only_once() -> None:
    source = inspect.getsource(JarvisRuntime._chat_job_inner)
    assert source.count("intent_shadow.attach(") == 1
    assert source.index("intent_shadow.attach(") > source.index("self.agent.run("), "판이 끝난 뒤에 — 도중에 모델을 따로 부르지 않는다"
    call = source[source.index("intent_shadow.attach("):][:400]
    assert "intent_shadow_enabled" in call and "_intent_shadow_ask" in call and "origin" in call


def test_the_runtime_asks_the_model_plainly() -> None:
    """생각을 끄고 · 도구 없이 · 지시문과 요청 둘만 보낸다. 돌려주는 것은 모델이 쓴 글이다."""
    seen: dict[str, Any] = {}

    class _Model:
        def chat_messages(self, messages, **kwargs):  # noqa: ANN001, ANN003, ANN201
            seen["messages"] = messages
            seen["kwargs"] = kwargs
            return {"role": "assistant", "content": json.dumps(GOOD)}

    runtime = object.__new__(JarvisRuntime)
    runtime.ollama = _Model()
    assert json.loads(runtime._intent_shadow_ask("지시문", "요청")) == GOOD
    assert seen["messages"] == [{"role": "system", "content": "지시문"}, {"role": "user", "content": "요청"}]
    assert seen["kwargs"].get("think") is False
    assert not seen["kwargs"].get("tools")
    assert seen["kwargs"].get("temperature") == 0
