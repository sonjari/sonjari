"""**연 것**과 **본문을 읽은 것**은 다르다.

★ 2026-09-02 라이브. 사람인에서 상세 셋을 열어 읽고, 답의 표에는 **목록에서만 본
다른 회사 둘**을 「정규직 · 경력 3년↑ · 마감 10.01」까지 단정해 적었다. 개수 대조는
「3개 읽음」으로 통과시켰다 — 숫자는 맞고 내용은 틀렸다.

그때 장부에는 이런 것을 셀 방법이 **아예 없었다.**

    연 것          vs  본문을 읽은 것
    새 출처        vs  같은 곳을 또 연 것
    읽기 전용 판   vs  거기서 생긴 쓰기

`evidence.py` 가 그 자리다. 지금은 **계측만 한다** — 완료 판정은 여전히
`plan.Requirement` 가 한다. 먼저 재고, 숫자가 나온 뒤에 붙일지 정한다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis import evidence


def _record(tool: str, payload: dict, *, ok: bool = True, step: int = 1) -> dict:
    made = evidence.record_for(tool, payload, ok=ok, step=step)
    return made.to_dict() if made is not None else {}


def test_opening_a_result_is_not_reading_it() -> None:
    """이 한 줄이 이 모듈의 존재 이유다."""
    opened = _record("browser_open_result", {"url": "https://x.test/jobs/1", "rank": 1})
    read = _record("browser_extract", {"url": "https://x.test/jobs/1", "text": "본문"})

    assert opened["type"] == evidence.TYPE_PAGE_OPEN
    assert read["type"] == evidence.TYPE_BODY_READ
    assert opened["source_id"] == read["source_id"]
    # 연 것에는 본문이 없다 — 해시가 비어 있다는 사실이 곧 증거다.
    assert opened["content_hash"] == ""
    assert read["content_hash"]


def test_a_page_opened_but_never_read_is_counted() -> None:
    """「3개 읽었다」의 거짓이 여기 산다."""
    ledger = [
        _record("browser_open_result", {"url": "https://x.test/a"}, step=1),
        _record("browser_extract", {"url": "https://x.test/a", "text": "본문 A"}, step=2),
        _record("browser_open_result", {"url": "https://x.test/b"}, step=3),
        _record("browser_open_result", {"url": "https://x.test/c"}, step=4),
    ]
    seen = evidence.summarize(ledger, read_only=False)

    assert seen["sources_opened"] == 3
    assert seen["sources_read"] == 1
    assert seen["opened_never_read"] == ["https://x.test/b", "https://x.test/c"]


def test_the_same_place_read_twice_is_not_two_places() -> None:
    """하나를 두 번 열고 「2개 읽음」이 되던 자리."""
    ledger = [
        _record("browser_extract", {"url": "https://x.test/a", "text": "본문"}, step=1),
        _record("browser_extract", {"url": "https://x.test/a/", "text": "본문"}, step=2),
        _record("browser_extract", {"url": "https://x.test/a#섹션", "text": "본문"}, step=3),
    ]
    seen = evidence.summarize(ledger, read_only=False)

    assert seen["sources_read"] == 1, "끝 슬래시·조각이 다르면 다른 곳으로 셌다"
    assert seen["reread_sources"] == ["https://x.test/a"]


def test_a_query_is_part_of_the_address() -> None:
    """검색 결과 주소는 질의가 곧 신원이다 — 지우면 서로 다른 곳이 하나가 된다."""
    one = _record("browser_extract", {"url": "https://x.test/s?q=가", "text": "ㄱ"})
    two = _record("browser_extract", {"url": "https://x.test/s?q=나", "text": "ㄴ"})

    assert one["source_id"] != two["source_id"]


def test_the_same_file_by_two_names_is_one_source(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "a.md"
    target.parent.mkdir(parents=True)
    target.write_text("본문", encoding="utf-8")
    relative = str(target.parent / ".." / "sub" / "a.md")

    direct = _record("local_read_text_file", {"path": str(target), "content": "본문"})
    round_about = _record("local_read_text_file", {"path": relative, "content": "본문"})

    assert direct["source_id"] == round_about["source_id"]


def test_a_write_in_a_read_only_job_is_counted_as_a_violation() -> None:
    """0 이어야 하는 숫자다. 세지 않으면 0 인지 알 방법이 없다."""
    ledger = [
        _record("local_read_text_file", {"path": "a.md", "content": "본문"}, step=1),
        _record("local_write_document", {"output_path": "b.hwpx"}, step=2),
    ]

    assert evidence.summarize(ledger, read_only=True)["read_only_violations"] == 1
    assert evidence.summarize(ledger, read_only=False)["read_only_violations"] == 0


def test_evidence_without_a_source_is_not_invented() -> None:
    """출처 없는 증거는 세어도 아무 말을 못 한다. 지어내지 않는다."""
    assert evidence.record_for("browser_extract", {"text": "본문"}, ok=True, step=1) is None
    assert evidence.record_for("local_read_text_file", {}, ok=True, step=1) is None


def test_a_tool_outside_the_manifest_is_skipped_quietly() -> None:
    """수직 슬라이스는 넷뿐이다. 나머지는 조용히 넘긴다 — 틀린 종류를 붙이지 않는다."""
    assert evidence.record_for("browser_click", {"url": "https://x.test"}, ok=True, step=1) is None


def test_opening_alone_supports_no_requirement() -> None:
    """★ 연 것만으로는 아무 요구도 못 채운다. 그게 요점이다."""
    contract = {
        "legacy_bindings": [
            {"requirement_kind": "count", "clause_id": "c1", "clause_ids": ["c1"]},
            {"requirement_kind": "artifact", "clause_id": "", "clause_ids": ["c2", "c3"]},
        ]
    }
    linked = evidence.attach_clauses(
        [
            _record("browser_open_result", {"url": "https://x.test/a"}, step=1),
            _record("browser_extract", {"url": "https://x.test/a", "text": "본문"}, step=2),
            _record("local_write_document", {"output_path": "b.hwpx"}, step=3),
        ],
        contract,
    )

    assert linked[0]["supports_clause_ids"] == ()
    assert linked[1]["supports_clause_ids"] == ("c1",)
    assert linked[2]["supports_clause_ids"] == ("c2", "c3")


def test_the_agent_mints_evidence_at_the_one_crossing() -> None:
    """★ 도구마다 붙이면 새 도구에서 샌다 — `sandbox_run` 으로 실제로 샜었다.

    결과가 반드시 지나는 자리는 `_record_observation` 하나다. 걸음에 실어 두고
    끝에서 걷는다 — 목록을 인자로 돌리면 부르는 자리 넷 중 하나를 빠뜨렸을 때
    **조용히** 빈다.
    """
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    assert source.count("evidence_record_for(") == 1
    assert 'step_record["evidence_record"] = minted.to_dict()' in source
    assert "attach_evidence_clauses(" in source
    assert '"evidence_shadow": summarize_evidence(' in source


def test_every_manifest_tool_still_exists() -> None:
    """표에만 있고 코드에 없는 이름은 다음 사람을 헤매게 한다."""
    root = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"
    haystack = "".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in root.glob("*.py")
    )
    for tool in evidence.MANIFEST:
        assert f'"{tool}"' in haystack, tool


def test_the_other_door_to_the_same_act_is_in_the_table() -> None:
    """★ 첫 라이브 판에서 바로 났던 구멍 (2026-09-03).

    모델은 `.md` 를 `local_read_document` 로 읽는다. 표에 `local_read_text_file`
    만 있어서 **문서를 제대로 읽은 판이 「증거 0」** 으로 남았다.
    같은 일을 하는 다른 문은 같이 넣어야 한다 — 안 그러면 이 원장이 조용히 는다.
    """
    read = _record("local_read_document", {"path": "a.md", "content": "본문"})

    assert read["type"] == evidence.TYPE_BODY_READ
    assert read["effect"] == evidence.EFFECT_READ_LOCAL
    text = _record("local_read_text_file", {"path": "a.md", "content": "본문"})
    assert read["source_id"] == text["source_id"]
    assert read["content_hash"] == text["content_hash"]


def test_every_write_door_is_counted_or_the_violation_metric_lies() -> None:
    """★ `local_write_file` 이 표에 없으면 「읽기 전용 위반 0건」이 **거짓말**이다.

    재는 자에 구멍을 두면 성적표가 완벽할수록 아무것도 안 본 것이 된다 —
    이 저장소가 분모·분류표에서 여러 번 겪은 자리다.
    """
    doors = [
        ("local_write_file", {"path": "a.txt"}),
        ("local_write_document", {"output_path": "a.hwpx"}),
        ("local_apply_edit", {"path": "a.py"}),
        ("local_edit_document", {"output_path": "a.hwpx"}),
        ("local_edit_spreadsheet", {"output_path": "a.xlsx"}),
    ]
    for tool, payload in doors:
        made = _record(tool, payload)
        assert made, tool
        assert made["effect"] in evidence.WRITE_EFFECTS, tool
        assert (
            evidence.summarize([made], read_only=True)["read_only_violations"] == 1
        ), f"{tool} 로 쓴 것이 위반으로 안 세어진다"


def test_a_hash_the_tool_already_computed_is_used() -> None:
    """`local_write_file` 은 `sha256` 을 돌려준다. 있는 것을 안 쓰면 그것도 구멍이다."""
    made = _record("local_write_file", {"path": "a.txt", "sha256": "abc123def4567890ff"})

    assert made["content_hash"] == "abc123def4567890"


def test_a_listing_is_neither_opened_nor_read() -> None:
    """★ 목록을 본 것은 **셋째 종류**다. 이게 없으면 2026-09-02 사고를 못 잡는다.

    그때 사람인 목록에서 회사 둘을 보고 상세를 안 열었는데, 답에는
    「정규직 · 경력 3년↑ · 마감 10.01」까지 적었다. 목록 줄에 없는 값이다.
    `page_open` 도 `body_read` 도 아니라서, 그 판은 「도구 잘 썼다」로 보였다.
    """
    listed = _record("browser_site_search", {"url": "https://x.test/s?q=가", "query": "가"})

    assert listed["type"] == evidence.TYPE_LISTING
    seen = evidence.summarize([listed], read_only=False)
    assert seen["sources_listed"] == 1
    assert seen["sources_opened"] == 0
    assert seen["sources_read"] == 0


def test_answering_from_the_listing_alone_is_flagged() -> None:
    """고장이 아니라 **신호**다 — 목록이 곧 답인 요청도 있다."""
    only_listed = [
        _record("browser_site_search", {"url": "https://x.test/s?q=가"}, step=1),
        _record("browser_snapshot", {"url": "https://x.test/s?q=가"}, step=2),
    ]
    assert evidence.summarize(only_listed, read_only=False)["answered_from_listing_only"] is True

    also_read = only_listed + [
        _record("browser_extract", {"url": "https://x.test/a", "text": "본문"}, step=3)
    ]
    assert evidence.summarize(also_read, read_only=False)["answered_from_listing_only"] is False

    # 목록을 아예 안 본 판까지 참으로 만들면 안 된다.
    assert evidence.summarize([], read_only=False)["answered_from_listing_only"] is False


def test_a_search_is_identified_by_what_was_asked() -> None:
    """검색에는 주소가 없다. 무엇을 물었는가가 그 목록의 신원이다."""
    one = _record("browser_search", {"query": "AI  자동화"})
    same = _record("browser_search", {"query": "ai 자동화"})
    other = _record("browser_search", {"query": "연구비 관리"})

    assert one["source_id"] == same["source_id"] == "q:ai 자동화"
    assert one["source_id"] != other["source_id"]


def test_the_local_listing_doors_are_in_the_table() -> None:
    """「파일 이름은 내용의 근거가 아니다」 — 도구 자신이 그렇게 말하고 있었다."""
    for tool, payload in (
        ("local_list_directory", {"path": "docs"}),
        ("local_search_files", {"query": "인수인계"}),
        ("local_glob", {"path": "docs"}),
    ):
        made = _record(tool, payload)
        assert made and made["type"] == evidence.TYPE_LISTING, tool


def test_the_2026_09_02_shape_is_now_visible() -> None:
    """그날의 판을 그대로 세워 본다 — 목록 하나, 상세 셋, 답에는 다섯.

    원장은 「셋만 읽었다」를 정확히 말한다. 답에 다섯이 적혔는지는 이 층이
    아니라 `_listed_entity_grounding_check` 가 본다 — **둘이 같이 있어야** 잡힌다.
    """
    ledger = [
        _record("browser_site_search", {"url": "https://saramin.test/s?q=연구비"}, step=1),
        _record("browser_open_result", {"url": "https://saramin.test/j/1"}, step=2),
        _record("browser_extract", {"url": "https://saramin.test/j/1", "text": "본문1"}, step=3),
        _record("browser_open_result", {"url": "https://saramin.test/j/2"}, step=4),
        _record("browser_extract", {"url": "https://saramin.test/j/2", "text": "본문2"}, step=5),
        _record("browser_open_result", {"url": "https://saramin.test/j/3"}, step=6),
        _record("browser_extract", {"url": "https://saramin.test/j/3", "text": "본문3"}, step=7),
    ]
    seen = evidence.summarize(ledger, read_only=False)

    assert seen["sources_listed"] == 1
    assert seen["sources_read"] == 3
    assert seen["opened_never_read"] == []
    assert seen["answered_from_listing_only"] is False


def test_navigating_to_a_site_is_not_an_unread_candidate() -> None:
    """★ 2026-09-03 실측. 「열어 놓고 안 읽은 곳 1」의 정체가 `https://kmong.com/` 였다.

    검색하러 들어간 **사이트 첫 화면**이다. 후보가 아니다. 이동까지 같이 세면
    이 지표가 거짓말을 한다 — 그리고 거짓말하는 지표는 아무도 안 읽게 된다.
    """
    ledger = [
        _record("browser_open", {"url": "https://kmong.com/"}, step=1),
        _record("browser_site_search", {"url": "https://kmong.com/search?q=가"}, step=2),
        _record("browser_open_result", {"url": "https://kmong.com/gig/1"}, step=3),
        _record("browser_extract", {"url": "https://kmong.com/gig/1", "text": "본문"}, step=4),
    ]
    seen = evidence.summarize(ledger, read_only=False)

    assert seen["opened_never_read"] == []
    assert seen["sources_opened"] == 1, "후보만 센다"


def test_an_unread_candidate_is_still_caught() -> None:
    """이동을 뺐다고 진짜 사례까지 놓치면 안 된다."""
    ledger = [
        _record("browser_open", {"url": "https://x.test/"}, step=1),
        _record("browser_open_result", {"url": "https://x.test/a"}, step=2),
        _record("browser_open_result", {"url": "https://x.test/b"}, step=3),
        _record("browser_extract", {"url": "https://x.test/a", "text": "본문"}, step=4),
    ]

    assert evidence.summarize(ledger, read_only=False)["opened_never_read"] == [
        "https://x.test/b"
    ]


def test_a_recipe_run_that_searched_is_a_listing() -> None:
    """레시피로 검색하면 목록 단계가 통째로 안 보였다(실측 `sources_listed: 0`)."""
    searched = _record("site_run", {"result_url": "https://saramin.test/s?q=가", "result_count": 15})
    assert searched and searched["type"] == evidence.TYPE_LISTING

    # 검색이 아닌 레시피 실행(스크랩 등)은 아직 표 밖이다 — 출처가 없으니 안 만든다.
    assert evidence.record_for("site_run", {"site": "saramin", "status": "done"}, ok=True, step=1) is None


def test_the_ledger_carries_who_saw_it() -> None:
    """★ 멀티 에이전트의 열쇠. 주인이 없으면 원문을 되짚을 수 없다."""
    made = evidence.record_for(
        "browser_extract",
        {"url": "https://x.test/a", "text": "본문"},
        ok=True,
        step=7,
        job_id="job-42",
    )
    assert made is not None
    assert made.job_id == "job-42" and made.step == 7


def test_grounding_survives_an_agent_boundary() -> None:
    """★ 이게 이번 작업의 이유다 (2026-09-03).

    근거 대조는 **부모의 전사**를 읽고 있었다. 하위 에이전트가 대신 읽으면 그
    도구 결과는 부모 전사에 안 들어온다 → `if not source: return ""` 에서
    **아무 경고 없이 통과**한다. 멀티 에이전트로 쪼개는 순간 눈을 감는 것이다.

    원장은 주인을 들고 있어서 본문을 되짚을 수 있다. 전사가 비어도 잡아야 한다.
    """
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    answer = (
        "| 순위 | 회사 |\n| --- | --- |\n"
        "| 1 | **코드나루** |\n| 2 | **도담스페이스** |\n| 3 | **바름터** |\n"
    )
    ledger = [
        evidence.record_for(
            "browser_extract",
            {"url": f"https://x.test/{n}", "text": body},
            ok=True, step=n, job_id="child",
        ).to_dict()
        for n, body in enumerate(["코드나루 채용", "한울솔루션 채용", "미르 채용"], start=1)
    ]
    bodies = {(rec["job_id"], rec["step"]): text for rec, text in zip(
        ledger, ["코드나루 채용", "한울솔루션 채용", "미르 채용"]
    )}

    # 부모 전사는 **비어 있다** — 하위 에이전트가 읽었기 때문이다.
    blind = BrowserAgent._listed_entity_grounding_check(answer, [])
    assert blind == "", "전사만 보면 이 판은 조용히 통과한다 — 그게 문제였다"

    seeing = BrowserAgent._listed_entity_grounding_check(
        answer, [], ledger, lambda job_id, step: bodies.get((job_id, step), "")
    )
    assert "도담스페이스" in seeing and "바름터" in seeing
    assert "코드나루" not in seeing, "실제로 읽은 것까지 경고하면 안 된다"


def test_the_transcript_is_still_the_fallback() -> None:
    """재료가 줄어드는 쪽으로는 안 바꾼다 — 원장이 비면 예전처럼 전사를 본다."""
    from alture_jarvis.agent import BrowserAgent  # noqa: PLC0415

    answer = "- **미르**\n- **바름터**\n"
    messages = [
        {"role": "tool", "tool_name": "browser_extract", "content": "미르 채용 공고"},
    ]
    note = BrowserAgent._listed_entity_grounding_check(answer, messages, [], lambda j, s: "")

    assert "바름터" in note


def test_the_agent_hands_the_ledger_to_the_check() -> None:
    """배선이 빠지면 이 모든 게 죽은 코드가 된다."""
    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "agent.py"
    ).read_text(encoding="utf-8")

    assert source.count("_listed_entity_grounding_check(answer, messages)") == 0
    # 원장을 넘기는 호출은 한 곳(`_grounding_with_carry`)에 모였고, 답을 만드는 네 자리는 그 도우미를 부른다
    # (2026-09-24: 앞 판을 이어받은 판은 앞 판 답도 자료로 본다).
    assert source.count(
        "_listed_entity_grounding_check(answer, messages, *self._evidence_view(steps, job_id))"
    ) == 1
    assert source.count("self._grounding_with_carry(answer, messages, steps, job_id,") == 4


def test_one_tool_that_does_two_jobs_is_split_by_its_result() -> None:
    """★ `site_run` 은 검색도 하고 스크랩(쓰기)도 한다.

    목록으로만 등록해 두면 **그 문으로 한 쓰기가 「읽기 전용 위반 0건」에서 빠진다.**
    인자가 아니라 결과로 가른다 — `undo_action` 이 있으면 되돌릴 것이 생긴 것이다.
    """
    searched = _record("site_run", {"result_url": "https://saramin.test/s?q=가", "result_count": 15})
    assert searched["type"] == evidence.TYPE_LISTING
    assert searched["effect"] not in evidence.WRITE_EFFECTS

    scrapped = _record(
        "site_run",
        {"result_url": "https://saramin.test/j/1", "site": "saramin", "undo_action": "unscrap"},
    )
    assert scrapped["type"] == evidence.TYPE_MUTATION
    assert evidence.summarize([scrapped], read_only=True)["read_only_violations"] == 1
