"""MCP 서버를 **클로드 데스크톱이 하는 그대로** 몰아 본다.

stdio 로 프로세스를 띄우고 initialize → tools/list → tools/call 을 실제로 주고받는다.
브리지 단위 테스트가 통과해도 프로토콜 handshake 나 stdout 오염 때문에 실제 연결이
안 되는 일이 흔해서, 그 구간을 여기서 따로 지킨다.

읽기만 한다 — 되돌릴 수 없는 도구는 부르지 않는다.

    python scripts/verify_mcp_server.py
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RUNTIME = Path(r"C:\RoboMetaFit\tools\alture-jarvis")


def _token() -> str:
    for env_path in (RUNTIME / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.strip().startswith("JARVIS_CONTROL_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    token = _token()
    if not token:
        print("✗ JARVIS_CONTROL_TOKEN 을 못 찾았다 — scripts/setup_mcp.py 를 먼저 돌려라")
        return 1

    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(RUNTIME / "src"),
        "PYTHONIOENCODING": "utf-8",
        "JARVIS_CONTROL_TOKEN": token,
        "JARVIS_BASE_URL": "http://127.0.0.1:8091",
    })
    params = StdioServerParameters(
        command=str(RUNTIME / ".venv" / "Scripts" / "python.exe"),
        args=["-m", "alture_jarvis.mcp_server"],
        env=env,
    )

    failures: list[str] = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print(f"1) initialize  OK — 서버 이름 '{info.server_info.name}'")

            listed = await session.list_tools()
            tools = listed.tools
            names = {tool.name for tool in tools}
            print(f"2) tools/list  {len(tools)}개")

            if not tools:
                failures.append("도구가 0개다")
            if any(name.startswith(("camera_", "ui_")) for name in names):
                failures.append("물리 장치 도구가 기본으로 노출됐다")

            search = next((tool for tool in tools if tool.name == "browser_search"), None)
            if search is None:
                failures.append("browser_search 가 없다")
            else:
                props = (search.input_schema or {}).get("properties") or {}
                print(f"   browser_search 인자: {sorted(props)}")
                if "query" not in props or "tab" not in props:
                    failures.append("browser_search 스키마가 비어 있다 — 모델이 인자를 지어낸다")

            # 되돌릴 수 없는 것은 기본으로 안 나간다(사용자님 결정). 승인을 건너뛰는 게
            # 아니라 능력을 안 주는 것이다 — 승인 카드는 자비스 창에만 뜨므로,
            # 다른 화면을 보고 있으면 아무도 못 보고 5분 뒤 만료된다.
            IRREVERSIBLE = {
                "google_gmail_send", "google_calendar_delete", "google_calendar_create",
                "google_drive_write",
                "naver_blog_publish", "browser_file_upload", "windows_execute_preview",
            }
            leaked = sorted(IRREVERSIBLE & names)
            print(f"   되돌릴 수 없는 도구 노출: {leaked or '없음 (기대대로)'}")
            if leaked:
                failures.append(f"되돌릴 수 없는 도구가 기본으로 나갔다: {leaked}")

            print("3) tools/call  gpu_status (읽기)")
            result = await session.call_tool("gpu_status", {})
            text = "".join(getattr(block, "text", "") for block in result.content)
            print(f"   응답 {len(text)}자: {text[:110].replace(chr(10), ' ')}")
            if not text:
                failures.append("도구 호출이 빈 응답을 줬다")

            print("4) tools/call  browser_search (실제 검색, 읽기만)")
            result = await session.call_tool(
                "browser_search",
                {"query": "제주도 3박4일 여행 경비", "engine": "naver", "tab": "blog", "limit": 3},
            )
            text = "".join(getattr(block, "text", "") for block in result.content)
            print(f"   응답 {len(text)}자")
            if '"rank"' not in text:
                failures.append("검색 결과에 rank 가 없다")
            if "제주" not in text:
                failures.append("한글이 깨졌거나 결과가 비었다")
            else:
                for line in [row for row in text.splitlines() if '"title"' in row][:3]:
                    print(f"     {line.strip()[:88]}")

    # ---- 일부러 열었을 때: 나오되, 경고가 붙고, 승인 없이는 실행되지 않는가 --------
    print("\n5) JARVIS_MCP_MAX_RISK=L2 로 열었을 때")
    env_open = dict(env)
    env_open["JARVIS_MCP_MAX_RISK"] = "L2"
    params_open = StdioServerParameters(
        command=params.command, args=list(params.args), env=env_open
    )
    async with stdio_client(params_open) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            names = {tool.name for tool in tools}
            warned = [tool for tool in tools if "되돌릴 수 없" in (tool.description or "")]
            print(f"   도구 {len(tools)}개 · 경고 문구 붙은 것 {len(warned)}개")
            if "google_gmail_send" not in names:
                failures.append("열었는데도 L2 도구가 안 나온다")
            if not warned:
                failures.append("L2 도구에 경고 문구가 안 붙었다")

    print("\n" + "=" * 66)
    if failures:
        for line in failures:
            print(f"  ✗ {line}")
        return 1
    print("  ✓ handshake · 도구 목록 · 스키마 · 실제 호출 통과")
    print("  ✓ 되돌릴 수 없는 도구는 기본으로 안 나가고, 열면 경고와 함께 나온다")
    print("  ✓ 클로드 데스크톱에 붙일 준비가 됐다")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
