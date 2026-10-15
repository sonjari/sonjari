"""작은 모델에게 큰 코드를 통째로 시키면 시작 전에 갈림길을 묻는다 (2026-10-02 테스터·지인 개발자).

10-01 테스터는 9B 에게 3ds Max 앱 전체를, 지인 개발자은 클로드를 안 거치고 9B 에게 게임 스크립트를 다 시켰다. 둘 다 개발자다.
실패가 「손자리 별로」로 기억되지 않게 질문 카드(이미 있는 화면)로 고르게 한다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis import big_code


def test_whole_build_requests_are_seen() -> None:
    for prompt in ("게임 스크립트 다 만들어줘", "3ds Max 용 앱 전체를 한 번에 만들어줘",
                   "유니티로 슈팅 게임 처음부터 끝까지 전부 만들어줘", "이 플러그인 모든 기능 구현해줘"):
        assert big_code.looks_like_whole_build(prompt), prompt


def test_small_or_fixing_requests_are_left_alone() -> None:
    for prompt in ("간단한 계산기 앱 만들어줘", "test_calc.py 가 실패한다. 원인을 찾아 calc.py 를 고쳐",
                   "이 함수 하나 다 고쳐줘", "사람인에서 여수 회계 공고 3개 찾아 엑셀로 정리해줘", "다음 단계 만들어줘"):
        assert not big_code.looks_like_whole_build(prompt), prompt


def test_the_question_offers_claude_code_only_when_it_is_there() -> None:
    with_cli = big_code.question(9, claude_available=True)
    without = big_code.question(9, claude_available=False)
    assert [o["label"] for o in with_cli["options"]] == [big_code.CLAUDE, big_code.SPLIT, big_code.AS_IS]
    assert [o["label"] for o in without["options"]] == [big_code.PASTE, big_code.SPLIT, big_code.AS_IS]
    assert "9B" in with_cli["question"] and with_cli["recommended"] == 0 and with_cli[big_code.MARK] is True
    assert "사용량이 듭니다" in with_cli["options"][0]["description"], "클로드 사용량을 쓴다는 것을 숨기지 않는다"


def test_paste_text_carries_the_request_and_the_split_rule() -> None:
    text = big_code.paste_text("게임 스크립트 다 만들어줘", r"D:\games\shooter")
    assert "게임 스크립트 다 만들어줘" in text and r"작업 폴더: D:\games\shooter" in text
    assert "작은 단계로 나누고" in text and "손자리" in text


def test_the_answer_is_read_back_from_the_card_step() -> None:
    steps = [{"tool": "local_index_codebase", "ok": True},
             {"tool": "ask_user", "arguments": {"question": "q", big_code.MARK: True}, "evidence": {"answer": big_code.SPLIT}}]
    assert big_code.asked(steps) and big_code.chosen(steps) == big_code.SPLIT
    plain = [{"tool": "ask_user", "arguments": {"question": "어느 파일?"}, "evidence": {"answer": "a.py"}}]
    assert not big_code.asked(plain) and big_code.chosen(plain) is None, "모델이 부른 질문 카드와 섞이지 않는다"


def test_the_agent_asks_first_and_acts_on_the_answer() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    loop = source.index("big_code_ask = big_code_question_call()")
    assert source.index("forced_claude = None if big_code_ask is not None else forced_claude_call()") > loop
    assert "size >= big_code.SMALL_MODEL_MAX_B" in source, "큰 모델(20B 이상)에는 묻지 않는다"
    assert 'decision = DelegationDecision("big_code_user_chose")' in source
    assert "completed_claude_answer = big_code.paste_text(prompt, required_local_root)" in source
    assert 'messages.append({"role": "user", "content": big_code.SPLIT_NOTE})' in source
