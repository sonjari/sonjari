"""Ollama 말을 하는 껍데기 — 받은 것을 OpenAI 로 넘긴다.

## 왜 필요한가

자비스는 Ollama 네이티브 API(`/api/chat`·`/api/ps`·`/api/tags`)만 말한다. 제공자
추상화가 없다. 등급별 대조군을 재려면 — **내장그래픽뿐인 노트북에서는 클라우드
경량 모델이 두뇌**가 된다 — 중간에 통역이 하나 필요하다.

앤트로픽판(`ollama_anthropic_shim.py`)보다 훨씬 짧다. Ollama 의 `messages` 와
`tools` 모양이 OpenAI 를 그대로 베낀 것이라 번역할 것이 거의 없다. 다른 곳은 셋뿐:

    tool 결과   Ollama `{"role":"tool","content":...}` (id 없음)
                OpenAI `{"role":"tool","tool_call_id":...}` (id 필수)
    도구 호출   Ollama `message.tool_calls[].function.arguments` = **dict**
                OpenAI 는 같은 자리가 **JSON 문자열**
    사고        Ollama 는 `message.thinking`, OpenAI 는 그런 칸이 없다

## 토큰 효율

OpenAI 는 프롬프트 캐싱이 **자동**이다(1,024 토큰 이상 접두사, 별도 인자 없음).
그래서 켜고 끌 것이 없고, 대신 `cached_tokens` 를 기록해 실제로 걸렸는지 본다 —
「켰다」가 아니라 「걸렸다」를 봐야 한다.

    python ollama_openai_shim.py --port 11501 --model gpt-5-nano

## OpenAI 만 붙는 것이 아니다

`--base-url` 로 **OpenAI 호환 엔드포인트를 쓰는 아무 제공자**에 붙는다. 오픈AI와
앤트로픽은 이 바닥에서 비싼 쪽이고, 3등급(내장그래픽 노트북)의 값은 거기서
정해질 이유가 없다.

    # DeepSeek
    --base-url https://api.deepseek.com --model deepseek-v4-flash
    # xAI
    --base-url https://api.x.ai/v1 --model grok-4.3
    # Zhipu GLM
    --base-url https://open.bigmodel.cn/api/paas/v4 --model glm-5.3
    # Alibaba Qwen
    --base-url https://dashscope-intl.aliyuncs.com/compatible-mode/v1 --model qwen3.7-max

키는 `--key-env` 가 가리키는 환경변수에서 읽는다(기본 `OPENAI_API_KEY`).

> ⚠ 제공자를 고르는 것은 **데이터가 어디로 가는가**를 고르는 것이다. 이 껍데기는
>   자비스가 본 페이지 본문을 그대로 넘긴다 — 로그인한 화면이면 그 내용까지 간다.
>   1·2등급(로컬)에는 그 문제가 없다. 3등급을 팔 때는 그 차이를 말해야 한다.
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import openai

MODEL = "gpt-5-nano"
MAX_TOKENS = 4096
USAGE_LOG = pathlib.Path(__file__).with_name("shim_openai_usage.jsonl")
TOOL_KEEP = [x for x in os.environ.get("SHIM_TOOL_KEEP", "").split(",") if x]
_client = None
_lock = threading.Lock()


def to_openai_tools(tools):
    """Ollama 도구 -> OpenAI 도구. 모양이 같아 대부분 그대로 지난다."""
    out = []
    for tool in tools or []:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "")
        if not name or (TOOL_KEEP and not any(name.startswith(k) for k in TOOL_KEEP)):
            continue
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": str(fn.get("description") or "")[:1024],
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return out


def to_openai_messages(messages):
    """Ollama 대화 -> OpenAI 대화.

    ★ `tool` 메시지에 **id 가 없다.** Ollama 는 순서로 짝을 맞추고 OpenAI 는
      `tool_call_id` 를 요구한다. 그래서 직전 assistant 가 낸 호출 id 를 순서대로
      물려준다 — 짝이 안 맞으면 400 이 나고, 그 400 은 **빠른 성공처럼 보인다**
      (앤트로픽판에서 여덟 판을 그렇게 잃었다).
    """
    out = []
    pending = []
    for index, message in enumerate(messages or []):
        role = str(message.get("role") or "user")
        content = message.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if role == "system":
            out.append({"role": "system", "content": text})
            continue
        if role == "tool":
            if not pending:
                # 짝이 없는 결과는 사용자 말로 내린다. 버리지 않는다 — 버리면
                # 모델이 도구를 부른 사실만 알고 답을 모르게 된다.
                out.append({"role": "user", "content": "[도구 결과] " + text})
                continue
            out.append({"role": "tool", "tool_call_id": pending.pop(0), "content": text})
            continue
        if role == "assistant":
            calls = []
            for order, call in enumerate(message.get("tool_calls") or []):
                fn = call.get("function") or {}
                args = fn.get("arguments")
                call_id = str(call.get("id") or "call_%d_%d" % (index, order))
                calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(fn.get("name") or ""),
                        # OpenAI 는 이 자리가 **문자열**이다. Ollama 는 dict 를 준다.
                        "arguments": args if isinstance(args, str)
                        else json.dumps(args or {}, ensure_ascii=False),
                    },
                })
            row = {"role": "assistant", "content": text or None}
            if calls:
                row["tool_calls"] = calls
                pending = [c["id"] for c in calls]
            else:
                pending = []
            out.append(row)
            continue
        pending = []
        out.append({"role": "user", "content": text})
    return out


def from_openai(resp):
    """OpenAI 응답 -> Ollama 모양."""
    choice = resp.choices[0].message
    calls = []
    for call in getattr(choice, "tool_calls", None) or []:
        raw = call.function.arguments
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (ValueError, TypeError):
            args = {}
        # 자비스는 dict 를 기대한다. 문자열로 주면 인자가 통째로 빈다.
        calls.append({"function": {"name": call.function.name, "arguments": args}})
    message = {"role": "assistant", "content": choice.content or ""}
    if calls:
        message["tool_calls"] = calls
    usage = resp.usage
    details = getattr(usage, "prompt_tokens_details", None)
    metrics = {
        "done_reason": "stop",
        "prompt_eval_count": getattr(usage, "prompt_tokens", 0) or 0,
        "eval_count": getattr(usage, "completion_tokens", 0) or 0,
        # 캐싱은 자동이다. 「켰다」가 아니라 **걸렸다**를 본다.
        "_cached": (getattr(details, "cached_tokens", 0) or 0) if details else 0,
    }
    return message, metrics


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
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
            "digest": "shim", "context_length": 400000,
            "details": {"family": "openai", "parameter_size": "n/a",
                        "quantization_level": "none"},
        }

    def do_GET(self):
        if self.path.startswith("/api/tags") or self.path.startswith("/api/ps"):
            # 늘 "이미 올라와 있다"고 답한다 — 자비스가 아무도 안 내리게.
            self._json({"models": [self._model_row()]})
        elif self.path.startswith("/api/version"):
            self._json({"version": "openai-shim-0.1"})
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
        if not messages:
            self._json({"model": MODEL, "message": {"role": "assistant", "content": ""},
                        "done": True, "done_reason": "unload"})
            return

        conv = to_openai_messages(messages)
        tools = to_openai_tools(body.get("tools"))
        started = time.monotonic()
        try:
            kwargs = {"model": MODEL, "messages": conv, "max_completion_tokens": MAX_TOKENS}
            if tools:
                kwargs["tools"] = tools
            resp = _client.chat.completions.create(**kwargs)
            message, metrics = from_openai(resp)
        except Exception as exc:
            # ★ 터진 요청을 떨군다. 추측하지 말고 본다.
            try:
                pathlib.Path(__file__).with_name("shim_openai_last_error.json").write_text(
                    json.dumps({"error": "%s: %s" % (type(exc).__name__, exc),
                                "ollama_in": messages, "openai_out": conv},
                               ensure_ascii=False, indent=1, default=str),
                    encoding="utf-8")
            except Exception:
                pass
            message = {"role": "assistant",
                       "content": ("[shim error] %s: %s" % (type(exc).__name__, exc))[:800]}
            metrics = {"done_reason": "error", "prompt_eval_count": 0,
                       "eval_count": 0, "_cached": 0}
            print("  ! %s: %s" % (type(exc).__name__, str(exc)[:200]), flush=True)

        elapsed_ns = int((time.monotonic() - started) * 1e9)
        metrics.update({"total_duration": elapsed_ns, "load_duration": 0})
        cached = metrics.pop("_cached", 0)
        with _lock:
            with USAGE_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": MODEL,
                    "in": metrics["prompt_eval_count"], "out": metrics["eval_count"],
                    "cached": cached, "sec": round(elapsed_ns / 1e9, 1),
                    "msgs": len(messages), "tools": len(tools),
                    "calls": len(message.get("tool_calls") or []),
                    "keep": ",".join(TOOL_KEEP) or "all",
                }, ensure_ascii=False) + "\n")
        print("  in %7d (캐시 %6d)  out %5d  %5.1fs  calls %d" % (
            metrics["prompt_eval_count"], cached, metrics["eval_count"],
            elapsed_ns / 1e9, len(message.get("tool_calls") or [])), flush=True)

        if not stream:
            payload = {"model": MODEL, "message": message, "done": True}
            payload.update(metrics)
            self._json(payload)
            return
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
    global _client, MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11501)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--base-url", default="", help="OpenAI 호환 엔드포인트")
    ap.add_argument("--key-env", default="OPENAI_API_KEY")
    args = ap.parse_args()
    MODEL = args.model
    key = os.environ.get(args.key_env, "")
    if not key:
        sys.exit("%s 가 없다." % args.key_env)
    _client = openai.OpenAI(api_key=key, base_url=args.base_url or None)
    print("껍데기: 127.0.0.1:%d -> %s @ %s  (도구 남김: %s)" % (
        args.port, MODEL, args.base_url or "api.openai.com",
        ",".join(TOOL_KEEP) or "전부"), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
