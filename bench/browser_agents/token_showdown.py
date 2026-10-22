"""클로드 단독 vs 클로드+자비스 — **호스트 토큰을 얼마나 아끼나.**

## 재는 것

어제 벤치는 「누가 더 잘하나」였다. 이건 다르다 — **같은 일을 시켰을 때 프런티어
모델이 몇 토큰을 태우나**를 잰다. 자비스를 하위 에이전트로 파는 것이 값이 되려면
이 숫자가 근거여야 한다.

## 두 리그

    A · 클로드 단독      자비스 브라우저 도구를 **클로드가 직접** 굴린다.
                        걸음마다 스냅샷·본문이 클로드 컨텍스트로 들어온다.
                        브라우저 MCP 를 붙였을 때 실제로 벌어지는 일이다.

    B · 클로드+자비스     도구가 **하나**다 — `jarvis_delegate(task)`.
                        자비스가 로컬(26B)에서 다 돌고 답만 돌려준다.

같은 모델(claude-sonnet-5) · 같은 과제 · 같은 도구 실행기(`/v1/tools/execute`).
다른 것은 **브라우저 루프가 어디서 도는가** 하나다.

## 공정성

- A 에게 자비스가 실제로 쓰는 브라우저 도구를 **그대로** 준다. 손을 묶지 않는다.
- A 의 도구 결과는 자비스가 모델에게 주는 것과 **같은 상한**으로 자른다
  (`_TOOL_RESULT_MAX_CHARS = 30,000`). A 를 불리하게 더 자르지 않는다.
- 둘 다 답을 낼 때까지 돌린다. 걸음 상한도 같다.
- B 의 자비스 쪽 로컬 토큰은 **호스트 비용이 아니다** — 따로 적되 합산하지 않는다.
  파는 이야기가 "프런티어 토큰을 아낀다"이므로 그 축을 그대로 잰다.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import anthropic

sys.path.insert(0, r"E:\evidence-ledger\src")
from evidence_ledger import numbers_claimed_in  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))
from alture_jarvis.evidence import numbers_in_body  # noqa: E402

HERE = pathlib.Path(__file__).parent
BASE = "http://127.0.0.1:8091"
TOKEN = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token").read_text().strip()
MODEL = "claude-sonnet-5"
MAX_STEPS = 30
# 자비스가 모델에게 주는 것과 같은 상한(agent._TOOL_RESULT_MAX_CHARS).
TOOL_RESULT_MAX = 30_000
# 소네트5 공개가(USD / 100만 토큰).
PRICE_IN, PRICE_OUT = 3.0, 15.0

TASKS = [
    ("yes24",   "YES24에서 파이썬 책 3권의 쪽수와 ISBN 을 조사해서 표로 알려줘."),
    ("wishket", "위시켓에서 AI 에이전트 관련 프로젝트 3개의 예상 기간과 지원자 수를 표로 알려줘."),
    ("saramin", "사람인에서 여수 회계 채용 공고 3개의 회사명과 고용형태를 표로 알려줘."),
]


def api(path: str, payload=None, method="GET"):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=body, method=method,
        headers={"X-Jarvis-Token": TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def browser_tools() -> list[dict]:
    """자비스가 실제로 쓰는 브라우저 도구를 앤트로픽 스키마로."""
    out = []
    for t in api("/v1/tools"):
        name = str(t.get("name") or "")
        if not name.startswith(("browser_", "site_")):
            continue
        if not t.get("enabled") or str(t.get("risk_level") or "L0") != "L0":
            continue          # 쓰기·승인 도구는 조사 과제에 필요 없다
        out.append({
            "name": name,
            "description": str(t.get("description") or "")[:900],
            "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


DELEGATE = {
    "name": "jarvis_delegate",
    "description": (
        "자비스(로컬 에이전트)에게 조사·브라우징 과제를 통째로 맡긴다. 자비스가 직접 "
        "브라우저를 몰아 사이트를 찾아 들어가고, 목록을 훑고, 상세를 열어 읽은 뒤 "
        "**최종 결과만** 돌려준다. 웹에서 알아내야 하는 일은 이 도구 하나로 끝낸다."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"task": {"type": "string", "description": "자비스에게 시킬 일. 원문 그대로."}},
        "required": ["task"],
    },
}


def run_jarvis_job(task: str, budget: int = 600) -> str:
    started = time.time()
    job = api("/v1/chat", {"prompt": task, "session_id": f"tok-{int(started)}", "open_results": False,
                           "measurement": True}, "POST")
    jid = str(job.get("id") or "")
    deadline = started + budget
    detail: dict = {}
    while time.time() < deadline:
        time.sleep(6)
        try:
            detail = api(f"/v1/jobs/{jid}")
        except urllib.error.URLError:
            continue
        if str(detail.get("status") or "") in {"completed", "failed", "cancelled"}:
            break
        began = detail.get("started_at")
        if began:
            deadline = max(deadline, float(began) + budget)
    res = detail.get("result") or {}
    return str(res.get("answer") or res.get("error") or "(자비스가 답을 못 냈다)")


def clip(text: str) -> tuple[str, bool]:
    if len(text) <= TOOL_RESULT_MAX:
        return text, False
    return text[:TOOL_RESULT_MAX] + f"\n…[{len(text):,}자 중 앞부분만]", True


#: 프롬프트 캐싱을 켤 것인가. **실제 클라이언트는 켠다** — 끄고 재면 A 가 부당하게
#: 비싸고, 그 상태의 배수는 상한일 뿐 사실이 아니다.
CACHE = os.environ.get("SHOWDOWN_CACHE", "1") != "0"
#: 도구 추리기. 비어 있으면 전부 준다. `"browser_,site_"` 처럼 접두사로 남긴다.
TOOL_KEEP = [x for x in os.environ.get("SHOWDOWN_TOOL_KEEP", "").split(",") if x]


def _cached(tools: list[dict]) -> list[dict]:
    """마지막 도구에 캐시 표시를 단다 — 그 앞의 스키마 전체가 한 덩어리로 캐시된다.

    도구 스키마는 **매 턴 통째로 다시 실린다.** 26개면 2,118 토큰이고 18턴이면
    38K 다. 전사만큼 크진 않지만, 공짜로 지울 수 있는 것을 두고 재면 안 된다.
    """
    if not CACHE or not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1]["cache_control"] = {"type": "ephemeral"}
    return out


def _mark_cache(msgs: list[dict]) -> None:
    """가장 최근 사용자 블록에 캐시 경계를 세운다.

    ★ 여기가 진짜다. 스냅샷 한 장이 38,867자인데 **이후 모든 턴에 다시 실린다** —
      A 리그 비용이 걸음 수에 제곱으로 붙는 이유다. 경계를 뒤쪽에 세우면 그 앞
      전사가 통째로 캐시 읽기가 된다(쓰기 1.25배, 읽기 0.1배).
    """
    if not CACHE:
        return
    # ★ 표시는 **옮기는 것**이지 쌓는 것이 아니다 (2026-09-09).
    #
    #   매 턴 새로 달기만 했더니 앤트로픽 상한(블록 4개)을 넘겨 400 이 났다.
    #   도구 스키마에 하나를 쓰므로 전사에는 **하나만** 둔다. 앞의 것을 지우고
    #   가장 뒤에 다시 세우면, 그 앞 전사가 통째로 캐시 읽기가 된다.
    for message in msgs:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)
    for message in reversed(msgs):
        content = message.get("content")
        if message.get("role") == "user" and isinstance(content, list) and content:
            last = content[-1]
            if isinstance(last, dict):
                last["cache_control"] = {"type": "ephemeral"}
            return


def loop(client, tools, prompt, *, arm) -> dict:
    """도구 루프 한 판. 앤트로픽 토큰을 전부 센다."""
    if TOOL_KEEP and len(tools) > 1:
        tools = [t for t in tools if any(t["name"].startswith(k) for k in TOOL_KEEP)]
    msgs = [{"role": "user", "content": prompt}]
    tin = tout = calls = turns = 0
    cache_write = cache_read = 0
    truncs = 0
    # ★ **두 리그를 같은 잣대로 재려면 A 의 도구 결과도 붙들어야 한다** (2026-09-07).
    #
    #   첫 판에서 B 의 창작(예스24 6개 값 전부)은 자비스 판 기록으로 잡았는데,
    #   A 는 도구 결과를 안 남겨 같은 검사를 못 했다. 싼 쪽만 검사하면 그 검사는
    #   비교가 아니라 고발이 된다.
    seen_numbers: set[str] = set()
    jarvis_seconds = 0.0
    t0 = time.time()
    answer = ""
    for _ in range(MAX_STEPS):
        r = client.messages.create(
            model=MODEL, max_tokens=4096, tools=_cached(tools), messages=msgs)
        turns += 1
        tin += r.usage.input_tokens
        tout += r.usage.output_tokens
        cache_write += getattr(r.usage, "cache_creation_input_tokens", 0) or 0
        cache_read += getattr(r.usage, "cache_read_input_tokens", 0) or 0
        uses = [b for b in r.content if b.type == "tool_use"]
        answer = "".join(b.text for b in r.content if b.type == "text") or answer
        if not uses:
            break
        msgs.append({"role": "assistant", "content": r.content})
        results = []
        for u in uses:
            calls += 1
            if u.name == "jarvis_delegate":
                jt = time.time()
                body = run_jarvis_job(str((u.input or {}).get("task") or prompt))
                jarvis_seconds += time.time() - jt
            else:
                try:
                    body = json.dumps(api("/v1/tools/execute",
                                          {"name": u.name, "arguments": u.input or {}}, "POST"),
                                      ensure_ascii=False)
                except Exception as exc:
                    body = json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            # ★ 위임 도구의 결과는 **JSON 이 아니라 글자**다 (2026-09-07).
            #   `json.loads` 를 그냥 걸었더니 B 리그의 「도구가 준 숫자」가 늘 0 이
            #   됐고, 검증까지 마친 정답 4개가 「근거 없음」으로 찍혔다. 눈금이
            #   싼 쪽만 불리하게 재고 있었다 — 오늘만 세 번째다.
            try:
                parsed = json.loads(body)
            except (ValueError, TypeError):
                parsed = {"text": body}
            try:
                seen_numbers.update(numbers_in_body(parsed))
            except Exception:
                pass
            body, cut = clip(body)
            truncs += int(cut)
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": body})
        msgs.append({"role": "user", "content": results})
        _mark_cache(msgs)
    return {
        "arm": arm, "turns": turns, "tool_calls": calls, "truncated": truncs,
        "tokens_in": tin, "tokens_out": tout,
        "cache_write": cache_write,
        "cache_read": cache_read,
        # 캐시 쓰기는 1.25배, 읽기는 0.1배. `input_tokens` 는 캐시 안 걸린 것만 센다.
        "usd": round(
            tin / 1e6 * PRICE_IN
            + cache_write / 1e6 * PRICE_IN * 1.25
            + cache_read / 1e6 * PRICE_IN * 0.1
            + tout / 1e6 * PRICE_OUT,
            4,
        ),
        "seconds": round(time.time() - t0, 1),
        "jarvis_seconds": round(jarvis_seconds, 1),
        "answer": answer.strip(),
        # 답의 숫자 중 **도구가 준 적 없는 것.** 값이 아니라 근거를 센다.
        "tool_numbers_seen": len(seen_numbers),
        "unsupported_numbers": sorted(numbers_claimed_in(answer) - seen_numbers)[:12],
    }


def _key_from_file() -> str:
    """키는 **모양으로 찾는다.** 「마지막 줄」로 집었더니 `"messages":` 를 키라고
    들고 왔다 — 파일에 예제 curl 이 같이 적혀 있었다."""
    import re
    text = pathlib.Path(r"C:\work\monorepo\클로드 API키.txt").read_text(
        encoding="utf-8", errors="replace")
    found = re.findall(r"sk-ant-[A-Za-z0-9_\-]{20,}", text)
    if not found:
        sys.exit("API 키를 파일에서 못 찾았다.")
    return found[0]


if __name__ == "__main__":
    key = os.environ.get("ANTHROPIC_API_KEY") or _key_from_file()
    client = anthropic.Anthropic(api_key=key)
    solo = browser_tools()
    print(f"A 리그 도구 {len(solo)}개 · B 리그 도구 1개\n", flush=True)
    rows = []
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    # ★ A 는 **기준점**이다 — 한 번 재면 다시 태울 이유가 없다($5.13/회).
    #   자비스를 고친 뒤에는 B 만 다시 돌린다($0.11/회).
    arms = [a for a in sys.argv[2:] if a in {"A", "B"}] or ["A", "B"]
    for name, prompt in TASKS:
        if only and only != name:
            continue
        pairs = [p for p in (("A_claude_solo", solo), ("B_claude_jarvis", [DELEGATE]))
                 if p[0][0] in arms]
        for arm, tools in pairs:
            print(f"{'=' * 66}\n[{arm}] {name}", flush=True)
            try:
                row = loop(client, tools, prompt, arm=arm)
            except Exception as exc:
                row = {"arm": arm, "error": f"{type(exc).__name__}: {exc}"}
            row["task"] = name
            rows.append(row)
            print(f"  턴 {row.get('turns')} · 도구 {row.get('tool_calls')} · 잘림 {row.get('truncated')}"
                  f" · {row.get('seconds')}s", flush=True)
            print(f"  토큰 in {row.get('tokens_in',0):,} / out {row.get('tokens_out',0):,}"
                  f"  = ${row.get('usd')}", flush=True)
            print(f"  답: {str(row.get('answer') or row.get('error'))[:150]}", flush=True)
            (HERE / "results" / f"token_showdown{'_' + ''.join(arms) if arms != ['A','B'] else ''}.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n완료 — results/token_showdown.json")
