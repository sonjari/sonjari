"""이어오기 인계 방향이 **계약으로** 실리는가 (W0, 2026-09-15).

이름 바꾼 앱 E2E 에서 캡슐의 「남은 일만 정리하기」(실행하지 않고 체크리스트)를 골랐는데
첫 턴이 239.5초·19걸음을 돌고 `작업_현황_보고서.docx` 를 만들었다. 오른쪽 칸은
「시킨 것 0/2: 직접 계산해 보기 · 실제 산출물 파일 만들기」.

원인은 계획 층이 **긴 인계문 전체**에서 요구를 뽑은 것이다. 카드 안의 할 일(「부가세 계산
확인」)과 `resume_prompt` 의 규칙 문장이 계산·산출물 요구로 걸렸다. 사람이 고른 방향은
어디에도 안 실렸다.

고친 모양: 방향은 잡의 필드(`handoff_direction`)로 싣고, 요구는 사람에게 보인 문장 + 방향
한 줄에서만 뽑는다. review·tasks 는 읽기 전용이다. **양방향**으로 본다 — 인계문 속 낱말이
과제를 만들지 않아야 하고, continue 는 여전히 일해야 한다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.api import ChatRequest
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult
from alture_jarvis.plan import extract
from alture_jarvis.takeover import (
    READ_ONLY_HANDOFF_DIRECTIONS,
    handoff_contract,
    handoff_instruction,
    resume_prompt,
)

# E2E 합성 로그와 같은 모양의 카드. 할 일 문구에 계산·검증·엑셀이 들어 있다.
CARD: dict[str, Any] = {
    "tool_name": "Claude Code",
    "cwd": "C:/work/tax",
    "first_request": "부가세 신고 자료 정리해줘",
    "last_request": "부가세 계산 확인하고 엑셀로 정리해줘",
    "last_reply": "계산을 검증하고 표를 만들겠습니다.",
    "open_tasks": ["부가세 계산 확인", "검증"],
    "files": ["C:/work/tax/vat.xlsx"],
}
SHOWN = {
    "continue": "Claude Code에서 멈춘 「부가세 신고」을 멈춘 자리부터 이어서 해줘",
    "review": "Claude Code에서 멈춘 「부가세 신고」을 먼저 검토해줘",
    "tasks": "Claude Code에서 멈춘 「부가세 신고」을 남은 일로 정리해줘",
}


def _handoff_prompt(direction: str) -> str:
    return (
        f"Claude Code에서 이어온 작업 · 부가세 신고\n\n{resume_prompt(CARD)}\n\n"
        f"[사용자가 고른 이어가기 방식]\n{handoff_instruction(direction)}\n\n"
        "지금은 Cowork 선공개 모드다."
    )


def test_the_long_handoff_text_itself_still_manufactures_tasks() -> None:
    """고장이 재현되는지 먼저 본다 — 이게 안 걸리면 아래 시험은 아무것도 증명하지 않는다."""
    kinds = {item.kind for item in extract(_handoff_prompt("tasks"))}
    assert "artifact" in kinds


def test_contract_text_comes_from_the_visible_sentence_and_direction() -> None:
    for direction in ("continue", "review", "tasks"):
        text, read_only = handoff_contract(direction, SHOWN[direction])  # type: ignore[misc]
        assert text.startswith(SHOWN[direction])
        assert handoff_instruction(direction) in text
        assert "부가세 계산 확인" not in text  # 카드의 할 일은 요구 문장에 안 들어간다
        assert read_only is (direction in READ_ONLY_HANDOFF_DIRECTIONS)
        assert {item.kind for item in extract(text)} & {"artifact", "action", "verify"} == set()


def test_read_only_directions_do_not_carry_the_fix_and_test_rules() -> None:
    """W0 라이브 1회차: 계약은 지켰지만 인계문의 「git diff 로 읽고·시험을 돌려」 규칙대로 명령부터 돌렸다."""
    for direction in ("tasks", "review"):
        text = resume_prompt(CARD, direction=direction)
        assert "git diff" not in text and "시험을 돌려" not in text
        assert "고치지 않" in text
        assert CARD["last_request"] in text  # 카드 사실은 그대로 옮긴다
    # ★ 이어서 하는 판의 규칙은 **그 일의 모양**을 따른다 (2026-09-16). 저장소면 git·시험,
    #   아니면 기록 읽기 + 「끝까지 해낸다」. 조사 과제에 코드 세션 규칙을 줬더니 모델이
    #   그 틀대로 「최종 보고」를 쓰고 예산 절반을 남긴 채 멈췄다.
    research = resume_prompt(CARD, direction="continue")
    assert "git diff" not in research
    assert "끝까지 해낸다" in research
    in_repo = resume_prompt({**CARD, "git": {"root": "C:/work/tax"}}, direction="continue")
    assert "git diff" in in_repo and "시험을 돌려" in in_repo


def test_custom_direction_uses_only_what_the_person_typed() -> None:
    text, read_only = handoff_contract("custom", "Claude Code에서 멈춘 작업을 이어서 해줘. 표로 엑셀 파일 만들어줘")  # type: ignore[misc]
    assert read_only is False
    # 사람이 직접 파일을 시켰으면 그건 진짜 요구다.
    assert "artifact" in {item.kind for item in extract(text)}


def test_ordinary_chat_is_not_a_handoff() -> None:
    assert handoff_contract("", "안녕") is None
    assert handoff_contract("tasks", "") is None
    assert handoff_contract("launch", "안녕") is None
    assert handoff_instruction("custom", "   ") == ""


def test_chat_request_accepts_the_direction_and_defaults_to_none() -> None:
    assert ChatRequest(prompt="안녕").handoff_direction == ""
    assert ChatRequest(prompt="긴 인계문", display_prompt="정리해줘", handoff_direction="tasks").model_dump()[
        "handoff_direction"
    ] == "tasks"


# ── 에이전트 층 ────────────────────────────────────────────────────────────


class _Browser:
    def status(self):
        return {"started": True}

    def forget_results(self):
        return None

    def set_requested_stay(self, _prompt):
        return None


def _fn(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": name,
                                             "parameters": {"type": "object", "properties": {}}}}


class _Tools:
    names = {"local_read_text_file", "local_write_document", "sandbox_run"}
    ollama_tools = [_fn("local_read_text_file"), _fn("local_write_document"), _fn("sandbox_run")]


class _Gateway:
    def execute(self, name, arguments, *, job_id=""):
        return ToolResult(True, name, result={"text": "ok"})


class _Ollama:
    """도구를 부르지 않고 체크리스트로 바로 답한다. 받은 도구 이름을 적어 둔다."""

    def __init__(self) -> None:
        self.offered: list[set[str]] = []

    def chat_messages(self, messages, **kwargs):
        self.offered.append({str((t.get("function") or {}).get("name")) for t in kwargs.get("tools") or []})
        return {"role": "assistant", "content": "남은 일 체크리스트\n1. 부가세 계산 확인\n2. 검증"}


def _agent(tmp_path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    ollama = _Ollama()
    agent = BrowserAgent(config, ollama, _Gateway(), _Browser(), _Tools(), store, EventBus())
    return agent, store, ollama


def _run(tmp_path, direction: str, *, contract: bool):
    agent, store, ollama = _agent(tmp_path)
    prompt = _handoff_prompt(direction)
    job = store.create_job("chat", "handoff", {"prompt": prompt})
    store.claim_next()
    kwargs: dict[str, Any] = {}
    if contract:
        text, read_only = handoff_contract(direction, SHOWN[direction])  # type: ignore[misc]
        kwargs = {"plan_prompt": text, "read_only": read_only}
    result = agent.run(prompt, job_id=job["id"], origin="workspace", **kwargs)
    return result, ollama


def test_tasks_handoff_has_no_computation_or_file_task_and_no_write_hands(tmp_path) -> None:
    result, ollama = _run(tmp_path, "tasks", contract=True)
    kinds = {item["kind"] for item in (result.plan or {}).get("items", [])}
    assert kinds & {"artifact", "action", "verify", "footnote", "count_action"} == set()
    assert result.steps == []
    # ★ 2026-09-30: 읽기 전용이어도 **목록은 같게** 보낸다(도구 목록이 프롬프트 맨 앞이라, 빼면 판마다 1만 5천 토큰을 다시
    #   읽었다). 쓰기는 디스패치가 같은 이름표로 되돌려 보낸다 — 여기서는 그 이름표에 쓰기 손이 있는지를 본다.
    from alture_jarvis.agent import _READ_ONLY_FORBIDDEN_TOOLS

    assert ollama.offered and "local_read_text_file" in ollama.offered[0]
    assert {"local_write_document", "sandbox_run"} <= _READ_ONLY_FORBIDDEN_TOOLS


def test_without_the_contract_the_same_text_still_demands_a_file(tmp_path) -> None:
    """반대쪽 표본 — 계약이 없으면 같은 인계문이 여전히 파일 과제를 만든다(고친 자리가 계약임을 확인)."""
    result, _ = _run(tmp_path, "tasks", contract=False)
    kinds = {item["kind"] for item in (result.plan or {}).get("items", [])}
    assert "artifact" in kinds


def test_continue_handoff_keeps_its_hands(tmp_path) -> None:
    """continue 는 여전히 일한다 — 쓰기 손을 빼지 않는다."""
    _result, ollama = _run(tmp_path, "continue", contract=True)
    assert ollama.offered and "local_write_document" in ollama.offered[0]


def test_continue_carries_the_original_request_but_read_only_does_not() -> None:
    """★ 2026-09-16 이어받기 3판: 요구가 0개라 되받기도 완료 판정도 통째로 죽었다.

    보이는 문장에는 개수도 산출물도 없다. 「마지막 요청」 한 줄을 이어서 **하는** 방향에만 붙인다.
    양방향으로 본다 — 붙였으니 요구가 서야 하고, 읽기 전용에는 여전히 안 서야 한다.
    """
    handoff_text = resume_prompt(CARD, direction="continue")
    text, read_only = handoff_contract("continue", SHOWN["continue"], handoff_text)  # type: ignore[misc]
    assert read_only is False
    assert CARD["last_request"] in text
    assert {item.kind for item in extract(text)} & {"artifact", "count"}
    # 카드의 할 일 목록은 여전히 요구가 아니다 — W0 에서 그것이 계산·파일 과제로 둔갑했다.
    # (「부가세 계산 확인」은 마지막 요청의 부분 문자열이라 판별에 못 쓴다 — 「검증」으로 본다.)
    assert "검증" not in text

    for direction in ("tasks", "review"):
        quiet, quiet_read_only = handoff_contract(direction, SHOWN[direction], handoff_text)  # type: ignore[misc]
        assert quiet_read_only is True
        assert CARD["last_request"] not in quiet
        assert {item.kind for item in extract(quiet)} & {"artifact", "action", "verify"} == set()


def test_handoff_file_list_is_absolute_and_drops_backup_noise() -> None:
    """★ 목록 15줄 중 14줄이 백업 사본이었고, 붙인 경로는 겹쳐서 없는 파일이 됐다(2026-09-16)."""
    card = {
        **CARD,
        "cwd": "C:/work/tax/report",
        "git": {"root": "C:/work/tax"},
        "files": ["notes.md"] + [f"backups/old_{n}/copy.py" for n in range(14)],
    }
    text = resume_prompt(card, direction="continue")
    assert "backups" not in text
    # 저장소 뿌리 기준으로 붙인다 — cwd 에 붙이면 `report/notes.md` 로 엉뚱한 자리를 가리킨다.
    assert "notes.md" in text
    assert "C:/work/tax/report/notes.md" not in text.replace("\\", "/")
