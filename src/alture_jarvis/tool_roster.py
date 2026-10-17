"""모델이 보는 **도구 목록**을 갈래·단계·요청으로 고르는 쪽 — agent.py 에서 분리(2026-10-09).

판의 **손**(tool definitions)을 좁히는 판정만 둔다: 조사 판은 갈래 접두사로, 산출물 차례는 쓰기 손으로,
요청에 없는 바깥 서비스는 낱말·계획으로, 작은 컨텍스트는 설명문 길이로. 도구의 **목록 자체**를
만드는 표(_ARTIFACT_PROGRESS_TOOLS·_COMMIT_CHAINS·_READ_ONLY_FORBIDDEN_TOOLS)는 agent.py 쪽에
있으므로 이 모듈은 agent.py 를 불러오면 안 된다.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .answer_hygiene import _ARTIFACT_PROGRESS_TOOLS, _ARTIFACT_STAGE_SUPPORT, _COMMIT_CHAINS
from .code_look_gate import _READ_ONLY_FORBIDDEN_TOOLS
from .stuck_hands import _ROUTE_REFUSAL, _ROUTE_WHOLE_LIST_MAX_SHARE, _STAGE_REFUSALS_BEFORE_NARROWING
from .transcript_policy import _TOOL_SCHEMA_CHARS_PER_TOKEN


def _unmet_action_tools(plan_results: list[tuple[Any, bool, str]]) -> frozenset[str]:
    """아직 안 한 **행동 요구**의 도구 이름(「드라이브에 올리기」 → google_drive_write)과 **그 사슬의 앞 걸음**.

    ★ 2026-10-04 도구 전수조사: 끝 도구(`google_drive_write`)만 넣어서, 산출물 차례에 그 앞 걸음
      (`google_drive_prepare_write`)이 `not_this_stage` 로 거절됐다 — 10-03 의 「시킨 행동의 손은 같이 받는다」가 반쪽이었다.
      사슬(`_COMMIT_CHAINS`)을 통째로 넣는다. 블로그 사슬은 뺀다 — 브라우저를 움직이는 걸음이라 산출물 차례에
      「더 열지 말고 파일을 만들어라」(2026-10-02 밤 9d6942f2)와 부딪힌다.
    """
    targets = frozenset(
        str(getattr(req, "target", "") or "")
        for req, ok, _ in plan_results or []
        if not ok and str(getattr(req, "kind", "")) == "action" and isinstance(getattr(req, "target", None), str)
    ) - {""}
    chained = {
        step
        for target in targets
        if not target.startswith("naver_blog_")
        for step in _COMMIT_CHAINS.get(target, ())
    }
    return targets | frozenset(chained)


def _focused_tool_definitions(
    tools: list[dict[str, Any]], stage: str, *, also: frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    """목표 전환 안내 뒤에는 그 단계를 끝낼 손만 남긴다."""
    if stage != "artifact":
        return tools
    # ★ 진척 판정(`_progress_matches_remaining_plan`)이 산출물 진전으로 치는 손과 **같은 목록**이어야 한다 (2026-10-02 밤).
    #   여기만 `local_edit_spreadsheet` 가 빠져 레딧 기록 판(98220347)에서 엑셀 덧붙이기가 `not_this_stage` 로 거절됐다 —
    #   「기존 행 아래 덧붙여」 예약 판이 덮어쓰기로 밀릴 수 있었다(사고 Q: 같은 것을 정하는 자리가 둘이면 어긋난다).
    # ★ 2026-10-03 「드라이브에 새 시트 만들어 레딧 반응 정리」 판(155bd3e1): 산출물 차례가 파일 쓰기 손만 받아서,
    #   파일을 만든 뒤 남은 「드라이브에 올리기」를 할 손이 없었다 — 한 번도 시도 못 하고 접혔다. 시킨 행동의 손(`also`)은 같이 받는다.
    #   보내기·발행 같은 되돌릴 수 없는 손이라도 여기서 받는 것은 **부를 수 있게** 할 뿐이다 — 승인 카드는 그대로 선다.
    # ★ 2026-10-03 레딧 기록 재실행(50bc9afe): 「기존 파일이 있으면 아래에 덧붙여」인데 그 파일을 읽는 손(`local_read_document`)이
    #   산출물 차례에 없어 두 번 거절됐고, 결국 새 파일 「(2)」에 썼다. 쓸 파일을 읽는 것은 산출물 일의 일부다(브라우저는 그대로 막는다).
    allowed = set(_ARTIFACT_PROGRESS_TOOLS) | set(also) | set(_ARTIFACT_STAGE_SUPPORT)
    focused = [
        tool
        for tool in tools
        if str((tool.get("function") or {}).get("name") or "") in allowed
    ]
    return focused or tools


def _offered_and_allowed(
    available: list[dict[str, Any]],
    focused: list[dict[str, Any]],
    *,
    final_answer_only: bool,
    refused: int = 0,
) -> tuple[list[dict[str, Any]], frozenset[str] | None]:
    """모델에게 **보낼** 목록과 이 걸음에 **부를 수 있는** 이름을 가른다 (2026-09-28 캐시 깨짐).

    보낼 목록은 기본으로 `available` 그대로다 — 판 도중 목록이 바뀌면 시스템 지시 뒤(≈2만 토큰)부터 다시 읽는다.
    단계가 손을 좁힐 때는 이름 집합으로 돌려주고, 부르면 디스패치에서 되돌려 보낸다. None 은 「전부 된다」.

    ★ 같은 날 확인 판(947a1d65): 되돌려 보내기만으로는 35B 가 안 따랐다 — `browser_open` 을 다섯 번 되풀이해 판이 멈췄다.
      그래서 **연달아 무시하면**(`refused`) 옛 방식으로 목록 자체를 좁힌다. 캐시가 한 번 깨지는 것이 판이 멈추는 것보다 싸다.
    """
    narrow = refused >= _STAGE_REFUSALS_BEFORE_NARROWING
    if final_answer_only:
        return ([] if narrow else available), frozenset()
    if focused is not available:
        return (focused if narrow else available), frozenset(str((tool.get("function") or {}).get("name") or "") for tool in focused)
    return available, None


def _artifact_turn_is_due(*, stage_says: bool, deliver_turn: bool, web_research: bool, read_sources: int) -> bool:
    """「파일을 만들 차례」(파일 쓰는 손만 받는다)를 지금 걸어도 되는가.

    ★ 2026-10-12 창 32K 의 9B · 가격 조사 세 판이 모두 이 문에서 끝났다. 한 판(eb13a02d)은 검색 한 번 뒤 모델이 도구 없이
      한마디 했고, 되받기 한 번에 차례가 걸려 가게 페이지를 여는 호출 둘이 `not_this_stage` 로 되돌아갔다 — 25초 · 3걸음 ·
      산출물 없음. **읽은 것이 하나도 없는데 쓸 차례**였다. 차례를 둔 까닭(10-02 · 9d6942f2)은 「글 6개를 읽고도 더 열기만
      하다 엑셀을 못 썼다」였다 — 읽은 것이 있는 판의 일이다. 조사 판은 본문을 하나라도 받아 온 뒤에 건다.
    ★ 걸음이 바닥나기 전에 주는 차례(`deliver_turn`)는 그대로 둔다 — 그 자리에서는 못 했다고 적어 내는 것이 맞다.
    """
    if deliver_turn:
        return True
    if not stage_says:
        return False
    return not (web_research and read_sources <= 0)


#: 어떤 판에서든 손에 있어야 하는 것. 갈래를 잘못 잡아도 이건 남는다.
#
# `self_check`·`self_heal` 은 판이 막혔을 때 스스로 보는 손이고, `skill_*` 은
# 어느 일에나 붙을 수 있다. 여기서 빼면 갈래 오판이 곧 판의 죽음이 된다.
_ALWAYS_ON_TOOLS = frozenset({
    "self_check", "self_heal", "skill_list", "skill_read",
    "shell_probe", "gpu_status", "clipboard_read", "clipboard_write",
    # 사람에게 선택지로 묻는 문(2026-09-30). 애매함은 갈래를 가리지 않는다.
    "ask_user",
})

#: 웹을 보고 와서 정리하는 판이 실제로 쓰는 접두사·이름.
#
# ★ 2026-09-09 실측으로 정했다. 조사·쓰기 28판에서 **쓰인 도구는 22종/133종**이고
#   111종(83%)은 한 번도 안 불렸다. 그런데 스키마 13,926토큰이 **매 걸음** 다시 실린다.
#
#   비용보다 나쁜 것은 **주의**다. 「YES24에서 파이썬 책 쪽수」 판이
#   `career_strategy_lookup(job="데이터 사이언티스트", region="부산")` 을 **6번**,
#   `schedule_list` 를 **4번** 불렀다 — 25걸음 중 13걸음(52%)이 과제와 무관했고,
#   그래서 3권 중 1권만 읽고 파일도 못 만들었다. 갈래 판정은 「자사DB 아님」으로
#   정확히 나왔는데 **그 판정이 도구 목록을 줄이지는 않았다.**
#
#   그렇다고 통째로 빼면 안 된다 — 이 저장소가 네 번 겪은 병이 「도구는 순서에
#   없으면 안 쓰인다」이다. 그래서 **지우지 않고 갈래별로 준다.**
_WEB_RESEARCH_PREFIXES = ("browser_", "site_", "ui_", "naver_web", "open_url",
                          "local_write", "local_edit", "local_read",
                          "artifact_", "sandbox_", "google_drive_",
                          # ★ 2026-10-04 도구 전수조사 2-F: 시스템 지시가 쓰라는 조사 API(「GitHub 탐색은 github_search」)와
                          #   내 PC 파일을 찾는 손이 조사 판 목록에서 빠져 있었다 — 「내 문서의 계약서 두 개 비교」에서
                          #   찾을 손이 없어 경로를 짐작했다. 메일·일정은 **읽는** 손만. 이 갈래를 만든 이유였던 헛손
                          #   (진로DB·일정 만들기·카메라, 2026-09-09)은 그대로 빼 둔다.
                          "github_", "reddit_", "hackernews_", "naver_news", "google_trend",
                          "local_list_directory", "local_search_files", "local_glob", "local_grep",
                          "local_request_path_access", "google_gmail_search", "google_calendar_upcoming")


def _is_web_research_job(plan: list[Any], prompt: str, declared: bool = False) -> bool:
    """이 판이 「가서 보고 와서 정리하는」 일인가. **계획으로 판정한다.**

    낱말표로 하지 않는 이유는 이 저장소가 그 자리로 여러 번 샜기 때문이다
    (「파이썬 책」이 코딩으로, 따옴표 안 검색어가 코드 대상으로). 계획 층은 이미
    「어느 사이트에서」·「몇 개를 열어 읽어라」를 뽑아 두었으므로, 그 결과를 보면
    낱말을 다시 읽을 이유가 없다.

    조건: **사이트 요구가 있거나 읽기 개수 요구가 있고**, 코드·검증 요구가 없다.
    코드 판은 `local_grep`·`local_run_project_command` 가 필요한데 그건 이 갈래의
    접두사 표에 없다 — 잘못 걸리면 코드 판이 손을 잃는다.

    ★ `declared` (2026-10-11) — 켠 스킬팩이 「이 스킬의 일은 웹을 보고 와서 정리하는 일」이라고 적어 왔다(`packs.WORK_KINDS`).
      가격 조사 스킬팩의 판은 사람의 말(「○○ 가격 조사」 + 「엑셀로 정리해 줘」)에서 「파일 만들기」만 뽑혀 이 갈래에 못 들었다.
      그래서 창 49,152 에서 도구 123개(첫 호출 28,205토큰)를 받았고, 쓰기 전 숫자 대조도 꺼진 채 돌았다. 시키는 말에
      「3개를 직접 읽고」를 넣어 요구로 잡히게 해 봤더니(판 092a5347) 목록은 줄었지만(21,476토큰) 그 요구가 엉뚱한 페이지로
      채워져 세 번째 가게를 여는 손이 막혔다. 요구를 보태지 않고 갈래만 받는다. 실행·검증이 걸린 판은 적어 와도 안 좁힌다.
    """
    kinds = {str(getattr(item, "kind", "") or "") for item in plan or []}
    if kinds & {"verify", "action"}:
        return False          # 실행·검증이 걸린 판은 코드 쪽 손이 필요하다
    # ★ **「실제로 읽기」 하나뿐이고 읽을 곳이 내 PC(경로 · 프로그램 창)면 웹 갈래가 아니다** (2026-10-17 화면 자동화 측정 dab5bddc).
    #   「C:\…\welcome.hwp 를 한글 프로그램으로 열어 PDF 로 저장해 줘」에 「내 PC 를 봐야 한다」 이유로 읽기 요구가 붙었고, 그것만으로
    #   판 전체가 웹 갈래가 되어 창 도구 · 한글 도구가 `not_this_route` 로 막혔다 — 모델은 「창 조작 도구가 없다」며 첫 걸음에 되물었다.
    #   사이트 · 개수 · 거르개 요구가 있거나 웹 주소를 댔으면 그대로 웹 갈래다.
    if (not declared and kinds & {"site", "count", "observe", "filter"} == {"observe"}
            and _LOCAL_TARGET.search(" ".join((prompt or "").split())) and not _WEB_ADDRESS.search(prompt or "")):
        return False
    return bool(declared) or bool(kinds & {"site", "count", "observe", "filter"})


#: 요청이 **내 PC 의 프로그램 창을 조작하라는** 것인가 — 경로만 댄 파일 요청은 아니다(그 판들은 웹 갈래에서 잘 돈다 ·
#: 2026-10-17 운영 요청 대조에서 경로 기준은 문서 요약 · 워드 만들기 40건 가까이를 같이 옮겨 좁혔다).
_LOCAL_TARGET = re.compile(
    r"(?:작업\s*관리자|메모장|그림판|계산기|한글\s*프로그램|엑셀\s*프로그램|워드\s*프로그램)[^.!?\n]{0,16}(?:열어|열고|켜|창|화면|메뉴)"
    r"|(?:프로그램|앱|한글|엑셀|워드|메모장)\s*창(?:을|에서|의)?\s*(?:직접\s*)?(?:조작|열어|읽)"
)
_WEB_ADDRESS = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|co\.kr|kr|io)\b", re.I)


def _route_refusals(steps: list[dict[str, Any]]) -> int:
    """이 판에서 갈래 밖의 손을 불러 되돌려 보낸 횟수. 연달아가 아니라 **판 전체**로 센다 —
    한 번 좁히면 그 판은 끝까지 좁힌 채로 둔다(좁혔다 넓혔다 하면 그때마다 앞머리 캐시가 깨진다)."""
    return sum(1 for step in steps if str(step.get("error") or "") == _ROUTE_REFUSAL)


def _route_hands(
    whole: list[dict[str, Any]], scoped: list[dict[str, Any]], *, window: int, refused: int,
) -> frozenset[str] | None:
    """조사 판에 **전체 목록을 그대로 보여 줄 수 있으면**, 그 판에서 되돌려 보낼 **갈래 밖의 이름들**. 좁힌 목록을 보내야 하면 None.

    돌려주는 것이 「부를 수 있는 이름」이 아니라 「막는 이름」인 까닭: 하네스는 목록에 없는 손으로 바꿔 부르기도 한다
    (검색 호출을 지목한 사이트 열기로 바꾸는 것 등). 보여 준 목록에 없다고 막으면 그 길까지 막힌다 — 처음에 그렇게 짰다가
    회귀 2건이 잡았다. 막는 것은 **전체에는 있고 웹 갈래에는 없는 이름**뿐이다.

    ## 왜 (2026-10-07 서버 기록)

    도구 목록은 프롬프트 **맨 앞**에 그려진다. 웹 조사 판만 좁힌 목록(79개)을 받고 그 밖의 판은 전체(123개)를 받으니,
    두 종류의 판이 번갈아 올 때마다 2만~2만 7천 토큰(7~10초)을 처음부터 다시 읽었다 — 하루에 54번.
    같은 목록끼리 이어지면 5,406토큰 · 2.2초다.

    그래서 조사 판에도 같은 목록을 **보여 주고**, 갈래 밖의 손은 부르면 디스패치에서 되돌려 보낸다
    (`_ROUTE_REFUSAL` — 단계 손의 `_offered_and_allowed` 와 같은 방식). 좁힌 까닭(2026-09-09: 책 조사 판이 진로DB 를
    6번 불렀다)은 그대로 막힌다 — 헛손이 **실행되지 않는다.**

    전체 목록을 안 보여 주는 때(좁힌 목록을 보낸다 — 예전 그대로):
      - 이 판에서 이미 두 번 되돌려 보냈다. 안내를 안 따르는 판이다(35B 도 그런 판이 있었다 — 09-28).
      - 더 실리는 도구 정의가 창의 5% 를 넘는다. 창이 작은 모델은 그 자리가 본문을 읽을 자리다.
        (운영 목록 123개 − 79개 ≈ 5,700토큰: 256K 에서 약 2% · 128K 에서 약 4% · 64K 에서 약 9% — 64K 이하는 예전처럼 좁힌다.
        128K 는 조건에 들지만 **그 창에서 돌려 본 적은 없다.**)
    """
    if scoped is whole or len(scoped) == len(whole) or refused >= _STAGE_REFUSALS_BEFORE_NARROWING or window <= 0:
        return None
    extra_chars = len(json.dumps(whole, ensure_ascii=False)) - len(json.dumps(scoped, ensure_ascii=False))
    # 도구 정의는 영어 이름·JSON 뼈대와 한국어 설명이 섞여 있다 — 실측(123개 목록 − 79개 목록 ≈ 5,700토큰)으로 글자당 토큰을 잡는다.
    if extra_chars / _TOOL_SCHEMA_CHARS_PER_TOKEN > window * _ROUTE_WHOLE_LIST_MAX_SHARE:
        return None
    inside = {str((tool.get("function") or {}).get("name") or "") for tool in scoped}
    outside = frozenset(
        name for tool in whole if (name := str((tool.get("function") or {}).get("name") or "")) and name not in inside
    )
    return outside or None


def _route_scoped_tool_definitions(
    tools: list[dict[str, Any]], *, web_only: bool
) -> list[dict[str, Any]]:
    """이 판의 갈래에 맞는 손만 남긴다. **지우는 것이 아니라 고르는 것이다.**

    `web_only` 는 「가서 보고 와서 정리하는 판」이라는 뜻이다. 그 판에 카메라·일정·
    메일·입시DB·한글편집이 손에 있을 이유가 없고, 있으면 실제로 헤맨다(위 실측).

    안전장치 둘:
      - `_ALWAYS_ON_TOOLS` 는 무조건 남긴다. 갈래 오판이 판의 죽음이 되면 안 된다.
      - 추린 결과가 비면 **원래 목록을 그대로 돌려준다.** 접두사 표가 낡아
        아무것도 안 남는 날, 조용히 손 없는 판이 되는 것이 제일 나쁘다.
    """
    if not web_only:
        return tools
    kept = [
        tool
        for tool in tools
        if (name := str((tool.get("function") or {}).get("name") or ""))
        and (name in _ALWAYS_ON_TOOLS or name.startswith(_WEB_RESEARCH_PREFIXES))
    ]
    return kept or tools


#: 바깥 서비스에 **올리는** 손 — 그 서비스를 사용자가 말했을 때만 연다.
#
# ★ 2026-09-18 실측(섀도 DOM 벤치 ms_detail): 「MS 스토어에서 ChatGPT 앱의 **게시자**와 별점을 알려줘」에서
#   모델이 답을 다 만들어 놓고 채팅으로 주는 대신 `naver_blog_prepare_post` → `naver_blog_fill_editor` 를 불렀다.
#   네이버 로그인이 없어 막혔을 뿐, 로그인돼 있었으면 사용자 블로그 편집기에 글이 들어갔다. 요청에 블로그의
#   「블」 자도 없었다(「게시자」의 게시 · 번역된 스토어 메뉴의 「블로그」에 끌린 것으로 보인다).
#   프롬프트로 타이르지 않는다(사고 R) — 요청(최근 사용자 발화 포함)에 그 서비스가 없으면 **보이지도, 실행되지도** 않는다.
_PLATFORM_WRITE_SUBJECTS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("naver_blog_",), ("블로그", "포스팅", "포스트", "blog"), "네이버 블로그"),
    (("google_gmail_prepare_send", "google_gmail_send"), ("메일", "gmail", "지메일", "편지"), "메일 보내기"),
    (
        ("google_calendar_prepare_create", "google_calendar_create", "google_calendar_prepare_update",
         "google_calendar_update", "google_calendar_prepare_delete", "google_calendar_delete"),
        ("일정", "캘린더", "calendar", "약속", "미팅", "회의", "스케줄"),
        "캘린더 일정",
    ),
)


#: 계획이 세운 행동 요구로는 **열지 않는** 서비스. 블로그는 「게시자」·「publisher」를 발행으로 읽은 전례가 있어 낱말로만 연다.
_PLATFORM_OPENED_BY_WORDS_ONLY = frozenset({"네이버 블로그"})


def _platform_write_unrequested(name: str, request_text: str, planned: frozenset[str] | set[str] = frozenset()) -> str:
    """이 손이 **말하지 않은 서비스에 올리는 것**이면 그 서비스 이름, 아니면 빈 값.

    ★ `planned` — 계획 층이 **요구로 세운 행동의 도구**(2026-10-04 도구 전수조사 2-G). 영어 「Send an email to …」·
      「Schedule a meeting …」은 계획이 「메일 발송」·「일정 등록」을 요구로 세우는데, 이 문은 한국어 낱말과
      `gmail`·`calendar` 만 봐서 손이 목록에서 빠지고 불러도 「보내라고 하지 않았다」로 거절됐다 — 요구는 서는데 손은 없었다.
      낱말표를 넓히지 않는다(같은 판정을 두 곳이 따로 하면 또 갈린다). 계획이 그 가족의 행동을 세웠으면 연다.
      블로그는 예외로 낱말로만 연다(`_PLATFORM_OPENED_BY_WORDS_ONLY`).
    """
    lowered = (request_text or "").lower()

    def in_family(tool: str, prefixes: tuple[str, ...]) -> bool:
        return any(tool == prefix or (prefix.endswith("_") and tool.startswith(prefix)) for prefix in prefixes)

    for prefixes, subjects, label in _PLATFORM_WRITE_SUBJECTS:
        if in_family(name, prefixes):
            if any(subject in lowered for subject in subjects):
                return ""
            if label not in _PLATFORM_OPENED_BY_WORDS_ONLY and any(in_family(str(tool), prefixes) for tool in planned or ()):
                return ""
            return label
    return ""


#: **작은 컨텍스트**(예: 8GB 노트북 4B 의 32K)에서만 — 그 이야기를 안 꺼낸 판에는 아예 안 싣는 도구 가족.
#
# ★ 2026-09-22 실측(`count_tool_tokens.py`): 일반 Cowork 는 도구 128개가 **18.4K 토큰 = 32K 의 56%** 다. 그중 이 셋이
#   입시·진로·문제은행 8개(10%) · 카메라 11개(6%) · 한글 4개(3%). 요청에 그 낱말이 없으면 쓰일 일이 없다.
#   Claude Code 는 도구 정의가 컨텍스트의 10% 를 넘으면 필요할 때만 불러온다(Haiku 급은 그 기능을 못 쓴다 → 작은 모델은 우리가 좁혀야 한다).
#   주력 경로(컨텍스트 큰 35B)는 건드리지 않는다 — 그쪽은 도구 선택 여유가 있고, 낱말표가 놓칠 위험을 질 이유가 없다.
#
#   낱말은 **넉넉하게** 잡는다(놓치면 그 도구가 판에서 사라진다). 그리고 `_ALWAYS_ON_TOOLS` 는 이 표에 없다.
_COMPACT_UNREQUESTED_FAMILIES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("admission_", "career_", "question_bank_", "official_exam_"),
        ("입시", "대학", "학과", "합격", "수능", "모평", "모의고사", "내신", "정시", "수시", "전형", "학종", "학생부", "세특",
         "진학", "진로", "직업", "연봉", "취업", "문제은행", "기출", "등급", "성적", "컷", "지원", "학교", "학원", "학생",
         "admission", "career", "exam"),
    ),
    (
        ("camera_",),
        ("카메라", "캠", "얼굴", "짐벌", "사람 찾", "누구", "누가", "라이브", "화면 보", "방 안", "앞에 있", "camera", "gimbal", "face"),
    ),
    (
        ("hwp_",),
        ("한글", "hwp", "hwpx", "아래한글"),
    ),
)


def _compact_family_unrequested(name: str, request_text: str) -> bool:
    lowered = (request_text or "").lower()
    for prefixes, subjects in _COMPACT_UNREQUESTED_FAMILIES:
        if name.startswith(prefixes):
            return not any(subject in lowered for subject in subjects)
    return False


#: 작은 컨텍스트에서 이보다 긴 도구·인자 설명문은 앞부분만 남긴다. 실측 중앙값이 78자라 대부분은 그대로다.
_COMPACT_DESCRIPTION_CHARS = 140
_COMPACT_PARAM_DESCRIPTION_CHARS = 70


def _clip_description(text: str, limit: int) -> str:
    """문장 경계에서 자른다. 경계가 없으면 글자 수에서 자르고 …을 붙인다."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for mark in ("。", ". ", "다. ", "요. ", "다 ", "\n"):
        at = cut.rfind(mark)
        if at >= limit // 2:
            return cut[: at + len(mark)].rstrip()
    return cut.rstrip() + "…"


def _compact_tool_descriptions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """긴 설명문만 줄인다. **이름·인자·타입·필수 여부는 그대로다** — 호출 계약을 건드리지 않는다."""
    compacted: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") or {}
        description = str(function.get("description") or "")
        parameters = function.get("parameters") or {}
        properties = parameters.get("properties") if isinstance(parameters, dict) else None
        needs_param_trim = isinstance(properties, dict) and any(
            isinstance(spec, dict) and len(str(spec.get("description") or "")) > _COMPACT_PARAM_DESCRIPTION_CHARS
            for spec in properties.values()
        )
        if len(description) <= _COMPACT_DESCRIPTION_CHARS and not needs_param_trim:
            compacted.append(tool)
            continue
        new_function = dict(function)
        new_function["description"] = _clip_description(description, _COMPACT_DESCRIPTION_CHARS)
        if needs_param_trim:
            new_properties = {
                key: (
                    {**spec, "description": _clip_description(str(spec["description"]), _COMPACT_PARAM_DESCRIPTION_CHARS)}
                    if isinstance(spec, dict) and len(str(spec.get("description") or "")) > _COMPACT_PARAM_DESCRIPTION_CHARS
                    else spec
                )
                for key, spec in properties.items()
            }
            new_function["parameters"] = {**parameters, "properties": new_properties}
        compacted.append({**tool, "function": new_function})
    return compacted


def _platform_scoped_tool_definitions(
    tools: list[dict[str, Any]], request_text: str, *, compact: bool = False,
    planned: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """요청에 없는 서비스에 올리는 손을 모델 표면에서 뺀다. `compact` 면(작은 컨텍스트) 이야기가 안 나온 도구 가족도 뺀다."""
    kept: list[dict[str, Any]] = []
    for tool in tools:
        name = str((tool.get("function") or {}).get("name") or "")
        if _platform_write_unrequested(name, request_text, planned):
            continue
        if compact and name not in _ALWAYS_ON_TOOLS and _compact_family_unrequested(name, request_text):
            continue
        kept.append(tool)
    return kept


#: **작은 창의 조사 판**이 받는 묶음 — 「찾아서 읽고 파일로」 (2026-10-12 · 스위치 `small_window_research_bundle` — 10-13 부터 기본 켜짐, 까닭은 `config.py`).
#
# ★ 그날 밤 창 32K 의 조사 판은 첫 프롬프트가 19,800토큰(창의 60%)이었다. 답 쓸 자리 8,192 를 떼면 읽은 페이지를 담을 자리가
#   4,800토큰쯤이라 가게 한 곳을 읽으면 앞 가게가 밀려났고, 9B · 4B 의 가격 조사는 9줄 중 1~3줄이었다. 그 판이 받는 도구는
#   81개(어림 9,900토큰)인데, 최근 열흘 브라우저를 쓴 649판의 호출 9,396번 가운데 83% 가 아래 스무 개였다
#   (`bench/device_audit/tools_called.py`). 이 묶음 + 늘 싣는 손은 29개 · 어림 3,600토큰이다.
# ★ 큰 창은 건드리지 않는다 — 거기서는 목록을 판 내내 그대로 두는 것이 이긴다(앞머리 캐시 · 09-28). 작은 창은 다시 읽는 값이
#   싸고(9B 가 1초에 1,400~1,900토큰) 자리가 귀하다.
# ★ 묶음 밖의 손을 **막지는 않는다.** 목록에서 뺄 뿐이라 계획이 세운 행동의 손(`planned`)은 그대로 실리고, 하네스가 바꿔 부르는
#   손도 실행된다. 화면 조작(채우기 · 고르기) · 코드 · 사진은 다른 묶음의 일이다 — 묶음을 판 도중에 바꿔 주는 것은 아직 없다.
_SMALL_WINDOW_RESEARCH_BUNDLE = frozenset({
    "browser_open", "browser_search", "browser_site_search", "browser_open_result", "browser_extract", "browser_read",
    "browser_find", "browser_snapshot", "browser_click", "browser_scroll", "browser_page_data", "browser_links",
    "browser_load_more", "browser_back", "browser_close", "site_list", "site_run",
    "local_write_document", "local_edit_spreadsheet", "local_read_document",
})


def _small_window_research_tools(
    tools: list[dict[str, Any]], *, enabled: bool, compact: bool, web_research: bool,
    planned: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """작은 창의 조사 판이면 묶음 · 늘 싣는 손 · 계획이 세운 손만 남긴다. 그 밖의 판은 받은 목록 그대로다.

    순서는 받은 목록 그대로 둔다(판마다 앞머리가 같아야 한다). 추린 것이 비면 원래 목록을 돌려준다 — 손 없는 판을 만들지 않는다.
    """
    if not (enabled and compact and web_research):
        return tools
    keep = _SMALL_WINDOW_RESEARCH_BUNDLE | _ALWAYS_ON_TOOLS | frozenset(planned or ())
    kept = [tool for tool in tools if str((tool.get("function") or {}).get("name") or "") in keep]
    return kept or tools


def _read_only_tool_definitions(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """명시적 읽기 전용 판에서 상태를 바꾸는 손을 모델 표면에서 제거한다."""
    return [
        tool
        for tool in tools
        if str((tool.get("function") or {}).get("name") or "")
        not in _READ_ONLY_FORBIDDEN_TOOLS
    ]
