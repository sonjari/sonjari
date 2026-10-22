"""손자리에 일을 거는 벤치 스크립트는 요청에 `"measurement": True` 를 싣는다 (2026-10-19).

「막히면 내 클로드에게 넘기기」는 측정 판에서 늘 막혀야 한다 — 08-27 에 측정 24판 중 6판이 클로드로 빠져 로컬 실력이
부풀어 보였다. 백엔드는 이름(bench · measure …)으로도 거르지만, `aurora-*` 처럼 이름에 그 낱말이 없는 벤치는 샌다.
그래서 `/v1/chat` 으로 일을 거는 스크립트는 요청 본문에 표시를 싣는다.

★ 처음 손자리에게 맡긴 시험은 「파일에 measurement 낱말이 있나」만 봤고, 손자리는 조회만 하는 스크립트 17개의 설명 글에
  낱말을 끼워 넣어 통과시켰다(시험을 맞추느라 뜻 없는 글을 넣음). 그래서 **요청 본문 안의 키**를 본다: `/v1/chat` 을 부르는
  파일에 `"measurement": True` 가 실제 코드로 있어야 한다.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "bench"
_CHAT_CALL = re.compile(r"""["'](?:https?://[^"']*)?/v1/chat["']""")
_MARK = re.compile(r"""["']measurement["']\s*:\s*True""")


def _bench_scripts():
    for path in _ROOT.rglob("*.py"):
        if ".venv" in path.parts or "site-packages" in path.parts:
            continue
        yield path


def test_every_script_that_starts_a_sonjari_job_marks_it_as_measurement():
    missing = []
    for path in _bench_scripts():
        text = path.read_text(encoding="utf-8", errors="replace")
        if _CHAT_CALL.search(text) and not _MARK.search(text):
            missing.append(str(path.relative_to(_ROOT)))
    assert not missing, f"측정 표시가 없는 벤치 스크립트: {missing}"


def test_the_check_finds_real_job_starters():
    # 개수로 묻지 않는다 — 공개본에는 bench 일부만 나가서(6개) 「10개 이상」이 공개 저장소에서 넘어졌다.
    # 대신 공개본에도 들어가는, 일을 거는 게 분명한 스크립트를 이름으로 잡는다.
    starters = {p.relative_to(_ROOT).as_posix() for p in _bench_scripts()
                if _CHAT_CALL.search(p.read_text(encoding="utf-8", errors="replace"))}
    assert {"coding/aurora_repeat.py", "browser_agents/token_showdown.py"} <= starters
