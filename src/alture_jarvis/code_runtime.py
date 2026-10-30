from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any


_DEEP_HINTS = re.compile(
    # ``docs/ARCHITECTURE.md를 읽어`` 같은 파일명은 난이도 신호가 아니다.
    r"아키텍처|architecture(?!\.[a-z0-9])|대규모|large[- ]scale|리팩터|refactor|마이그레이션|migration|"
    r"다중\s*파일|multi[- ]file|race condition|deadlock|성능\s*최적화",
    re.IGNORECASE,
)
_MUTATION_HINTS = re.compile(
    r"고쳐|수정|패치|구현|추가|삭제|바꿔|fix|patch|implement|add|remove|change|refactor",
    re.IGNORECASE,
)


# Code 모드는 저장소 작업에 집중하되, 질문이 최신 기술·커뮤니티 근거를 요구하면
# 읽기 전용 조사 도구를 그 판에만 연다. 모든 스키마를 항상 주는 방식은 Qwen의
# 도구 선택 정확도를 떨어뜨렸고, 반대로 sandbox만 주면 웹 조사를 임의 Python
# 네트워크 코드로 우회해서 L2 승인 카드를 만들었다(2026-08-26 라이브).
CODE_CORE_TOOL_NAMES = frozenset(
    {
        "local_list_directory",
        "local_index_codebase",
        # ★ 「이 함수 누가 부르나」 (2026-09-21). 이게 없어서 모델은 이름을 grep 하고
        #   파일을 통째로 읽어 확인했다 — 전사를 먹는 자리가 거기였다.
        "local_find_symbol",
        "local_search_files",
        # ★ 찾기가 약하면 읽기로 때운다 (2026-09-01).
        #
        #   `local_search_files` 는 파일 **이름**만 보고, 색인은 심볼 단위다.
        #   「이 값이 어디서 정해지나」에 답할 도구가 없어서, 자비스는 파일을 열어
        #   눈으로 훑었다 — 벤치 실패 판의 공통 모양이 「읽기 8~11회 · 쓰기 0회」다.
        "local_grep",
        "local_glob",
        "local_write_document",
        # ★ 디자인된 장표 (2026-10-25). 바깥 클로드가 맡긴 판은 이 목록으로 돈다 — 여기 없어서 「손자리 소개 PPT」 판이
        #   새 손을 못 보고 local_write_document 로 흰 바탕 PPT 를 만들었다(컴퓨터 창 연출도 안 나옴).
        "local_make_slide",
        "local_read_text_file",
        # ★ 저장소에는 글자 파일만 있는 게 아니다 (2026-09-20). 설계문서가 PDF·docx 면
        #   어려운 과제의 절반을 못 보고 시작한다.
        "local_read_document",
        "local_write_file",
        "local_apply_edit",
        "local_delete_file",
        "local_run_project_command",
        # ★ 막혔을 때 **사람에게 묻는 문** (2026-09-20). 이게 여기 없으면 코워크는 막힌 자리에서
        #   같은 경로를 되풀이하다 끝난다 — 오늘 코워크 판들이 정확히 그렇게 죽었다.
        #   L2 라서 사장님 승인 없이는 아무것도 안 열린다.
        "local_request_path_access",
        # ★ 만든 페이지를 스스로 보는 문 (2026-09-20). 이게 없어서 프론트 판이
        #   파일을 만들고도 「검증 못 함」으로 실패했다.
        "local_preview_page",
        # ★ 진짜 셸 (2026-09-20). 커서·윈드서프·클로드 코드 셋 다 준다 —
        #   허용 목록 8개로는 조사가 막힌다. 보는 명령은 승인 없이, 바꾸는 것은 카드.
        "local_run_shell",
        # ★ 스킬은 코드 모드에도 있어야 한다 (2026-08-29).
        #
        # 스킬 66종이 있고 로더(`skills.py`)도 도는데, 이 둘이 프로필에 없어서
        # **코드 모드만 못 불렀다.** 코워크는 부르고 있었다 — 같은 저장소 안에서
        # 한쪽 문만 잠겨 있던 셈이다.
        #
        # 도구를 과하게 주면 Qwen 의 선택 정확도가 떨어진다는 위 실측 때문에
        # 프로필을 좁게 유지해 왔지만, 이 둘은 **읽기 전용이고 두 개뿐이며**,
        # 코딩 규약·절차를 담는 그릇이라 코드 판에서 가장 쓸모가 크다.
        "skill_list",
        "skill_read",
        # ★ 사람에게 선택지로 묻는 문 (2026-09-30). 없으면 애매한 요청을 답 끝의 글로 묻고 판을 끝냈다 —
        #   사람이 대답하면 새 판이 처음부터 다시 돈다. 카드가 떠 있는 동안 판은 그 자리에서 기다린다.
        "ask_user",
    }
)
CODE_RESEARCH_TOOL_NAMES = frozenset(
    {
        "naver_news",
        "naver_web",
        "github_search",
        "reddit_hot",
        "hackernews_top",
        "browser_search",
        "browser_open",
        "browser_open_result",
        "browser_extract",
        "browser_read",
        "browser_links",
        "browser_site_search",
        "browser_load_more",
        "browser_close",
    }
)
CODE_SANDBOX_TOOL_NAMES = frozenset({"sandbox_run", "sandbox_fetch"})
CODE_PREVIEW_TOOL_NAMES = frozenset({
    "browser_open", "browser_snapshot", "browser_click", "browser_screenshot",
    "browser_wait", "browser_read",
    # ★ 좌표로 누르고 치는 것도 같은 계열이다 (2026-09-21 AURORA 3판).
    #   `browser_click_at` 이 `code_tool_not_in_active_profile` 로 튕겼다 — 섀도 DOM·
    #   캔버스 화면에서는 이것 말고 누를 방법이 없다. 손이 반만 열려 있던 셈이다.
    "browser_click_at", "browser_type_at", "browser_scroll",
    # ★ 칸을 ref 로 채우는 손도 같은 계열이다 (2026-09-29 밤 한방 도전 W1).
    #   모델이 먼저 `browser_fill` 을 불렀는데 `code_tool_not_in_active_profile` 로 튕겼고, 남은 손(좌표 입력)만
    #   14번 되풀이했다 — 762초 판의 약 8분. 만든 폼을 확인하려면 채우고·고르고·엔터 치는 손이 다 있어야 한다.
    "browser_fill", "browser_select_option", "browser_press",
    # 확인창에 답을 **정해 두는** 손 (2026-10-04 전수조사 11번). 이 PC 안 페이지의 확인창은 도구가 확인으로 답하는데,
    #   취소 쪽을 시험하려면(「취소를 누르면 안 지워지는가」) 이 손이 있어야 한다.
    "browser_handle_dialog",
})

# 프론트 작업에는 만든 것을 실제로 누를 손이 필요하다. 일반 저장소 작업에는
# 브라우저 스키마를 싣지 않아 Code 도구 선택 비용을 유지한다.
#: 유니티 일(2026-09-27, 게임 팩). 이 낱말이 사용자 말에 있으면 유니티 도구(프로젝트 훑기·레시피 실행)를 연다.
#: 「씬」은 홀로 흔한 말이 아니라서 넣었고, 「에셋」·「텍스처」는 유니티 밖(웹)에서도 쓰지만 코드 판에서는 거의 게임 자원이다.
_UNITY_HINTS = re.compile(r"유니티|unity|프리팹|prefab|\.unity\b|텍스처|texture|에셋\s*(?:점검|설정|정리)|빠진\s*참조|missing\s*(?:script|reference)", re.IGNORECASE)

#: 화면 손 묶음이 열렸을 때 모델에게 주는 안내. 판 시작에 열릴 때도, 판 도중 열릴 때도 **같은 글**이다.
PREVIEW_GUIDANCE = (
    "프론트 작업은 코드를 고친 뒤 local_preview_page로 만든 페이지의 로컬 URL을 받고, "
    "browser_open → browser_snapshot → browser_click → browser_read 로 핵심 흐름을 실제 확인한다"
    "(스크린샷은 파일만 남기고 너에게 보이지 않는다). "
    "로컬 미리보기 클릭은 expect를 지어내지 말고 expect 없이 누른 뒤 snapshot/read로 변화를 확인한다. "
    "같은 화면을 확인한 뒤에는 site_search/open_result를 쓰지 않는다. 화면 확인과 "
    "local_run_project_command 검사는 별개다. 확인하지 못했으면 했다고 말하지 않는다."
)

_PREVIEW_HINTS = re.compile(
    r"프론트(?:엔드)?|frontend|front-end|웹\s*앱|web\s*app|"
    r"(?:제품|앱|페이지|사이트|화면|버튼|레이아웃|UI|UX)\s*(?:을|를|이|가|에서|의)?\s*"
    r"(?:만들|고치|수정|구현|확인|눌러|테스트|검증|디자인)|"
    r"(?:만들|고치|수정|구현|확인|눌러|테스트|검증|디자인)\s*"
    r"(?:제품|앱|페이지|사이트|화면|버튼|레이아웃|UI|UX)",
    re.IGNORECASE,
)

_RESEARCH_HINTS = re.compile(
    # ★ `찾아줘` 와 맨 `검색` 은 일부러 안 받는다(2026-08-28 역검증). "이 에러 원인
    # 찾아줘", "이 검색 함수 고쳐줘" 같은 **저장소 안 일**까지 웹 도구 14개를 열어
    # 버린다. 도구를 과하게 주면 Qwen 의 도구 선택 정확도가 떨어진다는 것이 이
    # 파일 위쪽 주석의 실측이다.
    r"조사|찾아\s*(?:봐|보)|검색해|검색\s*좀|웹\s*검색|"
    r"최신|트렌드|동향|커뮤니티|"
    # ★ 도구 **이름을 직접 부르면 연다** (2026-08-28 라이브).
    #
    # 사용자가 "브라우저나 이런거 이용해서 … 깃허브나 이런데에서 … 브라우저
    # 조사라던지" 라고 **다섯 번** 말했는데 프로필이 `core` 로 떨어져 web 도구가
    # 하나도 안 열렸다. `깃허브에서` 는 조사 '에서' 를 요구해 "깃허브나" 를 놓쳤고,
    # `조사해` 는 "조사라던지" 를 놓쳤고, `브라우저` 는 낱말표에 아예 없었다.
    #
    # 손자리는 지어내지 않고 "제가 쓸 수 있는 도구는 local_* 8개뿐" 이라고 정직하게
    # 답했다 — 즉 **모델이 아니라 우리 낱말표가 손을 묶은 것**이다. 「도구를 만들어도
    # 갈래가 없으면 지어낸다」와 같은 자리다.
    #
    # 낱말을 더 붙이는 대신 원칙으로 둔다: 표면을 이름으로 지목하면 그 표면을 연다.
    # 이것은 의도 추측이 아니라 **명시적 요청**이라 넓혀도 안전하다.
    r"브라우저|browser|깃허브|github|레딧|구글|네이버|"
    r"웹에서|웹\s*(?:검색|페이지|사이트)|인터넷|온라인|"
    r"공식\s*문서|깃허브에서|github에서|레딧|reddit|hacker\s*news|해커\s*뉴스|"
    r"웹에서|인터넷에서|논문|벤치마크|benchmark|release\s*note|릴리스\s*노트|"
    r"출처(?:를|와|로)|근거(?:를|와|로)|"
    # ── 아래는 2026-08-28 에 **실측으로 뚫린 구멍**을 메운 것이다.
    # "이 API 문서 좀 보고 고쳐줘", "requests 쓰는 법 알려줘" 가 전부 core 로
    # 떨어져 웹 도구가 안 열렸다. 도구가 없으면 모델은 거절하지 않고 **지어낸다**
    # — 「라우팅 낱말표 → 78% 창작」과 같은 자리다.
    r"문서\s*(?:좀|를|는|에|가)?\s*(?:보|봐|읽|참고|확인|찾)|"
    r"api\s*문서|레퍼런스|reference|스펙\s*(?:을|를|이|보|확인)|"
    r"사용법|쓰는\s*법|쓰는\s*방법|어떻게\s*(?:쓰|사용|호출)|how\s*to\s*use|"
    r"예제|예시\s*코드|샘플\s*코드|sample\s*code|"
    r"업그레이드|마이그레이션\s*가이드|deprecat",
    re.IGNORECASE,
)
_EXTERNAL_RESEARCH_HINTS = re.compile(
    r"최신|트렌드|동향|커뮤니티|조사|웹\s*검색|인터넷|온라인|"
    r"깃허브|github|레딧|reddit|네이버|구글|공식\s*문서|출처|논문|벤치마크",
    re.IGNORECASE,
)
_SANDBOX_HINTS = re.compile(
    r"샌드박스|sandbox|(?:python|파이썬|코드)\s*(?:으로|로)\s*(?:직접\s*)?계산|"
    r"직접\s*계산|시뮬레이션\s*(?:해|돌려)|scratch\s*code|스크래치\s*코드|"
    # 산출물 낱말은 늘리고, 동사도 「만들/생성」 말고 실제로 쓰는 말까지 받는다.
    r"(?:csv|xlsx|엑셀|그래프|차트|표|테이블|json)\s*(?:으로|로|를|을)?\s*"
    r"(?:만들|생성|그려|뽑아|정리|저장|내보)|"
    # "이 함수 성능 측정해서 표로 만들어줘" 가 core 로 떨어졌다(2026-08-28 실측).
    r"표로\s*(?:만들|정리|뽑)|측정해|재\s*봐|계산해\s*(?:줘|봐)|"
    r"집계|통계\s*(?:를|내|낸)|시각화|플롯|plot",
    re.IGNORECASE,
)



#: 모델에게 **있다고 알려 주는** 라이브러리 목록 (2026-09-20).
#:
#: ★ 깔아 두기만 하면 안 쓴다. 이 저장소가 「스킬 85개가 일에 닿지 않았다(11/11,043회)」로
#:   배운 것이 그것이다. 도구 설명은 `python -m` 명령만 담으므로, **import 해서 쓰는**
#:   연장은 여기 적어 프로필 안내에 같이 싣는다.
CODE_LIBRARY_NOTE = (
    "이 파이썬에는 다음이 깔려 있다. `python -c` 나 작업 폴더에 쓴 스크립트에서 import 해서 써라:\n"
    "  jedi         심볼 정의·참조 찾기 — 「이 함수 누가 부르나」를 grep 보다 정확히\n"
    "  libcst       주석·포맷을 보존하며 코드를 바꾼다 (대량 리팩터)\n"
    "  pyright      타입 검사 — ruff 가 통과시킨 `fee(\"10\", 3)` 을 잡는다. `python -m pyright <경로>`\n"
    "  hypothesis   속성 기반 시험 — 사람이 안 떠올린 입력으로 버그를 찾는다\n"
    "  pandas·numpy 표·수치 분석 (CSV·엑셀·JSON)\n"
    "  bs4·lxml     만든 HTML 을 파싱해 태그 구조·접근성 속성을 검증한다\n"
    "  yaml·tomlkit 설정 파일 읽고 쓰기 (tomlkit 은 주석을 보존한다)\n"
    "  freezegun    시간을 고정한 시험 · respx  httpx 모킹\n"
    "  line_profiler 어느 줄이 느린가\n"
    "추측하지 말고 **직접 돌려서** 확인해라."
)

@dataclass(frozen=True)
class CodeToolProfile:
    name: str
    tool_names: frozenset[str]
    guidance: str


#: 프로필 밖 도구를 불렀을 때 **대신 가라고 댈 문**. 왼쪽이 부른 것, 오른쪽이 갈 곳.
#
# ★ 2026-09-21 실전: 모델이 파일 둘을 만들고 마지막에 검증 스크립트를 돌리려 `sandbox_run`
#   을 불렀다가 `code_tool_not_in_active_profile` 로 죽었다. 그 판의 프로필에는
#   `local_run_shell` 과 `local_run_project_command` 가 **이미 있었다.** 거절문이
#   「현재 요청에 허용된 도구 중에서 다시 선택하라」라고만 해서 모델이 못 찾았고,
#   거의 다 한 판이 마지막 한 걸음에서 무너졌다(`coding_verification_missing`).
#
#   막기만 하면 모델은 같은 벽에 계속 부딪친다. 거절은 **갈 곳을 같이 댄다.**
_CODE_TOOL_DETOURS: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"sandbox_run", "sandbox_fetch"}),
        "이 저장소에서 명령을 돌리는 것은 `local_run_project_command`(시험·린트처럼 정해진 것) "
        "와 `local_run_shell`(둘러보기·한 줄 실행)이다. 격리 상자는 이 판에 열려 있지 않다.",
    ),
    (
        frozenset({
            "browser_search", "browser_open", "browser_extract", "browser_site_search",
            "browser_open_result", "naver_web", "naver_news", "github_search",
        }),
        "이 판은 조사 갈래가 아니다 — 저장소 안에서 답을 찾으려면 `local_grep` 과 "
        "`local_search_files` 를 써라. 밖을 조사해야 하면 사람에게 무엇을 조사할지 말하고 "
        "다음 턴에 조사로 시켜 달라고 해라.",
    ),
)

#: 어느 갈래에도 안 걸릴 때 대는 기본 문 — **실제로 프로필에 있는 것만** 고른다.
_CODE_FALLBACK_DOORS = (
    "local_grep", "local_search_files", "local_read_text_file",
    "local_run_project_command", "local_run_shell",
)


def refusal_for_tool_not_this_turn(name: str, accepted: frozenset[str], *, profile: str = "") -> dict[str, Any]:
    """이 판의 손이지만 **이 걸음에는** 안 받는 손을 불렀을 때 돌려줄 관측 (2026-10-09).

    관문이 손을 좁힌 걸음(보기만 했다 → 쓰는 손만 · 검증을 안 돌렸다 → 검증하는 손만)에도 목록은 그대로 보낸다
    (`agent.offered_code_tools`). 그래서 모델은 그 손을 **보고** 부른다 — 「열려 있지 않다」고 하면 보이는 것과 말이 어긋난다.
    지금 받는 손과, 그중 하나를 부르면 풀린다는 것을 말한다(두 관문 모두 손을 한 번 뻗으면 — 실패해도 — 풀린다).
    """
    doors = ", ".join(f"`{door}`" for door in sorted(accepted))
    return {
        "ok": False,
        "tool": name,
        "error": "code_tool_not_in_active_profile",
        "profile": profile,
        "instruction": (
            f"`{name}` 은(는) 지금 차례가 아니다. 이 걸음에 받는 것: {doors}. "
            "그중 하나를 부르면(실패해도) 다음 걸음부터 다른 손도 다시 받는다 — 판은 계속 간다."
        ),
    }


def refusal_for_tool_outside_profile(name: str, profile: CodeToolProfile) -> dict[str, Any]:
    """프로필 밖 도구를 불렀을 때 돌려줄 관측. **왜 · 어디로 · 계속 간다** 셋을 담는다.

    ★ 여기서 대는 이름은 **반드시 지금 프로필에 있는 것**이어야 한다. 없는 이름을 대면
      모델은 그 다음 벽에 부딪치고, 우리는 벽을 하나 더 세운 셈이 된다.
    """
    detour = ""
    for callers, advice in _CODE_TOOL_DETOURS:
        if name in callers:
            detour = advice
            break
    open_doors = [door for door in _CODE_FALLBACK_DOORS if door in profile.tool_names]
    # 안내에 댄 도구가 실제로 안 열려 있으면 그 문장을 버린다 — 거짓 안내가 더 나쁘다.
    if detour and not all(
        word.strip("`,.") in profile.tool_names
        for word in detour.split()
        if word.strip("`,.").startswith(("local_", "browser_", "skill_"))
    ):
        detour = ""
    if not detour and open_doors:
        detour = "지금 쓸 수 있는 것: " + ", ".join(f"`{door}`" for door in open_doors)
    return {
        "ok": False,
        "tool": name,
        "error": "code_tool_not_in_active_profile",
        "profile": profile.name,
        "instruction": (
            f"`{name}` 은(는) 이 판에 열려 있지 않다. {detour} "
            "이름을 지어내지 말고 위의 것으로 이어서 해라 — 판은 계속 간다."
        ).strip(),
    }


#: 프로필을 정할 때 같이 볼 **직전 사용자 발화** 수와 글자 상한.
#: 모델이 한 말은 안 본다 — 자기 말로 자기 손을 열 수 있으면 안 된다.
_PROFILE_CONTEXT_TURNS = 3
_PROFILE_CONTEXT_CHARS = 1200


def recent_user_context(
    history: list[dict[str, Any]] | None,
    turns: int = _PROFILE_CONTEXT_TURNS,
) -> str:
    """직전 사용자 발화 몇 개를 이어 붙인다. 프로필 판정에만 쓴다."""
    if not history:
        return ""
    said: list[str] = []
    for item in reversed(history):
        if not isinstance(item, dict) or str(item.get("role")) != "user":
            continue
        text = str(item.get("content") or "").strip()
        if text:
            said.append(text)
        if len(said) >= turns:
            break
    return " ".join(reversed(said))[-_PROFILE_CONTEXT_CHARS:]


def select_code_tool_profile(
    prompt: str,
    *,
    force_sandbox: bool = False,
    context: str = "",
    available: "set[str] | frozenset[str] | None" = None,
    open_all: bool = False,
) -> CodeToolProfile:
    """현재 요청에 필요한 최소 Code 도구 묶음을 결정론으로 고른다.

    ## 왜 직전 대화까지 보나 (2026-08-29 라이브)

    예전에는 **그 판의 프롬프트 하나만** 봤다. 그래서 이런 일이 났다:

        세 턴 전  "브라우저로 깃허브 조사해줘"  -> core+research
        이번 턴   "1부터 한번 해보자"            -> core  (손이 사라짐)

    대화는 이어지는데 손은 매 턴 새로 정해졌다. 자비스는 지어내지 않고
    "내가 지금 가진 것은 local_* 과 skill_* 뿐" 이라고 정직하게 말했지만,
    시킨 일을 못 한 것은 그대로다. 낱말표 구멍이 아니라 **범위** 문제였다.

    ★ 사용자 발화만 본다. 모델이 제 말로 제 손을 여는 길은 열지 않는다.
    """
    haystack = f"{prompt or ''}\n{context or ''}"
    research = bool(_RESEARCH_HINTS.search(haystack))
    sandbox = force_sandbox or bool(_SANDBOX_HINTS.search(haystack))
    # ★ **이름을 대면 연다** (2026-09-21 실전 재측정에서 이것 때문에 판이 죽었다).
    #
    #   AURORA 판 프롬프트에 「browser_open, browser_snapshot, browser_click 으로
    #   화면과 상호작용을 직접 확인해」라고 적혀 있었는데, 위 낱말표는 **의도 낱말**
    #   (프론트·웹앱·화면을 만들…)만 봐서 안 걸렸다. 걸음 11·16 이
    #   `code_tool_not_in_active_profile` 로 튕겼고 판이 통째로 실패했다.
    #
    #   `_RESEARCH_HINTS` 주석에 이미 답이 적혀 있다 — 「낱말을 더 붙이는 대신
    #   원칙으로 둔다: 표면을 이름으로 지목하면 그 표면을 연다. 이것은 의도 추측이
    #   아니라 **명시적 요청**이라 넓혀도 안전하다.」 조사 쪽에만 있던 그 원칙을
    #   프리뷰 쪽에도 둔다.
    #
    #   파일 이름 속 언급(`docs/browser_click.md`)은 시킨 것이 아니므로 뺀다.
    named_preview = any(
        re.search(rf"(?<![\w./\\-]){re.escape(name)}(?![\w.]*\.(?:md|py|ts|tsx|json|txt))", haystack)
        for name in CODE_PREVIEW_TOOL_NAMES
    )
    preview = bool(_PREVIEW_HINTS.search(haystack)) or named_preview
    # 로컬 프론트 검증에서 ``browser_open``을 도구 이름으로 지목한 것은 외부 조사가
    # 아니다. research까지 열면 모델이 로컬 페이지에 site_search/open_result를 부른다.
    if preview and not _EXTERNAL_RESEARCH_HINTS.search(haystack):
        research = False
    # ★ **권한 무시면 손을 다 연다** (2026-09-28 사장님 결정, 전략안 §53).
    #
    #   이 프로필은 안전장치가 아니라 **작은 모델의 도구 목록을 줄이는 장치**다. 그런데 낱말표로 고르다 보니
    #   샐 때마다 판이 죽었다(08-29·09-21 두 번·09-23 도구 5종). 사람이 「묻지 말고 해라」를 고른 판에서
    #   도구 이름으로 막는 것은 권한 모드와 따로 노는 벽이다 — 사람은 「다 허락했는데 왜 막지」가 되고,
    #   모델은 그 거절을 정책으로 읽는다. 되돌릴 수 없는 것(결제·발송·발행)은 이 프로필이 아니라
    #   게이트웨이(`permissions.NEVER_BYPASS`)가 권한 무시에서도 계속 묻는다.
    if open_all:
        research = sandbox = preview = True
    names = set(CODE_CORE_TOOL_NAMES)
    profile_parts = ["core"]
    guidance = [
        "저장소 읽기·수정·테스트는 local_* 도구를 사용한다.",
        "프로필에 없는 도구를 호출하거나 이름을 지어내지 않는다.",
        CODE_LIBRARY_NOTE,
    ]
    if research:
        names.update(CODE_RESEARCH_TOOL_NAMES)
        profile_parts.append("research")
        guidance.extend(
            [
                "최신 정보와 외부 기술 근거는 읽기 전용 웹·GitHub·Reddit 도구로 조사한다.",
                "웹 검색·다운로드·스크래핑을 sandbox_run의 네트워크 코드로 대신하지 않는다.",
            ]
        )
    if sandbox:
        names.update(CODE_SANDBOX_TOOL_NAMES)
        profile_parts.append("sandbox")
        guidance.append(
            "sandbox_run은 명시된 계산·격리 실험에만 쓰고, 저장소 검증은 local_run_project_command로 한다."
        )
    from .unity_editor import EDITOR_TOOL_NAMES
    from .unity_tools import UNITY_TOOL_NAMES

    # 게임 팩이 꺼져 있으면(카탈로그에 유니티 도구가 없으면) 유니티 갈래를 열지 않는다 — 없는 도구를 안내하면 벽이 하나 는다.
    # 권한 무시여도 **팩이 켜진 PC 에서만** 연다 — 없는 도구를 목록에 올리면 그것도 벽이다.
    if (open_all or _UNITY_HINTS.search(haystack)) and (available is None or UNITY_TOOL_NAMES <= set(available)):

        names.update(UNITY_TOOL_NAMES)
        names.update(EDITOR_TOOL_NAMES if available is None else EDITOR_TOOL_NAMES & set(available))
        profile_parts.append("unity")
        guidance.append(
            "유니티 일은 unity_project_info 로 먼저 훑고, 점검·작업은 unity_list_recipes 로 레시피를 찾아 unity_run_recipe 로 돌린다. "
            "텍스처·프리팹·씬을 local_glob 으로 직접 뒤지거나 이미지 헤더를 읽는 스크립트를 짜지 않는다 — 크기·압축·참조는 "
            "유니티 가져오기 설정에 있어서 파일로는 틀린 답이 나온다(레시피가 유니티 안에서 읽는다). "
            "레시피 결과(result)의 숫자·경로만 사실로 쓴다. 에디터가 열려 있다고 나오면 사람에게 닫아 달라고 하고, "
            "에디터 버전이 없으면 다른 버전으로 열지 말고 설치를 부탁한다. "
            "에디터가 열려 있고 손자리와 이어져 있으면(unity_editor_status) 닫아 달라고 하지 말고 unity_editor_look 으로 "
            "열린 에디터 안(계층·콘솔·선택·컴포넌트)을 읽는다. 씬을 바꾸는 일은 unity_editor_change 로만 하고(승인 카드), "
            "저장은 따로 op=save_scene 이다."
        )
    if preview:
        names.update(CODE_PREVIEW_TOOL_NAMES)
        profile_parts.append("preview")
        guidance.append(PREVIEW_GUIDANCE)
    return CodeToolProfile(
        name="+".join(profile_parts),
        tool_names=frozenset(names),
        guidance=" ".join(guidance),
    )


def with_page_preview(profile: CodeToolProfile) -> CodeToolProfile:
    """화면 손 묶음을 더한 프로필. 이미 있으면 그대로 돌려준다.

    ★ 2026-10-04 도구 전수조사 2번. 화면 손은 요청에 「프론트·페이지를 만들…」 같은 **낱말**이 있어야 열렸다.
      「index.html 로 계산기 만들어 줘」·「build a landing page」는 낱말표에 안 걸려, 페이지를 만들고 띄운 뒤
      (`local_preview_page` 는 늘 있다) **열 손이 없었다** — `code_tool_not_in_active_profile` 로 튕기고 임시
      스크립트로 돌아가다 `coding_verification_missing` 으로 끝났다(aurora-replay 36baec94: 거절 4번).
      낱말을 더 붙이지 않는다. **페이지를 실제로 만든 판**이면 연다 — 추측이 아니라 걸음 기록이다.
      판 도중 목록이 한 번 바뀌어 앞머리 캐시가 한 번 깨진다. 판이 멈추는 것보다 싸다.
    """
    if "preview" in profile.name.split("+"):
        return profile
    return CodeToolProfile(
        name=f"{profile.name}+preview",
        tool_names=frozenset(profile.tool_names | CODE_PREVIEW_TOOL_NAMES),
        guidance=f"{profile.guidance} {PREVIEW_GUIDANCE}",
    )


#: 띄워서 열어 보는 것이 곧 확인인 파일. `.js`·`.css` 는 뺀다 — 페이지가 아닌 저장소(Node 서버)에서도 쓰인다.
_PAGE_FILE_SUFFIXES = (".html", ".htm")


def launched_a_page(steps: list[dict[str, Any]]) -> bool:
    """이 판이 **페이지를 만들었거나 띄웠는가** — 그러면 화면 손이 필요하다(`with_page_preview`).

    성공한 `local_preview_page`, 또는 `.html` 파일을 성공적으로 쓴 걸음. 말(「페이지를 만들겠다」)은 안 본다.
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
        if target.endswith(_PAGE_FILE_SUFFIXES):
            return True
    return False


def touched_local_page(steps: list[dict[str, Any]]) -> bool:
    """이 PC 안 페이지(file·localhost)를 **실제로 만진**(누르기·채우기) 걸음이 있는가.

    `.ts`·`.py`(플라스크)로 화면을 만들고 자기 서버를 연 판은 페이지 파일을 쓴 적이 없다. 그래도 그 화면을 만졌으면
    읽는 손이 남아야 한다 — 되받기가 「지금 browser_read 를 한 번 불러라」고 하는데 손이 없었다(전수조사 2-C).
    열기·읽기만 한 판은 아니다 — 09-21 「또 보기만」 다섯 판이 되살아나지 않게.
    """
    current = ""
    for step in steps:
        tool = str(step.get("tool") or "")
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        url = str(evidence.get("url") or (arguments.get("url") if tool == "browser_open" else "") or "")
        if url:
            current = url
        if step.get("ok") and tool in _BROWSER_ACTIONS and _is_local_page(current):
            return True
    return False


def route_code_profile(
    prompt: str,
    *,
    steps: list[dict[str, Any]] | None = None,
    configured: str = "balanced",
) -> str:
    """작업 증거로 fast/medium/deep를 결정한다.

    deep는 어려워 보인다는 감상이 아니라 아키텍처급 요청 또는 같은 검증 실패가
    반복됐을 때만 연다. 일반 변경은 medium, 설명·색인은 fast다.
    """
    history = steps or []
    failed = [
        step for step in history
        if step.get("tool") == "local_run_project_command"
        and not bool((step.get("evidence") or {}).get("verified"))
    ]
    fingerprints = [
        str((step.get("evidence") or {}).get("failure_fingerprint") or "")
        for step in failed
    ]
    repeated_failure = any(value and fingerprints.count(value) >= 2 for value in fingerprints)
    if repeated_failure or _DEEP_HINTS.search(prompt):
        return "deep"
    if _MUTATION_HINTS.search(prompt) or any(
        step.get("code_phase") in {"patch", "verify", "repair"} for step in history
    ):
        return "medium"
    requested = str(configured or "balanced").strip().lower()
    return "medium" if requested in {"balanced", "medium", "deep"} else "fast"


_CODE_MUTATION_TOOLS = frozenset({"local_write_file", "local_apply_edit", "local_delete_file"})


#: 화면을 **실제로 만진** 걸음 — 누르기·채우기·고르기·키 입력.
_BROWSER_ACTIONS = frozenset({
    "browser_click", "browser_click_at", "browser_fill", "browser_fill_form", "browser_type_at",
    "browser_press", "browser_select_option", "browser_pick_suggestion",
})
#: 만진 뒤 **결과를 읽은** 걸음.
_BROWSER_LOOKS = frozenset({"browser_read", "browser_snapshot", "browser_verify", "browser_extract"})


def _is_local_page(url: str) -> bool:
    lowered = str(url or "").strip().lower()
    if lowered.startswith("file:"):
        return True
    host = re.sub(r"^[a-z]+://", "", lowered).split("/")[0].split(":")[0]
    return host in {"localhost", "127.0.0.1", "[::1]"} or host.endswith(".localhost")


def browser_verification_indices(steps: list[dict[str, Any]]) -> list[int]:
    """이 PC 안 페이지를 **만진 뒤 읽은** 걸음의 번호 — 코드 판의 검증으로 친다 (2026-09-30 대표 결정).

    전에는 「브라우저로 본 것은 검증이 아니다」였다. 그래서 메모 앱(`index.html` 하나)을 만들고 브라우저로 칸을 채우고
    버튼을 누르고 결과까지 읽은 판이, 규칙이 시키는 프로젝트 명령을 안 돌렸다고 `coding_verification_missing` 으로 죽었다.
    정적 페이지 하나짜리 일에는 그 확인이 곧 검증이다.

    말로 「확인했다」는 건 안 친다 — **도구 걸음**이 있어야 한다: 이 PC 안 페이지(file·localhost)에서 누르기·채우기 뒤에
    읽기가 와야 하고, 그 사이 코드가 바뀌면 처음부터 다시 센다. 보기만(열기·읽기만) 한 것은 여전히 검증이 아니다.
    """
    current = ""
    acted = False
    found: list[int] = []
    for index, step in enumerate(steps):
        tool = str(step.get("tool") or "")
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        url = str(evidence.get("url") or (arguments.get("url") if tool == "browser_open" else "") or "")
        if url:
            # 다른 페이지로 옮겼다 — 앞 페이지에서 만진 것은 이 페이지의 확인이 아니다. `#`·`?` 만 바뀐 것은 같은 페이지다.
            if url.split("#")[0].split("?")[0] != current.split("#")[0].split("?")[0]:
                acted = False
            current = url
        if not step.get("ok"):
            continue
        if tool in _CODE_MUTATION_TOOLS:
            acted = False
            continue
        if not _is_local_page(current):
            continue
        if tool in _BROWSER_ACTIONS:
            acted = True
        elif tool in _BROWSER_LOOKS and acted:
            found.append(index)
    return found


def browser_action_awaits_look(steps: list[dict[str, Any]]) -> bool:
    """이 PC 안 페이지를 **만졌는데 그 뒤에 읽기가 없는가** — 읽기 한 번이면 검증이 된다.

    ★ 2026-10-04 사다리 L1: 페이지를 만들고 열고 버튼을 누른 뒤 바로 답했다. 빠진 것은 누른 뒤의 읽기 한 걸음뿐인데,
      되받기는 「파일을 고치고 테스트를 돌려라 … ① … ② …」 긴 안내였다. 모델은 ②를 골라 임시 스크립트를 만들고
      (그게 코드 변경으로 세어져 누른 것까지 무효가 됐다) 엉뚱한 도구로 돌리다 `coding_verification_missing` 으로 끝났다.
      채점은 통과한 판이다. 무엇이 빠졌는지 알면 그것만 말한다.
    """
    current = ""
    pending = False
    for step in steps:
        tool = str(step.get("tool") or "")
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        url = str(evidence.get("url") or (arguments.get("url") if tool == "browser_open" else "") or "")
        if url:
            if url.split("#")[0].split("?")[0] != current.split("#")[0].split("?")[0]:
                pending = False
            current = url
        if not step.get("ok"):
            continue
        if tool in _CODE_MUTATION_TOOLS:
            pending = False
        elif not _is_local_page(current):
            continue
        elif tool in _BROWSER_ACTIONS:
            pending = True
        elif tool in _BROWSER_LOOKS:
            pending = False
    return pending


def _same_command(value: Any) -> str:
    """명령을 견주기 좋게 한 줄로 — 목록이면 이어 붙이고 빈칸을 하나로."""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(part) for part in value)
    return " ".join(str(value or "").split())


def declared_check_is_current(steps: list[dict[str, Any]], command: str) -> bool:
    """맡긴 쪽이 정한 **확인 명령**이 마지막 변경 **뒤에** 통과했는가 (2026-10-09).

    바깥 AI 가 코드 일을 맡기며 「이 명령이 통과하면 끝」을 같이 줬을 때의 판정이다. 과제 글에서 요구를 낱말로 뽑아 대조하지 않고
    이 하나로 가른다 — 그 밤의 숙제에서 과제 글 속 예시 문장이 판을 읽기 전용으로 묶었고(hw3), 시험이 통과한 판이 「읽은 원문에
    없는 이름」으로 partial 이 됐다(사다리 L7). 둘 다 요구를 글에서 읽어서 생긴 일이다.

    모델이 **스스로** 같은 명령을 돌려 통과한 것도 친다. 그 뒤에 파일을 다시 고쳤으면 그 통과는 지금 코드의 것이 아니다.
    """
    wanted = _same_command(command)
    if not wanted:
        return False
    last = max(
        (
            index for index, step in enumerate(steps)
            if step.get("ok")
            and str(step.get("tool") or "") == "local_run_project_command"
            and bool((step.get("evidence") or {}).get("verified"))
            and _same_command((step.get("arguments") or {}).get("command")) == wanted
        ),
        default=-1,
    )
    if last < 0:
        return False
    return not any(
        step.get("ok") and str(step.get("tool") or "") in _CODE_MUTATION_TOOLS
        for step in steps[last + 1:]
    )


def code_verification_is_current(steps: list[dict[str, Any]]) -> bool:
    """현재 산출물이 마지막 성공 검증 뒤에 바뀌지 않았는지 판정한다.

    검증을 위해 새 스크립트를 만들고 성공 실행한 뒤 그 스크립트만 지우는 것은
    산출물 변경이 아니다. 예전 판정은 그 정리를 새 패치로 세서 이미 성공한 작업을
    ``coding_verification_missing`` 으로 끝냈다. 단, 작업 전에 있던 파일이나 실제
    산출물을 지운 경우는 계속 새 변경으로 취급한다.
    """
    last_verification = max(
        (
            index
            for index, step in enumerate(steps)
            if step.get("ok")
            and str(step.get("tool") or "") == "local_run_project_command"
            and bool((step.get("evidence") or {}).get("verified"))
        ),
        default=-1,
    )
    # 이 PC 안 페이지를 만지고 읽은 확인도 검증이다(2026-09-30) — 둘 중 늦은 것이 마지막 검증.
    last_verification = max([last_verification, *browser_verification_indices(steps)])
    if last_verification < 0:
        return False

    def mutation_path(step: dict[str, Any]) -> str:
        evidence = step.get("evidence") or {}
        arguments = step.get("arguments") or {}
        value = evidence.get("output_path") or arguments.get("path") or ""
        return str(value).replace("/", "\\").rstrip("\\").casefold()

    for index, step in enumerate(steps[last_verification + 1 :], last_verification + 1):
        if not step.get("ok") or str(step.get("tool") or "") not in _CODE_MUTATION_TOOLS:
            continue
        if str(step.get("tool") or "") != "local_delete_file":
            return False
        deleted_path = mutation_path(step)
        if not deleted_path:
            return False
        created_here = any(
            prior.get("ok")
            and str(prior.get("tool") or "") == "local_write_file"
            and bool((prior.get("evidence") or {}).get("created"))
            and mutation_path(prior) == deleted_path
            for prior in steps[:index]
        )
        if not created_here:
            return False
    return True


def code_ready_for_final_answer(
    steps: list[dict[str, Any]], *, plan_met: bool, review_requested_step: int
) -> bool:
    """적대적 검토 뒤의 성공 검증까지 끝난 Code 판은 도구를 내려놓는다."""
    if not plan_met or review_requested_step < 0 or not code_verification_is_current(steps):
        return False
    return any(
        index >= review_requested_step
        and step.get("ok")
        and str(step.get("tool") or "") == "local_run_project_command"
        and bool((step.get("evidence") or {}).get("verified"))
        for index, step in enumerate(steps)
    )


_QWEN_DESCRIPTIONS = {
    "local_index_codebase": "Rank repository files, symbols, imports, and related tests for the task. Index first.",
    "local_find_symbol": (
        "Find where a function/class/constant is DEFINED and WHO CALLS IT (Python). "
        "Returns exact line ranges - read only those lines, never the whole file. "
        "Call this before editing: it shows what will break. Args: path, symbol."
    ),
    "local_list_directory": "List one directory when the index is insufficient.",
    "local_search_files": "Find paths by file name. Read a match before making claims.",
    "local_grep": (
        "Search file CONTENTS by regex. Returns path:line with context. "
        "Use this to find where a value is set or who calls a function — "
        "do not open files and skim."
    ),
    "local_glob": "Find files by name pattern across the tree (e.g. **/*.test.ts).",
    "local_write_document": "Create a real xlsx/docx/csv file from rows or blocks. For a presentation deck use local_make_slide.",
    "local_make_slide": (
        "Design a presentation deck (PPTX). Call once without html (optionally with style) to get the design rules, "
        "the style list and a style example, "
        "then call per slide in order with title, index, total and a self-contained 1280x720 HTML slide. "
        "Each slide appears on the user's screen as it is made; the last slide builds the PPTX."
    ),
    "local_read_document": "Read a PDF, docx, xlsx, pptx or hwpx design document in the repository.",
    "local_read_text_file": (
        "Read actual code. Use before editing. "
        "Prefer line_start/line_end from index_codebase next_reads or the outline — "
        "reading a whole file floods the transcript."
    ),
    "local_write_file": "Create or replace one text file inside the selected workspace.",
    "local_apply_edit": (
        "Replace one exact old block with new text. The old block must occur once. "
        "If the text will not match (mixed quotes/backslashes), omit old and give line_start, line_end and first_line "
        "(the current text of line_start) to replace those lines with new."
    ),
    "local_delete_file": (
        "Delete one file inside the selected workspace, mainly to clean up a temporary probe. The deletion is backed up. "
        "A folder is deleted only if this task created it (e.g. a node_modules that just appeared) or it is a cache "
        "(__pycache__, .pytest_cache); folder deletion cannot be undone, so folders that existed before are refused."
    ),
    "local_run_project_command": (
        "Run an allowed command in the workspace. These are installed and ready:\n"
        "  tests    python -m pytest -q          (add --cov=<pkg> for coverage)\n"
        "  lint     python -m ruff check .       python -m ruff format .\n"
        "  types    python -m mypy <path>\n"
        "  security python -m bandit -r <path>\n"
        "  dead     python -m vulture <path>     complexity  python -m radon cc -s <path>\n"
        "  deps     python -m pip_audit\n"
        "  script   python <file>.py             (only files inside the workspace)\n"
        "  git      status/diff/log/show/remote/blame + add/commit/branch/switch\n"
        "JavaScript also runs here (not in sandbox_run): command=\"node test.js\" or command=\"npm test\". "
        "After changing code, run the tests first, then ruff and mypy on what you touched. "
        "Read failure_kind before retrying."
    ),
    "local_request_path_access": (
        "Ask the user to open a folder that is outside the allowed roots. "
        "Call this ONCE after a path_outside_allowed_roots error instead of retrying the same path. "
        "mode='read' to look, mode='write' to create or change files there. "
        "An approval card appears on screen; nothing opens until the user approves."
    ),
    "ask_user": (
        "Ask the user a multiple-choice question and wait for the answer. Use it only when the request "
        "has two or more readings and a wrong guess is costly to undo. 2-4 short options; mark the best "
        "one with recommended. Do not ask what you can find out yourself. The answer comes back as the result."
    ),
    "local_run_shell": (
        "Run one PowerShell command in the workspace (the window never appears). "
        "Use it to look around: dir, Get-ChildItem, Select-String, Get-Content, git log, --version. "
        "Read-only commands run immediately; anything that creates, deletes, installs or reaches the network asks the user first. Security settings are never allowed."
    ),
    "local_preview_page": (
        "Serve a web page you created on a loopback URL so you can open it with browser_open and see how it looks. The user sees the same screen."
    ),
    "sandbox_run": "Run isolated scratch code; it does not verify the selected repository.",
    "sandbox_fetch": "Fetch a previously generated sandbox artifact.",
    "naver_news": "Find current Korean news sources by query. Read-only research.",
    "naver_web": "Find Korean web sources with titles, snippets, and URLs. Read-only research.",
    "github_search": "Search public GitHub repositories and return stars, descriptions, and URLs.",
    "reddit_hot": "Read current hot posts from one public subreddit.",
    "hackernews_top": "Read current top Hacker News technology posts.",
    "browser_search": "Search the web and return ranked titles, URLs, and snippets.",
    "browser_open": "Open one exact HTTP(S) URL for read-only research.",
    "browser_open_result": "Open one ranked result from the latest browser search.",
    "browser_extract": "Extract the main article body from the current page.",
    "browser_read": "Read visible text on the current page.",
    "browser_links": "List relevant links from the current page.",
    "browser_site_search": "Search inside the currently open site without submitting changes.",
    "browser_load_more": "Load more items from the current read-only result list.",
    "browser_close": "Close the research browser when finished.",
}


#: 설명을 살려 둘 인자. 「어떻게 부르면 값이 달라지는가」를 담은 것만 남긴다 —
#: 나머지를 지우는 원래 뜻(스키마를 짧게)은 그대로다.
_KEEP_PARAM_DESCRIPTIONS = frozenset({"line_start", "line_end"})


def qwen_code_tools(tools: list[dict[str, Any]] | None, allowed: set[str] | frozenset[str]) -> list[dict[str, Any]]:
    """Qwen에 필요한 코드 도구만 짧고 닫힌 JSON schema로 준다."""
    compact: list[dict[str, Any]] = []
    for source in tools or []:
        function = source.get("function") if isinstance(source, dict) else None
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "")
        if name not in allowed:
            continue
        item = copy.deepcopy(source)
        target = item["function"]
        target["description"] = _QWEN_DESCRIPTIONS.get(name, str(target.get("description") or ""))
        parameters = target.get("parameters")
        if isinstance(parameters, dict):
            parameters["additionalProperties"] = False
            properties = parameters.get("properties")
            if isinstance(properties, dict):
                for key, prop in properties.items():
                    # ★ 설명을 통째로 지우면 **줄 범위 읽기가 사라진다** (2026-08-31).
                    #
                    # 기본 스키마는 이미 잘 적혀 있었다 — "outline 의 범위를 그대로
                    # 넣으면 된다". 그런데 코드 모드로 오면서 도구 설명은 갈아끼우고
                    # 인자 설명은 전부 지워, 모델이 보는 것은 **이름 네 개**뿐이었다.
                    # 그래서 파일을 통째로 읽었고(기본 15,000자), 열 번이면 15만 자다.
                    # 어젯밤 67,744토큰 프롬프트와 호출당 1~4분이 거기서 나왔다.
                    #
                    # 짧게 유지하려는 원래 뜻은 지키되, **일을 바꾸는 인자만** 남긴다.
                    if isinstance(prop, dict) and key not in _KEEP_PARAM_DESCRIPTIONS:
                        prop.pop("description", None)
        compact.append(item)
    return compact
