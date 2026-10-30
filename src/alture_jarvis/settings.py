"""설정 화면이 바꾸는 값 (W3, 2026-09-15).

## 값이 사는 자리 — 한 줄로 층층이

    코드 기본값(dataclass)  <  환경변수·.env(관리 설치)  <  data/model_selection.json(첫 실행)  <  data/settings.json(화면)

화면에서 바꾼 값이 **다음 기동에도 이긴다.** 이 저장소는 값이 여러 자리에 살아서 여러 번 데였다
(사고 Q, 「.env 가 항상 졌다」 — `task_entry` 의 `setdefault` 가 로더보다 먼저 환경에 값을 넣어 .env 가 졌다).
그래서 화면 값은 환경변수로 흘려보내지 않고 `JarvisConfig.__post_init__` 에서 **마지막에** 얹는다.
환경에 무엇이 들어 있든 그 뒤다.

## 지키는 것

- 217개를 다 열지 않는다. 아래 `SETTINGS` 표에 있는 칸만 읽고 쓴다. 표 밖 키는 거절한다.
- **비밀은 이 문으로 받지 않는다**(토큰·API 키·OAuth). 표에 넣지 않는 것으로 막는다.
- 값마다 「바로 적용 / 다시 시작해야 적용」을 표에 적는다. 모르면 다시 시작 쪽이다 — 적용된 척이 제일 나쁘다.
- 타입·범위·선택지를 여기서 검사한다. 화면이 계산하지 않는다.
"""

from __future__ import annotations

import json
import math
import threading
import time
from functools import wraps
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

FILE_NAME = "settings.json"
_STORE_LOCK = threading.RLock()


def _serialized(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def locked(*args: Any, **kwargs: Any) -> Any:
        with _STORE_LOCK:
            return method(*args, **kwargs)
    return locked


@dataclass(frozen=True)
class Setting:
    key: str
    group: str
    label: str
    kind: str  # bool · int · str · choice · list · model
    help: str = ""
    live: bool = False
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    # 설정 객체의 어느 속성인가. `model_roles.chat` 처럼 점으로 한 칸 들어간다.
    attr: str = ""
    lab: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def target(self) -> str:
        return self.attr or self.key


# 묶음 순서가 곧 화면 왼쪽 목록 순서다(`PRODUCT_COMPLETION_PLAN.ko.md` 3절).
GROUPS: tuple[tuple[str, str], ...] = (
    ("general", "일반"),
    ("model", "모델"),
    ("voice", "음성"),
    ("memory", "메모리"),
    ("permissions", "권한·안전"),
    ("takeover", "이어받기"),
    ("skills", "스킬"),
    ("labs", "실험실"),
)

SETTINGS: tuple[Setting, ...] = (
    # ── 일반 ──────────────────────────────────────────────────────────────
    Setting("user_label", "general", "부르는 이름", "str", "Sonjari가 사용자를 부를 호칭. 비우면 호칭 없이 말한다.",
            live=True, extra={"max_length": 20}),
    Setting("attention_notices_enabled", "general", "먼저 알려 주기", "bool",
            "작업이 끝나거나 사람이 필요할 때 Sonjari가 먼저 알린다.", live=False),
    Setting("scheduler_enabled", "general", "예약 작업", "bool", "정해 둔 시각에 일을 돌린다."),
    # ── 모델 ──────────────────────────────────────────────────────────────
    Setting("model_chat", "model", "대화 모델", "model", "Ollama 태그. 첫 실행에서 고른 값 위에 얹힌다.",
            live=True, attr="model_roles.chat"),
    Setting("model_code", "model", "코드 모델", "model", "Code 탭이 쓰는 모델.", live=True, attr="model_roles.code"),
    Setting("model_vision", "model", "이미지 모델", "model", "그림·스캔 PDF 를 읽는 모델.", live=True, attr="model_roles.vision"),
    # ★ 2026-09-23: 고정 선택지(16K·32K·64K·128K)였다. 이제 상한은 이 PC 에서 **실측**한다(모델 고르개 › 상한 재기) —
    #   두 배 칸 사이의 진짜 상한(예: 48K)을 받으려면 숫자여야 한다.
    Setting("ollama_num_ctx", "model", "컨텍스트 크기", "int",
            "크게 잡을수록 긴 문서를 한 번에 본다. 그래픽 메모리를 더 쓴다. 모델 고르개의 「상한 재기」가 이 PC 에 맞는 값을 잰다.",
            live=False, minimum=4096, maximum=262144,
            # 선택지 시절에 화면이 **문자열**("131072")로 저장했다. 그 값을 거절하면 갱신하자마자 조용히 기본값으로
            # 돌아간다(`apply_user_settings` 는 깨진 값을 건너뛴다) — 숫자 문자열도 받는다.
            extra={"legacy_digit_string": True}),
    # ★ 2026-09-24: 켜고 끄는 칸(「생각하고 답하기」)을 세 단계로 바꿨다(부산 노트북 「너무 느리다 — 추론 수준을 바꾸는 설정」).
    #   값은 `agent._should_think` 정책 그대로다: always(깊게) · adaptive(보통) · off(빠르게).
    # ★ 2026-10-28: `auto`(자동) 추가 · 기본값. 보통으로 시작해 막히면(되받기 · 실패 걸음 둘) 깊게 — 입력창 칩 「자동」과 같다.
    #   화면에서 바꾼 값만 settings.json 에 남으므로(`patch`), 고른 적 없는 사람은 새 기본값을 그대로 받는다.
    Setting("agent_thinking_policy", "model", "생각 깊이", "choice",
            "자동: 보통으로 시작해 막히면 깊게 생각한다. 깊게: 걸음마다 생각해 꼼꼼하지만 느리다. "
            "보통: 처음과 막혔을 때만 짧게 생각한다. 빠르게: 생각 없이 바로 한다.",
            live=True, choices=("auto", "off", "adaptive", "always")),
    Setting("ollama_max_tool_steps", "model", "한 번에 쓸 걸음 수", "int", "작업 한 판에서 도구를 부르는 최대 횟수.",
            live=True, minimum=4, maximum=40),
    # ── 음성 ──────────────────────────────────────────────────────────────
    Setting("voice_enabled", "voice", "말로 시키기", "bool", "마이크로 받아 적는다(음성 인식)."),
    Setting("tts_enabled", "voice", "소리 내어 답하기", "bool", "짧은 답을 음성으로 읽는다."),
    # 선택지를 지어내지 않는다 — 설치된 음성 목록을 아직 코드가 모른다. 이름만 받는다(예: F1).
    Setting("supertonic_voice", "voice", "목소리", "str", "음성 이름. 예: F1", extra={"max_length": 12}),
    Setting("hotkey_enabled", "voice", "단축키 쓰기", "bool", "누르고 말하기 단축키."),
    Setting("hotkey", "voice", "단축키", "str", "예: f9", extra={"max_length": 20}),
    Setting("media_pause_enabled", "voice", "말할 때 음악 멈추기", "bool", "", live=True),
    # ── 메모리 ────────────────────────────────────────────────────────────
    Setting("memory_retrieval_enabled", "memory", "지난 대화 찾아 쓰기", "bool", "관련 있는 옛 대화를 찾아 맥락에 넣는다.", live=True),
    Setting("fact_learning_enabled", "memory", "배운 사실 기억하기", "bool", "대화에서 사용자에 대한 사실을 뽑아 둔다.", live=True),
    Setting("memory_backup_enabled", "memory", "기억 복제본 두기", "bool",
            "앱을 지워도 대화·배운 사실이 남도록 사용자 폴더에 복제본을 둔다.", attr="memory_backup_dir"),
    # ── 권한·안전 ─────────────────────────────────────────────────────────
    Setting("local_file_allowed_roots", "permissions", "고치고 만들 수 있는 폴더", "list",
            "Sonjari가 파일을 만들거나 고치는 곳. 이 밖에 쓰려면 승인 카드를 받아야 한다."),
    # ★ 2026-09-20: 읽기와 쓰기를 갈랐다. 코워크는 이 PC 를 보고 답하는 자리라 **읽을 수 있어야**
    #   보고가 된다(오늘 코워크 판들이 저장소·메모 폴더에서 전부 막혔다). 비우면 사용자 폴더 전체.
    #   비밀(`.env`·키·토큰·다른 AI 도구 기록·브라우저 프로필)은 이 목록과 무관하게 항상 막힌다.
    Setting("local_read_roots", "permissions", "읽기만 할 수 있는 폴더", "list",
            "보고용으로 읽기만 하는 곳. 비우면 사용자 폴더 전체를 읽는다. 비밀 파일은 여기서도 안 열린다."),
    # ★ 2026-09-20: 셸을 열면서 같이 둔다. 기본 꺼짐 — 바꾸는 명령은 승인 카드가 뜬다.
    Setting("shell_autorun_enabled", "permissions", "셸 명령 자동 실행", "bool",
            "켜면 작업 폴더 안에서 파일을 만들고 지우는 명령도 승인 없이 돈다. 보안 설정·시스템 폴더는 켜도 막힌다.",
            live=True),
    # 권한 모드 `read_only` 가 끄는 자리. 끄면 바꾸는 도구가 **승인으로도 안 간다** —
    # 이번 판은 안 바꾸기로 한 것이라 물어볼 것이 없다(2026-09-21).
    Setting("local_write_enabled", "permissions", "바꾸기 허용", "bool",
            "끄면 읽고 계획만 말합니다. 파일·브라우저·일정 어느 것도 바꾸지 않습니다.", live=True),
    Setting("browser_enabled", "permissions", "브라우저 쓰기", "bool", "웹을 직접 열어 조사한다."),
    Setting("browser_read_only", "permissions", "브라우저는 읽기만", "bool", "끄면 폼 입력·제출을 한다(되돌릴 수 없는 것은 여전히 승인)."),
    Setting("google_write_enabled", "permissions", "Google 쓰기", "bool", "메일 보내기·일정 만들기. 켜면 권한을 다시 받는다.", live=True),
    Setting("windows_control_enabled", "permissions", "창·앱 조작", "bool", "열린 창을 앞으로 가져오고 조작한다."),
    Setting("approval_ttl_sec", "permissions", "승인 유효 시간(초)", "int", "승인 카드가 이 시간 뒤에 만료된다.",
            minimum=60, maximum=7200),
    # 바깥 Claude 가 시킨 일은 승인 카드가 온텔릭 창에만 떠서, 사람이 못 보면 30분 뒤 조용히 죽는다(2026-09-16).
    Setting("approval_auto_reversible", "permissions", "되돌릴 수 있는 일은 자동 승인", "bool",
            "내 폴더에 파일 쓰기처럼 되돌리기가 있는 일만 자동으로 진행한다. 메일 보내기·발행·결제·삭제는 항상 물어본다.",
            live=True),
    Setting("approval_bypass_enabled", "permissions", "권한 무시", "bool",
            "묻지 않고 다 한다(지우기·폴더 권한·PC 설정 포함). 결제·메일 보내기·블로그 발행만 물어본다.",
            live=True),
    # ── 이어받기 ──────────────────────────────────────────────────────────
    Setting("takeover_enabled", "takeover", "멈춘 AI 작업 이어받기", "bool",
            "Claude Code·Codex 가 사용량 한도로 멈추면 이어갈지 묻는다.", live=True),
    Setting("takeover_branch_enabled", "takeover", "코드 가지에서 이어 작업", "bool",
            "git 가지를 따로 만들어 코드를 이어 고친다. 아직 베타다.", live=True, lab=True),
    # ── 스킬 ──────────────────────────────────────────────────────────────
    Setting("skills_route_enabled", "skills", "요청에 맞는 스킬 붙이기", "bool",
            "요청에 맞는 일하는 방법(스킬)을 골라 답에 참고한다.", live=True),
    Setting("skills_domains", "skills", "주로 쓰는 분야", "list", "고른 분야의 스킬만 후보로 둔다. 비우면 전부.", live=True),
    # ── 연결 ──────────────────────────────────────────────────────────────
    # ★ 2026-10-19: 실험실의 「Claude Code 에 맡기기」를 제품 기능으로 옮겼다 — 클로드가 손자리에 맡기는 길(MCP)의 반대 방향.
    #   묶음 「connect」 는 왼쪽 목록(`GROUPS`)에 없다: 화면의 「사용자 지정 › 연결」(이음 카드가 사는 곳)이 이 칸을 그린다.
    #   기본 꺼짐 · 바로 적용 · 클로드 명령이나 로그인이 없으면 켤 수 없다(`unavailable_reason`) · 측정 판은 늘 꺼짐.
    Setting("claude_code_enabled", "connect", "막히면 내 클로드에게 넘기기", "bool",
            "손자리가 코드 일에서 막혔을 때만 이 PC 의 Claude Code 에 넘깁니다. 내 Claude 구독의 사용 한도를 씁니다.",
            live=True),
    # ★ 2026-10-26 넘기기와 다른 길 — 사용자 자기 API 키로 막힌 자리만 한 번 묻는다(`api_escalation.py`). 기본 꺼짐 · 바로 적용.
    #   키가 없거나 부품(anthropic)이 없으면 켤 수 없다. 키는 이 표로 받지 않는다(머리말 「비밀은 이 문으로 받지 않는다」).
    Setting("api_escalation_enabled", "connect", "막히면 내 API 키로 클로드에게 묻기", "bool",
            "손자리가 같은 자리에서 더 나아가지 못할 때만, 막힌 자리 요약을 내 Anthropic API 키로 클로드에게 보내 다음 할 일을 "
            "한 번 묻습니다. 일은 손자리가 계속합니다. 판마다 한 번 · 답 끝에 든 돈을 적습니다.", live=True),
    Setting("api_escalation_model", "connect", "물어볼 클로드 모델", "choice",
            "기본은 Opus 5.5. Sonnet 5.5 는 절반 값, Haiku 5.5 는 훨씬 싸지만 조언이 얕을 수 있습니다.",
            live=True, choices=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")),
    Setting("api_escalation_monthly_usd", "connect", "한 달 상한(달러)", "int",
            "이번 달에 쓴 돈과 다음 한 번의 최악값을 더해 이 값을 넘으면 묻지 않습니다.",
            live=True, minimum=0, maximum=200),
    # ── 실험실 ────────────────────────────────────────────────────────────
    Setting("sandbox_enabled", "labs", "격리 상자", "bool", "WSL 격리 상자에서 코드를 돌린다.", lab=True),
    Setting("code_scout_enabled", "labs", "코드 정찰기", "bool", "두 번째 그래픽카드의 작은 모델로 저장소를 먼저 훑는다.", lab=True),
    # ★ 2026-10-21 서기(`scribe.py`). 대화 기록은 사람 것이라 **기본 꺼짐 · 고른 폴더만** 읽는다. 루프가 매번 설정을 다시 읽어 바로 적용.
    # ★ 2026-10-22 실험실에서 꺼냈다(대표). 묶음 「scribe」 는 왼쪽 목록(`GROUPS`)에 없다 — 화면의 「사용자 지정 › 서기」가 이 칸과
    #   프로젝트 고르기(`scribe.claude_projects`)를 같이 그린다. 폴더 경로를 손으로 치게 두면 아무도 못 켠다.
    Setting("scribe_enabled", "scribe", "서기 켜기", "bool",
            "손자리가 쉴 때 고른 프로젝트의 클로드 코드 대화를 읽고 정한 것 · 버린 것 · 남은 일을 카드로 쌓습니다. "
            "대화가 압축되거나 새 대화를 열면 그 카드를 클로드에게 다시 넣어 줍니다.", live=True),
    Setting("scribe_folders", "scribe", "서기가 읽을 프로젝트", "list",
            "클로드 코드 대화 기록 폴더(사용자 폴더\\.claude\\projects\\<프로젝트>). 여기 고른 곳만 읽습니다.", live=True),
)

BY_KEY: dict[str, Setting] = {item.key: item for item in SETTINGS}

# 이 낱말이 키에 들어가면 표에 있어도 거절한다 — 누가 실수로 표에 넣어도 비밀 문이 안 열리게.
_SECRET_MARKERS = ("token", "secret", "password", "api_key", "apikey", "credential")


class SettingsError(ValueError):
    pass


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def read_user_values(data_dir: Path) -> dict[str, Any]:
    try:
        raw = json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    values = raw.get("values") if isinstance(raw, dict) else None
    if not isinstance(values, dict):
        return {}
    # 실행과 화면이 같은 값을 본다. 깨진 값은 기본값으로 돌아간다.
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        try:
            cleaned[key] = validate(key, value)
        except SettingsError:
            continue
    return cleaned


def _get(config: Any, setting: Setting) -> Any:
    target = setting.target
    if setting.key == "memory_backup_enabled":
        return getattr(config, "memory_backup_dir", None) is not None
    if "." in target:
        head, tail = target.split(".", 1)
        return (getattr(config, head, None) or {}).get(tail, "")
    value = getattr(config, target, None)
    if setting.kind == "list":
        if isinstance(value, str):
            return [part for part in value.split(";") if part.strip()]
        return list(value or [])
    if setting.kind == "choice":
        return str(value)
    return value


def _set(config: Any, setting: Setting, value: Any) -> None:
    target = setting.target
    if setting.key == "memory_backup_enabled":
        if not value:
            config.memory_backup_dir = None
        elif getattr(config, "memory_backup_dir", None) is None:
            from .config import _default_backup_root

            config.memory_backup_dir = _default_backup_root()
        return
    if "." in target:
        head, tail = target.split(".", 1)
        mapping = dict(getattr(config, head, None) or {})
        mapping[tail] = value
        setattr(config, head, mapping)
        return
    if setting.kind == "list" and isinstance(getattr(config, target, None), str):
        setattr(config, target, ";".join(value))
        return
    if setting.kind == "list":
        setattr(config, target, tuple(value))
        return
    if setting.kind == "choice" and isinstance(getattr(config, target, None), int):
        setattr(config, target, int(value))
        return
    setattr(config, target, value)


def validate(key: str, value: Any) -> Any:
    setting = BY_KEY.get(key)
    if setting is None or any(marker in key.lower() for marker in _SECRET_MARKERS):
        raise SettingsError(f"not_allowed:{key}")
    kind = setting.kind
    if kind == "bool":
        if not isinstance(value, bool):
            raise SettingsError(f"expected_bool:{key}")
        return value
    if kind == "int":
        if setting.extra.get("legacy_digit_string") and isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or (isinstance(value, float) and not math.isfinite(value)) or int(value) != value):
            raise SettingsError(f"expected_int:{key}")
        number = int(value)
        if setting.minimum is not None and number < setting.minimum:
            raise SettingsError(f"too_small:{key}")
        if setting.maximum is not None and number > setting.maximum:
            raise SettingsError(f"too_large:{key}")
        return number
    if kind == "choice":
        text = str(value)
        if text not in setting.choices:
            raise SettingsError(f"not_a_choice:{key}")
        return text
    if kind in {"str", "model"}:
        if not isinstance(value, str):
            raise SettingsError(f"expected_str:{key}")
        text = " ".join(value.split())
        limit = int(setting.extra.get("max_length", 120))
        if len(text) > limit:
            raise SettingsError(f"too_long:{key}")
        if kind == "model" and not text:
            raise SettingsError(f"empty_model:{key}")
        return text
    if kind == "list":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise SettingsError(f"expected_list:{key}")
        cleaned = [" ".join(item.split()) for item in value if item.strip()]
        if len(cleaned) > 30:
            raise SettingsError(f"too_many:{key}")
        return cleaned
    raise SettingsError(f"unknown_kind:{key}")


def apply_user_settings(config: Any) -> list[str]:
    """`data/settings.json` 을 설정에 얹는다. 얹은 키 목록을 돌려준다(어디서 왔는지 보이게)."""
    applied: list[str] = []
    config._settings_defaults = {item.key: _get(config, item) for item in SETTINGS}
    for key, raw in read_user_values(Path(config.data_dir)).items():
        try:
            _set(config, BY_KEY[key], validate(key, raw))
        except SettingsError:
            continue  # 깨진 값 하나로 자비스가 안 뜨면 안 된다. 화면이 「기본값으로 돌아감」을 보인다.
        applied.append(key)
    return applied


@_serialized
def adopt_model_selection(config: Any, *, vision: bool, code_follows_chat: bool = False) -> None:
    """측정 후 적용은 이전 수동 모델·대화 길이 선택을 대체한다. 코드 역할은 보존한다 — **따로 골랐을 때만**.

    ★ 2026-09-30: 대화·코드 둘 다 3.6 이던 PC 에서 대화만 3.8 로 바꾸자 코드가 3.6 에 남았다. Ollama 는 모델을 하나만
      올리므로(OLLAMA_MAX_LOADED_MODELS=1) 한 과제 안에서 대화 걸음(3.8)과 코드 걸음(3.6)이 서로를 밀어냈고
      (적재 70초·40초), 3.6 은 잰 적 없는 코드 창 102400 으로 올라가 GPU 94% — CPU 로 샜다.
      코드가 **대화와 같은 모델을 따라가고 있었으면**(`code_follows_chat`) 새 대화 모델로 같이 옮긴다.

    ★ 2026-10-10: 따라갈 때 대화 모델 이름을 `model_code` 에 **베껴 적지 않는다.** 사본은 원본과 어긋난다 — 이 PC 에서
      대화 쪽만 되돌리자 사본이 작은 양자화에 남아 하루 종일 두 모델이 서로를 밀어냈다. 「따라간다」는 선택 파일의
      한 줄이 적고(`model_setup.follow_chat_with_code`), 여기서는 옛 사본을 지운다.
    """
    keys = ['model_chat', 'ollama_num_ctx']
    if vision:
        keys.append('model_vision')
    values = read_user_values(Path(config.data_dir))
    for key in keys:
        values.pop(key, None)
        config._settings_defaults[key] = _get(config, BY_KEY[key])
    if code_follows_chat:
        chat = str(config.model_for("chat"))
        values.pop("model_code", None)
        keys.append("model_code")
        roles = dict(config.model_roles or {})
        roles["code"] = chat
        config.model_roles = roles
        config._settings_defaults["model_code"] = chat
    SettingsService(config)._write(settings_path(Path(config.data_dir)), values)
    config.settings_applied = tuple(key for key in config.settings_applied if key not in keys)


#: 이 기능이 **이 판에서 실제로 되는가**. 안 되면 화면이 「켜짐」 대신 그 이유를 말한다.
#
# ★ 2026-09-18 아버님 노트북. 설정에는 「말로 시키기: 켜짐」「소리 내어 답하기: 켜짐」이라고 적혀 있는데
#   실제로는 받아쓰기 모듈이 포장본에 없었고(`faster_whisper_not_installed`) 음성 서버도 안 떠 있었다.
#   켜짐이라 적힌 것이 실제로는 못 쓰는 상태 — 사람은 자기가 뭘 잘못한 줄 안다. 그래서 표시를
#   **설정값이 아니라 실제 가능 여부**로 바꾼다.
_CAPABILITY_MODULES: dict[str, tuple[tuple[str, ...], str]] = {
    "voice_enabled": (("faster_whisper", "ctranslate2"), "이 판에는 받아쓰기가 들어 있지 않습니다"),
    "hotkey_enabled": (("keyboard",), "이 판에는 단축키 기능이 들어 있지 않습니다"),
    "tts_enabled": (("supertonic",), "이 판에는 음성 출력이 들어 있지 않습니다"),
    "media_pause_enabled": (("winrt.windows.media.control",), "이 판에는 음악 제어가 들어 있지 않습니다"),
}


#: 구글 연결이 있어야만 뜻이 있는 설정. 연결을 시작할 수 없는 빌드에선 화면에서 뺀다.
_GOOGLE_ONLY_SETTINGS = frozenset({"google_write_enabled"})


#: 모듈이 아니라 **이 PC 의 바깥 프로그램**이 있어야 되는 설정 — 까닭과 짧은 상태 말을 함께 돌려준다(2026-10-19).
_EXTERNAL_CAPABILITY = frozenset({"claude_code_enabled", "api_escalation_enabled"})


def _external_block(key: str, config: Any) -> tuple[str, str]:
    if key == "claude_code_enabled" and config is not None:
        from .claude_code import cli_status

        status = cli_status(config)
        return str(status.get("reason") or ""), str(status.get("short") or "")
    if key == "api_escalation_enabled" and config is not None:
        from .api_escalation import unavailable

        return unavailable(config)
    return "", ""


def unavailable_short(key: str, config: Any = None) -> str:
    """화면의 「이 판에서는 못 씁니다」 자리에 들어갈 짧은 말. 빈 값이면 그 기본 말을 쓴다."""
    return _external_block(key, config)[1] if key in _EXTERNAL_CAPABILITY else ""


def unavailable_reason(key: str, config: Any = None) -> str:
    """빈 문자열이면 쓸 수 있다는 뜻. 「못 봤다」와 「없다」를 섞지 않으려고 모듈을 직접 찾아본다."""
    import importlib.util

    if key in _EXTERNAL_CAPABILITY:
        return _external_block(key, config)[0]
    modules, reason = _CAPABILITY_MODULES.get(key, ((), ""))
    for name in modules:
        try:
            if importlib.util.find_spec(name) is None:
                return reason
        except (ImportError, ValueError):  # 반쯤 깔린 패키지도 「없다」로 친다
            return reason
    return ""


class SettingsService:
    def __init__(self, config: Any, *, on_live_change: Callable[[list[str]], None] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.config = config
        self.on_live_change = on_live_change
        self.clock = clock
        # 이 프로세스가 뜰 때의 값. 「다시 시작해야 적용」을 판단하는 기준이다.
        self._boot = {item.key: _get(config, item) for item in SETTINGS}
        user = read_user_values(Path(config.data_dir))
        defaults = getattr(config, "_settings_defaults", {}).copy()
        defaults.update({key: value for key, value in self._boot.items() if key not in user})
        config._settings_defaults = defaults

    @_serialized
    def view(self) -> dict[str, Any]:
        user = read_user_values(Path(self.config.data_dir))
        rows = []
        # 구글 연결을 시작할 수 없는 빌드(공개판)엔 구글 설정을 진열하지 않는다 (2026-10-01).
        from .google_workspace import oauth_client_present

        hidden = set() if oauth_client_present(self.config) else _GOOGLE_ONLY_SETTINGS
        for item in SETTINGS:
            if item.key in hidden:
                continue
            current = _get(self.config, item)
            desired = user.get(item.key, self.config._settings_defaults.get(item.key, current))
            blocked = unavailable_reason(item.key, self.config)
            rows.append({
                "key": item.key, "group": item.group, "label": item.label, "kind": item.kind, "help": item.help,
                "choices": list(item.choices), "min": item.minimum, "max": item.maximum, "lab": item.lab,
                "value": desired,
                "source": "user" if item.key in user else "default",
                "live": item.live,
                # 이 판에서 못 쓰는 기능이면 그 이유. 화면은 켜짐으로 그리지 않는다.
                "unavailable": blocked,
                # 그 이유의 짧은 상태 말(「관리자가 꺼 둠」 · 「로그인 필요」). 비면 화면이 「이 판에서는 못 씁니다」를 쓴다.
                **({"unavailable_short": unavailable_short(item.key, self.config)} if blocked else {}),
                # 저장했지만 아직 이 프로세스에 안 먹은 값.
                "restart_required": (not item.live) and desired != current,
            })
        return {"groups": [{"id": gid, "label": label} for gid, label in GROUPS], "settings": rows,
                "path": str(settings_path(Path(self.config.data_dir)))}

    @_serialized
    def patch(self, changes: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, dict) or not changes:
            return {"ok": False, "error": "empty"}
        cleaned: dict[str, Any] = {}
        try:
            for key, value in changes.items():
                cleaned[key] = validate(str(key), value)
                # 바깥 프로그램이 있어야 되는 기능은 **없으면 켜지지 않는다**(끄는 것은 언제나 된다). 켜짐으로 저장해 두면
                # 화면은 꺼짐으로 그리는데 나중에 프로그램이 생기는 순간 사람 모르게 켜진다 — 켜는 것은 사람이 그때 한다.
                if key in _EXTERNAL_CAPABILITY and cleaned[key] is True and unavailable_reason(key, self.config):
                    raise SettingsError(f"unavailable:{key}")
        except SettingsError as exc:
            return {"ok": False, "error": str(exc)}
        path = settings_path(Path(self.config.data_dir))
        values = read_user_values(Path(self.config.data_dir))
        values.update(cleaned)
        self._write(path, values)
        live = [key for key in cleaned if BY_KEY[key].live]
        for key in live:
            _set(self.config, BY_KEY[key], cleaned[key])
        # 이 판에서 화면으로 고른 것도 「따로 고른 것」이다 — 켤 때 읽은 목록만 보면 방금 고른 코드 모델이 따라가기에 덮인다.
        applied_before = tuple(getattr(self.config, "settings_applied", ()) or ())
        self.config.settings_applied = tuple(dict.fromkeys((*applied_before, *cleaned)))
        if "model_chat" in live:
            # 화면에서 대화 모델만 바꿔도, 코드가 대화를 따라가는 PC 면 같이 간다(사본이 없으니 여기서 맞춘다).
            from .model_setup import follow_chat_with_code

            follow_chat_with_code(self.config)
        if live and self.on_live_change is not None:
            self.on_live_change(live)
        restart = [key for key in cleaned if not BY_KEY[key].live and cleaned[key] != _get(self.config, BY_KEY[key])]
        return {"ok": True, "applied": live, "restart_required": restart, **self.view()}

    @_serialized
    def reset(self, keys: list[str] | None = None) -> dict[str, Any]:
        """사용자 값을 지운다(기본·관리 설치 값으로 돌아감). 키가 없으면 전부."""
        path = settings_path(Path(self.config.data_dir))
        values = read_user_values(Path(self.config.data_dir))
        selected = keys if keys is not None else list(values)
        if any(key not in BY_KEY for key in selected):
            return {"ok": False, "error": "not_allowed:reset"}
        live = [key for key in selected if BY_KEY[key].live]
        for key in selected:
            values.pop(key, None)
        self._write(path, values)
        self.config.settings_applied = tuple(
            key for key in tuple(getattr(self.config, "settings_applied", ()) or ()) if key not in selected)
        for key in live:
            _set(self.config, BY_KEY[key], self.config._settings_defaults[key])
        if live and self.on_live_change is not None:
            self.on_live_change(live)
        view = self.view()
        restart = [row["key"] for row in view["settings"] if row["key"] in selected and row["restart_required"]]
        return {"ok": True, "applied": live, "restart_required": restart, **view}

    def _write(self, path: Path, values: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps({"version": 1, "updated_at": self.clock(), "values": values},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)


__all__ = ["GROUPS", "SETTINGS", "SettingsError", "SettingsService", "apply_user_settings", "read_user_values", "validate"]
