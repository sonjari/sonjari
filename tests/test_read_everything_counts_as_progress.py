"""「전부·끝까지」라고 시킨 판은 산출물만 남아도 **처음 읽는 글**이 진척이다 (2026-10-03 레딧 기록 판 98220347).

「올린 글을 전부」인데 계획은 「근거 1개 읽기」뿐이라, 6개 중 2개를 읽은 시점에 「진척 없음」으로 파일 쓰기로 넘어갔다 —
엑셀에 글 2개만 들어갔다. 그 말이 없는 판은 예전대로 「파일만 남았으면 쓰러 가라」(끝없이 읽던 판을 막은 설계).
"""

from __future__ import annotations

from types import SimpleNamespace

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.plan import asks_for_everything

ARTIFACT_LEFT = [(SimpleNamespace(kind="artifact", target=(".xlsx",)), False, "열 수 있는 산출물 없음"),
                 (SimpleNamespace(kind="observe", target=1), True, "2개 실제로 읽음")]


def _read(url: str) -> dict:
    return {"tool": "browser_extract", "ok": True, "evidence": {"url": url, "char_count": 4000}}


def test_reading_a_new_post_is_progress_only_when_everything_was_asked() -> None:
    steps = [_read(f"https://reddit.example/p/{i}") for i in range(1, 9)]
    assert BrowserAgent._progress_matches_remaining_plan(steps, ARTIFACT_LEFT, wants_everything=True)
    assert not BrowserAgent._progress_matches_remaining_plan(steps, ARTIFACT_LEFT)


def test_rereading_the_same_posts_is_not_progress() -> None:
    steps = [_read(f"https://reddit.example/p/{i % 2}") for i in range(10)]
    assert not BrowserAgent._progress_matches_remaining_plan(steps, ARTIFACT_LEFT, wants_everything=True)


def test_the_words_that_mean_everything() -> None:
    for yes in ("이 계정이 올린 글을 전부 찾아줘", "빠짐없이 정리해", "끝까지 내려서", "모든 공고를 읽고", "Read all posts"):
        assert asks_for_everything(yes), yes
    for no in ("사람인 공고 3개 찾아줘", "전부터 궁금했는데", "이전부터 쓰던", "smaller files"):
        assert not asks_for_everything(no), no
