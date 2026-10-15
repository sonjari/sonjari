"""기본값 표시만 바꾸던 reset과 재기동 우선순위를 실제 소비자에서 확인한다."""
import math
import json
import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.settings import SettingsService, validate, SettingsError


def config(tmp_path, **kwargs):
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path/'data', output_dir=tmp_path/'out', **kwargs)


@pytest.mark.parametrize('key,bad,expected', [('voice_enabled', 'false', False),
                                           ('ollama_max_tool_steps', '열둘', 12)])
def test_corrupt_saved_setting_is_displayed_as_the_actual_default(tmp_path, key, bad, expected):
    folder = tmp_path/'data'
    folder.mkdir()
    (folder/'settings.json').write_text(json.dumps({'values': {key: bad}}), encoding='utf-8')
    service = SettingsService(config(tmp_path, voice_enabled=False, ollama_max_tool_steps=12))
    row = next(r for r in service.view()['settings'] if r['key'] == key)
    assert row['value'] == expected
    assert row['source'] == 'default'
    assert not row['restart_required']


def test_reset_restores_the_name_used_in_the_system_prompt(tmp_path):
    from alture_jarvis.runtime import JarvisRuntime
    runtime = JarvisRuntime(config(tmp_path, user_label='관리호칭', voice_enabled=False, tts_enabled=False))
    runtime.settings.patch({'user_label': '직접호칭'})
    assert '직접호칭' in runtime._system_prompt()
    result = runtime.settings.reset(['user_label'])
    assert '관리호칭' in runtime._system_prompt() and '직접호칭' not in runtime._system_prompt()
    assert result['restart_required'] == []


def test_reset_after_restart_still_knows_the_managed_default(tmp_path):
    SettingsService(config(tmp_path, user_label='관리호칭')).patch({'user_label': '직접호칭'})
    service = SettingsService(config(tmp_path, user_label='관리호칭'))
    service.reset(['user_label'])
    assert service.config.user_label == '관리호칭'


def test_reset_of_restart_only_setting_reports_the_real_pending_default(tmp_path):
    SettingsService(config(tmp_path, voice_enabled=True)).patch({'voice_enabled': False})
    service = SettingsService(config(tmp_path, voice_enabled=True))
    result = service.reset(['voice_enabled'])
    row = next(r for r in result['settings'] if r['key'] == 'voice_enabled')
    assert row['value'] is True and row['restart_required']
    assert service.config.voice_enabled is False
    assert result['restart_required'] == ['voice_enabled']


@pytest.mark.parametrize('number', [math.nan, math.inf, -math.inf])
def test_bad_numeric_input_is_a_validation_error_not_an_api_crash(number):
    with pytest.raises(SettingsError, match='expected_int'):
        validate('ollama_max_tool_steps', number)


def test_reset_validates_the_whole_batch_before_removing_anything(tmp_path):
    service = SettingsService(config(tmp_path))
    service.patch({'user_label': '유지'})
    result = service.reset(['user_label', 'control_token'])
    assert not result['ok'] and service.config.user_label == '유지'


def test_google_write_toggle_changes_the_registered_tool_availability(tmp_path, monkeypatch):
    from alture_jarvis.runtime import JarvisRuntime
    runtime = JarvisRuntime(config(tmp_path, google_enabled=True, google_write_enabled=False,
                                   voice_enabled=False, tts_enabled=False))
    monkeypatch.setattr(runtime.google, '_is_configured', lambda: True)
    runtime.google.register(runtime.gateway)
    runtime.settings.patch({'google_write_enabled': True})
    assert runtime.config.google_write_enabled
    assert next(t for t in runtime.gateway.list_tools() if t['name'] == 'google_gmail_send')['enabled']
    runtime.settings.reset(['google_write_enabled'])
    assert not runtime.config.google_write_enabled
    assert not next(t for t in runtime.gateway.list_tools() if t['name'] == 'google_gmail_send')['enabled']
