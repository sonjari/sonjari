"""화면 자동화 부품의 COM 정의는 이 PC 용 캐시를 먼저 찾고, 실패한 불러오기는 되풀이하지 않는다 (2026-10-14).

부산 노트북에서 백엔드가 5분에 100MB 씩 늘었다. 꾸러미에 든 UIAutomation 정의(굽는 PC 에서 만든 9,224줄)의
마지막 줄이 「이 PC 의 UIAutomationCore.dll 시각이 만든 PC 와 같은가」를 검사한다. 다른 PC 에서는 다 실행된 뒤
마지막 줄에서 실패하고, 만든 클래스는 ctypes 캐시에 영영 남는다. comtypes 가 이 PC 용을 새로 만들어 캐시 폴더에
써도 그 폴더가 뒤에 있어 꾸러미 것이 또 먼저 잡혔다 — `/health` 마다 되풀이(세 번에 물건 7만 7천 개).
같은 까닭으로 굽는 PC 밖에서는 윈도우 화면 자동화가 늘 「부품 없음」이었다.

지키는 약속:
- `_prepare_com_cache` 는 캐시 폴더를 `comtypes.gen.__path__` 의 **맨 앞**에 둔다. 이미 뒤에 있으면 앞으로 옮긴다.
- `_dependency_ready` 는 성공을 기억하고, 실패는 10분 동안 다시 시도하지 않는다. 실패 문장은 `status()` 의
  `dependency_error` 로 보인다.
"""

from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.windows_automation import WindowsAutomationTools


def _tools(tmp_path: Path) -> WindowsAutomationTools:
    config = JarvisConfig.from_env()
    object.__setattr__(config, "data_dir", tmp_path / "data")
    object.__setattr__(config, "output_dir", tmp_path / "out")
    return WindowsAutomationTools(config)


def _fake_comtypes(monkeypatch: pytest.MonkeyPatch, paths: list[str]) -> types.ModuleType:
    comtypes = types.ModuleType("comtypes")
    client = types.ModuleType("comtypes.client")
    client.gen_dir = None
    gen = types.ModuleType("comtypes.gen")
    gen.__path__ = paths
    comtypes.client, comtypes.gen = client, gen
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)
    monkeypatch.setitem(sys.modules, "comtypes.gen", gen)
    return gen


@pytest.mark.skipif(sys.platform != "win32", reason="windows_only")
def test_the_cache_folder_is_searched_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(tmp_path)
    cache = str(tools.config.data_dir / "comtypes-cache")
    gen = _fake_comtypes(monkeypatch, [r"C:\package\comtypes\gen", cache])
    tools._prepare_com_cache()
    assert gen.__path__[0] == cache and gen.__path__.count(cache) == 1
    assert sys.modules["comtypes.client"].gen_dir == cache

    gen = _fake_comtypes(monkeypatch, [r"C:\package\comtypes\gen"])
    tools._prepare_com_cache()
    tools._prepare_com_cache()
    assert gen.__path__ == [cache, r"C:\package\comtypes\gen"]


def test_a_failed_import_is_not_retried_on_every_health_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _tools(tmp_path)
    monkeypatch.setattr(tools, "_prepare_com_cache", lambda: None)
    monkeypatch.delitem(sys.modules, "pywinauto", raising=False)
    tries = []
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pywinauto":
            tries.append(name)
            raise ImportError("Typelib different than module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    first = tools.status()
    for _ in range(5):
        tools.status()
    assert len(tries) == 1
    assert first["dependency"] is False
    assert "Typelib different than module" in first["dependency_error"]

    tools._dependency = (tools._dependency[0] - tools._DEPENDENCY_RETRY_SEC - 1, False, "old")
    tools.status()
    assert len(tries) == 2
