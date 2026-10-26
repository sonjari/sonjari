"""원본 HTML 장표 템플릿을 손자리 결로 옮긴다 (2026-10-25 6차 · 대표 「원본 느낌을 전부 들고 와야지」).

원본: zarazhangrui/beautiful-html-templates (MIT, Copyright (c) 2026 Zara Zhang). 장마다 <section> 인 템플릿만.
바꾸는 것은 셋뿐 — 크기(1920×1080 → 1280×720, px 값을 2/3), 글꼴(구글 글꼴 → 받는 사람 PC 에 있는 윈도우 글꼴 중
성격이 같은 것), 바깥 링크 · 스크립트 · 덱 무대. 배치 · 장식 · 등장 애니메이션은 원본 그대로 둔다.

쓰는 법:
    python scripts/port_slide_templates.py <beautiful-html-templates/templates 폴더>
결과: src/alture_jarvis/slide_themes/templates/<slug>/{theme.css, sections.json} + index.json + LICENSE
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "alture_jarvis" / "slide_themes" / "templates"
SCALE = 1280 / 1920

#: 고른 18개 — (한국어 이름, 언제, 용도 꼬리표, 분위기 꼬리표, 격식, 어두운가). 원본 template.json 의 occasion · mood 를 보고 우리 말로.
META: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...], str, bool]] = {
    "editorial-forest": ("숲 · 분홍 편집", "분기 보고 · 내부 공유 · 팀 소식 — 따뜻한 잡지처럼",
                         ("보고", "분기", "소개", "회고", "브랜드"), ("따뜻하게", "차분"), "보통", False),
    "emerald-editorial": ("에메랄드 표지", "임원 보고 · 전략 발표 · 분기 리뷰 — 잡지 표지처럼 힘 있게",
                          ("전략", "임원", "보고", "분기", "계획", "투자", "피칭", "사업계획"), ("힘있게", "신뢰"), "높음", False),
    "cobalt-grid": ("코발트 연구지", "연구 · 조사 보고 · 트렌드 리포트 — 차분하고 진지하게",
                    ("연구", "조사", "리서치", "동향", "보고", "논문", "학위", "심사", "세미나"), ("차분", "신뢰"), "높음", False),
    "editorial-tri-tone": ("세 빛 잡지", "브랜드 · 패션 · 라이프스타일 · 문화 기획 — 잡지 펼침면처럼",
                           ("브랜드", "기획", "라이프스타일", "마케팅"), ("따뜻하게", "고급"), "보통", False),
    "biennale-yellow": ("노란 전시", "전시 · 문화 행사 · 컨퍼런스 프로그램 — 포스터처럼",
                        ("전시", "행사", "프로그램", "디자인"), ("고급", "차분"), "높음", False),
    "broadside": ("호외 신문", "선언 · 비전 발표 · 브랜드 메시지 — 강렬하게",
                  ("비전", "브랜드", "선언", "발표"), ("힘있게",), "보통", True),
    "creative-mode": ("크리에이티브", "기획 제안 · 디자인 스튜디오 · 광고 제안 — 자신 있게",
                      ("제안", "기획", "디자인", "광고", "마케팅"), ("힘있게", "발랄"), "보통", False),
    "mat": ("무광 공방", "제품 · 공간 · 공예 브랜드 소개 — 어둡고 따뜻하게",
            ("제품", "브랜드", "공간", "소개"), ("고급", "따뜻하게"), "보통", True),
    "neo-grid-bold": ("네온 격자", "제품 출시 · 창업 피칭 · 데이터 강조 — 또렷하게",
                      ("제품", "출시", "투자", "피칭", "데이터"), ("힘있게",), "보통", False),
    "peoples-platform": ("광장 포스터", "캠페인 · 공공 · 커뮤니티 · 분기 리뷰 — 크고 솔직하게",
                         ("캠페인", "커뮤니티", "공공", "행사", "보고"), ("힘있게", "발랄"), "낮음", False),
    "pin-and-paper": ("핀과 종이", "조사 결과 · 회고 · 생각 정리 — 손으로 만든 느낌",
                      ("조사", "회고", "연구", "보고"), ("따뜻하게", "친근"), "보통", False),
    "sakura-chroma": ("레트로 카탈로그", "제품 카탈로그 · 신제품 소개 · 브랜드 연감 — 발랄하게",
                      ("제품", "카탈로그", "출시", "브랜드"), ("발랄", "따뜻하게"), "낮음", False),
    "soft-editorial": ("고요한 편집", "리서치 공유 · 인사이트 · 브랜드 이야기 — 문학적으로",
                       ("리서치", "인사이트", "브랜드", "연구", "보고"), ("차분", "고급"), "높음", False),
    "stencil-tablet": ("스텐실 기록", "기관 · 문화재 · 장기 프로젝트 · 원칙 정리 — 묵직하게",
                       ("기관", "프로젝트", "원칙", "전략"), ("신뢰", "힘있게"), "높음", False),
    "long-table": ("긴 식탁", "모임 · 행사 · 매장 · 지역 커뮤니티 소개 — 따뜻하게",
                   ("행사", "모임", "매장", "커뮤니티", "소개"), ("따뜻하게", "친근"), "보통", False),
    "grove": ("숲속 정원", "친환경 · 웰니스 · 자연 · 식음료 브랜드 — 어둡고 차분하게",
              ("환경", "웰니스", "브랜드", "제안"), ("차분", "고급"), "높음", True),
    "scatterbrain": ("포스트잇 벽", "브레인스토밍 · 워크숍 · 아이디어 회의 — 자유롭게",
                     ("워크숍", "아이디어", "회의", "기획"), ("발랄", "친근"), "낮음", False),
    "daisy-days": ("데이지 교실", "수업 · 어린이 · 교육 프로그램 · 공동체 워크숍 — 다정하게",
                   ("강의", "교육", "어린이", "워크숍"), ("발랄", "친근"), "낮음", False),
}

SERIF = re.compile(r"serif\b(?!-)|garamond|playfair|fraunces|cormorant|caslon|newsreader|crimson|spectral|cardo|lora|baskerville|"
                   r"cinzel|marcellus|bodoni|didot|georgia|stix|gelasio|alegreya(?! sans)|literata|instrument serif|dm serif|abril|"
                   r"prata|young serif|gloock|bitter|merriweather|tenor|source serif|libre caslon|ibm plex serif", re.I)
MONO = re.compile(r"mono|code|courier|consolas|menlo|vt323|press start", re.I)
HEAVY = re.compile(r"anton|archivo black|bebas|oswald|league spartan|alfa slab|shrikhand|unbounded|black|bowlby|rubik mono|"
                   r"climate crisis|dela gothic|syne|clash", re.I)
STACKS = {"serif": "Georgia, 'Batang', serif", "mono": "Consolas, 'Malgun Gothic', monospace",
          "heavy": "'Arial Black', 'Malgun Gothic', sans-serif", "sans": "'Segoe UI', 'Malgun Gothic', sans-serif"}


def font_stack(family: str) -> str:
    head = family.split(",")[0]
    if re.fullmatch(r"\s*var\(--[\w-]+\)\s*", family) or re.fullmatch(r"\s*(?:inherit|initial|unset)\s*", family):
        return family
    if MONO.search(head):
        return STACKS["mono"]
    if SERIF.search(head) and not re.search(r"sans", head, re.I):
        return STACKS["serif"]
    if HEAVY.search(head):
        return STACKS["heavy"]
    if re.fullmatch(r"\s*serif\s*", family):
        return STACKS["serif"]
    if re.fullmatch(r"\s*monospace\s*", family):
        return STACKS["mono"]
    return STACKS["sans"]


def scale_px(text: str) -> str:
    def one(m: re.Match) -> str:
        raw = float(m.group(1))
        value = raw * SCALE
        if raw != 0 and abs(value) < 1:  # 1px 선은 1px 로 남긴다
            value = 1 if value > 0 else -1
        return f"{value:.2f}".rstrip("0").rstrip(".") + "px"
    return re.sub(r"(-?\d+(?:\.\d+)?)px", one, text)


def convert_css(css: str) -> str:
    css = re.sub(r"@import[^;]+;", "", css)
    css = re.sub(r"(font-family\s*:\s*)([^;{}]+)", lambda m: m.group(1) + font_stack(m.group(2)), css)
    css = re.sub(r"(--[\w-]*(?:font|serif|sans|mono|display|body|head|type)[\w-]*\s*:\s*)([^;{}]+)",
                 lambda m: m.group(1) + font_stack(m.group(2)), css)
    css = scale_px(css)
    css = re.sub(r"deck-stage\s*\{[^}]*\}", "", css)
    return "/* sonjari-template */\n" + css + ("\nhtml,body{margin:0!important;padding:0!important;width:1280px;height:720px;overflow:hidden}"
                  "\nsection{width:1280px!important;height:720px!important;word-break:keep-all}")


def port(src: Path, slug: str) -> dict:
    html = (src / "template.html").read_text(encoding="utf-8")
    css = convert_css("\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)))
    stage = re.search(r"<deck-stage[^>]*>(.*)</deck-stage>", html, re.S)
    body = stage.group(1) if stage else html
    sections = []
    for m in re.finditer(r"<section\b([^>]*)>(.*?)</section>", body, re.S):
        attrs, inner = m.group(1), m.group(2)
        cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1]
        label = (re.search(r'data-screen-label="([^"]*)"', attrs) or [None, ""])[1]
        attrs = re.sub(r'\s*data-screen-label="[^"]*"', "", attrs)
        inner = re.sub(r"<!--.*?-->", "", inner, flags=re.S)
        sections.append({"class": cls.split()[0] if cls else "", "classes": cls, "label": label,
                         "html": scale_px(f"<section{attrs}>{inner.strip()}</section>")})
    target = OUT / slug
    target.mkdir(parents=True, exist_ok=True)
    (target / "theme.css").write_text(css, encoding="utf-8")
    (target / "sections.json").write_text(json.dumps(sections, ensure_ascii=False, indent=1), encoding="utf-8")
    name, when, uses, moods, formality, dark = META[slug]
    return {"name": name, "when": when, "uses": list(uses), "moods": list(moods), "formality": formality, "dark": dark,
            "layouts": [s["class"] for s in sections]}


def main() -> None:
    src = Path(sys.argv[1])
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    index = {slug: port(src / slug, slug) for slug in META}
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copy(src.parent / "LICENSE", OUT / "LICENSE")
    (OUT / "SOURCE.md").write_text(
        "# 출처\n\n이 폴더의 템플릿 18개는 zarazhangrui/beautiful-html-templates(MIT, `LICENSE`)에서 옮겼다(커밋 e5e204f).\n"
        "바꾼 것: 크기(1920→1280, px 값 2/3) · 글꼴(구글 글꼴 → 윈도우 글꼴) · 바깥 링크와 스크립트 제거 · 한국어 이름과 꼬리표.\n"
        "다시 만들기: `python scripts/port_slide_templates.py <templates 폴더>`.\n", encoding="utf-8")
    print(len(index), sum(len(v["layouts"]) for v in index.values()))


if __name__ == "__main__":
    main()
