"""왜 멈췄는지 **나중에 알 수 있어야** 한다.

★ 2026-09-02 라이브. 판 하나가 이렇게 끝났다:

    thinking_chars 48,282 · step_limit 12 · 10걸음 · stop=model_stopped_early
    답 마지막 줄: "파일 생성을 승인하시겠습니까?"

승인이 필요한 일이 아니었다(문서 만들기는 L1). 셋이 겹쳐 있었다:

    ① 사고 48,282자를 해 놓고 **본문이 안 남아** 왜 멈췄는지 못 캤다
    ② 걸음 예산이 `count` 만 보고 있어서 **산출물·각주에 자리를 안 줬다**(12걸음)
    ③ 상세 셋을 읽고 답에는 **다른 회사 둘**을 적었는데 개수 대조가 통과시켰다
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.plan import extract

REAL = (
    "자비스 구글 드라이브에서 나래이 이력서를 읽고 오늘자로 지원 가능한 연구비 관리 "
    "정규직 공고를 사람인에서 1순위부터 3순위까지 찾아줘 그 다음에 한글 파일에 "
    "이력서 원문을 그대로 옮기고 회사별로 각주로 달아줘"
)


def _agent(tmp_path: Path) -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents",
    )
    return agent


# ── ① 사고를 남긴다 ──────────────────────────────────────────────────────────
def test_the_thinking_is_kept_so_the_stop_can_be_explained(tmp_path: Path) -> None:
    agent = _agent(tmp_path)

    agent._keep_thinking("job-1", "공고를 세 건 읽었다. 이제 파일을 만들어야 하는데…")

    kept = (Path(agent.config.output_dir) / "thinking" / "job-1.md").read_text(encoding="utf-8")
    assert "파일을 만들어야" in kept


def test_thinking_from_several_turns_piles_up(tmp_path: Path) -> None:
    """한 판이 모델을 여러 번 부른다. 마지막 것만 남으면 흐름을 못 본다."""
    agent = _agent(tmp_path)

    agent._keep_thinking("job-2", "첫 번째 생각")
    agent._keep_thinking("job-2", "두 번째 생각")

    kept = (Path(agent.config.output_dir) / "thinking" / "job-2.md").read_text(encoding="utf-8")
    assert "첫 번째 생각" in kept and "두 번째 생각" in kept


def test_a_failure_to_keep_does_not_kill_the_run(tmp_path: Path) -> None:
    """사고를 못 적었다고 판을 죽이지 않는다."""
    agent = _agent(tmp_path)
    agent.config.output_dir = tmp_path / "없는곳" / "\0"  # 못 만드는 경로

    agent._keep_thinking("job-3", "생각")  # 예외가 새면 안 된다


def test_nothing_is_written_for_an_empty_thought(tmp_path: Path) -> None:
    agent = _agent(tmp_path)

    agent._keep_thinking("job-4", "   ")

    assert not (Path(agent.config.output_dir) / "thinking" / "job-4.md").exists()


# ── ② 걸음 예산이 시킨 일 전체를 본다 ────────────────────────────────────────
def test_the_budget_counts_the_artifact_not_just_the_reading(tmp_path: Path) -> None:
    """★ 라이브에서 12걸음이었다. 최소 걸음이 이미 10이라 산출물에 둘밖에 안 남았다."""
    agent = _agent(tmp_path)
    plan = extract(REAL, has_named_source=True)

    budget = agent._step_budget(plan)
    reading_only = agent._step_budget([r for r in plan if r.kind in {"count", "site"}])

    assert budget >= reading_only + 5, f"산출물·각주에 자리를 안 줬다({budget})"
    assert budget >= 15


def test_a_pure_research_ask_is_not_inflated(tmp_path: Path) -> None:
    """모르는 일을 크게 잡지 않는다 — 큰 예산은 헛도는 판을 길게 만든다."""
    agent = _agent(tmp_path)

    plain = agent._step_budget(extract("사람인에서 공고 3개 찾아줘", has_named_source=True))

    assert plain <= 13


# ── ③ 답에 적은 것이 읽은 것인가 ────────────────────────────────────────────
ANSWER = """| 순위 | 회사명 | 고용형태 |
| :--- | :--- | :--- |
| 1 | **(주)미르** | 정규직 |
| 2 | **(주)도담스페이스** | 정규직 |
| 3 | **(주)바름터** | 정규직 |"""


def test_a_company_that_was_never_opened_is_called_out() -> None:
    """★ 상세 셋을 읽고 답에는 **다른 회사 둘**을 적었다. 개수 대조는 통과시켰다."""
    read = [{"role": "tool", "content": "[코드나루(주)] … [(주)한울솔루션] … [(주)미르] 상세"}]

    note = BrowserAgent._listed_entity_grounding_check(ANSWER, read)

    assert "도담스페이스" in note and "바름터" in note
    assert "미르" not in note.split("있습니다:")[1].split(".")[0]


def test_it_stays_quiet_when_everything_was_read() -> None:
    read = [{"role": "tool", "content": "(주)미르 · (주)도담스페이스 · (주)바름터 상세를 읽었다"}]

    assert BrowserAgent._listed_entity_grounding_check(ANSWER, read) == ""


def test_a_single_mention_is_not_a_list() -> None:
    """지나가는 말에 경고를 달지 않는다."""
    answer = "| 순위 | 회사명 |\n| 1 | **(주)미르** |"

    assert BrowserAgent._listed_entity_grounding_check(answer, [{"role": "tool", "content": "없음"}]) == ""


def test_when_none_match_it_speaks_up_loudest() -> None:
    """★ 규칙을 뒤집었다 (2026-09-02 저녁).

    처음엔 「전부 안 맞으면 이름을 잘못 뽑은 것」이라며 조용히 넘어갔다. 그런데
    라이브에서 답의 세 회사가 **하나도 안 읽은 곳**이었는데 바로 그 조건 때문에
    경고가 통째로 죽었다 — **제일 강한 증거를 내가 만든 문턱이 지웠다.**

    「이름을 잘못 뽑았을 수도 있다」는 걱정은 다른 방식으로 던다: 도구가 실제로
    무언가를 읽어 왔을 때만 판정한다. 읽은 것이 있는데 그중 어느 것도 답에
    없으면, 그건 뽑기 실패가 아니라 **답이 딴 데서 왔다**는 뜻이다.
    """
    read = [{"role": "tool", "content": "전혀 다른 글"}]

    note = BrowserAgent._listed_entity_grounding_check(ANSWER, read)
    assert "미르" in note and "도담스페이스" in note and "바름터" in note

    # 도구가 아무것도 안 읽었으면 판정할 근거가 없다 — 그때는 조용하다.
    assert BrowserAgent._listed_entity_grounding_check(ANSWER, []) == ""


def test_the_check_is_actually_wired_into_the_answer() -> None:
    """만들어 놓고 안 부르면 없는 것과 같다."""
    import inspect

    source = inspect.getsource(BrowserAgent.run)
    assert "_grounding_with_carry" in source  # 안에서 `_listed_entity_grounding_check` 를 원장과 함께 부른다
