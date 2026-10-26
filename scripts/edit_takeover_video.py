"""레딧 영상 편집 — 손자리 이어받기 한 판(takeover2.mp4)을 자르지 않고 속도만 바꿔 붙인다 (2026-10-23).

- 장면은 그대로 이어진다(빼는 구간 없음). 바꾸는 것은 속도 · 맨 아래 틈 자르기 · 클로드 데스크톱 알림 가리기 · 윗띠 글.
- 알림(사람의 다른 작업 제목)은 그 자리만 흐리게. 화면 맨 아래 틈(창이 1023 줄에서 끝남 — 뒤 창이 비침)은 잘라 낸다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
WORK = OUT.parent / "edit_work"
WORK.mkdir(parents=True, exist_ok=True)
FFMPEG = Path(os.environ["LOCALAPPDATA"]) / r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
W, H = 1920, 1020          # 원본 1920x1032 에서 아래 틈을 자른 크기
BAR = 56                   # 윗띠
FONT_B = "C\\:/Windows/Fonts/segoeuib.ttf"
FONT = "C\\:/Windows/Fonts/segoeui.ttf"
TITLE = "Claude Code hit its usage limit. Sonjari picks up where it stopped"
INFO = "RTX 3090 · Qwen3.8 27B on this PC"
# 클로드 데스크톱 알림이 뜬 구간(원본 초) — 앞뒤로 여유를 둔다.
TOASTS = [(21.8, 39.5), (39.75, 46.0), (244.75, 251.0), (296.75, 303.0), (453.75, 456.4)]
TOAST_BOX = (1500, 840, 420, 180)  # x, y, w, h
# (시작, 끝, 배속, 밑줄 글)
SEGMENTS = [
    (0.0, 2.6, 2.0, "setup"),
    (2.6, 15.5, 1.5, "setup"),
    (15.5, 22.0, 1.0, "setup"),
    (22.0, 370.0, 14.0, ""),
    (370.0, 385.0, 3.0, ""),
    (385.0, 428.0, 14.0, ""),
    (428.0, 456.4, 2.0, ""),
]
SETUP_NOTE = ("Demo setup: the Claude Code session really ran. Only its limit line was added for this video. "
              "Everything Sonjari does after this is a real run, only sped up.")


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace(",", "\\,")


def run(cmd: list[str]) -> None:
    subprocess.run([str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error", *cmd], check=True)


def main() -> int:
    # 1) 자르기 + 알림 가리기(원본 시각 기준)
    x, y, w, h = TOAST_BOX
    enable = "+".join(f"between(t\\,{a - 0.5:.2f}\\,{b + 0.5:.2f})" for a, b in TOASTS)
    base = WORK / "base.mp4"
    run(["-i", str(SRC), "-filter_complex",
         f"[0:v]crop={W}:{H}:0:0,split[m][c];[c]crop={w}:{h}:{x}:{y},boxblur=24:4[b];"
         f"[m][b]overlay={x}:{y}:enable='{enable}'[v]",
         "-map", "[v]", "-c:v", "libx264", "-crf", "14", "-preset", "fast", "-pix_fmt", "yuv420p", str(base)])
    # 2) 구간마다 속도 + 윗띠 글
    parts = []
    for i, (a, b, speed, note) in enumerate(SEGMENTS):
        label = f"{speed:g}x speed" if speed != 1 else "real time"
        draws = [
            f"pad={W}:{H + BAR}:0:{BAR}:color=0x111111",
            f"drawtext=fontfile='{FONT_B}':text='{esc(TITLE)}':x=20:y=15:fontsize=26:fontcolor=white",
            f"drawtext=fontfile='{FONT}':text='{esc(label + '  ·  ' + INFO)}':x=w-tw-20:y=18:fontsize=22:fontcolor=0xd8d8d8",
        ]
        if note == "setup":
            draws.append(f"drawbox=x=0:y=h-58:w=iw:h=58:color=black@0.72:t=fill")
            draws.append(f"drawtext=fontfile='{FONT}':text='{esc(SETUP_NOTE)}':x=(w-tw)/2:y=h-42:fontsize=20:fontcolor=0xf2c94c")
        part = WORK / f"part{i}.mp4"
        run(["-ss", f"{a}", "-to", f"{b}", "-i", str(base), "-filter_complex",
             f"[0:v]setpts=(PTS-STARTPTS)/{speed},{','.join(draws)},fps=30[v]",
             "-map", "[v]", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", str(part)])
        parts.append(part)
    listing = WORK / "parts.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c:v", "libx264", "-crf", "20", "-preset", "slow",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT)])
    print("saved", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
