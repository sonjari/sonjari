"""09-19 노트북: 화면이 예쁘다는 말에 카메라 영상 없음을 답한 사고."""
import pytest
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime

SCREEN_REMARKS = [
    '온텔릭 화면이 왜이얼게 이뻐보이지',
    '온텔릭 화면이 왜 이렇게 예뻐 보이지',
    '지금 온텔릭 화면이 왜 이렇게 이뻐 보이지',
    '지금 이 앱 화면은 어떻게 보여?',
    '웹사이트 디자인이 예쁘네',
    '설정 화면 색상이 마음에 든다',
]


@pytest.mark.parametrize('prompt', SCREEN_REMARKS)
def test_digital_subject_never_takes_the_physical_camera_shortcut(prompt):
    assert not JarvisRuntime._requires_fresh_camera(prompt)


@pytest.mark.parametrize('entry', ['_general_route', '_contextual_answer'])
@pytest.mark.parametrize('prompt', SCREEN_REMARKS[:4])
@pytest.mark.parametrize('tool', ['look_at_camera', 'use_camera_control'])
@pytest.mark.parametrize('stream', [False, True])
def test_camera_call_hallucinated_by_model_is_rejected_in_both_answer_paths(tmp_path, monkeypatch, entry, prompt, tool, stream):
    runtime = JarvisRuntime(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path/'data', output_dir=tmp_path/'out',
                                       voice_enabled=False, tts_enabled=False, camera_enabled=False,
                                       vision_enabled=False, camera_control_enabled=False, google_enabled=False))
    monkeypatch.setattr(runtime, '_memory_context', lambda *_: [])
    monkeypatch.setattr(runtime, '_skill_instruction', lambda *_, **__: '')
    monkeypatch.setattr(runtime, '_vision_answer', lambda **_: pytest.fail('디지털 화면 질문이 물리 카메라를 호출함'))
    seen = []
    painted = []
    monkeypatch.setattr(runtime.events, 'publish', lambda kind, payload: painted.append((kind, payload)))

    def model(text, **kwargs):
        seen.append(kwargs)
        if stream:
            kwargs['on_chunk']({'content': '잘못된 카메라 초안' if len(seen) == 1 else '디자인이 마음에 드셨군요.'})
        if len(seen) == 1:
            return {'content': '', 'tool_calls': [{'function': {'name': tool, 'arguments': {}}}]}
        return {'content': '디자인이 마음에 드셨군요. 정돈된 화면은 편안하게 느껴질 수 있어요.'}

    monkeypatch.setattr(runtime.ollama, 'chat_message', model)
    monkeypatch.setattr(runtime.ollama, 'chat_message_stream', model)
    result = getattr(runtime, entry)(prompt, 'screen-test', job_id='screen-job' if stream else '')
    answer = result[1] if entry == '_general_route' else result[0]
    assert '디자인' in answer and '카메라' not in answer
    assert len(seen) == 2
    assert all(c['function']['name'] not in {'look_at_camera', 'use_camera_control'} for call in seen for c in call['tools'])
    shown = ''.join(payload.get('delta', '') for kind, payload in painted if kind == 'agent_answer_delta')
    assert '잘못된 카메라 초안' not in shown
    if stream:
        assert '디자인이 마음에 드셨군요.' in shown


@pytest.mark.parametrize('prompt', ['지금 내 얼굴 어때?', '지금 이거 보여?', '카메라로 봐줘'])
def test_real_physical_camera_requests_are_preserved(prompt):
    assert JarvisRuntime._requires_fresh_camera(prompt)


@pytest.mark.parametrize('prompt', ['카메라를 왼쪽으로 돌려서 화면에 보여줘',
                                   '카메라 정면으로 돌려줘, 화면으로 확인할게'])
def test_physical_camera_movement_is_preserved_when_screen_is_also_mentioned(prompt):
    assert JarvisRuntime._requires_camera_control(prompt)


def test_repeated_unoffered_camera_calls_never_execute_or_paint_a_draft(tmp_path, monkeypatch):
    runtime = JarvisRuntime(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path/'data',
                                       output_dir=tmp_path/'out', voice_enabled=False, tts_enabled=False))
    monkeypatch.setattr(runtime, '_memory_context', lambda *_: [])
    monkeypatch.setattr(runtime, '_skill_instruction', lambda *_, **__: '')
    monkeypatch.setattr(runtime, '_vision_answer', lambda **_: pytest.fail('카메라를 실행함'))
    events, calls = [], []
    monkeypatch.setattr(runtime.events, 'publish', lambda kind, payload: events.append((kind, payload)))
    def model(prompt, **kwargs):
        calls.append(kwargs)
        kwargs['on_chunk']({'content': '카메라가 없어서 볼 수 없습니다.'})
        return {'tool_calls': [{'function': {'name': 'look_at_camera', 'arguments': {}}}]}
    monkeypatch.setattr(runtime.ollama, 'chat_message_stream', model)
    with pytest.raises(RuntimeError, match='ollama_unoffered_camera_tool'):
        runtime._general_route(SCREEN_REMARKS[0], '시험', job_id='screen-failed')
    assert len(calls) == 2
    assert not any(kind == 'agent_answer_delta' for kind, _ in events)


@pytest.mark.parametrize('entry', ['_general_route', '_contextual_answer'])
def test_camera_denial_in_plain_text_is_retried_before_painting(tmp_path, monkeypatch, entry):
    runtime = JarvisRuntime(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path/'data',
                                       output_dir=tmp_path/'out', voice_enabled=False, tts_enabled=False))
    monkeypatch.setattr(runtime, '_memory_context', lambda *_: [])
    monkeypatch.setattr(runtime, '_skill_instruction', lambda *_, **__: '')
    events, calls = [], []
    monkeypatch.setattr(runtime.events, 'publish', lambda kind, payload: events.append((kind, payload)))
    def model(prompt, **kwargs):
        calls.append(kwargs)
        answer = ('온텔릭 디자인은 카메라를 돌릴 수 없어 확인할 수 없습니다. '
                  '이 텍스트 비서에는 별도의 그래픽 인터페이스나 화면이 존재하지 않습니다.'
                  if len(calls) == 1 else
                  '직접 화면을 보지는 못하지만 깔끔한 배치와 색의 조화가 예쁘게 느껴질 수 있겠네요.')
        kwargs['on_chunk']({'content': answer})
        return {'content': answer}
    monkeypatch.setattr(runtime.ollama, 'chat_message_stream', model)
    outcome = getattr(runtime, entry)(SCREEN_REMARKS[0], 'desktop-e2e', job_id='screen-job')
    answer = outcome[1] if entry == '_general_route' else outcome[0]
    shown = ''.join(payload.get('delta', '') for kind, payload in events if kind == 'agent_answer_delta')
    assert len(calls) == 2
    assert '카메라' not in answer and '화면이 존재하지 않' not in shown
    assert '깔끔한 배치' in answer and '깔끔한 배치' in shown


def test_repeated_plain_text_camera_denial_is_not_delivered(tmp_path, monkeypatch):
    runtime = JarvisRuntime(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path/'data',
                                       output_dir=tmp_path/'out', voice_enabled=False, tts_enabled=False))
    monkeypatch.setattr(runtime, '_memory_context', lambda *_: [])
    monkeypatch.setattr(runtime, '_skill_instruction', lambda *_, **__: '')
    events, calls = [], []
    monkeypatch.setattr(runtime.events, 'publish', lambda kind, payload: events.append((kind, payload)))
    def model(prompt, **kwargs):
        calls.append(kwargs)
        kwargs['on_chunk']({'content': '카메라 영상이 없어서 화면을 볼 수 없습니다.'})
        return {'content': '카메라 영상이 없어서 화면을 볼 수 없습니다.'}
    monkeypatch.setattr(runtime.ollama, 'chat_message_stream', model)
    with pytest.raises(RuntimeError, match='ollama_ungrounded_digital_visual_answer'):
        runtime._general_route(SCREEN_REMARKS[0], 'desktop-e2e', job_id='screen-job')
    assert len(calls) == 2
    assert not any(kind == 'agent_answer_delta' for kind, _ in events)


@pytest.mark.parametrize('wrong', [
    "온텔릭은 별도의 그래픽 인터페이스나 '화면'이 없어요.",
    '온텔릭은 텍스트 비서라 UI가 없네요.',
    '이 앱에는 화면 자체가 존재하지 않습니다.',
])
def test_screen_nonexistence_wording_is_detected(wrong):
    assert JarvisRuntime._ungrounded_digital_visual_answer(SCREEN_REMARKS[0], wrong)


def test_honest_lack_of_screenshot_is_not_a_denial_of_the_app():
    assert not JarvisRuntime._ungrounded_digital_visual_answer(
        SCREEN_REMARKS[0], '지금 화면을 직접 볼 수 없지만, 실제 온텔릭 화면의 어떤 점이 마음에 드셨나요?')


def test_bad_prior_answer_cannot_poison_design_retry(tmp_path, monkeypatch):
    runtime = JarvisRuntime(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path/'data',
                                       output_dir=tmp_path/'out', voice_enabled=False, tts_enabled=False))
    prior = [{'role': 'assistant', 'content': '온텔릭은 텍스트 비서라 화면이 없습니다.'}]
    monkeypatch.setattr(runtime, '_memory_context', lambda *_: prior)
    monkeypatch.setattr(runtime, '_skill_instruction', lambda *_, **__: '')
    calls = []
    def model(prompt, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1 or kwargs['history'] or kwargs['tools']:
            return {'content': '온텔릭은 텍스트 비서라 별도의 화면이 없어요.'}
        return {'content': '실제 화면을 직접 보지는 못하지만 디자인이 마음에 드셨다니 좋네요.'}
    monkeypatch.setattr(runtime.ollama, 'chat_message', model)
    route, answer, _ = runtime._general_route(SCREEN_REMARKS[0], 'poisoned-history')
    assert route == 'answer' and '디자인이 마음에' in answer
    assert len(calls) == 2 and calls[1]['history'] == [] and calls[1]['tools'] == []
