"""일하면서 **말한다** — 도구를 부르기 전에 무엇을 왜 하는지 한 줄 (2026-09-21 사장님 요청).

> 요즘 CLI 들은 사용자한테 얘기하면서 자기가 다음 작업을 하고 이런다이가 …
> 사용자 입장에서도 문제가 되는 거는 바로잡을 수 있고

## 지금까지

모델이 도구를 부르면 `message["content"]` 를 **아예 안 봤다.** 그래서 답은 판이
끝나야 한 번에 나왔다. 사람은 3분 동안 걸음 목록만 보고 기다렸고, 엉뚱한 길로
가고 있어도 끝나기 전엔 못 막았다.

## 실측 (2026-09-21, Qwen 3.6 35B-A3B)

|                | 말함 | 도구 부름 | 시간 |
|----------------|------|-----------|------|
| 안내 없음      | 0/3  | 3/3       | 0.8초 |
| 말하라고 시킴  | 3/3  | 3/3       | 0.9초 |

★ 이 저장소에는 전례가 있다 — 도구 설명에 「먼저 알리고」를 넣었다가 **호출이
  통째로 막힌 적**이 있다(젬마). Qwen 3.6 에서는 재현되지 않았다. 그래서 이 기능은
  **모델별로 껐다 켤 수 있어야 한다** — 낱말 하나가 손을 묶는 것을 이미 봤다.

## 말은 증거가 아니다 ⚠

같은 실측에서 이런 말이 나왔다:

    "'weekly_fee' 같은 유사한 이름의 함수를 찾아봤습니다."   ← 찾아본 적 없다

이 저장소가 아는 「한 척」이다. 그래서 나레이션은:

  * **증거 원장에 안 들어간다** — 무엇을 봤는지는 도구 결과가 말한다
  * **답이 되지 않는다** — 최종 답은 도구를 다 쓴 뒤 따로 만든다
  * 화면에 **「하는 말」로만** 표시한다 — 결과와 다른 칸에

## 그라운딩 효과는 아직 주장하지 않는다

사장님 가설(말하면서 한 번 더 검증된다)은 그럴듯하지만, 빈 결과를 알아챈 비율이
1/3 → 2/3 였다. **n=3 은 잡음이다.** 효과를 주장하려면 판 단위로 재야 한다.
지금 확실한 값은 **사람이 보면서 바로잡을 수 있다**는 것이다.
"""

from __future__ import annotations

import re

from .stray_han import mend as mend_stray_han
from typing import Any

#: 모델에게 주는 한 문장. **도구를 막지 않는 모양**이 중요하다 — 「말만 하고 끝내지 마라」를
#: 반드시 같이 적는다(안 적으면 말로 때우고 도구를 안 부르는 판이 생긴다).
NARRATION_INSTRUCTION = (
    "도구를 부르기 전에, 직전 결과에서 무엇을 봤는지와 지금 무엇을 왜 하는지를 "
    "사용자에게 **한 문장**으로 먼저 말해라. 그 문장을 content 에 담고, **같은 응답에서 "
    "tool_calls 도 반드시 함께** 낸다. 말만 하고 도구를 안 부르면 안 된다. "
    "아직 안 한 일을 했다고 적지 마라 — 본 것만 말해라."
)

#: 같은 지시의 영어판. **영어로 시킨 판**에 쓴다 (2026-10-05 AWS 영어 윈도우 첫 실행).
#: 한국어 지시만 주면 9B 는 그 한 문장을 한국어로 냈다 — 영어 화면·영어 질문인데 중계만 한국어였다.
NARRATION_INSTRUCTION_EN = (
    "Before calling a tool, first tell the user in **one English sentence** what you saw in the previous result "
    "and what you are doing now and why. Put that sentence in content, and **always send tool_calls in the same "
    "response**. Never speak without calling a tool. Do not claim work you have not done — say only what you saw."
)

#: 한 번에 내보낼 말의 최대 길이. 길면 그건 답이지 나레이션이 아니다.
MAX_CHARS = 400

#: 모델이 흘리는 속생각·표식 조각. 화면에 그대로 나가면 사람이 놀란다.
_JUNK = re.compile(
    r"</?\s*(?:thought|thinking|think|reasoning|tool_call|function_call)\b[^>\n]*>?",
    re.IGNORECASE,
)

#: Gemma 4 가 생각 채널을 닫는 표식까지 말에 흘린 것(「thought\n<channel|>」). 답에서는 `runtime.strip_leaked_thinking` 이
#: 걷는데 일하면서 하는 말에는 없어서, 진행 줄에 「thought <channel|>」가 두 줄 찍혔다(2026-10-05 영어 촬영 판 9cae577f).
_LEAKED_CHANNEL = re.compile(r"\A\s*(?:<\|?channel\|?>\s*)?thought\b.*?<\|?channel\|?>\s*", re.S)
_CHANNEL_MARK = re.compile(r"<\|?channel\|?>")

#: 모델이 따라 말한 내부 지시(생각 예산 끊기 · 그 앞뒤의 구분선). 줄 단위로 뺀다.
_ECHOED_NUDGE = re.compile(
    r"(?m)^[ \t]*(?:더\s*생각하지\s*말고\s*지금\s*바로[^\n]{0,40}(?:최종\s*답|도구)[^\n]{0,20}"
    r"|\[(?:생각\s*시간이\s*다\s*됐다|같은\s*생각을\s*되풀이[^\]\n]{0,40})\]"
    r"|지금까지\s*네가\s*한\s*생각의\s*끝부분이다:?"
    r"|-{3,})[ \t]*$\n?"
)

#: **말로 때우는 문장.** 이런 말만 하고 아무것도 안 하면 진전이 아니다(「예고는 진척이 아니다」).
_EMPTY_PROMISE = re.compile(
    r"^\s*(?:네[.,!]?|알겠습니다[.,!]?|확인했습니다[.,!]?|잠시만요[.,!]?|"
    r"ok(?:ay)?[.,!]?|sure[.,!]?|understood[.,!]?)\s*$",
    re.IGNORECASE,
)


def clean(content: Any) -> str:
    """모델이 도구와 함께 낸 말을 화면에 낼 수 있는 한 줄로. 낼 것이 없으면 빈 문자열.

    ★ 자르되 **자른 티를 낸다.** 조용히 자르면 사람은 그게 전부인 줄 안다.
    """
    text = str(content or "")
    if "channel|>" in text:
        text = _CHANNEL_MARK.sub("", _LEAKED_CHANNEL.sub("", text, count=1))
    text = _JUNK.sub("", text).strip()
    # ★ 내부 지시를 **따라 말한 줄**을 뺀다 (2026-10-04 허깅페이스 판 화면). 생각 시간이 다 됐을 때 모델에게 주는
    #   「더 생각하지 말고 지금 바로 다음 도구를 부르거나 최종 답을 내라.」가 중계에 그대로 찍혔다 — 사람에게 한 말이 아니다.
    text = _ECHOED_NUDGE.sub("", text).strip()
    if not text or _EMPTY_PROMISE.match(text):
        return ""
    # ★ 끼어든 한자를 고친다 (2026-10-04 사다리 L2 화면 — 「원격 관測 시작」). 최종 답에는 마지막 관문이 있었는데
    #   일하면서 하는 말에는 없었다. 영어 화면에서도 똑같이 건다 — 규칙은 `stray_han` 한 곳.
    text, _touched = mend_stray_han(text)
    text = text.strip()
    if not text:
        return ""
    # 여러 줄로 와도 화면에서는 한 덩어리다. 빈 줄만 접는다.
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1].rstrip() + "…"
    return text


def enabled_for(config: Any, model: str) -> bool:
    """이 모델에서 말하게 할 것인가.

    ★ 모델별로 끌 수 있어야 하는 이유: 「먼저 알리고」 한 줄이 젬마의 도구 호출을
      통째로 막은 적이 있다. 새 모델을 붙일 때는 **재 보고** 켠다.
    """
    if not bool(getattr(config, "agent_narration_enabled", True)):
        return False
    name = str(model or "").strip().lower()
    blocked = getattr(config, "agent_narration_blocked_models", ()) or ()
    return not any(name.startswith(str(prefix).lower()) for prefix in blocked)
