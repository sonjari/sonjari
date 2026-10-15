"""되돌릴 수 있으면 미리 묻지 않아도 된다 — 그 토대.

자비스는 사용자님 진짜 계정·진짜 블로그 위에서 돈다. 클라우드 VM 안의 에이전트는
틀리면 VM 을 버리면 되지만 여기서는 그럴 수가 없어서, 지금까지 **되돌릴 수 없으니
미리 물어보는 것**으로 대신해 왔다(L2 승인 15개).

그런데 실제로는 대부분 되돌릴 수 있다. 만든 일정은 지우면 되고 임시저장은 목록에서
빼면 된다. 역동작을 아무도 안 짜놨을 뿐이다. **자율성은 더 대담해져서 얻는 게
아니라 되돌릴 수 있어서 얻는 것이다.**

여기서 지키는 것:

  1. 성공한 커밋은 되돌릴 손잡이를 남긴다
  2. 무엇을 되돌릴지 모르면 **버튼을 안 만든다** — 눌러도 아무 일 없는 버튼이 최악
  3. 되돌리기는 **한 번만** 먹는다 (두 번 되돌리면 그게 새 사고다)
  4. 자동으로 못 되돌리는 것은 그렇다고 말하고 사람이 할 일을 알려 준다
  5. 되돌릴 수 없는 도구(메일 발송)에는 명세를 아예 안 단다
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import InverseSpec, ToolGateway, ToolSpec, UndoUnverified


def _gateway() -> ToolGateway:
    store = JobStore(Path(tempfile.mkdtemp()) / "jobs.db")
    return ToolGateway(store, EventBus())


def _register(gateway: ToolGateway, **kwargs: Any) -> list[dict[str, Any]]:
    undone: list[dict[str, Any]] = []

    def _undo(handle: dict[str, Any]) -> dict[str, Any]:
        undone.append(handle)
        return {"deleted": True}

    gateway.register(
        ToolSpec(
            name="calendar_create",
            description="일정 만들기",
            risk_level=RiskLevel.L1,
            handler=lambda a: dict(a),
            inverse=InverseSpec(
                label="방금 만든 일정 삭제",
                handle_from=lambda r: ({"event_id": r["event_id"]} if r.get("event_id") else None),
                undo=_undo if kwargs.get("automatic", True) else None,
                manual_hint=kwargs.get("manual_hint", ""),
            ),
        )
    )
    return undone


def test_a_successful_commit_leaves_a_way_back() -> None:
    gateway = _gateway()
    _register(gateway)
    gateway.execute("calendar_create", {"event_id": "evt-1"})

    offers = gateway.store.list_undo_offers()
    assert len(offers) == 1
    assert offers[0]["tool"] == "calendar_create"
    assert offers[0]["handle"] == {"event_id": "evt-1"}


def test_no_button_when_we_do_not_know_what_to_undo() -> None:
    """저장이 확인 안 돼 손잡이를 못 뽑으면 되돌리기를 안 내준다.

    눌러도 아무 일 없는 버튼은 없느니만 못하다 — 되돌렸다고 믿게 만든다.
    """
    gateway = _gateway()
    _register(gateway)
    gateway.execute("calendar_create", {})  # event_id 없음
    assert gateway.store.list_undo_offers() == []


def test_undo_actually_runs_the_inverse() -> None:
    gateway = _gateway()
    undone = _register(gateway)
    gateway.execute("calendar_create", {"event_id": "evt-2"})
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]

    out = gateway.undo(undo_id)
    assert out["ok"] is True
    assert undone == [{"event_id": "evt-2"}]


def test_undo_only_works_once() -> None:
    """두 번 되돌리면 되돌리기가 스스로 새로운 사고가 된다."""
    gateway = _gateway()
    undone = _register(gateway)
    gateway.execute("calendar_create", {"event_id": "evt-3"})
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]

    assert gateway.undo(undo_id)["ok"] is True
    second = gateway.undo(undo_id)
    assert second["ok"] is False
    assert second["error"] == "undo_not_found_or_expired"
    assert len(undone) == 1, "역동작이 두 번 돌았다"


def test_an_attempt_we_could_not_verify_is_neither_failed_nor_retryable() -> None:
    """역동작은 실행됐으므로 재사용은 막되, 확인 실패를 실행 실패로 쓰지 않는다."""
    gateway = _gateway()
    attempts: list[dict[str, Any]] = []

    def _unverified(handle: dict[str, Any]) -> None:
        attempts.append(handle)
        raise UndoUnverified({"action": "undo_toggle", "verification": "unverified"})

    gateway.register(
        ToolSpec(
            name="toggle",
            description="토글",
            risk_level=RiskLevel.L1,
            handler=lambda arguments: dict(arguments),
            inverse=InverseSpec(
                label="토글 되돌리기",
                handle_from=lambda result: dict(result),
                undo=_unverified,
            ),
        )
    )
    gateway.execute("toggle", {"ref": "j20"})
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]

    out = gateway.undo(undo_id)

    assert out["ok"] is True, "클릭 실행 자체를 실패로 보고하면 안 된다"
    assert out["verified"] is False
    assert out["status"] == "attempted_unverified"
    assert gateway.undo(undo_id)["error"] == "undo_not_found_or_expired"
    assert attempts == [{"ref": "j20"}], "확인 불능인 역동작은 정확히 한 번만 실행한다"


def test_a_manual_inverse_says_so_instead_of_pretending() -> None:
    gateway = _gateway()
    _register(gateway, automatic=False, manual_hint="임시저장 목록에서 방금 글을 지워 주세요.")
    gateway.execute("calendar_create", {"event_id": "evt-4"})
    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]

    out = gateway.undo(undo_id)
    assert out["ok"] is False
    assert out["error"] == "undo_is_manual"
    assert "임시저장 목록" in out["hint"]


def test_a_tool_with_no_inverse_leaves_nothing() -> None:
    """메일 발송처럼 진짜 못 되돌리는 것은 명세를 안 단다."""
    gateway = _gateway()
    gateway.register(
        ToolSpec(
            name="gmail_send",
            description="메일 발송",
            risk_level=RiskLevel.L2,
            handler=lambda a: {"message_id": "m1"},
        )
    )
    gateway.store.create_approval(
        nonce="n1", job_id="", tool_name="gmail_send", arguments={}, expires_at=9e9
    )
    gateway.store.decide_approval("n1", True)
    gateway.execute("gmail_send", {})
    assert gateway.store.list_undo_offers() == []


def test_a_broken_inverse_never_fails_the_original_action() -> None:
    """되돌리기를 못 적었다고 이미 한 일을 실패로 만들면 더 나쁜 거짓말이 된다."""
    gateway = _gateway()
    gateway.register(
        ToolSpec(
            name="boom",
            description="터지는 역동작",
            risk_level=RiskLevel.L1,
            handler=lambda a: {"event_id": "e"},
            inverse=InverseSpec(
                label="x",
                handle_from=lambda r: (_ for _ in ()).throw(RuntimeError("nope")),
            ),
        )
    )
    result = gateway.execute("boom", {})
    assert result.ok is True
    assert gateway.store.list_undo_offers() == []


# ── 임시저장은 승인 없이, 대신 되돌리는 법을 알려 준다 ────────────────────────
#
# 등급을 "파괴적인가"가 아니라 "되돌릴 수 있는가"로 다시 매긴 첫 사례.
#
# ★ 자동 되돌리기를 안 붙인 것은 실제 화면을 열어 보고 정한 것이다(2026-08-10):
#   - 편집 모드에서 글 행이 접근성 트리에 안 잡힌다(제목으로 찾으면 0 매치)
#   - '전체 삭제'가 '선택 삭제' 바로 옆이라, 조준이 틀리면 임시저장이 통째로 날아간다
#   - 되돌릴 대상은 아무에게도 안 보이는 임시저장이다
#   되돌리기가 되돌릴 대상보다 위험하면 그건 나쁜 거래다.


def _blog_tools():
    import tempfile
    from pathlib import Path

    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.external_actions import ExternalActionStore
    from alture_jarvis.naver_blog import NaverBlogTools

    root = Path(tempfile.mkdtemp())
    config = JarvisConfig(runtime_root=root, data_dir=root / "data", output_dir=root / "out")
    return NaverBlogTools(config, object(), object(), ExternalActionStore(root / "a.db"))


def test_saving_a_draft_no_longer_asks_for_approval() -> None:
    from alture_jarvis.models import RiskLevel

    gateway = _gateway()
    _blog_tools().register(gateway)
    tools = {row["name"]: row for row in gateway.list_tools()}
    assert tools["naver_blog_save_draft"]["risk_level"] == RiskLevel.L1.label()
    # 발행은 그대로 승인. 되돌려도 그 사이에 본 사람은 못 되돌린다.
    assert tools["naver_blog_publish"]["risk_level"] == RiskLevel.L2.label()


def test_the_draft_undo_names_the_post_and_admits_it_is_manual() -> None:
    inverse = _blog_tools()._inverses()["naver_blog_save_draft"]
    handle = inverse.handle_from({"status": "draft_saved", "title": "2학기 개학 전 상담 3가지"})
    assert handle == {"title": "2학기 개학 전 상담 3가지"}
    assert inverse.undo is None, "자동으로 지우려 들면 '전체 삭제'를 누를 위험이 생긴다"
    assert "선택 삭제" in inverse.manual_hint, "어떻게 지우는지 실제 절차를 알려 줘야 한다"


def test_an_unverified_save_offers_no_undo() -> None:
    """저장됐는지 모르는데 '되돌리기'를 내밀면 뭘 지우라는 건지 알 수 없다."""
    inverse = _blog_tools()._inverses()["naver_blog_save_draft"]
    assert inverse.handle_from({"status": "unknown", "title": "x"}) is None
    assert inverse.handle_from({"status": "draft_saved", "title": ""}) is None


# ── 발행도 돌아갈 길을 남긴다 (2026-08-15) ──────────────────────────────────
#
# 그 전까지 발행은 **아무것도 안 남겼다.** "본 사람은 못 되돌린다"는 이유로 명세
# 자체를 안 달아 뒀는데, 그건 자동 되돌리기를 안 하는 근거는 되어도 **어느 글이었는지
# 조차 안 적을** 근거는 아니다. 되돌리려면 먼저 찾을 수 있어야 한다.


def test_publishing_leaves_a_way_back_that_names_the_post() -> None:
    inverse = _blog_tools()._inverses()["naver_blog_publish"]
    handle = inverse.handle_from(
        {"status": "published", "url": "https://blog.naver.com/me/223", "title": "학원 데이터 3원칙"}
    )
    assert handle == {"url": "https://blog.naver.com/me/223", "title": "학원 데이터 3원칙"}
    assert inverse.undo is None, "셀렉터를 확인하기 전에는 자동으로 누르지 않는다"
    assert "비공개" in inverse.manual_hint
    assert "본 사람은 되돌릴 수 없습니다" in inverse.manual_hint


def test_an_unverified_publish_offers_no_undo() -> None:
    """발행됐는지 모르는데 '내리기'를 내밀면 어디로 가야 할지 알 수 없다."""
    inverse = _blog_tools()._inverses()["naver_blog_publish"]
    assert inverse.handle_from({"status": "published"}) is None
    assert inverse.handle_from({"status": "unknown", "url": "https://blog.naver.com/me/223"}) is None


def test_a_duplicate_commit_does_not_grow_a_second_button() -> None:
    """★ 중복 커밋은 아무것도 안 한다 — 앞선 커밋의 결과를 그대로 돌려받을 뿐이다.

    그 결과에도 event_id 가 들어 있어서, 막지 않으면 **일정 하나에 되돌리기
    버튼이 둘** 생긴다. 하나를 누르는 순간 나머지는 눌러도 아무 일 없는 버튼이
    된다 — 이 파일이 규칙 2로 금지한 바로 그것이다.

    2026-08-20 에 같은 지시가 일정 두 건을 만들었고, 그 재발을 막는 코드가
    두 번째 커밋을 duplicate 로 돌려보내면서 이 자리가 새로 생겼다.
    """
    gateway = _gateway()
    _register(gateway)
    gateway.execute("calendar_create", {"event_id": "evt-1"})
    gateway.execute("calendar_create", {"event_id": "evt-1", "duplicate_commit": True})

    offers = gateway.store.list_undo_offers()
    assert len(offers) == 1, "안 한 일에도 되돌리기가 달렸다"
    assert offers[0]["handle"] == {"event_id": "evt-1"}


def test_the_real_commits_undo_still_works_after_a_duplicate() -> None:
    gateway = _gateway()
    undone = _register(gateway)
    gateway.execute("calendar_create", {"event_id": "evt-9"})
    gateway.execute("calendar_create", {"event_id": "evt-9", "duplicate_commit": True})

    undo_id = gateway.store.list_undo_offers()[0]["undo_id"]
    assert gateway.undo(undo_id)["ok"] is True
    assert undone == [{"event_id": "evt-9"}]
