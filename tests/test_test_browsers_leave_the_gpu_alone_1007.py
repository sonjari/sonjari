"""검사가 띄우는 브라우저는 그래픽카드를 쓰지 않는다 (2026-10-07 — `conftest.py` 의 같은 이름 고정물).

회귀를 돌리자 화면이 연결된 그래픽카드의 드라이버가 응답을 놓쳐 대표의 게임이 꺼졌다. 검사가 띄우는 브라우저마다
`--disable-gpu` 가 붙는지를, 띄운 브라우저 **프로세스의 명령줄**로 본다(인자를 넘겼다는 말이 아니라 실제로 붙었는지).
"""
from __future__ import annotations

import subprocess

import pytest


def _headless_command_lines() -> list[str]:
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'chrom*' -or $_.Name -like 'headless*' } | "
         "ForEach-Object { $_.CommandLine }"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
    )
    return [line for line in (done.stdout or "").splitlines() if "--headless" in line and "--type=" not in line]


def test_a_browser_a_test_launches_is_told_not_to_use_the_gpu() -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--user-agent=sonjari-gpu-check"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            mine = [line for line in _headless_command_lines() if "sonjari-gpu-check" in line]
        finally:
            browser.close()
    assert mine, "띄운 브라우저의 명령줄을 찾지 못했다"
    assert all("--disable-gpu" in line for line in mine), mine
