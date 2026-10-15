"""GPU 배치는 **어떻게 띄웠느냐**에 따라 달라지면 안 된다 (2026-09-28).

사용자 전역 `CUDA_VISIBLE_DEVICES=0`(Ollama 를 3090 에 묶으려던 값)을 백엔드가 물려받자 3060 이 안 보였고, 음성·비전이
3090 으로 내려가 모델 1.5GB 를 CPU 로 밀어냈다. 정식 기동 스크립트만 그 값을 덮어쓰고 있었다 — 다른 길로 띄우면 샜다.
"""

from alture_jarvis.gpu_policy import apply_process_gpu_policy, child_env_for_ollama


def test_the_backend_does_not_inherit_a_card_limit_meant_for_other_tools():
    env = {"CUDA_VISIBLE_DEVICES": "0"}
    report = apply_process_gpu_policy(env)
    assert "CUDA_VISIBLE_DEVICES" not in env          # 모든 카드를 보고 자기 설정으로 고른다
    assert env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"   # 번호는 nvidia-smi 와 같다
    assert report["inherited_ignored"] == "0" and report["visible"] == "all"


def test_every_start_path_ends_the_same():
    # start.ps1 처럼 미리 0,1 을 준 길과, 아무것도 안 거친 길이 같은 결과여야 한다.
    via_script = {"CUDA_VISIBLE_DEVICES": "0,1"}
    via_command_line = {"CUDA_VISIBLE_DEVICES": "0"}
    apply_process_gpu_policy(via_script)
    apply_process_gpu_policy(via_command_line)
    assert via_script.get("CUDA_VISIBLE_DEVICES") == via_command_line.get("CUDA_VISIBLE_DEVICES")


def test_an_ontelic_only_limit_is_respected():
    env = {"CUDA_VISIBLE_DEVICES": "0", "JARVIS_CUDA_VISIBLE_DEVICES": "1"}
    apply_process_gpu_policy(env)
    assert env["CUDA_VISIBLE_DEVICES"] == "1"


def test_applying_twice_changes_nothing():
    env = {"CUDA_VISIBLE_DEVICES": "0"}
    apply_process_gpu_policy(env)
    first = dict(env)
    apply_process_gpu_policy(env)
    assert env == first


def test_ollama_we_start_keeps_the_users_card_limit_and_order():
    env = {"CUDA_VISIBLE_DEVICES": "0", "PATH": "x"}
    apply_process_gpu_policy(env)
    child = child_env_for_ollama(env)
    assert child["CUDA_VISIBLE_DEVICES"] == "0"
    assert "CUDA_DEVICE_ORDER" not in child            # 사용자는 순서를 안 정했었다 — 그 사람의 0 은 기본 순서의 0 이다
    assert not any(key.startswith("ONTELIC_INHERITED") for key in child)


def test_ollama_sees_every_card_when_the_user_never_limited_it():
    env = {"PATH": "x"}
    apply_process_gpu_policy(env)
    assert "CUDA_VISIBLE_DEVICES" not in child_env_for_ollama(env)


def test_the_policy_runs_before_any_cuda_library_in_the_entry_point():
    # 순서가 곧 정책이다 — API(torch·ctranslate2)가 먼저 뜨면 이미 늦다. 두 기동 길(start.ps1·task_entry)이 다 여기를 지난다.
    import inspect

    import alture_jarvis.__main__ as entry

    source = inspect.getsource(entry.main)
    assert source.index("apply_process_gpu_policy()") < source.index("uvicorn.run(")
    assert "import torch" not in inspect.getsource(entry) and "api" not in entry.__dict__
