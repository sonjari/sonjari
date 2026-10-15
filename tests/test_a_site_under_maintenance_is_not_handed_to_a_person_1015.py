"""가게 하나가 **점검 중**이면 사람에게 넘기지 않고 남은 가게로 잇는다 (2026-10-15).

2026-10-15 02시~05시 20분, 6GB 노트북(4B 3비트 · 글만 읽기)의 밤샘 측정: G마켓이 새벽 점검(「점검중」)이었다.
손자리는 G마켓을 다섯 번 연속 열다 실패하자 「같은 자리에서 막힘」으로 판 전체를 멈추고 사람에게
「크롬 창에서 이 화면을 원하시는 상태로 맞춰 주세요(팝업 닫기·선택하기 등)」라고 부탁했다 — 25분 기다리다 끝났다.
그 사이 판 열한 개가 **0~2걸음**으로 끝났다. 다나와 · 11번가는 멀쩡했다.

점검 중인 사이트는 사람도 고칠 수 없다. 그래서:
- 끝의 실패가 전부 「점검 중(site_under_maintenance)」이면 막힘의 종류는 `site_down` 이고, 사람에게 화면을 맞추라고 하지 않는다.
- 반복문은 체크포인트(사람에게 넘기기)를 만들지 않고, 모델에게 「그 사이트는 점검 중이라 못 읽었다고 적고 남은 출처로
  계속하라 · 다시 열지 마라」고 알린 뒤 잇는다.
- 그 알림 뒤에도 또 점검 중에서 막히면 가진 것으로 답을 정리한다(사람을 부르지 않는다).
"""

from __future__ import annotations

from alture_jarvis.agent import STUCK_FAILURES_AFTER, BrowserAgent, _stuck_report
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.tool_gateway import ToolResult

DOWN = ("site_under_maintenance:gmarket.co.kr — 이 사이트는 지금 점검 중이거나 일시 오류 상태입니다(화면 문구: '점검중'). "
        "다시 열어도 같습니다.")


def _down() -> dict:
    return {"tool": "browser_open", "ok": False, "error": DOWN}


def test_maintenance_failures_are_their_own_kind_and_ask_nobody_to_fix_the_screen() -> None:
    report = _stuck_report([_down() for _ in range(STUCK_FAILURES_AFTER)])
    assert report is not None and report["kind"] == "site_down"
    assert "gmarket.co.kr" in report["blocked"]
    assert "크롬 창에서" not in report["ask"] and "팝업" not in report["ask"]


def test_a_mix_with_other_failures_is_still_handed_over() -> None:
    steps = [_down() for _ in range(STUCK_FAILURES_AFTER - 1)] + [
        {"tool": "browser_click", "ok": False, "error": "browser_click_failed: element not found"}]
    assert _stuck_report(steps)["kind"] == "keeps_failing"


class _Down:
    def execute(self, name, arguments, *, job_id=""):
        return ToolResult(False, name, error=DOWN)


class _KeepsOpening:
    """점검 중인 가게를 계속 여는 작은 모델 — 알림을 받으면 답을 쓴다."""

    def __init__(self) -> None:
        self.calls = 0
        self.saw_note = False

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if any("점검 중" in str(item.get("content") or "") and "[시스템]" in str(item.get("content") or "") for item in messages):
            self.saw_note = True
            return {"role": "assistant", "content": "G마켓은 점검 중이라 읽지 못했습니다. 다나와 · 11번가 값만 적습니다."}
        return {"role": "assistant", "content": "", "tool_calls": [
            # 대역(`test_agent.FakeTools`)이 아는 손은 browser_search · browser_read 뿐이다 — 그 손으로 게이트웨이까지 보내야
            #   오류 글(점검 중)이 걸음에 남는다. 모르는 손이면 「unknown_tool」로 막혀 다른 길을 시험하게 된다.
            {"function": {"name": "browser_search", "arguments": {"query": f"무선 마우스 가격 비교 {self.calls}"}}}
        ]}


def test_the_loop_does_not_hand_a_maintenance_page_to_a_person(tmp_path) -> None:
    from test_agent import FakeBrowser, FakeTools  # 같은 폴더의 대역

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, ollama_max_tool_steps=30)
    store = JobStore(tmp_path / "jarvis.db")
    model = _KeepsOpening()
    agent = BrowserAgent(config, model, _Down(), FakeBrowser(), FakeTools(), store, EventBus())
    # 과제에 가게 이름을 넣으면 하네스가 검색을 「그 가게 열기」(browser_open)로 바꾸는데 대역은 그 손을 모른다 —
    #   여기서 보는 것은 반복문이 점검 중을 어떻게 다루는가라서 가게 이름 없는 과제로 돌린다.
    job = store.create_job("chat", "price", {"prompt": "무선 마우스 가격을 찾아줘"})
    store.claim_next()

    result = agent.run("무선 마우스 가격을 찾아줘", job_id=job["id"], origin="chat")

    assert model.saw_note, "점검 중이라는 알림을 모델이 받지 못했다"
    assert not store.get_agent_checkpoint(job["id"]), "사람에게 넘기는 체크포인트를 만들었다"
    answer = getattr(result, "answer", None) or (result.get("answer") if isinstance(result, dict) else str(result))
    assert "점검 중" in str(answer)
