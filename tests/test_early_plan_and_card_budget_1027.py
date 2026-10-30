"""코드 모드 첫 반응을 빠르게 — 요구 목록을 저장소 지도보다 먼저 보이고, 지도 만들기에 더 짧은 시간 상한을 둔다 (2026-10-27 그룹장 실사용).

## 무엇이 있었나

「계획 세우기까지 오래 걸린다 — 먼저 빠르게 이렇게 하겠다를 보여 주고 진행하면 좋겠다」. 요구 목록(화면의 「처음에 나눈 일」)은 문장에서
뽑는 순수 계산인데, 판은 모델에게 질문을 보이기 전에 저장소 지도(증분 색인)를 먼저 만들었고 요구 목록은 그 **뒤에야** 나갔다.

## 잰 값 (CPU 만 · 이 PC · `C:/work/monorepo` 훑은 파일 13,466개 · 코드 파일 6,122개 — 이 시험이 아니라 측정 스크립트로)

처음 색인 31.2~32.2초(초당 코드 파일 약 195개) · 바뀐 것 없는 증분 0.9초 · 지도 카드 1.5초. 따라잡을 게 없으면 상한은 안 닿는다.
처음 보는 큰 저장소의 앞단 상한을 45초 → 15초(`CodeIndex.CARD_BUDGET_SEC`)로 줄였다. 코드 품질에 주는 영향은 이날 못 쟀다.

## 여기서 지키는 것

1. 요구 목록은 지도 만들기보다 **먼저** 나간다(`agent_plan` 이벤트의 순서). 뒤에서 다시 뽑은 목록이 같으면 다시 안 쏜다.
2. 판 앞단의 지도는 `CARD_BUDGET_SEC` 로 끊고, 도구가 부르는 색인(`REFRESH_BUDGET_SEC`)은 그대로다.
3. 시간 상한에 걸려 부분 색인이어도 지도 카드는 선다 — 지도를 쓰는 다른 자리가 깨지지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.code_index import CodeIndex
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import ToolResult

_TOOLS = frozenset({
    "local_read_text_file", "local_index_codebase", "local_preview_page",
    "local_write_file", "local_apply_edit", "local_delete_file",
    "local_run_project_command", "browser_open", "browser_read",
})


class _Gateway:
    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, name, arguments, *, job_id=""):
        path = str(self.root / "index.html")
        if name == "local_write_file":
            (self.root / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
            return ToolResult(True, name, result={"action": name, "path": path, "verified": True, "created": True})
        if name == "local_run_project_command":
            return ToolResult(True, name, result={
                "action": name, "command": "python verify.py", "exit_code": 0, "stdout": "ok", "verified": True,
            })
        return ToolResult(True, name, result={"action": name, "path": path, "text": "x"})


def _call(name: str, **arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _call("local_write_file", path="index.html", content="<h1>x</h1>")
        if self.calls == 2:
            return _call("local_run_project_command", command="python verify.py")
        return {"role": "assistant", "content": "만들었고 검증했습니다."}


def _run(tmp_path: Path, *, slow_card_sec: float = 0.0) -> tuple[BrowserAgent, dict[str, Any]]:
    seen: dict[str, Any] = {}
    store = JobStore(tmp_path / "jarvis.db")
    events = EventBus()

    class _Tools:
        names = set(_TOOLS)
        ollama_tools = [
            {"type": "function", "function": {"name": name, "description": name,
                                              "parameters": {"type": "object", "properties": {}}}}
            for name in sorted(_TOOLS)
        ]

        def authorize_code_workspace(self, job_id, root):
            pass

        def repo_card(self, root, query="", on_progress=None):
            # 지도를 만드는 중 — 이 시점까지 나간 이벤트와, 이 일이 끝난 시각의 순서 번호를 적어 둔다.
            seen["events_before_card"] = [e.event for e in events.get_since(0, 500)]
            seen["seq_at_card"] = events.sequence
            return "[저장소 지도] 참조가 많은 순.\n  index.html — 첫 화면"

    class _Browser:
        def status(self):
            return {"started": True}

    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, agent_stream_enabled=False,
    )
    agent = BrowserAgent(config, _Model(), _Gateway(tmp_path), _Browser(), _Tools(), store, events)
    prompt = "index.html 파일을 만들어서 저장해줘"
    job = store.create_job("chat", "만들어줘", {"prompt": prompt})
    store.claim_next()
    agent.run(
        prompt, job_id=job["id"], origin="chat", model_role="code",
        require_sandbox=True, required_local_root=str(tmp_path), auto_continue_budget=True,
        # 사람이 저장소를 열고 시킨 코드 판 — 「저장소 보고 오기」가 확실한 요구(firm)로 선다.
        must_observe=True, observe_reasons=frozenset({"workspace"}), code_mode=True,
    )
    return agent, seen


def test_the_requirement_list_goes_out_before_the_repository_map(tmp_path: Path) -> None:
    agent, seen = _run(tmp_path)

    assert "events_before_card" in seen, "지도 만들기가 불리지 않았다"
    assert "agent_plan" in seen["events_before_card"], seen["events_before_card"]  # 지도를 만들기 시작할 때 이미 나가 있다
    plans = [e for e in agent.events.get_since(0, 500) if e.event == "agent_plan"]
    assert plans and plans[0].seq < seen["seq_at_card"]
    assert plans[0].payload["total"] >= 1 and plans[0].payload["met"] == 0  # 아직 아무것도 안 채운 체크리스트


def test_an_identical_list_is_not_sent_twice_at_the_start(tmp_path: Path) -> None:
    """뒤에서 다시 뽑은 첫 목록이 미리 낸 것과 같으면 다시 안 쏜다 — 처음 두 `agent_plan` 은 다른 모양(채워진 정도)이어야 한다."""
    agent, _seen = _run(tmp_path)

    plans = [e.payload for e in agent.events.get_since(0, 500) if e.event == "agent_plan"]
    signatures = [[(item["kind"], item["label"], item["met"]) for item in plan["items"]] for plan in plans]
    assert all(a != b for a, b in zip(signatures, signatures[1:])), signatures


def test_the_card_before_the_model_has_a_shorter_cap_than_the_tool(tmp_path: Path) -> None:
    assert CodeIndex.CARD_BUDGET_SEC < CodeIndex.REFRESH_BUDGET_SEC
    assert CodeIndex.CARD_BUDGET_SEC == 15.0

    budgets: list[float | None] = []

    class _Index:
        CARD_BUDGET_SEC = CodeIndex.CARD_BUDGET_SEC
        REFRESH_BUDGET_SEC = CodeIndex.REFRESH_BUDGET_SEC

        def _reused_backlog(self, root):
            return None

        def refresh(self, root, *, on_progress=None, budget_sec=None, **_):
            budgets.append(budget_sec)

        def repo_card(self, root, query=""):
            return "[저장소 지도]"

    class _Fake:
        code_index = _Index()

        def _resolve(self, root, must_exist=True):
            return tmp_path

    assert LocalComputerTools.repo_card(_Fake(), str(tmp_path), "질문") == "[저장소 지도]"
    assert budgets == [CodeIndex.CARD_BUDGET_SEC]


def test_a_partial_index_still_makes_a_map_and_says_it_stopped(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for number in range(120):
        (root / f"mod_{number}.py").write_text(f'"""모듈 {number}."""\n\ndef f_{number}():\n    return {number}\n', encoding="utf-8")
    index = CodeIndex(tmp_path / "idx")

    stats = index.refresh(root, budget_sec=0.0)  # 상한이 바로 닿는다 — 새로 읽은 파일이 하나는 있어야 멈춘다

    assert stats["stopped"] == "time" and 0 < stats["updated_files"] < 120
    assert index.last_refresh["stopped"] == "time"
    # 부분 색인이어도 지도는 선다 — 판의 다른 자리(진행 줄 · 판 기록 · 시스템 글)가 이 카드를 그대로 쓴다.
    card = index.repo_card(root, "모듈")
    assert card.startswith("[저장소 지도]") or card.startswith("[")
