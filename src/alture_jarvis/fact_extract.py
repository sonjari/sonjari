"""대화에서 **사실을 뽑는다** (2026-08-24, P2).

## 왜 두 단계인가

    ① 결정론 선별   이 대화에 뽑을 게 있을 법한가 — 낱말과 길이로만
    ② 로컬 젬마     있다면 무엇인지 — JSON 으로

①이 없으면 「고마워」·「어어」·「응」에도 모델을 태운다. 대화 1,758건에서
그런 짧은 말이 상당수라, 그대로 두면 매 턴 추가 호출이 붙는다.

②를 결정론으로 못 하는 이유는 반대다 — "우리 사무실 여수로 옮겼어"에서
`(product, 사무실 위치, 여수)` 를 뽑는 것은 규칙으로 안 된다. 규칙으로 하려다
템플릿이 된 것이 이 저장소의 사고 I 다.

## ★ 지어낸 사실을 막는 장치

`memory.add_fact` 가 `source_message_id` 를 필수로 받는다. 여기서는 **그 메시지에
실제로 들어 있는지**까지 본다 — 모델이 대화에 없는 말을 지어내면 거기서 걸린다.

이 저장소는 「AI가 생성했다」 라벨이 실은 정적 템플릿이었던 것을 **두 번** 겪었고
(사고 I, 그리고 과학 4과목 재발), 그때 배운 것은 provenance 가 **주장이 아니라
검증 대상**이라는 것이다. 라벨을 믿지 않고 대조한다.

## 젬마 함정

`think=False` 를 반드시 넘긴다. 젬마는 thinking 모델이라 안 넣으면 `num_predict`
예산이 내부 추론에 다 쓰이고 `message.content` 가 **빈 문자열**로 온다. 이
저장소는 그걸로 한 번 헤맸다. (`OllamaClient.chat` 의 기본값이 이미 False 지만,
여기서는 뜻을 드러내려고 명시한다.)
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

#: 이보다 짧은 말에는 뽑을 사실이 없다. 「어어」·「응」·「고마워」.
MIN_USER_CHARS = 12

#: 사실이 있을 법한 신호. **하나라도** 있으면 모델을 태운다.
#:
#: 넉넉하게 잡는다 — 여기서 놓치면 그 사실은 영영 안 들어오고, 괜히 태우면
#: 몇 초를 쓴다. 비용이 비대칭인 방향이 라우팅과 같다.
_TELLING = (
    "내가", "우리", "나는", "내 ", "제가", "저는",
    "이름", "이야", "이다", "입니다", "야.", "지금",
    "쓰는", "쓴다", "만든", "만드는", "산다", "샀", "있어", "있다",
    "좋아", "싫어", "선호", "원해", "해줘", "하지 마", "하지마",
    "회사", "사무실", "학원", "제품", "서비스",
    "옮겼", "이전", "바꿨", "바꾸", "정했", "결정",
)

#: 뽑지 않는다. 지나가는 말이거나, 이미 다른 자리가 맡고 있다.
_NOT_WORTH = ("고마워", "고맙", "잘했", "수고", "ㅋㅋ", "ㅎㅎ", "알겠", "오케이", "ok")


def worth_extracting(user_text: str, assistant_text: str = "") -> bool:
    """이 대화에 뽑을 게 있을 법한가. **모델을 태우기 전에** 판단한다."""
    text = " ".join(str(user_text or "").split())
    if len(text) < MIN_USER_CHARS:
        return False
    compact = text.lower()
    if any(word in compact for word in _NOT_WORTH) and len(text) < 40:
        return False
    return any(word in text for word in _TELLING)


_PROMPT = """다음 대화에서 **오래 남을 사실**만 뽑아라.

규칙:
- 사용자에 대한 것, 사용자의 회사·제품에 대한 것, 사용자가 일하는 방식,
  사용자가 지금 진행 중인 일, 참고할 값(장비·주소·이름) 만 뽑는다.
- **이 대화에만 해당하는 것은 뽑지 마라.** "지금 이걸 해줘" 같은 것은 사실이 아니다.
- 한 줄에 하나. 200자를 넘기지 마라.
- 없으면 빈 배열을 줘라. **없는데 지어내지 마라.**
- 사실의 근거가 되는 말을 대화에서 **그대로** `quote` 에 옮겨 적어라.

kind 는 다음 중 하나다:
  person      사용자와 주변 사람
  product     사용자의 회사·제품·서비스
  preference  사용자가 일을 어떻게 하길 원하는가
  ongoing     지금 진행 중인 일
  reference   장비·주소·이름 같은 참고값

JSON 만 답해라. 다른 말은 쓰지 마라.
{"facts": [{"kind": "...", "subject": "...", "fact": "...", "quote": "..."}]}

--- 대화 ---
사용자: {user}
손자리: {assistant}
"""


def build_prompt(user_text: str, assistant_text: str, *, max_chars: int = 3000) -> str:
    """모델에게 보낼 말. 긴 답변은 앞부분만 — 사실은 대개 앞에 있다."""
    return (
        _PROMPT.replace("{user}", str(user_text or "")[:max_chars])
        .replace("{assistant}", str(assistant_text or "")[:max_chars])
    )


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def parse(raw: str) -> list[dict[str, str]]:
    """모델 답에서 사실 목록을. **못 읽으면 빈 목록**이고 예외를 안 낸다.

    추출이 실패했다고 대화가 안 되면 그게 더 나쁘다. 다만 빈 목록과 「못 읽음」을
    부르는 쪽이 구별할 수 있어야 하므로, 실패는 로그로 남긴다(부르는 쪽 책임).
    """
    text = str(raw or "").strip()
    if not text:
        return []
    match = _JSON_BLOCK.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except Exception:
        return []
    rows = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "kind": str(row.get("kind") or "").strip().lower(),
                "subject": " ".join(str(row.get("subject") or "").split()),
                "fact": " ".join(str(row.get("fact") or "").split()),
                "quote": " ".join(str(row.get("quote") or "").split()),
            }
        )
    return out


def _loose(value: str) -> str:
    """대조용으로 느슨하게. 공백·문장부호를 지운다.

    모델이 인용을 옮기며 띄어쓰기나 조사를 조금 바꾸는 일이 흔하다. 그걸
    「지어냈다」로 판정하면 멀쩡한 사실이 전부 버려진다.
    """
    return re.sub(r"[\s.,!?~·…\-\"'()\[\]]+", "", str(value or "")).lower()


def grounded(row: dict[str, str], sources: Iterable[str], *, min_quote: int = 6) -> bool:
    """이 사실의 근거가 **대화에 실제로 있는가.**

    ★ 이게 사고 I 의 재발 방지다. 모델이 「이 사실은 대화에서 나왔다」고 말하는
      것은 주장일 뿐이고, 여기서 대조한다.

    인용이 너무 짧으면(조사 하나, 낱말 하나) 아무 데나 걸리므로 안 받는다.
    """
    quote = _loose(row.get("quote", ""))
    if len(quote) < min_quote:
        return False
    haystack = _loose(" ".join(sources))
    return quote in haystack


#: 사람에 관한 갈래 — 이건 **사람이 한 말**에 근거가 있어야 한다.
PERSON_KINDS = frozenset({"person", "preference"})


def usable(rows: list[dict[str, str]], sources: Iterable[str], kinds: Iterable[str], *,
           speaker_text: str | None = None) -> tuple[
    list[dict[str, str]], list[tuple[dict[str, str], str]]
]:
    """쓸 수 있는 것과 **왜 버렸는지**를 함께 돌려준다.

    버린 이유를 안 남기면 「추출이 안 된다」와 「뽑을 게 없었다」를 구별할 수
    없다. 빈 값이 두 가지를 뜻하면 조용히 고장 난다.
    """
    allowed = set(kinds)
    keep: list[dict[str, str]] = []
    dropped: list[tuple[dict[str, str], str]] = []
    for row in rows:
        if row["kind"] not in allowed:
            dropped.append((row, f"모르는 갈래 {row['kind']!r}"))
            continue
        if not row["subject"] or not row["fact"]:
            dropped.append((row, "subject 나 fact 가 비었다"))
            continue
        if not grounded(row, sources):
            dropped.append((row, "대화에 근거가 없다 — 지어낸 것으로 본다"))
            continue
        # ★ 2026-09-17 제품 책임자 목격: 온텔릭이 사용자의 이름·경력을 「상시 프로필」이라며 **답한 그 문장**이
        #   4초 뒤 사실 서랍에 사람에 관한 사실로 저장됐다. 인용이 답에 있으니 근거 대조는 통과했다 — 자기가 한 말이
        #   다음 판의 「사실」이 되는 고리다. 사람에 관한 것은 **사람이 한 말**에 있어야 한다.
        if speaker_text is not None and row["kind"] in PERSON_KINDS and not grounded(row, (speaker_text,)):
            dropped.append((row, "사람에 관한 사실인데 근거가 손자리 자기 말뿐이다"))
            continue
        keep.append(row)
    return keep, dropped

#: 사실을 **영구 서랍에 남기면 안 되는** 세션. 벤치·프로브·회수용 판이다.
#
# 2026-08-27 실측: 서랍의 202건 중 149건(74%)이 벤치 세션에서 왔고, 그중
# 「사용자 선호」 17건은 벤치 프롬프트 문구(“테스트 파일은 수정하지 마”)가
# 사용자의 영구 취향으로 박힌 것이었다. 같은 말이 17번 들어가 있었다.
#
# 벤치의 과제 지시는 **그 판에서만 참인 제약**이지 사람의 취향이 아니다.
EPHEMERAL_SESSION_MARKERS = (
    "code-repo-bench",
    "code-search-bench",
    "q4-golden",
    "p1-roundtrip",
    "-bench-",
    "smoke-",
)
#: 방 이름이 **이것으로 시작하면** 임시다.
#
# ★ 2026-10-08 전수조사 3-7. 위 표는 이름 가운데의 `-bench-` 만 봐서 `bench…` 로 **시작하는** 방과, 바깥 AI 가 맡긴 과제 방
#   (`mcp-…` — MCP 서버가 과제마다 그렇게 짓는다)이 통째로 샜다. 살아 있는 사실 1,277개 가운데 `bench…` 방 것이 400개,
#   `mcp-…` 방 것이 67개(합쳐 37%)였고, 이것들이 매 판 「배운 것」으로 모델에게 실렸다.
#   바깥 AI 가 쓴 과제 문장은 사람이 한 말이 아니다 — 거기서 「사람에 관한 사실」을 배우면 안 된다.
EPHEMERAL_SESSION_PREFIXES = ("mcp-", "bench")


def ephemeral_session(session_id: str = "", code_workspace: str = "") -> str:
    """이 판이 임시라면 그 이유를, 아니면 빈 문자열을 돌려준다.

    두 가지로 본다. 세션 이름표와, **작업한 저장소가 우리 산출물 폴더 안인지**.
    벤치가 물질화한 판은 다음 실행이면 사라지므로 거기서 배운 경로·동작은
    영구 사실이 될 수 없다.
    """
    lowered = str(session_id or "").strip().lower()
    for prefix in EPHEMERAL_SESSION_PREFIXES:
        if lowered.startswith(prefix):
            return f"ephemeral_session:{prefix}"
    for marker in EPHEMERAL_SESSION_MARKERS:
        if marker in lowered:
            return f"ephemeral_session:{marker}"
    workspace = str(code_workspace or "").replace("\\", "/").lower()
    if workspace and ("/outputs/" in workspace or "/temp/" in workspace or "/tmp/" in workspace):
        return "ephemeral_workspace"
    return ""
