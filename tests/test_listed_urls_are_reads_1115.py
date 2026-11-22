"""적어 준 주소가 여럿이면 그 수가 읽을 몫이다 · 맡긴 쪽이 켜는 「끝까지」 칸 (2026-11-15 PC 판 e16a4f31 · be3cd1b5).

바깥 클로드가 「아래 네 모델 페이지를 차례로 열고, 모델마다 … 표로」 + 번호 붙인 메이커월드 주소 넷(셋)을 맡겼다. 「4개」라는
숫자 낱말이 없어 계획이 `{}` 였고 예산은 기본 12 — 두 판 다 11걸음을 첫 페이지 하나에서 쓰고 「일부」로 끝났다.
고친 것 둘: (1) 늘어놓은 서로 다른 주소 수만큼 확실한 읽기 개수 요구(`plan.listed_urls_to_read`), (2) 호스트가 판단해 켜는
`finish_all` — 걸음 예산을 바깥 상한(48)까지(무제한 아님).
"""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.delegation import TASK_TOOL

# 운영 판 e16a4f31 의 과제 글 그대로(돌려받을 항목 줄은 MCP 문이 붙인 것).
TASK_E16 = (
    "크롬(메이커월드 로그인돼 있음)에서 아래 네 모델 페이지를 차례로 열고, 모델마다 ① 라이선스 이름(예: Standard Digital File "
    "License, CC BY-NC 등)과 그 뜻 한 줄 ② 내려받기 버튼이 있는지 ③ 받을 수 있는 파일 이름 · 형식(STL/3MF) · 크기(보이면) "
    "④ 만든 사람 이름 ⑤ 모델 크기(mm, 보이면)를 확인해 표로 답해 주세요. **파일은 절대 내려받지 마세요** — 내려받기 버튼을 "
    "누르면 받아지니 누르지 말고 페이지에 보이는 정보만 읽으세요.\n"
    "1) https://makerworld.com/ko/models/1909815-smiley-chibi-cat-adorable-happy-kitten\n"
    "2) https://makerworld.com/ko/models/1521156-sitting-kitty-figurine-cute-no-support-3d-print\n"
    "3) https://makerworld.com/ko/models/2470600-cute-teddy-bear-sitting-bear-figurine\n"
    "4) https://makerworld.com/ko/models/1137098-cute-sitting-hippo\n\n"
    "(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: 라이선스 · 내려받기 버튼 · 파일 형식 · 만든 사람)"
)
# 운영 판 be3cd1b5 — 주소 셋.
TASK_BE3 = (
    "크롬에서 아래 세 메이커월드 모델 페이지를 차례로 열고, 페이지마다 글을 한 번만 읽어(browser_extract) ① 라이선스 이름 "
    "② 만든 사람 ③ 파일 형식(STL/3MF)만 표로 답해 주세요. 내려받기 버튼은 찾지도 누르지도 마세요. 파일은 받지 않습니다. "
    "세 페이지 모두 여는 것이 우선입니다.\n"
    "1) https://makerworld.com/ko/models/1521156-sitting-kitty-figurine-cute-no-support-3d-print\n"
    "2) https://makerworld.com/ko/models/2470600-cute-teddy-bear-sitting-bear-figurine\n"
    "3) https://makerworld.com/ko/models/1137098-cute-sitting-hippo\n\n"
    "(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: 라이선스 · 만든 사람 · 파일 형식)"
)


def _extract(text: str, **options: Any) -> list[plan.Requirement]:
    """판이 부르는 꼴 그대로 — 계획 문장은 줄바꿈을 지운 글이고, 원문은 `own_from` 으로 같이 간다."""
    return plan.extract(" ".join(text.split()), own_from=text, **options)


def _url_counts(text: str, **options: Any) -> list[tuple[int, str, str]]:
    return [(r.target, r.grade, r.origin) for r in _extract(text, **options) if r.kind == "count" and r.listed_urls]


def _agent(tmp_path: Path) -> BrowserAgent:
    agent = BrowserAgent.__new__(BrowserAgent)
    agent.config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")  # type: ignore[attr-defined]
    return agent


# ── (1) 주소 목록 → 읽을 몫 ──────────────────────────────────────────────────────────────────────────


def test_the_two_live_tasks_now_get_a_firm_read_count_per_address() -> None:
    assert _url_counts(TASK_E16) == [(4, "firm", "address")]
    assert _url_counts(TASK_BE3) == [(3, "firm", "address")]
    count = next(r for r in _extract(TASK_E16) if r.kind == "count")
    assert count.label == "적어 준 주소 4곳을 하나씩 직접 열어 읽기"
    assert count.grounding_required and count.source_scope == "web"


def test_four_addresses_grow_the_budget_past_the_flat_twelve(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    assert agent._step_budget(_extract(TASK_E16)) == 14     # 4 × (열기 + 추출) + 준비 6
    assert agent._step_budget(_extract(TASK_BE3)) == 12     # 3 × 2 + 6 = 기본과 같다 — 셋은 예산이 아니라 확실한 요구가 더 가게 한다
    assert agent._step_budget([]) == 12


def test_addresses_listed_without_numbers_on_their_own_lines_also_count() -> None:
    text = "아래 주소들을 하나씩 열어 제목과 날짜를 읽어 표로 정리해 줘.\nhttps://a.example.com/x\nhttps://b.example.com/y\n- https://c.example.com/z"
    assert _url_counts(text) == [(3, "firm", "address")]


def test_the_same_address_twice_is_one_page() -> None:
    text = ("아래 페이지를 열어 확인해 줘.\n1) https://example.com/a/\n2) https://www.EXAMPLE.com/a#top\n3) https://example.com/b")
    assert _url_counts(text) == [(2, "firm", "address")]
    only_one = "아래 페이지를 열어 확인해 줘.\n1) https://example.com/a\n2) https://example.com/a/"
    assert _url_counts(only_one) == []


def test_told_not_to_open_them_is_not_a_read() -> None:
    told_not = ("이 주소들은 열지 마세요. 이름만 표로 옮겨 적어 줘.\n1) https://example.com/a\n2) https://example.com/b")
    assert _url_counts(told_not) == []
    no_need = "아래 링크는 열 필요 없어. 목록만 확인해서 정리해.\nhttps://example.com/a\nhttps://example.com/b"
    assert _url_counts(no_need) == []
    after = "아래 둘을 확인해 줘.\n1) https://example.com/a\n2) https://example.com/b\n이 주소들은 열지 말고 이름만 적어."
    assert _url_counts(after) == []


def test_keeping_off_other_pages_still_reads_the_given_ones() -> None:
    """「다른 페이지는 열지 마」는 **이 주소만** 읽으라는 말이다."""
    text = ("아래 세 페이지를 열어 가격을 확인해 줘. 다른 페이지는 열지 마세요.\n"
            "1) https://example.com/a\n2) https://example.com/b\n3) https://example.com/c")
    assert _url_counts(text) == [(3, "firm", "address")]


def test_one_line_marked_skip_drops_only_that_address() -> None:
    text = ("아래 페이지를 열어 확인해 줘.\n1) https://example.com/a\n2) https://example.com/b (제외)\n"
            "3) https://example.com/c\n4) https://example.com/d (이건 열지 마)\n5) https://example.com/e")
    assert _url_counts(text) == [(3, "firm", "address")]


def test_without_a_read_word_addresses_are_not_reads() -> None:
    bookmark = "아래 주소들을 북마크에 저장해 줘.\n1) https://example.com/a\n2) https://example.com/b"
    assert _url_counts(bookmark) == []


def test_a_negated_read_word_is_not_a_read_word() -> None:
    """운영 판 721180 · 76516710(역검증에서 찾은 헛걸림): 「받아서(browser_download) … 요약하거나 고치지 말고 저장만」."""
    download = ("아래 주소 3개를 차례로 받아서(browser_download), 요약하거나 고치지 말고 원문 그대로 텍스트 파일로 저장만 해 줘.\n"
                "1. https://example.com/a.json\n2. https://example.com/b.json\n3. https://example.com/c.json")
    assert _url_counts(download) == []
    # 같은 꼴이어도 「열어서」가 있으면 읽는 일이다(운영 판 d8f24ff0 — 레딧 주소 7개를 열어 본문을 그대로 저장).
    opened = download.replace("받아서(browser_download)", "열어서")
    assert _url_counts(opened) == [(3, "firm", "address")]


def test_a_fallback_address_in_brackets_is_not_another_page() -> None:
    """운영 판 137d4885(역검증에서 찾은 과소 계수): 「1) A (안 열리면 A') 2) B (안 열리면 …) 3) C 4) D」는 넷이다.
    「안 열리면」은 조건이지 「열지 마」가 아니고, 괄호 속 대체 주소는 다섯째 페이지가 아니다."""
    text = ("아래 페이지를 직접 열어 읽고 규칙만 뽑아 줘.\n"
            "1) https://www.reddit.com/r/A/about/rules (안 열리면 https://old.reddit.com/r/A/about/rules)\n"
            "2) https://www.reddit.com/r/B/about/rules (안 열리면 old.reddit.com 주소로)\n"
            "3) https://news.hada.io/guidelines\n4) https://news.ycombinator.com/newsguidelines.html")
    assert _url_counts(text) == [(4, "firm", "address")]
    no_need = "아래 링크는 안 열어도 돼. 이름만 확인해 줘.\n1) https://example.com/a\n2) https://example.com/b"
    assert _url_counts(no_need) == []


def test_addresses_inside_running_prose_are_left_alone() -> None:
    """목록이 아니라 문장 속에 든 주소(「a 와 b 를 …」)는 셈하지 않는다 — 헛걸림보다 못 걸림이 낫다."""
    prose = "https://example.com/a 에 있는 표를 읽고 https://example.com/b 의 설명과 같은지 확인해 줘."
    assert _url_counts(prose) == []


def test_an_existing_count_keeps_the_say() -> None:
    text = ("아래 목록에서 공고 2개를 골라 열어 읽고 정리해 줘.\n1) https://example.com/a\n2) https://example.com/b\n"
            "3) https://example.com/c")
    counts = [r for r in _extract(text, has_named_source=True) if r.kind == "count"]
    assert counts and all(not r.listed_urls for r in counts)


def test_code_tab_specs_are_not_read_lists() -> None:
    spec = "이 함수를 고쳐 줘. 참고 문서를 읽고 맞춰.\n1) https://docs.example.com/a\n2) https://docs.example.com/b"
    assert _url_counts(spec, code_workspace=True) == []


def test_more_than_the_cap_is_cut_at_the_cap() -> None:
    lines = "\n".join(f"{n}) https://example.com/p{n}" for n in range(1, 15))
    assert _url_counts("아래 페이지를 하나씩 열어 제목을 읽어 줘.\n" + lines) == [(plan._PER_ITEM_READ_CAP, "firm", "address")]


def test_english_lists_count_too() -> None:
    """영어는 「each of these」 + 번호로 이미 개수 요구가 선다(기존 장치) — 그쪽이 읽을 수를 쥐고, 주소 칸은 두 줄로 안 선다."""
    text = "Open each of these pages and read the license, then answer in a table.\n1) https://example.com/a\n2) https://example.com/b"
    assert [r.target for r in _extract(text) if r.kind == "count"] == [2]
    bare = "Read these pages and list each license in a table:\nhttps://example.com/a\nhttps://example.com/b\nhttps://example.com/c"
    assert [r.target for r in _extract(bare) if r.kind == "count"] == [3]
    told_not = "Don't open these links, just copy their names into a table.\n1) https://example.com/a\n2) https://example.com/b"
    assert _url_counts(told_not) == []


def test_reading_any_two_pages_fills_a_two_address_count() -> None:
    """채움은 보통 개수 요구와 같다 — 서로 다른 웹 페이지를 그 수만큼 직접 읽었나. 사이트 이름으로 셈을 좁히지 않는다."""
    text = "아래 두 페이지를 열어 확인해 줘.\n1) https://example.com/a\n2) https://other.example.org/b"
    reqs = [r for r in _extract(text) if r.kind == "count"]
    steps = [{"tool": "browser_open", "ok": True, "arguments": {"url": url}} for url in ("https://example.com/a", "https://other.example.org/b")]
    answer = "| 이름 | 라이선스 |\n|---|---|\n| a | MIT |\n| b | MIT |"
    one = plan.check(reqs, sources=["https://example.com/a"], steps=steps[:1], answer=answer)
    both = plan.check(reqs, sources=["https://example.com/a", "https://other.example.org/b"], steps=steps, answer=answer)
    assert [ok for _, ok, _ in one] == [False]
    assert [ok for _, ok, _ in both] == [True]


def test_a_named_site_does_not_shrink_the_count_of_given_addresses() -> None:
    """「깃허브에서 …」 + 깃허브 · 깃랩 주소 — 사람이 댄 주소는 사이트 이름 밖이어도 읽은 것으로 센다."""
    text = "깃허브에서 아래 두 저장소를 열어 라이선스를 확인해 표로 줘.\n1) https://github.com/a/b\n2) https://gitlab.com/c/d"
    reqs = _extract(text)
    assert any(r.kind == "site" and r.grade == "firm" for r in reqs)
    results = plan.check(reqs, sources=["https://github.com/a/b", "https://gitlab.com/c/d"], steps=[], answer="")
    assert [(ok, saw) for req, ok, saw in results if req.kind == "count"] == [(True, "2개 읽음")]


# ── (2) 「끝까지」 칸 ────────────────────────────────────────────────────────────────────────────────


def test_finish_all_gives_the_outer_cap_and_never_more(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    cap = agent.config.agent_autonomous_max_steps
    assert cap == 48
    assert agent._step_budget([], finish_all=True) == cap
    assert agent._step_budget(_extract(TASK_E16), finish_all=True) == cap
    assert agent._step_budget([], finish_all=False) == 12          # 안 켜면 그대로
    # 무제한이 아니다 — 개수가 아무리 커도 바깥 상한을 넘지 않는다.
    many = [plan.Requirement("count", "30개", 30), plan.Requirement("artifact", "엑셀", "xlsx")]
    assert agent._step_budget(many, finish_all=True) == cap


def test_the_task_tool_offers_finish_all_and_says_the_host_decides_up_to_48() -> None:
    spec = TASK_TOOL["parameters"]["properties"]["finish_all"]
    assert spec["type"] == "boolean"
    assert "finish_all" not in TASK_TOOL["parameters"]["required"]
    assert "48" in spec["description"] and "판단" in spec["description"] and "무제한 아님" in spec["description"]


def test_the_flag_travels_from_the_mcp_door_to_the_run() -> None:
    from alture_jarvis.api import ChatRequest
    from alture_jarvis.mcp_server import JarvisMcpBridge

    assert ChatRequest(prompt="x", origin="mcp", finish_all=True).model_dump()["finish_all"] is True
    assert ChatRequest(prompt="x").model_dump()["finish_all"] is False
    assert "finish_all" in inspect.signature(BrowserAgent.run).parameters
    runtime_src = Path(inspect.getfile(BrowserAgent)).with_name("runtime.py").read_text(encoding="utf-8")
    assert 'finish_all=payload.get("finish_all") is True' in runtime_src

    class _Client:
        def __init__(self) -> None:
            self.posts: list[dict[str, Any]] = []

        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:  # noqa: A002
            self.posts.append(json)

            class _R:
                status_code = 200

                @staticmethod
                def json() -> dict[str, Any]:
                    return {"id": "j1"}

            return _R()

        async def aclose(self) -> None:
            return None

    for value, expected in ((True, True), (False, None), ("true", None), (None, None)):
        client = _Client()
        bridge = JarvisMcpBridge(token="t", client=client)
        args: dict[str, Any] = {"task": "주소 네 곳 읽어 표로"}
        if value is not None:
            args["finish_all"] = value
        text, failed = asyncio.run(bridge.call("sonjari_task", args))
        assert not failed, text
        assert json.loads(text)["job_id"] == "j1"
        assert client.posts[0].get("finish_all") is expected, value
