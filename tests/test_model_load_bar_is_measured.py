"""모델 올리기 막대는 **잰 값**이다 (2026-10-01 헤르메스 비교에서 배움).

Ollama 는 올리는 진행률을 안 준다. 시간 따라 차는 막대는 거짓이라, 카드 메모리 차이를 이 PC 에서 지난번 잰 양으로 나눈다.
"""

from alture_jarvis.load_progress import LoadWatch, gpu_used_gb


class _Card:
    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_first_load_is_an_estimate_from_the_file_size(tmp_path):
    clock = _Clock()
    watch = LoadWatch(tmp_path, gpu_used=_Card(1.0, 4.0), clock=clock)
    first = watch.observe(model="qwen3.5:9b", num_ctx=65536, resident=False, model_bytes=6 * 2**30)
    assert first["loading"] and first["fraction"] == 0 and first["basis"] == "estimated"
    clock.now += 10
    second = watch.observe(model="qwen3.5:9b", num_ctx=65536, resident=False, model_bytes=6 * 2**30)
    assert second["loaded_gb"] == 3.0 and second["elapsed_s"] == 10.0
    assert 0.4 < second["fraction"] < 0.5  # 3GB / (6GB × 1.15)


def test_finished_load_is_remembered_and_becomes_the_denominator(tmp_path):
    clock = _Clock()
    watch = LoadWatch(tmp_path, gpu_used=_Card(1.0, 5.0, 9.0), clock=clock)
    watch.observe(model="m", num_ctx=32768, resident=False, model_bytes=2**30)
    clock.now += 20
    watch.observe(model="m", num_ctx=32768, resident=False, model_bytes=2**30)
    clock.now += 20
    done = watch.observe(model="m", num_ctx=32768, resident=True)
    assert done == {"loading": False, "resident": True}

    # 다음 콜드 적재(창 크기 같음) — 분모는 이번에 잰 8GB, 걸린 시간 40초도 같이 준다.
    clock.now += 600
    again = LoadWatch(tmp_path, gpu_used=_Card(1.0, 5.0), clock=clock)
    again.observe(model="m", num_ctx=32768, resident=False)
    clock.now += 5
    mid = again.observe(model="m", num_ctx=32768, resident=False)
    assert mid["basis"] == "measured" and mid["expected_gb"] == 8.0
    assert mid["fraction"] == 0.5 and mid["last_seconds"] == 40.0


def test_never_shows_done_before_ollama_says_so(tmp_path):
    clock = _Clock()
    watch = LoadWatch(tmp_path, gpu_used=_Card(1.0, 30.0), clock=clock)
    watch.observe(model="m", num_ctx=1, resident=False, model_bytes=2**30)
    over = watch.observe(model="m", num_ctx=1, resident=False, model_bytes=2**30)
    assert over["fraction"] < 1.0


def test_unloading_the_old_model_lowers_the_floor(tmp_path):
    # 다른 모델을 내리면서 올린다 — 사용량이 먼저 줄었다가 는다. 바닥은 본 것 중 가장 낮은 값.
    clock = _Clock()
    watch = LoadWatch(tmp_path, gpu_used=_Card(20.0, 2.0, 6.0), clock=clock)
    for _ in range(2):
        watch.observe(model="m", num_ctx=1, resident=False, model_bytes=8 * 2**30)
    last = watch.observe(model="m", num_ctx=1, resident=False, model_bytes=8 * 2**30)
    assert last["loaded_gb"] == 4.0


def test_without_nvidia_smi_there_is_no_bar_only_seconds(tmp_path):
    clock = _Clock()
    watch = LoadWatch(tmp_path, gpu_used=lambda: None, clock=clock)
    out = watch.observe(model="m", num_ctx=1, resident=False, model_bytes=2**30)
    assert out["fraction"] is None and out["basis"] == "unmeasured" and out["loading"]


def test_an_undercounted_run_does_not_shrink_the_denominator(tmp_path):
    clock = _Clock()
    full = LoadWatch(tmp_path, gpu_used=_Card(1.0, 9.0), clock=clock)
    full.observe(model="m", num_ctx=1, resident=False)
    full.observe(model="m", num_ctx=1, resident=True)
    clock.now += 600
    # 늦게 들어와 바닥이 높게 잡힌 판: 3GB 만 쟀다 — 분모 8GB 를 줄이면 다음 막대가 거짓으로 빨리 찬다.
    late = LoadWatch(tmp_path, gpu_used=_Card(6.0, 9.0), clock=clock)
    late.observe(model="m", num_ctx=1, resident=False)
    late.observe(model="m", num_ctx=1, resident=True)
    clock.now += 600
    check = LoadWatch(tmp_path, gpu_used=_Card(1.0, 3.0), clock=clock)
    check.observe(model="m", num_ctx=1, resident=False)
    assert check.observe(model="m", num_ctx=1, resident=False)["expected_gb"] == 8.0


def test_gpu_reader_sums_cards_and_survives_missing_tool():
    class Done:
        returncode = 0
        stdout = "1024\n2048\n"

    assert gpu_used_gb(lambda *a, **k: Done()) == 3.0

    def boom(*a, **k):
        raise FileNotFoundError

    assert gpu_used_gb(boom) is None
