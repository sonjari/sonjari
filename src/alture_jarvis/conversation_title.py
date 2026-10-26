"""대화 제목 짓기 (2026-10-26 · 대표: 「목록 제목이 첫 말 앞부분이라 한눈에 뭔지 모른다」).

첫 답이 끝나면 **내 PC 모델**에게 짧은 제목을 받는다 — 한국어 화면이면 15자 안팎, 영어 화면이면 영어 몇 낱말.
여기는 글만 다룬다(부를 말 · 받은 답 고르기). 부르는 자리 · 때(손자리가 쉴 때만)는 `runtime._title_soon` 이다.

지키는 것:
- 생각 끔(`think: false`) · 짧은 부르기 — `ollama.background_chat`(JSON 답 · 사람 일이 오면 끊김)으로만 부른다.
- 못 지으면(빈 답 · 깨진 JSON · 너무 긴 답) 아무것도 안 단다 — 목록은 지금처럼 첫 말 앞부분이다.
- 사람이 바꾼 제목은 덮지 않는다(`MemoryStore.set_title` 이 막는다).
"""
from __future__ import annotations

import json
import re
from typing import Any

#: 모델에게 보여 줄 첫 말 · 첫 답의 앞부분(글자). 제목은 앞부분으로 충분하고, 짧을수록 빨리 끝난다.
USER_CHARS = 1_200
ANSWER_CHARS = 1_200
#: 받은 제목의 상한 — 넘으면 제목이 아니라 문장이다(버린다).
MAX_KO_CHARS = 24
MAX_EN_CHARS = 48
#: 답 길이 상한(토큰) — JSON 한 줄이면 된다.
NUM_PREDICT = 48

_SYSTEM = {
    "ko": (
        "너는 대화 목록에 붙일 제목을 짓는다. 사용자의 첫 요청과 첫 답을 보고, 무슨 일인지 한눈에 알 수 있는 "
        "한국어 제목 하나를 15자 안팎(최대 20자)으로 짓는다. 명사로 끝내고, 따옴표 · 마침표 · 이모지 · "
        "「~해 줘」 같은 요청 말투는 쓰지 않는다. 파일 이름 · 고유명사는 그대로 둔다. "
        '반드시 JSON 한 줄로만 답한다: {"title": "제목"}'
    ),
    "en": (
        "You name a conversation for a chat list. From the user's first request and the first answer, write one short "
        "English title (2 to 6 words) that says what the conversation is about. No quotes, no final period, no emoji, "
        "no request phrasing like 'please'. Keep file names and proper nouns as they are. "
        'Reply with one line of JSON only: {"title": "Title"}'
    ),
}


def lang_of(value: str) -> str:
    return "en" if str(value or "").lower().startswith("en") else "ko"


def messages(user_text: str, answer_text: str, lang: str) -> tuple[str, str]:
    """(지시문, 사용자 글). 첫 말 · 첫 답은 앞부분만."""
    lang = lang_of(lang)
    user = " ".join(str(user_text or "").split())[:USER_CHARS]
    answer = " ".join(str(answer_text or "").split())[:ANSWER_CHARS]
    if lang == "en":
        body = f"First request:\n{user}\n\nFirst answer:\n{answer}"
    else:
        body = f"첫 요청:\n{user}\n\n첫 답:\n{answer}"
    return _SYSTEM[lang], body


_STRIP = re.compile(r"^[\s\"'「『《〈“‘`*#\-–—:]+|[\s\"'」』》〉”’`*.。!！?？:]+$")


def parse(raw: str | None, lang: str) -> str:
    """모델 답에서 제목. 쓸 수 없으면 빈 글."""
    text = str(raw or "").strip()
    if not text:
        return ""
    title: Any = ""
    try:
        value = json.loads(text)
        title = value.get("title") if isinstance(value, dict) else ""
    except ValueError:
        match = re.search(r'"title"\s*:\s*"([^"]{1,120})"', text)
        title = match.group(1) if match else ""
    title = " ".join(str(title or "").split())
    title = _STRIP.sub("", title).strip()
    if not title:
        return ""
    limit = MAX_EN_CHARS if lang_of(lang) == "en" else MAX_KO_CHARS
    if len(title) > limit or "\n" in title:
        return ""
    return title
