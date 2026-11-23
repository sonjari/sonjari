"""Sonjari MCP 다리를 .mcpb 꾸러미 안에서 띄운다(2026-11-23).

꾸러미 안에는 손자리 파이썬 소스가 `src/` 에 들어 있다. 다리는 그중 `alture_jarvis.mcp_server` 만 부르고,
이미 떠 있는 손자리 앱(127.0.0.1)에 붙는다. 토큰은 앱의 토큰 파일에서 스스로 찾는다(`mcp_server.default_token_file`).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alture_jarvis.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
