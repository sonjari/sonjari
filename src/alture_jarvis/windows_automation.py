from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec


VisualPlanner = Callable[[Path, dict[str, Any], str], dict[str, Any]]


# ── 키 조합 ────────────────────────────────────────────────────────────────
#
# 좌표를 쓰지 않는 조작 수단. 구형 프로그램에서는 이게 유일한 손잡이인 경우가 많다
# (메뉴가 UIA 트리에 안 잡히는데 Ctrl+S 는 먹는다).
#
# **통과가 아니라 허용 목록이다.** pywinauto 의 `send_keys` 는 문자열을 그대로 키로
# 바꿔 주므로, 모델이 만든 문자열을 그대로 넘기면 아무 글자나 아무 창에나 칠 수 있는
# 통로가 된다. 그래서 "수식키+키" 꼴로만 해석하고, 해석 못 하면 거절한다.
_KEY_MODIFIERS = {"ctrl": "^", "control": "^", "alt": "%", "shift": "+"}
_KEY_NAMES = {
    "enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}",
    "escape": "{ESC}", "space": "{SPACE}", "backspace": "{BACKSPACE}",
    "delete": "{DELETE}", "del": "{DELETE}", "insert": "{INSERT}",
    "home": "{HOME}", "end": "{END}", "pageup": "{PGUP}", "pagedown": "{PGDN}",
    "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
    **{f"f{index}": f"{{F{index}}}" for index in range(1, 13)},
}
# 되돌리기 어려운 조합. 막지는 않는다 — 어차피 화면 승인을 거친다. 다만 승인 카드에
# 그렇다고 적혀야 사람이 알아보고 누른다.
_DESTRUCTIVE_KEYS = {"alt+f4", "ctrl+w", "ctrl+q", "ctrl+shift+w", "delete", "ctrl+delete"}


def translate_key_combo(combo: str) -> tuple[str, str]:
    """'ctrl+s' -> ('^s', 'ctrl+s'). 해석 못 하는 것은 거절한다."""
    raw = " ".join(str(combo or "").split()).lower()
    if not raw:
        raise ValueError("key_required")
    parts = [part.strip() for part in raw.split("+") if part.strip()]
    if not parts:
        raise ValueError("key_required")
    *modifier_names, key = parts
    prefix = ""
    for name in modifier_names:
        if name not in _KEY_MODIFIERS:
            raise ValueError(f"key_modifier_not_allowed:{name}")
        prefix += _KEY_MODIFIERS[name]
    if key in _KEY_NAMES:
        body = _KEY_NAMES[key]
    elif len(key) == 1 and key.isalnum():
        body = key
    else:
        # 여러 글자를 한 번에 치는 것은 여기서 할 일이 아니다(붙여넣기가 있다).
        raise ValueError(f"key_not_allowed:{key}")
    return prefix + body, "+".join(parts)


def _clipboard_get(limit: int = 20000) -> str:
    """클립보드의 글. 없으면 빈 문자열."""
    if os.name != "nt":
        raise RuntimeError("windows_only")
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        try:
            value = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        except TypeError:
            return ""
        except Exception:
            return ""
    finally:
        win32clipboard.CloseClipboard()
    return str(value or "")[:limit]


def _clipboard_set(text: str) -> None:
    if os.name != "nt":
        raise RuntimeError("windows_only")
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(str(text), win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


@dataclass(slots=True)
class ActionPreview:
    preview_id: str
    source: str
    action: str
    window_id: int
    target: dict[str, Any]
    value: str
    screenshot_path: str
    created_at: float
    expires_at: float
    used: bool = False


class WindowsAutomationTools:
    """Preview-first Windows UIA and visual-coordinate control.

    Discovery and preview are read-only. Every state-changing action is stored
    as a short-lived preview and executed through the L2 approval gateway.
    """

    def __init__(
        self,
        config: JarvisConfig,
        *,
        visual_planner: VisualPlanner | None = None,
    ) -> None:
        self.config = config
        self.visual_planner = visual_planner
        from .user_presence import UserPresence

        self.presence = UserPresence(config)
        self.preview_dir = config.output_dir / "action-previews"
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._refs: dict[tuple[int, str], dict[str, Any]] = {}
        self._previews: dict[str, ActionPreview] = {}
        # (잰 시각, 불러와졌나, 실패 문장) — `status()` 는 `/health` 마다 불린다. 실패한 불러오기를 그때마다
        # 다시 하면 그 값이 매번 쌓인다(아래 `_prepare_com_cache` 의 2026-10-14 사고).
        self._dependency: tuple[float, bool, str] | None = None
        self._definitions = self._build_definitions()

    @staticmethod
    def _function(
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                },
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "windows_uia_snapshot",
                "열린 Windows 앱의 UI Automation 컨트롤 트리를 읽고 조작 가능한 ref를 만든다.",
                {
                    "window_id": {"type": "integer"},
                    "max_elements": {"type": "integer", "minimum": 1, "maximum": 300},
                },
                ["window_id"],
            ),
            self._function(
                "windows_uia_preview",
                "UIA ref에 실행할 클릭·입력·토글 동작을 실제 실행하지 않고 미리보기로 만든다.",
                {
                    "window_id": {"type": "integer"},
                    "ref": {"type": "string"},
                    "action": {"type": "string", "enum": ["invoke", "click", "set_value", "toggle", "select", "focus", "key", "paste"]},
                    "value": {
                        "type": "string",
                        "description": (
                            "set_value=입력값, key='ctrl+s' 같은 키 조합, paste=붙여넣을 글. "
                            "key·paste 는 창 전체에 보내므로 ref 를 생략해도 된다."
                        ),
                    },
                },
                ["window_id", "action"],
            ),
            self._function(
                "clipboard_write",
                "만든 글을 클립보드에 올린다. 사람이 카톡·한글·입력칸에 **바로 붙여넣을** 수 있게 할 때 쓴다. "
                "자리가 하나뿐이라 다시 부르면 앞 글이 사라진다 — 여러 문단이거나 다음에도 다시 볼 글(면접 답변 등)은 "
                "이것만으로 끝내지 말고 local_write_document 로 파일도 만들어라.",
                {"text": {"type": "string"}},
                ["text"],
            ),
            self._function(
                "clipboard_read",
                "지금 클립보드에 있는 글을 읽는다. 사용자가 방금 복사한 것이 무엇인지 확인할 때만 쓴다.",
                {"limit": {"type": "integer", "minimum": 1, "maximum": 20000}},
            ),
            self._function(
                "windows_copy_from_window",
                "창의 내용을 전체 선택·복사해서 글로 읽어온다(Ctrl+A, Ctrl+C). 화면을 바꾸지 않고, "
                "원래 클립보드는 그대로 되돌려 놓는다. 표나 목록을 눈으로 읽는 것보다 정확하다.",
                {
                    "window_id": {"type": "integer"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20000},
                },
                ["window_id"],
            ),
            self._function(
                "windows_visual_preview",
                "현재 앱 화면을 캡처해 Gemma 비전으로 목표 좌표를 찾고, 클릭 실행 전 미리보기를 만든다. UIA로 찾을 수 없는 캔버스에만 사용한다.",
                {
                    "window_id": {"type": "integer"},
                    "instruction": {"type": "string"},
                    "action": {"type": "string", "enum": ["click", "double_click"]},
                },
                ["window_id", "instruction"],
            ),
            self._function(
                "windows_execute_preview",
                "앞서 만든 UIA 또는 비전 좌표 미리보기를 실행한다. 화면 승인이 필수다.",
                {
                    "preview_id": {"type": "string"},
                    "target_summary": {
                        "type": "string",
                        "description": "미리보기 결과의 target/동작을 사용자가 승인 화면에서 알아볼 수 있게 그대로 요약",
                    },
                    "screenshot_path": {
                        "type": "string",
                        "description": "미리보기 결과에 포함된 screenshot_path",
                    },
                },
                ["preview_id"],
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "windows_uia_snapshot": self.uia_snapshot,
            "windows_uia_preview": self.uia_preview,
            "windows_visual_preview": self.visual_preview,
            "windows_execute_preview": self.execute_preview,
            "clipboard_read": self.clipboard_read,
            "clipboard_write": self.clipboard_write,
            "windows_copy_from_window": self.copy_from_window,
        }
        risks = {
            "windows_uia_snapshot": RiskLevel.L0,
            "windows_uia_preview": RiskLevel.L1,
            "windows_visual_preview": RiskLevel.L1,
            "windows_execute_preview": RiskLevel.L2,
            # 읽기다. 다만 사용자가 방금 복사한 것이 비밀번호일 수도 있어서, 아무 때나
            # 집어보라고 권하지 않는다(도구 설명이 그 역할을 한다).
            "clipboard_read": RiskLevel.L1,
            "clipboard_write": RiskLevel.L1,
            # Ctrl+A·Ctrl+C 만 보낸다 — 선택은 바뀌어도 내용은 바뀌지 않고,
            # 원래 클립보드도 되돌려 놓는다.
            "windows_copy_from_window": RiskLevel.L1,
        }
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=risks[name],
                    handler=handlers[name],
                    enabled=self.config.windows_control_enabled,
                )
            )

    def status(self) -> dict[str, Any]:
        dependency, error = self._dependency_ready()
        with self._lock:
            active = sum(1 for preview in self._previews.values() if preview.expires_at >= time.time() and not preview.used)
        out: dict[str, Any] = {
            "enabled": self.config.windows_control_enabled and os.name == "nt",
            "dependency": dependency,
            "preview_first": True,
            "active_previews": active,
        }
        if error:
            out["dependency_error"] = error
        return out

    _DEPENDENCY_RETRY_SEC = 600.0

    def _dependency_ready(self) -> tuple[bool, str]:
        """pywinauto 를 불러올 수 있는가. 되면 기억하고, 안 되면 10분 동안 다시 시도하지 않는다."""
        with self._lock:
            known = self._dependency
            if known is not None and (known[1] or time.time() - known[0] < self._DEPENDENCY_RETRY_SEC):
                return known[1], known[2]
            try:
                self._prepare_com_cache()
                import pywinauto  # noqa: F401

                self._dependency = (time.time(), True, "")
            except Exception as exc:
                self._dependency = (time.time(), False, f"{type(exc).__name__}: {exc}"[:300])
            return self._dependency[1], self._dependency[2]

    def _prepare_com_cache(self) -> None:
        """MSIX 설치 폴더는 읽기 전용이다. UIA 생성물은 앱 데이터에 두고, **그 폴더를 먼저** 찾게 한다.

        ★ 2026-10-14 사고(부산 노트북 · 백엔드가 5분에 100MB 씩 늘었다): 꾸러미에는 굽는 PC 에서 만든
        `comtypes/gen/_944DE083_...py`(UIAutomation 정의 9,224줄)가 들어 있다. 그 파일의 **마지막 줄**이
        `_check_version` — 이 PC 의 `UIAutomationCore.dll` 시각이 만든 PC 와 다르면 ImportError 를 던진다.
        굽는 PC 밖의 거의 모든 PC 가 그렇다. 그러면
          1) 9,224줄이 다 실행된 뒤 마지막 줄에서 실패하고, 만들어진 인터페이스 클래스는
             `ctypes._pointer_type_cache` 에 영영 남는다.
          2) comtypes 가 이 PC 용으로 새로 만들어 캐시 폴더에 쓰지만, 캐시 폴더가 `__path__` **뒤**에
             있어서 다시 불러올 때 꾸러미 쪽이 또 먼저 잡혀 또 실패한다.
          3) `status()` 가 `/health` 마다 이것을 되풀이했다 — 세 번에 물건 7만 7천 개.
        그래서 캐시 폴더를 맨 앞에 둔다. 처음 한 번은 꾸러미 쪽이 실패하고(한 번 새는 값), 이 PC 용이
        캐시에 써진 뒤로는 그것이 먼저 잡힌다. 다음 기동부터는 처음부터 캐시 것이 잡힌다.
        """
        if os.name != "nt":
            return
        import comtypes.client
        import comtypes.gen

        cache = self.config.data_dir / "comtypes-cache"
        cache.mkdir(parents=True, exist_ok=True)
        with self._lock:
            comtypes.client.gen_dir = str(cache)
            paths = comtypes.gen.__path__
            if str(cache) in paths and paths[0] == str(cache):
                return
            while str(cache) in paths:
                paths.remove(str(cache))
            paths.insert(0, str(cache))

    def _desktop(self) -> Any:
        if os.name != "nt":
            raise RuntimeError("windows_only")
        try:
            self._prepare_com_cache()
            from pywinauto import Desktop
        except ImportError as exc:
            raise RuntimeError("pywinauto_missing") from exc
        return Desktop(backend="uia")

    def _window(self, window_id: int) -> Any:
        if window_id <= 0:
            raise ValueError("window_id_required")
        window = self._desktop().window(handle=window_id)
        if not window.exists(timeout=1):
            raise ValueError("window_not_found")
        return window

    @staticmethod
    def _control_metadata(control: Any) -> dict[str, Any]:
        info = control.element_info
        rectangle = info.rectangle
        try:
            properties = control.get_properties()
        except Exception:
            properties = {}
        return {
            "name": str(info.name or "")[:300],
            "control_type": str(info.control_type or ""),
            "automation_id": str(info.automation_id or "")[:200],
            "class_name": str(info.class_name or "")[:200],
            "rectangle": {
                "left": int(rectangle.left), "top": int(rectangle.top),
                "right": int(rectangle.right), "bottom": int(rectangle.bottom),
            },
            "enabled": bool(properties.get("is_enabled", True)),
            "visible": bool(properties.get("is_visible", True)),
            "password": bool(properties.get("is_password", False)),
        }

    def uia_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        window_id = int(arguments.get("window_id") or 0)
        maximum = max(1, min(int(arguments.get("max_elements") or 160), 300))
        window = self._window(window_id)
        controls = [window, *window.descendants()]
        elements: list[dict[str, Any]] = []
        with self._lock:
            for key in [key for key in self._refs if key[0] == window_id]:
                self._refs.pop(key, None)
            for control in controls:
                if len(elements) >= maximum:
                    break
                try:
                    metadata = self._control_metadata(control)
                except Exception:
                    continue
                if not metadata["name"] and not metadata["automation_id"]:
                    continue
                ref = f"u{len(elements) + 1}"
                metadata["ref"] = ref
                self._refs[(window_id, ref)] = metadata
                elements.append(metadata)
        return {
            "action": "windows_uia_snapshot",
            "window_id": window_id,
            "title": str(window.window_text() or "")[:500],
            "count": len(elements),
            "truncated": len(controls) > len(elements),
            "elements": elements,
        }

    def _find_control(self, window_id: int, target: dict[str, Any]) -> Any:
        window = self._window(window_id)
        candidates = [window, *window.descendants()]
        desired_rect = target.get("rectangle") or {}

        def score(control: Any) -> tuple[int, int]:
            try:
                current = self._control_metadata(control)
            except Exception:
                return (-1, -999999)
            exact = int(bool(target.get("automation_id")) and current["automation_id"] == target.get("automation_id")) * 8
            exact += int(current["control_type"] == target.get("control_type")) * 4
            exact += int(bool(target.get("name")) and current["name"] == target.get("name")) * 3
            rect = current["rectangle"]
            distance = sum(abs(int(rect.get(key, 0)) - int(desired_rect.get(key, 0))) for key in ("left", "top", "right", "bottom"))
            return exact, -distance

        ranked = sorted(candidates, key=score, reverse=True)
        if not ranked or score(ranked[0])[0] < 4:
            raise RuntimeError("uia_target_stale_refresh_snapshot")
        return ranked[0]

    def _capture_window(self, window_id: int, prefix: str) -> tuple[Path, dict[str, int]]:
        window = self._window(window_id)
        rect = window.rectangle()
        bounds = {
            "left": int(rect.left), "top": int(rect.top),
            "right": int(rect.right), "bottom": int(rect.bottom),
        }
        if bounds["right"] <= bounds["left"] or bounds["bottom"] <= bounds["top"]:
            raise RuntimeError("window_not_visible")
        from PIL import ImageGrab

        image = ImageGrab.grab(
            bbox=(bounds["left"], bounds["top"], bounds["right"], bounds["bottom"]),
            all_screens=True,
        )
        path = self.preview_dir / f"{prefix}-{int(time.time() * 1000)}.png"
        image.save(path, format="PNG", optimize=True)
        return path, bounds

    def _save_preview(
        self,
        *,
        source: str,
        action: str,
        window_id: int,
        target: dict[str, Any],
        value: str = "",
        screenshot_path: str = "",
    ) -> ActionPreview:
        preview = ActionPreview(
            preview_id=secrets.token_urlsafe(18),
            source=source,
            action=action,
            window_id=window_id,
            target=target,
            value=value,
            screenshot_path=screenshot_path,
            created_at=time.time(),
            expires_at=time.time() + 300,
        )
        with self._lock:
            self._previews[preview.preview_id] = preview
            for preview_id, row in list(self._previews.items()):
                if row.expires_at < time.time() - 60 or row.used:
                    self._previews.pop(preview_id, None)
        return preview

    def clipboard_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = max(1, min(int(arguments.get("limit") or 20000), 20000))
        text = _clipboard_get(limit)
        return {
            "action": "clipboard_read",
            "text": text,
            "char_count": len(text),
            "empty": not text,
        }

    def clipboard_write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """만든 글을 클립보드에 올린다 — 사람이 아무 데나 붙여넣게.

        ★ 읽기만 있고 쓰기가 없었다 (2026-09-01). 자비스가 정리한 표나 문장을
        사용자가 카톡·한글·사이트 입력칸에 옮기려면 화면에서 긁어야 했다. 붙여넣기는
        자비스가 못 가는 곳(카톡 같은)까지 사람 손으로 닿게 해 주는 **가장 싼 다리**다.

        올린 뒤 **다시 읽어서 확인한다** — 클립보드는 다른 프로그램이 언제든 덮어쓴다.
        올렸다는 주장만 하고 안 올라간 경우가 제일 나쁘다.
        """
        text = str(arguments.get("text") or "")
        if not text:
            raise ValueError("text_required")
        if len(text) > 200_000:
            raise ValueError(f"text_too_large:{len(text)}")
        _clipboard_set(text)
        echo = _clipboard_get(len(text) + 16)
        return {
            "action": "clipboard_write",
            "char_count": len(text),
            "verified": echo.strip() == text.strip(),
            "preview": text[:200],
        }

    def copy_from_window(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """창의 내용을 글로 읽어온다 — 눈으로 읽는 대신 복사해서.

        OCR 도 비전도 오독하지만 복사는 원문 그대로다. 표·목록처럼 화면에서 옮겨
        적어야 하는 것에서 차이가 크다.

        원래 클립보드는 되돌려 놓는다. 사용자가 뭔가 복사해 둔 채로 자비스에게
        일을 시켰다가 그게 조용히 사라지면, 잃어버린 줄도 모른다.
        """
        window_id = int(arguments.get("window_id") or 0)
        limit = max(1, min(int(arguments.get("limit") or 20000), 20000))
        window = self._window(window_id)
        previous = ""
        try:
            previous = _clipboard_get()
        except Exception:
            previous = ""
        self._prepare_com_cache()
        from pywinauto import keyboard

        self._wait_for_hands_off("창 내용 복사")
        window.set_focus()
        time.sleep(0.15)
        _clipboard_set("")  # 복사가 실패했는데 이전 내용을 결과로 착각하지 않도록
        keyboard.send_keys("^a")
        time.sleep(0.1)
        keyboard.send_keys("^c")
        time.sleep(0.25)
        text = _clipboard_get(limit)
        try:
            _clipboard_set(previous)
        except Exception:
            pass
        return {
            "action": "windows_copy_from_window",
            "window_id": window_id,
            "text": text,
            "char_count": len(text),
            "copied": bool(text),
            "clipboard_restored": True,
            **({} if text else {"hint": "이 창은 전체 선택·복사를 지원하지 않는 것 같습니다. UIA 스냅샷을 보세요."}),
        }

    def uia_preview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        window_id = int(arguments.get("window_id") or 0)
        ref = str(arguments.get("ref") or "")
        action = str(arguments.get("action") or "invoke")
        value = str(arguments.get("value") or "")[:4000]
        if action not in {"invoke", "click", "set_value", "toggle", "select", "focus", "key", "paste"}:
            raise ValueError("uia_action_not_allowed")
        # key·paste 는 창 전체에 보내는 동작이라 ref 가 없어도 된다. 구형 앱은 메뉴가
        # UIA 트리에 아예 안 잡히면서 Ctrl+S 는 먹는 경우가 흔하다 — ref 를 강제하면
        # 바로 그 상황에서 못 쓰게 된다.
        key_combo = ""
        if action in {"key", "paste"}:
            if not value:
                raise ValueError("value_required")
            target: dict[str, Any] = {"window": True, "name": f"창 전체(id={window_id})"}
            if ref:
                with self._lock:
                    known = dict(self._refs.get((window_id, ref)) or {})
                if not known:
                    raise ValueError("uia_ref_not_found_refresh_snapshot")
                if known.get("password"):
                    raise PermissionError("password_control_blocked")
                target = known
            if action == "key":
                _, key_combo = translate_key_combo(value)  # 해석 못 하면 여기서 거절
        else:
            # ref 를 안 준 것과 준 ref 가 낡은 것은 고치는 방법이 다르다. 한 문구로
            # 뭉치면 "스냅샷을 다시 뜨라"는 엉뚱한 안내를 받고 그대로 반복한다.
            if not ref:
                raise ValueError("ref_required_for_this_action")
            with self._lock:
                target = dict(self._refs.get((window_id, ref)) or {})
            if not target:
                raise ValueError("uia_ref_not_found_refresh_snapshot")
            if target.get("password"):
                raise PermissionError("password_control_blocked")
            if action == "set_value" and not value:
                raise ValueError("value_required")
        screenshot, _ = self._capture_window(window_id, "uia")
        preview = self._save_preview(
            source="uia", action=action, window_id=window_id,
            target=target, value=value, screenshot_path=str(screenshot),
        )
        result = {
            "action": "windows_uia_preview",
            "preview_id": preview.preview_id,
            "expires_at": preview.expires_at,
            "target": target,
            "planned_action": action,
            "value_preview": value[:120] if action in {"set_value", "paste"} else "",
            "screenshot_path": str(screenshot),
            "requires_approval": True,
        }
        if action == "key":
            result["key_combo"] = key_combo
            # 승인 화면에서 사람이 알아볼 수 있게. 막지는 않는다 — 어차피 사람이 누른다.
            result["destructive"] = key_combo in _DESTRUCTIVE_KEYS
        return result

    def visual_preview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.visual_planner is None:
            raise RuntimeError("visual_planner_unavailable")
        window_id = int(arguments.get("window_id") or 0)
        instruction = str(arguments.get("instruction") or "").strip()[:800]
        action = str(arguments.get("action") or "click")
        if not instruction:
            raise ValueError("instruction_required")
        if action not in {"click", "double_click"}:
            raise ValueError("visual_action_not_allowed")
        screenshot, bounds = self._capture_window(window_id, "visual")
        plan = self.visual_planner(screenshot, bounds, instruction)
        relative_x = int(plan.get("x") or -1)
        relative_y = int(plan.get("y") or -1)
        confidence = float(plan.get("confidence") or 0)
        width = bounds["right"] - bounds["left"]
        height = bounds["bottom"] - bounds["top"]
        if not (0 <= relative_x < width and 0 <= relative_y < height):
            raise RuntimeError("visual_coordinate_out_of_bounds")
        if confidence < 0.55:
            raise RuntimeError("visual_coordinate_low_confidence")
        target = {
            "x": bounds["left"] + relative_x,
            "y": bounds["top"] + relative_y,
            "relative_x": relative_x,
            "relative_y": relative_y,
            "confidence": round(confidence, 3),
            "description": str(plan.get("description") or instruction)[:500],
            "bounds": bounds,
        }
        preview = self._save_preview(
            source="visual", action=action, window_id=window_id,
            target=target, screenshot_path=str(screenshot),
        )
        return {
            "action": "windows_visual_preview",
            "preview_id": preview.preview_id,
            "expires_at": preview.expires_at,
            "target": target,
            "planned_action": action,
            "screenshot_path": str(screenshot),
            "requires_approval": True,
        }

    def _wait_for_hands_off(self, what: str) -> None:
        """사람 손이 키보드·마우스에서 멈출 때까지 기다린다(인수인계 H2-A). 끝내 안 멈추면 미룬다."""
        if self.presence.wait_until_idle(quiet_sec=2.0, timeout_sec=45.0):
            return
        raise RuntimeError(
            f"user_active_try_later: 사용자가 키보드·마우스를 쓰는 중이라 {what}을 미뤘습니다. "
            "사람이 손을 멈춘 뒤 다시 시도하거나, 잠깐 PC 를 쓰지 말아 달라고 알리세요."
        )

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

        if preview.action in {"key", "paste"}:
            # 창(또는 그 안의 컨트롤)에 포커스를 준 뒤 보낸다. 좌표는 쓰지 않는다.
            self._prepare_com_cache()
            from pywinauto import keyboard

            # 키를 보내려면 포커스를 가져와야 한다. 사람이 치는 중이면 글자가 섞여 엉뚱한 창에 들어간다 — 기다린다.
            self._wait_for_hands_off("키 입력" if preview.action == "key" else "붙여넣기")
            if preview.target.get("window"):
                self._window(preview.window_id).set_focus()
            else:
                self._find_control(preview.window_id, preview.target).set_focus()
            time.sleep(0.15)
            if preview.action == "key":
                keys, combo = translate_key_combo(preview.value)
                keyboard.send_keys(keys)
                sent = combo
            else:
                # 붙여넣기: 한 글자씩 두드리지 않는다. 2026-08-05 에 네이버 편집기에서
                # 908자를 두드리다 자동 서식 변환과 부딪혀 문단이 뒤섞였다 —
                # 붙여넣기는 그럴 틈이 아예 없다. 클립보드는 되돌려 놓는다.
                previous = ""
                try:
                    previous = _clipboard_get()
                except Exception:
                    previous = ""
                _clipboard_set(preview.value)
                keyboard.send_keys("^v")
                time.sleep(0.2)
                try:
                    _clipboard_set(previous)
                except Exception:
                    pass
                sent = f"{len(preview.value)}자 붙여넣기"
            with self._lock:
                preview.used = True
            return {
                "action": "windows_execute_preview",
                "preview_id": preview_id,
                "source": preview.source,
                "executed_action": preview.action,
                "sent": sent,
                "target": preview.target,
                "executed_at": time.time(),
            }

        if preview.source == "uia":
            control = self._find_control(preview.window_id, preview.target)
            if preview.action == "focus":
                control.set_focus()
            elif preview.action == "set_value":
                if preview.target.get("password"):
                    raise PermissionError("password_control_blocked")
                control.set_edit_text(preview.value)
            elif preview.action == "toggle":
                control.toggle()
            elif preview.action == "select":
                control.select()
            elif preview.action == "invoke":
                try:
                    control.invoke()
                except Exception:
                    control.click_input()
            else:
                control.click_input()
        else:
            self._prepare_com_cache()
            from pywinauto import mouse

            coords = (int(preview.target["x"]), int(preview.target["y"]))
            if preview.action == "double_click":
                mouse.double_click(coords=coords)
            else:
                mouse.click(coords=coords)
        with self._lock:
            preview.used = True
        return {
            "action": "windows_execute_preview",
            "preview_id": preview_id,
            "source": preview.source,
            "executed_action": preview.action,
            "target": preview.target,
            "executed_at": time.time(),
        }
