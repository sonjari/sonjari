"""장표 결(테마) · 배치 틀 (2026-10-25 4차).

## 왜 이렇게 됐나

1차: Akxan 결 예시 한 장 + 플레이북 → 대표 「좋다, 강한 느낌만 빼면」.
2차: 「AI 티 빼기」를 꾸밈 빼기로 잘못 옮겨 밋밋해짐 → 「더 별로다」.
3차: 예시 · 플레이북을 되살리고 결 여덟 중에 고르게 함 → 깔끔하지만 장마다 작은 글 · 카드 반복(시험대 L1b, 7장 모두 같은 어두운 톤).
4차(지금): **모델이 장을 처음부터 디자인하지 않는다.** 우리가 만든 결 CSS(`slide_themes/`)와 배치 틀 12개를 주고,
     모델은 배치를 고르고 칸에 내용만 채운다. CSS 는 굽기 전에 우리가 끼운다.
     까닭: 조사 세 갈래(A 슬라이드 스킬 · B 디자인 체계 · C 변환기)가 같은 답 — 「와우」는 큰 색 면 · 화면 높이 30~50% 글자 ·
     크기 다른 칸 같은 **구조**에서 나오고, 27B 에게는 「가까운 틀을 복사해 내용만 바꾸기」가 가장 잘 먹힌다
     (lewislulu/html-ppt-skill `SKILL.md:141` · zarazhangrui/beautiful-html-templates `AGENTS.md`, 둘 다 MIT).

5차(걷어 냄): SlideSpeak 테마 35개에서 **색만** 뽑아 우리 배치 12개에 입혔더니 「색만 다른 같은 장표」 — 대표 「템플릿이 별로」.
6차(지금): 원본 템플릿을 **HTML · CSS 째** 옮긴다(`slide_themes/templates/`, MIT · `scripts/port_slide_templates.py`).
     결마다 자기 장 틀(표지 · 의제 · 한 문장 · 숫자 · 차트 …)과 장식 · 등장 애니메이션을 그대로 가진다. 모델은 그 결의 장 틀을
     복사해 글만 한국어로 바꾼다. 손으로 쓴 결 중 원본보다 못한 셋(forest · emerald · cobalt)은 목록에서 숨긴다(예전 판은 그대로 읽힘).

옛 Akxan 결(`slide_styles/`)은 남겨 둔다 — 모델이 완성 HTML 을 넣으면(<!DOCTYPE html>) 예전처럼 그대로 받는다.
"""

from __future__ import annotations

import re
from pathlib import Path

THEME_DIR = Path(__file__).with_name("slide_themes")
STYLE_DIR = Path(__file__).with_name("slide_styles")

#: 결 이름 → (한국어 이름, 언제 고르나, 기본으로 색 면인 배치)
THEMES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "paper": ("흰 종이 · 파랑", "업무 보고 · 회의 · 계획 · 회사 소개 — 무난한 기본", ("section", "closing")),
    "forest": ("숲 · 분홍", "소개 · 회고 · 브랜드 이야기 · 교육 — 따뜻하게", ("cover", "statement", "bignum", "closing")),
    "emerald": ("에메랄드 · 남색", "전략 · 성과 · 제안 — 힘 있게", ("cover", "statement", "closing")),
    "cobalt": ("코발트 · 종이", "연구 · 조사 · 데이터 · 분석 — 차분하게", ("statement", "closing")),
    "ink": ("먹 · 주황(어두운 바탕)", "제품 · 기술 · 성능 · 개발 도구", ("statement",)),
}
DEFAULT_THEME = "paper"
#: 손으로 쓴 결(`slide_themes/<이름>.css`, 우리 배치 12개를 쓴다).
HAND_THEMES = frozenset(THEMES)
#: 목록 · 추천에서 숨기는 손 결 — 같은 원본 템플릿(editorial-forest · emerald-editorial · cobalt-grid)을 옮긴 결이 더 낫다.
HIDDEN_THEMES = frozenset({"forest", "emerald", "cobalt"})
TEMPLATE_DIR = THEME_DIR / "templates"
#: 우리가 직접 쓴 템플릿(IR 등 · `scripts/build_own_slide_templates.py`). 옮긴 템플릿 폴더는 다시 만들 때 통째로 지워져서 따로 둔다.
OWN_TEMPLATE_DIR = THEME_DIR / "own"


def _load_templates() -> dict[str, dict]:
    import json

    found: dict[str, dict] = {}
    for folder in (TEMPLATE_DIR, OWN_TEMPLATE_DIR):
        index = folder / "index.json"
        if index.exists():
            for slug, meta in json.loads(index.read_text(encoding="utf-8")).items():
                found[slug] = {**meta, "_dir": str(folder / slug)}
    return found


#: 템플릿 — slug → {name, when, uses, moods, formality, dark, layouts, (own, flow), _dir}
TEMPLATES: dict[str, dict] = _load_templates()


def template_dir(key: str) -> Path:
    return Path(TEMPLATES[key]["_dir"]) if key in TEMPLATES else TEMPLATE_DIR / key
for _slug, _meta in TEMPLATES.items():
    THEMES.setdefault(_slug, (_meta["name"], _meta["when"], ()))


def is_template(key: str | None) -> bool:
    return bool(key) and key in TEMPLATES


_SECTIONS_CACHE: dict[str, list[dict]] = {}


def template_sections(key: str) -> list[dict]:
    """옮긴 템플릿의 장 틀 — [{class, classes, label, html}]."""
    if key not in _SECTIONS_CACHE:
        import json

        _SECTIONS_CACHE[key] = json.loads((template_dir(key) / "sections.json").read_text(encoding="utf-8"))
    return _SECTIONS_CACHE[key]


_LAYOUT_ID_CACHE: dict[str, list[str]] = {}


def template_layout_ids(key: str) -> list[str]:
    """템플릿 장마다 그 장을 가르는 이름 — 장 클래스 중 가장 드문 것(2026-10-25).

    ★ 옮긴 템플릿 여럿은 첫 클래스가 전부 `slide` 라 장 틀 이름이 하나뿐이었다 — 이야기판 카드가 모든 장을 「slide」로 보였고,
      「앞 장과 같은 배치」 알림도 늘 걸렸다. `slide s2` · `slide dark slide--cover` 처럼 장마다 다른 클래스가 따로 있다.
    """
    if key not in _LAYOUT_ID_CACHE:
        from collections import Counter

        sections = template_sections(key)
        sets = [section["classes"].split() for section in sections]
        count = Counter(name for names in sets for name in set(names))
        ids = []
        for names, section in zip(sets, sections):
            own = [name for name in names if count[name] < len(sections) and name not in {"active", "is-active"}]
            ids.append(min(own, key=lambda name: (count[name], "-" not in name, names.index(name))) if own else section["class"])
        _LAYOUT_ID_CACHE[key] = ids
    return _LAYOUT_ID_CACHE[key]


def template_texts(key: str) -> set[str]:
    """템플릿 장 틀에 들어 있던 글 토막(10자 이상) — 모델이 바꾸지 않고 남긴 글을 찾는 데 쓴다."""
    found: set[str] = set()
    own = bool(TEMPLATES.get(key, {}).get("own"))
    for section in template_sections(key):
        body = re.sub(r"<style\b[^>]*>.*?</style\s*>", " ", section["html"], flags=re.S | re.I)
        for part in re.split(r"<[^>]+>", body):
            text = re.sub(r"\s+", " ", part).strip()
            if len(text) >= 10 and re.search(r"[A-Za-z]{3}", text):
                found.add(text)
            # 우리 템플릿의 자리 표시는 한국어다 — 안내 문장(12자 이상)과 「○○」 자리를 남기면 돌려보낸다.
            elif own and (len(text) >= 12 or "○" in text):
                found.add(text)
    return found

#: 배치 이름 → (언제 쓰나, 뼈대). 뼈대의 글은 자리 표시다 — 그대로 두지 않는다.
LAYOUTS: dict[str, tuple[str, str]] = {
    "cover": ("첫 장 표지", """<section class="cover">
  <p class="kicker">짧은 꼬리말(누구에게 · 언제)</p>
  <h1>발표 제목 — 짧게</h1>
  <p class="lede">무엇을 말하는 발표인지 한두 문장.</p>
  <div class="meta"><div><b>값</b><span>이름</span></div><div><b>값</b><span>이름</span></div></div>
</section>"""),
    "section": ("장 넘김 — 큰 번호나 두세 글자 낱말 하나 + 다음 이야기 제목", """<section class="section">
  <div class="big">2</div>
  <div class="side"><p class="kicker">둘째 이야기</p><h2>다음 이야기의 제목</h2><p class="lede">한 문장 덧말.</p></div>
</section>"""),
    "statement": ("한 문장을 크게 — 주장 · 핵심 메시지 · 인용", """<section class="statement">
  <p class="kicker">한 문장으로</p>
  <blockquote>이 발표에서 기억할 한 문장을 크게. <em class="hi">강조할 말</em>은 하나만.</blockquote>
  <p class="by">덧말이나 출처</p>
</section>"""),
    "bignum": ("주인공 숫자 하나(전후 비교면 was 에 옛 값)", """<section class="bignum">
  <p class="kicker">무엇의 숫자인가</p>
  <h2>숫자가 말하는 주장을 한 문장으로</h2>
  <div class="hero"><p class="was">30.6초</p><p class="num">1.08<small>초</small></p><p class="desc">이 숫자의 뜻을 한두 문장. 조건 · 기준도.</p></div>
</section>"""),
    "stats": ("숫자 2~4개 나란히 — 가장 중요한 칸에 on", """<section class="stats">
  <p class="kicker">한눈에</p>
  <h2>숫자 묶음이 말하는 주장</h2>
  <div class="row">
    <div class="stat on"><p class="v">128K</p><p class="k">이름</p><p class="d">한 줄 설명</p></div>
    <div class="stat"><p class="v">27B</p><p class="k">이름</p><p class="d">한 줄 설명</p></div>
    <div class="stat"><p class="v">0원</p><p class="k">이름</p><p class="d">한 줄 설명</p></div>
  </div>
</section>"""),
    "compare": ("둘 맞대기 — 전/후 · 우리/남 · 안/밖. 양쪽 항목 수를 맞추고 이기는 쪽에 on", """<section class="compare">
  <p class="kicker">무엇과 무엇</p>
  <h2>비교가 말하는 주장</h2>
  <div class="cols">
    <div class="col"><h3>왼쪽 이름</h3><ul><li>항목</li><li>항목</li><li>항목</li></ul></div>
    <div class="col on"><h3>오른쪽 이름</h3><ul><li>항목</li><li>항목</li><li>항목</li></ul></div>
  </div>
</section>"""),
    "steps": ("순서 3~5단계(번호는 저절로 붙는다 — 쓰지 않는다). 핵심 단계에 on", """<section class="steps">
  <p class="kicker">어떻게 하나</p>
  <h2>흐름이 말하는 주장</h2>
  <ol>
    <li><b>단계 이름</b><span>한두 문장 설명</span></li>
    <li class="on"><b>단계 이름</b><span>한두 문장 설명</span></li>
    <li><b>단계 이름</b><span>한두 문장 설명</span></li>
  </ol>
</section>"""),
    "bars": ("막대 비교 2~6개. --v 는 가장 큰 값을 100% 로 둔 비율. 주인공 막대에 on", """<section class="bars">
  <p class="kicker">비교</p>
  <h2>막대가 증명하는 결론</h2>
  <div class="chart">
    <div class="bar" style="--v:100%"><span class="name">이름<small>덧말</small></span><i></i><span class="val">$40.70</span></div>
    <div class="bar" style="--v:26%"><span class="name">이름</span><i></i><span class="val">$10.70</span></div>
    <div class="bar on" style="--v:2%"><span class="name">이름</span><i></i><span class="val">값</span></div>
  </div>
  <p class="note">기준 · 출처 한 줄</p>
</section>"""),
    "table": ("표 — 3~5열 · 3~7행. 강조할 행에 on", """<section class="table">
  <p class="kicker">자세히</p>
  <h2>표가 말하는 주장</h2>
  <table><thead><tr><th>항목</th><th>열</th><th>열</th></tr></thead>
  <tbody><tr><td>행</td><td>값</td><td>값</td></tr><tr class="on"><td>행</td><td>값</td><td>값</td></tr></tbody></table>
  <p class="note">기준 · 출처 한 줄</p>
</section>"""),
    "split": ("반반 — 왼쪽 색 면에 제목, 오른쪽에 설명 2~4줄", """<section class="split">
  <div class="lead"><p class="kicker">꼬리말</p><h2>왼쪽에 크게 놓을 제목</h2></div>
  <div class="body"><ul>
    <li><b>요점 이름</b>한두 문장 설명</li>
    <li><b>요점 이름</b>한두 문장 설명</li>
    <li><b>요점 이름</b>한두 문장 설명</li>
  </ul></div>
</section>"""),
    "tiles": ("크기 다른 칸 3~5개 — 첫 칸이 가장 크다(가장 중요한 것을 첫 칸에)", """<section class="tiles">
  <p class="kicker">묶음</p>
  <h2>칸들이 말하는 주장</h2>
  <div class="grid">
    <div class="tile"><b>가장 중요한 것</b><span>한 줄 설명</span></div>
    <div class="tile"><b>이름</b><span>한 줄</span></div>
    <div class="tile"><b>이름</b><span>한 줄</span></div>
    <div class="tile"><b>이름</b><span>한 줄</span></div>
    <div class="tile"><b>이름</b><span>한 줄</span></div>
  </div>
</section>"""),
    "closing": ("마지막 장 — 「감사합니다」 대신 다음 걸음 · 요청 한 문장", """<section class="closing">
  <p class="kicker">다음 걸음</p>
  <h2>듣는 사람이 할 일 한 문장</h2>
  <p class="lede">어디서 · 어떻게 한두 문장.</p>
  <div class="meta"><div><b>값</b><span>이름</span></div><div><b>값</b><span>이름</span></div></div>
</section>"""),
}

_SECTION_TAG = re.compile(r"<section\b([^>]*)>", re.I)
_CLASS = re.compile(r"""class\s*=\s*["']([^"']*)["']""", re.I)


def theme_menu() -> str:
    return "\n".join(f"- {key}: {label} — {when}" for key, (label, when, _) in THEMES.items() if key not in HIDDEN_THEMES)


def layout_menu(theme: str | None = None, only: tuple[str, ...] | None = None) -> str:
    """고른 결의 장 틀. 옮긴 템플릿이면 그 템플릿의 장들, 손 결이면 우리 배치 12개. `only` 면 그 장 이름만(부품 결의 표지 · 마무리)."""
    if is_template(theme):
        return "\n\n".join(f"### {name} — {sec['label'] or name}\n{sec['html']}"
                             for name, sec in zip(template_layout_ids(theme), template_sections(theme))
                             if only is None or name in only)
    return "\n\n".join(f"### {name} — {when}\n{skeleton}" for name, (when, skeleton) in LAYOUTS.items()
                       if only is None or name in only)


def theme_css(name: str | None) -> tuple[str, str]:
    """(실제로 고른 결, 결 CSS). 손 결은 글꼴 선언 + base + 결 파일, 옮긴 템플릿은 그 템플릿 CSS. 모르는 이름이면 기본 결."""
    key = name if name in THEMES else DEFAULT_THEME
    if is_template(key):
        return key, (template_dir(key) / "theme.css").read_text(encoding="utf-8")
    base = (THEME_DIR / "base.css").read_text(encoding="utf-8")
    return key, font_face_css() + "\n" + base + "\n" + (THEME_DIR / f"{key}.css").read_text(encoding="utf-8")


# ── 앱에 든 오픈 글꼴 (2026-10-26) ──────────────────────────────────────────────────────────
#
# 손 결 다섯이 쓰는 한글 글꼴(전부 SIL OFL 1.1)을 `slide_themes/fonts/` 에 넣었다 — 목록 · 출처 · 바이트 · 해시는 `fonts.json`.
# 만든 곳이 배포한 파일을 그대로 넣는다(예약 이름이 있는 글꼴을 우리가 줄이거나 바꾸면 이름을 바꿔야 한다 · OFL 3조).
# 예약 이름이 없는 고운 둘만 ttf(23.8MB) → woff2 로 꼴을 바꿨다(10-26 · fonts.json 의 converted_from). PPTX 에 심을 땐 쓴 글자만(`pptx_fonts`).
#
# 장 HTML 은 `set_content` 로 그려서(주소 없는 빈 문서) 상대 경로 · 로컬 파일 주소가 안 먹는다. 그래서 글꼴 주소는
# 아무 데도 없는 주소(`FONT_ORIGIN`, .invalid 는 인터넷에 없는 이름)로 적고, 그리는 브라우저가 그 요청만 이 폴더의 파일로
# 돌려준다(`slides._serve_fonts`). 밖으로 나가는 요청은 없다. 이 주소를 모르는 곳(화면 미리보기 칸)에서는 글꼴 목록의
# 다음 글꼴(맑은 고딕 · Segoe UI 등 윈도우 기본)로 그린다 — 화면 미리보기 칸은 이 주소를 본체 `/v1/slides/fonts/…` 로 바꿔 받는다(ui `slideFonts.ts`).
FONT_DIR = THEME_DIR / "fonts"
FONT_ORIGIN = "https://fonts.sonjari.invalid"
_FONT_TABLE: dict | None = None


def bundled_fonts() -> list[dict]:
    """`fonts.json` 의 글꼴 묶음 목록 — [{family, faces: [{file, weight, …}], license, …}]. 파일이 없으면 빈 목록."""
    global _FONT_TABLE
    if _FONT_TABLE is None:
        import json

        path = FONT_DIR / "fonts.json"
        _FONT_TABLE = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"families": []}
    return list(_FONT_TABLE.get("families") or [])


def bundled_family_names() -> frozenset[str]:
    """앱에 든 글꼴 이름(소문자) — PPTX 글 상자는 이 이름을 쓰지 않는다(받는 PC 에 없다 · `slides.font_pair`)."""
    return frozenset(str(fam["family"]).lower() for fam in bundled_fonts())


def font_face_css() -> str:
    """앱에 든 글꼴의 @font-face. 실제로 쓰는 결(글꼴 목록에 그 이름이 있는 결)에서만 브라우저가 파일을 부른다."""
    rules = []
    for fam in bundled_fonts():
        for face in fam.get("faces") or []:
            file = str(face["file"])
            kind = "woff2" if file.endswith(".woff2") else "truetype"
            rules.append(f"@font-face{{font-family:'{fam['family']}';src:url('{FONT_ORIGIN}/{file}') format('{kind}');"
                         f"font-weight:{int(face['weight'])};font-style:normal;font-display:block}}")
    return "\n".join(rules)


def font_file(url: str) -> Path | None:
    """`FONT_ORIGIN/<파일>` 주소 → 이 폴더의 글꼴 파일. 목록(`fonts.json`)에 있는 파일만 — 그 밖은 None."""
    prefix = FONT_ORIGIN + "/"
    if not str(url).startswith(prefix):
        return None
    rel = str(url)[len(prefix):].split("?", 1)[0].split("#", 1)[0]
    listed = {str(face["file"]) for fam in bundled_fonts() for face in fam.get("faces") or []}
    if rel not in listed:
        return None
    path = (FONT_DIR / rel).resolve()
    return path if path.is_file() and FONT_DIR.resolve() in path.parents else None


def section_layout(fragment: str, theme: str | None = None) -> tuple[str | None, list[str]]:
    """조각의 첫 <section> 에서 (배치 이름, 클래스 목록). 옮긴 템플릿이면 그 템플릿의 장 이름으로 본다."""
    match = _SECTION_TAG.search(fragment or "")
    if not match:
        return None, []
    classes = (_CLASS.search(match.group(1)) or [None, ""])[1].split()
    if is_template(theme):
        ids = template_layout_ids(theme)
        # 장 이름이 여럿 맞으면(예: `slide dark slide--cover`) 가장 드문 것 — 장을 가르는 이름.
        hits = [name for name in classes if name in ids]
        layout = min(hits, key=lambda name: (ids.count(name), classes.index(name))) if hits else None
        return layout, classes
    layout = next((name for name in classes if name in LAYOUTS), None)
    return layout, classes


def unescape_fragment(html: str) -> str:
    r"""모델이 html 을 한 번 더 문자열로 감싸 보낸 것(class=\"cover\" · 글자 그대로의 \n)을 푼다 — 10-25 시험대 N2."""
    text = str(html or "")
    if '\\"' in text and re.search(r'class=\\"', text):
        text = text.replace('\\"', '"').replace("\\n", "\n").replace("\\t", " ").replace("\\/", "/")
    return text


def is_fragment(html: str) -> bool:
    """완성 문서(<!DOCTYPE html> · <html>)가 아니라 <section> 조각인가."""
    head = (html or "").lstrip()[:400].lower()
    return "<section" in (html or "").lower() and not head.startswith("<!doctype") and "<html" not in head


#: 흰 장이 이어질 때 색 면으로 뒤집어도 보기 좋은 배치(리듬 — B 조사 「밝은 장 2~3장마다 색 면 한 장」).
FLIPPABLE = ("statement", "bignum", "stats", "bars", "steps")


def wrap_fragment(fragment: str, theme: str | None, *, title: str = "", index: int = 0, total: int = 0,
                  light_run: int = 0) -> tuple[str, str | None]:
    """<section> 조각 → 결 CSS 를 끼운 자기완결 HTML. (html, 배치 이름).

    - 결이 기본으로 색 면으로 두는 배치면 `field` 를 붙인다. 모델이 `alt` 를 붙이면 뒤집는다(면 ↔ 종이).
    - 쪽 표시(제목 · n / 전체)는 우리가 넣는다 — 모델이 쓰지 않게(꼬리말 반복은 AI 티).
    """
    key, css = theme_css(theme)
    if "pz-slide" in fragment[:400]:
        # 부품 장(2026-10-25 묶음) — 결 CSS 뒤에 공통 뼈대 · 묶음 문법 · 결 값을 끼운다. 쪽 표시 · 색 면 뒤집기는 하지 않는다.
        from .slide_parts import parts_css

        extra = parts_css(key)
        if "pz-frame" in fragment[:400]:
            # 표지 · 마무리 부품(2026-10-26) — 혼자 서는 frames.css + 결 값. IR 처럼 부품 묶음 CSS 가 없는 결도 이 길로 간다.
            from .slide_frames import frame_css

            extra = frame_css(key)
        if extra:
            body = fragment
            match = _SECTION_TAG.search(body)
            if match and is_template(key):
                layout, classes = section_layout(fragment, key)
                new_classes = classes + [name for name in ("active", "is-active") if name not in classes]
                attrs = _CLASS.sub("", match.group(1), count=1).strip()
                body = body[: match.start()] + f'<section class="{" ".join(new_classes)}"{(" " + attrs) if attrs else ""}>' + body[match.end():]
            if "pz-frame" not in fragment[:400] and "pz-mark" not in body:
                # 본문 부품 장의 무늬 한 점(10-26 대표 14:20) — 쪽 머리 오른쪽 모서리. 글에 닿으면 재기가 지운다(글이 먼저).
                from .slide_frames import body_mark

                mark = body_mark(key, index)
                opened = _SECTION_TAG.search(body)
                if mark and opened:
                    body = body[: opened.end()] + mark + body[opened.end():]
            html = ("<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
                    f"<style data-sonjari-theme=\"{key}\">{css}</style><style data-sonjari-parts>{extra}</style></head><body>{body}</body></html>")
            return html, "parts"
    if is_template(key):
        return _wrap_template(fragment, key, css)
    layout, classes = section_layout(fragment)
    fields = THEMES[key][2]
    want_field = (layout in fields) != ("alt" in classes)
    if layout in {"section", "split"}:  # 장 안에 이미 색 면 반쪽이 있다 — 장 전체를 면으로 뒤집지 않는다
        want_field = False
    # 앞에 흰 장이 둘 이상 이어졌으면, 모델이 따로 정하지 않은(alt 없는) 뒤집을 만한 배치를 색 면으로.
    if light_run >= 2 and not want_field and "alt" not in classes and layout in FLIPPABLE and index != total:
        want_field = True
    body = fragment
    match = _SECTION_TAG.search(body)
    if match:
        new_classes = [name for name in classes if name not in {"field", "alt"}] + (["field"] if want_field else [])
        attrs = match.group(1)
        attrs = _CLASS.sub("", attrs, count=1).strip()
        tag = f'<section class="{" ".join(new_classes)}"{(" " + attrs) if attrs else ""}>'
        body = body[: match.start()] + tag + body[match.end():]
        if total and layout != "cover":
            folio = f'<div class="folio"><span>{_escape(title)}</span><span>{index} / {total}</span></div>'
            close = body.lower().rfind("</section>")
            if close >= 0:
                body = body[:close] + folio + body[close:]
    html = ("<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            f"<style data-sonjari-theme=\"{key}\">{css}</style></head><body>{body}</body></html>")
    return html, layout


def _wrap_template(fragment: str, key: str, css: str) -> tuple[str, str | None]:
    """옮긴 템플릿 — 원본은 「보이는 장」에만 active · is-active 를 달아 보인다. 장 하나가 한 페이지이니 늘 단다."""
    layout, classes = section_layout(fragment, key)
    body = fragment
    match = _SECTION_TAG.search(body)
    if match:
        new_classes = classes + [name for name in ("active", "is-active") if name not in classes]
        attrs = _CLASS.sub("", match.group(1), count=1).strip()
        tag = f'<section class="{" ".join(new_classes)}"{(" " + attrs) if attrs else ""}>'
        body = body[: match.start()] + tag + body[match.end():]
    html = ("<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
            f"<style data-sonjari-theme=\"{key}\">{css}</style></head><body>{body}</body></html>")
    return html, layout


def has_field(html: str) -> bool:
    """색 면이 있는 장인가 — 장 전체가 면이거나(field) 반쪽이 면인 배치(section · split)."""
    layout, classes = section_layout(html)
    return "field" in classes or layout in {"section", "split"}


def cover_preview(title: str, label: str, lede: str = "", theme: str | None = None) -> str:
    """큐레이션 화면에 띄울 표지 조각 — 발표 제목 + 결 이름(+ 무슨 발표인지).

    부품 결(2026-10-26 부터 모든 결)은 **실제로 만들 표지 부품**으로 그린다 — 「이 결로 만들면 이렇게 된다」가 실제 장과 같게.
    예전엔 템플릿 표지에 제목만 넣어 보였는데, 실제 판은 그 표지를 모델이 베껴 다르게 나왔다.
    """
    from . import slide_frames, slide_parts

    if slide_parts.supports(theme):
        spec = {"frame": "cover", "kicker": label, "title": (title or "발표 제목")[:60]}
        if lede:
            spec["sub"] = lede[:120]
        try:
            return slide_frames.build_frame(spec, theme)[0]
        except slide_parts.PartsError:
            pass
    if is_template(theme):
        cover = template_sections(theme)[0]["html"]
        text = _escape(title or "발표 제목")
        # 제목 자리: <h1>, 없으면 이름에 title · display · big · headline · hero 가 든 첫 칸(표지 구조가 템플릿마다 다르다).
        heading = re.compile(r"(<h1\b[^>]*>)(.*?)(</h1>)", re.S)
        if heading.search(cover):
            return heading.sub(lambda m: m.group(1) + text + m.group(3), cover, count=1)
        slot = re.compile(r"""(<(div|p|span)\b[^>]*class="[^"]*\b(?:title|display|big|headline|hero|b1)[\w-]*\b[^"]*"[^>]*>)(.*?)(</\2>)""", re.S)
        return slot.sub(lambda m: m.group(1) + text + m.group(4), cover, count=1)
    lede_html = f'<p class="lede">{_escape(lede[:120])}</p>' if lede else ""
    return (f'<section class="cover"><p class="kicker">{_escape(label)}</p><h1>{_escape(title or "발표 제목")}</h1>'
            f"{lede_html}</section>")


def _escape(text: str) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── 옛 Akxan 결(완성 HTML 을 넣는 길) ───────────────────────────────────────────────
STYLES: dict[str, tuple[str, str]] = {
    "blue_white": ("파랑 · 흰 바탕", "업무 보고 · 회사 소개 · 계획"),
    "dark_tech": ("어두운 기술", "제품 · 기술 · 개발 도구 · 성능 숫자"),
    "botanic_forest": ("숲 · 이야기", "여행 · 자연 · 브랜드 이야기 · 감성"),
    "bauhaus_block": ("바우하우스 도형", "강의 · 교육 · 디자인 · 원리 설명"),
    "medical_pulse": ("맑은 데이터", "의료 · 데이터 · 대시보드 · 지표"),
    "earth_concrete": ("콘크리트 · 공간", "건축 · 공간 · 포트폴리오 · 프로젝트 기록"),
    "mocha_editorial": ("에디토리얼", "리서치 · 보고서 · 에세이 · 긴 글"),
    "noir_film": ("흑백 필름", "행사 · 사진 · 영상 · 무대 발표"),
}
DEFAULT_STYLE = "blue_white"


def style_menu() -> str:
    return "\n".join(f"- {key}: {label} — {when}" for key, (label, when) in STYLES.items())


def style_html(name: str | None) -> tuple[str, str]:
    key = name if name in STYLES else DEFAULT_STYLE
    return key, (STYLE_DIR / f"{key}.html").read_text(encoding="utf-8")


def playbook() -> str:
    return (STYLE_DIR / "page-html-playbook.md").read_text(encoding="utf-8")
