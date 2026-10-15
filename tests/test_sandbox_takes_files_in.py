"""밖에서 안으로 — **다뤄야 할 파일을 상자에 넣을 수 있는가.**

## 무엇이 막혀 있었나 (2026-08-23)

상자는 격리돼 있다(`windows_mounts: 0`). 그래서 `E:\\` 를 못 본다. 그런데 로컬
도구는 **읽기 전용**이다 — `local_list_directory` · `local_read_document` ·
`local_read_text_file` · `local_search_files`. 쓰기·편집이 없다.

    "이 엑셀 읽어서 반별 평균 내고 새 파일로 저장해줘"
        로컬 도구  → 읽지만 계산·저장을 못 함
        상자      → 계산·저장은 하는데 그 파일을 못 봄

**나가는 길(`saved_to`)은 진작 있었는데 들어오는 길만 없었다.** 그래서 사무 실무의
절반이 구조적으로 불가능했다 — 자비스를 상업적으로 팔려면 여기가 뚫려야 한다.

## 격리는 그대로다

드라이브를 마운트하지 않는다. **고른 파일만 복사**한다. 경로 검증은 지메일 첨부가
쓰는 `local_computer.resolve_allowed_path` 를 그대로 쓴다 — 두 벌을 두면 갈리고,
갈린 쪽이 구멍이 된다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis.sandbox import SandboxBox


class _Config:
    sandbox_distro = "Ubuntu"
    sandbox_timeout_sec = 60
    sandbox_input_max_bytes = 1024


class _Local:
    """허용 뿌리 밖은 거절하는 진짜 검사기의 최소 흉내."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_allowed_path(self, raw: str) -> Path:
        path = Path(raw).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError(f"허용된 자리 밖이다: {path}")
        return path


def _box(tmp_path: Path) -> SandboxBox:
    return SandboxBox(_Config(), None, local_computer=_Local(tmp_path))


def test_a_file_outside_the_allowed_roots_is_refused(tmp_path: Path) -> None:
    """★ 넣는 길이 생겼다고 아무 파일이나 들어가면 안 된다."""
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("비밀", encoding="utf-8")

    result = _box(tmp_path).run({"code": "print(1)", "files": [str(outside)]})

    assert result["ok"] is False
    assert "허용된 자리 밖" in result["error"]


def test_a_directory_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "sub"
    folder.mkdir()

    result = _box(tmp_path).run({"code": "print(1)", "files": [str(folder)]})

    assert result["ok"] is False
    assert "파일이 아니다" in result["error"]


def test_too_much_is_refused(tmp_path: Path) -> None:
    """상자에 통째로 밀어 넣지 못하게 — 합계 상한이 있다."""
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 2048)  # 상한 1024

    result = _box(tmp_path).run({"code": "print(1)", "files": [str(big)]})

    assert result["ok"] is False
    assert "너무 크다" in result["error"]


def test_without_a_path_checker_it_refuses_rather_than_guesses(tmp_path: Path) -> None:
    """★ 검사기가 없으면 **넣지 않는다.** 열어 두는 쪽으로 실패하면 안 된다."""
    target = tmp_path / "a.txt"
    target.write_text("가", encoding="utf-8")

    result = SandboxBox(_Config(), None).run({"code": "print(1)", "files": [str(target)]})

    assert result["ok"] is False
    assert "경로 검사기가 없다" in result["error"]


def test_the_run_still_works_with_no_files() -> None:
    """파일을 안 넣는 예전 쓰임이 그대로여야 한다."""
    source = inspect.getsource(SandboxBox.run)

    assert 'args.get("files")' in source
    assert "stage_block" in source, "파일이 없을 때 빈 블록으로 떨어져야 한다"


def test_the_schema_tells_the_model_the_hand_exists() -> None:
    """★ 도구에 넣어도 스키마에 없으면 모델은 못 쓴다 — 이 저장소가 아는 병이다."""
    source = inspect.getsource(SandboxBox)

    assert '"files"' in source, "스키마에 files 가 없다"
    assert "in/" in source, "어디서 읽는지 안 알려 준다"


def test_the_result_says_what_went_in() -> None:
    """무엇을 받았는지 안 알려 주면 모델이 파일 이름을 지어낸다."""
    source = inspect.getsource(SandboxBox.run)

    assert "staged_in" in source
    assert "instruction" in source


def test_the_runtime_hands_the_path_checker_to_the_box() -> None:
    """★ 배선이 빠지면 이 기능이 통째로 죽는다 — 오늘 여러 번 본 모양이다."""
    from alture_jarvis.runtime import JarvisRuntime

    source = inspect.getsource(JarvisRuntime)
    assert "SandboxBox(self.config, self.events, local_computer=" in source, (
        "상자에 경로 검사기를 안 넘긴다 — files 인자가 늘 거절된다"
    )
