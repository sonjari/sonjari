"""다른 AI 대화 사이트에 **대신 묻지 않는다** — 사용자가 그렇게 시켰을 때만 (2026-10-12).

같은 날 두 번 봤다(둘 다 작은 모델):

    아침 · 4B · 창 32K    가격 조사가 벅차자 AI 대화 사이트로 흘러 들어갔다
    저녁 · 4B 3비트        사람이 「그 회사의 홍보 전략부터 다시 잡아 보자」고 하자, 손자리가 그 회사의 AI 대화 사이트에
                          들어가 **입력칸에 그 질문을 쳤다.** 사람은 거기서 껐다 — 「미친 거 아니야?」

일을 시켰는데 남에게 물으러 간 것이다. 그 답은 읽은 자료가 아니라 다른 모델이 지은 글이고, 사용자의 말이 그 사람의
계정으로 밖에 나간다. 큰 모델은 하지 않는다(개발 PC 의 걸음 있는 판 2,886개 가운데 0) — 벅찬 모델이 고르는 길이다.

막는 것은 **글을 넣는 손**과 **질문을 실은 주소로 여는 것**뿐이다. 그 사이트를 열어 공개된 글을 읽는 것은 막지 않는다.
사용자가 「○○한테 물어봐」·「○○에 입력해 줘」라고 시켰으면 한다 — 서비스 이름이 요청에 있다는 것만으로는 아니다
(「GPT 의 홍보 전략」은 그 서비스에 **대해** 묻는 말이다).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

#: 사람이 글을 쳐 넣으면 모델이 답하는 대화 사이트.
AI_CHAT_HOSTS: tuple[str, ...] = (
    "chatgpt.com", "chat.openai.com", "gemini.google.com", "claude.ai", "copilot.microsoft.com", "perplexity.ai",
    "wrtn.ai", "clova-x.naver.com", "grok.com", "chat.deepseek.com", "poe.com",
)
#: 화면에 글을 넣거나 넣은 글을 보내는 손.
TYPING_TOOLS = frozenset({
    "browser_fill", "browser_fill_form", "browser_type_at", "browser_pick_suggestion", "browser_site_search", "browser_press",
})
#: 주소에 질문을 실어 여는 칸.
_QUESTION_PARAMS = ("q", "prompt", "query")
_NAMES = r"(?:챗\s*GPT|chat\s*gpt|GPT|지피티|제미나이|gemini|클로드|claude|코파일럿|copilot|퍼플렉시티|perplexity|뤼튼|wrtn|그록|grok|딥시크|deepseek)"
#: 「○○한테 물어봐」·「○○에 입력해 줘」 — 그 서비스에 **시키라**고 한 말. 이름만 있는 것은 아니다.
_ASKED_TO_USE_IT = re.compile(
    _NAMES + r"\s*(?:한테|에게|에다가?|에서|에)\s*[^\n.?!]{0,16}?(?:물어|질문|입력|넣어|쳐\s*줘|쳐\s*봐|시켜|말해)"
    r"|\bask\s+(?:chatgpt|gemini|claude|copilot|perplexity|grok)\b",
    re.I,
)


def is_ai_chat_site(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").casefold()
    return bool(host) and any(host == item or host.endswith("." + item) for item in AI_CHAT_HOSTS)


def asked_to_use_one(request: str) -> bool:
    """사용자가 그런 사이트에 묻거나 입력하라고 시켰는가."""
    return bool(_ASKED_TO_USE_IT.search(str(request or "")))


def asks_another_ai(name: str, arguments: Any, steps: list[dict[str, Any]], request: str) -> str:
    """이 호출이 시키지 않았는데 다른 AI 대화 사이트에 글을 넣으려는 것이면 그 사이트 주소(호스트). 아니면 빈 글."""
    if asked_to_use_one(request):
        return ""
    if name == "browser_open":
        url = str(arguments.get("url") or "") if isinstance(arguments, dict) else ""
        if is_ai_chat_site(url) and any(parse_qs(urlparse(url).query).get(key) for key in _QUESTION_PARAMS):
            return (urlparse(url).hostname or "").casefold()
        return ""
    if name not in TYPING_TOOLS:
        return ""
    here = ""
    for step in steps:
        if not step.get("ok") or not str(step.get("tool") or "").startswith("browser_"):
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        arguments_before = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        url = str(evidence.get("url") or (arguments_before.get("url") if step.get("tool") == "browser_open" else "") or "")
        if url:
            here = url
    return (urlparse(here).hostname or "").casefold() if is_ai_chat_site(here) else ""


def refusal_note(host: str) -> str:
    return (
        f"[도구가 보낸 안내] 다른 AI 대화 사이트({host})에 질문을 넣지 않는다 — 사용자가 「거기에 물어봐」라고 시켰을 때만 한다. "
        "이 요청은 그 서비스에 **대해** 묻거나 다른 일을 시킨 것이다. 거기에 묻지 말고 검색과 읽기로 직접 조사해라. "
        "앞 대화에서 이미 답한 내용이면 그것을 써라. 조사해도 모르면 모른다고 답해라."
    )
