"""사람이 손자리 크롬에서 **한 번 해 보이면** 레시피 초안으로 (2026-10-20 · 확장 설계 P2 · T8 「배우기」).

P0 재생 실측(설계 §10): 잘 해낸 판에서 나온 「누르는 절차」는 2,623판 중 14개뿐이었고 다시 돈 것은 1/14 였다. 손자리는
잘 해낸 판에서 거의 다 검색 주소로 바로 간다 — 누르고 고르는 절차는 **사람이 보여 줘야** 생긴다(설계 §7 「낮으면 시연 입구를 앞당긴다」).

기록하는 것 · 안 하는 것:
  * 클릭 · 입력 · Enter · 이동을 **요소**(셀렉터 후보 · 이름)로 적는다. 좌표는 창 크기만 바뀌어도 깨진다(설계 §6).
  * 비밀번호 · 파일 칸은 값도 걸음도 적지 않는다 — 센 수만 남긴다(설계 §3-2).
  * 「배우기 시작」과 「다 했어」 사이에만 적는다. 그 밖의 사건은 받아도 버린다.
  * 출구는 하나다 — 기록을 판 기록과 같은 꼴로 바꿔 `recipe_from_run.draft_from_run` 에 넣는다. 확인 조건 · 추적 인자 · 빈칸 규칙이 같다.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .recipe_from_run import DraftRefused

#: 페이지마다 한 번 깔리는 기록기. `__sonjariDemo` 는 파이썬이 건 다리(`expose_binding`)다.
#: 셀렉터는 손자리가 누를 때 남기는 것과 **같은 함수**로 만든다(`browser._DURABLE_SELECTORS_JS`).
RECORDER_JS_TEMPLATE = """(() => {
  if (window.__sonjariDemoInstalled) return;
  window.__sonjariDemoInstalled = true;
  const durable = __DURABLE__;
  const send = payload => {
    try { if (window.__sonjariDemo) window.__sonjariDemo(payload); } catch (e) {}
    if (window.__sonjariDemoRefresh) window.__sonjariDemoRefresh();
  };
  const secret = el => {
    const type = ((el && el.getAttribute && el.getAttribute('type')) || '').toLowerCase();
    const auto = ((el && el.getAttribute && el.getAttribute('autocomplete')) || '').toLowerCase();
    return type === 'password' || type === 'file' || auto.includes('password') || auto.startsWith('cc-');
  };
  const nameOf = el => ((el.getAttribute('aria-label') || el.innerText || el.value || '').replace(/\\s+/g, ' ').trim()).slice(0, 60);
  const fieldOf = el => (el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.getAttribute('name') || '').trim().slice(0, 60);
  const pending = new Map();
  const secretSeen = new WeakSet();
  const flush = el => {
    const item = pending.get(el);
    if (!item) return;
    pending.delete(el);
    send(item);
  };
  const flushAll = () => { for (const el of Array.from(pending.keys())) flush(el); };
  document.addEventListener('input', e => {
    const el = e.target;
    if (!el || !el.tagName) return;
    if (secret(el)) { if (!secretSeen.has(el)) { secretSeen.add(el); send({kind: 'secret', url: location.href}); } return; }
    const value = el.isContentEditable ? (el.innerText || '') : (el.value || '');
    pending.set(el, {kind: 'fill', selectors: durable(el), field: fieldOf(el), value: String(value).slice(0, 300), url: location.href});
  }, true);
  document.addEventListener('change', e => {
    const el = e.target;
    if (!el || !el.tagName) return;
    if (el.tagName.toLowerCase() === 'select') {
      send({kind: 'select', selectors: durable(el), field: fieldOf(el), value: (el.options[el.selectedIndex] || {}).text || el.value, url: location.href});
      return;
    }
    flush(el);
  }, true);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const el = e.target;
    if (!el || !el.tagName || secret(el)) return;
    flush(el);
    send({kind: 'press', key: 'Enter', selectors: durable(el), field: fieldOf(el), url: location.href});
  }, true);
  document.addEventListener('click', e => {
    flushAll();
    const raw = e.target;
    if (!raw || !raw.closest) return;
    // 글을 치려고 칸을 누른 것은 걸음이 아니다 — 그 칸의 「채우기」가 대신한다(첫 시험: 검색칸 클릭이 확인 조건 없는 누르기가 됐다).
    const tag = raw.tagName.toLowerCase();
    const type = (raw.getAttribute('type') || 'text').toLowerCase();
    if (raw.isContentEditable || tag === 'textarea' || tag === 'select'
        || (tag === 'input' && ['text', 'search', 'email', 'url', 'tel', 'number', 'password', 'date'].includes(type))) return;
    const el = raw.closest('a,button,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[role=checkbox],input[type=submit],input[type=button],input[type=checkbox],input[type=radio],label,summary') || raw;
    if (secret(el)) return;
    send({kind: 'click', selectors: durable(el), label: nameOf(el), url: location.href});
  }, true);
  window.addEventListener('pagehide', flushAll, true);
  window.__sonjariDemoFlush = flushAll;
  // ★ 기록 중이면 화면에 띠를 보인다(2026-10-20 대표: 「화면에 뭐가 없으니까 미치겠네」). 누르기를 가로채지 않는다(pointer-events: none).
  //   새 페이지로 넘어가도 다시 묻고 다시 그린다 — 기록 중인지는 파이썬이 쥐고 있다(`__sonjariDemoState`).
  //   누르거나 칠 때마다 적은 걸음 수가 올라간다 — 「지금 적히고 있다」를 눈으로 확인하게(대표: 「배우는 중인지 아닌지 우째 아노」).
  const BADGE = 'sonjari-demo-badge';
  window.__sonjariDemoBadge = state => {
    const on = !!(state && state.on);
    const old = document.getElementById(BADGE);
    if (!on) { if (old) old.remove(); return; }
    if (!document.documentElement) return;
    const badge = old || document.createElement('div');
    badge.id = BADGE;
    const steps = Number((state && state.steps) || 0);
    badge.textContent = '● 손자리가 배우는 중 · ' + steps + '걸음 적음 — 다 하시면 손자리 대화창에 「다 했어」';
    badge.setAttribute('style', 'position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:2147483647;'
      + 'background:#c0392b;color:#fff;font:600 14px/1.4 sans-serif;padding:8px 16px;border-radius:20px;'
      + 'box-shadow:0 2px 10px rgba(0,0,0,.3);pointer-events:none;');
    if (!old) document.documentElement.appendChild(badge);
  };
  const showIfRecording = () => {
    try { if (window.__sonjariDemoState) window.__sonjariDemoState().then(state => window.__sonjariDemoBadge(state)); } catch (e) {}
  };
  window.__sonjariDemoRefresh = () => setTimeout(showIfRecording, 150);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', showIfRecording); else showIfRecording();
})();"""

#: 누른 뒤 이 시간 안에 일어난 이동은 그 누르기의 결과다(주소 입력창으로 간 것이 아니다).
NAV_AFTER_ACTION_SEC = 4.0


class DemoRecorder:
    """기록 상태와 사건 목록. 브라우저 스레드(다리 콜백)와 런타임 스레드가 같이 만지므로 잠근다."""

    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.recording = False
        self.events: list[dict[str, Any]] = []
        self.started_at = 0.0
        self.start_url = ""
        self.secrets_skipped = 0

    def start(self, url: str) -> None:
        with self._lock:
            self.recording, self.events, self.secrets_skipped = True, [], 0
            self.started_at, self.start_url = self._clock(), str(url or "")

    def state(self) -> dict[str, Any]:
        """화면 띠가 묻는 것 — 기록 중인가 · 지금까지 적은 걸음 수(이동은 빼고)."""
        with self._lock:
            return {"on": self.recording, "steps": sum(1 for event in self.events if event.get("kind") != "nav")}

    def stop(self) -> list[dict[str, Any]]:
        with self._lock:
            self.recording = False
            return list(self.events)

    def on_event(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        with self._lock:
            if not self.recording:
                return
            if payload.get("kind") == "secret":
                self.secrets_skipped += 1
                return
            self.events.append({**payload, "at": self._clock()})

    def on_navigation(self, url: str) -> None:
        url = str(url or "")
        if not url.startswith("http"):
            return
        with self._lock:
            if not self.recording:
                return
            if self.events and self.events[-1].get("kind") == "nav" and self.events[-1].get("url") == url:
                return
            self.events.append({"kind": "nav", "url": url, "at": self._clock()})


def steps_from_demo(events: list[dict[str, Any]], start_url: str = "") -> list[dict[str, Any]]:
    """기록을 **판 기록과 같은 꼴**(`agent_trace.steps`)로 바꾼다 — 그다음은 `draft_from_run` 이 똑같이 옮긴다.

    누르기 · Enter 바로 뒤(`NAV_AFTER_ACTION_SEC` 안)의 이동은 그 걸음의 결과 주소다(확인 조건 「주소가 바뀐다」의 근거).
    그 밖의 이동은 사람이 주소를 친 것이라 「연다」 걸음이 된다.
    """
    steps: list[dict[str, Any]] = []
    first_url = start_url or next((str(e.get("url") or "") for e in events if e.get("url")), "")
    if first_url.startswith("http") and not (events and events[0].get("kind") == "nav"):
        steps.append({"tool": "browser_open", "ok": True, "arguments": {"url": first_url}, "evidence": {"url": first_url}})
    ref = 0
    for index, event in enumerate(events):
        kind = str(event.get("kind") or "")
        url = str(event.get("url") or "")
        if kind == "nav":
            previous = events[index - 1] if index else {}
            caused = previous.get("kind") in {"click", "press"} and float(event.get("at") or 0) - float(previous.get("at") or 0) <= NAV_AFTER_ACTION_SEC
            if not caused:
                steps.append({"tool": "browser_open", "ok": True, "arguments": {"url": url}, "evidence": {"url": url}})
            continue
        ref += 1
        selectors = [str(s) for s in (event.get("selectors") or []) if str(s).strip()]
        if kind == "fill":
            steps.append({"tool": "browser_fill", "ok": True, "arguments": {"ref": f"d{ref}", "value": str(event.get("value") or "")},
                          "evidence": {"url": url, "selectors": selectors, "field": str(event.get("field") or "")}})
            continue
        if kind in {"click", "press"}:
            after = url
            following = events[index + 1] if index + 1 < len(events) else {}
            if following.get("kind") == "nav" and float(following.get("at") or 0) - float(event.get("at") or 0) <= NAV_AFTER_ACTION_SEC:
                after = str(following.get("url") or url)
            elif following.get("url"):
                after = str(following.get("url"))
            tool = "browser_click" if kind == "click" else "browser_press"
            arguments: dict[str, Any] = {"ref": f"d{ref}"}
            if kind == "press":
                arguments["key"] = str(event.get("key") or "Enter")
                # Enter 는 방금 채운 칸에서 누른다 — 같은 칸이면 같은 대상이 되게 채운 칸의 번호를 쓴다.
                last_fill = next((step for step in reversed(steps) if step["tool"] == "browser_fill"), None)
                if last_fill and last_fill["evidence"].get("selectors") == selectors:
                    arguments["ref"] = last_fill["arguments"]["ref"]
            steps.append({"tool": tool, "ok": True, "arguments": arguments,
                          "evidence": {"url": after, "selectors": selectors, "label": str(event.get("label") or "")}})
        if kind == "select":
            # 고르기는 아직 레시피 엔진에 걸음이 없다. 빼고 쓰면 **다른 절차**가 된다 — 쓰지 않는다(누르기의 확인 조건과 같은 규칙).
            raise DraftRefused(f"{len(steps) + 1}번째 걸음(목록에서 「{event.get('value') or ''}」 고르기)은 아직 레시피에 실을 수 없습니다")
    return steps
