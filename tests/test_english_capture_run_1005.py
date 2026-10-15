"""스토어용 영어 장면을 찍다가 나온 것 (2026-10-05 아침, 가짜 홈 · 추천 모델 Gemma 4 26B · 판 9cae577f).

「Open github.com/trending/python, read the top 3 repositories, and save … as an Excel file」가 1/3 에서 멈췄다:

  ① 눈앞의 인기 목록에 `browser_open_result` 가 `no_result_list` 를 세 번 — 목록 판정기가 0줄을 냈다
     (칸마다 짧은 부속 링크가 붙어 링크 평균이 메뉴처럼 짧았다). → 얼린 표본 `github_trending` 이 `test_result_list_bench` 에서 잰다.
  ② 엑셀을 만들려고 상자를 불렀다가 「tool_disabled」 한 낱말을 받고 파일 만들기를 접었다.
  ③ 진행 줄에 Gemma 의 생각 채널 표식 「thought <channel|>」가 두 줄 찍혔다.
  ④ 영어 화면인데 페이지 위 딱지만 한국어(「검색 결과 열어 보는 중」)였다.
"""
from __future__ import annotations

import inspect
import re

from alture_jarvis import narration, ui_i18n
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.tool_gateway import _DISABLED_ALTERNATIVE, ToolGateway, ToolSpec

_HANGUL = re.compile("[가-힣]")


def test_a_disabled_tool_says_it_is_off_and_what_does_the_job_instead():
    source = inspect.getsource(ToolGateway.execute)
    assert "tool_disabled — " in source and "_DISABLED_ALTERNATIVE" in source
    assert "local_write_document" in _DISABLED_ALTERNATIVE["sandbox_run"]
    # 대신할 도구를 모르는 것에는 지어내지 않는다.
    assert "camera_look" not in _DISABLED_ALTERNATIVE
    assert ToolSpec is not None


def test_the_leaked_thinking_channel_is_not_narration():
    assert narration.clean("thought\n<channel|>") == ""
    assert narration.clean("thought\n<channel|>I will open the first repository.") == "I will open the first repository."
    assert narration.clean("<|channel|>thought\nlet me see\n<channel|>Opening it now.") == "Opening it now."
    # 보통 문장 속의 낱말은 안 건드린다.
    assert narration.clean("I thought about the channel and will read it.") == "I thought about the channel and will read it."


def test_the_badge_on_the_page_has_an_english_form():
    names = re.findall(r'"([a-z_]+)": "', inspect.getsource(BrowserWorker._visual_label))
    assert len(names) > 30
    left = {}
    for name in [*names, "some_action_without_a_label"]:
        english = ui_i18n.translate_text(BrowserWorker._visual_label(name))
        if _HANGUL.search(english):
            left[name] = english
    assert not left, left
    for korean in ("작업 단계 완료", "입력란 선택", "항목 선택", "‘Star’ 선택", "‘Trending’ 위에 올림", "‘Python’ 고르기", "파일 첨부 중"):
        assert not _HANGUL.search(ui_i18n.translate_text(korean)), korean


def test_the_badge_is_translated_where_it_is_drawn():
    """부르는 자리는 열 곳이고 그리는 자리는 하나다 — 그리는 자리에서 화면 언어를 본다."""
    source = inspect.getsource(BrowserWorker._show_visual)
    assert "ui_i18n.lang()" in source and "translate_text(label)" in source
