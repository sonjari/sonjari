"""MCP 연결 준비 — 토큰을 만들고, 클로드 데스크톱 설정을 찍어 준다.

`/v1/tools/execute` 는 `JARVIS_CONTROL_TOKEN` 이 있어야 열린다. 지금까지 비어 있었고,
빈 값이면 **모두 거부**된다(`require_token` 이 빈 토큰을 통과시키지 않는다). 그래서
토큰을 세우는 것이 MCP 연결의 첫 단추다.

토큰을 만드는 것은 보안을 **더** 죄는 쪽이다: 8091 은 로컬에만 열려 있지만, 이 PC 에서
도는 아무 프로그램이나 브라우저 페이지가 부를 수 있는 자리다.

    python scripts/setup_mcp.py            # 있으면 그대로 쓰고 설정만 찍는다
    python scripts/setup_mcp.py --rotate   # 새 토큰으로 갈아 끼운다

.env 를 고치면 **자비스를 재시작해야** 반영된다.
"""

from __future__ import annotations

import argparse
import io
import json
import secrets
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

KEY = "JARVIS_CONTROL_TOKEN"
RUNTIME = Path(r"C:\RoboMetaFit\tools\alture-jarvis")
SOURCE = Path(__file__).resolve().parent.parent


def read_token(env_path: Path) -> str:
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line.strip().startswith(f"{KEY}="):
            return line.split("=", 1)[1].strip()
    return ""


def write_token(env_path: Path, token: str) -> None:
    """있으면 그 줄만 바꾸고, 없으면 끝에 붙인다. 나머지 줄은 손대지 않는다."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        if env_path.exists()
        else []
    )
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{KEY}="):
            lines[index] = f"{KEY}={token}"
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# MCP·외부 도구 호출용 제어 토큰 (setup_mcp.py 가 관리)")
        lines.append(f"{KEY}={token}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rotate", action="store_true", help="새 토큰으로 갈아 끼운다")
    args = parser.parse_args()

    targets = [SOURCE / ".env", RUNTIME / ".env"]
    existing = next((read_token(path) for path in targets if read_token(path)), "")

    if args.rotate or not existing:
        token = secrets.token_urlsafe(32)
        for path in targets:
            write_token(path, token)
            print(f"  기록: {path}")
        print(f"\n{'새 토큰을 만들었습니다' if not existing else '토큰을 갈아 끼웠습니다'}.")
        print("★ 자비스를 재시작해야 반영됩니다:")
        print("   scripts\\sync_to_runtime.ps1 → python 프로세스 종료 → schtasks /Run /TN RoboMetaFit-Alture-Jarvis")
    else:
        token = existing
        print("이미 토큰이 있습니다 (그대로 씁니다). 바꾸려면 --rotate")

    config = {
        "mcpServers": {
            "alture-jarvis": {
                "command": str(RUNTIME / ".venv" / "Scripts" / "python.exe"),
                "args": ["-m", "alture_jarvis.mcp_server"],
                "env": {
                    "PYTHONPATH": str(RUNTIME / "src"),
                    "PYTHONIOENCODING": "utf-8",
                    "JARVIS_CONTROL_TOKEN": token,
                    "JARVIS_BASE_URL": "http://127.0.0.1:8091",
                    # 되돌릴 수 없는 도구는 여기로 내보내지 않는다. 코드 기본값과
                    # 같지만 일부러 적어 둔다 — 나중에 "왜 메일 발송이 안 보이지"를
                    # 설정 파일에서 바로 답할 수 있어야 한다.
                    "JARVIS_MCP_MAX_RISK": "L1",
                },
            }
        }
    }

    print("\n" + "=" * 70)
    print("클로드 데스크톱 설정 (claude_desktop_config.json 에 넣으세요)")
    print("  위치: %APPDATA%\\Claude\\claude_desktop_config.json")
    print("=" * 70)
    print(json.dumps(config, indent=2, ensure_ascii=False))
    print("=" * 70)
    print("넣은 뒤 클로드 데스크톱을 완전히 종료했다 다시 켜야 합니다.")
    print("\n무엇이 나가고 무엇이 안 나가나:")
    print("  나감   읽기·조사·양식 채우기 (L0·L1, 55개)")
    print("  안 나감 되돌릴 수 없는 것 (L2, 12개) — 메일 발송·일정 삭제·블로그 발행·")
    print("          파일 업로드·프로그램 실행. 이건 자비스 창에 그대로 있습니다.")
    print("          승인 카드가 자비스 창에만 뜨기 때문입니다 — 다른 화면을 보고")
    print("          계시면 아무도 못 보고 5분 뒤 만료됩니다.")
    print("\n선택 환경변수:")
    print("  JARVIS_MCP_MAX_RISK=L2         되돌릴 수 없는 것까지 연다(승인은 그대로 걸림)")
    print("  JARVIS_MCP_INCLUDE=camera_look 기본 제외된 것을 다시 연다")
    print("  JARVIS_MCP_EXCLUDE=windows_uia_preview")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
