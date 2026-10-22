"""**사고가 예산을 통째로 먹는 턴을 끊는다** (2026-09-18 실측).

## 무엇이 있었나

사용자가 질문 하나에 5분을 기다렸다. 그 판(316초)을 호출 단위로 갈라 보니:

    턴 | 맥락 읽기(프리필)      | 생성                  | 그중 사고
     1 | 21,956토큰   6.7초    | 2,354토큰   23.5초    |  4,128자
     2 | 23,338토큰   0.7초    | 1,040토큰   10.2초    |  3,824자
     3 | 24,861토큰   0.8초    |   455토큰    4.5초    |  1,714자
     4 | 27,901토큰   1.4초    | 8,192토큰   85.4초    | 30,237자   ← 상한을 사고로 다 씀
     5 | 19,308토큰   5.9초    | 8,192토큰   82.7초    | 30,080자   ← 같은 모양
     6 | 19,310토큰   6.1초    | 1,088토큰   10.9초    |      0자
     7 | 20,614토큰   0.5초    | 1,111토큰   11.1초    |      0자

**프리필은 22초(7%)뿐이다** — 맥락 캐시는 잘 듣는다. 생성이 228초(77%)이고, 그중
**두 턴이 168초(판의 57%)**. 그 둘은 `num_predict` 8,192 를 전부 사고에 쓰고 답에는
600토큰만 남겼다.

모집단(판 153개·모델 턴 1,366개)에서도 같다: 상한까지 쓴 턴은 **1.5%뿐인데 생성
시간의 19%**를 먹고, 그런 턴이 한 번이라도 있는 판이 **12%** 다.

## 왜 우리가 끊어야 하나

로컬 엔진에는 사고 예산이 없다. `think` 를 `low`/`medium` 으로 낮춰 봤지만 우리
모델에서는 차이가 없었다(같은 프롬프트: 3,193자 17.5초 → 2,740자 14.1초).
그래서 **흐름을 닫고 지금까지의 생각을 들려주며 한 번 더 부른다** — Qwen 공식
우회법과 같은 모양이고, 앞 대화가 그대로라 두 번째 프리필은 싸다(20K 토큰 0.5~1.4초).

## 값의 근거

사고가 있는 턴 1,306개의 분포에 계단이 있다 — 95%가 5,711자 안인데 98%가 20,828자다.
**8,000자**는 보통 사고를 안 건드리고(95% 통과) 폭주만 잡는다(3.6%).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest


class _Response:
    def __init__(self, lines: list[str]) -> None:
        self.status_code = 200
        self._lines = lines
        self.text = ""
        self.closed_early = False

    def read(self) -> bytes:  # pragma: no cover — 400 일 때만 쓴다
        return b""

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self):
        for line in self._lines:
            yield line
        # 여기까지 왔으면 끝까지 읽은 것이다 — 예산이 안 걸렸다는 뜻.
        self.closed_early = False


class _Client:
    plan: list[_Response] = []
    bodies: list[dict[str, Any]] = []

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def stream(self, _method: str, _url: str, **kwargs: Any) -> _Response:
        type(self).bodies.append(kwargs.get("json") or {})
        return type(self).plan[len(type(self).bodies) - 1]


def _thinking_lines(chars: int, chunk: int = 500) -> list[str]:
    """사고만 흘리는 조각들. 끝에 done 을 두지만 예산에 걸리면 거기까지 안 간다."""
    lines = []
    sent = 0
    while sent < chars:
        piece = "가" * min(chunk, chars - sent)
        sent += len(piece)
        lines.append(json.dumps({"message": {"thinking": piece}}, ensure_ascii=False))
    lines.append(json.dumps({"message": {"content": "늦은 답"}, "done": True,
                             "done_reason": "stop", "eval_count": 8192}, ensure_ascii=False))
    return lines


_ANSWERED = json.dumps(
    {"message": {"content": "바로 답"}, "done": True, "done_reason": "stop", "eval_count": 300},
    ensure_ascii=False,
)


def _client(monkeypatch: Any, plan: list[_Response], budget: int = 8000) -> Any:
    from alture_jarvis import ollama as module
    from alture_jarvis.config import JarvisConfig

    _Client.plan, _Client.bodies = plan, []
    monkeypatch.setattr(module.httpx, "Client", _Client)
    config = JarvisConfig()
    config.ollama_thinking_char_budget = budget
    client = module.OllamaClient(config)
    for name in ("_make_room_for", "_wait_out_transient_404"):
        monkeypatch.setattr(type(client), name, lambda self, _x: None, raising=False)
    return client


def test_a_runaway_turn_is_cut_and_answered(monkeypatch: Any) -> None:
    """★ 그 판의 4번 턴 그대로 — 30,000자를 생각하면 끊고, 두 번째 호출로 답을 받는다."""
    client = _client(monkeypatch, [_Response(_thinking_lines(30_000)), _Response([_ANSWERED])])
    message = client.chat_messages_stream([{"role": "user", "content": "경쟁자 분석"}], think=True)

    assert message["content"] == "바로 답", "두 번째 호출의 답이 나와야 한다"
    assert message["_thinking_budget"]["hit"] is True
    assert message["_thinking_budget"]["thinking_chars"] >= 8000
    assert len(_Client.bodies) == 2, "두 번 불러야 한다(끊고 · 답하고)"


def test_the_second_call_stops_thinking_and_carries_the_thought_over(monkeypatch: Any) -> None:
    """생각을 **버리지 않는다.** 끝부분을 들려주고, 두 번째는 생각을 끈다."""
    client = _client(monkeypatch, [_Response(_thinking_lines(30_000)), _Response([_ANSWERED])])
    message = client.chat_messages_stream([{"role": "user", "content": "경쟁자 분석"}], think=True)

    second = _Client.bodies[1]
    assert second["think"] is False, "두 번째에도 생각하면 같은 자리에서 또 터진다"
    nudge = second["messages"][-1]
    assert nudge["role"] == "user" and "지금 바로" in nudge["content"]
    assert "가" in nudge["content"], "지금까지 한 생각을 들려줘야 한다"
    assert len(message["thinking"]) >= 8000, "장부에는 원래 사고가 남아야 한다(근거가 사라지면 안 된다)"


def test_normal_thinking_is_never_touched(monkeypatch: Any) -> None:
    """★ 좋은 표본. 보통 턴(사고 있는 턴의 95%가 5,711자 안)은 한 번에 끝나야 한다."""
    client = _client(monkeypatch, [_Response(_thinking_lines(5_000))])
    message = client.chat_messages_stream([{"role": "user", "content": "짧은 질문"}], think=True)

    assert len(_Client.bodies) == 1, "보통 사고를 끊으면 그것이 곧 품질 손해다"
    assert message.get("_thinking_budget") is None
    assert message["content"] == "늦은 답"


def test_a_turn_that_already_started_answering_is_left_alone(monkeypatch: Any) -> None:
    """답이나 도구 호출이 나오기 시작했으면 그 턴은 이미 생각을 끝낸 것이다 — 건드리지 않는다."""
    lines = [
        json.dumps({"message": {"thinking": "가" * 9000}}, ensure_ascii=False),
        json.dumps({"message": {"content": "이미 답 중"}}, ensure_ascii=False),
        json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop"}, ensure_ascii=False),
    ]
    # 사고 조각이 통째로 하나라 예산 검사는 그 조각 뒤에 처음 돈다 — 그때는 아직 답이 없다.
    # 그래서 여기서는 답이 먼저 온 경우를 본다.
    lines = [
        json.dumps({"message": {"thinking": "가" * 4000}}, ensure_ascii=False),
        json.dumps({"message": {"content": "이미 답 중"}}, ensure_ascii=False),
        json.dumps({"message": {"thinking": "가" * 9000}}, ensure_ascii=False),
        json.dumps({"message": {"content": " 계속"}, "done": True, "done_reason": "stop"}, ensure_ascii=False),
    ]
    client = _client(monkeypatch, [_Response(lines)])
    message = client.chat_messages_stream([{"role": "user", "content": "질문"}], think=True)

    assert len(_Client.bodies) == 1
    assert message["content"] == "이미 답 중 계속"


def test_a_call_that_does_not_think_has_no_budget(monkeypatch: Any) -> None:
    """생각을 안 켠 호출에는 걸 것이 없다 — 긴 답을 사고로 오해해 끊으면 안 된다."""
    long_answer = [
        json.dumps({"message": {"content": "나" * 20_000}}, ensure_ascii=False),
        json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop"}, ensure_ascii=False),
    ]
    client = _client(monkeypatch, [_Response(long_answer)])
    message = client.chat_messages_stream([{"role": "user", "content": "길게 써줘"}], think=False)

    assert len(_Client.bodies) == 1
    assert len(message["content"]) == 20_000


def test_the_budget_can_be_turned_off(monkeypatch: Any) -> None:
    client = _client(monkeypatch, [_Response(_thinking_lines(30_000))], budget=0)
    message = client.chat_messages_stream([{"role": "user", "content": "질문"}], think=True)
    assert len(_Client.bodies) == 1 and message.get("_thinking_budget") is None


def test_the_default_budget_sits_above_normal_thinking_and_below_the_runaways() -> None:
    """★ 값은 재 보고 정한다. 좋은 표본(5,711자)과 나쁜 표본(20,828자) 사이여야 한다."""
    from alture_jarvis.config import JarvisConfig

    budget = JarvisConfig().ollama_thinking_char_budget
    assert 5_711 < budget < 20_828


def test_the_job_ledger_says_where_the_model_time_went() -> None:
    """「느리다」에 답하려면 프리필과 생성이 갈라져 있어야 한다 — 예전에는 손으로 더했다."""
    from alture_jarvis.agent import _model_time_summary

    summary = _model_time_summary([
        {"telemetry": {"prompt_eval_count": 21956, "prompt_eval_duration": 6_728_074_000,
                       "eval_count": 2354, "eval_duration": 23_460_245_000}},
        {"telemetry": {"prompt_eval_count": 27901, "prompt_eval_duration": 1_400_000_000,
                       "eval_count": 8192, "eval_duration": 85_400_000_000}},
    ])
    assert summary["turns"] == 2
    assert summary["prefill_sec"] == pytest.approx(8.1, abs=0.2)
    assert summary["generate_sec"] == pytest.approx(108.9, abs=0.2)
    assert summary["turns_at_predict_cap"] == 1, "상한에 닿은 턴을 세야 폭주를 본다"


_LOOP = (
    "하지만 이 질문은 \"온텔릭이 어떻게 하는지\"를 묻는 것이므로, 이는 온텔릭의 내부 구현 방식에 대한 질문입니다.\n\n"
    "사용자가 실제로 확인하고 싶은 것은 아마도:\n1. 현재 열려 있는 브라우저 창이 있는지 확인\n"
    "2. 어떤 사이트가 열려 있는지 확인\n3. 브라우저 조작 도구들이 어떻게 작동하는지 확인\n\n"
)


def test_a_looping_thought_is_cut_long_before_the_budget(monkeypatch: Any) -> None:
    """★ 2026-09-26 노트북 캡처 그대로 — 같은 네 줄이 되풀이되면 8천 자까지 기다리지 않는다."""
    lines = [json.dumps({"message": {"thinking": "먼저 질문을 봅니다. 사용자는 브라우저를 묻고 있습니다. "}}, ensure_ascii=False)]
    lines += [json.dumps({"message": {"thinking": piece}}, ensure_ascii=False)
              for _ in range(40) for piece in (_LOOP[:90], _LOOP[90:])]
    lines.append(json.dumps({"message": {"content": "늦은 답"}, "done": True}, ensure_ascii=False))
    client = _client(monkeypatch, [_Response(lines), _Response([_ANSWERED])])
    message = client.chat_messages_stream([{"role": "user", "content": "브라우저 어떻게 해"}], think=True)

    assert message["content"] == "바로 답"
    assert message["_thinking_budget"]["reason"] == "repeat"
    assert message["_thinking_budget"]["thinking_chars"] < 1500, "두 바퀴쯤에서 끊어야 한다"
    nudge = _Client.bodies[1]["messages"][-1]["content"]
    assert "되풀이" in nudge and nudge.count("내부 구현 방식") == 1, "되풀이한 문단은 한 번만 들려준다"


def test_ordinary_long_thinking_is_not_mistaken_for_a_loop() -> None:
    """★ 좋은 표본: 같은 낱말이 자주 나와도 **문장 토막이 통째로** 반복되지 않으면 되풀이가 아니다."""
    from alture_jarvis.ollama import thinking_is_looping

    text = "".join(f"{i}번째 후보는 가격이 {i * 1300}원이고 배송은 {i % 3 + 1}일 걸립니다. 다음 후보를 봅니다. " for i in range(80))
    assert not thinking_is_looping(text)
    assert thinking_is_looping(text + _LOOP + _LOOP[:170])


def test_what_the_second_call_produced_is_kept(monkeypatch: Any) -> None:
    """★ 2026-09-30 QR 판: 3.8 이 2단째에 8,027 토큰을 내고 도구 0개로 끝났는데 본문이 안 남아 추정으로만 말했다."""
    client = _client(monkeypatch, [_Response(_thinking_lines(30_000)), _Response([_ANSWERED])])
    message = client.chat_messages_stream([{"role": "user", "content": "경쟁자 분석"}], think=True)

    second = message["_thinking_budget"]["second_pass"]
    assert second["content_chars"] == len("바로 답") and second["tool_calls"] == 0
    assert second["content_head"] == "바로 답"


def test_qwen38_gets_room_to_finish_its_thought_in_both_places() -> None:
    """★ 3.8 은 8,000자에 잘리면 2단째에서 탈선했다. 기본표는 dataclass 와 로더가 **같은 한 곳**을 본다(사고 Q)."""
    from alture_jarvis.config import JarvisConfig, _thinking_budgets

    assert JarvisConfig().ollama_thinking_budget_by_model["qwen3.8"] == 16000
    assert _thinking_budgets("")["qwen3.8"] == 16000
    assert _thinking_budgets("")["qwen3.6"] == 3000


# ── 끊고 버린 첫 호출도 시간에 넣는다 (2026-10-19 · 긱뉴스 판 1b6df02d) ──────────────────────────────
#
# 그 판은 699초였는데 판 기록의 모델 시간(프리필 171 + 생성 304)과 도구 28초를 빼면 196초가 비었다. 서버 기록을 맞대 보니
# 대부분이 **끊고 버린 첫 호출 두 번**이었다(생각 되풀이 4,096토큰 · 마무리 생각 예산 4,424토큰 · 약 137초). 끊은 호출은 서버의
# 끝 기록이 안 와서 관측에 시간이 안 남는다. 동작은 그대로 두고 적기만 한다.


def test_the_cut_first_pass_is_written_on_the_answer_we_kept(monkeypatch: Any) -> None:
    client = _client(monkeypatch, [_Response(_thinking_lines(30_000)), _Response([_ANSWERED])])
    message = client.chat_messages_stream([{"role": "user", "content": "경쟁자 분석"}], think=True)

    inference = message["_inference"]
    assert inference["cut_first_passes"] == 1, "끊고 다시 부른 호출이 관측에 남아야 한다"
    assert inference["cut_first_pass_sec"] == pytest.approx(message["_thinking_budget"]["first_pass_sec"], abs=0.01)


def test_an_uncut_call_writes_nothing_extra(monkeypatch: Any) -> None:
    """★ 좋은 표본 — 끊지 않은 호출에는 덧붙는 칸이 없다(0 으로라도 적으면 「끊었다」로 잘못 셀 수 있다)."""
    client = _client(monkeypatch, [_Response(_thinking_lines(5_000))])
    message = client.chat_messages_stream([{"role": "user", "content": "짧은 질문"}], think=True)

    assert "cut_first_pass_sec" not in message["_inference"]
    assert "cut_first_passes" not in message["_inference"]


def test_the_job_ledger_counts_the_cut_time_apart_from_server_time() -> None:
    """서버 시간(프리필 · 생성)과 버린 시간은 따로 센다 — 섞으면 「생성이 느리다」와 「버렸다」가 구별이 안 된다."""
    from alture_jarvis.agent import _model_time_summary

    summary = _model_time_summary([
        {"telemetry": {"prompt_eval_count": 63297, "prompt_eval_duration": 76_137_510_000,
                       "eval_count": 97, "eval_duration": 1_924_170_000}, "cut_first_pass_sec": 70.02, "cut_first_passes": 1},
        {"telemetry": {"prompt_eval_count": 65158, "prompt_eval_duration": 4_703_230_000,
                       "eval_count": 7348, "eval_duration": 122_958_760_000}},
    ])
    assert summary["cut_first_pass_sec"] == pytest.approx(70.0, abs=0.1)
    assert summary["cut_first_passes"] == 1
    assert summary["prefill_sec"] == pytest.approx(80.8, abs=0.2), "버린 시간을 프리필에 섞지 않는다"
    assert summary["generate_sec"] == pytest.approx(124.9, abs=0.2), "버린 시간을 생성에 섞지 않는다"
    empty = _model_time_summary([{"telemetry": {"eval_count": 10, "eval_duration": 1_000_000_000}}])
    assert empty["cut_first_pass_sec"] == 0 and empty["cut_first_passes"] == 0


def test_the_report_uses_the_whole_job_not_the_last_twelve_turns() -> None:
    """★ 판 기록의 관측은 마지막 12개만 남는다 — 23턴 판의 프리필을 113초로 셌다(전체 171초). 판의 `model_time` 을 먼저 쓴다."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "report_model_time.py"
    spec = importlib.util.spec_from_file_location("report_model_time_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    last_twelve = [{"telemetry": {"prompt_eval_duration": 9_440_000_000, "eval_duration": 10_000_000_000}}] * 12
    whole = {"turns": 23, "prefill_sec": 170.9, "generate_sec": 304.4, "cut_first_pass_sec": 137.0}
    split = module._split({"verification": {"inference_observations": last_twelve, "model_time": whole},
                           "steps": [{"took_ms": 28_000}]}, 699.0)
    assert split["prefill"] == pytest.approx(170.9) and split["generate"] == pytest.approx(304.4)
    assert split["cut"] == pytest.approx(137.0) and split["turns"] == 23
    # 옛 판(요약 없음)은 예전처럼 남은 관측으로 센다 — 양쪽 표본.
    old = module._split({"verification": {"inference_observations": last_twelve}, "steps": []}, 300.0)
    assert old["prefill"] == pytest.approx(113.3, abs=0.1) and old["turns"] == 12 and old["cut"] == 0
