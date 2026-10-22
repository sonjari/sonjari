"""답 맨 앞의 진행 보고 한 줄 떼기 (2026-10-18 처음 보는 사이트 측정 · steamcharts 판).

## 사고

steamcharts 에서 「현재 접속자 수 상위 5개」를 시켰더니 답이
「PUBG: 482,875 확인했습니다. 5개 자료를 읽었으니 이제 정리하겠습니다.」로 시작하고, 그 아래에 진짜 답(표)이 왔다.
첫 줄은 모델이 일하면서 하는 말(마지막 확인 · 「이제 정리하겠다」)이지 답이 아니다. 사람은 첫 줄의 숫자를 답으로 읽는다.

## 고친 것

`answer_hygiene._drop_progress_preamble` — 첫 단락이 **정보를 얻은 일의 과거 보고**(읽었 · 확인했 · 찾았 …)와
**「(이제) 정리 · 답 · 말씀하겠다」로 넘기는 한 문장**만으로 되어 있고, 그 아래에 진짜 답이 있을 때만 그 단락을 뗀다.
못 했다 · 틀렸다 · 정정 같은 말, 보고가 아닌 내용 절, 파일을 만들겠다는 말, 본문에 없는 이름(출처)이 머리에 있으면 남긴다.
운영 답 4,490개에 대 봤을 때 28개가 떼였고 전부 진행 보고였다(출처가 머리에만 있는 답은 남았다).

## 같은 판의 둘째 고장(표 한 칸에 다른 지표가 섞임)은 검사를 넣지 않았다

「현재 접속자 수」 칸의 1~3위는 게임 페이지의 "playing an hour ago", 4~5위는 목록의 "Current Players" 였고 답은 그 사실을
아래 글머리에서만 밝혔다. 답 글의 「1~3위는 … 값 / 4~5위는 … 값」 꼴로 잡는 검사는 운영 답 4,490개 중 이 판 하나에만 걸린다
(n=1 — 그 사고 문구를 외운 것과 같다). 조금만 넓히면(「4·5번은 목록에서, 1~3번은 상세 화면에서 확인」) 같은 지표(항공권 값)를
깊이만 달리 확인한 판에 헛걸린다. 제대로 하려면 표 칸 값마다 **읽은 원문에서 그 값 옆의 지표 이름**을 찾아 행끼리 견줘야 하는데,
운영 DB 의 걸음 기록은 미리보기만 남아 있어 그 검사를 먼저 재 볼 수 없다. 재 보지 못한 검사는 넣지 않는다.
"""
from __future__ import annotations

from alture_jarvis.answer_hygiene import _drop_progress_preamble

BODY = (
    "예시 사이트에서 확인한 현재 이용자 수 상위 3개입니다.\n\n"
    "| 순위 | 이름 | 이용자 수 |\n|---|---|---|\n"
    "| 1 | 가나다 게임 | 900,000 |\n| 2 | 라마바 게임 | 700,000 |\n| 3 | 사아자 게임 | 400,000 |\n"
)


def test_progress_line_then_table_is_dropped():
    answer = "사아자 게임: 400,000 확인했습니다. 3개 자료를 읽었으니 이제 정리하겠습니다.\n\n" + BODY
    assert _drop_progress_preamble(answer) == BODY.strip()


def test_common_shapes_are_dropped():
    for head in (
        "두 개를 읽었습니다. 정리해 드릴게요.",
        "사용자님, 세 자료 모두 읽었습니다. 이제 정리해서 드리겠습니다.",
        "네, 충분한 자료를 확보했습니다. 분석 결과를 정리해 드리겠습니다.",
        "세 곳 모두 확인 완료. 이제 말씀드리겠습니다.",
    ):
        assert _drop_progress_preamble(head + "\n\n" + BODY) == BODY.strip(), head


def test_head_right_above_table_without_blank_line():
    answer = "두 개를 읽었습니다. 정리해 드릴게요.\n| 순위 | 이름 |\n|---|---|\n| 1 | 가나다 게임 |\n| 2 | 라마바 게임 |"
    assert _drop_progress_preamble(answer).startswith("| 순위 | 이름 |")


def test_only_content_is_never_dropped():
    only = "두 개를 읽었습니다. 정리해 드릴게요."
    assert _drop_progress_preamble(only) == only
    short_rest = only + "\n\n짧은 말."
    assert _drop_progress_preamble(short_rest) == short_rest


def test_failure_or_correction_stays():
    for head in (
        "두 곳은 확인했지만 한 곳은 확인하지 못했습니다. 확인한 것으로 정리하겠습니다.",
        "죄송합니다. 세 페이지를 모두 읽었습니다. 다시 정리하겠습니다.",
        "목록이 더 안 늘어났으니 3건이 전부입니다. 결과를 정리하겠습니다.",
    ):
        answer = head + "\n\n" + BODY
        assert _drop_progress_preamble(answer) == answer, head


def test_content_clause_stays():
    # 넘기는 문장의 앞 절이 보고가 아니라 내용(기준에 따라 답이 다름)이면 남긴다.
    answer = "목록을 직접 확인했습니다. 기준에 따라 답이 달라지니, 크게 3개로 정리하겠습니다.\n\n" + BODY
    assert _drop_progress_preamble(answer) == answer
    # 「…읽었는데, 핵심은 둘째 글에 있습니다」 — 맺는 말이 보고가 아니다.
    answer = "글 세 개를 읽었는데, 핵심은 둘째 글에 있습니다. 이제 정리해 드릴게요.\n\n" + BODY
    assert _drop_progress_preamble(answer) == answer


def test_source_named_only_in_head_stays():
    answer = "가상일보 오전 헤드라인 본문을 직접 읽었습니다. 정리해 드릴게요.\n\n" + BODY
    assert _drop_progress_preamble(answer) == answer
    named = "예시 사이트 본문을 직접 읽었습니다. 정리해 드릴게요.\n\n" + BODY
    assert _drop_progress_preamble(named) == BODY.strip()


def test_file_promise_and_bare_intro_stay():
    answer = "세 곳 모두 확인했습니다. 결과를 엑셀 파일로 정리하겠습니다.\n\n" + BODY
    assert _drop_progress_preamble(answer) == answer
    intro = "지금까지 확인한 내용을 정리해 드리겠습니다.\n\n" + BODY
    assert _drop_progress_preamble(intro) == intro


def test_english():
    body = "| Rank | Name |\n|---|---|\n| 1 | Alpha Game |\n| 2 | Beta Game |\n| 3 | Gamma Game |"
    assert _drop_progress_preamble("I've read 5 sources, now summarizing.\n\n" + body) == body
    assert _drop_progress_preamble("I've read both pages. Here's what I found.\n\n" + body) == body
    keep = "I've confirmed the answer. The top one is Alpha Game.\n\n" + body
    assert _drop_progress_preamble(keep) == keep
    keep = "I've checked two pages but could not open the third. Here's what I found.\n\n" + body
    assert _drop_progress_preamble(keep) == keep


def test_agent_uses_it():
    from alture_jarvis import agent

    assert agent._drop_progress_preamble is _drop_progress_preamble
