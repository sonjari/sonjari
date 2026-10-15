"""가장 새 C++ 런타임이 먼저 올라가야 한다 — 노트북 포장본이 음성에서 백엔드째 죽었다(2026-09-24).

winrt 휠의 옛 msvcp140(14.29)이 먼저 올라가면 ctranslate2(음성 인식)가 std::mutex 에서 0xc0000005 로 죽는다.
개발 PC 재현: winrt 먼저 → whisper 2/2 비정상 종료, 새 런타임 먼저 → 2/2 정상.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="윈도우 DLL 문제")


def test_the_newest_candidate_is_chosen(monkeypatch, tmp_path):
    from alture_jarvis import msvc_runtime

    old, new = tmp_path / "old.dll", tmp_path / "new.dll"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    versions = {str(old): (14, 29, 30157, 0), str(new): (14, 44, 35211, 0)}
    monkeypatch.setattr(msvc_runtime, "candidates", lambda: [old, new])
    monkeypatch.setattr(msvc_runtime, "file_version", lambda p: versions[str(p)])
    loaded: list[str] = []
    monkeypatch.setattr("ctypes.WinDLL", lambda path: loaded.append(path))
    monkeypatch.setattr(msvc_runtime, "_loaded", "")
    assert msvc_runtime.preload_newest_msvcp() == str(new)
    assert loaded == [str(new)]


def test_importing_the_backend_wins_the_race_against_winrt():
    """실제 프로세스에서: `import alture_jarvis` 뒤 winrt 를 불러도 올라가 있는 msvcp140 은 winrt 의 옛 사본이 아니다."""
    pytest.importorskip("winrt.windows.media.control")
    code = textwrap.dedent(
        """
        import ctypes, ctypes.wintypes as wt, sys
        sys.path.insert(0, sys.argv[1])
        import alture_jarvis
        from alture_jarvis.msvc_runtime import file_version
        from pathlib import Path
        import winrt.windows.foundation, winrt.windows.media.control
        k = ctypes.windll.kernel32
        k.GetModuleHandleW.restype = wt.HMODULE
        k.GetModuleFileNameW.argtypes = [wt.HMODULE, wt.LPWSTR, wt.DWORD]
        buf = ctypes.create_unicode_buffer(1024)
        k.GetModuleFileNameW(k.GetModuleHandleW("msvcp140.dll"), buf, 1024)
        print(buf.value.lower().endswith("winrt\\\\msvcp140.dll"), file_version(Path(buf.value)))
        """
    )
    out = subprocess.run([sys.executable, "-c", code, str(ROOT / "src")], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    is_winrt_copy, version = out.stdout.strip().split(" ", 1)
    assert is_winrt_copy == "False", out.stdout
    assert eval(version) >= (14, 40, 0, 0), out.stdout  # noqa: S307 - 우리가 찍은 튜플


def test_the_package_build_refuses_old_runtimes():
    script = (ROOT / "packaging" / "msix" / "build_app_package.ps1").read_text(encoding="utf-8", errors="replace")
    assert 'minVc = [version]"14.40.0.0"' in script
    assert "package still carries VC++ runtime older than" in script
    assert "msvcp140.dll" in script
