"""코더 후보를 같은 세 과제와 같은 Ollama 조건으로 재는 선택 눈금.

에이전트 배선을 바꾸기 전에 모델 자체가 실행 가능한 파이썬을 내는지 본다. 응답의
코드 블록을 임시 파일로 저장해 별도 프로세스로 실행하므로 설명의 그럴듯함은 점수가
아니다. Ollama의 ``load_duration``을 함께 기록해 모델 교체 비용도 숨기지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from bench_coding_tasks import TASKS, normalize_stdout


DEFAULT_MODELS = (
    "plopfit-gemma4-qat:latest",
    "qwen2.5-coder:7b",
    "qwen3.8:27b-mtp-q4_K_M",
)
_FENCE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.I | re.S)


def _code(content: str) -> str:
    match = _FENCE.search(content)
    return (match.group(1) if match else content).strip()


def _call(base_url: str, model: str, prompt: str, *, num_ctx: int, timeout: int) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return only one complete Python program. Do not explain it. "
                    "The program must compute the answer rather than print a memorized literal."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "keep_alive": "24h",
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": 2048},
    }
    began = time.monotonic()
    with httpx.Client(timeout=float(timeout)) as client:
        response = client.post(f"{base_url}/api/chat", json=body)
        response.raise_for_status()
        payload = response.json()
    payload["wall_sec"] = round(time.monotonic() - began, 2)
    return payload


def _unload_resident(base_url: str) -> list[str]:
    """24h 상주가 모델 교체를 굶기므로 벤치 후보마다 슬롯을 명시적으로 비운다."""
    with httpx.Client(timeout=30.0) as client:
        resident = client.get(f"{base_url}/api/ps").json().get("models") or []
        names = [str(item.get("name") or item.get("model") or "") for item in resident]
        for name in names:
            if name:
                response = client.post(
                    f"{base_url}/api/generate",
                    json={"model": name, "keep_alive": 0},
                )
                response.raise_for_status()
    return names


def _restore(base_url: str, model: str, *, num_ctx: int, timeout: int) -> dict[str, Any]:
    payload = _call(
        base_url,
        model,
        "Reply with the single word OK.",
        num_ctx=num_ctx,
        timeout=timeout,
    )
    return {
        "model": model,
        "wall_sec": payload["wall_sec"],
        "load_sec": round(float(payload.get("load_duration") or 0) / 1_000_000_000, 2),
    }


def _execute(code: str, expected: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="jarvis-coder-bench-") as folder:
        target = Path(folder) / "answer.py"
        target.write_text(code, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, str(target)],
                cwd=folder,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    stdout = normalize_stdout(completed.stdout)
    return {
        "ok": completed.returncode == 0 and stdout == expected,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": completed.stderr[-1000:],
    }


def run_model(base_url: str, model: str, *, num_ctx: int, timeout: int) -> dict[str, Any]:
    rows = []
    for task in TASKS:
        try:
            payload = _call(base_url, model, task.prompt, num_ctx=num_ctx, timeout=timeout)
            content = str((payload.get("message") or {}).get("content") or "")
            execution = _execute(_code(content), task.expected_stdout)
            eval_count = int(payload.get("eval_count") or 0)
            eval_sec = float(payload.get("eval_duration") or 0) / 1_000_000_000
            rows.append(
                {
                    "key": task.key,
                    "ok": execution.get("ok") is True,
                    "wall_sec": payload["wall_sec"],
                    "load_sec": round(float(payload.get("load_duration") or 0) / 1_000_000_000, 2),
                    "tokens_per_sec": round(eval_count / eval_sec, 1) if eval_sec else 0,
                    "execution": execution,
                    "content_head": content[:300],
                }
            )
        except Exception as exc:
            rows.append({"key": task.key, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "model": model,
        "passed": sum(1 for row in rows if row.get("ok")),
        "total": len(rows),
        "swap_load_sec": max((float(row.get("load_sec") or 0) for row in rows), default=0),
        "wall_sec": round(sum(float(row.get("wall_sec") or 0) for row in rows), 2),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", action="append", dest="models")
    # 라이브 러너와 워치독이 실제 공유하는 값. 다르게 재면 벤치가 모델을 축출한다.
    parser.add_argument("--num-ctx", type=int, default=65536)
    parser.add_argument("--timeout-sec", type=int, default=420)
    parser.add_argument("--restore-model", default="plopfit-gemma4-qat:latest")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    results = []
    for model in args.models or DEFAULT_MODELS:
        print(f"[{model}]", flush=True)
        unloaded = _unload_resident(args.base_url)
        if unloaded:
            print(f"  슬롯 해제: {', '.join(unloaded)}", flush=True)
        result = run_model(
            args.base_url, model, num_ctx=args.num_ctx, timeout=args.timeout_sec
        )
        results.append(result)
        print(
            f"  실행정답 {result['passed']}/{result['total']} · "
            f"스왑 {result['swap_load_sec']}초 · 합계 {result['wall_sec']}초",
            flush=True,
        )
    restored = _restore(
        args.base_url,
        args.restore_model,
        num_ctx=args.num_ctx,
        timeout=args.timeout_sec,
    )
    print(
        f"원래 모델 복원 {restored['model']} · 적재 {restored['load_sec']}초 · "
        f"왕복 {restored['wall_sec']}초",
        flush=True,
    )
    payload = {
        "measured_at": time.time(),
        "num_ctx": args.num_ctx,
        "models": results,
        "restored": restored,
    }
    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"기록: {target}")
    return 0 if all(result["passed"] == result["total"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
