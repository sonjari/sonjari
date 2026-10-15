"""맡긴 쪽이 밝힌 「돌려받아야 할 것」 · 나가기 전 정제 · 한 줄 영수증 (2026-10-15 · 전략안 §55-32).

대표의 설계: 「Claude 가 MCP 로 시킬 때 이 정보는 꼭 들어가야 한다를 잡아 두고, 손자리가 검증해서 안 보내면 과제가 실패할 수
있다 · 안 나가도 되는 것은 정제해서 보낸다.」 Claude 가 다듬은 것: 무엇이 민감한가를 작은 모델에게 맡기지 않는다 — 정해진 규칙으로.

지키는 약속:
- `sonjari_task` 에 `needs`(돌려받아야 할 항목 이름 목록) 칸이 있다. MCP 문은 그것을 `/v1/chat` 에 그대로 싣고, 요청 모델이 받아 잡에 남긴다.
- 끝난 잡의 요약은 항목마다 채웠는지(`needs`)를 돌려준다. 채웠다 = 답의 표 머리에 그 이름이 있고 그 칸에 값이 하나라도 있다,
  또는 「이름: 값」 줄이 있다. 하나라도 비면 상태는 그대로 두고 메모로 알린다(맡긴 쪽이 다시 맡길지 정한다).
- 나가는 답에서 정해진 모양을 가린다: 주민등록번호 · 카드 번호 · 비밀 키는 **늘**, 전화번호 · 메일 주소는 **needs 가 밝히지 않았으면**.
  가린 자리는 「[가림: 종류]」로 남기고 종류별 개수를 `refined` 로 돌려준다. 값 · 날짜 · 주문번호 같은 숫자는 건드리지 않는다.
- 요약에 `receipt` 가 있다: 필요한 것 채움 수 · 정제한 수 · 화면에 쓸 한 줄. 「이 PC 에 남긴 원문」 숫자는 역검증 전이라 한 줄에 싣지 않는다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from alture_jarvis.delegation import TASK_TOOL, summarize_job
from alture_jarvis.outbound import check_needs, refine

FAKE_KEY = "sk-ant-api03-" + "EXAMPLE" * 6
TABLE = (
    "| 가게 | 상품 이름 | 판매 가격 | 주소 |\n"
    "|---|---|---|---|\n"
    "| 다나와 | 무선 마우스 | 129,000원 | https://prod.danawa.com/info/?pcode=1 |\n"
    "| 11번가 | 무선 마우스 |  | https://www.11st.co.kr/products/1 |\n"
)


def _job(answer: str, needs: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": "가격을 찾아 표로"}
    if needs is not None:
        payload["needs"] = needs
    return {
        "id": "j1", "status": "completed", "payload": payload,
        "result": {"answer": answer, "agent_trace": {
            "steps": [{"tool": "browser_extract", "ok": True, "evidence": {"url": "https://prod.danawa.com/info/?pcode=1"},
                       "evidence_record": {"effect": "read", "source_id": "https://prod.danawa.com/info/?pcode=1"}}],
            "tool_numbers": ["129000", "1", "11"]}},
    }


# ── 정제 ─────────────────────────────────────────────────────────────────────────────


def test_secrets_are_always_hidden_and_counted() -> None:
    text = f"키는 {FAKE_KEY} 이고 주민번호 900101-1234567, 카드 4111 1111 1111 1111 입니다."
    cleaned, found = refine(text, needs=["주민번호", "카드 번호", "키"])
    assert FAKE_KEY not in cleaned and "900101-1234567" not in cleaned and "4111 1111 1111 1111" not in cleaned
    assert "[가림:" in cleaned
    assert {item["kind"]: item["count"] for item in found} == {"비밀 키": 1, "주민등록번호": 1, "카드 번호": 1}


def test_contacts_are_hidden_unless_the_caller_asked_for_them() -> None:
    text = "담당자 전화 010-1234-5678 · 메일 someone@example.com"
    hidden, found = refine(text)
    assert "010-1234-5678" not in hidden and "someone@example.com" not in hidden
    assert {item["kind"] for item in found} == {"전화번호", "메일 주소"}

    kept, found = refine(text, needs=["담당자 연락처", "이메일"])
    assert kept == text and found == []


def test_prices_dates_and_order_numbers_are_untouched() -> None:
    text = "판매가 129,000원 · 2026-10-15 기준 · 주문번호 20261015123456 · 모델 MX3S-2024"
    cleaned, found = refine(text)
    assert cleaned == text and found == []


# ── 돌려받아야 할 것 ───────────────────────────────────────────────────────────────────


def test_a_need_is_met_by_a_filled_table_column_or_a_labelled_line() -> None:
    answer = TABLE + "\n배송비: 무료\n"
    checked = {item["label"]: item["met"] for item in check_needs(["상품 이름", "가격", "배송비", "리뷰 수"], answer)}
    assert checked == {"상품 이름": True, "가격": True, "배송비": True, "리뷰 수": False}


def test_a_column_with_only_blanks_does_not_count() -> None:
    answer = "| 가게 | 재고 |\n|---|---|\n| 다나와 | - |\n| 11번가 |  |\n"
    assert check_needs(["재고"], answer) == [{"label": "재고", "met": False}]


# ── 요약에 실리는 것 ────────────────────────────────────────────────────────────────────


def test_the_summary_reports_needs_refines_and_carries_a_receipt() -> None:
    summary = summarize_job(_job(TABLE + "\n문의: 010-1234-5678", needs=["상품 이름", "가격", "리뷰 수"]))
    assert summary["needs"] == [{"label": "상품 이름", "met": True}, {"label": "가격", "met": True},
                                {"label": "리뷰 수", "met": False}]
    assert "010-1234-5678" not in summary["answer"]
    assert summary["refined"] == [{"kind": "전화번호", "count": 1}]
    assert any("리뷰 수" in note for note in summary.get("review_notes") or [])
    receipt = summary["receipt"]
    assert receipt["needs_met"] == 2 and receipt["needs_total"] == 3 and receipt["refined"] == 1
    assert "필요한 것 2/3" in receipt["line"] and "정제 1" in receipt["line"]
    assert "원문" not in receipt["line"], "남긴 원문 숫자는 역검증 전에는 한 줄에 싣지 않는다"


def test_without_needs_the_summary_still_refines_and_has_no_needs_field() -> None:
    summary = summarize_job(_job("담당 메일 someone@example.com 로 보내세요"))
    assert "needs" not in summary
    assert summary["refined"] == [{"kind": "메일 주소", "count": 1}]
    assert summary["receipt"]["needs_total"] == 0
    assert "필요한 것" not in summary["receipt"]["line"]


def test_a_clean_answer_has_an_empty_refined_list() -> None:
    summary = summarize_job(_job(TABLE, needs=["가격"]))
    assert summary["refined"] == []
    assert summary["status"] == "done"


# ── 칸이 끝까지 흘러가는가 ──────────────────────────────────────────────────────────────


def test_the_task_tool_offers_a_needs_list() -> None:
    needs = TASK_TOOL["parameters"]["properties"]["needs"]
    assert needs["type"] == "array" and needs["items"]["type"] == "string"
    assert "needs" not in TASK_TOOL["parameters"]["required"]


def test_the_chat_request_keeps_needs() -> None:
    from alture_jarvis.api import ChatRequest

    request = ChatRequest(prompt="가격 찾아", origin="mcp", needs=["가격", "주소"])
    assert request.model_dump()["needs"] == ["가격", "주소"]


def test_the_mcp_door_passes_needs_through() -> None:
    from alture_jarvis.mcp_server import JarvisMcpBridge

    class _Client:
        def __init__(self) -> None:
            self.posts: list[dict[str, Any]] = []

        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:  # noqa: A002
            self.posts.append(json)

            class _R:
                status_code = 200

                @staticmethod
                def json() -> dict[str, Any]:
                    return {"id": "j9"}

            return _R()

        async def aclose(self) -> None:
            return None

    client = _Client()
    bridge = JarvisMcpBridge(token="t", client=client)
    text, failed = asyncio.run(bridge.call("sonjari_task", {"task": "가격 찾아", "needs": ["가격", " 주소 ", ""]}))
    assert not failed, text
    assert json.loads(text)["job_id"] == "j9"
    assert client.posts[0]["needs"] == ["가격", "주소"]


# ── 화면의 한 줄 영수증 ────────────────────────────────────────────────────────────────


def test_the_answer_record_carries_the_same_receipt_for_delegated_jobs_only() -> None:
    from alture_jarvis.outbound import outbound_record

    payload = {"origin": "mcp", "caller": "claude-code", "needs": ["가격", "리뷰 수"]}
    record = outbound_record(TABLE + "\n문의 010-1234-5678", payload)
    assert record == {"host": "claude-code", "needs": [{"label": "가격", "met": True}, {"label": "리뷰 수", "met": False}],
                      "refined": [{"kind": "전화번호", "count": 1}], "needs_total": 2, "needs_met": 1, "refined_count": 1}
    summary = summarize_job({**_job(TABLE + "\n문의 010-1234-5678", needs=["가격", "리뷰 수"]),
                             "payload": {"prompt": "가격", **payload}})
    assert summary["needs"] == record["needs"] and summary["refined"] == record["refined"]
    assert outbound_record("답", {"origin": "voice"}) is None
    assert outbound_record("답", None) is None
