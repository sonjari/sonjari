"""스킬 본문 위생 필터 — 승인·확인을 건너뛰라는 문장을 무력화한다 (W4 · TODO 6차 C ★).

스킬 본문은 밖에서 온 글인데 모델에게는 지시로 읽힌다. 자비스는 브라우저 쓰기·메일·일정 같은 손을 쥐고 있고,
위험등급(`ToolSpec.dynamic_risk`)은 게이트웨이를 지나는 호출에만 걸린다 — 프롬프트로 들어오는 스킬 본문은 그 보호 밖이다.

## 넓게 막지 않는다 (게이트는 양방향으로 잰다)

2026-09-15 수확물 96종을 넓은 그물(`without asking|don't ask|skip review` …)로 훑으니 12곳이 걸렸는데
**대부분 무해했다**: 「언어는 묻지 마라(질문이 언어 무관이면)」, 「다섯 개를 한꺼번에 묻지 마라」,
「리뷰어에게 테스트를 다시 돌리라고 하지 마라」, 「Never: Skip review」(금지 목록 안), 「proceed without comment」.
이런 문장을 걷으면 플레이북이 망가진다. 그래서 **진행·실행 동사 + 묻지/확인/승인 없이** 가 붙은 문장만 걷는다.
걸러야 할 표본과 남겨야 할 표본을 둘 다 `tests/test_skill_hygiene.py` 에 박아 둔다.

걷는 방식: 문장을 지우지 않고 **걷었다고 적는다.** 조용히 사라지는 것이 이 저장소에서 제일 나쁜 실패 모양이다.
"""

from __future__ import annotations

import re

NOTE = "〔손자리 위생 필터: 승인·확인 없이 진행하라는 문장을 걷었다 — 승인 절차는 등록된 위험등급을 따른다〕"

# 진행·실행하라는 말 + (묻지/확인/승인/허락) 없이. 영어·한국어.
_RISKY = re.compile(
    r"[^.\n!?]*?"
    r"(?:"
    r"\b(?:proceed|continue|go ahead|act|execute|run|send|publish|submit|deploy|delete|purchase|pay|push|merge)\b"
    r"[^.\n!?]{0,40}\bwithout\s+(?:asking|confirmation|confirming|approval|permission|checking\s+with\s+the\s+user)"
    r"|\bwithout\s+(?:asking|confirmation|approval|permission)\b[^.\n!?]{0,40}"
    r"\b(?:send|publish|submit|deploy|delete|purchase|pay|push|merge)\b"
    r"|(?:묻지\s*말고|확인\s*없이|승인\s*없이|허락\s*없이)[^.\n!?]{0,30}(?:진행|실행|보내|발행|삭제|결제|제출|배포)"
    r"|(?:사용자|사람)에게\s*알리지\s*(?:말고|마)"
    r")"
    r"[^.\n!?]*[.!?]?",
    re.I,
)


def neutralize(body: str) -> tuple[str, int]:
    """걷은 본문과 걷은 문장 수."""
    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        leading = match.group(0)[: len(match.group(0)) - len(match.group(0).lstrip())]
        return leading + NOTE

    return _RISKY.sub(_replace, body), count


__all__ = ["NOTE", "neutralize"]
