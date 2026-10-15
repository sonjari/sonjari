"""그림자 기록 — 사람이 한 요청에서 「무엇을 시켰나」 일곱 칸을 낱말 규칙과 모델로 나란히 읽는다.

판의 동작은 바꾸지 않는다. 판이 끝난 뒤에 결과를 읽어서 기록만 붙인다.
bench/intent_reading_1009/intent_compare.py 의 FIELDS · SYSTEM · by_regex 를
이 패키지로 옮겨 온 것이다(그쪽 sys.path.insert · E: 경로만 옮기지 않았다).
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from . import plan as P

FIELDS: tuple[str, ...] = ("count", "open", "file", "scope", "act", "code", "leans")

SYSTEM = """너는 사용자의 요청 한 문장을 읽고, 그 사람이 **무엇을 시켰는지**를 정해진 칸에 적는 분류기다. 일을 하지 말고 칸만 채워라. JSON 하나만 내라.

칸:
- count: 사용자가 **찾아 오거나 처리하라고 한 대상의 개수**(정수). 그런 개수가 없으면 0.
  조건을 설명하는 숫자(「리뷰 0개인」·「10만원 이하」·「3개월 안에」·「두 개 이상 작업을 걸면」), 사람 수(「2명이서 볼 거라」), 답의 길이(「5문장으로」), 이미 있는 것을 가리키는 숫자(「위 세 가지」)는 개수가 아니다.
- open: 대상 하나하나의 상세 페이지·본문을 여는 일에 대해 사용자가 **직접 한 말**. 열지 말라·열 필요 없다고 했으면 "no", 열어서 읽으라고 했으면 "yes", 아무 말도 없으면 "-".
- file: 문서·엑셀·워드·한글 같은 **산출물 파일을 새로 만들라**고 했으면 true. 답 안에 표나 목록으로 정리하라는 것, 채팅으로 답하라는 것, 코드 파일을 만드는 것은 false.
- scope: 파일을 쓰거나 고치는 것을 금지했는가. 금지가 없으면 "none". **특정 대상만** 건드리지 말라고 했고 다른 것은 고치거나 만들어도 되면 "target". 이 판 전체에서 아무것도 쓰지 말라(조사만·읽기 전용)이면 "all".
  사이트에 글을 올리지 말라는 말, 문서에 표를 넣지 말라는 말은 파일 쓰기 금지가 아니다.
- act: 바깥 서비스에 **실제로 반영하는 행위**를 시켰는가. 메일 보내기 "mail", 캘린더 일정 만들기·고치기·지우기 "calendar", 글을 임시저장만 "draft", 글 발행 "post", 그 밖의 반영(스크랩·신청·등록 등) "other", 없으면 "none".
  「답장은 내가 보낼게」처럼 사용자가 자기가 하겠다고 한 것, 다른 문장에서 딴 이야기로 나온 동사는 시킨 것이 아니다.
- code: **코드를 짜거나 고치라**고 했으면 true. 코드·책·저장소에 **관해** 찾아 달라·설명해 달라는 것은 false.
- leans: 이 말이 **그 자체로는 할 일이 없고 바로 앞 요청에 기대는 지시**인가(「응 그렇게 해」·「이어서 해줘」·「나머지도」). 감탄·칭찬·소감은 false. 할 일이 문장 안에 다 있으면 false."""

_OPEN_VALUES = {"no", "yes", "-"}
_SCOPE_VALUES = {"none", "target", "all"}
_ACT_VALUES = {"none", "mail", "calendar", "draft", "post", "other"}


def read_by_rules(prompt: str) -> dict[str, Any]:
    """낱말 규칙(plan.py)으로 일곱 칸을 읽는다. bench 의 by_regex 와 같은 값이다."""
    from .agent import named_sources  # agent.py 는 크고 무겁다 — 늦게 불러온다.

    compact = " ".join(prompt.split())
    named = bool(named_sources(compact))
    # 실제 판이 하는 대로: 길 정하기가 「가서 봐야 한다」고 정한 판(must_observe)과 아닌 판 둘 다 뽑아,
    # 요구가 더 많이 서는 쪽을 본다.
    plain = P.extract(prompt, has_named_source=named)
    observed = P.extract(prompt, has_named_source=named, must_observe=True)
    reqs = observed if len(observed) >= len(plain) else plain
    counts = [int(r.target) for r in reqs if r.kind in ("count", "count_action")]
    labels = " ".join(str(r.label) for r in reqs if r.kind in ("action", "count_action"))
    act = ("mail" if "메일" in labels else "calendar" if "일정" in labels else "draft" if "임시저장" in labels
           else "post" if re.search(r"발행|올리|게시", labels) else "other" if labels else "none")
    scope = {"": "none", "clause": "target", "job": "all"}[P.write_prohibition_scope(prompt)]
    code = bool(P.wants_code(prompt))
    return {
        "count": max(counts) if counts else 0,
        "open": "no" if P.says_list_only(prompt) else "yes" if P._wants_detail(compact) else "-",
        # 코드 판의 「산출물」(고친 코드)은 문서 파일이 아니다 — 정답표의 뜻(문서·엑셀 파일)에 맞춘다.
        "file": any(r.kind == "artifact" for r in reqs) and not code,
        "scope": scope,
        "act": act,
        "code": code,
        # 하네스는 이어짓기 후보라도 **그 문장에서 요구가 하나도 안 뽑힐 때만** 앞 말을 붙인다(`planning_prompt`).
        "leans": bool(P.is_continuation(prompt)) and not plain,
    }


def read_by_model(prompt: str, ask: Callable[[str, str], str]) -> dict[str, Any] | None:
    """모델에게 일곱 칸을 읽힌다. 읽히지 않으면 None — 예외를 밖으로 내보내지 않는다."""
    try:
        reply = ask(SYSTEM, prompt)
    except Exception:  # noqa: BLE001 — 모델 실패·느림은 읽기 없음이지, 밖의 오류가 아니다
        return None
    content = str(reply or "").strip()
    if not content:
        return None
    # 답 주변에 글이 있으면 ```json …``` 블록부터, 없으면 원문으로 본다.
    block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    text = block.group(1) if block else content
    try:
        data = json.loads(text)
    except ValueError:
        # 블록 밖의 맨 큰 중괄호 짝만 빼 본다.
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(content[start : end + 1])
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    got: dict[str, Any] = {}
    # count
    if not isinstance(data.get("count"), int) or isinstance(data.get("count"), bool) or data.get("count") < 0:
        return None
    got["count"] = data["count"]
    # open / scope / act — 정해진 값
    if data.get("open") not in _OPEN_VALUES:
        return None
    if data.get("scope") not in _SCOPE_VALUES:
        return None
    if data.get("act") not in _ACT_VALUES:
        return None
    got["open"] = data["open"]
    got["scope"] = data["scope"]
    got["act"] = data["act"]
    # file / code / leans — 참거짓(여기서 bool 은 int 가 아니다)
    if not isinstance(data.get("file"), bool):
        return None
    if not isinstance(data.get("code"), bool):
        return None
    if not isinstance(data.get("leans"), bool):
        return None
    got["file"] = data["file"]
    got["code"] = data["code"]
    got["leans"] = data["leans"]
    return got


def differing(rules: dict[str, Any], model: dict[str, Any] | None) -> list[str]:
    """두 읽기가 어긋난 칸을 칸 순서대로. 모델이 읽히지 않으면 빈 목록."""
    if model is None:
        return []
    out: list[str] = []
    for field in FIELDS:
        a, b = rules.get(field), model.get(field)
        # 하네스는 1 이하를 개수 요구로 치지 않는다 — 0 과 1 은 같은 읽기다.
        if field == "count" and (a or 0) <= 1 and (b or 0) <= 1:
            continue
        if a != b:
            out.append(field)
    return out


def record(prompt: str, ask: Callable[[str, str], str]) -> dict[str, Any]:
    """한 판의 기록 — 낱말 규칙 읽기 · 모델 읽기 · 어긋난 칸 · 걸린 시간 · 이유."""
    started = time.time()
    rules = read_by_rules(prompt)
    model = read_by_model(prompt, ask)
    return {
        "rules": rules,
        "model": model,
        "differs": differing(rules, model),
        "sec": round(time.time() - started, 3),
        "error": "" if model is not None else "모델이 읽히지 않았다",
    }


def attach(
    result: dict[str, Any] | None,
    prompt: str,
    *,
    enabled: bool,
    origin: str,
    ask: Callable[[str, str], str],
) -> None:
    """판의 결과 dict 에 그림자 기록을 붙인다. 판을 깨지 않는다 — 안쪽의 모든 실패를 삼킨다."""
    try:
        if not enabled:
            return
        if not str(prompt or "").strip():
            return
        # 맡긴 일의 글은 AI 가 쓴 것이다 — 사람의 요청을 읽는 법을 보려는 기록에 섞지 않는다.
        #   빼는 것은 그것 하나다 — 창 · 음성처럼 사람이 한 말은 어디서 왔든 적는다(줄에서 사람 것을 가르는 `jobs._delegated_payload` 와 같은 기준).
        if str(origin or "").strip() == "mcp":
            return
        if not isinstance(result, dict):
            return
        result["intent_shadow"] = record(prompt, ask)
    except Exception:  # noqa: BLE001, S110 — 기록은 판을 안 꺾는다. 안쪽 실패를 다 삼킨다
        pass
