"""모델이 **판마다 실제로 받는 도구**를 갈래별로 센다 (2026-09-21, 인수인계 「Cowork 가 싣는 도구 수 재기」).

운영 백엔드의 도구 카탈로그(`/v1/tools`)를 받아, 에이전트가 쓰는 **진짜 함수**(`_route_scoped_tool_definitions`·
`_platform_scoped_tool_definitions`·`select_code_tool_profile`)를 그대로 통과시킨다. 우리가 짐작한 표가 아니라 코드가 고르는 것을 센다.

    python count_tools_offered.py            # 운영 8091 (토큰은 파일에서 읽고 출력하지 않는다)
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from alture_jarvis import agent as A  # noqa: E402
from alture_jarvis.code_runtime import select_code_tool_profile  # noqa: E402

TOKEN = Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\control.token").read_text(encoding="utf-8-sig").strip()


def catalog() -> list[dict]:
    request = urllib.request.Request("http://127.0.0.1:8091/v1/tools", headers={"X-JARVIS-TOKEN": TOKEN})
    rows = json.load(urllib.request.urlopen(request, timeout=20))
    return [
        {"type": "function", "function": {"name": r["name"], "description": r["description"],
                                          "parameters": r.get("parameters") or {"type": "object", "properties": {}}}}
        for r in rows if str(r.get("enabled")).lower() != "false"
    ]


def size(defs: list[dict]) -> int:
    return sum(len(json.dumps(d, ensure_ascii=False)) for d in defs)


def names(defs: list[dict]) -> list[str]:
    return [str(d["function"]["name"]) for d in defs]


def main() -> None:
    defs = catalog()
    print(f"카탈로그(켜진 것): {len(defs)}개 · {size(defs):,}자\n")

    rows = []
    # 1) Cowork 일반 판 — 말하지 않은 서비스에 올리는 손만 빠진다
    plain = A._platform_scoped_tool_definitions(A._route_scoped_tool_definitions(defs, web_only=False), "이 PC 의 현재 상태를 진단해줘")
    rows.append(("Cowork 일반 (진단·문서·일정 아님)", plain))
    # 2) 같은 판인데 블로그·메일·일정을 말한 경우
    said = A._platform_scoped_tool_definitions(A._route_scoped_tool_definitions(defs, web_only=False),
                                               "블로그에 올리고 메일 보내고 일정 만들어줘")
    rows.append(("Cowork · 블로그·메일·일정을 말한 판", said))
    # 3) Cowork 웹 조사 판
    web = A._platform_scoped_tool_definitions(A._route_scoped_tool_definitions(defs, web_only=True), "책 세 권 쪽수 조사해줘")
    rows.append(("Cowork 웹 조사 (가서 보고 와서 정리)", web))
    # 4) Code — 실제 프로필
    for label, prompt in (
        ("Code · 코딩(고치기)", "test_calc.py 가 실패한다. calc.py 를 고치고 pytest 로 확인해."),
        ("Code · 코딩(페이지 만들기)", "index.html 을 만들고 local_preview_page 로 열어서 확인해."),
    ):
        profile = select_code_tool_profile(prompt, force_sandbox=False, context="")
        keep = set(profile.tool_names)
        rows.append((label + f" [{profile.name}]", [d for d in defs if d["function"]["name"] in keep]))

    print(f"{'갈래':<46}{'도구':>5}{'글자':>9}{'전체 대비':>10}")
    total_chars = size(defs)
    for label, chosen in rows:
        print(f"{label:<46}{len(chosen):>5}{size(chosen):>9,}{size(chosen) / total_chars:>9.0%}")

    print("\n가장 큰 스키마 10개(전체 카탈로그):")
    for d in sorted(defs, key=lambda d: -len(json.dumps(d, ensure_ascii=False)))[:10]:
        print(f"  {len(json.dumps(d, ensure_ascii=False)):>6,}자  {d['function']['name']}")

    # Cowork 일반 판이 싣는 것 중 그 판이 **거의 안 쓸** 무리(입시·카메라·한글·구글쓰기…)
    groups: dict[str, list[str]] = {}
    for n in names(plain):
        prefix = n.split("_", 1)[0]
        groups.setdefault(prefix, []).append(n)
    print("\nCowork 일반 판의 도구를 접두사별로:")
    for prefix, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        chars = size([d for d in plain if d["function"]["name"] in set(members)])
        print(f"  {prefix:<14}{len(members):>3}개 {chars:>8,}자")


if __name__ == "__main__":
    main()
