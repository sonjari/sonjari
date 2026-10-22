"""agent.py 에서 **막힘·대안·산출물 자리** 묶음을 분리한다 (2026-10-09).

왜: agent.py 가 13,471줄로 커서 읽기 어려웠다. 이 묶음은 BrowserAgent 클래스와
순환 import가 없고, 시험이 ``inspect.getsource(agent)`` 로 요구하는 문자열도
포함하지 않아 그대로 옮길 수 있다.

이름 목록(35개):
  _NEUTRAL_LOOK_TOOLS, _LOCATE_MISS_MARKERS, _is_locate_miss,
  _trailing_locate_misses, LOCATE_WALL_AFTER, STUCK_LOCATE_AFTER,
  STUCK_FAILURES_AFTER, STUCK_STOPS_MAX, _STUCK_MARK, _trailing_failures,
  _STAGE_REFUSAL, _ROUTE_REFUSAL, _ROUTE_WHOLE_LIST_MAX_SHARE,
  _STAGE_REFUSALS_BEFORE_NARROWING, _DELIVER_REFUSAL_GRACE,
  _trailing_stage_refusals, _COMMAND_RUNNERS, _tool_named_in_command,
  _ASKED_DESTINATION, _USER_FOLDER_KEYS, _asked_destination_folder,
  _ASKED_FILE_NAME, _ASKED_FOLDER_DIRS, _ADDRESS_ENDINGS, requested_delivery,
  _into_asked_folder, _stuck_report,
  _RECENCY_MAX_AGE_DAYS, _RECENCY_WORD, _RECENCY_SPAN, _published_age_days,
  _stale_for_request, _stale_read_notice, _locate_wall_notice, _repeat_notice,
  _FALLBACK_CLAUSE, _fallback_clauses, _unkeepable_notice
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

#: 결과가 화면을 **바꾸지 않는** 살피기 걸음 — 찾기 실패의 연속을 끊지 않는다(기다렸다 다시 찾아도 같은 벽이다).
_NEUTRAL_LOOK_TOOLS = frozenset({
    "browser_wait", "browser_probe_frames", "browser_screenshot", "browser_scroll", "browser_tabs",
    "browser_verify", "ui_verify",
})


_LOCATE_MISS_MARKERS = (
    "ui_target_not_found", "search_box_not_found", "element_not_found", "invalid_element_ref",
    "unreadable_structure", "not_visible", "no_element",
)


def _is_locate_miss(name: str, observation: dict[str, Any]) -> bool:
    """「화면에서 대상을 못 찾았다」인가 — **도구가 달라도** 같은 벽이다.

    ★ 2026-09-17 MS 스토어: ui_find_target(search box) → snapshot(0개) → find → wait → snapshot → probe →
      ui_find_target(search input) → site_search(검색칸 없음) → snapshot → find → wait → snapshot, 16걸음.
      반복 경보는 **같은 도구·같은 인자**에만 걸려 한 번도 안 울렸다 — 모델이 매번 낱말·도구를 바꿨기 때문이다.
    """
    if not (name.startswith("browser_") or name.startswith("ui_")):
        return False
    payload = observation.get("result")
    payload = payload if isinstance(payload, dict) else {}
    blob = " ".join(str(value or "") for value in (
        observation.get("error"), payload.get("error"), payload.get("empty_reason"), payload.get("failure_kind"),
    ))
    if any(marker in blob for marker in _LOCATE_MISS_MARKERS):
        return True
    if not observation.get("ok"):
        return False
    if name == "browser_snapshot" and "element_count" in payload and int(payload.get("element_count") or 0) == 0:
        return True
    if name == "browser_find" and "match_count" in payload and int(payload.get("match_count") or 0) == 0:
        return True
    return False


def _trailing_locate_misses(steps: list[dict[str, Any]]) -> int:
    """끝에서부터 이어진 찾기 실패 수. 살피기 걸음은 건너뛰고, 다른 성공이 나오면 끊는다."""
    count = 0
    for step in reversed(steps):
        if str(step.get("tool") or "") in _NEUTRAL_LOOK_TOOLS:
            continue
        if step.get("locate_miss"):
            count += 1
            continue
        break
    return count


#: 몇 번째 찾기 실패부터 알리나. 둘은 낱말을 한 번 바꿔 볼 여지다 — 셋이면 같은 벽이다.
LOCATE_WALL_AFTER = 3


# ★ 알리기만 하지 않고 **멈춘다** (2026-09-23 제품 요청).
#   「못 하는 걸 붙잡고 헤맨다 — 시간만 쓰고 UX 최악. 될 때까지 하다가 안 되면 『이래서 못 했다, 이것만 해 주시면
#   이어가겠다』가 맞다.」 위의 「같은 벽」 알림은 모델에게 방향을 바꾸라고 말할 뿐이고, 모델은 자주 계속 두드린다
#   (안내문은 안 먹는다 — 사고 R). 알림의 두 배만큼 같은 자리에서 실패하면 **코드가 멈추고** 한 것·막힌 곳·해 주실
#   일을 사람에게 넘긴다. 사람이 손보고 「이어서」를 누르면 체크포인트에서 그 자리부터 잇는다.
STUCK_LOCATE_AFTER = 2 * LOCATE_WALL_AFTER


STUCK_FAILURES_AFTER = 5


#: 막힘으로 멈추는 횟수 상한 — 넘으면 또 묻지 않고 가진 것으로 정리한다(영영 매달린 판이 제일 나쁘다).
STUCK_STOPS_MAX = 2


#: 막혀서 넘긴 사실을 대화에 남기는 표식 — 체크포인트에 같이 저장되니 몇 번 넘겼는지를 따로 들고 다닐 필요가 없다.
_STUCK_MARK = "[막혀서 멈춤]"
#: 점검 중인 사이트를 알린 표시 — 사람에게 넘기지 않고 남은 출처로 잇게 한 알림(2026-10-15).
_SITE_DOWN_MARK = "[점검 중인 사이트]"
_SITE_DOWN = re.compile(r"site_under_maintenance:([\w.\-]+)")
#: 브라우저가 앞 동작에 물려 있다는 알림 — 사람이 화면을 만져 풀리는 것이 아니라 일꾼을 갈아야 풀린다(2026-10-15).
_PAGE_HUNG_MARK = "[응답 없는 페이지]"
_BROWSER_HUNG = re.compile(r"browser_busy_stuck|browser_busy_active")


def _trailing_failures(steps: list[dict[str, Any]]) -> int:
    """끝에서부터 **연달아 실패한** 걸음 수. 성공한 「보기」(스냅샷 등)는 건너뛰고, 다른 성공이 나오면 멈춘다."""
    count = 0
    for step in reversed(steps):
        # 「지금은 그 손을 쓸 차례가 아니다」는 화면이 막힌 게 아니라 우리 차례 규칙이다 — 사람을 부를 일이 아니다(2026-09-28).
        if str(step.get("error") or "") == _STAGE_REFUSAL:
            continue
        if not step.get("ok"):
            count += 1
            continue
        if str(step.get("tool") or "") in _NEUTRAL_LOOK_TOOLS:
            continue
        break
    return count


def _trailing_failure_errors(steps: list[dict[str, Any]]) -> list[str]:
    """`_trailing_failures` 가 센 실패 걸음들의 오류 글(끝에서부터)."""
    errors: list[str] = []
    for step in reversed(steps):
        if str(step.get("error") or "") == _STAGE_REFUSAL:
            continue
        if not step.get("ok"):
            errors.append(str(step.get("error") or ""))
            continue
        if str(step.get("tool") or "") in _NEUTRAL_LOOK_TOOLS:
            continue
        break
    return errors


#: 단계가 손을 좁혔는데 그 밖의 손을 불렀을 때 되돌려 보내는 오류 이름.
_STAGE_REFUSAL = "not_this_stage"


#: 갈래(웹 조사) 밖의 손을 불렀을 때 되돌려 보내는 오류 이름. 차례 거절과 따로 센다 — 안내가 다르다.
_ROUTE_REFUSAL = "not_this_route"


#: 조사 판에도 **전체 목록**을 보여 주는 조건 — 더 실리는 도구 정의가 창의 이 비율 이하일 때만(`_route_hands`).
#
# ★ 2026-10-10: 0.05 였다. 10-07 에 넣을 때 운영 창은 256K 라 더 실리는 양이 3.2% 였는데, 10-08 에 운영 모델을 128K 창으로 바꾸자
#   같은 양이 6.4% 가 되어 **이 장치가 조용히 꺼졌다**(어림 8,335토큰 > 한도 6,554). 그 뒤로 조사 판은 다시 79개, 그 밖의 판은 123개를
#   받아 종류가 바뀔 때마다 앞부분 2만~3만 토큰을 처음부터 읽었다 — 대표가 「아직 살짝 느리다」로 찾았다(22:27 의 첫 걸음 31,411토큰 ·
#   32.8초 · 서버 보관함에 앞 대화가 살아 있었는데도 8,477토큰까지만 같아 못 썼다). `_route_hands` 주석의 「128K 는 조건에 든다」는
#   계산이 틀렸고, 시험은 256K 로만 쟀다. 128K 에서 켜지고 64K 에서는 꺼지는 값으로 올린다(64K 에서는 약 13% — 본문 읽을 자리다).
#   도구가 늘면 「더 실리는 양」도 늘어 또 꺼질 수 있다 — 실제 목록으로 128K 에서 켜지는지를 시험이 붙든다
#   (`tests/test_research_jobs_see_the_same_tool_list_1007.py`). 꺼졌는지는 `data/prefix_same_kind.jsonl` 의 도구 수로 보인다.
_ROUTE_WHOLE_LIST_MAX_SHARE = 0.08


#: 되돌려 보내도 이만큼 연달아 무시하면 옛 방식(목록 자체를 좁힘)으로 간다.
_STAGE_REFUSALS_BEFORE_NARROWING = 2


#: 산출물 차례 중 거절당한 걸음을 이만큼까지 돌려준다 — 좁히기(2번) 뒤 한 번은 쓸 수 있게.
_DELIVER_REFUSAL_GRACE = 3


def _trailing_stage_refusals(steps: list[dict[str, Any]]) -> int:
    count = 0
    for step in reversed(steps):
        if str(step.get("error") or "") != _STAGE_REFUSAL:
            break
        count += 1
    return count


#: 명령을 도는 손. 모델이 여기 **다른 도구의 이름**을 명령으로 넣는 일이 있다.
_COMMAND_RUNNERS = frozenset({"local_run_project_command", "local_run_shell"})


def _tool_named_in_command(name: str, arguments: dict[str, Any], available: set[str]) -> tuple[str, dict[str, Any]]:
    """명령 칸에 **열려 있는 도구의 이름**이 들어왔으면 그 도구를 부른 것으로 돌린다 (2026-09-27 게임 팩 벤치).

    35B 가 `local_run_project_command` 에 `{"command": "unity_project_info", "project_path": …}` 를 넣었다.
    「고치지 마」 판이라 명령 실행이 막혔고, 모델은 유니티 길을 버리고 프리팹 원본을 뒤지다 틀렸다.
    뜻은 분명하다 — 그 도구를 부르려 했다. 막지 말고 받아 준다(사고 R). 돌린 도구도 게이트웨이에서
    **자기 위험 등급·프로필 검사를 그대로** 받으므로 문이 넓어지지 않는다.
    """
    if name not in _COMMAND_RUNNERS:
        return name, arguments
    command = arguments.get("command")
    head = command[0] if isinstance(command, list) and command else command
    target = str(head or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", target) or target not in available or target in _COMMAND_RUNNERS:
        return name, arguments
    rest = {key: value for key, value in arguments.items() if key not in {"command", "timeout_sec", "cwd"}}
    return target, rest


#: 요청이 **저장할 곳**으로 사용자 폴더를 댔는가(「내 문서 폴더에」·「문서 폴더(내 문서)에」·「바탕화면에」).
#: 「바탕화면에 있는 파일」·「다운로드 폴더의 …」처럼 **읽을 곳**을 말한 것은 안 걸린다. 맨 「문서로」는 형식이라 안 본다.
#: 운영 과거 요청 전수에 돌려 저장 자리 넷을 모두 잡고 읽을 자리는 하나도 안 잡은 것을 확인했다(2026-09-28).
_ASKED_DESTINATION = re.compile(
    r"(내\s*문서(?:\s*폴더)?|문서\s*폴더|바탕\s*화면|다운로드(?:\s*폴더)?)(?:\s*[(（][^)）]{0,40}[)）])?"
    r"\s*(?:에다가?|안에|에|로)(?!\s*(?:있|저장돼|저장된|든|들어|받은|받아))"
)


#: `local_computer._USER_FOLDER_ALIASES` 의 열쇠와 같은 이름들(여기서 그 모듈을 부르지 않으려고 적는다 — 시험이 둘을 대조한다).
_USER_FOLDER_KEYS = frozenset({"바탕화면", "바탕 화면", "데스크톱", "데스크탑", "desktop", "문서", "내 문서", "documents", "다운로드", "downloads"})


def _asked_destination_folder(prompt: str) -> str:
    """요청이 댄 저장 폴더의 우리 이름(`_USER_FOLDER_ALIASES` 의 열쇠). 없으면 빈 문자열."""
    match = _ASKED_DESTINATION.search(prompt or "")
    if not match:
        return ""
    said = re.sub(r"\s+", "", match.group(1))
    if said.startswith("바탕"):
        return "바탕화면"
    if said.startswith("다운로드"):
        return "다운로드"
    return "내 문서"


#: 사람이 댄 산출물 이름 — 「sonjari_wordcloud.png 로 저장」·「report.docx 라는 이름으로」. 이름 뒤에 **붙는 말**로 가른다.
_ASKED_FILE_NAME = re.compile(
    r"([^\s\\/:*?\"<>|'「」`‘’“”]+\.[A-Za-z0-9]{1,5})\s*(?:으로|로|라는|이라는|이름으로|파일로)(?![가-힣])"
)


_ASKED_FOLDER_DIRS = {"바탕화면": "Desktop", "다운로드": "Downloads", "내 문서": "Documents"}


#: 이름처럼 보이는 주소 끝(「robometafit.com 로 들어가」) — 파일이 아니다.
_ADDRESS_ENDINGS = (".com", ".net", ".org", ".io", ".kr", ".co", ".ai", ".dev", ".app")


def requested_delivery(prompt: str) -> Path | None:
    """사람이 **자리와 이름을 둘 다** 댄 산출물의 실제 경로. 하나라도 없으면 None — 추측하지 않는다.

    ★ 2026-09-30 워드클라우드 판: 파일은 잡 작업 폴더에 떨어지고 모델은 「복사해서 붙여넣으세요」로 끝냈다.
    이 값은 두 곳이 쓴다 — 상자가 같은 이름을 내면 거기로 보내고(`local_computer.expect_delivery`),
    계획 층이 「그 자리에 있나」를 본다(`Requirement.destination`).
    """
    compact = " ".join((prompt or "").split())
    folder = _asked_destination_folder(compact)
    if not folder:
        return None
    name = next(
        (m.group(1) for m in _ASKED_FILE_NAME.finditer(compact) if not m.group(1).lower().endswith(_ADDRESS_ENDINGS)),
        "",
    )
    return Path.home() / _ASKED_FOLDER_DIRS[folder] / name if name else None


def _into_asked_folder(name: str, arguments: dict[str, Any], prompt: str) -> dict[str, Any]:
    """「내 문서 폴더에 만들어 줘」인데 모델이 **파일 이름만** 줬으면 그 폴더로 보낸다 (2026-09-28 T2 재시험).

    같은 요청에 모델은 한 번은 `내 문서/…docx`, 한 번은 `…docx` 만 줬다. 앞의 것은 문서 폴더로, 뒤의 것은 우리 결과물
    폴더(`내 문서/JARVIS`)로 갔다 — 같은 말에 자리가 갈린다. 결정론으로 박을 수 있으니 코드로 박는다(사고 R).
    폴더를 이미 댔거나 절대 경로면 건드리지 않는다.
    """
    if name != "local_write_document":
        return arguments
    raw = str(arguments.get("path") or "").strip()
    folder = _asked_destination_folder(prompt)
    if not raw or not folder:
        return arguments
    path = Path(raw)
    if raw.startswith(("~", "%", "$")) or path.is_absolute():
        return arguments
    # 첫 칸이 이미 사용자 폴더 이름이면 그대로 둔다. 하위 폴더를 댄 경우(`회의록/양식.docx`)도 그 폴더 **아래**로 보낸다
    # (2026-09-28 T2 재측정 B1: `Documents\JARVIS\회의록\` 에 저장). 우리 결과물 폴더 이름(`JARVIS/…`)은 모델이 고른 것이라 둔다.
    if path.parts[0].casefold() in _USER_FOLDER_KEYS or path.parts[0].casefold() in {"jarvis", "ontelic"}:
        return arguments
    return {**arguments, "path": f"{folder}/{raw}"}


def _stuck_report(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """같은 자리에서 헛돌고 있으면 사람에게 넘길 보고, 아니면 None. 모델을 부르지 않는다(이미 센 것만 쓴다)."""
    # ★ 사람이 같은 탭을 쓰고 있다(2026-10-19 잡 51f35b07 · `BrowserWorker._hold_if_human_on_tab`). 헛돈 것이 아니라 **사람의 차례**다 —
    #   몇 번 실패를 기다리지 않고 첫 번에 넘긴다. 모델에게 「물어라」로 돌려보내면 그 자리에서 다른 손을 또 써 본다(사고 R).
    last_step = steps[-1] if steps else {}
    if not last_step.get("ok") and "human_on_tab —" in str(last_step.get("error") or ""):
        from .url_privacy import safe_url

        hold_url = ""
        match = re.search(r"지금 화면\((\S+?)\)", str(last_step.get("error") or ""))
        if match:
            hold_url = safe_url(match.group(1))
        good = [step for step in steps if step.get("ok") and str(step.get("tool") or "") not in _NEUTRAL_LOOK_TOOLS]
        done = f"{len(good)}걸음 성공"
        blocked = "사람이 이 브라우저 탭을 쓰고 있는 것 같아 손을 멈췄습니다(이 작업이 연 적 없는 화면입니다)"
        ask = ("그 탭을 다 쓰셨으면 「이어서」를 눌러 주세요 — 그때 떠 있는 화면에서 이어 갑니다. "
               "이 작업이 그 화면에서 누르면 안 되면 「이어서」 대신 멈춰 주세요.")
        message = (
            f"여기까지 했습니다: {done}.\n여기서 멈췄습니다: {blocked}."
            + (f"\n그 화면: {hold_url[:200]}" if hold_url else "")
            + f"\n이것만 해 주세요: {ask}"
        )
        return {"kind": "human_on_tab", "done": done, "blocked": blocked, "ask": ask, "url": hold_url, "message": message}
    locate = _trailing_locate_misses(steps)
    failures = _trailing_failures(steps)
    if locate < STUCK_LOCATE_AFTER and failures < STUCK_FAILURES_AFTER:
        return None
    kind = "cant_find" if locate >= STUCK_LOCATE_AFTER else "keeps_failing"
    # ★ 점검 중인 사이트 (2026-10-15 6GB 밤샘 측정: G마켓 새벽 점검에 판 열한 개가 0~2걸음으로 멈췄다).
    #   끝의 실패가 **전부** 「점검 중」이면 사람도 고칠 수 없다 — 화면을 맞춰 달라고 넘기지 않는다(반복문이 남은 출처로 잇게 한다).
    trailing = _trailing_failure_errors(steps)
    down = [_SITE_DOWN.search(error) for error in trailing]
    if kind == "keeps_failing" and trailing and all(down):
        host = down[0].group(1)
        blocked = f"{host} 가 점검 중입니다({failures}번 열어 봤습니다)"
        message = f"{host} 는 지금 점검 중이라 열 수 없습니다. 남은 출처로 잇습니다."
        return {"kind": "site_down", "host": host, "done": "", "blocked": blocked,
                "ask": "사람이 할 일은 없습니다 — 점검이 끝나면 그 사이트만 다시 맡기세요.", "url": "", "message": message}
    # ★ 브라우저가 물림 (2026-10-15 가격 판 3판: 11번가 상품 페이지에서 56초째 물린 뒤 다섯 걸음이 전부 `browser_busy_stuck`).
    #   사람이 팝업을 닫는다고 풀리지 않는다 — 반복문이 브라우저를 되살리고(`recover_now`) 남은 출처로 잇게 한다.
    if kind == "keeps_failing" and trailing and all(_BROWSER_HUNG.search(error) for error in trailing):
        blocked = f"브라우저가 한 페이지에서 응답을 기다리다 물렸습니다({failures}번 연속)"
        message = "한 페이지가 응답하지 않아 브라우저를 되살렸습니다. 그 페이지는 건너뛰고 남은 출처로 잇습니다."
        return {"kind": "page_hung", "host": "", "done": "", "blocked": blocked,
                "ask": "사람이 할 일은 없습니다 — 그 페이지만 나중에 다시 맡기세요.", "url": "", "message": message}
    last = next((step for step in reversed(steps) if not step.get("ok") or step.get("locate_miss")), steps[-1] if steps else {})
    tool = str(last.get("tool") or "")
    error = " ".join(str(last.get("error") or "").split())[:160]
    url = ""
    for step in reversed(steps):
        record = step.get("evidence_record") or {}
        source = str(record.get("source_id") or (step.get("evidence") or {}).get("url") or "")
        if source.startswith("http"):
            url = source
            break
    good = [step for step in steps if step.get("ok") and str(step.get("tool") or "") not in _NEUTRAL_LOOK_TOOLS]
    files = [
        str((step.get("evidence") or {}).get("output_path") or "")
        for step in good
        if (step.get("evidence") or {}).get("output_path")
    ]
    done = f"{len(good)}걸음 성공" + (f" · 만든 파일 {len(files)}개" if files else "")
    if kind == "cant_find":
        blocked = f"화면에서 찾는 것을 {locate}번 연속 못 찾았습니다" + (f"({tool})" if tool else "")
        ask = "크롬 창에서 그 화면을 한 번 봐 주세요. 찾던 단추나 칸이 보이면 한 번 눌러 두시거나, 어디 있는지 말씀해 주세요."
    else:
        blocked = f"같은 자리에서 {failures}번 연속 실패했습니다" + (f" — {tool}: {error}" if tool else "")
        timeout = any(word in error.lower() for word in ("timeout", "time out", "시간 초과"))
        # ★ 부탁은 **막힌 도구의 종류**에 맞춘다(2026-09-27 게임 팩 벤치). 로컬 파일 찾기가 5번 실패했는데
        #   「크롬 창에서 이 화면을 맞춰 주세요」라고 했다 — 크롬은 그 판에 열린 적도 없었다.
        if timeout:
            ask = "사이트가 제때 응답하지 않습니다. 잠시 뒤 「이어서」를 눌러 주세요." if tool.startswith("browser_") else \
                "작업이 제한 시간 안에 안 끝났습니다. 잠시 뒤 「이어서」를 눌러 주세요."
        elif tool.startswith(("local_", "hwp_")):
            ask = "찾던 파일이나 폴더가 그 자리에 있는지 봐 주시고, 다른 곳에 있으면 경로를 알려 주세요."
        elif tool.startswith("unity_"):
            ask = "유니티 에디터가 그 프로젝트를 열고 있으면 닫아 주시고, 오류 내용을 한 번 봐 주세요."
        else:
            ask = "크롬 창에서 이 화면을 원하시는 상태로 맞춰 주세요(팝업 닫기·선택하기 등)."
    message = (
        f"여기까지 했습니다: {done}.\n여기서 막혔습니다: {blocked}."
        + (f"\n그 화면: {url[:200]}" if url else "")
        + f"\n이것만 해 주세요: {ask}\n다 하시면 「이어서」를 눌러 주세요 — 처음부터 하지 않고 이 자리에서 이어 갑니다."
    )
    return {"kind": kind, "done": done, "blocked": blocked, "ask": ask, "url": url, "message": message}


#: 「오늘 것」·「이번 주 것」이 허락하는 글의 나이(일). 오늘 새벽에는 어제 저녁 기사가 가장 최신이라 「오늘」도 하루를 봐준다.
_RECENCY_MAX_AGE_DAYS = {"day": 1, "week": 7}


_RECENCY_WORD = {"day": "오늘", "week": "이번 주"}


_RECENCY_SPAN = {"day": "최근 1일", "week": "최근 1주"}


def _published_age_days(published: str, today: Any = None) -> int | None:
    """게시일(`YYYY-MM-DD`)이 오늘부터 며칠 전인가. 못 읽으면 None."""
    try:
        day = datetime.strptime(str(published)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return ((today or datetime.now().date()) - day).days


def _stale_for_request(published: str, recency: str, today: Any = None) -> int | None:
    """요청 기간 밖의 글이면 그 나이(일), 아니면 None."""
    if recency not in _RECENCY_MAX_AGE_DAYS or not published:
        return None
    age = _published_age_days(published, today)
    return age if age is not None and age > _RECENCY_MAX_AGE_DAYS[recency] else None


def _stale_read_notice(observation: dict[str, Any], recency: str, today: Any = None) -> dict[str, Any]:
    """읽은 글이 요청 기간 밖이면 **날짜를** 결과 본문에 박는다. 막지 않는다 — 옛 글이 배경으로 쓸모 있을 수 있다.

    ★ 2026-09-29 실사용: 「오늘자」를 물었는데 09-17 기사 하나로 「오늘의 이슈」를 답했다. 날짜는 structured_data 에
    이미 있었다(안내문은 안 먹는다 — 사고 R). 그래서 도구가 **센 날짜**를 먼저 준다.
    """
    payload = observation.get("result")
    if not isinstance(payload, dict):
        return observation
    published = str(payload.get("published") or "")
    age = _stale_for_request(published, recency, today)
    if age is None:
        return observation
    note = (
        f"★ [도구가 보낸 안내 — 사용자 말이 아니다] 이 글은 **{published} 게시({age}일 전)**다. "
        f"사용자는 {_RECENCY_WORD[recency]} 것을 물었다 — 이 글을 {_RECENCY_WORD[recency]} 소식으로 쓰지 마라. "
        "기간 안의 다른 결과를 열거나, 쓰려면 날짜를 밝혀라."
    )
    payload = {**payload, "stale_for_request": age,
               "instruction": (note + " " + str(payload.get("instruction") or "")).strip()}
    return {**observation, "result": payload}


def _locate_wall_notice(observation: dict[str, Any], misses: int) -> dict[str, Any]:
    """막지 않고 **결과 본문에** 알린다(이 저장소의 규율). 다음 수를 하나로 좁혀 준다."""
    payload = observation.get("result")
    payload = dict(payload) if isinstance(payload, dict) else {}
    payload["locate_wall"] = misses
    note = (
        f"★ [도구가 보낸 안내 — 사용자 말이 아니다] 이 화면에서 대상 찾기가 도구·낱말을 바꿔 가며 {misses}번 연속 실패했다. "
        "같은 벽이다 — 다른 낱말로 다시 찾기·스냅샷·기다리기를 또 하면 결과가 같다. "
        "결과에 targets(좌표 목록)이 있으면 browser_click_at / browser_type_at 으로 좌표를 눌러라. "
        "좌표도 없으면 더 헤매지 말고, 무엇이 막혔는지(어느 화면에서 무엇을 못 찾았는지) 사용자에게 말하고 끝내라."
    )
    payload["instruction"] = (note + " " + str(payload.get("instruction") or "")).strip()
    return {**observation, "result": payload}


def _repeat_notice(
    observation: dict[str, Any],
    *,
    tool: str,
    repeat_count: int,
    same_failure_count: int,
) -> dict[str, Any]:
    """되풀이를 **막지 않고** 도구 결과 본문에 알린다.

    폼 작업의 snapshot처럼 같은 호출이 정상인 경우가 있어 실행 자체를 차단하면
    안 된다. 모델이 실제 결과와 함께 반복 사실을 받아 다른 가설을 고르게 한다.

    ## 「반복」과 「같은 실패의 반복」은 문턱이 달라야 한다 (2026-09-09)

    3회 반복 벤치에서 시간 편차가 4배(66~276초)였다. 제일 느린 판의 앞 다섯 걸음:

        1  site_run search_jobs  ✅
        2  site_run scrap        ❌ 값이 없다 — ['job_id']
        3  site_run scrap        ❌ 같은 실패
        4  site_run scrap        ❌ 같은 실패
        5  site_run open_result  ❌ 그런 절차가 없다
        6~21 레시피를 포기하고 손으로 더듬음   ← 시간이 여기서 다 갔다

    안내는 **한 번도 안 나갔다.** 문턱이 `repeat_count >= 3` 이라 네 번째 호출에야
    걸리는데 세 번에서 멈췄기 때문이다.

    같은 인자로 같은 실패가 난 호출은 **결과가 결정론이다.** 다시 불러도 같은 답이
    온다 — 스냅샷처럼 「반복이 정상인 경우」가 아니다. 그래서 그쪽만 문턱을 둘로
    내린다. 막지는 않는다(이 저장소가 아는 규율이다) — 두 번째에 **알린다.**
    """
    if repeat_count < 3 and same_failure_count < 2:
        return observation
    payload = observation.get("result")
    payload = dict(payload) if isinstance(payload, dict) else {}
    if same_failure_count >= 2:
        instruction = (
            f"★ [도구가 보낸 안내] {tool}를 같은 인자로 불러 **같은 실패가 {same_failure_count}번** 났다. "
            "인자를 안 바꾸면 다음에도 같은 답이 온다 — 위 오류가 요구하는 값을 "
            "채우거나, 오류가 알려 준 목록에서 고르거나, 다른 도구로 바꿔라."
        )
    else:
        instruction = (
            f"★ [도구가 보낸 안내] {tool}를 같은 인자로 이미 {repeat_count}번 호출했다. "
            "정상 반복인지 확인하고, 새 정보가 없다면 다른 도구·대상·가설로 바꿔라."
        )
    payload["repeat_notice"] = True
    payload["repeat_count"] = repeat_count
    payload["same_failure_count"] = same_failure_count
    payload["instruction"] = (
        instruction + " " + str(payload.get("instruction") or "")
    ).strip()
    return {**observation, "result": payload}



#: 요청 안의 **대안 문장** — 「원화만 보이면 원화 그대로 적고」·「그래도 안 되면 공식 도움말에서」 같은 것.
_FALLBACK_CLAUSE = re.compile(
    r"(안\s*되면|안되면|없으면|만\s*보이면|안\s*보이면|안\s*열리면|열리지\s*않으면|못\s*(?:찾|읽|열)으면|실패하면|막히면|"
    r"그래도\s*안|if\s+(?:it|that|the page)?\s*(?:is not|isn't|doesn't|fails|can't)|otherwise)",
    re.IGNORECASE,
)


def _fallback_clauses(text: str, limit: int = 3) -> list[str]:
    """요청에 사람이 적어 둔 대안 문장들(최대 `limit`). 문장 단위로 자르고 160자로 줄인다."""
    pieces = re.split(r"(?<=[.!?])\s+|(?<=다\.)|(?<=요\.)|\n+", str(text or ""))
    found: list[str] = []
    for piece in pieces:
        sentence = " ".join(piece.split()).lstrip("0123456789.-) ")
        if sentence and _FALLBACK_CLAUSE.search(sentence) and sentence not in found:
            found.append(sentence[:160])
        if len(found) >= limit:
            break
    return found


def _unkeepable_notice(observation: dict[str, Any], asked: str) -> dict[str, Any]:
    """도구가 「이 지시는 이 PC 에서 못 지킨다」를 관측했으면(지역 주소로 바뀜) **요청에 적힌 대안**을 같이 댄다 (2026-10-02 협업 1차).

    도구의 안내만으로는 「대안이 있으면 따르라」까지다 — 대안이 무엇인지는 요청 안에 있고, 모델은 그걸 찾아 쓰지 않고 같은 주소를
    다섯 번 열었다. 대안 문장을 그대로 옮겨 준다(지어내지 않는다). 요청에 대안이 없으면 도구 안내 그대로 둔다.
    """
    payload = observation.get("result")
    if not isinstance(payload, dict) or not payload.get("locale_redirect"):
        return observation
    clauses = _fallback_clauses(asked)
    if not clauses:
        return observation
    payload = dict(payload)
    payload["instruction"] = (
        str(payload.get("instruction") or "")
        + " 요청에 적힌 대안: " + " / ".join(f"「{clause}」" for clause in clauses)
        + " — 이 대안으로 넘어가고, 어느 칸을 대안으로 처리했는지 답(과 파일)에 적어라."
    ).strip()
    payload["fallback_clauses"] = clauses
    return {**observation, "result": payload}
