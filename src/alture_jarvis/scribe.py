"""서기 — 클로드 코드 대화 기록을 손자리가 읽고 「이야기 카드」 초안을 쓴다 (2026-10-21 대표).

## 왜

대표(10-21 새벽): 「클로드는 한 세션만 기억하고, 컨텍스트가 한 번 잘리면 이야기가 끊긴다. 사람이 인수인계서를 쓰는 것처럼
메우는데 귀찮다. 손자리가 서기처럼 10~15분마다 최근 대화를 큐레이션하고, 몇 개 쌓이면 클로드가 정제해서 금으로 만들자」.
그날 밤 실제로 겪었다 — 대표가 「그 중간이 뭐였지」 했을 때 클로드는 잘릴 때 남긴 요약에서 겨우 이어 맞췄다.

- 대화 기록은 이 PC 의 파일이다(`~/.claude/projects/<프로젝트>/<세션>.jsonl`). 손자리는 이 PC 안에서 읽는다 — 밖으로 안 나간다.
- 손자리는 한도가 없고 원본을 다 읽을 수 있지만 머리가 작다. 그래서 **초안**만 쓰고, 정제는 클로드가 한다.
- 초안 줄마다 **몇 번째 줄(기록의 줄 번호)에서 나왔나 + 짧은 인용**을 붙이고, 인용이 그 말에 실제로 없으면 버린다(지어낸 줄 차단).
- 비밀값은 `secret_scrub` 으로 걷은 뒤에야 모델에게 보인다.

## 2차 (2026-10-21 저녁) — 카드를 「닫는다」

첫 점검(이 세션 75장을 실제 일과 대 봄): 정한 것 · 고쳐 준 것은 대부분 맞았다. 그런데 **「남은 일」은 끝나도 닫히지 않았다** —
28장 중 적어도 15장이 이미 끝났거나 틀렸거나 뒤집힌 것이었다(README PR 「만드는 중」은 오래전에 합쳤고, 클라우드플레어 설계는
테일스케일로 바뀌었다). 압축 뒤 그걸 지금 상태로 믿으면 끝난 일을 다시 한다. 더하기만 하는 서기였다(mem0 의 ADD 전용과 같은 모양).

그래서 Graphiti 처럼 **지우지 않고 닫는다**:
- 새 덩어리를 읽을 때 지금 열린 카드(남은 일 · 정한 것)를 같이 보여 주고, 그 덩어리가 끝냈거나(done) 뒤집었거나(superseded)
  틀린 것으로 드러낸(wrong) 카드를 **닫는다**. 닫을 때도 그 덩어리 안의 글자 그대로 인용이 있어야 한다(새 카드와 같은 규칙).
  카드보다 앞선 말로는 못 닫는다.
- 닫기는 `cards.jsonl` 에 `{"op": "close"}` 줄로 덧붙인다 — 원래 카드도 닫힌 까닭도 남는다(진 결과도 지우지 않는다).
- 이미 지나간 기록은 노는 시간에 **닫기만 하는 되읽기**로 따라잡는다(`next_reconcile_chunk`).
- 같은 말을 또 적지 않는다(basic-memory 의 유사 노트 경고처럼) · 카드마다 그 말의 시각(절대 시각)을 단다.
- 훅이 넣은 말(`isMeta` — 예: 한국어 검사 훅의 「다시 쓰세요」)은 사람이 한 말이 아니라 읽지 않는다(「사람이 고쳐 줬다」로 적혔었다).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from . import secret_scrub

#: 카드의 칸 — 대표가 말한 「이야기」의 뼈대.
KINDS = ("decided", "dropped", "open", "corrected")
KIND_NAMES = {"decided": "정한 것", "dropped": "버린 것과 까닭", "open": "남은 일 · 약속", "corrected": "사람이 거듭 고쳐 준 것"}
#: 한 말에서 모델에게 보이는 글자 상한 — 긴 답 하나가 초안 창을 다 먹지 않게.
TURN_CHARS = 700

# ── 주제 색인 (2026-10-22 대표 설계) ─────────────────────────────────────────────
# 압축은 최근 일은 자세히, 오래된 일은 거의 안 남긴다. 원본(대화 기록 파일)은 다 남아 있으니 모자란 건 **어디를 열지**뿐이다.
# 카드는 「무엇을 정했나」, 색인은 「어디를 열면 자세히 나오나」 — 주제 → 날짜 범위 · 줄 번호. 압축 · 새 세션 때 펼쳐 주고 필요한 것만 연다.
# 대표 걱정: 「키워드는 두더지 잡기를 자처하는 것 — 표본이 너무 많아지지 않게 완충을」. 그래서 **모델이 아니라 코드가** 막는다:
#   ① 닫힌 목록에서 고르기(지금 있는 주제를 보여 주고 맞는 게 없을 때만 새로) ② 카드 두 장 이상에 붙은 주제만 색인에 올림
#   ③ 띄어쓰기 · 대소문자 · 기호만 다른 주제는 하나로 ④ 총량 상한 — 넘치면 오래 안 나온 주제부터 뺀다.
TOPIC_MAX = 3               # 카드 하나에 주제 몇 개까지
TOPIC_MIN_CARDS = 2         # 완충 ②
TOPIC_LIST_MAX = 60         # 모델에게 보여 주는 「지금 있는 주제」 개수
INDEX_CHARS = 1_500         # 완충 ④
INDEX_LINES_PER_TOPIC = 3   # 주제마다 최근 줄 번호 몇 개
NO_TOPIC = "(주제 없음)"     # 모델이 못 붙인 카드 — 다시 붙잡고 맴돌지 않게 표시만, 색인 · 목록에는 안 나온다


def topic_key(topic: str) -> str:
    """같은 주제인지 가르는 열쇠 — 띄어쓰기 · 대소문자 · 기호를 뺀다(완충 ③)."""
    return re.sub(r"[\W_]+", "", str(topic or "")).casefold()


def clean_topics(raw: Any) -> list[str]:
    """모델이 낸 주제 → 2~20자 · 최대 `TOPIC_MAX` 개 · 같은 열쇠는 하나."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        name = " ".join(str(item or "").split()).strip(" ·,.「」\"'")
        key = topic_key(name)
        if 2 <= len(name) <= 20 and key and key not in seen:
            seen.add(key)
            out.append(name)
        if len(out) >= TOPIC_MAX:
            break
    return out


def topic_index(cards: list[dict[str, Any]], *, max_chars: int = INDEX_CHARS) -> tuple[str, int]:
    """(색인 글, 상한 때문에 뺀 주제 수). 카드는 열린 것 · 닫힌 것 다 — 끝난 일도 「어디서 했나」는 다시 찾는다."""
    groups: dict[str, dict[str, Any]] = {}
    for card in cards:
        for topic in card.get("topics") or []:
            key = topic_key(topic)
            if not key or key == topic_key(NO_TOPIC):
                continue
            group = groups.setdefault(key, {"names": {}, "lines": set(), "days": set()})
            group["names"][topic] = group["names"].get(topic, 0) + 1
            try:
                group["lines"].add(int(card.get("line")))
            except (TypeError, ValueError):
                pass
            day = str(card.get("at") or "")[:5]
            if re.fullmatch(r"\d\d-\d\d", day):
                group["days"].add(day)
    rows = []
    for group in groups.values():
        if len(group["lines"]) < TOPIC_MIN_CARDS:
            continue
        # 가장 자주 쓴 표기 — 같으면 띄어 쓴 쪽(읽기 쉽다).
        name = max(group["names"], key=lambda n: (group["names"][n], len(n)))
        lines = sorted(group["lines"], reverse=True)
        days = sorted(group["days"])
        span = f"{days[0]}~{days[-1]}" if len(days) > 1 else (days[0] if days else "")
        text = f"- {name} ({span}) 줄 " + " · ".join(str(n) for n in lines[:INDEX_LINES_PER_TOPIC]) if span else \
            f"- {name} 줄 " + " · ".join(str(n) for n in lines[:INDEX_LINES_PER_TOPIC])
        rows.append((lines[0], text))
    rows.sort(reverse=True)  # 최근에 나온 주제부터 — 상한에 걸리면 오래 안 나온 주제가 빠진다
    out: list[str] = []
    used = 0
    for _, text in rows:
        if used + len(text) + 1 > max_chars:
            break
        out.append(text)
        used += len(text) + 1
    return "\n".join(out), len(rows) - len(out)


_TAG_SYSTEM = """너는 대화의 서기다. 아래는 이미 쓴 카드들이다([t번호] · 칸 · 근거 줄 · 내용). 카드마다 주제를 1~3개 붙여라.
주제는 짧은 이름(2~12자 — 「색인 속도」 · 「레딧 답글」 · 「원격 연결」처럼). 「지금 있는 주제」 목록이 있으면 **거기서 고르고**,
맞는 것이 없을 때만 새로 짓는다. 비슷한 일에는 같은 주제를 붙인다. 지어내지 마라.
형식: {"tags": [{"id": "t번호", "topics": ["...", "..."]}]}"""
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_TAGS = re.compile(r"<(?:pasted_content|antml:[a-z_]+|command-[a-z-]+)[^>]*>|</(?:pasted_content|antml:[a-z_]+|command-[a-z-]+)>")


#: 닫는 까닭 — 끝남 · 나중 결정으로 바뀜 · 틀린 것으로 드러남.
CLOSE_STATUSES = {"done": "끝남", "superseded": "바뀜", "wrong": "틀림"}
#: 닫을 수 있는 칸 — 「버린 것」 · 「고쳐 준 것」은 지난 일의 기록이라 닫을 게 없다.
CLOSABLE = ("open", "decided")


@dataclass
class Turn:
    line: int      # 기록 파일의 줄 번호(0부터) — 근거 자리
    role: str      # "사람" | "클로드" | "커밋"(클로드가 부른 git commit — 닫기 근거로만)
    text: str
    at: str = ""   # 그 말의 시각(이 PC 시간 「MM-DD HH:MM」) — 「다음 주」 같은 상대 말이 나중에 읽혀도 뜻이 남게


def _local_time(stamp: Any) -> str:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


def card_id(row: dict[str, Any]) -> str:
    """카드의 이름표. 2차 이전 카드는 이름표가 없어 같은 셈으로 만든다(세션 · 줄 · 칸 · 글이 같으면 같은 이름)."""
    if row.get("id"):
        return str(row["id"])
    digest = hashlib.sha1(f"{row.get('kind')}|{row.get('text')}".encode("utf-8")).hexdigest()[:6]
    return f"{str(row.get('session') or '')[:8]}-{row.get('line')}-{digest}"


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _same_story(a: str, b: str) -> bool:
    """같은 말을 또 적는가. 짧은 글은 글자까지 같을 때만(「남은 일 3」과 「남은 일 4」는 다르다), 긴 글은 거의 같으면."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return min(len(na), len(nb)) >= 15 and SequenceMatcher(None, na, nb).ratio() >= 0.85


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


#: 「~하는 중이다 · ~하고 있다」로 끝나는 말 — 곧 끝나는 진행 보고(남은 일 카드로 두지 않는다).
_PROGRESS_REPORT = re.compile(r"(?:는|고 있는)\s*중(?:이다|입니다|이에요|임)?[.。]?\s*$|고\s*있(?:다|습니다|어요)[.。]?\s*$")

_COMMIT_COMMAND = re.compile(r"\bgit\b[^\n]*?\bcommit\b", re.IGNORECASE)


def _commit_of(message: dict[str, Any]) -> str:
    """클로드가 부른 셸 명령 가운데 `git commit` 이 있으면 그 명령(커밋 메시지 포함) 앞부분 — 없으면 빈 글."""
    for block in message.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        command = str((block.get("input") or {}).get("command") or "")
        found = _COMMIT_COMMAND.search(command)
        if found and "--amend" not in command:
            return "git commit — " + command[found.end():].strip()[:TURN_CHARS]
    return ""


def _turn_of(number: int, raw: str) -> Turn | None:
    """기록 한 줄이 **사람의 말이나 클로드의 글**이면 그 말 — 도구 결과 · 시스템 안내 · 잘릴 때 남긴 요약 · 곁가지는 None."""
    # 줄 머리만 보고 거른다 — 도구 결과 줄은 수 MB 라 다 해석하면 느리다.
    if '"type":"user"' not in raw and '"type":"assistant"' not in raw and '"type": "user"' not in raw and '"type": "assistant"' not in raw:
        return None
    try:
        row = json.loads(raw)
    except ValueError:
        return None
    kind = row.get("type")
    # isMeta — 훅 · 명령이 사람 자리에 넣은 말(예: Stop 훅 「최종 답이 영어입니다 … 다시 쓰세요」). 사람이 고쳐 준 말이 아니다.
    if kind not in ("user", "assistant") or row.get("isCompactSummary") or row.get("isSidechain") or row.get("isMeta"):
        return None
    message = row.get("message") if isinstance(row.get("message"), dict) else {}
    if kind == "user" and isinstance(message.get("content"), list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in message["content"]):
        return None
    text = _TAGS.sub("", _REMINDER.sub("", _text_of(message))).strip()
    if not text and kind == "assistant":
        # ★ 커밋은 「끝났다」의 가장 확실한 신호인데 도구 호출이라 서기가 못 봤다 (2026-10-22 · r/ClaudeCode kincaidDev 처방).
        #   10-22 아침 압축 뒤 다시 넣은 「남은 일」에 이미 끝난 일이 남아 있었다. 커밋 명령만 「커밋」 줄로 보인다(다른 도구는 그대로 안 본다).
        commit = _commit_of(message)
        if commit:
            return Turn(number, "커밋", secret_scrub.scrub(commit)["text"], _local_time(row.get("timestamp")))
    if not text:
        return None
    return Turn(number, "사람" if kind == "user" else "클로드", secret_scrub.scrub(text)["text"], _local_time(row.get("timestamp")))


def read_turns(path: Path, start_line: int = 0, end_line: int | None = None) -> list[Turn]:
    """기록에서 **사람의 말과 클로드의 글**만 꺼낸다(줄 번호 범위). 실험 · 견주기용 — 서기 본체는 `read_turns_from`."""
    turns: list[Turn] = []
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for number, raw in enumerate(handle):
            if number < start_line:
                continue
            if end_line is not None and number >= end_line:
                break
            turn = _turn_of(number, raw)
            if turn is not None:
                turns.append(turn)
    return turns


def read_turns_from(path: Path, offset: int, line: int, limit: int) -> tuple[list[Turn], int, int]:
    """바이트 자리 `offset`(그 자리의 줄 번호 `line`)부터 말을 `limit` 개까지. (말들, 다음 바이트 자리, 다음 줄 번호).

    ★ 기록 하나가 1.3GB · 28만 줄이었다(2026-10-21 이 PC). 줄 번호로 건너뛰면 매번 처음부터 읽는다 — 그래서 바이트 자리로 잇는다.
    끝에 줄바꿈 없는 줄은 클로드가 아직 쓰는 중이라 읽지 않고 그 앞에서 멈춘다(반쪽 줄을 읽고 자리를 넘기면 그 말을 잃는다).
    """
    turns: list[Turn] = []
    with Path(path).open("rb") as handle:
        handle.seek(offset)
        for raw in handle:
            if not raw.endswith(b"\n"):
                break
            offset += len(raw)
            turn = _turn_of(line, raw.decode("utf-8", errors="replace"))
            line += 1
            if turn is not None:
                turns.append(turn)
                if len(turns) >= limit:
                    break
    return turns, offset, line


def tail_start(path: Path, tail_bytes: int) -> tuple[int, int]:
    """처음 보는 기록은 끝 `tail_bytes` 만 읽는다 — 서기는 **최근 대화**를 정리하는 것이지 몇 주 전 것을 다시 쓰는 게 아니다.
    (바이트 자리, 그 자리의 줄 번호). 줄 번호는 근거 자리라 앞 줄바꿈을 세어 맞춘다(1.3GB 에 1~2초, 처음 한 번만)."""
    size = Path(path).stat().st_size
    if size <= tail_bytes:
        return 0, 0
    with Path(path).open("rb") as handle:
        handle.seek(size - tail_bytes)
        handle.readline()  # 반쪽 줄은 건너뛴다
        offset = handle.tell()
        handle.seek(0)
        newlines, left = 0, offset
        while left > 0:
            block = handle.read(min(left, 16 * 1024 * 1024))
            if not block:
                break
            newlines += block.count(b"\n")
            left -= len(block)
    return offset, newlines


def offset_of_line(path: Path, line: int) -> int:
    """`line` 번째 줄이 시작하는 바이트 자리 — 되읽기를 카드의 줄에서 시작하려고(1.3GB 에 1~2초, 기록마다 한 번)."""
    if line <= 0:
        return 0
    seen, base = 0, 0
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(16 * 1024 * 1024)
            if not block:
                return base
            count = block.count(b"\n")
            if seen + count >= line:
                index = -1
                for _ in range(line - seen):
                    index = block.index(b"\n", index + 1)
                return base + index + 1
            seen += count
            base += len(block)


def compact_summaries(path: Path) -> list[tuple[int, str]]:
    """대화가 잘릴 때 남은 요약들 — (줄 번호, 글). 서기 초안과 견줄 기준이다."""
    found: list[tuple[int, str]] = []
    with Path(path).open(encoding="utf-8", errors="replace") as handle:
        for number, raw in enumerate(handle):
            if '"isCompactSummary"' not in raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if row.get("isCompactSummary"):
                found.append((number, _text_of(row.get("message") or {})))
    return found


_SYSTEM = """너는 대화의 서기다. 아래는 사람과 클로드(코딩 도우미)가 나눈 대화 조각이다. 각 줄 앞의 [번호]는 그 말의 자리다.
다음 네 칸에 해당하는 것만 뽑아 JSON 하나로 내라. 없으면 빈 목록. 지어내지 마라.
- decided: 사람과 클로드가 **정한 것**(방향 · 결정 · 하기로 한 것)
- dropped: **버린 것과 그 까닭**(해 보고 접은 것 · 하지 않기로 한 것)
- open: **남은 일 · 약속**(나중에 하기로 한 것 · 아직 안 끝난 것). 한 카드에 한 일만(여러 일을 묶지 마라).
  클로드가 바로 다음에 할 걸음(「이제 시험을 돌립니다」 · 「확인하겠습니다」 · 「조사하는 중」)은 적지 마라 — 곧 끝나는 진행 보고다.
- corrected: **사람이 거듭 고쳐 준 것**(말투 · 규칙 · 「그렇게 하지 마」)
각 항목: {"kind": 칸 이름, "text": 한 문장 요약(한국어), "line": 근거가 된 말의 [번호], "quote": 그 말에서 **그대로 옮긴** 짧은 구절(8~40자),
 "topics": 이 일의 주제 1~3개(짧은 이름, 2~12자 — 「색인 속도」 · 「레딧 답글」 · 「원격 연결」처럼)}
quote 는 반드시 그 [번호] 말 안에 글자 그대로 있어야 한다.
조각 뒤에 「지금 있는 주제」 목록이 있으면 **거기서 고르고**, 맞는 것이 없을 때만 새 주제를 짓는다. 형식: {"items": [...]}"""

_CLOSE_RULES = """
대화 조각 뒤에 「지금 열린 카드」 목록이 있다([c번호]). 이 조각을 보면 그 카드가
- done: 끝났다(했다 · 합쳤다 · 반영했다 · 올렸다)
- superseded: 나중 결정으로 바뀌었다(다른 방식으로 가기로 했다)
- wrong: 틀린 것으로 드러났다
면 closes 에 적어라: {"id": "c번호", "status": "done|superseded|wrong", "line": 근거 말의 [번호], "quote": 그 말에서 그대로 옮긴 구절(8~40자)}
확실하지 않으면 닫지 마라. 비슷한 일이 다시 언급됐다는 것만으로는 끝난 게 아니다.
- 「A 한 뒤에 B」 카드는 **B 가 끝나야** done 이다. A 만 끝난 것은 닫을 까닭이 아니다.
- 카드가 여러 일을 묶었으면 **전부** 끝났을 때만 done 이다.
- 「시작했다」 · 「하는 중」 · 「돌립니다」는 끝난 게 아니다.
- 「커밋」 줄은 실제로 커밋한 기록이다. 커밋 메시지가 그 카드의 일을 했다고 적고 있으면 done 으로 닫아도 된다(quote 는 커밋 줄에서)."""

_CLOSE_ONLY_SYSTEM = """너는 대화의 서기다. 아래는 사람과 클로드(코딩 도우미)가 나눈 대화 조각이다. 각 줄 앞의 [번호]는 그 말의 자리다.
이번에는 새 카드를 쓰지 않는다. 열린 카드 중 이 조각이 닫는 것만 찾는다. 지어내지 마라.""" + _CLOSE_RULES + """
형식: {"closes": [...]}"""


def _parse(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1]) if "{" in raw else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _body(turns: list[Turn], active: list[dict[str, Any]],
          topics: list[str] | None = None) -> tuple[str, dict[str, dict[str, Any]]]:
    """모델에게 보일 글 — 대화 조각이 먼저(줄 번호가 맨 앞), 열린 카드는 뒤에 짧은 이름표로."""
    body = "\n".join(f"[{turn.line}] {turn.role}: {turn.text[:TURN_CHARS]}" for turn in turns)
    tags: dict[str, dict[str, Any]] = {}
    if active:
        rows = []
        for number, card in enumerate(active, start=1):
            tags[f"c{number}"] = card
            rows.append(f"[c{number}] ({KIND_NAMES.get(card.get('kind'), card.get('kind'))} · 줄 {card.get('line')}) {card.get('text')}")
        body += "\n\n=== 지금 열린 카드 ===\n" + "\n".join(rows)
    if topics:
        # 완충 ①: 닫힌 목록에서 고르게 — 새 주제는 맞는 게 없을 때만(대표 10-22 「키워드 두더지 잡기」 걱정).
        body += "\n\n=== 지금 있는 주제 ===\n" + " · ".join(topics[:TOPIC_LIST_MAX])
    return body, tags


def _closes(data: dict[str, Any], turns: list[Turn], tags: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """닫기도 새 카드와 같은 규칙 — 그 조각 안의 글자 그대로 인용, 카드보다 뒤의 말, 아는 이름표만."""
    by_turn = {turn.line: turn for turn in turns}
    found: list[dict[str, Any]] = []
    taken: set[str] = set()
    for close in (data.get("closes") or [])[:40]:
        if not isinstance(close, dict) or close.get("status") not in CLOSE_STATUSES:
            continue
        card = tags.get(str(close.get("id") or "").strip())
        if card is None or card_id(card) in taken:
            continue
        try:
            line = int(close.get("line"))
        except (TypeError, ValueError):
            continue
        turn = by_turn.get(line)
        quote = str(close.get("quote") or "").strip()
        # 사람이 다시 연 카드는 그때까지 읽은 말로 또 닫지 못한다(`reopen_after`) — 10-21 저녁 되읽기가 같은 옛 근거로 다시 닫았다.
        floor = max(int(card.get("line") or 0), int(card.get("reopen_after") or 0))
        if turn is None or line <= floor:
            continue
        if len(quote) < 4 or _norm(quote) not in _norm(turn.text):
            continue
        taken.add(card_id(card))
        found.append({"op": "close", "id": card_id(card), "status": close["status"], "line": line, "quote": quote[:80],
                      "at": turn.at, "card_kind": card.get("kind"), "card_text": str(card.get("text") or "")[:200],
                      "card_line": card.get("line")})
    return found


def draft_and_close(turns: list[Turn], ask: Callable[[str, str], str], active: list[dict[str, Any]] | None = None,
                    *, max_items: int = 12, topics: list[str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """한 번의 부르기로 (새 카드, 닫을 카드). 열린 카드가 없으면 1차와 같은 프롬프트다."""
    if not turns:
        return [], []
    active = list(active or [])
    body, tags = _body(turns, active, topics)
    raw = ask(_SYSTEM + (_CLOSE_RULES + '\n형식: {"items": [...], "closes": [...]}' if active else ""), body)
    data = _parse(raw)
    return _kept_items(data, turns, max_items), _closes(data, turns, tags)


def close_only(turns: list[Turn], ask: Callable[[str, str], str], active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """지나간 조각을 다시 읽어 닫기만 — 새 카드는 이미 그때 썼다."""
    if not turns or not active:
        return []
    body, tags = _body(turns, active)
    return _closes(_parse(ask(_CLOSE_ONLY_SYSTEM, body)), turns, tags)


def draft(turns: list[Turn], ask: Callable[[str, str], str], *, max_items: int = 12) -> list[dict[str, Any]]:
    """한 덩어리의 말로 초안 항목을 뽑고, **인용이 실제로 있는 것만** 남긴다."""
    if not turns:
        return []
    return _kept_items(_parse(ask(_SYSTEM, _body(turns, [])[0])), turns, max_items)


def _kept_items(data: dict[str, Any], turns: list[Turn], max_items: int) -> list[dict[str, Any]]:
    # 「커밋」 줄은 닫기의 근거로만 쓴다 — 새 카드의 근거는 사람과 클로드의 말뿐(커밋마다 「정한 것」이 쌓이지 않게).
    by_line = {turn.line: turn.text for turn in turns if turn.role != "커밋"}
    at_line = {turn.line: turn.at for turn in turns}
    kept: list[dict[str, Any]] = []
    for item in (data.get("items") or [])[: max_items * 2]:
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            continue
        try:
            line = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        quote = str(item.get("quote") or "").strip()
        source = by_line.get(line, "")
        # 근거 검사 — 인용이 그 말 안에 글자 그대로 없으면 버린다(빈칸만 느슨하게).
        if len(quote) < 4 or re.sub(r"\s+", "", quote) not in re.sub(r"\s+", "", source):
            continue
        text = str(item.get("text") or "").strip()[:200]
        # ★ 진행 보고는 남은 일이 아니다 (2026-10-22 · 「손자리가 7개 프로젝트를 조사하여 문서를 작성하는 중이다」가 하루 넘게 열려 있었다).
        #   지시문에 「진행 보고는 적지 마라」가 있었는데 안 먹었다(사고 R) — 코드가 거른다.
        if item["kind"] == "open" and _PROGRESS_REPORT.search(text):
            continue
        # 같은 조각 안에서 같은 말을 두 칸에 또 적지 않는다(「정한 것」과 「고쳐 준 것」에 같은 줄이 두 번 들어갔었다).
        if any(prev["line"] == line and _same_story(prev["text"], text) for prev in kept):
            continue
        row = {"kind": item["kind"], "text": text, "line": line, "quote": quote[:80], "at": at_line.get(line, "")}
        topics = clean_topics(item.get("topics"))
        if topics:
            row["topics"] = topics
        kept.append(row)
        if len(kept) >= max_items:
            break
    return kept


def chunks(turns: list[Turn], size: int = 40) -> list[list[Turn]]:
    return [turns[index : index + size] for index in range(0, len(turns), size)]


def _where(line: Any, quote: Any, at: Any = "") -> str:
    return f"({at} · 줄 {line} · 「{quote}」)" if at else f"(줄 {line} · 「{quote}」)"


def render(items: list[dict[str, Any]], closed: list[dict[str, Any]] | None = None) -> str:
    """사람 · 클로드가 읽는 카드 — 열린 카드만 칸별로(줄마다 시각 · 근거 자리), 그 아래 최근에 닫힌 카드와 닫힌 까닭."""
    lines: list[str] = []
    for kind in KINDS:
        mine = [item for item in items if item["kind"] == kind]
        if not mine:
            continue
        lines.append(f"## {KIND_NAMES[kind]}")
        lines += [f"- {item['text']}  {_where(item['line'], item['quote'], item.get('at'))}" for item in mine]
    if closed:
        lines.append("## 최근 닫힌 것(끝남 · 바뀜 · 틀림 — 위 목록에서 뺐다)")
        lines += [f"- [{CLOSE_STATUSES.get(row.get('status'), row.get('status'))}] {row.get('card_text')}  "
                  f"{_where(row.get('line'), row.get('quote'), row.get('at'))}" for row in closed]
    return "\n".join(lines)


class Scribe:
    """노는 시간에 한 덩어리씩 — 동의한 폴더의 클로드 코드 기록을 **지난번 읽은 자리부터** 읽고 초안 항목을 쌓는다.

    한 번에 한 덩어리(`CHUNK` 말)만 쓴다 — 사람 일이 오면 바로 비켜야 하므로 길게 붙잡지 않는다(`background_chat`).
    새 말이 `MIN_NEW` 개보다 적으면 기다린다(짧은 조각은 이야기가 안 된다). 결과는 `data/scribe/cards.jsonl` 에 줄마다 쌓는다.
    """

    CHUNK = 40
    MIN_NEW = 12
    #: 처음 보는 기록은 끝에서 이만큼만(최근 대화). ★ 처음엔 3MB 로 「잘림 한 번 사이」라 적었는데 틀렸다(2026-10-21 03:17 실측) —
    #: 도구 출력이 커서 끝 3MB 에 말 43개(사람 2) · 10MB 98개(15) · 30MB 296개(51). 잘림 한 번 사이(말 241개)에 맞는 것은 30MB.
    TAIL_BYTES = 30_000_000
    #: 이보다 오래 안 바뀐 기록은 안 본다 — 끝난 대화를 몇 주 뒤에 다시 쓰지 않는다.
    RECENT_SEC = 2 * 86400

    def __init__(self, data_dir: Path, folders: list[Path]) -> None:
        self.root = Path(data_dir) / "scribe"
        self.folders = [Path(folder) for folder in folders]

    def _state_path(self) -> Path:
        return self.root / "state.json"

    def _state(self) -> dict[str, dict[str, int]]:
        """기록마다 {offset, line}(새 카드를 쓴 자리) + 있으면 {rc_offset, rc_line}(닫기 되읽기가 따라온 자리)."""
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        state: dict[str, dict[str, int]] = {}
        for key, value in data.items():
            if not (isinstance(value, dict) and "offset" in value and "line" in value):
                continue
            pos = {"offset": int(value["offset"]), "line": int(value["line"])}
            if "rc_offset" in value and "rc_line" in value:
                pos.update(rc_offset=int(value["rc_offset"]), rc_line=int(value["rc_line"]))
            state[str(key)] = pos
        return state

    def _rows(self) -> list[dict[str, Any]]:
        try:
            text = (self.root / "cards.jsonl").read_text(encoding="utf-8")
        except OSError:
            return []
        rows = []
        for raw in text.splitlines():
            try:
                row = json.loads(raw) if raw.strip() else None
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _split(self, session: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(열린 카드, 닫기 줄) — 닫힌 카드는 열린 목록에서 빠진다. 세션을 주면 그 세션 것만."""
        rows = [row for row in self._rows() if not session or str(row.get("session") or "").startswith(session)]
        # 줄 순서대로 — 닫기 뒤의 다시 열기(`op: reopen`, 잘못 닫은 것을 사람 · 클로드가 되돌림)가 이긴다. 둘 다 지우지 않고 남는다.
        shut: dict[str, dict[str, Any]] = {}
        guard: dict[str, int] = {}
        for row in rows:
            if row.get("op") == "close":
                shut[str(row.get("id"))] = row
            elif row.get("op") == "reopen":
                shut.pop(str(row.get("id")), None)
                guard[str(row.get("id"))] = int(row.get("after_line") or 0)
        closes = list(shut.values())
        tags = self._tags(rows)
        cards = [({**row, "reopen_after": guard[card_id(row)]} if card_id(row) in guard else row)
                 for row in rows if not row.get("op") and card_id(row) not in shut]
        cards = [({**card, "topics": tags[card_id(card)]} if not card.get("topics") and card_id(card) in tags else card)
                 for card in cards]
        return cards, closes

    @staticmethod
    def _tags(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
        """나중에 붙인 주제(`op: tag`) — 카드 이름표 → 주제. 같은 카드에 또 붙으면 나중 것."""
        return {str(row.get("id")): list(row.get("topics") or []) for row in rows if row.get("op") == "tag"}

    def all_cards(self, session: str = "") -> list[dict[str, Any]]:
        """열린 카드 + 닫힌 카드(주제까지) — 색인용. 닫혀도 「어디서 했나」는 남는다."""
        rows = [row for row in self._rows() if not session or str(row.get("session") or "").startswith(session)]
        tags = self._tags(rows)
        return [({**row, "topics": tags[card_id(row)]} if not row.get("topics") and card_id(row) in tags else row)
                for row in rows if not row.get("op")]

    def topics(self, session: str = "") -> list[str]:
        """지금 있는 주제 — 자주 · 최근에 쓴 것부터(완충 ①의 목록)."""
        count: dict[str, list[Any]] = {}
        for card in self.all_cards(session):
            for topic in card.get("topics") or []:
                key = topic_key(topic)
                if key and key != topic_key(NO_TOPIC):
                    slot = count.setdefault(key, [topic, 0, 0])
                    slot[1] += 1
                    slot[2] = max(slot[2], int(card.get("line") or 0))
        return [name for name, _, _ in sorted(count.values(), key=lambda v: (v[1], v[2]), reverse=True)]

    def index(self, session: str = "") -> dict[str, Any]:
        text, dropped = topic_index(self.all_cards(session))
        return {"text": text, "dropped": dropped}

    TAG_BATCH = 40

    def _tag_once(self, asked: Callable[[str, str], str]) -> dict[str, Any]:
        """주제가 없는 옛 카드에 주제를 붙인다 — 최근 세션 것부터 한 번에 `TAG_BATCH` 장. 노는 시간에만."""
        cards = [card for card in self.all_cards() if not card.get("topics")]
        if not cards:
            return {"done": False, "why": "읽을 새 말이 없음"}
        session = str(cards[-1].get("session") or "")
        batch = [card for card in cards if str(card.get("session") or "") == session][-self.TAG_BATCH:]
        listing = "\n".join(f"[t{n}] ({KIND_NAMES.get(card.get('kind'), card.get('kind'))} · 줄 {card.get('line')}) {card.get('text')}"
                            for n, card in enumerate(batch, start=1))
        known = self.topics(session)
        body = listing + ("\n\n=== 지금 있는 주제 ===\n" + " · ".join(known[:TOPIC_LIST_MAX]) if known else "")
        data = _parse(asked(_TAG_SYSTEM, body))
        rows = []
        for tag in (data.get("tags") or [])[: len(batch)]:
            if not isinstance(tag, dict):
                continue
            try:
                card = batch[int(str(tag.get("id") or "").lstrip("t")) - 1]
            except (ValueError, IndexError):
                continue
            topics = clean_topics(tag.get("topics"))
            if topics:
                rows.append({"op": "tag", "id": card_id(card), "topics": topics, "session": card.get("session"),
                             "folder": card.get("folder")})
        # 모델이 못 붙인 카드는 「주제 없음」으로 표시한다 — 같은 카드를 다시 붙잡고 맴돌지 않게.
        done = {row["id"] for row in rows}
        rows += [{"op": "tag", "id": card_id(card), "topics": [NO_TOPIC], "session": card.get("session"),
                  "folder": card.get("folder")} for card in batch if card_id(card) not in done]
        self._append(rows)
        return {"done": True, "tagged": len(rows), "session": session}

    def reopen(self, ids: list[str], why: str) -> int:
        """잘못 닫힌 카드를 다시 연다 — 닫기 줄은 그대로 두고 다시 열기 줄을 덧붙인다(까닭 필수)."""
        _, closes = self._split()
        known = {str(row.get("id")): row for row in closes}
        # 다시 연 그 순간까지 서기가 읽은 줄 — 이 줄 이하의 말로는 다시 못 닫는다.
        read_to = {Path(path).stem: max(int(pos.get("line") or 0), int(pos.get("rc_line") or 0))
                   for path, pos in self._state().items()}
        rows = [{"op": "reopen", "id": key, "why": str(why)[:200], "session": known[key].get("session"),
                 "folder": known[key].get("folder"),
                 "after_line": max(read_to.get(str(known[key].get("session") or ""), 0), int(known[key].get("line") or 0))}
                for key in ids if key in known and why.strip()]
        self._append(rows)
        return len(rows)

    def active(self, session: str) -> list[dict[str, Any]]:
        """모델에게 보일 열린 카드 — 그 세션의 남은 일(최근 30) + 정한 것(최근 15). 프롬프트가 끝없이 커지지 않게."""
        cards, _ = self._split(session)
        opens = [card for card in cards if card.get("kind") == "open"][-30:]
        decided = [card for card in cards if card.get("kind") == "decided"][-15:]
        return sorted(opens + decided, key=lambda card: int(card.get("line") or 0))

    def _append(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "cards.jsonl").open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _save_state(self, state: dict[str, dict[str, int]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self._state_path().with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(self._state_path())

    def _logs(self) -> list[Path]:
        import time

        now = time.time()
        found = []
        for folder in self.folders:
            if not folder.is_dir():
                continue
            for path in folder.glob("*.jsonl"):
                try:
                    if now - path.stat().st_mtime <= self.RECENT_SEC:
                        found.append(path)
                except OSError:
                    continue
        return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)

    def next_chunk(self) -> tuple[Path, list[Turn], dict[str, int]] | None:
        """다음에 읽을 (기록 파일, 말 덩어리, 다 읽으면 옮길 자리). 읽을 게 없으면 None. 가장 최근에 바뀐 기록부터."""
        state = self._state()
        for log in self._logs()[:20]:
            pos = state.get(str(log))
            if pos is None:
                # 처음 본 기록 — 시작 자리를 바로 적어 둔다(안 적으면 말이 모자란 동안 매번 1.3GB 줄바꿈을 다시 센다).
                offset, line = tail_start(log, self.TAIL_BYTES)
                pos = {"offset": offset, "line": line}
                state[str(log)] = pos
                self._save_state(state)
            turns, offset, line = read_turns_from(log, pos["offset"], pos["line"], self.CHUNK)
            if len(turns) < self.MIN_NEW:
                continue
            # 다음 덩어리는 이 덩어리를 다 읽은 바로 뒤부터 — 남은 것이 있으면 다음 차례에 이어서.
            return log, turns, {"offset": offset, "line": line}
        return None

    def next_reconcile_chunk(self) -> tuple[Path, list[Turn], dict[str, int], list[dict[str, Any]]] | None:
        """닫기 되읽기 — 새 카드를 다 따라잡은 뒤 노는 시간에, 이미 지나간 말을 다시 읽어 열린 카드를 닫는다.

        2차 이전 카드는 닫힌 적이 없다. 기록마다 가장 오래된 열린 카드의 줄에서 시작해 새 카드를 쓴 자리(offset)까지만 간다.
        (기록, 말 덩어리, 다 읽으면 옮길 되읽기 자리, 그 덩어리보다 앞선 열린 카드). 할 게 없으면 None.
        """
        state = self._state()
        for log in self._logs()[:20]:
            pos = state.get(str(log))
            if pos is None:
                continue
            active = self.active(log.stem)
            if "rc_offset" not in pos:
                if not active:
                    pos.update(rc_offset=pos["offset"], rc_line=pos["line"])
                else:
                    start = min(int(card.get("line") or 0) for card in active) + 1
                    pos.update(rc_offset=offset_of_line(log, start), rc_line=start)
                state[str(log)] = pos
                self._save_state(state)
            if pos["rc_offset"] >= pos["offset"]:
                continue
            turns, offset, line = read_turns_from(log, pos["rc_offset"], pos["rc_line"], self.CHUNK)
            if offset >= pos["offset"] or line >= pos["line"]:
                # 새 카드를 쓴 자리를 넘어가지 않는다 — 거기부터는 새 카드를 쓸 때 같이 닫는다.
                turns = [turn for turn in turns if turn.line < pos["line"]]
                offset, line = pos["offset"], pos["line"]
            first = turns[0].line if turns else line
            earlier = [card for card in active if int(card.get("line") or 0) < first]
            return log, turns, {"rc_offset": offset, "rc_line": line}, earlier
        return None

    def _caught_up(self, log: Path, rc: dict[str, int]) -> None:
        state = self._state()
        pos = state.get(str(log))
        if pos is not None:
            pos.update(rc)
            state[str(log)] = pos
            self._save_state(state)

    def run_once(self, ask: Callable[[str, str], str | None]) -> dict[str, Any]:
        """한 덩어리를 읽고 초안을 쌓는다(열린 카드도 같이 닫는다). 새 말이 없으면 지나간 말을 다시 읽어 닫기만 한다.
        끊겼으면(사람 일이 옴) 읽은 자리를 옮기지 않는다 — 다음 차례에 다시."""

        def asked(system: str, user: str) -> str:
            reply = ask(system, user)
            if reply is None:
                raise _Cancelled()
            return reply

        found = self.next_chunk()
        if found is None:
            try:
                result = self._reconcile_once(asked)
                # 읽을 말도 되읽을 말도 없으면 옛 카드에 주제를 붙인다(주제 색인 · 10-22).
                return result if result.get("done") else self._tag_once(asked)
            except _Cancelled:
                return {"done": False, "why": "사람 일이 와서 비켰다"}
        log, chunk, next_pos = found
        before = self._state().get(str(log), {})
        active = self.active(log.stem)
        try:
            items, closes = draft_and_close(chunk, asked, active, topics=self.topics(log.stem))
        except _Cancelled:
            return {"done": False, "why": "사람 일이 와서 비켰다", "log": log.name}
        known, _ = self._split(log.stem)
        fresh: list[dict[str, Any]] = []
        for item in items:
            # 이미 적힌 말을 또 적지 않는다 — 같은 세션의 열린 카드와 같은 이야기면 건너뛴다.
            if any(_same_story(item["text"], card.get("text")) for card in known + fresh):
                continue
            row = {**item, "session": log.stem, "folder": log.parent.name}
            row["id"] = card_id(row)
            fresh.append(row)
        # ★ **같은 조각 안에서 생기고 끝난 일** (2026-10-22). 닫기는 이미 열려 있던 카드만 보므로, 한 조각 안에서 「주제 색인을 만든다」가
        #   생기고 그 뒤에 커밋까지 끝나면 그 카드는 영영 열린 채였다(「버그 둘 수정」 · 「주제 색인」 둘 다 커밋 뒤에도 열림).
        #   새 남은 일보다 **뒤에 커밋 줄**이 있을 때만 그 뒤 말들로 닫기를 한 번 더 — 커밋이 없으면 모델 부르기가 늘지 않는다.
        fresh_open = [row for row in fresh if row.get("kind") == "open"]
        if fresh_open:
            first = min(int(row["line"]) for row in fresh_open)
            later = [turn for turn in chunk if turn.line > first]
            if any(turn.role == "커밋" for turn in later):
                try:
                    closes = list(closes) + close_only(later, asked, fresh_open)
                except _Cancelled:
                    pass  # 사람 일이 왔다 — 새 카드는 남기고, 닫기는 다음 기회에
        self._append(fresh + [{**close, "session": log.stem, "folder": log.parent.name} for close in closes])
        state = self._state()
        # 되읽기가 이미 따라와 있었으면 같이 옮긴다. 2차 이전 기록(되읽기 자리 없음)에 열린 카드가 있으면 옮기지 않는다 —
        # 그래야 노는 시간에 지나간 말을 다시 읽어 옛 카드를 닫는다.
        if "rc_offset" in before:
            caught_up = before["rc_offset"] >= before.get("offset", 0)
        else:
            caught_up = not active
        state[str(log)] = {**state.get(str(log), {}), **next_pos}
        if caught_up:
            state[str(log)].update(rc_offset=next_pos["offset"], rc_line=next_pos["line"])
        self._save_state(state)
        return {"done": True, "log": log.name, "turns": len(chunk), "items": len(fresh), "closed": len(closes)}

    def _reconcile_once(self, asked: Callable[[str, str], str]) -> dict[str, Any]:
        found = self.next_reconcile_chunk()
        if found is None:
            return {"done": False, "why": "읽을 새 말이 없음"}
        log, turns, rc, earlier = found
        if not turns or not earlier:
            self._caught_up(log, rc)
            return {"done": True, "log": log.name, "reconciled": True, "turns": len(turns), "closed": 0}
        try:
            closes = close_only(turns, asked, earlier)
        except _Cancelled:
            return {"done": False, "why": "사람 일이 와서 비켰다", "log": log.name}
        self._append([{**close, "session": log.stem, "folder": log.parent.name} for close in closes])
        self._caught_up(log, rc)
        return {"done": True, "log": log.name, "reconciled": True, "turns": len(turns), "closed": len(closes)}

    def recent(self, limit: int = 30, session: str = "") -> list[dict[str, Any]]:
        """**열린** 카드 — 최근 것부터 `limit` 개. `session` 을 주면 그 세션 것만. 닫힌 카드는 `closed` 로."""
        cards, _ = self._split(session)
        return cards[-limit:]

    def closed(self, limit: int = 8, session: str = "") -> list[dict[str, Any]]:
        """최근에 닫힌 카드와 닫힌 까닭(끝남 · 바뀜 · 틀림) — 근거 줄 포함."""
        _, closes = self._split(session)
        return closes[-limit:]


class _Cancelled(Exception):
    """노는 시간 일이 사람 일에 밀려 끊겼다."""


#: 설정 › 서기 의 프로젝트 목록 — 이 PC 의 클로드 코드 대화 기록 폴더(`~/.claude/projects/<프로젝트>`).
PROJECTS_LIMIT = 40
#: 작업 폴더 이름을 찾으려고 가장 최근 기록의 앞부분만 읽는다(기록 하나가 1GB 를 넘기도 한다).
_CWD_PEEK_BYTES = 256_000


def _workdir_of(log: Path) -> str:
    """기록 안의 `cwd`(그 대화를 연 작업 폴더). 폴더 이름(`E----------`)은 한글이 `-` 로 바뀌어 사람이 못 읽는다."""
    try:
        with log.open("rb") as handle:
            head = handle.read(_CWD_PEEK_BYTES).decode("utf-8", "ignore")
    except OSError:
        return ""
    for raw in head.splitlines():
        if '"cwd"' not in raw:
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        cwd = row.get("cwd") if isinstance(row, dict) else None
        if isinstance(cwd, str) and cwd.strip():
            return cwd.strip()
    return ""


def _is_temp(where: str) -> bool:
    """임시 폴더에서 연 대화(측정 · 시험이 만든 것) — 화면에서 접어 둔다. 지우거나 숨기지는 않는다."""
    lowered = where.replace("\\", "/").lower()
    return "/appdata/local/temp/" in lowered or "-appdata-local-temp" in lowered


def claude_projects(home: Path | None = None, limit: int = PROJECTS_LIMIT) -> list[dict[str, Any]]:
    """이 PC 의 클로드 코드 프로젝트 — 최근에 대화한 것부터. 사람이 경로를 손으로 치지 않고 체크로 고르게 한다(2026-10-22).

    본문은 읽지 않는다: 기록 수 · 마지막으로 바뀐 시각 · 작업 폴더(가장 최근 기록 앞부분의 `cwd`)만.
    """
    root = (Path(home) if home else Path.home()) / ".claude" / "projects"
    if not root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        logs: list[tuple[float, Path]] = []
        for log in folder.glob("*.jsonl"):
            try:
                logs.append((log.stat().st_mtime, log))
            except OSError:
                continue
        if not logs:
            continue
        logs.sort(key=lambda item: item[0], reverse=True)
        workdir = _workdir_of(logs[0][1])
        found.append({"folder": str(folder), "name": folder.name, "workdir": workdir,
                      "sessions": len(logs), "last_at": logs[0][0], "temp": _is_temp(workdir or folder.name)})
    found.sort(key=lambda item: item["last_at"], reverse=True)
    return found[:max(1, int(limit))]


def scribe_status(data_dir: Path, folders: list[Path]) -> dict[str, Any]:
    """설정 화면의 상태 줄 — 쌓인 카드(열린 것) · 닫힌 것 · 마지막으로 읽은 시각. 모델은 부르지 않는다."""
    scribe = Scribe(Path(data_dir), folders)
    opened, closes = scribe._split()
    cards = [row for row in opened if not row.get("op")]
    try:
        last_read = scribe._state_path().stat().st_mtime
    except OSError:
        last_read = 0.0
    return {"cards": len(cards), "closed": len({str(row.get("id")) for row in closes}),
            "topics": len(scribe.topics()), "last_read_at": last_read, "reading": len(scribe._logs())}
