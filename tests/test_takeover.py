"""이어받기 (전략안 §44) — 멈춤 판정 · 카드 · 증거×의도 · 가지에서 이어 작업.

기록 파일은 2026-09-14 가람 PC 에서 **구조만** 관찰한 모양을 따라 지어낸 가짜다(내용은 가공).
가짜 비밀은 실행 중에 조립한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.takeover import (
    TakeoverService,
    build_card,
    git_state,
    parse_label,
    read_claude_session,
    read_codex_session,
    recent_sessions,
    resume_prompt,
)

FAKE_KEY = "sk-" + "ant-api03-" + "Zq8Lm3Tx6Vb1Nc4Hy7Wd2Js5Ge9Kf0Ra" + "Pp33Qq44"
NOW = 1_780_000_000.0


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(epoch))


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8") + b"\n")
    return path


def _claude_rows(cwd: str, *, stop: str = "rate_limit", at: float = NOW - 300) -> list[dict]:
    base = {"sessionId": "s-1", "cwd": cwd}
    rows = [
        {**base, "type": "custom-title", "customTitle": "결제 모듈 리팩터링"},
        {**base, "type": "user", "timestamp": _iso(at - 900), "message": {"role": "user", "content": "결제 모듈을 나눠 줘"}},
        {**base, "type": "user", "timestamp": _iso(at - 890), "message": {"role": "user", "content": "<system-reminder>무시</system-reminder>"}},
        {**base, "type": "assistant", "timestamp": _iso(at - 800), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": "모듈 분리", "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": "시험 추가", "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": f"{cwd}/pay.py", "old_string": "a", "new_string": "b"}},
            {"type": "tool_use", "name": "Write", "input": {"file_path": f"{cwd}/new_test.py", "content": "x"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": f"curl -H 'X-API-KEY: {FAKE_KEY}' http://x\nsecond", "description": ""}},
        ]}},
        {**base, "type": "assistant", "timestamp": _iso(at - 700), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "1", "status": "completed"}}]}},
        {**base, "type": "user", "timestamp": _iso(at - 600), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}},
        {**base, "type": "assistant", "timestamp": _iso(at - 500), "message": {"role": "assistant", "content": [
            {"type": "text", "text": "분리를 끝냈고 시험을 추가하겠습니다."}]}},
        {**base, "type": "user", "timestamp": _iso(at - 400), "message": {"role": "user", "content": "시험도 붙여 줘"}},
    ]
    if stop:
        rows.append({**base, "type": "assistant", "timestamp": _iso(at), "isApiErrorMessage": True, "error": stop,
                     "apiErrorStatus": 429, "message": {"role": "assistant", "content": [
                         {"type": "text", "text": "You've hit your limit · resets 6pm"}]}})
    return rows


def _codex_rows(cwd: str, *, used: float, at: float = NOW - 200) -> list[dict]:
    return [
        {"timestamp": _iso(at - 600), "type": "session_meta", "payload": {"id": "c-1", "cwd": cwd}},
        {"timestamp": _iso(at - 500), "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
        {"timestamp": _iso(at - 499), "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "로그인 버그 고쳐"}]}},
        {"timestamp": _iso(at - 400), "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": "pytest -q\nmore"}},
        {"timestamp": _iso(at), "type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": used, "window_minutes": 300, "resets_at": int(NOW + 3600)},
            "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": int(NOW + 86400)}}}},
    ]


# ── 멈춤 판정 ────────────────────────────────────────────────────────────────
def test_claude_rate_limit_is_read_from_structure_and_secrets_never_leak(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "s.jsonl", _claude_rows(str(tmp_path)))
    state = read_claude_session(path)
    assert state.stop_kind == "rate_limit" and state.title == "결제 모듈 리팩터링"
    assert state.first_request == "결제 모듈을 나눠 줘" and state.last_request == "시험도 붙여 줘"
    assert state.open_tasks == ["시험 추가"]
    card = build_card(state, {"repo": False}, now=NOW)
    assert FAKE_KEY not in json.dumps(card, ensure_ascii=False)
    assert card["recent_commands"][0].startswith("curl") and "second" not in card["recent_commands"][0]
    assert card["stopped_minutes_ago"] == 5


def test_a_session_that_ended_normally_is_not_a_stop(tmp_path: Path) -> None:
    state = read_claude_session(_write_jsonl(tmp_path / "s.jsonl", _claude_rows(str(tmp_path), stop="")))
    assert state.stop_kind == "none"


def test_a_server_error_is_not_a_usage_limit(tmp_path: Path) -> None:
    state = read_claude_session(_write_jsonl(tmp_path / "s.jsonl", _claude_rows(str(tmp_path), stop="server_error")))
    assert state.stop_kind == "api_error"


def test_codex_limit_is_the_used_percent_not_a_word(tmp_path: Path) -> None:
    hit = read_codex_session(_write_jsonl(tmp_path / "a.jsonl", _codex_rows(str(tmp_path), used=100.0)))
    assert hit.stop_kind == "rate_limit" and hit.resets_at == NOW + 3600
    assert hit.first_request == "로그인 버그 고쳐" and hit.commands == ["pytest -q"]
    fine = read_codex_session(_write_jsonl(tmp_path / "b.jsonl", _codex_rows(str(tmp_path), used=62.0)))
    assert fine.stop_kind == "none"


def test_broken_lines_are_counted_not_fatal(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "s.jsonl", _claude_rows(str(tmp_path)))
    path.write_bytes(path.read_bytes() + b"{not json\n")
    assert read_claude_session(path).unreadable_lines == 1


def test_only_the_official_log_locations_are_scanned_and_limits_rank_first(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "done.jsonl", _claude_rows("C:/w", stop=""))
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows("C:/w"))
    _write_jsonl(home / ".codex" / "sessions" / "2026" / "09" / "14" / "rollout-x.jsonl", _codex_rows("C:/w", used=100))
    _write_jsonl(home / "Documents" / "other.jsonl", _claude_rows("C:/w"))  # 목록 밖
    found = recent_sessions(home, now=time.time(), window_sec=3600)
    assert {Path(s.path).name for s in found} == {"done.jsonl", "hit.jsonl", "rollout-x.jsonl"}
    assert found[-1].stop_kind == "none"


# ── 의도 판정 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("raw", "label"), [
    ('{"intent": "takeover"}', "takeover"), ('```json\n{"intent":"not"}\n```', "not"),
    ("intent: unclear", "unclear"), ("모르겠음", "unclear"), ('{"intent": "delete everything"}', "unclear"),
])
def test_labels_are_parsed_and_unknown_is_unclear(raw: str, label: str) -> None:
    assert parse_label(raw, "intent", {"takeover", "not", "unclear"}, "unclear") == label


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")


class _Ask:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return self.answers.pop(0) if self.answers else '{"intent": "not"}'


def test_no_recent_stop_means_the_model_is_never_asked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "done.jsonl", _claude_rows("C:/w", stop="", at=time.time()))
    ask = _Ask('{"intent": "takeover"}')
    service = TakeoverService(_config(tmp_path), ask=ask, home=home)
    assert service.intercept("보고서 다 썼어", "chat-1") is None
    assert ask.calls == []  # 증거가 없으면 평소 대화는 한 글자도 안 느려진다


def test_offer_then_yes_on_a_non_repo_gives_the_resume_prompt(tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows(str(work), at=time.time() - 120))
    ask = _Ask('{"intent": "takeover"}', '{"answer": "yes"}')
    service = TakeoverService(_config(tmp_path), ask=ask, home=home)
    offer = service.intercept("아 클로드 또 막혔네", "chat-1")
    assert offer["kind"] == "offer" and "이어갈까요" in offer["answer"]
    assert "원래 대화와 작업 폴더는 건드리지 않고" in offer["answer"] and "가지" not in offer["answer"]
    accepted = service.intercept("응 해줘", "chat-1")
    assert accepted["kind"] == "card" and "마지막 요청: 시험도 붙여 줘" in accepted["answer"]
    # 같은 멈춤으로 다시 묻지 않는다.
    assert service.intercept("다 썼어", "chat-1") is None


def test_offer_publishes_a_structured_card_for_the_cowork_relay(tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    path = _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows(str(work), at=time.time() - 60))
    events: list[tuple[str, dict]] = []
    service = TakeoverService(
        _config(tmp_path), ask=_Ask('{"intent":"takeover"}'), home=home,
        publish=lambda event, payload: events.append((event, payload)),
    )

    offer = service.intercept("클로드 한도에 걸렸어", "chat-1")

    event, payload = next(row for row in events if row[0] == "takeover_offered")
    assert event == "takeover_offered"
    assert payload["takeover_id"] == offer["takeover_id"]
    assert payload["card"]["session_path"] == str(path)
    assert payload["card"]["last_request"] == "시험도 붙여 줘"


def test_prepare_cowork_makes_a_read_only_handoff_without_starting_a_branch(tmp_path: Path, repo: Path) -> None:
    home = tmp_path / "home"
    path = _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows(str(repo), at=time.time() - 60))
    submitted: list[dict] = []
    service = TakeoverService(
        _config(tmp_path), home=home,
        submit=lambda payload: submitted.append(payload) or {"id": "should-not-run"},
    )
    made = service.record_card(str(path))

    result = service.prepare_cowork(made["takeover_id"], direction="review")

    assert result["ok"] is True and result["tool_name"] == "Claude Code"
    assert "지금까지 한 일과 근거를 먼저 검토" in result["prompt"]
    assert "원래 대화와 작업 폴더를 바꾸지 말고" in result["prompt"]
    assert submitted == []
    row = service.get(made["takeover_id"])
    assert row["status"] == "card_only" and row["branch"] == "" and row["worktree"] == ""


def test_offer_answer_is_one_line_when_the_capsule_is_on_screen(tmp_path: Path) -> None:
    """캡슐이 폴더·마지막 요청을 이미 보여 주는 화면에서 채팅이 같은 목록을 또 길게 말하지 않는다."""
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows("C:/w", at=time.time() - 60))
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent":"takeover"}'), home=home)
    short = service.intercept("클로드 한도에 걸렸어", "chat-1", capsule_visible=True)
    assert short["kind"] == "offer" and "\n" not in short["answer"] and "오른쪽에서" in short["answer"]
    assert "작업 폴더" not in short["answer"]
    home2 = tmp_path / "home2"
    _write_jsonl(home2 / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows("C:/w", at=time.time() - 60))
    voice = TakeoverService(_config(tmp_path / "v"), ask=_Ask('{"intent":"takeover"}'), home=home2)
    long = voice.intercept("클로드 한도에 걸렸어", "chat-2")
    assert "작업 폴더" in long["answer"]


def test_dismissed_cowork_offer_is_not_offered_again(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows("C:/w", at=time.time() - 60))
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent":"takeover"}'), home=home)
    offer = service.intercept("한도 끝났어", "chat-1")

    assert service.dismiss(offer["takeover_id"])["ok"] is True
    assert service.get(offer["takeover_id"])["status"] == "dismissed"
    assert service.intercept("또 이어줘", "chat-1") is None


def test_declining_is_remembered(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows("C:/w", at=time.time() - 60))
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent":"takeover"}', '{"answer":"no"}'), home=home)
    service.intercept("limit 걸림", "chat-1")
    assert service.intercept("아니 괜찮아", "chat-1")["kind"] == "declined"
    assert service.intercept("limit 걸림", "chat-1") is None


def test_unclear_right_after_a_stop_is_asked_but_later_only_hinted(tmp_path: Path) -> None:
    """「다 썼네」만 말해도 방금 멈췄으면 묻는다. 멈춘 지 오래면 답 끝에 한 줄만."""
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows("C:/w", at=time.time() - 60))
    recent = TakeoverService(_config(tmp_path / "a"), ask=_Ask('{"intent":"unclear"}'), home=home)
    assert recent.intercept("다 썼네", "chat-1")["kind"] == "offer"
    home2 = tmp_path / "home2"
    _write_jsonl(home2 / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows("C:/w", at=time.time() - 45 * 60))
    later = TakeoverService(_config(tmp_path / "b"), ask=_Ask('{"intent":"unclear"}'), home=home2)
    result = later.intercept("다 썼네", "chat-1")
    assert result["kind"] == "hint" and "answer" not in result


def test_the_judge_sees_only_the_message_not_the_evidence(tmp_path: Path) -> None:
    """v1 오탐 21% 의 원인 — 증거가 판정 문장에 들어가면 평범한 요청까지 끌려간다."""
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows("C:/w", at=time.time() - 60))
    ask = _Ask('{"intent":"not"}')
    service = TakeoverService(_config(tmp_path), ask=ask, home=home)
    assert service.intercept("진행하자", "chat-1") is None
    system, prompt = ask.calls[0]
    assert "stopped" not in prompt and "usage limit" not in prompt and "진행하자" in prompt


# ── git · H2 ─────────────────────────────────────────────────────────────────
def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "pay.py").write_text("a = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "pay.py").write_text("a = 2\n", encoding="utf-8")  # 멈춘 순간의 미커밋 변경
    (root / "new_test.py").write_text("def test_x(): pass\n", encoding="utf-8")  # 대화가 만든 새 파일
    (root / "outputs").mkdir()
    (root / "outputs" / "big.log").write_text("junk\n", encoding="utf-8")  # .gitignore 밖 출력물
    return root


def test_git_state_sees_uncommitted_changes(repo: Path) -> None:
    state = git_state(str(repo))
    assert state["repo"] and state["changed_count"] == 1 and state["untracked_count"] == 2
    assert state["changed"] == ["pay.py"]
    # 사람에게 보이는 경로는 운영체제 표기다(윈도우에서 git 은 슬래시로 준다).
    assert state["root"] == os.path.normpath(state["root"])
    assert os.path.normcase(state["root"]) == os.path.normcase(os.path.realpath(repo))
    assert git_state(str(repo.parent))["repo"] is False


def test_continue_on_branch_leaves_the_users_folder_alone_and_finish_marks_review(tmp_path: Path, repo: Path) -> None:
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows(str(repo), at=time.time() - 60))
    submitted: list[dict] = []
    # ★ 2026-09-20: 가지 이어 작업은 **화면 캡슐의 단추**(`accept`)로 시작한다.
    #   채팅의 「그래」로는 시작하지 않는다 — 말 한마디에 git 가지와 잡이 생기면 안 된다
    #   (`test_saying_yes_in_chat_never_starts_a_branch` 가 그 반대쪽을 붙든다).
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          takeover_branch_enabled=True)
    service = TakeoverService(config, ask=_Ask('{"intent":"takeover"}', '{"answer":"yes"}'), home=home,
                              submit=lambda payload: submitted.append(payload) or {"id": "job-1"})
    before = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True).stdout
    offer = service.intercept("클로드 한도 끝났어", "chat-1")
    started = service.accept(int(offer["takeover_id"]))
    assert started["kind"] == "started"
    row = service.get(started["takeover_id"])
    worktree = Path(row["worktree"])
    assert (worktree / "pay.py").read_text(encoding="utf-8") == "a = 2\n"  # 미커밋 변경을 옮겼다
    assert (worktree / "new_test.py").exists()
    assert not (worktree / "outputs" / "big.log").exists()  # 쓰레기는 안 따라온다
    assert submitted[0]["workspace_mode"] == "code" and submitted[0]["code_workspace"] == str(worktree)
    assert "시험도 붙여 줘" in submitted[0]["prompt"]
    # 원래 폴더는 그대로.
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True).stdout == before
    # 자비스가 가지에서 고친 것으로 치고 마무리.
    (worktree / "pay.py").write_text("a = 3\n", encoding="utf-8")
    service.on_job_terminal({"payload": {"takeover_id": started["takeover_id"]}, "status": "completed",
                             "result": {"answer": "시험을 붙였습니다"}})
    done = service.get(started["takeover_id"])
    assert done["status"] == "review_pending" and "pay.py" in done["result"]["changed_files"]
    context = service.review_context(str(repo))
    assert row["branch"] in context and "자동으로 병합하지 마세요" in context
    assert service.review_context(str(tmp_path)) == ""
    # 버리면 가지와 작업 자리가 사라지고 원래 폴더는 그대로.
    assert service.discard(started["takeover_id"])["ok"]
    assert not worktree.exists()
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True).stdout == before


def test_a_retry_session_points_back_to_the_real_work_in_the_same_folder(tmp_path: Path) -> None:
    """한도 뒤 새 대화로 다시 해 봤다 즉시 막힌 헛시도 — 그걸 이어받으면 빈 대화를 이어받는다."""
    home = tmp_path / "home"
    now = time.time()
    _write_jsonl(home / ".claude" / "projects" / "p" / "work.jsonl", _claude_rows("C:/w", stop="", at=now - 900))
    retry = [
        {"sessionId": "r", "cwd": "C:/w", "type": "user", "timestamp": _iso(now - 70),
         "message": {"role": "user", "content": "계속"}},
        {"sessionId": "r", "cwd": "C:/w", "type": "assistant", "timestamp": _iso(now - 60), "isApiErrorMessage": True,
         "error": "rate_limit", "message": {"role": "assistant", "content": [{"type": "text", "text": "limit"}]}},
    ]
    _write_jsonl(home / ".claude" / "projects" / "p" / "retry.jsonl", retry)
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent":"takeover"}'), home=home)
    offer = service.intercept("클로드 또 다 썼어", "chat-1")
    assert offer["card"]["resumed_from_earlier_session"] is True
    assert offer["card"]["last_request"] == "시험도 붙여 줘" and offer["card"]["stopped_minutes_ago"] == 1
    assert "시험도 붙여 줘" in offer["answer"]


def test_the_job_takeover_submits_passes_the_chat_api_validation(tmp_path: Path, repo: Path) -> None:
    """제품은 enqueue 로 바로 넣어 API 검증을 건너뛴다 — 그래서 **같은 검증을 시험이 대신 건다.**

    처음엔 `origin="takeover"` 를 넣었고, 실제 시험이 422 로 드러냈다(허용 값은 chat·voice·workspace).
    """
    from alture_jarvis.api import ChatRequest

    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows(str(repo), at=time.time() - 60))
    submitted: list[dict] = []
    service = TakeoverService(_config(tmp_path), home=home,
                              submit=lambda payload: submitted.append(payload) or {"id": "job-1"})
    made = service.record_card(str(home / ".claude" / "projects" / "p" / "hit.jsonl"))
    assert service.continue_on_branch(made["takeover_id"])["ok"]
    api_fields = {k: v for k, v in submitted[0].items() if k != "takeover_id"}
    request = ChatRequest(**api_fields)
    assert request.origin == "workspace" and request.workspace_mode == "code"
    assert "speak" not in submitted[0]
    service.discard(made["takeover_id"])


def test_resume_prompt_only_carries_card_facts(tmp_path: Path) -> None:
    state = read_claude_session(_write_jsonl(tmp_path / "s.jsonl", _claude_rows(str(tmp_path))))
    text = resume_prompt(build_card(state, {"repo": False}, now=NOW))
    assert "처음 요청: 결제 모듈을 나눠 줘" in text and "시험 추가" in text and FAKE_KEY not in text


def test_saying_yes_in_chat_does_not_start_a_branch_while_code_beta_is_off(tmp_path: Path, repo: Path) -> None:
    """Cowork 선공개: 캡슐도 채팅도 인계문까지만 약속한다. H2 가지는 설정으로만 켠다."""
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows(str(repo), at=time.time() - 60))
    submitted: list[dict] = []
    service = TakeoverService(
        _config(tmp_path), ask=_Ask('{"intent": "takeover"}', '{"answer": "yes"}'), home=home,
        submit=lambda payload: submitted.append(payload) or {"id": "should-not-run"},
    )
    offer = service.intercept("클로드 한도 걸렸어", "chat-1")
    assert offer["kind"] == "offer" and "가지" not in offer["answer"]
    accepted = service.intercept("응", "chat-1")
    assert accepted["kind"] == "card" and "시험도 붙여 줘" in accepted["answer"]
    assert submitted == []
    row = service.get(offer["takeover_id"])
    assert row["branch"] == "" and row["worktree"] == ""


def test_handoff_followup_turn_still_reads_the_hidden_handoff_prompt(tmp_path: Path) -> None:
    """기록에는 보이는 짧은 문장, 다음 턴 맥락에는 인계문 원문."""
    from alture_jarvis.memory import ConversationMemory

    memory = ConversationMemory(tmp_path / "memory.sqlite3", recent_messages=4, compact_batch=2)
    handoff = "Claude Code에서 이어온 작업 · 결제\n- 마지막 요청: 시험도 붙여 줘\n- 남은 할 일: 회귀 시험"
    memory.add_exchange("s1", "Claude Code에서 멈춘 「결제」을 이어서 해줘", "이어서 보겠습니다.",
                        user_metadata={"model_prompt": handoff})
    memory.add_exchange("s1", "그럼 남은 거 뭐였지?", "회귀 시험입니다.")

    shown = [row["content"] for row in memory.history("s1")]
    assert handoff not in shown and "Claude Code에서 멈춘 「결제」을 이어서 해줘" in shown
    context = "\n".join(row["content"] for row in memory.context_messages("s1"))
    assert "마지막 요청: 시험도 붙여 줘" in context

    for index in range(3):  # 요약 대상으로 밀려나도 인계문으로 요약한다
        memory.add_exchange("s1", f"추가 질문 {index}", "답")
    candidate = memory.compaction_candidate("s1")
    assert candidate is not None
    assert any("마지막 요청: 시험도 붙여 줘" in row["content"] for row in candidate["messages"])


def test_the_handoff_names_files_with_a_full_path(tmp_path) -> None:
    """★ 2026-09-16 실측: 상대 경로로 적어 줬더니 모델이 그 이름을 그대로 파일 도구에 넣어

    `path_outside_allowed_roots` 로 첫 걸음에서 죽었다. 경로를 주는 쪽이 온전한 경로를 준다.
    """
    from alture_jarvis.takeover import resume_prompt

    card = {
        "tool_name": "Claude Code",
        "title": "여수 회계 채용 비교표",
        "cwd": str(tmp_path / "work"),
        "files": ["notes.md", str(tmp_path / "work" / "already_absolute.md")],
        "open_tasks": ["공고 3개 찾기"],
        "first_request": "공고 3개 찾아 엑셀로",
        "last_request": "공고 3개 찾아 엑셀로",
    }

    text = resume_prompt(card, direction="continue")

    assert str(tmp_path / "work" / "notes.md") in text
    assert text.count(str(tmp_path / "work" / "already_absolute.md")) == 1


# ── 멈춘 기록이 없는데 사람이 직접 「이어받자」고 했다 (2026-10-05 밤, 대표 실사용) ──────────────
#
# 「클로드 한도걸렸어..」·「코덱스 한도걸렸어 이어받자」가 한 글자도 안 읽히고 평소 대화로 넘어가 엉뚱한 잡담이 나왔다.
# 최근 3시간 안에 한도로 멈춘 기록이 없었기 때문이다(실제로 안 걸렸다). 기능을 한 번 쳐 보는 사람이 정확히 이 길로 온다.


def test_saying_it_without_a_recent_stop_is_not_silently_dropped(tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    _write_jsonl(home / ".claude" / "projects" / "p" / "done.jsonl", _claude_rows(str(work), stop="", at=time.time() - 240))
    events: list[tuple[str, dict]] = []
    ask = _Ask('{"intent": "takeover"}', '{"answer": "yes"}')
    service = TakeoverService(_config(tmp_path), ask=ask, home=home, publish=lambda e, p: events.append((e, p)))

    offer = service.intercept("클로드 한도걸렸어..", "chat-1")

    assert offer and offer["kind"] == "offer"
    # 없는 멈춤을 지어내지 않는다 — 못 찾았다고 말하고, 가장 최근에 하던 대화를 내민다.
    assert "한도로 멈춘 기록은 찾지 못했습니다" in offer["answer"] and "결제 모듈 리팩터링" in offer["answer"]
    assert "멈췄습니다" not in offer["answer"]
    card = next(p for e, p in events if e == "takeover_offered")["card"]
    assert card["stop_kind"] == "none" and card["last_request"] == "시험도 붙여 줘"
    assert len(ask.calls) == 1
    # 그 뒤는 평소 이어받기와 같다.
    accepted = service.intercept("응 해줘", "chat-1")
    assert accepted["kind"] == "card" and "마지막 요청: 시험도 붙여 줘" in accepted["answer"]


def test_that_offer_is_one_line_when_the_capsule_is_on_screen(tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    _write_jsonl(home / ".claude" / "projects" / "p" / "done.jsonl", _claude_rows(str(work), stop="", at=time.time() - 240))
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent": "takeover"}'), home=home)
    offer = service.intercept("클로드 한도걸렸어..", "chat-1", capsule_visible=True)
    assert "\n" not in offer["answer"] and "오른쪽에서 방법을" in offer["answer"]


def test_an_ordinary_sentence_about_limits_goes_on_as_usual(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "p" / "done.jsonl", _claude_rows("C:/w", stop="", at=time.time() - 240))
    ask = _Ask('{"intent": "not"}')
    service = TakeoverService(_config(tmp_path), ask=ask, home=home)
    assert service.intercept("카드 한도 얼마까지 올릴 수 있는지 조사해줘", "chat-1") is None
    assert len(ask.calls) == 1  # 물어는 보되, 모델이 아니라고 하면 평소 대화다
    # 한도·이어받기 이야기가 아닌 말은 여전히 모델을 한 번도 안 부른다.
    assert service.intercept("교보문고에서 파이썬 책 3권 찾아줘", "chat-1") is None
    assert len(ask.calls) == 1


def test_no_records_on_this_pc_says_so_instead_of_pretending(tmp_path: Path) -> None:
    from alture_jarvis.takeover import NO_RECORDS_ANSWER

    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent": "takeover"}'), home=tmp_path / "empty-home")
    answer = service.intercept("코덱스 한도걸렸어 이어받자", "chat-1")
    assert answer == {"answer": NO_RECORDS_ANSWER, "kind": "no_records"}


def test_a_limit_stop_older_than_the_window_is_still_found_when_asked(tmp_path: Path) -> None:
    """밤에 걸리고 아침에 와서 말한다 — 3시간 창은 「말 안 했는데 끼어들지 않기」 위한 것이지, 물었을 때 숨기라는 뜻이 아니다."""
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows(str(work), at=time.time() - 5 * 3600))
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent": "takeover"}'), home=home)
    offer = service.intercept("어젯밤에 클로드 한도 걸려서 멈췄어", "chat-1")
    assert offer["kind"] == "offer" and "사용량 한도로 멈췄습니다" in offer["answer"]
    assert "찾지 못했습니다" not in offer["answer"]


def test_the_tool_the_person_named_comes_first(tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    _write_jsonl(home / ".claude" / "projects" / "p" / "done.jsonl", _claude_rows(str(work), stop="", at=time.time() - 60))
    _write_jsonl(home / ".codex" / "sessions" / "2026" / "10" / "05" / "rollout-x.jsonl",
                 _codex_rows(str(work), used=40.0, at=time.time() - 1800))
    events: list[tuple[str, dict]] = []
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent": "takeover"}'), home=home,
                              publish=lambda e, p: events.append((e, p)))
    service.intercept("나 그머라고하지 코덱스 한도걸렸어 이어받자", "chat-1")
    assert next(p for e, p in events if e == "takeover_offered")["card"]["tool"] == "codex"


def test_the_new_sentences_leave_no_korean_on_an_english_screen(tmp_path: Path) -> None:
    import re

    from alture_jarvis import ui_i18n
    from alture_jarvis.takeover import NO_RECORDS_ANSWER

    ui_i18n.reload()
    ui_i18n.configure(tmp_path / "lang.json")
    try:
        ui_i18n.set_lang("en")
        line = ("최근 3시간 안에 사용량 한도로 멈춘 기록은 찾지 못했습니다. 가장 최근에 쓰던 Claude Code 대화는 「GitHub trending table」(4분 전)입니다. "
                "이 대화를 이어받으려면 오른쪽에서 방법을 고르시거나 「응」이라고 답해 주세요.")
        hours = line.replace("(4분 전)", "(7시간 전)")
        missing = "최근 이틀 안의 Codex 대화 기록은 찾지 못했습니다.\n" + line
        older = "Claude Code 의 「GitHub trending table」 대화가 5시간 전 사용량 한도로 멈췄습니다. 오른쪽에서 이어갈 방법을 고르시거나 「응」이라고 답해 주세요."
        # 문장 한가운데 대문자 「Stopped」가 스토어 사진에 찍혔다(2026-10-06) — 멈춘 이유는 문장 안에 끼는 말이다.
        said = ui_i18n.translate_text("Claude Code 의 「GitHub trending table」 대화가 3분 전 사용량 한도로 멈췄습니다. "
                                      "오른쪽에서 이어갈 방법을 고르시거나 「응」이라고 답해 주세요.")
        assert said.startswith('The Claude Code conversation "GitHub trending table" stopped at the usage limit 3 minutes ago.')
        for text in (line, hours, missing, older, NO_RECORDS_ANSWER):
            assert not re.search(r"[가-힣]", ui_i18n.translate_text(text)), ui_i18n.translate_text(text)
    finally:
        ui_i18n.configure(tmp_path / "lang_reset.json")
        ui_i18n.reload()


def test_a_stop_from_days_ago_is_not_what_gets_offered(tmp_path: Path) -> None:
    """실제 기록으로 돌리자 12일 전에 멈춘 대화가 골라졌다 — 파일은 이틀 안에 건드려졌지만 멈춘 것은 18,323분 전이었다."""
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    _write_jsonl(home / ".claude" / "projects" / "p" / "old-hit.jsonl", _claude_rows(str(work), at=time.time() - 12 * 86400))
    recent = _claude_rows(str(work), stop="", at=time.time() - 600)
    recent[0]["customTitle"] = "오늘 하던 일"
    _write_jsonl(home / ".claude" / "projects" / "p" / "today.jsonl", recent)
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent": "takeover"}'), home=home)
    offer = service.intercept("클로드 한도걸렸어..", "chat-1")
    assert "오늘 하던 일" in offer["answer"] and "한도로 멈춘 기록은 찾지 못했습니다" in offer["answer"]


def test_old_work_is_told_in_hours_not_thousands_of_minutes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl", _claude_rows(str(work), at=time.time() - 5 * 3600))
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent": "takeover"}'), home=home)
    offer = service.intercept("어젯밤에 클로드 한도 걸려서 멈췄어", "chat-1", capsule_visible=True)
    assert "5시간 전 사용량 한도로 멈췄습니다" in offer["answer"] and "300분" not in offer["answer"]


def test_naming_a_tool_with_no_records_says_so_first(tmp_path: Path) -> None:
    """「코덱스 한도걸렸어 이어받자」에 코덱스 기록이 없다는 말 없이 클로드 대화를 내밀었다."""
    home = tmp_path / "home"
    work = tmp_path / "plain-folder"
    work.mkdir()
    _write_jsonl(home / ".claude" / "projects" / "p" / "done.jsonl", _claude_rows(str(work), stop="", at=time.time() - 240))
    service = TakeoverService(_config(tmp_path), ask=_Ask('{"intent": "takeover"}'), home=home)
    offer = service.intercept("나 그머라고하지 코덱스 한도걸렸어 이어받자", "chat-1", capsule_visible=True)
    first, rest = offer["answer"].split("\n", 1)
    assert first == "최근 이틀 안의 Codex 대화 기록은 찾지 못했습니다."
    assert "Claude Code 대화는 「결제 모듈 리팩터링」(" in rest and "분 전)" in rest


def test_the_session_list_looks_at_each_folder_once(tmp_path: Path, monkeypatch) -> None:
    """목록이 36초 걸렸다 — 대화 12개 중 10개가 같은 폴더였는데 그 폴더의 git 상태를 대화마다 다시 봤다(한 번에 2.9초)."""
    from alture_jarvis import takeover as module

    home = tmp_path / "home"
    work, other = tmp_path / "same-folder", tmp_path / "other-folder"
    work.mkdir()
    other.mkdir()
    for index in range(4):
        _write_jsonl(home / ".claude" / "projects" / "p" / f"s{index}.jsonl", _claude_rows(str(work), stop="", at=time.time() - 60 * index))
    _write_jsonl(home / ".claude" / "projects" / "q" / "o.jsonl", _claude_rows(str(other), stop="", at=time.time() - 600))
    looked: list[str] = []
    real = module.git_state

    def counting(cwd, run=subprocess.run):
        looked.append(cwd)
        return real(cwd, run)

    monkeypatch.setattr(module, "git_state", counting)
    cards = TakeoverService(_config(tmp_path), home=home).scan(hours=12)["sessions"]
    assert len(cards) == 5 and all("git" in card for card in cards)
    assert sorted(looked) == sorted([str(work), str(other)])
    cards[0]["git"]["changed_count"] = 999  # 한 카드를 고쳐도 같은 폴더의 다른 카드는 그대로
    assert cards[1]["git"].get("changed_count") != 999
