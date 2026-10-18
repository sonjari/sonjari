"""앱 이름만 댄 요청은 결과 파일을 파일 도구로 바로 쓴다 (2026-10-17 대표 결정).

평소 말투로 시킨 측정에서 「메모장으로 … 저장」 · 「VS Code 로 … 한 줄 더해」 · 「그림판으로 … JPEG 로」는 창을 몰아
90~160초가 걸렸고, 같은 판의 엑셀 · 워드 · 파워포인트는 파일 도구로 16~20초에 끝났다.
창을 직접 다루라고 말한 요청은 그대로 창으로 간다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import app_named_only


@pytest.mark.parametrize(
    ("prompt", "app"),
    [
        ("메모장으로 「앱측정 1」 한 줄을 적어서 「C:\\x\\a.txt」 로 저장해 줘.", "메모장"),
        ("VS Code 로 「C:\\x\\b.txt」 파일 맨 끝에 「한 줄」을 더해 줘.", "VS Code"),
        ("「C:\\x\\c.png」 그림을 그림판으로 같은 폴더에 같은 이름의 JPEG(.jpg) 로 바꿔 저장해 줘.", "그림판"),
        ("「C:\\x\\d.hwp」 를 한글 프로그램으로 PDF 로 저장해 줘.", "한글 프로그램"),
    ],
)
def test_naming_the_app_alone_points_to_the_file(prompt: str, app: str) -> None:
    assert app_named_only(prompt) == app


@pytest.mark.parametrize(
    "prompt",
    [
        # 창 · 메뉴를 직접 다루라고 했다 — 창으로 한다.
        "VS Code 로 「C:\\x\\b.txt」 파일을 열어서 VS Code 창을 직접 조작해 맨 끝에 한 줄을 추가해 줘.",
        "「C:\\x\\d.hwp」 파일을 한글 프로그램으로 열어서, 한글의 메뉴(파일 > PDF로 저장하기)로 저장해 줘.",
        "메모장으로 열어서 키보드로 한 줄 쳐 줘.",
        # 「한글로」는 언어일 수 있다.
        "이 글을 한글로 번역해서 파일로 저장해 줘.",
        # 엑셀 · 워드 · 파워포인트는 이미 파일 도구로 간다 — 조사 판에 안내를 붙이지 않는다.
        "사람인 공고 3개 찾아서 엑셀로 정리해 줘.",
        "",
    ],
)
def test_window_wording_or_other_apps_get_no_note(prompt: str) -> None:
    assert app_named_only(prompt) == ""


def test_task_manager_values_get_the_window_reading_note() -> None:
    """2026-10-18: 평소 말투 3판 중 둘이 tasklist · Get-Process 로 작업 관리자와 다른 값(작업 집합)을 읽었다."""
    from alture_jarvis.plan import asks_task_manager_values

    assert asks_task_manager_values("작업 관리자 기준으로 메모리를 가장 많이 쓰는 프로그램 다섯 개 알려 줘")
    assert asks_task_manager_values("Task Manager 에서 GPU 메모리 얼마야")
    assert not asks_task_manager_values("메모리를 가장 많이 쓰는 프로그램 알려 줘")
