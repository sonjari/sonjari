"""노트북에서 이미 관측한 CPU 누수를 적용 경로에서 재현한다."""
from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SetupService, read_selection
from alture_jarvis.setup_profile import recommend
from alture_jarvis.settings import SettingsService


class Laptop:
    def __init__(self, shares=None, missing=False):
        self.shares = shares or {'qwen3.5:9b': .76, 'qwen3.5:4b': 1., 'qwen3.5:2b': 1.}
        self.installed = ['qwen3.5:9b'] if missing else list(self.shares)
        self.calls = []
        self.current = ''

    def post(self, url, body, timeout):
        self.calls.append(dict(body))
        if body.get('keep_alive') == 0:
            self.current = ''
            return {}
        self.current = body['model']
        return {'response': '1, 2, 3', 'eval_count': 64, 'eval_duration': 1_000_000_000}

    def get(self, url):
        if url.endswith('/api/tags'):
            return {'models': [{'name': tag} for tag in self.installed]}
        return {'models': [{'name': self.current, 'size': 10000,
                            'size_vram': int(10000 * self.shares.get(self.current, 1.))}]}

    def stream(self, url, body):
        self.installed.append(body['model'])
        yield {'status': 'success'}


def service(tmp_path, laptop):
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path/'data', output_dir=tmp_path/'out')
    config.model_roles = {'chat': 'old-model', 'vision': 'old-model'}
    events = []
    return SetupService(config, post=laptop.post, get=laptop.get, stream=laptop.stream,
                        publish=lambda event, payload: events.append((event, payload))), events


def test_8gb_recommendation_is_the_measured_9b_q3_text_only_then_smaller():
    # ★ 2026-10-14 대표 결정: 8GB 의 첫 추천은 9B 3비트 글만 읽기 48K(가격 조사 37/63 · 같은 노트북의 4B 24/63).
    #   그 전에는 4B 32K 였다. 안 들어가면 같은 모델 32K, 그다음 4B 3비트 글만 읽기 48K(2026-10-14 밤 6GB 급 추천)로 내려간다.
    result = recommend({'gpus': [{'name': 'RTX 5050 Laptop', 'vram_total_gb': 7.96, 'display_active': True}],
                        'ollama': {'installed': [], 'vulkan_setting': 'off'}})
    assert (result['model_key'], result['num_ctx'], result['text_only']) == ('qwen3.5-9b-q3', 49152, True)
    assert result['picks'][0]['kind'] == 'verified'
    assert [(a['model_key'], a['num_ctx']) for a in result['alternatives']][:2] == [('qwen3.5-9b-q3', 32768), ('qwen3.5-4b-q3', 49152)]


def test_76_percent_gpu_retries_4b_at_32k_before_saving(tmp_path: Path):
    fake = Laptop()
    setup, events = service(tmp_path, fake)
    result = setup.apply('qwen3.5-9b', 32768)
    assert result['ok']
    saved = read_selection(setup.config.data_dir)
    assert (saved['chat_model'], saved['num_ctx'], saved['verified']['gpu_share']) == ('qwen3.5:4b', 32768, 1.)
    assert [p['chat_model'] for e, p in events if e == 'setup_model_applied'] == ['qwen3.5:4b']
    assert result['warnings']
    generated = [c for c in fake.calls if c.get('prompt') and c.get('keep_alive') != 0]
    assert [c['model'] for c in generated] == ['qwen3.5:9b', 'qwen3.5:4b']


def test_a_fully_loaded_9b_is_kept_without_fallback(tmp_path: Path):
    setup, _ = service(tmp_path, Laptop({'qwen3.5:9b': 1.}))
    assert setup.apply('qwen3.5-9b', 32768)['ok']
    assert read_selection(setup.config.data_dir)['chat_model'] == 'qwen3.5:9b'


def test_offloaded_candidates_never_replace_the_previous_selection(tmp_path: Path):
    setup, events = service(tmp_path, Laptop({'qwen3.5:9b': .76, 'qwen3.5:4b': .8, 'qwen3.5:2b': .9}))
    result = setup.apply('qwen3.5-9b', 32768)
    assert not result['ok']
    assert setup.config.model_for('chat') == 'old-model'
    assert read_selection(setup.config.data_dir) is None
    assert not any(e == 'setup_model_applied' for e, _ in events)


def test_missing_smaller_model_is_downloaded_then_measured(tmp_path: Path):
    setup, _ = service(tmp_path, Laptop(missing=True))
    result = setup.apply('qwen3.5-9b', 32768)
    assert result['ok']
    assert read_selection(setup.config.data_dir)['chat_model'] == 'qwen3.5:4b'


def test_a_tiny_cpu_fraction_is_not_rounded_to_full_gpu(tmp_path: Path):
    fake = Laptop({'qwen3.5:9b': .9999})
    fake.current = 'qwen3.5:9b'
    setup, _ = service(tmp_path, fake)
    assert setup.gpu_offload('qwen3.5:9b')['gpu_share'] < 1.


def test_measured_selection_survives_restart_over_older_manual_settings(tmp_path):
    setup, _ = service(tmp_path, Laptop())
    settings = SettingsService(setup.config)
    assert settings.patch({'model_chat': 'older:9b', 'model_vision': 'older:9b',
                           'model_code': 'separate-code:latest', 'ollama_num_ctx': 16384})['ok']
    assert setup.apply('qwen3.5-9b', 32768)['ok']
    restarted = JarvisConfig(runtime_root=tmp_path, data_dir=setup.config.data_dir,
                            output_dir=tmp_path/'out')
    assert restarted.model_for('chat') == 'qwen3.5:4b'
    assert restarted.model_for('vision') == 'qwen3.5:4b'
    assert restarted.model_for('code') == 'separate-code:latest'
    assert restarted.ollama_num_ctx == 32768
    rows = {row['key']: row for row in settings.view()['settings']}
    assert rows['model_chat']['value'] == 'qwen3.5:4b'
    assert not rows['model_chat']['restart_required']


def test_failed_generation_unloads_the_attempt_without_saving(tmp_path):
    fake = Laptop()
    original_post = fake.post
    def fail_generation(url, body, timeout):
        if body.get('prompt') and body.get('keep_alive') != 0:
            fake.calls.append(dict(body))
            return {'error': 'runner failed'}
        return original_post(url, body, timeout)
    fake.post = fail_generation
    setup, events = service(tmp_path, fake)
    assert not setup.apply('qwen3.5-9b', 32768)['ok']
    assert any(c['model'] == 'qwen3.5:9b' and c.get('keep_alive') == 0 for c in fake.calls)
    assert read_selection(setup.config.data_dir) is None
    assert not any(e == 'setup_model_applied' for e, _ in events)
