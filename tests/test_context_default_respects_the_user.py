"""잰 상한을 Ollama 전체 기본값(`OLLAMA_CONTEXT_LENGTH`)에 넣을 때 — **사람이 적어 둔 값은 덮지 않는다**.

2026-09-23 사용자님 결정: 「묻고 넣기」. 화면에서 체크했을 때만 넣고, 사람이 이미 넣어 둔 값은 안 건드린다
(`OLLAMA_VULKAN` 과 같은 규칙). 우리가 넣었던 값이면 새 상한으로 바꿔도 된다 — 기록 파일로 가린다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.ollama_install import OllamaInstaller, _read_owned


def _installer(tmp_path: Path) -> OllamaInstaller:
    installer = OllamaInstaller.__new__(OllamaInstaller)
    installer._process = None
    installer.running_version = lambda: ""  # 꺼져 있다 — 다시 켜기는 이 시험의 관심이 아니다
    return installer


def test_an_empty_setting_is_written_and_remembered_as_ours(tmp_path: Path) -> None:
    written: list[int] = []
    owned = tmp_path / "owned.json"
    done = _installer(tmp_path).set_default_context(
        131072, owned_path=owned, current_setting=lambda: "", write_setting=lambda n: written.append(n) or True)

    assert done["ok"] and written == [131072]
    assert _read_owned(owned) == {"OLLAMA_CONTEXT_LENGTH": "131072"}


def test_a_value_the_person_set_is_left_alone(tmp_path: Path) -> None:
    written: list[int] = []
    done = _installer(tmp_path).set_default_context(
        131072, owned_path=tmp_path / "owned.json", current_setting=lambda: "65536",
        write_setting=lambda n: written.append(n) or True)

    assert done == {"ok": False, "error": "user_set_context_length", "current": "65536"}
    assert written == []


def test_a_value_we_wrote_before_can_be_updated(tmp_path: Path) -> None:
    owned = tmp_path / "owned.json"
    owned.write_text('{"OLLAMA_CONTEXT_LENGTH": "65536"}', encoding="utf-8")
    written: list[int] = []
    done = _installer(tmp_path).set_default_context(
        131072, owned_path=owned, current_setting=lambda: "65536", write_setting=lambda n: written.append(n) or True)

    assert done["ok"] and written == [131072]


def test_when_we_cannot_read_the_setting_we_do_not_write(tmp_path: Path) -> None:
    """못 읽은 것을 「비었다」로 보면 사람 값을 덮는다 — 모르면 안 건드린다."""
    written: list[int] = []
    done = _installer(tmp_path).set_default_context(
        131072, owned_path=tmp_path / "owned.json", current_setting=lambda: "unknown",
        write_setting=lambda n: written.append(n) or True)

    assert not done["ok"] and written == []
