"""하네스 탓 11 (2026-11-08 밤 · 맥 05d20a83): 「1) git … cherry-pick 2) … commit 3) … log 4) … status」를 시켰는데
「명령 실행」 칸이 셸 **한 번** 성공으로 채워져, 1번만 하고 「커밋을 한다」는 예고가 답이 됐다. 번호 명령은 줄마다 센다.
같이: 「코드는 고치지 마」에 「repo 를 주라」 모드 알림이 걸리던 것(헛걸림 둘)."""
from __future__ import annotations

from alture_jarvis import plan
from alture_jarvis.delegation import _looks_like_code_work

PROMPT = """합쳐 줘(코드는 고치지 마). 셸로 아래 명령을 차례로 실행하고 결과를 그대로 적어.
1) git -C "/Users/d/BugGuard" cherry-pick -n 0d65..sonjari/task-1
2) git -C "/Users/d/BugGuard" commit -m "5단계 1판"
3) git -C "/Users/d/BugGuard" log --oneline -3
4) git -C "/Users/d/BugGuard" status --short 의 줄 수"""


def _shell(command: str) -> dict:
    return {"tool": "local_run_shell", "ok": True, "arguments": {"command": command}}


def _shell_req() -> plan.Requirement:
    return next(r for r in plan.extract(PROMPT) if r.kind == "action" and r.target == "local_run_shell")


def test_numbered_commands_are_carried_on_the_requirement() -> None:
    req = _shell_req()
    assert len(req.items) == 4 and req.label == "이 PC 에서 명령 실행하기"


def test_one_of_four_commands_is_not_done() -> None:
    steps = [_shell('git -C "/Users/d/BugGuard" cherry-pick -n 0d65..sonjari/task-1')]
    (_req, ok, saw), = plan.check([_shell_req()], sources=[], steps=steps)
    assert not ok and saw == "1/4개 명령 실행"


def test_commands_chained_with_and_still_count() -> None:
    steps = [
        _shell('git -C "/Users/d/BugGuard" cherry-pick -n 0d65..sonjari/task-1'),
        _shell('git -C "/Users/d/BugGuard" commit -m "5단계 1판" && git -C "/Users/d/BugGuard" log --oneline -3 && '
               'git -C "/Users/d/BugGuard" status --short | wc -l'),
    ]
    (_req, ok, saw), = plan.check([_shell_req()], sources=[], steps=steps)
    assert ok and saw == "4/4개 명령 실행"


def test_numbered_lines_that_are_not_commands_keep_the_old_rule() -> None:
    req = next(r for r in plan.extract("터미널로 알아봐줘\n1) 그래픽 카드\n2) 메모리 크기") if r.kind == "action")
    assert req.items == ()
    (_req, ok, _saw), = plan.check([req], sources=[], steps=[_shell("nvidia-smi")])
    assert ok


def test_dont_touch_the_code_is_not_code_work() -> None:
    assert not _looks_like_code_work("가지를 본가지에 합쳐 줘(코드는 고치지 마). 셸로 명령을 실행해")
    assert not _looks_like_code_work("5단계 준비야(게임 코드는 아직 짜지 마). check_compile.py 를 써")
    assert _looks_like_code_work("유니티 C# 스크립트로 포탑을 짜서 프로젝트에 넣어 줘")
