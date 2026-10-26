"""전사는 뒤에 붙기만 한다 (2026-10-24 · 전략안 §55-43 · `transcript.APPEND_ONLY_FOLD_TARGET` 의 설명).

운영 판 셋(27B · 창 131,072)에서 「지난번에 보낸 대화와 앞에서부터 같은 메시지 수」(`prefix_kept`)가 22번 지난 개수보다 작았다 —
그때마다 앞부분 캐시가 그 자리부터 깨져 한 번에 25~44초를 다시 읽었다. 까닭은 부르기마다 「무엇을 접을지」를 처음부터 다시
고른 규칙 둘이었다(넘침 묶어 접기의 미끄러지는 경계 · 길 찾기 8개 묶음 접기). 이 파일은 **행동**으로 지킨다:
가짜 판을 여러 걸음 돌려 부르기마다 앞 메시지가 그대로인지(접는 순간만 빼고), 예산을 크게 넘는 판에서도 시킨 일이 남는지.
"""

from __future__ import annotations

import copy
import json

from alture_jarvis import ollama as ollama_mod
from alture_jarvis.agent import BrowserAgent, numbers_read_in
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.transcript import bounded, message_sig

TASK = "레딧 세 게시판에서 이번 주 인기 글 10개를 읽고 표로 정리해"


def page(name: str, size: int, n: int, *, price: str = "") -> dict:
    body = {"ok": True, "url": f"https://example.com/p/{n}", "title": f"글 {n}", "text": f"가격 {price} " + "가" * size}
    return {"role": "tool", "tool_name": name, "content": json.dumps(body, ensure_ascii=False)}


def step(messages: list[dict], name: str, size: int, *, price: str = "") -> None:
    messages.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": {}}}],
                     "_inference": {"telemetry": "t" * 480}})
    messages.append(page(name, size, len(messages), price=price))


def run(steps: list[tuple[str, int]], *, budget: int, state: dict | None) -> list[tuple[int, int, bool]]:
    """걸음마다 전사를 골라 (지난 개수, 앞에서부터 같은 수, 이번에 한꺼번에 접었나)를 돌려준다."""
    messages = [{"role": "system", "content": "지" * 18_000}, {"role": "user", "content": TASK}]
    rows: list[tuple[int, int, bool]] = []
    prev: list[str] | None = None
    for name, size in steps:
        step(messages, name, size)
        out = bounded(messages, max_chars=budget, tool_result_max=30_000, fold_state=state)
        folded = bool(state and state.pop("just_folded", False))
        sigs = [message_sig(item) for item in out]
        if prev is not None:
            kept = next((i for i, (a, b) in enumerate(zip(prev, sigs)) if a != b), min(len(prev), len(sigs)))
            rows.append((len(prev), kept, folded))
        prev = sigs
    return rows


#: f6b60f9c 를 닮은 판 — 열기(작음)와 본문 읽기(2만 9천 자)가 번갈아, 예산 18만 자를 여러 번 넘긴다.
READ_RUN = [("browser_open", 2_000) if i % 2 == 0 else ("browser_extract", 28_000) for i in range(36)]
#: e9098192 를 닮은 판 — 스냅샷 · 요소 찾기(길 찾기)가 섞이고 예산은 안 넘는다.
NAV_RUN = [(("browser_open", 2_000), ("browser_snapshot", 3_000), ("browser_extract", 2_500))[i % 3] for i in range(36)]


def test_old_rule_breaks_the_middle_new_rule_only_appends() -> None:
    """옛 규칙은 넘친 뒤 결과 하나마다 경계가 미끄러졌다. 새 규칙은 접는 순간이 아니면 앞이 글자까지 같다."""
    old = run(READ_RUN, budget=180_000, state=None)
    old_breaks = sum(1 for prev, kept, _ in old if kept != prev)
    state: dict = {}
    new = run(READ_RUN, budget=180_000, state=state)
    for prev, kept, folded in new:
        assert folded or kept == prev, f"접지도 않았는데 앞이 바뀌었다: {kept}/{prev}"
    new_breaks = sum(1 for prev, kept, _ in new if kept != prev)
    assert new_breaks == state["folds"] > 0, "넘쳤으니 접기는 있어야 하고, 바뀐 것은 접은 순간뿐이어야 한다"
    assert old_breaks > new_breaks, f"옛 {old_breaks}번 → 새 {new_breaks}번"


def test_navigation_is_not_folded_by_count_while_under_budget() -> None:
    """예산이 남은 판에서는 한 번도 안 바뀐다 — 예전엔 길 찾기 결과 8개마다 오래된 스냅샷을 접어 앞이 바뀌었다."""
    old = run(NAV_RUN, budget=180_000, state=None)
    assert any(kept != prev for prev, kept, _ in old), "옛 규칙에서 길 찾기 묶음 접기가 재현돼야 이 시험이 뜻이 있다"
    state: dict = {}
    new = run(NAV_RUN, budget=180_000, state=state)
    assert all(kept == prev for prev, kept, _ in new)
    assert not state.get("folds")


def test_the_big_fold_folds_old_navigation_and_keeps_recent_whole() -> None:
    state: dict = {}
    messages = [{"role": "system", "content": "지" * 18_000}, {"role": "user", "content": TASK}]
    for name, size in NAV_RUN[:9] + READ_RUN:
        step(messages, name, size)
        out = bounded(messages, max_chars=180_000, tool_result_max=30_000, fold_state=state)
        if state.get("folds"):
            break  # 첫 접기 — 그 뒤 긴 판에서는 오래된 걸음이 통째로 덜어진다(`test_task_survives_a_run_far_over_budget`)
    assert state["folds"] == 1
    tools = [item for item in out if item.get("role") == "tool"]
    old_snapshots = [item for item in tools[:-4] if item.get("tool_name") == "browser_snapshot"]
    assert old_snapshots and all(item["content"].startswith("[접음]") for item in old_snapshots)
    assert all(not item["content"].startswith("[접음]") for item in tools[-4:]), "방금 본 것은 원문이어야 한다"


def test_task_survives_a_run_far_over_budget() -> None:
    """2026-08-20 쿠팡 판: 앞쪽이 잘려 시킨 일을 잃었다. 접는 상태를 들고 있어도 시킨 일은 고정이다."""
    state: dict = {}
    messages = [{"role": "system", "content": "지" * 18_000}, {"role": "user", "content": TASK}]
    for i in range(80):
        step(messages, "browser_extract", 28_000)
        out = bounded(messages, max_chars=120_000, tool_result_max=30_000, fold_state=state)
        assert out[0]["role"] == "system" and out[1]["role"] == "user" and TASK in out[1]["content"], f"{i}걸음에 시킨 일이 사라졌다"
        size = sum(len(json.dumps({k: v for k, v in item.items() if k != "_metrics"}, ensure_ascii=False)) for item in out)
        assert size <= 120_000 + 1_000, f"{i}걸음에 예산을 넘겼다({size:,}자)"


def test_original_messages_keep_the_body_for_the_number_ledger() -> None:
    """모델에게 보내는 사본만 접는다 — 근거 숫자 대조(`numbers_read_in`)는 원문을 본다. 접힌 페이지의 숫자도 근거로 남는다."""
    state: dict = {}
    messages = [{"role": "system", "content": "지" * 18_000}, {"role": "user", "content": TASK}]
    step(messages, "browser_extract", 28_000, price="987,654원")
    before = copy.deepcopy(messages)
    for name, size in READ_RUN:
        step(messages, name, size)
        out = bounded(messages, max_chars=180_000, tool_result_max=30_000, fold_state=state)
    assert state["folds"] >= 1
    first_page = next(item for item in out if item.get("role") == "tool")
    assert first_page["content"].startswith("[접음]"), "이 시험은 첫 페이지가 사본에서 접혀야 뜻이 있다"
    assert messages[:4] == before, "원래 전사는 그대로여야 한다"
    assert "987654" in numbers_read_in(messages) or "987,654" in numbers_read_in(messages)


# ── 에이전트를 지나는 길 — 부르기 기록 이름표까지 ─────────────────────────────────────


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names: set[str] = set()
    ollama_tools: list = []


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        raise AssertionError("도구를 실행하지 않는다")


class _Recorder:
    def __init__(self) -> None:
        self.tags: list[dict] = []

    def chat_messages_stream(self, messages, *, tools=None, temperature=0.1, think=False, on_chunk=None, **kwargs):
        self.tags.append(dict(ollama_mod._CALL_TAGS.get()))
        return {"role": "assistant", "content": "다음 걸음."}


def _agent(tmp_path) -> tuple[BrowserAgent, _Recorder]:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs", browser_enabled=True)
    model = _Recorder()
    agent = BrowserAgent(config, model, _Gateway(), _Browser(), _Tools(), JobStore(tmp_path / "j.db"), EventBus())
    return agent, model


def _drive(agent: BrowserAgent, model: _Recorder) -> list[dict]:
    messages = [{"role": "system", "content": "지" * 18_000}, {"role": "user", "content": TASK}]
    for name, size in READ_RUN + READ_RUN:
        step(messages, name, size)
        agent._model_message(messages, job_id="j", tools=None, think=True)
    return model.tags[1:]


def test_every_call_keeps_the_prefix_unless_it_is_a_big_fold(tmp_path) -> None:
    """부르기 기록에 남는 값 그대로 — `prefix_kept == prev_messages`, 아니면 `append_folded` 이름표가 붙은 부르기."""
    agent, model = _agent(tmp_path)
    tags = _drive(agent, model)
    assert tags and all("prefix_kept" in tag for tag in tags)
    breaks = [tag for tag in tags if tag["prefix_kept"] != tag["prev_messages"]]
    assert breaks, "예산을 넘기는 판이라 접기가 한 번은 있어야 한다"
    assert all(tag.get("append_folded") for tag in breaks), "접는 순간이 아닌데 앞이 바뀐 부르기가 있다"
    assert len(breaks) <= len(tags) // 4, f"접기가 드물지 않다: {len(breaks)}/{len(tags)}"


def test_switch_off_restores_the_old_rule(tmp_path, monkeypatch) -> None:
    """되돌리는 법이 실제로 되돌린다 — 끄면 예전처럼 접는 이름표 없이 앞이 바뀐다."""
    monkeypatch.setenv("JARVIS_APPEND_ONLY_TRANSCRIPT", "0")
    agent, model = _agent(tmp_path)
    tags = _drive(agent, model)
    assert not any(tag.get("append_folded") for tag in tags)
    assert any(tag["prefix_kept"] != tag["prev_messages"] for tag in tags)


def test_a_long_run_folds_rarely_and_drops_old_steps_at_once() -> None:
    """접힌 줄만으로도 과녁을 넘는 긴 판 — 예전엔 여기서 다시 한 걸음마다 미끄러졌다(맨 앞에서 하나씩 버림).
    이제는 오래된 걸음을 한꺼번에 덜어 내고, 그 사이 부르기는 뒤에 붙기만 한다."""
    state: dict = {}
    rows = run(READ_RUN * 4, budget=180_000, state=state)
    assert all(folded or kept == prev for prev, kept, folded in rows)
    assert state.get("cut_sig"), "이 판은 덜어 내기까지 가야 뜻이 있다"
    assert state["folds"] <= len(rows) // 5, f"접기가 드물지 않다: {state['folds']}/{len(rows)}"
