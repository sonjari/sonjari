# Sonjari MCP server (stdio) — for MCP directories that build and introspect servers (e.g. Glama).
#
# Sonjari itself is a Windows desktop app (Microsoft Store) that runs a local model on your own GPU.
# Its MCP server is a thin bridge to that app on 127.0.0.1:8091. In this container the app is not
# there, so the server still starts and lists its delegation tools (sonjari_task, sonjari_task_status,
# sonjari_guide); calling them says the app is not running. For real use, install the app and connect
# Claude Code / Codex from Settings › Connections.
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir "mcp==2.0.0" "httpx==0.28.1"
COPY src/alture_jarvis /app/alture_jarvis
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "alture_jarvis.mcp_server"]
