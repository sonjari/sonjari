"""손자리 앱 안의 **Claude Agent** — 모델 칸에서 고르면 앤트로픽의 클로드 코드 CLI 가 일하고, 우리는 중계만 한다 (2026-10-26).

결정 문서: `docs/ADR_클로드API_앱통합_2026-10-26.ko.md` 고침 3 · 고침 4 · 「구현 1판」.

이 모듈이 하는 일은 둘뿐이다.

1. **「앱 안」 지침 만들기** — 바깥 클로드에게 주는 `mcp_server.INSTRUCTIONS`(한국어 · 영어) 를 **줄 단위로 몇 줄만** 바꾼다.
   지침 글을 두 벌 쓰지 않는다: 바깥 판의 줄이 바뀌어 고칠 자리(닻)를 못 찾으면 `AnchorMissing` 으로 시끄럽게 실패한다
   (시험 `test_claude_agent_1026.py` 가 닻을 전부 센다). 그래서 두 판이 조용히 갈라지지 않는다.
2. **작업 폴더 준비** — 데이터 폴더의 `claude_agent/` 아래에 클로드 코드를 띄울 때 옆에 끼워 넣을 파일을 쓴다.
   - `mcp.json` — 손자리 MCP 서버 한 줄(`mcp_connect.server_entry` 그대로 · 비밀 없음).
   - `instructions_cowork.<lang>.md` · `instructions_code.<lang>.md` — `--append-system-prompt-file` 로 넘길 지침.
   - `workspace/` — 코워크 모드의 빈 작업 폴더(코드 모드는 사용자가 고른 코드 폴더가 작업 폴더다 · 대표 결정 10-26 08:25).

**사용자 파일은 고치지 않는다.** 사용자 전역 `~/.claude/CLAUDE.md` 에 줄을 쓰는 「잇기」(`guide_skill.py`)는 바깥 클로드 코드용이라
여기서 부르지 않는다. 키는 이 모듈이 다루지 않는다 — `api_escalation.py` 의 DPAPI 키 하나를 같이 쓰고, 꺼내는 것은 앱(Rust)이 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .brand import MCP_SERVER_NAME, NAME, NAME_KO

__all__ = [
    "AnchorMissing", "DIR_NAME", "TOOLS", "in_app_instructions", "prepare", "status",
]

DIR_NAME = "claude_agent"

#: 클로드에게 주는 손자리 도구 — **맡기기 문만**(첫 판 · 클로드가 페이지 원문을 직접 읽지 않게: 돈 · 「원문은 내 PC」).
#: 실제 이름은 MCP 서버 이름(`brand.MCP_SERVER_NAME`) + 도구 이름(`delegation.TASK_TOOL` 등)이다.
def _tool_names() -> list[str]:
    from .delegation import GUIDE_TOOL, STATUS_TOOL, TASK_TOOL

    return [f"mcp__{MCP_SERVER_NAME}__{tool['name']}" for tool in (TASK_TOOL, STATUS_TOOL, GUIDE_TOOL)]


TOOLS = _tool_names()


class AnchorMissing(RuntimeError):
    """바깥 판 지침에서 고칠 줄을 못 찾았다 — 바깥 판이 바뀌었으니 「앱 안」 판도 같이 손봐야 한다."""


# ── 「앱 안」 지침 ────────────────────────────────────────────────────────────────
#
# 바꾸는 것(한국어 · 영어 같은 자리):
#   ① 머리에 「당신은 손자리 앱 안의 Claude Agent」 몇 줄(모드별).
#   ② 「당신의 자동화 브라우저는 빈 브라우저」 — 바깥 클로드 이야기. 앱 안 코워크의 클로드에게는 브라우저가 없다 → 괄호를 뺀다.
#   ③ 「당신이 방금 띄워 둔 앱(localhost) 확인」 — 코워크의 클로드에게는 시험 도구가 없다 → 코워크에서 그 줄을 뺀다(코드 모드는 둔다).
#   ④ 「되돌릴 수 없는 동작은 Sonjari 창에서 · 승인 카드도 그 창」 → 「이 창의 승인 카드에서」.
#   ⑤ 코드 모드: 「사용자가 코드를 손자리에게 맡기라고 하면 맡긴다」 한 줄 + 「큰 설계 통째로 맡기지 말 것」과 부딪히지 않게 그 줄을 맞춘다.

_KO = {
    "browser_aside": "(당신의 자동화 브라우저는 빈 브라우저라 로그인이 없습니다)",
    "localhost_head": "- 당신이 방금 띄워 둔 앱(localhost)의 동작 확인",
    "dont_heads": ("- 큰 설계·처음 보는 API", "- 처음 보는 API"),
    "irreversible_head": "- 되돌릴 수 없는 동작(메일 발송·발행·결제·삭제)은 이 연결로 할 수 없습니다.",
    "irreversible": "- 되돌릴 수 없는 동작(메일 발송·발행·결제·삭제)은 당신이 직접 하지 않습니다. 손자리가 그 앞에서 멈추면 사용자가 **이 창의 승인 카드**에서 정합니다. 사용자에게 그렇게 알리세요.",
    "head_cowork": (
        f"당신은 {NAME}({NAME_KO}) 앱 안에서 사용자와 대화하는 Claude Agent 입니다. 사용자는 이 앱의 대화 칸에서 당신과 말하고, "
        f"오른쪽 「{NAME}의 컴퓨터」 칸에서 당신의 걸음과 {NAME_KO}가 맡아 한 걸음을 함께 봅니다.\n"
        f"당신에게는 {NAME_KO} 맡기기 도구(sonjari_task · sonjari_task_status · sonjari_guide)만 있습니다. 웹 · 파일 · 문서 일은 {NAME_KO}에게 맡기세요 — "
        "페이지 원문은 이 PC 에 남고 당신에게는 결과와 검사만 돌아옵니다. 맡긴 뒤에는 결과를 검토해 사용자에게 짧게 전하세요.\n"
        "답은 사용자가 쓰는 말로, 쉬운 말로 씁니다.\n\n"
    ),
    "head_code": (
        f"당신은 {NAME}({NAME_KO}) 앱의 코드 모드에서 사용자가 고른 프로젝트 폴더를 작업 폴더로 일하는 Claude Agent 입니다. "
        f"그 폴더의 원본을 당신의 도구로 바로 읽고 고칩니다. 사용자는 오른쪽 「{NAME}의 컴퓨터」 칸에서 당신이 연 파일 · 바꾼 줄과 "
        f"{NAME_KO}가 맡아 한 걸음을 함께 봅니다.\n"
        f"{NAME_KO} 맡기기 도구(sonjari_task · sonjari_task_status · sonjari_guide)도 있습니다. 이 PC 에 sonjari-guide 스킬이 깔려 있으면 그것을 따르고, "
        "없으면 처음 맡기기 전에 sonjari_guide 를 한 번 부르세요.\n\n"
    ),
    "code_delegate": (
        f"- 사용자가 코드를 {NAME_KO}에게 맡기라고 하면 맡깁니다 — 파일 한두 개 크기로 쪼개서 repo(저장소 폴더) · check(통과하면 끝인 명령)를 주고, "
        f"{NAME_KO}가 새 가지에서 고쳐 돌려준 것은 당신이 검토한 뒤 원본에 합칩니다"
    ),
    "code_dont": (
        f"- 사용자가 따로 말하지 않았는데 큰 설계 · 처음 보는 API(예: 3ds Max `pymxs`) 코드를 한 덩어리로 맡기기 — 로컬 모델이라 오래 걸립니다. "
        f"그런 코드는 당신이 직접 짜거나, 맡기라고 하면 위처럼 파일 한두 개 크기로 쪼개 맡기세요"
    ),
}

_EN = {
    "browser_aside": " (your automation browser is an empty browser without their logins)",
    "localhost_head": "- Checking an app you just started (localhost)",
    "dont_heads": ("- Handing over a whole large design",),
    "irreversible_head": "- Irreversible actions (sending mail, publishing, paying, deleting) cannot be done over this connection.",
    "irreversible": "- You do not do irreversible actions (sending mail, publishing, paying, deleting) yourself. If Sonjari stops before one, the user decides on the **approval card in this window**. Tell the user so.",
    "head_cowork": (
        f"You are Claude Agent working inside the {NAME} app. The user talks with you in this app's chat, and watches your steps "
        f"and the steps {NAME} takes for you in the \"{NAME}'s computer\" pane on the right.\n"
        f"You only have the {NAME} delegation tools (sonjari_task, sonjari_task_status, sonjari_guide). Hand web, file and document work to {NAME} — "
        "the page text stays on this PC and only the result and its checks come back to you. After a hand-off, review the result and tell the user briefly.\n"
        "Answer in the user's language, in plain words.\n\n"
    ),
    "head_code": (
        f"You are Claude Agent working in the {NAME} app's code mode, with the project folder the user picked as your working folder. "
        f"You read and edit the original files there directly with your own tools. The user watches the files you open, the lines you change "
        f"and the steps {NAME} takes for you in the \"{NAME}'s computer\" pane on the right.\n"
        f"You also have the {NAME} delegation tools (sonjari_task, sonjari_task_status, sonjari_guide). If the sonjari-guide skill is installed on this PC, follow it; "
        "otherwise call sonjari_guide once before the first hand-off.\n\n"
    ),
    "code_delegate": (
        f"- When the user asks you to hand code to {NAME}, do it — split it into one- or two-file pieces with a repo (repository folder) and a check "
        f"(a command that means done when it passes); review what {NAME} fixed on its new branch before you merge it into the original"
    ),
    "code_dont": (
        "- Handing over a whole large design or code against an API it has never seen (e.g. 3ds Max `pymxs`) when the user did not ask — it is a local model and "
        "will take long. Write that code yourself, or when the user asks you to hand it over, split it into one- or two-file pieces as above"
    ),
}


def _base(lang: str) -> str:
    from . import mcp_server

    return mcp_server.INSTRUCTIONS_EN if lang == "en" else mcp_server.instructions_ko()


def in_app_instructions(mode: str = "cowork", lang: str = "ko") -> str:
    """「앱 안」 판 지침. `mode` 는 `cowork` · `code`, `lang` 은 `ko` · `en`.

    고칠 줄(닻)을 하나라도 못 찾으면 `AnchorMissing` — 바깥 판이 바뀐 것이니 조용히 넘기지 않는다.
    """
    lang = "en" if str(lang).lower().startswith("en") else "ko"
    code = mode == "code"
    words = _EN if lang == "en" else _KO
    found = {"browser_aside": False, "localhost": False, "dont": False, "irreversible": False}
    out: list[str] = []
    for line in _base(lang).split("\n"):
        if words["browser_aside"] in line:
            found["browser_aside"] = True
            line = line.replace(words["browser_aside"], "")
        if line.startswith(words["localhost_head"]):
            found["localhost"] = True
            if not code:
                continue
        if line.startswith(words["dont_heads"]):
            found["dont"] = True
            if code:
                line = words["code_dont"]
        if line.startswith(words["irreversible_head"]):
            found["irreversible"] = True
            line = words["irreversible"]
        out.append(line)
    missing = [name for name, ok in found.items() if not ok]
    if missing:
        raise AnchorMissing(f"in-app instructions: anchors not found in mcp_server instructions ({lang}): {', '.join(missing)}")
    if code:
        # 「부르지 말 것」 머리 바로 앞(= 「언제 부르나」의 끝)에 코드 맡기기 줄을 둔다.
        when_not = "When not to call it" if lang == "en" else "부르지 말 것"
        try:
            at = out.index(when_not)
        except ValueError as exc:
            raise AnchorMissing(f"in-app instructions: section '{when_not}' not found ({lang})") from exc
        insert_at = at - 1 if at > 0 and out[at - 1] == "" else at
        out.insert(insert_at, words["code_delegate"])
    head = words["head_code"] if code else words["head_cowork"]
    return head + "\n".join(out).strip() + "\n"


# ── 작업 폴더 ─────────────────────────────────────────────────────────────────────

def root(config: Any) -> Path:
    return Path(config.data_dir) / DIR_NAME


def _write_if_changed(path: Path, text: str) -> None:
    """같은 글이면 쓰지 않는다 — 클로드 코드의 캐시 머리(지침 · 도구 목록)가 판마다 흔들리지 않게."""
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def prepare(config: Any, lang: str = "ko") -> dict[str, Any]:
    """클로드 코드를 띄우기 전에 부른다. 파일 자리를 돌려준다 — 앱(Rust)은 **같은 자리를 스스로 계산**하고 이 값은 확인용이다."""
    from .api_escalation import has_key
    from .mcp_connect import server_entry

    lang = "en" if str(lang).lower().startswith("en") else "ko"
    base = root(config)
    entry = server_entry(config)
    # 이 연결로 맡긴 판은 「사람이 보는 판」이다 — 사람이 같은 창에서 결 · 이야기판을 고른다(2026-10-26 첫 실제 판:
    # 바깥 클로드 판처럼 기다림 0초로 권장 결을 바로 골라 고를 틈이 없었다).
    entry = {**entry, "env": {**dict(entry.get("env") or {}), "JARVIS_MCP_VIA": "app"}}
    mcp_text = json.dumps({"mcpServers": {MCP_SERVER_NAME: entry}}, ensure_ascii=False, indent=2) + "\n"
    _write_if_changed(base / "mcp.json", mcp_text)
    paths: dict[str, str] = {}
    for mode in ("cowork", "code"):
        path = base / f"instructions_{mode}.{lang}.md"
        _write_if_changed(path, in_app_instructions(mode, lang))
        paths[mode] = str(path)
    (base / "workspace").mkdir(parents=True, exist_ok=True)
    return {
        "ok": True,
        "root": str(base),
        "mcp_config": str(base / "mcp.json"),
        "instructions": paths,
        "workspace": str(base / "workspace"),
        "tools": list(TOOLS),
        "has_key": has_key(config),
        "lang": lang,
    }


def status(config: Any) -> dict[str, Any]:
    """화면이 보는 상태 — 키는 있다/없다만(값 · 끝자리 모두 안 냄)."""
    from .api_escalation import has_key

    return {"has_key": has_key(config), "tools": list(TOOLS), "root": str(root(config))}
