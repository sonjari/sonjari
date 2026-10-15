from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _scratch import scratch_root
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.browser import BrowserTools, BrowserWorker
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.ollama import OllamaClient
from alture_jarvis.tool_gateway import ToolGateway


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        body = (
            "<!doctype html><html lang='ko'><head><title>Agent E2E</title></head>"
            "<body><main><h1>JARVIS 종단 검증</h1>"
            "<p>검증 코드는 ALTURE-9274 입니다.</p>"
            "<p>이 값은 페이지를 실제로 읽어야만 알 수 있습니다.</p></main></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Chromium/SQLite can release Windows file handles a few milliseconds
    # after close; cleanup errors must not turn a successful E2E into failure.
    with scratch_root("jarvis-agent-e2e-") as root:
        config = JarvisConfig(
            runtime_root=root,
            data_dir=root / "data",
            output_dir=root / "outputs",
            browser_enabled=True,
            browser_headless=True,
            browser_read_only=True,
            browser_profile_dir=root / "profile",
            browser_download_dir=root / "downloads",
            ollama_model="plopfit-gemma4:latest",
            ollama_max_tool_steps=6,
            browser_task_timeout_sec=180,
        )
        config.prepare()
        events = EventBus()
        store = JobStore(config.database_path)
        gateway = ToolGateway(store, events)
        browser = BrowserWorker(config)
        tools = BrowserTools(config, browser)
        tools.register(gateway)
        agent = BrowserAgent(
            config,
            OllamaClient(config),
            gateway,
            browser,
            tools,
            store,
            events,
        )
        job = store.create_job("chat", "Gemma agent E2E", {"origin": "chat"})
        store.claim_next()
        try:
            url = f"http://127.0.0.1:{server.server_port}/"
            result = agent.run(
                f"전용 브라우저에서 {url} 을 직접 열고 본문을 읽어서 검증 코드를 알려줘.",
                job_id=job["id"],
                origin="chat",
            )
            if "ALTURE-9274" not in result.answer:
                raise RuntimeError(f"agent_answer_missing_verification_code:{result.answer[:300]}")
            print(
                json.dumps(
                    {
                        "ok": True,
                        "answer": result.answer,
                        "steps": [step["tool"] for step in result.steps],
                        "verification": result.verification,
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            browser.stop()
            server.shutdown()


if __name__ == "__main__":
    main()
