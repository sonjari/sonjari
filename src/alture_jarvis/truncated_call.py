"""출력 한도에 걸려 **인자가 잘린 도구 호출**을 알아보고, 실행 대신 돌려줄 정확한 까닭을 만든다 (2026-11-09 · 하네스 후보 20).

맥 손자리(Strata 다리)에게 「유튜브 자막 전체(약 2.2만 자)를 md 로 저장」을 두 번 맡겼고 두 번 다 파일이 안 생겼다(job 9391c6fc ·
1f75fb4a). 모델이 긴 본문을 `local_write_document` 인자에 담다 한 번 쓰기 한도(`ollama_max_predict` 8,192토큰)에서 끊겼다 —
판 기록의 content_cuts 에 `length_limit · had_tool_call · tokens 8192` 가 판마다 2~3번. 다리(`scripts/strata_bridge.py` `_arguments`)는
반쪽 JSON 을 `{}` 로 바꾸고, 하네스는 그 `{}` 를 그대로 실행해 `path_required — 어디에 쓸지(path)가 없다` 를 돌려줬다.
**틀린 까닭**이다: 모델은 path 를 줬고, 길어서 잘렸다. 모델은 같은 긴 호출을 되풀이하다 partial 로 끝났다.

판정은 좁게 한다(헛걸림이 path_required 보다 나쁘면 안 된다):
  - 그 응답이 출력 한도에서 끊겼다(`done_reason == "length"` — Ollama 도 다리도 이 값을 준다).
  - 그 호출이 응답의 **마지막** 호출이다 — 끊긴 것은 마지막에 쓰던 것뿐이다.
  - 그 도구에 필수 인자가 있는데 빠졌거나, 인자 글이 JSON 으로 안 읽힌다. 필수 인자가 없는 도구(`browser_snapshot`)는 `{}` 가 정상이다.
"""
from __future__ import annotations

import json
from typing import Any

#: 판 기록 · 되풀이 판정이 가르는 낱말.
TRUNCATED_ERROR = "tool_arguments_truncated"

#: 나눠 쓸 수 있는 도구와 그 본문 칸 — 여기 있는 도구는 `append: true` 로 이어 쓴다.
_APPENDABLE = {"local_write_file": "content", "local_write_document": "text"}


def _required(name: str, tool_defs: list[dict[str, Any]] | None) -> list[str]:
    for tool in tool_defs or []:
        function = tool.get("function") or {}
        if str(function.get("name") or "") == name:
            return [str(item) for item in (function.get("parameters") or {}).get("required") or []]
    return []


def truncated_tool_call(
    message: dict[str, Any], call: dict[str, Any], calls: list[dict[str, Any]], tool_defs: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """이 호출의 인자가 출력 한도에 잘렸으면 그 사실(도구 · 빠진 칸 · 한도), 아니면 None."""
    metrics = message.get("_metrics") or {}
    if str(metrics.get("done_reason") or "") != "length" or not calls or call is not calls[-1]:
        return None
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    required = _required(name, tool_defs)
    if not required:
        return None
    raw = function.get("arguments")
    unreadable = False
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            unreadable, raw = True, {}
    arguments = raw if isinstance(raw, dict) else {}
    missing = [key for key in required if arguments.get(key) in (None, "")]
    if not missing and not unreadable:
        return None
    return {
        "tool": name,
        "missing": missing,
        "unreadable_json": unreadable,
        "limit_tokens": int(metrics.get("eval_count") or 0),
    }


def truncated_observation(found: dict[str, Any]) -> dict[str, Any]:
    """실행하지 않고 모델에게 돌려줄 결과 — 무엇이 왜 안 됐고 어떻게 하면 되는지."""
    name = found["tool"]
    limit = int(found.get("limit_tokens") or 0)
    # 한국어는 대체로 한 글자가 한 토큰 안팎이다. 생각 · 인자 뼈대 몫을 빼고 한도의 3/8 을 한 번 분량으로 권한다.
    chunk = max(1000, limit * 3 // 8) if limit else 3000
    limit_text = f"{limit}토큰" if limit else "한 번에 쓸 수 있는 길이"
    head = (
        f"[도구가 보낸 안내] 실행하지 않았다. 네 응답이 출력 한도({limit_text})에 닿아 `{name}` 의 인자가 중간에 잘렸다"
        + (f" — 도착한 인자에 {', '.join(found['missing'])} 가 없는 것은 빠뜨려서가 아니라 잘려서다." if found.get("missing") else ".")
        + " 같은 긴 내용을 한 번에 다시 보내면 또 잘린다. "
    )
    field = _APPENDABLE.get(name)
    if field:
        how = (
            f"나눠 써라: ① `{name}` 에 path 와 {field} 의 앞부분(한 번에 약 {chunk:,}자 이하)만 넣어 먼저 쓴다 "
            f"② 나머지는 **같은 path** 에 `append: true` 를 붙여 같은 크기로 여러 번 이어 붙인다. "
            "이어 붙인 결과에 이미 쓴 부분을 다시 넣지 마라."
        )
    else:
        how = f"인자를 짧게 줄이거나, 일을 여러 번의 호출로 나눠라(한 번에 약 {chunk:,}자 이하)."
    return {
        "ok": False,
        "tool": name,
        "error": TRUNCATED_ERROR,
        "output_limit_tokens": limit,
        "missing_arguments": list(found.get("missing") or []),
        "instruction": head + how,
    }
