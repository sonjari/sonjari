"""코딩 분업 실험(10-22)에서 잡힌 손자리 버그 둘.

1. `repo` 만 주고 「고치지 마 · 읽고 요약만」이라고 맡긴 **찾기** 일이 「코드 고치는 일」로 잡혀 검증하라고 되받혔고, 찾은 요약 대신
   모델의 실랑이 말이 최종 답이 됐다(판 db81850b). `check` 를 준 판만 고치는 일이다.
2. 4,000자를 넘는 과제 글을 말없이 잘랐다 — 고친 코드를 붙인 click 과제 글이 정확히 4,000자에서 끊겼다. 이제 돌려보낸다.
"""

from __future__ import annotations

import asyncio

from alture_jarvis.mcp_server import TASK_MAX_CHARS, JarvisMcpBridge
from alture_jarvis.plan import asks_read_only, delegated_read_only

FIND_MID = ("이 저장소(more_itertools)에서 one() 과 only() 함수의 구현을 찾아 주세요. 그 코드가 어떻게 동작하는지 파일 경로와 "
            "함수 이름, 줄 번호로 요약해 주세요. 코드는 고치지 마세요 — 읽고 요약만 해 주세요.")
FIND_HIGH = "click 저장소(이 폴더)에서 Option 의 envvar 표시 관련 코드를 찾아 줘. 고치지는 말고 어디서 어떻게 흐르는지만 파일·함수·줄로 요약해 줘."
FIX = "more_itertools 저장소의 one() 과 only() 버그를 고쳐 주세요. 먼저 재현 시험을 넣고 고쳐 주세요."
PARTIAL_GUARD = "이 버그를 고쳐 줘. 테스트 파일은 건드리지 마."


def test_read_only_words() -> None:
    assert asks_read_only(FIND_MID) and asks_read_only(FIND_HIGH)
    assert asks_read_only("Find where envvar is rendered. Don't change anything, just read and summarize.")
    assert not asks_read_only(FIX)
    assert not asks_read_only(PARTIAL_GUARD), "고치면서 일부만 막는 말을 읽기 일로 낮추면 검증이 빠진다"


def test_repo_without_check_and_read_only_is_a_find() -> None:
    branch = {"repo": "E:/x", "check": "", "workspace": "C:/w"}
    assert delegated_read_only(branch, FIND_MID)
    assert not delegated_read_only(branch, FIX), "고치라고 했으면 check 가 없어도 고치는 일이다"
    assert not delegated_read_only({**branch, "check": "python -m pytest -q"}, FIND_MID), "check 를 줬으면 고치는 일"
    assert not delegated_read_only(None, FIND_MID)


def test_too_long_task_is_sent_back_not_cut() -> None:
    bridge = JarvisMcpBridge(base_url="http://127.0.0.1:9", token="x")
    text, failed = asyncio.run(bridge._delegate("sonjari_task", {"task": "가" * (TASK_MAX_CHARS + 1)}))
    assert failed
    assert "보내지 않았습니다" in text and "코드를 붙이지 마세요" in text
