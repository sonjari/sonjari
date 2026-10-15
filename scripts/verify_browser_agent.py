from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _scratch import scratch_root
from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


INDEX = """<!doctype html><html lang="ko"><head><title>JARVIS 검증</title></head>
<body><h1>로컬 브라우저 검증</h1><a href="/detail">자료 보기</a>
<button type="submit">구매 확정</button></body></html>"""
DETAIL = """<!doctype html><html lang="ko"><head><title>검증 상세</title></head>
<body><h1>검증 완료</h1><p>지속형 브라우저가 ref로 링크를 열고 본문을 읽었습니다.</p></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        body = DETAIL if self.path == "/detail" else INDEX
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with scratch_root("jarvis-browser-smoke-") as root:
        config = JarvisConfig(
            runtime_root=root,
            data_dir=root / "data",
            output_dir=root / "outputs",
            browser_enabled=True,
            browser_headless=True,
            browser_read_only=True,
            browser_profile_dir=root / "profile",
            browser_download_dir=root / "downloads",
        )
        config.prepare()
        worker = BrowserWorker(config)
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            opened = worker.execute("browser_open", {"url": base_url})
            snapshot = worker.execute("browser_snapshot", {})
            link = next(item for item in snapshot["elements"] if item["name"] == "자료 보기")
            worker.execute("browser_click", {"ref": link["ref"]})
            detail = worker.execute("browser_read", {})
            if "검증 완료" not in detail["text"]:
                raise RuntimeError("browser_read_verification_failed")
            overlay_visible = worker._submit(
                lambda: worker._page.locator("#__alture_jarvis_visual").count() == 1
            )
            if not overlay_visible:
                raise RuntimeError("browser_visual_overlay_missing")

            worker.execute("browser_back", {})
            snapshot = worker.execute("browser_snapshot", {})
            risky = next(item for item in snapshot["elements"] if item["name"] == "구매 확정")
            blocked = ""
            try:
                worker.execute("browser_click", {"ref": risky["ref"]})
            except RuntimeError as exc:
                blocked = str(exc)
            if "read_only_action_blocked" not in blocked:
                raise RuntimeError("risky_action_was_not_blocked")

            # Closing the last persistent window must not leave a stale
            # `started=true` context. The next action should recover it.
            worker._submit(lambda: worker._context.close())
            recovered = worker.execute("browser_open", {"url": base_url})
            if recovered["title"] != "JARVIS 검증":
                raise RuntimeError("browser_auto_recovery_failed")

            print(
                json.dumps(
                    {
                        "ok": True,
                        "persistent": worker.status()["started"],
                        "opened": opened["url"],
                        "detail_title": detail["title"],
                        "ref_click_verified": True,
                        "visual_overlay_verified": True,
                        "risky_action_blocked": True,
                        "closed_window_auto_recovered": True,
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            worker.stop()
            server.shutdown()


if __name__ == "__main__":
    main()
