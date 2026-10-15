"""스토어판 **「지금 업데이트」** — 앱 밖 도우미가 깔고 다시 연다 (2026-09-18 밤 사용자 요청).

예전에는 「껐다 켜면 윈도우가 바꿔 줍니다」라는 글뿐이었고, 윈도우는 **다음에 켤 때** 바꿔서 두 번 켜야 할
때가 있었다. 스토어판은 실행 중인 자기를 못 바꾸므로 설치·다시 열기는 앱 밖 도우미가 한다.

실측(개발용 등록한 실제 포장 앱): 앱 안에서 띄운 도우미 셋(자식·WMI·작업 스케줄러)이 앱을 강제로 끈 뒤에도
모두 살아 있었고, 바깥에서 shell:AppsFolder 로 다시 여니 1초 만에 떴다.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import store_update

FULL = "RoboMetaFit.OntelicMsixTest_0.4.26261.2203_x64__d8mr8f7kqmcaj"
URI = "https://api.robometafit.com/ontelic/update/abc/Ontelic.appinstaller"
# 실제 채널 파일 모양 그대로(`publish_update_channel.ps1`) — 바깥 Version 과 패키지 Version 이 같다.
CHANNEL = (
    b'<?xml version="1.0" encoding="utf-8"?><AppInstaller Uri="https://x/Ontelic.appinstaller" Version="0.4.26261.2330" '
    b'xmlns="http://schemas.microsoft.com/appx/appinstaller/2021">'
    b'<MainPackage Name="RoboMetaFit.OntelicMsixTest" Publisher="CN=RoboMetaFit" Version="0.4.26261.2330" '
    b'ProcessorArchitecture="x64" Uri="https://x/a.msix" /></AppInstaller>'
)


def test_the_family_name_is_what_windows_opens_the_app_by() -> None:
    assert store_update.family_of(FULL) == "RoboMetaFit.OntelicMsixTest_d8mr8f7kqmcaj"
    assert store_update.family_of("") == ""


def test_the_helper_uses_the_channel_and_the_real_switch_names() -> None:
    """★ 스위치 이름은 `Get-Command Add-AppxPackage -Syntax` 로 **재 보고** 썼다. 짐작한 `-ForceApplicationShutdown`
    은 이 매개변수 묶음에 없다 — 그걸 썼으면 도우미가 매번 실패하고 조용히 옛 판을 다시 열었을 것이다."""
    script = store_update.helper_script(uri=URI, name="N", family="N_p", mine="1", theirs="2",
                                        result_dir=r"C:\Users\사용자\Ontelic\update")
    assert f"-Path '{URI}' -AppInstallerFile -ForceTargetApplicationShutdown" in script
    assert "-ForceApplicationShutdown" not in script.replace("-ForceTargetApplicationShutdown", "")
    # 성공하든 실패하든 다시 연다 — 실패해서 창이 사라진 채로 남으면 그게 제일 나쁘다.
    assert script.rstrip().endswith("Start-Process explorer.exe 'shell:AppsFolder\\N_p!App'")
    assert "phase = 'done'" in script and "error = $err" in script


def test_quotes_in_values_cannot_break_out_of_the_script() -> None:
    script = store_update.helper_script(uri="https://x/a'b", name="N", family="N_p", mine="1", theirs="2",
                                        result_dir="C:/x")
    assert "https://x/a''b" in script


def test_the_helper_is_started_through_wmi_with_an_encoded_command() -> None:
    """부모가 윈도우 서비스인 프로세스 — 앱이 꺼져도 산다. 경로 인자를 안 넘겨 한글 경로가 깨질 자리가 없다(J-2)."""
    seen: list[str] = []

    def run(command: str) -> str:
        seen.append(command)
        return "0\n"

    assert store_update._spawn_outside("Write-Output '한글 경로 C:\\Users\\박가람'", run=run) == "0"
    launcher = seen[0]
    assert "Invoke-CimMethod -ClassName Win32_Process -MethodName Create" in launcher
    encoded = launcher.split("-EncodedCommand ", 1)[1].split("'", 1)[0]
    assert "박가람" in base64.b64decode(encoded).decode("utf-16-le")


def _fakes(version: str = "0.4.26261.2203", uri: str = URI) -> tuple[Any, Any, list[str]]:
    calls: list[str] = []

    def run(command: str) -> str:
        calls.append(command)
        if "Get-AppxPackage" in command:
            return json.dumps({"version": version, "uri": uri})
        return "0"

    return run, (lambda _url: CHANNEL), calls


def test_apply_starts_the_helper_when_a_newer_version_exists(tmp_path: Path) -> None:
    run, fetch, calls = _fakes()
    out = store_update.apply(str(tmp_path), run=run, fetch=fetch, full_name=FULL)
    assert out["applied"] is True and out["theirs"] == "0.4.26261.2330"
    assert any("Win32_Process" in call for call in calls)


def test_apply_does_nothing_when_already_current(tmp_path: Path) -> None:
    run, fetch, calls = _fakes(version="0.4.26261.2330")
    out = store_update.apply(str(tmp_path), run=run, fetch=fetch, full_name=FULL)
    assert out["applied"] is False
    assert not any("Win32_Process" in call for call in calls), "최신인데 앱을 끄면 그것이 곧 고장이다"


def test_apply_outside_a_package_is_a_no(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store_update, "package_full_name", lambda: "")
    assert store_update.apply(str(tmp_path))["applied"] is False


def test_a_failed_wmi_start_is_reported_not_swallowed(tmp_path: Path) -> None:
    run, fetch, _ = _fakes()

    def failing(command: str) -> str:
        return "9" if "Win32_Process" in command else run(command)

    out = store_update.apply(str(tmp_path), run=failing, fetch=fetch, full_name=FULL)
    assert out["ok"] is False and "WMI 9" in out["reason"]


def test_the_result_is_shown_once_and_failures_too(tmp_path: Path) -> None:
    path = tmp_path / store_update.RESULT_NAME
    # 도우미는 PowerShell 5.1 의 Set-Content -Encoding UTF8 로 쓴다 — BOM 이 붙는다.
    path.write_text(json.dumps({"phase": "done", "ok": False, "from": "1", "to": "2", "installed": "1",
                                "error": "0x80073CF9", "shown": False}), encoding="utf-8-sig")
    first = store_update.last_result(str(tmp_path))
    assert first["ok"] is False and first["error"] == "0x80073CF9", "실패도 알린다 — 조용히 옛 판이면 된 줄 안다"
    store_update.mark_shown(str(tmp_path))
    assert store_update.last_result(str(tmp_path)) == {}


def test_a_half_written_result_is_not_shown(tmp_path: Path) -> None:
    (tmp_path / store_update.RESULT_NAME).write_text(json.dumps({"phase": "installing"}), encoding="utf-8")
    assert store_update.last_result(str(tmp_path)) == {}


def test_the_runtime_routes_the_button_to_the_store_path_inside_a_package() -> None:
    import inspect

    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime.update_apply)
    assert "store_update.apply(str(self.config.store_update_dir))" in source
    check = inspect.getsource(JarvisRuntime.update_check)
    assert "just_updated" in check and "mark_shown" in check


# ── 파일로 직접 깐 설치에도 채널이 있어야 한다 (2026-09-20 노트북 실측) ─────────────────────────
#
# 노트북 0.4.26261.2230 은 .msix 를 받아 직접 깔았다 → 윈도우가 기억하는 .appinstaller 주소가 없다 →
# `check` 가 「이 설치에는 업데이트 채널이 없습니다」 → **업데이트 버튼이 영영 안 뜬다.**
# 빌드가 그 판이 올라간 채널 주소를 패키지 안에 적어 두고(`update_channel.txt`), 윈도우가 모를 때만 그걸 쓴다.


def test_a_bare_msix_install_falls_back_to_the_channel_baked_at_build(tmp_path: Path, monkeypatch) -> None:
    baked = tmp_path / "update_channel.txt"
    baked.write_text(URI + "\n", encoding="ascii")
    monkeypatch.setattr(store_update, "_BAKED_CHANNEL", baked)
    run, fetch, _ = _fakes(uri="")
    state = store_update.check(run=run, fetch=fetch, full_name=FULL)
    assert state["available"] is True and state["theirs"] == "0.4.26261.2330"
    out = store_update.apply(str(tmp_path), run=run, fetch=fetch, full_name=FULL)
    assert out["applied"] is True


def test_windows_own_channel_wins_over_the_baked_one(tmp_path: Path, monkeypatch) -> None:
    baked = tmp_path / "update_channel.txt"
    baked.write_text("https://elsewhere.example/Ontelic.appinstaller", encoding="ascii")
    monkeypatch.setattr(store_update, "_BAKED_CHANNEL", baked)
    run, _fetch, _ = _fakes()
    assert store_update.installed(FULL, run=run)["uri"] == URI


def test_no_channel_anywhere_is_still_said_plainly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store_update, "_BAKED_CHANNEL", tmp_path / "missing.txt")
    run, fetch, _ = _fakes(uri="")
    assert store_update.check(run=run, fetch=fetch, full_name=FULL)["reason"] == "이 설치에는 업데이트 채널이 없습니다"


def test_a_baked_channel_must_be_https(tmp_path: Path, monkeypatch) -> None:
    baked = tmp_path / "update_channel.txt"
    baked.write_text("http://x/Ontelic.appinstaller", encoding="ascii")
    monkeypatch.setattr(store_update, "_BAKED_CHANNEL", baked)
    run, _fetch, _ = _fakes(uri="")
    assert store_update.installed(FULL, run=run)["uri"] == ""


def test_the_publish_script_bakes_the_channel_it_publishes_to() -> None:
    here = Path(__file__).resolve().parents[1] / "packaging" / "msix"
    if not (here / "publish_update_channel.ps1").is_file() and (here.parents[1] / ".sonjari-public-export").is_file():
        pytest.skip("채널에 올리는 스크립트는 공개본에 없다(우리 운영 도구)")
    publish = (here / "publish_update_channel.ps1").read_text(encoding="utf-8")
    build = (here / "build_app_package.ps1").read_text(encoding="utf-8")
    assert '-UpdateChannel "$channelUrl/Ontelic.appinstaller"' in publish
    assert 'alture_jarvis\\update_channel.txt' in build


def test_the_channel_is_asked_through_winrt_not_the_appx_cmdlet_object() -> None:
    """★ 2026-09-20 노트북: `(Get-AppxPackage X).GetAppInstallerInfo()` 는 파워셸 5.1 에서 **없는 메서드**다 —
    확인이 모든 PC 에서 늘 「채널 없음」이었다. 가짜 `run` 시험은 이걸 못 잡았다(스크립트를 안 돌리니까).
    WinRT `PackageManager.FindPackageForUser(...).GetAppInstallerInfo()` 는 노트북에서 실제 주소를 돌려줬다."""
    script = store_update._PS_APPINSTALLER
    assert "$p.GetAppInstallerInfo()" not in script
    assert "Windows.Management.Deployment.PackageManager" in script and "FindPackageForUser" in script


def test_the_query_script_runs_on_this_windows(tmp_path: Path) -> None:
    """스크립트가 파워셸에서 **문법 오류 없이 돈다** — 없는 패키지 이름이면 조용히 빈 출력."""
    import os

    import pytest

    if os.name != "nt":
        pytest.skip("windows only")
    out = store_update._run_powershell(store_update._PS_APPINSTALLER.format(name="No.Such.Package.Ontelic"))
    assert out.strip() == ""
