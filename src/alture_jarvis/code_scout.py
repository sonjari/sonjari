from __future__ import annotations

import json
import subprocess
import time
from typing import Any

import httpx

from .config import JarvisConfig


SCOUT_FORMAT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "priority_files": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10,
        },
        "hypotheses": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
        "next_reads": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10,
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
        # ★ 정찰기가 **대신 읽는다.** 예전에는 경로 순위만 돌려줘서, 구현기가
        #   같은 파일을 처음부터 다시 읽어야 했다. 3060 이 놀고 있는 동안
        #   3090 의 창이 원문으로 차는 구조였다.
        #   여기서 한 줄씩 요약해 주면 구현기는 원문 20,000 토큰 대신
        #   요약 몇백 토큰만 받는다 — 앤트로픽 스킬의 「본문은 필요할 때만」이다.
        "findings": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
    },
    "required": ["priority_files", "hypotheses", "next_reads", "risks", "findings"],
    "additionalProperties": False,
}


def _strings(value: Any, *, limit: int, max_chars: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:max_chars])
        if len(result) >= limit:
            break
    return result


def parse_scout_json(content: str) -> dict[str, Any]:
    """Ollama가 JSON 주위에 fence를 붙여도 닫힌 객체 하나만 받는다."""
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("code_scout_invalid_json")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("code_scout_object_required")
    return parsed


def normalize_scout_report(
    raw: dict[str, Any], candidate_paths: list[str]
) -> dict[str, list[str]]:
    """정찰기가 색인에 없는 경로를 지어내면 버리고 결정론 순위로 폴백한다."""
    allowed = list(dict.fromkeys(str(path) for path in candidate_paths if str(path).strip()))
    allowed_set = set(allowed)
    priority = [
        path for path in _strings(raw.get("priority_files"), limit=10)
        if path in allowed_set
    ]
    next_reads = [
        path for path in _strings(raw.get("next_reads"), limit=10)
        if path in allowed_set
    ]
    if not priority:
        priority = allowed[:6]
    if not next_reads:
        next_reads = priority[:6]
    return {
        "priority_files": priority,
        "hypotheses": _strings(raw.get("hypotheses"), limit=6),
        "next_reads": next_reads,
        "risks": _strings(raw.get("risks"), limit=6),
        "findings": _strings(raw.get("findings"), limit=8, max_chars=400),
    }


def format_scout_handoff(report: dict[str, Any]) -> str:
    def line(label: str, key: str) -> str:
        values = _strings(report.get(key), limit=10)
        return f"{label}: " + (", ".join(values) if values else "없음")

    return "\n".join(
        [
            "[Qwen3.5 읽기 전용 정찰기 인수인계]",
            line("우선 읽을 파일", "priority_files"),
            line("정찰기가 실제로 본 것", "findings"),
            line("가설", "hypotheses"),
            line("다음 읽기", "next_reads"),
            line("주의점", "risks"),
            "정찰기 요약은 **읽기의 대체가 아니라 좁히기**다. 고치기 전에는 그 구간을 직접 열어 확인하라.",
        ]
    )


class CodeScout:
    """별도 3060 Ollama에서 도구 없이 저장소 후보만 좁히는 보조 모델."""

    def __init__(self, config: JarvisConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(self.config.code_scout_enabled)

    def _model_is_loaded(self, client: httpx.Client) -> bool:
        try:
            response = client.get(
                f"{self.config.code_scout_base_url.rstrip('/')}/api/ps", timeout=2.0
            )
            response.raise_for_status()
            models = response.json().get("models")
        except Exception:
            return False
        target = self.config.code_scout_model.split(":", 1)[0].casefold()
        return any(
            target in str(item.get("name") or item.get("model") or "").casefold()
            for item in (models if isinstance(models, list) else [])
            if isinstance(item, dict)
        )

    def _free_vram_mb(self) -> int | None:
        try:
            completed = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=uuid,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        target = str(self.config.code_scout_gpu_uuid or "").casefold()
        for line in completed.stdout.splitlines():
            uuid, separator, free = line.partition(",")
            if separator and uuid.strip().casefold() == target:
                try:
                    return int(free.strip())
                except ValueError:
                    return None
        return None

    def _ensure_capacity(self, client: httpx.Client) -> None:
        # 이미 적재된 모델은 자신이 메모리를 쓰고 있으므로 free 눈금을 다시
        # 적용하면 두 번째 호출부터 자기 자신을 막게 된다.
        if self._model_is_loaded(client):
            return
        free = self._free_vram_mb()
        minimum = max(0, int(self.config.code_scout_min_free_vram_mb))
        if free is not None and free < minimum:
            raise RuntimeError(f"code_scout_vram_guard:{free}<{minimum}")

    def analyze(self, task: str, index_result: dict[str, Any]) -> dict[str, Any]:
        repo_map = index_result.get("repo_map")
        repo_map = repo_map if isinstance(repo_map, dict) else {}
        matches = repo_map.get("matches")
        matches = matches if isinstance(matches, list) else []
        candidate_paths = [
            str(item.get("path") or "")
            for item in matches
            if isinstance(item, dict) and item.get("path")
        ]
        if not candidate_paths:
            raise ValueError("code_scout_candidates_required")

        index = index_result.get("index")
        index = index if isinstance(index, dict) else {}
        bounded_input = {
            "task": str(task or "")[:1200],
            "index": {
                key: index.get(key)
                for key in ("total_files", "updated_files", "truncated", "languages")
                if index.get(key) is not None
            },
            "repo_map": repo_map,
        }
        serialized = json.dumps(bounded_input, ensure_ascii=False)[:40_000]
        body = {
            "model": self.config.code_scout_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a read-only code reconnaissance assistant. Rank only paths present "
                        "in the supplied repository map. Do not propose edits or commands. "
                        "In `findings`, summarise ONLY what the supplied code excerpts actually "
                        "show, one line each, in the form 'path:lines - what this code does'. "
                        "Never describe code you were not shown. Return only the requested JSON object."
                    ),
                },
                {"role": "user", "content": serialized},
            ],
            "stream": False,
            "think": False,
            "format": SCOUT_FORMAT,
            "keep_alive": self.config.code_scout_keep_alive,
            "options": {
                "num_ctx": max(4096, int(self.config.code_scout_num_ctx)),
                "num_predict": max(128, int(self.config.code_scout_max_predict)),
                "temperature": 0.2,
                "top_p": 0.8,
                "top_k": 20,
            },
        }
        started = time.monotonic()
        with httpx.Client(timeout=float(self.config.code_scout_timeout_sec)) as client:
            self._ensure_capacity(client)
            response = client.post(
                f"{self.config.code_scout_base_url.rstrip('/')}/api/chat", json=body
            )
            response.raise_for_status()
            payload = response.json()
        message = payload.get("message")
        message = message if isinstance(message, dict) else {}
        report = normalize_scout_report(
            parse_scout_json(str(message.get("content") or "")), candidate_paths
        )
        return {
            **report,
            "model": self.config.code_scout_model,
            "endpoint": self.config.code_scout_base_url,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "candidate_count": len(candidate_paths),
        }
