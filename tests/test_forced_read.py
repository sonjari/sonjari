"""목록만 보고 상세를 안 열어 읽는 판을 **대신 열어 준다.**

## 왜 (2026-08-20 실측)

계획 대조가 장부에 기록되기 시작한 뒤의 판만 골라 보니, 미달 항목이 셋으로 갈렸다:

    count   3개 이상 직접 열어 읽기   4건   실제로 읽은 것 0·1·2·4개
    site    거기서 아무것도 안 함     5건   (로그인 벽 — 여기서 못 고친다)
    action  발행·임시저장·일정 등록    4건   → `_COMMIT_CHAINS` 가 맡는다

일감은 전부 같은 모양이었다: "다나와에서 무선마우스 **상위 3개** 제품명과 가격",
"사람인에서 채용공고 **3개**의 제목과 회사명". 목록 화면까지는 갔고, 거기서
**상세를 안 열었다.**

프롬프트에 `_OPEN_THE_BODY_HINT` 가 있고 되받기도 그 문장을 붙여 보낸다. 그런데
사고 R 실측에서 상세를 165번 열고 그 페이지에서 스크롤한 것이 1번이었다 —
**안내문은 안 먹는다.**

## 이 검사가 지키는 것

**지어내지 않는다.** `browser_open_result` 의 인자는 `rank` 하나이고 그 순위는
도구가 스스로 만든 목록에서만 유효하다. `browser_extract` 는 인자가 아예 없다.
그 사실이 깨지면(도구가 셀렉터나 주소를 받기 시작하면) 이 검사가 그 자리에서
깨져야 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.agent import (
    _EXTRACT_TOOL,
    _FORCED_READ_LIMIT,
    _OPEN_RESULT_TOOL,
    _forced_read_call,
)
from alture_jarvis.browser import BrowserTools
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.plan import Requirement


def _step(tool: str, ok: bool = True, **arguments: Any) -> dict[str, Any]:
    return {
        "step": 1,
        "tool": tool,
        "arguments": dict(arguments),
        "ok": ok,
        "status": "",
        "error": "",
        "evidence": {},
    }


def _need(target: int = 3) -> list[tuple[Requirement, bool, str]]:
    return [(Requirement("count", f"{target}개 이상 직접 열어 읽기", target), False, "0개 읽음")]


def _met() -> list[tuple[Requirement, bool, str]]:
    # 실제 요청(「사람인 공고 3개를 찾아줘」)에서 뽑히는 모양 그대로 — 읽어야 채워지는 개수다(`grounding_required`).
    # 2026-10-10 까지 이 본보기는 그 표시 없이 만들어져 있었다. 판정이 그 표시를 보게 되면서 맞췄다.
    return [(Requirement("count", "3개 이상 직접 열어 읽기", 3, grounding_required=True), True, "3개 읽음")]


# ── 지어내지 않는다 ──────────────────────────────────────────────────────────


def test_the_pushed_tools_take_nothing_a_model_could_invent() -> None:
    """★ 이 검사가 이 파일의 존재 이유다.

    도구 스키마를 실제로 읽는다. `browser_open_result` 가 rank 말고 다른 것을
    받기 시작하거나, `browser_extract` 에 필수 인자가 생기면 **여기서 깨진다** —
    그때는 대신 부르는 것이 지어내기가 되기 때문이다.
    """
    tools = BrowserTools(JarvisConfig(runtime_root=Path(".")), EventBus())
    schemas = {
        str(d["function"]["name"]): d["function"].get("parameters") or {}
        for d in tools._definitions
    }

    open_params = schemas[_OPEN_RESULT_TOOL]
    # 2026-10-15: 선택 칸 `title`(모델이 목록에서 본 제목으로 지목)이 생겼다. 대신 부를 때는 지금처럼 rank 만 넣는다 —
    #   지킬 것은 「rank 말고 **꼭 넣어야 하는** 칸이 없다」이다(선택 칸은 비워 두면 되니 지어낼 것이 없다).
    assert (open_params.get("required") or []) == ["rank"], (
        "browser_open_result 가 rank 말고 다른 필수 칸을 받는다 — 대신 부르면 지어내기가 된다"
    )
    assert (open_params.get("properties") or {})["rank"]["type"] == "integer"

    extract_params = schemas[_EXTRACT_TOOL]
    assert not (extract_params.get("required") or []), (
        "browser_extract 에 필수 인자가 생겼다 — 빈 인자로 대신 부를 수 없다"
    )


def test_we_only_ever_push_those_two_tools() -> None:
    """다른 도구가 튀어나오면 인자를 지어내고 있다는 뜻이다."""
    seen = set()
    for steps in (
        [],
        [_step(_OPEN_RESULT_TOOL, rank=1)],
        [_step(_OPEN_RESULT_TOOL, rank=1), _step(_EXTRACT_TOOL)],
    ):
        pushed = _forced_read_call(_need(), steps)
        if pushed:
            seen.add(pushed[0])
    assert seen <= {_OPEN_RESULT_TOOL, _EXTRACT_TOOL}


# ── 언제 밀고 언제 안 미는가 ─────────────────────────────────────────────────


def test_nothing_is_pushed_when_the_count_is_already_met() -> None:
    assert _forced_read_call(_met(), [_step(_OPEN_RESULT_TOOL, rank=1)]) is None


def test_nothing_is_pushed_when_there_is_no_count_requirement() -> None:
    """행위 요구만 남은 판은 커밋 사슬이 맡는다. 여기가 끼어들면 안 된다."""
    action_only = [(Requirement("action", "임시저장", "naver_blog_save_draft"), False, "실행 안 됨")]
    assert _forced_read_call(action_only, [_step("naver_blog_prepare_post")]) is None


def test_a_site_requirement_alone_is_not_our_business() -> None:
    """로그인 벽은 상세를 열어서 뚫리는 것이 아니다."""
    site_only = [(Requirement("site", "네이버에서 하기", ("naver.com",)), False, "거기서 아무것도 안 함")]
    assert _forced_read_call(site_only, []) is None


def test_the_first_push_opens_the_first_result() -> None:
    assert _forced_read_call(_need(), []) == (_OPEN_RESULT_TOOL, {"rank": 1})


def test_opening_is_followed_by_reading_not_by_opening_again() -> None:
    """★ 열어 놓고 본문을 안 받으면 `_sources_actually_read` 가 세지 않는다.

    이 순서가 뒤집히면 "열기만 반복하고 개수는 그대로"인 판이 된다.
    """
    steps = [_step(_OPEN_RESULT_TOOL, rank=1)]
    assert _forced_read_call(_need(), steps) == (_EXTRACT_TOOL, {})


def test_after_reading_we_move_on_to_the_next_rank() -> None:
    steps = [_step(_OPEN_RESULT_TOOL, rank=1), _step(_EXTRACT_TOOL)]
    assert _forced_read_call(_need(), steps) == (_OPEN_RESULT_TOOL, {"rank": 2})


def test_ranks_the_model_already_opened_are_skipped() -> None:
    """모델이 스스로 1·2를 열었으면 우리는 3부터 민다."""
    steps = [
        _step(_OPEN_RESULT_TOOL, rank=1),
        _step(_EXTRACT_TOOL),
        _step(_OPEN_RESULT_TOOL, rank=2),
        _step(_EXTRACT_TOOL),
    ]
    assert _forced_read_call(_need(), steps) == (_OPEN_RESULT_TOOL, {"rank": 3})


def test_a_read_by_any_text_tool_counts_not_just_extract() -> None:
    """`browser_read` 로 읽었으면 그것도 읽은 것이다 — 다시 읽으라고 밀지 않는다."""
    steps = [_step(_OPEN_RESULT_TOOL, rank=1), _step("browser_read")]
    assert _forced_read_call(_need(), steps) == (_OPEN_RESULT_TOOL, {"rank": 2})


# ── 실패한 것은 대신 밀지 않는다 (커밋 쪽과 같은 규칙) ────────────────────────


def test_one_refused_open_stops_us_entirely() -> None:
    """★ 목록이 없는 화면이면 `no_result_list` 가 온다. 같은 것을 다시 밀어 봐야
    같은 실패고, 걸음만 태운다. 커밋 쪽 `attempted` 규칙과 같다."""
    steps = [_step(_OPEN_RESULT_TOOL, ok=False, rank=1)]
    assert _forced_read_call(_need(), steps) is None


def test_a_refused_open_stops_us_even_after_earlier_successes() -> None:
    steps = [
        _step(_OPEN_RESULT_TOOL, rank=1),
        _step(_EXTRACT_TOOL),
        _step(_OPEN_RESULT_TOOL, ok=False, rank=2),
    ]
    assert _forced_read_call(_need(), steps) is None


def test_a_failed_extract_is_not_retried() -> None:
    """본문이 안 잡히는 페이지를 계속 긁어 봐야 같은 실패다."""
    steps = [_step(_OPEN_RESULT_TOOL, rank=1), _step(_EXTRACT_TOOL, ok=False)]
    assert _forced_read_call(_need(), steps) is None


def test_there_is_a_ceiling_on_how_many_we_push() -> None:
    """상한이 없으면 안 열리는 목록에서 걸음을 통째로 태운다."""
    assert 0 < _FORCED_READ_LIMIT <= 12


# ── 배선이 실제로 물려 있는가 ─────────────────────────────────────────────────
#
# ★ 위 검사들은 판정 함수만 본다. 이 저장소는 "도구는 순서에 없으면 안 쓰인다"를
#   여러 번 겪었다 — 함수는 맞는데 아무도 안 부르는 것이 제일 안 보인다.
#   그래서 루프를 통째로 돌려 **실제로 세 건을 읽는지** 본다.

from alture_jarvis.agent import BrowserAgent  # noqa: E402
from alture_jarvis.jobs import JobStore  # noqa: E402
from alture_jarvis.models import ToolResult  # noqa: E402

_LIST_TOOLS = ("browser_site_search", _OPEN_RESULT_TOOL, _EXTRACT_TOOL)


class _ListThenDetails:
    """진짜 목록처럼 군다 — rank 마다 다른 상세 주소를 돌려준다.

    `_sources_actually_read` 는 **서로 다른 주소**를 셀 때만 개수가 오르므로,
    같은 주소를 계속 주면 이 검사는 통과할 수 없다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._rank = 0

    def execute(self, name: str, arguments: dict[str, Any], *, job_id: str = "") -> ToolResult:
        self.calls.append((name, dict(arguments)))
        if name == _OPEN_RESULT_TOOL:
            self._rank = int(arguments.get("rank") or 0)
            return ToolResult(
                True,
                name,
                result={"url": f"https://danawa.com/item/{self._rank}", "title": f"마우스 {self._rank}"},
            )
        if name == _EXTRACT_TOOL:
            return ToolResult(
                True,
                name,
                result={
                    "url": f"https://danawa.com/item/{self._rank}",
                    "title": f"마우스 {self._rank}",
                    "text": f"마우스 {self._rank} · 가격 {self._rank}0,000원",
                },
            )
        return ToolResult(True, name, result={"url": "https://danawa.com/list", "title": "목록"})


class _AnswersFromTheListing:
    """실측한 모델 그대로 — 목록 한 번 보고, 그 뒤로는 상세를 안 열고 답한다."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "browser_site_search", "arguments": {"query": "무선마우스"}}}
                ],
            }
        return {"role": "assistant", "content": "목록에서 확인한 상위 3개는 다음과 같습니다."}


class _FakeBrowser:
    def status(self) -> dict[str, Any]:
        return {"started": True}


class _FakeTools:
    names = set(_LIST_TOOLS)
    ollama_tools = [
        {
            "type": "function",
            "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}},
        }
        for name in _LIST_TOOLS
    ]


def test_the_loop_actually_opens_the_details(tmp_path: Path) -> None:
    """목록만 보고 답하는 모델을 두고도 **상세 세 건이 실제로 읽힌다.**

    이것이 안 되면 이 기능은 없는 것이다. 실측 판(다나와·쿠팡·사람인)이 정확히
    이 모양이었고, 그때는 "0개 읽음"으로 끝났다.
    """
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _ListThenDetails()
    agent = BrowserAgent(
        config, _AnswersFromTheListing(), gateway, _FakeBrowser(), _FakeTools(), store, EventBus()
    )
    prompt = "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘"
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()

    result = agent.run(prompt, job_id=job["id"], origin="chat")

    opened = sorted(
        int(a.get("rank") or 0) for n, a in gateway.calls if n == _OPEN_RESULT_TOOL
    )
    assert opened[:3] == [1, 2, 3], f"상세를 안 열었다: {gateway.calls}"
    assert result.verification["forced_reads"] >= 1
    # 열기만 하고 본문을 안 받으면 개수가 안 오른다 — 짝이 맞아야 한다.
    extracts = [n for n, _ in gateway.calls if n == _EXTRACT_TOOL]
    assert len(extracts) >= 3


def test_the_ledger_records_how_often_we_had_to_push(tmp_path: Path) -> None:
    """★ 안 남기면 이 기능이 도는지 아무도 못 잰다 — 되받기가 정확히 그랬다.
    이 값이 **줄어드는 것**이 모델 쪽이 나아지고 있다는 신호다."""
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    agent = BrowserAgent(
        config, _AnswersFromTheListing(), _ListThenDetails(), _FakeBrowser(), _FakeTools(), store, EventBus()
    )
    job = store.create_job("chat", "agent", {"prompt": "x"})
    store.claim_next()
    result = agent.run("다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘", job_id=job["id"], origin="chat")
    assert "forced_reads" in result.verification


def test_the_grace_is_big_enough_for_one_more_item_and_no_more() -> None:
    """★ 이 값이 없어서 라이브에서 답이 미완성으로 나갔다 (2026-08-20 다나와).

    3개 중 2개만 읽고 끝났는데 `forced_reads` 가 0이었다. 판정 함수는 rank 2 를
    내놓고 있었고, 거른 것은 예산 한 줄이었다 — `elapsed_sec 181.27` · 예산 180초.
    **1.27초가 모자랐다.**

    실측(3일·50판): 걸음당 중앙 13.3초 · 90p 25.0초 → 열기+읽기 한 쌍 27초/50초.
    유예는 그 한 쌍이 들어갈 만큼이어야 하고, 예산이 뜻을 잃을 만큼이면 안 된다.
    """
    from alture_jarvis.agent import _FORCED_READ_GRACE_SEC

    assert 50 <= _FORCED_READ_GRACE_SEC <= 120


# ── 계획과 답이 다투면 정직한 쪽을 따른다 ────────────────────────────────────
#
# ★ 2026-08-20 라이브(다나와). 계획은 충족, 답은 미달이라고 말했다:
#
#     계획   3개 이상 직접 열어 읽기 = 3개 읽음 (충족)
#     답     "현재까지 총 1개의 자료를 직접 읽었습니다. (1. 브랜드로그)
#             … 아까 확인한 검색 결과 목록의 정보를 바탕으로 정리해 드립니다"
#
# rank 1·2·3 을 열었는데 둘이 상품 상세가 아니라 브랜드 소개 페이지였다. 계획은
# "서로 다른 주소 셋"만 세므로 충족으로 봤다. **정직한 쪽은 답이었다.**
#
# 그리고 이때 강제 읽기가 **안 걸렸다** — 계획이 충족이라고 했기 때문이다. 자비스
# 자신은 알고 있었는데 그 판단이 강제 장치까지 전달이 안 됐다.


def test_the_answers_own_admission_reopens_a_met_requirement() -> None:
    """계획이 충족이라 해도 답이 모자라다고 하면 한 칸 더 연다."""
    met = _met()
    steps = [
        _step(_OPEN_RESULT_TOOL, rank=1),
        _step(_EXTRACT_TOOL),
        _step(_OPEN_RESULT_TOOL, rank=2),
        _step(_EXTRACT_TOOL),
        _step(_OPEN_RESULT_TOOL, rank=3),
        _step(_EXTRACT_TOOL),
    ]
    assert _forced_read_call(met, steps) is None, "고치기 전 동작이 남아 있다"
    assert _forced_read_call(met, steps, answer_admits_shortfall=True) == (
        _OPEN_RESULT_TOOL,
        {"rank": 4},
    )


def test_it_opens_a_new_rank_so_it_cannot_loop_in_place() -> None:
    """무한히 돌지 않는 근거 둘 중 하나 — 매번 **새 순위**를 연다."""
    met = _met()
    steps = [_step(_OPEN_RESULT_TOOL, rank=n) for n in (1, 2, 3, 5)]
    steps.append(_step(_EXTRACT_TOOL))
    assert _forced_read_call(met, steps, answer_admits_shortfall=True) == (
        _OPEN_RESULT_TOOL,
        {"rank": 4},
    )


def test_an_admission_without_a_count_requirement_changes_nothing() -> None:
    """★ 개수를 안 시킨 판에서 "다 못 했다"는 말이 상세 열기를 부르면 안 된다."""
    action_only = [(Requirement("action", "임시저장", "naver_blog_save_draft"), False, "실행 안 됨")]
    assert _forced_read_call(action_only, [], answer_admits_shortfall=True) is None


def test_a_refused_open_still_stops_us_even_when_the_answer_admits() -> None:
    """정직한 답이 있어도 **안 되는 것을 다시 밀지는 않는다.**"""
    steps = [_step(_OPEN_RESULT_TOOL, ok=False, rank=1)]
    assert _forced_read_call(_met(), steps, answer_admits_shortfall=True) is None


def test_the_detector_reads_the_danawa_answer_as_a_shortfall() -> None:
    """★ 실제로 그날 나온 문장으로 확인한다 — 판정기가 이 말을 못 알아들으면
    위의 배선이 전부 헛돈다."""
    from alture_jarvis.agent import BrowserAgent

    answer = (
        "1번째 자료(브랜드로그)를 읽었습니다. 이 페이지는 특정 제품의 상세 정보가 아닌, "
        "브라보텍 브랜드의 주요 제품군의 평균가와 최저가를 보여주는 브랜드 소개 페이지입니다. "
        "현재까지 총 1개의 자료를 직접 읽었습니다. (1. 브랜드로그) "
        "요청하신 '무선마우스 상위 3개 제품명과 가격'에 대한 답변을 드리기 위해, "
        "아까 확인한 검색 결과 목록의 정보를 바탕으로 다시 정리해 드립니다."
    )
    assert BrowserAgent._answer_reports_shortfall(answer, _met()) is True


def test_a_confident_complete_answer_is_not_read_as_a_shortfall() -> None:
    """반대쪽 표본. 게이트는 좋은 표본으로도 역검증해야 한다 —
    이 저장소가 하루에 두 번 오탐을 낸 적이 있다."""
    from alture_jarvis.agent import BrowserAgent

    answer = "다나와에서 무선마우스 상위 3개를 직접 열어 확인했습니다. 1) A 2) B 3) C"
    assert BrowserAgent._answer_reports_shortfall(answer, _met()) is False


class _ReadsThenAdmitsItFellShort:
    """실측한 다나와 판 그대로 — 상세를 열긴 열고, **스스로 모자라다고 말한다.**

    계획 대조는 「서로 다른 주소 셋」을 세어 충족이라 하고, 답은 「1개만 읽었다」고
    한다. 고치기 전에는 이 판에서 강제 읽기가 **한 번도 안 걸렸다.**
    """

    def __init__(self) -> None:
        self.calls = 0

    def chat_messages(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= 3:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": _OPEN_RESULT_TOOL, "arguments": {"rank": self.calls}}},
                ],
            }
        return {
            "role": "assistant",
            "content": (
                "1번째 자료(브랜드로그)를 읽었습니다. 상품 상세가 아니라 브랜드 소개 페이지입니다. "
                "현재까지 총 1개의 자료를 직접 읽었습니다. (1. 브랜드로그) "
                "아까 확인한 검색 결과 목록의 정보를 바탕으로 정리해 드립니다."
            ),
        }


def test_the_loop_reopens_when_the_answer_admits_it_fell_short(tmp_path: Path) -> None:
    """★ 배선까지 확인한다. 계획이 충족이라고 해도, 답이 모자라다고 하면 더 연다.

    고치기 전 실측(다나와 2026-08-20): `forced_reads` 0 · 답은 "1개만 읽었다".
    """
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        browser_enabled=True,
        browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    gateway = _ListThenDetails()
    agent = BrowserAgent(
        config, _ReadsThenAdmitsItFellShort(), gateway, _FakeBrowser(), _FakeTools(), store, EventBus()
    )
    prompt = "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘"
    job = store.create_job("chat", "agent", {"prompt": prompt})
    store.claim_next()

    result = agent.run(prompt, job_id=job["id"], origin="chat")

    assert result.verification["forced_reads"] > 0, "정직한 답을 듣고도 더 안 열었다"
    opened = sorted(
        int(a.get("rank") or 0) for n, a in gateway.calls if n == _OPEN_RESULT_TOOL
    )
    assert max(opened) > 3, f"이미 연 순위만 되풀이했다: {opened}"
    # 끝나기는 끝나야 한다 — 상한이 없으면 안 열리는 목록에서 걸음을 통째로 태운다.
    assert result.verification["forced_reads"] <= _FORCED_READ_LIMIT


# ── 정직한 미달과 거짓 미달을 가른다 ─────────────────────────────────────────
#
# ★ 둘은 겉으로 똑같이 보인다. 처방이 정반대다.
#
#   다나와  주소 셋을 읽었지만 둘이 브랜드 소개 페이지였다.
#           "1개만 읽었다" 는 **사실** → 더 읽어야 한다
#   사람인  제대로 셋을 읽고도 "세 번째 상세 정보 추출에 실패" 라고 적었다.
#           **거짓** → 답을 장부로 다시 쓰는 것이 맞다(재합성이 이미 그 일을 한다)
#
# 이 구별을 잃으면 둘 중 하나가 반드시 깨진다. 실제로 이 구별을 안 넣었을 때
# `test_agent.py` 의 사람인 재합성 검사가 그 자리에서 깨졌다.


def test_a_truthful_shortfall_and_a_false_one_are_told_apart() -> None:
    from alture_jarvis.agent import BrowserAgent

    met = _met()
    clean_steps = [
        {
            "tool": _EXTRACT_TOOL,
            "ok": True,
            "arguments": {},
            "evidence": {"url": f"https://x/{i}"},
            "status": "",
            "error": "",
        }
        for i in (1, 2, 3)
    ]
    prompt = "무선마우스 상위 3개 알려줘"

    truthful = (
        "이 페이지는 상품 상세가 아닌 브랜드 소개 페이지입니다. "
        "현재까지 총 1개의 자료를 직접 읽었습니다. (1. 브랜드로그)"
    )
    a_lie = "2개를 확인했습니다. 세 번째 상세 정보 추출에 실패했습니다."

    # 둘 다 "모자라다"고 말한다 — 여기까지는 구별이 안 된다.
    assert BrowserAgent._answer_reports_shortfall(truthful, met) is True
    assert BrowserAgent._answer_reports_shortfall(a_lie, met) is True

    # 가르는 것은 **장부와 모순되는가**다.
    assert not BrowserAgent._answer_trace_conflict(prompt, truthful, clean_steps, met)
    assert BrowserAgent._answer_trace_conflict(prompt, a_lie, clean_steps, met)


def test_a_lying_answer_must_not_trigger_more_reading() -> None:
    """이미 있는 것을 또 읽을 뿐이다. 그 판은 답을 고치는 것이 맞다."""
    from alture_jarvis.agent import BrowserAgent

    met = _met()
    clean_steps = [
        {
            "tool": _EXTRACT_TOOL,
            "ok": True,
            "arguments": {},
            "evidence": {"url": f"https://x/{i}"},
            "status": "",
            "error": "",
        }
        for i in (1, 2, 3)
    ]
    a_lie = "2개를 확인했습니다. 세 번째 상세 정보 추출에 실패했습니다."
    admits = bool(
        BrowserAgent._answer_reports_shortfall(a_lie, met)
        and not BrowserAgent._answer_trace_conflict("무선마우스 상위 3개", a_lie, clean_steps, met)
    )
    assert admits is False
    assert _forced_read_call(met, clean_steps, answer_admits_shortfall=admits) is None
