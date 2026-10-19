from __future__ import annotations

import hashlib
import gc
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from .config import JarvisConfig
from .dates import KST, DateRewrite, RequestedStay, requested_stay, rewrite_date_params
from .search_atlas import (
    MIN_ROWS as SEARCH_ATLAS_MIN_ROWS,
    SearchAtlas,
)
from .human_gate import (
    CAPTCHA_SELECTOR,
    PAYMENT_CARD_FRAME_MARKERS,
    PAYMENT_FIELD_SELECTOR,
    PAYMENT_FRAME_HOSTS,
    allows_local_test_secret,
)
from . import structured_data as _structured
from .site_traits import SiteTraits
from . import page_data as _page_data
from . import site_sources as _site_sources
from . import layout_probe as _layout_probe
from . import page_look as _page_look
from . import search_boxes as _search_boxes
from .models import RiskLevel
from .proof import ProofSpec, finalize_proof, same_fingerprint
from .serp import canonical_url, collect_results, opaque_outbound, unwrap_redirect
from .tool_gateway import InverseSpec, ToolGateway, ToolSpec, UndoUnverified


# 완료 화면에도 CAPTCHA 공급자의 숨은 iframe·response 노드가 남을 수 있다. 사람에게
# 보이지 않는 잔해는 더 이상 문이 아니다. 쉼표 목록의 각 항목에 Playwright의
# ``:visible``을 따로 붙여야 마지막 항목에만 적용되는 CSS 실수를 피한다.
_VISIBLE_CAPTCHA_SELECTOR = ", ".join(
    f"{item.strip()}:visible" for item in CAPTCHA_SELECTOR.split(",")
)

_VISIBLE_PAYMENT_SELECTOR = ", ".join(
    f"{item.strip()}:visible" for item in PAYMENT_FIELD_SELECTOR.split(",")
)
#: 결제 대행사 창을 문으로 칠 최소 크기 — 상품 페이지의 작은 「간편결제」 단추는 문이 아니다.
_PAYMENT_WINDOW_MIN = (250, 200)

# Naver bounces every logged-out request here, keeping the destination in the
# query string. Checking the host is what tells "not signed in" apart from
# "the editor changed its markup" -- the two produce identical symptoms
# otherwise, and we already chased the wrong one once.
_NAVER_LOGIN_HOST = "nid.naver.com"

# 전면 작업이 배경 일에게 양보하는 **천장.** 평소에는 배경 일이 스스로 적어 둔
# 마감(`deadline_at`)이 먼저 오므로 이 값은 안 쓰인다 — 그 마감이 터무니없을 때만
# 쓰는 안전장치다.
#
# 지금 있는 배경 일과 그 예산:
#     browser_pump        250ms 돌고 250ms 쉼
#     browser_live_frame  6.0초 (`_FRAME_TIMEOUT_SEC`, 스크린샷 자체는 4초)
#
# 8초면 둘 다 덮는다. 배경 일이 새로 생겨 예산이 이보다 크면, 그 일은 여기서
# 잘려 전면 작업이 튕기기 시작한다 — 그때는 이 값이 아니라 **그 일의 예산**을
# 먼저 의심할 것(고정 상한을 올리는 것은 원인이 아니라 증상을 미는 것이다).
_BACKGROUND_YIELD_CAP_SEC = 8.0

# The cookies Naver's own login sets. Only their presence is ever read -- never
# a value -- so this answers "signed in?" without touching the credentials.
_NAVER_SESSION_COOKIES = frozenset({"NID_AUT", "NID_SES"})

# 스마트에디터는 마크다운을 모른다. `**굵게**` 도 `### 제목` 도 그냥 글자로 찍힌다
# (2026-08-05 사용자 블로그 화면에서 실물 확인). 그래서 넣기 전에 평문으로 바꾼다.
#
# 보기 좋으라고 하는 게 아니라 **안전 때문**이기도 하다: 줄머리의 `- ` 와 `1. ` 은
# 에디터의 자동 목록 변환을 깨우고, 그 변환이 DOM 을 다시 그리는 사이에도 타이핑은
# 계속 들어간다. 같은 날 979자 글이 문단 단위로 뒤섞여 들어간 것이 이것으로 보인다
# (보낸 원문은 순서가 멀쩡했다 — 편집기가 뒤섞었다).
_MD_FENCE = re.compile(r"^\s*```.*$")
_MD_HEADING = re.compile(r"^\s*#{1,6}\s*")
_MD_QUOTE = re.compile(r"^\s*>\s?")
_MD_RULE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
_MD_BULLET = re.compile(r"^(\s*)[-*+]\s+")
_MD_NUMBER = re.compile(r"^(\s*)(\d+)\.\s+")
_MD_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)[^)]*\)")
_MD_EMPHASIS = re.compile(r"(\*\*\*|\*\*|__|`)")
# 눈에 안 보이는데 글에 남는 것들: BOM(U+FEFF), 제로폭 공백, 줄바꿈 없는 공백.
# 리치 에디터에서 복사·붙여넣기를 거치면 잘 따라붙고, 검색에도 안 걸리게 만든다.
_INVISIBLE = re.compile(r"[﻿​-‍⁠]")


def markdown_to_editor_text(body: str) -> str:
    """마크다운으로 쓰인 본문을 리치 에디터에 그대로 넣을 평문으로.

    빼기만 하고 더하지 않는다 — 문장은 손대지 않고 기호만 걷어낸다. 목록은 `·` 로,
    번호는 `1)` 로 바꾼다(자동 변환을 깨우지 않으면서 목록으로 읽히는 형태다).
    """
    lines: list[str] = []
    for raw in _INVISIBLE.sub("", body or "").replace("\xa0", " ").splitlines():
        if _MD_FENCE.match(raw) or _MD_TABLE_RULE.match(raw):
            continue
        line = _MD_RULE.sub("", raw)
        heading = bool(_MD_HEADING.match(line))
        line = _MD_HEADING.sub("", line)
        line = _MD_QUOTE.sub("", line)
        if not heading:
            # 제목 줄의 "## 2. 핵심 전략" 은 목록이 아니다. 여기를 안 갈라 놓으면
            # 그 "2." 까지 "2)" 로 바뀌어 원문에 없던 번호 매김이 생긴다.
            line = _MD_BULLET.sub(r"\1· ", line)
            line = _MD_NUMBER.sub(r"\1\2) ", line)
        line = _MD_LINK.sub(r"\1 (\2)", line)
        line = _MD_EMPHASIS.sub("", line)
        lines.append(line.rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _comparable(text: str) -> str:
    """읽어온 본문과 넣은 본문을 견주기 위한 형태. 공백·제로폭 문자만 지운다."""
    return re.sub(r"[\s​﻿\xa0]+", "", text or "")


# 편집기가 다 떴다는 신호. 스마트에디터가 부팅을 마쳐야 생기는 것들이라, 이게 보이면
# 그 프레임이 편집기다. 한 줄에 콤마로 묶지 않고 따로 두는 이유: 하나씩 세어야 어느
# 것이 있었는지가 실패 메시지에 남는다.
_NAVER_EDITOR_MARKERS = (
    ".se-title-text",
    ".se-documentTitle",
    ".se-text-paragraph",
)

_NAVER_INTERVENTION_MARKERS = (
    "보안문자",
    "캡차",
    "captcha",
    "비정상적인 접근",
    "로그인이 필요",
    "아이디를 잊으셨나요",
)


# What counts as an operable element anywhere on the web. Kept in one place
# because the snapshot, the probe and the vision candidate list must agree on
# what they are looking at -- a candidate the model can see but the snapshot
# never listed is a candidate nothing can click.
_INTERACTIVE = (
    "a,button,input,textarea,select,summary,"
    "[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],"
    "[role=radio],[role=combobox],[role=switch],[contenteditable=true],"
    # ★ 태그와 role 만 보면 **손으로 만든 버튼**이 통째로 안 보인다.
    #
    # 2026-08-13 실측(다나와 검색결과): 본문 텍스트에는 "인기순"이 있는데 조작 가능
    # 요소 93 개 안에는 정렬이 하나도 없었다. 젬마는 "낮은 가격순 정렬 버튼"부터
    # "정렬 기준"까지 일곱 가지 표현으로 찾고 스크롤까지 했다 — 판단이 모자란 게
    # 아니라 **아예 안 보여 줬다.**
    #
    # `onclick` 이 달렸거나 `tabindex` 로 초점을 받을 수 있으면 사람이 누르라고
    # 만든 것이다. 이름표(정렬·탭·필터)에 기대지 않는 것이 중요하다 — 낱말 목록은
    # 오늘 하루에만 세 번 샜다.
    "[onclick],[tabindex]:not([tabindex='-1'])"
)

# ★ 섀도 DOM (2026-09-17). MS 스토어(apps.microsoft.com)에서 16걸음을 헤매고 「못 찾았다」로 끝난 판의 원인.
#   실측(헤드리스): 그 사이트는 누를 것·글자가 **전부 웹 컴포넌트의 섀도 DOM 안**에 있다 — 일반 DOM 상호작용 요소 0개,
#   검색 결과 페이지 `body.innerText` 0자, 섀도 안 앱 링크 40개. 우리 페이지 안 코드는 전부
#   `document.querySelectorAll` 이라 섀도 경계를 못 넘었다. 요소 수(`_operable_count`)만 Playwright 로케이터라 147 로
#   나와서, 「요소는 있는데 목록은 비었다」는 모순된 화면을 모델이 16걸음 동안 풀려고 했다.
#   사이트마다 셀렉터를 늘리지 않는다 — **열린 섀도 루트를 전부 모아 같은 질의를 돌리는** 도우미 하나를 조각마다 끼운다.
#   닫힌 섀도 루트·캔버스는 이걸로도 안 보인다 → `_why_empty` 가 「읽을 수 없는 구조」로 말하고 좌표 도구로 넘긴다.
_DEEP_DOM_PRELUDE = """
  const __deepRoots = (() => {
    const roots = [document];
    try {
      for (let i = 0; i < roots.length && roots.length < 2000; i++) {
        for (const el of roots[i].querySelectorAll('*')) { if (el.shadowRoot) roots.push(el.shadowRoot); }
      }
    } catch (e) {}
    return roots;
  })();
  const __deepAll = (sel) => {
    if (__deepRoots.length === 1) return Array.from(document.querySelectorAll(sel));
    // 섀도 루트에는 body 가 없다 — 'body *' 같은 선택자는 루트 안에서는 앞머리를 떼고 돌린다.
    const inner = String(sel).split(',').map((part) => part.trim().replace(/^body\\s+/, '')).join(', ');
    const out = [];
    for (const root of __deepRoots) {
      let found = [];
      try { found = root.querySelectorAll(root === document ? sel : inner); } catch (e) { continue; }
      for (const el of found) out.push(el);
    }
    return out;
  };
  // 섀도 루트 맨 위 요소의 부모는 null 이다 — 호스트로 넘어가야 조상·묶음 판정이 이어진다.
  const __parentOf = (el) => (el && (el.parentElement || (el.parentNode && el.parentNode.host))) || null;
"""

_DEEP_PARENT = re.compile(r"([A-Za-z_$][\w$]*)\.parentElement\b")


def _deep_js(script: str) -> str:
    """페이지 안 코드가 **열린 섀도 DOM 안까지** 보게 한다.

    화살표 함수 본문 첫 줄에 도우미를 넣고, `document.querySelectorAll(` 을 `__deepAll(` 로, `x.parentElement` 를
    `__parentOf(x)` 로 바꾼다. 섀도 루트가 없는 보통 페이지는 `__deepAll` 이 원래 질의 그대로라 결과·순서가 같다.
    """
    head, sep, body = script.partition("=> {")
    if not sep:
        raise ValueError("deep_js_needs_block_arrow")
    body = body.replace("document.querySelectorAll(", "__deepAll(")
    body = _DEEP_PARENT.sub(r"__parentOf(\1)", body)
    return head + sep + _DEEP_DOM_PRELUDE + body


# 섀도 DOM 안 글자까지 **그려지는 순서대로** 읽는다. 섀도 루트가 없으면 null — 보통 페이지는 여기서 비용을 안 쓴다.
# 호스트는 섀도 루트만 따라가고, <slot> 에서는 거기 꽂힌 바깥 노드를 읽는다(안 꽂힌 바깥 자식은 화면에 없다).
_DEEP_TEXT_JS = _deep_js("""(maxChars) => {
  if (__deepRoots.length === 1) return null;
  const skip = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'svg', 'SVG']);
  const lines = [];
  let used = 0;
  const hidden = (el) => {
    try { const st = getComputedStyle(el); return st.display === 'none' || st.visibility === 'hidden'; } catch (e) { return false; }
  };
  const visit = (node) => {
    if (used > maxChars) return;
    if (node.nodeType === 3) {
      const t = node.textContent.replace(/\\s+/g, ' ').trim();
      if (t) { lines.push(t); used += t.length + 1; }
      return;
    }
    if (node.nodeType !== 1 && node.nodeType !== 11) return;
    if (node.nodeType === 1) {
      if (skip.has(node.tagName) || hidden(node)) return;
      if (node.tagName === 'SLOT') {
        const assigned = node.assignedNodes({ flatten: true });
        for (const child of (assigned.length ? assigned : node.childNodes)) visit(child);
        return;
      }
      if (node.shadowRoot) { for (const child of node.shadowRoot.childNodes) visit(child); return; }
    }
    for (const child of node.childNodes) visit(child);
  };
  visit(document.body || document.documentElement);
  return { text: lines.join('\\n'), roots: __deepRoots.length, light_chars: (document.body ? document.body.innerText.length : 0) };
}""")

# ★ 가상 스크롤 목록(2026-09-18). 긴 채용·쇼핑 목록은 **보이는 줄만** DOM 에 두고 내리면 앞줄을 지운다 — 링크 수가
#   안 늘어 「더 없다」로 멈췄고, 끝으로 한 번에 뛰면 중간 줄을 통째로 건너뛴다. 목록이 창이 아니라 안쪽 칸에서
#   스크롤되는 경우가 흔해 **링크를 제일 많이 품은 스크롤 칸**을 찾아 그 칸을 한 칸씩 내린다.
_SCROLLER_JS = _deep_js("""() => {
  for (const old of document.querySelectorAll('[data-jarvis-scroller]')) old.removeAttribute('data-jarvis-scroller');
  let best = null, bestLinks = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (el.clientHeight < 200 || el.scrollHeight <= el.clientHeight + 150) continue;
    const oy = getComputedStyle(el).overflowY;
    if (oy !== 'auto' && oy !== 'scroll') continue;
    const links = el.querySelectorAll('a[href]').length;
    if (links > bestLinks) { best = el; bestLinks = links; }
  }
  if (best) best.setAttribute('data-jarvis-scroller', '1');
  return { container: !!best, links: bestLinks };
}""")
_STEP_SCROLL_JS = _deep_js("""(fraction) => {
  const marked = document.querySelectorAll('[data-jarvis-scroller]')[0];
  const el = marked || document.scrollingElement || document.documentElement;
  const before = el.scrollTop;
  const step = Math.max(120, Math.round((marked ? el.clientHeight : window.innerHeight) * fraction));
  el.scrollTop = before + step;
  return { moved: el.scrollTop - before, top: el.scrollTop, height: el.scrollHeight };
}""")

# 사이트가 공개한 출처(피드·공식 링크) — site_sources.py.
_SITE_SOURCES_JS = _deep_js(_site_sources.SOURCES_JS)

# 사이트가 박아 둔 JSON-LD·메타(structured_data.py). 섀도 루트 안에 둔 사이트도 있어 깊게 본다.
_STRUCTURED_DATA_JS = _deep_js(_structured.STRUCTURED_DATA_JS)

# ── 좌표 입력 확인·직접 채우기 (2026-09-29 밤, `_type_at` 단계) ─────────────────────────
# 포커스된 칸(열린 섀도 안까지) → 없으면 그 좌표의 칸. 닫힌 섀도처럼 못 보면 null(「모름」).
_FIELD_AT_POINT_FN = """
function __fieldAt(x, y) {
  const isField = (e) => e && (e.tagName === 'INPUT' || e.tagName === 'TEXTAREA' || e.isContentEditable);
  let a = document.activeElement;
  while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
  if (isField(a)) return a;
  let p = document.elementFromPoint(x, y);
  while (p && p.shadowRoot) { const inner = p.shadowRoot.elementFromPoint(x, y); if (!inner || inner === p) break; p = inner; }
  if (isField(p)) return p;
  const near = p && p.closest ? p.closest('input,textarea,[contenteditable="true"]') : null;
  if (near) return near;
  const inside = p && p.querySelectorAll ? [...p.querySelectorAll('input,textarea,[contenteditable="true"]')] : [];
  return inside.length === 1 ? inside[0] : null;  // 안에 칸이 하나뿐일 때만 — 여럿이면 어느 칸인지 모른다
}
"""
_FIELD_VALUE_AT_POINT_JS = "([x, y]) => {" + _FIELD_AT_POINT_FN + """
  const f = __fieldAt(x, y);
  if (!f) return null;
  return f.isContentEditable ? f.textContent : f.value;
}"""
_FILL_AT_POINT_JS = "([x, y, text]) => {" + _FIELD_AT_POINT_FN + """
  const f = __fieldAt(x, y);
  if (!f) return {ok: false, why: 'no_field_at_point'};
  if (f.type === 'password' || f.type === 'file') return {ok: false, why: 'sensitive_field'};
  if (f.disabled || f.readOnly) return {ok: false, why: 'field_disabled'};
  let value = text;
  if (f.type === 'number') value = String(text).replace(/[,\\s원₩$]/g, '');  // 「500,000」은 number 칸이 거절한다
  f.focus();
  if (f.isContentEditable) { f.textContent = value; }
  else {
    // 프레임워크(React 등)는 value 속성을 직접 바꾸면 모른다 — 원형의 setter 로 넣고 input·change 를 쏜다.
    const proto = f.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(f, value);
  }
  f.dispatchEvent(new Event('input', {bubbles: true}));
  f.dispatchEvent(new Event('change', {bubbles: true}));
  return {ok: true, value: f.isContentEditable ? f.textContent : f.value, tag: f.tagName, type: f.type || ''};
}"""


def _coerce_expect(arguments: dict[str, Any]) -> dict[str, Any]:
    """모델이 `expect` 를 객체가 아니라 **글자**로 보내면 풀어 본다. 못 풀면 뺀다 — 동작(클릭)은 살린다.

    2026-09-29 밤 한방 도전 W1: `"expect": "<{\\"value\\": \\"100,000\\"}"` 가 와서 세 자리가 `.get` 하다
    `'str' object has no attribute 'get'` 으로 클릭이 통째로 죽었다(두 번). 기대는 검증 보조다 — 그것 때문에 손이 죽으면 안 된다.
    """
    expect = arguments.get("expect")
    if expect is None or isinstance(expect, dict):
        return arguments
    parsed: Any = None
    if isinstance(expect, str):
        text = expect.strip()
        start = text.find("{")
        if start >= 0:
            try:
                parsed = json.loads(text[start:text.rfind("}") + 1])
            except ValueError:
                parsed = None
    if isinstance(parsed, dict):
        arguments["expect"] = parsed
    else:
        arguments.pop("expect", None)
    return arguments


def _typed_matches(text: str, value: str) -> bool:
    """친 글자가 칸 값에 들어 있나 — 쉼표·통화 기호는 숫자 칸이 지우기도 하니 빼고 본다.

    공백은 빼지 않는다: 키를 삼키는 칸에서 한글은 들어가고 **공백만 빠진**(「점심 식대」→「점심식대」) 판이 시험에서 나왔다.
    """
    squash = lambda s: re.sub(r"[,원₩$]", "", str(s))  # noqa: E731
    wanted = squash(text)
    return bool(wanted) and wanted in squash(value)

# 목록이 비었을 때 **왜** 비었는지 — 읽을 수 없는 구조인가(닫힌 섀도 DOM·캔버스).
_STRUCTURE_PROBE_JS = _deep_js("""() => {
  let custom = 0, customOpaque = 0;
  for (const el of __deepAll('*')) {
    if (!el.tagName.includes('-')) continue;
    custom += 1;
    const r = el.getBoundingClientRect();
    if (!el.shadowRoot && !el.children.length && r.width * r.height > 400) customOpaque += 1;
  }
  let canvasArea = 0;
  for (const c of __deepAll('canvas')) { const r = c.getBoundingClientRect(); canvasArea += Math.max(0, r.width) * Math.max(0, r.height); }
  const viewport = Math.max(1, window.innerWidth * window.innerHeight);
  return { shadow_roots: __deepRoots.length - 1, custom_elements: custom, opaque_custom: customOpaque,
           canvas_share: Math.round((canvasArea / viewport) * 100) / 100 };
}""")

# 예전에는 이 둘이 한 덩어리였고, 읽기 전용 스위치 하나가 전부를 막았다. 그래서 폼을
# 쓰려고 스위치를 끄면 결제·삭제까지 같이 열렸다 — 전부 아니면 전무.
#
# 갈라 놓는다. 폼을 채워 넣는 일(신청·저장·제출)과 돈이 나가거나 지워지는 일은
# 위험의 종류가 다르다. 앞쪽은 열고, 뒤쪽은 스위치와 무관하게 **언제나** 사람의
# 화면 승인을 거친다.
_SUBMIT_ACTION = re.compile(
    r"(보내기|전송|제출|신청|등록|저장|확정|예약|동의|확인|send|submit|save|apply|register|confirm)",
    re.IGNORECASE,
)

# 제출 버튼인데 **찾아보는 것뿐인** 것들 (2026-09-04).
#
# `type="submit"` 을 무조건 승인 경로로 보낸 것은 글자 없는 제출 버튼 때문이었다.
# 그런데 한국 사이트의 검색 버튼은 거의 다 `<button type="submit">검색</button>` 이라,
# **모든 사이트의 검색이 사람 승인을 받아야 눌리게 됐다.** 야놀자에서 밀양 숙소를
# 찾는 판이 여기서 걸음 셋을 버리고 승인 창까지 띄웠다 — 찾아보는 일에.
#
# 이 목록은 **되돌릴 것이 안 생기는 말**만 담는다. 위 `_IRREVERSIBLE_ACTION` 검사는
# 그대로 앞에 서 있으므로 "검색 후 결제" 같은 이름은 여전히 걸린다. `_SUBMIT_ACTION`
# 의 낱말(신청·등록·저장·예약·동의…)은 여기 **넣지 않는다** — 그건 자국이 남는다.
_READ_ONLY_SUBMIT = re.compile(
    r"(검색|찾기|조회|필터|정렬|보기|search|find|filter|sort|lookup|browse)",
    re.IGNORECASE,
)


#: 누른 뒤 덮는 창이 새로 떴을 때 「바뀐 것」에 적는 말의 머리 — 누르기가 이 말로 「우리가 띄운 창」을 알아본다.
_DIALOG_ROSE_NOTE = "덮는 화면이 떴습니다"


#: 이 PC 안 페이지의 확인창을 도구가 확인으로 답했을 때 결과에 싣는 말.
LOCAL_DIALOG_NOTE = (
    "이 PC 안 페이지라서 확인창에 '확인'으로 답했다. 취소로 답해야 하면 누르기 전에 "
    "browser_handle_dialog(accept=false) 를 먼저 불러라."
)


def _is_local_page(page: Any) -> bool:
    """이 페이지가 **이 PC 안**인가 — `file://` · `localhost` · `127.0.0.1` · `[::1]` · `*.localhost`.

    ★ 2026-09-30 코드 벤치: 자기가 만든 여행 경비 앱의 「추가」 버튼(폼 submit)을 누르려 하자 「되돌릴 수 없는 동작 — 승인」으로
    막혔고, 알려 준 승인 도구(`browser_click_confirmed`)는 코드 모드에 없어 다시 막혔다. 제출·삭제 승인은 **밖으로 나가는 일**을
    막으려는 것이다 — 이 PC 의 파일·로컬 서버 페이지에서 누른 것은 아무 데도 안 간다. 판정은 낱말이 아니라 주소의 사실로 한다.
    """
    try:
        parsed = urlparse(str(getattr(page, "url", "") or ""))
    except Exception:  # noqa: BLE001
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "file" or host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")


def _read_only_submit(name: str) -> bool:
    """이 제출 버튼은 **찾아보는 것뿐**인가.

    이름이 있어야 하고(글자 없는 제출은 예전대로 승인), 짧아야 하고, 찾는다는
    말이 들어 있어야 한다. 길면 이름이 아니라 문단을 긁어 온 것이라 판정 재료로
    못 쓴다 — 그럴 땐 안전한 쪽(승인)으로 간다.
    """
    label = " ".join((name or "").split())
    if not label or len(label) > 20:
        return False
    return bool(_READ_ONLY_SUBMIT.search(label))


def _read_only_blocks(name: str, element_type: str) -> bool:
    """읽기 전용 모드에서 이 누르기를 막는가.

    ★ 2026-09-26 A/B 벤치(다나와): 읽기 전용(기본값 켜짐)이 `type=submit` 을 **이름을 안 보고** 막아,
      `<button type=submit>검색</button>` 이 `read_only_action_blocked:검색` 으로 막혔다. 모델은 검색칸 Enter(역시 막힘)를
      거쳐 승인 클릭(`browser_click_confirmed`)으로 우회했고 — 가격 조회에 **「검색 눌러도 될까요」 승인 카드**가 떠서
      판이 멈췄다. 일반 모드는 09-04 에 찾아보는 제출(`_read_only_submit`)을 이미 풀었다. 같은 기준을 쓴다 —
      결제·삭제 같은 말(`_RISKY_ACTION`)은 그대로 막는다.
    """
    if _RISKY_ACTION.search(name or ""):
        return True
    if element_type == "file":
        return True
    return element_type == "submit" and not _read_only_submit(name)


# 검색칸인가 — 읽기 전용에서도 Enter 로 검색해도 되는 칸. 구조(type·role)나 이름·안내문·id 로 본다.
_SEARCH_FIELD_JS = """el => {
  if (!el) return false;
  const type = (el.getAttribute('type') || '').toLowerCase();
  if (type === 'password') return false;
  const role = (el.getAttribute('role') || '').toLowerCase();
  if (type === 'search' || role === 'searchbox' || role === 'combobox') return true;
  const form = el.form || el.closest('form');
  if (form && (form.getAttribute('role') || '').toLowerCase() === 'search') return true;
  const words = [el.getAttribute('name'), el.getAttribute('id'), el.getAttribute('placeholder'),
                 el.getAttribute('aria-label'), el.getAttribute('title'), form && form.getAttribute('action')].join(' ');
  return /검색|찾기|search|query|keyword|kwd|kws|[?&/]q\b|^q$|\bq\b/i.test(words);
}"""


# 되돌릴 수 없는 것들. 승인 없이는 어떤 모드에서도 눌리지 않는다.
_IRREVERSIBLE_ACTION = re.compile(
    r"(결제|구매|주문|결제하기|삭제|제거|탈퇴|해지|취소하기|환불|발행|게시|공유|"
    r"업로드|설치|송금|이체|출금|pay|purchase|buy|order|checkout|delete|remove|"
    r"withdraw|unsubscribe|publish|share|install|transfer)",
    re.IGNORECASE,
)

# 읽기 전용 모드에서 막는 것 = 둘 다.
_RISKY_ACTION = re.compile(
    f"({_SUBMIT_ACTION.pattern}|{_IRREVERSIBLE_ACTION.pattern})", re.IGNORECASE
)

_TECHNICAL_SEARCH = re.compile(
    r"(github|gitlab|playwright|selenium|puppeteer|api|sdk|mcp|docker|kubernetes|"
    r"python|javascript|typescript|react|rust|npm|pypi|arxiv|stack\s*overflow|"
    r"깃허브|플레이라이트|셀레니움|공식\s*문서|개발\s*문서|기술\s*문서)",
    re.IGNORECASE,
)

# SmartEditor ONE selectors, kept together so a markup change is one edit.
# The popup ones are the only ones confirmed against a live session: the
# 2026-08-03 임시저장 failure produced this from Playwright's call log --
#   <div class="se-popup-dim se-popup-dim-white"></div> from
#   <div data-group="popupLayer" data-name="se-popup-alert se-popup-alert-confirm"
#        class="se-popup __se-sentry se-popup-alert se-popup-alert-confirm">
#   subtree intercepts pointer events
_SE_POPUP = ".se-popup, [data-group='popupLayer']"
_SE_POPUP_DIM = ".se-popup-dim"
_SE_POPUP_BUTTON = "button, a[role='button'], .se-popup-button, [class*='se-popup-button']"
# Only ever press a NEGATIVE button automatically. The usual popup here is the
# draft-restore confirm ("이전에 작성 중이던 글이 있습니다"), whose positive button
# loads a previous draft on top of the post we just wrote. A dismisser that
# guesses "확인" on an arbitrary confirm is a dismisser that can publish.
# Widened past SmartEditor's wording because the rule is not editor-specific:
# whatever the dialog is, only the button that *declines* may be pressed
# without a person. A cookie banner says 거부, an app-install sheet says
# 나중에, a permission prompt says 허용 안 함 -- all of them are the same answer,
# and none of them can commit anything. Anything not listed here stops with its
# wording quoted, which is the behaviour the 2026-08-05 handoff (3.3) locks in.
_SE_DISMISS_LABELS = (
    # ×·✕ 는 글자가 아니라 **기호로 된 닫기**다. 뜻이 하나뿐이라 안전하다 —
    # 2026-08-12 잡코리아 팝업이 정확히 이 모양이었다(글자 버튼은 "다음" 하나뿐).
    "×", "✕", "✖", "⨯",
    "취소", "닫기", "아니오", "아니요", "나중에", "다음에", "거부", "거절",
    "허용 안", "허용안", "동의하지", "사용 안", "사용안", "건너뛰기", "무시",
    "괜찮", "안 할래", "cancel", "close", "reject", "decline", "deny",
    "dismiss", "not now", "no thanks", "skip", "later",
)
_SE_ACK_LABELS = ("확인", "ok")
_SE_CONFIRM_CLASS = "se-popup-alert-confirm"

# Attribute the probe below stamps on whatever it decides is a modal, so Python
# can grab it back as a normal locator and let Playwright apply its usual
# visibility and actionability checks. Nothing is ever clicked by coordinate.
_MODAL_MARK = "data-jarvis-modal"

# Find a dialog by behaviour rather than by class name.
#
# Every selector-based attempt so far has eventually broken: `.se-popup` misses
# Naver's draft-restore confirm ("작성 중인 글이 있습니다"), which lives in the
# top document with different markup. What does not change is how a modal
# behaves -- it covers the middle of the screen, it is positioned above the
# page, and it offers a small number of short-labelled buttons.
#
# Deliberately conservative: it only reports something that both sits on top at
# the viewport centre AND contains a button. A full-page container with no
# buttons is ordinary layout, and marking it would make every page look blocked.
_MODAL_PROBE_JS = """() => {
  const MARK = 'data-jarvis-modal';
  document.querySelectorAll('[' + MARK + ']').forEach(el => el.removeAttribute(MARK));
  const w = window.innerWidth, h = window.innerHeight;
  if (!w || !h) return 0;

  const buttonish = (root) => Array.from(
    root.querySelectorAll("button, a[role='button'], [role='button'], input[type='button'], input[type='submit'], [class*='button'], [class*='btn']")
  ).filter(b => {
    const r = b.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return false;
    const t = (b.innerText || b.value || '').trim();
    if (t.length > 0) return t.length <= 24;
    // ★ 글자가 없어도 버튼이다 (2026-08-12 잡코리아). X 닫기가 아이콘뿐이라
    // 후보에서 빠졌고, 그래서 남은 "다음" 하나만 보고 "부정 버튼 없음"으로
    // 판정해 멈췄다. 사이트가 스스로 붙인 이름(aria-label·title)이 있으면 그것도
    // 이름이다 — 어제 스냅샷에서 배운 것과 같은 규칙.
    const named = (b.getAttribute('aria-label') || b.getAttribute('title') || '').trim();
    return named.length > 0 && named.length <= 24;
  });

  const isLayer = (el) => {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'absolute') return false;
    if (s.visibility === 'hidden' || s.display === 'none') return false;
    const r = el.getBoundingClientRect();
    return r.width >= 120 && r.height >= 60;
  };

  // Probe a few points down the centre line: a dialog is usually centred, but
  // a toast or a sheet may sit higher or lower.
  const points = [[w / 2, h / 2], [w / 2, h * 0.42], [w / 2, h * 0.58]];
  for (const [x, y] of points) {
    let node = document.elementFromPoint(x, y);
    while (node && node !== document.body && node !== document.documentElement) {
      if (node.getAttribute && node.getAttribute('aria-hidden') === 'true') break;
      const role = node.getAttribute ? (node.getAttribute('role') || '') : '';
      const modalish = role === 'dialog' || role === 'alertdialog'
        || (node.getAttribute && node.getAttribute('aria-modal') === 'true');
      if (modalish || isLayer(node)) {
        // Climb to the outermost positioned wrapper so the dim layer and the
        // dialog body are treated as one thing.
        let top = node;
        while (top.parentElement && top.parentElement !== document.body
               && isLayer(top.parentElement)) {
          top = top.parentElement;
        }
        const container = buttonish(top).length ? top : node;
        if (buttonish(container).length) {
          container.setAttribute(MARK, '1');
          return buttonish(container).length;
        }
      }
      node = node.parentElement;
    }
  }
  return 0;
}"""

# Failures that say nothing about the page's state. Capturing a screenshot for
# these only adds latency and clutter -- a blocked read-only action or a stale
# ref is already fully described by its own message.
_NO_EVIDENCE_ERRORS = (
    # 요청이 가리키지 않은 사이트의 화면이다 — 실패 화면으로 찍어 둘 이유가 없다(`_another_site_tab`).
    "tab_is_another_site",
    # 사람이 쓰던 화면이다 — 그 화면(로그인 · 계정)을 실패 증거로 찍어 남기지 않는다(`_hold_if_human_on_tab`).
    "human_on_tab",
    "screen_is_another_site",
    "read_only_action_blocked",
    "stale_element_ref",
    "invalid_element_ref",
    "sensitive_field_blocked",
    "read_only_enter_blocked",
    "browser_url_not_allowed",
    "url_required",
    "key_required",
    # 브라우저가 이미 없는데 스크린샷을 찍으러 가 봐야 같은 예외만 한 번 더 난다.
    "has been closed",
    "target closed",
)

# 브라우저 자체가 사라졌다는 뜻의 실패. 페이지가 이상한 것과는 다르다 —
# 이건 다시 띄우는 것 말고 할 수 있는 일이 없고, 다시 띄우면 대개 낫는다.
# 주소 자체가 존재하지 않을 때 크로미움이 내는 말. 페이지 문제가 아니라 주소 문제다.
_UNRESOLVED_HOST = re.compile(
    r"(ERR_NAME_NOT_RESOLVED|ERR_NAME_RESOLUTION_FAILED|getaddrinfo)", re.IGNORECASE
)

# 태그 한 칸을 기다리는 시간. 기본 액션 타임아웃(20초)을 쓰면 안 된다 — 태그는
# 여러 개를 줄줄이 넣으므로 그 값이 개수만큼 곱해져 잡 예산을 통째로 먹는다.
_TAG_ACTION_TIMEOUT_MS = 2_500

_DEAD_BROWSER = re.compile(
    r"(target page, context or browser has been closed"
    r"|browser has been closed"
    r"|target closed"
    r"|browser has disconnected"
    r"|connection closed)",
    re.IGNORECASE,
)

# Draw a numbered badge over every element the snapshot already stamped, so a
# screenshot and the candidate list refer to the same things by the same names.
#
# This is the whole reason the model never has to produce a coordinate. Asking a
# 26B local model to click (1467, 331) misses, and -- per the 2026-08-05 handoff
# 3.1 -- a click that lands on empty space still reports success, which is
# exactly how three clicks were spent on the gap between two buttons. Picking
# "번호 7" cannot miss: the number resolves to a ref, and the ref resolves to a
# Playwright locator that applies its own actionability checks.
#
# Marks are drawn per frame, in that frame's own document, because getBoundingClientRect
# is frame-local. The composite screenshot lines up because that is how the page
# is actually rendered.
_MARK_JS = """(limit) => {
  const ID = '__alture_jarvis_marks';
  const old = document.getElementById(ID);
  if (old) old.remove();
  const root = document.createElement('div');
  root.id = ID;
  root.style.cssText = 'position:fixed;inset:0;z-index:2147483645;pointer-events:none;';
  const marked = [];
  const cap = limit > 0 ? limit : Infinity;
  document.querySelectorAll('[data-jarvis-ref]').forEach(el => {
    if (marked.length >= cap) return;
    const r = el.getBoundingClientRect();
    if (r.width < 6 || r.height < 6) return;
    if (r.bottom <= 0 || r.right <= 0) return;
    if (r.top >= window.innerHeight || r.left >= window.innerWidth) return;
    const ref = el.getAttribute('data-jarvis-ref');
    const box = document.createElement('div');
    box.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;border:2px solid rgba(236,72,153,.85);border-radius:3px;`;
    const tag = document.createElement('div');
    tag.textContent = ref.slice(1);
    tag.style.cssText = `position:fixed;left:${Math.max(0, r.left)}px;top:${Math.max(0, r.top - 15)}px;padding:1px 5px;background:#db2777;color:#fff;font:700 11px/1.3 Segoe UI,sans-serif;border-radius:3px;`;
    root.append(box, tag);
    marked.push(ref);
  });
  (document.documentElement || document.body).appendChild(root);
  return marked;
}"""

_UNMARK_JS = """() => {
  const el = document.getElementById('__alture_jarvis_marks');
  if (el) el.remove();
  return 0;
}"""
_MARK_JS = _deep_js(_MARK_JS)

_NAVER_DRAFT_SAVED_MARKERS =("저장되었습니다", "저장 되었습니다", "저장완료", "저장 완료", "저장됨")

# 봇 검사 화면. 여기서 하는 일은 **푸는 게 아니라 알아보는 것**이다 — 캡차를 대신
# 풀지 않는다. 알아보지 못하면 더 나쁘다: 검사 화면을 검색 결과로 읽어 "결과가 없다"는
# 엉뚱한 답을 만들거나, 빈 페이지를 붙들고 시간만 쓴다.
#
# 2026-08-05 사용자 화면에서 실제로 걸린 문구가 아래 한국어 3종인데 하나도 목록에
# 없었다: "마지막 한 단계", "계속하려면 아래 과제 해결", "확인 중…"(Bing).
_SEARCH_BLOCK_MARKERS = (
    "로봇이 아닙니다",
    "비정상적인 트래픽",
    "자동입력 방지",
    "접근이 제한",
    "마지막 한 단계",
    "과제 해결",
    "사람인지 확인",
    "본인 확인",
    "보안문자",
    "unusual traffic",
    "verify you are human",
    "our systems have detected",
    "one more step",
    "solve the challenge",
    "checking your browser",
    "captcha",
)


# 사이트 앞단(Akamai·Cloudflare 등)이 **문전에서 되돌려보내는** 화면.
#
# 위의 봇 검사와 다르다. 그쪽은 "네가 사람인지 확인하겠다"라 기다리거나 사람이
# 넘겨받을 수 있지만, 이쪽은 "너는 못 들어온다"라 풀 것도 기다릴 것도 없다.
#
# ★ 목록이 필요한 이유는 우회가 아니라 **알아보기 위해서**다. 2026-08-11 실측:
# 쿠팡 상품검색이 이 화면을 돌려줬는데 자비스에는 이걸 알아보는 코드가 없어서
# 화면을 그냥 본문으로 읽었고, 그 위에 "쿠팡에서 구매 가능한…"으로 시작하는 표를
# 지어냈다. 못 간 것보다 못 갔다는 걸 숨긴 것이 나쁘다.
#
# 상태 코드로는 못 잡는다 — 실측에서 Akamai 는 **200 으로** 이 화면을 줬다.
_EDGE_BLOCK_MARKERS = (
    "access denied",
    "you don't have permission to access",
    "attention required",
    "request blocked",
    "error 1020",
    "접근이 거부",
)

# 문전박대 화면은 짧다. 본문에서 문구를 찾을 때 이 길이를 넘으면 "그냥 그 낱말이
# 들어간 멀쩡한 글"로 본다 — 문구 목록만으로 판정하면 멀쩡한 페이지를 차단으로
# 읽어 버린다. 제목에 걸리면 길이는 보지 않는다.
_EDGE_BLOCK_MAX_CHARS = 1500

#: **점검 중 · 일시 오류.** 세 번째 갈래다 — 여기서는 다시 해 볼 이유가 없다.
#
# 봇 검사(`_SEARCH_BLOCK_MARKERS`)는 「네가 사람인지 보겠다」라 기다리거나 사람이
# 넘겨받을 수 있고, 문전박대(`_EDGE_BLOCK_MARKERS`)는 앞단이 그때그때 되돌려보내는
# 것이라 세 번까지 다시 해 볼 값어치가 있다(실측에서 1~3번째에 열렸다).
#
# 그런데 점검 화면은 **모두에게 닫혀 있다.** 1초 뒤에도, 2초 뒤에도 같다. 세 번
# 두드리면 그 판은 3초와 걸음 셋을 버리고, 그 뒤에 「막혔다」가 아니라 「점검 중」
# 이라는 다른 사실을 알려 줘야 하는데 문구도 틀리게 나간다.
#
# ★ 그래서 **한 번 보고 바로 넘어간다.** 다른 출처로 가라고 말해 준다.
# ★★ 이 목록은 **상상해서 쓰면 샌다.** 처음에 「점검 중」·「시스템 점검」으로 적었는데,
#     바로 그날 위시켓이 진짜로 점검에 들어갔고 **한 낱말도 안 걸렸다.** 실제 화면은
#     이렇게 적혀 있었다(`tests/fixtures/wishket_maintenance_2026-09-11.txt`):
#
#         현재 서비스 **개선** 중입니다. … 서비스 개선 중에는 사이트 **접속이 불가**
#         하오니 … 위시켓 서비스 개선 **점검 시간** : 2026년 9월 11일 (금) 00:30 ~
#
#     「점검 중」이 아니라 「개선 중」이었고, 「점검」은 **「점검 시간」** 이라는 다른
#     자리에만 있었다. 이 저장소가 낱말표로 여러 번 샌 것과 같은 병이다 —
#     **실제 화면에서 캐서 쓴다.** 새 표본을 만나면 여기에 더하고 fixtures 에 남긴다.
_MAINTENANCE_MARKERS = (
    # 실제 위시켓 화면에서 캔 것 (2026-09-11)
    "서비스 개선 중",
    "서비스를 개선 중",
    "개선 작업 중",
    "점검 시간",
    "접속이 불가",
    "접속이 제한",
    "이용이 불가",
    "이용에 불편을 드려",
    # 흔한 다른 표현들
    "점검 중",
    "점검중",
    "시스템 점검",
    "서버 점검",
    "서비스 점검",
    "정기 점검",
    "긴급 점검",
    "일시적인 오류",
    "일시적 오류",
    "일시적으로 중단",
    "잠시 후 다시 이용",
    "잠시후 다시",
    "under maintenance",
    "temporarily unavailable",
    "service unavailable",
    "we'll be back",
    "be right back",
)

# 점검 화면도 짧다. 문전박대와 같은 규율을 쓴다 — 문구 목록만으로 판정하면
# 「차량 점검 서비스」를 파는 멀쩡한 페이지가 점검 중으로 읽힌다. 제목에 걸리면
# 길이는 보지 않는다(점검 화면은 제목부터 그렇게 적는다).
_MAINTENANCE_MAX_CHARS = 1200


# 되돌아왔을 때 몇 번까지 다시 해 보는가.
#
# 실측(2026-08-11, 쿠팡 상품검색, 같은 PC·같은 크롬·같은 프로필): 열리기까지 필요한
# 이동 횟수가 판마다 **1번·2번·3번**으로 달랐다. 코드 차이가 아니라 앞단이 그때그때
# 되돌려보내는 것이다. 그래서 한 번 만에 포기하면 들어갈 수 있는 곳을 못 들어가고,
# 무제한으로 두드리면 그건 우회다. 셋으로 묶는다 — 실측에서 셋을 넘긴 적이 없고,
# 넘으면 막혔다고 말한다.
_EDGE_BLOCK_ATTEMPTS = 3
_EDGE_BLOCK_BACKOFF_SEC = (1.0, 2.0)


# 한 프레임에서 훑어볼 요소의 절대 상한.
#
# ★ 예전에는 `budget * 3` 이었다. "보이는 것 몇 개만 모으면 되니 그 서너 배만 보면
# 충분하다"는 계산인데, **안 보이는 것이 앞에 잔뜩 깔려 있으면 틀린다.**
#
# 2026-08-06 실측 (네이버 블로그 탭):
#     조작 가능한 요소 377개 · 그 중 **보이는 것은 39개** · 첫 블로그 결과가 **240번째**
#
# budget 64 로 `64*3 = 192` 에서 끊으니 결과에 영영 못 닿았다. 겉으로는 "네이버
# 블로그 검색은 결과가 0건"으로 보였고, 그건 봇 차단이나 파서 버그와 구별되지 않는다.
#
# 정상적인 화면은 budget 을 채우는 순간 루프가 끊기므로 이 상한이 비용이 되지 않는다.
# 걸리는 것은 안 보이는 요소가 앞을 채운 화면뿐이고, 그게 정확히 우리가 놓치던 경우다.
#
# ★ 2026-08-13 두 번째 인상: 700 → 6000. **다나와 정렬 미스터리의 정체가 이것이었다.**
#
# 인수인계서에는 "통합검색 페이지엔 가격 정렬이 아예 없는 것 같다(가설)"고 적혀 있었다.
# 실제로 열어 보니 정렬은 멀쩡히 있었다 — `<li data-sort-method="priceASC">` 안의
# `<a href="">낮은가격순</a>`, 화면에 보이고 `visible()` 도 통과한다.
#
# 실측(`search.danawa.com/dsearch.php?query=무선마우스`):
#     _INTERACTIVE 에 걸리는 요소 7,157 개 · **정렬 바는 4,255~4,259 번째**
#     maxScan  700 → 75 개 수집, 정렬 **없음**   (인수인계서의 "93개 중 정렬 없음")
#     maxScan 5000 → 200 개 수집, 정렬 **있음**  (16ms)
#     전체 7,157 개를 다 훑어도 30ms — 700 이 산 것은 거의 없었다.
#
# 젬마는 일곱 가지 표현으로 정렬을 찾다 "못 찾았다"고 답했는데, 판단이 모자란 게
# 아니라 **목록에 넣어 주지 않은 것**이었다. `[onclick],[tabindex]` 를 더해도 안 나온
# 이유도 이것이다 — 선택자를 넓혀 봐야 4,255 번째까지 가지를 않는다.
#
# 오늘만 세 번째로 만나는 모양이다: 상한이 여러 군데면 **낮은 쪽만 일한다**
# (config dataclass · config 로더 · 그리고 여기, 함수 안의 하드 상수).
#
# ★ 2026-10-07: **스냅샷도 이 범위를 전부 훑는다**(번호를 찾기와 같게 매기려고 — `_snapshot` 주석). 실측(헤드리스 크로미움, 가운데값):
#     요소 1,062개(이력서 수정 화면)   스냅샷 32ms → 80ms
#     요소 5,701개(긴 목록 화면)       스냅샷 57ms → 370ms · 찾기 327ms → 320ms
#   모델에게 내주는 양은 그대로다(`browser_max_elements`, 기본 200).
_MAX_SCAN = 6000

#: 스냅샷 한 번의 요소 목록이 모델에게 갈 때 쓸 수 있는 글자 수.
#:
#: ★ 2026-10-07 폼 벤치 셋째 판: 요소 200개짜리 스냅샷은 32,011자였고, 도구 결과는 모델에게 가는 길목에서 **앞 30,000자**만
#:   남는다(`agent._TOOL_RESULT_MAX_CHARS`). 잘린 것은 목록의 190번째 뒤와 **맨 끝의 안내문**이었다 — 화면에 보이는 것을
#:   먼저 담게 고친 바로 그 「임시저장」(199번째)과 「아래에 더 있다」는 말이 통째로 안 갔다. 모델은 첫 줄의 「삭제」를
#:   추측으로 눌렀다(세 판 중 세 판 저장 0번). 개수 상한(200)과 글자 상한(30,000)이 따로 놀았다 — 사고 Q 의 다섯 번째다.
#:   고리를 여기서 닫는다: 스냅샷이 **글자 예산 안에 스스로 들어오고**, 뺀 것은 `more_elements` 로 센다.
#:   4,000자는 감싸는 열쇠·주소·안내문·되풀이 알림의 몫이다. 두 값이 어긋나면 시험이 잡는다.
_SNAPSHOT_CHAR_BUDGET = 26_000


def _fit_snapshot(
    listed: list[dict[str, Any]], on_screen: set[int], limit: int, char_budget: int
) -> tuple[list[dict[str, Any]], int]:
    """모델에게 내줄 요소를 고른다 — **지금 화면에 보이는 것 먼저**, 남는 자리는 문서 위쪽부터. (고른 것, 그중 화면에서 온 수)

    개수(`limit`)와 글자(`char_budget`, 0 이면 안 본다) 둘 다 지킨다. 다 들어가면 문서 순서 그대로 준다.
    줄여야 하면 **화면에 보이는 것을 목록 앞에** 둔다(각 묶음 안은 문서 순서) — 작은 창에서는 길목의 상한이 더 낮아
    목록 뒤가 또 잘린다(`chat_transcript_budget`). 그때 남는 것이 눈앞의 것이어야 한다.
    예산에 걸리면 거기서 멈춘다(뒤에서 작은 것을 골라 끼우지 않는다).
    """

    def cost(row: dict[str, Any]) -> int:
        return len(json.dumps(row, ensure_ascii=False)) + 2

    if len(listed) <= limit and (not char_budget or sum(cost(row) for row in listed) <= char_budget):
        return listed, 0
    chosen: set[int] = set()
    spent = 0
    from_screen = 0
    for first, group in ((True, [row for row in listed if id(row) in on_screen]), (False, listed)):
        for row in group:
            if id(row) in chosen:
                continue
            price = cost(row)
            if len(chosen) >= limit or (char_budget and spent + price > char_budget):
                break
            chosen.add(id(row))
            spent += price
        if first:
            from_screen = len(chosen)
    picked = [row for row in listed if id(row) in chosen]
    return (
        [row for row in picked if id(row) in on_screen] + [row for row in picked if id(row) not in on_screen],
        from_screen,
    )


# 태그로는 안 걸리는 것을 찾는 두 번째 훑기(`body *`)의 상한.
#
# 예전에는 `_MAX_SCAN * 6` 이라 위를 올리면 여기가 같이 따라 올라갔다. 두 훑기는
# 비용이 다르다 — 이쪽은 `getComputedStyle(cursor)` 를 부르므로 훨씬 비싸고, 대상도
# 문서 전체(다나와 실측 32,954 개)다. 묶어 두면 한쪽을 고칠 때 다른 쪽이 조용히
# 여섯 배가 된다. 값은 종전과 같게 둔다(700 × 6).
_MAX_DEEP_SCAN = 4200

# `browser_annotate`(= ui_find_target 이 보는 그림)가 후보를 고르기 전에 훑는 범위.
#
# 화면 안에 들었는지는 `_MARK_JS` 가 판정한다. 여기서 하는 일은 **그 판정에 걸릴
# 기회를 주는 것**뿐이라, 일반 스냅샷 예산과 같은 크기로 둔다. 좁게 잡으면 화면
# 한복판에 있는 것도 문서 뒤쪽이라는 이유로 그림에 못 들어간다(다나와 정렬 실측:
# 정렬 바가 136 번째라 60 으로 자르는 판에서는 후보에 아예 없었다).
#
# ★ 2026-10-07 폼 벤치: 200 도 모자랐다. 요소 1,062개인 이력서 수정 화면에서 화면 아래 고정 막대의 「임시저장」은
#   문서 1,060번째라, 화면에 뻔히 보이는데도 `ui_find_target` 이 「후보 7개 중에 없습니다」로 세 판 다 못 찾았다.
#   60 → 200 으로 올린 것과 같은 병이 더 큰 화면에서 재발한 것이다 — 이 값은 화면 전체를 훑는 상한과 같아야 한다.
_ANNOTATE_SCAN_BUDGET = _MAX_SCAN
#: 그림 도구가 돌려주는 목록의 상한 — 훑기는 전부 하되, 내주는 것은 화면에 든 것 + 이만큼까지(모델 창을 덮지 않게).
_ANNOTATE_LIST_MAX = 400

# 상세를 읽기 전에 훑어 내리는 횟수·간격.
#
# 여섯 칸 · 220ms = 최대 1.3 초다. 상세 한 장을 읽는 데 그 정도는 값이 있다 —
# 안 훑으면 지연 로딩 구간이 통째로 "그 페이지에 없는 것"이 된다.
_LAZY_SWEEP_STEPS = 6
_LAZY_SWEEP_PAUSE_MS = 220

# 화면 높이의 몇 배부터 훑을 것인가. 한 화면짜리 페이지를 훑는 것은 순수한 낭비다.
_LAZY_SWEEP_MIN_RATIO = 1.6

# 마우스를 올린 뒤 메뉴가 펼쳐지기를 기다리는 시간.
#
# 국내 쇼핑 내비게이션의 CSS 전환이 대개 150~300ms 다. 너무 짧게 잡으면 "아무것도
# 안 나타났다"로 읽고 눌러 버린다 — 그러면 상위 카테고리 기획전으로 간다(쿠팡 실측).
_HOVER_SETTLE_MS = 450

# 그림 한 장 찍는 데 줄 시간. 기본 동작 시간(20초)보다 짧게 잡는다 —
# 그림은 **거들 뿐**이라, 못 찍어도 목록으로 계속 갈 수 있어야 한다.
_SCREENSHOT_TIMEOUT_MS = 8000

# 그림 한 장에 번호를 몇 개까지 그릴 것인가. 이건 **읽기 좋음**의 문제다 — 번호가
# 수백 개면 비전이 못 읽는다. 호출자가 limit 을 주면 그쪽이 이긴다.
_MAX_MARKS = 60

# `site:blog.naver.com 크몽 후기` 처럼 보내는 일이 잦다(2026-08-06 실측). 구글에서
# 배운 습관인데 **네이버는 이 연산자를 모른다** — 조용히 빈손으로 돌아오고, 모델은
# 그걸 "그 사이트에는 자료가 없다"로 읽어 멀쩡한 검색을 포기한다.
_SITE_OPERATOR = re.compile(r"\bsite:\s*([^\s]+)", re.IGNORECASE)

#: 조사 결과에서 뺄 **영상** 주소(2026-09-24 제품 결정: 「브라우저 조사할 때 유튜브 같은 영상은 빼라」).
#: 영상은 본문을 읽을 수 없어 근거가 안 되고, 열면 소리·광고로 사람을 놀라게 한다.
_VIDEO_HOSTS = (
    "youtube.com", "youtu.be", "tv.naver.com", "tiktok.com", "vimeo.com", "dailymotion.com", "tv.kakao.com",
    # ★ 2026-09-26 노트북 실측(사용자: 「요즘 검색하면 유튜브·네이버 클립이 너무 많다」): 날씨를 찾다 **네이버 클립**
    #   (`clip.naver.com`)과 **숏츠**(`m.naver.com/shorts/…`)를 열어 읽고 최고기온을 못 찾았다. 호스트만 보던 목록에 없었다.
    "clip.naver.com", "chzzk.naver.com", "play-tv.kakao.com", "kakaotv.daum.net",
    "afreecatv.com", "sooplive.co.kr", "twitch.tv", "bilibili.com",
)
#: 호스트는 글도 있는 곳인데 **이 경로 아래**는 영상인 곳 — 네이버 숏츠·인스타 릴스·페이스북 워치.
_VIDEO_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("naver.com", ("/shorts", "/clip/")),
    ("instagram.com", ("/reel/", "/reels/", "/tv/")),
    ("facebook.com", ("/watch", "/reel/")),
)
_ASKS_FOR_VIDEO = re.compile(r"영상|동영상|유튜브|유투브|쇼츠|숏츠|클립|릴스|틱톡|생방송|video|youtube|shorts|reels?|tiktok", re.I)


def _is_video_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if any(host == video or host.endswith("." + video) for video in _VIDEO_HOSTS):
        return True
    path = (parsed.path or "").lower()
    return any((host == base or host.endswith("." + base)) and path.startswith(prefixes)
               for base, prefixes in _VIDEO_PATHS)


def _without_videos(results: list[dict[str, Any]], query: str, tab: str = "") -> list[dict[str, Any]]:
    """영상 결과를 빼고 순위를 다시 매긴다. 영상을 찾는 검색(검색어·탭)이면 그대로 둔다."""
    if _ASKS_FOR_VIDEO.search(query or "") or str(tab or "").lower() in {"video", "videos", "vod"}:
        return results

    kept = [item for item in results or [] if not _is_video_url(str(item.get("url") or ""))]
    if len(kept) == len(results or []):
        return results
    return [{**item, "rank": index} for index, item in enumerate(kept, 1)]


def _ensure_message_queue(user32: Any) -> None:
    """이 스레드에 **메시지 큐**를 만든다 — 없으면 `AttachThreadInput` 이 거부된다.

    ★ 2026-09-26 부산 노트북 진단: 안 보이는 크롬이 앞창을 쥐었을 때 되돌려주기가 **매번** `returned=False` 였다(40초 쥠).
      되돌려주기는 크롬의 입력 스레드에 잠깐 붙어(`AttachThreadInput`) 앞창을 넘기는데, 감시는 창 없는 파이썬 스레드라
      메시지 큐가 없다 — 윈도우는 큐 없는 스레드의 입력 연결을 받지 않는다. `PeekMessage` 한 번이 큐를 만든다(Win32 관례).
    """
    try:
        import ctypes
        import ctypes.wintypes as wt

        message = wt.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)  # PM_NOREMOVE
    except Exception:  # noqa: BLE001 — 못 만들면 예전처럼 시도만 한다
        pass


def _alt_tab_held(user32: Any) -> bool:
    """사람이 **Alt+Tab** 중인가 — 왼쪽 Alt 를 누른 채 Tab.

    ★ 2026-09-26 부산 노트북, 사람이 **한글로 채팅하는 중**에 잰 판: 크롬이 20초 화면에 나오고 15.8초 앞창을 쥐었다.
      예전엔 `VK_MENU`(0x12) — **양쪽 Alt** 를 봤는데, 한국 노트북은 오른쪽 Alt 가 한/영 키인 경우가 많다. 한/영을 누를 때마다
      1.5초 동안 「사람이 크롬을 불렀다」가 되어, 마침 태어난 크롬이 앞창을 쥐자 화면에 펼쳐 줬다. 가만히 둔 측정은 못 잡는다.
      왼쪽 Alt(0xA4)와 Tab(0x09)이 **같이** 눌렸을 때만 부른 것으로 본다. Alt 단독·오른쪽 Alt(한/영)는 아니다.
    """
    try:
        return bool(user32.GetAsyncKeyState(0xA4) & 0x8000) and bool(user32.GetAsyncKeyState(0x09) & 0x8001)
    except Exception:  # noqa: BLE001
        return False


# 검색 결과 **맨 위 답 상자**(날씨·환율·시간 같은 위젯). 링크가 아니라서 결과 목록에 안 들어오고, 모델 눈에 안 보였다.
# ★ 2026-09-26 고친 판 벤치(날씨 1/3): 「부산 날씨」 검색 결과 맨 위에 「현재 온도 20.1° … 최고 …」가 있는데 모델은 링크 제목만
#   받아 「최고기온은 위젯을 참고하세요」로 끝냈다. 네이버는 `#main_pack` 의 **첫 section**, 구글은 `#rso` 첫 블록, 빙은 첫 답이다.
#   1,500자: 네이버 날씨 상자에서 「최고기온」은 1,360자 중 ~890자 자리다(실측) — 700 으로는 잘렸다.
_SERP_ANSWER_BOX_JS = r"""
() => {
  // ★ 2026-09-26 노트북: 구글에서 첫 덩어리가 **보통 검색 결과**(「Web results · Rome2Rio …」)였는데 그걸 답 상자로 집었고,
  //   모델은 「부산→여수 평균 3시간 3분」을 길찾기 답으로 냈다. 답 상자는 위젯일 때만 준다 — 보통 결과(제목 링크+출처 표시)와
  //   광고는 거른다. 빙의 `li.b_algo` 도 보통 결과라 뺐다.
  const organic = el => {
    const text = (el.innerText || '').trim();
    if (/^(web results|웹 검색결과|검색결과|sponsored|광고|파워링크)/i.test(text)) return true;
    // 통합 검색 안의 뉴스·블로그·카페 묶음도 목록이다(2026-10-02 — 「언론사 선정 …」 기사 목록을 답 상자로 집었다).
    if (/^(뉴스|언론사 선정|블로그|카페|인플루언서|지식iN|이미지|동영상)/.test(text)) return true;
    if (/(power|ad_|_ad\b|sp_nreview|sp_nweb|web_gen)/i.test(el.className || '')) return true;
    const widget = el.querySelector('#wob_wc, [data-attrid], .kp-wholepage, g-card, [data-tts], .xpdopen');
    return !widget && !!(el.querySelector('h3') && el.querySelector('cite'));
  };
  const pick = () => {
    const naver = document.querySelector('#main_pack');
    if (naver) return [...naver.children].find(el => el.tagName === 'SECTION' && !organic(el));
    const google = document.querySelector('#rso');
    if (google) {
      const first = [...google.children].find(el => (el.innerText || '').trim().length > 30);
      return first && !organic(first) ? first : null;
    }
    const bing = document.querySelector('#b_results');
    if (bing) return bing.querySelector('li.b_ans');
    return null;
  };
  const box = pick();
  return box ? (box.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 1500) : '';
}
"""


#: 답 상자가 아닌 덩어리 — 광고·맞춤법 제안·동영상·「사람들이 묻는 질문」. 2026-10-02 운영 기록 대조: 통합 검색에서
#: 답 상자로 집은 17개 중 진짜(코스피 시세·날씨)는 6개였고 나머지가 이 모양이었다. 「읽은 근거」로 세면 안 된다.
_NOT_AN_ANSWER_BOX = re.compile(
    r"^(?:제안도움말|동영상|사람들이 묻는 질문|people also ask|videos?\b)|이 광고가 표시된 이유|관련 광고 |(?:동영상|videos?)\s\d{1,2}:\d{2}", re.IGNORECASE
)


def _clean_answer_box(text: str) -> str:
    """답 상자 글. 너무 짧으면(버튼·탭 이름뿐) 버린다 — 빈 상자를 「답이 있다」로 읽게 하지 않는다."""
    value = " ".join(str(text or "").split())
    if _NOT_AN_ANSWER_BOX.search(value[:160]):
        return ""
    return value if len(value) >= 40 else ""


def _host_of_url(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


#: 화면을 **바꾸는** 손. 요청이 적어 준 주소와 다른 사이트의, 전부터 떠 있던 화면에서는 안 쓴다(`_another_site_tab`).
#: 읽는 손(스냅샷·읽기·찾기)은 여기 없다 — 읽어야 「여기가 아니다」를 안다.
_SCREEN_HANDS = frozenset({
    "browser_click", "browser_click_at", "browser_click_confirmed", "browser_type_at", "browser_fill", "browser_fill_form",
    "browser_select_option", "browser_file_upload", "browser_pick_suggestion", "browser_press",
})
#: 이 판이 **스스로 주소를 연** 손. 그 탭은 그때부터 이 판의 탭이다(전부터 있던 탭이 아니다).
_NAVIGATING_HANDS = frozenset({"browser_open", "browser_search", "browser_site_search", "browser_open_result"})

#: 사람이 같은 탭을 쓰고 있는 것 같으면 **멈추는** 손 (2026-10-19 · `_hold_if_human_on_tab`). 그 화면의 내용을 바꾸거나
#: (누르기 · 쓰기 · 고르기 · 그 화면의 검색칸에 치기 · 더 보기 단추 · 알림창 답하기) 사람의 방문 기록을 따라가는(뒤로) 손이다.
_HANDS_ON_THE_PAGE = _SCREEN_HANDS | frozenset({
    "browser_back", "browser_site_search", "browser_load_more", "browser_dismiss_dialog", "browser_handle_dialog",
    "naver_blog_fill_editor", "naver_blog_upload_image", "naver_blog_click_save_draft", "naver_blog_click_publish",
})
#: 이 판이 **제 주소로** 가는 손 — 사람이 쓰던 화면을 건드리지 않고 이 판의 화면을 새로 연다. 멈추지 않고, 열면 다시 이 판의 화면이다.
#: (`browser_site_search` 는 지금 화면의 검색칸에 치므로 여기 아니라 위에 있다.)
_OWN_ADDRESS_HANDS = frozenset({"browser_open", "browser_search", "browser_open_result"})
#: 보기만 하는 손 — 사람이 쓰던 화면이어도 읽기는 이어 가되(알림을 붙인다), 그 결과 주소를 「이 판이 간 곳」으로 치지 않는다.
_LOOKING_HANDS = frozenset({
    "browser_extract", "browser_page_data", "browser_site_sources", "browser_links", "browser_find", "browser_snapshot",
    "browser_probe_frames", "browser_screenshot", "browser_annotate", "browser_verify", "browser_find_selector",
    "browser_read", "browser_tabs", "browser_download", "browser_wait", "browser_hover", "browser_scroll",
    "naver_blog_read_account", "naver_blog_capture_screen",
})


def _own_key(url: str) -> str:
    """「같은 화면」을 가르는 열쇠 — 호스트(앞 `www.` 뗌) + 경로. 물음표 · `#` 뒤는 안 본다(같은 화면의 정렬 · 앵커 · 추적값)."""
    try:
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host + (parsed.path.rstrip("/") or "")

#: 요청문에 **적혀 있는 주소**. 한글에서 끊는다 — 「…/basic에서」처럼 조사가 붙어 온다.
_WRITTEN_ADDRESS = re.compile(r"https?://[^\s<>\"'「」『』()\[\]가-힣]+", re.IGNORECASE)


def _site_of_url(url: str) -> str:
    """주소의 **사이트** — `search.kyobobook.co.kr` 과 `www.kyobobook.co.kr` 은 같고, 포트는 보지 않는다.

    숫자 주소·`localhost` 는 그대로 쓴다(`site_atlas.registrable` 은 점으로만 세어 `127.0.0.2` 를 `0.2` 로 만든다).
    """
    try:
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
    except ValueError:
        return ""
    # 웹 주소만 사이트가 있다 — `chrome://newtab/`·`about:blank` 은 어느 사이트도 아니다.
    if not host or parsed.scheme not in ("http", "https"):
        return ""
    if host.replace(".", "").isdigit() or ":" in host or "." not in host:
        return host
    from .site_atlas import registrable

    return registrable(host) or host


# 본문 고르기. 페이지 안에서 도는 코드라 왕복이 한 번뿐이다 — 블록마다 파이썬으로
# 물어보면 수백 번 왕복하고, 그 비용이 글 한 편당 몇 초가 된다.
#
# 점수 = 글자 수 − 링크 안 글자 수. 메뉴·이웃목록·인기글은 글자가 거의 전부 링크
# 안에 있어서 점수가 0 근처로 떨어지고, 본문은 링크가 드물어 높게 나온다.
# `<article>`·`<main>` 이 있으면 그대로 믿는다(그게 있는 사이트는 정확하다).
_EXTRACT_MAIN_JS = """
(readSelectors) => {
  const strip = ['script','style','noscript','nav','header','footer','aside',
                 'form','iframe','svg','button'];
  const textOf = (el) => (el.innerText || '').trim();
  const linkChars = (el) => {
    let n = 0;
    for (const a of el.querySelectorAll('a')) n += (a.innerText || '').length;
    return n;
  };
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (!rect.width && !rect.height) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden';
  };
  const score = (el) => {
    const t = textOf(el);
    if (t.length < 140) return -1;
    return t.length - linkChars(el);
  };
  const nameOf = (el) => {
    const id = el.id ? '#' + el.id : '';
    const cls = (el.className && typeof el.className === 'string')
      ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
    return el.tagName.toLowerCase() + id + cls;
  };

  // ★ 글·카드 안의 <header> 는 머리말이 아니라 **제목**이다 (2026-10-01 밤 허깅페이스 목록).
  //   모델 카드마다 이름이 <article><a><header><h4>이름</h4></header>… 안에 있어서, header 를 통째로 지우면
  //   「Text Generation · 15B · Updated 2 days ago」만 남고 이름이 전부 사라졌다(2,393자 → 살리면 3,715자).
  //   페이지 머리말(사이트 메뉴)은 article 밖에 있으니 그대로 지운다.
  const clone = (el) => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll(strip.join(',')).forEach((n) => {
      if (n.tagName === 'HEADER' && n.parentElement && n.parentElement.closest('article')) return;
      n.remove();
    });
    return copy;
  };

  let best = null;
  // ★ **믿는 태그가 여럿이면 글이 가장 많은 것** · **그것이 페이지 글의 10분의 1 도 안 되면 믿지 않는다** (2026-10-05 실측).
  //   예전에는 문서에서 **처음 나오는** article·main 을 그대로 믿었다. 두 사이트에서 틀렸다:
  //     연합뉴스 기사 — 요약 상자 <article class=story-summary>(154자)가 본문 <article id=articleWrap>(1,050자)보다 먼저 온다.
  //       기사를 요약 한 줄만 읽고 있었다(페이지 글의 3%).
  //     사람인 템플릿 공고 — 회사가 쓴 영역 안의 <main class=job-posting>(776자, 페이지 글의 4%). 사이트가 채운 칸이 통째로 빠졌다.
  //   같은 자로 잰 멀쩡한 곳: 위키백과 99% · 허깅페이스 100% · 깃허브 85% · 스택오버플로 97% · MDN 100% · 긱뉴스 100% ·
  //   잡코리아 100% · 원티드 100% · 연합뉴스(본문을 고른 뒤) 약 24%. 3~4% 와 24% 사이에 금을 긋는다 — 1/10.
  //   못 믿게 되면 아래 예전 길(전체에서 글이 가장 많은 덩어리)로 간다: 잡음은 섞여도 내용이 빠지지는 않는다.
  const trusted = Array.from(document.querySelectorAll(
    'article, main, [role=main], #postViewArea, .se-main-container, .article_body, #articleBodyContents'
  )).slice(0, 60);
  let preferred = null, preferredScore = -1;
  for (const el of trusted) {
    if (!visible(el)) continue;
    let s = -1;
    try { s = score(clone(el)); } catch (e) { s = -1; }
    if (s > preferredScore) { preferredScore = s; preferred = el; }
  }
  if (preferred) {
    let pageScore = 0;
    try { pageScore = score(clone(document.body)); } catch (e) { pageScore = 0; }
    if (preferredScore < 0 || (pageScore > 0 && preferredScore * 10 < pageScore)) preferred = null;
  }
  const pool = preferred ? [preferred] : Array.from(
    document.querySelectorAll('article, main, section, div, td')
  ).filter(visible).slice(0, 400);

  // ★ 복제본은 화면에 없어서 innerText 가 **칸 경계를 잃는다** (2026-10-02 사람인 실측).
  //   붙은 원본은 「근무형태 / 정규직 수습기간 3개월 / 우대사항 / 3건」(줄마다)인데 복제본은 「근무형태정규직 수습기간 3개월우대사항3건」 —
  //   모델이 고용형태 칸에 「정규직(수습 3개월 우대)」를 적었다. 줄바꿈 없이 짠 페이지 전부가 같은 병이다.
  //   고르기(점수)는 그대로 두고, **고른 하나만** 원본의 화면 모양(display)을 보고 블록 앞뒤에 줄바꿈·칸 뒤에 빈칸을 넣는다.
  const lineBreaks = new Set(['block', 'list-item', 'table', 'table-row', 'flex', 'grid', 'flow-root', 'table-caption',
                              'table-row-group', 'table-header-group', 'table-footer-group']);
  const NL = String.fromCharCode(10);
  // ★ 머리줄이 있는 표는 **줄마다 한 줄로, 칸마다 머리말을 붙여** 낸다 (2026-10-04 허깅페이스 판 5749ff16).
  //   모델 카드의 벤치마크 표가 「Type / Model / Size / WikiText-2 / C4 / IQ2_XXS / … / 6.68 / 11.03」 — 칸마다 한 줄로 풀려 왔다.
  //   모델은 다섯 줄씩 세어 열을 맞춰야 했고, C4 값을 WikiText-2 라고 적고 옆 줄 값을 섞었다(엑셀 다섯 줄 중 셋).
  //   머리줄(<th> 만으로 된 첫 줄)이 있는 자료 표만 건드린다 — 배치용 표(옛 사이트의 뼈대)는 th 가 없고, 그 안의 줄바꿈을 뭉개면 안 된다.
  //
  // ★ 머리칸이 **하나도 없는** 표도 줄마다 한 줄로 낸다 (2026-10-04 사람인 공고 21개 실측). 회사가 직접 짠 공고 템플릿 넷 중 셋이
  //   `<th>` 없이 `<td>` 만으로 「분류 | 담당업무 | 지원자격 | 근무지」를 짰고(표 12~24개, 표 안에 표 3~11겹), 전부 칸마다 한 줄로 풀렸다.
  //   머리말은 붙이지 않는다(어느 줄이 머리줄인지 모른다) — 줄만 지킨다. 안쪽 표(더 안에 표가 없는 것)만 건드리고,
  //   칸에 긴 글이 든 표는 배치용이라 그대로 둔다. `<th>` 가 섞인 줄머리 표(「급여 | 회사내규」)도 예전대로다.
  const tableLines = (table) => {
    if (table.querySelector('table')) return null;
    const rows = [...table.rows];
    if (rows.length < 2 || rows.length > 400) return null;
    const cellText = (c) => (c.innerText || c.textContent || '').replace(/\\s+/g, ' ').trim();
    const heads = [...rows[0].cells];
    if (!table.querySelector('th')) {
      const grid = rows.map((row) => [...row.cells].map(cellText));
      const wide = grid.filter((cells) => cells.length >= 2).length;
      const longest = Math.max(0, ...grid.map((cells) => Math.max(0, ...cells.map((value) => value.length))));
      if (wide * 2 < grid.length || longest > 300 || grid.some((cells) => cells.length > 30)) return null;
      return grid.map((cells) => cells.join(' | ')).filter((line) => line.replace(/[| ]/g, '')).join(NL);
    }
    if (table.parentElement && table.parentElement.closest('table')) return null;
    if (heads.length < 2 || heads.length > 30 || !heads.every((c) => c.tagName === 'TH' && c.colSpan === 1)) return null;
    const names = heads.map(cellText);
    // 큰 표는 머리말을 줄마다 되풀이하지 않는다 — 글자 예산을 먹는다. 그래도 한 줄에 한 줄은 지킨다.
    const label = rows.length <= 80;
    const lines = [names.join(' | ')];
    for (const row of rows.slice(1)) {
      const cells = [...row.cells];
      const plain = cells.map(cellText);
      const aligned = cells.length === names.length && cells.every((c) => c.colSpan === 1);
      lines.push(label && aligned
        ? plain.map((value, j) => (names[j] ? names[j] + ': ' + value : value)).join(' | ')
        : plain.join(' | '));
    }
    return lines.join(NL);
  };
  const separated = (el) => {
    const copy = el.cloneNode(true);
    const lives = [el, ...el.querySelectorAll('*')];
    const copies = [copy, ...copy.querySelectorAll('*')];
    if (lives.length === copies.length && lives.length <= 20000) {
      for (let i = 1; i < lives.length; i++) {
        const live = lives[i];
        if (live.tagName === 'BR') { copies[i].replaceWith(NL); continue; }
        if (live.tagName === 'TABLE') {
          let lines = null;
          try { lines = tableLines(live); } catch (e) { lines = null; }
          if (lines) { copies[i].replaceWith(NL + lines + NL); continue; }
        }
        // 숫자 굴림 칸(0~9 가 세로로 쌓인 것)은 지금 보이는 숫자 하나로 — `_ROLLER_DIGITS_JS` 와 같은 규칙(2026-10-02 Manus 가격).
        if (live.children.length >= 10 && (live.textContent || '').replace(/\\s+/g, '') === '0123456789') {
          let clip = live.parentElement;
          while (clip && clip !== document.body && getComputedStyle(clip).overflow === 'visible') clip = clip.parentElement;
          const box = (clip || live).getBoundingClientRect();
          let best = '?', overlap = 0;
          for (const child of live.children) {
            const r = child.getBoundingClientRect();
            const seen = Math.max(0, Math.min(r.bottom, box.bottom) - Math.max(r.top, box.top));
            if (seen > overlap) { overlap = seen; best = (child.textContent || '').trim(); }
          }
          copies[i].textContent = /^[0-9]$/.test(best) ? best : '?';
          continue;
        }
        let display = '';
        try { display = getComputedStyle(live).display; } catch (e) { continue; }
        if (display === 'table-cell') copies[i].append(' ');
        else if (lineBreaks.has(display)) { copies[i].prepend(NL); copies[i].append(NL); }
      }
    }
    copy.querySelectorAll(strip.join(',')).forEach((n) => {
      if (n.tagName === 'HEADER' && n.parentElement && n.parentElement.closest('article')) return;
      n.remove();
    });
    return copy;
  };

  let bestEl = null;
  for (const el of pool) {
    const cleaned = clone(el);
    const s = score(cleaned);
    if (s < 0) continue;
    if (!best || s > best.score) {
      const t = textOf(cleaned);
      bestEl = el;
      best = {
        score: s,
        text: t,
        selector: nameOf(el),
        link_ratio: t.length ? Math.round((linkChars(cleaned) / t.length) * 100) : 0,
      };
    }
  }
  if (best && bestEl) {
    try {
      const lined = (separated(bestEl).textContent || '').trim();
      if (lined) best.text = lined;
    } catch (e) { /* 줄 나누기는 거들 뿐 — 실패하면 예전 글 그대로 */ }
  }
  // ★ **사이트 레시피가 읽을 자리를 알려 줬으면 그 자리들을 읽는다** (2026-10-04 실전 판 e055235f · 사람인 → 엑셀).
  //   사람인의 공고 편집기 템플릿은 본문을 `<main class="job-posting">` 으로 감싼다 — 회사가 쓴 영역 **안**의 main 이다.
  //   「<main> 이 있으면 그대로 믿는다」 규칙이 그 안만 읽어, 사람인이 채운 「핵심 정보」(근무형태·급여)와 접수기간이 통째로 빠졌다
  //   (공고 11개 중 8개 — 451자·701자·797자…). 모델은 본문에 적힌 것만으로 형태·마감을 채웠다.
  //   믿을 태그를 고르는 범용 규칙은 그대로 둔다(위키백과 99%·허깅페이스 100%·깃허브 85% 는 main 이 곧 본문이다).
  //   자리가 **둘 이상** 보일 때만 쓴다 — 사이트가 화면을 바꿔 자리가 없어지면 예전 고르기로 돌아간다.
  if (Array.isArray(readSelectors) && readSelectors.length) {
    const parts = [];
    const names = [];
    for (const sel of readSelectors) {
      let el = null;
      try { el = document.querySelector(sel); } catch (e) { el = null; }
      if (!el || !visible(el)) continue;
      let t = '';
      try { t = (separated(el).textContent || '').trim(); } catch (e) { t = textOf(clone(el)); }
      if (t) { parts.push(t); names.push(sel); }
    }
    const joined = parts.join(NL + NL);
    if (names.length >= 2 && joined.length >= 140) {
      best = {
        score: Math.max(best ? best.score : 0, joined.length),
        text: joined,
        selector: 'recipe: ' + names.join(' + '),
        link_ratio: 0,
        read_places: names.length,
      };
    }
  }
  // ★ 본문 자리의 **큰 그림**을 센다 (2026-10-04 사람인 공고 21개 중 통이미지 1~2개: 글자 0자·그림 1장 / 255자·9장).
  //   글자가 없다고 「내용 없는 페이지」가 아니다 — 내용이 그림 안에 있다. 파이썬 쪽이 글자 수와 견줘 그렇게 말한다.
  //   로고·아이콘은 빼려고 그려진 크기로 본다(가로 300·세로 200 이상).
  try {
    //   세로로 긴 그림(가로 500·세로 1000 이상)은 따로 센다 — 사진이 아니라 「상세 내용을 통째로 그린 그림」의 모양이다.
    //   ★ **페이지 전체에서** 센다. 고른 본문 덩어리 안만 셌더니 실전 첫 판(9cbe4dde)에서 통이미지 공고(765×8501 한 장 · 글자 0자)를
    //     놓쳤다 — 고른 덩어리는 위쪽 요약이었고 그림은 그 밖의 본문 자리에 있었다. 광고 띠(300×250·160×600)는 긴 그림 기준에 안 든다.
    let big = 0, tall = 0;
    // 그 그림들의 주소 — 파이썬 쪽이 그림을 받아 모델에게 읽힌다(「그림에서 읽은 글」). 몇 장만.
    const bigSrcs = [], tallSrcs = [];
    for (const img of document.querySelectorAll('img')) {
      const r = img.getBoundingClientRect();
      const w = r.width || img.naturalWidth || 0, h = r.height || img.naturalHeight || 0;
      const src = img.currentSrc || img.src || '';
      if (w >= 300 && h >= 200) { big += 1; if (src && bigSrcs.length < 4) bigSrcs.push(src); }
      if (w >= 500 && h >= 1000) { tall += 1; if (src && tallSrcs.length < 3) tallSrcs.push(src); }
    }
    if (best) { best.big_images = big; best.tall_images = tall; best.big_image_srcs = bigSrcs; best.tall_image_srcs = tallSrcs; }
    else if (big) return { score: -1, text: '', selector: '', link_ratio: 0, big_images: big, tall_images: tall,
                           big_image_srcs: bigSrcs, tall_image_srcs: tallSrcs };
  } catch (e) { /* 세지 못해도 글은 그대로 준다 */ }
  return best;
}
"""

# 화면 장치(머리말·메뉴·꼬리말) 안에 있는 링크의 주소들.
#
# ★ 2026-08-06, MCP 로 붙이고 나서야 드러났다. 그때까지 검증은 **로그아웃된 임시
# 프로필**로만 했는데, 사용자가 실제로 쓰는 브라우저는 네이버에 로그인돼 있다.
# 로그인하면 검색 화면 머리말에 계정 위젯이 붙는다:
#
#     1위 네이버톡   talks.naver.com
#     2위 알림 58    m.notify.naver.com     <- 결과 8칸 중 3칸을 먹었다
#     3위 메일 4     mail.naver.com
#     4위~ 진짜 블로그 결과
#
# `browser_open_result rank=1` 이 네이버톡을 연다는 뜻이다.
#
# 호스트를 하나씩 늘려 막지 않는다 — 서비스는 계속 생기고, 그 목록은 영원히 안 끝난다.
# 대신 **어디에 있는가**로 판정한다: 결과는 본문에 있고 계정 위젯은 머리말에 있다.
# 이 구별은 사이트를 안 가린다.
_CHROME_LINKS_JS = """
() => {
  const zoneSel = 'header, nav, footer, aside, [role=banner], [role=navigation], [role=contentinfo], ' +
    '#header, #gnb, .gnb, #footer, #lnb, #snb, #topAsideArea';
  const zones = document.querySelectorAll(zoneSel);
  const out = [];
  for (const zone of zones) {
    for (const a of zone.querySelectorAll('a[href]')) {
      if (a.href) out.push(a.href);
      if (out.length >= 400) return out;
    }
  }
  // ★ 섀도 DOM 이 **겹으로** 있으면 머리말 안의 링크가 또 다른 섀도 루트 속에 있다 (2026-09-29 MS 스토어 M4).
  //   header > nav > nav-bar(섀도) > a — `zone.querySelectorAll` 은 nav-bar 안으로 못 들어가 머리 링크
  //   「유니버설 Microsoft 웹 사이트」가 검색 결과 1위가 됐다. 링크에서 **호스트를 넘어** 위로 올라가며 본다.
  if (__deepRoots.length > 1) {
    const seen = new Set(out);
    for (const a of document.querySelectorAll('a[href]')) {
      if (!a.href || seen.has(a.href)) continue;
      for (let el = a.parentElement, depth = 0; el && depth < 40; el = el.parentElement, depth++) {
        if (el.matches && el.matches(zoneSel)) { out.push(a.href); seen.add(a.href); break; }
      }
      if (out.length >= 400) return out;
    }
  }
  return out;
}
"""

# 이 페이지의 링크 전부. 앵커 글자와 함께 — 주소만으로는 무엇인지 모른다.
_COLLECT_LINKS_JS = """
() => {
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href;
    if (!href || href.startsWith('javascript:')) continue;
    const rect = a.getBoundingClientRect();
    if (!rect.width && !rect.height) continue;
    out.push({ href, text: (a.innerText || a.title || a.getAttribute('aria-label') || '').trim() });
    if (out.length >= 400) break;
  }
  return out;
}
"""
# ── 쿠키·동의 창의 「모두 허용」 (2026-10-02, `_steer_consent_click`) ───────────────────────────────
#: 「사용자 대신 동의」가 되는 버튼 이름. 동의 창 안일 때만 돌린다(밖이면 그대로 누른다).
_CONSENT_ACCEPT = re.compile(
    r"(모두|전체)\s*(허용|수락|동의)|^\s*(허용|수락|동의|동의함|동의합니다)\s*$|"
    r"accept\s*(all|cookies)|allow\s*(all|cookies)|agree\s*(and|&)\s*(close|continue)|^\s*(accept|agree|i\s*agree|allow)\s*$",
    re.IGNORECASE,
)
_CONSENT_STEER_JS = r"""
(el) => {
  const ctxRe = /쿠키|cookie|개인정보|consent|privacy|추적|tracking/i;
  const noRe = /(모두\s*거부|거부|거절|필수만|필수\s*쿠키만|필수\s*항목만|reject|decline|deny|refuse|necessary\s*only|only\s*necessary|essential\s*only|only\s*essential)/i;
  const closeRe = /^(×|✕|✖|닫기|close)$/i;
  const label = (c) => ((c.innerText || c.value || c.getAttribute('aria-label') || c.title || '') + '').trim();
  let box = el;
  for (let i = 0; i < 8 && box && box.parentElement; i++) {
    box = box.parentElement;
    if (!ctxRe.test((box.innerText || '').slice(0, 3000))) continue;
    const cands = [...box.querySelectorAll('button, a, [role="button"], input[type="button"]')].filter(c => c !== el);
    let pick = cands.find(c => noRe.test(label(c)));
    let kind = 'decline';
    if (!pick) { pick = cands.find(c => closeRe.test(label(c))); kind = 'close'; }
    if (pick) { pick.setAttribute('data-jarvis-consent', '1'); return {consent: true, kind, label: label(pick).slice(0, 60)}; }
    return {consent: true, kind: 'none', label: ''};
  }
  return {consent: false};
}
"""

# ── `javascript:함수(인자)` 링크 (2026-10-02, `BrowserController._follow_js_link`) ────────────────────
#: 단순한 함수 호출 하나만 받는다 — `javascript:go_view(178802)`·`javascript:fnDetail('A12', 3);void(0)`.
_JS_LINK = re.compile(
    r"^\s*javascript\s*:\s*([A-Za-z_$][\w$]{0,60})\s*\(\s*(.*?)\s*\)\s*;?\s*(?:void\s*\(?\s*0\s*\)?\s*;?\s*)?$",
    re.IGNORECASE | re.DOTALL,
)
#: 이동처럼 보이는 함수 이름. 이게 **없으면** 대신 부르지 않는다.
_JS_LINK_NAVIGATES = re.compile(r"view|detail|go|move|open|link|page|show|read|nav|select|list|tab|more|info", re.IGNORECASE)
#: 무언가를 **하는** 이름. 하나라도 있으면 이동처럼 보여도 대신 부르지 않는다 — 클릭(승인 규칙)으로 보낸다.
_JS_LINK_ACTS = re.compile(
    r"del|remove|drop|submit|save|write|regist|apply|pay|buy|order|cart|logout|signout|withdraw|cancel|send|mail|"
    r"upload|down|print|confirm|agree|join|login|vote|like|scrap|report|edit|modify|update|insert|reset",
    re.IGNORECASE,
)
_JS_ARG = re.compile(r"\s*(-?\d+(?:\.\d+)?|'[^'\\]{0,200}'|\"[^\"\\]{0,200}\")\s*(?:,|$)")


def _js_literal_args(raw: str) -> list[Any] | None:
    """`178802, 'A1'` → `[178802, 'A1']`. 숫자·따옴표 글자가 아닌 것이 하나라도 있으면 None(대신 부르지 않는다)."""
    text = (raw or "").strip()
    if not text:
        return []
    out: list[Any] = []
    pos = 0
    while pos < len(text):
        found = _JS_ARG.match(text, pos)
        if not found or found.end() == pos:
            return None
        token = found.group(1)
        if token[0] in "'\"":
            out.append(token[1:-1])
        else:
            out.append(float(token) if "." in token else int(token))
        pos = found.end()
        if len(out) > 8:
            return None
    return out


#: 숫자 굴림 띠(「0 1 2 … 9」가 한 칸에 세로로 쌓인 것) — 글로 읽으면 열 숫자가 다 나온다.
_ROLLER_RUN = re.compile(r"0\s*1\s*2\s*3\s*4\s*5\s*6\s*7\s*8\s*9")

#: 숫자 굴림 칸마다 **지금 보이는 숫자** — 문서 순서대로. 바깥 칸(overflow 로 잘린 자리)과 가장 많이 겹치는 자식이 보이는 숫자다.
#: ★ 2026-10-02 가격표 판: Manus 가격이 굴림 띠라 글로는 「$ 0 1 2 … 9 0 1 2 … 9 / 월」이었다. 모델은 「스크린샷으로 확인」을
#:   네 번 말하고 못 했다. 실제 페이지를 재 보니 칸 높이 33px · 바깥 overflow hidden · 보이는 숫자는 바깥과 같은 높이의 자식 하나
#:   — 그림이 아니라 **위치**로 정확히 읽힌다.
_ROLLER_DIGITS_JS = _deep_js("""() => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length < 10) continue;
    const text = (el.textContent || '').replace(/\\s+/g, '');
    if (text !== '0123456789') continue;
    let clip = el.parentElement;
    while (clip && clip !== document.body && getComputedStyle(clip).overflow === 'visible') clip = clip.parentElement;
    const box = (clip || el).getBoundingClientRect();
    let best = '', overlap = 0;
    for (const child of el.children) {
      const r = child.getBoundingClientRect();
      const seen = Math.max(0, Math.min(r.bottom, box.bottom) - Math.max(r.top, box.top));
      if (seen > overlap) { overlap = seen; best = (child.textContent || '').trim(); }
    }
    out.push(/^[0-9]$/.test(best) ? best : '');
  }
  return out;
}""")


_ROLLER_RUNS = re.compile(rf"{_ROLLER_RUN.pattern}(?:\s*{_ROLLER_RUN.pattern})*")


def _fold_rollers(text: str, digits: list[str]) -> str:
    """글 속 굴림 띠를 차례대로 보이는 숫자로 바꾼다. 붙어 있는 칸들은 한 수로 잇는다(「2」「0」 → 20).
    못 읽은 칸은 「?」로 — 열 숫자를 그대로 두지 않는다."""
    queue = list(digits)

    def run(match: "re.Match[str]") -> str:
        count = len(_ROLLER_RUN.findall(match.group(0)))
        return "".join((queue.pop(0) if queue else "") or "?" for _ in range(count))

    return _ROLLER_RUNS.sub(run, text)


def _js_nav_link(href: str) -> tuple[str, list[Any]] | None:
    """이동용 `javascript:함수(글자·숫자 인자)` 링크면 `(함수, 인자)`. 지우기·제출 같은 이름·인자 없는 호출은 None."""
    match = _JS_LINK.match(href or "")
    if not match:
        return None
    name, args = match.group(1), _js_literal_args(match.group(2))
    if not args or not _JS_LINK_NAVIGATES.search(name) or _JS_LINK_ACTS.search(name):
        return None
    return name, args


def _route_pattern(url: str, args: list[Any]) -> str:
    """도착한 주소에서 인자 값을 `{1}`·`{2}` 로 바꾼 **주소 모양**(호스트 빼고). 인자가 주소에 안 나오면 빈 값."""
    parsed = urlparse(url or "")
    tail = parsed.path or "/"
    if parsed.query:
        tail += "?" + parsed.query
    hit = False
    for index, value in enumerate(args, 1):
        token = str(value).strip()
        if len(token) < 2:
            continue
        replaced = re.sub(rf"(?<![\w]){re.escape(token)}(?![\w])", f"{{{index}}}", tail)
        if replaced != tail:
            tail, hit = replaced, True
    return tail[:160] if hit else ""


#: 주소 모양에서 뺄 꼬리표 — 검색 세션·추적용이라 길만 길게 만든다.
_ROUTE_NOISE_KEYS = re.compile(r"^(utm_|fbclid|gclid|search_uuid|uuid|location|paid_fl|t_ref|t_content|t_category|referNonce|ref|from)", re.IGNORECASE)


def _read_route_pattern(url: str) -> str:
    """읽은 페이지 주소의 **모양**: 호스트 빼고, 세 자리 넘는 숫자는 `{n}`, 추적용 꼬리표·긴 값은 뺀다. 첫 화면(`/`)은 빈 값."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        return ""
    path = parsed.path or "/"
    if path.strip("/") == "" and not parsed.query:
        return ""
    keep = []
    for pair in (parsed.query or "").split("&"):
        key, _, value = pair.partition("=")
        if not key or _ROUTE_NOISE_KEYS.match(key) or len(value) > 40:
            continue
        keep.append(f"{key}={value}" if _ else key)
    tail = path + ("?" + "&".join(keep) if keep else "")
    # 번호는 **네 자리 이상**만 `{n}` 로 — 세 자리면 분류 코드(`pbancClssCd=PBC010`)까지 번호로 읽혀, K-Startup 목록 주소 넷이
    # 「상세 모양」인 척 기억 다섯 칸 중 넷을 차지했다(10-02 새벽 실측). 상세 번호(pbancSn·rec_idx)는 여섯 자리 이상이다.
    return re.sub(r"\d{4,}", "{n}", tail)[:160]


_EXTRACT_MAIN_JS = _deep_js(_EXTRACT_MAIN_JS)
_CHROME_LINKS_JS = _deep_js(_CHROME_LINKS_JS)
_COLLECT_LINKS_JS = _deep_js(_COLLECT_LINKS_JS)


_EDITABLE_TAGS = frozenset({"input", "textarea", "select"})
_FIELD_WORDS = re.compile(r"칸|입력|값|필드|field|input|box|textbox", re.I)


def _near_find_candidates(query: str, rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """글자 그대로는 없을 때 **이름이 겹치는** 후보 몇 개 (2026-09-29 AWS 할당량 판).

    「새 할당량」으로 찾아 0건이 나오자 모델은 그대로 「입력란을 찾을 수 없다」고 끝냈다 — 그 창의 칸 이름은 다른 말이었다.
    두 글자 이상 낱말이 이름에 몇 개 들어 있나로 줄 세운다. 칸·입력·값을 찾는 말이면 입력 요소를 앞에 둔다.
    """
    words = [word for word in re.split(r"[\s,·/()\[\]「」'\"]+", query.lower()) if len(word) >= 2 and not _FIELD_WORDS.fullmatch(word)]
    if not words:
        return []
    wants_field = bool(_FIELD_WORDS.search(query))
    scored: list[tuple[int, int, int, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        name = str(row.get("name") or "").lower()
        hits = sum(1 for word in words if word in name)
        if not hits:
            continue
        editable = str(row.get("tag") or "").lower() in _EDITABLE_TAGS
        scored.append((hits, int(editable and wants_field), -index, row))
    scored.sort(key=lambda item: (item[1], item[0], item[2]), reverse=True)
    return [
        {"ref": row.get("ref"), "name": _clean(row.get("name"), 80), "tag": row.get("tag") or ""}
        for _hits, _field, _order, row in scored[:limit]
    ]


#: 주소 경로의 언어·지역 조각(`/ko`, `/ko-KR`, `/en_US`).
_LOCALE_SEGMENT = re.compile(r"^(?:ko|kr|en|ja|jp|zh|de|fr|es|pt|it|ru|vi|th|id)(?:[-_][a-z]{2})?$", re.IGNORECASE)

#: ★ 2026-10-02 협업 1차 판(33a2437f): 「미국 영어 가격 페이지 기준(claude.com/pricing)」을 지키려고 같은 주소를 다섯 번 열었다 —
#:   사이트가 한국 IP 를 보고 `/ko/pricing` 으로 돌려보냈고, 지어낸 `/en_US/pricing` 은 404 였다. 요청에 대안(「원화만 보이면 원화
#:   그대로」)이 적혀 있었는데도 넘어가지 않았다. 다시 열어도 같다는 것을 **도구가** 말한다(안내문이 아니라 관측된 사실).
LOCALE_REDIRECT_NOTE = (
    "★ [도구가 보낸 안내] 연 주소가 이 PC 의 접속 지역에 맞춘 주소로 바뀌었다({asked} → {landed}). 사이트가 지역을 보고 "
    "보내는 것이라 같은 주소를 다시 열어도, 다른 지역 주소를 지어내도(대개 404) 바뀌지 않는다. 특정 지역·언어 페이지를 "
    "요구한 지시는 이 PC 에서 지킬 수 없다 — 요청에 대안이 적혀 있으면 그걸 따르고, 없으면 지금 페이지로 하되 "
    "답에 「지역 페이지로 바뀌어 그 페이지 기준으로 적었다」고 밝혀라."
)


def _locale_segments(path: str) -> list[str]:
    return [part.lower().replace("_", "-") for part in (path or "").split("/") if _LOCALE_SEGMENT.match(part)]


def locale_redirect(asked: str, landed: str) -> dict[str, str] | None:
    """요청한 주소가 **같은 사이트의 다른 언어·지역 주소**로 바뀌었으면 `{asked, landed}`. 아니면 None."""
    a, b = urlparse(asked or ""), urlparse(landed or "")
    if not a.netloc or not b.netloc or a.netloc.lower().removeprefix("www.") != b.netloc.lower().removeprefix("www."):
        return None
    landed_locales = _locale_segments(b.path)
    if not landed_locales or landed_locales == _locale_segments(a.path):
        return None
    return {"asked": asked[:160], "landed": landed[:160]}


#: 조립한 글 주소를 목록의 진짜 주소로 바꿔 열었을 때 결과에 싣는 말.
ADDRESS_REPAIRED_NOTE = (
    "요청한 주소의 글 번호는 이 목록에 없었습니다. 목록에 있는 같은 제목의 실제 글을 대신 열었습니다. "
    "글 주소는 짐작해서 만들지 말고 browser_links 로 받아 그대로 여세요."
)

#: 글·항목 번호처럼 보이는 경로 조각 — 숫자가 섞인 5~14자 영숫자(레딧 `1wq5x2j`, 스택오버플로 `79012345`).
_ITEM_ID_SEGMENT = re.compile(r"^(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{5,14}$")
_SLUG_WORD = re.compile(r"[A-Za-z0-9\uac00-\ud7a3]{3,}")
#: 제목 꼬리의 낱말이 이 비율 미만으로 겹치면 「다른 글」로 본다. 운영 기록의 여섯 건은 0, 한 건은 1/7 이었다.
_SLUG_OVERLAP_MIN = 0.34


def wrong_item_redirect(asked: str, landed: str) -> dict[str, str] | None:
    """요청한 주소의 **번호는 맞는데 제목이 전혀 다른 글**로 갔으면 `{id, asked_title, landed_title}`. 아니면 None.

    ## 왜 (2026-10-04 새벽 실측, 판 `df35948f`)

    레딧 검색 결과를 **글자로만** 읽은 모델이 「진짜 제목 + 지어낸 글 번호」로 주소를 조립했다:

        연 주소   /r/LocalLLaMA/comments/1wq5x2j/who_wants_to_try_a_pi_trick_for_27b…
        간 곳     /r/Hookups_Florida/comments/1wq5x2j/26f_would_you_wanna…

    레딧은 번호만 보고 그 번호의 글로 보낸다. 도구는 「열었다」고 돌려줬고, 그 걸음은 「읽은 글」로 세어졌다.
    운영 기록 1,859번의 열기 가운데 일곱 번(네 판) — 전부 레딧, 여섯이 성인 게시판이었다. 사용자의 **실제 크롬**에 뜬다.

    ## 무엇을 잡나

    같은 사이트 · 같은 번호 조각 · 요청에 **제목 꼬리가 있고**(모델이 「이 제목의 글」이라고 주장) · 도착한 제목 꼬리와
    낱말이 안 겹친다(하나도 없거나, 게시판까지 바뀌고 거의 없거나). 제목을 안 붙인 주소(`/comments/1abc/`)는 주장이 없으니 안 잡는다 — 게시판만 바뀐 정상
    이동일 수 있다. 제목이 조금 다른 것(잘린 꼬리·고친 제목)은 낱말이 겹쳐 통과한다.
    """
    a, b = urlparse(asked or ""), urlparse(landed or "")
    if not a.netloc or not b.netloc or _bare_host(a.netloc) != _bare_host(b.netloc):
        return None
    asked_parts = [part for part in a.path.split("/") if part]
    landed_parts = [part for part in b.path.split("/") if part]
    if asked_parts == landed_parts:
        return None
    for index, part in enumerate(asked_parts[:-1]):
        if not _ITEM_ID_SEGMENT.match(part) or part not in landed_parts:
            continue
        at = landed_parts.index(part)
        if at + 1 >= len(landed_parts):
            continue
        asked_title, landed_title = asked_parts[index + 1], landed_parts[at + 1]
        asked_words = {word.lower() for word in _SLUG_WORD.findall(asked_title)}
        landed_words = {word.lower() for word in _SLUG_WORD.findall(landed_title)}
        if len(asked_words) < 3 or not landed_words:
            continue
        shared = len(asked_words & landed_words)
        # 낱말이 **하나도** 안 겹치거나, 조금 겹쳐도 번호 앞 경로(게시판)까지 바뀌었을 때만 「다른 글」이다.
        # 같은 자리에서 제목만 바뀐 것은 고친 제목일 수 있다 — 운영 기록의 statista `…/study/104511/…` 가 그랬다
        # (「digital-trends-in-finance…」 → 「fintech-trends-2022」, 같은 주제). 멀쩡한 페이지를 막는 쪽이 더 나쁘다.
        moved_place = asked_parts[:index] != landed_parts[:at]
        if shared == 0 or (moved_place and shared / len(asked_words) < _SLUG_OVERLAP_MIN):
            return {"id": part, "asked_title": asked_title[:120], "landed_title": landed_title[:120]}
    return None


def _item_and_title(url: str) -> tuple[str, tuple[str, ...], str, frozenset[str]] | None:
    """`…/<번호>/<제목 꼬리>` 모양의 주소면 (사이트, 번호 앞 경로, 번호, 제목 낱말). 아니면 None."""
    parsed = urlparse(url or "")
    if not parsed.netloc:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if not _ITEM_ID_SEGMENT.match(part):
            continue
        words = frozenset(word.lower() for word in _SLUG_WORD.findall(parts[index + 1]))
        if len(words) >= 3:
            return _bare_host(parsed.netloc), tuple(parts[:index]), part, words
    return None


#: 목록의 링크를 「같은 제목의 글」로 보려면 겹쳐야 하는 낱말 비율(짧은 쪽 기준)과 최소 개수.
_SAME_TITLE_MIN = 0.8
_SAME_TITLE_WORDS = 3


def real_link_for(asked: str, links: list[str]) -> str:
    """모델이 조립한 글 주소(`asked`) 대신 열 **목록에 실제로 있는 주소**. 없거나 애매하면 빈 문자열.

    ## 왜 (2026-10-04, 판 `df35948f`)

    검색 결과를 글자로 읽은 모델은 제목은 알고 주소는 모른다. 그래서 「진짜 제목 + 지어낸 번호」로 주소를 만든다.
    그 글은 **지금 보고 있는 목록에 링크로 있다.** 안내문(「browser_links 로 주소를 받아라」)은 안 먹는다(사고 R) —
    도구가 목록에서 같은 제목의 링크를 찾아 그걸 연다. 검색 주소를 조립해 오면 대신 검색칸에 쳐 넣는 것과 같은 방식이다.

    조심하는 것:
    - 요청한 번호가 목록에 **그대로 있으면** 지어낸 것이 아니다 — 손대지 않는다.
    - 같은 사이트 · 같은 자리(게시판)의 링크만 본다.
    - 맞는 링크가 **둘 이상**이면 고르지 않는다(틀린 글을 여는 것보다 실패가 낫다).
    """
    wanted = _item_and_title(asked)
    if wanted is None:
        return ""
    host, place, item_id, words = wanted
    found: dict[str, str] = {}
    for link in links:
        other = _item_and_title(str(link or ""))
        if other is None or other[0] != host:
            continue
        if other[2] == item_id:
            return ""  # 요청한 번호가 목록에 있다 — 진짜 주소다
        if other[1] != place:
            continue
        shared = len(words & other[3])
        if shared >= _SAME_TITLE_WORDS and shared / min(len(words), len(other[3])) >= _SAME_TITLE_MIN:
            found.setdefault(other[2], str(link))
    return next(iter(found.values())) if len(found) == 1 else ""


def _bare_host(netloc: str) -> str:
    host = str(netloc or "").lower()
    for prefix in ("www.", "old.", "new.", "m."):
        host = host.removeprefix(prefix)
    return host


#: 한 주소에 **여러 항목을 쌓아** 보여 주는 화면과, 같은 항목 **하나만** 보여 주는 주소 — (호스트, 쌓는 경로, 번호 인자, 하나만 보는 경로).
#:
#: ★ 2026-10-04 채용 공고 조사 판(788ef850). 사람인 검색 결과의 링크는 「이어 보기」(`/jobs/relay/view`)로 간다 — 연 공고 아래에
#:   **다음 공고들이 통째로 쌓이고**(틀 `iframe_content_0`·`_1`·`_2` …), 읽기 전에 페이지를 끝까지 훑으면 더 실린다. 그 판은 공고 21개를
#:   열어 제 공고의 상세 본문을 읽은 것이 2개였고, 2개는 옆 공고(두레기계공업)를 읽었다. 같은 번호의 단독 보기(`/jobs/view`)는
#:   공고 하나만 나오고 요약과 본문이 한 화면에 같이 있다(라이브에서 `rec_idx=51000001` 로 확인: 구역 1개 · 틀 0개 · 5,383자).
#:   읽으러 갈 때만 바꾼다 — 사람이 검토한 절차(스크랩·관심기업)는 그 화면에서 셀렉터를 세어 정했으니 손대지 않는다.
_STACKED_ITEM_VIEWS = (
    ("saramin.co.kr", "/zf_user/jobs/relay/view", "rec_idx", "/zf_user/jobs/view"),
)


def single_item_view(url: str) -> str:
    """여러 항목을 쌓아 보여 주는 주소면 그 항목 하나만 보는 주소로. 아니면 그대로."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return url
    host = _bare_host(parsed.netloc)
    for site, stacked, key, single in _STACKED_ITEM_VIEWS:
        if (host == site or host.endswith("." + site)) and parsed.path.rstrip("/") == stacked:
            number = (parse_qs(parsed.query).get(key) or [""])[0]
            if number.isdigit():
                return f"{parsed.scheme}://{parsed.netloc}{single}?{key}={number}"
    return url


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _is_poisoned_thread_start(exc: BaseException) -> bool:
    """브라우저 **시작**이 「이 스레드에 옛 asyncio 루프가 남아 있다」로 실패했나 — 스레드를 바꾸면 켜지는 경우."""
    text = str(exc)
    return text.startswith("browser_start_failed") and "Sync API inside the asyncio loop" in text


_REDDIT_POST = re.compile(
    r"^https?://(?:www\.|old\.|new\.)?reddit\.com(/r/[A-Za-z0-9_]+/comments/[a-z0-9]+)(?:\.json)?(?:/[^?#]*)?(?:[?#].*)?$", re.I)


def reddit_post_json_url(url: str) -> str:
    """레딧 글 주소 → 같은 글의 `.json` 주소. 글이 아니면 빈 값.

    ★ 2026-10-03 22시 예약 판(5fa9b74c): 모델이 `.json` 을 **직접** 열자 「이미 .json 이면 빈 값」 규칙 때문에 요약이 안 붙었고,
      원문 JSON 은 2만 자에서 잘려 댓글을 다 못 읽었다. `.json` 주소도 같은 요약을 받는다.
    """
    match = _REDDIT_POST.match(str(url or "").strip())
    if not match:
        return ""
    path = match.group(1)
    return f"https://www.reddit.com{path[:-5] if path.endswith('.json') else path}.json"


#: 레딧 **글 목록**의 정렬 이름(게시판 첫 화면·검색 결과도 목록이다).
_REDDIT_SORTS = frozenset({"hot", "new", "top", "rising", "best", "controversial"})


def reddit_listing_json_url(url: str) -> str:
    """레딧 글 목록 주소(게시판·정렬·검색) → 같은 목록의 `.json` 주소. 목록이 아니면 빈 값.

    ★ 2026-10-04 레딧 기준선 판 셋(92b3776a·b79871c7·70d6cffc): 「글 25개의 제목·댓글 수·추천 수」가 세 번 중 한 번만
      깔끔히 됐다. 댓글·추천 숫자는 화면 구성 요소 안에 있어 본문 추출에 안 잡히고, 모델은 판마다 다른 길(`.json` 을 열어
      읽기 · 내려받아 상자에서 풀기 · 화면에서 「댓글」 찾기 일곱 번)을 찾다 운에 따라 갈렸다. 그리고 목록을 글자로만 읽은
      모델은 제목은 알고 **주소는 몰라서** 글 번호를 지어냈다(열기 1,859번 중 7번, 여섯이 성인 게시판).
      글 한 편에는 이미 해 주던 일(`_attach_post_stats`)을 목록에도 한다 — 결정론으로 박을 수 있으면 코드로(사고 R).
    """
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or _bare_host(parsed.netloc) != "reddit.com":
        return ""
    path = parsed.path.rstrip("/")
    if path.lower().endswith(".json"):
        path = path[:-5].rstrip("/")
    parts = [part for part in path.split("/") if part]
    lowered = [part.lower() for part in parts]
    if "comments" in lowered:
        return ""  # 글 한 편 — `reddit_post_json_url` 의 일이다
    in_board = len(parts) >= 2 and lowered[0] == "r"
    rest = lowered[2:] if in_board else lowered
    if rest and not (len(rest) == 1 and (rest[0] in _REDDIT_SORTS or rest[0] == "search")):
        return ""  # 위키·규칙·사용자 페이지 등
    if not in_board and not rest:
        return ""  # 맨 첫 화면은 사람마다 다른 추천 목록이다 — 건드리지 않는다
    if rest == ["search"] and "q=" not in (parsed.query or ""):
        return ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"https://www.reddit.com/{'/'.join(parts)}.json{query}"


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{max(1, seconds // 60)}분 전"
    if seconds < 48 * 3600:
        return f"{seconds // 3600}시간 전"
    return f"{seconds // 86400}일 전"


def reddit_listing_items(payload: Any, *, now: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """레딧 목록 `.json` 응답 → 글마다 `{title, num_comments, score, age, created_local, url, subreddit}`. 모양이 다르면 빈 목록."""
    try:
        children = payload["data"]["children"]
    except (KeyError, TypeError):
        return []
    stamp = time.time() if now is None else float(now)
    items: list[dict[str, Any]] = []
    for child in children if isinstance(children, list) else []:
        post = child.get("data") if isinstance(child, dict) and child.get("kind") == "t3" else None
        if not isinstance(post, dict) or not post.get("permalink") or not post.get("title"):
            continue
        try:
            item: dict[str, Any] = {
                "title": _clean(post["title"], 300),
                "num_comments": int(post.get("num_comments") or 0),
                "score": int(post.get("score") or 0),
                "url": "https://www.reddit.com" + str(post["permalink"]),
            }
        except (TypeError, ValueError):
            continue
        if post.get("subreddit_name_prefixed") or post.get("subreddit"):
            item["subreddit"] = _clean(post.get("subreddit_name_prefixed") or f"r/{post['subreddit']}", 80)
        if isinstance(post.get("upvote_ratio"), (int, float)):
            item["upvote_ratio"] = post["upvote_ratio"]
        if isinstance(post.get("created_utc"), (int, float)):
            item["age"] = _ago(stamp - post["created_utc"])
            item["created_local"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(post["created_utc"]))
        if post.get("stickied"):
            item["pinned"] = True
        items.append(item)
        if len(items) >= limit:
            break
    return items


def reddit_post_stats(payload: Any) -> dict[str, Any]:
    """레딧 글 `.json` 응답에서 점수·댓글 수·추천 비율 · 제목·게시판·올린 시각(UTC). 모양이 다르면 빈 값."""
    try:
        post = payload[0]["data"]["children"][0]["data"]
        stats: dict[str, Any] = {"score": int(post["score"]), "num_comments": int(post["num_comments"])}
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    ratio = post.get("upvote_ratio")
    if isinstance(ratio, (int, float)):
        stats["upvote_ratio"] = ratio
    if post.get("title"):
        stats["title"] = _clean(post["title"], 300)
    if post.get("subreddit_name_prefixed") or post.get("subreddit"):
        stats["subreddit"] = _clean(post.get("subreddit_name_prefixed") or f"r/{post['subreddit']}", 80)
    if isinstance(post.get("created_utc"), (int, float)):
        stats["created_utc"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime(post["created_utc"]))
        # 이 PC 시각도 같이 — 모델이 UTC 를 스스로 바꿔 쓰면 숫자 문이 「읽은 자료에 없는 숫자」로 막는다(10-03 재실행 50bc9afe).
        stats["created_local"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(post["created_utc"]))
    if isinstance(post.get("view_count"), int):
        stats["view_count"] = post["view_count"]
    return stats


def reddit_post_comments(payload: Any, limit: int = 80) -> tuple[list[dict[str, Any]], int]:
    """레딧 글 `.json` 의 댓글 — `([{작성자, 점수, 깊이, 요지}], 더 있는 수)`. 트리를 위에서부터 펼친다.

    `more` 칸(접힌 댓글)은 읽지 않고 그 개수만 센다 — 읽지 않은 것을 읽었다고 하지 않게.
    """
    out: list[dict[str, Any]] = []
    hidden = 0
    try:
        roots = payload[1]["data"]["children"]
    except (KeyError, IndexError, TypeError):
        return [], 0
    stack = [(item, 0) for item in reversed(roots)]
    while stack:
        item, depth = stack.pop()
        if not isinstance(item, dict):
            continue
        data = item.get("data") or {}
        if item.get("kind") == "more":
            hidden += int(data.get("count") or 0)
            continue
        if item.get("kind") != "t1":
            continue
        if len(out) < limit:
            body = " ".join(str(data.get("body") or "").split())
            out.append({"author": _clean(data.get("author"), 40), "score": data.get("score"), "depth": depth,
                        "gist": body[:160] + ("…" if len(body) > 160 else "")})
        else:
            hidden += 1
        replies = data.get("replies")
        if isinstance(replies, dict):
            stack.extend((child, depth + 1) for child in reversed(replies.get("data", {}).get("children") or []))
    return out, hidden


def _clean_lines(value: Any, limit: int = 500) -> str:
    """`_clean` 과 같되 **줄은 살린다** — 본문 추출이 넣은 칸 경계(줄바꿈)를 공백 하나로 뭉치면 다시 붙는다(2026-10-02 사람인)."""
    lines = (" ".join(line.split()) for line in str(value or "").splitlines())
    return "\n".join(line for line in lines if line)[:limit]


#: Content-Type → 확장자. 이름에 확장자가 없을 때만 쓴다.
_EXTENSION_BY_TYPE = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "text/csv": ".csv",
    "text/plain": ".txt",
    "application/zip": ".zip",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


# 주소에 날짜가 실려 있는가. 목록이 "주소로 바꿀 수 있는 종류"인지 가르는 데 쓴다.
_DATE_IN_QUERY = re.compile(r"[?&][A-Za-z_]*=20[2-9][0-9][-./]?[01][0-9][-./]?[0-3][0-9](&|$)")


#: 크롬도 엣지도 없을 때 사람에게 보일 말. 환경변수 이름·Playwright 영어 원문을 사용자 화면에 내보내지 않는다
#: (2026-09-29 밤 AWS: 「chrome_not_found — JARVIS_BROWSER_CHROME_PATH 를 알려주세요」 → 「playwright install」 영어 원문).
NO_BROWSER_MESSAGE = (
    "browser_not_found — 브라우저 일을 하려면 크롬이나 엣지가 필요합니다. "
    "이 PC 에서 둘 다 찾지 못했습니다. 크롬(https://www.google.com/chrome)을 설치한 뒤 다시 시켜 주세요."
)


#: 날짜 칸 종류별 받는 꼴(HTML 표준).
_DATE_INPUT_FORMATS = {"date": "YYYY-MM-DD", "datetime-local": "YYYY-MM-DDTHH:MM", "month": "YYYY-MM", "time": "HH:MM"}
_MONTHS = {name: index for index, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")), 1) for name in names}


def normalize_date_input(kind: str, raw: str) -> str | None:
    """날짜 칸에 넣을 값을 표준 꼴로. 못 읽으면 None — 짐작으로 날짜를 만들지 않는다.

    받는 꼴: 2026-10-05 · 2026.10.05 · 2026/10/05 · 2026년 10월 5일 · 10/05/2026(미국식 월/일) · Oct 5, 2026 · 5 October 2026,
    시간은 14:30 · 2:30 PM. 「05/10/2026」처럼 월·일이 둘 다 12 이하면 미국식(월/일)으로 읽는다 — Mind2Web 사이트가 미국이다.
    """
    text = " ".join(str(raw or "").strip().split())
    low = text.lower()
    hour = minute = None
    clock = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", low)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2))
        if clock.group(3) == "pm" and hour < 12:
            hour += 12
        if clock.group(3) == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
    if kind == "time":
        return f"{hour:02d}:{minute:02d}" if hour is not None else None
    year = month = day = None
    patterns = (
        (r"(\d{4})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})", "ymd"),
        (r"(\d{1,2})/(\d{1,2})/(\d{4})", "mdy"),
        (r"([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", "Mdy"),
        (r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(\d{4})", "dMy"),
        (r"(\d{4})[-./년\s]+(\d{1,2})월?$", "ym"),
    )
    for pattern, order in patterns:
        found = re.search(pattern, low)
        if not found:
            continue
        a, b, c = (found.groups() + (None,))[:3]
        if order == "ymd":
            year, month, day = int(a), int(b), int(c)
        elif order == "mdy":
            month, day, year = int(a), int(b), int(c)
        elif order == "Mdy" and a in _MONTHS:
            month, day, year = _MONTHS[a], int(b), int(c)
        elif order == "dMy" and b in _MONTHS:
            day, month, year = int(a), _MONTHS[b], int(c)
        elif order == "ym":
            year, month, day = int(a), int(b), 1
        else:
            continue
        break
    if not year or not month or not (1 <= month <= 12) or not day or not (1 <= day <= 31):
        return None
    if kind == "month":
        return f"{year:04d}-{month:02d}"
    if kind == "datetime-local":
        return f"{year:04d}-{month:02d}-{day:02d}T{(hour or 0):02d}:{(minute or 0):02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


#: 입력 뒤 보이는 자동완성 후보. 표준(role=option·listbox)과 흔한 꼴(…suggest…·…autocomplete… 안의 li·a·button)을 본다.
_SUGGESTION_SCAN_JS = r"""
(typed) => {
  const seen = new Set(); const out = [];
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const nodes = document.querySelectorAll(
    '[role=listbox] [role=option], [role=option], [class*=suggest] li, [class*=Suggest] li, [class*=autocomplete] li, '
    + '[class*=Autocomplete] li, [id*=suggest] li, [id*=autocomplete] li, ul[role=listbox] > li, .pac-item, [class*=typeahead] li');
  for (const el of nodes) {
    if (out.length >= 8) break;
    if (!visible(el)) continue;
    const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length > 120 || seen.has(text)) continue;
    seen.add(text); out.push(text);
  }
  return out;
}
"""

#: 비밀번호 칸이 **닫을 수 있는 팝업** 안에 있으면 그 팝업의 닫기 단추를 누른다. 눌렀으면 true (2026-10-03 WebMD).
#: 팝업 = 대화창·모달 모양의 조상. 닫기 = 그 안의 단추 중 이름·글자가 닫기 꼴이거나 class/id 에 close 가 든 것.
#: 비밀번호 칸이 든 폼 **바깥**의 읽을 글이 몇 글자인가. 80자 이상인 글 조각만 센다(문단) — 메뉴·링크는 짧다.
#: 숨긴 글과 스크립트·스타일 안의 글은 안 센다. `limit` 를 넘으면 더 세지 않고 돌려준다.
_PROSE_OUTSIDE_LOGIN_JS = """
(nodes, limit) => {
  const forms = nodes.map(node => node.form || node.closest('form')).filter(Boolean);
  const inside = el => forms.some(form => form.contains(el)) || nodes.some(node => node.parentElement === el);
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  let prose = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = String(node.nodeValue || '').replace(/\\s+/g, ' ').trim();
    if (text.length < 80) continue;
    const el = node.parentElement;
    if (!el || inside(el) || el.closest('script,style,noscript,template')) continue;
    const style = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' || box.width === 0 || box.height === 0) continue;
    prose += text.length;
    if (prose >= limit) break;
  }
  return prose;
}
"""

_CLOSE_LOGIN_POPUP_JS = r"""
nodes => {
  const SHELL = '[role=dialog],[aria-modal="true"],dialog,[class*=modal],[class*=Modal],[class*=popup],[class*=Popup],'
    + '[class*=dialog],[class*=Dialog],[class*=lightbox],[class*=Lightbox]';
  const CLOSE_WORD = /^(?:close|closed|dismiss|no thanks|not now|maybe later|skip|cancel|닫기|취소|나중에|다음에|×|✕|✖|x)$/i;
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  for (const node of nodes) {
    const shell = node.closest(SHELL);
    if (!shell) continue;
    const controls = Array.from(shell.querySelectorAll('button,[role=button],a,span,div,i,svg'));
    const close = controls.find((el) => {
      if (!visible(el) || el.contains(node)) return false;
      const name = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim();
      const tag = ((el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : (el.getAttribute('class') || ''))).toLowerCase();
      return CLOSE_WORD.test(name) || /(?:^|[\s_-])close(?:$|[\s_-]|btn|button|icon)/.test(tag);
    });
    if (close) { (close.closest('button,[role=button],a') || close).click(); return true; }
  }
  return false;
}
"""

#: 클릭을 먹은 맨 위 요소가 무엇인가 — 「same_control」(같은 칸의 겉모양) · 「backdrop」(뒷막) · 「other」.
_BLOCKER_RELATION_JS = r"""
el => {
  const rect = el.getBoundingClientRect(); const doc = el.ownerDocument; const win = doc.defaultView;
  const top = doc.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
  if (!top || top === el || el.contains(top)) return 'none';
  const label = el.closest('label') || (el.labels && el.labels[0]);
  if (label && label.contains(top)) return 'same_control';
  if (top.closest('label') && top.closest('label').contains(el)) return 'same_control';
  const kind = (el.getAttribute('type') || '').toLowerCase();
  const tiny = rect.width < 4 || rect.height < 4 || Number(win.getComputedStyle(el).opacity) === 0;
  const near = el.parentElement && (el.parentElement.contains(top)
    || (el.parentElement.parentElement && el.parentElement.parentElement.contains(top) && top.contains(el) === false
        && (kind === 'checkbox' || kind === 'radio' || tiny)));
  if ((kind === 'checkbox' || kind === 'radio' || tiny) && near) return 'same_control';
  const tag = ((top.id || '') + ' ' + (typeof top.className === 'string' ? top.className : '')).toLowerCase();
  const box = top.getBoundingClientRect();
  const covers = box.width * box.height >= 0.6 * win.innerWidth * win.innerHeight;
  if (/backdrop|overlay|scrim|mask|curtain|dim\b|-dim|dimmed|modal-bg/.test(tag) || covers) return 'backdrop';
  return 'other';
}
"""



# 주소 인자 가운데 **이름이 「검색어」를 뜻하는 것** — `searchKeyword` · `SearchKey` · `searchText` · `kwd` · `srchWord` …
# `searchType` · `searchId` · `search_uuid` 처럼 search 를 품기만 한 이름은 아니다(그 값을 검색칸에 치면 엉뚱한 것을 찾는다).
_SEARCH_WORD_PARAM = re.compile(
    r"^(?:k|kwd|search|s(?:ea)?rch_?(?:term|word|key|keyword|query|text))$", re.IGNORECASE
)
# 검색어를 경로 끝에 실은 꼴: `/search/<검색어>` · `/search/keyword/<검색어>`.
_SEARCH_WORD_IN_PATH = re.compile(r"(?:^|/)search(?:/(?:keyword|q|query))?/([^/?#]+)/?$", re.IGNORECASE)


class BrowserWorker:
    """Serialized, persistent Playwright worker for JARVIS.

    Playwright's sync API is bound to the thread that created it. A dedicated
    single-worker executor keeps every browser operation on that same thread
    and isolates it from the API/job-runner threads.
    """

    _RECOVERY_WINDOW_SEC = 10 * 60
    _RECOVERY_LIMIT = 3
    _CIRCUIT_OPEN_SEC = 60
    _MUTATING_ACTIONS = frozenset(
        {
            "browser_click",
            "browser_click_at",
            "browser_click_confirmed",
            "browser_fill",
            "browser_type_at",
            "browser_fill_form",
            "browser_file_upload",
            "browser_handle_dialog",
            "browser_pick_suggestion",
            "browser_press",
            "browser_select_option",
            "naver_blog_draft_save",
            "naver_blog_publish",
        }
    )

    def __init__(self, config: JarvisConfig) -> None:
        from .user_presence import UserPresence

        # 사람이 PC 를 쓰는 중이면 창을 앞으로 안 가져온다(인수인계 H2-A). 뒤에서 한 창 조작 수는 status 에 싣는다.
        self.presence = UserPresence(config)
        self._yielded_front = 0
        # 일하는 동안 크롬을 화면 밖에 펴 둔다(2026-09-24 제품 결정). 정적 창 도우미들이 같이 보므로 클래스에 둔다.
        BrowserWorker._park_offscreen = bool(getattr(config, "browser_park_offscreen", True)) and not bool(getattr(config, "browser_headless", False))
        #: 우리가 만들었거나 우리가 주소를 넣은 탭. 정리 대상은 여기 있는 것뿐이다 —
        #: 사람이 직접 연 탭(로그인 창 등)은 우리 것이 아니다.
        self._our_pages: list[int] = []
        #: 우리 브라우저 동작이 **도는 중**이면 0 보다 크다. 그 사이에 생긴 탭은
        #: 사이트가 우리 클릭 때문에 띄운 것이므로 우리 것으로 센다 (아래 주석 참고).
        self._action_depth: int = 0
        #: pid → 「우리 크롬인가」. 감시 스레드가 0.02초마다 묻는다 — 캐시가 없으면 그때마다
        #: 프로세스 조회를 한다. 크롬을 새로 띄울 때 비운다.
        self._chrome_pid_answers: dict[int, bool] = {}
        #: 탭 눈금. **동작 스레드가** 재서 남긴다 — API 스레드에서 Playwright 를 부르면
        #: 스레드 규칙에 걸려 늘 None 이 된다(그러면 눈금이 아니라 장식이다).
        self._tab_census: dict[str, Any] = {}
        #: 동작을 시작할 때 열려 있던 탭들. 끝날 때 여기 없는 탭은 **그 동작이 띄운 것**이다.
        self._pages_before_action: set[int] = set()
        #: 붙어 쓰는 크롬이 **우리 프로필**의 것인가. 앞 판이 남긴 우리 크롬을 남의 창으로
        #: 읽으면 창도 안 내리고 탭도 안 닫는다(2026-09-16 실측).
        self._attached_is_ours: bool = False
        #: 크롬 프로세스 한 번에 몰아 읽은 결과와 그 시각. pid 마다 물으면 감시 스레드가
        #: 초당 50번 프로세스를 만든다(psutil 이 없는 포장본에서는 특히).
        self._chrome_scan_rows: dict[int, str] = {}
        self._chrome_scan_at: float = 0.0
        #: 크롬을 띄우기 **직전**에 있던 크롬 pid 들. 그 뒤에 생긴 pid 는 우리가 띄운 것이다.
        self._chrome_pids_before_launch: set[int] = set()
        self._launch_watch_until: float = 0.0
        self._birth_guard_stop = threading.Event()
        #: 감시 스레드가 한 일 — 몇 번 돌았나·몇 번 내렸나·몇 번 튀었나. 눈금이 없으면
        #: 「0.0초 판」과 「3.4초 판」이 왜 갈렸는지 물어볼 데가 없다.
        self._sink_report: dict[str, Any] = {}
        self.config = config
        # 브라우저 무대(2026-09-24): 화면 밖 크롬을 온텔릭 창 안에서 보고 만진다. 일꾼 스레드와 따로 CDP 로 붙는다.
        from .live_view import LiveView

        self.live_view = LiveView(self)
        #: 사람이 넘겨받았다가 돌려준 뒤 **다음 도구 결과**에 한 번 싣는 알림. 화면이 바뀌었으니 다시 보라는 뜻이다.
        self._human_took_over: dict[str, Any] | None = None
        # ── 이 탭을 지금 누가 쓰나 (2026-10-19 · `_hold_if_human_on_tab`) ──
        #: 이 판이 **스스로 간** 화면들의 열쇠(`_own_key`) · 그 주소 · 마지막으로 간 주소 · 그 시각.
        self._own_page_keys: set[str] = set()
        self._own_pages: list[str] = []
        self._last_own_page = ""
        self._own_page_at = 0.0
        #: 사람이 무대에서 크롬을 마지막으로 만진(돌려준) 시각. 이 판이 마지막으로 간 뒤에 만졌으면 화면이 사람 손으로 바뀌었을 수 있다.
        self._human_hand_at = 0.0
        #: 사람이 이 탭을 쓰고 있는 것 같아 손을 멈춘 상태 — {"from", "to", "at"}. 이 판이 제 주소를 열거나 「이어서」로 풀린다.
        self._human_on_tab: dict[str, Any] | None = None
        #: 사람이 「이어서」를 눌렀다 — 다음 걸음의 지금 화면을 이 판의 화면으로 받는다(`hand_tab_back`).
        self._tab_handed_back = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-browser")
        # 시간이 끊겼는데도 스레드에 남아 계속 도는 작업. 있으면 다음 호출은
        # 줄 서지 않고 바로 사실을 말한다(`_submit` 주석 참고).
        self._stuck_future: Any = None
        self._stuck_since: float | None = None
        # 몇 번 되살렸나. 잦으면 이 장치가 아니라 **원인**을 봐야 한다는 신호다.
        self._recoveries = 0
        self._last_recovery: dict[str, Any] = {}
        # 어느 호출이 물렸는지 이름·시작·상한을 같이 남긴다. `future` 하나만으로는
        # browser_tabs인지 발행인지 운영 화면에서 가를 수 없었다.
        self._operation_seq = 0
        self._active_operation: dict[str, Any] = {}
        self._epoch = 0
        self._last_late_completion: dict[str, Any] = {}
        self._last_timeout: dict[str, Any] = {}
        self._last_success_at = 0.0
        self._recovery_times: list[float] = []
        self._circuit_open_until = 0.0
        self._navigation_count = 0
        self._reconnect_pending = False
        self._reconnections = 0
        self._reconnect_reason = ""
        self._last_reconnect: dict[str, Any] = {}
        self._reattach_url = ""
        # 마지막으로 찍어 둔 화면 한 장 (R2). 브라우저가 앞 동작에 물려 있으면
        # 새로 못 찍는데, 그때 화면을 비우는 것보다 **몇 초 전 것을 그대로 두고
        # 낡았다고 말하는 편**이 낫다. `fresh` 가 그 사실을 나른다.
        self._last_frame: dict[str, Any] = {}
        # 캡처가 시간 제한에 걸린 탭 → 그 시각. 잠깐 다시 안 찍는다(`_capture` 참고).
        # 탭 → (그때 시각, 이유, 쉬는 초). 이유마다 쉬는 시간이 다르다(숨은 탭 20초 · 최소화 5초).
        self._capture_stalled: dict[int, tuple[float, str, float]] = {}
        # 크롬이 다 떴다는 신호 · 감시가 뜨는 동안 내려 둔 창(다 뜬 뒤 되살린다).
        self._sink_settled = threading.Event()
        self._sunk_hwnds: set[int] = set()
        self._capture_skip_reason = ""
        # 놀고 있을 때도 이벤트를 돌려 주는 심장박동(`_pump_loop` 참고).
        # 이게 없으면 **사람이 연 팝업이 about:blank 에 갇힌다.**
        self._pump_stop = threading.Event()
        self._pump_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        # 크롬에 어떻게 닿아 있는가. 이 값이 끄는 방식과 막히는 곳을 함께 정한다.
        #   "spawned"  우리가 chrome.exe 를 띄우고 붙었다 — 끌 수 있다
        #   "attached" 이미 떠 있던 크롬에 붙었다 — 남의 창이라 끄지 않는다
        #   "launched" Playwright 가 띄웠다(예전 방식) — 자동화 모드다
        self._connect_mode = ""
        self._attach_error = ""
        self._chrome_proc: Any = None
        self._automation_flag: bool | None = None
        self._last_error = ""
        self._last_failure: dict[str, Any] = {}
        self._ref_counter = 0
        # 다음 확인창을 어떻게 답할지(일회용). 비어 있으면 취소가 기본이다.
        self._dialog_policy: dict[str, Any] | None = None
        # 마지막으로 답한 확인창의 문구. Playwright 는 리스너가 없으면 조용히 닫아버려
        # 무엇을 물었는지조차 안 남는데, 그 침묵이 되돌릴 수 없는 동작 앞에서 가장 나쁘다.
        self._last_dialog: dict[str, Any] | None = None
        #: 사람에게 남겨 둔 「나가시겠습니까?」 창. 사람이 답하지 않은 채 우리 일이 시작되면 그때 취소로 닫는다(`_settle_human_dialog`).
        self._human_dialog: Any = None
        self._started_at: float | None = None
        self._connected = False
        # 마지막 검색 결과와 이번 세션에 실제로 들어가 본 주소.
        #
        # 파고드는 일에는 둘 다 필요하다. 결과 목록이 있어야 "3번째 것"이 뜻을 갖고,
        # 방문 이력이 있어야 같은 글을 두 번 열지 않는다 — 뒤로가기로 목록에 돌아오면
        # 화면은 처음과 똑같아서, 기록이 없으면 모델은 늘 1번부터 다시 고른다.
        self._last_results: list[dict[str, Any]] = []
        # 사이트의 성질(섀도 DOM·좌표 필요·봇 검사·구조화 데이터…) — 본 것을 세어 두고 다시 올 때 알린다(site_traits.py).
        try:
            self._site_traits = SiteTraits(Path(config.data_dir) / "site_traits.json")
        except Exception:
            self._site_traits = SiteTraits(None)
        # 그 순위를 **어느 사이트에서** 세웠나. 판(잡) 경계로 못 가르는 길
        # (MCP·/v1/tools/execute)에서 앞 판의 순위가 새는 것을 막는다.
        self._results_origin_host = ""
        # 이번 판에서 사용자가 말한 **묵을 날**. 주소에 날짜 인자가 있으면 이 값으로
        # 갈아 끼워서 연다(`dates.py` 참고). 순위와 같은 자리에서 판마다 새로 놓는다 —
        # 지난 판의 날짜가 남으면 엉뚱한 밤을 열게 되고, 그건 순위가 새는 것과 같은
        # 종류의 고장이다.
        self._requested_stay: RequestedStay | None = None
        # 요청이 **적어 준 주소의 사이트**와, 그 판이 시작할 때 이미 열려 있던 탭들(`set_named_addresses`).
        self._named_sites: frozenset[str] = frozenset()
        self._named_addresses: tuple[str, ...] = ()
        self._named_request = ""
        self._tabs_before_job: list[Any] = []
        # 사이트가 **검색 결과를 준 주소**를 배워 두는 표.
        #
        # `data/` 에 두는 이유: `recipes/` 는 배포 때 편집본으로 덮어써진다
        # (`sync_to_runtime.ps1` 는 data·outputs·.venv 만 지킨다). 배운 것을
        # 거기 두면 배포 한 번에 사라진다.
        self._search_atlas = SearchAtlas(config.data_dir / "search_atlas.json")
        # 방금 손으로 친 값. 목록이 뜨면 이것이 검색어였는지 주소로 확인한다.
        self._typed_recently: tuple[str, float] = ("", 0.0)
        # 어느 화면에서 어떤 칸을 채웠나. **값은 안 남긴다** — 이름과 글자 수만.
        # 제출한 뒤 "무엇을 냈는지" 사람이 찾아갈 수 있게 하는 것이 목적이지,
        # 낸 내용을 쌓아 두는 것이 목적이 아니다(`_submit_handle` 참고).
        self._form_trail: list[dict[str, Any]] = []
        # 채운 칸의 **자리 잡은 값의 지문**(`_remember_settled`). 값은 안 남긴다 — 누르기 직전에 다시 읽어 견줄 뿐이다.
        self._settled_fields: list[dict[str, Any]] = []
        # 번호표 → 그때 그 요소의 이름. 화면이 다시 그려져 번호표가 떨어졌을 때
        # **이름으로** 되찾기 위한 기억이다(`_recover_ref`). 번호는 다시 찍을 때마다
        # 새로 매겨지므로 번호 자체는 근거가 못 된다.
        self._ref_memory: dict[str, dict[str, str]] = {}
        self._recover_why: str = ""
        self._visited: list[str] = []
        # 방금 무엇을 검색했는지. 같은 검색이 되풀이되는 것을 알아보기 위한 것이다.
        self._recent_queries: list[str] = []
        # 사이트별로 사람이 검토한 **읽기 전용 검색 절차**가 있으면
        # `browser_site_search` 앞에서 그 길로 연결한다. 실제 콜백은
        # `SiteRecipeTools.register` 가 건다. 브라우저가 레시피 모듈을 import 하면
        # 순환하므로, 이쪽은 URL·인자만 넘기는 좁은 문만 가진다.
        self._recipe_search: dict[str, str] = {}
        # 검토된 검색 절차가 아는 **상세 URL 표식**. 검색 직후뿐 아니라 목록에서
        # 순위를 다시 만들 때도 같은 필터를 써야 회사정보·광고 링크가 섞이지 않는다.
        self._recipe_result_markers: dict[str, list[str]] = {}
        # 레시피가 아는 **이 사이트 상세 화면에서 읽을 자리** — 호스트 → [(경로 앞머리, 선택자들)]. `_extract` 가 쓴다.
        self._recipe_read_selectors: dict[str, list[tuple[str, list[str]]]] = {}
        self._site_search_delegate: Callable[
            [str, dict[str, Any]], dict[str, Any] | None
        ] | None = None
        # 마지막 검색 이후 결과를 몇 개나 실제로 열어 봤는가, 그리고 아무것도 안 읽은
        # 채로 검색만 몇 번을 되풀이했는가.
        #
        # ★ 질의 일치(`_recent_queries`)만으로는 부족하다는 것이 실측으로 드러났다.
        # 2026-08-06 프롬프트를 고친 뒤에도 검색 7번·열람 1번이었다 — 검색어를 조금씩
        # 바꾸면 "같은 검색"에 안 걸린다. 낱말이 아니라 **행동**을 봐야 한다.
        self._reads_since_search = 0
        self._searches_without_read = 0
        # 한 번이라도 검색했는가. 첫 검색까지 "안 읽고 또 검색"으로 세지 않기 위한 것.
        self._searched_before = False
        # 봇 검사에 걸린 엔진과 걸린 시각. 차단은 한 세션 안에서 이어지는데
        # 도구는 매번 그걸 잊고 처음부터 다시 부딪혔다 — 검색 1회당 ~10초다.
        self._blocked_engines: dict[str, float] = {}
        # 이 동작이 끝나면 브라우저를 닫는다. 핸들러 **안에서** 닫으면 안 된다 —
        # `_execute` 가 그 뒤에 페이지로 마무리 표시를 그리기 때문이다.
        self._close_after_action = False

    def _submit(
        self,
        function: Callable[[], Any],
        timeout: float | None = None,
        *,
        operation: str = "browser_internal",
        mutating: bool = False,
        background: bool = False,
        _retried_on_fresh_thread: bool = False,
    ) -> Any:
        # ★ 이름 없는 내부 동작엔 **부른 함수 이름을 붙인다** (2026-10-01).
        #   네이버 서치어드바이저 판에서 로그인 버튼을 누른 직후 다음 걸음 둘이 「앞 동작(browser_internal)을
        #   0초째 실행 중」으로 거절됐고, 손자리는 포기하고 사람에게 되물었다. 그런데 이름 없이 부르는 자리가
        #   열 곳이 넘어 무엇이 막았는지 기록 어디에도 없었다. 원인을 모른 채 「조금 기다리게」 바꾸면 08-16 의
        #   「호출마다 3분 멈춤」을 되살릴 수 있다 — 먼저 다음 판에서 범인이 찍히게 한다.
        if operation == "browser_internal":
            try:
                operation = f"browser_internal:{sys._getframe(1).f_code.co_name}"
            except Exception:  # noqa: BLE001 — 이름 붙이기 때문에 동작을 실패시키지 않는다
                pass
        # ★ **앞의 것이 아직 안 끝났으면 줄 서지 않는다** (2026-08-16).
        #
        # 일꾼이 하나뿐이라(`max_workers=1`) 하나가 물리면 뒤에 오는 모든 브라우저
        # 호출이 그 뒤에 줄을 선다. 그런데 각자 자기 상한(180초)을 기다리므로
        # **호출할 때마다 3분씩 멈춘 것처럼 보인다.** 실측(2026-08-16): 사람인 로그인
        # 화면이 로딩을 못 끝내는 동안 `browser_tabs` 같은 가벼운 호출까지 응답이 없었고,
        # 화면에는 아무 말도 안 나왔다 — 자비스가 죽은 것처럼 보였다.
        #
        # 물린 것을 여기서 풀 수는 없다(`cancel()` 은 이미 도는 작업을 못 멈춘다).
        # 대신 **기다리지 않고 그 사실을 말한다.** 3분 침묵보다 즉시 "지금 브라우저가
        # 앞 동작에 물려 있다"가 낫다 — 위층이 다른 길을 고를 수 있다.
        now = time.time()
        if now < self._circuit_open_until:
            remaining = max(1, round(self._circuit_open_until - now))
            raise RuntimeError(
                "browser_circuit_open — 브라우저 복구가 10분 안에 3번 반복되어 "
                f"재시도 폭주를 {remaining}초 동안 막습니다. Chrome 창과 네트워크를 확인한 뒤 "
                "잠시 후 다시 부르세요. 쓰기 동작은 자동 재시도하지 않았습니다."
            )

        stuck = self._stuck_future
        if stuck is not None:
            if stuck.done():
                self._stuck_future = None  # 앞의 것이 풀렸다. 정상으로 돌아간다.
            else:
                waited = round(time.time() - (self._stuck_since or time.time()))
                active_name = str(
                    self._active_operation.get("name") or "알 수 없는 브라우저 동작"
                )
                if waited >= max(5, int(self.config.browser_stuck_recover_after_sec)):
                    # 이만큼 지나도 안 풀리면 **영영 안 풀린다**(2026-08-16 실측: 3분
                    # 넘게 확인). 기다리는 것은 답이 아니다 — 버리고 새로 시작한다.
                    self._recover_from_stuck(waited)
                else:
                    raise RuntimeError(
                        f"browser_busy_stuck — 브라우저가 앞 동작({active_name})에 {waited}초째 물려 있습니다"
                        "(대개 페이지가 로딩을 못 끝낸 경우입니다). 이 호출은 줄 서지 않고 바로 돌아왔습니다. "
                        f"{max(5, int(self.config.browser_stuck_recover_after_sec))}초가 지나면 "
                        "브라우저를 스스로 되살립니다 — 그때 다시 부르세요. "
                        "그 사이 브라우저 없이 답할 수 있는 부분이 있으면 그것으로 답하고, "
                        "없으면 브라우저가 막혀 있었다고 말하세요 — 조용히 기다리지 마세요."
                    )
        wait_limit = timeout or self.config.browser_task_timeout_sec
        # 펌프는 250ms 동안 CDP 이벤트를 돌리는 **백그라운드** 일이다. 전면 작업과
        # 똑같이 취급하자 라이브 사람인 작업에서 browser_open 직후 검색·snapshot을
        # 네 번이나 ``browser_busy_active(browser_internal)`` 로 거절했다. 긴 작업 뒤에
        # 줄을 세우지 않는 규칙은 유지하되, 배경 일이 끝날 시간을 양보한다.
        # 배경 쪽은 전면 작업이 보이면 즉시 물러나므로 큐가 쌓이지 않는다.
        #
        # ★ 양보 시간을 **고정값으로 두지 않는다** (2026-08-20). 예전에는 0.75초
        # 고정이었는데, 배경 일 중 하나인 라이브 캡처는 자기 예산이 6초
        # (`_FRAME_TIMEOUT_SEC`, 스크린샷 자체가 4초)다. 숫자가 둘로 갈리자
        # **낮은 쪽만 일했다** — 캡처가 2~3초 걸리는 동안 에이전트 걸음이
        # `browser_busy_active(browser_live_frame)` 로 튕겼다.
        #
        #     실측 2026-08-20 03시: 에이전트 걸음 27건이 라이브 캡처에 막혔다.
        #     막힌 것: browser_open 6 · browser_extract 6 · site_run 5 · snapshot 5 …
        #     그 판(사람인)은 그대로 죽었다.
        #
        # 이 저장소가 하루에 네 번 만난 병이다 — 같은 것을 자르는 자리가 둘이면
        # 낮은 쪽이 조용히 이긴다. 그래서 **배경 일이 스스로 적어 둔 마감
        # (`deadline_at`)에서 끌어온다.** 지킬 숫자가 하나로 준다.
        #
        # 걸음 하나를 실패시키는 것보다 몇 초 기다리는 것이 싸다: 실패한 걸음은
        # 12걸음 예산에서 한 칸을 태우고 계획까지 어긋나게 만든다.
        background_wait_cap = time.monotonic() + (
            _BACKGROUND_YIELD_CAP_SEC if not background else 0.0
        )
        while True:
            should_wait_for_background = False
            with self._lock:
                active = dict(self._active_operation)
                if not active:
                    self._operation_seq += 1
                    operation_id = self._operation_seq
                    epoch = self._epoch
                    started_at = time.time()
                    self._active_operation = {
                        "id": operation_id,
                        "name": operation,
                        "mutating": bool(mutating),
                        "background": bool(background),
                        "epoch": epoch,
                        "state": "running",
                        "phase": "execute",
                        "started_at": started_at,
                        "deadline_at": started_at + float(wait_limit),
                    }
                    break

                active_is_background = bool(active.get("background"))
                # 배경 일이 **스스로 적어 둔 마감**까지 기다린다. 그 마감은
                # `_submit` 이 등록할 때 `started_at + wait_limit` 으로 박아 둔
                # 값이라 구조적으로 유한하다. 천장은 그 값이 터무니없을 때만 쓴다.
                active_deadline = float(active.get("deadline_at") or 0.0)
                should_wait_for_background = (
                    not background
                    and active_is_background
                    and time.monotonic() < background_wait_cap
                    and (active_deadline <= 0.0 or time.time() < active_deadline)
                )

            if should_wait_for_background:
                time.sleep(0.01)
                continue

            # ★ timeout이 나기 **전부터** executor는 이미 하나뿐이다 (2026-08-17
            # 라이브 실측). 예전에는 ``_stuck_future`` 가 생긴 뒤에만 후속 호출을
            # 막아서, 긴 navigation이 정상 상한 안에서 도는 동안 펌프·health probe가
            # 그 뒤에 줄을 섰다. 보조 호출이 먼저 자기 3~5초 상한에 걸리면 실제
            # browser_open 대신 그 보조 future를 stuck으로 기록했고, /health까지
            # 응답하지 않았다.
            #
            # 검사와 active 등록을 같은 lock 안에서 해야 동시에 들어온 두 호출도
            # 둘 다 executor에 실리지 않는다. 이미 도는 것은 건드리지 않고, 뒤의 것만
            # 즉시 돌려보낸다. health의 ``_probe_alive`` 는 이 오류를 cached 상태로
            # 바꾸므로 UI와 watchdog은 계속 살아 있다.
            active_name = str(active.get("name") or "알 수 없는 브라우저 동작")
            elapsed = max(
                0,
                round(time.time() - float(active.get("started_at") or time.time())),
            )
            raise RuntimeError(
                "browser_busy_active — 브라우저가 앞 동작"
                f"({active_name})을 {elapsed}초째 실행 중입니다. 이 호출은 executor에 "
                "줄 세우지 않고 바로 돌아왔습니다. 앞 동작 결과를 기다린 뒤 새 화면을 "
                "확인하세요. 쓰기 동작은 자동 재시도하지 않았습니다."
            )

        def guarded() -> Any:
            self._doing = ""  # 앞 호출이 남긴 구간을 이 호출의 것으로 읽지 않게
            value = function()
            if epoch != self._epoch:
                raise RuntimeError("browser_stale_epoch_result_discarded")
            return value

        future = self._executor.submit(guarded)

        def completed(_future: Any) -> None:
            with self._lock:
                if epoch != self._epoch:
                    self._last_late_completion = {
                        "id": operation_id,
                        "name": operation,
                        "epoch": epoch,
                        "discarded_at": time.time(),
                    }
                if self._active_operation.get("id") == operation_id:
                    self._active_operation = {}

        future.add_done_callback(completed)
        try:
            value = future.result(timeout=wait_limit)
            # done callback과 API 요청 스레드의 경합에 기대지 않는다. 이 함수가 성공을
            # 반환하는 순간에는 다음 전면 작업이 반드시 자리를 잡을 수 있어야 한다.
            with self._lock:
                if self._active_operation.get("id") == operation_id:
                    self._active_operation = {}
            self._last_success_at = time.time()
            # 열린 회로의 유예가 끝난 뒤 첫 실제 왕복이 성공해야 과거 복구 묶음을
            # 지운다. 시간만 지났다고 즉시 건강하다고 단정하지 않는다.
            if (
                self._circuit_open_until
                and self._last_success_at >= self._circuit_open_until
            ):
                self._circuit_open_until = 0.0
                self._recovery_times = []
            return value
        except RuntimeError as exc:
            # ★ **옛 Playwright 가 깨끗이 안 닫힌 일꾼 스레드에서는 브라우저가 영원히 다시 안 켜진다** (2026-10-15).
            #   sync Playwright 가 살아 있는 동안 그 스레드에는 「돌고 있는 asyncio 루프」가 보이고, 옛 것이 제대로
            #   닫히지 못하면 같은 스레드의 다음 `sync_playwright().start()` 가 「Sync API inside the asyncio loop」로
            #   매번 죽는다 — 가격 판 3판(11번가에서 물린 뒤)에서 백엔드를 다시 띄우기 전까지 안 풀렸다. 새 스레드에서는
            #   같은 순간에도 켜진다(실험으로 확인 · `tests/test_a_poisoned_browser_thread_is_replaced_1015.py`).
            #   시작 단계에서 난 오류라 아무 동작도 안 일어났으니, 스레드를 바꿔 **한 번만** 다시 부른다.
            if _retried_on_fresh_thread or not _is_poisoned_thread_start(exc):
                raise
            self._recover_from_stuck(0)
            return self._submit(function, timeout, operation=operation, mutating=mutating,
                                background=background, _retried_on_fresh_thread=True)
        except FutureTimeout as exc:
            # 이 작업은 스레드에 남아 계속 돈다. 그 사실을 적어 둬야 다음 호출이
            # 같은 함정에 3분을 또 쓰지 않는다.
            self._stuck_future = future
            self._stuck_since = time.time()
            with self._lock:
                if self._active_operation.get("id") == operation_id:
                    self._active_operation["state"] = "timed_out_running"
                    self._active_operation["phase"] = "awaiting_late_completion"
                    self._active_operation["timed_out_at"] = self._stuck_since
                    self._active_operation["where"] = str(getattr(self, "_doing", "") or "")
                    self._last_timeout = dict(self._active_operation)
            # ★ `cancel()` 은 **이미 돌기 시작한 작업을 멈추지 못한다.** 큐에서만 뺀다.
            # 그러니 여기서 시간이 끊겨도 브라우저 스레드는 하던 일을 계속 끝낸다.
            #
            # 2026-08-09: 블로그 본문 타이핑이 이 시간을 넘겨 실패로 보고됐는데,
            # 편집기에는 본문이 **그대로 다 들어가 있었다.** 그런데 상위 계층은
            # 이 실패를 "아무 일도 안 일어났다"로 읽고 그렇게 답했다. 다시
            # 실행하면 내용이 두 번 들어간다. 이름이 사실을 가린 것이다.
            #
            # 그래서 이름에 적어 둔다 — 이 문자열은 attention.py 의 browser_stuck
            # 규칙과 agent 의 사실 검증이 함께 읽는다.
            future.cancel()
            # ★ 어느 구간에서 멈췄는지 같이 적는다 (2026-10-06). 로컬 미리보기를 여는 첫 `browser_open` 이 180초 물렸는데
            #   기록에는 동작 이름만 남아, 이동에서 멈췄는지 앞 탭을 건드리다 멈췄는지 가릴 수 없었다. 원인을 모르는 채로
            #   고치지 않는다 — 다음에 같은 일이 나면 구간이 찍힌다.
            where = str(getattr(self, "_doing", "") or "")
            raise RuntimeError(
                "browser_action_timeout — 시간이 끊겼을 뿐 동작은 계속 진행됐을 수 있습니다."
                " 다시 실행하기 전에 화면을 확인하세요."
                + (f" (멈춘 구간: {where})" if where else "")
            ) from exc

    # 심장박동 한 번이 도는 시간 / 사이 간격(ms). 붙어 있는 동안만 돈다.
    _PUMP_MS = 250
    _PUMP_GAP_SEC = 0.25

    def _pump_loop(self, stop_event: threading.Event | None = None) -> None:
        """놀고 있을 때도 **이벤트를 돌려 준다.** 사람이 연 새 창이 살아나는 유일한 길.

        ## 왜 필요한가 (2026-08-16, 라이브로 증명)

        플레이라이트 **동기 API 는 호출이 돌고 있는 동안에만** CDP 이벤트를 처리한다.
        그런데 CDP 로 붙으면 새로 열리는 창(팝업)은 "디버거가 붙을 때까지 멈춤"
        상태로 태어난다. 자비스가 놀고 있으면 그 멈춤을 풀어 줄 사람이 없어서
        팝업이 `about:blank` 에 갇힌다.

        실측이 딱 갈렸다:

            자비스 놀고 있음  -> 구글 로그인 팝업이 about:blank 에서 죽음
            자비스 바쁨(20초)  -> 같은 버튼에 팝업이 정상으로 뜸

        사용자가 아침 내내 "로그인이 안 된다"고 한 것의 진짜 원인이 이것이다.
        사람이 못 누른 게 아니라, **자비스가 조용히 있어서** 창이 안 열린 것이다.

        ## 왜 `wait_for_timeout` 인가

        이 호출 자체가 **기다리는 동안 이벤트 루프를 돌린다.** 즉 심장박동이 곧
        펌프다 — CDP 왕복을 따로 만들지 않고도 멈춰 있던 창이 풀린다.

        ## 값을 왜 이렇게 잡았나

        일꾼이 하나뿐이라 이 박동도 줄을 선다. 250ms 씩 돌고 250ms 쉬면 진짜 일이
        기다리는 시간은 최악 250ms 이고, 사람이 버튼을 누른 뒤 창이 풀리기까지도
        그 정도다. 더 짧게 하면 점유가 늘고, 더 길게 하면 사람이 기다린다.
        """
        stop = stop_event or self._pump_stop
        while not stop.wait(self._PUMP_GAP_SEC):
            if self._context is None or self._connect_mode == "":
                continue
            try:
                # 물려 있으면 `_submit` 이 즉시 거절한다(줄을 안 선다). 그게 맞다 —
                # 박동이 회복을 방해하면 안 된다.
                self._submit(
                    self._pump_once,
                    5,
                    operation="browser_pump",
                    background=True,
                )
            except Exception:
                # 박동이 실패한다고 브라우저가 고장 난 것은 아니다. 조용히 넘긴다 —
                # 여기서 시끄러우면 진짜 고장이 안 보인다.
                pass

    def _pump_once(self) -> None:
        page = self._page
        if page is None or page.is_closed():
            return
        page.wait_for_timeout(self._PUMP_MS)

    def _start_pump(self) -> None:
        if (
            self._pump_thread is not None
            and self._pump_thread.is_alive()
            and not self._pump_stop.is_set()
        ):
            return
        # 정지된 옛 펌프가 아직 마지막 왕복에서 빠져나오는 중이어도 그 이벤트를
        # 다시 clear하지 않는다. 세대마다 새 이벤트를 써야 옛 펌프가 되살아나지 않는다.
        self._pump_stop = threading.Event()
        self._pump_thread = threading.Thread(
            target=self._pump_loop,
            args=(self._pump_stop,),
            name="jarvis-browser-pump",
            daemon=True,
        )
        self._pump_thread.start()

    def recover_now(self) -> bool:
        """앞 동작에 물려 있으면 **지금** 일꾼을 갈고 True. 물린 것이 없으면 아무것도 안 하고 False (2026-10-15).

        `_submit` 은 물린 지 `browser_stuck_recover_after_sec`(60초)가 지나야 스스로 간다. 그 사이 에이전트가 다섯 번
        「물려 있음」을 받으면 사람에게 넘기던 자리(가격 판 3판 · 11번가)에서, 반복문이 기다리지 않고 바로 갈게 한다.
        """
        stuck = self._stuck_future
        if stuck is None or stuck.done():
            return False
        self._recover_from_stuck(round(time.time() - (self._stuck_since or time.time())))
        return True

    def _recover_from_stuck(self, waited: int) -> None:
        """물린 일꾼을 **버리고** 새로 시작한다.

        ## 왜 이렇게밖에 못 하나 (2026-08-16)

        파이썬은 스레드를 강제로 못 죽인다. 물린 스레드는 그대로 둘 수밖에 없다.
        그래서 죽이는 대신 **버린다** — 새 일꾼을 만들고 그쪽으로 옮겨 탄다.

        ★ **`_shutdown()` 을 부르면 안 된다.** 그 안의 `context.close()` 는 지금
        물려 있는 그 연결을 건드리므로 **새 스레드까지 같이 물린다.** 회복하려다
        회복 경로를 잃는 것이 제일 나쁘다. 낡은 playwright·context 는 손대지 않고
        참조만 버린다 — 물린 스레드가 언젠가 풀리면 그때 알아서 정리된다.

        붙어 있던 크롬(`attached`)은 그대로 살아 있으므로, 새 연결이 같은 포트로
        다시 붙는다. **로그인 세션이 안 날아간다** — 이것이 크롬을 통째로 껐다 켜는
        것(오늘 사람이 세 번 손으로 했다)과 결정적으로 다른 점이다.

        새는 것은 스레드 하나와 연결 하나다. 회복이 드물면 감당할 수 있고, 드물지
        않으면 그건 이 함수가 아니라 원인을 봐야 한다는 신호다 — 그래서 센다.
        """
        old = self._executor
        old_playwright = self._playwright
        with self._lock:
            abandoned = dict(self._active_operation)
            self._epoch += 1
            self._active_operation = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-browser")
        # ★ 낡은 playwright 를 **버리기만 하면 안 된다** (2026-08-16 실측).
        #
        # 처음엔 참조만 끊었다. 그런데 한 프로세스에 sync playwright 가 둘 살아 있게
        # 되고, 그 다음 시작이 이렇게 죽는 것을 봤다:
        #
        #     browser_start_failed: It looks like you are using Playwright Sync API
        #                           inside the asyncio loop.
        #
        # 그렇다고 여기서 `stop()` 을 부르면 물린 그 연결을 건드려 **이 스레드까지
        # 물린다**(회복하려다 회복 경로를 잃는다). 그래서 **정리를 죽은 쪽에 맡긴다** —
        # 어차피 잃은 스레드이므로 거기서 더 기다려도 잃을 것이 없고, 그것이 풀리면
        # 그때 알아서 닫힌다. 우리는 기다리지 않는다.
        if old_playwright is not None:
            try:
                old.submit(old_playwright.stop)
            except Exception:
                pass
        # 큐에 남은 것은 비우되 위 정리는 남긴다(cancel_futures 를 안 쓰는 이유).
        old.shutdown(wait=False)
        self._playwright = None
        self._context = None
        self._page = None
        self._chrome_proc = None
        self._connect_mode = ""
        self._automation_flag = None
        self._stuck_future = None
        self._stuck_since = None
        self._recoveries += 1
        recovered_at = time.time()
        self._recovery_times = [
            when
            for when in self._recovery_times
            if recovered_at - when <= self._RECOVERY_WINDOW_SEC
        ]
        self._recovery_times.append(recovered_at)
        if len(self._recovery_times) >= self._RECOVERY_LIMIT:
            self._circuit_open_until = recovered_at + self._CIRCUIT_OPEN_SEC
        self._last_recovery = {
            "at": recovered_at,
            "stuck_sec": waited,
            "count": self._recoveries,
            "abandoned_operation": abandoned,
            "epoch": self._epoch,
            "circuit_open_until": self._circuit_open_until,
        }
        self._mark_disconnected()

    def start(self) -> dict[str, Any]:
        if not self.config.browser_enabled:
            raise RuntimeError("browser_disabled")
        return self._submit(
            self._ensure_started,
            self.config.browser_navigation_timeout_sec + 15,
            operation="browser_start",
        )

    def stop(self) -> None:
        try:
            self._submit(self._shutdown, 10, operation="browser_stop")
        except Exception:
            pass
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _probe_alive(self) -> bool | None:
        """워커가 한가하면 실제로 찔러 보고, 바쁘면 캐시값을 쓴다(`None`).

        바쁘다는 것은 브라우저 작업이 지금 돌고 있다는 뜻이고, 그럼 브라우저는
        살아 있다. 굳이 그 뒤에 줄 서서 화면을 몇 초씩 세울 이유가 없다 —
        `status` 는 UI 가 주기적으로 부르는 것이다.
        """
        try:
            return bool(
                self._submit(
                    self._context_alive,
                    3,
                    operation="browser_health_probe",
                    background=True,
                )
            )
        except Exception:
            return None

    def status(self) -> dict[str, Any]:
        # ★ 플래그만 읽으면 죽은 브라우저를 `started: true` 로 보고한다(실측
        # 2026-08-09: 크롬을 죽여도 계속 true). 화면에는 멀쩡한데 도구는 전부
        # 실패하는, 가장 알아채기 어려운 모양이 된다.
        probed = self._probe_alive()
        with self._lock:
            return {
                "enabled": self.config.browser_enabled,
                "started": self._connected if probed is None else probed,
                # 방금 실제로 확인한 값인지, 바빠서 못 물어보고 쓴 값인지.
                "liveness": "probed" if probed is not None else "cached",
                "headless": self.config.browser_headless,
                "read_only": self.config.browser_read_only,
                "sandbox": self.config.browser_sandbox,
                # 어느 크롬에 닿아 있는지, 자동화 모드인지. 막히는 곳에서 원인을
                # 짐작하지 않기 위한 것이다 — "launched" + automation_flag True 면
                # Akamai 를 쓰는 곳은 막힌다는 뜻이고, 그건 사이트 탓이 아니다.
                "connect_mode": self._connect_mode,
                # ★ 탭이 몇 장 열려 있나 (2026-09-16). 이것이 없어서 「탭이 너무 많다」를
                #   렌더러 프로세스 수로 짐작하려 했는데, iframe 이 섞여 18장과 6장을 못 가른다.
                #   상한을 같이 보내는 이유는 하나다 — 숫자 하나만 보면 그것이 많은지 알 수 없다.
                #   잰 **시각**도 보낸다. 캐시를 「지금」으로 읽으면 그게 곧 거짓말이다.
                "tabs": self._tab_census.get("tabs"),
                "max_tabs": int(getattr(self.config, "browser_max_tabs", 0) or 0),
                "ours_of_tabs": self._tab_census.get("ours"),
                "tabs_closed_total": self._tab_census.get("closed_total", 0),
                "tabs_wanted_to_close": self._tab_census.get("wanted_to_close"),
                "tabs_refused_to_close": self._tab_census.get("refused_to_close"),
                "tabs_error": self._tab_census.get("error"),
                "tabs_measured_at": self._tab_census.get("at"),
                "yielded_to_user": getattr(self, "_yielded_front", 0),
                # ★ 창을 내리고 앞창을 돌려준 기록 (2026-09-21). 이 진단이 안 나와서 「운영에서는 콜드스타트가 아직
                #   번쩍인다」를 밖에서 못 보고 짐작만 했다 — 몇 번 내렸고 몇 번 돌려줬고 언제였는지가 곧 번쩍임의 횟수다.
                "window_sink": {
                    key: (list(value) if isinstance(value, list) else value)
                    for key, value in self._sink_report.items()
                },
                "last_restore_path": getattr(BrowserWorker, "_last_restore_path", ""),
                "automation_flag": self._automation_flag,
                "cdp_port": getattr(self, "_cdp_port_in_use", None) or self.config.browser_cdp_port,
                # 붙기를 시도했다가 내려왔다면 그 이유. 비어 있으면 시도가 통했거나
                # 애초에 꺼져 있었다는 뜻이다.
                "attach_error": self._attach_error,
                "visual_overlay": self.config.browser_visual_overlay,
                "profile_dir": str(self._profile_dir),
                "last_error": self._last_error,
                # What the page looked like when it last went wrong. Surfaced
                # rather than only written to disk so a failure can be
                # diagnosed without knowing the evidence directory exists.
                "last_failure": dict(self._last_failure),
                # 지금 물려 있는가, 그리고 지금까지 몇 번 스스로 되살렸는가.
                # 회복이 잦아지면 이 장치가 아니라 **원인**을 봐야 한다 —
                # 안 세면 조용히 잦아진다.
                "stuck": self._stuck_future is not None and not self._stuck_future.done(),
                "recoveries": self._recoveries,
                "last_recovery": dict(self._last_recovery),
                "active_operation": dict(self._active_operation),
                "epoch": self._epoch,
                "last_late_completion": dict(self._last_late_completion),
                "last_timeout": dict(self._last_timeout),
                "last_success_at": self._last_success_at,
                "circuit_open": time.time() < self._circuit_open_until,
                "circuit_open_until": self._circuit_open_until,
                "navigations_since_reconnect": self._navigation_count,
                # 연결 장부에 쌓인 물건 수 — 이것이 한도를 넘으면 연결을 갈아 끼운다(탐색 횟수보다 이쪽이 진짜 눈금이다).
                "connection_objects": self._connection_objects(),
                "reconnect_pending": self._reconnect_pending,
                "reconnections": self._reconnections,
                "last_reconnect": dict(self._last_reconnect),
            }

    # ── 자비스가 보는 화면을 사람도 본다 (R2) ────────────────────────────────
    #
    # 화면이 **당겨 간다**(pull). 밀지 않는 이유: 미는 쪽이 되면 자비스가 놀 때도
    # 프레임을 만들게 되고, 그건 연출 계약 1번(정지가 기본)에 어긋난다. 보는 쪽이
    # 간격을 정하면 아무도 안 볼 때는 한 장도 안 찍힌다.
    #
    # 규칙 셋:
    #   1. **브라우저를 띄우지 않는다.** 화면을 보는 것이 크롬을 여는 계기가 되면
    #      안 된다 — 폴링 한 번이 사람 몰래 창을 띄우는 꼴이 된다.
    #   2. **앞 동작에 줄 서지 않는다.** `background=True` 로 보내고, 바쁘면
    #      마지막 장을 `fresh: false` 로 준다(`_submit` 이 즉시 거절한다).
    #   3. **오버레이를 끄지 않는다.** `browser_screenshot` 은 모델에게 보여 줄
    #      그림이라 자비스의 표시를 지우지만, 이건 사람이 보는 화면이다 — 자비스가
    #      무엇을 가리키고 있는지가 오히려 핵심이다. 1.5초마다 껐다 켜면 사용자가
    #      보고 있는 진짜 크롬 창이 깜빡인다.
    _FRAME_TIMEOUT_SEC = 6.0
    _FRAME_MIN_INTERVAL_SEC = 0.9
    # 심장박동과 부딪혔을 때 다시 해 보는 횟수·간격. 아래 주석에 실측 근거.
    _FRAME_RETRIES = 4
    _FRAME_RETRY_SLEEP = 0.12

    def live_frame(self) -> dict[str, Any]:
        """지금 화면 한 장 + 어디인지. 못 찍었으면 `reason` 에 **왜**가 들어 있다."""
        now = time.time()
        cached = dict(self._last_frame)
        # 여러 창이 같이 보고 있어도 캡처는 이 간격 안에서 한 번만 일어난다.
        if cached and now - float(cached.get("at") or 0) < self._FRAME_MIN_INTERVAL_SEC:
            return {**cached, "fresh": False}
        if not self._connected:
            return {"jpeg": b"", "reason": "browser_not_started", "at": now, "fresh": False}
        # ★ 심장박동(`_pump_loop`)과 부딪힌다 (2026-08-19 라이브에서 잡았다).
        #
        # 펌프는 250ms 돌고 250ms 쉬므로 **일꾼을 절반쯤 붙들고 있다.** 그리고
        # `_submit` 의 0.75초 양보는 `background=False` 인 호출에만 준다 — 이 캡처는
        # 스스로 background 라 그 양보를 못 받고 즉시 거절당한다.
        #
        # 실측: 배포 직후 34초 동안 계속 `browser_busy_active(browser_pump)` 였다.
        # 화면에는 낡은 장이 계속 걸려 있었고, 이유를 안 읽으면 "갱신이 멈췄다"로만
        # 보인다 — R2 가 하려던 일이 통째로 헛돌 뻔했다.
        #
        # background 를 포기하지는 않는다. 그 표시는 **에이전트가 내 캡처를 기다려
        # 주게** 하는 쪽이라 반대로 필요하다. 대신 여기서 잠깐씩 몇 번 다시 해 본다 —
        # 총 0.5초 이내라 폴링 간격(1.5초) 안에 넉넉히 들어간다.
        reason = ""
        for attempt in range(self._FRAME_RETRIES):
            try:
                shot = self._submit(
                    self._capture_live_frame,
                    self._FRAME_TIMEOUT_SEC,
                    operation="browser_live_frame",
                    background=True,
                )
            except Exception as exc:
                reason = str(exc)[:300]
                # 앞이 바쁜 것만 다시 해 본다. 물렸거나(stuck) 회로가 열린 것은
                # 기다린다고 풀리지 않으므로 그 사실을 바로 말한다.
                if "browser_busy_active" not in reason or attempt == self._FRAME_RETRIES - 1:
                    break
                time.sleep(self._FRAME_RETRY_SLEEP)
                continue
            self._last_frame = shot
            return {**shot, "fresh": True}
        if cached:
            return {**cached, "fresh": False, "reason": reason}
        return {"jpeg": b"", "reason": reason, "at": now, "fresh": False}

    def _capture_live_frame(self) -> dict[str, Any]:
        """Playwright 전용 스레드 안에서 도는 본체. **재기동하지 않는다.**"""
        if not self._context_alive():
            raise RuntimeError("browser_not_started")
        pages = [item for item in self._context.pages if not item.is_closed()]
        page = self._page if self._page in pages else (pages[-1] if pages else None)
        if page is None:
            raise RuntimeError("browser_has_no_page")
        url = str(getattr(page, "url", "") or "")
        try:
            title = _clean(page.title(), 200)
        except Exception:
            # 제목을 못 읽는 것은 화면을 못 찍는 것과 다르다. 그림은 그대로 준다.
            title = ""
        # `animations="disabled"` 를 **쓰지 않는다.** 그건 화면이 멎기를 기다리는
        # 설정이라 배너·캐러셀이 도는 페이지에서 상한을 통째로 태운다(2026-08-14
        # 쿠팡 상세에서 20초 두 번). 여기는 라이브 뷰라 기다릴 이유가 없다.
        raw = self._capture(page, quiet=True)
        if raw is None and self._capture_skip_reason:
            # 조용한 캡처가 시간 제한에 걸렸다 — 제한 없는 길로 다시 가지 않는다. 화면은 마지막 장을
            # 낡았다고 표시해 보여 주고, 이유를 사람에게 그대로 준다(`live_frame`).
            raise RuntimeError(self._capture_skip_reason)
        if raw is None:
            raw = page.screenshot(type="jpeg", quality=55, scale="css", timeout=4000)
        return {"jpeg": bytes(raw), "url": url, "title": title, "at": time.time()}

    # ── 읽은 순간의 사진 (대표사진의 재료 · 2026-10-18 대표 결정) ─────────────────
    #
    # 본문을 읽은 그 탭을 한 장. 실시간 화면(`live_frame`)과 같은 규칙을 지킨다:
    #   1. **브라우저를 띄우지 않는다 · 재기동하지 않는다** — 사진 한 장이 크롬을 여는 계기가 되면 안 된다.
    #   2. **창을 앞으로 올리지 않고 시간 제한을 건다**(`_capture` 의 조용한 길). 최소화 · 뒤 탭은 2.5초 안에 포기하고 이유를 남긴다.
    #   3. **오버레이를 끄지 않는다** — 껐다 켜면 사용자가 보는 진짜 크롬 창이 깜빡인다(`live_frame` 주석). 그래서 손자리 표시가
    #      사진에 같이 찍힐 수 있다.
    # 판의 걸음 사이에 부르므로 앞 동작에 줄 서도 된다(`background=False`) — 읽기 걸음 바로 뒤라 보통 비어 있다.
    _READ_SHOT_TIMEOUT_SEC = 6.0
    _READ_SHOT_QUALITY = 70

    def capture_read_shot(self, destination: str | Path) -> dict[str, Any]:
        """지금 탭의 보이는 영역을 `destination` 에 JPEG 로(가로 1280 이하). 실패는 예외가 아니라 `{"ok": False, "reason"}` 다."""
        started = time.monotonic()

        def done(result: dict[str, Any]) -> dict[str, Any]:
            return {**result, "ms": int((time.monotonic() - started) * 1000)}

        if not getattr(self, "_connected", False):
            return done({"ok": False, "reason": "browser_not_started"})
        try:
            shot = self._submit(self._capture_read_shot, self._READ_SHOT_TIMEOUT_SEC, operation="browser_read_shot")
        except Exception as exc:  # noqa: BLE001 — 사진 한 장 때문에 판을 멈추지 않는다
            return done({"ok": False, "reason": _clean(str(exc), 200)})
        try:
            from .showcase import save_jpeg

            saved = save_jpeg(shot["jpeg"], destination)
        except Exception as exc:  # noqa: BLE001
            return done({"ok": False, "reason": "save_failed: " + _clean(str(exc), 160)})
        return done({"ok": True, "path": saved["path"], "url": shot["url"], "title": shot["title"], "at": shot["at"],
                     "bytes": saved["bytes"], "width": saved["width"], "height": saved["height"]})

    def _capture_read_shot(self) -> dict[str, Any]:
        """Playwright 전용 스레드 안에서 도는 본체. **재기동하지 않는다**(`_capture_live_frame` 과 같다)."""
        if not self._context_alive():
            raise RuntimeError("browser_not_started")
        pages = [item for item in self._context.pages if not item.is_closed()]
        page = self._page if self._page in pages else None
        if page is None:
            # 읽은 탭이 아니면 찍지 않는다 — 엉뚱한 탭의 사진은 증거가 아니라 거짓말이다.
            raise RuntimeError("read_tab_gone")
        url = str(getattr(page, "url", "") or "")
        try:
            title = _clean(page.title(), 200)
        except Exception:  # noqa: BLE001
            title = ""
        raw = self._capture(page, quiet=True, quality=self._READ_SHOT_QUALITY)
        if raw is None and self._capture_skip_reason:
            raise RuntimeError(self._capture_skip_reason)
        if raw is None:
            raw = page.screenshot(type="jpeg", quality=self._READ_SHOT_QUALITY, scale="css",
                                  timeout=self._QUIET_CAPTURE_TIMEOUT_MS)
        return {"jpeg": bytes(raw), "url": url, "title": title, "at": time.time()}

    def _wait_while_human_controls(self) -> float:
        """사람이 무대에서 크롬을 넘겨받았으면 돌려줄 때까지 기다린다. 기다린 초를 돌려준다.

        막지 않고 **기다린다** — 로그인·보안문자를 사람이 푸는 동안 온텔릭이 같은 탭을 누르면 사람 손과 부딪힌다.
        15분 넘게 안 돌려주면 그만 기다리고 계속한다(사람이 자리를 비운 판이 영영 멈추지 않게).
        """
        view = getattr(self, "live_view", None)
        if view is None or not view.human_in_control():
            return 0.0
        started = time.time()
        while view.human_in_control() and time.time() - started < 900:
            time.sleep(0.4)
        waited = time.time() - started
        self._human_took_over = {"waited_sec": round(waited, 1), "released_at": time.time()}
        self.note_human_hand()
        return waited

    def _with_takeover_note(self, result: Any) -> Any:
        """사람이 넘겨받았던 뒤의 첫 결과에 한 번 알린다 — 화면이 바뀌었을 수 있으니 다시 보라고."""
        note = getattr(self, "_human_took_over", None)
        if not note or not isinstance(result, dict):
            return result
        self._human_took_over = None
        return {**result, "human_took_over": (
            f"사람이 브라우저를 {note.get('waited_sec', 0)}초 동안 직접 조작했습니다. "
            "화면·로그인 상태가 바뀌었을 수 있으니 이어 가기 전에 지금 화면을 먼저 다시 보세요."
        )}

    def execute(self, action: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self._wait_while_human_controls()
        return self._with_takeover_note(self._execute_entry(action, arguments))

    def _execute_entry(self, action: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = _coerce_expect(dict(arguments or {}))
        # ★ 검토된 L0 검색 레시피는 **모델이 기억해 주기를 기다리지 않는다.**
        #
        # 사람인 라이브 판에서 Gemma는 `site_run(saramin, search_jobs)`가 있는데도
        # 먼저 숨은 검색칸을 범용으로 찾다가 실패했다. 안내문을 받은 뒤에야 레시피를
        # 썼고, 그 사이 걸음과 생각 예산을 크게 소모했다. 여기서 자동 연결하되 콜백은
        # executor 밖에서 부른다 — 레시피가 다시 worker.execute* 를 부르므로 전용
        # 스레드 안에서 부르면 자기 자신 뒤에 줄을 서는 교착이 된다.
        delegate = self._site_search_delegate
        if action == "browser_site_search" and callable(delegate):
            current_url = self._submit(
                lambda: str(getattr(self._current_page(), "url", "") or ""),
                min(10, self.config.browser_task_timeout_sec),
                operation="browser_site_search:recipe_lookup",
            )
            delegated = delegate(current_url, arguments)
            if delegated is not None:
                return self._submit(
                    lambda: self._finish_delegated_site_search(delegated, arguments),
                    self.config.browser_task_timeout_sec,
                    operation="browser_site_search:recipe_results",
                )
        return self._submit(
            lambda: self._execute(action, arguments),
            self.config.browser_task_timeout_sec,
            operation=action,
            mutating=action in self._MUTATING_ACTIONS,
        )

    def reviewed_search_recipe(self) -> str:
        """지금 사이트에 검토된 검색 길이 있으면 그 호출 이름을 돌려준다."""
        def lookup() -> str:
            page = self._current_page()
            host = _host_of_url(str(getattr(page, "url", "") or ""))
            for site_host, call in self._recipe_search.items():
                if host == site_host or host.endswith("." + site_host):
                    return call
            return ""

        return str(
            self._submit(
                lookup,
                min(10, self.config.browser_task_timeout_sec),
                operation="browser_search_recipe_lookup",
            )
            or ""
        )

    def collect_reviewed_search_results(
        self, markers: list[str] | None = None, *, limit: int = 15
    ) -> dict[str, Any]:
        """검토된 검색 레시피가 도착한 목록을 순위 배열로 만든다."""
        clean_markers = [str(item) for item in markers or [] if str(item).strip()]
        bounded = max(1, min(int(limit), 30))
        return dict(
            self._submit(
                lambda: self._collect_reviewed_search_results(clean_markers, limit=bounded),
                self.config.browser_task_timeout_sec,
                operation="browser_reviewed_search_results",
            )
        )

    def _collect_reviewed_search_results(
        self, markers: list[str], *, limit: int
    ) -> dict[str, Any]:
        """Playwright 전용 스레드 안에서 쓰는 목록 수집 본체."""
        page = self._current_page()
        raw = self._collect_results(
            page, limit=min(80, limit * 4) if markers else limit
        )
        results = self._filter_reviewed_results(raw, markers, limit=limit)
        if results or not self._last_results:
            self._last_results = results
            self._remember_results_origin(page)
        self._reads_since_search = 0
        self._searched_before = True
        return {
            "results": results,
            "result_count": len(results),
            "url": str(getattr(page, "url", "") or ""),
        }

    def _finish_delegated_site_search(
        self, delegated: dict[str, Any], arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """레시피가 목록에 도착한 뒤 범용 검색과 같은 결과 계약을 만든다."""
        if delegated.get("status") != "done":
            # 검증을 못 한 것은 실패와도, 성공과도 다르다. 여기서 범용 검색을 다시
            # 실행하면 같은 화면을 한 번 더 건드릴 수 있고, 성공으로 포장하면 모델이
            # 잘못 열린 목록을 읽는다. 레시피의 보수적인 중단을 그대로 보존한다.
            return self._evidence(
                "site_search_unverified",
                query=_clean(arguments.get("query"), 300),
                strategy="reviewed_site_recipe",
                recipe_site=str(delegated.get("site") or ""),
                recipe_action=str(delegated.get("action") or ""),
                recipe_status=str(delegated.get("status") or ""),
                reason=str(delegated.get("reason") or "검색 결과 화면을 확인하지 못했습니다."),
                instruction=(
                    "★ 검토된 검색 절차가 결과 화면의 증거를 못 읽어 멈췄다. 같은 검색을 "
                    "자동으로 다시 실행하지 말고 현재 화면을 확인하라."
                ),
            )
        query = _clean(arguments.get("query"), 300)
        limit = max(1, min(int(arguments.get("limit") or 15), 30))
        # 한 카드가 공고·회사·기업정보 링크를 함께 내는 사이트가 있다. 범용 목록
        # 수집기에서 "긴 글자 하나"를 고르면 쇼핑몰들이 깨진다는 실측이 이미 있어
        # 거기는 건드리지 않는다. 대신 검토된 레시피가 상세 URL 표식을 아는 경우에만
        # 넉넉히 모은 뒤 그 표식으로 좁힌다.
        markers = [
            str(item)
            for item in delegated.get("result_url_contains") or []
            if str(item).strip()
        ]
        supplied = delegated.get("results")
        if isinstance(supplied, list):
            results = self._filter_reviewed_results(
                [dict(item) for item in supplied if isinstance(item, dict)], [], limit=limit
            )
            url = str(delegated.get("result_url") or "")
        else:
            # 이 함수는 이미 browser executor 안에서 돈다. 공개 메서드(다시 _submit)를
            # 부르면 자기 자신 뒤에 줄 서므로 내부 본체를 바로 쓴다.
            listing = self._collect_reviewed_search_results(markers, limit=limit)
            results = list(listing.get("results") or [])
            url = str(listing.get("url") or "")
        page = self._current_page()
        if not url:
            url = str(getattr(page, "url", "") or "")
        self._mark_visited(url)
        return self._evidence(
            "site_searched",
            site=_host_of_url(url),
            query=query,
            strategy="reviewed_site_recipe",
            recipe_site=str(delegated.get("site") or ""),
            recipe_action=str(delegated.get("action") or ""),
            recipe_status=str(delegated.get("status") or ""),
            results=results,
            result_count=len(results),
            instruction=(
                f"★ 사람이 검토한 읽기 전용 절차로 이 사이트의 목록을 열었다({len(results)}건). "
                "browser_open_result 에 rank 를 줘서 하나씩 들어가라. 급여·마감일 같은 "
                "값은 목록의 분류가 아니라 상세 화면 원문에서 읽어라."
            ),
        )

    @staticmethod
    def _filter_reviewed_results(
        results: list[dict[str, Any]], markers: list[str], *, limit: int
    ) -> list[dict[str, Any]]:
        """레시피가 검토한 상세 URL 표식만 남기고 순위를 다시 매긴다.

        `!` 로 시작하는 표식은 「이 글이 든 주소는 뺀다」(`result_links.EXCLUDE` — G마켓의 광고 카드는 상품과 같은
        주소 꼴에 `buyboxtype=ad` 만 더 붙는다).
        """
        from .result_links import EXCLUDE

        wanted = [marker for marker in markers if not marker.startswith(EXCLUDE)]
        unwanted = [marker[len(EXCLUDE):] for marker in markers if marker.startswith(EXCLUDE) and len(marker) > len(EXCLUDE)]
        selected = results
        if wanted or unwanted:
            selected = [
                item
                for item in results
                if (not wanted or any(marker in str(item.get("url") or "") for marker in wanted))
                and not any(marker in str(item.get("url") or "") for marker in unwanted)
            ]
        trimmed = selected[: max(1, limit)]
        return [{**item, "rank": index} for index, item in enumerate(trimmed, 1)]

    def forget_results(self) -> None:
        """지난 판의 검색 순위를 버린다. **판이 바뀔 때 부른다.**

        ## 왜 필요한가 (2026-08-14 실측, 사람인 판)

        `_last_results` 는 워커 인스턴스에 붙어 있어서 **잡이 끝나도 안 지워진다.**
        그래서 이런 일이 났다:

            (직전 판) 대학알리미 과제 — browser_search 로 순위 15개를 만듦
            (다음 판) 사람인 과제 — site_run 으로 사람인 검색 결과에 도착
              4  browser_open_result rank=38  → 실패 "있는 순위: 1~15"   ← 남의 순위다
              5  browser_open_result rank=1   → **academyinfo.go.kr** 로 감
              7  browser_extract              → 대학알리미 본문을 읽음

        사람인 화면에 서서 **대학알리미를 열고 읽었다.** 그리고 그것이 "읽은 출처"로
        세어졌다. 지목한 사이트를 두고 딴 데를 읽는 것 — 오늘 잡은 것 중 제일 나쁜
        종류다(광고 브리지 사고와 같은 부류인데, 이쪽은 우리 상태가 원인이다).

        ## 왜 "지금 화면"으로 못 가르나

        "결과를 딴 화면과 지금 화면이 다르면 버린다"로 하면 정상 경로가 깨진다 —
        결과 → 상세로 들어간 뒤 `rank 2` 를 여는 것이 바로 그 모양이고, 그건 이
        도구의 존재 이유다. 그러니 경계는 **화면이 아니라 판(잡)** 이어야 한다.
        """
        self._last_results = []
        self._results_departed_to = ""
        self._results_origin_links = frozenset()
        self._reads_since_search = 0
        self._searches_without_read = 0
        self._searched_before = False
        self._requested_stay = None
        self._named_sites = frozenset()
        self._named_addresses = ()
        self._named_request = ""
        self._tabs_before_job = []
        # 이 탭의 주인 기록도 판의 것이다 — 앞 판이 간 화면을 이 판이 간 곳으로 치지 않는다(첫 걸음의 화면이 새 출발점이다).
        self._own_page_keys = set()
        self._own_pages = []
        self._last_own_page = ""
        self._own_page_at = 0.0
        self._human_on_tab = None
        self._tab_handed_back = False

    # ── 사람이 같은 탭을 쓰고 있으면 손을 멈춘다 (2026-10-19 · 잡 51f35b07) ─────────────────────────────
    #
    # ## 무슨 일이 있었나
    #
    #   browser_open(github.com/sonjari/sonjari) → find → snapshot → click j15 → snapshot(★ accounts.google.com 계정 고르기 ·
    #   「사람이 111.3초 직접 조작」) → back(★ github.com/login?add_account=1&return_to=…/ollama/ollama — 이 판이 연 적 없는 화면) →
    #   snapshot(★ github.com/ollama/ollama · 「30.4초 직접 조작」) → **click j15** → snapshot
    #
    # 대표가 같은 탭에서 깃허브 계정을 더하고 있었다. 손자리는 「사람이 만졌다 · 다시 보라」는 알림(`_with_takeover_note`)을 받고도
    # 그 화면에서 뒤로 가고 눌렀다. 알림은 안내문이라 안 먹는다(사고 R). 결제 · 글쓰기 화면이었다면 사람 화면에서 단추를 눌렀다.
    #
    # ## 규칙 (안내가 아니라 문)
    #
    # 1. 이 판이 **스스로 간** 화면을 적는다 — 제 동작(열기 · 누르기 · 쓰기 …)이 끝난 뒤의 주소와, 열라고 한 주소.
    #    읽기 손(`_LOOKING_HANDS`)의 결과 주소는 적지 않는다(읽었다고 그 화면이 이 판의 것이 되지 않는다).
    # 2. 걸음마다 지금 주소를 본다. 적힌 화면이면 그대로.
    # 3. 적히지 않은 화면인데 **이 판이 마지막으로 간 뒤에 사람이 무대에서 크롬을 만졌으면** → 사람이 이 탭을 쓰고 있는 것 같다.
    #    화면을 바꾸는 손(`_HANDS_ON_THE_PAGE`)은 멈추고 `human_on_tab` 으로 돌려보낸다(반복문이 사람에게 넘긴다 —
    #    `stuck_hands._stuck_report`). 읽기는 이어 가되 알림을 붙인다. 제 주소를 여는 손(`_OWN_ADDRESS_HANDS`)은 막지 않는다 —
    #    사람 화면을 건드리지 않고 이 판의 화면을 새로 연다.
    # 4. 사람이 만진 흔적이 없으면 **받아들인다** — 우리 누르기 뒤 늦게 끝난 이동 · 광고 다리 주소 · 화면이 스스로 바꾼 주소다.
    #    운영 2,654판을 되짚으니 이런 「말없이 바뀐 주소」가 100번 넘게 있었고(다른 사이트로 바뀐 것도 30번 넘게 — 다나와 · 네이버
    #    광고 다리) 사람 흔적은 없었다 — 여기서 멈추면 전부 헛멈춤이다.
    # 5. 예외: 이 판이 간 **로그인 화면**에서 사람이 로그인을 마쳐 원래 사이트로 돌아온 것 — 같은 사이트로 돌아왔거나 로그인 주소가
    #    돌아갈 곳으로 적은 화면이면 이 판의 화면이다.
    #
    # 사람이 무대가 아니라 **크롬 창을 직접** 만지면(붙어 쓰는 남의 크롬) 흔적이 없어 이 문이 못 본다 — 남은 구멍이다.

    def hand_tab_back(self) -> None:
        """사람이 「이어서」를 눌렀다 — 다음 걸음의 지금 화면을 이 판의 화면으로 받고 멈춤을 푼다(멈춘 판을 이을 때 부른다)."""
        self._tab_handed_back = True

    def note_human_hand(self) -> None:
        """사람이 무대에서 크롬을 만졌다(돌려줄 때 `live_view` 가 부른다)."""
        self._human_hand_at = time.time()

    def _adopt_own_page(self, url: str) -> None:
        key = _own_key(url)
        if not key:
            return
        if key not in self._own_page_keys:
            self._own_page_keys.add(key)
            self._own_pages.append(url)
            if len(self._own_pages) > 400:
                self._own_pages = self._own_pages[-400:]
        self._last_own_page = url

    def _human_in_control_now(self) -> bool:
        view = getattr(self, "live_view", None)
        try:
            return bool(view is not None and view.human_in_control())
        except Exception:  # noqa: BLE001
            return False

    def _finished_a_login(self, url: str) -> bool:
        """이 판이 간 로그인 화면에서 사람이 로그인을 마치고 돌아온 화면인가(규칙 5)."""
        from .url_privacy import is_sign_in_url

        last = self._last_own_page
        if not last or not is_sign_in_url(last):
            return False
        site = _site_of_url(url)
        if site and any(_site_of_url(own) == site for own in self._own_pages if not is_sign_in_url(own)):
            return True
        try:
            pairs = parse_qs(urlparse(last).query)
        except ValueError:
            return False
        want = _own_key(url)
        return any(
            _own_key(unquote(value)) == want
            for values in pairs.values() for value in values if value.startswith("http")
        )

    def _hold_if_human_on_tab(self, action: str, page: Any) -> None:
        """걸음 앞에서 지금 화면이 이 판의 것인지 본다. 사람이 쓰는 화면이면 화면을 바꾸는 손을 멈춘다(위 규칙)."""
        from .url_privacy import safe_url

        try:
            url = str(getattr(page, "url", "") or "")
        except Exception:  # noqa: BLE001
            return
        if not _own_key(url):
            return
        if self._tab_handed_back:
            self._tab_handed_back = False
            self._human_on_tab = None
            self._adopt_own_page(url)
            self._own_page_at = time.time()
            return
        if self._human_on_tab is None:
            if not self._own_page_keys:
                # 판의 첫 화면 — 사람이 맡기며 띄워 둔 화면이거나 지난 판이 남긴 화면이다. 여기가 출발점이다.
                self._adopt_own_page(url)
                return
            if _own_key(url) in self._own_page_keys:
                return
            if not (self._human_in_control_now() or self._human_hand_at > self._own_page_at):
                self._adopt_own_page(url)  # 규칙 4 — 우리 동작의 늦은 이동
                return
            if self._finished_a_login(url):
                self._adopt_own_page(url)  # 규칙 5
                return
            self._human_on_tab = {"from": self._last_own_page, "to": url, "at": time.time()}
        if action in _HANDS_ON_THE_PAGE:
            hold = self._human_on_tab
            raise ValueError(
                "human_on_tab — 사람이 이 탭을 쓰고 있는 것 같다. 지금 화면("
                + safe_url(str(hold.get("to") or ""))[:160]
                + ")은 이 작업이 연 화면이 아니고, 이 작업이 마지막으로 간 뒤에 사람이 브라우저를 직접 만졌다(이 작업이 마지막으로 간 화면: "
                + safe_url(str(hold.get("from") or ""))[:160]
                + "). 여기서는 아무것도 누르거나 쓰지 않았다. 사람에게 이 탭을 다 썼는지 물어라 — 사람이 「이어서」를 누르면 "
                "그때의 화면에서 잇는다. 이 작업의 화면이 필요하면 browser_open 으로 그 주소를 새로 열어라(사람 화면은 건드리지 않는다)."
            )

    def _note_own_page_after(self, action: str, arguments: dict[str, Any], started: float) -> None:
        """제 동작이 끝난 뒤의 주소를 「이 판이 간 화면」으로 적는다(규칙 1). 사람이 그 사이에 만졌으면 끝 주소는 적지 않는다."""
        if action in _LOOKING_HANDS:
            return
        navigating = action in _OWN_ADDRESS_HANDS
        if self._human_on_tab is not None and not navigating:
            return
        asked = str(arguments.get("url") or "") if navigating else ""
        if asked:
            self._adopt_own_page(asked)
        if not self._human_in_control_now() and self._human_hand_at < started:
            try:
                self._adopt_own_page(str(getattr(self._page, "url", "") or ""))
            except Exception:  # noqa: BLE001
                pass
        elif not asked:
            return
        if navigating:
            self._human_on_tab = None
        self._own_page_at = time.time()

    def _with_human_on_tab_note(self, result: Any) -> Any:
        """사람이 쓰던 화면을 읽은 결과에 붙이는 알림 — 읽기는 하되 그 화면에서 손은 쓰지 않는다고."""
        hold = self._human_on_tab
        if not hold or not isinstance(result, dict):
            return result
        from .url_privacy import safe_url

        return {**result, "human_on_tab": (
            "사람이 이 탭을 쓰고 있는 것 같다 — 지금 화면(" + safe_url(str(hold.get("to") or ""))[:160]
            + ")은 이 작업이 연 화면이 아니다. 읽기만 했다. 이 화면에서 누르기 · 쓰기는 사람이 「이어서」를 누른 뒤에만 된다."
        )}

    def set_named_addresses(self, prompt: str) -> tuple[str, ...]:
        """이번 판의 요청문이 **적어 준 주소**를 읽어 두고, 지금 열려 있는 탭을 「전부터 있던 탭」으로 적는다. 판이 바뀔 때 부른다.

        ## 왜 (2026-10-07 폼 벤치 과제 J)

        요청은 `http://…/resume/basic 에서 … 고치고 저장해줘` 였다. 모델은 탭 목록부터 봤고, 거기 **다른 사이트의
        이력서 수정 탭**(사람이 전에 쓰던 실제 사이트)이 있자 그 탭으로 넘어갔다. 그 화면이 로그인 화면이라 사람 확인 문에서
        멈췄지만, 로그인이 살아 있었다면 **요청이 가리키지 않은 사이트의 폼**을 고칠 뻔했다.

        주소를 적어 준 요청은 「어디서」가 이미 정해져 있다. 그러니 판이 시작하기 전부터 열려 있던 **다른 사이트의 탭**으로는
        바꾸지 않고(`_switch_tab`), 그런 화면이 판이 시작할 때 이미 앞에 떠 있어도 거기서 **화면을 바꾸는 손**은 쓰지 않는다
        (`_refuse_hand_on_another_site` · `_SCREEN_HANDS`). 읽는 손은 그대로다.

        막지 않는 것: 같은 사이트의 탭 · 이 판이 연 탭(새 창으로 뜬 것) · 이 판이 스스로 주소를 연 탭(그때부터 이 판의 탭이다) ·
        웹 주소가 아닌 탭 · 요청문이 그 사이트를 글자로 말한 경우 · 주소가 없는 요청(「지금 열려 있는 … 탭에서 해줘」).
        """
        try:
            written = tuple(dict.fromkeys(m.group(0).rstrip(".,;:!?") for m in _WRITTEN_ADDRESS.finditer(prompt or "")))
            sites = frozenset(site for site in (_site_of_url(url) for url in written) if site)
            before = [item for item in self._context.pages if not item.is_closed()] if self._context is not None else []
        except Exception:
            # 못 읽는 것은 판을 죽일 일이 아니다. 안 적어 두면 예전대로 돈다.
            written, sites, before = (), frozenset(), []
        self._named_addresses = written if sites else ()
        self._named_sites = sites
        self._named_request = (prompt or "").casefold() if sites else ""
        self._tabs_before_job = before if sites else []
        return self._named_addresses

    def _another_site_tab(self, target: Any, *, switching: bool = True) -> str:
        """이 탭으로 바꾸면(또는 이 화면에서 손을 쓰면) 안 되는 까닭. 괜찮으면 빈 값."""
        if not self._named_sites or not any(target is item for item in self._tabs_before_job):
            return ""
        try:
            site = _site_of_url(str(target.url or ""))
        except Exception:
            return ""
        if not site or site in self._named_sites:
            return ""
        # 요청문이 그 사이트를 글자로 말했으면(도메인이나 그 앞 이름) 사용자가 가리킨 것이다.
        if site in self._named_request or site.split(".")[0] in self._named_request:
            return ""
        asked = " · ".join(self._named_addresses[:2])
        if switching:
            return (
                f"tab_is_another_site — 요청이 적어 준 주소는 {asked} 인데, 이 탭은 {site} 이고 이 작업을 시작하기 전부터 "
                "열려 있던 탭이다. 요청이 지목한 주소를 browser_open 으로 열어라. 사용자가 이 탭에서 하라고 한 것인지 "
                "확실하지 않으면 손대지 말고 물어봐라."
            )
        return (
            f"screen_is_another_site — 요청이 적어 준 주소는 {asked} 인데, 지금 화면은 {site} 이고 이 작업을 시작하기 전부터 "
            "떠 있던 화면이다. 여기서는 아무것도 바꾸지 않았다. 요청이 지목한 주소를 browser_open 으로 먼저 열어라. "
            "사용자가 이 화면에서 하라고 한 것인지 확실하지 않으면 손대지 말고 물어봐라."
        )

    def _refuse_hand_on_another_site(self, action: str, page: Any) -> None:
        """판이 시작할 때 앞에 떠 있던 **다른 사이트의 화면**에서는 화면을 바꾸는 손을 쓰지 않는다 (2026-10-07 폼 벤치 과제 J).

        탭 바꾸기만 막으면, 그 화면이 이미 앞에 있을 때는 바꾸지 않고도 채우고 누를 수 있다.
        """
        if action in _SCREEN_HANDS:
            refused = self._another_site_tab(page, switching=False)
            if refused:
                raise ValueError(refused)

    def _note_job_navigated(self, action: str) -> None:
        """이 판이 스스로 주소를 연 탭은 그때부터 이 판의 탭이다 — 거기서 다른 사이트로 넘어가는 것은 이 판이 한 일이다."""
        if action in _NAVIGATING_HANDS and self._tabs_before_job:
            self._tabs_before_job = [item for item in self._tabs_before_job if item is not self._page]

    def set_requested_stay(self, prompt: str) -> RequestedStay | None:
        """이번 판의 요청문에서 **묵을 날**을 읽어 둔다. 판이 바뀔 때 부른다.

        `forget_results()` 와 같은 자리에서 부르는 이유도 같다 — 워커는 잡보다 오래
        살아서, 안 지우면 지난 판의 날짜가 다음 판의 주소에 붙는다.

        못 읽으면 None 이고, 그러면 주소는 아무것도 안 바뀐다(예전 동작).
        """
        try:
            self._requested_stay = requested_stay(prompt)
        except Exception:
            # 날짜를 못 읽는 것은 판을 죽일 일이 아니다. 안 바꾸면 예전대로 돈다.
            self._requested_stay = None
        return self._requested_stay

    def _goto_with_dates(self, page: Any, url: str) -> DateRewrite | None:
        """날짜 인자가 있으면 **요청한 날짜로 바꿔서** 연다. 안 되면 원래 주소로.

        ## 왜 여기인가 (2026-09-04 실측, 잡 `cd3e84c0`)

        「이번 주 토요일 1박」이라고 했는데 목록이 준 상세 주소가 이랬다:

            …/stay/domestic/3011753?adultCount=2
                &checkInDate=2026-09-04&checkOutDate=2026-09-05

        자비스는 이 주소를 그대로 열어 본문을 진짜로 읽고 「50,000원」이라고 답했다.
        **9월 4일 밤의 값이다.** 9/5 는 60,000원이었고(하루 차이로 20%), 같은 판의
        다른 숙소는 9/5 에 예약마감이었다 — 즉 "있다"고 답한 곳이 못 자는 곳이었다.

        증거 원장은 이걸 못 잡는다. **가격은 진짜로 읽은 값이니까.** 틀린 것은 읽은
        값이 아니라 **어느 밤을 열었는가**다.

        날짜를 명시해서 다시 시켰더니 이번엔 달력 위젯을 32번 두드리다 673초에
        예산이 끝났다(잡 `3b5f3a76`). 그래서 위젯이 아니라 **주소**로 간다 —
        QA 쪽 정설도 한 줄로 같다: 「달력을 누르지 마라, 값을 직접 넣어라.」

        ## 폴백이 있는 이유

        바꾼 주소가 안 열릴 수 있다(사이트가 그 인자를 검사하거나, 그 조합이 없거나).
        그때는 **원래 주소로 되돌아간다** — 검색 주소를 사람처럼 쳐 보고 안 되면
        원래 주소로 가는 것(`_search_like_a_person`)과 같은 규칙이다. 못 바꾼 것이
        못 여는 것보다 낫다.
        """
        rewrite = rewrite_date_params(url, self._requested_stay)
        if rewrite is None:
            self._goto_checked(page, url)
            return None
        try:
            self._goto_checked(page, rewrite.url)
        except Exception:
            self._goto_checked(page, url)
            return None
        return rewrite

    def _apply_requested_dates_here(self, page: Any) -> DateRewrite | None:
        """**지금 떠 있는 목록**의 날짜를 요청한 날짜로 갈아 끼워 다시 연다.

        ## 왜 이게 따로 필요한가 (2026-09-05 라이브, 잡 `e8d7fa0f`)

        날짜 교체는 `_open` 과 `_open_result` **두 문에만** 걸려 있었다. 그런데
        목록은 그 문을 안 지난다 — 검색칸에 쳐서 그 자리에 뜨기 때문이다.
        여기어때 목록 주소에는 날짜가 그대로 실려 있었는데도:

            ?keyword=경주&checkIn=2026-09-05&checkOut=2026-09-06
                              ↑ 요청은 9/26 인데 아무도 안 바꿨다

        그래서 모델이 **달력을 10 걸음 두드렸다**(`browser_click` 6 회 +
        `ui_find_target` 실패 2 회). 24 걸음짜리 판의 42% 다.

        ## ★ 두 장치가 서로를 상쇄하고 있었다

        `_stay_note_for_list` 는 「주소로 바꿀 수 있으면 말 안 한다」였다. 바꿀 수
        있으니 침묵했고, **정작 바꿔 주는 사람이 없었다.** 둘 다 각자로는 맞는
        규칙인데 겹치는 자리에서 아무도 일을 안 했다.

        ## 크기 (정직하게)

        최근 4,000 판의 목록 걸음 1,062 건 중 주소에 날짜가 실린 것은 **5 건**
        (전부 여기어때)이다. 야놀자는 조건을 불투명한 덩어리에 접어서 이 길로는
        못 고친다. **분모는 작다.** 다만 걸리면 판의 40% 를 태우고, 고치는 비용은
        페이지 한 번 다시 여는 것뿐이다.
        """
        rewrite = None
        if self._requested_stay is None:
            return None
        try:
            url = str(getattr(page, "url", "") or "")
            rewrite = rewrite_date_params(url, self._requested_stay)
            if rewrite is None:
                return None
            self._goto_checked(page, rewrite.url)
            self._wait_until_operable(page)
        except Exception:
            # 못 바꾸면 있던 목록 그대로 쓴다 — 이 층은 거들 뿐이지 조건이 아니다.
            return None
        return rewrite

    def _stay_note_for_list(self, page: Any, *, applied: DateRewrite | None = None) -> str:
        """목록 화면에서 **날짜에 대해** 해 줘야 하는 말. 해당 없으면 빈 문자열.

        ## 왜 필요한가 (2026-09-04 라이브, 잡 `746b25bb`)

        상세 주소는 이제 도구가 갈아 끼운다. 그런데 **목록은 못 바꾼다** — 야놀자는
        검색 조건을 주소에 안 싣고 불투명한 덩어리 하나로 접어 둔다:

            /discovery/list/search/PRODUCT_CATEGORY_KOREA_ACCOMMODATION?filter=4XAAjW4Y…

        그래서 목록에 찍힌 가격은 **그 사이트가 고른 밤**의 값이다. 그걸 모르는 채로
        모델은 둘 중 하나를 한다:

            ① 목록 가격을 그대로 답에 쓴다 → 엉뚱한 밤의 값 (원래 고장)
            ② 달력 위젯을 두드린다 → 24걸음·608초를 태우고 그제야 상세를 연다

        ②가 실제로 났다. 그리고 ①을 부추긴 것은 **우리 안내문이었다** — 목록
        지시가 "목록 줄에 보이는 값은 상세를 안 열어도 그대로 답에 써라"라고 적혀
        있다. 날짜를 요청한 판에서는 그 말이 틀린다.

        여기서 하는 일은 안내다. 안내는 약하다는 것을 이 저장소가 안다(사고 R) —
        그래서 **결정론 쪽은 이미 박아 두고**(상세를 열면 도구가 날짜를 갈아 끼운다)
        그 사실을 알려 주는 것만 말로 한다. 「해라」가 아니라 「이미 돼 있다」이므로
        모델이 안 따라도 손해가 없다.
        """
        if self._requested_stay is None:
            return ""
        stay = self._requested_stay
        # ★ 방금 도구가 갈아 끼웠으면 **그렇다고 말한다.** (2026-09-05)
        #
        #   예전에는 「주소로 바꿀 수 있으면 말 안 한다」였다. 그런데 바꿀 수 있다는
        #   것과 바꿨다는 것은 다르다 — 목록은 `_open` 문을 안 지나서 아무도 안
        #   바꿨고, 침묵까지 겹쳐 **둘이 서로를 상쇄했다.** 모델은 그 사이에서
        #   달력을 10 걸음 두드렸다(잡 `e8d7fa0f`).
        if applied is not None:
            # ★ 여기서 **읽으라고** 말한다 (2026-09-05, 사람이 직접 확인).
            #
            #   「상세를 열면 도구가 날짜를 넣어 준다」고만 말했더니 판이 빈손이 됐다.
            #   여기어때를 직접 열어 보니 이랬다:
            #
            #       목록   란타나 … 숙박 15:00 체크인 · 회원가 177,000원   ← 답이 여기 있다
            #       상세   /91939 → 객실 9종이 **전부** 「다른 날짜 확인」
            #
            #   이 사이트는 상세 주소에 날짜가 없다. 그래서 상세로 보내면 값이 사라진다.
            #   날짜를 맞춘 목록이 **가장 정확한 자리**다.
            return (
                f"★ 목록을 사용자가 말한 날짜로 다시 열었다({applied.summary()}). "
                "달력 위젯을 누르지 마라, 이미 적용돼 있다. "
                "**가격·잔여는 이 목록 줄에서 읽어라** — 상세 페이지에는 그 날짜의 값이 "
                "없을 수 있다(실측: 상세의 객실이 전부 '다른 날짜 확인'이었다). "
                "★ 한 줄에 '대실'과 '숙박'이 같이 있으면 **다른 값**이다. 1박 요금은 "
                "'숙박' 쪽이다 — '대실'이 '다른 날짜 확인'이어도 '숙박'은 예약될 수 있다."
            )
        url = ""
        try:
            url = str(getattr(page, "url", "") or "")
        except Exception:
            pass
        # 주소에 날짜가 있고 그것이 이미 요청한 날짜면 바로잡을 것이 없다.
        if url and _DATE_IN_QUERY.search(url) and rewrite_date_params(url, stay) is None:
            return ""
        # ★ 「오늘」 하나만 말했고 기간이 없으면 **바로잡을 것이 없다** (2026-10-05). 지금 떠 있는 목록이 곧 오늘 것이다.
        #   운영 기록에서 이 경고가 붙은 12번 중 11번이 그 꼴이었다 — 레딧 6 · 네이버 뉴스 2 · 네이버 날씨 2 · K-Startup 1
        #   (의도한 숙박 사이트는 검증 판 1번). 「오늘 허깅페이스에서 뜨는 모델」에 「이 목록은 그 날짜가 아닐 수 있다 —
        #   가격·잔여를 쓰지 마라」가 붙어 9B 가 눈앞의 목록을 두고 날짜를 넣어 다시 검색했다. 며칠 묵는지(끝 날짜·N박)를
        #   말했으면 여전히 알린다.
        if stay.end is None and stay.start == datetime.now(KST).date():
            return ""
        span = f"{stay.start.isoformat()}"
        if stay.end is not None:
            span += f" ~ {stay.end.isoformat()}"
        return (
            f"★ 사용자가 말한 날짜는 {span} 인데 **이 목록은 그 날짜가 아닐 수 있다** "
            "(이 사이트는 검색 조건을 주소에 안 싣는다). 그러니 목록 줄의 가격·잔여를 "
            "그대로 답에 쓰지 마라. **달력 위젯을 누르지 마라** — 그건 예산만 태운다. "
            "browser_open_result 로 상세를 열면 도구가 그 날짜를 주소에 넣어서 연다. "
            "가격은 거기서 읽어라."
        )

    @staticmethod
    def _date_rewrite_evidence(rewrite: DateRewrite | None) -> dict[str, Any]:
        """바꿨으면 증거에 남긴다. **조용히 바꾸면 안 된다.**

        사람이 나중에 "왜 이 날짜를 봤나"를 물을 자리이고, 모델에게도 지금 화면이
        어느 날인지 알려 줘야 답에 그 날짜를 함께 쓴다.

        ## ★ 값이 평평한 이유 (2026-09-04 라이브에서 잡음)

        처음엔 `{"changed": {...}, "original_url": ...}` 처럼 **중첩 dict** 로 냈다.
        모델은 잘 받았는데(지시는 문자열이라 살아남았다) **장부에는 한 줄도 안
        남았다.** `agent._step_evidence` 마지막 줄이 이렇게 적혀 있다:

            # dict 는 안 싣는다 — 깊이가 어디까지인지 알 수 없다.

        이 저장소가 이미 여러 번 겪은 병이다 — 산출물 경로를 장부가 버려서 파일도
        각주도 실재하는데 대조가 ❌ 로 찍혔던 그 자리와 같다. 그래서 **문자열로**
        낸다. 장부를 통과하지 못하는 증거는 없는 증거다.
        """
        if rewrite is None:
            return {}
        return {
            "date_rewritten": rewrite.summary(),
            "date_original_url": rewrite.original_url,
            "date_instruction": (
                f"★ 요청한 날짜로 주소를 바꿔서 열었다({rewrite.summary()}). "
                "지금 화면은 그 날짜의 값이다 — 답에 쓸 때 이 날짜를 함께 밝혀라. "
                "달력 위젯을 누르지 마라, 이미 적용돼 있다."
            ),
        }

    def execute_trusted(self, action: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """사람이 쓰고 검토한 호출자만 쓰는 문 — 레시피가 이리로 들어온다.

        게이트웨이에 등록된 것은 `execute` 쪽뿐이라 모델은 이 문을 부를 수 없다.
        `approved` 와 같은 방식이다: 신뢰는 인자에 실어 보내는 값이 아니라
        **어느 문으로 들어왔는가**여야 한다. 인자로 넘기면 호출자가 지어낼 수 있고,
        실제로 `_approved` 가 그렇게 뚫려 있었다.
        """
        arguments = dict(arguments or {})
        self._wait_while_human_controls()
        return self._submit(
            lambda: self._execute(action, arguments, trusted=True),
            self.config.browser_task_timeout_sec,
            operation=f"trusted:{action}",
            mutating=action in self._MUTATING_ACTIONS,
        )

    def capture_confirmed_click_proof(
        self, arguments: dict[str, Any], *, screenshot: bool
    ) -> dict[str, Any]:
        """승인 카드와 실제 클릭을 같은 화면의 같은 요소에 묶는다.

        이 읽기는 일반 도구 실행과 같은 Playwright 스레드에서 한다. 승인 전에는
        사람이 볼 PNG까지 남기고, 실행 직전에는 빠르게 DOM 지문만 다시 읽는다.
        """
        arguments = dict(arguments or {})
        return self._submit(
            lambda: self._confirmed_click_proof(arguments, screenshot=screenshot),
            min(15, self.config.browser_task_timeout_sec),
            operation="browser_click_confirmed:proof_before"
            if screenshot
            else "browser_click_confirmed:proof_recheck",
        )

    def capture_confirmed_click_after(
        self, arguments: dict[str, Any], result: Any
    ) -> dict[str, Any]:
        """클릭 뒤 요소가 사라져도 현재 페이지 전체를 사후 근거로 남긴다."""
        return self._submit(
            lambda: self._confirmed_click_after(arguments, result),
            min(15, self.config.browser_task_timeout_sec),
            operation="browser_click_confirmed:proof_after",
        )

    def _free_cdp_port(self, base: int) -> int | None:
        """base 다음의 **아무도 안 쓰는** 포트 하나. 없으면 None."""
        import socket

        for port in range(base + 1, base + 40):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        return None

    def _connect_context(self) -> Any:
        """크롬에 붙는다 — 우리 방식(spawned/attached)이 먼저, 안 되면 자동화 크롬(launched).

        ★ 2026-09-20 운영: 9222 에 **남의 브라우저**가 답해 붙기가 실패했고(`Browser context management is not supported`)
          곧장 `launched` 로 내려갔다. 그 길에는 번쩍임 방지(최소화로 띄우고 맨 뒤로)가 없어 「파파박 → 뒤로 숨기」가 보였고,
          자동화 표시 때문에 봇 검사 사이트에서도 막힌다. 남의 포트에서 실패하면 **빈 포트에 우리 크롬을** 띄워 붙는다.
        """
        self._attach_error = ""
        base = int(self.config.browser_cdp_port or 9222)
        self._cdp_port_in_use = base
        if str(self.config.browser_attach_mode or "").strip().lower() != "off":
            # ★ 2026-09-24 브라우저 무대: 업데이트 뒤에는 옛 판이 띄운 크롬이 살아 있고 새 백엔드는 **붙기만** 한다. 그 크롬에는
            #   가림 판정 끄기 인자가 없어서 화면 밖에서 그리기를 멈춘다(스트림 0장·지연 로딩 안 됨). 우리 프로필 크롬이 그 인자 없이
            #   떠 있으면 한 번 끄고 새로 띄운다 — 로그인은 프로필에 남고, 잃는 것은 열려 있던 탭뿐이다.
            if self._our_chrome_needs_restart():
                self._kill_profile_chromes()
            try:
                return self._attach_chrome()
            except Exception as exc:
                # 내려가도 된다. 다만 **왜** 내려갔는지는 남긴다 —
                # 조용히 갈아타면 쿠팡이 다시 막힐 때 원인을 처음부터 다시 판다.
                self._attach_error = _clean(exc, 300)
                self._kill_chrome_process(self._chrome_proc)
                self._chrome_proc = None
            # ★ 고아를 되찾는다 (2026-08-19). 앞 백엔드를 강제 종료하면 그것이 띄운 크롬이 살아남아 포트와 프로필을
            #   쥔다. 우리 프로필을 쓰는 크롬은 우리 것이다 — 명령줄로 찾아 죽이고 한 번 더 붙는다.
            if self._kill_profile_chromes() > 0:
                try:
                    context = self._attach_chrome()
                    self._attach_error = ""
                    return context
                except Exception as retry_error:
                    self._attach_error = _clean(retry_error, 300)
                    self._kill_chrome_process(self._chrome_proc)
                    self._chrome_proc = None
            # ★ 2026-09-20: 그 포트의 주인이 우리 프로필이 아니면(남의 브라우저) 빈 포트에 우리 크롬을 띄운다.
            if not self._port_is_our_profile(base):
                spare = self._free_cdp_port(base)
                if spare is not None:
                    try:
                        context = self._attach_chrome(spare)
                        self._cdp_port_in_use = spare
                        self._attach_error = f"moved_off_foreign_port:{base}->{spare}"
                        return context
                    except Exception as spare_error:
                        self._attach_error = _clean(spare_error, 300)
                        self._kill_chrome_process(self._chrome_proc)
                        self._chrome_proc = None
        self._connect_mode = "launched"
        return self._launch_chrome()

    def _ensure_started(self) -> dict[str, Any]:
        if self._context_alive():
            return self._evidence("browser_ready")
        if self._context is not None or self._playwright is not None:
            self._shutdown()
        try:
            from playwright.sync_api import sync_playwright

            self._profile_dir.mkdir(parents=True, exist_ok=True)
            self.config.browser_download_dir.mkdir(parents=True, exist_ok=True)
            self._playwright = sync_playwright().start()
            self._context = self._connect_context()
            self._context.set_default_timeout(self.config.browser_action_timeout_sec * 1000)
            self._context.set_default_navigation_timeout(
                self.config.browser_navigation_timeout_sec * 1000
            )
            self._context.on("close", lambda *_: self._mark_disconnected())
            self._context.on("page", self._watch_page)
            self._context.on("page", self._claim_if_we_caused_it)
            pages = [page for page in self._context.pages if not page.is_closed()]
            # ★ 2026-09-16 실측: 탭 26장이 상한 6을 넘겼는데도 **한 장도 안 닫혔다**. 눈금을 붙여
            #   보니 `wanted_to_close: 0` — 26장 전부가 「동작 시작 전부터 있던 탭」이었다.
            #   크롬을 강제로 죽이면 다음 기동 때 **세션 복원**으로 그 무더기가 되살아나고,
            #   그 탭들은 우리가 만들지도 주소를 넣지도 않았으니 아무도 적지 않아 **영구 면역**이 됐다.
            #
            #   우리가 띄운 크롬이 방금 떴다면 거기 있는 탭은 **우리 지난 판의 잔여물**이다 —
            #   사람은 아직 이 창을 만진 적이 없다. 그러니 우리 것으로 적는다. 붙어 쓰는
            #   크롬(attached)은 사람의 창이라 건드리지 않는다.
            if self._browser_is_ours():
                for leftover in pages:
                    self._claim_page(leftover)
            reattached = [
                page
                for page in pages
                if self._reattach_url
                and str(getattr(page, "url", "") or "") == self._reattach_url
            ]
            if reattached and self._connect_mode == "attached":
                # 핸들 회수를 위한 재attach는 사람이 보던 탭을 새로 만들거나 빼앗지
                # 않고, 직전까지 자비스가 쓰던 정확한 URL로 돌아간다.
                self._page = reattached[-1]
            elif pages and self._connect_mode == "attached":
                # 붙기만 한 크롬에는 사람이 보던 탭이 있다. 그것을 빼앗지 않는다 —
                # 빈 탭이 있으면 거기 앉고, 없으면 새 탭을 연다.
                blank = [page for page in pages if str(getattr(page, "url", "") or "")
                         in ("", "about:blank", "chrome://newtab/")]
                self._page = blank[-1] if blank else self._new_page(home=False)
            else:
                self._page = pages[-1] if pages else self._new_page(home=False)
            self._reattach_url = ""
            for page in self._context.pages:
                self._watch_page(page)
            if self._connect_mode in ("attached", "spawned"):
                # 붙어 쓰는 크롬은 받는 곳이 크롬 설정을 따른다(Playwright 의
                # `downloads_path` 는 자기가 띄운 브라우저에만 걸린다).
                self._apply_download_dir(self._page)
            self._maximize_window(self._page)
            self._go_home(self._page)
            # ★ **띄우는 것 자체가 창을 앞으로 끌어온다** (2026-09-16 실측).
            #   앞창을 0.2초마다 재면서 확인했다: 크롬이 꺼진 상태에서 도구 하나를 부르면
            #   1.8초 뒤 `about:blank - Chrome` 이 앞으로 나오고 2.2초에 `NAVER - Chrome` 이 됐다.
            #   「사람이 쓰는 중」을 강제로 켠 판에서도 그랬다 — 이 자리는 양보 검사를 **한 번도**
            #   안 거쳤기 때문이다. `browser_open` 같은 뒤쪽 자리는 잘 막혀 있었다.
            #   바깥 AI(MCP)가 시킬 때 특히 아프다: 사람은 그때 다른 창에서 타이핑 중이다.
            self._yield_new_window(self._page)
            self._automation_flag = self._read_automation_flag(self._page)
            with self._lock:
                self._started_at = __import__("time").time()
                self._last_error = ""
                self._connected = True
            # 붙었으면 심장박동을 돌린다. 이게 없으면 **사람이 연 팝업이 갇힌다**
            # (`_pump_loop` 참고 — 2026-08-16 라이브로 증명한 자리다).
            self._start_pump()
            return self._evidence(
                "browser_started",
                connect_mode=self._connect_mode,
                attach_error=self._attach_error,
            )
        except Exception as exc:
            with self._lock:
                self._last_error = _clean(exc, 800)
            self._shutdown()
            raise RuntimeError(f"browser_start_failed:{_clean(exc, 500)}") from exc

    def _launch_chrome(self) -> Any:
        """예전 방식 — Playwright 가 직접 크롬을 띄운다.

        붙기가 안 될 때의 바닥이다. 이 길로 뜬 크롬은 `--remote-debugging-pipe`
        때문에 자동화 모드라(`navigator.webdriver=true`) Akamai 를 쓰는 곳
        (쿠팡 상품검색 등)에서는 막힌다. 막히면 막혔다고 말할 것.
        """
        # ★ 2026-09-16 실측: 크롬 양보를 고친 자리는 `_spawn_chrome` 하나였고, **이 폴백에는
        #   `--start-maximized` 가 인자 목록에 하드로 박혀** 있었다. 붙기가 실패해 이 길로
        #   내려온 판에서는 고친 것이 하나도 안 걸렸다 — 0.8초간 앞을 뺏기는 것을 재서 잡았다.
        #   상한이 사는 세 자리(dataclass·로더·**함수 안 하드 상수**) 중 셋째다(사고 Q).
        quiet = not self.config.browser_headless and not self._may_take_foreground()
        if not quiet:
            self._sink_report = {"where": "launch_chrome", "thread": "not started",
                                 "headless": bool(self.config.browser_headless),
                                 "may_take_foreground": self._may_take_foreground()}
        args = ["--disable-background-timer-throttling"]
        if not quiet:
            args.append("--start-maximized")
        else:
            args += self._offscreen_window_args()  # 화면 밖에서 태어나게 — 번쩍임의 뿌리 처방
        launch_args: dict[str, Any] = {
            "user_data_dir": str(self._profile_dir),
            "headless": self.config.browser_headless,
            "accept_downloads": True,
            "downloads_path": str(self.config.browser_download_dir),
            "args": args,
            "chromium_sandbox": self.config.browser_sandbox,
        }
        if self.config.browser_headless:
            launch_args["viewport"] = {"width": 1440, "height": 900}
        else:
            # Playwright otherwise emulates its 1280x720 default viewport even
            # after Chromium's native window is maximized, leaving gray gutters.
            launch_args["no_viewport"] = True
        if quiet:
            # 띄우기 **전에** 붙인다. `launch_persistent_context` 는 창이 뜨고 CDP 가 붙은
            # 뒤에야 돌아오므로, 돌아온 뒤에 감시를 시작하면 이미 앞을 뺏긴 뒤다.
            self._chrome_pid_answers.clear()
            self._chrome_scan_at = 0.0
            self._chrome_pids_before_launch = set(self._chrome_scan(max_age_sec=0.0))
            self._launch_watch_until = time.time() + 12.0
            self._sink_report = {"where": "launch_chrome", "thread": "starting"}
            self._sink_settled.clear()
            self._sunk_hwnds.clear()
            self._start_birth_guard()  # ★ 띄우기 전에
            threading.Thread(target=self._sink_new_chrome_window, daemon=True).start()
        self._turn_off_translate_in_our_profile()
        try:
            return self._playwright.chromium.launch_persistent_context(
                channel="msedge" if self._is_edge else "chrome", **launch_args
            )
        except Exception:
            if not self._browser_exe():
                raise RuntimeError(NO_BROWSER_MESSAGE) from None
            return self._playwright.chromium.launch_persistent_context(**launch_args)

    def _attach_chrome(self, port: int | None = None) -> Any:
        """평범하게 띄운 크롬에 DevTools 로 붙는다. 없으면 평범하게 하나 띄우고 붙는다.

        프로필은 예전과 **같은 폴더**를 쓴다(`browser_profile_dir`). Playwright 의
        영구 프로필은 그냥 크롬 user-data-dir 이라 chrome.exe 로 그대로 열리고,
        그래서 이미 해 둔 로그인이 그대로 딸려 온다.

        ★ 크롬 136 부터 **기본 프로필**(사람이 평소 쓰는 그 크롬)에서는
        `--remote-debugging-port` 가 무시된다. 그러니 "지금 떠 있는 저 크롬"에
        그냥 붙는 길은 없다 — 붙으려면 포트를 연 채로 뜬 크롬이어야 한다.
        사람이 직접 그렇게 띄워 두면 여기서 그 크롬을 찾아 붙는다.
        """
        port = int(port or self.config.browser_cdp_port or 9222)
        info = self._probe_cdp(port)
        if info is None:
            self._spawn_chrome(port)
            deadline = time.time() + max(5, int(self.config.browser_attach_launch_timeout_sec))
            died_at: float | None = None
            while info is None and time.time() < deadline:
                time.sleep(0.4)
                info = self._probe_cdp(port)
                if info is not None:
                    break
                if died_at is None and self._chrome_proc.poll() is not None:
                    # 크롬은 자기를 다시 띄우고 처음 프로세스를 끝내기도 한다.
                    # 그러니 죽었다고 곧바로 포기하지 않고 조금 더 기다린다.
                    died_at = time.time()
                if died_at is not None and time.time() - died_at > 3:
                    break
            if info is None:
                raise RuntimeError(
                    f"cdp_port_never_opened:{port} — 같은 프로필로 크롬이 이미 떠 있으면"
                    " chrome.exe 는 그 프로세스에 일을 넘기고 끝나 포트가 열리지 않습니다."
                )
            self._connect_mode = "spawned"
            self._attached_is_ours = True
            if getattr(self, "_first_window_pending", False):
                self._first_window_pending = False
                self._open_first_window_background(info)
        else:
            # ★ 2026-09-23: 그 포트의 크롬이 **다른 온텔릭**(다른 설치·시험판)의 자동화 크롬이면 붙지 않는다.
            #   붙으면 두 온텔릭이 크롬 하나를 같이 몬다 — 스토어 촬영용 앱이 이 PC 평소 온텔릭 크롬(9222)에 붙어
            #   다나와 본문 읽기가 180초씩 멈췄고(평소 앱 혼자면 2.2초), 로그인된 남의 프로필이 그 앱 화면에 찍힐 뻔했다.
            #   사람이 자기 프로필로 포트를 열어 둔 크롬에는 예전처럼 붙는다 — 막는 것은 「다른 온텔릭」뿐이다.
            #   여기서 던지면 `_connect_context` 가 빈 포트에 우리 크롬을 띄운다(남의 포트 → 빈 포트 길 그대로).
            if not self._port_is_our_profile(port) and self._port_is_another_ontelic(port):
                raise RuntimeError(f"another_ontelic_chrome:{port} — 다른 손자리가 쓰는 크롬이라 붙지 않습니다")
            # 우리가 띄운 크롬이 아니다. 남의 창이니 끄지 않는다(`_shutdown`).
            self._connect_mode = "attached"
            # ★ 2026-09-16 실측: 「우리가 안 띄웠다」와 「우리 것이 아니다」는 다른 말이다.
            #   앞 판의 백엔드가 띄워 둔 크롬은 포트를 쥔 채 남아 있고, 다음 판은 거기에 **붙는다**.
            #   그 크롬을 남의 창으로 읽어서 창도 안 내리고(3.4초 뺏김) 탭도 안 닫았다(26장 그대로).
            #   프로필로 정한다 — `_kill_profile_chromes`·`_is_our_chrome_pid` 가 쓰는 것과 같은 규칙.
            self._attached_is_ours = self._port_is_our_profile(port)
        browser = self._playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        contexts = list(browser.contexts)
        if self._connect_mode == "attached" and self._attached_is_ours:
            self._park_existing_windows()
            if BrowserWorker._park_offscreen and not self.config.browser_headless:
                # 백엔드만 다시 켜진 판(업데이트·재기동)도 감시가 있어야 한다 — 예전엔 새로 띄울 때만 세웠다.
                self._start_park_rescue()
        return contexts[0] if contexts else browser.new_context()

    def _open_first_window_background(self, info: dict[str, Any]) -> bool:
        """창 없이 띄운 크롬에 **첫 창을 뒤쪽·화면 밖에** 만든다 — 활성화가 일어나지 않는다.

        ★ 2026-09-26 부산 노트북: 보이지 않는 크롬이 콜드스타트마다 앞창을 쥐었다(1.1~40초, 사람이 쓰는 중). 감시기의 되돌려주기는
          백엔드에 앞창 권한이 없어 `returned=False` 로 늘 실패했다. 이 PC 에서 띄우는 방식만 바꿔 3회씩 쟀더니
          보통 띄우기 1,400·1,400·1,400ms · 창 없이 띄우고 CDP 로 뒤쪽 창 0·0·0ms. 뺏긴 걸 돌려받지 말고 안 뺏기게 한다.
        못 만들면 False — 그때는 Playwright 가 평소대로 창을 만든다(일이 죽으면 안 된다).
        """
        try:
            from websockets.sync.client import connect

            url = str((info or {}).get("webSocketDebuggerUrl") or "")
            if not url:
                return False
            left, top = 20000, 0
            if sys.platform == "win32":
                import ctypes

                user32 = ctypes.windll.user32
                left = int(user32.GetSystemMetrics(76)) + int(user32.GetSystemMetrics(78)) + 200
                top = int(user32.GetSystemMetrics(77))
            with connect(url, open_timeout=3, ping_interval=None) as socket:
                socket.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {
                    "url": "about:blank", "newWindow": True, "background": True,
                    "left": left, "top": top, "width": 1600, "height": 1000,
                }}))
                reply = json.loads(socket.recv(timeout=5))
            return "result" in reply
        except Exception:  # noqa: BLE001
            return False

    def _park_existing_windows(self) -> int:
        """**이미 떠 있던** 우리 크롬 창을 화면 밖으로 치운다 (2026-09-24 노트북 「한 번 반짝」).

        치우는 코드는 크롬을 **새로 띄울 때만** 돌았다. 업데이트해도 크롬은 앱 밖 프로그램이라 살아남고, 새 백엔드는
        거기에 **붙기만** 해서 옛 판이 화면 안 맨 뒤에 둔 창이 그대로 남았다 — 탭을 열 때 크롬이 스스로 올라오며 번쩍였다.
        사람이 보고 있는 창(앞창)은 건드리지 않는다. 최소화된 창은 그대로 둔다(보이지 않는 것은 번쩍이지 않는다).
        """
        if sys.platform != "win32" or not BrowserWorker._park_offscreen:
            return 0
        try:
            import ctypes

            user32 = ctypes.windll.user32
            parked = 0
            for hwnd in self._our_chrome_windows():
                if user32.IsZoomed(hwnd) and int(user32.GetForegroundWindow() or 0) != int(hwnd):
                    # 최대화된 창은 크기를 주면 안 풀린다 — 투명한 채로 보통 크기로 되돌린 뒤 옮긴다.
                    self._restore_quietly(user32, hwnd)
                    parked += 1
                    continue
                if BrowserWorker._park_window_offscreen(user32, hwnd):
                    parked += 1
            return parked
        except Exception:  # noqa: BLE001 — 창 하나 때문에 붙기를 실패시키지 않는다
            return 0

    @staticmethod
    def _probe_cdp(port: int) -> dict[str, Any] | None:
        """포트에 **실제로 물어본다.** 열려 있다는 짐작으로 붙으면 그때 가서 터진다."""
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2
            ) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except Exception:
            return None

    def _chrome_scan(self, *, max_age_sec: float = 1.0) -> dict[int, str]:
        """돌고 있는 크롬들의 pid → 명령줄. **한 번에 몰아 읽고 잠깐 캐시한다.**

        ★ 2026-09-16 실측으로 두 번 물렸다:
          ① 처음엔 `wmic` 으로 pid 하나씩 물었다. **이 PC(Windows 11 26200)에 wmic 이 없어서**
             호출이 죽고 우리는 그것을 「우리 것 아님」으로 삼켰다 — 크롬의 손자 창을 한 번도
             못 알아봤다.
          ② 그 다음엔 `psutil` 로 바꿨는데, **포장본에는 psutil 이 없다**(빌드 검사가
             `optional off: … psutil` 로 알려 줬다). 노트북·스토어 판에서는 고침이 통째로
             안 걸릴 판이었다.

        그래서 둘 다 없어도 되게 한다: psutil 이 있으면 쓰고(빠르다, 실측 27개 10ms), 없으면
        **파워셸 한 번**으로 전체를 받는다(pid 마다 부르면 감시 스레드가 초당 50번 프로세스를 만든다).
        """
        if sys.platform != "win32":
            return {}
        now = time.time()
        if self._chrome_scan_at and now - self._chrome_scan_at < max_age_sec:
            return self._chrome_scan_rows
        rows: dict[int, str] = {}
        try:
            import psutil

            for process in psutil.process_iter(["name", "cmdline"]):
                if (process.info["name"] or "").lower() == self._exe_name:
                    rows[int(process.pid)] = " ".join(process.info["cmdline"] or [])
        except ImportError:
            try:
                import subprocess as _sp

                done = _sp.run(
                    ["powershell", "-NoProfile", "-Command",
                     "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
                     f"Get-CimInstance Win32_Process -Filter \"Name='{self._exe_name}'\" | "
                     "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
                    capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
                )
                for line in (done.stdout or "").splitlines():
                    pid, _, command = line.partition("	")
                    if pid.strip().isdigit():
                        rows[int(pid.strip())] = command
            except Exception:  # noqa: BLE001
                return self._chrome_scan_rows
        except Exception:  # noqa: BLE001
            return self._chrome_scan_rows
        self._chrome_scan_rows = rows
        self._chrome_scan_at = now
        return rows

    #: 화면 밖에서도 그리게 하는 인자(`_spawn_chrome`). 이 인자 없이 떠 있는 우리 크롬은 옛 판의 것이다.
    _OCCLUSION_FLAG = "--disable-backgrounding-occluded-windows"

    def _our_chrome_needs_restart(self) -> bool:
        """우리 프로필 크롬이 **가림 판정 끄기 없이** 떠 있나(옛 판이 띄운 것). 주차를 안 쓰면 상관없다."""
        if sys.platform != "win32" or not BrowserWorker._park_offscreen or self.config.browser_headless:
            return False
        try:
            profile = str(self._profile_dir)
            mains = [line for line in self._chrome_scan(max_age_sec=0.0).values()
                     if profile in line and "--remote-debugging-port=" in line and "--type=" not in line]
        except Exception:  # noqa: BLE001 — 못 보면 건드리지 않는다
            return False
        # 음소거(09-26)도 같은 이유로 본다 — 옛 크롬이 계속 돌면 자동 재생 영상 소리가 난다.
        return bool(mains) and not any(self._OCCLUSION_FLAG in line and "--mute-audio" in line for line in mains)

    def _port_is_our_profile(self, port: int) -> bool:
        """그 포트를 쥔 크롬이 **우리 프로필**로 떠 있나. 그러면 우리가 안 띄웠어도 우리 것이다."""
        profile = str(self._profile_dir)
        needle = f"--remote-debugging-port={port}"
        return any(profile in line and needle in line
                   for line in self._chrome_scan(max_age_sec=0.0).values())

    def _port_is_another_ontelic(self, port: int) -> bool:
        """그 포트를 쥔 크롬이 **다른 온텔릭의 프로필**로 떠 있나 — 폴더 이름은 우리와 같고(`browser-profile`) 자리가 다르다."""
        ours = Path(str(self._profile_dir))
        needle = f"--remote-debugging-port={port}"
        for line in self._chrome_scan(max_age_sec=0.0).values():
            if needle not in line:
                continue
            match = re.search(r'--user-data-dir="?([^"]+?)"?(?:\s--|\s*$)', line)
            if not match:
                continue
            theirs = Path(match.group(1).strip())
            if theirs.name.lower() == ours.name.lower() and str(theirs).lower() != str(ours).lower():
                return True
        return False

    def _browser_is_ours(self) -> bool:
        """이 크롬을 우리가 정리해도 되나(창 내리기·탭 닫기).

        우리가 띄운 것이거나, 우리 프로필로 떠 있어 우리가 붙은 것이면 우리 것이다.
        사람이 **자기 프로필**로 포트를 열어 둔 크롬에 붙은 경우에만 False 다 — 그때는
        창도 안 내리고 탭도 안 닫는다(남의 창이다).
        """
        if self._connect_mode in ("launched", "spawned"):
            return True
        return bool(getattr(self, "_attached_is_ours", False))

    def _find_chrome(self) -> str:
        configured = str(self.config.browser_chrome_path or "").strip()
        if configured:
            if not Path(configured).exists():
                raise RuntimeError(f"chrome_not_found:{configured}")
            return configured
        candidates: list[Path] = []
        if sys.platform == "win32":
            for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(variable)
                if base:
                    candidates.append(
                        Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
                    )
        else:
            candidates += [
                Path("/usr/bin/google-chrome"),
                Path("/usr/bin/google-chrome-stable"),
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ]
        for path in candidates:
            if path.exists():
                return str(path)
        for name in ("chrome", "google-chrome", "google-chrome-stable"):
            found = shutil.which(name)
            if found:
                return found
        # ★ 2026-09-29 밤 AWS(윈도우 서버·크롬 없음): 크롬만 찾아서 브라우저 일을 통째로 못 했다. 엣지는 윈도우 10/11 에
        #   늘 있고 같은 크로미움이라 CDP·Playwright 가 그대로 붙는다(`channel="msedge"`).
        edge_candidates: list[Path] = []
        if sys.platform == "win32":
            for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
                base = os.environ.get(variable)
                if base:
                    edge_candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        for path in edge_candidates:
            if path.exists():
                return str(path)
        found = shutil.which("msedge")
        if found:
            return found
        raise RuntimeError(NO_BROWSER_MESSAGE)

    def _browser_exe(self) -> str:
        """찾은 브라우저 실행 파일(없으면 빈 값). 한 번 찾으면 기억한다 — 프로필·프로세스 이름이 이걸 따른다."""
        cached = getattr(self, "_found_browser_exe", None)
        if cached is None:
            try:
                cached = self._find_chrome()
            except Exception:  # noqa: BLE001 — 못 찾은 것과 같다(설정 칸이 없는 판도). 프로필·이름은 크롬 쪽 그대로
                cached = ""
            self._found_browser_exe = cached
        return cached

    @property
    def _is_edge(self) -> bool:
        return Path(self._browser_exe()).name.lower() == "msedge.exe"

    @property
    def _exe_name(self) -> str:
        """창·프로세스를 가려낼 때 보는 이름. 크롬 없는 PC 에서는 엣지다."""
        return "msedge.exe" if self._is_edge else "chrome.exe"

    @property
    def _profile_dir(self) -> Path:
        """우리 브라우저 프로필. 엣지는 **다른 폴더** — 크롬 프로필을 엣지로 열면 둘이 섞여 깨질 수 있다."""
        base = Path(self.config.browser_profile_dir)
        return base.with_name(base.name + "-edge") if self._is_edge else base

    def _turn_off_translate_in_our_profile(self) -> bool:
        """**온텔릭 전용 프로필에서만** 크롬 번역을 끈다. 띄우기 직전(그 프로필 크롬이 안 떠 있을 때)에만 부른다.

        ★ 2026-09-18: 영어 페이지가 번역체로 읽혀(OpenAI→「오픈아이」) 모델이 그 이름을 답에 옮겼다. `--disable-*` 플래그는
          자동화 브라우저처럼 보이게 하니 쓰지 않고, 사람이 설정 화면에서 끄는 것과 같은 자리(Preferences 의 translate.enabled)를 쓴다.
          사람의 크롬 프로필은 절대 건드리지 않는다 — 경로가 우리 프로필이 아니면 아무것도 안 한다.
        """
        import json as _json

        try:
            profile = Path(self._profile_dir)
            prefs_path = profile / "Default" / "Preferences"
            prefs: dict[str, Any] = {}
            if prefs_path.exists():
                prefs = _json.loads(prefs_path.read_text(encoding="utf-8") or "{}")
            translate = prefs.get("translate") if isinstance(prefs.get("translate"), dict) else {}
            if translate.get("enabled") is False:
                return False
            prefs["translate"] = {**translate, "enabled": False}
            prefs_path.parent.mkdir(parents=True, exist_ok=True)
            temp = prefs_path.with_suffix(".ontelic-tmp")
            temp.write_text(_json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, prefs_path)
            return True
        except Exception:  # noqa: BLE001 - 못 바꿔도 띄우기는 계속한다(번역 감지가 뒤를 받친다)
            return False

    def _mark_our_profile_exited_cleanly(self) -> bool:
        """**온텔릭 전용 프로필의** 지난 종료를 「정상」으로 적는다. 띄우기 직전(그 크롬이 안 떠 있을 때)에만 부른다.

        ★ 2026-09-18 밤 사용자: 「온텔릭이 크롬을 띄울 때 팍 떴다가 스르륵 들어간다 — 사용자가 놀란다.」
          온텔릭이 재시작·업데이트되면 크롬이 강제로 꺼지고, 프로필에 `exit_type: Crashed` 가 남는다. 다음에
          띄우면 크롬이 **「페이지를 복원할까요?」 말풍선을 띄우면서 창을 스스로 앞으로 끌어올린다** — 우리
          감시가 「다 떴다」고 본 뒤(2.9초쯤)라, 감시는 포커스를 돌려주려고 최소화·복원을 되풀이했다.

              운영 프로필 조건(Crashed) 5판   사람 창 위로 200~300ms(4/5) · 최소화 4~8번 · 앞창 약 4.8초
              같은 조건에서 Normal 로만 바꾼 5판   0ms · 0번 · 0초 (×5)
              (bench/browser_agents/measure_chrome_flash.py, SEED_LIKE_LIVE=1)

          `--hide-crash-restore-bubble` 플래그도 있지만 쓰지 않는다 — `_spawn_chrome` 의 규칙대로 플래그는
          자동화 브라우저처럼 보이게 한다. 사람이 크롬을 정상 종료했을 때 남는 값과 같은 자리를 쓴다.
          사람의 크롬 프로필은 건드리지 않는다 — 이 경로는 온텔릭 전용 프로필이다.
        """
        import json as _json

        try:
            prefs_path = Path(self._profile_dir) / "Default" / "Preferences"
            if not prefs_path.exists():
                return False  # 처음 뜨는 프로필 — 복원할 것이 없다
            prefs = _json.loads(prefs_path.read_text(encoding="utf-8") or "{}")
            profile = prefs.get("profile") if isinstance(prefs.get("profile"), dict) else {}
            if profile.get("exit_type") == "Normal" and profile.get("exited_cleanly") is True:
                return False
            prefs["profile"] = {**profile, "exit_type": "Normal", "exited_cleanly": True}
            temp = prefs_path.with_suffix(".ontelic-tmp")
            temp.write_text(_json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, prefs_path)
            return True
        except Exception:  # noqa: BLE001 - 못 적어도 띄우기는 계속한다(감시가 창을 내린다)
            return False

    def _spawn_chrome(self, port: int) -> None:
        """크롬을 **사람이 띄우듯이** 띄운다.

        ★ 여기에 `--disable-*` 를 덧대지 않는다. 플래그를 더할수록 다시 자동화
        브라우저처럼 보이고, 그러면 이 전환의 이유가 통째로 사라진다.
        """
        self._turn_off_translate_in_our_profile()
        self._mark_our_profile_exited_cleanly()
        arguments = [
            self._find_chrome(),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={self._profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        # ★ 사람이 쓰는 중이면 **내려놓고, 활성화하지 않은 채로** 띄운다 (2026-09-16 실측).
        #
        #   띄운 뒤에 내리는 것으로는 늦다. 앞창을 0.2초마다 재 보니 크롬이 **3초 동안**
        #   앞을 차지했다 — 그 사이에 친 글자는 크롬으로 들어간다. 창 상태를 나중에 고치는
        #   방식으로는 못 막는다. 크롬을 띄우는 것이 우리이므로, **띄우는 순간**에 정한다:
        #   윈도우의 `STARTUPINFO.wShowWindow = SW_SHOWMINNOACTIVE` 는 「최소화해서, 포커스는
        #   주지 말고」라는 뜻이고 크로미움이 첫 창에 그대로 따른다.
        #
        #   최소화한 채로도 일은 된다(2026-09-16: 창 내린 채 조사→문서 3판 전부 성공).
        #
        #   ★ 2026-09-16 덧붙임: 일은 되지만 **그림이 안 나온다.** 최소화한 창의 탭은 캡처 요청에 답을
        #     안 해서 브라우저 일꾼이 통째로 멈췄다(`_capture`). 그래서 뜨는 동안만 최소화하고, 다 뜨면
        #     활성화 없이 되살려 **맨 뒤로** 둔다(`_yield_new_window`). 처음부터 맨 뒤로만 보냈더니
        #     크롬이 포커스를 쥔 채 남아 0.2~1.0초 뺏겼다 — 뜨는 동안은 최소화가 답이었다.
        quiet_start = (
            sys.platform == "win32"
            and not self.config.browser_headless
            and not self._may_take_foreground()
        )
        if self.config.browser_headless:
            arguments.append("--headless=new")
        elif not quiet_start:
            arguments.append("--start-maximized")
        if quiet_start:
            arguments += self._offscreen_window_args()  # 화면 밖에서 태어나게 — 번쩍임의 뿌리 처방
        if quiet_start and BrowserWorker._park_offscreen:
            # ★ 2026-09-24 브라우저 무대: 화면 밖 창을 크롬은 **가려진 창**으로 보고 그리기를 멈춘다(visibilityState=hidden).
            #   실측(이 PC, 3초): 화면 안 32장 · 화면 밖 0장 → 이 인자를 주면 화면 밖 32장 · visible. 스트림만의 일이 아니다 —
            #   숨은 페이지는 지연 로딩 그림·IntersectionObserver 가 안 돌아 온텔릭이 빈 자리를 읽는다.
            #   위 원칙(`--disable-*` 를 덧대지 않는다)의 예외다: 이 인자는 웹페이지가 볼 수 있는 흔적이 없다(navigator·UA 불변).
            arguments.append("--disable-backgrounding-occluded-windows")
            # ★ 2026-09-26 부산 노트북: 가림 판정을 끄자 화면 밖 크롬이 **네이버 검색 결과의 클립 미리보기를 자동 재생**했다
            #   (사용자: 「클립·동영상을 튼다」). 사람 화면에 안 보이는 창에서 소리까지 나면 최악이다. 음소거 + 자동 재생은 사람
            #   손짓이 있어야. 둘 다 페이지가 볼 수 있는 흔적이 없고, 자동 재생 막힘은 보통 크롬에서도 흔하다.
            arguments.append("--mute-audio")
            arguments.append("--autoplay-policy=user-gesture-required")
            BrowserWorker._focus_return_logged = 0
            if bool(getattr(self.config, "browser_no_startup_window", True)):
                # 첫 창은 포트가 열린 뒤 `_open_first_window_background` 가 뒤쪽·화면 밖에 만든다.
                arguments.append("--no-startup-window")
                self._first_window_pending = True
        creationflags = 0
        startupinfo = None
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if quiet_start:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                # SW_SHOWMINNOACTIVE. 최소화한 채로는 탭이 그림을 안 만들지만(`_capture`), 그건 **다 뜬 뒤**
                # `_yield_new_window` 가 활성화 없이 되살려 맨 뒤로 보내 푼다(2026-09-16).
                startupinfo.wShowWindow = 7
        self._chrome_pid_answers.clear()  # pid 는 재사용된다 — 새 크롬에는 새 답이 필요하다
        self._chrome_scan_at = 0.0
        # ★ 스캔 비용을 **창이 뜨기 전에** 낸다 (2026-09-16 실측). psutil 이 없는 포장본에서는
        #   이 스캔이 401ms 라, 창이 나타난 뒤에 물으면 그 사이에 앞을 뺏긴다(0.6초의 정체였다).
        #   지금 있는 크롬은 사람의 것이고, 이 뒤에 새로 생기는 크롬 pid 는 우리가 띄운 것이다.
        self._chrome_pids_before_launch = set(self._chrome_scan(max_age_sec=0.0))
        self._launch_watch_until = time.time() + 12.0
        if quiet_start and BrowserWorker._park_offscreen:
            self._start_park_rescue()
        if quiet_start:
            self._sink_settled.clear()
            self._start_birth_guard()  # ★ 띄우기 **전에** — 창이 태어난 뒤에는 늦다
        self._chrome_proc = subprocess.Popen(  # noqa: S603 - 경로는 우리가 찾은 chrome.exe
            arguments,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        if quiet_start:
            # ★ 시작 플래그만으로는 못 막는다 (2026-09-16 실측). 크롬은 **자기를 다시 띄우므로**
            #   시작 플래그(`wShowWindow`)가 손자 프로세스까지 안 간다. 실제로 창이 뜬 순간 앞을 뺏겼다.
            #   그래서 창이 나타나는 것을 지켜보다가 **나타나자마자 내린다.** 몇 백 ms 안이라
            #   사람이 치던 것을 빼앗기 전에 끝난다. 못 잡아도 그냥 지나간다 — 창 하나 때문에
            #   브라우저 기동을 실패시키지 않는다.
            self._sink_report = {"where": "spawn_chrome", "thread": "starting"}
            self._sink_settled.clear()
            self._sunk_hwnds.clear()
            threading.Thread(target=self._sink_new_chrome_window, daemon=True).start()

    def _sink_new_chrome_window(self, *, watch_sec: float = 8.0) -> None:
        """방금 띄운 크롬 창이 나타나면 **내리고, 앞창을 원래 주인에게 돌려준다.**

        「띄우긴 띄우되 앞으로만 나오지 않게」가 요구다(2026-09-16 사용자). 그래서 닫지 않고
        내린다 — 작업 표시줄에서 바로 볼 수 있다.

        ★ 2026-09-16 두 번째 실측: 이 감시가 있는데도 크롬이 **0.6초** 앞을 쥐었다. 둘이 겹쳤다.
          ① 창을 hwnd 별로 **한 번만** 내렸다(`seen` 에 넣고 건너뜀). 크롬은 첫 탭이 뜨면 자기
             창을 다시 올리므로, 같은 hwnd 가 두 번째로 올라온 것을 아무도 안 내렸다 —
             실측 로그에 `about:blank - Chrome` 과 `Google - Chrome` 두 제목이 찍힌 이유다.
          ② 앞창만 봤다. 창이 **나타나는 순간**이 아니라 **앞을 쥔 뒤**에야 알게 되니, 0.1초
             표집으로도 이미 늦다.
          그래서 앞창을 기다리지 않고 **우리 크롬의 창을 직접 찾아** 보이는 즉시 내린다.
          처음 2초는 촘촘히(0.02초) 본다 — 창이 그 사이에 생긴다.
        """
        if sys.platform != "win32":
            return
        if not bool(getattr(self.config, "browser_sink_windows", True)):
            self._sink_report = {"thread": "disabled", "why": "browser_sink_windows=0"}
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            keep = user32.GetForegroundWindow()
            started = time.time()
            deadline = started + watch_sec
            # ★ **촘촘히 보는 구간은 다 뜬 뒤까지 이어진다** (2026-09-21 실측).
            #
            #   예전엔 2초였다. 그런데 번쩍임은 **2.9~3.0초**에 왔고 길이가 20ms 였다 —
            #   그 구간의 감시는 0.1초마다 보므로 **한 번도 못 본다.** 되살린 뒤에도
            #   우리가 탭을 열면 크롬이 창을 스스로 올리는데, 그 순간이 여기다.
            #   늦게 반응하는 것은 번쩍임을 못 막는다 — 보는 주기가 사건보다 굵으면
            #   그 사건은 우리에게 존재하지 않는다.
            close_watch_until = started + 6.0
            self._sink_report = {**self._sink_report, "ticks": 0, "sunk": 0, "errors": 0,
                                 "last_error": "", "thread": "running"}
            restored = False
            while time.time() < deadline:
                # ★ 실수 하나로 감시를 **끝내지 않는다** (2026-09-16 실측). try 가 루프 **밖에**
                #   하나뿐이라, 창을 훑는 도중 한 번 튄 예외가 그 판의 감시를 통째로 멈췄다.
                #   그 판만 크롬이 3.4초 앞을 쥐었다 — 0.0초 판들과 같은 코드에서 나온 꼬리다.
                #   창 하나 때문에 감시를 포기할 이유가 없다: 세고, 남기고, 계속 본다.
                self._sink_report["ticks"] += 1
                try:
                    settled = self._sink_settled.is_set()
                    if settled and not restored:
                        # ★ 2026-09-16: 다 떴다 — 내려 둔 창을 **활성화 없이 되살려 맨 뒤로** 둔다.
                        #   최소화한 채로 두면 탭이 그림을 안 만들어 실시간 화면이 안 찍힌다(`_capture`).
                        #   같은 스레드에서 되살린다: 다른 스레드가 되살리는 사이 이 루프가 다시
                        #   최소화하는 경합을 없앤다.
                        self._restore_sunk_windows(user32)
                        restored = True
                        self._sink_report["restored_at"] = round(time.time() - started, 2)
                    if not settled:
                        # 뜨는 동안은 **보이는 즉시 최소화한다.** 맨 뒤로만 보내면 크롬이 포커스를
                        # 쥔 채 남아 0.2~1.0초 뺏겼다(2026-09-16 실측 — 최소화하던 판은 0.0 ×9).
                        # 크롬은 뜨는 도중에 스스로 창을 여러 번 활성화하므로 이 구간엔 최소화가 답이다.
                        for hwnd in self._our_chrome_windows():
                            user32.ShowWindow(hwnd, 7)  # SW_SHOWMINNOACTIVE
                            self._sunk_hwnds.add(int(hwnd))
                            self._sink_report["sunk"] += 1
                    # ★ **앞을 안 뺏고 위로만 올라오는 길이 따로 있다** (2026-09-21 실측).
                    #
                    #   다 뜬 뒤 여기서는 「앞창을 쥐었나」만 봤다. 그런데 크롬의 복원 말풍선은
                    #   포커스를 **안 뺏고** z 순서만 올린다 — 사람 눈에는 똑같이 번쩍인다.
                    #
                    #       Crashed 조건 4판:  front_ms 0 · over_user_ms 20 · 보인 시각 2.95초 (3/4)
                    #       (되살린 시각은 0.58초 — 번쩍임은 그보다 2.4초 뒤에 온다)
                    #
                    #   ★ **이 줄은 그 20ms 번쩍임을 못 없앴다** (실측: 3/4 → 3/5 → 2/5, n=5 에서
                    #     잡음 범위). 20ms 는 어떤 표집보다 짧아 **반응으로는 못 막는다** — 막으려면
                    #     올리는 쪽을 없애야 한다(다음 사람의 일: 2.9~3.0초에 무엇이 창을 올리는지).
                    #     그래도 남겨 둔다: 「앞창만 보면 보이는 번쩍임을 통째로 놓친다」는 것은
                    #     `front_ms 0 · over_user_ms 20` 으로 증명됐고, 더 느린 올림은 이 줄이 잡는다.
                    #
                    #   「앞창을 뺏겼나」와 「화면에 보이나」는 다른 질문이다. 앞엣것만 보면
                    #   뒤엣것이 통째로 안 보인다 — 빈 값 하나가 두 사실을 뜻할 때와 같은 병이다.
                    #   되살린 뒤에는 z 순서도 같이 본다. 활성화하지 않고 조용히 내린다.
                    if settled and keep and self._is_above_other(user32, keep):
                        for ours in self._our_chrome_windows():
                            self._send_window_to_back(user32, ours)
                        rose = self._sink_report.setdefault("rose_above_at", [])
                        if len(rose) < 20:
                            rose.append(round(time.time() - started, 2))
                    # 그래도 앞을 쥐고 있으면 원래 주인에게 돌려준다.
                    hwnd = user32.GetForegroundWindow()
                    pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if hwnd and self._window_is_ours(hwnd, int(pid.value)):
                        if settled:
                            self._give_focus_back(user32, hwnd, keep)
                        else:
                            user32.ShowWindow(hwnd, 7)
                            self._sunk_hwnds.add(int(hwnd))
                            if keep and keep != hwnd:
                                user32.SetForegroundWindow(keep)
                        # 언제·몇 번 돌려줬나 — 앞창 눈금의 꼬리를 이 칸과 맞대어 읽는다.
                        gave = self._sink_report.setdefault("gave_back_at", [])
                        if len(gave) < 20:
                            gave.append(round(time.time() - started, 2))
                except Exception as tick_error:  # noqa: BLE001
                    self._sink_report["errors"] += 1
                    self._sink_report["last_error"] = _clean(tick_error, 200)
                time.sleep(0.02 if time.time() < close_watch_until else 0.1)
            self._sink_report["thread"] = "done"
        except Exception as fatal:  # noqa: BLE001
            self._sink_report = {"fatal": _clean(fatal, 200)}
            return

    def _is_above_other(self, user32: Any, other: int) -> bool:
        """우리 크롬 창 중 하나가 z 순서에서 `other` 보다 **위**인가.

        맨 위 창부터 아래로 훑어 **먼저 만나는 쪽**이 위다. 포커스와는 다른 질문이다 —
        크롬의 복원 말풍선은 앞창을 안 뺏고 z 순서만 올리므로, 앞창만 보면 이 번쩍임을
        통째로 놓친다(2026-09-21 실측: front_ms 0 · over_user_ms 20).

        ★ 최소화·숨김 창은 세지 않는다. 보이지 않는 것은 번쩍이지 않는다.
        """
        try:
            ours = {int(h) for h in self._our_chrome_windows()}
            if not ours:
                return False
            hwnd = user32.GetTopWindow(0)
            for _ in range(4000):
                if not hwnd:
                    return False
                if int(hwnd) == int(other):
                    return False
                if int(hwnd) in ours and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                    return True
                hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
        except Exception:  # noqa: BLE001 — 못 봤으면 건드리지 않는다
            return False
        return False

    @staticmethod
    def _send_window_to_back(user32: Any, hwnd: int) -> None:
        """창을 **보이는 채로 맨 뒤로** 보낸다. 활성화하지 않고, 크기·위치·최대화도 그대로 둔다.

        ★ 2026-09-16 저녁: 크롬을 **최소화한 채로 두지 않는다.** 최소화한 창의 탭은 그림을 안 만들어
          실시간 화면 캡처가 답을 안 받고 브라우저 일꾼을 통째로 쥐었다(이어받기 e2e 5·6·7판 stuck).
          사용자 요구도 「띄우긴 띄워라, 앞으로만 안 나오면 된다」였다.
          다만 **뜨는 동안에는** 최소화한다 — 처음부터 이것만 썼더니 크롬이 포커스를 쥔 채 남아
          0.2~1.0초 뺏겼다. 순서: 뜨는 동안 최소화(감시) → 다 뜨면 되살려 여기로(`_restore_sunk_windows`).
          보이는 창에 `ShowWindow(SW_SHOWNOACTIVATE)` 를 쓰지 않는다: 최대화된 창을 보통 크기로 되돌린다.
          앞창 실측(n=9 × 네 갈래): `bench/browser_agents/results/foreground/README.ko.md`.
        """
        # ★ 2026-09-24 제품 결정: 일하는 동안 크롬은 **화면 밖에 펴 둔다**(「주차」). 끝나도 안 띄우고, 로그인·보안문자·
        #   결제처럼 사람이 할 일이 있을 때만(`show_browser(activate=True)`) 화면 안으로 데려온다.
        #   노트북(1920×1200·125%)에서 「화면 밖 출생 → 작업 영역으로 데려와 맨 뒤」가 사람 눈에 「파바박 하다 뒤로 숨음」
        #   으로 보였다 — 맨 뒤라도 화면 **위에** 있으면 앞창이 다 덮지 않는 한 보이고, 크롬은 탭을 열 때마다 스스로 올라온다.
        #   화면 밖에 펴 둔 창은 최소화가 아니라서 계속 그린다(실측: visibilityState=visible · 캡처 0.05초, 화면 안과 같다).
        #   사람이 작업 표시줄에서 누르면 `_park_rescue` 가 화면 안으로 데려온다(안 보이는 앞창을 남기지 않는다).
        if BrowserWorker._park_offscreen and int(hwnd) in BrowserWorker._human_shown:
            # 사람이 불러 둔 창 — 자리는 그대로, 순서만 맨 뒤(치우면 보던 것을 뺏는다).
            user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            return
        if BrowserWorker._park_offscreen and BrowserWorker._park_window_offscreen(user32, hwnd):
            return
        # ★ 주차 중에는 **화면 밖에 있는 창을 화면 안으로 데려오지 않는다** (2026-09-24 노트북 측정).
        #   노트북 화면 세션에서 5ms 로 재 보니 크롬은 화면 밖(x=2650, 폭 1920)에서 **제대로 태어나 그대로 있었다** — 끌어온 건
        #   아래 옛 규칙(「어느 모니터에도 없는 창 = 유령 → 작업 영역으로」)이었다. 막 태어난 크롬이 잠깐 앞창을 쥐면 위 주차가
        #   「사람이 보는 창」으로 알고 비켜 가고, 그러면 이 규칙이 잘 숨은 창을 화면 안으로 끌고 와 번쩍였다.
        if BrowserWorker._park_offscreen:
            # ★ 2026-09-24 부산 노트북: 여기까지 왔다는 건 치우기를 못 했다는 것이다(앞창이거나 최대화). 예전에는 화면 **안**에
            #   있던 창을 아래 옛 규칙이 작업 영역 전체로 펴 버렸다 — 「화면 전체 크롬」이 그것이었다. 주차 중에는 자리를 건드리지
            #   않고 순서만 맨 뒤로 둔다. 화면 안에 남았으면 감시(`_start_park_rescue`)가 앞창을 돌려준 뒤 치운다.
            # HWND_BOTTOM=1 · SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE — 자리는 그대로, 순서만 맨 뒤
            user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            return
        # ★ 2026-09-17 사용자 화면: 크롬이 「최소화는 아닌데 안 보이는」 창이 됐다 — 좌표 (-32000,-32000), 크기 516×129.
        #   최소화로 **태어난** 창은 「원래 크기·위치」를 가진 적이 없어서, 되살리면 최소화 때의 자리·크기로 돌아온다.
        #   작업 표시줄에서 눌러도 안 보이고, 실시간 화면은 그 작은 창을 찍어 흰 줄만 나왔다.
        #   그런 창이면 **사람이 쓰는 모니터의 작업 영역 크기로 펴서** 맨 뒤에 둔다(활성화 없이).
        #
        # ★ 2026-09-18 사용자 화면: 「516×129 만큼 망가지지는 않았는데 비율이 이상한」 창. 같은 뿌리다 —
        #   조용히 뜨는 길은 `--start-maximized` 를 안 붙이므로(`_spawn_chrome`, 최소화 출생과 싸운다)
        #   되살아난 창은 크롬이 정한 기본 크기다. 예전 기준(480×360 보다 크면 멀쩡)은 그것을 통과시켰다.
        #   이제 **최대화가 아닌 우리 창은 작업 영역으로 편다.** 최대화된 창은 그대로 둔다 — 크기를 주면
        #   최대화가 풀린다. 펴기는 `SetWindowPos`(SWP_NOACTIVATE)라 앞창을 뺏지 않는다. `ShowWindow`
        #   최대화는 활성화하므로 쓰지 않는다(2026-09-18 「팍 → 스르륵」이 그 자리였다).
        try:
            placement = BrowserWorker._usable_window_rect(user32, hwnd)
        except Exception:  # noqa: BLE001 - 자리를 못 재면 예전처럼 z 순서만 바꾼다
            placement = None
        if placement is not None:
            left, top, width, height = placement
            # HWND_BOTTOM=1 · SWP_NOACTIVATE=0x10 (위치·크기를 준다)
            user32.SetWindowPos(hwnd, 1, left, top, width, height, 0x0010)
            return
        # HWND_BOTTOM=1 · SWP_NOSIZE=0x1 | SWP_NOMOVE=0x2 | SWP_NOACTIVATE=0x10
        user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

    #: 일하는 동안 크롬을 화면 밖에 펴 둘까(설정 `browser_park_offscreen`, 워커가 켤 때 채운다).
    _park_offscreen: bool = False

    @staticmethod
    def _park_window_offscreen(user32: Any, hwnd: int) -> bool:
        """창을 **모든 모니터 바깥**에 보통 크기로 펴 둔다(활성화 없이, 맨 뒤). 못 하면 False.

        사람이 보고 있는 창(앞창)·사람이 최대화한 창은 건드리지 않는다 — 치우는 건 우리가 띄운 뒤의 일이지
        사람이 쓰는 창을 뺏는 게 아니다.
        """
        try:
            if int(hwnd) in BrowserWorker._human_shown:
                return False  # 사람이 불러 둔 창
            if int(user32.GetForegroundWindow() or 0) == int(hwnd) or user32.IsZoomed(hwnd):
                return False
            left = int(user32.GetSystemMetrics(76)) + int(user32.GetSystemMetrics(78)) + 200  # 가상 화면 오른쪽 밖
            top = int(user32.GetSystemMetrics(77))
            width = int(user32.GetSystemMetrics(16)) or 1280   # SM_CXFULLSCREEN — 페이지가 보통 크기로 그리게
            height = int(user32.GetSystemMetrics(17)) or 800
            # ★ 2026-09-24 브라우저 무대: 무대 비율에 맞춰 둔 크기(`LiveView.fit`)를 치울 때마다 되돌리면 화면이 출렁인다.
            #   창이 제 크기(보통 이상)면 **자리만** 옮긴다. 작게 남은 유령 창(516×129 같은)만 크기를 준다.
            flags = 0x0010  # SWP_NOACTIVATE
            try:
                import ctypes
                import ctypes.wintypes as wt

                rect = wt.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)) and rect.right - rect.left >= 800 and rect.bottom - rect.top >= 500:
                    flags |= 0x0001  # SWP_NOSIZE
            except Exception:  # noqa: BLE001 — 못 재면 예전처럼 크기도 준다
                pass
            # HWND_BOTTOM=1
            return bool(user32.SetWindowPos(hwnd, 1, left, top, width, height, flags))
        except Exception:  # noqa: BLE001 — 못 치우면 예전 길(작업 영역 맨 뒤)
            return False

    @staticmethod
    def _user_input_within(seconds: float) -> bool:
        """사람이 마지막으로 키보드·마우스를 쓴 지 `seconds` 안인가(윈도우 `GetLastInputInfo`). 못 재면 False."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            import ctypes.wintypes as wt

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return False
            idle_ms = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
            return idle_ms <= seconds * 1000
        except Exception:  # noqa: BLE001
            return False

    #: 사람이 **직접 불러서** 화면 안에 둔 우리 크롬 창(hwnd). 이 창들은 화면 밖으로 치우지 않는다.
    #: 부르는 길은 셋뿐이다 — 「크롬 창 보기」(`present_for_human(activate=True)`), 작업 표시줄 클릭, Alt+Tab.
    _human_shown: set[int] = set()

    #: 크롬 창을 부르는 셸 창들 — 작업 표시줄·그 위에 뜨는 미리보기.
    _SUMMON_CLASSES = frozenset({
        "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "TaskListThumbnailWnd",
        "XamlExplorerHostIslandWindow", "MultitaskingViewFrame", "TaskSwitcherWnd", "ForegroundStaging",
    })

    @classmethod
    def _human_summoned(cls, user32: Any, alt_seen_at: float, click_seen_at: float = 0.0, click_class: str = "") -> bool:
        """우리 크롬이 앞창이 된 **그 순간** 사람이 부른 흔적이 있나.

        ★ 2026-09-24 부산 노트북: 「1초 안에 입력이 있었나」로 가렸더니, 사람이 노트북을 **쓰는 중이면** 늘 참이었다.
          입력이 **어디서** 왔는지를 보게 고쳤다: 작업 표시줄 클릭, 또는 Alt+Tab.
        ★ 2026-09-26 부산 노트북(사람이 한글로 채팅하는 중): 크롬이 20초 화면에 나왔다. 「작업 표시줄 클릭」 판정이 실제로는
          **아무 입력(키보드 포함) + 지금 커서가 작업 표시줄 위**였다 — 작업 표시줄에서 창을 켠 뒤 커서를 거기 둔 채 타자를 치면
          「불렀다」가 됐다. 이제 감시 루프가 **마우스 왼쪽 버튼이 눌리는 순간**과 그때 커서 아래 창 종류를 적고(`click_*`), 그것만 본다.
        """
        now = time.time()
        if now - alt_seen_at < 1.5:
            return True
        return now - click_seen_at < 1.0 and click_class in cls._SUMMON_CLASSES

    @classmethod
    def _class_under_cursor(cls, user32: Any) -> str:
        """지금 커서 아래 최상위 창의 종류. 모르면 빈 문자열."""
        try:
            import ctypes
            import ctypes.wintypes as wt

            point = wt.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                return ""
            under = user32.WindowFromPoint(point)
            root = user32.GetAncestor(under, 2) if under else 0  # GA_ROOT
            return cls._window_class(int(root or 0))
        except Exception:  # noqa: BLE001
            return ""

    def _start_park_rescue(self) -> None:
        """화면 밖에 펴 둔 우리 크롬을 **계속 화면 밖에 둔다.** 사람이 부를 때만 화면 안으로 데려온다.

        ## 왜 (2026-09-24 부산 노트북, 사람이 쓰는 중에 잰 것)

        치우는 코드는 정해진 순간(새 창·탭·되살리기)에만 돌았다. 그 사이에 크롬이 **스스로** 화면 안에 나오면
        (최소화에서 되살아나거나, 대화 상자를 띄우거나) 다음 치우기까지 그대로 보였다 — 사람 입력 없이 9초 보였다.
        그래서 감시가 0.1초마다 본다:

        - 우리 크롬이 **화면 밖에서 앞창**이 됐다 → 사람이 불렀으면(`_human_summoned`) 화면 안으로.
          아니면 크롬 혼자 쥔 것이다 — 0.3초 안에 앞창을 원래 창에 돌려준다(안 보이는 크롬이 타자를 먹지 않게).
        - 우리 크롬이 **화면 안에** 나와 있는데 사람이 부른 창이 아니다 → 다시 화면 밖으로.
        """
        if sys.platform != "win32" or getattr(self, "_park_rescue_started", False):
            return
        self._park_rescue_started = True

        def watch() -> None:
            import ctypes
            import ctypes.wintypes as wt

            user32 = ctypes.windll.user32
            try:
                user32.MonitorFromWindow.restype = ctypes.c_void_p
                user32.GetForegroundWindow.restype = ctypes.c_void_p
                user32.WindowFromPoint.restype = ctypes.c_void_p
                user32.GetAncestor.restype = ctypes.c_void_p
                user32.GetWindow.restype = ctypes.c_void_p
            except AttributeError:
                pass
            _ensure_message_queue(user32)
            last_other = 0       # 사람이 마지막으로 쓰던 (우리 것이 아닌) 앞창
            grabbed_at = 0.0     # 화면 밖 우리 크롬이 앞창이 된 시각
            alt_seen_at = 0.0
            click_seen_at = 0.0  # 마우스 왼쪽 버튼이 **눌린 순간**
            click_class = ""     # 그 순간 커서 아래 창 종류
            mouse_was_down = False
            tick = 0
            while True:
                time.sleep(0.05)
                tick += 1
                try:
                    if _alt_tab_held(user32):  # Alt+Tab 은 Alt 를 뗄 때 창이 바뀐다 — 그 순간을 1.5초 기억한다
                        alt_seen_at = time.time()
                    mouse_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
                    if mouse_down and not mouse_was_down:
                        click_seen_at = time.time()
                        click_class = self._class_under_cursor(user32)
                    mouse_was_down = mouse_down
                    if tick % 2:
                        continue
                    BrowserWorker._human_shown = {h for h in BrowserWorker._human_shown
                                                  if user32.IsWindow(h) and not user32.IsIconic(h)}
                    hwnd = int(user32.GetForegroundWindow() or 0)
                    pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    fg_ours = bool(hwnd) and self._window_is_ours(hwnd, int(pid.value))
                    if hwnd and not fg_ours:
                        last_other = hwnd  # ★ 뜨는 동안에도 적는다 — 돌려줄 창을 알아야 최소화 없이 돌려준다
                        grabbed_at = 0.0
                    if time.time() < float(getattr(self, "_launch_watch_until", 0.0) or 0.0):
                        # ★ 2026-09-24 부산 노트북(사람이 쓰는 중): 뜨는 동안 크롬이 앞창을 **12초** 쥐었다 — 가라앉히기 감시의
                        #   되돌려주기가 사람이 쓰는 중에는 안 먹었다. 여기서는 창을 움직이지 않고 **앞창만** 돌려준다
                        #   (최소화로 넘기는 길은 가라앉히기 감시와 싸워 창이 깜빡인다 — `.600` 측정의 최소화·복원 수십 번).
                        if fg_ours and hwnd not in BrowserWorker._human_shown and last_other:
                            if grabbed_at == 0.0:
                                grabbed_at = time.time()
                            elif time.time() - grabbed_at >= 0.3:
                                self._return_focus(user32, hwnd, last_other, move=False)
                                grabbed_at = 0.0
                        continue
                    # 말풍선·대화 상자(주인이 있는 창)는 주 창을 따른다 — 판단은 주 창으로 한다.
                    main = int(user32.GetWindow(hwnd, 4) or 0) if fg_ours else 0  # GW_OWNER
                    main = main if main and self._window_is_ours(main, int(pid.value)) else hwnd
                    if fg_ours and main not in BrowserWorker._human_shown:
                        offscreen = not user32.MonitorFromWindow(main, 0)  # MONITOR_DEFAULTTONULL
                        if grabbed_at == 0.0:
                            grabbed_at = time.time()
                            if offscreen and self._human_summoned(user32, alt_seen_at, click_seen_at, click_class):
                                # 왜 불렀다고 봤는지 남긴다 — 09-26 한/영 오판은 이유가 안 남아 가설로만 잡았다.
                                logging.getLogger(__name__).info(
                                    "chrome shown for human: %s",
                                    "alt_tab" if time.time() - alt_seen_at < 1.5 else "taskbar_click")
                                self._show_for_human(user32, main)
                                grabbed_at = 0.0
                                continue
                        if time.time() - grabbed_at >= 0.3:
                            # 크롬 혼자 앞을 쥐었다 — 돌려주고 화면 밖으로(화면 안에 나왔어도 사람이 부른 게 아니다).
                            self._return_focus(user32, hwnd, last_other, main=main)
                            grabbed_at = 0.0
                        continue
                    # 앞창이 아닌데 화면 안에 나온 우리 크롬 — 사람이 부른 창이 아니면 도로 밖으로.
                    for ours in self._our_chrome_windows():
                        if ours in BrowserWorker._human_shown or user32.GetWindow(ours, 4):  # GW_OWNER — 말풍선은 주인을 따른다
                            continue
                        if user32.IsIconic(ours):
                            continue
                        if user32.MonitorFromWindow(ours, 0):
                            if user32.IsZoomed(ours):
                                self._restore_quietly(user32, ours)
                            else:
                                BrowserWorker._park_window_offscreen(user32, ours)
                            continue
                        # 최소화로 태어난 창을 되살리면 (-32000,-32000) 작은 창으로 남는다 — 안 보이지만 페이지가 작게 그려진다
                        # (2026-09-17 실시간 화면 흰 줄). 제 크기로 화면 밖 오른쪽에 다시 편다.
                        rect = wt.RECT()
                        if user32.GetWindowRect(ours, ctypes.byref(rect)) and rect.left <= -30000:
                            BrowserWorker._park_window_offscreen(user32, ours)
                except Exception:  # noqa: BLE001 — 감시 하나 때문에 일이 죽으면 안 된다
                    grabbed_at = 0.0

        threading.Thread(target=watch, daemon=True, name="chrome-park-keeper").start()

    def _show_for_human(self, user32: Any, hwnd: int) -> None:
        """사람이 부른 크롬 창을 사람이 쓰는 모니터 작업 영역에 편다. 이 창은 이제 치우지 않는다."""
        BrowserWorker._human_shown.add(int(hwnd))
        placement = self._usable_window_rect(user32, hwnd)
        if placement is not None:
            left, top, width, height = placement
            user32.SetWindowPos(hwnd, 0, left, top, width, height, 0x0040)  # HWND_TOP · SWP_SHOWWINDOW

    #: 돌려주기 진단을 몇 번 남겼나 — 크롬을 새로 띄울 때 0 으로(`_spawn_chrome`).
    _focus_return_logged = 0

    @classmethod
    def _return_focus(cls, user32: Any, hwnd: int, keep: int, *, main: int = 0, move: bool = True) -> None:
        """크롬이 혼자 쥔 앞창을 **원래 창에 돌려주고** 크롬은 화면 밖·맨 뒤에 둔다.

        먼저 입력 큐를 잠깐 이어 `SetForegroundWindow(keep)` 를 시도한다 — 최소화를 안 거쳐서 창이 움직이지 않는다.
        윈도우가 그래도 막으면 예전 길(`_give_focus_back`: 최소화로 윈도우가 활성을 넘기게)로 간다.
        """
        import ctypes

        kernel32 = ctypes.windll.kernel32
        returned = False
        attached = False
        if keep and user32.IsWindow(keep):
            ours_thread = user32.GetWindowThreadProcessId(hwnd, None)
            me = kernel32.GetCurrentThreadId()
            attached = bool(ours_thread) and bool(user32.AttachThreadInput(me, ours_thread, True))
            try:
                user32.SetForegroundWindow(keep)
            finally:
                if attached:
                    user32.AttachThreadInput(me, ours_thread, False)
            returned = int(user32.GetForegroundWindow() or 0) == int(keep)
        main = int(main or hwnd)
        # ★ 2026-09-26 부산 노트북(사람이 쓰는 중): 안 보이는 크롬이 앞창을 27.8초 쥐었다 — 돌려주기가 실패하는지, 돌려줘도 크롬이
        #   다시 뺏는지 기록이 없어 못 갈랐다. 한 번 뜰 때 앞 5번만 남긴다(경고 — 포장본 로그는 정보 수준을 안 남긴다).
        if cls._focus_return_logged < 5:
            cls._focus_return_logged += 1
            try:
                after = int(user32.GetForegroundWindow() or 0)
                logging.getLogger(__name__).warning(
                    "chrome focus return: returned=%s attached=%s move=%s keep=%s(%s) after=%s(%s)",
                    returned, attached, move, keep, cls._window_class(int(keep or 0)), after, cls._window_class(after))
            except Exception:  # noqa: BLE001
                pass
        if not move:
            return  # 뜨는 동안 — 창은 출생 가드·가라앉히기 감시의 몫이다
        if returned:
            if not cls._park_window_offscreen(user32, main):
                user32.SetWindowPos(main, 1, 0, 0, 0, 0, 0x0013)  # 맨 뒤·자리 그대로
            return
        cls._give_focus_back(user32, main, keep)

    @staticmethod
    def _usable_window_rect(user32: Any, hwnd: int) -> tuple[int, int, int, int] | None:
        """이 창을 펼 자리(left, top, width, height). 손댈 필요가 없으면 None.

        **최대화된 창은 None** — 크기를 주면 최대화가 풀린다. 그 밖의 우리 창은 작업 영역이 답이다:
        조용히 뜨는 길에는 `--start-maximized` 가 없어서(최소화 출생과 싸운다) 되살아난 창이
        크롬 기본 크기로 남는다. 이미 작업 영역을 덮고 있으면 역시 None.

        자리는 **그 창이 있는 모니터**의 작업 영역이다 — 보조 모니터에 뜬 창을 주 모니터로 끌어오지 않는다.
        어느 모니터에도 없는 창(최소화 자리에서 되살아난 유령)만 사람이 지금 쓰는 모니터로 데려온다.
        보조 모니터가 왼쪽이면 좌표가 음수다: 좌표 부호가 아니라 **모니터 위에 있는가**로 가른다.
        """
        import ctypes
        import ctypes.wintypes as wt

        # 모니터 핸들은 64비트 값이다 — 기본 int 반환형이면 잘려 GetMonitorInfo 가 헛돈다.
        try:
            user32.MonitorFromRect.restype = ctypes.c_void_p
            user32.MonitorFromWindow.restype = ctypes.c_void_p
            user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        except AttributeError:  # 시험용 가짜 user32
            pass
        rect = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        # MONITOR_DEFAULTTONULL=0 — 어느 모니터와도 안 겹치면 0
        on_monitor = bool(user32.MonitorFromRect(ctypes.byref(rect), 0))
        if on_monitor and user32.IsZoomed(hwnd):
            return None

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

        # 모니터 위에 있는 창은 제 모니터에서 편다. 유령 창만 사람이 보는 화면으로 데려온다.
        anchor = hwnd if on_monitor else (user32.GetForegroundWindow() or hwnd)
        # MONITOR_DEFAULTTOPRIMARY=1
        monitor = user32.MonitorFromWindow(anchor, 1)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        work_w, work_h = work.right - work.left, work.bottom - work.top
        if on_monitor and width >= work_w and height >= work_h:
            return None
        return work.left, work.top, work_w, work_h

    def _restore_sunk_windows(self, user32: Any) -> int:
        """우리가 **내려 둔 창만** 활성화 없이 되살려 맨 뒤로 보낸다.

        내려 둔 창은 둘이다: 감시가 최소화한 창(`_sunk_hwnds`), 그리고 **처음부터 최소화로 뜬 창**.
        ★ 2026-09-16 실측: 운영 기본 길(`_spawn_chrome`)은 `wShowWindow=7` 을 크롬이 그대로 따라서
          창이 한 번도 보이는 상태를 안 거쳤다 — 감시가 적은 것이 0개라 되살릴 것도 0개였고,
          실시간 화면이 18판 중 0판 찍혔다. 그래서 이 판에 띄운 크롬의 최소화된 창도 같이 되살린다
          (다 뜬 직후라 사람이 그 창을 만졌을 틈이 없다).
        """
        count = 0
        for hwnd in set(self._sunk_hwnds) | set(self._our_chrome_windows(include_iconic=True)):
            try:
                if user32.IsWindow(hwnd) and user32.IsIconic(hwnd):
                    self._restore_quietly(user32, hwnd)
                    self._send_window_to_back(user32, hwnd)
                    count += 1
            except Exception:  # noqa: BLE001
                pass
        self._sunk_hwnds.clear()
        return count

    #: 뜨는 동안 **막 태어난 크롬 주 창**을 보이기 전에 투명하게 만든 것들: hwnd → 원래 확장 스타일.
    #: 모든 워커가 같은 창 목록을 보므로 클래스에 둔다(`_restore_quietly` 가 정적 메서드라 인스턴스를 못 본다).
    _newborn_transparent: dict[int, int] = {}

    def _offscreen_window_args(self, user32: Any = None) -> list[str]:
        """크롬 창이 **어느 모니터에도 안 겹치는 자리에서** 태어나게 하는 인자.

        ## 왜 (2026-09-21, 사장님: 「콜드스타트하면 아직 번쩍인다」)

        창을 태어난 뒤에 숨기는 길(20ms 감시 → 이벤트 훅 → 폴링)은 전부 **반응 지연**만큼 보인다 — 이벤트 전달과 파이썬 GIL
        전환(5ms) 때문에 8~26ms. 숨긴 창의 hwnd 와 번쩍인 창의 hwnd 가 **같음**을 대조로 확인했다: 잡긴 잡는데 늦는다.
        지연이 0 이 아닌 한 반응으로는 0 에 못 간다. 그래서 **애초에 화면 위에 없는 자리에서** 태어나게 한다.

        크롬은 `--window-position` 의 화면 밖 좌표를 그대로 받는다(실측: (2220,0)·(-20000,-20000) 둘 다 그 자리에 생김).
        이 인자는 자동화 탐지 신호가 아니다(이 코드가 피하는 건 `--disable-*` 류).
        다 뜨면 `_send_window_to_back` 이 모니터 밖 창을 사람이 보는 화면의 작업 영역으로 데려온다(`_usable_window_rect`).
        """
        if sys.platform != "win32" or not bool(getattr(self.config, "browser_birth_offscreen", True)):
            return []
        try:
            if user32 is None:
                import ctypes

                user32 = ctypes.windll.user32
            left = int(user32.GetSystemMetrics(76))    # SM_XVIRTUALSCREEN
            top = int(user32.GetSystemMetrics(77))     # SM_YVIRTUALSCREEN
            width = int(user32.GetSystemMetrics(78))   # SM_CXVIRTUALSCREEN
        except Exception:  # noqa: BLE001 — 못 재면 예전처럼(태어난 뒤에 숨기는 길만)
            return []
        return [f"--window-position={left + width + 200},{top}"]

    def _start_birth_guard(self) -> bool:
        """크롬을 띄우기 **전에** 세운다. 창이 태어난 뒤에 세우면 이미 늦다.

        ## 왜 (2026-09-21, 사장님: 「콜드스타트하면 아직 번쩍인다」)

        운영 콜드스타트를 밖에서 관찰했더니 창은 비최소화·전체 화면으로 **태어나** ~16ms 동안 다른 창 위에 보인 뒤에야
        20ms 감시 스레드가 최소화했다. 크롬은 자기를 다시 띄워서 `wShowWindow=SW_SHOWMINNOACTIVE` 가 첫 창까지 안 간다.
        폴링은 주기만큼 틈이 남는다 — **창 표시 이벤트**(`SetWinEventHook`)로 받는 즉시 알파 0 으로 만든다.
        뜨는 동안의 앞창 다툼(최소화·복원 수십 번)도 투명한 채 일어난다.
        """
        if sys.platform != "win32" or not bool(getattr(self.config, "browser_birth_guard", True)):
            return False
        try:
            import ctypes

            # 백엔드가 죽어도 크롬은 산다 — 지난번 가드가 못 돌려놓은 투명한 창이 있으면 먼저 청소한다.
            self._sweep_stuck_transparent(ctypes.windll.user32)
        except Exception:  # noqa: BLE001
            pass
        self._birth_guard_stop.clear()
        ready = threading.Event()
        threading.Thread(target=self._birth_guard, args=(ready,), daemon=True, name="chrome-birth-guard").start()
        ready.wait(1.0)  # 훅이 서기 전에 크롬을 띄우면 소용없다
        return True

    def _newborn_should_hide(self, user32: Any, hwnd: int, pid_cache: dict[int, bool]) -> bool:
        """이 창이 **우리가 방금 띄운 크롬의 주 창**인가. 아니면 손대지 않는다."""
        import ctypes

        if hwnd in BrowserWorker._newborn_transparent:
            return False
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "Chrome_WidgetWin_1":
            return False
        # 제목 표시줄이 있는 주 창만. 말풍선·메뉴·툴팁은 WS_POPUP 이라 건드리지 않는다.
        if (int(user32.GetWindowLongW(hwnd, -16)) & 0xC00000) != 0xC00000:  # GWL_STYLE · WS_CAPTION
            return False
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        number = int(pid.value)
        answer = pid_cache.get(number)
        if answer is None:
            # 띄우기 전에 있던 pid 는 사람의 크롬이다. Electron 앱도 같은 클래스를 쓰니 이름도 본다.
            answer = number not in self._chrome_pids_before_launch and self._process_name(number).lower() == self._exe_name
            pid_cache[number] = answer
        return answer

    def _make_newborn_transparent(self, user32: Any, hwnd: int) -> None:
        ex_style = int(user32.GetWindowLongW(hwnd, -20))  # GWL_EXSTYLE
        if not ex_style & 0x80000:  # WS_EX_LAYERED
            user32.SetWindowLongW(hwnd, -20, ex_style | 0x80000)
        user32.SetLayeredWindowAttributes(hwnd, 0, 0, 2)  # 알파 0
        BrowserWorker._newborn_transparent[hwnd] = ex_style

    def _reassert_transparent(self, user32: Any, hwnd: int, stats: dict[str, Any] | None = None) -> bool:
        """숨겨 둔 창이 다시 보이게 돌아갔으면(레이어드가 벗겨졌거나 알파가 올라감) 다시 투명하게 한다."""
        import ctypes
        import ctypes.wintypes as wt

        key, alpha, flags = wt.DWORD(0), ctypes.c_ubyte(0), wt.DWORD(0)
        ex_style = int(user32.GetWindowLongW(hwnd, -20))
        still_hidden = bool(ex_style & 0x80000) and bool(
            user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags))
        ) and (int(flags.value) & 0x2) and int(alpha.value) == 0
        if still_hidden:
            return False
        if not ex_style & 0x80000:
            user32.SetWindowLongW(hwnd, -20, ex_style | 0x80000)
        user32.SetLayeredWindowAttributes(hwnd, 0, 0, 2)
        if stats is not None:
            stats["reasserted"] = int(stats.get("reasserted", 0)) + 1
        return True

    def _finish_newborn_windows(self, user32: Any) -> None:
        """투명하게 만든 창을 **전부** 불투명으로 돌린다. 안 보이는 크롬은 사고다."""
        for hwnd, ex_style in list(BrowserWorker._newborn_transparent.items()):
            try:
                if user32.IsWindow(hwnd):
                    user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
                    if not ex_style & 0x80000:
                        user32.SetWindowLongW(hwnd, -20, ex_style)
            except Exception:  # noqa: BLE001 — 한 창이 실패해도 나머지는 돌려놓는다
                pass
            BrowserWorker._newborn_transparent.pop(hwnd, None)

    def _sweep_stuck_transparent(self, user32: Any) -> int:
        """우리 크롬 창 중 **알파 0 인 채 남은 것**을 불투명으로 돌린다(지난 백엔드가 죽으며 남긴 것)."""
        import ctypes
        import ctypes.wintypes as wt

        fixed = 0
        for hwnd in self._our_chrome_windows(include_iconic=True):
            key, alpha, flags = wt.DWORD(0), ctypes.c_ubyte(0), wt.DWORD(0)
            if not int(user32.GetWindowLongW(hwnd, -20)) & 0x80000:
                continue
            if user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags)) \
                    and (int(flags.value) & 0x2) and int(alpha.value) == 0:
                user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
                fixed += 1
        return fixed

    def _birth_guard(self, ready: threading.Event) -> None:
        """뜨는 동안 새 크롬 주 창을 **표시 이벤트로** 받아 즉시 투명하게 만들고, 다 뜨면 불투명으로 돌린다."""
        import ctypes
        import ctypes.wintypes as wt

        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)
        pid_cache: dict[int, bool] = {}
        hook = None
        began = time.time()
        # 진단 — 이게 없으면 「가드가 안 잡았다」를 짐작으로만 안다(2026-09-21, 폴백 경로 5/6 번쩍임).
        stats: dict[str, Any] = {"hook": False, "events": 0, "candidates": 0, "hidden": 0, "errors": 0,
                                 "first_hidden_ms": None, "first_event": None, "reasserted": 0, "hidden_hwnds": [], "last_error": ""}
        self._sink_report["birth_guard"] = stats

        def on_event(_hook, _event, hwnd, id_object, _id_child, _thread, _time):  # type: ignore[no-untyped-def]
            stats["events"] += 1
            if id_object != 0 or not hwnd:  # OBJID_WINDOW
                return
            handle = int(hwnd)
            try:
                if handle in BrowserWorker._newborn_transparent:
                    # ★ 이미 숨긴 창이 **다시 보이게 되돌려졌는지** 본다. 크롬은 창을 보일 때 스스로 레이어드 속성을 만지므로
                    #   (폴백 경로 6/8 번쩍임: 알파 0 을 걸었는데 눈금엔 255) 표시·위치·순서 이벤트마다 확인해 다시 건다.
                    self._reassert_transparent(user32, handle, stats)
                    return
                if int(_event) not in (0x8000, 0x8002):  # CREATE · SHOW 에서만 새 창을 고른다
                    return
                if self._newborn_should_hide(user32, handle, pid_cache):
                    stats["candidates"] += 1
                    self._make_newborn_transparent(user32, handle)
                    stats["hidden"] += 1
                    stats["hidden_hwnds"].append(handle)
                    if stats["first_hidden_ms"] is None:
                        stats["first_hidden_ms"] = round((time.time() - began) * 1000)
                        stats["first_event"] = hex(int(_event))
            except Exception as error:  # noqa: BLE001 — 가드 하나 때문에 브라우저 기동을 깨지 않는다
                stats["errors"] += 1
                stats["last_error"] = f"{type(error).__name__}: {error}"[:120]

        callback = callback_type(on_event)  # 참조를 쥐고 있어야 한다 — 놓으면 콜백이 가비지가 된다
        try:
            user32.SetWinEventHook.restype = wt.HANDLE
            user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, callback_type,
                                               wt.DWORD, wt.DWORD, wt.DWORD]
            # 0x8000 CREATE ~ 0x800B LOCATIONCHANGE · WINEVENT_OUTOFCONTEXT(0) — 이 스레드가 메시지를 돌려야 콜백이 온다
            hook = user32.SetWinEventHook(0x8000, 0x800B, None, callback, 0, 0, 0)
            stats["hook"] = bool(hook)
            ready.set()
            message = wt.MSG()
            started = time.time()
            settled_at: float | None = None
            while not self._birth_guard_stop.is_set() and time.time() - started < 25.0:
                while user32.PeekMessageW(ctypes.byref(message), 0, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
                # ★ 숨긴 창의 알파를 **매 반복 확인**한다(~1ms). 크롬이 창을 보일 때 스스로 레이어드 속성을 되돌리는데
                #   그건 창 이벤트를 내지 않아서, 이벤트만 기다리면 되돌려진 채 보인다(폴백 경로 7/8 번쩍임, 재적용 0회).
                for hidden_hwnd in list(BrowserWorker._newborn_transparent):
                    try:
                        self._reassert_transparent(user32, hidden_hwnd, stats)
                    except Exception:  # noqa: BLE001
                        pass
                # 다 떴다(`settled`)고 알린 뒤 조금 더 — 마지막 앞창 다툼이 끝날 때까지 — 두었다가 돌린다.
                if self._sink_settled.is_set():
                    settled_at = settled_at or time.time()
                    if time.time() - settled_at > 1.0:
                        break
                elif time.time() > self._launch_watch_until + 8.0:
                    break
                time.sleep(0.001)
        except Exception:  # noqa: BLE001
            pass
        finally:
            ready.set()
            try:
                if hook:
                    user32.UnhookWinEvent(hook)
            except Exception:  # noqa: BLE001
                pass
            # ★ 어떤 이유로 끝나든 창을 불투명으로 돌려놓는다 — 이게 이 가드의 안전장치다.
            self._finish_newborn_windows(user32)

    @staticmethod
    def _restore_quietly(user32: Any, hwnd: int) -> None:
        """최소화된 창을 **화면 위에서 한 프레임도 안 보이게** 되살려 맨 뒤에 둔다.

        ## 왜 (2026-09-21, 사장님: 「전용 크롬이 떠 있으면 안 번쩍이는데 콜드스타트에서 번쩍인다」)

        예전 순서는 `SetWindowPos(맨 뒤)` → `ShowWindow(SW_SHOWNOACTIVATE)` → `SetWindowPos(맨 뒤)` 였다.
        첫 줄이 「복원 전에 내려 틈을 없앤다」는 뜻이었지만 **최소화된 창은 z 순서 자리가 없어서** 소용이 없었고,
        `ShowWindow` 가 창을 **맨 위**에 세운 뒤 다음 줄이 내리기까지 10~37ms 동안 다른 창 위에
        그려졌다. 측정(`measure_chrome_flash.py`, 콜드스타트 8/8, 이벤트 단계 전부 `_restore_sunk_windows`)이다.
        이전 인수인계의 「되살린 2.4초 뒤에 번쩍」은 **시계가 어긋난 해석**이었다 — `restored_at` 은 감시
        스레드 시작 기준이고 번쩍임 시각은 측정 시작 기준이라, 같은 순간이 다른 숫자로 보였다.

        ## 어떻게 — 되살리는 동안만 **투명**하게 둔다

        `WS_EX_LAYERED` + 알파 0 으로 만든 뒤 되살리고 맨 뒤로 보내고, 다시 불투명으로 돌린다.
        맨 위에 잠깐 서도 **투명해서 안 보인다.** 창의 위치·크기·z 순서 규칙은 하나도 안 바꾼다.

        ## 해 봤는데 안 된 것 (다시 시도하지 말 것)

        - **화면 밖에서 되살리기** (`SetWindowPlacement` 로 보통 자리를 모든 모니터 바깥에): 윈도우가
          자리를 **가장 가까운 모니터 안으로 끌어온다**(요청 x=2120 → 실제 [1120,1920]). 그대로 번쩍였다.
          `restore_path=quiet` 인데도 콜드스타트 7/8 이 번쩍여서 알았다.
        - **DWM 클로킹** (`DWMWA_CLOAK`): 남의 프로세스 창에는 `E_ACCESSDENIED(0x80070005)`.

        투명하게 못 만들면(크롬이 레이어드를 거부하면) 예전 길로 돌아간다 — 창 하나 때문에 일이 죽으면 안 된다.
        어느 길을 탔는지는 `_last_restore_path` 에 남는다.
        """
        try:
            ex_style = int(user32.GetWindowLongW(hwnd, -20))  # GWL_EXSTYLE
            was_layered = bool(ex_style & 0x80000)  # WS_EX_LAYERED
            if not was_layered:
                user32.SetWindowLongW(hwnd, -20, ex_style | 0x80000)
            if not user32.SetLayeredWindowAttributes(hwnd, 0, 0, 2):  # 알파 0 (LWA_ALPHA)
                if not was_layered:
                    user32.SetWindowLongW(hwnd, -20, ex_style)
                raise OSError("SetLayeredWindowAttributes")
            try:
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE — 맨 위에 서지만 투명하다
                # ★ 주차 중이면 **투명한 채로 먼저 화면 밖으로** 옮긴다(2026-09-24 노트북 「한 번 반짝」). 불투명으로 돌린 뒤에
                #   옮기면, 최소화로 태어난 창이 되살아난 자리(크롬이 화면 안으로 끌어온 자리)에서 한 프레임 보인다.
                if not (BrowserWorker._park_offscreen and BrowserWorker._park_window_offscreen(user32, hwnd)):
                    # HWND_BOTTOM=1, SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE=0x13
                    user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0013)
            finally:
                # ★ 뜨는 동안 출생 가드가 투명하게 만든 창은 여기서 불투명으로 돌리지 **않는다.** 되살림이 앞창 다툼으로
                #   수십 번 불리는데 그때마다 보이면 소용돌이가 그대로 보인다 — 다 뜬 뒤 가드가 한 번에 돌린다.
                if hwnd not in BrowserWorker._newborn_transparent:
                    user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
                    if not was_layered:
                        user32.SetWindowLongW(hwnd, -20, ex_style)
            BrowserWorker._last_restore_path = "transparent"
            return
        except Exception as error:  # noqa: BLE001 — 투명하게 못 하면 예전 길로
            # 어느 길을 탔는지 남긴다 — 폴백이 조용히 옛 번쩍임을 되살리면 눈금은 「안 고쳐졌다」만 말한다.
            BrowserWorker._last_restore_path = f"fallback:{type(error).__name__}:{error}"[:120]
        # HWND_BOTTOM=1, SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE=0x13.
        user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0013)
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE

    @classmethod
    def _give_focus_back(cls, user32: Any, hwnd: int, keep: int) -> None:
        """우리 크롬이 **앞창(포커스)을 쥐었다** — 돌려주고, 창은 보이는 채로 맨 뒤에 둔다.

        ★ 2026-09-16 실측: 맨 뒤로 보내기(`_send_window_to_back`)만으로는 포커스가 안 돌아온다.
          `SetWindowPos` 는 z 순서만 바꾸고 활성 창은 그대로 두며, 우리 프로세스의
          `SetForegroundWindow(keep)` 는 윈도우의 앞창 잠금에 막힌다. 그래서 크롬이 앞을
          0.2~1.0초 쥐었다(off·psutil 9판 중 7판 — 최소화하던 예전 판은 0.0 ×9).
          최소화는 **윈도우가 직접** 활성을 다음 창에 넘긴다 — 그 한 가지만 빌려 쓰고, 곧바로
          활성화 없이 되살려 맨 뒤로 보낸다(보이는 창이어야 탭이 그림을 만든다).
        """
        user32.ShowWindow(hwnd, 7)  # SW_SHOWMINNOACTIVE — 활성을 윈도우가 넘긴다
        # 활성화 없이 되살린다 — **화면 위에 안 그려지게**(`_restore_quietly`, 콜드스타트 번쩍임).
        cls._restore_quietly(user32, hwnd)
        cls._send_window_to_back(user32, hwnd)
        if keep and keep != hwnd:
            user32.SetForegroundWindow(keep)

    #: 절대 건드리지 않는 창. 작업표시줄·바탕화면은 창처럼 보이지만 사람의 PC 그 자체다.
    #: (2026-09-16 사고: 보조 모니터 작업표시줄을 최소화해 클릭이 안 먹게 만들었다.)
    _SHELL_WINDOW_CLASSES = frozenset({
        "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW",
        "NotifyIconOverflowWindow", "Windows.UI.Core.CoreWindow", "TaskListThumbnailWnd",
    })

    @staticmethod
    def _window_class(hwnd: int) -> str:
        if sys.platform != "win32":
            return ""
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, buffer, 256)
            return buffer.value
        except Exception:  # noqa: BLE001
            return ""

    def _window_is_ours(self, hwnd: int, pid: int) -> bool:
        """이 창을 우리가 내려도 되나. **두 겹으로 막는다.**

        첫째 그물은 프로세스 이름(`_is_our_chrome_pid` 안). 둘째 그물이 이것이다 — 셸 창은
        이름 검사를 통과할 일이 없지만, 한 겹이 빠졌다는 사실 자체가 이번 사고였다. 사람의
        작업표시줄을 내리는 것과 크롬 창을 내리는 것은 되돌리는 값이 다르다.
        """
        if self._window_class(hwnd) in self._SHELL_WINDOW_CLASSES:
            return False
        return self._is_our_chrome_pid(pid)

    def _our_chrome_windows(self, *, include_iconic: bool = False) -> list[int]:
        """우리가 띄운 크롬의 **보이는 최상위 창**들. 사람의 크롬은 들어오지 않는다.

        앞창 하나만 보면 창이 앞을 쥔 뒤에야 알게 된다. 창 목록을 직접 훑으면 **나타나는
        순간** 잡을 수 있다 — 그 차이가 0.6초와 0 초의 차이다.
        """
        if sys.platform != "win32":
            return []
        found: list[int] = []
        try:
            import ctypes

            user32 = ctypes.windll.user32
            enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def visit(hwnd, _param):  # type: ignore[no-untyped-def]
                if not user32.IsWindowVisible(hwnd) or (user32.IsIconic(hwnd) and not include_iconic):
                    return True
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                # 이름으로 먼저 걸러야 한다. 아니면 크롬이 아닌 창마다 프로세스 조회를 한다.
                if self._process_name(int(pid.value)).lower() != self._exe_name:
                    return True
                if self._window_is_ours(hwnd, int(pid.value)):
                    found.append(hwnd)
                return True

            user32.EnumWindows(enum_proc(visit), None)
        except Exception:  # noqa: BLE001
            return found
        return found

    @staticmethod
    def _process_name(pid: int) -> str:
        """pid 의 exe 이름. 프로세스를 띄우지 않고 읽는다(감시 스레드가 0.02초마다 쓴다)."""
        if sys.platform != "win32" or pid <= 0:
            return ""
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return ""
            try:
                size = ctypes.c_ulong(260)
                buffer = ctypes.create_unicode_buffer(260)
                if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    return ""
                return buffer.value.rsplit("\\", 1)[-1]
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return ""

    def _is_our_chrome_pid(self, pid: int) -> bool:
        """그 창이 **우리가 띄운 크롬**의 것인가. 사람의 크롬은 건드리지 않는다.

        ★ 답을 적어 둔다. 창이 나타나는 순간을 잡으려면 0.02초마다 물어야 하는데, 이 판단은
          `wmic` 프로세스를 띄운다 — 캐시가 없으면 감시 스레드가 초당 50번 프로세스를 만든다.
          pid 는 그 프로세스가 사는 동안 안 바뀌니 한 번 물으면 된다.
        """
        proc = self._chrome_proc
        if pid <= 0:
            return False
        # ★★ 2026-09-16, 제품 사고. 이 판단이 아래 「새로 생긴 pid → 우리 것」 지름길을 타면서
        #    **프로세스 이름을 한 번도 안 봤다.** 그래서 감시 스레드가 사용자의 카카오톡 창과
        #    **보조 모니터 작업표시줄(explorer 의 `Shell_SecondaryTrayWnd`)을 최소화했다.**
        #    작업표시줄을 눌러도 창이 안 뜨는 상태가 됐다(실측으로 `iconic=True` 확인).
        #
        #    그래서 이름 검사를 **이 함수 첫 줄에** 둔다. 부르는 자리마다 붙이면 또 한 곳이
        #    빠진다 — 그것이 바로 이번 사고의 모양이었다(`_our_chrome_windows` 는 이름을
        #    봤고, 앞창을 보는 자리는 안 봤다).
        if self._process_name(pid).lower() != self._exe_name:
            return False
        # ★ Playwright 가 띄운 길(`_launch_chrome`)에는 `_chrome_proc` 이 **없다**. 예전 판은
        #   여기서 곧바로 False 를 답해, 그 길에서는 감시 스레드가 아무 창도 못 알아봤다.
        #   손잡이가 없어도 우리 것인지 알 방법은 있다 — 명령줄의 프로필이다
        #   (`_kill_profile_chromes` 가 쓰는 것과 같은 규칙).
        if proc is not None and pid == proc.pid:
            return True
        # ★ 띄운 직후 몇 초는 **새로 생긴 pid** 로 가른다. 프로세스 목록을 다시 읽지 않으니
        #   창이 나타나는 순간 답할 수 있다. 그 창을 뺏기는 것은 이 몇 백 ms 에서 갈렸다.
        #   대가: 그 12초 안에 사람이 자기 크롬을 새로 띄우면 그 창도 한 번 내려간다.
        #   되돌림은 작업 표시줄에서 한 번 누르는 것이고, 반대쪽 손해(치던 글자를 뺏김)가 더 크다.
        if time.time() < self._launch_watch_until:
            # 띄운 직후 몇 초는 **프로세스 목록을 다시 읽지 않는다.** 답은 두 가지로 충분하다:
            #   · 띄우기 전에 없던 pid → 우리가 띄운 것
            #   · 있던 pid → 사람의 크롬
            # ★ 다시 읽으면 안 되는 이유가 실측으로 나왔다. psutil 이 없는 포장본에서 스캔이
            #   401ms 인데, 감시 스레드가 **사람의 크롬 창**을 판단하려고 1초마다 그것에 갇혀
            #   굶었다. 0.0초였던 것이 2.0~3.8초로 나빠졌다(n=3).
            if pid not in self._chrome_pids_before_launch:
                return True
            return bool(self._chrome_pid_answers.get(pid, False))
        cached = self._chrome_pid_answers.get(pid)
        if cached is not None:
            return cached
        # 크롬은 자기를 다시 띄운다 — 자식·손자도 우리 것이다. 명령줄의 프로필로 가린다.
        answer = self._chrome_cmdline_has_our_profile(pid)
        if len(self._chrome_pid_answers) > 500:
            self._chrome_pid_answers.clear()
        self._chrome_pid_answers[pid] = answer
        return answer

    def _chrome_cmdline_has_our_profile(self, pid: int) -> bool:
        """그 pid 의 명령줄에 우리 프로필이 있나.

        ★ 2026-09-16 실측: 이 판단이 `wmic` 이었고, **이 PC(Windows 11 26200)에 wmic 이 없다.**
          호출이 `FileNotFoundError` 로 죽고 우리는 그것을 False 로 삼켰다 — 그래서 크롬의
          **손자 창**(크롬이 자기를 다시 띄운 것)을 한 번도 우리 것으로 알아보지 못했다.
          어제 「한 번도 안 뺏김」이 나온 것은 첫 창이 `_chrome_proc.pid` 로 직접 맞아서였다.
          없는 도구에 기댄 검사는 조용히 「아니다」라고 답한다(같은 가족: 사고 S).

        `psutil` 이 먼저다(프로세스를 안 띄운다, 실측 27개 10ms). 없으면 파워셸 한 번.
        """
        profile = str(self._profile_dir)
        return profile in self._chrome_scan().get(pid, "")

    def _kill_profile_chromes(self) -> int:
        """우리 프로필을 쓰는 크롬을 전부 죽인다. 죽인 개수를 돌려준다.

        **명령줄로 찾는다.** 이름(`chrome.exe`)으로 고르면 사용자가 보고 있는 크롬까지
        같이 죽는다 — 우리 것은 `--user-data-dir` 이 우리 프로필인 것뿐이다.

        (윈도우 전용. 다른 OS 에서는 0 을 돌려주고 아무것도 안 한다.)
        """
        if sys.platform != "win32":
            return 0
        profile = str(self._profile_dir)
        script = (
            f"Get-CimInstance Win32_Process -Filter \"Name='{self._exe_name}'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{profile}*' }} | "
            "ForEach-Object { $_.ProcessId }"
        )
        try:
            found = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            return 0
        pids = [line.strip() for line in (found.stdout or "").splitlines() if line.strip().isdigit()]
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", pid],
                    capture_output=True, timeout=15,
                )
            except Exception:
                continue
        if pids:
            # 포트가 풀리는 데 잠깐 걸린다. 바로 다시 붙으면 아직 잡고 있는 것을 본다.
            time.sleep(1.5)
        return len(pids)

    @staticmethod
    def _kill_chrome_process(process: Any) -> None:
        if process is None:
            return
        try:
            if process.poll() is not None:
                return
            if sys.platform == "win32":
                # 크롬은 자식이 여럿이라 부모만 죽이면 창이 남는다.
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    timeout=15,
                )
            else:
                process.terminate()
        except Exception:
            pass

    def _apply_download_dir(self, page: Any) -> None:
        session = None
        try:
            session = self._context.new_cdp_session(page)
            session.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(self.config.browser_download_dir),
                },
            )
        except Exception:
            pass
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass

    @staticmethod
    def _read_automation_flag(page: Any) -> bool | None:
        """이 크롬이 자동화 모드로 떠 있는가. 감추려는 게 아니라 **알고 있으려는** 것이다.

        막히는 곳에서 "왜 막혔나"를 짐작하지 않기 위해 한 번 재서 `status()` 에 둔다.
        """
        try:
            return bool(page.evaluate("() => navigator.webdriver === true"))
        except Exception:
            return None

    def _watch_page(self, page: Any) -> None:
        """창마다 거는 감시 둘 — 확인창, 그리고 페이지가 받아 온 JSON 응답(읽기만)."""
        self._watch_network(page)
        self._watch_dialogs(page)

    #: 창마다 최근 JSON 응답 몇 개를 들고 있나. 오래된 것은 밀려난다.
    _NETWORK_KEEP = 40

    def _watch_network(self, page: Any) -> None:
        """페이지가 **스스로 받은** XHR/fetch JSON 응답을 붙들어 둔다(본문은 도구가 물을 때만 읽는다).

        우리는 요청을 보내지 않는다 — 이미 오간 응답의 손잡이만 적어 둔다(page_data.py 의 선).
        """
        try:
            from collections import deque

            buffers = self.__dict__.setdefault("_network_buffers", {})
            if id(page) in buffers:
                return
            buffer: Any = deque(maxlen=self._NETWORK_KEEP)
            key = id(page)
            buffers[key] = buffer

            def on_close(*_args: Any) -> None:
                # ★ 닫힌 탭의 기록은 버린다 (2026-10-14). 응답 하나가 자기 탭과 **연결 전체**를 붙든다 — 이 칸을 안 비워서
                #   연결을 갈아 끼워도 옛 연결(장부 4,453개)이 통째로 남았고, 밤새 탭을 열고 닫을수록 쌓였다(손잡이 12만 개).
                #   지우지 않으면 같은 `id` 를 다시 받은 새 탭이 「이미 감시 중」으로 읽혀 감시가 빠지기도 한다.
                if buffers.get(key) is buffer:
                    buffers.pop(key, None)

            page.on("close", on_close)

            def on_response(response: Any) -> None:
                try:
                    if response.request.resource_type not in ("xhr", "fetch"):
                        return
                    if "json" not in str((response.headers or {}).get("content-type") or "").lower():
                        return
                    # ★ 응답은 **머리줄만 온 때** 여기로 온다 — 본문은 아직 오는 중일 수 있다(2026-10-07 폼 벤치 F: 끝나지 않는
                    #   응답의 본문을 읽으려다 도구가 멈췄고, 브라우저가 60초 넘게 묶여 뒤의 누르기까지 전부 「물려 있다」로 돌아왔다).
                    #   실시간 알림·긴 폴링처럼 끝나지 않는 응답은 흔하다. 다 받았다는 신호(`requestfinished`)가 온 것만 읽게 표시해 둔다.
                    buffer.append({"response": response, "request": response.request, "url": str(response.url),
                                   "status": int(response.status), "done": False})
                except Exception:
                    pass

            def on_finished(request: Any) -> None:
                for item in list(buffer):
                    if item.get("request") is request:
                        item["done"] = True

            page.on("response", on_response)
            page.on("requestfinished", on_finished)
        except Exception:
            pass

    def _site_sources(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """피드·공식 링크(페이지에서) + robots.txt(한 번 짧게). 못 읽은 것은 모른다고 적는다."""
        del arguments
        page_url = str(getattr(page, "url", "") or "")
        try:
            found = dict(page.evaluate(_SITE_SOURCES_JS) or {})
        except Exception:
            found = {}
        result: dict[str, Any] = {"feeds": found.get("feeds") or [], "official": found.get("official") or [],
                                  "sitemaps": [], "path_allowed": None, "robots": "unknown"}
        robots = _site_sources.robots_url(page_url)
        if robots:
            try:
                response = page.context.request.get(robots, timeout=5000, max_redirects=3)
                if response.ok:
                    verdict = _site_sources.robots_verdict(response.text()[:200_000], page_url)
                    result.update(verdict, robots="read")
                else:
                    result["robots"] = f"http_{response.status}"
            except Exception as exc:
                result["robots"] = f"unreadable:{type(exc).__name__}"
        return self._evidence("site_sources", **result, instruction=_site_sources.note_for(result))

    def _page_data(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """페이지가 이미 받아 온 같은 사이트 JSON 응답에서 **찾는 값**을 추린다(query 없으면 모양만)."""
        query = _clean(arguments.get("query"), 200)
        buffer = (self.__dict__.get("_network_buffers") or {}).get(id(page)) or []
        captured: list[dict[str, Any]] = []
        page_url = str(getattr(page, "url", "") or "")
        for item in reversed(list(buffer)):
            if item.get("done") is False:      # 아직 오는 중인 응답 — 본문을 읽으면 끝날 때까지 매달린다
                continue
            if not _page_data.same_site(page_url, item["url"]):
                continue
            try:
                body = item["response"].body()
                if len(body) > _page_data.MAX_BODY_BYTES:
                    continue
                parsed = json.loads(body.decode("utf-8", errors="replace"))
            except Exception:
                continue
            captured.append({"url": item["url"], "status": item["status"], "json": parsed})
            if len(captured) >= 15:
                break
        summary = _page_data.summarize_responses(page_url, captured, query)
        if not summary["responses"]:
            note = ("이 페이지가 받아 온 같은 사이트 JSON 에 " + (f"'{query}' 가 든 값이 없다." if query else "읽을 응답이 없다.")
                    + " 화면을 새로 그린 뒤(스크롤·검색) 다시 부르거나 browser_extract 로 본문을 읽어라.")
        else:
            note = ("[도구가 보낸 안내] 페이지가 화면을 그리려고 **이미 받아 온** 데이터다 — 새로 요청하지 않았다. "
                    "민감한 칸은 [숨김]. 값을 답에 쓸 때는 화면에 보이는 값과 맞는지 확인하라.")
        return self._evidence("page_data", query=query, **summary, instruction=note)

    def _settle_human_dialog(self) -> None:
        """사람에게 남겨 둔 「나가시겠습니까?」 창이 아직 떠 있으면 **취소로** 닫는다 — 우리 일이 시작되는 자리에서.

        답 안 한 확인창이 떠 있는 탭은 멈춰 있다. 그대로 일을 시작하면 그 탭을 건드리는 호출이 시간 초과까지 매달린다.
        취소는 사람의 입력을 지키는 쪽이다(탭이 남는다). 사람이 이미 답했으면 닫을 것이 없어 조용히 지나간다.
        """
        dialog = getattr(self, "_human_dialog", None)
        if dialog is None:
            return
        self._human_dialog = None
        try:
            dialog.dismiss()
        except Exception:  # noqa: BLE001 — 사람이 이미 답했거나 탭이 닫혔다
            pass

    def _watch_dialogs(self, page: Any) -> None:
        """확인창에 **그 자리에서** 답하고, 무엇을 물었는지 남긴다.

        붙잡아 두는 설계를 먼저 만들었다가 실브라우저에서 멈췄다: 확인창이 뜬 동안
        클릭 호출이 끝나지 않고, 브라우저 작업은 한 스레드에서 직렬로 돌기 때문에
        그 창에 답할 명령조차 실행될 수 없다. 스스로 만든 교착이었다.

        그래서 정책은 **미리** 정한다(`browser_handle_dialog`). 기본은 취소 —
        페이지 안 모달에 거는 잣대와 같다. '확인'은 사람이 문구를 보고 정할 일이므로
        한 번 쓰고 사라지는 일회용 허가로만 열린다.

        Playwright 의 기본값(리스너 없으면 자동 dismiss)과 결과는 같아 보여도 다르다:
        무엇을 물었는지가 남는다. 되돌릴 수 없는 동작 앞의 침묵이 가장 나쁘다.
        """
        def on_dialog(dialog: Any) -> None:
            message = ""
            kind = ""
            try:
                message = str(dialog.message or "")
                kind = str(dialog.type or "")
            except Exception:
                pass
            # ★ 2026-09-26 브라우저 무대: 사람이 넘겨받은 동안 뜬 알림창은 **사람의 것**이다 — 여기서 취소를 누르면 사람은 보지도
            #   못하고 「정말 삭제?」가 취소된다. 답하지 않고 두면 무대가 대신 그려 사람이 답한다(`LiveView.answer_dialog`).
            view = getattr(self, "live_view", None)
            if view is not None and view.human_in_control():
                self._last_dialog = {"message": _clean(message, 400), "type": kind, "accepted": None,
                                     "left_to_human": True, "at": time.time()}
                return
            # ★ **우리가 일하지 않는 동안** 뜬 「나가시겠습니까?」는 사람이 그 탭을 닫거나 떠나려는 것이다 (2026-10-07 대표 실사용).
            #   채용 사이트의 이력서 수정 탭의 X 를 눌러도 닫히지 않았다 — 쉬는 동안에도 도는 펌프가 이 창을 받아 기본값(취소)으로
            #   닫아 버렸기 때문이다. 사람은 창을 보지도 못하고 「닫기가 안 된다」만 겪는다. 재현: 자동 취소 = 탭 그대로,
            #   답하지 않고 두면 사람이 「나가기」를 누르는 순간 닫힌다. 우리 동작 중이어도 **우리가 보던 탭이 아니면** 사람의 것이다.
            if kind == "beforeunload" and (
                int(getattr(self, "_action_depth", 0) or 0) <= 0 or page is not getattr(self, "_page", page)
            ):
                self._human_dialog = dialog
                self._last_dialog = {"message": _clean(message, 400), "type": kind, "accepted": None,
                                     "left_to_human": True, "at": time.time()}
                return
            decision = self._dialog_policy
            self._dialog_policy = None  # 일회용
            # ★ **이 PC 안 페이지**의 확인창은 따로 정하지 않았으면 확인으로 답한다 (2026-10-04 대표 결정, 도구 전수조사 11번).
            #   기본이 취소라, 자기가 만든 페이지의 「삭제」 버튼(`confirm("삭제할까요?")`)은 눌러도 아무 일이 안 일어났다 —
            #   모델은 자기 코드가 틀린 줄 알고 멀쩡한 코드를 계속 고쳤다. 누르기는 09-30 부터 이 PC 안 페이지에서 승인 없이
            #   눌린다(`_is_local_page`) — 결정은 그 누르기에서 이미 났고, 확인창만 거꾸로 답하고 있었다. 같은 잣대(주소의 사실)다.
            #   밖의 사이트는 그대로다: 기본 취소, 허가를 둬도 「정말 삭제?」·결제는 취소.
            #   모델이 취소를 원하면 누르기 전에 browser_handle_dialog(accept=false) 로 정해 둔다 — 그 말이 먼저다.
            on_local = _is_local_page(page)
            auto_local = decision is None and on_local
            accept = bool(decision.get("accept")) if decision else on_local
            if accept and not on_local and _IRREVERSIBLE_ACTION.search(message):
                # 읽기 전용을 꺼도 이건 취소한다. "정말 삭제하시겠습니까?"에 자동으로
                # '확인'을 누르는 길은 어떤 모드에서도 열지 않는다 — 클릭과 같은 잣대다.
                accept = False
                blocked = True
            else:
                blocked = False
            try:
                if accept:
                    dialog.accept(str((decision or {}).get("prompt_text") or ""))
                else:
                    dialog.dismiss()
            except Exception:
                pass
            self._last_dialog = {
                "message": _clean(message, 400),
                "type": kind,
                "accepted": accept,
                "blocked_by_read_only": blocked,
                "auto_accepted_local": bool(auto_local and accept),
                "at": time.time(),
            }

        try:
            page.on("dialog", on_dialog)
        except Exception:
            pass

    def _shutdown(self, *, keep_chrome: bool = False) -> None:
        """연결을 내려놓는다. `keep_chrome` 이면 우리가 띄운 크롬도 끄지 않는다 — 연결만 갈아 끼울 때 쓴다."""
        self._pump_stop.set()
        context, playwright = self._context, self._playwright
        mode, process = self._connect_mode, self._chrome_proc
        # 탭마다 붙들어 둔 응답 기록도 내려놓는다 — 남기면 그 응답이 옛 연결 전체를 붙든다. 새 연결에서 탭마다 다시 건다.
        self.__dict__.pop("_network_buffers", None)
        self._page = None
        self._context = None
        self._playwright = None
        self._chrome_proc = None
        self._connect_mode = ""
        self._automation_flag = None
        self._mark_disconnected()
        if context is not None and mode != "attached" and not keep_chrome:
            # ★ 붙기만 한 크롬은 **끄지 않는다.** 사람이 열어 둔 창이고, 자비스가
            # 재기동할 때마다 그 탭이 사라지면 안 된다. 우리가 띄운 것만 끈다.
            try:
                browser = context.browser if mode == "spawned" else None
                if browser is not None:
                    browser.close()
                else:
                    context.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        if mode == "spawned" and not keep_chrome:
            self._kill_chrome_process(process)

    def _mark_disconnected(self) -> None:
        with self._lock:
            self._connected = False

    def _context_alive(self) -> bool:
        """살아 있는지 **실제로 말을 걸어서** 확인한다. 플래그를 읽는 게 아니라.

        ★ 예전에는 `context.browser.is_connected()` 하나였는데, 그건 캐시된 값이다.
        Playwright 동기 API 는 프로토콜 호출이 오갈 때 딸려 오는 이벤트로 그 값을
        갱신하는데, 속성 읽기는 드라이버에 아무것도 안 보내므로 큐에 쌓인
        `disconnected` 가 영원히 처리되지 않는다. **정작 물어보는 그 순간에 반드시
        낡아 있는** 검사였다 — NAS 사고 H 의 `/api/tags`, 자비스 워치독의 생존
        검사와 정확히 같은 고장이다.

        실측(2026-08-09): 크롬을 죽인 뒤 이 검사는 "살아 있음"을 돌려줬고,
        `_current_page` 는 재기동을 건너뛰고 죽은 페이지를 넘겼다. 그 세션의 모든
        브라우저 도구가 끝까지 `Target page, context or browser has been closed`
        로 떨어졌다(대화 하나가 통째로 날아감).

        `cookies(url)` 을 쓰는 이유: 브라우저 프로세스와 한 번 왕복하되 **페이지는
        건드리지 않는다.** 렌더러가 멎어 있어도 브라우저가 살아 있으면 살아 있다고
        답해야 하고(그건 다시 띄울 일이 아니다), 주소를 주면 돌려주는 쿠키도 없다.
        """
        if self._context is None:
            self._mark_disconnected()
            return False
        alive = False
        try:
            browser = self._context.browser
            if browser is None or browser.is_connected():
                # 왕복 한 번. 브라우저가 없으면 여기서 예외가 난다.
                self._context.cookies("http://127.0.0.1/")
                alive = True
        except Exception:
            alive = False
        with self._lock:
            # `status()` 가 읽는 값이다. 여기서 갱신해 둬야 화면이 거짓말을 안 한다.
            self._connected = alive
        return alive

    def _current_page(self) -> Any:
        if self._reconnect_pending and self._connect_mode in ("attached", "spawned"):
            self._reconnect_attached()
        if not self._context_alive():
            self._shutdown()
            self._ensure_started()
        pages = [page for page in self._context.pages if not page.is_closed()]
        if self._page not in pages:
            if pages:
                self._page = pages[-1]
            else:
                # 새로 여는 탭도 빈 창으로 두지 않는다. 2026-08-10 실측: 작업이
                # 끝난 뒤 화면에 about:blank 만 남아 있었는데, 그 상태에서 자비스가
                # "메인 페이지를 띄워 두었습니다"라고 답했다. 사람이 보는 것과
                # 자비스가 말하는 것이 갈라지는 자리다.
                self._page = self._new_page()
                self._yield_new_window(self._page)
        return self._page

    def _connection_objects(self) -> int:
        """Playwright 연결 장부에 쌓인 물건 수. 대부분이 페이지가 주고받은 요청 · 응답 기록이다. 못 읽으면 0."""
        try:
            return len(self._context._impl_obj._connection._objects)  # noqa: SLF001 — 공개된 눈금이 없다
        except Exception:  # noqa: BLE001
            return 0

    def _note_connection_weight(self) -> None:
        """장부가 한도를 넘었으면 「다음 동작 앞에서 연결을 간다」고 적어 둔다. 동작 하나의 맨 앞에서만 부른다.

        ★ 동작 도중에 갈면 그 동작이 쥔 탭 손잡이가 죽는다. 그래서 적어 두기만 하고, 가는 것은 `_current_page` 가 한다.
        """
        if self._reconnect_pending or self._connect_mode not in ("attached", "spawned"):
            return
        limit = max(0, int(getattr(self.config, "browser_reconnect_after_objects", 0) or 0))
        if limit and self._connection_objects() >= limit:
            self._reconnect_pending = True
            self._reconnect_reason = "connection_objects"

    def _reconnect_attached(self) -> None:
        """Chrome은 살리고 Playwright CDP 연결만 갈아 탐색 핸들을 회수한다.

        ★ 2026-10-14: 우리가 **띄운** 크롬(spawned)에서도 간다. 예전에는 붙은 크롬(attached)에서만 갈았는데, PC 를 켜고
          처음 실행한 사람은 전부 「띄운 크롬」이다 — 그 길에는 회수가 아예 없어서 켜 둔 시간만큼 쌓였다(8GB 노트북 12시간
          뒤 메모리 18GB). 크롬은 끄지 않고 연결만 내려놓은 뒤 같은 포트에 다시 붙고, 끌 때 같이 끄도록 다시 우리 것으로 적는다.
        """
        if self._connect_mode not in ("attached", "spawned"):
            self._reconnect_pending = False
            return
        spawned_process = self._chrome_proc if self._connect_mode == "spawned" else None
        was_spawned = self._connect_mode == "spawned"
        objects_before = self._connection_objects()
        reason = str(getattr(self, "_reconnect_reason", "") or "navigation_handle_budget")
        began = time.monotonic()
        page = self._page
        try:
            self._reattach_url = (
                str(getattr(page, "url", "") or "") if page is not None and not page.is_closed() else ""
            )
        except Exception:
            self._reattach_url = ""
        # URL 문자열만 보존한다. 이 지역변수가 옛 Page 객체를 계속 쥐고 있으면
        # 아래 gc.collect()는 순환 참조의 출발점 자체를 수거할 수 없다.
        page = None
        navigation_count = self._navigation_count
        self._reconnect_pending = False
        self._reconnect_reason = ""
        self._navigation_count = 0
        self._shutdown(keep_chrome=True)
        # Page -> event listener -> bound method -> BrowserWorker -> Page 순환
        # 참조는 Playwright.stop()만으로는 즉시 사라지지 않는다. Windows 실측:
        # 30회 goto 뒤 stop만 하면 handle +450 잔류, 참조 해제 뒤 gc.collect()까지
        # 하면 +11만 남았다(2026-08-17). 새 연결을 만들기 전에 옛 세대를 수거해야
        # 재attach 자체가 누수를 더 키우지 않는다.
        gc.collect()
        self._ensure_started()
        if was_spawned and self._connect_mode == "attached":
            # 다시 붙으면 「붙은 크롬」으로 적히지만 이것은 우리가 띄운 크롬이다 — 끌 때 같이 끄도록 되돌려 적는다.
            self._connect_mode = "spawned"
            self._chrome_proc = spawned_process
        self._reconnections += 1
        self._last_reconnect = {
            "at": time.time(),
            "reason": reason,
            "navigations": navigation_count,
            "objects_before": objects_before,
            "objects_after": self._connection_objects(),
            "took_ms": round((time.monotonic() - began) * 1000),
            "url": self._reattach_url or str(getattr(self._page, "url", "") or ""),
        }

    def _goto_page(self, page: Any, url: str, *, wait_until: str) -> Any:
        """탐색을 세어 attach 연결이 핸들을 끝없이 쌓지 않게 한다."""
        response = page.goto(url, wait_until=wait_until)
        if self._connect_mode in ("attached", "spawned"):
            self._navigation_count += 1
            limit = max(0, int(self.config.browser_reconnect_after_navigations))
            if limit and self._navigation_count >= limit:
                self._reconnect_pending = True
        return response

    def _go_home(self, page: Any) -> None:
        """빈 창 대신 쓸 수 있는 화면을 띄워 둔다.

        자비스가 자기 일을 할 때는 주소로 바로 가므로 시작 화면이 무엇이든 상관없다.
        문제는 **사람이 이 창을 쓸 때**다 — 로그인을 하려고 봐도 about:blank 라
        주소를 손으로 쳐야 했다(2026-08-10 사용자 지적). 네이버가 떠 있으면 거기서
        검색해서 들어갈 수 있고, 네이버 로그인 자체도 바로 된다.

        이미 뭔가 열려 있으면 건드리지 않는다. 재기동이 사람이 보던 화면을
        뺏으면 안 된다.

        실패해도 무시한다 — 시작 화면 하나 때문에 브라우저 기동이 실패하면
        그게 훨씬 나쁘다.
        """
        home = str(self.config.browser_home_url or "").strip()
        if not home or page is None:
            return
        try:
            if str(getattr(page, "url", "") or "") not in ("", "about:blank"):
                return
            page.goto(home, wait_until="domcontentloaded")
        except Exception:
            pass

    #: 조용한 캡처 한 장에 주는 시간. 보이는 탭은 실측 0.04~0.09초다.
    _QUIET_CAPTURE_TIMEOUT_MS = 2500
    #: 제한에 걸린 탭은 이만큼 다시 안 찍는다. 1.5초마다 오는 실시간 화면이 매번 2.5초를
    #: 태우면 브라우저 일꾼을 사실상 계속 쥐게 된다 — 그것이 이번에 고친 병의 약한 판이다.
    _QUIET_CAPTURE_BACKOFF_SEC = 20.0

    def _capture(self, page: Any, *, quiet: bool, quality: int = 55) -> bytes | None:
        """사람이 PC 를 쓰는 중이면 **창을 안 올리고, 시간 제한을 걸고** 찍는다.

        못 찍으면 None 이고 `_capture_skip_reason` 에 이유가 남는다. 조용한 모드에서 None 을 받은
        쪽은 **제한 없는 캡처로 되돌아가지 말 것** — 같은 탭은 같은 이유로 또 안 찍힌다.

        ★★ 2026-09-16, 이어받기 e2e 5·6·7판이 전부 `browser_busy_stuck` 으로 멈춘 원인.
          예전 판은 CDP `Page.captureScreenshot` 을 **직접** 불렀고, 그 호출에는 시간 제한이 없다.
          크로미움은 **프레임을 안 만드는 탭**(최소화된 창의 탭 · 보이는 창의 배경 탭)에서 이 요청에
          답하지 않는다. 실시간 화면 한 장이 브라우저 전용 스레드를 무기한 쥐었고, 뒤따른 모든
          도구가 `busy_stuck` 으로 거절됐다.

          재현(`bench/browser_agents/repro_hidden_tab_capture.py`, 임시 프로필 크롬):
            최소화+앞탭 → 8초 넘게 안 옴 · 최소화+배경탭 → 안 옴
            보이되 맨뒤+앞탭 → 0.04초 · 보이되 맨뒤+배경탭 → 안 옴

          ★ 인수인계가 제안한 「`document.visibilityState` 가 hidden 이면 건너뛴다」는 **못 쓴다.**
            Playwright 로 붙은 탭은 네 조건 전부 `visible` 로 답했다(원시 CDP `Runtime.evaluate` 로
            물어도, `requestAnimationFrame` 도 전부 정상). 페이지 안에서는 멈출 탭을 가를 수 없다.
            그래서 미리 가르지 않고 **제한을 건다.**

          Playwright 1.62 의 `page.screenshot` 은 같은 `Page.captureScreenshot` 에 **제한만 씌운 것**이다
          (드라이버 `crPage.takeScreenshot` 확인 — `bringToFront` 를 부르지 않는다). 네 조건 실측에서
          창을 앞으로 올리지도, 최소화를 풀지도 않았고, 제한을 넘기면 3.03초에 예외로 돌아왔다.
          속도도 같다(보이는 탭 6회: 0.044~0.088초 vs 직접 CDP 0.043~0.055초).
        """
        self._capture_skip_reason = ""
        if not quiet or self._may_take_foreground():
            return None
        key = id(page)
        stalled = self._capture_stalled.get(key)
        if stalled is not None and time.time() - stalled[0] < stalled[2]:
            self._capture_skip_reason = stalled[1]
            return None
        try:
            raw = page.screenshot(type="jpeg", quality=quality, scale="css",
                                  timeout=self._QUIET_CAPTURE_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if len(self._capture_stalled) > 50:
                self._capture_stalled.clear()
            if "Timeout" in text or "timeout" in text:
                self._capture_stalled[key] = (time.time(), "capture_timeout_hidden_tab", self._QUIET_CAPTURE_BACKOFF_SEC)
                self._capture_skip_reason = "capture_timeout_hidden_tab"
            elif "0 width" in text or "0 height" in text:
                # ★ 2026-09-17 제품 책임자 화면: `capture_failed: Page.screenshot: Protocol error (Page.captureScreenshot):
                #   Cannot take screenshot with 0 width` 가 원문 그대로 떴다. 크롬 창이 **최소화**되면 폭이 0 이다.
                #   고장이 아니라 창 상태다 — 짧게(5초) 쉬고, 사람이 창을 올리면 바로 다시 보인다.
                self._capture_stalled[key] = (time.time(), "capture_window_minimized", 5.0)
                self._capture_skip_reason = "capture_window_minimized"
            else:
                self._capture_skip_reason = "capture_failed: " + _clean(text, 160)
            return None
        self._capture_stalled.pop(key, None)
        return bytes(raw) if raw else None

    def _may_take_foreground(self) -> bool:
        """우리가 화면을 앞으로 가져와도 되는가. **기본은 안 된다.**

        ★ 2026-09-16, 같은 지적을 두 번째로 받은 자리. 이 판단이 `_user_is_busy()` —
          「최근 10초 안에 키·마우스 입력이 있었나」— 였다. 맡겨 놓고 **지켜보는** 사람은
          키를 누르지 않는다. 10초가 지나면 양보가 풀려 크롬이 최대화로 튀어나왔다.
          MCP 로 맡긴 판에서 특히 그렇다 — 사람은 다른 창에서 대화하는 중이라 손이 멈춰 있다.

          「10초」를 늘리는 것은 고치는 게 아니라 미루는 것이다. 30분짜리 일을 지켜보는
          사람은 어떤 값으로도 안 잡힌다. 그래서 **조건을 없앤다.** 뒤에서 일해도 결과는
          같다(2026-09-16 실측: 창을 내린 채 조사→문서 3판 373~445초 전부 성공).

        되돌리는 법은 한 줄이다 — `JARVIS_BROWSER_ALLOW_FOREGROUND=1`.
        """
        # `__init__` 을 안 거친 워커(시험)는 지금까지처럼 군다 — `_user_is_busy` 와 같은 규칙.
        # 먼저 묻는 이유는 그 워커에 `config` 도 없기 때문이다(실측으로 잡혔다).
        if getattr(self, "presence", None) is None:
            return True
        return bool(getattr(getattr(self, "config", None), "browser_allow_foreground", False))

    def _user_is_busy(self, *, count: bool = True) -> bool:
        """사람이 PC 를 쓰는 중이면 True 로 답하고 양보 수를 센다. `__init__` 을 안 거친 워커(시험)는 양보하지 않는다."""
        presence = getattr(self, "presence", None)
        if presence is None or not presence.active():
            return False
        if count:
            self._yielded_front = getattr(self, "_yielded_front", 0) + 1
        return True

    def present_for_human(self, *, activate: bool = False) -> dict[str, Any]:
        """사람이 직접 해야 하는 순간(로그인·사람 확인) — 크롬 창을 **찾기 쉽게** 해 둔다.

        ★ 2026-09-18 새벽 사용자 요청: 「앞으로 뜨면 하던 작업 흐름이 끊긴다. 다른 AI 앱을 쓰면서 온텔릭도 쓰는데,
          온텔릭이 브라우저를 쓸 때마다 그 앱을 다시 끄집어내야 한다. 뒤에 떠 있고 작업표시줄 크롬을 누르면 보이게.」
          그래서 온텔릭이 스스로 멈출 때(`activate=False`)는 **앞으로 올리지 않는다** — 탭만 맞추고, 창은 보이는 채로
          맨 뒤에, 작업 표시줄 아이콘만 깜빡인다. 사람이 「크롬 창 보기」를 **직접 눌렀을 때만**(`activate=True`) 앞으로.
        """
        try:
            return dict(self._submit(lambda: self._present_for_human(activate=activate), 8) or {})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": _clean(exc, 200)}

    def _present_for_human(self, *, activate: bool = False) -> dict[str, Any]:
        page = self._page
        if page is None:
            return {"ok": False, "error": "browser_not_started"}
        user32 = None
        keep = 0
        if sys.platform == "win32":
            try:
                import ctypes

                user32 = ctypes.windll.user32
                keep = int(user32.GetForegroundWindow() or 0)
            except Exception:
                user32 = None
        # 「크롬 창 보기」를 눌렀는데 창이 투명하면 안 된다 — 뜨는 동안 가드가 숨겨 둔 창을 먼저 돌려놓는다.
        self._birth_guard_stop.set()
        if user32 is not None:
            self._finish_newborn_windows(user32)
        # 막힌 그 탭을 크롬 안에서 고른다. 이 호출은 창까지 앞으로 끌어와(실측 0.05초) 아래에서 되돌리니,
        # 고를 탭이 따로 없을 때(탭 하나)는 부르지 않는다 — 그 짧은 순간에도 사람의 타자가 크롬으로 샐 수 있다.
        try:
            tabs = len(page.context.pages)
        except Exception:
            tabs = 2
        if activate or tabs > 1:
            try:
                page.bring_to_front()
            except Exception:
                pass
        raised = 0
        if user32 is not None and self._browser_is_ours():
            try:
                import ctypes
                import ctypes.wintypes as wt

                self._restore_sunk_windows(user32)

                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [("cbSize", wt.UINT), ("hwnd", wt.HWND), ("dwFlags", wt.DWORD),
                                ("uCount", wt.UINT), ("dwTimeout", wt.DWORD)]

                ours = self._our_chrome_windows(include_iconic=True)
                for hwnd in ours:
                    if activate:
                        BrowserWorker._human_shown.add(int(hwnd))  # 사람이 불렀다 — 감시가 도로 치우지 않게 **먼저** 적는다
                        placement = self._usable_window_rect(user32, hwnd)
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE — 최소화였으면 편다
                        if placement is not None:
                            left, top, width, height = placement
                            # HWND_TOP=0 · 화면 밖·너무 작은 창은 사람이 쓰는 모니터 작업 영역으로
                            user32.SetWindowPos(hwnd, 0, left, top, width, height, 0x0040)
                        user32.SetForegroundWindow(hwnd)
                        flags = 0x3 | 0xC  # FLASHW_ALL|FLASHW_TIMERNOFG
                    else:
                        if keep and keep not in ours and int(user32.GetForegroundWindow() or 0) == hwnd:
                            self._give_focus_back(user32, hwnd, keep)  # 탭 고르다 앞을 쥐었으면 돌려준다
                        else:
                            if user32.IsIconic(hwnd):
                                self._restore_quietly(user32, hwnd)
                            self._send_window_to_back(user32, hwnd)
                        flags = 0x2 | 0xC  # FLASHW_TRAY|FLASHW_TIMERNOFG — 작업 표시줄만, 창은 안 올린다
                    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, flags, 0, 0)
                    user32.FlashWindowEx(ctypes.byref(info))
                    raised += 1
            except Exception:
                pass
        return {"ok": True, "windows": raised, "activated": bool(activate),
                "url": str(getattr(page, "url", "") or "")}

    def _bring_to_front(self, page: Any) -> None:
        """탭을 앞으로. 사람이 PC 를 쓰는 중이면 창을 올리지 않는다 — Page.bringToFront 는 창까지 앞으로 끌어온다."""
        if page is None:
            return
        if not self._may_take_foreground():
            self._user_is_busy()  # 양보 수는 그대로 센다
            return
        try:
            page.bring_to_front()
        except Exception:
            pass

    def _yield_new_window(self, page: Any) -> None:
        """방금 띄운 창을 **내려 둔다** — 사람이 쓰는 중일 때만.

        내려도 일은 그대로 된다. 2026-09-16 실측에서 창을 최소화한 채로 조사→문서 3판이
        전부 성공했다(373~445초). 그러니 사람이 타이핑 중일 때 화면을 뺏을 이유가 없다.

        **붙어 쓰는 크롬(attached)은 건드리지 않는다.** 그건 사람의 창이다 — 우리가 내리면
        사람이 보던 것을 치우는 셈이 된다. 우리가 띄운 창만 우리가 내린다.
        """
        if page is None or self.config.browser_headless:
            return
        if not self._browser_is_ours():
            return
        if self._may_take_foreground():
            return
        if sys.platform == "win32":
            # 최소화한 채로 두지 않는다 — 최소화한 창의 탭은 그림을 안 만든다(`_capture`, 2026-09-16).
            # 뜨는 동안 감시가 내려 둔 창을 **감시 스레드가** 되살린다(경합 방지). 감시가 이미 끝났으면
            # (기동이 8초보다 느린 판) 여기서 직접 되살린다.
            try:
                self._sink_settled.set()
                import ctypes

                user32 = ctypes.windll.user32
                if str(self._sink_report.get("thread") or "") != "running":
                    self._restore_sunk_windows(user32)
                for hwnd in self._our_chrome_windows():
                    self._send_window_to_back(user32, hwnd)
            except Exception:  # noqa: BLE001
                pass
            return
        self._set_window_state(page, "minimized")

    def _set_window_state(self, page: Any, state: str) -> None:
        """창 상태를 바꾼다(minimized·maximized·normal). 실패는 삼킨다 — 창 모양 때문에 일이 죽으면 안 된다."""
        session = None
        try:
            session = self._context.new_cdp_session(page)
            info = session.send("Browser.getWindowForTarget")
            session.send(
                "Browser.setWindowBounds",
                {"windowId": info["windowId"], "bounds": {"windowState": state}},
            )
        except Exception:
            pass
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass

    def _maximize_window(self, page: Any) -> None:
        if self.config.browser_headless or page is None or page.is_closed():
            return
        if not self._may_take_foreground():
            # 최대화는 최소화해 둔 창을 되살려 앞으로 띄운다 — 그것이 곧 화면을 가져가는 것이다.
            self._user_is_busy()
            return
        session = None
        try:
            session = self._context.new_cdp_session(page)
            info = session.send("Browser.getWindowForTarget")
            session.send(
                "Browser.setWindowBounds",
                {"windowId": info["windowId"], "bounds": {"windowState": "maximized"}},
            )
        except Exception:
            pass
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass

    @staticmethod
    def _validate_url(url: str) -> str:
        value = url.strip()
        if not value:
            raise ValueError("url_required")
        if "://" not in value:
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("browser_url_not_allowed")
        return value

    def _evidence(self, action: str, **extra: Any) -> dict[str, Any]:
        page = self._page
        url = ""
        title = ""
        if page is not None and not page.is_closed():
            try:
                url = page.url
                title = page.title()
            except Exception:
                pass
        result = {"action": action, "url": url, "title": _clean(title, 300), **extra}
        # 방금 확인창이 지나갔으면 결과에 실어 보낸다. 이게 없으면 "눌렀는데 아무 일도
        # 안 일어났다"로 보이고, 무엇을 묻고 무엇으로 답했는지가 사라진다.
        last = self._last_dialog
        if last and time.time() - float(last.get("at") or 0) < 30:
            result["dialog_answered"] = {
                "message": last.get("message", ""),
                "type": last.get("type", ""),
                "accepted": last.get("accepted", False),
                **({"blocked_by_read_only": True} if last.get("blocked_by_read_only") else {}),
                # 누가 답했는지 숨기지 않는다 — 모델이 정한 것이 아니라 도구가 이 PC 안 페이지라서 확인한 것이다.
                **({"auto_accepted_local": True, "note": LOCAL_DIALOG_NOTE} if last.get("auto_accepted_local") else {}),
            }
        return result

    # 셀렉터를 받는 기대(expect). 모델에게는 안 연다.
    #
    # 이 저장소의 원칙이 "모델은 셀렉터를 지어내면 안 된다 — 지어낸 셀렉터가 이틀을
    # 태웠다"(`_find_selector` 주석)인데, 예측을 강제한다면서 셀렉터를 짓게 하면 그
    # 원칙을 정면으로 깬다. 특히 `appears` 가 위험하다: 아무 셀렉터나("div") 주면
    # count > 0 이 되어 **거짓 성공**이 난다. 나머지 둘은 못 찾으면 실패로 떨어지니
    # 덜 위험하지만, 같은 이유로 함께 막는다.
    #
    # 사람이 실측해서 못 박은 레시피는 그대로 쓴다(naver_blog.json 의
    # `number_increases: .save_btn__bzc5B`). 거기가 이 지식이 있어야 할 자리다.
    _SELECTOR_EXPECTS = frozenset({"appears", "disappears", "count_increases", "number_increases"})

    @classmethod
    def _reject_untrusted_expect(cls, arguments: dict[str, Any]) -> None:
        kind = str((arguments.get("expect") or {}).get("kind") or "")
        if kind in cls._SELECTOR_EXPECTS:
            raise RuntimeError(
                f"expect_kind_needs_a_recipe:{kind}"
                " — 이 기대는 CSS 셀렉터가 있어야 하고, 셀렉터는 지어내면 안 됩니다."
                " 셀렉터 없이 쓸 수 있는 것: url_changes · text_appears · text_disappears."
                " 이 사이트에서 꼭 이 방식이어야 하면 레시피(recipes/*.json)에 적으세요."
            )

    # 브라우저가 죽었을 때 **다시 띄우고 한 번 더 해 볼** 동작들.
    #
    # 여기 있는 것은 전부 아무것도 커밋하지 않는다 — 열기·읽기·찾기·검색이다.
    # 누르기·채우기·올리기·발행은 일부러 뺐다. 브라우저가 사라졌다는 것은 그
    # 동작이 **닿지 않았다**는 뜻이라 되풀이해도 논리적으로는 안전하지만, 여러
    # 단계를 밟는 핸들러(폼 채우기)가 중간에 죽은 경우까지 여기서 판단할 수는
    # 없다. 되돌릴 수 없는 것 앞에서는 조용히 다시 하지 않는다 — 실패로 올리고
    # 사람이 화면을 본다(attention.py 의 browser_stuck).
    _RETRY_ON_DEAD_BROWSER = frozenset(
        {
            "browser_open",
            "browser_search",
            # 사이트 자기 검색은 글자를 넣지만 **읽기**다 — 결과 목록을 받아 올 뿐
            # 무엇도 저장·제출하지 않는다. 브라우저가 죽었을 때 한 번 더 해 보는
            # 목록에 넣어 두는 이유도 그것이다.
            "browser_site_search",
            "browser_load_more",
            "browser_open_result",
            "browser_extract",
            "browser_links",
            "browser_find",
            "browser_snapshot",
            "browser_probe_frames",
            "browser_screenshot",
            "browser_download",
            "browser_read",
            "browser_tabs",
            "browser_switch_tab",
            "browser_back",
            "browser_wait",
            "browser_scroll",
        }
    )

    #: 지금 탭을 **떠나는** 동작 — 나가기 확인창에 막히면 새 탭에서 다시 한다.
    _LEAVES_THE_PAGE = frozenset({"browser_open", "browser_search"})

    def _leaving_was_refused(self, exc: BaseException) -> bool:
        """방금 실패가 「나가시겠습니까?」를 우리가 취소로 닫아서 난 것인가 — 오류 모양과 **방금 뜬 확인창**으로 본다."""
        if "ERR_ABORTED" not in str(exc):
            return False
        last = self._last_dialog or {}
        return (
            last.get("type") == "beforeunload"
            and last.get("accepted") is False
            and time.time() - float(last.get("at") or 0) < 15
        )

    def _execute(
        self, action: str, arguments: dict[str, Any], *, trusted: bool = False
    ) -> dict[str, Any]:
        try:
            return self._execute_once(action, arguments, trusted=trusted)
        except Exception as exc:
            # ★ **사람이 쓰던 폼은 그대로 두고 새 탭에서 연다** (2026-10-07 대표 실사용 「브라우저 잠김」).
            #   이력서 수정 탭에 저장 안 된 입력이 생긴 뒤로 모든 이동이 `ERR_ABORTED` 였다(Ornith 19걸음 중 11번 ·
            #   Gemma 5번). 사이트의 「나가시겠습니까?」를 우리가 취소로 닫은 것이다 — 입력을 지키는 답으로는 맞지만,
            #   모델에게는 이유가 안 갔고 그 탭에서 영영 못 나갔다. 「확인」으로 넘기면 사람이 쓰던 글이 날아간다.
            #   그래서 그 탭은 두고 **새 탭**에서 같은 동작을 한 번 더 한다. 무엇을 했는지 결과에 적는다.
            if action in self._LEAVES_THE_PAGE and self._leaving_was_refused(exc):
                left = str(getattr(self._page, "url", "") or "")
                self._page = self._new_page(home=False)
                result = self._execute_once(action, arguments, trusted=trusted)
                if isinstance(result, dict):
                    result["opened_in_new_tab"] = True
                    result["instruction"] = (
                        f"[도구가 보낸 안내] 앞 탭({left[:100]})에는 저장 안 된 입력이 있어 사이트가 나가기를 막았다. "
                        "그 탭은 **그대로 두고 새 탭에서** 열었다(입력은 남아 있다). 그 폼으로 돌아가려면 browser_tabs 로 "
                        "목록을 보고 browser_switch_tab 을 써라. " + str(result.get("instruction") or "")
                    ).strip()
                return result
            # `_current_page` 를 지나온 뒤에 브라우저가 죽는 창은 늘 남는다.
            # 읽기 동작이면 다시 띄우고 한 번만 더 해 본다 — 한 번만이다.
            if action not in self._RETRY_ON_DEAD_BROWSER or not _DEAD_BROWSER.search(str(exc)):
                raise
            self._shutdown()
            return self._execute_once(action, arguments, trusted=trusted)

    def _execute_once(
        self, action: str, arguments: dict[str, Any], *, trusted: bool = False
    ) -> dict[str, Any]:
        self._settle_human_dialog()
        self._doing = "current_page"  # 크롬을 띄우거나 붙는 구간 — 첫 동작이 여기서 오래 걸릴 수 있다
        self._note_connection_weight()
        page = self._current_page()
        # 밑줄로 시작하는 인자는 **바깥에서 오면 안 되는 값**이다. 게이트웨이도
        # 여기도 인자를 스키마로 거르지 않고 그대로 넘기므로, 이걸 안 떨어내면
        # 호출자가 내부 표식을 지어내 붙일 수 있다 — `_approved` 하나로 결제·삭제의
        # L2 승인이 통째로 우회됐다. 승인 같은 것은 인자가 아니라 매개변수로 받는다.
        arguments = {key: value for key, value in arguments.items() if not key.startswith("_")}
        if not trusted:
            # 한 곳에서 막는다 — click·press·fill·verify 가 전부 같은 expect 를 받는다.
            self._reject_untrusted_expect(arguments)
        handlers: dict[str, Callable[[Any, dict[str, Any]], dict[str, Any]]] = {
            # ★ 검토된 절차(레시피)가 부를 때는 주소를 가로채지 않는다 (2026-08-13).
            #
            # 모델이 손으로 조립한 검색 주소를 잡으려고 `_open` 에 가로채기를 넣었는데,
            # `recipes/saramin.json` 의 `?searchword={query}` 가 **정확히 같은 모양**이라
            # 같이 걸렸다. 사람이 보고 확정한 경로를 두고 홈으로 돌아가 검색칸을
            # 찾기 시작했고, 벤치에서 사람인이 150초 성공 → 204초 미달로 뒤집혔다.
            #
            # `trusted` 는 `execute(..., trusted=True)` 로만 켜진다 — 인자가 아니라
            # **어느 문으로 들어왔는가**다. 모델 쪽 등록(`BrowserTools.register`)은
            # 이 값을 안 넘기므로 스스로 켤 수 없다(`_approved` 구멍에서 배운 규칙).
            "browser_open": lambda page, args: self._with_site_traits(
                page, self._noting_departure(page, self._open(page, args, trusted=trusted))),
            "browser_search": self._search,
            "browser_site_search": lambda page, args: self._with_site_traits(page, self._site_search(page, args)),
            "browser_load_more": self._load_more_tool,
            "browser_close": self._close,
            "browser_open_result": lambda page, args: self._with_site_traits(page, self._open_result(page, args)),
            "browser_extract": self._extract_with_data,
            "browser_page_data": self._page_data,
            "browser_site_sources": self._site_sources,
            "browser_links": self._links,
            "browser_find": self._find,
            "browser_snapshot": self._snapshot,
            "browser_probe_frames": self._probe_frames,
            "browser_screenshot": self._screenshot,
            "browser_download": self._download,
            "browser_annotate": self._annotate,
            "browser_dismiss_dialog": self._dismiss_dialog,
            "browser_verify": self._verify,
            "browser_find_selector": self._find_selector,
            "browser_click_confirmed": self._click_confirmed,
            "browser_fill_form": self._fill_form,
            "browser_select_option": self._select_option,
            "browser_file_upload": self._file_upload,
            "browser_handle_dialog": self._handle_dialog,
            "browser_read": self._read_with_data,
            "browser_click": self._click,
            "browser_click_at": self._click_at,
            "browser_type_at": self._type_at,
            "browser_hover": self._hover,
            "browser_fill": self._fill,
            "browser_pick_suggestion": self._pick_suggestion,
            "browser_press": self._press,
            "browser_scroll": self._scroll,
            "browser_tabs": self._tabs,
            "browser_switch_tab": self._switch_tab,
            "browser_back": self._back,
            "browser_wait": self._wait,
            "naver_blog_open_editor": self._naver_blog_open_editor,
            "naver_blog_read_account": self._naver_blog_read_account,
            "naver_blog_fill_editor": self._naver_blog_fill_editor,
            "naver_blog_upload_image": self._naver_blog_upload_image,
            "naver_blog_capture_screen": self._naver_blog_capture_screen,
            "naver_blog_click_save_draft": self._naver_blog_click_save_draft,
            "naver_blog_click_publish": self._naver_blog_click_publish,
        }
        handler = handlers.get(action)
        if handler is None:
            raise ValueError(f"unknown_browser_action:{action}")
        self._action_depth += 1
        if self._action_depth == 1:
            # ★ 2026-09-16 실측: `context.on("page")` 로 「우리 동작 중에 생긴 탭」을 잡으려 했는데
            #   24장 중 **2장**만 잡혔다. Playwright 동기 API 는 이벤트를 **다음 호출 때 펌프**하므로,
            #   콜백이 도는 시점엔 동작이 이미 끝나 있다(`_action_depth == 0`). 시점을 이벤트에
            #   맡기면 안 된다 — 동작을 **시작할 때 목록을 찍어** 두고, 끝날 때 차이를 본다.
            self._pages_before_action = self._page_ids()
        try:
            # `_doing` — 지금 어느 구간에 있나. 시간에 끊기면 오류 글에 실린다(`_submit`).
            self._doing = "show_visual"
            self._show_visual(page, self._visual_label(action))
            self._doing = "handler"
            self._refuse_hand_on_another_site(action, page)
            self._hold_if_human_on_tab(action, page)
            started_at = time.time()
            result = handler(page, arguments)
            self._note_job_navigated(action)
            self._note_own_page_after(action, arguments, started_at)
            result = self._with_human_on_tab_note(result)
            self._doing = "show_visual_done"
            self._show_visual(self._page, "작업 단계 완료", completed=True)
            with self._lock:
                self._last_error = ""
            # 다 본 탭을 치운다. 여는 자리마다 붙이지 않고 **끝나는 한 자리**에서 한다 —
            # 그래야 어느 길로 열렸든 같은 규칙이 걸린다.
            try:
                self._prune_tabs()
            except Exception as prune_error:  # noqa: BLE001
                # ★ 삼키지 않는다. 2026-09-16 에 여기서 통째로 삼켜서, 탭이 25장인데도
                #   「정리가 돌았고 닫을 것이 없었다」로 보였다. 정리 실패로 일을 죽일 이유는
                #   없지만(탭 때문에 조사가 실패하면 안 된다) **왜 못 했는지는 남는다.**
                self._tab_census["error"] = _clean(prune_error, 300)
            if self._close_after_action:
                # 일이 끝났으니 창을 치운다. 여기서 닫는 이유는 위 마무리 표시가
                # 살아 있는 페이지를 필요로 하기 때문이다.
                self._close_after_action = False
                self._shutdown()
                if isinstance(result, dict):
                    result = {**result, "browser_closed": True}
            return result
        except Exception as exc:
            self._close_after_action = False
            message = _clean(exc, 800)
            with self._lock:
                self._last_error = message
            if not any(marker in message for marker in _NO_EVIDENCE_ERRORS):
                self._last_failure = self._capture_failure_evidence(action, message)
            raise
        finally:
            self._action_depth = max(0, self._action_depth - 1)

    @staticmethod
    def _visual_label(action: str) -> str:
        return {
            "browser_open": "페이지 여는 중",
            "browser_search": "웹 검색 중",
            "browser_site_search": "이 사이트 안에서 검색 중",
            "browser_load_more": "목록 더 불러오는 중",
            "browser_close": "브라우저 닫는 중",
            "browser_open_result": "검색 결과 열어 보는 중",
            "browser_extract": "본문 추려 읽는 중",
            "browser_links": "다음에 볼 링크 찾는 중",
            "browser_find": "화면에서 찾는 중",
            "browser_snapshot": "페이지 요소 확인 중",
            "browser_screenshot": "화면 캡처 중",
            "browser_download": "문서 받는 중",
            "browser_annotate": "화면에서 후보 표시 중",
            "browser_dismiss_dialog": "가로막는 창 정리 중",
            "browser_verify": "결과 확인 중",
            "browser_find_selector": "화면에서 대상 찾는 중",
            "browser_click_confirmed": "승인된 동작 실행 중",
            "browser_fill_form": "양식 채우는 중",
            "browser_select_option": "항목 선택 중",
            "browser_file_upload": "파일 첨부 중",
            "browser_handle_dialog": "확인창에 답하는 중",
            "browser_read": "본문 읽는 중",
            "browser_click": "선택한 항목 여는 중",
            "browser_click_at": "화면 좌표를 누르는 중",
            "browser_page_data": "페이지가 받아 온 데이터에서 찾는 중",
            "browser_site_sources": "이 사이트의 공개 출처를 찾는 중",
            "browser_type_at": "화면 좌표의 칸에 입력하는 중",
            "browser_hover": "메뉴 위에 올려 펼치는 중",
            "browser_fill": "입력란 작성 중",
            "browser_pick_suggestion": "목록에서 고르는 중",
            "browser_press": "키 입력 중",
            "browser_scroll": "다음 내용 확인 중",
            "browser_tabs": "탭 확인 중",
            "browser_switch_tab": "탭 이동 중",
            "browser_back": "이전 페이지로 이동 중",
            "browser_wait": "페이지 응답 대기 중",
            "naver_blog_open_editor": "네이버 블로그 편집기 여는 중",
            "naver_blog_read_account": "블로그 계정 확인 중",
            "naver_blog_fill_editor": "블로그 글 작성 중",
            "naver_blog_upload_image": "이미지 업로드 중",
            "naver_blog_capture_screen": "화면 캡처 중",
            "naver_blog_click_save_draft": "임시저장 중",
            "naver_blog_click_publish": "블로그 발행 중",
        }.get(action, "손자리 작업 중")

    def _show_visual(
        self,
        page: Any,
        label: str,
        *,
        locator: Any = None,
        pulse: bool = False,
        completed: bool = False,
    ) -> None:
        if not self.config.browser_visual_overlay or page is None or page.is_closed():
            return
        # ★ 2026-10-05 영어 화면 촬영: 「Sonjari's computer」 안의 페이지 위 딱지만 한국어(「검색 결과 열어 보는 중」)였다.
        #   딱지를 그리는 자리는 여기 하나다 — 부르는 열 곳이 아니라 여기서 바꾼다. 사전에 없는 말(「‘이름’ 선택」)은 그대로 간다.
        from . import ui_i18n  # 늦게 가져온다(브라우저 층은 화면 언어를 평소엔 모른다)

        if ui_i18n.lang() == "en":
            label = ui_i18n.translate_text(label)
        x = y = None
        # 사라진 요소의 자리를 재면 기본 대기(8초)를 꽉 채운다 — 있는지부터 센다(`_still_there`).
        if locator is not None and self._still_there(locator):
            try:
                box = locator.bounding_box()
                if box:
                    x = float(box["x"]) + float(box["width"]) / 2
                    y = float(box["y"]) + float(box["height"]) / 2
            except Exception:
                pass
        try:
            page.evaluate(
                """({label, x, y, pulse, completed}) => {
                  const id = '__alture_jarvis_visual';
                  let root = document.getElementById(id);
                  if (!root) {
                    root = document.createElement('div');
                    root.id = id;
                    root.style.cssText = 'position:fixed;inset:0;z-index:2147483646;pointer-events:none;border:2px solid rgba(139,92,246,.74);box-shadow:inset 0 0 22px rgba(99,102,241,.20),inset 0 0 5px rgba(236,72,153,.26);transition:opacity .3s ease;';
                    const badge = document.createElement('div');
                    badge.dataset.jarvisPart = 'badge';
                    badge.style.cssText = 'position:absolute;top:14px;right:16px;padding:7px 11px;border:1px solid rgba(167,139,250,.45);border-radius:999px;color:#ede9fe;background:rgba(15,23,42,.86);box-shadow:0 8px 24px rgba(15,23,42,.28);font:600 11px/1.2 Segoe UI,sans-serif;backdrop-filter:blur(10px);';
                    const cursor = document.createElement('div');
                    cursor.dataset.jarvisPart = 'cursor';
                    cursor.style.cssText = 'position:absolute;left:0;top:0;width:19px;height:19px;border:2px solid rgba(255,255,255,.94);border-radius:50%;background:radial-gradient(circle,rgba(236,72,153,.92),rgba(124,58,237,.88));box-shadow:0 0 0 5px rgba(139,92,246,.16),0 0 22px rgba(168,85,247,.72);opacity:0;transform:translate(-30px,-30px);transition:transform .22s cubic-bezier(.22,1,.36,1),opacity .12s ease;';
                    root.append(badge, cursor);
                    (document.documentElement || document.body).appendChild(root);
                    // ★ 사람의 마우스가 다가오면 알약을 비킨다 (2026-10-01 네이버 서치어드바이저).
                    //   오른쪽 위는 사이트가 로그인 버튼을 두는 자리라, 알약이 그걸 덮어 사람이 못 봤다.
                    //   pointer-events:none 이라 알약 자체는 마우스를 못 받으니 문서에서 거리로 잰다.
                    //   모델 쪽은 원래 상관없다 — 스크린샷 때 숨기고(_toggle_overlay) 클릭은 통과한다.
                    const NEAR = 48;
                    document.addEventListener('mousemove', (ev) => {
                      const r = badge.getBoundingClientRect();
                      const near = ev.clientX > r.left - NEAR && ev.clientX < r.right + NEAR
                        && ev.clientY > r.top - NEAR && ev.clientY < r.bottom + NEAR;
                      badge.style.opacity = near ? '0' : '';
                    }, { passive: true, capture: true });
                    badge.style.transition = 'opacity .15s ease';
                  }
                  root.style.opacity = completed ? '.55' : '1';
                  const badge = root.querySelector('[data-jarvis-part="badge"]');
                  const cursor = root.querySelector('[data-jarvis-part="cursor"]');
                  if (badge) badge.textContent = `Sonjari · ${label}`;
                  if (cursor && Number.isFinite(x) && Number.isFinite(y)) {
                    cursor.style.opacity = '1';
                    cursor.style.transform = `translate(${x - 9.5}px,${y - 9.5}px)`;
                    if (pulse) {
                      const ring = document.createElement('div');
                      ring.style.cssText = `position:absolute;left:${x - 7}px;top:${y - 7}px;width:14px;height:14px;border:2px solid rgba(216,180,254,.95);border-radius:50%;animation:jarvisClick .48s ease-out forwards;`;
                      const style = document.createElement('style');
                      style.textContent = '@keyframes jarvisClick{to{transform:scale(4);opacity:0}}';
                      root.append(style, ring);
                      setTimeout(() => { ring.remove(); style.remove(); }, 550);
                    }
                  }
                  if (completed) setTimeout(() => { if (root) root.style.opacity = '.2'; }, 700);
                }""",
                {"label": label, "x": x, "y": y, "pulse": pulse, "completed": completed},
            )
        except Exception:
            return

    def _operable_count(self, page: Any) -> int:
        """모든 프레임을 합쳐 조작 가능한 요소가 몇 개인가."""
        total = 0
        for frame in self._frames_of(page):
            try:
                total += int(frame.locator(_INTERACTIVE).count())
            except Exception:
                continue
        return total

    def _wait_until_operable(self, page: Any, *, timeout_ms: int | None = None) -> dict[str, Any]:
        """페이지에 누를 것이 하나라도 생길 때까지. 없으면 시간까지만 기다린다.

        ★ 2026-08-05 실측(8개 사이트 점검): `domcontentloaded` 직후 스냅샷을 뜨면
        대학어디가·학교알리미·평가원이 **요소 0개**로 나왔다. 잠시 뒤 다시 뜨면
        111개·72개·177개다. 서버가 뼈대만 내려주고 나머지를 스크립트가 그리는
        사이트에서는 전부 이렇게 된다.

        요소 0개는 "빈 페이지"와 구별되지 않는다 — 모델은 그걸 보고 클릭 계획을 못
        세운 채 다른 길로 새거나, 없는 셀렉터를 지어낸다. 네이버 편집기에서 하루를
        보낸 것과 같은 고장이 범용 경로에도 있었던 셈이다(따뜻한 날엔 되고 식은
        날엔 안 된다).
        """
        limit = int(timeout_ms if timeout_ms is not None else self.config.browser_ready_timeout_ms)
        started = time.monotonic()
        deadline = started + max(0, limit) / 1000
        polls = 0
        while True:
            polls += 1
            count = self._operable_count(page)
            if count or time.monotonic() >= deadline:
                # `polls` 는 "정말 기다렸는가"의 유일한 증거다. 걸린 시간만 보면 세는
                # 비용(요소 수백 개면 그 자체로 100ms 넘는다)과 구별되지 않는다.
                return {
                    "count": count,
                    "ms": round((time.monotonic() - started) * 1000),
                    "polls": polls,
                }
            time.sleep(0.2)

    @staticmethod
    def _edge_blocked(page: Any) -> str:
        """문전박대 화면인가. 맞으면 **근거가 된 문구**를 돌려준다(빈 문자열이면 아니다)."""
        try:
            title = _clean(page.title(), 200).lower()
        except Exception:
            title = ""
        for marker in _EDGE_BLOCK_MARKERS:
            if marker in title:
                return marker
        try:
            body = _clean(page.locator("body").inner_text(timeout=2000), 4000).lower()
        except Exception:
            return ""
        if len(body) > _EDGE_BLOCK_MAX_CHARS:
            return ""
        for marker in _EDGE_BLOCK_MARKERS:
            if marker in body:
                return marker
        return ""

    @staticmethod
    def _under_maintenance(page: Any) -> str:
        """점검·일시 오류 화면인가. 맞으면 **근거가 된 문구**를 돌려준다.

        `_edge_blocked` 와 같은 모양이지만 **쓰임이 다르다** — 이쪽은 다시 해 보지
        않고 곧장 넘어간다. 다시 두드려도 열리지 않는 종류이기 때문이다.
        """
        try:
            title = _clean(page.title(), 200).lower()
        except Exception:
            title = ""
        for marker in _MAINTENANCE_MARKERS:
            if marker in title:
                return marker
        try:
            body = _clean(page.locator("body").inner_text(timeout=2000), 4000).lower()
        except Exception:
            return ""
        if len(body) > _MAINTENANCE_MAX_CHARS:
            return ""
        for marker in _MAINTENANCE_MARKERS:
            if marker in body:
                return marker
        return ""

    def _new_page(self, *, home: bool = True) -> Any:
        """새 탭. **사람이 쓰는 중이면 배경으로 만든다.**

        ★ 2026-09-16 실측: 크롬을 `SW_SHOWMINNOACTIVE` 로 내려 띄워도, 그 다음 `new_page()` 가
        창을 도로 앞으로 끌어올렸다. Playwright 의 `new_page` 는 CDP `Target.createTarget` 을
        **앞 탭으로** 만들기 때문이다. 같은 CDP 에 `background: true` 가 있다 — 그걸 직접 쓴다.
        (사용자 요청: 「띄우긴 띄워라, 작업표시줄에서 바로 볼 수 있게. 앞으로만 안 나오면 된다.」)

        배경으로 못 만들면 평소대로 만든다 — 탭 하나 때문에 일이 죽으면 안 된다.
        """
        page = None
        # ★ 주차 중이면 **언제나** 뒤에서 연다 (2026-09-24 노트북: 「걸음할 때마다 크롬이 앞으로 나온다」). 예전엔 사람이 PC 를
        #   쓰는 중일 때만 뒤에서 열어서, 사람이 가만히 화면을 보고 있으면 탭마다 크롬이 앞창을 쥐었다. 헤르메스도 같은 이유로
        #   「보이는 창이 없으니 포커스를 절대 안 뺏는다」를 원칙으로 둔다.
        if BrowserWorker._park_offscreen or not self._may_take_foreground():
            page = self._new_page_background()
        if page is None:
            page = self._context.new_page()
        self._claim_page(page)
        if home:
            self._go_home(page)
        return page

    def _new_page_background(self) -> Any:
        """CDP 로 **뒤에** 탭을 만든다. 만들어진 Page 객체는 목록 차이로 찾는다."""
        session = None
        try:
            anchor = next((page for page in self._context.pages if not page.is_closed()), None)
            if anchor is None:
                return None
            before = {id(page) for page in self._context.pages}
            session = self._context.new_cdp_session(anchor)
            session.send("Target.createTarget", {"url": "about:blank", "background": True})
            for _ in range(20):
                fresh = [page for page in self._context.pages
                         if id(page) not in before and not page.is_closed()]
                if fresh:
                    return fresh[-1]
                anchor.wait_for_timeout(100)
        except Exception:  # noqa: BLE001
            return None
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:  # noqa: BLE001
                    pass
        return None

    def _claim_page(self, page: Any) -> None:
        """이 탭은 **우리가 쓴 것**이라고 적어 둔다. 정리할 때 이 목록만 본다."""
        try:
            key = id(page)
        except Exception:  # noqa: BLE001
            return
        if key in self._our_pages:
            self._our_pages.remove(key)
        self._our_pages.append(key)
        del self._our_pages[:-60]

    def _page_ids(self) -> set[int]:
        """지금 열린 탭들의 손잡이. 못 물으면 빈 집합 — 그러면 아무것도 우리 것으로 늘지 않는다."""
        context = self._context
        if context is None:
            return set()
        try:
            return {id(page) for page in context.pages if not page.is_closed()}
        except Exception:  # noqa: BLE001
            return set()

    def _claim_if_we_caused_it(self, page: Any) -> None:
        """새 탭이 생겼다 — **우리 동작 중에 생긴 것만** 우리 것으로 적는다.

        ★ 2026-09-16 (두 번째 지적: 「탭이 너무 많다」). `browser_max_tabs` 를 6 으로 넣고
          동작이 끝날 때마다 `_prune_tabs` 를 불렀는데도 탭이 쌓였다. 정리가 `_our_pages`
          에 적힌 탭만 닫기 때문이다 — 그 목록에는 우리가 `_new_page`·`_goto_checked` 로
          만든 탭만 들어간다. **사이트가 스스로 띄운 탭**(`target="_blank"` 링크, 상세 팝업)은
          아무도 안 적어서 상한을 넘어도 그대로 남았다. 상한이 있는데 분모가 비어 있던 것이다.

          그렇다고 창의 탭을 전부 우리 것으로 세면 안 된다 — 사람이 이 프로필에서 직접
          로그인해 둔 탭(네이버 「로그인 상태 유지」)을 치우게 된다. 그래서 **시점**으로 가른다:
          우리 동작이 도는 중에 생긴 탭은 우리가 띄운 것이고, 우리가 쉬는 동안 생긴 탭은
          사람이 띄운 것이다.
        """
        if self._action_depth <= 0:
            return
        self._claim_page(page)

    def _prune_tabs(self) -> int:
        """다 본 탭을 닫는다 — **오래된 것부터**, 지금 보는 탭은 남긴다.

        2026-09-16 사용자 지적 두 번: 조사 몇 판을 돌리면 탭이 18~26장이 된다.

        ## 누구 탭인가 — 세 번 틀리고 실측이 고른 규칙

        처음엔 「우리가 `_new_page`·`_goto_checked` 로 만진 탭만」이었다. 상한 6 인데 26장이
        남았고, 눈금을 붙여 보니 `wanted_to_close: 0` 이었다. 빠져나간 길이 셋이었다:

        1. **사이트가 스스로 띄운 탭** (`target="_blank"`, 상세 팝업) — 아무도 안 적었다.
        2. `context.on("page")` 로 「우리 동작 중에 생긴 탭」을 잡으려 했더니 **24장 중 2장**만
           잡혔다. Playwright 동기 API 는 이벤트를 다음 호출 때 펌프하므로, 콜백이 도는
           시점엔 동작이 이미 끝나 있다(`_action_depth == 0`).
        3. 기동 때 있던 탭을 적게 했더니 **3장**만 적혔다. 크롬을 강제 종료하면 다음 기동 때
           **세션 복원**으로 무더기가 되살아나는데, 우리가 붙는 순간엔 복원이 아직 안 끝나
           몇 장만 보인다. 나머지는 위 2번 길로 와서 또 빠진다.

        그래서 **우리가 띄운 크롬(`launched`·`spawned`)의 탭은 우리 것**으로 본다. 시점이나
        경로로 가르려는 시도는 세 번 다 구멍이 났다 — 그 창은 우리가 띄웠고 우리 프로필이다.

        ## 남기는 것

        - **지금 보는 탭**은 안 닫는다(일하던 자리다).
        - **붙어 쓰는 크롬(attached)** 은 사람의 창이므로 예전 규칙대로 **우리가 적은 탭만** 닫는다.
        - 그 프로필에서 사람이 직접 로그인해 둔 탭은 닫힐 수 있다. 다만 **로그인 자체는
          프로필(쿠키)에 남으므로** 다시 열면 그대로다 — 잃는 것은 창 하나다.
        """
        cap = int(getattr(self.config, "browser_max_tabs", 6) or 0)
        if self._context is None:
            return 0
        try:
            pages = [page for page in self._context.pages if not page.is_closed()]
        except Exception:  # noqa: BLE001
            return 0
        # ★ 재는 것은 상한과 상관없이 한다. 상한이 0(정리 끔)일 때도 몇 장인지는 보여야 한다 —
        #   눈금을 기능 안쪽에 두면 기능을 끄는 순간 눈이 같이 감긴다.
        ours_is_all = self._browser_is_ours()
        self._tab_census.update({"tabs": len(pages), "at": time.time(),
                                 "ours": len(pages) if ours_is_all else len(self._our_pages)})
        if cap <= 0 or len(pages) <= cap:
            return 0
        current = self._page
        if ours_is_all:
            # `context.pages` 는 만들어진 순서다 — 그대로가 「오래된 것부터」다.
            mine = [page for page in pages if page is not current]
        else:
            order = {key: index for index, key in enumerate(self._our_pages)}
            mine = sorted(
                (page for page in pages if page is not current and id(page) in order),
                key=lambda page: order[id(page)],
            )
        closed = 0
        refused = 0
        wanted = mine[: len(pages) - cap]
        for page in wanted:
            try:
                page.close()
                closed += 1
            except Exception:  # noqa: BLE001
                refused += 1
                continue
        # 「닫을 것이 없었다」와 「닫으려 했는데 못 했다」는 다른 말이다.
        self._tab_census["wanted_to_close"] = len(wanted)
        self._tab_census["refused_to_close"] = refused
        self._tab_census["tabs"] = len(pages) - closed
        self._tab_census["closed_total"] = int(self._tab_census.get("closed_total", 0)) + closed
        return closed

    def _goto_checked(self, page: Any, url: str) -> None:
        self._claim_page(page)
        """이동하고, 문전박대면 몇 번 더 해 보고, 그래도 막히면 **막혔다고 한다.**

        막힌 화면에서 사람이 새로고침을 누르는 것과 같은 일이다. 다만 횟수를 묶는다
        (`_EDGE_BLOCK_ATTEMPTS`) — 열릴 때까지 두드리는 것은 우회이고, 그건 감추기·
        UA 위조·캡차 풀기와 같은 줄에 있다.

        그리고 못 들어갔으면 예외로 올린다. 이 화면을 본문으로 읽는 것이 제일 나쁘다:
        2026-08-11 실측에서 자비스는 쿠팡에 발도 안 들이고 "쿠팡에서 구매 가능한…"
        으로 시작하는 표를 냈다.
        """
        marker = ""
        for attempt in range(_EDGE_BLOCK_ATTEMPTS):
            if attempt:
                index = min(attempt - 1, len(_EDGE_BLOCK_BACKOFF_SEC) - 1)
                time.sleep(_EDGE_BLOCK_BACKOFF_SEC[index])
            response = self._goto_page(page, url, wait_until="domcontentloaded")
            # ★ **없는 페이지는 「열었다」가 아니다** (2026-10-04 허깅페이스 판 56247177). 모델이 기억으로 지어낸
            #   `huggingface.co/Qwen/Qwen3-32B-A3B-Instruct`(없는 모델)를 열었고, 404 화면인데 도구는 OK 를 돌려줬다.
            #   모델은 그 이름이 있는 줄 알고 같은 이름을 다섯 번 더 검색했다(20걸음 중 14걸음). 없는 사이트(DNS)는
            #   8월에 막았는데 **사이트는 있고 페이지가 없는** 경우가 비어 있었다 — 같은 종류다: 모르는 것을 안다고 했다.
            missing = self._not_found_page(page, response)
            if missing:
                raise RuntimeError(
                    f"page_not_found:{urlparse(url).netloc}{urlparse(url).path[:120]} — 그런 페이지는 없습니다"
                    f"(HTTP {missing}). 주소나 이름을 짐작해서 만들지 마세요. 그 사이트의 목록·검색 결과에 **실제로 나온 링크**로 "
                    "여세요(browser_links · browser_open_result). 이름이 기억과 다를 수 있습니다 — 목록에 적힌 이름이 맞는 이름입니다."
                )
            # ★ **거절당한 주소도 「열었다」가 아니다** (2026-10-05 9B 허깅페이스 판 ef1e8e25). 모델이 주소에 인자를 지어 붙였고
            #   (`/models?sort=trending&direction=desc`) 사이트는 400 화면(「Invalid input … at direction」)을 줬는데 도구는 OK 에
            #   「이 사이트에는 검색칸이 있다」는 안내까지 붙였다. 모델은 오류 화면인 줄 모르고 「목록이 덜 불러와졌나」 하며
            #   스크롤·재검색을 열일곱 걸음 했다. 화면이 한 말을 그대로 전한다 — 무엇이 틀렸는지는 사이트가 제일 잘 안다.
            rejected = self._rejected_address(page, response)
            if rejected:
                raise RuntimeError(
                    f"address_rejected:{urlparse(url).netloc}{urlparse(url).path[:120]} — 이 사이트가 그 주소를 거절했습니다"
                    f"(HTTP {rejected[0]}). 화면이 말한 것: 「{rejected[1]}」. 목록이 아니라 오류 화면입니다 — 스크롤하거나 다시 열어도 같습니다. "
                    "주소에 인자를 짐작해서 붙이지 마세요. 인자(? 뒤)를 뺀 주소로 열거나, 그 사이트 화면의 정렬·필터·검색칸을 쓰세요."
                )
            # ★ 점검 중이면 **다시 해 보지 않는다** (2026-09-10). 두드려도 열리지
            #   않는 종류라, 세 번 시도는 3초와 걸음 셋을 버리고 끝에 가서
            #   「막혔다」라는 **틀린 이유**를 말하게 된다.
            down = self._under_maintenance(page)
            if down:
                host = urlparse(url).netloc or url
                raise RuntimeError(
                    f"site_under_maintenance:{host} — 이 사이트는 지금 점검 중이거나"
                    f" 일시 오류 상태입니다(화면 문구: '{down}'). 다시 열어도 같습니다."
                    " 안의 내용을 짐작해서 말하지 말고, **다른 출처로 넘어가세요.**"
                )
            marker = self._edge_blocked(page)
            if not marker:
                return
        host = urlparse(url).netloc or url
        raise RuntimeError(
            f"site_blocked:{host} — 이 사이트가 문전에서 되돌려보냈습니다"
            f"(화면 문구: '{marker}', {_EDGE_BLOCK_ATTEMPTS}번 시도). 들어가지 못했으니"
            " 그 안의 내용을 짐작해서 말하지 마세요. 막혔다고 말하고, 다른 출처로 가세요."
        )

    #: 없는 페이지 화면에 적히는 말. 상태 코드만 믿지 않는다 — 404 로 답하면서 제대로 그리는 사이트가 있다
    #: (깃허브 페이지에 올린 한 장짜리 앱이 그렇게 한다). 둘 다 맞을 때만 「없다」고 한다.
    _NOT_FOUND_WORDS = re.compile(
        r"404|not\s*found|doesn[’']?t\s*exist|does\s*not\s*exist|no\s*longer\s*available|nothing\s*here"
        r"|찾을\s*수\s*없|존재하지\s*않|없는\s*페이지|삭제된\s*(?:페이지|게시)",
        re.IGNORECASE,
    )

    def _not_found_page(self, page: Any, response: Any) -> int:
        """서버가 404·410 으로 답했고 화면도 「없다」고 하면 그 상태 코드. 아니면 0."""
        try:
            status = int(getattr(response, "status", 0) or 0)
        except (TypeError, ValueError):
            return 0
        if status not in (404, 410):
            return 0
        try:
            seen = str(page.title() or "") + " " + str(
                page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 800)") or ""
            )
        except Exception:  # noqa: BLE001 — 화면을 못 읽으면 판정하지 않는다(막는 쪽으로 넘어지지 않는다)
            return 0
        return status if self._NOT_FOUND_WORDS.search(seen) else 0

    #: 오류 화면은 짧다 — 이보다 길면 내용이 있는 화면으로 보고 건드리지 않는다(상태 코드만 400 인 사이트가 있다).
    _REJECTED_PAGE_MAX_CHARS = 1500

    def _rejected_address(self, page: Any, response: Any) -> tuple[int, str] | None:
        """서버가 「그 요청은 못 받는다」(400·422)로 답했고 화면이 짧은 오류 글이면 (상태, 화면이 한 말). 아니면 `None`."""
        try:
            status = int(getattr(response, "status", 0) or 0)
        except (TypeError, ValueError):
            return None
        if status not in (400, 422):
            return None
        try:
            body = str(page.evaluate(
                "(cap) => (document.querySelector('main') || document.body || {innerText: ''}).innerText.slice(0, cap)",
                self._REJECTED_PAGE_MAX_CHARS + 1) or "")
        except Exception:  # noqa: BLE001 — 화면을 못 읽으면 판정하지 않는다(막는 쪽으로 넘어지지 않는다)
            return None
        if len(body) > self._REJECTED_PAGE_MAX_CHARS:
            return None
        said = " ".join(body.split())[:200]
        return status, said or "(글 없음)"

    def _follow_js_link(self, page: Any, link: str) -> dict[str, Any]:
        """`javascript:go_view(178802)` 같은 링크를 **그 페이지의 함수로** 따라간다 (2026-10-02 대표 운영 판).

        K-Startup 목록의 공고 링크는 주소가 아니라 `javascript:go_view(N)` 이다. 그걸 browser_open 에 넘기면
        `https://` 가 붙어 엉뚱한 주소가 됐고, 누르면 겹친 회전판에 클릭이 막혔다. 모델은 번호를 보고 상세 주소를
        **짐작**했는데(`bizpbanc-view.do?id=N`) 그 모양은 본문이 빈 껍데기라 열 걸음을 헛돌다 판이 접혔다.
        진짜 주소는 그 함수가 알고 있다 — 사이트가 쓰는 길을 그대로 타고, 도착한 주소를 알려 주고 기억한다.

        이동처럼 보이는 함수 이름(view·detail·go·move·open·link …)에 숫자·글자 인자만 있을 때만 대신 부른다.
        지우기·제출·결제·로그아웃 같은 이름은 부르지 않는다 — 그건 사람이 보는 클릭(승인 규칙)으로 간다.
        """
        match = _JS_LINK.match(link or "")
        args = _js_literal_args(match.group(2)) if match else None
        name = match.group(1) if match else ""
        if match is None or args is None:
            raise RuntimeError(
                "js_link_unsupported — 이 javascript: 링크는 단순한 함수 호출 모양이 아니라 대신 따라가지 않는다. "
                "그 링크를 화면에서 browser_click 으로 누르세요."
            )
        if not _JS_LINK_NAVIGATES.search(name) or _JS_LINK_ACTS.search(name):
            raise RuntimeError(
                f"js_link_not_followed:{name} — 이동 함수로 보이지 않아 대신 실행하지 않는다. "
                "그 링크를 화면에서 browser_click 으로 누르세요."
            )
        try:
            exists = bool(page.evaluate("(n) => typeof window[n] === 'function'", name))
        except Exception:
            exists = False
        if not exists:
            raise RuntimeError(
                f"js_link_function_missing:{name} — 지금 페이지에는 그 함수가 없다. "
                "그 링크가 있던 목록 페이지를 먼저 열고 거기서 다시 browser_open 하세요."
            )
        before = str(page.url or "")
        known = list(self._context.pages) if self._context is not None else []
        try:
            with page.expect_navigation(timeout=12000):
                page.evaluate("([n, a]) => { window[n](...a); }", [name, args])
        except Exception:
            pass  # 새 창으로 열리거나 같은 주소의 화면만 바뀌는 사이트 — 아래에서 가른다.
        opened = self._adopt_new_window(known, wait_ms=1500)
        target = self._page if opened else page
        ready = self._wait_until_operable(target)
        after = str(getattr(target, "url", "") or "")
        moved = after and after != before
        pattern = _route_pattern(after, args) if moved else ""
        if pattern:
            self._note_trait(target, "js_link_route", f"{name}→{pattern}")
        if moved and pattern:
            note = (
                f"javascript:{name}(…) 를 그 페이지의 함수로 따라갔다 → 실제 주소 {after}. "
                f"같은 목록의 다른 항목은 이 주소 모양({pattern})에 번호만 바꿔 browser_open 하면 된다 — 번호로 주소를 짐작하지 마라."
            )
        elif moved:
            note = (
                f"javascript:{name}(…) 를 따라갔다 → {after}. 주소에 번호가 안 나온다 — "
                f"다른 항목도 javascript:{name}(번호) 그대로 browser_open 하라."
            )
        else:
            note = (
                f"javascript:{name}(…) 를 불렀는데 주소가 그대로다 — 같은 화면 안에서 내용이 바뀌었을 수 있다. "
                "browser_read 로 지금 화면을 읽어 확인하라."
            )
        if after:
            self._mark_visited(after)
        return self._evidence(
            "opened", followed_js_link=name, element_count=ready["count"], ready_ms=ready["ms"],
            ready_polls=ready["polls"], instruction=note,
        )

    def _open(self, page: Any, arguments: dict[str, Any], *, trusted: bool = False) -> dict[str, Any]:
        """`trusted` 는 **인자가 아니라 매개변수**다 — `_click(approved=...)` 과 같은 이유.

        사람이 검토한 레시피만 `browser_open_reviewed` 문으로 들어와 이걸 켠다.
        모델이 `{"trusted": true}` 를 얹어도 여기까지 오지 않는다.
        """
        raw = str(arguments.get("url") or "").strip()
        if raw.lower().startswith("javascript:"):
            return self._follow_js_link(page, raw)
        url = self._validate_url(raw)
        if not trusted:
            # 여러 항목을 쌓아 보여 주는 주소면 그 항목 하나만 보는 주소로 연다(`single_item_view` 주석). 검토된 절차의 주소는 그대로.
            url = single_item_view(url)
        # ★ 검색 주소를 조립해 왔으면 **사람 방식으로 먼저 해 본다** (2026-08-13).
        #   단, 검토된 절차의 주소는 손대지 않는다 — 그건 지어낸 것이 아니다.
        self._doing = "open:search_like_a_person"
        handed = None if trusted else self._search_like_a_person(page, url)
        if handed is not None:
            return handed
        # ★ 글 번호를 지어낸 주소면, **지금 보는 목록에 있는 같은 제목의 진짜 주소**로 바꿔 연다 (`real_link_for` 주석).
        #   엉뚱한 글(운영 기록에서는 성인 게시판)을 한 번도 띄우지 않고 간다. 못 찾으면 그대로 가고, 가서 틀리면
        #   아래 `wrong_item_redirect` 가 되돌린다.
        self._doing = "open:listed_address"
        repaired = "" if trusted else self._listed_address_for(page, url)
        asked_url = url
        if repaired:
            url = repaired
        rewrite: DateRewrite | None = None
        try:
            self._doing = "open:goto"
            rewrite = self._goto_with_dates(page, url)
        except Exception as exc:
            # ★ 없는 주소로 갔다 = 주소를 **지어냈다.**
            #
            # 2026-08-09 실측: 크몽 공고를 보라고 했더니 `www.kmon.co.kr` 로 갔다.
            # 크몽은 `kmong.com` 이다. 그리고 이 실패를 받아 든 모델은 사이트를
            # 다시 찾는 대신 네이버 검색으로 되돌아갔고, 공고는 한 건도 못 열고
            # 블로그 두 개를 읽어 "예산 15만~30만원" 같은 숫자를 냈다.
            #
            # DNS 실패는 페이지 문제가 아니라 **모르는 것을 안다고 한 것**이다.
            # 그러니 여기서 회복할 길을 알려 준다 — 셀렉터를 지어내지 말라는 것과
            # 같은 규칙이고, 주소도 똑같이 지어내면 안 되는 지식이다.
            if _UNRESOLVED_HOST.search(str(exc)):
                host = urlparse(url).netloc or url
                raise RuntimeError(
                    f"host_does_not_exist:{host} — 그런 주소는 없습니다. 주소를 짐작해서 "
                    "만들지 마세요. browser_search 로 그 서비스의 **공식 사이트**를 먼저 찾고, "
                    "검색 결과에 나온 주소를 browser_open_result 로 여세요."
                ) from exc
            raise
        # ★ 번호는 맞는데 **다른 글**로 갔다 = 글 번호를 지어냈다 (2026-10-04, `wrong_item_redirect` 주석).
        #   「열었다」고 돌려주면 그 걸음이 읽은 글로 세어지고, 엉뚱한 페이지(성인 게시판이었다)가 사용자 크롬에 남는다.
        #   앞 페이지로 돌아가고 실패로 알린다 — 없는 주소(`host_does_not_exist`)와 같은 종류다: 모르는 것을 안다고 했다.
        wrong = None if trusted else wrong_item_redirect(url, str(getattr(page, "url", "") or ""))
        if wrong:
            self._leave_wrong_page(page)
            raise RuntimeError(
                f"address_leads_to_another_post:{wrong['id']} — 이 주소의 글 번호는 **다른 글**로 갑니다(제목과 번호가 안 맞습니다). "
                "번호를 짐작해서 주소를 만들지 마세요. 목록·검색 결과 페이지에서 browser_links 로 실제 주소를 받아 "
                "그대로 여세요. 엉뚱한 페이지는 닫고 앞 페이지로 돌아갔습니다."
            )
        self._doing = "open:wait_until_operable"
        ready = self._wait_until_operable(page)
        self._mark_visited(url)
        # 몇 개가 잡혔는지 증거에 남긴다. 0이면 정말로 조작할 게 없는 페이지이거나
        # (오류·차단 화면) 기다려도 안 그려진 것이고, 둘 다 사람이 알아야 한다.
        self._doing = "open:site_search_offer"
        offer = self._handmade_search_note(url) or self._site_search_offer(page)
        self._doing = "open:evidence"
        marks = self._date_rewrite_evidence(rewrite)
        if repaired:
            marks["address_repaired"] = {"asked": asked_url[:200], "opened": repaired[:200]}
            offer = (ADDRESS_REPAIRED_NOTE + " " + (offer or "")).strip()
        moved = locale_redirect(url, str(getattr(page, "url", "") or ""))
        if moved:
            marks["locale_redirect"] = moved
            offer = (LOCALE_REDIRECT_NOTE.format(**moved) + " " + (offer or "")).strip()
        # ★ 이 PC 안에서 띄운 페이지(우리가 만든 것)는 열 때마다 **화면을 계산으로 잰다** (2026-10-11 · `layout_probe`).
        #   글자를 다른 것이 덮었나 · 가로로 삐져나갔나 · 그림이 깨졌나. 글자로 읽어서는 안 보이는 결함이다 — 쇼핑몰 판에서
        #   품절 막이 첫 화면 전체를 덮었는데 손자리는 읽고 누르기만 해서 몰랐다. 걸리면 그 말을 맨 앞에 세운다.
        self._doing = "open:layout_check"
        layout_lines = self._layout_check(page)
        if layout_lines:
            marks["layout_issues"] = layout_lines
        # ★ 그리고 **눈으로 본다** (2026-10-11 · `page_look`). 계산으로 안 잡히는 것(흐린 글자 · 어색한 자리)을 위해
        #   화면 없는 크롬으로 따로 통째로 찍어 모델에게 보여 준다. 인상이라 틀릴 수 있다는 딱지를 붙여서, 계산 검사 뒤에 둔다.
        self._doing = "open:page_look"
        looked = self._look_at_local_page(page)
        if looked:
            marks["looked"] = looked
        # 날짜를 바꿨으면 그 말을 **앞에** 세운다. 뒤에 붙이면 긴 결과 JSON 안에
        # 묻히고, 묻힌 지시는 없는 지시다(이 파일이 두 번 확인한 자리다).
        note = " ".join(filter(None, [
            _layout_probe.layout_note(layout_lines), _page_look.look_note(looked),
            marks.pop("date_instruction", ""), offer.strip() if offer else "",
        ]))
        return self._evidence(
            "opened",
            element_count=ready["count"],
            ready_ms=ready["ms"],
            ready_polls=ready["polls"],
            **marks,
            **({"instruction": note} if note else {}),
        )

    def _layout_check(self, page: Any) -> list[str]:
        """이 PC 안 페이지의 화면을 재서 문제를 줄로 돌려준다. 남의 사이트이거나 재다 틀어지면 빈 목록."""
        try:
            if not _layout_probe.is_local_page(str(getattr(page, "url", "") or "")):
                return []
            return _layout_probe.layout_issues(page.evaluate(_layout_probe.LAYOUT_PROBE_JS, _layout_probe.MAX_SCREENS))
        except Exception:  # noqa: BLE001 — 검사가 페이지 열기를 실패로 만들면 안 된다
            return []

    def _look_at_local_page(self, page: Any) -> str:
        """이 PC 안 페이지를 따로 찍어 모델의 눈으로 본 말을 돌려준다. 눈이 없거나(런타임이 안 걸었다) 틀어지면 빈 글.

        보는 동안 화면의 「지금 보는 그림」 카드에 그 그림을 비춘다(`image_read_sink` — 그림 속 글자를 읽을 때와 같은 통로).
        """
        eye = getattr(self, "page_eye", None)
        if eye is None or self._playwright is None or self._cannot_read_pictures():
            return ""
        try:
            url = str(getattr(page, "url", "") or "")
            if not _layout_probe.is_local_page(url):
                return ""
            shot = _page_look.render_apart(self._playwright, self._find_chrome(), url)
            picture, width, height = _page_look.shrink_for_eyes(shot) if shot else (b"", 0, 0)
            if not picture:
                return ""
        except Exception:  # noqa: BLE001 — 보기가 페이지 열기를 실패로 만들면 안 된다
            return ""
        sink = getattr(self, "image_read_sink", None)
        told = False
        if sink is not None:
            try:
                from PIL import Image as _Image
                import io as _io

                told = self._tell_image_read(
                    lambda info: sink({**info, "kind": "page"}), _Image.open(_io.BytesIO(picture)),
                    image=1, images=1, tile=1, tiles=1,
                )
            except Exception:  # noqa: BLE001
                told = False
        try:
            said = str(eye(picture) or "").strip()
        except Exception:  # noqa: BLE001 — 눈이 없는 모델 · 서버가 바쁜 때
            said = ""
        if told:
            try:
                sink({"done": True})
            except Exception:  # noqa: BLE001
                pass
        return "" if _page_look.saw_nothing(said) else said

    def _listed_address_for(self, page: Any, url: str) -> str:
        """조립한 글 주소 대신 열, 지금 페이지의 링크. 글 주소 모양이 아니면 페이지를 건드리지 않는다."""
        if _item_and_title(url) is None:
            return ""
        links: list[str] = []
        try:
            for frame in self._frames_of(page):
                try:
                    rows = frame.evaluate(_COLLECT_LINKS_JS)
                except Exception:  # noqa: BLE001 — 한 프레임이 안 읽혀도 나머지는 본다
                    continue
                links.extend(unwrap_redirect(str(row.get("href") or "")) for row in rows or [])
        except Exception:  # noqa: BLE001 — 못 찾으면 원래 주소로 간다
            return ""
        real = real_link_for(url, links)
        if not real:
            return ""
        try:
            return self._validate_url(real)
        except Exception:  # noqa: BLE001 — 허용 안 되는 주소면 바꾸지 않는다
            return ""

    @staticmethod
    def _leave_wrong_page(page: Any) -> None:
        """엉뚱한 글에 도착했을 때 그 페이지를 화면에 남기지 않는다 — 앞 페이지로, 안 되면 빈 페이지로."""
        try:
            if page.go_back(wait_until="domcontentloaded", timeout=8000) is not None:
                return
        except Exception:  # noqa: BLE001 — 돌아가기가 안 되면 아래에서 비운다
            pass
        try:
            page.goto("about:blank", wait_until="domcontentloaded", timeout=8000)
        except Exception:  # noqa: BLE001 — 비우기까지 안 되면 실패 보고만 한다
            pass

    # 손으로 조립한 **사이트 검색 주소**. `?stext=`·`?q=`·`/search?...` 같은 모양.
    _HANDMADE_SEARCH = re.compile(
        r"[?&](q|query|stext|keyword|kw|searchword|search_word|term|k1)=", re.IGNORECASE
    )
    # 검색 **입구**임을 말해 주는 경로 조각. 상세 페이지와 가르는 기준이다 —
    # 잡코리아 공고 상세는 주소에 `stext=` 를 달고 다니지만 경로는 `/Recruit/GI_Read/…`
    # 라서 여기 안 걸린다. 그 구분이 없으면 멀쩡한 상세 이동까지 가로챈다.
    _SEARCH_ENTRY_PATH = re.compile(r"(^|/)[a-z_]*search", re.IGNORECASE)
    _SEARCH_ENGINE_HOSTS = ("search.naver.com", "google.com", "bing.com", "search.daum.net")

    _QUERY_KEYS = ("q", "query", "stext", "keyword", "kw", "searchword", "search_word", "term", "k1")

    def _handmade_search_query(self, url: str) -> str:
        """이 주소가 **손으로 만든 사이트 검색 입구**면 그 검색어. 아니면 빈 문자열."""
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if not host or any(engine in host for engine in self._SEARCH_ENGINE_HOSTS):
            return ""
        # 경로에 검색 입구 표시가 있거나, 호스트 자체가 검색 서브도메인일 때만.
        if not self._SEARCH_ENTRY_PATH.search(parsed.path or "") and not host.startswith("search."):
            return ""
        params = parse_qs(parsed.query or "")
        for key in self._QUERY_KEYS:
            for name, values in params.items():
                if name.lower() == key and values and str(values[0]).strip():
                    return str(values[0]).strip()[:300]
        # ★ 이름이 아홉 개 밖이어도 **「검색어」를 뜻하는 이름**이면 그 값이다 (2026-10-13 가격 조사 판 · 9B).
        #   검색 엔진이 막히자 모델이 가게 검색 주소를 지어 왔다 — `SearchResult.aspx?SearchKey=` · `/search/keyword/<검색어>`.
        #   그물이 못 알아봐 「대신 검색칸에 치기」가 안 돌았고, 결과 목록이 아닌 화면에서 순위를 불러 `stale_result_list` 로
        #   그 가게를 놓쳤다. 운영 기록의 주소 열기 3,592번에 나란히 대 봄: 옛 그물 252번은 그대로, 새로 36번.
        #   값이 낱말이 아니면(필터 묶음을 통째로 실은 `searchQuery={"…"}`) 받지 않는다 — 그것을 검색칸에 칠 수는 없다.
        for name, values in params.items():
            value = str(values[0]).strip() if values else ""
            if value and _SEARCH_WORD_PARAM.match(name) and len(value) <= 120 and not re.search(r"[{}\[\]=<>]", value):
                return value
        # 검색어를 **경로에** 실은 꼴. 인자가 하나도 없고, 그 조각이 낱말 여럿이거나 한글일 때만 —
        # `/search/recruit` 같은 길 이름은 한 낱말짜리 영문이라 검색어와 가를 수 없으니 건드리지 않는다.
        if not params:
            carried = _SEARCH_WORD_IN_PATH.search(parsed.path or "")
            words = unquote(carried.group(1)).replace("+", " ").strip() if carried else ""
            if words and (" " in words or re.search(r"[가-힣]", words)):
                return words[:300]
        return ""

    def _search_like_a_person(self, page: Any, url: str) -> dict[str, Any] | None:
        """검색 주소를 조립해 왔으면 **칸에 쳐서** 한다. 해당 없으면 None.

        ## 왜 안내가 아니라 도구가 하는가

        여기엔 원래 `_handmade_search_note` 라는 **안내문**이 있었다("다음부터는
        browser_site_search 를 써라"). 실측(2026-08-13, 오늘 잡 260건):

            browser_open 74 회 중 검색어가 주소에 박힌 것 **12 회**

        안내는 안 먹었다. 이 저장소가 오늘만 세 번 확인한 것과 같다 — 결정론으로
        박을 수 있는 것은 코드로 해야 한다.

        ## 왜 이게 실제로 위험한가 (안 통해서가 아니다)

        같은 날 실측에서 모델이 만든 주소가 이랬다:

            search.danawa.com/dsearch/main?tab=shopping&query=%EB%AC%B4%EC%84%A7…
                                                              ^^^^ = "무섧마우스"

        **퍼센트 인코딩을 손으로 쓰다 한 글자를 틀렸다.** 사람이 검색칸에 치면
        절대 안 나오는 오타다. 그리고 이런 주소는 404 가 아니라 **빈 목록**으로
        조용히 돌아온다 — "그 사이트엔 그런 게 없네요"가 되는 것이다.
        경로도 마찬가지다(`dsearch?q=` 는 진짜 `dsearch.php?query=` 가 아니다).

        ## 하이브리드 — 사람 방식이 먼저, 주소는 폴백

        막기만 하면 검색칸을 못 찾는 사이트에서 길이 끊긴다. 그래서 도구가 대신 한다:
        그 사이트로 들어가 **검색칸을 눌러 커서를 놓고 쳐 넣고 Enter.**
        칸을 못 찾으면 그때 원래 주소로 간다(그리고 그 사실을 결과에 적는다).
        """
        query = self._handmade_search_query(url)
        if not query:
            return None
        parsed = urlparse(url)
        home = f"{parsed.scheme or 'https'}://{parsed.netloc}/"
        try:
            self._goto_checked(page, home)
            self._wait_until_operable(page)
            result = self._site_search(page, {"query": query})
        except Exception as exc:
            # 사람 방식이 안 되는 화면이다. 원래 하려던 대로 가되 **감추지 않는다.**
            self._goto_checked(page, url)
            ready = self._wait_until_operable(page)
            self._mark_visited(url)
            return self._evidence(
                "opened",
                element_count=ready["count"],
                ready_ms=ready["ms"],
                ready_polls=ready["polls"],
                typed_search=False,
                instruction=(
                    f"★ 검색칸에 직접 쳐 넣으려 했으나 실패해서({str(exc)[:80]}) "
                    "네가 준 주소로 열었다. 이 주소는 네가 조립한 것이라 경로나 인코딩이 "
                    "틀리면 **빈 목록이 조용히** 나온다 — 결과가 0건이면 사이트에 없는 "
                    "것이 아니라 주소가 틀린 것일 수 있다."
                ),
            )
        result["typed_search"] = True
        result["instruction"] = (
            "★ 주소를 조립해서 부르길래 **그 사이트 검색칸에 직접 쳐 넣었다**"
            f"('{query}'). 앞으로도 검색은 browser_site_search 를 써라 — 손으로 만든 "
            "주소는 인코딩이나 경로가 틀리면 빈 목록으로 조용히 끝난다. "
            + str(result.get("instruction") or "")
        ).strip()
        return result

    def _handmade_search_note(self, url: str) -> str:
        """검색 주소를 **지어내서** 들어간 것을 알아보고, 제대로 된 길을 알려 준다.

        2026-08-12 실측: 자비스가 `jobkorea.co.kr/Search/?stext=광양사무직` 을 손으로
        만들어 열었다. 이번엔 주소가 맞아서 통했지만, 이게 크몽을 `kmon.co.kr` 로
        만들어 갔던 사고(`host_does_not_exist`)와 **같은 버릇**이다. 호스트를 틀리면
        DNS 에서 걸리지만 경로를 틀리면 404 나 빈 목록으로 조용히 끝난다.

        막지는 않는다. 사람이 검색 주소를 그대로 주는 멀쩡한 경우가 있고, 이번처럼
        통하기도 한다. 대신 **다음에 무엇을 쓰면 되는지**를 그 자리에서 준다 —
        오늘 하루 배운 대로, 도구를 만들어 두는 것만으로는 안 쓰인다.
        """
        host = _host_of_url(url)
        if not host or any(engine in host for engine in self._SEARCH_ENGINE_HOSTS):
            return ""
        if not self._HANDMADE_SEARCH.search(url) and "/search" not in url.lower():
            return ""
        return (
            f" ★ 지금 연 주소는 네가 조립한 **{host} 의 검색 주소**다. 이번엔 통했더라도"
            " 경로를 틀리면 빈 목록이 조용히 나올 뿐이라 알아채지 못한다. 다음부터는"
            " 그 사이트에 들어간 뒤 browser_site_search 를 써라 — 그러면 목록에 순위가"
            " 매겨져서 browser_open_result 로 상세까지 바로 들어갈 수 있다."
        )

    # 지금 열린 사이트의 **자기 검색칸**. 사이트 목록으로 찾지 않는다 — 그 목록은
    # 끝이 없고 금방 낡는다. 검색칸이라고 알리는 **구조**로 찾는다.
    _SITE_SEARCH_JS = """
    () => {
      const vis = (el) => {
        if (!el.getClientRects().length) return false;
        const st = getComputedStyle(el);
        return st.visibility !== "hidden" && parseFloat(st.opacity) !== 0;
      };
      const word = /(search|query|keyword|kw|q$|검색|찾기)/i;
      const score = (el) => {
        let s = 0;
        const type = (el.getAttribute("type") || "").toLowerCase();
        const role = (el.getAttribute("role") || "").toLowerCase();
        if (type === "search") s += 6;
        if (role === "searchbox" || role === "combobox") s += 4;
        for (const attr of ["name", "id", "placeholder", "aria-label", "title", "class"]) {
          if (word.test(el.getAttribute(attr) || "")) { s += 3; break; }
        }
        if (el.closest("form[role=search], [role=search]")) s += 3;
        // 화면 위쪽·넓은 칸이 그 사이트의 주 검색칸이다. 댓글칸·구독칸이 아니라.
        const box = el.getBoundingClientRect();
        if (box.width >= 120) s += 2;
        if (box.top < 400) s += 2;
        return s;
      };
      // ★ **입력 폼의 칸은 사이트 검색칸이 아니다** (2026-10-07 대표 실사용). 이력서 수정 화면에서 회사 이름을 검색하려던
      //   호출이 고등학교 이름 칸(`HighSchool_Schl_Name_Search` — 이름에 search, 넓고, 위쪽: 7점)에 그 이름을 쳐 넣었다.
      //   사람이 값을 적는 폼(글 칸이 여럿)의 칸은, 스스로 검색칸이라고 밝힌 것(type=search · role · 머리/내비 안)만 후보다.
      const TEXTLIKE = "input[type=text], input:not([type]), textarea";
      const pageIsForm = document.querySelectorAll(TEXTLIKE).length >= 12;
      const declared = (el) => {
        const type = (el.getAttribute("type") || "").toLowerCase();
        const role = (el.getAttribute("role") || "").toLowerCase();
        return type === "search" || role === "searchbox" || !!el.closest("[role=search], header, nav");
      };
      const inEntryForm = (el) => {
        if (declared(el)) return false;
        if (pageIsForm) return true;
        const form = el.closest("form") || el.closest("fieldset");
        return !!form && form.querySelectorAll(TEXTLIKE).length >= 4;
      };
      const inputs = Array.from(
        document.querySelectorAll("input[type=search], input[type=text], input:not([type]), [role=searchbox], [role=combobox][contenteditable=true]")
      ).filter((el) => vis(el) && !el.disabled && !el.readOnly && !inEntryForm(el));
      let best = null, bestScore = 0;
      for (const el of inputs) {
        const s = score(el);
        if (s > bestScore) { best = el; bestScore = s; }
      }
      if (!best || bestScore < 5) return null;
      best.setAttribute("data-jarvis-sitesearch", "1");
      return {
        score: bestScore,
        name: (best.getAttribute("placeholder") || best.getAttribute("aria-label") ||
               best.getAttribute("name") || best.getAttribute("id") || "").slice(0, 80),
        tag: best.tagName.toLowerCase(),
      };
    }
    """

    # 접힌 검색칸을 펴는 손잡이(돋보기). 글자가 없는 아이콘인 경우가 대부분이라
    # 사이트가 붙인 이름(aria-label·title)으로 찾는다 — 팝업 X 닫기와 같은 규칙이다.
    _OPEN_SEARCH_JS = r"""
    () => {
      const vis = (el) => {
        const r = el.getBoundingClientRect();
        if (r.width <= 1 || r.height <= 1) return false;
        const s = getComputedStyle(el);
        return s.visibility !== 'hidden' && s.display !== 'none';
      };
      const word = /(검색|찾기|search)/i;
      const candidates = document.querySelectorAll(
        "button, a[role=button], [role=button], [role=search] *, [class*='search'], [class*='Search']"
      );
      for (const el of candidates) {
        if (!vis(el)) continue;
        const name = (el.getAttribute('aria-label') || el.getAttribute('title') ||
                      el.innerText || el.className || '').toString();
        if (!word.test(name)) continue;
        const box = el.getBoundingClientRect();
        // 돋보기는 작다. 큰 덩어리(검색 영역 전체)를 누르면 엉뚱한 데로 간다.
        if (box.width > 200 || box.height > 120) continue;
        el.setAttribute('data-jarvis-searchopen', '1');
        return (el.getAttribute('aria-label') || el.getAttribute('title') || '').slice(0, 40) || '검색';
      }
      return null;
    }
    """
    _SITE_SEARCH_JS = _deep_js(_SITE_SEARCH_JS)
    _OPEN_SEARCH_JS = _deep_js(_OPEN_SEARCH_JS)

    def _open_search_box(self, page: Any) -> bool:
        """접힌 검색칸을 펴 본다. 폈으면 True."""
        try:
            found = page.evaluate(self._OPEN_SEARCH_JS)
        except Exception:
            return False
        if not found:
            return False
        try:
            page.locator("[data-jarvis-searchopen='1']").first.click(timeout=3000)
            return True
        except Exception:
            return False
        finally:
            try:
                page.evaluate(
                    _deep_js("() => { document.querySelectorAll('[data-jarvis-searchopen]')"
                    ".forEach((el) => el.removeAttribute('data-jarvis-searchopen')); }")
                )
            except Exception:
                pass

    def _site_search_offer(self, page: Any) -> str:
        """지금 선 화면에 **그 사이트의 검색칸**이 있으면 그렇다고 알린다.

        ★ 도구를 만들어 놓는 것으로는 안 된다(2026-08-12 실측). `browser_site_search`
        를 붙인 첫 판에서 자비스는 그 도구를 **한 번도 부르지 않았다.** 잡코리아·
        findjob24h 에 들어가 놓고도 본문만 읽고 나왔다.

        쓸 수 있다는 사실을 **쓸 수 있는 그 순간에** 줘야 한다. 검색할 때 준 안내는
        결과를 열고 나면 이미 지나간 말이다 — 이 저장소가 여러 번 배운 것과 같다
        (지시는 결과 안쪽에 묻지 말고 그 자리에서 최상단에).

        남이 쓴 글(블로그·카페)에서는 알리지 않는다. 블로그에도 검색칸은 있지만
        거기서 찾는 것은 그 사람의 글이지 우리가 찾는 원문이 아니다. 잦은 안내는
        안 읽히는 안내다.
        """
        host = _host_of_url(str(getattr(page, "url", "") or ""))
        if not host or any(
            host.endswith(known) or host == known for known in self._SECONDHAND_HOSTS
        ):
            return ""
        try:
            found = page.evaluate(self._SITE_SEARCH_JS.replace('best.setAttribute("data-jarvis-sitesearch", "1");', ""))
        except Exception:
            return ""
        if not found:
            return ""
        return (
            f" ★ 이 사이트({host})에는 **자체 검색칸**이 있다"
            f"({str(found.get('name') or '')[:40]}). 지금 필요한 것이 최신 목록이라면"
            " browser_site_search 로 **이 사이트 안에서** 찾아라 — 검색엔진으로 돌아가"
            "사이트 이름을 낱말로 넣는 것보다 정확하고 최신이다."
        )

    #: 손으로 친 값을 검색어로 인정하는 시간. 이보다 오래되면 딴 칸에 친 것이다.
    _TYPED_TTL_SEC = 180.0

    def _remember_typed(self, value: str) -> None:
        """방금 입력칸에 넣은 값. **마지막 하나만** 들고 있는다."""
        text = str(value or "").strip()
        # 너무 짧으면 검색어로 보기 어렵고, 너무 길면 본문 붙여넣기다.
        if 1 < len(text) <= 120:
            self._typed_recently = (text, time.time())

    def _learn_search_url(self, page: Any, rows: int, query: str = "") -> None:
        """지금 화면이 목록이면 **그 주소를 배운다.** 실패해도 삼킨다.

        ## 왜 여러 자리에서 부르나 (2026-09-06 라이브가 가르쳐 준 것)

        처음엔 `browser_site_search` 성공 경로 **한 군데**에만 걸었다. 위시켓 판에서
        그 도구가 2 걸음에 `site_search_box_not_found` 로 죽었고, 모델은 `browser_fill`
        + `browser_press` 로 손수 검색해 결과까지 갔다 — **학습기는 한 번도 안 지났다.**

        오늘만 세 번째다(날짜 교체 두 문 → 세 문, 그리고 여기). 규칙은 하나다:
        **문에 걸지 말고, 결과가 나온 자리에 건다.**

        `query` 가 비면 방금 손으로 친 값을 쓴다. 그 값이 주소에 글자 그대로
        없으면 `template_from` 이 알아서 아무것도 안 배운다 — 여기서 판단하지 않는다.
        """
        if rows < SEARCH_ATLAS_MIN_ROWS:
            return
        text = str(query or "").strip()
        if not text:
            typed, at = self._typed_recently
            if typed and (time.time() - at) <= self._TYPED_TTL_SEC:
                text = typed
        if not text:
            return
        try:
            self._search_atlas.learn(str(getattr(page, "url", "") or ""), text, rows)
        except Exception:
            pass

    def _learned_search(self, page: Any, query: str) -> dict[str, Any] | None:
        """배운 주소로 바로 간다. 없거나 안 먹으면 **None** — 원래 길로 돌아간다.

        ## 계약

            표에 확인된 틀이 있다   →  그 주소로 이동
            결과가 3 건 이상        →  그대로 쓴다 (검색칸을 안 건드린다)
            결과가 모자라다         →  **틀을 버리고** None. 원래 길이 다시 배운다.
            무슨 일이든 터진다      →  None. 이 층은 거들 뿐이지 조건이 아니다.

        마지막 줄이 중요하다. 배운 것이 낡으면 조용히 빈 목록을 주는 게 아니라
        **스스로 물러난다.** 안 그러면 어제 맞던 주소 하나가 오늘 판을 죽인다.
        """
        current = str(getattr(page, "url", "") or "")
        target = ""
        try:
            target = self._search_atlas.url_for(current, query)
        except Exception:
            return None
        if not target or target == current:
            return None
        try:
            self._goto_checked(page, target)
            ready = self._wait_until_operable(page)
            date_fix = self._apply_requested_dates_here(page)
            results = self._results_once_drawn(page, limit=15)
        except Exception:
            return None
        if len(results) < SEARCH_ATLAS_MIN_ROWS:
            # 낡았다. 버리고 원래 길로 — 그 길이 새 주소를 다시 배운다.
            try:
                self._search_atlas.forget(current)
            except Exception:
                pass
            return None
        self._last_results = results
        self._remember_results_origin(page)
        self._reads_since_search = 0
        self._searched_before = True
        self._mark_visited(target)
        return self._evidence(
            "site_searched",
            **{
                key: value
                for key, value in self._date_rewrite_evidence(date_fix).items()
                if key != "date_instruction"
            },
            site=_host_of_url(target),
            query=query,
            strategy="learned_url",
            element_count=ready["count"],
            results=results,
            result_count=len(results),
            instruction=(
                (note + " " if (note := self._stay_note_for_list(page, applied=date_fix)) else "")
                + f"★ 앞서 이 사이트에서 통했던 주소로 바로 갔다({len(results)}건). "
                "검색칸을 찾을 필요가 없었다. **목록 줄에 보이는 값은 그대로 근거다** — "
                "제목·가격·평점처럼 이미 보이는 값은 상세를 안 열어도 답에 써라. "
                "목록에 없는 값이 필요할 때만 browser_open_result 에 rank 를 줘라."
            ),
        )

    #: 글을 적는 칸이 이만큼 있으면 그 화면은 **입력 폼**이다(`_SITE_SEARCH_JS` 의 pageIsForm 과 같은 값).
    _ENTRY_FORM_FIELDS = 12

    def _is_entry_form(self, page: Any) -> bool:
        try:
            return int(page.evaluate(
                "() => document.querySelectorAll('input[type=text], input:not([type]), textarea').length"
            )) >= self._ENTRY_FORM_FIELDS
        except Exception:  # noqa: BLE001
            return False

    def _site_search(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """사이트 검색 — **입력 폼 화면에서 불렸으면 그 탭은 두고, 새 탭의 사이트 첫 화면에서** 한다.

        ★ 2026-10-07 폼 벤치(B#1). 입력 폼에서는 검색칸을 안 고르게 고쳤더니(`_SITE_SEARCH_JS`), 이번에는 그 실패에 붙은
          안내 「손으로 하려면 browser_fill 로 채워라」를 따라 모델이 **학교 이름 칸에** 회사 이름을 넣고 Enter 를 쳤다.
          틀린 안내는 벽보다 나쁘다. 폼 화면의 칸은 검색칸이 아니고, 사람도 이럴 때 새 탭을 연다 — 도구가 그렇게 한다.
        """
        try:
            return self._site_search_here(page, arguments)
        except RuntimeError as exc:
            if "site_search_box_not_found" not in str(exc) or not self._is_entry_form(page):
                raise
        left = str(getattr(page, "url", "") or "")
        parsed = urlparse(left)
        fresh = None
        try:
            fresh = self._new_page(home=False)
            fresh.goto(f"{parsed.scheme}://{parsed.netloc}/", wait_until="domcontentloaded", timeout=20000)
            self._page = fresh
            result = self._site_search_here(fresh, arguments)
        except Exception:  # noqa: BLE001 — 첫 화면에도 검색칸이 없다(또는 못 열었다)
            self._page = page
            if fresh is not None:
                try:
                    fresh.close()
                except Exception:  # noqa: BLE001
                    pass
            raise RuntimeError(
                f"site_search_box_not_found:{_host_of_url(left)} — 지금 화면은 **입력 폼**이고, 이 사이트 첫 화면에도 검색칸이 없다. "
                "폼의 칸(이름에 「검색」이 들어 있어도)은 그 칸의 값을 고르는 자리이지 사이트 검색칸이 아니다 — **거기에 검색어를 넣지 마라.** "
                "찾는 것이 이 사이트 안에 있으면 browser_open 으로 사이트 첫 화면이나 목록 주소를 열고(쓰던 폼은 그대로 남는다), "
                "링크는 browser_links 로 찾아라."
            ) from None
        if isinstance(result, dict):
            result["opened_in_new_tab"] = True
            result["instruction"] = (
                f"[도구가 보낸 안내] 앞 화면({left[:100]})은 입력 폼이라 사이트 검색칸이 없다. 그 탭은 **그대로 두고** 새 탭에서 "
                "이 사이트 첫 화면을 열어 검색했다. 폼으로 돌아가려면 browser_tabs → browser_switch_tab. "
                + str(result.get("instruction") or "")
            ).strip()
        return result

    def _site_search_here(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """**지금 열린 사이트 안에서** 그 사이트의 검색으로 찾는다.

        2026-08-12 실측에서 드러난 빈 자리다. "여수·순천·광양 채용 공고"를 시켰더니
        네이버 검색을 일곱 번 돌면서 질의에 **"잡코리아"를 낱말로 끼워 넣었다.**
        잡코리아로 **들어가서** 그 사이트의 검색을 쓰는 것이 사람이 하는 일인데,
        그 걸음을 밟을 도구가 없었다. 그래서 제일 싼 행동(또 검색)을 되풀이했다.

        `google_drive_read` 가 없어서 이력서를 못 읽던 것과 **같은 모양**이다 —
        연장이 없으면 모델이 아무리 똑똑해도 그 일을 못 한다.

        ★ 주소를 지어내서 `jobkorea.co.kr/Search?...` 로 직행하지 않는다. 그건
        크몽을 `kmon.co.kr` 로 만들어 갔던 사고와 같은 짓이다. 검색 결과를 눌러
        그 사이트에 **들어간 뒤**, 그 화면의 검색칸을 쓴다.
        """
        query = _clean(arguments.get("query"), 300)
        if not query:
            raise ValueError("query_required")
        host = _host_of_url(str(getattr(page, "url", "") or ""))
        if not host or host.startswith("search.naver") or "bing.com" in host:
            raise RuntimeError(
                "not_on_a_site — 지금은 검색엔진 결과 화면이다. 먼저 browser_open_result 로"
                " 그 사이트에 **들어간 뒤** 이 도구를 써라."
            )
        # ★ **배운 주소가 있으면 검색칸을 찾기 전에 거기로 간다** (2026-09-06).
        #
        #   실측: 검색칸을 못 찾은 것이 31 건(위시켓만 22 건 — 걸음 2 위 사이트다),
        #   모델이 손으로 주소를 조립한 것이 57 건이었다. 손 조립은 오타가 난다 —
        #   다나와에서 퍼센트 인코딩을 한 글자 틀려 「무섧마우스」로 검색했고
        #   **404 가 아니라 빈 목록**으로 조용히 왔다.
        #
        #   여기서 쓰는 것은 **이 크롬이 실제로 열어서 결과가 나온 주소**다. 토큰을
        #   저장하지도, 브라우저 없이 쏘지도 않는다(그러면 봇 검사에 더 걸린다).
        learned = self._learned_search(page, query)
        if learned is not None:
            return learned
        found = None
        for _ in range(2):
            found = page.evaluate(self._SITE_SEARCH_JS)
            if found:
                break
            page.wait_for_timeout(800)
        if not found and self._open_search_box(page):
            # ★ 접혀 있는 검색칸 (2026-08-12 사람인 실측).
            #
            # 검색칸이 DOM 에는 있는데 `width=0 · 안 보임`이었다 — 돋보기를 눌러야
            # 펼쳐지는 형태다. 그래서 "이 사이트엔 검색이 없다"로 읽고 멈췄다.
            # 없는 게 아니라 **접혀 있었다.**
            page.wait_for_timeout(700)
            found = page.evaluate(self._SITE_SEARCH_JS)
        if not found:
            # ★ **검색칸이 있던 페이지로 한 번 가 본다** (2026-09-09).
            #
            #   위시켓은 홈에 검색칸이 없고 `/project/` 에만 있다. 사이트 이름만
            #   알고 들어가면 홈으로 가므로, 위시켓 4 판이 **4 판 다** 여기서
            #   실패하고 손으로 더듬어 회복했다 — 시간 편차의 제일 큰 상수였다.
            #
            #   안내문으로는 안 고쳐진다(이 저장소가 아는 규율). 아는 주소가 있으면
            #   **도구가 직접 가서 다시 본다.** 한 번만 — 무한히 돌면 진짜 없는
            #   사이트에서 판을 먹는다.
            remembered = self._search_atlas.search_page_for(
                str(getattr(page, "url", "") or "")
            )
            here = str(getattr(page, "url", "") or "").rstrip("/")
            if remembered and remembered.rstrip("/") != here:
                try:
                    page.goto(remembered, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(600)
                    found = page.evaluate(self._SITE_SEARCH_JS)
                except Exception:
                    found = None
        if not found:
            self._note_trait(page, "site_search_fails")
            raise RuntimeError(
                f"site_search_box_not_found:{host} — 이 화면에서 검색칸을 못 찾았다."
                + self._recipe_search_hint(host)
                + " 그래도 손으로 하려면 browser_snapshot 으로 보고 browser_fill 로 채워라."
                " ★ 그때는 **방금 찍은 스냅샷의 ref** 를 써라 — 앞서 ui_find_target 이"
                " 알려 준 ref 는 그 사이 화면이 바뀌었으면 딴 칸을 가리킨다."
            )

        self._note_trait(page, "site_search_ok")
        box = page.locator("[data-jarvis-sitesearch='1']").first
        before = str(getattr(page, "url", "") or "")
        # 칸을 찾은 **이 주소**를 기억한다. 다음에 홈으로 들어와도 여기로 온다.
        try:
            self._search_atlas.remember_search_page(before)
        except Exception:
            pass
        # ★ 누르기는 **실패해도 된다.** 2026-08-12 실측: 잡코리아 검색칸을 정확히
        # 찾아 놓고도 공지 팝업(dialog-overlay)이 포인터를 가로채 20초를 버티다
        # 통째로 실패했다. `fill` 은 포인터를 쓰지 않고 값을 넣으므로 그 벽을 안 탄다.
        #
        # 그래도 먼저 눌러 보는 이유: 눌러야 검색 UI 가 펼쳐지는 사이트가 있다.
        # 짧게 시도하고, 막히면 그냥 채운다.
        try:
            box.click(timeout=2500)
        except Exception:
            pass
        box.fill(query)
        box.press("Enter")
        # 사이트 검색은 이동일 수도, 그 자리에서 그리는 것일 수도 있다. 둘 다 기다린다.
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        try:
            page.evaluate(
                _deep_js("() => { document.querySelectorAll('[data-jarvis-sitesearch]')"
                ".forEach((el) => el.removeAttribute('data-jarvis-sitesearch')); }")
            )
        except Exception:
            pass
        ready = self._wait_until_operable(page)
        after = str(getattr(page, "url", "") or "")
        self._mark_visited(after)
        limit = max(1, min(int(arguments.get("limit") or 15), 30))
        loaded = self._load_more(page, rounds=int(arguments.get("scroll") or 0))
        # ★ 여기가 ② 다. 사이트 목록에도 **순위**를 매겨 `_last_results` 에 넣는다.
        #
        # 2026-08-12 실측: 잡코리아 목록을 스냅샷으로 85개 잡아 놓고
        # `browser_open_result rank=32` 를 불렀는데 "있는 순위: 1~9" 로 거절당했다.
        # 그 1~9 는 **네이버 검색 결과**였다. 사이트 안 목록에는 부를 이름이 아예
        # 없었던 것이다. 그래서 상세를 못 열고 목록에 적힌 분류를 그대로 옮겨 적었다
        # (실제 직무는 "KB라이프 청약매니저"인데 "전산설계사무"로 나갔다).
        # ★ 순위를 매기기 **전에** 날짜를 맞춘다. 목록이 다시 그려지므로 순서가
        #   뒤바뀌면 엉뚱한 밤의 순위를 들고 상세로 들어가게 된다.
        date_fix = self._apply_requested_dates_here(page)
        results = self._results_once_drawn(page, limit=limit)
        # ★ 여러 낱말 검색에 **첫 낱말이 하나도 안 걸렸으면** 그 낱말 하나로 한 번 다시 찾는다 (2026-10-02 분업 실험 2186746e).
        #   손자리가 K-Startup 에서 「AI 창업지원사업」·「소프트웨어 창업지원사업」으로 검색했다 — 그 사이트 검색칸은 낱말을 다
        #   맞춰야 나와서 AI 제목 공고가 하나도 안 걸리고 엉뚱한 9건이 왔다. 그러고 「목록에 AI 제목 공고가 없었다」고 보고했고,
        #   클로드는 그 말을 믿었다. 새벽 3차 판처럼 「AI」 하나로 찾았으면 「AI 올라운더 8기」가 바로 떴다. 안내문이 아니라 도구가 한다.
        #   0건 화면은 아래 판정이 따로 말한다 — 거기서 모아 온 것은 결과가 아니라 필터 링크라 다시 찾기의 재료가 못 된다
        #   (첫 회귀에서 다시 찾기가 0건 화면을 덮어 「0건입니다」가 사라졌다).
        def says_no_results() -> bool:
            # ★ 검색 결과가 0건인 화면 (2026-10-01 밤 운영 판 b9f90b2c, 허깅페이스 「7B 14B model GGUF Q4」).
            #   진짜 목록이 없으면 `_collect_results` 는 화면의 아무 링크나 모아 오는데, 그게 **왼쪽 필터 20개**였다.
            #   도구는 「이 사이트가 직접 준 목록이다(20건)」라고 알렸고, 1번을 열자 「Text Generation」 필터 화면이 열렸다.
            #   화면이 「No results found」라고 말하고 판정기도 목록을 못 찾았으면 0건이라고 말한다.
            return bool(results) and self._page_says_no_results(page) and len(self._result_list_rows(page)) < 3

        no_results = says_no_results()
        retried = None if no_results else self._retry_with_head_word(page, query, results, limit, host=host)
        if retried is not None:
            query, results = retried
            no_results = says_no_results()
        if no_results:
            results = []
        if results or not self._last_results:
            self._last_results = results
            self._remember_results_origin(page)
        # ★ 통했으면 **그 주소를 배운다.** 다음 판은 검색칸을 안 찾아도 된다.
        self._learn_search_url(page, len(results), query)
        self._reads_since_search = 0
        self._searched_before = True
        return self._evidence(
            "site_searched",
            **{
                key: value
                for key, value in self._date_rewrite_evidence(date_fix).items()
                if key != "date_instruction"
            },
            site=host,
            query=query,
            search_box=str(found.get("name") or ""),
            url_changed=after != before,
            element_count=ready["count"],
            results=results,
            result_count=len(results),
            **({"loaded_more": loaded} if loaded else {}),
            **({"no_results": True} if no_results else {}),
            **({"retried_with": query} if retried is not None else {}),
            instruction=(getattr(self, "_head_retry_note", "") if retried is not None else "") + ((
                f"★ 이 사이트 검색 결과가 0건이다(화면에 「결과 없음」이 보인다). 화면의 필터·메뉴 링크는 결과가 아니니 열지 마라. "
                f"검색어 「{query}」가 너무 길거나 여러 낱말을 섞었을 수 있다 — 핵심 낱말 하나(이름·모델명 하나)로 줄여 "
                "browser_site_search 를 다시 하거나, 그 사이트의 정렬·필터 주소로 목록을 열어라."
            ) if no_results else (
                # 날짜 이야기를 **맨 앞**에 세운다. 바로 아래 "목록 줄에 보이는 값은
                # 그대로 써라"가 날짜를 요청한 판에서는 틀린 말이기 때문이다.
                (stay_note + " " if (stay_note := self._stay_note_for_list(page, applied=date_fix)) else "")
                + f"★ 이 사이트가 직접 준 목록이다({len(results)}건). 네이버로 돌아가 다시 "
                "검색하지 마라 — 여기가 최신이다. "
                "**이 목록에 적힌 것은 그 자체로 근거다** — 제목·가격·평점·리뷰 수·판매자처럼 "
                "목록 줄에 이미 보이는 값은 상세를 안 열어도 그대로 답에 써라. 여러 건을 "
                "비교하라는 요구라면 목록만으로 대부분 채워진다. "
                "**목록에 없는 것**(본문 내용·조건·마감일 같은 값)이 필요할 때만 "
                "browser_open_result 에 rank 를 줘서 들어가라(이제 이 목록에도 순위가 있다). "
                "목록이 짧으면 browser_load_more 로 더 불러와라."
            )),
        )

    def _retry_with_head_word(
        self, page: Any, query: str, results: list[dict[str, Any]], limit: int, *, host: str = ""
    ) -> tuple[str, list[dict[str, Any]]] | None:
        """여러 낱말 검색 결과에 **첫 낱말**이 하나도 없으면, 그 낱말 하나로 한 번 다시 찾는다. 안 그래도 되면 None.

        첫 낱말을 쓰는 이유: 모델은 핵심어를 앞에 둔다(「AI 창업지원사업」·「소프트웨어 창업지원사업」·「무선 마우스 추천」).
        한 번만 — 다시 찾은 것도 그 낱말이 안 걸리면 그대로 두고, 무엇을 했는지 결과에 적는다(`_head_retry_note`).

        ★ **검색칸이 낱말을 다 맞춰야 나온다고 확인한 사이트에서만** 한다 (2026-10-12 · `search_boxes`).
          모든 사이트에 걸어 둔 열흘 동안 24번 켜졌고, 모델이 다시 찾은 결과를 그대로 연 것은 1번이었다(바로 다시 검색 13번).
          가게에서는 첫 낱말이 상표라, 상표 하나로 다시 찾으면 모델 번호가 사라진다 — 모델이 넣은 검색어를 말없이 바꾸지 않는다.
        """
        self._head_retry_note = ""
        if not _search_boxes.needs_every_word(host):
            return None
        words = query.split()
        head = words[0] if len(words) >= 2 else ""
        if len(head) < 2:
            return None
        def mentions(items: list[dict[str, Any]]) -> bool:
            return any(head.lower() in f"{item.get('title') or ''} {item.get('snippet') or ''}".lower() for item in items)
        if not results or mentions(results):
            return None
        try:
            again = self._site_search(page, {"query": head, "limit": limit})
        except Exception:  # noqa: BLE001 — 다시 찾기는 거들 뿐이다
            return None
        found = list(again.get("results") or [])
        self._head_retry_note = (
            f"★ 「{query}」 결과 {len(results)}건에 「{head}」가 하나도 없어서 「{head}」 하나로 다시 찾았다({len(found)}건). "
            "이 사이트 검색칸은 낱말을 다 맞춰야 나오는 곳이다 — 여러 낱말을 붙이지 말고 핵심어 하나로 찾아라. "
        )
        return head, found

    # 무한스크롤·더보기로 뒤에 숨은 목록. 한 화면만 보고 "이게 전부"라고 하면 안 된다.
    _MORE_BUTTON = re.compile(r"(더\s*보기|더보기|더\s*불러|다음\s*페이지|load\s*more|show\s*more|see\s*more)", re.IGNORECASE)

    def _load_more(self, page: Any, *, rounds: int = 3) -> dict[str, Any] | None:
        """목록 끝까지 내려가며 **더 불러온다.** 더 이상 안 늘면 멈춘다.

        무한스크롤은 한 화면만 보고 판단하면 반드시 틀린다 — 화면에 열 개가 보여도
        실제 목록은 수백 개다. 그렇다고 끝까지 내려가면 목록이 수천 개짜리 사이트에서
        영영 안 끝나므로 **늘지 않으면 멈추는 것**이 상한이다.

        링크 수로 재는 이유: `_collect_results` 는 프레임을 전부 훑어 비싸다(라운드마다
        부르면 몇 초씩 든다). 늘었는지만 알면 되므로 세는 것은 싸야 한다.

        `더보기` 버튼을 쓰는 사이트도 있어서 스크롤로 안 늘면 그 버튼을 한 번 누른다.
        """
        if rounds <= 0:
            return None
        virtual = self._harvest_virtual_list(page)
        if virtual is not None:
            return virtual
        count_js = _deep_js("() => { return document.querySelectorAll('a[href]').length; }")
        try:
            seen = [int(page.evaluate(count_js))]
        except Exception:
            return None
        clicked = 0
        for _ in range(max(1, min(rounds, 8))):
            try:
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1200)
                now = int(page.evaluate(count_js))
            except Exception:
                break
            if now <= seen[-1]:
                # 스크롤로 안 늘면 '더보기' 버튼이 있는 사이트일 수 있다.
                if self._click_more_button(page):
                    clicked += 1
                    page.wait_for_timeout(1500)
                    try:
                        now = int(page.evaluate(count_js))
                    except Exception:
                        break
                    if now <= seen[-1]:
                        seen.append(now)
                        break
                else:
                    seen.append(now)
                    break
            seen.append(now)
        return {"link_counts": seen, "more_clicks": clicked, "grew": seen[-1] > seen[0]}

    #: 가상 스크롤을 모을 때 최대 몇 칸 내리나. 한 칸 = 보이는 높이의 80%.
    _VIRTUAL_MAX_STEPS = 40

    def _harvest_virtual_list(self, page: Any) -> dict[str, Any] | None:
        """가상 스크롤 목록이면 **한 칸씩 내리며 줄을 쌓아** 모은다. 아니면 None(예전 길로).

        판정은 구조로 한다: 한 칸 내렸을 때 목록 줄 **일부가 사라지고 새 줄이 생기면** 가상 스크롤이다.
        보통 페이지는 내려도 줄이 그대로 DOM 에 남아 있다.
        """
        try:
            before = self._result_list_rows(page)
            if len(before) < 3:
                return None
            page.evaluate(_SCROLLER_JS)
            first = page.evaluate(_STEP_SCROLL_JS, 0.8)
            page.wait_for_timeout(350)
            after = self._result_list_rows(page)
        except Exception:
            return None
        before_keys = {row["href"] for row in before}
        after_keys = {row["href"] for row in after}
        if not int((first or {}).get("moved") or 0) or not (before_keys - after_keys) or not (after_keys - before_keys):
            return None
        collected: dict[str, dict[str, Any]] = {}
        for row in before + after:
            collected.setdefault(row["href"], row)
        quiet = 0
        steps = 1
        while steps < self._VIRTUAL_MAX_STEPS and quiet < 2:
            try:
                moved = page.evaluate(_STEP_SCROLL_JS, 0.8)
                page.wait_for_timeout(350)
                rows = self._result_list_rows(page)
            except Exception:
                break
            steps += 1
            fresh = [row for row in rows if row["href"] not in collected]
            for row in fresh:
                collected[row["href"]] = row
            quiet = 0 if fresh else quiet + 1
            if not int((moved or {}).get("moved") or 0):
                break
        self._virtual_rows = list(collected.values())
        self._virtual_rows_url = str(getattr(page, "url", "") or "")
        return {"virtualized": True, "scroll_steps": steps, "collected_rows": len(collected),
                "grew": len(collected) > len(before)}

    def _click_more_button(self, page: Any) -> bool:
        try:
            found = page.evaluate(
                _deep_js("""
                (pattern) => {
                  const re = new RegExp(pattern, "i");
                  const vis = (el) => el.getClientRects().length > 0 &&
                    getComputedStyle(el).visibility !== "hidden";
                  const cand = Array.from(document.querySelectorAll("button,a,[role=button]"));
                  for (const el of cand) {
                    const text = (el.innerText || el.getAttribute("aria-label") || "").trim();
                    if (text && re.test(text) && vis(el)) {
                      el.setAttribute("data-jarvis-more", "1");
                      return text.slice(0, 40);
                    }
                  }
                  return null;
                }
                """),
                self._MORE_BUTTON.pattern,
            )
        except Exception:
            return False
        if not found:
            return False
        try:
            page.locator("[data-jarvis-more='1']").first.click(timeout=5000)
            return True
        except Exception:
            return False
        finally:
            try:
                page.evaluate(
                    _deep_js("() => { document.querySelectorAll('[data-jarvis-more]')"
                    ".forEach((el) => el.removeAttribute('data-jarvis-more')); }")
                )
            except Exception:
                pass

    def _close(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """브라우저를 닫는다. 일이 끝났으면 창을 남겨 두지 않는다.

        되돌릴 수 없는 동작이 아니다 — 다음 브라우저 호출이 알아서 다시 띄운다
        (측정: 0.9초). 그래서 승인을 받지 않는다.
        """
        del arguments
        url = str(getattr(page, "url", "") or "")
        self._close_after_action = True  # `_execute` 가 마무리 표시 뒤에 닫는다
        return self._evidence("browser_closed", url=url)

    def _search(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        query = _clean(arguments.get("query"), 1000)
        if not query:
            raise ValueError("query_required")
        requested = str(arguments.get("engine") or "auto").lower()
        tab = str(arguments.get("tab") or "all").lower()
        period = str(arguments.get("period") or "").lower()
        period = period if period in self._NAVER_PERIOD else ""
        limit = max(1, min(int(arguments.get("limit") or 12), 30))
        # 검색어에 site: 를 섞어 보내는 일이 잦다(실측). 네이버는 그 연산자를 모르므로
        # 조용히 빈손으로 돌아오고, 모델은 "그 사이트에는 없다"로 잘못 읽는다.
        # 여기서 떼고, 대신 tab 을 쓰라고 알려 준다.
        stripped = _SITE_OPERATOR.sub("", query).strip()
        site_hint = ""
        if stripped and stripped != query:
            site_hint = _SITE_OPERATOR.search(query).group(1)  # type: ignore[union-attr]
            query = stripped
        fingerprint = f"{requested}|{tab}|{period}|{query}"
        repeated = fingerprint in self._recent_queries
        self._recent_queries.append(fingerprint)
        del self._recent_queries[:-12]
        # 직전 검색 뒤로 하나도 안 읽고 또 검색했는가.
        #
        # ★ 예전에는 `self._last_results` 가 비어 있으면 이 셈을 **0으로 되돌렸다.**
        # 그게 정작 필요한 순간에 경고를 죽였다(2026-08-10 실측): 검색 10번 중
        # 처음 두 번은 결과가 4건·3건이었는데 모델이 안 읽고 넘어갔고, 그 뒤 8번이
        # 0건이라 셈이 매번 0으로 초기화돼 "읽지도 않고 또 검색한다"는 경고가
        # 한 번도 안 떴다. 결과가 없었다는 것은 **더 검색하라는 뜻이 아니다.**
        if self._searched_before and self._reads_since_search == 0:
            self._searches_without_read += 1
        else:
            self._searches_without_read = 0
        self._searched_before = True
        self._reads_since_search = 0
        preferred = self._search_engines(query, requested)
        engines, cooling = self._engine_order(preferred)
        # 건너뛴 것도 시도 기록이다. 안 적으면 "빙을 왜 안 썼는지"가 사라진다.
        attempts: list[dict[str, str]] = [
            {"engine": engine, "status": "skipped", "seen": "cooldown"} for engine in cooling
        ]
        # 0건으로 돌아온 엔진의 보고. 다음 엔진도 못 주면 이것을 돌려준다.
        came_back_empty: dict[str, Any] | None = None
        for engine in engines:
            self._goto_page(
                page,
                self._search_url(engine, query, tab, period),
                wait_until="domcontentloaded",
            )
            # 검색 결과도 스크립트가 그린다. `domcontentloaded` 직후에 세면 0개가
            # 나오고, 그 0개는 "결과 없음"과 구별되지 않는다 (2026-08-05 8개 사이트).
            ready = self._wait_until_operable(page)
            if self._search_blocked(page):
                self._note_blocked(engine)
                attempts.append({"engine": engine, "status": "blocked", "seen": "immediately"})
                continue
            # 검색창·탭이 아니라 **결과**가 그려지기를 기다린다.
            settled = self._wait_for_results(page, limit=limit)
            if settled["blocked"]:
                # ★ 늦게 온 봇 검사. 위 검사를 통과했다고 안심하면 안 된다 —
                # 실측(2026-08-07)에서 검사 화면은 문서보다 **4초 뒤**에 왔고,
                # 그래서 0건이 "결과 없음"으로 둔갑해 있었다. 여기서 못 잡으면
                # 다음 엔진(네이버)으로 넘어가는 길이 통째로 막힌다.
                self._note_blocked(engine)
                attempts.append({"engine": engine, "status": "blocked", "seen": "while_waiting"})
                continue
            # 통했으면 낙인을 지운다 — 차단은 풀리고, 그때 바로 원래 엔진으로 돌아가야 한다.
            self._blocked_engines.pop(engine, None)
            attempts.append({"engine": engine, "status": "ok"})
            results = _without_videos(settled["results"], query, tab)
            # ★ 빈 결과로 **쓸 수 있던 결과를 덮지 않는다.**
            #
            # 실측(2026-08-10): 4건짜리 결과를 받아 둔 뒤 질의를 바꿔 가며 8번을
            # 0건으로 받았는데, 그때마다 `_last_results` 가 []로 덮여서 나중에
            # rank 1 을 열려 해도 `no_search_results` 가 났다. 열 수 있던 문을
            # 검색이 스스로 닫은 것이다.
            if results or not self._last_results:
                self._last_results = results
                self._remember_results_origin(page)
            # ★ 답 상자는 **통합 검색에만** 있다 (2026-10-02 「모두의 AI」 판). 뉴스·블로그 탭의 첫 덩어리는 기사 목록 요약인데
            #   그걸 답 상자로 집어, 검색 두 번이 「근거 2개 실제로 읽음」이 됐다 — 읽기가 끝난 줄 안 계획이 파일 단계로 넘어가
            #   기사를 열려던 걸음을 두 번 막았고, 본문 0개로 문서를 썼다.
            try:
                answer_box = _clean_answer_box(page.evaluate(_SERP_ANSWER_BOX_JS)) if tab == "all" else ""
            except Exception:  # noqa: BLE001 — 답 상자는 거들 뿐이다
                answer_box = ""
            found = self._evidence(
                "searched",
                **({"answer_box": answer_box,
                    "answer_box_note": "검색 결과 맨 위 답 상자 글이다(날씨·환율 같은 위젯). 묻는 값이 여기 있으면 이걸로 답해도 된다."}
                   if answer_box else {}),
                # ★ 결과를 여기서 준다. 예전에는 검색어와 차단 여부만 돌려주고
                # 결과는 모델이 `browser_snapshot` 으로 직접 뒤지게 했는데,
                # 그 스냅샷은 앞 20개가 전부 탭·로그인이고(네이버) 링크 26개가
                # 전부 리다이렉트 래퍼였다(빙). 고를 정보가 화면에 없었다.
                results=results,
                result_count=len(results),
                query=query,
                engine=engine,
                tab=tab,
                **({"period": period} if period else {}),
                **({"site_operator_removed": site_hint} if site_hint else {}),
                requested_engine=requested,
                # 쿨다운으로 순서를 바꾼 뒤의 첫째가 아니라 **원래 1순위**와 견준다.
                # 빙을 건너뛰고 네이버로 갔으면 그건 분명히 폴백이다 — 재정렬한
                # 목록을 기준으로 삼으면 그 사실이 증거에서 사라진다.
                fallback_used=engine != preferred[0],
                attempts=attempts,
                element_count=ready["count"],
                ready_polls=ready["polls"],
                # 결과를 몇 번 만에 잡았는가. 1이면 첫 시도에 있었다는 뜻이고,
                # 여러 번이면 화면이 늦게 그려졌다는 증거다 — 0건이 나왔을 때
                # "정말 없다"와 "덜 그려졌다"를 가르는 유일한 값이다.
                result_polls=settled["polls"],
                # 같은 검색을 또 했는가. 실측(2026-08-06)에서 모델이 한 질문에
                # 검색을 8번 하고 글은 1개만 읽었다 — 결과가 마음에 안 들면
                # 파고드는 대신 검색어를 바꿔 가며 목록만 다시 받았다.
                # 검색은 늘 성공으로 돌아오므로 스스로는 헛돌고 있음을 모른다.
                **({"repeated_search": True} if repeated else {}),
                **({"searches_without_reading": self._searches_without_read}
                   if self._searches_without_read else {}),
                instruction=self._search_instruction(
                    results, repeated=repeated, skipped=self._searches_without_read
                ),
            )
            # ★ **0건도 다음 엔진으로 가는 문이다** (2026-10-13 가격 조사 판). 막혔을 때만 넘어갔다 — 그런데 상품 이름으로
            #   네이버 통합검색을 하면 첫 화면이 광고와 쇼핑 묶음으로 차서(광고는 결과가 아니다) 0건이 된다. 재는 판의 통합검색
            #   129번 중 68번이 그랬고(마우스 이름 33번 중 28번 · 화면은 다 그려져 있었다), 「결과가 없다」를 받은 모델은 77번 중
            #   41번을 다시 검색했다. 흔한 상품 이름에 「결과가 없다」는 사실이 아니다. 다음 엔진이 있으면 거기서 한 번 더 본다.
            #   탭(블로그 · 뉴스 …)은 그 엔진의 것이라 넘기지 않는다 — 시킨 것과 다른 것을 찾아 오게 된다.
            if results or tab != "all" or engine == engines[-1] or answer_box:
                return found
            attempts[-1] = {"engine": engine, "status": "empty"}
            came_back_empty = found
        if came_back_empty is not None:
            came_back_empty["attempts"] = attempts
            return came_back_empty
        # 여기서 멈추는 게 맞다. 봇 검사는 사람이 통과해야 하는 것이고, 우리가 대신
        # 풀지 않는다. 브라우저는 화면에 떠 있으므로 사용자가 직접 넘기실 수 있다.
        # 조용히 실패하면 모델이 검사 화면을 결과로 읽고 없는 사실을 지어낸다.
        raise RuntimeError(
            "search_engines_blocked:"
            + ",".join(item["engine"] for item in attempts)
            + " — 검색엔진이 봇 확인 화면을 띄웠습니다. 화면의 확인을 직접 통과해 주시면"
            " 이어서 진행하겠습니다. 급하면 naver_web 같은 검색 API를 쓰는 편이 낫습니다."
        )

    @staticmethod
    def _search_instruction(
        results: list[dict[str, Any]], *, repeated: bool, skipped: int = 0
    ) -> str:
        """다음에 무엇을 하라고 말해 줄 것인가.

        검색은 **언제나 성공으로 돌아온다.** 결과가 마음에 안 들 때 파고드는 대신
        검색어를 바꿔 가며 목록만 다시 받아도, 그 자체로는 아무 신호가 없다.

        실측 두 번(2026-08-06):
            프롬프트 고치기 전   검색 8번 · 본문 1개
            프롬프트 고친 뒤     검색 7번 · 본문 1개   <- 말로는 안 고쳐졌다

        `repeated` 는 **같은 낱말**일 때만 걸린다. 검색어를 조금씩 바꾸면 빠져나간다 —
        위 두 번째 실측이 정확히 그 모양이었다. 그래서 `skipped` 를 함께 본다:
        결과를 받아 놓고 **하나도 안 읽은 채** 또 검색한 횟수다. 낱말이 아니라
        행동을 보므로 검색어를 바꿔도 걸린다.

        결과 안쪽에 묻어 두지 않고 최상단에 싣는 이유는 6.2 와 같다 — 중첩된 값 안에
        두면 모델이 안 펼쳐 보고 실패로만 읽는다.
        """
        if not results:
            return (
                "결과가 없다. 같은 질의를 다시 보내지 말고 낱말을 바꾸거나 "
                "tab(blog·cafe·news·kin)·engine 을 지정해라. site: 연산자는 쓰지 마라."
            )
        unread = [item["rank"] for item in results if not item.get("visited")]
        base = (
            f"아직 안 읽은 결과 {len(unread)}건이 있다(rank {unread[:5]}). "
            "browser_open_result 에 rank 를 줘서 **들어가라.** 본문은 browser_extract 로 "
            "읽고, 더 파고들 링크는 browser_links 로 찾는다."
        )
        secondhand = BrowserWorker._secondhand_note(results)
        if skipped >= 2:
            return (
                f"★ 결과를 받아 놓고 **하나도 안 읽은 채 검색만 {skipped + 1}번째**다. "
                "검색어를 바꿔도 목록의 성격은 달라지지 않는다 — 답은 본문에 있고, "
                "본문은 열어야 보인다. 지금은 검색하지 말고 읽어라. " + base
            )
        if skipped == 1:
            return "★ 직전 검색 결과를 하나도 안 읽고 또 검색했다. " + base
        if repeated:
            return (
                "★ 방금과 같은 검색이다. 목록을 다시 받아도 달라지는 것이 없다 — "
                "지금 필요한 것은 검색이 아니라 **읽기**다. " + base
            )
        return base + secondhand

    # 남이 쓴 글이 올라오는 곳. **원문을 내는 서비스가 아니다.**
    #
    # 사이트를 늘려 가며 "여기는 채용 사이트"를 적지 않는다 — 그 목록은 끝이 없고
    # 금방 낡는다. 반대쪽은 유한하고 잘 안 변한다: 블로그·카페·커뮤니티다.
    _SECONDHAND_HOSTS = (
        "blog.naver.com", "m.blog.naver.com", "post.naver.com", "cafe.naver.com",
        "blog.daum.net", "cafe.daum.net", "tistory.com", "brunch.co.kr",
        "velog.io", "medium.com", "wordpress.com", "egloos.com",
        "dcinside.com", "fmkorea.com", "clien.net", "ruliweb.com",
    )

    @staticmethod
    def _secondhand_note(results: list[dict[str, Any]]) -> str:
        """결과가 대부분 **남이 쓴 글**이면, 원문 서비스로 들어가라고 말한다.

        2026-08-12 실측(여수·순천·광양 채용 공고). 네이버 웹·블로그 검색만 뒤져서
        연 것이 티스토리 글 하나·네이버 블로그 하나였고, 유일하게 찾은 진짜 공고는
        **2025년 9월에 마감된 것**이었다. 답은 정직했다("현재 지원 가능한 공고 없음")
        지만 쓸 결과가 0건이었다.

        블로그 글은 **그때의 이야기**다. 지금 열려 있는 것을 알려면 그 서비스 안으로
        들어가서 그 사이트의 검색을 써야 한다. 사용자 말이 정확했다 —
        "네이버에서 → 잡코리아 → 이런 식으로 가야 그라운딩이 된다."

        ★ 주소를 지어내서 직행하는 길은 열지 않는다. 그건 크몽을 `kmon.co.kr` 로
        만들어 갔던 그 사고(`host_does_not_exist`)와 같은 짓이다. **검색 결과를
        눌러서** 들어가고, 사이트 안에서는 그 사이트의 검색창을 쓴다.
        """
        if not results:
            return ""
        hosts = [str(item.get("domain") or "").lower() for item in results]
        blogs = sum(
            1 for host in hosts
            if any(host.endswith(known) or host == known for known in BrowserWorker._SECONDHAND_HOSTS)
        )
        if blogs * 2 < len(hosts):
            return ""
        return (
            " ★ 이 결과는 대부분 **남이 쓴 글**(블로그·카페)이라 시점이 지난 이야기일 수 "
            "있다. 지금 열려 있는 원문이 필요하면, 결과 중 **그 서비스 자체**의 도메인을 "
            "골라 browser_open_result 로 들어간 뒤(주소를 지어내지 말고 결과를 눌러라) "
            "**browser_site_search** 로 그 사이트 안에서 다시 찾아라. 검색어에 사이트 "
            "이름을 끼워 넣어 또 검색하는 것은 같은 목록을 다시 받는 것뿐이다."
        )

    def _note_blocked(self, engine: str) -> None:
        self._blocked_engines[engine] = time.monotonic()

    def _engine_order(self, engines: list[str]) -> tuple[list[str], list[str]]:
        """방금 막힌 엔진은 건너뛴다. `(시도할 것, 건너뛴 것)`.

        차단은 한 번 걸리면 한동안 이어지는데(2026-08-08 실측: 빙·구글이 새 임시
        프로필에서도 계속 막혔다) 도구는 매번 그걸 잊었다. 막힌 엔진을 다시 부딪히는
        값은 goto + 결과 대기 + 수집으로 **검색 1회당 ~10초**이고, 이미 찍힌 엔진을
        계속 두드리는 것 자체가 차단을 유지시킨다.

        ★ 전부 쿨다운 중이면 **그래도 시도한다.** 건너뛰기만 하면 차단이 한 바퀴
        돈 순간 검색이 통째로 불가능해지고, 그건 원래 고장보다 나쁘다 — 쿨다운은
        비용을 아끼자는 것이지 검색을 막자는 것이 아니다.

        건너뛴 것은 이름을 대서 증거에 남긴다. 조용히 건너뛰면 이 쿨다운 자체가
        "빙은 결과가 없다"로 읽히는 새로운 침묵이 된다 — 고치려던 그 고장이다.
        """
        window = max(0, int(self.config.browser_search_block_cooldown_sec))
        if not window:
            return engines, []
        now = time.monotonic()
        fresh = [e for e in engines if now - self._blocked_engines.get(e, -1e9) >= window]
        return (fresh, [e for e in engines if e not in fresh]) if fresh else (engines, [])

    @staticmethod
    def _search_engines(query: str, requested: str) -> list[str]:
        """어느 엔진으로 갈 것인가.

        ★ 2026-08-12 실측으로 전제가 뒤집혔다. 예전 지식은 "빙·구글은 상시 차단"이라
        국내는 네이버, 해외는 빙이었다. 그런데 그 차단은 **Playwright 가 띄운 크롬**
        (자동화 모드)에서 잰 것이었다. 진짜 크롬에 붙기 시작하자 같은 질의로:

            구글   ok · 결과 8건 · 폴백 없음   (langchain.com 등 영어권 원문)
            빙     여전히 막힘 → 네이버 폴백
            네이버 ok

        쿠팡과 정확히 같은 이야기다 — 사이트가 아니라 우리가 문제였다.

        그래서 **기본은 구글**, 국내 정보는 네이버다. 갈림은 질의의 성격으로 본다:
        한국어이면서 기술어가 아니면 국내 이야기(후기·업체·지역·제도)일 가능성이
        높고, 그건 네이버가 낫다. 빙은 아직 막히므로 폴백 맨 뒤로 보낸다.
        """
        if requested in {"naver", "bing", "google"}:
            primary = requested
        else:
            has_korean = bool(re.search(r"[가-힣]", query))
            primary = "naver" if has_korean and not _TECHNICAL_SEARCH.search(query) else "google"
        fallbacks = {
            "naver": ["naver", "google"],
            "google": ["google", "naver"],
            "bing": ["bing", "google", "naver"],
        }
        return fallbacks[primary]

    # 네이버의 검색 탭. 통합검색은 나무위키·쇼핑·지식iN 이 섞여 나오므로, 블로그
    # 사례를 찾을 때는 탭을 직접 지정하는 편이 훨씬 정확하다 — 실측에서 통합검색
    # 앞머리는 나무위키가 통째로 차지했고 blog.naver.com 링크 36개는 한참 뒤에 있었다.
    #
    # 검색 API 를 쓰지 않고 탭 주소를 쓰는 이유: API 는 제목·요약·URL 한 겹이라
    # 그 글 안으로 들어가 링크를 또 타고 갈 수가 없다. 파고드는 것이 목적이면
    # 처음부터 DOM 이어야 한다.
    _NAVER_TABS = {
        "blog": "ssc=tab.blog.all&sm=tab_jum",
        "cafe": "ssc=tab.cafe.all&sm=tab_jum",
        "news": "ssc=tab.news.all&where=news&sm=tab_jum",
        "kin": "ssc=tab.kin.all&where=kin&sm=tab_jum",
        "video": "ssc=tab.video.all&where=video&sm=tab_jum",
    }

    # 기간 거르기. ★ 2026-09-29 실측(네이버 뉴스 「국내 주요 뉴스」): 기간 없이는 앞 15건에 3일~1주 전 기사가 섞였고,
    #   `nso=so:r,p:1d`(관련도순 · 1일)를 붙이자 15건 전부 18시간 이내였다(`pd=4` 도 같은 결과 — 옛 형식이라 새 형식을 쓴다).
    #   네이버는 **뉴스 탭에만** 붙인다(재 본 곳만). 구글은 어느 결과에나 `tbs=qdr:` 가 먹는다.
    _NAVER_PERIOD = {"day": "1d", "week": "1w", "month": "1m"}
    _GOOGLE_PERIOD = {"day": "d", "week": "w", "month": "m"}

    @classmethod
    def _search_url(cls, engine: str, query: str, tab: str = "all", period: str = "") -> str:
        encoded = quote_plus(query)
        if engine == "naver":
            extra = cls._NAVER_TABS.get(tab, "")
            if tab == "news" and period in cls._NAVER_PERIOD:
                extra += f"&nso=so%3Ar%2Cp%3A{cls._NAVER_PERIOD[period]}"
            return f"https://search.naver.com/search.naver?query={encoded}" + (f"&{extra}" if extra else "")
        if engine == "bing":
            return f"https://www.bing.com/search?q={encoded}"
        if period in cls._GOOGLE_PERIOD:
            return f"https://www.google.com/search?q={encoded}&tbs=qdr:{cls._GOOGLE_PERIOD[period]}"
        return f"https://www.google.com/search?q={encoded}"

    @staticmethod
    def _search_blocked(page: Any) -> bool:
        try:
            url = str(page.url or "").lower()
            if any(marker in url for marker in ("/sorry/", "captcha", "challenge")):
                return True
            text = _clean(page.locator("body").inner_text(timeout=2500), 5000).lower()
            return any(marker.lower() in text for marker in _SEARCH_BLOCK_MARKERS)
        except Exception:
            return False

    # ---- 파고들기: 검색 결과 → 본문 → 그 안의 링크 → 다시 목록 -------------------
    #
    # 이 넷이 한 고리를 이룬다. 하나라도 없으면 "타고 타고 들어가서 집요하게 본다"가
    # 안 된다:
    #
    #   _collect_results   무엇이 있는지        (흩어진 ref 를 결과로 묶는다)
    #   _open_result       그 중 하나로 들어간다  (순위로 — ref 는 이동하면 날아간다)
    #   _extract           본문만 읽는다         (메뉴·댓글·추천글을 뺀 글 자체)
    #   _links             그 안에서 다음 후보    (더 깊이 갈 곳)

    def _wait_for_results(self, page: Any, *, limit: int) -> dict[str, Any]:
        """**결과가** 그려질 때까지 기다린다 — 아무거나 그려질 때까지가 아니라.

        ★ `_wait_until_operable` 로는 부족하다. 검색 화면에서 검색창과 탭은 문서와
        함께 즉시 내려오므로 그 검사는 **첫 번째 폴에서 바로 통과한다.** 결과는 그
        뒤에 스크립트가 그린다. 그 사이에 세면 결과 0건이 나오고, 0건은 "이 질의에
        결과가 없다"와 구별되지 않는다 — 모델은 질의를 바꾸러 간다.

        실측(2026-08-06, 네이버 블로그 탭): 조작 가능한 요소는 197개인데 결과는 0건.
        같은 화면을 3초 뒤에 다시 재면 결과가 나온다. 요소 0개 사고(2026-08-05)와
        같은 고장인데, 빈 화면이 아니라 **반쯤 그려진 화면**이라 더 안 보인다.

        교훈은 일반적이다: 준비됐는지는 **실제로 필요한 것**으로 재야 한다.

        ★ 봇 검사도 여기서 같이 본다(2026-08-07). 검사 화면은 문서와 함께 오지
        않고 **한참 뒤에** 온다 — 같은 페이지를 300ms 간격으로 재 보면 이렇다:

            0.6초   탭·검색창만 있는 껍데기   차단 아님   결과 0건
            4.7초   "마지막 한 단계 · 계속하려면 아래 과제 해결"   차단   결과 0건

        `_search` 는 `goto` 직후 한 번만 차단을 보므로 저 0.6초 지점만 보고 "ok" 로
        지나간다. 그러고는 여기서 6초를 기다렸다가 0건을 **성공으로** 돌려준다.
        봇 검사 화면이 "결과가 없다"로 둔갑하는 것이고, 그러면 멀쩡한 네이버 폴백도
        쓰이지 않는다. 기다리는 동안 다시 보는 것 말고는 잡을 방법이 없다.

        결과가 이미 잡혔으면 차단을 묻지 않는다 — 검사 화면에는 결과가 없고,
        "captcha" 같은 낱말이 실린 멀쩡한 결과 페이지를 차단으로 오인할 이유도 없다.
        """
        deadline = time.monotonic() + max(0, int(self.config.browser_ready_timeout_ms)) / 1000
        polls = 0
        results: list[dict[str, Any]] = []
        previous = -1
        while True:
            polls += 1
            results = self._collect_results(page, limit=limit)
            # 달라는 만큼 찼으면 더 볼 것이 없다. 흔한 길이고, 여기서 끝나야 싸다.
            if len(results) >= limit:
                return {"results": results, "polls": polls, "blocked": False}
            if results:
                # ★ 하나라도 잡히면 곧장 돌아가던 것이 고장이었다(2026-08-08).
                #
                # 반쯤 그려진 화면의 첫 결과 하나를 잡고 끝내 버린다. limit=10 인데
                # 1건을 받고 status ok 로 끝난 실측이 있다 — 같은 질의가 다른 시점엔
                # 8건이었다. "덜 그려졌다"를 "결과가 적다"로 내보내는 것이고, 이건
                # 봇 검사를 "결과 0건"으로 읽던 것과 같은 계열이다.
                #
                # 그렇다고 limit 이 찰 때까지 기다리면 안 된다. 정말 3건뿐인 질의에서
                # 매번 타임아웃을 다 쓰게 된다. 그래서 **자라기를 멈출 때까지**만 본다.
                if len(results) <= previous:
                    return {"results": results, "polls": polls, "blocked": False}
                previous = len(results)
            elif self._search_blocked(page):
                return {"results": [], "polls": polls, "blocked": True}
            if time.monotonic() >= deadline:
                return {"results": results, "polls": polls, "blocked": False}
            time.sleep(0.3)

    # 이만큼 잡혔으면 목록이 그려진 것으로 본다(판정기가 목록으로 치는 줄 수와 같다).
    _DRAWN_ROWS = 3
    _DRAWN_POLL_MS = 300

    def _results_once_drawn(self, page: Any, *, limit: int) -> list[dict[str, Any]]:
        """사이트 목록을 **그려진 뒤에** 센다. 이미 그려져 있으면 한 번에 끝난다.

        ★ 2026-10-13 가격 조사 판을 까닭별로 가르다 찾음. 재는 판의 11번가 사이트 검색 190번 중 15번이 0건이었고, 그중
          12번은 요소 13~28개 · 제목이 아직 「11번가 | 검색결과」인 **껍데기**였다(결과가 있을 때는 요소 중간값 404개).
          그 화면은 링크 7개짜리 문서가 먼저 오고 결과는 그 뒤에 그려진다(한가할 때 0.7~1.1초 — 재 봄). 여기는 Enter 뒤
          1.2초 고정으로 기다렸다 한 번 셌고, 모델이 도는 동안은 그보다 늦어 「이 사이트가 직접 준 목록이다(0건)」이 됐다.
          `_wait_for_results`(검색엔진 · 08-06)와 같은 고장이 사이트 검색 쪽에 남아 있던 것이다.

        - 세 줄 이상 잡혔으면 그대로 돌려준다 — 흔한 길에 왕복을 보태지 않는다.
        - 모자라면 짧게 다시 본다. **자라기를 멈추면** 끝(정말 두 건뿐인 검색에서 한도를 다 쓰지 않는다).
        - 한 줄도 없는데 화면이 「결과 없음」이라고 적었으면 기다리지 않는다.
        - 그 밖에는 화면 준비 한도(`browser_ready_timeout_ms`)까지만.
        """
        results = self._collect_results(page, limit=limit)
        if len(results) >= min(limit, self._DRAWN_ROWS):
            return results
        budget_ms = max(0, int(getattr(getattr(self, "config", None), "browser_ready_timeout_ms", 6000) or 0))
        deadline = time.monotonic() + budget_ms / 1000
        previous = -1
        for _ in range(budget_ms // self._DRAWN_POLL_MS):
            if results:
                if len(results) >= limit or len(results) <= previous:
                    break
                previous = len(results)
            elif self._page_says_no_results(page):
                break
            if time.monotonic() >= deadline:
                break
            try:
                page.wait_for_timeout(self._DRAWN_POLL_MS)
            except Exception:
                time.sleep(self._DRAWN_POLL_MS / 1000)
            results = self._collect_results(page, limit=limit)
        return results

    def _chrome_links(self, page: Any) -> set[str]:
        """머리말·메뉴·꼬리말 안에 있는 링크. 결과가 아니다."""
        found: set[str] = set()
        for frame in self._frames_of(page):
            try:
                for href in frame.evaluate(_CHROME_LINKS_JS) or []:
                    key = canonical_url(unwrap_redirect(str(href)))
                    if key:
                        found.add(key)
            except Exception:
                continue
        return found

    # 화면에서 **결과 목록**을 구조로 찾는다. 사이트 이름은 한 줄도 안 쓴다.
    #
    # ★ 왜 필요한가 (2026-08-12 실측). 한 번도 안 건드린 사이트 네 곳에 같은 고리를
    # 태웠더니 문은 다 열리는데 **1번이 전부 엉뚱**했다:
    #
    #     다나와 "무선마우스"  → 1번이 경쟁사(에누리) 광고
    #     교보문고 "회계"      → 1번이 "오늘의 미션"
    #     당근마켓 "책상"      → 1번이 "당근 알바"
    #
    # `collect_results` 는 검색엔진 SERP 용이라 "본문의 링크를 DOM 순서로"가 전부다.
    # 쇼핑몰·서점은 본문 앞머리가 배너·기획전·제휴광고라 그게 1번이 된다. 잡코리아가
    # 잘 됐던 건 목록이 마침 앞에 있어서였다 — 운이었다.
    #
    # 목록이란 것은 어디서나 같은 모양이다: **비슷하게 생긴 형제가 여러 개 반복되고
    # 각각이 링크를 품는다.** 그 묶음을 찾아 그 안에서만 순위를 매기면, 배너 하나짜리는
    # 애초에 후보가 안 된다. 팝업·검색칸을 푼 방식과 같은 계열이다.
    #
    # ★ 목록 **안에** 끼워 넣은 광고·이벤트 (2026-09-18 실측).
    #
    #     당근마켓 "책상"     40개 중 8개가 ader.naver.com · adoffice.11st.co.kr — 1번이 광고
    #     YES24 "파이썬"      2위가 event.yes24.com/bookBindService(분철 서비스)
    #     다나와 "무선마우스" event.danawa.com 하나가 상품 사이에
    #
    # 묶음 고르기는 옳았다. 광고가 같은 생김새의 칸을 빌려 쓰니 한 바구니다. 가르는 것은
    # 목적지다: 한 사이트의 상품 목록에서 **딴 사이트로 가는 항목**, 같은 사이트라도
    # **혼자만 딴 호스트로 가는 항목**은 끼워 넣은 것이다. 검색엔진 결과는 원래 딴 사이트로
    # 가니 이 사이트 항목이 75% 이상이고 모양이 60% 이상 모일 때만 거른다. 다나와 장터
    # (dmall, 9개)처럼 여럿이 같은 호스트면 둔다. 얼린 표본 8곳은 1번이 하나도 안 바뀌었다
    # (다나와 event 한 줄만 빠짐), 당근 실사이트는 40→32·1번이 매물로.
    #
    # ★ 광고 칸 **묶음** 자체가 1등이 되는 화면 (2026-09-18 네이버 검색 「파이썬 책」).
    #   ul.lst_type 47개가 전부 ader.naver.com 이고 보이는 글자는 "koreaitacademy.com"·"coupang.com" 이었다 — 광고주 주소를
    #   보여 주고 중계 주소로 보낸다. 보통 결과는 「위키독스 wikidocs.net›book」처럼 보이는 주소와 가는 곳이 같다.
    #   주소를 보여 준 항목이 둘 이상이고 그중 60% 이상이 딴 곳으로 가면 후보에서 뺀다. 전체 링크 대비로 재면 광고 카드 하나가
    #   링크를 여럿 내서 3/18 로 낮아 안 걸렸다(실측) — 주소를 보여 준 항목끼리 견준다.
    _RESULT_LIST_JS = r"""
    () => {
      const vis = (el) => {
        const r = el.getBoundingClientRect();
        if (r.width <= 1 || r.height <= 1) return false;
        const s = getComputedStyle(el);
        return s.visibility !== 'hidden' && s.display !== 'none';
      };
      const links = Array.from(document.querySelectorAll('a[href]')).filter(
        (a) => vis(a) && a.href && !a.href.startsWith('javascript')
      );
      if (links.length < 6) return null;

      // 링크에서 위로 올라가며 **형제가 셋 이상 반복되는** 첫 묶음을 찾는다.
      // 묶음(container)과, 그 안에서 이 링크가 든 **한 칸(card)** 을 같이 돌려준다.
      const groupOf = (a) => {
        let node = a;
        for (let i = 0; i < 8 && node.parentElement; i++) {
          const parent = node.parentElement;
          let same = 0;
          for (const child of parent.children) {
            if (child.tagName === node.tagName) same += 1;
          }
          if (same >= 3) return { container: parent, card: node };
          node = parent;
        }
        return null;
      };

      // ★ 네비게이션은 제외한다 (2026-08-12 실측). 당근마켓에서 카테고리 메뉴가
      // 진짜 목록을 이겼다 — 메뉴 링크10 평균 6자 vs 목록 링크4 평균 51자.
      const CHROME = 'header, nav, footer, aside, [role=banner], [role=navigation], [role=contentinfo]';

      // ★ **빈 클래스는 서명이 아니다** (2026-08-14 쿠팡).
      //
      // 서명이 같은 묶음은 아래에서 한 바구니로 합쳐진다. 당근마켓이 목록을 4개씩
      // 세 덩어리로 쪼개 놔서 넣은 규칙인데, 거기서는 덩어리마다 진짜 클래스가
      // 있었다. 클래스가 비면 `ul|` 하나로 **아무 상관 없는 통끼리 합쳐진다.**
      //
      // 쿠팡 검색 화면이 정확히 그 꼴이었다 — 통은 둘뿐인데 링크가 86개:
      //     카테고리 사이드바 <ul>  26개  '전체' '가전디지털' '로켓직구' …
      //     상품 목록 <ul>          60개  'UGREEN 유그린 5000DPI …'
      // 합쳐 놓으니 평균 글자수는 상품이 끌어올려 통과하고, 1번은 DOM 순서상 앞인
      // **메뉴의 '전체'** 가 됐다. 그 뒤 `browser_open_result` 가 카테고리 페이지를
      // 열어 상품인 줄 알고 읽었다(실측: /np/categories/510691, /np/campaigns/82).
      //
      // 클래스가 없으면 "같은 종류"라고 말할 근거 자체가 없으니 합치지 않는다.
      // 통 하나가 통째로 목록인 경우는 원래 합칠 필요도 없다.
      let serial = 0;
      const marks = new WeakMap();
      const signature = (el) => {
        const cls = (el.className || '').toString().trim().slice(0, 60);
        if (cls) return el.tagName.toLowerCase() + '|' + cls;
        let mark = marks.get(el);
        if (mark === undefined) { mark = serial++; marks.set(el, mark); }
        return el.tagName.toLowerCase() + '|#' + mark;
      };

      // 목적지의 **모양**. 진짜 목록은 같은 종류의 상세 페이지로 간다.
      //
      // 앞 두 칸만 본다(/prod/123 → prod, /kr/buy-sell/원목-책상-xy → kr/buy-sell).
      // ★ 처음에는 숫자만 지웠는데, 주소에 **슬러그**를 쓰는 사이트에서는 항목마다
      // 모양이 달라져 동질성이 2% 로 떨어졌다(당근마켓 실측). 경쟁 묶음이 없어서
      // 이겼을 뿐, 다른 화면이었으면 네비에 졌을 것이다.
      const shapeOf = (href) => {
        try {
          const u = new URL(href, location.href);
          const parts = u.pathname.split('/').filter(Boolean).slice(0, 2)
            .map((part) => (/\d/.test(part) || part.length > 24 ? '#' : part));
          return u.host + '/' + parts.join('/');
        } catch (e) { return href.slice(0, 40); }
      };

      // ★ 지금 보고 있는 페이지로 되돌아가는 링크는 항목이 아니다 (2026-08-12).
      //
      // 광고를 걷어내고 나니 이번엔 **검색 페이지 자체**가 1번이 됐다(다나와·교보문고).
      // 목록 안에는 쪽번호·정렬·필터처럼 같은 주소로 되돌아가는 링크가 섞여 있고,
      // 그것들은 경로가 같아 동질성 점수까지 끌어올린다. 항목은 **다른 곳으로** 간다.
      //
      // ★ 다만 이 판정은 `shapeOf` 로 하면 안 된다. 두 판정은 목적이 다르다:
      // 동질성은 **거칠게**(앞 두 칸) 묶어야 슬러그 주소가 한 덩어리가 되고,
      // 자기 페이지는 **정확하게** 봐야 항목을 안 버린다. 하나로 합쳤더니
      // 당근마켓에서 매물 60개가 통째로 사라졌다(실측):
      //     현재  /kr/buy-sell/s/?search=책상      -> 앞 두 칸 kr/buy-sell
      //     매물  /kr/buy-sell/원목-책상-xxx/      -> 앞 두 칸 kr/buy-sell  (같아져 버림)
      // 경로 전체로 보면 둘은 다르고, 쪽번호(?page=2)는 여전히 같다.
      const pathOf = (href) => {
        try {
          const u = new URL(href, location.href);
          return u.host + u.pathname.replace(/\/+$/, '');
        } catch (e) { return href.slice(0, 60); }
      };
      const here = pathOf(location.href);
      const siteOf = (host) => {
        const parts = (host || '').toLowerCase().split('.').filter(Boolean);
        if (parts.length <= 2) return parts.join('.');
        const tld = parts[parts.length - 1], second = parts[parts.length - 2];
        const take = (tld.length === 2 && second.length <= 3) ? 3 : 2;
        return parts.slice(-take).join('.');
      };
      const hostOf = (href) => { try { return new URL(href, location.href).host.toLowerCase(); } catch (e) { return ''; } };
      // ★ 광고 칸의 모양: **보이는 글자는 광고주 주소**인데 **링크는 중계 주소**로 간다(실측은 위 파이썬 주석).
      //   보통 검색 결과는 보이는 주소와 가는 곳이 같은 사이트다.
      const DOMAIN_LINE = /^(?:https?:\/\/)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})(?:[\/›\s].*)?$/i;
      // 보이는 주소가 없으면 null, 있으면 가는 곳과 **다른 사이트인가**(true/false).
      const namesAnotherSite = (text, href) => {
        const target = siteOf(hostOf(href));
        let named = null;
        for (const line of (text || '').split(/\n/)) {
          const m = line.trim().match(DOMAIN_LINE);
          if (!m) continue;
          if (siteOf(m[1]) !== target) return true;
          named = false;
        }
        return named;
      };

      const tally = new Map();
      for (const a of links) {
        const group = groupOf(a);
        const container = group && group.container;
        if (!container || container.closest(CHROME)) continue;
        if (pathOf(a.href) === here) continue;
        const key = signature(container);
        let entry = tally.get(key);
        if (!entry) { entry = { links: [], chars: 0, items: 0, shapes: new Map(), adHrefs: new Set(), namedHrefs: new Set(), cards: new Map() }; tally.set(key, entry); }
        const length = (a.innerText || '').trim().length;
        entry.cards.set(group.card, Math.max(entry.cards.get(group.card) || 0, length));
        const named = namesAnotherSite(a.innerText, a.href);
        if (named !== null) entry.namedHrefs.add(a.href);
        if (named === true) entry.adHrefs.add(a.href);
        // ★ 한 장(카드)이 링크를 여러 개 내는 사이트가 있다 — 사람인 div.item_recruit
        //   하나가 공고제목·회사명·기업정보 셋을 낸다. 그래서 목록에 "(주)푸른빛에너지"·
        //   "기업정보"가 공고와 나란히 섞인다.
        //
        //   카드마다 대표 하나(글자가 제일 긴 것)만 남기는 규칙을 넣어 봤다가 **되돌렸다**
        //   (2026-08-12). 사람인은 깨끗해졌는데 교보문고와 다나와가 함께 망가졌다 —
        //   그 카드들에서는 제일 긴 글자가 제목이 아니라 브랜드·기획전이었고, 1번이
        //   "바로펀딩"·"Bravotec 브랜드로그"로 바뀌었다.
        //
        //   섞이는 것은 성가신 정도지만(1번은 여전히 진짜 항목이다) 1번이 엉뚱해지는
        //   것은 답을 통째로 틀리게 만든다. 고칠 값보다 깨뜨릴 값이 크면 안 고친다.
        entry.links.push({ href: a.href, name: (a.innerText || '').trim().slice(0, 180), card: group.card, length });
        entry.chars += length;
        entry.items += 1;
        const shape = shapeOf(a.href);
        entry.shapes.set(shape, (entry.shapes.get(shape) || 0) + 1);
      }
      let best = null, bestScore = 0;
      for (const [, entry] of tally) {
        if (entry.links.length < 3) continue;
        // 광고 칸 묶음 — 주소를 보여 주는 항목이 둘 이상인데 그 60% 이상이 **보여 준 곳과 다른 곳으로** 가면 후보가 아니다.
        // (광고 카드 하나가 링크를 여럿 내서 전체 링크 대비로 재면 3/18 로 낮았다 — 주소를 보여 준 항목끼리 견준다.)
        if (entry.adHrefs.size >= 2 && entry.adHrefs.size / entry.namedHrefs.size >= 0.6) continue;
        let average = entry.chars / entry.items;
        // ★ 글자 길이가 주된 신호다. 목록 항목에는 제목·가격·지역이 붙어 길고,
        // 메뉴는 낱말 하나라 짧다. 개수로 재면 메뉴가 이긴다.
        if (average < 12) {
          // ★ 칸마다 **짧은 부속 링크**가 붙은 목록은 링크 평균이 메뉴처럼 짧아진다 (2026-10-05 GitHub 인기 목록).
          //   칸 하나가 「Star」·「earthtojake / text-to-cad」·「16,826」·「1,739」 넷을 내서 평균 9.3자 → 목록이 통째로
          //   빠졌고, `browser_open_result` 가 눈앞의 목록에 `no_result_list` 를 세 번 냈다(추천 모델이 거기서 포기).
          //   **칸마다 제일 긴 글자**로 보면 23.8자다. 메뉴는 칸에 링크가 하나라 그렇게 봐도 여전히 짧다.
          //   이렇게 살린 묶음에서만 부속 링크(12자 미만이고 그 칸에서 제일 길지도 않은 것)를 뺀다 —
          //   평균으로 통과하던 묶음은 손대지 않는다(카드 대표만 남기는 규칙은 교보·다나와 1번을 바꿔 되돌린 적이 있다).
          let longest = 0;
          for (const [, value] of entry.cards) longest += value;
          if (entry.cards.size < 3 || longest / entry.cards.size < 12) continue;
          const main = entry.links.filter((it) => it.length >= 12 || it.length === entry.cards.get(it.card));
          if (main.length < 3) continue;
          entry.links = main;
          entry.items = main.length;
          entry.chars = 0;
          entry.shapes = new Map();
          for (const it of main) {
            entry.chars += it.length;
            const shape = shapeOf(it.href);
            entry.shapes.set(shape, (entry.shapes.get(shape) || 0) + 1);
          }
          average = entry.chars / entry.items;
        }
        // ★ 그런데 개수와 길이만으로도 진다 (2026-08-12 다나와 실측).
        // 상품 카드 하나가 링크를 여러 개 낸다(제목·브랜드로고·의견수·쇼핑몰).
        // 그래서 **부속 링크가 많은 묶음**이 이겼다:
        //     n=241 평균12자 prod_info      "브랜드로그 | 의견194"   <- 이김
        //     n=76  평균15자 prod_main_info "ATK VXE R1 SE+ 유무선"  <- 진짜 목록
        // 부속 링크는 목적지가 제각각이고, 진짜 항목은 한 모양으로 모인다.
        let common = 0;
        for (const [, count] of entry.shapes) common = Math.max(common, count);
        const homogeneity = common / entry.items;
        const score = entry.links.length * Math.min(average, 60) * homogeneity;
        if (score > bestScore) { bestScore = score; best = entry; }
      }
      if (!best) return null;

      // ★ 목록 안에 끼워 넣은 광고·이벤트 — 실측과 이유는 이 JS 위 파이썬 주석에.
      // 이 사이트로 가는 항목이 대부분이고 목적지 모양이 한 가지로 모일 때만 거른다.
      // 여럿이 같은 호스트면 하위 목록으로 보고 둔다. 셋이 안 남으면 거르지 않는다.
      const items = best.links;
      const homeSite = siteOf(location.host);
      const onSite = items.filter((it) => siteOf(hostOf(it.href)) === homeSite);
      let kept = items;
      if (items.length >= 4 && onSite.length / items.length >= 0.75) {
        const shapeCount = new Map();
        for (const it of onSite) { const s = shapeOf(it.href); shapeCount.set(s, (shapeCount.get(s) || 0) + 1); }
        let top = 0;
        for (const [, c] of shapeCount) top = Math.max(top, c);
        if (top / onSite.length >= 0.6) {
          const hostCount = new Map();
          for (const it of onSite) { const h = hostOf(it.href); hostCount.set(h, (hostCount.get(h) || 0) + 1); }
          // 링크가 같은 칸 하나에서 두 번 나오는 일이 흔하다(제목·가게 이름) — 주소로 센다.
          const hrefsOf = new Map();
          for (const it of onSite) {
            const h = hostOf(it.href);
            if (!hrefsOf.has(h)) hrefsOf.set(h, new Set());
            hrefsOf.get(h).add(it.href);
          }
          const filtered = onSite.filter((it) => hrefsOf.get(hostOf(it.href)).size > 1 || hostCount.size === 1);
          if (filtered.length >= 3) kept = filtered;
        }
      }
      // 같은 생김새(tag+class)의 묶음을 **합쳐서** 돌려준다. 당근마켓은 목록이
      // 4개씩 세 덩어리로 쪼개져 있어, 하나만 고르면 4건밖에 못 얻는다.
      // 칸(DOM 요소)은 안에서만 쓴다 — 밖으로는 주소와 이름만.
      return kept.slice(0, 80).map((it) => ({ href: it.href, name: it.name }));
    }
    """
    _RESULT_LIST_JS = _deep_js(_RESULT_LIST_JS)

    # 「결과 없음」 문구. 화면에 **보이는** 글에서만 찾는다(innerText — 숨은 템플릿 글은 안 센다).
    _NO_RESULTS_JS = r"""
    () => {
      const root = document.querySelector('main, [role=main]') || document.body;
      return ((root && root.innerText) || '').slice(0, 30000);
    }
    """
    _NO_RESULTS_TEXT = re.compile(
        r"(\bno\s+(?:results|matches|matching\s+\w+|items|products|models|datasets|repositories)(?:\s+(?:were\s+)?found)?\b"
        r"|\b0\s+results\b|did\s+not\s+match\s+any|\bnothing\s+(?:was\s+)?found\b"
        r"|검색\s*결과가\s*없|결과가\s*없습니다|일치하는\s*\S{0,10}\s*없|검색된\s*\S{0,10}\s*없|총\s*0\s*건)",
        re.IGNORECASE,
    )

    def _page_says_no_results(self, page: Any) -> bool:
        try:
            text = str(page.evaluate(self._NO_RESULTS_JS) or "")
        except Exception:
            return False
        return bool(self._NO_RESULTS_TEXT.search(text))

    def _result_list_rows(self, page: Any) -> list[dict[str, Any]]:
        """결과 목록의 항목들을 **그대로** 받아 온다(`name`·`href`).

        ★ 처음에는 주소만 받아서 `_frame_elements` 결과를 걸러 썼는데, 그 방식은
        **예산에 막힌다**(2026-08-12 다나와 실측). 다나와 검색 화면은 링크가 1,561개인데
        수집 예산은 144개이고, 앞에 스펙 필터가 링크 724개를 깔고 있어서 예산이 거기서
        전부 소진된다. 판정기가 상품 묶음(75개)을 정확히 골라 놨는데도 그 주소들이
        rows 에 아예 없어 좁히기가 무의미했다.

        묶음 상한(`group_cap`)으로 막아 보려다 더 나빠졌다 — 우리가 원하는 것이 바로
        그 큰 묶음이라 잘라 내면 결과가 사라진다(당근마켓 12건 → 0건).

        판정기는 이미 브라우저 안에서 **모든 링크를 한 번에** 훑는다. 그러니 항목을
        직접 받아 오면 예산 문제 자체가 없어진다. 왕복도 한 번뿐이다.
        """
        found = None
        for frame in self._frames_of(page):
            try:
                found = frame.evaluate(self._RESULT_LIST_JS)
            except Exception:
                continue
            if found:
                break
        rows: list[dict[str, Any]] = []
        for item in found or []:
            # 페이지가 무엇을 돌려주든 여기서 넘어지지 않는다 — 주소만 있으면 쓴다.
            if isinstance(item, dict):
                href, name = str(item.get("href") or ""), str(item.get("name") or "")
            else:
                href, name = str(item or ""), ""
            if href:
                rows.append({"name": name, "href": href, "ref": ""})
        return rows

    def _remember_results_origin(self, page: Any) -> None:
        """이 순위를 **어느 화면에서** 세웠는지 적어 둔다.

        `forget_results()` 는 판이 바뀔 때 부르는 것인데, 그 호출이 `agent.run`
        한 곳에만 있다. 그래서 `/v1/tools/execute` 나 MCP 처럼 **잡 없이** 부르는
        길로 들어오면 앞 판의 순위가 그대로 남는다 — 2026-08-16 실측: 사람인 검색
        결과가 눈앞에 있는데 `browser_open_result(1)` 이 **쿠팡 상품**을 열었다.

        판(잡)으로 못 가르면 화면으로 갈라야 하는데, "지금 화면과 다르면 버린다"는
        안 된다(결과→상세로 들어간 뒤 rank 2 를 여는 것이 이 도구의 존재 이유다).
        그래서 **어디서 세운 목록인지**를 남긴다 — 그 사이트 안에 있는 동안은 살고,
        딴 사이트의 목록 앞에 서면 죽는다.
        """
        try:
            self._results_origin_host = (urlparse(str(page.url or "")).hostname or "").casefold()
            # javascript: 결과는 그 목록 페이지의 함수로만 따라갈 수 있다 — 상세로 넘어간 뒤 다음 순위를 열려면 돌아올 자리가 필요하다.
            self._results_origin_url = str(page.url or "")
        except Exception:
            self._results_origin_host = ""
            self._results_origin_url = ""
        # 새 순위다 — 「떠났다」 표시를 지우고, 이 목록 화면에 **어떤 주소들이 있었는지** 적어 둔다(`_note_address_departure`).
        self._results_departed_to = ""
        self._results_origin_links = self._links_on(page)

    #: 목록 화면의 링크를 적어 둘 때의 상한. 다나와 검색 화면이 1,561개였다(2026-08-12).
    _ORIGIN_LINKS_MAX = 5000

    def _links_on(self, page: Any) -> frozenset[str]:
        """이 화면에 걸린 주소들(정리한 꼴). 못 읽으면 빈 묶음 — 그때는 「떠났나」를 판단하지 않는다."""
        try:
            hrefs = page.evaluate(
                "(cap) => [...document.querySelectorAll('a[href]')].slice(0, cap).map(a => a.href)", self._ORIGIN_LINKS_MAX)
        except Exception:
            return frozenset()
        return frozenset(key for key in (canonical_url(str(href or "")) for href in hrefs or []) if key)

    def _noting_departure(self, page: Any, result: Any) -> Any:
        try:
            self._note_address_departure(self._page or page)
        except Exception:  # noqa: BLE001 — 표시 하나 때문에 열기가 죽으면 안 된다
            pass
        return result

    def _note_address_departure(self, page: Any) -> None:
        """모델이 **주소를 직접 쳐서** 간 곳이, 순위를 세운 목록과 무관한 곳인가.

        ★ 2026-10-05 AWS 영어 윈도우(c3c1b051). GitHub 사이트 검색으로 순위를 세운 뒤 모델이 주소로 인기 목록
          (`github.com/trending/python`)에 갔다. 거기서 「1·2·3번을 열자」며 `browser_open_result` 를 불렀는데 도구는
          **검색 목록의** 1·2·3번(`bonfy/github-trending` · `topics/python` · `topics/github-trending`)을 열었다.
          「3개 읽음」이 채워졌고 답은 「각 저장소 페이지를 열어 확인했다」고 했다 — 연 것은 딴 페이지 셋이었다.

        「지금 화면이 목록이면 그것을 쓴다」로는 못 고친다 — 실측(2026-10-05): 판정기는 GitHub 인기 목록·해커뉴스 첫
        화면을 0줄로, GitHub 저장소·스토어 상세·허깅페이스 모델 페이지를 5~18줄 「목록」으로 본다. 그 규칙이면 상세를
        연 뒤 다음 순위를 여는 정상 흐름이 깨진다. 그래서 **모델의 행동**으로 가른다:

        - 주소로 연 곳이 순위 속 주소이거나, 그 목록 화면에 걸려 있던 주소면 — 목록에서 고른 것이다. 그대로 둔다.
        - 그 목록 화면과 **같은 경로**면(다음 쪽 · 목록과 상세가 같은 경로인 사이트) — 건드리지 않는다.
        - 그 밖이면 스스로 다른 곳으로 떠난 것이다. 적어 두고, 거기서 순위를 부르면 추측하지 않는다(`_open_result`).
        """
        origin = canonical_url(str(getattr(self, "_results_origin_url", "") or ""))
        links = getattr(self, "_results_origin_links", None) or frozenset()
        if not self._last_results or not origin or not links:
            return
        here = canonical_url(str(getattr(page, "url", "") or ""))
        if not here or here == origin:
            self._results_departed_to = ""
            return
        if here in links or any(
            canonical_url(str(item.get("url") or item.get("href") or "")) == here for item in self._last_results
        ):
            return
        if urlparse(here).path.rstrip("/") == urlparse(origin).path.rstrip("/"):
            return
        self._results_departed_to = here

    def _standing_where_it_departed_to(self, page: Any) -> str:
        """순위와 무관한 곳으로 떠난 뒤 **아직 그 자리**면 그 주소. 목록으로 돌아왔거나 순위 속 페이지에 있으면 빈 글."""
        departed = str(getattr(self, "_results_departed_to", "") or "")
        if not departed or not self._last_results:
            return ""
        here = canonical_url(str(getattr(page, "url", "") or ""))
        origin = canonical_url(str(getattr(self, "_results_origin_url", "") or ""))
        links = getattr(self, "_results_origin_links", None) or frozenset()
        if not here or here == origin or here in links or any(
            canonical_url(str(item.get("url") or item.get("href") or "")) == here for item in self._last_results
        ):
            self._results_departed_to = ""
            return ""
        return here

    def _results_are_someone_elses(self, page: Any) -> bool:
        """갖고 있는 순위가 **지금 보고 있는 사이트의 것이 아닌가.**

        딴 사이트에 서 있다는 것만으로는 부족하다 — 결과에서 상세로 넘어가면
        호스트가 바뀌는 것이 정상이다(검색엔진 SERP 가 그렇다). 그래서 둘을 같이 본다:
        **딴 사이트이면서, 그 화면이 자기 목록을 갖고 있을 때**만 남의 것으로 친다.
        사람이 하는 판단과 같다 — 눈앞에 목록이 있으면 그것의 세 번째를 누른다.
        """
        if not self._last_results or not self._results_origin_host:
            return False
        try:
            here = (urlparse(str(page.url or "")).hostname or "").casefold()
        except Exception:
            return False
        if not here or here == self._results_origin_host:
            return False
        # 검색 결과를 하나 연 직후에는 호스트가 달라지는 것이 정상이다. 상세 화면의
        # "관련 글"·"추천 상품" 묶음이 구조적인 목록처럼 보여도, 지금 주소 자체가
        # 기억한 순위 중 하나라면 **그 순위를 타고 온 상세**이지 새 목록이 아니다.
        # 이 예외가 없으면 rank 1 을 연 뒤 rank 2 를 열 때 상세의 링크로 순위를
        # 갈아치운다. 반대로 사용자가 정말 다른 사이트의 새 목록으로 이동했다면
        # 현재 주소가 옛 순위에 없으므로 아래의 기존 판정이 그대로 작동한다.
        try:
            current = canonical_url(str(page.url or ""))
        except Exception:
            current = ""
        if current and any(
            canonical_url(str(item.get("url") or item.get("href") or "")) == current
            for item in self._last_results
        ):
            return False
        # ★ 「자기 목록」은 **반복 카드가 실제로 잡힌 화면**만이다 (2026-10-01 운영 판 f7c9e4e3).
        #   검색 결과에서 블로그 글(dcordero.me)로 바로 옮겨 간 뒤 rank 1·4 를 부르자 둘 다 `no_result_list` 였다 —
        #   넓은 수집(`_collect_results`)이 글의 메뉴·관련 글 링크 몇 개를 「남의 검색 목록」으로 봐서 기억한 순위를
        #   지웠다. 화면 하단 「같은 곳에서 계속 막히고 있습니다」 경고도 이것 때문에 떴다. 순위 복구
        #   (`_recover_results_for_open`)가 이미 쓰는 엄격한 기준을 여기도 쓴다 — 사람인 검색 목록 같은 진짜 남의
        #   목록(반복 카드)은 그대로 잡힌다.
        return len(self._result_list_rows(page)) >= 3

    # 어느 사이트에 **사람이 검토한 검색 절차**가 있는지. `SiteRecipeTools.register`
    # 가 채운다(레시피가 브라우저에게 알려 주는 한 방향이다 — 반대로 하면 순환한다).
    _recipe_search: dict[str, str] = {}

    def _recipe_search_hint(self, host: str) -> str:
        """이 사이트에 **이미 되는 길**이 있으면 그것부터 알려 준다.

        ## 왜 (2026-08-16 실측)

        "사람인에서 '연구비 관리'로 정규직 3개" 판이 이렇게 샜다:

            2 browser_site_search   실패        <- 사람인은 검색칸이 width=0 이라 원래 안 된다
            6~8 ui_find_target      j35, j35, j33
            11 browser_fill         ref=j79     <- 비전이 찾은 것과 **다른 칸**
            12 browser_press Enter
            -> 쿠팡풀필먼트·토목시공·배민캡틴이 나왔다(연구비와 무관)

        사람인에는 그 실패 때문에 **사람이 만들어 둔 레시피**가 이미 있다
        (`recipes/saramin.json` 의 `search_jobs`). 그 길을 두고 손으로 더듬다가
        엉뚱한 칸을 채운 것이다. 도구가 실패하는 그 자리에서 되는 길을 알려 주면
        더듬을 이유가 없다 — 이 저장소가 여러 번 확인한 규율(사고 R)이다.
        """
        for site_host, call in self._recipe_search.items():
            if host == site_host or host.endswith("." + site_host):
                return (
                    f" ★ 이 사이트에는 **사람이 검토해 둔 검색 절차**가 있다 — `{call}` 를 써라."
                    " 이 사이트의 검색칸은 화면에 안 보이게 접혀 있어서 손으로는 잘 안 된다."
                )
        return ""

    def _collect_results(self, page: Any, *, limit: int = 12) -> list[dict[str, Any]]:
        """지금 화면이 검색 결과라면, 결과 목록으로 바꿔서 돌려준다."""
        rows: list[dict[str, Any]] = []
        for index, frame in enumerate(self._frames_of(page)):
            rows.extend(
                self._frame_elements(
                    frame,
                    frame_label=self._frame_label(frame, index),
                    frame_index=index,
                    # 앞부분이 전부 네비게이션이라 넉넉히 훑어야 결과에 닿는다.
                    # 실측에서 네이버는 첫 결과가 j21 이었다.
                    #
                    # 8배로는 모자란다. 카드 하나가 링크를 8~9개 낸다(홈 2 + 글 여러
                    # 개)는 것을 2026-08-07 에 쟀고, 홈을 글에 합치기 시작한 뒤로는
                    # 그 링크들이 순위를 채워 주지 않으므로 limit 만큼 모으려면 더
                    # 훑어야 한다. 같은 질의 · limit=10 실측:
                    #
                    #     8배    결과 6건    23.1s
                    #     12배   결과 10건   28.5s
                    #     16배   결과 10건   27.3s   <- 더 훑어도 10건이 상한
                    budget=max(limit * 12, 60),
                    start=len(rows),
                    include_box=False,
                )
            )
        chrome = self._chrome_links(page)
        if chrome:
            rows = [
                row
                for row in rows
                if canonical_url(unwrap_redirect(str(row.get("href") or ""))) not in chrome
            ]
        # ★ 이동용 `javascript:go_view(N)` 링크도 결과다 (2026-10-02 K-Startup 4차 판 70a447c4).
        #   주소 판정(`canonical_url`)이 http 만 받아서 K-Startup 목록 공고가 **전부** 빠졌고, 사이트 검색 「AI」가 공고를 띄워
        #   놓고 `result_count: 0` 을 보고했다. 모델은 그 0 을 믿고 검색칸·필터를 35걸음 다시 만졌다. 판정용으로만 그 사이트의
        #   가짜 주소를 씌우고, 순위에는 원래 링크를 돌려놓는다 — 여는 길은 `_open_result` 가 안다(함수·통한 길 기억).
        js_links: dict[str, str] = {}
        here = urlparse(str(getattr(page, "url", "") or ""))
        origin = f"{here.scheme or 'https'}://{here.netloc}" if here.netloc else ""

        def masked(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not origin:
                return items
            out = []
            for row in items:
                href = str(row.get("href") or "")
                found = _js_nav_link(href) if href.lower().startswith("javascript:") else None
                if found:
                    stand_in = f"{origin}/__js_link__/{found[0]}/" + "/".join(quote_plus(str(arg)) for arg in found[1])
                    js_links[stand_in] = href.strip().rstrip(";")
                    row = {**row, "href": stand_in}
                out.append(row)
            return out

        rows = masked(rows)
        # ★ 표식으로 거를 사이트는 **거르기 전에 자르지 않는다** (2026-10-05 arXiv 실측). 15개로 먼저 자르면 그 안에 논문 링크가
        #   하나뿐이라(건너뛰기·날짜·pdf·저자가 앞을 채운다) 순위가 1번 하나만 남았다. 넉넉히 모으고, 자르는 것은 거른 뒤에 한다.
        markers = self._result_markers_for(page)
        gather = limit * 8 if markers else limit
        wide = [item.as_dict() for item in collect_results(rows, limit=gather, visited=self._visited)]
        # 목록을 찾았으면 **그 항목들로** 순위를 매긴다. 다만 결과가 부실하면 예전
        # 것을 쓴다 — 새 판정이 조용히 결과를 지우는 일이 없어야 한다.
        listed = masked(self._result_list_rows(page))
        # 가상 스크롤을 모아 둔 것이 **이 화면의 것이면** 앞에 붙인다 — 지금 DOM 에는 마지막 몇 줄만 남아 있다.
        virtual = getattr(self, "_virtual_rows", None)
        if virtual and getattr(self, "_virtual_rows_url", "") == str(getattr(page, "url", "") or ""):
            known = {row["href"] for row in virtual}
            listed = list(virtual) + [row for row in listed if row.get("href") not in known]
        if chrome:
            # ★ 머리말·메뉴 걸러내기는 **이 경로에도** 걸어야 한다. 판정기의 네비
            # 제외는 `header`·`nav` 같은 시맨틱 태그를 보는데, 그걸 안 쓰는 사이트가
            # 흔하다(다나와 실측: 네비 제외 0건). `_chrome_links` 는 `#gnb`·`.gnb`·
            # `#lnb` 같은 실제 관용구까지 본다 — 둘은 겹치는 게 아니라 보완이다.
            listed = [
                row
                for row in listed
                if canonical_url(unwrap_redirect(str(row.get("href") or ""))) not in chrome
            ]
        if len(listed) < 3:
            selected = wide
        else:
            narrowed = [
                item.as_dict() for item in collect_results(listed, limit=gather, visited=self._visited)
            ]
            selected = narrowed if len(narrowed) >= 3 else wide
        # 사람인 카드처럼 공고·회사·기업정보 링크가 한 장에 함께 있는 사이트는
        # 범용 수집 결과를 그대로 순위로 쓰면 회사정보가 2·4번에 끼어든다. 사람이
        # 검토한 레시피가 상세 URL 모양을 안다면 **모든 순위 생성 경로**가 그 지식을
        # 공유해야 한다. site_run 직후에만 거르면 open_result 복구에서 다시 샌다.
        if js_links:
            for item in selected:
                original = js_links.get(str(item.get("url") or ""))
                if original:
                    item["url"] = original
        picked = self._filter_reviewed_results(selected, markers, limit=limit)
        if markers and len(picked) < 3 and selected is not wide:
            # 표식을 아는 사이트에서 판정기가 엉뚱한 묶음(arXiv 의 저자 링크)을 골랐으면 걸러서 남는 것이 없다.
            # 그때는 화면 전체에서 표식에 맞는 것을 쓴다 — 항목이 **있는데** 「목록 없음」이라고 하지 않는다.
            from_wide = self._filter_reviewed_results(wide, markers, limit=limit)
            if len(from_wide) > len(picked):
                picked = from_wide
        return picked

    def _read_selectors_for(self, url: str) -> list[str]:
        """이 주소의 화면에서 레시피가 읽으라고 적어 둔 자리(선택자)들. 없으면 빈 목록 — 그러면 본문을 예전대로 고른다."""
        try:
            parsed = urlparse(str(url or ""))
            host = _host_of_url(str(url or ""))
        except Exception:
            return []
        for site_host, places in (getattr(self, "_recipe_read_selectors", None) or {}).items():
            if host == site_host or host.endswith("." + site_host):
                for prefix, selectors in places:
                    if parsed.path.startswith(prefix):
                        return list(selectors)
        return []

    def _result_markers_for(self, page: Any) -> list[str]:
        try:
            host = _host_of_url(str(getattr(page, "url", "") or ""))
        except Exception:
            return []
        for site_host, markers in getattr(self, "_recipe_result_markers", {}).items():
            if host == site_host or host.endswith("." + site_host):
                return list(markers)
        # 검토한 레시피가 없어도 **상세 주소의 표식만** 적어 둔 사이트가 있다(`result_links` — arXiv·네이버 뉴스).
        from .result_links import markers_for

        return markers_for(host)

    def _recover_results_for_open(self, page: Any, *, limit: int = 15) -> list[dict[str, Any]]:
        """현재 화면이 **구조적인 목록**일 때만 순위를 복구한다.

        `_collect_results` 의 넓은 폴백은 검색엔진처럼 구조가 제각각인 화면을 읽기
        위한 것이다. 그것을 open_result 복구에 그대로 쓰면 일반 상세 페이지의
        메뉴·회사 홈페이지 링크까지 "검색 결과"가 된다(2026-08-17 사람인 실측).
        복구는 반복 카드가 실제로 잡힌 화면으로 좁히고, 수집 자체는 기존 경로를 써
        검토 레시피의 URL 필터까지 보존한다.
        """
        if len(self._result_list_rows(page)) < 3:
            return []
        # ★ **세 번째 문** (2026-09-05). 날짜 교체를 `browser_site_search` 와
        #   `browser_load_more` 에만 걸었더니, 라이브에서 모델이 셋째 길로 갔다 —
        #   홈에서 달력을 두드리고 클릭으로 목록에 도착했다. 두 도구 어느 것도
        #   안 불렸으니 교체가 한 번도 안 돌았다.
        #
        #   방금 고친 것과 **같은 종류의 실수다**: 문에 걸면 다른 문으로 들어온다.
        #   여기는 「화면이 목록이다」가 확정된 자리라, 어떤 길로 왔든 지난다.
        self._apply_requested_dates_here(page)
        recovered = self._collect_results(page, limit=limit)
        # 클릭만으로 목록에 도착한 판도 여기를 지난다.
        self._learn_search_url(page, len(recovered))
        return recovered

    def _mark_visited(self, url: str) -> None:
        key = canonical_url(url)
        if key and key not in self._visited:
            self._visited.append(key)
            del self._visited[:-200]

    def _remember_where_it_landed(self, page: Any, match: dict[str, Any], opened_url: str) -> None:
        """목적지를 숨긴 링크로 열었으면 **도착한 주소를 그 순위에 적는다.**

        ★ 2026-10-05 9B 판 셋(8fc59c35 · b8cfa1bc · 107e821c): 구글이 준 `google.com/goto?url=…` 로 1번을 열고 2·3번을 부르자
          구글의 2·3번이 아니라 **방금 들어간 사이트 안의 링크**가 열렸다(세 판 모두 한 사이트 안에서만 돌았다). 순위 속 주소가
          전부 구글 것이라, 도착한 사이트를 「이 순위를 타고 온 상세」로 못 알아보고 남의 목록으로 봐 순위를 갈아치웠다
          (`_results_are_someone_elses` 는 지금 주소가 순위 속 주소인지를 본다). 열어 보면 어디인지 안다 — 그것을 적는다.
        """
        if not opaque_outbound(opened_url):
            return
        try:
            landed = str(getattr(page, "url", "") or "")
        except Exception:
            return
        if landed.startswith(("http://", "https://")) and not opaque_outbound(landed):
            match["via"] = opened_url
            match["url"] = landed
            self._mark_visited(landed)

    def _open_result(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """마지막 검색 결과의 N번째로 들어간다.

        ref 로 누르지 않고 주소로 여는 것은 일부러다. ref 는 그 화면에만 찍어 둔
        표식이라 한 번 이동하면 사라지고, 뒤로 돌아오면 페이지가 다시 그려지면서
        번호도 달라진다. 순위는 검색 한 번 동안 변하지 않는다.
        """
        rank = int(arguments.get("rank") or 0)
        if self._results_are_someone_elses(page):
            # 남의 순위다. 조용히 쓰면 지목한 사이트를 두고 딴 데를 연다.
            self._last_results = []
        standing = self._standing_where_it_departed_to(page)
        if standing:
            # 추측해서 열지 않는다. 지금 화면의 N번째인지, 앞 검색 목록의 N번째인지는 모델만 안다.
            origin = str(getattr(self, "_results_origin_url", "") or "")
            raise RuntimeError(
                "stale_result_list — 갖고 있는 순위는 지금 화면이 아니라 **앞서 세운 목록**의 것이다"
                f"({origin[:120]}). 지금은 주소로 직접 연 다른 곳({standing[:120]})에 있다. "
                "지금 화면의 항목을 열려면 browser_snapshot 으로 보고 그 ref 를 browser_click 으로 눌러라. "
                "앞 목록의 N번째를 열려던 것이면 그 목록으로 돌아간 뒤(browser_back 또는 browser_open) 다시 불러라."
            )
        if not self._last_results:
            # ★ **지금 화면이 목록이면 거기서 순위를 만든다** (2026-08-13).
            #
            # 여태 순위는 `browser_search`·`browser_site_search` 를 **거쳐 왔을 때만**
            # 생겼다. 즉 "몇 번째를 열어라"가 화면의 성질이 아니라 **어떻게 도착했는지**에
            # 묶여 있었다. 사람은 그렇게 안 본다 — 목록이 보이면 세 번째를 누른다.
            #
            # 실측(위시켓, 15걸음 판): 자비스가 사람처럼 갔다. 홈 → '프로젝트 찾기'
            # 클릭 → 검색칸에 입력 → Enter. 화면에는 프로젝트 목록이 멀쩡히 떠 있는데
            # `browser_open_result(1)` 이 **`no_search_results`** 로 거절했다. 3·13·15번
            # 걸음에서 세 번 거절당했고, 그때마다 ref 로 손클릭해서 하나 열고
            # `browser_back` 이 30초 타임아웃 나면서 목록을 통째로 잃었다.
            #
            # 도구가 사람처럼 다닌 것을 벌준 셈이다. 화면을 보면 되는 일이다.
            recovered = self._recover_results_for_open(page, limit=15)
            if recovered:
                self._last_results = recovered
                self._remember_results_origin(page)
        if not self._last_results:
            raise RuntimeError(
                "no_result_list — 지금 화면에서 결과 목록을 못 찾았다. "
                "목록 화면으로 간 뒤에 다시 부르거나, browser_snapshot 으로 보고 "
                "browser_click 으로 직접 눌러라."
            )
        wanted_title = str(arguments.get("title") or "")
        if wanted_title.strip():
            match = self._pick_result(rank, wanted_title)
            rank = int(match["rank"])
        else:
            match = next((item for item in self._last_results if int(item["rank"]) == rank), None)
        if match is None:
            available = ", ".join(str(item["rank"]) for item in self._last_results)
            # ★ **순위(rank)와 번호표(ref)는 다른 것이다** (2026-08-14).
            #
            # 실측: 스냅샷에서 `j90` 을 눌러 놓고 다음 걸음에 `open_result rank=90`
            # 을 불렀다. 목록은 15개뿐이라 거절당했는데, 그때 준 말이 "있는 순위:
            # 1~15" 뿐이라 **왜 틀렸는지**는 안 알려 줬다. 그래서 같은 착각을 또 한다.
            #
            # 순위 밖의 큰 수는 거의 언제나 번호표를 옮겨 적은 것이다 — 그걸 짚어 준다.
            hint = ""
            if rank > len(self._last_results):
                hint = (
                    " ★ 혹시 스냅샷의 번호표(j90 같은 것)를 순위로 쓴 것 아닌가?"
                    " 그 둘은 다르다 — 번호표는 browser_click 에, 순위는 여기에 쓴다."
                    " 목록의 N 번째를 열려면 그 목록에 있는 순위를 줘라."
                )
            raise ValueError(f"result_rank_not_found:{rank} — 있는 순위: {available}.{hint}")

        raw_url = str(match.get("url") or "")
        if raw_url.lower().startswith("javascript:"):
            routed = self._js_route_url(raw_url)
            if not routed:
                return self._open_js_result(page, match, rank)
            raw_url = routed
        # 여러 항목을 쌓아 보여 주는 주소면 그 항목 하나만 보는 주소로 연다(`single_item_view` 주석).
        url = single_item_view(self._validate_url(raw_url))
        # 검색 결과를 타고 들어가도 문전박대는 똑같이 걸린다(실측: 네이버 검색 →
        # 쿠팡 결과 클릭도 같은 화면이었다). 그러니 판정은 두 경로에 같이 건다.
        #
        # ★ 날짜도 여기서 갈아 끼운다. 목록이 준 상세 주소는 **목록을 그린 날**의
        #   날짜를 달고 있어서(야놀자 `checkInDate`), 그대로 열면 엉뚱한 밤을 읽는다.
        rewrite = self._goto_with_dates(page, url)
        ready = self._wait_until_operable(page)
        self._mark_visited(url)
        match["visited"] = True
        self._remember_where_it_landed(page, match, raw_url)
        self._reads_since_search += 1
        self._searches_without_read = 0
        remaining = [item["rank"] for item in self._last_results if not item.get("visited")]
        return self._evidence(
            "opened_result",
            rank=rank,
            result_title=match.get("title", ""),
            element_count=ready["count"],
            ready_polls=ready["polls"],
            # 몇 개째를 읽고 있는지, 몇 개가 남았는지. 이게 없으면 하나 읽고 "이 글엔
            # 없네" 하고 검색으로 돌아간다 — 실측에서 두 번 다 그랬다.
            read_so_far=self._reads_since_search,
            remaining=remaining,
            **{k: v for k, v in self._date_rewrite_evidence(rewrite).items() if k != "date_instruction"},
            # ★ 로 시작해야 에이전트가 이 지시를 **따로 올린다**. 그래서 사이트 검색
            # 안내가 있으면 그것을 앞에 세운다 — 뒤에 붙이면 긴 결과 JSON 안에 묻히고,
            # 묻힌 지시는 없는 지시다(실측으로 두 번 확인한 자리다).
            instruction=(
                (note + " " if (note := self._date_rewrite_evidence(rewrite).get("date_instruction", "")) else "")
                + (offer + " " if (offer := self._site_search_offer(page).strip()) else "")
                + f"이번이 {self._reads_since_search}번째로 읽는 자료다. 본문은 browser_extract 로 읽어라. "
                + (
                    f"이 글에 답이 없으면 **검색하지 말고** browser_open_result 로 다음을 열어라 "
                    f"(안 읽은 rank {remaining[:5]})."
                    if remaining
                    else "안 읽은 결과가 더 없다. 여기서도 못 찾으면 그때 다른 낱말로 검색해라."
                )
            ),
        )

    def _pick_result(self, rank: int, title: str) -> dict[str, Any]:
        """열 결과를 고른다 — `title` 을 주면 지금 목록에서 그 제목이 들어간 결과, 아니면 `rank` 번째.

        ★ 2026-10-15 02:41 레딧 판(3dc56fb1): 결과에서 「Why run LLMs locally?」를 찾아 놓고 rank=1 을 불렀는데 1번은 다른 글이었다.
          순위는 모델이 세는 값이라 틀린다 — 모델이 본 그대로의 제목을 주면 그것이 이긴다. 그 제목이 목록에 없으면 추측해서 열지 않고
          있는 제목을 알려 준다.
        """
        wanted = " ".join(str(title or "").split()).casefold()
        if not wanted:
            match = next((item for item in self._last_results if int(item["rank"]) == int(rank or 0)), None)
            if match is None:
                available = ", ".join(str(item["rank"]) for item in self._last_results)
                raise ValueError(f"result_rank_not_found:{rank} — 있는 순위: {available}.")
            return match
        for item in self._last_results:
            if wanted in " ".join(str(item.get("title") or "").split()).casefold():
                return item
        titles = " / ".join(f"{item['rank']}. {str(item.get('title') or '')[:60]}" for item in self._last_results[:15])
        raise ValueError(
            f"result_title_not_found — 「{title.strip()[:80]}」가 들어간 제목이 지금 목록에 없다. 있는 제목: {titles}. "
            "목록이 더 있으면 browser_load_more 로 불러온 뒤 다시 불러라. 제목을 지어내지 마라."
        )

    def _js_route_url(self, link: str) -> str:
        """`javascript:go_view(176076)` → 「통한 길」 기억(js_link_route)에 그 함수의 실제 주소 모양이 있으면 그 주소. 없으면 빈 값."""
        found = _js_nav_link(link)
        host = getattr(self, "_results_origin_host", "") or ""
        if not found or not host:
            return ""
        name, args = found
        for trait in self._site_traits.traits_for(f"https://{host}/"):
            if trait["trait"] != "js_link_route":
                continue
            for detail in trait["details"]:
                func, _, pattern = str(detail).partition("→")
                if func != name or not pattern.startswith("/"):
                    continue
                path = pattern
                for index, value in enumerate(args, 1):
                    path = path.replace(f"{{{index}}}", str(value))
                if "{" not in path:
                    return f"https://{host}{path}"
        return ""

    def _open_js_result(self, page: Any, match: dict[str, Any], rank: int) -> dict[str, Any]:
        """순위의 주소가 `javascript:` 링크다 — 목록 페이지의 함수로 따라간다(지금 화면에 함수가 없으면 목록으로 돌아가서)."""
        link = str(match.get("url") or "")
        found = _js_nav_link(link)
        origin = getattr(self, "_results_origin_url", "") or ""
        if found and origin:
            try:
                present = bool(page.evaluate("(n) => typeof window[n] === 'function'", found[0]))
            except Exception:
                present = False
            if not present:
                self._goto_checked(page, origin)
                self._wait_until_operable(page)
        result = self._follow_js_link(page, link)
        match["visited"] = True
        self._reads_since_search += 1
        self._searches_without_read = 0
        remaining = [item["rank"] for item in self._last_results if not item.get("visited")]
        result.update(rank=rank, result_title=match.get("title", ""), read_so_far=self._reads_since_search, remaining=remaining)
        result["instruction"] = (
            str(result.get("instruction") or "")
            + f" 이번이 {self._reads_since_search}번째로 읽는 자료다. 본문은 browser_extract 로 읽어라. "
            + (f"다음은 browser_open_result 로 (안 읽은 rank {remaining[:5]})." if remaining else "")
        ).strip()
        return result

    # 상세를 읽기 전에 훑어 내릴 때 쓰는 값들.
    #
    # 왕복을 늘리지 않으려고 **브라우저 안에서 한 번에** 돈다(스크롤 → 잠깐 대기 →
    # 다시 스크롤). 파이썬에서 한 칸씩 부르면 그만큼 왕복이 붙는다 — 스냅샷을
    # 0.5초로 줄인 것과 같은 이유다.
    _LAZY_SWEEP_JS = """
    async (args) => {
      const { steps, pause, minRatio } = args;
      const view = window.innerHeight || 800;
      const height = () => document.body ? document.body.scrollHeight : 0;
      const before = height();
      // 볼 것이 화면 하나뿐이면 훑을 이유가 없다.
      if (before < view * minRatio) return {swept: false, before, after: before};
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      for (let i = 1; i <= steps; i++) {
        window.scrollTo(0, Math.floor((height() / steps) * i));
        await sleep(pause);
      }
      const after = height();
      window.scrollTo(0, 0);          // 읽고 나면 제자리로 — 다음 스냅샷의 기준이 된다
      await sleep(120);
      return {swept: true, before, after};
    }
    """

    def _sweep_for_lazy_content(self, page: Any) -> dict[str, Any]:
        """상세를 읽기 전에 **끝까지 훑어 내렸다 돌아온다.** 실패해도 삼킨다.

        여기서 넘어지면 읽기 자체가 실패한다 — 훑기는 읽기를 **거들려고** 있는 것이지
        읽기의 조건이 아니다. 못 훑었으면 안 훑은 채로 읽으면 된다(예전 동작).
        """
        try:
            return page.evaluate(
                self._LAZY_SWEEP_JS,
                {
                    "steps": _LAZY_SWEEP_STEPS,
                    "pause": _LAZY_SWEEP_PAUSE_MS,
                    "minRatio": _LAZY_SWEEP_MIN_RATIO,
                },
            ) or {}
        except Exception:
            return {}

    def _extract(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """본문만 골라 읽는다 — 메뉴·사이드바·댓글·추천글을 뺀 글 자체.

        `browser_read` 는 보이는 글을 전부 준다. 블로그 한 편을 읽으려는데 상단
        메뉴와 이웃 목록과 인기글 20개가 같이 딸려오면, 젬마의 24K 컨텍스트에서
        정작 본문이 밀려난다. 파고드는 일은 글을 여러 편 읽는 일이라 이 낭비가
        그대로 쌓인다.

        고르는 방법은 글자 밀도다. `<article>`·`<main>` 이 있으면 그걸 쓰고, 없으면
        블록마다 (글자 수 − 링크 안 글자 수)를 재서 제일 높은 것을 고른다 — 메뉴와
        추천글은 글자가 거의 다 링크 안에 있어서 이 점수가 낮게 나온다.
        """
        # ★ 기본 8,000 → **20,000** (2026-08-13).
        #
        # 실측: 성공한 추출 128건 중 29건(23%)이 8,000 에 딱 걸려 잘렸다. 상세 한 장을
        # 반만 읽는 것이 그만큼 잦았다는 뜻이다.
        #
        # 컨텍스트는 이 모델에서 거의 공짜다(num_ctx 24K→128K 가 0.38GB). 그리고
        # 브라우저가 컨텍스트를 제일 많이 먹는 자리인데, **거기가 제일 값이 나가는
        # 자리**이기도 하다 — 본문을 반만 보고 답하면 나머지 전부가 헛돈다.
        #
        # ⚠ 여기만 올리면 아무것도 안 바뀐다. `agent._bounded_transcript` 가 도구
        # 결과 하나를 따로 자른다(`_TOOL_RESULT_MAX_CHARS`). 두 값은 같이 움직여야
        # 한다 — 오늘만 세 번째로 만나는 "상한이 여러 군데" 자리다.
        max_chars = max(500, min(int(arguments.get("max_chars") or 20000), 30000))
        # ★ 읽기 전에 **페이지를 훑고 온다** (2026-08-13).
        #
        # 사용자가 브라우저를 보다 짚으신 자리다 — "상세페이지 들어가는 것에만 보상이
        # 있고 스크롤에는 관심이 없다. 상세페이지는 무조건 스크롤이 없을 수가 없다."
        #
        # 실측(그날 잡 260건):
        #     상세를 연 횟수 165 · **그 페이지에서 스크롤한 것 1 (0.6%)**
        #     browser_extract 의 23% 가 8,000자 상한에 걸려 잘림
        #
        # 계획 층이 세는 것은 "몇 개를 **열었나**"뿐이라, 열기만 하면 요구가 채워진다.
        # 다 읽었는지는 아무도 안 본다. 그래서 첫 화면만 보고 나오는 것이 이득이었다.
        #
        # 지연 로딩 화면(쿠팡 상세정보·다나와 스펙표)은 **내려가야 DOM 에 생긴다.**
        # 안 내리고 읽으면 "그 페이지에 그런 정보가 없다"가 되는데, 사실은 안 그려진
        # 것이다. 사람은 상세를 열면 훑어 내린다. 도구가 그걸 한다.
        self._sweep_for_lazy_content(page)
        best: dict[str, Any] | None = None
        outer: dict[str, Any] | None = None
        inner: dict[str, Any] | None = None
        big_images = 0
        tall_images = 0
        big_sources: list[str] = []
        tall_sources: list[str] = []
        seen_groups: set[str] = set()
        page_host = _bare_host(urlparse(str(getattr(page, "url", "") or "")).netloc)
        for index, frame in enumerate(self._frames_of(page)):
            label = self._frame_label(frame, index)
            # ★ **같은 이름에 번호만 다른 틀은 첫째만 이 페이지의 것이다** (2026-10-04 채용 공고 조사 판 788ef850).
            #   사람인 「이어 보기」는 공고를 쌓아 보여 준다 — `iframe_content_0` 이 연 공고, `_1`·`_2` 는 **다음 공고들**이다.
            #   점수 높은 틀 하나를 고르다 보니 도담에어로스페이스·KAIST 연구실 공고를 열고 두레기계공업 공고(`_2`)를 읽었다(두 번, 글자 하나 안 틀리고 같음).
            group = re.sub(r"\d+$", "", label) if index and re.search(r"\d$", label) else ""
            if group:
                if group in seen_groups:
                    continue
                seen_groups.add(group)
            # 레시피가 적어 둔 읽을 자리는 **바깥 화면**에만 준다 — 안쪽 틀은 올린 사람이 짠 HTML 이라 그 자리가 없다.
            places = self._read_selectors_for(str(getattr(page, "url", "") or "")) if index == 0 else []
            try:
                found = frame.evaluate(_EXTRACT_MAIN_JS, places) if places else frame.evaluate(_EXTRACT_MAIN_JS)
            except Exception:
                continue
            if not found:
                continue
            big_images += int(found.get("big_images") or 0)
            tall_images += int(found.get("tall_images") or 0)
            big_sources.extend(str(src) for src in (found.get("big_image_srcs") or []) if src)
            tall_sources.extend(str(src) for src in (found.get("tall_image_srcs") or []) if src)
            if not found.get("text"):
                continue
            found["frame"] = label
            if best is None or int(found.get("score") or 0) > int(best.get("score") or 0):
                best = found
            if index == 0:
                outer = found
            elif _bare_host(urlparse(str(getattr(frame, "url", "") or "")).netloc) in {"", page_host} and (
                inner is None or int(found.get("score") or 0) > int(inner.get("score") or 0)
            ):
                inner = found
        # ★ **요약은 바깥, 본문은 안쪽 틀** — 둘 다 읽는다 (같은 판). 그 판이 연 공고 21개 가운데 제 공고의 상세 본문을 읽은 것은 2개였다.
        #   17개는 바깥의 요약(근무형태·급여·지역)만 받았고(바깥 점수가 이겼다), 2개는 본문 틀이 이겨 요약을 잃었다. 국내 채용·쇼핑 사이트가
        #   흔히 이렇게 짠다 — 사이트가 칸을 채우고, 올린 사람이 짠 HTML 은 틀 안에 넣는다. 같은 사이트의 틀만 합친다(광고 틀은 호스트가 다르다).
        merged_from = ""
        if outer is not None and inner is not None:
            outer_text = _clean_lines(outer.get("text"), 10_000_000)
            inner_text = _clean_lines(inner.get("text"), 10_000_000)
            if len(inner_text) >= 200 and inner_text not in outer_text:
                room = max(3000, max_chars - len(inner_text) - 120)
                head = outer_text if len(outer_text) <= room else outer_text[:room] + "\n…(바깥 글은 여기까지만 — 아래 본문 틀을 싣느라 줄였다)"
                merged_from = str(inner.get("frame") or "")
                best = {
                    **outer,
                    "text": head + f"\n\n[이 페이지 안쪽 틀 「{merged_from}」의 글 — 상세 본문]\n" + inner_text,
                    "frame": f"main + {merged_from}",
                }

        # ★ 섀도 DOM 페이지(2026-09-17 MS 스토어): 본문 고르기는 조각 하나(설명 칸)만 집고 게시자·별점 칸은 다른
        #   컴포넌트라 빠진다. 섀도 안 글자 전체가 고른 본문보다 훨씬 길면 그 전체를 준다 — 반만 보고 「없다」가 나가지 않게.
        deep = self._deep_text(page, max_chars)
        chosen = len(_clean_lines((best or {}).get("text"), 10_000_000))
        if deep and len(deep) > max(2 * chosen, chosen + 40):
            self._mark_visited(str(getattr(page, "url", "") or ""))
            text = self._visible_rollers(page, deep)[:max_chars]
            return self._evidence(
                "extracted",
                text=text,
                char_count=len(text),
                selector="(섀도 DOM 안 글자 전체)",
                fell_back=False,
                shadow_dom=True,
                **({"truncated": True} if len(deep) > max_chars else {}),
                note="이 페이지는 글이 웹 컴포넌트(섀도 DOM) 안에 있어 화면에 그려지는 순서대로 전체를 읽었다 — 메뉴 글자도 섞여 있다.",
            )

        if best is None:
            # 본문을 못 고르면 조용히 빈 값을 주지 않는다 — 그러면 "글이 없는 페이지"로
            # 읽혀 모델이 엉뚱한 결론을 낸다. 보이는 글 전체로 물러서고 그렇다고 말한다.
            fallback = self._read(page, {"max_chars": max_chars})
            image_body = self._image_body_note(str(fallback.get("text") or ""), big_images, tall_images)
            return self._evidence(
                "extracted",
                text=fallback.get("text", ""),
                char_count=int(fallback.get("char_count") or 0),
                **({"image_body": True, "big_images": big_images, "tall_images": tall_images, "image_body_note": image_body} if image_body else {}),
                selector="",
                fell_back=True,
                note="본문 영역을 특정하지 못해 보이는 글 전체를 돌려준다 — 메뉴·추천글이 섞여 있다.",
            )

        # 먼저 다듬고 **그다음에** 자른다. 반대로 하면 "얼마나 남았나"를 셀 수가 없다
        # (다듬기 전 길이는 공백·줄바꿈이 섞여 있어 실제 남은 글과 다르다).
        full = _clean_lines(best.get("text"), 10_000_000)
        text = full[:max_chars]
        # ★ **잘랐으면 잘랐다고 말한다** (2026-08-13).
        #
        # 실측: 성공한 추출 128건 중 **29건(23%)** 이 상한에 딱 걸렸다. 딱 걸렸다는
        # 것은 뒤가 남았다는 뜻인데, 결과에는 `char_count: 8000` 만 있어서 모델은
        # 그게 전부인 줄 안다. 그래서 아래에 있는 값(가격표·상세조건·스펙)을 두고
        # "그 페이지에는 없습니다"가 나간다.
        #
        # 자사 데이터 조회에서 배운 것과 같은 규칙이다 — 조용히 자르지 않는다.
        cut = len(full) - len(text)
        self._mark_visited(str(getattr(page, "url", "") or ""))
        remaining = [item["rank"] for item in self._last_results if not item.get("visited")]
        image_body = self._image_body_note(full, big_images, tall_images)
        image_read: dict[str, Any] = {}
        if image_body:
            # ★ 그림 본문을 **읽는다** (2026-10-05). 어제까지는 「그림이라 확인 못 함」이라고 말하는 데까지였다.
            image_text, image_count, tile_count = self._read_body_images(page, tall_sources or big_sources)
            if image_text:
                addition = (
                    f"\n\n[그림에서 읽은 글 — 이 페이지의 그림 {image_count}장을 모델이 보고 옮겨 적었다. 글자 하나가 틀릴 수 있다]\n"
                    + image_text
                )
                room = max(2000, max_chars - len(addition))
                text = text[:room] + addition
                image_body = (
                    f"★ 이 페이지의 상세 내용은 그림 안에 있어, 그림 {image_count}장을 읽어 글 끝에 붙였다(「그림에서 읽은 글」). "
                    "그 값은 답에 써도 되지만 **「그림에서 읽음」이라고 밝혀라** — 그림 글자는 한두 자가 틀릴 수 있다. "
                    "그림에서 읽은 글에도 없는 값은 「확인 못 함」이다."
                )
                image_read = {"image_text_chars": len(image_text), "image_tiles": tile_count, "images_read": image_count}
        return self._evidence(
            "extracted",
            text=text,
            char_count=len(text),
            **image_read,
            **({"image_body": True, "big_images": big_images, "tall_images": tall_images, "image_body_note": image_body} if image_body else {}),
            **({"merged_frame": merged_from} if merged_from else {}),
            **(
                {
                    "truncated": True,
                    "truncated_note": (
                        f"본문이 더 있다(최소 {cut:,}자 더). 찾는 값이 안 보이면 "
                        "browser_extract 를 max_chars=20000 으로 다시 불러라 — "
                        "그 페이지에 없는 것이 아니라 아직 안 받은 것이다."
                    ),
                }
                if cut > 0
                else {}
            ),
            selector=_clean(best.get("selector"), 120),
            frame=best.get("frame", ""),
            link_ratio=best.get("link_ratio", 0),
            fell_back=False,
            read_so_far=self._reads_since_search,
            remaining=remaining,
            # 읽고 난 직후가 다음 수를 정하는 자리다. 여기서 아무 말도 안 하면
            # "이 글엔 답이 없다"는 판단이 곧장 새 검색으로 이어진다.
            # ★ 로 시작하는 안내는 에이전트가 결과 밖으로 따로 세운다 — 그림 본문 알림은 그래야 눈에 띈다.
            instruction=(image_body + " " if image_body else "") + (
                f"{self._reads_since_search}개째 읽었다. 여기에 답이 있으면 그것을 쓰고, "
                f"없으면 browser_open_result 로 다음을 열어라 — 안 읽은 rank {remaining[:5]}. "
                "새로 검색하지 마라."
                if remaining
                else f"{self._reads_since_search}개째 읽었다. 목록에 안 읽은 것이 더 없다."
            ),
        )

    #: 글자가 이만큼도 안 되는데 큰 그림이 있으면 내용이 그림 안에 있다고 본다.
    _IMAGE_BODY_MAX_CHARS = 400

    #: 그림 본문 읽기의 상한 — 그림 수 · 조각 수 · 전체 시간(초). 넘으면 거기까지 읽은 것만 붙인다.
    _IMAGE_READ_MAX_IMAGES = 2
    _IMAGE_READ_MAX_TILES = 8
    _IMAGE_READ_SECONDS = 60.0
    #: 한 번에 모델에게 보여 주는 조각의 높이와 겹침(px), 그림의 최대 가로(px).
    _IMAGE_TILE_HEIGHT = 1600
    _IMAGE_TILE_OVERLAP = 80
    _IMAGE_MAX_WIDTH = 1100

    def _image_bytes(self, page: Any, source: str) -> bytes:
        """페이지가 이미 보여 주고 있는 그림의 원본. 못 받으면 빈 바이트."""
        if source.startswith("data:"):
            try:
                import base64

                return base64.b64decode(source.split(",", 1)[1])
            except Exception:
                return b""
        if not source.startswith(("http://", "https://")):
            return b""
        try:
            response = page.context.request.get(source, timeout=15000)
            return response.body() if response.ok else b""
        except Exception:
            return b""

    def _read_body_images(self, page: Any, sources: list[str]) -> tuple[str, int, int]:
        """그림으로 된 본문을 조각으로 잘라 모델에게 읽힌다 → (읽은 글, 읽은 그림 수, 조각 수). 못 읽으면 빈 글.

        ★ 넣기 전에 쟀다 (2026-10-05, 운영 모델 Ornith 35B · 정답을 아는 공고 그림을 만들어 3판): 값 18개 중 글자 그대로 맞은 것
          17 · 17 · 18, 조각 하나에 3~4초. 숫자·날짜·금액·전화번호는 전부 맞았고, 틀린 하나는 주소 「신일서로」를 「신일로」로
          줄인 것. 깨끗하게 만든 그림이라 실제 공고 그림은 이보다 낮을 수 있다 — 그래서 읽은 글에 「틀릴 수 있다」를 붙인다.
        읽는 손(`image_text_reader`)은 런타임이 건다. 없거나(그림을 못 읽는 모델) 실패하면 예전처럼 「확인 못 함」으로 남는다.
        """
        reader = getattr(self, "image_text_reader", None)
        if reader is None or not sources or self._cannot_read_pictures():
            return "", 0, 0
        try:
            import io as _io

            from PIL import Image
        except Exception:
            return "", 0, 0
        deadline = time.monotonic() + self._IMAGE_READ_SECONDS
        lines: list[str] = []
        images = tiles = 0
        seen_sources: set[str] = set()
        # 화면에 「지금 이 조각을 읽는 중」을 비추는 길 (2026-10-10). 조각 하나에 3~4초씩 여덟 번이면 30초 가까이 걸리는데
        # 그동안 화면에는 「본문 읽기」 한 줄만 떠 있어 멈춘 것처럼 보였다. 통로는 런타임이 건다 — 없으면 아무 일도 없다.
        sink = getattr(self, "image_read_sink", None)
        stride = self._IMAGE_TILE_HEIGHT - self._IMAGE_TILE_OVERLAP
        planned_images = min(len(dict.fromkeys(sources)), self._IMAGE_READ_MAX_IMAGES)
        opened = 0
        told = False
        for source in sources:
            if images >= self._IMAGE_READ_MAX_IMAGES or source in seen_sources:
                continue
            seen_sources.add(source)
            raw = self._image_bytes(page, source)
            if not raw:
                continue
            try:
                picture = Image.open(_io.BytesIO(raw)).convert("RGB")
            except Exception:
                continue
            width, height = picture.size
            if width > self._IMAGE_MAX_WIDTH:
                height = int(height * self._IMAGE_MAX_WIDTH / width)
                width = self._IMAGE_MAX_WIDTH
                picture = picture.resize((width, height))
            read_any = False
            top = 0
            opened += 1
            # 이 그림에서 읽을 조각 수 — 아래 고리와 같은 셈(겹침만큼 덜 내려간다) · 남은 조각 한도를 넘지 않는다.
            in_this = min(-(-height // stride), self._IMAGE_READ_MAX_TILES - tiles)
            nth = 0
            while top < height and tiles < self._IMAGE_READ_MAX_TILES and time.monotonic() < deadline:
                tile = picture.crop((0, top, width, min(height, top + self._IMAGE_TILE_HEIGHT)))
                buffer = _io.BytesIO()
                tile.save(buffer, format="PNG")
                tiles += 1
                top += self._IMAGE_TILE_HEIGHT - self._IMAGE_TILE_OVERLAP
                nth += 1
                if sink is not None:
                    told = self._tell_image_read(
                        sink, tile, image=opened, images=max(planned_images, opened), tile=nth, tiles=max(in_this, nth),
                    ) or told
                try:
                    said = str(reader(buffer.getvalue()) or "")
                except Exception:
                    said = ""
                for line in said.splitlines():
                    line = line.strip()
                    # 겹친 자리의 같은 줄 · 「빈 이미지」 같은 모델의 군말은 싣지 않는다.
                    if not line or line in lines[-6:] or (line.startswith("(") and line.endswith(")")):
                        continue
                    lines.append(line)
                    read_any = True
            if read_any:
                images += 1
                if top < height:
                    lines.append("…(그림이 길어 여기까지만 읽었다)")
        if told:
            # 다 읽었다 — 화면의 그림을 거둔다. 다음 걸음 알림이 늦게 와도 「읽는 중」이 남아 있지 않게.
            try:
                sink({"done": True})
            except Exception:  # noqa: BLE001 — 알림이 실패해도 읽은 글은 그대로 돌려준다
                pass
        return "\n".join(lines), images, tiles

    def _cannot_read_pictures(self) -> bool:
        """읽는 모델이 그림을 **못 읽는다고 확인됐는가**. 물어볼 길이 없거나 답을 모르면 False — 예전처럼 불러 본다.

        물어보는 손(`pictures_readable`)은 런타임이 건다(`OllamaClient.reads_pictures`). 그림 부속이 없는 모델에게 그림을 주면
        서버가 조각마다 거절한다 — 그림을 받아 자르고 화면에 「읽는 중」을 비추고 거절을 받는 일을 처음부터 하지 않는다.
        """
        ask = getattr(self, "pictures_readable", None)
        if ask is None:
            return False
        try:
            return ask() is False
        except Exception:  # noqa: BLE001 — 묻다가 틀어지면 모르는 것이다
            return False

    _IMAGE_LOOK_WIDTH = 240          # 화면에 비추는 조각 그림의 폭 — 무엇을 읽는지 알아볼 만큼만(수 KB)
    _IMAGE_LOOK_QUALITY = 60

    def _tell_image_read(self, sink: Any, piece: Any, *, image: int, images: int, tile: int, tiles: int) -> bool:
        """읽기 직전의 조각을 작은 그림으로 줄여 통로에 넘긴다 → 넘겼는가. 실패해도 읽기는 계속된다(그래서 전부 삼킨다)."""
        try:
            import base64 as _base64
            import io as _io

            small = piece.copy()
            small.thumbnail((self._IMAGE_LOOK_WIDTH, self._IMAGE_LOOK_WIDTH * 2))
            buffer = _io.BytesIO()
            small.save(buffer, format="JPEG", quality=self._IMAGE_LOOK_QUALITY)
            sink({
                "image": int(image), "images": int(images),
                "tile": int(tile), "tiles": int(tiles),
                "width": int(small.size[0]), "height": int(small.size[1]),
                "picture": "data:image/jpeg;base64," + _base64.b64encode(buffer.getvalue()).decode("ascii"),
            })
            return True
        except Exception:  # noqa: BLE001
            return False

    def _image_body_note(self, full: str, big_images: int, tall_images: int) -> str:
        """상세 내용이 **그림 안에** 있는 페이지인가 — 그렇다면 모델에게 그렇게 말해 줄 글. 아니면 빈 글.

        ★ 2026-10-04 사람인 공고 21개 실측: 통이미지 공고가 1~2개(상세 본문 글자 0자·그림 1장 / 255자·9장). 글자가 없으면 모델은
          「이 공고엔 조건이 안 적혀 있다」고 읽거나 바깥 요약만으로 나머지를 채운다. 안 적힌 것이 아니라 **못 읽은 것**이다 —
          빈 값 하나가 두 사실을 뜻하면 조용히 고장 난다(08-05 `_why_empty` 와 같은 규칙).
        두 꼴을 본다: 글자가 거의 없고 큰 그림이 있다 · 세로로 긴 그림이 있다(요약 글이 길어도 상세는 그림일 수 있다).
        사진 몇 장 있는 글에는 걸지 않는다 — 긴 그림은 가로 500·세로 1000 이상만 센다.

        ★ 2026-10-12: 지금 모델이 그림을 못 읽으면(그림 부속 없는 모델 · 그림 읽기를 끈 설정) 까닭을 그렇게 말한다.
          「찍어 보라」는 권하지 않는다 — 찍어도 못 본다. 사용자에게는 「그림 읽기를 켜면 읽을 수 있다」가 쓸모 있는 말이다.
        """
        if self._cannot_read_pictures() and ((big_images > 0 and len(full) <= self._IMAGE_BODY_MAX_CHARS) or tall_images > 0):
            count = big_images if (big_images > 0 and len(full) <= self._IMAGE_BODY_MAX_CHARS) else tall_images
            return (
                f"★ 이 페이지에는 내용이 든 그림이 {count}장 있는데, **지금 모델은 그림을 읽지 못한다.** "
                "그림 속 값은 **확인하지 못한 것**이다: 읽은 것처럼 적지 말고, 찾는 값이 위 글에 없으면 그 칸은 "
                "「그림이라 확인 못 함」이라고 적어라. 그런 칸이 있으면 답 끝에 「그림을 읽는 설정으로 바꾸면 그림 속 내용도 읽을 수 있습니다」라고 한 줄 알려라."
            )
        if big_images > 0 and len(full) <= self._IMAGE_BODY_MAX_CHARS:
            return (
                f"★ 이 페이지는 글자가 거의 없고 큰 그림이 {big_images}장이다 — 내용이 **그림 안에** 있고 글자로는 읽히지 않았다. "
                "그림 속 조건은 **확인하지 못한 것**이다: 읽은 것처럼 적지 말고 그 칸은 「본문이 이미지라 확인 못 함」이라고 적어라. "
                "꼭 필요하면 browser_screenshot 으로 그 자리를 찍어 보라."
            )
        if tall_images > 0:
            return (
                f"★ 이 페이지에는 세로로 긴 그림이 {tall_images}장 있다 — 상세 내용이 그 그림 안에 있을 수 있고, 그 글은 읽히지 않았다. "
                "찾는 값이 위 글에 없으면 「없다」가 아니라 **「그림이라 확인 못 함」**이다. 꼭 필요하면 browser_screenshot 으로 찍어 보라."
            )
        return ""

    def _why_empty(self, page: Any, *, scanned: int | None = None, listed_nothing: bool = False) -> dict[str, Any]:
        """빈손으로 끝났을 때 **왜** 비었는지. 셋을 가른다.

        빈 결과는 세 가지 전혀 다른 사정을 하나로 뭉갠다:

            정말 없음        이 페이지엔 그런 게 없다        -> 다른 데를 봐야 한다
            아직 안 그려짐   스크립트가 그리는 중이다        -> 기다렸다 다시 보면 된다
            차단·오류 화면   봇 검사나 오류가 떠 있다        -> 사람이 손대야 한다

        셋이 구별 안 되면 모델은 늘 첫째로 읽는다 — "여긴 없네" 하고 엉뚱한 데로
        간다. 빙 0건 사고(2026-08-08)가 정확히 그 모양이었고, `_snapshot` 은 자기
        docstring 에 "요소 0개는 망가진 페이지로 읽힌다"고 적어 놓고도 정작 0을
        돌려줄 때 아무 말을 안 하고 있었다(2026-08-05, 8개 사이트).

        `scanned` 를 주면 그것으로 "그려졌는가"를 판단한다 — 이미 훑어 놓고 또
        세는 것은 낭비다.
        """
        # `_search_blocked` 는 이름만 검색이지 하는 일은 "이 화면이 봇 검사·차단인가"라
        # 사이트를 안 가린다. 여기서 그대로 쓴다.
        blocked = self._search_blocked(page)
        drawn = scanned if scanned is not None else self._operable_count(page)
        # ★ 2026-09-17 MS 스토어: 요소는 147개 그려져 있는데 목록은 0개였고, 여기서 「조건에 맞는 것이 정말 없다」가 나갔다.
        #   목록을 만드는 쪽이 못 본 것이지 없는 것이 아니다. 닫힌 섀도 DOM·캔버스 앱이면 요소 수조차 0 이라 「아직 안
        #   그려졌다」로 읽혀 기다리기만 반복한다 — 구조를 재서 가른다.
        structure: dict[str, Any] = {}
        if listed_nothing and not blocked:
            try:
                structure = dict(page.evaluate(_STRUCTURE_PROBE_JS) or {})
            except Exception:
                structure = {}
            opaque = int(structure.get("opaque_custom") or 0) >= 5 or float(structure.get("canvas_share") or 0) >= 0.3
            # 좌표를 모델이 눈대중으로 정하게 두지 않는다 — 접근성 트리(닫힌 섀도 DOM 도 뚫는다)에서 뽑아 준다.
            # 목록은 0 인데 접근성 트리에 누를 것이 있으면 그 자체가 「못 읽는 구조」의 증거다(닫힌 위젯 하나짜리 화면).
            targets = self._ax_targets(page, limit=30)
            if drawn or opaque or targets:
                self._note_trait(page, "needs_coordinates")
                return {
                    "empty_reason": "unreadable_structure",
                    "page_elements": drawn,
                    "structure": structure,
                    "targets": targets,
                    "instruction": "★ 없는 게 아니라 **목록이 못 읽는 구조**다(닫힌 웹 컴포넌트·캔버스). 같은 것을 다른 낱말로 "
                    "다시 찾지 마라 — 결과가 같다. browser_screenshot 으로 화면을 보고 browser_click_at(x, y) · "
                    "browser_type_at(x, y, text) 로 좌표를 눌러라.",
                }
        if blocked:
            self._note_trait(page, "bot_wall")
            return {
                "empty_reason": "blocked",
                "page_elements": drawn,
                "instruction": "★ 화면이 봇 검사·차단이다. 여긴 아무것도 없는 게 아니라 "
                "**막힌 것**이다. 같은 걸 다시 시도하지 말고 사람에게 알리거나 다른 경로로 가라 — "
                "browser_site_sources 로 이 사이트가 공개한 피드·사이트맵·공식 페이지를 찾을 수 있다(우회하지 마라).",
            }
        if not drawn:
            return {
                "empty_reason": "not_drawn",
                "page_elements": 0,
                "instruction": "★ 화면이 아직 안 그려졌다 — 없는 게 아니다. browser_wait 로 "
                "잠깐 기다렸다가 다시 불러라. 여기서 '없다'고 결론내지 마라.",
            }
        return {
            "empty_reason": "absent",
            "page_elements": drawn,
            "instruction": f"화면은 그려져 있고(요소 {drawn}개) 조건에 맞는 것이 정말 없다. "
            "조건을 넓히거나 다른 페이지로 가라.",
        }

    def _links(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """이 페이지에서 더 갈 수 있는 곳 — 다음 한 걸음의 후보.

        `same_site` 로 안쪽(연재 다음 편·태그 목록)과 바깥쪽(출처·인용)을 가른다.
        `contains` 는 앵커 글자에 걸리는 것만 남긴다.

        이미 가 본 곳에 `visited` 를 달아 준다. 이게 없으면 링크가 서로를 가리키는
        블로그에서 두 글 사이를 무한히 오간다.
        """
        limit = max(1, min(int(arguments.get("limit") or 30), 100))
        contains = _clean(arguments.get("contains"), 100).lower()
        scope = str(arguments.get("same_site") or "any").lower()
        try:
            here = _host_of_url(str(page.url or ""))
        except Exception:
            here = ""

        seen: dict[str, dict[str, Any]] = {}
        for index, frame in enumerate(self._frames_of(page)):
            try:
                rows = frame.evaluate(_COLLECT_LINKS_JS)
            except Exception:
                continue
            for row in rows or []:
                url = unwrap_redirect(str(row.get("href") or ""))
                if not url.startswith(("http://", "https://")):
                    continue
                text = _clean(row.get("text"), 160)
                if contains and contains not in text.lower() and contains not in url.lower():
                    continue
                host = _host_of_url(url)
                inside = bool(here) and (host == here or host.endswith("." + here) or here.endswith("." + host))
                if scope == "inside" and not inside:
                    continue
                if scope == "outside" and inside:
                    continue
                key = canonical_url(url)
                if not key or key in seen:
                    continue
                seen[key] = {
                    "url": url,
                    "domain": host,
                    "text": text or url,
                    "inside": inside,
                    **({"visited": True} if key in self._visited else {}),
                    **({"frame": self._frame_label(frame, index)} if index else {}),
                }
                if len(seen) >= limit:
                    break
            if len(seen) >= limit:
                break

        links = list(seen.values())
        if not links:
            # 링크 0개는 "갈 데가 없다"와 "아직 안 그려졌다"와 "차단"을 뭉갠다.
            return self._evidence("links", links=[], link_count=0, same_site=scope,
                                  **self._why_empty(page))
        return self._evidence(
            "links",
            links=links,
            link_count=len(links),
            same_site=scope,
            instruction=(
                "여기서 고른 주소는 browser_open 으로 연다. 다시 검색 결과로 돌아가려면 "
                "browser_open_result 에 다른 rank 를 주면 된다."
            ),
        )

    def _find(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """스냅샷에서 글자로 찾는다 — 200개를 다 읽지 않고.

        전체 스냅샷은 요소 100~200개짜리 덤프라, 버튼 하나를 찾으려고 그걸 통째로
        컨텍스트에 넣으면 정작 읽어야 할 본문이 밀려난다. 여기서는 걸린 것만 준다.
        """
        query = _clean(arguments.get("query"), 200)
        if not query:
            raise ValueError("query_required")
        limit = max(1, min(int(arguments.get("limit") or 12), 50))
        use_regex = bool(arguments.get("regex"))
        try:
            pattern = re.compile(query, re.IGNORECASE) if use_regex else None
        except re.error as exc:
            raise ValueError(f"bad_regex:{exc}") from exc

        needle = query.lower()
        matches: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        for index, frame in enumerate(self._frames_of(page)):
            rows.extend(
                self._frame_elements(
                    frame,
                    frame_label=self._frame_label(frame, index),
                    frame_index=index,
                    # ★ 찾기는 **화면 전체**를 본다 (2026-10-07). 200 은 스냅샷이 모델에게 줄 양의 상한이지 찾을 범위가
                    #   아니다 — 요소 1,266개인 이력서 수정 화면에서 「자기소개서」가 200번째 밖이라 「없다」고 답했다.
                    #   걸린 것만 돌려주므로 넓게 봐도 모델이 받는 양은 그대로다(전수 7,157개 30ms — 사고 Q 실측).
                    budget=_MAX_SCAN,
                    start=len(rows),
                    include_box=bool(arguments.get("include_box")),
                )
            )
        # 찾기도 번호표를 전부 다시 붙였다 — 기억을 같이 새로 쓴다(죽은 ref 를 이름으로 되살리는 근거).
        self._remember_refs(rows)
        for row in rows:
            haystack = (f"{row.get('name', '')} {row.get('row', '')} {row.get('group', '')} "
                        f"{row.get('placeholder', '')} {row.get('href', '')}")
            hit = pattern.search(haystack) if pattern else (needle in haystack.lower())
            if not hit:
                continue
            matches.append(row)
            if len(matches) >= limit:
                break

        if matches:
            return self._evidence(
                "found",
                query=query,
                regex=use_regex,
                matches=matches,
                match_count=len(matches),
                scanned=len(rows),
                instruction="ref 를 browser_click 에 넘겨라.",
            )

        # 0건은 "없다"가 아니라 "이 이름으로는 없다"이다. 그 구별을 안 해 주면
        # 모델이 없는 셀렉터를 지어내기 시작한다.
        #
        # 그런데 훑은 것이 0개면 그건 "이 이름으로는 없다"조차 아니다 — 아직 안
        # 그려졌거나 차단 화면이다. 그 셋을 `_why_empty` 가 가른다.
        why = self._why_empty(page, scanned=len(rows))
        near = [] if use_regex else _near_find_candidates(query, rows)
        if near and why["empty_reason"] == "absent":
            listed = " · ".join(f"{row.get('ref')} 「{_clean(row.get('name'), 40)}」({row.get('tag') or '요소'})" for row in near)
            instruction = (
                f"'{query}' 그대로는 없다. 이름이 비슷한 것: {listed}. 찾던 것이 맞으면 그 ref 를 써라 — "
                "아니면 browser_snapshot 으로 전체를 봐라. 한 번 못 찾았다고 끝내지 마라."
            )
        elif why["empty_reason"] == "absent":
            instruction = (
                f"{len(rows)}개를 훑었지만 '{query}' 는 없다. 다른 낱말로 다시 찾거나 "
                "browser_snapshot 으로 전체를 봐라 — 없는 셀렉터를 지어내지 마라."
            )
        else:
            instruction = why["instruction"]
        return self._evidence(
            "found",
            query=query,
            regex=use_regex,
            matches=[],
            match_count=0,
            scanned=len(rows),
            **({"near": near} if near else {}),
            **{**why, "instruction": instruction},
        )

    def _snapshot(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """Every operable element on the page, in **every frame**.

        Reading the top document only is the single reason generic control did
        not transfer off the pages we had hand-tuned: an editor, a payment
        widget or an admin console that renders inside an iframe reports "0
        elements", which reads as a broken page rather than as a snapshot that
        cannot see it. That misreading is written up in the 2026-08-05 handoff
        (6장) and cost most of two days on Naver alone.

        `include_box` adds on-screen geometry. It is off by default because a
        bounding box costs a round trip per element; the vision path turns it
        on because a screenshot without coordinates cannot be annotated.
        """
        # 하드 상한 200 → 400. 설정값을 올려도 여기서 다시 잘려 소용이 없었다
        # (2026-08-13: 설정 120 을 200 으로 올려도 실제 반환은 200 에서 멈춤).
        # 상한이 두 군데 있으면 낮은 쪽만 일한다.
        # `_ceiling` 은 안에서만 넘긴다(밑줄 인자는 바깥 호출에서 걸러진다) — 그림 도구가 화면 전체를 훑을 때 쓴다.
        ceiling = max(400, int(arguments.get("_ceiling") or 400))
        limit = max(1, min(int(arguments.get("limit") or self.config.browser_max_elements), ceiling))
        include_box = bool(arguments.get("include_box"))
        # ★ 예전에는 이 함수가 느린 것 자체로 기다림 노릇을 했다(요소 수백 개를 하나씩
        # 왕복하느라 50초). 브라우저 안에서 한 번에 훑도록 고치면서 그 우연한 유예가
        # 사라졌으므로, 기다림을 **일부러** 둔다. 0개는 "빈 페이지"와 구별되지 않고,
        # 그게 이 저장소가 여러 번 데인 고장이다(2026-08-05 8개 사이트).
        #
        # 이건 "아무거나 하나 그려졌는가"까지만 보장한다. 늦게 오는 장식(알림 개수
        # 따위)까지 기다리지는 않는다 — 검색 결과처럼 **정말 기다려야 하는 것**은
        # `_wait_for_results` 가 따로 본다.
        self._wait_until_operable(page)
        frames = self._frames_of(page)
        # ★ **번호는 화면 전체에 매기고, 내줄 것만 고른다** (2026-10-07 폼 벤치 둘째 판).
        #
        #   예전에는 문서 위쪽부터 200개에서 훑기를 멈췄다. 요소 1,062개인 이력서 화면에서:
        #     · 화면 아래 고정 막대의 「임시저장」은 문서 1,061번째라 **눈앞에 있는데 목록에 없었다.** 모델은 칸을 채우고
        #       스냅샷을 뜨고 또 채우기를 세 번 되풀이한 뒤 「임시저장했습니다」로 끝냈다(저장 0번).
        #     · 아래로 내려도 목록은 그대로였다. 안내문(「browser_find 로 찾아라」)은 달았지만 따르지 않았다.
        #     · 스냅샷이 번호표를 200개만 다시 붙여서, 방금 찾기가 준 1,058번이 그 자리에서 죽었다.
        #   이제 전부 훑어 **찾기와 같은 번호**를 붙이고(걸린 시간은 아래 `_MAX_SCAN` 주석의 실측),
        #   상한을 넘으면 **지금 화면에 보이는 것 먼저**, 남는 자리는 문서 위쪽부터 채운다. 사람이 보는 순서다.
        rows: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            if len(rows) >= _MAX_SCAN:
                break
            rows.extend(
                self._frame_elements(
                    frame,
                    frame_label=self._frame_label(frame, index),
                    frame_index=index,
                    budget=_MAX_SCAN - len(rows),
                    start=len(rows),
                    include_box=include_box,
                    group_cap=self.config.browser_snapshot_group_cap,
                    on_screen=True,
                )
            )
        # 접힌 것까지 이름을 기억해 둔다(_recover_ref 가 그 기억만 믿는다).
        self._remember_refs(rows)
        listed = [row for row in rows if not row.get("capped")]
        seen_now = {id(row) for row in rows if row.pop("on_screen", False)}
        if not arguments.get("_ceiling"):
            # ★ 줄마다 되풀이되는 **뻔한 값**은 모델에게 보내지 않는다 (2026-10-07). 요소 한 줄 156자 가운데 60자가
            #   `"type": "", "disabled": false, "frame": "main", "frame_index": 0` 였다 — 같은 글자 예산에 요소가 164개에서
            #   200개로 는다. 본문 프레임·눌리는 상태가 기본이고, 다른 프레임의 것·눌리지 않는 것만 그렇다고 적는다.
            #   (`frame_index` 는 어디서도 읽지 않는다. 안에서 쓰는 그림 도구의 목록(`_ceiling`)은 그대로 둔다.)
            for row in listed:
                if not row.get("frame_index"):
                    row.pop("frame", None)
                    row.pop("frame_index", None)
                if row.get("disabled") is False:
                    del row["disabled"]
                if row.get("type") == "":
                    del row["type"]
        # 안에서 쓰는 그림 도구(`_ceiling`)의 목록은 모델에게 통째로 가지 않는다 — 글자 예산은 모델에게 가는 스냅샷에만 둔다.
        output, shown_from_screen = _fit_snapshot(
            listed, seen_now, limit, 0 if arguments.get("_ceiling") else _SNAPSHOT_CHAR_BUDGET
        )
        if not output:
            # 이 함수의 docstring 이 "요소 0개는 망가진 페이지로 읽힌다"고 적어 놓고도,
            # 정작 0을 돌려줄 때는 아무 말이 없었다. 왜 0인지를 같이 준다.
            return self._evidence("snapshot", elements=[], element_count=0,
                                  frame_count=len(frames), **self._why_empty(page, listed_nothing=True))
        # 목록을 잘랐으면 **잘랐다고 말한다.** 조용히 자르면 "그 화면엔 그런 것이
        # 없다"는 잘못된 결론이 그대로 나간다 — 목록에서 빠진 것과 화면에 없는 것은
        # 자비스 눈에 똑같이 보인다.
        hidden = sum(int(item.get("group_more") or 0) for item in listed)
        extra: dict[str, Any] = {}
        if hidden:
            extra["list_more"] = hidden
            extra["instruction"] = (
                f"긴 목록에서 {hidden}개를 접었다(칸마다 최대 "
                f"{self.config.browser_snapshot_group_cap}개까지만 보여 준다). 접힌 목록에서"
                " 무언가를 고를 때는 browser_pick_suggestion 을 써라 — 그건 목록 전체를 본다."
            )
        # ★ 화면에 요소가 더 있는데 **위쪽부터만** 담았으면 그렇다고 말한다 (2026-10-07 폼 벤치).
        #   요소 1,062개인 이력서 수정 화면에서 스냅샷은 문서 위쪽 200개만 담았고, 스크롤해도 목록은 그대로였다.
        #   모델은 「스크롤 → 스냅샷」을 세 번 되풀이하다 「자기소개서 칸이 화면에 없습니다」로 끝냈다(3판 중 2판).
        #   접힌 목록(위)과 같은 규율이다 — 목록에서 빠진 것과 화면에 없는 것은 모델 눈에 똑같이 보인다.
        left = len(listed) - len(output)
        if left > 0:
            extra["more_elements"] = left
            extra["on_screen_count"] = shown_from_screen
            extra["instruction"] = (
                f"이 화면에는 조작할 요소가 {left}개 더 있다 — 목록의 **앞 {shown_from_screen}개가 지금 화면에 보이는 것**이고, "
                f"그 뒤 {len(output) - shown_from_screen}개는 문서 위쪽부터다. 스크롤하면 그때 보이는 것이 담긴다. "
                "이름을 아는 칸·단추는 browser_find 가 빠르다 — 번호는 스냅샷과 찾기가 같은 것을 쓴다. "
                + str(extra.get("instruction") or "")
            ).strip()
        # 안내·개수를 **목록 앞에** 둔다 — 긴 결과는 길목에서 뒤가 잘린다. 「더 있다」는 말이 잘리면 없는 것이 된다.
        return self._evidence(
            "snapshot",
            **extra,
            element_count=len(output),
            frame_count=len(frames),
            elements=output,
        )

    def _frame_elements(
        self,
        frame: Any,
        *,
        frame_label: str,
        frame_index: int,
        budget: int,
        start: int,
        include_box: bool,
        stamp_refs: bool = True,
        group_cap: int = 0,
        on_screen: bool = False,
    ) -> list[dict[str, Any]]:
        # ★ 2026-08-10: 여기가 조사 전체를 느리게 만들던 자리다.
        #
        # 요소 하나마다 is_visible·evaluate·get_attribute×6·is_disabled… 로 브라우저와
        # **열두 번씩 왕복**했다. 네이버 검색 한 화면이 요소 494개(프레임 5개)라
        # 왕복이 수천 번이 되고, 한 번에 8~10ms 라 그것만으로 50초다. 실측:
        #
        #     browser_open      1.1초    ← 페이지 여는 것은 빠르다
        #     browser_snapshot 53.5초    ← 화면을 읽는 데 이만큼
        #     browser_search   70.0초    ← 그래서 검색이 느렸다
        #
        # 브라우저 안에서 한 번에 훑고 결과만 받아 온다. 왕복이 프레임당 한 번이 된다.
        # 판정 기준은 Playwright 와 맞춘다(보임: 그려진 사각형이 있고 visibility 가
        # hidden 이 아님 / 비활성: disabled·aria-disabled·disabled fieldset 안).
        collected = self._frame_elements_fast(
            frame,
            frame_label=frame_label,
            frame_index=frame_index,
            budget=budget,
            start=start,
            include_box=include_box,
            stamp_refs=stamp_refs,
            group_cap=group_cap,
            on_screen=on_screen,
        )
        if collected is not None:
            return collected
        # 페이지가 evaluate 를 막는 경우(CSP·about:blank 등)에는 예전 길로 간다.
        # 느리지만 못 읽는 것보다는 낫다.
        try:
            elements = frame.locator(_INTERACTIVE)
            count = min(int(elements.count()), _MAX_SCAN)
        except Exception:
            return []
        found: list[dict[str, Any]] = []
        for index in range(count):
            locator = elements.nth(index)
            try:
                if not locator.is_visible():
                    continue
                ref = f"j{start + len(found) + 1}"
                locator.evaluate("(el, ref) => el.setAttribute('data-jarvis-ref', ref)", ref)
                tag = locator.evaluate("el => el.tagName.toLowerCase()")
                role = locator.get_attribute("role") or tag
                name = (
                    locator.get_attribute("aria-label")
                    or locator.get_attribute("title")
                    or locator.get_attribute("placeholder")
                    or locator.inner_text(timeout=1000)
                    or locator.get_attribute("value")
                    or ""
                )
                item: dict[str, Any] = {
                    "ref": ref,
                    "role": _clean(role, 40),
                    "name": _clean(name, 180),
                    "tag": _clean(tag, 20),
                    "type": _clean(locator.get_attribute("type"), 30),
                    "disabled": locator.is_disabled(),
                    "frame": frame_label,
                    "frame_index": frame_index,
                }
                href = locator.get_attribute("href")
                if href:
                    item["href"] = _clean(href, 400)
                if include_box:
                    box = self._box_of(locator)
                    if box:
                        item["box"] = box
                found.append(item)
                if len(found) >= budget:
                    break
            except Exception:
                continue
        return found

    def _frame_elements_fast(
        self,
        frame: Any,
        *,
        frame_label: str,
        frame_index: int,
        budget: int,
        start: int,
        include_box: bool,
        stamp_refs: bool = True,
        group_cap: int = 0,
        on_screen: bool = False,
    ) -> list[dict[str, Any]] | None:
        """프레임 하나를 **브라우저 안에서 한 번에** 훑는다. 못 하면 None.

        느린 길과 **같은 것**을 돌려줘야 한다 — ref 를 붙이는 것까지 포함해서.
        `data-jarvis-ref` 는 나중에 클릭·입력할 때 다시 찾는 주소이므로, 여기서
        안 붙이면 스냅샷은 빨라지고 조작이 통째로 깨진다.
        """
        script = """
        (args) => {
          const { selector, maxScan, maxDeepScan, budget, start, includeBox, stamp, stampRefs, groupCap, withScreen,
                  floor, isMain } = args;
          const clean = (value, max) => {
            const text = (value == null ? "" : String(value)).replace(/\\s+/g, " ").trim();
            return text.length > max ? text.slice(0, max) : text;
          };
          // Playwright 의 '보임' 정의: 그려진 사각형이 있고 visibility 가 hidden 이 아님
          const visible = (el) => {
            if (!el.getClientRects().length) return false;
            const st = window.getComputedStyle(el);
            if (st.visibility === "hidden") return false;
            // ★ 투명한 것은 화면에 없는 것이다. 닫힌 달력·드롭다운이 opacity:0 으로
            // 남아 있는 경우가 많아, 이걸 안 거르면 날짜 칸 수십 개가 목록을 채운다
            // (위시켓에서 11~31 이 43개 들어왔다). 조상까지 조금 올라가 본다.
            for (let p = el, i = 0; p && i < 6; p = p.parentElement, i++) {
              const ps = p === el ? st : window.getComputedStyle(p);
              if (parseFloat(ps.opacity) === 0) return false;
            }
            return true;
          };
          // ★ `stampRefs` 가 거짓이면 **번호를 새로 매기지 않는다.**
          //
          // 속으로 화면을 훑는 일(후보 세기 따위)이 번호를 다시 찍으면, 방금 밖에
          // 내준 ref 가 그 자리에서 어긋난다. 오늘 그것 때문에 두 번 깨졌다
          // (invalid_element_ref, 그리고 옵션 표식이 스냅샷 번호를 덮어쓴 것).
          // 번호는 **사람·모델에게 목록을 내줄 때만** 새로 매긴다.
          const mark = "__jarvis_" + stamp;   // 호출마다 새 표식 (지난 표식과 안 섞이게)
          // ★ 새로 번호를 매기기 전에 **옛 번호표를 전부 뗀다** (2026-08-11).
          //
          // 붙이기만 하고 안 뗐더니 같은 번호가 여러 노드에 남았다. 화면이 다시
          // 그려지면 옛 노드는 화면에서 사라지는데 번호표는 그대로 붙어 있고,
          // `[data-jarvis-ref="j104"]` 로 찾으면 **그 유령이 먼저 잡힌다** —
          // 그래서 "요소는 있는데 안 보인다"가 됐다(경험 칸이 계속 실패한 이유).
          //
          // 한 번호는 한 요소만 가리켜야 한다. 그게 이 번호표의 유일한 약속이다.
          //
          // ★ 2026-10-07: 그 약속을 **떼고 다시 붙이기**가 아니라 **한 번 준 번호를 안 바꾸기**로 지킨다.
          //
          // 다시 붙이면 번호가 문서 순서대로 새로 매겨진다. 그래서 줄 하나가 끼면 그 뒤가 전부 밀렸다. 지원서 판(E#2):
          //   스냅샷에서 「임시저장」이 j12 → 「자격증 추가」를 누르자 줄이 생겨 j15 로. 모델은 앞에서 본 번호로 눌렀고,
          //   j13 은 「자격증 추가」(줄이 하나 더 생겼다), j14 는 동의 체크 칸이 아니라 새로 생긴 글 칸이었다 — 조용히.
          //   번호 하나만 달랐으면 「지원하기」였다. 모델이 든 번호의 뜻을, 그 사이에 돈 다른 훑기가 바꾸면 안 된다.
          // 이제 번호는 **그 요소의 것**이다: 이미 받은 번호는 그대로, 처음 보는 요소만 새 번호(지금까지의 최댓값 + 1),
          // 한 번 쓴 번호는 다시 쓰지 않는다. 같은 번호가 두 노드에 있을 수 없으니 유령도 안 생긴다(복제된 노드는 새 번호).
          // 새 문서(이동·새로 고침)는 1부터 다시 센다. 번호가 문서 순서와 어긋날 수 있다 — 목록은 여전히 문서 순서로 준다.
          let high = Number(floor) || 0;
          const usedRefs = new Set();
          if (stampRefs) {
            const firstLook = !document.__jarvisRefDoc;
            document.__jarvisRefDoc = true;
            if (firstLook && isMain) high = 0;
            for (const old of document.querySelectorAll("[data-jarvis-ref]")) {
              const had = /^j(\\d+)$/.exec(old.getAttribute("data-jarvis-ref") || "");
              // 처음 보는 문서에 붙어 온 번호표(다른 문서에서 복사된 조각)·모양이 다른 것은 뗀다.
              if (firstLook || !had) { old.removeAttribute("data-jarvis-ref"); continue; }
              high = Math.max(high, Number(had[1]));
            }
          }
          // 담은 것을 **품고 있는** 조상에 표시해 둔다 — 「이미 담은 것을 품었나」를 담은 것 수만큼 되묻지 않게.
          const holds = mark + "_holds";
          // ★ 칸의 이름은 **그 칸에 붙은 라벨**이다 (2026-10-07 폼 벤치 둘째 판).
          //
          // `<label for>` 를 한 번도 읽지 않았다. 라벨이 붙은 빈 칸은 속성에도 안에도 글이 없으니 부모의 글을 빌렸고,
          // 한 묶음 안의 칸 여섯이 전부 「자기소개서 자기소개서 1 제목 자기소개서 1 내용 … 안의 textarea」가 됐다.
          // 모델은 번호만 보고 골랐다 — 세 판 중 두 판이 둘째 칸에 쓰고 「입력하고 저장했습니다」라고 답했다.
          // 웹이 정한 이름의 출처 순서 그대로다: aria-labelledby → aria-label → label. 추측 규칙은 넣지 않는다.
          const labelOf = (el, tag) => {
            const ids = (el.getAttribute("aria-labelledby") || "").split(/\\s+/).filter(Boolean);
            if (ids.length) {
              const root = el.getRootNode ? el.getRootNode() : document;
              const said = ids.map((id) => {
                const node = root.getElementById ? root.getElementById(id) : document.getElementById(id);
                return node ? (node.innerText || node.textContent || "") : "";
              }).join(" ");
              if (clean(said, 10)) return said;
            }
            const own = el.getAttribute("aria-label");
            if (own && clean(own, 10)) return own;
            if (tag !== "input" && tag !== "textarea" && tag !== "select") return "";
            const said = [];
            for (const label of Array.from(el.labels || [])) {
              // 라벨이 칸을 감싸고 있으면 칸(과 그 안의 선택지 글)은 빼고 읽는다.
              for (const node of Array.from(label.childNodes)) {
                if (node.nodeType === 3) said.push(node.textContent || "");
                else if (node.nodeType === 1 && node !== el && !node.contains(el) &&
                         !node.matches("input,textarea,select,button")) said.push(node.innerText || node.textContent || "");
              }
            }
            return said.join(" ");
          };
          // ★ 라벨 태그 없이 **표·정의 목록으로 짠 폼**: 그 줄의 머리 칸(th)·앞의 dt 가 그 칸의 이름이다 (2026-10-07 과제 E).
          //   `<tr><th>희망연봉</th><td><input> 만원</td></tr>` 의 칸 이름이 「만원 안의 input」이었고, 선택 상자는 선택지를 이어
          //   붙인 글, div 로 만든 드롭다운은 「선택하세요」였다 — 모델은 「지원 분야 입력란을 찾지 못했다」고 답했다.
          //   가까운 글을 짐작하는 것이 아니라 HTML 이 정한 관계(머리 칸·용어)만 읽는다.
          const rowHeadOf = (el) => {
            const cell = el.closest ? el.closest("td,dd") : null;
            if (!cell) return "";
            if (cell.tagName === "TD") {
              const row = cell.parentElement;
              const head = row ? Array.from(row.children).find((c) => c.tagName === "TH") : null;
              return head ? clean(head.innerText, 40) : "";
            }
            let prev = cell.previousElementSibling;
            while (prev && prev.tagName === "DD") prev = prev.previousElementSibling;
            return prev && prev.tagName === "DT" ? clean(prev.innerText, 40) : "";
          };
          const ancestorPicked = (el) => {
            for (let p = el.parentElement, i = 0; p && i < 30; p = p.parentElement, i++) {
              if (p[mark]) return true;
            }
            return false;
          };
          const out = [];
          const outEls = [];   // out 과 같은 순서의 요소 — 훑은 뒤 「같은 이름의 칸」을 가려 줄 때 쓴다
          // ★ 목록 하나가 예산을 다 먹지 못하게 한다 (2026-08-11).
          //
          // 스냅샷은 DOM 순서로 자른다. 그래서 드롭다운이 열려 있으면 그 카탈로그가
          // 앞에서 예산을 통째로 쓰고, 뒤에 있는 저장 버튼·다음 입력칸은 화면에
          // 뻔히 보이는데도 목록에 안 들어온다. 위시켓 기술 카탈로그가 그랬다.
          //
          // 사이트마다 선택자를 늘리지 않는다 — **묶음의 구조**로 판정한다.
          // 그리고 자를 때는 **잘랐다고 적는다**(`group_more`). 조용히 자르면
          // "그 화면엔 그런 것이 없다"는 잘못된 결론이 그대로 나간다.
          const LIST_HOST = "[role=listbox],[role=menu],[role=tree],[role=grid]," +
                            "ul,ol,datalist,select,tbody";
          const groups = new Map();
          const groupOf = (el) => (groupCap > 0 ? el.parentElement?.closest?.(LIST_HOST) : null);
          const overGroupCap = (el) => {
            const host = groupOf(el);
            if (!host) return false;
            const seen = groups.get(host);
            if (!seen) { groups.set(host, { count: 1, last: null }); return false; }
            if (seen.count < groupCap) { seen.count += 1; return false; }
            // 넘친 것은 담지 않되, 그 묶음의 마지막 항목에 **몇 개가 더 있는지** 적는다.
            if (seen.last) seen.last.group_more = (seen.last.group_more || 0) + 1;
            return true;
          };
          const noteGroup = (el, item) => {
            const host = groupOf(el);
            if (host && groups.has(host)) groups.get(host).last = item;
          };
          // ★ **번호는 담든 접든 문서 순서로 하나씩** 준다 (2026-10-07). 접힌 항목(`capped`)도 번호표를 받는다 —
          //   그래야 접는 스냅샷과 접지 않는 찾기가 **같은 요소에 같은 번호**를 준다. 예전에는 접힌 것이 번호를 안 먹어서,
          //   찾기가 준 번호가 스냅샷 한 번에 다른 것을 가리키거나 사라졌다(「기억에 j1058 가 없다 (기억 200개)」).
          const take = (el, capped) => {
            let ref = "j" + (start + out.length + 1);
            if (stampRefs) {
              const had = el.getAttribute("data-jarvis-ref") || "";
              if (had && !usedRefs.has(had)) {
                ref = had;                       // 이미 받은 번호 — 그대로
              } else {
                high += 1;                       // 처음 보는 요소(또는 복제돼 번호가 겹친 것) — 새 번호
                ref = "j" + high;
                el.setAttribute("data-jarvis-ref", ref);
              }
              usedRefs.add(ref);
            }
            el[mark] = true;
            for (let p = el.parentElement; p && !p[holds]; p = p.parentElement) p[holds] = true;
            const tag = el.tagName.toLowerCase();
            // ★ 이름이 없으면 모델은 그 요소를 **고를 수가 없다.** 목록에 담아 놓고
            // 이름을 안 주면 "(이름없음)" 스물일곱 개가 되고, 그건 안 담은 것과 같다.
            // alt 를 안 읽고 있었고(아이콘이 <img> 인 사이트가 많다), 그것도 없으면
            // 그 요소가 놓인 줄의 글을 빌려 온다 — 사람도 그렇게 알아본다
            // ("Python 줄의 연필").
            const labelled = clean(labelOf(el, tag), 180);
            const rowHead = rowHeadOf(el);
            let name =
              labelled ||
              el.getAttribute("aria-label") ||
              el.getAttribute("title") ||
              el.getAttribute("alt") ||
              el.getAttribute("placeholder") ||
              "";
            // 제 이름이 없는 글 칸·선택 상자는 줄 머리가 이름이다. 선택 상자의 안쪽 글은 선택지라 이름이 아니다(선택지는 따로 준다).
            const kind = (el.getAttribute("type") || "text").toLowerCase();
            const writable = tag === "textarea" || tag === "select" ||
              (tag === "input" && !["submit", "button", "reset", "image", "checkbox", "radio", "file", "hidden"].includes(kind));
            if (!clean(name, 10) && writable && rowHead) name = rowHead;
            // 값(value)이 이름인 것은 누르는 단추뿐이다(<input type=submit value="검색">). 글을 넣는 칸의 값은 **내용**이라 이름이 아니다 —
            // 서버가 값을 채워 내려보낸 라벨 없는 폼에서 칸 이름이 「010-0000-0101」이 됐고, 같은 이름의 칸을 가려 줄 수도 없었다(2026-10-07).
            if (!clean(name, 10)) name = el.innerText || (writable ? "" : el.getAttribute("value")) || "";
            if (!clean(name, 10)) {
              for (let p = el.parentElement, i = 0; p && i < 4; p = p.parentElement, i++) {
                const near = clean(p.innerText, 60);
                if (near) { name = near + " 안의 " + tag; break; }
              }
            }
            const item = {
              ref,
              role: clean(el.getAttribute("role") || tag, 40),
              name: clean(name, 180),
              tag: clean(tag, 20),
              type: clean(el.getAttribute("type"), 30),
              disabled:
                el.disabled === true ||
                el.getAttribute("aria-disabled") === "true" ||
                !!el.closest("fieldset[disabled]"),
            };
            if (capped) item.capped = true;
            // 같은 줄의 다른 것(라디오·단추·직접 만든 드롭다운)에는 줄 머리를 문맥으로 붙인다 — 「어느 줄의 삭제인가」.
            if (rowHead && item.name !== rowHead) item.row = rowHead;
            // 라벨이 이름이 됐으면 칸 안의 흐린 글(placeholder)은 따로 준다 — 그 글로 찾는 일이 계속 되게.
            if (labelled) {
              const hint = clean(el.getAttribute("placeholder"), 60);
              if (hint && hint !== item.name) item.placeholder = hint;
            }
            if (withScreen) {
              const r = el.getBoundingClientRect();
              if (r.bottom > 0 && r.right > 0 && r.top < (window.innerHeight || 0) && r.left < (window.innerWidth || 0)) {
                item.on_screen = true;
              }
            }
            // ★ 주소는 **절대경로로** 담는다 (2026-08-12).
            //
            // `getAttribute("href")` 는 원시 속성이라 사이트 내부 링크가 상대경로
            // ("/prod/123") 로 나온다. 그런데 이 주소를 대조하는 쪽은 전부 절대경로다
            // (`_CHROME_LINKS_JS`·`_RESULT_LIST_JS` 는 `a.href` 를 쓴다). 그래서
            // **내부 링크는 어느 쪽과도 안 맞았다**:
            //   - 목록으로 좁히기가 통째로 실패 → 외부 광고(절대경로)만 살아남음
            //   - 네비게이션 필터가 내부 메뉴를 한 번도 못 걸러냄
            // `_validate_url` 도 상대경로를 받으면 "https:///prod/123" 을 만든다.
            // ★ 2026-10-03 (Browser Use 조작 방식 조사 · Online-Mind2Web NVIDIA·LandWatch): 선택 상자는 이름이 선택지 글자를
            //   다 이어 붙인 180자라 **무엇이 골라져 있는지·선택지가 몇 개인지** 몰랐다. 따로 담는다(앞 8개 + 개수).
            //   입력칸은 지금 들어 있는 값, 체크 칸은 체크 여부 — 고른 뒤 「남았나」를 다음 스냅샷에서 바로 본다.
            if (tag === "select") {
              const opts = Array.from(el.options || []);
              item.options_count = opts.length;
              item.options = opts.slice(0, 8).map((o) => clean(o.label || o.text, 40)).filter(Boolean);
              const chosen = el.selectedOptions && el.selectedOptions[0];
              if (chosen) item.selected = clean(chosen.label || chosen.text, 60);
            } else if (tag === "input" || tag === "textarea") {
              const kind = (el.getAttribute("type") || "text").toLowerCase();
              const secret = /^cc-|one-time-code|current-password|new-password/i.test(el.getAttribute("autocomplete") || "")
                || /card|cvv|cvc|ssn|주민|비밀/i.test((el.getAttribute("name") || "") + " " + (el.id || ""));
              if (kind === "checkbox" || kind === "radio") item.checked = !!el.checked;
              else if (!["password", "file", "hidden"].includes(kind) && !secret && el.value) item.value = clean(el.value, 60);
              if (["date", "datetime-local", "month", "time", "week"].includes(kind)) item.format = {
                "date": "YYYY-MM-DD", "datetime-local": "YYYY-MM-DDTHH:MM", "month": "YYYY-MM", "time": "HH:MM", "week": "YYYY-Www",
              }[kind];
            }
            const href = el.getAttribute("href");
            if (href) {
              let absolute = href;
              try { absolute = new URL(href, document.baseURI).href; } catch (e) {}
              item.href = clean(absolute, 400);
            }
            if (includeBox) {
              const box = el.getBoundingClientRect();
              if (box && (box.width || box.height)) {
                item.box = {
                  x: Math.trunc(box.x), y: Math.trunc(box.y),
                  width: Math.trunc(box.width), height: Math.trunc(box.height),
                };
              }
            }
            out.push(item);
            outEls.push(el);
            if (!capped) noteGroup(el, item);
          };

          // ① 확실한 것부터 — 태그·role 로 이미 조작 대상임이 분명한 것들
          for (const el of Array.from(document.querySelectorAll(selector)).slice(0, maxScan)) {
            if (out.length >= budget) break;
            if (!visible(el) || ancestorPicked(el)) continue;
            take(el, overGroupCap(el));
          }

          // ② ★ 눈에는 보이는데 태그로는 안 걸리는 것들 (2026-08-11)
          //
          // 요즘 웹은 <div onclick> 과 <li> 로 조작 요소를 만든다. 위시켓 보유기술
          // 화면 실측: 연필(수정) 아이콘 7개가 화면에 멀쩡히 보이는데 button 은 2개뿐이라
          // 손자리 목록에 **하나도 안 들어왔다.** 그래서 "누르지를 못한다"가 아니라
          // 처음부터 **안 보였다** — 모델은 후보 중 제일 비슷한 저장 버튼을 골랐다.
          //
          // 선택자를 사이트마다 늘리는 건 두더지 잡기다. 대신 **사람에게 클릭하라고
          // 알리는 신호**를 본다: 손가락 커서, role, 키보드 포커스 가능, onclick.
          // 로그인 문을 문구가 아니라 구조로 판정한 것과 같은 규칙이다.
          const clickableRole = new Set([
            "option","listitem","menuitem","menuitemcheckbox","menuitemradio",
            "button","link","tab","checkbox","radio","switch","combobox","treeitem",
          ]);
          const looksClickable = (el) => {
            if (el.hasAttribute("onclick")) return true;
            const role = (el.getAttribute("role") || "").toLowerCase();
            if (role && clickableRole.has(role)) return true;
            const tabindex = el.getAttribute("tabindex");
            if (tabindex !== null && Number(tabindex) >= 0) return true;
            return window.getComputedStyle(el).cursor === "pointer";
          };
          // 이름도 없고 아이콘도 없는 껍데기까지 담으면 목록이 쓰레기가 된다.
          // 다만 **이름 없는 아이콘 버튼**은 담아야 한다 — 위시켓의 수정(연필)이
          // 정확히 그것이다: 24×24, 글자 없음, 배경 이미지. 이름으로만 거르면
          // 화면에 뻔히 보이는 그 버튼이 목록에서 통째로 사라진다.
          const iconSized = (el) => {
            const b = el.getBoundingClientRect();
            return b.width >= 12 && b.width <= 64 && b.height >= 12 && b.height <= 64;
          };
          const worthShowing = (el) =>
            clean(el.getAttribute("aria-label") || el.getAttribute("title") || el.innerText, 40) !== "" ||
            !!el.querySelector("svg, img, i") ||
            iconSized(el);
          if (out.length < budget) {
            const all = Array.from(document.querySelectorAll("body *")).slice(0, maxDeepScan);
            for (const el of all) {
              if (out.length >= budget) break;
              if (el[mark] || ancestorPicked(el)) continue;
              // 이미 담은 것을 품고 있으면 그건 껍데기다 — 안쪽 것이 진짜 대상이다.
              if (el[holds]) continue;
              if (!visible(el) || !looksClickable(el) || !worthShowing(el)) continue;
              take(el, overGroupCap(el));
            }
          }
          // ★ **같은 이름의 칸이 둘 이상이면, 어느 묶음의 칸인지를 붙인다** (2026-10-07 폼 벤치 과제 J · 3판 중 1판).
          //   라벨 없는 폼에 「본인 정보 — 이름·연락처·주소」와 「비상 연락처 — 이름·연락처」가 있었다. 목록에는 「연락처 안의 input」이
          //   둘이었고 모델은 앞의 것(본인)에 넣고 「비상 연락처를 바꿨다」고 답했다. 고를 근거를 안 줬다 — 배송지/청구지,
          //   학력 1/학력 2 처럼 묶음이 되풀이되는 폼이 다 이 모양이다.
          //   낱말로 제목을 찾지 않는다. 구조로 찾는다: 같은 이름의 다른 칸과 **갈라지는 가지**가 그 칸의 묶음이다.
          //     ① 그 가지가 칸을 여럿 품고 있으면 가지의 첫 줄이 묶음 이름이다.
          //     ② 가지가 그 칸의 줄 하나뿐이면(제목과 줄들이 나란히 놓인 폼), 앞쪽 형제 가운데 칸을 품지 않은 가장 가까운 글이다.
          //   같은 이름의 칸들이 전부 같은 묶음 이름을 받으면 가려 주는 것이 없으니 붙이지 않는다.
          const FIELDS = "input, textarea, select";
          const plainField = (item) => (item.tag === "textarea" || item.tag === "select" ||
            (item.tag === "input" && !["submit", "button", "reset", "image", "hidden", "file"].includes(item.type || "text")));
          const firstLine = (el) => {
            const lines = String(el.innerText || "").split(String.fromCharCode(10));
            for (const line of lines) { const t = clean(line, 40); if (t) return t; }
            return "";
          };
          const sameName = new Map();
          out.forEach((item, i) => {
            if (!item.name || !plainField(item)) return;
            const key = item.tag + "|" + item.name + "|" + (item.row || "");
            if (!sameName.has(key)) sameName.set(key, []);
            sameName.get(key).push(i);
          });
          for (const group of sameName.values()) {
            if (group.length < 2) continue;
            const labels = group.map((i) => {
              const el = outEls[i];
              const others = group.filter((o) => o !== i).map((o) => outEls[o]);
              let branch = el, common = el.parentElement;
              while (common && !others.some((o) => common.contains(o))) { branch = common; common = common.parentElement; }
              if (!common) return "";
              const own = clean(String(out[i].name).split(" 안의 ")[0], 40);
              if (branch !== el && branch.querySelectorAll(FIELDS).length > 1) {
                const head = firstLine(branch);
                if (head && head !== own) return head;
              }
              for (let s = branch.previousElementSibling; s; s = s.previousElementSibling) {
                if (s.matches(FIELDS) || s.querySelector(FIELDS)) continue;
                const t = firstLine(s);
                if (t && t !== own) return t;
              }
              return "";
            });
            if (new Set(labels).size < 2) continue;
            group.forEach((i, n) => { if (labels[n]) out[i].group = labels[n]; });
          }
          return { rows: out, high };
        }
        """
        # 번호의 최댓값은 **페이지 단위로** 이어 간다 — 프레임마다 따로 세면 두 프레임에 같은 번호가 생긴다.
        highs = self.__dict__.setdefault("_ref_high", {})
        page_key = id(getattr(frame, "page", None) or frame)
        try:
            raw = frame.evaluate(
                _deep_js(script),
                {
                    "selector": _INTERACTIVE,
                    "maxScan": _MAX_SCAN,
                    "maxDeepScan": _MAX_DEEP_SCAN,
                    "budget": budget,
                    "start": start,
                    "includeBox": include_box,
                    # 표식이 호출마다 달라야 한다. 같은 노드에 지난 표식이 남아 있으면
                    # 두 번째 스냅샷이 "이미 담았다"고 오판한다.
                    "stamp": f"{int(time.time() * 1000)}_{start}",
                    "stampRefs": bool(stamp_refs),
                    "groupCap": max(0, int(group_cap)),
                    "withScreen": bool(on_screen),
                    "floor": int(highs.get(page_key, 0)),
                    "isMain": frame_index == 0,
                },
            )
        except Exception:
            return None
        if isinstance(raw, dict):
            if stamp_refs:
                try:
                    highs[page_key] = int(raw.get("high") or 0)
                except (TypeError, ValueError):
                    pass
            raw = raw.get("rows")
        if not isinstance(raw, list):
            return None
        # 프레임 이름표는 파이썬 쪽 것이다. 브라우저 안에서는 자기가 몇 번째 프레임인지
        # 모른다 — 그래서 여기서 붙인다.
        for item in raw:
            item["frame"] = frame_label
            item["frame_index"] = frame_index
        return raw

    @staticmethod
    def _box_of(locator: Any) -> dict[str, int] | None:
        try:
            box = locator.bounding_box()
        except Exception:
            return None
        if not box:
            return None
        try:
            return {
                "x": int(box["x"]),
                "y": int(box["y"]),
                "width": int(box["width"]),
                "height": int(box["height"]),
            }
        except Exception:
            return None

    @staticmethod
    def _frame_label(frame: Any, index: int) -> str:
        """A stable, human-readable name for a frame.

        Frame *indexes* shift as a page lazy-loads iframes, so they are not
        addresses -- the label exists to be read in a failure report and in the
        candidate list handed to the model, not to be stored and reused.
        """
        try:
            name = _clean(getattr(frame, "name", "") or "", 60)
        except Exception:
            name = ""
        if name:
            return name
        if index == 0:
            return "main"
        try:
            url = _clean(getattr(frame, "url", "") or "", 100)
        except Exception:
            url = ""
        return url or f"frame{index}"

    def _find_selector(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve author-written selectors to a ref, searching every frame.

        This is the bridge a site recipe needs. The model is told never to
        invent a selector -- it guesses, and a guessed selector is what burned
        two days -- but a *recipe* is written and reviewed by a person, and its
        selectors are exactly the durable knowledge about a site worth keeping.

        Handing back a ref rather than a locator is what keeps the rest honest:
        everything downstream (guarded click, evidence check, read-only gate)
        already works on refs, so a recipe gets those for free instead of
        growing its own click path.

        Failing here names every selector tried, in every frame -- the
        information needed to fix it, which a click timeout does not carry.
        """
        selectors = [str(s) for s in (arguments.get("selectors") or []) if str(s).strip()]
        if not selectors:
            raise ValueError("selectors_required")
        require_visible = arguments.get("visible", True)
        tried: list[str] = []
        for index, frame in enumerate(self._frames_of(page)):
            label = self._frame_label(frame, index)
            for selector in selectors:
                try:
                    locator = frame.locator(selector).first
                    if int(frame.locator(selector).count()) == 0:
                        tried.append(f"{label}:{selector}=0")
                        continue
                    if require_visible and not locator.is_visible():
                        tried.append(f"{label}:{selector}=hidden")
                        continue
                except Exception as exc:
                    tried.append(f"{label}:{selector}=error:{_clean(exc, 40)}")
                    continue
                ref = f"j{self._next_ref()}"
                try:
                    # 이미 번호를 받은 요소면 그 번호를 돌려준다 — 덮어쓰면 스냅샷이 준 번호가 죽는다(2026-10-07).
                    kept = locator.evaluate(
                        "(el, ref) => { const had = el.getAttribute('data-jarvis-ref');"
                        " if (had) return had; el.setAttribute('data-jarvis-ref', ref); return ref; }", ref
                    )
                    if isinstance(kept, str) and re.fullmatch(r"j\d{1,5}", kept):
                        ref = kept
                except Exception as exc:
                    raise RuntimeError(f"selector_not_markable:{selector}:{_clean(exc, 80)}") from exc
                return self._evidence(
                    "selector_found",
                    ref=ref,
                    selector=selector,
                    frame=label,
                    text=self._locator_text(locator, 120),
                )
        raise RuntimeError("selector_not_found:" + " | ".join(tried or selectors))

    def _next_ref(self) -> int:
        """Ref numbers that do not collide with the last snapshot's.

        A recipe stamping `j1` over an element the snapshot already called `j1`
        would make a stale ref resolve to the wrong element -- silently, and
        only sometimes.
        """
        with self._lock:
            self._ref_counter += 1
            return 900 + (self._ref_counter % 90)

    def _visible_rollers(self, page: Any, text: str) -> str:
        """글 속 숫자 굴림 띠(「0 1 2 … 9」)를 화면에 보이는 숫자로. 띠가 없거나 칸을 못 찾으면 글 그대로."""
        if not _ROLLER_RUN.search(text or ""):
            return text
        try:
            digits = list(page.evaluate(_ROLLER_DIGITS_JS) or [])
        except Exception:
            return text
        return _fold_rollers(text, digits) if digits else text

    def _read(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """Visible text -- from every frame, not just the top document.

        Same blind spot as the snapshot had: a page whose content lives in an
        iframe used to read as empty. Each frame gets its own slice of the
        budget so one chatty frame cannot starve the one being asked about.
        """
        max_chars = max(500, min(int(arguments.get("max_chars") or 12000), 20000))
        selector = _clean(arguments.get("selector"), 200)
        frames = self._frames_of(page)
        parts: list[str] = []
        used = 0
        for index, frame in enumerate(frames):
            if used >= max_chars:
                break
            try:
                locator = frame.locator(selector).first if selector else frame.locator("body")
                if selector and int(frame.locator(selector).count()) == 0:
                    continue
                text = _clean(locator.inner_text(), max_chars - used)
            except Exception:
                continue
            if not text:
                continue
            label = self._frame_label(frame, index)
            parts.append(text if index == 0 and not selector else f"[{label}] {text}")
            used += len(text)
        shadow = False
        if not selector:
            deep = self._deep_text(page, max_chars)
            light = sum(len(part) for part in parts)
            # 일반 DOM 글이 거의 없고 섀도 안 글이 훨씬 많을 때만 바꾼다(섞인 페이지는 그대로).
            if deep and len(deep) > max(2 * light, light + 40):
                parts, shadow = [deep], True
        text = self._visible_rollers(page, "\n\n".join(parts))[:max_chars]
        return self._evidence(
            "read", text=text, char_count=len(text), frame_count=len(frames),
            **({"shadow_dom": True} if shadow else {}),
        )

    #: 누를 수 있는 것으로 보는 접근성 역할.
    _AX_TARGET_ROLES = frozenset({
        "button", "link", "textbox", "searchbox", "combobox", "menuitem", "tab", "checkbox", "radio",
        "switch", "option", "listitem", "treeitem",
    })

    def _ax_targets(self, page: Any, *, limit: int = 30) -> list[dict[str, Any]]:
        """접근성 트리에서 **누를 수 있는 것의 이름·역할·가운데 좌표**. 못 구하면 빈 목록.

        ★ 2026-09-17. 닫힌 섀도 DOM·캔버스 화면은 페이지 안 코드로는 아무것도 못 본다. 크롬의 접근성 트리는
          닫힌 섀도 DOM 안까지 들어간다(화면 읽기 프로그램이 읽어야 하므로). 여기서 뽑은 좌표를 browser_click_at 에 준다.
        """
        session = None
        found: list[dict[str, Any]] = []
        try:
            session = page.context.new_cdp_session(page)
            session.send("DOM.getDocument", {"depth": 0})
            nodes = (session.send("Accessibility.getFullAXTree") or {}).get("nodes") or []
            for node in nodes:
                if len(found) >= limit:
                    break
                if node.get("ignored"):
                    continue
                role = str(((node.get("role") or {}).get("value")) or "").lower()
                name = _clean(((node.get("name") or {}).get("value")), 120)
                backend = node.get("backendDOMNodeId")
                if role not in self._AX_TARGET_ROLES or not backend or not (name or role in {"textbox", "searchbox", "combobox"}):
                    continue
                try:
                    quad = (session.send("DOM.getBoxModel", {"backendNodeId": backend}) or {}).get("model", {}).get("border") or []
                except Exception:
                    continue
                if len(quad) < 8:
                    continue
                xs, ys = quad[0::2], quad[1::2]
                width, height = max(xs) - min(xs), max(ys) - min(ys)
                if width < 4 or height < 4:
                    continue
                found.append({"role": role, "name": name, "x": int(sum(xs) / 4), "y": int(sum(ys) / 4),
                              "width": int(width), "height": int(height)})
        except Exception:
            return found
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass
        return found

    def _point_target(self, page: Any, x: int, y: int) -> dict[str, str]:
        """그 좌표에 있는 요소의 **역할·이름·type** — 안전 검사의 재료. 닫힌 섀도 DOM 안이어도 접근성 트리로 읽는다."""
        target = {"tag": "", "role": "", "name": "", "type": ""}
        session = None
        try:
            session = page.context.new_cdp_session(page)
            session.send("DOM.getDocument", {"depth": 0})
            located = session.send("DOM.getNodeForLocation", {"x": int(x), "y": int(y), "ignorePointerEventsNone": True}) or {}
            backend = located.get("backendNodeId")
            if backend:
                described = (session.send("DOM.describeNode", {"backendNodeId": backend}) or {}).get("node") or {}
                target["tag"] = _clean(described.get("nodeName"), 30).lower()
                attributes = described.get("attributes") or []
                attrs = dict(zip(attributes[0::2], attributes[1::2]))
                target["type"] = _clean(attrs.get("type"), 30).lower()
                tree = (session.send("Accessibility.getPartialAXTree", {"backendNodeId": backend, "fetchRelatives": True}) or {}).get("nodes") or []
                # 그 노드 또는 가장 가까운 조상 중 이름이 있는 것
                for node in tree:
                    name = _clean(((node.get("name") or {}).get("value")), 300)
                    role = str(((node.get("role") or {}).get("value")) or "").lower()
                    if node.get("backendDOMNodeId") == backend:
                        target["role"] = role
                        if name:
                            target["name"] = name
                if not target["name"]:
                    for node in reversed(tree):
                        name = _clean(((node.get("name") or {}).get("value")), 300)
                        if name and not node.get("ignored"):
                            target["name"] = name
                            break
                if not target["name"]:
                    target["name"] = _clean(attrs.get("aria-label") or attrs.get("title") or attrs.get("placeholder") or attrs.get("value"), 300)
        except Exception:
            pass
        finally:
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass
        return target

    def _checked_point(self, page: Any, arguments: dict[str, Any]) -> tuple[int, int, dict[str, str]]:
        """좌표를 창 안으로 확인하고, 그 점의 요소가 **browser_click 과 같은 안전 검사**를 통과하는지 본다."""
        try:
            x, y = int(arguments.get("x")), int(arguments.get("y"))
        except (TypeError, ValueError) as exc:
            raise ValueError("x_y_required") from exc
        size = getattr(page, "viewport_size", None) or {}
        width, height = int(size.get("width") or 10_000), int(size.get("height") or 10_000)
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"point_outside_window:{x},{y} (창 {width}×{height})")
        target = self._point_target(page, x, y)
        name, element_type = target["name"], target["type"]
        if self.config.browser_read_only and _read_only_blocks(name, element_type):
            raise RuntimeError(f"read_only_action_blocked:{name or element_type}")
        if not _is_local_page(page) and (
            _IRREVERSIBLE_ACTION.search(name) or (element_type == "submit" and not _read_only_submit(name))
        ):
            # 좌표 누르기에는 승인 문(confirmed)이 없다 — 되돌릴 수 없는 것은 ref 길로만 간다.
            raise RuntimeError(
                f"irreversible_click_needs_approval:{name or element_type}"
                " — 되돌릴 수 없는 동작은 좌표로 누르지 않는다. 사용자에게 화면에서 직접 누르게 하거나 승인 길을 써라."
            )
        return x, y, target

    def _click_at(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """좌표를 누른다 — 목록이 못 읽는 화면 전용(`_why_empty` 의 unreadable_structure)."""
        x, y, target = self._checked_point(page, arguments)
        before = str(getattr(page, "url", "") or "")
        page.mouse.click(x, y)
        try:
            page.wait_for_timeout(700)
        except Exception:
            pass
        after = str(getattr(page, "url", "") or "")
        if after != before:
            self._mark_visited(after)
        self._note_trait(page, "needs_coordinates", url=before)
        return self._evidence("clicked_at", x=x, y=y, target=target, navigated=after != before)

    def _local_test_secret_ok(self, page: Any, value: str) -> bool:
        """이 PC 개발 주소의 시험 앱에, 맡긴 글에 글자 그대로 적힌 값인가(human_gate.allows_local_test_secret)."""
        return allows_local_test_secret(
            str(getattr(page, "url", "") or ""), str(getattr(self, "local_test_prompt", "") or ""), value
        )

    def _type_at(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """좌표의 입력칸을 눌러 글자를 친다. 비밀번호 칸은 거부한다(자격 증명은 사람이 넣는다)."""
        text = str(arguments.get("text") or "")
        if not text:
            raise ValueError("text_required")
        x, y, target = self._checked_point(page, arguments)
        password_like = target["type"] == "password" or "password" in target["name"].lower() or "비밀번호" in target["name"]
        if password_like and not self._local_test_secret_ok(page, text):
            raise RuntimeError("password_field_refused — 비밀번호는 사람이 직접 넣는다.")
        submit = bool(arguments.get("submit"))
        if submit and self.config.browser_read_only:
            raise RuntimeError("read_only_enter_blocked")
        page.mouse.click(x, y)
        page.keyboard.type(text, delay=20)
        # ★ 2026-09-29 밤 한방 도전 W1: 가계부 예산 칸에 좌표로 **14번** 쳤다. 이 도구는 친 뒤 확인 없이 「성공」을 돌려줬고,
        #   모델은 화면을 다시 찍어 빈 칸을 보고 또 쳤다 — 762초 판의 약 8분이 여기였다(대표: 「느린 건 거의 클릭이 안 돼서」).
        #   단계를 도구가 밟는다: ① 사람처럼 누르고 친다 → ② 값이 **분명히 비었으면** 그 자리 입력칸에 값을 직접 넣고
        #   입력 이벤트를 쏜다 → ③ 그래도 안 되면 정직하게 실패(같은 수 반복 금지 · ref 로 채우기 · 사람에게).
        #   값을 **읽을 수 없는** 칸(닫힌 섀도 등)은 「모름」이라 건드리지 않는다 — 거기서는 ①이 이미 된다(시험).
        method = "keyboard"
        landed = self._typed_value_landed(page, x, y, text)
        if landed is False:
            try:
                direct = page.evaluate(_FILL_AT_POINT_JS, [x, y, text]) or {}
            except Exception as exc:  # noqa: BLE001
                direct = {"ok": False, "why": f"evaluate_failed: {exc}"[:160]}
            if direct.get("ok") and _typed_matches(text, str(direct.get("value") or "")):
                method = "direct_fill"
            else:
                raise RuntimeError(
                    "type_at_not_applied — 좌표로 누르고 친 글자도, 그 자리 입력칸에 값을 직접 넣은 것도 칸에 남지 않았다"
                    f"({direct.get('why') or 'value_rejected'}). 같은 좌표·다른 좌표로 다시 치지 마라. "
                    "browser_snapshot 으로 그 칸의 ref 를 찾아 browser_fill 로 채우고, 그것도 안 되면 사용자에게 "
                    "「이 칸은 자동 입력이 안 됩니다 — 직접 넣어 주시겠어요?」라고 넘겨라."
                )
        if submit:
            page.keyboard.press("Enter")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
        return self._evidence("typed_at", x=x, y=y, target=target, submitted=submit, chars=len(text), method=method,
                              value_verified=landed is not None or method == "direct_fill")

    @staticmethod
    def _typed_value_landed(page: Any, x: float, y: float, text: str) -> bool | None:
        """친 글자가 칸에 남았나. 읽을 수 없으면 None — 모르는 것을 실패로 치지 않는다."""
        try:
            value = page.evaluate(_FIELD_VALUE_AT_POINT_JS, [x, y])
        except Exception:
            return None
        if value is None:
            return None
        return _typed_matches(text, str(value))

    def _structured_data(self, page: Any) -> dict[str, Any]:
        """사이트가 박아 둔 구조화 데이터(JSON-LD·메타) 요약. 못 읽으면 빈 dict — 읽기를 막지 않는다."""
        try:
            return _structured.summarize(page.evaluate(_STRUCTURED_DATA_JS))
        except Exception:
            return {}

    def _note_trait(self, page: Any, trait: str, detail: str = "", *, url: str = "") -> None:
        """도구가 **본** 사이트 성질을 센다. 실패해도 일을 막지 않는다."""
        try:
            traits = getattr(self, "_site_traits", None)
            if traits is not None:
                traits.record(url or str(getattr(page, "url", "") or ""), trait, detail)
        except Exception:
            pass

    def _with_site_traits(self, page: Any, result: dict[str, Any]) -> dict[str, Any]:
        """이 사이트에서 전에 본 성질을 결과에 한 줄로 싣는다 — 헤매기 전에."""
        try:
            traits = getattr(self, "_site_traits", None)
            url = str(getattr(page, "url", "") or "")
            if traits is None or not url or not isinstance(result, dict):
                return result
            found = traits.traits_for(url)
            if not found:
                return result
            note = traits.note_for(url)
            return {**result, "site_traits": found,
                    "instruction": (note + " " + str(result.get("instruction") or "")).strip()}
        except Exception:
            return result

    #: 크롬 번역이 켜진 페이지 — 크롬이 `<html>` 에 `translated-ltr`/`translated-rtl` 을 단다.
    _MACHINE_TRANSLATED_JS = (
        "() => { const c = document.documentElement.classList;"
        " return c.contains('translated-ltr') || c.contains('translated-rtl'); }"
    )
    _MACHINE_TRANSLATED_NOTE = (
        "machine_translated — 이 페이지는 크롬이 자동 번역한 화면이다. 고유명사·제품명·회사명이 번역체로 바뀌어 있을 수 있다"
        "(실측: OpenAI→「오픈아이」, Plans→「계략」). 이름·숫자는 structured_data 나 원문 표기로 확인하고, 번역된 이름을 그대로 답에 쓰지 마라."
    )

    def _page_is_machine_translated(self, page: Any) -> bool:
        try:
            return bool(page.evaluate(self._MACHINE_TRANSLATED_JS))
        except Exception:
            return False

    def _note_read_route(self, page: Any, result: dict[str, Any]) -> None:
        """본문이 **읽힌** 주소 모양과 **비어 온** 주소 모양을 사이트별로 남긴다(`site_traits` readable_url/empty_url)."""
        try:
            count = int(result.get("char_count") or 0)
        except (TypeError, ValueError, AttributeError):
            return
        pattern = _read_route_pattern(str(getattr(page, "url", "") or ""))
        if not pattern:
            return
        if count >= 800:
            # 검색어만 바뀌는 목록 주소(`?schStr=AI`)가 다섯 칸을 밀어내지 않게 — 번호가 든 상세 모양이나 꼬리표 없는 주소만.
            # 「page=」가 든 주소는 목록이다 — 상세를 열 길이 아니다.
            if ("{n}" in pattern or "?" not in pattern) and not re.search(r"[?&]page=", pattern):
                self._note_trait(page, "readable_url", pattern)
        elif count < 200:
            self._note_trait(page, "empty_url", pattern)

    def _attach_structured(self, page: Any, result: dict[str, Any]) -> dict[str, Any]:
        if isinstance(result, dict):
            self._note_read_route(page, result)
        if isinstance(result, dict) and result.get("shadow_dom"):
            self._note_trait(page, "shadow_dom")
        # ★ 2026-09-18: 영어 페이지가 번역체로 읽혔다. 온텔릭 프로필엔 번역 설정이 없었고 **사람의 크롬**(Default)에
        #   「영어는 항상 한국어로」가 켜져 있었다 — 그 크롬에 붙은 판이다. 사람의 설정은 안 바꾸고, 번역된 화면이면 알린다.
        if isinstance(result, dict) and self._page_is_machine_translated(page):
            result = {**result, "machine_translated": True,
                      "instruction": (self._MACHINE_TRANSLATED_NOTE + " " + str(result.get("instruction") or "")).strip()}
        summary = self._structured_data(page)
        if not summary:
            return result
        for item in summary.get("items") or []:
            self._note_trait(page, "structured_data", str(item.get("type") or ""))
        note = _structured.note_for(summary)
        merged = {**result, "structured_data": summary}
        # 게시일은 **한 칸으로** 싣는다 — 장부에 남아야 에이전트가 「오늘을 물었는데 12일 전 글」을 셀 수 있다.
        published = _structured.published_date(summary)
        if published:
            merged["published"] = published
        if note:
            merged["instruction"] = (note + " " + str(result.get("instruction") or "")).strip()
        return merged

    def _extract_with_data(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """본문 + 구조화 데이터. 에이전트가 부르는 `browser_extract` 는 이 길로 온다(2026-09-18)."""
        return self._attach_listing(page, self._attach_post_stats(page, self._attach_structured(page, self._extract(page, arguments))))

    def _read_with_data(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._attach_listing(page, self._attach_post_stats(page, self._attach_structured(page, self._read(page, arguments))))

    def _attach_listing(self, page: Any, result: Any) -> Any:
        """레딧 글 **목록**이면 글마다 제목·댓글 수·추천 수·지난 시간·**진짜 글 주소**를 본문 맨 앞에 붙인다(`reddit_listing_json_url`).

        못 받으면 아무것도 안 붙인다 — 모르면 안 고친다. 숫자는 레딧이 준 값 그대로고, 「N시간 전」만 이 PC 시각으로 계산한다.
        """
        if not isinstance(result, dict):
            return result
        json_url = reddit_listing_json_url(str(result.get("url") or getattr(page, "url", "") or ""))
        if not json_url:
            return result
        try:
            response = page.context.request.get(json_url, timeout=6000, max_redirects=3)
            items = reddit_listing_items(response.json()) if response.ok else []
        except Exception:
            items = []
        if not items:
            return result
        lines = [
            f"{index}. 「{item['title']}」 · 댓글 {item['num_comments']} · 추천 {item['score']}"
            + (f" · {item['age']} (올린 시각 {item['created_local']})" if item.get("age") else "")
            + (" · 고정 글" if item.get("pinned") else "")
            + f" · {item['url']}"
            for index, item in enumerate(items, 1)
        ]
        head = (
            f"[레딧 글 목록 {len(items)}개] 도구가 같은 브라우저로 {json_url} 에서 읽은 값(화면 추출에는 숫자가 안 잡힌다). "
            "글을 열 때는 여기 적힌 주소를 그대로 써라 — 글 번호를 짐작해 주소를 만들지 마라."
        )
        updated = dict(result)
        updated["listing"] = items
        block = head + "\n" + "\n".join(lines)
        if isinstance(updated.get("text"), str):
            updated["text"] = block + "\n\n" + updated["text"]
        else:
            updated["listing_note"] = block
        return updated

    def _attach_post_stats(self, page: Any, result: Any) -> Any:
        """레딧 글이면 점수·댓글 수를 **도구가** 같은 브라우저 세션으로 `.json` 에서 읽어 본문 맨 앞에 붙인다.

        ★ 2026-10-03 「내 레딧 글들 추천·댓글 수」 판(155bd3e1): 투표 숫자가 화면 구성 요소 안에 있어 본문 추출·화면 읽기·
          요소 찾기·캡처가 다 놓쳤고, 모델이 다섯 걸음 만에 스스로 `.json` 을 떠올렸다. 결정론으로 박을 수 있는 것은 코드로(사고 R).
          못 받으면 아무것도 안 붙인다 — 모르면 안 고친다.
        """
        if not isinstance(result, dict):
            return result
        json_url = reddit_post_json_url(str(result.get("url") or getattr(page, "url", "") or ""))
        if not json_url:
            return result
        try:
            response = page.context.request.get(json_url, timeout=5000, max_redirects=3)
            payload = response.json() if response.ok else None
            stats = reddit_post_stats(payload) if payload is not None else {}
            comments, hidden = reddit_post_comments(payload) if payload is not None else ([], 0)
        except Exception:
            stats, comments, hidden = {}, [], 0
        if not stats:
            return result
        head = " · ".join(part for part in (
            f"제목 「{stats['title']}」" if stats.get("title") else "",
            stats.get("subreddit", ""),
            (f"올린 시각 {stats['created_utc']} UTC (이 PC 시각 {stats['created_local']})" if stats.get("created_local")
             else f"올린 시각 {stats['created_utc']} UTC") if stats.get("created_utc") else "",
            f"조회수 {stats['view_count']}" if stats.get("view_count") is not None else "",
        ) if part)
        line = (f"[레딧 글 수치] 점수(추천) {stats['score']} · 댓글 {stats['num_comments']}"
                + (f" · 추천 비율 {stats['upvote_ratio']}" if stats.get("upvote_ratio") is not None else "")
                + (f" · {head}" if head else "")
                + f" — 도구가 같은 브라우저로 {json_url} 에서 읽은 값(화면 추출에는 안 잡힌다)")
        # ★ 댓글마다 작성자·요지(2026-10-03 22시 예약 판): 원문 JSON 은 2만 자에서 잘려 「댓글 전부」를 못 읽었다.
        if comments:
            line += (f"\n[레딧 댓글 {len(comments)}개" + (f" · 접혀 있어 안 읽은 댓글 {hidden}개" if hidden else "") + "]\n"
                     + "\n".join(f"{'  ' * min(c['depth'], 4)}- u/{c['author']} (점수 {c['score']}): {c['gist']}" for c in comments))
        updated = dict(result)
        updated["post_stats"] = stats
        if comments:
            updated["post_comments"] = comments
        if isinstance(updated.get("text"), str):
            updated["text"] = line + "\n" + updated["text"]
        else:
            updated["post_stats_note"] = line
        return updated

    def _deep_text(self, page: Any, max_chars: int) -> str:
        """섀도 DOM 안까지 그려지는 글. 섀도 루트가 없는 페이지면 빈 값(비용도 거의 없다)."""
        try:
            found = page.evaluate(_DEEP_TEXT_JS, int(max_chars) + 2000)
        except Exception:
            return ""
        if not isinstance(found, dict):
            return ""
        return _clean(found.get("text"), 10_000_000) if found.get("text") else ""

    def _ref_locator(self, page: Any, ref: str) -> Any:
        """Resolve a snapshot ref in whichever frame it was stamped in.

        Searching every frame rather than remembering which one is deliberate:
        a frame list is reordered by lazy loading, so a stored index goes stale
        while the attribute on the element itself does not.
        """
        # ★ 번호는 **다섯 자리까지** 받는다 (2026-10-07 폼 벤치). 세 자리(j999)까지만 받던 동안, 요소가 1,000개를 넘는
        #   화면에서 browser_find 가 돌려준 번호(j1063)로 채우기·누르기를 하면 네 번 다 `invalid_element_ref` 였다 —
        #   찾기는 맞게 찾았는데 그 번호를 받는 쪽이 형식에서 떨어뜨렸다(함수 안 상수 — 사고 Q 와 같은 모양).
        if not re.fullmatch(r"j\d{1,5}", ref):
            raise ValueError("invalid_element_ref")
        for frame in self._frames_of(page):
            try:
                locator = frame.locator(f'[data-jarvis-ref="{ref}"]').first
                if int(locator.count()) > 0 and locator.is_visible():
                    return locator
            except Exception:
                continue
        recovered = self._recover_ref(page, ref)
        if recovered is not None:
            return recovered
        why = f" ({self._recover_why})" if self._recover_why else ""
        raise RuntimeError(f"stale_element_ref:take_a_new_snapshot{why}")

    def _confirmed_click_proof(
        self, arguments: dict[str, Any], *, screenshot: bool
    ) -> dict[str, Any]:
        page = self._current_page()
        ref = str(arguments.get("ref") or "")
        locator = self._ref_locator(page, ref)
        target = locator.evaluate(
            """el => ({
              tag: (el.tagName || '').toLowerCase(),
              type: el.getAttribute('type') || '',
              role: el.getAttribute('role') || '',
              name: (el.getAttribute('aria-label') || el.innerText || el.value ||
                     el.getAttribute('title') || '').trim().slice(0, 300),
              aria_pressed: el.getAttribute('aria-pressed'),
              aria_checked: el.getAttribute('aria-checked'),
              href: el.getAttribute('href') || ''
            })"""
        )
        url = str(getattr(page, "url", "") or "").split("#", 1)[0]
        material = {"url": url, "ref": ref, "target": dict(target or {})}
        fingerprint = hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        proof = {**material, "fingerprint": fingerprint}
        if screenshot:
            try:
                shot = self._screenshot(
                    page, {"label": "l3_before", "ref": ref, "pad": 72}
                )
                proof["screenshot"] = str(shot.get("path") or "")
            except Exception as exc:
                # PNG 보조 근거가 실패해도 DOM 지문까지 버리지는 않는다. 지문이 없으면
                # 실행을 막지만, 지문이 있고 PNG만 없으면 승인 화면 자체가 주 근거다.
                proof["screenshot_error"] = _clean(exc, 200)
        return proof

    def _confirmed_click_after(
        self, arguments: dict[str, Any], result: Any
    ) -> dict[str, Any]:
        page = self._current_page()
        shot = self._screenshot(page, {"label": "l3_after"})
        return {
            "url": str(getattr(page, "url", "") or "")[:1000],
            "screenshot": str(shot.get("path") or ""),
        }

    def _recover_ref(self, page: Any, ref: str) -> Any | None:
        """죽은 ref 를 **이름으로** 되살린다. 못 되살리면 None.

        ★ 2026-08-11 위시켓 실측. 목록에서 하나 고르면 SPA 는 그 자리를 통째로
        다시 그린다 — 노드가 바뀌니 붙여 둔 번호표가 같이 사라진다. 사람 눈에는
        화면이 그대로인데 자비스만 "없다"며 손을 놓는다. 숙련도를 고른 직후 경험
        칸이 정확히 그랬다.

        **번호로 다시 찾으면 안 된다.** 다시 찍으면 번호는 DOM 순서대로 새로
        매겨지므로, 같은 번호가 다른 것을 가리킬 수 있다(그걸 누르면 조용히 엉뚱한
        일이 벌어진다). 그래서 번호가 아니라 **그때 그 칸의 이름**으로 찾는다.
        사람도 "104번 칸"이 아니라 "경험 칸"으로 기억한다.

        이름이 안 맞으면 **되살리지 않는다.** 비슷한 것을 골라 주는 편이 친절해
        보이지만, 그건 사람이 모르는 채로 다른 것을 누르게 만드는 길이다.
        """
        # ★ 실패하면 **왜** 실패했는지 남긴다. 이유 없이 None 만 돌려주니 추측으로
        # 두 번 고쳤고 두 번 다 빗나갔다(2026-08-11). 셋 중 어느 것인지만 알면
        # 한 번에 끝나는 문제였다.
        self._recover_why = ""
        remembered = dict(self._ref_memory.get(ref) or {})
        if not remembered.get("name"):
            self._recover_why = f"기억에 {ref} 가 없다 (기억 {len(self._ref_memory)}개)"
            return None
        # 다시 찍으면 기억도 새로 덮인다. 쓰기 전에 떠 놓는다.
        want_name = str(remembered.get("name") or "")
        want_tag = str(remembered.get("tag") or "")
        seen: list[str] = []
        found_but_hidden = 0
        for item in self._snapshot_elements(page):
            name = str(item.get("name") or "")
            # 이름이 **자라는** 경우가 있다. 칸을 채우면 그 줄의 글이 늘어나고,
            # 이름을 그 줄에서 빌려 오므로 `경험 *` 이 `경험 * 1년 미만` 이 된다.
            # 정확일치만 보면 방금 그 칸을 못 알아본다(위시켓 실측). 한쪽이 다른
            # 쪽을 품고 있으면 같은 것으로 본다 — 다만 **태그가 같을 때만**이고,
            # 짧은 쪽이 너무 짧으면(두 글자 미만) 아무 데나 걸리므로 안 쓴다.
            if want_tag and str(item.get("tag") or "") != want_tag:
                continue
            if name != want_name:
                if len(want_name) < 2:
                    continue
                if want_name not in name and name not in want_name:
                    continue
            fresh = str(item.get("ref") or "")
            for index, frame in enumerate(self._frames_of(page)):
                try:
                    locator = frame.locator(f'[data-jarvis-ref="{fresh}"]').first
                    count = int(locator.count())
                    if count == 0:
                        seen.append(f"{fresh}@f{index}:요소없음")
                        continue
                    if not locator.is_visible():
                        seen.append(f"{fresh}@f{index}:안보임")
                        found_but_hidden += 1
                        continue
                    return locator
                except Exception as exc:
                    seen.append(f"{fresh}@f{index}:예외 {str(exc)[:40]}")
                    continue
        if seen:
            self._recover_why = f"이름은 맞았다 → {'; '.join(seen[:4])}"
        else:
            self._recover_why = (
                f"‘{want_name[:30]}’({want_tag}) 와 맞는 이름이 지금 화면에 없다"
            )
        return None

    def _hover(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """마우스를 **올리기만** 한다. 그리고 **무엇이 나타났는지** 알려 준다.

        ## 없던 동작이다 (2026-08-13)

        사용자가 쿠팡 카테고리를 보다 짚으셨다 — "누르지 말고 가져다 대기만 하면
        스르륵 나온다". 코드를 뒤져 보니 `hover`·`mouseover` 가 **0 건**이었다.
        자비스는 클릭만 알았다.

        국내 쇼핑·포털 내비게이션은 거의 전부 이 모양이다: 상위 항목은 **누르는
        것이 아니라 올려놓는 것**이고, 하위 목록은 올려놓기 전까지 DOM 에 아예 없거나
        `display:none` 이다. 그래서 스냅샷에 **상위 몇 개만** 보이고, 자비스는 그
        상위 항목을 눌러 엉뚱한 기획전으로 갔다(실측: rank 1 이 "가전디지털 기획전").

        ## 이 도구의 값은 '올렸다'가 아니라 '나타났다'이다

        올려 놓고 아무것도 안 알려 주면 모델은 다시 스냅샷을 떠야 하고, 그 사이
        메뉴가 닫힌다. 그래서 **올린 직후 화면을 떠서 새로 생긴 것만** 돌려준다.
        조작 가능한 요소가 몇 개에서 몇 개로 늘었는지도 같이 준다 — 안 늘었으면
        그건 호버로 열리는 메뉴가 아니라는 뜻이고, 그때는 눌러야 한다.

        ## 열어 둔 채로 다음 수를 두려면

        Playwright 의 마우스는 **순간이동**한다. 그래서 사람처럼 "메뉴를 벗어나면
        닫히는" 함정은 대개 안 밟는다 — 다음 클릭이 패널 안쪽 좌표로 바로 간다.
        다만 트리거에서 `mouseleave` 가 먼저 도는 구현이 있어서, 열린 목록을
        누를 때는 **바로 다음 걸음에** 눌러야 한다(사이에 스냅샷을 끼우지 마라).
        """
        ref = str(arguments.get("ref") or "")
        locator = self._ref_locator(page, ref)
        name = _clean(
            locator.get_attribute("aria-label")
            or locator.get_attribute("title")
            or locator.inner_text(timeout=1000),
            200,
        )
        before = self._hover_visible_labels(page)
        self._show_visual(page, f"‘{name or ref}’ 위에 올림", locator=locator)
        try:
            locator.hover(timeout=self.config.browser_action_timeout_sec * 1000)
        except Exception as exc:
            raise RuntimeError(f"hover_failed:{name or ref} — {str(exc)[:160]}") from exc
        # 펼쳐지는 데 시간이 걸린다(대개 CSS 전환 150~300ms).
        page.wait_for_timeout(_HOVER_SETTLE_MS)
        after = self._hover_visible_labels(page)
        appeared = [label for label in after if label not in before][:40]
        result = self._evidence(
            "hovered",
            ref=ref,
            element={"name": name},
            visible_before=len(before),
            visible_after=len(after),
            appeared=appeared,
        )
        if appeared:
            result["instruction"] = (
                f"올려놓으니 {len(appeared)}개가 나타났다. **바로 다음 걸음에** "
                "browser_snapshot 으로 번호를 받아 누르거나, 이미 아는 이름이면 "
                "browser_click 으로 눌러라 — 사이에 다른 일을 하면 메뉴가 닫힌다."
            )
        else:
            # ★ 같은 자리를 되풀이하면 **다른 손**을 알려 준다 (2026-08-23).
            #
            # 그 전에는 여기서 안내가 끊겼다 — "눌러 봐라"까지만 말하고, 눌러도
            # 아무 일이 없으면 그다음 할 말이 없었다. 그래서 자비스는 실패한 그
            # ref 로 계속 돌아왔다.
            #
            # 실측(2026-08-23, 쿠팡 가전디지털 카테고리):
            #
            #      5. hover(j10) → 아무것도 안 나타남
            #      6. click(j10) → 눌렀는데 URL 그대로
            #      8. hover(j19) → 같은 실패      9. click(j19) → 같은 실패
            #     15. hover(j10) → ★ 아까 죽은 그 자리를 다시
            #
            # 퀀3.8 은 16걸음·173초를 쓰고 출처 2개로 끝났고, 젬마4-26B 도 이
            # 판에서만 호버가 안 열렸다. **모델 문제가 아니라 막다른 길에서
            # 나가는 문을 아무도 안 알려 준 것**이다.
            #
            # 그리고 손은 이미 다 있다. 실측한 도구 사용 분포에서 키보드는
            # 5~9%였고 `browser_press`·`browser_fill`·`browser_select_option` 은
            # **0회**였다 — 있는데 안 쓰는 것이지 없는 게 아니다.
            fingerprint = (str(getattr(page, "url", "") or "")[:120], name or ref)
            dead = getattr(self, "_dead_hovers", None)
            if dead is None:
                dead = self._dead_hovers = {}
            dead[fingerprint] = dead.get(fingerprint, 0) + 1
            if dead[fingerprint] < 2:
                result["instruction"] = (
                    "올려놨는데 새로 나타난 것이 없다. 호버로 열리는 메뉴가 아니다 — "
                    "browser_click 으로 눌러 봐라."
                )
            else:
                result["instruction"] = (
                    f"★ 이 자리는 {dead[fingerprint]}번째 헛손질이다. 올려도 눌러도 "
                    "아무것도 안 열린다. **같은 곳을 또 건드리지 말고 다른 손을 써라:**\n"
                    "  ① browser_site_search 로 그 낱말을 이 사이트 검색칸에 쳐 넣어라\n"
                    "  ② browser_find 로 '…바로가기' 같은 링크를 찾아 그 주소를 "
                    "browser_open 해라\n"
                    "  ③ 칸에 값을 넣어야 하면 browser_fill, 키를 보내야 하면 "
                    "browser_press(Enter/Tab/Escape) 를 써라"
                )
        return result

    @staticmethod
    def _hover_visible_labels(page: Any) -> set[str]:
        """지금 **화면에 보이는** 조작 가능 요소들의 이름표.

        개수만 세지 않고 이름을 모으는 이유: 호버 메뉴는 열리면서 다른 것을 가리기도
        해서 개수만으로는 늘었는지 줄었는지가 뒤섞인다. 무엇이 **새로 생겼는지**를
        말해 줘야 다음 수가 나온다.
        """
        try:
            found = page.evaluate(
                _deep_js("""
                (selector) => {
                  const out = [];
                  for (const el of document.querySelectorAll(selector)) {
                    if (!el.getClientRects().length) continue;
                    const st = getComputedStyle(el);
                    if (st.visibility === "hidden" || parseFloat(st.opacity) === 0) continue;
                    const text = (el.getAttribute("aria-label") || el.innerText || "")
                      .replace(/\\s+/g, " ").trim();
                    if (text) out.push(text.slice(0, 60));
                  }
                  return out;
                }
                """),
                _INTERACTIVE,
            )
        except Exception:
            return set()
        return set(found or [])

    def _steer_consent_click(self, page: Any, locator: Any, name: str) -> dict[str, Any] | None:
        """「모두 허용」이 쿠키·개인정보 동의 창 안이면 거부·필수만(없으면 닫기)을 대신 누른다. 동의 창이 아니면 None(그대로 누른다)."""
        try:
            found = locator.evaluate(_CONSENT_STEER_JS)
        except Exception:
            return None
        if not isinstance(found, dict) or not found.get("consent"):
            return None
        kind = str(found.get("kind") or "none")
        label = _clean(str(found.get("label") or ""), 60)
        if kind == "none":
            return self._evidence(
                "not_clicked", consent_steered="none",
                instruction=(
                    f"쿠키·동의 창의 「{name}」은 사용자의 동의라 대신 누르지 않는다. 거부·닫기 버튼이 없어 그대로 뒀다 — "
                    "본문은 browser_read/browser_extract 로 읽고, 창이 내용을 가려 일을 못 하면 사람에게 넘겨라."
                ),
            )
        try:
            page.locator('[data-jarvis-consent="1"]').first.click(timeout=5000)
        finally:
            try:
                page.evaluate("() => document.querySelectorAll('[data-jarvis-consent]').forEach(e => e.removeAttribute('data-jarvis-consent'))")
            except Exception:
                pass
        page.wait_for_timeout(300)
        return self._evidence(
            "clicked", consent_steered=kind, pressed=label,
            instruction=(
                f"쿠키·동의 창에서 「{name}」 대신 「{label}」을 눌렀다 — 사용자 대신 추가 동의를 하지 않는다. 하던 일을 이어서 하라."
            ),
        )

    def _click(self, page: Any, arguments: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        """★ `approved` 는 **인자가 아니라 매개변수**다.

        예전에는 `arguments["_approved"]` 로 넘겼다. 그런데 `_execute` 도
        `ToolGateway` 도 인자를 그대로 흘려보내므로, 모델이 L1 인 `browser_click` 에
        `{"_approved": true}` 를 얹으면 **되돌릴 수 없는 동작의 L2 승인을 그냥
        건너뛸 수 있었다.** 결제·삭제·발행이 그 문 뒤에 있다.

        승인은 호출자가 주장하는 값이 아니라 **어느 문으로 들어왔는가**여야 한다.
        `browser_click_confirmed`(L2) 만 이 매개변수를 켠다.
        """
        ref = str(arguments.get("ref") or "")
        locator = self._ref_locator(page, ref)
        name = _clean(
            locator.get_attribute("aria-label")
            or locator.get_attribute("title")
            or locator.inner_text(timeout=1000),
            300,
        )
        tag = _clean(locator.evaluate("el => el.tagName.toLowerCase()"), 20)
        element_type = _clean(locator.get_attribute("type"), 30)
        if self.config.browser_read_only and _read_only_blocks(name, element_type):
            raise RuntimeError(f"read_only_action_blocked:{name or element_type}")
        # 읽기 전용을 꺼도 이건 안 열린다. 돈이 나가거나 지워지는 일은 스위치가 아니라
        # 사람이 화면에서 승인해야 한다 — browser_click_confirmed(L2)로만 눌린다.
        # 글자가 없는 <input type="submit">도 제출이다. 공식 Selenium 폼에서
        # inner_text가 빈 문자열이라 이름 기반 위험 판정을 통과했고, L0 click이
        # 승인 없이 실제 제출까지 해 버렸다. 요소 타입은 모델의 표현과 무관한
        # 구조적 사실이므로 무조건 승인 경로로 보낸다.
        if not approved and not _is_local_page(page) and (
            _IRREVERSIBLE_ACTION.search(name)
            or (element_type == "submit" and not _read_only_submit(name))
        ):
            raise RuntimeError(
                f"irreversible_click_needs_approval:{name or element_type}"
                " — 되돌릴 수 없는 동작입니다. browser_click_confirmed 로 요청하면"
                " 화면 승인 뒤에 눌립니다."
            )
        # ★ 쿠키·동의 창의 「모두 허용」은 대신 누르지 않는다 (2026-10-02 공개 전 필수 ②).
        #   가격 비교 판에서 모델이 Perplexity 쿠키 창의 「모두 허용」을 눌렀다 — 대표의 **실제 크롬**에서 광고·분석 쿠키까지
        #   동의한 것이다. 안내문은 안 먹으니(사고 R) 도구가 같은 창의 거부·필수만을 대신 누르고, 없으면 닫기, 그것도 없으면 안 누른다.
        #   사람이 화면에서 승인한 클릭(approved)은 그 사람의 선택이라 손대지 않는다.
        if not approved and _CONSENT_ACCEPT.search(name or ""):
            steered = self._steer_consent_click(page, locator, name)
            if steered is not None:
                return steered
        # ★ **채운 칸이 그 사이 되돌아갔나** (2026-10-06 r/AI_Agents 댓글 · Mind2Web WebMD 위치).
        #   자동완성 칸은 후보를 안 고르고 포커스가 떠나면 친 글을 지우거나 옛 값으로 되돌린다. 채운 직후의 되읽기
        #   (`_fill`)는 그 뒤를 못 본다 — 모델은 채웠다고 믿고 검색을 누르고, 빈 칸으로 검색이 나갔다.
        #   누르기 직전에 이 화면에서 채운 칸을 다시 읽어, 달라졌으면 **누르지 않고** 그 사실과 지금 값을 준다.
        #   같은 상태로 다시 누르면 그때는 누른다(한 번만 붙잡는다 — 일부러 비운 칸일 수 있다).
        if not approved:
            # 칸에 포커스가 남아 있으면 되돌림은 **이 누르기 때문에** 일어난다 — 누른 뒤에는 늦다. 먼저 칸을 떠나 본다.
            self._leave_filled_field(page, locator, tag)
            drifted = self._fields_changed_since_filled(page)
            if drifted:
                names = ", ".join(f"「{item['field']}」" for item in drifted[:3])
                said = self._said_since_filled(page, skip=tuple(str(item.get("now") or "") for item in drifted))
                return self._evidence(
                    "not_clicked", ref=ref, element={"name": name, "tag": tag}, fields_changed=drifted,
                    **({"site_said": said} if said else {}),
                    instruction=(
                        f"누르지 않았다 — 앞에서 채운 칸 {names}의 값이 그 사이 달라졌다(사이트가 지우거나 되돌렸다). "
                        "fields_changed 의 now 가 지금 칸에 남은 값이다. "
                        + ("칸을 채운 뒤 화면에 새로 나온 글이 site_said 다 — 사이트가 받는 모양·까닭을 말하고 있으면 "
                           "**그대로 맞춰** 다시 채워라(같은 값을 같은 모양으로 또 넣지 마라). " if said else "")
                        + "목록에서 골라야 하는 칸이면 browser_pick_suggestion 으로 다시 채우고, "
                        "그대로 두어도 되는 칸이면 같은 것을 다시 눌러라."
                    ),
                )
        # An expectation must be sampled *before* the click, or "did it change"
        # has nothing to compare against.
        expect = dict(arguments.get("expect") or {})
        # ★ 되돌릴 수 없는 클릭은 **예측이 없어도** 지문을 뜬다(2026-08-08).
        #
        # 여기가 비어 있던 자리다. 되돌릴 수 없는 동작은 사람 승인은 받는데 증거는
        # 안 받았다 — `expect` 없이 부르면 아무 검증 없이 `clicked` 를 돌려줬다.
        # 기록된 사고가 거의 전부 이 모양이다: 빈 공간에 세 번 클릭하고 세 번 다
        # 성공 보고(2026-08-05), `any(step.ok)` 집계가 무의미했던 건.
        #
        # 무동작을 잡는 데는 셀렉터도 예측도 필요 없다 — 화면이 하나도 안 바뀌었다는
        # 사실만으로 충분하고, 그건 `_page_signals` 가 이미 잰다.
        watch = bool(expect) or approved
        # ★ 기대 없이 누른 평범한 클릭도 **화면 지문은 뜬다** (2026-10-07). Gemma 가 같은 단추를 세 판에 걸쳐 네 번
        #   눌렀고 도구는 매번 `clicked` 만 돌려줬다 — 화면은 그대로였다. 무엇이 일어났는지 모르는 모델은 같은 스냅샷을
        #   여섯 번 뜨다가 「진입할까요?」로 되물었다. 판정은 안 한다(포커스만 옮기는 클릭도 있다) — 사실만 준다.
        plain = not watch
        before = self._observe(page, expect) if expect else None
        # 기대와 별개로 화면 전체의 지문을 떠 둔다. 기대가 빗나갔을 때 "안 눌렸다"와
        # "눌렸는데 다른 일이 일어났다"를 가르는 근거가 이것뿐이다 — 누른 뒤에는
        # 이전 화면을 다시 잴 수 없다.
        signals_before = self._page_signals(page) if (watch or plain) else None
        # 누르기 전의 창 목록. 누른 뒤에 늘어났으면 그게 일이 옮겨 간 곳이다.
        windows_before = list(self._context.pages) if self._context else []
        self._show_visual(page, f"‘{name or ref}’ 선택", locator=locator)
        page.wait_for_timeout(220)
        # Recovering from an interception is not a Naver concern -- cookie
        # banners, consent sheets and "계속하려면 확인" dialogs do the same thing
        # on every site, and a bare click timeout there is indistinguishable
        # from a wrong ref. Same rules as the editor path: only a negative
        # button is ever pressed automatically, and exactly one retry.
        # 누르기 전의 **토글 상태**. 표준이 정한 것만 본다(아래 `_toggle_state` 참고).
        toggle_before = self._toggle_state(locator)
        # ★ 체크 칸·라디오는 **그 칸의 체크 상태**가 눌린 효과다 (2026-10-07 폼 벤치 넷째 판). 글도 주소도 요소 수도 안 바뀐다 —
        #   그래서 라디오를 맞게 누른 판에 「화면에서 어떤 변화도 찾지 못했습니다. 무엇이 막고 있는지 확인하라」가 붙었다.
        self.__dict__.pop("_auto_closed", None)
        native_check = tag == "input" and element_type.lower() in {"checkbox", "radio"}
        checked_before = self._is_checked(locator) if native_check else None
        try:
            self._guarded_click(locator, what=name or ref, page=page, prefix="browser")
        except Exception as exc:
            # ★ 누르기가 막힌 **이동용 javascript: 링크**는 그 함수로 따라간다 (2026-10-02 K-Startup 4차 판 70a447c4).
            #   목록의 공고 `<a href="javascript:go_view(176076)">` 를 눌렀더니 겹친 요소에 막혀 8초 시간 초과 — 새벽에 넣은
            #   javascript 링크 따라가기는 browser_open 에만 있어서 클릭 길에서는 안 돌았다. 이동처럼 보이는 함수만
            #   (`_follow_js_link` 의 규칙 그대로) 대신 부르고, 아니면 원래 실패를 그대로 올린다.
            href = ""
            if tag == "a" and not approved:
                try:
                    href = str(locator.get_attribute("href", timeout=1000) or "")
                except Exception:
                    href = ""
            js = _JS_LINK.match(href) if href else None
            if not (js and _JS_LINK_NAVIGATES.search(js.group(1)) and not _JS_LINK_ACTS.search(js.group(1))):
                raise
            followed = self._follow_js_link(page, href)
            followed["clicked_via_js_link"] = True
            followed["instruction"] = (
                f"★ 누르기가 막혀({str(exc)[:60]}) 그 링크의 함수({js.group(1)})로 대신 따라갔다. "
                + str(followed.get("instruction") or "")
            ).strip()
            return followed
        self._show_visual(page, f"‘{name or ref}’ 선택", locator=locator, pulse=True)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        opened = self._adopt_new_window(windows_before)
        if opened:
            # 일이 저쪽으로 갔다. 이제부터 보는 것도 검증하는 것도 새 창이다.
            page = self._page
            if str(expect.get("kind") or "") == "text_appears":
                before = False  # 옛 창에서 잰 「전」은 새 창의 기준이 아니다
        result = self._evidence("clicked", ref=ref, element={"name": name, "tag": tag})
        # 눌렀더니 토글 상태가 뒤집혔으면, **같은 것을 다시 누르는 것이 역동작**이다.
        # 사이트를 몰라도 알 수 있는 몇 안 되는 되돌리기다(`_toggle_state` 참고).
        # 누르기 전에 토글이 아니었으면 뒤집힐 것도 없다. 다른 페이지로 넘어가 요소가 사라졌으면 읽을 것도 없다.
        toggle_after = self._toggle_state(locator) if toggle_before and self._still_there(locator) else None
        if toggle_before and toggle_after and toggle_before != toggle_after and not opened:
            result["toggled"] = {"attr": toggle_before[0], "from": toggle_before[1], "to": toggle_after[1]}
            result["undo_ref"] = ref
        if opened:
            result["opened_window"] = opened
            result["instruction"] = (
                f"새 창이 열려서 그쪽으로 옮겨 탔다({opened.get('url','')[:120]}). "
                "이제 browser_snapshot·browser_extract 는 이 새 창을 본다. "
                "원래 창으로 돌아가려면 browser_tabs 로 목록을 보고 browser_switch_tab 을 써라."
            )
        timeout = max(500, min(int(arguments.get("verify_timeout_ms") or 8000), 60000))
        if expect:
            verification = self._await_change(page, expect, before, timeout, signals_before)
            result["verification"] = verification
            result["verified"] = verification["status"] == "verified"
            # 모델이 가장 먼저 읽는 자리에도 올려 준다. verification 안에만 있으면
            # 중첩된 값을 안 펼쳐 보고 "실패"로만 읽는 일이 생긴다.
            if verification.get("instruction"):
                result["what_changed"] = verification.get("changes") or []
                result["instruction"] = verification["instruction"]
        elif approved:
            result["predicted"] = False
            changes = self._await_any_change(page, signals_before or {}, timeout)
            result["what_changed"] = changes
            if not changes:
                # 확실한 실패다. 되돌릴 수 없는 것을 누르라고 사람이 승인까지 했는데
                # 화면이 아무 반응도 안 했다 — 못 눌렀거나 무언가 막고 있다.
                result["verified"] = False
                result["instruction"] = (
                    "★ 눌렀는데 화면이 **하나도** 안 바뀌었다(주소·제목·요소 수·본문·"
                    "확인창 전부 그대로). 못 눌렀거나 무언가 가로막고 있다는 뜻이다. "
                    "**다시 누르지 마라** — 눌렸는데 화면만 안 바뀌었을 수도 있고, "
                    "되돌릴 수 없는 동작을 두 번 하는 것이 최악이다. "
                    "browser_snapshot 으로 화면을 다시 보고 사람에게 알려라."
                )
            else:
                # ★ 여기서 `verified: True` 를 주면 안 된다. 화면이 바뀐 것은
                # **의도한 일이 일어난 것과 다르다** — 오류 페이지로 넘어가도 화면은
                # 바뀐다. 우리가 아는 것은 "아무 일도 안 일어나지는 않았다"까지다.
                result["instruction"] = (
                    f"화면이 바뀌었다({', '.join(changes[:3])}). 다만 **의도한 일이**"
                    " 일어났는지는 이걸로 알 수 없다 — 예측(expect)을 주지 않았기"
                    " 때문이다. browser_extract 나 browser_read 로 결과를 직접 확인해라."
                )
        elif plain and not opened and "toggled" not in result:
            plain_changes = self._await_any_change(page, signals_before or {}, self._PLAIN_CLICK_SETTLE_MS)
            result["_changes"] = plain_changes
            quiet = not plain_changes
            if quiet:
                result["changed"] = False
                result["instruction"] = (
                    "눌렀다. 다만 화면에 달라진 것이 **없다**(주소·제목·요소 수·본문 그대로, 새 탭도 안 열림). "
                    "칸에 커서만 놓는 클릭이면 정상이다. 이동이나 열림을 기대했다면 안 된 것이니 **같은 것을 또 누르지 말고** "
                    "browser_tabs 로 새 탭이 생겼는지 보거나, 그 링크의 주소(href)를 browser_open 으로 열어라."
                )
        # 이 누르기가 덮는 창을 띄웠으면 기억해 둔다 — 다음 누르기가 그 창에 가로막혔을 때 치우지 않으려고(`_guarded_click`).
        seen_changes = [str(note) for note in (
            list(result.pop("_changes", None) or []) + list(result.get("what_changed") or [])
            + list((result.get("verification") or {}).get("changes") or []))]
        raised = next((note.split(":", 1)[1].strip() for note in seen_changes if note.startswith(_DIALOG_ROSE_NOTE)), "")
        if raised:
            self.__dict__["_dialog_we_opened"] = {
                "text": raised, "url": str(getattr(page, "url", "") or ""), "at": time.monotonic()}
        auto_closed = self.__dict__.pop("_auto_closed", None)
        if auto_closed:
            result["closed_first"] = auto_closed
            told = " · ".join(f"「{item['text'] or '(문구 없음)'}」 창을 「{item['pressed']}」로" for item in auto_closed)
            result["instruction"] = (
                f"★ 누르려던 것을 다른 창이 덮고 있어서 {told} 닫고 눌렀다. 그 창이 하던 일에 필요한 것이었다면 "
                "다시 띄워 그 창 안의 단추를 눌러라. " + str(result.get("instruction") or "")
            ).strip()
        checked_after = self._is_checked(locator) if native_check and not opened and self._still_there(locator) else None
        if checked_after is not None:
            result["checked"] = checked_after
            if checked_before is not None and checked_after != checked_before:
                result["changed"] = True
                result["verified"] = True
                result["instruction"] = (
                    f"눌려서 체크 상태가 바뀌었다({'체크됨' if checked_before else '비어 있음'} → "
                    f"{'체크됨' if checked_after else '비어 있음'}). 체크·선택은 화면의 글을 바꾸지 않는다 — 이것이 눌린 증거다."
                )
            elif checked_after and element_type.lower() == "radio":
                result["instruction"] = "이 항목은 누르기 전부터 선택돼 있었고 지금도 선택돼 있다."
        return result

    @staticmethod
    def _is_checked(locator: Any) -> bool | None:
        """체크 칸·라디오의 지금 상태. 못 읽으면 None."""
        try:
            return bool(locator.is_checked(timeout=1200))
        except Exception:  # noqa: BLE001
            return None

    # ---- did it actually happen? ----------------------------------------
    #
    # The rule this implements, from the 2026-08-05 handoff (3.3): an action
    # that changes something is only successful if the change can be read back
    # off the screen. Naver's 임시저장 proved the shape -- `draft_count:3->4` is
    # what turned "저장했습니다" from a claim into a fact, after a night where the
    # claim was made and nothing had been saved. None of that is Naver-specific,
    # so it lives here rather than in the blog flow.
    #
    # `unknown` is a first-class outcome and never a retry. The click may well
    # have landed; pressing again would post twice.

    def _observe(self, page: Any, expect: dict[str, Any]) -> Any:
        kind = str(expect.get("kind") or "")
        selector = _clean(expect.get("selector"), 200)
        value = _clean(expect.get("value"), 300)
        if kind == "url_changes":
            try:
                return str(page.url or "")
            except Exception:
                return ""
        if kind in {"text_appears", "text_disappears"}:
            return value in self._read(page, {"max_chars": 20000}).get("text", "")
        if kind in {"count_increases", "appears", "disappears"}:
            total = 0
            for frame in self._frames_of(page):
                try:
                    total += int(frame.locator(selector).count())
                except Exception:
                    continue
            return total
        if kind == "number_increases":
            # The generalized draft counter: whatever number this element shows.
            for frame in self._frames_of(page):
                try:
                    locator = frame.locator(selector).first
                    if not locator.is_visible():
                        continue
                    match = re.search(r"\d+", _clean(locator.inner_text(timeout=1200), 60))
                except Exception:
                    continue
                if match:
                    return int(match.group())
            return -1
        raise ValueError(f"unknown_expectation:{kind or '(없음)'}")

    @staticmethod
    def _satisfied(kind: str, before: Any, after: Any) -> str:
        """The evidence string when the expectation holds, else ''."""
        if kind == "url_changes":
            return f"url:{before}->{after}" if after and after != before else ""
        if kind == "text_appears":
            # ★ 누르기 전부터 있던 글은 증거가 아니다 (2026-10-07). 「이력서」가 원래 떠 있는 화면에서 expect 가
            #   text_appears:이력서 였고, 아무 일도 안 일어난 클릭이 두 번 `verified: true` 를 받았다.
            return "text_present" if after and not before else ""
        if kind == "text_disappears":
            return "text_gone" if not after else ""
        if kind == "appears":
            return f"count:{after}" if int(after) > 0 else ""
        if kind == "disappears":
            return "count:0" if int(after) == 0 else ""
        if kind in {"count_increases", "number_increases"}:
            if int(before) >= 0 and int(after) > int(before):
                return f"{kind.split('_')[0]}:{before}->{after}"
            return ""
        return ""

    # ---- 기대가 빗나갔을 때, 그래도 무엇이 바뀌었는지 -------------------------
    #
    # `unknown` 하나로 뭉뚱그리면 두 가지 다른 상황이 같은 얼굴이 된다.
    #
    #   "아무 일도 안 일어났다"   -> 못 눌렀거나 무언가 막고 있다. 사람이 봐야 한다.
    #   "다른 일이 일어났다"      -> 눌리긴 했다. 기대를 잘못 걸었을 뿐이다.
    #
    # 2026-08-05 실측: 커리어넷에서 메뉴를 눌렀더니 `url_changes` 가 빗나갔는데,
    # 화면은 분명히 바뀌어 있었다(조작 가능한 요소 73->75, 하위 메뉴가 열렸다).
    # 그 둘을 구별 못 하면 모델은 잘 눌린 것을 실패로 읽고 다른 길을 찾아 헤맨다.
    #
    # 둘 다 **재시도는 아니다**. 눌렸는데 확인만 못 했을 수 있고, 그러면 두 번 눌린다.

    #: 기대 없는 클릭 뒤에 화면이 바뀌기를 기다리는 시간. 길면 포커스만 옮기는 클릭마다 그만큼 느려진다.
    _PLAIN_CLICK_SETTLE_MS = 1200

    def _await_any_change(
        self, page: Any, signals_before: dict[str, Any], timeout_ms: int
    ) -> list[str]:
        """화면이 **뭐라도** 바뀔 때까지. 예측이 없을 때 쓰는 최소한의 잣대다.

        기대가 있으면 `_await_change` 가 훨씬 정확하게 판정한다. 여기는 예측 없이
        되돌릴 수 없는 것을 눌렀을 때, 적어도 **아무 일도 안 일어난 것**은 잡자는
        것이다. 기다리는 이유는 저장·제출이 대개 한 박자 늦기 때문이다 — 누르자마자
        재면 멀쩡한 동작도 "무동작"으로 몰린다.

        `_page_signals` 가 본문 2만 자를 읽으므로 폴 간격을 넉넉히 둔다. 어차피
        되돌릴 수 없는 클릭에서만 도는 길이고, 그런 클릭은 한 작업에 한두 번이다.
        """
        deadline = time.monotonic() + max(0.5, timeout_ms / 1000)
        while True:
            changes = self._explain_change(signals_before, self._page_signals(page))
            if changes or time.monotonic() >= deadline:
                return changes
            time.sleep(0.4)

    def _page_signals(self, page: Any) -> dict[str, Any]:
        """지금 화면의 값싼 지문. 클릭 전후로 견주기 위한 것.

        기대(expect)와 독립적으로 잰다 — 기대는 한 가지만 보지만, 화면은 그 한 가지
        말고 다른 것이 바뀌었을 수 있고 바로 그게 여기서 알고 싶은 것이다.
        """
        signals: dict[str, Any] = {"url": "", "title": "", "operable": 0, "text_len": 0, "text_hash": "", "dialog": ""}
        try:
            signals["url"] = str(page.url or "")
        except Exception:
            pass
        try:
            signals["title"] = _clean(page.title(), 200)
        except Exception:
            pass
        signals["operable"] = self._operable_count(page)
        try:
            text = str(self._read(page, {"max_chars": 20000}).get("text") or "")
        except Exception:
            text = ""
        signals["text_len"] = len(text)
        signals["text_hash"] = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:12]
        try:
            popup = self._first_visible_popup(page)
            signals["dialog"] = self._locator_text(popup, 200) if popup is not None else ""
        except Exception:
            pass
        return signals

    @staticmethod
    def _explain_change(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        """무엇이 어떻게 바뀌었는지, 사람이 읽는 문장으로."""
        notes: list[str] = []
        if before.get("url") != after.get("url"):
            notes.append(f"주소가 {after.get('url')} 로 바뀌었습니다")
        if before.get("title") != after.get("title"):
            notes.append(f"제목이 '{after.get('title')}' 로 바뀌었습니다")
        if after.get("dialog") and not before.get("dialog"):
            # 문구를 짧게 자른다. 메가 메뉴가 통째로 잡히면 200자가 한 줄로 들어와
            # 사람도 모델도 무엇이 떴는지 못 읽는다(워크넷 실측).
            notes.append(f"{_DIALOG_ROSE_NOTE}: {_clean(after.get('dialog'), 80)}")
        elif before.get("dialog") and not after.get("dialog"):
            notes.append("떠 있던 창이 닫혔습니다")
        if before.get("operable") != after.get("operable"):
            notes.append(
                f"조작 가능한 요소가 {before.get('operable')}개에서 {after.get('operable')}개로 바뀌었습니다"
            )
        if before.get("text_hash") != after.get("text_hash"):
            delta = int(after.get("text_len") or 0) - int(before.get("text_len") or 0)
            notes.append(f"화면 글이 바뀌었습니다(글자 {delta:+d})")
        return notes

    def _await_change(
        self,
        page: Any,
        expect: dict[str, Any],
        before: Any,
        timeout_ms: int,
        signals_before: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kind = str(expect.get("kind") or "")
        deadline = time.monotonic() + max(0.5, timeout_ms / 1000)
        # 이미 있던 글을 기다려 봐야 새로 나타날 수 없다 — 오래 기다리지 않고 화면이 바뀌었는지만 본다.
        already_there = kind == "text_appears" and bool(before)
        if already_there:
            deadline = time.monotonic() + 1.2
        after = before
        while True:
            try:
                after = self._observe(page, expect)
            except ValueError:
                raise
            except Exception:
                after = before
            evidence = self._satisfied(kind, before, after)
            if evidence:
                return {
                    "kind": kind, "status": "verified", "evidence": evidence,
                    "before": before, "after": after,
                }
            if time.monotonic() >= deadline:
                # 기대는 빗나갔다. 그런데 화면은 바뀌었을 수도 있다 — 그 둘은 다음에
                # 할 일이 완전히 다르므로 여기서 갈라 준다.
                if signals_before is None:
                    return {
                        "kind": kind, "status": "unknown", "evidence": "",
                        "before": before, "after": after,
                    }
                changes = self._explain_change(signals_before, self._page_signals(page))
                return {
                    "kind": kind,
                    "status": "changed_otherwise" if changes else "unchanged",
                    "evidence": "",
                    "before": before,
                    "after": after,
                    "changes": changes,
                    "instruction": ("기대한 글은 누르기 **전부터** 화면에 있었다 — 이 기대로는 눌린 효과를 알 수 없다. "
                                    if already_there else "") + (
                        "기대한 변화는 아니지만 화면이 바뀌었습니다. 다시 누르지 말고 "
                        "browser_snapshot 으로 지금 화면을 다시 읽고 다음 수를 고르세요."
                        if changes
                        else "화면에서 어떤 변화도 찾지 못했습니다. 같은 것을 다시 누르지 말고, "
                        "무엇이 막고 있는지 확인하거나(팝업·비활성) 사용자에게 화면을 봐 달라고 하세요."
                    ),
                }
            page.wait_for_timeout(400)

    def _verify(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """Check an expectation that needs no before-state (appears / text)."""
        expect = dict(arguments.get("expect") or {})
        kind = str(expect.get("kind") or "")
        if kind in {"url_changes", "count_increases", "number_increases"}:
            raise ValueError(f"expectation_needs_a_baseline:{kind}")
        timeout = max(200, min(int(arguments.get("timeout_ms") or 5000), 60000))
        # These four kinds are absolute -- "is the toast there", not "did the
        # count go up" -- so the before-state is only a starting sample.
        signals_before = self._page_signals(page)
        result = self._await_change(
            page, expect, self._observe(page, expect), timeout, signals_before
        )
        return self._evidence(
            "verified",
            verification=result,
            **({"what_changed": result["changes"]} if result.get("changes") else {}),
            **({"instruction": result["instruction"]} if result.get("instruction") else {}),
        )

    def _fill(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """입력칸을 채운다. **못 채우면 왜 못 채웠는지와 다음 수를 같이 준다.**

        ## 왜 다음 수까지 주나 (2026-08-15 실측)

        사람인에서 이런 판이 있었다:

            2 ui_find_target   ok
          ✗ 3 browser_fill     Locator.fill: Error: Element is not an <input>…
            4 browser_snapshot ok
          ✗ 5 browser_fill     Locator.fill: Error: Element is not an <input>…

        **같은 실패를 그대로 두 번 했다.** 플레이라이트의 원문은 사람에게는 정확한
        말이지만 모델에게는 다음에 무엇을 하라는 뜻이 하나도 없다. 그래서 같은
        수를 다시 둔다 — 끈기가 없는 것이 아니라 **다음 수를 모르는 것**이다.

        이 사이트가 왜 그런지도 알고 있다: 검색칸이 div 로 만든 복합 위젯이고
        진짜 `<input>`(`#ipt_keyword_recruit`)은 width=0 으로 숨어 있다. 비전이
        찾아 주는 것은 **눈에 보이는 div** 라 채울 수가 없다.

        되풀이 차단이 이 자리를 못 막는다는 점도 중요하다 — 인자(ref·value)가
        매번 달라서 지문이 갈린다. 막는 것으로 풀 문제가 아니라 **알려 줘서**
        풀 문제다.
        """
        ref = str(arguments.get("ref") or "")
        if arguments.get("value") is None:
            # ★ **넣을 글 없이 불리면 빈 글을 넣지 않는다** (2026-10-07 폼 벤치 넷째 판). 모델이 `fields: [{ref, value}]` 모양
            #   (여러 칸 채우기의 인자)으로 이 도구를 불렀고, 도구는 맨 위에 `value` 가 없다고 **빈 글을 넣고 성공**이라 답했다 —
            #   희망연봉·자격증 칸이 비었는데 모델은 「4200 입력」이라고 보고했다. 운영 기록(09-01 이후): 채우기 227번 중 11번이
            #   값 없이 불렸고, 일부러 빈 글을 준 것은 0번이다. 뜻이 분명하면 그대로 해 주고, 아니면 무엇이 빠졌는지 말한다.
            fields = arguments.get("fields")
            if isinstance(fields, list) and fields:
                return self._fill_form(page, {"fields": fields})
            raise ValueError(
                "value_required — 넣을 글(value)이 없다. 칸에 넣을 글을 value 로 줘라. 칸을 비우려는 것이면 value 에 빈 글을 주고, "
                "여러 칸이면 browser_fill_form(fields=[{ref, value}, …]) 을 써라."
            )
        value = str(arguments.get("value") or "")[:4000]
        locator = self._ref_locator(page, ref)
        field_type = _clean(locator.get_attribute("type"), 30)
        local_test_secret = field_type == "password" and self._local_test_secret_ok(page, value)
        if field_type == "file" or (field_type == "password" and not local_test_secret):
            raise RuntimeError("sensitive_field_blocked")
        # Playwright의 `fill()` 은 비활성 칸이 활성화되기를 기본 타임아웃까지 기다린다.
        # Google 공식 reCAPTCHA 데모처럼 애초에 disabled 로 고정된 샘플 필드에서는
        # 그 기다림이 칸마다 20초씩 반복됐다(2026-08-18 라이브). snapshot 이 이미
        # 아는 결정론적 사실은 **시도하기 전에** 끝낸다. 오래 기다린다고 활성화되는
        # 칸과 페이지가 나중에 활성화할 칸을 구별할 수 없으므로, 다시 snapshot 을
        # 찍으라는 다음 수도 함께 준다.
        try:
            disabled = bool(locator.is_disabled(timeout=1200))
        except Exception:
            disabled = False  # 판정 자체를 못 했으면 예전처럼 실제 fill 이 판단한다
        if disabled:
            raise RuntimeError(
                f"target_disabled:{ref} — 이 입력란은 현재 disabled 상태라 채울 수 없다. "
                "기다리며 같은 fill 을 반복하지 말고, 활성화 조건을 수행한 뒤 "
                "browser_snapshot 으로 새 ref·disabled 상태를 다시 확인하라."
            )
        self._show_visual(page, "입력란 선택", locator=locator)
        page.wait_for_timeout(180)
        # ★ 채우기 전에 **원래 있던 값**을 잡아 둔다 (2026-08-15).
        #
        # 브라우저 동작 중에 되돌리기를 진짜로 짤 수 있는 것이 이것이다 — 누르기는
        # 무엇이 일어날지 일반적으로 모르지만, 칸은 **원래 값으로 다시 채우면** 원래대로다.
        # 비밀번호·파일 칸은 위에서 이미 막혔으므로 여기 남는 것은 평범한 입력값이다.
        try:
            previous = str(locator.input_value(timeout=1200))[:2000]
        except Exception:
            previous = None  # 못 읽었으면 되돌리기를 안 내준다(무엇으로 되돌릴지 모른다)
        # ★ 날짜 칸은 정해진 꼴만 받는다(2026-10-03 Browser Use 조사 · Mind2Web 날짜 과제). 「10/05/2026」·「2026년 10월 5일」을
        #   그대로 넣으면 Playwright 가 「Malformed value」로 거절하고 모델은 같은 값을 또 넣는다. 도구가 꼴을 맞춘다.
        field_type = field_type.lower()
        if field_type in _DATE_INPUT_FORMATS:
            normalized = normalize_date_input(field_type, value)
            if normalized is None:
                raise RuntimeError(
                    f"date_format_required:{field_type} — 이 칸은 {_DATE_INPUT_FORMATS[field_type]} 꼴만 받는다"
                    f"(받은 값 「{_clean(value, 40)}」을 날짜로 못 읽었다). 그 꼴로 다시 채워라."
                )
            value = normalized
        try:
            locator.fill(value)
        except Exception as exc:
            raise RuntimeError(self._fill_failure_hint(locator, exc)) from exc
        evidence = self._evidence("filled", ref=ref, value_length=len(value))
        # 어느 칸에 넣었는지 **이름으로** 돌려준다 — 번호만 보고 옆 칸에 넣은 것을 그 자리에서 알아보게.
        remembered = (getattr(self, "_ref_memory", None) or {}).get(str(ref)) or {}
        field_name = _clean(remembered.get("name"), 80)
        if field_name:
            # 같은 이름의 칸이 여럿인 폼에서는 **어느 묶음의 칸**인지까지 — 「비상 연락처 › 연락처」.
            evidence["field"] = f"{_clean(remembered.get('group'), 40)} › {field_name}" if remembered.get("group") else field_name
        # ★ **채운 뒤 다시 읽는다** (2026-10-03 Browser Use 조사 · Mind2Web booking): 사이트가 값을 지우거나 고쳐 쓰는 칸이 있다.
        #   도구는 「채웠다」고 했는데 화면엔 다른 값 — 모델은 그걸 모른 채 검색을 눌렀다. 다르면 그 사실과 지금 값을 같이 준다.
        if not local_test_secret:
            try:
                after = str(locator.input_value(timeout=1200))[:200]
            except Exception:
                after = None
            if after is not None and after != value[:200]:
                evidence["value_after"] = _clean(after, 120)
                evidence["value_mismatch"] = True
                evidence["next"] = (
                    "칸에 남은 값이 친 값과 다르다 — 사이트가 지우거나 고쳐 썼다. 그대로 진행하지 말고 "
                    "browser_snapshot 으로 칸을 다시 보고, 목록에서 골라야 하는 칸이면 browser_pick_suggestion 을 써라."
                )
            # ★ **밑에 후보 목록이 떴나** (2026-10-03 Mind2Web WebMD 위치): 치면 후보가 뜨는 칸인데 Enter 를 눌러 아무것도
            #   안 골라졌다. 후보가 보이면 이름과 같이 알려 준다 — 고르는 것은 모델이 browser_pick_suggestion 으로.
            if value.strip() and field_type in {"", "text", "search", "email", "tel", "url"}:
                suggestions = self._visible_suggestions(page, value)
                if suggestions:
                    evidence["suggestions"] = suggestions
                    evidence.setdefault(
                        "next",
                        "입력칸 밑에 후보 목록이 떴다 — Enter 를 누르지 말고 "
                        f"browser_pick_suggestion(ref='{ref}', choose='<후보 글자 그대로>') 로 골라라.",
                    )
        if local_test_secret:
            # 비밀번호 값은 검색어 기억·되돌리기 값으로도 남기지 않는다 — 길이와 「맡긴 시험 계정」이라는 사실만.
            evidence["local_test_credential"] = True
            return evidence
        self._remember_filled(evidence.get("url"), locator, ref, len(value))
        self._remember_settled(page, locator, ref)
        # ★ **손으로 친 값도 검색어일 수 있다** (2026-09-06).
        #
        #   검색 주소 학습을 `browser_site_search` 성공 경로에만 걸었더니, 위시켓
        #   라이브에서 그 도구가 2 걸음에 실패하고 모델이 `browser_fill` +
        #   `browser_press` 로 손수 검색했다 — 학습기가 **한 번도 안 지났다.**
        #   오늘만 세 번째로 같은 실수다: 문에 걸면 다른 문으로 들어온다.
        #
        #   그래서 친 값을 들고 있다가, 나중에 목록이 뜨면 그때 배운다.
        #   값 자체는 안 쌓는다 — 마지막 하나만, 그리고 짧게만.
        self._remember_typed(value)
        if previous is not None:
            evidence["previous_value"] = previous
            evidence["undo_ref"] = ref
        return evidence

    def _visible_suggestions(self, page: Any, typed: str, *, wait_ms: int = 450) -> list[str]:
        """입력 뒤 **새로 뜬** 자동완성 후보(보이는 것만, 8개까지). 없거나 못 읽으면 빈 목록."""
        try:
            page.wait_for_timeout(wait_ms)
            found = page.evaluate(_SUGGESTION_SCAN_JS, typed[:60])
        except Exception:
            return []
        return [_clean(text, 80) for text in (found or []) if _clean(text, 80)][:8]

    @staticmethod
    def _fill_failure_hint(locator: Any, exc: Exception) -> str:
        """왜 못 채웠는지 + **그래서 다음에 무엇을 하면 되는지.**

        도구가 실패를 돌려줄 때 다음 수가 없으면 모델은 같은 수를 다시 둔다.
        이 저장소가 여러 번 확인한 것과 같은 규율이다 — 결정론으로 알려 줄 수
        있는 것은 안내문이 아니라 **그 자리에서** 준다.
        """
        detail = _clean(exc, 120)
        try:
            tag = _clean(locator.evaluate("el => el.tagName"), 20).lower()
        except Exception:
            tag = ""
        if "not an <input>" in detail or "not an <input>, <textarea>" in detail:
            return (
                f"fill_target_is_not_an_input:{tag or '?'} — 이 요소는 글자를 받는 칸이 아니다"
                "(div 로 만든 검색·선택 위젯이다). 다음 중 하나로 가라: "
                "① 이 요소를 browser_click 으로 먼저 눌러 진짜 입력칸을 띄운 뒤, "
                "browser_snapshot 을 다시 찍어 새로 생긴 input 을 채워라. "
                "② 치면 밑에 목록이 뜨는 칸이면 browser_pick_suggestion 을 써라. "
                "③ 드롭다운이면 browser_select_option 이다. "
                "④ 그 사이트에 레시피가 있으면 site_run 이 이미 아는 길로 간다. "
                "★ 같은 ref 에 browser_fill 을 다시 부르지 마라 — 같은 결과가 나온다."
            )
        if "not visible" in detail or "outside of the viewport" in detail:
            return (
                f"fill_target_not_visible:{tag or '?'} — 칸이 화면 밖이거나 가려져 있다. "
                "browser_scroll 로 그 자리로 내린 뒤 browser_snapshot 을 다시 찍어라. "
                "덮은 것이 팝업이면 browser_dismiss_dialog 가 먼저다."
            )
        if "disabled" in detail or "not enabled" in detail:
            return (
                f"target_disabled:{tag or '?'} — 이 입력란은 현재 비활성 상태다. "
                "같은 fill 을 반복하지 말고 활성화 조건을 수행한 뒤 snapshot 을 다시 찍어라."
            )
        return f"fill_failed:{detail}"

    def _pick_suggestion(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """**타이핑해서 뜬 목록에서 고른다.** 자동완성 한 벌을 한 걸음으로 묶은 것.

        ★ 2026-08-11 사용자 지적. 위시켓 보유기술에서 자비스가 `Python` 을 치는
        데까지는 했는데, 밑에 뜬 목록을 못 눌러 결국 사용자가 손으로 하셨다.
        도구 하나하나는 다 있었다 — 채우기·스냅샷·클릭. 없던 것은 **순서**다:

            채운다 → 목록이 뜰 때까지 기다린다 → **다시 찍는다** → 새로 생긴 것 중에서 고른다

        모델에게 이 순서를 매번 알아서 하라고 두면 어제처럼 낡은 스냅샷의 저장
        버튼을 누른다. 결정론으로 만들 수 있는 절차를 모델 판단에 맡기지 않는다.

        **새로 생긴 것**만 후보로 본다. 그래야 이미 등록돼 있던 같은 이름의 줄
        (위시켓에는 기존 기술 목록이 화면에 그대로 있다)을 잘못 누르지 않는다.
        팝업 창을 따라갈 때 쓴 수법과 같다 — 전후를 비교해서 달라진 것을 잡는다.

        못 고르면 **누르지 않고** 후보를 이름과 함께 돌려준다. 비슷한 걸 아무거나
        누르는 것이 이 기능에서 제일 나쁜 실패다.
        """
        ref = str(arguments.get("ref") or "")
        text = str(arguments.get("text") or "").strip()
        choose = str(arguments.get("choose") or text).strip()
        if not choose:
            raise ValueError("choose_required")
        wait_ms = max(500, min(int(arguments.get("wait_ms") or 4000), 15000))

        # ★ 낡은 ref 를 여기서 한 번 되살린다(2026-08-11 실측).
        #
        # SPA 는 앞 칸을 고르면 그 자리를 통째로 다시 그린다. 위시켓에서 숙련도를
        # 고른 직후 경험 칸의 ref 가 죽어 `stale_element_ref` 로 끝났다 — 사람 눈엔
        # 화면이 그대로인데 자비스만 손을 놓는다. 다시 찍어서 한 번 더 찾아본다.
        # 그래도 없으면 그때는 진짜 없어진 것이다.
        # 낡은 ref 는 `_ref_locator` 가 이름으로 되살린다(공통 계층). 여기서
        # 따로 땜질하지 않는다 — 도구마다 제 나름대로 복구하면 규칙이 갈린다.
        locator = self._ref_locator(page, ref)
        if _clean(locator.get_attribute("type"), 30) in {"password", "file"}:
            raise RuntimeError("sensitive_field_blocked")

        # 모델이 네이티브 <select>를 자동완성/커스텀 셀렉트로 잘못 분류해도
        # 목록의 껍데기를 클릭하는 식으로 조용히 실패시키지 않는다. 실제 폼에서
        # 이 오분류가 나와 `verified=false` 뒤 사람에게 선택을 떠넘겼다. ref가
        # 가리키는 실물은 도구가 확정할 수 있으므로 visible label로 바로 고른다.
        tag = _clean(locator.evaluate("el => el.tagName.toLowerCase()"), 20)
        if tag == "select":
            result = self._select_option(page, {"ref": ref, "label": choose})
            result["routed_from"] = "browser_pick_suggestion"
            return result

        # ★ 여기서 화면 목록을 미리 세면 안 된다(2026-08-11 실측 `invalid_element_ref`).
        # 목록을 세는 일은 요소마다 ref 를 **다시 찍는 것**이라, 방금 받은 ref 가
        # 그 자리에서 무효가 된다 — 진단하려던 코드가 본작업을 깨뜨린다.
        # 후보 목록은 **못 찾았을 때만** 센다. 그때는 더 이상 원래 ref 를 안 쓴다.
        self._show_visual(page, f"‘{text or choose}’ 고르기", locator=locator)
        # ★ **이미 열린 목록을 닫지 않는다** (2026-10-07 폼 벤치 과제 F · 3판 중 2판). 모델이 드롭다운을 먼저 눌러 열어 놓고 이 도구를
        #   불렀더니, 여기서 그 단추를 한 번 더 눌러 **목록을 닫은 뒤** 선택지를 찾았다 — 「목록에 없다」. 누르는 드롭다운은 누를 때마다
        #   열렸다 닫힌다. 칠 글이 없고(누르는 칸) 고를 것이 **목록 안에** 이미 보이면 칸을 다시 누르지 않고 그것을 고른다.
        already_open = None if text else self._innermost_option(page, choose, in_list_only=True)
        if already_open is None:
            locator.click()
        # ★ `text` 는 없어도 된다. 눌러야 목록이 뜨는 칸(커스텀 셀렉트)이 그렇다 —
        # 위시켓의 숙련도·경험이 <select> 가 아니라 div 라 네이티브 셀렉트 도구가
        # 안 먹는다. 치는 칸과 누르는 칸은 **고르는 방식이 같다**: 목록이 뜨고,
        # 새로 생긴 것 중에서 고른다. 그래서 한 도구로 둘 다 한다.
        if text:
            try:
                locator.fill("")
            except Exception:
                pass
            # 진짜 키로 친다. `fill()` 은 값만 꽂으므로, keyup·debounce 로 검색하는
            # 자동완성은 아예 뜨지 않는 사이트가 있다. 위시켓은 fill 로도 떴지만
            # 그건 이 사이트 사정이고, 도구는 사이트를 가리면 안 된다.
            try:
                locator.press_sequentially(text, delay=45)
            except AttributeError:  # 예전 playwright
                locator.type(text, delay=45)

        deadline = time.monotonic() + wait_ms / 1000
        fresh: list[dict[str, Any]] = []
        chosen: dict[str, Any] | None = already_open
        while chosen is None:
            # ★ 목록에서 고를 때는 **제일 안쪽 글자**를 찾는다.
            #
            # 스냅샷 목록으로 고르려다 실패했다(2026-08-11 실측): 스냅샷은 바깥쪽
            # 요소를 우선 담으므로 셀렉트를 열면 "숙련도 관심있음 초급 중급 고급 특급"
            # 이라는 **껍데기 하나**만 후보로 오고, 정작 눌러야 할 '중급' 은 그 안에
            # 있어서 목록에 없다. 껍데기를 누르면 아무 일도 안 일어난다.
            chosen = self._innermost_option(page, choose)
            if chosen:
                break
            if time.monotonic() >= deadline:
                break
            page.wait_for_timeout(250)
        if chosen is None:
            fresh = self._all_elements(page)
            return self._evidence(
                "suggestion_not_found",
                typed=text,
                looking_for=choose,
                # 무엇이 떴는지는 보여 준다 — 사람이 보면 바로 아는 경우가 많다.
                candidates=[str(i.get("name") or "")[:60] for i in fresh[:12]],
                instruction=(
                    f"‘{text}’ 를 쳤는데 ‘{choose}’ 와 맞는 항목이 목록에 없다. "
                    "위 candidates 에서 고를 것이 보이면 choose 를 그 글자로 바꿔 다시 불러라. "
                    "아무것도 없으면 그 사이트는 다른 방식일 수 있으니 화면을 사람에게 보여라. "
                    "**비슷해 보이는 다른 것을 누르지 마라.**"
                ),
            )

        target = chosen["locator"]
        target.click()
        page.wait_for_timeout(500)
        # 고른 값이 칸의 새 기준이다 — 안 고치면 다음 누르기가 「값이 달라졌다」로 붙잡는다.
        self._resettle_fields(page)
        # ★ 고른 항목이 화면에서 사라졌는가 = 목록이 닫혔는가.
        #
        # 전체를 다시 훑어 비교하려다 두 번 데였다: 훑는 일이 ref 를 다시 찍어
        # 남의 ref 를 깨뜨렸고(invalid_element_ref), 텍스트로 확인하려니 입력란의
        # 값은 본문 글자가 아니라서 "안 들어갔다"고 오판했다. 방금 누른 그것만 본다.
        try:
            settled = not target.is_visible()
        except Exception:
            settled = True  # 요소 자체가 사라져 조회가 안 되면 닫힌 것이다
        return self._evidence(
            "suggestion_picked",
            typed=text,
            picked=str(chosen.get("name") or "")[:80],
            matched=str(chosen.get("matched") or "")[:80],
            verified=bool(settled),
            instruction=(
                "골랐다. 목록이 닫혔다."
                if settled
                else "눌렀는데 목록이 그대로다 — 안 골라졌을 수 있으니 화면을 다시 확인해라."
            ),
        )

    def _innermost_option(self, page: Any, choose: str, *, in_list_only: bool = False) -> dict[str, Any] | None:
        """지금 화면에서 `choose` 에 해당하는 **제일 안쪽** 항목을 찾아 ref 를 찍는다.

        목록에서 고르는 일은 스냅샷 목록으로 하면 안 된다. 스냅샷은 겹친 것 중
        **바깥쪽**을 담는데(그래야 아이콘 버튼이 제대로 잡힌다), 셀렉트를 열면
        바깥쪽은 "숙련도 관심있음 초급 중급 고급 특급" 같은 껍데기다. 눌러야 할
        '중급' 은 그 안에 있고, 껍데기를 누르면 아무 일도 안 일어난다.

        그래서 고를 때만은 반대로 본다 — **글자가 맞으면서 그 안에 다른 후보를
        품고 있지 않은 것.** 사람이 목록에서 한 줄을 고르는 것과 같다.
        """
        script = """
        (args) => {
          const { want, stamp, listOnly } = args;
          const norm = (s) => (s == null ? "" : String(s)).replace(/\\s+/g, " ").trim().toLowerCase();
          const w = norm(want);
          if (!w) return null;
          const visible = (el) => {
            if (!el.getClientRects().length) return false;
            const st = window.getComputedStyle(el);
            if (st.visibility === "hidden") return false;
            return parseFloat(st.opacity) !== 0;
          };
          const hits = [];
          // ★ 글자를 치는 칸은 후보가 아니다(2026-10-07 폼 벤치 과제 G · 3판 중 2판). 모델이 칸에 「…대학교」를 먼저 채우고 이 도구를
          //   불렀더니, 값이 그 글자인 **칸 자신**이 「정확히 같은 후보」가 됐고 문서에서 목록보다 앞이라 그것이 뽑혔다. 칸을 눌렀으니
          //   아무것도 안 골라졌고(「목록이 그대로다」), 칸을 떠나자 사이트가 값을 지웠다. 값으로 이름을 삼는 것은 누르는 단추뿐이다.
          const typing = (el) => el.matches("textarea, select, [contenteditable=true]")
            || (el.tagName === "INPUT" && !["button", "submit", "reset", "image"].includes((el.getAttribute("type") || "text").toLowerCase()));
          for (const el of document.querySelectorAll("body *")) {
            if (!visible(el) || typing(el)) continue;
            // 「이미 열려 있나」를 볼 때는 목록 안의 것만 센다 — 닫힌 드롭다운에 적힌 지금 값·설명 글을 선택지로 잘못 집지 않게.
            if (listOnly && !el.closest("[role=listbox],[role=option],[role=menu],[role=menuitem],ul,ol,datalist")) continue;
            const t = norm(el.innerText || el.getAttribute("aria-label") || el.value);
            if (!t) continue;
            if (t === w || t.startsWith(w) || t.includes(w)) hits.push([t, el]);
          }
          if (!hits.length) return null;
          // 다른 후보를 품고 있으면 그건 껍데기다.
          const inner = hits.filter(([, el]) => !hits.some(([, o]) => o !== el && el.contains(o)));
          const pool = inner.length ? inner : hits;
          const rank = ([t]) => (t === w ? 0 : t.startsWith(w) ? 1 : 2);
          pool.sort((a, b) => rank(a) - rank(b) || a[0].length - b[0].length);
          const [text, el] = pool[0];
          // ★ 스냅샷 ref(jNN)와 **다른 표식**을 쓴다. 스냅샷 번호를 덮어쓰면
          // 다른 도구가 들고 있던 ref 가 그 자리에서 어긋난다(실측: invalid_element_ref).
          el.setAttribute("data-jarvis-opt", stamp);
          return { stamp, name: (el.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 120),
                   tag: el.tagName.toLowerCase(), matched: text.slice(0, 120) };
        }
        """
        stamp = f"{int(time.time() * 1000)}"
        for frame in self._frames_of(page):
            try:
                found = frame.evaluate(_deep_js(script), {"want": choose, "stamp": stamp, "listOnly": bool(in_list_only)})
            except Exception:
                continue
            if isinstance(found, dict) and found.get("stamp"):
                found["locator"] = frame.locator(f'[data-jarvis-opt="{stamp}"]')
                return found
        return None

    def _all_elements(self, page: Any) -> list[dict[str, Any]]:
        """지금 화면의 조작 가능한 것 전부 — **번호는 새로 찍지 않는다.**

        속으로 훑는 일이 번호를 다시 매기면 밖에 내준 ref 가 그 자리에서 어긋난다.
        이름만 필요할 때 쓴다.
        """
        return self._scan_elements(page, stamp_refs=False)

    def _snapshot_elements(self, page: Any) -> list[dict[str, Any]]:
        """번호를 새로 찍고, **무엇이 무슨 이름이었는지 기억한다.**

        그 기억이 나중에 죽은 ref 를 되살리는 유일한 근거다(`_recover_ref`).
        """
        items = self._scan_elements(page, stamp_refs=True)
        self._remember_refs(items)
        return items

    def _remember_refs(self, rows: list[dict[str, Any]]) -> None:
        """방금 번호표를 붙인 것 **전부**의 이름을 적어 둔다 — 스냅샷이 모델에게 내준 200개만이 아니라."""
        self._ref_memory = {
            str(i.get("ref")): {"name": str(i.get("name") or ""), "tag": str(i.get("tag") or ""),
                                **({"group": str(i["group"])} if i.get("group") else {})}
            for i in rows
            if i.get("ref")
        }

    def _scan_elements(self, page: Any, *, stamp_refs: bool) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for index, frame in enumerate(self._frames_of(page)):
            out.extend(
                self._frame_elements(
                    frame,
                    frame_label=self._frame_label(frame, index),
                    frame_index=index,
                    # 250 에서 끊으면 번호표를 다시 붙일 때 251번째부터가 **번호를 잃는다**(되살리려다 더 죽인다).
                    budget=_MAX_SCAN,
                    start=len(out),
                    include_box=False,
                    stamp_refs=stamp_refs,
                    # ★ 여기는 상한을 걸지 않는다. 이 훑기는 `browser_pick_suggestion`
                    # 이 **이름으로 하나를 찾으려고** 쓰는 것이라, 목록을 접으면
                    # 57번째 항목을 영영 못 고른다. 접는 것은 사람·모델에게 목록을
                    # 내주는 `_snapshot` 에서만 한다.
                    group_cap=0,
                )
            )
        return out

    @staticmethod
    def _suggestion_head(name: Any) -> str:
        """목록 이름에서 **꼬리표를 뗀 알맹이**.

        자동완성 항목은 이름 뒤에 숫자를 달고 오는 일이 흔하다(위시켓은 보유자 수:
        `Java 480`, `JavaScript 1200`). 그걸 그대로 비교하면 `Java` 를 찾을 때
        정확일치가 하나도 없어 접두사 비교로 내려가고, 거기서 `JavaScript` 가
        먼저 걸린다. 사이트마다 꼬리표 모양이 다르므로 **숫자 꼬리만 뗀다.**
        """
        tokens = str(name or "").split()
        while tokens and re.fullmatch(r"[\d,.]+", tokens[-1]):
            tokens.pop()
        return " ".join(tokens).casefold().strip()

    @staticmethod
    def _match_suggestion(items: list[dict[str, Any]], choose: str) -> dict[str, Any] | None:
        """고를 것을 정한다 — **순위가 고정돼 있다.** 사이트를 가리지 않는다.

            ① 알맹이가 정확히 같다        Java  ←  "Java 480"
            ② 알맹이가 그 낱말로 시작한다  Java  ←  "Java SE 8"   (낱말 경계까지 본다)
            ③ 이름 전체가 정확히 같다
            ④ 이름이 그 낱말로 시작한다
            ⑤ 어디든 들어 있다

        ★ ②에서 **낱말 경계**를 보는 것이 핵심이다. 그게 없으면 `Java` 가
        `JavaScript` 를 먼저 잡고, 사용자는 한참 뒤에 엉뚱한 태그를 발견한다.
        조용히 틀리는 쪽이 제일 나쁜 실패다.

        같은 순위가 여럿이면 **화면에 먼저 나온 것**을 고른다. 자동완성 목록은
        관련도 순으로 오므로 위쪽이 정답일 확률이 높고, 무엇보다 **매번 같은 것을
        고른다** — 같은 화면에서 두 번 부르면 두 번 다 같은 결과여야 한다.
        """
        want = str(choose or "").casefold().strip()
        if not want:
            return None
        rows = [
            (BrowserWorker._suggestion_head(i.get("name")), str(i.get("name") or "").casefold().strip(), i)
            for i in items
        ]

        def starts_word(text: str, prefix: str) -> bool:
            if not text.startswith(prefix):
                return False
            rest = text[len(prefix) :]
            return not rest or not rest[0].isalnum()

        for probe in (
            lambda head, full: head == want,
            lambda head, full: starts_word(head, want),
            lambda head, full: full == want,
            lambda head, full: starts_word(full, want),
            lambda head, full: want in head or want in full,
        ):
            for head, full, item in rows:
                if (head or full) and probe(head, full):
                    return item
        return None

    def _adopt_new_window(self, known: list[Any], *, wait_ms: int = 2000) -> dict[str, Any] | None:
        """클릭이 새 창을 열었으면 **그 창으로 옮겨 탄다.** 없으면 None.

        ★ 2026-08-10 사용자 지적("위시켓에서 구글로 로그인이 안 된다"). 실제로 가서
        보니 **구글은 아무것도 막고 있지 않았다** — 로그인 화면이 멀쩡히 떠 있었다.
        다만 그게 **새 창**에 떠 있었고, 자비스는 원래 창만 보고 있었다:

            탭 0  auth.wishket.com/login      ← 자비스가 보던 곳
            탭 1  accounts.google.com/...     ← 실제로 일이 벌어지는 곳

        그래서 자비스는 "주소가 그대로다 = 아무 일도 안 일어났다"고 읽었고, 사람
        눈에는 큰 창 뒤에 가려 "눌러도 안 넘어간다"로 보였다. OAuth·결제·본인확인이
        전부 이 모양이라 한 사이트의 문제가 아니다.

        새 창을 **앞으로 가져오는 것**도 여기서 같이 한다. 자비스만 따라가고 사람은
        못 보면, 화면과 자비스가 갈라지는 그 자리가 그대로 남는다.
        """
        if self._context is None:
            return None
        deadline = time.monotonic() + max(0, wait_ms) / 1000
        while True:
            fresh = [
                item
                for item in self._context.pages
                if not item.is_closed() and not any(item is seen for seen in known)
            ]
            if fresh:
                # 여러 개면 마지막 것. 클릭 하나가 창을 둘 여는 경우는 광고뿐이고,
                # 그때도 사람이 마지막으로 보게 되는 것이 마지막 창이다.
                page = fresh[-1]
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                # 사람도 봐야 한다. 자비스만 따라가면 화면과 자비스가 갈라진다 — 단 사람이 다른 일을 하는 중이면
                # 앞으로 안 가져온다(작업 화면의 실시간 화면으로 본다).
                self._bring_to_front(page)
                self._page = page
                self._maximize_window(page)
                try:
                    return {"url": page.url, "title": _clean(page.title(), 200)}
                except Exception:
                    return {"url": "", "title": ""}
            if time.monotonic() >= deadline:
                return None
            # 팝업은 클릭 직후 바로 안 뜬다(리다이렉트가 한 번 더 도는 경우가 흔하다).
            # ★ 기다리는 동안 **이벤트를 돌린다** (2026-10-07 대표 실사용). `time.sleep` 은 Playwright 이벤트를 안 돌려서,
            #   그 사이 열린 새 탭이 `context.pages` 에 끝내 안 나타났다 — 「이력서 100% 완성」을 네 번 눌러 수정 탭이
            #   넷 열렸는데 손자리는 원래 탭에 남아 「눌렀다」만 보고했다. 재현: sleep 0/3 · wait_for_timeout 3/3(0.1초).
            pump = next((item for item in known if not item.is_closed()), None)
            try:
                pump.wait_for_timeout(100)
            except Exception:  # noqa: BLE001 — 돌릴 탭이 없거나 닫혔다
                time.sleep(0.1)

    _FORM_TRAIL_MAX = 24

    _SETTLED_MAX = 12

    @staticmethod
    def _value_print(value: str) -> str:
        """값의 지문. **꼴만 바뀐 것**(쉼표·붙임표·대소문자·날짜 순서)은 같은 지문이 되게 글자·숫자만 모아 정렬한다."""
        letters = sorted(ch for ch in str(value or "").casefold() if ch.isalnum())
        return hashlib.sha1("".join(letters).encode("utf-8")).hexdigest()

    def _remember_settled(self, page: Any, locator: Any, ref: str) -> None:
        """방금 채운 칸의 **자리 잡은 값의 지문**을 적어 둔다. 값은 안 남긴다(`_remember_filled` 와 같은 규율)."""
        try:
            handle = locator.element_handle(timeout=800)
            value = str(locator.input_value(timeout=800))
        except Exception:
            return
        if handle is None:
            return
        name = ""
        for attribute in ("aria-label", "name", "placeholder", "id"):
            try:
                name = _clean(locator.get_attribute(attribute), 60)
            except Exception:
                name = ""
            if name:
                break
        url = str(getattr(page, "url", "") or "").split("#")[0]
        field = name or ref
        # 이 화면에서 채운 칸이 아직 하나도 없으면(= 방금 열었거나 다시 연 화면의 첫 채우기) 글의 기준을 새로 잡는다.
        first_fill_on_this_screen = not self._read_settled(page)
        kept = [item for item in (getattr(self, "_settled_fields", None) or [])
                if item["url"] == url and item["field"] != field]
        kept.append({"url": url, "field": field, "handle": handle, "print": self._value_print(value),
                     "chars": len(value), "told": ""})
        self._settled_fields = kept[-self._SETTLED_MAX:]
        # 이 화면에서 처음 채운 때의 글을 적어 둔다 — 나중에 「채운 뒤 새로 나온 글」(사이트의 오류 안내)을 가려낼 기준이다.
        # ★ 기준은 주소가 아니라 **이번에 연 화면**에 묶는다(2026-10-07 벤치 H: 3판 중 첫 판만 통과). 주소로만 묶었더니 같은 주소를
        #   다시 연 판에서는 앞 판이 본 오류 글이 이미 「아는 글」이라 한 번도 건네지 않았다.
        if first_fill_on_this_screen or (self.__dict__.get("_settled_text") or {}).get("url") != url:
            self._settled_text = {"url": url, "lines": self._screen_lines(page)}

    @staticmethod
    def _screen_lines(page: Any) -> set[str]:
        """지금 화면에 보이는 글을 줄로 나눈 것. 못 읽으면 빈 집합."""
        try:
            body = str(page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 80000)") or "")
        except Exception:
            return set()
        return {" ".join(line.split()) for line in body.splitlines() if len(line.strip()) >= 4}

    def _said_since_filled(self, page: Any, *, skip: tuple[str, ...] = ()) -> list[str]:
        """이 화면에서 칸을 채운 뒤 **새로 나온 글** — 대개 사이트가 그 값에 대해 한 말이다(「YYYY.MM.DD 로 넣어 주세요」).

        ★ 2026-10-07 폼 벤치 과제 H(달력 · 3판 중 0판): 모델은 날짜를 `2026-02-02` 로 넣었고 사이트는 칸을 떠나자 지우면서
          받는 모양을 화면에 적었다. 누르기 전 확인은 「값이 달라졌다」까지만 말했고, 모델은 같은 모양으로 세 번 더 넣었다
          (한 판은 48걸음). 화면은 이미 답을 말하고 있었다 — 그 말을 그 자리에서 건넨다. 낱말 목록으로 오류 글을 찾지 않는다:
          채우기 전에 없던 줄이면 된다. 한 번 건넨 줄은 다시 건네지 않는다. 길거나 많은 것(새로 그려진 목록)은 버린다.
        """
        memo = self.__dict__.get("_settled_text") or {}
        url = str(getattr(page, "url", "") or "").split("#")[0]
        if memo.get("url") != url:
            return []
        fresh = [line for line in self._screen_lines(page) - set(memo.get("lines") or ())
                 if len(line) <= 160 and line not in skip]
        memo["lines"] = set(memo.get("lines") or ()) | set(fresh)
        return sorted(fresh, key=len)[:3] if len(fresh) <= 8 else []

    def _read_settled(self, page: Any) -> list[tuple[dict[str, Any], str]]:
        """이 화면에 아직 붙어 있는 기억한 칸과 **지금 값**. 다른 화면 것·사라진 칸은 버린다."""
        url = str(getattr(page, "url", "") or "").split("#")[0]
        alive: list[tuple[dict[str, Any], str]] = []
        for item in getattr(self, "_settled_fields", None) or []:
            if item["url"] != url:
                continue
            try:
                now = item["handle"].evaluate("el => el.isConnected ? String(el.value ?? '') : null")
            except Exception:
                continue
            if now is None:
                continue
            alive.append((item, str(now)))
        self._settled_fields = [item for item, _ in alive]
        return alive

    def _leave_filled_field(self, page: Any, target: Any, tag: str) -> None:
        """누르면 어차피 떠날 칸을 **먼저** 떠나 본다. 떠나는 순간 값을 지우는 칸은 그때 드러난다.

        목록 안의 것을 누를 때는 건드리지 않는다 — 후보를 고르는 중일 수 있고, 먼저 떠나면 그 목록이 닫힌다.
        """
        if tag not in {"button", "a", "input"} or not getattr(self, "_settled_fields", None):
            return
        try:
            in_a_list = bool(target.evaluate(
                "el => !!el.closest('[role=listbox],[role=option],[role=menu],[role=menuitem],ul,ol,datalist')"
            ))
        except Exception:
            return
        if in_a_list:
            return
        for item, _ in self._read_settled(page):
            try:
                if item["handle"].evaluate("el => el === document.activeElement"):
                    item["handle"].evaluate("el => el.blur()")
                    page.wait_for_timeout(200)
            except Exception:
                continue

    def _fields_changed_since_filled(self, page: Any) -> list[dict[str, Any]]:
        """채운 뒤 값이 달라진 칸들. **같은 상태를 두 번 알리지 않는다** — 두 번째에는 누르게 둔다."""
        changed: list[dict[str, Any]] = []
        for item, now in self._read_settled(page):
            current = self._value_print(now)
            if current == item["print"] or item["told"] == current:
                continue
            item["told"] = current
            changed.append({"field": item["field"], "filled_chars": item["chars"],
                            "now": _clean(now, 80), "now_chars": len(now)})
        return changed

    def _resettle_fields(self, page: Any) -> None:
        """지금 값이 새 기준이다(목록에서 골라 칸이 바뀐 뒤)."""
        for item, now in self._read_settled(page):
            item["print"] = self._value_print(now)
            item["chars"] = len(now)
            item["told"] = ""

    def _remember_filled(self, url: Any, locator: Any, ref: str, chars: int) -> None:
        """어느 화면에서 어떤 칸을 채웠는지 적어 둔다. **값은 안 남긴다.**

        제출한 뒤 사람이 "무엇을 냈는지" 찾아갈 수 있게 하려는 것이지, 낸 내용을
        쌓아 두려는 것이 아니다. 이름과 글자 수면 찾아가기에 충분하고, 값까지
        남기면 이 장부가 그 자체로 새는 자리가 된다.
        """
        name = ""
        for attribute in ("aria-label", "name", "placeholder", "id"):
            try:
                name = _clean(locator.get_attribute(attribute), 60)
            except Exception:
                name = ""
            if name:
                break
        self._form_trail.append(
            {"url": str(url or ""), "field": name or ref, "chars": chars, "at": time.time()}
        )
        del self._form_trail[: -self._FORM_TRAIL_MAX]

    def _filled_here(self, url: str) -> list[dict[str, Any]]:
        """이 화면에서 채운 칸들. 주소가 같은 것만 본다."""
        here = str(url or "").split("#")[0]
        return [item for item in self._form_trail if str(item.get("url") or "").split("#")[0] == here]

    def _submit_handle(self, result: dict[str, Any]) -> dict[str, Any] | None:
        url = str(result.get("url") or "")
        if not url:
            # 어디서 냈는지 모르면 찾아갈 수가 없다. 안 내주는 편이 낫다.
            return None
        element = result.get("element") or {}
        return {
            "url": url,
            "title": str(result.get("title") or "")[:120],
            "button": str(element.get("name") or "")[:80],
            # 그 화면에서 채운 칸 이름들. 값이 아니라 **무엇을 냈는지**의 목록이다.
            "fields": [item["field"] for item in self._filled_here(url)][:12],
        }

    # 표준이 **"나는 토글이다"라고 말해 주는** 속성. 여기 있는 것만 본다.
    #
    # `aria-pressed` 와 `aria-checked` 는 뜻이 정해져 있다 — 누르면 두 상태를
    # 오가는 버튼이고 지금 어느 쪽인지 알려 준다. 그러니 뒤집혔다면 **같은 것을
    # 다시 누르는 것이 역동작**이라고 말할 근거가 있다. 사이트를 몰라도 된다.
    _TOGGLE_ATTRS = ("aria-pressed", "aria-checked")

    @staticmethod
    def _still_there(locator: Any) -> bool:
        """누른 요소가 **아직 화면에 있나** — 기다리지 않고 센다 (2026-10-05 AWS 영어 윈도우 첫 실행).

        링크를 눌러 다른 페이지로 넘어가면 그 요소는 사라진다. 그 뒤에 같은 요소를 두 번 더 찾았다 — 누름 표시를 그릴 자리
        (`bounding_box`)와 토글 상태(`get_attribute`). 둘 다 기본 대기 8초를 꽉 채웠고, 페이지 대기 3초가 붙어
        **클릭 한 번이 19초**였다(원격 GitHub 판 19,297·19,266·19,436ms — 233초 판 가운데 58초).
        이 PC 운영 기록도 같다: 주소가 바뀌는 클릭 28번 중 24번이 7초 이상, 가운데값 11.5초.
        실제 크롬으로 재니 클릭 0.58초 · 사라진 요소 자리 재기 8.01초 · 속성 읽기 8.00초 · **세기 0.03초**.

        `count()` 는 요소를 기다리지 않는다. 페이지가 넘어가는 중이라 셀 수 없으면 사라진 것으로 본다.
        셀 줄 모르는 것(시험용 가짜)은 예전대로 「있다」.
        """
        try:
            return int(locator.count()) > 0
        except AttributeError:
            return True
        except Exception:  # noqa: BLE001 — 넘어가는 중(실행 문맥이 사라짐)이면 그 요소도 없다
            return False

    def _toggle_state(self, locator: Any) -> tuple[str, str] | None:
        """이 요소가 **표준 토글**이면 `(속성, 지금 값)`. 아니면 None.

        ## 왜 클래스 변화로는 안 보나 (중요)

        "눌렀더니 이 요소의 클래스가 바뀌었다"도 토글의 신호처럼 보인다. 그런데
        **제출 버튼도 누르면 클래스가 바뀐다**(disabled·loading·done…). 그걸 토글로
        오해하면 "되돌리기"가 **두 번째 제출**이 된다 — 지원서를 두 번 내는 것보다
        나쁜 되돌리기는 없다.

        그래서 표준이 뜻을 정해 둔 것만 본다. 못 잡는 토글(ARIA 를 안 쓰는 사이트)이
        생기지만, **없는 역동작을 만들어 내지는 않는다.** 모르면 안 내주는 쪽이 맞다.

        실측(2026-08-16): 사람인 검색 화면에 `[aria-pressed]` 가 **40개**,
        다나와에 `[role=switch]` 5개. 쿠팡·위시켓은 안 쓴다. 범용으로 다 덮지는
        못해도, 쓰는 사이트에서는 **레시피 없이** 스크랩·관심기업이 되돌려진다.
        """
        for attribute in self._TOGGLE_ATTRS:
            try:
                value = _clean(locator.get_attribute(attribute), 12)
            except Exception:
                return None
            if value in {"true", "false"}:
                return (attribute, value)
        return None

    def _toggle_handle(self, result: dict[str, Any]) -> dict[str, Any] | None:
        toggled = result.get("toggled") or {}
        ref = str(result.get("undo_ref") or "")
        if not ref or not toggled:
            return None
        return {
            "ref": ref,
            "url": str(result.get("url") or ""),
            "attr": str(toggled.get("attr") or ""),
            "back_to": str(toggled.get("from") or ""),
            "label": str((result.get("element") or {}).get("name") or "")[:60],
        }

    def _toggle_counts(self, page: Any, attribute: str) -> dict[str, int] | None:
        """화면 전체에서 표준 토글의 true/false 개수. 못 재면 None.

        정확한 대상을 다시 찾는 것이 우선이다. 이 값은 클릭이 대상 노드를 갈아 끼워
        ref와 이름까지 잃었을 때만 쓰는 보조 증거다. 프레임 하나라도 못 읽으면 일부
        화면만 센 수치를 성공 근거로 쓰지 않는다.
        """
        if attribute not in self._TOGGLE_ATTRS:
            return None
        frames = self._frames_of(page)
        if not frames:
            return None
        counts = {"true": 0, "false": 0}
        for frame in frames:
            try:
                for value in counts:
                    counts[value] += int(frame.locator(f'[{attribute}="{value}"]').count())
            except Exception:
                return None
        return counts

    def _undo_page(self, expected_url: str) -> Any:
        """되돌릴 ref가 만들어진 정확한 탭을 다시 얻는다.

        도구 호출 사이에는 사용자가 탭을 바꾸거나 워커가 ``self._page``를 잃을 수
        있다. 그렇다고 현재 탭에서 같은 ref를 누르면 전혀 다른 쓰기가 된다. 원래
        URL과 정확히 일치하는 열린 탭이 하나일 때만 재획득하고, 없거나 둘 이상이면
        추측하지 않는다. fragment는 같은 문서 안의 위치일 뿐이라 비교에서 제외한다.
        """
        current = self._current_page()
        if not expected_url:
            return current
        wanted = expected_url.split("#", 1)[0]
        current_url = str(getattr(current, "url", "") or "")
        if current_url.split("#", 1)[0] == wanted:
            return current

        matches: list[Any] = []
        context = getattr(self, "_context", None)
        try:
            pages = list(getattr(context, "pages", []) or [])
        except Exception:
            pages = []
        for candidate in pages:
            try:
                if candidate.is_closed():
                    continue
                candidate_url = str(getattr(candidate, "url", "") or "")
            except Exception:
                continue
            if candidate_url.split("#", 1)[0] == wanted:
                matches.append(candidate)

        if len(matches) > 1:
            raise RuntimeError(
                f"undo_toggle_ambiguous_page: 눌렀던 화면({expected_url[:70]})과 "
                f"같은 탭이 {len(matches)}개라 고르지 않았다"
            )
        if len(matches) == 1:
            page = matches[0]
            self._bring_to_front(page)
            self._page = page
            return page
        raise RuntimeError(
            f"undo_toggle_wrong_page: 눌렀던 화면({expected_url[:70]})이 아니라 "
            f"지금은 {current_url[:70]} 이고 원래 탭도 열려 있지 않다"
        )

    def _undo_toggle(self, handle: dict[str, Any]) -> dict[str, Any]:
        """같은 것을 한 번 더 누르고, **정말 돌아왔는지 확인한다.**

        확인이 핵심이다. 토글인 줄 알았는데 아니었으면 여기서 드러나고, 드러나면
        실적이 회수된다 — 되돌아갈 줄 알았는데 안 되는 것이 제일 나쁘다.
        """
        was = str(handle.get("url") or "")
        page = self._undo_page(was)
        ref = str(handle.get("ref") or "")
        attribute = str(handle.get("attr") or "")
        want = str(handle.get("back_to") or "")
        if attribute not in self._TOGGLE_ATTRS or want not in {"true", "false"}:
            raise RuntimeError(f"undo_toggle_invalid_handle:{attribute}={want}")
        locator = self._ref_locator(page, ref)
        before = self._toggle_state(locator)
        if before is None or before[0] != attribute:
            # 아직 누르지 않았다. 여기서는 평범한 실패가 맞고 재실행해도 mutation 은 없다.
            raise RuntimeError(f"undo_toggle_target_not_readable:{attribute}")
        if before[1] == want:
            # 사람이 먼저 원복했거나 늦게 도착한 offer. 다시 누르면 도로 켜진다.
            return {
                "action": "undo_toggle",
                "ref": ref,
                "attr": attribute,
                "now": want,
                "clicked": False,
                "verified": True,
                "verification": "already_returned",
            }
        counts_before = self._toggle_counts(page, attribute)
        locator.click(timeout=5000)
        page.wait_for_timeout(600)
        after = None
        recover_error = ""
        try:
            # Locator는 selector를 다시 해석하지만, selector의 근거인 data-jarvis-ref가
            # 교체된 노드와 함께 사라질 수 있다. `_ref_locator`를 다시 부르면 기존의
            # 이름 기반 복구 경로가 새 snapshot/ref를 발급한다.
            after = self._toggle_state(self._ref_locator(page, ref))
        except Exception as exc:
            recover_error = _clean(exc, 240)
        if after and after[0] == attribute and after[1] == want:
            return {
                "action": "undo_toggle",
                "ref": ref,
                "attr": attribute,
                "now": want,
                "clicked": True,
                "verified": True,
                "verification": "target",
            }
        if after and after[0] == attribute and after[1] != want:
            # 새로 찾은 **그 대상**이 반대 상태라고 읽혔다. 확인 불능이 아니라 확인된 실패다.
            raise RuntimeError(
                f"undo_toggle_did_not_return: {attribute} 가 {want} 로 안 돌아왔다"
                f"(지금 {after[1]})"
            )
        counts_after = self._toggle_counts(page, attribute)
        left = before[1]
        if (
            counts_before is not None
            and counts_after is not None
            and counts_after[want] == counts_before[want] + 1
            and counts_after[left] == counts_before[left] - 1
        ):
            return {
                "action": "undo_toggle",
                "ref": ref,
                "attr": attribute,
                "now": want,
                "clicked": True,
                "verified": True,
                "verification": "aggregate",
                "counts_before": counts_before,
                "counts_after": counts_after,
            }
        # 여기까지 왔으면 클릭은 이미 딱 한 번 실행됐다. 실패 예외를 내면 장부가
        # `failed`가 되고 상위가 재시도할 수 있다. 성공으로 꾸미지도 않고, offer를
        # 다시 살리지도 않는 제3상태로 게이트웨이에 넘긴다.
        raise UndoUnverified(
            {
                "action": "undo_toggle",
                "ref": ref,
                "attr": attribute,
                "wanted": want,
                "clicked": True,
                "verified": False,
                "verification": "unverified",
                "counts_before": counts_before,
                "counts_after": counts_after,
                "recovery_error": recover_error,
            },
            "undo_toggle_clicked_but_result_unverified",
        )

    def _click_confirmed(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """되돌릴 수 없는 클릭. 게이트웨이가 화면 승인을 받은 뒤에만 여기까지 온다.

        일반 클릭과 코드가 같고 차이는 등록된 위험도(L2)뿐이다. 굳이 도구를 나눈 이유:
        승인은 도구 단위로 걸리기 때문에, 같은 도구로 결제도 하고 스크롤도 하면
        모든 클릭마다 승인창이 뜨거나 아무 클릭도 승인을 안 받거나 둘 중 하나가 된다.
        """
        return self._click(page, arguments, approved=True)

    # ---- 폼 작성 ---------------------------------------------------------
    #
    # 한 칸씩 채우면 칸 수만큼 모델 왕복이 생기고, 그 사이 페이지가 바뀌면 ref 가
    # 낡는다. 여기서 중요한 건 속도보다 **반쯤 채워진 폼을 반쯤 채워졌다고 말하는
    # 것**이다 -- 어느 칸까지 들어갔는지 모르면 사람이 화면을 열어 처음부터 확인해야 한다.

    def _fill_form(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        fields = list(arguments.get("fields") or [])
        if not fields:
            raise ValueError("fields_required")
        filled: list[dict[str, Any]] = []
        for index, field in enumerate(fields):
            ref = str((field or {}).get("ref") or "")
            value = str((field or {}).get("value") or "")[:4000]
            try:
                done = self._fill(page, {"ref": ref, "value": value})
            except Exception as exc:
                # 여기서 멈춘다. 남은 칸을 계속 밀어넣으면 어디서 어긋났는지가
                # 사라지고, 폼은 사람이 손대야 하는 상태가 된다.
                raise RuntimeError(
                    f"fill_form_stopped_at:{index + 1}/{len(fields)}:{ref}:{_clean(exc, 200)}"
                    f" — 앞의 {len(filled)}칸은 이미 채워져 있습니다."
                ) from exc
            # 어느 칸에 넣었는지 이름으로 돌려준다(한 칸 채우기와 같다).
            filled.append({"ref": ref, "value_length": len(value),
                           **({"field": done["field"]} if isinstance(done, dict) and done.get("field") else {})})
        return self._evidence("form_filled", fields=filled, field_count=len(filled))

    def _select_option(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """네이티브 <select> 전용.

        커스텀 드롭다운(div 로 만든 것)은 여기서 안 된다 -- 그건 클릭 두 번이라
        browser_click 으로 열고 목록에서 고르는 게 맞다. 조용히 실패하지 않도록
        무엇이 안 됐는지 이름을 대고 끝낸다.
        """
        ref = str(arguments.get("ref") or "")
        locator = self._ref_locator(page, ref)
        tag = _clean(locator.evaluate("el => el.tagName.toLowerCase()"), 20)
        if tag != "select":
            raise RuntimeError(
                f"not_a_select:{tag or '(알 수 없음)'}"
                " — 커스텀 드롭다운은 browser_click 으로 열고 항목을 고르세요."
            )
        label = _clean(arguments.get("label"), 200)
        value = _clean(arguments.get("value"), 200)
        if not label and not value:
            raise ValueError("label_or_value_required")
        self._show_visual(page, "항목 선택", locator=locator)
        chosen = locator.select_option(label=label) if label else locator.select_option(value=value)
        selected = list(chosen or [])
        if not selected:
            raise RuntimeError("option_selection_unverified:no_selected_value")
        # ★ 고른 뒤 **화면에 보이는 이름**을 되읽는다(2026-10-03) — 사이트가 바꾸면(다시 그리기·막기) 다른 값이 남는다.
        try:
            shown = _clean(locator.evaluate("el => (el.selectedOptions[0] || {}).label || ''"), 120)
        except Exception:
            shown = ""
        evidence = self._evidence(
            "option_selected",
            ref=ref,
            selected=selected,
            requested_label=label,
            requested_value=value,
            verified=True,
        )
        if shown:
            evidence["selected_label"] = shown
            if label and shown.strip().lower() != label.strip().lower():
                evidence["verified"] = False
                evidence["next"] = f"고른 뒤 상자에 「{shown}」가 보인다 — 「{label}」가 아니다. browser_snapshot 으로 다시 확인하라."
        return evidence

    def _file_upload(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """파일 첨부. 허용된 폴더 안의 파일만.

        업로드는 이 PC의 파일을 바깥으로 내보내는 동작이라 다른 도구와 급이 다르다.
        그래서 두 겹으로 잠근다: 게이트웨이에서 화면 승인(L2), 그리고 여기서 경로가
        허용된 뿌리 안인지. 승인만으로는 부족하다 -- 승인 화면에 뜬 경로가 무엇을
        가리키는지는 사람이 한눈에 판단하기 어렵다.
        """
        ref = str(arguments.get("ref") or "")
        raw_paths = [str(p) for p in (arguments.get("paths") or []) if str(p).strip()]
        if not raw_paths:
            raise ValueError("paths_required")
        if len(raw_paths) > 6:
            raise ValueError("too_many_files:최대 6개")
        roots = [Path(r).resolve() for r in self.config.browser_upload_allowed_roots]
        resolved: list[str] = []
        for raw in raw_paths:
            path = Path(raw).expanduser()
            try:
                path = path.resolve(strict=True)
            except OSError as exc:
                raise RuntimeError(f"file_not_found:{raw}") from exc
            if not any(path == root or root in path.parents for root in roots):
                raise RuntimeError(
                    f"upload_path_not_allowed:{path}"
                    f" — 허용된 폴더: {', '.join(str(r) for r in roots) or '(없음)'}"
                )
            if path.stat().st_size > int(self.config.browser_upload_max_bytes):
                raise RuntimeError(f"file_too_large:{path.name}")
            resolved.append(str(path))
        locator = self._ref_locator(page, ref)
        self._show_visual(page, "파일 첨부 중", locator=locator)
        via = "input"
        try:
            locator.set_input_files(resolved)
        except Exception as direct:  # noqa: BLE001 - 파일 칸이 아닌 번호일 수 있다. 아래에서 사람이 하는 길로 다시 해 본다
            # ★ 2026-10-07 폼 벤치 과제 I(3판 중 0판): 흔한 폼은 파일 칸(`<input type=file>`)을 숨겨 두고 「파일 선택」 **단추**가 그것을 연다.
            #   숨은 칸은 목록에 안 나오니 모델이 줄 수 있는 번호는 단추뿐인데, 단추에는 파일을 넣을 수 없어 「Node is not an
            #   HTMLInputElement」로 끝났다. 모델은 「이 사이트는 파일 올리기가 안 된다」고 답했다(도구가 그렇게 말했으니까).
            #   사람이 하는 대로 한다: 그 단추를 누르고, **뜨는 파일 선택 창**에 파일을 넣는다. 창은 브라우저가 가로채 주므로 화면에 뜨지 않는다.
            #   눌러도 창이 안 뜨면 파일을 여는 단추가 아니다 — 그때는 무엇을 줘야 하는지 말한다(원래 오류도 같이).
            try:
                with page.expect_file_chooser(timeout=4000) as chooser_info:
                    locator.click()
                chooser_info.value.set_files(resolved)
            except Exception as opened:  # noqa: BLE001
                raise RuntimeError(
                    "not_a_file_control — 이 번호의 요소에는 파일을 넣을 수 없고, 눌러도 파일 선택 창이 뜨지 않았다. "
                    "파일 칸이나 그것을 여는 단추(「파일 선택」·「찾아보기」·「첨부」)의 번호를 줘라. "
                    f"(직접 넣기: {str(direct).splitlines()[0][:120]} · 눌러 보기: {str(opened).splitlines()[0][:120]})"
                ) from opened
            via = "chooser"
        return self._evidence(
            "files_uploaded",
            ref=ref,
            files=[Path(p).name for p in resolved],
            file_count=len(resolved),
            **({"via": "button"} if via == "chooser" else {}),
        )

    def _handle_dialog(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """다음에 뜰 브라우저 확인창(alert/confirm/prompt)에 어떻게 답할지 정한다.

        **미리** 정하는 이유는 교착 때문이다: 확인창이 떠 있는 동안 그것을 띄운
        클릭이 끝나지 않고, 브라우저 작업은 한 스레드에서 직렬로 돌기 때문에 뒤이어
        답하는 명령은 영영 실행되지 않는다(실브라우저에서 실측하고 되돌린 설계다).

        그래서 순서가 반대다: 누르기 **전에** 이 도구로 허가를 두고, 그 다음에 누른다.
        허가는 한 번 쓰면 사라진다. 아무것도 두지 않으면 취소가 기본이다.

        페이지 안에 그려진 모달은 이게 아니라 browser_dismiss_dialog 가 처리한다.
        """
        del page
        accept = bool(arguments.get("accept"))
        self._dialog_policy = {
            "accept": accept,
            "prompt_text": str(arguments.get("prompt_text") or "")[:500],
        }
        return self._evidence(
            "dialog_policy_set",
            accept=accept,
            note=(
                "다음에 뜨는 확인창 한 번에만 적용됩니다."
                if accept
                else "다음 확인창은 취소로 답합니다."
            ),
            last_dialog=dict(self._last_dialog or {}),
        )

    def _press(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        ref = str(arguments.get("ref") or "")
        key = _clean(arguments.get("key"), 50)
        if not key:
            raise ValueError("key_required")
        locator = self._ref_locator(page, ref)
        if self.config.browser_read_only and key.lower() in {"enter", "numpadenter"}:
            # 검색칸의 Enter 는 찾아보는 것뿐이다 — 다른 칸(신청서·댓글)의 Enter 는 여전히 막는다.
            try:
                search_field = bool(locator.evaluate(_SEARCH_FIELD_JS))
            except Exception:  # noqa: BLE001 — 모르면 안전한 쪽(막기)
                search_field = False
            if not search_field:
                raise RuntimeError("read_only_enter_blocked")
        locator.press(key)
        return self._evidence("pressed", ref=ref, key=key)

    def _scroll(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        amount = max(-3000, min(int(arguments.get("amount") or 700), 3000))
        page.mouse.wheel(0, amount)
        return self._evidence("scrolled", amount=amount)

    def _load_more_tool(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """지금 목록을 더 불러온다(무한스크롤·더보기). 그리고 순위를 다시 매긴다."""
        rounds = max(1, min(int(arguments.get("rounds") or 3), 8))
        limit = max(1, min(int(arguments.get("limit") or 20), 30))
        loaded = self._load_more(page, rounds=rounds) or {}
        # 목록을 더 불러오는 자리에서도 날짜를 맞춘다 — 검색을 안 거치고 클릭으로
        # 목록에 도착한 판이 있어서, 여기가 두 번째 기회다.
        date_fix = self._apply_requested_dates_here(page)
        results = self._collect_results(page, limit=limit)
        if results or not self._last_results:
            self._last_results = results
            self._remember_results_origin(page)
        # 손으로 검색해서 여기까지 온 판도 있다 — 그 주소를 여기서 배운다.
        self._learn_search_url(page, len(results))
        return self._evidence(
            "loaded_more",
            **{k: v for k, v in self._date_rewrite_evidence(date_fix).items() if k != "date_instruction"},
            results=results,
            result_count=len(results),
            **loaded,
            instruction=(
                # 여기도 "목록 줄 값을 그대로 써라"가 있다. 날짜를 요청한 판에서는
                # 그 말이 틀리므로 앞에 세워 바로잡는다.
                (stay_note + " " if (stay_note := self._stay_note_for_list(page, applied=date_fix)) else "")
                + f"★ 목록을 더 불러왔다({len(results)}건). **목록 줄에 보이는 값은 그대로"
                " 근거로 써라** — 여러 건을 비교하라는 요구는 상세를 안 열어도 여기서 채운다."
                " 목록에 없는 값이 필요할 때만 browser_open_result 에 rank 를 줘서 들어가라."
                " 더 안 늘어났으면 그게 이 목록의 끝이다 — 같은 도구를"
                " 되풀이하지 말고 읽기로 넘어가라."
            ),
        )

    def _tabs(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        del page, arguments
        pages = [item for item in self._context.pages if not item.is_closed()]
        tabs = []
        for index, item in enumerate(pages):
            try:
                tabs.append({"index": index, "url": item.url, "title": _clean(item.title(), 200)})
            except Exception:
                continue
        return self._evidence("tabs", tabs=tabs, active_index=pages.index(self._page))

    def _switch_tab(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        del page
        pages = [item for item in self._context.pages if not item.is_closed()]
        index = int(arguments.get("index", -1))
        if index < 0 or index >= len(pages):
            raise ValueError("tab_index_out_of_range")
        if pages[index] is self._page:
            # 이미 그 탭이다. 실패로 만들면 모델은 탭 충돌로 읽고 사람에게 정리를
            # 요구한다. 상태 설정형 호출은 같은 상태를 다시 요구해도 성공이어야 한다.
            return self._evidence("tab_already_active", index=index, already_active=True)
        refused = self._another_site_tab(pages[index])
        if refused:
            raise ValueError(refused)
        self._page = pages[index]
        self._maximize_window(self._page)
        self._bring_to_front(self._page)
        return self._evidence("tab_switched", index=index)

    #: 뒤로 가기에서 이동이 **시작되는 것**을 기다리는 시간(ms) · 그걸 놓친 뒤 주소가 바뀌는지 지켜보는 시간(초). 합쳐 8초.
    _BACK_COMMIT_MS = 2500
    _BACK_URL_WATCH_SEC = 5.5

    #: 이동이 시작됐다고 돌아왔는데 주소가 아직 그대로일 때 더 지켜보는 시간.
    _BACK_URL_SETTLE_SEC = 1.5

    @staticmethod
    def _wait_document_ready(page: Any, timeout_sec: float = 5.0) -> bool:
        """문서가 읽을 수 있는 상태인지 **직접 묻는다** — 「읽기 끝」 신호를 기다리지 않는다.

        ★ 2026-10-05 아침 실측(직접 띄운 크롬에 붙은 조건 · GitHub·해커뉴스·arXiv 각 5번): 뒤로 가면 주소는 0.1초 만에 바뀌는데
          `wait_for_load_state("domcontentloaded")` 가 **15번 전부 5초를 꽉 채웠다.** 실제 크롬은 뒤로 갈 때 저장해 둔 화면을 그대로
          되살리고, 그때는 읽기 끝 신호가 다시 오지 않는다. 뒤로 가기가 5초대였던 이유가 이 한 줄이었다. 상태를 물으면 0.0~0.1초.
        """
        deadline = time.monotonic() + timeout_sec
        while True:
            try:
                if str(page.evaluate("() => document.readyState")) in ("interactive", "complete"):
                    return True
            except Exception:
                pass  # 문서가 갈리는 중 — 다시 묻는다
            if time.monotonic() >= deadline:
                return False
            try:
                page.wait_for_timeout(100)
            except Exception:
                return False

    def _back(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """뒤로 간다. 목록으로 돌아가려는 것이면 **더 나은 길을 알려 준다.**

        ★ 2026-08-14 실측(쿠팡 20걸음 판): 상세를 읽고 목록으로 가려고
        `browser_back` 을 **두 번 연달아** 부른 뒤, 방금 본 rank 3 을 또 열었다.
        네 걸음이 제자리였다. 그 앞 판에서는 `go_back` 이 30초 타임아웃 나면서
        목록을 통째로 잃었다.

        프롬프트에는 이미 "목록 화면에서 뒤로 가지 마라"가 있다(그리고 안 지켜졌다).
        그래서 **도구가 그 자리에서** 말한다 — 오늘 하루 배운 방식이다.
        """
        del arguments
        # ★ **기다림에 상한을 건다** (2026-08-15). 예전에는 `go_back` 이 기본 30초를
        # 다 쓰고 타임아웃 나면서 그 판이 통째로 끝났다. 뒤로 가기는 **되돌아오는
        # 길이지 목적이 아니다** — 오래 걸리면 그 길로 안 가면 그만이다.
        #
        # 못 갔다고 실패로 던지지도 않는다. `_last_results` 는 워커에 남아 있으므로
        # (판이 바뀔 때만 `forget_results` 로 지운다) 뒤로 못 갔어도 rank 로 다음
        # 자료를 여는 길은 그대로 살아 있다. 여기서 예외를 던지면 그 길까지 닫는다.
        # ★ **돌아갔는지는 주소로 본다** (2026-10-05 AWS 영어 윈도우 · 이 PC 운영 기록 26번 중 5번).
        #   GitHub 처럼 화면을 스스로 바꿔 끼우는 사이트는 뒤로 가도 문서 이벤트가 새로 안 온다. `go_back` 은 그 이벤트를
        #   8초 기다리다 시간 초과가 났고, 실제로는 **이미 돌아가 있는데** 「뒤로 가기가 안 끝나 그만뒀다(화면은 그대로일 수
        #   있다)」고 했다 — 느리고(8.1초) 틀린 말이었다. 이동이 시작된 것만 짧게 기다리고, 놓쳤으면 주소가 바뀌었는지 본다.
        try:
            url_before = str(page.url or "")
        except Exception:
            url_before = ""
        committed = True
        try:
            page.go_back(wait_until="commit", timeout=self._BACK_COMMIT_MS)
        except Exception:
            committed = False
        # ★ 돌아갔는지는 **늘 주소로** 본다 (2026-10-05 아침, 이 PC 운영 브라우저). 이동이 시작됐다고 돌아온 판 하나가
        #   「went_back」이라면서 주소는 상세 그대로였다. 앞 주소를 알면 바뀔 때까지 본다 — 이동이 시작됐으면 짧게, 놓쳤으면 길게.
        went_back = committed
        if url_before:
            went_back = False
            deadline = time.monotonic() + (self._BACK_URL_SETTLE_SEC if committed else self._BACK_URL_WATCH_SEC)
            while True:
                try:
                    if str(page.url or "") != url_before:
                        went_back = True
                        break
                    if time.monotonic() >= deadline:
                        break
                    page.wait_for_timeout(100)
                except Exception:
                    break
        if went_back:
            self._wait_document_ready(page)
        result = self._evidence("went_back" if went_back else "back_timed_out")
        if not went_back:
            result["instruction"] = (
                "★ 뒤로 가기가 8초 안에 안 끝나 **그만뒀다**(화면은 그대로일 수 있다). "
                "이건 고장이 아니라 이 사이트가 느린 것이고, 순위는 아직 살아 있다 — "
                "browser_open_result 에 rank 를 주면 목록을 안 거치고 바로 간다. "
                "지금 화면이 어디인지 모르겠으면 browser_read 로 한 번 확인해라."
            )
        remaining = [item["rank"] for item in self._last_results if not item.get("visited")]
        if remaining:
            result["remaining"] = remaining
            result["instruction"] = (
                "★ 다음 자료를 보려고 뒤로 온 것이라면 그럴 필요가 없다. "
                f"browser_open_result 에 안 읽은 rank 를 주면 바로 간다({remaining[:5]}). "
                "뒤로 가기는 목록을 잃는 가장 빠른 길이다 — 이미 한 번 30초 타임아웃으로 "
                "순위를 통째로 날린 적이 있다."
            )
        return result

    def _wait(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        milliseconds = max(100, min(int(arguments.get("milliseconds") or 1000), 10000))
        page.wait_for_timeout(milliseconds)
        return self._evidence("waited", milliseconds=milliseconds)

    # ---- Naver Blog: internal Playwright steps, driven only by NaverBlogTools ----
    #
    # DOM selectors below are a best-effort match of the current SmartEditor ONE
    # markup and have not been verified against a live blog.naver.com session
    # (no real-account testing was performed this pass). Treat them as the
    # first thing to check if fill/save/publish behave unexpectedly live.

    def _naver_blog_check_intervention(self, page: Any) -> None:
        # The URL first, because being bounced to the login host is the one
        # signal that is unambiguous. The body-text markers below miss it
        # entirely: Naver's login page says "NAVER 로그인", "아이디 찾기" --
        # none of the phrases we look for. Measured live, and the result was a
        # title-locator timeout that blamed the editor for a session problem
        # and sent the whole investigation the wrong way.
        try:
            url = str(page.url or "")
        except Exception:
            url = ""
        if _NAVER_LOGIN_HOST in url:
            raise RuntimeError(
                "naver_blog_login_required: 브라우저에 네이버 로그인이 필요합니다. "
                "로그인할 때 '로그인 상태 유지'를 켜 주세요 — 끄면 세션 쿠키라 "
                "브라우저가 닫히거나 손자리가 재시작되는 순간 로그인이 풀립니다."
            )
        try:
            text = _clean(page.locator("body").inner_text(timeout=1500), 4000).lower()
        except Exception:
            return
        if any(marker.lower() in text for marker in _NAVER_INTERVENTION_MARKERS):
            raise RuntimeError("naver_blog_manual_intervention_required")

    @staticmethod
    def _locator_text(locator: Any, limit: int = 300) -> str:
        try:
            return _clean(locator.inner_text(timeout=1200), limit)
        except Exception:
            return ""

    @classmethod
    def _button_label(cls, button: Any) -> str:
        """버튼의 이름. 글자가 없으면 **접근성 이름**에서 가져온다.

        ★ 2026-08-12 실측(잡코리아). 팝업은 정확히 감지했는데
        `browser_popup_blocking:AI가 내 조건에 딱 맞는 공고만 먼저 보여줘요 다음`
        으로 멈췄다. 후보 버튼이 "다음" 하나뿐이라 **부정 버튼이 없다**고 본 것이다.
        실제 화면에는 글자 없는 **X 닫기**가 있었는데, 버튼을 글자로만 세는 바람에
        후보에 아예 안 들어왔다.

        어제 스냅샷에서 고친 "이름 없는 아이콘 버튼" 문제가 팝업 감지기에도 똑같이
        있었다 — 같은 병이 두 곳에 있었던 셈이다.

        `aria-label`·`title` 은 사이트가 **스스로 붙인 이름**이라 짐작이 아니다.
        여기서 '닫기'가 나오면 그건 닫기 버튼이 맞다.
        """
        label = cls._locator_text(button, 40)
        if label:
            return label
        for attribute in ("aria-label", "title", "alt", "data-testid"):
            try:
                value = _clean(button.get_attribute(attribute) or "", 40)
            except Exception:
                continue
            if value:
                return value
        return ""

    @staticmethod
    def _visible(locator: Any) -> bool:
        try:
            return bool(locator.is_visible())
        except Exception:
            return False

    def _naver_blog_dismiss_popups(self, page: Any, frame: Any = None, *, rounds: int = 3) -> list[dict[str, Any]]:
        """Clear whatever modal is covering the editor, before touching it.

        Playwright cannot work this out on its own: the target element really
        is visible, enabled and stable, so `click()` just keeps retrying its
        actionability check against a dim layer that will never go away, and
        20 seconds later reports a timeout that reads like a bad selector.
        That is exactly how the 2026-08-03 임시저장 attempt burned three tries
        on a correct selector.

        Modals are found **structurally and across every frame**, not by class
        name and not inside one hardcoded iframe. Both of those bit us: the
        2026-08-05 attempt hit "작성 중인 글이 있습니다" -- Naver's draft-restore
        confirm -- which sits in the *top* document, while this only searched
        `iframe#mainFrame`, so nothing was found and the whole page read as
        zero elements. `_SE_POPUP` is still tried first because it is precise
        when it matches; the structural probe is what makes a miss survivable.

        `frame` is accepted and ignored, so existing callers keep working.
        """
        del frame
        return self._dismiss_dialogs(page, rounds=rounds, prefix="naver_blog")

    def _dismiss_dialogs(
        self, page: Any, *, rounds: int = 3, prefix: str = "browser"
    ) -> list[dict[str, Any]]:
        """Clear whatever modal is covering the page. Site-agnostic.

        Nothing below knows a class name: a dialog is found by behaviour (see
        `_MODAL_PROBE_JS`), and the rule for answering it is fixed regardless of
        site -- only a negative button is ever pressed, an alert with a single
        button is acknowledged, and anything else stops loudly with its wording
        quoted. That rule is what keeps a dismisser from publishing something.
        """
        dismissed: list[dict[str, Any]] = []
        for _ in range(max(1, rounds)):
            popup = self._first_visible_popup(page)
            if popup is None:
                return dismissed
            record = self._dismiss_one_popup(popup)
            if not record.get("dismissed") and self._escape_closes_popup(page):
                # ★ 2026-09-26 A/B 벤치(네이버 날씨): 모델이 연 「지역 설정」 창에는 닫기·취소 같은 부정 버튼이 없어서
                #   이 규칙이 「가로막는 팝업」으로 멈췄고, 판은 「닫기(X)를 눌러 주세요」라며 사람에게 넘겼다.
                #   Esc 는 무엇도 제출하지 않는다 — 부정 버튼 다음으로 안전한 닫기다.
                record.update(dismissed=True, button="Esc")
            dismissed.append(record)
            if not record.get("dismissed"):
                raise RuntimeError(
                    f"{prefix}_popup_blocking:"
                    + (record.get("text") or "(문구 없음)")[:200]
                    + " — 닫기 버튼도 Esc 도 안 먹는 창이다. 네가 방금 열어 쓰려던 창이면 닫지 말고 browser_snapshot 을"
                    " 다시 찍어 **그 창 안의** 번호표를 눌러라(창 뒤의 옛 번호표는 가려져 안 눌린다)."
                )
            page.wait_for_timeout(350)
        if self._first_visible_popup(page) is not None:
            # Carry what was actually pressed. Bare "persists" cannot tell
            # "we clicked 취소 and it ignored us" apart from "we never found a
            # button", and those need opposite fixes.
            attempts = "; ".join(
                f"{r.get('button') or '(버튼없음)'}"
                f"{'' if r.get('dismissed') else '[클릭실패]'}"
                f"{'' if not r.get('buttons') else ' 후보=' + ','.join(r['buttons'])}"
                for r in dismissed
            )
            raise RuntimeError(
                f"{prefix}_popup_persists_after_dismiss:{attempts or '(시도 없음)'}"
            )
        return dismissed

    def _frames_of(self, page: Any) -> list[Any]:
        """Every frame of the page, top document included.

        Falls back to the old single-iframe view when the object does not
        expose frames -- which is what the offline tests hand in.
        """
        frames = getattr(page, "frames", None)
        if frames:
            # ★ 2026-09-23: **아직 문서가 없는 하위 프레임은 뺀다.** 다나와 목록의 광고 iframe 네 개가 새 크롬 프로필에서
            #   주소가 빈 문자열(`''`)인 채 광고 서버 이동이 끝나지 않았고, 그 프레임에 `frame.evaluate` 를 하면 Playwright 가
            #   실행 환경이 생기기를 **끝없이** 기다린다(evaluate 에는 시간 제한이 없다). browser_extract 가 매번 180초
            #   시간 초과로 죽었다(평소 프로필은 광고가 달라 2.2초). 이동을 시작만 한 프레임에는 읽을 글이 아직 없으니
            #   빼도 잃는 것이 없다. 다만 주소가 빈 프레임이 다 그런 것은 아니다 — `src` 없이 스크립트가 채운 편집기 iframe 은
            #   읽을 수 있다(처음에 전부 뺐다가 시험 53개가 깨졌다). 그래서 **바깥 `src` 로 가다 멈춘 것**만 뺀다
            #   (`_navigation_never_committed`).
            #   이 목록을 26곳이 쓰므로 여기 한 자리에서 막는다.
            main = getattr(page, "main_frame", None)
            kept = []
            for frame in frames:
                if main is not None and frame is main:
                    kept.append(frame)
                    continue
                detached = getattr(frame, "is_detached", None)
                if callable(detached):
                    try:
                        if detached():
                            continue
                    except Exception:
                        continue
                if getattr(frame, "url", None) == "" and self._navigation_never_committed(frame):
                    continue
                kept.append(frame)
            return kept
        try:
            return [page.frame_locator("iframe#mainFrame")]
        except Exception:
            return []

    @staticmethod
    def _navigation_never_committed(frame: Any) -> bool:
        """주소가 빈 프레임 중 **바깥 주소로 가다 멈춘 것**인가.

        ★ 주소가 빈 프레임이 다 같지 않다(2026-09-23, 처음엔 전부 뺐다가 시험 53개가 깨졌다).
          · `src` 없이 스크립트가 내용을 채운 iframe(편집기·위젯) — 주소는 비어도 **읽을 수 있다.** 남긴다.
          · `src` 가 바깥 주소인데 이동이 안 끝난 iframe(다나와 광고) — 실행 환경이 안 생겨 evaluate 가 끝없이 멈춘다. 뺀다.
          부모 문서에서 iframe 요소의 `src` 를 읽어 가른다(부모는 실행 환경이 있어 멈추지 않는다). 못 읽으면 남긴다(예전 동작).
        """
        try:
            element = frame.frame_element()
            src = str(element.get_attribute("src") or "").strip().lower()
        except Exception:
            return False
        return bool(src) and not src.startswith(("about:", "javascript:", "data:", "blob:"))

    def _first_visible_popup(self, page: Any) -> Any:
        """The topmost modal anywhere on the page, or None.

        Known selectors first, then a structural probe. The probe marks
        candidates with a data attribute from inside the page and hands back a
        locator, so Playwright still applies its own visibility and
        actionability checks -- nothing is clicked by coordinate.
        """
        for frame in self._frames_of(page):
            try:
                popups = frame.locator(_SE_POPUP)
                count = min(int(popups.count()), 8)
            except Exception:
                count = 0
            for index in range(count):
                popup = popups.nth(index)
                if self._visible(popup):
                    return popup
        for frame in self._frames_of(page):
            popup = self._probe_modal(frame)
            if popup is not None:
                return popup
        return None

    def _probe_modal(self, frame: Any) -> Any:
        """Find a modal by behaviour: it is what owns the middle of the screen.

        Nothing here knows what SmartEditor's classes are called. A dialog is
        whatever sits on top at the viewport centre, is positioned, and holds
        at least one short-labelled button -- which is also true of every other
        site's dialogs, so this keeps working when Naver renames things.
        """
        try:
            marked = frame.evaluate(_MODAL_PROBE_JS)
        except Exception:
            return None
        if not marked:
            return None
        try:
            candidate = frame.locator(f"[{_MODAL_MARK}]").first
        except Exception:
            return None
        return candidate if self._visible(candidate) else None

    def _escape_closes_popup(self, page: Any) -> bool:
        """Esc 를 한 번 눌러 창이 사라지는가. 누를 수 없거나 그대로면 False."""
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:  # noqa: BLE001 — 키를 못 누르면 원래 규칙(멈추고 문구 인용)으로
            return False
        return self._first_visible_popup(page) is None

    def _dismiss_one_popup(self, popup: Any) -> dict[str, Any]:
        text = self._locator_text(popup, 400)
        classes = ""
        try:
            classes = _clean(popup.get_attribute("class") or "", 200)
        except Exception:
            pass
        try:
            classes += " " + _clean(popup.get_attribute("data-name") or "", 200)
        except Exception:
            pass
        try:
            buttons = popup.locator(_SE_POPUP_BUTTON)
            count = min(int(buttons.count()), 8)
        except Exception:
            count = 0
        labels: list[tuple[int, str]] = []
        for index in range(count):
            button = buttons.nth(index)
            if not self._visible(button):
                continue
            label = self._button_label(button)
            # Skip wrappers. `[class*='button']` also matches the row that
            # *contains* the buttons, whose text is every label run together --
            # measured live as a single "취소 확인" entry, which was then
            # clicked (hitting the gap between the real buttons) three times
            # while the dialog sat there. A real button carries one label.
            if self._encloses_other_buttons(button):
                continue
            labels.append((index, label))

        # Two or more choices means it is asking a question; one means it is
        # only telling us something. That is a property of the dialog itself,
        # so it survives a rename -- unlike `se-popup-alert-confirm`, which is
        # still consulted because it is precise when it happens to be there.
        is_confirm = _SE_CONFIRM_CLASS in classes or len(labels) >= 2
        record: dict[str, Any] = {
            "text": text,
            "confirm": is_confirm,
            "dismissed": False,
            "button": "",
        }

        chosen = next(
            (
                (index, label)
                for index, label in labels
                if any(word in label.lower() for word in _SE_DISMISS_LABELS)
            ),
            None,
        )
        if chosen is None and not is_confirm:
            # A plain alert only reports something; acknowledging it is the only
            # way out and cannot answer a question on the user's behalf.
            chosen = next(
                (
                    (index, label)
                    for index, label in labels
                    if any(word in label.lower() for word in _SE_ACK_LABELS)
                ),
                None,
            )
        if chosen is None:
            record["buttons"] = [label for _, label in labels]
            return record
        index, label = chosen
        try:
            buttons.nth(index).click(timeout=4000)
        except Exception as exc:
            record["error"] = _clean(exc, 200)
            return record
        record["dismissed"] = True
        record["button"] = label
        return record

    def _first_present(self, frame: Any, *selectors: str, what: str, wait_ms: int = 0) -> Any:
        """The first selector that actually matches something on this page.

        SmartEditor's markup differs between an empty draft and one with
        content, so a single selector is a guess about which state we are in.
        Trying them in order keeps the precise one first and the structural
        fallback last, and failing here names every selector that missed --
        which is the information needed to fix it, unlike a click timeout.

        `count()` 는 **기다리지 않는다** — 0 이면 그 순간 0 이다. 아직 그려지는 중인
        화면에 쓰면 "셀렉터가 틀렸다"와 구별되지 않는 실패가 나오고, 실제로 그렇게
        읽혔다(2026-08-05). 기본값 0 은 예전 그대로라 이미 다 뜬 화면에서는 값이 같다.
        """
        deadline = time.monotonic() + max(0, wait_ms) / 1000
        while True:
            for selector in selectors:
                try:
                    if int(frame.locator(selector).count()) > 0:
                        return frame.locator(selector).first
                except Exception:
                    continue
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        raise RuntimeError(
            f"naver_blog_element_missing:{what}:" + " | ".join(selectors)
        )

    def _encloses_other_buttons(self, locator: Any) -> bool:
        """Is this a wrapper around buttons rather than a button itself?

        Asked of the element in the page, because the answer is structural: a
        row that holds 취소 and 확인 matches the same permissive selector the
        buttons do, and clicking it lands between them.
        """
        try:
            return bool(locator.evaluate(
                f"el => el.querySelectorAll(\"{_SE_POPUP_BUTTON}\").length > 0"
            ))
        except Exception:
            # The offline fakes return their blocker string here. Anything
            # non-boolean must not be read as "this is a wrapper", or every
            # button gets skipped and no dialog is ever answered.
            return False

    def _clear_blocker(self, page: Any, locator: Any, *, timeout: float) -> bool:
        """닫기 버튼 없는 가림막을 사람처럼 치우고 다시 누른다. 눌렀으면 True."""
        try:
            relation = str(locator.evaluate(_BLOCKER_RELATION_JS) or "")
        except Exception:
            return False
        try:
            if relation == "same_control":
                # 겉 칸이 진짜 칸의 얼굴이다 — 그 자리를 그대로 누른다(맨 위 요소, 곧 겉 칸이 받는다).
                locator.click(timeout=timeout, force=True)
                return True
            if relation == "backdrop":
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                try:
                    locator.click(timeout=min(timeout, 3000))
                    return True
                except Exception:
                    pass
                # Esc 로 안 닫히면 뒷막을 누른다(바깥 누르기 = 닫기). 그 자리의 맨 위가 뒷막이라 뒷막이 받는다.
                locator.click(timeout=min(timeout, 3000), force=True)
                page.wait_for_timeout(300)
                locator.click(timeout=min(timeout, 3000))
                return True
        except Exception:
            return False
        return False

    @staticmethod
    def _intercepting_element(locator: Any) -> str:
        """Describe whatever actually owns the click point, from inside the
        element's own document so iframe coordinates line up."""
        try:
            return _clean(
                locator.evaluate(
                    """el => {
                      const rect = el.getBoundingClientRect();
                      const doc = el.ownerDocument;
                      const top = doc.elementFromPoint(
                        rect.left + rect.width / 2, rect.top + rect.height / 2);
                      if (!top || top === el || el.contains(top)) return '';
                      const parts = [top.tagName.toLowerCase()];
                      // 가리는 것이 누르려던 요소의 **조상**이면 표시한다 — 조상의 덧씌움(::before/::after)이 클릭을 받는 모양이다.
                      if (top.contains(el)) parts.unshift('<조상>');
                      if (top.id) parts.push('#' + top.id);
                      const cls = typeof top.className === 'string' ? top.className.trim() : '';
                      if (cls) parts.push('.' + cls.split(/\\s+/).join('.'));
                      const layer = top.closest('[data-group], .se-popup');
                      if (layer) {
                        const name = layer.getAttribute('data-name')
                          || layer.getAttribute('data-group') || '';
                        if (name) parts.push('<' + name + '>');
                      }
                      const text = ((layer || top).innerText || '').replace(/\\s+/g, ' ').trim();
                      return parts.join('') + (text ? ' | ' + text.slice(0, 120) : '');
                    }"""
                ),
                300,
            )
        except Exception:
            return ""

    def _naver_blog_click(
        self, locator: Any, *, what: str, timeout_ms: int | None = None, page: Any = None
    ) -> None:
        """Editor-flow click. Keeps the `naver_blog_*` error names its callers
        and tests read; the behaviour lives in `_guarded_click`."""
        self._guarded_click(
            locator, what=what, timeout_ms=timeout_ms, page=page, prefix="naver_blog"
        )

    #: 가로막힌 자리를 기억하는 시간(초). 그 안에 같은 가림막이 그대로면 다시 기다리지 않는다.
    _BLOCKED_CLICK_MEMORY_SEC = 180.0
    #: 「우리 누르기가 띄운 창」으로 기억하는 시간(초). 그 안에 같은 문구의 창이 가리고 있으면 치우지 않는다.
    _OWN_DIALOG_MEMORY_SEC = 300.0

    @staticmethod
    def _blocked_click_hint(blocker: str, *, repeated: bool = False) -> str:
        """가로막힌 클릭의 오류 글 뒤에 붙이는 한 줄 — 무엇이 달라져야 눌리는지."""
        parts: list[str] = []
        if repeated:
            parts.append("★ 방금과 같은 것이 그대로 가리고 있다 — 다시 눌러도 같다. 가리는 것을 치우거나 다른 길로 가라")
        if blocker.startswith("<조상>"):
            parts.append(
                "가리는 것이 누르려던 요소의 **조상**이다 — 그 조상에 덧씌운 ::before/::after 나 겹침 순서가 클릭을 받는 모양이다. "
                "직접 만든 페이지면 그 덧씌움에 pointer-events:none 을 주거나 겹침 순서(z-index)를 고쳐라"
            )
        return (" | " + " · ".join(parts)) if parts else ""

    def _guarded_click(
        self,
        locator: Any,
        *,
        what: str,
        timeout_ms: int | None = None,
        page: Any = None,
        prefix: str = "browser",
    ) -> None:
        """Click, clearing a modal that appears mid-flight, and name anything
        that still eats the click.

        A bare timeout here is indistinguishable from a wrong selector, which
        is how the same failure got misdiagnosed twice as "iframe 구조 때문에
        본문 영역 인식 실패".

        The retry exists because the draft-restore confirm does not appear at a
        predictable moment. Clearing popups once after navigation was not
        enough: measured on 2026-08-05, the editor booted clean, the dismisser
        found nothing, and only then did "작성 중인 글이 있습니다" appear -- so
        the very next click was the thing that discovered it. Reacting to the
        interception is reliable in a way that waiting longer is not, because
        it needs no guess about how late is late enough.
        """
        timeout = timeout_ms or self.config.browser_action_timeout_sec * 1000
        # ★ **같은 것이 그대로 가리고 있는 자리를 또 누르면 기다리지 않는다** (2026-10-05 사다리 L2).
        #   모델이 만든 페이지의 카드 덧씌움(`.card::before`)이 버튼을 가렸고, 가로막힌 클릭 한 번이 17초(기다렸다 누르기 두 번)였다.
        #   같은 버튼을 여덟 번 눌러 약 136초 — 그 판이 226초에서 600초가 됐다. 첫 시도는 그대로 기다린다(잠깐 뜨는 가림막은
        #   기다리면 걷힌다). 방금 가로막힌 그 자리에 **같은 가림막이 지금도 있으면** 다시 눌러도 같으니 바로 알린다.
        memory: dict[str, tuple[str, float]] = self.__dict__.setdefault("_blocked_clicks", {})
        memory_key = f"{getattr(page, 'url', '') if page is not None else ''}|{prefix}|{what}"
        remembered = memory.get(memory_key)
        if remembered and time.monotonic() - remembered[1] < self._BLOCKED_CLICK_MEMORY_SEC:
            still = self._intercepting_element(locator)
            if still and still == remembered[0]:
                memory[memory_key] = (still, time.monotonic())
                raise RuntimeError(
                    f"{prefix}_click_intercepted:{what}:{still}" + self._blocked_click_hint(still, repeated=True)
                )
            memory.pop(memory_key, None)
        try:
            locator.click(timeout=timeout)
            memory.pop(memory_key, None)
            return
        except Exception as exc:
            blocker = self._intercepting_element(locator)
            if page is None:
                if not blocker:
                    raise RuntimeError(
                        f"{prefix}_click_failed:{what}:{_clean(exc, 300)}"
                    ) from exc
                raise RuntimeError(f"{prefix}_click_intercepted:{what}:{blocker}") from exc
            if not blocker:
                # `elementFromPoint` runs inside the *element's* document, so a
                # dialog living in the top document is invisible to a target
                # inside an iframe -- it reports nothing on top and the click
                # looks like a plain timeout. That is cause #3 of the 2026-08-05
                # write-up, and it is why recovery keys off "is there a dialog
                # anywhere on this page", not off naming the blocker.
                dialog = self._first_visible_popup(page)
                if dialog is None:
                    raise RuntimeError(
                        f"{prefix}_click_failed:{what}:{_clean(exc, 300)}"
                    ) from exc
                blocker = f"다른 프레임의 대화상자 | {self._locator_text(dialog, 120)}"
            # ★ 방금 **우리 누르기가 띄운 창**은 치우지 않는다 (2026-10-07 폼 벤치 여섯째 판).
            #   「임시저장」을 누르자 「임시저장하시겠습니까? [확인][취소]」가 떴다. 모델이 「임시저장」을 한 번 더 누르자 아래 규칙이
            #   그 창을 **「취소」로 닫고** 다시 눌렀다 — 결과에는 한 마디도 없이. 떠돌이 팝업에는 맞는 규칙이지만, 이 창은
            #   하던 일의 다음 단계다. 부정 단추를 누르는 것은 사용자 대신 「아니오」라고 답하는 일이다.
            #   그 창이 덮고 있다는 사실과 문구를 그대로 돌려주고, 어느 단추를 누를지는 모델이 정한다.
            own = self.__dict__.get("_dialog_we_opened") or {}
            if (own and time.monotonic() - float(own.get("at") or 0.0) < self._OWN_DIALOG_MEMORY_SEC
                    and own.get("url") == str(getattr(page, "url", "") or "")):
                showing = self._first_visible_popup(page)
                shown = _clean(self._locator_text(showing, 200), 80) if showing is not None else ""
                if shown and shown == own.get("text"):
                    raise RuntimeError(
                        f"{prefix}_click_blocked_by_the_dialog_you_opened:{what} — 방금 누른 것이 「{shown}」 창을 띄웠고, "
                        "그 창이 화면을 덮고 있어 창 뒤의 것은 눌리지 않는다. 이 창은 닫지 않았다(하던 일의 다음 단계일 수 있다). "
                        "browser_snapshot 을 다시 찍어 **그 창 안의 단추**를 눌러라 — 시킨 일을 이어 가려면 확인 쪽, "
                        "그만두려면 취소 쪽이다."
                    ) from exc
            # Something is on top. Clear it under the usual rules -- only a
            # negative button, and a loud failure if there is not one -- then
            # take exactly one more shot. A second interception is a real
            # blocker, not a timing race, and must not become a retry loop.
            closed = self._dismiss_dialogs(page, prefix=prefix)
            # 무엇을 무엇으로 닫았는지 남긴다 — 누르기 결과가 싣는다. 말없이 닫으면 「눌렀다」만 남고 창이 있었던 것이 사라진다.
            self.__dict__["_auto_closed"] = [
                {"text": _clean(record.get("text"), 80), "pressed": str(record.get("button") or "")}
                for record in closed or [] if record.get("dismissed")
            ]
            try:
                locator.click(timeout=timeout)
                return
            except Exception as retry_exc:
                again = self._intercepting_element(locator) or blocker
                # ★ 2026-10-03 (Online-Mind2Web Zara 세 판): 닫기 버튼이 없는 가림막이 둘이었다.
                #   ① 열린 메뉴의 **뒷막**(`div.zds-backdrop`) — 대화창이 아니라 「닫기」를 못 찾는다. 사람은 Esc 나 바깥을 누른다.
                #   ② 체크박스를 꾸민 **겉 칸**(`span.zds-checkbox-control`)이 진짜 체크박스를 덮음 — 그 겉 칸을 누르는 게 맞다.
                if self._clear_blocker(page, locator, timeout=timeout):
                    memory.pop(memory_key, None)
                    return
                memory[memory_key] = (again, time.monotonic())
                raise RuntimeError(
                    f"{prefix}_click_intercepted:{what}:{again}" + self._blocked_click_hint(again)
                ) from retry_exc

    def _probe_frames(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """Count how many nodes each candidate selector matches, per frame.

        A diagnostic, not something the model is given. `browser_snapshot`
        reports the top document only, so an editor that lives entirely inside
        an iframe reads as "0 elements" and says nothing about *why* a selector
        missed -- which is the exact question when a click times out with no
        "locator resolved to" line in its call log.
        """
        selectors = [
            str(s) for s in (arguments.get("selectors") or [])
        ] or [
            ".se-main-container", ".se-text-paragraph", ".se-component",
            ".se-title-text", "[contenteditable='true']", ".se-placeholder",
            ".se-popup", ".se-popup-dim",
        ]
        samples = bool(arguments.get("samples"))
        frames = []
        for index, frame in enumerate(self._frames_of(page)):
            counts: dict[str, Any] = {}
            matched: dict[str, Any] = {}
            for selector in selectors:
                try:
                    locator = frame.locator(selector)
                    count = int(locator.count())
                except Exception as exc:
                    counts[selector] = f"error:{_clean(exc, 60)}"
                    continue
                counts[selector] = count
                if samples and count:
                    matched[selector] = self._selector_samples(locator, count)
            entry: dict[str, Any] = {
                "name": self._frame_label(frame, index),
                "url": _clean(getattr(frame, "url", "") or "", 120),
                "counts": {k: v for k, v in counts.items() if v},
            }
            if matched:
                entry["samples"] = matched
            frames.append(entry)
        return self._evidence("browser_probe_frames", frames=frames)

    def _selector_samples(self, locator: Any, count: int, limit: int = 3) -> list[dict[str, Any]]:
        """What the first few matches actually are.

        A count alone answers "does this selector hit anything" but not "is it
        hitting the thing I mean" -- which is the question that follows every
        time, and the one that had us clicking a row that wrapped two buttons.
        """
        out: list[dict[str, Any]] = []
        for index in range(min(count, limit)):
            node = locator.nth(index)
            item: dict[str, Any] = {"index": index, "text": self._locator_text(node, 120)}
            box = self._box_of(node)
            if box:
                item["box"] = box
            out.append(item)
        return out

    def _dismiss_dialog(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """Clear a blocking dialog on any site, under the fixed rules."""
        rounds = max(1, min(int(arguments.get("rounds") or 2), 5))
        dismissed = self._dismiss_dialogs(page, rounds=rounds)
        return self._evidence(
            "dialog_dismissed", dismissed=dismissed, dialog_count=len(dismissed)
        )

    #: 한 번에 받을 최대 크기. 넘으면 잘라 받지 않고 **안 받았다고 말한다** —
    #: 반쪽 PDF 는 읽으면 틀린 답이 나온다.
    _DOWNLOAD_MAX_BYTES = 60 * 1024 * 1024

    def _download(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """URL 의 문서를 **브라우저 세션 그대로** 받아 파일로 남긴다.

        ★ 왜 필요했나 (2026-09-01)

        브라우저 도구가 30개인데 **받는 도구가 하나도 없었다.** Playwright 는
        `accept_downloads` 로 받을 준비가 돼 있었지만, 자비스가 그걸 시킬 손이 없었다.
        그래서 PDF 를 만나면 화면에 띄워 놓고 눈으로 읽거나, 그냥 못 읽었다.

        `httpx` 로 따로 받으면 **로그인 세션이 없다.** 학교·기관 자료는 대개 로그인
        뒤에 있으므로, 브라우저 컨텍스트의 쿠키를 그대로 쓰는 `context.request` 로
        받는다 — 사람이 그 창에서 클릭한 것과 같은 자격이다.

        받은 파일은 `browser_download_dir` 에 남고, 그 폴더는 로컬 읽기 허용 루트에
        들어 있으므로 곧바로 `local_read_document` 로 읽을 수 있다.

        ★ 2026-10-18 LH 청년전세임대 공고 판(잡 760b04f4 · 413초 · 23걸음) — **받고도 못 읽었다.**
        「1순위 자격」은 공고의 첨부 PDF 에 있었다. 모델은 14걸음째에 이 도구를 불러 `ok` 를 받았지만, 그 뒤 4분 동안
        같은 HTML 화면에서 찾기·내리기만 하다가 **읽지 않은 조건**(나이 · 거주)을 답에 적었다(답 스스로 「읽지 않고 적은 것」).
        파일을 열어 보니 PDF 가 아니라 **공고 화면 HTML(695KB)** 이었다 — 첨부 링크가 `javascript:fileDownLoad('…')`
        라 모델은 받을 주소를 몰랐고, 화면 주소에 이름만 `.pdf` 로 붙여 넘겼다. 도구는 그걸 `ok` 로 저장해 줬다.
        「받은 path 를 local_read_document 로 읽어라」는 안내는 있었지만 안 먹었다(사고 R). 그래서 셋을 코드로 박는다.

          ① **링크 ref 로 받는다** — 주소가 없는 첨부(`javascript:`)는 도구가 그 링크를 눌러 내려오는 파일을 붙잡는다.
          ② **문서라 부른 것이 웹 화면이면 저장하지 않는다** — 「받았다」가 아니라 「받은 것은 화면이다, ref 로 다시」를 준다.
          ③ **받은 문서는 그 자리에서 읽어 본문을 결과에 싣는다**(`content`) — 읽는 걸음을 모델에게 맡기지 않는다.
        """
        directory = self.config.browser_download_dir
        directory.mkdir(parents=True, exist_ok=True)
        ref = str(arguments.get("ref") or "").strip()
        url = str(arguments.get("url") or "").strip()
        if ref:
            from urllib.parse import urljoin

            locator = self._ref_locator(page, ref)
            label = _clean(locator.get_attribute("title") or locator.inner_text(timeout=1000), 200)
            # 받기는 누르기다 — 결제·삭제처럼 되돌릴 수 없는 이름이 붙은 것은 이 문으로 누르지 않는다(`_click` 과 같은 규칙).
            if _IRREVERSIBLE_ACTION.search(label):
                raise RuntimeError(f"irreversible_click_needs_approval:{label}")
            href = str(locator.get_attribute("href") or "").strip()
            if href and not href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
                # 진짜 주소가 붙은 링크면 세션 요청으로 받는다 — 누르는 것보다 조용하고 같은 자격이다.
                url = urljoin(str(getattr(page, "url", "") or ""), href)
            else:
                return self._download_by_click(page, locator, label, directory, arguments)
        if not url:
            raise ValueError("url_or_ref_required")
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("http_url_required")

        context = page.context
        response = context.request.get(url, timeout=120_000)
        status = int(response.status)
        if status >= 400:
            # 실패를 파일로 남기지 않는다 — 오류 HTML 을 PDF 로 읽는 사고가 난다.
            return {"action": "browser_download", "url": url, "status": status, "ok": False}
        body = response.body()
        if len(body) > self._DOWNLOAD_MAX_BYTES:
            raise ValueError(f"download_too_large:{len(body)}")

        header = {k.lower(): v for k, v in (response.headers or {}).items()}
        content_type = str(header.get("content-type") or "").split(";")[0].strip()
        name = str(arguments.get("name") or "").strip()
        if not name:
            # 파일 이름은 Content-Disposition → URL 마지막 조각 → 시각 순으로 정한다.
            disposition = str(header.get("content-disposition") or "")
            match = re.search(r'filename\*?=(?:UTF-8'')?"?([^";]+)', disposition)
            name = match.group(1) if match else unquote(urlparse(url).path.rsplit("/", 1)[-1])
        name = re.sub(r"[^0-9A-Za-z_.가-힣-]+", "_", name)[:80] or "download"
        if "." not in name:
            name += _EXTENSION_BY_TYPE.get(content_type, ".bin")
        refused = self._download_is_a_page(name, body[:4096], url=url, status=status, content_type=content_type)
        if refused is not None:
            return refused
        path = directory / f"{time.strftime('%Y%m%d_%H%M%S')}_{name}"
        path.write_bytes(body)
        return self._downloaded(path, url=url, status=status, content_type=content_type, arguments=arguments)

    #: 링크를 눌러 받을 때 파일이 내려오기를 기다리는 시간.
    _DOWNLOAD_CLICK_TIMEOUT_MS = 60_000

    def _download_by_click(
        self, page: Any, locator: Any, label: str, directory: Path, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """주소가 없는 첨부 링크(`javascript:fileDownLoad('…')`)를 눌러 **내려오는 파일을 붙잡는다.**

        공공기관 게시판의 첨부는 거의 이 꼴이다 — 받을 주소가 화면에 없고, 누르면 스크립트가 주소를 만들어 이동한다.
        누르기만 하면 파일은 조용히 다운로드 폴더로 가고 모델은 「화면에 변화 없음」만 받는다(760b04f4 의 16걸음째).
        """
        try:
            with page.expect_download(timeout=self._DOWNLOAD_CLICK_TIMEOUT_MS) as info:
                locator.click()
            download = info.value
        except Exception as exc:  # noqa: BLE001 — 안 내려온 것은 실패로 알린다, 판을 죽이지 않는다
            if "timeout" not in type(exc).__name__.lower() and "timeout" not in str(exc).lower():
                raise
            return {
                "action": "browser_download", "ok": False, "label": label,
                "instruction": (
                    f"「{label}」를 눌렀지만 {self._DOWNLOAD_CLICK_TIMEOUT_MS // 1000}초 안에 파일이 내려오지 않았다 — "
                    "새 창 미리보기로 열렸을 수 있다. browser_tabs 로 새 탭을 보고, 그 주소를 browser_download(url=…) 로 넘겨라."
                ),
            }
        name = str(arguments.get("name") or "").strip() or str(getattr(download, "suggested_filename", "") or "")
        name = re.sub(r"[^0-9A-Za-z_.가-힣-]+", "_", name)[:80] or "download"
        if "." not in name:
            name += ".bin"
        path = directory / f"{time.strftime('%Y%m%d_%H%M%S')}_{name}"
        download.save_as(str(path))
        url = str(getattr(download, "url", "") or "")
        size = path.stat().st_size
        if size > self._DOWNLOAD_MAX_BYTES:
            path.unlink(missing_ok=True)
            raise ValueError(f"download_too_large:{size}")
        with path.open("rb") as handle:
            head = handle.read(4096)
        refused = self._download_is_a_page(name, head, url=url, status=200, content_type="")
        if refused is not None:
            path.unlink(missing_ok=True)
            return refused
        return self._downloaded(path, url=url, status=200, content_type="", arguments=arguments, label=label)

    #: 그 자리에서 읽어 결과에 싣는 형식. 옛 한글(.hwp)·옛 오피스(.doc/.xls)는 읽는 자가 없어 따로 안내한다.
    _DOWNLOAD_READABLE = frozenset({
        ".pdf", ".docx", ".xlsx", ".pptx", ".hwpx", ".odt", ".ods", ".odp", ".epub",
        ".txt", ".md", ".csv", ".tsv", ".json", ".rtf",
    })
    #: 이름이 이 꼴이면 **문서 파일을 받으려 한 것**이다 — 받은 것이 웹 화면이면 저장하지 않는다.
    _DOWNLOAD_DOCUMENT_SUFFIXES = _DOWNLOAD_READABLE | frozenset({".hwp", ".doc", ".xls", ".ppt", ".zip"})
    _HTML_HEAD = re.compile(rb"^\s*(?:<!--.*?-->\s*)*<(?:!doctype\s+html|html|head|body)\b", re.I | re.S)
    #: 받은 그 자리에서 결과에 싣는 본문 글자 수 — 기본은 `browser_extract` 와 같은 20,000. 위로는 도구 결과 한 건
    #: 상한(`transcript_policy._TOOL_RESULT_MAX_CHARS`)까지만 받는다. 그보다 크게 실으면 그 상한이 조용히 자른다(사고 Q).
    _DOWNLOAD_READ_CHARS = 20_000

    def _download_is_a_page(
        self, name: str, head: bytes, *, url: str, status: int, content_type: str
    ) -> dict[str, Any] | None:
        """문서라고 받은 것이 **웹 화면(HTML)** 이면 거절 결과를, 아니면 None 을 준다(760b04f4 — 화면을 `.pdf` 로 저장했다)."""
        suffix = Path(name).suffix.lower()
        if suffix not in self._DOWNLOAD_DOCUMENT_SUFFIXES:
            return None
        is_html = bool(self._HTML_HEAD.match(head.lstrip(b"\xef\xbb\xbf")))
        not_pdf = suffix == ".pdf" and b"%PDF" not in head[:1024]
        if not is_html and not (not_pdf and content_type.startswith("text/")):
            return None
        return {
            "action": "browser_download", "url": url, "status": status, "ok": False,
            "got": "web_page", "content_type": content_type or "text/html",
            "instruction": (
                f"받은 것은 {suffix} 문서가 아니라 웹 화면(HTML)이다 — 저장하지 않았다. 이 주소는 문서가 아니라 화면이다. "
                "첨부가 `javascript:` 링크로 받는 사이트(공공기관 게시판 등)는 주소로 못 받는다: browser_find 로 첨부 "
                "파일 이름(예: 「.pdf」)을 찾아 그 ref 를 browser_download(ref=…) 로 넘겨라 — 도구가 링크를 눌러 받은 "
                "파일을 저장하고 본문까지 읽어 준다."
            ),
        }

    def _downloaded(
        self, path: Path, *, url: str, status: int, content_type: str, arguments: dict[str, Any], label: str = "",
    ) -> dict[str, Any]:
        """저장한 파일의 결과 — 읽을 수 있는 문서면 **본문을 같이 싣는다**(`content`)."""
        result: dict[str, Any] = {
            "action": "browser_download", "url": url, "status": status, "ok": True,
            "path": str(path), "bytes": path.stat().st_size, "content_type": content_type,
            **({"label": label} if label else {}),
        }
        suffix = path.suffix.lower()
        if suffix == ".hwp":
            # local_read_document 도 옛 한글은 거절한다 — 갈 길을 같이 준다(local_computer.read_document 와 같은 말).
            result["instruction"] = (
                "옛 한글(.hwp)은 그 자리에서 못 읽었다. hwp_export_pdf(path) 로 PDF 로 바꾼 뒤 local_read_document 로 읽어라."
            )
            return result
        if suffix not in self._DOWNLOAD_READABLE:
            result["note"] = "문서 형식이 아니라 읽지 않았다 — 파일만 저장했다."
            return result
        from .document_reader import DocumentReader
        from .transcript_policy import _TOOL_RESULT_MAX_CHARS

        try:
            limit = max(1_000, min(int(arguments.get("max_chars") or self._DOWNLOAD_READ_CHARS), _TOOL_RESULT_MAX_CHARS))
        except (TypeError, ValueError):
            limit = self._DOWNLOAD_READ_CHARS
        try:
            document = DocumentReader().read_path(path)
        except Exception as exc:  # noqa: BLE001 — 받기는 됐다, 읽기 실패만 알린다
            result["read_error"] = str(exc)[:200]
            result["instruction"] = "받았지만 그 자리에서 못 읽었다 — local_read_document 로 path 를 읽어라."
            return result
        text = document.text
        result.update({
            "format": document.format, "pages": document.pages, "content": text[:limit],
            "char_count": min(len(text), limit), "total_chars": len(text),
            "truncated": len(text) > limit or document.truncated,
        })
        if document.warnings:
            result["warnings"] = list(document.warnings)
        if not text.strip():
            result["instruction"] = (
                "받은 문서에 글자 층이 없다(스캔 PDF 일 수 있다). local_read_document 로 path 를 읽으면 그림 판독을 시도한다."
            )
        elif len(text) > limit:
            result["instruction"] = (
                f"받은 문서의 본문을 content 에 실었다 — 앞 {limit:,}자(전체 {len(text):,}자). 뒷부분이 필요하면 "
                "local_read_document(path, max_chars) 로 더 읽어라. 화면에서 다시 찾지 마라."
            )
        else:
            result["instruction"] = "받은 문서의 본문 전체를 content 에 실었다 — 이것으로 답하라. 화면에서 다시 찾지 마라."
        return result

    def _screenshot(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """A PNG of what is on screen right now, saved to the evidence dir.

        Playwright's own capture, not the tablet camera -- so this works with
        the camera offline, and it is pixel-exact rather than a photo of a
        monitor. The JARVIS overlay is hidden for the shot: it draws a frame and
        a badge over the page, which is noise to a model being asked what the
        page shows.
        """
        label = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(arguments.get("label") or "shot"))[:40]
        full_page = bool(arguments.get("full_page"))
        directory = self.config.browser_evidence_dir
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        path = directory / f"{time.strftime('%Y%m%d_%H%M%S')}_{label}.png"
        # ★ `ref` 를 주면 **그 자리만** 잘라 찍는다 (2026-08-11).
        #
        # 화면 전체를 모델에게 물었더니 웜 상태에서 178초에 오답이었다 —
        # 1920×950 을 축소해서 보니 검색창의 '파이썬' 글자를 못 읽었다. 사람도
        # 그 크기로 줄이면 못 읽는다. 판정에 필요한 것은 그 칸 하나지 화면 전체가
        # 아니다. 둘레를 조금 남겨서(버튼 색·옆 칸 같은 문맥) 자른다.
        clip = None
        ref = str(arguments.get("ref") or "")
        given_box = arguments.get("box") if isinstance(arguments.get("box"), dict) else None
        if ref or given_box:
            # 좌표 상자로도 자른다(2026-09-18) — 닫힌 섀도 DOM·캔버스 칸은 ref 가 없고 접근성 트리 좌표만 있다.
            try:
                box = self._ref_locator(page, ref).bounding_box() if ref else {
                    "x": float(given_box.get("x") or 0), "y": float(given_box.get("y") or 0),
                    "width": float(given_box.get("width") or 0), "height": float(given_box.get("height") or 0),
                }
            except Exception:
                box = None
            if box and float(box["width"]) > 0 and float(box["height"]) > 0:
                pad = max(8, int(arguments.get("pad") or 48))
                clip = {
                    "x": max(0.0, float(box["x"]) - pad),
                    "y": max(0.0, float(box["y"]) - pad),
                    "width": float(box["width"]) + pad * 2,
                    "height": float(box["height"]) + pad * 2,
                }
        self._toggle_overlay(page, visible=False)
        try:
            # ★ 애니메이션을 멈추고 찍는다 (2026-08-14).
            #
            # 쿠팡 상세에서 `Page.screenshot: Timeout 20000ms exceeded` 가 연달아
            # 두 번 났다 — 40초를 통째로 버렸고 `ui_find_target` 이 두 번 다 죽었다.
            # 배너·캐러셀이 계속 도는 페이지에서는 Playwright 가 "화면이 멎기"를
            # 기다리다 시간을 다 쓴다. `animations="disabled"` 가 그걸 얼린다.
            shot = {"animations": "disabled", "caret": "initial",
                    "timeout": _SCREENSHOT_TIMEOUT_MS}
            raw = None if (clip or full_page) else self._capture(page, quiet=True)
            if raw is not None:
                # 사람이 PC 를 쓰는 중이라 창을 안 올리고 찍었다(인수인계 H2-A).
                path.write_bytes(raw)
            elif self._capture_skip_reason == "capture_timeout_hidden_tab":
                # 이 탭은 지금 그림을 안 만든다. 20초짜리 캡처로 다시 가 봐야 같은 자리에서 멈춘다.
                raise RuntimeError(
                    "screenshot_unavailable_hidden_tab — 이 탭은 지금 화면에 그려지지 않아 그림을 못 찍습니다."
                    " browser_snapshot 으로 내용을 읽으세요."
                )
            elif clip:
                page.screenshot(path=str(path), clip=clip, **shot)
            else:
                page.screenshot(path=str(path), full_page=full_page, **shot)
        finally:
            self._toggle_overlay(page, visible=True)
        size = 0
        try:
            size = path.stat().st_size
        except Exception:
            pass
        return self._evidence(
            "screenshot", path=str(path), bytes=size,
            instruction=(
                "그림 파일만 저장됐다. 이 그림은 너에게 보이지 않는다 — 화면 내용·바뀐 것은 "
                "browser_snapshot·browser_read 로 읽어 확인해라."
            ),
        )

    def _annotate(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """A screenshot with every candidate numbered, plus the matching list.

        The two halves are the point: the picture is what a model can actually
        judge ("which of these is the 본문"), and the list is what code can act
        on. Neither side ever mentions a coordinate, so a misread costs a wrong
        candidate -- recoverable -- instead of a click into empty space that
        reports success (2026-08-05 handoff, 3.1).

        Marks are removed before returning. Leaving them would put pink boxes
        into every later screenshot and into the user's own view of the page.
        """
        # ★ 자르는 자리를 옮겼다 (2026-08-13).
        #
        # 예전에는 스냅샷을 **60 개로 먼저 자르고** 그 안에서 화면에 든 것을 골랐다.
        # 그런데 자르는 기준이 DOM 순서라, 화면에 뻔히 보이는데 문서 뒤쪽에 있는 것은
        # 그림에 들어갈 기회조차 없었다.
        #
        # 실측(다나와 검색결과): 정렬 바가 스냅샷 **136~139 번째** — 60 을 훌쩍 넘는다.
        # 그래서 `ui_find_target("낮은 가격순 정렬 버튼")` 이 "후보 58 개 중에 없습니다"로
        # 끝났다. 화면 한복판에 있는 버튼이었다.
        #
        # 좁히는 일은 이미 `_MARK_JS` 가 한다 — **화면 안에 든 것만** 표시한다. 그게
        # 진짜 기준이고(모델은 그림에 없는 것을 못 고른다), 개수 상한은 그림이 번호로
        # 뒤덮이지 않게 하는 안전장치일 뿐이다. 그래서 넓게 뜨고 **표시할 때** 자른다.
        cap = max(1, int(arguments.get("limit") or _MAX_MARKS))
        snapshot = self._snapshot(
            page, {**arguments, "limit": _ANNOTATE_SCAN_BUDGET, "include_box": True, "_ceiling": _ANNOTATE_SCAN_BUDGET}
        )
        elements = snapshot.get("elements", [])
        marked: set[str] = set()
        for frame in self._frames_of(page):
            # 남은 자리만큼만 표시한다 — 그림과 목록이 어긋나면 "모델이 잘못 골랐다"로
            # 보이지만 실은 못 보여 준 것이다.
            remaining = cap - len(marked)
            if remaining <= 0:
                break
            try:
                refs = frame.evaluate(_MARK_JS, remaining)
            except Exception:
                continue
            for ref in refs or []:
                marked.add(str(ref))
        # ★ 그림을 못 찍어도 **목록은 내준다** (2026-08-14).
        #
        # 예전에는 여기서 예외가 그대로 올라가 `ui_find_target` 이 통째로 죽었다.
        # 실측(쿠팡 상세): `Page.screenshot: Timeout 20000ms` 이 연달아 두 번 —
        # 40초를 버렸고, 그 판은 찾기를 포기했다.
        #
        # 그런데 이 도구의 **싼 길은 그림이 필요 없다.** 이름이 딱 하나 맞으면
        # 코드가 바로 고른다(`UiVision._by_name`). 비싸고 잘 깨지는 쪽이 싸고
        # 확실한 쪽을 막고 있었던 셈이다 — 순서가 거꾸로였다.
        shot: dict[str, Any] = {}
        shot_error = ""
        try:
            shot = self._screenshot(page, {"label": arguments.get("label") or "annotated"})
        except Exception as exc:
            shot_error = str(exc)[:160]
        finally:
            for frame in self._frames_of(page):
                try:
                    frame.evaluate(_UNMARK_JS)
                except Exception:
                    continue
        visible = []
        for item in elements:
            item["marked"] = item["ref"] in marked
            if item["marked"]:
                visible.append(item)
        if len(elements) > _ANNOTATE_LIST_MAX:
            # 훑기는 전부 했다. 내주는 목록은 **화면에 든 것 먼저**(번호를 그린 것 → 번호는 못 그렸지만 화면에 있는 것),
            # 나머지는 문서 순서로 상한까지만. 화면에 요소가 60개를 넘으면 번호는 앞에서부터만 그려지는데, 그때도 이름으로
            # 찾는 싼 길(`UiVision._by_name`)은 화면에 있는 것 전부를 봐야 한다 — 아래 고정 막대의 단추가 그 자리다.
            try:
                width, height = page.evaluate("() => [window.innerWidth, window.innerHeight]")
            except Exception:  # noqa: BLE001
                width, height = 0, 0

            def on_screen(item: dict[str, Any]) -> bool:
                box = item.get("box") or {}
                return bool(
                    box and height and box.get("y", 0) < height and box.get("y", 0) + box.get("height", 0) > 0
                    and box.get("x", 0) < width and box.get("x", 0) + box.get("width", 0) > 0
                )

            unmarked = [item for item in elements if not item["marked"]]
            near = [item for item in unmarked if on_screen(item)]
            far = [item for item in unmarked if not on_screen(item)]
            elements = (visible + near + far)[:_ANNOTATE_LIST_MAX]
        return self._evidence(
            "annotated",
            path=shot.get("path", ""),
            elements=elements,
            # What is actually in the picture. Offering the model a candidate it
            # cannot see is how a "wrong choice" gets blamed on the model.
            candidates=visible,
            candidate_count=len(visible),
            # 그림이 없으면 **없다고 적는다.** 조용히 빈 경로를 주면 "화면이 비었다"와
            # 구별이 안 되고, 비전이 못 고른 것이 모델 탓으로 기록된다.
            **({"screenshot_failed": shot_error} if shot_error else {}),
        )

    def _toggle_overlay(self, page: Any, *, visible: bool) -> None:
        if not self.config.browser_visual_overlay or page is None:
            return
        try:
            page.evaluate(
                "(visible) => { const el = document.getElementById('__alture_jarvis_visual');"
                " if (el) el.style.display = visible ? '' : 'none'; }",
                visible,
            )
        except Exception:
            pass

    def _capture_failure_evidence(self, action: str, error: str) -> dict[str, Any]:
        """Screenshot + per-frame element counts at the moment a step failed.

        Written because the expensive part of the 2026-08-03~05 chase was not
        fixing anything -- it was reconstructing the state each failure had been
        in. Best-effort by design: an evidence capture that can itself raise
        would replace the real error with its own.
        """
        page = self._page
        if page is None or page.is_closed():
            return {}
        evidence: dict[str, Any] = {}
        try:
            shot = self._screenshot(page, {"label": f"fail_{action}"})
            evidence["screenshot"] = shot.get("path", "")
        except Exception:
            pass
        try:
            probe = self._probe_frames(page, {"selectors": [_INTERACTIVE], "samples": True})
            evidence["frames"] = probe.get("frames", [])
        except Exception:
            pass
        if evidence:
            evidence["error"] = error[:300]
        return evidence

    def blocking_wall(self) -> dict[str, Any]:
        """사람만 지날 수 있는 문이 지금 화면에 있는가 — **글자가 아니라 구조로** 본다.

        ★ 이것이 근본 신호다. 지금까지는 사이트가 뭐라고 쓰는지로 로그인 화면을
        알아보려 했다. 2026-08-10 크몽에서 그 방식이 깨졌다: 모달에 '로그인'이 네 번
        나오는데 규칙이 찾던 '로그인이 필요'라는 어구가 없어서 못 알아봤고, 그래서
        사람에게 넘기지도 못한 채 두 번 두드려 보고 끝냈다. 문구를 하나씩 더 넣는 것은
        사이트 수만큼 두더지를 잡는 일이다.

        문구가 아니라 **자비스가 구조적으로 못 하는 일**을 본다:

            인증 문맥의 비밀번호 칸 자비스는 비밀번호를 치지 않는다(코드에 박힌 결정)
            캡차가 떠 있다         자비스는 봇 검사를 통과하지 않는다(같은 결정)

        둘 다 사이트 사정이 아니라 **우리 쪽 규칙**이라, 어느 나라 어느 사이트든
        똑같이 성립한다. 번역도 필요 없고 새 사이트마다 규칙을 더할 일도 없다.

        같은 신호로 **열렸는지도** 판정한다 — 비밀번호 칸이 사라지면 사람이 지나간
        것이다. 막힘과 열림을 한 신호로 보는 것이 이 설계의 핵심이다.

        브라우저가 바쁘면 모른다고 답한다. 확인하려고 줄을 서면 그 자체가 작업을
        늦춘다(gate_state 와 같은 규칙).
        """
        try:
            # 걸음 뒤의 **감지**다 — 닫을 수 있는 로그인 팝업은 여기서만 한 번 닫아 본다(감시 쪽 gate_state 는 안 닫는다).
            return dict(self._submit(lambda: self._blocking_wall(dismiss_popups=True), 4) or {"known": False})
        except Exception:
            return {"known": False}

    #: 닫은 로그인 팝업을 「같은 자리에서 또 떴다」로 볼 시간. 지나면 다시 한 번 닫아 본다.
    _LOGIN_POPUP_MEMORY_SEC = 1800.0
    #: 로그인 폼 **바깥**에 긴 글 조각(80자 이상)이 이만큼 있으면 그 페이지는 읽을 수 있는 페이지다(`_blocking_wall`).
    #: 한국어 기사 한두 문단이 300~600자다. 메뉴·단추·바닥글 링크는 한 조각이 80자를 넘지 않는다.
    _READABLE_PROSE_CHARS = 600

    @staticmethod
    def _login_popup_key(url: str) -> str:
        """팝업을 닫은 **자리** — 호스트+경로. 질의·해시는 뺀다(같은 화면이 질의만 바뀌어 다시 그려진다)."""
        try:
            parsed = urlparse(str(url or ""))
        except Exception:
            return ""
        return f"{(parsed.hostname or '').lower()}{(parsed.path or '').rstrip('/')}"

    def _login_popup_seen(self, key: str) -> bool:
        closed = getattr(self, "_login_popups_closed", None) or {}
        at = closed.get(key)
        return at is not None and (time.monotonic() - at) < self._LOGIN_POPUP_MEMORY_SEC

    def _login_popup_mark(self, key: str) -> None:
        closed = getattr(self, "_login_popups_closed", None)
        if closed is None:
            closed = {}
            self._login_popups_closed = closed
        if len(closed) > 200:
            closed.clear()
        closed[key] = time.monotonic()

    def _blocking_wall(self, root_page: Any | None = None, *, dismiss_popups: bool = False) -> dict[str, Any]:
        """★ **현재 작업 창과 그 창이 연 팝업**을 본다.

        2026-08-10: 로그인 문은 새 창에서 열리는 일이 아주 흔하다(OAuth·결제·본인확인).
        현재 창만 보면 팝업에 뜬 비밀번호 칸이 안 보이고, 그러면 "문이 없다"고 읽어
        사람에게 넘기지도 지켜보지도 않는다 — 위시켓에서 자비스가 원래 창만 보고
        "아무 일도 안 일어났다"고 하던 것과 **같은 고장**이다. 한 사이트의 문제가
        아니므로 한 사이트에서 고치면 안 된다.

        그렇다고 브라우저의 모든 기존 탭을 보면 안 된다. 2026-08-17 실제 캡차 시험에서
        현재 Google 임무와 무관한 Naver/Namu 탭의 봇 차단을 주워 잘못 대기했다. 따라서
        현재 창과 그 창에서 열린 popup 자손만 포함한다. OAuth 팝업은 보면서, 오래전에
        열어 둔 다른 작업 탭은 격리하는 경계다.
        """
        pages: list[Any] = []
        if self._context is not None:
            try:
                pages = [item for item in self._context.pages if not item.is_closed()]
            except Exception:
                pages = []
        if not pages and self._page is not None:
            pages = [self._page]
        if not pages:
            return {"known": False}
        # 현재 창을 루트로 삼고, 그 창이 연 popup 자손만 따라간다. Playwright의
        # Page.opener() 관계는 사이트가 달라지는 OAuth에도 유지된다.
        current = root_page if root_page in pages else (self._page if self._page in pages else pages[0])
        related = [current]
        changed = True
        while changed:
            changed = False
            for candidate in pages:
                if any(candidate is item for item in related):
                    continue
                try:
                    opener = candidate.opener()
                except Exception:
                    opener = None
                if opener is not None and any(opener is item for item in related):
                    related.append(candidate)
                    changed = True
        pages = related
        passwords = 0
        password_gate = False
        captcha = False
        payment = False
        where = ""
        for page in pages:
            page_captcha = False
            page_password_gate = False
            page_payment = False
            try:
                page_url = str(page.url or "")
            except Exception:
                page_url = ""
            lowered_url = page_url.casefold()
            frames = self._frames_of(page)
            for frame in frames:
                try:
                    password_inputs = frame.locator("input[type='password']:visible")
                    found = int(password_inputs.count())
                except Exception:
                    continue
                if found:
                    # 비밀번호 input **하나만**으로 페이지 전체를 로그인 문으로 치면
                    # 일반 가입·설정·테스트 폼도 첫 화면에서 멈춘다. Selenium 공식
                    # Web Form 라이브가 그랬다(2026-08-18): 13개 입력 중 연습용
                    # password 한 칸이 있다는 이유로 로그인 대기가 걸렸다.
                    #
                    # URL이 명백한 인증 경로이거나, password가 속한 form 자체가
                    # 작고 인증용 모양일 때만 문으로 친다. 문구 언어에는 기대지 않는다.
                    url_is_auth = any(
                        marker in lowered_url
                        for marker in ("/login", "/signin", "/sign_in", "nid.naver.com")
                    )
                    # ★ 닫을 수 있는 로그인 **팝업**은 문이 아니다 (2026-10-03 Online-Mind2Web WebMD 재기):
                    #   결과 화면 위에 X 가 있는 「Log In」 팝업이 뜨자 비밀번호 칸만 보고 「로그인이 필요해요」로 사람에게 넘겼다.
                    #   과제는 로그인이 필요 없었다 — 사람이라면 X 를 누르고 계속 간다. 칸이 대화창 모양 안에 있고 그 안에
                    #   닫기 단추가 있으면 **한 번 닫아 보고** 다시 센다. 로그인 전용 주소(`/login`)는 그대로 문이다.
                    #
                    #   ★ 두 가지 조건을 건다 — 안 걸면 2026-08-10 크몽(「의뢰 등록」을 눌러 뜬 로그인 모달이 **진짜 문**)을 되살린다.
                    #   ① **감지할 때만** 닫는다(`dismiss_popups`). 사람을 기다리며 지켜보는 쪽(gate_state)은 손대지 않는다 —
                    #      사람이 로그인하려고 연 창을 우리가 닫으면 안 된다.
                    #   ② **같은 주소에서는 한 번만** 닫는다. 닫았는데 같은 자리에서 또 뜨면 그 일에는 로그인이 필요한 것이다 → 문.
                    popup_key = self._login_popup_key(page_url)
                    if dismiss_popups and not url_is_auth and not self._login_popup_seen(popup_key):
                        try:
                            closed = bool(password_inputs.evaluate_all(_CLOSE_LOGIN_POPUP_JS))
                        except Exception:
                            closed = False
                        if closed:
                            self._login_popup_mark(popup_key)
                            try:
                                page.wait_for_timeout(400)
                                found = int(password_inputs.count())
                            except Exception:
                                pass
                            if not found:
                                self._note_trait(None, "login_popup_closed", url=page_url)
                                continue
                    try:
                        compact_auth_form = bool(
                            password_inputs.evaluate_all(
                                """
                                nodes => nodes.some(node => {
                                  const form = node.form || node.closest('form');
                                  const controls = form
                                    ? Array.from(form.querySelectorAll('input,textarea,select,button'))
                                    : [node];
                                  const visible = controls.filter(el => {
                                    const s = getComputedStyle(el);
                                    const r = el.getBoundingClientRect();
                                    return !el.disabled && s.display !== 'none' && s.visibility !== 'hidden'
                                      && r.width > 0 && r.height > 0
                                      && String(el.type || '').toLowerCase() !== 'hidden';
                                  });
                                  const editable = visible.filter(el =>
                                    /^(input|textarea|select)$/i.test(el.tagName));
                                  const ac = String(node.autocomplete || '').toLowerCase();
                                  const action = String((form && form.action) || '').toLowerCase();
                                  return ac.includes('current-password')
                                    || /(?:login|signin|sign_in)/.test(action)
                                    || (editable.length <= 3 && visible.length <= 6);
                                })
                                """
                            )
                        )
                    except Exception:
                        compact_auth_form = False
                    # ★ **읽을 본문이 있는 페이지의 로그인 상자는 문이 아니다** (2026-10-06 국내 조사 판).
                    #   한국클라우드신문 기사(로그인 없이 열리고 본문이 다 읽힌다)의 머리말에 아이디·비밀번호 상자가 있었다.
                    #   위 「작고 인증용 모양인 폼」에 그대로 걸려 `login_required` 로 사람에게 넘겼고, 판은 12분을 기다렸다.
                    #   머리말 로그인 상자와 로그인 화면은 폼만 보면 같은 모양이다 — 가르는 것은 **폼 바깥의 글**이다.
                    #   로그인 화면에는 읽을 글이 없고, 기사에는 긴 문단이 있다. 메뉴·바닥글은 짧은 글 조각이라 안 센다.
                    #   인증 주소(`/login`)는 글이 있어도 그대로 문이다.
                    if compact_auth_form and not url_is_auth:
                        try:
                            prose = int(password_inputs.evaluate_all(_PROSE_OUTSIDE_LOGIN_JS, self._READABLE_PROSE_CHARS))
                        except Exception:
                            prose = 0
                        if prose >= self._READABLE_PROSE_CHARS:
                            compact_auth_form = False
                            self._note_trait(None, "login_box_beside_readable_page", url=page_url)
                    page_password_gate = page_password_gate or url_is_auth or compact_auth_form
                passwords += found
                try:
                    if int(
                        frame.locator(_VISIBLE_CAPTCHA_SELECTOR).count()
                    ):
                        page_captcha = True
                except Exception:
                    pass
                # ★ 결제 칸·결제창(2026-09-23) — 온텔릭은 카드 번호를 넣지 않으니 비밀번호 칸과 같은 문이다.
                if not page_payment and self._frame_is_payment(frame):
                    page_payment = True
            # reCAPTCHA/hCaptcha/Turnstile 은 사람이 풀어도 iframe 자체는 DOM에
            # 남는다. iframe 존재만 보면 watcher가 영원히 재개하지 못한다. 푸는
            # 동작은 하지 않고, 공급자가 이미 써 둔 완료 체크/응답 토큰만 읽는다.
            if page_captcha and not self._captcha_was_solved(frames):
                captcha = True
                if not where:
                    try:
                        where = str(page.url or "")
                    except Exception:
                        where = ""
            if page_password_gate:
                password_gate = True
                if not where:
                    where = page_url
            if page_payment:
                payment = True
                if not where:
                    where = page_url
        if captcha:
            self._note_trait(None, "bot_wall", url=where)
        if password_gate:
            self._note_trait(None, "login_wall", url=where)
        return {
            "known": True,
            "password_fields": passwords,
            "password_gate": password_gate,
            "captcha": captcha,
            "payment": payment,
            "windows": len(pages),
            # 사람에게 "여기서 로그인해 주세요"라고 말하려면 어느 창인지가 있어야 한다.
            "wall_url": where,
        }

    @staticmethod
    def _frame_is_payment(frame: Any) -> bool:
        """이 프레임이 **결제 정보를 넣는 자리**인가 — 카드 칸이 보이거나, 결제창 크기의 결제 대행사 창이다.

        온텔릭은 카드 번호를 넣지 않는다. 그러니 이 자리는 비밀번호 칸처럼 사람만 지날 수 있다(2026-09-23).
        """
        try:
            if int(frame.locator(_VISIBLE_PAYMENT_SELECTOR).count()):
                return True
        except Exception:
            pass
        url = str(getattr(frame, "url", "") or "").lower()
        if not url or getattr(frame, "parent_frame", None) is None:
            return False
        if any(marker in url for marker in PAYMENT_CARD_FRAME_MARKERS):
            return True
        if not any(host in url for host in PAYMENT_FRAME_HOSTS):
            return False
        try:
            box = frame.frame_element().bounding_box() or {}
        except Exception:
            return False
        return float(box.get("width") or 0) >= _PAYMENT_WINDOW_MIN[0] and float(box.get("height") or 0) >= _PAYMENT_WINDOW_MIN[1]

    @staticmethod
    def _captcha_was_solved(frames: list[Any]) -> bool:
        """사람이 이미 통과했다는 공급자 표식만 확인한다 — 상호작용은 전혀 없다."""
        token_selector = (
            "textarea[name='g-recaptcha-response'], "
            "textarea[name='h-captcha-response'], "
            "input[name='cf-turnstile-response']"
        )
        for frame in frames:
            try:
                if int(frame.locator("#recaptcha-anchor[aria-checked='true']").count()):
                    return True
            except Exception:
                pass
            try:
                tokens = frame.locator(token_selector)
                if bool(
                    tokens.evaluate_all(
                        "nodes => nodes.some(node => String(node.value || '').trim().length > 0)"
                    )
                ):
                    return True
            except Exception:
                pass
        return False

    def gate_state(self, gate: dict[str, Any] | None = None) -> dict[str, Any]:
        """사람이 막힌 문을 열었는지 **싸게** 확인할 값들.

        지켜보는 쪽(HumanGateWatcher)이 20초마다 부르므로 비싸면 안 된다. 그래서
        페이지에 말을 걸지 않고 이미 있는 것만 읽는다: 지금 주소와 네이버 쿠키.

        브라우저가 다른 일로 바쁘면 그냥 모른다고 답한다 — 확인하려고 줄을 서면
        그 자체가 작업을 늦춘다. 모르면 다음 차례에 다시 보면 된다.
        """
        gate = dict(gate or {})
        try:
            # 프로세스가 재기동돼도 Chrome과 체크포인트는 살아 있다. 감시기가
            # 최초 브라우저 도구 호출만 기다리면 사람 문은 영원히 못 깨어난다.
            # attach는 기존 Chrome 프로세스·로그인·탭을 건드리지 않는다.
            self.start()
            snapshot = dict(
                self._submit(
                    lambda: self._gate_snapshot(
                        str(gate.get("url") or ""),
                        str(gate.get("wall_url") or ""),
                        [str(item) for item in (gate.get("hosts") or []) if str(item)],
                    ),
                    4,
                    # 감시기의 확인은 배경 일이다 — 작업 걸음이 오면 비킨다(아래 naver_session_alive 와 같은 이유).
                    operation="browser_internal:gate_state",
                    background=True,
                )
                or {}
            )
        except Exception:
            return {"known": False}
        session = self.naver_session_alive()
        return {
            "known": bool(snapshot.get("known")),
            "url": str(snapshot.get("url") or ""),
            "naver_signed_in": bool(session.get("signed_in")),
            "password_fields": snapshot.get("password_fields") if snapshot.get("known") else None,
            "password_gate": snapshot.get("password_gate") if snapshot.get("known") else None,
            "captcha": snapshot.get("captcha") if snapshot.get("known") else None,
            "payment": snapshot.get("payment") if snapshot.get("known") else None,
            "wall_url": snapshot.get("wall_url") if snapshot.get("known") else "",
            "windows": snapshot.get("windows") if snapshot.get("known") else None,
        }

    def _gate_snapshot(
        self,
        target_url: str = "",
        wall_url: str = "",
        expected_hosts: list[str] | None = None,
    ) -> dict[str, Any]:
        """체크포인트가 가리킨 탭을 다시 찾아 문 상태를 읽는다.

        프로세스가 재기동되면 ``self._page`` 선택은 보존되지 않는다. Chrome 탭은
        그대로인데 임의의 다른 탭을 읽으면, 사람이 이미 문을 열어도 대기 작업은
        영원히 깨어나지 않는다. 정확한 URL, 당시 popup URL, host 순으로 복구한다.
        탭을 전환하거나 항해하지 않는 읽기 전용 선택이다.
        """
        pages: list[Any] = []
        if self._context is not None:
            try:
                pages = [item for item in self._context.pages if not item.is_closed()]
            except Exception:
                pages = []
        if not pages and self._page is not None and not self._page.is_closed():
            pages = [self._page]
        if not pages:
            return {"known": False}

        def page_url(page: Any) -> str:
            try:
                return str(page.url or "")
            except Exception:
                return ""

        exact = {
            item.split("#", 1)[0]
            for item in (target_url, wall_url)
            if item
        }
        selected = next(
            (page for page in reversed(pages) if page_url(page).split("#", 1)[0] in exact),
            None,
        )
        hosts = {item.lower().lstrip(".") for item in (expected_hosts or []) if item}
        if selected is None and hosts:
            selected = next(
                (
                    page
                    for page in reversed(pages)
                    if any(
                        (host := (urlparse(page_url(page)).hostname or "").lower()) == wanted
                        or host.endswith("." + wanted)
                        for wanted in hosts
                    )
                ),
                None,
            )
        if selected is None:
            selected = self._page if self._page in pages else pages[0]
        wall = self._blocking_wall(selected)
        return {"url": page_url(selected), **wall}

    def _current_url(self) -> str:
        """브라우저 스레드에서 주소만 읽는다. 항해하지 않는다."""
        page = self._page
        if page is None or page.is_closed():
            return ""
        try:
            return str(page.url or "")
        except Exception:
            return ""

    def naver_session_alive(self) -> dict[str, Any]:
        """Is the browser profile still signed in to Naver?

        Answered from the cookie jar rather than by navigating, so asking is
        free and does not disturb whatever page is open. Only whether a session
        cookie exists is read -- never its value.

        The reason this is worth surfacing at all: Naver hands out session-only
        cookies unless '로그인 상태 유지' is ticked, and those die with the
        browser process. The user then discovers it mid-task, several minutes
        into something, as a mysterious editor failure.

        Routed through `_submit` like every other call that touches
        `_context`: Playwright's sync API is bound to the thread that created
        it, and this is read from the API's request thread, not the browser
        thread. Called directly the first time, it raised a greenlet
        cross-thread error instead of an answer -- caught in the same session
        that added it, before anyone downstream had to debug a health endpoint
        that intermittently threw.
        """
        # ★ **배경 일로 보낸다** (2026-10-01 운영 판 d60f38d3). 화면의 상태 확인(`/health` → naver_blog.status)이 몇 초마다
        #   이걸 부르는데, 전면 일로 등록돼 있어서 그 순간 들어온 손자리의 걸음(browser_page_data)이
        #   「앞 동작(browser_internal:naver_session_alive)을 0초째 실행 중」으로 거절됐다 — 상태 확인이 진짜 일을 밀어냈다.
        #   배경 일이면 작업 걸음은 몇 초 양보받아 기다리고, 작업 중엔 이쪽이 물러난다(모르면 known=False 로 답한다).
        try:
            cookies = self._submit(self._naver_cookies, 5.0, operation="browser_internal:naver_session_alive", background=True)
        except Exception as exc:
            return {"known": False, "reason": _clean(exc, 200)}
        if cookies is None:
            return {"known": False, "reason": "browser_not_started"}
        names = {str(cookie.get("name") or "") for cookie in cookies}
        signed_in = bool(names & _NAVER_SESSION_COOKIES)
        # A cookie with no expiry dies with the process; that is exactly the
        # state that keeps catching us out, so it is reported separately.
        session_only = any(
            cookie.get("name") in _NAVER_SESSION_COOKIES and not cookie.get("expires", 0) > 0
            for cookie in cookies
        )
        return {
            "known": True,
            "signed_in": signed_in,
            "survives_restart": signed_in and not session_only,
            "hint": (
                ""
                if not signed_in
                else "'로그인 상태 유지'가 꺼져 있어 브라우저가 닫히면 로그인이 풀립니다."
                if session_only
                else ""
            ),
        }

    def _naver_cookies(self) -> list[dict[str, Any]] | None:
        """Runs on the browser thread. `None` means no context to read yet."""
        with self._lock:
            context = self._context
        if context is None:
            return None
        return context.cookies("https://www.naver.com")

    def _frame_report(self, page: Any) -> str:
        """어느 프레임이 어떤 주소로 떠 있는지 한 줄로. 실패 메시지에 붙인다 —
        "제목을 못 찾음"만 남기면 다음 사람이 셀렉터부터 뒤지게 된다(실제로 그랬다)."""
        parts = []
        for index, frame in enumerate(self._frames_of(page)):
            name = self._frame_label(frame, index)
            parts.append(f"{name}({_clean(getattr(frame, 'url', '') or '', 80)})")
        return " | ".join(parts) or "(프레임 없음)"

    def _naver_blog_editor_frame(self, page: Any, *, timeout_ms: int | None = None) -> Any:
        """편집기가 실제로 그려진 프레임. 그려질 때까지 기다린다.

        ★ 2026-08-05 실측한 진짜 원인이 여기다. `iframe#mainFrame` 도 `.se-title-text`
        도 **맞는 값이었다** — 다만 그 순간에 아직 없었을 뿐이다.

        바깥 페이지의 domcontentloaded 는 편집기와 아무 상관이 없다. 그 시점에
        mainFrame 은 이제 막 `PostWriteForm.naver` 로 이동을 시작했고, 스마트에디터가
        DOM 을 그리는 건 그 뒤다. 그런데 예전 코드는 500ms 만 쉬고 `count()` 로
        **한 번** 물어봤다. count() 는 기다리지 않는다 — 0 이면 즉시 0 이다. 그래서
        캐시가 따뜻한 날엔 되고 식은 날엔 "naver_blog_element_missing:제목 영역" 이
        떴다(2026-08-04 성공, 2026-08-05 실패. 같은 코드였다).

        직접 재보고 확인: 열고 4초 뒤 mainFrame 에 `.se-title-text` 1개,
        `.se-text-paragraph` 2개가 정상적으로 있었다. 셀렉터 문제가 아니었다.

        프레임을 못 박지 않는 이유도 같다 — 못 박은 이름이 맞는지는 그 이름이 틀린
        날에만 알 수 있고, 그날 증상은 똑같이 "셀렉터가 안 맞는다"로 보인다.
        """
        limit = int(
            timeout_ms if timeout_ms is not None else self.config.naver_blog_editor_ready_timeout_ms
        )
        deadline = time.monotonic() + max(0.0, limit / 1000)
        while True:
            for frame in self._frames_of(page):
                for marker in _NAVER_EDITOR_MARKERS:
                    try:
                        if int(frame.locator(marker).count()) > 0:
                            return frame
                    except Exception:
                        continue
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        raise RuntimeError(
            f"naver_blog_editor_not_ready:{limit}ms 안에 편집기가 뜨지 않았습니다:"
            f"{self._frame_report(page)}"
        )

    def _naver_blog_open_editor(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        self._goto_page(
            page,
            "https://blog.naver.com/GoBlogWrite.naver",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(500)
        self._naver_blog_check_intervention(page)
        # The draft-restore confirm is raised by the editor as it boots, so it
        # can only be cleared after the navigation, not before.
        dismissed = self._naver_blog_dismiss_popups(page)
        # "열었다"는 편집기가 실제로 그려졌다는 뜻이어야 한다. 이걸 확인 안 하고
        # 성공을 반환하던 것이, 뒤따르는 fill_editor 가 빈 화면을 뒤지다 실패하던
        # 이유였다 — 실패는 두 번째 도구에서 났지만 원인은 여기 있었다.
        frame = self._naver_blog_editor_frame(page)
        return self._evidence(
            "naver_blog_editor_opened",
            popups_dismissed=dismissed,
            editor_frame=self._frame_label(frame, 0),
        )

    def _naver_blog_read_account(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        self._naver_blog_check_intervention(page)
        account = ""
        title_text = ""
        try:
            frame = page.frame_locator("iframe#mainFrame")
            account = _clean(
                frame.locator(".se-blog-icon-area .se-blog-name, .blog_id, .nick_name")
                .first.inner_text(timeout=1500),
                120,
            )
        except Exception:
            pass
        try:
            frame = page.frame_locator("iframe#mainFrame")
            title_text = _clean(
                frame.locator(".se-title-text, .se-documentTitle").first.inner_text(timeout=1500),
                200,
            )
        except Exception:
            pass
        return self._evidence("naver_blog_account_read", account=account, title_text=title_text)

    def _naver_blog_fill_editor(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        self._naver_blog_check_intervention(page)
        title = str(arguments.get("title") or "")[:200]
        body = str(arguments.get("body") or "")
        plain_body = markdown_to_editor_text(body)
        tags = list(arguments.get("tags") or [])
        # 하드코딩된 iframe 대신, 편집기가 실제로 있는 프레임을 기다려서 찾는다.
        frame = self._naver_blog_editor_frame(page)
        dismissed = self._naver_blog_dismiss_popups(page)

        title_box = self._first_present(
            frame,
            ".se-title-text, .se-documentTitle .se-text-paragraph",
            ".se-documentTitle [contenteditable='true']",
            ".se-documentTitle",
            what="제목 영역",
            # 프레임은 이미 준비된 것을 받았지만, 제목 칸이 본문 문단보다 한 틱 늦게
            # 그려지는 경우까지 이 몇 초가 덮는다.
            wait_ms=4000,
        )
        self._naver_blog_click(title_box, what="제목 영역", page=page)
        page.keyboard.type(title, delay=6)

        # `.se-main-container` does not exist in this editor at all -- probed
        # live on 2026-08-05, which is why every selector built on that prefix
        # matched nothing and the click timed out as "본문 영역". The real
        # structure is flat: `.se-text-paragraph` appears exactly twice, one of
        # them inside `.se-documentTitle`. So the body is "the paragraph that
        # is not the title", which needs no container name to express.
        body_box = frame.locator(
            ".se-text-paragraph:not(.se-documentTitle .se-text-paragraph)"
        ).first
        self._naver_blog_click(body_box, what="본문 영역", page=page)
        # 한 글자씩 두드리지 않는다. insert_text 는 키 이벤트를 만들지 않아 자동 목록
        # 변환·IME 조합을 건드리지 않고, 979자에 3ms 씩 두드리며 DOM 이 다시 그려질
        # 틈을 주던 것도 사라진다. 없는 환경(테스트 가짜 페이지)에서는 예전 방식으로.
        keyboard = page.keyboard
        insert = getattr(keyboard, "insert_text", None)
        for index, line in enumerate(plain_body.splitlines() or [""]):
            if index:
                keyboard.press("Enter")
                page.wait_for_timeout(30)
            if not line:
                continue
            if callable(insert):
                insert(line)
            else:
                keyboard.type(line, delay=3)

        # 태그. **한 개씩 실패를 삼키며 계속 가면 안 된다.**
        #
        # 2026-08-09: 이 자리가 글 하나를 통째로 날렸다. 태그 칸을 못 찾으면
        # `tag_input.click()` 이 기본 액션 타임아웃(20초)을 꽉 채우고 예외를 내는데,
        # `continue` 라서 다음 태그가 또 20초를 쓴다. 태그 11개 = **220초**다.
        # 잡 전체 예산이 180초(browser_task_timeout_sec)라 그 안에서 시간이 끊겼고,
        # 본문은 이미 다 들어갔는데 도구는 실패로 보고됐다.
        #
        # 게다가 사람이 실측해 못 박은 레시피(recipes/naver_blog.json)에는 태그
        # 셀렉터가 아예 없다 — 이 편집기에 태그 칸이 있다는 근거가 처음부터 없었다.
        #
        # 그래서 둘을 바꾼다: 있는지 먼저 **기다리지 않고** 세어 보고(count 는 즉답),
        # 하나가 막히면 나머지도 막힌 것이므로 **거기서 멈춘다.**
        tags_added = 0
        tags_skipped = ""
        if tags:
            tag_locator = frame.locator(".se-tag-input, .se-tag-area input")
            try:
                present = int(tag_locator.count())
            except Exception:
                present = 0
            if not present:
                tags_skipped = "editor_has_no_tag_field"
            else:
                tag_input = tag_locator.first
                for tag in tags[:30]:
                    try:
                        tag_input.click(timeout=_TAG_ACTION_TIMEOUT_MS)
                        tag_input.type(str(tag)[:30], delay=6)
                        page.keyboard.press("Enter")
                        tags_added += 1
                    except Exception:
                        tags_skipped = "tag_input_stopped_responding"
                        break

        # ★ 넣었다고 끝내지 않는다 — 넣은 것이 화면에 그대로 있는지 읽어서 견준다.
        #
        # 2026-08-05: 순서가 멀쩡한 979자를 넣었는데 편집기 안에서 문단이 뒤섞였다
        # (`## 2` 절이 `## 3` 뒤로 가고, 한 줄이 중간에서 잘려 앞쪽에 붙었다). 그런데
        # 도구는 성공을 반환했다. 타이핑이 "먹었는지"만 알고 "무엇이 남았는지"를 안
        # 봤기 때문이다. 이건 임시저장의 draft_count 검증과 같은 규칙이다.
        landed = self._naver_blog_body_text(frame)
        expected, actual = _comparable(plain_body), _comparable(landed)
        verified = bool(expected) and expected in actual
        return self._evidence(
            "naver_blog_editor_filled",
            title=title,
            body_length=len(plain_body),
            body_chars_landed=len(landed),
            tag_count=len(tags),
            # 태그가 실제로 몇 개 들어갔는지. 요청 개수만 돌려주면 "태그도 넣었다"는
            # 거짓 보고가 그대로 답변에 실린다.
            tags_added=tags_added,
            **({"tags_skipped": tags_skipped} if tags_skipped else {}),
            popups_dismissed=dismissed,
            # `verified` 라는 이름을 쓰는 이유: 되돌릴 수 없는 클릭·저장 검증과 같은
            # 이름이라야 상위 계층(확인 요청 판정, 답변 사실 검증)이 함께 읽는다.
            verified=verified,
            body_mismatch="" if verified else "넣은 본문과 화면의 본문이 다릅니다",
        )

    def _naver_blog_body_text(self, frame: Any) -> str:
        """편집기 본문에 실제로 남은 글. 제목 문단은 뺀다."""
        for selector in (
            ".se-text-paragraph:not(.se-documentTitle .se-text-paragraph)",
            ".se-component-content",
            "body",
        ):
            try:
                locator = frame.locator(selector)
                count = int(locator.count())
            except Exception:
                continue
            if not count:
                continue
            parts = []
            for index in range(min(count, 400)):
                try:
                    parts.append(locator.nth(index).inner_text(timeout=1200))
                except Exception:
                    continue
            text = "\n".join(parts).strip()
            if text:
                return text
        return ""

    def _naver_blog_upload_image(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        self._naver_blog_check_intervention(page)
        path = str(arguments.get("path") or "")
        if not path:
            raise ValueError("naver_blog_image_path_required")
        frame = page.frame_locator("iframe#mainFrame")
        self._naver_blog_dismiss_popups(page)
        with page.expect_file_chooser() as chooser_info:
            frame.locator(".se-toolbar-item-image button, button[data-name='image']").first.click()
        chooser = chooser_info.value
        chooser.set_files(path)
        page.wait_for_timeout(900)
        return self._evidence("naver_blog_image_uploaded", path=path)

    def _naver_blog_capture_screen(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        directory = self.config.output_dir / "naver-blog-previews"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"preview-{int(time.time() * 1000)}.png"
        page.screenshot(path=str(path), full_page=True)
        return self._evidence("naver_blog_screen_captured", screenshot_path=str(path))

    @staticmethod
    def _naver_blog_draft_count(frame: Any) -> int:
        """Saved-draft count shown next to 저장. -1 when it cannot be read."""
        for selector in (".save_btn__bzc5B", ".btn_save", "[class*='save_btn']", ".btn_save_list"):
            try:
                locator = frame.locator(selector).first
                if not locator.is_visible():
                    continue
                text = _clean(locator.inner_text(timeout=1200), 60)
            except Exception:
                continue
            match = re.search(r"\d+", text)
            if match:
                return int(match.group())
        return -1

    def _naver_blog_wait_for_draft_saved(
        self, page: Any, frame: Any, *, count_before: int
    ) -> dict[str, Any]:
        """Look for proof the draft landed, rather than assuming the click did it.

        Two independent signals because either one can be missing: the saved
        toast is transient, and the draft counter is unreadable when the header
        markup changes. Not finding proof is reported as not finding proof --
        the caller turns that into a failure, never into "저장 완료".
        """
        deadline = time.monotonic() + max(1, self.config.naver_blog_save_verify_timeout_sec)
        count_after = count_before
        while True:
            try:
                body_text = _clean(frame.locator("body").inner_text(timeout=1200), 6000)
            except Exception:
                body_text = ""
            marker = next((m for m in _NAVER_DRAFT_SAVED_MARKERS if m in body_text), "")
            if marker:
                return {"verified": True, "evidence": f"page_text:{marker}", "count_after": count_after}
            count_after = self._naver_blog_draft_count(frame)
            if count_before >= 0 and count_after > count_before:
                return {
                    "verified": True,
                    "evidence": f"draft_count:{count_before}->{count_after}",
                    "count_after": count_after,
                }
            if time.monotonic() >= deadline:
                return {"verified": False, "evidence": "", "count_after": count_after}
            page.wait_for_timeout(500)

    def _naver_blog_click_save_draft(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        self._naver_blog_check_intervention(page)
        frame = page.frame_locator("iframe#mainFrame")
        dismissed = self._naver_blog_dismiss_popups(page)
        count_before = self._naver_blog_draft_count(frame)
        save_button = frame.locator(".save_btn__bzc5B, .btn_save, button:has-text('저장')").first
        self._naver_blog_click(save_button, what="임시저장 버튼", page=page)
        page.wait_for_timeout(700)
        outcome = self._naver_blog_wait_for_draft_saved(page, frame, count_before=count_before)
        # 저장이 **확인됐을 때만** 창을 닫는다.
        #
        # 확인 안 된 채로 닫으면 증거가 사라진다. 2026-08-09 에 정확히 그 상황이
        # 있었다 — 도구는 실패라고 했는데 편집기에는 본문이 다 들어가 있었고, 그
        # 창이 열려 있었기 때문에 그 사실을 알 수 있었다. 닫아 버렸다면 "안 됐구나"
        # 하고 다시 실행했을 것이고, 그러면 내용이 두 번 들어간다.
        self._close_after_action = bool(
            outcome["verified"] and self.config.naver_blog_close_after_save
        )
        return self._evidence(
            "naver_blog_draft_save_attempted",
            saved_verified=outcome["verified"],
            saved_evidence=outcome["evidence"],
            draft_count_before=count_before,
            draft_count_after=outcome["count_after"],
            popups_dismissed=dismissed,
        )

    def _naver_blog_click_publish(self, page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        self._naver_blog_check_intervention(page)
        frame = page.frame_locator("iframe#mainFrame")
        dismissed = self._naver_blog_dismiss_popups(page)
        url_before = str(getattr(page, "url", "") or "")
        publish_button = frame.locator(".publish_btn__m9KHH, .btn_publish, button:has-text('발행')").first
        self._naver_blog_click(publish_button, what="발행 버튼", page=page)
        page.wait_for_timeout(500)
        try:
            frame.locator("button:has-text('발행'), .confirm_btn").first.click(timeout=3000)
        except Exception:
            pass
        self._naver_blog_check_intervention(page)
        # Leaving the write URL is the one publish signal that does not depend on
        # a guessed class name: the editor navigates to the published post.
        deadline = time.monotonic() + max(1, self.config.naver_blog_save_verify_timeout_sec)
        url_after = url_before
        while True:
            page.wait_for_timeout(600)
            url_after = str(getattr(page, "url", "") or "")
            if url_after != url_before and "blogwrite" not in url_after.lower():
                break
            if time.monotonic() >= deadline:
                break
        published = url_after != url_before and "blogwrite" not in url_after.lower()
        # 임시저장과 같은 규칙 — 확인됐을 때만 닫는다.
        self._close_after_action = bool(published and self.config.naver_blog_close_after_save)
        return self._evidence(
            "naver_blog_publish_attempted",
            published_verified=published,
            url_before=url_before,
            url_after=url_after,
            popups_dismissed=dismissed,
        )


class BrowserTools:
    def __init__(self, config: JarvisConfig, worker: BrowserWorker) -> None:
        self.config = config
        self.worker = worker
        self._definitions = self._build_definitions()

    @staticmethod
    def _function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                },
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        definitions = [
            self._function(
                "browser_search",
                "보이는 Chrome에서 웹을 검색하고 **결과 목록**을 순위·제목·주소·요약으로 돌려준다. "
                "auto는 한국어·국내 검색을 네이버, 해외 기술 검색을 Bing으로 보내며 차단 시 자동 전환한다. "
                "블로그 후기·사례를 찾을 때는 tab=\"blog\"를 써라 — 통합검색은 나무위키·쇼핑이 앞을 차지한다. "
                "결과를 고른 뒤에는 browser_open_result 로 들어가라.",
                {
                    "query": {"type": "string"},
                    "engine": {"type": "string", "enum": ["auto", "naver", "bing", "google"]},
                    "tab": {
                        "type": "string",
                        "enum": ["all", "blog", "cafe", "news", "kin", "video"],
                        "description": "네이버 전용 검색 탭. 기본 all(통합검색).",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                        "description": "최근 것만(네이버는 news 탭에서만). 「오늘 뉴스」는 day — 안 주면 몇 주 전 기사가 앞에 온다.",
                    },
                    "limit": {"type": "integer", "description": "결과 개수, 기본 12"},
                },
                ["query"],
            ),
            self._function(
                "browser_site_search",
                "**지금 열려 있는 사이트 안에서** 그 사이트의 검색으로 찾는다. "
                "잡코리아·사람인 같은 서비스의 최신 목록은 검색엔진이 아니라 그 사이트가 가지고 있다 — "
                "네이버 검색어에 사이트 이름을 끼워 넣지 말고, browser_open_result 로 그 사이트에 "
                "**들어간 뒤** 이걸 써라. 주소를 지어내서 직행하지 마라.",
                {
                    "query": {"type": "string", "description": "그 사이트 검색칸에 넣을 말"},
                    "limit": {"type": "integer", "description": "받아올 결과 수, 기본 15"},
                    "scroll": {
                        "type": "integer",
                        "description": "무한스크롤을 몇 번 내려서 더 불러올지. 기본 0(안 내림)",
                    },
                },
                ["query"],
            ),
            self._function(
                "browser_load_more",
                "지금 화면의 목록을 **더 불러온다**(무한스크롤로 내리고, 안 늘면 '더보기'를 누른다). "
                "한 화면만 보고 '이게 전부'라고 하지 마라 — 화면에 열 개가 보여도 목록은 수백 개일 수 있다. "
                "불러온 뒤 순위를 다시 매기므로 browser_open_result 로 바로 들어갈 수 있다.",
                {
                    "rounds": {"type": "integer", "description": "몇 번 내릴지, 기본 3 (최대 8)"},
                    "limit": {"type": "integer", "description": "받아올 결과 수, 기본 20"},
                },
            ),
            self._function(
                "browser_close",
                "브라우저 창을 닫는다. 브라우저로 할 일이 다 끝났을 때 부른다 — 조사·작성이 "
                "끝났는데 창을 켜 둘 이유가 없다. 다음에 브라우저가 필요하면 알아서 다시 열리므로 "
                "닫는다고 잃는 것은 없다. 아직 확인할 것이 남아 있으면 부르지 마라.",
                {},
                [],
            ),
            self._function(
                "browser_open_result",
                "마지막 검색 결과의 rank 번째로 들어간다. 목록으로 돌아갈 필요 없이 다른 rank 를 "
                "바로 열 수 있다. 이미 본 것은 결과에 visited=true 로 표시돼 있다. "
                "목록에서 본 제목이 있으면 title 에 그 제목(일부)을 주면 순위 대신 그 제목의 결과를 연다.",
                {"rank": {"type": "integer"}, "title": {"type": "string"}},
                ["rank"],
            ),
            self._function(
                "browser_extract",
                "지금 페이지의 **본문만** 추려 읽는다. 메뉴·사이드바·추천글을 뺀다. "
                "글 한 편을 읽을 때는 browser_read 대신 이걸 써라 — read 는 화면 글을 전부 준다.",
                {"max_chars": {"type": "integer"}},
            ),
            self._function(
                "browser_links",
                "지금 페이지에서 더 들어가 볼 수 있는 링크 목록. 글 안에서 다음 단서를 찾을 때 쓴다. "
                "same_site=inside 는 같은 사이트 안(연재 다음 편·태그), outside 는 바깥 출처만 본다.",
                {
                    "same_site": {"type": "string", "enum": ["any", "inside", "outside"]},
                    "contains": {"type": "string", "description": "이 낱말이 링크 글자나 주소에 있는 것만"},
                    "limit": {"type": "integer"},
                },
            ),
            self._function(
                "browser_find",
                "지금 화면에서 글자로 요소를 찾아 ref 를 받는다. 무엇을 누를지 이미 아는 경우 "
                "browser_snapshot 으로 전체를 받는 것보다 이걸 써라 — 훨씬 짧다.",
                {
                    "query": {"type": "string"},
                    "regex": {"type": "boolean"},
                    "limit": {"type": "integer"},
                    "include_box": {"type": "boolean"},
                },
                ["query"],
            ),
            self._function("browser_open", "HTTP 또는 HTTPS 주소를 연다. 목록의 javascript:함수(번호) 링크도 그대로 넣으면 그 페이지의 함수로 따라간다.", {"url": {"type": "string"}}, ["url"]),
            self._function("browser_snapshot", "현재 페이지에서 클릭하거나 입력할 수 있는 요소의 ref 목록을 읽는다. iframe 안까지 모두 포함한다.", {"limit": {"type": "integer"}, "include_box": {"type": "boolean"}}),
            # Diagnostic. `samples` answers the question that always follows a
            # count -- "is it matching the thing I mean?" -- with the text and
            # geometry of the first few hits.
            self._function(
                "browser_probe_frames",
                "각 프레임에서 주어진 CSS 선택자가 몇 개나 잡히는지 세어 본다. 화면을 바꾸지 않는 진단용이다.",
                {
                    "selectors": {"type": "array", "items": {"type": "string"}},
                    "samples": {"type": "boolean"},
                },
            ),
            self._function(
                "browser_download",
                # ★ 2026-10-18 LH 공고 판(760b04f4): 첨부가 `javascript:` 링크라 주소가 없었고, 모델은 화면 주소를 넘겨
                #   HTML 을 `.pdf` 로 받았다. 주소를 모르는 첨부는 browser_find 의 ref 로 받는다 — 도구가 눌러 붙잡는다.
                "PDF·한글·워드·엑셀 같은 **첨부 문서**를 지금 브라우저 세션 그대로 받아 저장하고, 읽을 수 있는 문서면 "
                "**본문을 결과의 content 에 실어 준다**(로그인 뒤 자료도 된다). 파일 주소를 알면 url, 주소가 안 보이는 "
                "첨부 링크(공공기관 게시판의 javascript 링크 등)는 browser_find 로 찾은 그 링크의 ref 를 넘겨라. "
                "웹 화면 주소를 넘기지 마라 — 화면은 문서가 아니다. 화면에 띄워 눈으로 읽지 마라.",
                {
                    "url": {"type": "string", "description": "파일 자체의 주소(화면 주소 아님)"},
                    "ref": {"type": "string", "description": "browser_find 가 준 첨부 링크의 ref — 주소가 없는 첨부는 이것으로"},
                    "name": {"type": "string", "description": "저장할 파일 이름(생략 가능)"},
                    "max_chars": {"type": "integer", "description": "결과에 실을 본문 글자 수(기본 20000, 최대 30000)"},
                },
            ),
            self._function(
                "browser_screenshot",
                # ★ 설명이 할 수 없는 일을 할 수 있다고 하면 걸음을 버린다 (2026-10-04 대표 관찰 — 사다리 L2: 「스크린샷을
                #   저장했지만 이미지 내용은 눈으로 확인할 수 없으니…」). 이 손은 파일을 남길 뿐, 그림이 모델에게 가지 않는다.
                "지금 화면을 PNG 파일로 저장한다 — 사람에게 남길 증거용이다. **너는 이 그림을 볼 수 없다.** "
                "화면에 무엇이 있는지는 browser_snapshot·browser_read 로 확인해라.",
                {"label": {"type": "string"}, "full_page": {"type": "boolean"}},
            ),
            self._function(
                "browser_dismiss_dialog",
                "클릭을 가로막는 팝업·동의창을 정리한다. 취소·닫기 같은 부정 버튼만 자동으로 누르며, 확인이 필요한 창은 문구를 알리고 멈춘다.",
                {"rounds": {"type": "integer"}},
            ),
            self._function("browser_read", "현재 페이지의 보이는 본문을 읽는다.", {"max_chars": {"type": "integer"}, "selector": {"type": "string"}}),
            # `expect` is how a click stops being a claim. Without it the tool
            # can only report that it pressed something, which is exactly what
            # was reported the night nothing was actually saved.
            self._function(
                "browser_click",
                "snapshot에서 받은 ref 요소를 클릭한다. 읽기 모드에서는 전송·삭제·구매 동작이 차단된다. "
                "무언가를 바꾸는 클릭이면 expect로 확인 방법을 함께 줘라 — 화면에서 증거를 못 읽으면 "
                "verified=false로 돌아오며, 그때 다시 누르면 두 번 저장된다.",
                {
                    "ref": {"type": "string"},
                    "expect": {
                        "type": "object",
                        "description": "확인 방법. kind는 text_appears·text_disappears·appears·disappears·"
                        "url_changes·count_increases·number_increases 중 하나. "
                        "text_appears는 value에 문구를, 나머지 selector 계열은 selector를 준다.",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "text_appears", "text_disappears", "appears", "disappears",
                                    "url_changes", "count_increases", "number_increases",
                                ],
                            },
                            "value": {"type": "string"},
                            "selector": {"type": "string"},
                        },
                    },
                    "verify_timeout_ms": {"type": "integer"},
                },
                ["ref"],
            ),
            self._function(
                "browser_site_sources",
                "지금 사이트가 **공개한 출처**를 찾는다: 페이지가 선언한 RSS·Atom 피드, robots.txt 의 사이트맵과 이 경로의 "
                "자동 수집 허용 여부, 공식·개발사·게시자 링크. 봇 검사·로그인 벽으로 막혔거나 값이 안 보일 때, 같은 곳을 다시 "
                "두드리는 대신 쓴다. robots.txt 하나만 짧게 읽는다.",
                {},
            ),
            self._function(
                "browser_page_data",
                "지금 페이지가 화면을 그리려고 **이미 받아 온** 같은 사이트 JSON 응답에서 값을 찾는다(새 요청 없음). "
                "query 에 찾을 값(상품명·공고명·가격 등)을 주면 그 값이 든 묶음을, 비우면 응답의 모양만 준다. "
                "화면 글자가 난독화·캔버스·가상 스크롤이라 안 읽힐 때 쓴다. 토큰·비밀번호 같은 칸은 가려진다.",
                {"query": {"type": "string"}},
            ),
            self._function(
                "browser_click_at",
                "화면 **좌표**(x, y — 창 안 CSS 픽셀)를 누른다. 스냅샷 목록이 못 읽는 화면(닫힌 웹 컴포넌트·캔버스) 전용이다. "
                "좌표는 지어내지 말고 결과에 온 것을 써라: 스냅샷 `unreadable_structure` 의 targets, "
                "browser_snapshot include_box 의 box, browser_probe_frames 의 box(가운데를 눌러라). "
                "누르기 전에 그 점의 요소 이름을 읽어 browser_click 과 같은 안전 검사를 한다(결제·삭제·설치 등은 막힌다).",
                {"x": {"type": "integer"}, "y": {"type": "integer"}},
                ["x", "y"],
            ),
            self._function(
                "browser_type_at",
                "화면 **좌표**의 입력칸을 눌러 글자를 친다(submit=true 면 Enter). browser_click_at 과 같은 경우에만 쓴다 — "
                "ref 가 있으면 browser_fill 을 써라. 비밀번호 칸에는 치지 않는다.",
                {"x": {"type": "integer"}, "y": {"type": "integer"}, "text": {"type": "string"},
                 "submit": {"type": "boolean"}},
                ["x", "y", "text"],
            ),
            self._function(
                "browser_hover",
                "마우스를 올려놓기만 한다(누르지 않는다). 국내 쇼핑·포털의 카테고리 메뉴는 "
                "**누르는 것이 아니라 올려놓는 것**이라, 하위 목록이 올리기 전까지는 화면에 아예 없다. "
                "올린 뒤 새로 나타난 것들을 appeared 로 돌려준다. 아무것도 안 나타나면 호버 메뉴가 "
                "아니라는 뜻이니 그때 browser_click 으로 눌러라. "
                "★ 메뉴가 열린 채로 있는 동안 눌러야 하므로 **바로 다음 걸음에** 누르거나 스냅샷을 떠라.",
                {"ref": {"type": "string"}},
                ["ref"],
            ),
            self._function(
                "browser_verify",
                "지금 화면에 특정 문구나 요소가 나타났는지 확인한다. 클릭 결과를 뒤늦게 확인할 때 쓴다.",
                {
                    "expect": {"type": "object", "properties": {
                        "kind": {"type": "string"},
                        "value": {"type": "string"},
                        "selector": {"type": "string"},
                    }},
                    "timeout_ms": {"type": "integer"},
                },
                ["expect"],
            ),
            self._function("browser_scroll", "현재 페이지를 위나 아래로 스크롤한다.", {"amount": {"type": "integer", "description": "양수는 아래, 음수는 위"}}),
            self._function("browser_tabs", "열린 탭 목록을 확인한다.", {}),
            self._function("browser_switch_tab", "탭 목록의 index로 활성 탭을 바꾼다.", {"index": {"type": "integer"}}, ["index"]),
            self._function("browser_back", "현재 탭에서 뒤로 이동한다.", {}),
            self._function("browser_wait", "동적 페이지가 갱신되기를 잠깐 기다린다.", {"milliseconds": {"type": "integer"}}),
        ]
        definitions.extend(
            [
                self._function("browser_fill", "입력 요소에 값을 채운다. 비밀번호·파일 입력은 차단되며 제출은 별도 승인 단계로 처리한다.", {"ref": {"type": "string"}, "value": {"type": "string"}}, ["ref", "value"]),
                self._function(
                    "browser_pick_suggestion",
                    "입력란에 치면 **밑에 목록이 뜨는** 칸에서 항목을 고른다(기술 태그·주소 검색·사람 찾기 등). "
                    "치고·기다리고·다시 보고·고르는 것까지 한 번에 한다. "
                    "★ browser_fill 로 글자만 넣으면 목록에서 안 골라져 **등록이 안 된다** — 이 도구를 써라. "
                    "text 를 비우면 **눌러야 목록이 뜨는 칸**(커스텀 셀렉트)에도 쓸 수 있다. "
                    "맞는 항목이 없으면 아무것도 누르지 않고 후보 목록을 돌려준다.",
                    {
                        "ref": {"type": "string", "description": "입력란 또는 셀렉트의 ref"},
                        "text": {"type": "string", "description": "칠 글자 (예: Python). 누르기만 할 땐 비운다"},
                        "field": {
                            "type": "string",
                            "description": "그 칸의 이름(예: 경험). ref 가 낡았을 때 이 이름으로 다시 찾는다",
                        },
                        "choose": {
                            "type": "string",
                            "description": "고를 항목의 글자. 생략하면 text 와 같게 본다",
                        },
                    },
                    ["ref", "choose"],
                ),
                self._function(
                    "browser_click_confirmed",
                    "결제·구매·삭제·발행처럼 되돌릴 수 없는 버튼을 누른다. 화면 승인을 받은 뒤에 "
                    "실행된다. 일반 버튼은 browser_click 을 써라.",
                    {"ref": {"type": "string"}, "expect": {"type": "object"}},
                    ["ref"],
                ),
                self._function(
                    "browser_fill_form",
                    "여러 입력란을 한 번에 채운다. 칸마다 따로 부르지 말고 이걸 써라. "
                    "중간에 실패하면 몇 번째에서 멈췄는지 알려주며 나머지는 채우지 않는다.",
                    {
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"ref": {"type": "string"}, "value": {"type": "string"}},
                            },
                        }
                    },
                    ["fields"],
                ),
                self._function(
                    "browser_select_option",
                    "드롭다운(select)에서 항목을 고른다. label은 보이는 글자, value는 내부 값이다. "
                    "div로 만든 커스텀 드롭다운은 browser_click으로 열고 골라야 한다.",
                    {"ref": {"type": "string"}, "label": {"type": "string"}, "value": {"type": "string"}},
                    ["ref"],
                ),
                self._function(
                    "browser_file_upload",
                    "파일 첨부란에 이 PC의 파일을 올린다. 허용된 폴더(바탕화면·문서·다운로드) 안의 "
                    "파일만 가능하며, 실행 전에 화면 승인을 받는다.",
                    {"ref": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}},
                    ["ref", "paths"],
                ),
                self._function(
                    "browser_handle_dialog",
                    "브라우저 확인창(alert·confirm·prompt)에 **어떻게 답할지 미리 정한다** — 확인창은 뜨는 즉시 답해 버리므로, "
                    "확인창을 띄울 버튼을 누르기 **전에** 부른다(다음 확인창 한 번에만 쓰인다). accept 를 생략하면 취소다. "
                    "따로 정하지 않으면: 이 PC 안 페이지(localhost·file)는 확인, 밖의 사이트는 취소로 답한다.",
                    {
                        "accept": {"type": "boolean"},
                        "prompt_text": {"type": "string", "description": "prompt 창에 넣을 값"},
                    },
                ),
                self._function("browser_press", "입력 요소에서 키를 누른다. 보호 모드에서는 Enter 제출이 차단된다.", {"ref": {"type": "string"}, "key": {"type": "string"}}, ["ref", "key"]),
            ]
        )
        return definitions

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def register(self, gateway: ToolGateway) -> None:
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            # 업로드만 L2다. 나머지와 달리 이 PC의 파일이 바깥으로 나가는 동작이고,
            # 한 번 나가면 되돌릴 수 없다 — 사람이 화면에서 보고 승인해야 한다.
            if name in {"browser_file_upload", "browser_click_confirmed"}:
                risk = RiskLevel.L2
            elif name in {"browser_fill", "browser_fill_form", "browser_press", "browser_type_at",
                          "browser_select_option", "browser_pick_suggestion",
                          "browser_handle_dialog"}:
                risk = RiskLevel.L1
            # `browser_site_search` 는 글자를 넣지만 여기 아래(L0)로 둔다. 검색은
            # 읽기다 — 아무것도 저장·제출하지 않고 목록만 받아 온다. L1 로 올리면
            # 읽기 전용 모드에서 사이트 검색이 막히는데, 그건 원래 고장보다 나쁘다.
            else:
                risk = RiskLevel.L0
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=risk,
                    inverse=self._inverses().get(name),
                    proof=self._proofs().get(name),
                    handler=lambda args, action=name: self.worker.execute(action, args),
                    enabled=self.config.browser_enabled,
                )
            )
        # 되돌릴 수 없는 버튼을 `browser_click` 으로 누르려 하면 게이트웨이가 그 자리에서
        # 같은 인자로 승인 카드를 띄운다 — 모델이 승인 도구를 다시 부를 때까지 기다리지 않는다.
        gateway.approval_escalations["browser_click"] = (
            "irreversible_click_needs_approval", "browser_click_confirmed",
        )

    def _proofs(self) -> dict[str, ProofSpec]:
        return {
            "browser_click_confirmed": ProofSpec(
                capture_before=lambda args: self.worker.capture_confirmed_click_proof(
                    args, screenshot=True
                ),
                capture_current=lambda args: self.worker.capture_confirmed_click_proof(
                    args, screenshot=False
                ),
                capture_after=lambda args, result: self.worker.capture_confirmed_click_after(
                    args, result
                ),
                same_target=same_fingerprint,
                finalize=finalize_proof,
            )
        }

    def _inverses(self) -> dict[str, InverseSpec]:
        """브라우저 동작 중 **되돌릴 수 있는 것.**

        ## 왜 채우기 하나뿐인가 (2026-08-15)

        사용자: "자비스가 잘못 눌렀는데 물릴 방법이 없다." 맞는 말이라 브라우저에도
        역동작을 달았는데, **정직하게 달 수 있는 것은 채우기 하나**다.

            browser_fill    원래 값으로 다시 채우면 원래대로다. 잡아 둘 수 있다.
            browser_click   무엇이 일어나는지 일반적으로 알 수 없다. 토글이면 한 번 더
                            누르면 되지만 제출이면 그러면 두 번 낸다. **모르면서 되돌리는
                            척하는 것이 제일 나쁘다.**
            browser_press   같은 이유(Enter 가 제출인지 아닌지 모른다).
            browser_open    돌아가는 것은 browser_back 이지 되돌리기가 아니다.

        누르기를 되돌리는 길은 **그 사이트를 아는 레시피**에 있다(`site_recipes`
        의 action `undo`). 범용으로는 못 하고, 사이트별로는 이미 할 수 있다.
        """
        return {
            # 되돌릴 수 없는 제출에도 **돌아갈 길은 적어 둔다** (13-3).
            #
            # 레시피가 있는 사이트는 절차가 역동작을 선언한다(`site_recipes`).
            # 레시피가 없는 사이트에서 폼을 내면 지금까지 **아무 기록도 안 남았다** —
            # 채우기에는 되돌리기가 붙었는데 정작 제출이 비어 있었다.
            #
            # 자동으로는 못 되돌린다(무엇이 일어나는지 사이트마다 다르다). 그래서
            # `undo=None` 으로 두고 **어디에서 무엇을 냈는지**를 남긴다 — 되돌리려면
            # 먼저 찾을 수 있어야 한다. 발행(naver_blog_publish)의 일반화다.
            "browser_click_confirmed": InverseSpec(
                label="방금 제출한 것 찾아가기",
                handle_from=lambda result: BrowserTools._submit_handle_of(self, result),
                undo=None,  # 무엇이 일어났는지 모른다 — 아는 척하지 않는다
                manual_hint=(
                    "이 제출은 손자리가 자동으로 못 되돌립니다(무엇이 일어나는지 사이트마다 "
                    "다릅니다). 아래 주소로 가서 취소·수정할 수 있는지 보세요. "
                    "자주 쓰는 사이트라면 레시피에 취소 절차를 넣어 두면 다음부터는 "
                    "손자리가 직접 되돌립니다."
                ),
            ),
            # ★ 평범한 누르기에도 되돌리기가 붙는다 — **표준이 토글이라고 말한 것에 한해.**
            # `aria-pressed`/`aria-checked` 가 뒤집혔으면 같은 것을 다시 누르는 것이
            # 역동작이고, 그건 사이트를 몰라도 알 수 있다. 클래스 변화로 짐작하지 않는
            # 이유는 `_toggle_state` 에 — 제출 버튼도 누르면 클래스가 바뀐다.
            "browser_click": InverseSpec(
                label="방금 켠/끈 것을 되돌리기",
                handle_from=lambda result: BrowserTools._toggle_handle_of(self, result),
                undo=lambda handle: BrowserTools._undo_toggle_of(self, handle),
            ),
            "browser_fill": InverseSpec(
                label="방금 채운 칸을 원래 값으로 되돌리기",
                # 손잡이 뽑기는 인스턴스가 필요 없다(결과만 본다). 클래스에서 가져오면
                # 시험이 워커 없이도 이 지도를 확인할 수 있다 — 무엇에 되돌리기를
                # **안** 달았는지가 이 지도의 핵심이라 확인할 수 있어야 한다.
                handle_from=BrowserTools._fill_handle,
                undo=lambda handle: BrowserTools._undo_fill(self, handle),
            ),
        }

    @staticmethod
    def _toggle_handle_of(tools: Any, result: dict[str, Any]) -> dict[str, Any] | None:
        worker = getattr(tools, "worker", None)
        return None if worker is None else worker._toggle_handle(result)

    @staticmethod
    def _undo_toggle_of(tools: Any, handle: dict[str, Any]) -> dict[str, Any]:
        return tools.worker._undo_toggle(handle)

    @staticmethod
    def _submit_handle_of(tools: Any, result: dict[str, Any]) -> dict[str, Any] | None:
        """제출 손잡이는 **워커**가 만든다 — 그 화면에서 무엇을 채웠는지 아는 쪽이다."""
        worker = getattr(tools, "worker", None)
        if worker is None:
            return None
        return worker._submit_handle(result)

    @staticmethod
    def _fill_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        ref = str(result.get("undo_ref") or "")
        if not ref or "previous_value" not in result:
            # 원래 값을 못 읽었으면 무엇으로 되돌릴지 모른다. 안 내주는 편이 낫다.
            return None
        return {
            "ref": ref,
            "previous_value": str(result.get("previous_value") or ""),
            # 그 페이지에서만 유효하다. 다른 화면에서 같은 ref 는 딴 요소다.
            "url": str(result.get("url") or ""),
        }

    def _undo_fill(self, handle: dict[str, Any]) -> dict[str, Any]:
        ref = str(handle.get("ref") or "")
        was = str(handle.get("url") or "")
        now = str((self.worker.execute("browser_tabs", {}) or {}).get("url") or "")
        if was and now and was.split("#")[0] != now.split("#")[0]:
            # ref 는 그 화면의 것이다. 딴 데서 같은 번호를 쓰면 엉뚱한 칸을 덮어쓴다.
            raise RuntimeError(
                f"undo_fill_wrong_page: 채웠던 화면({was[:80]})이 아니라 지금은 {now[:80]} 이다"
            )
        return self.worker.execute(
            "browser_fill", {"ref": ref, "value": str(handle.get("previous_value") or "")}
        )
