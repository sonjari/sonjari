"""미리보기 서버는 **보는 사람이 둘이어도** 막히지 않는다 (2026-09-29 대표 목격).

제품 화면 칸이 흰 화면이었고 새로고침해도 한참 그대로였다. 같은 판 손자리 걸음엔 「스크린샷이 타임아웃 됐습니다」.
서버가 한 번에 연결 하나만 받는 `socketserver.TCPServer` 였고, 손자리의 크롬과 앱의 제품 화면 칸이 같은 서버를 쓴다.
브라우저가 요청 없이 미리 열어 둔 연결 하나가 서버를 붙잡으면 다른 요청은 전부 줄을 선다 — 그 모양을 그대로 만든다.
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from pathlib import Path

from alture_jarvis.local_computer import start_preview_server


def _serve(tmp_path: Path):
    (tmp_path / "card.html").write_text("<h1>카드</h1>", encoding="utf-8")
    return start_preview_server(tmp_path)


def test_an_idle_connection_does_not_block_the_next_viewer(tmp_path: Path) -> None:
    server = _serve(tmp_path)
    port = server.server_address[1]
    idle = socket.create_connection(("127.0.0.1", port))  # 브라우저의 미리 열어 둔 연결 — 요청을 안 보낸다
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/card.html", timeout=3) as response:
            assert response.status == 200
            assert "카드" in response.read().decode("utf-8")
    finally:
        idle.close()
        server.shutdown()
        server.server_close()


def test_the_edited_page_is_never_served_from_cache(tmp_path: Path) -> None:
    """손자리가 파일을 고친 뒤 새로고침하면 고친 판이 보여야 한다."""
    server = _serve(tmp_path)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/card.html", timeout=3) as response:
            assert response.headers.get("Cache-Control") == "no-store"
    finally:
        server.shutdown()
        server.server_close()


def test_it_only_listens_on_loopback(tmp_path: Path) -> None:
    server = _serve(tmp_path)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.shutdown()
        server.server_close()


def test_a_link_inside_the_folder_cannot_read_outside(tmp_path: Path) -> None:
    """폴더 안의 심볼릭 링크가 밖을 가리키면 404 (2026-09-29 코덱스 교차 검사 재현: 200 · OUTSIDE)."""
    import os

    import pytest

    site = tmp_path / "site"
    site.mkdir()
    (site / "card.html").write_text("ok", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("OUTSIDE", encoding="utf-8")
    try:
        os.symlink(secret, site / "linked.txt")
    except (OSError, NotImplementedError):
        pytest.skip("이 PC 는 심볼릭 링크를 만들 권한이 없다(개발자 모드 꺼짐)")
    server = start_preview_server(site)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/card.html", timeout=3) as response:
            assert response.status == 200
        with pytest.raises(urllib.error.HTTPError) as blocked:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/linked.txt", timeout=3)
        assert blocked.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
