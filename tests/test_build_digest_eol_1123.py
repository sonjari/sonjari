"""판 번호는 줄 끝(CRLF/LF)을 세지 않는다 · 세 자리가 같은 규칙 하나를 쓴다 (2026-11-23).

맥 0.4.51: 같은 커밋인데 `git archive`(CRLF)로 보낸 맥 설치본과 PC 작업 폴더(일부 LF)로 만든 업데이트 묶음의
판 번호가 갈려(ef9a600c ≠ 3fb52d39) 「새 버전이 있습니다」가 떴다. 302개 파일 내용은 모두 같았다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alture_jarvis import config, updater

ROOT = Path(__file__).resolve().parents[1]


def _package(root: Path, eol: bytes) -> Path:
    package = root / "src" / "alture_jarvis"
    package.mkdir(parents=True)
    (package / "a.py").write_bytes(b"x = 1" + eol + b"y = 2" + eol)
    (package / "b.py").write_bytes(b"def f():" + eol + b"    return 3" + eol)
    (package / "sub").mkdir()
    (package / "sub" / "c.py").write_bytes(b"ignored = True" + eol)  # 바로 아래만 센다(예전 규칙 그대로)
    return package


def test_the_same_code_with_crlf_or_lf_has_the_same_build(tmp_path: Path) -> None:
    lf = config.code_digest(_package(tmp_path / "lf", b"\n"))
    crlf = config.code_digest(_package(tmp_path / "crlf", b"\r\n"))
    assert lf == crlf and len(lf) == 12


def test_a_real_change_still_changes_the_build(tmp_path: Path) -> None:
    package = _package(tmp_path / "p", b"\n")
    before = config.code_digest(package)
    (package / "a.py").write_bytes(b"x = 2\ny = 2\n")
    assert config.code_digest(package) != before


def test_the_three_places_agree(tmp_path: Path) -> None:
    # 지금 도는 코드(build_id) · 받아 푼 묶음(staged_build) · 올릴 묶음(source_build)이 같은 규칙.
    repo = tmp_path / "repo"
    _package(repo, b"\r\n")
    staged = tmp_path / "staged"
    _package(staged, b"\n")
    spec = importlib.util.spec_from_file_location("build_mac_update", ROOT / "scripts" / "mac" / "build_mac_update.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.source_build(repo) == updater.staged_build(staged) == config.code_digest(repo / "src" / "alture_jarvis")
    assert config.build_id() == config.code_digest(Path(config.__file__).resolve().parent)
