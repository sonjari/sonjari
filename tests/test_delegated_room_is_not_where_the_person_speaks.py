"""바깥 AI 가 맡긴 판의 방을 **보는** 것은 거기서 **말하겠다**는 뜻이 아니다 (2026-10-09).

화면이 맡긴 판을 사람이 보던 대화에 끼워 넣지 않고 제 방으로 열게 됐다. 그러면 사람이 그 방을 보고 있는 동안 화면은
「이 대화를 보고 있다」고 서버에 알린다 — 그대로 받으면 말로 시킨 것이 과제 방으로 들어간다.
"""
from __future__ import annotations

import inspect
import time

from alture_jarvis import mcp_server
from alture_jarvis.memory import DELEGATED_ROOM_PREFIX
from alture_jarvis.runtime import JarvisRuntime


class _Bare:
    """`note_workspace_presence` 가 만지는 것만 가진 껍데기 — 런타임 전체를 띄우지 않는다."""

    def __init__(self) -> None:
        self._workspace_presence: tuple[str, float] = ("", 0.0)

    def __getattr__(self, name: str):  # noqa: ANN204 — 그 밖의 속성은 아무거나 받아 준다
        return _Anything()


class _Anything:
    def __getattr__(self, name: str):  # noqa: ANN204
        return _Anything()

    def __call__(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN204
        return _Anything()

    def __setattr__(self, name: str, value) -> None:  # noqa: ANN001
        return None


def _note(runtime: _Bare, session_id: str) -> None:
    try:
        JarvisRuntime.note_workspace_presence(runtime, session_id)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — 자리 기록 뒤의 부가 처리는 이 검사의 대상이 아니다
        pass


def test_the_room_name_is_the_one_the_mcp_server_hands_out() -> None:
    assert DELEGATED_ROOM_PREFIX == "mcp-"
    assert 'f"mcp-{uuid.uuid4().hex[:12]}"' in inspect.getsource(mcp_server)


def test_looking_at_a_delegated_room_keeps_the_person_where_they_were() -> None:
    runtime = _Bare()
    _note(runtime, "office-main")
    assert runtime._workspace_presence[0] == "office-main"

    before = time.time()
    _note(runtime, "mcp-0123456789ab")

    session, seen_at = runtime._workspace_presence
    assert session == "office-main"          # 사람의 자리는 그대로
    assert seen_at >= before                  # 화면이 살아 있다는 사실은 받는다


def test_a_person_room_still_moves_the_presence() -> None:
    runtime = _Bare()
    _note(runtime, "office-main")
    _note(runtime, "mcp-0123456789ab")
    _note(runtime, "second-chat")
    assert runtime._workspace_presence[0] == "second-chat"


def test_with_nothing_before_it_the_delegated_room_does_not_become_the_place() -> None:
    runtime = _Bare()
    _note(runtime, "mcp-0123456789ab")
    assert runtime._workspace_presence[0] == ""


def test_the_queue_event_says_who_asked() -> None:
    source = inspect.getsource(JarvisRuntime)
    at = source.index('"job_queued",')
    assert '"caller": str(payload.get("caller") or "")[:80]' in source[at:at + 900]


def test_the_job_list_says_which_mode_and_folder_each_job_runs_in(tmp_path) -> None:  # noqa: ANN001
    """화면의 작업 창이 맡긴 판의 폴더를 보이려면 목록이 그것을 실어야 한다."""
    from alture_jarvis.jobs import JobStore

    store = JobStore(tmp_path / "jarvis.db")
    store.create_job("chat", "delegated", {"origin": "mcp", "workspace_mode": "code", "code_workspace": "C:/copy/repo"})
    store.create_job("chat", "plain", {"origin": "chat"})
    rows = {row["title"]: row for row in store.list_job_summaries()}

    assert (rows["delegated"]["workspace_mode"], rows["delegated"]["code_workspace"]) == ("code", "C:/copy/repo")
    assert (rows["plain"]["workspace_mode"], rows["plain"]["code_workspace"]) == ("", "")
