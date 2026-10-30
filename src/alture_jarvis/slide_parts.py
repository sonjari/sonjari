"""장표 부품 조립 — 템플릿을 부품으로 증류하고, 모델은 부품을 골라 배치한다 (2026-10-25 대표).

## 왜

6차까지 모델은 템플릿 장 하나를 통째로 복사해 글만 바꿨다 — 품질은 고르지만 장마다 배치가 정해져 있어 이야기에 맞게 못 짠다.
그렇다고 모델이 HTML · CSS 를 처음부터 쓰게 하면 로컬 27B 는 장마다 품질이 들쑥날쑥하다(10-25 아침 Akxan 방식 6분 · 배경 빠짐).
대표: 「템플릿은 자산 — 부품으로 증류하고 모델은 부품을 골라 배치」. 자유는 중간, 품질 바닥은 부품 CSS 가 지킨다.

## 나눔

    결(템플릿)   부품의 색 · 글꼴 · 선 · 간격(CSS) — 손대지 않는 자산
    모델         장마다 조립표(JSON): 칸 나눔 · 부품 · 역할(주인공 하나) · 글 · 숫자
    이 모듈      조립표 검사(모르는 부품 · 빠진 칸 · 분량 상한 · 자리 표시 · 연출 지시문 샘) → <section> 조각
                 막대 길이는 값으로 계산한다(같은 눈금 — 모델이 % 를 셈하지 않는다)

Akxan ppt-agent-skill(MIT)의 page-html-playbook 에서 가져온 생각: 장마다 계획(카드 · 역할 anchor/support · 분량 상한 ·
차트 종류)을 먼저 세우고 정해진 부품으로 조립한다, 주인공 카드가 첫 시선, 연출 지시문이 화면에 새면 지운다.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
from typing import Any

#: 부품을 갖춘 결 → 부품 CSS 가 들어 있는 결(지금은 우리가 쓴 IR 브리프).
PARTS_THEMES: frozenset[str] = frozenset({"ir-brief"})
#: 부품 결의 표지 · 마무리 — 2026-10-26 부터 **틀째 장이 아니라 부품**(`slide_frames`)이다. 이름은 이야기판 카드의 틀 이름으로 쓴다.
#:   예전엔 IR 의 ir-cover · ir-closing, 묶음 결은 그 결의 첫 장 · 마지막 장 틀을 통째로 받았다 — 대표 「템플릿에 종속되면 큰일난다」.
WHOLE_SLIDES: dict[str, tuple[str, ...]] = {}
FRAME_NAMES: tuple[str, str] = ("cover", "closing")

LAYOUTS = {"1": [1], "1:1": [1, 1], "2:1": [2, 1], "1:2": [1, 2], "3:1": [3, 1], "1:3": [1, 3], "3:2": [3, 2], "2:3": [2, 3],
           "1:1:1": [1, 1, 1], "2:1:1": [2, 1, 1], "1:2:1": [1, 2, 1], "1:1:2": [1, 1, 2]}
MAX_CARDS = 6
MAX_COLS = 4
_LAYOUT_FORM = re.compile(r"[1-3](?::[1-3]){0,3}")


def _widths(layout: str) -> list[int] | None:
    """칸 나눔 → 칸 너비 비율. 목록에 없어도 1~4칸 · 칸마다 1~3 비율이면 받는다(「1:1:1:1」 · 「2:1:1:1」)."""
    if layout in LAYOUTS:
        return LAYOUTS[layout]
    return [int(x) for x in layout.split(":")] if _LAYOUT_FORM.fullmatch(layout) else None

#: 부품 이름 → (언제 쓰나, 필수 칸, 예시). 예시는 메뉴에 그대로 보인다.
PARTS: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {
    "text": ("소제목 + 짧은 글 또는 대시 목록(근거 · 까닭)", (),
             {"part": "text", "title": "왜 지금", "quote": "바뀌는 것 한 줄", "items": ["근거 한 줄", "근거 한 줄"]}),
    "stat": ("큰 숫자 하나(주인공 숫자 · 위험 크기). tone: navy(강조색 면 — 결마다 색이 다르다) · loss(손실 빨강)", ("value",),
             {"part": "stat", "label": "월 반복 매출", "value": "4,079", "unit": "만 원", "note": "412곳 × 9.9만 원"}),
    "metrics": ("숫자 2~4개 나란히(견인 지표). evidence 를 주면 증빙 자리가 붙는다", ("items",),
                {"part": "metrics", "items": [{"label": "유료 학원", "value": "412", "unit": "곳", "note": "2026.9.30 기준",
                                               "evidence": "관리자 화면 캡처"}]}),
    "bars": ("세로 막대 2~6개 — value 는 숫자만, 길이는 손자리가 같은 눈금으로 그린다. 주인공 막대에 on", ("items",),
             {"part": "bars", "unit": "만 원", "items": [{"name": "직접 고용", "value": 120}, {"name": "우리", "value": 9.9, "on": True}]}),
    "table": ("표 — 열 2~6 · 줄 1~7. 강조할 줄은 highlight(0부터 · \"last\")", ("columns", "rows"),
              {"part": "table", "columns": ["회사", "고객", "매출"], "rows": [["A사", "21,000", "182"], ["우리", "6,000", "목표"]],
               "highlight": "last"}),
    "flow": ("가로 흐름 상자 2~5개(사업 모델 · 과정). 우리 상자에 on, arrows 는 사이 글", ("nodes",),
             {"part": "flow", "nodes": [{"label": "공급", "title": "알림톡 망", "text": "건당 7원"},
                                        {"label": "우리", "title": "클래스노트", "on": True}], "arrows": ["조달"]}),
    "steps": ("번호 붙은 단계 3~5개(막는 방법 · 절차). 핵심 단계에 on", ("items",),
              {"part": "steps", "title": "우리가 막는 방법", "items": [{"title": "가입 첫날", "text": "명단만 받는다"}]}),
    "stages": ("로드맵 격자 — 단계 3~5 × 줄 1~4. 지금 단계에 on", ("stages",),
               {"part": "stages", "stages": [{"label": "1단계 · 지금", "title": "연동", "on": True}, {"label": "2단계", "title": "요약"}],
                "rows": [{"name": "핵심 기능", "cells": ["출결 알림", "상담 요약"]}]}),
    "pair": ("지금 → 바뀐 뒤 두 상자(시장 몫 · 전후 비교)", ("before", "after"),
             {"part": "pair", "before": {"label": "지금", "year": "2026", "text": "전체 중 우리 몫", "value": "510억", "sub": "산출식"},
              "after": {"label": "바뀐 뒤(추정)", "year": "2028", "text": "전제 한 줄", "value": "736억", "sub": "1.4배"}}),
    "panel": ("강조색 면 상자(핵심 비율 · 누적 필요 자금 · 결론)", ("value",),
              {"part": "panel", "label": "이익률(매출 대비)", "value": "56.6%", "text": "이익 5.6 ÷ 매출 9.9"}),
    "calc": ("사례 계산 — 식과 결과(위험이 생겨도 손실은 얼마)", ("items",),
             {"part": "calc", "title": "사례 계산", "items": [{"title": "해지율 38%", "expr": "5.6만 × 31.6개월", "result": "177만 원"}],
              "assume": "가정 한 줄"}),
    "people": ("사람 카드 2~4명(팀). nick 은 기억에 남는 한 줄 소개", ("items",),
               {"part": "people", "title": "현장 실행", "items": [{"name": "이름", "role": "영업", "text": "해 본 일 한 줄"}]}),
    "points": ("번호 붙은 요점 2~4개를 나란히(질문 셋 · 요약 셋)", ("items",),
               {"part": "points", "items": [{"title": "요점 이름", "sub": "한 줄 부제", "text": "두세 문장"}]}),
    "photo": ("사람이 넣을 사진 자리(매장 · 제품 · 팀 · 화면 캡처). 손자리는 그림을 만들지 않는다 — 사람이 화면에서 끌어다 넣는다. "
              "ratio: 16:9 · 4:3 · 1:1 · 3:4", ("label",),
              {"part": "photo", "label": "매장 전경", "caption": "광주 본점 · 2026.9", "ratio": "4:3"}),
    "kv": ("이름 : 값 목록(조달 조건 · 개요)", ("items",),
           {"part": "kv", "title": "조달", "items": [["방식", "시드 8억 + 정책 자금 4억"], ["진행", "실사 중"]]}),
}

#: 분량 상한 — 넘치면 돌려보낸다(Akxan 의 content_budget).
_BUDGET = {"metrics": 4, "bars": 6, "flow": 5, "steps": 5, "points": 4, "people": 4, "kv": 7, "calc": 3, "text": 6}
_TABLE_MAX = (7, 6)  # 줄 · 열
#: 화면에 새면 안 되는 연출 · 지시 말(Akxan 「반누설」).
_DIRECTOR = re.compile(r"이 장(?:은|에서|의 목적)|여기서는 먼저|자리 표시|플레이스홀더|placeholder|lorem|예시 문구|TODO", re.I)
_PLACEHOLDER = re.compile(r"○{1,}|XX억|xx억|\?\?\?")
_ALLOWED_TAGS = re.compile(r"&lt;(/?)(u|b|mark)&gt;")


class PartsError(ValueError):
    pass


GUIDE = (
    "부품 조립 — 이 결은 **모든 장을 부품으로 조립**한다(html 틀 없음). 표지 · 마무리는 frames 의 조립표, 그 사이 장은 "
    "parts(조립표 JSON)를 넣는다:\n"
    '{"head":"섹션","sub":"소주제","lede":["첫 줄 — 사실","둘째 줄 — 그래서 <u>핵심어</u>"],"layout":"2:1",'
    '"cols":[[부품, 부품],[부품]],"source":"출처 · 기준일","unit":"단위","bottom":"결론 띠(선택)"}\n'
    "- 색 · 선 · 간격 · 막대 길이는 손자리가 그린다. 너는 장마다 이야기에 맞는 부품을 고르고, 칸 나눔(layout)을 정하고, 글 · 숫자를 채운다.\n"
    "- 레시피(order)는 출발점이다 — 이야기에 맞게 부품을 바꾸고 더한다. 이웃한 두 장은 다른 짜임(칸 나눔 · 부품)으로.\n"
    "- 장마다 주인공(role:\"anchor\") 하나 — 그 장의 결론을 보이는 부품. 부품은 한 장에 6개까지.\n"
    "- 숫자에는 산출식이나 출처를 note · source 에. 막대 value 는 숫자만(단위는 unit). 「○○」 같은 자리 표시 · 연출 지시 말은 남기지 않는다.\n"
    "- 글 안에서는 <u>밑줄</u> · <b>굵게</b> · <mark>형광</mark> 만 쓴다(형광은 장마다 한 곳)."
)


#: 부품 묶음(2026-10-25 대표 「유사도 · 유형으로 묶음집」) — 결 24개를 「그리는 문법」 넷으로 묶었다.
#:   line(선) · block(면) · round(둥근 칸) · sticky(붙인 종이). 묶음은 `slide_themes/parts/<묶음>.css`, 결마다 다른 것은 값(themes.json)뿐.
#:   IR 브리프는 자기 부품 CSS 를 그대로 쓴다(이 묶음 밖).
_PARTS_DIR = Path(__file__).resolve().parent / "slide_themes" / "parts"
_TOKEN_DEFAULTS = {
    "bg": "#ffffff", "ink": "#15181f", "sub": "#5a6274", "faint": "#959cab", "line": "#d8dce4", "fill": "#f3f5f9",
    "accent": "#0f2152", "on_accent": "#ffffff", "on_accent_sub": "#dfe5f2", "hi": "#ffee9a", "loss": "#c33b2c", "bar": "#c4ccdc",
    "font": "'Malgun Gothic', '맑은 고딕', sans-serif", "num_font": "'Segoe UI', 'Malgun Gothic', sans-serif",
    "head_weight": "700", "num_weight": "300", "radius": "0px", "stroke": "1px", "card_border": "0 solid transparent",
    "card_shadow": "none", "shadow": "rgba(0,0,0,.15)", "tape": "rgba(255,255,255,.6)",
}
#: 값이 없으면 다른 값을 따른다(순서대로 푼다).
_TOKEN_FALLBACK = (("line_strong", "ink"), ("key", "accent"), ("head_color", "ink"), ("card", "fill"), ("card_ink", "ink"),
                   ("card_key", "key"), ("fill_2", "fill"), ("fill_2_ink", "sub"), ("head_font", "font"), ("label_font", "font"),
                   ("c1", "card"), ("c1_ink", "card_ink"))


def _families() -> dict[str, dict[str, str]]:
    try:
        raw = json.loads((_PARTS_DIR / "themes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, str]] = {}
    for name, value in raw.items():
        if name.startswith("_") or not isinstance(value, dict):
            continue
        base = raw.get(str(value.get("_from") or ""), {}) if value.get("_from") else {}
        merged = {**base, **{k: v for k, v in value.items() if k != "_from"}}
        if merged.get("family") in {"line", "block", "round", "sticky"}:
            out[name] = {k: str(v) for k, v in merged.items()}
    return out


FAMILIES: dict[str, dict[str, str]] = _families()


def family(theme: str | None) -> str:
    """결의 부품 묶음 — line · block · round · sticky. 묶음 밖(IR 브리프 · 모르는 결)이면 빈 글."""
    return (FAMILIES.get(str(theme or "")) or {}).get("family", "")


def theme_tokens(theme: str) -> dict[str, str]:
    values = {**_TOKEN_DEFAULTS, **{k: v for k, v in (FAMILIES.get(theme) or {}).items() if k not in ("family", "arrange", "deco")}}
    for name, source in _TOKEN_FALLBACK:
        values.setdefault(name, values.get(source, ""))
    return values


def parts_css(theme: str | None) -> str:
    """부품 장에 끼울 CSS — 공통 뼈대 + 묶음 문법 + 결 값. 묶음 밖 결이면 빈 글(IR 은 자기 CSS 에 부품이 있다)."""
    name = family(theme)
    if not name:
        return ""
    tokens = theme_tokens(str(theme))
    block = ":root{" + "".join(f"--pz-{key.replace('_', '-')}:{value};" for key, value in tokens.items()) + "}"
    css = [block, (_PARTS_DIR / "common.css").read_text(encoding="utf-8")]
    if name != "line":
        css.append((_PARTS_DIR / f"{name}.css").read_text(encoding="utf-8"))
    return "\n".join(css)


def whole_slides(theme: str | None) -> tuple[str, ...]:
    """부품 결의 표지 · 마무리 이름 — 이제 틀째 장이 아니라 표지 · 마무리 부품(`slide_frames`)이다(2026-10-26).

    ★ 묶음 결에 틀 전체를 안내로 주면 daisy-days 는 7.1만 글자(장식 SVG)였다(10-25 밤). 표지 · 마무리 틀만 줄여 줘도
      daisy 표지 한 장을 넣는 부르기가 약 8,000토큰을 냈다 — 큰 장식 SVG 를 그대로 베꼈다(10-26 결과.md). 이제 틀을 아예 주지 않는다.
    """
    return FRAME_NAMES if supports(theme) else ()


def supports(theme: str | None) -> bool:
    return bool(theme) and (theme in PARTS_THEMES or bool(family(theme)))


def menu(theme: str) -> str:
    """부품 메뉴 — 이름 · 언제 · 예시 JSON. guide 에 실린다."""
    lines = ["칸 나눔(layout): " + " · ".join(LAYOUTS) + " · 1:1:1:1  (숫자는 칸 너비 비율 · 칸은 4개까지)"]
    for name, (when, _, example) in PARTS.items():
        lines.append(f"- {name}: {when}\n  {json.dumps(example, ensure_ascii=False)}")
    return "\n".join(lines)


def parse(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        raise PartsError("parts_empty")
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise PartsError(f"parts_not_json: 조립표가 JSON 이 아니다({exc.msg} · {exc.pos}번째 글자)") from exc
    if not isinstance(value, dict):
        raise PartsError("parts_not_object: 조립표는 {head, lede, layout, cols} 객체다")
    return value


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def validate(spec: dict[str, Any]) -> list[str]:
    """조립표의 잘못을 모두 모은다(빈 목록이면 통과)."""
    problems: list[str] = []
    layout = str(spec.get("layout") or "1")
    cols = spec.get("cols")
    if not isinstance(cols, list) or not cols or not all(isinstance(col, list) for col in cols):
        problems.append("cols 는 칸마다 부품 목록: [[부품, …], [부품, …]]")
        return problems
    widths = _widths(layout)
    if widths is None or len(widths) != len(cols):
        # 칸 나눔이 없거나 칸 수와 안 맞으면 같은 너비로 고쳐 준다 — 돌려보낼 일이 아니다.
        #   두 실제 판(fde0be39 · e5844c85)은 「1:1」에 칸 하나를 냈고, grove 판(6cda73c3)은 「1:1:1:1」이 거절되자 판을 접었다(10-25 밤).
        if 1 <= len(cols) <= MAX_COLS:
            spec["layout"] = ":".join(["1"] * len(cols))
        else:
            problems.append(f"cols 는 칸 1~{MAX_COLS}개 — {len(cols)}개")
    if not str(spec.get("head") or "").strip():
        problems.append("head(섹션 이름)가 비었다")
    cards = [card for col in cols for card in col]
    if not cards:
        problems.append("부품이 하나도 없다")
    if len(cards) > MAX_CARDS:
        problems.append(f"부품 {len(cards)}개 — 한 장에 {MAX_CARDS}개까지(장을 나눈다)")
    anchors = [card for card in cards if isinstance(card, dict) and card.get("role") == "anchor"]
    if len(anchors) > 1:
        problems.append(f"주인공(role: anchor)이 {len(anchors)}개 — 하나만")
    for number, card in enumerate(cards, 1):
        if not isinstance(card, dict):
            problems.append(f"{number}번 부품이 객체가 아니다")
            continue
        name = str(card.get("part") or "")
        if name not in PARTS:
            problems.append(f"{number}번 부품 「{name}」 없음 — {' · '.join(PARTS)} 중 하나")
            continue
        for field in PARTS[name][1]:
            if card.get(field) in (None, "", [], {}):
                problems.append(f"{number}번 {name} 의 {field} 가 비었다")
        items = card.get("items") if isinstance(card.get("items"), list) else []
        if name in _BUDGET and len(items) > _BUDGET[name]:
            problems.append(f"{number}번 {name} 항목 {len(items)}개 — {_BUDGET[name]}개까지")
        if name == "bars":
            for item in items:
                if _number(item.get("value") if isinstance(item, dict) else None) is None:
                    problems.append(f"{number}번 bars 의 value 「{item.get('value') if isinstance(item, dict) else item}」 — 숫자만(단위는 unit 에)")
                    break
        if name == "table":
            rows = card.get("rows") if isinstance(card.get("rows"), list) else []
            columns = card.get("columns") if isinstance(card.get("columns"), list) else []
            if len(rows) > _TABLE_MAX[0] or len(columns) > _TABLE_MAX[1]:
                problems.append(f"{number}번 표 {len(rows)}줄 × {len(columns)}열 — {_TABLE_MAX[0]}줄 × {_TABLE_MAX[1]}열까지")
            if any(isinstance(row, list) and len(row) != len(columns) for row in rows):
                problems.append(f"{number}번 표의 줄마다 칸 수가 열 수({len(columns)})와 같아야 한다")
    texts = _strings(spec)
    left = sorted({m.group(0) for text in texts for m in _PLACEHOLDER.finditer(text)})
    if left:
        problems.append("자리 표시가 남았다(" + " · ".join(left) + ") — 이 발표의 실제 값으로")
    leaked = sorted({m.group(0) for text in texts for m in _DIRECTOR.finditer(text)})
    if leaked:
        problems.append("연출 지시 말이 화면 글에 섞였다(" + " · ".join(leaked) + ") — 듣는 사람이 읽을 글만")
    return problems


# ── 계산 검사 (2026-10-25 실제 판 fde0be39) ──────────────────────────────────────────────────
# 모델이 맞게 쓴 「4.3만 × 9.9만 × 12 = 511억」을 스스로 「10배 오타」라며 「5,108억」으로 고쳤다(계산하면 510.8억).
# 장에 적힌 식은 손자리가 직접 계산해 본다 — 안내문보다 결정론(사고 R).
_UNITS = {"조": 1e12, "억": 1e8, "만": 1e4, "천": 1e3}
_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(조|억|만|천)?"
_OPS = {"×": "*", "x": "*", "X": "*", "*": "*", "÷": "/", "/": "/", "+": "+", "−": "-", "-": "-", "–": "-"}
#: 숫자 · 단위 · 연산자 사이에 끼어도 되는 말(「4.3만 곳 × 월 9.9만 × 12」).
_FILLER = r"[\s가-힣%]{0,6}?"
_EXPR = re.compile(
    rf"{_NUM}{_FILLER}(?:\s*([×xX*÷/+−–-])\s*{_FILLER}{_NUM}{_FILLER}){{1,5}}\s*=\s*{_FILLER}(-?{_NUM[1:]}\s*(%?)", re.S)
_TOKEN = re.compile(rf"{_NUM}\s*(%)?|([×xX*÷/+−–-])")
#: 「13.9% (71.3 ÷ 511)」 · 「4,079만(412×9.9)」 — 값 뒤 괄호 안의 식.
#: 값에 붙는 단위 말 — 「7.4곳 (412 × 1.8%)」 · 「31.6개월(12 ÷ 0.38)」. 단위 없는 값의 괄호는 식이 아닐 때가 많다
#: (「5 (4×24)」 · 「4.5 (전공 평점: 4.32 / 4.5)」 — 10-25 지난 문서 쓰기 1,116번 대 보기에서 헛걸림).
_SUFFIX = r"(%|곳|원|개월|명|개|건|배|시간|분|초|년|회|억|만)"
_PAREN = re.compile(rf"{_NUM}\s*{_SUFFIX}?\s*\(\s*([^()=]{{3,60}}?)\s*\)")
#: 괄호 안이 식일 때만 — 숫자 · 연산자 · 단위만(「제주 20,000원 / 도서산간 40,000원」 같은 글은 아니다).
_PURE = re.compile(r"[\d\s,.%×xX*÷/+−–\-만억천조곳원개월명건배시간분초년회]+")
_DATEISH = re.compile(r"\d{4}\s*[-./]\s*\d{1,2}|\d{1,2}\s*/\s*\d{1,2}\s*$")


def _value(number: str, unit: str | None) -> float:
    return float(number.replace(",", "")) * _UNITS.get(unit or "", 1.0)


def _evaluate(expr: str) -> float | None:
    """「4.3만 곳 × 월 9.9만 × 12」 → 값. 숫자 · 연산자가 번갈아 나오지 않으면 None(계산 안 함)."""
    pieces: list[str] = []
    want_number = True
    for match in _TOKEN.finditer(expr):
        if match.group(1):
            if not want_number:
                return None
            # 「412 × 1.8%」의 1.8% 는 0.018 이다(10-25 실제 장 74개 대 보기에서 헛걸림 1건).
            pieces.append(repr(_value(match.group(1), match.group(2)) / (100 if match.group(3) else 1)))
            want_number = False
        else:
            if want_number:
                return None
            pieces.append(_OPS[match.group(4)])
            want_number = True
    if want_number or len(pieces) < 3:
        return None
    try:
        return float(eval("".join(pieces), {"__builtins__": {}}, {}))  # noqa: S307 — 숫자와 + - * / 만 들어간다
    except (ZeroDivisionError, SyntaxError):
        return None


def _fmt_like(value: float, unit: str | None, percent: bool) -> str:
    if percent:
        return f"{value * 100:,.2f}%"
    scale = _UNITS.get(unit or "", 1.0)
    shown = value / scale
    return (f"{shown:,.1f}" if abs(shown) < 1000 else f"{shown:,.0f}") + (unit or "")


def _tolerance(raw: str, unit: str | None, percent: bool) -> float:
    """적힌 숫자의 자릿수만큼 봐준다 — 「1%」는 ±0.5, 「13.9%」는 ±0.05, 「182억」은 ±0.5억(반올림해 쓴 값)."""
    decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
    scale = 1.0 if percent else _UNITS.get(unit or "", 1.0)
    return 0.5 * 10 ** -decimals * scale


def _wrong(computed: float, stated: float, percent: bool, tolerance: float = 0.0) -> bool:
    """틀렸나 — 반올림(3% · 적힌 자릿수)은 봐준다. 단위를 빼고 쓴 경우(412 × 9.9 = 4,079만)는 만 · 억 단위 차이로 보고 봐준다."""
    if percent:
        computed *= 100
    for unit in (1.0, 1e4, 1e-4, 1e8, 1e-8, 1e12, 1e-12):
        shown = computed / unit
        if abs(shown - stated) <= tolerance * 1.0001:
            return False
        if stated and abs(shown / stated - 1) <= 0.03:
            return False
    return True


def arithmetic_problems(texts: list[str]) -> list[str]:
    """글 안의 「식 = 값」 · 「값(식)」을 직접 계산해 틀린 것을 돌려준다."""
    found: list[str] = []
    for text in texts:
        plain = re.sub(r"<[^>]+>", "", str(text))
        for match in _EXPR.finditer(plain):
            left = plain[match.start(): plain.index("=", match.start())]
            computed = _evaluate(left)
            stated_raw, stated_unit, percent = match.groups()[-3:]
            if computed is None or stated_raw is None:
                continue
            stated = _value(stated_raw.lstrip("-"), stated_unit) * (-1 if stated_raw.startswith("-") else 1)
            if percent:
                stated = float(stated_raw.replace(",", ""))
            if _wrong(computed, stated, bool(percent), _tolerance(stated_raw.lstrip("-"), stated_unit, bool(percent))):
                found.append(f"「{match.group(0).strip()}」 — 계산하면 {_fmt_like(computed, stated_unit, bool(percent))}")
        for match in _PAREN.finditer(plain):
            inner = match.group(4)
            if not (match.group(2) or match.group(3)) or not _PURE.fullmatch(inner) or _DATEISH.search(inner):
                continue
            computed = _evaluate(inner)
            if computed is None:
                continue
            percent = match.group(3) == "%"
            unit = match.group(2) or (match.group(3) if match.group(3) in ("억", "만") else None)
            stated = float(match.group(1).replace(",", "")) if percent else _value(match.group(1), unit)
            if _wrong(computed, stated, percent, _tolerance(match.group(1), unit, percent)):
                found.append(f"「{match.group(0).strip()}」 — 괄호 안을 계산하면 {_fmt_like(computed, unit, percent)}")
    return list(dict.fromkeys(found))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


#: 객체로 온 글 칸에서 앞(이름)과 뒤(내용)로 읽는 열쇠 — 모델이 짝 대신 {title, text} 를 보낸다.
_NAME_KEYS = ("title", "name", "label", "key", "head")
_BODY_KEYS = ("text", "value", "desc", "description", "note", "body")


def _plain(value: Any) -> str:
    """글 칸에 객체 · 목록이 와도 **코드 글자({'text': …})를 찍지 않고** 사람이 읽는 글로 잇는다 (10-26 소개 판 be78277a).

    kv 부품이 `[[{title, text}, …]]` 를 받아 장에 `{'text': '클로드가 …', 'title': …}` 가 그대로 찍혔다. 어느 부품이든 바닥에서 막는다.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        name = next((str(value[k]) for k in _NAME_KEYS if value.get(k)), "")
        body = next((str(value[k]) for k in _BODY_KEYS if value.get(k)), "")
        if name or body:
            return f"{name} — {body}" if name and body else name or body
        return " · ".join(_plain(v) for v in value.values() if v not in (None, ""))
    if isinstance(value, (list, tuple)):
        return " · ".join(_plain(v) for v in value if v not in (None, ""))
    return str(value)


def _t(value: Any) -> str:
    """글 — 이스케이프하되 <u> <b> <mark> 만 살린다."""
    text = _html.escape(_plain(value), quote=False)
    return _ALLOWED_TAGS.sub(lambda m: f"<{m.group(1)}{m.group(2)}>", text)


def _attr_on(item: Any) -> str:
    return " on" if isinstance(item, dict) and item.get("on") else ""


_RATIOS = {"16:9": "16 / 9", "4:3": "4 / 3", "1:1": "1 / 1", "3:4": "3 / 4"}


def _slot(slots: list[str], label: Any, kind: str) -> str:
    """사진 자리 — 사람이 화면에서 사진을 끌어다 넣는 칸(10-25 대표). 장 안에서 s1 · s2 … 순서로 이름을 붙인다."""
    slots.append(str(label or ""))
    attr = _html.escape(str(label or ""), quote=True)
    return f'data-slot="s{len(slots)}" data-label="{attr}">[{kind}: {_t(label)}]'


def _render_card(card: dict[str, Any], slots: list[str] | None = None, counters: dict[str, int] | None = None) -> str:
    """부품 하나를 그린다. `counters` 는 **장 하나** 안에서 번호 붙는 부품이 이어 세는 값이다(`render` 가 장마다 새로 만든다).

    ★ 10-28 장표 재측정(실제 판 a5fb5da7 · grove 결): 요점(points)이 한 장에 셋 쌓이면 부품마다 1부터 다시 세어 「01 01 01」이 됐다.
      번호는 부품이 아니라 **장**이 센다 — 부품이 무엇이든 번호 붙이는 부품(지금은 points)은 이 값을 받아 이어 센다.
      CSS 로 번호를 붙이는 단계(steps)도 같은 규칙이다 — 장 단위 `counter-reset`(`slide_themes/parts/common.css`).
    """
    slots = [] if slots is None else slots
    counters = {} if counters is None else counters
    name = card["part"]
    role = " anchor" if card.get("role") == "anchor" else ""
    title = f'<h3 class="cap-title">{_t(card["title"])}</h3>' if card.get("title") and name not in {"panel"} else ""
    if name == "text":
        quote = f'<p class="pz-quote">{_t(card["quote"])}</p>' if card.get("quote") else ""
        body = f'<p class="pz-p">{_t(card["text"])}</p>' if card.get("text") else ""
        items = card.get("items") or []
        lst = ('<ul class="dash">' + "".join(f"<li>{_t(item)}</li>" for item in items) + "</ul>") if items else ""
        return f'<div class="pz pz-text{role}">{title}{quote}{body}{lst}</div>'
    if name == "stat":
        tone = {"navy": " navy", "loss": " loss-tone"}.get(str(card.get("tone") or ""), "")
        unit = f'<small>{_t(card["unit"])}</small>' if card.get("unit") else ""
        label = f'<span class="label">{_t(card["label"])}</span>' if card.get("label") else ""
        note = f'<p class="pz-note">{_t(card["note"])}</p>' if card.get("note") else ""
        return f'<div class="pz pz-stat{tone}{role}">{title}{label}<span class="n">{_t(card["value"])}{unit}</span>{note}</div>'
    if name == "metrics":
        cells = []
        for item in card["items"]:
            item = item if isinstance(item, dict) else {"value": item}
            unit = f'<small>{_t(item["unit"])}</small>' if item.get("unit") else ""
            shot = f'<div class="pz-shot" {_slot(slots, item["evidence"], "증빙")}</div>' if item.get("evidence") else ""
            cells.append(f'<div class="pz-metric"><span class="label">{_t(item.get("label", ""))}</span>'
                         f'<span class="n">{_t(item.get("value", ""))}{unit}</span><p class="pz-note">{_t(item.get("note", ""))}</p>{shot}</div>')
        return f'<div class="pz pz-metrics{role}" style="--k:{len(cells)}">{title}<div class="pz-row">{"".join(cells)}</div></div>'
    if name == "bars":
        items = [item for item in card["items"] if isinstance(item, dict)]
        values = [_number(item.get("value")) or 0.0 for item in items]
        top = max(values) or 1.0
        unit = _t(card.get("unit") or "")
        bars = "".join(
            f'<div class="pz-bar{_attr_on(item)}"><span class="v n">{_t(item.get("label") or _fmt(value))}</span>'
            f'<i style="--h:{max(value / top * 100, 1.2):.1f}%"></i><b>{_t(item.get("name", ""))}</b></div>'
            for item, value in zip(items, values))
        note = f'<p class="pz-note">{_t(card["note"])}</p>' if card.get("note") else ""
        scale = f'<span class="pz-scale">단위: {unit} · 같은 눈금</span>' if unit else '<span class="pz-scale">같은 눈금</span>'
        return f'<div class="pz pz-bars{role}">{title}<div class="pz-bar-area">{bars}</div>{scale}{note}</div>'
    if name == "table":
        columns = card["columns"]
        rows = card["rows"]
        highlight = card.get("highlight")
        if highlight == "last":
            highlight = len(rows) - 1
        def _numeric_cell(cell: Any) -> bool | None:
            cleaned = re.sub(r"[%배원억만곳명개 ·,−\-–—+]", "", str(cell))
            return None if not cleaned else _number(cleaned) is not None
        numeric = []
        for i in range(len(columns)):
            marks = [_numeric_cell(row[i]) for row in rows if isinstance(row, list) and i < len(row)]
            marks = [mark for mark in marks if mark is not None]
            numeric.append(bool(marks) and all(marks))
        head = "".join(f'<th class="{"num" if numeric[i] and i else ""}">{_t(col)}</th>' for i, col in enumerate(columns))
        body = ""
        for r, row in enumerate(rows):
            cells = "".join(f'<td class="{"num n" if numeric[i] and i else ""}">{_t(cell)}</td>'
                            for i, cell in enumerate(row if isinstance(row, list) else [row]))
            body += f'<tr class="{"us" if isinstance(highlight, int) and r == highlight else ""}">{cells}</tr>'
        return f'<div class="pz pz-table{role}">{title}<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    if name == "flow":
        arrows = card.get("arrows") or []
        parts = []
        for i, node in enumerate(card["nodes"]):
            node = node if isinstance(node, dict) else {"title": node}
            if i:
                label = _t(arrows[i - 1]) if i - 1 < len(arrows) else ""
                parts.append(f'<div class="pz-arrow">{label}</div>')
            foot = f'<span class="foot">{_t(node["foot"])}</span>' if node.get("foot") else ""
            text = f'<p>{_t(node["text"])}</p>' if node.get("text") else ""
            parts.append(f'<div class="pz-node{_attr_on(node)}"><span class="label">{_t(node.get("label", ""))}</span>'
                         f'<b>{_t(node.get("title", ""))}</b>{text}{foot}</div>')
        return f'<div class="pz pz-flow{role}">{title}<div class="pz-flow-row">{"".join(parts)}</div></div>'
    if name == "steps":
        items = "".join(f'<li class="{"on" if isinstance(item, dict) and item.get("on") else ""}">{_t(item.get("title", "") if isinstance(item, dict) else item)}'
                        f'{("<small>" + _t(item["text"]) + "</small>") if isinstance(item, dict) and item.get("text") else ""}</li>'
                        for item in card["items"])
        return f'<div class="pz pz-steps{role}">{title}<ol>{items}</ol></div>'
    if name == "stages":
        stages = [stage for stage in card["stages"] if isinstance(stage, dict)]
        rows = [row for row in (card.get("rows") or []) if isinstance(row, dict)]
        head = "<div></div>" + "".join(f'<div class="stage{_attr_on(stage)}"><span class="label">{_t(stage.get("label", ""))}</span>'
                                       f'<b>{_t(stage.get("title", ""))}</b></div>' for stage in stages)
        body = ""
        for row in rows:
            cells = list(row.get("cells") or [])[: len(stages)]
            cells += [""] * (len(stages) - len(cells))
            body += f'<div class="rowname">{_t(row.get("name", ""))}</div>' + "".join(
                f'<div class="cell{_attr_on(stage)}">{_t(cell)}</div>' for stage, cell in zip(stages, cells))
        return (f'<div class="pz pz-stages{role}" style="--k:{len(stages)};--r:{len(rows)}">{title}'
                f'<div class="pz-stage-grid">{head}{body}</div></div>')
    if name == "pair":
        def side(data: Any, on: bool) -> str:
            data = data if isinstance(data, dict) else {"value": data}
            year = f'<span>{_t(data["year"])}</span>' if data.get("year") else ""
            return (f'<div class="pz-state{" on" if on else ""}"><div class="head"><b>{_t(data.get("label", ""))}</b>{year}</div>'
                    f'<p class="whole">{_t(data.get("text", ""))}</p><div class="ours"><span class="n">{_t(data.get("value", ""))}</span>'
                    f'<span>{_t(data.get("sub", ""))}</span></div></div>')
        return f'<div class="pz pz-pair{role}">{title}<div class="pz-pair-row">{side(card["before"], False)}<div class="pz-to"></div>{side(card["after"], True)}</div></div>'
    if name == "panel":
        label = f'<span class="label">{_t(card["label"])}</span>' if card.get("label") else ""
        text = f'<p>{_t(card["text"])}</p>' if card.get("text") else ""
        return f'<div class="pz pz-panel{role}">{label}<span class="n">{_t(card["value"])}</span>{text}</div>'
    if name == "calc":
        quote = f'<p class="pz-quote">{_t(card["quote"])}</p>' if card.get("quote") else ""
        items = "".join(f'<div class="pz-calc-item"><b>{_t(item.get("title", ""))}</b>{_t(item.get("expr", ""))}'
                        f'<span class="res">= {_t(item.get("result", ""))}</span></div>'
                        for item in card["items"] if isinstance(item, dict))
        assume = f'<p class="pz-assume">{_t(card["assume"])}</p>' if card.get("assume") else ""
        return f'<div class="pz pz-calc{role}">{title}{quote}{items}{assume}</div>'
    if name == "people":
        sub = f'<small>{_t(card["sub"])}</small>' if card.get("sub") else ""
        head = f'<h3 class="cap-title">{_t(card.get("title", ""))}{sub}</h3>' if card.get("title") else ""
        people = "".join(f'<div class="pz-person"><b>{_t(p.get("name", ""))}</b><span class="role">{_t(p.get("role", ""))}</span>'
                         f'{_t(p.get("text", ""))}{("<em>" + _t(p["nick"]) + "</em>") if p.get("nick") else ""}</div>'
                         for p in card["items"] if isinstance(p, dict))
        return f'<div class="pz pz-people{role}" style="--k:{len(card["items"])}">{head}<div class="pz-row">{people}</div></div>'
    if name == "points":
        start = int(counters.get("points", 0)) + 1
        shown = [p for p in card["items"] if isinstance(p, dict)]
        counters["points"] = start - 1 + len(shown)
        items = "".join(f'<div class="pz-point"><span class="n">{i:02d}</span><b class="t">{_t(p.get("title", ""))}</b>'
                        f'{("<span class=sub>" + _t(p["sub"]) + "</span>") if p.get("sub") else ""}<p>{_t(p.get("text", ""))}</p></div>'
                        for i, p in enumerate(shown, start))
        return f'<div class="pz pz-points{role}" style="--k:{len(card["items"])}">{title}<div class="pz-row">{items}</div></div>'
    if name == "photo":
        ratio = _RATIOS.get(str(card.get("ratio") or ""), "")
        style = f' style="aspect-ratio:{ratio}"' if ratio else ""
        caption = f"<figcaption>{_t(card['caption'])}</figcaption>" if card.get("caption") else ""
        return f'<figure class="pz pz-photo{role}">{title}<div class="pz-photo-box"{style} {_slot(slots, card["label"], "사진")}</div>{caption}</figure>'
    if name == "kv":
        rows = "".join(f"<dt>{_t(pair[0])}</dt><dd>{_t(pair[1])}</dd>" for pair in card["items"]
                       if isinstance(pair, (list, tuple)) and len(pair) >= 2)
        return f'<div class="pz pz-kv{role}">{title}<dl>{rows}</dl></div>'
    raise PartsError(f"part_unknown: {name}")


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if value == int(value) else f"{value:,.1f}"


def render(spec: dict[str, Any]) -> str:
    """검사를 통과한 조립표 → <section class="slide ir-parts"> 조각."""
    layout = str(spec.get("layout") or "1")
    widths = _widths(layout) or [1]
    head = _t(spec.get("head", ""))
    sub = f' <small>_ {_t(spec["sub"])}</small>' if spec.get("sub") else ""
    lede_raw = spec.get("lede") or []
    lines = lede_raw if isinstance(lede_raw, list) else re.split(r"\s*(?:\n|\|)\s*", str(lede_raw))
    lede = "<br>".join(_t(line) for line in lines if str(line).strip())
    lede_html = f'<p class="ir-lede">{lede}</p>' if lede else ""
    slots: list[str] = []
    counters: dict[str, int] = {}  # 장 하나 안에서 번호가 이어진다(위 `_render_card` 주석)
    cols = "".join(f'<div class="pz-col">{"".join(_render_card(card, slots, counters) for card in col)}</div>' for col in spec["cols"])
    grid = f'<div class="pz-grid" style="grid-template-columns:{" ".join(f"minmax(0,{w}fr)" for w in widths)}">{cols}</div>'
    bottom = f'<div class="pz-bottom">{_t(spec["bottom"])}</div>' if spec.get("bottom") else ""
    source = spec.get("source") or ""
    unit = spec.get("unit") or ""
    foot = f'<p class="ir-src"><span>{_t(source)}</span><span>{_t(unit)}</span></p>' if source or unit else ""
    return (f'<section class="slide ir-parts pz-slide"><h2 class="ir-head">{head}{sub}</h2>{lede_html}'
            f'<div class="ir-rule"></div>{grid}{bottom}{foot}</section>')


def signature(spec: dict[str, Any]) -> str:
    """이웃한 장이 같은 짜임인지 가르는 이름 — 칸 나눔 + 부품 순서."""
    names = "+".join(str(card.get("part")) for col in spec.get("cols") or [] for card in col if isinstance(card, dict))
    return f"parts:{spec.get('layout') or '1'}:{names}"


#: 조립표 머리 칸 — 괄호가 하나 잘못 닫혀 칸 목록(cols) 안으로 흘러든 「이름, 값」 짝을 되살릴 때만 쓴다.
_HEAD_KEYS = ("head", "sub", "lede", "layout", "source", "unit", "bottom")


def repair(spec: dict[str, Any]) -> list[str]:
    """정답이 하나로 정해지는 모양 잘못은 코드가 고친다 — 사다리 0~1단(`fix`, 2026-10-26 최소 개입 설계 ①).

    지난 장표 22판의 「조립표 잘못」 7번 중 4번이 이 모양이었다(e5844c85 · d4df8a28): JSON 괄호를 하나 잘못 닫아
    머리 칸이 칸 목록 안으로 들어갔다 — `cols: [[부품…], "head", "경쟁", "layout", "1", …]`. 돌려보내면 걸음 하나를 쓴다.
    칸 목록에서 목록만 칸으로 두고, 남은 글을 「아는 머리 이름, 값」 짝으로 읽어 비어 있는 머리 칸에만 넣는다.
    짝이 어긋날 수 있으니 무엇을 고쳤는지 돌려준다 — 결과에 실려 모델이 본다(1단: 고치고 알린다).
    """
    fixed: list[str] = []
    cols = spec.get("cols")
    # kv(이름 : 값)가 짝 대신 {title, text} 객체로 · 한 겹 더 싸여 왔다 — 짝으로 편다(10-26 소개 판 be78277a 3 · 7번 장).
    for col in cols if isinstance(cols, list) else []:
        for card in col if isinstance(col, list) else []:
            if isinstance(card, dict) and card.get("part") == "kv" and isinstance(card.get("items"), list):
                flat: list[Any] = []
                for item in card["items"]:
                    if isinstance(item, list) and item and all(isinstance(x, dict) for x in item):
                        flat.extend(item)
                    else:
                        flat.append(item)
                pairs = []
                changed = flat != card["items"]
                for item in flat:
                    if isinstance(item, dict):
                        name = next((str(item[k]) for k in _NAME_KEYS if item.get(k)), "")
                        body = next((str(item[k]) for k in _BODY_KEYS if item.get(k)), "")
                        pairs.append([name, body])
                        changed = True
                    else:
                        pairs.append(item)
                if changed:
                    card["items"] = pairs
                    fixed.append("이름 : 값 부품이 짝 대신 객체로 와서 「이름, 값」 짝으로 폈다")
    if isinstance(cols, list) and cols and any(isinstance(col, dict) for col in cols) and not any(isinstance(col, list) for col in cols):
        spec["cols"] = [[col for col in cols if isinstance(col, dict)]]
        fixed.append("cols 가 한 겹이라 한 칸으로 감쌌다")
        cols = spec["cols"]
    def clean(item: Any) -> str:
        return str(item).strip().strip("*{}:\" ").strip()

    def all_text(col: Any) -> bool:
        return isinstance(col, list) and bool(col) and all(isinstance(item, (str, int, float)) for item in col)

    messy = isinstance(cols, list) and any(isinstance(col, list) for col in cols) and (
        any(not isinstance(col, list) for col in cols) or any(all_text(col) for col in cols))
    if messy:
        new_cols: list[list[Any]] = []
        restored: list[str] = []
        revived = dropped = 0
        i = 0
        while i < len(cols):
            item = cols[i]
            key = clean(item) if isinstance(item, (str, int, float)) else ""
            if key in _HEAD_KEYS and i + 1 < len(cols):
                value = cols[i + 1]
                # 머리 이름 바로 뒤의 값 — 글이면 그대로, 글 목록이면(lede) 목록으로.
                if (isinstance(value, (str, int, float)) and clean(value) and clean(value) not in _HEAD_KEYS) or all_text(value):
                    if not spec.get(key):
                        spec[key] = [clean(v) for v in value] if isinstance(value, list) else clean(value)
                        restored.append(key)
                    i += 2
                    continue
            if isinstance(item, list) and any(isinstance(card, dict) for card in item):
                new_cols.append([card for card in item if isinstance(card, dict)])
            elif all_text(item):
                # 껍데기가 벗겨진 글 부품(「['items', '우리 고객 412곳 …']」) — 버리지 않고 글 부품으로 되살린다.
                lines = [clean(v) for v in item if clean(v) and clean(v) not in {"items", "text", "part"}]
                if lines:
                    new_cols.append([{"part": "text", "items": lines}])
                    revived += 1
            elif isinstance(item, (str, int, float)) and clean(item):
                dropped += 1
            i += 1
        spec["cols"] = new_cols
        notes = []
        if restored:
            notes.append(f"머리 칸 {' · '.join(restored)} 를 되살렸다(맞는지 확인)")
        if revived:
            notes.append(f"껍데기가 벗겨진 글 {revived}칸을 글 부품으로 되살렸다")
        if dropped:
            notes.append(f"칸 목록 안의 조각 글 {dropped}개를 뺐다")
        fixed.append("조립표 괄호가 어긋나 칸 목록을 고쳤다 — " + " · ".join(notes or ["모양만 바로잡음"]))
    return fixed


def build(raw: Any) -> tuple[str, str, list[str]]:
    """조립표(JSON 문자열 · 객체) → (조각 html, 짜임 이름, 쓴 부품). 잘못이 있으면 PartsError 로 한꺼번에 알린다."""
    html, sig, names, _fixed = build_with_fixes(raw)
    return html, sig, names


def build_with_fixes(raw: Any, theme: str | None = None, index: int = 0, total: int = 0) -> tuple[str, str, list[str], list[str]]:
    """`build` + 코드가 고친 것(`repair`). 고친 것은 장표 손 결과의 `fixed` 에 실린다.

    표지 · 마무리 조립표(`{"frame": "cover", …}` · 칸 목록 없이 title 만 있는 것)는 `slide_frames` 가 결의 짜임 · 장식으로 그린다.
    """
    spec = parse(raw)
    from . import slide_frames

    if slide_frames.is_frame(spec, index, total):
        return slide_frames.build_frame(spec, theme, index, total)
    fixed = repair(spec)
    layout_before = str(spec.get("layout") or "1")
    problems = validate(spec)
    if problems:
        raise PartsError("parts_invalid: " + " / ".join(problems))
    if str(spec.get("layout") or "1") != layout_before:
        fixed.append(f"칸 나눔 「{layout_before}」 → 칸 수에 맞춰 「{spec['layout']}」")
    names = [str(card.get("part")) for col in spec["cols"] for card in col]
    return render(spec), signature(spec), names, fixed


# ── 사진 자리 (2026-10-25 대표 「사진은 사용자가 실시간으로 넣을 수 있게」) ─────────────────────────
_SLOT_TAG = re.compile(r'<(div)\b([^>]*\bdata-slot="(s\d+)"[^>]*)>(.*?)</div>', re.S)
_LABEL = re.compile(r'data-label="([^"]*)"')


def slots_of(html: str) -> list[dict[str, Any]]:
    """장 HTML 의 사진 자리 — [{id, label, filled}]."""
    found = []
    for match in _SLOT_TAG.finditer(html or ""):
        label = _LABEL.search(match.group(2))
        found.append({"id": match.group(3), "label": _html.unescape(label.group(1)) if label else "",
                      "filled": "<img" in match.group(4)})
    return found


#: 틀째 장(부품이 없는 결)에서 모델이 사진 자리로 적은 칸 — 「[사진: 매장 전경]」 · 「[ 제품 화면 사진 ]」 · 「[스크린샷]」.
#: 첫 소개 판(891b5d6a · paper 결)은 사진 자리를 글자로만 박아 사람이 끌어다 넣을 칸이 없었다.
_PHOTO_MARK = re.compile(
    r"^\s*\[\s*(?:(?:사진|이미지|그림|스크린샷|캡처)\s*[:：]\s*)?([^\[\]]{0,40}?(?:사진|이미지|스크린샷|캡처|로고)?[^\[\]]{0,40}?)\s*\]"
)
_PHOTO_WORD = re.compile(r"사진|이미지|스크린샷|캡처|로고")
_LEAF_BOX = re.compile(r"<(div|li|figure)\b((?:(?!data-slot)[^>])*)>((?:(?!<(?:div|li|figure|ul|ol|section)\b).)*?)</\1>", re.S | re.I)
_PHOTO_CSS = ("<style data-sonjari-slot>.ph-slot{border:2px dashed currentColor;border-radius:8px;opacity:.72;display:flex;"
              "align-items:center;justify-content:center;text-align:center;min-height:5.5em;padding:.6em;box-sizing:border-box}"
              ".ph-slot.has-photo{opacity:1;border:0;padding:0;overflow:hidden}"
              ".ph-slot img{display:block;width:100%;height:100%;object-fit:cover}</style>")


def mark_photo_slots(html: str) -> str:
    """틀째 장의 「[사진: …]」 칸을 사람이 사진을 끌어다 넣는 자리(data-slot)로 바꾼다 (2026-10-25).

    칸 안의 글이 대괄호 표시로 **시작**하고 그 안에 사진 낱말이 있을 때만 바꾼다 — 본문 문장 속 대괄호는 건드리지 않는다.
    이미 자리가 있는 장(부품 장)은 번호를 이어 붙인다. 바꾼 칸이 있으면 점선 모양 스타일을 한 번 끼운다.
    """
    text = str(html or "")
    taken = len(slots_of(text))
    count = [taken]

    def swap(match: re.Match) -> str:
        tag, attrs, inner = match.group(1), match.group(2), match.group(3)
        plain = _html.unescape(re.sub(r"<[^>]+>", " ", inner))
        mark = _PHOTO_MARK.match(plain)
        if not mark or not _PHOTO_WORD.search(mark.group(0)):
            return match.group(0)
        label = " ".join(mark.group(1).split()) or "사진"
        count[0] += 1
        slot = f'data-slot="s{count[0]}" data-label="{_html.escape(label, quote=True)}">[사진: {_html.escape(label)}]'
        if tag.lower() == "div":
            if re.search(r'class="', attrs):
                attrs = re.sub(r'class="([^"]*)"', lambda m: f'class="{m.group(1)} ph-slot"', attrs, count=1)
            else:
                attrs += ' class="ph-slot"'
            return f"<div{attrs} {slot}</div>"
        return f'<{tag}{attrs}><div class="ph-slot" {slot}</div></{tag}>'

    out = _LEAF_BOX.sub(swap, text)
    if count[0] > taken and "data-sonjari-slot" not in out:
        out = re.sub(r"(</head\s*>)", _PHOTO_CSS + r"\1", out, count=1, flags=re.I) if re.search(r"</head\s*>", out, re.I) else _PHOTO_CSS + out
    return out


def put_photo(html: str, slot: str, data_uri: str, alt: str = "") -> str:
    """사진 자리 하나에 그림을 박는다(자리 표시 글 → <img>). 자리가 없으면 PartsError."""
    def swap(match: re.Match) -> str:
        if match.group(3) != slot:
            return match.group(0)
        attrs = match.group(2)
        attrs = re.sub(r'class="([^"]*)"', lambda m: f'class="{m.group(1)} has-photo"' if "has-photo" not in m.group(1) else m.group(0), attrs, count=1)
        return f'<div{attrs}><img src="{data_uri}" alt="{_html.escape(alt)}"></div>'
    out, count = _SLOT_TAG.subn(swap, html or "")
    if not any(item["id"] == slot for item in slots_of(html)):
        raise PartsError(f"slot_unknown: {slot}")
    return out
