"""값의 출처를 사이트 페이지로 묶은 요청 = 찾은 항목마다 그 페이지 읽기 · 목록 화면 한 장으로는 「거기서 했다」가 아니다 (2026-11-14).

맥 판 cc505ece: 「별 수와 라이선스는 깃허브 페이지에서 직접 읽은 값만 쓰고」 + 돌려받을 항목에 별 수 · 라이선스. 대조표에 그 읽기 칸이
없고 「깃허브에서 하기」는 검색 목록 한 장으로 찼다 → 저장소 하나 읽고 「목표 달성」→ 파일 차례에서 둘째 저장소 열기가 not_this_stage.
역검증: 운영 요청 3,397개에 옛 · 새 뽑기를 대 바뀐 것 1개(이 판). 끝 판정 · 판 도중 「그만해도 됨」 걸음 대조는 전문 노트에.
"""
from __future__ import annotations

from alture_jarvis import plan

TASK_CC505ECE = (
    "블렌더(Blender)를 AI·자동화로 다루는 도구 조사: 깃허브와 레딧(r/blender, r/blenderhelp, r/gamedev, r/ClaudeAI)에서 2025~2026년에 "
    "평이 좋은 블렌더 MCP 서버·블렌더용 AI 애드온·파이썬 자동화 도구(리토폴로지·UV·리깅·게임용 최적화·에셋 점검)를 찾아, 이름·깃허브 주소·"
    "별 수·라이선스·마지막 업데이트·무엇을 하는지·사람들 평(좋은 점·불만)을 엑셀 표 하나로 정리해 줘. 별 수와 라이선스는 깃허브 페이지에서 "
    "직접 읽은 값만 쓰고, 못 읽었으면 빈칸으로 둬.\n\n(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 "
    "주세요: 이름 · 깃허브 주소 · 별 수 · 라이선스 · 마지막 업데이트 · 하는 일 · 평)"
)
TASK_E4A69E06 = (
    "앤트로픽의 새 모델 「Claude Fable 5.2」가 어느 정도 성능인지 조사해 줘. 앤트로픽 공식 발표·모델 소개 페이지·시스템 카드에서 벤치마크 "
    "숫자(코딩·에이전트·추론·시각 등)를 Claude Opus 5.5 와 나란히 읽고, 레딧(r/ClaudeAI, r/ClaudeCode, r/LocalLLaMA)과 X·블로그에서 실제로 "
    "써 본 사람들의 평(특히 게임·3D·블렌더·디테일 작업, 설계 품질, 속도, 가격·한도)을 모아 워드 문서 하나로 정리해 줘. 숫자는 페이지에서 "
    "직접 읽은 것만 쓰고 출처 주소를 줄마다 붙이고, 못 찾은 것은 「못 찾음」으로 적어.\n\n(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 "
    "어디에 쓰든 이 이름을 그대로 붙여 주세요: 벤치마크 비교 · 가격 · 사용자 평 · 게임·3D 작업 평 · 출처)"
)
PER_ITEM = "깃허브 페이지에서 찾은 항목마다 직접 열어 읽기(최대 10개)"


def _plan(text: str) -> list[plan.Requirement]:
    return plan.extract(text, must_observe=True, observe_from=("web",), has_named_source=True)


def _step(tool: str, url: str, **evidence: object) -> dict:
    return {"tool": tool, "ok": True, "arguments": {}, "evidence": {"url": url, **evidence}}


SEARCH = "https://github.com/search?q=blender+mcp&type=repositories&s=stars&o=desc"


def _listing_steps() -> list[dict]:
    return [
        _step("browser_open", SEARCH, action="site_searched", result_count=11),
        _step("browser_extract", SEARCH, remaining=[str(n) for n in range(1, 12)], read_so_far=0),
    ]


def _read_repo(name: str) -> list[dict]:
    url = f"https://github.com/{name}"
    return [_step("browser_open_result", url, action="opened_result"), _step("browser_extract", url)]


def _sources(steps: list[dict]) -> list[str]:
    return list(dict.fromkeys(s["evidence"]["url"] for s in steps if s["tool"] == "browser_extract"))


def _result(reqs: list[plan.Requirement], steps: list[dict], label: str, answer: str = "") -> tuple:
    return next(r for r in plan.check(reqs, sources=_sources(steps), steps=steps, answer=answer) if r[0].label == label)


# ── 뽑기 ──────────────────────────────────────────────────────────────────────

def test_values_bound_to_the_github_page_become_a_per_item_read() -> None:
    reqs = _plan(TASK_CC505ECE)
    count = next(r for r in reqs if r.kind == "count")
    assert (count.label, count.grade, count.origin, count.per_item_hosts) == (PER_ITEM, "firm", "ask", ("github.com",))
    assert count.target == plan._PER_ITEM_READ_CAP and count.grounding_required
    # 확실한 읽기 개수가 「근거 읽기」의 일을 한다(예비는 빠진다 — 예전 개수 요구와 같은 규칙).
    assert not any(r.kind == "observe" for r in reqs)


def test_a_source_rule_without_a_named_site_is_not_a_per_item_read() -> None:
    """맥 판 e4a69e06 「숫자는 페이지에서 직접 읽은 것만」 — 곳을 안 댄 출처 규칙이다. 그 판이 막힌 뿌리는 이 칸이 아니다(노트)."""
    assert not any(r.per_item_hosts for r in _plan(TASK_E4A69E06))


def test_counter_examples_of_directly_read_do_not_make_the_read() -> None:
    # 묶인 값이 돌려받을 항목에 없다(그 말 안에만 나온다).
    alone = "깃허브에서 블렌더 MCP 서버를 찾아 이름과 주소를 표로 정리해 줘. 별 수는 깃허브 페이지에서 직접 읽은 값만 써."
    # 「직접 읽은」이 사람이 읽은 것 · 페이지 출처가 아님.
    mine = "깃허브에서 블렌더 MCP 서버를 찾아 이름·별 수를 표로 정리해 줘. 별 수는 내가 직접 읽은 것만 믿으니 참고만 해."
    # 곳을 안 댄 「상세 페이지」(사이트가 셋) — 개수 · 곳마다 규칙이 맡을 일이다.
    shops = ("다나와, 11번가, G마켓에서 각각 상품 하나씩 찾아 가게 이름·판매 가격·배송비를 표로 정리해 줘. "
             "가격이나 배송비를 상품 상세 페이지에서 직접 읽은 값만 쓰고, 추정하지 마.")
    # 이미 개수를 댔으면 그 개수가 읽을 수를 쥔다 — 두 줄로 세우지 않는다.
    counted = ("깃허브에서 블렌더 MCP 저장소 5개를 찾아 이름·별 수·라이선스를 표로 정리해 줘. "
               "별 수와 라이선스는 깃허브 페이지에서 직접 읽은 값만 써.")
    for text in (alone, mine, shops):
        assert not any(r.per_item_hosts for r in _plan(text)), text
    labels = [r.label for r in _plan(counted) if r.kind == "count"]
    assert labels and PER_ITEM not in labels


# ── 대조 ──────────────────────────────────────────────────────────────────────

def test_per_item_goal_comes_from_the_listing_and_one_repo_is_not_enough() -> None:
    reqs = plan.firm_only(_plan(TASK_CC505ECE))
    req, ok, saw = _result(reqs, [], PER_ITEM)
    assert (req.target, ok) == (1, False) and "아직 목록을 못 봄" in saw
    steps = _listing_steps() + _read_repo("ahujasid/mcp-for-blender") + _read_repo("ahujasid/mcp-for-blender/blob/main/LICENSE")
    req, ok, saw = _result(reqs, steps, PER_ITEM)
    # 목록 11개 → 상한 10. 저장소 아래 LICENSE 는 같은 항목이다 — 1개.
    assert (req.target, ok) == (10, False) and saw.startswith("1개 읽음")
    # 판 도중 「그만해도 됨」이 안 선다 → 목표 달성 · 파일 차례로 넘어가지 않는다(cc505ece 의 뿌리).
    assert not plan.enough_to_stop(plan.check(reqs, sources=_sources(steps), steps=steps))
    for n in range(2, 11):
        steps += _read_repo(f"owner{n}/repo{n}")
    req, ok, _saw = _result(reqs, steps, PER_ITEM)
    assert ok and req.target == 10


def test_per_item_goal_shrinks_to_the_rows_the_answer_holds() -> None:
    reqs = plan.firm_only(_plan(TASK_CC505ECE))
    steps = _listing_steps() + [s for n in range(1, 4) for s in _read_repo(f"owner{n}/repo{n}")]
    answer = "| 이름 | 별 수 |\n|---|---|\n| a | 1 |\n| b | 2 |\n| c | 3 |\n"
    req, ok, _saw = _result(reqs, steps, PER_ITEM, answer=answer)
    assert (req.target, ok) == (3, True)


def test_a_search_listing_alone_does_not_fill_the_site() -> None:
    reqs = plan.firm_only(_plan(TASK_CC505ECE))
    req, ok, saw = _result(reqs, _listing_steps(), "깃허브에서 하기")
    assert not ok and "목록 화면" in saw
    _req, ok, _saw = _result(reqs, _listing_steps() + _read_repo("ahujasid/mcp-for-blender"), "깃허브에서 하기")
    assert ok


def test_when_the_listing_is_the_answer_the_listing_fills_the_site() -> None:
    """반례: 목록이 곧 답인 요청(상위 N개의 이름 · 별 수)은 예전처럼 목록 한 장으로 찬다."""
    text = "깃허브에서 블렌더 MCP 저장소를 별 순으로 검색해 상위 5개의 이름과 별 수를 알려 줘."
    reqs = plan.firm_only(_plan(text))
    site = next(r for r in reqs if r.kind == "site")
    assert site.list_only
    _req, ok, _saw = _result(reqs, _listing_steps(), "깃허브에서 하기")
    assert ok


def test_a_search_engine_named_as_the_place_is_still_filled_by_its_results() -> None:
    """반례: 「네이버에서 찾아」의 네이버는 검색엔진이다 — 결과 목록으로 찬다(예전 그대로)."""
    reqs = [plan.Requirement("site", "네이버에서 하기", ("naver.com",))]
    url = "https://search.naver.com/search.naver?query=x"
    steps = [_step("browser_search", url), _step("browser_extract", url)]
    assert plan.check(reqs, sources=[url], steps=steps)[0][1]


def test_a_price_comparison_answered_in_the_reply_body_is_filled_by_the_listing() -> None:
    """역검증에서 나온 헛걸림: 「답 본문에 표로」의 「본문」은 내 답 글이다 — 목록이 곧 답인 가격 비교는 예전처럼 목록으로 찬다."""
    text = "11번가와 다나와에서 「쿠첸 전기밥솥 6인용」 판매 가격과 배송비를 찾아 가게마다 한 줄씩 답 본문에 표로 적어 줘"
    reqs = plan.firm_only(_plan(text))
    url = "https://search.11st.co.kr/Search.tmall?kwd=x"
    steps = [_step("browser_site_search", url), _step("browser_extract", url)]
    result = next(r for r in plan.check(reqs, sources=[url], steps=steps) if r[0].label == "11번가에서 하기")
    assert result[1], result[2]


def test_a_post_opened_from_results_stays_an_item_after_loading_more_comments() -> None:
    """역검증에서 나온 헛걸림(운영 판 10bd9bac): 구글 결과로 연 레딧 글에서 댓글을 더 불러온 화면은 목록이 아니다."""
    text = "레딧에서 우리 글을 찾아 열고 댓글을 최대한 많이 읽어 댓글 원문 요지와 작성자를 마크다운 문서로 정리해 줘."
    reqs = plan.firm_only(_plan(text))
    post = "https://www.reddit.com/r/ollama/comments/1wopx15/post/"
    steps = [
        _step("browser_search", "https://www.google.com/search?q=x"),
        _step("browser_open_result", post), _step("browser_extract", post), _step("browser_load_more", post),
        _step("browser_read", post),
    ]
    result = next(r for r in plan.check(reqs, sources=[post], steps=steps) if r[0].label == "레딧에서 하기")
    assert result[1], result[2]
