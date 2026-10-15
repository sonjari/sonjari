"""포장본에서 읽기 전용 설치 경로와 외부 경로를 실제 호출 문으로 확인한다."""
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.windows_automation import WindowsAutomationTools
from alture_jarvis import diagnostics, msix


@pytest.mark.skipif(sys.platform != 'win32', reason='윈도우 창 읽기 경로')
def test_desktop_redirects_comtypes_before_pywinauto_generates(monkeypatch, tmp_path):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path/'data', output_dir=tmp_path/'out')
    client = ModuleType('comtypes.client')
    client.gen_dir = str(tmp_path/'WindowsApps'/'comtypes'/'gen')
    gen = ModuleType('comtypes.gen')
    gen.__path__ = [client.gen_dir]
    package = ModuleType('comtypes')
    package.client, package.gen = client, gen
    for name, module in [('comtypes', package), ('comtypes.client', client), ('comtypes.gen', gen)]:
        monkeypatch.setitem(sys.modules, name, module)
    fake = ModuleType('pywinauto')

    def desktop(**kwargs):
        assert Path(client.gen_dir).is_relative_to(config.data_dir)
        assert client.gen_dir in gen.__path__
        Path(client.gen_dir, 'UIAutomationClient.py').write_text('# 생성 성공', encoding='utf-8')
        return '창 읽기 성공'

    fake.Desktop = desktop
    monkeypatch.setitem(sys.modules, 'pywinauto', fake)
    assert WindowsAutomationTools(config)._desktop() == '창 읽기 성공'


def test_export_returns_the_path_an_outside_program_can_read(monkeypatch, tmp_path):
    logical = tmp_path/'Local'/'Ontelic'/'outputs'
    external = tmp_path/'Packages'/'Ontelic'/'LocalCache'
    external.mkdir(parents=True)
    monkeypatch.setattr(diagnostics, 'build_bundle', lambda _: {'health': {'ok': True}})
    monkeypatch.setattr(msix, 'external_path', lambda path: external/Path(path).name)
    result = diagnostics.export_bundle(SimpleNamespace(config=SimpleNamespace(output_dir=logical)))
    assert Path(result['path']).parent == external
