"""답 끝의 「대조 덩어리」를 받는 쪽에 맞게 나눈다 (2026-10-24 · 전략안 §55-44).

판이 끝나면 하네스가 답 끝에 대조표(「시킨 것 대조」 · 「Checklist」)와 「읽었나」 경고(읽지 않고 적은 이름 · 이번에 열지 않은
주소 · 열지 않은 곳의 줄 · 「N개 중 M개만 실제로 열어 읽었습니다」 · 「X에서 읽은 것이 하나도 없습니다」 · 조건 · 줄 값 대조)를
이어 붙였다. 그 글이 손자리 창에도, 바깥 AI(MCP)에게 가는 결과에도 똑같이 들어갔다 — 창에서 읽는 사람에게는 덩어리가 너무 컸다.

받는 쪽이 셋이다.
- **바깥 AI 가 맡긴 판**(`origin == "mcp"` · 디스코드 다리 제외): 덩어리는 바깥 AI 에게만 간다(지금까지와 글자까지 같은 답).
  창에 남는 답에는 안 붙인다.
- **사람이 시킨 판**(창 · 예약 · 지켜보기 · 디스코드): 덩어리 대신 한 줄(「시킨 것 3개 중 2개 ✓ · 못 한 것: …」) — 다 했으면 아무것도.
- **판 기록**: 둘 다 남는다 — `result.answer`(창에 보인 답) · `result.host_answer`(덩어리까지 든 답, 다를 때만) ·
  `verification.checks_line`(한 줄).

자르는 자리는 낱말로 찾지 않는다 — 붙일 때 보이지 않는 표(사용자 영역 글자 둘)로 감싸 두고, 판이 끝나는 한 자리에서 나눈다.
붙인 뒤에 답을 다듬는 단계(표 구분줄 고치기 · 새는 생각 걷기 · 「만든 파일」 붙이기 …)는 그 표를 건드리지 않는다.

바깥 AI 의 MCP 연결 프로세스는 클로드가 띄워 며칠씩 산다(옛 코드). 그 프로세스는 백엔드의 일 조회 문을 토큰 없이 읽고, 그 문이
`outbound.outbound_job_view` 로 사본을 만든다 — 여기서 받는 쪽에 맞는 답을 고르므로 옛 연결도 대조표를 잃지 않는다.
"""

from __future__ import annotations

import re
from typing import Any

#: 덩어리를 감싸는 표 — 유니코드 사용자 영역(모델 · 사람 글에 안 나오는 자리). 화면 · 바깥으로 나가기 전에 늘 걷힌다.
OPEN = ""
CLOSE = ""
_BLOCK = re.compile(re.escape(OPEN) + r"(.*?)" + re.escape(CLOSE), re.S)
_MARKS = re.compile("[" + re.escape(OPEN + CLOSE) + "]")

#: 사람이 시킨 판의 창에 덩어리 대신 보이는 한 줄의 머리(`plan.summary_line`). 다음 턴에 모델에게 갈 때 떼는 자리
#: (`memory.without_our_tail`)와 숫자를 세지 않는 자리(`delegation._OUR_CHECKLIST`)가 같은 머리를 본다.
SUMMARY_LINE_HEAD = re.compile(r"(?:시킨 것 \d+개 중 \d+개 ✓|Requested \d+ · done \d+ ✓)")

#: 디스코드 다리가 맡긴 판의 호스트 이름 — 다리는 `ChatRequest.origin` 이 디스코드를 못 받아 `mcp` 를 빌려 쓴다(`savings_receipt`).
DISCORD_CALLER = "Discord"


def wrap(block: str) -> str:
    """붙일 덩어리를 표로 감싼다. 빈 글이면 빈 글."""
    return f"{OPEN}{block}{CLOSE}" if block else ""


def has_blocks(answer: str) -> bool:
    return OPEN in (answer or "")


def full(answer: str) -> str:
    """덩어리까지 든 답(지금까지 바깥 AI 가 받던 글 그대로) — 표만 걷는다."""
    return _MARKS.sub("", answer or "")


def screen(answer: str, line: str = "") -> str:
    """창에 보일 답 — 덩어리를 걷고, 한 줄이 있으면 **마지막 덩어리 자리**에 둔다."""
    text = answer or ""
    spans = list(_BLOCK.finditer(text))
    if not spans:
        return _MARKS.sub("", text)
    last = spans[-1]
    out: list[str] = []
    cursor = 0
    for span in spans:
        out.append(text[cursor:span.start()])
        if span is last and line:
            out.append("\n\n" + line.strip())
        cursor = span.end()
    out.append(text[cursor:])
    return _MARKS.sub("", "".join(out))


def outside_ai(payload: Any) -> bool:
    """바깥 AI 가 맡긴 판인가 — 덩어리를 그쪽에만 보낸다. 디스코드 다리는 사람이 폰으로 시킨 판이라 아니다."""
    if not isinstance(payload, dict) or str(payload.get("origin") or "") != "mcp":
        return False
    return str(payload.get("caller") or "").strip() != DISCORD_CALLER


def answer_for_receiver(result: Any, payload: Any) -> str:
    """일 기록의 답 중 **이 판을 맡긴 쪽**이 받을 글. 바깥 AI 면 덩어리까지(`host_answer`), 아니면 창에 보인 답."""
    if not isinstance(result, dict):
        return ""
    host = result.get("host_answer")
    if outside_ai(payload) and isinstance(host, str) and host:
        return host
    return str(result.get("answer") or "")
