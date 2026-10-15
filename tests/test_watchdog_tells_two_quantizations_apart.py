"""워치독은 같은 저장소의 두 양자화를 **다른 모델**로 본다 (2026-10-10).

「올라와 있는 모델만 찌른다」는 규칙이 있었는데 이름을 콜론 앞부분만 비교했다. 허깅페이스 이름은 양자화가 콜론 뒤에 온다 —
`…-GGUF:…IQ3_S-mtp.gguf` 와 `…-GGUF:…IQ3_XXS-mtp.gguf` 는 콜론 앞이 같다. 운영 모델만 올라와 있는데 작은 판도 올라와 있다고
보고 둘 다 찔렀고, 자리가 하나뿐이라 5분마다 서로를 밀어냈다(하루 종일 시간당 12번 · 사용자의 다음 말이 17~27초 적재를 기다림).

눈금 주의: 이 시험은 비교 함수만 본다. 「실제로 안 밀어낸다」는 워치독 기록(`ollama_watchdog.log`)과 Ollama 기록으로 확인했다.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

# 세 단계 위가 없는 얕은 폴더(예: `E:\somewhere\tests`)에 받아도 모으는 단계에서 넘어지지 않게 — 없으면 아래에서 건너뛴다.
_ABOVE = Path(__file__).resolve().parents
SCRIPT = _ABOVE[min(3, len(_ABOVE) - 1)] / "scripts" / "watchdog_ollama.ps1"
pytestmark = [
    pytest.mark.skipif(not SCRIPT.exists(), reason="워치독 스크립트는 이 PC 의 운영 저장소에만 있다"),
    pytest.mark.skipif(sys.platform != "win32", reason="PowerShell 스크립트"),
]

REPO = "hf.co/someone/Some-Model-27B-GGUF"
BIG = f"{REPO}:Some-Model-27B-IQ3_S-mtp.gguf"
SMALL = f"{REPO}:Some-Model-27B-IQ3_XXS-mtp.gguf"

CASES = [
    (BIG, SMALL, False),            # 같은 저장소 · 다른 양자화 — 이번 사고
    (BIG, BIG, True),
    (BIG, BIG.upper(), True),
    ("somemodel", "somemodel:latest", True),   # 꼬리표가 없으면 :latest — 이 한 가지만 같게 친다
    ("somemodel:27b", "somemodel:9b", False),
    ("somemodel:27b", "somemodel", False),
    ("library/somemodel", "library/somemodel:latest", True),
    ("", BIG, False),
    ("", "", False),
]


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def _functions() -> str:
    text = _text()
    found = []
    for name in ("Get-OllamaModelKey", "Test-SameOllamaModel"):
        match = re.search(r"^function " + re.escape(name) + r"\(.*?^\}", text, re.S | re.M)
        assert match, f"{name} 이 없다"
        found.append(match.group(0))
    return "\n".join(found)


def test_same_model_is_decided_by_the_whole_name() -> None:
    lines = [_functions()]
    for a, b, _ in CASES:
        lines.append(f"[string](Test-SameOllamaModel '{a}' '{b}')")
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "\n".join(lines)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-400:]
    got = [line.strip() == "True" for line in done.stdout.split() if line.strip() in ("True", "False")]
    assert got == [want for _, _, want in CASES], list(zip(CASES, got))


def test_nothing_compares_only_the_part_before_the_colon() -> None:
    """콜론 앞부분만 비교하는 자리가 하나라도 남으면 같은 사고가 그 자리에서 다시 난다."""
    assert ".Split(':')[0]" not in _text()
    assert _text().count("Test-SameOllamaModel") >= 7
