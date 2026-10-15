"""비활성 입력란은 Playwright 기본 타임아웃까지 기다리지 않는다."""

from __future__ import annotations

import pytest

from alture_jarvis.browser import BrowserWorker


class _DisabledInput:
    def get_attribute(self, name: str):
        return "text" if name == "type" else None

    def is_disabled(self, timeout: int = 0) -> bool:
        assert timeout <= 1200
        return True

    def fill(self, _value: str) -> None:  # pragma: no cover - 호출되면 시험이 바로 실패한다
        raise AssertionError("disabled를 알고도 fill을 기다리면 안 된다")


def test_disabled_input_is_rejected_before_fill() -> None:
    worker = BrowserWorker.__new__(BrowserWorker)
    worker._ref_locator = lambda _page, _ref: _DisabledInput()  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="target_disabled:j1"):
        worker._fill(object(), {"ref": "j1", "value": "Codex"})
