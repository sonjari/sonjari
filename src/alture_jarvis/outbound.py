"""바깥 AI 에게 나가는 답을 다듬는다 — 「돌려받아야 할 것」 확인 · 정해진 규칙의 정제 · 한 줄 영수증 (2026-10-15 · 전략안 §55-32).

대표의 설계: 「Claude 가 MCP 로 시킬 때 이 정보는 꼭 들어가야 한다를 잡아 두고, 손자리가 검증해서 안 보내면 과제가 실패할 수
있다 · 안 나가도 되는 것은 정제해서 보낸다 — 데이터의 주권은 당신.」

- **무엇이 민감한가를 작은 모델에게 묻지 않는다.** 모양으로 가린다(정규식). 주민등록번호 · 카드 번호 · 비밀 키는 늘 가리고,
  전화번호 · 메일 주소는 맡긴 쪽이 `needs` 로 밝혔을 때만 내보낸다 — 밝힌 조건이라 「이것 없이는 못 끝낸다」가 참이다.
- 「돌려받아야 할 것」은 답의 표 머리 또는 「이름: 값」 줄로 가린다. 낱말 뜻을 짐작하지 않는다.
- 이 PC 의 파일은 건드리지 않는다 — 나가는 글(답)만 다듬는다. 파일은 이 PC 에 남고 경로만 나간다.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["clean_needs", "check_needs", "refine", "receipt", "outbound_record", "outbound_job_view"]

MAX_NEEDS = 12

# 순서가 뜻이 있다: 긴 모양(키 · 카드)을 먼저 가려야 짧은 모양(전화)이 그 속을 물지 않는다.
_SECRET_KEY = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-ant-[A-Za-z0-9_\-]{20,}|sk-(?:proj-)?[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{30,}"
    r"|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|xox[baprs]-[A-Za-z0-9\-]{10,})"
)
_RRN = re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-?[1-4]\d{6}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")
_PHONE = re.compile(r"(?<![\d-])(?:01[016789]|0[2-6]\d?)[-. ]?\d{3,4}[-. ]?\d{4}(?![\d-])")
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")

#: needs 의 이름에 이 낱말이 있으면 그 종류는 나가도 된다(맡긴 쪽이 필요하다고 밝혔다).
_ALLOWED_BY = {
    "전화번호": ("전화", "연락처", "휴대폰", "핸드폰", "phone", "tel", "contact"),
    "메일 주소": ("메일", "연락처", "email", "e-mail", "mail", "contact"),
}
_BLANK = {"", "-", "–", "—", "없음", "n/a", "na", "?", "x"}


def _luhn(digits: str) -> bool:
    total, flip = 0, False
    for char in reversed(digits):
        value = int(char)
        if flip:
            value *= 2
            if value > 9:
                value -= 9
        total += value
        flip = not flip
    return total % 10 == 0


def clean_needs(raw: Any) -> list[str]:
    """맡긴 쪽이 준 needs 를 이름 목록으로 — 빈 것 · 겹친 것을 빼고 앞에서 열두 개까지."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        label = " ".join(str(item or "").split())[:60]
        if label and label not in out:
            out.append(label)
    return out[:MAX_NEEDS]


def refine(text: str, *, needs: list[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """정해진 모양을 「[가림: 종류]」로 바꾸고 종류별 개수를 돌려준다(가린 것이 없으면 빈 목록)."""
    asked = " ".join(needs or []).casefold()
    allowed = {kind for kind, words in _ALLOWED_BY.items() if any(word in asked for word in words)}
    counts: dict[str, int] = {}

    def _mask(kind: str) -> Any:
        def _sub(match: re.Match[str]) -> str:
            if kind == "카드 번호" and not _luhn(re.sub(r"\D", "", match.group(0))):
                return match.group(0)
            counts[kind] = counts.get(kind, 0) + 1
            return f"[가림: {kind}]"
        return _sub

    out = str(text or "")
    for kind, pattern in (("비밀 키", _SECRET_KEY), ("주민등록번호", _RRN), ("카드 번호", _CARD),
                          ("전화번호", _PHONE), ("메일 주소", _EMAIL)):
        if kind in allowed:
            continue
        out = pattern.sub(_mask(kind), out)
    return out, [{"kind": kind, "count": count} for kind, count in counts.items()]


def _norm(text: str) -> str:
    return re.sub(r"[\s*_`:：]+", "", str(text or "")).casefold()


def _tables(answer: str) -> list[tuple[list[str], list[list[str]]]]:
    """답 속 마크다운 표들 → (머리, 줄들)."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    head: list[str] | None = None
    rows: list[list[str]] = []
    for line in str(answer or "").splitlines() + [""]:
        if line.count("|") >= 2:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell or "--") for cell in cells):
                continue
            if head is None:
                head = cells
            else:
                rows.append(cells)
            continue
        if head is not None:
            tables.append((head, rows))
        head, rows = None, []
    return tables


_HEADING = re.compile(r"^\s*(?:#{1,6}\s+(.+?)\s*#*|\*\*(.+?)\*\*\s*[:：]?)\s*$")


def _under_heading(want: str, answer: str) -> bool:
    """제목(「### 좋게 보는 점」 · 굵은 글씨만 있는 줄)이 그 이름을 담고, 다음 제목 전까지 내용이 있다.

    ★ 2026-10-15 StepFun 조사 판: 답에 「좋게 보는 점」 · 「나쁘게 보는 점」을 제목 아래 목록으로 다 썼는데 1/6 으로 셌다 —
      표 머리와 「이름: 값」 줄만 봤다. 제목이 이름을 **담는** 쪽만 본다(「분위기」 ⊂ 「④ 댓글 분위기」). 거꾸로(짧은 제목이
      긴 이름 안에 든 것)는 안 본다 — 「정리」 같은 제목 하나가 여러 항목을 채운 것으로 셀 수 있다.
    """
    lines = str(answer or "").splitlines()
    for index, line in enumerate(lines):
        found = _HEADING.match(line)
        if not found or want not in _norm(found.group(1) or found.group(2) or ""):
            continue
        for after in lines[index + 1:]:
            if _HEADING.match(after) and after.lstrip().startswith("#"):
                break
            body = after.strip().lstrip("-*•>|").strip().strip("*").strip()
            if body and not re.fullmatch(r"[-:|\s]+", body) and body.casefold() not in _BLANK:
                return True
    return False


def check_needs(needs: list[str], answer: str) -> list[dict[str, Any]]:
    """항목마다 채웠는가: 표 머리에 그 이름이 있고 그 칸에 값이 하나라도 있다 · 표의 첫 칸이 그 이름이고 옆 칸에 값이 있다 ·
    그 이름을 담은 제목 아래 내용이 있다 · 또는 「이름: 값」 줄이 있다."""
    tables = _tables(answer)
    checked: list[dict[str, Any]] = []
    for label in needs:
        want = _norm(label)
        met = False
        for head, rows in tables:
            for index, name in enumerate(head):
                have = _norm(name)
                if not have or not (want in have or have in want):
                    continue
                if any(len(row) > index and row[index].strip().strip("*").strip().casefold() not in _BLANK for row in rows):
                    met = True
                    break
            if met:
                break
        if not met:
            # ★ 표의 **첫 칸**이 항목 이름인 표(「| 라이선스 | MIT |」) — 머리가 아니라 줄이 이름을 든다 (2026-10-15 GLM 조사 판).
            for _head, rows in tables:
                for row in rows:
                    have = _norm(row[0]) if row else ""
                    # 줄 이름이 항목 이름을 **통째로** 담을 때만 — 거꾸로 보면 「설립」 한 칸이 「회사 국적과 설립」을 채운 것이 된다.
                    if not want or want not in have:
                        continue
                    if any(cell.strip().strip("*").strip().casefold() not in _BLANK for cell in row[1:]):
                        met = True
                        break
                if met:
                    break
        if not met:
            met = _under_heading(want, answer)
        if not met:
            words = r"\s*".join(re.escape(part) for part in label.split())
            line = re.search(rf"(?im)^\s*(?:[-*•]\s*)?\**{words}\**\s*[:：]\s*\**\s*(\S.*)$", str(answer or ""))
            met = bool(line and line.group(1).strip().strip("*").strip().casefold() not in _BLANK)
        checked.append({"label": label, "met": met})
    return checked


def receipt(needs: list[dict[str, Any]] | None, refined: list[dict[str, Any]], *, host: str = "") -> dict[str, Any]:
    """화면과 바깥 AI 가 같이 보는 한 줄 영수증의 재료.

    「이 PC 에 남긴 원문」 숫자는 싣지 않는다 — 지금 세는 값은 하한이고, 두 손 견주기로 역검증한 뒤에만 띄운다(§55-32).
    """
    total = len(needs or [])
    met = sum(1 for item in needs or [] if item.get("met"))
    hidden = sum(int(item.get("count") or 0) for item in refined)
    parts = [f"{host.strip() or '바깥 AI'} 에게 보냄"]
    if total:
        parts.append(f"필요한 것 {met}/{total}")
    parts.append(f"정제 {hidden}")
    return {"needs_total": total, "needs_met": met, "refined": hidden, "line": " · ".join(parts)}


def outbound_record(answer: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """바깥 AI 가 맡긴 판의 답 기록에 붙일 영수증 — 화면이 「손자리의 답」 아래 한 줄로 그린다.

    상태 조회(`delegation.summarize_job`)와 **같은 함수**로 만든다 — 화면과 바깥 AI 가 받은 것이 갈리지 않게.
    문장은 화면이 번역 사전으로 만든다(영어 화면) — 여기서는 숫자와 항목만 싣는다. 바깥 AI 가 맡긴 판이 아니면 None.
    """
    payload = payload if isinstance(payload, dict) else {}
    if str(payload.get("origin") or "") != "mcp":
        return None
    needs = clean_needs(payload.get("needs"))
    cleaned, refined = refine(answer, needs=needs)
    checked = check_needs(needs, cleaned) if needs else []
    made = receipt(checked, refined, host=str(payload.get("caller") or ""))
    return {"host": str(payload.get("caller") or "")[:80], "needs": checked, "refined": refined,
            "needs_total": made["needs_total"], "needs_met": made["needs_met"], "refined_count": made["refined"]}


def outbound_job_view(job: dict[str, Any]) -> dict[str, Any]:
    """바깥에 나가는 일 사본 — 바깥 AI 가 맡긴 일(origin=mcp)이면 답을 정제한 판으로 바꿔 돌려준다(원본은 건드리지 않는다).

    ★ 2026-10-15: 정제가 MCP 연결 프로세스 안에서만 일어나서, 며칠 사는 옛 연결 프로세스로는 원문이 나갔다. 백엔드의 일 조회 문이
      토큰 없이 읽힐 때 이 사본을 내보낸다 — 연결 프로세스의 판과 상관없이 같은 규칙이 걸린다.
    """
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else None
    if str(payload.get("origin") or "") != "mcp" or not result or not isinstance(result.get("answer"), str):
        return job
    needs = clean_needs(payload.get("needs"))
    answer, refined = refine(result["answer"], needs=needs)
    return {**job, "result": {**result, "answer": answer, "outbound": {"refined": refined, "needs": needs}}}
