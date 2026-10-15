"""새 도구는 **열 곳**에 등록해야 한다. 한 곳만 빠져도 조용히 고장난다.

이 저장소가 하루에 네 번, 그리고 여섯 달에 걸쳐 여러 번 물린 함정이다:

    도구를 만들었는데 갈래(라우팅)가 없다      → 모델이 지어낸다
    분류표에 없다                              → 눈금의 분모에서 조용히 빠진다
    `needs_job_context` 에 없다                → 라이브에서 `job_context_required`
    화면 라벨이 없다                            → 걸음에 도구 이름 날것이 뜬다
    `_OUTPUT_TOOLS` 에 없다                     → 「만든 것」 서랍이 조용히 빈다

전부 **조용히** 온다. 에러가 아니라 침묵으로 오기 때문에 사람이 라이브에서
겪고 나서야 안다. 그래서 검사로 박는다.

이 검사는 「모든 도구가 모든 표에 있어야 한다」고 말하지 않는다 — 그건 틀린 규칙이다.
**그 성질을 가진 도구가 그 표에 있는가**를 본다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig


def _local_tools():
    from alture_jarvis.local_computer import LocalComputerTools

    room = Path(tempfile.mkdtemp())
    config = JarvisConfig(
        runtime_root=room,
        data_dir=room / "data",
        output_dir=room / "outputs",
        documents_dir=room / "documents",
        local_computer_enabled=True,
    )
    return LocalComputerTools(config)


def _names(tools) -> set[str]:
    return {str(item["function"]["name"]) for item in tools.ollama_tools}


#: 파일을 만들거나 고치는 도구. 이 성질이면 다섯 표에 다 있어야 한다.
MAKES_A_FILE = {
    "local_write_document",
    "local_edit_document",
    "local_edit_spreadsheet",
    "local_write_file",
    "local_apply_edit",
}

#: 상대 경로를 풀 작업폴더가 필요한 도구. 빠지면 `job_context_required` 로 죽는다.
NEEDS_A_JOB = MAKES_A_FILE | {"local_grep", "local_glob", "local_delete_file"}


def test_the_new_document_tools_actually_exist() -> None:
    """먼저 도구가 있는지부터. 없으면 아래 검사가 전부 헛돈다."""
    names = _names(_local_tools())
    for tool in ("local_write_document", "local_edit_document", "local_edit_spreadsheet"):
        assert tool in names, f"{tool} 가 등록 자체가 안 됐다"


@pytest.mark.parametrize("tool", sorted(NEEDS_A_JOB))
def test_a_tool_that_resolves_paths_gets_its_job_context(tool: str) -> None:
    """★ 제일 안 보이는 자리. 라이브에서 문서 생성이 이걸로 죽었다."""
    import inspect

    from alture_jarvis import local_computer

    source = inspect.getsource(local_computer.LocalComputerTools.register)
    marker = source.split("needs_job_context")[1] if "needs_job_context" in source else ""
    assert f'"{tool}"' in marker, f"{tool} 에 __job_id 가 안 실린다 → job_context_required"


@pytest.mark.parametrize("tool", sorted(MAKES_A_FILE))
def test_a_tool_that_makes_a_file_shows_up_in_the_outputs_drawer(tool: str) -> None:
    """여기 없으면 「만든 파일:」 줄도 화면의 「만든 것」 탭도 빈다."""
    from alture_jarvis.runtime import JarvisRuntime

    assert tool in JarvisRuntime._OUTPUT_TOOLS, f"{tool} 산출물이 화면에 안 뜬다"
    keys = JarvisRuntime._OUTPUT_TOOLS[tool]
    assert any(key in {"path", "output_path"} for key in keys), f"{tool} 의 경로 칸이 없다"


@pytest.mark.parametrize("tool", sorted(MAKES_A_FILE))
def test_a_writing_tool_is_counted_as_writing(tool: str) -> None:
    """분류표에 없으면 그 도구의 실적이 **눈금의 분모에서 통째로 빠진다.**

    2026-08-11 에 `pick_suggestion` 71건이 이 자리에서 빠졌다.
    """
    import inspect

    from alture_jarvis import agent

    assert f'"{tool}"' in inspect.getsource(agent), f"{tool} 이 쓰기로 안 세어진다"


@pytest.mark.parametrize(
    "tool",
    ["local_write_document", "local_edit_document", "local_edit_spreadsheet",
     "local_grep", "local_glob", "browser_download", "google_drive_write"],
)
def test_a_tool_has_a_korean_label_on_screen(tool: str) -> None:
    """라벨이 없으면 걸음에 도구 이름이 날것으로 뜬다."""
    labels = Path("ui/src/trajectory.ts").read_text(encoding="utf-8")
    assert f"{tool}:" in labels, f"{tool} 의 화면 이름이 없다"


def test_a_tool_the_model_must_choose_is_named_in_the_contract() -> None:
    """★ 갈래가 없으면 지어낸다 — 이 저장소가 일곱 번 겪었다.

    2026-09-01: `local_write_document` 를 만들어 뒀는데 자비스는 `sandbox_run` 으로
    python-docx 를 직접 돌렸다. 도구가 있어도 **언제 쓰는지**가 계약에 없으면
    모델은 자기가 아는 길로 간다.
    """
    from alture_jarvis.agent import AGENT_SYSTEM_PROMPT

    for tool in ("local_write_document", "local_edit_document", "google_drive_write"):
        assert tool in AGENT_SYSTEM_PROMPT, f"{tool} 을 언제 쓰는지 계약에 없다"


def test_a_commit_tool_is_paired_with_its_prepare_step() -> None:
    """준비 → 승인 → 커밋. 짝이 없으면 코드가 대신 부를 수 없다."""
    from alture_jarvis.agent import _ACTION_ID_CONSUMER_TO_PRODUCER

    assert (
        _ACTION_ID_CONSUMER_TO_PRODUCER.get("google_drive_write")
        == "google_drive_prepare_write"
    )


def test_a_file_making_tool_is_seen_by_the_plan_layer() -> None:
    """★ 열한 번째 등록 자리 (2026-09-01).

    `plan._ARTIFACT_TOOLS` 에 없으면 문서를 제대로 만들어도 계획 층에는
    **아무것도 안 만든 것**이다. 라이브에서 hwpx 를 만들고도
    「실제 산출물 파일 만들기 — 열 수 있는 산출물 없음」이 찍혔다.
    """
    from alture_jarvis.plan import _ARTIFACT_TOOLS

    for tool in MAKES_A_FILE - {"local_apply_edit", "local_write_file"}:
        assert tool in _ARTIFACT_TOOLS, f"{tool} 산출물이 계획 대조에서 사라진다"


def test_an_outward_action_counts_toward_what_was_asked() -> None:
    """행위 개수를 세는 표에 없으면 「5개 시켰는데 2개」를 못 잡는다."""
    from alture_jarvis.plan import _ACTION_TOOLS

    for tool in ("google_drive_write", "local_edit_document", "local_write_document"):
        assert tool in _ACTION_TOOLS, f"{tool} 이 「했다」로 안 세어진다"
