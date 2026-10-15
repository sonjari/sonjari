"""페이지 하나가 응답을 안 해 브라우저가 물리면, 사람에게 넘기지 않고 브라우저를 되살려 남은 가게로 잇는다 (2026-10-15).

가격 판 price1015c 3판(버즈 · 맡기기): 11번가 상품 페이지에서 `browser_extract` 가 56초째 물렸고, 다음 걸음 다섯이
전부 `browser_busy_stuck`(앞 동작에 물려 있음)으로 돌아오자 「같은 자리에서 5번 연속 실패」로 판 전체를 멈추고
사람에게 「크롬 창에서 팝업을 닫아 달라」고 넘겼다. 다나와는 이미 읽었고 G마켓은 가 보지도 못했다.
물린 브라우저는 사람이 화면을 만져서 풀리는 것이 아니다 — 우리가 일꾼을 갈아야(`_recover_from_stuck`) 풀린다.

지키는 약속:
- 끝의 실패가 전부 「브라우저가 물림」(busy_stuck · busy_active)이면 — 「시간 초과」(action_timeout · 사이트가 느림)는 예전처럼 「잠시 뒤 이어서」 — 막힘의 종류는 `page_hung` 이고,
  사람에게 화면을 맞추라고 하지 않는다.
- 반복문은 체크포인트(사람에게 넘기기)를 만들지 않고, 브라우저를 **바로 되살린 뒤**(`recover_now`) 모델에게
  「그 페이지는 응답이 없어 못 읽었다고 적고, 같은 주소를 다시 열지 말고 남은 출처로 계속하라」고 알린다.
- 그 알림 뒤에도 또 물리면 가진 것으로 답을 정리한다(사람을 부르지 않는다).
"""

from __future__ import annotations

from alture_jarvis.agent import STUCK_FAILURES_AFTER, BrowserAgent, _stuck_report
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.tool_gateway import ToolResult

HUNG = ("browser_busy_stuck — 브라우저가 앞 동작(browser_extract)에 56초째 물려 있습니다"
        "(대개 페이지가 로딩을 못 끝낸 경우입니다).")


def _hung() -> dict:
    return {"tool": "browser_search", "ok": False, "error": HUNG}


def test_hung_browser_failures_are_their_own_kind_and_ask_nobody_to_fix_the_screen() -> None:
    report = _stuck_report([_hung() for _ in range(STUCK_FAILURES_AFTER)])
    assert report is not None and report["kind"] == "page_hung"
    assert "크롬 창에서" not in report["ask"] and "팝업" not in report["ask"]


def test_a_mix_with_other_failures_is_still_handed_over() -> None:
    steps = [_hung() for _ in range(STUCK_FAILURES_AFTER - 1)] + [
        {"tool": "browser_click", "ok": False, "error": "browser_click_failed: element not found"}]
    assert _stuck_report(steps)["kind"] == "keeps_failing"


class _Hung:
    def execute(self, name, arguments, *, job_id=""):
        return ToolResult(False, name, error=HUNG)


class _KeepsTrying:
    def __init__(self) -> None:
        self.calls = 0
        self.saw_note = False

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if any("응답이 없" in str(item.get("content") or "") and "[시스템]" in str(item.get("content") or "") for item in messages):
            self.saw_note = True
            return {"role": "assistant", "content": "11번가 상품 페이지는 응답이 없어 읽지 못했습니다. 다나와 값만 적습니다."}
        return {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "browser_search", "arguments": {"query": f"무선 마우스 가격 비교 {self.calls}"}}}
        ]}


def test_the_loop_revives_the_browser_and_does_not_hand_over(tmp_path) -> None:
    from test_agent import FakeBrowser, FakeTools  # 같은 폴더의 대역

    class _Browser(FakeBrowser):
        revived = 0

        def recover_now(self) -> bool:
            type(self).revived += 1
            return True

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, ollama_max_tool_steps=30)
    store = JobStore(tmp_path / "jarvis.db")
    model = _KeepsTrying()
    agent = BrowserAgent(config, model, _Hung(), _Browser(), FakeTools(), store, EventBus())
    job = store.create_job("chat", "price", {"prompt": "무선 마우스 가격을 찾아줘"})
    store.claim_next()

    result = agent.run("무선 마우스 가격을 찾아줘", job_id=job["id"], origin="chat")

    assert model.saw_note, "응답 없는 페이지라는 알림을 모델이 받지 못했다"
    assert _Browser.revived >= 1, "브라우저를 되살리지 않았다"
    assert not store.get_agent_checkpoint(job["id"]), "사람에게 넘기는 체크포인트를 만들었다"
    answer = getattr(result, "answer", None) or (result.get("answer") if isinstance(result, dict) else str(result))
    assert "응답이 없" in str(answer)


def test_recover_now_replaces_a_stuck_worker(tmp_path) -> None:
    import threading

    import pytest

    from alture_jarvis.browser import BrowserWorker

    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
                                        browser_task_timeout_sec=1))
    release = threading.Event()
    with pytest.raises(RuntimeError, match="browser_action_timeout"):
        worker._submit(lambda: release.wait(30))
    assert worker.recover_now() is True
    assert worker._submit(lambda: "다시 됨") == "다시 됨"
    assert worker.recover_now() is False, "물린 것이 없으면 갈지 않는다"
    release.set()
