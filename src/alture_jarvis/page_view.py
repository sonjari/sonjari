"""측정 스위치 `JARVIS_AGENT_PAGE_VIEW` (2026-11-11 · 기본 꺼짐).

대표 가설: 작은 모델일수록 맥락이 접히면 길을 잃는다 — 지금 화면과 기준점이 있으면 덜 잃는다.
기준점 = 화면에 그린 분홍 번호 상자 + 같은 번호 목록(글). 상자 숫자는 번호표의 숫자다(`j12` → 「12」, `browser._MARK_JS`).
★ 11-11: 안내 글이 「ref(예: e12)」라고 가르쳤는데 번호표는 `j12` 다 — 측정 9칸 중 4칸이 같은 실패 5번으로 멈춘 뿌리 중 하나.
  누르기 쪽도 숫자만 · `e12` 를 `j12` 로 받게 했다(`browser._coerce_ref`).
SeeAct · WebVoyager 처럼 그림과 글을 같이 준다 — 그림만 주면 작은 모델이 번호를 잘못 읽는다.
설계: generated_reports/lora_9b_1109/설계_v3_스크린샷기준점_1111.md
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

#: 그림에 그릴 번호 상한. 많으면 작은 모델이 못 고른다(Aria-UI) — 재서 정한다.
PAGE_VIEW_MARKS = 40
#: 목록 글 한 줄의 이름 길이.
_NAME_MAX = 60


def last_browser_tool(messages: list[dict[str, Any]]) -> str:
    """모델의 마지막 말 뒤에 브라우저 도구 결과가 있으면 그 도구 이름, 아니면 빈 글.

    끝에 하네스 안내(user · system)가 붙어 있어도 거슬러 올라간다 — 11-11 노트북 판에서 끝이 `user` 라 놓친 걸음이 있었다.
    """
    for message in reversed(messages or []):
        role = str(message.get("role") or "")
        if role == "assistant":
            return ""
        if role == "tool":
            name = str(message.get("tool_name") or message.get("name") or "")
            return name if name.startswith("browser_") else ""
    return ""


def last_browser_failure(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """모델의 마지막 말 뒤 브라우저 걸음이 **실패**였으면 (도구 이름, 오류 앞부분), 아니면 빈 둘.

    ★ 11-11 노트북 그림 켬 측정: 멈춘 4칸 모두 같은 걸음을 5번 되풀이했다(없는 번호 · 없는 순위 · 낡은 목록 · 지어낸 주소).
      오류 문구는 분명했는데, 그 뒤에 「지금 화면」 그림이 **사용자 말로 맨 끝에** 붙어 모델이 마지막에 읽는 글이 오류가 아니었다.
      실패한 걸음 뒤 그림에는 그 오류를 맨 윗줄에 같이 둔다 — 새 지시가 아니라 이미 받은 오류를 읽는 자리로 옮기는 것이다.
    """
    for message in reversed(messages or []):
        role = str(message.get("role") or "")
        if role == "assistant":
            return "", ""
        if role != "tool":
            continue
        name = str(message.get("tool_name") or message.get("name") or "")
        if not name.startswith("browser_"):
            return "", ""
        text = str(message.get("content") or "")
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            if data.get("ok") is False:
                return name, " ".join(str(data.get("error") or "failed").split())[:_FAIL_MAX]
            return "", ""
        # 길어서 잘린 결과는 JSON 으로 안 풀린다 — 머리의 ok · error 만 본다.
        if re.search(r'"ok"\s*:\s*false', text):
            found = re.search(r'"error"\s*:\s*"((?:[^"\\]|\\.){0,400})', text)
            return name, " ".join((found.group(1) if found else "failed").split())[:_FAIL_MAX]
        return "", ""
    return "", ""


#: 그림 윗줄에 옮기는 오류 길이.
_FAIL_MAX = 220


def build_page_view(result: dict[str, Any], *, english: bool = False, max_lines: int = PAGE_VIEW_MARKS,
                    failure: tuple[str, str] = ("", "")) -> dict[str, Any] | None:
    """`browser_annotate` 결과 → 일회용 user 메시지(글 + 그림). 그림 파일이 없으면 None."""
    path = Path(str(result.get("path") or ""))
    if not str(path) or not path.is_file():
        return None
    raw = path.read_bytes()
    lines = []
    for item in (result.get("candidates") or [])[:max_lines]:
        ref = str(item.get("ref") or "")
        if not ref:
            continue
        name = " ".join(str(item.get("name") or "").split())[:_NAME_MAX]
        lines.append(f"{ref[1:] or ref} = {ref} · {item.get('role') or ''} · {name}".rstrip(" ·"))
    if english:
        head = ("[Current screen, attached by Sonjari, not the user] Pink box number 12 = element ref j12 in the list below. "
                "To click or fill, pass ref j12. It is not a result rank: never pass a box number as browser_open_result's rank. "
                "Copy values exactly as shown.")
    else:
        head = ("[지금 화면 · 손자리가 붙임 · 사용자가 한 말 아님] 분홍 상자 숫자 12 = 아래 목록의 번호표 j12. "
                "누르거나 채울 때는 ref 에 j12 를 쓴다. 이 숫자는 검색 결과 순위가 아니다 — browser_open_result 의 rank 로 쓰지 않는다. "
                "화면에 보이는 값은 그대로 옮긴다.")
    tool, error = failure
    if tool:
        if english:
            head = (f"[The last step failed: {tool} — {error}] Do not repeat it with the same arguments; "
                    "use a ref from this screen or a different tool.\n" + head)
        else:
            head = (f"[방금 걸음 실패: {tool} — {error}] 같은 인자로 다시 하지 말고, 이 화면의 번호표나 다른 도구로 바꾼다.\n" + head)
    return {
        "role": "user",
        "content": head + ("\n" + "\n".join(lines) if lines else ""),
        "images": [base64.b64encode(raw).decode("ascii")],
        "_image_bytes": len(raw),
        # 예산 재기에서 이 메시지를 글자로는 빼고 토큰으로만 남긴다 — 다음 화면 몫이 예산에서 저절로 비워진다(`agent._note_prompt_size`).
        "_page_view": True,
    }
