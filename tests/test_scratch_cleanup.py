"""일회용 폴더는 **정말로** 지워져야 한다 — 지우는 척은 안 지우는 것보다 나쁘다.

2026-08-08: `%TEMP%` 에 `jarvis-*` 가 31개 / 691MB 쌓여 있었다. 실행 PC(여수 사무실)는
원격으로만 닿으므로 이런 건 사람이 볼 때까지 자란다.

원인 둘 중 **둘째**를 여기서 잠근다. 넷은 아예 안 지웠고(mkdtemp 만), 나머지 넷은
`TemporaryDirectory(ignore_cleanup_errors=True)` 로 **지우는 척**했다 — 크로미움이
프로필 파일을 쥐고 있으면 정리가 실패하는데 그 실패를 조용히 삼킨다. 정리 코드가
버젓이 있으니 아무도 의심하지 않는다. 이 저장소가 반복해서 데인 그 모양이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _scratch import purge, scratch_root  # noqa: E402


def test_the_folder_is_gone_afterwards() -> None:
    with scratch_root("jarvis-test-") as root:
        (root / "profile").mkdir()
        (root / "profile" / "Cookies").write_bytes(b"x" * 1024)
        kept = root
        assert kept.exists()
    assert not kept.exists()


def test_a_locked_file_is_retried_not_swallowed(tmp_path: Path, capsys) -> None:
    """처음엔 잠겨 있다가 풀리는 경우 — 크로미움이 죽는 중일 때 실제로 이 모양이다."""
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "Cookies").write_bytes(b"x")

    import _scratch

    calls = {"n": 0}
    real = _scratch.shutil.rmtree

    def flaky(path, *a, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError(32, "사용 중인 파일")
        return real(path, *a, **kw)

    _scratch.shutil.rmtree = flaky
    try:
        ok = purge(root, attempts=5, pause=0.01)
    finally:
        _scratch.shutil.rmtree = real

    assert ok is True
    assert calls["n"] == 3, "한 번 실패했다고 포기하면 브라우저가 죽는 동안 늘 샌다"
    assert not root.exists()


def test_giving_up_says_so_out_loud(tmp_path: Path, capsys) -> None:
    """끝내 못 지우면 **말한다.** 조용히 넘어가면 다시 쌓이기 시작해도 아무도 모른다."""
    root = tmp_path / "stuck"
    root.mkdir()
    (root / "big") .write_bytes(b"x" * 2048)

    import _scratch

    real = _scratch.shutil.rmtree
    _scratch.shutil.rmtree = lambda *a, **kw: (_ for _ in ()).throw(OSError(32, "잠김"))
    try:
        ok = purge(root, attempts=2, pause=0.01)
    finally:
        _scratch.shutil.rmtree = real

    assert ok is False
    assert "못 지웠다" in capsys.readouterr().out, (
        "실패를 삼키는 정리는 정리가 아니라 정리한다는 주장일 뿐이다"
    )


def test_the_folder_is_removed_even_when_the_body_raises() -> None:
    # 검증 스크립트는 실패로 끝나는 일이 잦다. 그때야말로 뒷정리가 필요하다.
    kept: Path | None = None
    try:
        with scratch_root("jarvis-test-") as root:
            kept = root
            raise RuntimeError("검증 실패")
    except RuntimeError:
        pass
    assert kept is not None and not kept.exists()
