"""요청의 모양과 걸음·답의 모양을 낱말 규칙으로 판정 — agent.py 에서 분리(2026-10-09).

어디에 물었는가 · 구체값을 달랐는가 · 우리 데이터에 물어야 하는가(812-996)와
걸음 기록에서 무엇을 읽는가 · 답이 무엇을 주장하는가(1070-1289) —
모두 `english`·`plan`·`urllib`·`pathlib` 만 부르고 agent.py 의 다른 상수에 기대지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from . import english as _english
from .plan import all_met as plan_all_met

# ── 어디에 물었는가 ──────────────────────────────────────────────────────────
#
# ★ 2026-08-13. 오늘 10 판을 실제로 돌려 보고 나온 자리다.
#
# "쿠팡에서 무선마우스 상위 3개 제품명과 가격을 알려줘" — 사람이 가장 자연스럽게
# 쓰는 이 형태가 라우터의 조사 갈래에 **하나도 안 걸렸다.** 그 갈래는
# `동사목록 ∧ 대상목록` 인데 "알려줘"는 동사목록에 없고 "무선마우스"는 대상목록에
# 없다. 10 판 중 결정론으로 걸린 것은 1 판뿐이었고, 모델 판단에 넘어간 9 판 중
# **7 판이 사이트에 가지도 않고 답을 지어냈다.** 얼려 둔 표본과 대조하니 다나와
# 1위도 위시켓 1위도 실제와 전혀 달랐다.
#
# 낱말을 더 넣는 것은 두더지 잡기다 — 바로 앞 판에서 "찾아서"를 넣었는데 이번엔
# "알려줘"로 샜다. 그래서 낱말이 아니라 **누구한테 물었는가**를 본다. 출처를 대고
# 구체적인 값을 달라고 한 것은, 모델이 아는 것을 말하라는 뜻이 아니라 거기 가서
# 보라는 뜻이다.
_NAMED_SOURCE = re.compile(r"([가-힣A-Za-z][가-힣A-Za-z0-9-]{1,9})에서")

# ★ 이름 뒤 괄호 설명은 걷어 내고 본다 (2026-10-02 대표 운영 판).
#
#   「K-Startup(k-startup.go.kr)에서 … 지원사업 5개를 찾아 … 엑셀로」가 출처 판정에 안 걸렸다 — 이름과 「에서」 사이에
#   괄호가 끼었기 때문이다. 그래서 「5개」가 읽기 개수 요구로 안 올라갔고(계획 = 산출물 하나), 22걸음째에 상세 공고를 읽는
#   중인데 「남은 목표(파일)에 진전 없음」으로 접혀 1행만 내고 끝났다. 붙임표(K-Startup)도 이름 안에서 받는다.
_PAREN_BEFORE_PARTICLE = re.compile(r"\s*[(（][^()（）]{1,80}[)）](?=\s*(?:에서|에|으로|로))")

# ★ 「~에 들어가서」도 출처다 (2026-09-04).
#
# 「야놀자**에** 직접 들어가서 밀양 숙소를 찾아줘」가 출처 판정에 **안 걸렸다.**
# 조사가 「에서」가 아니라 「에」였기 때문이다. 사이트에 들어가라는 말로는 이쪽이
# 더 자연스러운데, 그물이 조사 하나만 보고 있었다.
#
# 두 군데가 동시에 망가진다. ① 라우터가 「가서 봐야 아는 것」으로 안 보고,
# ② `SiteAtlas` 가 **배울 이름을 못 받는다** — 어제 야놀자를 성공적으로 열고
# 제목까지 「NOL(야놀자)」로 받았는데도 표에 안 들어갔다. 그래서 오늘 모델이
# 주소를 지어냈다(`yyj.co.kr`).
#
# 조사만 넓히면 안 된다 — 「3시에」·「회의에」가 전부 출처가 된다. **들어간다는
# 동사와 짝**일 때만 본다. 실측(프롬프트 1,706): 새로 걸린 판 4, 그중 셋이 진짜
# 사이트(야놀자·사람인·위시캣), 둘은 불용어로 뺐다(페이지·관리).
_NAMED_SOURCE_ENTERED = re.compile(
    # ★ 이름은 **게으르게** 잡는다. 욕심내면 「설정으로」에서 「설정으」+「로」로
    # 잘려 조사를 이름이 먹는다.
    r"([가-힣A-Za-z][가-힣A-Za-z0-9]{1,9}?)\s*(?:으로|에다|에|로)\s*"
    r"(?:직접\s*|한번\s*|좀\s*)*(?:들어가|들어와|접속|방문|가서|가 봐|가봐)"
)

# 주소를 직접 준 것은 그 자체로 "여기를 봐라"다.
_EXPLICIT_URL = re.compile(
    r"https?://|[a-z0-9][a-z0-9-]*\.(?:com|co\.kr|kr|net|org|io|ai)\b", re.IGNORECASE
)

# "~에서"가 붙어도 출처가 아닌 말. 전부 실측으로 걸러진 것들이다 —
# "다음 **영상에서** 만나요", "**지구온난화에서** 왜 문제가", "30대 40대 50대
# **분들에서**", "그런 **입장에서**". 이 목록은 넉넉해도 안전하다: 여기 없는 말이
# 하나 새면 에이전트로 한 번 더 갈 뿐이고, 그 비용은 몇 초다.
_NOT_A_SOURCE = frozenset(
    {
        # 지시·시점
        "여기", "거기", "저기", "지금", "오늘", "어제", "내일", "아까", "방금", "어디",
        "이거", "그거", "저거", "우리", "너", "내",
        # 이 컴퓨터 안쪽(로컬 갈래가 가져가야 한다)
        "집", "회사", "사무실", "컴퓨터", "폴더", "파일", "메모", "대화", "화면", "프로그램",
        # 추상명사 — 긴 글에 흔히 섞인다
        "입장", "관점", "상황", "부분", "분들", "영상", "측면", "의미", "기준", "상태",
        "과정", "차원", "개념", "현장", "수준", "결과", "이상", "이하", "전체", "일부",
        "중간", "차이", "관계",
        # 「~에 들어가서」를 보기 시작하면서 걸린 것들. 사이트가 아니라 그 안의 자리다.
        "페이지", "관리", "메뉴", "탭", "설정", "목록", "수정",  # 「화면」은 위에 이미 있다
        # 들어가는 곳이지만 사이트가 아닌 것 — 사람이 실제로 들어가는 자리들.
        "회의", "수업", "교실", "사이트", "자리", "단톡방", "채팅방",
    }
)

# 구체적인 값을 달라는 요구. "알려줘"라는 동사가 아니라 **무엇을 달라고 했는지**를
# 본다 — 지어낼 수 있는 것과 가서 봐야 아는 것의 경계가 여기다.
#
# 개수 뒤 부정 후방탐색은 `plan._COUNT` 와 같은 이유다("3개월"은 개수 요구가 아니다).
_PARTICULAR_REQUEST = re.compile(
    r"(\d{1,2}\s*(?:개|건|곳|권|명|가지|종|군데)(?![월년국인])"
    r"|가격|시세|얼마|제목|목록|리스트|순위|상위|후기|평점|재고|공고|매물|스펙|"
    r"몇\s*(?:개|건|곳|권|명)"
    # 그 사이트의 **어디**인지도 가서 봐야 아는 값이다. 메뉴 이름과 경로를 기억에서
    # 쓰면 그럴듯한 길 안내가 나오고, 따라가면 그런 메뉴가 없다(대학알리미 실측).
    r"|어디서|어디에|어디로|어느\s*(?:메뉴|탭|페이지|화면)|경로)"
)

# 붙여넣은 문서는 이 판정의 범위 밖이다. 카메라 지름길이 이미 같은 교훈을 배웠다
# (`CAMERA_SHORTCUT_MAX_CHARS`) — 글이 길수록 흔한 낱말이 우연히 다 들어 있게 된다.
# 실측: 오탐으로 걸린 것들("프로그램에서", "개념에서", "현장에서")이 전부 긴
# 붙여넣기였다. 오늘 실제 요청은 전부 60 자 미만이다.
NAMED_SOURCE_MAX_CHARS = 200


#: 이 PC 의 디스크를 부르는 말 — 「E 드라이브」·「C드라이브」·「D: 드라이브」·「외장 드라이브」.
_LOCAL_DISK = re.compile(r"(?i)(?<![A-Za-z])[A-Z]\s?:?\s?\\?\s?드라이브|(?:외장|로컬|하드|내장)\s*드라이브")
#: 바깥 저장소의 드라이브 — 이쪽은 출처다.
_CLOUD_DRIVE = re.compile(r"(?i)구글\s*드라이브|google\s*drive|원\s*드라이브|onedrive")


def named_sources(prompt: str) -> list[str]:
    """이 요청이 **어디에** 물어본 것인지. 출처를 안 댔으면 빈 목록.

    라우터(갈지 말지)와 정직성 검사(갔다고 말해도 되는지)가 이 함수 하나를
    공유한다. 둘이 서로 다른 기준을 쓰면 한쪽이 보낸 것을 다른 쪽이 못 알아본다 —
    예고 판정(`PROMISED_ACTION`)을 공유하는 것과 같은 이유다.
    """
    compact = " ".join(prompt.split())
    if _english.english_dominant(compact):
        # 영어는 조사 대신 전치사로 댄다(「on Saramin」·「go to naver.com」) — `english.named_sources`.
        return _english.named_sources(compact)
    compact = _PAREN_BEFORE_PARTICLE.sub("", compact)
    seen: list[str] = []
    for pattern in (_NAMED_SOURCE, _NAMED_SOURCE_ENTERED):
        for name in pattern.findall(compact):
            if name in _NOT_A_SOURCE or len(name) < 2:
                continue
            # ★ 「E 드라이브에서 찾아줘」의 드라이브는 **이 PC 의 디스크**다 (2026-10-05 판 b4b71589). 바깥 출처로 읽혀
            #   「근거 읽기」의 대상이 브라우저가 됐고, 파일을 찾은 뒤 하네스가 브라우저 결과 열기를 억지로 시켰다.
            #   드라이브 글자가 붙은 것만 뺀다 — 「구글 드라이브에서」는 그대로 출처다.
            if name.endswith("드라이브") and _LOCAL_DISK.search(compact) and not _CLOUD_DRIVE.search(compact):
                continue
            if name not in seen:
                seen.append(name)
    return seen


def asks_for_particulars(prompt: str) -> bool:
    """가서 봐야 아는 값을 달라고 했는가."""
    compact = " ".join(prompt.split())
    if _english.english_dominant(compact):
        # 수량은 **읽을 것**을 셀 때만 구체값 요구다 — 「5 sentences」는 내놓을 글의 길이다(한국어 표도 「5문장」은 안 본다).
        return bool(
            _english.PARTICULAR_REQUEST.search(compact)
            or any(role != _english.ROLE_OUTPUT for _v, _q, role, _s, _e in _english.counts(compact))
        )
    return bool(_PARTICULAR_REQUEST.search(compact))


def has_explicit_url(prompt: str) -> bool:
    """주소를 직접 준 요청인가. 이건 출처를 댄 것보다 더 분명하다."""
    return bool(_EXPLICIT_URL.search(prompt))


# ── 우리 데이터에 물어야 하는 질문인가 ──────────────────────────────────────
#
# 2026-08-13 인수인계 4-1. 입시·진로 조회 도구가 NAS 에 스무 개 넘게 있는데
# 자비스 목록에는 하나도 없었다. 도구를 붙였으니 이제 **그리로 보내는 길**이 필요하다.
#
# 왜 라우터가 정하는가: 이 질문들은 모델이 **답할 수 있는 것처럼 보인다.** "중앙대
# 소프트웨어학부 작년 경쟁률"은 어딘가에서 본 적 있는 종류의 숫자라 그럴듯한 값이
# 바로 나온다. 웹 조사와 달리 "찾아봐"라는 말도 안 붙는다 — 사람은 우리가 그 데이터를
# 가지고 있다고 생각하니까 그냥 묻는다. 그래서 `_requires_web_research` 도
# `_requires_named_source` 도 이걸 못 잡는다("~에서"가 없다).
#
# 판정은 두 신호의 AND 다:
#   ① 대상 — 학교·학과·전형을 가리키는 **접미사**(대학교·학과·학부·전공…). 이쪽은
#      낱말표가 아니라 문법이라 학교 이름이 늘어도 목록이 안 늘어난다.
#   ② 값   — 우리 DB 가 실제로 들고 있는 종류의 값(경쟁률·컷·취업률·연봉…).
#
# 하나만으로는 안 된다. ①만 보면 "고려대 나온 친구가 그러는데"가 걸리고, ②만 보면
# "연봉 얼마 받아야 하나" 같은 잡담이 걸린다.
_INHOUSE_TARGET = re.compile(
    r"(대학교|대학원|[가-힣]{2,6}대(?=\s|$|[의를은는이가로])|학과|학부|전공|"
    r"수시|정시|학생부\s*종합|학종|교과\s*전형|논술\s*전형|내신|수능|모의고사|생기부|학생부)"
)

# 우리가 실제로 가진 축만 적는다 — 없는 것을 여기 적으면 도구가 빈손으로 돌아오고,
# 그때 모델은 기억으로 메운다(그게 이 갈래를 만든 이유다).
_INHOUSE_VALUE = re.compile(
    r"(경쟁률|합격선|합격\s*컷|커트라인|충원|추가\s*합격|추합|모집\s*인원|모집\s*정원|"
    r"환산\s*(?:점수|등급)|백분위|표준\s*점수|합격\s*(?:확률|가능성)|지원\s*가능|"
    r"취업률|중도\s*탈락|등록금|장학|연봉|직업\s*전망|진로|어느\s*(?:대학|학과)|"
    r"어디\s*(?:쓸|넣|지원|갈))"
)


def asks_inhouse_data(prompt: str) -> bool:
    """우리 입시·진로 DB 가 답해야 하는 질문인가.

    `named_sources` 와 마찬가지로 **길면 범위 밖**이다. 붙여넣은 생기부 전문에는
    이 낱말이 전부 들어 있어서, 길이 제한이 없으면 아무 글이나 다 걸린다.
    """
    compact = " ".join((prompt or "").split())
    if len(compact) > NAMED_SOURCE_MAX_CHARS:
        return False
    return bool(_INHOUSE_TARGET.search(compact)) and bool(_INHOUSE_VALUE.search(compact))


# 인자가 **대상을 스스로 가리키는** 브라우저 도구. 이건 페이지로 나누면 안 된다 —
# A→B→A→B 로 오가는 것을 지문이 못 막게 된다(그건 진짜 되풀이다).
#
# `browser_switch_tab(index=0)` 은 여기서 뺐다. 숫자 index는 절대 대상이 아니다:
# 탭이 열리고 닫히면 같은 숫자가 다른 탭을 가리키고, 무엇보다 **현재 어느 탭에서
# 출발했는가**가 동작을 결정한다. 2026-08-17 라이브에서는 0→2→0 이동의 세 번째
# index=0이 전역 중복으로 막혀 580초 판의 직접 실패가 됐다. 페이지를 지문에 넣어도
# A↔B 왕복은 같은 (출발 페이지, index) 쌍이 세 번째 반복될 때 그대로 잡힌다.
_ABSOLUTE_TARGET_TOOLS = frozenset({"browser_open", "browser_search"})


def _site_of(url: str) -> str:
    """주소의 사이트(호스트)만. 주소가 아니면 그대로."""
    host = urlparse(str(url or "")).netloc.lower()
    return host.removeprefix("www.") or str(url or "")


def _page_scoped(tool: str) -> bool:
    """이 도구의 되풀이 여부를 **페이지별로** 따져야 하는가."""
    return tool.startswith("browser_") and tool not in _ABSOLUTE_TARGET_TOOLS


def _model_answer_stop_reason(plan_results: list[tuple[Any, bool, str]]) -> str:
    """모델이 답을 냈을 때 **계획 미달**과 **계획을 모름**을 구별한다."""
    if not plan_results:
        return "model_answered"
    return "model_done" if plan_all_met(plan_results) else "model_stopped_early"


def _review_scratch_files(steps: list[dict[str, Any]], since: int, request_text: str) -> list[str]:
    """검토가 시작된 뒤 이 판이 **새로 만든** 파일 가운데, 판이 끝날 때 치워도 되는 것들의 경로.

    ## 왜 (2026-10-07 어려운 사다리 L7·L8)

    검토 턴은 경계값을 확인하려고 `_verify.py`·`_edge_probe.py`·`_adversarial.csv` 같은 파일을 사용자 폴더에 만들어 돌린다.
    검토 요청문에 「점검용 파일을 만들었다면 지워라」가 적혀 있는데, 만든 6판 중 2판만 지웠다 — 13판 중 4판이 그 파일을
    남겼다(답에는 매번 적었다). 안내문으로 안 되는 것은 코드로 옮긴다.

    치우는 것은 좁다:
      - **검토가 시작된 걸음 이후**에 이 판이 `local_write_file` 로 **새로 만든** 파일(있던 파일을 고친 것은 아니다).
      - 판이 끝날 때 아직 있고, 이 판이 스스로 지우지 않은 것.
      - 요청문에 그 파일 이름이 없다(사용자가 만들라고 한 파일이 아니다).
      - 검토 중 이 판이 고친 다른 파일이 그 이름을 쓰지 않는다(검토가 구현을 고치며 새 모듈을 만든 경우 — 그건 남긴다).
    """
    if since < 0:
        return []
    made: dict[str, int] = {}
    touched: set[str] = set()
    for index, step in enumerate(steps):
        if index < since or not step.get("ok"):
            continue
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        path = str(evidence.get("output_path") or evidence.get("path") or "")
        if not path:
            continue
        tool = str(step.get("tool") or "")
        if tool == "local_write_file" and evidence.get("created") is True:
            made[path] = index
        elif tool == "local_delete_file":
            made.pop(path, None)
        elif tool in {"local_write_file", "local_apply_edit"}:
            touched.add(path)
    if not made:
        return []
    lowered = (request_text or "").casefold()
    used_by_the_fix = ""
    for other in touched - set(made):
        try:
            used_by_the_fix += Path(other).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    scratch: list[str] = []
    for path in made:
        target = Path(path)
        if not target.is_file() or target.name.casefold() in lowered:
            continue
        if target.stem and target.stem in used_by_the_fix:
            continue
        scratch.append(path)
    return scratch


#: 제자리여서 접은 판의 머리말 — 까닭 이름 → (한국어, 영어). `not_getting_anywhere` 가 돌려주는 이름과 걸음 안전망.
_STUCK_LEAD = {
    "same_failure": ("같은 확인 실패가 되풀이돼 멈췄습니다", "Stopped because the same check failure kept repeating"),
    "rewriting": (
        "같은 파일을 돌려 보지 않고 거듭 다시 써서 멈췄습니다",
        "Stopped after rewriting the same file again and again without running it",
    ),
    "nothing_new": (
        "한동안 새로 본 것도, 고친 것도, 돌려 본 것도 없어 멈췄습니다",
        "Stopped because the recent steps looked at nothing new, changed nothing and ran nothing",
    ),
    "step_backstop": ("걸음 수 안전망에 닿아 멈췄습니다", "Stopped at the step safety limit"),
}


def _code_budget_head(stop: dict[str, Any], written: list[str], *, english: bool = False) -> str:
    """시간을 다 써서(또는 제자리여서) 접은 코드 판의 답 맨 위에 붙는 줄. 모델이 쓰지 않는다 — 센 값과 걸음 기록만 적는다."""
    minutes = max(1, round(int(stop.get("elapsed_sec") or 0) / 60))
    files = [str(path) for path in written if str(path).strip()]
    shown = ", ".join(Path(path).name for path in files[:6]) + (
        (f" (+{len(files) - 6})" if english else f" 외 {len(files) - 6}개") if len(files) > 6 else ""
    )
    lead = _STUCK_LEAD.get(str(stop.get("why") or ""))
    if lead:
        # 맡긴 판 — 「이어서 해줘」를 권하지 않는다. 같은 자리에서 다시 돌 뿐이다. 무엇을 할지는 맡긴 쪽이 정한다.
        steps_done = int(stop.get("steps") or 0)
        if english:
            return (
                f"⚠ **{lead[1]} ({steps_done} steps, about {minutes} min) — the final state did not pass the check command.** "
                + (f"Files written (not verified): {shown}.\n\n" if files else "No files were written.\n\n")
            )
        return (
            f"⚠ **{lead[0]}({steps_done}걸음 · 약 {minutes}분) — 마지막 상태는 확인 명령을 통과하지 못했습니다.** "
            + (f"만든·고친 파일(검증되지 않음): {shown}.\n\n" if files else "만든 파일은 없습니다.\n\n")
        )
    if english:
        return (
            f"⚠ **Stopped after about {minutes} min of working time — the final state did not pass verification.** "
            + (f"Files written (not verified): {shown}. " if files else "No files were written. ")
            + "Send \"continue\" to pick up from here.\n\n"
        )
    return (
        f"⚠ **정해 둔 작업 시간(약 {minutes}분)을 다 써서 멈췄습니다 — 마지막 상태는 검증을 통과하지 못했습니다.** "
        + (f"만든·고친 파일(검증되지 않음): {shown}. " if files else "만든 파일은 없습니다. ")
        + "「이어서 해줘」라고 보내면 여기서 이어갑니다.\n\n"
    )


def _code_unverified_head(stop: dict[str, Any], written: list[str], *, english: bool = False) -> str:
    """검증 없이 접은 코드 판의 답 맨 위에 붙는 줄. 모델이 쓰지 않는다 — 걸음 기록에서 본 사실만 적는다."""
    # 같은 파일을 여러 번 고치면 걸음마다 이름이 온다 — 한 번씩만 적는다(2026-10-11: 「index.html, index.html, … 외 6개」).
    files = list(dict.fromkeys(str(path) for path in written if str(path).strip()))
    shown = ", ".join(Path(path).name for path in files[:6]) + (
        (f" (+{len(files) - 6})" if english else f" 외 {len(files) - 6}개") if len(files) > 6 else ""
    )
    blocked = [str(item) for item in stop.get("blocked_writes") or [] if str(item).strip()]
    if stop.get("mutated"):
        if english:
            return ("⚠ **Finished without running a check on the final state.** "
                    + (f"Files written (not verified): {shown}. " if files else "")
                    + "Ask me to verify it, or open the files to check.\n\n")
        return ("⚠ **고친 코드를 실행해 확인하지 못한 채 끝났습니다.** "
                + (f"만든·고친 파일(검증되지 않음): {shown}. " if files else "")
                + "「검증해줘」라고 보내면 확인만 이어서 합니다.\n\n")
    if blocked:
        if english:
            return f"⚠ **No file was changed — writing was blocked** ({blocked[-1]}). Nothing was run either.\n\n"
        return f"⚠ **파일을 고치지 못했습니다 — 쓰기가 막혔습니다**({blocked[-1]}). 실행 확인도 하지 않았습니다.\n\n"
    if english:
        return ("ℹ **No file was changed and nothing was run in this turn.** The answer below is Sonjari's reply — "
                "if you wanted the code changed, say what to change.\n\n")
    return ("ℹ **이 판에서는 파일을 고치지 않았고 실행 확인도 하지 않았습니다.** 아래는 손자리의 답입니다 — "
            "코드를 고치길 바라셨다면 무엇을 고칠지 알려 주세요.\n\n")


#: 말줄임표 — 긴 제목을 표에 줄여 적을 때 쓴다.
_ELLIPSIS = re.compile(r"…|\.{3,}")


def _shortened_name_was_read(name: str, source: str) -> bool:
    """말줄임표로 **줄여 적은 이름**의 조각들이 읽은 글에 다 있는가.

    ★ 2026-10-04 레딧 기준선 판(de3228ec): 25줄을 다 맞게 낸 답의 표가 긴 제목을 「Tesla V100 32GB, RTX3090…」·
      「live-vibe: … voice Mod for Claude Code」로 줄여 적었고, 그 다섯에 「읽지 않고 적은 것이 있습니다」가 붙었다.
      줄인 이름은 글자 그대로는 원문에 없다 — 조각으로 본다. 조각이 하나라도 없거나, 조각이 너무 짧으면(세 글자 이하뿐)
      판정하지 않는다(경고가 그대로 선다 — 안전한 쪽으로 넘어진다).
    """
    if not _ELLIPSIS.search(name):
        return False
    pieces = [piece.strip(" -:·,") for piece in _ELLIPSIS.split(name)]
    pieces = [piece for piece in pieces if piece]
    if not pieces or max(len(piece) for piece in pieces) < 4:
        return False
    return all(piece in source for piece in pieces)


# 최종 답이 **도구 장부와 정반대의 실패를 주장하는가.**
#
# 2026-08-18 사람인 라이브: rank 3 상세를 열고 본문 15,696자까지 성공적으로
# 받았는데 최종 답은 "3개째 상세 정보 추출에 실패"라고 썼다. 조건에 안 맞아서
# 결과에서 제외하는 것과, 본문을 못 읽었다고 말하는 것은 전혀 다른 사실이다.
# ★ 낱말표는 두 번 샜다. 실제로 겪은 어법을 넣는다 (2026-09-07, 09-09).
#
#     잡던 것    "상세 페이지 추출에 실패"
#     샌 것 ①    "검색 결과 목록이 나타나지 않았습니다"
#     샌 것 ②    "결과 목록이 나타나지 않고 화면이 변화하지 않는 상태입니다"
#
#   낱말표가 남아 있는 이유는, 「답이 실패를 주장하는가」를 구조로 판정할 방법을
#   아직 못 찾았기 때문이다. 그래서 **문(gate)을 대신 고쳤다** — 판정에 필요한
#   것은 「본문을 실제로 받아 왔는가」 하나뿐이고, 나머지 조건이 이 검사를
#   순환으로 꺼 버리고 있었다(`_answer_trace_conflict` 주석 참고).
#
#   여기 없는 어법은 또 샌다. 새는 것을 볼 때마다 **여기 넣지 말고** 구조로
#   옮길 방법을 먼저 찾아라 — 이 목록이 길어지는 것 자체가 설계가 틀렸다는 신호다.
# ★ 2026-10-10 — **「확인하지 못했다」는 「읽지 못했다」가 아니다.** 운영 판 전체에 대 봤다(본문을 받아 온 2,039판).
#   옛 규칙은 「확인 · 조회 · 표시 · 검색 … 못 했/불가/되지 않」까지 읽기 실패로 읽었고, 주어 없이 동작 낱말만 있어도 걸었다.
#   모델의 글에서 걸린 것이 129판 — 140개쯤 글귀를 직접 보니 거의 전부 **정직한 보고**였다:
#       「가격: 확인 불가」 · 「나머지 2권은 본문을 읽지 못해 채우지 못했습니다」 · 「저장됐는지는 확인하지 못했습니다」 ·
#       「그런 코드는 확인되지 않음」(읽어 보니 없더라)
#   그런데 이 판정이 서면 모델을 한 번 더 불러 답을 **다시 쓰게** 한다(「성공을 실패라고 쓰지 못하게」). 모르는 칸을 모른다고
#   적은 답이 그 대상이었다 — 쓰기 전 숫자 문은 바로 그렇게 적으라고 시킨다(「확인 못 함」). 두 층이 반대로 말하고 있었다.
#   낱말을 읽기 쪽으로 좁히는 것만으로는 안 됐다(37판 — 여전히 「나머지는 못 읽었다」는 참말). 무엇을 못 읽었는지는 낱말로
#   알 수 없다. 그래서 **기록이 먼저 말하게** 한다 — `nothing_was_left_unread`: 요청이 정한 만큼 다 읽었고 읽기 실패 걸음도
#   없을 때만 이 글귀를 본다. 그 조건까지 걸면 129 → 8 이다(기록에는 요구의 표시가 다 남지 않아 이름표로 어림한 값).
#   ※ 남은 8판도 대부분 정직한 보고다 — 「셋을 읽으라」를 채우고 「4~15순위는 못 열었다」고 적은 판처럼, 요구는 「적어도 N」이고
#     일은 그보다 컸다. 이 판정은 낱말로는 끝까지 정확해지지 않는다. 지울지는 대표와 정한다(전수조사 §7-19).
#   이 규칙을 낳은 꼴(제대로 셋을 읽고 「세 번째 추출 실패」)은 그대로 잡는다. 09-09 의 실제 판(e7b6d39f)은 읽기 걸음 하나가
#   실패해 있어 이제 안 걸린다 — `tests/test_agent.py::test_a_failed_read_step_means_the_claim_may_be_true` 에 까닭을 적었다.
_READ_FAILURE_CLAIM = re.compile(
    # 읽는 대상 + 읽는 동작 + 안 됐다
    r"(?:상세|본문|공고|자료|페이지|결과|목록).{0,36}"
    r"(?:추출|읽기|로딩|진입).{0,24}"
    r"(?:실패|못\s*(?:했|함|읽|추출|가져)|막힘|불가|되지\s*않|안\s*됐)|"
    # 「본문을 읽지 못했다」 · 「페이지를 열 수 없었다」
    r"(?:본문|페이지|내용)[을를이가은는]?\s*(?:읽|열|불러오|가져오)[가-힣]{0,2}\s*(?:지\s*못|수\s*없|못\s*했)|"
    # "결과 목록이 나타나지 않" · "화면이 변화하지 않" — 2026-09-09 실측 어법
    r"(?:결과|목록|화면|내용).{0,20}(?:나타나지|보이지|변화하지|바뀌지)\s*않",
    re.IGNORECASE,
)
#: 읽으러 가는 손 — 이 가운데 하나라도 실패한 판은 「못 읽은 것이 있다」는 말이 참일 수 있다.
_READING_TOOLS = frozenset({
    "browser_open", "browser_open_result", "browser_extract", "browser_read", "browser_page_data", "browser_click",
    "browser_site_search", "local_read_text_file", "local_read_document", "github_read_file",
})


def nothing_was_left_unread(plan_results: Any, steps: list[dict[str, Any]]) -> bool:
    """기록으로 보아 **못 읽은 것이 없는가** — 요청이 정한 읽기 요구가 있고 전부 채워졌고, 읽기 걸음이 실패한 적도 없다.

    「읽지 못했다」는 답이 거짓인지는 이것이 참일 때만 물을 수 있다. 요구가 없으면(몇 개를 읽으라는 말이 없던 판) 모른다 —
    모르면 거짓이라 하지 않는다. 읽기 요구는 두 꼴로 뽑힌다: `observe`(근거가 되는 대상 실제로 읽기)와 직접 열어 읽으라는 `count`.
    """
    asked = [
        bool(met)
        for requirement, met, _ in plan_results or ()
        if getattr(requirement, "kind", "") == "observe"
        or (getattr(requirement, "kind", "") == "count" and getattr(requirement, "grounding_required", False))
    ]
    if not asked or not all(asked):
        return False
    return not any(not step.get("ok") and str(step.get("tool") or "") in _READING_TOOLS for step in steps or ())


def table_cells(line: str) -> list[str]:
    """마크다운 표 한 줄의 칸들. **이스케이프한 세로줄(`\\|`)은 칸을 가르지 않는다.**

    2026-10-09 소스 조사 판: 답의 표에 코드 `a \\|\\| b` 가 있었는데 `split("|")` 이 그 세로줄에서 칸을 잘라
    `stopReason === "error" \\` 라는 토막을 「읽지 않고 적은 이름」으로 알렸다. 칸을 자르는 자리가 여덟 군데였고 전부 같은 식이었다.
    """
    # 바깥 세로줄을 떼는 법은 예전 그대로다(`strip("|")`) — 이스케이프가 없는 줄은 한 글자도 다르게 잘리지 않는다.
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [cell.replace("\\|", "|") for cell in cells]
#: 답이 스스로 **하지 못했다**고 말하는 꼴 — 「찾을 수 없습니다」·「열지 못했습니다」·「확인하지 못했습니다」.
#: 「찾을 수 없으면 …」 같은 조건은 안 걸린다(과거·현재 단정형만).
_ADMITS_NOT_DONE = re.compile(
    r"(?:찾|확인|입력|열|읽|누르|클릭|채우|넣|접속|진행)[가-힣]{0,3}\s*"
    r"(?:수\s*(?:가\s*)?없었|수\s*없습니다|지\s*못했|지\s*못\s*했|못\s*했|못했)"
)
#: 영어로 **하지 못했다**고 말하는 꼴 (2026-10-03 Online-Mind2Web B 판). 「I was unable to complete the task」·「I have to stop
#: here」·「I've hit a wall」로 답한 세 판(AdoptAPet·NVIDIA·Apple)이 대조표 칸이 우연히 다 차서 complete 로 나갔다 — 한국어 그물만 있었다.
#: 1인칭 단정만 본다(「If you can't find …」 같은 조건·안내는 안 걸린다).
_ADMITS_NOT_DONE_EN = re.compile(
    # ★ 동사 목록이 아니라 모양으로(B 판 2차 NVIDIA 「comboboxes I couldn't expand」가 목록 밖이라 complete).
    #   운영 영어 답 52개 역검증: 걸린 13개 전부 실제로 못 한 판(하나는 「폭 필터는 못 걸었다」고 밝힌 판 — 일부가 정직).
    r"(?i)\b(?:i\s+(?:was|am|['’]m)\s+(?:unable|not\s+able)\s+to\s+[a-z]+"
    r"|i\s+(?:could\s*not|couldn['’]t|wasn['’]t\s+able\s+to)\s+[a-z]+"
    r"|i\s+have\s+to\s+stop\s+here|i['’]ve\s+hit\s+a\s+wall|i\s+(?:was|am)\s+blocked)\b"
)
#: 우리가 붙이는 두 경고의 머리 — 「N개 중 M개만 실제로 열어 읽었습니다」 · 「성공했다고 확인하지 못했습니다」.
#: 이 둘은 답의 자백이 아니라 **우리가 센 것**이라 `harness_shortfall` 로 따로 적는다(문구는 `_goal_shortfall_check` ·
#: `_commit_reality_check` 에 있다 — 거기를 고치면 여기도 같이 고친다. 시험이 둘을 묶어 둔다).
_READ_SHORT_MARK = re.compile(r"개만 실제로 열어 읽었습니다|were actually opened and read")
_COMMIT_UNCONFIRMED_MARK = re.compile(r"성공했다고 확인하지 못했습니다|Success could not be confirmed")
_SHORTFALL_WORDS = re.compile(
    r"(?:개만|건만|곳만|부족|미달|미확인|못\s*했|못\s*읽|실패|막힘|현재까지|"
    r"그중|이 중|간주하지\s*않)"
)
# 세는 단위는 **개만이 아니다.** 2026-08-18 라이브에서 6개를 시켰는데 1건만 준 판이
# `complete` 로 기록됐다. 답에는 "…검증한 것은 위 1건입니다" 라고 분명히 적혀 있었는데,
# 이 정규식이 `개` 만 받아서 그 자백을 통째로 놓쳤다. 같은 날 다른 판이 잡힌 것은
# 우연히 "3개만 … 읽었습니다" 라고 썼기 때문이지 탐지가 좋아서가 아니었다.
#
# 그래서 단위를 넓히고(건·곳·가지·종·명), 서술어까지의 거리도 한국어 문장에 맞게
# 늘린다. 조사·수식어가 붙으면 16자는 금방 넘는다.
_COUNT_UNIT = r"(?:개|건|곳|가지|종|명)"
_COUNT_VERB = r"(?:확인|정리|찾|읽|검증|뽑|추렸|골랐|나왔)"
# 한국어는 **서술어가 숫자보다 앞에 오는 문장이 흔하다** — "검증한 것은 위 1건입니다".
# 숫자→서술어 한 방향만 보면 그런 자백을 통째로 놓친다(A판이 그렇게 샜다).
# 그래서 양방향을 다 본다. 여기서 나온 수 중 **가장 작은 값**을 실제 성과로 보므로,
# 목표치("6개를 채우기 위해")가 같이 잡혀도 판정을 망치지 않는다.
_REPORTED_COUNT_FWD = re.compile(rf"(\d{{1,2}})\s*{_COUNT_UNIT}.{{0,30}}?{_COUNT_VERB}")
_REPORTED_COUNT_REV = re.compile(rf"{_COUNT_VERB}.{{0,30}}?(\d{{1,2}})\s*{_COUNT_UNIT}")

