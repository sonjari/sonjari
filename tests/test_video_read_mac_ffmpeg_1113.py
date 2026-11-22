"""맥 영상 파일 읽기 — ffmpeg 를 PATH 또는 imageio-ffmpeg 에서 찾고, ffprobe 없이 크기를 잰다 (2026-11-13).

맥에는 ffmpeg 가 없다. 맥 설치가 pyproject 의 `imageio-ffmpeg`(맥 표시)를 깔고 그 안의 ffmpeg 를 쓴다. 그 꾸러미에는
ffprobe 가 없어서 크기 재기를 `ffmpeg -i` 의 설명 줄로 옮겼다. 여기서는 진짜 imageio-ffmpeg 대신 가짜 모듈이
이 PC 의 ffmpeg 를 가리키게 하고, PATH 에서는 ffmpeg · ffprobe 를 둘 다 감춘다 — 맥과 같은 처지.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from alture_jarvis.video_read import scan

_REAL_FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(_REAL_FFMPEG is None, reason="ffmpeg 없음")


def _hide_path(monkeypatch: pytest.MonkeyPatch) -> None:
    real = shutil.which
    monkeypatch.setattr(scan.shutil, "which", lambda name, *a, **k: None if name in {"ffmpeg", "ffprobe"} else real(name, *a, **k))


def _fake_imageio(monkeypatch: pytest.MonkeyPatch, exe: str) -> None:
    module = types.ModuleType("imageio_ffmpeg")
    module.get_ffmpeg_exe = lambda: exe  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", module)


def test_path_ffmpeg_comes_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scan.shutil, "which", lambda name, *a, **k: "/opt/homebrew/bin/ffmpeg" if name == "ffmpeg" else None)
    _fake_imageio(monkeypatch, str(tmp_path / "never"))
    assert scan.ffmpeg_exe() == "/opt/homebrew/bin/ffmpeg"


def test_without_path_the_packaged_ffmpeg_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / "ffmpeg-macos-aarch64-v7.1"
    exe.write_bytes(b"")
    _hide_path(monkeypatch)
    _fake_imageio(monkeypatch, str(exe))
    assert scan.ffmpeg_exe() == str(exe)


def test_nothing_anywhere_is_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _hide_path(monkeypatch)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)  # import 가 실패한다
    assert scan.ffmpeg_exe() is None
    _fake_imageio(monkeypatch, str(tmp_path / "gone"))  # 꾸러미는 있는데 실행 파일이 없다
    assert scan.ffmpeg_exe() is None


_PLAIN = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'a.mp4':
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 8 fps
    Metadata:
      handler_name    : VideoHandler
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo
"""
_PHONE = _PLAIN.replace("      handler_name    : VideoHandler\n",
                        "      handler_name    : VideoHandler\n    Side data:\n      Display Matrix: rotation of -90.00 degrees\n")
_OLD_FFMPEG = _PLAIN.replace("      handler_name    : VideoHandler\n", "      rotate          : 270\n")
_COVER = """  Stream #0:0: Video: h264, yuv420p, 1280x720, 30 fps
  Stream #0:1: Video: mjpeg (Baseline), yuvj420p, 600x600, 90k tbr (attached pic)
    Side data:
      Display Matrix: rotation of 90.00 degrees
"""


@pytest.mark.parametrize(("stderr", "size"), [
    (_PLAIN, (1920, 1080)),
    (_PHONE, (1080, 1920)),       # 휴대폰 세로 영상: 저장은 가로, 보이기는 세로
    (_OLD_FFMPEG, (1080, 1920)),  # 옛 ffmpeg 의 rotate 표시
    (_COVER, (1280, 720)),        # 다른 줄기(표지 그림)의 돌림 표시는 안 본다
])
def test_size_is_read_from_the_first_video_stream_as_shown(monkeypatch: pytest.MonkeyPatch, stderr: str, size: tuple[int, int]) -> None:
    monkeypatch.setattr(scan, "_need_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(scan.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", stderr))
    assert scan.video_size("a.mp4") == size


@needs_ffmpeg
def test_a_rotated_phone_video_is_read_without_ffprobe_like_on_a_mac(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """진짜 ffmpeg 로 만든 「가로로 저장 · 90도 돌려 보이기」 영상 — 옛 코드(ffprobe 크기)는 가로로 눌러 담았다."""
    plain, rotated = tmp_path / "a.mp4", tmp_path / "phone.mp4"
    subprocess.run([_REAL_FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=1:r=8",
                    "-pix_fmt", "yuv420p", str(plain)], check=True)
    subprocess.run([_REAL_FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-display_rotation:v:0", "90", "-i", str(plain),
                    "-c", "copy", str(rotated)], check=True)
    _hide_path(monkeypatch)
    _fake_imageio(monkeypatch, str(_REAL_FFMPEG))
    assert scan.video_size(str(plain)) == (320, 180)
    assert scan.video_size(str(rotated)) == (180, 320)
    frames = scan.frames_from_file(str(rotated))
    assert frames.shape[1:] == (scan.W, scan.H)  # 세로 크기(108x192)로 담는다
    assert len(frames) >= 7


def test_the_contact_sheet_uses_a_korean_font_on_a_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    """맥에는 맑은 고딕이 없다 — 기본 글꼴로 떨어지면 「3.2초 · 컷」의 한글이 네모로 찍힌다."""
    from alture_jarvis.video_read import report

    tried: list[str] = []

    def truetype(path: str, size: int) -> str:
        tried.append(path)
        if not path.startswith("/System/Library/Fonts/"):
            raise OSError("이 맥에 없는 글꼴")
        return f"font:{path}"

    monkeypatch.setattr(report.ImageFont, "truetype", truetype)
    assert report.sheet_font(22) == "font:/System/Library/Fonts/AppleSDGothicNeo.ttc"
    assert tried[0].endswith("malgun.ttf")  # 윈도우 글꼴이 먼저 — 윈도우는 그대로다


def test_the_mac_install_check_stops_without_the_packaged_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """맥 설치(`install_mac.sh` → check_bundle)는 imageio-ffmpeg 가 안 깔렸으면 멈춘다 — 영상 파일 읽기가 빠진 채로 뜨지 않게."""
    import tomllib

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging" / "msix"))
    import check_bundle

    deps = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert any(d.startswith("imageio-ffmpeg") and "Darwin" in d for d in deps)
    assert "imageio_ffmpeg" in check_bundle.MAC_REQUIRED
    monkeypatch.setattr(check_bundle, "data_root", lambda: tmp_path)
    monkeypatch.setattr(check_bundle, "REQUIRED_DATA", {})
    monkeypatch.setattr(check_bundle, "_prepare_windows_cache", lambda: None, raising=False)
    monkeypatch.setattr(check_bundle.sys, "platform", "darwin")

    def load(name: str) -> object:
        if name == "imageio_ffmpeg":
            raise ImportError("안 깔림")
        return object()

    monkeypatch.setattr(check_bundle.importlib, "import_module", load)
    monkeypatch.setattr(check_bundle.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "ok", ""))
    assert check_bundle.main() == 1
