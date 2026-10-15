"""대화 기록의 질문·답이 자기 작업 번호를 들고 있다 (2026-10-01 스토어 촬영 18번).

질문·답은 작업이 **끝날 때** 저장되고(`memory.add_exchange`), 화면의 작업 기록 상자는 **시작 시각**으로 줄을 섰다.
몇 분 걸린 판은 상자가 질문 위로 올라갔다. 화면(`ui/src/trajectory.ts` buildTimeline)은 질문의 `metadata.job_id`
로 상자를 그 질문 바로 뒤에 붙인다 — 그러려면 서버가 번호를 남겨야 한다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.memory import ConversationMemory

RUNTIME = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "runtime.py"


def test_the_job_turn_record_writes_the_job_id_on_both_sides() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    start = source.index("user_message_id, assistant_message_id = self.memory.add_exchange(")
    block = source[start:start + 3_000]
    user_part = block[block.index("user_metadata={"):block.index("assistant_metadata={")]
    assistant_part = block[block.index("assistant_metadata={"):]
    assert '"job_id": str(job["id"])' in user_part
    assert '"job_id": str(job["id"])' in assistant_part


def test_the_store_keeps_the_job_id_for_the_screen(tmp_path: Path) -> None:
    memory = ConversationMemory(tmp_path / "jarvis.db")
    memory.add_exchange("s1", "교보 3권 찾아 줘", "만들었습니다", user_metadata={"job_id": "job-k"},
                        assistant_metadata={"job_id": "job-k"})
    rows = memory.history("s1")
    assert [row["metadata"].get("job_id") for row in rows] == ["job-k", "job-k"]
