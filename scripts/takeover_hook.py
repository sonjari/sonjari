"""클로드 코드 훅 — 다시 열렸을 때 「자비스가 한도 동안 이어서 한 일」을 대화에 넣는다 (전략안 §44 H2).

    settings.json 의 SessionStart(startup|resume) 에서 불린다. `mcp_connect.ConnectService.set_hook` 이 등록한다.

규칙:
- **표준 라이브러리만.** 클로드가 세션을 열 때마다 뜨므로 가벼워야 한다.
- **실패는 조용히.** 자비스가 꺼져 있거나 토큰이 없으면 아무것도 안 찍고 0 으로 끝난다 —
  훅 오류가 사용자의 클로드 세션을 방해하면 안 된다.
- 토큰은 인자로 받지 않고 **파일 경로**만 받는다. 설정 파일에 비밀을 안 남긴다.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=["session-start"])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        cwd = str(payload.get("cwd") or "")
        with open(args.token_file, encoding="utf-8-sig") as fh:
            token = fh.read().strip()
        url = f"{args.base_url.rstrip('/')}/v1/takeover/review-context?cwd={urllib.parse.quote(cwd)}"
        request = urllib.request.Request(url, headers={"X-JARVIS-TOKEN": token})
        with urllib.request.urlopen(request, timeout=3) as response:
            text = str(json.loads(response.read().decode("utf-8")).get("context") or "")
    except Exception:
        return 0
    if text:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                            "additionalContext": text}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
