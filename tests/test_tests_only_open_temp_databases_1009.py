"""시험은 임시 폴더의 DB 만 연다 — 다른 곳을 가리키면 그 자리에서 떨어진다 (2026-10-09).

사본에서 돌린 시험이 돌고 있는 진짜 DB 에 **조용히** 붙었던 사고의 둘째 문이다(첫째 문은 환경변수를 안 물려받는 것).
문 자체는 `conftest.py` 에 있다. 여기서는 그 문이 실제로 서 있는지만 본다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.jobs import JobStore


def test_a_database_under_the_temp_folder_opens(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "nested" / "jarvis.db")
    job = store.create_job("chat", "시험", {"prompt": "x"})
    assert store.get_job(job["id"])["title"] == "시험"


@pytest.mark.parametrize("where", [
    Path(__file__).resolve().parent / "should_never_exist.db",          # 저장소 안
    Path(__file__).resolve().parents[1] / "data" / "jarvis.db",          # 저장소의 data 폴더(운영과 같은 모양)
    Path.home() / "should_never_exist_sonjari_test.db",                  # 사용자 폴더
])
def test_a_database_anywhere_else_is_refused_before_it_is_touched(where: Path) -> None:
    existed = where.exists()
    with pytest.raises(RuntimeError, match="임시 폴더 밖의 DB"):
        JobStore(where)
    assert where.exists() == existed, "거절은 파일을 만들기 전이어야 한다"


def test_importing_the_api_module_builds_nothing() -> None:
    """`alture_jarvis.api` 를 불러오기만 해서는 앱이 만들어지지 않는다 — 쓰일 때(`api.app`) 만든다.

    전에는 모듈 끝의 `app = create_app()` 가 불러오는 순간 기본 설정으로 런타임을 만들고 사용자의 진짜 앱 폴더 DB 를 열었다.
    새 프로세스에서 본다 — 이 프로세스에서는 다른 시험이 이미 불러왔을 수 있다.
    """
    import os
    import subprocess
    import sys

    import alture_jarvis

    # ★ 새 프로세스의 `python -c` 는 **깔려 있는 코드**를 불러온다(이 저장소의 것이 아니라). 처음 이 시험을 쓸 때 그대로 밟았다 —
    #   운영에 깔린 옛 api 를 불러와 「만들어졌다」가 나왔다. 이 저장소의 src 를 맨 앞에 주고, 정말 그것을 불렀는지도 본다.
    source = str(Path(alture_jarvis.__file__).resolve().parents[1])
    done = subprocess.run(
        [sys.executable, "-c",
         "import alture_jarvis.api as m; print(m.__file__); print('built' if 'app' in vars(m) else 'nothing')"],
        # 자식은 UTF-8 로 쓰고 이쪽도 UTF-8 로 읽는다 — 경로에 한글이 있어서, 셸에 `PYTHONIOENCODING=utf-8` 이 걸려 있으면
        # 자식만 UTF-8 로 쓰고 이쪽은 cp949 로 읽다 깨져 stdout 이 None 이 됐다(2026-10-16).
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        env={**os.environ, "PYTHONPATH": source, "PYTHONIOENCODING": "utf-8"},
    )
    assert done.returncode == 0, done.stderr[-400:]
    loaded, verdict = done.stdout.strip().splitlines()[-2:]
    assert Path(loaded).resolve().parents[1] == Path(source), f"다른 곳의 코드를 불러왔다: {loaded}"
    assert verdict == "nothing"


def test_the_server_can_still_find_the_app_by_name() -> None:
    import inspect

    from alture_jarvis import api

    source = inspect.getsource(api.__getattr__)
    assert 'if name == "app":' in source and "create_app()" in source
    with pytest.raises(AttributeError):
        api.no_such_name  # noqa: B018


def test_the_gate_is_up_before_any_test_file_is_imported() -> None:
    """문이 세션 픽스처면 수집 단계의 불러오기를 놓친다 — conftest 를 불러올 때 선다."""
    from alture_jarvis import jobs

    assert getattr(jobs.JobStore.__init__, "_guards_temp_only", False) is True

