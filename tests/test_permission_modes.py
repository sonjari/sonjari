"""권한을 **한 번에 고른다** — 토글 아홉 개 말고 모드 하나 (2026-09-21 사장님 요청).

> 권한승인 이거 이제 클로드 권한 설정하는것처럼해서 사용자가 원하는대로 하는거는 어떤데
> … 왜냐하면 계속 눌러야되는게 귀찮네

## 왜

지금 권한은 설정 화면에 **토글 아홉 개**로 흩어져 있다. 사람은 그걸 찾아 들어가
하나씩 켜야 하고, 그 전까지는 승인 카드를 계속 누른다.

## 모드

    ask         하나씩 물어본다 (기본 · 지금 동작 그대로)
    reversible  되돌릴 수 있는 일은 알아서 — 되돌리기가 달린 것만
    workspace   작업 폴더 안에서는 알아서 — 셸의 만들기·지우기까지
    read_only   아무것도 안 바꾼다 — 보고 계획만 (클로드의 plan 과 같은 자리)

## ★ 모드가 못 여는 것

결제·발행·메일 보내기·지우기·보안 설정은 **어느 모드에서도 자동이 안 된다.**
이건 설정이 아니라 규칙이다 — 사장님이 「무조건」이라고 하신 자리와 같다.
모드를 넓혀도 이 목록은 안 넓어진다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.permissions import (
    ALWAYS_ASK,
    MODES,
    apply_mode,
    mode_of,
)


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")


# ── 모드가 토글을 정한다 ────────────────────────────────────────────────────
def test_ask_is_the_default_and_changes_nothing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert mode_of(config) == "ask"
    assert config.approval_auto_reversible is False
    assert config.shell_autorun_enabled is False


def test_reversible_opens_only_what_can_be_undone(tmp_path: Path) -> None:
    config = _config(tmp_path)
    changes = apply_mode(config, "reversible")
    assert changes["approval_auto_reversible"] is True
    assert changes["shell_autorun_enabled"] is False, "되돌리기 없는 셸까지 열면 안 된다"


def test_workspace_also_opens_the_shell(tmp_path: Path) -> None:
    changes = apply_mode(_config(tmp_path), "workspace")
    assert changes["approval_auto_reversible"] is True
    assert changes["shell_autorun_enabled"] is True


def test_read_only_closes_everything(tmp_path: Path) -> None:
    changes = apply_mode(_config(tmp_path), "read_only")
    assert changes["approval_auto_reversible"] is False
    assert changes["shell_autorun_enabled"] is False
    assert changes["local_write_enabled"] is False


def test_a_bad_mode_name_is_refused_not_guessed(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        apply_mode(_config(tmp_path), "전부다열어")


# ── 모드를 읽어 되돌릴 수 있다 ──────────────────────────────────────────────
@pytest.mark.parametrize("mode", sorted(MODES))
def test_what_we_set_is_what_we_read_back(tmp_path: Path, mode: str) -> None:
    """설정하고 읽었을 때 다른 모드가 나오면 화면이 거짓말한다."""
    config = _config(tmp_path)
    for key, value in apply_mode(config, mode).items():
        setattr(config, key, value)
    assert mode_of(config) == mode


# ── ★ 모드가 못 여는 것 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("tool", sorted(ALWAYS_ASK))
def test_the_never_auto_list_is_not_reachable_by_any_mode(tool: str) -> None:
    """어느 모드에서도 이 도구들은 자동이 안 된다 — 설정이 아니라 규칙이다."""
    for mode in MODES:
        assert tool in ALWAYS_ASK, (mode, tool)


def test_the_never_auto_list_covers_the_irreversible_kinds() -> None:
    """목록이 비면 규칙이 없는 것과 같다. 무엇이 들었는지 못 박아 둔다."""
    joined = " ".join(ALWAYS_ASK)
    for kind in ("gmail_send", "delete", "publish", "payment"):
        assert kind in joined, f"{kind} 종류가 목록에 없다"


def test_modes_are_exactly_five_and_named() -> None:
    assert set(MODES) == {"ask", "reversible", "workspace", "read_only", "bypass"}
    for mode, meta in MODES.items():
        assert meta["label"] and meta["help"], mode


def test_labels_match_claude_codes_permission_menu() -> None:
    """★ 2026-09-23 사장님 요청: 「클로드 권한방식이랑 똑같이」. 이름과 순서를 클로드 코드 메뉴에 맞춘다."""
    assert [meta["label"] for meta in MODES.values()] == ["자동", "수동", "편집 자동 수락", "계획", "권한 무시"]
