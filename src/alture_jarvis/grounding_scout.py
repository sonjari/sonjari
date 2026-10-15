"""정찰기에게 **읽게 하고, 판정은 코드가 한다.**

근거 대조는 지금 문자열 포함으로 이름을 찾는다. 그것으로 대부분 맞지만, 같은 곳을
다르게 적은 경우에 헛경고가 난다.

    답에 적은 것      (주)미르
    본문에 있는 것    미르테크놀로지  ·  미 르  ·  MIR Technologies

이 자리에 작은 모델을 쓴다. 다만 **판정을 시키지 않는다.** 이 저장소가 비싸게 배운
규율이다 — 판단시키면 178초 걸려 오답이 나왔고, 자르고 읽게 하면 1.8초에 정확했다.

## 계약

    코드    「없다」고 나온 이름만 넘긴다
    정찰기  그 이름을 가리키는 **원문 구절**을 그대로 돌려준다 (지어내면 티가 난다)
    코드    그 구절이 본문에 **글자 그대로** 있는지 확인한다        ← fail-closed
            없으면 정찰기 답을 버린다. 경고는 그대로 선다.

그래서 정찰기는 **경고를 지울 수만 있고**, 지우려면 원문을 내야 한다. 없는 근거를
만들어 낼 길이 없다. 작업계약의 「원문 span 없는 소유권은 안 받는다」와 같은 불변식이다.

## 왜 주 모델이 아니라 정찰기인가

1. **독립적이다.** 다른 모델이고, 추론 과정이 아니라 증거만 본다. 산출물과 그것을
   검증한 근거가 같은 루프에서 나오면 그건 독립 확인이 아니다.
2. **공짜다.** 3060의 별도 Ollama(11435)라 3090의 주 모델을 축출하지 않는다.
   같은 슬롯에 두면 서로 쫓아내며 판이 통째로 느려진다 — 겪은 일이다.
3. **없어도 된다.** 안 떠 있으면 조용히 빈 결과를 준다. 그러면 경고가 그대로 서니
   안전한 쪽으로 넘어진다.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import httpx

from .config import JarvisConfig

#: 정찰기에게 허용한 대답 모양. 자유 문장을 받지 않는다.
CONFIRM_FORMAT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "found": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    # **원문 그대로**여야 한다. 요약·의역은 코드가 걸러 낸다.
                    "quote": {"type": "string"},
                },
                "required": ["name", "quote"],
            },
        }
    },
    "required": ["found"],
}

_PROMPT = (
    "아래 본문에서 다음 이름들이 실제로 언급되는지 확인해라.\n"
    "언급된 것만 골라, 그 이름이 나오는 **본문의 문장을 글자 그대로** 옮겨 적어라.\n"
    "요약하거나 고쳐 쓰지 마라. 없으면 넣지 마라. 확실하지 않으면 넣지 마라.\n\n"
    "찾을 이름: {names}\n\n"
    "본문:\n{body}"
)

#: 정찰기에게 넘길 본문 상한. 창을 넘기면 잘려서 뒤쪽 이름이 조용히 「없음」이 된다.
_BODY_CHARS = 24_000
#: 인용이 이보다 짧으면 우연히 맞을 수 있다. 「아」 한 글자가 본문에 있다고
#: 근거가 되지는 않는다.
_MIN_QUOTE = 8


#: 이름을 갈라놓는 껍데기. 여기까지만 지운다 — 더 손대면 원문 대조가 아니라 추측이다.
#: 결정론 대조(`_ENTITY_NOISE`)는 괄호·공백만 지운다. 그래서 「미르·테크놀로지」처럼
#: 가운뎃점이 낀 표기를 못 잡고 헛경고를 낸다. 이 층이 메우는 자리가 정확히 거기다.
_SEPARATORS = str.maketrans("", "", " \t\n·․.,‧・|/\\-–—_()[]{}（）㈜'\"")


def _normalize(text: str) -> str:
    """띄어쓰기와 구분자만 지운다. 뜻은 건드리지 않는다."""
    return str(text or "").translate(_SEPARATORS)


#: 한 번 죽은 것을 계속 두드리지 않는다.
#:
#: ★ 실측(2026-09-03). 정찰기가 안 떠 있으면 한 번 부를 때마다 **2.18초**를 버린다.
#:   근거 대조는 한 판에서 최대 네 번 불린다 — 죽어 있는 판마다 9초를 잃는 셈이다.
#:   그래서 첫 실패 뒤에는 잠시 건너뛴다. 살아나면 저절로 다시 쓴다.
_BREAKER_SEC = 120.0
_broken_until = 0.0


def _tripped() -> bool:
    return time.monotonic() < _broken_until


def _trip() -> None:
    global _broken_until
    _broken_until = time.monotonic() + _BREAKER_SEC


def reset_breaker() -> None:
    """검사와 수동 복구용. 라이브에서는 시간이 알아서 푼다."""
    global _broken_until
    _broken_until = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 정찰기 성적표
# ─────────────────────────────────────────────────────────────────────────────
#
# ★ 왜 필요한가 (2026-09-05)
#
# 정찰기를 넓히자는 이야기가 나왔는데, **지금 얼마나 일하는지 잴 방법이 없었다.**
# `agent_grounding_scout` 이벤트는 SSE 로만 흐르고 DB 에 안 남는다. 그래서 사후에
# 셀 수 있는 것은 「불려 갔을 자리」(근거 경고가 뜬 판 2%)뿐이고, 가서 무엇을
# 했는지 — 몇 개를 물었고, 몇 개를 지웠고, 몇 개를 **지어내서 버려졌는지** — 는
# 아무도 모른다.
#
# 재는 자 없이 늘리면 좋아졌는지 나빠졌는지 모른 채로 늘리는 것이 된다.
# 그래서 늘리기 **전에** 이걸 놓는다.
#
# 판마다 비운다(`drain_calls`). 판이 아닌 길(MCP·직접 호출)에서도 쌓이므로
# 상한을 둔다 — 안 비우는 길이 있으면 메모리가 조용히 자란다.

_CALLS_MAX = 200
_calls: list[dict[str, Any]] = []
_calls_lock = threading.Lock()


def record_call(
    purpose: str,
    *,
    asked: int = 0,
    accepted: int = 0,
    rejected: int = 0,
    took_ms: int = 0,
    outcome: str = "ok",
    detail: str = "",
) -> None:
    """정찰기를 부른 한 번을 남긴다.

    `outcome` 이 중요하다. 「안 불렀다」가 여러 종류이기 때문이다:

        disabled   이 PC 에서 꺼져 있다
        breaker    앞서 실패해서 잠시 쉬는 중이다
        no_input   물을 것이 없었다
        error      불렀는데 실패했다
        ok         불렀고 답을 받았다

    이걸 안 가르면 「정찰기가 0 번 일했다」가 고장인지 정상인지 구별이 안 된다.
    빈 값 하나가 두 사실을 뜻하면 조용히 고장난다 — 이 저장소가 배운 것이다.
    """
    row = {
        "purpose": purpose,
        "asked": int(asked),
        "accepted": int(accepted),
        # **정찰기가 답했는데 코드가 버린 것.** 이 숫자가 크면 정찰기가 지어내고
        # 있다는 뜻이고, 그건 모델이나 프롬프트를 바꿔야 할 신호다.
        "rejected": int(rejected),
        "took_ms": int(took_ms),
        "outcome": outcome,
        **({"detail": detail[:200]} if detail else {}),
    }
    with _calls_lock:
        _calls.append(row)
        if len(_calls) > _CALLS_MAX:
            del _calls[: len(_calls) - _CALLS_MAX]


def drain_calls() -> list[dict[str, Any]]:
    """쌓인 것을 꺼내고 비운다. 판이 끝날 때 부른다."""
    with _calls_lock:
        rows = list(_calls)
        _calls.clear()
    return rows


def summarize_calls(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """성적표 한 줄. 판 기록에 이 모양으로 들어간다."""
    if not rows:
        return {}
    return {
        "calls": len(rows),
        "ran": len([r for r in rows if r.get("outcome") == "ok"]),
        "asked": sum(int(r.get("asked") or 0) for r in rows),
        "accepted": sum(int(r.get("accepted") or 0) for r in rows),
        "rejected": sum(int(r.get("rejected") or 0) for r in rows),
        "took_ms": sum(int(r.get("took_ms") or 0) for r in rows),
        # ★ **왜 실패했는지도 싣는다** (2026-09-10).
        #
        #   `record_call` 은 `detail` 을 받아 두는데 이 성적표가 그걸 버렸다. 그래서
        #   판 기록에는 `{"error": 1, "breaker": 2}` 만 남고 **이유가 없었다.**
        #   실제로 그 한 줄 때문에 「정찰기가 왜 안 도나」를 라이브에서 재현해 가며
        #   찾아야 했다 — 이미 손에 쥐고 있던 답을 버린 것이다.
        #
        #   첫 실패 하나면 충분하다. 뒤따르는 것은 대개 차단기라 같은 말이다.
        **(
            {"first_error": next(
                (str(r.get("detail") or "") for r in rows
                 if r.get("outcome") == "error" and r.get("detail")), "")}
            if any(r.get("outcome") == "error" for r in rows) else {}
        ),
        # 무엇 때문에 안 돌았는지. 「0 번」의 뜻을 여기서 읽는다.
        "outcomes": {
            key: sum(1 for r in rows if r.get("outcome") == key)
            for key in sorted({str(r.get("outcome") or "") for r in rows})
        },
        "purposes": {
            key: sum(1 for r in rows if r.get("purpose") == key)
            for key in sorted({str(r.get("purpose") or "") for r in rows})
        },
    }


def confirm_names(
    names: list[str],
    body: str,
    *,
    config: JarvisConfig,
    client: Any = None,
) -> dict[str, str]:
    """「없다」고 나온 이름 중 **본문에 정말 있는 것**을 원문 인용과 함께 돌려준다.

    돌려주는 것은 코드가 **직접 확인한 것뿐**이다. 정찰기가 지어낸 인용은 여기서
    버려진다. 실패·미기동·시간초과는 전부 빈 결과다 — 그러면 경고가 그대로 선다.
    """
    if not names or not body:
        record_call("grounding", outcome="no_input")
        return {}
    if not getattr(config, "code_scout_enabled", False):
        record_call("grounding", asked=len(names), outcome="disabled")
        return {}
    if _tripped():
        record_call("grounding", asked=len(names), outcome="breaker")
        return {}
    started = time.monotonic()
    payload = {
        "model": config.code_scout_model,
        "messages": [
            {
                "role": "user",
                "content": _PROMPT.format(
                    names=", ".join(names[:12]), body=body[:_BODY_CHARS]
                ),
            }
        ],
        "stream": False,
        # ★ thinking 모델은 `think` 를 안 끄면 예산을 전부 사고에 쓰고 본문이 빈
        #   문자열로 온다. 이 저장소가 로컬 모델에서 여러 번 물린 함정이다.
        "think": False,
        "format": CONFIRM_FORMAT,
        "options": {"num_predict": 700, "temperature": 0},
    }
    try:
        owns = client is None
        http = client or httpx.Client(timeout=config.code_scout_timeout_sec)
        try:
            response = http.post(
                f"{config.code_scout_base_url.rstrip('/')}/api/chat", json=payload
            )
            response.raise_for_status()
            content = (response.json().get("message") or {}).get("content") or ""
        finally:
            if owns:
                http.close()
        parsed = json.loads(content)
    except Exception as exc:  # noqa: BLE001 — 검증자가 죽어도 판은 계속 간다
        _trip()
        record_call(
            "grounding",
            asked=len(names),
            outcome="error",
            took_ms=int((time.monotonic() - started) * 1000),
            detail=str(exc),
        )
        return {}

    flat = _normalize(body)
    confirmed: dict[str, str] = {}
    for item in (parsed.get("found") or [])[:12]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if name not in names or len(quote) < _MIN_QUOTE:
            continue
        # ★ 여기가 이 모듈의 전부다. **인용이 본문에 진짜 있어야 한다.**
        #   없으면 정찰기가 지어낸 것이고, 지어낸 근거로 경고를 지우지 않는다.
        if _normalize(quote) not in flat:
            continue
        # 이름 자체도 본문에 있어야 한다 — 인용만 맞고 이름은 딴 데서 온 경우를 막는다.
        if _normalize(name) not in _normalize(quote):
            continue
        confirmed[name] = quote[:200]
    # ★ **버린 개수를 같이 남긴다.** 정찰기가 답했는데 코드가 버린 것이 많으면
    #   지어내고 있다는 뜻이고, 그건 성적표에서만 보인다.
    answered = len([item for item in (parsed.get("found") or [])[:12] if isinstance(item, dict)])
    record_call(
        "grounding",
        asked=len(names),
        accepted=len(confirmed),
        rejected=max(0, answered - len(confirmed)),
        took_ms=int((time.monotonic() - started) * 1000),
    )
    return confirmed


# ─────────────────────────────────────────────────────────────────────────────
# 편집 닻 찾기 — 사다리 4칸
# ─────────────────────────────────────────────────────────────────────────────

#: ★ **받아쓰게 하지 않는다. 짚게만 한다.** (2026-09-05 라이브에서 배움)
#:
#:   처음엔 원문을 그대로 옮겨 적게 했다. 라이브 3 건이 **전부** 실패했다 —
#:   9B 모델은 들여쓰기·공백을 정규화해서 내놓고, 그러면 코드의 글자 대조에서
#:   통째로 버려진다(0/3, 그중 하나는 23 초를 쓰고 버려졌다).
#:
#:   줄 번호는 다르다. **짚는 것은 작은 모델도 잘한다.** 원문을 꺼내는 일은
#:   코드가 하면 되고, 그러면 받아쓰기 오류라는 실패 원인이 아예 사라진다.
#:   이 저장소의 규율과도 더 맞는다 — 정찰기는 읽고, 판정과 추출은 코드가 한다.
ANCHOR_FORMAT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
    },
    "required": ["start_line", "end_line"],
}

_ANCHOR_PROMPT = (
    "어떤 사람이 파일에서 아래 「찾는 글」을 고치려 했는데 글자가 정확히 맞지 않아 실패했다.\n"
    "아래 파일은 줄마다 번호가 붙어 있다. 그 사람이 가리킨 부분이 **몇 번 줄부터 몇 번 "
    "줄까지인지** 번호만 답해라.\n"
    "- 내용을 옮겨 적지 마라. 번호만 답하면 된다.\n"
    "- 「찾는 글」과 같은 범위를 덮어야 한다(줄 수가 비슷해야 한다).\n"
    "- 해당하는 곳이 없으면 start_line 과 end_line 을 둘 다 0 으로 답해라.\n\n"
    "찾는 글:\n{wanted}\n\n파일:\n{windows}"
)

#: 정찰기에게 보여 줄 후보 창의 수와 여유. **파일 전체를 절대 안 준다** —
#: 이 저장소가 정찰기에 건 규율이 「후보 top-K 만」이다(토큰도 시간도 그만큼만 쓴다).
_ANCHOR_WINDOWS = 3
_ANCHOR_WINDOW_PAD = 6


def find_anchor(
    text: str,
    wanted: str,
    *,
    config: JarvisConfig,
    client: Any = None,
) -> str:
    """모델이 어긋나게 적어 온 편집 닻을 **파일 원문에서** 찾아 준다.

    돌려주는 것은 `text` 안에 **글자 그대로 있고 딱 한 번 나오는** 조각뿐이다.
    아니면 빈 문자열 — 그러면 부르는 쪽은 예전처럼 실패한다.

    ## 왜 이 자리인가 (2026-09-05 실측)

        local_apply_edit   195 번 중 108 번 실패 (55%)
        old_text_not_found                     107 건
          결국 못 고친 것                        42 건 (39%)
          회복한 것의 추가 걸음   중앙 2 · 90% 5

    주 모델 한 턴이 중앙 10 초다(P4 실측). 즉 실패 하나가 **중앙 20 초**를 태우고,
    39% 는 그러고도 못 고친다. 정찰기 한 번은 웜 2 초다.

    ## 속도와 결과를 같이 얻는 이유

    이 층은 **거의 느려질 수 없다.** 최악이 「2 초 쓰고 예전 실패로 떨어짐」이고,
    맞히면 주 모델 왕복 두 번(≈20 초)을 통째로 없앤다. 판정을 시키지 않으므로
    틀린 답이 통과할 길도 없다 — 코드가 파일에서 글자 그대로 찾아보고 없으면 버린다.

    (콜드 로딩은 예외다. 모델이 안 올라와 있으면 첫 호출이 20 초를 넘을 수 있다.
     `keep_alive` 가 30 분이라 이어지는 판에서는 웜이다.)
    """
    if not text or not wanted:
        record_call("edit_anchor", outcome="no_input")
        return ""
    if not getattr(config, "code_scout_enabled", False):
        record_call("edit_anchor", outcome="disabled")
        return ""
    if _tripped():
        record_call("edit_anchor", outcome="breaker")
        return ""
    lines = text.split("\n")
    windows = _anchor_windows(lines, wanted)
    if not windows:
        record_call("edit_anchor", outcome="no_input", detail="후보 창 없음")
        return ""
    started = time.monotonic()
    payload = {
        "model": config.code_scout_model,
        "messages": [
            {
                "role": "user",
                "content": _ANCHOR_PROMPT.format(
                    wanted=wanted[:2000], windows="\n\n…\n\n".join(windows)
                ),
            }
        ],
        "stream": False,
        "think": False,
        "format": ANCHOR_FORMAT,
        # 번호 둘만 받으므로 생성이 짧다 — 받아쓰기보다 빠르고 틀릴 자리도 적다.
        "options": {"num_predict": 80, "temperature": 0},
    }
    try:
        owns = client is None
        http = client or httpx.Client(timeout=config.code_scout_timeout_sec)
        try:
            response = http.post(
                f"{config.code_scout_base_url.rstrip('/')}/api/chat", json=payload
            )
            response.raise_for_status()
            content = (response.json().get("message") or {}).get("content") or ""
        finally:
            if owns:
                http.close()
        parsed = json.loads(content) or {}
        start = int(parsed.get("start_line") or 0)
        end = int(parsed.get("end_line") or 0)
    except Exception as exc:  # noqa: BLE001 — 정찰기가 죽어도 편집은 예전처럼 실패한다
        _trip()
        record_call(
            "edit_anchor",
            asked=1,
            outcome="error",
            took_ms=int((time.monotonic() - started) * 1000),
            detail=str(exc),
        )
        return ""
    took = int((time.monotonic() - started) * 1000)
    span = _span_of(lines, start, end, wanted)
    # ★ 여기가 이 함수의 전부다. **파일에 글자 그대로 있고, 딱 한 번 나와야 한다.**
    #   둘 이상이면 어느 쪽인지 모르는 것이고, 모르는 채 고치는 것이 못 고치는
    #   것보다 나쁘다(사다리 아래 칸들과 같은 규칙).
    if span and text.count(span) == 1:
        record_call("edit_anchor", asked=1, accepted=1, took_ms=took)
        return span
    record_call(
        "edit_anchor",
        asked=1,
        rejected=1,
        took_ms=took,
        detail=(f"줄 {start}~{end} 을 못 씀" if (start or end) else "해당 없음"),
    )
    return ""


#: 짚은 자리가 **찾던 자리인지** 가르는 문턱. 낱말 포함률이다.
#:
#: ★ 라이브가 잡은 고장 (2026-09-05). 처음엔 「파일에 글자 그대로 있나」만 봤다.
#:   그랬더니 없는 함수(`gamma`)를 고치라고 했을 때 정찰기가 **엉뚱한 함수
#:   (`alpha`)를 짚었고, 그 조각은 파일에 진짜로 있으니 통과해서 alpha 가
#:   지워졌다.** 못 고치는 것보다 훨씬 나쁘다 — 조용히 딴 곳을 고친 것이다.
#:
#:   유사도(difflib)로는 못 가른다. 재 봤더니 **오짚음(alpha↔beta) 0.905 가
#:   정상 사례(줄 일부만) 0.843 보다 높았다.** 문턱을 어디 둬도 갈리지 않는다.
#:
#:   낱말 포함률은 갈린다. 이름이 다르면 그 낱말이 통째로 빠지기 때문이다:
#:
#:       들여쓰기만 다름   1.000      gamma 를 원했는데 alpha   0.667
#:       줄 일부만        1.000      alpha 를 원했는데 beta    0.750
#:       오타 하나        0.875      완전 딴 곳               0.250
#:
#:   정상 최저 0.875 와 오짚음 최고 0.750 사이에 둔다.
_ANCHOR_TOKEN_COVERAGE = 0.85

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|[0-9]+")


def _token_coverage(wanted: str, span: str) -> float:
    """`wanted` 의 낱말 중 몇 할이 `span` 에 있나. 없으면 0."""
    tokens = _TOKEN.findall(wanted)
    if not tokens:
        return 0.0
    present = set(_TOKEN.findall(span))
    return sum(1 for token in tokens if token in present) / len(tokens)


def _span_of(lines: list[str], start: int, end: int, wanted: str) -> str:
    """정찰기가 짚은 줄 범위를 **파일 원문 그대로** 꺼낸다. 못 쓰면 빈 문자열.

    번호는 1부터다. 범위가 뒤집혔거나 밖으로 나가거나, 찾는 글보다 터무니없이
    넓으면 안 쓴다 — 넓게 잡아 바꾸면 편집이 아니라 삭제가 된다.

    ★ 그리고 **찾던 자리인지**까지 본다. 「파일에 있나」만 보면 정찰기가 아무
    함수나 짚어도 통과한다 — 라이브에서 실제로 그렇게 엉뚱한 함수가 지워졌다.
    """
    if start <= 0 or end <= 0 or end < start or start > len(lines):
        return ""
    end = min(end, len(lines))
    wanted_lines = max(1, len([line for line in wanted.split("\n") if line.strip()]))
    if (end - start + 1) > wanted_lines * 3 + 4:
        return ""
    span = "\n".join(lines[start - 1 : end])
    if not span.strip():
        return ""
    if _token_coverage(wanted, span) < _ANCHOR_TOKEN_COVERAGE:
        return ""
    return span


def _anchor_windows(lines: list[str], wanted: str) -> list[str]:
    """닻이 있을 법한 **후보 조각 몇 개**, 줄 번호를 붙여서.

    파일 전체를 주지 않으려고 있다. 정찰기가 답할 것이 이 번호다.
    """
    import difflib

    wanted_lines = [line.strip() for line in wanted.split("\n") if line.strip()]
    if not wanted_lines or not lines:
        return []
    span = len(wanted_lines)
    target = "\n".join(wanted_lines)
    stripped = [line.strip() for line in lines]
    scored: list[tuple[float, int]] = []
    for index in range(max(1, len(lines) - span + 1)):
        window = "\n".join(part for part in stripped[index : index + span] if part)
        if not window:
            continue
        scored.append((difflib.SequenceMatcher(None, target, window).ratio(), index))
    scored.sort(reverse=True)
    windows: list[str] = []
    taken: list[int] = []
    for _ratio, index in scored:
        # 이미 고른 창과 겹치면 건너뛴다 — 같은 자리를 세 번 보여 줄 이유가 없다.
        if any(abs(index - other) < span for other in taken):
            continue
        taken.append(index)
        begin = max(0, index - _ANCHOR_WINDOW_PAD)
        stop = min(len(lines), index + span + _ANCHOR_WINDOW_PAD)
        windows.append("\n".join(f"{n + 1}: {lines[n]}" for n in range(begin, stop)))
        if len(windows) >= _ANCHOR_WINDOWS:
            break
    return windows
