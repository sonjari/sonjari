"""업데이트 「바뀐 것」 쇼의 예시 장표를 만든다 (2026-10-26 · 0.4.34.0).

쇼(`ui/src/workspace/WhatsNewShow.tsx`)는 앱의 진짜 장표 칸(DeckStage)에 예시 사건을 흘려 움직인다. 그 사건에 실을 장 HTML 을
**제품과 같은 길**로 만든다 — 결 고르기 표지는 `slides.guide_payload` → `slides_style.cover_preview`, 장은 지금 결 CSS(앱 글꼴)로
감싸 `slides.fit_in_subprocess` 로 맞춘다. 내용은 운영에서 실제로 구운 「동네 카페 3분기 보고」(지어낸 가게 · 사람 이름 없음)의 장 조각.

    .venv/Scripts/python.exe scripts/build_whats_new_show.py [원본 장표 폴더]

결과: `ui/src/workspace/whatsNewShow.fixture.json` (다시 돌리면 덮어쓴다).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alture_jarvis import slides, slides_style  # noqa: E402

DEFAULT_SOURCE = Path(r"C:/RoboMetaFit/tools/alture-jarvis/outputs/slides/0246be17-b3e8-48dc-8398-bb56bd66bd04/동네 카페 3분기 보고")
OUT = ROOT / "ui" / "src" / "workspace" / "whatsNewShow.fixture.json"
TITLE = "동네 카페 3분기 보고"
ABOUT = "동네 카페의 3분기 매출 · 손님 · 키오스크 효과와 4분기 계획을 사장님께 보고"
#: 쇼에 쓰는 장(원본 번호) — 표지 · 큰 숫자 · 전후 비교. 장마다 손자리의 혼잣말(예시). 짓는 연출이 다 보이게 셋만.
PICKED = (
    (1, "표지는 결론부터 — 22% 늘었다는 것"),
    (2, "숫자 하나를 크게 세웠습니다"),
    (6, "키오스크 전 · 후를 맞대어"),
)
NAMES = ("가람", "나래", "박가람", "알튜어", "로보메타핏", "RoboMetaFit")


def fragment_of(saved: str) -> str:
    """구운 장 HTML 에서 <section> 조각만 — 옛 맞춤 크기 · 쪽 번호 · 장식은 뗀다(지금 결이 다시 붙인다)."""
    start, end = saved.find("<section"), saved.rfind("</section>")
    frag = saved[start:end + 10]
    frag = re.sub(r'<div class="pz-deco pz-mark".*?</div>', "", frag, flags=re.S)
    frag = re.sub(r'<div class="folio">.*?</div>', "", frag, flags=re.S)
    frag = re.sub(r'\sstyle="font-size:[^"]*"', "", frag)
    frag = re.sub(r"\sdata-sonjari-fit-\d+", "", frag)
    return re.sub(r'(<section\b[^>]*?)\s(?:active|is-active)(?=[\s"])', r"\1", frag)


def headline(frag: str) -> str:
    match = re.search(r"<h[12][^>]*>(.*?)</h[12]>", frag, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group(1))).strip() if match else ""


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    layouts = json.loads((source / "layouts.json").read_text(encoding="utf-8"))
    theme = "paper"
    payload = slides.guide_payload(None, about=ABOUT)
    picks = []
    for pick in payload["recommended"]:
        if pick["theme"] in slides_style.HIDDEN_THEMES:
            continue
        cover = slides_style.cover_preview(TITLE, str(pick["name"]), "3분기 매출 4,820만 원 — 2분기보다 22% 늘었습니다", theme=str(pick["theme"]))
        picks.append({"theme": pick["theme"], "name": pick["name"], "why": pick.get("why", ""),
                      "html": slides.clean_slide_html(slides_style.wrap_fragment(cover, str(pick["theme"]), title=TITLE)[0])})
    chosen = theme if any(p["theme"] == theme for p in picks) else (picks[0]["theme"] if picks else theme)
    built = []
    outline = []
    with tempfile.TemporaryDirectory() as tmp:
        for at, (number, note) in enumerate(PICKED, 1):
            frag = fragment_of((source / f"slide_{number:02d}.html").read_text(encoding="utf-8"))
            html, _ = slides_style.wrap_fragment(frag, chosen, title=TITLE, index=at, total=len(PICKED))
            path = Path(tmp) / f"slide_{at:02d}.html"
            path.write_text(slides.clean_slide_html(html), encoding="utf-8")
            slides.fit_in_subprocess(path)
            built.append({"html": path.read_text(encoding="utf-8"), "note": note})
            outline.append({"layout": str(layouts.get(str(number), {}).get("layout") or "split"), "claim": headline(frag)})
    # 쇼 ③(글꼴) 의 「전」 — 같은 표지를 **0.4.33 의 결 CSS(윈도우 글꼴)** 로 감싸 그 글꼴에 맞춘 것. 넘침을 지어내지 않는다.
    old_css = subprocess.run(["git", "show", f"f46df0d4^:tools/alture-jarvis/src/alture_jarvis/slide_themes/{chosen}.css"],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    base = (slides_style.THEME_DIR / "base.css").read_text(encoding="utf-8")
    real_theme_css = slides_style.theme_css
    slides_style.theme_css = lambda name: (chosen, base + chr(10) + old_css)  # type: ignore[assignment]
    try:
        frag = fragment_of((source / f"slide_{PICKED[0][0]:02d}.html").read_text(encoding="utf-8"))
        html, _ = slides_style.wrap_fragment(frag, chosen, title=TITLE, index=1, total=len(PICKED))
    finally:
        slides_style.theme_css = real_theme_css  # type: ignore[assignment]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "slide_01.html"
        path.write_text(slides.clean_slide_html(html), encoding="utf-8")
        slides.fit_in_subprocess(path)
        before = path.read_text(encoding="utf-8")
    assert "fonts.sonjari.invalid" not in before and "Pretendard" not in before, "「전」 표지에 새 글꼴이 섞였다"
    data = {"title": TITLE, "chosen": chosen, "say": "숫자가 주인공인 보고라 깔끔한 흰 종이 결을 권합니다",
            "picks": picks, "outline": outline, "slides": built, "font_before": before}
    text = json.dumps(data, ensure_ascii=False)
    leaked = [name for name in NAMES if name in text]
    if leaked:
        raise SystemExit(f"사람 · 회사 이름이 섞였다: {leaked}")
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT} · 결 {[p['theme'] for p in picks]} · 장 {len(built)} · {len(text.encode('utf-8')):,} 바이트")


if __name__ == "__main__":
    main()
