"""Public-install boundaries introduced by the 2026-09-14 productization pass."""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.agent import AgentToolCatalog
from alture_jarvis.config import JarvisConfig, _default_local_roots
from alture_jarvis.events import EventBus
from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.google_workspace import GoogleWorkspace
from alture_jarvis.google_workspace import DRIVE_FILE_SCOPE, RESTRICTED_SCOPES, _READ_ONLY_SCOPES, _WRITE_SCOPES
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.plopfit import PlopfitTools


def _google(config: JarvisConfig, tmp_path: Path) -> GoogleWorkspace:
    return GoogleWorkspace(
        config,
        EventBus(),
        local_computer=LocalComputerTools(config),
        actions=ExternalActionStore(tmp_path / "data" / "jarvis.db"),
    )


def test_public_defaults_are_machine_neutral_and_private_apps_are_opt_in(
    monkeypatch,
) -> None:
    for key in (
        "JARVIS_OLLAMA_MODEL",
        "JARVIS_OLLAMA_CHAT_MODEL",
        "JARVIS_OLLAMA_VISION_MODEL",
        "JARVIS_USER_LABEL",
        "JARVIS_INHOUSE_DATA_ENABLED",
        "JARVIS_INHOUSE_API_BASE",
        "JARVIS_INHOUSE_API_HEADER",
        "JARVIS_INHOUSE_TENANT_ID",
        "JARVIS_PLOPFIT_ENABLED",
        "JARVIS_CAMERA_ENABLED",
        "JARVIS_FACE_RECOGNITION_ENABLED",
        "JARVIS_STT_DEVICE_INDEX",
        "JARVIS_VISION_DEVICE",
        "JARVIS_SELF_CHECK_EXPECTED_GPUS",
        "JARVIS_NAVER_BLOG_ENABLED",
        "JARVIS_PRIVATE_UPDATE_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    config = JarvisConfig.from_env()

    assert config.model_for("chat") == "gemma4:26b-a4b-it-qat"
    assert config.model_for("vision") == "gemma4:26b-a4b-it-qat"
    assert config.user_label == ""
    assert config.inhouse_data_enabled is False
    assert config.inhouse_api_base == ""
    assert config.inhouse_api_header == "X-API-Key"
    assert config.inhouse_tenant_id == ""
    assert config.plopfit_enabled is False
    assert config.camera_enabled is False
    assert config.face_recognition_enabled is False
    assert config.stt_device_index == 0
    assert config.vision_device == "cuda:0"
    assert config.self_check_expected_gpus == 0
    assert config.naver_blog_enabled is False
    assert config.private_update_enabled is False
    assert "monorepo" not in _default_local_roots()


def test_private_integrations_do_not_enter_the_agent_catalog_by_default(tmp_path: Path) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        google_oauth_bundle_path=tmp_path / "missing-google-client.json",
        google_client_secret_path=tmp_path / "missing-legacy-client.json",
    )
    google = _google(config, tmp_path)
    plopfit = PlopfitTools(config)

    assert google.ollama_tools  # schemas remain inspectable for contract tests
    assert google.active_ollama_tools == []
    assert plopfit.ollama_tools
    assert plopfit.active_ollama_tools == []
    assert AgentToolCatalog(google, plopfit).ollama_tools == []


def test_packaged_google_desktop_client_enables_google_without_user_console_setup(
    tmp_path: Path,
) -> None:
    bundled = tmp_path / "resources" / "google_oauth_client.json"
    bundled.parent.mkdir(parents=True)
    bundled.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "public-desktop.apps.googleusercontent.com",
                    "project_id": "public-product",
                }
            }
        ),
        encoding="utf-8",
    )
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        google_oauth_bundle_path=bundled,
        google_client_secret_path=tmp_path / "missing-legacy-client.json",
    )
    google = _google(config, tmp_path)

    status = google.status()
    assert status["configured"] is True
    assert status["credential_source"] == "packaged_file"
    assert status["project_id"] == "public-product"
    assert google.active_ollama_tools
    # ★ 공개판은 제한 권한(드라이브 전체·지메일 읽기)을 요청하지 않는다 — CASA 연례 평가 대상(인수인계 H4).
    assert set(google._requested_scopes()) == (set(_READ_ONLY_SCOPES) - set(RESTRICTED_SCOPES)) | {DRIVE_FILE_SCOPE}
    gmail = google.gmail_search({"query": "견적서"})
    assert gmail["available"] is False and "mail.google.com" in gmail["next"]
    config.google_write_enabled = True
    assert set(google._requested_scopes()) == set(_READ_ONLY_SCOPES + _WRITE_SCOPES) - set(RESTRICTED_SCOPES)
    config.google_restricted_scopes_enabled = True  # 사내 설치
    assert set(google._requested_scopes()) == set(_READ_ONLY_SCOPES + _WRITE_SCOPES)
    assert "client_secret" not in google._token_form(
        google._credentials(), grant_type="refresh_token", refresh_token="fake"
    )


def test_public_config_never_exposes_google_client_secret(tmp_path: Path) -> None:
    config = JarvisConfig(
        runtime_root=tmp_path,
        google_oauth_client_id="public-id",
        google_oauth_client_secret="not-for-the-ui",
    )

    assert "google_oauth_client_secret" not in config.public_dict()


def test_runtime_launcher_does_not_force_private_machine_capabilities() -> None:
    source = (Path(__file__).parents[1] / "scripts" / "task_entry.py").read_text(
        encoding="utf-8"
    )

    assert 'JARVIS_GOOGLE_WRITE_ENABLED", "true"' not in source
    assert 'JARVIS_BROWSER_READ_ONLY", "false"' not in source
    assert 'JARVIS_CAMERA_CONTROL_ENABLED", "true"' not in source
    assert "CUDA_VISIBLE_DEVICES" not in source


def test_shipped_source_has_no_personal_or_machine_specific_markers() -> None:
    root = Path(__file__).parents[1]
    files = [
        *sorted((root / "src").rglob("*.py")),
        *sorted((root / "ui" / "src").rglob("*.ts")),
        *sorted((root / "ui" / "src").rglob("*.tsx")),
        *sorted((root / "ui" / "src-tauri" / "src").rglob("*.rs")),
        # ★ 포장본에 자료로 실린다(2026-09-16부터) — 코드만 보면 여기서 샌다.
        *sorted((root / "recipes").glob("*.json")),
        *sorted((root / "skills").glob("*.json")),
    ]
    body = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for marker in (
        "사용자님",
        "박가람",
        # 회사·학원 도메인은 제품 기본값이 아니다 — 그 PC 사용자의 기억에 산다(2026-09-16 밤).
        "알튜어",
        "로보메타핏",
        "sample-owner-id",
        "192.168.0.",
        r"C:\work\monorepo",
        r"C:\RoboMetaFit",
        "RoboMetaFit-Alture-Jarvis",
        "X-ROBOMETAFIT-API-KEY",
    ):
        assert marker not in body


def test_rehearsal_fixtures_use_reserved_example_addresses_only() -> None:
    """리허설 화면은 캡처돼 문서로 나간다. 실제 주소를 가려 쓴 것(`ab••••@gmail.com`)도 실제 주소에서 온 것이다."""
    import re

    root = Path(__file__).parents[1] / "ui" / "src" / "fixtures"
    body = "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.rglob("*.ts")))
    addresses = re.findall(r"[\w.+•-]+@[\w-]+(?:\.[\w-]+)+", body)
    assert addresses, "fixture 에 메일 주소가 하나도 없으면 이 검사가 아무것도 안 본다"
    leaked = sorted({a for a in addresses if not re.search(r"@example\.(com|org|net)$", a)})
    assert leaked == []
