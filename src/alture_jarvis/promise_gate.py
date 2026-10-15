"""agent.py 에서 **「한 일인가, 예고인가」 판정** 묶음을 분리한다 (2026-10-09 · 5째 판).

왜: agent.py 가 12,062줄로 커서 읽기 어려웠다. 이 묶음은 BrowserAgent 클래스와
순환 import가 없다 — `re`·`pathlib`·`typing` 과, 이미 agent.py 가 불러오던
`.evidence`·`.transcript_policy` 만 기대한다(둘 다 agent.py 를 불러오지 않는다).

이름 목록(24개):
  _GOAL_MET_CLOSING_STEPS, _GOAL_MET_CLOSING_STEPS_MANIPULATION, _GOAL_MET_CLOSING_SEC,
  _seen_text, table_rows_seen_by_tools, _row_was_seen, _list_items, _cell_pieces,
  steps_against_cap, cap_room, what_was_done_lines, _CORRECTS_EARLIER, _corrects_earlier,
  _PATH_ARGUMENTS, anchor_relative_paths, _only_a_promise, _FUTURE_ENDING,
  _states_a_fact, _promises_in_english, _restore_pointed_back_answer,
  _PROCESS_PURPOSE, _SENTENCE_BREAK, _POLITE_END, _self_directive,
  count_met_by_rows_on_screen
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .evidence import TYPE_BODY_READ as EVIDENCE_TYPE_BODY_READ
from .plan import count_listed_items
from .transcript_policy import PROMISED_ACTION, _ANSWER_BODY_LINE, _PAGE_READ_TOOLS

#: 다시 써도 예고로 끝난 답 끝에 붙이는 한 줄 (2026-10-02 공개 전 필수 ④). 실행 안 된 일을 한 것처럼 두지 않는다.
#: 바닥선을 채운 뒤 모델에게 주는 마무리 한 번 — 도구 최대 이만큼 · 시간 이만큼(초). 넘기면 지금처럼 닫는다.
_GOAL_MET_CLOSING_STEPS = 3
#: 정렬·필터 칸이 있는 조작형 판의 마무리 여유(위치 입력 → 후보 고르기 → 결과 열기가 한 덩어리다).
_GOAL_MET_CLOSING_STEPS_MANIPULATION = 8
_GOAL_MET_CLOSING_SEC = 120.0

def _seen_text(text: str) -> str:
    """도구가 돌려준 글과 답의 칸을 견줄 때의 모양 — 꾸밈 기호 · 빈칸 · 자릿수 쉼표 · 숫자 앞의 0 을 걷어 낸다."""
    # 따옴표 모양도 걷어 낸다 — 도구 결과는 JSON 글이라 따옴표가 `\"` 로 오고, 화면은 굽은 따옴표를 쓴다(2026-10-08 뉴스 제목).
    text = re.sub(r"[*_`~\"'“”‘’\\]", "", str(text or ""))
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"\s+", "", text).casefold()
    return re.sub(r"(?<!\d)0+(?=\d)", "", text)


def table_rows_seen_by_tools(answer: str, messages: list[dict[str, Any]] | None) -> int:
    """답의 표에서 **모든 칸이 도구가 돌려준 글에 그대로 있는** 줄의 수.

    ★ 2026-10-08 대표 운영 판(항공권 조회). 출발지 · 날짜 · 인원 · 정렬 · 시간대를 사이트에서 직접 맞추고, 결과 목록의 위 다섯
      줄을 표로 옮긴 **맞는 답** 끝에 「5개를 열어 보라고 하셨는데 본문까지 연 것은 하나도 없습니다 … 근거가 약합니다」가
      붙었다. 항공편은 목록의 줄이지 하나씩 열어 읽을 글이 아니다 — 값(항공사 · 시각 · 가격)은 전부 화면에서 본 것이었다.
      이 경고는 「연 쪽수」를 세는데, 연 쪽수는 근거의 **대리 눈금**이다. 근거 자체(답의 값이 본 글에 있는가)를 볼 수 있으면
      그쪽이 먼저다. 요청의 낱말로 가르지 않는다 — 「정렬해서 N개」로 가르는 규칙을 운영 요청 1,796개에 대 보니 달라진
      둘이 다 틀린 방향이었다(공고의 고용형태 · 책의 쪽수처럼 열어야 나오는 값).
    칸 하나라도 본 글에 없으면 그 줄은 세지 않는다 — 열어야 나오는 값을 목록만 보고 채운 줄은 여전히 경고를 받는다.
    순위 칸(한두 자리 숫자뿐인 칸)은 값이 아니라서 건너뛴다. 값 칸이 둘 이상인 줄만 센다.
    """
    seen = _seen_text("".join(str(m.get("content") or "") for m in messages or [] if m.get("role") == "tool"))
    if not seen:
        return 0
    lines = [line.strip() for line in str(answer or "").splitlines()]
    rows = 0
    for index, line in enumerate(lines):
        if not line.startswith("|") or not line.strip("|-: "):
            continue  # 표가 아니거나 구분 줄
        if index + 1 < len(lines) and lines[index + 1].startswith("|") and not lines[index + 1].strip("|-: "):
            continue  # 바로 아래가 구분 줄이면 머리 줄
        values = [cell for cell in line.strip("|").split("|")
                  if _seen_text(cell) and not re.fullmatch(r"\d{1,2}", _seen_text(cell))]
        if len(values) >= 2 and _row_was_seen(values, seen):
            rows += 1
    return rows


#: 목록의 한 항목이 시작하는 줄 — 「1. 」「2) 」「- 」「• 」. 들여쓴 줄(아래 딸린 줄)은 항목의 시작이 아니다.
_LIST_ITEM_START = re.compile(r"^(?:\d{1,2}[.)]|[-*•])\s+(?=\S)")
#: 항목에 딸린 「이름표: 값」 줄 — 「   - 가격: 109,900원」. 값 쪽만 본 글과 견준다(이름표는 모델이 붙인 말이다).
_LIST_LABELLED = re.compile(r"^\s*(?:[-*•]\s+)?(?:\*\*)?[^:：|]{1,20}?(?:\*\*)?\s*[:：]\s*(?:\*\*)?(?P<value>\S.*)$")
#: 항목 머리에서 이름이 끝나는 자리 — 설명은 모델이 쓴 말이라 본 글과 견주지 않는다.
_LIST_HEAD_END = re.compile(r"\s+[—–-]\s+|[:：]\s|\s*\(")
#: 숫자가 든 낱말 — 시각 · 가격 · 날짜 · 판 번호. 설명 속에 있어도 값이다(지어낸 숫자는 여기서 걸린다).
_LIST_NUMBER = re.compile(r"[A-Za-z가-힣₩$€£]*\d[\d,.:/\-~%]*\d[A-Za-z가-힣%₩$€£]*|\d+[A-Za-z가-힣%]+")
_LIST_ITEM_LINES = 8


def _list_items(answer: str) -> list[list[str]]:
    """답의 번호 목록·불릿 항목들을, 본 글과 견줄 **값의 묶음**으로 돌려준다.

    한 항목의 값 = 머리의 이름(굵게 쓴 것이 있으면 그것, 없으면 설명이 시작되기 전까지) + 딸린 「이름표: 값」 줄의 값
    + 항목 안의 숫자 든 낱말. 이어 쓴 설명 문장은 모델의 말이라 값으로 치지 않는다.
    """
    lines = str(answer or "").splitlines()
    items: list[list[str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        start = _LIST_ITEM_START.match(line)
        if not start:
            index += 1
            continue
        head_line = line[start.end():].strip()
        body: list[str] = []
        index += 1
        while index < len(lines) and len(body) < _LIST_ITEM_LINES:
            follow = lines[index]
            if not follow.strip() or _LIST_ITEM_START.match(follow) or follow.lstrip().startswith(("#", "|")):
                break
            if not follow.startswith((" ", "\t")):
                break  # 들여쓰지 않은 줄은 항목 밖의 글이다
            body.append(follow)
            index += 1
        bold = re.search(r"\*\*(.+?)\*\*", head_line)
        head = bold.group(1) if bold else _LIST_HEAD_END.split(head_line, maxsplit=1)[0]
        head = head.strip(" `[]")
        values = [head] if _seen_text(head) else []
        for follow in body:
            labelled = _LIST_LABELLED.match(follow)
            if labelled:
                values.append(labelled.group("value").strip(" *`"))
        rest = head_line + " " + " ".join(body)
        for number in _LIST_NUMBER.findall(rest):
            if number not in head and not any(number in value for value in values):
                values.append(number)
        if values:
            items.append(values)
    return items


def list_items_seen_by_tools(answer: str, messages: list[dict[str, Any]] | None) -> int:
    """답의 번호 목록·불릿 항목 가운데, **값이 전부 도구가 돌려준 글의 한 자리에 모여 있는** 항목의 수.

    ★ 2026-10-08 전수조사 3-2. 화면에서 본 줄을 표로 옮긴 답은 되받지 않게 했는데(`table_rows_seen_by_tools`), 같은 것을
      번호 목록으로 옮긴 답은 그대로 되받혔다. 최근 3주 개수 요구가 있던 판에서 번호 목록으로 답한 판은 45판 중 28판이,
      표로 답한 판은 117판 중 22판이 되받혔다. 모델이 답을 어떤 모양으로 쓰는지에 판정이 흔들리면 안 된다.
    이름 하나뿐인 항목(「1. **이름**」)은 그 이름이 세 글자 이상이고 본 글에 그대로 있을 때만 센다.
    """
    seen = _seen_text("".join(str(m.get("content") or "") for m in messages or [] if m.get("role") == "tool"))
    if not seen:
        return 0
    count = 0
    for values in _list_items(answer):
        if len(values) == 1 and len(_seen_text(values[0])) < 3:
            continue
        if _row_was_seen(values, seen):
            count += 1
    return count


def rows_seen_by_tools(answer: str, messages: list[dict[str, Any]] | None) -> int:
    """답이 낸 줄(표 줄 또는 목록 항목) 가운데 화면에서 본 것의 수 — 표와 목록 중 많은 쪽."""
    return max(table_rows_seen_by_tools(answer, messages), list_items_seen_by_tools(answer, messages))


def _row_of_name_was_seen(answer: str, name: str, seen: str) -> bool:
    """그 이름이 든 답의 **표 줄**(또는 목록 항목) 가운데, 모든 값이 본 글에 있는 줄이 있는가(순위 칸은 값이 아니다 · 값이 둘 이상인 줄만).

    ★ 이름 하나뿐인 목록 항목은 여기서 구제하지 않는다 — 이 검사가 지키는 것이 바로 「검색 목록에서 이름만 본 것은 읽은 것이
      아니다」이다. 값이 둘 이상 **한 자리에 모여** 있을 때만 화면의 한 줄을 옮긴 것으로 본다(표와 같은 기준).
    """
    key = _seen_text(name)
    if not key:
        return False
    for values in _list_items(answer):
        if len(values) >= 2 and key in _seen_text(" ".join(values)) and _row_was_seen(values, seen):
            return True
    for line in str(answer or "").splitlines():
        line = line.strip()
        if not line.startswith("|") or key not in _seen_text(line):
            continue
        values = [cell for cell in line.strip("|").split("|")
                  if _seen_text(cell) and not re.fullmatch(r"\d{1,2}", _seen_text(cell))]
        if len(values) >= 2 and _row_was_seen(values, seen):
            return True
    return False


def count_met_by_rows_on_screen(plan_results: list[tuple[Any, bool, str]], seen_rows: int) -> list[tuple[Any, bool, str]]:
    """답의 표 줄 가운데 본 화면에 그대로 있는 줄이 시킨 개수만큼이면, **답에 담으면 충족인 개수 요구**를 채운 것으로 본다.

    읽기 근거를 따로 따지는 요구(`grounding_required`)는 그대로 둔다 — 그쪽은 연 쪽수가 조건이다.
    """
    if seen_rows <= 0:
        return plan_results
    out: list[tuple[Any, bool, str]] = []
    for req, ok, saw in plan_results:
        if (
            not ok
            and str(getattr(req, "kind", "")) == "count"
            and not getattr(req, "grounding_required", False)
            and seen_rows >= int(getattr(req, "target", 0) or 0) > 0
        ):
            out.append((req, True, (str(saw) + " · " if saw else "") + f"답의 {seen_rows}줄이 본 화면에 있음"))
        else:
            out.append((req, ok, saw))
    return out


#: 한 칸에 값 둘을 묶어 쓰는 자리 — 「06:00 → 07:15」·「서울 / 부산」·「정규직 (경력)」. 숫자 사이의 쉼표는 자릿수라 가르지 않는다.
_CELL_PIECES = re.compile(r"[\s→←↔⇒➔∼/·;()\[\]]+|(?<!\d),|,(?!\d)")


def _cell_pieces(cell: str, seen: str) -> list[str] | None:
    """칸의 글을 본 글에서 찾을 조각들 — 통째로 있으면 그것 하나, 없으면 조각마다. 조각 하나라도 본 글에 없으면 None.

    ★ 같은 날 고친 뒤 첫 판(df0e684c): 모델이 출발·도착을 「06:00 → 07:15」 한 칸으로 합쳐 쓰자, 그 글자열이 화면 글에
      그대로는 없다는 이유로 다섯 줄이 전부 「안 본 줄」이 됐다(값은 원문 목록으로 따로 계산해 다섯 줄 다 맞았다).
      모델이 칸을 어떻게 묶어 쓰는지에 판정이 흔들리면 안 된다.
    """
    whole = _seen_text(cell)
    if whole in seen:
        return [whole]
    pieces = [_seen_text(piece) for piece in _CELL_PIECES.split(re.sub(r"[*_`~]", "", str(cell or "")))]
    pieces = [piece for piece in pieces if len(piece) >= 2 or piece.isdigit()]
    if not pieces or any(piece not in seen for piece in pieces):
        return None
    return pieces


#: 한 줄의 값들이 본 글에서 이만큼(빈칸을 걷어 낸 글자 수) 안에 모여 있어야 한다 — 목록의 한 줄과 그 곁의 안내 글 정도.
_ROW_SPAN = 300


def _row_was_seen(values: list[str], seen: str) -> bool:
    """줄의 칸들이 본 글의 **한 자리에 모여** 있는가.

    칸마다 본 글 어딘가에 있는 것으로는 모자라다 — 「정규직」·「경력」·「10.01」은 목록 화면 어디에나 있는 말이라, 이름만
    옮기고 세부를 다른 줄에서 끌어와 채운 줄도 통과한다(2026-09-02 사람인 판이 정확히 그 꼴이었다). 화면의 한 줄은 값들이
    붙어 나온다(「항공사 06:00 07:15 할인석 편도 109,900원」). 가장 긴 조각이 나온 자리마다 그 둘레에 나머지가 다 있는지 본다.
    """
    pieces: list[str] = []
    for value in values:
        found = _cell_pieces(value, seen)
        if found is None:
            return False
        pieces.extend(found)
    if not pieces:
        return False
    anchor = max(pieces, key=len)
    at = seen.find(anchor)
    while at >= 0:
        near = seen[max(0, at - _ROW_SPAN): at + len(anchor) + _ROW_SPAN]
        if all(piece in near for piece in pieces):
            return True
        at = seen.find(anchor, at + 1)
    return False


#: 자율 걸음 상한이 **세지 않는** 걸음 — 이미 열려 있는 화면을 다시 들여다보는 것(조작할 요소 보기 · 화면에서 찾기 · 링크 목록).
#:   ★ 2026-10-08 대표 운영 판(항공권 조회 · 폼 조작). 출발지 · 도착지 · 달력 · 인원 · 정렬 · 시간대를 다 맞추고 48번째 걸음에
#:   거르개 「적용」을 누른 순간 상한에 닿아, 결과 목록을 읽지 못한 채 「덜 끝남」으로 닫혔다. 실패 걸음 0 · 48걸음 중 21걸음이
#:   보기였다 — 누르고 확인하는 모델일수록 상한에 빨리 닿는다. 그 앞 3주의 운영 1,103판 중 이 상한에 걸린 13판이 **전부**
#:   덜 끝남이었고, 시간 상한(1,500초)은 한 번도 일하지 않았다(230~660초에 끊겼다) — 낮은 쪽만 일하고 있었다.
#:   상한이 막으려는 것은 **헛도는 조사**(새 쪽을 계속 여는 꼬리)다. 그래서 열기 · 읽기 · 검색 · 누르기는 지금처럼 다 센다 —
#:   조사 판은 예전 그대로 48 에서 멈춘다. 보기만 되풀이하는 판이 끝없이 가지 않게, 안 세는 몫은 상한의 절반까지다(48 이면 72걸음).
_LOOK_ONLY_TOOLS = frozenset({"browser_snapshot", "browser_find", "browser_links", "browser_annotate"})


def steps_against_cap(steps: list[dict[str, Any]], cap: int) -> int:
    """자율 걸음 상한에 대고 셀 걸음 수 — 열려 있는 화면을 다시 본 걸음은 상한의 절반까지 빼고 센다."""
    looks = sum(1 for step in steps or [] if str((step or {}).get("tool") or "") in _LOOK_ONLY_TOOLS)
    return len(steps or []) - min(looks, max(0, int(cap)) // 2)


def cap_room(config: Any, steps: list[dict[str, Any]]) -> int:
    """자율 걸음 상한까지 남은 자리 — 0 이하면 상한에 닿은 것. 화면을 다시 본 걸음은 덜 센다(`steps_against_cap`)."""
    cap = max(1, int(config.agent_autonomous_max_steps))
    return cap - steps_against_cap(steps, cap)

#: 예고 되받기 상한 — 일을 하면서 중간중간 예고하는 판은 이만큼까지 이어 간다(되받기 사이에 도구를 써야 다음 되받기가 열린다).
_ANNOUNCE_PUSHBACK_MAX = 4

#: 화면에 값을 넣는 도구 · 누르는 도구 — 마무리 글이 비었을 때 「한 일」을 기록에서 옮길 때 본다.
_ENTRY_STEP_TOOLS = frozenset({"browser_fill", "browser_fill_form", "browser_select_option", "browser_pick_suggestion",
                               "browser_type_at", "browser_file_upload"})
_PRESS_STEP_TOOLS = frozenset({"browser_click", "browser_click_confirmed", "browser_click_at", "browser_press"})


def what_was_done_lines(steps: list[dict[str, Any]], *, english: bool = False, keep: int = 14) -> list[str]:
    """이 판이 화면에서 **실제로 한 일**을 도구 기록에서 그대로 옮긴다 — 지어내지 않는다. 한 일이 없으면 빈 목록.

    마무리 글을 끝내 못 받은 판에서 쓴다. 읽기·찾기는 옮기지 않는다(그건 한 일이 아니라 본 것이다).
    """
    lines: list[str] = []
    for step in steps:
        if not step.get("ok"):
            continue
        tool = str(step.get("tool") or "")
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        if tool in _ENTRY_STEP_TOOLS:
            name = " ".join(str(evidence.get("field") or "").split())[:60]
            if english:
                lines.append(f"- entered a value in the field \"{name}\"" if name else "- entered a value in a field")
            else:
                lines.append(f"- 「{name}」 칸에 값을 넣음" if name else "- 칸에 값을 넣음")
        elif tool in _PRESS_STEP_TOOLS:
            name = " ".join(str(evidence.get("label") or "").split())[:60]
            if english:
                lines.append(f"- pressed \"{name}\"" if name else "- pressed something on the page")
            else:
                lines.append(f"- 「{name}」 누름" if name else "- 화면의 무언가를 누름")
    if len(lines) > keep:
        skipped = len(lines) - keep
        lines = [f"- (earlier: {skipped} more)" if english else f"- (앞의 {skipped}개는 줄임)"] + lines[-keep:]
    return lines


_NO_CLOSING_ANSWER_NOTE = (
    "(걸음·시간 한도에 닿아 작업을 멈췄고, 마무리 설명을 받지 못했습니다. 아래는 도구 기록에서 옮긴 **실제로 한 일**입니다 — "
    "저장·제출까지 됐는지는 화면에서 확인해 주세요. 「이어서 해줘」라고 하시면 이어갑니다.)"
)
_NO_CLOSING_ANSWER_NOTE_EN = (
    "(Sonjari hit its step or time limit and did not get a closing summary. Below is what it **actually did**, copied from "
    "the tool records — please check on the page whether it was saved or submitted. Say \"continue\" to pick it up.)"
)

_PROMISE_ONLY_NOTE = "(손자리가 다음 할 일을 예고만 하고 멈췄습니다 — 그 일은 실행되지 않았습니다. 「이어서 해줘」라고 하시면 이어갑니다.)"
#: 한글 글자 — 영어 요청에 한국어 위주로 답했는지 셀 때(최종 언어 다시 쓰기).
_HANGUL_RE = re.compile("[가-힣]")
#: 영어로 시킨 판의 같은 알림(2026-10-03 Online-Mind2Web B 판 — 영어 답 끝에 위 한국어 알림이 붙었다).
_PROMISE_ONLY_NOTE_EN = ("(Sonjari announced its next step and stopped — that step was not carried out. "
                         "Say \"continue\" to pick it up.)")


#: 답이 **내용은 앞 답에 있다고 가리키는** 꼴 — 「목록은 위에 있다」·「shown above」·「앞서 드린 답변과 동일」.
#: ★ 좁게 잡는다(운영 답 2,604개 역검증, 10-03): 넓게 잡으면 「앞서 말씀하신」(사용자 말)·한 답 안의 「위 표」·
#:   「이전 답변에서 잘못 말씀드렸습니다」(바로잡는 답)까지 걸렸다. 바로잡는 답에서 앞 답을 되살리면 틀린 답으로 돌아간다.
_POINTS_BACK = re.compile(
    r"(?i)\b(?:is|are)\s+(?:shown|listed|given|provided|included|presented)\s+above\b"
    r"|\b(?:shown|listed|given|provided)\s+in\s+my\s+(?:previous|earlier|last)\s+(?:answer|reply|message|response)\b"
    r"|\bsee\s+(?:above|my\s+(?:previous|earlier|last)\s+(?:answer|reply|message|response))\b"
    r"|(?:목록|표|답|결과)[은는이가]\s*(?:이미\s*)?(?:위에|앞에)\s*(?:있|나와|정리|적)"
    r"|(?:위에|앞서|앞에서|이전\s*답변?에서|직전\s*답변?에서)\s*(?:이미\s*)?(?:정리해\s*|적어\s*|보여\s*)?드린\s*(?:답|답변|목록|표|내용|정리)")
#: 앞 답을 **바로잡는** 답 — 이런 답에서는 앞 답을 되살리지 않는다.
_CORRECTS_EARLIER = re.compile(
    r"(?i)사과|죄송|미안|잘못|폐기|정정|틀렸|바로잡|\bapolog|\bmistake|\bincorrect|\bwrong\b|\bcorrect(?:ed|ion)\b|\bretract")


def _restore_pointed_back_answer(answer: str, earlier: list[str]) -> str:
    """마지막 답이 앞 답을 가리키는데 앞 답이 훨씬 실속 있으면 그 앞 답. 아니면 빈 문자열.

    「훨씬」= 200자 이상이고 마지막 답의 1.5배 이상. 앞 답도 앞을 가리키거나 예고뿐이면 건너뛰고 더 앞을 본다.
    한 답 안에서 「위 표처럼」이라고 스스로 가리키는 긴 답은 앞 답이 더 길지 않으면 그대로 둔다.
    """
    if not answer or not _POINTS_BACK.search(answer) or _CORRECTS_EARLIER.search(answer):
        return ""
    for candidate in reversed(earlier):
        if candidate.strip() == answer.strip() or _POINTS_BACK.search(candidate) or _only_a_promise(candidate):
            continue
        if len(candidate) >= 200 and len(candidate) >= 1.5 * len(answer):
            return candidate
    return ""


#: 새 근거를 만들지 않는 걸음 — 보기만 하는 도구와 창 닫기. 이미 읽은 주소를 다시 읽은 것도 새 근거가 아니다.
_NO_NEW_GROUND_TOOLS = _LOOK_ONLY_TOOLS | frozenset({"browser_close", "browser_screenshot"})
#: 그 페이지의 **내용을 돌려주는** 걸음 — 본문 추출과 화면 보기. 연 바로 다음에 이것이 오면 그 페이지를 읽은 것이다.
_READ_OR_LOOKED_AT_PAGE = frozenset({"browser_extract", "browser_read", "browser_snapshot", "browser_find", "browser_page_data"})


def _nothing_new_since(steps: list[dict[str, Any]], since: int) -> bool:
    """`since` 번째 걸음 뒤로 **새로 본 것이 없는가** — 보기만 했거나, 이미 읽은 주소를 다시 읽었거나, 실패한 걸음뿐."""
    before = {str((step.get("evidence") or {}).get("url") or "") for step in steps[:since]} - {""}
    for step in steps[since:]:
        if not step.get("ok"):
            continue
        tool = str(step.get("tool") or "")
        if tool in _NO_NEW_GROUND_TOOLS:
            continue
        url = str((step.get("evidence") or {}).get("url") or "")
        if tool in _PAGE_READ_TOOLS and url and url in before:
            continue
        return False
    return True


def _answer_that_lost_its_rows(answer: str, earlier: list[str], earlier_steps: list[int], steps: list[dict[str, Any]]) -> str:
    """줄(표·목록)이 있던 앞 답을, 줄이 하나도 없는 마지막 답이 덮었으면 그 앞 답. 아니면 빈 문자열.

    ★ 2026-10-08 실기(깃허브 트렌딩 판 98fcd10c). 모델이 저장소 다섯을 목록으로 냈는데 대조표가 헛되받았고(「5개 처리하라」),
      모델은 「이미 목록에서 상위 5개를 모두 확인해 답에 담았습니다 … 추가할 것이 없습니다」라고 대꾸했다. 하네스는 그 한 줄을
      최종 답으로 가져가 **목록이 사라졌다.** 「위에 있습니다」 꼴 낱말표(`_POINTS_BACK`)는 이 말을 못 알아봤다.
    낱말이 아니라 사실로 가른다 — ① 마지막 답에는 줄이 없고 ② 앞 답에는 줄이 둘 이상 있었고 ③ 그 답 뒤로 **새로 본 것이 없다**
    (새 근거 없이 줄이 사라졌다면 그것은 우리에게 한 대꾸다). 새로 읽고 나서 줄을 거둔 답은 그대로 둔다 — 그건 고친 답이다.
    앞 답을 바로잡는 답(「잘못 말씀드렸습니다」)도 그대로 둔다.
    """
    if not answer or not earlier or _CORRECTS_EARLIER.search(answer) or count_listed_items(answer) > 0:
        return ""
    for candidate, at in zip(reversed(earlier), reversed(earlier_steps)):
        if candidate.strip() == answer.strip():
            continue
        if not _nothing_new_since(steps, at):
            return ""
        if count_listed_items(candidate) >= 2:
            return candidate
    return ""


#: 로컬 도구의 인자 가운데 **경로**인 칸.
_PATH_ARGUMENTS = ("path", "source", "destination", "cwd", "directory", "folder", "root", "target")


def anchor_relative_paths(arguments: dict[str, Any], root: str) -> dict[str, Any] | None:
    """경로 칸의 **상대 경로**를 작업 폴더 밑의 경로로 바꾼 인자. 바꾼 것이 없으면 None.

    절대 경로 · 홈(`~`) · 환경변수(`%…%` · `$…`)로 시작하는 값은 그대로 둔다. 작업 폴더 밖으로 나가는지는 여기서 보지 않는다 —
    그 검사는 도구의 허용 범위 문이 그대로 한다(`..` 로 빠져나가려는 경로는 거기서 막힌다).
    """
    base = Path(root)

    def fix(value: Any) -> Any:
        if isinstance(value, list):
            return [fix(item) for item in value]
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if not raw or raw.startswith(("~", "%", "$")) or "://" in raw:
            return value
        try:
            candidate = Path(raw)
        except (TypeError, ValueError):
            return value
        if candidate.is_absolute() or candidate.drive or raw.startswith(("/", chr(92))):
            return value
        return str(base / candidate)

    changed = {key: (fix(value) if key in _PATH_ARGUMENTS or key == "paths" else value) for key, value in arguments.items()}
    return None if changed == arguments else changed


def _only_a_promise(answer: str) -> bool:
    """답 전체가 「~찾아보겠습니다」 같은 예고 한두 문장뿐인가.

    ★ 같은 벤치(대학알리미 · 바꾼 뒤): 블로그 한 편을 읽고 나서 답이
    「대학알리미에서 취업률 지표를 확인하는 방법을 찾아보겠습니다.」 한 줄이었다. 옛 되받기는 「읽은 것이
    있다」는 이유로 꺼져 있었다 — 읽은 것이 있어도 **답이 예고뿐이면** 사람에게 줄 것이 없다.
    """
    text = str(answer or "").strip()
    if not text or _ANSWER_BODY_LINE.search(text):
        return False
    if len(text) > 200:
        # ★ 영어는 한 문장이 길다 (2026-10-03 Online-Mind2Web A 판 공식 조건). 「… so let me verify the sort actually worked by
        #   re-checking the Sort button's current state.」(225자)가 상한 200을 넘어 그물을 안 타고 complete 로 나갔다.
        #   영어 예고만 450자까지 본다 — 운영 영어 답 64개 역검증: 새로 걸린 3개 전부 진짜 예고, 700자로 넓혀도 더 없음, 헛걸림 0.
        return len(text) <= 450 and _promises_in_english(text)
    # ★ 고친 판 벤치(날씨): 「…검색 버튼을 눌러 부산 날씨 페이지로 **이동하겠습니다**.」 — 낱말표(`PROMISED_ACTION`)에 「이동」이 없어
    #   또 빠져나갔다. 낱말표는 계속 뚫린다. 짧은 답이 **앞으로 할 일로 끝나면**(~겠습니다·~할게요) 그 자체가 예고다.
    return bool(PROMISED_ACTION.search(text) or _FUTURE_ENDING.search(text) or _self_directive(text)
                or _plain_inner_monologue(text) or announces_present_action(text) or _promises_in_english(text)
                or _announces_without_a_result(text))


# ★ 영어 예고 (2026-10-03 Online-Mind2Web A 판). 「Redfin is also blocked. Let me try one more source — rent.com — …」·
#   「The form fields aren't persisting my selections. Let me try Expedia's direct package search URL …」가 최종 답인데
#   `goal_met`·`complete` 로 나갔다 — 한국어 그물(~하겠습니다·~확인합니다)만 있고 영어는 없었다. 짧은 답의 **마지막 문장**이
#   「Let me / I'll / I will / I'm going to + 일하는 동사」면 결과가 아니라 다음 걸음이다.
#   운영 영어 답 23개로 쟀다: 걸린 것 1(진짜 예고), 헛걸림 0 · A 판 두 판(#7·#11) 다 걸림.
_PROMISE_EN = re.compile(
    # ★ 동사 목록이 아니라 **모양**으로(B 판 2차: 「Let me type …」·「Let me snapshot …」·「Let me examine …」가 목록 밖이라 빠졌다).
    #   「Let me know」·「I'll be happy」 같은 맺음말만 뺀다. 운영 영어 답 52개 역검증: 걸린 8개 전부 진짜 예고, 헛걸림 0.
    r"(?i)\b(?:let\s+me\s+(?!know\b)|i['’]ll\s+(?!be\b)|i\s+will\s+(?!be\b)|i['’]m\s+going\s+to\s+|now\s+i['’]ll\s+"
    r"|next,?\s+i['’]ll\s+)[a-z]+\b[^\n]*$"
)


def _promises_in_english(text: str) -> bool:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", text) if part.strip()]
    return bool(sentences) and bool(_PROMISE_EN.search(sentences[-1]))


# ★ 현재형 존댓말 예고 (2026-10-01 밤 운영 판 b9f90b2c·c430d75c·54f2d6b3 — 세 판 연속).
#   허깅페이스를 9걸음 읽고 최종 답이 「목록에 모델명이 안 나와서 snapshot으로 실제 링크를 확인합니다.」였고 **complete** 로 나갔다.
#   미래 꼴(~겠습니다)도 반말도 아니라 위 그물을 다 빠져나갔고, 그 답이 대화에 남자 다음 두 판도 같은 꼴(「…찾기 위해 검색합니다」·
#   대화 갈래의 「…조사 중입니다」)로 끝났다. 짧은 답의 **마지막 문장**이 자기 동작을 현재형으로 말하면(~확인합니다·~검색합니다·
#   ~조사 중입니다·~찾아봅니다) 그것은 결과가 아니라 다음 걸음이다.
#   넣기 전 운영 답 2,469개로 쟀다: 새로 걸린 4개가 전부 진짜 예고, 오탐 0. 「확인했습니다」(과거)·「~입니다」(사실)는 안 걸린다.
_PRESENT_SELF_ACTION = re.compile(
    r"(?:(?:확인|검색|탐색|조회|추출|이동|시도|재시도|클릭|스크롤|조사|비교|진행|접속|수집|열람)(?:합니다|하고\s*있습니다|\s*중입니다)"
    r"|(?:찾아|살펴|열어|읽어|들어가|알아|둘러)\s*(?:봅니다|보고\s*있습니다|보는\s*중입니다)"
    r"|(?:엽니다|읽습니다|찾습니다|넘어갑니다|내려갑니다|들어갑니다))[.!…~\s]*$"
)


def announces_present_action(answer: str) -> bool:
    """짧은 답이 자기 다음 동작을 현재형으로 말하며 끝나는가(「~확인합니다」·「~조사 중입니다」). 라우터 직답에도 쓴다."""
    text = str(answer or "").strip()
    if not text or len(text) > 200 or _ANSWER_BODY_LINE.search(text):
        return False
    sentences = [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]
    return bool(sentences and _PRESENT_SELF_ACTION.search(sentences[-1]))


# ★ 반말 혼잣말로 끝난 답 (2026-10-01 운영 MCP 판 d60f38d3). Steam 설문을 세 장 읽고 최종 답이
#   「VRAM 상세 비율이 페이지 본문에 안 보인다. Steam은 동적 테이블을 쓰는데, browser_extract로 본문만 추출해 본다.」였고
#   **complete** 로 바깥 AI 에게 갔다. 미래 꼴(~겠습니다)도, 과정 목적(~찾기 위해)도 없어 위 그물을 다 빠져나갔다.
#   표식은 둘 중 하나 + 전부 반말 평서형: ① 우리 도구 이름을 말한다(사람에게 하는 답이 아니라 자기 작업 메모) ② 마지막 문장이
#   「~해 본다·~해 보자·~하자」(다음 할 일). 「전문가들은 성장으로 본다」 같은 답 내용은 도구 이름도 「해 본다」도 없어 안 걸린다.
_TOOL_NAME_IN_SPEECH = re.compile(r"\b(?:browser|local|google|naver|unity|sandbox|site|skill)_[a-z_]+\b")
_TRY_NEXT_ENDING = re.compile(r"(해\s*본다|해\s*보자|해\s*봐야겠다|하자|보자|가자|읽자|열자|찾자)[.!…~\s]*$")


def _plain_inner_monologue(text: str) -> bool:
    sentences = [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]
    if not sentences:
        return False
    plain = all(sentence.rstrip(".!?…~ ").endswith(("다", "자")) and not _POLITE_END.search(sentence) for sentence in sentences)
    if not plain:
        return False
    return bool(_TOOL_NAME_IN_SPEECH.search(text) or _TRY_NEXT_ENDING.search(sentences[-1]))


_FUTURE_ENDING =re.compile(r"(겠습니다|겠어요|할게요|볼게요|드릴게요|올게요)[.!…~\s]*$")


def _states_a_fact(sentence: str) -> bool:
    """문장이 **한 일·있는 사실**로 끝나는가 — 「읽었습니다」·「없었습니다」·「있습니다」. 「~겠습니다」(앞으로 할 일)는 아니다.

    낱말표가 아니라 글자 모양으로 본다: 맺음말(습니다·어요·다) 앞 글자의 받침이 ㅆ 이면 과거·상태다. 「겠」만 뺀다.
    """
    body = sentence.rstrip(".!?…~ ")
    for tail in ("습니다", "어요", "다"):
        if body.endswith(tail) and len(body) > len(tail):
            before = body[-len(tail) - 1]
            if "가" <= before <= "힣" and (ord(before) - 0xAC00) % 28 == 20 and before != "겠":
                return True
    return False


def _announces_without_a_result(text: str) -> bool:
    """짧은 답의 **어느 문장이든** 앞으로 할 일이고, 한 일·사실을 말한 문장도 되묻는 문장도 없는가.

    ★ 2026-10-04 실전 판(e055235f · 사람인 → 엑셀): 검토 지적을 받고 최종 답이 「…담당업무 표기를 수정하고 최종 답을 다시
      작성하겠습니다. 엑셀 파일을 수정합니다.」였는데 `complete` 로 나갔다. 그물은 **마지막 문장**만 봤고(「수정합니다」는
      낱말표에 없다), 예고는 첫 문장에 있었다. 낱말을 더하는 대신 모양으로: 짧은 답에 「~겠습니다」 문장이 있고 **결과를 말한
      문장이 하나도 없으면** 사람에게 줄 것이 없다. 「정정하겠습니다. 실제로는 2개를 읽었습니다.」(결과 있음)와
      「주소를 알려 주시면 접속해 드릴게요. 로그인돼 있나요?」(사람에게 묻는 답)는 그대로 둔다.
      운영 답 2,023개 역검증: 새로 걸리는 것 1(이 판), 헛걸림 0.
    """
    sentences = [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]
    if any(sentence.endswith("?") or _states_a_fact(sentence) for sentence in sentences):
        return False
    return any(_FUTURE_ENDING.search(sentence) for sentence in sentences)

# ★ 「~하겠습니다」가 아니라 **자기에게 거는 지시**로 끝나는 속말 (2026-09-28 MCP 위임 판 78671832).
#   여덟 곳을 읽고 최종 답이 「llama.cpp 저장소에서 --override-tensor 옵션을 찾기 위해 GitHub 코드 검색을 올바르게 사용한다.」
#   두 번이었다. 예고 그물은 미래 꼴만 봐서 이 「~한다」 꼴을 못 잡았다. 표식은 둘을 **같이** 본다 — 문장이 전부 반말 평서형(「다.」,
#   「니다」 아님)이고, **일하는 과정**(찾기·검색·확인·읽기)을 목적으로 댄다. 「옵션을 쓰면 전문가를 CPU 로 보낸다」 같은 답 내용은
#   과정 목적이 없어서 안 걸린다.
_PROCESS_PURPOSE = re.compile(r"(찾|검색하|확인하|읽|열|알아보|살펴보|조사하|파악하|탐색하)(기\s*위해|려고|고자)")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")  # 「llama.cpp」의 점은 문장 끝이 아니다
_POLITE_END = re.compile(r"(니다|요|죠|까)[.!?…~\s]*$")


def _self_directive(text: str) -> bool:
    sentences = [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]
    if not sentences or not _PROCESS_PURPOSE.search(text):
        return False
    return all(sentence.rstrip(".!?…~ ").endswith("다") and not _POLITE_END.search(sentence) for sentence in sentences)
