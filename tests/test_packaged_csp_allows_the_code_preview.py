"""포장판도 코드 모드 미리보기를 끼워 보여 줄 수 있어야 한다 (2026-09-23 스토어 촬영에서 발견).

개발용 `tauri.conf.json` 에만 `frame-src http://127.0.0.1:* http://localhost:*` 가 있었고 포장판 설정(msix·store·e2e)엔
없었다. 그래서 **설치한 사용자는 코드 모드 「제품 화면」이 늘 금지 표시**였다 — 개발용 앱에서만 돼서 우리 시험이 못 잡았다.
설정이 여러 벌이면 한 벌만 고치는 병(사고 Q)이 그대로 온다 — 전부 같은 줄을 갖는지 본다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

TAURI = Path(__file__).resolve().parents[1] / "ui" / "src-tauri"
NEEDED = "frame-src http://127.0.0.1:* http://localhost:*"


@pytest.mark.parametrize("name", ["tauri.conf.json", "tauri.msix.conf.json", "tauri.store.conf.json", "tauri.e2e.conf.json"])
def test_every_build_lets_the_preview_frame_load_local_pages(name: str) -> None:
    csp = json.loads((TAURI / name).read_text(encoding="utf-8"))["app"]["security"]["csp"]
    assert NEEDED in csp, f"{name} 의 CSP 에 미리보기 허용이 없다 — 포장판 코드 모드 미리보기가 막힌다"


def test_the_preview_is_limited_to_this_pc() -> None:
    """★ 좋은 표본 — 허용은 이 PC 주소뿐이다. 바깥 사이트를 끼워 넣는 길은 열지 않는다."""
    for name in ("tauri.msix.conf.json", "tauri.store.conf.json"):
        csp = json.loads((TAURI / name).read_text(encoding="utf-8"))["app"]["security"]["csp"]
        frame = next(part for part in csp.split(";") if part.strip().startswith("frame-src"))
        assert "https:" not in frame and "*." not in frame and frame.strip().split()[1:] == ["http://127.0.0.1:*", "http://localhost:*"]
