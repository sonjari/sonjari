"""W2 라이브 — 「Ollama 설치」 버튼이 하는 일을 실제 공식 릴리스로 한 번 돈다.

운영 Ollama(11434)와 안 부딪히게 **다른 포트(기본 11534)** 와 빈 모델 폴더로 켰다가 끈다.
받은 zip 은 공식 `sha256sum.txt`·자산 digest 와 대조한 뒤에만 푼다(`OllamaInstaller.install`).

    python scripts/live_ollama_install_check.py --root C:\\RoboMetaFit\\tools\\ollama_install_check
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alture_jarvis.ollama_install import OllamaInstaller  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--port", type=int, default=11534)
    args = ap.parse_args()
    root = Path(args.root)
    events: list[dict] = []
    last = [0.0]

    def publish(_name: str, payload: dict) -> None:
        if payload.get("phase") != "downloading" or time.monotonic() - last[0] > 15:
            last[0] = time.monotonic()
            events.append({k: payload.get(k) for k in ("phase", "received", "total", "version", "error")})
            print(json.dumps(events[-1], ensure_ascii=False), flush=True)

    installer = OllamaInstaller(install_root=root / "data" / "ollama", base_url=f"http://127.0.0.1:{args.port}",
                                models_dir=str(root / "models"), publish=publish)
    started = time.time()
    release = installer.resolve()
    print("release", json.dumps(release), flush=True)
    result = installer.install()
    result["elapsed_sec"] = round(time.time() - started, 1)
    result["status"] = {k: v for k, v in installer.status().items() if k in ("running", "version", "bundled", "managed")}
    print("result", json.dumps(result, ensure_ascii=False), flush=True)
    installer.stop()
    time.sleep(2)
    result["after_stop_running"] = bool(installer.running_version())
    (root / "result.json").write_text(json.dumps({"release": release, "result": result, "events": events},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print("after_stop_running", result["after_stop_running"])


if __name__ == "__main__":
    main()
