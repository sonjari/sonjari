"""사람에게 선택지로 묻고, 고른 답으로 **그 자리에서** 이어 간다 (2026-09-30).

대표: 「클로드처럼 추천 표시 단 선택지 질문을 왜 못 던지나」 — 묻는 도구가 아예 없었다.
애매하면 답 끝에 글로 묻고 판을 끝냈고, 사람이 대답하면 새 판이 처음부터 다시 돌았다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.ask_user import AskUserTool, normalize_options
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ApprovalRequired, JobStore
from alture_jarvis.tool_gateway import ToolGateway

QUESTION = {
    "question": "어떤 화면으로 만들까요?",
    "options": [
        {"label": "한 페이지", "description": "입력과 결과를 한 화면에"},
        {"label": "단계별", "description": "참가자 → 지출 → 정산 순서로"},
    ],
    "recommended": 0,
}


def _gateway(tmp_path, **kwargs) -> tuple[ToolGateway, JobStore]:
    store = JobStore(tmp_path / "j.db")
    gateway = ToolGateway(store, EventBus(), **kwargs)
    AskUserTool().register(gateway)
    return gateway, store


def test_asking_parks_the_job_with_a_card_that_carries_the_question(tmp_path) -> None:
    gateway, store = _gateway(tmp_path)
    job = store.create_job("chat", "질문", {"prompt": "정산 앱 만들어 줘"})

    with pytest.raises(ApprovalRequired) as raised:
        gateway.execute("ask_user", QUESTION, job_id=job["id"])

    card = gateway.describe_approval(store.get_approval(raised.value.nonce))
    assert card["tool_name"] == "ask_user"
    assert card["target"]["question"] == "어떤 화면으로 만들까요?"
    assert [option["label"] for option in card["target"]["options"]] == ["한 페이지", "단계별"]
    assert card["target"]["recommended"] == 0


def test_the_chosen_answer_comes_back_to_the_model_on_replay(tmp_path) -> None:
    gateway, store = _gateway(tmp_path)
    job = store.create_job("chat", "질문", {"prompt": "정산 앱 만들어 줘"})
    with pytest.raises(ApprovalRequired) as raised:
        gateway.execute("ask_user", QUESTION, job_id=job["id"])

    store.decide_approval(raised.value.nonce, True, "단계별")
    assert store.get_job(job["id"])["status"] == "queued", "답하면 잡이 다시 줄에 서야 한다"
    # 재개는 체크포인트의 호출을 그대로 재생한다.
    result = gateway.execute("ask_user", QUESTION, job_id=job["id"])

    assert result.ok is True
    assert result.result["answer"] == "단계별"
    assert result.result["free_text"] is False


def test_a_typed_answer_is_passed_through_as_free_text(tmp_path) -> None:
    gateway, store = _gateway(tmp_path)
    job = store.create_job("chat", "질문", {"prompt": "정산 앱 만들어 줘"})
    with pytest.raises(ApprovalRequired) as raised:
        gateway.execute("ask_user", QUESTION, job_id=job["id"])

    store.decide_approval(raised.value.nonce, True, "둘 다 말고 표 하나로")
    result = gateway.execute("ask_user", QUESTION, job_id=job["id"])

    assert result.result["answer"] == "둘 다 말고 표 하나로"
    assert result.result["free_text"] is True


def test_a_question_without_choices_never_parks_the_job(tmp_path) -> None:
    """사람이 답할 수 없는 카드로 30분 멈추지 않는다 — 모델에게 고칠 말을 돌려준다."""
    gateway, store = _gateway(tmp_path)
    job = store.create_job("chat", "질문", {"prompt": "정산 앱 만들어 줘"})

    result = gateway.execute("ask_user", {"question": "어떻게 할까요?", "options": ["네"]}, job_id=job["id"])

    assert result.ok is False
    assert "options_required" in str(result.error)
    assert store.list_approvals(10, "") == []


def test_no_permission_mode_answers_for_the_person(tmp_path) -> None:
    """「권한 무시」·자동 승인에서도 질문은 사람이 답한다."""
    gateway, store = _gateway(tmp_path, auto_approve_all=True, auto_approve_reversible=True)
    job = store.create_job("chat", "질문", {"prompt": "정산 앱 만들어 줘"})

    with pytest.raises(ApprovalRequired):
        gateway.execute("ask_user", QUESTION, job_id=job["id"])


def test_options_accept_plain_strings_and_drop_duplicates() -> None:
    assert normalize_options(["가", "나", "가", "", 3, "다", "라", "마"]) == [
        {"label": "가", "description": ""},
        {"label": "나", "description": ""},
        {"label": "다", "description": ""},
        {"label": "라", "description": ""},
    ]


def test_the_tool_is_wired_where_tools_get_used() -> None:
    """만든 날 세 곳 다 — 게이트웨이 등록 · 에이전트 카탈로그 · 코드 모드 프로필(소스에서 확인)."""
    import inspect

    from alture_jarvis import code_runtime, runtime

    source = inspect.getsource(runtime)
    assert "self.ask_user.register(self.gateway)" in source
    assert "            self.ask_user,\n" in source
    assert "ask_user" in code_runtime.CODE_CORE_TOOL_NAMES


def test_the_host_chat_is_told_the_question_not_just_that_something_waits() -> None:
    """바깥 Claude 가 맡긴 일이면 「승인 카드가 떠 있다」가 아니라 **무엇을 묻는지**를 전한다."""
    from alture_jarvis.delegation import summarize_job

    card = {"tool_name": "ask_user", "target": AskUserTool.describe(QUESTION)}
    summary = summarize_job({"id": "j1", "status": "waiting_approval"}, pending_approval=card)

    assert summary["status"] == "needs_approval"
    assert summary["question"] == {"question": "어떤 화면으로 만들까요?",
                                   "options": ["한 페이지", "단계별"], "recommended": "한 페이지"}
    assert "어떤 화면으로 만들까요?" in summary["message"]
    assert "대신 고르지 마세요" in summary["message"]
