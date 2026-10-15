"""Ollama/Qwen3.8의 Code 런타임 노브를 작은 요청으로 실측해 JSON으로 남긴다."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


BASE = "http://127.0.0.1:11434"
MODEL = "qwen3.8:27b-mtp-q4_K_M"


def request(client: httpx.Client, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post(BASE + path, json=body) if body is not None else client.get(BASE + path)
    response.raise_for_status()
    return dict(response.json())


def summarize(
    payload: dict[str, Any],
    elapsed: float,
    *,
    requested: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = dict(payload.get("message") or {})
    contract = requested or {}
    return {
        "elapsed_sec": round(elapsed, 3),
        "done_reason": payload.get("done_reason"),
        "prompt_eval_count": payload.get("prompt_eval_count"),
        "eval_count": payload.get("eval_count"),
        "thinking_chars": len(str(message.get("thinking") or "")),
        "content_chars": len(str(message.get("content") or "")),
        "tool_calls": len(message.get("tool_calls") or []),
        "message_keys": sorted(message),
        "request_contract": contract,
        "response_acknowledged": {
            key: (
                payload.get(key) == value
                if key in payload
                else message.get(key) == value
                if key in message
                else None
            )
            for key, value in contract.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="")
    parser.add_argument("--num-ctx", type=int, default=102400)
    args = parser.parse_args()
    with httpx.Client(timeout=300) as client:
        version = request(client, "/api/version")
        shown = request(client, "/api/show", {"model": MODEL})
        common = {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Reply with the single word READY."}],
            "stream": False,
            "keep_alive": "24h",
            "options": {"num_ctx": args.num_ctx, "num_predict": 96},
        }
        probes: dict[str, Any] = {}
        for name, extras in {
            "non_thinking": {"think": False, "options": {"temperature": 0.7, "top_p": 0.8}},
            "official_thinking": {
                "think": True,
                "options": {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0},
            },
            "requested_effort_preserve": {
                "think": True,
                "reasoning_effort": "medium",
                "preserve_thinking": True,
                "options": {"temperature": 1.0, "top_p": 0.95, "top_k": 20},
            },
        }.items():
            body = {**common, **extras, "options": {**common["options"], **extras.get("options", {})}}
            started = time.monotonic()
            payload = request(client, "/api/chat", body)
            contract = {
                key: body[key]
                for key in ("reasoning_effort", "preserve_thinking")
                if key in body
            }
            probes[name] = summarize(
                payload, time.monotonic() - started, requested=contract
            )
            if name == "requested_effort_preserve":
                first_message = dict(payload.get("message") or {})
                followup = {
                    **body,
                    "messages": [
                        common["messages"][0],
                        first_message,
                        {"role": "user", "content": "Now reply with the single word KEPT."},
                    ],
                }
                follow_started = time.monotonic()
                follow_payload = request(client, "/api/chat", followup)
                probes["preserved_thinking_followup"] = summarize(
                    follow_payload,
                    time.monotonic() - follow_started,
                    requested=contract,
                )
                probes["preserved_thinking_followup"]["thinking_history_sent"] = bool(
                    first_message.get("thinking")
                )
        tool_body = {
            **common,
            "messages": [
                {
                    "role": "user",
                    "content": "Call runtime_probe with value READY. Do not answer in text.",
                }
            ],
            "think": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "runtime_probe",
                        "description": "Record the probe value.",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                        },
                    },
                }
            ],
        }
        started = time.monotonic()
        probes["thinking_tool_call"] = summarize(
            request(client, "/api/chat", tool_body), time.monotonic() - started
        )
        running = request(client, "/api/ps")

    parameters = str(shown.get("parameters") or "")
    capabilities = list(shown.get("capabilities") or [])
    payload = {
        "measured_at": time.time(),
        "ollama_version": version.get("version"),
        "model": MODEL,
        "capabilities": capabilities,
        "mtp_declared": "draft_num_predict" in parameters,
        "thinking_declared": "thinking" in capabilities,
        "tools_declared": "tools" in capabilities,
        "resident": [
            {
                "name": item.get("name") or item.get("model"),
                "context_length": item.get("context_length"),
                "size_vram": item.get("size_vram"),
            }
            for item in running.get("models", [])
            if str(item.get("name") or item.get("model") or "").startswith("qwen3.8")
        ],
        "probes": probes,
        # Ollama가 알 수 없는 top-level 키를 받아도 응답에는 반영 여부가 나오지 않는다.
        # HTTP 200을 "medium이 적용됐다"로 부풀리지 않도록 명시적으로 미확증 처리한다.
        "reasoning_effort_observable": False,
        "preserve_thinking_observable": False,
        "note": (
            "reasoning_effort/preserve_thinking은 요청 수락만으로 적용을 증명할 수 없다. "
            "Ollama 응답에 적용값이 없어 동일 24과제 A/B 전에는 미확증으로 취급한다."
        ),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
