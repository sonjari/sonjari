"""문서 쓰기 승인 카드는 **어디에 무슨 파일이 생기는지** 보이고, 실패가 정해진 일은 묻지 않는다 (2026-09-30 촬영 판).

새 가짜 홈 촬영에서 모델이 `local_write_document` 를 `path` 없이 `blocks`(내용)만 넣어 불렀다.
- 위험도: 경로를 못 풀어 「모르는 경로 → 승인」으로 올렸다.
- 카드: 「문서 만들기 · 미리보기 없음 · 자세히에서 확인」만 — 위치가 없었다.
- 사람이 눌렀다면: 쓰기는 `path_required` 로 **반드시 실패** — 실패가 정해진 일을 승인받는 셈이었다.
파일 이름만 준 판은 실제로 `문서\\Sonjari` 에 쓰는데 카드 설명은 「작업 폴더에 쓰기」라고 틀리게 적었다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import ApprovalRequired, JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.tool_gateway import ToolGateway

BLOCKS = [{"type": "heading", "level": 1, "text": "교보문고 파이썬 도서"},
          {"type": "table", "rows": [["제목", "판매가"], ["점프 투 파이썬", "19,800원"]]}]


def _setup(tmp_path: Path, monkeypatch) -> tuple[LocalComputerTools, ToolGateway, JobStore, str]:
    monkeypatch.setattr("alture_jarvis.local_computer.os.startfile", lambda p: None, raising=False)
    tools = LocalComputerTools(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        documents_dir=tmp_path / "documents", local_computer_enabled=True,
    ))
    store = JobStore(tmp_path / "j.db")
    gateway = ToolGateway(store, EventBus())
    tools.register(gateway)
    job = store.create_job("chat", "엑셀로 정리", {"prompt": "교보문고에서 파이썬 책 3권"})
    return tools, gateway, store, job["id"]


def test_a_write_without_a_path_is_sent_back_before_any_card(tmp_path, monkeypatch) -> None:
    _tools, gateway, store, job_id = _setup(tmp_path, monkeypatch)

    result = gateway.execute("local_write_document", {"blocks": BLOCKS}, job_id=job_id)

    assert result.ok is False
    assert "path_required" in str(result.error)
    assert store.list_approvals(10, "") == [], "실패가 정해진 일로 사람을 부르면 안 된다"


def test_a_bare_file_name_is_described_as_the_real_folder(tmp_path, monkeypatch) -> None:
    tools, _gateway, _store, _job = _setup(tmp_path, monkeypatch)

    target = tools.describe_document_target({"path": "교보문고_파이썬.xlsx", "blocks": BLOCKS})

    assert target["path"] == str(tools.documents_root / "교보문고_파이썬.xlsx")
    assert target["label"] != "작업 폴더에 쓰기"


def test_a_bare_file_name_goes_to_our_folder_without_a_card(tmp_path, monkeypatch) -> None:
    """이름만 준 문서는 제 결과물 폴더라 L1 — 전처럼 묻지 않고 쓴다(되돌리기는 붙는다)."""
    tools, gateway, store, job_id = _setup(tmp_path, monkeypatch)

    result = gateway.execute("local_write_document", {"path": "교보문고_파이썬.xlsx", "blocks": BLOCKS}, job_id=job_id)

    assert result.ok is True, result.error
    assert (tools.documents_root / "교보문고_파이썬.xlsx").exists()
    assert store.list_approvals(10, "") == []


def test_a_write_outside_our_folder_still_asks_and_the_card_names_the_place(tmp_path, monkeypatch) -> None:
    _tools, gateway, store, job_id = _setup(tmp_path, monkeypatch)
    outside = tmp_path / "elsewhere" / "보고서.docx"

    with pytest.raises(ApprovalRequired) as raised:
        gateway.execute("local_write_document", {"path": str(outside), "blocks": BLOCKS}, job_id=job_id)

    card = gateway.describe_approval(store.get_approval(raised.value.nonce))
    assert card["target"]["path"] == str(outside)
    assert card["arguments"]["path"] == str(outside), "인자는 그대로(승인 뒤 그대로 재실행된다)"
