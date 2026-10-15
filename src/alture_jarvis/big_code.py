"""작은 모델에게 **큰 코드를 통째로** 시켰을 때, 시작하기 전에 갈림길을 묻는다 (2026-10-02).

## 왜 생겼나

같은 일이 두 번 났다.
- 10-01 첫 테스터: 손자리 9B 에게 3ds Max 용 앱 **전체를 한 번에** 시켰다 — 코드가 망가졌다(클로드 오푸스도 한 번엔 못 하는 크기).
- 10-01 밤 지인 개발자: 브라우저에는 충격을 받았는데, 코드는 클로드를 안 거치고 손자리 9B 에게 **게임 스크립트를 다** 시켰다.
  다음 날 반응이 「당장 우리는 크게 활용하기 힘든 것 같고」였다.

두 분 다 개발자다. 실사용자는 과제를 쪼개 주지 않고 한 줄로 시킨다(전략안 §55-17). 실패는 「손자리 별로」로 기억된다.
그래서 **실패를 갈림길로** 바꾼다 — 시작 전에 질문 카드(`ask_user`, 이미 있는 화면)로 고르게 한다.

## 언제 묻나 (좁게)

- 코드 일(코드 역할 또는 실행 검증이 걸린 판)이고, 코드 모델이 **20B 미만**이고,
- 요청이 「통째로 만들기」 모양이다: 범위 낱말(전체·전부·다·통째·처음부터·한 번에·모든 기능…) + 대상(게임·앱·프로그램·플러그인·사이트·
  스크립트…) + 만들기 동사, 그리고 「간단한·작은·예제」 같은 말이 없다.
- 운영 요청 1,456개(2026-10-02)에 대 보니 걸린 것은 1개 — 코드가 아닌 조사 요청이라 코드 조건에서 빠진다. 진짜 사례 둘은 그분들 PC 에서
  났기 때문에 우리 기록엔 없다(두 문장 모양으로만 확인했다).
"""

from __future__ import annotations

import re
from typing import Any

#: 선택지 이름 — 답(`answer`)이 이 글자 그대로 돌아온다. 화면 버튼에도 이대로 뜬다.
CLAUDE = "클로드 코드에 맡기기"
PASTE = "클로드에 붙여 넣을 글 받기"
SPLIT = "작게 나눠서 하나씩"
AS_IS = "그대로 진행"

#: 질문 카드 인자에 붙이는 표식 — 이 판의 갈림길 질문인지 가른다(모델이 부른 ask_user 와 섞이지 않게).
MARK = "_big_code"

#: 이보다 작은 코드 모델에만 묻는다. 20B 이상은 `hf_catalog.code_upgrade` 의 「이미 크다」와 같은 선.
SMALL_MODEL_MAX_B = 20.0

_THING = (r"(게임|앱|어플|애플리케이션|프로그램|툴|플러그인|확장\s*프로그램|웹\s*사이트|홈페이지|사이트|서비스|시스템|엔진|에디터|봇|"
          r"스크립트|코드|프로젝트|클라이언트|서버|대시보드|쇼핑몰)")
_SCOPE = (r"(전체|전부|통째|통으로|처음부터|한\s*번에|한번에|완성본|완전한|풀\s*버전|모든\s*(?:기능|코드|스크립트|파일)|"
          r"(?:^|\s)다\s*(?=만들|짜|구현|개발|제작|완성))")
_WHOLE = re.compile(rf"{_SCOPE}[^.!?\n]{{0,30}}?{_THING}|{_THING}[^.!?\n]{{0,30}}?{_SCOPE}")
_MAKE = re.compile(r"(만들어|만들기|만들자|만들고|짜\s*줘|짜\s*주|개발해|구현해|제작해|완성해|코딩해)")
_SMALL = re.compile(r"(간단한|간단히|간단하게|작은|미니|예제|샘플|한\s*줄|함수\s*하나|테스트용|연습)")


def looks_like_whole_build(prompt: str) -> bool:
    """「통째로 만들어 달라」 모양의 요청인가."""
    text = " ".join(str(prompt or "").split())
    return bool(_WHOLE.search(text) and _MAKE.search(text) and not _SMALL.search(text))


def question(model_b: float, *, claude_available: bool) -> dict[str, Any]:
    """질문 카드 인자. 클로드 코드가 이 PC 에 있으면 맡기기를, 없으면 붙여 넣을 글을 권한다."""
    size = f"{model_b:g}B" if model_b else "작은"
    first = (
        {"label": CLAUDE, "description": "이 PC 의 클로드 코드가 짜고 테스트까지 돌립니다. 클로드 사용량이 듭니다."}
        if claude_available
        else {"label": PASTE, "description": "클로드에 붙여 넣을 요청 글을 드립니다. 손자리는 파일 읽기·실행을 맡습니다."}
    )
    return {
        "question": f"이 일은 이 PC 의 {size} 모델이 한 번에 하기엔 큽니다. 어떻게 할까요?",
        "options": [
            first,
            {"label": SPLIT, "description": "먼저 단계를 나눠 보여 드리고, 첫 단계부터 만들어 실제로 돌려 봅니다."},
            {"label": AS_IS, "description": "이 PC 모델로 한 번에 해 봅니다. 큰 일은 잘 안 될 수 있습니다."},
        ],
        "recommended": 0,
        MARK: True,
    }


def paste_text(prompt: str, folder: str = "") -> str:
    """클로드(클로드 코드·클로드 앱)에 그대로 붙여 넣을 요청 글. 지어내는 말 없이 사용자의 요청을 그대로 싣는다."""
    where = f"작업 폴더: {folder}\n" if folder else ""
    return (
        "이 일은 클로드와 나눠 하시는 게 좋습니다. 아래 글을 클로드 코드(또는 클로드 앱)에 그대로 붙여 넣으세요.\n\n"
        "```\n"
        f"{where}{' '.join(str(prompt or '').split())}\n\n"
        "진행 방식:\n"
        "- 먼저 이 일을 작은 단계로 나누고, 단계마다 실제로 실행해 확인한 뒤 다음으로 넘어가 주세요.\n"
        "- 이 PC 에 손자리(Sonjari) 연결이 있으면, 넓게 파일 찾기·읽기, 테스트 실행과 긴 로그 읽기, 문서 검색은 손자리에게 맡겨 주세요.\n"
        "```"
    )


SPLIT_NOTE = (
    "[손자리 안내] 사용자가 「작게 나눠서 하나씩」을 골랐다. 먼저 이 일을 3~6개 단계로 나눈 목록을 보여 주고, **1단계만** 만들어 "
    "실제로 실행해 확인한 뒤 멈춰라. 남은 단계는 답 끝에 목록으로 적고, 「이어서 해줘」라고 하면 다음 단계를 한다고 알려라."
)


def chosen(steps: list[dict[str, Any]]) -> str | None:
    """이 판의 갈림길 질문에 사람이 고른 답. 아직 안 물었으면 None, 물었는데 답이 비었으면(맡김) 빈 문자열."""
    for step in steps:
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        if step.get("tool") == "ask_user" and arguments.get(MARK):
            evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
            return str(evidence.get("answer") or "")
    return None


def asked(steps: list[dict[str, Any]]) -> bool:
    return any(
        step.get("tool") == "ask_user" and isinstance(step.get("arguments"), dict) and step["arguments"].get(MARK)
        for step in steps
    )
