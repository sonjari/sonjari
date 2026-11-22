"""데스크톱 창 조종 도구의 **역할 → 이름 표** — 윈도우 `windows_*` 와 맥 `mac_*` 를 한 표에서 본다.

★ 2026-11-16 맥 컴퓨터 유즈(설계 `docs/설계_맥_컴퓨터유즈_2026-11-16.ko.md` §4-4 · §8-1).
  판정 코드 13곳(승인 목록 · 걸음 셈 · 읽음 셈 · 진척 셈 …)이 `windows_*` 이름을 저마다 글자로 적어 두고 있었다. 맥 도구를 더할 때
  자리마다 이름을 하나씩 더하면 한 곳은 반드시 빠진다 — 빠진 곳이 승인 목록이면 맥 실행이 **사람 승인 없이** 지나간다.
  그래서 판정 자리는 이 표에서 **역할로** 집합을 가져간다. 새 OS · 새 이름은 이 표에만 더한다.

이름을 `mac_*` 로 따로 두는 까닭: 모델이 「Windows 앱」 설명을 맥에서 보면 헷갈린다(설계 §4-1). 이름은 둘, 역할은 하나다.

★ 윈도우 이름은 **바뀌지 않는다.** 각 자리의 윈도우 쪽 집합은 옮기기 전과 글자까지 같다(`tests/test_desktop_tools.py` 가 6927f47e 의
  옛 집합을 그대로 들고 대조한다).
"""

from __future__ import annotations

#: 열린 창 목록(읽기 · L0)
LIST = "list"
#: 창 앞으로(L1)
FOCUS = "focus"
#: 파일 · 앱 열기(L2)
OPEN = "open"
#: 창의 UI 요소 읽기(L0) — 윈도우 UIA · 맥 손쉬운 사용(AX)
SNAPSHOT = "snapshot"
#: 요소 동작 미리보기(L1 · 실행 안 함)
PREVIEW = "preview"
#: 비전 좌표 미리보기(L1) — 맥은 1차에 없다(설계 §4-1)
VISUAL_PREVIEW = "visual_preview"
#: 승인된 미리보기 실행(L2 · 늘 승인)
EXECUTE = "execute"
#: 창 내용 복사해 읽기(L1)
COPY = "copy"

#: 역할 → (윈도우 이름, 맥 이름). 짝이 없으면 빈 글.
ROLE_NAMES: dict[str, tuple[str, str]] = {
    LIST: ("windows_list_open_windows", "mac_list_open_windows"),
    FOCUS: ("windows_focus_window", "mac_focus_window"),
    OPEN: ("windows_open_path", "mac_open_path"),
    SNAPSHOT: ("windows_uia_snapshot", "mac_ax_snapshot"),
    PREVIEW: ("windows_uia_preview", "mac_ax_preview"),
    VISUAL_PREVIEW: ("windows_visual_preview", ""),
    EXECUTE: ("windows_execute_preview", "mac_execute_preview"),
    COPY: ("windows_copy_from_window", "mac_copy_from_window"),
}

WINDOWS = "windows"
MAC = "mac"
_OS_INDEX = {WINDOWS: 0, MAC: 1}


def names(*roles: str, os_name: str | None = None) -> frozenset[str]:
    """역할들의 도구 이름 집합. `os_name` 을 안 주면 두 OS 다."""
    picked = (0, 1) if os_name is None else (_OS_INDEX[os_name],)
    out: set[str] = set()
    for role in roles:
        pair = ROLE_NAMES[role]
        out.update(pair[index] for index in picked if pair[index])
    return frozenset(out)


def role_of(tool: str) -> str:
    """도구 이름의 역할. 표에 없으면 빈 글."""
    for role, pair in ROLE_NAMES.items():
        if tool and tool in pair:
            return role
    return ""


ALL_ROLES = tuple(ROLE_NAMES)
MAC_NAMES = names(*ALL_ROLES, os_name=MAC)
WINDOWS_NAMES = names(*ALL_ROLES, os_name=WINDOWS)

#: 맥 도구의 진행 문구(`agent._tool_label`). 윈도우 문구는 그 자리에 그대로 둔다(「Windows 앱」 낱말이 들어 있어서).
MAC_PROGRESS_LABELS: dict[str, str] = {
    "mac_list_open_windows": "현재 열린 맥 앱 창을 확인 중",
    "mac_focus_window": "요청한 앱 창을 앞으로 가져오는 중",
    "mac_open_path": "요청한 파일이나 앱을 여는 중",
    "mac_ax_snapshot": "앱의 조작 가능한 요소를 읽는 중",
    "mac_ax_preview": "맥 동작 미리보기를 만드는 중",
    "mac_execute_preview": "승인된 맥 동작을 실행하는 중",
    "mac_copy_from_window": "창의 내용을 읽는 중",
}
