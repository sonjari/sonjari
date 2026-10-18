"""ALTURE JARVIS 를 MCP 서버로 내보낸다 — 안전 규칙을 붙인 채로.

## 무엇이고 왜 있나

클로드 데스크톱·커서 같은 MCP 클라이언트에서 자비스의 도구를 그대로 쓰게 한다.
검색해서 → 들어가서 → 본문 읽고 → 다음 걸 여는 그 고리를, 코드를 쓰던 자리에서
바로 부를 수 있다.

**핵심은 도구를 나눠 주는 것이 아니라 규칙을 나눠 주는 것이다.** 비슷한 데스크톱
자동화 MCP 들은 도구만 던져 준다(2026-08-06 에 nuphus 를 검토하고 도입하지 않은
이유가 그것이다 — 도구 36개가 우리 게이트웨이 **바깥**에 붙는다). 여기서는 되돌릴
수 없는 동작이 여전히 화면 승인을 거치고, 키 입력은 허용 목록만 통과하며, 모든
호출이 감사 기록에 남는다.

## ★ 왜 자체 런타임을 띄우지 않는가

이 서버는 **이미 돌고 있는 자비스에 HTTP 로 붙는 얇은 껍데기**다. `JarvisRuntime`
을 여기서 새로 만들면 안 된다. 그러면 이렇게 된다:

    브라우저 2개 · 승인 대기열 2개 · 기억 2개 · 상태 2개

이 고장은 이미 겪었다. 2026-08-06 에 작은 HUD 와 전체화면이 각자 sessionId 를 들고
있어서 **자비스가 둘로 갈라졌고**(메시지 94개 대 14개), 사용자 눈에는 방금 한 얘기를
모르는 다른 자비스로 보였다. 승인까지 갈라지면 훨씬 나쁘다 — 결제 승인이 아무도
안 보는 창에 뜬다.

그래서 진실은 한 곳에만 둔다: 8091 에서 돌고 있는 그 자비스.

## 실행

    JARVIS_CONTROL_TOKEN 이 설정돼 있어야 한다(없으면 /v1/tools/execute 가 401).

    python -m alture_jarvis.mcp_server

토큰 생성과 클로드 데스크톱 설정 출력은 `scripts/setup_mcp.py` 가 한다
(`--rotate` 로 토큰 교체). 붙었는지 확인은 `scripts/verify_mcp_server.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from typing import Any, Iterable

import httpx

from .brand import MCP_SERVER_NAME, NAME, NAME_KO
from .outbound import clean_needs
from .delegation import (
    CLAUDE_CODE_MAX_WAIT_SEC, DELEGATION_TOOLS, GUIDE_TOOL, MAX_WAIT_SEC, STATUS_TOOL, TASK_TOOL, is_claude_code, localized_tool,
    summarize_job,
)

__all__ = ["ToolFilter", "JarvisMcpBridge", "build_server", "main", "INSTRUCTIONS", "INSTRUCTIONS_EN"]

# ★ 맡기기 문은 **처음부터 보이게** 한다 (2026-09-23 오후 비용 재측정).
#   클로드 코드는 MCP 도구를 기본으로 지연 적재한다 — 이름만 싣고 설명은 도구 찾기로 찾아야 보인다. 그 조건에서
#   클로드는 `sonjari_task` 를 찾지 않고 자기 WebFetch 를 골랐다: 지침 없이 3판 중 2판, 잇기 지침을 넣어도
#   맡기기 전용 3판 중 2판. 「연결해도 안 부른다」(09-16)가 지연 적재로 돌아온 것이다.
#   `_meta["anthropic/alwaysLoad"]` 는 **그 도구만** 지연 적재에서 뺀다(code.claude.com/docs/en/mcp
#   「Exempt a server from deferral」). 낮은 도구 100여 개는 계속 지연돼 싸고, 맡기기 문 셋은 늘 보인다.
#   이 표시를 모르는 호스트는 그냥 무시한다.
ALWAYS_LOAD = frozenset({TASK_TOOL["name"], STATUS_TOOL["name"], GUIDE_TOOL["name"]})
#: 1단계까지의 맡기기 문 이름 → 지금 이름. 목록에는 새 이름만 낸다(두 벌이 보이면 호스트가 헷갈린다).
LEGACY_TOOL_NAMES = {
    "ontelic_task": TASK_TOOL["name"],
    "ontelic_task_status": STATUS_TOOL["name"],
    "ontelic_guide": GUIDE_TOOL["name"],
}
ALWAYS_LOAD_META = {"anthropic/alwaysLoad": True}


def lean_toolset() -> bool:
    """바깥 AI 에게 **맡기기 문(둘)과 가이드만** 내보내나. 기본은 그렇다 — `JARVIS_MCP_TOOLSET=full` 이면 낮은 도구도.

    ★ 2026-09-23 제품 결정(재측정 뒤): 기본값을 맡기기 전용으로.
      - 본실험(지연 적재 끔): 낮은 도구 100여 개의 설명서가 호스트 입력을 약 7만 6천 토큰 늘렸다 — 도구 전부 팔이 두 배.
      - 재측정(클로드 코드 기본 = 지연 적재 켬 + 맡기기 문 alwaysLoad, 4과제×3): 맡기기 전용 11/12 · 합계 $1.62,
        도구 전부 11/12 · $2.16(−25%). 도구 전부에선 클로드가 낮은 도구로 직접 22걸음을 걷는 판이 남는다.
      - 가이드도 원래 「낮은 도구를 직접 부르지 말고 맡겨라」였다 — 목록이 권고와 맞게 됐다.
    `JARVIS_MCP_DELEGATION=0`(맡기기 끈 실측)이면 낮은 도구가 유일한 손이라 전부 낸다.
    설치되는 가이드 스킬(`api._exported_tools`)도 이 판단을 따른다 — 없는 도구를 적어 주면 부르다 막힌다.
    """
    if os.environ.get("JARVIS_MCP_DELEGATION", "1") == "0":
        return False
    return os.environ.get("JARVIS_MCP_TOOLSET", "delegate").strip().lower() != "full"

# ★ 연결할 때 클라이언트(Claude Desktop·Claude Code·Cursor)가 읽는 안내문 (2026-09-16, 인수인계 H1-a).
#   비어 있던 동안 Claude 는 도구 설명만 보고 온텔릭이 무엇인지 추측했다. 사실만 적는다 — 「이렇게 해라」
#   부탁은 안 먹는다(사고 R). 구조로 박을 수 있는 것(L2 비노출·승인·근거 대조)은 코드가 한다.
INSTRUCTIONS = f"""{NAME}({NAME_KO})는 이 PC 에서 도는 로컬 AI 작업 도우미입니다. 사용자의 실제 크롬(로그인된 사이트 포함), 이 PC 의 파일, 워드·엑셀·한글 문서를 직접 다룹니다.

언제 부르나
- 웹에서 찾아 읽고 → 표·문서·엑셀로 만드는 일 (예: 채용 공고·상품·가격 조사 후 파일로)
- 사용자가 로그인한 실제 브라우저가 필요한 일
- 사용자 PC 의 파일을 읽거나 새 문서를 만드는 일
- 코딩 중에도: 여러 페이지를 읽어야 하는 조사(라이브러리 문서·에러 메시지·버전 비교) — 본문은 이 PC 에서 읽고 결과만 돌아와 이 대화의 창을 아낍니다. 사용자 로그인이 있어야 보이는 화면 확인도 여기입니다(당신의 자동화 브라우저는 빈 브라우저라 로그인이 없습니다)
- 이 PC 의 코드 파일 읽어 오기 · 당신이 짠 수정을 그 파일에 쓰기
- 저장소의 좁은 코드 일: sonjari_task 에 repo(저장소 폴더)·check(통과하면 끝인 명령)를 주면 새 가지에서 고치고, 바뀐 것과 가져가는 명령을 돌려줍니다(원래 폴더는 안 건드립니다)

부르지 말 것
- 이미 대화에 있는 글의 요약·번역
- 당신이 방금 띄워 둔 앱(localhost)의 동작 확인 — 당신의 테스트 도구가 더 빠르고 결과를 직접 봅니다
- 큰 설계·처음 보는 API(예: 3ds Max `pymxs`) 코드를 통째로 맡기기 — 로컬 모델이라 웹에서 공부하느라 오래 걸립니다. 고칠 코드는 당신이 짜서 {NAME_KO}에게 그 경로에 쓰게 하거나, 파일 한두 개 크기로 쪼개 repo·check 로 맡기세요

어떻게
- 처음 맡기기 전에 sonjari_guide 를 한 번 불러 사용법을 읽으세요.
- 과제 하나는 sonjari_task 로 통째로 맡기고 sonjari_task_status 로 결과를 받으세요. browser_* 같은 낮은 도구를 여러 번 부르는 것보다 빠르고 토큰이 적습니다.
- 결과의 unsupported_numbers 는 도구가 준 적 없는 숫자입니다. 사실로 전하지 말고 확인이 필요하다고 알리세요.
- 결과에 model_hint 가 있으면 그 일에 손자리 모델이 작다는 뜻입니다. 사용자에게 그대로 전하세요. 맡길 일은 sonjari_guide 끝의 「이 PC 의 손자리 모델」 표를 보세요.
- 되돌릴 수 없는 동작(메일 발송·발행·결제·삭제)은 이 연결로 할 수 없습니다. 사용자에게 {NAME} 창에서 직접 하도록 알리세요. 승인 카드도 그 창에 뜹니다.
- 로그인·보안 문자·결제 화면을 만나면 사람에게 넘깁니다. 예외: 이 PC 개발 주소(localhost 등)의 시험 앱은 과제 문장에 시험 계정을 그대로 적으면 {NAME_KO}가 그 값으로 넣습니다.
- 결과의 sources(읽은 주소·원문)·files·「없었다」에 붙은 본 범위로 당신이 직접 확인할 수 있습니다.
- {NAME_KO}는 한 번에 한 일을 합니다. 과제가 여러 개면 하나가 끝난 뒤 다음을 맡기세요.
- 만든 파일은 결과의 files 경로에 있습니다.
- 과제는 사용자가 당신과 쓰는 언어로 적으세요.
"""

# ★ 영어 연결의 안내문 (2026-10-19). 위 한국어판과 **같은 사실 · 같은 순서**다 — 한쪽만 고치지 말 것.
#   영어로 시킨 클로드 코드가 한국어 안내문을 따라 과제를 한국어로 넘긴 판(`029fae29`)이 이것을 만들게 했다.
INSTRUCTIONS_EN = f"""{NAME} is a local AI assistant that runs on this PC. It works directly in the user's real Chrome (including logged-in sites), the files on this PC, and Word/Excel/Hangul documents.

When to call it
- Finding and reading things on the web, then turning them into a table, document or spreadsheet (e.g. research job posts, products or prices and save them to a file)
- Work that needs the browser the user is actually logged into
- Reading files on the user's PC or creating new documents
- While coding, too: research that means reading many pages (library docs, error messages, version comparisons) — the page text is read on this PC and only the result comes back, which saves this conversation's context. Checking screens that only show up when the user is logged in also belongs here (your automation browser is an empty browser without their logins)
- Reading code files on this PC, and writing a fix you made into that file
- Narrow code jobs in a repository: give sonjari_task a repo (repository folder) and a check (a command that means done when it passes); it fixes the code on a new branch and returns what changed and the commands to take it (the original folder is untouched)

When not to call it
- Summarizing or translating text that is already in the conversation
- Checking an app you just started (localhost) — your own test tools are faster and you see the result directly
- Handing over a whole large design or code against an API it has never seen (e.g. 3ds Max `pymxs`) — it is a local model and will spend a long time studying on the web. Write the code yourself and have {NAME} write it to that path, or split it into one- or two-file pieces with repo and check

How
- Call sonjari_guide once to read how to use it before handing off the first task.
- Hand one task as a whole with sonjari_task and get the result with sonjari_task_status. That is faster and uses fewer tokens than calling low-level tools such as browser_* many times.
- unsupported_numbers in the result are numbers no tool ever returned. Do not pass them on as fact; say they need checking.
- If the result has model_hint, Sonjari's model is small for that job. Pass it to the user as is. For which jobs to hand off, see the "Sonjari model on this PC" table at the end of sonjari_guide.
- Irreversible actions (sending mail, publishing, paying, deleting) cannot be done over this connection. Tell the user to do them in the {NAME} window. Approval cards also appear in that window.
- Login, captcha and payment screens are handed to a person. Exception: for a test app on a development address on this PC (localhost and so on), write the test account in the task and {NAME} will enter those values.
- You can check the work yourself with sources (addresses read and original text), files, and the range it looked at when it says something was not there.
- {NAME} does one job at a time. If there are several tasks, hand off the next one after the previous one finishes.
- Files it made are at the paths in files.
- Write the task in the language the user is using with you.
"""


DEFAULT_BASE_URL = "http://127.0.0.1:8091"

# 기본으로 내보내지 않는 도구.
#
# 카메라·시선·짐벌은 이 PC 에 물린 **물리 장치**라, 다른 창에서 부르면 사용자가 보고
# 계신 화면이 말없이 움직인다. ui_* 는 자비스가 보고 있는 화면을 기준으로 좌표를
# 잡으므로 바깥에서 부르면 엉뚱한 곳을 짚는다.
#
# 막는 것이 아니라 기본값일 뿐이다 — JARVIS_MCP_INCLUDE 로 다시 열 수 있다.
DEFAULT_EXCLUDE_PREFIXES = ("camera_", "ui_")

# ★ 되돌릴 수 없는 도구(L2)는 기본으로 **내보내지 않는다** — 승인을 건너뛰는 게
# 아니라 그 능력을 아예 주지 않는다(사용자 결정, 2026-08-06).
#
# 이유 둘:
#
# 1. **승인 카드는 자비스 창에 뜬다.** 클로드 데스크톱에서 부르면 사용자는 다른
#    화면을 보고 계신다. 아무도 안 보는 카드는 5분 뒤 만료되고, 작업은 이유 없이
#    멈춘 것처럼 보인다 — 같은 창 안에서도 이미 한 번 놓친 적이 있다(8-06 2.2).
# 2. **바깥 클라이언트가 늘어날수록 되돌릴 수 없는 동작의 출발점이 늘어난다.**
#    메일 발송·일정 삭제·블로그 발행은 자비스 창에 그대로 있다. 거기서는 카드가
#    보이고, 그 화면이 승인의 자리다.
#
# 읽고 조사하는 일(L0·L1 55개)은 전부 열려 있다 — MCP 로 내보내는 목적이 그것이다.
# 필요하면 `JARVIS_MCP_MAX_RISK=L2` 로 열 수 있고, 그때도 승인은 여전히 걸린다.
DEFAULT_MAX_RISK = "L1"

# 승인이 필요한 도구를 불렀을 때 모델에게 돌려줄 말.
#
# 이게 중요하다: MCP 클라이언트의 모델은 이 응답만 보고 다음 수를 정한다. "실패"로만
# 읽히면 다른 도구로 우회하거나 없는 사실을 지어낸다. 무엇이 필요한지, 어디를 봐야
# 하는지, 다시 부르면 되는지를 문장으로 말해 줘야 한다.
_APPROVAL_HELP = (
    "이 동작은 되돌릴 수 없어서 사람의 화면 승인이 필요합니다.\n"
    "Sonjari 창에 승인 카드가 떴습니다 — 사용자가 승인하면 **같은 인자로 다시 호출**하세요.\n"
    "승인은 5분 뒤 만료되고, 한 번 쓰면 소진됩니다.\n"
    "사용자를 대신해 승인할 수 없고, 우회할 다른 도구를 찾지 마세요."
)


class ToolFilter:
    """어떤 도구를 바깥으로 내보낼 것인가.

    포함이 제외를 이긴다 — 기본값으로 닫아 둔 것을 손으로 열 수 있어야 하고, 그 반대
    (열어 둔 것을 손으로 닫기)도 되어야 하는데, 둘 중 하나는 우선순위를 정해야 한다.
    사용자가 이름을 **명시한** 쪽을 존중하는 편이 덜 놀랍다.
    """

    def __init__(
        self,
        *,
        include: Iterable[str] = (),
        exclude: Iterable[str] = (),
        exclude_prefixes: Iterable[str] = DEFAULT_EXCLUDE_PREFIXES,
        max_risk: str = DEFAULT_MAX_RISK,
    ) -> None:
        self.include = {item.strip() for item in include if item.strip()}
        self.exclude = {item.strip() for item in exclude if item.strip()}
        self.exclude_prefixes = tuple(exclude_prefixes)
        self.max_risk = max_risk.upper() if max_risk else "L2"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ToolFilter":
        source = env if env is not None else dict(os.environ)

        def _split(key: str) -> list[str]:
            return [part for part in (source.get(key, "") or "").replace(";", ",").split(",") if part.strip()]

        prefixes = _split("JARVIS_MCP_EXCLUDE_PREFIXES")
        return cls(
            include=_split("JARVIS_MCP_INCLUDE"),
            exclude=_split("JARVIS_MCP_EXCLUDE"),
            exclude_prefixes=tuple(prefixes) if prefixes else DEFAULT_EXCLUDE_PREFIXES,
            max_risk=source.get("JARVIS_MCP_MAX_RISK") or DEFAULT_MAX_RISK,
        )

    def allows(self, tool: dict[str, Any]) -> bool:
        name = str(tool.get("name") or "")
        if not name:
            return False
        if name in self.include:
            return True
        if not tool.get("enabled", True):
            return False
        if name in self.exclude:
            return False
        if any(name.startswith(prefix) for prefix in self.exclude_prefixes):
            return False
        # 위험도 상한. "L1" 로 두면 되돌릴 수 없는 동작을 아예 안 보여 준다 —
        # 승인 카드를 볼 수 없는 자리(무인 실행)에서 쓰라고 있는 것이다.
        order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
        return order.get(str(tool.get("risk_level") or "L0"), 0) <= order.get(self.max_risk, 2)

    def apply(self, tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [tool for tool in tools if self.allows(tool)]


def describe(tool: dict[str, Any]) -> str:
    """모델이 읽을 도구 설명. 위험도를 문장으로 붙인다.

    `risk_level: "L2"` 같은 딱지는 모델에게 아무 뜻이 없다. 무슨 일이 일어나는지를
    말해 줘야 부르기 전에 사람에게 물어볼지 판단할 수 있다.
    """
    text = str(tool.get("description") or "").strip()
    if str(tool.get("risk_level")) == "L2":
        text += "\n\n⚠️ 되돌릴 수 없는 동작입니다. 호출하면 사용자 화면에 승인 카드가 뜨고, 승인 전에는 실행되지 않습니다."
    return text


#: 영어 연결에서도 **바꾸지 않는** 칸 — 명령 · 경로 · 저장소(한국어 폴더 이름을 바꾸면 명령이 깨진다) · 모델의 답 원문.
_KEEP_FOR_HOST = frozenset({"repo", "worktree", "review", "take", "discard", "name", "base", "stat", "changed",
                            "answer", "unverified_claim", "error", "job_id"})
_HANGUL_RE = re.compile("[가-힣]")
#: 문장 끝 — 안내문은 여러 문장을 띄어쓰기 하나로 이어 붙여 나간다(`delegation._failure_report` 의 `" ".join(notes)`).
_SENTENCE_END = re.compile(r"(?<=[.)])\s+")


def _english(text: str) -> str:
    """한 글을 화면 사전으로 영어로. 통째로 → 줄마다 → 「 · 」 조각마다 → 이어 붙은 문장을 가장 긴 덩어리부터.

    사전은 한 문장 · 한 조각 단위로 들어 있는데, 나가는 글은 여러 개를 이어 붙인 것이 많다(10-19 운영 맡기기 판 1,481개를
    영어로 요약해 보니 남은 한국어 1,610줄 중 1,393줄이 「○○ 에게 보냄 · 정제 N」 같은 이어 붙인 한 줄이었다).
    찾지 못한 조각은 그대로 둔다 — 빠진 번역이 글을 깨지 않는다.
    """
    from . import ui_i18n

    if not text or not _HANGUL_RE.search(text):
        return text
    whole = ui_i18n.translate_text(text)
    if whole != text:
        # 사전이 통째로 알아봤다 — 빈칸에 남은 한국어(「메일 주소 1」 같은 항목 이름)는 사용자의 말일 수 있어 그대로 둔다.
        return whole
    if "\n" in text:
        return "\n".join(_english(line) for line in text.split("\n"))
    # 「 · 」 조각은 사전(`ui_i18n.translate_text`)이 나눠 찾는다 — 틀의 빈칸 안에서도 같은 길을 타게 한 자리에 둔다.
    sentences = [part for part in _SENTENCE_END.split(text) if part]
    if len(sentences) < 2:
        return whole
    out: list[str] = []
    start = 0
    while start < len(sentences):
        for end in range(len(sentences), start, -1):
            chunk = " ".join(sentences[start:end])
            moved = ui_i18n.translate_text(chunk)
            if not _HANGUL_RE.search(moved) or end == start + 1:
                out.append(moved)
                start = end
                break
    return " ".join(out)


class JarvisMcpBridge:
    """돌고 있는 자비스에 HTTP 로 붙는다. 상태는 저쪽에만 있다."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: str = "",
        *,
        tool_filter: ToolFilter | None = None,
        timeout: float = 300.0,
        client: Any = None,
        lang: str = "ko",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.filter = tool_filter or ToolFilter()
        self.timeout = timeout
        self._client = client
        # 이 연결의 언어(`mcp_language.pick_language`). 영어면 도구 설명 · 결과 안내 · 오류 문구를 영어로 낸다.
        self.lang = lang if lang in ("ko", "en") else "ko"
        # 내보내기로 한 도구 이름. 호출을 막는 데 쓴다.
        #
        # ★ 감추는 것만으로는 못 막는다(2026-08-06 실측). 목록에서 뺀
        # `google_gmail_send` 를 그냥 불렀더니 그대로 자비스까지 갔다 — MCP 클라이언트는
        # 목록에 없는 이름도 보낼 수 있고, 모델은 앞선 대화나 짐작으로 이름을 안다.
        # 승인 게이트가 있어서 실행되지는 않았지만, "안 내보낸다"는 약속이 목록에서만
        # 지켜지고 호출에서는 안 지켜지고 있었다.
        self._allowed: set[str] | None = None

    def say(self, value: Any) -> Any:
        """나가는 글을 이 연결의 언어로. 영어면 화면과 **같은 사전**(`ui_i18n`)으로 바꾼다 — 따로 번역을 두면 갈린다.

        사용자의 글 · 주소 · 파일 경로(`ui_i18n._KEEP_KEYS`)는 바꾸지 않는다. 사전에 없는 문장은 그대로 나간다.
        """
        if self.lang != "en":
            return value
        from . import ui_i18n

        def walk(item: Any, key: str = "") -> Any:
            if isinstance(item, str):
                return item if key in ui_i18n._KEEP_KEYS or key in _KEEP_FOR_HOST else _english(item)
            if isinstance(item, list):
                return [walk(part, key) for part in item]
            if isinstance(item, dict):
                return {name: walk(part, str(name)) for name, part in item.items()}
            return item

        return walk(value)

    def _dumps(self, value: Any, **kwargs: Any) -> str:
        return json.dumps(self.say(value), ensure_ascii=False, **kwargs)

    async def _http(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def list_tools(self) -> list[dict[str, Any]]:
        client = await self._http()
        # 위임 문 두 개는 목록 맨 앞에 — 거르는 대상이 아니다(런타임 도구가 아니라 이 껍데기가 만든 것).
        # `JARVIS_MCP_DELEGATION=0` 은 실측용: 「낮은 도구를 직접 부리기」와 「맡기기」를 같은 과제로 비교할 때 끈다.
        delegation = [] if os.environ.get("JARVIS_MCP_DELEGATION", "1") == "0" else [
            localized_tool(tool, self.lang) for tool in DELEGATION_TOOLS]
        guide = localized_tool(GUIDE_TOOL, self.lang)
        # ★ 2026-09-28 실측: 본체가 재시작 중일 때 클로드 세션이 붙으면 여기서 예외가 나 **도구 0개**로 기록됐고,
        #   클로드는 목록을 다시 묻지 않아 그 세션은 끝날 때까지 온텔릭을 못 썼다(연결됨 · tool_count 0).
        #   위임·가이드 문은 본체 없이도 있는 문이다 — 본체가 막 뜨는 중이면 잠깐 기다려 보고, 그래도 안 되면 그 셋만 낸다.
        #   부를 때 본체가 꺼져 있으면 그 호출이 「온텔릭이 꺼져 있다」고 말한다.
        runtime_payload: Any = None
        for attempt in range(3):
            try:
                response = await client.get(f"{self.base_url}/v1/tools")
                response.raise_for_status()
                runtime_payload = response.json()
                break
            except Exception:  # noqa: BLE001 — 본체가 아직 안 떴다
                if attempt < 2:
                    await asyncio.sleep(1.5)
        if runtime_payload is None:
            self._allowed = None  # 다음 호출 때 다시 본다 — 못 본 것을 「금지」로 굳히지 않는다
            return delegation + [guide]
        # 가이드는 위임을 꺼도 준다 — 읽기만 하는 문서다.
        runtime_tools = self.filter.apply(runtime_payload)
        if self.lang == "en":
            # 본체가 주는 낮은 도구 · 팩 도구의 설명도 화면과 같은 사전으로(사전에 없는 문장은 그대로).
            runtime_tools = [{**tool, "description": self.say(str(tool.get("description") or ""))} for tool in runtime_tools]
        # ★ 켜진 분야 팩의 문은 맡기기 전용 목록에도 넣는다(2026-09-27 게임 팩). 유니티는 「통째로 맡기기」보다
        #   클로드·코덱스가 레시피를 **직접 고르고, 새 스크립트를 짜서 온텔릭에게 돌려 보게** 하는 편이 맞다 —
        #   설계는 그쪽이, 사용자 PC 의 실제 프로젝트에서 돌리는 것은 온텔릭이.
        pack_tools = await self._enabled_pack_tools(client)
        allowed = delegation + [guide] + ([
            tool for tool in runtime_tools if str(tool.get("name")) in pack_tools
        ] if lean_toolset() else [
            tool for tool in runtime_tools
            if str(tool.get("name")) not in {TASK_TOOL["name"], STATUS_TOOL["name"], GUIDE_TOOL["name"]}
        ])
        self._allowed = {str(tool["name"]) for tool in allowed}
        return allowed

    async def _enabled_pack_tools(self, client: Any) -> set[str]:
        """켜진 팩의 도구 이름. 못 물어보면 빈 집합 — 모르는 것을 「켜져 있다」로 치지 않는다."""
        try:
            response = await client.get(f"{self.base_url}/v1/packs", headers={"X-JARVIS-TOKEN": self.token})
            if response.status_code != 200:
                return set()
            return {
                str(tool)
                for pack in response.json().get("packs") or []
                if pack.get("enabled")
                for tool in pack.get("tools") or []
            }
        except Exception:  # noqa: BLE001
            return set()

    async def _is_allowed(self, name: str) -> bool:
        """이 연결로 내보내기로 한 도구인가. 한 번도 목록을 안 냈으면 지금 낸다."""
        if self._allowed is None:
            try:
                await self.list_tools()
            except Exception:
                # 목록을 못 가져왔으면 막지 않는다 — 자비스가 잠깐 응답을 못 하는 것과
                # "금지된 도구"를 섞으면, 진짜 원인을 가린 채 엉뚱한 메시지가 나간다.
                # 실행 여부는 어차피 게이트웨이가 다시 판정한다.
                return True
            if self._allowed is None:
                # 본체가 꺼져 목록을 못 받았다(위임 문만 냈다) — 여기서도 막지 않는다. 호출이 「꺼져 있다」를 말한다.
                return True
        return name in (self._allowed or set())

    async def _model_fit(self) -> tuple[str, str, float, dict[str, Any] | None]:
        """지금 손자리의 대화·코드 모델과 카드 여유, 코드 일 추천. 못 물으면 빈 값 — 사용법·결과는 그대로 나간다."""
        client = await self._http()
        headers = {"X-JARVIS-TOKEN": self.token}
        try:
            code = (await client.get(f"{self.base_url}/v1/setup/models/picker?role=code", headers=headers)).json()
            chat = (await client.get(f"{self.base_url}/v1/setup/models/picker?role=chat", headers=headers)).json()
        except Exception:  # noqa: BLE001
            return "", "", 0.0, None
        return (str(chat.get("current") or ""), str(code.get("current") or ""), float(code.get("budget_gb") or 0.0),
                code.get("suggestion") or None)

    async def _model_fit_note(self) -> str:
        from .hf_catalog import model_fit_note

        chat, code, budget, upgrade = await self._model_fit()
        return "\n" + model_fit_note(chat, code, budget, upgrade) if chat else ""

    async def _delegate(self, name: str, arguments: dict[str, Any], *, caller: str = "") -> tuple[str, bool]:
        """위임 문. 잡을 넣거나(`sonjari_task`) 잡을 요약한다(`sonjari_task_status`)."""
        client = await self._http()
        headers = {"X-JARVIS-TOKEN": self.token}
        try:
            if name == TASK_TOOL["name"]:
                task = str(arguments.get("task") or "").strip()
                if not task:
                    return "task 가 비어 있습니다 — 맡길 과제를 한 문장으로 주세요.", True
                body: dict[str, Any] = {
                    "prompt": task[:4000],
                    # 화면이 「바깥 AI 가 맡긴 일」로 알아보고 생각·진행을 띄운다(2026-09-16 사용자 목격: 안 보였다).
                    "origin": "mcp",
                    "display_prompt": f"바깥 AI 가 맡긴 일 · {task.strip()[:60]}",
                    "open_results": False,
                    # ★ 과제마다 **제 방**을 준다 (2026-09-29 1순위 버그).
                    #   대화 번호를 안 보내면 「사람이 지금 보고 있는 대화」로 들어갔다 — 최근 잡 400건 속 MCP 과제 가운데
                    #   74건이 대표 대화방 하나에 쌓였고, 앞 과제·대표 대화가 문맥으로 샜다: 「example.com 열어 제목」에
                    #   「깃허브 조직 생성에는 세 가지 정보가…」(앞 과제)로 답했다.
                    #   이어 하기는 따로 방이 필요 없다 — 멈춘 과제는 같은 잡이 제 방을 들고 잇고, 덜 끝난 과제는
                    #   결과의 resume(읽은 주소·남은 칸)이 새 과제 문장에 실려 온다. 화면은 대화가 달라도 MCP 잡을 따라간다.
                    "session_id": f"mcp-{uuid.uuid4().hex[:12]}",
                }
                if arguments.get("skill"):
                    body["skill"] = str(arguments["skill"])[:80]
                # 코드 일의 칸 둘 — 저장소와 확인 명령. 서버가 가지를 만들고 그 명령으로 끝을 가른다(`delegated_branch`).
                if str(arguments.get("repo") or "").strip() or str(arguments.get("check") or "").strip():
                    body["delegated_repo"] = str(arguments.get("repo") or "").strip()[:1000]
                    body["delegated_check"] = str(arguments.get("check") or "").strip()[:1000]
                # 돌려받아야 할 것 — 끝난 판의 요약이 항목마다 채웠는지 확인하고, 밝힌 연락처는 정제에서 뺀다(§55-32).
                needs = clean_needs(arguments.get("needs"))
                if needs:
                    body["needs"] = needs
                # ★ 누가 맡겼나 (2026-09-30 대표: 「클로드·코덱스를 동시에 쓰면 누가 손자리를 불렀는지 모른다」).
                #   화면이 그 호스트의 출처 색 이음선과 이름을 두른다 — 이어온 대화와 같은 규칙(tokens.css `--origin-*`).
                if caller:
                    body["caller"] = caller[:80]
                response = await client.post(f"{self.base_url}/v1/chat", json=body, headers=headers)
                if response.status_code == 401:
                    return "손자리가 이 호출을 거부했습니다(토큰 불일치).", True
                if response.status_code >= 400:
                    return f"손자리가 과제를 받지 못했습니다({response.status_code}): {response.text[:400]}", True
                job = response.json()
                return self._dumps({
                    "job_id": str(job.get("id") or ""),
                    "status": "queued",
                    "message": "맡겼습니다. sonjari_task_status 로 결과를 받으세요(한 판에 보통 1~5분).",
                }), False

            job_id = str(arguments.get("job_id") or "").strip()
            if not job_id:
                return "job_id 가 비어 있습니다.", True
            # ★ 클로드 코드는 한 번에 더 오래 기다린다 (2026-10-02 분업 실험 K-Startup 판). 974초 판에서 클로드가 상태를 18번
            #   물었고, 물을 때마다 그때까지의 대화(5~6만 토큰)를 캐시에서 다시 읽었다 — 대기가 곧 비용이었다. 클로드 코드는 MCP 호출을
            #   기본 28시간·stdio 무응답 30분까지 기다린다(code.claude.com/docs/en/mcp). 한도를 확인 안 한 호스트(코덱스·데스크톱)는 그대로.
            ceiling = CLAUDE_CODE_MAX_WAIT_SEC if is_claude_code(caller) else MAX_WAIT_SEC
            try:
                wait = max(0, min(int(arguments.get("wait_sec", ceiling)), ceiling))
            except (TypeError, ValueError):
                wait = ceiling
            deadline = asyncio.get_running_loop().time() + wait
            while True:
                response = await client.get(f"{self.base_url}/v1/jobs/{job_id}")
                if response.status_code == 404:
                    return f"job_id '{job_id}' 를 찾지 못했습니다.", True
                response.raise_for_status()
                job = response.json()
                ahead = None
                if str(job.get("status") or "") == "queued":
                    # 줄을 섰으면 **앞에 몇 개인지** 같이 준다 — 「왜 안 움직이지」를 없앤다.
                    try:
                        listed = (await client.get(f"{self.base_url}/v1/jobs?limit=50&view=summary")).json()
                        created = float(job.get("created_at") or 0)
                        ahead = sum(1 for row in listed
                                    if str(row.get("status")) in ("queued", "running")
                                    and float(row.get("created_at") or 0) < created)
                    except Exception:  # noqa: BLE001 — 줄 길이는 덤이다
                        ahead = None
                live = None
                if str(job.get("status") or "") in ("running", "waiting_approval"):
                    # 진행 중일 때만 — 화면이 보여 주는 「지금 하는 일·시킨 것 n/m」을 호스트 채팅으로 잇는다.
                    try:
                        # ★ 이 문은 토큰을 받는다(api.py). 2026-09-28 까지 토큰 없이 불러 401 이었다 — 진행이 한 번도 안 나갔다.
                        live_response = await client.get(f"{self.base_url}/v1/jobs/{job_id}/live", headers=headers)
                        if live_response.status_code == 200:
                            live = live_response.json()
                    except Exception:  # noqa: BLE001 — 진행 표시는 덤이다. 못 받아도 상태는 나간다
                        live = None
                pending = None
                if str(job.get("status") or "") == "waiting_approval":
                    # 무엇을 기다리는지 — 질문 카드면 질문과 선택지를 호스트 채팅에 그대로 전한다(2026-09-30).
                    try:
                        approvals = await client.get(f"{self.base_url}/v1/approvals?status=pending&limit=20",
                                                     headers=headers)
                        if approvals.status_code == 200:
                            pending = next((row for row in approvals.json()
                                            if str(row.get("job_id") or "") == job_id), None)
                    except Exception:  # noqa: BLE001 — 못 받아도 「승인 대기」는 나간다
                        pending = None
                summary = summarize_job(job, ahead=ahead, live=live, pending_approval=pending)
                # ★ 코드 일을 맡겼는데 코드 모델이 작으면 한 줄(2026-10-01 밤 대표) — 판정은 결정론(`hf_catalog.model_hint`).
                #   작은 모델에게 「너보다 나은 모델이 뭐냐」를 묻지 않는다 — 그럴듯하게 지어낼 수 있다.
                if summary["status"] not in ("running", "needs_approval"):
                    from .hf_catalog import model_hint

                    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
                    asked = str(payload.get("prompt") or "")
                    if asked:
                        _chat, _code, _budget, upgrade = await self._model_fit()
                        hint = model_hint(asked, upgrade)
                        if hint:
                            summary["model_hint"] = hint
                if summary["status"] not in ("running", "needs_approval") or asyncio.get_running_loop().time() >= deadline:
                    return self._dumps(summary, indent=2), summary["status"] in ("failed", "cancelled")
                await asyncio.sleep(2.0)
        except httpx.RequestError as exc:
            return f"손자리에 연결하지 못했습니다({self.base_url}). 손자리가 실행 중인지 확인해 주세요. 원인: {exc}", True

    async def call(self, name: str, arguments: dict[str, Any], *, caller: str = "") -> tuple[str, bool]:
        """도구를 부르고 (사람이 읽을 글, 오류인가) 를 돌려준다. `caller` 는 이 연결을 연 호스트의 이름(clientInfo).

        영어 연결이면 **우리가 만든 오류 문장**만 영어로 바꾼다. 성공한 도구 결과는 사용자의 자료라 그대로 둔다.
        """
        text, failed = await self._call(name, arguments, caller=caller)
        if failed and not text.lstrip().startswith(("{", "[")):
            text = self.say(text)
        return text, failed

    async def _call(self, name: str, arguments: dict[str, Any], *, caller: str = "") -> tuple[str, bool]:
        # 옛 이름(ontelic_task 등)으로 불러도 받는다 — 옛 지침을 들고 있는 호스트가 한동안 그 이름을 부른다(이름 2단계).
        name = LEGACY_TOOL_NAMES.get(name, name)
        if name == GUIDE_TOOL["name"]:
            from .guide_skill import render_skill

            try:
                tools = await self.list_tools()
            except Exception:  # noqa: BLE001 — 도구 목록을 못 받아도 사용법 본문은 준다
                tools = [localized_tool(tool, self.lang) for tool in DELEGATION_TOOLS]
            # 이 PC 의 모델에 맞춘 「맡길 일 / 직접 할 일」(2026-10-01 밤 대표) — 모든 PC 에 같은 문장을 박지 않는다.
            return render_skill(tools, lang=self.lang) + self.say(await self._model_fit_note()), False
        if name in (TASK_TOOL["name"], STATUS_TOOL["name"]) and os.environ.get("JARVIS_MCP_DELEGATION", "1") != "0":
            return await self._delegate(name, arguments or {}, caller=caller)
        if not await self._is_allowed(name):
            return (
                f"'{name}' 은 이 연결로 쓸 수 없습니다. 되돌릴 수 없는 동작(메일 발송·"
                "일정 삭제·발행·업로드·프로그램 실행)은 Sonjari 창에서만 실행되며, "
                "승인 카드도 그 화면에 뜹니다.\n"
                "다른 도구로 우회하려 하지 말고, 사용자에게 손자리 창에서 직접 해 달라고 알리세요.",
                True,
            )
        client = await self._http()
        try:
            response = await client.post(
                f"{self.base_url}/v1/tools/execute",
                json={"name": name, "arguments": arguments or {}},
                headers={"X-JARVIS-TOKEN": self.token},
            )
        except httpx.RequestError as exc:
            # 자비스가 안 떠 있으면 여기로 온다. 무엇을 해야 하는지 말해 준다 —
            # "연결 실패"만 보면 모델은 도구가 고장난 줄 알고 지어내기 시작한다.
            return (
                f"손자리에 연결하지 못했습니다({self.base_url}). "
                f"손자리가 실행 중인지 확인해 주세요. 원인: {exc}",
                True,
            )
        if response.status_code == 401:
            return (
                "손자리가 이 호출을 거부했습니다(토큰 불일치). JARVIS_CONTROL_TOKEN 이 "
                "손자리 쪽 .env 와 같은 값인지 확인해 주세요.",
                True,
            )
        if response.status_code >= 400:
            return f"손자리가 오류를 돌려줬습니다({response.status_code}): {response.text[:400]}", True

        payload = response.json()
        status = str(payload.get("status") or "")
        if status == "approval_required":
            return self.say(_APPROVAL_HELP), False
        if not payload.get("ok"):
            return f"실패({status or 'error'}): {payload.get('error') or ''}", True

        result = payload.get("result")
        if isinstance(result, str):
            return result, False
        return json.dumps(result, ensure_ascii=False, indent=2, default=str), False


def build_server(bridge: JarvisMcpBridge) -> Any:
    """MCP 서버 객체.

    SDK import 를 함수 안에 두는 것은 일부러다 — 이 모듈의 나머지(필터·브리지)는
    SDK 없이도 테스트할 수 있어야 하고, 실제로 단위 테스트가 그렇게 돈다.

    콜백(`on_list_tools`/`on_call_tool`) 방식을 쓰는 이유: 우리 도구는 파이썬 함수가
    아니라 **런타임이 돌려주는 목록**이라 시그니처에서 스키마를 뽑을 수가 없다.
    고수준 `@tool` 데코레이터는 함수에서 스키마를 유추하므로 여기서는 못 쓴다.
    """
    from mcp.server.lowlevel import Server
    from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

    async def on_list_tools(context: Any, params: Any) -> Any:
        del context, params
        return ListToolsResult(
            tools=[
                Tool(
                    name=str(tool["name"]),
                    description=describe(tool),
                    input_schema=dict(
                        tool.get("parameters") or {"type": "object", "properties": {}}
                    ),
                    meta=ALWAYS_LOAD_META if str(tool["name"]) in ALWAYS_LOAD else None,
                )
                for tool in await bridge.list_tools()
            ]
        )

    async def on_call_tool(context: Any, params: Any) -> Any:
        text, failed = await bridge.call(params.name, dict(params.arguments or {}), caller=caller_of(context))
        # 실패도 예외가 아니라 `is_error` 로 돌려준다. 예외로 던지면 클라이언트가
        # 프로토콜 오류로 처리해 **모델이 이유를 못 본다** — 무엇이 잘못됐는지 알아야
        # 다음 수를 정할 수 있고, 모르면 지어내기 시작한다.
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=failed)

    return Server(
        MCP_SERVER_NAME,
        instructions=INSTRUCTIONS_EN if bridge.lang == "en" else INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def _run() -> None:
    from mcp.server.stdio import stdio_server

    from .mcp_language import pick_language

    base_url = os.environ.get("JARVIS_BASE_URL", DEFAULT_BASE_URL)
    token = resolve_token()
    bridge = JarvisMcpBridge(
        base_url=base_url,
        token=token,
        tool_filter=ToolFilter.from_env(),
        # 연결을 켤 때 한 번 정한다 — 앱에서 고른 화면 언어, 손자리가 아직 안 떴으면 윈도우 언어(`mcp_language`).
        lang=pick_language(base_url, token),
    )
    if not bridge.token:
        # stderr 로 낸다. stdout 은 JSON-RPC 전용이라 한 글자라도 섞이면 프로토콜이 깨진다.
        print(
            "[alture-jarvis] JARVIS_CONTROL_TOKEN 이 비어 있습니다 — 모든 도구 호출이 401 로 거부됩니다.",
            file=sys.stderr,
        )
    server = build_server(bridge)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        await bridge.aclose()


def caller_of(context: Any) -> str:
    """이 연결을 연 호스트의 이름 — MCP `initialize` 의 clientInfo(title 이 있으면 그것, 없으면 name).

    예: 클로드 코드 `claude-code`, 코덱스 `codex-mcp-client`, 커서 `cursor-vscode`. 못 읽으면 빈 문자열 —
    이름이 없다고 과제를 막지 않는다(화면은 「바깥 AI」로만 적는다).
    """
    try:
        params = context.session.client_params
        info = getattr(params, "client_info", None) if params is not None else None
    except Exception:  # noqa: BLE001 — 세션 모양이 달라도 과제는 간다
        return ""
    if info is None:
        return ""
    return str(getattr(info, "title", None) or getattr(info, "name", "") or "").strip()[:80]


def resolve_token() -> str:
    """환경변수가 먼저, 없으면 **자비스 토큰 파일**(`JARVIS_TOKEN_FILE`).

    ★ 2026-09-14 (P5): 공개 제품에서는 클로드·코덱스·커서 설정 세 곳에 토큰을 복사하지 않는다.
      복사하면 비밀이 퍼지고, 토큰을 바꾸는 순간 설정과 갈라져 401 로 조용히 막힌다(08-08 사고).
      설정에는 파일 **경로**만 두고 매번 파일에서 읽는다.
    """
    token = os.environ.get("JARVIS_CONTROL_TOKEN", "").strip()
    if token:
        return token
    path = os.environ.get("JARVIS_TOKEN_FILE", "").strip()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
