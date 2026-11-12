"""하네스 탓 10 (2026-11-08 게임 시험 4단계 둘째 판 · 맥 0502dee0): 「셸(curl -L)로 받고 … -batchmode 로 띄우고 … grep -c 로 세」를
계획이 「파일 만들기」 한 칸으로만 읽어, 「파일 만들 차례」에 셸을 한 번도 못 부르고 끝났다. 실행 낱말과 하라는 동사가 한 문장 안에
같이 오면 「이 PC 에서 명령 실행하기」 칸을 세운다. 옛 · 새 대조: PC 요청 2,921개 중 바뀐 것 1(「터미널로 알아봐줘」) · 사라진 칸 0."""
from __future__ import annotations

import pytest

from alture_jarvis import plan


def _actions(text: str) -> set[str]:
    return {str(r.target) for r in plan.extract(text) if r.kind == "action"}


@pytest.mark.parametrize("text", [
    "공식 릴리스 페이지의 첨부를 확인한 뒤 셸(curl -L)로 ~/Documents/Sonjari/downloads 에 받고, sha256 과 맞는지 확인해.",
    "에디터로 -batchmode -projectPath …/BugGuard -importPackage <받은 파일> -quit 를 셸 background=true 로 띄우고 기다려.",
    "두 로그에서 「error CS」 줄 수를 grep -c 로 세.",
    "내 pc 사양이 개발하기에 충분한지 너가 터미널로 알아봐줘",
])
def test_asked_to_run_commands(text: str) -> None:
    assert "local_run_shell" in _actions(text)


@pytest.mark.parametrize("text", [
    "셸 스크립트 하나 짜 줘. 실행은 내가 할게.",
    "grep 이 뭔지 설명해 줘.",
    "명령줄에서 `python report.py a.csv` 로 실행하면 합계가 나와야 한다.",
    "Agent TARS(명령줄·웹 화면으로 도는 범용 에이전트) 문서를 읽고 정리해 줘.",
])
def test_describing_or_writing_commands_is_not_running_them(text: str) -> None:
    assert "local_run_shell" not in _actions(text)


def test_english_label_exists() -> None:
    req = next(r for r in plan.extract("터미널로 알아봐줘") if r.kind == "action")
    assert plan.display_label(req, "en") == "Run the commands on this PC"


def test_dollrigo_form_counts_as_run_1108_night() -> None:
    """하네스 탓 13: 「셸 background=true 로 돌리고」가 동사 목록 밖이라 칸이 안 섰다."""
    text = "1) cd ~/Documents/Sonjari/BugGuard && python3 check_compile.py 를 셸 background=true 로 돌리고 기다려."
    assert "local_run_shell" in _actions(text)


def test_planned_action_hands_are_kept_on_a_narrow_route() -> None:
    """하네스 탓 13: 조사 갈래로 잡힌 판에서 계획이 요구한 셸이 not_this_route 로 막혔다 — 갈래가 좁혀도 남긴다."""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "src" / "alture_jarvis" / "agent.py").read_text(encoding="utf-8")
    assert "in planned_action_tools\n                        and asked_name not in scoped_names" in source
    assert "route_scoped_tools = [*route_scoped_tools, *asked_for]" in source


@pytest.mark.parametrize("text", ["3) 셸로 풀어서, 유니티가 읽는 모델 파일만 복사해.", "4) 셸로 차례로:", "셸(curl -L)로 받아."])
def test_naming_the_shell_as_the_tool_is_enough_1108_night(text: str) -> None:
    """하네스 탓 14(맥 504d6c31): 동사 목록을 늘리는 건 두더지 잡기 — 셸을 도구로 지목한 꼴(~로)이면 실행 요구다."""
    assert "local_run_shell" in _actions(text)


@pytest.mark.parametrize("text", ["터미널에서 쓰는 단축키를 알려 줘.", "명령줄에서 `python report.py a.csv` 로 실행하면 합계가 나와야 한다."])
def test_shell_as_a_place_is_not_an_order(text: str) -> None:
    assert "local_run_shell" not in _actions(text)
