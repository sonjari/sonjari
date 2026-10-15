"""22시 레딧 예약 판(2026-10-03 5fa9b74c)에서 나온 것.

① 생각 시간이 넘친 뒤 두 번째 답이 한 문단을 1만 8천 자 되풀이했다 — 본문에는 되풀이 끊기가 없었다.
② 모델이 `.json` 을 직접 열자 요약이 안 붙었고, 원문은 2만 자에서 잘려 「댓글마다 작성자·요지」를 못 읽었다.
"""

from __future__ import annotations

from alture_jarvis.agent import _only_a_promise
from alture_jarvis.browser import BrowserWorker, reddit_post_comments, reddit_post_stats
from alture_jarvis.ollama import collapse_repeated_paragraphs

LOOP = "\n\n".join(
    ["[생각 시간이 다 됐습니다]",
     "browser_read가 .json을 12000자로 자릅니다. 댓글을 모두 읽으려면 .json을 파일로 저장해 파싱해야 하는데, "
     "sandbox_run은 사이트 스크래핑을 막습니다. .json을 브라우저로 열고 browser_read로 원문을 그대로 읽어보겠습니다."] * 40
) + "\n\n[생각 시간이 다 됐습니다]\n\nbrowser_read가 .json"


def test_a_looping_answer_collapses_to_one_promise() -> None:
    once = collapse_repeated_paragraphs(LOOP)
    assert once.count("읽어보겠습니다") == 1 and "[생각 시간" not in once
    assert len(once) < 200
    # 접히고 나면 예고 그물이 다시 일한다(전에는 1만 8천 자라 450자 상한을 넘었다).
    assert _only_a_promise(once)


def test_normal_answers_are_left_alone() -> None:
    answer = "## 결과\n\n| 글 | 점수 |\n|---|---|\n| A | 4 |\n| B | 4 |\n\n두 글 모두 점수 4 입니다.\n\n출처: https://www.reddit.com/"
    assert collapse_repeated_paragraphs(answer) == answer


PAYLOAD = [
    {"data": {"children": [{"data": {
        "score": 12, "num_comments": 4, "upvote_ratio": 0.93, "title": "Popular old GGUF or brand-new one with 0 downloads?",
        "subreddit_name_prefixed": "r/LocalLLM", "created_utc": 1790900000, "view_count": None}}]}},
    {"data": {"children": [
        {"kind": "t1", "data": {"author": "plainuser07", "score": 9, "body": "Don't trust the tag, read the actual config.",
                                "replies": {"data": {"children": [
                                    {"kind": "t1", "data": {"author": "Maker-Account0000", "score": 3, "body": "Thanks — fixed it.",
                                                            "replies": ""}}]}}}},
        {"kind": "t1", "data": {"author": "Quiet-Harbor1234", "score": 5, "body": "Render the template first. " * 20, "replies": ""}},
        {"kind": "more", "data": {"count": 2}},
    ]}},
]


def test_stats_carry_title_board_and_time() -> None:
    stats = reddit_post_stats(PAYLOAD)
    assert stats["title"].startswith("Popular old GGUF") and stats["subreddit"] == "r/LocalLLM"
    assert stats["created_utc"] == "2026-10-02 00:13" and "view_count" not in stats


def test_comments_are_flattened_with_depth_and_hidden_ones_counted() -> None:
    comments, hidden = reddit_post_comments(PAYLOAD)
    assert [(c["author"], c["depth"]) for c in comments] == [
        ("plainuser07", 0), ("Maker-Account0000", 1), ("Quiet-Harbor1234", 0)]
    assert comments[2]["gist"].endswith("…") and len(comments[2]["gist"]) <= 161
    assert hidden == 2


def test_a_directly_opened_json_gets_the_digest() -> None:
    class Response:
        ok = True

        def json(self):
            return PAYLOAD

    class Page:
        url = "https://www.reddit.com/r/LocalLLM/comments/1wvpw0e/popular_old_gguf.json"

        class context:
            class request:
                @staticmethod
                def get(url, **_):
                    assert url == "https://www.reddit.com/r/LocalLLM/comments/1wvpw0e.json"
                    return Response()

    out = BrowserWorker._attach_post_stats(None, Page(), {"ok": True, "url": Page.url, "text": '[{"kind": "Listing", ...'})
    assert out["text"].startswith("[레딧 글 수치] 점수(추천) 12 · 댓글 4")
    assert "r/LocalLLM" in out["text"] and "[레딧 댓글 3개 · 접혀 있어 안 읽은 댓글 2개]" in out["text"]
    assert "  - u/Maker-Account0000 (점수 3): Thanks — fixed it." in out["text"]


def test_a_runs_reply_language_does_not_leak_to_the_next_thing() -> None:
    """판 언어가 판 밖으로 새면 같은 스레드의 다음 일이 영어 경고를 받는다(10-03 회귀 5개가 순서에 따라 깨짐)."""
    from alture_jarvis import agent as agent_module

    @agent_module._reply_language_scoped
    def english_run() -> str:
        agent_module._REPLY_LANGUAGE.set("en")
        return agent_module.reply_language("한국어 요청")

    assert english_run() == "en"
    assert agent_module.reply_language("한국어 요청") == "ko"
    assert agent_module.BrowserAgent.run.__wrapped__.__name__ == "run"


# ── 같은 과제 재실행(50bc9afe)에서 나온 것 ─────────────────────────────────────────────
def test_the_artifact_turn_may_read_the_file_it_appends_to() -> None:
    from alture_jarvis.agent import _focused_tool_definitions

    tools = [{"function": {"name": name}} for name in
             ("browser_open", "local_read_document", "local_edit_spreadsheet", "local_write_document")]
    names = {tool["function"]["name"] for tool in _focused_tool_definitions(tools, "artifact")}
    assert "local_read_document" in names and "browser_open" not in names


def test_a_row_url_that_is_the_front_of_an_opened_url_is_the_same_post() -> None:
    from alture_jarvis.agent import BrowserAgent

    opened = "https://www.reddit.com/r/LocalLLM/comments/1wvpw0e/popular_old_gguf_or_brandnew_one_with_0_downloads/"
    steps = [{"tool": "browser_open", "ok": True, "evidence": {"url": opened, "title": "Popular old GGUF or brand-new one? : r/LocalLLM"}}]
    answer = ("| 번호 | 게시판 | 제목 | 링크 |\n|---|---|---|---|\n"
              "| 1 | r/LocalLLM | Popular old GGUF or brand-new one? | https://www.reddit.com/r/LocalLLM/comments/1wvpw0e/ |\n")
    assert "열지 않은 주소" not in BrowserAgent._row_page_binding_check(answer, steps)


def test_the_digest_gives_this_pcs_time_too() -> None:
    stats = reddit_post_stats(PAYLOAD)
    assert stats["created_local"] and len(stats["created_local"]) == 16
