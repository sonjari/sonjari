"""만든 파일을 사람에게 띄운다 — **여는 프로그램이 없는 PC 에서도** 창이 터지지 않게.

2026-10-05 AWS 영어 윈도우 새 PC 첫 실행. 과제가 끝나며 손자리가 만든 `comparison_table_arxiv_cscl_papers.md` 를
`os.startfile` 로 열자 윈도우가 「Windows can't open this type of file (.md)」 창을 띄웠다. 새 윈도우에는 `.md` 를 여는
프로그램이 없다(개발자 PC 에는 편집기가 깔려 있어 한 번도 못 봤다). 일은 잘 끝났는데 마지막 화면이 오류 창이었다.

여는 자리가 셋이었다(판이 끝날 때 · 「열기」 도구 · 산출물 카드의 열기). 한 곳에서 정한다:

- 연결된 프로그램이 있으면 예전대로 그 프로그램으로 연다.
- 없고 **글로 된 파일**이면 메모장으로 연다 — 메모장은 모든 윈도우에 있다.
- 없고 글도 아니면 탐색기에서 그 파일을 **짚어 보여 준다**(무엇으로 열지는 사람이 고른다).
"""
from __future__ import annotations

from . import winapi  # 11-03: 윈도우 API 크기는 winapi.py 한 곳에서(백엔드 0xc0000005 사고)

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

#: 메모장으로 읽을 수 있는 글 파일. 연결된 프로그램이 없을 때만 쓴다.
TEXT_LIKE = frozenset({
    ".md", ".markdown", ".txt", ".log", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".xml", ".ini", ".toml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html", ".htm", ".sql", ".sh", ".ps1", ".bat", ".c", ".cpp", ".h",
    ".java", ".go", ".rs", ".rb", ".php", ".srt", ".tex",
})

_ASSOCF_NONE = 0
_ASSOCSTR_EXECUTABLE = 2


def associated_app(suffix: str) -> str:
    """이 확장자를 여는 프로그램의 경로. 없으면 빈 문자열(윈도우의 「앱 고르기」 창은 프로그램으로 치지 않는다)."""
    if os.name != "nt" or not suffix:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        result = winapi.shlwapi.AssocQueryStringW(  # type: ignore[attr-defined]
            _ASSOCF_NONE, _ASSOCSTR_EXECUTABLE, suffix, None, buffer, ctypes.byref(size))
    except Exception:  # noqa: BLE001 — 못 물어보면 「있다」로 보고 예전대로 연다(아래 open_file)
        return "unknown"
    if result != 0:
        return ""
    found = buffer.value.strip()
    return "" if Path(found).name.casefold() == "openwith.exe" else found


#: `open_file` 이 연결 프로그램을 묻는 문. 시험은 이것을 갈아 끼운다 — **그 기계에 워드가 깔려 있나**가 시험 결과를
#: 바꾸면 안 된다(2026-10-06: 공개 저장소의 깨끗한 기계에서 `.docx` 를 여는 시험 넷이 진짜 탐색기를 띄우고 떨어졌다).
_ask_windows: Callable[[str], str] = associated_app


def open_file(
    path: Path,
    *,
    associated: Callable[[str], str] | None = None,
    startfile: Callable[[str], Any] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
) -> str:
    """파일(이나 폴더)을 띄운다. 돌려주는 값: `app`(연결된 프로그램) · `notepad` · `revealed`(탐색기에서 짚음)."""
    target = str(path)
    if sys.platform == "darwin" and startfile is None:
        return _open_on_mac(target, popen=popen if popen is not subprocess.Popen else None)
    launch = startfile or getattr(os, "startfile")
    ask = associated or _ask_windows
    if Path(target).is_dir() or ask(Path(target).suffix.lower()):
        launch(target)
        return "app"
    if Path(target).suffix.lower() in TEXT_LIKE:
        popen(["notepad.exe", target])  # noqa: S603,S607 — 윈도우에 늘 있는 메모장, 우리가 만든 파일 하나
        return "notepad"
    popen(["explorer.exe", f"/select,{target}"])  # noqa: S603,S607
    return "revealed"


def _open_on_mac(target: str, *, popen: Callable[..., Any] | None = None,
                 run: Callable[..., Any] | None = None) -> str:
    """맥(2026-11-03 · 전수조사 B6): `open` 이 연결된 앱으로 연다. 여는 앱이 없으면 `open` 이 실패하니(오류 창 없음)
    글 파일은 텍스트 편집기로, 그 밖은 파인더에서 짚어 보여 준다 — 윈도우의 메모장 · 탐색기 갈래와 같은 뜻."""
    popen = popen or subprocess.Popen
    done = (run or subprocess.run)(["open", target], capture_output=True, text=True, timeout=15)  # noqa: S603,S607
    if getattr(done, "returncode", 1) == 0:
        return "app"
    if Path(target).suffix.lower() in TEXT_LIKE:
        popen(["open", "-e", target])  # noqa: S603,S607 — 맥에 늘 있는 텍스트 편집기
        return "notepad"
    popen(["open", "-R", target])  # noqa: S603,S607
    return "revealed"


def reveal_file(path: Path, *, popen: Callable[..., Any] | None = None) -> bool:
    """파일을 탐색기(윈도우) · 파인더(맥)에서 **짚어** 보여 준다. 못 하는 OS 면 False."""
    target = str(path)
    # ★ 부를 때 찾는다 — 기본값으로 붙잡으면 시험이 갈아 끼운 가짜 대신 진짜 탐색기가 뜬다(11-03 실제로 한 번 떴다).
    popen = popen or subprocess.Popen
    if sys.platform == "darwin":
        popen(["open", "-R", target])  # noqa: S603,S607
        return True
    if os.name == "nt":
        popen(["explorer.exe", f"/select,{target}"])  # noqa: S603,S607
        return True
    return False


def open_folder_or_url(target: str, *, popen: Callable[..., Any] | None = None) -> bool:
    """폴더나 주소를 그 OS 의 기본 앱으로(윈도우 `os.startfile` · 맥 `open`). 못 하는 OS 면 False."""
    popen = popen or subprocess.Popen
    if sys.platform == "darwin":
        popen(["open", target])  # noqa: S603,S607
        return True
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
        return True
    return False
