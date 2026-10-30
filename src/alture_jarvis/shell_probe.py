"""**읽기 전용 셸** — 자비스가 스스로 파고들 수 있게, 그러나 아무것도 못 바꾸게.

## 왜 (2026-08-21)

`self_check` 는 정해진 다섯 기관만 본다. 그런데 진짜 진단은 그 뒤에 온다 —
"8091 이 안 뜬다" 다음은 **"누가 그 포트를 잡고 있나"**, 그다음은 "그 프로세스가
뭔가"다. 도구를 105개 만들어도 106번째 상황은 온다. 터미널이 핵심인 진짜 이유는
**우리가 안 만든 도구를 전부 대신한다**는 것이다.

## 그런데 위험한 것은 「터미널」이 아니다

위험한 것은 **되돌릴 수 없는 곳에서 실행하는 것**이다. 이 둘은 분리된다.

    클라우드 에이전트가 터미널을 마음껏 쓰는 이유는 담대해서가 아니라
    **버릴 수 있는 VM 안에 있기 때문이다** (`test_undo.py` 서두).

자비스는 사용자 진짜 PC 위에서 돈다. 그래서 이 파일은 **부작용이 없는 것만** 연다.
자유 셸은 언젠가 격리 상자 안에서 열 일이지 여기서 열 일이 아니다.

## ★ 차단목록은 이기는 게임이 아니다

"위험한 명령만 막자"는 셸에서 **절대 성립하지 않는다.**

    powershell -enc <base64>      막을 문자열이 없다
    python -c "import os; ..."    한 줄로 뭐든
    cmd /c "..."                  그 안은 다시 셸이다

그래서 **허용목록만** 쓴다. 그리고 그 목록에 **인터프리터를 하나라도 넣으면
그 순간 허용목록이 무의미해진다** — powershell·cmd·python·node·bash·wsl 은
영원히 여기 안 들어온다. 이 파일을 고치는 사람은 그 줄을 먼저 읽어라.

## 세 겹으로 막는다

    1. 실행파일이 허용목록에 있는가 (이름이 아니라 **절대경로로 풀어서**)
    2. 하위명령이 읽기인가 (`git push` 는 `git` 이지만 쓰기다)
    3. `shell=False` — 셸이 없으니 `|` `>` `&&` 가 **글자 그대로**다
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

from .config import JarvisConfig
from .events import EventBus
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec


# ★ **인터프리터 금지.** 하나라도 들어오면 위의 세 겹이 통째로 무의미해진다.
#   이 목록은 "위험해 보이는 것"이 아니라 **"셸이나 임의 코드를 여는 것"** 이다.
FORBIDDEN_EVER = frozenset(
    {
        "powershell", "pwsh", "cmd", "wsl", "bash", "sh", "zsh",
        "python", "python3", "py", "node", "deno", "ruby", "perl", "php",
        "wscript", "cscript", "mshta", "rundll32", "regsvr32",
        "reg", "regedit",  # 레지스트리는 읽기여도 여기서 안 연다
        "curl", "wget", "Invoke-WebRequest",  # 바깥으로 나가는 길 — 아래 참고
    }
)

# 허용목록. **부작용이 없는 것만.** 값은 (읽기로 인정하는 하위명령들, 설명).
# 빈 튜플이면 하위명령을 안 따진다(그 실행파일 자체가 읽기 전용이다).
ALLOWED: dict[str, tuple[tuple[str, ...], str]] = {
    "tasklist": ((), "지금 도는 프로세스"),
    "netstat": ((), "포트와 연결"),
    "ipconfig": ((), "네트워크 설정"),
    "nvidia-smi": ((), "그래픽카드 상태"),
    "where": ((), "실행파일이 어디 있나"),
    "systeminfo": ((), "윈도우 기본 정보"),
    "driverquery": ((), "드라이버 목록 — 어젯밤 3090 사고 같은 것을 판다"),
    # 아래 둘은 쓰기 하위명령이 있다. **읽기만 통과시킨다.**
    "sc": (("query", "queryex", "qc"), "서비스 상태"),
    "schtasks": (("/query",), "작업 스케줄러 조회"),
    "git": (
        ("status", "log", "diff", "show", "branch", "rev-parse", "remote", "describe"),
        "저장소 상태 — 무엇이 바뀌었나",
    ),
}

# 인자에 이 글자가 있으면 거절한다.
#
# `shell=False` 라 셸이 없고, 따라서 이 글자들은 이미 **글자 그대로** 넘어간다 —
# 즉 이 검사는 없어도 안전하다. 그런데도 두는 이유는 하나다: 나중에 누가
# `shell=True` 로 바꾸거나 인자를 문자열로 합치는 순간, 이 줄이 **마지막 방벽**이
# 된다. 방벽을 하나만 두면 그것이 무너질 때 아무것도 안 남는다.
SHELL_METACHARACTERS = frozenset("|&;<>`$(){}[]!\n\r\"'")

MAX_OUTPUT_CHARS = 20_000
TIMEOUT_SEC = 30


class ShellProbe:
    """허용목록에 있는 **읽기 전용** 명령만 돌린다."""

    def __init__(self, config: JarvisConfig, events: EventBus) -> None:
        self.config = config
        self.events = events
        self._definitions = self._build_definitions()

    # ── 판정 (화면·프로세스 없이 검사할 수 있게 순수 함수로) ──────────────

    @staticmethod
    def _base_name(command: str) -> str:
        """`C:\\...\\git.exe` → `git`. 경로로 목록을 우회하지 못하게."""
        name = str(command or "").strip().strip('"').replace("\\", "/").rsplit("/", 1)[-1]
        return name[:-4].lower() if name.lower().endswith(".exe") else name.lower()

    @classmethod
    def check(cls, command: str, args: list[str]) -> str:
        """돌려도 되는가. 되면 빈 문자열, 안 되면 **왜 안 되는지**."""
        name = cls._base_name(command)
        if not name:
            return "command_required — 무엇을 돌릴지 적어 주세요."
        if name in FORBIDDEN_EVER:
            return (
                f"interpreter_forbidden:{name} — 셸이나 임의 코드를 여는 것은 "
                "영원히 허용되지 않습니다. 이 목록이 열리면 허용목록 전체가 "
                "무의미해집니다. 필요한 것을 읽기 전용 명령으로 다시 말해 주세요."
            )
        if name not in ALLOWED:
            return (
                f"not_allowed:{name} — 돌릴 수 있는 것은 "
                f"{', '.join(sorted(ALLOWED))} 뿐입니다."
            )
        for arg in args:
            bad = SHELL_METACHARACTERS.intersection(str(arg))
            if bad:
                return f"argument_has_shell_characters:{''.join(sorted(bad))} — 인자에 못 씁니다."
        subcommands = ALLOWED[name][0]
        if subcommands:
            first = str(args[0]).lower() if args else ""
            if first not in subcommands:
                return (
                    f"subcommand_not_allowed:{name} {first or '(없음)'} — "
                    f"읽기 하위명령({', '.join(subcommands)})만 됩니다."
                )
        return ""

    # ── 실행 ─────────────────────────────────────────────────────────────

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = str(arguments.get("command") or "").strip()
        raw = arguments.get("args") or []
        if isinstance(raw, str):
            # 문자열로 오면 **쪼개지 않는다.** 쪼개는 순간 따옴표 규칙을 우리가
            # 다시 만들게 되고, 그것이 곧 셸이다. 목록으로 달라고 말한다.
            return {
                "action": "shell_probe",
                "ok": False,
                "error": "args_must_be_a_list — 인자는 목록으로 주세요(예: [\"-ano\"]).",
            }
        args = [str(item) for item in raw]

        why = self.check(command, args)
        if why:
            self.events.publish("shell_probe_refused", {"command": command, "why": why[:120]})
            return {"action": "shell_probe", "ok": False, "error": why}

        name = self._base_name(command)
        # ★ 이름이 아니라 **절대경로로 풀어서** 돌린다. PATH 앞쪽에 같은 이름의
        #   파일을 놓는 것으로 목록을 우회하지 못하게.
        resolved = shutil.which(name)
        if not resolved:
            return {
                "action": "shell_probe", "ok": False,
                "error": f"not_installed:{name} — 이 PC 에 없습니다.",
            }

        began = time.monotonic()
        try:
            # shell=False 가 이 파일의 심장이다. 셸이 없으니 `|` `>` `&&` 는
            # 해석되지 않고 **글자 그대로** 프로그램에 넘어간다.
            done = subprocess.run(
                [resolved, *args],
                capture_output=True, text=True, timeout=TIMEOUT_SEC,
                shell=False, check=False, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return {
                "action": "shell_probe", "ok": False, "command": name,
                "error": f"timeout — {TIMEOUT_SEC}초 안에 안 끝났습니다.",
            }
        except Exception as exc:  # noqa: BLE001
            return {"action": "shell_probe", "ok": False, "command": name, "error": str(exc)[:200]}

        stdout, cut = self._clip(done.stdout)
        result = {
            "action": "shell_probe",
            "ok": True,
            "command": name,
            "args": args,
            "exit_code": done.returncode,
            "stdout": stdout,
            "stderr": self._clip(done.stderr)[0],
            "elapsed_sec": round(time.monotonic() - began, 2),
        }
        if cut:
            # ★ 잘랐으면 **잘랐다고 말한다.** 조용히 자르면 없던 것과 구별이 안 된다.
            result["truncated"] = True
            result["truncated_note"] = f"출력이 길어 앞 {MAX_OUTPUT_CHARS:,}자만 남겼습니다."
        self.events.publish("shell_probe", {"command": name, "exit_code": done.returncode})
        return result

    @staticmethod
    def _clip(text: str) -> tuple[str, bool]:
        text = str(text or "")
        if len(text) <= MAX_OUTPUT_CHARS:
            return text, False
        return text[:MAX_OUTPUT_CHARS], True

    # ── 등록 ─────────────────────────────────────────────────────────────

    def _build_definitions(self) -> list[dict[str, Any]]:
        catalogue = " · ".join(f"{name}({info[1]})" for name, info in sorted(ALLOWED.items()))
        return [
            {
                "type": "function",
                "function": {
                    "name": "shell_probe",
                    "description": (
                        "읽기 전용 명령을 하나 돌려 지금 이 PC 상태를 직접 확인한다. "
                        "self_check 로 부족할 때, 어떤 도구가 계속 실패하는 이유를 파고들 때 쓴다. "
                        f"돌릴 수 있는 것: {catalogue}. "
                        "아무것도 바꾸지 않으며, powershell·python 같은 셸/인터프리터는 돌릴 수 없다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "enum": sorted(ALLOWED)},
                            "args": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": '인자 목록. 예: ["-ano"] · ["query", "W32Time"]',
                            },
                        },
                        "required": ["command"],
                    },
                },
            }
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {"shell_probe"}

    def register(self, gateway: ToolGateway) -> None:
        definition = self._definitions[0]["function"]
        gateway.register(
            ToolSpec(
                name="shell_probe",
                description=str(definition["description"]),
                parameters=dict(definition.get("parameters") or {}),
                # 읽기만 하고 아무것도 안 바꾼다 — 되돌릴 것이 없으니 L0.
                risk_level=RiskLevel.L0,
                handler=self.run,
                enabled=True,
            )
        )
