"""권한 모드를 고르면 **그 자리에서** 적용된다 — 안 됐으면 안 됐다고 말한다 (2026-09-21, 노트북 벤치).

## 어떻게 찾았나

승인 카드를 못 누르겠다는 말에 노트북의 권한 모드를 API 로 `workspace` 로 올렸다:

    POST /v1/permissions/mode {"mode":"workspace"}   →   {"ok": true, "mode": "ask", ...}
    GET  /v1/permissions/mode                        →   "ask"        ← 그대로

**`ok: true` 인데 아무 일도 안 일어났다.** 모드가 정하는 세 설정(`approval_auto_reversible`·`shell_autorun_enabled`·
`local_write_enabled`)이 `live` 가 아니라서 `SettingsService.patch` 가 **파일에만 저장하고** 실행 중인 설정과 승인 관문에는
반영하지 않았다(응답의 `restart_required` 를 모드 API 가 버렸다). 「계속 눌러야 되는 게 귀찮네」에서 만든 기능이 실제로는
재시작 전까지 안 먹고, 그 이유도 안 알려 주었다 — **조용한 성공**이다.

## 고친 것

1. 세 설정을 `live` 로 — 저장과 동시에 실행 중 설정에 반영된다.
2. 승인 관문(`ToolGateway.auto_approve_reversible`·`write_enabled`)은 생성 때 복사해 둔 값이라 **변경 핸들러가 직접 갱신**한다.
3. 모드 API 는 `change_mode` 한 곳을 거치고, **읽어 본 결과가 고른 모드와 다르면 `ok: False`** 로 돌려준다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from alture_jarvis.config import JarvisConfig
from alture_jarvis.permissions import change_mode, mode_of
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.settings import BY_KEY, SettingsService

_TRIO = ("approval_auto_reversible", "shell_autorun_enabled", "local_write_enabled")


def _service(tmp_path: Path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data")
    gateway = SimpleNamespace(auto_approve_reversible=False, write_enabled=True)
    runtime = SimpleNamespace(
        config=config, gateway=gateway, google=SimpleNamespace(register=lambda *_: None),
        takeover=SimpleNamespace(enabled=False, branch_enabled=False, register=lambda *_: None),
        events=SimpleNamespace(publish=lambda *_a, **_k: None),
    )
    service = SettingsService(config, on_live_change=lambda keys: JarvisRuntime._settings_changed(runtime, keys))
    return config, gateway, service


def test_the_three_permission_settings_are_live() -> None:
    for key in _TRIO:
        assert BY_KEY[key].live, f"{key}: 재시작 전까지 안 먹는 권한은 모드 손잡이가 아니다"


def test_choosing_workspace_changes_the_running_config_and_the_gateway(tmp_path: Path) -> None:
    config, gateway, service = _service(tmp_path)
    assert mode_of(config) == "ask"

    result = change_mode(service, config, "workspace")

    assert result["ok"] is True and result["mode"] == "workspace"
    assert config.approval_auto_reversible is True and config.shell_autorun_enabled is True
    assert gateway.auto_approve_reversible is True, "승인 관문이 생성 때 복사한 값을 그대로 쓰면 카드가 계속 뜬다"


def test_read_only_closes_the_gate_at_once(tmp_path: Path) -> None:
    config, gateway, service = _service(tmp_path)

    result = change_mode(service, config, "read_only")

    assert result["ok"] is True and result["mode"] == "read_only"
    assert gateway.write_enabled is False and gateway.auto_approve_reversible is False


def test_and_back_to_ask(tmp_path: Path) -> None:
    config, gateway, service = _service(tmp_path)
    change_mode(service, config, "workspace")

    result = change_mode(service, config, "ask")

    assert result["mode"] == "ask" and gateway.auto_approve_reversible is False


def test_a_mode_that_did_not_apply_is_not_reported_as_ok(tmp_path: Path) -> None:
    """저장됐다고 적용된 것은 아니다 — 읽어 본 결과가 고른 것과 다르면 조용히 `ok` 라 하지 않는다."""
    config, _gateway, _service_unused = _service(tmp_path)

    class _SavesButDoesNotApply:
        def patch(self, changes):
            return {"ok": True, "applied": [], "restart_required": list(changes)}

    result = change_mode(_SavesButDoesNotApply(), config, "workspace")

    assert result["ok"] is False and result["error"] == "mode_not_applied"
    assert result["mode"] == "ask" and result["wanted"] == "workspace"
    assert result["restart_required"], "왜 안 됐는지(재시작 필요)를 같이 말해야 한다"


def test_a_bad_mode_is_still_refused(tmp_path: Path) -> None:
    config, _gateway, service = _service(tmp_path)

    result = change_mode(service, config, "everything")

    assert result["ok"] is False and "unknown_permission_mode" in result["error"]


def test_the_api_goes_through_change_mode() -> None:
    """엔드포인트가 예전 길(`patch` 를 직접 부르고 `ok` 를 돌려줌)로 남아 있으면 같은 조용한 성공이 산다."""
    import inspect

    from alture_jarvis import api

    source = inspect.getsource(api)
    start = source.index('@app.post("/v1/permissions/mode"')
    endpoint = source[start:start + 600]
    assert "change_mode(" in endpoint
    assert "settings.patch(" not in endpoint, "예전 길(patch 를 직접 부르고 ok 를 돌려줌)이 남았다"
