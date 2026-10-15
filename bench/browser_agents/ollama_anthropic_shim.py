"""Ollama 말을 하는 껍데기 — 받은 것을 앤트로픽으로 넘긴다.

## 왜 필요한가

자비스는 Ollama 네이티브 API(`/api/chat`·`/api/ps`·`/api/tags`)만 말한다. 제공자
추상화가 없다. 그래서 **자비스 배선 + 프런티어 모델**(arm D)을 재려면 중간에
통역이 하나 있어야 한다.

`JARVIS_CLAUDE_CODE_ENABLED=1` 은 답이 아니다 — 그건 Claude Code CLI 에 일을 통째로
넘기는 위임이라, 재는 대상이 「자비스 배선」이 아니라 「Claude Code 배선」이 된다.

## 쓰는 법

    set ANTHROPIC_API_KEY=...
    python ollama_anthropic_shim.py --port 11500 --model claude-sonnet-5

    # 자비스를 여기로 향하게 하고 재시작
    JARVIS_OLLAMA_BASE_URL=http://127.0.0.1:11500

## 덤으로 얻는 것

`prompt_eval_count`/`eval_count` 를 앤트로픽의 input/output 토큰으로 채운다. 그러면
**자비스 자기 잡 기록에 진짜 토큰 수가 남는다** — 레퍼런스 숫자가 여기서 나온다.
매 호출을 `shim_usage.jsonl` 에도 적는다.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8192
# 프롬프트 캐싱. 도구 스키마·시스템 프롬프트가 매 호출 **바이트 단위로 동일**해서
# 입력의 84%를 차지한다(2026-09-07 실측: 도구 61.4% + 시스템 23.0%).
# 껍데기에서 캐시 표식만 붙이면 자비스는 아무것도 안 고쳐도 된다.
CACHE = True
# 도구 추리기 실험용. 빈 값이면 전부 보낸다.
TOOL_KEEP_PREFIXES = [x for x in os.environ.get("SHIM_TOOL_KEEP", "").split(",") if x]
USAGE_LOG = pathlib.Path(__file__).with_name("shim_usage.jsonl")
_lock = threading.Lock()
_client = None
# ★ 프리픽스 캐시가 실제로 얼마나 먹는지 잰다.
#
# Ollama 도 앤트로픽도 **앞부분이 그대로일 때만** 캐시가 산다. 자비스는 전사를
# 접을 때 오래된 항목을 "한 줄로" 고치는데, 그러면 그 지점부터 프리픽스가 달라져
# 캐시가 통째로 깨진다. 그 일이 실제로 일어나는지는 재 봐야 안다.
_last_prompt = {"text": ""}


def _prefix_stats(system, conv, tools):
    """직전 호출과 앞부분이 몇 글자나 같은가."""
    cur = json.dumps([system, tools, conv], ensure_ascii=False, sort_keys=True)
    prev = _last_prompt["text"]
    n = 0
    for a, b in zip(prev, cur):
        if a != b:
            break
        n += 1
    _last_prompt["text"] = cur
    return {"prompt_chars": len(cur), "prev_chars": len(prev), "common_prefix": n,
            "prefix_pct": round(n / max(1, min(len(cur), len(prev))) * 100, 1) if prev else None}


# ───────────────────────────────────────────────────────────── 번역 ──

def to_anthropic_tools(tools):
    """Ollama {"type":"function","function":{...}} -> 앤트로픽 {name, input_schema}."""
    out = []
    for t in tools or []:
        fn = t.get("function") or t
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "description": str(fn.get("description") or "")[:1024],
            # 빈 스키마는 거부당한다. 최소형을 채워 준다.
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    if TOOL_KEEP_PREFIXES:
        kept = [t for t in out if any(t["name"].startswith(p) for p in TOOL_KEEP_PREFIXES)]
        if kept:
            out = kept
    # 마지막 도구에 캐시 경계를 찍으면 **그 앞 전부**가 캐시된다.
    if CACHE and out:
        out[-1] = dict(out[-1], cache_control={"type": "ephemeral"})
    return out


def to_anthropic_messages(messages):
    """Ollama 전사 -> (system, messages).

    까다로운 자리는 **도구 결과 짝짓기**다. Ollama 는 {"role":"tool","tool_name":...}
    만 보내고 **id 가 없다.** 앤트로픽은 tool_use_id 를 요구한다. 그래서 어시스턴트가
    낸 tool_use 에 순번 id 를 붙여 두고, 뒤따르는 tool 메시지에 **순서대로** 짝지운다.
    """
    system_parts = []
    out = []
    pending = []          # 아직 결과가 안 온 tool_use id 들
    counter = 0

    for m in messages:
        role = str(m.get("role") or "")
        content = m.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

        if role == "system":
            if text.strip():
                system_parts.append(text)
            continue

        if role == "tool":
            # 짝이 없으면 가짜 id 를 만들지 않는다 — 앤트로픽이 400 으로 거부한다.
            # 아래 _repair_pairs 가 글로 내린다.
            tool_id = pending.pop(0) if pending else ""
            counter += 1
            out.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": text[:60000] or "(empty)",
            }]})
            continue

        if role == "assistant":
            # ★ 짝은 **인접한 턴 안에서만** 맞춘다.
            #   예전에는 pending 을 전역 큐로 썼는데, 한 턴에 도구를 둘 이상 부르면
            #   짝이 다음다음 턴으로 밀려서 앤트로픽이 "tool_use without tool_result
            #   immediately after" 로 거부했다. 새 어시스턴트 턴이 시작되면 앞 턴의
            #   미결 id 는 버린다 — _repair_pairs 가 글로 내린다.
            pending = []
            blocks = []
            if text.strip():
                blocks.append({"type": "text", "text": text})
            for call in m.get("tool_calls") or []:
                fn = call.get("function") or {}
                tool_id = "call_%d" % counter
                counter += 1
                pending.append(tool_id)
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"_raw": args}
                blocks.append({
                    "type": "tool_use",
                    "id": tool_id,
                    "name": str(fn.get("name") or "unknown"),
                    "input": args if isinstance(args, dict) else {},
                })
            if blocks:
                out.append({"role": "assistant", "content": blocks})
            continue

        # user (그리고 모르는 역할)
        if text.strip():
            out.append({"role": "user", "content": text})

    # 앤트로픽은 같은 역할이 연달아 오는 것을 싫어한다. 붙인다.
    merged = []
    for m in out:
        if merged and merged[-1]["role"] == m["role"]:
            prev, cur = merged[-1]["content"], m["content"]
            prev = [{"type": "text", "text": prev}] if isinstance(prev, str) else list(prev)
            cur = [{"type": "text", "text": cur}] if isinstance(cur, str) else list(cur)
            merged[-1]["content"] = prev + cur
        else:
            merged.append(dict(m))

    merged = _repair_pairs(merged)

    # 첫 메시지는 user 여야 한다. 비어 있어도 안 된다.
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    if not merged:
        merged = [{"role": "user", "content": "continue"}]
    return "\n\n".join(system_parts), merged


def _repair_pairs(msgs):
    """짝이 안 맞는 tool_use / tool_result 를 **글로 내린다.**

    ★ 2026-09-07 에 이걸 안 해서 arm D 첫 두 판이 400 으로 죽었다.

    자비스는 창을 지키려고 전사를 접는다(agent._bounded_transcript). 그러면 오래된
    어시스턴트 턴의 tool_use 는 사라지는데 **그 결과는 남는다.** 앤트로픽은 짝 없는
    tool_use_id 를 거부한다(400 invalid_request_error).

    자르는 쪽(자비스)과 짝을 요구하는 쪽(앤트로픽)이 서로를 모른다. 그 사이를 메우는
    것이 이 함수다. 구조를 살릴 수 있으면 살리고, 못 살리면 글로 내린다 —
    **버리지는 않는다.** 버리면 모델이 자기가 뭘 했는지 모른다.
    """
    def blocks(m):
        c = m.get("content")
        return c if isinstance(c, list) else None

    # (1) 앞 어시스턴트에 짝이 없는 tool_result -> 글
    for i, m in enumerate(msgs):
        bs = blocks(m)
        if m["role"] != "user" or not bs:
            continue
        valid = set()
        if i > 0 and msgs[i - 1]["role"] == "assistant":
            pb = blocks(msgs[i - 1]) or []
            valid = {x.get("id") for x in pb if x.get("type") == "tool_use"}
        m["content"] = [
            x if not (x.get("type") == "tool_result" and x.get("tool_use_id") not in valid)
            else {"type": "text", "text": "[도구 결과] " + str(x.get("content") or "")[:8000]}
            for x in bs
        ]

    # (2) 뒤에 결과가 안 온 tool_use -> 글
    for i, m in enumerate(msgs):
        bs = blocks(m)
        if m["role"] != "assistant" or not bs:
            continue
        answered = set()
        if i + 1 < len(msgs) and msgs[i + 1]["role"] == "user":
            nb = blocks(msgs[i + 1]) or []
            answered = {x.get("tool_use_id") for x in nb if x.get("type") == "tool_result"}
        m["content"] = [
            x if not (x.get("type") == "tool_use" and x.get("id") not in answered)
            else {"type": "text", "text": "[도구 호출] %s(%s)" % (
                x.get("name"), json.dumps(x.get("input") or {}, ensure_ascii=False)[:600])}
            for x in bs
        ]

    # (3) tool_result 는 **사용자 메시지 맨 앞**에 몰려 있어야 한다.
    #
    # ★ 이것 때문에 arm D 가 세 번째로 죽었다. 구조는 맞는데 순서가 틀렸다:
    #     assistant [text, tool_use×3]
    #     user      [tool_result, text, tool_result, text, tool_result, text …]
    #                             ↑ 자비스가 도구 결과 사이에 지시문을 끼워 넣는다
    # 앤트로픽은 그걸 "tool_result 가 안 왔다"로 읽는다. 글은 뒤로 민다 — 버리지 않는다.
    for m in msgs:
        bs = blocks(m)
        if m["role"] != "user" or not bs:
            continue
        if any(x.get("type") == "tool_result" for x in bs):
            m["content"] = ([x for x in bs if x.get("type") == "tool_result"]
                            + [x for x in bs if x.get("type") != "tool_result"])

    # (4) 빈 내용은 앤트로픽이 거부한다
    out = []
    for m in msgs:
        bs = blocks(m)
        if bs is not None:
            bs = [x for x in bs
                  if x.get("type") != "text" or str(x.get("text") or "").strip()]
            if not bs:
                continue
            m["content"] = bs
        elif not str(m.get("content") or "").strip():
            continue
        out.append(m)
    return out


def from_anthropic(resp):
    """앤트로픽 응답 -> (ollama message, metrics)."""
    text_parts, tool_calls = [], []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({"function": {"name": block.name, "arguments": block.input}})
    message = {"role": "assistant", "content": "".join(text_parts)}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = getattr(resp, "usage", None)
    metrics = {
        "done_reason": getattr(resp, "stop_reason", "stop") or "stop",
        "prompt_eval_count": getattr(usage, "input_tokens", 0) or 0,
        "eval_count": getattr(usage, "output_tokens", 0) or 0,
        "_cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "_cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    return message, metrics


# ───────────────────────────────────────────────────────────── 서버 ──

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):        # 콘솔을 조용히
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _model_row(self):
        return {
            "name": MODEL, "model": MODEL, "size": 0, "size_vram": 0,
            "digest": "shim", "context_length": 200000,
            "details": {"family": "anthropic", "parameter_size": "n/a",
                        "quantization_level": "none"},
        }

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            self._json({"models": [self._model_row()]})
        elif self.path.startswith("/api/ps"):
            # 항상 "원하는 모델이 이미 올라와 있다"고 답한다 ->
            # 자비스의 _make_room_for 가 아무도 안 내린다.
            self._json({"models": [self._model_row()]})
        elif self.path.startswith("/api/version"):
            self._json({"version": "shim-0.1"})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}

        if self.path.startswith("/api/generate"):
            self._json({"model": MODEL, "response": "", "done": True,
                        "done_reason": "stop", "prompt_eval_count": 0, "eval_count": 0})
            return
        if not self.path.startswith("/api/chat"):
            self._json({"error": "not found"}, 404)
            return

        messages = body.get("messages") or []
        stream = bool(body.get("stream"))

        # 빈 메시지 = 모델 내리라는 프로브. 생성하지 않는다.
        if not messages:
            self._json({"model": MODEL, "message": {"role": "assistant", "content": ""},
                        "done": True, "done_reason": "unload"})
            return

        system, conv = to_anthropic_messages(messages)
        tools = to_anthropic_tools(body.get("tools"))
        started = time.monotonic()
        try:
            kwargs = {"model": MODEL, "max_tokens": MAX_TOKENS, "messages": conv}
            if system.strip():
                text = system[:200000]
                kwargs["system"] = ([{"type": "text", "text": text,
                                      "cache_control": {"type": "ephemeral"}}]
                                    if CACHE else text)
            if tools:
                kwargs["tools"] = tools
            resp = _client.messages.create(**kwargs)
            message, metrics = from_anthropic(resp)
        except Exception as exc:
            # ★ 터진 요청을 떨군다. 추측하지 말고 본다.
            try:
                dump = pathlib.Path(__file__).with_name("shim_last_error.json")
                dump.write_text(json.dumps({
                    "error": "%s: %s" % (type(exc).__name__, exc),
                    "ollama_in": messages,
                    "anthropic_out": conv,
                    "system_chars": len(system),
                }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            except Exception:
                pass
            message = {"role": "assistant",
                       "content": ("[shim error] %s: %s" % (type(exc).__name__, exc))[:800]}
            metrics = {"done_reason": "error", "prompt_eval_count": 0, "eval_count": 0}
            print("  ! %s: %s" % (type(exc).__name__, str(exc)[:200]), flush=True)

        elapsed_ns = int((time.monotonic() - started) * 1e9)
        metrics.update({"total_duration": elapsed_ns, "load_duration": 0})

        with _lock:
            with USAGE_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": MODEL,
                    "in": metrics["prompt_eval_count"], "out": metrics["eval_count"],
                    "sec": round(elapsed_ns / 1e9, 1), "msgs": len(messages),
                    "tools": len(tools), "calls": len(message.get("tool_calls") or []),
                    "tools_kept": len(tools), "keep": ",".join(TOOL_KEEP_PREFIXES) or "all",
                    # ★ 무엇이 입력을 먹는지 나눠 적는다. 도구 스키마를 추릴지 말지는
                    #   감이 아니라 이 비율을 보고 정한다.
                    "cache_write": metrics.get("_cache_write", 0),
                    "cache_read": metrics.get("_cache_read", 0),
                    **_prefix_stats(system, conv, tools),
                    "tool_chars": len(json.dumps(tools, ensure_ascii=False)),
                    "msg_chars": len(json.dumps(conv, ensure_ascii=False)),
                    "sys_chars": len(system),
                }, ensure_ascii=False) + "\n")
        print("  in %7d  out %5d  %5.1fs  calls %d" % (
            metrics["prompt_eval_count"], metrics["eval_count"],
            elapsed_ns / 1e9, len(message.get("tool_calls") or [])), flush=True)

        if not stream:
            payload = {"model": MODEL, "message": message, "done": True}
            payload.update(metrics)
            self._json(payload)
            return

        # 스트리밍: NDJSON 두 줄이면 된다(자비스가 조각을 합쳐서 쓴다).
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        tail = {"model": MODEL, "message": {"role": "assistant", "content": ""}, "done": True}
        tail.update(metrics)
        for payload in ({"model": MODEL, "message": message, "done": False}, tail):
            line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            self.wfile.write(("%X\r\n" % len(line)).encode() + line + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


def main():
    global MODEL, _client
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11500)
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args()
    MODEL = args.model
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("ANTHROPIC_API_KEY 가 없다.")
    _client = anthropic.Anthropic(api_key=key)
    print("Ollama->Anthropic 껍데기  포트 %d  모델 %s" % (args.port, MODEL), flush=True)
    print("  자비스에 JARVIS_OLLAMA_BASE_URL=http://127.0.0.1:%d 를 주고 재시작" % args.port,
          flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
