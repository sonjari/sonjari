"""남의 설정 파일을 바꿔 쓸 때 윈도우가 「접근 거부」를 내면 잠깐 기다렸다 다시 한다 (2026-10-23 공개 저장소 main 검사 실패).

클로드 데스크톱 · 클로드 코드가 제 설정을 읽는 순간과 겹치면 이름 바꾸기가 `PermissionError` 로 막힌다. 한 번 막혔다고 연결 ·
서기 훅 설치가 실패하면 안 된다. 끝내 안 되면 임시 파일을 남기지 않고 그대로 알린다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis import mcp_connect


def test_a_brief_lock_is_waited_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "claude_desktop_config.json"
    target.write_text("{}", encoding="utf-8")
    real_replace = Path.replace
    tries = {"n": 0}

    def flaky(self: Path, other):  # noqa: ANN001
        tries["n"] += 1
        if tries["n"] <= 2:
            raise PermissionError(5, "Access is denied")
        return real_replace(self, other)

    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr(mcp_connect.time, "sleep", lambda _s: None)
    mcp_connect._atomic_write(target, '{"mcpServers": {}}')
    assert target.read_text(encoding="utf-8") == '{"mcpServers": {}}'
    assert tries["n"] == 3
    assert not (tmp_path / "claude_desktop_config.json.jarvis-tmp").exists()


def test_a_lock_that_never_lets_go_is_reported_and_leaves_no_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "settings.json"
    target.write_text("{}", encoding="utf-8")

    def locked(self: Path, other):  # noqa: ANN001
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr(mcp_connect.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        mcp_connect._atomic_write(target, '{"x": 1}')
    assert target.read_text(encoding="utf-8") == "{}", "원래 파일은 그대로"
    assert not (tmp_path / "settings.json.jarvis-tmp").exists()
