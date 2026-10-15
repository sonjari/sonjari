"""장부는 사람 문 앞에만 있으면 안 된다.

8단계에서 "같은 사이트에서 세 번 막히면 레시피를 만들자"는 규칙을 넣었다. 그런데
막힘을 세는 곳이 `_checkpoint_human_gate` **한 군데**였다 — 로그인과 봇 확인 앞에서만
적혔다는 뜻이다.

정작 레시피가 제일 급한 곳은 거기가 아니었다. 「알려진 한계」에 적어 둔 것은
**"크몽 공고 본문 접근이 불안정하다 — 레시피를 박아야 풀릴 문제"** 인데, 크몽 공고는
로그인을 요구하지도 봇 확인을 띄우지도 않는다. 그냥 안 읽힌다. 그래서 그 사이트는
장부에 한 줄도 없었고, 3번 규칙이 영영 걸리지 않았다. 레시피가 자기 입력을 못 받고
있었던 것이다.

여기서 조심할 것은 반대쪽이다. **실패한 걸음을 그때그때 세면** 세 번 두드려 결국
읽어낸 멀쩡한 사이트까지 장부 위로 올라오고, 그러면 3번 규칙이 아무 데서나 걸려
아무도 안 믿게 된다. 이 저장소는 게이트를 좋은 표본으로 역검증해야 한다는 것을 이미
두 번 배웠다 — 그래서 아래 시험의 절반은 **안 세는 경우**를 지킨다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.human_gate import (
    CONTENT_FRICTION_CODE,
    RECIPE_SUGGEST_AFTER,
    suggest_recipe,
)
from alture_jarvis.jobs import JobStore
from alture_jarvis.tool_gateway import ToolGateway


def _agent() -> BrowserAgent:
    root = Path(tempfile.mkdtemp())
    config = JarvisConfig(
        runtime_root=root, data_dir=root / "data", output_dir=root / "outputs"
    )
    store = JobStore(root / "jobs.db")
    return BrowserAgent(
        config, object(), ToolGateway(store, EventBus()), object(), object(), store, EventBus()
    )


def _try(
    url: str = "",
    ok: bool = True,
    tool: str = "browser_extract",
    arg_url: str = "",
) -> dict[str, Any]:
    """도구 한 걸음. 실패한 걸음에는 대개 결과가 없어서 evidence 가 빈다."""
    return {
        "step": 1,
        "tool": tool,
        "arguments": {"url": arg_url} if arg_url else {},
        "ok": ok,
        "status": "",
        "error": "",
        "evidence": {"url": url} if url else {},
    }


_GOAL = "크몽에서 외주 공고를 찾아서 예산을 정리해줘"

# 아래 배선 시험은 사이트 이름이 없는 요구를 쓴다. 요구에 "크몽"이 들어 있으면
# 7단계 대조(plan)가 "크몽을 못 봤다"를 답에 따로 적고, 그건 correction 이다 —
# 여기서 보려는 것은 **제안이 correction 이 아니라는 것**이라 섞이면 안 된다.
_PLAIN = "외주 공고 예산 좀 정리해줘"


# ── 못 읽은 곳을 고른다 ──────────────────────────────────────────────────────
def test_a_site_we_tried_and_never_read_is_counted() -> None:
    steps = [_try(tool="browser_open", arg_url="https://kmong.com/gig/123", ok=False)]
    assert BrowserAgent._unreadable_hosts(steps) == {"kmong.com": "https://kmong.com/gig/123"}


def test_a_site_we_eventually_read_is_not_counted() -> None:
    """세 번 두드려 결국 읽었으면 아픈 곳이 아니다.

    ★ 이게 오탐을 막는 핵심이다. 실패한 걸음을 그때그때 셌다면 여기서 2가 적히고,
    멀쩡히 읽히는 사이트가 며칠 뒤 "레시피 만들 때가 됐다"고 올라온다.
    """
    steps = [
        _try(tool="browser_open", arg_url="https://kmong.com/gig/123", ok=False),
        _try(tool="browser_extract", ok=False, arg_url="https://kmong.com/gig/123"),
        _try("https://kmong.com/gig/123"),
    ]
    assert BrowserAgent._unreadable_hosts(steps) == {}


def test_reading_a_different_page_of_the_same_site_counts_as_readable() -> None:
    """사이트 단위로 본다. 레시피도 사이트 단위로 쓰기 때문이다."""
    steps = [
        _try(tool="browser_extract", ok=False, arg_url="https://kmong.com/gig/1"),
        _try("https://kmong.com/gig/2"),
    ]
    assert BrowserAgent._unreadable_hosts(steps) == {}


def test_a_failed_search_page_is_not_a_sick_site() -> None:
    """검색이 막힌 것은 그 사이트 절차 문제가 아니다 — bot_check 로 따로 잡힌다."""
    steps = [_try(tool="browser_open", arg_url="https://search.naver.com/search.naver?q=x", ok=False)]
    assert BrowserAgent._unreadable_hosts(steps) == {}


def test_a_failure_without_a_url_falls_back_to_where_we_actually_are() -> None:
    """실패한 걸음에는 주소가 안 실려 온다. 그래도 어디서 막혔는지는 알아야 한다.

    브라우저는 직렬이라 마지막으로 확인된 위치가 지금 서 있는 곳이다. 여기서는
    목록(`browser_links`)이 크몽 페이지에서 성공했고 — 목록은 무엇이 있는지만
    알려 주지 무엇인지는 알려 주지 않으므로 읽은 것으로 치지 않는다 — 바로 다음
    본문 읽기가 주소도 없이 실패했다.
    """
    steps = [
        _try("https://kmong.com/gig/9", tool="browser_links"),
        _try(tool="browser_extract", ok=False),
    ]
    assert BrowserAgent._unreadable_hosts(steps) == {"kmong.com": ""}


def test_a_listing_tool_failing_is_not_an_unreadable_page() -> None:
    """목록·검색 도구가 실패한 것은 본문을 못 읽은 것과 다르다."""
    steps = [_try(tool="browser_links", ok=False, arg_url="https://kmong.com/list")]
    assert BrowserAgent._unreadable_hosts(steps) == {}


# ── 장부에 적고, 때가 되면 제안한다 ──────────────────────────────────────────
def test_the_ledger_now_records_pages_that_would_not_open() -> None:
    agent = _agent()
    steps = [_try(tool="browser_open", arg_url="https://kmong.com/gig/1", ok=False)]

    agent._note_unreadable_sites(_GOAL, steps)

    rows = agent.store.site_friction()
    assert len(rows) == 1
    assert rows[0]["host"] == "kmong.com"
    assert rows[0]["code"] == CONTENT_FRICTION_CODE
    assert rows[0]["last_url"] == "https://kmong.com/gig/1", "레시피를 만들 때 열어 볼 주소다"
    assert rows[0]["last_goal"] == _GOAL


def test_one_job_adds_one_hit_per_site() -> None:
    """한 잡 안에서 다섯 번 두드린 것과 다섯 날에 걸쳐 막힌 것은 전혀 다른 신호다."""
    agent = _agent()
    steps = [
        _try(tool="browser_open", arg_url="https://kmong.com/gig/1", ok=False),
        _try(tool="browser_extract", ok=False, arg_url="https://kmong.com/gig/1"),
        _try(tool="browser_extract", ok=False, arg_url="https://kmong.com/gig/2"),
    ]
    agent._note_unreadable_sites(_GOAL, steps)
    assert agent.store.site_friction()[0]["hits"] == 1


def test_the_third_job_that_could_not_read_asks_for_a_recipe() -> None:
    agent = _agent()
    steps = [_try(tool="browser_open", arg_url="https://kmong.com/gig/1", ok=False)]

    notes = [agent._note_unreadable_sites(_GOAL, steps) for _ in range(RECIPE_SUGGEST_AFTER)]

    assert notes[:-1] == [""] * (RECIPE_SUGGEST_AFTER - 1), "한 번은 사고, 두 번은 우연"
    assert "kmong.com" in notes[-1]
    assert "레시피" in notes[-1]


def test_only_one_recipe_is_suggested_at_a_time() -> None:
    """세 곳이 동시에 때가 됐다고 세 개를 붙이면 읽는 사람은 하나도 안 만든다."""
    agent = _agent()
    for host in ("kmong.com", "wishket.com"):
        for _ in range(RECIPE_SUGGEST_AFTER - 1):
            agent.store.note_site_friction(host=host, code=CONTENT_FRICTION_CODE)
    steps = [
        _try(tool="browser_open", arg_url="https://kmong.com/gig/1", ok=False),
        _try(tool="browser_open", arg_url="https://wishket.com/project/2", ok=False),
    ]

    note = agent._note_unreadable_sites(_GOAL, steps)

    assert note.count("💡") == 1
    assert "kmong.com" in note


def test_a_site_that_read_fine_leaves_the_ledger_alone() -> None:
    agent = _agent()
    agent._note_unreadable_sites(_GOAL, [_try("https://kmong.com/gig/1")])
    assert agent.store.site_friction() == []


# ── 배선 — 진짜 run() 을 지나야 적힌다 ──────────────────────────────────────
#
# 위의 시험들은 helper 를 직접 부른다. 그것만으로는 **불리기는 하는가**를 모른다.
# 이 저장소가 두 번 데인 자리다: 라벨은 맞는데 실제로는 아무도 안 부르는 코드,
# 캐시 플래그만 보고 살아 있다고 답하는 생존 검사. 그래서 아래는 잡을 만들어
# run() 을 끝까지 돌리고 장부를 본다.


class _OneSiteWontOpen:
    """크몽만 못 읽는 브라우저. 로그인도, 봇 확인도 아니다 — 그냥 안 열린다."""

    def execute(self, name: str, arguments: dict[str, Any], *, job_id: str = "") -> Any:
        from alture_jarvis.models import ToolResult

        url = str(arguments.get("url") or "")
        if "kmong.com" in url:
            return ToolResult(False, name, error="timeout: 본문을 읽지 못했습니다")
        return ToolResult(True, name, result={"url": url, "title": "공고", "text": "예산 300만원"})


class _OpensThenAnswers:
    """읽히는 곳 하나, 안 읽히는 곳 하나를 열어 보고 아는 것으로 답한다.

    한쪽을 읽어내게 두는 것이 중요하다. 아무것도 못 읽으면 답변에 "무엇도 열어
    보지 않고 썼다"는 **경고**가 붙어 버려서, 레시피 제안이 경고와 섞인다 —
    그러면 이 시험이 정작 보려는 것(제안은 경고가 아니다)을 못 본다.
    """

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        urls = ["https://wishket.com/project/1", "https://kmong.com/gig/1"]
        if self.calls <= len(urls):
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "browser_open", "arguments": {"url": urls[self.calls - 1]}}}
                ],
            }
        return {"role": "assistant", "content": "위시켓 공고 하나의 예산은 300만원입니다."}


class _OpenTools:
    names = {"browser_open"}
    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": "browser_open",
                "description": "open",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def _running_agent(tmp_path: Path) -> tuple[BrowserAgent, JobStore]:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    agent = BrowserAgent(
        config,
        _OpensThenAnswers(),
        _OneSiteWontOpen(),
        object(),
        _OpenTools(),
        store,
        EventBus(),
    )
    return agent, store


def test_a_real_run_that_could_not_read_reaches_the_ledger(tmp_path: Path) -> None:
    agent, store = _running_agent(tmp_path)
    job = store.create_job("chat", "agent", {"prompt": _PLAIN})["id"]

    result = agent.run(_PLAIN, job_id=job)

    rows = store.site_friction()
    assert rows and rows[0]["host"] == "kmong.com", "run() 을 지나도 장부에 적혀야 한다"
    assert rows[0]["code"] == CONTENT_FRICTION_CODE
    assert "💡" not in result.answer, "첫 번째는 사고다 — 아직 제안하지 않는다"


def test_the_third_real_run_puts_the_suggestion_in_the_answer(tmp_path: Path) -> None:
    """제안은 답변에 붙어야 한다. 장부에만 쌓이면 아무도 안 본다."""
    agent, store = _running_agent(tmp_path)
    for _ in range(RECIPE_SUGGEST_AFTER - 1):
        store.note_site_friction(host="kmong.com", code=CONTENT_FRICTION_CODE)
    job = store.create_job("chat", "agent", {"prompt": _PLAIN})["id"]

    result = agent.run(_PLAIN, job_id=job)

    assert "레시피" in result.answer
    assert "kmong.com" in result.answer
    # 답이 틀려서 붙은 말이 아니다. 이걸 섞으면 answer_corrected 가 뜻을 잃는다.
    assert result.verification["answer_corrected"] is False


# ── 막힌 종류에 따라 말이 달라야 한다 ────────────────────────────────────────
def test_an_unreadable_page_is_not_described_as_a_locked_door() -> None:
    """로그인 문과 안 읽히는 페이지는 손대는 곳이 완전히 다르다.

    같은 문구를 두 경우에 쓰면 한쪽은 반드시 어긋난다 — 로그인도 안 걸린 페이지를
    두고 "지금 막 뚫으셨으니 같이 보자"고 하면 무슨 말인지 알 수 없다.
    """
    note = suggest_recipe("kmong.com", RECIPE_SUGGEST_AFTER, code=CONTENT_FRICTION_CODE)
    assert "본문" in note
    assert "로그인이나 봇 확인이 아니라" in note

    gate = suggest_recipe("kmong.com", RECIPE_SUGGEST_AFTER)
    assert gate != note, "사람 문 문구가 그대로 재활용되면 안 된다"
