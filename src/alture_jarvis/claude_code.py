"""Claude Code를 **결정론으로만** 부르는 로컬 위임 손.

모델에게 "어려우면 Claude를 불러라"고 적는 것으로는 위임이 되지 않는다. 그 문장은
안내문이고, 안내문 준수율이 낮다는 것을 이 저장소는 이미 여러 번 재 봤다. 여기서는
다중 파일·git 저장소·같은 파일 상자 실패·남은 테스트 실패·명시적 무지를 코드가
판정하고, 그때만 이 도구를 강제로 부른다.

CLI는 구독 로그인을 그대로 쓰며 ``--bare``를 넣지 않는다. 첫 호출에서 받은
``session_id``는 걸음 증거에 남고 후속 호출은 반드시 ``--resume``으로 이어진다.

## 켜고 끄는 자리 (2026-10-19 — 사용자 설정 「막히면 내 클로드에게 넘기기」)

    관리자 잠금(JARVIS_CLAUDE_CODE_LOCKED)  >  측정 판  >  화면 값(settings.json)  >  .env·코드 기본값(꺼짐)

- **기본 꺼짐.** 켜는 것은 사람이 설정 › 연결에서 한다. 운영 .env 의 ``JARVIS_CLAUDE_CODE_ENABLED=0`` 은 기본값일 뿐이라
  화면 값이 이긴다(다른 설정과 같은 층 — `settings.py` 머리말).
- **측정 판은 무조건 끈다**(`measurement_reason`). 2026-08-27 측정에서 24판 중 6판이 다중 파일 조건으로 클로드에게
  빠져 로컬 실력이 부풀어 보였다. 판 단위로 잡아 두고(`hold_for_job`) 갈래 · 강제 호출 · 도구 손 세 자리가 모두 본다.
- **클로드 명령이 없거나 로그인 흔적이 없으면 켤 수 없다**(`cli_status`). 명령을 실행해 보지 않는다 — 실행 파일과
  로그인 파일만 본다.
- 넘겼으면 **답에 그 사실을 적는다**(`handoff_line`). 진행 줄에도 「클로드(내 구독)에게 넘깁니다」가 먼저 뜬다.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import project_env
from .models import RiskLevel
from .tool_gateway import InverseSpec, ToolGateway, ToolSpec


CLAUDE_CODE_TOOL = "claude_code_delegate"

_MULTI_FILE = re.compile(
    r"(?:여러|다중|복수|두|2\s*개|둘\s*이상).{0,16}(?:파일|모듈|컴포넌트)|"
    r"(?:multi[- ]?file|multiple\s+files)",
    re.IGNORECASE,
)
_GIT_REPOSITORY = re.compile(
    r"(?:git|깃)\s*(?:저장소|레포지토리|레포|repo)|"
    r"(?:repository|repo)\s*(?:안|에서|전체|수정|리팩터|refactor)",
    re.IGNORECASE,
)
_UNKNOWN_ENDING = re.compile(
    r"(?:모르겠|알\s*수\s*없|해결하지\s*못|제가\s*못|방법을\s*찾지\s*못)",
    re.IGNORECASE,
)
_TEST_COMMAND = re.compile(
    r"(?:pytest|unittest|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|"
    r"yarn\s+test|cargo\s+test|go\s+test|dotnet\s+test)",
    re.IGNORECASE,
)
_CODE_FILE = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/])?[\w.@+()\- \\/]+\.(?:py|js|jsx|ts|tsx|java|"
    r"kt|go|rs|cs|cpp|c|h|html|css|vue|svelte|json|ya?ml|toml))",
    re.IGNORECASE,
)
_QUOTED_WINDOWS_PATH = re.compile(r"[\"'`](?P<path>[A-Za-z]:\\[^\"'`\r\n]+)[\"'`]")
_WINDOWS_PATH_START = re.compile(r"(?P<path>[A-Za-z]:\\[^\r\n]+)")


class ClaudeCodeError(RuntimeError):
    pass


#: 우리 측정 스크립트가 스스로 붙인 이름의 낱말. 세션 이름(`code-repo-bench-*` · `measure-chain-*` · `bench-polyglot-*` ·
#:   `q4-golden-*` · `route-probe-*` · `ladder-*`)과 맡긴 쪽 이름(`bench-om2w` · `honesty-bench`)에서 본다.
#:   ★ 2026-08-27 의 6/24 는 `scripts/bench_code_repo_agent.py`(세션 `code-repo-bench-*`)에서 나왔다.
#:   이름으로 못 잡는 스크립트는 요청에 ``"measurement": true`` 를 싣는다(측정 꾸러미 `measure_kit` 은 싣는다).
_MEASUREMENT_MARK = re.compile(r"bench|measure|rerun|probe|golden|ladder", re.IGNORECASE)


def measurement_reason(payload: Any, session_id: str = "") -> str:
    """이 판이 측정 판이면 그 까닭 코드, 아니면 빈 문자열. 측정 판은 사용자 설정과 무관하게 클로드에게 넘기지 않는다."""
    if not isinstance(payload, dict):
        return ""
    if payload.get("measurement") is True:
        return "measurement_flag"
    if _MEASUREMENT_MARK.search(str(payload.get("caller") or "")):
        return "measurement_caller"
    if _MEASUREMENT_MARK.search(str(session_id or payload.get("session_id") or "")):
        return "measurement_session"
    return ""


def hold_reason(payload: Any, session_id: str = "") -> str:
    """이 판에서 클로드에게 넘기지 않을 까닭. 빈 문자열이면 사용자 설정을 따른다.

    - 측정 판(`measurement_reason`).
    - **클로드 코드가 맡긴 판**(MCP · caller 가 Claude Code). 클로드가 손자리에 맡긴 일을 손자리가 막혔다고 새 클로드 코드
      세션에 되넘기면 같은 구독을 두 번 쓰고 맡긴 쪽은 그 사실을 모른다 — 막힌 자리는 맡긴 클로드에게 답으로 돌려준다.
    """
    measured = measurement_reason(payload, session_id)
    if measured:
        return measured
    if isinstance(payload, dict) and str(payload.get("origin") or "") == "mcp":
        from .delegation import is_claude_code  # 늦게 — 맡기기 모듈은 정제 · 근거 모듈을 끌고 온다
        from .messaging.bridge import CALLER as PERSON_BRIDGE  # 디스코드 다리 — 폰으로 사람이 시킨 일

        caller = str(payload.get("caller") or "")
        if is_claude_code(caller):
            return "delegated_by_claude_code"
        # ★ 2026-10-26 대표: 「클로드 앱이 MCP 로 시킨 일은 무조건 로컬 모델로만 — 클로드 API 로 가면 안 된다」.
        #   클로드 코드만 막던 때 최근 14일 MCP 판 722 중 426판이 부른 쪽 이름이 비어(클로드 앱 등) 막히지 않았다.
        #   바깥 AI 가 맡긴 판은 이름이 무엇이든(비어도) 막는다 — 사람이 시킨 디스코드 다리만 사용자 설정을 따른다.
        if caller != PERSON_BRIDGE:
            return "delegated_by_outside_ai"
    return ""


#: 넘긴 까닭 — 사람에게 보이는 말. 코드에 없는 까닭은 원래 코드 그대로 낸다(숨기지 않는다).
HANDOFF_REASONS: dict[str, str] = {
    "multi_file_request": "여러 파일을 함께 고치는 일이라서",
    "git_repository_request": "저장소 전체를 다루는 일이라서",
    "sandbox_same_file_failed_twice": "같은 파일에서 두 번 막혀서",
    "tests_still_failing": "고친 뒤에도 테스트가 계속 실패해서",
    "local_agent_about_to_give_up": "손자리가 방법을 찾지 못해서",
    "resume_after_budget": "앞서 넘긴 일을 같은 세션에서 이어서",
    "big_code_user_chose": "직접 클로드에게 맡기기를 골라서",
}
#: 답 · 진행 줄에 들어가는 고정 말머리. 이 낱말이 이미 답에 있으면 한 번 더 붙이지 않는다.
HANDOFF_MARK = "클로드(내 구독)에게 넘겨"


def handoff_reason_text(reason: str) -> str:
    code = str(reason or "").strip()
    return HANDOFF_REASONS.get(code, code or "막혀서")


def handoff_line(reason: str, *, completed: bool = True) -> str:
    """넘긴 판의 답에 붙는 한 줄. 끝내지 못했으면 그렇다고 적는다 — 그 판의 답은 손자리가 낸 것이다."""
    why = handoff_reason_text(reason)
    if completed:
        return f"이 일은 클로드(내 구독)에게 넘겨 처리했습니다 · 이유: {why}"
    return f"이 일을 클로드(내 구독)에게 넘겨 봤지만 끝내지 못했습니다 · 이유: {why}"


def handoff_receipt(steps: list[dict[str, Any]]) -> str:
    """판의 걸음에 클로드에게 넘긴 걸음이 있으면 영수증 한 줄, 없으면 빈 문자열."""
    rows = [step for step in steps or [] if str(step.get("tool") or "") == CLAUDE_CODE_TOOL]
    if not rows:
        return ""
    first_args = rows[0].get("arguments") if isinstance(rows[0].get("arguments"), dict) else {}
    last = rows[-1].get("evidence") if isinstance(rows[-1].get("evidence"), dict) else {}
    completed = bool(rows[-1].get("ok")) and str(last.get("status") or "") == "completed"
    reason = str(first_args.get("reason") or last.get("reason") or "")
    return handoff_line(reason, completed=completed)


def with_handoff_receipt(answer: str, steps: list[dict[str, Any]]) -> str:
    """넘긴 판이면 답 끝에 영수증 한 줄을 붙인다. 이미 적혀 있으면(`completion_answer`) 그대로 둔다."""
    line = handoff_receipt(steps)
    if not line or HANDOFF_MARK in str(answer or ""):
        return answer
    return str(answer or "").rstrip() + "\n\n" + line


def _claude_config_dir() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(configured) if configured else Path.home() / ".claude"


def signed_in() -> bool:
    """로그인 흔적이 있는가 — 명령을 실행하지 않고 파일만 본다(값은 읽어 내보내지 않는다).

    Windows 의 Claude Code 는 구독 로그인을 ``~/.claude/.credentials.json`` 에 둔다. 예전 판은 ``~/.claude.json`` 의
    ``oauthAccount`` 칸에 계정을 적었다. 둘 다 없으면 로그인 전이다.
    """
    if (_claude_config_dir() / ".credentials.json").is_file():
        return True
    try:
        text = (Path.home() / ".claude.json").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return '"oauthAccount"' in text


def command_prefix(config: Any) -> list[str]:
    configured = str(getattr(config, "claude_code_command", "claude") or "claude")
    found = shutil.which(configured) if not Path(configured).is_file() else configured
    if not found:
        raise ClaudeCodeError("claude_code_cli_not_found")
    path = Path(found)
    if path.suffix.lower() in {".cmd", ".bat"}:
        # 최신 Claude Code npm 패키지는 예전 ``cli.js`` 대신 네이티브
        # ``bin/claude.exe``를 래퍼에서 직접 실행한다. 셸을 켜서 .cmd를 부르면
        # 프롬프트 인자 인젝션 면적이 생기므로 실행 파일을 shell=False로 부른다.
        native = (
            path.parent
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
            / "bin"
            / "claude.exe"
        )
        if native.is_file():
            return [str(native)]
        node = shutil.which("node")
        cli = path.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        if not node or not cli.is_file():
            raise ClaudeCodeError("claude_code_node_entry_not_found")
        return [node, str(cli)]
    return [str(path)]


#: 켤 수 없는 까닭 → 화면 말(긴 설명 · 짧은 상태). 짧은 말은 「이 판에서는 못 씁니다」 자리에 들어간다.
CLI_BLOCKS: dict[str, tuple[str, str]] = {
    "locked": ("관리자가 이 PC 에서 꺼 두었습니다.", "관리자가 꺼 둠"),
    "not_installed": ("이 PC 에 Claude Code(claude 명령)가 없습니다. 설치하고 로그인하면 켤 수 있습니다.", "Claude Code 없음"),
    "not_signed_in": ("Claude Code 에 로그인하지 않았습니다. 명령 창에서 claude 를 한 번 실행해 로그인하면 켤 수 있습니다.",
                      "로그인 필요"),
}


def cli_status(config: Any) -> dict[str, Any]:
    """「막히면 내 클로드에게 넘기기」를 **켤 수 있는가.** 켜져 있는가와는 다른 질문이다.

    빈 ``code`` 면 켤 수 있다. 명령을 실행해 보지 않는다(구독 사용량을 쓰지 않고, 창도 안 뜬다).
    """
    if bool(getattr(config, "claude_code_locked", False)):
        code = "locked"
    else:
        try:
            command_prefix(config)
            code = "" if signed_in() else "not_signed_in"
        except ClaudeCodeError:
            code = "not_installed"
    reason, short = CLI_BLOCKS.get(code, ("", ""))
    return {"ok": not code, "code": code, "reason": reason, "short": short}


@dataclass(frozen=True, slots=True)
class DelegationDecision:
    reason: str
    resume_session_id: str = ""


def initial_delegation_reason(prompt: str) -> str:
    """첫 턴부터 로컬 코더보다 팀코칭이 싼, 명시적인 두 모양."""
    compact = " ".join(str(prompt or "").split())
    if _MULTI_FILE.search(compact):
        return "multi_file_request"
    if _GIT_REPOSITORY.search(compact):
        return "git_repository_request"
    return ""


def completion_answer(evidence: dict[str, Any]) -> str:
    """성공 결과를 두 번째 LLM 호출 없이 사용자 답으로 만든다.

    세션 ID는 재개용 내부 상태이고 화면 답에는 필요 없다. 비용은 숨기지 않는다.
    ★ 2026-10-19: 맨 끝에 「클로드(내 구독)에게 넘겨 처리했다 · 이유」 한 줄 — 넘긴 일은 넘겼다고 말한다.
    """
    result = str(evidence.get("result") or "").strip()
    if not result:
        result = "Claude Code가 지목한 폴더의 코딩 작업과 검증을 완료했습니다."
    cost = float(evidence.get("total_cost_usd") or 0.0)
    line = handoff_line(str(evidence.get("reason") or ""))
    return f"{result}\n\nClaude Code 완료 · 예상비용 ${cost:.4f}\n{line}"


def _sandbox_failed(step: dict[str, Any]) -> bool:
    if str(step.get("tool") or "") != "sandbox_run":
        return False
    evidence = step.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    if not step.get("ok") or evidence.get("ok") is False:
        return True
    try:
        return int(evidence.get("exit_code") or 0) != 0
    except (TypeError, ValueError):
        return True


def _sandbox_target(step: dict[str, Any]) -> str:
    arguments = step.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    for key in ("path", "output_path", "filename", "file"):
        value = str(arguments.get(key) or "").strip()
        if value:
            return value.lower()
    files = arguments.get("files")
    if isinstance(files, list) and files:
        value = str(files[0] or "").strip()
        if value:
            return value.lower()
    code = str(arguments.get("code") or "")
    found = _CODE_FILE.search(code)
    return str(found.group("path") if found else "").strip().lower()


def _same_file_failed_twice(steps: list[dict[str, Any]]) -> bool:
    attempts = [step for step in steps if _sandbox_failed(step)]
    if len(attempts) < 2:
        return False
    left, right = attempts[-2:]
    left_target, right_target = _sandbox_target(left), _sandbox_target(right)
    return bool(left_target and left_target == right_target)


def _tests_still_failing(steps: list[dict[str, Any]]) -> bool:
    """마지막 테스트 실행이 실패했는가. 성공한 재실행이 뒤에 있으면 이미 해결됐다."""
    for step in reversed(steps):
        if str(step.get("tool") or "") != "sandbox_run":
            continue
        arguments = step.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        if not _TEST_COMMAND.search(str(arguments.get("code") or "")):
            continue
        return _sandbox_failed(step)
    return False


def _last_claude_session(steps: list[dict[str, Any]]) -> tuple[str, str]:
    for step in reversed(steps):
        if str(step.get("tool") or "") != CLAUDE_CODE_TOOL:
            continue
        evidence = step.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        return str(evidence.get("session_id") or ""), str(evidence.get("status") or "")
    return "", ""


def delegation_decision(
    prompt: str,
    steps: list[dict[str, Any]],
    *,
    answer: str = "",
    coding_request: bool = True,
    max_calls: int = 2,
) -> DelegationDecision | None:
    """LLM의 취향을 묻지 않고 위임 여부를 한 벌의 규칙으로 정한다."""
    if not coding_request:
        return None
    claude_steps = [step for step in steps if str(step.get("tool") or "") == CLAUDE_CODE_TOOL]
    if len(claude_steps) >= max(1, max_calls):
        return None
    session_id, status = _last_claude_session(steps)
    if session_id and status == "waiting_continuation":
        return DelegationDecision("resume_after_budget", session_id)
    # 첫 위임 뒤에 다시 판정할 때는 그 위임 **뒤의** 로컬 실패만 본다.
    after = steps
    if claude_steps:
        last_index = max(i for i, step in enumerate(steps) if step in claude_steps)
        after = steps[last_index + 1 :]
    if not claude_steps:
        reason = initial_delegation_reason(prompt)
        if reason:
            return DelegationDecision(reason)
    if _same_file_failed_twice(after):
        return DelegationDecision("sandbox_same_file_failed_twice", session_id)
    if _tests_still_failing(after):
        return DelegationDecision("tests_still_failing", session_id)
    if answer and _UNKNOWN_ENDING.search(answer):
        return DelegationDecision("local_agent_about_to_give_up", session_id)
    return None


def build_command(
    prefix: list[str],
    *,
    prompt: str,
    folder: Path,
    resume_session_id: str = "",
) -> list[str]:
    """구독 로그인 경로. ``--bare``가 들어가면 이 검사가 즉시 깨져야 한다."""
    command = [
        *prefix,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--add-dir",
        str(folder),
        "--allowedTools",
        "Read,Edit,Bash",
    ]
    if resume_session_id:
        command.extend(["--resume", resume_session_id])
    return command


class ClaudeCodeTools:
    def __init__(self, config: Any, events: Any, local_computer: Any) -> None:
        self.config = config
        self.events = events
        self.local_computer = local_computer

    @property
    def names(self) -> set[str]:
        return {CLAUDE_CODE_TOOL}

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        # 이 도구를 모델에게 고르게 하지 않는다. 아래 스키마는 게이트웨이·승인 화면의
        # 계약이고, 호출 시점은 ``delegation_decision``이 정한다.
        return []

    @staticmethod
    def _definition() -> dict[str, Any]:
        return {
            # 화면 라벨 검사가 소스에서 도구 이름을 정적으로 뽑는다. 상수만 쓰면
            # 실제 도구인데도 "없는 라벨"로 읽으므로 계약 자리에는 이름을 남긴다.
            "name": "claude_code_delegate",
            "description": (
                "결정론 위임 조건이 충족됐을 때 지목한 폴더를 Claude Code에 맡기고 "
                "세션·결과·예상비용을 기록한다. 모델이 임의로 고르는 도구가 아니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "folder": {"type": "string"},
                    "reason": {"type": "string"},
                    "resume_session_id": {"type": "string"},
                },
                "required": ["prompt", "folder", "reason"],
            },
        }

    def _command_prefix(self) -> list[str]:
        return command_prefix(self.config)

    def switched_on(self) -> bool:
        """사람이 켰는가(관리자 잠금이 없을 때). 화면 값은 `settings` 가 설정 객체에 얹어 두었다."""
        return bool(getattr(self.config, "claude_code_enabled", False)) and not bool(
            getattr(self.config, "claude_code_locked", False)
        )

    def hold_for_job(self, job_id: str, reason: str) -> None:
        """이 판에서는 넘기지 않는다(측정 판). 빈 까닭이면 아무것도 안 한다 — 판 번호는 판마다 새것이다."""
        if not job_id or not reason:
            return
        held = self.__dict__.setdefault("_held", {})
        held[str(job_id)] = str(reason)
        while len(held) > 500:  # 오래 켜 둔 앱에서 끝없이 쌓이지 않게. 오래된 판부터 잊는다.
            held.pop(next(iter(held)))
        self.events.publish("claude_code_held", {"job_id": str(job_id), "reason": str(reason)})

    def held_reason(self, job_id: str) -> str:
        return str(self.__dict__.get("_held", {}).get(str(job_id or ""), ""))

    def available(self, job_id: str = "") -> bool:
        """이 판에서 지금 넘길 수 있는가 — 켰고 · 측정 판이 아니고 · 클로드 명령과 로그인 흔적이 있다.

        켜 둔 뒤에 로그아웃했으면 여기서 걸러진다 — 넘겼다가 「로그인 필요」로 실패한 판을 만들지 않는다.
        """
        if not self.switched_on():
            return False
        if job_id and self.held_reason(job_id):
            return False
        return bool(cli_status(self.config).get("ok"))

    def folder_for(self, prompt: str, *, required_path: str = "", job_id: str = "") -> Path:
        if required_path:
            resolved = self.local_computer.resolve_allowed_path(required_path, must_exist=True)
            return resolved if resolved.is_dir() else resolved.parent
        compact = str(prompt or "")
        candidates = [match.group("path") for match in _QUOTED_WINDOWS_PATH.finditer(compact)]
        if not candidates:
            raw = _WINDOWS_PATH_START.search(compact)
            if raw:
                # 따옴표 없는 경로 뒤에 자연어가 이어질 수 있다. 존재하는 가장 긴
                # 접두사를 찾으면 "E:\repo에서 고쳐"의 조사까지 삼키지 않는다.
                value = raw.group("path").strip()
                candidates.extend(value[:cut].rstrip(" ,.;:)]}에서를은는") for cut in range(len(value), 2, -1))
        for candidate in candidates:
            try:
                resolved = self.local_computer.resolve_allowed_path(candidate, must_exist=True)
            except Exception:
                continue
            return resolved if resolved.is_dir() else resolved.parent
        # Code 모드에서 사람이 고른 저장소는 추측이 아니라 API가 검증해 이 잡에
        # 묶어 둔 유일한 쓰기 루트다. 그것을 무시하고 빈 잡 책상을 넘기면 위임받은
        # 쪽은 고칠 파일이 하나도 없는 폴더에서 일한다 — 실제로 그렇게 돌았다.
        authorized = self.local_computer.code_workspace(job_id)
        if authorized is not None:
            return authorized
        # 폴더를 지목하지 않았다고 현재 저장소 전체를 추측해 맡기지 않는다. 잡 전용
        # 책상은 범위가 작고, git이 아니므로 L2에서 한 번 더 드러난다.
        return self.local_computer.job_workspace(job_id, create=True)

    @staticmethod
    def _git(folder: Path, *arguments: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(folder), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )

    def _git_state(self, folder: Path) -> dict[str, Any]:
        root = self._git(folder, "rev-parse", "--show-toplevel")
        if root.returncode != 0:
            return {"is_repo": False, "root": str(folder), "clean": False, "head": "", "status": ""}
        repo = Path(root.stdout.strip()).resolve(strict=False)
        status = self._git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        head = self._git(repo, "rev-parse", "HEAD")
        return {
            "is_repo": True,
            "root": str(repo),
            "clean": status.returncode == 0 and not status.stdout.strip(),
            "head": head.stdout.strip() if head.returncode == 0 else "",
            "status": status.stdout[:12_000],
        }

    def _changed_paths(self, folder: Path, before_head: str) -> list[str]:
        """기준 커밋 뒤 실제로 남은 파일. P5 산출물 대조가 다시 열 경로다."""
        state = self._git_state(folder)
        if not state.get("is_repo"):
            return []
        repo = Path(str(state.get("root") or folder))
        names: list[str] = []
        if before_head:
            changed = self._git(repo, "diff", "--name-only", before_head, "--")
            if changed.returncode == 0:
                names.extend(changed.stdout.splitlines())
        untracked = self._git(repo, "ls-files", "--others", "--exclude-standard")
        if untracked.returncode == 0:
            names.extend(untracked.stdout.splitlines())
        paths: list[str] = []
        for name in dict.fromkeys(item.strip() for item in names if item.strip()):
            path = (repo / name).resolve(strict=False)
            try:
                path.relative_to(repo)
            except ValueError:
                continue
            if path.is_file():
                paths.append(str(path))
        return paths

    def _resolve_folder(self, arguments: dict[str, Any]) -> Path:
        raw = str(arguments.get("folder") or "").strip()
        if not raw:
            raise ValueError("claude_code_folder_required")
        path = self.local_computer.resolve_allowed_path(raw, must_exist=True)
        if not path.is_dir():
            raise NotADirectoryError("claude_code_folder_required")
        return path

    def _risk(self, arguments: dict[str, Any]) -> RiskLevel:
        try:
            state = self._git_state(self._resolve_folder(arguments))
        except Exception:
            return RiskLevel.L2
        return RiskLevel.L1 if state["is_repo"] and state["clean"] else RiskLevel.L2

    def _publish_progress(self, job_id: str, step: int, message: str) -> None:
        if not job_id:
            return
        payload = {
            "job_id": job_id,
            "phase": "tool",
            "message": message[:300],
            "step": max(1, step),
            "tool": CLAUDE_CODE_TOOL,
            "status": "running",
        }
        self.events.publish("agent_progress", payload)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    @staticmethod
    def _text_from_event(event: dict[str, Any]) -> str:
        if event.get("type") != "assistant":
            return ""
        message = event.get("message")
        message = message if isinstance(message, dict) else {}
        rows: list[str] = []
        for item in message.get("content") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                rows.append(str(item["text"]))
            elif item.get("type") == "tool_use":
                rows.append(f"도구 사용: {item.get('name') or 'unknown'}")
        return " ".join(rows).strip()

    def delegate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        job_id = str(arguments.get("__job_id") or "")
        # ★ 손 자체에서도 한 번 더 본다 — 갈래 · 강제 호출이 놓쳐도 여기서 멈춘다(측정 판이 부풀던 자리, 2026-08-27).
        if not self.switched_on():
            raise ClaudeCodeError("claude_code_switched_off")
        if self.held_reason(job_id):
            raise ClaudeCodeError(f"claude_code_off_for_measurement:{self.held_reason(job_id)}")
        folder = self._resolve_folder(arguments)
        prompt = str(arguments.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("claude_code_prompt_required")
        reason = str(arguments.get("reason") or "deterministic_delegation")[:120]
        resume_session_id = str(arguments.get("resume_session_id") or "").strip()
        step = int(arguments.get("_step") or 1)
        before = self._git_state(folder)
        prefix = self._command_prefix()
        command = build_command(
            prefix, prompt=prompt, folder=folder, resume_session_id=resume_session_id
        )
        if "--bare" in command:
            raise ClaudeCodeError("claude_code_bare_forbidden")

        # 손자리 자신의 설정(`JARVIS_*`)은 넘기지 않는다 — Claude Code 도 그 폴더에서 아무 명령이나 돌린다.
        environment = project_env.without_our_settings(dict(os.environ))
        # 이 배선은 사용자의 claude.ai 구독 로그인을 쓰는 것으로 결정됐다. 우연히
        # 남아 있는 API 키가 비용 경로를 바꾸지 못하게 한다.
        environment.pop("ANTHROPIC_API_KEY", None)
        environment.pop("ANTHROPIC_AUTH_TOKEN", None)
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            command,
            cwd=str(folder),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=flags,
        )
        lines: queue.Queue[tuple[str, str | None]] = queue.Queue()

        def read_pipe(kind: str, stream: Any) -> None:
            try:
                for line in iter(stream.readline, ""):
                    lines.put((kind, line.rstrip("\r\n")))
            finally:
                lines.put((kind, None))

        readers = [
            threading.Thread(target=read_pipe, args=("stdout", process.stdout), daemon=True),
            threading.Thread(target=read_pipe, args=("stderr", process.stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()

        started = time.monotonic()
        lease = max(5, int(getattr(self.config, "claude_code_lease_sec", 90)))
        session_id = resume_session_id
        final: dict[str, Any] | None = None
        stderr_rows: list[str] = []
        streams_done: set[str] = set()
        timed_out = False
        # 진행 줄의 첫 말 — 사람이 「지금 내 구독을 쓰는 중」인 줄 알아야 한다(2026-10-19).
        self._publish_progress(
            job_id, step,
            "막혀서 클로드(내 구독)에게 넘깁니다 · 이유: " + handoff_reason_text(reason)
            if not resume_session_id
            else "클로드(내 구독)에게 넘긴 일을 이어 갑니다 · 이유: " + handoff_reason_text(reason),
        )
        while len(streams_done) < 2 or process.poll() is None:
            if time.monotonic() - started >= lease and process.poll() is None:
                timed_out = True
                self._terminate(process)
            try:
                kind, line = lines.get(timeout=0.2)
            except queue.Empty:
                if process.poll() is not None and all(not reader.is_alive() for reader in readers):
                    break
                continue
            if line is None:
                streams_done.add(kind)
                continue
            if kind == "stderr":
                if sum(len(row) for row in stderr_rows) < 8_000:
                    stderr_rows.append(line)
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            session_id = str(event.get("session_id") or session_id)
            event_type = str(event.get("type") or "")
            if event_type == "system" and event.get("subtype") == "init":
                self._publish_progress(job_id, step, "Claude Code가 지목한 폴더를 읽기 시작했습니다")
            text = self._text_from_event(event)
            if text:
                self._publish_progress(job_id, step, f"Claude Code: {text[:220]}")
            if event_type == "result":
                final = event
        rc = process.wait(timeout=10)
        elapsed = round(time.monotonic() - started, 2)
        after = self._git_state(folder)
        changed_paths = self._changed_paths(folder, str(before.get("head") or ""))
        changed = bool(
            before.get("head") != after.get("head")
            or before.get("status") != after.get("status")
        )
        if timed_out:
            if not session_id:
                raise ClaudeCodeError("claude_code_budget_expired_without_session")
            return {
                "action": CLAUDE_CODE_TOOL,
                "status": "waiting_continuation",
                "reason": reason,
                "folder": str(folder),
                "session_id": session_id,
                "resumed": bool(resume_session_id),
                "total_cost_usd": float((final or {}).get("total_cost_usd") or 0.0),
                "elapsed_sec": elapsed,
                "timed_out": True,
                "git_clean_before": bool(before.get("clean")),
                "git_changed": changed,
                "changed_paths": changed_paths,
                "instruction": "★ Claude Code 세션을 저장했다. 같은 작업을 새로 시작하지 말고 --resume으로 이어라.",
            }
        if final is None:
            detail = "\n".join(stderr_rows)[-2000:]
            raise ClaudeCodeError(f"claude_code_result_missing:rc={rc}:{detail}")
        if rc != 0 or final.get("is_error") is True or final.get("subtype") != "success":
            detail = str(final.get("result") or "\n".join(stderr_rows) or "claude_code_failed")
            raise ClaudeCodeError(detail[:2000])
        result_text = str(final.get("result") or "").strip()
        maximum = max(1_000, int(getattr(self.config, "claude_code_result_max_chars", 16_000)))
        undo_handle = None
        if before.get("is_repo") and before.get("clean") and changed:
            undo_handle = {
                "repo": str(after.get("root") or before.get("root") or folder),
                "before_head": str(before.get("head") or ""),
                "after_head": str(after.get("head") or ""),
                "after_status": str(after.get("status") or ""),
                "job_id": job_id,
            }
        return {
            "action": CLAUDE_CODE_TOOL,
            "status": "completed",
            "reason": reason,
            "folder": str(folder),
            "session_id": str(final.get("session_id") or session_id),
            "resumed": bool(resume_session_id),
            "result": result_text[:maximum],
            "result_truncated": len(result_text) > maximum,
            "total_cost_usd": float(final.get("total_cost_usd") or 0.0),
            "duration_ms": int(final.get("duration_ms") or round(elapsed * 1000)),
            "elapsed_sec": elapsed,
            "model": str(final.get("model") or ""),
            "git_clean_before": bool(before.get("clean")),
            "git_changed": changed,
            "changed_paths": changed_paths,
            "verified": True,
            "undo_handle": undo_handle,
        }

    @staticmethod
    def _undo_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        handle = result.get("undo_handle")
        return dict(handle) if isinstance(handle, dict) else None

    def _undo(self, handle: dict[str, Any]) -> dict[str, Any]:
        repo = Path(str(handle.get("repo") or "")).resolve(strict=False)
        current = self._git_state(repo)
        if str(current.get("head") or "") != str(handle.get("after_head") or ""):
            raise RuntimeError("undo_target_drifted")
        if str(current.get("status") or "") != str(handle.get("after_status") or ""):
            raise RuntimeError("undo_target_drifted")
        stash_ref = ""
        if str(current.get("status") or ""):
            stash = self._git(
                repo,
                "stash",
                "push",
                "--include-untracked",
                "-m",
                f"jarvis-undo-{str(handle.get('job_id') or '')[:40]}",
                timeout=60,
            )
            if stash.returncode != 0:
                raise RuntimeError(f"git_stash_failed:{stash.stderr[:300]}")
            latest = self._git(repo, "rev-parse", "stash@{0}")
            stash_ref = latest.stdout.strip() if latest.returncode == 0 else "stash@{0}"
        before_head = str(handle.get("before_head") or "")
        if before_head and str(current.get("head") or "") != before_head:
            backup_ref = f"refs/jarvis/undo/{int(time.time())}"
            saved = self._git(repo, "update-ref", backup_ref, str(current.get("head") or ""))
            if saved.returncode != 0:
                raise RuntimeError(f"git_backup_ref_failed:{saved.stderr[:300]}")
            reset = self._git(repo, "reset", "--hard", before_head, timeout=60)
            if reset.returncode != 0:
                raise RuntimeError(f"git_reset_failed:{reset.stderr[:300]}")
        verified = self._git_state(repo)
        if str(verified.get("head") or "") != before_head or not verified.get("clean"):
            raise RuntimeError("git_undo_unverified")
        return {
            "repo": str(repo),
            "verified": True,
            "restored_head": before_head,
            "stash_ref": stash_ref,
        }

    def register(self, gateway: ToolGateway) -> None:
        definition = self._definition()
        gateway.register(
            ToolSpec(
                name=CLAUDE_CODE_TOOL,
                description=str(definition["description"]),
                parameters=dict(definition["parameters"]),
                risk_level=RiskLevel.L1,
                dynamic_risk=self._risk,
                handler=self.delegate,
                # 화면에서 켜고 끄면 런타임이 다시 등록한다(`runtime._settings_changed`).
                enabled=self.switched_on(),
                inverse=InverseSpec(
                    label="Claude Code가 만든 git 변경을 임시 보관하고 원상복구",
                    handle_from=self._undo_handle,
                    undo=self._undo,
                ),
                needs_job_context=True,
            )
        )
