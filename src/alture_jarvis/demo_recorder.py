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
from typing import Any, Callable
from urllib.parse import urlparse

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
  // ★ 칸에서 Enter 를 치면 브라우저가 그 폼의 **제출 단추에 스스로 누르기(click)를 한 번 더 보낸다**(암묵적 제출). 사람이 누른 것이 아니다 —
  //   이걸 걸음으로 적으면 「Enter → (제출 단추 누르기) → 이동」이 되어 Enter 걸음 바로 뒤에 이동이 없어 확인 조건을 못 만든다
  //   (2026-10-28 운영 시험: 위키 검색칸 · `audit_log` 의 사건 순서 nav · fill · press · click · nav). 그 Enter 에서 비롯된 누르기만 거른다.
  let lastEnter = null;
  const impliedBy = (target, raw) => {
    if (!lastEnter || Date.now() - lastEnter.at > 500 || raw.detail !== 0) return false;
    const button = target.closest && target.closest('button,input[type=submit],input[type=image]');
    if (!button) return false;
    const type = (button.getAttribute('type') || '').toLowerCase();
    if (button.tagName.toLowerCase() === 'button' && type && type !== 'submit') return false;
    return !!(lastEnter.el && lastEnter.el.form && lastEnter.el.form === button.form);
  };
  document.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const el = e.target;
    if (!el || !el.tagName || secret(el)) return;
    lastEnter = {el, at: Date.now()};
    flush(el);
    send({kind: 'press', key: 'Enter', selectors: durable(el), field: fieldOf(el), url: location.href});
  }, true);
  document.addEventListener('click', e => {
    const raw = e.target;
    // 띠의 단추([다 했어] · [취소])를 누른 것은 사람이 가르치는 동작이 아니다 — 걸음으로 적지 않는다.
    if (raw && raw.closest && raw.closest('#sonjari-demo-badge')) return;
    if (raw && impliedBy(raw, e)) return;
    flushAll();
    if (!raw || !raw.closest) return;
    // 글을 치려고 칸을 누른 것은 걸음이 아니다 — 그 칸의 「채우기」가 대신한다(첫 시험: 검색칸 클릭이 확인 조건 없는 누르기가 됐다).
    const typable = node => {
      if (!node || !node.tagName) return false;
      const tag = node.tagName.toLowerCase();
      const type = (node.getAttribute('type') || 'text').toLowerCase();
      return node.isContentEditable || tag === 'textarea' || tag === 'select'
        || (tag === 'input' && ['text', 'search', 'email', 'url', 'tel', 'number', 'password', 'date'].includes(type));
    };
    if (typable(raw)) return;
    // ★ 글 칸을 **감싼 상자**나 글 칸에 붙은 **이름표**를 누른 것도 칸을 잡은 손동작이다 (2026-10-30 · 대표 10-29 판 감사 77033:
    //   click · fill · press … — 첫 누르기가 검색칸을 감싼 이름 없는 상자라 「다시 찾을 이름이 없다」로 보여 준 절차 전체가 거절됐다).
    //   누를 단추 · 링크 안이면 걸음이다. 상자 안에 글 칸이 **하나뿐**일 때만 그 칸을 잡은 것으로 본다(칸 여럿을 품은 큰 틀은 모른다).
    if (!raw.closest('a,button,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[role=checkbox],input[type=submit],input[type=button],input[type=checkbox],input[type=radio]')) {
      const label = raw.closest('label');
      if (label && typable(label.control)) return;
      const inside = raw.querySelectorAll ? raw.querySelectorAll('input,textarea,select,[contenteditable]') : [];
      if (inside.length === 1 && typable(inside[0])) return;
    }
    const el = raw.closest('a,button,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[role=checkbox],input[type=submit],input[type=button],input[type=checkbox],input[type=radio],label,summary') || raw;
    if (secret(el)) return;
    send({kind: 'click', selectors: durable(el), label: nameOf(el), url: location.href});
  }, true);
  window.addEventListener('pagehide', flushAll, true);
  window.__sonjariDemoFlush = flushAll;
  // ★ 새 문서가 뜰 때 **페이지가 직접** 주소를 알린다(2026-10-28). 파이썬이 듣는 `framenavigated` 만 믿었더니, 운영 크롬(붙은 크롬)에서
  //   위키 검색칸에 치고 Enter 한 시연에서 누른 뒤의 이동이 한 번도 안 적혀 「바뀐 것이 기록에 없어」 레시피로 못 옮겼다. 둘 중 하나만 와도 적힌다.
  //   바깥 문서(탑 프레임)만 — 광고 같은 안쪽 틀의 주소는 이동이 아니다.
  if (window.top === window) send({kind: 'nav_dom', url: location.href});
  // ★ 기록 중이면 화면에 띠를 보인다(2026-10-20 대표: 「화면에 뭐가 없으니까 미치겠네」). 띠 자체는 누르기를 가로채지 않는다(pointer-events: none) —
  //   **단추 둘([다 했어] · [취소])만** 눌린다(2026-10-28 · 「/레시피」). 단추는 파이썬이 쥔 같은 문(`__sonjariDemoControl`)으로 말을 보낸다.
  //   새 페이지로 넘어가도 다시 묻고 다시 그린다 — 기록 중인지는 파이썬이 쥐고 있다(`__sonjariDemoState`).
  //   누르거나 칠 때마다 적은 걸음 수가 올라간다 — 「지금 적히고 있다」를 눈으로 확인하게(대표: 「배우는 중인지 아닌지 우째 아노」).
  const BADGE = 'sonjari-demo-badge';
  const control = action => {
    try { if (window.__sonjariDemoControl) window.__sonjariDemoControl(action); } catch (e) {}
  };
  const button = (role, text, solid, action) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.setAttribute('data-role', role);
    el.textContent = text;
    el.setAttribute('style', 'pointer-events:auto;cursor:pointer;border:0;border-radius:14px;padding:4px 12px;margin:0;'
      + 'font:600 13px/1.4 sans-serif;' + (solid ? 'background:#fff;color:#c0392b;' : 'background:rgba(255,255,255,.22);color:#fff;'));
    el.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); control(action); }, true);
    return el;
  };
  window.__sonjariDemoBadge = state => {
    const on = !!(state && state.on);
    const old = document.getElementById(BADGE);
    if (!on) { if (old) old.remove(); return; }
    if (!document.documentElement) return;
    const en = !!(state && state.lang === 'en');
    const steps = Number((state && state.steps) || 0);
    const badge = old || document.createElement('div');
    badge.id = BADGE;
    badge.setAttribute('style', 'position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:2147483647;display:flex;align-items:center;gap:10px;'
      + 'background:#c0392b;color:#fff;font:600 14px/1.4 sans-serif;padding:6px 8px 6px 16px;border-radius:20px;'
      + 'box-shadow:0 2px 10px rgba(0,0,0,.3);pointer-events:none;');
    let label = badge.querySelector('[data-role=label]');
    if (!label) {
      label = document.createElement('span');
      label.setAttribute('data-role', 'label');
      badge.appendChild(label);
      badge.appendChild(button('done', en ? 'Done' : '다 했어', true, 'stop'));
      badge.appendChild(button('cancel', en ? 'Cancel' : '취소', false, 'cancel'));
    }
    label.textContent = en ? ('● Sonjari is learning · ' + steps + ' steps noted') : ('● 손자리가 배우는 중 · ' + steps + '걸음 적음');
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


def describe_event(event: dict[str, Any]) -> dict[str, Any]:
    """화면의 「배우는 중」 칸에 보낼 한 걸음 — 종류 · 요소 이름 · 어느 페이지. **입력한 글은 싣지 않는다**(칸 이름만)."""
    url = urlparse(str(event.get("url") or ""))
    where = (url.hostname or "") + (url.path if url.path not in {"", "/"} else "")
    return {
        "kind": str(event.get("kind") or ""),
        "name": str(event.get("label") or event.get("field") or "")[:60],
        "where": where[:80],
    }


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
        #: 화면 띠 · 앱 화면 언어 (`ko` · `en`). 본체가 시작 때 채운다.
        self.lang = "ko"
        #: 걸음이 적힐 때마다 부른다 — `{"n", "kind", "name", "where"}`. 본체가 앱 화면에 알리는 데 쓴다(없어도 기록은 간다).
        self.listener: Callable[[dict[str, Any]], None] | None = None
        #: 손자리 크롬 띠의 단추가 눌렸을 때 부른다 — `"stop"` · `"cancel"`.
        self.control_handler: Callable[[str], None] | None = None

    def start(self, url: str) -> None:
        with self._lock:
            self.recording, self.events, self.secrets_skipped = True, [], 0
            self.started_at, self.start_url = self._clock(), str(url or "")

    def state(self) -> dict[str, Any]:
        """화면 띠가 묻는 것 — 기록 중인가 · 지금까지 적은 걸음 수(이동은 빼고) · 화면 언어."""
        with self._lock:
            return {"on": self.recording, "steps": sum(1 for event in self.events if event.get("kind") != "nav"), "lang": self.lang}

    def recent_steps(self, limit: int = 40) -> list[dict[str, Any]]:
        """앱 화면이 늦게 붙었을 때 채울 지금까지의 걸음(이동 제외)."""
        with self._lock:
            kept = [event for event in self.events if event.get("kind") != "nav"]
        return [{"n": number, **describe_event(event)} for number, event in enumerate(kept, 1)][-limit:]

    def stop(self) -> list[dict[str, Any]]:
        with self._lock:
            self.recording = False
            return list(self.events)

    def on_event(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("kind") == "nav_dom":
            # 페이지가 직접 알린 새 문서 주소 — 파이썬이 듣는 이동과 같은 한 줄이다(같은 주소가 이어 오면 `on_navigation` 이 하나로 합친다).
            self.on_navigation(str(payload.get("url") or ""))
            return
        item: dict[str, Any] | None = None
        with self._lock:
            if not self.recording:
                return
            if payload.get("kind") == "secret":
                self.secrets_skipped += 1
                return
            event = {**payload, "at": self._clock()}
            self.events.append(event)
            if event.get("kind") != "nav":
                item = {"n": sum(1 for row in self.events if row.get("kind") != "nav"), **describe_event(event)}
        self._tell(item)

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

    def on_control(self, action: Any) -> None:
        """띠의 단추 — 기록 중일 때만 받는다."""
        with self._lock:
            live = self.recording
        if not live or str(action) not in {"stop", "cancel"} or self.control_handler is None:
            return
        try:
            self.control_handler(str(action))
        except Exception:  # noqa: BLE001 — 단추가 틀어져도 기록은 그대로다
            pass

    def _tell(self, item: dict[str, Any] | None) -> None:
        if item is None or self.listener is None:
            return
        try:
            self.listener(item)
        except Exception:  # noqa: BLE001 — 화면 알림이 틀어져도 기록은 간다
            pass


def _findable_label(label: str) -> bool:
    """누르기의 이름으로 다시 찾을 수 있나 — `recipe_from_run._selectors_for` 와 같은 기준(비지 않고 40자 이하)."""
    label = label.strip()
    return bool(label) and len(label) <= 40


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
            navigated = following.get("kind") == "nav" and float(following.get("at") or 0) - float(event.get("at") or 0) <= NAV_AFTER_ACTION_SEC
            if navigated:
                after = str(following.get("url") or url)
            elif following.get("url"):
                after = str(following.get("url"))
            if kind == "click" and not selectors and not _findable_label(str(event.get("label") or "")):
                # ★ **다시 찾을 이름이 없는 누르기** 하나로 보여 준 절차 전체를 버리지 않는다 (2026-10-30 · 대표 10-29 판).
                #   바로 뒤가 글 채우기면 그 칸을 잡은 손동작이다 — 채우기가 칸을 스스로 잡으니 뺀다.
                #   바로 뒤가 페이지 이동이면 사람이 간 곳은 그 주소다 — 「그 주소 열기」로 적는다(이어지는 이동은 이 걸음의 결과라 따로 안 적힌다).
                #   둘 다 아니면 그대로 둔다 — 빼면 다른 절차가 된다(펼침 단추 같은 것). 변환이 몇 번째 걸음인지 말하며 거절한다.
                if following.get("kind") == "fill":
                    continue
                if navigated and after.startswith("http") and after != url:
                    steps.append({"tool": "browser_open", "ok": True, "arguments": {"url": after}, "evidence": {"url": after}})
                    continue
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
