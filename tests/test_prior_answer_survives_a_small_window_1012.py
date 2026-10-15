"""이어지는 질문에서 바로 앞 판의 답이 버려지지 않는다 (2026-10-12 저녁).

작은 카드(4B · 창 32K)로 쓰는 사람의 말: 「한 판은 잘한다. 그다음 질문에서 무너진다」. 전사를 줄이는 자리가 지키는 것은
맨 처음 요청과 이번 요청뿐이었고, 그 사이의 대화(바로 앞 판의 답)는 걸음이 쌓이면 제일 먼저 버려졌다. 창 32K 에서는
새 판이 화면을 하나나 둘 읽으면 앞 답이 없었다 — 「그중에 둘째 것만」의 「그중」이 지워진 채로 일했다.

표본의 대화 모양은 실제 그대로다: [시스템] [앞 질문] [앞 답] [이번 요청(판 맥락을 앞에 실음)] + 이번 판의 걸음.
"""

from __future__ import annotations

import json

from alture_jarvis import transcript
from alture_jarvis.transcript_policy import chat_transcript_budget

MARK = "앞 판의 답 표식 가나다."
FILE_LINE = r"만든 파일: C:\Users\someone\Documents\Sonjari\가상 노트북 가격.xlsx"
PRIOR_ASK = "가상 노트북 세 종 가격 조사해서 표로 정리해 줘"
NOW_ASK = "그중에 둘째 것만 다른 가게 값도 찾아 줘"


def _prior_answer(chars: int = 3_000) -> str:
    body = (MARK + " " + "1) 가상 노트북 A 1,290,000원 · 2) 가상 노트북 B 1,450,000원 · 3) 가상 노트북 C 990,000원. " * 60)[:chars]
    return body + "\n\n" + FILE_LINE


def _call(tool: str, **arguments) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": tool, "arguments": arguments}}]}


def _tool(name: str, body: dict) -> dict:
    return {"role": "tool", "tool_name": name, "content": json.dumps(body, ensure_ascii=False)}


def _shop(number: int) -> list[dict]:
    return [
        _call("browser_site_search", query="가상 노트북 B"),
        _tool("browser_site_search", {"ok": True, "url": f"https://shop{number}.example.test/search", "results": "목록 " * 900}),
        _call("browser_extract"),
        _tool("browser_extract", {"page_main_values": "판매가 1,440,000원", "ok": True, "url": f"https://shop{number}.example.test/item/1",
                                  "title": f"가상 노트북 B : 가게{number}", "text": "본문 " * 6000}),
    ]


def _conversation(shops: int, *, answer: str | None = None, extra_turns: list[dict] | None = None) -> list[dict]:
    messages = [{"role": "system", "content": "지침 " * 6700}, {"role": "user", "content": PRIOR_ASK},
                {"role": "assistant", "content": _prior_answer() if answer is None else answer}]
    messages += extra_turns or []
    messages.append({"role": "user", "content": transcript.with_job_context("스킬 안내: 가게마다 값을 찾아 표로.", NOW_ASK)})
    for number in range(1, shops + 1):
        messages += _shop(number)
    return messages


def _sent(messages: list[dict], window: int = 32_768, model: str = "qwen3.5:4b") -> tuple[list[dict], str, int]:
    budget, per = chat_transcript_budget(window, model)
    kept = transcript.bounded([dict(item) for item in messages], max_chars=budget, tool_result_max=per)
    return kept, json.dumps(kept, ensure_ascii=False), budget


def test_the_answer_just_before_is_still_there_after_the_new_job_reads_pages() -> None:
    for window, model in ((32_768, "qwen3.5:4b"), (32_768, "qwen3.5:9b"), (49_152, "big-27b")):
        for shops in range(0, 5):
            kept, whole, budget = _sent(_conversation(shops), window, model)
            assert MARK in whole, f"창 {window} · {model} · 가게 {shops}곳 읽은 뒤 앞 답이 없다"
            assert "가상 노트북 가격.xlsx" in whole, "답의 끝(만든 파일 경로)도 남는다"
            assert NOW_ASK in whole and PRIOR_ASK in whole
            assert sum(len(json.dumps(item, ensure_ascii=False)) for item in kept) <= budget + 800


def test_it_rides_in_the_job_context_only_when_the_answer_was_pushed_out() -> None:
    # 아직 다 들어가면 대화 그대로다 — 덧붙이는 것이 없다.
    kept, whole, _ = _sent(_conversation(0))
    assert transcript.PRIOR_TURN_OPEN not in whole and MARK in whole
    # 밀려나면 이번 요청의 맥락 안에, 요청보다 앞에.
    kept, whole, _ = _sent(_conversation(4))
    request = next(str(item["content"]) for item in kept if item["role"] == "user" and NOW_ASK in str(item["content"]))
    assert request.index(transcript.PRIOR_TURN_OPEN) < request.index(transcript.JOB_CONTEXT_CLOSE) < request.index(NOW_ASK)
    assert request.count(transcript.JOB_CONTEXT_OPEN) == 1 and "스킬 안내: 가게마다 값을 찾아 표로." in request
    block = request[request.index(transcript.PRIOR_TURN_OPEN):request.index(transcript.PRIOR_TURN_CLOSE)]
    assert "[앞 답] " + MARK in block
    assert "가운데" in block and "줄임" in block, "긴 답은 머리와 꼬리만"
    assert len(block) <= transcript.PRIOR_TURN_ANSWER_HEAD_CHARS + transcript.PRIOR_TURN_ANSWER_TAIL_CHARS + transcript.PRIOR_TURN_ASK_CHARS + 400
    # 읽은 화면의 한 줄 묶음과 같이 실릴 때는 앞 대화가 먼저다.
    if transcript.READ_LEDGER_OPEN in request:
        assert request.index(transcript.PRIOR_TURN_OPEN) < request.index(transcript.READ_LEDGER_OPEN)


def test_with_several_turns_the_last_is_kept_long_and_the_two_before_it_short() -> None:
    """실제로 필요했던 것은 세 판 앞의 답이었다 — 바로 앞 판만 지키면 「다시 설명해 주시겠어요?」가 난다."""
    older = [{"role": "user", "content": "가상 모니터도 찾아 줘"}, {"role": "assistant", "content": "가운데 판의 답 표식 라마바. " + "모니터 값 " * 300}]
    kept, whole, budget = _sent(_conversation(4, extra_turns=older))
    request = next(str(item["content"]) for item in kept if item["role"] == "user" and NOW_ASK in str(item["content"]))
    block = request[request.index(transcript.PRIOR_TURN_OPEN):request.index(transcript.PRIOR_TURN_CLOSE)]
    # 바로 앞 판은 길게(머리 · 꼬리).
    assert "[앞 질문] 가상 모니터도 찾아 줘" in block and "[앞 답] 가운데 판의 답 표식 라마바." in block
    # 그 앞 판은 첫머리만 — 무엇을 이미 말했는지는 안다.
    assert "[그 앞 답] " + MARK in block
    older_part = block[block.index("[그 앞 답] "):block.index("[앞 질문] ")]
    assert len(older_part) <= transcript.PRIOR_TURN_OLDER_ANSWER_CHARS + 60 and "줄임" in older_part
    assert block.index("[그 앞 답] ") < block.index("[앞 답] "), "오래된 것이 위로"
    assert sum(len(json.dumps(item, ensure_ascii=False)) for item in kept) <= budget + 800


def test_only_the_last_three_turns_are_carried() -> None:
    turns = []
    for number in range(1, 6):
        turns += [{"role": "user", "content": f"{number}째 덧질문"}, {"role": "assistant", "content": f"{number}째 덧답 표식. " + "글 " * 400}]
    kept, whole, _ = _sent(_conversation(4, extra_turns=turns))
    request = next(str(item["content"]) for item in kept if item["role"] == "user" and NOW_ASK in str(item["content"]))
    block = request[request.index(transcript.PRIOR_TURN_OPEN):request.index(transcript.PRIOR_TURN_CLOSE)]
    assert "[앞 답] 5째 덧답 표식." in block and "[그 앞 답] 4째 덧답 표식." in block and "[그 앞 답] 3째 덧답 표식." in block
    assert "2째 덧답 표식." not in block and MARK not in block, "더 앞의 판까지 다 싣지 않는다 — 묶음이 방을 도로 채운다"
    assert block.index("3째 덧답") < block.index("4째 덧답") < block.index("5째 덧답")


def test_a_first_request_has_nothing_before_it() -> None:
    messages = [{"role": "system", "content": "지침 " * 6700},
                {"role": "user", "content": transcript.with_job_context("스킬 안내", "가상 노트북 가격 조사")}]
    for number in range(1, 5):
        messages += _shop(number)
    _, whole, _ = _sent(messages)
    assert transcript.PRIOR_TURN_OPEN not in whole


def test_the_block_alone() -> None:
    rest = [{"role": "user", "content": "둘째 질문"}, {"role": "assistant", "content": "짧은 답"},
            {"role": "user", "content": transcript.with_job_context("맥락", "셋째 질문")}]
    # 앞 답이 담겼으면 빈 글 · 이번 요청이 어디인지 모르면 빈 글.
    assert transcript.prior_turn_block(rest, 2, {1}) == ""
    assert transcript.prior_turn_block(rest, None, set()) == ""
    block = transcript.prior_turn_block(rest, 2, set())
    assert "[앞 질문] 둘째 질문" in block and "[앞 답] 짧은 답" in block and "줄임" not in block
    # 도구를 부른 걸음(글 없는 assistant)과 하네스 안내는 「앞 답 · 앞 질문」이 아니다.
    rest = [{"role": "user", "content": "첫 질문"}, {"role": "assistant", "content": "진짜 답"},
            {"role": "user", "content": transcript.SYSTEM_NOTE_PREFIX + " 안내"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "x", "arguments": {}}}]},
            {"role": "user", "content": transcript.with_job_context("맥락", "다음 질문")}]
    block = transcript.prior_turn_block(rest, 4, set())
    assert "[앞 답] 진짜 답" in block and "[앞 질문] 첫 질문" in block and "안내" not in block.split("[앞 질문]")[1]
    # 대화의 맨 처음 요청은 여기 없다(따로 지킨다) — 그 답만 남긴다.
    block = transcript.prior_turn_block([{"role": "assistant", "content": "첫 판의 답"},
                                         {"role": "user", "content": transcript.with_job_context("맥락", "둘째 질문")}], 1, set())
    assert "[앞 답] 첫 판의 답" in block and "[앞 질문]" not in block
