"""지목한 대상 하나를 지키라는 말이 **판 전체의 손을 뺏으면** 안 된다.

★ 2026-09-03. SWE 벤치는 모든 판에 이 줄을 붙인다:

    테스트 파일은 절대 수정하지 마 — 구현을 고쳐야 한다.

`forbids_writes` 가 이것을 판 전역 정책으로 읽어, 새로 붙은 읽기 전용 관문이
`local_apply_edit`·`local_write_file`·`local_run_project_command`·`sandbox_run`
을 전부 막았다. **고칠 손도 실행할 손도 없이 「고쳐서 통과시켜줘」를 시키는**
상태였다. 과거 187판을 재생해 보니 60판이 읽기 전용으로 묶여 있었고 그중
**56판이 이 오해**였다.

관문 자체는 HEAD 에 없던 새 코드라 한 번도 돌아본 적이 없었다 — 다음 벤치가
첫 실행이었고 0/N 이 나왔을 것이다. [[ci_green_did_not_mean_deployed]] 와 같은
모양이다.

여기서 지키는 것은 둘이다.

    ① 대상 하나에 대한 금지는 판을 묶지 않는다 (손이 살아 있다)
    ② 그렇다고 금지가 사라지지도 않는다 (모델에게 따로 일러 준다)
"""

from __future__ import annotations

import sys
from pathlib import Path

from alture_jarvis.agent import _READ_ONLY_FORBIDDEN_TOOLS
from alture_jarvis.plan import forbids_writes, write_prohibition_scope
from alture_jarvis.task_contract import compile_task_contract

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


#: 실제 벤치가 쓰는 문장 그대로. 벤치 문구가 바뀌면 이 검사도 같이 깨져야 한다.
SWE_ASKS = [
    "이 저장소에서 다음 테스트가 실패한다:\n\n    tests/test_sandbox.py\n\n"
    "원인을 찾아 소스를 고쳐서 이 테스트를 통과시켜줘.\n"
    "테스트 파일은 절대 수정하지 마 — 구현을 고쳐야 한다.\n"
    "고친 뒤 그 테스트를 실제로 실행해 통과를 확인해줘.",
    "INSTRUCTIONS.md 를 읽고 book_store.py 를 구현해줘. 테스트 파일은 수정하지 마. "
    "테스트를 실행해 전부 통과시켜줘.",
    "unique_tags가 입력 순서를 보존하며 중복을 제거하게 고쳐줘. "
    "기존 공개 테스트 파일은 수정하지 말고 그대로 실행해 검증해줘.",
]

#: 진짜로 판 전체를 묶은 말. 이쪽이 느슨해지면 2026-09-02 사고가 재발한다
#: (조사만 시켰는데 xlsx·docx 두 개가 생겼다).
JOB_WIDE_ASKS = [
    "복합 분석 실전 점검이다. 파일을 수정하거나 외부 서비스에 쓰지 말고 조사·분석만 해라.",
    "이 문서 읽고 핵심 3개를 채팅으로 정리해줘. 파일 수정이나 외부 서비스 쓰기는 하지 마.",
    "이 판에서는 파일을 수정하지 마",
    "읽기 전용으로 봐줘",
]


def test_the_bench_prompt_the_repo_actually_ships_is_not_job_wide() -> None:
    """벤치 스크립트가 **지금** 붙이는 문장 그대로 확인한다.

    문구를 이 파일에 베껴 두면 벤치가 바뀔 때 같이 안 깨진다. 그래서 빌더를
    직접 부른다 — 케이스 목록(JSON)은 없을 수 있으니 만들지 않는다.
    """
    from bench_repo_swe import build_prompt  # noqa: PLC0415
    from repo_swe_bench_cases import RepoSweSpec  # noqa: PLC0415

    spec = RepoSweSpec(
        commit="0" * 40,
        parent="1" * 40,
        subject="fix: 무언가",
        source_files=("tools/alture-jarvis/src/alture_jarvis/plan.py",),
        test_files=("tools/alture-jarvis/tests/test_plan.py",),
        failure_head="AssertionError: 무언가",
    )
    prompt = build_prompt(spec)

    assert "수정하지 마" in prompt, "벤치가 더 이상 금지 문구를 안 붙인다 — 검사를 고칠 것"
    assert write_prohibition_scope(prompt) == "clause", (
        "벤치 문장이 판 전역 금지로 읽힌다 — 손이 전부 막힌다: " + prompt[:200]
    )
    assert forbids_writes(prompt) is False


def test_the_bench_keeps_every_hand_it_needs() -> None:
    """막히는 손이 하나라도 있으면 그 벤치는 0점이 나온다."""
    from bench_repo_swe import REQUIRED_TOOLS  # noqa: PLC0415

    for prompt in SWE_ASKS:
        if not forbids_writes(prompt):
            continue
        blocked = sorted(REQUIRED_TOOLS & _READ_ONLY_FORBIDDEN_TOOLS)
        assert not blocked, f"{blocked} 가 막힌다: {prompt[:60]}"


def test_a_scoped_prohibition_is_carried_not_dropped() -> None:
    """막지 않는 것과 잊는 것은 다르다."""
    for prompt in SWE_ASKS:
        assert write_prohibition_scope(prompt) == "clause"
        assert compile_task_contract(prompt).side_effect_policy == "scoped"


def test_a_job_wide_prohibition_still_takes_the_hands() -> None:
    for prompt in JOB_WIDE_ASKS:
        assert write_prohibition_scope(prompt) == "job", prompt
        assert forbids_writes(prompt) is True
        assert compile_task_contract(prompt).side_effect_policy == "read_only"


def test_a_forbidden_verb_is_never_work_in_either_scope() -> None:
    """금지절의 「수정」을 할 일로 뽑으면 그림자 계약부터 오탐을 재현한다."""
    for prompt in SWE_ASKS + JOB_WIDE_ASKS:
        contract = compile_task_contract(prompt)
        guilty = [
            clause.quote
            for clause in contract.clauses
            if "mutate_or_create" in clause.operations
            and write_prohibition_scope(clause.quote)
        ]
        assert not guilty, guilty


def test_the_agent_tells_the_model_about_a_scoped_prohibition() -> None:
    """★ 봉쇄를 푸는 대가로 사용자의 보호가 사라지면 안 된다."""
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    assert 'elif write_scope == "clause":' in source
    assert "agent_scoped_write_prohibition" in source


def test_keep_the_old_rows_is_not_a_ban_on_writing_the_file() -> None:
    """★ 10-02 레딧 기록 예약 시험: 「파일이 있으면 기존 행은 지우지 말고 덧붙여」가 판 전체 읽기 전용이 됐다."""
    ask = ("C:/Users/me/Documents/reddit.xlsx 에 오늘 날짜로 기록해줘. 시트는 둘로 나눠. "
           "파일이 이미 있으면 기존 행은 지우지 말고 아래에 덧붙여.")
    assert write_prohibition_scope(ask) == "clause"
    assert forbids_writes(ask) is False
    # 파일 자체를 막은 말은 그대로 판 전체다.
    assert write_prohibition_scope("파일을 수정하거나 외부 서비스에 쓰지 말고 조사만 해라.") == "job"
    assert write_prohibition_scope("이 판에서는 파일을 만들지 마.") == "job"
