"""우리가 직접 쓴 장표 템플릿을 장 틀 파일로 나눈다 (2026-10-25).

원본: src/alture_jarvis/slide_themes/own/<slug>/template.html (한 파일에 <style> + 장마다 <section class="slide 장이름">)
결과: 같은 폴더의 theme.css · sections.json + own/index.json

옮긴 템플릿(`port_slide_templates.py`)은 다시 만들 때 templates/ 폴더를 통째로 지운다 — 그래서 우리 것은 own/ 에 따로 둔다.
다시 만들기: `python scripts/build_own_slide_templates.py`
"""

from __future__ import annotations

import json
import re
from pathlib import Path

OWN = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "slide_themes" / "own"

#: slug → (이름, 언제, 용도 꼬리표, 분위기, 격식, 어두움, 장 순서 안내)
META: dict[str, tuple] = {
    "ir-brief": (
        "IR · 투자 설명", "투자 IR · 피치덱 · 지원사업 발표 평가 — 섹션 제목 + 밑줄 두 줄 헤드라인 + 도식",
        ("투자", "IR", "사업계획", "창업", "재무", "전략", "임원"), ("신뢰", "차분", "깔끔"), "높음", False,
        "IR 장 순서와 조립 레시피(있는 것만, 이 순서로 · 레시피는 출발점): "
        "1 표지 = cover 부품(frame · figure 에 요청 금액 · meta 에 회사 · 발표자) / 2 질문 셋 = points 3개 / 3 사업 모델 = flow(우리 on) + kv 또는 text(수익 · 청구) / "
        "4 견인 지표(사용자 · 매출이 이미 있으면 앞쪽, 없으면 뺀다) = metrics(evidence 로 원본 화면 자리) / "
        "5 시장 = pair(지금 → 바뀐 뒤) + text(왜 지금) · layout 2:1 / 6 경쟁 = table(우리 줄 highlight) + steps(연차별 목표) · 2:1 / "
        "7 단위 경제 = bars(같은 눈금 · 우리 on) + panel(이익률 · 기준) · 3:2 / "
        "8 핵심 경쟁력(장마다 하나 · 여러 장 가능) = stat(위험 크기 · tone loss) + steps(막는 방법) + calc(사례 계산) · 1:1:1 / "
        "9 로드맵 = stages / 10 손익 · 자금 = table(5년) + panel(누적 필요 자금) + kv(조달 진행) · 2:1 / "
        "11 팀 = people 두 묶음(산업 · 현장) / 12 요약 = points 3개 + bottom(한 문장 결론) / 13 마무리 = closing 부품(frame · 요청 한 문장 · meta 에 연락). "
        "모든 장: head 「섹션」 + sub 「소주제」, lede 두 줄(첫 줄 사실 · 둘째 줄 그래서, <u> 밑줄 핵심어), 숫자에는 산출식 · 출처.",
    ),
}


def build(slug: str) -> dict:
    folder = OWN / slug
    html = (folder / "template.html").read_text(encoding="utf-8")
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
    css = "/* sonjari-template */\n" + css + (
        "\nhtml,body{margin:0!important;padding:0!important;width:1280px;height:720px;overflow:hidden}"
        "\nsection{width:1280px!important;height:720px!important;word-break:keep-all}")
    sections = []
    for m in re.finditer(r"<section\b([^>]*)>(.*?)</section>", html, re.S):
        attrs, inner = m.group(1), m.group(2)
        cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1]
        label = (re.search(r'data-screen-label="([^"]*)"', attrs) or [None, ""])[1]
        attrs = re.sub(r'\s*data-screen-label="[^"]*"', "", attrs)
        sections.append({"class": cls.split()[0] if cls else "", "classes": cls, "label": label,
                         "html": f"<section{attrs}>{inner.strip()}</section>"})
    (folder / "theme.css").write_text(css, encoding="utf-8")
    (folder / "sections.json").write_text(json.dumps(sections, ensure_ascii=False, indent=1), encoding="utf-8")
    name, when, uses, moods, formality, dark, flow = META[slug]
    return {"name": name, "when": when, "uses": list(uses), "moods": list(moods), "formality": formality, "dark": dark,
            "layouts": [s["class"] for s in sections], "own": True, "flow": flow}


def main() -> None:
    index = {slug: build(slug) for slug in META}
    (OWN / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(index), sum(len(v["layouts"]) for v in index.values()))


if __name__ == "__main__":
    main()
