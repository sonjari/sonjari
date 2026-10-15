"""도구 스키마가 **몇 토큰**인가 — 모델에게 직접 물어 잰다 (2026-09-21, 「Cowork 가 싣는 도구 수」의 다음 질문).

`count_tools_offered.py` 는 글자 수다. 무료 티어(8GB 노트북, 4B, 컨텍스트 32K)에 아픈 것은 **토큰**이다. 한국어가 섞인 JSON 은
글자 수로 토큰을 짐작하면 틀린다 — Ollama 가 프롬프트를 실제로 토큰화해 `prompt_eval_count` 로 알려 준다.

★ **이미 올라와 있는 모델을 그 컨텍스트 그대로** 쓴다(`/api/ps` 에서 읽는다). 다른 `num_ctx` 를 주면 Ollama 가 러너를 새로
  띄워 운영 모델이 축출된다(이 저장소가 여러 번 겪은 것). 토크나이저는 같은 계열(Qwen 3.5·3.6)이라 4B 도 같은 값이다.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import count_tools_offered as C  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"


def post(path: str, body: dict, timeout: float = 300) -> dict:
    request = urllib.request.Request(OLLAMA + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=timeout))


def loaded() -> tuple[str, int]:
    running = json.load(urllib.request.urlopen(OLLAMA + "/api/ps", timeout=10)).get("models") or []
    if not running:
        raise SystemExit("올라와 있는 모델이 없다 — 운영 모델이 떠 있을 때 돌려라(다른 컨텍스트로 새로 띄우면 축출된다)")
    return running[0]["name"], int(running[0].get("context_length") or 0)


def tokens(model: str, ctx: int, text: str) -> int:
    out = post("/api/generate", {"model": model, "prompt": text, "stream": False, "raw": True,
                                 "options": {"num_ctx": ctx, "num_predict": 1, "temperature": 0}, "keep_alive": "24h"})
    return int(out.get("prompt_eval_count") or 0)


def main() -> None:
    model, ctx = loaded()
    print(f"모델 {model} · 컨텍스트 {ctx:,} (운영 값 그대로)\n")
    defs = C.catalog()
    from alture_jarvis import agent as A
    from alture_jarvis.code_runtime import select_code_tool_profile

    rows = [
        ("Cowork 일반", A._platform_scoped_tool_definitions(A._route_scoped_tool_definitions(defs, web_only=False), "이 PC 상태를 진단해줘")),
        ("Cowork 웹 조사", A._platform_scoped_tool_definitions(A._route_scoped_tool_definitions(defs, web_only=True), "책 세 권 쪽수 조사해줘")),
    ]
    # 작은 컨텍스트(≤ tool_surface_compact_max_ctx)에서 실제로 모델에 가는 표면 — 이야기가 안 나온 가족을 빼고 긴 설명문을 줄인 것
    for label, web_only, said in (
        ("Cowork 일반·압축", False, "이 PC 상태를 진단해줘"),
        ("Cowork 웹조사·압축", True, "책 세 권 쪽수 조사해줘"),
    ):
        scoped = A._platform_scoped_tool_definitions(A._route_scoped_tool_definitions(defs, web_only=web_only), said, compact=True)
        rows.append((label, A._compact_tool_descriptions(scoped)))
    profile = select_code_tool_profile("test_calc.py 가 실패한다. calc.py 를 고치고 pytest 로 확인해.", force_sandbox=False, context="")
    keep = set(profile.tool_names)
    rows.append(("Code 코딩", [d for d in defs if d["function"]["name"] in keep]))

    base = tokens(model, ctx, "안녕")
    print(f"{'갈래':<14}{'도구':>5}{'글자':>9}{'토큰':>9}{'글자/토큰':>10}{'32K 대비':>10}{'8K 대비':>9}")
    for label, chosen in rows:
        text = json.dumps(chosen, ensure_ascii=False)
        n = max(0, tokens(model, ctx, text) - base)
        print(f"{label:<14}{len(chosen):>5}{len(text):>9,}{n:>9,}{len(text) / max(n, 1):>10.2f}{n / 32768:>10.0%}{n / 8192:>9.0%}")
    print("\n※ 위는 **도구 스키마만**이다. 시스템 프롬프트(계약 ~12K자)·저장소 지도·대화·도구 결과가 이 위에 더 얹힌다.")


if __name__ == "__main__":
    main()
