"""요구마다 확실성 등급 — 확실한 요구만 밀고, 확실한 요구만 완료를 가른다 (2026-10-24 · 전략안 §55-41).

10-23 하네스 전수조사: 실사용 미달 판의 헛 요구는 전부 「뽑기」에서 났다 — 수다 속 숫자 · 「표로 정리해 줘」 · 배운 표의 지명 ·
계산 말 없는 「개수」. 낱말 예외를 더하지 않고 「사람이 시킨 문장 안에 그 요구의 근거가 있나」 하나로 가른다.

시험은 소스 글자가 아니라 **행동**으로 쓴다(보고서 5절 뿌리 ⑤). 문장은 운영 판에서 가져왔다(판 앞 8자리를 적어 둠).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import test_forced_commit as base
from alture_jarvis import plan as P
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.answer_gate import _READ_SHORT_MARK
from alture_jarvis.jobs import JobStore
from alture_jarvis.run_card import RunCard

_WEB = {"must_observe": True, "observe_from": ("web",)}


def _grades(prompt: str, **options) -> dict[str, tuple[str, str]]:
    return {req.label: (req.grade, req.origin) for req in P.extract(prompt, **options)}


# ── 등급의 정의 ──────────────────────────────────────────────────────────────


def test_a_number_in_chat_is_not_a_reading_order() -> None:
    """18c54a99 — 수다 속 「3명은 깔았고」는 「3개 열어 읽기」가 아니다. 서긴 서되 흐림이다(지우지 않는다)."""
    got = _grades("그래도 괘안치 아직 레딧이나 이런데 홍보도 안하고 조용히 했는데 3명은 깔았고 1명은 5점 별점을 줬더라고", **_WEB)
    assert got["3개 이상 직접 열어 읽기"] == ("soft", "mention")
    assert got["레딧에서 하기"] == ("soft", "mention")
    # 「가서 봐야 하는 일」의 안전망(근거 읽기)은 늘 확실이다 — 흐린 개수가 대신하지 못하니 예비로 세워 둔 것이 남는다.
    assert got["근거가 되는 대상 실제로 읽기"] == ("firm", "router")


def test_a_question_with_a_rank_is_not_a_count() -> None:
    """26915f9f — 「26년 2 3 순위는 언제뜨누」."""
    got = _grades("26년이 지금 2개월정도밖에 안 남앗는데 그럼 26년 2 3 순위는 언제뜨누 근데 이거 카페들어가서 보니까 보통 1순위에어 끝난다는디", **_WEB)
    assert got["3개 이상 직접 열어 읽기"][0] == "soft"


@pytest.mark.parametrize(
    "prompt",
    [
        "사람인에서 공고 3개 열어 읽어줘",
        "삼성전자 뉴스 3개",  # 명사로 끝나는 지시 — 글 전체가 지시다
        "교보문고에서 책 3권",
        "여수 국밥집 세 군데만 알려줘",
        "그 혹시 오늘자로 허깅페이스에서 좋은 모델들중 인기 순으로 한 5개만 얘기해줄수있나",  # 부탁하는 물음(c41f09c2)
        "레딧 r/LocalLLaMA 에서 글을 찾아 댓글을 읽고 답만 해 줘. 결과 중 댓글 많은 순으로 3개를 열어.",  # 반말 지시(3dc56fb1)
    ],
)
def test_counts_the_person_asked_for_stay_firm(prompt: str) -> None:
    counts = [req for req in P.extract(prompt, **_WEB) if req.kind == "count"]
    assert counts and all(req.grade == "firm" for req in counts), [(r.label, r.grade, r.origin) for r in counts]


def test_a_table_in_the_answer_is_not_a_file_but_a_named_format_is() -> None:
    """904a9893 — 앞부분만 보면 「표로 정리해 줘」(답 속 표)지만, 같은 글 끝의 「결과는 엑셀로.」(풀이말 없는 조각)가 시킨 형식이다.
    10-23 보고서는 이 판을 헛 요구로 셌다 — 앞부분만 읽은 탓이다(전략안 §55-41 덧붙임 바로잡기 1)."""
    with_format = P.extract("그래픽카드 메모리 16GB PC에서 쓰는 로컬 모델을 조사해 표로 정리해 줘. 결과는 엑셀로.")
    assert [(r.kind, r.grade) for r in with_format if r.kind == "artifact"] == [("artifact", "firm")]
    # b679dff3 — 「값을 그대로 옮겨 적어줘」는 답에 옮겨 적으라는 말이다.
    copied = P.grade_requirements(
        [P.Requirement("artifact", "실제 산출물 파일 만들기", ())],
        "YES24 사이트에서 아래 두 상품 페이지를 열어 쪽수와 ISBN 값이 맞는지 확인해줘. 실제로 적힌 값을 그대로 옮겨 적어줘(지어내지 말고).",
    )
    assert copied[0].grade == "soft"


def test_a_name_learned_by_the_atlas_is_soft_unless_the_address_is_given() -> None:
    """141e2955 · 760b04f4 — 배운 표의 「여수」는 사는 곳이지 일하는 사이트가 아니다. 주소를 대면 그곳이다."""
    atlas = {"known_sites": {"여수": ("yeosu.example.kr",)}}
    assert _grades("전남 여수에서 지금 사무실이 있는데 입주 공간을 알아봐 줄 수 있나?", **atlas)["여수에서 하기"] == ("soft", "learned")
    assert _grades("여수(yeosu.example.kr)에서 공고 3개 찾아줘", **atlas)["여수에서 하기"] == ("firm", "address")


def test_a_site_is_firm_where_the_work_happens_not_where_it_is_a_topic() -> None:
    # 일하는 곳 자리(「X에서」)는 물음 속이어도 그곳이다 — fb5467da 「얼마하노 쿠팡에서」.
    assert _grades("근데 26년도 기준으로도 3090은 강력하제 얼마하노 쿠팡에서")["쿠팡에서 하기"][0] == "firm"
    # 시키는 문장 밖의 이름은 흐림이다.
    graded = P.grade_requirements(
        [P.Requirement("site", "깃허브에서 하기", ("github.com",))],
        "크롬에서 레딧 게시판의 규칙 목록을 열어 원문 그대로 옮겨 줘. 특히 자기 홍보 · 링크 · 깃허브에 관한 규칙은 빠짐없이 원문 그대로.",
    )
    assert graded[0].grade == "soft"


def test_a_computation_needs_a_word_of_computing() -> None:
    assert _grades("1부터 100까지 합을 계산해 줘")["직접 계산해 보기"] == ("firm", "ask")
    graded = P.grade_requirements(
        [P.Requirement("action", "직접 계산해 보기", "sandbox_run")],
        "크롬에서 레딧 인기 글 위에서부터 25개의 제목 · 점수(업보트) · 댓글 수를 엑셀 파일 하나로 정리해 줘.",  # 759ba894
    )
    assert graded[0].grade == "soft"


def test_code_tab_changes_stay_firm_but_show_me_is_not_a_file() -> None:
    fix = P.extract(
        "C:/x/L6 의 test_pager.py 테스트가 여러 개 실패한다. 원인을 찾아 pager.py 와 slicer.py 를 고쳐서 전부 통과시켜. 테스트 파일은 고치지 마.",
        code_workspace=True,
    )
    assert ("artifact", "firm") in [(r.kind, r.grade) for r in fix]
    show = P.extract(  # b93c137f — 버그 설명 속 「만들어버려」 · 「고치지 말고 보여줘」
        "이 저장소에서 one() 함수의 구현을 찾아줘. 지금 버그는: 사용자가 넘긴 예외를 무시하고 기본 ValueError 를 만들어버려. "
        "함수 전체 코드를 파일·줄 번호와 함께 그대로 보여줘(고치지 말고).",
        code_workspace=True,
    )
    assert [(r.kind, r.grade) for r in show if r.kind == "artifact"] == [("artifact", "soft")]


def test_english_requests_are_not_graded_yet() -> None:
    got = _grades("Open https://news.ycombinator.com and list the titles of the top 3 stories.", **_WEB)
    assert all(grade == "firm" for grade, _origin in got.values())


def test_pasted_text_is_found_even_when_the_plan_text_lost_its_line_breaks() -> None:
    """6c8de096 — 판의 계획 문장은 줄바꿈을 지운 글이라 붙여넣은 글을 못 갈랐다(10-20 고침이 판에서는 한 번도 일하지 않음).
    원문(`own_from`)을 같이 넘기면 붙여넣은 글의 이름은 요구가 되지 않는다. 계획 문장 뒤에 스킬 지시가 붙어 와도 같다."""
    pasted = "\n".join(
        f"{i}. 깃허브에서 저장소를 고르고 다나와 최저가를 보고 노션에서 정리하는 흐름을 레시피로 남긴다 — 설계 초안 문단 {i} 입니다."
        for i in range(1, 9)
    )
    raw = "그러면 mcp 를 따로 하는 거는 어떤데\n\n" + pasted + "\n\n클로드는 이렇게 하자고 하네"
    plan_text = " ".join(raw.split()) + " 말한 상품을 스킬에 적힌 가게마다 찾아 정리해 줘"
    sites = {r.label for r in P.extract(plan_text, own_from=raw) if r.kind == "site"}
    assert not sites & {"깃허브에서 하기", "다나와에서 하기", "노션에서 하기"}, sites
    # 원문이 없던 예전 길은 그대로 그 이름들을 요구로 세운다 — 이 시험이 무엇을 막는지 보이려고 남긴다.
    assert {r.label for r in P.extract(plan_text) if r.kind == "site"} & {"깃허브에서 하기", "다나와에서 하기", "노션에서 하기"}


def test_the_switch_turns_every_requirement_back_to_firm(monkeypatch: pytest.MonkeyPatch) -> None:
    """되돌리는 법(§55-41): 스위치 하나면 예전 판정이다. 출처 칸은 그대로 적는다."""
    monkeypatch.setattr(P, "GRADE_REQUIREMENTS", False)
    got = _grades("그래도 괘안치 아직 레딧이나 이런데 홍보도 안하고 조용히 했는데 3명은 깔았고 1명은 5점 별점을 줬더라고", **_WEB)
    assert got["3개 이상 직접 열어 읽기"] == ("firm", "mention")


# ── 그릇 · 걸러 내기 ──────────────────────────────────────────────────────────


def test_the_run_card_splits_firm_from_soft_and_keeps_empty_slots() -> None:
    reqs = P.extract("그래도 괘안치 아직 레딧이나 이런데 홍보도 안하고 조용히 했는데 3명은 깔았고 1명은 5점 별점을 줬더라고", **_WEB)
    card = RunCard.of(reqs)
    assert [r.kind for r in card.firm()] == ["observe"]
    assert {r.kind for r in card.soft()} == {"count", "site"}
    summary = card.summary()
    assert summary["firm"] == 1 and summary["soft"] == 2 and summary["soft_origins"] == ["mention"]
    # 판 종류 · 언어 칸은 자리만 있다(안 2 에서 채움).
    assert card.work_kind == "" and card.language == ""
    results = P.check(reqs, sources=[], steps=[])
    assert [r[0].kind for r in P.firm_only(results)] == ["observe"]
    assert len(P.soft_only(results)) == 2


def test_the_read_count_warning_can_leave_the_talking_to_the_checklist() -> None:
    """「N개 중 M개만 실제로 열어 읽었습니다」는 대조표 ❌ 줄과 같은 사실 — 대조표가 붙는 판에서는 글을 뺀다. 계산은 그대로."""
    four = "두 곳에서 공고를 최소 4개는 직접 열어 읽고 예산·기간을 표로 정리해줘"
    two_read = [
        {"tool": "browser_extract", "ok": True, "error": "", "status": "", "arguments": {}, "evidence": {"url": f"https://jobs.example/p/{i}"}}
        for i in (1, 2)
    ]
    full = BrowserAgent._goal_shortfall_check(four, two_read)
    assert _READ_SHORT_MARK.search(full)  # 「일부」를 만드는 표시(harness_shortfall)는 이 글로 센다
    assert BrowserAgent._goal_shortfall_check(four, two_read, read_note=False) == ""
    # 처리 개수 경고는 대조표와 다른 사실이라 그대로 낸다.
    acted = BrowserAgent._goal_shortfall_check(
        "", [], plan_results=[(P.Requirement("count_action", "5개 실제로 처리하기", 5), False, "0개")], read_note=False
    )
    assert "5개를 처리하라고 하셨는데" in acted


# ── 판 전체로 ────────────────────────────────────────────────────────────────

_BLOG_WITH_A_REMARK = (
    "네이버 블로그에 '점검' 이라는 제목으로 세 줄 쓰고 임시저장까지 해줘. 발행은 하지 마. 어제 글 3개를 읽었는데 반응이 좋더라."
)


def _run(tmp_path: Path):
    config = base._Config(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        browser_enabled=True, browser_task_timeout_sec=60,
    )
    store = JobStore(tmp_path / "jarvis.db")
    events = base._EventBus()
    screen: list[dict] = []
    events.add_listener(lambda record: screen.append(dict(record.payload)) if record.event == "agent_plan" else None)
    runner = BrowserAgent(config, base._StopsAfterPreparing(), base._RecordingGateway(), base._FakeBrowser(), base._FakeTools(), store, events)
    job = store.create_job("chat", "agent", {"prompt": _BLOG_WITH_A_REMARK})
    store.claim_next()
    return runner.run(_BLOG_WITH_A_REMARK, job_id=job["id"], origin="chat"), screen


def test_a_soft_requirement_neither_pushes_nor_decides_the_run(tmp_path: Path) -> None:
    """수다 한 줄(「어제 글 3개를 읽었는데 반응이 좋더라」)이 세운 「3개 이상 직접 열어 읽기」가 판을 「일부」로 만들지 않는다.
    화면 · 답 끝 대조표 · 바깥 AI 로 가는 체크리스트에도 안 나가고, 판 기록의 `plan_soft` 에만 남는다."""
    result, screen = _run(tmp_path)
    verification = result.verification
    assert verification["completion_state"] == "complete"
    # 밀지도 않는다 — 흐린 「3개 열어 읽기」 때문에 하네스가 결과를 대신 열지 않는다(스위치를 끄면 1번 대신 연다 · 아래 짝).
    assert verification["forced_reads"] == 0
    assert "3개 이상 직접 열어 읽기" not in [item["label"] for item in verification["plan"]["items"]]
    assert [(item["label"], item["grade"], item["met"]) for item in verification["plan_soft"]] == [("3개 이상 직접 열어 읽기", "soft", False)]
    assert verification["run_card"]["soft"] == 1
    assert "3개 이상 직접 열어 읽기" not in result.answer
    assert screen and all("3개 이상 직접 열어 읽기" not in [item["label"] for item in shot["items"]] for shot in screen)


def test_with_the_switch_off_the_same_run_is_partial_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 판을 스위치만 끄고 돌리면 예전처럼 그 헛 요구가 「일부」를 만든다 — 위 시험이 무엇을 바꿨는지의 짝."""
    monkeypatch.setattr(P, "GRADE_REQUIREMENTS", False)
    result, _screen = _run(tmp_path)
    assert result.verification["completion_state"] == "partial"
    assert result.verification["forced_reads"] >= 1
    assert "3개 이상 직접 열어 읽기" in [item["label"] for item in result.verification["plan"]["items"]]
    assert result.verification["plan_soft"] == []
