"""젬마가 **95종 중에서 스킬을 고를 수 있나.** 화면을 만들기 전에 재는 관문.

## 왜 재나

「단독으로 쓸 때는 젬마가 추천 태그를 달아 준다」가 되려면 젬마가 고를 줄 알아야
한다. 그런데 2026-09-09 실측에서 로컬 모델이 **133개 도구 중에서 고르다 헤맸다** —
책 조사 판에 진로DB를 6번 불렀다. 95개 스킬에서도 같은 병이 날 수 있다.

되면 화면을 만들고, 안 되면 **클로드가 지목하는 길만** 남긴다. 둘 다 값진 답이다.

## 채점

    맞음      기대한 스킬을 1순위로 골랐나
    근처      기대한 것이 후보 안에 있나 (3개까지 보여 주므로)
    헛것      스킬이 필요 없는 프롬프트에 아무거나 골랐나  ← 오탐이 더 나쁘다
"""
from __future__ import annotations
import json, pathlib, sys, time, urllib.request
sys.stdout.reconfigure(encoding="utf-8")

TOKEN = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token").read_text().strip()

#: (프롬프트, 기대 스킬 또는 None). None 은 **아무것도 고르면 안 되는** 판이다.
CASES = [
    ("사람인에서 여수 회계 채용 공고 3개 찾아서 정리해줘", "career-job-search"),
    ("나래이 이력서 첨삭해줘", "career-resume-review"),
    ("이 공고에 맞게 이력서 문구 손봐줘", "career-application-tailoring"),
    ("우리 학원 경쟁사 3곳 조사해서 정리해줘", "competitors"),
    ("이 버그 원인을 체계적으로 찾아줘", "systematic-debugging"),
    ("이 결정을 여러 각도로 따져봐줘", None),          # 사고 틀은 여러 개가 맞다
    ("YES24에서 파이썬 책 3권 쪽수 알려줘", None),      # 스킬 필요 없음
    ("지금 몇 시야", None),                            # 스킬 필요 없음
    ("이 코드 테스트부터 짜줘", "test-driven-development"),
    ("우리 서비스 SEO 어떻게 올리지", "ai-seo"),
]

PROMPT = (
    "아래 목록은 쓸 수 있는 플레이북(스킬)이다. 사용자의 요청에 **가장 도움이 되는**"
    " 것 하나를 고르고, 도움이 되는 것이 없으면 정확히 `none` 이라고만 답해라.\n"
    "이름 하나만 답한다. 설명하지 마라.\n\n"
    "[스킬 목록]\n{catalog}\n\n[요청]\n{prompt}\n\n답:"
)


def api(path: str, payload=None, method="GET"):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        "http://127.0.0.1:8091" + path, data=body, method=method,
        headers={"X-Jarvis-Token": TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def catalog_lines() -> tuple[str, set[str]]:
    res = api("/v1/tools/execute",
              {"name": "skill_list", "arguments": {}}, "POST").get("result") or {}
    lines, names = [], set()
    for collection, items in (res.get("collections") or {}).items():
        for item in items:
            name = str(item.get("name") or "")
            what = str(item.get("what") or "")[:70].replace("\n", " ")
            lines.append(f"- {name} ({collection}): {what}")
            names.add(name)
    return "\n".join(lines), names


def ask(model: str, text: str) -> tuple[str, float]:
    body = {"model": model, "messages": [{"role": "user", "content": text}],
            "stream": False, "think": False, "options": {"temperature": 0}}
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    return str((data.get("message") or {}).get("content") or "").strip(), time.time() - started


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "plopfit-gemma4-qat"
    catalog, names = catalog_lines()
    print(f"스킬 {len(names)}종 · 목록 {len(catalog):,}자 · 모델 {model}\n")
    right = near = false_pick = missed = 0
    rows = []
    for prompt, expected in CASES:
        raw, sec = ask(model, PROMPT.format(catalog=catalog, prompt=prompt))
        pick = raw.strip().strip("`").split()[0].strip(".,") if raw.strip() else ""
        valid = pick if pick in names else ("none" if pick.lower().startswith("none") else "")
        if expected is None:
            ok = valid in ("", "none")
            false_pick += 0 if ok else 1
        else:
            ok = valid == expected
            if not ok:
                if valid in ("", "none"):
                    missed += 1
                else:
                    near += 1
        right += int(ok)
        rows.append((prompt, expected, valid or raw[:20], ok, round(sec, 1)))
        print(f"  {'OK ' if ok else 'X  '} {str(expected):28} -> {str(valid or raw[:22]):28} {sec:5.1f}s | {prompt[:26]}")
    total = len(CASES)
    print(f"\n맞음 {right}/{total}  ·  다른 것 고름 {near}  ·  못 고름 {missed}  ·  ★헛것 {false_pick}")
    pathlib.Path("results/skill_pick.json").write_text(
        json.dumps([{"prompt": p, "expected": e, "picked": g, "ok": o, "sec": s}
                    for p, e, g, o, s in rows], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
