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


# ── 화면 자동화 눈 · 손 (2026-10-17 첫 측정) ─────────────────────────────────
#
# 메모장 판: 저장 창에서 「파일 이름」 칸 대신 다른 칸에 값을 넣고 저장해, 파일이 메모장이 미리 채운 이름(첫 줄)으로 저장됐다.
# 손자리는 그걸 몰랐다 — 창 구조 읽기가 화면 순서로 160개만 담아 긴 폴더 나무 · 파일 목록 뒤의 입력 칸이 밀렸고, 칸의 지금 값이
# 안 보였고, 값을 넣은 뒤 다시 읽어 보지 않았다. 그래서 (1) 조작할 수 있는 요소를 먼저 담고 (2) 입력 칸의 지금 값을 같이 보이고
# (3) 값을 넣은 뒤 다시 읽어 맞는지 · 동작 뒤 창 제목을 결과에 적는다.

#: 조작할 수 있는 요소 — 창 구조를 읽을 때 **먼저** 담는다(같은 묶음 안에서는 화면 순서 그대로).
_INTERACTIVE_TYPES = frozenset({
    "Edit", "ComboBox", "Button", "CheckBox", "RadioButton", "MenuItem", "TabItem", "Hyperlink",
    "SplitButton", "Document", "Spinner", "Slider",
})
#: 지금 값을 같이 보여 줄 요소.
_VALUE_TYPES = frozenset({"Edit", "ComboBox", "Document", "Spinner"})
#: 누르면 프로그램을 **강제로 끄는** 단추 — 손자리는 누르지 않는다(되돌릴 수 없다 · 사람이 직접). 권한 무시 모드에서도.
_END_TASK_NAMES = frozenset({"작업 끝내기", "프로세스 트리 끝내기", "end task", "end process tree"})


def _process_elevated(pid: int) -> bool | None:
    """그 프로세스가 관리자 권한으로 떠 있나. 못 보면 None."""
    if os.name != "nt" or pid <= 0:
        return None
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32, advapi32 = ctypes.windll.kernel32, ctypes.windll.advapi32
    handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            return None
        try:
            elevated = wintypes.DWORD()
            size = wintypes.DWORD()
            if not advapi32.GetTokenInformation(token, 20, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(size)):
                return None
            return bool(elevated.value)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(handle)


#: 작업 관리자 「프로세스」 탭에 안 나오는 것 — 메모리 순위에서 뺀다. (Secure System 은 나온다 — 2026-10-17 화면과 대 봄)
_NOT_PROGRAMS = frozenset({"", "memory compression", "system idle process"})


def _private_working_sets() -> list[tuple[int, str, int]]:
    """(PID, 실행 파일 이름, 개인 작업 집합 바이트) — 작업 관리자 「메모리」 열이 쓰는 값. 윈도우 호출 한 번(실측 0.012초).

    `NtQuerySystemInformation(SystemProcessInformation)` 의 `WorkingSetPrivateSize` 칸이다. 관리자 권한 없이 모든 프로세스가 나온다.
    같은 값을 WMI(`Win32_PerfFormattedData_PerfProc_Process.WorkingSetPrivate`)로 읽으면 8초 걸렸다(2026-10-17 이 PC, 숫자는 같았다).
    """
    if os.name != "nt":
        return []
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    if ctypes.sizeof(ctypes.c_void_p) != 8:  # 칸 위치는 64비트 기준이다
        return []

    size = 1 << 20
    for _ in range(6):
        buffer = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG()
        status = ctypes.windll.ntdll.NtQuerySystemInformation(5, buffer, size, ctypes.byref(needed)) & 0xFFFFFFFF
        if status == 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH — 그사이 프로세스가 늘었다
            size = max(size * 2, needed.value + 65536)
            continue
        if status != 0:
            return []
        break
    else:
        return []
    raw, rows, offset = buffer.raw, [], 0
    while offset + 88 <= len(raw):
        following = int.from_bytes(raw[offset:offset + 4], "little")
        private = int.from_bytes(raw[offset + 8:offset + 16], "little", signed=True)
        length = int.from_bytes(raw[offset + 56:offset + 58], "little")
        pointer = int.from_bytes(raw[offset + 64:offset + 72], "little")
        pid = int.from_bytes(raw[offset + 80:offset + 88], "little")
        name = ctypes.wstring_at(pointer, length // 2) if pointer and length else ""
        rows.append((pid, name, max(0, private)))
        if not following:
            break
        offset += following
    return rows


def _is_task_manager(pid: int, title: str) -> bool:
    try:
        import psutil  # noqa: PLC0415

        if psutil.Process(int(pid)).name().casefold() == "taskmgr.exe":
            return True
    except Exception:
        pass
    return title.strip().casefold() in {"작업 관리자", "task manager"}


def _task_manager_values(rows: list[tuple[int, str, int]] | None = None, gpus_text: str | None = None) -> dict[str, Any]:
    """작업 관리자가 보여 주는 값 — 메모리 많이 쓰는 프로그램(이름별 합)과 그래픽카드 메모리.

    ★ 2026-10-17 작업 관리자 측정(5046e2e7 3판): 관리자 권한 창이라 모델이 명령으로 대신 읽었는데, 판마다 명령이 달라
      llama-server 가 8.1GB · 19.1GB · 13.0GB 로 나왔다(작업 집합 · 이름별 합 · 프로세스 하나). 작업 관리자는 **앱별로 묶고 개인
      작업 집합**을 보여 준다. 그 기준으로 한 번 읽어 붙인다 — 같은 질문에 같은 기준의 숫자가 나오게.
      같은 순간 작업 관리자 화면과 대 봄: llama-server 14,896.2MB ↔ 14,896 · Claude(25) 1,785.0 ↔ 1,775 · Chrome 두 묶음 합 2,730.5 ↔ 2,731.
      작업 관리자는 창(프로필)마다 따로 묶기도 한다 — 여기서는 이름으로 합친다.
    """
    rows = _private_working_sets() if rows is None else rows
    totals: dict[str, list[int]] = {}
    for _pid, name, private in rows:
        if name.casefold() in _NOT_PROGRAMS:
            continue
        label = name[:-4] if name.casefold().endswith(".exe") else name
        entry = totals.setdefault(label, [0, 0])
        entry[0] += private
        entry[1] += 1
    top = sorted(totals.items(), key=lambda item: item[1][0], reverse=True)[:10]
    out: dict[str, Any] = {
        "basis": "앱 이름별 합 · 개인 작업 집합(작업 관리자 「메모리」 열과 같은 기준). 시스템의 Memory Compression 은 뺐다.",
        "memory_top": [{"name": name, "mb": round(total / 1048576), "processes": count} for name, (total, count) in top],
    }
    if gpus_text is None:
        try:
            import subprocess  # noqa: PLC0415

            done = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=10, creationflags=0x08000000)
            gpus_text = done.stdout if done.returncode == 0 else ""
        except Exception:
            gpus_text = ""
    gpus = []
    for line in (gpus_text or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            gpus.append({"name": parts[0], "used_mib": int(parts[1]), "total_mib": int(parts[2])})
    if gpus:
        out["gpus"] = gpus
    return out


def _item_matches(item: str, wanted: str) -> bool:
    """목록 항목이 넣으려던 값과 같은가 — 글자 그대로, 아니면 앞 낱말(「JPEG (*.jpg…)」의 「JPEG」)이 같으면."""
    a, b = " ".join(str(item).split()).casefold(), " ".join(str(wanted).split()).casefold()
    if not a or not b:
        return False
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    head = b.split(" (")[0].split("(")[0].strip()
    return bool(head) and (a.split(" (")[0].split("(")[0].strip() == head)


def _select_combo_item(control: Any, wanted: str) -> str | None:
    """목록 칸(ComboBox)에서 넣으려는 값과 맞는 항목을 **골라** 넣는다. 맞는 항목이 없거나 고르지 못하면 None — 그때는 글자로 넣는다.

    파일 이름 칸처럼 글자를 쓰는 목록 칸은 넣을 값(「그림_1.jpg」)이 항목과 안 맞아 None 이 되고, 원래 길(붙여넣기)로 간다.
    """
    try:
        items = [str(text) for text in (control.texts() or []) if str(text).strip()]
    except Exception:
        items = []
    match = next((item for item in items if " ".join(item.split()).casefold() == " ".join(str(wanted).split()).casefold()), None)
    match = match or next((item for item in items if _item_matches(item, wanted)), None)
    if match is None:
        return None
    try:
        control.select(match)
    except Exception:
        return None
    return match


def _invoke_changed_something(tools: Any, window_id: int, control: Any, before: dict[int, str]) -> bool:
    """누름 신호(invoke)를 보내고 **눈에 띄는 변화**가 있었나 — 새 창 · 창 제목 변화 · 그 창의 요소 수 변화(메뉴가 펼쳐짐).

    한글 하위 메뉴처럼 신호를 오류 없이 무시하는 프로그램이 있어(7412255c), 변화가 없으면 False — 그때만 실제로 누른다.
    신호 자체가 안 되면(패턴 없음) False.
    """
    try:
        window = tools._window(window_id)
        title_before = str(window.window_text() or "")
        count_before = len(window.descendants())
    except Exception:
        return False
    try:
        control.invoke()
    except Exception:
        return False
    time.sleep(0.8)
    now = _visible_windows_now()
    if any(hwnd not in before and str(title).strip() for hwnd, title in now.items()):
        return True
    try:
        window = tools._window(window_id)
        return str(window.window_text() or "") != title_before or len(window.descendants()) != count_before
    except Exception:
        return True  # 창이 닫혔다 — 무언가 일어났다


def _menu_item_on_screen(control: Any) -> bool:
    """화면에 보이는 메뉴 항목인가 — 그때만 invoke 를 실제 클릭으로 바꾼다(닫힌 메뉴 속 항목은 클릭할 자리가 없다)."""
    try:
        info = control.element_info
        if str(info.control_type or "") != "MenuItem":
            return False
        rect = info.rectangle
        if int(rect.right) <= int(rect.left) or int(rect.bottom) <= int(rect.top):
            return False
        properties = control.get_properties()
        return bool(properties.get("is_visible", True)) and bool(properties.get("is_enabled", True))
    except Exception:
        return False


#: 파일 앞부분으로 아는 형식 — (확장자들, 맞는 머리 바이트들). 이름만 바꾸고 형식은 그대로 저장한 것을 잡는다.
_FORMAT_HEADS: tuple[tuple[tuple[str, ...], tuple[bytes, ...], str], ...] = (
    ((".jpg", ".jpeg", ".jpe", ".jfif"), (bytes([0xFF, 0xD8, 0xFF]),), "JPEG"),
    ((".png",), (bytes([0x89]) + b"PNG",), "PNG"),
    ((".gif",), (b"GIF8",), "GIF"),
    ((".bmp",), (b"BM",), "BMP"),
    ((".pdf",), (b"%PDF",), "PDF"),
)


def _sniff_format(head: bytes) -> str:
    for _exts, heads, label in _FORMAT_HEADS:
        if any(head.startswith(mark) for mark in heads):
            return label
    if head[4:8] == b"ftyp":
        return "HEIC/AVIF/MP4 계열"
    return "알 수 없음"


def _format_mismatch(path: Path) -> dict[str, Any]:
    """확장자가 말하는 형식과 파일 실제 형식이 다르면 알린다 (2026-10-17 앱 묶음 · 그림판 cf93ca97).

    저장 창의 「파일 형식」은 못 바꾸고 이름만 .jpg 로 저장해 **속은 HEIC 인 .jpg** 가 생겼고, 답은 「JPEG 로 저장했다」고 했다.
    창이 닫힌 바로 그때 알려 주면 모델이 형식을 다시 고를 수 있다. 모르는 확장자는 보지 않는다.
    """
    suffix = path.suffix.casefold()
    expected = next(((heads, label) for exts, heads, label in _FORMAT_HEADS if suffix in exts), None)
    if expected is None:
        return {}
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return {}
    heads, label = expected
    if any(head.startswith(mark) for mark in heads):
        return {}
    actual = _sniff_format(head)
    return {"saved_format_mismatch": f"이름은 {suffix} 인데 파일 실제 형식은 {actual} 입니다 — 저장 창의 「파일 형식」에서 {label} 를 고르고 다시 저장하세요."}


#: 대화 창(다른 이름으로 저장 · 열기)을 **열려고** 누르는 키 — 눌러도 아무 창이 안 뜨면 알린다(`_after_action`).
_DIALOG_KEYS = frozenset({"ctrl+shift+s", "f12", "ctrl+o", "ctrl+f12"})


def _dialog_key(preview: Any) -> str:
    if str(getattr(preview, "action", "")) != "key":
        return ""
    combo = "+".join(part.strip() for part in str(getattr(preview, "value", "") or "").casefold().split("+"))
    return combo if combo in _DIALOG_KEYS else ""


def _compact_element(metadata: dict[str, Any]) -> dict[str, Any]:
    """모델에게 보내는 요소 한 줄 — 번호 · 이름 · 종류 · 값, 그리고 **평소와 다를 때만** 꺼짐 · 안 보임.

    ★ 2026-10-17 한글 → PDF 측정(23d8ce63): 창을 한 번 읽을 때마다 모델 입력이 7,500~11,000토큰씩 늘었다(31,988 → 42,604 등).
      요소마다 좌표 네 개 · 내부 이름(class) · 자동화 번호 · 켜짐/보임/암호 칸이 붙어 있었는데, 모델은 번호(ref)로만 누르고
      그 칸들을 쓰지 않는다. 누를 때 다시 찾는 데 쓰는 전체 정보는 `self._refs` 에 그대로 있다.
    """
    row: dict[str, Any] = {"ref": metadata.get("ref", ""), "name": metadata.get("name", ""),
                           "control_type": metadata.get("control_type", "")}
    if not row["name"] and metadata.get("automation_id"):
        row["automation_id"] = metadata["automation_id"]
    if metadata.get("value"):
        row["value"] = metadata["value"]
    if metadata.get("enabled") is False:
        row["enabled"] = False
    if metadata.get("visible") is False:
        row["visible"] = False
    return row


def _visible_windows_now() -> dict[int, str]:
    """화면에 보이는 맨 위 창들 — `local_computer._visible_windows` 와 같은 것(그쪽 하나를 쓴다)."""
    try:
        from .local_computer import _visible_windows  # noqa: PLC0415 — 순환을 피해 쓸 때 부른다

        return _visible_windows()
    except Exception:
        return {}


def _control_value(control: Any) -> str:
    """입력 요소의 지금 값(최대 200자). 못 읽으면 빈 글."""
    for read in (lambda: control.get_value(), lambda: control.iface_value.CurrentValue, lambda: control.window_text()):
        try:
            value = read()
        except Exception:
            continue
        if value is not None and str(value) != "":
            return str(value)[:200]
    return ""


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
        on_waiting_for_hands: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.visual_planner = visual_planner
        #: 사람 손이 안 멈춰 실제 클릭 · 키 입력을 기다릴 때 부른다(`_wait_for_hands_off`). 무엇을 기다리는지(「키 입력」 등)를 넘긴다.
        self.on_waiting_for_hands = on_waiting_for_hands
        self._last_hands_notice = -1e9
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
        # ★ 바닥 150 (2026-10-17 한글 → PDF 측정 f885ea48 2판째). 모델이 입력을 아끼려고 50 · 80 개만 달라고 해서 열린 메뉴의
        #   「PDF로 저장하기」가 잘렸고, 같은 메뉴를 다시 열기를 되풀이하다 48걸음 상한에 걸렸다. 요소 한 줄이 짧아진 뒤로는(번호 ·
        #   이름 · 종류 · 값) 150개도 한글 창 기준 약 1만 자다 — 아낄 까닭이 없다.
        maximum = max(150, min(int(arguments.get("max_elements") or 160), 300))
        window = self._window(window_id)
        controls = [window, *window.descendants()]

        def interactive(control: Any) -> int:
            try:
                return 0 if str(control.element_info.control_type or "") in _INTERACTIVE_TYPES else 1
            except Exception:
                return 1

        # 조작할 수 있는 요소를 먼저(안정 정렬 — 같은 묶음 안은 화면 순서). 창 자신은 맨 앞 그대로.
        controls = [controls[0], *sorted(controls[1:], key=interactive)]
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
                if metadata["control_type"] in _VALUE_TYPES and not metadata.get("password"):
                    value = _control_value(control)
                    if value and value != metadata["name"]:
                        metadata["value"] = value
                if not metadata["name"] and not metadata["automation_id"] and not metadata.get("value"):
                    continue
                ref = f"u{len(elements) + 1}"
                metadata["ref"] = ref
                self._refs[(window_id, ref)] = metadata
                elements.append(_compact_element(metadata))
        result = {
            "action": "windows_uia_snapshot",
            "window_id": window_id,
            "title": str(window.window_text() or "")[:500],
            "count": len(elements),
            "truncated": len(controls) > len(elements),
            "elements": elements,
        }
        # ★ **관리자 권한 창은 안을 못 읽는다고 바로 말한다** (2026-10-17 작업 관리자 판 24b0a455). 윈11 작업 관리자는 관리자
        #   권한으로 뜨고, 일반 권한인 손자리는 그 창의 안(목록 · 칸)을 읽을 수 없다(윈도우 보안 규칙). 구조가 「창 하나」로만 와서
        #   모델이 복사 · 다시 읽기 · 화면 보고 누르기로 다섯 걸음을 헤맸다. 같은 값을 명령으로 읽으라고 같이 적는다.
        if len(elements) <= 2:
            try:
                pid = int(window.process_id())
            except Exception:
                pid = 0
            if _process_elevated(pid) and not _process_elevated(os.getpid()):
                result["unreadable_elevated"] = True
                result["note"] = ("이 창은 관리자 권한으로 떠 있어 손자리가 안의 목록 · 칸을 읽을 수 없습니다. 창을 다시 읽거나 누르지 말고, "
                                  "같은 값을 명령으로 읽으세요(예: 프로세스 메모리는 Get-Process, 그래픽 메모리는 nvidia-smi).")
                if _is_task_manager(pid, result["title"]):
                    values = _task_manager_values()
                    if values.get("memory_top"):
                        result["same_values"] = values
                        result["note"] = ("이 창은 관리자 권한이라 안을 읽을 수 없어, 작업 관리자 「메모리」 열과 같은 기준(앱 이름별 합 · 개인 작업 집합)으로 "
                                          "손자리가 같은 값을 읽어 same_values 에 붙였습니다. 창을 다시 읽거나 명령을 따로 돌리지 말고 이 값을 쓰세요.")
        return result

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
        """사람 손이 키보드·마우스에서 멈출 때까지 기다린다(인수인계 H2-A). 끝내 안 멈추면 미룬다.

        ★ 2026-10-17 밤(대표): 기다리는 동안 사람은 손자리가 기다리는 줄 몰랐다. 곧바로 손이 안 멈추면 **한 번 알린다**
          (`on_waiting_for_hands` — 윈도우 알림. 1분에 한 번까지).
        """
        if self.presence.wait_until_idle(quiet_sec=2.0, timeout_sec=1.5):
            return
        now = time.monotonic()
        if self.on_waiting_for_hands is not None and now - self._last_hands_notice >= 60.0:
            self._last_hands_notice = now
            try:
                self.on_waiting_for_hands(what)
            except Exception:
                pass
        if self.presence.wait_until_idle(quiet_sec=2.0, timeout_sec=43.5):
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
        before = _visible_windows_now()
        save_target = self._save_dialog_target(preview.window_id) if preview.action in {"invoke", "click", "key"} else ""

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
                **self._after_action(preview.window_id, before, wait=2.0 if preview.action in {"key", "invoke", "click", "double_click"} else 0.3,
                                 dialog_key=_dialog_key(preview)),
            }

        checked: dict[str, Any] = {}
        if preview.source == "uia":
            if str(preview.target.get("name") or "").strip().casefold() in _END_TASK_NAMES and preview.action in {"invoke", "click", "double_click"}:
                raise PermissionError("end_task_blocked: 프로그램을 강제로 끄는 단추는 손자리가 누르지 않습니다 — 사람이 직접 눌러 주세요.")
            control = self._find_control(preview.window_id, preview.target)
            if preview.action == "focus":
                control.set_focus()
            elif preview.action == "set_value":
                if preview.target.get("password"):
                    raise PermissionError("password_control_blocked")
                # ★ **사람처럼 고르고 · 다 고르고 · 붙여 넣는다** (2026-10-17 메모장 판 ac3f08b7). 값을 바로 바꿔 넣었더니(`set_edit_text`)
                #   다시 읽은 칸은 「화면측정_13545.txt」로 맞았는데, 윈도우 저장 창은 그 값을 받지 않고 첫 줄 이름으로 저장했다 —
                #   파일 대화 창은 키 입력으로 들어온 값만 제 것으로 친다. 붙여넣기가 안 되는 칸이면 예전 방식으로 넣는다.
                # ★ **목록에서 고르는 칸은 고른다** (2026-10-17 앱 묶음 측정 · 그림판 cf93ca97). 저장 창의 「파일 형식」에 「JPEG (*.jpg…)」를
                #   넣으려다 'ComboBoxWrapper' 에 글자 넣기가 없어 오류가 났고, 목록을 열어 누르려니 항목이 두 번 사라졌다. 결국 형식은
                #   그대로 둔 채 이름만 .jpg 로 저장해 **HEIC 파일에 .jpg 이름**이 붙었다. 넣을 값이 그 칸의 항목과 맞으면 그 항목을 고른다.
                picked = _select_combo_item(control, preview.value) if str(preview.target.get("control_type") or "") == "ComboBox" else None
                if picked is not None:
                    time.sleep(0.2)
                    after = _control_value(control) or picked
                    checked = {"value_after": after, "selected_item": picked,
                               "value_matches": _item_matches(after, preview.value) or _item_matches(picked, preview.value)}
                else:
                    self._prepare_com_cache()
                    from pywinauto import keyboard

                    self._wait_for_hands_off("값 넣기")
                    previous = ""
                    try:
                        previous = _clipboard_get()
                    except Exception:
                        previous = ""
                    try:
                        control.set_focus()
                        time.sleep(0.1)
                        keyboard.send_keys("^a")
                        _clipboard_set(preview.value)
                        keyboard.send_keys("^v")
                        time.sleep(0.2)
                    finally:
                        try:
                            _clipboard_set(previous)
                        except Exception:
                            pass
                    if _control_value(control).strip() != str(preview.value).strip() and hasattr(control, "set_edit_text"):
                        control.set_edit_text(preview.value)
                    time.sleep(0.1)
                    after = _control_value(control)
                    checked = {"value_after": after, "value_matches": after.strip() == str(preview.value).strip()}
            elif preview.action == "toggle":
                control.toggle()
            elif preview.action == "select":
                control.select()
            elif preview.action == "invoke" and _menu_item_on_screen(control):
                # ★ **메뉴 항목은 실제로 누른다** (2026-10-17 한글 → PDF 측정 7412255c). 한글의 「파일 > PDF로 저장하기」를 invoke 로
                #   누르면 오류 없이 **아무 일도 안 일어났다** — 메뉴를 직접 그리는 프로그램은 누름 신호를 무시한다. 모델이 같은 메뉴를
                #   invoke 로 다섯 번 되풀이하다 41걸음째에 click 으로 바꾸고서야 저장 창이 떴다(46걸음 · 593초). 사람도 메뉴는 클릭한다.
                # ★ 2026-10-17 밤(대표 「사람이 PC 를 쓰는 중이어도」): 실제 클릭은 사람의 마우스를 뺏는다. 먼저 누름 신호를 보내 보고,
                #   **아무 변화가 없을 때만** 실제로 누른다 — 한글 「파일」 메뉴처럼 신호가 먹는 곳에서는 마우스를 움직이지 않는다.
                if _invoke_changed_something(self, preview.window_id, control, before):
                    checked = {"executed_as": "invoke"}
                else:
                    self._wait_for_hands_off("메뉴 누르기")
                    control.click_input()
                    checked = {"executed_as": "click"}
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
            **checked,
            **self._saved_file(save_target),
            **self._after_action(preview.window_id, before, wait=2.0 if preview.action in {"key", "invoke", "click", "double_click"} else 0.3,
                                 dialog_key=_dialog_key(preview)),
        }

    #: 저장 대화 창의 제목 — 윈도우 기본 「다른 이름으로 저장」과 한글의 「PDF로 저장하기」.
    _SAVE_DIALOG_TITLES = ("다른 이름으로 저장", "save as", "pdf로 저장하기", "저장하기")

    def _save_dialog_target(self, window_id: int) -> str:
        """저장 창이면 **누르기 직전** 그 창의 폴더(주소 칸)와 파일 이름 칸으로 저장될 자리를 만든다. 아니면 빈 글.

        ★ 2026-10-17 메모장 측정(cad4f57a): 12걸음째에 저장을 끝내고도 「저장한 자리를 알려 줘」를 채우려고 C 드라이브 폴더를 열 걸음
          뒤졌다. 그 자리는 저장 창의 주소 칸에 적혀 있었다. 짐작은 하지 않는다 — 창이 닫힌 뒤 그 파일이 실제로 있을 때만 적는다.
        """
        try:
            window = self._window(window_id)
            title = str(window.window_text() or "").strip().casefold()
            if not any(mark in title for mark in self._SAVE_DIALOG_TITLES):
                return ""
            folder, name = "", ""
            for control in window.descendants():
                info = control.element_info
                label = str(info.name or "")
                if not folder and (label.startswith("주소: ") or label.startswith("Address: ")):
                    folder = label.split(": ", 1)[1].strip()
                if not name and str(info.control_type or "") in {"Edit", "ComboBox"} and (
                    label.startswith("파일 이름") or label.startswith("File name") or str(info.automation_id or "") == "1001"
                ):
                    name = _control_value(control).strip()
                if folder and name:
                    break
            if folder and name and ":" in folder:
                return str(Path(folder) / name)
        except Exception:
            return ""
        return ""

    @staticmethod
    def _saved_file(target: str) -> dict[str, Any]:
        """저장 창이 닫힌 뒤 그 자리에 파일이 **실제로 있으면** 그 경로. 확장자를 안 적은 이름은 같은 이름의 파일을 찾는다."""
        if not target:
            return {}
        time.sleep(0.5)
        path = Path(target)
        try:
            if path.is_file():
                return {"saved_file": str(path), **_format_mismatch(path)}
            if not path.suffix:
                hits = sorted(path.parent.glob(path.name + ".*"), key=lambda item: item.stat().st_mtime, reverse=True)
                if hits and time.time() - hits[0].stat().st_mtime < 30:
                    return {"saved_file": str(hits[0]), **_format_mismatch(hits[0])}
        except OSError:
            return {}
        return {}

    def _after_action(self, window_id: int, before: dict[int, str], *, wait: float = 2.0, dialog_key: str = "") -> dict[str, Any]:
        """동작 뒤 그 창의 제목과 **새로 뜬 창**(저장 창 · 대화 창).

        ★ 2026-10-17 한글 → PDF 측정(5d5b9d82): 「PDF로 저장하기」를 누르면 그 대화 창은 **따로 뜨는 새 창**인데, 원래 한글 창의
          제목은 그대로라 모델이 「아무 일도 없었다」로 읽고 같은 메뉴를 되풀이하다 48걸음을 다 썼다. 성공한 판은 창 목록을 다시 보고서야
          그 창을 찾았다. 새 창이 뜨면 그 번호 · 제목을 바로 적는다(최대 2.5초 기다림). 저장 뒤 제목이 시킨 이름과 같은지도 여기서 본다.
        """
        out: dict[str, Any] = {}
        fresh: dict[int, str] = {}
        deadline = time.monotonic() + max(0.3, wait)
        while True:
            time.sleep(0.3)
            now = _visible_windows_now()
            fresh = {hwnd: title for hwnd, title in now.items() if hwnd not in before and title.strip()}
            if fresh or time.monotonic() >= deadline or not before:
                break
        try:
            out["window_title_after"] = str(self._window(window_id).window_text() or "")[:300]
        except Exception:
            out.update({"window_title_after": "", "window_closed_after": True})
        if fresh:
            out["new_windows"] = [{"window_id": hwnd, "title": title[:200]} for hwnd, title in list(fresh.items())[:3]]
        # ★ **창을 열려고 누른 키가 아무것도 안 열었으면 바로 말한다** (2026-10-17 앱 묶음 · 엑셀 ec55f971). 엑셀에서 Ctrl+Shift+S 는
        #   아무 일도 안 해서 「파일」 탭 저장 화면으로 돌아갔고, 거기에 전체 경로를 넣다 오류 창 두 번 · 폴더 하나씩 들어가기로 15걸음을 썼다.
        #   Tab · Enter 처럼 원래 창이 안 바뀌는 키는 보지 않는다 — 대화 창을 여는 키만.
        elif dialog_key and out.get("window_title_after") == before.get(window_id, out.get("window_title_after")):
            out["no_window_opened"] = (f"{dialog_key} 뒤에 새 창이 뜨지 않았고 창 제목도 그대로입니다 — 이 프로그램에서는 그 창을 여는 키가 "
                                       "다를 수 있습니다(오피스 엑셀 · 워드 · 파워포인트의 「다른 이름으로 저장」 창은 F12, 「열기」 창은 Ctrl+F12).")
        return out
