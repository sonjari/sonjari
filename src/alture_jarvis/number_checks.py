"""답 속 **비율(%) 숫자**를 읽은 자료와 답 자신의 표로 대조한다 (2026-10-01 밤).

## 무슨 일이 있었나 (운영 판 e84ae679, 손자리 VRAM 조사)

Steam 설문 표를 정확히 옮겨 놓고(4GB 5.69% · 6GB 5.30% · 8GB 25.74% · … · 12GB 12.99% · 16GB 26.92% · 20GB 1.37%),
요약 줄에 「VRAM 8GB 이하가 약 **41.3%**」라고 썼다. 41.3 은 지어낸 숫자가 아니었다 — **12+16+20GB 칸의 합**
(12.99+26.92+1.37=41.28)에 「8GB 이하」라는 엉뚱한 이름표를 붙인 것이다. 표를 더하면 8GB 이하는 그보다 크다.
같은 답의 「24GB 이상 5.4%」도 32GB 칸(1.34%)을 빠뜨린 값이었다.

앱에서 받은 답에는 「읽은 자료에 없는 숫자」 검사가 아예 없었고(MCP 결과·파일 쓰기에만 있었다), 있었더라도 이 종류는
못 잡는다 — 숫자는 자료에 있고 **이름표가 틀렸다.** 그래서 둘을 본다.

1. `table_sum_mismatches` — 답에 분포 표(「| 8 GB | 25.74% |」)가 있고 요약이 「8GB 이하 약 N%」「12~16GB N%」라고
   말하면, 표에서 그 조건의 칸을 **직접 더해** 대조한다. 1%포인트 넘게 다르면 더한 칸과 함께 알린다.
   운영 답 2,474개로 쟀다: 걸린 답 1개 — 바로 이 판(오탐 0).
2. `ungrounded_percents` — 읽은 자료에 없는 % 값. 퍼센트끼리 이어진 칸의 합 · 「3개 중 2개(67%)」 같은 개수 비율 ·
   같은 줄에 적힌 두 수의 비율 · 100 에서 뺀 나머지 · 도구 값의 반올림은 계산값으로 인정한다.
   본문 숫자 장부가 있는 운영 답 627개로 쟀다: 걸린 답 9개(1.4%), 대부분 기억으로 적은 벤치 점수.

둘 다 **경고만** 붙인다(답을 지우지 않는다). 정답을 단정하지 않는다 — 내가 더한 칸을 보여 사람이 확인하게 한다.
"""

from __future__ import annotations

import re

from .evidence import numbers_claimed_in, unsupported_numbers

#: 분포 표의 한 줄 — 「| **8 GB** | **25.74%** |」. 첫 칸은 숫자+단위, 둘째 칸은 퍼센트.
_ROW = re.compile(
    r"^\s*\|\s*\**\s*(\d+(?:\.\d+)?)\s*([A-Za-z가-힣]{1,4})?\s*\**\s*\|\s*\**\s*(\d+(?:\.\d+)?)\s*%",
    re.M,
)
#: 「8GB 이하가 약 41.3%」 — 경계·관계·주장값. 사이에 숫자·%·줄바꿈·표 칸이 끼면 다른 말이다.
_BOUND = re.compile(
    r"(\d+(?:\.\d+)?)\s*([A-Za-z가-힣]{1,4})?\s*(이하|이상|미만|초과)[^\d%\n|]{0,24}?(\d+(?:\.\d+)?)\s*%"
)
#: 「12~16GB가 약 39.9%」.
_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([A-Za-z가-힣]{1,4})?\s*[~∼–]\s*(\d+(?:\.\d+)?)\s*([A-Za-z가-힣]{1,4})?"
    r"(?:\s*(?:구간|사이|대))?[^\d%\n|]{0,24}?(\d+(?:\.\d+)?)\s*%"
)
_PCT = re.compile(r"(?<![0-9A-Za-z_.])(\d{1,3}(?:\.\d+)?)\s*%")
_INT = re.compile(r"(?<![0-9A-Za-z_.])(\d{1,3}(?:,\d{3})+|\d+)(?![.\d])")
#: 차이가 이만큼 넘어야 알린다 — 반올림·「약」 정도는 넘어간다.
SUM_TOLERANCE = 1.0
_TEST = {"이하": lambda v, b: v <= b, "미만": lambda v, b: v < b, "이상": lambda v, b: v >= b, "초과": lambda v, b: v > b}


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def table_sum_mismatches(answer: str) -> list[dict[str, object]]:
    """요약 비율이 답 자신의 분포 표 합과 다른 곳. 표가 3줄 미만이면 보지 않는다."""
    text = str(answer or "")
    rows = [(float(label), (unit or "").upper(), float(pct), f"{label}{unit or ''}") for label, unit, pct in _ROW.findall(text)]
    if len(rows) < 3:
        return []
    units = {unit for _, unit, _, _ in rows}
    found: list[dict[str, object]] = []
    seen: set[str] = set()

    def judge(said: str, claimed: float, picked: list[tuple[float, str, float, str]]) -> None:
        if not picked or said in seen:
            return
        total = sum(p for _, _, p, _ in picked)
        if abs(total - claimed) > SUM_TOLERANCE:
            seen.add(said)
            found.append({"said": said, "claimed": claimed, "table_sum": round(total, 2),
                          "rows": [name for _, _, _, name in picked]})

    for match in _BOUND.finditer(text):
        bound, unit, rel, claimed = float(match.group(1)), (match.group(2) or "").upper(), match.group(3), float(match.group(4))
        if unit and unit in units:
            judge(f"{match.group(1)}{match.group(2) or ''} {rel} {match.group(4)}%", claimed,
                  [row for row in rows if row[1] == unit and _TEST[rel](row[0], bound)])
    for match in _RANGE.finditer(text):
        low, high = float(match.group(1)), float(match.group(3))
        unit = (match.group(4) or match.group(2) or "").upper()
        if unit and unit in units and low < high:
            picked = [row for row in rows if row[1] == unit and low <= row[0] <= high]
            if len(picked) >= 2:
                judge(f"{match.group(1)}~{match.group(3)}{match.group(4) or match.group(2) or ''} {match.group(5)}%",
                      float(match.group(5)), picked)
    return found


def _key(text: str) -> str:
    value = float(text)
    return str(int(value)) if value == int(value) else repr(value)


def ungrounded_percents(answer: str, seen: set[str]) -> list[str]:
    """읽은 자료에도 없고 계산으로도 안 나오는 % 값. `seen` 은 도구 결과·요청에서 모은 숫자(`numbers_read_in` 꼴)."""
    text = str(answer or "")
    percents = [m.group(1) for m in _PCT.finditer(text)]
    if not percents:
        return []
    # 도구 값의 반올림·자료에 있는 값은 기존 눈금(`unsupported_numbers`)이 먼저 거른다.
    claimed = {_key(p) for p in percents if _key(p) not in {"0", "100"}}
    left = unsupported_numbers(claimed, seen)
    if not left:
        return []
    grounded = [float(p) for p in percents if _key(p) in seen]
    counts = sorted({int(n.replace(",", "")) for n in _INT.findall(text) if 0 < int(n.replace(",", "")) <= 20})
    lines = text.split("\n")
    bad: list[str] = []
    for raw in dict.fromkeys(percents):
        if _key(raw) not in left:
            continue
        target = float(raw)
        places = len(raw.split(".", 1)[1]) if "." in raw else 0
        if _derivable(target, places, grounded, counts, lines, raw):
            continue
        bad.append(raw)
    return bad


def _derivable(target: float, places: int, grounded: list[float], counts: list[int], lines: list[str], raw: str) -> bool:
    # ① 퍼센트끼리 이어진 칸의 합(2~12칸) — 표를 위에서부터 더한 요약.
    for i in range(len(grounded)):
        total = grounded[i]
        for j in range(i + 1, min(len(grounded), i + 12)):
            total += grounded[j]
            if round(total, places) == target:
                return True
    # ② 100 에서 근거 있는 값을 뺀 나머지.
    if any(round(100 - g, places) == target for g in grounded):
        return True
    # ③ 개수 비율 — 「3개 중 2개(67%)」. 정수 % · 분모 20 이하만(넓히면 아무 숫자나 만들어진다: 19/46 = 41.3).
    if places == 0 and any(round(100 * a / b) == target for b in counts for a in counts if a <= b):
        return True
    # ④ 같은 줄의 두 수 비율 — 「2582줄 중 약 700줄(약 27%)」.
    for line in lines:
        if raw + "%" not in line.replace(" %", "%"):
            continue
        nums = [int(n.replace(",", "")) for n in _INT.findall(line)]
        if any(0 < a <= b and round(100 * a / b, places) == target for b in nums for a in nums):
            return True
        # 「나머지 73%(701~2582줄)」 — (2582-701)/2582. 같은 줄의 두 수로 낸 나머지 비율도 계산이다.
        if any(0 < a < b and round(100 * (b - a) / b, places) == target for b in nums for a in nums):
            return True
        # ⑤ **같은 대상을 적은 다른 줄**의 두 수 비율 (2026-10-17 작업 관리자 판 ac57f00e). 「RTX 3090은 VRAM의 약 79%」의 두 수는
        #   위 표 줄 「RTX 3090 | 19,392 MiB | 24,576 MiB」에 있다(78.9%). 아무 줄의 아무 쌍이나 받으면 거의 모든 정수 %가 만들어지니,
        #   비율 줄과 **이름 낱말(글자 셋 이상)** 이 겹치는 줄만 본다.
        names = _name_words(line)
        if not names:
            continue
        for other in lines:
            if other is line or not (names & _name_words(other)):
                continue
            nums = [int(n.replace(",", "")) for n in _INT.findall(other)]
            if any(0 < a <= b and round(100 * a / b, places) == target for b in nums for a in nums):
                return True
    return False


_NAME_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
#: 이름처럼 생겼지만 어느 줄에나 붙는 단위.
_UNIT_WORDS = frozenset({"mib", "gib", "kib", "tib", "mbps", "gbps", "kbps", "fps", "rpm"})


def _name_words(line: str) -> set[str]:
    """줄에 적힌 **고유 이름 꼴** 낱말 — 대문자 · 숫자 · 붙임표가 섞인 것(RTX · NVIDIA · GeForce · llama-server · msedgewebview2).

    한국어 일반 낱말(「메모리」)과 영어 일반 낱말(「The」 · 「total」)은 어느 줄에나 있어 뺀다. 단위(MiB)도 뺀다.
    """
    words: set[str] = set()
    for word in _NAME_WORD.findall(line):
        folded = word.casefold()
        if folded in _UNIT_WORDS:
            continue
        if word.isupper() or any(ch.isdigit() or ch == "-" for ch in word) or any(ch.isupper() for ch in word[1:]):
            words.add(folded)
    return words


def percent_warning(answer: str, seen: set[str], *, english: bool = False) -> str:
    """답 끝에 붙일 경고(없으면 빈 문자열). 표 합계 어긋남을 먼저 — 그쪽이 더 구체적이다."""
    notes: list[str] = []
    for item in table_sum_mismatches(answer)[:3]:
        rows = " + ".join(str(r) for r in item["rows"])  # type: ignore[union-attr]
        if english:
            notes.append(f"the summary says {item['said']}, but adding the table rows ({rows}) gives "
                         f"{_fmt(float(item['table_sum']))}%")  # type: ignore[arg-type]
        else:
            notes.append(f"요약은 「{item['said']}」인데 답의 표에서 그 칸({rows})을 더하면 "
                         f"{_fmt(float(item['table_sum']))}%입니다")  # type: ignore[arg-type]
    loose = [p for p in ungrounded_percents(answer, seen) if not any(p == _fmt(float(i["claimed"])) or float(p) == float(i["claimed"])
                                                                      for i in table_sum_mismatches(answer))]
    if not notes and not loose:
        return ""
    if english:
        parts = []
        if notes:
            parts.append("⚠ **The summary does not match its own table**: " + "; ".join(notes) + " — recheck the totals.")
        if loose:
            parts.append("⚠ **Percentages not found in anything read**: " + ", ".join(p + "%" for p in loose[:8])
                         + " — do not use them as facts until checked against the source.")
        return "\n\n" + "\n\n".join(parts)
    parts = []
    if notes:
        parts.append("⚠ **요약 숫자가 답의 표와 맞지 않습니다**: " + " · ".join(notes) + " — 합계를 다시 확인하세요.")
    if loose:
        parts.append("⚠ **읽은 자료에 없는 비율이 있습니다**: " + ", ".join(p + "%" for p in loose[:8])
                     + " — 원문으로 확인하기 전에는 사실로 쓰지 마세요.")
    return "\n\n" + "\n\n".join(parts)


__all__ = ["percent_warning", "table_sum_mismatches", "ungrounded_percents", "numbers_claimed_in"]
