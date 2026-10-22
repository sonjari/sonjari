"""클로드 코드 훅 — 서기 카드를 압축 · 새 세션 때 다시 넣는다 (2026-10-22 · 대표 PC 의 손 훅을 제품으로 옮김).

**표준 라이브러리만 쓴다** — 클로드 코드가 이 파일을 따로 띄운다(개발 판은 파일 경로로, 스토어 판은 실행 별칭 `-m` 으로).
손자리 본체는 HTTP 로만 부른다. 손자리가 꺼져 있어도 훅은 조용히 끝난다(클로드 코드를 막지 않는다).

    after-compact --base-url URL --token-file PATH [--style-file PATH]
        SessionStart 훅. source=compact 면 (작업방식 · 주제 색인 · 카드)를, startup 이면 바로 앞 대화의 주제 색인을 넣는다.
    save-compact --base-url URL --token-file PATH --log-dir DIR
        PostCompact 훅. 압축 요약과 그 순간의 카드를 같이 남긴다 — 결정이 얼마나 살아남는지 나중에 셀 재료(채점은 아직 안 함).
    open-line <기록 파일> <줄 번호> [앞뒤 말 수]
        주제 색인의 줄 번호를 여는 손 — 그 줄과 앞뒤 사람 · 클로드 말을 보여 준다.

설계: `docs/` 와 README 의 「서기 흐름」. 열쇠(control.token)는 읽기만 하고 어디에도 찍지 않는다.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

#: 훅 출력이 1만 자를 넘으면 클로드 코드가 파일 경로 + 미리보기로 바꾸고 읽으라고 하지 않는다(10-21 r/ClaudeCode sertanhlvcii).
TEXT_MAX = 9_000
CARD_MAX = 8_000
STARTUP_MAX = 3_000
_WHERE_WITH_QUOTE = re.compile(r"\s*\(((?:[^()·]*·\s*)?줄\s*\d+)\s*·\s*「[^」]*」\)\s*$")
_SECTIONS = (("정한 것", "정한 것"), ("버린 것", "버린 것"), ("남은 일", "남은 일"), ("사람이 거듭 고쳐 준 것", "고쳐 준 것"))


def _args(argv: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    key = ""
    for item in argv:
        if item.startswith("--"):
            key = item[2:]
            out[key] = ""
        elif key:
            out[key] = item
            key = ""
    return out


def _story(base_url: str, token_file: str, session: str) -> dict:
    """서기 이야기(`/v1/scribe/story`). 못 받으면 {"_missing": 까닭}."""
    token_path = Path(token_file)
    if not session or not token_path.exists():
        return {"_missing": "손자리 열쇠 파일이 없음"}
    try:
        url = f"{base_url.rstrip('/')}/v1/scribe/story?{urllib.parse.urlencode({'session': session, 'limit': 40})}"
        req = urllib.request.Request(url, headers={"X-JARVIS-TOKEN": token_path.read_text(encoding="utf-8-sig").strip()})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — 손자리가 없어도 클로드 코드는 계속돼야 한다
        return {"_missing": "손자리에 닿지 못함"}
    if data.get("enabled") is False:
        return {"_missing": "서기가 꺼져 있음"}
    return data


def newest_first_without_quotes(card: str) -> str:
    """칸마다 최신 카드부터, 근거 인용은 빼고 시각 · 줄 번호만 — 한도에 걸리면 오래된 카드가 잘린다(10-22 AndreyBegma)."""
    out: list[str] = []
    items: list[str] = []

    def flush() -> None:
        out.extend(reversed(items))
        items.clear()

    for line in card.splitlines():
        if line.startswith("- "):
            items.append(_WHERE_WITH_QUOTE.sub(lambda m: f"  ({m.group(1).strip()})", line))
            continue
        flush()
        out.append(line)
    flush()
    return "\n".join(out)


#: 줄 여는 명령의 앞부분 — 스토어 판은 설치하는 쪽이 넘긴 `--alias`(실행 별칭), 개발 판은 이 파일 경로.
_OPEN_LINE_PREFIX: list[str] = []


def _open_line_command(transcript: str) -> str:
    prefix = _OPEN_LINE_PREFIX[0] if _OPEN_LINE_PREFIX else f'"{_python()}" "{Path(__file__).resolve().as_posix()}"'
    return f'{prefix} open-line "{Path(transcript).as_posix()}" <줄 번호>'


def _python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return exe.with_name("python.exe").as_posix()
    return exe.as_posix()


def index_block(data: dict, transcript: str, title: str) -> str:
    text = str(data.get("index") or "").strip()
    if not text:
        return ""
    dropped = int(data.get("index_dropped") or 0)
    more = f"\n(주제 {dropped}개는 상한 때문에 뺐다 — sonjari_story 로)" if dropped else ""
    return (f"## {title}\n"
            "자세한 내용은 요약이 아니라 **대화 기록 파일의 그 줄**에 그대로 있다. 필요한 주제만 연다(다 열지 않는다):\n"
            f"`{_open_line_command(transcript)}`\n" + text + more)


def _notice(text: str, missing: str, cut: bool) -> str:
    if missing:
        return f"대화가 접혔습니다. 서기 카드는 못 넣었습니다({missing})."
    counts: dict[str, int] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            current = next((short for name, short in _SECTIONS if title.startswith(name)), "")
        elif current and line.startswith("- "):
            counts[current] = counts.get(current, 0) + 1
    body = " · ".join(f"{short} {counts[short]}" for _, short in _SECTIONS if counts.get(short))
    tail = " (9,000자 한도로 일부 잘림)" if cut else ""
    return f"대화가 접혔습니다. 서기 카드를 다시 넣었습니다 — {body or '카드 0'}{tail}."


def after_compact(payload: dict, opts: dict[str, str]) -> dict | None:
    base, token = opts.get("base-url", "http://127.0.0.1:8091"), opts.get("token-file", "")
    if opts.get("alias"):
        # 스토어 판: 앱 안 파이썬은 밖에서 못 띄운다 — 실행 별칭으로(`mcp_connect.server_entry` 와 같은 길).
        _OPEN_LINE_PREFIX[:] = [f'"{Path(opts["alias"]).as_posix()}" -m alture_jarvis.claude_hooks']
    session = str(payload.get("session_id") or "")
    transcript = str(payload.get("transcript_path") or "")
    if str(payload.get("source") or "compact") != "compact":
        return _new_session(payload, base, token)
    parts = ["[압축 직후 다시 넣음] 대화가 방금 접혔다. 요약은 오래된 결정을 잃는다. 아래는 요약이 아니라 파일에서 새로 읽은 것이니 "
             "요약보다 우선한다."]
    style_file = opts.get("style-file", "")
    if style_file:
        try:
            style = Path(style_file).read_text(encoding="utf-8").strip()
            if style:
                parts.append("## 일하는 방식(지시로 따를 것)\n" + style)
        except OSError:
            pass
    data = _story(base, token, session)
    missing = str(data.get("_missing") or "")
    if not missing and not int(data.get("count") or 0):
        missing = "이 대화의 카드가 아직 없음"
    block = "" if missing else index_block(data, transcript, "이 대화의 주제 색인(주제 → 날짜 · 줄 번호)")
    if block:
        parts.append(block)
    if not missing:
        card = newest_first_without_quotes(str(data.get("card") or "").strip())[:CARD_MAX]
        parts.append("## 이 대화에서 정한 것 · 버린 것 · 남은 일(서기 카드, 근거 줄 포함)\n"
                     "주의: 「남은 일」은 그 줄이 쓰인 시점의 것이라 이미 끝났거나 뒤집혔을 수 있다. 행동하기 전에 기록(git · 파일 · "
                     "최근 대화)으로 확인한다. 칸마다 최신 카드가 위에 있다. 같은 주제에서 줄 번호가 큰 카드가 나중 결정이다.\n" + card)
    text = "\n\n".join(parts)
    cut = len(text) > TEXT_MAX
    if cut:
        text = text[: TEXT_MAX - 100].rsplit("\n", 1)[0] + "\n(9,000자 한도로 잘림 — 나머지 카드는 sonjari_story 로)"
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text},
            "systemMessage": _notice(text, missing, cut)}


def _new_session(payload: dict, base: str, token: str) -> dict | None:
    """새 세션: 같은 폴더에서 바로 앞 대화의 주제 색인만 펼쳐 준다. 없으면 아무것도 안 넣는다."""
    here = Path(str(payload.get("transcript_path") or ""))
    folder = here.parent if here.name else None
    if folder is None or not folder.is_dir():
        return None
    others = sorted((p for p in folder.glob("*.jsonl") if p.stem != str(payload.get("session_id") or "")),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    for previous in others[:3]:
        data = _story(base, token, previous.stem)
        if data.get("_missing"):
            return None
        block = index_block(data, str(previous), f"바로 앞 대화의 주제 색인({previous.stem[:8]})")
        if block:
            text = ("[새 세션] 바로 앞 대화에서 다룬 주제다. 지금 일과 이어지는 주제가 있으면 그 줄만 열어 본다 — 사실처럼 믿지 말고, "
                    "결정은 기록 · git 으로 확인한다.\n\n" + block)[:STARTUP_MAX]
            count = text.count("\n- ")
            return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text},
                    "systemMessage": f"새 세션 — 앞 대화의 주제 색인을 펼쳐 두었습니다({count}개 주제)."}
    return None


def save_compact(payload: dict, opts: dict[str, str]) -> dict | None:
    """압축 요약과 그 순간의 카드를 남긴다. 실패해도 조용히."""
    summary = ""
    for key in ("compact_summary", "summary"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            summary = payload[key]
            break
    else:
        summary = next((v for k, v in payload.items() if "summary" in k.lower() and isinstance(v, str) and v.strip()), "")
    session = str(payload.get("session_id") or "unknown")
    folder = Path(opts.get("log-dir") or ".") / session
    data = _story(opts.get("base-url", "http://127.0.0.1:8091"), opts.get("token-file", ""), session)
    record = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "trigger": payload.get("trigger") or "",
              "transcript_path": payload.get("transcript_path") or "", "summary_chars": len(summary), "summary": summary,
              "cards": str(data.get("card") or ""), "index": str(data.get("index") or ""),
              "payload_keys": sorted(payload.keys())}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                                                    encoding="utf-8")
    count = len(list(folder.glob("*.json")))
    if not summary:
        return {"systemMessage": "압축 요약 글을 훅 입력에서 못 찾았습니다 — 카드만 남겼습니다."}
    return {"systemMessage": f"압축 요약을 남겼습니다(이 대화 {count}번째 · 요약 {len(summary):,}자)."}


def _turn_text(row: dict) -> str:
    message = row.get("message") if isinstance(row.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(str(b.get("text") or "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def open_line(path: str, target: int, around: int = 2) -> str:
    """그 줄(서기 카드 · 주제 색인의 번호 = 파일의 0부터 센 줄)과 앞뒤 사람 · 클로드 말. 도구 결과는 건너뛴다."""
    turns: list[tuple[int, str, str]] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, raw in enumerate(handle):
            if number > target + 400:
                break
            # 줄 머리만 보고 거른다(도구 결과 줄은 수 MB) — 띄어쓰기 있는 꼴도 받는다(`scribe._turn_of` 와 같게).
            if number < target - 400 or not any(mark in raw for mark in (
                    '"type":"user"', '"type":"assistant"', '"type": "user"', '"type": "assistant"')):
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            text = _turn_text(row).strip()
            if text and not row.get("isMeta"):
                turns.append((number, "사람" if row.get("type") == "user" else "클로드", text))
    if not turns:
        return f"줄 {target} 근처에 사람 · 클로드 말이 없습니다."
    at = min(range(len(turns)), key=lambda i: abs(turns[i][0] - target))
    return "\n\n".join(f"{'▶' if n == turns[at][0] else ' '} [{n}] {role}: {text[:1500]}"
                       for n, role, text in turns[max(0, at - around): at + around + 1])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if not argv:
        return 0
    command, rest = argv[0], argv[1:]
    if command == "open-line":
        if len(rest) < 2:
            print("쓰는 법: open-line <기록 파일> <줄 번호> [앞뒤 말 수]")
            return 2
        print(open_line(rest[0], int(rest[1]), int(rest[2]) if len(rest) > 2 else 2))
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:  # noqa: BLE001
        payload = {}
    try:
        out = (after_compact if command == "after-compact" else save_compact if command == "save-compact" else None)
        result = out(payload, _args(rest)) if out else None
    except Exception:  # noqa: BLE001 — 훅이 넘어져도 클로드 코드는 계속돼야 한다
        result = None
    if result:
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
