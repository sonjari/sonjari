"""Claude(바깥 MCP 클라이언트)가 온텔릭에게 일을 **통째로** 맡기는 문 (2026-09-16, 인수인계 H1).

## 왜 있나

MCP 로 내보낸 도구는 `browser_click`·`browser_fill` 같은 낮은 단위뿐이었다. 그러면 Claude 가 손 40개를
직접 부려야 하고, 걸음마다 누적 전사를 다시 읽으니 토큰이 걸음 수의 제곱으로 는다(메모리 「토큰 48배」).
여기서는 과제 한 줄을 온텔릭 잡으로 넣고, 결과만 받아 간다.

## ★ 위험 — 싼 쪽이 창작한다

같은 메모리의 두 번째 줄: 위임 3판 중 2판이 없는 숫자를 지어냈다. 그래서 결과를 그대로 넘기지 않는다.
**답과 만든 파일에 적힌 숫자 중 도구가 준 적 없는 것**을 세서 같이 싣고, 하나라도 있으면
`needs_review` 로 내보낸다 — Claude 가 사용자에게 전하기 전에 확인하게.

## 두 호출로 나눈 이유

한 판은 몇 분 걸린다. MCP 호출 하나가 그동안 매달리면 클라이언트가 끊거나 사용자가 멈춘 줄 안다.
시작(`sonjari_task`)은 즉시 잡 번호를 돌려주고, 조회(`sonjari_task_status`)는 최대 `wait_sec` 만 기다린다.

이 모듈은 HTTP 를 모른다 — 잡 사전을 받아 요약만 한다(단위 시험이 런타임 없이 돈다).
"""

from __future__ import annotations

import re
import time
from typing import Any

from .brand import NAME, NAME_KO
from .check_notes import SUMMARY_LINE_HEAD, answer_for_receiver
from .evidence import WRITE_EFFECTS, code_string_values, numbers_claimed_in, unsupported_numbers
from .outbound import check_needs, clean_needs, receipt, refine
from .url_privacy import safe_url

__all__ = ["TASK_TOOL", "STATUS_TOOL", "GUIDE_TOOL", "STORY_TOOL", "DELEGATION_TOOLS", "summarize_job", "partial_work",
           "host_context_kept_out", "MAX_WAIT_SEC", "CLAUDE_CODE_MAX_WAIT_SEC", "is_claude_code"]

MAX_WAIT_SEC = 50
#: 클로드 코드는 한 번에 이만큼까지 기다린다 — MCP 호출을 기본 28시간·stdio 무응답 30분까지 기다려 준다(code.claude.com/docs/en/mcp).
#: 2026-10-02 분업 실험: 50초씩 18번 물으며 매번 대화 5~6만 토큰을 다시 읽었다. 한도를 확인 안 한 호스트는 MAX_WAIT_SEC 그대로.
CLAUDE_CODE_MAX_WAIT_SEC = 240


def is_claude_code(caller: str) -> bool:
    """이 연결을 연 호스트가 클로드 코드인가 — MCP clientInfo 의 이름(`claude-code`)·제목(`Claude Code`)."""
    name = str(caller or "").strip().lower().replace("-", " ")
    return name == "claude code"


_ANSWER_LIMIT = 6000
#: 답 끝에 **우리가 붙인** 대조 칸의 머리(`plan` 의 대조표 · 한국어 「시킨 것 대조」 · 영어 「Checklist」).
#: ★ 2026-10-24: 사람이 시킨 판(디스코드 다리)은 덩어리 대신 한 줄(`plan.summary_line`)을 받는다 — 그 줄의 「3개 중 2개」도 하네스가 센 것이다.
_OUR_CHECKLIST = re.compile(r"\n\s*(?:\*\*(?:시킨 것 대조|Checklist)\*\*|" + SUMMARY_LINE_HEAD.pattern + ")")
_TERMINAL = {"completed", "failed", "cancelled"}

TASK_TOOL: dict[str, Any] = {
    "name": "sonjari_task",
    "description": (
        f"{NAME_KO}에게 과제 하나를 통째로 맡깁니다. {NAME_KO}는 이 PC 에서 도는 로컬 AI 로, 사용자의 실제 크롬"
        "(로그인된 사이트 포함)·파일·워드/엑셀/한글 문서를 직접 다룹니다. 예: 「사람인에서 서울 마케팅 공고 3개 찾아 "
        "엑셀로 정리」, 「내 문서의 계약서 두 개 비교해 요약 문서로」.\n"
        "즉시 job_id 를 돌려줍니다. 결과는 sonjari_task_status 로 받으세요.\n"
        "과제에는 무엇을 · 어디서 · 어떤 파일로 받을지를 한 문장에 담으세요. 낮은 단위 도구(browser_*)를 여러 번 "
        "부르는 것보다 이 도구 한 번이 빠르고 토큰이 적게 듭니다.\n"
        # ★ 2026-10-15 가격 판: 맡기기 팔이 놓친 9줄 중 6줄이 「내 작업 폴더에 저장해」를 받고 승인 카드 앞에서 멈춘 것이었다.
        #   바깥 AI 는 자기 작업 폴더를 적는 것이 자연스럽다 — 그 폴더가 손자리에게는 허락 안 된 자리라는 것을 몰랐다.
        "저장 폴더는 적지 않는 것이 기본입니다 — 그러면 손자리 결과물 폴더(내 문서 아래)에 저장되고 결과의 files 로 경로가 옵니다. "
        "다른 폴더를 적으면 손자리 창에서 사람이 승인해야 끝납니다(사람이 자리에 없으면 그대로 기다립니다)."
    ),
    "risk_level": "L1",
    "parameters": {
        "type": "object",
        "properties": {
            # ★ 2026-10-19: 전에는 「(한국어 권장)」이었다 — 영어로 시킨 클로드 코드가 그 말을 따라 과제를 한국어로 넘겼다.
            #   손자리 모델은 두 언어를 다 읽는다. 사용자의 말로 적게 해야 답도 사용자의 말로 돌아온다.
            "task": {"type": "string", "description": (
                "맡길 과제 한 문장 — 사용자가 당신과 쓰는 언어로 적으세요. 최대 4,000자(넘으면 보내지 않고 돌려보냅니다).")},
            "skill": {"type": "string", "description": "지목할 스킬 이름(선택, skill_list 로 확인). 모르면 비워 두세요."},
            # ★ 코드 일을 맡기는 칸 둘 (2026-10-09). 과제 글에서 짐작하지 않고 **칸으로** 받는다.
            "repo": {"type": "string", "description": (
                "코드 일을 맡길 때만: 이 PC 의 git 저장소(또는 그 안의 폴더) 절대 경로. 주면 그 저장소의 **새 가지**를 따로 꺼내 "
                "거기서만 고칩니다 — 원래 폴더는 건드리지 않습니다. 커밋 안 한 변경(추적 중인 파일)은 같이 가져갑니다. "
                "끝나면 결과의 branch 에 바뀐 파일과 가져가는 명령이 옵니다. check 없이 repo 만 주고 과제 글에 「고치지 마 · "
                "읽고 요약만」이라고 적으면, 고치지 않고 관련 코드를 이 PC 에서 읽어 파일 · 함수 · 줄로 요약해 줍니다.")},
            "check": {"type": "string", "description": (
                "repo 와 같이: 끝났는지 가르는 **확인 명령** 한 줄(그 폴더에서 실행 · 종료 코드 0 이면 통과). "
                "예: python -m pytest -q tests/test_x.py. 주면 과제 글에서 요구를 짐작하지 않고 이 명령으로 끝을 가릅니다 — "
                "통과할 때까지 고치고, 못 하면 못 했다고 돌려줍니다.")},
            # ★ 돌려받아야 할 것 (2026-10-15 · 전략안 §55-32). 밝히면 손자리가 결과에 그 항목이 채워졌는지 확인하고,
            #   밝힌 연락처(전화 · 메일)는 정제에서 빼고 내보낸다. 안 밝히면 지금처럼 답 전체 — 연락처 모양은 가려서.
            "needs": {"type": "array", "items": {"type": "string"}, "maxItems": 12, "description": (
                "선택: 결과로 꼭 돌려받아야 할 항목 이름들(예: [\"상품 이름\", \"가격\", \"주소\"]). 주면 결과의 needs 에 항목마다 "
                "채웠는지(met)가 옵니다 — true 는 그 이름의 칸 · 제목 · 「이름: 값」 줄에 값이 있음, false 는 그 자리가 비어 있음, "
                "null 은 그 이름의 자리를 못 찾아 확인 못 함(비었다는 뜻이 아님 — 답 본문을 직접 보세요). "
                "답에서 주민번호 · 카드 번호 · 비밀 키는 늘 가리고, 전화번호 · 메일 주소는 여기에 "
                "밝혔을 때만(예: \"연락처\") 내보냅니다.")},
        },
        "required": ["task"],
    },
}

STATUS_TOOL: dict[str, Any] = {
    "name": "sonjari_task_status",
    "description": (
        "sonjari_task 로 맡긴 과제의 진행·결과를 받습니다. 끝나지 않았으면 최대 wait_sec 초 기다린 뒤 지금 상태를 "
        "돌려줍니다 — 그러면 다시 부르세요.\n"
        "status 가 needs_review 면 답이나 파일에 **도구가 준 적 없는 숫자**(unsupported_numbers)가 있다는 뜻입니다. "
        "그 숫자를 사실로 전하지 말고 사용자에게 확인이 필요하다고 알리세요.\n"
        "needs_approval 이면 되돌릴 수 없는 동작이 손자리 창의 승인 카드를 기다리는 중입니다 — 사용자에게 알리세요.\n"
        "resume 이 있으면 과제가 덜 끝난 것입니다. resume.evidence 의 주소는 이미 읽은 것이니 **다시 열지 말고**, "
        "resume.next 에 적힌 남은 칸만 이어서 하세요.\n"
        "failed·cancelled 여도 files·sources·resume 이 있으면 실패하기 전까지 한 일이니 버리지 말고 쓰세요. "
        "unverified_claim 은 검증되지 않은 마지막 말이라 사실로 전하지 마세요.\n"
        "running 이면 progress.doing(지금 하는 일)과 progress.requested(시킨 것 n/m)를 사용자에게 한 줄로 전하세요 — "
        "예: 「지금 사람인에서 공고를 읽는 중 — 시킨 것 2/3」. 남은 시간은 예측해 주지 않습니다(맞는지 재 본 적이 없습니다) — "
        "지어 말하지 마세요.\n"
        "cost 는 이 심부름을 이 PC 에서 처리한 기록입니다(걸린 초·로컬에서 읽은 페이지 수·센 값에서 나온 하한과 그 근거). "
        "사용자에게 설명할 때 쓸 수 있고, 하한을 말할 때는 basis 를 같이 말하세요. "
        "cost.host_context_kept_out.tokens_at_least 는 센 값에서 나온 **하한**입니다 — 「최소 N토큰 분량의 본문을 이 PC 에서 읽어 "
        "이 대화에 싣지 않았다」고 전하고, 「약」·「배」로 부풀리지 마세요. 시간을 아꼈다는 말은 하지 마세요(로컬은 더 느릴 수 있습니다)."
    ),
    "risk_level": "L1",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "sonjari_task 가 돌려준 job_id"},
            "wait_sec": {"type": "integer", "minimum": 0, "maximum": CLAUDE_CODE_MAX_WAIT_SEC,
                         "description": (f"끝날 때까지 기다릴 최대 초. 비우면 클로드 코드는 {CLAUDE_CODE_MAX_WAIT_SEC}초, "
                                         f"다른 앱은 {MAX_WAIT_SEC}초(그보다 크게 줘도 그 앱의 상한으로 줄입니다). "
                                         "자주 묻지 말고 비워 두세요 — 물을 때마다 대화 전체를 다시 읽습니다")},
        },
        "required": ["job_id"],
    },
}

DELEGATION_TOOLS: tuple[dict[str, Any], ...] = (TASK_TOOL, STATUS_TOOL)

# ★ 2026-09-17 제품 요청: Claude Desktop 은 스킬을 앱이 넣을 수 없다(업로드·조직 배포뿐 — 공식 문서). 채팅은 PC 폴더의
#   스킬 파일도 스스로 못 읽는다. 그래서 **연결 자체가 가이드를 들고 간다** — 안내문이 「처음엔 이걸 불러 읽으라」고 하고,
#   이 도구가 Claude Code 에 넣는 SKILL.md 와 **같은 본문**을 돌려준다(두 벌이면 갈린다 — `guide_skill.render_skill`).
GUIDE_TOOL: dict[str, Any] = {
    "name": "sonjari_guide",
    "description": ("손자리 사용법 가이드(과제를 어떻게 적어 맡기는지·결과를 어떻게 전하는지·막히면 무엇을 하는지)를 돌려준다. "
                    "처음 손자리에게 일을 맡기기 전에 한 번 불러 읽으세요. 읽기만 하고 아무것도 바꾸지 않습니다."),
    "parameters": {"type": "object", "properties": {}},
    "risk_level": "L0",
    "enabled": True,
}

# ★ 2026-10-21 서기(`scribe.py`). 클로드 대화가 잘리면 앞에서 정한 것 · 버린 것 · 남은 일이 요약에서 빠진다(그날 밤 실측:
#   열 덩어리 앞의 핵심 결정 12개 중 마지막 요약에 0개). 손자리가 노는 시간에 대화 기록에서 초안 카드를 쌓아 두고,
#   클로드는 이 문으로 꺼내 읽는다. 줄마다 기록의 줄 번호와 원문 인용이 붙어 있어 클로드가 직접 확인할 수 있다.
STORY_TOOL: dict[str, Any] = {
    "name": "sonjari_story",
    "description": ("손자리 서기가 이 PC 의 클로드 코드 대화 기록에서 뽑아 둔 「이야기 카드」(정한 것 · 버린 것과 까닭 · 남은 일 · "
                    "사람이 거듭 고쳐 준 것)를 돌려준다. 대화가 잘린 뒤 이어 갈 때나 「그 중간이 뭐였지」 할 때 부르세요. "
                    "줄마다 기록의 줄 번호와 원문 인용이 붙어 있습니다 — 초안이니 중요한 줄은 그 자리를 직접 확인하세요. "
                    "읽기만 하고 아무것도 바꾸지 않습니다."),
    "parameters": {"type": "object", "properties": {
        "session": {"type": "string", "description": "이 세션 것만(대화 기록 파일 이름의 앞부분). 비우면 전부."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 120, "description": "최근 몇 줄까지(기본 30)."},
    }},
    "risk_level": "L0",
    "enabled": True,
}


# ★ 영어 연결용 설명 (2026-10-19). 이름 · 칸 · 스키마는 한국어판과 **같은 것**을 쓴다 — 설명 글만 바꿔 끼운다.
#   한국어판의 말을 더하거나 빼지 않는다(같은 규칙이 두 언어로 갈리면 안 된다 — `test_mcp_language_1019`).
_EN_DESCRIPTIONS: dict[str, dict[str, str]] = {
    TASK_TOOL["name"]: {
        "": (
            "Hand one whole task to Sonjari, a local AI running on this PC. It works in the user's real Chrome "
            "(including logged-in sites), files, and Word/Excel/Hangul documents. Examples: \"find 3 marketing jobs in "
            "Seoul on a job board and put them in a spreadsheet\", \"compare the two contracts in my Documents and write "
            "a summary\".\n"
            "Returns a job_id right away. Get the result with sonjari_task_status.\n"
            "Put what, where, and which file you want back in one sentence. One call here is faster and uses fewer "
            "tokens than calling low-level tools (browser_*) many times.\n"
            "Leave the save folder out by default — results go to Sonjari's output folder (under Documents) and the "
            "path comes back in files. If you name another folder, a person has to approve it in the Sonjari window "
            "(if nobody is there, the job waits)."
        ),
        "task": ("The task in one sentence — write it in the language the user is using with you. Up to 4,000 characters "
                 "(longer tasks are sent back, not cut)."),
        "skill": "Optional skill name to use (see skill_list). Leave empty if unsure.",
        "repo": (
            "Code jobs only: absolute path of a git repository on this PC (or a folder inside it). Sonjari checks out "
            "a **new branch** of it separately and changes only that — the original folder is untouched. Uncommitted "
            "changes to tracked files come along. When done, branch in the result lists the changed files and the "
            "commands to take them. Give repo without check and say \"don't change anything, just read and summarize\" "
            "in the task, and Sonjari reads the relevant code on this PC and summarizes it by file, function and line "
            "without editing."
        ),
        "check": (
            "With repo: one **check command** that decides when the job is done (run in that folder; exit code 0 "
            "passes). Example: python -m pytest -q tests/test_x.py. With it, Sonjari does not guess requirements from "
            "the task text — it fixes until the command passes, or reports that it could not."
        ),
        "needs": (
            "Optional: names of items you must get back (e.g. [\"product name\", \"price\", \"address\"]). The result's "
            "needs then says, item by item, whether it was filled (met): true means a column, heading or \"name: value\" "
            "line with that name has a value, false means that place is empty, and null means no place with that name "
            "was found so it could not be checked (not that it is empty — read the answer itself). "
            "National ID numbers, card numbers and secret "
            "keys are always masked; phone numbers and email addresses are only returned when you name them here "
            "(e.g. \"contact\")."
        ),
    },
    STATUS_TOOL["name"]: {
        "": (
            "Get the progress or result of a task handed off with sonjari_task. If it is not finished, it waits up "
            "to wait_sec seconds and returns the current state — then call it again.\n"
            "status needs_review means the answer or a file contains **numbers no tool ever returned** "
            "(unsupported_numbers). Do not pass those on as fact; tell the user they need checking.\n"
            "needs_approval means an irreversible action is waiting for the approval card in the Sonjari window — "
            "tell the user.\n"
            "If resume is present, the task is not finished. The addresses in resume.evidence were already read — "
            "**do not open them again**; continue only with what resume.next lists.\n"
            "Even when failed or cancelled, files, sources and resume are work done before the failure — use them, "
            "do not throw them away. unverified_claim is an unchecked last statement; do not pass it on as fact.\n"
            "While running, pass progress.doing (what it is doing now) and progress.requested (requested n/m) to the "
            "user in one line — e.g. \"reading job posts on the site now, requested 2/3\". It does not predict time "
            "left (that has never been measured) — do not make one up.\n"
            "cost is the record of this errand on this PC (seconds taken, pages read locally, a lower bound from "
            "counted values and its basis). You can use it when explaining to the user; when you state the lower "
            "bound, state its basis too. cost.host_context_kept_out.tokens_at_least is a **lower bound** from counted "
            "values — say \"at least N tokens of page text were read on this PC and kept out of this conversation\", "
            "and do not inflate it with \"about\" or \"x times\". Do not claim time was saved (local can be slower)."
        ),
        "job_id": "The job_id returned by sonjari_task",
        "wait_sec": (
            f"Maximum seconds to wait for it to finish. Empty means {CLAUDE_CODE_MAX_WAIT_SEC} s for Claude Code and "
            f"{MAX_WAIT_SEC} s for other apps (larger values are cut to that app's limit). Leave it empty and do not "
            "ask often — every call re-reads the whole conversation."
        ),
    },
    GUIDE_TOOL["name"]: {
        "": (
            "Returns the Sonjari guide (how to write and hand off a task, how to pass on the result, what to do when "
            "stuck). Call it once before handing Sonjari its first task. Read-only; changes nothing."
        ),
    },
    STORY_TOOL["name"]: {
        "": (
            "Returns the \"story cards\" Sonjari's scribe drafted from this PC's Claude Code conversation logs (what was "
            "decided, what was dropped and why, what is left to do, what the person corrected more than once). Call it "
            "when you continue after the conversation was cut, or when you need to recall \"what came in between\". "
            "Each line carries the log's line number and a verbatim quote — they are drafts, so check that spot "
            "yourself for anything important. Read-only; changes nothing."
        ),
        "session": "Only this session (start of the conversation log's file name). Empty means all.",
        "limit": "How many of the most recent lines (default 30).",
    },
}


def localized_tool(tool: dict[str, Any], lang: str) -> dict[str, Any]:
    """도구 사전 하나를 그 언어로 — 영어면 설명 글만 바꾼 **새 사전**(원본은 그대로)."""
    texts = _EN_DESCRIPTIONS.get(str(tool.get("name") or "")) if lang == "en" else None
    if not texts:
        return dict(tool)
    out = dict(tool)
    out["description"] = texts.get("", out.get("description", ""))
    params = out.get("parameters")
    if isinstance(params, dict) and isinstance(params.get("properties"), dict):
        props = {}
        for key, spec in params["properties"].items():
            spec = dict(spec)
            if key in texts:
                spec["description"] = texts[key]
            props[key] = spec
        out["parameters"] = {**params, "properties": props}
    return out


#: 코드가 든 인자 이름 — 계산 상자(`sandbox_run`)로 파일을 만든 판.
_CODE_KEYS = frozenset({"code", "script", "source"})


def _code_strings(code: str) -> list[str]:
    """코드 속 따옴표 안 글자만 — `evidence.code_string_values` (2026-10-02 판 7f437150 에서 생겼고 10-05 에 한 자리로 모았다)."""
    return code_string_values(code)


def _strings(node: Any, out: list[str], depth: int = 0) -> None:
    """쓰기 인자에서 **글자 값만** 모은다. 키 이름·열 너비 같은 구조 숫자는 주장이 아니다."""
    if depth > 6:
        return
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for key, value in node.items():
            if str(key) in _CODE_KEYS and isinstance(value, str):
                out.extend(_code_strings(value))
                continue
            if str(key) == "html" and isinstance(value, str):
                # ★ 장표 HTML(2026-10-25 · `local_make_slide`)은 **보이는 글만** — CSS · 그림 좌표(0.92 · 880 …)가
                #   「도구가 준 적 없는 숫자 9개」로 찍혀 잘 만든 장표 판이 needs_review 가 됐다.
                from .slides import visible_text

                out.append(visible_text(value))
                continue
            _strings(value, out, depth + 1)
    elif isinstance(node, (list, tuple)):
        for value in node[:500]:
            _strings(value, out, depth + 1)


def _is_write(step: dict[str, Any]) -> bool:
    record = step.get("evidence_record") or {}
    return str(record.get("effect") or "") in WRITE_EFFECTS


#: 파일을 만들거나 고치는 손. 실패한 판이 **무엇을 남겼는지** 복원할 때 쓴다.
_PARTIAL_WRITE_TOOLS = frozenset({
    "local_write_file", "local_apply_edit", "local_write_document",
    "local_edit_document", "local_edit_spreadsheet", "local_make_slide",
})


def partial_work(get_step: Any, steps: list[dict[str, Any]]) -> dict[str, list[str]]:
    """실패한 판이 **실패 전에 한 일**(만든 파일 · 읽은 주소)을 걸음 기록에서 복원한다.

    ## 왜 (2026-09-22, 사장님 승인)

    실패한 잡의 요약은 상태와 오류 500자뿐이었다. 그런데 노트북 4B 사다리에서 실패로 끝난 판의 상당수가
    **만든 파일은 채점을 통과했다**(`pat3` 실패 4판 중 3판). 호스트는 「실패」만 받고 쓸 만한 결과를 버린다 —
    위임의 값(호스트 토큰을 아끼는 것)이 실패하는 순간 0 이 된다. 조사 중에 죽은 판도 같다.

    `get_step(번호)` 는 걸음 하나의 전체 기록(`arguments`·`payload`)을 돌려주는 함수다. 목록 줄에는 경로가 없다.
    만든 뒤 **지운 파일**(검증용 임시 스크립트 등)은 뺀다 — 없는 파일을 산출물이라고 하면 안 된다.
    """
    files: list[str] = []
    sources: list[str] = []
    for row in steps:
        if not isinstance(row, dict) or not row.get("ok"):
            continue
        tool = str(row.get("tool") or "")
        try:
            full = get_step(int(row.get("step") or 0)) or {}
        except Exception:  # noqa: BLE001 — 한 걸음이 안 읽혀도 나머지는 복원한다
            continue
        arguments = full.get("arguments") if isinstance(full.get("arguments"), dict) else {}
        payload = full.get("payload") if isinstance(full.get("payload"), dict) else {}
        if tool in _PARTIAL_WRITE_TOOLS:
            path = str(arguments.get("path") or arguments.get("output_path") or "").strip()
            if path and path not in files:
                files.append(path)
        elif tool == "local_delete_file":
            path = str(arguments.get("path") or "").strip()
            if path in files:
                files.remove(path)
        elif tool.startswith("browser_"):
            # 로그인 화면 · 한 번 쓰는 값은 줄여서 내보낸다(`url_privacy` — 2026-10-19 잡 51f35b07 의 구글 계정 고르기 주소).
            url = safe_url(str(payload.get("url") or arguments.get("url") or "").strip())
            if url.startswith("http") and url not in sources:
                sources.append(url)
    return {"files": files[:20], "sources": sources[:20]}


#: 실패 이유 → 호스트가 읽을 한 줄. **지어내지 않는다** — 실제로 그 이유로 끝났을 때만 붙는다.
_STOPPED_WHY = {
    "approval_expired": "승인 카드가 시간 안에 처리되지 않아 취소됐습니다 — 사용자에게 승인 창을 봐 달라고 알리세요.",
    "approval_denied": "사용자가 승인을 거절해 취소됐습니다.",
    "code_budget_exhausted": (
        "정해 둔 시간 안에 검증을 통과하지 못해 멈췄습니다. files 가 있다면 그때까지 만든 것이고 **검증되지 않았습니다** — "
        "열어서 확인하거나 이어서 맡기세요."
    ),
}

#: 제자리여서 접힌 맡긴 코드 판 — 까닭 이름(`agent.not_getting_anywhere`) → 맡긴 쪽이 읽을 한 줄.
_STUCK_WHY = {
    "same_failure": (
        "같은 확인 실패가 되풀이돼 멈췄습니다 — 그대로 다시 맡기면 같은 자리에서 멈춥니다. "
        "마지막 실패 출력을 보고 과제를 더 작게 쪼개거나, 걸린 곳을 직접 고친 뒤 나머지를 맡기세요."
    ),
    "rewriting": (
        "같은 파일을 돌려 보지 않고 거듭 다시 쓰다 멈췄습니다 — 이 일은 지금 모델에 큽니다. "
        "파일 하나·함수 하나 크기로 쪼개 맡기세요."
    ),
    "nothing_new": (
        "한동안 새로 본 것도 고친 것도 돌려 본 것도 없어 멈췄습니다 — 과제에 고칠 자리(파일·함수 이름)를 적어 다시 맡기세요."
    ),
    "step_backstop": "걸음 수 안전망에 닿아 멈췄습니다 — 한 번에 맡기기엔 큰 일입니다. 나눠서 맡기세요.",
}

#: 끝내지 못한 판이 대화에 남기는 한 줄의 앞머리. (한국어, 영어)
_UNFINISHED_LEAD = {
    "cancelled": ("이 작업은 도중에 멈췄습니다 — 끝까지 가지 못했습니다.", "This task was stopped partway — it did not finish."),
    "code_budget_exhausted": (
        "정해 둔 작업 시간을 다 써서 멈췄습니다 — 검증은 통과하지 못했습니다.",
        "Stopped after using all the allowed working time — verification did not pass.",
    ),
    "coding_verification_missing": (
        "코드는 고쳤지만 마지막 상태를 실행해 확인하지 못한 채 멈췄습니다.",
        "The code was changed, but the task stopped before the final state was run and checked.",
    ),
    "timeout": (
        "모델이 제한 시간 안에 답하지 못해 이 작업을 끝내지 못했습니다.",
        "The model did not answer within the time limit, so this task did not finish.",
    ),
    "other": ("이 작업은 끝내지 못했습니다.", "This task did not finish."),
}


def unfinished_turn_note(
    error: str, *, cancelled: bool, files: list[str], sources: list[str], last_failure: str = "", english: bool = False
) -> str:
    """끝내지 못한 판(실패·멈춤)이 **대화에 남기는 한 줄**. 모델을 부르지 않는다 — 걸음 기록에 있는 것만 적는다.

    ## 왜 (2026-10-04 새벽)

    운영 기록에서 실패한 실제 판 84개·멈춘 판 129개 가운데 **대화에 남은 것이 0개**였다. 질문과 답은 판이 끝날 때만
    저장됐기 때문이다. 화면은 「이어서 해줘라고 보내면 이어갑니다」라고 안내하는데, 다음 판은 앞 판의 **질문조차** 몰랐다.
    코드 판이 22분을 쓰고 멈추면 사람에게는 빨간 한 줄만 남았다(대표: 「하단에 새빨간 에러」).

    그렇다고 실패를 「완료」로 바꾸지 않는다 — 상태는 실패·멈춤 그대로다(눈금이 안 바뀐다). 지어내지도 않는다:
    만든 파일은 **검증되지 않았다**고 적고, 걸린 자리는 도구가 낸 말을 그대로 옮긴다.
    """
    lang = 1 if english else 0
    name = str(error or "").strip()
    if cancelled:
        key = "cancelled"
    elif name in _UNFINISHED_LEAD:
        key = name
    elif name.startswith("timed out") or "timeout" in name.lower():
        key = "timeout"
    else:
        key = "other"
    parts = [_UNFINISHED_LEAD[key][lang]]
    shown = [str(path) for path in files if str(path).strip()][:6]
    if shown:
        more = len([path for path in files if str(path).strip()]) - len(shown)
        listed = ", ".join(shown) + ((f" (+{more})" if english else f" 외 {more}개") if more > 0 else "")
        parts.append(
            f"Files written so far (not verified): {listed}." if english else f"그때까지 만든·고친 파일(검증되지 않음): {listed}."
        )
    if sources:
        parts.append(f"Pages read: {len(sources)}." if english else f"읽은 주소 {len(sources)}곳.")
    stuck = " ".join(str(last_failure or "").split())[:160]
    if stuck and not cancelled:
        parts.append(f"Last thing that failed: {stuck}" if english else f"마지막으로 걸린 것: {stuck}")
    parts.append('Send "continue" to pick up from here.' if english else "「이어서 해줘」라고 보내면 여기서 이어갑니다.")
    return "(" + " ".join(parts) + ")"


#: 진행 중인 작업이 이 시간을 넘으면 호스트에게 「오래 걸린다」고 알린다. 판단은 호스트가 한다(우리는 자르지 않는다).
_LONG_RUNNING_SEC = 600


def _failure_report(job: dict[str, Any], result: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    """실패·취소된 잡이 **어디까지 갔는가**. 상태와 오류만 주면 호스트는 남은 일을 버린다."""
    partial = result.get("partial") if isinstance(result.get("partial"), dict) else {}
    files = [str(p) for p in (partial.get("files") or [])][:20]
    # 저장된 `partial` 은 이 고침 전에 쌓인 것일 수 있다 — 나가는 자리에서 한 번 더 줄인다(`url_privacy`).
    sources = list(dict.fromkeys(safe_url(str(u)) for u in (partial.get("sources") or [])))[:20]
    diagnosis = result.get("diagnosis") if isinstance(result.get("diagnosis"), dict) else {}
    error = str(job.get("error") or result.get("error") or "")
    report: dict[str, Any] = {}
    if files:
        report["files"] = files
    if sources:
        report["sources"] = sources
    workspace = str((job.get("payload") or {}).get("code_workspace") or "")
    if workspace and files:
        report["workspace"] = workspace  # files 의 상대 경로가 어디 기준인지

    notes: list[str] = []
    if result.get("cancelled"):
        # ★ 사람이 멈춘 판(2026-09-30 e7dd3831). 「실패(이유 미상)」가 아니다. 다만 끝까지 가지 못해 **답·파일의 숫자 검사를
        #   안 거쳤다** — 그 판의 엑셀은 5행 중 1행만 원문과 맞았다. 파일을 사실로 옮기지 않게 먼저 말한다.
        notes.append(
            f"사용자가 판을 멈췄습니다. files·sources 는 멈추기 전까지 한 일이고, **끝까지 검사하지 않았습니다** — "
            "파일의 숫자·내용은 sources 원문으로 확인하기 전에는 사실로 전하지 마세요."
            if files else "사용자가 판을 멈췄습니다(만든 파일 없음)."
        )
    elif error == "coding_verification_missing":
        if files:
            notes.append(
                "파일은 만들었지만 **검증(테스트·실행 확인)을 끝내지 못해** 멈췄습니다. files 는 검증되지 않은 결과입니다 — "
                "열어서 확인하거나, 검증만 다시 맡기세요."
            )
        else:
            notes.append("검증할 결과를 만들지 못한 채 멈췄습니다(만든 파일 없음).")
    elif error in _STOPPED_WHY:
        notes.append(_STOPPED_WHY[error])
    elif files or sources:
        notes.append(f"{NAME_KO}가 실패했습니다({error or '이유 미상'}). files·sources 는 실패하기 전까지 한 일입니다.")

    if diagnosis:
        stopped: dict[str, Any] = {}
        for key in ("verified", "mutated", "coding_pushbacks"):
            if key in diagnosis:
                stopped[key] = diagnosis[key]
        if stopped:
            report["stopped"] = stopped
        claim = str(diagnosis.get("final_answer") or "").strip()
        if claim:
            # ★ 이것은 **모델이 마지막에 한 말**이다. 검증에 실패한 판의 마지막 말은 「완료했습니다」인 경우가 많다.
            report["unverified_claim"] = claim[:600] + ("…" if len(claim) > 600 else "")
            notes.append("unverified_claim 은 손자리가 마지막에 한 말입니다 — 검증되지 않았으니 사실로 전하지 마세요.")

    if notes:
        report["message"] = " ".join(notes)
    resume = _resume(result.get("agent_trace") or {}, steps, sources, files)
    if resume is not None:
        report["resume"] = resume
    return report




#: 글자 수 → 토큰 수 **하한**을 만드는 나눗수.
#:
#: 2026-09-22 실측(Qwen3.6 토크나이저, 위키 본문 9,000자): 한글 토큰당 **1.66~1.72자** · 영어 **4.43자**.
#: 「최소 N토큰」이 **어떤 본문에서도 참**이려면 가장 큰 쪽(영어)보다 크게 나눠야 한다 → 4.5.
#: 한글 본문이면 실제 토큰은 이보다 **2.6배쯤 더 많다** — 하한이라 일부러 낮게 잡았다.
_CHARS_PER_TOKEN_FLOOR = 4.5


def host_context_kept_out(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """이 심부름에서 **호스트 대화에 안 실린 본문**의 크기 — 하한이다 (2026-09-22, 사장님 지시).

    ## 왜 이 숫자인가

    이전 추정(`host_input_tokens_avoided_estimate`)은 호스트가 직접 했을 때의 실측 두 건을 쪽수로 나눠 곱한 **범위**다.
    밖으로 나가면 「그 숫자가 어디서 나왔나」에 약하다. 이쪽은 **우리가 정확히 센 것**에서 나온다:

      · 로컬에서 읽은 본문의 글자 수(걸음 기록의 `char_count`) — 세는 값이지 추정이 아니다.
      · 그 본문이 호스트 대화에 들어가지 않았다는 것 — 호스트는 답과 요약만 받는다.
      · 글자→토큰 비율은 모델로 잰 값에서 **일부러 낮게** 잡았다(`_CHARS_PER_TOKEN_FLOOR`).

    세지 않는 것: 화면 요소 목록(snapshot)·도구 인자·호스트가 직접 했다면 걸음마다 **다시** 실리는 누적 전사.
    그래서 실제 절감은 이보다 크다. 그 큰 쪽은 「추정」이라는 이름으로 따로 둔다 — 하한과 섞어 말하지 않는다.

    성공한 **읽기**(`effect` 가 `read*`) 이면서 `char_count` 가 있는 걸음만 센다. 없으면 `None`.
    """
    chars = 0
    reads = 0
    for step in steps:
        if not step.get("ok"):
            continue
        if not str((step.get("evidence_record") or {}).get("effect") or "").startswith("read"):
            continue
        raw = (step.get("evidence") or {}).get("char_count")
        try:
            count = int(float(str(raw)))
        except (TypeError, ValueError):
            continue
        if count > 0:
            chars += count
            reads += 1
    if not chars:
        return None
    return {
        "kind": "floor",
        "text_chars": chars,
        "reads": reads,
        "tokens_at_least": int(chars / _CHARS_PER_TOKEN_FLOOR),
        "basis": (
            "이 PC 에서 읽은 본문 글자 수(센 값)를 토큰당 4.5자로 나눈 **하한**입니다. 실측: 한글 본문은 토큰당 약 1.7자라 "
            "실제는 이보다 훨씬 큽니다. 화면 요소 목록과 호스트가 직접 했다면 걸음마다 다시 실리는 누적은 세지 않았습니다."
        ),
    }


def _cost(trace: dict[str, Any], steps: list[dict[str, Any]], sources: list[str]) -> dict[str, Any]:
    """「로컬이라 느리지만 돈이 굳는다」를 **말이 아니라 숫자로** (인수인계 밤 §4-②).

    자비스가 자기 입으로 그 말을 하면 변명이 된다. 숫자를 주고, 말은 호스트가 자기 말투로 한다(§4-③).
    """
    verification = trace.get("verification") or {}
    pages = len(sources)
    cost: dict[str, Any] = {
        "sec": verification.get("elapsed_sec"),
        "local_steps": len(steps),
        "pages_read_locally": pages,
        # 페이지 본문은 이 PC 안에서만 읽혔다 — 호스트 대화로는 답과 요약만 갔다.
        "pages_read_by_host": 0,
    }
    kept = host_context_kept_out(steps)
    if kept is not None:
        cost["host_context_kept_out"] = kept  # 하한 — 밖에 말할 때는 이것을 먼저
    # ★ 2026-09-23: 쪽수 × 9/7 실측으로 곱한 「호스트 입력 토큰 절감 추정」(`host_input_tokens_avoided_estimate`)을 뺐다.
    #   그 9/7 숫자는 캐싱을 끄고 n=1 로 잰 것이라 같은 날 비용 재측정(캐싱 켠 실제 클로드 코드)으로 폐기됐는데,
    #   여기서는 계속 곱해져 나갔다 — 파트너 센터 **로그인 화면 한 장**에 「20만~32만 토큰 절감」, 세 쪽에 「60만~97만」.
    #   밖에 말할 숫자는 우리가 센 **하한**(`host_context_kept_out`) 하나다. 큰 쪽은 재지 않은 것이라 싣지 않는다.
    return cost


def _resume(trace: dict[str, Any], steps: list[dict[str, Any]], sources: list[str],
            files: list[str], completion: str = "") -> dict[str, Any] | None:
    """덜 끝났을 때 **어디까지 갔고 남은 칸이 무엇인가** (인수인계 밤 §4-①).

    「실패했으니 다시 해줘」로 돌려주면 호스트가 처음부터 브라우징한다 — 아낀 토큰이 0 이다
    (4판: 21걸음 돌고 표까지 완성했는데 파일 하나 못 만들었다). 그래서 이미 한 것과 근거를 싣는다.

    ★ `next` 는 **지어내지 않는다.** 계획 층이 「못 채웠다」고 판정한 요구를 그대로 옮긴다.
    """
    verification = trace.get("verification") or {}
    unmet = [item for item in ((verification.get("plan") or {}).get("items") or [])
             if isinstance(item, dict) and not item.get("met")]
    failed = [s for s in steps if not s.get("ok")]
    # ★ 2026-09-16 밤 실측(붙임새 S1 2판): 계획 요구는 다 채웠고 실패 걸음도 없는데 **답 검토에 걸려**
    #   `partial` 이 된 판이 있었다(「본문을 읽지 않은 출처를 분석 근거로 적었습니다(saramin)」).
    #   예전엔 여기서 None 이라 호스트는 「덜 끝났다」만 받고 **왜·어디까지**는 못 받았다 — 빈 칸 하나가
    #   「다 끝남」과 「이유가 계획 밖에 있음」 두 뜻이었다. 그 검토 문구를 **그대로** 싣는다(지어내지 않는다).
    review: list[str] = []
    if str(verification.get("answer_conflict") or "").strip():
        review.append(str(verification["answer_conflict"]).strip())
    if verification.get("reported_shortfall") is True:  # 참/거짓 값이다 — 문자열로 찍지 않는다
        # 개수 미달과 「못 읽음·확인 못 함」은 다른 말이다 — 판 기록이 갈라 적어 준 대로 전한다(옛 기록은 종류가 없어 개수로 읽는다).
        review.append(
            "답 스스로 하지 못한 것(못 찾음·못 읽음·확인 못 함)이 있다고 밝혔습니다."
            if verification.get("reported_shortfall_kind") == "not_done"
            else "답 스스로 요구한 개수에 못 미쳤다고 말했습니다."
        )
    # 답의 말이 아니라 손자리가 걸음 기록으로 센 미달 (2026-10-08). 예전엔 우리 경고 문구가 「답 스스로 … 밝혔습니다」로 전해졌다.
    # 검증 없이 접은 코드 판 (2026-10-08) — 예전에는 판이 실패(`coding_verification_missing`)로 끝나 답이 버려졌다.
    unverified = verification.get("code_unverified")
    if isinstance(unverified, dict):
        review.append(
            "코드는 고쳤지만 검증(테스트·실행 확인)을 돌리지 못한 채 끝났습니다 — files 는 검증되지 않은 결과입니다. 열어서 확인하거나 검증만 다시 맡기세요."
            if unverified.get("mutated")
            else "이 판에서는 파일을 고치지 않았고 실행 확인도 하지 않았습니다 — 답은 설명입니다."
        )
    harness_shortfall = str(verification.get("harness_shortfall") or "")
    if harness_shortfall == "read_count":
        review.append("손자리가 센 것으로는 시킨 개수만큼 본문을 열어 읽지 않았습니다(답 끝의 경고에 몇 개인지 있습니다).")
    elif harness_shortfall == "commit_unconfirmed":
        review.append("실행한 동작이 성공했는지 손자리가 확인하지 못했습니다 — 다시 실행하기 전에 화면을 먼저 확인해야 합니다.")
    if not unmet and not failed and not (completion == "partial" and review):
        return None
    counts: dict[str, int] = {}
    for step in steps:
        if step.get("ok"):
            tool = str(step.get("tool") or "")
            counts[tool] = counts.get(tool, 0) + 1
    resume: dict[str, Any] = {
        "did": [f"{tool} ×{n}" for tool, n in counts.items()],
        "evidence": sources[:20],
        "files": files,
        "next": [
            str(item.get("label") or "") + (f" (지금: {item.get('saw')})" if item.get("saw") else "")
            for item in unmet
        ],
    }
    if review and completion == "partial":
        resume["why_partial"] = review
    if failed:
        last = failed[-1]
        resume["blocked"] = (str(last.get("tool") or "") + ": " + str(last.get("error") or "")[:200]).strip(": ")
    return resume


def _progress_block(live: "dict[str, Any] | None", *, now: "float | None" = None) -> "dict[str, Any] | None":
    """진행 중인 작업이 **지금 무엇을 하는가** — 화면이 보여 주는 「지금 하는 일 · 시킨 것 n/m」을 호스트 채팅으로 잇는다.

    ## 왜 (2026-09-22, 사장님 스크린샷)

    온텔릭 화면은 기다림을 지루하지 않게 한다. 그런데 큰 플랫폼이 부르면 사용자는 호스트 채팅만 보고, 거기엔 「일하는 중, 0걸음」
    뿐이었다. 그 정보(`live_progress.py`)를 여기서 요약에 싣는다.

    ★ **남은 시간 예측은 싣지 않는다.** 화면의 「3분 남음」이 얼마나 맞는지 재 본 적이 없고, 작업 시간이 3배씩 흔들린다.
    틀린 예측을 호스트가 사용자에게 전하면 신뢰를 깎는다.
    """
    if not isinstance(live, dict) or not live:
        return None
    block: dict[str, Any] = {}
    doing = str(live.get("doing") or "").strip()
    if doing:
        block["doing"] = doing
    try:
        step = int(live.get("step") or 0)
    except (TypeError, ValueError):
        step = 0
    if step > 0:
        block["step"] = step
    requested = live.get("requested")
    if isinstance(requested, dict):
        try:
            total = int(requested.get("total") or 0)
            met = int(requested.get("met") or 0)
        except (TypeError, ValueError):
            total = met = 0
        if total > 0:
            items = [
                {"label": str(i.get("label") or ""), "met": bool(i.get("met")), "saw": str(i.get("saw") or "")}
                for i in (requested.get("items") or [])[:8] if isinstance(i, dict)
            ]
            block["requested"] = {"met": met, "total": total, "items": items}
    updated = live.get("updated_at")
    if isinstance(updated, (int, float)) and updated > 0:
        block["seconds_since_update"] = max(0, int((time.time() if now is None else now) - float(updated)))
    return block or None


def _progress_sentence(progress: "dict[str, Any]") -> str:
    """호스트가 사용자에게 그대로 옮겨도 되는 한두 문장. 남은 시간은 말하지 않는다."""
    parts: list[str] = []
    doing = str(progress.get("doing") or "").strip().rstrip(".")
    if doing:
        parts.append(f"지금: {doing}.")
    requested = progress.get("requested")
    if isinstance(requested, dict) and int(requested.get("total") or 0) > 0:
        parts.append(f"시킨 것 {int(requested.get('met') or 0)}/{int(requested['total'])} 채웠습니다.")
        missing = [str(i.get("label") or "") for i in requested.get("items") or [] if not i.get("met") and i.get("label")]
        if missing:
            parts.append("남은 것: " + ", ".join(missing[:2]) + ".")
    quiet = progress.get("seconds_since_update")
    if isinstance(quiet, int) and quiet >= 120:
        parts.append(f"마지막 소식이 {quiet // 60}분 전입니다.")
    return " ".join(parts)


def summarize_job(
    job: dict[str, Any], *, ahead: int | None = None, now: float | None = None, live: dict[str, Any] | None = None,
    pending_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """잡 사전 하나 → Claude 가 읽을 요약.

    status: queued · running · needs_approval · needs_decision · done · needs_review · failed · cancelled
    `ahead` 는 이 일 앞에 줄 서 있는 일의 수(모르면 None).
    """
    raw_status = str(job.get("status") or "")
    result = job.get("result") or {}
    trace = result.get("agent_trace") or {}
    steps = [s for s in trace.get("steps") or [] if isinstance(s, dict)]
    summary: dict[str, Any] = {
        "job_id": str(job.get("id") or ""),
        "steps": len(steps),
    }
    if raw_status not in _TERMINAL:
        # ★ 「일하는 중 · 걸음 0」만 돌려주면 Claude 는 **왜 안 움직이는지 모른 채** 20분을 기다린다(2026-09-16 실측).
        #   줄을 서 있는 것인지, 사람 승인을 기다리는 것인지, 정말 일하는 중인지를 말한다.
        summary["status"] = {"waiting_approval": "needs_approval", "queued": "queued",
                             "waiting_continuation": "needs_decision"}.get(raw_status, "running")
        if steps:
            summary["current_tool"] = str(steps[-1].get("tool") or "")
        if ahead is not None:
            summary["jobs_ahead"] = int(ahead)
        progress = _progress_block(live, now=now)
        if progress and raw_status != "queued":
            summary["progress"] = progress
            # 걸음 기록(agent_trace)은 판이 끝나야 저장된다 — 일하는 동안은 진행에서 센다(2026-09-28: 14걸음 일하는 내내 「0」).
            summary["steps"] = max(summary["steps"], int(progress.get("step") or 0))
        question = (pending_approval or {}).get("target") if (pending_approval or {}).get("tool_name") == "ask_user" else None
        if raw_status == "waiting_approval" and isinstance(question, dict) and question.get("question"):
            # ★ 질문 카드(2026-09-30): 승인이 아니라 **사람의 답**을 기다린다. 무엇을 묻는지 그대로 전하게 한다.
            options = [str(option.get("label") or "") for option in question.get("options") or [] if isinstance(option, dict)]
            recommended = question.get("recommended")
            summary["question"] = {"question": str(question["question"]), "options": options,
                                   "recommended": options[recommended] if isinstance(recommended, int)
                                   and 0 <= recommended < len(options) else ""}
            summary["message"] = (f"{NAME_KO}가 사용자에게 묻고 있습니다 — 「{question['question']}」 "
                                  f"(선택지: {' / '.join(options)}). 이 질문을 사용자에게 그대로 전하고, "
                                  f"사용자가 {NAME} 창의 질문 카드에서 고르면 그 자리부터 잇습니다. 대신 고르지 마세요.")
        elif raw_status == "waiting_approval":
            summary["message"] = (f"{NAME} 창에 승인 카드가 떠 있습니다. 사용자가 승인하거나 거절해야 진행됩니다 — "
                                  "사용자에게 그 창을 봐 달라고 알리세요.")
        elif raw_status == "waiting_continuation":
            waiting = result.get("continuation") if isinstance(result.get("continuation"), dict) else {}
            report = waiting.get("report") if isinstance(waiting.get("report"), dict) else None
            if waiting.get("reason") == "stuck" and report:
                # ★ 헛돌다 멈춘 판(2026-09-23): 「계속할까요」가 아니라 **사람이 할 일**이 있다. 그걸 그대로 전하게 한다.
                summary["stuck"] = {key: str(report.get(key) or "") for key in ("done", "blocked", "ask", "url")}
                # 멈춘 화면이 로그인 화면일 수 있다(사람이 같은 탭을 쓰다 멈춘 판) — 한 번 쓰는 값은 줄여서(`url_privacy`).
                summary["stuck"]["url"] = safe_url(summary["stuck"]["url"])
                summary["message"] = (f"{NAME_KO}가 같은 자리에서 막혀 멈췄습니다. 사용자에게 다음을 그대로 전하세요 — "
                                      f"한 것: {report.get('done') or '-'} / 막힌 곳: {report.get('blocked') or '-'} / "
                                      f"해 주실 일: {report.get('ask') or '-'}. 사용자가 그 일을 한 뒤 {NAME} 창에서 "
                                      "「이어서」를 누르면 그 자리부터 잇습니다. 대신 풀거나 우회하지 마세요.")
            elif str(waiting.get("reason") or "").startswith("human_gate:"):
                # ★ 사람 문(2026-09-29): 「계속할지 묻는다」가 아니다 — 로그인·사람 확인은 사람만 연다.
                what = {"login_required": "로그인", "bot_check": "보안 문자 확인",
                        "payment_required": "결제 정보 입력"}.get(str(waiting["reason"]).split(":", 1)[1], "사람 확인")
                # ★ 2026-10-02 밤 팀원 실사용(V2EX): 「풀고 「이어서」를 누른 뒤 말해 달라」로 읽은 클로드가 상태 확인을 멈췄다.
                #   실제로는 사람이 로그인하자 손자리가 **스스로 알아채고 이어서 답까지 썼는데**(gate_watcher) 클로드는 몰랐다.
                #   「이어서」는 사람용 버튼이다 — 바깥 AI 에게는 「계속 물어라」가 맞는 다음 수다.
                summary["waiting_for_person"] = what
                summary["resumes_on_its_own"] = True
                summary["message"] = (f"{NAME_KO}가 {what} 화면에서 멈췄습니다"
                                      + (f"({waiting.get('gate_url')})" if waiting.get("gate_url") else "")
                                      + f". 사용자에게 크롬에서 직접 {what}만 해 달라고 전하세요. 끝나면 {NAME_KO}가 알아채고 "
                                      "스스로 이어갑니다 — 사용자가 「이어서」를 누르지 않아도 됩니다. 사용자가 「했다」고 말하길 "
                                      "기다리지 말고 같은 job_id 로 sonjari_task_status 를 계속 불러 결과를 받으세요. "
                                      f"오래 안 열리면 {NAME_KO}가 가진 것으로 답하고 끝냅니다. 대신 풀거나 우회하지 마세요.")
            else:
                summary["message"] = f"{NAME_KO}가 계속할지 사용자에게 묻고 있습니다. 사용자에게 알리세요."
        elif raw_status == "queued":
            summary["message"] = (f"아직 시작 못 했습니다 — {NAME_KO}는 한 번에 한 일만 합니다"
                                  + (f"(앞에 {int(ahead)}개)." if ahead else ".")
                                  + " 앞의 일이 끝나면 시작합니다.")
        else:
            summary["message"] = "일하는 중입니다. 잠시 뒤 sonjari_task_status 를 다시 부르세요."
            if progress:
                summary["message"] += " " + _progress_sentence(progress)
            # 호스트는 「일하는 중」만 받으면 얼마나 기다렸는지 모른다(4B 가 검증을 못 해 29분을 돈 판이 있었다).
            started = job.get("started_at")
            if isinstance(started, (int, float)) and started > 0:
                import time as _time

                elapsed = max(0, int((_time.time() if now is None else now) - float(started)))
                summary["elapsed_sec"] = elapsed
                if elapsed >= _LONG_RUNNING_SEC:
                    summary["message"] += (
                        f" 벌써 {elapsed // 60}분째입니다 — 오래 걸리는 판이니 계속 기다릴지, 사용자에게 알리고 직접 "
                        "이어받을지 판단하세요."
                    )
        return summary
    if raw_status != "completed":
        summary["status"] = raw_status
        summary["error"] = str(job.get("error") or "")[:500]
        # 상태와 오류만 주면 호스트는 「실패」만 받고 만들어 둔 것·읽어 둔 것을 버린다.
        summary.update(_failure_report(job, result, steps))
        return summary

    # 맡긴 쪽이 받을 답 — 바깥 AI 면 대조 덩어리까지 든 답(2026-10-24 · `check_notes`). 영수증 셈(`receipt`)도 같은 글을 센다.
    answer = answer_for_receiver(result, job.get("payload"))
    files: list[str] = []
    written: list[str] = []
    sources: list[str] = []
    for step in steps:
        if not step.get("ok"):
            continue
        evidence = step.get("evidence") or {}
        record = step.get("evidence_record") or {}
        # ★ 2026-09-30 QR 판: 상자 걸음은 `path` 가 없고 **`saved_to` 에 실제 경로**가 온다. 그걸 못 보고 상자 실행
        #   번호(`48cdbd03a6a7`)를 경로 자리에 넣어 files 에 없는 파일이 찍혔다 — 바깥 AI 는 이 칸을 그대로 전한다.
        for saved in evidence.get("saved_to") or []:
            saved_path = str((saved or {}).get("path") or "") if isinstance(saved, dict) else ""
            if saved_path and saved_path not in files:
                files.append(saved_path)
        # ★ 2026-09-30 워드클라우드 v2: 장부는 `saved_to` 를 **글자로 뭉개 두고**(`"{'name': …"`) 실제 경로는
        #   `output_paths` 로 평평하게 싣는다(`_step_evidence`). 그걸 안 봐서 아래 폴백이 실행 번호를 경로로 만들었다
        #   (`c:\…\alture-jarvis\dd1e25288c56`). 바탕화면에 제대로 만든 판이었다.
        flat = [str(value or "").strip() for value in evidence.get("output_paths") or [] if str(value or "").strip()]
        for flat_path in flat:
            if flat_path not in files:
                files.append(flat_path)
        if _is_write(step):
            path = str(evidence.get("output_path") or evidence.get("path") or "")
            if not path and not flat:
                # source_id 는 경로일 수도, 실행 번호일 수도 있다 — **경로 모양일 때만** 파일로 친다.
                source = str(record.get("source_id") or "")
                path = source if ("\\" in source or "/" in source) else ""
            if path and path not in files:
                files.append(path)
            _strings(step.get("arguments") or {}, written)
        elif str(record.get("effect") or "").startswith("read"):
            # ★ 2026-10-19 잡 51f35b07: 사람이 같은 탭에서 계정을 더하는 사이 읽은 구글 계정 고르기 화면이 `client_id` ·
            #   `code_challenge` · `nonce` · `state` 를 단 채 sources 로 나갔다. 출처는 「그 화면을 봤다」면 충분하다 — 로그인 화면과
            #   한 번 쓰는 값이 붙은 주소는 `scheme://host/path` 로 줄인다(지우지 않는다 · `url_privacy.safe_url`).
            source = safe_url(str(record.get("source_id") or ""))
            if source.startswith("http") and source not in sources:
                sources.append(source)

    seen = {str(n) for n in trace.get("tool_numbers") or []} | {str(n) for n in trace.get("tool_numbers_body") or []}
    # ★ 2026-09-30: **사용자가 과제에 직접 적은 숫자**는 근거다. 「17 곱하기 23은?」의 답에 17·23 이
    #   「도구가 준 적 없는 숫자」로 찍혀 needs_review 가 됐다. 391(계산 결과)은 그대로 잡힌다 — 그건 도구가 안 줬다.
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    seen |= numbers_claimed_in(str(payload.get("prompt") or ""))
    # ★ 2026-10-11 쇼핑몰 과제 두 판: 손자리가 쓴 CSS 의 글자 크기·여백(1.05 · 1.2 · 240 …)이 「도구가 준 적 없는 숫자」
    #   44개·59개로 찍혀 잘 만든 판이 needs_review 가 됐다. 이 검사는 **조사한 값을 파일에 옮겨 적을 때** 지어낸 숫자를
    #   잡으려는 것이다. 코드를 만드는 일에서 쓴 코드의 숫자는 주장이 아니라 만든 것 자체다 — 세지 않는다.
    #   그리고 답이 「합계 7,500원으로 계산된다」처럼 자기가 만든 것을 설명하는 숫자는 그 코드가 근거다.
    code_job = str(payload.get("workspace_mode") or "") == "code" or bool(str(payload.get("code_workspace") or "").strip())
    # ★ 2026-10-14 레딧 홍보 규칙 조사: 답 끝에 **우리가 붙인** 대조 칸의 「14개 읽음 · 답에 7개」가 「도구가 준 적 없는 숫자」로
    #   찍혀 needs_review 가 됐다. 그 숫자는 하네스가 걸음 기록을 센 것이다 — 모델의 주장이 아니니 대조 칸부터 뒤는 세지 않는다.
    #   좁게 자른다: 대조 칸 머리(「시킨 것 대조」 · 「Checklist」)만. 경고(⚠)는 모델 글과 섞일 수 있어 그대로 센다.
    checklist = _OUR_CHECKLIST.search(answer)
    model_said = answer[:checklist.start()] if checklist else answer
    if code_job:
        seen |= numbers_claimed_in("\n".join(written))
        claimed = numbers_claimed_in(model_said)
    else:
        claimed = numbers_claimed_in(model_said + "\n" + "\n".join(written))
    unsupported = sorted(unsupported_numbers(claimed, seen))
    completion = str(result.get("completion_state") or "")
    # ★ 나가기 전 정제 · 돌려받아야 할 것 (2026-10-15 · §55-32). 숫자 대조는 위에서 **원래 답**으로 끝냈다 — 가린 자리가
    #   숫자를 지워 근거 없는 숫자를 숨기지 않게. 나가는 글만 다듬는다.
    needs = clean_needs(payload.get("needs"))
    answer, refined = refine(answer, needs=needs)
    needs_checked = check_needs(needs, answer, files=files) if needs else None
    summary.update({
        # ★ `partial` 은 상태를 안 바꾸고 메모로만 싣는다 — 운영 잡 178개 중 68개(38%)가 partial 이라
        #   상태에 섞으면 needs_review 가 늘 켜져 아무도 안 본다(경보줄이 길어 안 읽힌 사고와 같은 모양).
        "status": "needs_review" if unsupported else "done",
        "answer": answer[:_ANSWER_LIMIT] + ("…(잘림)" if len(answer) > _ANSWER_LIMIT else ""),
        "files": files,
        "sources": sources[:20],
        "numbers_from_tools": len(seen),
        "unsupported_numbers": unsupported[:20],
        "completion_state": completion,
    })
    if needs_checked is not None:
        summary["needs"] = needs_checked
    summary["refined"] = refined
    summary["receipt"] = receipt(needs_checked, refined, host=str(payload.get("caller") or ""))
    notes: list[str] = []
    if unsupported:
        notes.append(f"도구가 준 적 없는 숫자 {len(unsupported)}개 — 사실로 전하기 전에 확인하세요.")
    # ★ 2026-10-19: met 은 셋이다 — False(이름 붙은 자리가 비었다)만 「비어 있다」고 말한다. None(이름으로 자리를 못 찾음)은
    #   「확인 못 함」이다. 둘을 섞어 「비어 있는 항목」으로 알리던 탓에 답에 다 있는 판이 0/4 로 나갔다(Ollama FAQ 세 판).
    missing = [item["label"] for item in needs_checked or [] if item.get("met") is False]
    unchecked = [item["label"] for item in needs_checked or [] if item.get("met") is None]
    if missing:
        notes.append(f"돌려받아야 할 것 중 비어 있는 항목: {', '.join(missing)} — 이 항목 없이 끝낼 수 있는지, 다시 맡길지 정하세요.")
    if unchecked:
        notes.append(f"이름이 붙은 칸 · 제목을 찾지 못해 확인하지 못한 항목: {', '.join(unchecked)} — 비어 있다는 뜻이 아닙니다. "
                     "답 본문에서 직접 확인하세요.")
    if refined:
        notes.append("답에서 가린 것이 있습니다(" + ", ".join(f"{item['kind']} {item['count']}" for item in refined)
                     + "). 연락처가 꼭 필요하면 needs 에 밝혀 다시 맡기세요 — 주민번호 · 카드 번호 · 비밀 키는 내보내지 않습니다.")
    if completion == "partial":
        notes.append(f"{NAME_KO}가 요청의 일부만 끝냈다고 판정했습니다.")
    # ★ 2026-09-23 파트너 센터 실전: 이어서 맡긴 과제에 **걸음 0·출처 0** 으로 「목록에 Ontelic 제품이 없음」이라고 답했다 —
    #   브라우저를 안 보고 앞 판 기억으로 화면 상태를 단정한 것이다(사람이 방금 예약해서 실제로는 있었다).
    #   이 문으로 오는 일은 **도구가 필요해서 맡긴 일**이다(혼자 할 수 있는 일은 맡기지 말라고 안내한다). 그러니 도구를 하나도
    #   안 쓰고 끝난 답은 낱말을 보지 않고 **구조로** 표시한다 — 호스트가 그 답을 확인한 사실로 옮기지 않게.
    if not steps:
        summary["status"] = "needs_review"
        notes.append(f"{NAME_KO}가 이번 판에 도구를 하나도 쓰지 않고 답했습니다 — 화면·파일·사이트를 실제로 확인한 답이 "
                     "아닙니다. 지금 상태에 대한 말이면 다시 확인하도록 맡기세요.")
    # ★ 가지에서 한 코드 일 (2026-10-09) — 무엇이 바뀌었고 · 확인 명령이 통과했고 · 어떻게 보고 가져가는지.
    #   손자리는 원래 폴더에 합치지 않는다. 합치는 것은 맡긴 쪽이 바뀐 것을 본 뒤에 정한다.
    delegated = result.get("delegated") if isinstance(result.get("delegated"), dict) else None
    if delegated:
        check = delegated.get("check") if isinstance(delegated.get("check"), dict) else None
        summary["branch"] = {
            "repo": str(delegated.get("repo") or ""),
            "name": str(delegated.get("branch") or ""),
            "worktree": str(delegated.get("worktree") or ""),
            "base": str(delegated.get("base") or "")[:12],
            "changed": list(delegated.get("changed") or [])[:60],
            "changed_count": int(delegated.get("changed_count") or 0),
            "stat": str(delegated.get("stat") or ""),
            **({"check": check} if check else {}),
            "take_home": dict(delegated.get("take_home") or {}),
        }
        if check and not check.get("passed"):
            notes.append("확인 명령이 통과하지 않은 채 끝났습니다 — 가지의 변경은 미완성입니다. 가져가기 전에 직접 돌려 보세요.")
        # 제자리여서 접힌 판 — 까닭을 이름으로 싣는다. 같은 과제를 그대로 다시 맡기면 같은 자리에서 멈춘다.
        folded = (trace.get("verification") or {}).get("code_budget_exhausted")
        why = str((folded or {}).get("why") or "") if isinstance(folded, dict) else ""
        if why in _STUCK_WHY:
            summary["branch"]["stopped_because"] = why
            notes.append(_STUCK_WHY[why])
        # ★ 설명 글 · 주석만 바뀐 파이썬 파일 (2026-10-19 75aaa296 — 허술한 시험을 설명 글에 낱말을 끼워 넣어 통과시켰다).
        wording = [str(path) for path in (delegated.get("wording_only") or [])][:60]
        if wording:
            summary["branch"]["wording_only"] = wording
            notes.append(
                f"바뀐 파일 중 {len(wording)}개는 설명 글 · 주석만 바뀌고 코드는 그대로입니다(branch.wording_only). "
                "확인 명령을 맞추려고 넣은 글일 수 있으니 가져가기 전에 보세요."
            )
        if not summary["branch"]["changed_count"]:
            notes.append("가지에 바뀐 파일이 없습니다.")
        else:
            notes.append("가지의 변경은 아직 원래 폴더에 없습니다 — branch.take_home 의 명령으로 본 뒤 가져가세요.")
    if notes:
        summary["review_notes"] = notes
    summary["cost"] = _cost(trace, steps, sources)
    resume = _resume(trace, steps, sources, files, completion)
    if resume is not None:
        summary["resume"] = resume
    return summary
