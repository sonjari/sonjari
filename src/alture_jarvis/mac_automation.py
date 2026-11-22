"""맥 창 조종 — 오픈소스 Peekaboo(openclaw/Peekaboo · MIT · v4.9.8 NAS 동결) CLI 를 감싼다. `windows_automation.py` 의 짝.

설계: `docs/설계_맥_컴퓨터유즈_2026-11-16.ko.md`. 흐름은 윈도우와 같다 — 읽기(L0) → 미리보기(L1 · 실행 안 함) → 사람 승인 뒤 실행(L2).

★ 11-16 맥미니 실측에서 겪은 함정 셋을 **코드로** 막는다(안내문이 아니다):
  1. NFD 한글 — 창 · 앱 · 요소 이름이 낱자 분해로 온다(「무제 2」 길이 6). 들어오고 나가는 **모든 이름**을 NFC 로 맞춘다(`_nfc`).
  2. 창 지정 — 지정 없이 찍었더니 대표의 기존 문서 창(`버그막이_설계.md`)이 잡혔다. 화면 바꾸는 동작은 **window_id 로만**, 실행 직전에
     그 창을 다시 찍어 창 이름이 미리보기 때와 같을 때만 보낸다(다르면 `window_changed` 거절 · 동작 명령은 한 번도 안 부른다).
  3. 성공 신호 불신 — type · click · press 는 「보냈지만 확인 안 됨」을 돌려준다(3판 타자는 rc=1 인데 실제로 들어갔다). 실행 뒤 같은 창을
     `see --fresh` 로 다시 읽어 `verified` / `not_verified` / `window_changed` 로 판정한다. Peekaboo rc 는 참고로만 싣는다.

밖으로 안 보낸다: `--analyze` · `agent` · `mcp` 와 원격 다리는 막는다 — 모든 부름은 `--no-remote` 로 끝난다. 부르는 길은 설정 한 칸
(`mac_peekaboo_transport`): `app`(기본 · 서명한 도우미 앱 꾸러미를 `open -a` 로 — 허락이 그 꾸러미에 붙는다) · `direct`(실행 파일 직접).
허락(화면 및 시스템 오디오 녹음 · 기기 제어 및 데이터 접근)이 없으면 `permission_needed` 로 거절한다 — 지어내지 않는다.
허락 켜기를 돕는 갈래(`permission_status` · `permission_setup`)는 모델 도구가 아니라 백엔드 길이다(`/v1/mac/permissions`).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

#: 부를 수 있는 Peekaboo 하위 명령 — 이것 말고는 부르지 않는다(`agent` · `mcp` · `learn` 같은 AI · 원격 문은 여기 없다).
_ALLOWED_SUBCOMMANDS = frozenset({"see", "window", "app", "click", "set-value", "type", "press", "paste", "action", "permissions"})
#: `permissions request <종류>` 로 띄울 수 있는 허락 창.
_PERMISSION_KINDS = frozenset({"screen-recording", "accessibility"})
#: 어느 자리에 와도 거절하는 인자 — AI 분석 · 길을 부르는 쪽이 덧붙이는 것. (`agent` · `mcp` 는 하위 명령 허용 목록이 막는다 —
#:   붙여넣을 글에 그 낱말이 들어 있어도 막히지 않게 여기엔 두지 않는다.)
_FORBIDDEN_ARGS = frozenset({"--analyze", "--no-remote", "--bridge-socket", "--bridgeSocket"})
_TRANSPORTS = ("app", "direct")

_ACTIONS = ("invoke", "click", "set_value", "toggle", "select", "focus", "key", "paste")
#: Peekaboo 키 이름 — `cmd+s` 꼴(쉼표로 이으면 거절된다 · 1판 실측 `Invalid chord 'cmd,n'`).
_MODIFIERS = frozenset({"cmd", "command", "shift", "option", "opt", "alt", "ctrl", "control", "fn"})
_KEY_TOKEN = re.compile(r"^[a-z0-9]+$|^[\[\]\\;',./`=\-]$")
_DESTRUCTIVE_KEYS = frozenset({"cmd+q", "cmd+w", "cmd+delete", "cmd+backspace", "cmd+option+esc"})
#: 이름으로 여는 맥 앱 → 번들 ID(앱 이름 · 퍼지 매칭으로는 열지 않는다 — 실측 함정 ②).
_LAUNCHABLE_APPS: dict[str, str] = {
    "텍스트 편집기": "com.apple.TextEdit", "textedit": "com.apple.TextEdit",
    "finder": "com.apple.finder", "파인더": "com.apple.finder",
    "계산기": "com.apple.calculator", "calculator": "com.apple.calculator",
    "미리보기": "com.apple.Preview", "preview": "com.apple.Preview",
    "메모": "com.apple.Notes", "notes": "com.apple.Notes",
    "시스템 설정": "com.apple.systempreferences", "system settings": "com.apple.systempreferences",
}
_TEXT_ROLES = frozenset({"textField", "textArea", "staticText", "text"})
_PASSWORD_AX_ROLES = frozenset({"AXSecureTextField"})


def _nfc(value: Any) -> str:
    """NFD 로 온 한글을 NFC 로. 이 파일에서 이름 · 값은 전부 이것을 지난다."""
    return unicodedata.normalize("NFC", str(value or ""))


def _same_name(left: Any, right: Any) -> bool:
    return _nfc(left).strip() == _nfc(right).strip()


def normalize_key_combo(combo: str) -> str:
    """`cmd+s` 꼴로 맞춘다. 못 알아들으면 ValueError(쉼표 · 빈 토막 · 수식키만)."""
    text = _nfc(combo).strip().lower().replace(" ", "")
    if not text or "," in text:
        raise ValueError(f"key_combo_invalid: 「{combo}」 — 키는 cmd+s 처럼 + 로 잇습니다(쉼표 안 됨).")
    parts = text.split("+")
    if any(not part for part in parts) or not all(part in _MODIFIERS or _KEY_TOKEN.match(part) for part in parts):
        raise ValueError(f"key_combo_invalid: 「{combo}」 — 키는 cmd+s 처럼 + 로 잇습니다.")
    if all(part in _MODIFIERS for part in parts):
        raise ValueError(f"key_combo_invalid: 「{combo}」 — 수식키만으로는 보낼 수 없습니다.")
    return "+".join(parts)


@dataclass(slots=True)
class PeekabooResult:
    rc: int
    data: dict[str, Any] | None
    error_code: str
    message: str
    text: str
    #: 맨 위의 `target_receipt`(실측 see1.json: `data` 밖에 있다) — 실제로 찍힌 창 번호.
    receipt: dict[str, Any] = field(default_factory=dict)


class PermissionNeeded(PermissionError):
    pass


#: 허락 이름 — macOS 27 기준(「손쉬운 사용」이 「기기 제어 및 데이터 접근」으로 바뀌었다 · 주력 세션 11-16 확인).
_SCREEN_LABEL = "화면 및 시스템 오디오 녹음"
_CONTROL_LABEL = "기기 제어 및 데이터 접근"
_PERMISSION_NOTE = ("permission_needed: 맥의 「시스템 설정 → 개인정보 보호 및 보안 → {what}」에서 「손자리 화면 도우미」를 켜야 화면을 읽고 누를 수 있습니다. "
                    "허락 전에는 이 도구가 아무것도 하지 않습니다 — 사람에게 허락을 켜 달라고 알리세요.")


class PeekabooRunner:
    """Peekaboo CLI 를 부르는 유일한 자리. 인자 검사 · 길(app/direct) 붙이기 · json 풀기 · 허락 오류 판정.

    ★ 2026-11-16 허락 주인 실측(주력 세션 · 설계 §8 은 주력 가지에): 다리 소켓(`--bridge-socket`)은 허락이 다 켜졌는데도 `see` 를
      「host did not satisfy Peekaboo runtime requirements」로 거절했다. 대신 **서명한 앱 꾸러미를 LaunchServices 로 실행**하면
      허락이 그 꾸러미(`com.sonjari.screenhelper`)에 붙고, 허락 없는 ssh 에서도 요소 356개 0.41초 · 찍기 · 누르고 다시 읽기가 됐다.
      그래서 기본 길은 `app` — `open -W -n -g --stdout <파일> --stderr <파일> -a <도우미.app> --args <명령…> --json --no-remote`.
      출력은 부르기마다 다른 파일로 받아 읽고 지운다. `direct` 는 실행 파일을 바로 부르는 길(시험 · 개발용 · 허락이 부른 쪽에 붙는다).
    """

    def __init__(
        self,
        binary: str = "",
        *,
        transport: str = "app",
        app_bundle: str = "",
        io_dir: Path | None = None,
        timeout_sec: float = 30.0,
        run: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        if transport not in _TRANSPORTS:
            raise ValueError(f"peekaboo_transport_unknown:{transport} — app 또는 direct")
        if transport == "app" and not str(app_bundle or "").strip():
            raise ValueError("peekaboo_app_missing: app 길은 도우미 앱 꾸러미 경로가 있어야 합니다(JARVIS_MAC_PEEKABOO_APP).")
        if transport == "direct" and not str(binary or "").strip():
            raise ValueError("peekaboo_binary_missing: direct 길은 실행 파일 경로가 있어야 합니다(JARVIS_MAC_PEEKABOO_BIN).")
        self.binary = str(binary or "").strip()
        self.transport = transport
        self.app_bundle = str(app_bundle or "").strip()
        self.io_dir = Path(io_dir) if io_dir is not None else Path(os.environ.get("TMPDIR") or "/tmp") / "sonjari-peekaboo"
        self.timeout_sec = timeout_sec
        self._run = run or subprocess.run
        #: 부른 인자 전부(시험 · 증거용). 마지막 200개만.
        self.calls: list[list[str]] = []

    @staticmethod
    def command(*args: str) -> list[str]:
        """Peekaboo 명령 한 줄 — 허용 목록 · 금지 인자 검사 뒤 `--json --no-remote` 를 붙인다(원격 다리는 어느 길에서도 안 탄다)."""
        args = tuple(str(arg) for arg in args)
        if not args or args[0] not in _ALLOWED_SUBCOMMANDS:
            raise PermissionError(f"peekaboo_subcommand_not_allowed:{args[0] if args else ''}")
        if args[0] == "permissions" and not (len(args) == 1 or (len(args) == 2 and args[1] == "status")
                                              or (len(args) == 3 and args[1] == "request" and args[2] in _PERMISSION_KINDS)):
            raise PermissionError(f"peekaboo_permissions_subcommand_not_allowed:{' '.join(args[1:])}")
        bad = [arg for arg in args if arg in _FORBIDDEN_ARGS or arg.startswith("--analyze")]
        if bad:
            raise PermissionError(f"peekaboo_arg_not_allowed:{bad[0]}")
        return [*args, "--json", "--no-remote"]

    def argv(self, *args: str, out_file: str = "", err_file: str = "") -> list[str]:
        command = self.command(*args)
        if self.transport == "direct":
            return [self.binary, *command]
        return ["/usr/bin/open", "-W", "-n", "-g", "--stdout", out_file, "--stderr", err_file, "-a", self.app_bundle,
                "--args", *command]

    def call(self, *args: str, check_permission: bool = True) -> PeekabooResult:
        env = dict(os.environ)
        env.update({"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"})
        out_file = err_file = ""
        if self.transport == "app":
            self.io_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{int(time.time() * 1000)}-{secrets.token_hex(6)}"  # 부르기마다 다른 파일(겹쳐 부를 때 섞이지 않게)
            out_file, err_file = str(self.io_dir / f"{stem}.out"), str(self.io_dir / f"{stem}.err")
        argv = self.argv(*args, out_file=out_file, err_file=err_file)
        self.calls.append(argv)
        del self.calls[:-200]
        try:
            done = self._run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=self.timeout_sec, env=env, check=False)
        except FileNotFoundError as exc:
            raise RuntimeError(f"not_ready: Peekaboo 를 부를 수 없습니다({self.binary or self.app_bundle}).") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"peekaboo_timeout: {self.timeout_sec:.0f}초 안에 끝나지 않았습니다.") from exc
        stdout, stderr = str(done.stdout or ""), str(done.stderr or "")
        if self.transport == "app":
            stdout, stderr = _take(out_file), _take(err_file) + ("\n" + stderr if stderr.strip() else "")
        return self.parse(int(done.returncode), stdout, stderr, check_permission=check_permission)

    @staticmethod
    def parse(rc: int, stdout: str, stderr: str = "", *, check_permission: bool = True) -> PeekabooResult:
        text = _nfc((stdout or "") + ("\n" + stderr if stderr else ""))
        payload: dict[str, Any] | None = None
        start = stdout.find("{")
        if start >= 0:
            try:
                loaded = json.loads(stdout[start:])
                payload = loaded if isinstance(loaded, dict) else None
            except json.JSONDecodeError:
                payload = None
        error = (payload or {}).get("error") if isinstance((payload or {}).get("error"), dict) else {}
        code = str(error.get("code") or "")
        message = _nfc(error.get("message") or "")
        data = (payload or {}).get("data")
        receipt = (payload or {}).get("target_receipt")
        result = PeekabooResult(rc=rc, data=data if isinstance(data, dict) else None, error_code=code, message=message, text=text,
                                receipt=receipt if isinstance(receipt, dict) else {})
        if check_permission:
            PeekabooRunner.raise_if_permission(result)
        return result

    @staticmethod
    def raise_if_permission(result: PeekabooResult) -> None:
        code = result.error_code.upper()
        lowered = (result.message + "\n" + result.text).lower()
        if code.startswith("PERMISSION") or "missingpermissions" in lowered.replace(" ", "") or (
            "permission" in lowered and ("screen recording" in lowered or "accessibility" in lowered)
        ):
            what = _SCREEN_LABEL if "SCREEN" in code or "screen recording" in lowered else _CONTROL_LABEL
            raise PermissionNeeded(_PERMISSION_NOTE.format(what=what))


def _take(path: str) -> str:
    """`open --stdout` 이 쓴 파일을 읽고 지운다. 없으면 빈 글."""
    if not path:
        return ""
    try:
        file = Path(path)
        text = file.read_text(encoding="utf-8", errors="replace")
        file.unlink(missing_ok=True)
        return text
    except OSError:
        return ""


@dataclass(slots=True)
class MacPreview:
    preview_id: str
    action: str
    window_id: int
    window_title: str
    app: str
    target: dict[str, Any]
    value: str
    screenshot_path: str
    before: dict[str, Any]
    created_at: float
    expires_at: float
    used: bool = False


@dataclass(slots=True)
class _Seen:
    """`see --window-id W --json` 한 번의 결과를 NFC 로 맞춘 것."""

    window_id: int
    title: str
    app: str
    snapshot_id: str
    screenshot: str
    elements: list[dict[str, Any]] = field(default_factory=list)
    focused: str = ""

    def by_id(self, element_id: str) -> dict[str, Any] | None:
        return next((row for row in self.elements if row["ref"] == element_id), None)

    def find(self, target: dict[str, Any]) -> dict[str, Any] | None:
        """미리보기 때의 요소를 지금 찍은 것에서 찾는다 — 같은 번호이고 종류 · 이름이 같을 때, 아니면 종류 · 이름(· 식별자)이 같은 하나."""
        same = self.by_id(str(target.get("ref") or ""))
        if same and same["role"] == target.get("role") and same["name"] == target.get("name"):
            return same
        hits = [row for row in self.elements if row["role"] == target.get("role") and row["name"] == target.get("name")
                and (not target.get("identifier") or row.get("identifier") == target.get("identifier"))]
        return hits[0] if len(hits) == 1 else None

    def signature(self) -> dict[str, Any]:
        return {"title": self.title, "focused": self.focused,
                "values": {row["ref"]: row.get("value", "") for row in self.elements},
                "names": sorted(f"{row['role']}:{row['name']}" for row in self.elements)}


def _element(row: dict[str, Any]) -> dict[str, Any] | None:
    ref = str(row.get("id") or "")
    if not ref:
        return None
    name = _nfc(row.get("label") or row.get("title") or row.get("description") or "")[:300]
    out: dict[str, Any] = {"ref": ref, "role": str(row.get("role") or ""), "name": name}
    value = row.get("value")
    if value not in (None, "") and str(row.get("ax_role") or "") not in _PASSWORD_AX_ROLES:
        out["value"] = _nfc(value)[:2000]
    if row.get("identifier"):
        out["identifier"] = _nfc(row["identifier"])[:200]
    if row.get("is_actionable"):
        out["actionable"] = True
    if row.get("is_value_settable"):
        out["settable"] = True
    if row.get("is_enabled") is False:
        out["enabled"] = False
    if str(row.get("ax_role") or "") in _PASSWORD_AX_ROLES:
        out["password"] = True
    return out


class MacAutomationTools:
    """맥 창 조종 도구 일곱. 미리보기는 읽기만, 실행은 L2 승인 문을 지난다(`windows_automation.WindowsAutomationTools` 짝)."""

    def __init__(
        self,
        config: JarvisConfig,
        *,
        runner: PeekabooRunner | None = None,
        resolve_path: Callable[[str], Path] | None = None,
        open_run: Callable[..., subprocess.CompletedProcess] | None = None,
        wait_for_hands: Callable[[str], None] | None = None,
        settle_sec: float = 0.8,
    ) -> None:
        self.config = config
        self._runner = runner
        self._resolve_path = resolve_path
        self._open_run = open_run or subprocess.run
        self._wait_for_hands = wait_for_hands
        self.settle_sec = settle_sec
        self.preview_dir = config.output_dir / "action-previews"
        self._lock = threading.RLock()
        self._previews: dict[str, MacPreview] = {}
        self._seen: dict[int, _Seen] = {}
        self._definitions = self._build_definitions()

    # ── 정의 · 등록 ─────────────────────────────────────────────
    @staticmethod
    def _function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required or []}}}

    def _build_definitions(self) -> list[dict[str, Any]]:
        window = {"window_id": {"type": "integer", "description": "mac_list_open_windows 결과의 window_id"}}
        return [
            self._function("mac_list_open_windows", "이 맥에서 화면에 열린 앱 창의 제목 · 앱 · 창 ID 를 확인한다.",
                           {"max_results": {"type": "integer", "minimum": 1, "maximum": 100}}),
            self._function("mac_focus_window", "열린 맥 앱 창을 앞으로 가져온다. 창 ID 는 mac_list_open_windows 결과를 쓴다.", window, ["window_id"]),
            self._function("mac_open_path",
                           "허용된 폴더의 파일 · 폴더를 맥 기본 앱으로 연다. 텍스트 편집기 · Finder · 계산기 · 미리보기 · 메모 · 시스템 설정은 path 에 "
                           "이름만 적으면 새로 켠다. 파일을 그 앱들 가운데 하나로 열려면 app 에 앱 이름을 같이 적는다. 실제 실행이라 화면 승인이 필요하다.",
                           {"path": {"type": "string"}, "app": {"type": "string"}}, ["path"]),
            self._function("mac_ax_snapshot", "열린 맥 앱 창 하나의 UI 요소(단추 · 칸 · 값)를 읽고 조작할 ref 를 만든다. 창은 window_id 로만 고른다.",
                           {**window, "max_elements": {"type": "integer", "minimum": 1, "maximum": 300}}, ["window_id"]),
            self._function("mac_ax_preview", "mac_ax_snapshot 의 ref 에 할 누르기 · 값 넣기 · 키 · 붙여넣기를 실제로 하지 않고 미리보기로 만든다.",
                           {**window, "ref": {"type": "string"},
                            "action": {"type": "string", "enum": list(_ACTIONS)},
                            "value": {"type": "string", "description": "set_value=넣을 값, key='cmd+s' 같은 키(+ 로 잇는다), paste=붙여넣을 글. "
                                                                        "key · paste 는 창 전체에 보내므로 ref 를 생략해도 된다."}},
                           ["window_id", "action"]),
            self._function("mac_execute_preview",
                           "앞서 만든 맥 미리보기를 실행한다. 화면 승인이 필수다. 실행 뒤 같은 창을 다시 읽어 verdict(verified · not_verified · "
                           "window_changed)를 돌려준다 — verified 가 아니면 성공했다고 말하지 마라.",
                           {"preview_id": {"type": "string"},
                            "target_summary": {"type": "string", "description": "미리보기의 대상 · 동작을 승인 화면에서 알아볼 수 있게 그대로 요약"},
                            "screenshot_path": {"type": "string", "description": "미리보기 결과의 screenshot_path"}},
                           ["preview_id"]),
            self._function("mac_copy_from_window", "맥 앱 창의 글을 읽어온다 — 요소 값을 먼저 읽고, 없을 때만 전체 선택 · 복사(클립보드는 되돌린다).",
                           {**window, "limit": {"type": "integer", "minimum": 1, "maximum": 20000}}, ["window_id"]),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        """모델에게 보일 도구 — 설정이 꺼져 있으면(기본) 하나도 안 보인다(`AgentToolCatalog` 가 이것을 먼저 본다)."""
        return list(self._definitions) if self.config.mac_control_enabled else []

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "mac_list_open_windows": self.list_open_windows,
            "mac_focus_window": self.focus_window,
            "mac_open_path": self.open_path,
            "mac_ax_snapshot": self.ax_snapshot,
            "mac_ax_preview": self.ax_preview,
            "mac_execute_preview": self.execute_preview,
            "mac_copy_from_window": self.copy_from_window,
        }
        risks = {
            "mac_list_open_windows": RiskLevel.L0,
            "mac_focus_window": RiskLevel.L1,
            "mac_open_path": RiskLevel.L2,
            "mac_ax_snapshot": RiskLevel.L0,
            "mac_ax_preview": RiskLevel.L1,
            "mac_execute_preview": RiskLevel.L2,
            "mac_copy_from_window": RiskLevel.L1,
        }
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(ToolSpec(
                name=name, description=str(definition["function"]["description"]),
                parameters=dict(definition["function"].get("parameters") or {}),
                risk_level=risks[name], handler=handlers[name], enabled=bool(self.config.mac_control_enabled),
            ))
        # 권한 무시여도 닫기 · 끝내기 · 지우기 단축키는 사람이 본다(2026-11-16 대표).
        still_asks = getattr(gateway, "bypass_still_asks", None)
        if isinstance(still_asks, dict):  # 시험의 가짜 게이트웨이에는 없다
            still_asks["mac_execute_preview"] = self.preview_is_destructive

    def preview_is_destructive(self, arguments: dict[str, Any]) -> bool:
        """실행하려는 미리보기가 되돌릴 수 없는 단축키인가. 미리보기를 못 찾으면 True(묻는 쪽)."""
        with self._lock:
            preview = self._previews.get(str(arguments.get("preview_id") or ""))
        if preview is None:
            return True
        return preview.action == "key" and normalize_key_combo(preview.value) in _DESTRUCTIVE_KEYS

    def status(self) -> dict[str, Any]:
        ready, why = self._ready()
        with self._lock:
            active = sum(1 for p in self._previews.values() if p.expires_at >= time.time() and not p.used)
        out = {"enabled": bool(self.config.mac_control_enabled), "ready": ready,
               "transport": self.config.mac_peekaboo_transport, "preview_first": True, "active_previews": active}
        if why:
            out["not_ready"] = why
        return out

    # ── Peekaboo 부르기 ─────────────────────────────────────────
    def _ready(self) -> tuple[bool, str]:
        """부를 수 있는가(파일이 있나만 본다 — 허락은 `permission_status`)."""
        if self._runner is not None:
            return True, ""
        transport = str(self.config.mac_peekaboo_transport or "app")
        if transport == "app":
            app = str(self.config.mac_peekaboo_app or "").strip()
            if not app or not Path(app).is_dir():
                return False, "not_ready: 손자리 화면 도우미 앱 꾸러미가 없습니다(JARVIS_MAC_PEEKABOO_APP). 맥 창 조종을 쓸 수 없습니다."
            return True, ""
        binary = str(self.config.mac_peekaboo_bin or "").strip() or (shutil.which("peekaboo") or "")
        if not binary or not Path(binary).is_file():
            return False, "not_ready: 이 맥에 Peekaboo 실행 파일이 없습니다(JARVIS_MAC_PEEKABOO_BIN). 맥 창 조종을 쓸 수 없습니다."
        return True, ""

    def runner(self) -> PeekabooRunner:
        if self._runner is None:
            ready, why = self._ready()
            if not ready:
                raise RuntimeError(why)
            self._runner = PeekabooRunner(
                str(self.config.mac_peekaboo_bin or "").strip() or (shutil.which("peekaboo") or ""),
                transport=str(self.config.mac_peekaboo_transport or "app"),
                app_bundle=str(self.config.mac_peekaboo_app or ""),
                io_dir=self.config.data_dir / "peekaboo-io",
            )
        return self._runner

    # ── 허락 켜기 돕기(백엔드 길 · 모델 도구 아님 · 주력 세션 11-16 요청) ──────────
    #: 시스템 설정의 허락 화면 주소 — 정해 둔 둘만 연다.
    _SETTINGS_URLS = {
        "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "screen-recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    }

    def permission_status(self) -> dict[str, Any]:
        """허락 상태만 묻는다(화면이 2초마다 부를 갈래). `state` 는 ready · permission_needed · not_ready · unknown.

        ★ `permissions --json` 출력은 실측 기록이 아직 없다 — v4.9.8 소스 `PermissionStatusResponse`(name · isGranted …)대로 읽고,
          두 철자(isGranted · is_granted)를 다 받는다. 모양이 다르면 지어내지 않고 `unknown` 으로 둔다.
        """
        ready, why = self._ready()
        if not ready:
            return {"state": "not_ready", "why": why}
        result = self.runner().call("permissions", "status", check_permission=False)
        rows = (result.data or {}).get("permissions") if isinstance(result.data, dict) else None
        granted: dict[str, bool | None] = {"screen-recording": None, "accessibility": None}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").lower()
            value = row.get("isGranted", row.get("is_granted"))
            key = "screen-recording" if "screen" in name else "accessibility" if "accessibility" in name else ""
            if key and isinstance(value, bool):
                granted[key] = value
        if any(value is None for value in granted.values()):
            state = "unknown"
        else:
            state = "ready" if all(granted.values()) else "permission_needed"
        missing = [{"screen-recording": _SCREEN_LABEL, "accessibility": _CONTROL_LABEL}[key]
                   for key, value in granted.items() if value is False]
        out: dict[str, Any] = {"state": state, "screen_recording": granted["screen-recording"],
                               "accessibility": granted["accessibility"], "missing": missing}
        if state == "unknown":
            out["why"] = (result.error_code + " " + result.message).strip() or "permissions 출력 모양을 읽지 못했습니다."
        return out

    def permission_setup(self, step: str) -> dict[str, Any]:
        """허락 켜기 한 걸음. step: status · request(허락 창 띄우기) · open_settings(설정 화면 둘) · reveal(Finder 에 도우미 골라 띄우기)."""
        step = str(step or "").strip()
        if step == "status":
            return {"step": step, **self.permission_status()}
        ready, why = self._ready()
        if not ready:
            return {"step": step, "ok": False, "state": "not_ready", "why": why}
        if step == "request":
            asked = {}
            for kind in ("screen-recording", "accessibility"):
                result = self.runner().call("permissions", "request", kind, check_permission=False)
                asked[kind] = {"rc": result.rc, "granted": (result.data or {}).get("granted")}
            return {"step": step, "ok": True, "asked": asked}
        if step == "open_settings":
            for url in self._SETTINGS_URLS.values():
                self._open_run(["/usr/bin/open", url], capture_output=True, text=True, timeout=20, check=False)
            return {"step": step, "ok": True, "opened": list(self._SETTINGS_URLS.values()),
                    "labels": [_CONTROL_LABEL, _SCREEN_LABEL]}
        if step == "reveal":
            app = str(self.config.mac_peekaboo_app or "").strip()
            if not app:
                return {"step": step, "ok": False, "why": "app 길이 아니라 Finder 에 띄울 도우미 꾸러미가 없습니다."}
            self._open_run(["/usr/bin/open", "-R", app], capture_output=True, text=True, timeout=20, check=False)
            return {"step": step, "ok": True, "revealed": app}
        raise ValueError(f"mac_permission_step_unknown:{step} — status · request · open_settings · reveal")

    def _shot_path(self, prefix: str) -> str:
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        return str(self.preview_dir / f"mac-{prefix}-{int(time.time() * 1000)}-{secrets.token_hex(3)}.png")

    def _see(self, window_id: int, prefix: str = "see") -> _Seen:
        """그 창 **하나만** 다시 찍어 읽는다(`--window-id` · `--fresh`). 앱 이름으로는 찍지 않는다(실측 함정 ②)."""
        if window_id <= 0:
            raise ValueError("window_id_required: 창은 mac_list_open_windows 의 window_id 로만 고릅니다.")
        result = self.runner().call("see", "--window-id", str(window_id), "--fresh", "--path", self._shot_path(prefix))
        if result.error_code == "WINDOW_NOT_FOUND":
            raise LookupError(f"window_not_found: {result.message}")
        if result.error_code or result.data is None:
            raise RuntimeError(f"peekaboo_see_failed: {result.error_code or '결과 없음'} {result.message}".strip())
        data = result.data
        receipt = result.receipt or (data.get("target_receipt") if isinstance(data.get("target_receipt"), dict) else {})
        seen_id = int(receipt.get("window_id") or window_id)
        elements = [row for row in (_element(item) for item in data.get("ui_elements") or [] if isinstance(item, dict)) if row]
        focused = data.get("focused_element") if isinstance(data.get("focused_element"), dict) else {}
        return _Seen(window_id=seen_id, title=_nfc(data.get("window_title")), app=_nfc(data.get("application_name")),
                     snapshot_id=str(data.get("snapshot_id") or ""), screenshot=str(data.get("screenshot_raw") or ""),
                     elements=elements, focused=_nfc((focused or {}).get("id") or (focused or {}).get("label") or ""))

    def _hands_off(self, what: str) -> None:
        if self._wait_for_hands is not None:
            self._wait_for_hands(what)
            return
        from .user_presence import UserPresence

        if not UserPresence(self.config).wait_until_idle(quiet_sec=2.0, timeout_sec=45.0):
            raise RuntimeError(f"user_active_try_later: 사용자가 키보드 · 마우스를 쓰는 중이라 {what}을 미뤘습니다. 손이 멈춘 뒤 다시 시도하세요.")

    # ── L0 · L1 읽기 ────────────────────────────────────────────
    def list_open_windows(self, arguments: dict[str, Any]) -> dict[str, Any]:
        maximum = max(1, min(int(arguments.get("max_results") or 50), 100))
        apps = self.runner().call("app", "list")
        rows = _app_rows(apps.data or {})
        windows: list[dict[str, Any]] = []
        for app in rows:
            if len(windows) >= maximum:
                break
            target = app.get("bundle_id") or (f"PID:{app['pid']}" if app.get("pid") else "")
            if not target:
                continue
            listed = self.runner().call("window", "list", "--app", target)
            for row in _window_rows(listed.data or {}):
                if len(windows) >= maximum:
                    break
                windows.append({**row, "app": app.get("name") or row.get("app", ""), "bundle_id": app.get("bundle_id", "")})
        return {"action": "mac_list_open_windows", "count": len(windows), "windows": windows}

    def ax_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        window_id = int(arguments.get("window_id") or 0)
        maximum = max(150, min(int(arguments.get("max_elements") or 160), 300))
        seen = self._see(window_id, "snapshot")
        with self._lock:
            self._seen[window_id] = seen
        ordered = sorted(seen.elements, key=lambda row: 0 if row.get("actionable") or row.get("settable") else 1)
        return {"action": "mac_ax_snapshot", "window_id": window_id, "title": seen.title, "app": seen.app,
                "count": min(len(ordered), maximum), "truncated": len(ordered) > maximum, "elements": ordered[:maximum]}

    def copy_from_window(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """요소 값을 먼저 읽는다(화면 · 선택을 안 바꾼다). 글이 하나도 없을 때만 cmd+a · cmd+c 로 복사하고 클립보드를 되돌린다."""
        window_id = int(arguments.get("window_id") or 0)
        limit = max(1, min(int(arguments.get("limit") or 20000), 20000))
        seen = self._see(window_id, "copy")
        texts = [row["value"] for row in seen.elements
                 if row["role"] in _TEXT_ROLES and row.get("value") and not row.get("password") and row["value"] != seen.title]
        text = "\n".join(dict.fromkeys(texts))
        how = "element_values"
        if not text:
            from . import macos

            previous = macos.clipboard_read()
            if previous is None:
                # 원래 클립보드를 못 읽었으면 되돌릴 수도 없다 — 사람이 복사해 둔 것을 지우지 않게 아예 복사하지 않는다.
                raise RuntimeError("clipboard_unreadable: 클립보드를 읽지 못해 복사로 읽기를 하지 않았습니다(사람이 복사해 둔 것을 지울 수 있어서).")
            self._hands_off("창 내용 복사")
            self.runner().call("press", "cmd+a", "--window-id", str(window_id))
            self.runner().call("press", "cmd+c", "--window-id", str(window_id))
            text = _nfc(macos.clipboard_read() or "")
            macos.clipboard_write(previous)
            how = "select_all_copy"
        return {"action": "mac_copy_from_window", "window_id": window_id, "title": seen.title, "text": text[:limit],
                "char_count": len(text[:limit]), "copied": bool(text), "read_by": how}

    def focus_window(self, arguments: dict[str, Any]) -> dict[str, Any]:
        window_id = int(arguments.get("window_id") or 0)
        if window_id <= 0:
            raise ValueError("window_id_required")
        self._hands_off("창 앞으로 가져오기")
        result = self.runner().call("window", "focus", "--window-id", str(window_id))
        if result.error_code:
            raise RuntimeError(f"window_focus_failed: {result.error_code} {result.message}".strip())
        return {"action": "mac_focus_window", "window_id": window_id, "peekaboo_rc": result.rc}

    # ── L2 열기 ─────────────────────────────────────────────────
    def open_path(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = _nfc(arguments.get("path")).strip()
        app = _nfc(arguments.get("app")).strip()
        if not raw:
            raise ValueError("path_required")
        bundle = _LAUNCHABLE_APPS.get(raw.casefold())
        if bundle and not app:
            argv = ["/usr/bin/open", "-b", bundle]
            opened: dict[str, Any] = {"path": raw, "type": "app", "bundle_id": bundle}
        else:
            if self._resolve_path is None:
                raise RuntimeError("path_resolver_missing")
            target = self._resolve_path(raw)  # 허용 폴더 밖이면 여기서 거절(기존 `_resolve` 그대로)
            argv = ["/usr/bin/open"]
            if app:
                app_bundle = _LAUNCHABLE_APPS.get(app.casefold())
                if app_bundle is None:
                    raise PermissionError("app_not_allowed: 이름으로 여는 앱(텍스트 편집기 · Finder · 계산기 · 미리보기 · 메모 · 시스템 설정)만 고를 수 있습니다.")
                argv += ["-b", app_bundle]
            argv += ["--", str(target)]
            opened = {"path": str(target), "type": "directory" if Path(target).is_dir() else "file"}
        done = self._open_run(argv, capture_output=True, text=True, timeout=20, check=False)
        if int(done.returncode) != 0:
            raise RuntimeError(f"open_failed: {_nfc(done.stderr).strip()[:300]}")
        return {"action": "mac_open_path", **opened}

    # ── L1 미리보기 ─────────────────────────────────────────────
    def _save_preview(self, preview: MacPreview) -> None:
        with self._lock:
            self._previews[preview.preview_id] = preview
            for key, row in list(self._previews.items()):
                if row.used or row.expires_at < time.time() - 60:
                    self._previews.pop(key, None)

    def ax_preview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        window_id = int(arguments.get("window_id") or 0)
        ref = str(arguments.get("ref") or "").strip()
        action = str(arguments.get("action") or "").strip()
        value = _nfc(arguments.get("value"))[:4000]
        if window_id <= 0:
            raise ValueError("window_id_required: 화면 바꾸는 동작은 창 ID 로만 고릅니다(앱 이름으로는 안 함).")
        if action not in _ACTIONS:
            raise ValueError("ax_action_not_allowed")
        key_combo = normalize_key_combo(value) if action == "key" else ""
        if action in {"key", "paste", "set_value"} and not value:
            raise ValueError("value_required")
        if action not in {"key", "paste"} and not ref:
            raise ValueError("ref_required_for_this_action")
        with self._lock:
            earlier = self._seen.get(window_id)
        if earlier is None:
            raise ValueError("ax_snapshot_required: 먼저 mac_ax_snapshot 으로 이 창을 읽으세요.")
        seen = self._see(window_id, "preview")
        if not _same_name(seen.title, earlier.title):
            raise RuntimeError(f"window_changed: 읽을 때 창은 「{earlier.title}」 이었는데 지금은 「{seen.title}」 입니다 — 창을 다시 고르세요.")
        target: dict[str, Any] = {"window": True, "name": f"창 전체 「{seen.title}」"}
        if ref:
            known = earlier.by_id(ref)
            if known is None:
                raise ValueError("ax_ref_not_found_refresh_snapshot")
            now = seen.find(known)
            if now is None:
                raise RuntimeError("ax_target_stale_refresh_snapshot: 그 요소가 지금 창에 없습니다 — mac_ax_snapshot 을 다시 하세요.")
            if now.get("password"):
                raise PermissionError("password_control_blocked")
            target = dict(now)
        preview = MacPreview(
            preview_id=secrets.token_urlsafe(18), action=action, window_id=window_id, window_title=seen.title, app=seen.app,
            target=target, value=key_combo or value, screenshot_path=seen.screenshot, before=seen.signature(),
            created_at=time.time(), expires_at=time.time() + 300,
        )
        self._save_preview(preview)
        out = {"action": "mac_ax_preview", "preview_id": preview.preview_id, "expires_at": preview.expires_at,
               "window_id": window_id, "window_title": seen.title, "app": seen.app, "target": target,
               "planned_action": action, "value_preview": value[:120] if action in {"set_value", "paste"} else "",
               "screenshot_path": seen.screenshot, "requires_approval": True}
        if action == "key":
            out["key_combo"] = key_combo
            out["destructive"] = key_combo in _DESTRUCTIVE_KEYS
        return out

    # ── L2 실행 ─────────────────────────────────────────────────
    def _command(self, preview: MacPreview, snapshot_id: str, element_ref: str) -> list[str]:
        where = ["--window-id", str(preview.window_id)]
        snap = ["--snapshot", snapshot_id] if snapshot_id else []
        on = ["--on", element_ref] if element_ref else []
        if preview.action == "key":
            return ["press", preview.value, *where, *snap]
        if preview.action == "paste":
            if element_ref:  # 붙여넣을 칸을 먼저 눌러 초점을 둔다 — 같은 승인 안의 한 동작으로 본다
                self.runner().call("click", *on, *where, *snap)
            return ["paste", "--text", preview.value, *where]
        if preview.action == "set_value":
            return ["set-value", "--value", preview.value, *on, *where, *snap]
        if preview.action == "invoke":
            return ["action", "AXPress", *on, *where, *snap]
        return ["click", *on, *where, *snap]  # click · toggle · select · focus

    def execute_preview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        preview_id = str(arguments.get("preview_id") or "")
        with self._lock:
            preview = self._previews.get(preview_id)
            if preview is None:
                raise ValueError("preview_not_found")
            if preview.used:
                raise RuntimeError("preview_already_used")
            if preview.expires_at < time.time():
                raise RuntimeError("preview_expired")
            preview.used = True  # 한 번만 — 거절로 끝나도 같은 미리보기로 다시 보내지 않는다(새로 미리보기)
        # ① 창 고정 — 그 창을 다시 찍어 창 이름이 미리보기 때와 같을 때만 보낸다.
        try:
            now = self._see(preview.window_id, "before")
        except LookupError as exc:
            return self._refused(preview, "window_changed", f"창이 없어졌습니다: {exc}")
        if now.window_id != preview.window_id or not _same_name(now.title, preview.window_title):
            return self._refused(preview, "window_changed",
                                 f"미리보기 때 창은 「{preview.window_title}」 이었는데 지금 그 자리에는 「{now.title}」 이 있습니다 — 아무것도 보내지 않았습니다.")
        element_ref = ""
        if not preview.target.get("window"):
            hit = now.find(preview.target)
            if hit is None:
                return self._refused(preview, "target_changed", "미리보기 때의 요소가 지금 창에 없습니다 — 아무것도 보내지 않았습니다.")
            element_ref = hit["ref"]
        self._hands_off({"key": "키 입력", "paste": "붙여넣기", "set_value": "값 넣기"}.get(preview.action, "누르기"))
        # ② 보낸다 — rc 는 참고만.
        sent = self.runner().call(*self._command(preview, now.snapshot_id, element_ref))
        if self.settle_sec:
            time.sleep(self.settle_sec)
        # ③ 같은 창을 다시 읽어 판정한다.
        try:
            after = self._see(preview.window_id, "after")
        except LookupError:
            verdict, why, after = "window_changed", "실행 뒤 그 창이 없어졌습니다(닫혔거나 바뀜).", None
        else:
            verdict, why = _judge(preview, now, after)
        out = {"action": "mac_execute_preview", "preview_id": preview.preview_id, "executed_action": preview.action,
               "window_id": preview.window_id, "target": preview.target, "executed_at": time.time(),
               "verdict": verdict, "verified": verdict == "verified", "why": why,
               "peekaboo_rc": sent.rc, "peekaboo_said": _first_line(sent)}
        if after is not None:
            out["window_title_after"] = after.title
        return out

    @staticmethod
    def _refused(preview: MacPreview, verdict: str, why: str) -> dict[str, Any]:
        return {"action": "mac_execute_preview", "preview_id": preview.preview_id, "executed_action": "", "sent": False,
                "window_id": preview.window_id, "verdict": verdict, "verified": False, "why": why}


def _first_line(result: PeekabooResult) -> str:
    """Peekaboo 가 한 말 첫 줄 — 참고용(판정에 쓰지 않는다)."""
    lines = [line for line in result.text.splitlines() if line.strip()]
    return (result.error_code or (lines[0].strip() if lines else ""))[:200]


def _judge(preview: MacPreview, before: _Seen, after: _Seen) -> tuple[str, str]:
    """실행 뒤 다시 읽은 창으로 판정한다. 기대한 변화가 보일 때만 verified."""
    if after.window_id != preview.window_id:
        return "window_changed", f"다시 읽으니 다른 창(id={after.window_id})이 잡혔습니다."
    if preview.action in {"set_value", "paste"}:
        wanted = _nfc(preview.value).strip()
        if not preview.target.get("window"):
            row = after.find(preview.target)
            got = _nfc((row or {}).get("value")).strip()
            if row is not None and (got == wanted or (preview.action == "paste" and wanted in got)):
                return "verified", "다시 읽은 칸의 값에 넣은 글이 있습니다."
            return "not_verified", "다시 읽은 칸의 값에 넣은 글이 보이지 않습니다."
        if any(wanted and wanted in _nfc(row.get("value")) for row in after.elements):
            return "verified", "다시 읽은 창에 붙여넣은 글이 있습니다."
        return "not_verified", "다시 읽은 창에 붙여넣은 글이 보이지 않습니다."
    old, new = before.signature(), after.signature()
    if preview.action == "toggle" and not preview.target.get("window"):
        ref = (after.find(preview.target) or {}).get("ref", "")
        was = (before.find(preview.target) or {}).get("value", "")
        if ref and new["values"].get(ref, "") != was:
            return "verified", "다시 읽은 요소의 값이 바뀌었습니다."
        return "not_verified", "다시 읽은 요소의 값이 그대로입니다."
    changed = [key for key in ("title", "focused", "values", "names") if old[key] != new[key]]
    if changed:
        return "verified", "다시 읽은 창이 바뀌었습니다(" + " · ".join(changed) + ")."
    return "not_verified", "다시 읽은 창에 바뀐 것이 보이지 않습니다 — 동작이 안 먹었을 수 있습니다."


def _app_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """`app list --json` 의 앱들. ★ 실측 기록이 없는 모양이라 두 철자(snake · camel)를 다 받는다(설계 §8-3)."""
    raw = data.get("applications") or data.get("apps") or []
    out = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict) or row.get("is_hidden") or row.get("isHidden"):
            continue
        count = row.get("window_count", row.get("windowCount"))
        if count == 0:
            continue
        out.append({"name": _nfc(row.get("name") or row.get("app_name")),
                    "bundle_id": str(row.get("bundle_id") or row.get("bundleIdentifier") or ""),
                    "pid": int(row.get("pid") or row.get("processIdentifier") or 0)})
    return out


def _window_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """`window list --app X --json` 의 창들(실측 `out3/wins.json` 모양). 제목 없는 · 픽셀만 되는 창은 뺀다."""
    raw = data.get("windows") or []
    info = data.get("target_application_info") or {}
    out = []
    for row in raw if isinstance(raw, list) else []:
        title = _nfc(row.get("window_title") or row.get("title"))
        if not isinstance(row, dict) or not title.strip() or row.get("observation_capability") == "pixels_only":
            continue
        out.append({"window_id": int(row.get("window_id") or 0), "title": title[:500],
                    "app": _nfc(info.get("app_name")), "pid": int(info.get("pid") or 0),
                    "frontmost": bool(row.get("is_frontmost")), "on_screen": bool(row.get("is_on_screen", True))})
    return out
