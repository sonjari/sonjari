"""능력을 잰 적 없는 모델에게 권한을 주지 않는다 (2026-09-20 사장님 지시).

> "이어받기를 하거나 접근 폴더 권한을 줄 때, 벤치에서 성능이 검증된 애들만 허용을 틀어 주는 게
> 어떤가. 4B 같은 애들을 그렇게 해 버리면 진짜 큰일난다."

★ 먼저 확인한 것: 화면의 「검증됨」(`status="verified"`)은 **VRAM 을 쟀다**는 뜻이다
  (`public()["vram_measured"]`). 4B 도 거기선 「검증됨」이라, 그 칸으로 잠그면 **틀린 눈금으로
  잠그는 것**이 된다. 능력은 `chain`(사슬 벤치)으로만 판정한다 — 그게 이 파일이 지키는 것이다.

막는 것은 **하나**다: 능력 안 잰 모델이 스스로 **쓰기** 폴더를 넓히는 것. 읽기는 열린다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.model_catalog import CATALOG, agent_grade, by_tag


def test_a_small_model_is_not_measured() -> None:
    grade = agent_grade("qwen3.5:4b")
    assert grade["measured"] is False
    assert grade["chain"] is None
    # 「나쁘다」가 아니라 **모른다**는 뜻이어야 한다 — 문구가 그렇게 말하는지 본다.
    assert "잰 적" in grade["label"] or "잰 적" in grade["detail"]


def test_a_benchmarked_model_is_measured() -> None:
    grade = agent_grade("qwen3.5:9b")
    assert grade["measured"] is True
    assert grade["chain"] == {"ok": 9, "total": 10, "ctx": 131072}


def test_vram_verified_is_not_capability_verified() -> None:
    """★ 이 시험이 이 파일의 이유다. 두 칸이 섞이면 4B 가 「검증됨」으로 권한을 얻는다."""
    small = by_tag("qwen3.5:4b")
    assert small is not None
    assert small.public()["vram_measured"] is True, "메모리는 실제로 쟀다 — 그래서 헷갈린다"
    assert agent_grade(small.ollama_tag)["measured"] is False, "그런데 능력은 잰 적이 없다"


def test_an_unknown_model_is_not_measured() -> None:
    """카탈로그에 없는 태그(사람이 직접 적은 것)도 「모른다」쪽이다."""
    assert agent_grade("someones-own-model:latest")["measured"] is False
    assert agent_grade("")["measured"] is False


def test_only_models_we_actually_benched_are_measured() -> None:
    """지어낸 성적이 카탈로그에 슬며시 들어오지 않게 — 실측이 있는 것만 `measured` 다."""
    measured = {model.ollama_tag for model in CATALOG if agent_grade(model.ollama_tag)["measured"]}
    assert measured == {
        "gemma4:26b-a4b-it-qat",   # 8/10 · git d375897c
        "qwen3.5:9b",              # 9/10 · results/multiturn_9b_2026-09-11.json
        # ★ 2026-09-20 추가: 10/10 · results/multiturn_qwen36_35ba3b_128k_20260920_after.json
        #   같은 날 오전 6/10 은 GPU 자리 다툼이었고(4판이 시작조차 못 함), 고친 뒤 다시 쟀다.
        "qwen3.6:35b-a3b",
    }, "능력 실측이 늘었으면 이 줄을 같이 고쳐라. 벤치를 안 돌리고 고치면 그게 창작이다."


def _tools(tmp_path: Path, model: str) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "밖"
    outside.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data",
        local_file_allowed_roots=str(work), local_read_roots=str(tmp_path),
        model_roles={"chat": model},
    )
    return LocalComputerTools(config), outside


def test_a_model_we_never_benched_cannot_widen_writing(tmp_path: Path) -> None:
    tools, outside = _tools(tmp_path, "qwen3.5:4b")
    with pytest.raises(PermissionError) as blocked:
        tools.request_path_access({"path": str(outside), "mode": "write", "reason": "결과물을 여기 두고 싶다"})
    message = str(blocked.value)
    assert "model_not_benchmarked" in message
    # 막기만 하면 안 된다 — 사람이 직접 넣는 길을 말해 준다.
    assert "설정" in message and "권한" in message


def test_the_same_model_may_still_ask_to_read(tmp_path: Path) -> None:
    """읽기는 열린다. 코워크가 이 PC 를 보고 답하는 것까지 막으면 제품이 죽는다."""
    tools, outside = _tools(tmp_path, "qwen3.5:4b")
    granted = tools.request_path_access({"path": str(outside), "mode": "read", "reason": "여기 자료를 봐야 합니다"})
    assert granted["ok"] is True and granted["mode"] == "read"


def test_a_benched_model_may_widen_writing(tmp_path: Path) -> None:
    tools, outside = _tools(tmp_path, "qwen3.5:9b")
    granted = tools.request_path_access({"path": str(outside), "mode": "write", "reason": "결과물을 여기 둡니다"})
    assert granted["ok"] is True and granted["mode"] == "write"
    tools.write_file({"path": str(outside / "결과.txt"), "content": "ok"})


def test_the_screen_gets_the_grade_from_health() -> None:
    """화면이 추측하지 않게 `/health` 가 같은 값을 실어 보낸다 (승인 카드 경고의 근거)."""
    import inspect

    from alture_jarvis.ollama import OllamaClient

    source = inspect.getsource(OllamaClient.health)
    assert '"agent_grade"' in source
