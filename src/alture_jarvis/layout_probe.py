"""만든 화면을 **계산으로** 잰다 — 글자가 덮였나 · 가로로 삐져나갔나 · 그림이 깨졌나 (2026-10-11).

## 왜

코드 모드에 「디저트 가게 사이트를 예쁘게 만들어 줘」 한 문장을 맡긴 판(e936d144)에서, 품절 상품에 씌우려던 반투명 막이
카드가 아니라 **첫 화면 전체**를 덮었다(`position: absolute; inset: 0` 인데 부모에 기준이 없었다). 머리글이 뿌옇게 보였다.
손자리는 만든 페이지를 열어 읽고 눌러 봤지만 **글자로만** 봐서 몰랐다 — 글자는 거기 그대로 있었으니까.
같은 페이지를 「검토해 봐」라고 따로 시키자 코드를 읽어 원인을 정확히 찾았다. 즉 못 고치는 것이 아니라 못 본 것이다.

이런 결함은 눈대중이 아니라 계산으로 나온다: 글자 한가운데를 찍었을 때 맨 위에 있는 것이 그 글자가 아니면 덮인 것이다.
그래서 모델의 성실함에 기대지 않고(스킬 문서의 「화면을 찍어 확인하라」를 그 판은 따르지 않았다) 페이지를 열 때 도구가 잰다.

## 재는 것

- **덮인 글자** — 화면 안의 글자 요소마다 가운데 점을 찍어, 그 위에 **다른 큰 요소**가 있으면 센다. 같은 요소가 글자 둘 이상을
  덮을 때만 알린다. 열려 있는 대화 상자와 붙어 다니는 머리띠(fixed·sticky)는 덮는 것이 정상이라 뺀다.
- **가로 넘침** — 문서 폭이 화면 폭보다 넓으면, 삐져나간 요소 몇 개와 함께.
- **깨진 그림** — 다 받았는데 폭이 0 인 그림.

못생긴 것 · 어색한 정렬은 여기서 못 잰다. 그것은 눈으로 볼 일이다.

## 규율

- **이 PC 안 페이지에서만** 잰다(`file:` · localhost). 남의 사이트는 우리가 고칠 것이 아니다.
- 추측을 적지 않는다. 「부모에 기준이 빠진 것 같다」가 아니라 **잰 사실**을 적는다(「position:absolute 인데 기준이 문서 전체다」).
  틀린 안내는 막는 것보다 나쁘다.
- 재다 틀어지면 아무 말도 안 한다. 검사가 페이지 열기를 실패로 만들면 안 된다.
"""

from __future__ import annotations

import re
from typing import Any

#: 한 번에 훑는 화면 수(첫 화면부터 아래로). 긴 페이지를 끝까지 훑지는 않는다 — 열 때마다 도는 검사다.
MAX_SCREENS = 5

LAYOUT_PROBE_JS = r"""
(maxScreens) => {
  const out = { covered: [], overflow: null, broken_images: 0, dialog_open: false, screens: 0 };
  const vw = window.innerWidth, vh = window.innerHeight;
  if (!(vw > 0 && vh > 0)) return out;
  const style = (el) => window.getComputedStyle(el);
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const s = style(el);
    return s.visibility !== "hidden" && s.display !== "none" && parseFloat(s.opacity) > 0.05;
  };
  const label = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    const cls = (typeof el.className === "string" ? el.className : "").trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (cls.length) s += "." + cls.join(".");
    return s;
  };
  const pinned = (el) => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const p = style(n).position;
      if (p === "fixed" || p === "sticky") return true;
    }
    return false;
  };
  const texts = Array.from(document.querySelectorAll("h1,h2,h3,h4,p,li,a,button,label,td,th,figcaption,summary"))
    .filter((el) => shown(el) && (el.innerText || "").trim().length >= 2).slice(0, 600);
  const startX = window.scrollX, startY = window.scrollY;
  const pageHeight = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const byCover = new Map();
  const counted = new Set();
  for (let screen = 0; screen < maxScreens; screen++) {
    const top = screen * vh;
    if (screen > 0 && top >= pageHeight) break;
    window.scrollTo(0, top);
    out.screens = screen + 1;
    for (const el of texts) {
      if (counted.has(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.bottom <= 2 || r.top >= vh - 2 || r.right <= 2 || r.left >= vw - 2) continue;
      const x = Math.min(vw - 2, Math.max(1, r.left + Math.min(r.width / 2, 48)));
      const y = Math.min(vh - 2, Math.max(1, r.top + Math.min(r.height / 2, 14)));
      const hit = document.elementFromPoint(x, y);
      counted.add(el);
      if (!hit || hit === el || el.contains(hit) || hit.contains(el)) continue;
      if (hit.closest("dialog,[role=dialog],[aria-modal=true]")) { out.dialog_open = true; continue; }
      if (pinned(hit)) continue;
      const hr = hit.getBoundingClientRect();
      // 글자 옆의 작은 꾸밈(아이콘·배지)이 겹친 것은 덮은 것이 아니다 — 글자 요소보다 뚜렷이 클 때만.
      if (hr.width * hr.height < r.width * r.height * 1.5) continue;
      const hs = style(hit);
      const row = byCover.get(hit) || {
        by: label(hit), width: Math.round(hr.width), height: Math.round(hr.height), position: hs.position,
        anchored_to_page: hs.position === "absolute" && (!hit.offsetParent || hit.offsetParent === document.body
          || hit.offsetParent === document.documentElement),
        count: 0, samples: [],
      };
      row.count += 1;
      if (row.samples.length < 3) row.samples.push((el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 28));
      byCover.set(hit, row);
    }
  }
  window.scrollTo(startX, startY);
  out.covered = Array.from(byCover.values()).filter((r) => r.count >= 2).sort((a, b) => b.count - a.count).slice(0, 3);
  const docWidth = document.documentElement.scrollWidth;
  if (docWidth > vw + 8) {
    const wide = Array.from(document.querySelectorAll("body *")).filter((el) => {
      if (!shown(el)) return false;
      const r = el.getBoundingClientRect();
      return r.right > vw + 8 && r.width <= docWidth;
    }).slice(0, 200);
    // 가장 바깥에서 삐져나간 것만 — 그 안의 자식들까지 늘어놓지 않는다.
    const outer = wide.filter((el) => !wide.some((other) => other !== el && other.contains(el))).slice(0, 3).map(label);
    out.overflow = { by_px: Math.round(docWidth - vw), viewport: vw, elements: outer };
  }
  out.broken_images = Array.from(document.images).filter((img) => img.complete && img.naturalWidth === 0
    && (img.currentSrc || img.getAttribute("src"))).length;
  return out;
}
"""


def is_local_page(url: str) -> bool:
    """이 PC 안에서 띄운 페이지인가 — 우리가 만든 것이라 고칠 수 있는 페이지."""
    lowered = str(url or "").strip().lower()
    if lowered.startswith("file:"):
        return True
    host = re.sub(r"^[a-z]+://", "", lowered).split("/")[0].split(":")[0]
    return host in {"localhost", "127.0.0.1", "[::1]"} or host.endswith(".localhost")


def layout_issues(found: Any) -> list[str]:
    """잰 것을 모델이 읽을 줄로 — 잰 사실만 적는다. 문제가 없으면 빈 목록."""
    if not isinstance(found, dict):
        return []
    lines: list[str] = []
    for row in found.get("covered") or []:
        if not isinstance(row, dict) or int(row.get("count") or 0) < 2:
            continue
        samples = " · ".join(f"「{text}」" for text in (row.get("samples") or []) if text)
        fact = f"`{row.get('by')}`({row.get('width')}×{row.get('height')} · position:{row.get('position')})가 글자 {row.get('count')}곳 위를 덮고 있다"
        if row.get("anchored_to_page"):
            fact += " — 이 요소는 position:absolute 인데 기준이 되는 부모가 없어 **문서 전체**를 기준으로 깔려 있다"
        lines.append(fact + (f" (덮인 글: {samples})" if samples else "") + ".")
    overflow = found.get("overflow")
    if isinstance(overflow, dict) and int(overflow.get("by_px") or 0) > 0:
        names = ", ".join(f"`{name}`" for name in (overflow.get("elements") or []) if name)
        lines.append(
            f"페이지가 화면 폭({overflow.get('viewport')}px)보다 {overflow.get('by_px')}px 넓어 가로로 밀린다"
            + (f" — 삐져나간 요소: {names}" if names else "") + "."
        )
    broken = int(found.get("broken_images") or 0)
    if broken:
        lines.append(f"그림 {broken}개가 뜨지 않는다(주소가 틀렸거나 파일이 없다).")
    return lines


def layout_note(lines: list[str]) -> str:
    """페이지를 연 결과 맨 앞에 세울 한 덩어리. 뒤에 붙이면 긴 결과 속에 묻힌다."""
    if not lines:
        return ""
    return (
        "⚠ 화면 검사(계산으로 잰 것 — 글자로 읽어서는 안 보인다): " + " ".join(lines)
        + " 고친 뒤 이 페이지를 다시 열면 다시 잰다."
    )
