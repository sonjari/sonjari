"""영어 화면의 진행 줄에 「browser_extract 실행 중」이 그대로 나갔다 (2026-10-05, 스토어용 영어 장면을 찍다가).

도구 153개 중 81개에 이름표가 없어 `_tool_label` 이 「도구이름 실행 중」을 돌려줬고, 그 꼴은 영어 사전에 없었다.
자주 쓰는 손에는 이름표를 붙였고, 나머지는 영어 화면에서 「Running 도구이름」으로 나간다.
"""
from __future__ import annotations

import inspect
import re

from alture_jarvis import ui_i18n
from alture_jarvis.agent import BrowserAgent

_HANGUL = re.compile("[가-힣]")


def _labelled_names() -> list[str]:
    source = inspect.getsource(BrowserAgent._tool_label)
    return sorted(set(re.findall(r'^\s+"([a-z][a-z0-9_]+)": "', source, re.M)))


def test_every_label_has_an_english_form():
    names = _labelled_names()
    assert len(names) > 80, "이름표 표를 못 읽었다 — 이 시험이 아무것도 안 보고 통과하면 안 된다"
    left = {name: ui_i18n.translate_text(BrowserAgent._tool_label(name, {})) for name in names}
    left = {name: text for name, text in left.items() if _HANGUL.search(text)}
    assert not left, left


def test_the_hands_research_uses_most_have_a_real_label():
    for name in ("browser_extract", "browser_open_result", "browser_site_search", "browser_find", "sandbox_run", "local_grep"):
        label = BrowserAgent._tool_label(name, {})
        assert name not in label, f"{name}: 도구 이름이 그대로 보인다 — {label}"


def test_a_tool_without_a_label_does_not_leak_korean():
    label = BrowserAgent._tool_label("some_new_tool_2", {})
    assert label == "some_new_tool_2 실행 중"
    assert ui_i18n.translate_text(label) == "Running some_new_tool_2"


def test_only_a_tool_name_takes_that_shape():
    """「…실행 중」으로 끝나는 아무 글이나 먹으면 안 된다 — 도구 이름 꼴일 때만."""
    for text in ("서버가 실행 중", "첫 줄\n둘째 줄 실행 중", "Ollama 실행 중"):
        assert not ui_i18n.translate_text(text).startswith("Running "), text
