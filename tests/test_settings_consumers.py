"""32칸 저장 → 실행 소비자 눈금. 장치·외부 계정은 건드리지 않는다."""
from types import SimpleNamespace
from pathlib import Path
import tempfile
import time

import httpx
import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime
from alture_jarvis.settings import BY_KEY
from alture_jarvis.agent import _should_think
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolSpec
from alture_jarvis.skills import SkillDoc


CHANGES = {
    'user_label': '새호칭', 'attention_notices_enabled': True, 'scheduler_enabled': True,
    'model_chat': 'changed-chat:latest', 'model_code': 'changed-code:latest',
    'model_vision': 'changed-vision:latest', 'ollama_num_ctx': 32768,
    'agent_thinking_policy': 'off', 'ollama_max_tool_steps': 20,
    'voice_enabled': True, 'tts_enabled': True, 'supertonic_voice': 'M2',
    'hotkey_enabled': True, 'hotkey': 'f10', 'media_pause_enabled': True,
    'memory_retrieval_enabled': True, 'fact_learning_enabled': True,
    'memory_backup_enabled': True, 'local_file_allowed_roots': None,
    'shell_autorun_enabled': True,
    'local_write_enabled': False,
    'local_read_roots': None,
    'browser_enabled': True, 'browser_read_only': True, 'google_write_enabled': True,
    'windows_control_enabled': True, 'approval_ttl_sec': 900,
    'approval_auto_reversible': True, 'approval_bypass_enabled': True, 'takeover_enabled': True,
    'takeover_branch_enabled': True, 'skills_route_enabled': True,
    'skills_domains': ['dev'], 'claude_code_enabled': True,
    'sandbox_enabled': True, 'code_scout_enabled': True,
    'scribe_enabled': True, 'scribe_folders': ['C:/scribe-probe'],
    'api_escalation_enabled': True, 'api_escalation_model': 'claude-haiku-5-5', 'api_escalation_monthly_usd': 50,
}


class OfflineClient:
    calls = []
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get(self, url, **kwargs):
        return httpx.Response(200, json={'models': []}, request=httpx.Request('GET', url))
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs.get('json', {})))
        return httpx.Response(200, json={'message': {'content': '시험 답'}},
                              content=None, request=httpx.Request('POST', url))


def enabled_tool(runtime, name):
    return next(t['enabled'] for t in runtime.gateway.list_tools() if t['name'] == name)


def consumer(runtime, key, monkeypatch, tmp_path):
    """설정 객체의 속성 대신 실행 경계·요청·등록·분기 결과를 관찰한다."""
    if key == 'user_label':
        return runtime._system_prompt()
    if key == 'attention_notices_enabled':
        runtime.attention.notifications = None
        runtime.attention.speak = None
        return runtime.attention.announce(code='시험', title='시험', message='시험', speech='시험') is not None
    if key == 'scheduler_enabled':
        try:
            runtime.scheduler.create({'prompt': '시험', 'delay_minutes': 1})
            return True
        except RuntimeError:
            return False
    if key.startswith('model_'):
        monkeypatch.setattr(runtime.ollama, '_make_room_for', lambda *_: None)
        monkeypatch.setattr(runtime.ollama, '_resident_context', lambda *_: 0)
        captured = []
        def post(client, body):
            captured.append(body)
            return httpx.Response(200, json={'message': {'content': '시험'}},
                                  request=httpx.Request('POST', 'http://offline/api/chat'))
        monkeypatch.setattr(runtime.ollama, '_post_chat', post)
        runtime.ollama.chat_message('시험', role=key.removeprefix('model_'))
        return captured[-1]['model']
    if key == 'ollama_num_ctx':
        return runtime.ollama._options(.1, model=runtime.config.model_for('chat'),
                                      force_preferred=True)['num_ctx']
    if key == 'agent_thinking_policy':
        return _should_think(runtime.agent.config, [])
    if key == 'ollama_max_tool_steps':
        return runtime.agent._step_budget([])
    if key == 'voice_enabled':
        loaded = []
        monkeypatch.setattr(runtime.stt, '_load', lambda: loaded.append(True))
        runtime.stt.warmup()
        return bool(loaded)
    if key == 'tts_enabled':
        requested = []
        monkeypatch.setattr(runtime.tts, '_request_audio', lambda *_: requested.append(True))
        runtime.tts.warmup()
        return bool(requested)
    if key == 'supertonic_voice':
        runtime.tts._request_audio('시험')
        return OfflineClient.calls[-1][1]['voice']
    if key in {'hotkey_enabled', 'hotkey'}:
        calls = []
        monkeypatch.setattr(runtime.hotkey, '_native_supported', lambda: True)
        def register():
            calls.append(runtime.hotkey.config.hotkey)
            return {'enabled': True}
        monkeypatch.setattr(runtime.hotkey, '_start_windows_hotkey', register)
        runtime.hotkey.start()
        return calls[-1] if calls else None
    if key == 'media_pause_enabled':
        paused = []
        monkeypatch.setattr(runtime.media.backend, 'pause_playing', lambda *_: paused.append(True) or [])
        runtime.media.pause_for_interaction()
        return bool(paused)
    if key == 'memory_retrieval_enabled':
        query = []
        monkeypatch.setattr(runtime.memory, 'context_messages', lambda *_, **kw: query.append(kw['query']) or [])
        runtime._memory_context('실제대화', '관련 질문')
        return query[-1]
    if key == 'fact_learning_enabled':
        from alture_jarvis import fact_extract
        monkeypatch.setattr(fact_extract, 'worth_extracting', lambda *_: True)
        called = []
        monkeypatch.setattr(runtime.ollama, 'chat', lambda *_, **__: called.append(True) or '[]')
        runtime._learn_facts('실제대화', '나는 부산에 살아요.', '알겠습니다.', 1, 2)
        return bool(called)
    if key == 'memory_backup_enabled':
        return runtime.backup.create('시험').get('ok', False)
    if key == 'local_file_allowed_roots':
        # ★ 2026-09-20: 이 설정은 이제 **쓰기** 범위다. 읽기로 재면 tmp_path 가 사용자 폴더 아래라
        #   설정을 바꾸기 전에도 통과해 버린다(`True != True` 로 이 시험이 실제로 잡았다).
        path = tmp_path/'allowed'/'sample.txt'
        path.parent.mkdir(exist_ok=True)
        path.write_text('읽을 자료', encoding='utf-8')
        try:
            return runtime.local_computer._resolve(str(path), write=True) == path
        except (ValueError, PermissionError):
            return False
    if key == 'shell_autorun_enabled':
        # 이 설정이 지배하는 것은 **바꾸는 셸 명령의 등급**이다.
        # (`RiskLevel` 은 파일 위에서 이미 가져온다 — 여기서 또 import 하면 그 이름이
        #  함수 지역변수가 되어 아래 다른 가지들이 UnboundLocalError 로 죽는다. 실제로 죽였다.)
        return runtime.local_computer._shell_risk({'command': 'Remove-Item x.txt'}) == RiskLevel.L1
    if key == 'local_read_roots':
        # 읽기 범위. 사용자 폴더 **밖**에 두어야 설정이 실제로 일하는지 보인다.
        outside = Path(tempfile.gettempdir()).resolve()/'ontelic-read-roots-probe'
        outside.mkdir(exist_ok=True)
        (outside/'sample.txt').write_text('읽을 자료', encoding='utf-8')
        try:
            return runtime.local_computer._resolve(str(outside/'sample.txt')) == (outside/'sample.txt')
        except (ValueError, PermissionError):
            return False
    tool_keys = {'browser_enabled': 'browser_open', 'google_write_enabled': 'google_gmail_send',
                 'windows_control_enabled': 'windows_uia_snapshot', 'claude_code_enabled': 'claude_code_delegate',
                 'sandbox_enabled': 'sandbox_run', 'takeover_enabled': 'takeover_resume_prompt'}
    if key in tool_keys:
        return enabled_tool(runtime, tool_keys[key])
    if key == 'browser_read_only':
        pressed = []
        monkeypatch.setattr(runtime.browser, '_ref_locator', lambda *_: SimpleNamespace(press=lambda *_: pressed.append(True)))
        monkeypatch.setattr(runtime.browser, '_evidence', lambda *_, **__: {})
        try:
            runtime.browser._press(None, {'ref': '試験', 'key': 'Enter'})
        except RuntimeError:
            pass
        return bool(pressed)
    if key == 'approval_ttl_sec':
        recorded = []
        monkeypatch.setattr(runtime.store, 'create_approval', lambda **kw: recorded.append(kw) or kw)
        monkeypatch.setattr(runtime.gateway, '_notify_approval', lambda *_: None)
        runtime.gateway.register(ToolSpec(name='試験', description='시험', parameters={},
                                          risk_level=RiskLevel.L2, handler=lambda _: pytest.fail('실행되면 안 됨')))
        runtime.gateway.execute('試験')
        return round(recorded[-1]['expires_at'] - time.time())
    if key == 'local_write_enabled':
        # 이 설정이 지배하는 것은 **바꾸는 도구가 아예 안 도는가**이다.
        spec = ToolSpec(name='local_write_file', description='x', parameters={},
                        risk_level=RiskLevel.L1, handler=lambda _a: {})
        return runtime.gateway.refusal_for_read_only(spec) is None
    if key == 'approval_auto_reversible':
        # ★ 이름이 있어야 한다 — 관문이 `ALWAYS_ASK` 를 이름으로 본다(2026-09-21).
        #   가짜의 모양이 진짜와 다르면 시험은 통과하고 라이브가 깨진다.
        spec = SimpleNamespace(name='local_write_file', risk_level=RiskLevel.L1, inverse=object())
        return runtime.gateway._auto_approvable(spec, RiskLevel.L2)
    if key == 'approval_bypass_enabled':
        # 권한 무시 — 평소 늘 묻는 삭제가 관문을 그냥 지나가는가(2026-09-23).
        spec = SimpleNamespace(name='local_delete_file', risk_level=RiskLevel.L2, inverse=None)
        return runtime.gateway._auto_approvable(spec, RiskLevel.L2)
    if key == 'takeover_branch_enabled':
        # ★ 2026-09-20: 예전에는 **채팅 제안 문구**를 봤다. 그런데 이제 말로 하는 자리에서는
        #   가지를 약속하지 않으므로(문구가 켜도 꺼도 같다) 그 눈금은 이 설정을 못 잰다.
        #   이 설정이 실제로 지배하는 것은 **화면에서 눌렀을 때 가지를 파는가**다 — 그걸 잰다.
        return bool(runtime.takeover.branch_enabled)
    if key in {'skills_route_enabled', 'skills_domains'}:
        documents = {
            name: SkillDoc(tmp_path/'SKILL.md', '시험', name, '시험', f'{name}의 방법')
            for name in ['writing-plans', 'document-craft']}
        runtime.skills.skills = documents
        monkeypatch.setattr(runtime.skills, 'read_skill', lambda args: {'ok': True, 'name': args['name'],
                          'body': documents[args['name']].body, 'collection': '시험'})
        monkeypatch.setattr(runtime, '_skill_guess', lambda *_: '')
        return runtime._skill_instruction('과정을 정리해주세요', asked='document-craft')
    if key == 'code_scout_enabled':
        return runtime.code_scout.enabled
    if key in {'scribe_enabled', 'scribe_folders'}:
        # 서기 한 차례가 실제로 어디서 멈추는가 — 꺼짐 / 고른 폴더 없음 / 그다음(2026-10-21).
        return runtime._scribe_tick().get('skipped')
    if key == 'api_escalation_enabled':
        # 막힌 자리에서 실제로 어디서 멈추는가 — 꺼짐 / 그다음(키 · 부품)(2026-10-26).
        return runtime.api_escalation.skip_reason('probe-job', 10)
    if key == 'api_escalation_model':
        return runtime.api_escalation.model()
    if key == 'api_escalation_monthly_usd':
        return runtime.api_escalation.monthly_cap()
    raise AssertionError(f'소비자 눈금 없음: {key}')


def test_all_settings_have_a_consumer_probe():
    assert set(CHANGES) == set(BY_KEY)


@pytest.mark.parametrize('key', CHANGES)
def test_saved_setting_reaches_its_consumer(tmp_path, monkeypatch, key):
    monkeypatch.setattr(httpx, 'Client', OfflineClient)
    monkeypatch.setattr('alture_jarvis.config._default_backup_root', lambda: tmp_path/'backups')
    # 「막히면 내 클로드에게 넘기기」는 클로드 명령 · 로그인이 없으면 켜지지 않는다 — 이 PC 의 설치 여부와 무관하게 잰다.
    monkeypatch.setattr('alture_jarvis.claude_code.cli_status',
                        lambda _config: {'ok': True, 'code': '', 'reason': '', 'short': ''})
    # 「막히면 내 API 키로 묻기」도 키 · 부품이 없으면 켜지지 않는다 — 이 PC 의 설치 여부와 무관하게 잰다.
    monkeypatch.setattr('alture_jarvis.api_escalation.unavailable', lambda _config: ('', ''))
    defaults = dict(runtime_root=tmp_path, data_dir=tmp_path/'data', output_dir=tmp_path/'out',
                    documents_dir=tmp_path/'documents',
                    user_label='기본호칭', attention_notices_enabled=False, scheduler_enabled=False,
                    model_roles={'chat': 'base-chat', 'code': 'base-code', 'vision': 'base-vision'},
                    ollama_num_ctx=16384, agent_thinking_enabled=True, agent_thinking_policy='always', ollama_max_tool_steps=12,
                    voice_enabled=False, tts_enabled=False, supertonic_voice='F1', hotkey_enabled=False,
                    hotkey='f9', media_pause_enabled=False, memory_retrieval_enabled=False,
                    fact_learning_enabled=False, memory_backup_dir=None, local_file_allowed_roots='',
                    # 비우면 사용자 폴더 전체가 읽기 범위다 — 그러면 설정을 바꾸기 전에도 통과한다.
                    local_read_roots=str(tmp_path/'읽기범위없음'),
                    browser_enabled=False, browser_read_only=False, google_enabled=True,
                    google_write_enabled=False, windows_control_enabled=False, approval_ttl_sec=600,
                    approval_auto_reversible=False, approval_bypass_enabled=False, takeover_enabled=False, takeover_branch_enabled=False,
                    skills_route_enabled=False, skills_domains=(), claude_code_enabled=False,
                    sandbox_enabled=False, code_scout_enabled=False,
                    scribe_enabled=False, scribe_folders='')
    if key == 'scribe_folders': defaults['scribe_enabled'] = True
    if key == 'hotkey': defaults['hotkey_enabled'] = True
    if key == 'skills_domains': defaults['skills_route_enabled'] = True
    runtime = JarvisRuntime(JarvisConfig(**defaults))
    if key == 'google_write_enabled':
        monkeypatch.setattr(runtime.google, '_is_configured', lambda: True)
        runtime.google.register(runtime.gateway)
    before = consumer(runtime, key, monkeypatch, tmp_path)
    value = ([str(tmp_path/'allowed')] if key == 'local_file_allowed_roots'
             else [str(Path(tempfile.gettempdir())/'ontelic-read-roots-probe')] if key == 'local_read_roots'
             else CHANGES[key])
    result = runtime.settings.patch({key: value})
    assert result['ok']
    if not BY_KEY[key].live:
        runtime = JarvisRuntime(JarvisConfig(**defaults))
    after = consumer(runtime, key, monkeypatch, tmp_path)
    assert before != after, f'{key}: 저장했지만 소비자의 실행 결과가 달라지지 않았다'
