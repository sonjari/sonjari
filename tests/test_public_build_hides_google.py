"""구글 연결을 시작할 수 없는 빌드엔 구글을 진열하지 않는다 (2026-10-01).

공개판(스토어) 패키지를 열어 보니 OAuth 클라이언트가 없었다(29,976개 파일 중 0개). 그러면 구글 도구는
처음부터 꺼져 있다. 그런데 화면엔 「구글 · Drive · Gmail · Calendar」 회색 카드와 「이 빌드에는
Google 연결 설정이 포함되지 않았습니다」, 회색 도구 묶음, 설정의 「Google 쓰기」 스위치가 그대로
보였다. 못 쓰는 기능을 진열하면 베타 사용자·스토어 심사자는 「고장」으로 읽는다.

판정은 하나다 — `oauth_client_present`. 도구 등록(`_is_configured`)과 설정 화면이 같은 판정을 쓴다.
화면 쪽(연결 카드·도구 묶음)은 ui/src/workspace/CapabilityDrawer.behavior.test.tsx 가 본다.
"""

from __future__ import annotations

import json
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.google_workspace import oauth_client_present
from alture_jarvis.settings import SettingsService


def _config(tmp_path: Path, *, bundle: dict | None = None, **extra) -> JarvisConfig:
    bundle_path = tmp_path / "resources" / "google_oauth_client.json"
    if bundle is not None:
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        google_oauth_bundle_path=bundle_path,
        google_client_secret_path=tmp_path / "data" / "google" / "client_secret.json",
        **extra,
    )


_DESKTOP_CLIENT = {"installed": {"client_id": "123.apps.googleusercontent.com", "client_secret": "x", "project_id": ""}}


def _setting_keys(config: JarvisConfig) -> set[str]:
    return {row["key"] for row in SettingsService(config).view()["settings"]}


def test_a_build_without_a_client_cannot_start_google(tmp_path: Path) -> None:
    assert oauth_client_present(_config(tmp_path)) is False


def test_a_build_with_a_packaged_client_can(tmp_path: Path) -> None:
    assert oauth_client_present(_config(tmp_path, bundle=_DESKTOP_CLIENT)) is True


def test_a_broken_client_file_is_not_a_client(tmp_path: Path) -> None:
    # 웹 클라이언트(installed 가 없음)는 데스크톱 앱이 못 쓴다 — 있다고 치면 회색 카드가 돌아온다.
    assert oauth_client_present(_config(tmp_path, bundle={"web": {"client_id": "x"}})) is False


def test_google_switched_off_hides_it_even_with_a_client(tmp_path: Path) -> None:
    assert oauth_client_present(_config(tmp_path, bundle=_DESKTOP_CLIENT, google_enabled=False)) is False


def test_the_settings_screen_drops_google_write_in_a_public_build(tmp_path: Path) -> None:
    assert "google_write_enabled" not in _setting_keys(_config(tmp_path))


def test_the_settings_screen_keeps_google_write_when_google_can_start(tmp_path: Path) -> None:
    assert "google_write_enabled" in _setting_keys(_config(tmp_path, bundle=_DESKTOP_CLIENT))
