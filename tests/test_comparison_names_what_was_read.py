"""비교표의 경쟁사 칸을 **무엇을 읽고** 썼는지 밝힌다 (2026-09-29 실사용 · 잡 cceb296f).

인벤 기사 한 편(「DGX 스파크에서 상시 가동」)만 읽고 「헤르메스: 클라우드 연동 필요」라고 적었는데 경고가 0 이었다.
같은 질문을 공식 사이트를 읽고 답한 판(ddc1faee)에는 아무것도 붙지 않아야 한다.
"""
from __future__ import annotations

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore

ASKED = "우리랑 가장 겹치는 공개 에이전트 헤르메스를 직접 조사해서 우리가 나은 부분이랑 헤르메스의 장점을 말해주라"
TABLE = (
    "| 구분 | **온텔릭 (OnTellic)** | **헤르메스 (Hermes)** |\n"
    "| :--- | :--- | :--- |\n"
    "| **데이터 보안** | 완전 로컬 처리 | 클라우드 연동 필요 |\n"
    "| **개방성** | 아파치 2.0 | 주로 특정 클라우드 생태계 |\n"
)


class _Browser:
    def status(self):
        return {"started": True}


class _Tools:
    names: set[str] = set()
    ollama_tools: list = []


def _agent(tmp_path) -> BrowserAgent:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    return BrowserAgent(config, object(), object(), _Browser(), _Tools(), JobStore(tmp_path / "jobs.db"), EventBus())


def _read(step: int, url: str, title: str) -> dict:
    return {"ok": True, "step": step, "tool": "browser_extract", "evidence": {"url": url, "title": title},
            "evidence_record": {"type": "body_read", "ok": True, "source_id": url, "job_id": "j", "step": step}}


def _with_bodies(agent: BrowserAgent, bodies: dict[int, str]) -> None:
    ledger_of = agent._evidence_view

    def view(steps, job_id=""):
        ledger, _resolve, confirm = ledger_of(steps, job_id)
        return ledger, (lambda _job, step: bodies.get(step, "")), confirm

    agent._evidence_view = view  # type: ignore[method-assign]


def test_one_webzine_article_is_named_as_the_only_source(tmp_path) -> None:
    agent = _agent(tmp_path)
    _with_bodies(agent, {2: "자체 진화하는 AI 에이전트 헤르메스가 DGX 스파크에서 상시 가동된다."})
    steps = [_read(2, "https://www.inven.co.kr/webzine/news/?news=316456", "헤르메스, DGX 스파크에서 상시 가동 | 웹진 인벤")]
    note = agent._comparison_source_check(ASKED, TABLE, steps, "j")
    assert "헤르메스에 대해 읽은 자료는 www.inven.co.kr 한 곳뿐" in note
    assert "온텔릭" not in note.split("헤르메스", 1)[0], "우리 열은 보지 않는다"


def test_the_official_site_clears_it(tmp_path) -> None:
    agent = _agent(tmp_path)
    _with_bodies(agent, {3: "Hermes Agent runs in isolated sandboxes such as Docker or SSH."})
    steps = [_read(3, "https://hermes-agent.nousresearch.com/", "Hermes Agent")]
    assert agent._comparison_source_check(ASKED, TABLE, steps, "j") == ""


def test_two_independent_sources_clear_it(tmp_path) -> None:
    agent = _agent(tmp_path)
    _with_bodies(agent, {2: "헤르메스 에이전트 소개", 4: "Hermes agent review"})
    steps = [_read(2, "https://www.inven.co.kr/a", "a"), _read(4, "https://blog.example/b", "b")]
    assert agent._comparison_source_check(ASKED, TABLE, steps, "j") == ""


KMONG_TABLE = "| 구분 | **크몽 (Kmong)** | **위시캣 (Wishket)** |\n| --- | --- | --- |\n| 수수료 | 20% | 10% |\n"


def test_asked_to_look_but_read_nothing_says_so(tmp_path) -> None:
    agent = _agent(tmp_path)
    note = agent._comparison_source_check("크몽이랑 위시캣 한번 조사해서 차이 알려줘", KMONG_TABLE, [], "j")
    assert "크몽에 대해 이번에 읽은 자료가 없습니다" in note and "위시캣에 대해 이번에 읽은 자료가 없습니다" in note


def test_a_chat_question_answered_from_memory_is_left_alone(tmp_path) -> None:
    """역검증: 「젬마는 제미나이랑 머가 달라」 같은 잡담에 붙은 판이 절반이었다 — 읽으라고 안 시켰으면 안 붙인다."""
    agent = _agent(tmp_path)
    assert agent._comparison_source_check("크몽이랑 위시캣의 차이는 머고 단가 차이가 어마무시하던데", KMONG_TABLE, [], "j") == ""


def test_read_other_things_but_not_the_competitor_says_so(tmp_path) -> None:
    agent = _agent(tmp_path)
    _with_bodies(agent, {2: "위시캣 프로젝트 목록 — 예산 500만 원"})
    steps = [_read(2, "https://www.wishket.com/project/", "위시캣 프로젝트")]
    note = agent._comparison_source_check("크몽이랑 위시캣의 차이는 머고", KMONG_TABLE, steps, "j")
    assert "크몽에 대해 이번에 읽은 자료가 없습니다" in note
    assert "위시캣" not in note, "위시캣은 공식 사이트를 읽었다"


def test_an_unresolved_body_is_not_called_unread(tmp_path) -> None:
    agent = _agent(tmp_path)
    _with_bodies(agent, {})  # 보관소가 비었다 — 무엇을 읽었는지 모른다
    steps = [_read(2, "https://example.com/x", "무관한 제목")]
    assert agent._comparison_source_check(ASKED, TABLE, steps, "j") == ""


def test_tables_that_are_not_comparisons_of_named_things_are_left_alone(tmp_path) -> None:
    agent = _agent(tmp_path)
    rows = "| 순위 | 제목 | 가격 |\n| --- | --- | --- |\n| 1 | 파이썬 책 | 18,000원 |\n"
    assert agent._comparison_source_check("교보문고에서 파이썬 책 가격 비교해줘", rows, [], "j") == ""
    fields = "| 구분 | 마감일 | 자격 요건 |\n| --- | --- | --- |\n| A사 | 10.01 | 경력 3년 |\n"
    assert agent._comparison_source_check("회사명·마감일·자격 요건을 비교", fields, [], "j") == "", \
        "질문에 나온 열 이름이라도 항목 이름이면 — 이 판은 그 칸이 비교 대상 열이 아니다"
