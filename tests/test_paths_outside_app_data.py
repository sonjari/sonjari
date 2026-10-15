"""밖에서 도는 프로그램이 읽는 자리는 **앱 전용 칸 밖**에 둔다 (2026-09-18 노트북 실측).

스토어판(MSIX)에서 `%LOCALAPPDATA%` 아래에 새로 만든 파일은 앱 전용 칸으로 간다. 우리만 읽으면 괜찮지만
**패키지 밖 실행 파일**(Ollama·크롬)은 그 칸이 안 보인다. 노트북에서 `llama-server.exe` 를 포함해 파일 43개가
멀쩡히 있는데도 Ollama 가 「binary not found」로 모델을 하나도 못 올렸다. 서버는 켜지고 목록도 답해서
고장이 며칠 안 보였고, 화면은 엉뚱하게 그래픽카드 드라이버를 의심하라고 했다.

여기서 재는 것 셋:
1. 패키지 안에서는 그 자리들이 `%LOCALAPPDATA%` 밖이다.
2. 패키지 **밖**(지금 이 PC·개발기)은 쓰던 옛 자리를 그대로 쓴다 — 갑자기 빈 프로필로 시작하지 않는다.
3. 패키지 안에서는 옛 자리가 「있어 보여도」 안 쓴다 — 우리 눈에만 있는 그 폴더가 바로 고장난 자리다.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _config_module(monkeypatch, *, local_app_data: Path, home: Path, packaged: str):
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setenv("JARVIS_FAKE_PACKAGE_FULL_NAME", packaged)
    for name in ("JARVIS_RUNTIME_ROOT", "JARVIS_DATA_DIR", "JARVIS_BROWSER_PROFILE_DIR",
                 "JARVIS_OLLAMA_INSTALL_DIR", "JARVIS_FACE_MODEL_DIR"):
        monkeypatch.delenv(name, raising=False)
    from alture_jarvis import msix

    importlib.reload(msix)
    from alture_jarvis import config as config_module

    importlib.reload(config_module)
    monkeypatch.setattr(config_module.Path, "home", staticmethod(lambda: home))
    return config_module


@pytest.fixture(autouse=True)
def _restore_modules():
    yield
    # 다음 시험이 진짜 환경을 보게 되돌린다(가짜 모듈 누수는 이 저장소가 이미 데인 자리다).
    from alture_jarvis import msix

    importlib.reload(msix)
    from alture_jarvis import config as config_module

    importlib.reload(config_module)


#: 밖의 프로그램이 읽거나(=못 보면 고장) 다시 받기 비싼 자리.
OUTSIDE_FACING = ("ollama_install_dir", "browser_profile_dir", "face_model_dir")


def test_inside_a_package_these_paths_live_in_the_user_folder(tmp_path: Path, monkeypatch) -> None:
    local_app_data, home = tmp_path / "AppData" / "Local", tmp_path / "home"
    config_module = _config_module(monkeypatch, local_app_data=local_app_data, home=home,
                                   packaged="RoboMetaFit.OntelicMsixTest_0.4.0.0_x64__abc")
    config = config_module.JarvisConfig.from_env()
    for name in OUTSIDE_FACING:
        path = Path(getattr(config, name))
        assert home in path.parents, f"{name} 은 사용자 폴더 아래여야 한다: {path}"
        assert local_app_data not in path.parents, f"{name} 이 앱 전용 칸 안이다: {path}"


def test_a_legacy_folder_inside_app_data_is_ignored_when_packaged(tmp_path: Path, monkeypatch) -> None:
    """★ 이것이 노트북에서 벌어진 일이다 — 우리 눈에는 있고 Ollama 눈에는 없는 폴더."""
    local_app_data, home = tmp_path / "AppData" / "Local", tmp_path / "home"
    (local_app_data / "Ontelic" / "data" / "ollama" / "v0.34.1").mkdir(parents=True)
    (local_app_data / "Ontelic" / "data" / "browser-profile").mkdir(parents=True)
    config_module = _config_module(monkeypatch, local_app_data=local_app_data, home=home,
                                   packaged="RoboMetaFit.OntelicMsixTest_0.4.0.0_x64__abc")
    config = config_module.JarvisConfig.from_env()
    assert local_app_data not in Path(config.ollama_install_dir).parents
    assert local_app_data not in Path(config.browser_profile_dir).parents


def test_outside_a_package_the_folder_already_in_use_is_kept(tmp_path: Path, monkeypatch) -> None:
    local_app_data, home = tmp_path / "AppData" / "Local", tmp_path / "home"
    legacy_profile = local_app_data / "Ontelic" / "data" / "browser-profile"
    legacy_profile.mkdir(parents=True)
    config_module = _config_module(monkeypatch, local_app_data=local_app_data, home=home, packaged="")
    config = config_module.JarvisConfig.from_env()
    assert Path(config.browser_profile_dir) == legacy_profile, "쓰던 프로필을 버리면 로그인이 다 날아간다"


def test_a_fresh_pc_outside_a_package_also_uses_the_user_folder(tmp_path: Path, monkeypatch) -> None:
    local_app_data, home = tmp_path / "AppData" / "Local", tmp_path / "home"
    config_module = _config_module(monkeypatch, local_app_data=local_app_data, home=home, packaged="")
    config = config_module.JarvisConfig.from_env()
    for name in OUTSIDE_FACING:
        assert home in Path(getattr(config, name)).parents


def test_the_installer_is_given_that_folder_not_the_app_data_one() -> None:
    import inspect

    from alture_jarvis import runtime

    source = inspect.getsource(runtime)
    assert "install_root=self.config.ollama_install_dir" in source
    assert 'install_root=self.config.data_dir / "ollama"' not in source


#: **밖의 프로그램이 읽거나 쓰는** 자리 전부. 새로 생기면 여기에 넣는다 — 안 넣으면 조용히 같은 병이 난다.
#: (Ollama·크롬·WSL 상자·Open WebUI·탐색기. 얼굴 모델은 다시 받기 비싼 쪽이다.)
EVERY_OUTSIDE_FACING = (
    "ollama_install_dir", "browser_profile_dir", "face_model_dir", "sandbox_output_dir",
    "plopfit_functions_dir", "plopfit_lib_dir", "documents_dir", "browser_download_dir",
    # 「지금 업데이트」 도우미는 앱이 꺼진 뒤 패키지 밖에서 돈다(2026-09-18 밤).
    "store_update_dir",
)


def test_no_outside_facing_folder_sits_in_the_app_private_store(tmp_path: Path, monkeypatch) -> None:
    local_app_data, home = tmp_path / "AppData" / "Local", tmp_path / "home"
    config_module = _config_module(monkeypatch, local_app_data=local_app_data, home=home,
                                   packaged="RoboMetaFit.OntelicMsixTest_0.4.0.0_x64__abc")
    config = config_module.JarvisConfig.from_env()
    for name in EVERY_OUTSIDE_FACING:
        path = Path(getattr(config, name))
        assert local_app_data not in path.parents, (
            f"{name} 이 앱 전용 칸 안이다({path}) — 밖의 프로그램은 그 자리를 못 본다"
        )


def test_opening_a_file_hands_the_shell_the_real_path() -> None:
    """탐색기·워드는 패키지 밖이다 — 가상화된 경로를 주면 아무것도 못 연다."""
    import inspect

    from alture_jarvis import local_computer, runtime

    for source in (inspect.getsource(local_computer.LocalComputerTools._open_now),
                   inspect.getsource(local_computer.LocalComputerTools.open_path)):
        assert "external_path(" in source, source[:200]
    apply_source = inspect.getsource(runtime)
    assert '"-File", str(external_path(script))' in apply_source, "갱신 스크립트는 밖의 PowerShell 이 읽는다"
