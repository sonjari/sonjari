"""표지 · 마무리 부품 + 장식 부품 + 장표 유형 (2026-10-26 대표 「템플릿에 종속되면 큰일난다」).

## 왜

대표: 「템플릿은 참고만 하고, 결(느낌)과 유형을 고르면 손자리가 그 느낌대로 **완전히 새로** 짓는다. 글자 · 글 간격 · 줄 · 도형까지 전부.」
짓는 손은 모델이 아니라 **코드**다. 모델은 내용과 「어떤 부품」만 고른다.

    모델 자유 HTML            넘침 · 186~316초 (10-25 3차)
    템플릿 통째 베끼기        장식까지 베껴 daisy 표지 한 장 약 8,000토큰 · 글 겹침 (10-26 c81a10dd 표지)
    부품 조립(본문)           12판 12판 완성 (10-26 결과.md)

본문은 이미 부품이었고, 표지 · 마무리만 템플릿 장을 통째로 썼다. 10-26 13:40 실제 판(cobalt-grid) 표지에서 짧은 꼬리말 칸에 긴 문장이
들어가 절대 위치로 놓인 작은 바닥 글과 **겹쳤다** — 넘침 검사는 「장 밖으로」만 봐서 못 잡았다.

## 나눔

    모델     표지 · 마무리 조립표: {"frame":"cover","kicker","title","sub","meta":[[이름,값]],"note","figure"}
    이 모듈  글은 위에서 아래로 흐르는 한 줄기(머리 말 → 제목 → 부제 → 바닥 줄)에만 놓는다 — 절대 위치 글이 없어 겹칠 수 없다.
             제목 크기는 글 길이와 짜임 너비로 코드가 정한다. 짜임(arrangement)과 장식(deco)은 결 값(themes.json)에서 고른다.
             장식은 결 값의 색으로 코드가 그린 도형(SVG)이고, 글 줄기가 비켜 가는 자리에만 놓인다. 모델은 장식을 보지도 쓰지도 않는다.
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import math
import re
from pathlib import Path
from typing import Any

FRAMES = ("cover", "closing")
_PARTS_DIR = Path(__file__).resolve().parent / "slide_themes" / "parts"
#: 결 값 중 CSS 변수가 아닌 것(짜임 · 장식 · 묶음).
_NOT_TOKENS = {"family", "arrange", "deco"}
#: 짜임별 글 줄기 너비(px) — 제목 크기를 고를 때 쓴다.
_WIDTH = {"left": 1136, "bottom": 1136, "center": 1016, "note": 940, "side": 738, "panel": 736}
_TITLE_MAX = 60
_SUB_MAX = 160
_KICKER_MAX = 28
_META_MAX = 4

FRAME_GUIDE = (
    "표지 · 마무리도 부품이다 — html(틀)을 쓰지 않고 parts 에 조립표를 넣는다. 글자 크기 · 간격 · 줄 · 장식(도형)은 손자리가 결에 맞게 그린다:\n"
    '1번 장: {"frame":"cover","kicker":"누구에게 · 무엇(2~16자)","title":"발표 제목(짧게)","sub":"무엇을 말하는 발표인지 한두 문장",'
    '"meta":[["발표","이름 · 회사"],["날짜","2026.10.26"]],"note":"출처 · 기준일(선택)"}\n'
    '마지막 장: {"frame":"closing","kicker":"다음 걸음","title":"듣는 사람이 할 일 한 문장","sub":"어디서 · 어떻게(선택)",'
    '"meta":[["연락","메일 · 전화"]]}\n'
    '- 숫자 하나를 크게 보이려면 figure: {"label":"요청 금액","value":"12억 원","note":"시드 · 18개월 운영"}(선택).\n'
    "- 제목 40자 · 부제 160자 · 머리 말 28자 · meta 4쌍까지. 머리 말 · meta 에는 짧은 말만 — 긴 문장은 sub 에."
)


# ── 결 값 ────────────────────────────────────────────────────────────────────────────────
def _raw() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads((_PARTS_DIR / "themes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if name.startswith("_") and name != "_own" or not isinstance(value, dict):
            continue
        base = raw.get(str(value.get("_from") or ""), {}) if value.get("_from") else {}
        out[name] = {**base, **{k: v for k, v in value.items() if k != "_from"}}
    return out


THEME_VALUES: dict[str, dict[str, Any]] = _raw()


def style_of(theme: str | None) -> tuple[str, list[str]]:
    """결의 (짜임, 장식 목록). 모르는 결이면 왼쪽 정렬 · 장식 없음."""
    values = THEME_VALUES.get(str(theme or "")) or {}
    arrange = str(values.get("arrange") or "left")
    if arrange not in _WIDTH:
        arrange = "left"
    decos = [name for name in str(values.get("deco") or "").split() if name in DECOS]
    return arrange, decos


def frame_tokens(theme: str | None) -> dict[str, str]:
    from .slide_parts import _TOKEN_DEFAULTS, _TOKEN_FALLBACK

    values = {**_TOKEN_DEFAULTS, **{k: str(v) for k, v in (THEME_VALUES.get(str(theme or "")) or {}).items() if k not in _NOT_TOKENS}}
    for name, source in _TOKEN_FALLBACK:
        values.setdefault(name, values.get(source, ""))
    return values


def frame_css(theme: str | None) -> str:
    """표지 · 마무리 장에 끼울 CSS — 결 값 + frames.css(혼자 선다 · IR 처럼 부품 묶음이 없는 결도)."""
    tokens = frame_tokens(theme)
    block = ":root{" + "".join(f"--pz-{key.replace('_', '-')}:{value};" for key, value in tokens.items()) + "}"
    return block + "\n" + (_PARTS_DIR / "frames.css").read_text(encoding="utf-8")


# ── 조립표 ────────────────────────────────────────────────────────────────────────────────
def is_frame(spec: Any, index: int = 0, total: int = 0) -> bool:
    """표지 · 마무리 조립표인가 — frame 이름이 있거나, 칸 목록(cols) 없이 제목만 있거나, 1번 · 마지막 장인데 칸 목록이 없거나."""
    if not isinstance(spec, dict):
        return False
    kind = str(spec.get("frame") or spec.get("kind") or "").strip().lower()
    if kind in FRAMES:
        return True
    if spec.get("cols"):
        return False
    edge = bool(total) and index in (1, total)
    return (bool(spec.get("title")) and not spec.get("head")) or (edge and bool(spec.get("title") or spec.get("head")))


def _weighted_len(text: str) -> float:
    plain = re.sub(r"<[^>]+>", "", str(text or ""))
    total = 0.0
    for ch in plain:
        if ch.isspace():
            total += 0.3
        elif ord(ch) < 0x2E80:
            total += 0.58
        else:
            total += 1.0
    return total


def title_px(title: str, arrange: str, budget: int = 380) -> int:
    """제목 크기 — 줄 너비에 몇 줄로 들어가는지와 높이 예산(기본 380px)으로 고른다. 그래도 넘치면 재기(_FIT_JS)가 줄인다."""
    width = _WIDTH.get(arrange, 1136)
    n = max(_weighted_len(title), 1.0)
    for size in (128, 112, 100, 88, 78, 68, 60, 52, 46, 40):
        # 낱말 단위로 줄을 바꾸니(keep-all) 한 줄을 다 못 채운다 — 15% 넉넉히 센다(10-26 IR 마무리가 3줄 셈 · 4줄로 그려졌다).
        lines = math.ceil(n * size * 1.17 / width)
        if lines <= 3 and lines * size * 1.14 <= budget:
            return size
    return 40


def _title_budget(spec: dict[str, Any], arrange: str, decos: list[str], sub_px: int, figure_in_main: bool) -> int:
    """제목에 쓸 수 있는 높이(px) — 장 높이에서 위아래 여백 · 머리 말 · 부제 · 큰 숫자 · 바닥 줄 높이를 어림해 뺀다(frames.css 의 값).
    10-26 첫 판은 고정 값을 빼서 아래 짜임(bottom) + 숫자가 있는 장의 제목이 넘쳐 재기가 반 크기로 줄였다."""
    top = {"bottom": 170}.get(arrange, 56) + (20 if "frame" in decos else 0)
    avail = 720 - top - 40
    kicker = 43 if spec.get("kicker") else 0
    sub = str(spec.get("sub") or "")
    width = min(820, _WIDTH.get(arrange, 1136))
    sub_h = (26 + math.ceil(_weighted_len(sub) * sub_px * 1.05 / width) * sub_px * 1.6) if sub else 0
    figure = 150 if figure_in_main else 0
    foot = 84 if (spec.get("meta") or spec.get("note")) and arrange != "panel" else 60
    if arrange == "bottom" and isinstance(spec.get("figure"), dict):
        foot = 140  # 큰 숫자가 바닥 줄로 내려온다
    return int(max(110, min(380, avail - kicker - sub_h - figure - foot - 24)))


def _pairs(value: Any) -> list[list[str]]:
    from .slide_parts import _BODY_KEYS, _NAME_KEYS, _plain

    out: list[list[str]] = []
    if isinstance(value, dict):
        value = [[k, v] for k, v in value.items()]
    for item in value if isinstance(value, list) else []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append([_plain(item[0]), _plain(item[1])])
        elif isinstance(item, dict):
            name = next((str(item[k]) for k in _NAME_KEYS if item.get(k)), "")
            body = next((str(item[k]) for k in _BODY_KEYS if item.get(k)), "")
            if name or body:
                out.append([name, body])
        elif isinstance(item, str) and item.strip():
            out.append(["", item])
    return out


def repair_frame(spec: dict[str, Any], index: int = 0, total: int = 0) -> list[str]:
    """정답이 하나인 모양 잘못은 코드가 고친다(사다리 0~1단) — 고친 것을 돌려준다."""
    fixed: list[str] = []
    kind = str(spec.get("frame") or spec.get("kind") or "").strip().lower()
    if kind not in FRAMES:
        kind = "closing" if total and index == total and index != 1 else "cover"
        fixed.append(f"표지 · 마무리 이름이 없어 자리로 「{kind}」를 붙였다")
    spec["frame"] = kind
    for wrong, right in (("head", "title"), ("lede", "sub"), ("subtitle", "sub"), ("label", "kicker"), ("source", "note"), ("date", "note")):
        if spec.get(wrong) and not spec.get(right):
            value = spec.pop(wrong)
            spec[right] = " ".join(map(str, value)) if isinstance(value, list) else value
            fixed.append(f"{wrong} → {right}")
    kicker = str(spec.get("kicker") or "")
    if len(kicker) > _KICKER_MAX and not spec.get("sub"):
        spec["sub"], spec["kicker"] = kicker, ""
        fixed.append("머리 말이 길어 부제로 옮겼다")
    if "meta" in spec:
        pairs = _pairs(spec.get("meta"))
        if pairs != spec.get("meta"):
            fixed.append("meta 를 「이름, 값」 짝으로 폈다")
        if len(pairs) > _META_MAX:
            fixed.append(f"meta {len(pairs)}쌍 중 앞 {_META_MAX}쌍만 남겼다")
            pairs = pairs[:_META_MAX]
        spec["meta"] = pairs
    return fixed


def validate_frame(spec: dict[str, Any]) -> list[str]:
    from .slide_parts import _DIRECTOR, _PLACEHOLDER, _strings

    problems: list[str] = []
    title = re.sub(r"<[^>]+>", "", str(spec.get("title") or "")).strip()
    if not title:
        problems.append("title(제목)이 비었다")
    if len(title) > _TITLE_MAX:
        problems.append(f"제목 {len(title)}자 — {_TITLE_MAX}자까지(긴 말은 sub 로)")
    if len(str(spec.get("sub") or "")) > _SUB_MAX:
        problems.append(f"부제 {len(str(spec.get('sub')))}자 — {_SUB_MAX}자까지")
    if len(str(spec.get("kicker") or "")) > _KICKER_MAX:
        problems.append(f"머리 말 {len(str(spec.get('kicker')))}자 — {_KICKER_MAX}자까지(긴 말은 sub 로)")
    for name, value in spec.get("meta") or []:
        if len(str(value)) > 60:
            problems.append(f"meta 「{name}」 값 {len(str(value))}자 — 60자까지(긴 말은 sub 로)")
            break
    figure = spec.get("figure")
    if figure not in (None, "", {}) and not (isinstance(figure, dict) and str(figure.get("value") or "").strip()):
        problems.append("figure 는 {label, value, note} — value 가 비었다")
    texts = _strings(spec)
    left = sorted({m.group(0) for text in texts for m in _PLACEHOLDER.finditer(text)})
    if left:
        problems.append("자리 표시가 남았다(" + " · ".join(left) + ") — 이 발표의 실제 값으로")
    leaked = sorted({m.group(0) for text in texts for m in _DIRECTOR.finditer(text)})
    if leaked:
        problems.append("연출 지시 말이 화면 글에 섞였다(" + " · ".join(leaked) + ")")
    return problems


def render_frame(spec: dict[str, Any], theme: str | None, index: int = 0, total: int = 0) -> str:
    from .slide_parts import _t

    kind = spec["frame"]
    arrange, decos = style_of(theme)
    classes = ["slide", "pz-slide", "pz-frame", f"fr-{kind}", f"ar-{arrange}"]
    if arrange == "note":
        classes.insert(-1, "ar-center")
    classes += [f"deco-{name}" for name in decos]
    title = str(spec.get("title") or "")
    sub = str(spec.get("sub") or "")
    figure_in_main = isinstance(spec.get("figure"), dict) and arrange not in ("panel", "bottom")
    sub_px = 22 if len(sub) <= 70 else 19
    size = title_px(title, arrange, _title_budget(spec, arrange, decos, sub_px, figure_in_main))
    kicker = f'<p class="fr-kicker">{_t(spec["kicker"])}</p>' if spec.get("kicker") else ""
    sub_html = f'<p class="fr-sub" style="--ss:{sub_px}px">{_t(sub)}</p>' if sub else ""
    figure = spec.get("figure") if isinstance(spec.get("figure"), dict) else None
    figure_html = ""
    if figure:
        label = f'<span class="fr-label">{_t(figure["label"])}</span>' if figure.get("label") else ""
        note = f'<p>{_t(figure["note"])}</p>' if figure.get("note") else ""
        figure_html = f'<div class="fr-figure">{label}<span class="n">{_t(figure["value"])}</span>{note}</div>'
    meta = "".join(f"<div><dt>{_t(name)}</dt><dd>{_t(value)}</dd></div>" for name, value in spec.get("meta") or [])
    meta_html = f'<dl class="fr-meta">{meta}</dl>' if meta else ""
    note_html = f'<span class="fr-note">{_t(spec["note"])}</span>' if spec.get("note") else ""
    folio = f'<span class="folio">{index:02d} / {total:02d}</span>' if index and total else ""
    main = f'<div class="fr-main">{kicker}<h1 class="fr-title" style="--fs:{size}px">{_t(title)}</h1>{sub_html}'
    if arrange == "panel":
        panel = f'<div class="fr-panel">{figure_html}{meta_html}</div>' if (figure_html or meta_html) else '<div class="fr-panel"></div>'
        foot = f'<div class="fr-foot">{note_html or "<span></span>"}<span style="flex:1"></span>{folio}</div>'
        body = main + "</div>" + foot + panel
    elif arrange == "bottom":
        # 아래 짜임은 위 170px 가 장식 자리라 줄기가 짧다 — 큰 숫자는 바닥 줄 오른쪽에 작게 둔다(제목이 반 크기로 줄던 것 · 10-26).
        spacer = '<span style="flex:1"></span>'
        tail = figure_html.replace('class="fr-figure"', 'class="fr-figure fr-figure-foot"')
        foot = (f'<div class="fr-foot">{meta_html or spacer}{note_html}{tail}{folio}</div>'
                if meta_html or note_html or folio or tail else "")
        body = main + "</div>" + foot
    else:
        spacer = '<span style="flex:1"></span>'
        foot = (f'<div class="fr-foot">{meta_html or spacer}{note_html}{folio}</div>'
                if meta_html or note_html or folio else "")
        body = main + figure_html + "</div>" + foot
    seed = int(hashlib.sha1(title.encode("utf-8")).hexdigest()[:6], 16)
    deco = "".join(DECOS[name](index or 1, seed) for name in decos)
    return f'<section class="{" ".join(classes)}">{deco}{body}</section>'


def build_frame(spec: dict[str, Any], theme: str | None, index: int = 0, total: int = 0) -> tuple[str, str, list[str], list[str]]:
    """표지 · 마무리 조립표 → (조각 html, 짜임 이름, 쓴 부품, 고친 것). 잘못이 있으면 PartsError."""
    from .slide_parts import PartsError

    fixed = repair_frame(spec, index, total)
    problems = validate_frame(spec)
    if problems:
        raise PartsError("parts_invalid: " + " / ".join(problems))
    arrange, decos = style_of(theme)
    names = [f"frame-{spec['frame']}"] + (["figure"] if spec.get("figure") else []) + (["meta"] if spec.get("meta") else [])
    return render_frame(spec, theme, index, total), f"frame:{spec['frame']}:{arrange}", names, fixed


def menu() -> str:
    return FRAME_GUIDE


# ── 장식 부품 — 결 값의 색으로 코드가 그린다(모델은 보지 않는다) ─────────────────────────────────
def _box(style: str, inner: str, zone: bool = True) -> str:
    """장식 하나. zone 이면 「글이 들어오면 안 되는 자리」 — 넘침 · 겹침 재기(_FIT_JS)가 글과 이 자리의 겹침도 잰다.
    바탕에 까는 것(면 · 틀 · 선 · 옅은 숫자)은 zone 이 아니다 — 글이 그 위에 앉는 것이 그 결의 모양이다."""
    mark = " data-zone" if zone else ""
    return f'<div class="pz-deco"{mark} aria-hidden="true" style="{style}">{inner}</div>'


def _svg(view: str, body: str, keep: bool = False) -> str:
    aspect = "" if keep else ' preserveAspectRatio="none"'
    return f'<svg viewBox="{view}"{aspect} xmlns="http://www.w3.org/2000/svg">{body}</svg>'


#: 짜임 「side」의 장식 자리 — 글 줄기 padding(470px) 바깥, 바닥 줄 위.
_SIDE = "right:72px;top:56px;width:360px;bottom:132px;"


def _stripes(index: int, seed: int) -> str:
    rows = [(36, 38, 14), (22, 50, 12), (34, 46, 11), (16, 60, 13), (28, 48, 11), (18, 62, 14), (34, 44, 12), (22, 50, 13)]
    shift = seed % 9 - 4
    rects = []
    y = 0
    for x, w, h in rows:
        rects.append(f'<rect x="{x + shift}" y="{y}" width="{w}" height="{h}" fill="url(#pzs)"/>')
        y += h
    pattern = ('<defs><pattern id="pzs" width="2.4" height="100" patternUnits="userSpaceOnUse">'
               '<rect x="0" y="0" width="1" height="100" style="fill:var(--fd-a)"/></pattern></defs>')
    return _box(_SIDE, _svg("0 0 100 100", pattern + "".join(rects)))


def _rules(index: int, seed: int) -> str:
    line = "position:absolute;left:72px;right:72px;height:1.5px;background:var(--fd-line);"
    return (_box(line + "top:28px;", "", zone=False) + _box(line + "bottom:22px;", "", zone=False))


def _frame(index: int, seed: int) -> str:
    return _box("left:26px;top:26px;right:26px;bottom:26px;border:3px solid var(--fd-line);border-radius:4px;", "", zone=False)


def _ring(index: int, seed: int) -> str:
    body = ('<circle cx="40" cy="40" r="38" style="fill:none;stroke:var(--fd-b);stroke-width:1.5"/>'
            f'<text x="40" y="46" text-anchor="middle" style="font:500 17px Consolas, monospace;fill:var(--fd-b)">{index:02d}</text>')
    return _box("right:72px;top:44px;width:80px;height:80px;", _svg("0 0 80 80", body, keep=True))


def _pills(index: int, seed: int) -> str:
    widths = [118, 156, 96, 132, 84, 148, 110, 92, 138, 104, 126, 88]
    colors = ["var(--fd-b)", "var(--fd-c)", "var(--fd-b)", "var(--fd-c)", "var(--fd-c)", "var(--fd-b)"]
    shapes, x, y, i = [], 0, 0, seed % 3
    for row in range(3):
        x = 0 if row % 2 == 0 else 40
        while x < 1080:
            w = widths[i % len(widths)]
            shapes.append(f'<rect x="{x}" y="{y}" width="{w}" height="30" rx="15" style="fill:{colors[i % len(colors)]};opacity:.92"/>')
            x += w + 14
            i += 1
        y += 40
    return _box("left:72px;right:72px;top:40px;height:110px;", _svg("0 0 1136 110", "".join(shapes)))


def _blocks(index: int, seed: int) -> str:
    return (_box("left:0;top:250px;width:170px;height:260px;background:var(--fd-c);opacity:.78;", "", zone=False)
            + _box("right:0;top:0;width:300px;height:150px;background:var(--fd-c);opacity:.55;", "", zone=False)
            + _box("left:0;right:0;bottom:0;height:120px;background:linear-gradient(transparent,color-mix(in srgb,var(--fd-c) 45%,transparent));", "",
                   zone=False))


def _boxes(index: int, seed: int) -> str:
    body = ('<rect x="0" y="0" width="360" height="400" style="fill:var(--pz-card)"/>'
            '<rect x="118" y="112" width="170" height="150" style="fill:var(--fd-f)"/>'
            '<rect x="100" y="96" width="170" height="150" style="fill:var(--fd-a);stroke:var(--pz-bg);stroke-width:3"/>'
            '<polygon points="126,122 248,122 240,190 132,206" style="fill:var(--pz-bg);opacity:.85"/>')
    return _box(_SIDE, _svg("0 0 360 400", body))


def _panels(index: int, seed: int) -> str:
    checker = "".join(f'<rect x="{12 + (k % 4) * 10}" y="{12 + (k // 4) * 10}" width="10" height="10" style="fill:var(--pz-bg)"/>'
                      for k in range(16) if (k + k // 4) % 2 == 0)
    body = ('<rect x="0" y="0" width="172" height="400" style="fill:var(--pz-card)"/>'
            '<rect x="188" y="0" width="172" height="250" style="fill:var(--fd-c)"/>'
            '<rect x="188" y="266" width="172" height="134" style="fill:var(--pz-card)"/>' + checker)
    return _box(_SIDE, _svg("0 0 360 400", body))


def _pin(index: int, seed: int) -> str:
    body = ('<circle cx="22" cy="22" r="16" style="fill:var(--fd-b)"/><circle cx="17" cy="17" r="5" style="fill:var(--pz-bg);opacity:.6"/>'
            '<line x1="22" y1="38" x2="22" y2="58" style="stroke:var(--fd-b);stroke-width:2.5"/>')
    return _box("right:96px;top:46px;width:44px;height:60px;", _svg("0 0 44 60", body, keep=True))


def _rainbow(index: int, seed: int) -> str:
    colors = ["var(--fd-d)", "var(--fd-c)", "var(--fd-e)", "var(--fd-f)"]
    bands = "".join(f'<polygon points="{-40 + k * 0},{330 - k * 52} 400,{120 - k * 52} 400,{172 - k * 52} {-40},{382 - k * 52}" '
                    f'style="fill:{color}"/>' for k, color in enumerate(colors))
    circles = ('<circle cx="70" cy="70" r="46" style="fill:var(--fd-b)"/><circle cx="130" cy="58" r="40" style="fill:var(--fd-e)"/>'
               '<circle cx="104" cy="112" r="36" style="fill:var(--fd-c)"/>')
    return _box(_SIDE, _svg("0 0 360 400", bands + circles))


def _dots3(index: int, seed: int) -> str:
    body = ('<circle cx="10" cy="10" r="9" style="fill:var(--fd-d)"/><circle cx="34" cy="10" r="9" style="fill:var(--fd-c)"/>'
            '<circle cx="58" cy="10" r="9" style="fill:var(--fd-b);opacity:.45"/>')
    return _box("right:72px;top:46px;width:68px;height:20px;", _svg("0 0 68 20", body, keep=True))


def _blob(index: int, seed: int) -> str:
    body = ('<path d="M200 0 C 120 10, 60 70, 70 150 C 80 210, 160 230, 220 200 C 160 170, 150 110, 220 60 Z" style="fill:var(--fd-f)"/>'
            '<path d="M150 0 L 220 0 L 220 70 C 190 60, 160 30, 150 0 Z" style="fill:var(--fd-b)"/>')
    return _box("right:48px;top:36px;width:220px;height:230px;", _svg("0 0 220 230", body, keep=True))


def _bignum(index: int, seed: int) -> str:
    body = (f'<text x="360" y="150" text-anchor="end" style="font:400 150px Georgia, Batang, serif;fill:var(--fd-b)">No.</text>'
            f'<text x="360" y="360" text-anchor="end" style="font:400 210px Georgia, Batang, serif;fill:var(--fd-b)">{index:02d}</text>')
    return _box(_SIDE, _svg("0 0 360 400", body, keep=True))


def _watermark(index: int, seed: int) -> str:
    body = f'<text x="300" y="250" text-anchor="end" style="font:400 260px Georgia, Batang, serif;fill:var(--fr-ink);opacity:.07">{index:02d}</text>'
    return _box("right:40px;bottom:-40px;width:300px;height:260px;", _svg("0 0 300 260", body, keep=True), zone=False)


def _notes(index: int, seed: int) -> str:
    def note(x: int, y: int, w: int, h: int, color: str, tilt: float) -> str:
        return _box(f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;background:{color};transform:rotate({tilt}deg);"
                    "box-shadow:0 6px 14px var(--pz-shadow),0 1px 2px var(--pz-shadow);", "")
    return (note(52, 44, 118, 86, "var(--fd-d)", -7) + note(1100, 548, 128, 96, "var(--fd-e)", 6)
            + note(1132, 70, 70, 58, "var(--fd-f)", 9))


def _daisy_svg(size: int) -> str:
    petals = "".join(f'<ellipse cx="50" cy="24" rx="11" ry="22" transform="rotate({k * 30} 50 50)" '
                     'style="fill:#ffffff;stroke:var(--pz-ink);stroke-width:2.2"/>' for k in range(12))
    center = '<circle cx="50" cy="50" r="13" style="fill:#F7D154;stroke:var(--pz-ink);stroke-width:2.2"/>'
    return _svg("0 0 100 100", petals + center, keep=True)


def _daisy(index: int, seed: int) -> str:
    # 바닥 줄(이름:값 · 쪽)은 아래 72~720px 사이 — 아래 꽃은 장 귀퉁이 밖으로 반쯤 걸쳐 그 글을 덮지 않는다.
    spots = [("left:-22px;top:-20px;", 150), ("right:-26px;top:20px;", 110), ("left:-58px;bottom:-62px;", 120),
             ("right:-56px;bottom:-60px;", 124)]
    star = ('<polygon points="20,2 25,15 39,15 28,24 32,38 20,30 8,38 12,24 1,15 15,15" '
            'style="fill:var(--fd-d);stroke:var(--pz-ink);stroke-width:2"/>')
    out = "".join(_box(f"{pos}width:{size}px;height:{size}px;", _daisy_svg(size)) for pos, size in spots)
    out += _box("left:44px;top:200px;width:40px;height:40px;", _svg("0 0 40 40", star, keep=True))
    out += _box("right:150px;bottom:150px;width:34px;height:34px;", _svg("0 0 40 40", star.replace("--fd-d", "--fd-e"), keep=True))
    return out


def _bar(index: int, seed: int) -> str:
    return _box("left:0;top:0;bottom:0;width:16px;background:var(--fd-a);", "", zone=False)


DECOS = {"stripes": _stripes, "rules": _rules, "frame": _frame, "ring": _ring, "pills": _pills, "blocks": _blocks, "boxes": _boxes,
         "panels": _panels, "pin": _pin, "rainbow": _rainbow, "dots3": _dots3, "blob": _blob, "bignum": _bignum,
         "watermark": _watermark, "notes": _notes, "daisy": _daisy, "bar": _bar}


# ── 본문 장의 작은 무늬 한 점 (2026-10-26 대표 14:20 「본문에도 결 장식을 작게 하나만」) ─────────────────
# 쪽 머리 오른쪽 모서리에 그 결의 무늬 한 점. **글이 먼저다** — 재기(_FIT_JS)가 다 맞춘 뒤 이 점이 글(또는 사진 칸)에
# 닿으면 지운다(data-optional). 장식 때문에 글을 줄이거나 옮기지 않는다. IR 본문은 자기 디자인(컨설팅 보고서 결 · 장식 없음) 그대로.
_CORNER = "right:40px;top:22px;"


def _mark(style: str, inner: str) -> str:
    return f'<div class="pz-deco pz-mark" data-optional aria-hidden="true" style="{_CORNER}{style}">{inner}</div>'


def _m_stripes(index: int) -> str:
    rows = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="13" fill="url(#pzm)"/>' for x, y, w in ((30, 0, 70), (10, 14, 84), (24, 28, 76)))
    pattern = ('<defs><pattern id="pzm" width="4" height="20" patternUnits="userSpaceOnUse">'
               '<rect width="1.6" height="20" style="fill:var(--fd-a)"/></pattern></defs>')
    return _mark("width:110px;height:42px;", _svg("0 0 110 42", pattern + rows))


def _m_rules(index: int) -> str:
    body = "".join(f'<rect x="0" y="{y}" width="{w}" height="2" style="fill:var(--fd-line)"/>' for y, w in ((0, 56), (7, 40), (14, 56)))
    return _mark("width:56px;height:16px;", _svg("0 0 56 16", body))


def _m_frame(index: int) -> str:
    body = ('<rect x="1.5" y="1.5" width="31" height="31" style="fill:none;stroke:var(--fd-line);stroke-width:3"/>'
            '<rect x="10" y="10" width="14" height="14" style="fill:var(--fd-c)"/>')
    return _mark("width:34px;height:34px;", _svg("0 0 34 34", body, keep=True))


def _m_ring(index: int) -> str:
    body = ('<circle cx="22" cy="22" r="20.5" style="fill:none;stroke:var(--fd-b);stroke-width:1.5"/>'
            f'<text x="22" y="27" text-anchor="middle" style="font:500 13px Consolas, monospace;fill:var(--fd-b)">{index:02d}</text>')
    return _mark("width:44px;height:44px;", _svg("0 0 44 44", body, keep=True))


def _m_pills(index: int) -> str:
    body = ('<rect x="0" y="0" width="44" height="14" rx="7" style="fill:var(--fd-b)"/><rect x="50" y="0" width="30" height="14" rx="7" '
            'style="fill:var(--fd-c)"/><rect x="18" y="20" width="36" height="14" rx="7" style="fill:var(--fd-c)"/>'
            '<rect x="60" y="20" width="26" height="14" rx="7" style="fill:var(--fd-b)"/>')
    return _mark("width:86px;height:34px;", _svg("0 0 86 34", body))


def _m_blocks(index: int) -> str:
    return _mark("width:96px;height:34px;background:var(--fd-c);opacity:.8;", "")


def _m_boxes(index: int) -> str:
    body = ('<rect x="10" y="8" width="30" height="30" style="fill:var(--fd-f)"/>'
            '<rect x="2" y="0" width="30" height="30" style="fill:var(--fd-a);stroke:var(--pz-bg);stroke-width:2"/>')
    return _mark("width:42px;height:40px;", _svg("0 0 42 40", body, keep=True))


def _m_panels(index: int) -> str:
    checker = "".join(f'<rect x="{(k % 4) * 8}" y="{(k // 4) * 8}" width="8" height="8" style="fill:var(--pz-card)"/>'
                      for k in range(16) if (k + k // 4) % 2 == 0)
    return _mark("width:62px;height:32px;", _svg("0 0 62 32", checker + '<rect x="38" y="0" width="24" height="32" style="fill:var(--fd-c)"/>'))


def _m_pin(index: int) -> str:
    body = ('<circle cx="12" cy="12" r="10" style="fill:var(--fd-b)"/><circle cx="9" cy="9" r="3" style="fill:var(--pz-bg);opacity:.6"/>'
            '<line x1="12" y1="22" x2="12" y2="34" style="stroke:var(--fd-b);stroke-width:2"/>')
    return _mark("width:24px;height:34px;", _svg("0 0 24 34", body, keep=True))


def _m_rainbow(index: int) -> str:
    colors = ["var(--fd-d)", "var(--fd-c)", "var(--fd-e)", "var(--fd-f)"]
    bands = "".join(f'<polygon points="0,{34 - k * 8} 110,{14 - k * 8} 110,{20 - k * 8} 0,{40 - k * 8}" style="fill:{color}"/>'
                    for k, color in enumerate(colors))
    return _mark("width:110px;height:40px;", _svg("0 -12 110 52", bands))


def _m_dots3(index: int) -> str:
    return _mark("width:68px;height:20px;", _dots3(index, 0).split(">", 1)[1].rsplit("</div>", 1)[0])


def _m_blob(index: int) -> str:
    body = ('<path d="M54 0 C 30 4, 12 22, 16 42 C 20 58, 44 62, 60 54 C 44 46, 40 30, 60 16 Z" style="fill:var(--fd-f)"/>'
            '<path d="M40 0 L 60 0 L 60 18 C 52 16, 44 8, 40 0 Z" style="fill:var(--fd-b)"/>')
    return _mark("width:60px;height:60px;top:14px;", _svg("0 0 60 60", body, keep=True))


def _m_bignum(index: int) -> str:
    body = f'<text x="96" y="30" text-anchor="end" style="font:400 30px Georgia, Batang, serif;fill:var(--fd-b)">No.{index:02d}</text>'
    return _mark("width:96px;height:38px;", _svg("0 0 96 38", body, keep=True))


def _m_watermark(index: int) -> str:
    body = f'<text x="70" y="44" text-anchor="end" style="font:400 50px Georgia, Batang, serif;fill:var(--fd-b);opacity:.35">{index:02d}</text>'
    return _mark("width:70px;height:52px;", _svg("0 0 70 52", body, keep=True))


def _m_notes(index: int) -> str:
    return _mark("width:52px;height:44px;", '<div style="position:absolute;inset:0;background:var(--fd-d);transform:rotate(6deg);'
                 'box-shadow:0 4px 10px var(--pz-shadow)"></div><div style="position:absolute;left:12px;top:-6px;width:30px;height:11px;'
                 'background:var(--pz-tape);transform:rotate(-4deg)"></div>')


def _m_daisy(index: int) -> str:
    return _mark("width:54px;height:54px;top:14px;", _daisy_svg(54))


BODY_MARKS = {"stripes": _m_stripes, "rules": _m_rules, "frame": _m_frame, "ring": _m_ring, "pills": _m_pills, "blocks": _m_blocks,
              "boxes": _m_boxes, "panels": _m_panels, "pin": _m_pin, "rainbow": _m_rainbow, "dots3": _m_dots3, "blob": _m_blob,
              "bignum": _m_bignum, "watermark": _m_watermark, "notes": _m_notes, "daisy": _m_daisy}


def body_mark(theme: str | None, index: int = 0) -> str:
    """본문 부품 장의 무늬 한 점 — 결의 장식 중 첫 것의 작은 판. 없거나(broadside) 부품 묶음 밖 결(IR)이면 빈 글.
    paper · ink 의 왼쪽 띠(bar)는 무늬가 아니라 면이라 본문에는 두지 않는다(표지 · 마무리만)."""
    from .slide_parts import family

    if not family(theme):
        return ""
    _, decos = style_of(theme)
    name = next((name for name in decos if name in BODY_MARKS), "")
    return BODY_MARKS[name](index or 1) if name else ""


# ── 틀째 html → 부품 (두 번째로 틀째 html 이 오면 받지 않고 옮긴다) ───────────────────────────────
_BLOCK_SPLIT = re.compile(r"<(?:/?(?:h1|h2|h3|h4|p|li|div|dt|dd|td|th|figcaption|blockquote|section|ul|ol|br)\b[^>]*)>", re.I)


def _blocks_of(fragment: str) -> list[tuple[str, str]]:
    """(태그, 글) — 보이는 글 토막을 문서 순서로. svg · style 은 뺀다."""
    text = re.sub(r"<(svg|style|script)\b.*?</\1\s*>", " ", str(fragment or ""), flags=re.S | re.I)
    out: list[tuple[str, str]] = []
    for match in re.finditer(r"<(h1|h2|h3|h4|p|li|div|dt|dd|td|th|span|b|strong|blockquote|figcaption)\b[^>]*>(.*?)(?=<(?:/?(?:h1|h2|h3|h4|p|li|div|dt|dd|td|th|blockquote|figcaption))\b|$)",
                             text, flags=re.S | re.I):
        plain = " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", match.group(2))).split())
        if plain:
            out.append((match.group(1).lower(), plain))
    return out


def frame_from_html(fragment: str, kind: str) -> dict[str, Any]:
    """틀째 표지 · 마무리 html 에서 글만 뽑아 조립표로 — 제목은 첫 h1(없으면 h2), 그 앞 짧은 말은 머리 말, 뒤 긴 말은 부제, 나머지 짧은 말은 meta."""
    blocks = _blocks_of(fragment)
    at = next((i for i, (tag, _) in enumerate(blocks) if tag == "h1"), None)
    if at is None:
        at = next((i for i, (tag, _) in enumerate(blocks) if tag in ("h2", "h3")), 0)
    spec: dict[str, Any] = {"frame": kind, "title": blocks[at][1][:_TITLE_MAX] if blocks else ""}
    before = [text for _, text in blocks[:at] if len(text) <= _KICKER_MAX and not re.fullmatch(r"[\d\s/.]+", text)]
    if before:
        spec["kicker"] = before[0]
    rest = [text for _, text in blocks[at + 1:] if not re.fullmatch(r"\d{1,2}\s*/\s*\d{1,2}", text)]
    long_at = next((i for i, text in enumerate(rest) if len(text) > 24), None)
    if long_at is not None:
        spec["sub"] = rest[long_at][:_SUB_MAX]
        # 머리 말이 제목 앞에 없으면 제목과 부제 사이의 짧은 말(템플릿 표지의 「꼬리말」 칸)이 머리 말이다.
        if "kicker" not in spec:
            between = [text for text in rest[:long_at] if len(text) <= _KICKER_MAX]
            if between:
                spec["kicker"] = between[0]
    tail = [text for i, text in enumerate(rest) if text not in (spec.get("sub"), spec.get("kicker")) and len(text) <= 60
            and (long_at is None or i > long_at)]
    meta, loose, i = [], [], 0
    while i < len(tail):
        # 짧은 이름(8자까지) 바로 뒤의 값은 「이름 : 값」 짝(템플릿 바닥 줄의 「정리 / 회사명 · 보고용」).
        if len(tail[i]) <= 8 and i + 1 < len(tail) and len(tail[i + 1]) > len(tail[i]):
            meta.append([tail[i], tail[i + 1]])
            i += 2
            continue
        loose.append(tail[i])
        i += 1
    if meta:
        spec["meta"] = meta[:_META_MAX]
    if loose:
        spec["note"] = " · ".join(dict.fromkeys(loose))[:80]
    return spec


def parts_from_html(fragment: str) -> dict[str, Any]:
    """틀째 본문 장 html → 글 부품 하나짜리 조립표(제목 · 첫 문장 · 나머지 줄)."""
    blocks = _blocks_of(fragment)
    at = next((i for i, (tag, _) in enumerate(blocks) if tag in ("h1", "h2")), 0)
    head = blocks[at][1][:60] if blocks else "본문"
    rest = list(dict.fromkeys(text for _, text in blocks[at + 1:] if text != head))
    lede = [rest[0]] if rest and len(rest[0]) > 20 else []
    items = [text for text in rest[len(lede):] if len(text) >= 2][:6] or ["(내용 없음)"]
    return {"head": head, "lede": lede, "layout": "1", "cols": [[{"part": "text", "items": items}]]}


# ── 장표 유형 — 결(느낌) × 유형(장 흐름) (2026-10-26) ─────────────────────────────────────────
#: 유형 → (알아보는 낱말, 권장 흐름). 흐름은 출발점이다 — 이야기에 맞게 빼고 더한다. IR 은 IR 결(ir-brief)의 흐름이 따로 더 자세하다.
DECK_TYPES: dict[str, tuple[tuple[str, ...], str]] = {
    "IR": (("IR", "투자", "피치", "데모데이", "투자유치", "투자 유치", "시드", "시리즈", "펀딩"),
           "1 cover(figure 에 요청 금액) / 2 문제 = points 3 / 3 해법 · 사업 모델 = flow + kv / 4 견인 지표 = metrics / "
           "5 시장 = pair + text / 6 경쟁 = table / 7 단위 경제 = bars + panel / 8 로드맵 = stages / 9 팀 = people / 10 closing(요청 한 문장)"),
    "교육": (("교육", "강의", "수업", "강좌", "튜토리얼", "연수", "온보딩", "교재", "학습", "가르"),
           "1 cover / 2 오늘 배울 것 = points 3 / 3 왜 필요한가 = text + stat / 4~ 개념마다 한 장 = text + steps 또는 pair(전 → 후) / "
           "그다음 실습 · 절차 = steps / 자주 하는 실수 = table 또는 text / 요약 = points + bottom / closing(다음 걸음 · 숙제)"),
    "제안": (("제안", "기획안", "기획", "설득", "도입", "견적", "협업 제안", "파트너"),
           "1 cover / 2 지금 문제 = stat(손실 크기) + text / 3 제안 = flow 또는 steps(우리 on) / 4 근거 = metrics 또는 bars / "
           "5 비교 = table(우리 줄 highlight) / 6 일정 · 비용 = stages 또는 kv + calc / closing(결정해 줄 것 한 문장)"),
    "소개": (("소개", "회사 소개", "회사소개", "서비스 소개", "제품 소개", "브랜드", "포트폴리오", "안내"),
           "1 cover / 2 한 문장 정의 = text + panel / 3 무엇을 하나 = points 3 / 4 어떻게 = flow / 5 숫자로 = metrics / "
           "6 사례 · 사진 = photo + text / 7 사람 = people / closing(연락 · 다음 걸음)"),
    "보고": (("보고", "현황", "실적", "결과", "브리핑", "뉴스", "동향", "회의", "주간", "월간", "분기", "정리", "요약", "소식"),
           "1 cover / 2 결론 먼저 = stat 또는 panel + text / 3~ 근거마다 한 장 = metrics · bars · table + text / "
           "위험 · 남은 일 = steps 또는 kv / closing(정할 것 · 다음 걸음)"),
}
DEFAULT_TYPE = "보고"


def deck_type(about: str, asked: str | None = None) -> str:
    """요청 글로 유형을 고른다 — 사람이 정했으면 그것. 낱말이 여럿 맞으면 위에서부터(IR > 교육 > 제안 > 소개 > 보고)."""
    if asked in DECK_TYPES:
        return str(asked)
    text = str(about or "")
    for name, (words, _) in DECK_TYPES.items():
        if any(word in text for word in words):
            return name
    return DEFAULT_TYPE


def flow_text(kind: str) -> str:
    return f"{kind} 장표의 장 흐름(권장 · 출발점 — 이야기에 맞게 빼고 더한다): " + DECK_TYPES[kind][1]
