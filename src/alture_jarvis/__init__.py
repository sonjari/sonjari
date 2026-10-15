"""ALTURE JARVIS local backend."""

from .msvc_runtime import preload_newest_msvcp

# ★ 무엇이든 불러오기 전에 가장 새 C++ 런타임을 먼저 올린다 — winrt 휠의 옛 msvcp140(14.29)이 먼저 올라가면
#   음성 인식(ctranslate2)이 그 위에서 백엔드째 죽는다(2026-09-24 노트북 실측). 자세히는 msvc_runtime.py.
preload_newest_msvcp()

import warnings as _warnings

# pywinauto 가 불릴 때마다 「Apply externally defined coinit_flags」 경고를 찍는다 — 노트북 백엔드 로그 한 번 기동분 303줄 중
# 150줄이 이것이었다(2026-09-26). 우리가 일부러 정한 COM 설정이라 알릴 것이 없고, 진짜 오류를 묻는다.
_warnings.filterwarnings("ignore", message=r"Apply externally defined coinit_flags", category=UserWarning)
_warnings.filterwarnings("ignore", message=r"Revert to STA COM threading mode", category=UserWarning)

__version__ = "0.1.0"
