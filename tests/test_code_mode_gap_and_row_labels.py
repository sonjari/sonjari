"""코드 모드 첫 걸음 전 공백 · 표의 분류 칸 헛경고 (2026-09-28 16:37 실사용 판 `8da70e67`).

① 모노레포 코드 모드 판이 157초 중 약 111초 동안 화면에 「도구를 고르는 중」만 띄웠다. 모델도 Ollama 도 아니었다 — 첫 걸음 전
  저장소 지도(`repo_card`)가 밀린 색인을 따라잡고 있었다(데워진 뒤엔 0.5~1.3초). 이제 색인이 훑은 수를 1.5초마다 내보낸다.
② 답의 「| 레이어 | 파일 | 역할 |」 표에서 첫 칸 「로컬 조작」을 이름으로 보고 「읽지 않고 적었다」 — 같은 줄의 파일은 읽었다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis import code_index as code_index_module
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.code_index import CodeIndex


def test_a_slow_index_reports_what_it_has_scanned(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for number in range(6):
        (repo / f"m{number}.py").write_text(f"def f{number}():\n    return {number}\n", encoding="utf-8")
    clock = iter(float(second) for second in range(0, 1000, 2))
    monkeypatch.setattr(code_index_module.time, "monotonic", lambda: next(clock))
    seen: list[dict[str, int]] = []

    CodeIndex(tmp_path / "index").refresh(repo, on_progress=seen.append)

    assert seen, "따라잡기 동안 아무것도 안 내보냈다 — 화면이 멈춘 것처럼 보인다"
    assert seen[-1]["scanned"] >= 1 and set(seen[-1]) == {"scanned", "updated", "unchanged"}


def test_a_broken_progress_listener_does_not_break_indexing(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    clock = iter(float(second) for second in range(0, 1000, 2))
    monkeypatch.setattr(code_index_module.time, "monotonic", lambda: next(clock))

    def boom(_: dict[str, int]) -> None:
        raise RuntimeError("화면이 죽었다")

    assert CodeIndex(tmp_path / "index").refresh(repo, on_progress=boom)["total_files"] == 1


READ = r"e:\monorepo\tools\alture-jarvis\src\alture_jarvis"
LEDGER = [
    {"type": "body_read", "source_id": rf"{READ}\local_computer.py", "job_id": "j", "step": 2, "ok": True},
    {"type": "body_read", "source_id": rf"{READ}\tool_gateway.py", "job_id": "j", "step": 3, "ok": True},
]
BODY = "class LocalComputer: SURVEY_READ_CHARS = 15000\nclass ToolGateway: audit_shape"


def _check(answer: str) -> str:
    return BrowserAgent._listed_entity_grounding_check(answer, [], LEDGER, lambda _job, _step: BODY)


def test_a_category_cell_next_to_a_file_we_read_is_not_flagged() -> None:
    answer = (
        "| 레이어 | 파일 | 역할 |\n|---|---|---|\n"
        "| **로컬 조작** | `local_computer.py` | 파일 읽기·쓰기 |\n"
        "| **도구 게이트웨이** | `tool_gateway.py` | 감사·되돌리기 |\n"
    )

    assert _check(answer) == ""


def test_a_row_without_anything_we_read_is_still_flagged() -> None:
    """읽은 파일이 없는 줄까지 풀어 주면 지어낸 줄이 빠져나간다."""
    answer = (
        "| 레이어 | 파일 | 역할 |\n|---|---|---|\n"
        "| **로컬 조작** | `local_computer.py` | 파일 읽기·쓰기 |\n"
        "| **음성 합성** | `supertonic_bridge.py` | 말하기 |\n"
        "| **카메라 중계** | `camera_relay.py` | 보기 |\n"
    )

    note = _check(answer)

    # 경고는 이름을 **원래 표기**로 적는다(2026-10-01 — 대조는 공백을 지우고 하지만 보여 주기는 그대로).
    assert "음성 합성" in note and "카메라 중계" in note
    assert "로컬 조작" not in note and "로컬조작" not in note
