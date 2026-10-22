"""마무리 안내 두 버그 (2026-10-19) — 재현 시험.

A. 판 8b90144f: 마무리 대조가 「사용자가 지정한 조건과 충돌하는 항목이 섞였습니다(무료≠유료)」를 **사용자 차례**로 돌려보냈고,
   모델은 다시 쓴 답을 「지적하신 대로 …」로 시작했다. 아무도 지적하지 않았다. 게다가 「표에서 제외」했다는 줄이 이미 만든 엑셀에는
   그대로 있었다(다시 쓰기는 도구 없는 글 답이라 파일을 못 고친다).
   - 고친 구조: 사람의 말(시킨 일 · 작업 도중 덧붙인 말)에 표시를 달고, 그 뒤의 표시 없는 사용자 차례는 전부 하네스 안내로 본다.
     모델에 보내는 길목 한 곳(`_model_message` → `transcript.frame_harness_notes`)에서 공통 머리를 단다.
   - 「무료 · 유료」처럼 늘어놓은 값은 조건이 아니다(`plan.broken_conditions`).
   - 다시 쓰기 안내에 「파일은 그대로 남는다」를 같이 준다 · 다시 쓴 답이 뺐다는 항목이 파일에 남았으면 알린다.

B. 판 bb5ab643: 답을 파일로 옮기는 안전망이 **답의 첫 문장**(「…게시판은 열지 못했고 …」)으로 파일 이름을 지었다.
   - 고친 구조: 이름은 시킨 글에서 짓는다(`answer_hygiene.artifact_name_from_task`).

표본에는 실제 사람 이름 · 키 · 개인 값을 넣지 않는다 — 제품 이름도 지어낸 것이다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import BrowserAgent, _forced_artifact_decision, said_by_the_person
from alture_jarvis.answer_hygiene import artifact_name_from_task
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import ToolResult
from alture_jarvis.plan import broken_conditions, check as check_plan, excluded_item_names, extract as extract_plan
from alture_jarvis.runtime import strip_leaked_thinking
from alture_jarvis.transcript import (
    HARNESS_NOTE_HEAD,
    PERSON_KEY,
    attach_system_notes,
    frame_harness_notes,
    harness_note_positions,
    person_message,
)
from alture_jarvis.transcript_policy import _STEER_MARK

RECONCILE_NOTE = "[시스템] 방금 최종 답은 실행 장부와 모순된다: 사용자가 지정한 조건과 충돌하는 항목이 섞였습니다(무료≠유료)."


def _sent(messages: list[dict]) -> list[dict]:
    """`_model_message` 가 서버로 보내기 전에 거치는 두 단계 그대로."""
    return frame_harness_notes(attach_system_notes(messages))


# ── A. 하네스 안내는 사람 말로 가지 않는다 ───────────────────────────────────────────────────────────


def _run_transcript() -> list[dict]:
    return [
        {"role": "system", "content": "지침"},
        {"role": "user", "content": "지난 대화의 질문"},           # 지난 대화 — 사람 말
        {"role": "assistant", "content": "지난 대화의 답"},
        person_message("AI 도구 제품을 조사해서 엑셀로 정리해 줘. 가격(무료 · 유료 · 월 얼마)도 적어 줘."),
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "browser_read", "arguments": {}}}]},
        {"role": "tool", "content": "본문"},
        {"role": "user", "content": "[시스템] 도구 결과 뒤의 안내"},  # 도구 결과에 붙는다
        {"role": "assistant", "content": "첫 답 — 알파툴은 유료"},
        {"role": "user", "content": RECONCILE_NOTE},                   # 답 뒤의 안내 — 이게 사람 말로 읽혔다
    ]


def test_the_reconcile_note_after_an_answer_is_marked_as_an_automatic_check() -> None:
    sent = _sent(_run_transcript())
    last = sent[-1]
    assert last["role"] == "user"
    assert last["content"].startswith(HARNESS_NOTE_HEAD), "답 뒤의 하네스 안내에 「사용자가 한 말 아님」 머리가 없다"
    assert RECONCILE_NOTE in last["content"]


def test_the_persons_words_are_left_as_they_are() -> None:
    sent = _sent(_run_transcript())
    users = [item["content"] for item in sent if item["role"] == "user"]
    assert users[0] == "지난 대화의 질문"
    assert users[1].startswith("AI 도구 제품을 조사해서")
    assert not any(HARNESS_NOTE_HEAD in text for text in users[:2])


def test_a_note_riding_on_a_tool_result_is_not_headed_again() -> None:
    sent = _sent(_run_transcript())
    tool = next(item for item in sent if item["role"] == "tool")
    assert "[시스템] 도구 결과 뒤의 안내" in tool["content"]
    assert HARNESS_NOTE_HEAD not in tool["content"]


def test_the_person_mark_never_reaches_the_server() -> None:
    assert not any(PERSON_KEY in item for item in _sent(_run_transcript()))


def test_a_note_without_any_prefix_is_still_a_harness_note() -> None:
    """앞머리 없는 안내(「예고하지 말고 지금 도구를 호출해라」)도 시킨 일 뒤면 하네스 안내다 — 앞머리를 기억할 필요가 없다."""
    messages = [
        {"role": "system", "content": "지침"},
        person_message("제품 셋을 찾아 줘"),
        {"role": "assistant", "content": "지금 찾아보겠습니다."},
        {"role": "user", "content": "예고하지 말고 지금 도구를 호출해라."},
    ]
    assert _sent(messages)[-1]["content"].startswith(HARNESS_NOTE_HEAD)


def test_words_the_person_added_mid_run_stay_the_persons_and_notes_before_them_do_not() -> None:
    messages = [
        {"role": "system", "content": "지침"},
        person_message("제품 셋을 찾아 줘"),
        {"role": "assistant", "content": "찾는 중"},
        {"role": "user", "content": "[시스템] 같은 자리를 맴돌고 있다."},
        {"role": "assistant", "content": "알겠습니다"},
        person_message(f"{_STEER_MARK}\n무료인 것만"),
    ]
    sent = _sent(messages)
    assert sent[3]["content"].startswith(HARNESS_NOTE_HEAD), "덧붙인 말 앞의 안내가 사람 말로 빠졌다"
    assert sent[5]["content"].startswith(_STEER_MARK), "사람이 덧붙인 말에 「사용자가 한 말 아님」이 붙었다"


def test_an_old_transcript_without_marks_falls_back_to_the_prefixes() -> None:
    messages = [
        {"role": "system", "content": "지침"},
        {"role": "user", "content": "제품 셋을 찾아 줘"},
        {"role": "assistant", "content": "첫 답"},
        {"role": "user", "content": RECONCILE_NOTE},
    ]
    sent = _sent(messages)
    assert sent[1]["content"] == "제품 셋을 찾아 줘"
    assert sent[3]["content"].startswith(HARNESS_NOTE_HEAD)


def test_the_rule_is_stable_so_the_cached_prefix_does_not_move() -> None:
    messages = _run_transcript()
    once = _sent(messages)
    later = _sent(messages + [{"role": "assistant", "content": "다시 쓴 답"}, {"role": "user", "content": "[시스템] 또 하나"}])
    assert later[: len(once)] == once
    assert _sent(messages) == once


def test_said_by_the_person_uses_the_same_split() -> None:
    messages = [
        person_message("가격이 12,000원인 것"),
        {"role": "assistant", "content": "답"},
        {"role": "user", "content": "예고하지 말고 지금 도구를 호출해라. 3,456"},
    ]
    said = said_by_the_person(messages)
    assert "12,000" in said and "3,456" not in said
    assert harness_note_positions(messages) == {2}


def test_a_leaked_head_line_is_stripped_from_the_answer() -> None:
    leaked = HARNESS_NOTE_HEAD + "\n표를 정리했습니다."
    assert strip_leaked_thinking(leaked) == "표를 정리했습니다."


def test_the_reconcile_turn_reaches_the_model_headed(tmp_path) -> None:
    """실제 판 길목으로 — 다시 쓰기 안내가 모델에 「자동 점검」 머리를 달고 도착하고, 시킨 일은 그대로 도착한다."""

    class _ReadTools:
        names = {"browser_read"}
        ollama_tools = [{"type": "function", "function": {
            "name": "browser_read", "description": "read",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}}]

    class _ReadGateway:
        def execute(self, name, arguments, *, job_id=""):
            index = int(str(arguments["url"]).rsplit("/", 1)[-1])
            return ToolResult(True, name, result={
                "action": "read", "url": f"https://jobs.example.test/{index}", "title": f"정규직 공고 {index}",
                "char_count": 12000 + index, "text": f"정규직 공고 {index} 본문"})

    class _Model:
        def __init__(self) -> None:
            self.calls = 0
            self.seen: list[list[dict]] = []

        def chat_messages(self, messages, **_kwargs):
            self.calls += 1
            self.seen.append([dict(item) for item in messages])
            if self.calls <= 3:
                return {"role": "assistant", "content": "", "tool_calls": [{"function": {
                    "name": "browser_read", "arguments": {"url": f"https://jobs.example.test/{self.calls}"}}}]}
            if self.calls == 4:
                return {"role": "assistant", "content": "2개를 확인했습니다. 세 번째 상세 정보 추출에 실패했습니다."}
            return {"role": "assistant", "content": "정규직 공고 1, 정규직 공고 2, 정규직 공고 3을 모두 확인했습니다."}

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          browser_enabled=True, browser_task_timeout_sec=60)
    store = JobStore(tmp_path / "jarvis.db")
    model = _Model()

    class _Browser:
        def status(self):
            return {"started": True}

    agent = BrowserAgent(config, model, _ReadGateway(), _Browser(), _ReadTools(), store, EventBus())
    job = store.create_job("chat", "agent", {"prompt": "구인 사이트 정규직 공고 3개를 찾아줘"})
    store.claim_next()
    result = agent.run("구인 사이트 정규직 공고 3개를 찾아줘", job_id=job["id"], origin="chat")

    assert result.verification["answer_reconciled"] is True
    reconcile_call = model.seen[-1]
    assert reconcile_call[-1]["role"] == "user"
    assert reconcile_call[-1]["content"].startswith(HARNESS_NOTE_HEAD)
    assert "실행 장부와 모순" in reconcile_call[-1]["content"]
    task = next(item for item in reconcile_call if item["role"] == "user")
    assert "구인 사이트 정규직 공고 3개를 찾아줘" in task["content"]
    assert HARNESS_NOTE_HEAD not in task["content"]
    assert not any(PERSON_KEY in item for call in model.seen for item in call)


# ── A. 원인이 된 판정 · 다시 쓰기와 파일 ──────────────────────────────────────────────────────────────


def test_a_listed_choice_of_values_is_not_a_condition() -> None:
    """「가격(무료 · 유료 · 월 얼마)」는 칸에 적을 값의 보기다 — 「무료만」이 아니다(판 8b90144f 의 첫 답 꼴)."""
    prompt = "AI 도구 제품을 조사해 엑셀로 정리해 줘. 가격(무료 · 유료 · 월 얼마), 대상 사용자를 적어 줘."
    answer = "| 알파툴 | 유료 |\n| 베타검색 | 무료(유료 플랜 있음) |"
    assert broken_conditions(prompt, answer) == []
    listed = "공고 3개의 고용형태(정규직/계약직/인턴 등)를 확인해 줘"
    assert broken_conditions(listed, "| 가 | 계약직 |\n| 나 | 인턴 |") == []


def test_a_real_condition_still_catches_its_conflict() -> None:
    assert broken_conditions("무료 앱만 3개 찾아 줘", "- 알파툴: 유료") == [("무료", "유료")]
    assert ("정규직", "계약직") in broken_conditions("정규직 공고 3개, 계약직은 빼고", "- 가 공고: 계약직")


def _written(path: Path) -> list[dict]:
    return [{"tool": "local_write_document", "ok": True, "evidence": {"output_path": str(path), "path": str(path)}}]


def test_the_rewrite_note_says_the_file_stays_as_it_was(tmp_path) -> None:
    path = tmp_path / "조사.csv"
    path.write_text("제품,가격\n알파툴,유료\n", encoding="utf-8")
    note = BrowserAgent._files_stay_as_written_note(_written(path))
    assert "조사.csv" in note and "파일을 고칠 수 없다" in note
    assert BrowserAgent._files_stay_as_written_note([]) == ""


REWRITTEN = (
    "조건을 다시 대조했습니다.\n\n"
    "**조건에 맞지 않아 결과 표에서 제외한 것:**\n"
    "- **알파툴**: 첫 화면에 가격 표기가 없음 → 제외\n"
    "- **베타검색**: 영어 원문 문구를 확인 못 함 → 제외\n\n"
    "남은 제품은 둘입니다."
)


def test_names_said_to_be_left_out_are_read_from_the_lines_that_say_so() -> None:
    assert excluded_item_names(REWRITTEN) == ["알파툴", "베타검색"]
    # 뺀 자리 제목 아래라도 그 줄에 「뺐다」는 말이 없으면 이름으로 치지 않는다(칸 이름 · 설명문이 섞이던 것).
    assert excluded_item_names("**제외한 것:**\n- **배송비**: 확인 못 함") == []


def test_left_out_in_the_answer_but_still_in_the_file_is_flagged(tmp_path) -> None:
    path = tmp_path / "조사.csv"
    path.write_text("제품,가격\n알파툴,유료\n베타검색,무료\n감마노트,무료\n", encoding="utf-8")
    warning = BrowserAgent._excluded_but_in_file(REWRITTEN, _written(path))
    assert "알파툴" in warning and "베타검색" in warning and "조사.csv" in warning


def test_no_warning_when_the_file_agrees(tmp_path) -> None:
    path = tmp_path / "조사.csv"
    path.write_text("제품,가격\n감마노트,무료\n", encoding="utf-8")
    assert BrowserAgent._excluded_but_in_file(REWRITTEN, _written(path)) == ""


# ── B. 대신 저장하는 파일의 이름은 시킨 글에서 ─────────────────────────────────────────────────────────

BOARD_PROMPT = (
    "커뮤니티 게시판 세 곳에서 지난 한 달 인기 글을 게시판마다 10개씩 열어 읽고, 사용자들이 아쉬워하는 점(페인포인트)을 모아서 "
    "엑셀 파일 하나로 정리해 줘. 줄마다 담을 것: 페인포인트, 원문 문장, 게시판 이름. 못 열어 본 글은 「확인 못 함」으로 표시해 줘."
)
CONFESSING_ANSWER = """세 번째 게시판은 열지 못했고, 두 번째 게시판은 10개 중 6개만 읽었습니다. 실제로 읽은 글에서 확인한 페인포인트를 표로 정리합니다.

## 페인포인트 정리

| 페인포인트 | 원문 문장 | 게시판 |
|---|---|---|
| 사용량 한도 | "hit the limit again" | 게시판 가 |
| 자신 있게 틀림 | "confidently wrong" | 게시판 가 |
| 설치가 어려움 | "setup took hours" | 게시판 나 |
"""
READ_STEPS = [{"tool": "browser_extract", "ok": True, "evidence": {"url": f"https://board.example.test/{i}"}} for i in range(6)]


def _decide(prompt: str, answer: str = CONFESSING_ANSWER) -> dict:
    plan = extract_plan(prompt, has_named_source=False)
    results = check_plan(plan, sources=[s["evidence"]["url"] for s in READ_STEPS], steps=READ_STEPS)
    call, reason = _forced_artifact_decision(results, READ_STEPS, answer, prompt)
    assert call is not None, reason
    return call[1]


def test_the_file_is_not_named_after_the_answers_confession() -> None:
    args = _decide(BOARD_PROMPT)
    assert args["path"] == "페인포인트.xlsx"
    assert "열지_못했고" not in args["path"]


def test_a_name_in_corner_quotes_is_used_as_it_is() -> None:
    args = _decide(BOARD_PROMPT + " 파일 이름은 「게시판_불만_정리.xlsx」로 해 줘.")
    assert Path(args["path"]).name == "게시판_불만_정리.xlsx"


def test_the_document_title_comes_from_the_task_when_the_answer_has_none() -> None:
    no_heading = CONFESSING_ANSWER.replace("## 페인포인트 정리\n\n", "")
    args = _decide(BOARD_PROMPT, no_heading)
    title = args["blocks"][0]
    assert title.get("type") == "heading" and title.get("text") == "페인포인트"


def test_names_from_tasks() -> None:
    assert artifact_name_from_task("구인 사이트에서 지역 회계 채용 공고 3개를 조사해서 문서로 정리해줘.") == "지역 회계 채용 공고"
    assert artifact_name_from_task("세 가게에서 「무선 이어폰 프로」을 찾아 가게 · 가격 · 주소를 엑셀로 정리해 줘") == "무선 이어폰 프로"
    assert artifact_name_from_task(r"그 내용을 C:\Users\someone\Documents\반응기록.xlsx 에 기록해줘") == "반응기록"
    assert artifact_name_from_task("거기 지원할 이력서 초안을 문서로 만들어줘.") == "이력서 초안"
    assert artifact_name_from_task("결과는 마크다운(.md) 파일로 만들어줘") != "마크다운("
    assert artifact_name_from_task("https://example.test/index.html 을 읽고 표로 정리해 줘") != "index"
