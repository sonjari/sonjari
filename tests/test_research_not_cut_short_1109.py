"""조사를 일찍 끊지 않는다 — 산출물 차례의 문 · 진척 판정 · 거절 글을 **한 원칙**으로 (2026-11-09).

원칙: 시킨 것 가운데 아직 못 채운 읽기(대조표의 읽기 칸 · 요청에 적힌 주소 · 요청이 이름으로 댄 페이지 · 「전부」)가 남았으면,
아직 안 읽은 **페이지**로 가는 열기는 막지 않고 처음 읽은 페이지는 진척으로 센다. 이미 읽은 바로 그 페이지를 또 여는 것 ·
지금 페이지 맴돌기는 그대로 막는다. 막을 때는 늘 다음 길을 같이 준다.

걸음의 모양은 운영 기록 그대로다(도구 · 성공 여부 · 인자 · `evidence.url`):
  ① 맥 df9e4209 — 허깅페이스 자료 13개(요청이 이름으로 댐)를 읽어 엑셀로. 넷째 자료를 읽은 뒤 다섯째 자료 페이지가
     「huggingface.co 는 읽은 사이트」로 `not_this_stage` 에 막혀 4건으로 끝났다. 그 앞에서는 새 자료 페이지를 읽는 걸음이
     「남은 목표(파일)에 진척 없음」으로 접혔다(`wrapped_up:no_progress_for_remaining_goal`).
  ② 맥 02a711f2 — 9개 자료 주소를 번호로 적고 「하나씩 열어 … 엑셀 한 시트에」. 끝에 붙은 「(돌려받을 항목 — …)」 덩어리가
     사람의 말로 갈려 요구가 하나도 안 섰고, 진척 없음으로 접혀 파일 없이 「엑셀을 만든다」로 끝났다.
  ③ PC 기록 — 「일부만 됨 + 모델이 스스로 끝냄」 444판 중 83판이 하네스 거절 직후 멈췄다. 거절 글이 갈 곳을 안 댔다.
주소의 자료 이름은 실제 기록의 것이고, 그 밖의 번호는 지어낸 것이다.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.plan_nudges import (
    _goes_to_unread_site,
    _owed_read_site,
    _OWED_READ_PAGES,
    _page_named_in,
    fresh_pages_read,
    owed_page,
    page_key,
    reading_owed,
    request_urls,
    stage_gate_lets_through,
    stage_refusal_note,
)

HF = "https://huggingface.co/datasets/"
DF9_REQUEST = (
    "웹 브라우저 에이전트와 도구 호출(function calling)을 학습시키는 공개 데이터셋을 전수조사해서 「브라우저에이전트_학습자료_전수조사_1109.xlsx」 "
    "엑셀 파일로 정리해 줘(저장 폴더는 따로 정하지 말고 결과물 폴더에). 출발점: 깃허브 Khang-9966/Computer-Browser-Phone-Use-Agent-Datasets 의 "
    "목록, 그리고 허깅페이스의 Qwen/WebWorldData · microsoft/WebSTAR · openbmb/UltraData-SFT-Agent-2609 · nvidia Nemotron-SFT-Agentic-v2 · "
    "data-for-agents/insta-150k-v1 · Go-Browse · AgentTrek · Mind2Web · WebLINX · NNetNav · Salesforce xlam-function-calling-60k · "
    "NousResearch hermes-function-calling-v1 · ToolACE. 자료마다 한 줄씩: 자료 이름 · 주소 · 크기 · 라이선스 이름. 라이선스는 짐작하지 말고 "
    "원문에서 읽은 것만 적어 줘.\n\n"
    "(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: 자료 이름 · 크기 · 라이선스 · 근거 주소)"
)
NINE = [
    HF + "data-for-agents/insta-150k-v1", "https://github.com/ApGa/Go-Browse", "https://github.com/xlang-ai/AgentTrek",
    HF + "osunlp/Mind2Web", HF + "McGill-NLP/WebLINX", "NNetNav (stanfordnlp 의 웹 에이전트 자료 · 허깅페이스에서 찾기)",
    HF + "Salesforce/xlam-function-calling-60k", HF + "NousResearch/hermes-function-calling-v1", HF + "Team-ACE/ToolACE",
]
A2_REQUEST = (
    "학습 자료 전수조사 이어서: 아래 9개 자료의 페이지를 하나씩 열어 데이터 카드나 LICENSE 원문을 읽고 「브라우저에이전트_학습자료_전수조사_1109_2.xlsx」 "
    "엑셀 파일 한 시트에 자료마다 한 줄로 정리해 줘(저장 폴더는 따로 정하지 말고 결과물 폴더에). 칸: 자료 이름 · 주소 · 크기(궤적 수나 예시 수) · "
    "라이선스 이름 · 상업적 사용(원문에 적힌 문장 그대로, 없으면 「확인 못 함」) · 언어(한국어 포함 여부) · 실제 웹사이트인지 시험용 사이트인지 "
    "합성인지 · 행동 형식(도구 이름과 인자 모양) · 실패 판 포함 여부 · 근거로 읽은 주소. 라이선스는 짐작하지 말고 원문에서 읽은 것만. 주소가 열리지 "
    "않으면 그 자료 이름으로 허깅페이스나 깃허브에서 찾아 열어.\n"
    + "\n".join(f"{index}) {item}" for index, item in enumerate(NINE, 1))
    + "\n\n(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: 자료 이름 · 크기 · 라이선스 · "
    "상업적 사용 · 언어 · 행동 형식 · 근거 주소)"
)


def _open(url: str, landed: str = "", ok: bool = True) -> dict[str, Any]:
    return {"tool": "browser_open", "ok": ok, "arguments": {"url": url}, "evidence": {"url": landed or url} if ok else {}}


def _extract(url: str, ok: bool = True) -> dict[str, Any]:
    return {"tool": "browser_extract", "ok": ok, "arguments": {"find": ["License"]},
            "evidence": {"url": url, "char_count": 9000} if ok else {}}


def _req(kind: str, target: Any = None, *, label: str = "", source_scope: str = "") -> SimpleNamespace:
    return SimpleNamespace(kind=kind, label=label or kind, target=target, source_scope=source_scope)


def _df9_steps() -> list[dict[str, Any]]:
    """df9e4209 의 1~20걸음 모양 — 깃허브 목록을 읽고 허깅페이스 자료 넷을 열어 읽었다."""
    listing = "https://github.com/Khang-9966/Computer-Browser-Phone-Use-Agent-Datasets"
    steps = [{"tool": "site_list", "ok": True, "arguments": {}, "evidence": {}}, _open(listing), _extract(listing)]
    for name in ("Qwen/WebWorldData", "microsoft/WebSTAR", "openbmb/UltraData-SFT-Agent-2609", "nvidia/Nemotron-SFT-Agentic-v2"):
        steps += [_open(HF + name), _extract(HF + name)]
    return steps


DF9_PLAN = [(_req("artifact", (".xlsx",)), False, "열 수 있는 산출물 없음"),
            (_req("observe", "browser", label="근거가 되는 대상 실제로 읽기"), True, "7개 실제로 읽음")]


# ① 문 — 읽은 사이트의 안 읽은 자료 페이지 ─────────────────────────────────────────────

def test_df9_the_fifth_named_dataset_on_a_read_site_is_let_through_in_both_turns() -> None:
    steps = _df9_steps()
    insta = {"url": HF + "data-for-agents/insta-150k-v1"}
    # 옛 문은 사이트로 갈랐다 — 허깅페이스는 이미 읽은 사이트라 둘 다 막혔다(이 시험이 그 판정을 바꾼다).
    assert not _goes_to_unread_site("browser_open", insta, steps)
    assert _owed_read_site("browser_open", insta, steps, DF9_PLAN, DF9_REQUEST) == ""
    # 새 문: 요청이 이름(「insta-150k-v1」)으로 댄 페이지다.
    for deliver in (False, True):
        assert stage_gate_lets_through(
            "browser_open", insta, steps, plan_results=DF9_PLAN, request=DF9_REQUEST, deliver_turn=deliver,
        ) == "owed_page", deliver
    # 열고 나면 그 페이지의 첫 읽기도 받는다(되읽기는 아니다).
    opened = steps + [_open(insta["url"])]
    assert stage_gate_lets_through(
        "browser_extract", {}, opened, plan_results=DF9_PLAN, request=DF9_REQUEST, deliver_turn=True,
    ) == "found_unread"


def test_an_unmet_count_lets_a_new_page_on_a_read_site_through() -> None:
    """PC 기록의 주된 모양(aa741c81 · 1881fc77 · 17a76267 · 350e6d6a): 「N개 이상 열어 읽기」가 남았는데 같은 레딧 · 깃허브의 다음 글이 막혔다."""
    steps = []
    for n in range(3):
        url = f"https://www.reddit.com/r/editors/comments/1w{n}aaaa/post_{n}/"
        steps += [_open(url), _extract(url)]
    plan_left = [(_req("count", 12, label="12개 이상 직접 열어 읽기", source_scope="web"), False, "3개 읽음"),
                 (_req("artifact"), False, "없음")]
    nxt = {"url": "https://www.reddit.com/r/editors/comments/1w9zzzz/post_9/"}
    assert stage_gate_lets_through("browser_open", nxt, steps, plan_results=plan_left, request="", deliver_turn=True) == "owed_page"
    # 개수를 다 채웠으면 같은 열기는 막힌다 — 차례를 둔 까닭(9d6942f2: 글 여섯을 읽고도 더 열다 엑셀 0개)은 그대로.
    plan_met = [(plan_left[0][0], True, "12개 읽음"), plan_left[1]]
    assert stage_gate_lets_through("browser_open", nxt, steps, plan_results=plan_met, request="", deliver_turn=True) == ""


def test_the_same_page_already_read_and_circling_the_current_page_stay_refused() -> None:
    steps = _df9_steps()
    plan_left = [(_req("count", 13, source_scope="web"), False, "5개 읽음")]
    again = {"url": HF + "microsoft/WebSTAR/"}  # 끝 빗금 · 스킴만 다른 같은 페이지
    assert stage_gate_lets_through("browser_open", again, steps, plan_results=plan_left, request=DF9_REQUEST, deliver_turn=False) == ""
    for hand in ("browser_extract", "browser_read", "browser_page_data"):
        assert stage_gate_lets_through(hand, {}, steps, plan_results=plan_left, request=DF9_REQUEST, deliver_turn=False) == "", hand
    # 넘겨주기로 다른 주소에 선 페이지(blob/master → blob/main)도 같은 페이지다.
    redirected = [_open("https://github.com/ApGa/Go-Browse/blob/master/LICENSE", "https://github.com/ApGa/Go-Browse/blob/main/LICENSE"),
                  _extract("https://github.com/ApGa/Go-Browse/blob/main/LICENSE")]
    for url in ("https://github.com/ApGa/Go-Browse/blob/master/LICENSE", "https://github.com/ApGa/Go-Browse/blob/main/LICENSE"):
        assert owed_page("browser_open", {"url": url}, redirected, plan_left, "") == "", url


def test_searching_in_the_last_turn_and_new_pages_with_nothing_owed_stay_refused() -> None:
    steps = _df9_steps()
    plan_left = [(_req("count", 13, source_scope="web"), False, "5개 읽음")]
    for hand in ("browser_search", "browser_site_search", "browser_open_result"):
        assert stage_gate_lets_through(hand, {"query": "x"}, steps, plan_results=plan_left, request="", deliver_turn=True) == "", hand
    # 마지막 차례가 아니면 대조표의 읽기 칸이 남은 동안은 찾기도 받는다.
    assert stage_gate_lets_through("browser_site_search", {"query": "x"}, steps, plan_results=plan_left, request="",
                                   deliver_turn=False) == "owed_finding"
    # 남은 읽기도 없고 요청이 대지도 않은 페이지 — 이미 읽은 사이트면 막힌다(안 읽은 사이트는 10-12 대로 마지막 차례 밖에서만 받는다).
    unnamed = {"url": HF + "someone/unrelated-dataset"}
    assert stage_gate_lets_through("browser_open", unnamed, steps, plan_results=DF9_PLAN, request="파일로 정리해 줘",
                                   deliver_turn=True) == ""
    assert stage_gate_lets_through("browser_open", unnamed, steps, plan_results=DF9_PLAN, request="파일로 정리해 줘",
                                   deliver_turn=False) == ""
    # 검색엔진 결과 화면은 페이지가 아니다.
    assert owed_page("browser_open", {"url": "https://search.naver.com/search.naver?query=x"}, steps, plan_left, "") == ""


def test_a_requirement_about_this_pc_does_not_owe_web_pages() -> None:
    local = [(_req("count", 2, source_scope="local"), False, "1개"), (_req("observe", "local"), False, "0개")]
    assert reading_owed(local, "", []) == []
    assert owed_page("browser_open", {"url": "https://tool.example.io/a"}, _df9_steps(), local, "") == ""


def test_addresses_and_page_names_in_the_request() -> None:
    urls = request_urls(A2_REQUEST)
    assert len(urls) == 8 and urls[0] == NINE[0] and urls[-1] == NINE[-1]
    assert _page_named_in(DF9_REQUEST, HF + "osunlp/Mind2Web")
    assert _page_named_in(DF9_REQUEST, HF + "data-for-agents/insta-150k-v1")
    assert _page_named_in(A2_REQUEST, NINE[2].upper().replace("HTTPS://", "https://"))
    assert not _page_named_in(DF9_REQUEST, HF + "someone/unrelated-dataset")
    assert not _page_named_in(DF9_REQUEST, "https://huggingface.co/datasets/x/v1"), "네 글자 미만 끝 이름은 안 본다"
    assert page_key("HTTPS://WWW.Example.com/A/#top") == "example.com/A"
    # 요청에 적힌 주소 중 아직 안 읽은 것은 남은 읽기다.
    read_two = [_open(NINE[0]), _extract(NINE[0]), _open(NINE[1]), _extract(NINE[1])]
    owed = reading_owed([], A2_REQUEST, read_two)
    assert NINE[0] not in owed and NINE[1] not in owed and NINE[2] in owed and len(owed) == 6
    # 적힌 주소가 남았다는 것만으로 **아무 페이지나** 받지는 않는다 — 적힌 그 주소(또는 이름 댄 페이지)만 받는다.
    assert owed_page("browser_open", {"url": NINE[2]}, read_two, [], A2_REQUEST)
    assert owed_page("browser_open", {"url": "https://github.com/someone/unlisted"}, read_two, [], A2_REQUEST) == ""


# ② 진척 — 처음 읽은 페이지 ───────────────────────────────────────────────────────

def test_df9_reading_new_named_pages_is_progress_even_when_only_the_file_is_left() -> None:
    steps = _df9_steps()
    plan_left = [(_req("artifact"), False, "없음")]
    assert BrowserAgent._progress_matches_remaining_plan(steps, plan_left, request=DF9_REQUEST)
    # 요청이 안 댄 판(같은 걸음)은 예전대로 「파일만 남았으면 쓰러 가라」. 요청에 다른 주소가 남아 있어도 안 댄 페이지 읽기는 진척이 아니다.
    assert not BrowserAgent._progress_matches_remaining_plan(steps, plan_left, request="https://board.example.com/p/99 를 읽어 엑셀로")
    assert not BrowserAgent._progress_matches_remaining_plan(steps, plan_left, request="자료를 엑셀로 정리해 줘")
    # 같은 페이지 되읽기만 한 창은 진척이 아니다.
    rereads = steps + [_open(HF + "Qwen/WebWorldData"), _extract(HF + "Qwen/WebWorldData"),
                       _open(HF + "microsoft/WebSTAR"), _extract(HF + "microsoft/WebSTAR"),
                       _extract(HF + "microsoft/WebSTAR"), _extract(HF + "microsoft/WebSTAR")]
    assert not fresh_pages_read(rereads, 6)
    assert not BrowserAgent._progress_matches_remaining_plan(rereads, plan_left, request=DF9_REQUEST)


def test_02a7_a_page_opened_just_before_the_window_and_first_read_inside_it_is_progress() -> None:
    """02a711f2 의 40~46걸음: 40 에 연 go-browse-wa 를 41 에 처음 읽었다 — 「연 주소」로는 창 밖이라 새 출처 0 이었다."""
    early = []
    for url in (NINE[0], NINE[1], NINE[2], NINE[3]):
        early += [_open(url), _extract(url)]
    find = {"tool": "browser_find", "ok": True, "arguments": {"query": "license"}, "evidence": {"url": NINE[2]}}
    # 창(마지막 여섯 걸음)은 go-browse-wa 의 **첫 읽기**부터 — 그 페이지를 연 걸음은 창 밖이다.
    first_read_inside = early + [_open(HF + "apurvaga/go-browse-wa"), _extract(HF + "apurvaga/go-browse-wa"),
                                 _open(NINE[3]), _extract(NINE[3]), _open(NINE[2]), _extract(NINE[2]), find]
    assert first_read_inside[-6]["tool"] == "browser_extract"
    assert not BrowserAgent._is_stuck(first_read_inside)
    # 창 안이 전부 앞에서 읽은 페이지의 되열기 · 되읽기면 예전대로 제자리다.
    only_rereads = early + [_extract(NINE[3]), _open(NINE[3]), _extract(NINE[3]), _open(NINE[2]), _extract(NINE[2]), find]
    assert BrowserAgent._is_stuck(only_rereads)


def test_02a7_the_needs_note_we_append_no_longer_hides_the_request() -> None:
    kinds = {(item.kind, str(item.target)) for item in plan.extract(A2_REQUEST)}
    assert ("count", "9") in kinds and ("artifact", "('.xlsx',)") in kinds, kinds
    english = A2_REQUEST.replace("(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요:",
                                 '(Items to return — label them with these exact names, as a table header, a heading or a "name: value" line:')
    assert {item.kind for item in plan.extract(english)} >= {"count", "artifact"}
    assert plan.own_words(A2_REQUEST) is None


def test_a_pasted_document_is_still_set_apart_with_the_needs_note_attached() -> None:
    """10-20 의 「붙여넣은 글의 요구는 안 세운다」는 그대로 — 우리 덩어리를 빼도 사람 말 + 붙여넣은 글은 갈린다."""
    pasted = ("설계 문서 초안. 예: 깃허브에서 저장소를 찾아 다나와 최저가와 비교하고 노션에서 정리하는 흐름이다. " * 9).strip()
    request = "이 문서 어떻게 생각해?\n\n" + pasted + "\n\n(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: 의견)"
    assert plan.own_words(request) == "이 문서 어떻게 생각해?"
    assert not any(item.kind == "site" for item in plan.extract(request))


# ③ 거절 글 — 막을 때 다음 길 ─────────────────────────────────────────────────────

def test_the_refusal_names_what_is_still_unread_or_says_to_write() -> None:
    hands = frozenset({"local_write_document"})
    read_two = [_open(NINE[0]), _extract(NINE[0]), _open(NINE[1]), _extract(NINE[1])]
    again = stage_refusal_note("browser_open", {"url": NINE[0]}, read_two, plan_results=[], request=A2_REQUEST, hands=hands)
    assert "이미 읽었다" in again and NINE[2] in again and "browser_open" in again, again
    nothing_left = stage_refusal_note("browser_extract", {}, read_two, plan_results=[], request="정리해 줘", hands=hands)
    assert "지금 페이지는 이미 읽었다" in nothing_left and "파일을 만들어라" in nothing_left and "local_write_document" in nothing_left
    plan_left = [(_req("count", 12, label="12개 이상 직접 열어 읽기", source_scope="web"), False, "3개")]
    owed = stage_refusal_note("browser_search", {"query": "x"}, read_two, plan_results=plan_left, request="", hands=hands)
    assert "12개 이상 직접 열어 읽기" in owed and "안 연 다른 페이지" in owed
    full = stage_refusal_note("browser_open", {"url": NINE[5]}, read_two, plan_results=plan_left, request=A2_REQUEST,
                              hands=hands, out_of_room=True)
    assert "더 읽을 걸음이 없다" in full and "문서 끝에" in full
    for note in (again, nothing_left, owed, full):
        assert note.startswith("[도구가 보낸 안내] 권한이나 정책 거절이 아니다")


def test_the_last_turn_grant_is_bounded() -> None:
    assert _OWED_READ_PAGES == 4


# 판 하나를 끝까지 — 마지막 차례에서 요청에 적힌, 읽은 사이트의 안 읽은 주소는 열리고 파일도 써진다.

def test_in_the_deliver_turn_a_listed_page_on_a_read_site_opens_and_the_file_gets_written(tmp_path: Path) -> None:
    from test_stage_gate_unmet_reads_1019 import _run

    listed = "https://board.example.com/p/99"
    gateway, seen, out = _run(tmp_path, "게시판 글을 열어 읽고, " + listed + " 도 열어 읽어서 {out} 에 정리해줘", listed)
    assert "agent_deliver_before_wrap_up" in seen, seen
    assert ("browser_open", listed) in gateway.calls, gateway.calls
    assert "agent_owed_read_allowed" in seen
    assert out.exists(), gateway.calls


# 같은 장부의 작은 고침 둘 ─────────────────────────────────────────────────────────

def test_candidate_16_looking_at_a_picture_on_this_pc_counts_as_observing() -> None:
    """맥 665664d5: 유니티 화면을 찍어 그림으로 읽었는데 「근거 읽기 0개」라 웹 검색 결과를 열려 했다."""
    looked = [
        {"tool": "unity_editor_look", "ok": True, "arguments": {"what": "screenshot"}, "evidence": {}},
        {"tool": "local_view_image", "ok": True, "arguments": {"paths": ["/tmp/a.png"]}, "evidence": {}},
    ]
    for target in ("local", "any"):
        requirement = plan.Requirement("observe", "근거가 되는 대상 실제로 읽기", target)
        (_req_, met, saw), = plan.check([requirement], sources=[], steps=looked)
        assert met and "그림" in saw, (target, saw)
    # 웹을 보라는 판은 그림 한 장으로 안 채워진다.
    web = plan.Requirement("observe", "근거가 되는 대상 실제로 읽기", "browser")
    (_req_, met, _saw), = plan.check([web], sources=[], steps=looked)
    assert not met


def test_candidate_19_the_start_point_regression_runs_at_most_four_workers() -> None:
    from alture_jarvis import regression_vs_start as rvs

    assert rvs.WORKERS_MAX == 4
    assert rvs.PytestSuite().workers <= 4
