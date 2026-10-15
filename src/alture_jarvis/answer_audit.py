"""답이 **자기 두 줄 사이에서** 모순되는가 (2026-09-21).

## 왜 생겼나

AURORA 2차 재측정에서 판은 합격했는데(19걸음·complete·verified) 답이 이랬다:

    - `verify_aurora.py` 는 검증 완료 후 삭제했습니다.

    만든 파일:
    - ...\\verify_aurora.py              ← 두 줄 아래

걸음을 보면 둘 다 사실이었다 — 17걸음에서 지웠고 **18걸음에서 다시 만들었다.**
그래서 「삭제했습니다」는 그때는 참이었고 답을 쓰는 시점에는 거짓이다.

## 왜 이 검사가 싸고 강한가

이 저장소는 「안 한 일을 했다고 한다」를 여러 번 겪었고, 그걸 잡으려면 보통
**밖의 사실**과 대조해야 한다(파일이 있나, 페이지에 그 값이 있나). 그런데 이 건은
**답이 스스로 증거를 옆에 적어 놨다.** 두 줄만 맞대 보면 된다.

## 무엇을 하고 무엇을 안 하나

- 답을 **고치지 않는다.** 지우지도 않는다.
- 원장에 **모순을 적는다.** 사람과 다음 판이 본다.

조용히 고치면 다음에 또 모르고, 조용히 넘어가면 사람이 속는다.
이 저장소의 규칙 그대로다 — 비운 칸이 있으면 말한다.
"""

from __future__ import annotations

import re
from typing import Any

#: 「만든 파일」 목록이 시작되는 자리. 답의 맨 끝에 붙는 관례를 따른다.
_MADE_HEADING = re.compile(r"^\s*(?:##+\s*)?(?:만든 파일|생성(?:한|된) 파일|산출물)\s*[:：]?\s*$", re.M)

#: 목록 줄에서 꺼낸 파일 이름. 경로 전체가 아니라 **마지막 조각**만 본다 —
#: 답의 산문은 보통 짧은 이름으로 부르고 목록은 절대 경로를 적는다.
_LIST_ITEM = re.compile(r"^\s*[-*]\s+`?([^`\n]+?)`?\s*$", re.M)

#: 「지웠다」고 말하는 흔한 모양. 파일 이름이 앞에 오는 경우와 괄호 안에 오는 경우 둘 다.
_DELETED = re.compile(
    r"`?([\w.\-]+\.\w{1,6})`?\s*(?:을|를|은|는|\))?[^.\n]{0,40}?"
    r"(?:(?:삭제|제거)(?:했|하였|함|됐|되었)|지웠|지웠습니다|없앴)",
)


def _made_files(answer: str) -> set[str]:
    """답이 「만들었다」고 적은 파일들의 **이름만**."""
    heading = _MADE_HEADING.search(answer)
    if heading is None:
        return set()
    tail = answer[heading.end():]
    out: set[str] = set()
    for match in _LIST_ITEM.finditer(tail):
        raw = match.group(1).strip()
        if not raw:
            continue
        name = re.split(r"[\\/]", raw)[-1].strip()
        # 목록이 끝나고 다른 문단이 시작되면 거기서 멈춘다.
        if name and "." in name and " " not in name:
            out.add(name)
    return out


def contradictions(answer: str) -> list[dict[str, Any]]:
    """답 안에서 서로 부딪치는 말. 없으면 빈 목록.

    지금 잡는 것은 하나다 — **지웠다고 하고 만든 파일에 적은 것.**
    종류를 늘릴 때는 늘 같은 규칙을 지킨다: 오탐이 없는 것만 넣는다.
    멀쩡한 답에 경고를 붙이면 아무도 경고를 안 읽는다.
    """
    text = str(answer or "")
    if not text.strip():
        return []
    made = _made_files(text)
    if not made:
        return []
    found: list[dict[str, Any]] = []
    for match in _DELETED.finditer(text):
        name = match.group(1).strip()
        if name in made:
            found.append({
                "kind": "deleted_but_listed",
                "file": name,
                "detail": (
                    f"답이 `{name}` 을(를) 「삭제했다」고 적어 놓고 "
                    f"「만든 파일」에도 적었다 — 둘 중 하나는 지금 사실이 아니다."
                ),
            })
    return found
