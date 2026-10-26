"""로컬이 막혔을 때만 **사용자 자기 API 키**로 클로드에게 한 번 묻는다 (2026-10-26 · `docs/설계_혼합_로컬API승급_2026-10-26.ko.md`).

`claude_code.py`(넘기기)와 다른 길이다 — 섞지 않는다.

| | 넘기기(`claude_code.py`) | 이 길 |
|---|---|---|
| 무엇으로 | 이 PC 의 Claude Code 프로그램 · 구독 로그인 | 손자리에 넣은 API 키 · Messages API |
| 무엇을 | 코드 일을 통째로 넘김 | 막힌 자리 요약을 보내 「다음에 할 것」 조언 한 번 |
| 환경변수 키 | 일부러 지움(구독으로만) | **읽지 않음**(손자리에 직접 넣은 키만) |

## 지키는 것

- **실패 신호에서만 부른다** — 요청 글로 어렵다고 미리 짐작하지 않는다(전략안 §19, G1~G4 예측 라우팅 금지).
  첫 판의 신호는 하나: 되받기가 진전 없이 막힘(`agent_plan_pushback_stalled`).
- **기본 꺼짐.** 측정 판 · 클로드가 맡긴 판은 켜 둬도 부르지 않는다(`hold_reason`).
- **돈 상한 셋**: 판마다 1번 · 한 번에 입력 20,000자 / 출력 2,000 토큰 · 달마다 상한(설정).
- **영수증 셋**: 진행 이벤트 · 답 끝 한 줄 · 장부(`data/api_escalation.jsonl`). 부르지 **않은** 까닭도 장부에 남긴다.
- 키는 DPAPI(현재 사용자에 묶인 암호화)로만 둔다. 값은 어디에도 찍지 않는다 — 보일 때는 끝 4자리.
- 조언은 사람 말처럼 끼울 뿐이다. 대조표 · 근거 검사 · 승인 카드는 그대로 돌고, 클로드 말을 근거로 세지 않는다.
"""

from __future__ import annotations

import importlib.util
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# ── 모델 · 가격 (앤트로픽 1차 API · `claude-api` 스킬 표 2026-10-06 · 100만 토큰당 달러) ────────────────
#   ★ 확인 전 표다. 실제 청구는 앤트로픽 콘솔이 정한다 — 장부에 토큰 수를 같이 남겨 나중에 다시 셀 수 있게 한다.
#   기본은 Opus 5.5. 싼 모델로 내리는 것은 사용자가 고른다(설정) — 우리가 돈 때문에 몰래 내리지 않는다.
MODELS: dict[str, dict[str, Any]] = {
    "claude-opus-5-5": {"name": "Claude Opus 5.5", "input": 4.00, "output": 20.00, "cache_read": 0.20, "fallbacks": True},
    "claude-sonnet-5-5": {"name": "Claude Sonnet 5.5", "input": 2.00, "output": 10.00, "cache_read": 0.20, "fallbacks": True},
    # Haiku 5.5 는 서버 쪽 거절 대비가 없다 — `fallbacks` 를 보내면 400(목록) · 그대로 거절(default). 보내지 않는다.
    "claude-haiku-5-5": {"name": "Claude Haiku 5.5", "input": 0.10, "output": 0.50, "cache_read": 0.01, "fallbacks": False},
}
DEFAULT_MODEL = "claude-opus-5-5"
#: 거절 대비 기본값(서버가 거절 갈래별로 다른 모델로 다시 돌린다) — `"default"` 꼴의 머리표.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

MAX_SEND_CHARS = 20_000
MAX_OUTPUT_TOKENS = 2_000
PER_JOB_CALLS = 1
DEFAULT_MONTHLY_USD = 3.0
#: 글자 → 토큰 어림(한국어 · 영어 섞임). 달 상한을 **넘기 전에** 막으려고 일부러 크게 잡는다.
_CHARS_PER_TOKEN_WORST = 2.5

LEDGER_NAME = "api_escalation.jsonl"
SENT_DIR = "api_escalation"
KEY_FILE = Path("secrets") / "anthropic_api_key.bin"

#: 답 · 진행 줄의 고정 말머리. 이미 답에 있으면 한 번 더 붙이지 않는다.
RECEIPT_MARK = "내 API 키로 클로드"

#: 부르지 않은 까닭 — 사람에게 보이는 말.
SKIP_TEXT: dict[str, str] = {
    "switched_off": "설정에서 꺼져 있어서",
    "no_key": "API 키가 없어서",
    "no_sdk": "이 판에 클로드 연결 부품이 없어서",
    "measurement_flag": "측정 판이라서",
    "measurement_caller": "측정 판이라서",
    "measurement_session": "측정 판이라서",
    "delegated_by_claude_code": "클로드가 맡긴 일이라 막힌 자리를 그 클로드에게 돌려줘서",
    "delegated_by_outside_ai": "바깥 AI 가 맡긴 일이라 로컬 모델로만 하고 막힌 자리는 맡긴 쪽에 돌려줘서",
    "per_job_limit": "이 판에서 이미 한 번 물어서",
    "monthly_cap": "이번 달 상한에 닿아서",
}


# ── 키 보관 ────────────────────────────────────────────────────────────────

def _key_path(config: Any) -> Path:
    return Path(config.data_dir) / KEY_FILE


def _vault(config: Any) -> Any:
    from .google_workspace import TokenVault  # DPAPI 감싸기 — 같은 것을 두 번 만들지 않는다

    return TokenVault(_key_path(config))


def mask(key: str) -> str:
    key = str(key or "").strip()
    return f"…{key[-4:]}" if len(key) >= 8 else "…"


def has_key(config: Any) -> bool:
    return _key_path(config).is_file()


def save_key(config: Any, key: str) -> str:
    """키를 DPAPI 로 감싸 둔다. 돌려주는 것은 끝 4자리뿐이다."""
    key = str(key or "").strip()
    if not key or len(key) < 20 or any(ch.isspace() for ch in key):
        raise ValueError("api_key_shape")
    _vault(config).save({"api_key": key, "saved_at": int(time.time())})
    return mask(key)


def clear_key(config: Any) -> bool:
    path = _key_path(config)
    if not path.is_file():
        return False
    path.unlink()
    return True


def load_key(config: Any) -> str:
    if not has_key(config):
        return ""
    try:
        return str(_vault(config).load().get("api_key") or "").strip()
    except (OSError, ValueError):
        return ""


#: 클로드 구독 로그인 토큰(`claude setup-token` 이 주는 것)의 머리 — **앤트로픽 문서에 접두어가 적혀 있지는 않다**(10-26 확인:
#: code.claude.com/docs/en/authentication 은 「구독으로 인증하는 1년짜리 OAuth 토큰」이라고만 함). 실물에서 본 머리라 막는 목록에 둔다.
#: 제3자 제품이 claude.ai 로그인을 쓰는 것은 앤트로픽 사전 승인이 필요하다(Agent SDK 문서) — 손자리는 API 키만 받는다.
SUBSCRIPTION_TOKEN_PREFIX = "sk-ant-oat"
ADMIN_KEY_PREFIX = "sk-ant-admin"


def key_shape(key: str) -> str:
    """`api_key` · `subscription_token` · `admin_key` · `not_a_key`. 값은 되풀이하지 않는다."""
    key = str(key or "").strip()
    if not key.startswith("sk-ant-") or any(ch.isspace() for ch in key):
        return "not_a_key"
    if key.startswith(SUBSCRIPTION_TOKEN_PREFIX):
        return "subscription_token"
    if key.startswith(ADMIN_KEY_PREFIX):
        return "admin_key"
    return "api_key"


def key_from_clipboard(config: Any, clipboard: Any = None) -> dict[str, Any]:
    """키는 HTTP 몸통으로 받지 않는다 — 본체가 클립보드를 직접 읽어 DPAPI 에만 둔다(디스코드 봇 토큰과 같은 길).

    모양이 틀린 글은 **무엇이 들어 있었는지 되풀이하지 않는다** — 실수로 복사한 비밀번호일 수 있다.
    """
    if clipboard is None:
        from .messaging.service import system_clipboard

        clipboard = system_clipboard()
    try:
        key = str(clipboard.read() or "").strip()
    except Exception:  # noqa: BLE001 — 다른 프로그램이 클립보드를 쥐고 있다
        return {"ok": False, "error": "clipboard_unavailable"}
    if not key:
        return {"ok": False, "error": "clipboard_empty"}
    shape = key_shape(key)
    if shape != "api_key":
        return {"ok": False, "error": "subscription_token" if shape == "subscription_token" else "not_an_api_key"}
    try:
        masked = save_key(config, key)
    except (OSError, ValueError):
        return {"ok": False, "error": "store_failed"}
    cleared = False
    try:
        if str(clipboard.read() or "").strip() == key:
            clipboard.clear()
            cleared = True
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "masked": masked, "cleared": cleared}


def key_status(config: Any) -> dict[str, Any]:
    """화면 · 바깥이 보는 상태. 키 값은 끝 4자리도 내지 않는다 — 있다/없다만."""
    reason, short = unavailable(config)
    return {
        "has_key": has_key(config),
        "sdk": sdk_present(),
        "unavailable": reason,
        "unavailable_short": short,
        "enabled": bool(getattr(config, "api_escalation_enabled", False)),
        "model": str(getattr(config, "api_escalation_model", DEFAULT_MODEL) or DEFAULT_MODEL),
        "monthly_cap_usd": float(getattr(config, "api_escalation_monthly_usd", DEFAULT_MONTHLY_USD) or 0),
        "month_usd": month_spent(Path(config.data_dir), time.time()),
    }


def sdk_present() -> bool:
    try:
        return importlib.util.find_spec("anthropic") is not None
    except (ImportError, ValueError):
        return False


def unavailable(config: Any) -> tuple[str, str]:
    """(까닭, 짧은 말). 빈 까닭이면 켤 수 있다. 화면의 「못 씁니다」 자리에 들어간다."""
    if not sdk_present():
        return "no_sdk", "이 판에는 클로드 연결 부품이 없습니다"
    if not has_key(config):
        return "no_key", "API 키를 먼저 넣어 주세요"
    return "", ""


def hold_reason(payload: Any, session_id: str = "") -> str:
    """이 판에서 부르지 않을 까닭. 측정 판 · 클로드가 맡긴 판은 넘기기와 같은 규칙(`claude_code.hold_reason`).

    재는 스크립트만 ``"api_escalation_measure": true`` 로 측정 판 막기를 푼다(설계 문서 5절) — 장부에 그 표시가 남는다.
    """
    from .claude_code import hold_reason as handoff_hold

    reason = handoff_hold(payload, session_id)
    if reason.startswith("measurement") and isinstance(payload, dict) and payload.get("api_escalation_measure") is True:
        return ""
    return reason


# ── 보낼 글 ────────────────────────────────────────────────────────────────

_KEYLIKE = re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{12,}|[A-Za-z0-9_\-]{32,})\b")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?82[-\s]?)?0?1[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
_WIN_PATH = re.compile(r"[A-Za-z]:\\[^\s\"'<>|]*")
_USER_HOME = re.compile(r"(?i)(/home/|/Users/)[^/\s]+")


def redact(text: str) -> str:
    """보내기 전에 가린다 — 키 · 토큰 모양 글자, 메일, 전화번호, 이 PC 의 경로(사용자 이름이 든다)."""
    text = str(text or "")
    text = _KEYLIKE.sub("[가림:키]", text)
    text = _EMAIL.sub("[가림:메일]", text)
    text = _PHONE.sub("[가림:전화]", text)
    text = _WIN_PATH.sub(lambda m: "[경로]\\" + m.group(0).replace("/", "\\").rstrip("\\").split("\\")[-1], text)
    text = _USER_HOME.sub(r"\1[사용자]", text)
    return text


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _step_line(index: int, step: dict[str, Any]) -> str:
    tool = str(step.get("tool") or "?")
    arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
    outcome = step.get("observation")
    if outcome in (None, ""):
        outcome = step.get("result")
    if outcome in (None, ""):
        outcome = step.get("evidence")
    status = "실패" if (step.get("ok") is False or step.get("error")) else "됨"
    error = f" 오류={_short(step.get('error'), 120)}" if step.get("error") else ""
    return f"{index}. {tool}({_short(arguments, 160)}) → {status}{error} · {_short(outcome, 200)}"


SYSTEM_PROMPT = (
    "당신은 이 PC 에서 도는 작은 로컬 AI 작업 도우미(손자리)의 조언자다. 손자리는 브라우저 · 파일 · 문서 도구를 직접 부르며 일하는데, "
    "같은 자리에서 더 나아가지 못하고 막혔다. 아래에 사람이 시킨 일, 아직 못 채운 요구, 최근 걸음, 지금까지의 답 초안이 있다. "
    "당신은 도구를 부를 수 없다. 손자리가 **다음에 무엇을 할지**를 짧게 알려 줘라:\n"
    "1) 왜 막혔는지 한 줄 짐작(짐작이라고 밝힌다).\n"
    "2) 다음에 부를 걸음 1~3개 — 무엇을 어디서 찾거나 어떻게 고칠지 구체적으로.\n"
    "3) 이 요구가 처음부터 채울 수 없는 것이면 그렇다고 말하고, 사람에게 무엇을 알려야 하는지.\n"
    "사실을 지어내지 마라. 걸음에 없는 값 · 주소 · 숫자를 확인된 것처럼 쓰지 마라. 한국어로, 600자 안에서."
)


def build_brief(prompt: str, unmet: list[str], steps: list[dict[str, Any]], answer: str) -> str:
    """막힌 자리 요약 — 원문을 통째로 보내지 않는다(설계 2-3). 상한을 넘으면 걸음부터 줄인다."""
    request = redact(_short(prompt, 4_000))
    wants = [redact(_short(item, 160)) for item in unmet[:12]]
    recent = list(enumerate(steps, start=1))[-12:]
    lines = [redact(_step_line(i, step)) for i, step in recent if isinstance(step, dict)]
    draft = redact(_short(answer, 2_000))

    def compose(step_lines: list[str]) -> str:
        return (
            "## 사람이 시킨 일\n" + request
            + "\n\n## 아직 못 채운 요구\n" + ("\n".join(f"- {w}" for w in wants) or "- (대조표 없음)")
            + f"\n\n## 최근 걸음 (전체 {len(steps)}걸음 중 마지막 {len(step_lines)})\n" + ("\n".join(step_lines) or "(없음)")
            + "\n\n## 지금까지의 답 초안\n" + (draft or "(없음)")
        )

    text = compose(lines)
    while len(text) > MAX_SEND_CHARS and lines:
        lines = lines[1:]
        text = compose(lines)
    return text[:MAX_SEND_CHARS]


# ── 돈 ────────────────────────────────────────────────────────────────────

def price_usd(model: str, usage: dict[str, Any]) -> float:
    rates = MODELS.get(model) or MODELS[DEFAULT_MODEL]
    plain = int(usage.get("input_tokens") or 0)
    written = int(usage.get("cache_creation_input_tokens") or 0)
    read = int(usage.get("cache_read_input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cost = (plain + written * 1.25) * rates["input"] + read * rates["cache_read"] + out * rates["output"]
    return round(cost / 1_000_000, 6)


def worst_case_usd(model: str, sent_chars: int) -> float:
    tokens_in = int((sent_chars + len(SYSTEM_PROMPT)) / _CHARS_PER_TOKEN_WORST) + 64
    return price_usd(model, {"input_tokens": tokens_in, "output_tokens": MAX_OUTPUT_TOKENS})


def _month_key(when: float) -> str:
    return datetime.fromtimestamp(when).strftime("%Y-%m")


def month_spent(data_dir: Path, now: float) -> float:
    path = Path(data_dir) / LEDGER_NAME
    if not path.is_file():
        return 0.0
    month = _month_key(now)
    total = 0.0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("month") == month and row.get("called"):
            total += float(row.get("usd") or 0.0)
    return round(total, 6)


# ── 부르기 ────────────────────────────────────────────────────────────────

@dataclass
class Escalation:
    job_id: str
    reason: str
    called: bool
    ok: bool = False
    advice: str = ""
    skip: str = ""
    error: str = ""
    model: str = ""
    served_model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    usd: float = 0.0
    month_usd: float = 0.0
    monthly_cap_usd: float = 0.0
    sent_chars: int = 0
    sent_file: str = ""
    stop_reason: str = ""
    measure: bool = False
    at: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


def _default_client(api_key: str) -> Any:
    import anthropic  # 늦게 — 부품이 없는 판도 손자리는 떠야 한다

    # 키는 직접 넘긴다. 빈 Anthropic() 은 환경변수 · 로그인 프로필을 찾아 **다른 프로그램용 키로 돈이 나갈 수 있다.**
    return anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=90.0)


def _usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    get = usage.get if isinstance(usage, dict) else (lambda name, default=0: getattr(usage, name, default))
    return {
        "input_tokens": int(get("input_tokens", 0) or 0),
        "output_tokens": int(get("output_tokens", 0) or 0),
        "cache_creation_input_tokens": int(get("cache_creation_input_tokens", 0) or 0),
        "cache_read_input_tokens": int(get("cache_read_input_tokens", 0) or 0),
    }


def _text_of(response: Any) -> str:
    blocks = getattr(response, "content", None) or []
    parts = []
    for block in blocks:
        kind = getattr(block, "type", None) if not isinstance(block, dict) else block.get("type")
        if kind == "text":
            parts.append(str(getattr(block, "text", "") if not isinstance(block, dict) else block.get("text", "")))
    return "\n".join(p for p in parts if p).strip()


class ApiEscalation:
    """판마다 막혔을 때 한 번 — 켜짐 판정 · 돈 상한 · 장부 · 영수증을 한 자리에서."""

    def __init__(
        self,
        config: Any,
        events: Any = None,
        *,
        client_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], float] = time.time,
        sdk_check: Callable[[], bool] = sdk_present,
    ) -> None:
        self.config = config
        self.events = events
        self.client_factory = client_factory or _default_client
        self.clock = clock
        self.sdk_check = sdk_check
        self._lock = threading.Lock()
        self._held: dict[str, str] = {}
        self._by_job: dict[str, list[Escalation]] = {}

    # 설정 ------------------------------------------------------------------
    def switched_on(self) -> bool:
        return bool(getattr(self.config, "api_escalation_enabled", False))

    def model(self) -> str:
        chosen = str(getattr(self.config, "api_escalation_model", "") or DEFAULT_MODEL)
        return chosen if chosen in MODELS else DEFAULT_MODEL

    def monthly_cap(self) -> float:
        try:
            return max(0.0, float(getattr(self.config, "api_escalation_monthly_usd", DEFAULT_MONTHLY_USD)))
        except (TypeError, ValueError):
            return DEFAULT_MONTHLY_USD

    def hold_for_job(self, job_id: str, reason: str) -> None:
        if not job_id or not reason:
            return
        with self._lock:
            self._held[str(job_id)] = str(reason)
            while len(self._held) > 500:
                self._held.pop(next(iter(self._held)))

    def entries(self, job_id: str) -> list[Escalation]:
        with self._lock:
            return list(self._by_job.get(str(job_id), []))

    # 판정 ------------------------------------------------------------------
    def skip_reason(self, job_id: str, sent_chars: int) -> str:
        """빈 문자열이면 부른다. 싼 판정부터 — 키 파일을 여는 것은 마지막."""
        if not self.switched_on():
            return "switched_off"
        held = self._held.get(str(job_id), "")
        if held:
            return held
        called = [e for e in self.entries(job_id) if e.called]
        if len(called) >= PER_JOB_CALLS:
            return "per_job_limit"
        if not self.sdk_check():
            return "no_sdk"
        if not has_key(self.config):
            return "no_key"
        spent = month_spent(Path(self.config.data_dir), self.clock())
        if spent + worst_case_usd(self.model(), sent_chars) > self.monthly_cap():
            return "monthly_cap"
        return ""

    # 부르기 ----------------------------------------------------------------
    def ask(self, job_id: str, reason: str, brief: str, *, measure: bool = False) -> Escalation:
        job_id = str(job_id)
        now = self.clock()
        model = self.model()
        entry = Escalation(job_id=job_id, reason=reason, called=False, model=model, sent_chars=len(brief),
                           monthly_cap_usd=self.monthly_cap(), measure=measure, at=now)
        skip = self.skip_reason(job_id, len(brief))
        if skip:
            entry.skip = skip
            entry.month_usd = month_spent(Path(self.config.data_dir), now)
            # 꺼져 있어서 안 부른 것은 장부에 쌓지 않는다 — 기본 꺼짐이라 모든 막힌 판이 한 줄씩 남는다.
            if skip != "switched_off":
                self._record(entry, brief=None)
            return entry
        self._publish("agent_api_escalation", {"job_id": job_id, "reason": reason, "model": model,
                                               "sent_chars": len(brief), "phase": "asking"})
        entry.called = True
        try:
            client = self.client_factory(load_key(self.config))
            request: dict[str, Any] = {
                "model": model,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": brief}],
                # 조언 한 번이라 깊게 생각할 일이 아니다. Opus 5.5 는 생각을 끌 수 없어 깊이로만 줄인다(끄면 400).
                "output_config": {"effort": "low"},
            }
            response = None
            if MODELS[model]["fallbacks"]:
                try:
                    response = client.beta.messages.create(**request, betas=[FALLBACK_BETA], fallbacks="default")
                except TypeError:
                    # 깔린 SDK 판이 `fallbacks` 인자를 모른다 — 요청이 나가기 **전**에 난 오류라 돈은 안 나갔다. 대비 없이 부른다.
                    entry.extra["fallbacks"] = "sdk_unsupported"
            if response is None:
                response = client.messages.create(**request)
            usage = _usage_dict(getattr(response, "usage", None))
            entry.served_model = str(getattr(response, "model", "") or model)
            entry.stop_reason = str(getattr(response, "stop_reason", "") or "")
            entry.input_tokens = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
            entry.output_tokens = usage.get("output_tokens", 0)
            entry.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            # 거절 대비로 다른 모델이 답했으면 그 모델 값으로 센다(표에 없으면 고른 모델 값).
            entry.usd = price_usd(entry.served_model if entry.served_model in MODELS else model, usage)
            if entry.stop_reason == "refusal":
                entry.error = "refusal"
            else:
                entry.advice = _text_of(response)
                entry.ok = bool(entry.advice)
                if not entry.ok:
                    entry.error = "empty"
        except Exception as error:  # noqa: BLE001 — 바깥 API 의 어떤 고장도 로컬 판을 죽이지 않는다
            entry.error = type(error).__name__
            status = getattr(error, "status_code", None)
            if status:
                entry.extra["status"] = int(status)
        entry.month_usd = round(month_spent(Path(self.config.data_dir), now) + entry.usd, 6)
        self._record(entry, brief=brief)
        self._publish("agent_api_escalation", {
            "job_id": job_id, "reason": reason, "model": entry.served_model or model, "phase": "done",
            "ok": entry.ok, "error": entry.error, "usd": entry.usd, "month_usd": entry.month_usd,
            "input_tokens": entry.input_tokens, "output_tokens": entry.output_tokens,
        })
        return entry

    # 기록 ------------------------------------------------------------------
    def _record(self, entry: Escalation, *, brief: str | None) -> None:
        with self._lock:
            self._by_job.setdefault(entry.job_id, []).append(entry)
            while len(self._by_job) > 500:
                self._by_job.pop(next(iter(self._by_job)))
        data_dir = Path(self.config.data_dir)
        try:
            if brief is not None:
                folder = data_dir / SENT_DIR
                folder.mkdir(parents=True, exist_ok=True)
                sent = folder / f"{_safe(entry.job_id)}_{int(entry.at)}.json"
                sent.write_text(json.dumps({"system": SYSTEM_PROMPT, "user": brief, "model": entry.model,
                                            "advice": entry.advice}, ensure_ascii=False, indent=1), encoding="utf-8")
                entry.sent_file = str(sent)
            row = {k: v for k, v in asdict(entry).items() if k != "advice"}
            row["month"] = _month_key(entry.at)
            row["advice_chars"] = len(entry.advice)
            data_dir.mkdir(parents=True, exist_ok=True)
            with (data_dir / LEDGER_NAME).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 장부를 못 써도 판은 간다 — 다만 답 끝 영수증은 그대로 붙는다

    def _publish(self, kind: str, payload: dict[str, Any]) -> None:
        if self.events is not None:
            try:
                self.events.publish(kind, payload)
            except Exception:  # noqa: BLE001
                pass


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", str(text))[:64] or "job"


# ── 영수증 · 끼울 말 ──────────────────────────────────────────────────────

def receipt_line(entries: list[Escalation]) -> str:
    called = [e for e in entries if e.called]
    if not called:
        return ""
    last = called[-1]
    name = MODELS.get(last.served_model or last.model, {}).get("name") or (last.served_model or last.model)
    usd = sum(e.usd for e in called)
    result = "조언을 받아 이어서 했습니다" if last.ok else f"답을 못 받았습니다({last.error or '알 수 없음'})"
    return (
        f"— 막혀서 {RECEIPT_MARK}({name})에게 한 번 물었습니다: {result} · "
        f"입력 {sum(e.input_tokens for e in called):,} · 출력 {sum(e.output_tokens for e in called):,} 토큰 · "
        f"약 ${usd:.3f} (이번 달 ${last.month_usd:.2f} / ${last.monthly_cap_usd:.2f}) · "
        f"보낸 것은 막힌 자리 요약(읽은 글 조각 포함) {sum(e.sent_chars for e in called):,}자"
    )


def with_receipt(answer: str, entries: list[Escalation]) -> str:
    line = receipt_line(entries)
    if not line or RECEIPT_MARK in str(answer or ""):
        return answer
    return str(answer or "").rstrip() + "\n\n" + line


def advice_message(advice: str) -> str:
    """루프에 끼울 말. 조언은 근거가 아니다 — 확인은 손자리가 도구로 한다."""
    return (
        "[클로드 조언 — 사용자의 API 키로 한 번 물음]\n"
        f"{advice.strip()}\n\n"
        "이 조언은 참고일 뿐 근거가 아니다. 조언에 나온 값 · 주소를 확인된 것처럼 답에 쓰지 말고, **도구를 불러 직접 확인**해라. "
        "지금까지 찾은 것을 버리지 말고 다음 걸음을 정해라. 해 봐도 안 되면 못 한 것을 못 했다고 적고 끝내라."
    )


def trace_payload(entries: list[Escalation]) -> dict[str, Any]:
    called = [e for e in entries if e.called]
    return {
        "called": len(called),
        "skipped": [e.skip for e in entries if not e.called],
        "ok": any(e.ok for e in called),
        "usd": round(sum(e.usd for e in called), 6),
        "model": (called[-1].served_model or called[-1].model) if called else "",
        "reason": (called[-1].reason if called else (entries[-1].reason if entries else "")),
        "measure": any(e.measure for e in entries),
    }
