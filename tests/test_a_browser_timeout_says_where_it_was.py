"""브라우저 동작이 시간에 끊기면 **어느 구간에서 멈췄는지**를 같이 말한다 (2026-10-06).

로컬 미리보기를 여는 첫 `browser_open` 이 180초 물렸다. 기록에는 동작 이름만 남아, 이동에서 멈췄는지 앞 탭을
건드리다 멈췄는지 가릴 수 없었다. 원인을 모르는 채로 고치지 않는다 — 다음에 같은 일이 나면 구간이 찍히게 한다.

구간을 모르면(동작 밖에서 물린 호출) 예전 글 그대로다.
"""

from __future__ import annotations

import threading

import pytest

from alture_jarvis import ui_i18n
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


def _worker(tmp_path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "out",
            browser_task_timeout_sec=1,
        )
    )


def test_the_timeout_names_the_stretch_it_was_in(tmp_path) -> None:
    worker = _worker(tmp_path)
    release = threading.Event()

    def stuck_in_goto() -> None:
        worker._doing = "open:goto"
        release.wait(30)

    with pytest.raises(RuntimeError, match="browser_action_timeout") as caught:
        worker._submit(stuck_in_goto)
    release.set()

    assert "(멈춘 구간: open:goto)" in str(caught.value)


def test_without_a_known_stretch_the_message_is_the_old_one(tmp_path) -> None:
    worker = _worker(tmp_path)
    release = threading.Event()

    with pytest.raises(RuntimeError, match="browser_action_timeout") as caught:
        worker._submit(lambda: release.wait(30))
    release.set()

    assert "멈춘 구간" not in str(caught.value)
    assert str(caught.value).endswith("다시 실행하기 전에 화면을 확인하세요.")


def test_a_stretch_left_by_an_earlier_call_is_not_blamed(tmp_path) -> None:
    """앞 호출이 끝내며 남긴 구간을, 다른 자리에서 물린 다음 호출의 것으로 읽으면 엉뚱한 곳을 판다."""
    worker = _worker(tmp_path)
    release = threading.Event()

    def finished_fine() -> str:
        worker._doing = "open:evidence"
        return "끝"

    assert worker._submit(finished_fine) == "끝"
    with pytest.raises(RuntimeError, match="browser_action_timeout") as caught:
        worker._submit(lambda: release.wait(30))
    release.set()

    assert "멈춘 구간" not in str(caught.value)


def test_the_english_screen_gets_the_stretch_too() -> None:
    ui_i18n.reload()
    korean = (
        "browser_action_timeout — 시간이 끊겼을 뿐 동작은 계속 진행됐을 수 있습니다."
        " 다시 실행하기 전에 화면을 확인하세요. (멈춘 구간: open:goto)"
    )

    english = ui_i18n.translate_text(korean)

    assert english.endswith("(stuck at: open:goto)")
    assert "시간이" not in english
