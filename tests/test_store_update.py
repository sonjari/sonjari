"""스토어 설치에 **새 버전이 있다고 알려 준다** (2026-09-18 사용자 요청).

윈도우가 알아서 갱신하지만 사람에게는 아무 말도 안 한다. 첫 실행 마법사는 한 번만 도니 거기 붙일 수도 없다.
그래서 제품 화면의 업데이트 줄을 스토어 설치까지 넓혔다. 여기서 재는 것: 주소를 코드에 안 박고 윈도우가
기억하는 채널에서 읽는가, 버전을 제대로 견주는가, 못 닿을 때 조용히 「없음」으로 넘어가는가.
"""

from __future__ import annotations

from alture_jarvis import store_update

APPINSTALLER = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<AppInstaller xmlns="http://schemas.microsoft.com/appx/appinstaller/2021"'
    ' Uri="https://example.test/ch/Ontelic.appinstaller" Version="0.4.26261.350">'
    '<MainPackage Name="RoboMetaFit.OntelicMsixTest" Publisher="CN=RoboMetaFit"'
    ' Version="0.4.26261.350" ProcessorArchitecture="x64" Uri="https://example.test/ch/app.msix" />'
    "</AppInstaller>"
).encode("utf-8")

FULL_NAME = "RoboMetaFit.OntelicMsixTest_0.4.26261.206_x64__d8mr8f7kqmcaj"


def _windows_says(version: str, uri: str):
    return lambda _script: '{"version":"%s","uri":"%s"}' % (version, uri)


def test_a_newer_version_on_the_channel_is_reported() -> None:
    found = store_update.check(
        full_name=FULL_NAME,
        run=_windows_says("0.4.26261.206", "https://example.test/ch/Ontelic.appinstaller"),
        fetch=lambda _uri: APPINSTALLER,
    )
    assert found == {"kind": "store", "mine": "0.4.26261.206", "theirs": "0.4.26261.350",
                     "available": True, "how": "restart"}


def test_the_same_version_says_nothing() -> None:
    found = store_update.check(
        full_name=FULL_NAME,
        run=_windows_says("0.4.26261.350", "https://example.test/ch/Ontelic.appinstaller"),
        fetch=lambda _uri: APPINSTALLER,
    )
    assert found["available"] is False


def test_an_install_without_a_channel_is_left_alone() -> None:
    """스토어에서 받은 설치는 스토어가 갱신한다 — 우리가 끼어들지 않는다."""
    found = store_update.check(full_name=FULL_NAME, run=_windows_says("0.4.0.0", ""), fetch=lambda _uri: b"")
    assert found["available"] is False and "채널" in found["reason"]


def test_a_server_we_cannot_reach_is_not_an_error_on_screen() -> None:
    def boom(_uri: str) -> bytes:
        raise OSError("offline")

    found = store_update.check(
        full_name=FULL_NAME,
        run=_windows_says("0.4.26261.206", "https://example.test/ch/Ontelic.appinstaller"),
        fetch=boom,
    )
    assert found["available"] is False and found["reason"]


def test_an_http_channel_is_refused() -> None:
    """갱신 정보를 평문으로 받지 않는다 — 바꿔치기하면 사람을 엉뚱한 버전으로 보낸다."""
    assert store_update.channel_version("http://example.test/ch/Ontelic.appinstaller",
                                        fetch=lambda _uri: APPINSTALLER) == ""


def test_outside_a_package_nothing_happens() -> None:
    assert store_update.check(full_name="") == {"kind": "none", "available": False}


def test_versions_are_compared_as_numbers_not_text() -> None:
    assert store_update.is_newer("0.4.26261.350", "0.4.26261.206") is True
    assert store_update.is_newer("0.4.26261.206", "0.4.26261.350") is False
    assert store_update.is_newer("0.5", "0.4.9.9") is True, "칸 수가 달라도 숫자로 본다"
    assert store_update.is_newer("0.4.26261.206", "0.4.26261.206") is False
    assert store_update.is_newer("", "0.4.0.0") is False


def test_the_product_screen_knows_this_kind() -> None:
    """화면이 「지금 받기」(위성)와 「껐다 켜면 적용」(스토어)을 갈라 그려야 한다."""
    from pathlib import Path

    bar = Path(__file__).resolve().parents[1] / "ui" / "src" / "workspace" / "UpdateBar.tsx"
    source = bar.read_text(encoding="utf-8")
    assert 'status?.kind === "store"' in source
    assert "껐다 켜면" in source


def test_the_wizard_puts_the_repair_button_next_to_the_message() -> None:
    """★ 「아래 「Ollama 다시 설치」를 눌러 주세요」라고 적고 그 버튼은 다른 화면에 있었다(2026-09-18 노트북)."""
    from pathlib import Path

    wizard = Path(__file__).resolve().parents[1] / "ui" / "src" / "setup" / "SetupWizard.tsx"
    source = wizard.read_text(encoding="utf-8")
    assert 'applied.error === "ollama_runner_missing" && api ? <RepairOllamaButton' in source
    assert "function RepairOllamaButton" in source
