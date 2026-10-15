"""사람에게 **선택지로** 묻는다 — 질문 카드 (2026-09-30).

## 왜 생겼나

대표: 「클로드처럼 추천 표시 단 선택지 질문을 왜 못 던지나」. 묻는 도구가 **아예 없었다.**
애매하면 모델이 답 끝에 글로 묻고 판을 끝냈다 — 사람이 대답하면 새 판이 처음부터 다시 돈다.

## 어떻게 도나

승인 카드 틀을 그대로 빌린다(새 멈춤·이어감을 따로 만들지 않는다).

1. 모델이 `ask_user(question, options, recommended)` 를 부른다 → 게이트웨이가 L2 로 보고 카드를 만든다.
   잡은 승인 대기처럼 멈추고 체크포인트에 **이 호출 그대로** 남는다.
2. 화면이 카드를 질문으로 그린다(선택지 버튼 · 추천 표시 · 직접 입력).
3. 사람이 고르면 답이 승인 기록(`approvals.answer`)에 실린다 → 잡이 다시 줄에 선다.
4. 재개가 같은 호출을 재생하면 게이트웨이가 승인을 소비하며 답을 `__answer` 로 넘기고,
   이 도구가 그 답을 모델에게 돌려준다. 모델은 **그 자리에서** 이어 간다.

질문은 어느 권한 모드에서도 자동으로 지나가지 않는다(`ToolGateway._auto_approvable`).
"""

from __future__ import annotations

import re
from typing import Any

from .models import RiskLevel
from .stray_han import mend
from .tool_gateway import ASK_USER_TOOL, ToolGateway, ToolSpec

#: 선택지 수. 둘보다 적으면 물을 게 없고, 넷보다 많으면 사람이 안 읽는다(클로드 앱과 같은 폭).
MIN_OPTIONS = 2
MAX_OPTIONS = 4

_DESCRIPTION = (
    "사용자에게 선택지로 묻고 답을 받을 때까지 기다린다. 요청이 둘 이상으로 읽히고 잘못 고르면 "
    "되돌리기 번거로울 때만 쓴다(예: 무엇을 만들지·어느 파일을 고칠지·어느 방식으로 할지). "
    "선택지는 2~4개, 짧게. 가장 나은 것 하나를 recommended 로 표시하라. "
    "찾아보면 알 수 있는 것은 묻지 말고 찾아라. 답은 이 도구의 결과(answer)로 돌아온다."
)

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "사용자에게 할 질문 한 문장"},
        "options": {
            "type": "array",
            "description": "선택지 2~4개",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "버튼에 뜰 짧은 글(1~6낱말)"},
                    "description": {"type": "string", "description": "고르면 어떻게 되는지 한 줄"},
                },
                "required": ["label"],
            },
        },
        "recommended": {
            "type": "integer",
            "description": "추천하는 선택지의 번호(0부터). 모르면 생략",
        },
    },
    "required": ["question", "options"],
}


def normalize_options(raw: Any) -> list[dict[str, str]]:
    """모델이 준 선택지를 카드에 그릴 모양으로. 글자만 준 목록도 받는다."""
    options: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            label, description = item.strip(), ""
        elif isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            description = str(item.get("description") or "").strip()
        else:
            continue
        if label and all(label != existing["label"] for existing in options):
            options.append({"label": label[:80], "description": description[:200]})
    return options[:MAX_OPTIONS]


_THOUGHT = re.compile(r"<(think|thought)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_STRAY_THOUGHT_END = re.compile(r"</(?:think|thought)\s*>", re.IGNORECASE)
_OPTION_LINE = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•]|[①-④])\s+(.+?)\s*$")
#: 질문의 끝 — 물음표, 또는 고르라는 말.
_QUESTION_END = re.compile(r"(?:[?？]|(?:골라|선택해|고르|정해)\s*주(?:세요|십시오)[.!]?)\s*$")
#: **고르는** 질문이라는 표시. 「다시 찾아드릴까요?」 같은 예/아니오는 선택지 카드가 아니다(운영 답 2,379개 재 보니
#: 헛발동 대부분이 소제목 목록 뒤의 예/아니오 질문이었다 — 2026-09-30).
_CHOICE_WORDS = re.compile(r"다음\s*중|어느|어떤|어떻게|무엇을|뭘로|중에서|골라|선택|which|choose|prefer", re.IGNORECASE)
#: 선택지가 아닌 줄 — 「**정직함:** …」 같은 소제목, 표시 기호, 우리 검사기의 알림.
_NOT_AN_OPTION = re.compile(r"[:：]$|^[✅❌⚠✔✖☑]|시키셨는데")


def _option_parts(text: str) -> tuple[str, str]:
    """「**웹 페이지** (HTML/JS, 브라우저에서 바로)」 → (웹 페이지, HTML/JS, 브라우저에서 바로)."""
    body = text.strip()
    bold = re.match(r"\*\*(.+?)\*\*\s*[:：\-—–]?\s*(.*)$", body)
    if bold:
        label, rest = bold.group(1), bold.group(2)
    else:
        # 콜론은 **뒤에 빈칸이 올 때만** 가른다 — `C:\…` 경로 속 콜론에서 잘라 「`C」만 남았다(운영 답 653024db).
        split = re.match(r"(.+?)\s*(?:[:：](?=\s)|\s[-—–]\s|\()\s*(.*)$", body)
        label, rest = (split.group(1), split.group(2)) if split else (body, "")
    rest = rest.strip()
    # 「**웹 페이지 형태** (HTML/JavaScript): 브라우저에서 바로…」 — 괄호 뒤에 설명이 더 오면 괄호만 벗기면
    # 「HTML/JavaScript): 브라우저…」가 카드에 그대로 찍혔다(2026-09-30 촬영 판). 괄호 안과 뒤를 이어 붙인다.
    paren = re.match(r"\(([^()]*)\)\s*[:：\-—–]?\s*(.*)$", rest)
    if paren:
        inner, after = paren.group(1).strip(), paren.group(2).strip()
        rest = f"{inner} · {after}" if inner and after else (inner or after)
    rest = rest.strip("()").strip()
    return label.strip().strip("*`[]").strip(), rest


def question_from_text(text: str) -> dict[str, Any] | None:
    """모델이 **글로** 한 선택지 질문을 질문 카드 인자로 (2026-09-30). 질문이 아니면 None.

    ★ 촬영 판(Gemma 4): 「어떤 방식으로 만들까요? 1. 웹 페이지 2. 파이썬 명령줄 … 골라주세요」를 도구 없이 글로 세 번 물었고,
      코드 게이트는 그걸 「코드 없이 끝내려는 답」으로 되받다가 실패로 닫았다. 도구를 부를 줄 아는 모델만 카드가 떴다.
      안내문으로는 못 고친다(사고 R) — 글로 된 질문을 코드가 알아보고 카드로 띄운다.

    헛발동이 제일 나쁘다(조사 결과 목록 끝의 「더 필요하시면 말씀해 주세요」를 질문으로 보면 판이 멈춘다). 그래서 좁게:
    선택지 2~4개가 한 덩어리 · 이름이 짧다 · **목록 바로 앞뒤 두 줄 안에** 물음표나 「골라 주세요」 · 그 뒤로 긴 글이 없다.
    """
    visible = _THOUGHT.sub("", str(text or ""))
    # 여는 태그 없이 닫는 태그만 온 생각(Gemma) — 그 앞은 전부 생각이다. 안 떼면 질문이 「</thought>어떤 방식으로…」가 됐다.
    closing = list(_STRAY_THOUGHT_END.finditer(visible))
    if closing:
        visible = visible[closing[-1].end():]
    lines = [line.rstrip() for line in visible.split("\n")]
    blocks: list[tuple[int, int]] = []
    start = -1
    for index, line in enumerate([*lines, ""]):
        if _OPTION_LINE.match(line):
            start = index if start < 0 else start
        elif line.strip() and start >= 0 and not _OPTION_LINE.match(line):
            blocks.append((start, index))
            start = -1
        elif not line.strip() and start >= 0:
            blocks.append((start, index))
            start = -1
    if not blocks:
        return None
    first, end = blocks[-1]  # 마지막 목록만 — 질문은 답의 끝에 온다
    options = []
    for line in lines[first:end]:
        match = _OPTION_LINE.match(line)
        if not match:
            continue
        label, description = _option_parts(match.group(1))
        options.append({"label": label[:80], "description": description[:200]})
    labels = [option["label"] for option in options]
    if not (MIN_OPTIONS <= len(options) <= MAX_OPTIONS) or any(not label or len(label) > 40 for label in labels):
        return None
    if any(_NOT_AN_OPTION.search(label) for label in labels):
        return None
    near = [line.strip() for line in lines[max(0, first - 2):first] + lines[end:end + 3] if line.strip()]
    cue = next((line for line in near if _QUESTION_END.search(line) and _CHOICE_WORDS.search(line)), "")
    if not cue:
        return None
    after = [line for line in lines[end:] if line.strip()]
    if len(after) > 2 or sum(len(line) for line in after) > 160:
        return None
    before = [line.strip() for line in lines[:first] if line.strip()]
    question = next((line for line in reversed(before) if re.search(r"[?？]\s*$", line)), "") or cue
    return {"question": question.strip("*# ").strip()[:200], "options": options, "recommended": -1}


class AskUserTool:
    """`ask_user` 하나짜리 도구 묶음 — 게이트웨이 등록 · 에이전트 카탈로그에 같이 넣는다."""

    def __init__(self) -> None:
        self._definitions = [
            {
                "type": "function",
                # 이름은 글자로 적는다 — 도구 목록 시험(test_tool_labels)이 이 모양으로 선언을 찾는다.
                "function": {"name": "ask_user", "description": _DESCRIPTION, "parameters": _PARAMETERS},
            }
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {ASK_USER_TOOL}

    @staticmethod
    def check(arguments: dict[str, Any]) -> None:
        """카드를 만들기 **전에** 거른다 — 물을 수 없는 질문으로 판을 멈추지 않는다."""
        if not str(arguments.get("question") or "").strip():
            raise ValueError("question_required — 사용자에게 할 질문을 한 문장으로 적어라.")
        if len(normalize_options(arguments.get("options"))) < MIN_OPTIONS:
            raise ValueError(
                f"options_required — 선택지를 {MIN_OPTIONS}~{MAX_OPTIONS}개 달아라. "
                "선택지로 물을 수 없는 것이면 묻지 말고 가장 그럴듯한 쪽으로 진행한 뒤 답에 가정을 밝혀라."
            )

    @staticmethod
    def answer(arguments: dict[str, Any]) -> dict[str, Any]:
        """재개 때 불린다 — 게이트웨이가 승인 기록의 답을 `__answer` 로 넣어 준다."""
        answer = str(arguments.get("__answer") or "").strip()
        options = normalize_options(arguments.get("options"))
        if not answer:
            # 고르지 않고 「알아서 진행」(또는 HUD 의 승인 버튼)을 누른 것 — 맡긴다는 뜻이다.
            # 답을 지어내 적지 않는다: 누가 골랐는지 모델에게 그대로 말하고, 가정을 밝히게 한다.
            return {
                "ok": True,
                "question": str(arguments.get("question") or ""),
                "answer": "",
                "delegated": True,
                "instruction": (
                    "사용자가 고르지 않고 알아서 진행하라고 했다. 네가 추천한 선택지로 진행하고, "
                    "최종 답에 「이렇게 가정하고 진행했다」를 한 줄로 밝혀라. 다시 묻지 마라."
                ),
            }
        # 카드는 고친 글(`describe`)을 보여 줬다 — 사람이 고른 말도 그 글이다. 원문과 고친 글 어느 쪽과 같아도 그 선택지다.
        chosen = next((option for option in options if answer in {option["label"], mend(str(option["label"]))[0]}), None)
        return {
            "ok": True,
            "question": str(arguments.get("question") or ""),
            "answer": answer,
            # 선택지 밖의 말이면 사람이 직접 적은 것이다 — 모델이 그 뜻을 그대로 따라야 한다.
            "free_text": chosen is None,
            "instruction": "사용자가 고른 답이다. 다시 묻지 말고 이 답대로 이어서 진행하라.",
        }

    def register(self, gateway: ToolGateway) -> None:
        definition = self._definitions[0]["function"]

        def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            return self.answer(arguments)

        gateway.register(
            ToolSpec(
                name=ASK_USER_TOOL,
                description=str(definition["description"]),
                parameters=dict(definition["parameters"]),
                # 사람이 답해야 지나간다. 승인 틀이 멈춤·재개·만료를 이미 다 가지고 있어서 그것을 쓴다.
                risk_level=RiskLevel.L2,
                handler=handler,
                enabled=True,
            )
        )
        gateway.approval_describers[ASK_USER_TOOL] = self.describe
        gateway.pre_approval_checks[ASK_USER_TOOL] = self.check

    @staticmethod
    def describe(arguments: dict[str, Any]) -> dict[str, Any]:
        """카드가 그릴 질문 — 정리된 선택지와 추천 번호. 인자는 건드리지 않는다(재생 때 그대로 비교한다)."""
        # ★ 끼어든 한자를 고친다 (2026-10-04 라이브 351858ba — 선택지가 「폴더를保存합니다 · 정리对象에서 제외」였다).
        #   답과 중계에는 이 관문이 있었는데 **사람이 눌러야 하는 카드**에는 없었다.
        options = [
            {**option, **{key: mend(str(option[key]))[0] for key in ("label", "description") if option.get(key)}}
            for option in normalize_options(arguments.get("options"))
        ]
        try:
            recommended = int(arguments.get("recommended"))
        except (TypeError, ValueError):
            recommended = -1
        return {
            "question": mend(str(arguments.get("question") or "").strip())[0],
            "options": options,
            "recommended": recommended if 0 <= recommended < len(options) else -1,
        }
