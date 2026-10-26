"""우리가 답 끝에 덧붙인 경고·대조표는 다음 턴의 모델에게 들어가지 않는다 (2026-10-05 대표 실사용, 전략 대화 방).

    c6b5ad92  「…깃허브 레포에 올리고 공개한 뒤에 … 레딧 이렇게 다 갈려고…」(자기 계획 이야기)
              → 답 끝에 「⚠ 읽지 않고 적은 것이 있습니다 …」 + 「시킨 것 대조 ❌ 깃허브에서 하기 · ❌ 레딧에서 하기」
    cecf6a10  「아니아니 너가 봤을 때 어떻게 생각하냐는 거지 나의 전략이」
              → **앞 답을 경고문·대조표까지 그대로 되풀이**
    05cd5f7b  「…국내는 왜 그럴까 심지어 중국도…」 → 또 같은 답
    19294dfa · f7caaae1  → 모델이 **스스로 흉내 낸** 경고문(구두점이 우리 것과 다름)

사람에게 한 말이 대화 기록을 타고 모델에게 되돌아가, 모델이 「❌ … 아무것도 안 함」을 남은 숙제로 읽었다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis import agent
from alture_jarvis.memory import ConversationMemory, without_our_tail

SAID = (
    "사용자님, 지금 제가 할 수 있는 건 **전략 정리 + 준비물 작성**뿐입니다.\n\n"
    "먼저 어떤 게 가장 시급하신지 알려주세요:\n\n"
    "1. **첫 90일 커뮤니티 활성화 체크리스트** — 엑셀로\n2. **공개용 README 초안** — 워드로\n\n"
    "어느 것부터 만들까요?"
)
WARNING = (
    "⚠ **읽지 않고 적은 것이 있습니다:** \"첫 90일 커뮤니티 활성화 체크리스트\" \"공개용 README 초안\" — 이 이름들은 "
    "이번에 읽은 자료(페이지·파일) 어디에도 없습니다 — 목록 줄에서 옮겨 적었을 수 있습니다."
)
CHECKLIST = "**시킨 것 대조**\n- ❌ 깃허브에서 하기 — 거기서 아무것도 안 함\n- ❌ 레딧에서 하기 — 거기서 아무것도 안 함"
SHOWN = f"{SAID}\n\n{WARNING}\n\n{CHECKLIST}"


def test_the_warning_and_the_checklist_are_taken_off_the_end() -> None:
    assert without_our_tail(SHOWN) == SAID


def test_the_english_checklist_is_taken_off_too() -> None:
    shown = "Here are the three papers.\n\n**Checklist**\n- ❌ Make the actual file — No output that can be opened"
    assert without_our_tail(shown) == "Here are the three papers."


def test_a_warning_the_model_wrote_in_the_middle_stays() -> None:
    said = "정리했습니다.\n\n⚠ **주의** 이 값은 2024년 기준입니다.\n\n그래서 올해 값은 따로 확인해야 합니다."
    assert without_our_tail(said) == said


def test_an_answer_that_is_only_a_warning_is_not_emptied() -> None:
    assert without_our_tail(WARNING) == WARNING
    assert without_our_tail("") == ""


def test_the_model_sees_what_it_said_and_the_record_keeps_what_was_shown(tmp_path: Path) -> None:
    memory = ConversationMemory(tmp_path / "memory.db")
    memory.add_message("room", "user", "깃허브 레포에 올리고 공개한 뒤에 레딧 이렇게 다 갈려고")
    memory.add_message("room", "assistant", SHOWN)
    memory.add_message("room", "user", "⚠ **이건 사용자가 쓴 글이다**\n\n**시킨 것 대조** 라는 말도 사용자가 썼다")

    sent = memory.context_messages("room")
    stored = memory.recent("room")

    assert [item["content"] for item in sent if item["role"] == "assistant"] == [SAID]
    assert "❌ 깃허브에서 하기" not in "\n".join(item["content"] for item in sent)
    assert sent[-1]["content"].startswith("⚠ **이건 사용자가 쓴 글이다**"), "사용자의 글은 건드리지 않는다"
    assert stored[1]["content"] == SHOWN, "화면과 저장된 기록은 그대로다"


def test_an_answer_that_used_no_tools_gets_no_name_warning_and_no_checklist() -> None:
    source = inspect.getsource(agent.BrowserAgent.run)
    assert '("" if not steps else' in source and "self._grounding_with_carry(answer, messages, steps, job_id," in source
    assert '("" if not steps else summary_note(final_plan_results, reply_language(answer)))' in source  # 10-23: 답 언어를 따른다
    # 한 것처럼 **말한** 답을 잡는 검사는 도구를 안 쓴 답에도 그대로 돈다.
    assert "+ claimed_reads_note(answer, steps)" in source
    assert "self._commit_reality_check(answer, steps)" in source
