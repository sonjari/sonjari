"""글자 없는 **X 닫기**도 버튼이다 — 못 알아보면 팝업 밑의 화면을 통째로 못 쓴다.

2026-08-12 실측(잡코리아). 화면 한가운데 모달이 떠 있는데 그 밑 버튼이 안 눌렸다.
`browser_dismiss_dialog` 를 태워 보니 팝업은 **정확히 감지**했는데 이렇게 멈췄다:

    browser_popup_blocking:AI가 내 조건에 딱 맞는 공고만 먼저 보여줘요 다음

글자 있는 버튼이 "다음" 하나뿐이라 **부정 버튼이 없다**고 본 것이다. 실제 화면에는
글자 없는 X 닫기가 있었는데 버튼을 글자로만 세는 바람에 후보에 안 들어왔다.
어제 스냅샷에서 고친 "이름 없는 아이콘 버튼" 문제가 팝업 감지기에도 있었다.

여기서 지키는 것 넷:

  1. 글자가 없으면 사이트가 붙인 이름(aria-label·title)을 쓴다
  2. ×·✕ 같은 기호는 닫기로 본다 — 뜻이 하나뿐이다
  3. 그래도 **부정 버튼만** 누른다. "다음"·"확인"을 대신 누르지 않는다
  4. 이름이 아무 데도 없으면 조용히 넘어가지 않고 문구를 인용해 멈춘다
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.browser import _SE_DISMISS_LABELS, BrowserWorker
from alture_jarvis.config import JarvisConfig


class _Button:
    def __init__(self, text: str = "", attributes: dict[str, str] | None = None) -> None:
        self._text = text
        self._attributes = attributes or {}

    def inner_text(self, timeout: int = 0) -> str:
        del timeout
        if not self._text:
            raise RuntimeError("no text")
        return self._text

    def get_attribute(self, name: str) -> str | None:
        return self._attributes.get(name)


def _worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(
        JarvisConfig(
            runtime_root=tmp_path,
            data_dir=tmp_path / "data",
            output_dir=tmp_path / "outputs",
            browser_visual_overlay=False,
            browser_evidence_dir=tmp_path / "evidence",
        )
    )


def test_a_text_button_keeps_its_text(tmp_path: Path) -> None:
    del tmp_path
    assert BrowserWorker._button_label(_Button("취소")) == "취소"


def test_an_icon_close_is_named_by_its_accessible_name(tmp_path: Path) -> None:
    del tmp_path
    button = _Button("", {"aria-label": "닫기"})

    assert BrowserWorker._button_label(button) == "닫기"


def test_title_is_used_when_aria_label_is_missing(tmp_path: Path) -> None:
    del tmp_path
    assert BrowserWorker._button_label(_Button("", {"title": "close"})) == "close"


def test_a_nameless_button_stays_nameless(tmp_path: Path) -> None:
    """이름이 없으면 지어내지 않는다 — 모르는 버튼을 누르는 것이 제일 위험하다."""
    del tmp_path
    assert BrowserWorker._button_label(_Button("")) == ""


def test_close_symbols_count_as_dismiss() -> None:
    for symbol in ("×", "✕", "✖"):
        assert any(word in symbol.lower() for word in _SE_DISMISS_LABELS), symbol


def test_next_is_not_a_dismiss_button() -> None:
    """'다음'은 진행이다. 잡코리아 팝업에서 이걸 눌렀으면 안내를 계속 넘겼을 뿐이다.

    '다음에'(나중에)와 헷갈리면 안 된다 — 그건 부정이고 이건 진행이다.
    """
    assert not any(word == "다음" for word in _SE_DISMISS_LABELS)
    assert "다음에" in _SE_DISMISS_LABELS


def test_confirm_words_are_never_dismiss_words() -> None:
    """확인·동의를 자동으로 누르는 순간 이 도구는 무언가를 저지를 수 있게 된다."""
    for word in ("확인", "동의", "허용", "저장", "삭제", "제출"):
        assert word not in _SE_DISMISS_LABELS
