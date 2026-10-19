"""코드 판의 관문 — 보기·되받기·손 좁히기 (agent.py 에서 2026-10-09).

「저장소를 바꾸는 손」이 나오지 않은 판을 어떻게 잡을지,
읽기 루프를 어떻게 끊을지, 검증을 안 돌린 판을 어떻게 좁힐지 —
판의 걸음(스텝)을 보고 결정하는 순수 함수 모음.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .stuck_hands import _STAGE_REFUSALS_BEFORE_NARROWING

#: 코드 판에서 **저장소를 바꾸는** 손. 이게 한 번도 안 나오면 아직 아무 일도
#: 안 한 것이다.
_CODE_WRITE_TOOLS = frozenset({
        "local_write_document", "local_edit_spreadsheet", "local_edit_document","local_write_file", "local_apply_edit", "local_delete_file"})

# 사용자가 「조사·분석만」이라고 묶은 판에서는 모델에게 보이지도, 혹시 이름을
# 기억해 호출하더라도 실행되지도 않아야 하는 손. L1은 읽기와 쓰기가 섞여 있어
# 위험등급만으로는 이 계약을 지킬 수 없다.
_READ_ONLY_FORBIDDEN_TOOLS = _CODE_WRITE_TOOLS | frozenset(
    {
        "artifact_from_observations",
        "sandbox_run",
        "local_run_project_command",
        "hwp_preview_edit",
        "hwp_apply_edit",
        "hwp_preview_format",
        "hwp_apply_format",
        "hwp_export_pdf",
        "clipboard_write",
        "windows_execute_preview",
        "browser_click_confirmed",
        "site_draft_recipe",
        "site_promote_draft",
        "google_drive_prepare_write",
        "google_drive_write",
        "google_gmail_prepare_send",
        "google_gmail_send",
        "google_calendar_prepare_create",
        "google_calendar_create",
        "google_calendar_prepare_update",
        "google_calendar_update",
        "google_calendar_prepare_delete",
        "google_calendar_delete",
        "naver_blog_prepare_post",
        "naver_blog_fill_editor",
        "naver_blog_prepare_save_draft",
        "naver_blog_save_draft",
        "naver_blog_prepare_publish",
        "naver_blog_publish",
        "schedule_create",
        "schedule_cancel",
        "self_heal",
        "camera_register_face",
        "camera_register_new_person",
        "camera_forget_face",
    }
)

#: 계약으로 읽기 전용인 판에서는 세우지 않는 요구. 전부 위 손이 있어야 채워진다
#: (행위·산출물·각주·실행 검증·행위 개수). 읽기·개수·사이트·관찰 요구는 그대로 둔다.
_READ_ONLY_UNMEETABLE_KINDS = frozenset(
    {"action", "artifact", "footnote", "verify", "count_action"}
)

#: 맡긴 쪽이 정한 확인 명령을 하네스가 대신 돌려 주는 횟수의 끝. 넘기면 통과하지 못한 채로 끝내고 「일부」로 적는다.
_DECLARED_CHECK_RUNS = 4

#: 저장소를 **보기만** 하는 손.
_CODE_LOOK_TOOLS = frozenset({
    "local_index_codebase", "local_list_directory", "local_search_files",
    "local_grep", "local_glob",
    "local_read_text_file", "local_read_document",
})

#: 이만큼 보기만 하고 한 번도 안 고쳤으면 되받는다. (진단값 `looks_without_write` 의 눈금 — 관문은 아래 `looking_in_circles` 가 정한다.)
_LOOKS_WITHOUT_WRITE_LIMIT = 10
#: **이미 본 것을 이만큼 다시 보면** 헛도는 것으로 본다.
_RELOOKS_LIMIT = 5
#: 새 것만 보더라도 이만큼 보기만 했으면 한 번은 되받는다 — 안전망.
_LOOKS_BACKSTOP = 30
#: 보기 한 번의 **대상**. 같은 손으로 같은 곳을 같은 범위로 보면 같은 보기다.
_LOOK_TARGET_KEYS = ("path", "paths", "pattern", "query", "glob", "line_start", "line_end")


def _look_mark(step: dict[str, Any]) -> str:
    arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
    target = {key: arguments.get(key) for key in _LOOK_TARGET_KEYS if key in arguments}
    return str(step.get("tool") or "") + json.dumps(target, ensure_ascii=False, sort_keys=True, default=str)


def stalled_looks(steps: list[dict[str, Any]], *, since_attempt: bool = False) -> tuple[int, int]:
    """마지막 성공한 쓰기(`since_attempt` 면 쓰기 **시도**) 뒤로 — (이 판에서 이미 본 것을 **다시 본** 횟수, 본 횟수).

    ## 왜 횟수가 아니라 「다시 보기」인가 (2026-10-09 새벽 — 우리 숙제를 손자리에게 맡긴 판 7958e32b)

    관문은 「열 번 보기만 했으면 고쳐라」였다(2026-08-28 · 66개 파일 저장소 · 읽기 → 목록 → 읽기 → 목록을 되풀이한 판).
    1만 3천 줄짜리 파일 셋을 건드려야 하는 기능 과제에서 모델은 **서로 다른 곳 37군데**를 읽었고 되풀이는 0번이었다 —
    헛돈 것이 아니라 탐색이었다. 그런데 관문이 열 번마다 걸려 쓰는 손만 남겼고, 모델은 읽지 못한 채 고치려다
    세 번 실패했다(`old_text_not_found` · `old_text_not_unique`). 그 사이 도구 목록이 여섯 번 뒤집혀 대화 전체를
    다섯 번 다시 읽었다(다시 읽기 841초 가운데 264초 — 서버 기록).

    운영 코드 판에 대 본 것(보기가 열 번 넘게 이어진 40판):
      · 새 것만 본 판 24개 — 19개가 제대로 끝났다(다시 본 것 0~1번).
      · 같은 것을 다시 본 판 13개(다시 본 것 6~23번) — 9개가 실패·중단.
    헛도는 판은 같은 것을 또 보고, 일하는 판은 새 것을 본다. 2026-08-28 의 원래 사고도 그 모양이었다
    (「같은 저장소를 여섯 번 색인」).
    """
    seen: set[str] = set()
    again = looks = 0
    for step in steps:
        tool = str(step.get("tool") or "")
        if tool in _CODE_WRITE_TOOLS:
            if since_attempt or bool(step.get("ok")):
                again = looks = 0
            continue
        if tool in _CODE_LOOK_TOOLS:
            mark = _look_mark(step)
            looks += 1
            if mark in seen:
                again += 1
            seen.add(mark)
    return again, looks


def looking_in_circles(steps: list[dict[str, Any]], *, since_attempt: bool = False) -> bool:
    """보기만 하며 **헛돌고 있는가** — 같은 것을 다시 보고 있거나(`_RELOOKS_LIMIT`), 새 것이라도 너무 오래 보기만 했다(`_LOOKS_BACKSTOP`)."""
    again, looks = stalled_looks(steps, since_attempt=since_attempt)
    return again >= _RELOOKS_LIMIT or looks >= _LOOKS_BACKSTOP


#: 「나아가지 않는다」의 눈금. 운영 코드 판 520개에 대 본 값이다(2026-10-09 · `not_getting_anywhere` 의 설명).
#: 같은 확인 실패가 **연달아** 이만큼.
_SAME_FAILURE_LIMIT = 4
#: 한 번도 돌려 보지 않고 **같은 파일을 통째로** 이만큼 다시 썼다.
_REWRITES_WITHOUT_RUN_LIMIT = 5
#: 마지막 이만큼의 걸음에 새로 본 것·성공한 변경·돌려 본 것이 하나도 없다.
_IDLE_STEPS_LIMIT = 20
#: 흘려 받는 도중에 「사람이 기다리나」를 보는 간격(초). 조각마다 보면 줄을 초당 수십 번 읽는다.
_YIELD_POLL_SEC = 2.0
#: 비켜 준 판의 멈춘 자리를 이만큼 둔다. 기본(30분)으로는 사람의 긴 일 하나에 사라진다 — 사라지면 처음부터 다시 돈다.
_YIELD_CHECKPOINT_TTL_SEC = 6 * 3600
#: 맡긴 판의 걸음 수 **안전망**. 운영에서 제대로 끝난 코드 판 360개의 최대가 65걸음이었다 — 그 세 배.
#: 시간이 아니라 걸음으로 둔다: 긴 시험 한 번이 10분을 쓰는 저장소에서 시간은 한 일을 재지 못한다.
_DELEGATED_STEPS_BACKSTOP = 200


def not_getting_anywhere(steps: list[dict[str, Any]]) -> str:
    """코드 판이 **제자리**인가 — 까닭 이름을 돌려준다. 나아가고 있으면 빈 글.

    ## 왜 시간이 아닌가 (2026-10-09 대표)

    코드 판은 검증 없이 20분을 넘기면 접혔다(`code_job_stall_sec` · 2026-09-22 — 작은 모델이 29분을 헛돈 판에서 나왔다).
    그런데 1만 줄짜리 파일 셋을 건드리는 기능 과제는 헛돌지 않고도 20분을 넘긴다. 그 밤의 숙제 2 는 27분 가운데 16분이
    하네스·워치독 손실이었고, 고친 뒤에도 일하는 중에 시간에 접혔다. 대표: 「저렇게 어려운 과제를 22분 만에 제한을 걸어
    두는 것도 이상하지 않나 — 회귀 한 번에도 물리적인 시간이 든다」. 사람과 함께 하는 개발도 30분을 넘기는 일이 흔하다.
    시간은 **일한 양**이 아니라 **기다린 양**까지 센다. 그래서 접는 기준을 「무엇을 되풀이하는가」로 옮긴다.

    ## 세 가지 제자리

      · `same_failure` — 확인을 돌릴 때마다 **같은 실패**(같은 `failure_fingerprint`)가 연달아 `_SAME_FAILURE_LIMIT` 번.
        그 사이에 무엇을 고쳤든 결과가 안 바뀌었다.
      · `rewriting` — 마지막으로 돌려 본 뒤로 **같은 파일을 통째로** `_REWRITES_WITHOUT_RUN_LIMIT` 번 다시 썼다.
        부분 고치기(`local_apply_edit`)는 안 센다 — 큰 파일을 여러 군데 고치는 정상 판이 같은 파일을 열 번도 고친다.
      · `nothing_new` — 마지막 `_IDLE_STEPS_LIMIT` 걸음에 처음 보는 것도, 성공한 변경도, 돌려 본 것도 없다.

    ## 넣기 전에 대 본 것 (운영 코드 판 520개 · 걸음 3 이상)

    이 값(4 · 5 · 20)으로 걸리는 판은 **3개**이고 셋 다 실패·중단으로 끝난 판이다(32걸음 가운데 31번째 · 76 가운데 68번째 ·
    138 가운데 17번째 — 마지막 것은 121걸음을 아꼈을 판이다). 제대로 끝난 360판에서는 0개.
    한 칸 조이면(3 · 4 · 14) 8개가 걸리는데 그중 2개가 **제대로 끝난 판**이다 — 그래서 여기에 둔다.
    표본이 작다(걸리는 판 3개). 맡긴 판에 먼저 붙이고, 걸린 판을 장부(`code_budget_exhausted.why`)로 다시 센다.
    """
    tail: list[str] = []
    for step in reversed(steps):
        if str(step.get("tool") or "") != "local_run_project_command":
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        fingerprint = str(evidence.get("failure_fingerprint") or "")
        if evidence.get("verified") or not fingerprint:
            break
        tail.append(fingerprint)
        if len(tail) >= _SAME_FAILURE_LIMIT:
            break
    if len(tail) >= _SAME_FAILURE_LIMIT and len(set(tail)) == 1:
        return "same_failure"
    rewrites: dict[str, int] = {}
    for step in reversed(steps):
        tool = str(step.get("tool") or "")
        if tool == "local_run_project_command":
            break
        if tool == "local_write_file" and step.get("ok"):
            arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
            key = str(arguments.get("path") or "").replace("/", "\\").casefold()
            rewrites[key] = rewrites.get(key, 0) + 1
    if rewrites and max(rewrites.values()) >= _REWRITES_WITHOUT_RUN_LIMIT:
        return "rewriting"
    if len(steps) >= _IDLE_STEPS_LIMIT:
        seen = {_look_mark(step) for step in steps[:-_IDLE_STEPS_LIMIT] if str(step.get("tool") or "") in _CODE_LOOK_TOOLS}
        for step in steps[-_IDLE_STEPS_LIMIT:]:
            tool = str(step.get("tool") or "")
            if tool == "local_run_project_command" or (step.get("ok") and tool in _CODE_WRITE_TOOLS):
                return ""
            if tool in _CODE_LOOK_TOOLS:
                mark = _look_mark(step)
                if mark not in seen:
                    return ""
                seen.add(mark)
            elif step.get("ok"):
                return ""  # 다른 종류의 성공한 걸음(화면 확인 등)은 한 일로 친다
        return "nothing_new"
    return ""


def offered_code_tools(
    profile_names: set[str] | frozenset[str] | None,
    active: set[str] | frozenset[str] | None,
    steps: list[dict[str, Any]],
) -> frozenset[str] | None:
    """모델에게 **보여 줄** 코드 손. 이 걸음에 받는 손(`active`)이 좁아져도 목록은 그대로 보낸다 (2026-10-09).

    도구 목록은 프롬프트 맨 앞에 그려진다 — 목록이 바뀌면 그 뒤 대화 전체를 다시 읽는다(2026-09-28 계측). 조사 판은 그날
    「목록은 그대로 보내고 부르면 되돌려 보낸다」(`_offered_and_allowed`)로 옮겼는데 코드 판의 두 관문(보기만 한다 ·
    검증을 안 돌린다)은 목록 자체를 좁히고 있었다. 7만 토큰짜리 판에서 한 번 뒤집힐 때마다 100초 안팎이었다.
    받는 손은 디스패치가 그대로 가른다(`name not in active_code_tools`). 되돌려 보낸 것을 **연달아 무시하면** 그때 목록을 좁힌다 —
    같은 날 확인한 대로, 말을 안 듣는 판은 캐시가 한 번 깨지는 것이 판이 멈추는 것보다 싸다.
    """
    if active is None:
        return None
    narrowed = frozenset(active)
    whole = frozenset(profile_names or narrowed)
    if narrowed == whole or not narrowed <= whole:
        return narrowed
    refused = 0
    for step in reversed(steps):
        if str(step.get("error") or "") != "code_tool_not_in_active_profile":
            break
        refused += 1
    return narrowed if refused >= _STAGE_REFUSALS_BEFORE_NARROWING else whole


#: 답에 붙일 주소의 최대 개수. 목록이 길면 사람이 안 읽고 전사만 먹는다.
_ADDRESS_BLOCK_LIMIT = 12

#: 목록처럼 보이는 답인가. 번호나 순위표가 있으면 다음 턴에 "저거 해줘"가 온다.
_LOOKS_LIKE_A_LIST = re.compile(r"^\s*(?:[1-9][0-9]?[.)]|\|\s*[1-9])", re.M)


def result_addresses(steps: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """이 판에서 만든 결과 목록의 (제목, 주소). 없으면 빈 목록.

    ★ 왜 필요한가 (2026-09-01 실측)

    「공고 찾아줘」에 순위표로 답한 다음 턴에 「저 순위대로 스크랩해줘」가 왔다.
    자비스는 **사람인을 새로 검색해서 새 rank 1~5 를 스크랩했다** — 앞 답의 그
    회사들이 아니라.

    셋 다 정상이었다:
      · 대화 이력은 들어갔다(`context_messages` 6개, 앞 답 포함)
      · 레시피도 맞다 — `scrap` 은 rank 가 아니라 `job_id`(rec_idx)를 받는다
      · `forget_results` 가 판 경계에서 순위를 버리는 것도 **옳다**
        (순위는 그 검색의 것이다 — 안 버리면 딴 사이트 순위로 남의 페이지를 연다)

    끊긴 곳은 하나였다. **앞 답에 주소가 없었다.** 기업명만 있으니 다음 턴이
    그것을 집을 방법이 없었고, 그래서 새로 검색할 수밖에 없었다.

    순위는 판을 넘길 수 없지만 **주소는 넘길 수 있다.** 그래서 답에 실어 보낸다.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        result = step.get("result")
        rows = result.get("results") if isinstance(result, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            title = str(row.get("title") or row.get("text") or "").strip()
            found.append((title[:90], url))
    return found[:_ADDRESS_BLOCK_LIMIT]


def with_addresses(answer: str, steps: list[dict[str, Any]]) -> str:
    """목록으로 답했으면 **주소를 같이 적는다.** 아니면 그대로 둔다.

    안내문으로 "주소를 적어라"라고 하면 안 적는다(사고 R, 준수율 6~12%). 그래서
    코드가 붙인다 — 이 저장소가 여러 번 확인한 그 규율이다.
    """
    if not answer or "http" in answer or not _LOOKS_LIKE_A_LIST.search(answer):
        return answer
    rows = result_addresses(steps)
    if len(rows) < 2:
        return answer
    lines = "\n".join(
        f"{index}. {title or '(제목 없음)'} — {url}" for index, (title, url) in enumerate(rows, 1)
    )
    head = (
        "\n\n[이 목록의 주소]\n"
        "다음에 「저거 해줘」라고 하실 때 이 주소로 집습니다. 순위는 검색마다 달라집니다.\n"
    )
    return answer.rstrip() + head + lines


def looks_without_write(steps: list[dict[str, Any]]) -> int:
    """마지막 쓰기 이후 저장소를 몇 번이나 보기만 했나.

    ## 왜 낱말이 아니라 행동인가 (2026-08-28)

    10과제 벤치에서 실패한 5건 중 **3건이 파일을 한 번도 안 고쳤다.** 20분 동안
    읽기 50회 · 쓰기 0회였고, 한 판은 같은 저장소를 **여섯 번** 색인했다.
    읽기 → 목록 → 읽기 → 목록 을 반복하는 탐색 루프였다.

    셋 다 「없는 심볼을 만들어야 하는」 과제였다. `AttributeError` 는 파일과 줄을
    가리키지만 `ImportError: cannot import name` 은 **"없다"만 말하고 어디에
    만들지는 안 말한다.** 그래서 모델이 없는 것을 계속 찾았다.

    기존 안전장치(`coding_verification_missing`)는 모델이 **답을 내려 할 때**만
    걸리는데, 이 판들은 답을 안 내고 계속 도구를 불렀다. 그래서 20분을 다 쓴
    뒤에야 죽었다. 루프 안에서 잡아야 한다.

    브라우저의 `_searches_without_read`, local_computer 의 `_listings_since_read`
    와 같은 규율이다 — **낱말이 아니라 행동을 본다.**
    """
    looks = 0
    for step in reversed(steps):
        tool = str(step.get("tool") or "")
        if tool in _CODE_WRITE_TOOLS:
            # ★ `ok` 를 봐야 한다 (2026-08-28). 예전에는 이름만 보고 끊어서
            # `old_text_not_found` 로 **실패한 편집도 카운터를 0 으로 되돌렸다.**
            # 실측(3fbeed24 마지막 판)에서 26·29·31 걸음이 전부 실패한 편집인데
            # 그때마다 「보기만 한 횟수」가 리셋돼, 20 걸음 넘게 읽기만 해도
            # 진단이 안 걸렸다. 시도와 성공이 같은 값이면 조용히 고장 난다.
            if bool(step.get("ok")):
                # 쓰기를 만나면 거기까지다. **0 이 아니라 그때까지 센 값**을 돌려준다 —
                # 고친 뒤에 또 열 번 넘게 보기만 하는 것도 같은 병이기 때문이다.
                break
            # 실패한 쓰기는 경계도 아니고 보기도 아니다. 그냥 지나간다.
            continue
        if tool in _CODE_LOOK_TOOLS:
            looks += 1
    return looks


def looks_since_write_attempt(steps: list[dict[str, Any]]) -> int:
    """쓰기를 **시도**한 뒤로 몇 번이나 보기만 했나.

    `looks_without_write` 와 분모가 다르다. 그쪽은 **성공한** 쓰기만 경계로 치는
    정직한 진단값이고, 이쪽은 성패를 안 가리는 관문용이다.

    둘을 쪼갠 이유(2026-08-28): 관문이 진단값을 그대로 쓰면 `old_text_not_found`
    가 난 판이 **교착**한다 — 쓰기전용 손만 남은 채로 정확한 줄을 다시 읽을 길이
    없어지기 때문이다. 그래서 관문은 「한 번이라도 손을 뻗었나」로 푼다.
    """
    looks = 0
    for step in reversed(steps):
        tool = str(step.get("tool") or "")
        if tool in _CODE_WRITE_TOOLS:
            break
        if tool in _CODE_LOOK_TOOLS:
            looks += 1
    return looks


def code_tools_after_look_pushback(
    tool_names: set[str] | frozenset[str],
    steps: list[dict[str, Any]],
    look_pushbacks: int,
) -> frozenset[str]:
    """두 번째 되받기마저 무시하면 다음 턴에는 쓰는 손만 보여 준다.

    안내문을 두 번 붙이고도 다시 읽기만 한 실측(3fbeed24: 29걸음·쓰기 0)을
    결정론으로 끊는다. 쓰기를 한 번 **시도**하면 원래 도구를 다시 보여 준다.
    ``old_text_not_found`` 뒤에는 정확한 줄을 다시 읽어야 고쳐 나갈 수 있기 때문이다.

    ★ 그래서 여기서는 `looks_without_write` 가 아니라 `looks_since_write_attempt`
    를 쓴다(2026-08-28). 진단값은 성공한 쓰기만 경계로 치도록 고쳤는데, 관문이
    그 값을 쓰면 실패한 편집 뒤에 손이 묶여 교착한다.
    """
    allowed = frozenset(tool_names)
    # ★ 2026-10-09: 횟수가 아니라 **헛도는가**로 건다(`stalled_looks`). 새 것을 읽는 중인 판의 손은 묶지 않는다.
    if (
        look_pushbacks >= 2
        and looking_in_circles(steps, since_attempt=True)
    ):
        write_tools = allowed & _CODE_WRITE_TOOLS
        if write_tools:
            # 묻는 손은 「또 보기」가 아니다 — 허용 밖 경로를 헤매던 판이 물을 손까지 잃지 않게 (2026-10-04 전수조사 14).
            return write_tools | (allowed & _CODE_ASK_HANDS)
    return allowed


#: 검증을 되받은 뒤에 남기는 손. 고치고(쓰기) · 돌리고(실행) · 임시 스크립트를 지우는 것뿐이다.
_CODE_VERIFY_HANDS = frozenset({
    "local_run_project_command", "local_write_file", "local_apply_edit", "local_delete_file",
})
#: ★ 화면으로 검증하는 손도 남긴다 (2026-10-04 사다리 L1). 2026-09-30 부터 「이 PC 안 페이지를 만진 뒤 읽기」도 검증인데
#:   (`code_runtime.browser_verification_indices`), 좁힌 손에는 브라우저가 없었다. 되받기는 「눌러 본 뒤 browser_read 로
#:   읽어라」고 하는데 읽을 손이 없어, 모델은 남은 손(파일 쓰기)으로 임시 스크립트를 만들었고 — 그게 코드 변경으로 세어져
#:   누른 것까지 무효가 됐다. 채점은 통과한 판이 `coding_verification_missing` 으로 끝났다. 안내와 손이 어긋나면 안 된다.
#: 손을 좁힐 때도 남기는 **묻는 손**. 4B 가 묻기로 도망가는 것은 한 판 상한이 따로 막는다.
_CODE_ASK_HANDS = frozenset({"ask_user", "local_request_path_access"})
_CODE_SCREEN_VERIFY_HANDS = frozenset({
    "local_preview_page", "browser_open", "browser_snapshot", "browser_read", "browser_extract", "browser_verify",
    "browser_click", "browser_click_at", "browser_fill", "browser_fill_form", "browser_type_at", "browser_press",
    "browser_select_option", "browser_pick_suggestion",
})


def code_tools_after_coding_pushback(
    tool_names: set[str] | frozenset[str],
    coding_pushbacks: int,
    *,
    verified: bool,
    attempted_since_pushback: bool = False,
    mutated: bool = True,
    screen_check: bool = False,
) -> frozenset[str]:
    """검증을 한 번 되받고도 아직 안 돌렸으면 다음 턴에는 검증하는 손만 보여 준다.

    ## ★ 고칠 것이 없는 판에는 걸지 않는다 (2026-09-21 밤, 노트북 사다리 fin1 이 잡음)

    이 좁히기는 **파일을 만들고도 안 돌린** 판(AURORA)을 위한 것이다. 그런데 아직 아무것도
    고치지 않은 판이 「직접 읽어 보겠다」고 말만 하고 끝내려다 되받기를 맞으면, 다음 턴에
    읽기·검색이 빠진 채 쓰기·실행 손 넷만 남았다 — 고칠 줄을 **읽을 길이 없어** 세 번을 튕기고
    (`code_tool_not_in_active_profile`, 0ms) 죽었다. 18판 중 세 판(L4·L6 두 번)이 이렇게 졌고
    채점은 15/18 → 13/18 이었다. 검증할 것이 없으면(성공한 쓰기·편집이 없으면) 좁히지 않는다.

    ## 왜 (2026-09-21 저녁 AURORA 5판)

    7걸음에 파일을 만들고 브라우저로 화면까지 봤는데 ``local_run_project_command`` 는
    한 번도 안 불렀고, 답을 세 번 내려다 ``coding_verification_missing`` 으로 죽었다.
    프롬프트에 「검증하라」고 적혀 있었다. **안내문은 안 먹는다**(사고 R) — 그래서
    읽기 루프(`code_tools_after_look_pushback`)와 같은 방식으로 손을 좁힌다.

    되받기 첫 번째는 말로 하고(기존), 그것을 무시한 **두 번째 턴부터** 좁힌다.
    검증이 이미 현재 코드에 대해 성공했으면 좁히지 않는다 — 그때는 검토 턴이 이어진다.
    검증 도구 자체가 이 판의 손에 없으면(읽기 전용 등) 좁히지 않는다 — 교착 방지.

    ★ 되받은 **뒤에 손을 한 번이라도 뻗었으면**(성패 불문) 원래 도구를 돌려 준다.
    좁힌 손에서 ``local_apply_edit`` 가 ``old_text_not_found`` 로 실패하면 정확한 줄을
    다시 읽을 길이 없어 교착한다 — 읽기 루프가 겪은 것과 같은 모양이다
    (`looks_since_write_attempt` 주석). 그 뒤 또 말로만 답하면 되받기가 다시 걸려
    다시 좁혀진다.
    """
    allowed = frozenset(tool_names)
    if coding_pushbacks < 1 or verified or attempted_since_pushback or not mutated:
        return allowed
    # 화면 손은 **페이지를 만든 판**(`screen_check`)에서만 남긴다. 파이썬만 고치는 판에서 브라우저가 남으면
    # 「또 보기만」 하는 길이 열려 2026-09-21 의 다섯 판이 되살아난다 — 그쪽은 예전 그대로 넷이다.
    hands = allowed & (_CODE_VERIFY_HANDS | (_CODE_SCREEN_VERIFY_HANDS if screen_check else frozenset()))
    if "local_run_project_command" not in hands:
        return allowed
    return hands | (allowed & _CODE_ASK_HANDS)


#: 브라우저로 열어 확인하는 것이 곧 검증인 파일 — 정적 페이지와 그 곁가지.
_PAGE_SUFFIXES = (".html", ".htm", ".css", ".js", ".mjs", ".jsx", ".tsx", ".vue", ".svelte")


def _made_a_page(steps: list[dict[str, Any]]) -> bool:
    """이 판이 **페이지를 만들거나 고쳤는가** — 그러면 화면으로 확인하는 손을 검증 손에 남긴다.

    성공한 쓰기·편집의 대상이 페이지 파일이거나, 만든 페이지를 띄워 봤으면(`local_preview_page`) 그렇다.
    """
    for step in steps:
        if not step.get("ok"):
            continue
        tool = str(step.get("tool") or "")
        if tool == "local_preview_page":
            return True
        if tool not in {"local_write_file", "local_apply_edit"}:
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        target = str(evidence.get("output_path") or arguments.get("path") or "").strip().lower()
        if target.endswith(_PAGE_SUFFIXES):
            return True
    return False
