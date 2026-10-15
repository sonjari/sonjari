"""권한을 **한 번에 고른다** — 토글 아홉 개 말고 모드 하나 (2026-09-21 사장님 요청).

> 권한승인 이거 이제 클로드 권한 설정하는것처럼해서 사용자가 원하는대로 하는거는 어떤데
> … 왜냐하면 계속 눌러야되는게 귀찮네

## 왜 모드인가

권한은 설정 화면에 토글 아홉 개로 흩어져 있었다. 사람은 그걸 찾아 들어가 하나씩
켜야 하고, 그 전까지는 승인 카드를 계속 누른다. 실제로 그게 귀찮아서 나온 요청이다.

**모드는 새 관문이 아니다.** 이미 잘 만들어진 관문(`ToolGateway._auto_approvable`)
위에 얹는 **한 곳의 손잡이**다 — 모드가 기존 설정값을 정한다. 관문을 두 벌로 만들면
언젠가 둘이 갈리고, 그때 낮은 쪽만 일한다(사고 Q).

## ★ 모드가 못 여는 것

결제·발행·메일 보내기·지우기·보안 설정은 **어느 모드에서도 자동이 안 된다.**
이건 설정이 아니라 규칙이다. 모드를 넓혀도 이 목록은 안 넓어진다 —
넓히려면 이 파일을 고쳐야 하고, 고치면 시험이 잡는다.

**예외 하나 — 「권한 무시」(2026-09-23 사장님 결정).** 클로드 코드의 bypass 와 같은 자리라
지우기·폴더 권한·PC 설정까지 묻지 않는다. 그래도 `NEVER_BYPASS`(결제·메일 보내기·발행)는
남는다 — 돈이 빠지거나 남에게 나간 것은 되돌릴 수 없기 때문이다.
"""

from __future__ import annotations

from typing import Any

#: 어느 모드에서도 **사람이 본다.** 되돌릴 수 없거나, 밖으로 나가거나, 돈이 드는 것.
#
# 이 목록은 「조심해서 다루자」가 아니라 **닫힌 문**이다. 여기 없는 것을 자동으로
# 여는 것은 모드의 일이고, 여기 있는 것을 여는 것은 아무의 일도 아니다.
ALWAYS_ASK: frozenset[str] = frozenset({
    # 밖으로 나간다 — 되돌릴 수 없다
    "google_gmail_send",
    "naver_blog_publish",
    # 남의 것을 지운다
    "google_calendar_delete",
    "schedule_cancel",
    "local_delete_file",
    # 돈이 오간다 (지금 없어도 생기면 여기부터다)
    "payment_confirm",
    # 이 PC 를 바꾼다
    "windows_execute_preview",
    "local_request_path_access",
})

#: **권한 무시** 모드에서도 사람이 보는 것 — 돈이 오가거나 남에게 나가는 것만 (2026-09-23 사장님 결정).
#
# 「권한 무시」는 클로드 코드의 bypass 와 같은 자리다. 다만 로컬 모델이 지어낸 내용으로
# **메일이 나가거나 돈이 빠지면 되돌릴 방법이 없다** — 그래서 이 셋만 남긴다. 지우기·PC 설정·
# 폴더 권한은 이 모드에서 묻지 않는다(사장님이 고른 범위). 셸 실행부의 보안 거부(보안 설정·
# 시스템 폴더)는 승인이 아니라 실행부의 규칙이라 이 모드에서도 그대로다.
NEVER_BYPASS: frozenset[str] = frozenset({
    "google_gmail_send",
    "naver_blog_publish",
    "payment_confirm",
})

#: 고를 수 있는 모드. 라벨·설명은 화면이 그대로 쓴다 — 두 곳에 적으면 갈린다.
#
# ★ 이름과 순서를 **클로드 코드의 권한 메뉴와 맞췄다** (2026-09-23 사장님 요청: 「클로드 권한방식이랑
#   똑같이」). 자동 · 수동 · 편집 자동 수락 · 계획 · 권한 무시. 안쪽 id 는 그대로 둔다 —
#   저장된 설정·화면·시험이 id 로 부른다.
MODES: dict[str, dict[str, Any]] = {
    "workspace": {
        "label": "자동",
        # ★ 2026-10-09: 「작업 폴더 안에서는」이라고 적혀 있었는데 실제와 달랐다 — 허락한 폴더 목록은 파일 도구에만 걸리고,
        #   실행하는 명령은 그 밖이다. 대표가 이 화면을 보고 「폴더를 정해 줬는데 왜 밖을 건드렸나」를 물었다. 있는 대로 적는다.
        #   (손자리 자신의 설치 폴더는 명령으로도 못 바꾼다 — `local_computer.names_our_own_install`.)
        "help": "허락한 폴더 안의 파일은 알아서 만들고 고칩니다. 명령도 묻지 않고 실행합니다 — 명령은 그 폴더 밖의 파일도 바꿀 수 있습니다. 폴더 밖 파일 고치기와 메일·발행·삭제·결제는 물어봅니다.",
        "settings": {
            "approval_auto_reversible": True,
            "shell_autorun_enabled": True,
            "local_write_enabled": True,
            "approval_bypass_enabled": False,
        },
    },
    "ask": {
        "label": "수동",
        "help": "바꾸기 전에 항상 확인합니다. 가장 안전합니다.",
        "settings": {
            "approval_auto_reversible": False,
            "shell_autorun_enabled": False,
            "local_write_enabled": True,
            "approval_bypass_enabled": False,
        },
    },
    "reversible": {
        "label": "편집 자동 수락",
        "help": "되돌릴 수 있는 편집은 묻지 않고 합니다. 명령 실행·메일·발행·삭제는 물어봅니다.",
        "settings": {
            "approval_auto_reversible": True,
            # 셸의 만들기·지우기는 되돌리기가 없다 — 여기서는 안 연다.
            "shell_autorun_enabled": False,
            "local_write_enabled": True,
            "approval_bypass_enabled": False,
        },
    },
    "read_only": {
        "label": "계획",
        "help": "아무것도 바꾸지 않습니다. 읽고, 보고, 무엇을 할지 계획만 세웁니다.",
        "settings": {
            "approval_auto_reversible": False,
            "shell_autorun_enabled": False,
            "local_write_enabled": False,
            "approval_bypass_enabled": False,
        },
    },
    "bypass": {
        "label": "권한 무시",
        "help": "묻지 않고 다 합니다(지우기·폴더 권한·PC 설정 포함). 결제·메일 보내기·블로그 발행만 확인합니다.",
        "settings": {
            "approval_auto_reversible": True,
            "shell_autorun_enabled": True,
            "local_write_enabled": True,
            "approval_bypass_enabled": True,
        },
    },
}


#: **무언가를 바꾸는 도구.** `read_only` 모드가 막는 목록이고, 눈금(`measure_autonomy`)이
#: 쓰기 실적을 세는 목록이기도 하다.
#
# ★ 이 목록은 오래 **벤치 스크립트 안에** 있었다. 제품이 벤치를 import 할 수는 없으니
#   제품 쪽으로 옮겼다 — 같은 목록이 두 곳에 있으면 언젠가 갈리고, 갈리면 한쪽이
#   조용히 덜 센다(실측: 새 도구가 목록에 안 들어가 쓰기 71건이 통째로 안 세어졌다).
#
# ★ 새 쓰기 도구를 만들면 **여기에 넣는다.** 안 넣으면 읽기만 모드가 그 도구를 안 막고,
#   눈금도 그 도구를 안 센다. 두 고장이 한 줄에서 난다.
WRITE_TOOL_NAMES: frozenset[str] = frozenset({
    "artifact_from_observations",
    "browser_click",
    "browser_click_at",
    "browser_click_confirmed",
    "browser_dismiss_dialog",
    "browser_file_upload",
    "browser_fill",
    "browser_fill_form",
    "browser_handle_dialog",
    "browser_pick_suggestion",
    "browser_press",
    "browser_select_option",
    "browser_type_at",
    "camera_forget_face",
    "camera_gimbal_mode",
    "camera_recenter",
    "camera_register_face",
    "camera_register_new_person",
    "camera_start_live",
    "camera_stop_live",
    "claude_code_delegate",
    "clipboard_write",
    "google_calendar_create",
    "google_calendar_delete",
    "google_calendar_update",
    "google_drive_write",
    "google_gmail_send",
    "hwp_apply_edit",
    "local_apply_edit",
    "local_delete_file",
    "local_edit_document",
    "local_edit_spreadsheet",
    "local_open_path",
    # ★ 2026-09-23 (사장님 지적으로 발견): 등급이 하드코딩 L1 이라 승인 카드가 아예
    #   안 뜨는데, 허용 명령에 `ruff format .` 처럼 **저장소 파일을 실제로 고쳐 쓰는**
    #   것이 있다. 이 목록에 없으면 「읽기만」 모드에서도 그대로 실행됐다 — 그 모드의
    #   약속("아무것도 안 바꾼다")이 깨지는 자리였다.
    "local_run_project_command",
    "local_write_document",
    "local_write_file",
    "naver_blog_fill_editor",
    "naver_blog_publish",
    "naver_blog_save_draft",
    "sandbox_fetch",
    "sandbox_reset",
    "sandbox_run",
    "schedule_cancel",
    "schedule_create",
    "site_promote_draft",
    "ui_click_target",
    "undo_action",
    "watch_cancel",
    "watch_create",
    "windows_click",
    "windows_execute_preview",
    "windows_open_path",
    "windows_type",
})

DEFAULT_MODE = "ask"


def apply_mode(config: Any, mode: str) -> dict[str, Any]:
    """`mode` 가 뜻하는 설정값들. **여기서 config 를 바꾸지 않는다** — 돌려만 준다.

    바꾸는 것은 설정 서비스의 일이다(라이브 반영·기록이 거기 달려 있다).
    이 함수가 직접 쓰면 저장 안 된 값이 프로세스에만 살아 다음 재시작에 사라진다.
    """
    key = str(mode or "").strip()
    if key not in MODES:
        raise ValueError(f"unknown_permission_mode:{key} — 고를 수 있는 것: {', '.join(MODES)}")
    return dict(MODES[key]["settings"])


def change_mode(settings: Any, config: Any, mode: str) -> dict[str, Any]:
    """모드를 **저장하고 실제로 적용됐는지 읽어 본다.** 안 됐으면 `ok: False` 로 이유와 함께 돌려준다.

    ★ 예전 엔드포인트는 `settings.patch` 가 `ok` 이면 그대로 `ok` 라 했다. 그런데 이 세 설정이 라이브가 아니었을 때
      `patch` 는 **파일에만 저장하고** `restart_required` 로 알렸고, 엔드포인트는 그걸 버렸다 — 모드를 골라도
      아무 일도 안 일어났는데 응답은 `ok: true` 였다(2026-09-21). 저장과 적용은 다른 일이다.
    """
    try:
        changes = apply_mode(config, mode)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    saved = settings.patch(changes)
    if not saved.get("ok"):
        return {"ok": False, "error": str(saved.get("error") or "settings_rejected")}
    current = mode_of(config)
    if current != str(mode).strip():
        return {"ok": False, "error": "mode_not_applied", "wanted": str(mode).strip(), "mode": current,
                "restart_required": list(saved.get("restart_required") or []), **public_modes(config)}
    return {"ok": True, **public_modes(config)}


def mode_of(config: Any) -> str:
    """지금 설정이 어느 모드인가. 어디에도 안 맞으면 `custom`.

    ★ `custom` 이 있어야 하는 이유: 사람이 토글을 하나만 손으로 바꿔 둘 수 있다.
      그걸 억지로 가까운 모드로 부르면 화면이 거짓말하고, 모드를 다시 고르는 순간
      사람이 바꿔 둔 것이 조용히 사라진다.
    """
    current = {
        "approval_auto_reversible": bool(getattr(config, "approval_auto_reversible", False)),
        "shell_autorun_enabled": bool(getattr(config, "shell_autorun_enabled", False)),
        "local_write_enabled": bool(getattr(config, "local_write_enabled", True)),
        "approval_bypass_enabled": bool(getattr(config, "approval_bypass_enabled", False)),
    }
    for name, meta in MODES.items():
        if all(current[key] == value for key, value in meta["settings"].items()):
            return name
    return "custom"


def public_modes(config: Any) -> dict[str, Any]:
    """화면이 그릴 것 — 지금 모드와 고를 수 있는 것들."""
    return {
        "mode": mode_of(config),
        "modes": [
            {"id": name, "label": meta["label"], "help": meta["help"]}
            for name, meta in MODES.items()
        ],
        # 화면이 「이건 모드를 바꿔도 계속 물어봅니다」라고 정직하게 적을 수 있게.
        "always_ask": sorted(ALWAYS_ASK),
        # 「권한 무시」에서도 묻는 것 — 화면이 그 모드 설명 옆에 정직하게 적을 수 있게.
        "never_bypass": sorted(NEVER_BYPASS),
    }
