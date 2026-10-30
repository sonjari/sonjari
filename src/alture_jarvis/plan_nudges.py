"""agent.py 에서 「다음 수」 묶음을 분리한다 (2026-10-10).

남은 요구의 종류에 맞는 다음 수를 골라 주는 쪽 — 되받기(다음 수) 상한·단계 순서·읽기/쓰기 걸음 판정. 함수 내용과 주석은 원본과 글자까지 같다(자리만 옮긴 것).
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import re

# 시킨 것이 남았는데 모델이 멈췄을 때 되받는 최대 횟수.
#
# 한 번으로는 모자랐다 — 첫 되받음에 목록을 한 번 더 보고 또 멈추는 판이 있다.
# 그렇다고 무한이면 못 하는 일을 계속 시키며 같은 말만 오간다. 둘이 그 사이다.
_PLAN_PUSHBACK_LIMIT = 2
# 「안 보고 답하려 함」 되받기 상한. 두 번까지 — 못 하는 일을 계속 시키면 같은 말만
# 오간다(`nudges`·`_PLAN_PUSHBACK_LIMIT` 과 같은 이유).
_OBSERVE_PUSHBACK_LIMIT = 2

# 전사에서 **도구 결과 하나**가 차지할 수 있는 최대 글자.


# 되받을 때 같이 주는 **다음 수**. 남은 것을 알려 주기만 하면 모델은 같은 방법을
# 다시 쓴다(실측: 목록을 한 번 더 읽고 같은 값을 낸다). 이 저장소가 실패마다 다음
# 수를 같이 주는 것과 같은 규율이다.
_OPEN_THE_BODY_HINT = (
    "\n★ **목록 화면에 적힌 값은 근거가 아니다.** 검색 결과·상품 목록·공고 목록에서 "
    "옮겨 적은 것은 '읽은 것'으로 세지 않는다 — 목록의 분류와 실제 상세가 다른 일이 "
    "흔하기 때문이다(실측: 목록 '전산설계사무' / 실제 'KB라이프 청약매니저').\n"
    "  시킨 개수만큼 **본문을 열어라**: browser_open_result(rank) → browser_extract\n"
    "  이미 읽은 것(visited=true)은 다시 열지 말고 다음 rank 를 골라라.\n"
    "  목록이 짧으면 browser_load_more, 값이 안 보이면 browser_scroll 을 먼저 써라."
)

#: ★ 읽기는 시킨 만큼 했는데 **답에 담긴 항목이 모자랄 때**의 다음 수 (2026-09-14).
#
#   새 과제 검사에서 잡코리아·알라딘 판이 「6개 읽음 · 답에 2개」로 끝났다. 되받기가
#   한 번 나갔는데 받은 말이 「본문을 열어라」였다 — 이미 여섯 곳을 열었다. 모델은 같은
#   페이지를 다시 열었고, 칸을 못 찾은 항목은 「확인 불가」로 채웠다. 필요한 말은 달랐다:
#   **다른 후보를 열어라, 못 찾은 항목은 빼라.**
_FILL_FROM_OTHER_CANDIDATES_HINT = (
    "\n★ **읽은 페이지는 충분한데 칸이 다 찬 항목이 모자라다.** 이미 연 페이지를 다시 "
    "열지 마라.\n"
    "  목록에서 **아직 안 연 다른 후보**(visited=false)를 열어 빈 칸(가격·고용형태 같은 값)이 "
    "있는지 browser_extract 로 확인해라. 값이 안 보이면 browser_scroll 로 아래를 본 뒤 읽어라.\n"
    "  끝내 값을 못 찾은 항목은 표에서 **빼라**. 칸에 「확인 불가」를 넣지 말고, 문서 끝에 "
    "「N건은 ○○을 찾지 못해 뺐다」고 한 번만 적어라."
)

_LIST_IS_THE_ANSWER_HINT = (
    "\n★ **이 과제는 목록이 답이다.** 항목을 하나하나 열어 읽을 필요가 없다. 목록 화면에 보이는 값으로 시킨 개수만큼 "
    "표(답이나 파일)에 담아라. 목록이 모자라면 더 불러오거나(스크롤·다음 쪽) 다음 목록으로 가라. "
    "목록에 없는 값은 지어내지 말고 없다고 적어라."
)

#: 접기 전에 주는 **산출물 차례**의 말. 루프 맨 위 경계와, 한 번에 상한을 넘긴 직후의 경계가 같은 글을 쓴다.
_DELIVER_TURN_NOTE = (
    "[시스템] 더 찾아도 진전이 없다. 새로 검색·열기를 하지 말고, "
    "지금까지 실제로 읽은 근거로 시킨 파일을 local_write_document 로(발표 장표는 local_make_slide 로) "
    "지금 만들어라. 못 채운 칸은 비우지 말고 그 행을 빼거나 "
    "문서 끝에 못 찾은 이유를 한 번 적어라."
)

_FINISH_THE_ARTIFACT_HINT = (
    "\n★ **조사는 여기서 멈추고 산출물 단계로 넘어가라.** 지금까지 직접 읽은 근거만 "
    "사용해 파일을 만들고, 파일이 실제로 열리는지 확인해라. 조건을 만족하는 자료가 "
    "요청 수보다 적으면 없는 항목을 만들지 말고, 확인된 수량만 반영한 뒤 부족한 수와 "
    "이유를 최종 답에 밝혀라."
)

_VERIFY_THE_ARTIFACT_HINT = (
    "\n★ **새 자료를 더 찾지 말고 방금 만든 결과를 검증해라.** 파일을 다시 열거나 "
    "요청에 맞는 좁은 검사 도구를 실행해, 존재·내용·형식을 확인한 뒤 끝내라."
)


_SAW_READ_AND_LISTED = re.compile(r"(\d+)개 읽음 · (?:답에 (\d+)개|파일 표에 (\d+)줄)")  # 파일 표: plan.check 10-03


#: 표 칸 자체가 주소·도메인인가(「https://inrng.com」·「inrng.com/2026/…」·「www.lwn.net」).
_URLISH_CELL = re.compile(r"(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:[/?#]\S*)?", re.I)


def _bare_host(value: str) -> str:
    """주소·도메인의 호스트 — 스킴이 없어도, www. 은 뗀다."""
    text = value.strip()
    host = (urlparse(text if "://" in text else "https://" + text).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _read_enough_but_listed_short(plan_results: list[tuple[Any, bool, str]]) -> bool:
    """개수 요구가 미달인데, **읽은 수는 목표 이상이고 답에 담긴 수만 모자란가.**"""
    for req, ok, saw in plan_results:
        if ok or str(getattr(req, "kind", "")) != "count":
            continue
        match = _SAW_READ_AND_LISTED.search(str(saw or ""))
        if not match:
            continue
        target = int(getattr(req, "target", 0) or 0)
        read, listed = int(match.group(1)), int(match.group(2) or match.group(3))
        if target and read >= target and listed < target:
            return True
    return False


#: 읽기 요구가 남았는데 대상이 브라우저가 아닐 때의 다음 수 (2026-09-23).
_READ_THE_SOURCE_HINT = (
    "\n★ 아직 근거를 실제로 읽지 않았다. 답에 쓸 사실이 들어 있는 파일·문서를 열어 읽어라"
    "(local_read_document · local_read_text_file). 사람이 내용을 직접 불러 준 일이라 읽을 대상이 없으면 "
    "새로 찾지 말고, 한 일(만든 파일·위치)을 그대로 답하라."
)


#: 최상급·범위 조건이 남았을 때의 다음 수 — 검색어 결과는 전체가 아니다(2026-10-03 TED 판, Browser Use 의 「필터 먼저」).
_APPLY_SITE_FILTERS_HINT = (
    "\n★ **검색어 결과는 전체가 아니다.** 「가장 ○○한 · ~사이 · 반경 ~」은 그 사이트가 직접 정렬·필터한 목록에서 골라야 한다 — "
    "검색어로는 제목에 그 낱말이 없는 정답을 놓친다. 사이트의 목록 페이지(Talks·Products·Listings·카테고리)로 가서 "
    "정렬(많이 본·낮은 가격·평점)과 필터(주제·길이·가격·거리)를 화면의 칸으로 걸어라(browser_select_option · browser_click). "
    "걸고 나면 주소에 sort=·duration= 같은 값이 남는다 — 그 목록의 위쪽에서 골라라."
)


def _next_plan_step_hint(plan_results: list[tuple[Any, bool, str]]) -> str:
    """남은 요구의 **종류**에 맞는 다음 수만 준다.

    예전에는 무엇이 남았든 ``_OPEN_THE_BODY_HINT`` 를 붙였다. 그래서 공고 읽기는
    이미 끝나고 문서·각주만 남은 판에도 "본문을 더 열어라"고 지시했고, 모델은
    15분 동안 공고 12건을 더 읽었다. 자유도를 줄이는 문제가 아니라 남은 목표와
    같은 방향으로만 열어 주는 문제다.
    """
    missing = {
        str(getattr(req, "kind", ""))
        for req, ok, _saw in plan_results
        if not ok
    }
    # ★ 2026-09-23: 「읽기」만 남았고 그 대상이 **브라우저가 아니면**(파일·문서) 브라우저 조사 문구를 주지 않는다.
    #   메모 파일 과제에 `browser_open_result → browser_extract` 재촉이 가자 모델이 시킨 일 대신 그 문구에
    #   「지침을 완벽히 이해했습니다」라고 답했다. 남은 것과 같은 방향의 다음 수만 준다(이 함수의 원래 규칙).
    browser_read_missing = any(
        not ok and (
            str(getattr(req, "kind", "")) in {"count", "site"}
            or (str(getattr(req, "kind", "")) == "observe" and str(getattr(req, "target", "")) == "browser")
        )
        for req, ok, _saw in plan_results
    )
    # ★ 2026-10-03 TED 판: 「가장 많이 본 · 12~18분」을 검색어 결과에서 골랐다. 정렬·필터가 남았으면 그게 먼저다.
    if "filter" in missing:
        return _APPLY_SITE_FILTERS_HINT
    # ★ 남은 것이 **목록이 답인 개수**뿐이면 「본문을 열어라」가 아니다 (2026-10-04 레딧 기준선 판 92b3776a).
    #   사람이 **직접** 「열 필요 없다」고 한 요구(`list_only`)에만 — 「표로 정리」만으로 가르면 상세가 필요한 과제까지 걸린다.
    listing_only = bool(missing) and all(
        ok or (str(getattr(req, "kind", "")) == "count" and getattr(req, "list_only", False))
        or str(getattr(req, "kind", "")) in {"artifact", "footnote", "verify"}
        for req, ok, _saw in plan_results
    ) and "count" in missing
    if listing_only:
        return _LIST_IS_THE_ANSWER_HINT
    if missing & {"count", "observe", "site"} and not browser_read_missing:
        return _READ_THE_SOURCE_HINT
    if missing & {"count", "observe", "site"}:
        if _read_enough_but_listed_short(plan_results):
            return _FILL_FROM_OTHER_CANDIDATES_HINT
        return _OPEN_THE_BODY_HINT
    if missing & {"artifact", "footnote"}:
        return _FINISH_THE_ARTIFACT_HINT
    if "verify" in missing:
        return _VERIFY_THE_ARTIFACT_HINT
    return ""


#: 되받기가 도는 순서. 앞 단계가 안 끝나도 **뒤 단계는 자기 예산을 받는다.**
_PLAN_STAGE_ORDER: tuple[tuple[str, frozenset[str]], ...] = (
    ("read", frozenset({"count", "observe", "site", "filter"})),
    ("artifact", frozenset({"artifact", "footnote"})),
    ("verify", frozenset({"verify"})),
    # 「그 화면까지 가기」(reach · 2026-10-30)는 읽기를 마친 뒤 누르고 넘어가는 일이라 행위 단계다.
    ("action", frozenset({"action", "count_action", "reach"})),
)


def _plan_focus_stage(
    plan_results: list[tuple[Any, bool, str]],
    *,
    spent: "Mapping[str, int] | None" = None,
    limit: int | None = None,
) -> str:
    """남은 요구를 한 단계 이름으로 압축한다. 단계마다 되받기 예산을 따로 쓴다.

    ## 앞 단계가 뒤 단계를 굶겼다 (2026-09-10)

    사슬 벤치에서 세 판이 **조사를 다 하고 표까지 짜 놓고 파일을 안 만들고** 끝났다.
    셋 다 `artifact` 요구가 있었고 예산도 남아 있었는데 되받기를 **한 번도** 못 받았다.

    원인은 이 함수였다. `count` 가 안 끝나면 늘 `"read"` 를 돌려주는데, 그 셋의
    `count` 는 「답 항목 중 읽은 원문에 없는 이름 있음」으로 **끝날 수가 없는 상태**
    였다. 읽기 되받기 두 번을 거기 다 쓰고 나면 `if` 가 통째로 거짓이 되어
    **산출물 단계는 자기 차례를 영영 못 받는다.**

        r1 사람인   16걸음 · 574초 (예산 900) · 읽기 5곳 · 파일 0
        r1 yes24    30걸음 · 387초             · 읽기 6곳 · 파일 0
        r2 위시켓   16걸음 · 250초             · 읽기 3곳 · 파일 0

    그래서 **예산을 다 쓴 단계는 건너뛴다.** 못 끝내는 일 하나가 할 수 있는 일까지
    막지 않게 한다. 전부 다 썼으면 첫 미달 단계를 그대로 돌려주어 바깥의 예산 검사가
    판을 끝내게 둔다 — 여기서 `unknown` 을 내면 없던 예산이 두 번 생긴다.
    """
    missing = {
        str(getattr(req, "kind", ""))
        for req, ok, _saw in plan_results
        if not ok
    }
    first = ""
    for name, kinds in _PLAN_STAGE_ORDER:
        if not (missing & kinds):
            continue
        first = first or name
        if spent is not None and limit is not None and spent.get(name, 0) >= limit:
            continue
        return name
    return first or "unknown"


def _opened_url(step: dict[str, Any]) -> str:
    args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
    return str(args.get("url") or "").strip().rstrip("/")


def _fresh_read_for_everything(name: str, arguments: Any, steps: list[dict[str, Any]]) -> bool:
    """「전부」 판의 산출물 차례에서도 막지 않는 읽기 — **처음 여는 주소**와 그 직후 읽기 한 번.

    ★ 2026-10-03 「내 레딧 글들 … 표로」 판(155bd3e1): 첫 글 `.json` 을 세 번 되읽어 진척 없음 → 산출물 차례에 들어갔고,
      그 차례가 **아직 안 연 둘째 글**을 네 번 거절해 표의 한 줄이 「확인 불가」로 나갔다. 되열기·되읽기는 그대로 막는다.
    """
    if name == "browser_open":
        url = str((arguments or {}).get("url") or "").strip().rstrip("/") if isinstance(arguments, dict) else ""
        return bool(url) and all(
            _opened_url(step) != url for step in steps if step.get("ok") and step.get("tool") == "browser_open"
        )
    return _reads_page_just_opened(name, steps)


def _reads_page_just_opened(name: str, steps: list[dict[str, Any]]) -> bool:
    """**방금 처음 연 페이지의 첫 읽기**인가 — 그러면 산출물 차례에서도 막지 않는다. 「더 찾기」가 아니다.

    ★ 2026-10-04 새벽 레딧 판(33cac79a): 다섯째 글을 **연 바로 그 순간** 산출물 차례가 시작돼, 그 글을 읽는 걸음이
      네 번 거절됐다. 모델은 연 글을 못 읽은 채로는 파일을 안 썼고(맞는 고집이다) 예고로 끝났다 — 글 다섯을 찾고도 엑셀 0개.
      차례의 뜻은 「새로 검색·열기를 하지 마라」다. 이미 연 페이지를 읽는 것은 거기 안 든다. 되열기·되읽기는 그대로 막는다
      (바로 앞 걸음이 그 주소의 **첫** 열기일 때 한 번뿐이다).
    """
    if name in {"browser_read", "browser_extract"} and steps:
        last = steps[-1]
        if last.get("ok") and last.get("tool") == "browser_open":
            # 그 주소를 **한 번도 못 읽었으면** 읽게 한다. 읽은 적이 있으면 되읽기다 — 그대로 막는다.
            return not _url_was_read(_opened_url(last), steps[:-1])
    return False


def _url_was_read(url: str, steps: list[dict[str, Any]]) -> bool:
    """이 주소를 열고 **그 자리에서 읽은** 적이 있는가(열기 다음, 다른 열기 전에 성공한 읽기)."""
    on_it = False
    for step in steps:
        if not step.get("ok"):
            continue
        tool = str(step.get("tool") or "")
        if tool == "browser_open":
            on_it = _opened_url(step) == url
        elif on_it and tool in {"browser_read", "browser_extract"}:
            return True
    return False


def _reopens_unread_page(name: str, arguments: Any, steps: list[dict[str, Any]]) -> bool:
    """**열어 놓고 못 읽은 주소**를 다시 여는 것인가 — 산출물 차례에서도 한 번은 받는다.

    ★ 2026-10-04 새벽 레딧 판(93f08e95): 다섯 글 중 하나를 열고 안 읽은 채 다음 글로 넘어갔다. 차례가 온 뒤 그 글로
      돌아가려 했지만 「이미 연 주소」라 거절됐고, 표는 네 줄로 나갔다(답에는 「주소가 깨져서 못 열었다」는 틀린 설명까지).
      새 주소가 아니다 — 이미 찾아 놓은 것을 마저 읽는 일이다. 읽은 적 있는 주소·세 번째 열기는 그대로 막는다.
    """
    if name != "browser_open" or not isinstance(arguments, dict):
        return False
    url = str(arguments.get("url") or "").strip().rstrip("/")
    if not url:
        return False
    opened = [step for step in steps if step.get("ok") and step.get("tool") == "browser_open" and _opened_url(step) == url]
    return len(opened) == 1 and not _url_was_read(url, steps)


_DOCUMENT_WRITE_TOOL = "local_write_document"


def _write_came_back_clean(step: dict[str, Any]) -> str:
    """이 걸음이 **확인까지 끝난 문서 쓰기**면 그 파일의 경로(소문자), 아니면 빈 글.

    「확인」은 도구가 돌려준 것으로만 본다 — 성공했고, `verified` 가 참이고, 고치라는 말(꼴 메모 · 못 읽은 블록 · 비운 칸)이 없다.
    """
    if step.get("tool") != _DOCUMENT_WRITE_TOOL or not step.get("ok"):
        return ""
    evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
    if str(evidence.get("verified") or "").strip().lower() not in {"true", "1"}:
        return ""
    if evidence.get("shape_notes") or evidence.get("unreadable_blocks") or evidence.get("blanked_unverified_cells"):
        return ""
    return str(evidence.get("output_path") or "").strip().casefold()


def _rewrote_a_finished_document(steps: list[dict[str, Any]]) -> str:
    """**확인까지 끝난 문서를 바로 이어 또 썼고, 그것도 확인됐는가** — 그 파일의 경로를 돌려준다(아니면 빈 글).

    ★ 2026-10-12 밤 네 번 이어 묻기(4B · 창 32K)의 셋째 판: 「방금 내용을 워드 파일로 정리해 줘」에 같은 파일을 **열네 번**
      썼다. 첫 번째만 고칠 것이 있었고(꼴 메모), 둘째부터 열넷째까지는 전부 「확인됨」이었다. 모델은 매번 글을 조금씩 바꿔
      다시 보냈고(쓸 때마다 1,400토큰쯤), 판은 시간 한도(197초)에서야 접혔다. 같은 호출의 되풀이를 알리는 장치는 인자가
      **같은** 호출만 봐서 못 잡았다 — 열네 번 다 글이 달랐다.

      고칠 것이 없다고 도구가 말한 문서를 또 썼고, 그 답도 「확인됨」이면 세 번째에서 달라질 것이 없다. 그 자리에서 접는다 —
      만든 파일은 그대로 두고, 모델은 답만 쓴다. 사이에 다른 걸음(읽기 · 다른 파일)이 끼었으면 해당 없다.
    """
    if len(steps) < 2:
        return ""
    last, before = _write_came_back_clean(steps[-1]), _write_came_back_clean(steps[-2])
    return last if last and last == before else ""


#: 「파일을 만들 차례」를 이만큼 연달아 거슬렀으면 그 짐작을 거둔다 — 되돌려 보내기 2번 + 목록을 좁힌 뒤 2번.
STAGE_REFUSALS_BEFORE_WITHDRAWING = 4


def _stage_guess_failed(trailing_refusals: int, *, deliver_turn: bool) -> bool:
    """되받기가 건 「파일을 만들 차례」를 거둘 때인가 — 모델이 네 번 연달아 다른 손을 불렀다.

    ★ 2026-10-12 밤 공식 9B · 창 32K 가격 조사 두 판(d804d833 · e22dbb7b)이 같은 모양으로 죽었다:

          5  browser_extract      다나와 상품 화면 (값이 본문에 안 잡혔다)
             (모델이 도구 없이 한마디 → 되받기 → 「파일을 만들 차례」)
          6  browser_page_data    not_this_stage
          7  browser_read         not_this_stage
          8  browser_extract      not_this_stage
          9~ browser_snapshot     not_this_stage  × 12
         21~ browser_open_result  not_this_stage  × 5      → 25걸음 · 가게 하나 · 파일 없음

      그 차례는 **짐작**이다 — 근거는 모델이 도구 없이 한 번 말했다는 것뿐이고, 계획에 남은 요구가 「파일 만들기」 하나라
      거기로 갔다(팩 본문의 「가게 세 곳」은 계획이 모른다). 모델은 값도 못 읽은 채로는 파일을 안 썼다(10-04 레딧 판과 같은
      맞는 고집이다). 문은 한 번 걸리면 파일이 생길 때까지 안 풀려서, 같은 거절을 스무 번 하며 걸음을 다 태웠다.
      거절 2번 뒤에 목록을 좁히는 장치(09-28 · 35B 는 이것으로 따랐다)도 9B 에게는 안 먹었다 — 목록에 없는 손을 불렀다.

      되돌려 보내기 두 번 · 좁힌 목록으로 두 번, 네 번을 다 거슬렀으면 말도 목록도 안 먹은 것이다. 더 막는 것은 걸음만
      태운다 — 짐작을 거두고 모델이 하려던 것을 하게 둔다. 다시 도구 없이 답하면 되받기가 차례를 또 건다.

    걸음이 바닥나기 전의 마지막 차례(`deliver_turn`)는 거두지 않는다 — 거기서는 못 했다고 적어 내는 것이 맞다.
    """
    return not deliver_turn and int(trailing_refusals) >= STAGE_REFUSALS_BEFORE_WITHDRAWING


def _slides_saved(steps: list[dict]) -> int:
    """장표 판에서 지금까지 저장된 **서로 다른 장**의 수 — 되받기의 진전으로 센다 (2026-10-25 밤 grove 판 6cda73c3).

    장표는 마지막 장을 넣어 구울 때까지 「열 수 있는 산출물 없음」이 그대로다. 장을 새로 넣어도 남은 것이 같아 보여 「진전 없음」이
    됐고, 두 번째 되받기가 안 나가 판이 1장에서 접혔다. 같은 장을 다시 넣은 것은 세지 않는다(같은 파일 거듭 쓰기는 진전이 아니다).
    """
    seen = set()
    for step in steps:
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        if step.get("ok") and str(step.get("tool") or "") == "local_make_slide" and evidence.get("saved") and evidence.get("index"):
            seen.add((str(evidence.get("title") or ""), evidence.get("index")))
    return len(seen)


def _deck_steps_owed(steps: list[dict]) -> int:
    """장표 판에서 아직 넣을 장 수 + 여유 2 — 걸음 한도가 이만큼은 남게 한다 (2026-10-25 밤 grove 판 de242e91).

    걸음 예산은 개수 요구(「4곳 읽기」)로만 커져서 장표는 기본 12~15걸음이었다. 7장 판은 결 · 이야기판 · 장 7개에
    장마다 한 번씩만 돌려받아도 넘는다 — 실제로 15걸음 중 8걸음이 돌려받기였고 5장에서 끝났다. 다 구웠으면 0.
    """
    total = 0
    saved: set = set()
    title = ""
    for step in steps:
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        if not step.get("ok") or str(step.get("tool") or "") != "local_make_slide":
            continue
        if evidence.get("total"):
            total = int(evidence.get("total") or 0)
            title = str(evidence.get("title") or title)
        if evidence.get("saved") and evidence.get("index") and str(evidence.get("title") or "") == title:
            saved.add(evidence.get("index"))
        if evidence.get("output_path"):  # 마지막 장을 넣어 구웠다
            return 0
    return (max(0, total - len(saved)) + 2) if total else 0


def _deck_in_progress(steps: list[dict]) -> bool:
    """장표를 만드는 중인가 — 장표 손을 한 번이라도 성공했고 아직 굽지 않았다(결만 고른 판도 포함).

    daisy-days 둘째 판(7d298ae0)은 결 안내를 두 번 읽는 데 321초를 쓰고 장을 하나도 넣기 전에 시간이 끝났다 —
    「저장된 장」으로만 장표 판을 알아보면 이 판이 안 걸린다.
    """
    made = [step for step in steps if step.get("ok") and str(step.get("tool") or "") == "local_make_slide"]
    return bool(made) and not any((step.get("evidence") or {}).get("output_path") for step in made)


def _read_more_since(reads_now: int, reads_before: int | None) -> bool:
    """지난 되받기 뒤로 본문을 새로 받아 온 곳이 늘었는가. 지난 되받기가 없으면(처음이면) 아니다."""
    return reads_before is not None and int(reads_now) > int(reads_before)


#: 배수 · 퍼센트 단정(「생산성 10배」 · 「인력 50% 감축」 · 「2~3배」).
_RATIO_CLAIM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:~\s*\d+(?:\.\d+)?\s*)?(?:배|%|퍼센트)")


def _invented_ratios(answer: str, *known: str) -> list[str]:
    """도구 없이 쓴 답이 단정한 배수 · 퍼센트 중 **질문 · 대화 어디에도 없던 것**(2026-10-18 대표 디스코드 실사용).

    「AI 시대에 불안하다」 · 「손자리가 일자리를 줄이나」 같은 의견 질문에 도구 0걸음으로 「생산성 10배」 · 「3년 뒤 인력 50% 감축,
    2~3배 증가」를 단정했다. 금액 검사(원 · 포인트)도, 라우터의 숫자 검사(세 자리 이상)도 이 꼴을 안 본다. 운영의 도구 없이 쓴
    답 117개 중 19개에 이런 수치가 있었다 — 「계약금은 보통 10%」 같은 상식도 섞여 있어 지우게 하지 않고 밝히게 한다.
    """
    seen = set(re.findall(r"\d+(?:\.\d+)?", " ".join(known)))
    found: list[str] = []
    for match in _RATIO_CLAIM.finditer(answer or ""):
        if match.group(1) in seen:
            continue
        claim = re.sub(r"\s+", "", match.group(0))
        if claim not in found:
            found.append(claim)
    return found


def _keep_answer_over_reply(kept: str, reply: str, *, new_steps: int) -> str:
    """되받기 뒤 최종 답. 되받은 뒤 **새 걸음이 없고** 새 답이 앞 답보다 많이 짧으면 앞 답을 살리고 새 답을 그 뒤에 붙인다.

    새로 한 일이 없으면 내용은 앞 답에 있다 — 새 답은 대개 「그건 할 일이 없었다」 같은 해명이다(2026-10-18 c9910364).
    새 걸음이 있었거나 새 답이 앞 답만큼 길면 새 답이 고쳐 쓴 답이다 — 그대로 둔다.
    """
    kept_text, reply_text = (kept or "").strip(), (reply or "").strip()
    if not kept_text or new_steps > 0:
        return reply
    if not reply_text:
        return kept
    if len(reply_text) >= len(kept_text) * 0.6 or kept_text in reply_text or reply_text in kept_text:
        return reply
    return f"{kept_text}\n\n{reply_text}"


def _pushback_stalled(unmet_now: Any, unmet_before: Any, *, read_more: bool) -> bool:
    """되받아도 소용없는 판인가 — 남은 요구가 지난 되받기 때와 같고 **그 사이에 새로 읽은 것도 없다.**

    ★ 2026-10-12 공식 9B · 창 32K 가격 조사 여섯 판 중 넷이 10~12걸음에서 `model_stopped_early` 로 끝났다(되받기 1번).
      9B 는 걸음 사이에 「이제 11번가를 확인하겠습니다」처럼 말만 하는 버릇이 있다. 한 번 되받자 다음 가게를 읽었고(진짜
      진전), 또 말만 했다 — 그런데 「남은 것」을 계획의 요구로만 봐서, 요구가 「파일 만들기」 하나뿐인 그 판은 남은 것이
      한 글자도 안 바뀌었고(「열 수 있는 산출물 없음」) 「진전 없음」으로 판정돼 두 번째 되받기가 안 나갔다. 같은 조건의
      4B 는 말없이 손을 움직여 여섯 판 모두 끝까지 갔다(14~21걸음).
      그 규칙(09-30)이 막으려던 것은 「채울 수 없는 요구를 두고 자기 파일만 다시 읽는 판」이다 — 새로 읽은 곳이 없는 판이다.
    """
    return bool(unmet_now) and unmet_before == unmet_now and not read_more


#: 한 사이트 안에서 찾고 · 열고 · 읽는 손 — 그 사이트를 아직 못 읽었으면 산출물 차례에서도 받는다(`_goes_to_unread_site`).
_SITE_WALK_TOOLS = frozenset({
    "browser_site_search", "browser_open_result", "browser_load_more", "browser_snapshot",
    "browser_extract", "browser_read", "browser_page_data",
})


def _site_of(url: str) -> str:
    """주소의 사이트(`prod.danawa.com` · `search.danawa.com` → `danawa.com`). 검색엔진의 결과 화면은 사이트가 아니다 — 빈 글."""
    from .site_atlas import SEARCH_ENGINE_HOSTS, registrable

    host = (urlparse(str(url or "")).hostname or "").casefold()
    if not host or any(engine in host for engine in SEARCH_ENGINE_HOSTS):
        return ""
    return registrable(host)


def _goes_to_unread_site(name: str, arguments: Any, steps: list[dict[str, Any]]) -> bool:
    """**아직 본문을 못 받아 온 사이트**로 가는(또는 그 안에서 찾고 여는) 손인가 — 그러면 산출물 차례에서도 막지 않는다.

    ★ 2026-10-12 가격 조사 · 공식 9B · 창 32K 세 판(89931d82 · 80a53177 · 1c25551c)이 가게 하나나 둘만 읽고 끝났다.
      모델이 첫 가게를 읽고 「이제 11번가를 보겠습니다」처럼 **말만 한 번** 하자 되받기와 함께 차례가 걸렸고, 방금 연
      11번가의 검색(`browser_site_search`)이 `not_this_stage` 로 되돌아갔다. 엑셀에는 다나와 한 줄만 남았다. 같은 날 앞선
      세 판은 반대 모양이었다 — 다나와와 11번가를 되풀이해 읽다 걸음을 다 썼다. 큰 모델은 말없이 세 가게를 돌아 안 걸린다.

      차례의 뜻은 「더 찾지 마라」였는데(10-02 · 읽은 글 여섯을 두고 더 열기만 한 판), 그 문은 **새 땅과 헌 땅을 가르지
      않았다.** 이 문에 붙은 예외 넷(방금 연 화면 · 안 읽은 주소 · 「전부」 판 · 대조가 열라고 한 주소)이 다 그 구멍이다.
      읽은 적 없는 사이트로 가는 길은 받고, 이미 읽은 사이트로 돌아가는 길만 막는다 — 일찍 닫히는 것과 되풀이를
      규칙 하나로 막는다.

    좁게 둔다: 웹 검색(`browser_search`)과 검색엔진 결과 화면에서 여는 것은 예전처럼 막는다(거기는 사이트가 아니다).
    한 사이트 안의 둘째 화면(채용 공고 셋 같은 일)은 이 예외에 들지 않는다 — 예전 그대로다. 걸음이 바닥나기 전의 마지막
    차례에는 부르는 쪽이 이 예외를 쓰지 않는다 — 거기서는 `_owed_read_site` 가 남은 요구에 닿는 곳만 연다.
    """
    return bool(_unread_site_target(name, arguments, steps))


def _unread_site_target(name: str, arguments: Any, steps: list[dict[str, Any]]) -> str:
    """이 손이 가는 사이트가 **아직 본문을 못 받아 온 곳**이면 그 사이트(`ollama.com`), 아니면 빈 글(`_goes_to_unread_site`)."""
    read_sites = set()
    here = ""
    for step in steps:
        if not step.get("ok") or not str(step.get("tool") or "").startswith("browser_"):
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        url = str(evidence.get("url") or _opened_url(step) or "")
        if not url:
            continue
        here = _site_of(url)
        if step.get("tool") in {"browser_read", "browser_extract"} and here:
            read_sites.add(here)
    if name == "browser_open":
        target = _site_of(str(arguments.get("url") or "")) if isinstance(arguments, dict) else ""
    elif name in _SITE_WALK_TOOLS:
        target = here
    else:
        return ""
    return target if target and target not in read_sites else ""


#: 접기 전 산출물 차례에서도 「아직 못 채운 읽기 요구」로 받아 주는 **사이트 수**(한 판) — `_owed_read_site`.
_OWED_READ_SITES = 2
#: 그 사이트 하나에 받아 주는 걸음(열기 · 그 안에서 찾기 · 결과 열기 · 읽기). 넘으면 예전처럼 막는다. 그 사이트를 한 번 읽으면 「안 읽은 곳」이 아니라 거기서 끝난다.
_OWED_READ_CALLS_PER_SITE = 4

#: 읽기 요구로 보는 대조표 칸의 종류 — 어디서 무엇을 **읽으라는** 요구. 파일 · 행동 · 필터 · 각주는 아니다.
_READ_REQUIREMENT_KINDS = frozenset({"site", "count", "observe"})


def _site_named_in(text: str, site: str) -> bool:
    """요청 글이 그 사이트를 **이름으로** 댔는가(`ollama.com` ← 「Ollama」 · 「ollama.com」). 낱말표가 아니라 주소 자체와 대 본다.

    주소의 몸통(`ollama`)이 요청에 **낱말 하나로** 있어야 한다 — 「lmstudio」 는 「LM Studio」 와 다르게 쓰였으면 안 댄 것이다
    (헛맞기보다 못 맞기가 낫다: 못 맞으면 예전처럼 막힐 뿐이다). 세 글자 미만 몸통(`ai.com`)은 안 본다.
    """
    site = str(site or "").casefold()
    haystack = str(text or "").casefold()
    if not site or not haystack:
        return False
    if site in haystack:
        return True
    stem = site.split(".")[0]
    if len(stem) < 3:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(stem)}(?![a-z0-9])", haystack) is not None


def _owed_read_site(
    name: str,
    arguments: Any,
    steps: list[dict[str, Any]],
    plan_results: list[tuple[Any, bool, str]] | None,
    request: str,
) -> str:
    """**아직 못 채운 읽기 요구**에 닿는 걸음이면 그 사이트, 아니면 빈 글 — 접기 전 산출물 차례에서도 받는다.

    ★ 2026-10-19 두 판이 「확인 못 함」으로 나갔다. 아픔 넷 × 제품 둘의 홈페이지 조사(8b90144f)는 아픔 ①~③을 읽고 ④의
      Ollama · LM Studio 홈페이지를 열려는 순간 걸음 상한에 닿았고, 접기 전 산출물 차례(`deliver_turn_used`)가 걸려 두 열기가
      `not_this_stage` 로 되돌아갔다. inline AI 조사(d0d36f19)는 요청이 「네이버 블로그 후기도 읽어 줘」였고 대조표에
      「네이버 블로그에서 하기」가 **못 채운 채** 남았는데, 그 블로그 글을 여는 걸음이 같은 문에 막혔다.
      그 차례는 「아직 안 읽은 사이트로 가는 길」(`_goes_to_unread_site`)을 일부러 안 받는다 — 걸음이 +3 뿐이라 그 셋을
      읽기에 쓰면 파일을 못 쓴다(10-02 · 9d6942f2: 글 여섯을 읽고도 더 열다 엑셀 0개). 그 까닭은 맞다. 다만 그 문은
      **시킨 것이 남았는가**를 안 봤다 — 요청이 이름으로 댄 곳과 대조표에 남은 읽기 칸도 「더 찾기」로 막았다.

    가르는 것은 낱말이 아니라 요구 상태다. 이 손이 **아직 본문을 못 받아 온 사이트**로 가고(`_unread_site_target` — 검색엔진 ·
    읽은 사이트로 되돌아가기는 그대로 막힌다), 다음 중 하나일 때만 받는다:
      ① 요청이 그 사이트를 이름으로 댔다 — 대조표의 「○○에서 하기」 칸(사이트 표가 「다나와」를 `danawa.com` 으로 푼 것)이
         그 주소이거나, 요청 글에 주소의 이름이 있다(`_site_named_in` — 「Ollama」 · 「inline-ai.com」).
         「○○에서 하기」 칸은 그 사이트에 **들르기만 해도** 채워진다(검색 화면을 연 것). 그래서 여기서는 그 칸의 채움 여부를 안
         본다 — 이 손이 가는 곳은 아직 본문을 하나도 못 받아 온 곳이라는 것이 이미 걸러져 있다(10-13 4cfe1fba: 다나와 검색
         화면을 연 뒤 「다나와에서 하기」는 채워졌는데 상품을 여는 걸음 다섯이 막혀 파일 없이 끝났다).
      ② 대조표에 **못 채운 읽기 칸**(개수 · 「대상 실제로 읽기」 — 이 PC 를 보라는 칸은 뺀다)이 있다 — 새 사이트면 된다.
    둘 다 아니면 예전처럼 막는다 — 차례를 둔 까닭(끝없이 더 읽기)을 지킨다.
    받는 횟수의 상한(`_OWED_READ_SITES` · `_OWED_READ_CALLS_PER_SITE`)과 걸음 · 시간 돌려주기는 부르는 쪽이 쥔다.
    """
    site = _unread_site_target(name, arguments, steps)
    if not site:
        return ""
    if _site_named_in(request, site):
        return site
    for requirement, met, _saw in plan_results or []:
        kind = str(getattr(requirement, "kind", "") or "")
        if kind == "site":
            target = getattr(requirement, "target", None)
            hosts = [str(part).casefold() for part in (target if isinstance(target, (list, tuple)) else (target,)) if part]
            if any(site == host or site.endswith("." + host) or host.endswith("." + site) for host in hosts):
                return site
            continue
        if met or kind not in _READ_REQUIREMENT_KINDS:
            continue
        if str(getattr(requirement, "source_scope", "") or "") == "local":
            continue
        if kind == "observe" and str(getattr(requirement, "target", "") or "") == "local":
            continue
        return site
    return ""


_OWED_READ_REWRITE_NOTE = (
    "[도구가 보낸 안내] 시킨 것 중 아직 못 읽은 곳이라 열어 준다. 이 곳을 읽었으면 **앞서 만든 파일을 다시 써서** "
    "「확인 못 함」으로 둔 칸을 읽은 내용으로 고쳐라(같은 파일 이름). 이 곳 말고 다른 곳을 더 찾지는 마라."
)


def _with_owed_read_note(observation: dict[str, Any], note: str) -> dict[str, Any]:
    """받아 준 읽기의 결과에 안내를 붙인다 — 모델이 보는 것은 `result` 안이다(`site_first_note` 와 같은 자리)."""
    if not note:
        return observation
    payload = observation.get("result")
    payload = dict(payload) if isinstance(payload, dict) else {}
    payload["instruction"] = (note + " " + str(payload.get("instruction") or "")).strip()
    return {**observation, "result": payload}


#: 쓴 파일의 줄이 「열지 않은 주소」로 지적된 뒤, 산출물 차례에서도 받아 주는 **새 주소 열기**의 상한.
_REPAIR_READ_OPENS = 3


def _repair_read_after_write_feedback(name: str, arguments: Any, steps: list[dict[str, Any]]) -> bool:
    """쓴 파일이 「열지 않은 주소가 줄에 붙어 있다」로 되돌아온 뒤의 **그 주소 열기**는 산출물 차례에서도 막지 않는다.

    ★ 2026-10-04 레딧 조사 두 판(30f003f6 · aa741c81): 파일을 쓰자 대조가 「열지 않은 주소는 빼거나, 먼저 열어서 읽은 뒤에
      적어라」고 했고, 모델이 그 주소를 열려 하자 차례 문이 `not_this_stage` 로 두세 번 거절했다 — 검사는 열라 하고
      문은 열지 말라 했다. 모델은 「확인하겠습니다」로 끝났다(예고로 끝남). 틀린 안내는 막는 것보다 나쁘다.

    좁게 연다: 대조 되돌림을 받은 **뒤**에만 · **처음 여는 주소**와 그 직후 읽기 한 번만 · 주소 `_REPAIR_READ_OPENS` 개까지.
    검색·되열기·되읽기는 그대로 막는다(2026-10-02 밤: 산출물 차례에 페이지를 세 번 더 열어 파일을 못 쓴 판).
    """
    fed = next((index for index, step in enumerate(steps) if step.get("write_grounding_feedback")), -1)
    if fed < 0:
        return False
    opened_since = sum(1 for step in steps[fed + 1:] if step.get("ok") and step.get("tool") == "browser_open")
    if name == "browser_open" and opened_since >= _REPAIR_READ_OPENS:
        return False
    return _fresh_read_for_everything(name, arguments, steps)


def _own_written_messages(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """이 판이 **파일에 직접 쓴 글**을 도구 결과 모양으로 — 코드 판의 근거 검사가 만든 것을 읽은 것처럼 따지지 않게."""
    written: list[str] = []
    for step in steps:
        if not step.get("ok") or str(step.get("tool") or "") not in {"local_write_file", "local_apply_edit"}:
            continue
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        for key in ("content", "new"):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                written.append(value)
    return [{"role": "tool", "content": "\n".join(written)}] if written else []


def _artifact_requirements_met(plan_results: list[tuple[Any, bool, str]]) -> bool:
    """산출물 요구가 **있고 전부 채워졌나**. 산출물 요구가 없는 판은 False(예전 동작 그대로)."""
    owed = [ok for req, ok, _ in plan_results or [] if str(getattr(req, "kind", "")) == "artifact"]
    return bool(owed) and all(owed)


def _cleans_up(name: str, arguments: Any, steps: list[dict[str, Any]], root: str) -> bool:
    """**치우는 걸음**인가 — 자기가 쓴 파일을 지우거나, 폴더를 지우는 것. 「먼저 읽어라」를 타지 않는다."""
    if name != "local_delete_file" or not isinstance(arguments, dict):
        return False
    if _deletes_own_file(name, arguments, steps):
        return True
    raw = str(arguments.get("path") or "").strip()
    if not raw:
        return False
    try:
        target = Path(raw)
        if not target.is_absolute() and root:
            target = Path(root) / target
        return target.is_dir()
    except OSError:
        return False


def _deletes_own_file(name: str, arguments: Any, steps: list[dict[str, Any]]) -> bool:
    """이 판에서 **자기가 만든 파일**을 지우는 걸음인가 — 최종 답만 남은 때에도 받는다.

    ★ 2026-10-04 도구 전수조사 2-D: 검토 안내는 「점검용 파일을 만들었다면 local_delete_file 로 정리하라」고 하는데,
      검증이 성공하는 순간 모든 손이 닫혀 「만들고 → 돌리고 → 지우기」의 지우기 직전에 막혔다. 임시 파일이 사용자
      폴더에 남거나, 지울 손이 없어 0바이트로 덮어썼다(그게 검증을 무효로 만들었다). 손을 닫은 이유(「성실한 모델이
      같은 파일과 화면을 다시 확인하며 돈다」)는 지우기 하나에는 해당하지 않는다. 만들고 지운 임시 파일은 검증을 무효로
      만들지도 않는다(`code_runtime.code_verification_is_current`).
    """
    if name != "local_delete_file" or not isinstance(arguments, dict):
        return False

    def norm(value: Any) -> str:
        return str(value or "").replace("\\", "/").rstrip("/").casefold()

    target = norm(arguments.get("path"))
    if not target:
        return False
    for step in steps:
        if not step.get("ok") or str(step.get("tool") or "") != "local_write_file":
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        for written in (norm(evidence.get("output_path")), norm(args.get("path"))):
            if written and (written == target or written.endswith("/" + target) or target.endswith("/" + written)):
                return True
    return False
