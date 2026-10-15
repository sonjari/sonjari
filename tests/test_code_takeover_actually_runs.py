"""Code 모드 이어받기가 **실제로 코드를 이어서 고친다** (2026-09-20 사장님 지시).

> "코드모드에서 이어받기가 핵심인데 그게 아직 안 되더라고."

## 고장이 아니라 **세 겹으로 막혀 있었다** (2026-09-20 조사)

기계는 다 있었다 — `continue_on_branch` 가 git worktree 를 만들고, 새 가지를 파고,
멈춘 순간의 미커밋 변경을 옮겨 담고, 시작점 커밋을 찍고, 잡을 넣는다. 그런데:

    1. 화면    `TakeoverRelay` 가 `/cowork` 만 부른다 — `/accept` 를 부르는 길이 UI 에 없다
    2. 설정    `takeover_branch_enabled` 기본값이 False — 켜도 `/accept` 가 카드만 준다
    3. 인계문  `prepare_cowork` 가 **"코드 파일 수정과 git 가지 실행만 직접 하지 말고"** 를 써 넣는다

「도구를 만들어도 갈래가 없으면 안 쓰인다」 — 이 저장소가 제일 많이 밟은 그 자리다.

## 왜 이제 열어도 되나

막아 둔 근거는 주석의 "H2 실제 시험은 아직 기본 추천 조건을 못 넘었다"(9월 중순)다.
그 뒤로 모델과 배선이 바뀌었고, **되돌리기는 여전히 「가지 하나 삭제」로 끝난다** —
이 저장소가 쓰기를 여는 기준으로 삼아 온 바로 그 선 안이다. 원래 폴더는 건드리지 않는다.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.takeover import TakeoverService

from test_takeover import _claude_rows, _write_jsonl  # noqa: F401  (같은 harness 를 쓴다)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """멈춘 순간의 저장소 — 커밋된 것 + 미커밋 변경 + 새 파일."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "pay.py").write_text("a = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "pay.py").write_text("a = 2\n", encoding="utf-8")
    (root / "new_test.py").write_text("def test_x(): pass\n", encoding="utf-8")
    return root


def _config(tmp_path: Path, **over) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                        output_dir=tmp_path / "out", **over)


def test_the_branch_path_is_on_by_default() -> None:
    """★ 기본값이 꺼져 있어서 아무도 쓸 수 없었다. 되돌리기는 가지 삭제 하나다."""
    assert JarvisConfig().takeover_branch_enabled is True


def test_accepting_a_repo_session_starts_real_code_work(tmp_path: Path, repo: Path) -> None:
    """가지를 파고 **잡을 넣는다.** 「정리해 드렸습니다」로 끝나면 이어받기가 아니다."""
    home = tmp_path / "home"
    path = _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl",
                        _claude_rows(str(repo), at=time.time() - 60))
    submitted: list[dict] = []
    service = TakeoverService(
        _config(tmp_path), home=home,
        submit=lambda payload: submitted.append(payload) or {"id": "job-1"},
    )
    made = service.record_card(str(path))

    result = service.accept(made["takeover_id"])

    assert result["kind"] == "started", f"카드만 주고 끝났다: {result}"
    assert submitted, "잡을 안 넣었다 — 아무도 이어서 일하지 않는다"
    row = service.get(made["takeover_id"])
    assert row["status"] == "continuing" and row["branch"] and row["worktree"]


def test_the_code_handoff_does_not_forbid_editing_code(tmp_path: Path, repo: Path) -> None:
    """★ 인계문이 「코드는 고치지 마라」라고 적혀 있으면 모델은 그대로 따른다.

    Cowork(대화) 쪽 인계문은 그 말이 맞다 — 거기는 저장소를 안 건드린다.
    Code 쪽은 **고치라고 부른 자리**다. 같은 문장을 쓰면 안 된다.
    """
    home = tmp_path / "home"
    path = _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl",
                        _claude_rows(str(repo), at=time.time() - 60))
    service = TakeoverService(_config(tmp_path), home=home, submit=lambda payload: {"id": "x"})
    made = service.record_card(str(path))

    code = service.prepare_cowork(made["takeover_id"], direction="continue", target="code")
    assert code["ok"] is True
    assert "직접 하지 말고" not in code["prompt"], "Code 인계문이 손을 묶고 있다"
    assert "가지" in code["prompt"] or "브랜치" in code["prompt"], "어디서 고치는지 말해 줘야 한다"

    # 대화 쪽은 그대로 — 저장소를 안 건드린다는 약속은 지킨다.
    chat = service.prepare_cowork(made["takeover_id"], direction="continue")
    assert "원래 대화와 작업 폴더를 바꾸지 말고" in chat["prompt"]


def test_a_session_without_a_repo_still_falls_back_to_the_card(tmp_path: Path) -> None:
    """저장소가 아니면 팔 가지가 없다. 그때는 예전처럼 인계문만 준다 — 조용히 실패하지 않는다."""
    home = tmp_path / "home"
    path = _write_jsonl(home / ".claude" / "projects" / "p" / "hit.jsonl",
                        _claude_rows("C:/그냥폴더", at=time.time() - 60))
    service = TakeoverService(_config(tmp_path), home=home, submit=lambda payload: {"id": "x"})
    made = service.record_card(str(path))

    result = service.accept(made["takeover_id"])
    assert result["kind"] == "card"
