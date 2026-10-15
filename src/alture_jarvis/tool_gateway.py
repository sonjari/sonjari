from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .events import EventBus
from .jobs import ApprovalRequired, JobStore
from .models import ApprovalStatus, RiskLevel, ToolResult
from .permissions import ALWAYS_ASK, NEVER_BYPASS, WRITE_TOOL_NAMES
from .proof import ProofSpec

#: 사람에게 선택지로 묻는 도구(`ask_user.py`). 승인 틀을 빌려 멈추고, 답은 승인 기록에 실려 온다.
ASK_USER_TOOL = "ask_user"


ToolHandler = Callable[[dict[str, Any]], Any]

_FALSE_WORDS = frozenset({"false", "0", "no", "n", "off", "아니오", "아니요", ""})
_TRUE_WORDS = frozenset({"true", "1", "yes", "y", "on", "예", "네"})


def coerce_boolean_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """스키마에 **참/거짓(boolean)** 으로 적힌 칸이 글자로 오면 참/거짓으로 바꾼다. 다른 칸은 안 건드린다.

    ★ 2026-09-29 밤 한방 도전 W1: 모델이 `browser_type_at(..., submit="False")` 로 불렀다. 도구는 `bool("False")` —
      파이썬에서 **참**이다 — 로 읽어 칠 때마다 엔터를 눌렀고, 폼이 제출되며 값이 날아갔다. 같은 칸에 14번 쳤다.
      `bool(arguments.get(...))` 로 읽는 자리가 16곳(한글 문서 `replace_all` 도 — 「False」가 **전부 바꾸기**가 된다).
      자리마다 고치면 17번째에서 또 샌다 — 모든 호출이 지나는 이 문에서 스키마를 보고 한 번에 바꾼다.
      스키마가 글자(string)라고 한 칸은 그대로 둔다: 사용자가 폼에 「False」라는 **글자**를 넣으라고 할 수 있다.
    """
    properties = (schema or {}).get("properties") or {}
    changed: dict[str, Any] | None = None
    for key, value in arguments.items():
        if not isinstance(value, str) or (properties.get(key) or {}).get("type") != "boolean":
            continue
        word = value.strip().lower()
        if word in _FALSE_WORDS or word in _TRUE_WORDS:
            changed = changed if changed is not None else dict(arguments)
            changed[key] = word in _TRUE_WORDS
    return changed if changed is not None else arguments


#: 장부에 남길 인자. **값이 아니라 모양만** 남긴다.
#:
#: 2026-08-31: 어젯밤 벤치에서 `local_read_text_file` 이 47번 불렸는데, 그중 몇 번이
#: 줄 범위를 지목했는지 **셀 수가 없었다** — 장부에 `tool`/`ok`/`status` 만 있었다.
#: 「모델이 파일을 통째로 읽어서 전사가 부푼다」는 가설을 세워 놓고 분모가 없었다.
#: 고치기 전에 세는 자부터 만든다.
_AUDIT_ARG_KEYS = ("line_start", "line_end", "max_chars", "max_results", "limit", "offset")


def audit_shape(name: str, arguments: dict[str, Any], result: Any) -> dict[str, Any]:
    """도구 한 번의 **모양**. 본문·자격증명은 절대 안 담는다.

    담는 것은 셋뿐이다 — 범위를 지목했는가(`line_start`/`line_end`), 어떤 파일인가
    (이름만, 경로 전체는 안 남긴다), 얼마나 되돌려받았는가(`out_chars`).
    이 셋이면 "통째로 읽어서 전사가 부풀었다"를 셀 수 있다.
    """
    shape: dict[str, Any] = {}
    for key in _AUDIT_ARG_KEYS:
        value = arguments.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            shape[key] = value
    target = arguments.get("path") or arguments.get("root") or ""
    if target:
        # 이름만 남긴다. 전체 경로는 장부를 불리고 사람 폴더 구조까지 남긴다.
        shape["file"] = str(target).replace("\\", "/").rsplit("/", 1)[-1][:80]
    query = arguments.get("query")
    if query:
        shape["query_chars"] = len(str(query))
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, str):
            shape["out_chars"] = len(content)
        for key in ("count", "scanned"):
            value = result.get(key)
            if isinstance(value, int):
                shape[key] = value
        if result.get("truncated"):
            shape["truncated"] = True
    return shape


class UndoUnverified(RuntimeError):
    """역동작은 한 번 실행했지만 결과를 확인할 수 없었다.

    실행 전 실패와는 다르다. 이미 실행했으므로 offer 는 소비해야 하고, 다시 실행하면
    토글처럼 원래 동작을 되풀이할 수 있다. 그렇다고 `undone` 으로 쓰면 확인하지 않은
    성공을 장부에 남긴다. 게이트웨이가 이 예외만 제3상태로 기록한다.
    """

    def __init__(self, result: dict[str, Any], message: str = "undo_result_unverified") -> None:
        super().__init__(message)
        self.result = dict(result)


@dataclass(frozen=True)
class InverseSpec:
    """이 도구가 한 일을 **어떻게 되돌리는가.**

    자비스는 사용자 진짜 계정, 진짜 블로그, 진짜 파일 위에서 돈다. 클라우드 VM
    안에서 도는 에이전트는 틀리면 VM 을 버리면 되지만 여기서는 그럴 수가 없어서,
    지금까지 **되돌릴 수 없으니 미리 물어보는 것**으로 대신해 왔다. 승인 카드
    15개가 전부 그것이다.

    그런데 실제로는 대부분 되돌릴 수 있다 — 만든 일정은 지우면 되고, 임시저장은
    목록에서 빼면 된다. 역동작을 아무도 안 짜놨을 뿐이다.

    되돌릴 수 있으면 물어볼 이유가 줄고, 물어볼 이유가 줄면 그만큼 자율이 는다.
    **자율성은 더 대담해져서 얻는 게 아니라 되돌릴 수 있어서 얻는 것이다.**

    `undo` 가 없는 것은 "사람이 손으로 해야 한다"는 뜻이고, 그때는 `manual_hint`
    로 무엇을 어디서 해야 하는지 알려 준다. **되돌릴 수 없는 것(메일 발송)에는
    아예 이 명세를 달지 않는다** — 달아 두고 안 되는 것이 제일 나쁘다.
    """

    label: str
    # 커밋 결과에서 되돌리기에 필요한 값을 뽑는다. None 을 주면 이번 건은 되돌릴
    # 수 없다는 뜻이다(예: 저장이 확인되지 않아 무엇을 지울지 모른다).
    handle_from: Callable[[dict[str, Any]], dict[str, Any] | None]
    # 실제로 되돌리는 함수. None 이면 사람 몫이다.
    undo: Callable[[dict[str, Any]], Any] | None = None
    manual_hint: str = ""


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    risk_level: RiskLevel
    handler: ToolHandler
    enabled: bool = True
    # 인자의 JSON Schema. 각 도구 묶음이 이미 Ollama 용으로 들고 있던 것을 그대로
    # 흘려 보낸다.
    #
    # 게이트웨이가 이걸 갖고 있어야 하는 이유: 바깥(MCP)으로 도구를 내보낼 때
    # **이름과 설명만으로는 부를 수가 없다.** 스키마가 없으면 인자를 지어내게 되고,
    # 그건 도구를 안 주느니만 못하다. 모델용 정의와 게이트웨이 등록이 따로 놀면
    # 둘이 어긋나므로(오늘 프롬프트와 도구가 어긋나 사고가 났다) 한 곳에서 온다.
    parameters: dict[str, Any] = field(default_factory=dict)
    # 이 도구가 한 일을 되돌리는 방법. 없으면 되돌릴 수 없는 도구다.
    inverse: "InverseSpec | None" = None
    # 같은 도구라도 무엇에 대고 부르느냐로 위험이 갈리는 경우가 있다. 레시피가
    # 그렇다 — 읽기만 하는 절차를 확정하는 것과, 누르고 채우는 절차를 확정하는
    # 것은 같은 `site_promote_draft` 지만 되돌릴 것의 크기가 다르다.
    #
    # ★ 이 함수는 **등급을 올리기만 한다.** 등록된 `risk_level` 이 바닥이고 그
    # 아래로는 못 내려간다. 내릴 수 있게 만들면 이것이 곧 승인 우회로가 된다 —
    # `_approved` 인자가 정확히 그렇게 뚫려 있었다. 신뢰는 인자가 아니라 등록에서
    # 온다는 규칙을 여기서도 지킨다.
    dynamic_risk: Callable[[dict[str, Any]], RiskLevel] | None = None
    # 승인 당시 보고 있던 대상과 실제 실행 직전 대상을 묶고, 실행 결과까지 한
    # 봉투로 남긴다. 모든 도구에 억지로 적용하지 않고 외부 쓰기 중 근거를 제대로
    # 잡을 수 있는 도구만 명시적으로 단다.
    proof: ProofSpec | None = None
    # 모델에게는 보이지 않지만 실행 중인 잡의 작업폴더가 필요한 도구가 있다.
    # 모든 도구 인자에 job_id 를 섞으면 브라우저·외부 API로 내부 키가 새므로,
    # 명시한 도구에만 ``__job_id`` 를 건넨다.
    needs_job_context: bool = False

    def effective_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """이번 호출에 실제로 적용할 등급."""
        if self.dynamic_risk is None:
            return self.risk_level
        try:
            asked = RiskLevel.parse(self.dynamic_risk(arguments))
        except Exception:
            # 판단이 실패했으면 **모르는 것이다.** 모르면 사람 앞에 세운다.
            return max(self.risk_level, RiskLevel.L2)
        return max(self.risk_level, asked)

    def public_dict(self) -> dict[str, Any]:
        # Bound handlers can own locks, browser processes, or credential
        # vaults. Build the public shape explicitly instead of deep-copying.
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.label(),
            "enabled": self.enabled,
            "parameters": self.parameters or {"type": "object", "properties": {}},
        }


#: 꺼진 도구가 하려던 일을 **대신 하는 도구.** 없으면 적지 않는다(지어내지 않는다).
_DISABLED_ALTERNATIVE = {
    "sandbox_run": " 표·문서 파일(xlsx·docx·md)을 만들려던 것이면 코드가 필요 없다 — local_write_document 가 직접 만든다.",
}

class ToolGateway:
    """Single enforcement point for all tool calls.

    L0/L1 execute directly. L2+ always require an approval nonce confirmed
    through the authenticated API; spoken confirmation is deliberately ignored.
    """

    def __init__(
        self,
        store: JobStore,
        events: EventBus,
        # ★ 여기 300(5분)이 박혀 있었고 `runtime.py` 가 인자 없이 만들어서 **조절할
        # 방법이 없었다**(2026-08-14). 승인이 잡(체크포인트 1800초)보다 25분 먼저
        # 죽어서, 되살릴 수 있는 잡을 승인이 없어서 못 되살렸다. 근거는
        # `config.approval_ttl_sec` 주석에. 부르는 쪽은 반드시 config 값을 넘긴다.
        approval_ttl_sec: int = 1800,
        # 되돌리기를 언제까지 내줄 것인가. 승인보다 훨씬 길어야 한다 —
        # 승인은 "지금 할까요"라 짧아도 되지만, 되돌리기는 결과를 보고 나서
        # 마음이 바뀌는 일이라 한참 뒤에 찾는다.
        undo_ttl_sec: int = 6 * 3600,
        notifications: Any = None,
        approval_reminder_lead_sec: int = 300,
        # ★ 승인 방식 (2026-09-16). 기본은 **수동** — 지금까지와 같다.
        #
        #   켜면 「되돌릴 수 있는 것만」 자동으로 지나간다: 등록 등급이 L1 이하인데 **대상 때문에** L2 로 올라간
        #   동작(사용자 폴더에 파일 쓰기 같은 것)이고, 그 도구에 **역동작이 실제로 달려 있을 때**뿐이다.
        #   메일 발송·발행·결제·삭제처럼 등록 자체가 L2 인 것은 이 스위치로도 안 열린다 — 코드가 막는다.
        #   왜 필요한가: 바깥 Claude 가 시킨 일의 승인 카드는 온텔릭 창에만 뜬다. 사람이 Claude 창을 보고 있으면
        #   아무도 못 보고 30분 뒤 만료돼 **일이 조용히 죽는다**(2026-09-16 실측에서 그렇게 멈췄다).
        auto_approve_reversible: bool = False,
        write_enabled: bool = True,
        # 「셸 명령 자동 실행」— **사용자가 명시적으로 켰을 때만** 셸 명령이 승인 단계를 자동으로 지나간다.
        # 등록 바닥(L2)은 그대로 둔다: 동적 등급은 올리기만 하므로 `_shell_risk` 가 돌려주는 L1 은 게이트에서 늘
        # 무시됐고, 그래서 이 설정과 권한 모드 `workspace` 의 셸 항목은 켜도 효과가 없었다(2026-09-21).
        auto_approve_shell: bool = False,
        # 권한 모드 「권한 무시」(2026-09-23). 켜면 `NEVER_BYPASS`(결제·메일 보내기·발행)만 사람이 본다.
        auto_approve_all: bool = False,
    ) -> None:
        self.store = store
        self.events = events
        #: 아는 비밀 값의 모음(`known_secrets.KnownSecrets`) — 런타임이 건다. 걸려 있으면 **모든 도구 결과**에서 그 값을 가린다.
        #: 문이 여기 하나라 도구마다 붙이지 않는다(붙이면 언젠가 하나를 잊는다). 없으면 아무 일도 없다.
        self.known_secrets: Any = None
        #: 승인 카드에 **보여 줄 말**을 만드는 함수(도구 이름 → 인자 → 덧붙일 칸). 인자는 건드리지 않는다 —
        #: 승인 뒤 그 인자 그대로 재실행되기 때문이다(2026-09-24, 「바탕화면/회의 메모.txt」 카드).
        self.approval_describers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        #: 도구가 「이건 승인이 있어야 한다」는 오류로 멈추면 **같은 인자로 승인 도구를 대신 부른다**
        #: (도구 이름 → (오류 표식, 승인 도구)). 2026-09-30 코드 벤치: 자기 앱의 「추가」가
        #: `browser_click` 에서 막히고 「browser_click_confirmed 로 요청하라」는 **글**만 돌아왔다 —
        #: 모델이 그 도구를 다시 불러야만 카드가 떴고, 코드 모드엔 그 도구가 없어 카드가 영영 안 떴다.
        #: 이제 카드는 도구가 띄우고, 재개 때 막혔던 그 호출이 재생되면 같은 길로 승인을 소비해 눌린다.
        self.approval_escalations: dict[str, tuple[str, str]] = {}
        #: 카드를 만들기 **전에** 인자를 거르는 함수(도구 이름 → 검사, 못 쓰면 예외). 선택지 없는 질문처럼
        #: 사람이 답할 수 없는 카드로 판을 30분 멈추지 않게 한다 — 대신 모델에게 고칠 말을 돌려준다.
        self.pre_approval_checks: dict[str, Callable[[dict[str, Any]], None]] = {}
        self.approval_ttl_sec = approval_ttl_sec
        self.undo_ttl_sec = undo_ttl_sec
        self.notifications = notifications
        self.approval_reminder_lead_sec = max(1, approval_reminder_lead_sec)
        self.auto_approve_reversible = bool(auto_approve_reversible)
        self.auto_approve_shell = bool(auto_approve_shell)
        self.auto_approve_all = bool(auto_approve_all)
        # 읽기만 모드(권한 모드 `read_only`). 끄면 **바꾸는 도구를 아예 안 돌린다** —
        # 승인으로 넘기지 않는다. 승인은 「해도 되나」고, 이건 「이번 판은 안 바꾼다」다.
        self.write_enabled = bool(write_enabled)
        self._tools: dict[str, ToolSpec] = {}

    def refusal_for_read_only(self, spec: "ToolSpec") -> dict[str, Any] | None:
        """읽기만 모드에서 막아야 하면 그 이유. 막을 것 없으면 None.

        ★ 막기만 하면 모델은 같은 벽에 계속 부딪친다 — **무엇을 대신 하면 되는지**
          같이 준다. 여기서는 「계획을 글로 답해라」가 그 다음 수다.
        """
        if self.write_enabled or spec.name not in WRITE_TOOL_NAMES:
            return None
        return {
            "ok": False,
            "tool": spec.name,
            "error": "read_only_mode",
            "instruction": (
                f"지금은 **읽기만** 모드라 `{spec.name}` 으로 바꿀 수 없다. "
                "읽고 살펴본 다음, 무엇을 어떻게 바꾸면 되는지 **계획을 글로** 답해라. "
                "사람이 모드를 바꾸면 그대로 실행하면 된다."
            ),
        }

    def _auto_approvable(self, spec: "ToolSpec", risk: RiskLevel) -> bool:
        """이 동작을 사람 없이 지나가게 해도 되는가.

        셋을 **동시에** 만족할 때만: ① 설정이 자동 ② 등록 등급이 L2 미만인데 **대상 때문에** 올라갔다
        ③ 되돌리는 방법(`inverse`)이 실제로 달려 있다. 하나라도 빠지면 사람이 본다.
        """
        # 질문은 승인이 아니라 **사람의 답**이다 — 어느 모드에서도 대신 고르지 않는다.
        if spec.name == ASK_USER_TOOL:
            return False
        # 「권한 무시」— 돈이 오가거나 남에게 나가는 것만 사람이 본다(사장님이 고른 범위).
        #   `ALWAYS_ASK` 보다 **먼저** 본다: 이 모드는 지우기·폴더 권한·PC 설정까지 여는 자리다.
        if self.auto_approve_all:
            return spec.name not in NEVER_BYPASS
        # ★ 그 밖의 모드에서는 사람이 본다 — 설정이 아니라 규칙이다.
        #   밖으로 나가거나, 남의 것을 지우거나, 돈이 오가거나, 이 PC 를 바꾸는 것.
        if spec.name in ALWAYS_ASK:
            return False
        # 켠 사람에게만. 셸 안의 보안 거부(보안 설정·시스템 폴더)는 실행부에서 **여전히** 막는다.
        if spec.name == "local_run_shell" and self.auto_approve_shell:
            return True
        return (
            self.auto_approve_reversible
            and spec.risk_level < RiskLevel.L2
            and risk >= RiskLevel.L2
            and spec.inverse is not None
        )

    def _notify_approval(self, approval: dict[str, Any], description: str) -> None:
        """승인 요청을 즉시 밀고, 살아 있으면 만료 전에 한 번 더 민다."""
        notifier = self.notifications
        if notifier is None:
            return
        tool = str(approval.get("tool_name") or "작업")
        try:
            notifier.notify(
                "Sonjari · 승인이 필요합니다",
                f"{description or tool} 작업이 화면 승인을 기다리고 있습니다.",
            )
        except Exception:
            pass

        ttl = max(0.1, float(approval.get("expires_at") or 0) - time.time())
        lead = min(float(self.approval_reminder_lead_sec), max(0.05, ttl / 2))
        delay = max(0.05, ttl - lead)
        nonce = str(approval.get("nonce") or "")

        def remind() -> None:
            try:
                current = self.store.get_approval(nonce)
                if not current or current.get("status") != ApprovalStatus.PENDING.value:
                    return
                remaining = float(current.get("expires_at") or 0) - time.time()
                if remaining <= 0:
                    return
                notifier.notify(
                    "Sonjari · 승인이 곧 만료됩니다",
                    f"{description or tool} 작업 승인이 아직 필요합니다.",
                )
                self.store.add_audit(
                    "approval_reminded",
                    nonce,
                    {"tool": tool, "remaining_sec": round(remaining, 1)},
                )
                self.events.publish(
                    "approval_reminder",
                    {"nonce": nonce, "tool_name": tool, "expires_at": current.get("expires_at")},
                )
            except Exception:
                # 알림 실패가 승인 자체를 실패시키면 사람이 승인할 길까지 사라진다.
                return

        timer = threading.Timer(delay, remind)
        timer.daemon = True
        timer.start()

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def list_tools(self) -> list[dict[str, Any]]:
        return [self._tools[name].public_dict() for name in sorted(self._tools)]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        job_id: str = "",
    ) -> ToolResult:
        arguments = arguments or {}
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(False, name, status="not_found", error="unknown_tool")
        arguments = coerce_boolean_arguments(spec.parameters, arguments)
        if not spec.enabled:
            # ★ 「tool_disabled」 한 낱말만 주면 모델은 왜 안 되는지도, 대신 무엇을 할지도 모른다 (2026-10-05 영어 촬영 판 9cae577f:
            #   엑셀을 만들려고 상자에서 pandas 를 돌리려다 이 한 낱말을 받고 파일 만들기를 통째로 접었다). 꺼져 있다는 사실과,
            #   그 일을 대신 하는 도구가 있으면 그것을 말해 준다.
            hint = _DISABLED_ALTERNATIVE.get(name, "")
            return ToolResult(False, name, status="disabled",
                              error=f"tool_disabled — {name} 은(는) 이 PC 에서 꺼져 있다. 다시 부르지 말고 다른 도구로 하라.{hint}")
        # 읽기만 모드는 **승인으로 넘기지 않는다.** 이번 판은 안 바꾸기로 한 것이므로
        # 물어볼 것이 없다 — 대신 무엇을 하면 되는지 말해 준다.
        if (blocked := self.refusal_for_read_only(spec)) is not None:
            return ToolResult(
                False, name, status="read_only",
                error=blocked["error"], result={"instruction": blocked["instruction"]},
            )

        execution_arguments = dict(arguments)
        if spec.needs_job_context:
            execution_arguments["__job_id"] = job_id

        risk = spec.effective_risk(execution_arguments)
        proof_before: dict[str, Any] = {}
        approval_consumed = False
        if risk >= RiskLevel.L2:
            approved = self.store.find_approved(
                job_id=job_id, tool_name=name, arguments=arguments
            )
            if approved and self.store.consume_approval(str(approved["nonce"])):
                approval_consumed = True
                self.store.add_audit("approval_consumed", str(approved["nonce"]), {"tool": name})
                proof_before = dict(approved.get("proof") or {})
                # 질문 카드의 답은 승인 기록에 실려 온다 — 도구가 그것을 모델에게 돌려준다.
                if approved.get("answer") is not None:
                    execution_arguments["__answer"] = str(approved["answer"])
                if spec.proof is not None:
                    try:
                        current = spec.proof.recapture(execution_arguments)
                    except Exception as exc:
                        payload = {"tool": name, "error": str(exc)[:500]}
                        self.store.add_audit(
                            "proof_recheck_failed", str(approved["nonce"]), payload
                        )
                        self.events.publish("proof_target_drifted", payload)
                        return ToolResult(
                            False,
                            name,
                            status="proof_target_drifted",
                            error="proof_recheck_failed",
                            risk_level=risk.label(),
                        )
                    if not spec.proof.same_target(proof_before, current):
                        payload = {
                            "tool": name,
                            "before": proof_before,
                            "current": current,
                        }
                        self.store.add_audit(
                            "proof_target_drifted", str(approved["nonce"]), payload
                        )
                        self.events.publish("proof_target_drifted", payload)
                        return ToolResult(
                            False,
                            name,
                            status="proof_target_drifted",
                            error="approved_target_changed",
                            risk_level=risk.label(),
                        )
            else:
                if (check := self.pre_approval_checks.get(name)) is not None:
                    try:
                        check(arguments)
                    except Exception as exc:  # noqa: BLE001 — 무엇이 모자란지 모델에게 그대로 돌려준다
                        return ToolResult(
                            False, name, status="failed", error=str(exc), risk_level=risk.label(),
                        )
                if spec.proof is not None:
                    try:
                        proof_before = dict(spec.proof.capture_before(execution_arguments) or {})
                    except Exception as exc:
                        self.store.add_audit(
                            "proof_capture_failed",
                            job_id,
                            {"tool": name, "error": str(exc)[:500]},
                        )
                        return ToolResult(
                            False,
                            name,
                            status="proof_capture_failed",
                            error=str(exc),
                            risk_level=risk.label(),
                        )
                if self._auto_approvable(spec, risk):
                    # 자동으로 지나가되 **조용히는 안 한다** — 기록에 남기고, 화면·알림에 「자동 승인함」을 띄운다.
                    payload = {"tool": name, "job_id": job_id, "risk_level": risk.label(),
                               "registered_risk": spec.risk_level.label(),
                               "reason": ("permission_bypass" if self.auto_approve_all
                                          else "shell_autorun_opt_in" if name == "local_run_shell"
                                          else "reversible_target_escalation")}
                    self.store.add_audit("approval_auto_approved", job_id or name, payload)
                    self.events.publish("approval_auto_approved", payload)
                    if self.notifications is not None:
                        try:
                            self.notifications.notify(
                                "Sonjari · 자동 승인",
                                (
                                    f"{spec.description or name} 을(를) 묻지 않고 진행했습니다(권한 무시 모드)."
                                    if self.auto_approve_all
                                    else "셸 명령을 자동으로 실행했습니다(설정에서 「셸 명령 자동 실행」을 켠 상태). "
                                    "되돌리기는 없습니다."
                                    if name == "local_run_shell"
                                    else f"{spec.description or name} 을(를) 자동으로 진행했습니다. 되돌릴 수 있습니다."
                                ),
                            )
                        except Exception:  # noqa: BLE001
                            pass
                else:
                    nonce = secrets.token_urlsafe(24)
                    approval = self.store.create_approval(
                    nonce=nonce,
                    job_id=job_id,
                    tool_name=name,
                    arguments=arguments,
                    proof=proof_before,
                        expires_at=time.time() + self.approval_ttl_sec,
                    )
                    approval = self.describe_approval(approval)
                    self.store.add_audit("approval_requested", nonce, approval)
                    self.events.publish("approval_requested", approval)
                    self._notify_approval(approval, spec.description)
                    if job_id:
                        raise ApprovalRequired(nonce)
                    return ToolResult(
                        False,
                        name,
                        status="approval_required",
                        approval_nonce=nonce,
                        risk_level=risk.label(),
                    )

        # 도구가 실제로 돈 시간. **이 길목 하나에서만** 잰다 — 부르는 자리가 넷이라
        # 하나씩 붙이면 언젠가 잊고, 그러면 그 도구만 조용히 0 이 된다.
        handler_started = time.monotonic()
        try:
            result = spec.handler(execution_arguments)
            took_ms = int((time.monotonic() - handler_started) * 1000)
            result_status = ""
            if spec.proof is not None:
                result = spec.proof.finalize(proof_before, result)
                proof = dict(result.get("proof") or {})
                after = dict(proof.get("after") or {})
                try:
                    after.update(spec.proof.after(execution_arguments, result))
                except Exception as exc:
                    # 클릭은 이미 실행됐다. 사후 촬영 실패를 실행 실패로 바꾸거나
                    # 재시도를 유도하지 않고 증거 봉투 안에 그대로 남긴다.
                    after["capture_error"] = str(exc)[:500]
                proof["after"] = after
                proof["approval"] = {
                    "bound_fingerprint": str(proof_before.get("fingerprint") or ""),
                    "consumed": approval_consumed,
                }
                result["proof"] = proof
                if result.get("verified") is not True:
                    result_status = "executed_unverified"
                    self.events.publish(
                        "tool_executed_unverified",
                        {"tool": name, "job_id": job_id, "proof": proof},
                    )
            self.store.add_audit(
                "tool_executed",
                job_id,
                {
                    "tool": name,
                    "ok": True,
                    "status": result_status,
                    "shape": audit_shape(name, execution_arguments, result),
                    "proof": result.get("proof") if isinstance(result, dict) else None,
                },
            )
            self._offer_undo(spec, job_id, result)
            # 되돌리기 손잡이까지 남긴 **뒤에** 가린다 — 손잡이는 원래 값으로 일해야 한다. 모델·걸음 장부로 가는 것은 가린 쪽이다.
            result = self._hide_known_secrets(execution_arguments, result)
            return ToolResult(
                True,
                name,
                result=result,
                status=result_status,
                risk_level=risk.label(),
                took_ms=took_ms,
            )
        except Exception as exc:
            escalation = self.approval_escalations.get(name)
            if (
                escalation is not None
                and escalation[0] in str(exc)
                and escalation[1] != name
                and escalation[1] in self._tools
            ):
                # 막힌 것은 아직 아무것도 안 눌렀다(판정은 누르기 전). 인자를 그대로 넘겨야
                # 재개 때 `find_approved` 가 같은 것으로 알아본다.
                self.store.add_audit(
                    "approval_escalated",
                    job_id or name,
                    {"tool": name, "to": escalation[1], "reason": str(exc)[:300]},
                )
                return self.execute(escalation[1], arguments, job_id=job_id)
            self.store.add_audit(
                "tool_executed",
                job_id,
                {
                    "tool": name,
                    "ok": False,
                    "error": str(exc)[:500],
                    "shape": audit_shape(name, execution_arguments, None),
                },
            )
            return ToolResult(
                False,
                name,
                status="failed",
                error=str(self._hide_known_secrets(execution_arguments, str(exc))),
                risk_level=risk.label(),
                # 실패에도 시간을 싣는다. **느린 실패**가 편차의 큰 몫이라
                # 여기가 0 이면 그 몫이 통째로 안 보인다.
                took_ms=int((time.monotonic() - handler_started) * 1000),
            )

    def _hide_known_secrets(self, arguments: dict[str, Any], result: Any) -> Any:
        """도구 결과에서 **아는** 비밀 값을 가린다(`known_secrets`). 가릴 것이 없으면 받은 것을 그대로 돌려준다.

        도구가 건드린 경로 가까이의 `.env` 류 파일은 여기서 먼저 배운다 — 그래서 그 파일을 어느 도구로 읽든(파일 읽기 · 찾기 ·
        명령) 값은 가려지고 이름만 남는다. 가리다 틀어지면 결과를 그대로 낸다: 가리기가 도구를 실패로 만들면 안 된다.
        """
        known = self.known_secrets
        if known is None:
            return result
        try:
            for source in (arguments, result):
                path = source.get("path") if isinstance(source, dict) else None
                if isinstance(path, str) and path:
                    known.learn_near(path)
            hidden, count = known.hide_in(result)
            return hidden if count else result
        except Exception:  # noqa: BLE001
            return result

    def _offer_undo(self, spec: ToolSpec, job_id: str, result: Any) -> None:
        """방금 한 일을 되돌릴 수 있으면 그 손잡이를 남긴다.

        여기서 실패해도 도구 실행은 성공이다. 되돌리기를 못 적었다고 이미 한 일을
        실패로 만들면 더 나쁜 거짓말이 된다 — 그래서 통째로 삼킨다.
        """
        if spec.inverse is None or not isinstance(result, dict):
            return
        if result.get("duplicate_commit"):
            # 이번 호출은 아무것도 안 했다 — 앞선 커밋의 결과를 그대로 되돌려
            # 받았을 뿐이다. 그 결과의 손잡이로 되돌리기를 또 달면, 같은 일정
            # 하나에 버튼이 둘이 된다. 하나를 누르면 나머지 하나는 눌러도
            # 아무 일도 안 일어나는 버튼이 된다 — 그게 제일 나쁘다.
            # 진짜로 한 쪽(첫 커밋)의 되돌리기는 그대로 살아 있다.
            return
        try:
            handle = spec.inverse.handle_from(result)
        except Exception:
            handle = None
        if handle is None:
            # 이번 건은 무엇을 되돌려야 할지 모른다(저장이 확인 안 됐다든지).
            return
        try:
            offer = self.store.add_undo_offer(
                tool=spec.name,
                job_id=job_id,
                label=spec.inverse.label,
                handle=handle,
                manual_hint=spec.inverse.manual_hint,
                automatic=spec.inverse.undo is not None,
                expires_at=time.time() + self.undo_ttl_sec,
            )
        except Exception:
            return
        self.events.publish("undo_available", offer)

    def undo(self, undo_id: str) -> dict[str, Any]:
        """되돌린다. 사람이 시작하는 동작이라 승인을 다시 묻지 않는다.

        되돌리기에 또 승인을 걸면 되돌리기가 무거워지고, 무거운 되돌리기는 안 쓰인다.
        그리고 이건 **원래 상태로 가는 방향**이라 승인으로 지켜야 할 것이 없다.
        """
        offer = self.store.claim_undo_offer(undo_id)
        if offer is None:
            return {"ok": False, "error": "undo_not_found_or_expired"}
        spec = self._tools.get(str(offer["tool"]))
        inverse = spec.inverse if spec else None
        if inverse is None or inverse.undo is None:
            # 자동으로는 못 되돌린다. 사람이 할 수 있게 그대로 돌려준다.
            self.store.finish_undo_offer(undo_id, "manual")
            return {"ok": False, "error": "undo_is_manual", "hint": offer.get("manual_hint") or "", **offer}
        try:
            result = inverse.undo(dict(offer["handle"]))
        except UndoUnverified as exc:
            # 역동작은 이미 **한 번 실행됐다.** live 로 돌려놓으면 다음 호출이 같은
            # 토글을 또 눌러 원래 상태를 다시 만든다. 성공 실적도 실패도 아닌 별도
            # 상태로 닫고, 호출자에게는 실행됨(ok)과 미확인(verified)을 함께 말한다.
            self.store.finish_undo_offer(undo_id, "attempted_unverified")
            audit = {"tool": offer["tool"], "reason": str(exc)[:500], "result": exc.result}
            self.store.add_audit("undo_unverified", undo_id, audit)
            self.events.publish("undo_unverified", {"undo_id": undo_id, **audit})
            return {
                "ok": True,
                "verified": False,
                "status": "attempted_unverified",
                "tool": offer["tool"],
                "label": offer["label"],
                "result": exc.result,
                "instruction": (
                    "되돌리기 동작은 한 번 실행했지만 결과를 확인하지 못했다. "
                    "성공이나 실패로 단정하지 말고, 같은 undo_action을 다시 호출하지 마라."
                ),
            }
        except Exception as exc:
            self.store.finish_undo_offer(undo_id, "failed")
            self.store.add_audit("undo_failed", undo_id, {"tool": offer["tool"], "error": str(exc)[:500]})
            return {"ok": False, "error": str(exc)[:500]}
        self.store.finish_undo_offer(undo_id, "undone")
        self.store.add_audit("undo_done", undo_id, {"tool": offer["tool"]})
        self.events.publish("undo_done", {"undo_id": undo_id, "tool": offer["tool"]})
        return {
            "ok": True,
            "verified": True,
            "status": "undone",
            "tool": offer["tool"],
            "label": offer["label"],
            "result": result,
        }

    def describe_approval(self, approval: dict[str, Any]) -> dict[str, Any]:
        """승인 한 건에 사람이 읽을 칸(`target`)을 붙인다. 설명을 못 만들면 그대로 둔다 — 카드는 인자를 보여 준다."""
        describe = self.approval_describers.get(str(approval.get("tool_name") or ""))
        if describe is None:
            return approval
        try:
            extra = describe(dict(approval.get("arguments") or {}))
        except Exception:  # noqa: BLE001 — 설명은 덤이다. 승인을 막으면 안 된다
            return approval
        return {**approval, "target": extra} if extra else approval

    def decide(self, nonce: str, approve: bool, answer: str | None = None) -> dict[str, Any] | None:
        decision = self.store.decide_approval(nonce, approve, answer)
        if decision:
            event = "approval_approved" if approve else "approval_denied"
            self.store.add_audit(event, nonce, decision)
            self.events.publish(event, decision)
        return decision
