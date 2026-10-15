"""푼 폴더를 제자리로 못 옮겨도 Ollama 설치는 끝난다 (2026-10-06 스토어 공개판 첫 설치, 회사 PC).

다 받고 해시도 맞고 다 풀었는데 마지막 이름 바꾸기 한 번이 `PermissionError [WinError 5]` 로 떨어져 설치 전체가
실패했다 — 보안 프로그램이 방금 푼 exe·dll 을 훑는 동안에는 폴더 이름을 못 바꾼다. 이름 바꾸기는 필수가 아니다.
몇 번 다시 해 보고, 끝내 안 되면 푼 자리를 그대로 `current.json` 이 가리킨다.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_ollama_install import _installer, _zip_bytes


def _block_the_move(monkeypatch, tmp_path: Path, times: int | None) -> list[str]:
    """풀어 둔 폴더(`….extracting…`)의 이름 바꾸기를 `times` 번(None 이면 끝까지) 막는다."""
    real = type(tmp_path).rename
    tried: list[str] = []

    def rename(self, target):
        if ".extracting" in self.name:
            tried.append(self.name)
            if times is None or len(tried) <= times:
                raise PermissionError(5, "액세스가 거부되었습니다", str(self))
        return real(self, target)

    monkeypatch.setattr(type(tmp_path), "rename", rename)
    return tried


def _ready(installer, monkeypatch) -> None:
    answers = iter(["", ""] + ["0.9.9"] * 20)
    monkeypatch.setattr(installer, "running_version", lambda: next(answers))
    monkeypatch.setattr("alture_jarvis.ollama_install.time.sleep", lambda _s: None)


def test_a_move_that_fails_at_first_is_tried_again(tmp_path: Path, monkeypatch) -> None:
    installer, started, _real = _installer(tmp_path, _zip_bytes())
    _ready(installer, monkeypatch)
    tried = _block_the_move(monkeypatch, tmp_path, times=2)

    result = installer.install()

    assert result["ok"] is True
    assert len(tried) == 3, "두 번 막히고 세 번째에 옮겨졌다"
    root = tmp_path / "data" / "ollama"
    assert json.loads((root / "current.json").read_text(encoding="utf-8"))["folder"] == "v9.9.9"
    assert installer.bundled_exe() == root / "v9.9.9" / "ollama.exe"
    installer.stop()


def test_a_move_that_never_works_still_ends_in_a_working_install(tmp_path: Path, monkeypatch) -> None:
    installer, started, _real = _installer(tmp_path, _zip_bytes())
    _ready(installer, monkeypatch)
    installer.MOVE_RETRY_SECONDS = 0.0
    _block_the_move(monkeypatch, tmp_path, times=None)

    result = installer.install()

    assert result["ok"] is True, "이름을 못 바꿨다고 설치를 포기하면 안 된다"
    root = tmp_path / "data" / "ollama"
    folder = json.loads((root / "current.json").read_text(encoding="utf-8"))["folder"]
    assert folder == "v9.9.9.extracting"
    exe = installer.bundled_exe()
    assert exe == root / folder / "ollama.exe" and exe.read_bytes() == b"MZ fake"
    assert started and started[0][0] == str(exe) and started[0][-1] == "serve", "서버도 그 자리에서 켠다"
    installer.stop()


def test_installing_again_does_not_extract_over_the_folder_in_use(tmp_path: Path, monkeypatch) -> None:
    """푼 자리 그대로 쓰는 설치 위에 다시 깔 때 — 살아 있는 폴더를 풀 자리로 다시 쓰지 않고, 끝난 뒤 옛 폴더를 치운다."""
    installer, _started, _real = _installer(tmp_path, _zip_bytes())
    _ready(installer, monkeypatch)
    installer.MOVE_RETRY_SECONDS = 0.0
    tried = _block_the_move(monkeypatch, tmp_path, times=None)
    assert installer.install()["ok"] is True
    root = tmp_path / "data" / "ollama"
    (root / "v9.9.9.extracting" / "keep.txt").write_text("in use", encoding="utf-8")
    tried.clear()
    seen_while_extracting: list[bool] = []
    extract = installer._move_into_place

    def watch(staging: Path, target: Path) -> Path:
        seen_while_extracting.append((root / "v9.9.9.extracting" / "keep.txt").is_file())
        return extract(staging, target)

    monkeypatch.setattr(installer, "_move_into_place", watch)
    _ready(installer, monkeypatch)

    again = installer.install()

    assert again["ok"] is True
    assert seen_while_extracting == [True], "새것을 푸는 동안 쓰던 폴더는 그대로였다"
    assert tried and all(name == "v9.9.9.extracting-2" for name in tried), "다른 이름의 자리에 풀었다"
    folder = json.loads((root / "current.json").read_text(encoding="utf-8"))["folder"]
    assert folder == "v9.9.9.extracting-2"
    assert not (root / "v9.9.9.extracting").exists(), "안 쓰게 된 옛 폴더는 치운다"
    installer.stop()


def test_a_marker_with_a_strange_folder_name_is_never_used_to_delete(tmp_path: Path, monkeypatch) -> None:
    installer, _started, _real = _installer(tmp_path, _zip_bytes())
    root = tmp_path / "data" / "ollama"
    root.mkdir(parents=True)
    for name in ("..", ".", "a/b", "..\\x", ""):
        (root / "current.json").write_text(json.dumps({"folder": name}), encoding="utf-8")
        assert installer._live_folder() == ""
    (root / "current.json").write_text(json.dumps({"folder": "v0.35.1"}), encoding="utf-8")
    assert installer._live_folder() == "v0.35.1"
