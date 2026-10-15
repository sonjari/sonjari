"""걸음을 다 써서 접힌 판의 **마무리 답**도 파일로 옮긴다 · 표 뒤의 맺음말은 계획문이 아니다 (2026-10-06).

「답을 파일로 옮기기」 안전망은 루프 안에서 모델이 답을 냈을 때만 돌았다. 걸음·시간을 다 써서 접힌 판은 답이 루프 밖의
정리에서 만들어져 한 번도 안 걸렸다 — 그런데 그 정리 지시가 「확인한 내용을 표로 답에 담고, 파일은 만들지 못했다고
밝혀라」다. 표는 답에 있고 파일만 없는 판을 우리가 만들고 있었다.

운영 21일: 산출물이 끝내 안 나온 25판 중 10판이 이 모양(마무리 답을 판정에 넣으면 옮길 수 있다),
「계획문」으로 물러난 2판은 둘 다 표 **뒤**의 맺음말 한 줄 때문이었다.
"""

from __future__ import annotations

from alture_jarvis.agent import _ARTIFACT_FALLBACK_TOOL, _EXTRACT_TOOL, BrowserAgent, _forced_artifact_decision
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult

OPEN = "browser_open"


class _Artifact:
    kind = "artifact"
    label = "실제 산출물 파일 만들기"


UNMET = [(_Artifact(), False, "열 수 있는 산출물 없음")]
XLSX_PROMPT = "국내 AI 에이전트 제품을 찾아서 제품명·만든 곳·가격 표를 엑셀로 만들어줘"

TABLE_THEN_OFFER = """확인한 근거로 다시 정리했습니다.

## 확인한 제품 표

| 제품명 | 만든 곳 | 가격 |
|---|---|---|
| 가나 에이전트 | 가나소프트 | 무료 |
| 다라 비서 | 다라랩 | 월 9,900원 |

## 하지 못한 것

- 엑셀 파일 작성: 이 판에서 산출물 파일을 만들지 못했습니다.

필요하시면 기사를 더 읽고, 확인한 제품으로 파일을 만들어 드리겠습니다.
"""

OFFER_ONLY = """두 곳을 읽고 요건을 분석했습니다.

### 분석한 것

- 가나소프트는 무료 요금제가 있고, 팀 요금제는 문의해야 한다고 적혀 있습니다.
- 다라랩은 월 요금제만 있고, 연 결제 할인은 페이지에서 확인하지 못했습니다.
- 두 곳 모두 윈도우용 설치 파일을 제공하며, 맥용은 준비 중이라고 안내합니다.
- 문서 파일을 직접 만들어 주는지는 가나소프트만 명시했고 다라랩은 언급이 없습니다.

필요하시면 이 내용을 바탕으로 비교표를 작성해 드리겠습니다.
"""


def test_a_closing_offer_after_a_real_table_does_not_block_the_file() -> None:
    call, reason = _forced_artifact_decision(UNMET, [], TABLE_THEN_OFFER, XLSX_PROMPT)

    assert reason == ""
    assert call is not None and call[0] == _ARTIFACT_FALLBACK_TOOL
    assert call[1]["path"].endswith(".xlsx")
    tables = [block for block in call[1]["blocks"] if block.get("type") == "table"]
    assert len(tables) == 1 and len(tables[0]["rows"]) == 3


def test_the_closing_offer_stays_out_of_the_file() -> None:
    call, _reason = _forced_artifact_decision(UNMET, [], TABLE_THEN_OFFER, XLSX_PROMPT)
    texts = " ".join(str(block.get("text") or "") for block in call[1]["blocks"] if block.get("type") != "table")

    assert "만들어 드리겠습니다" not in texts


def test_an_offer_with_no_table_is_still_a_plan() -> None:
    """거꾸로 — 값이 든 표가 없으면 예고는 여전히 계획문이다."""
    call, reason = _forced_artifact_decision(UNMET, [], OFFER_ONLY, XLSX_PROMPT)

    assert call is None
    assert reason == "answer_is_a_plan"


# ── 실제 루프에서: 걸음을 다 쓰고 접힌 판 ────────────────────────────────────


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names = {OPEN, _EXTRACT_TOOL, _ARTIFACT_FALLBACK_TOOL}
    ollama_tools = [
        {"type": "function", "function": {"name": OPEN, "description": "open",
                                          "parameters": {"type": "object", "properties": {}}}},
    ]


class _Gateway:
    def __init__(self, *, write_ok: bool = True) -> None:
        self.showing = ""
        self.calls: list[tuple[str, dict]] = []
        self.write_ok = write_ok

    def execute(self, name, arguments, *, job_id=""):
        self.calls.append((name, dict(arguments)))
        if name == OPEN:
            self.showing = str(arguments.get("url") or "")
            return ToolResult(True, name, result={"url": self.showing, "title": "제품 소개"})
        if name == _EXTRACT_TOOL:
            return ToolResult(True, name, result={
                "url": self.showing, "title": "제품 소개",
                "text": "가나 에이전트는 가나소프트가 만든 제품이고 무료입니다. 다라 비서는 다라랩이 만들었고 유료입니다. " * 8,
            })
        if name == _ARTIFACT_FALLBACK_TOOL:
            if not self.write_ok:
                return ToolResult(False, name, error="disk_full")
            return ToolResult(True, name, result={"path": str(arguments.get("path") or ""), "action": "written"})
        return ToolResult(True, name, result={})


CLOSING_ANSWER = """확인한 것을 정리했습니다.

## 확인한 제품 표

| 제품명 | 만든 곳 | 가격 |
|---|---|---|
| 가나 에이전트 | 가나소프트 | 무료 |
| 다라 비서 | 다라랩 | 유료 |

## 확인하지 못한 것

- 다라 비서의 정확한 월 요금은 읽은 페이지에 적혀 있지 않았습니다.
- 두 제품의 출시 시기는 어느 페이지에서도 확인하지 못했습니다.
- 세 번째 제품은 찾지 못했습니다. 읽은 곳은 모두 위 두 제품만 다뤘습니다.

파일은 만들지 못했습니다.
"""


class _ReadsUntilCutOffThenTabulates:
    """도구가 있으면 계속 새 페이지를 열어 읽고(파일은 안 만든다), 도구 없이 정리하라면 표로 답한다."""

    def __init__(self, closing: str = CLOSING_ANSWER) -> None:
        self.turns = 0
        self.closing = closing

    def chat_messages(self, messages, **kwargs):
        self.turns += 1
        if kwargs.get("tools"):
            page = f"https://example.com/p{self.turns}"
            return {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": OPEN, "arguments": {"url": page}}},
                {"function": {"name": _EXTRACT_TOOL, "arguments": {}}},
            ]}
        return {"role": "assistant", "content": self.closing}


def _run(tmp_path, gateway: _Gateway, model=None):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    agent = BrowserAgent(config, model or _ReadsUntilCutOffThenTabulates(), gateway, _Browser(), _Tools(), store, EventBus())
    prompt = "example.com 에서 AI 에이전트 제품 2개를 찾아 제품명·만든 곳·가격 표를 엑셀로 만들어줘"
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()
    return agent.run(prompt, job_id=job["id"], origin="chat")


def _writes(gateway: _Gateway) -> list[dict]:
    return [arguments for name, arguments in gateway.calls if name == _ARTIFACT_FALLBACK_TOOL]


def test_a_job_that_ran_out_of_steps_still_gets_its_table_as_a_file(tmp_path) -> None:
    gateway = _Gateway()

    result = _run(tmp_path, gateway)

    writes = _writes(gateway)
    assert len(writes) == 1, [name for name, _ in gateway.calls]
    assert writes[0]["path"].endswith(".xlsx")
    table = next(block for block in writes[0]["blocks"] if block.get("type") == "table")
    assert [row[0] for row in table["rows"][1:]] == ["가나 에이전트", "다라 비서"], "답의 표 그대로 — 더하지도 빼지도 않는다"
    assert result.steps[-1]["tool"] == _ARTIFACT_FALLBACK_TOOL and result.steps[-1]["ok"], "걸음 기록에 남아야 「만든 파일」에 뜬다"
    assert "📄 답의 표를 파일로 옮겨 저장했습니다" in result.answer


def test_the_note_is_not_added_when_the_write_fails(tmp_path) -> None:
    gateway = _Gateway(write_ok=False)

    result = _run(tmp_path, gateway)

    assert len(_writes(gateway)) == 1, "한 번만 해 본다"
    assert "📄" not in result.answer


def test_a_closing_answer_with_no_table_makes_no_file(tmp_path) -> None:
    gateway = _Gateway()

    _run(tmp_path, gateway, _ReadsUntilCutOffThenTabulates("읽은 두 곳 모두 가격을 적지 않았습니다. 표로 만들 값이 없습니다. " * 6))

    assert _writes(gateway) == []
