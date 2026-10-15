"""모델 받기 진행은 **층을 합쳐** 센다 · 확인 단계는 단계로 알린다 (2026-09-29 밤, AWS 첫 실행).

대표가 본 것: 6.1GB 를 다 받은 뒤 마법사가 「받는 중 0% · 0.0/0.0GB」로 1~2분 — 「또 뭘 받나 봐」.
Ollama pull 은 층(digest)마다 total 을 보낸다. 본체 뒤에 몇 KB 짜리 틀·설정 층이 오면 마지막 층의 total 만
적던 백엔드가 0.0GB 로 떨어졌고, 그 뒤 `verifying sha256 digest` 는 크기가 없어 그대로 멈춘 듯 보였다.
"""
from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.model_setup import SetupService

GB = 1024**3

STREAM = [
    {"status": "pulling manifest"},
    {"status": "pulling aaa", "digest": "sha256:aaa", "total": 6 * GB, "completed": 3 * GB},
    {"status": "pulling aaa", "digest": "sha256:aaa", "total": 6 * GB, "completed": 6 * GB},
    {"status": "pulling bbb", "digest": "sha256:bbb", "total": 4_096, "completed": 4_096},
    {"status": "pulling ccc", "digest": "sha256:ccc", "total": 120, "completed": 120},
    {"status": "verifying sha256 digest"},
    {"status": "writing manifest"},
    {"status": "success"},
]


def test_layers_are_summed_and_the_verify_step_is_named(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    service = SetupService(
        config,
        post=lambda url, body, timeout: {},
        get=lambda url: {"models": [{"name": "qwen3.5:9b"}]},
        stream=lambda url, body: iter(STREAM),
        publish=lambda event, payload: events.append((event, payload)),
    )
    service._pulls["qwen3.5-9b"] = {"model_key": "qwen3.5-9b", "status": "pulling", "completed": 0, "total": 0}
    service._pull("qwen3.5-9b", "qwen3.5:9b")

    seen = [payload for event, payload in events if event == "setup_model_pull"]
    after_small_layers = seen[4]
    assert after_small_layers["total"] == 6 * GB + 4_096 + 120, "작은 층이 전체 크기를 덮어쓰면 0.0GB 로 떨어진다"
    assert after_small_layers["completed"] == after_small_layers["total"]
    assert [p.get("phase") for p in seen[5:7]] == ["verifying", "finishing"]
    assert seen[-1]["status"] == "done"
