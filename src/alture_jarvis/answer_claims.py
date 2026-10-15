"""답장 판정 — 합격·완료·근거·금액·표행·이름독립·완료상태 (agent.py 에서 2026-10-10 분리를 나눈다)."""
from __future__ import annotations

import re
from typing import Any

from .answer_audit import contradictions as _answer_contradictions
from datetime import datetime
from .answer_gate import table_cells
from .evidence import (
    TYPE_ARTIFACT as EVIDENCE_TYPE_ARTIFACT,
    TYPE_BODY_READ as EVIDENCE_TYPE_BODY_READ,
    TYPE_MUTATION as EVIDENCE_TYPE_MUTATION,
)
from .plan import all_met as plan_all_met, asked_for_work as plan_asked_for_work

_ANSWERABLE_EVIDENCE = frozenset(
    {EVIDENCE_TYPE_BODY_READ, EVIDENCE_TYPE_ARTIFACT, EVIDENCE_TYPE_MUTATION}
)


def _nothing_to_answer_from(steps: list[dict[str, Any]]) -> bool:
    """예고를 되받을지 정할 때 **「답할 재료가 생겼나」**를 본다.

    ★ 2026-09-04 밀양 야놀자 판이 여기서 샜다. 화면을 한 장 찍고
    (`browser_snapshot`) "이제 상세 가격 확인 들어갑니다!"로 끝났다.
    `_nothing_done_yet` 은 **성공한 걸음이 하나 있으니** False 를 냈고, 예고
    되받기가 통째로 꺼졌다. 다음 턴도 같은 모양으로 한 번 더 예고하고 끝났고,
    그 다음 턴은 0 걸음으로 **가격표를 지어냈다.** 세 턴이 한 병에서 나왔다.

    화면을 보는 것은 일이 일어난 것이 아니다 — 원장이 이미 그렇게 갈라 놓았다
    (스냅샷·검색은 `listing`, 여는 것은 `page_open`). 본문을 읽었거나, 무엇을
    만들었거나, 바꿨을 때에만 「답할 재료」다.

    `_nothing_done_yet` 을 고치지 않고 옆에 세우는 이유: 저쪽은 「사용자가 볼 만한
    일이 일어났나」를 재고 여기는 「답을 지을 것이 있나」를 잰다. 조사 판에서
    목록만 보고 답하는 것은 정상이므로(위시켓 상위 5개), 이 판정은 **예고가 있을
    때만** 쓴다.
    """
    for step in steps:
        if not step.get("ok"):
            continue
        record = step.get("evidence_record") or {}
        if str(record.get("type") or "") in _ANSWERABLE_EVIDENCE:
            return False
    return True


_SUCCESS_CLAIM = re.compile(
    r"(완료|저장했|저장됐|저장되었|저장됨|발행했|발행됐|발행되었|보냈|보내졌|전송했|전송됐|"
    r"등록했|등록됐|생성했|생성됐|삭제했|삭제됐|올렸|올라갔|"
    # 2026-08-13: "변경할 준비를 **마쳤습니다**" 가 도구 0 건으로 나갔다. 완료형인데
    # 위 목록 어디에도 안 걸렸다. 라우터 직답 202 건에 대고 재 보니 이 세 낱말이 든
    # 답은 **그 한 건뿐**이었다 — 넣어도 시끄러워지지 않는다.
    r"마쳤|마무리했|끝냈)"
)

# 「바꿨다」는 완료 주장 — 도구를 하나도 안 부른 판에서 이게 나오면 지어낸 것이다(2026-09-28, 가짜 「삭제했습니다」).
# `_SUCCESS_CLAIM` 에 없는 되돌리기·만들기·바꾸기·옮기기·지우기를 더한다. 「했습니다」만 보면 인사말까지 걸리니 동작 낱말에 묶는다.
_DONE_CLAIM = re.compile(
    r"(저장했|저장됐|발행했|보냈|전송했|등록했|생성했|삭제했|삭제됐|지웠|만들었|만들어\s*두었|바꿨|바꾸었|변경했|수정했|"
    r"옮겼|이동했|되돌렸|되돌려\s*놓았|복구했|설치했|추가했|적용했|실행했)(?:습니다|어요|다)"
)

# "가서 보고 왔다"는 주장. 이게 있는데 실제로 본 것이 없으면 답은 창작이다.
_SOURCED_CLAIM = re.compile(
    r"(코드를 (보|확인|분석|살펴)|소스 ?코드|based on code|코드 기준|코드를 기반|"
    # ★ 사용자에게 **권하는 말**(「파일을 확인하고 싶으시다면」·「보시면」·「읽어 보세요」)은 주장이 아니다(2026-09-24 노트북:
    #   빈 양식을 만들고 「열어 보시면 됩니다」라고 했다가 「무엇도 열어 보지 않고 쓴 것」 경고가 붙었다).
    r"(?:파일을|폴더를|구조를) (?:보|확인|읽|살펴|분석)(?!\s*(?:하고\s*싶|하시|하세|하려|하실|해\s*보(?!니)|해\s*주|어\s*보(?!니)|시|세요|실))|"
    r"분석한 결과|조사한 결과|확인한 결과|검토한 결과|살펴본 결과|확인해 ?보니|살펴보니"
    # ★ 영어 답의 「봤다」 주장 (2026-10-01 영어 정직 재기: 「Based on my review of the code」·「After checking the files」가
    #   아무것도 안 열고도 조용했다). **내가 봤다**는 주장만 잡는다 — 「You can check the files」 같은 권유는 주장이 아니다.
    r"|\bbased on (?:my |a |the )?(?:review|reading|analysis|inspection|look|examination) of\b"
    r"|\b(?:after|from|upon) (?:checking|reviewing|reading|analy[sz]ing|inspecting|examining|scanning|going through|looking (?:at|through|into))"
    r" (?:the |your |this |that )?(?:code|codebase|source|files?|folders?|repo(?:sitory)?|project|directory|documents?|pages?|site|website)\b"
    r"|\bI(?:'ve| have)? (?:checked|reviewed|read|analy[sz]ed|inspected|examined|scanned|went through|looked (?:at|through|into))"
    r" (?:the |your |this |that |all )?(?:code|codebase|source|files?|folders?|repo(?:sitory)?|project|directory|documents?)\b"
    r"|\b(?:looking|having looked) (?:at|through) (?:the |your )?(?:code|codebase|source|files|repo(?:sitory)?)\b)",
    re.IGNORECASE,
)

# 목록만 주는 도구. **무엇이 있는지**는 알려 주지만 **무엇인지**는 알려 주지 않는다.
_LISTING_TOOLS = frozenset(
    {
        "local_list_directory", "local_search_files", "local_index_codebase",
        # 유니티 프로젝트 훑기(2026-09-27) — 개수·경로 **목록**이다. 에셋 내용을 읽은 것은 아니다.
        "unity_project_info",
        # 열린 에디터 읽기(2026-09-27 · 2단계) — 계층·선택·콘솔 **목록**이다. 에셋 파일을 연 것이 아니다.
        "unity_editor_status", "unity_editor_look",
        # 찾기 결과는 **목록**이다 — 줄 하나를 봤다고 그 파일을 읽은 것이 아니다.
        "local_grep", "local_glob",
        "hwp_list_open",
        "browser_search", "browser_links", "browser_snapshot",
        # 사이트 자기 검색도 **목록**이다. 여기서 나온 항목을 열어야 출처가 된다.
        "browser_site_search",
        # 사이트가 공개한 출처(피드·사이트맵·공식 링크) **목록**이다(2026-09-18). 열어야 출처가 된다.
        "browser_site_sources",
        "google_drive_search", "google_gmail_search", "naver_web", "naver_news",
        "github_search",
    }
)

# 이름 -> 한 줄 쓰임. NAS 설명문은 High Thinking 용이라 길고 문어체라서, 순서에
# 박을 때는 짧은 쪽이 낫다. 목록에 없는 도구는 이 절에 안 실린다(스키마는 도구
# 정의로 이미 모델에 가 있다).
_INHOUSE_TOOL_HINTS: dict[str, str] = {
    "admission_quant_lookup": "대학·학과별 3개년 경쟁률·합격선·모집인원",
    "admission_major_profile_lookup": "그 학과가 어떤 곳인가(대학알리미 취업률·중도탈락률 포함)",
    "admission_candidates_by_grade": "이 성적으로 갈 만한 곳 역방향 후보군",
    "admission_major_semantic_search": "말로 설명한 관심사에서 학과 찾기",
    "admission_probability_simulate": "특정 대학·학과 합격 확률(실컷 근거)",
    "career_strategy_lookup": "학과↔직업↔기업, 연봉·전망",
    "official_exam_items_lookup": "공식 기출 문항",
    "question_bank_same_type": "같은 유형 문제 뽑기",
}


# 내용을 실제로 가져오는 도구.
_CONTENT_TOOLS = frozenset(
    {
        "local_read_text_file", "local_read_document",
        # 유니티 레시피(2026-09-27) — 유니티가 에셋 설정·참조를 **실제로 열어 읽은** 결과 파일이다.
        # 첫 레시피는 전부 읽기다. 바꾸는 레시피가 생기면 그 판정은 쓰기 쪽(measure_autonomy.WRITE_TOOLS)에서 따로 한다.
        "unity_run_recipe",
        "hwp_read",
        "browser_extract", "browser_read", "browser_open", "browser_open_result",
        # 받은 것은 **가져온 내용**이다 — 파일이 손에 들어왔으니 목록이 아니다.
        # (그 뒤 local_read_document 로 읽으면 그것도 내용으로 한 번 더 센다.)
        "browser_download",
        # 페이지가 이미 받아 온 JSON 에서 값을 찾는다(2026-09-18) — 가져온 내용이다.
        "browser_page_data",
        # 칸을 잘라 그림으로 읽는다(숨긴 가격) — 가져온 내용이다.
        "ui_read_value",
        "google_calendar_upcoming",
        # 드라이브는 **찾기**(google_drive_search, 목록)와 **읽기**가 다른 도구다.
        # 읽기가 없던 동안 자비스는 브라우저로 docs.google.com 을 열었고 로그인
        # 화면만 봤다 — 그런데도 "2개 읽었다"로 세어졌다(2026-08-12 실측).
        "google_drive_read",
    }
    # ★ 우리 DB 조회도 **내용을 가져오는 것**이다 (2026-08-13).
    #
    # 안 넣었더니 두 곳이 동시에 틀렸다:
    #   · 눈금(`measure_autonomy.py`)이 이 호출들을 "분류 안 된 도구"로 흘렸다.
    #     읽기 성공률의 분모에 안 들어갔다는 뜻이다 — 어제 `pick_suggestion` 71건이
    #     같은 자리에서 통째로 빠졌었다.
    #   · 정직성 검사가 **오탐**을 낼 수 있다. DB 에서 실제 행을 읽고 "확인한 결과"
    #     라고 쓴 답에 "실제로 가지 않았습니다"가 붙는다.
    #
    # 출처 계산(`_sources_read`)은 안 흔들린다 — 거기는 주소·경로가 있어야 세는데
    # 이 도구들은 둘 다 없어서 그냥 지나간다. 목록은 힌트표 하나에서 온다.
    | frozenset(_INHOUSE_TOOL_HINTS)
)

_READ_TOOLS = _LISTING_TOOLS | _CONTENT_TOOLS

# 검색 결과 화면은 출처도 아니고, 못 읽었다고 장부에 적을 곳도 아니다.
# 여기서 막히는 것은 그 사이트의 절차 문제가 아니라 검색이 막힌 것이고,
# 그건 이미 bot_check 로 따로 잡힌다.
_SEARCH_HOSTS = frozenset({"search.naver.com", "bing.com", "www.bing.com"})

# "화면에 띄워 놨다"는 주장. 이건 사람이 화면을 보면 바로 대조되는 사실이라,
# 틀렸을 때 신뢰가 제일 빨리 깨진다.
#
# 2026-08-10 실측: `browser_open` 이 wishket.com/login 을 ok=True 로 열었는데
# 답변은 "정상적으로 열리지 않고 있습니다"였고, 이어서 "메인 페이지를 띄워
# 두었습니다"라고 했다. 그때 화면의 탭은 **about:blank** 였다. 도구 결과와도
# 어긋나고 화면과도 어긋난 말을 한 번에 두 개 한 셈이다.
_LEFT_OPEN_CLAIM = re.compile(
    r"(띄워\s*(놨|뒀|두었|놓았)|열어\s*(놨|뒀|두었|놓았)|화면에\s*(띄웠|열었)|"
    r"띄워\s*드렸|열어\s*드렸"
    # 영어 답(2026-10-01 영어 정직 재기: 「I've opened the result file on your screen」이 조용했다).
    r"|\bI(?:'ve| have)? (?:opened|left|pulled up|brought up|put|displayed|kept)\b[^.\n]{0,60}"
    r"\b(?:on (?:your|the) screen|for you|in (?:your|the|a new) (?:browser|tab|window)|open (?:for you|on))"
    r"|\b(?:it(?:'s| is)|they(?:'re| are)|the (?:page|file|tab|site)s? (?:is|are)) (?:now )?open (?:on|in) (?:your|the) (?:screen|browser)\b)",
    re.IGNORECASE,
)

# 실패했을 때 **다음에 무엇을 할지.**


# 개수 요구("공고 4개는 직접 열어 읽어라")를 여기서 따로 재던 정규식 둘은
# **지웠다** (2026-08-13). `plan._COUNT` 와 쌍둥이라고 주석까지 달아 놨었는데,
# 실제로 갈렸다 — 이쪽만 "출처를 대고 개수를 말한 것도 읽기 요구"로 고쳐졌고
# 계획 층은 안 고쳐져서, 같은 문장을 놓고 두 층이 다른 말을 했다.
# 이제 `plan.extract` 하나가 판정하고 이 파일은 그 결과를 받아 쓴다.

# 답에 적힌 **돈 액수**. 이것만 따로 보는 이유는 아래 `_money_grounding_check` 에.
_MONEY_CLAIM = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(억\s*원?|만\s*원|천\s*원|원)")
# 적립 **포인트**도 돈처럼 읽힌다(2026-09-28 T1 O1b: 「1,300P (5%)」를 가격×5% 로 **계산**해 적었는데 「원」만 봐서 안 걸렸다).
# 금액 검사에서만 쓴다 — `_MONEY_CLAIM` 을 넓히면 표 판별(`_TABLE_ROW` 와 같이 쓰는 자리)까지 바뀐다.
_POINT_CLAIM = re.compile(r"([0-9][0-9,]*)\s*(P|포인트)(?![A-Za-z])")
# ★ 영어 답의 금액 (2026-10-01 영어 정직 재기: 「$129.99」·「129.99 USD」를 지어내도 **경고 0**이었다 — 위 둘은 원·P 만 본다).
#   기호 앞(`$24.99`·`€19`·`₩19,800`)과 낱말 뒤(`129.99 USD`·`25 dollars`) 둘 다. 소수점 값은 **소수점까지** 원문과 대조한다 —
#   한국어 규칙의 「세 자리 미만은 건너뛴다」를 그대로 쓰면 `$24.99` 같은 지어낸 값이 다 빠져나간다.
_EN_MONEY_CLAIM = re.compile(
    r"(?:[$€£¥₩]|(?<![A-Za-z])(?:US\$|USD|EUR|GBP|KRW)\s?)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
    r"|([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s?(?:USD|EUR|GBP|JPY|KRW|dollars?|euros?|pounds?|won)\b",
    re.I,
)
# 줄↔페이지 대조에서 「그 페이지의 주 항목」으로 볼 본문 앞자리. 교보 상세는 제목이 33자째, 추천 띠는 한참 뒤다(2026-09-28 실측).
_ROW_BODY_HEAD_CHARS = 1200
# 줄의 **값**을 대조할 첫머리. 이름보다 좁게 — 교보 실측(09-28): 종이책 값 260자째 · 전자책 값 약 680자째 · 추천 띠 1,350자째.
_ROW_VALUE_HEAD_CHARS = 900

# 자릿수 구분 쉼표만 뗀다. `1,234` → `1234`, 문장의 쉼표는 건드리지 않는다.
_DIGIT_COMMA = re.compile(r"(?<=\d),(?=\d)")

# 표의 줄. **가져온 값처럼 보이는 것**의 대리 지표다 — 지어낸 답은 거의 항상 표로
# 나왔다(실측 7/7). 다만 이것 하나로는 못 쓴다: 도구 없이 표를 그린 답 47 건 중
# 대부분이 정당한 분석·조언표였다. 반드시 '출처 인용'과 AND 로 묶어서 본다.
_TABLE_ROW = re.compile(r"^\s*\|.*\|.*\|", re.M)


#: 답이 **「N건을 열어/읽었다」고 과거형으로** 말한 자리. 같은 문장에 못 했다는 말·앞으로 하겠다는 말이 있으면 주장이 아니다.
_CLAIMED_READS = re.compile(
    r"(\d{1,3})\s*(?:건|개|곳|편|쪽|페이지)(?:의\s*[가-힣]{1,8})?[을를은는이가]?\s*"
    r"(?:모두\s*|전부\s*|직접\s*|하나씩\s*|각각\s*)*(?:열어|열람|읽)[^.!?。\n]{0,40}?(?:었|았|했)(?:습니다|어요|다|으나|지만|고)")
_CLAIM_UNDONE = re.compile(r"못|시도|려고|려\s|겠|수\s*있도록|으면|하면|않")
_PAGE_TOOLS = frozenset({
    "browser_open", "browser_open_result", "browser_extract", "browser_read", "browser_read_pdf",
    "local_read_text_file", "local_read_document", "google_drive_read",
})


_FACT_ROWS_UNDER_ONE_LABEL = 3


def _name_words_were_read_together(name: str, source: str, *, window: int = 80) -> bool:
    """이름의 **낱말이 전부**, 읽은 글의 한자리(가까운 범위)에 모여 있는가.

    ★ 2026-10-04 채용 공고 조사 판: 「KAIST 이민호 연구실」에 「읽지 않고 적은 것」이 붙었다 — 그 공고를 열어 읽었고 제목은
      「KAIST AI미래학과 이민호교수 연구실 …」이었다. 모델이 사이의 말을 빼고 줄여 부른 것이다. 낱말이 따로따로 흩어져 있는 것은
      치지 않는다(지어낸 이름의 낱말도 긴 글 어딘가엔 다 있다) — 첫 낱말이 나온 자리마다 그 둘레에 나머지가 다 있어야 한다.
    """
    words = [word for word in re.split(r"\s+", str(name or "").strip()) if len(word) >= 2]
    if len(words) < 2 or not any(len(word) >= 3 for word in words):
        return False
    at = source.find(words[0])
    while at >= 0:
        near = source[max(0, at - window): at + len(words[0]) + window]
        if all(word in near for word in words[1:]):
            return True
        at = source.find(words[0], at + 1)
    return False


def _is_a_list_of_facts(name: str) -> bool:
    """「최나래 / 1991년생 / 한울대 행정졸업」처럼 빗금으로 **사실 여럿을 늘어놓은 줄**인가 — 한 항목의 이름이 아니다.

    ★ 같은 판: 드라이브에서 읽은 이력서를 한 줄로 간추린 굵은 글이 「읽지 않고 적은 이름」으로 잡혔다. 이름 검사는 목록의 항목
      (회사·상품·글 제목)을 보려는 것이다. 빗금 둘 이상으로 나눈 줄은 이름이 아니라 요약이다.
    """
    return len(re.findall(r"\s/\s", str(name or ""))) >= 2


def _completion_state(
    stop_reason: str, plan_results: list[tuple[Any, bool, str]], prompt: str = ""
) -> str:
    """작업 상태와 별도로, 답이 어디까지 검증됐는지 사람이 읽을 이름으로 남긴다."""
    if plan_results:
        return "complete" if plan_all_met(plan_results) else "partial"
    if stop_reason in {"wrapped_up:goal_met", "claude_code_completed"}:
        return "complete"
    if stop_reason == "model_answered":
        # 대조 가능한 개수·사이트·행위 요구를 못 뽑았다는 뜻이지, 덜 했다는
        # 증거는 아니다. completed도 partial도 지어내지 않는다.
        #
        # ★ 2026-08-21: 그런데 이 한 칸이 **두 가지**를 뜻하고 있었다.
        #
        #     "지금 몇 시야"            → 대조할 요구가 원래 없다. 정상
        #     "그래서 공고를 좀 찾아줘"  → 일을 시켰는데 못 뽑았다. 눈금의 구멍
        #
        # 그리고 눈금(`measure_autonomy._goal_reached`)이 `answered` 를 **성공으로**
        # 세고 있어서, 못 잰 판이 L4 분자에 들어가 있었다(위임 54판 중 17판 = 31.5%).
        # 이제 둘을 가른다 — 뒤쪽은 성공도 실패도 아닌 **모름**이다.
        return "unmeasured" if plan_asked_for_work(prompt) else "answered"
    if stop_reason == "model_done":
        return "complete"
    return "partial"


def _self_contradiction(answer: str) -> str:
    """답 안에서 서로 부딪치는 말이 있으면 한 줄로. 없으면 빈 문자열."""
    found = _answer_contradictions(answer)
    return found[0]["detail"] if found else ""

#: 구분줄 칸 하나 — 대시 3개 이상, 양끝 콜론, 끝에 붙은 오타 글자 두 개까지.
TABLE_RULE_TYPO =re.compile(r"^\s*(:?)-{3,}(:?)[0-9A-Za-z]{0,2}\s*$")


#: 날짜 바로 뒤 괄호 안의 「오늘·내일·모레」 — 「10/08(내일!)」·「10월 8일 (모레)」.
_DATE_THEN_DAY_WORD = re.compile(
    r"(?P<month>\d{1,2})\s*(?:[/.]|월\s*)(?P<day>\d{1,2})\s*일?\s*[(（\[]\s*(?P<word>오늘|내일|모레)"
)
_DAY_WORDS = {"오늘": 0, "내일": 1, "모레": 2}


def mend_day_words(text: str | None, today: "datetime | None" = None) -> str | None:
    """날짜 옆에 붙인 「내일」이 **그 날짜와 안 맞으면** 맞는 말로 고친다.

    ★ 2026-10-04 채용 공고 조사 판(788ef850): 마감 「10/08(내일!)」 — 날짜는 공고에서 맞게 읽었는데 오늘이 10/04 라 나흘 뒤다.
      「가장 급함」이라며 추천 순서까지 그 말에 기댔다. 날짜는 읽은 것이고 「내일」은 모델이 덧붙인 셈이라, 둘이 다르면 **날짜가 맞다.**
    날짜와 낱말이 한자리에 같이 있을 때만 고친다(「내일 다시 볼게요」 같은 말은 건드리지 않는다). 해가 안 적힌 날짜는 올해로 보고,
    반년 넘게 지난 날짜면 내년으로 본다(연말에 1월 마감).
    """
    if not text:
        return text
    now = (today or datetime.now()).date()

    def fix(match: "re.Match[str]") -> str:
        try:
            target = now.replace(month=int(match["month"]), day=int(match["day"]))
        except ValueError:
            return match.group(0)
        days = (target - now).days
        if days < -180:
            try:
                days = (target.replace(year=now.year + 1) - now).days
            except ValueError:
                return match.group(0)
        if days == _DAY_WORDS[match["word"]]:
            return match.group(0)
        right = next((word for word, gap in _DAY_WORDS.items() if gap == days), "") or (
            f"{days}일 뒤" if days > 0 else f"{-days}일 지남"
        )
        return match.group(0)[: match.start("word") - match.start()] + right

    return _DATE_THEN_DAY_WORD.sub(fix, text)


def repair_table_rules(text: str | None) -> str | None:
    """모델이 낸 마크다운 표의 **망가진 구분줄**을 고쳐 쓴다 (2026-09-30 촬영 판).

    `| :--- | :---0 |` 처럼 칸 끝에 글자가 붙으면 화면 해석기가 표를 통째로 글로 뭉개 보였다.
    표 머리줄(파이프로 시작) **바로 아래** 줄만, 칸이 전부 구분줄 모양일 때만 고친다. 정렬 콜론은 지킨다.

    ★ 답이 없는 판(`None`)은 그대로 돌려준다. 받는 쪽은 `str(answer or "")` 로 받던 자리라, 여기서 `.split` 을 부르면
      판이 `'NoneType' object has no attribute 'split'` 로 죽는다(2026-09-30 촬영 판 5f45a7e3 — 질문 카드·파일 쓰기·실행까지 간 판).
    """
    if not text:
        return text
    lines = text.split(chr(10))
    changed = False
    for index in range(1, len(lines)):
        line = lines[index]
        if not lines[index - 1].strip().startswith("|") or not line.strip().startswith("|"):
            continue
        cells = table_cells(line)
        if not cells or not all(TABLE_RULE_TYPO.match(cell) for cell in cells):
            continue
        fixed = "| " + " | ".join(
            f"{m.group(1)}---{m.group(2)}" for m in (TABLE_RULE_TYPO.match(cell) for cell in cells) if m
        ) + " |"
        if fixed.replace(" ", "") != line.strip().replace(" ", ""):
            lines[index] = fixed
            changed = True
    return chr(10).join(lines) if changed else text
